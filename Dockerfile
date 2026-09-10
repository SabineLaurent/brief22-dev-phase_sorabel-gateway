# Image applicative de la gateway Sorabel — UNE image, DEUX commandes.
#
# `sorabel-web` (Chainlit) et `sorabel-gateway` (API + serveurs MCP) sortent de la même
# image, avec deux `CMD` différentes posées côté Container Apps. Un seul `uv.lock`, un seul
# push, et la garantie que le front et l'API viennent du MÊME COMMIT — ce qui compte d'autant
# plus que le contrat entre eux (`/roles`, `/chat`, `/journal`) est neuf. Deux images
# sépareraient les dépendances (le front n'a besoin que de `chainlit` + `httpx`) au prix de
# deux résolutions à tenir cohérentes : mauvais échange.
#
# PAS DE PYTORCH ICI, et c'est le point de la cellule ④. `uv sync` sans l'extra `[vector]`
# laisse `sentence-transformers` — et ses 505 Mo de `torch` — dehors. L'image sert donc
# forcément les modèles distants : un repli local lèverait un `ModuleNotFoundError`, ce qui
# est le comportement voulu (bruyant), et `_warn_partial` en dit la cause avant.

# ---------------------------------------------------------------- dépendances
FROM python:3.11-slim AS base

# `uv` pinné : une version flottante rendrait le build non reproductible, alors que
# `--frozen` sert précisément à figer la résolution.
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# `WORKDIR /app` + le dépôt copié en `/app` fait COÏNCIDER `REPO_ROOT` ET LE CWD, et c'est
# ce qui rend justes d'un coup `bm25_path()`, `gateway_journal`, `sorabel_db`, `matrix_path`,
# `schema_doc` et les fichiers d'éval. `uv sync` installe le projet en EDITABLE (vérifié),
# donc `config.py` reste à `/app/config.py` et `REPO_ROOT` vaut `/app` — un projet installé
# en copie aurait fait pointer `REPO_ROOT` vers `site-packages`.
#
# La condition est que `.env` NE SOIT PAS LÀ : il pose `GATEWAY_JOURNAL=logs/journal.jsonl`
# et `SORABEL_DB=data/sorabel.db`, des chemins RELATIFS qui écrasent les défauts absolus de
# `config.py`. Le `.dockerignore` l'exclut, et les `COPY` ci-dessous sont nommés.
WORKDIR /app

# Les dépendances avant le code : cette couche ne se reconstruit que si le lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --------------------------------------------------------------------- le code
# `COPY` NOMMÉS, jamais `COPY . /app` : le `.dockerignore` est la seconde barrière contre
# les secrets, pas la seule.
#
# `data/bm25/*.pkl` porte le chemin de module `packages.rag_machines.retrieval.lexical` EN
# DUR dans le pickle : l'arborescence doit être préservée à l'identique, sans quoi le
# dépicklage lève un `ModuleNotFoundError` qui ne dira pas que le pickle est en cause.
COPY config.py ./
COPY packages/ ./packages/
COPY mcp_server/ ./mcp_server/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY eval/ ./eval/
COPY docs/schema.sql ./docs/
COPY tests/ ./tests/
COPY run-api.sh run-web.sh ./
RUN chmod +x /app/run-api.sh /app/run-web.sh

RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# LA BASE EST RECONSTRUITE, pas héritée : `scripts/seed.py` est le seul des trois artefacts
# à être DÉTERMINISTE depuis la source (`random.Random(8842)`), et n'a que des imports
# stdlib. La reconstruire rend l'image auto-cohérente ; l'index Chroma et le pickle BM25,
# eux, ne peuvent pas l'être — cf. `Dockerfile.chroma`.
RUN python scripts/seed.py

# Le journal part VIDE et reste éphémère (décision assumée : pas de volume). `logs/` doit
# exister et être inscriptible — `packages/journal.py` fait bien un `mkdir(parents=True)`,
# mais un dossier non inscriptible transformerait une erreur déjà gérée en 500 non géré.
RUN mkdir -p /app/logs

# `/app` RESTE INSCRIPTIBLE, et ce n'est pas de la négligence : Chainlit fait
# `FILES_DIRECTORY.mkdir(exist_ok=True)` À L'IMPORT du module, sans `parents=True`, et
# régénère `.chainlit/` et `chainlit.md` — tous deux gitignorés, donc absents de l'image.
# Un utilisateur non-root exigerait un `chown` sur `/app` ; on reste root, ce qui est le
# défaut de Container Apps.

# DEUX SCRIPTS DE LANCEMENT, ET C'EST UNE NÉCESSITÉ, PAS UN RANGEMENT.
#
# Le champ « Arguments » d'Azure Container Apps transmet sa valeur comme UN SEUL argument :
# ni les virgules ni les espaces ne la découpent. Mesuré à l'écran —
# `packages.agent.api:app --host,0.0.0.0 --port,8000` arrive en un bloc, et uvicorn cherche
# un attribut littéralement nommé « app --host,0.0.0.0 --port,8000 ». Le conteneur
# redémarrait en boucle.
#
# Un script ne laisse rien à découper :
#   gateway : Commande = /app/run-api.sh   Arguments = (vide)
#   web     : Commande = /app/run-web.sh   Arguments = (vide)
#
# Aucun `CMD` par défaut : les deux rôles de cette image n'ont pas le même point d'entrée,
# et un défaut arbitraire ferait démarrer le mauvais si la commande était oubliée.

# ------------------------------------------------------------ cible de contrôle
# `--no-dev` laisse `pytest` dehors, et c'est juste pour l'image servie. Mais la validation
# par conteneurs doit jouer la SUITE D'ACCEPTANCE dans le conteneur, pas seulement à côté.
# D'où cette cible : mêmes couches, plus le groupe `dev`.
#
# Les six suites `check-*` n'en ont PAS besoin — ce sont des scripts Python purs, jouables
# dans l'image SERVIE, ce qui en fait une preuve plus forte.
FROM base AS test
RUN uv sync --frozen --no-install-project
RUN uv sync --frozen


# ------------------------------------------------------------- cible par défaut
# `serve` est LE DERNIER STAGE, et c'est délibéré : `docker build` sans `--target` construit
# le dernier, donc le défaut est l'image SERVIE. Avec `test` en dernier, un build nu
# embarquait `mypy`, `mypyc` et son `.so` — mesuré, 357 Mo contre 304 — dans l'image
# déployée. Un défaut sûr vaut mieux qu'un drapeau à ne pas oublier.
#
#   docker build .                  -> image servie (304 Mo, sans pytest ni mypy)
#   docker build --target test .     -> image de contrôle (357 Mo, avec le groupe dev)
FROM base AS serve
