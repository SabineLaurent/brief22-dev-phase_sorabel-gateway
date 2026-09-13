# Suite d'acceptance rejouée — local et conteneur

**Date** : 2026-09-13 · **Commit** : `343e23a` (branche `deploiement/azure-aca`, arbre propre)

## Résultat

**12/12 dans les deux configurations.** Aucun échec, aucun test ignoré.

| Suite | Local | Image `sorabel-app:test` |
|---|---|---|
| `test_rag.py` (E1, E2, E6) | 4 passed — 25,69 s | 4 passed — 8,86 s |
| `test_sql.py` (E3, E5) | 4 passed — 9,16 s | 4 passed — 9,51 s |
| `test_mcp.py` (E4, E5) | 4 passed — 14,56 s | 4 passed — 6,68 s |

Les fichiers de sortie `pytest -v` complets : `local_*.txt` et `docker_*.txt` dans ce dossier.

## Les deux configurations ne sont pas la même chose

Ce ne sont pas deux exécutions du même code dans deux décors : ce sont **deux cellules de
modèles différentes**, celle qu'on sert en local et celle qui est déployée.

| | Local | Conteneur |
|---|---|---|
| Code | arbre de travail | cuit dans l'image (`COPY` nommés du `Dockerfile`) |
| Python | 3.11.15 (darwin, `.venv`) | 3.11.16 (linux, `/app/.venv`, `uv.lock --frozen`) |
| Cellule | ① embedder `e5` local + reranker mmarco local | ④ `text-embedding-3-small` + `Cohere-rerank-v4.0-pro`, tous deux distants |
| Collection | `sorabel_corpus` (Chroma de `make up`, port 8002) | `sorabel_corpus_azure_small` (image `sorabel-chroma:local`, réseau isolé) |
| Seuil de refus | celui de `config.py` | `RERANK_THRESHOLD=0.6203`, calibré pour ④ |
| PyTorch | présent (extra `[vector]`) | **absent** — l'image ne peut servir que du distant |

L'écart de durée sur `test_rag.py` (25,7 s → 8,9 s) vient de là : en local le premier appel
charge deux modèles en mémoire, dans l'image les deux appels partent au réseau.

## Ce que ça prouve, et ce que ça ne prouve pas

Le conteneur rejoue **le code de l'image déployée sur Azure Container Apps**, ses dépendances
figées et son Chroma — pas l'arbre local monté dans un conteneur. Les 12 scénarios se
comportent donc de la même façon sur ACA.

Ne sont **pas** couverts : l'architecture `linux/amd64` (l'image de contrôle est bâtie pour
l'hôte — cf. `DEP-01` de `docs/BUGS.md`), l'ingress et le réseau ACA, et l'image *servie*
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
