"""Le jeu des 24 questions SQL, passé au tool `ask_database`.

Ce harnais mesure ce que `check_sql` ne peut pas mesurer : **la génération**, qui n'est pas
déterministe. Un run consomme un appel de modèle par question.

Il est **hors du protocole de mesure du RAG**, qui le dit lui-même — `eval/questions_sql.jsonl`
y est rangé « chantier 2, hors de ce protocole ». Rien ici ne touche `eval/rapport_gain.md`
ni les `mesure-*.csv` : les noms sont distincts exprès, pour qu'un chiffre SQL ne puisse
jamais être lu comme un chiffre E6.

Ce qui est mesuré est la **conformité du code de sortie au type de la question**, pas la
justesse du chiffre : le jeu ne porte aucun attendu chiffré, et les valeurs de référence
vivent en prose dans `2-text-to-sql/description-base.md` §8. Les quatre valeurs que les
tests d'acceptance vérifient, elles, sont contrôlées par `check_sql`, sans modèle.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from config import settings
from packages.text_to_sql_factory.generator import build_generator
from packages.text_to_sql_factory.tools import ask_database

#: La racine du dépôt. **parents[3]**, pas [2] : ce module vit un niveau plus bas que
#: les autres, dans `evals_and_controls/`. Le compte était juste avant ce déplacement,
#: et il a fait pointer les jeux de questions et les rapports dans `packages/eval/`,
#: qui n'existe pas — la cible échouait à la lecture du jeu.
REPO_ROOT = Path(__file__).resolve().parents[3]
QUESTION_SET = REPO_ROOT / "eval" / "questions_sql.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "resultats"
REPORT = REPO_ROOT / "eval" / "rapport_sql.md"

#: Les codes acceptables pour chaque type de question. Un ensemble et non une valeur
#: unique : le type `metier` couvre aussi bien un résultat qu'une absence de ligne
#: (SQL-08, `CMD-2026-0042` n'existe pas) ou une désignation ambiguë (SQL-10, quatre
#: disjoncteurs portent ce libellé). Les trois sont des réussites — seul un refus serait
#: un échec.
EXPECTED_CODES: dict[str, frozenset[str]] = {
    "metier": frozenset({"ok", "aucune_ligne", "ambiguite_donnees"}),
    "ecriture": frozenset({"ecriture_refusee"}),
    "table_interdite": frozenset({"perimetre_interdit"}),
    "hors_schema": frozenset({"hors_schema"}),
    "ambigue": frozenset({"clarification"}),
}

_CSV_FIELDS = ("id", "type", "profil", "status", "code", "conforme", "repare", "n_rows",
               "latency_ms", "sql")


@dataclass(frozen=True)
class Row:
    """Une question, et ce que le tool en a fait."""

    id: str
    type: str
    profil: str
    status: str
    code: str
    conforme: bool
    #: Le contrôle 6 a écarté la première requête et le modèle en a produit une seconde.
    repare: bool
    n_rows: int
    latency_ms: float
    sql: str


def load_questions(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run(questions: list[dict]) -> list[Row]:
    """Passe chaque question au tool, avec un générateur construit **une fois**."""
    generator = build_generator(settings)
    rows: list[Row] = []
    for question in questions:
        before = generator.repairs
        answer = ask_database(question["question"], question["profil"], settings, generator)
        payload = answer.payload
        code = str(payload.get("code", ""))
        row = Row(
            id=str(question["id"]),
            type=str(question["type"]),
            profil=str(question["profil"]),
            status=answer.status,
            code=code,
            conforme=code in EXPECTED_CODES.get(str(question["type"]), frozenset()),
            repare=generator.repairs > before,
            n_rows=int(payload.get("n_rows", 0)),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            sql=str(payload.get("sql", "")),
        )
        rows.append(row)
        mark = "ok  " if row.conforme else "ÉCART"
        repair = "  (reprise)" if row.repare else ""
        print(f"  [{mark}] {row.id}  {row.type:16} {row.status:13} {row.code}{repair}")
    return rows


def write_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# jeu={QUESTION_SET.name} modele={settings.llm_chat_model} "
                     f"limit={settings.sql_default_limit} plafond={settings.sql_max_rows} "
                     f"timeout={settings.sql_timeout_s:g}s\n")
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row.id, "type": row.type, "profil": row.profil, "status": row.status,
                "code": row.code, "conforme": int(row.conforme), "repare": int(row.repare),
                "n_rows": row.n_rows,
                "latency_ms": f"{row.latency_ms:.1f}", "sql": row.sql,
            })


def read_csv(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    return [
        Row(
            id=entry["id"], type=entry["type"], profil=entry["profil"], status=entry["status"],
            code=entry["code"], conforme=entry["conforme"] == "1",
            repare=entry.get("repare", "0") == "1",
            n_rows=int(entry["n_rows"] or 0), latency_ms=float(entry["latency_ms"] or 0.0),
            sql=entry["sql"],
        )
        for entry in csv.DictReader(lines)
    ]


def build_report(rows: list[Row], csv_name: str) -> str:
    """Écrit le rapport **en entier**, jamais par retouche."""
    lines = [
        "# Text-to-SQL — conformité sur les 24 questions du jeu",
        "",
        f"> Généré par `make eval-sql` le {date.today().isoformat()}. "
        "**Ne pas éditer à la main.**",
        "",
        f"Jeu : `eval/questions_sql.jsonl` · modèle de génération : `{settings.llm_chat_model}` "
        f"· CSV : `eval/resultats/{csv_name}.csv`",
        "",
        "Ce qui est mesuré est la **conformité du code de sortie au type de la question**, "
        "pas la justesse",
        "du chiffre : le jeu ne porte aucun attendu chiffré. Les quatre valeurs que les tests "
        "d'acceptance",
        "vérifient sont contrôlées par `make check-sql`, sans appel de modèle et donc sans "
        "part de hasard.",
        "",
        "## Conformité par type de question",
        "",
        "| Type | Codes acceptés | Questions | Conformes |",
        "|---|---|---:|---:|",
    ]
    for kind in ("metier", "ecriture", "table_interdite", "hors_schema", "ambigue"):
        subset = [row for row in rows if row.type == kind]
        if not subset:
            continue
        accepted = " · ".join(f"`{code}`" for code in sorted(EXPECTED_CODES[kind]))
        conform = sum(1 for row in subset if row.conforme)
        lines.append(f"| `{kind}` | {accepted} | {len(subset)} | **{conform}/{len(subset)}** |")

    total = sum(1 for row in rows if row.conforme)
    repaired = [row for row in rows if row.repare]
    lines += [
        f"| **ensemble** | | **{len(rows)}** | **{total}/{len(rows)}** |",
        "",
        "## Reprises après l'essai à blanc",
        "",
        "Le contrôle 6 prépare la requête par `EXPLAIN` avant de l'exécuter. Quand le moteur "
        "la refuse —",
        "une fonction que sqlglot n'a pas su transposer, une colonne inventée, une ambiguïté "
        "de jointure —",
        "l'erreur est rendue au modèle pour **une** reprise, jamais deux. Un refus de droits "
        "n'en déclenche",
        "aucune : il ne se renégocie pas.",
        "",
        f"**{len(repaired)}/{len(rows)}** question(s) ont demandé une reprise ; "
        f"**{sum(1 for row in repaired if row.conforme)}** ont fini conformes.",
        "",
        "## Détail question par question",
        "",
        "| id | profil | type | `status` | `code` | reprise | lignes | requête |",
        "|---|---|---|---|---|:-:|---:|---|",
    ]
    for row in rows:
        mark = "" if row.conforme else " ⚠"
        sql = f"`{row.sql[:70]}`" if row.sql else "—"
        lines.append(
            f"| {row.id}{mark} | {row.profil} | `{row.type}` | `{row.status}` | "
            f"`{row.code}` | {'oui' if row.repare else ''} | {row.n_rows or ''} | {sql} |"
        )

    ecarts = [row for row in rows if not row.conforme]
    lines += ["", "## Écarts", ""]
    if ecarts:
        lines += [f"- **{row.id}** (`{row.type}`) a rendu `{row.code}` — "
                  f"attendu {' ou '.join(sorted(EXPECTED_CODES[row.type]))}." for row in ecarts]
    else:
        lines.append("Aucun : les 24 questions rendent un code conforme à leur type.")

    lines += [
        "",
        "## Ce que ce rapport ne mesure pas",
        "",
        "- **la justesse des chiffres.** Le jeu ne porte pas d'attendu ; les valeurs de "
        "référence sont en prose dans `docs/conception/2-text-to-sql/description-base.md` §8.",
        "- **la stabilité de la génération.** Un run, un appel par question. Deux runs peuvent "
        "différer, et c'est la raison pour laquelle E3 et E5 sont vérifiées ailleurs, sans "
        "modèle.",
        "- **le journal (E5) et l'étage 2 (`tool_interdit`).** Ils relèvent du serveur MCP, "
        "chantier 3 : aucun appel n'est journalisé ici.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Passe les 24 questions SQL au tool ask_database et publie la conformité."
    )
    parser.add_argument("--out", default="eval-sql",
                        help="nom du CSV écrit sous eval/resultats/ (défaut : eval-sql)")
    parser.add_argument("--report", action="store_true",
                        help="régénère le rapport depuis le CSV, sans rejouer les questions")
    args = parser.parse_args(argv)

    csv_path = RESULTS_DIR / f"{args.out}.csv"

    if args.report:
        if not csv_path.exists():
            print(f"CSV absent : {csv_path} — lancer `make eval-sql` d'abord", file=sys.stderr)
            return 1
        rows = read_csv(csv_path)
    else:
        if not QUESTION_SET.exists():
            print(f"jeu de questions absent : {QUESTION_SET}", file=sys.stderr)
            return 1
        questions = load_questions(QUESTION_SET)
        print(f"{len(questions)} questions, un appel de modèle chacune\n")
        try:
            rows = run(questions)
        except RuntimeError as error:
            # Génération non configurée, base absente : un message qui porte le remède.
            print(f"\nÉvaluation impossible : {error}", file=sys.stderr)
            return 1
        write_csv(rows, csv_path)
        print(f"\nCSV écrit : {csv_path.relative_to(REPO_ROOT)}")

    REPORT.write_text(build_report(rows, args.out), encoding="utf-8")
    print(f"Rapport écrit : {REPORT.relative_to(REPO_ROOT)}")

    conform = sum(1 for row in rows if row.conforme)
    print(f"\nConformité : {conform}/{len(rows)}")
    return 0 if conform == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
