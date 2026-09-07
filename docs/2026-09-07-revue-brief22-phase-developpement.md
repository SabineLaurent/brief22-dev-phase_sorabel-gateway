# Revue du brief 22 — phase de développement

> Confrontation **exigence par exigence** entre ce que le brief demande pour la phase de
> développement et ce que le code fait réellement. Seconde partie : delta entre le code
> livré et les cinq livrables de `docs/conception/LIVRABLES_CONCEPTION/`.
>
> Établi le 2026-09-07 sur la branche `mcp-second-try` (HEAD `279aabb`), par lecture du
> code et exécution des cibles de vérification. Aucun élément n'est repris d'un schéma de
> conception sans avoir été retrouvé dans le code.

## 0. Vérifications exécutées pour cette revue

| Cible | Résultat mesuré ce jour |
|---|---|
| `make test` (suite d'acceptance, boîte noire stdio) | **12 passed en 48,46 s** |
| `make check-sql` | **81 contrôles au vert** |
| `make check-feedback` | **103 contrôles au vert** (`CLAUDE.md` en annonce 102 — écart de décompte, pas de régression) |
| `make check-rag-tools` | **62 contrôles au vert** |
| `make check-perimetre` | **31 contrôles au vert** |

Rapports chiffrés présents dans `eval/` : `rapport_gain.md`, `rapport_sql.md`,
`rapport_perimetre.md`. **Aucun rapport pour E5.**

---

# Partie A — Les demandes du brief, une par une

## A.1 Chantier RAG avancé

### Étape 1 — « construire l'ingestion du corpus : normalisation PDF/HTML/Markdown, gestion des versions et doublons, chunking, métadonnées (référence produit, version, date), indexation dans Chroma »

| Demande | Où c'est fait | Verdict |
|---|---|---|
| normalisation PDF | `ingest/normalize.py:_read_pdf` — `pypdf`, extraction par regex de `Référence produit`, `Version`, `Date`, titre en 1ʳᵉ ligne | ✅ |
| normalisation HTML | `_read_html` — `BeautifulSoup`, métadonnées dans les `<meta>`, titre en `<title>` puis repli `<h1>` | ✅ |
| normalisation Markdown | `_read_markdown` — frontmatter YAML, thème dérivé du nom de fichier | ✅ |
| gestion des versions | `ingest/registry.py:build_registry` — `doc_key`, `version_sort_key` (1.10 après 1.9), `is_current`. Les **400** éditions sont indexées ; le filtre `is_current` s'applique **à la requête** | ✅ |
| gestion des doublons | Traitée comme un **problème de versions**, pas d'octets : une édition dont le nom de fichier contredit son contenu est **écartée**, et son document perd son édition courante (`undetermined_doc_keys`). Pas de déduplication par empreinte de contenu | ✅ avec réserve — voir §A.4 |
| chunking | **Délibérément absent** : une édition = un chunk. Justifié par la longueur maximale mesurée (923 caractères, < 45 % de la fenêtre e5-base). Documenté en tête de `normalize.py` | ⚠️ écart assumé |
| métadonnées | `ingest/registry.py:build_metadata` — les **onze champs**, conversion attribut → clé de données à un **seul endroit**. `reference` et `theme` **omises** quand absentes (Chroma refuse `None`) | ✅ |
| indexation Chroma | `ingest/index.py:index_editions` — `upsert` sur `edition_id` (idempotent), réconciliation des suppressions, empreinte du modèle d'embeddings dans la métadonnée de collection, index BM25 construit **dans la même passe** | ✅ |

Deux garde-fous que le brief ne demandait pas et qui sont là : `_check_embedding_model()`
refuse une collection construite avec un autre modèle d'embeddings, et
`ChromaEmbeddingFunction.__call__` **lève** plutôt que de laisser Chroma vectoriser une
question avec le préfixe `passage:` (asymétrie e5).

### Étape 2 — « brancher une recherche dense de base avec citations systématiques et refus hors corpus (E1) »

| Demande | Où c'est fait | Verdict |
|---|---|---|
| recherche dense | `retrieval/search.py:_dense_search` / `_dense_query` — `collection.query`, score = `1 - distance` | ✅ |
| citations systématiques | `search.py:citation()` — **construite en Python depuis les métadonnées, jamais rédigée par le modèle**. Repli `reference → doc_key` pour que la clé ne soit jamais vide (imposé par T1, qui interroge une procédure SAV) | ✅ |
| refus hors corpus | `search()` — `threshold` comparé au score du **premier** résultat, **avant tout appel au LLM**. Seuil calibré (`refusal_threshold=0.8308` dense, `rerank_threshold=0.0530` hybride) par `make calibrer` / `calibrer-hybride`, sur `questions_calibration.jsonl` — jamais sur le jeu de mesure | ✅ |

Le module se présente comme « **paramétré, jamais câblé** ». La formule est vraie de la
signature ; elle mérite d'être confrontée aux appelants réels, sinon elle décrit une
souplesse que rien n'exerce. Résultat de ce contrôle :

| Paramètre de `search()` | Qui lui passe une valeur non-défaut | Verdict |
|---|---|---|
| `strategy` | `eval_rag` (dense · lexical · hybrid, via `make mesure-*`), `calibrate_threshold` (dense · hybrid), `tools.py` (hybrid) | **exercé** |
| `text` | `eval_rag --text raw` (`make mesure-sans-nettoyage`) | **exercé** |
| `version_filter` | `eval_rag --version-filter off` (`make mesure-sans-versions`) | **exercé** |
| `tiebreak` | `eval_rag` et `eval_perimeter` passent `False` | **exercé** |
| `perimeter` | `tools.py` (les quatre tools), `eval_perimeter` (P0 vs P1) | **exercé** |
| `settings` · `embedder` · `reranker` | injectés par les deux harnais, pour ne pas recharger un modèle par question | **exercé** |
| `threshold` | `tools.py` seulement — `None` (`search_docs`) ou `threshold_for(strategy)` (`answer_question`) | **exercé, mais étroit** : les deux harnais passent toujours `threshold=None` et appliquent le seuil eux-mêmes après coup, pour observer le score sans que la barrière le masque |
| `top_k` | personne : `eval_rag` passe `settings.search_top_k`, c'est-à-dire le défaut | **jamais varié** |

Quatre points de code que ce contrôle met au jour, et qui n'apparaissaient pas dans la
première version de cette revue :

1. **le garde `strategy="lexical"` + `threshold` est inatteignable.** Il lève `ValueError`
   parce que le score BM25 n'est pas borné — raison juste. Mais aucun appelant ne peut le
   déclencher : `threshold_for("lexical", …)` rend `None` (et `check_rag_tools.py:170` le
   vérifie), et les deux harnais passent `threshold=None` en toutes configurations. C'est
   un **garde défensif jamais franchi et jamais testé** — pas un bug, mais pas une garantie
   vérifiée non plus ;
2. **`strategy="lexical"` / `_lexical_search` ne sont sur aucun chemin servi.** Ils
   n'existent que comme configuration B, le témoin du protocole de mesure. C'est leur
   raison d'être, écrite dans `eval/protocole-mesure.md` — mais la souplesse de `strategy`
   sert la mesure, pas le service : le serveur MCP ne rend jamais autre chose que `hybrid`,
   et `--strategy` a été retiré du banc d'essai exprès ;
3. **`access_rag.search_for_profile()` n'est appelée que par `check_perimeter.py`.** Aucun
   tool ne l'emprunte : `tools.py` appelle `perimeter_for()` puis `search()` directement.
   C'est une **façade sans consommateur en production** ;
4. **`top_k` n'est jamais varié.** `search_top_k = 5` est motivé par la métrique Recall@5 ;
   le paramètre reste utile pour rejouer une mesure, il n'a simplement jamais servi.

Aucun de ces quatre points ne fausse un chiffre publié ni un test. Les deux premiers sont
du code de défense ou de mesure ; le troisième est le seul qu'on puisse retirer sans rien
perdre — et le retirer obligerait à déplacer son contrôle de parité dans
`check_perimeter.py`.

### Étape 3 — « passer en recherche hybride (+ reranking) et mesurer le gain sur eval/questions_rag.jsonl, notamment les questions par référence exacte (E2, E6) »

| Demande | Où c'est fait | Verdict |
|---|---|---|
| BM25 | `retrieval/lexical.py` — `rank_bm25`, index sérialisé à l'ingestion, cache sur `(chemin, mtime)`, garde-fou de schéma sur un pickle antérieur au filtre de périmètre | ✅ |
| fusion | `search.py:_reciprocal_rank_fusion` — RRF, `k=60`, fusion **sur les rangs** et non sur les scores | ✅ |
| reranking | `retrieval/reranker.py` — deux implémentations commutables par configuration : cross-encoder local `mmarco-mMiniLMv2` (mMARCO car le corpus est français) et LLM-juge Azure. Score **toujours borné [0,1]** (sigmoïde), condition pour qu'un seuil soit une opération sensée | ✅ |
| mesure du gain | `evals_and_controls/eval_rag.py`, sept cibles `mesure-*`, `eval/rapport_gain.md` | ✅ |

Chiffres publiés (`eval/rapport_gain.md`, sous-ensemble `reference_exacte`, n=8) :

| Métrique | A dense | B lexical | C hybride |
|---|---:|---:|---:|
| Hit@1 (référence) | 1/8 | 3/8 | **8/8** |
| Hit@1 (fiche technique) | 1/8 | 3/8 | **8/8** |
| MRR | 0,375 | 0,688 | **1,000** |
| refus corrects (`hors_corpus`, n=8) | 7/8 | n/a | **5/8** |

Le rapport publie aussi ses limites méthodologiques (échantillon de 8, `attendu_type` à
trois valeurs, deux questions en tension avec le corpus) et une règle de départage
explicite — fiche technique devant notice à référence égale — qui **ne lit jamais la
question**, seulement les métadonnées des résultats, pour que le gain mesuré ne vienne pas
de la règle.

**Ce que la ligne « refus corrects » mesure — et ce qu'elle ne mesure pas.** Lue de travers,
elle dit que la configuration servie refuse moins bien que la dense (5/8 contre 7/8), donc
un recul sur la seconde moitié d'E1. **C'est faux, et c'est le rapport qui prête à
confusion** : `eval_rag.py` appelle `search()` puis compare le score du premier résultat au
seuil — il mesure donc la **barrière 1 seule**, sur l'étage de recherche. Or E1 vit dans
`answer_question`, qui en a **deux**.

Mesuré ce jour, les 8 questions `hors_corpus` traversant `answer_question` au profil
`commercial` :

| Question | Barrière 1 (seuil) | Verdict servi |
|---|---|---|
| RAG-25 · 26 · 27 · 28 · 30 | refuse (0,0015 – 0,0175) | `hors_corpus` |
| RAG-23 (0,0868) · RAG-24 (0,8422) · RAG-29 (0,5175) | **laisse passer** | `contexte_insuffisant` — rattrapé par la barrière 2 |

**Refus corrects réels : 8/8.** La barrière 2 rattrape exactement les trois que le seuil
laisse passer. Ce qui manque n'est donc pas une amélioration du refus, c'est **une mesure
publiée du refus tel qu'il est servi** — voir §A.7.

## A.2 Chantier Text-to-SQL

### Étape 1 — « implémenter get_schema puis le tool génératif ask_database : génération sur schéma commenté, validation lecture seule, périmètre de tables par profil, requête renvoyée avec le résultat (E3, E5) »

| Demande | Où c'est fait | Verdict |
|---|---|---|
| `get_schema` | `text_to_sql_factory/tools.py:get_schema` — rend `contract.as_text()`, **aucun argument exposé** | ✅ |
| schéma commenté | `contract.py:build_read_contract` — cinq blocs : DDL filtré + commentaires colonne par colonne, énumérations exactes, plage temporelle réelle, exemples question→SQL, conventions métier. **Aucun échantillon de lignes** : il ferait fuiter `prix_achat_ht` dans le prompt, en amont de toute validation. **Un seul artefact, deux consommateurs** — le prompt d'`ask_database` et `get_schema` | ✅ |
| génération | `generator.py` — **une passe**, sortie JSON imposée, trois branches `{sql}` / `{clarification}` / `{refus}` ; exactement une remplie sinon `panne` | ✅ |
| validation lecture seule | `validator.py` — 5 contrôles sqlglot + `LIMIT` + contrôle 6 `EXPLAIN`. **Aucune liste de mots interdits** : `VACUUM INTO 'copie.db'` exfiltre la base sans écrire | ✅ |
| périmètre par profil | `validator.py` contrôle **5a tables puis 5b colonnes** — l'ordre est la garantie : `qualify` ne résout pas les colonnes d'une table qu'il ignore. `referenced_columns()` résout les **alias par scope** (sans quoi `SUM(v.marge_ht)` passerait) et porte sur **toute occurrence**, pas la projection (`ORDER BY marge_pct` sans la projeter) | ✅ |
| lecture seule à la connexion | `executor.py:_connect` — `mode=ro` **et** `PRAGMA query_only=ON`, connexion **neuve à chaque requête** | ✅ |
| requête renvoyée avec le résultat | `tools.py:_from_execution` — `sql` **systématiquement** dans le payload, pas sur demande. `PAYLOAD_KEPT` le conserve sur les codes de résultat, et le retire sur les refus (une requête refusée n'a pas été exécutée) | ✅ |
| bornes | `sql_default_limit=200` injecté s'il manque et **jamais en remplacement d'un LIMIT plus petit**, `sql_max_rows=1000`, `sql_timeout_s=5` via `set_progress_handler` | ✅ |

### Étape 2 — « implémenter les tools SQL figés (check_stock(ref), order_status(order_id)) et le refus propre des questions ambiguës ou hors schéma »

| Demande | Où c'est fait | Verdict |
|---|---|---|
| `check_stock` | `tools.py:check_stock` — requête figée paramétrée, **une ligne par entrepôt + total**, `sous_seuil` par ligne jamais agrégé (les seuils diffèrent par entrepôt), argument validé `^REF-\d{4}$` | ✅ |
| `order_status` | requête figée paramétrée, en-tête seul, argument validé `^CMD-\d{4}-\d{4}$` | ✅ |
| le figement ne dispense pas de la matrice | `_forbidden()` confronte les colonnes de sortie de chaque tool figé au `Scope` du profil | ✅ |
| refus ambiguë | branche `clarification` — **axes fermés calculés par le code** (`clarification_axes`) et filtrés par la matrice (5 au commercial, 4 au support), jamais les chaînes libres du modèle. Plus une 4ᵉ décision **après** exécution que le modèle ne peut pas prendre : `ambiguite_donnees` (`_filters_on_label`, égalité à la frontière du classement) | ✅ |
| refus hors schéma | branche `refus` + `_refusal_out_of_scope()` qui **requalifie** en `perimetre_interdit` quand la question désigne une colonne fermée — sinon le support s'entendrait dire « la base ne porte pas cette donnée » sur une donnée qui existe et lui est seulement fermée | ✅ |

**Écart déjà consigné, refermé depuis** : le brief nomme E5 dans cette étape et T2 exige un
refus « journalisé ». La journalisation a été reportée au chantier 3 et y est écrite une
fois pour les huit tools. Elle est en place aujourd'hui.

## A.3 Chantier Serveur MCP

### Étape 1 — « implémenter le serveur MCP exposant le catalogue : answer_question, search_docs, get_document, list_sources, ask_database, get_schema, check_stock, order_status »

`mcp_server/server.py` — `FastMCP`, transport stdio, les **huit** tools déclarés, tous
annotés `readOnlyHint=True, idempotentHint=True, openWorldHint=False`. Deux points d'entrée
(`python -m mcp_server.server`, forme du contrat DSI, et `python -m mcp_server`).
✅

Deux choix structurels qui se lisent dans le fichier :

- **le profil est lu dans `SORABEL_PROFILE`, une fois au chargement du module.** Il
  n'apparaît dans la signature d'aucun tool — un paramètre dans l'`inputSchema` serait
  rempli par le LLM du client ;
- **les imports du domaine documentaire sont locaux aux fonctions de tool.** Contrainte de
  protocole : `initialize` a 30 s, un import au niveau du module chargerait l'embedder
  avant la poignée de main.

Les descriptions sont le **seul aiguillage** — aucun code ne choisit le tool — et chacune
dit vers quoi renvoyer quand ce n'est pas elle.

### Étape 2 — « appliquer la matrice d'accès et la journalisation de tous les appels, autorisés comme refusés (E4, E5) »

Trois étages, et ils ne font pas le même travail :

| Étage | Où | Nature | Code produit |
|---|---|---|---|
| 1 — `tools/list` filtré | `SorabelMCP.list_tools` | ergonomie (le LLM ne voit pas ce qu'il ne peut pas appeler) | aucun |
| 2 — droit d'appeler le tool | `text_to_sql_factory/handler.py` et `rag_machines/handler.py`, tous deux par `packages/access.py:authorize` | **garantie**, journalisée | `tool_interdit` |
| 3 — périmètre | `validator.py` (5a/5b), `retrieval/perimeter.py`, `tools.py:_resolve_perimeter` / `get_document` | **garantie**, journalisée | `perimetre_interdit` |

La matrice est une **donnée versionnée** (`mcp_server/matrice.yaml`) lue à un seul endroit ;
aucun `if profile ==` dans le code métier. `scope_for()` est **totale** : profil absent,
inconnu ou mal typé → `default`, zéro droit, jamais de `KeyError`.

Le périmètre documentaire est appliqué **avant la troncature**, côté Chroma comme côté
BM25, et sa clause `where` est une **disjonction** — une conjonction ne rendrait que des
notes, puisque les 320 non-notes n'ont pas de clé `theme` et que Chroma évalue à faux toute
comparaison sur une clé absente.

Journalisation : `packages/journal.py`, JSONL, une ligne par appel, transverse aux huit
tools par le protocole structurel `Journalable`. L'ordre dans les deux handlers est
**journaliser l'objet entier, puis purger** — jamais l'inverse. Aucune exception ne sort de
`handle()` : un appel se termine toujours par une entrée et une réponse.

Séparation des deux lecteurs, structurelle et non conventionnelle : `cause`, `stack`,
`forbidden`, `etage` sont des **attributs de dataclass, jamais des clés de dict**, et le
seul sérialiseur par domaine travaille sur **liste blanche** (`PAYLOAD_KEPT`). Le client lit
une **phrase figée choisie sur le code** ; le texte du modèle, le message SQLite et la trace
d'exception partent au journal.

✅ E4 et E5 tenues côté mécanisme.

### Étape 3 — « documenter le catalogue pour les équipes clientes et démontrer deux profils différents avec scripts/mcp_client.py (support vs commercial) »

| Demande | État |
|---|---|
| démontrer deux profils avec `scripts/mcp_client.py` | ✅ — `--profile {support,commercial}`, lance le serveur en sous-processus stdio, imprime le catalogue filtré puis appelle un tool. `make client PROFILE=…` |
| documenter le catalogue pour les équipes clientes | ❌ **absent** — voir §A.4 |

## A.4 Ce qui manque, et ce qui est un écart assumé

### Manquant

| # | Attendu | Statut |
|---|---|---|
| 1 | **Le mini guide d'accès** — livrable explicite : « Le serveur MCP (mcp_server/) exposant le catalogue complet **ainsi qu'un mini guide d'accès** » | ❌ n'existe pas. Aucun fichier du dépôt ne le porte ; c'est aussi l'endroit du bloc de configuration stdio pour un client externe, donc la réponse à « essai du service » |
| 2 | **E5 démontrée par une preuve chiffrée** | ❌ **E5 est la seule des six exigences sans mesure publiée.** Le champ `blocked_at` est posé sur les huit tools, mais il n'existe ni cible `make mesure-acces` ni `eval/rapport_acces.md` |
| 3 | **« Un lien d'une interface graphique du produit fonctionnel »** | ⚠️ partiel — l'interface Chainlit existe et fonctionne (`make web`, port 8100, adossée à `make api`), avec cinq rôles qui agissent réellement (un sous-processus serveur par profil). Mais **aucune URL** n'est publiée : le livrable demande un lien |

### Écarts assumés, tranchés et traçables dans le code

| Écart | Justification écrite dans le code |
|---|---|
| **pas de chunker** | une édition = un chunk ; 923 caractères au maximum mesuré, < 45 % de la fenêtre d'embedding (`normalize.py`, en-tête) |
| **pas de déduplication par contenu** | le corpus ne porte aucun doublon d'octets ; le « doublon » réel est la version multiple, traitée par `registry.py` |
| **noms d'arguments** `search_docs(query)`, `get_document(doc_id)` | la suite d'acceptance fait foi sur `03-catalogue-tools.md` (`question`, `doc_key`) — règle d'arbitrage du dépôt |
| **`get_schema` retiré à `support`** | T9, T10, T12 attendent un `refused` ; sans effet tant que rien n'exerçait l'étage 2, bloquant dès que le handler l'exerce |
| **contrôle 6 `EXPLAIN` ajouté** | l'arbre ne voit pas ce que le moteur voit (`DATE_TRUNC`, colonne inventée, ambiguïté de jointure) ; **en dernier**, après que la matrice a tranché |
| **une reprise sur requête fausse** | `Verdict.repairable`, posé par le **seul** contrôle 6 — jamais sur un refus de droits, qui ne se renégocie pas |
| **`--strategy` retiré du banc d'essai** | les tools MCP n'exposent pas d'étage de recherche : c'est le serveur qui décide ; `make mesure-*` reste l'endroit pour comparer |

## A.7 Le refus documentaire, mesuré des deux côtés

Section ajoutée après coup : la première version de cette revue lisait la ligne « refus
corrects » du rapport E6 comme une mesure d'E1, ce qu'elle n'est pas (§A.1 étape 2). Voici
la mesure du refus **tel qu'il est servi**, les deux barrières traversées, profil
`commercial`, faite ce jour sur les 30 questions de `questions_rag.jsonl`.

### Les deux chiffres

| | Résultat |
|---|---|
| **Refus corrects** sur les 8 `hors_corpus` | **8/8** |
| **Faux refus** sur les 22 questions à cible | **5/22** — dont **2 seulement sont un défaut** |

### Les cinq faux refus, un par un

| Question | Code | Score barrière 1 | Diagnostic |
|---|---|---:|---|
| RAG-03 « REF-5313 » | `contexte_insuffisant` | 1,0000 | **défaut réel** — le retrieval est parfait, mais une **référence nue n'est pas une question** : le rédacteur cherche une question, n'en trouve pas, déclare l'insuffisance |
| RAG-05 « REF-5719 » | `contexte_insuffisant` | 1,0000 | **défaut réel**, même cause |
| RAG-18 « comment demander un duplicata de facture ? » | `contexte_insuffisant` (stable 3/3) | 0,9377 | **refus correct.** Le corpus porte bien `proc-demande-duplicata-facture-01`, mais « duplicata » n'apparaît **que dans son titre** : son corps est le passe-partout des 80 procédures — ouvrir un dossier SAV, joindre des photos de la panne, délais d'échange. Rien sur les factures. Déjà signalé par `rapport_gain.md` (« le titre est le seul discriminant ») |
| RAG-19 | `hors_corpus` | 0,0049 | **refus correct** — sujet absent du corpus, déjà signalé comme « en tension » |
| RAG-20 « quelle section de conducteur pour un disjoncteur 40 A ? » | `contexte_insuffisant` (stable 3/3) | 0,9951 | **refus correct** — déjà signalé, terme présent en notice seulement |

### Pourquoi il ne faut **pas** relever le seuil du reranker

Les deux populations se chevauchent **irréductiblement** sur l'échelle du reranker :

| Population | Étendue des scores du premier résultat |
|---|---|
| `reference_exacte` (8) | 0,9998 – 1,0000 |
| `couverte` (14) | **0,0049** · 0,0732 · 0,4178 … 0,9997 |
| `hors_corpus` (8) | 0,0015 … 0,5175 · **0,8422** |

Aucun seuil ne les sépare : le minimum couvert (0,0049) est très en dessous du maximum
hors corpus (0,8422). Relever `rerank_threshold` de 0,0530 à 0,09 pour attraper RAG-23
(0,0868) refuserait RAG-13 (0,0732), une question réellement couverte. **Le seuil bas est
le bon réglage** : la barrière 1 est un pré-filtre bon marché — elle économise un appel LLM
sur 5 questions hors corpus sur 8 —, la barrière 2 est le juge.

*(À noter, pour l'honnêteté de la comparaison : la barrière 1 dense « réussit » 7/8 dans une
bande de scores de 0,798 à 0,845 pour un seuil à 0,8308 — soit une marge de 0,014 sur RAG-29.
Ce n'est pas une meilleure séparation, c'est une similarité cosinus comprimée et un seuil
posé au milieu de la bande.)*

### Le correctif de la référence nue, testé

Testé hors dépôt, sur les 5 questions concernées : la recherche garde la référence **nue**
— c'est elle que BM25 attrape, score 1,0000 — et **seule la question transmise à
`writer.write()`** est explicitée en « Quelles sont les caractéristiques de la référence
X ? ».

| Question | Avant | Après |
|---|---|---|
| RAG-03 · RAG-05 | `contexte_insuffisant` | **`ok`** |
| RAG-18 · RAG-20 | `contexte_insuffisant` | `contexte_insuffisant` — **inchangé** |
| RAG-23 (hors corpus) | `contexte_insuffisant` | `contexte_insuffisant` — **inchangé** |

**Variante écartée, et la mesure qui la disqualifie** : porter la même règle dans le
`_SYSTEM_PROMPT` du rédacteur corrige aussi RAG-03 et RAG-05, mais **desserre la barrière 2
au-delà du cas visé** — RAG-18 et RAG-20, stables en `contexte_insuffisant` sur trois
passes, basculent en `ok`. Sur RAG-18 c'est un recul d'E1 : le corpus ne porte pas cette
réponse, et le modèle la composerait quand même. Une règle générale dans le prompt ne sait
pas rester locale ; un cas nommé dans le code, si.

## A.5 Les six exigences DSI

| # | Exigence | Tenue par | Preuve |
|---|---|---|---|
| **E1** | citations systématiques + refus hors corpus | `search.py:citation()` (construite en Python), deux barrières dans `answer_question` : seuil `hors_corpus` **avant** tout appel au modèle, puis garde de suffisance `contexte_insuffisant`. Sur ces deux codes, `answer` est **absent du payload** — un client n'a rien à afficher | T1 et T2 passent ; **8/8 refus corrects mesurés sur les deux barrières** (§A.7). Le 5/8 de `rapport_gain.md` ne concerne que la barrière 1, sur `search_docs` — **à ne pas lire comme une mesure d'E1** |
| **E2** | référence exacte **et** langage naturel | BM25 rattrape `REF-8842` (jeton à IDF élevé), le dense couvre la synonymie, RRF les fusionne, la règle de départage tranche fiche/notice | T3 passe ; Hit@1 8/8, MRR 1,000 |
| **E3** | lecture seule + tables autorisées + requête tracée | 6 contrôles sqlglot/`EXPLAIN`, connexion `mode=ro` + `query_only` neuve, `sql` toujours dans le payload de résultat | T5, T6, T8 passent ; `rapport_sql.md` 24/24 dont 4/4 `ecriture` |
| **E4** | un serveur, matrice par client | un processus par profil, `SORABEL_PROFILE`, trois étages, matrice en donnée | T9, T10, T11 passent |
| **E5** | tout appel journalisé + colonnes sensibles jamais au support | `journal.record()` sur le chemin unique des deux handlers ; trois colonnes fermées ensemble à `support` et `dev` (fermeture par dérivation) | T6, T7, T10, T12 passent ; `check-sql` 81 · `check-feedback` 103. **Aucune mesure chiffrée publiée** |
| **E6** | gain mesuré et documenté | protocole arrêté **avant** l'implémentation (`eval/protocole-mesure.md`), 4 drapeaux orthogonaux, une cible Make par mesure | `eval/rapport_gain.md` : 1/8 → 8/8 |

## A.6 Les douze tests d'acceptance

`make test` → **12 passed, 48,46 s**. Tous verts, vérifié ce jour.

| Volet | Test | Ce que le code y répond |
|---|---|---|
| RAG | sources titre+référence+date | `citation()` avec repli `reference → doc_key` (la question porte sur une procédure SAV, qui n'a pas de référence) |
| RAG | hors corpus signalé sans inventer | `status="hors_corpus"`, phrase figée, `answer` hors de `PAYLOAD_KEPT` |
| RAG | `REF-8842` en tête via `search_docs` | hybride + départage → fiche technique au rang 1 |
| RAG | gain mesuré et documenté | `eval/rapport_gain.md` (le test lit le fichier et exige des chiffres) |
| SQL | résultat + requête | `payload["sql"]` systématique |
| SQL | écriture refusée et journalisée | branche `refus`/`motive="ecriture"` ou contrôles 1–4 → `ecriture_refusee`, journalisé |
| SQL | support jamais de marge | `_refusal_out_of_scope` ou contrôle 5b → `perimetre_interdit`, aucune ligne |
| SQL | hors schéma refusé proprement | branche `refus`/`hors_schema`, aucune requête produite ni tentée |
| MCP | matrice respectée | étage 2 dans les deux handlers |
| MCP | refus clair et journalisé | phrase figée + entrée `denied` |
| MCP | `search_docs` puis `get_document` | deux tools indépendants, `doc_id` = `edition_id` d'un hit |
| MCP | journal exhaustif | une ligne par appel, ordre préservé, `refused` et non-`refused` présents |

---

# Partie B — Delta entre le code et les livrables de conception

Périmètre : `docs/conception/LIVRABLES_CONCEPTION/` (`01-flux-complet.md`,
`02-modele-chunk.md`, `03-catalogue-tools.md`, `04-chemin-text-to-sql.md`, `matrice.yaml`,
`README.md`).

**Règle d'arbitrage du dépôt, appliquée ici :** quand la conception, `docs/cadrage_dsi.md`
et `tests/` divergent, **le test fait foi**, puis le cadrage.

## B.1 Le delta majeur — la forme de la réponse

C'est le seul écart de structure, et il touche les huit tools.

| | Conception (`03-catalogue-tools.md` §4) | Code |
|---|---|---|
| Forme | `outputSchema` d'union par tool, `structuredContent` **et** duplicata `TextContent` | `{"status", "payload", "message"}` de `docs/cadrage_dsi.md`, sérialisé en JSON dans un unique `TextContent` |
| Champ décisionnel | `code` requis dans tous les cas | `status` (5 valeurs) en surface, `code` conservé dans `payload["code"]` |
| `isError` | tranché tool par tool sur les douze codes | **jamais posé** — les tools rendent `str`, FastMCP ne marque rien en erreur |
| `outputSchema` | spécifié pour chaque tool | **non déclaré** |
| `hint` (le recours) | champ du socle commun | **absent** |
| Clés de payload | `reponse`, `citations` | `answer`, `sources` (forme du cadrage) |

**Ce n'est pas une régression, c'est une substitution de contrat** : la suite d'acceptance
lit littéralement `result["status"]`, `payload["answer"]`, `payload["sources"]`,
`payload["hits"][0]["doc_id"]`. La conception avait conçu la forme MCP 2026-07-28 ; le
cadrage DSI impose la sienne, et les tests la vérifient. **Ce qui est perdu au passage** :
le mécanisme `structuredContent`/`isError` que `03-catalogue-tools.md` §4 défendait comme
« le chemin correct sans avoir à y penser » pour le client. Aujourd'hui, la protection
équivalente est obtenue autrement — par l'absence de la clé `answer` sur les non-réponses
(`PAYLOAD_KEPT`) — donc l'intention est tenue, le mécanisme non.

Les **douze codes** de la conception sont tous présents, répartis sur deux tables :
9 côté SQL (`DB_STATUS_BY_CODE`), 8 côté RAG (`RAG_STATUS_BY_CODE`), union = 12.
Le choix de **couches parallèles et non partagées** est un ajout du développement, justifié
en tête de `rag_machines/structured_answer.py` (codes disjoints, 183 contrôles SQL au vert
à ne pas toucher) ; ce qui est partagé l'est par le protocole `Journalable`.

## B.2 `01-flux-complet.md`

| Élément du schéma | Code | Delta |
|---|---|---|
| serveur MCP comme barrière unique, clients au-dessus, sources en dessous | `mcp_server/server.py` — aucun client n'atteint Chroma ni SQLite | conforme |
| `SORABEL_PROFILE` lu dans l'environnement | `PROFILE = os.environ.get("SORABEL_PROFILE", "support")` au chargement du module | conforme |
| 3 étages : « `tools/list` filtré · **intercepteur d'entrée** · dans le tool » | l'étage 2 est dans les **deux handlers**, pas dans un intercepteur de serveur | ⚠️ **écart de forme** — même garantie, autre emplacement. Aucun tool n'a de chemin dérobé : le serveur ne peut appeler un tool qu'à travers `handle_request` |
| filtre d'index par profil, en disjonction | `retrieval/perimeter.py:Perimeter.where` | conforme, y compris la disjonction |
| BM25 ∥ dense → RRF k=60 → rerank → 2 barrières | `_hybrid_search`, `_RRF_K = 60`, `answer_question` | conforme |
| contrat de lecture → base « DDL seul, jamais de lignes » | `contract.py` — aucun échantillon de lignes | conforme |
| tout aboutit au journal, `etage` rend la défense vérifiable | `journal.entry_for` porte `etage` **et** `blocked_at` | conforme, enrichi |
| 4 profils | **5** : `default`, `dev`, `support`, `commercial`, **`admin`** | ➕ ajout du développement, motivé (le rôle `admin` de l'UI retombait sur `default`) et le seul porteur de `read_journal` |

## B.3 `02-modele-chunk.md`

| Élément | Code | Delta |
|---|---|---|
| une édition = un chunk, 400 indexées / 350 courantes | `registry.py` | conforme |
| les onze champs, tous scalaires | `build_metadata()` | conforme |
| clé **omise** quand absente, jamais vide ni `None` | `build_metadata` n'ajoute `reference` / `theme` que si présents | conforme |
| `doc_type` **est** la collection, la matrice filtre dessus | `matrice.yaml` → `collections`, `Perimeter.doc_types` | conforme |
| dérivation `edition_id` / `doc_key` | `normalize._identifiers` | conforme |
| `n_caracteres` mesure le **texte indexé** | `edition.text_for(profile)`, un seul endroit décide | conforme |
| JSON Schema : `doc_key` « **seul** mode d'adressage de `get_document` » | `get_document` accepte `edition_id` **et** `doc_key` | ⚠️ delta — imposé par T11, qui lui passe le `doc_id` d'un hit de `search_docs`, c'est-à-dire un `edition_id` |
| citation = `titre + version + date` (+ `reference` quand elle existe) | `citation()` rend toujours `reference` non vide, par **repli sur `doc_key`** | ⚠️ delta — imposé par T1, qui exige `src["reference"].strip()` sur chaque source d'une procédure SAV. La **métadonnée** reste fidèle (clé omise) ; c'est la **citation** qui garantit la chaîne |
| `n_caracteres` `maximum: 923` | aucune validation à l'ingestion contre ce plafond | mineur — le schéma n'est pas exécuté |

## B.4 `03-catalogue-tools.md`

Au-delà du delta de forme (§B.1) :

| Élément | Code | Delta |
|---|---|---|
| 8 tools, 8 descriptions écrites « contre le tool voisin » | `server.py` — chaque description nomme le tool de repli | conforme |
| `readOnlyHint: true` sur les huit | `_READ_ONLY = ToolAnnotations(readOnlyHint=True, …)` | conforme |
| `inputSchema` avec `pattern` sur `check_stock` / `order_status` | `Annotated[str, Field(pattern=…)]` **et** re-validation dans le tool | conforme, doublé |
| `answer_question(question, **collections**)` · `search_docs(…, collections)` · `list_sources(collections)` | l'argument `collections` existe dans la bibliothèque et dans les handlers, mais **n'est pas exposé** par les tools MCP | ⚠️ **delta fonctionnel** — la logique de refus sur collection explicitement fermée (`_resolve_perimeter`) est écrite, testée par `check-rag-tools`, mais **inatteignable depuis un client MCP** |
| `search_docs(question)` · `get_document(doc_key)` | `search_docs(query)` · `get_document(doc_id)` | écart assumé — le test fait foi |
| `check_stock(ref)` | `check_stock(reference)` | écart assumé — T12 appelle `{"reference": …}` |
| `top_k` de `search_docs` « point ouvert, à trancher au développement » | `search_top_k = 5` dans `config.py`, motivé par la métrique Recall@5 | ✅ **point ouvert refermé** |
| `list_sources` → « par collection : nombre de documents et d'éditions, `doc_key`, plage de dates » | liste **plate** de sources (`doc_id`, `titre`, `reference`, `version`, `date`, `doc_key`, `doc_type`), triée | ⚠️ delta — c'est la forme du **cadrage** (`{"sources": [{"doc_id","titre","reference","version","date","doc_type"}]}`), pas celle de la conception. Le filtrage par périmètre, lui, est bien construit depuis `Perimeter.where()` et non par parcours du corpus |
| `check_stock` colonnes : `stocks.*` **+ `produits.ref`, `produits.nom`** | `_STOCK_SQL` ne touche que `stocks` ; `_STOCK_COLUMNS` ne déclare que `stocks` | mineur — le nom du produit n'est pas rendu ; cohérent avec « un libellé n'identifie pas un produit » |
| codes de `get_schema` : `ok` · `tool_interdit` | + `perimetre_interdit` (profil sans périmètre) et `erreur_execution` | ➕ enrichissement |
| journal : `ts` · `client` · `profil` · `tool` · `args` · `decision` · `etage` · `code` · `sql` · `n_rows` · **`citations`** · `latency_ms` | `timestamp`, `profile`, `tool`, `arguments`, `status`, `message`, `code`, `decision`, `etage`, `blocked_at`, `sql`, `n_rows`, `latency_ms`, `forbidden`, `cause`, `client_message`, `stack` | ⚠️ **`citations` absent** du journal (E1 n'est donc pas retraçable après coup depuis le journal) · **`client` absent** (un processus par profil en stdio : il n'y a pas d'identité de client à écrire) · ➕ `blocked_at`, `forbidden`, `cause`, `stack`, `client_message` ajoutés |
| étage 1 « ergonomie, pas sécurité » | `SorabelMCP.list_tools` filtre, et l'appel non listé est **quand même** refusé à l'étage 2 | conforme, et vérifié par T9 |

## B.5 `04-chemin-text-to-sql.md`

| Élément | Code | Delta |
|---|---|---|
| étage 2 → N1 périmètre → N2 contrat → N3 LLM : **la matrice parle avant le modèle** | `handler` → `_denied_scope` → `build_read_contract` → `generator.generate` | conforme |
| **« cinq contrôles »**, `EXPLAIN` explicitement **retiré de la V3** | **six contrôles** : les cinq de l'arbre, le `LIMIT`, puis le contrôle 6 `EXPLAIN` | ⚠️ **delta assumé et inversé** — la conception avait retiré `EXPLAIN` faute de trace argumentative ; le développement l'a réintroduit, en **dernier** (après la matrice), avec une raison écrite : l'arbre ne voit pas `DATE_TRUNC`, une colonne inventée, une ambiguïté de jointure. « Ça se prépare » ≠ « c'est permis » |
| **« un seul aller-retour avec le LLM, pas de boucle de correction »** | jusqu'à **deux** passes : la génération, plus **une** reprise si et seulement si le contrôle 6 a posé `repairable` | ⚠️ **delta assumé** — jamais sur un refus de droits ; `rapport_sql.md` mesure **0/24** reprises réellement déclenchées sur le jeu |
| N5 `LIMIT` injecté s'il manque | `_apply_limit` — et **jamais** en remplacement d'un `LIMIT` plus petit déjà présent | conforme, affiné |
| N7 trois contrôles de code, aucune passe LLM | `execute()` — vide, égalité à la frontière du classement, homonymie | conforme |
| `ecriture_refusee` journalisé `etage=3` | `etage=3` quand le refus vient du **validateur** ; **aucun étage** quand il vient de la branche `refus` du modèle | ⚠️ mineur, et volontaire : « c'est le modèle qui a refusé, pas une barrière ; le journal ne doit pas lui en attribuer une » |
| `check_stock` / `order_status` traversent « étage 2 · N1 · N6 · N7 » | `_denied_scope` + `_forbidden` + `execute_with_parameters` | conforme |

## B.6 `matrice.yaml` — conception vs exécution

`docs/conception/LIVRABLES_CONCEPTION/matrice.yaml` est la **source**,
`mcp_server/matrice.yaml` la **copie exécutée**. Elles diffèrent en trois points, tous
tracés :

| # | Différence | Motif écrit dans le fichier exécuté |
|---|---|---|
| 1 | `get_schema` **retiré** à `support` | T9, T10, T12 attendent un `refused` ; l'arbitrage était consigné, il est devenu bloquant dès que l'étage 2 s'exerce. Aligne aussi la matrice sur `docs/cadrage_dsi.md`, qui ne donne `get_schema` qu'au `commercial` |
| 2 | profil **`admin`** ajouté (8 tools + `read_journal`, 28 colonnes du commercial) | sans lui, le rôle `admin` de l'UI retombait sur `default` ; seul lecteur du journal, car le journal contient la matrice en creux |
| 3 | `clients.email` fermée aux **cinq** profils au lieu de quatre | corollaire du point 2 ; motif RGPD, pas E5 |

Le reste est identique : liste blanche partout, `default` à zéro droit, les trois colonnes
sensibles fermées ensemble à `support` **et** `dev` (fermeture par dérivation),
`stocks.id` / `ventes.id` exclues, décomptes 28 / 25 / 25 / 0.

**Delta avec `docs/cadrage_dsi.md` — à connaître, car c'est le cadrage qui est normatif
pour la DSI**, et il est plus restrictif que la matrice implémentée sur deux points :

| Point | Cadrage DSI | Matrice implémentée |
|---|---|---|
| notes internes | « réservées au profil `commercial` » | `support` a `note_interne` sur **3 thèmes** (`alerte-qualite`, `logistique`, `retour-terrain`) — 318 éditions |
| table `ventes` pour `support` | « ventes.* (table non accessible) » | `support` lit `ventes` **moins `marge_ht`** (5 colonnes sur 6) |

Les deux sont argumentés dans la conception (`Q3` §6 : fermer `note_interne` coûterait au
support ses 16 notes `alerte-qualite`, son métier même ; le grain est le thème). Aucun test
ne les exerce dans un sens ni dans l'autre — **ils restent donc un choix à défendre en
soutenance, pas un fait vérifié par la suite**.

## B.7 Deux dérives documentaires mineures

- `eval/rapport_gain.md` annonce « Généré par `scripts/eval_rag.py --report` » ; le script
  vit désormais dans `packages/rag_machines/evals_and_controls/eval_rag.py`. Le rapport
  n'est pas faux, son en-tête l'est ;
- `packages/web_client/app.py` porte encore, en docstring, « Écart assumé […] ici c'est le
  client qui déclare son rôle […] Il disparaît avec le serveur MCP ». L'écart **est** refermé
  depuis l'étape C : le rôle choisit désormais *quel processus* on interroge, jamais *quel
  argument* on passe (`packages/agent/gateway.py`, `api.py`).

---

## Synthèse

| Bloc du brief | État |
|---|---|
| Chantier RAG — étapes 1, 2, 3 | ✅ complet, mesuré, publié |
| Chantier Text-to-SQL — étapes 1, 2 | ✅ complet, mesuré, publié |
| Chantier MCP — étape 1 (serveur, 8 tools) | ✅ |
| Chantier MCP — étape 2 (matrice + journal) | ✅ mécanisme complet, **preuve chiffrée manquante (E5)** |
| Chantier MCP — étape 3 (démo 2 profils) | ✅ `scripts/mcp_client.py` |
| Chantier MCP — étape 3 (documenter le catalogue) | ❌ mini guide d'accès absent |
| Livrable « lien d'une IGU fonctionnelle » | ⚠️ interface existante, pas de lien |
| Tests d'acceptance | ✅ 12/12, vérifié ce jour (48,46 s) |
| E1 · E2 · E3 · E4 · E6 | ✅ tenues et chiffrées |
| E5 | ✅ tenue, ❌ **non chiffrée** — seule des six dans ce cas |

Trois choses à faire, dans cet ordre d'exigence : **le mini guide d'accès** (livrable
nommé), **`make mesure-acces` → `eval/rapport_acces.md`** (E5, le champ `blocked_at` est
déjà posé), **une URL pour l'IGU**.

Deux propositions issues de §A.7, par ordre de rendement :

1. **`make mesure-refus` → `eval/rapport_refus.md`** — publier le refus documentaire tel
   qu'il est **servi**, les deux barrières traversées, avec ses deux colonnes : refus
   corrects **8/8**, faux refus **5/22** puis **2/22** après le correctif ci-dessous. Le
   chiffre existe déjà ; c'est un script de mesure, aucun code de production touché. C'est
   ce rapport qui manquait, pas une amélioration du refus — et son absence a suffi à faire
   lire le 5/8 de la barrière 1 comme un recul d'E1 ;
2. **le correctif de la référence nue** — 3 lignes dans `answer_question` : la recherche
   garde la référence nue, seule la question transmise à `writer.write()` est explicitée.
   Mesuré : RAG-03 et RAG-05 passent à `ok`, RAG-18 · RAG-20 · RAG-23 **inchangés**. Ne pas
   porter cette règle dans le `_SYSTEM_PROMPT` : mesuré aussi, elle desserre la barrière 2
   au-delà du cas visé.

Deux deltas méritent une décision et non un simple constat :

- **l'argument `collections` des trois tools documentaires est implémenté mais non exposé
  par le serveur** — soit on l'expose dans l'`inputSchema`, soit on retire la promesse du
  catalogue ;
- **`access_rag.search_for_profile()` n'a aucun consommateur en production** (§A.1 étape 2,
  point 4) — soit un tool l'emprunte, soit elle descend dans `check_perimeter.py`, qui est
  son seul appelant.

Enfin, un point à **consigner plutôt qu'à corriger** : le seuil du reranker n'est pas
l'organe de refus, et aucun réglage ne le rendra tel — les populations se chevauchent
(§A.7). Le poser bas est le bon choix ; la barrière 2 tranche. C'est une réserve à publier
au protocole, pas un seuil à recalibrer.
