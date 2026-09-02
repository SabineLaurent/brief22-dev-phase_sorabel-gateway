"""Agent conversationnel LangChain, minimal, pour rejouer à la main les questions
d'``eval/questions_rag.jsonl``.

Un seul outil, ``search_docs``, qui appelle ``retrieval.search.search()``. Pas de
mémoire : chaque question part d'un historique vide, l'agent n'a que la question
posée et ce que l'outil lui rend.

Usage :
    uv run python scripts/rag_chat.py
    uv run python scripts/rag_chat.py --strategy dense
"""

from __future__ import annotations

import argparse

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import settings
from retrieval.search import Strategy, citation, search

_SYSTEM_PROMPT = (
    "Tu réponds aux questions sur le catalogue et les procédures Sorabel en "
    "t'appuyant uniquement sur l'outil search_docs — jamais sur tes propres "
    "connaissances. Cite systématiquement la référence et le titre des sources "
    "utilisées. Si l'outil signale que le corpus ne couvre pas la question, dis-le "
    "clairement au lieu d'inventer une réponse."
)


def _build_executor(strategy: Strategy) -> AgentExecutor:
    @tool
    def search_docs(query: str) -> str:
        """Cherche dans le corpus documentaire Sorabel ; rend les résultats ou un refus motivé."""
        result = search(query, strategy=strategy)
        if result.is_out_of_corpus:
            return result.message
        return "\n\n".join(
            f"[{citation(hit)['reference']}] {citation(hit)['titre']} "
            f"(score {hit.score:.3f})\n{hit.text}"
            for hit in result.hits
        )

    if not settings.azure_chat_deployment:
        raise RuntimeError(
            "AZURE_CHAT_DEPLOYMENT n'est pas renseigné dans .env — c'est le déploiement "
            "de chat que cet agent appelle."
        )

    llm = ChatOpenAI(
        base_url=f"{settings.azure_ai_endpoint.rstrip('/')}/openai/v1",
        api_key=SecretStr(settings.azure_ai_api_key),
        model=settings.azure_chat_deployment,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    agent = create_tool_calling_agent(llm, [search_docs], prompt)
    return AgentExecutor(agent=agent, tools=[search_docs])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        choices=["dense", "lexical", "hybrid"],
        default="hybrid",
        help="étage de recherche appelé par l'outil (défaut : hybrid, le meilleur mesuré).",
    )
    args = parser.parse_args()

    executor = _build_executor(args.strategy)
    print(f"Agent RAG Sorabel — étage « {args.strategy} ». Ctrl+D pour quitter.")
    while True:
        try:
            question = input("\n> ").strip()
        except EOFError:
            print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break
        response = executor.invoke({"input": question})
        print(response["output"])


if __name__ == "__main__":
    main()
