"""API FastAPI de l'agent conversationnel, consommée par l'interface web de test.

Le rôle **choisit un processus, plus un argument.** ``profile_for_role()`` le convertit en
profil de matrice, et ce profil sert à désigner *quel sous-processus serveur MCP* on
interroge — chacun lancé avec son ``SORABEL_PROFILE``. L'écart du banc d'essai est donc
refermé : le profil n'est plus déclaré par le client, il est une propriété du processus
d'en face, et le LLM n'a aucun moyen de l'atteindre.

Le rôle a désormais un effet réel sur **les deux domaines** : la base *et* le corpus. Le
raccourci documentaire du banc d'essai — étage 2 en dur, seuil de refus contourné — a
disparu avec le branchement.

**Rien de technique ne franchit cette frontière.** Ce module est le dernier point avant
l'écran, et il applique deux règles :

* une phrase figée déposée au carnet de l'appel (``cli.call_record``) part **telle quelle**,
  sans repasser par le modèle. C'est ce qui rend l'affichage aussi déterministe que la
  décision — un refus reformulé par un LLM produit une phrase différente à chaque fois ;
* une panne rend une phrase figée elle aussi, et la trace part au **journal**. La version
  précédente renvoyait ``str(exc)``, que l'interface Chainlit affichait ensuite à
  l'utilisateur : un message d'exception de SDK sous les yeux d'un agent du support.

Lancement : uv run uvicorn packages.agent.api:app --reload
"""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from config import settings as gateway_settings
from packages import journal
from packages.access import authorize
from packages.text_to_sql_factory.handler import read_feedback
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    build_db_structured_answer,
)

from .cli import EMPTY_CATALOGUE, build_agent, call_record, frozen_text
from .gateway import GatewayRegistry

ROLES = ["support", "dev", "commerciale", "sans_role", "admin"]

#: Les rôles affichés par l'interface ne portent pas les noms des profils de la matrice :
#: `commerciale` (UI) vaut `commercial` (matrice), et `sans_role` vaut `default` — le profil
#: à zéro droit, qui est la valeur de repli du modèle et non une exception. C'est le seul
#: endroit de la conversion : une seconde table finirait par diverger.
_PROFILE_BY_ROLE = {
    "support": "support",
    "dev": "dev",
    "commerciale": "commercial",
    "sans_role": "default",
    "admin": "admin",
}

def profile_for_role(role: str) -> str:
    """Le profil de matrice correspondant à un rôle de l'interface.

    Un rôle inconnu rend `default` — zéro droit. La matrice est totale, cette conversion
    l'est aussi : rien ne doit pouvoir produire un profil qui n'existe pas.
    """
    return _PROFILE_BY_ROLE.get(role, "default")


#: Les sessions MCP ouvertes par cette API, une par profil. Vit au niveau du module et non
#: dans l'état de l'application : ``build_agent`` en a besoin à la construction, et un
#: registre par instance de ``FastAPI`` n'apporterait rien à un banc d'essai à un processus.
GATEWAYS = GatewayRegistry()

#: Un agent par profil. Le profil est dans la clé pour la même raison qu'avant : partagé,
#: le premier rôle utilisé serait servi à tous les suivants, et un `sans_role` hériterait
#: des droits d'un `commerciale` passé avant lui. La différence est qu'aujourd'hui cette
#: séparation est **doublée** par celle des processus serveur.
_AGENTS: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Les sous-processus serveur s'ouvrent au premier besoin et se ferment tous ici.

    Sans cette fermeture, arrêter l'API laisserait derrière elle autant de serveurs MCP
    que de rôles utilisés — chacun tenant son embedder en mémoire.
    """
    try:
        yield
    finally:
        await GATEWAYS.aclose()
        _AGENTS.clear()


app = FastAPI(title="Sorabel Data Gateway — API de test", lifespan=lifespan)


class ChatRequest(BaseModel):
    role: str
    question: str


class ChatResponse(BaseModel):
    answer: str
    #: Une **phrase figée**, jamais un message d'exception. L'interface l'affiche tel quel.
    error: str | None = None


class JournalResponse(BaseModel):
    """Les entrées du journal, rendues entières — trace d'exception comprise.

    C'est assumé : ce n'est pas une commodité d'affichage mais la surface de débug métier, et
    l'expurger la rendrait inutile à ce pour quoi elle existe. Sa protection est son droit
    d'accès, pas son contenu.
    """

    status: str
    message: str
    entries: list[dict[str, Any]] = []


async def _agent_for(profile: str):  # type: ignore[no-untyped-def]
    """L'agent de ce profil, construit sur le catalogue que **son** serveur lui sert.

    Le catalogue est lu une fois, à la construction : il ne peut pas changer en cours de
    route, puisque le profil du processus d'en face ne change pas non plus.
    """
    if profile not in _AGENTS:
        _AGENTS[profile] = await build_agent(await GATEWAYS.get(profile))
    return _AGENTS[profile]


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    # Un rôle inconnu n'est pas renvoyé en écho : le répéter à l'écran fait de la réponse un
    # miroir de l'entrée, et la matrice retombe déjà sur `default` sans qu'on ait à le dire.
    if request.role not in ROLES:
        return ChatResponse(answer="", error=CLIENT_MESSAGES["argument_malforme"])

    profile = profile_for_role(request.role)
    with call_record() as book:
        try:
            agent = await _agent_for(profile)
            # Catalogue vide : pas d'appel possible, donc rien à faire rédiger. La phrase
            # figée du refus part directement — cf. `cli.build_agent`.
            if agent is None:
                return ChatResponse(answer=EMPTY_CATALOGUE)
            response = await agent.ainvoke(
                {"messages": [{"role": "user", "content": request.question}]}
            )
        except Exception as error:  # noqa: BLE001 - dernier filet avant l'écran
            # La trace va au journal, entière ; l'écran reçoit une phrase figée. Le tool est
            # nommé `chat` : ce n'est pas un tool du catalogue, mais c'est bien un appel qui
            # a échoué, et le retrouver au journal est précisément ce qu'on veut au débug.
            journal.record(
                "chat", profile, {"question": request.question},
                build_db_structured_answer(
                    "erreur_execution",
                    cause=f"{type(error).__name__}: {error}",
                    stack=traceback.format_exc(),
                ),
            )
            return ChatResponse(answer="", error=CLIENT_MESSAGES["erreur_execution"])

        # Une phrase figée gagne sur le texte rédigé : le refus ne se renégocie pas au
        # dernier mètre.
        frozen = frozen_text(book)
        if frozen is not None:
            return ChatResponse(answer=frozen)
        return ChatResponse(answer=response["messages"][-1].content)


@app.get("/journal", response_model=JournalResponse)
def read_journal(role: str, limit: int = 50) -> JournalResponse:
    """Le journal, rendu au front — **réservé au rôle qui en a le droit par la matrice**.

    L'autre moitié de la journalisation : sans lecture, le journal ne se consulte qu'en se
    connectant à la machine. Le garde-fou n'est pas ici, il est dans la matrice — cette
    route ne fait que convertir un rôle d'interface en profil et transmettre.
    """
    view = read_feedback(profile_for_role(role), limit)
    return JournalResponse(
        status=view["status"],
        message=view["message"],
        entries=view["payload"].get("entries", []),
    )


@app.get("/journal/allowed")
def journal_allowed(role: str) -> dict[str, bool]:
    """Ce rôle peut-il lire le journal ? Sert à l'interface pour ne pas proposer un bouton
    qui refusera de toute façon. Ce n'est **pas** la barrière — la barrière est dans
    ``read_journal``, et elle est journalisée."""
    return {"allowed": authorize(profile_for_role(role), gateway_settings.journal_reader_tool)}
