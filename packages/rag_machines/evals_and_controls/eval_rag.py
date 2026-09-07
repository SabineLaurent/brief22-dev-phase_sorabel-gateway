"""Mesure du gain de la recherche avancée (E6) — ``eval/protocole-mesure.md``.

Deux modes, un seul script lancé par chemin comme ``check_index.py`` :

* **mode run** — ``--config {A,B,C} --text {clean,raw} --version-filter {on,off}
  [--out NOM]`` : rejoue les 30 questions de ``questions_rag.jsonl`` dans cette
  configuration fixe, écrit ``eval/resultats/NOM.csv``. Sans ``--out``, écrit sous
  ``eval/resultats/adhoc-*.csv`` — l'exploration ne prend jamais un nom de cible
  (protocole §10).
* **mode rapport** — ``--report`` : relit les six CSV nommés par les cibles Make
  publiées et réécrit **en entier** ``eval/rapport_gain.md``.

Le harnais attaque ``packages.rag_machines.retrieval.search`` directement, sans serveur MCP — c'est ce qui
permet de mesurer E6 dès ce chantier, avant que le serveur n'existe (chantier 3).

**La règle de départage n'a pas de drapeau ici** (protocole §10) : chaque question est
jouée une seule fois par le pipeline, et les deux rangs — avec et sans départage — sont
calculés dans la même passe (``packages.rag_machines.retrieval.search.apply_tiebreak`` est pure, rejouable sans
second appel au reranker) et publiés comme deux colonnes du même CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config import settings
from packages.rag_machines.retrieval.embedder import build_embedder
from packages.rag_machines.retrieval.reranker import build_reranker
from packages.rag_machines.retrieval.search import (
    STATUS_OK,
    STATUS_OUT_OF_CORPUS,
    Hit,
    Strategy,
    apply_tiebreak,
    search,
)

#: La racine du dépôt. **parents[3]**, pas [2] : ce module vit un niveau plus bas que
#: les autres, dans `evals_and_controls/`. Le compte était juste avant ce déplacement,
#: et il a fait pointer les jeux de questions et les rapports dans `packages/eval/`,
#: qui n'existe pas — la cible échouait à la lecture du jeu.
REPO_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_SET = REPO_ROOT / "eval" / "questions_rag.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "resultats"
REPORT_PATH = REPO_ROOT / "eval" / "rapport_gain.md"

_STRATEGY_BY_CONFIG: dict[str, Strategy] = {"A": "dense", "B": "lexical", "C": "hybrid"}
_CSV_FIELDS = (
    "id", "type", "criterion", "rank_with_tiebreak", "rank_without_tiebreak",
    "score", "refused", "code",
)

#: Les sept mesures publiées (protocole §10) — nom de cible → (config, texte, filtre).
#: Seule source de vérité du mapping ; le Makefile invoque ce script avec les mêmes
#: valeurs, `--report` s'y réfère pour savoir quel CSV lire et comment le lire.
TARGETS: dict[str, tuple[str, str, bool]] = {
    "mesure-dense": ("A", "clean", True),
    "mesure-lexical": ("B", "clean", True),
    "mesure-hybride": ("C", "clean", True),
    "mesure-sans-nettoyage": ("C", "raw", True),
    "mesure-sans-versions": ("C", "clean", False),
    "mesure-rag-simple": ("A", "raw", False),
}


def load_questions() -> list[dict]:
    return [
        json.loads(line)
        for line in QUESTIONS_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@dataclass(frozen=True)
class Row:
    """Une ligne du CSV — un couple (question, critère) dans une configuration fixe."""

    id: str
    type: str
    criterion: str
    rank_with_tiebreak: int | None
    rank_without_tiebreak: int | None
    score: float | None
    refused: str
    code: str


def _rank(hits: list[Hit], predicate: Callable[[Hit], bool]) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if predicate(hit):
            return rank
    return None


def _rows_for_question(
    question: dict, hits: list[Hit], hits_tiebreak: list[Hit], threshold: float | None
) -> list[Row]:
    """Les lignes d'une question. Le refus est calculé **pour toute question**, pas
    seulement les `hors_corpus` : une question couverte refusée à tort (RAG-19 à
    l'étape 2) est exactement ce que cette colonne doit pouvoir montrer."""
    top = hits_tiebreak[0] if hits_tiebreak else None
    score = top.score if top else None
    is_refused = threshold is not None and (top is None or top.score < threshold)
    refused = ("oui" if is_refused else "non") if threshold is not None else "n/a"
    code = STATUS_OUT_OF_CORPUS if is_refused else STATUS_OK

    q_type = question["type"]
    if q_type == "reference_exacte":
        attendu = question["attendu_reference"]

        def is_reference(hit: Hit) -> bool:
            return hit.reference == attendu

        def is_fiche(hit: Hit) -> bool:
            return hit.reference == attendu and hit.doc_type == "fiche_technique"

        return [
            Row(
                question["id"], q_type, criterion,
                _rank(hits_tiebreak, predicate), _rank(hits, predicate),
                score, refused, code,
            )
            for criterion, predicate in (("reference", is_reference), ("fiche_technique", is_fiche))
        ]

    if q_type == "couverte":
        attendu_type = question.get("attendu_type")
        if not attendu_type:
            # RAG-09 : Q5 §9 note que `attendu_type` manque sur une des 14 questions —
            # la ligne est écrite pour la traçabilité, exclue des métriques par son
            # `criterion` distinct (`compute_metrics` ne compte que `type_attendu`).
            return [Row(question["id"], q_type, "type_attendu_absent", None, None, score, refused, code)]

        def is_type(hit: Hit) -> bool:
            return hit.doc_type == attendu_type

        return [
            Row(
                question["id"], q_type, "type_attendu",
                _rank(hits_tiebreak, is_type), _rank(hits, is_type),
                score, refused, code,
            )
        ]

    return [Row(question["id"], q_type, "refus", None, None, score, refused, code)]


def run_measure(config: str, text: str, version_filter: bool, out_name: str | None) -> Path:
    strategy = _STRATEGY_BY_CONFIG[config]
    threshold = {"A": settings.refusal_threshold, "B": None, "C": settings.rerank_threshold}[config]

    # Construits une fois pour les 30 questions : reconstruire l'embedder ou le
    # reranker à chaque question rechargerait un modèle PyTorch 30 fois pour rien.
    embedder = build_embedder(settings)
    reranker = build_reranker(settings) if config == "C" else None

    rows: list[Row] = []
    for question in load_questions():
        result = search(
            question["question"],
            strategy=strategy,
            text=text,  # type: ignore[arg-type]
            top_k=settings.search_top_k,
            version_filter=version_filter,
            tiebreak=False,
            threshold=None,
            settings=settings,
            embedder=embedder,
            reranker=reranker,
        )
        hits = result.hits
        hits_tiebreak = apply_tiebreak(list(hits))
        rows.extend(_rows_for_question(question, hits, hits_tiebreak, threshold))

    name = out_name or f"adhoc-{config}-{text}-{'on' if version_filter else 'off'}-{int(time.time())}"
    path = write_csv(name, config, text, version_filter, rows)
    print(f"écrit : {path.relative_to(REPO_ROOT)} ({len(rows)} lignes, {len(load_questions())} questions)")
    _print_summary(config, compute_metrics(rows, tiebreak=True))
    return path


def write_csv(name: str, config: str, text: str, version_filter: bool, rows: list[Row]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            f"# cible={name} config={config} text={text} "
            f"version_filter={'on' if version_filter else 'off'}\n"
        )
        writer = csv.writer(handle)
        writer.writerow(_CSV_FIELDS)
        for row in rows:
            writer.writerow(
                [
                    row.id, row.type, row.criterion,
                    row.rank_with_tiebreak if row.rank_with_tiebreak is not None else "",
                    row.rank_without_tiebreak if row.rank_without_tiebreak is not None else "",
                    f"{row.score:.4f}" if row.score is not None else "",
                    row.refused, row.code,
                ]
            )
    return path


def read_csv(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    rows = []
    for record in csv.DictReader(lines):
        rows.append(
            Row(
                record["id"], record["type"], record["criterion"],
                int(record["rank_with_tiebreak"]) if record["rank_with_tiebreak"] else None,
                int(record["rank_without_tiebreak"]) if record["rank_without_tiebreak"] else None,
                float(record["score"]) if record["score"] else None,
                record["refused"], record["code"],
            )
        )
    return rows


def compute_metrics(rows: list[Row], *, tiebreak: bool) -> dict:
    """Les cinq métriques du protocole (Q5 §3), sur les rangs avec ou sans départage."""

    def rank(row: Row) -> int | None:
        return row.rank_with_tiebreak if tiebreak else row.rank_without_tiebreak

    hit_reference = [r for r in rows if r.criterion == "reference"]
    hit_fiche = [r for r in rows if r.criterion == "fiche_technique"]
    couverte = [r for r in rows if r.criterion == "type_attendu"]
    hors_corpus = [r for r in rows if r.type == "hors_corpus"]

    def hit_at_1(subset: list[Row]) -> tuple[int, int]:
        return sum(1 for r in subset if rank(r) == 1), len(subset)

    def mrr(subset: list[Row]) -> float:
        if not subset:
            return 0.0
        total = 0.0
        for row in subset:
            row_rank = rank(row)
            if row_rank:
                total += 1 / row_rank
        return total / len(subset)

    found_ranks: list[int] = []
    for row in couverte:
        row_rank = rank(row)
        if row_rank is not None:
            found_ranks.append(row_rank)

    return {
        "hit1_reference": hit_at_1(hit_reference),
        "hit1_fiche": hit_at_1(hit_fiche),
        "mrr_reference": mrr(hit_reference),
        "recall5_type": (len(found_ranks), len(couverte)),
        "rang_moyen_type": (sum(found_ranks) / len(found_ranks)) if found_ranks else None,
        "refus_corrects": (
            sum(1 for r in hors_corpus if r.refused == "oui"),
            len(hors_corpus),
            bool(hors_corpus) and all(r.refused == "n/a" for r in hors_corpus),
        ),
    }


def _print_summary(config: str, metrics: dict) -> None:
    hr, hf = metrics["hit1_reference"], metrics["hit1_fiche"]
    rc, rt, refus_na = metrics["refus_corrects"]
    print(f"  [{config}] Hit@1 référence {hr[0]}/{hr[1]}  ·  Hit@1 fiche {hf[0]}/{hf[1]}  ·  "
          f"MRR {metrics['mrr_reference']:.3f}  ·  Recall@5 type {metrics['recall5_type'][0]}/"
          f"{metrics['recall5_type'][1]}  ·  refus corrects "
          f"{'n/a' if refus_na else f'{rc}/{rt}'}")


def _ratio(pair: tuple[int, int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def _load_target(name: str) -> list[Row] | None:
    path = RESULTS_DIR / f"{name}.csv"
    if not path.exists():
        return None
    return read_csv(path)


def build_report() -> str:
    missing = [name for name in TARGETS if not (RESULTS_DIR / f"{name}.csv").exists()]
    if missing:
        raise RuntimeError(
            "CSV manquant pour : " + ", ".join(missing) + " — lancer `make " + missing[0] + "` "
            "(ou `make mesure`) avant `--report`."
        )
    rows_by_target = {name: _load_target(name) or [] for name in TARGETS}
    metrics = {name: compute_metrics(rows, tiebreak=True) for name, rows in rows_by_target.items()}

    def cell(name: str, key: str, kind: str) -> str:
        value = metrics[name][key]
        if kind == "ratio":
            return _ratio(value)
        if kind == "float":
            return f"{value:.3f}"
        return "n/a"

    lines = [
        "# Rapport de gain — recherche avancée (E6)",
        "",
        "Généré par `make mesure` à partir des CSV de `eval/resultats/` — "
        "voir `eval/protocole-mesure.md` pour le protocole complet. **Ne pas éditer à la "
        "main** : `make mesure` réécrit ce fichier en entier.",
        "",
        "## Axe 1 — la recherche, à ingestion constante (E6)",
        "",
        "Texte nettoyé, filtre de version actif, règle de départage appliquée dans les "
        "trois configurations (`eval/protocole-mesure.md` §1). Profil `commercial` — "
        "périmètre documentaire complet, le cas le plus difficile pour le refus (Q5 §5).",
        "",
        "| sous-ensemble | métrique | A dense | B lexical | C hybride |",
        "|---|---|---:|---:|---:|",
        "| reference_exacte | Hit@1 (référence) | "
        + " | ".join(cell(n, "hit1_reference", "ratio") for n in ("mesure-dense", "mesure-lexical", "mesure-hybride"))
        + " |",
        "| reference_exacte | Hit@1 (fiche technique) | "
        + " | ".join(cell(n, "hit1_fiche", "ratio") for n in ("mesure-dense", "mesure-lexical", "mesure-hybride"))
        + " |",
        "| reference_exacte | MRR | "
        + " | ".join(cell(n, "mrr_reference", "float") for n in ("mesure-dense", "mesure-lexical", "mesure-hybride"))
        + " |",
        "| couverte | Recall@5 (`attendu_type`, n="
        + str(metrics["mesure-dense"]["recall5_type"][1]) + ") | "
        + " | ".join(cell(n, "recall5_type", "ratio") for n in ("mesure-dense", "mesure-lexical", "mesure-hybride"))
        + " |",
        "| hors_corpus | refus corrects | "
        + cell("mesure-dense", "refus_corrects", "ratio") + " | n/a — Q4 §3 | "
        + cell("mesure-hybride", "refus_corrects", "ratio") + " |",
        "",
        "`B` n'a pas de seuil de refus praticable (aucune échelle bornée sur un score BM25 "
        "— Q4 §3) : la case vide est un résultat, pas un trou.",
        "",
        "",
        "## Effet de la règle de départage — avec / sans, sur les trois sous-ensembles",
        "",
        "| configuration | Hit@1 référence (sans / avec) | Hit@1 fiche (sans / avec) | "
        "Recall@5 type (sans / avec) |",
        "|---|---:|---:|---:|",
    ]
    for name, label in (
        ("mesure-dense", "A dense"), ("mesure-lexical", "B lexical"), ("mesure-hybride", "C hybride"),
    ):
        with_tb = compute_metrics(rows_by_target[name], tiebreak=True)
        without_tb = compute_metrics(rows_by_target[name], tiebreak=False)
        lines.append(
            f"| {label} | {_ratio(without_tb['hit1_reference'])} / {_ratio(with_tb['hit1_reference'])} "
            f"| {_ratio(without_tb['hit1_fiche'])} / {_ratio(with_tb['hit1_fiche'])} "
            f"| {_ratio(without_tb['recall5_type'])} / {_ratio(with_tb['recall5_type'])} |"
        )

    lines += [
        "",
        "## Axe 2 — l'ingestion, à recherche constante",
        "",
        "Configuration C fixée dans les deux cas — seul un flag d'ingestion varie contre "
        "`mesure-hybride`.",
        "",
        "| | Hit@1 référence | Hit@1 fiche | Recall@5 type | refus corrects |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, label in (
        ("mesure-hybride", "C — texte nettoyé (référence)"),
        ("mesure-sans-nettoyage", "C — texte brut (`--text raw`)"),
        ("mesure-sans-versions", "C — sans filtre de version (`--version-filter off`)"),
    ):
        m = metrics[name]
        lines.append(
            f"| {label} | {_ratio(m['hit1_reference'])} | {_ratio(m['hit1_fiche'])} | "
            f"{_ratio(m['recall5_type'])} | {_ratio(m['refus_corrects'][:2])} |"
        )

    rag_simple = compute_metrics(rows_by_target["mesure-rag-simple"], tiebreak=False)
    rag_avance = metrics["mesure-hybride"]
    lines += [
        "",
        "## La ligne « RAG simple »",
        "",
        "Un point de comparaison lisible, publié **en plus** des deux axes ci-dessus, "
        "jamais à leur place (protocole §4) : `texte brut · dense seul · sans filtre de "
        "version · sans départage` contre `texte nettoyé · hybride · filtre actif · "
        "départage actif`.",
        "",
        "| | Hit@1 référence | Hit@1 fiche | Recall@5 type |",
        "|---|---:|---:|---:|",
        f"| RAG simple | {_ratio(rag_simple['hit1_reference'])} | {_ratio(rag_simple['hit1_fiche'])} "
        f"| {_ratio(rag_simple['recall5_type'])} |",
        f"| RAG avancé | {_ratio(rag_avance['hit1_reference'])} | {_ratio(rag_avance['hit1_fiche'])} "
        f"| {_ratio(rag_avance['recall5_type'])} |",
        "",
        "## Limites méthodologiques — à lire avant les chiffres ci-dessus",
        "",
        "- **huit questions par sous-ensemble** : un échantillon minuscule, le seuil de "
        "refus reste réglé sur une base étroite (protocole §9) ;",
        "- **`attendu_type` ne prend que trois valeurs**, et manque sur une des 14 "
        "questions `couverte` (RAG-09) — ce sous-ensemble détecte une régression, il ne "
        "démontre pas un gain ;",
        "- **sur les 6 questions `couverte` attendant une `procedure_sav`, le titre est le "
        "seul discriminant** — le nettoyage SAV rend le corps des 80 procédures identique ;",
        "- **RAG-19 et RAG-20 sont en tension avec le corpus** (sujet absent pour l'une, "
        "terme présent en notice seulement pour l'autre) : une configuration qui les rate "
        "n'a pas régressé, voir leur ligne dans les CSV individuels ;",
        "- **le compte porte sur les questions, pas sur les références** : RAG-01 et "
        "RAG-02 partagent `REF-8842` — 8 questions pour 7 références distinctes.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesure du gain de la recherche avancée (E6).")
    parser.add_argument("--config", choices=("A", "B", "C"))
    parser.add_argument("--text", choices=("clean", "raw"), default="clean")
    parser.add_argument("--version-filter", choices=("on", "off"), default="on")
    parser.add_argument("--out", help="nom de la cible — écrit eval/resultats/<NOM>.csv")
    parser.add_argument("--report", action="store_true", help="régénère eval/rapport_gain.md")
    args = parser.parse_args(argv)

    if args.report:
        try:
            REPORT_PATH.write_text(build_report(), encoding="utf-8")
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"écrit : {REPORT_PATH.relative_to(REPO_ROOT)}")
        return 0

    if args.config is None:
        parser.error("--config est requis hors du mode --report")
    try:
        run_measure(args.config, args.text, args.version_filter == "on", args.out)
    except RuntimeError as error:
        # Chroma injoignable, index BM25 manquant (collection ingérée avant cette
        # étape) : même style que ingest/cli.py — un message actionnable, pas une
        # trace de pile.
        print(f"Mesure impossible : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
