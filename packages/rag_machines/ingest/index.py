"""Indexation des éditions dans Chroma.

Une seule collection physique : ``doc_type`` est une métadonnée, pas une
collection à part. C'est sur ce champ que la matrice d'accès filtrera plus tard,
et quatre collections physiques obligeraient à réunir leurs résultats à la main
à chaque recherche.

L'écriture se fait en ``upsert`` sur ``edition_id``, **jamais en ``add``** : la
ré-ingestion est le risque réel du corpus (aucun doublon d'octets n'y existe),
et l'``upsert`` la rend idempotente. L'``upsert`` seul ne suffit pourtant pas à
faire d'une ré-ingestion une remise à niveau : il ne sait rien de ce qui a
disparu du corpus. La passe se termine donc par une réconciliation, qui supprime
de l'index les éditions que le registre ne retient plus.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from urllib.parse import urlparse

import chromadb
from chromadb.api.models.Collection import Collection

from config import Settings
from config import settings as default_settings
from packages.rag_machines.ingest.normalize import Edition, TextProfile
from packages.rag_machines.ingest.registry import Registry, build_metadata
from packages.rag_machines.retrieval.embedder import Embedder, build_embedder
from packages.rag_machines.retrieval.lexical import bm25_path, build_lexical_index, save_lexical_index

#: Les vecteurs sont comparés en cosinus — la métrique des modèles e5.
_DISTANCE_METADATA = {"hnsw:space": "cosine"}
#: Empreinte du modèle d'embeddings, écrite dans la métadonnée de la collection.
_MODEL_KEY = "embedding_model"
#: Ports implicites d'une URL sans port. Chroma en `docker compose` écoute sur 8002.
_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}
_BATCH_SIZE = 100


class ChromaEmbeddingFunction:
    """Adaptateur : expose un :class:`Embedder` à l'interface de Chroma.

    Chroma appelle cette fonction pour tout texte qu'on lui confie **sans**
    vecteur. Or la gateway fournit toujours les siens : l'ingestion vectorise ses
    documents, la recherche vectorisera ses questions. Cet adaptateur n'existe
    donc que pour satisfaire l'interface de la collection.

    Il refuse d'embarquer un texte plutôt que de deviner de quel côté il vient.
    La famille e5 est asymétrique : un appel à ``collection.query(query_texts=…)``
    — l'API la plus naturelle de Chroma — passerait ici, et la question partirait
    encodée avec le préfixe ``passage:`` des documents. Le rappel se dégraderait
    sans que rien ne le signale. Mieux vaut une exception au premier essai.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def name(self) -> str:
        """Nom de l'adaptateur. Chroma ne le persiste pas — voir ``_MODEL_KEY``."""
        return f"sorabel:{self._embedder.name}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - imposé par Chroma
        raise RuntimeError(
            "Chroma a demandé des vecteurs à la gateway : un texte lui a été confié "
            "sans embedding. Les modèles e5 sont asymétriques — vectoriser "
            "explicitement, avec `Embedder.embed_documents()` à l'indexation et "
            "`Embedder.embed_query()` à la recherche, puis passer `embeddings=` ou "
            "`query_embeddings=`."
        )


def _parse_chroma_url(url: str) -> tuple[str, int, bool]:
    """Rend ``(hôte, port, TLS)``. Lève ``ValueError`` sur une URL inexploitable.

    Le parsing est strict à dessein : ``urlparse`` rend ``hostname=None`` sur une
    URL sans schéma (``localhost:8002``) et ne dit rien du TLS. Retomber
    silencieusement sur des valeurs par défaut ferait se connecter la gateway à un
    autre service que celui demandé — l'erreur ne se verrait que plus tard, sous
    la forme d'une collection vide ou inattendue.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _DEFAULT_PORT_BY_SCHEME or not parsed.hostname:
        raise ValueError(
            f"CHROMA_URL inexploitable : {url!r}. Attendu http(s)://hôte[:port], "
            "par exemple http://localhost:8002."
        )
    port = parsed.port or _DEFAULT_PORT_BY_SCHEME[parsed.scheme]
    return parsed.hostname, port, parsed.scheme == "https"


def connect(settings: Settings | None = None) -> chromadb.ClientAPI:
    """Client Chroma pointant sur le service de ``docker compose``."""
    settings = settings or default_settings
    host, port, secure = _parse_chroma_url(settings.chroma_url)
    try:
        return chromadb.HttpClient(host=host, port=port, ssl=secure)
    except Exception as error:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            f"Chroma injoignable sur {settings.chroma_url} — lancer `make up` "
            "(le service docker expose Chroma sur le port 8002)."
        ) from error


def _check_embedding_model(collection: Collection, embedder: Embedder) -> None:
    """Refuse une collection construite avec un autre modèle d'embeddings.

    Chroma garde la fonction d'embeddings côté client : elle n'est ni persistée
    ni comparée à l'ouverture. Changer ``EMBEDDING_MODEL`` pour un modèle de même
    dimension et ré-ingérer réussirait donc sans un mot, en mélangeant deux
    espaces vectoriels incompatibles dans la même collection — les recherches
    suivantes rendraient un classement dégradé, sans erreur. D'où cette empreinte,
    écrite dans la métadonnée de la collection à sa création et vérifiée ici.
    """
    stored = (collection.metadata or {}).get(_MODEL_KEY)
    if stored == embedder.name:
        return
    if stored is None:
        raise RuntimeError(
            f"La collection « {collection.name} » ne porte pas l'empreinte de son "
            "modèle d'embeddings : elle a été construite avant ce contrôle, et rien "
            "ne prouve l'homogénéité de ses vecteurs. La reconstruire : `make reindex`."
        )
    raise RuntimeError(
        f"La collection « {collection.name} » a été construite avec le modèle "
        f"« {stored} », la configuration demande « {embedder.name} ». Mélanger deux "
        "espaces vectoriels dégraderait la recherche sans rien signaler. Rétablir le "
        "modèle d'origine, changer de collection (CHROMA_COLLECTION), ou reconstruire "
        "celle-ci : `make reindex`."
    )


def collection_name(settings: Settings, text: TextProfile = "clean") -> str:
    """La collection dépend du texte indexé.

    Deux textes produisent deux jeux de vecteurs : les mélanger dans une même collection
    rendrait la comparaison de l'axe 2 impossible à relire. Le suffixe est donc porté par
    le nom, pas par une métadonnée.
    """
    base = settings.chroma_collection
    return base if text == "clean" else f"{base}_raw"


def get_collection(
    client: chromadb.ClientAPI,
    embedder: Embedder,
    settings: Settings | None = None,
    text: TextProfile = "clean",
) -> Collection:
    settings = settings or default_settings
    collection = client.get_or_create_collection(
        name=collection_name(settings, text),
        embedding_function=ChromaEmbeddingFunction(embedder),  # type: ignore[arg-type]
        metadata={**_DISTANCE_METADATA, _MODEL_KEY: embedder.name},
    )
    _check_embedding_model(collection, embedder)
    return collection


@dataclass(frozen=True)
class IndexReport:
    """Ce que la passe d'indexation a écrit, et ce qu'elle a retiré."""

    written: int
    #: ``edition_id`` supprimés de l'index parce que le registre ne les retient plus.
    deleted: list[str]


def _reconcile_deletions(collection: Collection, kept_ids: set[str]) -> list[str]:
    """Supprime de l'index les éditions absentes du registre.

    Sans cette passe, l'index ne fait que croître. Un fichier supprimé, renommé
    (l'``edition_id`` est son chemin : le renommer en crée un nouveau et laisse
    l'ancien orphelin) ou nouvellement écarté par le contrôle de version y
    survivrait, avec l'``is_current`` que la passe précédente lui avait écrit — et
    la recherche rendrait une édition que le registre a délibérément exclue.
    """
    indexed_ids = set(collection.get(include=[])["ids"])
    stale = sorted(indexed_ids - kept_ids)
    if stale:
        collection.delete(ids=stale)
    return stale


def drop_collection(
    client: chromadb.ClientAPI, settings: Settings | None = None, text: TextProfile = "clean"
) -> None:
    """Supprime la collection si elle existe. Sans effet sinon."""
    settings = settings or default_settings
    try:
        client.delete_collection(collection_name(settings, text))
    except Exception:  # la collection n'existait pas : c'est l'état recherché
        pass


def index_editions(
    editions: list[Edition],
    registry: Registry,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    reset: bool = False,
    text: TextProfile = "clean",
) -> IndexReport:
    """Vectorise puis ``upsert`` les éditions, et retire de l'index le reste.

    ``text`` choisit le texte indexé et, avec lui, la collection : « clean » est le contrat,
    « raw » n'existe que pour mesurer ce que le nettoyage apporte.

    ``reset`` reconstruit la collection à neuf. C'est le remède à une collection
    dont on ne peut plus garantir l'homogénéité — modèle d'embeddings changé, ou
    collection antérieure au contrôle d'empreinte.
    """
    settings = settings or default_settings
    embedder = embedder or build_embedder(settings)
    client = connect(settings)
    if reset:
        drop_collection(client, settings, text)
    collection = get_collection(client, embedder, settings, text)

    written = 0
    for start in range(0, len(editions), _BATCH_SIZE):
        batch = editions[start : start + _BATCH_SIZE]
        texts = [edition.text_for(text) for edition in batch]
        collection.upsert(
            ids=[edition.edition_id for edition in batch],
            documents=texts,
            metadatas=[build_metadata(edition, registry, text) for edition in batch],  # type: ignore[arg-type]
            embeddings=embedder.embed_documents(texts),  # type: ignore[arg-type]
        )
        written += len(batch)

    deleted = _reconcile_deletions(collection, {edition.edition_id for edition in editions})
    if deleted:
        print(f"index : {len(deleted)} édition(s) obsolète(s) retirée(s)", file=sys.stderr)

    # L'index BM25 est reconstruit en entier, sur les mêmes éditions et le même texte que
    # l'index dense qui précède : les deux index de cette collection sont donc toujours en
    # phase, et le lexical n'a pas de mise à jour incrémentale sensée — l'IDF de chaque
    # terme change globalement dès qu'une édition apparaît ou disparaît.
    save_lexical_index(
        build_lexical_index(editions, registry, text),
        bm25_path(collection_name(settings, text)),
    )

    return IndexReport(written=written, deleted=deleted)
