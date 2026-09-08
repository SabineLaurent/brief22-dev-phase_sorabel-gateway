"""Embeddings : une interface, deux implémentations commutables.

Le choix se fait par configuration, pas par le code appelant : si
``AZURE_EMBEDDING_DEPLOYMENT`` et ``AZURE_AI_ENDPOINT`` sont renseignés, les
vecteurs sont calculés par Azure AI Foundry ; sinon par ``multilingual-e5-base``
en local.

Le module vit dans ``retrieval/`` parce qu'il sert des deux côtés : l'ingestion
calcule les vecteurs des documents une fois, la recherche calcule celui de
chaque question. La distinction n'est pas cosmétique — la famille e5 est
**asymétrique** et attend le préfixe ``passage:`` sur les documents, ``query:``
sur les questions. Confondre les deux dégrade le rappel sans rien signaler.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, cast

from config import Settings
from config import settings as default_settings
from packages.rag_machines.retrieval.azure_client import build_azure_openai_client

#: Les modèles e5 sont entraînés avec ces préfixes ; les omettre coûte du rappel.
_DOCUMENT_PREFIX = "passage: "
_QUERY_PREFIX = "query: "

Vector = list[float]


class Embedder(Protocol):
    """Ce que la gateway attend d'un fournisseur d'embeddings."""

    name: str

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        """Vectorise des documents, pour l'indexation."""

    def embed_query(self, text: str) -> Vector:
        """Vectorise une question, pour la recherche."""


class LocalEmbedder:
    """``intfloat/multilingual-e5-base`` via sentence-transformers.

    Le modèle est chargé paresseusement : la suite d'acceptance relance un
    processus serveur à chaque appel, un chargement au niveau module ferait
    exploser le budget de démarrage.
    """

    def __init__(self, model_name: str) -> None:
        self.name = model_name
        self._model = None

    def _load_model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name)
        return self._model

    def _encode(self, texts: list[str]) -> list[Vector]:
        vectors = self._load_model().encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(value) for value in vector] for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        return self._encode([_DOCUMENT_PREFIX + text for text in texts])

    def embed_query(self, text: str) -> Vector:
        return self._encode([_QUERY_PREFIX + text])[0]


class AzureEmbedder:
    """Azure AI Foundry en OpenAI-compatible, **API v1**.

    Pas d'``api_version`` : l'endpoint ``/openai/v1`` se consomme avec le client
    OpenAI standard, et le nom du déploiement passe en ``model``.

    Les modèles d'embeddings OpenAI sont symétriques : aucun préfixe à poser,
    contrairement à la famille e5.
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
                setting_name="AZURE_EMBEDDING_DEPLOYMENT", fallback="le modèle local",
            )
        return self._client

    def _encode(self, texts: list[str]) -> list[Vector]:
        response = self._get_client().embeddings.create(model=self.name, input=texts)
        return [item.embedding for item in response.data]

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        return self._encode(texts)

    def embed_query(self, text: str) -> Vector:
        return self._encode([text])[0]


@lru_cache(maxsize=None)
def _embedder(azure: bool, endpoint: str, api_key: str, deployment: str,
              model: str) -> Embedder:
    """Le cache est ici, sur les seuls champs lus — pas sur ``Settings``, qui n'est pas
    hachable, et pas sur l'objet appelant, qui varie d'une mesure à l'autre."""
    if azure:
        return cast(Embedder, AzureEmbedder(endpoint, api_key, deployment))
    return cast(Embedder, LocalEmbedder(model))


def build_embedder(settings: Settings | None = None) -> Embedder:
    """Rend l'embedder configuré. Azure s'il est renseigné, local sinon.

    **Le même objet est rendu à configuration égale**, et c'est nécessaire, pas
    opportuniste : ``LocalEmbedder`` ne charge son ``SentenceTransformer`` qu'au premier
    usage, mais il le charge **par instance**. Une instance neuve à chaque appel de
    ``search()`` ferait relire le modèle sur le disque à chaque question — invisible pour
    la suite d'acceptance, qui relance un processus serveur par appel, mais payé à chaque
    question par un serveur MCP qui vit. Même raison que l'index BM25, mémoïsé dans
    ``lexical.py``.
    """
    settings = settings or default_settings
    return _embedder(
        settings.uses_azure_embeddings,
        settings.azure_ai_endpoint,
        settings.azure_ai_api_key,
        settings.azure_embedding_deployment,
        settings.embedding_model,
    )
