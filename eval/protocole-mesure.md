# Protocole de mesure — ce qui varie, ce qui ne varie pas

Ce document fixe **l'espace des configurations comparables** avant que la moindre mesure
soit produite. Il existe pour une raison précise : un chiffre de gain n'a de valeur que si
l'on peut dire à quelle décision il est imputable.

Référence normative : [`Q5`](../docs/conception/1-rag-avance/Q5.md) §1.

> « Même corpus, même index nettoyé, même filtre de version, même jeu de questions, même
> règle de départage. **Seul l'étage de recherche change** — sinon on ne mesure pas ce
> qu'on croit mesurer. »

## 1. Le principe : une seule chose change à la fois

Un « RAG simple » construit de bout en bout — sa propre ingestion, son propre index, sa
propre recherche — produirait **un seul chiffre indécomposable**, qui additionnerait :

| Ce qui change | Gain attribuable mesuré ou attendu |
|---|---|
| le nettoyage du texte indexé | **+5 en Hit@3** sur 8 questions ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2) |
| le filtre de version | change le dénominateur : 350 candidats au lieu de 400 |
| la stratégie de recherche | **la seule chose que le brief demande de mesurer** |

Un tel chiffre est flatteur et indéfendable : impossible de répondre à « quelle part vient
du reranker ? ». C'est le reproche que [`Q5`](../docs/conception/1-rag-avance/Q5.md) §2
adresse déjà au protocole à deux configurations.

**Décision : aucune mesure ne fait varier plus d'un drapeau à la fois.**

## 2. Quatre drapeaux orthogonaux

L'espace de mesure est un produit de quatre paramètres, pas une collection de pipelines.

| Drapeau | Valeurs | Où il s'applique | Ce qu'il change |
|---|---|---|---|
| `--text` | `clean` *(défaut)* · `raw` | ingestion | le texte indexé : avec ou sans retrait des liens sortants et des références-exemples des SAV ([`Q2`](../docs/conception/1-rag-avance/Q2.md) §2) |
| `--config` | `A` · `B` · `C` | recherche | l'étage de recherche : dense seul · lexical seul · hybride BM25+dense+RRF+rerank |
| `--version-filter` | `on` *(défaut)* · `off` | recherche | `is_current` appliqué dans chaque liste **avant sa troncature** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §5), ou pas de filtre |
| `--tiebreak` | `on` · `off` | recherche | la règle de départage fiche/notice, en rangs, `FENETRE = 3` ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §5) |

**Chaque valeur de `--text` a sa collection Chroma**, parce que le texte indexé détermine
les vecteurs : `sorabel_corpus` pour `clean`, `sorabel_corpus_raw` pour `raw`. Les trois
autres drapeaux ne touchent pas à l'index et se règlent à la requête.

**Le filtre de version est un drapeau de recherche, pas d'ingestion.** Les 400 éditions sont
indexées dans les deux collections, `is_current` étant une métadonnée
([`Q1`](../docs/conception/1-rag-avance/Q1.md) §5). Le désactiver ne demande donc pas un
second index — c'est ce qui rend l'axe 2 bon marché.

## 3. Les deux axes de mesure

### Axe 1 — la recherche, à ingestion constante

C'est **E6**, l'exigence du brief et du test d'acceptance.

| | Constant | Varie |
|---|---|---|
| | `--text clean` · `--version-filter on` · `--tiebreak` publié dans les deux positions | `--config A` → `B` → `C` |

| | Étage de recherche | Rôle |
|---|---|---|
| **A** | embedding + top-k | l'« avant » que le brief nomme *recherche dense initiale* |
| **B** | BM25 + top-k | **le témoin** — déjà 8/8 en Hit@1 sur le critère du jeu ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2) |
| **C** | BM25 + dense + RRF + rerank | l'« après » |

B n'est pas demandé par le brief. Sans lui, le gain attribué à l'hybride inclut celui de
BM25 seul, et le chiffre ment par omission
([`Q5`](../docs/conception/1-rag-avance/Q5.md) §2).

### Axe 2 — l'ingestion, à recherche constante

Le dossier ne le mesure pas. Il répond à : **que valent les décisions d'ingestion ?**

| | Constant | Varie |
|---|---|---|
| nettoyage | `--config` fixée · `--version-filter on` | `--text clean` → `raw` |
| versionnement | `--config` fixée · `--text clean` | `--version-filter on` → `off` |

Deux mesures distinctes, un drapeau chacune. La première chiffre le nettoyage sur ce corpus
et doit retrouver le **+5 en Hit@3** annoncé par [`Q3`](../docs/conception/1-rag-avance/Q3.md) §2 —
si elle ne le retrouve pas, c'est l'implémentation qui s'écarte du dossier, et on le saura.

La seconde chiffre ce que coûte l'absence de versionnement. L'attendu est nommé avant d'être
mesuré, pour ne pas l'ajuster après coup : **50 documents ont deux éditions à 0,965 de
similarité** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §4). Sans filtre, les deux
occupent deux places du même top-5 pour un contenu unique.

> **Le dédoublonnage par hash n'est pas un axe de mesure.** Il est mesuré à **zéro doublon
> d'octets sur les 400 fichiers** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §3) : une
> étape qui ne se déclenche jamais. Le seul doublon réel du corpus est l'édition multiple,
> et c'est l'axe `--version-filter` qui le traite. Le seul risque de doublon d'index est la
> ré-ingestion, déjà couverte par l'`upsert` déterministe.

## 4. Le « RAG simple » est un coin de l'espace, pas un second projet

Il ne se construit pas, il se **désactive**.

| | `--text` | `--config` | `--version-filter` | `--tiebreak` |
|---|---|---|---|---|
| **RAG simple** | `raw` | `A` | `off` | `off` |
| **RAG avancé** | `clean` | `C` | `on` | `on` |

Cette ligne-là **peut** être publiée — elle parle, et c'est celle qu'un lecteur non
technique comprend. Mais elle est publiée **en plus** des deux axes, jamais à leur place,
et toujours accompagnée de leur décomposition. Un écart global sans ventilation n'est pas
une mesure, c'est une affiche.

## 5. Le refus n'a pas la même grandeur selon la configuration

[`Q5`](../docs/conception/1-rag-avance/Q5.md) §4 : la configuration A n'a pas de reranker,
donc pas du score sur lequel [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3 fait porter le
seuil. Il n'existe pas de grandeur commune aux trois.

| Configuration | Critère de refus | Grandeur |
|---|---|---|
| **A** | distance cosinus du premier résultat | bornée, comparable entre requêtes |
| **B** | **aucun seuil possible** — case vide, et c'est un résultat | — |
| **C** | score du reranker | bornée, apprise |

> La ligne se lit **« chaque configuration à son meilleur réglage »**, jamais « le même
> seuil ». Le seuil de chacune est calibré sur le **même jeu de calibration** — huit
> questions hors corpus écrites par nous, distinctes des huit du jeu d'évaluation
> ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §6).

Conséquence pour l'étape 2, à ne pas manquer : la recherche dense seule doit poser son seuil
sur **la distance cosinus**, nommée comme telle. Un seuil écrit sur un score non borné
serait à jeter à l'étape 3.

## 6. Ce qui ne varie dans aucune mesure

- le **corpus** : `data/corpus/`, 400 éditions, inchangé ;
- le **jeu de questions** : `eval/questions_rag.jsonl`, 30 questions — 8 `reference_exacte`,
  14 `couverte`, 8 `hors_corpus` ;
- le **profil d'accès** : `commercial`, périmètre documentaire complet, donc le cas le plus
  difficile pour le refus et le seul indépendant d'un filtre de gouvernance
  ([`Q5`](../docs/conception/1-rag-avance/Q5.md) §5). Le taux du profil `support` est
  indiqué en second, **comme effet de la matrice, pas comme gain de recherche** ;
- les **versions figées** : `pypdf`, le modèle d'embeddings, le reranker — elles déterminent
  le contenu de l'index et le classement ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §6) ;
- la **graine** et l'**ordre de parcours** du corpus ;
- le **compte** : on compte les **questions**, pas les références — 8 questions pour
  7 références distinctes, vérifié sur le fichier réel.

## 7. Ce qui est publié

`eval_rag.py` écrit **un CSV par question** — configuration, id, critère, rang du bon
document, score, refus oui/non, code renvoyé — puis imprime le tableau de synthèse.

Le CSV importe autant que le tableau : c'est lui qui permet de dire *quelle* question a
échoué et pourquoi. Trois sous-ensembles, trois métriques
([`Q5`](../docs/conception/1-rag-avance/Q5.md) §3) :

| Sous-ensemble | n | Métrique |
|---|---:|---|
| `reference_exacte` | 8 | Hit@1 **sur deux critères** — référence attendue, et fiche technique en tête — plus MRR |
| `couverte` | 14 | Recall@5 sur `attendu_type`, et rang du premier document du bon type |
| `hors_corpus` | 8 | taux de refus correct |

**Les deux critères de Hit@1 sont publiés côte à côte** : ils diffèrent de 6 points sur 8 en
BM25 seul. Le critère exigeant est celui du test d'acceptance ; celui du jeu se calcule sans
interprétation. Et `--tiebreak` est publié **dans ses deux positions, sur les trois
sous-ensembles** — c'est sur `couverte` que la règle peut nuire.

## 8. Nommage

**Le vocabulaire publié est celui des cibles Make, en français** — c'est lui qui apparaît
dans le rapport et qui doit rester stable une fois qu'un chiffre le cite. Les drapeaux du
script restent en anglais par cohérence avec `--dry-run` et `--reset` ; ils sont un détail
d'implémentation, pas l'interface. Voir §10.

## 9. Ce que ce protocole ne mesure pas — à dire, pas à cacher

- **huit questions par sous-ensemble**, c'est un échantillon minuscule. Le seuil de refus
  reste réglé sur une base étroite : limite méthodologique, pas corrigeable à cette échelle ;
- **`attendu_type` ne prend que trois valeurs** sur les questions `couverte` — et n'est
  présent que sur **13** des 14. Ce sous-ensemble détecte une régression, il ne démontre pas
  un gain ;
- **deux questions sont en tension avec le corpus** : RAG-19 porte sur un sujet absent,
  RAG-20 attend une fiche technique là où le terme n'existe qu'en notice. Elles sont
  mesurées comme les autres et **signalées dans le rapport** : une configuration qui les
  rate n'a pas régressé ;
- **rejouer A après C**, pas seulement avant
  ([`Q5`](../docs/conception/1-rag-avance/Q5.md) §6) : une mesure « avant » faite sur un
  index qui a changé entre-temps n'est pas une mesure.

## Conséquence sur le code à écrire

**La recherche prend sa collection et sa stratégie en paramètres, jamais en constantes.**
C'est la seule décision d'architecture qu'impose ce protocole, et elle se prend à l'étape 2 :
si elle est prise, chaque axe de mesure coûte un drapeau ; si elle ne l'est pas, il faudra
rouvrir la recherche à l'étape 3, au moment précis où il faudra la rejouer à l'identique.

## 10. Comment ça se joue

### Le harnais lit les `.jsonl`, il ne passe pas par le serveur MCP

Le jeu d'évaluation est du **JSON Lines** — une question par ligne, pas un `.json` unique :

```
eval/questions_rag.jsonl          30 questions fournies — 8 reference_exacte · 14 couverte · 8 hors_corpus
eval/questions_calibration.jsonl  8 questions hors corpus écrites par nous — CALIBRATION SEULEMENT
eval/questions_sql.jsonl          chantier 2, hors de ce protocole
```

Le harnais lit `questions_rag.jsonl`, rejoue **chaque question dans chaque configuration**,
et écrit une ligne de CSV par couple (question, configuration).

> **Les deux fichiers de questions ne se mélangent jamais.**
> `questions_calibration.jsonl` sert à régler les seuils,
> `questions_rag.jsonl` à les mesurer. Les confondre ferait constater un réglage au lieu de
> mesurer une capacité ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §6). Le harnais refuse
> de calibrer et de mesurer sur le même fichier.

**Le harnais attaque la recherche directement, sans serveur MCP.** C'est ce qui permet de
mesurer E6 dès l'étape 2, alors que les tests d'acceptance — qui exigent le serveur —
ne passeront qu'au chantier 3. Ce sont deux vérifications différentes, sur deux chemins
différents, et elles n'ont pas le même calendrier.

Le script est `scripts/eval_rag.py`, lancé par chemin comme `scripts/check_index.py` — pas
un module importable, pour ne pas nommer un paquet `eval`.

### Une cible Make par mesure publiée

Les quatre drapeaux forment 24 combinaisons, mais **on n'en publie que sept**. À ce
nombre-là, une cible nommée par mesure vaut mieux qu'une chaîne de drapeaux : c'est la
convention du dépôt — tous les flux passent par `make` —, c'est ce qui rend un chiffre
rejouable tel quel, et c'est le seul endroit où le protocole se lit d'un coup d'œil.

```make
# — ingestion —
ingest                   # texte nettoyé -> sorabel_corpus        (défaut, existant)
ingest-brut              # texte brut    -> sorabel_corpus_raw    (axe 2a)

# — axe 1 : la recherche, à ingestion constante —
mesure-dense             # A · clean · filtre on   — l'« avant » du brief
mesure-lexical           # B · clean · filtre on   — le témoin
mesure-hybride           # C · clean · filtre on   — l'« après »

# — axe 2 : l'ingestion, à recherche constante —
mesure-sans-nettoyage    # C · raw   · filtre on   — ce que vaut le nettoyage
mesure-sans-versions     # C · clean · filtre off  — ce que vaut le versionnement

# — la ligne parlante —
mesure-rag-simple        # A · raw   · filtre off · départage off

# — orchestration —
mesure                   # rejoue les sept et réécrit eval/rapport_gain.md
calibrer                 # règle les seuils sur questions_calibration.jsonl
```

**Les cibles sont l'interface publiée ; les drapeaux restent dessous.** Le script les accepte
— il en a besoin — mais aucun chiffre du rapport ne cite une ligne de commande à drapeaux :
il cite une cible. L'exploration ponctuelle et le débogage passent par le script directement,
sans que ça devienne une manière de produire un résultat publiable.

```bash
uv run python scripts/eval_rag.py --config A --text raw --version-filter off   # exploration
make mesure-rag-simple                                                          # publication
```

**`--tiebreak` n'a pas sa cible.** La règle de départage est un réordonnancement de la liste
finale : le harnais calcule les deux positions dans la même passe et publie les deux colonnes
([`Q3`](../docs/conception/1-rag-avance/Q3.md) §5). Une cible par position doublerait le
nombre de runs pour un post-traitement qui ne coûte rien.

**Les noms de cibles sont en français**, comme le reste du `Makefile` et comme le fixe
`CLAUDE.md`. Les drapeaux du script restent en anglais, par cohérence avec `--dry-run` et
`--reset` — ils ne sont plus le vocabulaire publié, donc la question de leur langue ne se
pose plus.

### Ce qui est écrit sur le disque

```
eval/resultats/mesure-dense.csv            une ligne par question
eval/resultats/mesure-sans-nettoyage.csv
eval/resultats/…                           un fichier par cible
eval/rapport_gain.md                       le tableau de synthèse publié
```

**Le CSV porte le nom de la cible qui l'a produit**, et son en-tête rappelle les quatre
drapeaux effectifs. Un fichier de résultats dont on ne peut pas relire la configuration n'est
pas une mesure, c'est un souvenir — et le nom de la cible est la manière la plus courte de la
relire, puisqu'il suffit de la relancer.

Un run d'exploration lancé au script écrit dans `eval/resultats/adhoc-*.csv`, jamais sous un
nom de cible : ce qui n'est pas reproductible par un `make` ne prend pas la place de ce qui
l'est. Et `make mesure` réécrit `rapport_gain.md` **en entier**, jamais par retouche — un
rapport à moitié régénéré mélangerait deux exécutions.

## 11. Pas d'évaluateur de RAG — et c'est une décision, pas une paresse

La question se pose : RAGAS, DeepEval, TruLens, promptfoo, ou un LLM-juge maison. **Non**,
et [`Q5`](../docs/conception/1-rag-avance/Q5.md) §3 le tranche explicitement :

> « La mesure reste une comparaison de chaînes dans les deux cas — **pas de LLM-juge, pas
> d'annotation manuelle**, deux exécutions donnent le même chiffre. »

Quatre raisons, dans l'ordre où elles pèsent.

**1. Les métriques demandées sont des métriques de *retrieval*, pas de génération.** Hit@1,
MRR, Recall@5, taux de refus : toutes se calculent par égalité de chaînes contre
`attendu_reference` et `attendu_type`.

```python
top = resultats[0]
hit_reference = top.metadata["reference"] == question["attendu_reference"]
hit_fiche     = hit_reference and top.metadata["doc_type"] == "fiche_technique"
```

Un évaluateur n'ajouterait rien à ces trois lignes, sinon une dépendance.

**2. Le corpus d'évaluation n'a pas de réponses de référence.** `questions_rag.jsonl` porte
`id`, `type`, `question`, `attendu_reference` — et rien d'autre. Les métriques centrales de
RAGAS (*faithfulness*, *answer relevancy*, *context recall*) exigent une réponse ou un
contexte attendus. Il faudrait donc les **écrire nous-mêmes**, puis noter nos réponses
contre nos propres attendus : corriger sa propre copie.

**3. Ces métriques sont elles-mêmes jugées par un LLM, donc non déterministes — sur
`n = 8`.** Le sous-ensemble `reference_exacte` compte huit questions. Une métrique dont deux
exécutions ne donnent pas le même chiffre introduirait une variance du même ordre que le
gain à démontrer. Q5 §6 exige au contraire de figer les versions, la graine et l'ordre de
parcours : un juge probabiliste va exactement contre.

**4. L'architecture a déjà retiré le besoin.** C'est le point à défendre en soutenance :

| Ce qu'un évaluateur mesurerait | Pourquoi c'est sans objet ici |
|---|---|
| *faithfulness* — la réponse est-elle fidèle aux sources ? | la **citation n'est pas rédigée par le modèle**, elle est construite en Python depuis les métadonnées ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §1). Elle est exacte par construction — il n'y a rien à vérifier après coup |
| *context precision / recall* | c'est Hit@1 et Recall@5, calculés sur `attendu_*` |
| le refus est-il justifié ? | le contrat de sortie porte un `code` — `hors_corpus`, `contexte_insuffisant`, ou une réponse. Comparaison de chaînes |
| la réponse suffit-elle ? | la **garde de suffisance** ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §5) est *dans* le pipeline, en sortie structurée, pas dans l'évaluateur |

Un pipeline où la citation est générée par le modèle *a besoin* d'un évaluateur de fidélité.
Celui-ci n'en a pas besoin parce qu'il ne peut pas mentir sur ses sources.

> **Ce qu'on écrit dans le rapport**, plutôt que de faire semblant de ne pas connaître ces
> outils : les évaluateurs de RAG ont été examinés et écartés, avec ces quatre raisons. Un
> outil écarté pour une raison mesurée vaut mieux qu'un outil branché sans raison.

**La seule chose qui pourrait faire revenir la question** : si le brief demandait de noter
la *qualité rédactionnelle* des réponses. Il ne le demande pas — E1 porte sur la citation et
le refus, E6 sur le gain de la recherche. Les deux sont structurels et déterministes.

## Renvois

- protocole normatif : [`Q5`](../docs/conception/1-rag-avance/Q5.md)
- refus et seuils : [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3 et §6
- étages de recherche, RRF, départage : [`Q3`](../docs/conception/1-rag-avance/Q3.md)
- texte indexé et nettoyage : [`Q2`](../docs/conception/1-rag-avance/Q2.md) §2
- filtre de version et éditions courantes : [`Q1`](../docs/conception/1-rag-avance/Q1.md) §5
