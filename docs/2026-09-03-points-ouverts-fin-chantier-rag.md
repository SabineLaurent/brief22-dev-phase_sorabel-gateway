# Points à garder en tête — fin du chantier RAG (2026-09-03)

Relevé à la clôture du chantier 1 (RAG avancé), avant d'ouvrir le chantier Text-to-SQL.
Ce fichier ne remplace pas `docs/journal-developpement.md` : il rassemble en un endroit ce
qui **reste ouvert et doit être repris plus tard**, avec l'étape où le reprendre.

## 1. Ce que le chantier 1 ne contient pas, par construction

- **`answer_question` n'existe pas.** Le chantier RAG s'arrête à la recherche ; la
  génération de réponse est au chantier MCP (brief, « Chantier Serveur MCP » §1).
  Conséquence : **deux des quatre tests d'acceptance RAG ne peuvent pas passer**
  (`test_answer_question_cite_ses_sources`, `test_hors_corpus_signale_sans_inventer`),
  et un troisième non plus (`search_docs` est un tool MCP). Seul
  `test_gain_hybride_mesure_et_documente` est indépendant du serveur — il passe.
- **La seconde barrière de refus, `contexte_insuffisant`, n'est pas implémentée.**
  Elle suppose un appel au modèle, donc `answer_question` (Q4 §5, §7). Seul
  `hors_corpus` — le seuil — existe aujourd'hui.
- **La matrice d'accès n'est pas appliquée.** Les cinq rôles de l'interface Chainlit
  sont des étiquettes transmises à l'API ; rien ne filtre collections ni documents
  avant le serveur MCP (E4, E5).

## 2. Le point à corriger en premier au chantier suivant

**Le seuil de refus n'est pas branché dans le flux agent → API → Chainlit.**
`search()` a `threshold=None` par défaut, et le tool `search_docs` de
`packages/agent/cli.py` appelle `search(query, strategy=strategy)` sans le passer.
Dans l'interface web, **E1 ne tient donc que par le prompt système** — pas par la
barrière mesurée. Les valeurs calibrées existent pourtant en configuration :
`settings.refusal_threshold = 0.8308` (dense) et `settings.rerank_threshold = 0.0530`
(hybride). À câbler en même temps que `answer_question`, en choisissant le seuil selon
la stratégie — les deux échelles ne sont pas comparables (Q5 §4).

## 3. Résultats de mesure à ne pas oublier

- **Le refus régresse en hybride : 5/8 contre 7/8 en dense.** Trois cas distincts,
  analysés au journal (§825). Le gain E6 est réel sur le Hit@1 — 2/8 → 8/8, MRR 1,000 —
  mais il se paie sur le refus.
- **`rerank_candidates = 20` et `top_k = 5` n'ont jamais été balayés.** `top_k` est
  imposé par la métrique Recall@5, pas par une mesure ; une profondeur de rerank plus
  large pourrait changer le taux de refus sans toucher aux Hit@1, déjà au plafond.
- **Le seuil est calibré sur 8 questions hors corpus.** Limite méthodologique nommée
  (Q4 §6), non corrigeable à cette échelle. Ne pas recalibrer sur le jeu de mesure.
- **`attendu_type` ne prend que trois valeurs** et manque sur RAG-09 : ce sous-ensemble
  détecte une régression, il ne démontre pas un gain.
- **`eval/rapport_gain.md` est généré** par `make mesure` — ne jamais l'éditer à la main.

## 4. Dettes techniques du code livré

- **Le rerank LLM Azure n'a jamais tourné contre un déploiement réel** — même situation
  que `AzureEmbedder` depuis l'étape 1. Prompt et format de sortie sont un pari
  d'implémentation, à revoir à la première exécution réelle.
- **La citation retombe sur `doc_key` quand `reference` est absente** (210 éditions,
  dont les 90 procédures SAV). C'est un contournement assumé, imposé par le test
  d'acceptance qui exige `src["reference"]` non vide sur *chaque* source. À vérifier au
  moment où `answer_question` construira ses sources : la clé de métadonnée, elle, reste
  absente — c'est la citation qui garantit la chaîne.
- **Un document = un chunk, pas de chunker.** Tenable tant que le corpus tient dans la
  fenêtre du modèle d'embeddings ; à revoir si le corpus grossit.
- **Les pickles BM25 encodent des chemins de modules** — à régénérer après tout
  déplacement de paquet, sinon le dépicklage casse.
- **`uv sync` retire l'extra `vector`** : toujours `uv sync --extra vector`, sinon
  l'embedder local est indisponible.

## 5. Rejouer le chantier de bout en bout

```bash
make up && make reindex && make ingest-brut && make check-index
make calibrer && make calibrer-hybride
make mesure
```
