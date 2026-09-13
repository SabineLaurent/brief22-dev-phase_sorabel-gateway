# Suite d'acceptance rejouée — local et conteneur

**Date** : 2026-09-13 · **Commit** : `343e23a` (branche `deploiement/azure-aca`)

## Résultat

**12/12 dans les deux configurations.** Aucun échec, aucun test ignoré.

| Suite | Local | Image `sorabel-app:test` |
|---|---|---|
| `test_rag.py` (E1, E2, E6) | 4 passed — 22,59 s | 4 passed — 10,31 s |
| `test_sql.py` (E3, E5) | 4 passed — 9,19 s | 4 passed — 9,51 s |
| `test_mcp.py` (E4, E5) | 4 passed — 14,79 s | 4 passed — 7,66 s |

Sorties `pytest -v` complètes : `local_*.txt` et `docker_*.txt`.

## Contre quoi le vert a été obtenu

Un « 12/12 » ne dit rien tant qu'on ignore quel index a été interrogé, avec quel modèle et
sous quel seuil. Chaque sortie porte donc en en-tête la configuration **réellement lue**,
extraite à l'exécution par `conftest.py` (racine) — aucun nom n'y est écrit à la main : les
modèles viennent du `.name` des fabriques que `search()` appelle, la collection et son
empreinte de l'objet Chroma que la recherche ouvre, les chemins de `config.settings`,
résolus en absolu.

```
                    local                                   conteneur
embedder   intfloat/multilingual-e5-base [local]     text-embedding-3-small [distant]
reranker   mmarco-mMiniLMv2-L12-H384-v1 [local]      Cohere-rerank-v4.0-pro [distant]
seuil      0.053 = calibré pour ce couple            0.6203 = calibré pour ce couple
vectoriel  localhost:8002 · sorabel_corpus           chroma:8002 · sorabel_corpus_azure_small
           400 éditions · empreinte e5-base =        400 éditions · empreinte 3-small =
lexical    data/bm25/sorabel_corpus.pkl              /app/data/bm25/…_azure_small.pkl
métier     …/data/sorabel.db (156 Kio)               /app/data/sorabel.db (156 Kio)
```

Trois appariements y sont lisibles d'un coup d'œil, et ce sont les trois qui rendraient un
vert mensonger s'ils étaient faux :

1. **index ↔ embedder** — l'empreinte inscrite dans la métadonnée de la collection à sa
   construction, comparée au modèle configuré. Déjà **fatale** dans le code
   (`_check_embedding_model`) ; l'en-tête la rend simplement lisible sans lire le code.
2. **seuil ↔ couple de modèles** — `CALIBRATED_THRESHOLDS` de `config.py`. C'est le seul
   des trois qu'aucune exception ne protège à l'exécution : un seuil étranger déplace la
   barrière de refus **en silence**, et 0,053 contre 0,6203 est plus d'un ordre de grandeur.
3. **quel fichier** — chemins résolus en absolu, parce que `.env` pose `SORABEL_DB` et
   `GATEWAY_JOURNAL` en **relatif** : « ça marche » tant que le répertoire courant vaut
   `/app`, donc par coïncidence.

L'en-tête décrit le processus pytest ; le serveur MCP que la suite lance est un
sous-processus qui hérite du même environnement (`tests/conftest.py`), donc de la même
configuration.

### Les témoins : ce que fait la suite quand la configuration est fausse

Quatre exécutions volontairement mal configurées, conservées telles quelles.

| Témoin | Ce qui est faussé | L'en-tête dit | La suite dit |
|---|---|---|---|
| `temoin_1_index_etranger.txt` | index `…azure_small` (3-small) lu par `e5-base` | `ILLISIBLE` + la raison | **1 failed en 0,84 s** |
| `temoin_2_seuil_etranger.txt` | `RERANK_THRESHOLD=0.6203` sur la cellule ① (12× trop haut) | `≠ CALIBRÉ POUR CE COUPLE (0.053)` | **4 passed** |
| `temoin_3_chroma_injoignable.txt` | `CHROMA_URL=http://localhost:9999` | `ILLISIBLE` + la raison | 3 failed, 1 passed |
| `temoin_4_seuil_etranger_conteneur.txt` | `RERANK_THRESHOLD=0.053` sur la cellule ④ (12× trop bas) | `≠ CALIBRÉ POUR CE COUPLE (0.6203)` | **4 passed** |

**T2 et T4 sont le résultat qui compte.** Le seuil de refus peut être faux d'un ordre de
grandeur, **dans les deux sens**, et la suite d'acceptance reste verte : l'en-tête est le
seul endroit où ça se voit. La raison est connue et écrite ailleurs — le refus servi tient
déjà par la **barrière 2**, la garde de suffisance du rédacteur, dont le code
`contexte_insuffisant` porte le même statut `hors_corpus` que le refus au seuil. Le test de
refus est donc satisfait des deux côtés de la barrière 1, et le test de réponse a une marge
confortable. La barrière 1 peut être déréglée sans qu'aucune assertion bouge.

Ce n'est pas un défaut de la suite : les 12 scénarios contrôlent un comportement servi, pas
un appariement de configuration. C'est exactement le trou que l'en-tête vient combler, et
c'est pourquoi il nomme le seuil calibré attendu plutôt que d'afficher le seuil seul.

**T1 et T3 tombent, mais pas pour la même raison** : T1 est *fatal par le code*
(`_check_embedding_model`), T3 ne fait qu'échouer faute d'index. Et dans T3, un test reste
vert — `test_gain_hybride_mesure_et_documente`, qui lit un rapport publié et ne touche ni
l'index ni la base. Un vert isolé ne prouve donc rien à lui seul, même quand rien ne marche.

## Les deux configurations ne sont pas le même décor

Ce sont **deux cellules de modèles** : celle qu'on sert en local (①) et celle qui est
déployée (④). Même code, mêmes 12 scénarios, chaînes de recherche différentes.

| | Local | Conteneur |
|---|---|---|
| Code | arbre de travail | cuit dans l'image (`COPY` nommés) |
| Python | 3.11.15, darwin, `.venv` | 3.11.16, linux, `/app/.venv`, `uv.lock --frozen` |
| Cellule | ① les deux modèles en mémoire | ④ les deux modèles distants |
| PyTorch | présent (extra `[vector]`) | **absent** — l'image ne peut servir que du distant |

L'écart de durée sur le RAG (22,6 s → 10,3 s) vient de là : chargement de deux modèles
contre deux appels réseau.

## Ce que ça prouve, et ce que ça ne prouve pas

Le conteneur rejoue le code de l'image déployée sur Azure Container Apps, ses dépendances
figées et son Chroma — pas l'arbre local monté dans un conteneur.

Ne sont **pas** couverts : l'architecture `linux/amd64` (l'image de contrôle est bâtie pour
l'hôte, cf. `DEP-01` de `docs/BUGS.md`), l'ingress et le réseau ACA, et l'image *servie*
elle-même (la cible `test` ajoute le groupe `dev` : 1,86 Go contre 304 Mo).

## Reproduire

```bash
# local — Chroma de dev requis (make up)
for d in rag sql mcp; do
  uv run pytest "tests/acceptance/test_${d}.py" -v --import-mode=importlib \
    > "docs/TESTS_ACCEPTANCE/local_${d}.txt" 2>&1
done

# conteneur — procédure détaillée : docs/2026-09-11-rapport-tests-txt.md
docker build --target test -t sorabel-app:test .
docker compose -f docker-compose.aca.yml -p sorabel-acatest up -d chroma
for d in rag sql mcp; do
  docker run --rm --network sorabel-acatest_default --env-file .env \
    -e CHROMA_URL=http://chroma:8002 \
    -e CHROMA_COLLECTION=sorabel_corpus_azure_small \
    -e AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    -e AZURE_RERANK_DEPLOYMENT=Cohere-rerank-v4.0-pro \
    -e RERANK_THRESHOLD=0.6203 \
    -e SORABEL_DB=/app/data/sorabel.db \
    -e GATEWAY_JOURNAL=/app/logs/journal.jsonl \
    sorabel-app:test \
    pytest "tests/acceptance/test_${d}.py" -v --import-mode=importlib \
    > "docs/TESTS_ACCEPTANCE/docker_${d}.txt" 2>&1
done
docker compose -f docker-compose.aca.yml -p sorabel-acatest down
```

`--import-mode=importlib` n'est pas décoratif : sans lui, la collecte meurt sur le paquet
`tests` que `literalai` installe à la racine de `site-packages`.
