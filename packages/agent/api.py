"""API FastAPI de l'agent conversationnel, consommée par l'interface web de test.

Le rôle **a désormais un effet réel sur le SQL** : il est converti en profil de la matrice,
qui décide du droit d'interroger la base et des colonnes atteignables. Il reste sans effet
sur la recherche documentaire, inchangée.

C'est un **banc d'essai**, et un écart assumé : le profil est ici déclaré par le client,
alors que la conception veut ``SORABEL_PROFILE`` lu au lancement du serveur MCP et jamais
reçu du client (cf. docs/cadrage_dsi.md et matrice.yaml). Il disparaît au chantier 3.

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
from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from config import settings as gateway_settings
from packages import journal
from packages.access import authorize
from packages.rag_machines.retrieval.search import Strategy
from packages.text_to_sql_factory.handler import read_feedback
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    build_db_structured_answer,
)

from .cli import build_agent, call_record, frozen_text

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


app = FastAPI(title="Sorabel Data Gateway — API de test")


class ChatRequest(BaseModel):
    role: str
    question: str
    strategy: Strategy = "hybrid"


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


@lru_cache(maxsize=None)
def _agent_for(strategy: Strategy, profile: str):  # type: ignore[no-untyped-def]
    """Un agent par couple (stratégie, profil).

    Le profil est capturé à la construction du tool : mis en cache sur la seule stratégie,
    le premier rôle utilisé serait servi à tous les suivants — et un `sans_role` hériterait
    des droits d'un `commerciale` passé avant lui.
    """
    return build_agent(strategy, profile)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    # Un rôle inconnu n'est pas renvoyé en écho : le répéter à l'écran fait de la réponse un
    # miroir de l'entrée, et la matrice retombe déjà sur `default` sans qu'on ait à le dire.
    if request.role not in ROLES:
        return ChatResponse(answer="", error=CLIENT_MESSAGES["argument_malforme"])

    profile = profile_for_role(request.role)
    with call_record() as book:
        try:
            agent = _agent_for(request.strategy, profile)
            response = agent.invoke(
                {"messages": [{"role": "user", "content": request.question}]}
            )
        except Exception as error:  # noqa: BLE001 - dernier filet avant l'écran
            # La trace va au journal, entière ; l'écran reçoit une phrase figée. Le tool est
            # nommé `chat` : ce n'est pas un tool du catalogue, mais c'est bien un appel qui
            # a échoué, et le retrouver au journal est précisément ce qu'on veut au débug.
            journal.record(
                "chat", profile, {"question": request.question, "strategy": request.strategy},
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
