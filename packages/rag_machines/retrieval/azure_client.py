"""Client OpenAI partagé pour Azure AI Foundry, **API v1**.

``AzureEmbedder`` (``retrieval/embedder.py``) et ``AzureReranker`` (``retrieval/reranker.py``)
parlent tous deux à Azure AI Foundry en OpenAI-compatible de la même façon — même
``base_url``, même import paresseux, même message d'erreur si ``openai`` n'est pas installé.
Ce module porte cette seule construction pour que les deux ne divergent pas.
"""

from __future__ import annotations

from config import llm_base_url


def build_azure_openai_client(endpoint: str, api_key: str, *, setting_name: str, fallback: str):  # type: ignore[no-untyped-def]
    """Client OpenAI standard pointant sur ``{endpoint}/openai/v1`` — pas d'``api_version``,
    le nom du déploiement se passe en ``model`` à l'appel.

    ``setting_name`` et ``fallback`` ne servent qu'au message d'erreur si ``openai`` n'est
    pas installé : ils nomment la variable d'environnement en cause et ce sur quoi
    retomber en la vidant.
    """
    try:
        from openai import OpenAI
    except ImportError as error:  # pragma: no cover - dépend de la config
        raise RuntimeError(
            f"{setting_name} est configuré mais le paquet `openai` n'est pas installé — "
            f"ajouter la dépendance ou vider la variable pour retomber sur {fallback}."
        ) from error
    return OpenAI(base_url=llm_base_url(endpoint), api_key=api_key)
