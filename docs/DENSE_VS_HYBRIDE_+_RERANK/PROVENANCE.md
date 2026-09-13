# Provenance de cette copie

Sorties de `make mesure` jouées le **2026-09-13** sous le profil **`support`**, branche
`deploiement/azure-aca`. Copie brute de `eval/rapport_gain.md` et des six CSV de
`eval/resultats/` — les originaux restent la source, ce dossier en est un instantané.

Configuration lue au moment du rejeu, vérifiée contre les défauts du code :
`search_top_k=5`, `search_pool=60`, `rerank_candidates=20`,
`max_candidates_per_title=3`, collection `sorabel_corpus` — **aucune surcharge**.
Embedder local `intfloat/multilingual-e5-base` et reranker cross-encoder local
`mmarco-mMiniLMv2-L12-H384-v1` (les deux bascules Azure incomplètes, repli annoncé sur
stderr). Seuil dense 0,8308, seuil hybride 0,0530.

## Le profil est désormais une condition de mesure, pas une étiquette

Jusqu'à ce lot, `eval_rag.py` n'appliquait **aucun** périmètre documentaire et le rapport
annonçait pourtant « profil `commercial` » : une prose, pas un paramètre. La mesure portait
donc sur les 400 éditions, ni le périmètre de `commercial` ni celui de `support`.

`eval_rag` prend maintenant `--profile`, **défaut `support`** — celui que
`docs/cadrage_dsi.md` §5 fixe pour `SORABEL_PROFILE`, et celui que servent déjà
`mcp_server/server.py`, `scripts/mcp_client.py`, `packages/agent/cli.py` et `make client`.
Le périmètre est résolu par `perimeter_for()`, la fonction qu'appellent les tools servis —
pas une seconde implémentation. Il est écrit dans l'en-tête de chaque CSV
(`profile=support`), et le rapport l'y relit au lieu de le répéter de mémoire.

Un profil sans périmètre (`default`) **arrête la mesure** au lieu de la jouer : mesurer
sans périmètre publierait les chiffres du corpus entier sous un nom de profil, ce qui est
précisément l'écart que ce lot ferme.

## Ce que le passage à `support` déplace

| | sans périmètre | sous `support` |
|---|---:|---:|
| A dense — Hit@1 référence | 3/8 | 3/8 |
| A dense — MRR | 0,542 | **0,562** |
| B lexical — Hit@1 référence | 3/8 | **5/8** |
| B lexical — MRR | 0,688 | **0,812** |
| C hybride | 8/8 · MRR 1,000 | **inchangé** |
| Recall@5 type (A · B · C) | 12/13 · 11/13 · 12/13 | **inchangés** |

**C'est B qui bouge le plus**, et c'est cohérent : restreindre le périmètre retire des
concurrents du classement BM25 sans rien apporter au bon document. Le gain E6 se lit donc
sur un « avant » plus fort — 3/8 en dense, 5/8 en lexical, contre **8/8** en hybride.

## Réserve, nommée dans le rapport

**Les seuils de refus n'ont pas été recalibrés sous `support`.** `make calibrer` et
`make calibrer-hybride` ne prennent pas de profil, et le protocole (§1) interdit de
comparer deux configurations à seuil constant quand l'échelle bouge. La colonne
« refus corrects » est un indicatif ; les lignes de rang, elles, ne dépendent d'aucun seuil.

## L'instabilité de la colonne A, constatée le même jour

Le rejeu *sans périmètre* joué plus tôt ne reproduisait pas la colonne A publiée le 09-09
(1/8 → 3/8, MRR 0,271 → 0,542, Recall 9/13 → 12/13), tandis que B, C et l'axe 2 se
rejouaient à l'octet. Écarté, vérifié : la passe est stable dans la session
(`make mesure-dense` joué deux fois rend un CSV identique), `make check-index` est au vert,
aucune surcharge de configuration, et le chemin dense n'a pas changé depuis `da305f7`.

**Déduit, pas vérifié** : la différence vient du côté Chroma — `chroma.sqlite3` n'a pas
bougé depuis le 08-09, mais les segments HNSW ont été réécrits le 13-09 et le conteneur
avait redémarré. La démonstration manque. Voir l'entrée de journal du 2026-09-13 (soir).

## La contradiction rouverte

Les lignes de données de `eval/resultats/mesure-emb-local-A.csv` et du `mesure-dense.csv`
commité avant ce lot sont identiques — même cellule, deux cibles. `rapport_embeddings.md`
annonce toujours 1/8, MRR 0,271, Recall 9/13 pour `e5` en dense seul, sur un corpus non
filtré. Ses conclusions tiennent, ses chiffres de colonne ① sont à reprendre — comme ceux
de `rapport_rerank.md` et `rapport_local_vs_distant.md` depuis l'axe 8, et désormais sous
le profil `support`.
