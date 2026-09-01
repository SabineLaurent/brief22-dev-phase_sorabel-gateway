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

from typing import Protocol, cast

from config import Settings
from config import settings as default_settings

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
            try:
                from openai import OpenAI
            except ImportError as error:  # pragma: no cover - dépend de la config
                raise RuntimeError(
                    "AZURE_EMBEDDING_DEPLOYMENT est configuré mais le paquet `openai` "
                    "n'est pas installé — ajouter la dépendance ou vider la variable "
                    "pour retomber sur le modèle local."
                ) from error
            self._client = OpenAI(base_url=f"{self._endpoint}/openai/v1", api_key=self._api_key)
        return self._client

    def _encode(self, texts: list[str]) -> list[Vector]:
        response = self._get_client().embeddings.create(model=self.name, input=texts)
        return [item.embedding for item in response.data]

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        return self._encode(texts)

    def embed_query(self, text: str) -> Vector:
        return self._encode([text])[0]


def build_embedder(settings: Settings | None = None) -> Embedder:
    """Rend l'embedder configuré. Azure s'il est renseigné, local sinon."""
    settings = settings or default_settings
    if settings.uses_azure_embeddings:
        return cast(
            Embedder,
            AzureEmbedder(
                settings.azure_ai_endpoint,
                settings.azure_ai_api_key,
                settings.azure_embedding_deployment,
            ),
        )
    return cast(Embedder, LocalEmbedder(settings.embedding_model))
