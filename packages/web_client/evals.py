"""Les questions des jeux d'évaluation, chargées une fois pour les deux interfaces.

Extrait de ``app.py`` quand le second front est arrivé : les deux rejouent les mêmes
identifiants (``RAG-03``, ``SQL-01``, ``CAL-02``), et deux chargeurs auraient fini par ne
plus lire les mêmes fichiers. Le module ne fait que lire — aucun décorateur Chainlit, pour
qu'une interface puisse l'importer sans enregistrer les gestionnaires de l'autre.
"""

from __future__ import annotations

import json
from pathlib import Path

#: La racine du dépôt, déduite de l'emplacement de ce fichier et **non du répertoire de
#: travail**. Sans elle, les chemins étaient relatifs au CWD : un lancement depuis un autre
#: dossier — ou un conteneur dont le `WORKDIR` diffère — chargeait zéro question, en
#: silence, parce qu'un fichier absent est ignoré ci-dessous. L'accueil promettait alors
#: `RAG-03` et le sélecteur n'avait aucun starter, tandis que `RAG-03` tapé au chat partait
#: au modèle comme question littérale.
#:
#: Déduite ici plutôt qu'importée de ``config`` : ce module est chargé par le front, qui
#: depuis le découplage n'importe plus rien du backend.
_ROOT = Path(__file__).resolve().parents[2]

EVAL_FILES = [
    _ROOT / "eval" / "questions_rag.jsonl",
    _ROOT / "eval" / "questions_sql.jsonl",
    _ROOT / "eval" / "questions_calibration.jsonl",
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
