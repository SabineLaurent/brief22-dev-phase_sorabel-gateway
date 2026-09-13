# Rapport de politique de candidats — axe 8

Généré par `make mesure-candidats-profils`. **Ne pas éditer à la main** : la cible
réécrit ce fichier en entier.

## Ce qui varie, et ce qui ne varie pas

| | |
|---|---|
| **varie** | la politique de candidats : `C0` vivier 20 / budget 20 / sans plafond → `C1` vivier 60 / budget 20 / plafond 3 par titre |
| constant | étage hybride (config C), `--text clean`, filtre de version actif, `top_k=5`, règle de départage active, **le seuil**, le même embedder et le même reranker, le même jeu |

**Le seuil est constant, et ce n'est pas une entorse.** Le protocole exige un seuil
recalibré par cellule *quand l'échelle change* ; ici le reranker est le même, et la
recalibration sous `C1` repropose **0.0530**, la valeur en
place. Le vérifier était le préalable à cette mesure — `make calibrer-candidats-c0`
rejoue le seuil de l'ancienne politique, `make calibrer-hybride` celui de la nouvelle,
et les deux proposent la même valeur. Il n'y a donc **aucun confondant de seuil** ici.

**Une politique, pas deux drapeaux.** Le vivier et le plafond ne veulent rien dire l'un
sans l'autre : un plafond sans vivier profond n'a rien à repêcher, un vivier profond
sans plafond se laisse remplir par la même série. Les faire varier ensemble respecte la
règle fondatrice (§1) au même titre que les étages `P0`/`P1` de l'axe 3.

## Résultats — par profil, par droits croissants

*Barrière 1 seule : aucun appel de modèle de rédaction.*

| profil | éditions | étage | réponses servies | titres distincts rendus (moyenne) |
|---|---:|---|---:|---:|
| `dev` | 270 | C0 | 3 / 4 | 4.50 |
| `dev` | 270 | C1 | 3 / 4 | 4.50 |
| `support` | 318 | C0 | 2 / 4 | 3.50 |
| `support` | 318 | C1 | 3 / 4 | 4.50 |
| `commercial` | 350 | C0 | 2 / 4 | 3.50 |
| `commercial` | 350 | C1 | 3 / 4 | 4.75 |
| `admin` | 350 | C0 | 2 / 4 | 3.50 |
| `admin` | 350 | C1 | 3 / 4 | 4.75 |

### Ce que la colonne « réponses servies » dit

**Sous `C0`, plus de droits donne moins de réponses.** `support` voit un surensemble
du corpus de `dev` — 318 éditions contre 270 — et sert
**2 / 4** là où `dev` sert
**3 / 4**. C'est E1 qui recule là où la
matrice s'élargit, et c'est le défaut `2bis.1`.

**Sous `C1`, les quatre profils coïncident** à 3 / 4, et `dev` n'a pas bougé.

### Le mécanisme, dans un seul nombre

`CND-01` — « Comment procéder à un retour ? », la question par laquelle le défaut s'est
vu — pour `support` :

| étage | titres distincts dans les 5 résultats | score du rang 1 | verdict |
|---|---:|---:|---|
| `C0` | **1** | 0.0050 | refusé |
| `C1` | **5** | 0.0859 | servi |

**Un seul titre dans les cinq résultats.** Les 20 places du budget étaient occupées par
des documents distincts mais par deux séries de notes seulement — 80 notes internes pour
5 titres, redondance 16× — et la procédure SAV n'entrait jamais dans les candidats. Le
reranker ne se trompait pas : **on ne lui montrait pas le document.** Sous `C1`, le score
de `support` vaut 0.0859, soit exactement celui de
`dev` (0.0859) — le même document, au même rang.

### Le témoin

`CND-04` porte sur une référence produit, sujet sans aucune série redondante. Il rend
0.9997 en `C0` comme en `C1`, pour les quatre profils.
Sans lui, un écart général serait indiscernable d'un écart dû à la redondance.

## Ce que cette mesure ne règle pas — et le passe à l'axe 4

`CND-02` — « que faire en cas de retour d'un article ? » — vise le **même document** que
`CND-01` et `CND-03`. Elle est refusée par les quatre profils, dans les **deux** étages.

| question | tournure | score `dev` | verdict |
|---|---|---:|---|
| `CND-03` | « procédure de retour produit » | 0.9480 | servi |
| `CND-01` | « Comment procéder à un retour ? » | 0.0859 | servi |
| `CND-02` | « que faire en cas de retour d'un article ? » | 0.0061 | **refusé** |

**Le correctif fait ce qu'il annonce, et pas plus.** Sous `C1`, `support` passe de
0.0021 à 0.0061
sur `CND-02` : il rejoint **exactement** `dev`. L'asymétrie de périmètre est donc
réparée. Ce qui refuse encore est le **seuil**, sur un document que le retrieval trouve.

C'est le défaut `2bis.2`, et il est distinct : il ne dépend pas du profil, et aucun
réglage de vivier ne l'atteint. Le rapport de refus (axe 4) est l'endroit où il se
tranche.

## Limites

**Le jeu de mesure partagé ne voit rien de cet axe.** Rejoué en `C0` puis `C1`
(`make mesure-candidats`), il rend les mêmes Hit@1 8/8, MRR 1,000, Recall@5 12/13 et
refus corrects 5/8 — aucun verdict, aucun rang ne bascule. Six scores sur 38 dérivent,
tous vers le bas. La raison est que ce jeu est joué **sans périmètre** et qu'aucune de
ses cibles n'est enterrable par une série redondante : **un jeu qui ne contient pas le
cas difficile ne peut rien dire du cas difficile.** C'est la troisième fois que ce
dossier le constate.

**Quatre questions, pas trente.** Ce jeu-ci est écrit pour un défaut nommé ; il montre
un mécanisme, il ne mesure pas une capacité générale.

**Un vivier plus profond ne fait pas qu'ajouter.** Le budget reste à 20 : élargir le
vivier change *lesquels* des candidats sont notés, puisque les scores RRF se recomposent
sur une union plus large. Un score de rang 1 peut donc baisser, et six le font sur le jeu
partagé. Aucun n'y change de verdict, mais rien ne garantit qu'aucun ne le ferait sur un
autre jeu.

*Rejouer : `make mesure-candidats-profils`, et `make mesure-candidats` pour les deux
cellules sur le jeu partagé.*
