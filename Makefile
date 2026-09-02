.PHONY: install up down seed ingest ingest-brut reindex check-index calibrer calibrer-hybride \
	mesure-dense mesure-lexical mesure-hybride mesure-sans-nettoyage mesure-sans-versions \
	mesure-rag-simple mesure test fmt lint serve client journal

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
	uv run python scripts/calibrate_threshold.py --config A

calibrer-hybride:
	uv run python scripts/calibrate_threshold.py --config C

mesure-dense:
	uv run python scripts/eval_rag.py --config A --text clean --version-filter on --out mesure-dense

mesure-lexical:
	uv run python scripts/eval_rag.py --config B --text clean --version-filter on --out mesure-lexical

mesure-hybride:
	uv run python scripts/eval_rag.py --config C --text clean --version-filter on --out mesure-hybride

mesure-sans-nettoyage:
	uv run python scripts/eval_rag.py --config C --text raw --version-filter on --out mesure-sans-nettoyage

mesure-sans-versions:
	uv run python scripts/eval_rag.py --config C --text clean --version-filter off --out mesure-sans-versions

mesure-rag-simple:
	uv run python scripts/eval_rag.py --config A --text raw --version-filter off --out mesure-rag-simple

mesure: mesure-dense mesure-lexical mesure-hybride mesure-sans-nettoyage mesure-sans-versions mesure-rag-simple
	uv run python scripts/eval_rag.py --report

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
