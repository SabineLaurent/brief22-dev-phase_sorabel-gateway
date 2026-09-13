# Sorabel Data Gateway — cibles de développement
#
#   `make help` affiche cette liste dans le terminal, descriptions comprises.
#
#   1 · Mise en route ............ install · up · down · seed · ingest · reindex
#   2 · Qualité .................. test · fmt · lint
#   3 · Contrôles déterministes .. check-* — aucun appel de modèle, tous rejouables
#   4 · Faire tourner ............ serve · client · api · web · web-compare · journal
#   5 · Documentation générée .... doc-tools
#   6 · Réglages des mesures ..... les variables partagées des axes 6, 7 et 8
#   7 · Index témoins ............ ingest-brut · ingest-azure-small
#   8 · Calibration des seuils ... calibrer-*
#   9 · Mesures publiées ......... mesure-* · eval-sql — une cible par rapport
#  10 · Aide ..................... help
#
# Les sections 6 à 9 forment une chaîne : on pose un réglage, on construit l'index témoin
# s'il en faut un, on calibre SON seuil, puis on mesure. `eval/protocole-mesure.md` fixe
# ce qui varie et ce qui ne varie pas — et la règle « une cible Make par mesure publiée ».
#
# Les cibles qui APPELLENT UN MODÈLE, donc qui coûtent, portent un ✱ dans `make help` :
# tous les `calibrer-*` sur index Azure, `mesure-refus`, `mesure-acces`, `eval-sql`, et les
# `mesure-*` qui passent par Cohere ou les embeddings Azure. Les sections 2 à 5 n'en
# appellent aucun.

.PHONY: \
	install up down seed ingest reindex \
	test fmt lint \
	check-index check-perimetre check-rag-tools check-sql check-feedback check-client \
	check-contrat \
	serve client api web web-compare journal \
	doc-tools help \
	ingest-brut ingest-azure-small \
	calibrer calibrer-hybride calibrer-cohere calibrer-azure-small calibrer-distant \
	calibrer-candidats-c0 \
	mesure mesure-dense mesure-lexical mesure-hybride mesure-perimetre mesure-refus \
	mesure-acces mesure-sans-nettoyage mesure-sans-versions mesure-rag-simple \
	mesure-rerank mesure-embeddings mesure-distant mesure-candidats \
	mesure-candidats-profils eval-sql


# ============================================================ 1 · Mise en route ==========

install: ## Installer les dépendances (uv sync)
	uv sync

up: ## Démarrer Chroma — docker compose, port 8002
	docker compose up -d

down: ## Arrêter Chroma
	docker compose down

seed: ## Générer data/sorabel.db
	uv run python scripts/seed.py

ingest: ## Indexer le corpus dans Chroma — met l'index à jour
	uv run python -m packages.rag_machines.ingest.cli

reindex: ## Reconstruire la collection à neuf — modèle d'embeddings changé
	uv run python -m packages.rag_machines.ingest.cli --reset


# ================================================================ 2 · Qualité ============

test: ## Suite d'acceptance — les 12 scénarios
	uv run pytest --import-mode=importlib

fmt: ## Formater et corriger ce qui peut l'être (ruff)
	uv run ruff format .
	uv run ruff check --fix .

lint: ## ruff + mypy
	uv run ruff check .
	uv run mypy packages mcp_server


# =============================================== 3 · Contrôles déterministes =============
#
# Aucun appel de modèle, aucun aléa : ils se rejouent à volonté et doivent tous être au
# vert avant de journaliser une étape.

check-index: ## Intégrité de l'index documentaire
	uv run python -m packages.rag_machines.evals_and_controls.check_index

check-perimetre: ## Le filtre de périmètre — la matrice appliquée au corpus
	uv run python -m packages.rag_machines.evals_and_controls.check_perimeter

check-rag-tools: ## Les quatre tools RAG et leur journal
	uv run python -m packages.rag_machines.evals_and_controls.check_rag_tools

check-sql: ## Le Text-to-SQL — validation, exécution, bornes
	uv run python -m packages.text_to_sql_factory.evals_and_controls.check_sql

check-feedback: ## La réponse structurée et le journal, côté SQL
	uv run python -m packages.text_to_sql_factory.evals_and_controls.check_feedback

check-client: ## Le dernier mètre — substituer, compléter, ou renoncer
	uv run python -m packages.evals_and_controls.check_client

check-contrat: ## Le contrat publié, la frontière du serveur, les descriptions
	uv run python -m packages.evals_and_controls.check_mcp_contract


# ========================================================= 4 · Faire tourner =============

serve: ## Serveur MCP en stdio — profil dans SORABEL_PROFILE
	uv run python -m mcp_server.server

client: ## Client de test — le catalogue d'un profil (PROFILE=support)
	uv run python scripts/mcp_client.py --profile $${PROFILE:-support}

api: ## API du banc d'essai — uvicorn, port 8000
	uv run uvicorn packages.agent.api:app --reload

# Chainlit écoute sur 8000 par défaut, comme l'API ci-dessus : port explicite pour
# que `make api` et `make web` puissent tourner en même temps.
web: ## IGU mono-rôle — Chainlit, port 8100
	uv run chainlit run packages/web_client/app.py --port 8100

# Le second front : une question, quatre profils côte à côte. Port encore différent —
# les deux interfaces et l'API tournent ensemble, c'est le mode de démonstration.
#
# `CHAINLIT_APP_ROOT` n'est pas cosmétique : Chainlit efface `<root>/.files` à l'arrêt
# (`chainlit/server.py`), et deux fronts partageant un root partagent ce dossier — arrêter
# l'un fait échouer les éléments de l'autre, qui reste debout. Constaté au navigateur.
# C'est aussi ce qui donne à ce front sa propre configuration (`layout = "wide"`) et son
# propre `public/elements/`, sans rien changer au mono-rôle.
web-compare: ## IGU splittée — une question, quatre profils, port 8101
	CHAINLIT_APP_ROOT=packages/web_client/compare_root \
		uv run chainlit run packages/web_client/app_compare.py --port 8101

journal: ## Les 20 dernières entrées de logs/journal.jsonl
	@tail -n 20 logs/journal.jsonl 2>/dev/null || echo "journal vide"


# ================================================= 5 · Documentation générée =============

# La page du catalogue, générée depuis les cinq catalogues que le serveur rend vraiment.
# `initialize` et `tools/list`, plus deux appels de tools qui ne touchent que SQLite — la
# page montre leurs enveloppes réelles. Aucun appel de modèle, donc aucun coût : elle se
# rejoue à chaque changement de signature.
doc-tools: ## Régénérer le guide d'accès HTML depuis le serveur lui-même
	uv run python scripts/build_tool_docs.py


# ==================================================== 6 · Réglages des mesures ===========
#
# Toutes les variables des sections 7 à 9 sont ici, en un seul endroit : ce sont les
# boutons, et on les cherche avant de lancer une mesure, pas au milieu des cibles.
# Chacune se surcharge en ligne de commande — `make mesure-rerank SEUIL_COHERE=0.61`.

# — axe 6 du protocole : le modèle d'embeddings —
# Le drapeau `--embeddings` se pose par l'environnement, JAMAIS dans `.env` : y écrire
# AZURE_EMBEDDING_DEPLOYMENT basculerait aussi `make ingest`, donc l'index servi. Les deux
# collections coexistent, ce qui est la condition pour rejouer la comparaison dans les deux
# sens. Surcharger au besoin : `make ingest-azure-small EMB_AZURE=mon-deploiement`.
EMB_AZURE  ?= text-embedding-3-small
COLL_AZURE ?= sorabel_corpus_azure_small
AZURE_ENV   = CHROMA_COLLECTION=$(COLL_AZURE) AZURE_EMBEDDING_DEPLOYMENT=$(EMB_AZURE)

# — axe 7 du protocole : le reranker —
# La cible ne pose QUE le nom du déploiement : l'endpoint et la clé viennent de `.env`,
# où est leur place. C'est la règle tout ou rien qui rend ce partage sûr — deux variables
# sur trois ne basculent rien, donc `.env` peut les porter sans que la configuration
# servie change. Vider AZURE_RERANK_DEPLOYMENT dans `.env` : le défaut reste le
# cross-encoder local, et seules ces cibles-ci passent sur Cohere.
RERANK_COHERE ?= Cohere-rerank-v4.0-pro
COHERE_ENV     = AZURE_RERANK_DEPLOYMENT=$(RERANK_COHERE)

# Les deux rerankers côte à côte, index e5 constant. Chaque passe porte SON seuil
# calibré : comparer à seuil constant mesurerait le seuil, pas le reranker.
SEUIL_MMARCO ?= 0.0530
SEUIL_COHERE ?= 0.5923

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

# Axe 8 — la politique de candidats (2bis.1). Deux étages, et c'est UNE politique qui
# varie, pas deux drapeaux : le vivier et le plafond ne veulent rien dire l'un sans
# l'autre — un plafond sans vivier profond n'a rien à repêcher, un vivier profond sans
# plafond se laisse remplir par la même série. Même précédent que P0/P1 de l'axe 3.
#
# Un plafond supérieur à toute taille de vivier équivaut à « aucun plafond » : rien
# n'est différé, la liste ressort inchangée. C'est ainsi qu'on rejoue C0, une chaîne
# vide ne se parsant pas en None.
#
# Les deux cellules portent le MÊME seuil, et ce n'est pas un raccourci : la
# recalibration sous C1 repropose 0,0530, vérifié — cf. calibrer-candidats-c0 pour
# l'« avant ». Il n'y a donc aucun confondant de seuil dans cette comparaison.
POOL_C0 ?= 20
PLAFOND_C0 ?= 999
SEUIL_CANDIDATS ?= 0.0530


# ========================================================= 7 · Index témoins =============
#
# Des index parallèles au servi, construits pour une comparaison et conservés : refaire
# l'index à chaque sens de la comparaison la rendrait irrejouable.

ingest-brut: ## Index témoin — texte non nettoyé (axe 2)
	uv run python -m packages.rag_machines.ingest.cli --text raw --reset

ingest-azure-small: ## ✱ Index témoin — embeddings Azure (axe 6)
	$(AZURE_ENV) uv run python -m packages.rag_machines.ingest.cli --reset


# ================================================ 8 · Calibration des seuils =============
#
# Un seuil par cellule mesurée, jamais un seuil pour toutes : comparer deux
# configurations à seuil constant mesurerait le seuil.

calibrer: ## Le seuil de refus en dense seul (config A)
	uv run python -m packages.rag_machines.calibrate_threshold --config A

calibrer-hybride: ## Le seuil de refus en hybride + rerank (config C)
	uv run python -m packages.rag_machines.calibrate_threshold --config C

calibrer-cohere: ## ✱ Le seuil hybride sur l'échelle de Cohere (axe 7)
	$(COHERE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

calibrer-azure-small: ## ✱ Les deux seuils sur l'index Azure (axe 6)
	$(AZURE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config A
	$(AZURE_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

calibrer-distant: ## ✱ Le seuil de la cellule 4 — les deux modèles distants
	$(DISTANT_ENV) uv run python -m packages.rag_machines.calibrate_threshold --config C

# L'« avant » de la recalibration : le seuil que le jeu de calibration proposait sous
# l'ancienne politique. Il vaut 0,0530 comme sous la nouvelle — le seuil est stable, et
# c'est ce qui rend l'axe 8 lisible.
calibrer-candidats-c0: ## Le seuil sous l'ancienne politique de candidats (axe 8)
	SEARCH_POOL=$(POOL_C0) MAX_CANDIDATES_PER_TITLE=$(PLAFOND_C0) \
	  uv run python -m packages.rag_machines.calibrate_threshold --config C


# ===================================================== 9 · Mesures publiées ==============
#
# Une cible par rapport de `eval/`. Les trois premières sont les étages de recherche
# (A dense, B lexical, C hybride + rerank) ; viennent ensuite les axes du protocole.

# — les étages de recherche, et l'agrégat qui en fait le rapport de gain E6 —
mesure-dense: ## Étage A — dense seul
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text clean --version-filter on --out mesure-dense

mesure-lexical: ## Étage B — BM25 seul
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config B --text clean --version-filter on --out mesure-lexical

mesure-hybride: ## Étage C — hybride + rerank, la configuration servie
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text clean --version-filter on --out mesure-hybride

mesure-sans-nettoyage: ## Axe 2 — texte brut, à étage constant
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text raw --version-filter on --out mesure-sans-nettoyage

mesure-sans-versions: ## Axe 1 — sans le filtre de version
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config C --text clean --version-filter off --out mesure-sans-versions

mesure-rag-simple: ## Le RAG naïf, témoin bas de tous les axes
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text raw --version-filter off --out mesure-rag-simple

mesure: mesure-dense mesure-lexical mesure-hybride mesure-sans-nettoyage mesure-sans-versions mesure-rag-simple ## Les six passes ci-dessus, puis le rapport de gain E6
	uv run python -m packages.rag_machines.evals_and_controls.eval_rag --report

# — axe 3 : le périmètre documentaire —
mesure-perimetre: ## Axe 3 — filtrer avant ou après la troncature
	uv run python -m packages.rag_machines.evals_and_controls.eval_perimeter

# — axe 4 : le refus servi, sur les deux barrières —
# Trois passes, et c'est le prix de l'honnêteté : la barrière 2 est un jugement de modèle.
# Une passe publierait un chiffre sans dire s'il tient.
mesure-refus: ## ✱ Axe 4 — le refus servi sur les deux barrières, 3 passes
	uv run python -m packages.rag_machines.evals_and_controls.eval_refusal --passes 3

# — axe 5 : E5 chiffrée, étages d'arrêt, colonnes fermées, frontière du serveur —
mesure-acces: ## ✱ Axe 5 — E5 chiffrée, étages d'arrêt, frontière du serveur
	uv run python -m packages.evals_and_controls.eval_access

# — axe 6 : les deux embedders —
mesure-embeddings: ## ✱ Axe 6 — les deux embedders
	$(RERANK_LOCAL) REFUSAL_THRESHOLD=$(SEUIL_LOCAL_A) \
	  $(EVAL_RAG) --config A --out mesure-emb-local-A
	$(RERANK_LOCAL) RERANK_THRESHOLD=$(SEUIL_LOCAL_C) \
	  $(EVAL_RAG) --config C --out mesure-emb-local-C
	$(RERANK_LOCAL) $(AZURE_ENV) REFUSAL_THRESHOLD=$(SEUIL_AZURE_A) \
	  $(EVAL_RAG) --config A --out mesure-emb-azure-A
	$(RERANK_LOCAL) $(AZURE_ENV) RERANK_THRESHOLD=$(SEUIL_AZURE_C) \
	  $(EVAL_RAG) --config C --out mesure-emb-azure-C

# — axe 7 : les deux rerankers —
mesure-rerank: ## ✱ Axe 7 — les deux rerankers
	AZURE_RERANK_DEPLOYMENT= RERANK_THRESHOLD=$(SEUIL_MMARCO) \
	  uv run python -m packages.rag_machines.evals_and_controls.eval_rag \
	  --config C --text clean --version-filter on --out mesure-rerank-local
	$(COHERE_ENV) RERANK_THRESHOLD=$(SEUIL_COHERE) \
	  uv run python -m packages.rag_machines.evals_and_controls.eval_rag \
	  --config C --text clean --version-filter on --out mesure-rerank-cohere

# — la cellule 4 : les deux modèles en distant —
mesure-distant: ## ✱ Cellule 4 — les deux modèles en distant
	$(DISTANT_ENV) RERANK_THRESHOLD=$(SEUIL_DISTANT) \
	  $(EVAL_RAG) --config C --out mesure-emb-azure-C-cohere

# — axe 8 : la politique de candidats —
mesure-candidats: ## Axe 8 — la politique de candidats, C0 contre C1
	SEARCH_POOL=$(POOL_C0) MAX_CANDIDATES_PER_TITLE=$(PLAFOND_C0) RERANK_THRESHOLD=$(SEUIL_CANDIDATS) \
	  $(EVAL_RAG) --config C --out mesure-candidats-C0
	RERANK_THRESHOLD=$(SEUIL_CANDIDATS) \
	  $(EVAL_RAG) --config C --out mesure-candidats-C1

# Le même axe, mais là où le défaut vit : sur les profils. Le jeu d'évaluation est joué
# sans périmètre, donc dans les conditions de `commercial`, et aucune de ses cibles n'est
# une note interne — les six mesures publiées ne pouvaient pas voir 2bis.1.
mesure-candidats-profils: ## Axe 8 sur les profils, là où le défaut vit
	uv run python -m packages.rag_machines.evals_and_controls.eval_candidates

# — les 24 questions SQL, un appel de modèle chacune —
eval-sql: ## ✱ Les 24 questions SQL — un appel de modèle chacune
	uv run python -m packages.text_to_sql_factory.evals_and_controls.eval_sql


# ================================================================ 10 · Aide ==============

# Le sommaire, mais depuis le terminal. Il se lit dans ce fichier plutôt que dans une liste
# tenue à côté, qui divergerait. Une cible sans `##` n'apparaît pas : c'est le prix de la
# simplicité de l'awk, et la contrepartie est qu'ajouter une cible demande d'écrire sa
# description au même endroit, sur la même ligne.
help: ## Ce sommaire
	@echo "Sorabel Data Gateway — cibles disponibles.   ✱ = appelle un modèle, donc coûte"
	@awk 'BEGIN {FS = ":.*##"} \
		/^# =+ [0-9]+ · / { t = $$0; sub(/^# =+ /, "", t); sub(/ =+$$/, "", t); \
			printf "\n\033[1m%s\033[0m\n", t; next } \
		/^[a-z][a-z0-9-]*:.*##/ { printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2 } \
		' $(MAKEFILE_LIST)
	@echo ""
