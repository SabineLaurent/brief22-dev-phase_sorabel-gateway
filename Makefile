.PHONY: install up down seed ingest ingest-brut reindex check-index calibrer test fmt lint serve client journal

install:
	uv sync

seed:
	uv run python scripts/seed.py

up:
	docker compose up -d

ingest:
	uv run python -m ingest.cli

ingest-brut:
	uv run python -m ingest.cli --text raw --reset

reindex:
	uv run python -m ingest.cli --reset

check-index:
	uv run python scripts/check_index.py

calibrer:
	uv run python scripts/calibrate_threshold.py

down:
	docker compose down

test:
	uv run pytest

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run mypy ingest retrieval sql mcp_server

serve:
	uv run python -m mcp_server.server

client:
	uv run python scripts/mcp_client.py --profile $${PROFILE:-support}

journal:
	@tail -n 20 logs/journal.jsonl 2>/dev/null || echo "journal vide"
