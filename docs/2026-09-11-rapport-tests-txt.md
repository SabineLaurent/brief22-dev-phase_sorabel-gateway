# Rapport de tests en .txt

Générer un rapport de la suite d'acceptance dans un fichier texte, sans dépendance
ajoutée (redirection de la sortie de pytest). Un fichier par domaine, dans
`docs/tests-acceptance-rapports/` :

```bash
mkdir -p docs/tests-acceptance-rapports
uv run pytest tests/acceptance/test_rag.py -v --import-mode=importlib \
  > docs/tests-acceptance-rapports/cr_test_accept_rag.txt 2>&1
uv run pytest tests/acceptance/test_sql.py -v --import-mode=importlib \
  > docs/tests-acceptance-rapports/cr_test_accept_sql.txt 2>&1
uv run pytest tests/acceptance/test_mcp.py -v --import-mode=importlib \
  > docs/tests-acceptance-rapports/cr_test_accept_mcp.txt 2>&1
```

Le drapeau `--import-mode=importlib` est nécessaire : sans lui, la collecte échoue sur
`ModuleNotFoundError: No module named 'tests.conftest'` (collision avec le paquet `tests`
installé par `literalai`, dépendance de `chainlit`).

## Avec la configuration RAG (embeddings, reranker, seuils)

Spécifique au domaine RAG (SQL et MCP n'ont pas d'embedder ni de reranker). Pour que le
rapport consigne aussi le modèle d'embeddings, le reranker et les deux seuils réellement
utilisés au moment du run — interrogés sur le code, pas rappelés de mémoire :

```bash
{
  echo "# Rapport de tests d'acceptance — $(date +%Y-%m-%d)"
  echo
  echo "## Configuration RAG au moment du test"
  echo '```'
  uv run python -c "
from config import settings
from packages.rag_machines.retrieval.embedder import build_embedder
from packages.rag_machines.retrieval.reranker import build_reranker
from packages.rag_machines.tools import threshold_for

embedder = build_embedder(settings)
reranker = build_reranker(settings)
print('embedding model  :', embedder.name)
print('reranker model   :', reranker.name)
print('seuil dense (refus)    :', threshold_for('dense', settings))
print('seuil hybride (rerank) :', threshold_for('hybrid', settings))
"
  echo '```'
  echo
  echo "## Sortie pytest — tests/acceptance/test_rag.py"
  echo '```'
  uv run pytest tests/acceptance/test_rag.py -v --import-mode=importlib
  echo '```'
} > docs/tests-acceptance-rapports/cr_test_accept_rag.txt 2>&1
```

`build_embedder()` / `build_reranker()` appliquent la même bascule tout-ou-rien que le
serveur (Azure si les trois variables sont posées, sinon repli local) : le rapport reflète
donc le modèle réellement chargé, pas un défaut statique de `config.py`.

## Avec le chemin de la base (SQL)

Spécifique au domaine SQL : consigner le chemin de `data/sorabel.db` réellement lu
(`settings.sorabel_db`, résolu depuis `REPO_ROOT`, pas rappelé de mémoire) avant la
sortie pytest :

```bash
{
  echo "base de données (settings.sorabel_db) : $(uv run python -c 'from config import settings; print(settings.sorabel_db)')"
  echo
  uv run pytest tests/acceptance/test_sql.py -v --import-mode=importlib
} > docs/tests-acceptance-rapports/cr_test_accept_sql.txt 2>&1
```

## Dans l'image Docker de prod (suffixe `_img_prod`)

Pas contre le code local : contre celui **cuit dans l'image** qui tourne sur ACA. La suite
d'acceptance lance elle-même `python -m mcp_server.server` (`tests/conftest.py`), donc pour
tester l'image il faut exécuter pytest **depuis l'intérieur** d'un conteneur bâti sur cette
image, contre le Chroma de la cellule ④ déployée (embeddings + reranker Azure) — pas
contre celui de dev.

Le `Dockerfile` a une cible `test` prévue pour ça (`FROM base AS test`, §cible de contrôle) :
même code que l'image servie, plus `pytest`.

```bash
# 1. l'image de contrôle (code + pytest)
docker build --target test -t sorabel-app:test .

# 2. le Chroma de la cellule ④ (index cuit dans Dockerfile.chroma), sur un réseau isolé
#    du Chroma de dev (make up) — nom de projet dédié pour ne rien croiser
docker compose -f docker-compose.aca.yml -p sorabel-acatest up -d chroma
# attendre "healthy" :
docker inspect --format '{{.State.Health.Status}}' sorabel-acatest-chroma-1

# 3. les trois suites, une à la fois, avec les variables de la cellule ④
#    (mêmes que le service `gateway` de docker-compose.aca.yml)
for domaine in rag sql mcp; do
  docker run --rm \
    --network sorabel-acatest_default \
    --env-file .env \
    -e CHROMA_URL=http://chroma:8002 \
    -e CHROMA_COLLECTION=sorabel_corpus_azure_small \
    -e AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    -e AZURE_RERANK_DEPLOYMENT=Cohere-rerank-v4.0-pro \
    -e RERANK_THRESHOLD=0.6203 \
    -e SORABEL_DB=/app/data/sorabel.db \
    -e GATEWAY_JOURNAL=/app/logs/journal.jsonl \
    sorabel-app:test \
    pytest "tests/acceptance/test_${domaine}.py" -v --import-mode=importlib \
    > "docs/tests-acceptance-rapports/cr_test_accept_${domaine}_img_prod.txt" 2>&1
done

# 4. nettoyage — ne touche pas au Chroma de dev (autre nom de projet)
docker compose -f docker-compose.aca.yml -p sorabel-acatest down
```

**Prérequis** : `.docker-data/chroma` doit porter la collection `sorabel_corpus_azure_small`
(`make ingest-azure-small`) — gitignoré, donc absent d'un clone propre. `sorabel-app:test`
n'embarque pas de secrets : `--env-file .env` les fournit à l'exécution, comme le fait déjà
`docker-compose.aca.yml` pour le service `gateway`.

**Ce que ça prouve, et ce que ça ne prouve pas** : même code, mêmes dépendances figées
(`uv.lock`), même Chroma que la cellule servie → si les 12 tests passent ici, l'image qui
tourne sur ACA se comporte de la même façon sur ces 12 scénarios. Ça ne couvre pas
l'architecture (`--platform linux/amd64`, cf. `DEP-01`), ni le réseau ACA lui-même (ingress,
sidecar) — seulement le code et ses dépendances.
