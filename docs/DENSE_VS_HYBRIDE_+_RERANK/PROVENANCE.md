# Provenance de cette copie

Sorties de `make mesure` rejouées le **2026-09-13**, branche `deploiement/azure-aca`,
au commit `acfcac6`. Copie brute de `eval/rapport_gain.md` et des six CSV de
`eval/resultats/` — les originaux restent la source, ce dossier en est un instantané.

Configuration lue au moment du rejeu, vérifiée contre les défauts du code :
`search_top_k=5`, `search_pool=60`, `rerank_candidates=20`,
`max_candidates_per_title=3`, collection `sorabel_corpus` — **aucune surcharge**.
Embedder local `intfloat/multilingual-e5-base` (bascule Azure incomplète, repli
annoncé sur stderr). Seuil dense 0,8308, seuil hybride 0,0530.

## Ce rejeu ne reproduit pas la colonne A publiée

| | publié (09-09, commit `da305f7`) | rejoué (13-09) |
|---|---:|---:|
| A dense — Hit@1 référence | 1/8 | **3/8** |
| A dense — MRR | 0,271 | **0,542** |
| A dense — Recall@5 type | 9/13 | **12/13** |
| RAG simple — Hit@1 référence | 2/8 | **1/8** |
| B lexical, C hybride, axe 2 | — | **identiques à l'octet** |

Le gain E6 publié s'en trouve **réduit** : l'« avant » devient meilleur, 1/8 → 3/8.
Le sens de la conclusion ne bouge pas — C hybride reste 8/8, MRR 1,000.

## Ce qui a été écarté

- **Reproductibilité intra-session** : `make mesure-dense` joué deux fois de suite
  rend le CSV **identique à l'octet**. L'instabilité est entre sessions, pas dans la passe.
- **Intégrité de l'index** : `make check-index` au vert, décomptes en or tenus ;
  les trois collections portent 400 éditions et le bon `embedding_model`.
- **Configuration** : aucune valeur surchargée (tableau ci-dessus).
- **Code** : les deux seuls commits touchant la recherche depuis `da305f7`
  (`cc634ea` politique de candidats, `af41ea9` bascule embeddings) ne modifient pas
  le chemin dense — `_dense_search` n'utilise ni `search_pool` ni
  `max_candidates_per_title`, et `top_k` vaut toujours `settings.search_top_k`.

## Piste non conclue

`chroma.sqlite3` — les vecteurs et les documents — n'a pas bougé depuis le 08-09 20:08.
En revanche les segments HNSW (`data_level0.bin`, `header.bin`) des collections ont été
**réécrits le 13-09**, à 15:20 pour l'une et à 18:32 pour celle interrogée ici, soit
pendant ce rejeu ; le conteneur Chroma a redémarré il y a ~3 h.

**Déduit, pas vérifié** : la différence vient du côté Chroma — seul élément qui ait
changé — et plus probablement de l'état du graphe HNSW que du corpus ou du code.
La démonstration manque : il faudrait figer puis rejouer un graphe pour trancher.

Cohérent avec le précédent du 07-09, dont le journal dit la cause « non déterminable ».
C'est le même symptôme : **seule la colonne A bouge, B et C se rejouent identiques**,
le rerank absorbant une différence de vivier qui reste visible en dense seul.

## La contradiction rouverte

Vérifié : les lignes de données de `eval/resultats/mesure-emb-local-A.csv` et du
`mesure-dense.csv` **commité** sont identiques — même cellule, deux cibles. Republier
`mesure-dense` remet donc `rapport_gain.md` en désaccord avec `rapport_embeddings.md`,
qui annonce toujours 1/8, MRR 0,271, Recall 9/13 pour `e5` en dense seul.

**Non corrigé, et c'est un choix** : `make mesure-embeddings` appelle Azure, et la demande
portait sur `make mesure`. Les conclusions de `rapport_embeddings.md` tiennent — l'écart
entre embedders y est lu à index constant, dans la même session — mais les chiffres de sa
colonne ① sont à reprendre, comme ceux de `rapport_rerank.md` et
`rapport_local_vs_distant.md` depuis l'axe 8.
