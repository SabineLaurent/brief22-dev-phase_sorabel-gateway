"""Recherche lexicale — BM25 (``Q3`` §2 et §8).

L'index BM25 est construit **à l'ingestion**, sur le même texte que l'index dense, et
sérialisé à côté de lui : c'est ce qui évite de le reconstruire à chaque démarrage du
serveur MCP, et ce qui garantit que le lexical et le dense ne peuvent pas diverger — les
deux sont produits par la même passe (``ingest.index.index_editions``).

Ce module ne dépend jamais de ``ingest.index`` : ``bm25_path()`` prend un nom de collection
déjà résolu, pour que l'appelant (l'ingestion comme la recherche) reste seul responsable de
la correspondance nom de collection / texte indexé, sans import circulaire.
"""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from config import REPO_ROOT
from ingest.normalize import Edition, TextProfile
from ingest.registry import Registry

#: Reprend au caractère près la regex de ``Q3.md`` §8 : c'est elle qui reproduit les
#: scores mesurés dans le dossier (« REF-8842 » notice 6,1, note 5,5, fiche 4,5).
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:-\d+)?")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class LexicalIndex:
    """L'index BM25 d'une collection : les éditions dans l'ordre du corpus BM25."""

    edition_ids: list[str]
    is_current: list[bool]
    bm25: BM25Okapi

    def search(self, query: str, top_k: int, version_filter: bool) -> list[tuple[str, float]]:
        """Rend jusqu'à ``top_k`` couples ``(edition_id, score)``, triés par score.

        Le filtre de version s'applique **avant** la troncature — même sémantique que le
        ``where`` de Chroma côté dense (``Q1`` §5) : filtrer après aurait tronqué sur un
        classement qui inclut des éditions qu'on écarte de toute façon.
        """
        scores = self.bm25.get_scores(tokenize(query))
        candidates = [
            (edition_id, float(score))
            for edition_id, score, current in zip(self.edition_ids, scores, self.is_current)
            if not version_filter or current
        ]
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[:top_k]


def bm25_path(collection: str) -> Path:
    """Chemin du pickle BM25 d'une collection. ``collection`` est déjà résolu par
    ``ingest.index.collection_name`` — jamais recalculé ici, pour éviter tout import
    circulaire entre ``ingest.index`` (qui écrit ce fichier) et ce module (qui le lit)."""
    return REPO_ROOT / "data" / "bm25" / f"{collection}.pkl"


def build_lexical_index(editions: list[Edition], registry: Registry, text: TextProfile) -> LexicalIndex:
    """Construit l'index BM25 sur toutes les éditions du registre, comme le dense.

    Reconstruit en entier à chaque passe : BM25 n'a pas de mise à jour incrémentale
    sensée, les fréquences documentaires (donc l'IDF de chaque terme) changent
    globalement dès qu'une édition apparaît ou disparaît.
    """
    if not editions:
        raise RuntimeError(
            "Aucune édition à indexer : BM25Okapi ne construit pas d'index sur un corpus "
            "vide. `ingest/cli.py` s'arrête avant d'appeler cette fonction dans ce cas — "
            "un autre appelant doit vérifier `editions` avant d'y recourir."
        )
    edition_ids = [edition.edition_id for edition in editions]
    is_current = [registry.is_current(edition) for edition in editions]
    corpus = [tokenize(edition.text_for(text)) for edition in editions]
    return LexicalIndex(edition_ids=edition_ids, is_current=is_current, bm25=BM25Okapi(corpus))


def save_lexical_index(index: LexicalIndex, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(index, handle)
    _load_lexical_index_cached.cache_clear()


def load_lexical_index(path: Path) -> LexicalIndex:
    """Charge le pickle, mis en cache par ``(chemin, date de modification)`` : un run de
    mesure rejoue les 30 questions de ``questions_rag.jsonl`` sur la même collection, pas
    la peine de redéserialiser l'index à chaque question.

    La date de modification fait partie de la clé de cache — pas seulement le chemin —
    pour qu'un processus long (le futur serveur MCP) n'y reste jamais épinglé après un
    ``make ingest`` lancé par ailleurs : le prochain appel voit un ``mtime`` différent et
    recharge, sans redémarrage. ``save_lexical_index`` vide le cache en plus, pour le cas
    où ``ingest`` puis ``search`` tournent dans le même process, dans la même seconde."""
    if not path.exists():
        raise RuntimeError(
            f"Index BM25 introuvable : {path}. Lancer l'ingestion de cette collection "
            "(`make ingest`, `make reindex` ou `make ingest-brut` selon le texte visé) "
            "avant une recherche lexicale ou hybride."
        )
    return _load_lexical_index_cached(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _load_lexical_index_cached(path: Path, mtime_ns: int) -> LexicalIndex:  # noqa: ARG001
    with path.open("rb") as handle:
        return pickle.load(handle)  # noqa: S301 - fichier écrit par cette même passe d'ingestion
