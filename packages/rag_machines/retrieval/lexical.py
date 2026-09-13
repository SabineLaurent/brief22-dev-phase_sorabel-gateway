"""Recherche lexicale — BM25 (``Q3`` §2 et §8).

L'index BM25 est construit **à l'ingestion**, sur le même texte que l'index dense, et
sérialisé à côté de lui : c'est ce qui évite de le reconstruire à chaque démarrage du
serveur MCP, et ce qui garantit que le lexical et le dense ne peuvent pas diverger — les
deux sont produits par la même passe (``packages.rag_machines.ingest.index.index_editions``).

Ce module ne dépend jamais de ``packages.rag_machines.ingest.index`` : ``bm25_path()`` prend un nom de collection
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
from packages.rag_machines.ingest.normalize import Edition, TextProfile
from packages.rag_machines.ingest.registry import Registry
from packages.rag_machines.retrieval.perimeter import Perimeter

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
    #: Les deux listes du périmètre documentaire, parallèles aux deux précédentes.
    #: ``themes`` porte ``None`` sur les 320 éditions qui ne sont pas des notes — symétrique
    #: de la clé ``theme`` omise dans les métadonnées Chroma.
    doc_types: list[str]
    themes: list[str | None]
    bm25: BM25Okapi

    def search(self, query: str, top_k: int, version_filter: bool,
               perimeter: Perimeter | None = None) -> list[tuple[str, float]]:
        """Rend jusqu'à ``top_k`` couples ``(edition_id, score)``, triés par score.

        Le filtre de version s'applique **avant** la troncature — même sémantique que le
        ``where`` de Chroma côté dense (``Q1`` §5) : filtrer après aurait tronqué sur un
        classement qui inclut des éditions qu'on écarte de toute façon.

        Le filtre de périmètre s'applique au même endroit, et pour la même raison : c'est le
        rang de cette liste que consomme la fusion RRF de la configuration hybride. Écarter
        après coup rendrait ce rang ininterprétable, et rendrait moins de ``top_k``
        résultats sans repêchage.

        Les scores BM25 eux-mêmes ne changent pas : on n'ôte rien du corpus indexé, donc
        rien des fréquences documentaires. On écarte des candidats après le calcul.
        """
        scores = self.bm25.get_scores(tokenize(query))
        candidates = [
            (edition_id, float(score))
            for edition_id, score, current, doc_type, theme in zip(
                self.edition_ids, scores, self.is_current, self.doc_types, self.themes
            )
            if (not version_filter or current)
            and (perimeter is None or perimeter.allows(doc_type, theme))
        ]
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[:top_k]


def bm25_path(collection: str) -> Path:
    """Chemin du pickle BM25 d'une collection. ``collection`` est déjà résolu par
    ``packages.rag_machines.ingest.index.collection_name`` — jamais recalculé ici, pour éviter tout import
    circulaire entre ``packages.rag_machines.ingest.index`` (qui écrit ce fichier) et ce module (qui le lit)."""
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
    doc_types = [edition.doc_type for edition in editions]
    themes = [edition.theme for edition in editions]
    corpus = [tokenize(edition.text_for(text)) for edition in editions]
    return LexicalIndex(edition_ids=edition_ids, is_current=is_current, doc_types=doc_types,
                        themes=themes, bm25=BM25Okapi(corpus))


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
    index = _load_lexical_index_cached(path, path.stat().st_mtime_ns)
    _check_schema(index, path)
    return index


def _check_schema(index: LexicalIndex, path: Path) -> None:
    """Cet index porte-t-il le périmètre documentaire ? Sinon, il précède le filtre.

    ``LexicalIndex`` est une dataclass ordinaire : le dépicklage restaure ``__dict__`` sans
    passer par ``__init__``, donc un index construit avant l'ajout de ``doc_types`` et
    ``themes`` se charge sans erreur et ne casse qu'au premier ``search`` filtré, loin de sa
    cause. On préfère dire tout de suite ce qui manque, et comment le refaire.

    Le contrôle vit ici, pas dans la fonction mise en cache : deux ``hasattr`` ne coûtent
    rien, et une exception levée sous ``lru_cache`` n'est pas mémorisée de toute façon.
    """
    expected = len(index.edition_ids)
    if (getattr(index, "doc_types", None) is None or getattr(index, "themes", None) is None
            or len(index.doc_types) != expected or len(index.themes) != expected):
        raise RuntimeError(
            f"Index BM25 antérieur au filtre de périmètre : {path}. Il ne porte pas "
            "`doc_type` et `theme`, sans lesquels l'étage lexical ne sait pas appliquer la "
            "matrice d'accès. Le reconstruire (`make ingest`, `make reindex` ou "
            "`make ingest-brut` selon le texte visé) — l'index dense, lui, n'a pas besoin "
            "d'être refait."
        )


@lru_cache(maxsize=8)
def _load_lexical_index_cached(path: Path, mtime_ns: int) -> LexicalIndex:  # noqa: ARG001
    with path.open("rb") as handle:
        return pickle.load(handle)  # noqa: S301 - fichier écrit par cette même passe d'ingestion
