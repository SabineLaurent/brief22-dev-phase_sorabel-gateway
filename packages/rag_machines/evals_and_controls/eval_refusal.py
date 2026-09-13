"""Le refus documentaire tel qu'il est **servi** — axe 4 du protocole de mesure.

Ce script existe pour refermer un malentendu de lecture, et il vaut la peine d'être nommé :
``eval_rag.py`` mesure le refus sur ``search()`` suivi d'une comparaison au seuil, donc sur
**une seule des deux barrières**, et publie ce chiffre dans la ligne « refus corrects » de
``rapport_gain.md``. Or E1 ne vit pas dans ``search()`` : elle vit dans ``answer_question``,
et ce tool a **deux** barrières.

| | Où elle est | Ce qu'elle lit | Nature |
|---|---|---|---|
| **barrière 1** — ``hors_corpus`` | ``search(threshold=…)`` | le score du premier résultat | déterministe, **avant tout appel au modèle** |
| **barrière 2** — ``contexte_insuffisant`` | la garde de suffisance du rédacteur | les extraits eux-mêmes | jugement du modèle, donc **non déterministe** |

Le rapport publie les **deux colonnes**. Publier la seconde seule ferait passer la barrière 1
pour insuffisante ; publier la première seule — ce que fait `rapport_gain.md`, à bon droit
puisqu'il mesure un étage de recherche — laisse lire un chiffre de recherche comme une mesure
d'E1. C'est exactement l'erreur commise dans la première version de la revue du 2026-09-07.

**Une seule chose varie ici : le nombre de barrières prises en compte.** Le profil, le jeu,
l'étage de recherche, le seuil et le filtre de version sont ceux du protocole — profil
``commercial``, périmètre documentaire complet, donc le cas le plus difficile pour le refus
(``Q5`` §5).

**Un seul appel de tool par question suffit aux deux colonnes**, et c'est ce qui rend la
mesure honnête : les deux barrières sont lues sur *le même* appel servi, jamais sur deux
exécutions dont l'une serait reconstituée. Le code rendu dit lequel des deux étages a tranché
— ``hors_corpus`` pour la barrière 1, ``contexte_insuffisant`` pour la 2.

``search_docs`` n'a **aucune** barrière et n'en aura pas (``03-catalogue-tools.md``) : c'est
le tool sur lequel E6 se mesure, et un seuil qui masquerait les résultats sous la barre
rendrait le rang inobservable. Il n'apparaît donc pas ici.

Usage : make mesure-refus
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from config import settings
from packages.rag_machines.tools import answer_question, search_docs, threshold_for

REPO_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_SET = REPO_ROOT / "eval" / "questions_rag.jsonl"
RESULTS_PATH = REPO_ROOT / "eval" / "resultats" / "mesure-refus.csv"
REPORT_PATH = REPO_ROOT / "eval" / "rapport_refus.md"

#: Le profil du protocole (§6) : périmètre documentaire complet. C'est le cas le plus
#: difficile pour le refus, et le seul indépendant d'un filtre de gouvernance — mesurer le
#: refus sous un profil restreint mélangerait la barrière et la matrice.
PROFILE = "commercial"

#: Le code rendu par chaque barrière. Ni l'un ni l'autre n'est dans ``REFUSAL_CODES`` :
#: ce sont des **non-réponses**, pas des refus de droits, et les compter comme des refus
#: ferait dire ``denied`` au journal sur une question hors sujet.
BARRIER_CODE = {1: "hors_corpus", 2: "contexte_insuffisant"}

_CSV_FIELDS = ("pass", "id", "type", "score_top", "code", "barrier", "n_sources")


def _questions() -> list[dict]:
    return [json.loads(line) for line in
            QUESTIONS_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _barrier(code: str) -> int:
    """L'étage qui a tranché : 1, 2, ou 0 si la question a été servie."""
    for barrier, barrier_code in BARRIER_CODE.items():
        if code == barrier_code:
            return barrier
    return 0


def run(passes: int) -> list[dict]:
    threshold = threshold_for("hybrid", settings)
    if threshold is None:
        raise RuntimeError(
            "RERANK_THRESHOLD n'est pas renseigné : sans seuil, la barrière 1 ne tranche "
            "rien et les deux colonnes seraient identiques. Le régler avec "
            "`make calibrer-hybride`."
        )
    questions = _questions()
    rows: list[dict] = []
    for run_index in range(1, passes + 1):
        for question in questions:
            # Le score du premier résultat, lu par le tool qui n'a pas de barrière : c'est
            # exactement le classement que `answer_question` verra, et la seule manière de
            # relever le score **sans** que le seuil l'ait déjà escamoté.
            listing = search_docs(question["question"], PROFILE, settings=settings)
            hits = listing.payload.get("hits") or []
            answer = answer_question(question["question"], PROFILE, settings=settings)
            rows.append({
                "pass": run_index,
                "id": question["id"],
                "type": question["type"],
                "score_top": f"{hits[0]['score']:.4f}" if hits else "",
                "code": answer.code,
                "barrier": _barrier(answer.code),
                "n_sources": len(answer.payload.get("sources") or []),
            })
    return rows


def _counts(rows: list[dict], types: tuple[str, ...], run_index: int | None = None) -> dict:
    """Les deux colonnes, sur un sous-ensemble de questions, pour **une** passe.

    ``barrier_1`` est ce que ``rapport_gain.md`` publie ; ``both`` est ce que le client
    reçoit. La différence est le rattrapage de la barrière 2 — et sur les questions à cible,
    c'est un coût, pas un gain.

    Le décompte est par passe et jamais cumulé : additionner trois passes rendrait un
    dénominateur de 24 là où le jeu compte 8 questions, et un lecteur lirait « 15 / 24 » pour
    un refus qui vaut 5 sur 8.
    """
    subset = [r for r in rows if r["type"] in types
              and (run_index is None or r["pass"] == run_index)]
    return {
        "n": len(subset),
        "barrier_1": sum(1 for r in subset if r["barrier"] == 1),
        "barrier_2": sum(1 for r in subset if r["barrier"] == 2),
        "both": sum(1 for r in subset if r["barrier"] != 0),
        "served": sum(1 for r in subset if r["barrier"] == 0),
        # Ce qui serait servi si la barrière 2 n'existait pas — la colonne « barrière 1
        # seule » du tableau. Ce n'est pas `n - barrier_1` par distraction : c'est bien la
        # définition de la colonne, et la nommer évite de la recalculer à l'affichage.
        "served_barrier_1": sum(1 for r in subset if r["barrier"] != 1),
    }


def _across(rows: list[dict], types: tuple[str, ...], passes: int, key: str) -> str:
    """La valeur d'une métrique, ou sa plage si elle varie d'une passe à l'autre.

    Une plage publiée est plus honnête qu'une moyenne : elle dit que le chiffre bouge, et
    elle laisse voir de combien. Une moyenne le cacherait derrière une décimale.
    """
    values = sorted({_counts(rows, types, run)[key] for run in range(1, passes + 1)})
    return str(values[0]) if len(values) == 1 else f"{values[0]}–{values[-1]}"


def _ids(rows: list[dict], types: tuple[str, ...], barrier: int) -> list[str]:
    seen = {r["id"] for r in rows if r["type"] in types and r["barrier"] == barrier}
    return sorted(seen)


def _cite(ids: list[str]) -> str:
    if not ids:
        return "aucune"
    if len(ids) == 1:
        return ids[0]
    return ", ".join(ids[:-1]) + f" et {ids[-1]}"


def _unstable(rows: list[dict], passes: int) -> list[str]:
    """Les questions dont le verdict change d'une passe à l'autre.

    La barrière 2 est un jugement de modèle : son instabilité est une propriété de la
    mesure, pas un défaut de l'exécution. Elle est **publiée**, jamais lissée par une
    moyenne — une moyenne cacherait quelle question bouge.
    """
    if passes < 2:
        return []
    verdicts: dict[str, set[str]] = {}
    for row in rows:
        verdicts.setdefault(row["id"], set()).add(row["code"])
    return sorted(qid for qid, codes in verdicts.items() if len(codes) > 1)


def _bands(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """Les plages de score du premier résultat, par type de question.

    Elles servent la réserve du protocole (§5) : un seuil ne sépare que ce que les
    populations séparent, et ces trois plages se recouvrent.
    """
    bands: dict[str, tuple[float, float]] = {}
    for kind in ("reference_exacte", "couverte", "hors_corpus"):
        scores = [float(r["score_top"]) for r in rows
                  if r["type"] == kind and r["score_top"]]
        if scores:
            bands[kind] = (min(scores), max(scores))
    return bands


ANSWERABLE = ("reference_exacte", "couverte")
OUT_OF_CORPUS = ("hors_corpus",)


def write_report(rows: list[dict], passes: int) -> None:
    # Les dénominateurs sont ceux d'**une** passe : 8 questions hors corpus, 22 à cible.
    out = _counts(rows, OUT_OF_CORPUS, 1)
    answerable = _counts(rows, ANSWERABLE, 1)
    threshold = threshold_for("hybrid", settings)
    bands = _bands(rows)
    unstable = _unstable(rows, passes)

    lines = [
        "# Le refus documentaire, mesuré sur les deux barrières",
        "",
        "Axe 4 du [protocole de mesure](protocole-mesure.md). Une seule chose varie : le",
        "**nombre de barrières prises en compte**. Profil `commercial` — périmètre",
        "documentaire complet, donc le cas le plus difficile pour le refus —, étage hybride,",
        "texte nettoyé, filtre de version actif, les 30 questions de `questions_rag.jsonl`,",
        f"seuil du reranker à **{threshold:.4f}**.",
        "",
        "## Pourquoi ce rapport existe",
        "",
        "[`rapport_gain.md`](rapport_gain.md) publie une ligne « refus corrects ». Elle est",
        "mesurée sur `search()` suivi d'une comparaison au seuil — **la barrière 1 seule**,",
        "ce qui est le bon périmètre pour un rapport qui compare des étages de recherche.",
        "Mais E1 ne vit pas dans `search()` : elle vit dans `answer_question`, qui a deux",
        "barrières. Lire le chiffre de `rapport_gain.md` comme le refus servi est une erreur",
        "— elle a été commise dans la première version de la revue du 2026-09-07.",
        "",
        "| | Où | Ce qu'elle lit | Nature |",
        "|---|---|---|---|",
        "| **barrière 1** `hors_corpus` | `search(threshold=…)` | le score du premier "
        "résultat | déterministe, **avant tout appel au modèle** |",
        "| **barrière 2** `contexte_insuffisant` | la garde de suffisance du rédacteur | les "
        "extraits eux-mêmes | jugement du modèle, **non déterministe** |",
        "",
        "Les deux colonnes sont lues sur **le même appel servi** : le code rendu dit lequel",
        "des deux étages a tranché. Aucune des deux n'est reconstituée.",
        "",
        "`search_docs` n'a aucune barrière et n'en aura pas : c'est le tool sur lequel E6 se",
        "mesure, et un seuil qui masque les résultats sous la barre rend le rang",
        "inobservable. Il n'apparaît pas dans cette mesure.",
        "",
        "## Résultats",
        "",
        f"*{passes} passe{'s' if passes > 1 else ''}, "
        f"{len(rows)} appels de `answer_question`.*",
        "",
        "*Les dénominateurs sont ceux d'**une** passe ; une plage `n–m` signale une métrique",
        "qui bouge d'une passe à l'autre.*",
        "",
        "### Les 8 questions hors corpus — le refus qu'on veut",
        "",
        "| | Barrière 1 seule | Les deux barrières |",
        "|---|---|---|",
        f"| Refus corrects | {_across(rows, OUT_OF_CORPUS, passes, 'barrier_1')} / "
        f"{out['n']} | **{_across(rows, OUT_OF_CORPUS, passes, 'both')} / {out['n']}** |",
        f"| Servies malgré tout | "
        f"{_across(rows, OUT_OF_CORPUS, passes, 'served_barrier_1')} | "
        f"{_across(rows, OUT_OF_CORPUS, passes, 'served')} |",
        "",
        f"La barrière 2 rattrape **{_across(rows, OUT_OF_CORPUS, passes, 'barrier_2')}** "
        "question(s) que le seuil laisse",
        f"passer : {_cite(_ids(rows, OUT_OF_CORPUS, 2))}. La barrière 1 en tranche",
        f"{out['barrier_1']} : {_cite(_ids(rows, OUT_OF_CORPUS, 1))} — et elle les tranche",
        "**sans dépenser un token**, ce que la seconde ne peut pas faire.",
        "",
        "### Les 22 questions à cible — le refus qu'on ne veut pas",
        "",
        "| | Barrière 1 seule | Les deux barrières |",
        "|---|---|---|",
        f"| Faux refus | {_across(rows, ANSWERABLE, passes, 'barrier_1')} / "
        f"{answerable['n']} | "
        f"**{_across(rows, ANSWERABLE, passes, 'both')} / {answerable['n']}** |",
        f"| Réponses servies | "
        f"{_across(rows, ANSWERABLE, passes, 'served_barrier_1')} | "
        f"{_across(rows, ANSWERABLE, passes, 'served')} |",
        "",
        f"La barrière 1 en refuse "
        f"{_across(rows, ANSWERABLE, passes, 'barrier_1')} : "
        f"{_cite(_ids(rows, ANSWERABLE, 1))}.",
        f"La barrière 2 en refuse "
        f"{_across(rows, ANSWERABLE, passes, 'barrier_2')} de plus : "
        f"{_cite(_ids(rows, ANSWERABLE, 2))}.",
        "",
        "**Un faux refus n'est pas toujours un défaut.** Le protocole (§9) signale déjà deux",
        "questions en tension avec le corpus — RAG-19 porte sur un sujet absent, RAG-20",
        "attend une fiche technique là où le terme n'existe qu'en notice. Une configuration",
        "qui les refuse n'a pas régressé : elle a raison contre le jeu.",
        "",
        "## Toutes les sources citées viennent du classement, par construction",
        "",
        "Sur un code `ok`, `answer_question` cite au moins une source, et le modèle ne rend",
        "que des **numéros** d'extraits : ceux hors bornes sont ignorés, et la citation est",
        "construite en Python depuis les métadonnées. Il n'y a donc rien à mesurer sur cette",
        "moitié d'E1 — elle est vraie par construction, pas par statistique. Le décompte",
        "ci-dessous l'atteste sans le démontrer :",
        "",
        f"- réponses servies avec au moins une source : "
        f"{sum(1 for r in rows if r['code'] == 'ok' and r['n_sources'] >= 1)} / "
        f"{sum(1 for r in rows if r['code'] == 'ok')}.",
        "",
        "## Les trois plages de score se recouvrent",
        "",
        "Le score du premier résultat, relevé par `search_docs` — donc **avant** que le seuil",
        "l'escamote — sur l'échelle du reranker :",
        "",
        "| Sous-ensemble | plage du score du 1er résultat |",
        "|---|---|",
    ]
    for kind, (low, high) in bands.items():
        lines.append(f"| `{kind}` | {low:.4f} – {high:.4f} |")
    lines += [
        "",
        "**C'est la raison d'être de la barrière 2, et il faut la lire dans ce sens.** Tant",
        "que la plage des questions couvertes et celle des hors-corpus se chevauchent, aucun",
        "réglage du seuil ne les sépare : monter le seuil pour attraper une question hors",
        "corpus refuse une question couverte au même score. Une seconde barrière qui lit le",
        "**contenu** plutôt que le score n'est donc pas une ceinture de sécurité ajoutée par",
        "prudence — c'est le seul organe qui peut trancher là où le score ne peut pas.",
        "",
        "## Ce que cette mesure ne garantit pas",
        "",
        "**La barrière 2 est un jugement de modèle.** Elle n'est pas déterministe, et le",
        "protocole (§11) refuse par ailleurs tout juge probabiliste *dans la mesure* — ici il",
        "est dans le **produit**, ce qui est différent : on mesure ce que la gateway fait, et",
        "ce qu'elle fait comporte un appel de modèle. La conséquence est qu'un chiffre de la",
        "colonne « les deux barrières » peut bouger d'une exécution à l'autre, là où celui de",
        "la barrière 1 ne bouge pas.",
        "",
    ]
    if passes < 2:
        lines += [
            "Cette exécution n'a fait **qu'une passe** : elle ne dit rien de la stabilité.",
            "Relancer avec `--passes 3` pour l'établir.",
            "",
        ]
    elif unstable:
        lines += [
            f"Sur {passes} passes, **{len(unstable)} question(s) changent de verdict** : "
            f"{_cite(unstable)}.",
            "Ce sont elles, et elles seules, qui font les plages du tableau ci-dessus. Elles",
            "sont **nommées plutôt que moyennées** : une moyenne dirait « 3,3 faux refus » et",
            "cacherait laquelle des 22 questions bouge — or c'est la seule information",
            "sur laquelle on puisse agir.",
            "",
        ]
    else:
        lines += [
            f"Sur {passes} passes, **aucune question ne change de verdict**. C'est un",
            "constat de stabilité sur ce jeu, pas une garantie de déterminisme.",
            "",
        ]
    lines += [
        "**Huit questions par sous-ensemble**, comme partout dans ce protocole (§9) : un",
        "écart d'une question vaut 12,5 points. Ces chiffres détectent une régression, ils",
        "ne mesurent pas une capacité.",
        "",
        "*Rejouer : `make mesure-refus`.*",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--passes", type=int, default=1,
        help="nombre de passes ; au-delà de 1, la stabilité de la barrière 2 est publiée",
    )
    options = parser.parse_args()

    rows = run(options.passes)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    write_report(rows, options.passes)

    out = _counts(rows, OUT_OF_CORPUS, 1)
    answerable = _counts(rows, ANSWERABLE, 1)
    print(f"écrit : {RESULTS_PATH.relative_to(REPO_ROOT)} ({len(rows)} lignes)")
    print(f"écrit : {REPORT_PATH.relative_to(REPO_ROOT)}")
    print(f"  hors corpus   refus corrects  barrière 1 "
          f"{_across(rows, OUT_OF_CORPUS, options.passes, 'barrier_1')}/{out['n']}"
          f"  ·  les deux {_across(rows, OUT_OF_CORPUS, options.passes, 'both')}/{out['n']}")
    print(f"  à cible       faux refus      barrière 1 "
          f"{_across(rows, ANSWERABLE, options.passes, 'barrier_1')}/{answerable['n']}"
          f"  ·  les deux "
          f"{_across(rows, ANSWERABLE, options.passes, 'both')}/{answerable['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
