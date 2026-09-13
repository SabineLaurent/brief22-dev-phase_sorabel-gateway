#!/usr/bin/env bash
# Rejoue eval/questions_rag.jsonl (30) et eval/questions_sql.jsonl (24) via
# l'agent conversationnel en local — même principe que
# scripts/test-accept-agent-local.sh, mais sur les jeux de questions complets
# plutôt que sur les 12 scénarios ponctuels. 54 questions, chacune avec au
# moins un appel LLM : compter plusieurs minutes.
#
# Prérequis : `make up` (Chroma de dev) et `make seed` (data/sorabel.db).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

API_URL="${API_URL:-http://127.0.0.1:8000}"
LOG_API=/tmp/sorabel-api-e2e-jsonl.log
LANCE_ICI=""
API_PID=""

api_prete() {
  curl -sS -o /dev/null --max-time 2 "$API_URL/roles" 2>/dev/null
}

arreter() {
  if [ -n "$LANCE_ICI" ] && [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap arreter EXIT

if api_prete; then
  echo "API déjà en écoute sur $API_URL — réutilisée, pas arrêtée en sortie."
else
  if ! curl -sS -o /dev/null --max-time 3 http://localhost:8002/api/v2/heartbeat; then
    echo "Chroma injoignable sur localhost:8002 — lancer \`make up\` d'abord." >&2
    exit 1
  fi
  uv run uvicorn packages.agent.api:app --host 127.0.0.1 --port 8000 \
    > "$LOG_API" 2>&1 &
  API_PID=$!
  LANCE_ICI=1
  sain=""
  for _ in $(seq 1 15); do
    if api_prete; then
      sain=1
      break
    fi
    sleep 1
  done
  if [ -z "$sain" ]; then
    echo "API jamais prête sur $API_URL — voir $LOG_API" >&2
    exit 1
  fi
fi

uv run python scripts/e2e_agent_jsonl.py
