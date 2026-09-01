"""Ingestion du corpus : `python -m ingest.cli` (ou `make ingest`).

Lit les 400 fichiers, les normalise, désigne les éditions courantes, puis écrit
l'index. Rejouable : l'``upsert`` sur ``edition_id`` rend une seconde exécution
sans effet sur le contenu de l'index.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from config import Settings
from config import settings as default_settings
from ingest.index import index_editions
from ingest.normalize import Edition, NormalizationError, corpus_files, normalize
from ingest.registry import Registry, build_registry


def collect(root: Path) -> tuple[list[Edition], list[str]]:
    """Normalise tout le corpus. Rend les éditions lues et les échecs de lecture."""
    editions: list[Edition] = []
    failures: list[str] = []
    for path in corpus_files(root):
        try:
            editions.append(normalize(path, root))
        except NormalizationError as error:
            failures.append(f"{path.relative_to(root).as_posix()} : {error}")
    return editions, failures


def build_report(
    editions: list[Edition],
    failures: list[str],
    registry: Registry,
    written: int,
) -> str:
    """Le compte rendu d'ingestion, à lire après chaque exécution."""
    by_doc_type = Counter(edition.doc_type for edition in registry.editions)
    by_theme = Counter(
        edition.theme for edition in registry.editions if edition.theme is not None
    )
    with_reference = sum(1 for edition in registry.editions if edition.reference is not None)
    max_chars = max((edition.char_count for edition in registry.editions), default=0)

    lines = [
        "--- Rapport d'ingestion ---",
        f"fichiers lus          : {len(editions) + len(failures)}",
        f"éditions normalisées  : {len(editions)}",
        f"éditions indexées     : {written}",
        f"documents (doc_key)   : {len(registry.current_version)}",
        f"éditions courantes    : {len(registry.current_edition_ids)}",
        "",
        "par doc_type :",
        *(f"  {doc_type:<16} {count}" for doc_type, count in sorted(by_doc_type.items())),
        "",
        f"reference présente    : {with_reference} / {len(registry.editions)}",
        f"theme présent         : {sum(by_theme.values())} / {len(registry.editions)}",
        *(f"  {theme:<20} {count}" for theme, count in sorted(by_theme.items())),
        "",
        f"n_caracteres max      : {max_chars}",
    ]
    if registry.mismatches:
        lines += [
            "",
            f"éditions écartées (version incohérente) : {len(registry.mismatches)}",
            *(f"  {mismatch}" for mismatch in registry.mismatches),
        ]
    if failures:
        lines += ["", f"fichiers illisibles : {len(failures)}", *(f"  {f}" for f in failures)]
    return "\n".join(lines)


def run(settings: Settings, write_index: bool = True) -> int:
    editions, failures = collect(settings.corpus_dir)
    registry = build_registry(editions)
    written = index_editions(registry.editions, registry, settings) if write_index else 0
    print(build_report(editions, failures, registry, written))
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingestion du corpus Sorabel.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="normalise et contrôle sans écrire dans l'index",
    )
    args = parser.parse_args(argv)
    return run(default_settings, write_index=not args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
