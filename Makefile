.PHONY: install up down seed ingest ingest-brut reindex check-index check-perimetre calibrer calibrer-hybride \
	mesure-dense mesure-lexical mesure-hybride mesure-perimetre mesure-refus mesure-acces mesure-sans-nettoyage mesure-sans-versions \
	mesure-rag-simple mesure check-rag-tools check-sql check-feedback check-contrat check-client eval-sql test fmt lint serve client \
	ingest-azure-small calibrer-azure-small calibrer-cohere mesure-rerank mesure-embeddings calibrer-distant mesure-distant \
	journal api web web-compare

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

# — axe 6 du protocole : le modèle d'embeddings —
# Le drapeau `--embeddings` se pose par l'environnement, JAMAIS dans `.env` : y écrire
# AZURE_EMBEDDING_DEPLOYMENT basculerait aussi `make ingest`, donc l'index servi. Les deux
# collections coexistent, ce qui est la condition pour rejouer la comparaison dans les deux
# sens. Surcharger au besoin : `make ingest-azure-small EMB_AZURE=mon-deploiement`.
EMB_AZURE  ?= text-embedding-3-small
COLL_AZURE ?= sorabel_corpus_azure_small
AZURE_ENV   = CHROMA_COLLECTION=$(COLL_AZURE) AZURE_EMBEDDING_DEPLOYMENT=$(EMB_AZURE)

ingest-azure-small:
	$(AZURE_ENV) uv run python -m packages.rag_machines.ingest.cli --reset

# — axe 7 du protocole : le reranker —
# La cible ne pose QUE le nom du déploiement : l'endpoint et la clé viennent de `.env`,
# où est leur place. C'est la règle tout ou rien qui rend ce partage sûr — deux variables
# sur trois ne basculent rien, donc `.env` peut les porter sans que la configuration
# servie change. Vider AZURE_RERANK_DEPLOYMENT dans `.env` : le défaut reste le
# cross-encoder local, et seules ces cibles-ci passent sur Cohere.
RERANK_COHERE ?= Cohere-rerank-v4.0-pro
COHERE_ENV     = AZURE_RERANK_DEPLOYMENT=$(RERANK_COHERE)

calibrer-cohere:
	$(COHERE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

# Les deux rerankers côte à côte, index e5 constant. Chaque passe porte SON seuil
# calibré : comparer à seuil constant mesurerait le seuil, pas le reranker.
SEUIL_MMARCO ?= 0.0530
SEUIL_COHERE ?= 0.5923

mesure-rerank:
	AZURE_RERANK_DEPLOYMENT= RERANK_THRESHOLD=$(SEUIL_MMARCO) \
	  uv run python -m packages.rag_machines.evals_and_controls.eval_rag \
	  --config C --text clean --version-filter on --out mesure-rerank-local
	$(COHERE_ENV) RERANK_THRESHOLD=$(SEUIL_COHERE) \
	  uv run python -m packages.rag_machines.evals_and_controls.eval_rag \
	  --config C --text clean --version-filter on --out mesure-rerank-cohere

calibrer-azure-small:
	$(AZURE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config A
	$(AZURE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

# Les deux embedders côte à côte, reranker local des DEUX côtés — sans quoi l'axe 6 et
# l'axe 7 se mélangeraient. A isole l'embedder (pas de BM25 pour le sauver), C dit ce que
# le produit servi y gagne. Chaque passe porte SES seuils calibrés : comparer à seuil
# constant mesurerait le seuil.
SEUIL_LOCAL_A ?= 0.8308
SEUIL_LOCAL_C ?= 0.0530
SEUIL_AZURE_A ?= 0.4893
SEUIL_AZURE_C ?= 0.0153
RERANK_LOCAL   = AZURE_RERANK_DEPLOYMENT=
EVAL_RAG       = uv run python -m packages.rag_machines.evals_and_controls.eval_rag \
                 --text clean --version-filter on

# La cellule 4 : les DEUX modèles en distant. C'est la seule combinaison qui retire
# PyTorch du processus, donc la seule qui réponde à la contrainte de déploiement — et
# elle ne se déduit pas des axes 6 et 7, les deux effets portant sur un seuil qu'il faut
# calibrer pour elle.
SEUIL_DISTANT ?= 0.6203
DISTANT_ENV    = $(AZURE_ENV) $(COHERE_ENV)

calibrer-distant:
	$(DISTANT_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

mesure-distant:
	$(DISTANT_ENV) RERANK_THRESHOLD=$(SEUIL_DISTANT) \
	  $(EVAL_RAG) --config C --out mesure-emb-azure-C-cohere

mesure-embeddings:
	$(RERANK_LOCAL) REFUSAL_THRESHOLD=$(SEUIL_LOCAL_A) \
	  $(EVAL_RAG) --config A --out mesure-emb-local-A
	$(RERANK_LOCAL) RERANK_THRESHOLD=$(SEUIL_LOCAL_C) \
	  $(EVAL_RAG) --config C --out mesure-emb-local-C
	$(RERANK_LOCAL) $(AZURE_ENV) REFUSAL_THRESHOLD=$(SEUIL_AZURE_A) \
	  $(EVAL_RAG) --config A --out mesure-emb-azure-A
	$(RERANK_LOCAL) $(AZURE_ENV) RERANK_THRESHOLD=$(SEUIL_AZURE_C) \
	  $(EVAL_RAG) --config C --out mesure-emb-azure-C

mesure-dense:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text clean --version-filter on --out mesure-dense

mesure-lexical:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config B --text clean --version-filter on --out mesure-lexical

mesure-hybride:
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text clean --version-filter on --out mesure-hybride

mesure-perimetre:
	uv run python -m packages.rag_machines.evals_and_controls.eval_perimeter

# Trois passes, et c'est le prix de l'honnêteté : la barrière 2 est un jugement de modèle.
# Une passe publierait un chiffre sans dire s'il tient.
mesure-refus:
	uv run python -m packages.rag_machines.evals_and_controls.eval_refusal --passes 3

mesure-acces:
	uv run python -m packages.evals_and_controls.eval_access

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

check-client:
	uv run python -m packages.evals_and_controls.check_client

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

# Le second front : une question, quatre profils côte à côte. Port encore différent —
# les deux interfaces et l'API tournent ensemble, c'est le mode de démonstration.
#
# `CHAINLIT_APP_ROOT` n'est pas cosmétique : Chainlit efface `<root>/.files` à l'arrêt
# (`chainlit/server.py`), et deux fronts partageant un root partagent ce dossier — arrêter
# l'un fait échouer les éléments de l'autre, qui reste debout. Constaté au navigateur.
# C'est aussi ce qui donne à ce front sa propre configuration (`layout = "wide"`) et son
# propre `public/elements/`, sans rien changer au mono-rôle.
web-compare:
	CHAINLIT_APP_ROOT=packages/web_client/compare_root \
		uv run chainlit run packages/web_client/app_compare.py --port 8101

check-contrat:
	uv run python -m packages.evals_and_controls.check_mcp_contract
