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
  posée : Hit@1 2/8 en dense seul, refus 7/8 au seuil 0,831.
- **Chantier RAG, étape 3 — hybride BM25 + RRF + rerank, mesure du gain E6 : faite.**
  `retrieval/lexical.py` (BM25), `retrieval/reranker.py` (cross-encoder / LLM Azure,
  commutables), `scripts/eval_rag.py`, sept cibles `mesure-*`. E6 mesuré et publié dans
  `eval/rapport_gain.md` : Hit@1 référence 2/8 (A) → 3/8 (B) → **8/8 (C)**, MRR 1,000 en
  hybride. Chantier RAG terminé.
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
  est son droit d'accès, pas son contenu. `make check-feedback` : 102 contrôles
  déterministes, tous au vert ; `make check-sql` 81/81 et `make eval-sql` 24/24 inchangés.
  Schéma des deux voies : `docs/schema-feedback.html` (à ouvrir dans un navigateur).
  **Écart corrigé** : `get_schema` retiré à `support` dans `matrice.yaml` — arbitrage déjà
  consigné au journal, devenu bloquant dès que l'étage 2 s'exerce.
- **Reste du chantier 3 : à faire.** Étendre la couche au RAG, puis le serveur MCP
  lui-même. Puis l'interface graphique.
  **À instruire à la fin du chantier, et à ne pas oublier** : un champ `blocked_at` au
  journal disant **quelle couche a bloqué la chaîne de réponse** (`0` = servi, toutes les
  couches franchies), puis la mesure de quel point de contrôle décide chaque refus. Le champ
  doit être **posé en même temps que l'extension au RAG**, pas après. Motif, réserves de
  conception et mesure visée : `docs/journal-developpement.md`, entrée « Piste à instruire :
  quelle couche a bloqué la chaîne de réponse ».

Aucun test d'acceptance ne passe encore : ils exigent tous un serveur MCP, qui n'existe
pas avant le troisième chantier.

T2 (« une demande d'écriture est refusée **et journalisée** ») est désormais *satisfaisable* :
le journal qu'il relit existe, il ne manque plus que le serveur pour l'appeler.

`pytest` échoue même à la **collecte**, et **ce n'est pas un défaut de la suite** :
`literalai` (dépendance de `chainlit`) installe un paquet `tests` dans `site-packages`, qui
masque le `tests/` du dépôt. Écarter ce dossier parasite fait repartir la collecte : 1
succès (`test_gain_hybride_mesure_et_documente`) et 11 échecs, tous « `mcp_server.server`
introuvable ». **Ne rien modifier dans `tests/`** : la suite est arrivée avec le dépôt et
fait foi.

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
comparaison : quatre drapeaux orthogonaux, trois axes, une cible Make par mesure
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
make seed          # génère data/sorabel.db
make check-sql     # contrôles déterministes du Text-to-SQL (sans appel de modèle)
make check-feedback # contrôles de la réponse structurée et du journal (sans appel de modèle)
make journal       # les 20 dernières entrées de logs/journal.jsonl
make eval-sql      # les 24 questions SQL -> eval/rapport_sql.md (un appel LLM chacune)
make test          # suite d'acceptance
make lint          # ruff + mypy — rouge sur 3 erreurs préexistantes (Chainlit, IncludeEnum)
```
