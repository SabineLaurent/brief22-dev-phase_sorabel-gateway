# Rapport de gain — recherche avancée (E6)

Généré par `scripts/eval_rag.py --report` à partir des CSV de `eval/resultats/` — voir `eval/protocole-mesure.md` pour le protocole complet. **Ne pas éditer à la main** : `make mesure` réécrit ce fichier en entier.

## Axe 1 — la recherche, à ingestion constante (E6)

Texte nettoyé, filtre de version actif, règle de départage appliquée dans les trois configurations (`eval/protocole-mesure.md` §1). Profil `commercial` — périmètre documentaire complet, le cas le plus difficile pour le refus (Q5 §5).

| sous-ensemble | métrique | A dense | B lexical | C hybride |
|---|---|---:|---:|---:|
| reference_exacte | Hit@1 (référence) | 2/8 | 3/8 | 8/8 |
| reference_exacte | Hit@1 (fiche technique) | 2/8 | 3/8 | 8/8 |
| reference_exacte | MRR | 0.375 | 0.688 | 1.000 |
| couverte | Recall@5 (`attendu_type`, n=13) | 11/13 | 11/13 | 12/13 |
| hors_corpus | refus corrects | 7/8 | n/a — Q4 §3 | 5/8 |

`B` n'a pas de seuil de refus praticable (aucune échelle bornée sur un score BM25 — Q4 §3) : la case vide est un résultat, pas un trou.

## Effet de la règle de départage — avec / sans, sur les trois sous-ensembles

| configuration | Hit@1 référence (sans / avec) | Hit@1 fiche (sans / avec) | Recall@5 type (sans / avec) |
|---|---:|---:|---:|
| A dense | 2/8 / 2/8 | 2/8 / 2/8 | 11/13 / 11/13 |
| B lexical | 3/8 / 3/8 | 1/8 / 3/8 | 11/13 / 11/13 |
| C hybride | 8/8 / 8/8 | 8/8 / 8/8 | 12/13 / 12/13 |

## Axe 2 — l'ingestion, à recherche constante

Configuration C fixée dans les deux cas — seul un flag d'ingestion varie contre `mesure-hybride`.

| | Hit@1 référence | Hit@1 fiche | Recall@5 type | refus corrects |
|---|---:|---:|---:|---:|
| C — texte nettoyé (référence) | 8/8 | 8/8 | 12/13 | 5/8 |
| C — texte brut (`--text raw`) | 8/8 | 8/8 | 12/13 | 5/8 |
| C — sans filtre de version (`--version-filter off`) | 8/8 | 8/8 | 12/13 | 5/8 |

## La ligne « RAG simple »

Un point de comparaison lisible, publié **en plus** des deux axes ci-dessus, jamais à leur place (protocole §4) : `texte brut · dense seul · sans filtre de version · sans départage` contre `texte nettoyé · hybride · filtre actif · départage actif`.

| | Hit@1 référence | Hit@1 fiche | Recall@5 type |
|---|---:|---:|---:|
| RAG simple | 1/8 | 1/8 | 12/13 |
| RAG avancé | 8/8 | 8/8 | 12/13 |

## Limites méthodologiques — à lire avant les chiffres ci-dessus

- **huit questions par sous-ensemble** : un échantillon minuscule, le seuil de refus reste réglé sur une base étroite (protocole §9) ;
- **`attendu_type` ne prend que trois valeurs**, et manque sur une des 14 questions `couverte` (RAG-09) — ce sous-ensemble détecte une régression, il ne démontre pas un gain ;
- **sur les 6 questions `couverte` attendant une `procedure_sav`, le titre est le seul discriminant** — le nettoyage SAV rend le corps des 80 procédures identique ;
- **RAG-19 et RAG-20 sont en tension avec le corpus** (sujet absent pour l'une, terme présent en notice seulement pour l'autre) : une configuration qui les rate n'a pas régressé, voir leur ligne dans les CSV individuels ;
- **le compte porte sur les questions, pas sur les références** : RAG-01 et RAG-02 partagent `REF-8842` — 8 questions pour 7 références distinctes.
