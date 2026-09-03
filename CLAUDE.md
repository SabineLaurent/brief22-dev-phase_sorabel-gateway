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
  `access` (matrice), `contract` (contrat de lecture filtré), `generator` (une passe LLM,
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
- **Chantier serveur MCP : à faire.** C'est la prochaine étape. Puis l'interface graphique.

Aucun test d'acceptance ne passe encore : ils exigent tous un serveur MCP, qui n'existe
pas avant le troisième chantier.

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
comparaison : quatre drapeaux orthogonaux, deux axes, une cible Make par mesure
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
make seed          # génère data/sorabel.db
make check-sql     # contrôles déterministes du Text-to-SQL (sans appel de modèle)
make eval-sql      # les 24 questions SQL -> eval/rapport_sql.md (un appel LLM chacune)
make test          # suite d'acceptance
make lint          # ruff + mypy
```
