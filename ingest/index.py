"""Indexation des éditions dans Chroma.

Une seule collection physique : ``doc_type`` est une métadonnée, pas une
collection à part. C'est sur ce champ que la matrice d'accès filtrera plus tard,
et quatre collections physiques obligeraient à réunir leurs résultats à la main
à chaque recherche.

L'écriture se fait en ``upsert`` sur ``edition_id``, **jamais en ``add``** : la
ré-ingestion est le risque réel du corpus (aucun doublon d'octets n'y existe),
et l'``upsert`` la rend idempotente.
"""

from __future__ import annotations

from urllib.parse import urlparse

import chromadb
from chromadb.api.models.Collection import Collection

from config import Settings
from config import settings as default_settings
from ingest.normalize import Edition
from ingest.registry import Registry, build_metadata
from retrieval.embedder import Embedder, build_embedder

#: Les vecteurs sont comparés en cosinus — la métrique des modèles e5.
_COLLECTION_METADATA = {"hnsw:space": "cosine"}
_BATCH_SIZE = 100


class ChromaEmbeddingFunction:
    """Adaptateur : expose un :class:`Embedder` à l'interface de Chroma.

    Chroma appelle cette fonction pour tout texte qu'on lui confie sans vecteur.
    L'ingestion fournit ses vecteurs explicitement et la recherche fournira ceux
    des questions : l'adaptateur est un filet, et il traite ce qu'il reçoit comme
    des documents.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def name(self) -> str:  # Chroma persiste ce nom avec la collection.
        return f"sorabel:{self._embedder.name}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - imposé par Chroma
        return self._embedder.embed_documents(list(input))


def connect(settings: Settings | None = None) -> chromadb.ClientAPI:
    """Client Chroma pointant sur le service de ``docker compose``."""
    settings = settings or default_settings
    parsed = urlparse(settings.chroma_url)
    try:
        return chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)
    except Exception as error:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            f"Chroma injoignable sur {settings.chroma_url} — lancer `make up` "
            "(le service docker expose Chroma sur le port 8002)."
        ) from error


def get_collection(
    client: chromadb.ClientAPI,
    embedder: Embedder,
    settings: Settings | None = None,
) -> Collection:
    settings = settings or default_settings
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        embedding_function=ChromaEmbeddingFunction(embedder),  # type: ignore[arg-type]
        metadata=_COLLECTION_METADATA,
    )


def index_editions(
    editions: list[Edition],
    registry: Registry,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
) -> int:
    """Vectorise puis ``upsert`` les éditions. Rend le nombre d'éditions écrites."""
    settings = settings or default_settings
    embedder = embedder or build_embedder(settings)
    collection = get_collection(connect(settings), embedder, settings)

    written = 0
    for start in range(0, len(editions), _BATCH_SIZE):
        batch = editions[start : start + _BATCH_SIZE]
        texts = [edition.indexed_text for edition in batch]
        collection.upsert(
            ids=[edition.edition_id for edition in batch],
            documents=texts,
            metadatas=[build_metadata(edition, registry) for edition in batch],  # type: ignore[arg-type]
            embeddings=embedder.embed_documents(texts),  # type: ignore[arg-type]
        )
        written += len(batch)
    return written


# --- Point de greffe de l'étape 3 -------------------------------------------
# La recherche hybride ajoutera ici la construction de l'index lexical BM25 sur
# `edition.indexed_text`, sérialisé à côté de l'index vectoriel pour ne pas être
# reconstruit à chaque démarrage du serveur MCP. `index_editions()` en sera le
# point d'appel : les deux index sont produits par la même passe d'ingestion, sur
# le même texte, pour qu'ils ne puissent pas diverger.
