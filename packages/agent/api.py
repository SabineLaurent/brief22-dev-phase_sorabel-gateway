"""API FastAPI de l'agent conversationnel, consommée par l'interface web de test.

Le rôle est pour l'instant une simple étiquette transmise avec la question : rien ne la
filtre encore, la matrice d'accès n'est appliquée qu'avec le serveur MCP (chantier
suivant, cf. docs/cadrage_dsi.md).

Lancement : uv run uvicorn packages.agent.api:app --reload
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel

from packages.rag_machines.retrieval.search import Strategy

from .cli import build_agent

ROLES = ["support", "dev", "commerciale", "sans_role", "admin"]

app = FastAPI(title="Sorabel Data Gateway — API de test")


class ChatRequest(BaseModel):
    role: str
    question: str
    strategy: Strategy = "hybrid"


class ChatResponse(BaseModel):
    answer: str
    error: str | None = None


@lru_cache(maxsize=None)
def _agent_for(strategy: Strategy):  # type: ignore[no-untyped-def]
    return build_agent(strategy)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if request.role not in ROLES:
        return ChatResponse(answer="", error=f"rôle inconnu : {request.role}")
    try:
        agent = _agent_for(request.strategy)
        response = agent.invoke({"messages": [{"role": "user", "content": request.question}]})
        return ChatResponse(answer=response["messages"][-1].content)
    except Exception as exc:  # appel Azure chat encore en échec connu (404) — remonté proprement
        return ChatResponse(answer="", error=str(exc))
