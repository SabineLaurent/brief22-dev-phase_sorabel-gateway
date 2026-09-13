# Rapport — local ou distant : les quatre combinaisons

Ce rapport **assemble** les axes 6 et 7 et ajoute la combinaison que ni l'un ni l'autre ne
mesure. Le détail de chaque axe pris séparément vit dans
[`rapport_embeddings.md`](rapport_embeddings.md) et [`rapport_rerank.md`](rapport_rerank.md) ;
on ne répète ici que ce qui sert à **décider**.

Rejouable par `make mesure-embeddings`, `make mesure-rerank` et `make mesure-distant`.

## La question qui a ouvert le sujet n'était pas la qualité

Elle était l'**empreinte mémoire**. Mesuré sur la machine de développement, un serveur MCP
qui a répondu à une question documentaire occupe **~1 Go de RSS** : PyTorch, plus les poids
de `multilingual-e5-base` et du cross-encoder. Quatre profils chauds ≈ 2,8 Go, sans compter
l'API ni le front — au-delà de ce qu'un petit plan Azure offre.

**PyTorch ne disparaît que si les deux modèles partent en distant.** Basculer l'embedder seul
le garde (le cross-encoder en a besoin), et le reranker seul aussi (`e5` en a besoin). D'où
l'intérêt d'une quatrième cellule que les deux axes, pris séparément, ne produisent jamais.

## Les quatre combinaisons

Reranking et embedding sont les deux seuls étages commutables. Chaque cellule porte **son**
seuil, calibré pour elle sur `questions_calibration.jsonl` — comparer à seuil constant
mesurerait le seuil.

| # | embedder | reranker | PyTorch ? | seuil C | Hit@1 réf | MRR | Recall@5 | **refus corrects** | **faux refus** |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| ① | `e5` local | mmarco local | **oui** | 0,0530 | 8/8 | 1,000 | 12/13 | 5/8 | 1/22 |
| ② | `text-embedding-3-small` | mmarco local | oui | 0,0153 | 8/8 | 1,000 | 12/13 | 4/8 | 1/22 |
| ③ | `e5` local | `Cohere-rerank-v4.0-pro` | oui | 0,5923 | 8/8 | 1,000 | 12/13 | 7/8 | 0/22 |
| ④ | `text-embedding-3-small` | `Cohere-rerank-v4.0-pro` | **non** | 0,6203 | 8/8 | 1,000 | 12/13 | **8/8** | **0/22** |

① est la configuration servie, celle qui tient les chiffres publiés dans les cinq autres
rapports.

**Le classement est identique dans les quatre cellules** — Hit@1 8/8, MRR 1,000, Recall@5
12/13. Aucun des deux modèles distants ne change ce que la recherche trouve : ils ne changent
que **ce qu'elle refuse**.

## Ce que chaque cellule apprend

**② l'embedder ne se voit pas.** En configuration C, aucun rang ne change sur 38 lignes, et
le seul verdict qui bascule le fait sur un score **identique au dix-millième** — c'est le
seuil, pas la recherche. BM25 et le rerank absorbent entièrement la différence d'embedder.

**③ le reranker se voit, sur le refus seul.** +2 refus corrects, un rang changé sur 38.

**④ les deux effets s'additionnent, et dans le bon sens.** 8/8 en refus, 0 faux refus, sans
que rien ne se dégrade ailleurs. Ce n'était pas acquis : les deux effets portent sur un
seuil, et un seuil ne s'additionne pas — il fallait calibrer ④ pour elle-même, ce qu'aucune
des trois autres calibrations n'avait produit.

## Ce que le tableau ne montre pas, et qui compte autant

**Le refus servi est déjà de 8/8 en ①.** [`rapport_refus.md`](rapport_refus.md) le mesure sur
les **deux** barrières : le seuil (barrière 1) en tranche 5, et la garde de suffisance du
rédacteur (barrière 2) rattrape les 3 autres — `RAG-23`, `RAG-24`, `RAG-29`. Or `RAG-23` et
`RAG-29` sont exactement celles que Cohere ajoute à la barrière 1.

**Le gain de ④ n'est donc pas « refuser plus », c'est « refuser mieux »** :

| | ① | ④ |
|---|---|---|
| refus servi à l'utilisateur | 8/8 | 8/8 — identique |
| combien tranchés **sans appeler le modèle** | 5 | **8** |
| nature de la décision | 3 refus par **jugement de modèle** | tout **déterministe** |
| faux refus à la barrière 1 | 1 (`RAG-19`) | 0 |

Un refus à la barrière 1 est **reproductible**, **gratuit en tokens** et **stable au journal**
(`hors_corpus` plutôt que `contexte_insuffisant`). C'est un gain d'E5 et de latence, pas un
gain visible à l'écran.

## Le coût de ④, qui n'est pas dans les métriques

- **une dépendance de service.** Foundry indisponible ⇒ recherche documentaire morte. En ①,
  seule la machine est nécessaire ;
- **un quota qui plafonne déjà** : **quatre reprises sur 429** pour 30 questions
  *séquentielles*. Le comparateur interroge quatre profils **en parallèle** — c'est le pire
  cas pour un quota, et une démonstration qui bégaie est pire qu'une démonstration lente ;
- **un coût par appel**, là où le local ne coûte que de la RAM ;
- **la republication des rapports** si la configuration servie change : les cinq autres
  décrivent ①.

## Décision proposée

**Servir ① en local, déployer ④.** Les deux sont mesurées, aucune n'est un pari :

- la machine de développement et les mesures publiées restent sur ①, donc rien à republier ;
- l'image déployée porte les quatre variables `AZURE_*`, donc **pas de PyTorch** — l'empreinte
  passe de ~1 Go à ~150 Mo par processus, et les quatre colonnes du comparateur tiennent ;
- ce que le déploiement sert est **au moins aussi bon** que ce que la mesure publie : même
  classement, refus au moins égal, zéro faux refus.

C'est la seule configuration qui répond à la contrainte matérielle **sans concession mesurée**
sur la qualité. Ce qu'elle concède est ailleurs : la disponibilité et le quota.

## Réserves

- **huit questions `hors_corpus`, vingt-deux à cible.** Un refus qui bascule vaut 12,5 points ;
- **la barrière 2 n'est pas mesurée ici.** `eval_rag` s'arrête à la barrière 1 ; l'effet de ④
  sur le refus *servi* est déduit de [`rapport_refus.md`](rapport_refus.md), pas remesuré ;
- **les seuils de ③ et ④ sont réglés sur un jeu qui ne contient aucune référence produit**
  (voir [`rapport_embeddings.md`](rapport_embeddings.md)), donc sur de la prose seule ;
- **`RAG-19` reste en tension avec le corpus** (`protocole-mesure.md` §9) : ne pas lire sa
  disparition des faux refus comme un gain franc.
