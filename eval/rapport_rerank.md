# Rapport — l'effet du reranker (axe 7)

**Écrit à la main**, contrairement à [`rapport_gain.md`](rapport_gain.md) que `make mesure`
régénère : cet axe publie deux cellules, pas six, et un générateur coûterait plus que ce
qu'il rendrait. Les chiffres viennent des CSV nommés ci-dessous, tous deux rejouables par
`make mesure-rerank`.

Protocole : [`protocole-mesure.md`](protocole-mesure.md) §2 (drapeau `--rerank`) et §3
(axe 7).

## Ce qui varie, et ce qui ne varie pas

| | valeur |
|---|---|
| **varie** | `--rerank local` → `cohere` |
| constant | `--text clean` · `--embeddings local` (`multilingual-e5-base`, collection `sorabel_corpus`) · `--version-filter on` · `--tiebreak on` · `--config C` |
| jeu | `eval/questions_rag.jsonl`, 30 questions · profil `commercial` |
| CSV | `resultats/mesure-rerank-local.csv` · `resultats/mesure-rerank-cohere.csv` |

**`--embeddings` reste local, et c'est la condition du résultat** : c'est ce qui permet
d'attribuer l'écart au reranker et à rien d'autre.

**Chaque passe porte son propre seuil calibré** — 0,0530 pour le cross-encoder, 0,5923 pour
Cohere, tous deux obtenus sur `questions_calibration.jsonl`, jamais sur le jeu ci-dessus.
Comparer à seuil constant aurait mesuré le seuil.

## Le résultat

| sous-ensemble | métrique | mmarco (local) | Cohere-rerank-v4.0-pro |
|---|---|---:|---:|
| reference_exacte | Hit@1 (référence) | 8/8 | 8/8 |
| reference_exacte | Hit@1 (fiche technique) | 8/8 | 8/8 |
| reference_exacte | MRR | 1,000 | 1,000 |
| couverte | Recall@5 (`attendu_type`, n=13) | 12/13 | 12/13 |
| couverte | refusées à tort | 1/14 | **0/14** |
| hors_corpus | **refus corrects** | **5/8** | **7/8** |

**Tout l'écart est sur le refus. Le classement ne bouge pas** : sur les 38 lignes du CSV,
**une seule** change de rang. C'est ce que le protocole annonçait avant la mesure — sur les
questions `reference_exacte`, BM25 a déjà placé le bon document en tête, et un meilleur
reranker ne peut y gagner que des places qui sont déjà prises.

### Les trois verdicts qui changent

| question | type | mmarco | Cohere | lecture |
|---|---|---|---|---|
| `RAG-23` | hors_corpus | `ok` — 0,0868 | **refus** — 0,4279 | gain |
| `RAG-29` | hors_corpus | `ok` — 0,5175 | **refus** — 0,5172 | gain |
| `RAG-19` | couverte | refus — 0,0049 | `ok` — 0,6685 | **à ne pas compter comme un gain** |

`RAG-19` est l'une des deux questions que le protocole signale comme **en tension avec le
corpus** (§9 : « porte sur un sujet absent »). Cohere y répond au lieu de refuser, **et** y
fait reculer le document du bon type du rang 1 au rang 5 — c'est le seul rang qui change de
tout le fichier. Le compter comme un faux refus évité serait se féliciter d'avoir répondu à
une question dont le corpus ne porte pas la réponse.

**Le gain net défendable est donc de +2 refus corrects sur 8**, sans contrepartie sur le
classement.

### Le mécanisme, lisible dans les scores

Cohere **n'accorde jamais moins de 0,29** à quoi que ce soit, là où le cross-encoder écrase
les hors-corpus à quasi zéro. Les deux échelles sont dans `[0, 1]` sans y avoir la même
forme : l'une est un sigmoïde de logit, l'autre un score de pertinence natif. C'est pourquoi
un seuil ne se transporte pas d'un reranker à l'autre — et pourquoi les deux passes
ci-dessus ont chacune le leur.

## Le renversement entre le jeu de réglage et le jeu de mesure

Sur `questions_calibration.jsonl` (14 questions), la conclusion était **l'inverse** :

| | mmarco | Cohere |
|---|---|---|
| `couverte` | 0,053 – 0,993 | 0,617 – 0,952 |
| `hors_corpus` | 0,000 – 0,016 | 0,292 – 0,620 |
| populations séparables | **OUI** | **NON** — elles se chevauchent |
| refus corrects au seuil proposé | **8/8** | 7/8 |

Quatorze questions donnaient l'avantage au cross-encoder ; trente le donnent à Cohere. **Le
jeu de réglage ne prédit pas le résultat**, et c'est précisément pourquoi le protocole
interdit de calibrer sur le jeu de mesure. À garder en tête avant de lire le tableau
principal comme un verdict définitif : lui aussi tient sur huit questions `hors_corpus`.

## Réserves

- **huit questions par sous-ensemble.** Un refus qui bascule vaut 12,5 points. L'écart mesuré
  ici est de deux questions ;
- **`RAG-19` et `RAG-20` sont en tension avec le corpus** (§9). Une configuration qui les rate
  n'a pas régressé — et une qui y répond n'a pas forcément progressé ;
- **le service plafonne.** La passe Cohere a déclenché **six reprises sur 429** pour 30
  questions. Le quota du déploiement ne soutient pas une mesure enchaînée ; c'est sans effet
  sur les chiffres (la reprise ne change pas la réponse), mais la mesure est plus lente et
  dépend d'un service tiers, là où le cross-encoder ne dépend que de la machine ;
- **le classement n'a pas été mesuré là où Cohere pourrait gagner.** Ce jeu a un corpus où
  BM25 suffit à placer le bon document. Sur un corpus moins bien indexé lexicalement, l'écart
  se lirait peut-être sur le rang, pas sur le refus.

## Ce que la mesure ne dit pas, et qu'il faut décider ailleurs

Elle ne dit **pas** qu'il faut basculer. Le cross-encoder tourne dans le processus, sans
réseau, sans quota et sans coût par appel ; Cohere ajoute une dépendance de service pour
+2 refus corrects sur huit questions. Le rapport donne le chiffre — l'arbitrage tient compte
du reste, et il est écrit dans le journal de développement.
