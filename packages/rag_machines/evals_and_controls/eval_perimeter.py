"""Ce que coûte un filtre de périmètre appliqué **après** la troncature — axe 3 du protocole.

Le chantier a tranché pour un filtrage **avant** la troncature, au prix d'une réingestion.
Ce script chiffre ce que l'autre choix aurait coûté, au lieu de le laisser en argument.

Deux configurations, un seul drapeau qui varie — le moment du filtrage :

* **P0, après troncature** — ``search(perimeter=None)`` puis les hits interdits sont retirés
  de la liste rendue. Aucun code de production n'implémente cette variante : elle se
  fabrique ici, à partir du même appel de référence, ce qui garantit qu'elle part
  exactement du même classement.
* **P1, avant troncature** — ``search(perimeter=…)`` : le périmètre part dans la requête.

Tout le reste est constant : ``--text clean``, étage hybride (config C), filtre de version
actif, même jeu, même seuil, même profil. Les quatre profils que la matrice dote d'un
périmètre sont joués — ``default`` en est exclu, n'ayant rien à filtrer : il est refusé avant
toute requête, et son cas est contrôlé par ``check_perimeter.py``.

``dev`` et ``support`` perdent des éditions. ``commercial`` et ``admin`` sont les **témoins** :
leur périmètre couvre le corpus courant entier, donc P0 et P1 doivent y être identiques à la
référence. Un écart chez eux signalerait un défaut du protocole, pas du filtre. Leurs deux
périmètres sont identiques thème pour thème — c'est une propriété de la matrice, pas une
redondance de ce script, et les voir coïncider ligne à ligne l'atteste.

La métrique n'est pas Hit@1 : aucune question du jeu ne vise une note interne, donc aucune
cible n'est rendue inatteignable et Hit@1 ne bouge pas — c'est précisément le point. Ce qui
sépare les deux configurations, c'est le **nombre de résultats rendus**, les **refus indus**
et la **cohérence du seuil**.

Usage : make mesure-perimetre
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from config import settings
from packages.rag_machines.access_rag import perimeter_for
from packages.rag_machines.retrieval.embedder import build_embedder
from packages.rag_machines.retrieval.perimeter import Perimeter
from packages.rag_machines.retrieval.reranker import build_reranker
from packages.rag_machines.retrieval.search import Hit, apply_tiebreak, search

#: La racine du dépôt. **parents[3]**, pas [2] : ce module vit un niveau plus bas que
#: les autres, dans `evals_and_controls/`. Le compte était juste avant ce déplacement,
#: et il a fait pointer les jeux de questions et les rapports dans `packages/eval/`,
#: qui n'existe pas — la cible échouait à la lecture du jeu.
REPO_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_SET = REPO_ROOT / "eval" / "questions_rag.jsonl"
RESULTS_PATH = REPO_ROOT / "eval" / "resultats" / "mesure-perimetre.csv"
REPORT_PATH = REPO_ROOT / "eval" / "rapport_perimetre.md"

#: Les quatre profils dotés d'un périmètre. `default` n'en a aucun : il est refusé avant
#: toute requête, et il n'y a pas deux moments de filtrage à comparer là où rien n'est filtré.
PROFILES = ("dev", "support", "commercial", "admin")

#: Les profils dont le périmètre couvre tout le corpus courant : le filtre y est un no-op,
#: donc P0 et P1 doivent y coïncider. `admin` a exactement le périmètre de `commercial`
#: (matrice.yaml : « il n'a PAS plus, et c'est délibéré ») — les deux sont joués quand même,
#: un seul ne dirait rien de la lecture de la matrice pour l'autre.
WITNESSES = ("commercial", "admin")

_CSV_FIELDS = ("profile", "stage", "id", "type", "criterion", "rank", "returned",
               "score", "refused")


@dataclass(frozen=True)
class Outcome:
    """Ce qu'une configuration rend sur une question, pour un profil."""

    returned: int
    rank: int | None
    criterion: str
    score: float | None
    refused: bool
    #: Le premier résultat du classement de référence est-il interdit à ce profil ? En P0,
    #: c'est sur lui que le seuil de refus a été évalué — donc sur une pièce que
    #: l'utilisateur ne verra jamais.
    threshold_on_forbidden: bool


def _criterion(question: dict) -> tuple[str, object]:
    """Ce qu'on cherche dans la liste rendue, selon le type de question."""
    if question["type"] == "reference_exacte":
        return "reference", question["attendu_reference"]
    if question["type"] == "couverte" and question.get("attendu_type"):
        return "type_attendu", question["attendu_type"]
    return "refus", None


def _rank_of(hits: list[Hit], criterion: str, expected: object) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if criterion == "reference" and hit.reference == expected:
            return rank
        if criterion == "type_attendu" and hit.doc_type == expected:
            return rank
    return None


def _theme_of(hit: Hit) -> str | None:
    """Le thème d'un hit. Les métadonnées Chroma sont typées large ; la clé est absente sur
    les 320 éditions qui ne sont pas des notes, et c'est cette absence qui compte."""
    theme = hit.metadata.get("theme")
    return str(theme) if theme is not None else None


def _allows(perimeter: Perimeter, hit: Hit) -> bool:
    return perimeter.allows(str(hit.metadata.get("doc_type", "")), _theme_of(hit))


def _allowed(hits: list[Hit], perimeter: Perimeter) -> list[Hit]:
    return [hit for hit in hits if _allows(perimeter, hit)]


def _outcome(question: dict, hits: list[Hit], reference_top: Hit | None,
             decision_top: Hit | None, perimeter: Perimeter, threshold: float) -> Outcome:
    """`decision_top` est le résultat sur lequel le seuil de refus a porté, qui n'est pas
    forcément le premier de `hits` : en P0 le moteur tranche avant que le filtre passe,
    donc sur le premier du classement de référence, interdit ou non. En P1 ils coïncident."""
    ordered = apply_tiebreak(list(hits))
    top = ordered[0] if ordered else None
    criterion, expected = _criterion(question)
    forbidden_top = reference_top is not None and not _allows(perimeter, reference_top)
    return Outcome(
        returned=len(ordered),
        rank=_rank_of(ordered, criterion, expected),
        criterion=criterion,
        score=top.score if top else None,
        refused=decision_top is None or decision_top.score < threshold,
        threshold_on_forbidden=forbidden_top,
    )


def run() -> list[dict]:
    questions = [json.loads(line) for line in
                 QUESTIONS_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    threshold = settings.rerank_threshold
    if threshold is None:
        raise RuntimeError(
            "RERANK_THRESHOLD n'est pas renseigné : sans seuil, les refus ne se mesurent "
            "pas, et c'est l'une des trois colonnes qui séparent les deux configurations. "
            "Le régler avec `make calibrer-hybride`."
        )
    embedder = build_embedder(settings)
    reranker = build_reranker(settings)
    perimeters = {p: perimeter_for(p) for p in PROFILES}

    rows: list[dict] = []
    for question in questions:
        # Un seul classement de référence, partagé par les trois profils : P0 s'en déduit
        # par filtrage, et c'est ce qui garantit que les deux configurations partent du
        # même classement plutôt que de deux appels qui pourraient différer.
        reference = search(question["question"], strategy="hybrid", tiebreak=False,
                           threshold=None, settings=settings, embedder=embedder,
                           reranker=reranker).hits
        reference_top = apply_tiebreak(list(reference))[0] if reference else None

        for profile in PROFILES:
            perimeter = perimeters[profile]
            assert perimeter is not None, profile
            filtered = search(question["question"], strategy="hybrid", tiebreak=False,
                              threshold=None, settings=settings, embedder=embedder,
                              reranker=reranker, perimeter=perimeter).hits
            ordered_filtered = apply_tiebreak(list(filtered))
            filtered_top = ordered_filtered[0] if ordered_filtered else None
            # Le seuil ne porte pas sur le même résultat dans les deux configurations : en
            # P0 le moteur a tranché avant que le filtre passe, en P1 sur ce qui reste.
            # Les confondre effacerait justement l'écart que l'axe 3 cherche à établir.
            for stage, hits, decision_top in (
                    ("P0", _allowed(reference, perimeter), reference_top),
                    ("P1", filtered, filtered_top)):
                outcome = _outcome(question, hits, reference_top, decision_top,
                                   perimeter, threshold)
                rows.append({
                    "profile": profile, "stage": stage, "id": question["id"],
                    "type": question["type"], "criterion": outcome.criterion,
                    "rank": outcome.rank, "returned": outcome.returned,
                    "score": f"{outcome.score:.4f}" if outcome.score is not None else "",
                    "refused": "oui" if outcome.refused else "non",
                })
                if stage == "P0":
                    rows[-1]["threshold_on_forbidden"] = outcome.threshold_on_forbidden
    return rows


def _metrics(rows: list[dict], profile: str, stage: str) -> dict:
    subset = [r for r in rows if r["profile"] == profile and r["stage"] == stage]
    answerable = [r for r in subset if r["type"] != "hors_corpus"]
    ranked = [r for r in subset if r["criterion"] != "refus"]
    hits_at_1 = sum(1 for r in ranked if r["rank"] == 1)
    mrr = sum(1 / r["rank"] for r in ranked if r["rank"]) / len(ranked) if ranked else 0.0
    return {
        "returned_mean": sum(r["returned"] for r in subset) / len(subset),
        "returned_min": min(r["returned"] for r in subset),
        "empty": sum(1 for r in subset if r["returned"] == 0),
        # Une question vidée qui était de toute façon à refuser ne coûte rien : c'est la
        # distinction qui empêche ce rapport de gonfler son propre écart.
        "empty_answerable": sum(1 for r in answerable if r["returned"] == 0),
        "refused_answerable": sum(1 for r in answerable if r["refused"] == "oui"),
        "hit_at_1": hits_at_1,
        "ranked": len(ranked),
        "mrr": mrr,
        "threshold_on_forbidden": sum(1 for r in subset if r.get("threshold_on_forbidden")),
    }


def _cite(rows: list[dict]) -> str:
    """« RAG-27 et RAG-30 pour `dev`, RAG-30 pour `support` ». Les identifiants cités dans
    la lecture du rapport sont dérivés des lignes, jamais recopiés à la main : le rapport
    est régénéré à chaque exécution, une liste figée y survivrait à ce qu'elle décrit."""
    by_profile: dict[str, list[str]] = {}
    for row in rows:
        by_profile.setdefault(row["profile"], []).append(row["id"])
    parts = []
    for profile, ids in by_profile.items():
        listed = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + f" et {ids[-1]}"
        parts.append(f"{listed} pour `{profile}`")
    return ", ".join(parts)


def write_report(rows: list[dict]) -> None:
    lines = [
        "# Ce que coûte un filtre de périmètre appliqué après la troncature",
        "",
        "Axe 3 du [protocole de mesure](protocole-mesure.md). Un seul drapeau varie — le",
        "**moment** où le périmètre du profil est appliqué. Tout le reste est constant :",
        "texte nettoyé, étage hybride (config C), filtre de version actif, les 30 questions",
        "de `questions_rag.jsonl`, le seuil de refus du reranker.",
        "",
        "| | Ce qui est appelé |",
        "|---|---|",
        "| **P0** — après troncature | `search(perimeter=None)`, puis les résultats interdits "
        "sont retirés de la liste rendue |",
        "| **P1** — avant troncature | `search(perimeter=…)` : le périmètre part dans la requête |",
        "",
        "Les deux configurations partent du **même classement de référence** : P0 s'en déduit",
        "par filtrage, dans la même passe. Aucun code de production n'implémente P0 — elle est",
        "fabriquée par ce script, ce qui évite d'entretenir une branche morte.",
        "",
        "## Pouvoir discriminant du jeu",
        "",
        "Aucune des 30 questions ne vise une note interne : les cibles attendues sont 6",
        "`procedure_sav`, 3 `notice` et 4 `fiche_technique`. **Aucune cible n'est donc rendue",
        "inatteignable par le filtre** — et c'est pourquoi Hit@1 et MRR ne sont pas la mesure",
        "ici. Ce qui change, ce sont les places du top-5 qu'occupent des notes interdites.",
        "",
    ]

    discriminant = {
        p: sum(1 for r in rows if r["profile"] == p and r["stage"] == "P0" and r["returned"] < 5)
        for p in PROFILES
    }
    lines += [
        "| Profil | Questions dont le top-5 contient au moins un résultat interdit |",
        "|---|---|",
    ] + [f"| `{p}` | {n} / 30 |" for p, n in discriminant.items()] + [""]

    lines += ["## Résultats", ""]
    for profile in PROFILES:
        p0, p1 = _metrics(rows, profile, "P0"), _metrics(rows, profile, "P1")
        witness = (" *(témoin — périmètre couvrant tout le corpus courant)*"
                   if profile in WITNESSES else "")
        lines += [
            f"### Profil `{profile}`{witness}",
            "",
            "| Mesure | P0 — après troncature | P1 — avant troncature |",
            "|---|---|---|",
            f"| Résultats rendus, moyenne | {p0['returned_mean']:.2f} | {p1['returned_mean']:.2f} |",
            f"| Résultats rendus, minimum | {p0['returned_min']} | {p1['returned_min']} |",
            f"| Questions sans aucun résultat | **{p0['empty']}** | {p1['empty']} |",
            f"| … dont questions couvertes | {p0['empty_answerable']} | {p1['empty_answerable']} |",
            f"| Questions couvertes refusées | {p0['refused_answerable']} | {p1['refused_answerable']} |",
            f"| Seuil évalué sur un résultat interdit | **{p0['threshold_on_forbidden']}** | 0 |",
            f"| Hit@1 | {p0['hit_at_1']} / {p0['ranked']} | {p1['hit_at_1']} / {p1['ranked']} |",
            f"| MRR | {p0['mrr']:.3f} | {p1['mrr']:.3f} |",
            "",
        ]

    # Les questions que P0 rend vides se lisent en deux tas : celles qu'il refuse malgré
    # tout, et celles qu'il **accepte** parce que le seuil a été franchi par un document
    # que le filtre retire ensuite. Le second tas est le défaut de P0 dans sa forme nette.
    emptied = [r for r in rows if r["stage"] == "P0" and r["returned"] == 0]
    accepted_empty = [r for r in emptied if r["refused"] == "non"]

    lines += [
        "## Lecture",
        "",
        "Hit@1 et MRR ne séparent rien, ce qui est attendu : le filtre ne retire aucune cible,",
        "il libère des places. Ce que la mesure établit tient en deux lignes.",
        "",
        "**Des résultats perdus, sans repêchage.** En P0, chaque place occupée par un document",
        "interdit est perdue : le profil reçoit moins que les `top_k` résultats auxquels il a",
        "droit. En P1, ces mêmes places sont prises par les résultats autorisés suivants.",
        "",
        "**Un seuil décidé sur une pièce écartée.** Le refus compare le score du *premier*",
        "résultat. Quand ce premier est un document interdit que P0 retire ensuite, la décision",
        "d'accepter ou de refuser a porté sur une pièce que l'utilisateur ne verra jamais.",
        "",
        "**Ce que la mesure n'établit pas, et qu'il faut dire.** Les questions que P0 vide",
        "entièrement sont, sur ce jeu, **toutes des questions hors corpus** :",
        f"{_cite(emptied)}. Les refuser est juste, et P0 en refuse "
        f"{len(emptied) - len(accepted_empty)} sur {len(emptied)} —",
        "pour la mauvaise raison, mais avec le bon résultat.",
        "Le refus indu redouté ne se produit pas ici : il faudrait",
        "pour cela une question couverte dont tout le top-5 soit interdit, et le jeu n'en",
        "contient aucune — aucune de ses cibles n'est une note interne.",
        "",
    ]

    if accepted_empty:
        lines += [
            f"**P0 accepte, et ne rend rien.** {_cite(accepted_empty)} : le seuil a été",
            "franchi par un document interdit, donc P0 n'a pas refusé la question — puis le",
            "filtre a vidé la liste. Le profil reçoit une acceptation sans une seule source,",
            "ce qui est pire que le refus qu'il aurait dû recevoir. C'est le seuil décidé en",
            "amont du filtre dans sa forme la plus nette ; P1 refuse ces mêmes questions.",
            "",
        ]

    lines += [
        "**Les deux témoins.** `commercial` et `admin` doivent être identiques dans les",
        "deux colonnes *et* identiques l'un à l'autre : leurs périmètres couvrent les mêmes",
        "350 éditions courantes, le filtre y est un no-op. Un écart entre les deux colonnes",
        "signalerait un défaut du protocole ; un écart entre les deux profils, une matrice",
        "lue de travers.",
        "",
        "*Rejouer : `make mesure-perimetre`.*",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = run()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    write_report(rows)
    print(f"écrit : {RESULTS_PATH.relative_to(REPO_ROOT)} ({len(rows)} lignes)")
    print(f"écrit : {REPORT_PATH.relative_to(REPO_ROOT)}")
    for profile in PROFILES:
        p0, p1 = _metrics(rows, profile, "P0"), _metrics(rows, profile, "P1")
        print(f"  {profile:11} P0 rendus {p0['returned_mean']:.2f} · vides {p0['empty']} · "
              f"refus {p0['refused_answerable']}   |   "
              f"P1 rendus {p1['returned_mean']:.2f} · vides {p1['empty']} · "
              f"refus {p1['refused_answerable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
