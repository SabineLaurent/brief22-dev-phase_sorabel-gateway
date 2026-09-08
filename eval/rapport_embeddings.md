# Rapport — l'effet du modèle d'embeddings (axe 6)

**Écrit à la main**, comme [`rapport_rerank.md`](rapport_rerank.md) et contrairement à
[`rapport_gain.md`](rapport_gain.md) que `make mesure` régénère. Les chiffres viennent des
quatre CSV nommés ci-dessous, tous rejouables par `make mesure-embeddings`.

Protocole : [`protocole-mesure.md`](protocole-mesure.md) §2 (drapeau `--embeddings`) et §3
(axe 6).

## Ce qui varie, et ce qui ne varie pas

| | valeur |
|---|---|
| **varie** | `--embeddings local` → `azure-small`, **et la collection qui va avec** |
| constant | `--text clean` · **`--rerank local`** · `--version-filter on` · `--tiebreak on` |
| jeu | `eval/questions_rag.jsonl`, 30 questions · profil `commercial` |
| CSV | `resultats/mesure-emb-{local,azure}-{A,C}.csv` |

| | modèle | dimensions | collection | seuil A | seuil C |
|---|---|---:|---|---:|---:|
| local | `intfloat/multilingual-e5-base` | 768 | `sorabel_corpus` | 0,8308 | 0,0530 |
| azure-small | `text-embedding-3-small` | 1536 | `sorabel_corpus_azure_small` | 0,4893 | 0,0153 |

**Le reranker reste local des deux côtés** : c'est ce qui sépare cet axe de l'axe 7. Et
chaque passe porte ses propres seuils, calibrés sur `questions_calibration.jsonl` — comparer
à seuil constant aurait mesuré le seuil.

## Le résultat

| sous-ensemble | métrique | A — `e5` | A — Azure | C — `e5` | C — Azure |
|---|---|---:|---:|---:|---:|
| reference_exacte | Hit@1 (référence) | 1/8 | **0/8** | 8/8 | 8/8 |
| reference_exacte | Hit@1 (fiche technique) | 1/8 | 0/8 | 8/8 | 8/8 |
| reference_exacte | MRR | 0,271 | **0,000** | 1,000 | 1,000 |
| couverte | Recall@5 (`attendu_type`, n=13) | 9/13 | **11/13** | 12/13 | 12/13 |
| hors_corpus | refus corrects | 7/8 | 6/8 | 5/8 | **4/8** |

## En configuration servie, l'embedder est invisible

C'est le résultat de l'axe, et il ne se lit pas dans le tableau mais dans les CSV : en
configuration **C**, **aucun rang ne change sur les 38 lignes**, et un seul verdict bascule.
Voici lequel, et pourquoi :

```
RAG-30  hors_corpus   e5     score 0,0175   seuil 0,0530   -> refus
                      azure  score 0,0175   seuil 0,0153   -> pas de refus
```

**Le score du premier résultat est identique au dix-millième.** Ce qui change n'est pas la
recherche, c'est le **seuil que la calibration de chaque modèle a produit**. BM25 et le
rerank absorbent entièrement la différence d'embedder : le reranker note les mêmes candidats,
dans le même ordre, et rend le même score.

Autrement dit : **en configuration hybride, le modèle d'embeddings de service donne un
résultat rigoureusement identique, moins un refus correct.**

## En dense seul, l'écart est réel — et à double sens

13 rangs sur 38 changent, et les deux modèles se trompent de façons opposées :

| | Azure fait mieux | Azure fait moins bien |
|---|---|---|
| `couverte` | Recall@5 **9/13 → 11/13** ; `RAG-17` et `RAG-18`, que `e5` refusait, obtiennent une réponse | |
| `reference_exacte` | | Hit@1 **1/8 → 0/8**, MRR **0,271 → 0,000** — le bon document n'est **jamais** dans les cinq premiers |
| `hors_corpus` | | `RAG-27` n'est plus refusée (7/8 → 6/8) |

Le sens de cet écart est cohérent avec le reste du dossier : une référence `REF-8842` est un
token rare, terrain de BM25 et non d'un modèle d'embeddings généraliste
([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2). Le modèle OpenAI est meilleur sur la
**prose**, `e5` accroche mieux les **identifiants** — et c'est précisément pour ça que la
configuration servie est hybride.

`RAG-19` bascule aussi mais ne compte pas : le protocole la signale « en tension avec le
corpus » (§9).

### Contre-vérification : le MRR de 0,000 n'est pas un échec muet

Question de l'utilisatrice en lisant ce chiffre — *« t'es sûr qu'il n'y a pas eu de gag
quelque part ? »*. Un zéro parfait est exactement la forme qu'aurait une erreur avalée en
silence. Trois vérifications indépendantes, toutes hors du harnais de mesure :

| ce qu'on craint | ce qui a été vérifié | résultat |
|---|---|---|
| le harnais écrit `0` sur une erreur | la colonne rang des 8 questions `reference_exacte` dans le CSV | **vide**, pas `0` — le harnais dit « absent du top-5 », il n'invente pas un zéro |
| le bon document est là, mais plus bas | recherche à `top_k=50` sur 350 éditions courantes | 50 résultats rendus, **le bon document absent du top 50** |
| l'index Azure est incomplet ou corrompu | le **texte du document lui-même** passé en requête | **rang 1, score 0,9572** — les vecteurs sont sains, la collection est complète (647 caractères, identiques à ceux de l'index `e5`) |

Le résultat tient donc, et il s'explique. Le document contient en clair
`Référence produit : REF-8842` — le modèle le **voit**, il ne le **pondère** pas. Une requête
de huit caractères contre un document de 647 produit un vecteur dominé par la sémantique
générique (« une référence produit »), dont les 400 éditions du corpus parlent toutes.

C'est la démonstration par l'absurde de ce que
[`Q3`](../docs/conception/1-rag-avance/Q3.md) §2 posait : pour BM25 une référence est un
terme à IDF très élevé, donc décisif ; pour un embedding ce n'est qu'un motif parmi d'autres.
**Ce n'est pas une faiblesse d'OpenAI en particulier** — `e5` place la même notice au rang 3,
ce qui n'est pas bon non plus (1/8). C'est la raison d'être de la recherche hybride, et la
configuration C le confirme : les deux modèles y font 8/8.

## Le renversement entre le jeu de réglage et le jeu de mesure — deuxième occurrence

Sur `questions_calibration.jsonl` (14 questions), la conclusion était **l'inverse** :

| | `e5` | `text-embedding-3-small` |
|---|---|---|
| `couverte` | 0,820 – 0,882 | — |
| `hors_corpus` | 0,797 – 0,831 | — |
| populations séparables (config A) | **NON — elles se chevauchent** | **OUI** |

Le modèle Azure séparait proprement ce que `e5` chevauchait, ce qui laissait attendre un
meilleur refus. Sur les 30 questions, il refuse **moins bien**, en A (6/8 contre 7/8) comme
en C (4/8 contre 5/8).

**La cause est identifiée, et elle est structurelle** — question de l'utilisatrice pendant la
mesure, vérifiée sur les fichiers :

```
questions_calibration.jsonl : {hors_corpus: 8, couverte: 6}    — 0 question porte une REF-
questions_rag.jsonl         : {reference_exacte: 8, couverte: 14, hors_corpus: 8}  — 8 REF-
```

**Le jeu de calibration ne contient aucune référence produit.** Il ne teste donc jamais le
point faible du modèle OpenAI, et interroge surtout son point fort, la prose. D'où l'avantage
qu'il lui donne, et d'où le renversement dès que la mesure ajoute huit questions
`reference_exacte`.

Ce n'est **pas** un défaut du jeu de calibration : il existe pour placer une frontière entre
« couvert » et « hors corpus » ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §3), et des
références n'y serviraient à rien. Mais il faut le dire net : **il est non représentatif pour
comparer deux modèles** — un tiers du jeu de mesure n'y a pas d'équivalent.

C'est la **deuxième fois** dans ce protocole qu'un jeu de calibration annonce l'inverse du
résultat (l'axe 7 a produit le même renversement sur les rerankers, en sens contraire), et
c'est une raison de plus de ne jamais calibrer sur le jeu de mesure — mais la leçon
opératoire est plus précise que la morale : **un jeu qui ne contient pas le cas difficile ne
peut pas prédire ce qui arrive sur le cas difficile.**

## Réserves

- **huit questions `hors_corpus`, treize `couverte`.** Les écarts mesurés ici sont d'une à
  deux questions ; ils ne survivraient pas forcément à un autre échantillon ;
- **`e5` est asymétrique, les modèles OpenAI ne le sont pas.** `e5` reçoit `query:` devant la
  question et `passage:` devant le document — un régime pour lequel il a été entraîné. La
  comparaison est donc « chaque modèle dans son usage nominal », pas « le même traitement
  pour les deux » ;
- **le jeu de calibration ne couvre pas `reference_exacte`** (voir ci-dessus). Les seuils
  publiés ici sont donc réglés sur de la prose seule, pour les deux modèles ;
- **un seul modèle de service testé.** `text-embedding-3-large` (3072 dimensions) et les
  modèles Cohere multilingues du catalogue ne sont pas mesurés ;
- **le corpus favorise BM25.** 400 éditions courtes, fortement identifiées par des
  références. Sur un corpus de prose longue sans identifiants, la moitié `couverte` du
  tableau pèserait bien plus lourd que la moitié `reference_exacte`.

## Ce que la mesure décide

Elle décide, et c'est rare : **il n'y a aucune raison de qualité de basculer les embeddings
sur le service.** En configuration servie, le résultat est identique à un refus près, et ce
refus est perdu.

Elle règle aussi l'argument de déploiement qui avait ouvert la question : basculer l'embedder
pour supprimer PyTorch de l'image coûterait **un refus correct sur huit**, pour zéro gain
mesuré. Si l'empreinte mémoire doit baisser, c'est une décision d'architecture à prendre les
yeux ouverts sur ce prix — pas un remplacement neutre.
