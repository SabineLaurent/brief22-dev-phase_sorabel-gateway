"""Calibration du seuil de refus, sur le jeu de calibration — jamais sur le jeu de mesure.

Régler un seuil sur les questions qui serviront à le noter ne mesure plus rien : le chiffre
publié constaterait qu'on a bien réglé (``Q4`` §6). Ce script ne lit donc que
``eval/questions_calibration.jsonl``, et refuse de s'exécuter sur le jeu d'évaluation.

Il n'écrit aucun chiffre publié : il propose une valeur pour ``REFUSAL_THRESHOLD``, à
reporter dans la configuration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from config import settings
from retrieval.search import search

CALIBRATION_SET = Path(__file__).resolve().parent.parent / "eval" / "questions_calibration.jsonl"


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def best_threshold(covered: list[float], out_of_corpus: list[float]) -> tuple[float, int, int]:
    """Le seuil qui sépare le mieux les deux populations.

    Balaie les valeurs candidates entre les deux nuages et retient celle qui maximise le
    nombre de décisions correctes — refuser une question hors corpus, répondre à une
    question couverte. En cas d'égalité, le seuil le plus bas gagne : à qualité égale,
    mieux vaut répondre à tort que refuser à tort une question que le corpus couvre.
    """
    candidates = sorted({round(score, 4) for score in covered + out_of_corpus})
    best = (0.0, -1, 0, 0)
    for threshold in candidates:
        refused_ok = sum(1 for s in out_of_corpus if s < threshold)
        answered_ok = sum(1 for s in covered if s >= threshold)
        total = refused_ok + answered_ok
        if total > best[1]:
            best = (threshold, total, refused_ok, answered_ok)
    return best[0], best[2], best[3]


def main() -> int:
    questions = load_questions(CALIBRATION_SET)
    scores: dict[str, list[float]] = {"couverte": [], "hors_corpus": []}

    print(f"Jeu de calibration : {CALIBRATION_SET.name} — {len(questions)} questions")
    print(f"Index : recherche dense, filtre de version actif, top_k={settings.search_top_k}\n")

    for question in questions:
        # Seuil désactivé : on veut le score, pas la décision qu'il produirait.
        result = search(question["question"], threshold=None)
        score = result.hits[0].score if result.hits else 0.0
        scores[question["type"]].append(score)
        trap = f"  ← {question['piege']}" if question.get("piege") else ""
        print(f"  {score:.3f}  {question['id']}  {question['type']:<12} "
              f"{question['question'][:52]}{trap}")

    covered, out_of_corpus = scores["couverte"], scores["hors_corpus"]
    print("\nDistribution des scores du premier résultat")
    print(f"  couverte    ({len(covered):>2}) : {min(covered):.3f} – {max(covered):.3f}")
    print(f"  hors_corpus ({len(out_of_corpus):>2}) : "
          f"{min(out_of_corpus):.3f} – {max(out_of_corpus):.3f}")

    separable = min(covered) > max(out_of_corpus)
    print(f"\n  populations séparables : {'OUI' if separable else 'NON — elles se chevauchent'}")

    threshold, refused_ok, answered_ok = best_threshold(covered, out_of_corpus)
    print(f"\nSeuil proposé : {threshold:.3f}")
    print(f"  refus corrects  : {refused_ok} / {len(out_of_corpus)} questions hors corpus")
    print(f"  réponses tenues : {answered_ok} / {len(covered)} questions couvertes")
    print("\nÀ reporter dans REFUSAL_THRESHOLD (.env). Ce chiffre est un réglage, "
          "pas un résultat :\nil ne se publie pas, il se rejoue sur le jeu de mesure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
