.PHONY: install up down seed ingest ingest-brut reindex check-index check-perimetre calibrer calibrer-hybride \
	mesure-dense mesure-lexical mesure-hybride mesure-perimetre mesure-sans-nettoyage mesure-sans-versions \
	mesure-rag-simple mesure check-rag-tools check-sql check-feedback eval-sql test fmt lint serve client \
	journal api web

install:
	uv sync

seed:
	uv run python scripts/seed.py

up:
	docker compose up -d

ingest:
	uv run python -m packages.rag_machines.ingest.cli

ingest-brut:
	uv run python -m packages.rag_machines.ingest.cli --text raw --reset

reindex:
	uv run python -m packages.rag_machines.ingest.cli --reset

check-index:
	uv run python -m packages.rag_machines.evals_and_controls.check_index

check-perimetre:
	uv run python -m packages.rag_machines.evals_and_controls.check_perimeter

calibrer:
	uv run python -m packages.rag_machines.calibrate_threshold --config A

calibrer-hybride:
	uv run python -m packages.rag_machines.calibrate_threshold --config C

mesure-dense:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text clean --version-filter on --out mesure-dense

mesure-lexical:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config B --text clean --version-filter on --out mesure-lexical

mesure-hybride:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text clean --version-filter on --out mesure-hybride

mesure-perimetre:
	uv run python -m packages.rag_machines.evals_and_controls.eval_perimeter

mesure-sans-nettoyage:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text raw --version-filter on --out mesure-sans-nettoyage

mesure-sans-versions:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text clean --version-filter off --out mesure-sans-versions

mesure-rag-simple:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text raw --version-filter off --out mesure-rag-simple

mesure: mesure-dense mesure-lexical mesure-hybride mesure-sans-nettoyage mesure-sans-versions mesure-rag-simple
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --report

check-rag-tools:
	uv run python -m packages.rag_machines.evals_and_controls.check_rag_tools

check-sql:
	uv run python -m packages.text_to_sql_factory.evals_and_controls.check_sql

check-feedback:
	uv run python -m packages.text_to_sql_factory.evals_and_controls.check_feedback

eval-sql:
	uv run python -m packages.text_to_sql_factory.evals_and_controls.eval_sql

down:
	docker compose down

test:
	uv run pytest --import-mode=importlib

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run mypy packages mcp_server

serve:
	uv run python -m mcp_server.server

client:
	uv run python scripts/mcp_client.py --profile $${PROFILE:-support}

journal:
	@tail -n 20 logs/journal.jsonl 2>/dev/null || echo "journal vide"

api:
	uv run uvicorn packages.agent.api:app --reload

# Chainlit écoute sur 8000 par défaut, comme l'API ci-dessus : port explicite pour
# que `make api` et `make web` puissent tourner en même temps.
web:
	uv run chainlit run packages/web_client/app.py --port 8100
