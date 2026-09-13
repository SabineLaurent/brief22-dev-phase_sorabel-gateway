#!/usr/bin/env bash
# Rejoue les 3 suites d'acceptance depuis l'image Docker de prod (cellule ④ :
# embeddings + reranker Azure), dans un conteneur bâti sur `sorabel-app:test`
# (cible `test` du Dockerfile — même code que l'image servie, plus pytest).
#
# La suite lance elle-même `python -m mcp_server.server` (tests/conftest.py) :
# tester l'image exige donc de jouer pytest DEPUIS L'INTÉRIEUR d'un conteneur
# bâti sur elle, pas de l'appeler depuis le poste. Réseau isolé du Chroma de
# dev (`make up`), rien n'y est touché. Voir docs/2026-09-11-rapport-tests-txt.md.
#
# Prérequis : .docker-data/chroma porte la collection sorabel_corpus_azure_small
# (`make ingest-azure-small`) — gitignoré, absent d'un clone propre.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

RAPPORTS=docs/tests-acceptance-rapports
PROJET=sorabel-acatest
mkdir -p "$RAPPORTS"

nettoyer() {
  docker compose -f docker-compose.aca.yml -p "$PROJET" down
}
trap nettoyer EXIT

docker build --target test -t sorabel-app:test .
docker compose -f docker-compose.aca.yml -p "$PROJET" build chroma
docker compose -f docker-compose.aca.yml -p "$PROJET" up -d chroma

sain=""
for _ in $(seq 1 12); do
  etat=$(docker inspect --format '{{.State.Health.Status}}' "${PROJET}-chroma-1" 2>/dev/null || true)
  if [ "$etat" = "healthy" ]; then
    sain=1
    break
  fi
  sleep 2
done
if [ -z "$sain" ]; then
  echo "Chroma (${PROJET}-chroma-1) jamais sain — abandon." >&2
  exit 1
fi

# Communes aux deux docker run par domaine (config + pytest) : posées une fois,
# jamais répétées à la main — le risque sinon est que les deux appels divergent.
DOCKER_ENV=(
  --env-file .env
  -e CHROMA_URL=http://chroma:8002
  -e CHROMA_COLLECTION=sorabel_corpus_azure_small
  -e AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small
  -e AZURE_RERANK_DEPLOYMENT=Cohere-rerank-v4.0-pro
  -e RERANK_THRESHOLD=0.6203
  -e SORABEL_DB=/app/data/sorabel.db
  -e GATEWAY_JOURNAL=/app/logs/journal.jsonl
)

statut_global=0
for domaine in rag sql mcp; do
  fichier="$RAPPORTS/cr_test_accept_${domaine}_img_prod.txt"

  echo "image testée : sorabel-app:test (cible \`test\` du Dockerfile, même code que l'image servie sorabel-app:v1 + pytest)" > "$fichier"

  # En-tête : la configuration MESURÉE dans le conteneur (pas rappelée de mémoire
  # ni recopiée d'une doc) — build_embedder()/build_reranker()/threshold_for()
  # sont les mêmes fonctions que le serveur appelle, interrogées à l'exécution.
  case "$domaine" in
    rag)
      echo "chroma : sorabel-chroma:local (cellule ④, index cuit dans l'image)" >> "$fichier"
      docker run --rm --network "${PROJET}_default" "${DOCKER_ENV[@]}" sorabel-app:test \
        python -c "
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
" >> "$fichier" 2>&1
      ;;
    sql)
      docker run --rm --network "${PROJET}_default" "${DOCKER_ENV[@]}" sorabel-app:test \
        python -c "
from config import settings
print('base de données (settings.sorabel_db) :', settings.sorabel_db)
" >> "$fichier" 2>&1
      ;;
    mcp)
      echo "chroma : sorabel-chroma:local (cellule ④)" >> "$fichier"
      ;;
  esac
  echo >> "$fichier"

  docker run --rm --network "${PROJET}_default" "${DOCKER_ENV[@]}" sorabel-app:test \
    pytest "tests/acceptance/test_${domaine}.py" -v --import-mode=importlib \
    >> "$fichier" 2>&1 || statut_global=1
done

echo "Rapports écrits dans $RAPPORTS/cr_test_accept_{rag,sql,mcp}_img_prod.txt"
exit "$statut_global"
