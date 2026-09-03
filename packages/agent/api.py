"""API FastAPI de l'agent conversationnel, consommée par l'interface web de test.

Le rôle **a désormais un effet réel sur le SQL** : il est converti en profil de la matrice,
qui décide du droit d'interroger la base et des colonnes atteignables. Il reste sans effet
sur la recherche documentaire, inchangée.

C'est un **banc d'essai**, et un écart assumé : le profil est ici déclaré par le client,
alors que la conception veut ``SORABEL_PROFILE`` lu au lancement du serveur MCP et jamais
reçu du client (cf. docs/cadrage_dsi.md et matrice.yaml). Il disparaît au chantier 3.

Lancement : uv run uvicorn packages.agent.api:app --reload
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel

from packages.rag_machines.retrieval.search import Strategy

from .cli import build_agent

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
    error: str | None = None


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
    if request.role not in ROLES:
        return ChatResponse(answer="", error=f"rôle inconnu : {request.role}")
    try:
        agent = _agent_for(request.strategy, profile_for_role(request.role))
        response = agent.invoke({"messages": [{"role": "user", "content": request.question}]})
        return ChatResponse(answer=response["messages"][-1].content)
    except Exception as exc:  # appel Azure chat encore en échec connu (404) — remonté proprement
        return ChatResponse(answer="", error=str(exc))
