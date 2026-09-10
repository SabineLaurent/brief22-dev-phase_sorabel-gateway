# Sorabel Data Gateway

Point d'accès unique aux données de **Sorabel**, distributeur B2B de matériel électrique et d'outillage professionnel. La gateway expose, via un **serveur MCP**, le corpus documentaire (fiches techniques, notices, procédures SAV, notes internes) et la base SQL (produits, stocks, commandes, clients, ventes) à tous les outils internes — bot Slack du support, IDE des développeurs, poste des commerciaux — sous une gouvernance commune : matrice d'accès par profil, lecture seule stricte côté SQL, journal de tous les appels.

## Features

- **Recherche documentaire avancée** : dense + lexicale (BM25), fusion RRF, reranking
  (cross-encoder local ou LLM Azure, commutables), réponses sourcées (titre + référence +
  date), refus explicite hors corpus sur seuil calibré. Gain mesuré et publié
  (`eval/rapport_gain.md`) : Hit@1 **1/8 → 8/8**, MRR 1,000 en hybride
- **Accès aux données en langage naturel** : génération SQL une passe, validation en six
  contrôles (sqlglot puis `EXPLAIN`), exécution `mode=ro` bornée, requête toujours renvoyée
  avec le résultat. `make eval-sql` : **24/24** conformes (`eval/rapport_sql.md`)
- **Tools figés** pour les besoins récurrents : `check_stock`, `order_status`
- **Serveur MCP unique** exposant les **huit tools**, sous matrice d'accès par profil
  (`support`, `commercial`, `dev`, `admin`, `default`), journalisation de chaque appel —
  servi comme refusé
- **Matrice appliquée au corpus** : filtre de périmètre documentaire (collections et thèmes)
  appliqué **avant** la troncature, côté Chroma comme côté BM25 (`eval/rapport_perimetre.md`)
- **Banc d'essai** : agent LangChain client MCP (CLI + API FastAPI) et interface Chainlit ;
  le rôle choisit un processus serveur, jamais un argument
- Données en place : base SQL générée par `scripts/seed.py`, corpus de ~400 documents
  indexés dans Chroma

**La suite d'acceptance passe : `make test` → 12/12.**

## Contrat d'intégration

Le serveur se lance en stdio et sert les huit tools sous le profil de son environnement.
Toute réponse est une enveloppe `{status, payload, message}`, refus compris, et tout appel
est journalisé.

> **[`mcp_server/README.md`](mcp_server/README.md) — le mini guide d'accès** : bloc de
> configuration prêt à coller, tableau profil × tools, les douze codes et ce qu'un client
> doit en faire, les limites et les écarts assumés.

La note de cadrage de la DSI (`docs/cadrage_dsi.md`) **fait foi** sur ce contrat. La suite
`tests/acceptance/` consomme la gateway en boîte noire, exactement comme un client interne :
elle est rouge tant que le serveur et ses tools ne tiennent pas ce contrat — elle est
aujourd'hui verte, 12/12.

## Déployé

L'interface graphique est en ligne sur Azure Container Apps :

**<https://sorabel-web-demo-sabl.delightfulpond-41840da3.francecentral.azurecontainerapps.io>**

Trois applications dans l'environnement `cae-sorabel-demo-sabl` — le front (ingress externe),
la gateway (interne) et Chroma (interne). Le serveur MCP n'en est pas une : il parle en
**stdio**, donc sans port, et reste un sous-processus de l'API.

Le pas-à-pas complet — commandes de paramétrage, de vérification et les cinq obstacles
rencontrés — est dans **`docs/2026-09-10-deploiement-azure-pas-a-pas.md`**.

> **Le build ne part pas d'un clone propre.** `.docker-data/chroma`, `data/bm25/*.pkl` et
> `data/sorabel.db` sont gitignorés et nécessaires à la construction des images. L'index
> vectoriel n'est pas un artefact de build : c'est le **référent de la calibration** — le
> reconstruire produirait d'autres vecteurs et invaliderait le seuil de refus en silence. Il
> faut donc construire depuis une machine qui a joué `make ingest`, et l'erreur serait
> silencieuse : l'image démarrerait et ne répondrait à aucune question documentaire.

## Stack

- Python 3.11 (géré avec `uv`)
- Chroma pour l'index vectoriel (`docker compose`, port 8002)
- SQLite pour la base (`data/sorabel.db`, générée par le seed, à ouvrir en lecture seule)
- SDK MCP (`mcp`) pour le serveur et le client stdio
- `pypdf` / `beautifulsoup4` pour l'extraction du corpus, `rank-bm25` pour la piste lexicale
- `sentence-transformers` disponible via l'extra `vector` :

```bash
uv sync                       # cœur + outils de dev
uv sync --extra vector        # + sentence-transformers
```

## Démarrage

```bash
make install      # uv sync
make seed         # génère data/sorabel.db (déterministe, aligné sur le corpus)
make up           # docker compose : Chroma sur localhost:8002
make ingest       # indexation du corpus dans Chroma
make test         # suite d'acceptance — 12/12
make serve        # serveur MCP stdio (profil via SORABEL_PROFILE)
make client       # client de test (PROFILE=support|commercial)
```

Exemples côté client :

```bash
uv run python scripts/mcp_client.py --profile support --tool search_docs --args '{"query": "REF-8842"}'
uv run python scripts/mcp_client.py --profile commercial --tool ask_database --args '{"question": "combien de commandes en avril ?"}'
```

## Layout

```
config.py             # configuration unique (pydantic-settings) — aucun module ne lit os.environ
packages/
  access.py           # matrice d'accès : Scope, scope_for, authorize — l'étage 2 des huit tools
  journal.py          # journal JSONL transverse (record / tail, protocole Journalable)
  rag_machines/       # domaine documentaire
    ingest/           # normalisation, registre, indexation, CLI
    retrieval/        # embedder, recherche dense, BM25, RRF, reranker, périmètre
    tools.py          # les quatre tools RAG          handler.py  # étage 2, journal, purge
    structured_answer.py  # le seul sérialiseur du domaine
  text_to_sql_factory/  # domaine SQL
    contract.py       # contrat de lecture filtré par profil
    generator.py      # génération (une passe, trois branches, une reprise)
    validator.py      # cinq contrôles sqlglot + LIMIT + contrôle 6 EXPLAIN
    executor.py       # connexion mode=ro + query_only, bornes, contrôles du résultat
    tools.py          # les quatre tools SQL          handler.py  # étage 2, journal, purge
  agent/              # banc d'essai : gateway.py (client MCP), cli.py, api.py (FastAPI)
  web_client/         # interface Chainlit
mcp_server/
  README.md           # LE MINI GUIDE D'ACCÈS — pour qui branche un client
  server.py           # le serveur : les huit tools, étage 1 sur tools/list, frontière call_tool
  output_schemas.py   # l'outputSchema des huit tools : le contrat, déclaré au protocole
  matrice.yaml        # matrice d'accès — donnée de configuration versionnée, jamais du code
data/
  corpus/             # ~400 documents : fiches/ notices/ (PDF), sav/ (HTML), notes/ (Markdown)
  bm25/               # index lexicaux sérialisés
  sorabel.db          # base SQL (hors git — make seed, schéma dans docs/schema.sql)
docs/
  cadrage_dsi.md      # exigences E1–E6, matrice d'accès, contrat d'intégration
  conception/         # dossier de conception (livrables de la phase 1)
  journal-developpement.md  # décisions, arbitrages, écarts et points ouverts — à lire d'abord
eval/
  protocole-mesure.md # ce qui varie et ce qui ne varie pas dans toute comparaison
  rapport_gain.md     # E6 : gain de l'hybride sur le dense
  rapport_sql.md      # les 24 questions SQL
  rapport_refus.md    # le refus documentaire sur ses deux barrières
  rapport_perimetre.md # ce que coûte un filtre appliqué après la troncature
  rapport_acces.md    # E5 : journalisation, étages d'arrêt, colonnes fermées
scripts/
  seed.py             # génère et peuple data/sorabel.db
  mcp_client.py       # client MCP de test (profils support / commercial)
tests/acceptance/     # suite d'acceptance boîte noire, adossée aux exigences E1–E6
```

## Où en est le projet

Les trois chantiers du brief sont livrés et vérifiés ; `CLAUDE.md` en tient l'état détaillé
et `docs/journal-developpement.md` les décisions. Le mini guide d'accès est écrit
([`mcp_server/README.md`](mcp_server/README.md)) et E5 est chiffrée
([`eval/rapport_acces.md`](eval/rapport_acces.md)). Reste, côté phase de développement :
**l'interface graphique splittée par rôle**, et le lien public qui va avec.
