"""Les questions des jeux d'évaluation, chargées une fois pour les deux interfaces.

Extrait de ``app.py`` quand le second front est arrivé : les deux rejouent les mêmes
identifiants (``RAG-03``, ``SQL-01``, ``CAL-02``), et deux chargeurs auraient fini par ne
plus lire les mêmes fichiers. Le module ne fait que lire — aucun décorateur Chainlit, pour
qu'une interface puisse l'importer sans enregistrer les gestionnaires de l'autre.
"""

from __future__ import annotations

import json
from pathlib import Path

EVAL_FILES = [
    Path("eval/questions_rag.jsonl"),
    Path("eval/questions_sql.jsonl"),
    Path("eval/questions_calibration.jsonl"),
]


def load_eval_questions() -> dict[str, str]:
    """Les questions par identifiant. Un fichier absent est ignoré, pas fatal : la mesure
    peut vivre sans que l'interface tombe."""
    questions: dict[str, str] = {}
    for path in EVAL_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            questions[entry["id"]] = entry["question"]
    return questions
