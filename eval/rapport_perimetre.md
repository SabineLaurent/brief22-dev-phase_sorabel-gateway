# Ce que coûte un filtre de périmètre appliqué après la troncature

Axe 3 du [protocole de mesure](protocole-mesure.md). Un seul drapeau varie — le
**moment** où le périmètre du profil est appliqué. Tout le reste est constant :
texte nettoyé, étage hybride (config C), filtre de version actif, les 30 questions
de `questions_rag.jsonl`, le seuil de refus du reranker.

| | Ce qui est appelé |
|---|---|
| **P0** — après troncature | `search(perimeter=None)`, puis les résultats interdits sont retirés de la liste rendue |
| **P1** — avant troncature | `search(perimeter=…)` : le périmètre part dans la requête |

Les deux configurations partent du **même classement de référence** : P0 s'en déduit
par filtrage, dans la même passe. Aucun code de production n'implémente P0 — elle est
fabriquée par ce script, ce qui évite d'entretenir une branche morte.

## Pouvoir discriminant du jeu

Aucune des 30 questions ne vise une note interne : les cibles attendues sont 6
`procedure_sav`, 3 `notice` et 4 `fiche_technique`. **Aucune cible n'est donc rendue
inatteignable par le filtre** — et c'est pourquoi Hit@1 et MRR ne sont pas la mesure
ici. Ce qui change, ce sont les places du top-5 qu'occupent des notes interdites.

| Profil | Questions dont le top-5 contient au moins un résultat interdit |
|---|---|
| `dev` | 9 / 30 |
| `support` | 3 / 30 |
| `commercial` | 0 / 30 |
| `admin` | 0 / 30 |

## Résultats

### Profil `dev`

| Mesure | P0 — après troncature | P1 — avant troncature |
|---|---|---|
| Résultats rendus, moyenne | 4.33 | 5.00 |
| Résultats rendus, minimum | 0 | 5 |
| Questions sans aucun résultat | **2** | 0 |
| … dont questions couvertes | 0 | 0 |
| Questions couvertes refusées | 1 | 1 |
| Seuil évalué sur un résultat interdit | **4** | 0 |
| Hit@1 | 20 / 21 | 20 / 21 |
| MRR | 0.952 | 0.952 |

### Profil `support`

| Mesure | P0 — après troncature | P1 — avant troncature |
|---|---|---|
| Résultats rendus, moyenne | 4.83 | 5.00 |
| Résultats rendus, minimum | 2 | 5 |
| Questions sans aucun résultat | **0** | 0 |
| … dont questions couvertes | 0 | 0 |
| Questions couvertes refusées | 1 | 1 |
| Seuil évalué sur un résultat interdit | **1** | 0 |
| Hit@1 | 20 / 21 | 20 / 21 |
| MRR | 0.952 | 0.952 |

### Profil `commercial` *(témoin — périmètre couvrant tout le corpus courant)*

| Mesure | P0 — après troncature | P1 — avant troncature |
|---|---|---|
| Résultats rendus, moyenne | 5.00 | 5.00 |
| Résultats rendus, minimum | 5 | 5 |
| Questions sans aucun résultat | **0** | 0 |
| … dont questions couvertes | 0 | 0 |
| Questions couvertes refusées | 1 | 1 |
| Seuil évalué sur un résultat interdit | **0** | 0 |
| Hit@1 | 20 / 21 | 20 / 21 |
| MRR | 0.952 | 0.952 |

### Profil `admin` *(témoin — périmètre couvrant tout le corpus courant)*

| Mesure | P0 — après troncature | P1 — avant troncature |
|---|---|---|
| Résultats rendus, moyenne | 5.00 | 5.00 |
| Résultats rendus, minimum | 5 | 5 |
| Questions sans aucun résultat | **0** | 0 |
| … dont questions couvertes | 0 | 0 |
| Questions couvertes refusées | 1 | 1 |
| Seuil évalué sur un résultat interdit | **0** | 0 |
| Hit@1 | 20 / 21 | 20 / 21 |
| MRR | 0.952 | 0.952 |

## Lecture

Hit@1 et MRR ne séparent rien, ce qui est attendu : le filtre ne retire aucune cible,
il libère des places. Ce que la mesure établit tient en deux lignes.

**Des résultats perdus, sans repêchage.** En P0, chaque place occupée par un document
interdit est perdue : le profil reçoit moins que les `top_k` résultats auxquels il a
droit. En P1, ces mêmes places sont prises par les résultats autorisés suivants.

**Un seuil décidé sur une pièce écartée.** Le refus compare le score du *premier*
résultat. Quand ce premier est un document interdit que P0 retire ensuite, la décision
d'accepter ou de refuser a porté sur une pièce que l'utilisateur ne verra jamais.

**Ce que la mesure n'établit pas, et qu'il faut dire.** Les questions que P0 vide
entièrement sont, sur ce jeu, **toutes des questions hors corpus** :
RAG-29 et RAG-30 pour `dev`. Les refuser est juste, et P0 en refuse 1 sur 2 —
pour la mauvaise raison, mais avec le bon résultat.
Le refus indu redouté ne se produit pas ici : il faudrait
pour cela une question couverte dont tout le top-5 soit interdit, et le jeu n'en
contient aucune — aucune de ses cibles n'est une note interne.

**P0 accepte, et ne rend rien.** RAG-29 pour `dev` : le seuil a été
franchi par un document interdit, donc P0 n'a pas refusé la question — puis le
filtre a vidé la liste. Le profil reçoit une acceptation sans une seule source,
ce qui est pire que le refus qu'il aurait dû recevoir. C'est le seuil décidé en
amont du filtre dans sa forme la plus nette ; P1 refuse ces mêmes questions.

**Les deux témoins.** `commercial` et `admin` doivent être identiques dans les
deux colonnes *et* identiques l'un à l'autre : leurs périmètres couvrent les mêmes
350 éditions courantes, le filtre y est un no-op. Un écart entre les deux colonnes
signalerait un défaut du protocole ; un écart entre les deux profils, une matrice
lue de travers.

*Rejouer : `make mesure-perimetre`.*
