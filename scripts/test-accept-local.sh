#!/usr/bin/env bash
# Rejoue les 3 suites d'acceptance (rag, sql, mcp) en local, avec le venv de dev.
#
# Prérequis : `make up` (Chroma de dev sur localhost:8002) et `make seed`
# (data/sorabel.db). Voir docs/2026-09-11-rapport-tests-txt.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

RAPPORTS=docs/tests-acceptance-rapports
mkdir -p "$RAPPORTS"

if ! curl -sS -o /dev/null --max-time 3 http://localhost:8002/api/v2/heartbeat; then
  echo "Chroma injoignable sur localhost:8002 — lancer \`make up\` d'abord." >&2
  exit 1
fi

statut_global=0

# RAG : la configuration réellement chargée (repli local si Azure n'est pas
# posé aux trois variables) au-dessus de la sortie pytest.
{
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
  uv run pytest tests/acceptance/test_rag.py -v --import-mode=importlib
} > "$RAPPORTS/cr_test_accept_rag.txt" 2>&1 || statut_global=1

# SQL : le chemin de la base réellement lue au-dessus de la sortie pytest.
{
  echo "base de données (settings.sorabel_db) : $(uv run python -c 'from config import settings; print(settings.sorabel_db)')"
  echo
  uv run pytest tests/acceptance/test_sql.py -v --import-mode=importlib
} > "$RAPPORTS/cr_test_accept_sql.txt" 2>&1 || statut_global=1

# MCP : rien à consigner en tête, la matrice et le journal sont dans le contenu du test.
uv run pytest tests/acceptance/test_mcp.py -v --import-mode=importlib \
  > "$RAPPORTS/cr_test_accept_mcp.txt" 2>&1 || statut_global=1

echo "Rapports écrits dans $RAPPORTS/cr_test_accept_{rag,sql,mcp}.txt"
exit "$statut_global"
