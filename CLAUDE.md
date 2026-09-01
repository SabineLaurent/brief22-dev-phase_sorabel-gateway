# Sorabel Data Gateway — conventions du dépôt

Brief 22 : gateway MCP exposant un RAG avancé et du Text-to-SQL sur les données
Sorabel, sous matrice d'accès et journalisation.

## Où en est le projet

Phase de conception terminée (`LIVRABLES_CONCEPTION/`). Phase de développement en cours.

- **Chantier RAG, étape 1 — ingestion : faite.** `config.py`, `ingest/` (normalize,
  registry, index, cli), `retrieval/embedder.py`, `scripts/check_index.py`. 400 éditions
  indexées dans Chroma, 18 contrôles au vert. Revue de code passée : neuf constats
  corrigés et vérifiés, consignés au journal.
- **Chantier RAG, étape 2 — recherche dense, citations, refus hors corpus : à faire.**
  C'est la prochaine étape.
- Étape 3 (hybride BM25 + rerank, mesure du gain E6), puis chantier Text-to-SQL, puis
  chantier serveur MCP, puis l'interface graphique.

Aucun test d'acceptance ne passe encore : ils exigent tous un serveur MCP, qui n'existe
pas avant le troisième chantier.

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
- `LIVRABLES_CONCEPTION/02-modele-chunk.md` — les onze champs de métadonnées, dont
  **`titre`** et **`n_caracteres`** ;
- `tests/acceptance/` — la suite lit littéralement certaines clés (`src["titre"]`,
  `metadata["doc_type"]`, `hits[0]["doc_id"]`).

La conversion attribut Python → clé de données se fait à un seul endroit par
domaine. Pour le corpus : `build_metadata()` dans `ingest/registry.py`.

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
make check-index   # contrôles d'intégrité de l'index
make seed          # génère data/sorabel.db
make test          # suite d'acceptance
make lint          # ruff + mypy
```
