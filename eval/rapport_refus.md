# Le refus documentaire, mesuré sur les deux barrières

Axe 4 du [protocole de mesure](protocole-mesure.md). Une seule chose varie : le
**nombre de barrières prises en compte**. Profil `commercial` — périmètre
documentaire complet, donc le cas le plus difficile pour le refus —, étage hybride,
texte nettoyé, filtre de version actif, les 30 questions de `questions_rag.jsonl`,
seuil du reranker à **0.0530**.

## Pourquoi ce rapport existe

[`rapport_gain.md`](rapport_gain.md) publie une ligne « refus corrects ». Elle est
mesurée sur `search()` suivi d'une comparaison au seuil — **la barrière 1 seule**,
ce qui est le bon périmètre pour un rapport qui compare des étages de recherche.
Mais E1 ne vit pas dans `search()` : elle vit dans `answer_question`, qui a deux
barrières. Lire le chiffre de `rapport_gain.md` comme le refus servi est une erreur
— elle a été commise dans la première version de la revue du 2026-09-07.

| | Où | Ce qu'elle lit | Nature |
|---|---|---|---|
| **barrière 1** `hors_corpus` | `search(threshold=…)` | le score du premier résultat | déterministe, **avant tout appel au modèle** |
| **barrière 2** `contexte_insuffisant` | la garde de suffisance du rédacteur | les extraits eux-mêmes | jugement du modèle, **non déterministe** |

Les deux colonnes sont lues sur **le même appel servi** : le code rendu dit lequel
des deux étages a tranché. Aucune des deux n'est reconstituée.

`search_docs` n'a aucune barrière et n'en aura pas : c'est le tool sur lequel E6 se
mesure, et un seuil qui masque les résultats sous la barre rend le rang
inobservable. Il n'apparaît pas dans cette mesure.

## Résultats

*3 passes, 90 appels de `answer_question`.*

*Les dénominateurs sont ceux d'**une** passe ; une plage `n–m` signale une métrique
qui bouge d'une passe à l'autre.*

### Les 8 questions hors corpus — le refus qu'on veut

| | Barrière 1 seule | Les deux barrières |
|---|---|---|
| Refus corrects | 5 / 8 | **8 / 8** |
| Servies malgré tout | 3 | 0 |

La barrière 2 rattrape **3** question(s) que le seuil laisse
passer : RAG-23, RAG-24 et RAG-29. La barrière 1 en tranche
5 : RAG-25, RAG-26, RAG-27, RAG-28 et RAG-30 — et elle les tranche
**sans dépenser un token**, ce que la seconde ne peut pas faire.

### Les 22 questions à cible — le refus qu'on ne veut pas

| | Barrière 1 seule | Les deux barrières |
|---|---|---|
| Faux refus | 1 / 22 | **3 / 22** |
| Réponses servies | 21 | 19 |

La barrière 1 en refuse 1 : RAG-19.
La barrière 2 en refuse 2 de plus : RAG-18 et RAG-20.

**Un faux refus n'est pas toujours un défaut.** Le protocole (§9) signale déjà deux
questions en tension avec le corpus — RAG-19 porte sur un sujet absent, RAG-20
attend une fiche technique là où le terme n'existe qu'en notice. Une configuration
qui les refuse n'a pas régressé : elle a raison contre le jeu.

## Toutes les sources citées viennent du classement, par construction

Sur un code `ok`, `answer_question` cite au moins une source, et le modèle ne rend
que des **numéros** d'extraits : ceux hors bornes sont ignorés, et la citation est
construite en Python depuis les métadonnées. Il n'y a donc rien à mesurer sur cette
moitié d'E1 — elle est vraie par construction, pas par statistique. Le décompte
ci-dessous l'atteste sans le démontrer :

- réponses servies avec au moins une source : 57 / 57.

## Les trois plages de score se recouvrent

Le score du premier résultat, relevé par `search_docs` — donc **avant** que le seuil
l'escamote — sur l'échelle du reranker :

| Sous-ensemble | plage du score du 1er résultat |
|---|---|
| `reference_exacte` | 0.9998 – 1.0000 |
| `couverte` | 0.0049 – 0.9997 |
| `hors_corpus` | 0.0015 – 0.8422 |

**C'est la raison d'être de la barrière 2, et il faut la lire dans ce sens.** Tant
que la plage des questions couvertes et celle des hors-corpus se chevauchent, aucun
réglage du seuil ne les sépare : monter le seuil pour attraper une question hors
corpus refuse une question couverte au même score. Une seconde barrière qui lit le
**contenu** plutôt que le score n'est donc pas une ceinture de sécurité ajoutée par
prudence — c'est le seul organe qui peut trancher là où le score ne peut pas.

## Ce que cette mesure ne garantit pas

**La barrière 2 est un jugement de modèle.** Elle n'est pas déterministe, et le
protocole (§11) refuse par ailleurs tout juge probabiliste *dans la mesure* — ici il
est dans le **produit**, ce qui est différent : on mesure ce que la gateway fait, et
ce qu'elle fait comporte un appel de modèle. La conséquence est qu'un chiffre de la
colonne « les deux barrières » peut bouger d'une exécution à l'autre, là où celui de
la barrière 1 ne bouge pas.

Sur 3 passes, **aucune question ne change de verdict**. C'est un
constat de stabilité sur ce jeu, pas une garantie de déterminisme.

**Huit questions par sous-ensemble**, comme partout dans ce protocole (§9) : un
écart d'une question vaut 12,5 points. Ces chiffres détectent une régression, ils
ne mesurent pas une capacité.

*Rejouer : `make mesure-refus`.*
