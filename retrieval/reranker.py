"""Reranking : une interface, deux implémentations commutables.

Même schéma que ``retrieval/embedder.py`` — le choix se fait par configuration, jamais par
le code appelant : si ``AZURE_RERANK_DEPLOYMENT`` (et ``AZURE_AI_ENDPOINT``) sont renseignés,
le rerank part sur Azure AI Foundry en LLM-juge ; sinon sur le cross-encoder local
``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`` — mMARCO parce que le corpus est en français,
pas ``ms-marco-MiniLM`` (``Q3`` §6).

Le score rendu est **toujours borné dans ``[0, 1]``** : c'est la condition posée par
``Q4`` §3 pour qu'un seuil de refus soit une opération sensée sur cette échelle. Les
cross-encoders mMARCO ne sont pas tous nativement dans cet intervalle — une sigmoïde
l'y ramène.
"""

from __future__ import annotations

import json
import math
from typing import Protocol, cast

from config import Settings
from config import settings as default_settings
from retrieval.azure_client import build_azure_openai_client

#: Prompt du rerank LLM : un score par document, jamais du texte libre.
_AZURE_RERANK_SYSTEM_PROMPT = (
    "Tu notes la pertinence de documents pour une question, sur une échelle de 0 (aucun "
    "rapport) à 1 (répond exactement à la question). Réponds uniquement par un objet JSON "
    '{"scores": [{"index": <entier>, "score": <nombre entre 0 et 1>}, ...]}, un élément par '
    "document, dans l'ordre où ils sont fournis. Aucun texte hors de ce JSON."
)


class Reranker(Protocol):
    """Ce que la gateway attend d'un fournisseur de rerank."""

    name: str

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Note chaque document pour la requête. Rend une liste bornée ``[0, 1]``,
        dans l'ordre d'entrée."""


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


class LocalReranker:
    """Cross-encoder local, chargé paresseusement — même motif que ``LocalEmbedder``."""

    def __init__(self, model_name: str) -> None:
        self.name = model_name
        self._model = None

    def _load_model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.name)
        return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        pairs = [(query, document) for document in documents]
        logits = self._load_model().predict(pairs)
        return [_sigmoid(float(logit)) for logit in logits]


class AzureReranker:
    """Azure AI Foundry en OpenAI-compatible, **API v1** — le rerank en LLM-juge.

    Un seul appel de complétion par requête, quel que soit le nombre de documents : les
    candidats sont numérotés dans le prompt, le modèle rend un score par index. Sortie
    structurée (``response_format=json_object``) pour ne jamais avoir à parser de la prose.
    """

    def __init__(self, endpoint: str, api_key: str, deployment: str) -> None:
        self.name = deployment
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            self._client = build_azure_openai_client(
                self._endpoint, self._api_key,
                setting_name="AZURE_RERANK_DEPLOYMENT", fallback="le cross-encoder local",
            )
        return self._client

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        candidates = "\n\n".join(
            f"[{index}] {document}" for index, document in enumerate(documents)
        )
        response = self._get_client().chat.completions.create(
            model=self.name,
            messages=[
                {"role": "system", "content": _AZURE_RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": f"Question : {query}\n\nDocuments :\n{candidates}"},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        by_index = {int(item["index"]): float(item["score"]) for item in payload.get("scores", [])}
        return [max(0.0, min(1.0, by_index.get(i, 0.0))) for i in range(len(documents))]


def build_reranker(settings: Settings | None = None) -> Reranker:
    """Rend le reranker configuré. Azure s'il est renseigné, cross-encoder local sinon."""
    settings = settings or default_settings
    if settings.uses_azure_rerank:
        return cast(
            Reranker,
            AzureReranker(
                settings.azure_ai_endpoint,
                settings.azure_ai_api_key,
                settings.azure_rerank_deployment,
            ),
        )
    return cast(Reranker, LocalReranker(settings.reranker_model))
