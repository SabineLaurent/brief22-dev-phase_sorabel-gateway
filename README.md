# Sorabel Data Gateway

Point d'accès unique aux données de **Sorabel**, distributeur B2B de matériel électrique et
d'outillage professionnel. La gateway expose, par un **serveur MCP**, le corpus documentaire
(fiches techniques, notices, procédures SAV, notes internes) et la base métier (produits,
stocks, commandes, clients, ventes) à tous les outils internes — bot Slack du support, IDE des
développeurs, poste des commerciaux — sous une gouvernance commune : matrice d'accès par
profil, lecture seule stricte côté SQL, journalisation de chaque appel.

Le contrat imposé est celui de la note de cadrage DSI ([`docs/cadrage_dsi.md`](docs/cadrage_dsi.md),
exigences E1 à E6) ; quand la conception, le cadrage et `tests/` divergent, **le test fait foi**.

---

## Les huit tools

| Tool | Ce qu'il rend | Domaine |
|---|---|---|
| `answer_question` | une réponse rédigée **et ses sources** (titre, référence, date) | documentaire |
| `search_docs` | les extraits classés, sans barrière de refus — c'est sur lui que le gain se mesure | documentaire |
| `get_document` | le texte d'une édition et ses métadonnées | documentaire |
| `list_sources` | la liste plate des éditions courantes du périmètre du profil | documentaire |
| `ask_database` | le SQL généré, les colonnes, les lignes — **la requête part toujours avec le résultat** | métier |
| `get_schema` | le DDL commenté, réduit au périmètre du profil | métier |
| `check_stock` | le stock d'une référence `REF-NNNN` (tool figé) | métier |
| `order_status` | l'état d'une commande par identifiant (tool figé) | métier |

Un neuvième, `read_journal`, n'appartient pas au catalogue DSI : il lit le journal, et le seul
profil qui le porte est `admin`.

### Recherche documentaire

Dense (Chroma) + lexicale (BM25), fusion RRF, puis rerank — **cross-encoder local ou Cohere
déployé sur Azure AI Foundry**, commutables tout ou rien. Politique de candidats explicite :
vivier 60, budget de rerank 20, plafond de 3 candidats par titre. Deux barrières de refus, et
elles ne lisent pas la même chose : le **seuil** sur le score du premier résultat (déterministe,
avant tout appel de modèle), puis la **garde de suffisance** du rédacteur, qui lit les extraits.

### Accès aux données en langage naturel

Une passe de génération, puis la validation : cinq contrôles d'arbre `sqlglot` (tables avant
colonnes), la borne `LIMIT`, et un sixième contrôle qui prépare la requête par `EXPLAIN` sans
lire une ligne. Sur échec du sixième — et de lui seul — l'erreur du moteur repart au modèle pour
**une** reprise ; un refus de droits ne se renégocie pas. L'exécution ouvre la base en
`mode=ro` avec `query_only` réarmé sur chaque connexion neuve.

### Trois étages d'accès, qui ne font pas le même travail

| Étage | Ce qu'il décide | Où il se lit |
|---|---|---|
| 1 | le catalogue visible — de l'**ergonomie**, pas une serrure | `tools/list` |
| 2 | le droit d'appeler le tool — **c'est là que le refus se prononce**, et il est journalisé | `blocked_at == 2` |
| 3 | le périmètre : colonnes fermées côté SQL, collections et thèmes côté corpus | `blocked_at == 3` |

Le profil n'est jamais déclaré par le client : il est lu dans `SORABEL_PROFILE`, dans
l'environnement du processus serveur. Un processus par profil. Catalogue servi, mesuré profil
par profil : `default` 0, `dev` 5, `support` 7, `commercial` 8, `admin` 8 — identique à ce que
[`mcp_server/matrice.yaml`](mcp_server/matrice.yaml) déclare.

### Le contrat de réponse

Toute réponse est une enveloppe `{status, payload, message}`, refus et erreurs compris — cinq
statuts, douze codes. Le `message` d'un refus est une **phrase figée choisie sur le code**,
jamais un texte de modèle : le texte du modèle, le message SQLite et la trace d'exception
partent au journal. Les huit tools publient leur `outputSchema` dans `tools/list`, et
`isError` n'est marqué que sur le statut `error` — un refus n'a rien à corriger.

---

## Ce qui est vérifié, et comment

**Suite d'acceptance : 12/12 en 47,26 s** (rejouée le 2026-09-13, commit `56fca0e`). Elle
consomme la gateway en boîte noire, comme un client interne, et chaque sortie porte en en-tête
la configuration **réellement lue** — commit, embedder, reranker, seuil, collection et son
empreinte : ici `sorabel_corpus`, 400 éditions, `multilingual-e5-base` et
`mmarco-mMiniLMv2-L12-H384-v1` en local, seuil 0,0530. Ne rien modifier dans `tests/` : la
suite est arrivée avec le dépôt et fait foi.

**Sept suites de contrôles déterministes** — aucun appel de modèle, donc rejouables à volonté
et sans coût. Décomptes relevés en exécutant les cibles le 2026-09-13 :

| Cible | Ce qu'elle contrôle | Contrôles |
|---|---|---:|
| `make check-index` | l'intégrité de l'index documentaire | 18 |
| `make check-perimetre` | la matrice appliquée au corpus, décomptes en or compris | 43 |
| `make check-rag-tools` | les quatre tools documentaires et leur journal | 77 |
| `make check-sql` | validation, exécution, bornes, réarmement de `query_only` | 83 |
| `make check-feedback` | la réponse structurée et le journal, côté SQL | 103 |
| `make check-client` | le dernier mètre : substituer, compléter, ou dire qu'on renonce | 83 |
| `make check-contrat` | le contrat publié, la frontière `call_tool`, les descriptions | 163 |
| | **total** | **570** |

`make lint` (ruff + mypy) est au vert. La CI (`.github/workflows/quality.yml`) joue le seed, le
lint et la suite d'acceptance ; elle ne construit pas les images, faute d'index vectoriel dans
un clone propre.

---

## Mesures publiées

Une cible Make par rapport — [`eval/protocole-mesure.md`](eval/protocole-mesure.md) fixe ce qui
varie et ce qui ne varie pas dans toute comparaison, et il a été arrêté avant l'implémentation.

| Rapport | Cible | Ce qu'il établit |
|---|---|---|
| [`rapport_gain.md`](eval/rapport_gain.md) | `make mesure` | **E6** : sous profil `support`, Hit@1 référence 3/8 en dense seul → **8/8** en hybride, MRR 0,562 → **1,000** ; contre le témoin « RAG simple », 1/8 → 8/8 |
| [`rapport_sql.md`](eval/rapport_sql.md) | `make eval-sql` | les 24 questions SQL, **24/24** conformes au code attendu par type |
| [`rapport_refus.md`](eval/rapport_refus.md) | `make mesure-refus` | le refus servi : 5/8 sur la barrière 1 seule → **8/8** sur les deux ; faux refus 3/22, stable sur trois passes |
| [`rapport_perimetre.md`](eval/rapport_perimetre.md) | `make mesure-perimetre` | ce que coûte un filtre appliqué **après** la troncature : à `dev`, 4,33 résultats rendus par question au lieu de 5,00, et **quatre** seuils de refus décidés sur un document que l'utilisateur ne verrait pas |
| [`rapport_acces.md`](eval/rapport_acces.md) | `make mesure-acces` | **E5** : 50 appels, **50 entrées de journal**, 0 fuite des trois colonnes sensibles ; plus la frontière du serveur, 5/5 |
| [`rapport_candidats.md`](eval/rapport_candidats.md) | `make mesure-candidats-profils` | un profil à plus de droits obtenait **moins** de réponses ; sous la politique servie les quatre profils coïncident |
| [`rapport_embeddings.md`](eval/rapport_embeddings.md) · [`rapport_rerank.md`](eval/rapport_rerank.md) · [`rapport_local_vs_distant.md`](eval/rapport_local_vs_distant.md) | `make mesure-embeddings` · `mesure-rerank` · `mesure-distant` | local ou distant, quatre cellules, chacune avec **son** seuil calibré — hors brief, c'est ce qui a décidé la configuration déployée. Chiffres relevés avant le lot « candidats » : conclusions intactes, scores à reprendre |

Les CSV bruts de chaque passe sont dans [`eval/resultats/`](eval/resultats/), en-tête portant la
politique et le seuil du run.

---

## Contrat d'intégration

Le serveur se lance en **stdio** (`python -m mcp_server.server`) et sert les huit tools sous le
profil de son environnement.

> **[`mcp_server/README.md`](mcp_server/README.md) — le mini guide d'accès**, pour qui branche
> son propre client : bloc de configuration prêt à coller, tableau profil × tools, les cinq
> statuts, les douze codes avec la colonne « ce qu'il ne faut **jamais** faire », les garanties,
> les limites chiffrées et les écarts assumés.
>
> `mcp_server/SMG-guide-d-acces.html` en est la version **générée** — `make doc-tools` lance un
> serveur par profil et rend ce que `tools/list` répond vraiment, descriptions et enveloppes
> réelles comprises. Une page rédigée à la main dérive ; celle-là ne peut pas.

Une seule source pour ce contrat : [`docs/mini-guide-acces.md`](docs/mini-guide-acces.md) et
cette section sont des renvois, pas des copies.

---

## Déployé

L'interface graphique est en ligne sur Azure Container Apps :

**<https://sorabel-web-demo-sabl.delightfulpond-41840da3.francecentral.azurecontainerapps.io>**

Le front, l'API et Chroma sont trois applications distinctes ; leur paramétrage
d'ingress est décrit dans le pas-à-pas ci-dessous, qui en porte les commandes. Le serveur MCP
n'est pas une application : il parle **stdio**, donc sans port ni adresse, et reste un
sous-processus de l'API, un par profil — d'où une seule image pour le front et l'API.

La configuration déclarée pour le déploiement — [`docker-compose.aca.yml`](docker-compose.aca.yml),
le fichier versionné qui la porte — est celle qui retire PyTorch de l'image :
`text-embedding-3-small`, `Cohere-rerank-v4.0-pro`, collection `sorabel_corpus_azure_small`,
seuil 0,6203. Le `Dockerfile` la rend obligatoire plutôt que préférée : `uv sync` y est joué
sans l'extra `vector`, donc un repli sur un modèle local lèverait un `ModuleNotFoundError`.

**Il n'y a aucune authentification, et le rôle est déclaré par l'appelant** — lu dans le code,
pas supposé : `ChatRequest.role` est un champ du corps de `POST /chat`
(`packages/agent/api.py:159`), et le front l'y met depuis le sélecteur de profils que le
visiteur manipule (`packages/web_client/app.py:201`). Aucun des deux fronts ne déclare de
rappel d'authentification Chainlit, et l'API ne vérifie ni en-tête ni jeton. Le profil MCP,
lui, reste hors d'atteinte du client : il est dans `SORABEL_PROFILE`, et le rôle ne choisit
que *lequel* des processus serveur on interroge. Le journal survit à un redémarrage, pas au
remplacement du conteneur.

Le pas-à-pas complet, commandes et cinq obstacles rencontrés :
[`docs/2026-09-10-deploiement-azure-pas-a-pas.md`](docs/2026-09-10-deploiement-azure-pas-a-pas.md).

> **Le build ne part pas d'un clone propre.** `.docker-data/chroma`, `data/bm25/*.pkl` et
> `data/sorabel.db` sont gitignorés et nécessaires à la construction des images. L'index
> vectoriel n'est pas un artefact de build : c'est le **référent de la calibration** — le
> reconstruire produirait d'autres vecteurs et invaliderait le seuil de refus en silence. Il
> faut donc construire depuis une machine qui a joué `make ingest`, et l'erreur serait muette :
> l'image démarrerait sans répondre à aucune question documentaire.

---

## Stack

- Python 3.11 (épinglé `>=3.11,<3.12`), géré avec `uv`
- Chroma pour l'index vectoriel (`docker compose`, port 8002)
- SQLite pour la base métier (`data/sorabel.db`, générée par le seed, ouverte en lecture seule)
- SDK `mcp` pour le serveur et le client stdio ; `sqlglot` pour la validation SQL
- `pypdf` / `beautifulsoup4` pour l'extraction du corpus, `rank-bm25` pour la piste lexicale
- LangChain + FastAPI + Chainlit pour le banc d'essai
- Inférence, embeddings et rerank : Azure AI Foundry en OpenAI-compatible (API v1)
- `sentence-transformers` (donc PyTorch) dans l'extra `vector` — nécessaire **en local seulement**

```bash
uv sync                  # cœur + outils de dev — retire l'extra s'il était installé
uv sync --extra vector   # + sentence-transformers : sans lui, l'embedder local casse
```

## Démarrage

```bash
uv sync --extra vector    # `make install` ne pose que le cœur
cp .env.example .env      # aucune valeur du modèle n'y est un secret
make up                   # Chroma, docker compose, port 8002
make seed                 # data/sorabel.db — déterministe, aligné sur le corpus
make ingest               # indexation du corpus dans Chroma
make test                 # suite d'acceptance — 12/12
make help                 # les 48 cibles, par section ; ✱ = appelle un modèle, donc coûte
```

Faire tourner :

```bash
make serve         # serveur MCP stdio (profil dans SORABEL_PROFILE)
make client        # client de test : catalogue d'un profil (PROFILE=support|commercial|dev|admin|default)
make api           # API du banc d'essai — uvicorn, port 8000
make web           # IGU mono-rôle — Chainlit, port 8100
make web-compare   # IGU splittée : une question, quatre profils côte à côte, port 8101
make journal       # les 20 dernières entrées de logs/journal.jsonl
```

Deux profils côte à côte, en ligne de commande :

```bash
uv run python scripts/mcp_client.py --profile support --tool search_docs --args '{"query": "REF-8842"}'
uv run python scripts/mcp_client.py --profile commercial --tool ask_database --args '{"question": "combien de commandes en avril ?"}'
uv run python scripts/mcp_client.py --profile dev        # 5 tools sur 8
uv run python scripts/mcp_client.py --profile default    # aucun tool
```

---

## Les données

**Corpus** — 400 fichiers dans `data/corpus/` : 150 fiches techniques et 80 notices (PDF), 90
procédures SAV (HTML), 80 notes internes (Markdown). Indexés en 400 éditions pour 350 documents
distincts : 50 documents portent deux versions, et seule la courante est servie. Le périmètre du
profil réduit encore : 270 éditions courantes pour `dev`, 318 pour `support`, 350 pour
`commercial` et `admin`, 0 pour `default`.

**Base métier** — `data/sorabel.db`, générée par `make seed` : 120 produits, 312 lignes de
stock, 340 commandes, 60 clients, 993 lignes de vente. Schéma commenté de référence :
[`docs/schema.sql`](docs/schema.sql). Trois colonnes sont sensibles au sens d'E5 —
`produits.prix_achat_ht`, `produits.marge_pct`, `ventes.marge_ht` : un seul secret en trois
exemplaires, donc fermées ensemble. `clients.email` est fermée aux **cinq** profils, pour un
motif RGPD et non E5.

---

## Layout

```
config.py                 # configuration unique (pydantic-settings), 26 réglages — aucun module ne lit os.environ
conftest.py               # l'en-tête de configuration que chaque sortie de test porte
packages/
  access.py               # la matrice : Scope, scope_for, authorize — l'étage 2 des huit tools
  journal.py              # journal JSONL transverse : record / tail, protocole Journalable
  rag_machines/           # domaine documentaire
    ingest/               # normalize, registry, index, cli
    retrieval/            # embedder, search, lexical (BM25), reranker, perimeter, azure_client
    tools.py              # les quatre tools          handler.py  # étage 2, journal, purge
    writer.py             # rédaction et garde de suffisance
    structured_answer.py  # le seul sérialiseur du domaine
    calibrate_threshold.py
    evals_and_controls/   # check_index, check_perimeter, check_rag_tools, eval_rag, eval_refusal…
  text_to_sql_factory/    # domaine métier
    contract.py           # contrat de lecture filtré par profil
    generator.py          # une passe, trois branches, une reprise
    validator.py          # cinq contrôles sqlglot, la borne, puis le contrôle 6 EXPLAIN
    executor.py           # mode=ro + query_only, bornes, contrôles du résultat
    tools.py              # les quatre tools          handler.py  # étage 2, journal, purge
    evals_and_controls/   # check_sql, check_feedback, eval_sql
  evals_and_controls/     # ce qui mêle les deux domaines : check_client, check_mcp_contract, eval_access
  agent/                  # banc d'essai : gateway.py (le seul client MCP), cli.py, api.py
  web_client/             # les deux fronts Chainlit : app.py et app_compare.py
mcp_server/
  README.md               # LE MINI GUIDE D'ACCÈS — livrable du brief
  SMG-guide-d-acces.html  # sa version générée (make doc-tools)
  server.py               # les huit tools, étage 1 sur tools/list, frontière sur call_tool
  output_schemas.py       # les huit outputSchema : le contrat, déclaré au protocole
  matrice.yaml            # la matrice — donnée de configuration versionnée, jamais du code
data/
  corpus/                 # fiches/ notices/ (PDF), sav/ (HTML), notes/ (Markdown)
  bm25/                   # index lexicaux sérialisés (hors git)
  sorabel.db              # base métier (hors git — make seed)
docs/
  cadrage_dsi.md          # E1–E6, matrice initiale, contrat d'intégration — fait foi
  journal-developpement.md # décisions, arbitrages, écarts, points ouverts — à lire d'abord
  conception/             # les livrables de la phase de conception
  BUGS.md                 # les défauts rencontrés et ce qu'ils ont appris
  TESTS_ACCEPTANCE/       # la suite rejouée en local et en conteneur, témoins de configuration fausse compris
eval/
  protocole-mesure.md     # ce qui varie et ce qui ne varie pas — sept drapeaux, huit axes
  rapport_*.md            # une mesure publiée par choix technique tranché
  resultats/              # les CSV bruts
scripts/
  seed.py                 # génère et peuple data/sorabel.db
  mcp_client.py           # client MCP de test, les cinq profils lus dans la matrice
  build_tool_docs.py      # le guide d'accès, généré depuis le serveur lui-même
  e2e_agent_*.py          # les 12 scénarios rejoués en langage naturel, via l'agent
tests/acceptance/         # la suite boîte noire, adossée à E1–E6 — ne pas modifier
Dockerfile                # une image, deux commandes (front et gateway), sans PyTorch
```

---

## Où en est le projet

Les trois chantiers du brief sont livrés, vérifiés et journalisés, et les deux livrables nommés
le sont aussi : le mini guide d'accès et l'URL publique de l'interface graphique.

Ce qui reste ouvert est consigné, pas deviné :
[`docs/journal-developpement.md`](docs/journal-developpement.md) tient les décisions, les
arbitrages et les écarts de chaque étape — **à lire avant de reprendre** ;
[`docs/2026-09-07-todo-post-revue.md`](docs/2026-09-07-todo-post-revue.md) tient les points
restants. Les écarts au dossier de conception y sont nommés un par un, avec le fichier et la
ligne qui les prouvent.
