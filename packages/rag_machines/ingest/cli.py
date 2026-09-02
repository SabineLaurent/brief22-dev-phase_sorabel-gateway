"""Ingestion du corpus : `python -m packages.rag_machines.ingest.cli` (ou `make ingest`).

Lit les 400 fichiers, les normalise, désigne les éditions courantes, puis écrit
l'index. Rejouable : l'``upsert`` sur ``edition_id`` réécrit ce qui a changé, et
la passe de réconciliation retire ce qui a disparu du corpus.

**Le code de sortie porte l'anomalie, pas seulement l'échec de lecture.** Un
fichier illisible, une version incohérente, un corpus vide : chacun laisse
l'index dans un état partiel, et chacun sort en 1. Sans cela, une ingestion
silencieusement incomplète passerait pour un succès en intégration continue.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from config import Settings
from config import settings as default_settings
from packages.rag_machines.ingest.index import IndexReport, collection_name, index_editions
from packages.rag_machines.ingest.normalize import (
    Edition,
    NormalizationError,
    TextProfile,
    corpus_files,
    normalize,
)
from packages.rag_machines.ingest.registry import Registry, build_registry


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
    index_report: IndexReport,
    text: TextProfile = "clean",
) -> str:
    """Le compte rendu d'ingestion, à lire après chaque exécution."""
    by_doc_type = Counter(edition.doc_type for edition in registry.editions)
    by_theme = Counter(
        edition.theme for edition in registry.editions if edition.theme is not None
    )
    with_reference = sum(1 for edition in registry.editions if edition.reference is not None)
    max_chars = max((len(e.text_for(text)) for e in registry.editions), default=0)

    lines = [
        "--- Rapport d'ingestion ---",
        f"texte indexé          : {text}",
        f"fichiers lus          : {len(editions) + len(failures)}",
        f"éditions normalisées  : {len(editions)}",
        f"éditions indexées     : {index_report.written}",
        f"éditions retirées     : {len(index_report.deleted)}",
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
    if index_report.deleted:
        lines += [
            "",
            f"éditions retirées de l'index : {len(index_report.deleted)}",
            *(f"  {edition_id}" for edition_id in index_report.deleted),
        ]
    if registry.mismatches:
        lines += [
            "",
            f"éditions écartées (version incohérente) : {len(registry.mismatches)}",
            *(f"  {mismatch}" for mismatch in registry.mismatches),
            "",
            "documents privés d'édition courante en conséquence : "
            f"{len(registry.undetermined_doc_keys)}",
            *(f"  {doc_key}" for doc_key in sorted(registry.undetermined_doc_keys)),
        ]
    if failures:
        lines += ["", f"fichiers illisibles : {len(failures)}", *(f"  {f}" for f in failures)]
    return "\n".join(lines)


def run(
    settings: Settings,
    write_index: bool = True,
    reset: bool = False,
    text: TextProfile = "clean",
) -> int:
    root = settings.corpus_dir
    if not root.is_dir():
        print(
            f"Corpus introuvable : {root} — vérifier CORPUS_DIR dans l'environnement "
            "ou dans `.env`.",
            file=sys.stderr,
        )
        return 1

    editions, failures = collect(root)
    if not editions:
        print(
            f"Aucune édition exploitable sous {root} : rien n'a été indexé. Vérifier "
            "que CORPUS_DIR pointe bien sur un corpus contenant "
            "fiches/, notices/, sav/ et notes/.",
            file=sys.stderr,
        )
        return 1

    registry = build_registry(editions)
    try:
        index_report = (
            index_editions(registry.editions, registry, settings, reset=reset, text=text)
            if write_index
            else IndexReport(written=0, deleted=[])
        )
    except (RuntimeError, ValueError) as error:
        # Chroma injoignable, URL inexploitable, collection incompatible : le
        # message porte déjà le remède, une trace de pile n'ajouterait rien.
        print(f"Indexation impossible : {error}", file=sys.stderr)
        return 1
    print(build_report(editions, failures, registry, index_report, text))
    if write_index:
        print(f"collection            : {collection_name(settings, text)}")

    anomalies = []
    if failures:
        anomalies.append(f"{len(failures)} fichier(s) illisible(s)")
    if registry.mismatches:
        anomalies.append(f"{len(registry.mismatches)} édition(s) écartée(s)")
    if anomalies:
        print(
            "\nIngestion incomplète : " + ", ".join(anomalies) + ". "
            "Corriger le corpus à la source, puis rejouer l'ingestion.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingestion du corpus Sorabel.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="normalise et contrôle sans écrire dans l'index",
    )
    parser.add_argument(
        "--text",
        choices=("clean", "raw"),
        default="clean",
        help="texte indexé : « clean » (le contrat) ou « raw » (témoin de l'axe 2)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="reconstruit la collection à neuf au lieu de la mettre à jour",
    )
    args = parser.parse_args(argv)
    return run(default_settings, write_index=not args.dry_run, reset=args.reset, text=args.text)


if __name__ == "__main__":
    sys.exit(main())
