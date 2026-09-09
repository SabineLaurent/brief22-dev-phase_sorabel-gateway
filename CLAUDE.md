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
  `make test` 12/12 ; check-sql 81, check-feedback 103, check-rag-tools 62,
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
- **Axes 6 et 7 — local ou distant, mesuré (hors brief).** `retrieval/reranker.py`
  (`CohereReranker`, LLM-juge retiré), `config.py` (les trois `azure_rerank_*`),
  `protocole-mesure.md` (**six** drapeaux, **sept** axes), et trois rapports :
  `eval/rapport_embeddings.md`, `rapport_rerank.md`, `rapport_local_vs_distant.md`.
  **Le point de départ n'était pas la qualité mais l'empreinte** : ~1 Go de RSS par serveur
  MCP chaud, quatre profils ≈ 2,8 Go. PyTorch ne disparaît que si **les deux** modèles partent
  en distant.
  Quatre cellules, **chacune avec son seuil calibré** — comparer à seuil constant mesurerait
  le seuil. **Le classement est identique aux quatre coins** (Hit@1 8/8, MRR 1,000, Recall@5
  12/13) ; seul le **refus** bouge : ① `e5`+mmarco 5/8 · ② azure+mmarco 4/8 · ③ `e5`+Cohere
  7/8 · ④ **azure+Cohere 8/8, 0 faux refus**.
  **En configuration servie, l'embedder est invisible** : aucun rang ne change sur 38 lignes,
  et le seul verdict qui bascule le fait sur un score identique au dix-millième — BM25 et le
  rerank absorbent la différence. En dense seul l'écart est réel et à double sens : meilleur
  sur la prose (Recall 9/13 → 11/13), **nul sur les identifiants** (MRR 0,271 → **0,000**,
  contre-vérifié trois fois : le texte du document en requête le ramène au rang 1 à 0,9572).
  **Le gain de ④ n'est pas « refuser plus » mais « refuser mieux »** : le refus *servi* est
  déjà 8/8 en ① grâce à la barrière 2. ④ tranche **8 refus sans appeler le modèle** au lieu de
  5, de façon déterministe, avec une ligne de journal stable.
  **Décision : servir ① en local, déployer ④** — les cinq rapports publiés décrivent ①, rien à
  republier ; l'image déployée n'embarque pas PyTorch (~150 Mo par processus).
  **Constat ouvert** : aucun garde-fou ne relie un seuil au modèle qui l'a calibré (le contrôle
  d'empreinte protège index ↔ modèle, pas seuil ↔ modèle). Chaque seuil **nomme** désormais son
  modèle en commentaire — ce qui n'est pas un contrôle.
  **Le jeu de calibration ne contient aucune référence produit** : non représentatif pour
  comparer deux modèles, et c'est ce qui explique que les deux axes aient vu la calibration
  annoncer l'inverse du résultat.
- **La frontière du serveur : posée et mesurée.** `SorabelMCP.call_tool` — surcharge
  symétrique de `list_tools` : **la liste décide ce qui est visible, l'appel garantit ce qui
  en sort.**
  **Le défaut fermé.** FastMCP valide les arguments contre l'`inputSchema` **avant** la
  fonction de tool, et un tool hors catalogue ne l'atteint jamais : argument hors format,
  argument requis absent, mauvais type et tool inconnu court-circuitaient handler, étage 2 et
  journal. Le SDK rendait à leur place la trace pydantique brute, **qui n'est pas du JSON** —
  or les trois clients du dépôt font `json.loads`. Mesuré sur neuf appels : **6 exceptions sur
  9 → 0**, et **3 lignes de journal sur 9 → 9**. E5 était entamée sur un chemin qu'aucune
  mesure ne regardait.
  **`isError` : tranché sur `erreur_execution` seul** — tout statut `error`, et rien d'autre.
  La spec en fait un **canal de correction** que le client remonte au modèle pour qu'il
  réessaie ; un refus de droits n'a rien à corriger, et le marquer inviterait à réessayer à
  l'identique — la différence entre un `500` et un `403`. Motif technique concordant :
  `mcp/client/session.py:411` ne valide le `structuredContent` **que si `isError` est faux**,
  donc marquer un refus supprimerait la vérification du schéma là où il déclare l'absence de
  la clé de charge utile. Sur `erreur_execution` le coût est nul, le payload étant réduit à
  `{"code": …}`. Le tableau §5 de la conception en marquait cinq — **écart décidé, motivé**.
  **MCP n'a pas d'équivalent de `403` ni de `404`** : le protocole n'offre qu'un booléen et
  des codes JSON-RPC de structure. C'est le trou que les douze codes comblent, et la raison de
  « le discriminant du client est `code`, pas `isError` ».
  Mesure : `rapport_acces.md` gagne une section et `mesure-acces-frontiere.csv` —
  **5/5 journalisés, 5/5 enveloppes conformes, 0 fuite**, témoin valide compris, et **mesurée
  à travers un vrai processus serveur** : un handler ne connaît pas l'`inputSchema`, il
  rendrait `aucune_ligne` sur une référence mal formée. Les 50 appels d'E5 passaient tous des
  arguments valides — la limite n'était écrite nulle part.
  `make lint` vert ; check-contrat 121 → **145** ; check-sql 83, check-feedback 103,
  check-rag-tools 67, check-perimetre 31 inchangés ; `make test` 12/12.
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
- **Le mini guide d'accès : écrit.** `mcp_server/README.md` — *livrable exigé du brief*, au
  même titre que `mcp_server/` lui-même. Dix sections, écrites **pour un intégrateur** qui
  branche son propre client : bloc de configuration prêt à coller, tableau profil × tools avec
  sa commande de régénération, les huit tools et vers quoi renvoyer quand ce n'est pas eux, les
  cinq statuts, les douze codes avec la colonne « ce qu'il ne faut **jamais** faire », la
  clause de prompt système, les citations, les garanties, les limites chiffrées, la
  démonstration de deux profils, et les six écarts assumés.
  `docs/mini-guide-acces.md` est un renvoi pour qui parcourt `docs/`, et la section « Contrat
  d'intégration » du README racine devient un renvoi elle aussi — **une seule source pour le
  contrat**, faute de quoi les deux divergent.
  **Le brief exigeait une seconde chose sur le même sujet, que ni la revue ni le TODO n'avaient
  relevée** : « documenter le catalogue […] **et démontrer deux profils différents avec
  `scripts/mcp_client.py`** ». D'où le §9 du guide, et l'ouverture de `--profile` **aux cinq
  profils lus dans la matrice** — une liste en dur y divergeait.
  **Écart refermé au passage** : le guide recommande `structuredContent` comme chemin de
  lecture, ce que `03-catalogue-tools.md` §4 défendait comme « le chemin correct sans avoir à y
  penser ». Avant ce soir, l'écrire aurait été mentir.
  **Le point le plus fin du guide** est le seul que la conception avait vu : `readOnlyHint` est
  une **déclaration du serveur**, qu'un client ne peut pas vérifier — ce qui la tient est la
  matrice et les contrôles SQL, donc du code invisible pour lui.
- **Les descriptions de tools : le seul aiguillage, et il nommait des tools fermés (2bis.11).**
  `mcp_server/server.py` — deux tables, `_DESCRIPTIONS` (les corps) et `_REFERRALS` (les
  renvois, chacun rattaché à sa **cible**), recomposées par `_served_description` dans
  `list_tools`, là où l'`outputSchema` est déjà réécrit : **le droit d'accès et le texte publié
  sont posés au même endroit.**
  **Le défaut : `list_tools` filtre les tools, jamais le contenu de leurs descriptions.** Or
  une description nomme d'autres tools — et `get_schema` recommandait `ask_database` à `dev`,
  qui ne l'a pas. Même défaut que le prompt système corrigé le matin, mais **dans le
  protocole**. Le modèle lisait le renvoi, cherchait le tool, et renonçait.
  **Les huit descriptions suivent cinq rubriques** — `Objet`, `Entrée`, `Sortie`,
  `Utiliser quand`, `Ne pas utiliser quand` — demandées par l'utilisatrice en cours de route.
  La cinquième vient **en dernier** parce que les renvois s'y collent, et c'est là que les trois
  volets se logent : renvoi conditionnel, ponts entre domaines (dans les **deux** sens : la
  fiche depuis `check_stock`, la base depuis `answer_question`), et l'interdit de
  `get_document` qui oppose l'identifiant d'édition à une référence `REF-NNNN`.
  **Aucun nom de tool ne paraît dans un corps** : la garantie est structurelle, pas
  conventionnelle. `check-contrat` 145 → **163**, dont le **décompte en or des renvois qui
  survivent** au filtrage (0 · 8 · 14 · 15 · 15) — sans lui, vider les tables passerait.
  Régressions rejouées : renvoi remis en dur → 3 contrôles tombent ; tables vidées → 5.
  **Rejeu LLM, 3 passes, 12 cellules, 0 fuite** : 2bis.8 **fermée** (`answer_question·ok` 3/3,
  plus d'`introuvable`) ; **2bis.7 tranchée de fait vers la fiche**, uniforme sur les quatre
  profils (c'était un choix produit — écrit et assumé) ; 2bis.10 **à moitié** — le chemin est
  stable donc la ligne de journal l'est, le texte varie toujours : un aiguillage ne fabrique
  pas un verdict.
  Guide mis à jour (§4 « les descriptions ne sont pas les mêmes pour tous », et la clause de
  prompt du §5 — **moitié de 2bis.6**).
- **Le cumul fiche + stock, et la non-réponse qui écrasait une réponse servie (2bis.7 · 2bis.12).**
  **2bis.7 est décidée : LES DEUX.** Sur une référence nue, la réponse porte la fiche *et* le
  stock — un renvoi **cumulatif** dans `_REFERRALS`, donc filtré par la matrice comme les
  autres (`dev`, qui n'a pas `check_stock`, ne reçoit pas la consigne). L'exemple est **nommé et
  borné** — « un seul cas demande DEUX appels, et c'est le seul » — parce qu'une règle générale
  de prompt ne reste pas locale, mesuré deux fois dans ce projet. Cumul **1/6 → 6/6**, texte
  portant les deux avec le SQL montré et la source citée ; **0 régression** (SQL pur,
  documentaire pur, témoin `dev`).
  **Le cumul a rendu atteignable un défaut qui existait** : `frozen_text` traitait une
  **non-réponse** comme un **refus**, donc `answer_question·contexte_insuffisant` **jetait** le
  résultat de `check_stock·aucune_ligne(ok)` — mesuré 3/3. Racine : les deux domaines ont un
  code « rien trouvé » et **pas le même statut** — SQL `aucune_ligne` vaut `ok`, RAG
  `hors_corpus` non — alors que `REFUSAL_CODES` exclut déjà ces codes (« ni l'un ni l'autre
  n'est un refus »). La distinction existait dans les domaines, pas au dernier mètre.
  **La règle, reformulée par l'utilisatrice : on substitue quand rien n'a été servi, on
  complète sinon.** Ce qui est `ok` a franchi les étages 2 et 3 ; le retenir à l'écran ne
  protège rien. Ce qui n'a pas abouti est dit **avec SA phrase**. `compose_answer()` est le
  **point d'assemblage unique** de la CLI et de l'API. Second défaut trouvé en mesurant le
  premier : le modèle recopie la phrase figée lui-même, donc elle sortait deux fois — une phrase
  déjà présente n'est plus ajoutée, et l'égalité est **stricte** pour qu'une paraphrase ne
  dispense pas de la phrase exacte.
  `make check-client` : **39 contrôles, la première suite du client** — les cinq autres portent
  sur les couches en dessous, et `frozen_text` n'était couvert par rien. Elle vit dans
  `packages/evals_and_controls/`, pas sous un domaine : le dernier mètre mêle les deux.
  **Limite qui compte** : le cas « un domaine réussit, l'autre échoue » n'est **pas produisible**
  avec une référence réelle — correspondance **120/120** base ↔ corpus. Le jeu de données cache
  le défaut ; les contrôles déterministes comptent donc plus que le rejeu.
  **Écart assumé** : le badge de colonne du comparateur (`_statut`) reste plus strict que le
  texte — à relire avec 2bis.9.
- **Reste du chantier 3.** Par ordre d'exigence du brief :
  1. **l'interface graphique splittée par rôle : faite le 2026-09-08** (`make web-compare`,
     port 8101) — un front Chainlit, une colonne par profil, chaque colonne adossée à son
     propre processus MCP (custom element React, exécution en `asyncio.gather`), sur le
     registre de sessions `GatewayRegistry`. C'est elle qui porte le livrable « un lien d'une
     interface graphique du produit fonctionnel » — **l'URL exigée porte sur l'IGU, pas sur le
     serveur MCP** : stdio tient le livrable serveur (arbitrage consigné au journal le
     2026-09-06). **Ce qui manque est l'URL publiée, pas l'interface** : c'est le dernier
     livrable nommé sans réponse, et c'est un choix d'hébergement, pas du code.

  Le reste vit dans `docs/2026-09-07-todo-post-revue.md` — deux décisions ouvertes
  (`citations` au journal, `search_for_profile()`), l'écriture du contrat de réponse, et les
  écarts au dossier de conception.

  Hors périmètre du brief, instruit et journalisé mais **non ouvert** : le passage à un
  service partagé (transport HTTP, annuaire et secrets), et la chaîne de délégation
  d'identité (comptes, JWT, OBO). Trois entrées de journal les tiennent — ne pas les rouvrir
  sans décision explicite, elles ne rapportent aucun point.

**Les douze tests d'acceptance passent** (`make test`, ~47 s). **Ne rien modifier dans
`tests/`** : la suite est arrivée avec le dépôt et fait foi.

**Le contournement `literalai` est périmé — vérifié le 2026-09-09.** `literalai`
(dépendance de `chainlit`) installe bien un paquet `tests` à la racine de `site-packages`,
mais `make test` passe `--import-mode=importlib`, qui résout la collision : dossier remis à
son nom, **12/12 en 46,52 s**. Contre-épreuve : sans le drapeau, la collecte meurt sur
`ModuleNotFoundError: No module named 'tests.conftest'` pour les trois modules. **Plus rien à
rejouer après un `uv sync`** — mais un `uv run pytest` tapé à la main sans le drapeau échouera
toujours.

**Lire `docs/journal-developpement.md` avant de reprendre** — il tient les décisions, les
arbitrages, les écarts constatés et les points ouverts de chaque étape livrée. Y ajouter
une entrée à chaque étape terminée.

## Choix techniques transverses

- **Inférence LLM** : Azure AI Foundry en OpenAI-compatible, **API v1** — client OpenAI
  standard, `base_url=f"{endpoint}/openai/v1"`, déploiement en `model`, pas d'`api_version`.
- **Embeddings** : commutables — Azure si `AZURE_EMBEDDING_DEPLOYMENT` est renseigné,
  sinon `intfloat/multilingual-e5-base` en local (préfixes `passage:` / `query:`).
- **Reranker** : commutable — cross-encoder local (`mmarco-mMiniLMv2-L12-H384-v1`) ou
  **Cohere sur Azure AI Foundry**. Bascule **tout ou rien** : les trois `AZURE_RERANK_*`
  (déploiement, endpoint, clé), sinon le local. L'endpoint est **l'URL complète** de l'appel
  (`…/providers/cohere/v2/rerank`), pas une base — Foundry sert les modèles partenaires sur
  une autre surface que l'API OpenAI-compatible. *Le rerank LLM-juge a été retiré le
  2026-09-08 : ni conçu, ni mesuré, ni calibré.*
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
make ingest-azure-small   # index témoin, embeddings OpenAI (axe 6) -> sorabel_corpus_azure_small
make calibrer-azure-small # les deux seuils sur l'index OpenAI
make calibrer-cohere      # le seuil hybride sur l'échelle de Cohere (axe 7)
make calibrer-distant     # le seuil de la cellule 4 : les deux modèles en distant
make mesure-embeddings    # axe 6 : A et C, les deux embedders -> eval/rapport_embeddings.md
make mesure-rerank        # axe 7 : les deux rerankers -> eval/rapport_rerank.md
make mesure-distant       # cellule 4 -> eval/rapport_local_vs_distant.md
make check-index   # contrôles d'intégrité de l'index
make check-perimetre # contrôles du filtre de périmètre documentaire (matrice sur le corpus)
make check-rag-tools # contrôles des quatre tools RAG et de leur journal (sans appel de modèle)
make seed          # génère data/sorabel.db
make check-sql     # contrôles déterministes du Text-to-SQL (sans appel de modèle)
make check-feedback # contrôles de la réponse structurée et du journal (sans appel de modèle)
make check-contrat # contrôles du contrat publié, de la frontière et des descriptions (163)
make check-client  # contrôles du dernier mètre : substituer, compléter, ou dire qu'on renonce (75)
make mesure-refus  # axe 4 : le refus servi sur les deux barrières -> eval/rapport_refus.md
make mesure-acces  # axe 5 : E5 chiffrée, étages d'arrêt, colonnes fermées et la
                   #          frontière du serveur -> eval/rapport_acces.md
make journal       # les 20 dernières entrées de logs/journal.jsonl
make eval-sql      # les 24 questions SQL -> eval/rapport_sql.md (un appel LLM chacune)
make serve         # serveur MCP stdio, les huit tools (profil dans SORABEL_PROFILE)
make client        # client de test : catalogue et appel d'un tool (PROFILE=support|commercial)
make api           # API du banc d'essai (uvicorn, port 8000) — socle des deux fronts
make web           # IGU mono-rôle, Chainlit (port 8100)
make web-compare   # IGU splittée par rôle : une question, quatre profils côte à côte (8101)
make test          # suite d'acceptance — 12/12
make lint          # ruff + mypy — au vert
```
