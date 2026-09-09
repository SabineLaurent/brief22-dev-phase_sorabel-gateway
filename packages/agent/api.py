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
from packages.access import authorize, scope_for
from packages.text_to_sql_factory.handler import read_feedback
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    build_db_structured_answer,
)

from .cli import (
    EMPTY_CATALOGUE,
    CallNote,
    build_agent,
    call_record,
    compose_answer,
    served_status,
)
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

#: Ce que le sélecteur de l'interface affiche pour chaque rôle. Une table de **libellés**,
#: pas une seconde table de conversion : elle ne produit aucun profil et ne peut donc pas
#: diverger de la matrice. Elle vit ici parce que le front ne doit plus rien savoir des
#: rôles — il affiche ce que ``/roles`` lui rend.
_DISPLAY_BY_ROLE = {
    "support": "Support",
    "dev": "Dev",
    "commerciale": "Commerciale",
    "sans_role": "Sans rôle",
    "admin": "Admin",
}


def profile_for_role(role: str) -> str:
    """Le profil de matrice correspondant à un rôle de l'interface.

    Un rôle inconnu rend `default` — zéro droit. La matrice est totale, cette conversion
    l'est aussi : rien ne doit pouvoir produire un profil qui n'existe pas.
    """
    return _PROFILE_BY_ROLE.get(role, "default")


def rights_summary(role: str) -> str:
    """Ce que ce rôle peut faire, dit d'avance plutôt que découvert par un refus.

    Un `sans_role` doit apprendre à l'accueil qu'il n'obtiendra aucun chiffre : le lui
    laisser découvrir par un refus donnerait l'impression d'une panne.

    **Vit ici et non dans le front**, depuis le découplage : la phrase se déduit de la
    matrice, et un front qui la lirait lui-même en tiendrait une seconde copie — deux
    exemplaires d'une source d'autorité qui peuvent diverger dès que les deux processus ne
    partagent plus le même disque. C'est la règle déjà appliquée au catalogue à l'étape C,
    étendue à ce qui restait.
    """
    profile = profile_for_role(role)
    scope = scope_for(profile)
    # La documentation se lit dans la matrice, elle ne se promet pas en dur : `default` n'a
    # aucun tool, `search_docs` compris. L'étage 2 lui est désormais appliqué comme aux
    # quatre tools SQL, et le périmètre documentaire du profil part dans la requête — la
    # phrase dit donc ce qui se passe, plus seulement ce qui devrait se passer.
    docs = (" La documentation reste interrogeable." if "search_docs" in scope.tools
            else " La documentation ne lui est pas ouverte non plus.")
    if "ask_database" not in scope.tools:
        # Le cas de `dev` : il a `get_schema` et aucun tool de lecture de données. La forme
        # de la base, jamais son contenu — le dire évite de faire passer pour une panne un
        # schéma qui répond pendant qu'un chiffre est refusé.
        forme = (" Le **schéma** reste consultable : la forme de la base, pas son contenu."
                 if "get_schema" in scope.tools else "")
        return (f"profil `{profile}` — **aucun chiffre** : les questions sur les données "
                f"seront refusées.{docs}{forme}")
    sensitive = {("produits", "prix_achat_ht"), ("produits", "marge_pct"),
                 ("ventes", "marge_ht")}
    marges = ("marges et prix d'achat compris" if sensitive <= scope.columns
              else "**sans** les marges ni le prix d'achat")
    return (f"profil `{profile}` — base interrogeable sur {len(scope.columns)} colonnes, "
            f"{marges}.")


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


class ToolCall(BaseModel):
    """Un appel de tool tel qu'il s'est passé, réduit à ce qu'une colonne peut montrer.

    Ni payload ni message : c'est de l'**observabilité d'interface**, pas une seconde voie
    de sortie des données. Le nom du tool dit quel étage a servi, le code dit ce que la
    matrice en a fait — les deux seuls faits qui distinguent visuellement deux profils sur
    la même question.
    """

    tool: str
    status: str
    code: str


class ChatResponse(BaseModel):
    answer: str
    #: Une **phrase figée**, jamais un message d'exception. L'interface l'affiche tel quel.
    error: str | None = None
    #: Les tools appelés pendant cette question, dans l'ordre. Vide quand le modèle n'a rien
    #: appelé — catalogue vide, ou question à laquelle il répond sans outil.
    calls: list[ToolCall] = []
    #: Ce qui s'est passé pendant le tour, en un mot — ``cli.served_status``. **Calculé sur
    #: le carnet, jamais sur le texte** : le client n'a pas à juger un contenu pour savoir
    #: si l'utilisateur a obtenu sa réponse, et il ne le peut pas. Sans ce champ, le
    #: comparateur relisait `calls` avec sa propre règle — une seconde lecture du même
    #: carnet, donc une divergence en attente.
    statut: str = "ok"


class CatalogueResponse(BaseModel):
    """Les tools que ce rôle voit — l'**étage 1**, tel que ``tools/list`` le sert.

    Lu sur le serveur et non dans ``matrice.yaml`` : c'est le catalogue effectif qu'on veut
    montrer, pas la déclaration dont il dérive. Les deux doivent coïncider, et c'est
    justement ce qu'une interface qui les affiche permet de constater.
    """

    profile: str
    tools: list[str] = []


class RoleCard(BaseModel):
    """Un rôle proposé par l'interface : son identifiant, son libellé, et ses droits en clair.

    ``summary`` est calculé sur la matrice à chaque appel, jamais figé : c'est ce qui permet
    au front de l'afficher sans jamais lire ``matrice.yaml``.
    """

    role: str
    display_name: str
    summary: str


class RolesResponse(BaseModel):
    """Les rôles que l'interface peut proposer.

    **Le front n'en tient pas de liste.** Une liste en dur y divergerait de la matrice le jour
    où un profil y est ajouté — c'est exactement le défaut que ``scripts/mcp_client.py`` a
    corrigé de son côté en ouvrant ``--profile`` aux profils lus dans la matrice. La même
    règle vaut ici.
    """

    roles: list[RoleCard] = []


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


def _calls_of(book: list[CallNote]) -> list[ToolCall]:
    """Le carnet, mis à plat pour l'affichage. Le carnet lui-même ne sort pas de l'API."""
    return [
        ToolCall(tool=note.tool, status=note.envelope["status"],
                 code=note.envelope["payload"]["code"])
        for note in book
    ]


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    # Un rôle inconnu n'est pas renvoyé en écho : le répéter à l'écran fait de la réponse un
    # miroir de l'entrée, et la matrice retombe déjà sur `default` sans qu'on ait à le dire.
    if request.role not in ROLES:
        return ChatResponse(answer="", error=CLIENT_MESSAGES["argument_malforme"],
                            statut="error")

    profile = profile_for_role(request.role)
    with call_record(request.question) as book:
        try:
            agent = await _agent_for(profile)
            # Catalogue vide : pas d'appel possible, donc rien à faire rédiger. La phrase
            # figée du refus part directement — cf. `cli.build_agent`.
            if agent is None:
                # `refused` et non « aucun appel » : rien n'a été appelé parce que l'étage 1
                # a tout retiré du catalogue. C'est un refus de la matrice, et le dire au
                # badge rend cet étage aussi lisible que les deux autres.
                return ChatResponse(answer=EMPTY_CATALOGUE, statut="refused")
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
            return ChatResponse(answer="", error=CLIENT_MESSAGES["erreur_execution"],
                                statut="error")

        # Une phrase figée gagne sur le texte rédigé : le refus ne se renégocie pas au
        # dernier mètre. Mais il ne se substitue à la réponse que si **rien** n'a été servi
        # — sinon il la complète, et `compose_answer` tranche pour la CLI comme pour ici.
        return ChatResponse(answer=compose_answer(book, response["messages"][-1].content),
                            calls=_calls_of(book), statut=served_status(book))


def role_cards() -> list[RoleCard]:
    """Les rôles servis au front, dans l'ordre de ``ROLES``.

    Fonction pure, sans requête ni session : c'est elle que les contrôles exercent, et c'est
    ce qui permet de vérifier l'accord avec la matrice sans lancer un serveur.
    """
    return [RoleCard(role=role, display_name=_DISPLAY_BY_ROLE.get(role, role),
                     summary=rights_summary(role))
            for role in ROLES]


@app.get("/roles", response_model=RolesResponse)
def roles() -> RolesResponse:
    """Les rôles proposés par l'interface, avec leurs droits en clair.

    Route ajoutée au découplage du front : c'est elle qui remplace les deux imports que
    ``web_client`` faisait du backend. Elle n'ouvre **aucune** session MCP — contrairement à
    ``/catalogue`` —, elle est donc appelable à l'accueil sans lancer de sous-processus.
    """
    return RolesResponse(roles=role_cards())


@app.get("/catalogue", response_model=CatalogueResponse)
async def catalogue(role: str) -> CatalogueResponse:
    """Le catalogue de ce rôle, demandé au serveur qui le sert.

    Ouvre la session du profil si elle ne l'est pas — c'est voulu : l'interface de
    comparaison appelle cette route **en même temps** que la première question, jamais à
    l'accueil. Quatre sessions ouvertes pour afficher un en-tête coûteraient quatre
    sous-processus à qui personne n'a rien demandé.
    """
    profile = profile_for_role(role)
    if role not in ROLES:
        return CatalogueResponse(profile=profile)
    gateway = await GATEWAYS.get(profile)
    return CatalogueResponse(
        profile=profile, tools=[card.name for card in await gateway.catalogue()]
    )


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
