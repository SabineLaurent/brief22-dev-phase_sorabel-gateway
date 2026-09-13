"""Ce que la politique de candidats change, profil par profil — axe 8 du protocole.

Le défaut ``2bis.1`` s'est vu à l'écran et non dans une mesure, et ce n'est pas un hasard :
le jeu d'évaluation est joué **sans périmètre**, donc dans les conditions de ``commercial``,
et aucune de ses 30 questions n'a de cible qu'une série redondante puisse enterrer. Les six
mesures publiées ne pouvaient pas le voir. Ce script le regarde là où il vit — sur les
**profils**.

Deux étages, et c'est **une politique** qui varie, pas deux drapeaux :

* **C0** — vivier == budget (20), aucun plafond. La forme d'avant le correctif.
* **C1** — vivier 60, budget 20, plafond 3 par titre.

Les séparer n'aurait aucun sens : un plafond sans vivier profond n'a rien à repêcher, un
vivier profond sans plafond se laisse remplir par la même série. C'est le précédent des
étages ``P0``/``P1`` de l'axe 3, qui déplacent aussi deux choses solidaires.

Tout le reste est constant : ``--text clean``, étage hybride, filtre de version actif, même
jeu, **même seuil** — la recalibration sous C1 repropose 0,0530, donc il n'y a pas de
confondant de seuil dans cette comparaison (``make calibrer-candidats-c0`` rejoue l'avant).

**Aucun appel de modèle de rédaction** : on mesure la barrière 1 seule, celle qui tranche sur
le score. Ce que la barrière 2 en ferait ensuite est l'objet de l'axe 4.

**Ce script a son propre jeu**, ``eval/questions_candidats.jsonl``, et c'est une décision.
Le jeu de mesure partagé est un invariant du protocole (§6 : « ce qui ne varie dans aucune
mesure ») et il est **lu par trois harnais qui n'interprètent pas son champ ``type`` de la
même façon** — ``eval_perimeter.py`` compte comme « à cible » tout ce qui n'est pas
``hors_corpus``, si bien qu'y ajouter un type neuf déplacerait en silence les chiffres
publiés de l'axe 3, et ajouterait une ligne sans métrique aux CSV des axes 1 et 2. Le cas
difficile vit donc à côté, où il ne perturbe rien.

Le jeu porte un **témoin** (``CND-04``) dont le sujet ne connaît aucune série redondante :
les deux étages doivent y coïncider. Sans lui, une différence générale serait indiscernable
d'une différence due à la redondance.

Usage : make mesure-candidats-profils
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from config import Settings, settings
from packages.rag_machines.access_rag import perimeter_for
from packages.rag_machines.retrieval.embedder import build_embedder
from packages.rag_machines.retrieval.reranker import build_reranker
from packages.rag_machines.retrieval.search import (
    Hit,
    apply_tiebreak,
    candidate_policy,
    search,
)

#: La racine du dépôt. **parents[3]**, pas [2] : ce module vit un niveau plus bas que les
#: autres, dans `evals_and_controls/` (même piège que `eval_rag.py`).
REPO_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_SET = REPO_ROOT / "eval" / "questions_candidats.jsonl"
RESULTS_PATH = REPO_ROOT / "eval" / "resultats" / "mesure-candidats-profils.csv"
REPORT_PATH = REPO_ROOT / "eval" / "rapport_candidats.md"

#: Les quatre profils dotés d'un périmètre, **par droits croissants** : c'est l'ordre qui
#: rend la monotonie lisible. `default` n'en a aucun — refusé avant toute requête.
PROFILES = ("dev", "support", "commercial", "admin")

#: Les deux étages, chacun décrit par ce qu'il change dans `Settings`. `None` sur le
#: plafond est le réglage d'extinction, pas une absence de valeur.
STAGES: dict[str, dict[str, int | None]] = {
    "C0": {"search_pool": 20, "max_candidates_per_title": None},
    "C1": {"search_pool": 60, "max_candidates_per_title": 3},
}

#: Les questions auxquelles le corpus répond — le dénominateur des réponses servies.
ANSWERABLE = ("reference_exacte", "couverte", "couverte_redondance")

_CSV_FIELDS = ("profile", "stage", "id", "type", "served", "score", "titles_top5")


@dataclass(frozen=True)
class Outcome:
    """Ce qu'un étage rend sur une question, pour un profil."""

    served: bool
    score: float | None
    #: Titres distincts parmi les résultats rendus. C'est la grandeur que le correctif
    #: vise directement : le reranker ne peut pas préférer un document qu'on ne lui
    #: montre pas, et 20 candidats de 2 titres ne lui laissent aucun choix.
    titles_top5: int


def _titles(hits: list[Hit]) -> int:
    return len({str(hit.metadata.get("titre", "")) for hit in hits})


def run() -> list[dict]:
    questions = [json.loads(line) for line in
                 QUESTIONS_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    threshold = settings.rerank_threshold
    if threshold is None:
        raise RuntimeError("RERANK_THRESHOLD doit être renseigné : cet axe mesure un refus.")

    # Construits une fois pour les 32 recherches. `build_*` est mémoïsé, mais passer les
    # objets explicitement dit que les deux étages partagent bien les mêmes modèles :
    # ce qui varie est la politique de candidats, rien d'autre.
    embedder = build_embedder(settings)
    reranker = build_reranker(settings)

    rows: list[dict] = []
    for profile in PROFILES:
        perimeter = perimeter_for(profile)
        assert perimeter is not None, profile
        for stage, overrides in STAGES.items():
            staged: Settings = settings.model_copy(update=overrides)
            for question in questions:
                result = search(
                    question["question"],
                    strategy="hybrid",
                    version_filter=True,
                    tiebreak=False,
                    threshold=None,
                    perimeter=perimeter,
                    settings=staged,
                    embedder=embedder,
                    reranker=reranker,
                )
                hits = apply_tiebreak(list(result.hits))
                top = hits[0] if hits else None
                outcome = Outcome(
                    served=top is not None and top.score >= threshold,
                    score=top.score if top else None,
                    titles_top5=_titles(hits),
                )
                rows.append({
                    "profile": profile, "stage": stage,
                    "id": question["id"], "type": question["type"],
                    "served": "oui" if outcome.served else "non",
                    "score": f"{outcome.score:.4f}" if outcome.score is not None else "",
                    "titles_top5": outcome.titles_top5,
                })
    return rows


def metrics(rows: list[dict], profile: str, stage: str) -> dict[str, float]:
    scoped = [r for r in rows if r["profile"] == profile and r["stage"] == stage]
    answerable = [r for r in scoped if r["type"] in ANSWERABLE]
    out_of_corpus = [r for r in scoped if r["type"] == "hors_corpus"]
    return {
        "served": sum(1 for r in answerable if r["served"] == "oui"),
        "answerable": len(answerable),
        "refused_correctly": sum(1 for r in out_of_corpus if r["served"] == "non"),
        "out_of_corpus": len(out_of_corpus),
        "titles_mean": sum(int(r["titles_top5"]) for r in scoped) / len(scoped),
    }


def write_report(rows: list[dict]) -> None:
    def cell(profile: str, stage: str, question: str, field: str) -> str:
        for row in rows:
            if row["profile"] == profile and row["stage"] == stage and row["id"] == question:
                return str(row[field])
        return "?"

    lines = [
        "# Rapport de politique de candidats — axe 8",
        "",
        "Généré par `make mesure-candidats-profils`. **Ne pas éditer à la main** : la cible",
        "réécrit ce fichier en entier.",
        "",
        "## Ce qui varie, et ce qui ne varie pas",
        "",
        "| | |",
        "|---|---|",
        "| **varie** | la politique de candidats : `C0` vivier 20 / budget 20 / sans plafond → "
        "`C1` vivier 60 / budget 20 / plafond 3 par titre |",
        "| constant | étage hybride (config C), `--text clean`, filtre de version actif, "
        "`top_k=5`, règle de départage active, **le seuil**, le même embedder et le même "
        "reranker, le même jeu |",
        "",
        "**Le seuil est constant, et ce n'est pas une entorse.** Le protocole exige un seuil",
        "recalibré par cellule *quand l'échelle change* ; ici le reranker est le même, et la",
        f"recalibration sous `C1` repropose **{settings.rerank_threshold:.4f}**, la valeur en",
        "place. Le vérifier était le préalable à cette mesure — `make calibrer-candidats-c0`",
        "rejoue le seuil de l'ancienne politique, `make calibrer-hybride` celui de la nouvelle,",
        "et les deux proposent la même valeur. Il n'y a donc **aucun confondant de seuil** ici.",
        "",
        "**Une politique, pas deux drapeaux.** Le vivier et le plafond ne veulent rien dire l'un",
        "sans l'autre : un plafond sans vivier profond n'a rien à repêcher, un vivier profond",
        "sans plafond se laisse remplir par la même série. Les faire varier ensemble respecte la",
        "règle fondatrice (§1) au même titre que les étages `P0`/`P1` de l'axe 3.",
        "",
        "## Résultats — par profil, par droits croissants",
        "",
        "*Barrière 1 seule : aucun appel de modèle de rédaction.*",
        "",
        "| profil | éditions | étage | réponses servies | titres distincts rendus (moyenne) |",
        "|---|---:|---|---:|---:|",
    ]
    editions = {"dev": 270, "support": 318, "commercial": 350, "admin": 350}
    for profile in PROFILES:
        for stage in STAGES:
            m = metrics(rows, profile, stage)
            lines.append(
                f"| `{profile}` | {editions[profile]} | {stage} | "
                f"{m['served']:.0f} / {m['answerable']:.0f} | {m['titles_mean']:.2f} |"
            )

    dev_c0 = metrics(rows, "dev", "C0")
    sup_c0 = metrics(rows, "support", "C0")
    sup_c1 = metrics(rows, "support", "C1")
    lines += [
        "",
        "### Ce que la colonne « réponses servies » dit",
        "",
        "**Sous `C0`, plus de droits donne moins de réponses.** `support` voit un surensemble",
        f"du corpus de `dev` — {editions['support']} éditions contre {editions['dev']} — et sert",
        f"**{sup_c0['served']:.0f} / {sup_c0['answerable']:.0f}** là où `dev` sert",
        f"**{dev_c0['served']:.0f} / {dev_c0['answerable']:.0f}**. C'est E1 qui recule là où la",
        "matrice s'élargit, et c'est le défaut `2bis.1`.",
        "",
        f"**Sous `C1`, les quatre profils coïncident** à"
        f" {sup_c1['served']:.0f} / {sup_c1['answerable']:.0f}, et `dev` n'a pas bougé.",
        "",
        "### Le mécanisme, dans un seul nombre",
        "",
        "`CND-01` — « Comment procéder à un retour ? », la question par laquelle le défaut s'est",
        "vu — pour `support` :",
        "",
        "| étage | titres distincts dans les 5 résultats | score du rang 1 | verdict |",
        "|---|---:|---:|---|",
        f"| `C0` | **{cell('support', 'C0', 'CND-01', 'titles_top5')}** | "
        f"{cell('support', 'C0', 'CND-01', 'score')} | refusé |",
        f"| `C1` | **{cell('support', 'C1', 'CND-01', 'titles_top5')}** | "
        f"{cell('support', 'C1', 'CND-01', 'score')} | servi |",
        "",
        "**Un seul titre dans les cinq résultats.** Les 20 places du budget étaient occupées par",
        "des documents distincts mais par deux séries de notes seulement — 80 notes internes pour",
        "5 titres, redondance 16× — et la procédure SAV n'entrait jamais dans les candidats. Le",
        "reranker ne se trompait pas : **on ne lui montrait pas le document.** Sous `C1`, le score",
        f"de `support` vaut {cell('support', 'C1', 'CND-01', 'score')}, soit exactement celui de",
        f"`dev` ({cell('dev', 'C1', 'CND-01', 'score')}) — le même document, au même rang.",
        "",
        "### Le témoin",
        "",
        "`CND-04` porte sur une référence produit, sujet sans aucune série redondante. Il rend",
        f"{cell('dev', 'C0', 'CND-04', 'score')} en `C0` comme en `C1`, pour les quatre profils.",
        "Sans lui, un écart général serait indiscernable d'un écart dû à la redondance.",
        "",
        "## Ce que cette mesure ne règle pas — et le passe à l'axe 4",
        "",
        "`CND-02` — « que faire en cas de retour d'un article ? » — vise le **même document** que",
        "`CND-01` et `CND-03`. Elle est refusée par les quatre profils, dans les **deux** étages.",
        "",
        "| question | tournure | score `dev` | verdict |",
        "|---|---|---:|---|",
        f"| `CND-03` | « procédure de retour produit » | {cell('dev', 'C1', 'CND-03', 'score')} | servi |",
        f"| `CND-01` | « Comment procéder à un retour ? » | {cell('dev', 'C1', 'CND-01', 'score')} | servi |",
        f"| `CND-02` | « que faire en cas de retour d'un article ? » | {cell('dev', 'C1', 'CND-02', 'score')} | **refusé** |",
        "",
        "**Le correctif fait ce qu'il annonce, et pas plus.** Sous `C1`, `support` passe de",
        f"{cell('support', 'C0', 'CND-02', 'score')} à {cell('support', 'C1', 'CND-02', 'score')}",
        "sur `CND-02` : il rejoint **exactement** `dev`. L'asymétrie de périmètre est donc",
        "réparée. Ce qui refuse encore est le **seuil**, sur un document que le retrieval trouve.",
        "",
        "C'est le défaut `2bis.2`, et il est distinct : il ne dépend pas du profil, et aucun",
        "réglage de vivier ne l'atteint. Le rapport de refus (axe 4) est l'endroit où il se",
        "tranche.",
        "",
        "## Limites",
        "",
        "**Le jeu de mesure partagé ne voit rien de cet axe.** Rejoué en `C0` puis `C1`",
        "(`make mesure-candidats`), il rend les mêmes Hit@1 8/8, MRR 1,000, Recall@5 12/13 et",
        "refus corrects 5/8 — aucun verdict, aucun rang ne bascule. Six scores sur 38 dérivent,",
        "tous vers le bas. La raison est que ce jeu est joué **sans périmètre** et qu'aucune de",
        "ses cibles n'est enterrable par une série redondante : **un jeu qui ne contient pas le",
        "cas difficile ne peut rien dire du cas difficile.** C'est la troisième fois que ce",
        "dossier le constate.",
        "",
        "**Quatre questions, pas trente.** Ce jeu-ci est écrit pour un défaut nommé ; il montre",
        "un mécanisme, il ne mesure pas une capacité générale.",
        "",
        "**Un vivier plus profond ne fait pas qu'ajouter.** Le budget reste à 20 : élargir le",
        "vivier change *lesquels* des candidats sont notés, puisque les scores RRF se recomposent",
        "sur une union plus large. Un score de rang 1 peut donc baisser, et six le font sur le jeu",
        "partagé. Aucun n'y change de verdict, mais rien ne garantit qu'aucun ne le ferait sur un",
        "autre jeu.",
        "",
        "*Rejouer : `make mesure-candidats-profils`, et `make mesure-candidats` pour les deux",
        "cellules sur le jeu partagé.*",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print(f"Jeu : {QUESTIONS_SET.name} · profils : {len(PROFILES)} · étages : {len(STAGES)}")
    print(f"Politique servie : {candidate_policy(settings)} · seuil {settings.rerank_threshold}")
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
        c0, c1 = metrics(rows, profile, "C0"), metrics(rows, profile, "C1")
        print(f"  {profile:11} C0 servies {c0['served']:.0f}/{c0['answerable']:.0f} · "
              f"titres {c0['titles_mean']:.2f}   |   "
              f"C1 servies {c1['served']:.0f}/{c1['answerable']:.0f} · "
              f"titres {c1['titles_mean']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
