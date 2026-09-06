"""Le lien client entre le banc d'essai et le serveur MCP.

**C'est le seul endroit du code servi qui parle le protocole MCP.** L'agent, l'API et la
CLI ne voient que deux choses : un catalogue de tools et une enveloppe
``{status, payload, message}``. Ils ignorent qu'un sous-processus existe.

Ce module fait tomber l'écart le plus visible du banc d'essai : **le profil n'est plus un
argument**. Il est écrit dans ``SORABEL_PROFILE``, dans l'environnement du sous-processus
serveur, et il n'apparaît dans la signature d'aucun appel. Le LLM ne peut donc pas
l'écrire — ni par erreur, ni par instruction reçue dans une question. Auparavant
``build_agent(strategy, profile)`` le capturait en closure : rien n'empêchait
structurellement de le faire varier, seule la discipline du code le tenait.

Deux conséquences que le branchement apporte sans qu'on ait à les coder :

* **l'étage 1 devient visible.** Les tools de l'agent sont ceux que ``tools/list`` rend,
  donc filtrés par ``authorize()`` côté serveur. Un profil ``default`` construit un agent
  à zéro tool ; ``support`` en a sept, sans ``get_schema``. Le catalogue en dur du banc
  d'essai disparaît, et avec lui la possibilité qu'il diverge de la matrice ;
* **les quatre tools documentaires passent enfin par leur handler**, donc par l'étage 2,
  le seuil de refus et la journalisation. Le ``search_docs`` du banc d'essai les
  court-circuitait tous les trois.

**Une session par profil, gardée ouverte.** Le sous-processus serveur charge l'embedder
et le reranker au premier appel documentaire (mesuré : 5,3 s, puis 0,16 s) ; le rouvrir à
chaque question repaierait ce coût à chaque fois. Les sessions s'ouvrent
paresseusement — cinq sous-processus pré-chargés tiendraient cinq modèles en mémoire pour
un banc d'essai qui n'en utilise qu'un à la fois.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

#: Le serveur est lancé depuis la racine du dépôt, et ce n'est pas cosmétique :
#: ``logs/journal.jsonl`` est un chemin relatif, et un ``cwd`` différent créerait un
#: second journal au lieu d'alimenter celui que ``make journal`` lit.
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_MODULE = "mcp_server.server"

#: Même borne que la suite d'acceptance, et pour la même raison : un appel qui ne rend
#: pas la main doit échouer, pas suspendre l'interface.
CALL_TIMEOUT = float(os.environ.get("GATEWAY_TEST_TIMEOUT", "30"))


@dataclass(frozen=True)
class ToolCard:
    """Ce que le serveur dit d'un tool : son nom, sa description, son schéma d'arguments.

    Rien n'est réécrit ici. Les descriptions sont **le seul aiguillage** de la gateway
    (``mcp_server/server.py``) : les recopier côté client les ferait diverger du jour où
    l'une des deux serait retouchée.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


class Gateway:
    """Une session ouverte vers le serveur, sous un profil fixé à l'ouverture."""

    def __init__(self, profile: str, session: ClientSession) -> None:
        self.profile = profile
        self._session = session

    async def catalogue(self) -> list[ToolCard]:
        """Les tools que **ce profil** voit — l'étage 1, tel que le serveur l'applique."""
        listed = await asyncio.wait_for(self._session.list_tools(), CALL_TIMEOUT)
        return [
            ToolCard(tool.name, (tool.description or "").strip(), dict(tool.inputSchema))
            for tool in listed.tools
        ]

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Appelle un tool et rend l'enveloppe décodée du contrat d'intégration.

        Le profil n'est pas un paramètre : il appartient au processus d'en face.
        """
        result = await asyncio.wait_for(
            self._session.call_tool(tool, arguments), CALL_TIMEOUT
        )
        # `getattr` et non `block.text` : le protocole autorise cinq types de bloc et un
        # seul en porte. La gateway ne rend que du texte, mais le type de retour du SDK
        # dit l'inverse — on lit ce qui est là, on ne postule pas.
        texts = [text for block in result.content if (text := getattr(block, "text", None))]
        if not texts:
            raise RuntimeError(f"réponse vide du tool {tool}")
        envelope: dict[str, Any] = json.loads(texts[0])
        envelope.setdefault("payload", {})
        envelope.setdefault("message", "")
        return envelope


@asynccontextmanager
async def gateway_session(profile: str) -> AsyncIterator[Gateway]:
    """Lance un serveur MCP sous ``profile`` et tient la session le temps du contexte."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
        env={**os.environ, "SORABEL_PROFILE": profile},
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), CALL_TIMEOUT)
            yield Gateway(profile, session)


class GatewayRegistry:
    """Une session par profil, ouverte au premier besoin, fermée toutes ensemble.

    L'API sert plusieurs rôles dans un même processus : chacun a son sous-processus
    serveur, donc son profil, donc ses droits. Deux rôles ne peuvent pas se mélanger —
    non par convention, mais parce qu'ils ne parlent pas au même processus.

    **Chaque session est ouverte et fermée dans une tâche à elle**, et ce n'est pas un
    choix de style : ``stdio_client`` ouvre un groupe de tâches anyio, dont la portée
    d'annulation doit être quittée par la tâche qui l'a entrée. Ouvrir la session dans une
    requête et la fermer à l'arrêt de l'application — deux tâches différentes — lèverait
    une erreur au moment précis où l'on cherche à ranger proprement. La tâche gardienne
    ouvre, publie la session, puis attend le signal d'arrêt sans rien faire d'autre.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Gateway] = {}
        self._keepers: list[asyncio.Task[None]] = []
        self._closing = asyncio.Event()
        self._lock = asyncio.Lock()

    async def get(self, profile: str) -> Gateway:
        # Le verrou n'est pas décoratif : deux requêtes simultanées sur un profil neuf
        # lanceraient deux serveurs, et l'un des deux ne serait jamais fermé.
        async with self._lock:
            if profile not in self._sessions:
                ready: asyncio.Future[Gateway] = asyncio.get_running_loop().create_future()
                self._keepers.append(asyncio.create_task(self._keep(profile, ready)))
                self._sessions[profile] = await ready
            return self._sessions[profile]

    async def _keep(self, profile: str, ready: asyncio.Future[Gateway]) -> None:
        """Ouvre la session, la publie, et la tient jusqu'à l'arrêt."""
        try:
            async with gateway_session(profile) as gateway:
                ready.set_result(gateway)
                await self._closing.wait()
        except Exception as error:  # noqa: BLE001 - remonté à l'appelant qui attend
            if not ready.done():
                ready.set_exception(error)
            else:
                raise

    async def aclose(self) -> None:
        self._closing.set()
        await asyncio.gather(*self._keepers, return_exceptions=True)
        self._keepers.clear()
        self._sessions.clear()
        self._closing.clear()


async def build_tools(
    gateway: Gateway, render: Callable[[str, dict[str, Any]], str]
) -> list[StructuredTool]:
    """Adapte le catalogue du serveur en tools LangChain, sans rien y ajouter.

    ``StructuredTool`` accepte un ``args_schema`` sous forme de dictionnaire JSON Schema :
    l'``inputSchema`` rendu par le serveur passe donc tel quel, sans modèle Pydantic
    reconstruit et sans dépendance d'adaptation. Nom et description viennent du serveur
    eux aussi — les recopier ici les ferait diverger de l'aiguillage réel.

    ``render`` est le seul point d'extension : il reçoit le nom du tool et l'enveloppe, et
    rend le texte que le modèle lira. C'est l'appelant qui décide ce qu'un modèle a le
    droit de voir d'une enveloppe, et c'est lui qui tient le carnet de l'appel — ce module
    ne connaît que le protocole.
    """
    return [
        StructuredTool(
            name=card.name,
            description=card.description,
            args_schema=card.input_schema,
            coroutine=_proxy(gateway, card.name, render),
        )
        for card in await gateway.catalogue()
    ]


def _proxy(
    gateway: Gateway, tool: str, render: Callable[[str, dict[str, Any]], str]
) -> Callable[..., Awaitable[str]]:
    """La coroutine appelée par LangChain quand le modèle choisit ``tool``."""

    async def call(**arguments: Any) -> str:
        return render(tool, await gateway.call(tool, arguments))

    return call
