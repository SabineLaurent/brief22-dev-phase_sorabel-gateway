# Sorabel Data Gateway — conventions du dépôt

Brief 22 : gateway MCP exposant un RAG avancé et du Text-to-SQL sur les données
Sorabel, sous matrice d'accès et journalisation.

## Où en est le projet

Phase de conception terminée (`docs/conception/LIVRABLES_CONCEPTION/`). Phase de développement en cours.

- **Chantier RAG, étape 1 — ingestion : faite.** `config.py`, `ingest/` (normalize,
  registry, index, cli), `retrieval/embedder.py`, `scripts/check_index.py`. 400 éditions
  indexées dans Chroma, 18 contrôles au vert. Revue de code passée : neuf constats
  corrigés et vérifiés, consignés au journal.
- **Chantier RAG, étape 2 — recherche dense, citations, refus : faite.**
  `retrieval/search.py` (tout paramétré : collection, étage, filtre, départage, seuil),
  `scripts/calibrate_threshold.py`, `eval/questions_calibration.jsonl`. Mesure « avant »
  posée : Hit@1 **1/8** en dense seul, refus 7/8 au seuil 0,831 (2/8 à la première mesure ;
  republié le 2026-09-07 après réindexation — cf. journal du jour).
- **Chantier RAG, étape 3 — hybride BM25 + RRF + rerank, mesure du gain E6 : faite.**
  `retrieval/lexical.py` (BM25), `retrieval/reranker.py` (cross-encoder / LLM Azure,
  commutables), `scripts/eval_rag.py`, sept cibles `mesure-*`. E6 mesuré et publié dans
  `eval/rapport_gain.md` : Hit@1 référence **1/8** (A) → 3/8 (B) → **8/8 (C)**, MRR 1,000 en
  hybride. Chantier RAG terminé.
  **Chiffres republiés le 2026-09-07.** A valait 2/8 à la première mesure ; l'index a été
  reconstruit depuis, et les neuf cibles de mesure ne tournaient plus (chemin faux, corrigé).
  B et C sont **rejoués identiques** : seul l'« avant » bouge, et il devient plus mauvais —
  le gain publié était sous-estimé. Les seuils, eux, **n'ont pas bougé** : `make calibrer` et
  `make calibrer-hybride` reproposent 0,8308 et 0,0530, les valeurs configurées.
- **Chantier Text-to-SQL : fait, en bibliothèque.** `packages/text_to_sql_factory/` :
  `access_sql` (les colonnes ; la matrice elle-même vit dans `packages/access.py`), `contract` (contrat de lecture filtré), `generator` (une passe LLM,
  trois branches, plus une reprise sur requête fausse), `validator` (cinq contrôles sqlglot
  — **tables en 5a avant colonnes en 5b** — puis LIMIT, puis le contrôle 6 `EXPLAIN`),
  `executor` (connexion `mode=ro` + `query_only`, bornes, trois contrôles du résultat, et
  `explain()`), `tools` (les quatre tools SQL). `make check-sql` : 81 contrôles
  déterministes, tous au vert. `make eval-sql` : 24/24 conformes, publié dans
  `eval/rapport_sql.md`.
  **Le contrôle 6 confronte la requête au moteur avant de l'exécuter** : `EXPLAIN` la
  prépare sans lire une ligne et refuse ce que l'arbre ne peut pas voir (`DATE_TRUNC`,
  colonne inventée, ambiguïté de jointure). Il vient **en dernier**, après que la matrice a
  tranché : il dit « ça se prépare », jamais « c'est permis ». Sur échec, l'erreur du moteur
  est rendue au modèle pour **une** reprise — jamais sur un refus de droits
  (`Verdict.repairable`, posé par le seul contrôle 6).
  **Écart au brief, décidé et consigné** : le brief nomme E5 dans l'étape 1 de ce chantier,
  et le test T2 exige un refus « journalisé ». La moitié « colonnes sensibles » est tenue ;
  **la journalisation est reportée au chantier 3**, où elle sera écrite une fois pour les
  huit tools. Les enveloppes portent déjà `code`, `sql`, `n_rows`, `latency_ms` pour ça.
- **Banc d'essai GUI : fait.** L'agent de `packages/agent/` expose les quatre tools du
  chantier 2 — `ask_to_db`, `check_stock_by_ref`, `order_status_by_id`, `get_db_schema` —
  nommés autrement exprès : ils *appellent* les tools du catalogue, ils ne les sont pas.
  **Aucun aiguillage codé** : c'est le LLM qui choisit sur les descriptions, comme le fera
  le serveur MCP. Le rôle Chainlit devient un profil de matrice (`profile_for_role()` dans
  `api.py`), l'étage 2 est appliqué aux quatre, et `matrice.yaml` gagne un profil `admin`.
  **Le profil est déclaré par le client** : écart assumé et temporaire, il tombe avec le
  serveur MCP.
- **Matrice appliquée au corpus : faite.** `packages/access.py` (module partagé : `Scope`,
  chargement, `scope_for`, `authorize` — l'étage 2 des huit tools), avec un lecteur par
  domaine : `text_to_sql_factory/access_sql.py` et `rag_machines/access_rag.py`. Le filtre
  de périmètre documentaire (`retrieval/perimeter.py`) applique `collections` et
  `themes_notes` **avant la troncature**, côté Chroma comme côté BM25 — les pickles portent
  désormais `doc_type` et `theme`, et un garde-fou refuse un index antérieur.
  **La forme du `where` est une disjonction, pas une conjonction** : la clé `theme` est
  omise sur les 320 non-notes, et un `$and` naïf ne rendrait que des notes. C'est la forme
  écrite dans `Q3.md` §8, qui y était « documentée, pas exécutée » — ce chantier l'exécute.
  `make check-perimetre` : 31 contrôles, décomptes en or 270/318/350 vérifiés contre l'index.
  `make mesure-perimetre` → `eval/rapport_perimetre.md` (axe 3 du protocole) : filtrer après
  la troncature coûte 0,83 résultat par question à `dev` et décide cinq fois le seuil de
  refus sur un document que l'utilisateur ne verrait pas.
- **Chantier 3, étape 1 — réponse déterministe et journalisation, côté SQL : faite.**
  `text_to_sql_factory/structured_answer.py` (`DbStructuredAnswer`,
  `build_db_structured_answer()`, `client_view()` — **le seul sérialiseur**),
  `text_to_sql_factory/handler.py` (`handle()` : le point de passage unique, qui applique
  l'étage 2, journalise, puis purge — **dans cet ordre**), `packages/journal.py` (JSONL
  transverse aux huit tools, `record()` / `tail()`, protocole `Journalable`), et le câblage du
  banc d'essai (`agent/api.py`, `agent/cli.py`, `web_client/app.py`).
  **`envelope()` n'existe plus** : renommée sur demande. Les trois clés du DSI — `status`,
  `payload`, `message` — sont inchangées.
  **Le défaut corrigé n'était pas la forme, c'était l'énoncé** : le `message` était écrit par
  le modèle sur `ecriture_refusee`, `hors_schema` et `clarification`, puis reformulé par le
  LLM de chat. Il est désormais une **phrase figée choisie sur le code** ; le texte du modèle,
  le message SQLite et la trace d'exception partent au journal sous `cause` / `stack`.
  `cause`, `stack`, `forbidden` et `etage` sont des **attributs de dataclass, jamais des clés
  de dict** — la garantie est structurelle, pas conventionnelle.
  Le journal est lisible par le seul profil `admin` (`read_feedback()`, garde-fou par
  `authorize()` + `read_journal` dans `matrice.yaml`), entrées **entières** : sa protection
  est son droit d'accès, pas son contenu. `make check-feedback` : 103 contrôles
  déterministes, tous au vert ; `make check-sql` 81/81 et `make eval-sql` 24/24 inchangés.
  Schéma des deux voies : `docs/archives/schema-feedback.html` (à ouvrir dans un navigateur).
  **Écart corrigé** : `get_schema` retiré à `support` dans `matrice.yaml` — arbitrage déjà
  consigné au journal, devenu bloquant dès que l'étage 2 s'exerce.
- **Chantier 3, étapes A et B — les quatre tools RAG, puis les huit au serveur : faites.**
  `rag_machines/structured_answer.py` (`RagStructuredAnswer`, `build_rag_structured_answer()`,
  `rag_client_view()` — **le seul sérialiseur du domaine**), `writer.py` (rédaction + garde
  de suffisance), `tools.py` (les quatre tools), `handler.py` (`handle()` : étage 2,
  journalisation, purge — **dans cet ordre**), `models.py`, et `classify()` ajouté à
  `ingest/normalize.py`. Côté serveur : `mcp_server/server.py` sert les **huit** tools,
  `mcp_server/__main__.py` ajoute la forme courte `python -m mcp_server`.
  **La couche RAG est parallèle à la couche SQL, pas partagée** : elle n'a pas les mêmes
  codes, et le SQL était vert sur 183 contrôles. Ce qui est partagé l'est par le protocole
  `Journalable` de `packages/journal.py`, écrit structurel exprès pour ça. Un seul journal,
  deux domaines qui l'alimentent sans se connaître.
  **Deux codes que le SQL n'a pas** : `hors_corpus` (le seuil, avant tout appel au modèle)
  et `contexte_insuffisant` (le modèle juge les extraits). Ils **partagent le statut
  `hors_corpus`** — le contrat DSI n'a pas de sixième statut — mais gardent des codes
  distincts, et **ni l'un ni l'autre n'est un refus** : les compter dans `REFUSAL_CODES`
  ferait dire `denied` au journal sur des non-réponses et rendrait E5 illisible.
  **`blocked_at` a été posé en même temps que la couche**, comme l'exigeait la piste
  « capter tôt, publier tard ». Reste ouvert : « nommer, pas numéroter » et la cible Make de
  mesure.
  **L'import du handler RAG est local aux fonctions de tool du serveur** — contrainte de
  protocole, pas optimisation : `initialize` a 30 s, et un import au niveau du module
  chargerait l'embedder avant la poignée de main. Premier appel de recherche : 8,2 s.
  **`make test` passe : 12/12, pour la première fois du projet.** T2 est satisfait.
  `make check-rag-tools` : 62 contrôles déterministes au vert ; `make check-sql` 81,
  `make check-feedback` 103, `make check-perimetre` 31 inchangés.
  **Écart décidé** : les noms d'arguments suivent la suite d'acceptance —
  `search_docs(query)`, `get_document(doc_id)` — et non `question` / `doc_key` de
  `03-catalogue-tools.md`. Le test fait foi.
- **Chantier 3, étape C — l'agent du banc d'essai est client MCP : faite.**
  `packages/agent/gateway.py` (**le seul endroit du code servi qui parle le protocole**) :
  `gateway_session()`, `GatewayRegistry`, et l'adaptateur catalogue MCP → `StructuredTool`.
  `cli.py` et `api.py` passent en async ; `packages/web_client/app.py` n'est pas touché.
  **Le profil n'est plus un argument** : il est dans `SORABEL_PROFILE`, dans l'environnement
  du sous-processus serveur, et le rôle de l'interface sert désormais à choisir *quel
  processus* on interroge — plus *quel argument* on passe. `profile_for_role()` est
  inchangé. Écart refermé.
  **Le catalogue n'est plus en dur** : les tools de l'agent sont ceux que `tools/list` rend
  (support 7, commercial 8, dev 5, admin 8, **default 0**). L'étage 1 existait depuis
  l'étape B, rien ne l'exerçait. Et les quatre tools documentaires passent enfin par leur
  handler : étage 2, seuil de refus et journalisation, les trois d'un coup.
  **Prérequis levé au passage** : `build_embedder` / `build_reranker` n'étaient pas
  mémoïsés, et `search()` en construisait un par appel. Invisible pour la suite
  d'acceptance, qui relance un processus par appel — mais 4 s par question dans un serveur
  qui vit. Mesuré : 5,00 / 4,22 / 3,77 s avant, 5,35 / **0,16** / **0,16** après.
  **Défaut introduit puis corrigé** : un catalogue vide ne rend pas un modèle muet — sous
  `sans_role` il annonçait « je vais interroger la base ». `build_agent()` rend `None` sur
  catalogue vide, CLI et API rendent `EMPTY_CATALOGUE`, la phrase figée du refus.
  **Écart décidé** : `--strategy` disparaît (CLI et `ChatRequest`) — les tools MCP
  n'exposent pas d'étage de recherche, le serveur décide. `make mesure-*` reste l'endroit
  pour comparer les étages.
  `make test` 12/12 ; check-sql 81, check-feedback 102, check-rag-tools 62,
  check-perimetre 31 inchangés.
- **Vague 1 du TODO post-revue : faite.** `docs/2026-09-07-todo-post-revue.md`.
  Deux mesures publiées de plus — `make mesure-refus` → `eval/rapport_refus.md` (axe 4) et
  `make mesure-acces` → `eval/rapport_acces.md` (axe 5, **E5 chiffrée** : 50/50 appels
  journalisés, 0 fuite des trois colonnes sensibles) ; `collections` exposé sans `enum` sur
  les trois tools ; les motifs d'écart au cadrage écrits dans `mcp_server/matrice.yaml`.
  **Deux correctifs de garantie.** `check_sql.py` contrôle le **réarmement de `query_only`
  sur connexion neuve** — le seul invariant qui tienne la lecture seule, et il n'était
  vérifié que par ses charges (81 → **83**). Et `question_for_writer()` dans
  `rag_machines/tools.py` complète l'énoncé quand la question est réduite à une référence
  nue : « REF-5313 » n'est pas une question, et la barrière 2 la refusait sur un retrieval
  parfait. La réécriture est **au seul bord de `writer.write()`** — la recherche garde la
  référence nue, c'est cette forme que BM25 attrape — et **pas dans le `_SYSTEM_PROMPT`** :
  mesuré, la règle au prompt desserre la barrière 2 au-delà du cas visé (RAG-18 et RAG-20
  basculent en `ok` alors que le corpus ne porte pas leur réponse). Faux refus 3–4/22 →
  **3/22**, et **la plage disparaît** : les trois passes sont identiques.
  **`make lint` est au vert** — `IncludeEnum.metadatas` dans `check_index.py`, et deux
  `# type: ignore[arg-type]` motivés sur les décorateurs Chainlit.
  `make test` 12/12 ; check-rag-tools **67**, check-sql **83**, check-feedback 103,
  check-perimetre 31.
- **Le contrat de réponse est déclaré au protocole : fait.** `mcp_server/output_schemas.py`
  (les huit `outputSchema`), `mcp_server/server.py` (les huit tools rendent l'enveloppe,
  `list_tools` publie le schéma), `packages/evals_and_controls/check_mcp_contract.py`.
  `make check-contrat` : **121 contrôles**, et c'est le **premier contrôle du serveur MCP** du
  projet — les quatre autres suites portent sur les couches en dessous.
  **Le défaut n'était pas une absence, c'était un contrat faux.** FastMCP dérive
  l'`outputSchema` de l'annotation de retour : `-> str` publiait
  `{"required":["result"],"properties":{"result":{"type":"string"}}}` et rendait
  `structuredContent = {"result": "<l'enveloppe en chaîne>"}`. Publié dans `tools/list`, donc
  lu par tout client externe, et validé par le SDK sans rien attraper.
  **Le schéma est écrit à la main, et le type de retour reste large** — `dict[str, Any]`. Un
  type de retour joue deux rôles dans FastMCP : il dérive le schéma *et* il filtre la sortie.
  Mesuré : un modèle plus étroit que le dict rendu fait **diverger `content[0].text` de
  `structuredContent`**, la clé restant dans le texte et disparaissant du structuré. Or le
  payload servi est un **surensemble du cadrage**. Le schéma est donc réécrit dans
  `SorabelMCP.list_tools` — le décorateur n'accepte pas de schéma, et cette méthode est déjà
  celle qui décide du catalogue *et* celle qui remplit le cache de validation du serveur.
  **Trois provenances, trois pannes évitées** : `status` **calculé** depuis les tables de
  statuts des domaines (un enum recopié dériverait) · `payload` **écrit à la main**, par tool
  (un payload dérivé filtrerait) · `payload.code` décrit **sans `enum`** (un enum incomplet
  transforme une réponse valide en panne — et les codes ne sont pas relevables par lecture :
  `perimetre_interdit` passe par une constante, `aucune_ligne` est propagé depuis
  l'exécution). **`additionalProperties` n'est fermé nulle part.**
  **Écart qui reste, nommé** : les *noms de champs*. Le §4 conçu dit
  `code`/`hint`/`reponse`/`citations`, le servi dit `status`/`payload`/`message` — deux
  contrats concurrents, et un `outputSchema` ne décrit que celui qui est servi. `hint` et
  `isError` tranché code par code sont **abandonnés**, décidé et consigné.
  `make test` 12/12 ; check-sql 83, check-feedback 103, check-rag-tools 67,
  check-perimetre 31 inchangés ; `make lint` au vert ; E5 rejouée identique.
- **Reste du chantier 3.** Par ordre d'exigence du brief :
  1. **Le mini guide d'accès** — *livrable exigé*, au même titre que `mcp_server/` : « Le
     serveur MCP (mcp_server/) exposant le catalogue complet **ainsi qu'un mini guide
     d'accès** ». Il n'existe pas encore. C'est aussi l'endroit où mettre le bloc de
     configuration stdio pour un client externe, donc la réponse à « essai du service ».
     Il peut désormais recommander **`structuredContent`** comme chemin de lecture — les huit
     tools le rendent et l'`outputSchema` le décrit ; hier, l'écrire aurait été mentir. Et le
     tableau profil × tools devient reproductible plutôt que recopié :
     `npx @modelcontextprotocol/inspector --cli uv run python -m mcp_server.server
     --method tools/list` ;
  2. **l'interface graphique splittée par rôle** — un front Chainlit, une colonne par profil,
     chaque colonne adossée à son propre processus MCP (custom element React, exécution en
     `asyncio.gather`). Le registre de sessions par profil (`GatewayRegistry`) est déjà en
     place pour ça. C'est aussi elle qui porte le livrable « un lien d'une interface graphique
     du produit fonctionnel » — **l'URL exigée porte sur l'IGU, pas sur le serveur MCP** :
     stdio tient le livrable serveur (arbitrage consigné au journal le 2026-09-06).

  Le reste vit dans `docs/2026-09-07-todo-post-revue.md` — deux décisions ouvertes
  (`citations` au journal, `search_for_profile()`), l'écriture du contrat de réponse, les
  écarts au dossier de conception, et le contournement `literalai` à rendre durable.

  Hors périmètre du brief, instruit et journalisé mais **non ouvert** : le passage à un
  service partagé (transport HTTP, annuaire et secrets), et la chaîne de délégation
  d'identité (comptes, JWT, OBO). Trois entrées de journal les tiennent — ne pas les rouvrir
  sans décision explicite, elles ne rapportent aucun point.

**Les douze tests d'acceptance passent** (`make test`, ~47 s). **Ne rien modifier dans
`tests/`** : la suite est arrivée avec le dépôt et fait foi.

**Un contournement est nécessaire avant chaque `make test`, et il doit être rejoué après
chaque `uv sync`** : `literalai` (dépendance de `chainlit`) installe un paquet `tests` à la
racine de `site-packages`, qui masque le `tests/` du dépôt et empêche pytest de collecter.
Écarter ce dossier — renommage plutôt que suppression — fait repartir la collecte. Ce n'est
pas un défaut de la suite.

**Lire `docs/journal-developpement.md` avant de reprendre** — il tient les décisions, les
arbitrages, les écarts constatés et les points ouverts de chaque étape livrée. Y ajouter
une entrée à chaque étape terminée.

## Choix techniques transverses

- **Inférence LLM** : Azure AI Foundry en OpenAI-compatible, **API v1** — client OpenAI
  standard, `base_url=f"{endpoint}/openai/v1"`, déploiement en `model`, pas d'`api_version`.
- **Embeddings** : commutables — Azure si `AZURE_EMBEDDING_DEPLOYMENT` est renseigné,
  sinon `intfloat/multilingual-e5-base` en local (préfixes `passage:` / `query:`).
- **Reranker** (étape 3) : les deux, commutables — cross-encoder local et rerank LLM Azure.
- **Chroma** : service `docker compose`, port 8002.

## Langue

**Les identifiants Python sont en anglais** — fonctions, classes, variables,
constantes, paramètres. Sans exception.

**Le reste est en français** — docstrings, commentaires, messages d'erreur,
sorties console, documentation, noms de cibles Make.

## Clés de données : le contrat prime

Les clés de données ne sont pas des identifiants Python : elles suivent le
contrat, même quand elles sont en français. Ne jamais les renommer pour des
raisons de style.

- `docs/cadrage_dsi.md` — enveloppe de réponse, noms des tools, champs du journal ;
- `docs/conception/LIVRABLES_CONCEPTION/02-modele-chunk.md` — les onze champs de métadonnées, dont
  **`titre`** et **`n_caracteres`** ;
- `tests/acceptance/` — la suite lit littéralement certaines clés (`src["titre"]`,
  `metadata["doc_type"]`, `hits[0]["doc_id"]`).

La conversion attribut Python → clé de données se fait à un seul endroit par
domaine. Pour le corpus : `build_metadata()` dans `ingest/registry.py`.

## Mesure

`eval/protocole-mesure.md` fixe **ce qui varie et ce qui ne varie pas** dans toute
comparaison : quatre drapeaux orthogonaux, cinq axes, une cible Make par mesure
publiée. À lire avant d'écrire la moindre ligne d'évaluation — le protocole a été
arrêté avant l'implémentation exprès pour ne pas se façonner sur elle.

## Arbitrage

Quand le dossier de conception, `docs/cadrage_dsi.md` et `tests/` divergent,
**le test fait foi**. Les écarts connus sont consignés dans
`docs/journal-developpement.md`.

## Rythme de travail

Le développement suit le découpage du brief : trois chantiers (RAG avancé,
Text-to-SQL, serveur MCP), et trois étapes dans le chantier RAG. **Une étape à la
fois**, vérifiée et journalisée avant de passer à la suivante.

## Commandes

```bash
make up            # Chroma (docker compose, port 8002)
make ingest        # ingestion du corpus dans Chroma (met l'index à jour)
make reindex       # reconstruit la collection à neuf (modèle d'embeddings changé)
make ingest-brut   # index témoin, texte non nettoyé (axe 2 du protocole de mesure)
make calibrer      # règle le seuil de refus sur le jeu de calibration
make check-index   # contrôles d'intégrité de l'index
make check-perimetre # contrôles du filtre de périmètre documentaire (matrice sur le corpus)
make check-rag-tools # contrôles des quatre tools RAG et de leur journal (sans appel de modèle)
make seed          # génère data/sorabel.db
make check-sql     # contrôles déterministes du Text-to-SQL (sans appel de modèle)
make check-feedback # contrôles de la réponse structurée et du journal (sans appel de modèle)
make check-contrat # contrôles de l'outputSchema publié par les huit tools (121)
make mesure-refus  # axe 4 : le refus servi sur les deux barrières -> eval/rapport_refus.md
make mesure-acces  # axe 5 : E5 chiffrée, étages d'arrêt et colonnes fermées -> eval/rapport_acces.md
make journal       # les 20 dernières entrées de logs/journal.jsonl
make eval-sql      # les 24 questions SQL -> eval/rapport_sql.md (un appel LLM chacune)
make serve         # serveur MCP stdio, les huit tools (profil dans SORABEL_PROFILE)
make client        # client de test : catalogue et appel d'un tool (PROFILE=support|commercial)
make test          # suite d'acceptance — 12/12
make lint          # ruff + mypy — au vert
```
