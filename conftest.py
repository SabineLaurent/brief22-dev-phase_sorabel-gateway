"""En-tête de la suite d'acceptance : quelle configuration est réellement lue.

À la racine, et non dans ``tests/`` : la suite est arrivée avec le dépôt et fait foi, on
n'y touche pas. pytest charge les ``conftest.py`` du *rootdir* jusqu'au répertoire des
tests, donc celui-ci s'applique à toute exécution — en local comme dans le conteneur.

**Aucun nom n'est écrit ici.** Chaque valeur est extraite à l'exécution : les modèles par
le ``.name`` des fabriques (celles-là mêmes que ``search()`` appelle), la collection et son
empreinte par l'objet Chroma que la recherche ouvre, les chemins par ``config.settings``.
Un en-tête recopié à la main serait juste jusqu'au jour où la configuration change — c'est
exactement le jour où l'on relit un résultat de test.
"""

from __future__ import annotations

from pathlib import Path

from config import CALIBRATED_THRESHOLDS, settings


def _fichier(chemin: Path) -> str:
    """Chemin **résolu** : ``.env`` pose ``SORABEL_DB=data/sorabel.db``, un relatif qui
    dépend du répertoire courant. Afficher le relatif laisserait entière la question que
    cet en-tête doit fermer — quel fichier a été lu."""
    chemin = chemin.resolve()
    if not chemin.exists():
        return f"{chemin} — ABSENT"
    return f"{chemin} ({chemin.stat().st_size / 1024:.0f} Kio)"


def _index(embedder_name: str) -> str:
    """La collection telle que ``search()`` l'ouvre — même client, même fabrique.

    Passer par ``get_collection`` plutôt que par un accès direct fait aussi jouer le
    contrôle d'empreinte : un index construit avec un autre modèle se dit ici, avant les
    tests, au lieu de se déduire d'un échec de recherche.
    """
    from packages.rag_machines.ingest.index import _MODEL_KEY, connect, get_collection
    from packages.rag_machines.retrieval.embedder import build_embedder

    try:
        collection = get_collection(connect(settings), build_embedder(settings), settings)
        empreinte = (collection.metadata or {}).get(_MODEL_KEY, "SANS EMPREINTE")
        accord = "=" if empreinte == embedder_name else "≠ CONFIGURATION"
        return (
            f"{settings.chroma_url} · {collection.name} · {collection.count()} éditions "
            f"· empreinte {empreinte} {accord}"
        )
    except Exception as erreur:  # noqa: BLE001 - l'en-tête ne doit jamais casser la collecte
        return f"{settings.chroma_url} · {settings.chroma_collection} — ILLISIBLE : {erreur}"


def pytest_report_header() -> list[str]:
    from packages.rag_machines.retrieval.embedder import build_embedder
    from packages.rag_machines.ingest.index import collection_name
    from packages.rag_machines.retrieval.lexical import bm25_path
    from packages.rag_machines.retrieval.reranker import build_reranker

    embedder = build_embedder(settings).name
    reranker = build_reranker(settings).name
    calibre = CALIBRATED_THRESHOLDS.get((embedder, reranker))
    if calibre is None:
        seuil = f"{settings.rerank_threshold} — COUPLE NON CALIBRÉ"
    elif calibre == settings.rerank_threshold:
        seuil = f"{settings.rerank_threshold} = calibré pour ce couple"
    else:
        seuil = f"{settings.rerank_threshold} ≠ CALIBRÉ POUR CE COUPLE ({calibre})"

    distant = {True: "distant", False: "local"}
    return [
        "configuration lue par cette exécution (extraite du code, pas recopiée) :",
        f"  embedder  : {embedder} [{distant[settings.uses_azure_embeddings]}]",
        f"  reranker  : {reranker} [{distant[settings.uses_azure_rerank]}]",
        f"  seuil     : {seuil}",
        f"  vectoriel : {_index(embedder)}",
        f"  lexical   : {_fichier(bm25_path(collection_name(settings)))}",
        f"  métier    : {_fichier(settings.sorabel_db)}",
    ]
