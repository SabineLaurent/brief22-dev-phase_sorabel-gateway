# Registre des défauts — Sorabel Data Gateway

Ce document liste **les défauts rencontrés pendant la phase de développement et ce qui a été
fait pour chacun**. Il est un index, pas un récit : le raisonnement complet, les mesures et
les arbitrages vivent dans `docs/journal-developpement.md`, à la date indiquée. Les défauts
encore ouverts vivent dans `docs/2026-09-07-todo-post-revue.md`, sous leur numéro `2bis.N`.

Trois conventions pour lire ce registre :

- **« Contrôlé par »** nomme la suite qui empêche le défaut de revenir. Quand la ligne dit
  *rien*, la correction tient par la relecture, ce qui est plus faible — c'est signalé exprès.
- **Un défaut trouvé par un contrôle** est distingué d'un défaut trouvé à l'écran ou à la
  lecture : la proportion dit ce que les suites tiennent vraiment.
- **Tout n'est pas un bug.** Deux sections finales séparent les écarts diagnostiqués qui n'en
  étaient pas, et les observations non reproduites.

---

## 1. Chantier RAG — ingestion (2026-09-02)

Neuf constats de revue de code, tous corrigés le jour même. Le premier est le seul qui aurait
servi une mauvaise donnée ; les huit autres sont des garanties qui ne tenaient pas.

**RAG-01 · Une édition écartée en promouvait une périmée.** `build_registry()` filtrait les
éditions dont la version du nom contredit celle du corps, **puis** désignait l'édition
courante sur ce qui restait — donc `REF-8842-v1.0` héritait de `is_current` précisément dans
le cas que le contrôle existe pour attraper. *Correctif* : un document dont une édition est
écartée n'a plus d'édition courante du tout ; les `doc_key` concernés sont tracés
(`undetermined_doc_keys`) et l'ingestion sort en échec. Fermer plutôt que deviner.
*Contrôlé par* : `make check-index`.

**RAG-02 · Code de sortie aveugle** (`ingest/cli.py`). Le code de sortie ne dépendait que des
fichiers illisibles : une édition écartée ou un `CORPUS_DIR` mal pointé sortaient en `0`.
C'est ainsi que RAG-01 serait passé inaperçu en intégration continue. *Correctif* : toute
anomalie sort en `1`, motif sur `stderr`.

**RAG-03 · Aucune réconciliation des suppressions** (`ingest/index.py`). L'`upsert` seul ne
rend la ré-ingestion idempotente que sur un corpus qui croît : un fichier supprimé, renommé ou
nouvellement écarté survivait avec son `is_current` de la passe précédente. *Correctif* :
suppression des `edition_id` absents du registre en fin de passe, comptée au rapport.

**RAG-04 · Le type déclaré primait sur le dossier** (`ingest/normalize.py`). Le commentaire
disait « le dossier fait foi », le code faisait gagner la balise `<meta name="type">`. Comme
la matrice filtre sur `doc_type`, **une balise erronée reclassait un document dans une autre
classe d'accès** — un défaut d'autorisation, pas de style. *Correctif* : le dossier fait foi,
une divergence lève `NormalizationError`.

**RAG-05 · Le vérificateur plantait sur les index qu'il doit attraper**
(`scripts/check_index.py`). `max()` sur une collection vide levait `ValueError` : `check-index`
avant `ingest` rendait une trace de pile au lieu de la ligne « éditions indexées 0 ÉCHEC »
qu'il s'apprêtait à écrire. *Correctif* : les entrées incomplètes sont mises de côté et
rapportées.

**RAG-06 · `CHROMA_URL` : schéma perdu, port faux** (`ingest/index.py`). Aucun `ssl=` n'était
passé (`https://` se connectait **en clair**), une URL sans port retombait sur 8000 alors que
le projet est en 8002, et une URL sans schéma donnait `hostname=None`. *Correctif* : parsing
strict, hôte et schéma obligatoires, port déduit du schéma, TLS transmis.

**RAG-07 · Le modèle d'embeddings n'était pas persisté** (`ingest/index.py`). Le commentaire
« Chroma persiste ce nom avec la collection » est faux pour chromadb 0.5.23, vérifié dans le
paquet installé. Changer `EMBEDDING_MODEL` pour un autre modèle en 768 dimensions et
ré-ingérer aurait **mélangé deux espaces vectoriels dans la même collection, sans erreur**.
*Correctif* : empreinte du modèle écrite dans la métadonnée de collection et vérifiée à
l'ouverture — d'où `make reindex`, qui existe pour cette raison.

**RAG-08 · Tri de versions dupliqué** (`scripts/check_index.py`). Le contrôle réécrivait le
classement de l'ingestion sans son garde-fou : deux tris divergents auraient pu dénoncer un
coupable qui n'en était pas un. *Correctif* : `version_sort_key()` rendue publique et importée.

**RAG-09 · L'adaptateur d'embeddings devinait** (`ingest/index.py`). `ChromaEmbeddingFunction`
routait tout vers `embed_documents()`, donc préfixait `passage:` — un
`collection.query(query_texts=…)`, l'API la plus naturelle de Chroma, aurait encodé chaque
question comme un document et **dégradé le rappel sans rien signaler**. *Correctif* :
l'adaptateur lève ; la gateway fournit toujours ses vecteurs explicitement.

---

## 2. Chantier Text-to-SQL (2026-09-03)

**SQL-01 · Une colonne hallucinée servie sur 200 lignes** — le plus grave du projet, et il a
été trouvé **en instruisant une demande**, pas par un contrôle. `qualify()` mettait les
identifiants entre guillemets doubles, et SQLite applique la misfeature *double-quoted string
literal* : un identifiant entre guillemets qui ne résout pas **devient une chaîne**. Donc
`SELECT zzz FROM commandes` rendait `code=ok` et 200 lignes de la valeur inventée `zzz`, SQL
à l'appui — le mode d'échec que tout le chantier existe pour empêcher. Le bloc `unknown` ne le
voyait pas : sa règle d'alias écartait précisément cette colonne. *Correctif* :
`quote_identifiers=False`, plus le contrôle 6 (`EXPLAIN`) qui refuse ce qui reste. Les deux
moitiés du trou fermées ensemble. *Contrôlé par* : `make check-sql`.

**SQL-02 · `Expression.limit()` élargit une requête déjà bornée.** Appelée avec 200 sur
`… LIMIT 5`, elle rend `LIMIT 200` — exactement ce que la conception interdit. *Correctif* :
`_apply_limit()` lit la borne existante avant de poser la sienne. *Trouvé par* un contrôle.

**SQL-03 · Un alias de projection pris pour une colonne inventée.**
`SELECT SUM(v.quantite) AS quantite_vendue … ORDER BY quantite_vendue` échouait en
`erreur_execution`. *Correctif* : les alias de sortie du scope sont écartés — sans rien
rouvrir, la colonne réellement lue derrière l'alias restant vue avec sa table. *Trouvé par* un
contrôle.

**SQL-04 · Deux faux refus sur CTE et sous-requête.** `validator.py` réimplémentait à la main
la résolution d'alias, de CTE et de sous-requêtes pour décider si une colonne existe, et se
trompait : une CTE légitime était refusée. *Correctif* : le validateur ne garde que la moitié
**autorisation** (la colonne est-elle dans `scope.columns` ?) et délègue l'**existence** au
moteur, qui résout correctement. Sept lignes en moins, deux faux refus en moins.

**SQL-05 · Le déploiement Azure refuse `temperature`.** « Unsupported value », comportement
des modèles de raisonnement — découvert au premier appel LLM réellement exercé du projet.
*Correctif* : paramètre retiré.

---

## 3. Banc d'essai et matrice (2026-09-03 → 2026-09-04)

**BANC-01 · Une fuite de droits entre rôles.** `_agent_for` était un `lru_cache` sur la seule
stratégie, le profil étant capturé à la construction du tool : **le premier rôle utilisé
aurait été servi à tous les suivants** — un `sans_role` héritant des droits d'un `commercial`
passé avant lui. *Correctif* : la clé de cache est le couple `(stratégie, profil)`.

**BANC-02 · Les rôles de l'interface ne portent pas les noms des profils.** `commerciale` vaut
`commercial`, `sans_role` vaut `default`. *Correctif* : la conversion vit à un seul endroit,
`profile_for_role()`, et rend `default` sur un rôle inconnu — totale comme la matrice.

**MES-01 · P0 et P1 jugés par la même formule** (`eval_perimetre`). `_outcome` calculait
`refused` sur le premier de la liste qu'on lui passe — juste pour P1, **faux pour P0**, dont
la définition écrite partout ailleurs est un filtrage *après* la décision du moteur. La ligne
« questions couvertes refusées » ne pouvait donc pratiquement pas montrer d'écart : le `1/1`
publié était vrai par construction, pas par mesure. *Correctif* : `_outcome` reçoit un
`decision_top` explicite ; `score` reste celui du résultat **rendu**, `refused` celui de la
pièce qui a **décidé**. Une ligne sur 240 change, les tableaux publiés ne bougent pas.

**MCP-00 · Quatre points de revue** (2026-09-04) : `blocked_at` porté explicitement par
`DbStructuredAnswer`, motifs `REF-NNNN` / `CMD-AAAA-NNNN` aux schemas, `launch()` utilisant
réellement les méthodes nommées, instance de launcher conservée par le serveur.

---

## 4. Chantier 3 — les huit tools et le serveur (2026-09-06)

**CTL-01 · Un contrôle qui s'est trompé lui-même.** Un contrôle de `check_rag_tools` lisait
`granted["status"] == "ok"` pour vérifier qu'un document était servi — et il **passait sur un
document introuvable**, qui partage ce statut. Le mapping n'était pas en cause. *Correctif* :
le contrôle nomme ce qu'il vérifie — le **code**, pas le statut — et un contrôle explicite
couvre la distinction. Consigné parce qu'il montre où le mapping se lit mal.

**PERF-01 · Un embedder construit à chaque appel.** `build_embedder` / `build_reranker`
n'étaient pas mémoïsés : invisible pour la suite d'acceptance, qui relance un processus par
appel, mais **4 s par question dans un serveur qui vit**. Mesuré : 5,00 / 4,22 / 3,77 s avant,
5,35 / **0,16** / **0,16** après.

**CLI-01 · Un catalogue vide ne rend pas un modèle muet.** Sous `sans_role`, l'agent annonçait
« je vais interroger la base » — une action qu'il ne pouvait pas faire. Il ne mentait pas
*avant* le branchement MCP : le tool existait alors pour se faire refuser et rendre sa phrase
figée ; le catalogue filtré supprime l'appel **et** le refus qui l'accompagnait. *Correctif* :
`build_agent()` rend `None` sur catalogue vide, CLI et API rendent `EMPTY_CATALOGUE`.
*Effet de bord consigné* : un profil sans aucun tool ne produit plus d'entrée au journal.

---

## 5. Revue de fin de chantier et vague 1 (2026-09-07)

**GAR-01 · La lecture seule tenait par une propriété que rien ne contrôlait.** Des trois
couches qui la défendent, celle qui porte réellement la garantie est **la connexion neuve par
requête** — une connexion désarmée exfiltre la base entière (159 744 o) par un seul
`VACUUM INTO`. Et c'était la seule des trois non contrôlée. Le risque n'était pas théorique :
le dépôt venait de mémoïser `build_embedder` pour la performance, et le même réflexe appliqué
à `_connect` aurait laissé les 81 contrôles au vert. *Correctif* : deux contrôles, dont le
réarmement de `query_only` sur connexion neuve ; `check-sql` 81 → 83. Le contrôle importe
`_connect` **nommément** — une connexion réécrite dans le script contrôlerait le script.

**API-01 · `collections` promis, implémenté, contrôlé — et inatteignable.** Les tools MCP ne
l'exposaient pas : aucun client ne pouvait l'atteindre. *Correctif* : exposé (retirer la
promesse aurait rendu morte la branche « collection fermée » et ses contrôles), et **sans
`enum`** — une énumération statique publierait l'existence de `note_interne` à un `dev`, qui
n'y a pas droit.

**MES-02 · Neuf cibles de mesure ne tournaient plus.** `REPO_ROOT = parents[2]`, juste tant
que le module vivait un cran plus haut, faux depuis le déplacement du 2026-09-04 :
`eval-sql`, les sept `mesure-*` et `make mesure`. L'échec était **bruyant** — rien n'a été
publié en silence. *Correctif* : `parents[3]`, motif en commentaire.

**MES-03 · `rapport_gain.md` ne se régénérait pas à l'identique.** Un CSV réécrit sans
régénérer le rapport, puis un index reconstruit. *Correctif* : chiffres republiés le
2026-09-07 — la mesure « avant » devient plus mauvaise, donc **le gain publié était
sous-estimé**. B et C rejoués identiques, seuils inchangés.

**RAG-10 · Une référence nue n'est pas une question.** `RAG-03` et `RAG-05` sortaient en
`contexte_insuffisant` sur un retrieval **parfait** (score 1,0000, bonne fiche au rang 1) : le
rédacteur cherche un énoncé à satisfaire et n'en trouve pas. *Correctif* :
`question_for_writer()` complète l'énoncé **au seul bord de `writer.write()`** — la recherche
garde la référence nue, c'est cette forme que BM25 attrape. **Et pas dans le prompt** :
mesuré, la même règle au `_SYSTEM_PROMPT` desserre la barrière 2 au-delà du cas visé (RAG-18
et RAG-20 basculent en `ok` alors que le corpus ne porte pas leur réponse). Faux refus 3–4/22
→ **3/22**, et la plage disparaît.

**ACC-01 · Écart de matrice corrigé** : `get_schema` retiré à `support` — arbitrage déjà
consigné, devenu bloquant dès que l'étage 2 s'est exercé.

---

## 6. La frontière du serveur et le contrat publié (2026-09-07)

**MCP-01 · Le contrat n'était pas absent, il était faux.** FastMCP dérive l'`outputSchema` de
l'annotation de retour : `-> str` publiait
`{"required":["result"],"properties":{"result":{"type":"string"}}}` et rendait
`structuredContent = {"result": "<l'enveloppe en chaîne>"}` — **publié dans `tools/list`, donc
lu par tout client externe, et validé par le SDK sans rien attraper**. *Correctif* : les huit
schémas écrits à la main dans `output_schemas.py` et posés par `list_tools`, le type de retour
restant large (`dict[str, Any]`) — un modèle plus étroit que le dict rendu fait diverger
`content[0].text` de `structuredContent`, mesuré. *Contrôlé par* : `make check-contrat`, le
**premier contrôle du serveur MCP** du projet.

**MCP-02 · Quatre familles d'appels ne traversaient rien.** FastMCP valide les arguments
contre l'`inputSchema` **avant** la fonction de tool, et un tool hors catalogue ne l'atteint
jamais : argument hors format, argument requis absent, mauvais type et tool inconnu
court-circuitaient handler, étage 2 **et journal**. Le SDK rendait à leur place la trace
pydantique brute, **qui n'est pas du JSON** — or les trois clients du dépôt font `json.loads`.
Mesuré sur neuf appels : **6 exceptions sur 9 → 0**, et **3 lignes de journal sur 9 → 9**. E5
était entamée sur un chemin qu'aucune mesure ne regardait. *Correctif* : `SorabelMCP.call_tool`,
surcharge symétrique de `list_tools` — la liste décide ce qui est visible, l'appel garantit ce
qui en sort. *Contrôlé par* : `check-contrat`, et mesuré à travers un vrai processus serveur.

---

## 7. Le front de comparaison et les descriptions (2026-09-08)

**FUITE-01 · Le prompt système publiait l'étage 1.** Constat de l'utilisatrice en regardant la
colonne `dev` : « je n'ai pas accès à l'outil de consultation de stock », alors que
`answer_question("REF-5313", profile="dev")` rend `ok`. `_SYSTEM_PROMPT` était une constante
passée aux cinq profils, et elle **énumérait les huit tools**, suivie de « si l'un de ceux
cités ci-dessus ne t'est pas proposé, il ne t'est pas accessible ». Deux conséquences : le
modèle apprenait l'existence des tools qu'il n'avait pas et le disait à l'utilisateur ; et les
profils partiels **renonçaient** — aucun appel, donc aucun verdict, donc aucune phrase figée.
*Correctif* : une suppression, déjà due — les descriptions arrivent par le protocole depuis
l'étape C. Mesuré : fuite d'existence **4 cellules sur 20 → 1**.

**FUITE-02 · Les descriptions de tools nommaient des tools que la matrice ferme.**
`list_tools` filtre les tools, jamais le **contenu de leurs descriptions** : `get_schema`
recommandait `ask_database` à `dev`, qui ne l'a pas. Même défaut que FUITE-01, **mais dans le
protocole**. *Correctif* : deux tables — `_DESCRIPTIONS` (les corps, **aucun nom de tool n'y
paraît**) et `_REFERRALS` (les renvois, chacun rattaché à sa cible, donc filtrables par la
matrice) — recomposées par `_served_description` dans `list_tools`, là où l'`outputSchema` est
déjà réécrit. *Contrôlé par* : `check-contrat` 145 → 163, dont le **décompte en or des renvois
qui survivent** au filtrage (0 · 8 · 14 · 15 · 15) — sans lui, vider les tables passerait.

**CLI-02 · Une non-réponse écrasait une réponse servie.** `frozen_text` traitait une
non-réponse comme un refus : `answer_question·contexte_insuffisant` **jetait** le résultat de
`check_stock·aucune_ligne(ok)`, mesuré 3/3. Racine : les deux domaines ont un code « rien
trouvé » et **pas le même statut**, alors que `REFUSAL_CODES` excluait déjà ces codes. La
distinction existait dans les domaines, pas au dernier mètre. *Correctif* : on **substitue**
quand rien n'a été servi, on **complète** sinon — ce qui est `ok` a franchi les étages 2 et 3,
le retenir à l'écran ne protège rien ; ce qui n'a pas abouti est dit **avec sa phrase**.
`compose_answer()` devient le point d'assemblage unique de la CLI et de l'API.
*Contrôlé par* : `make check-client`, **39 contrôles, la première suite du client** — les cinq
autres portent sur les couches en dessous, et `frozen_text` n'était couvert par rien.

**CLI-03 · La phrase figée sortait deux fois.** Trouvé en mesurant CLI-02 : le modèle recopie
lui-même la phrase, la consigne du serveur le lui demandant, puis le carnet l'ajoutait.
*Correctif* : une phrase déjà présente n'est plus ajoutée, l'égalité étant **stricte** pour
qu'une paraphrase ne dispense pas de la phrase exacte.

**UI-01 · Tableaux markdown illisibles en colonne étroite** (comparateur). Corrigé au rendu.

---

## 8. Défauts connus, non corrigés

Tous décrits en détail dans `docs/2026-09-07-todo-post-revue.md`, sous leur numéro.

| # | Défaut | Pourquoi il reste |
|---|---|---|
| **2bis.10** | La non-réponse d'un profil partiel n'a pas de phrase stable — et sur `SQL-08` sous `dev`, elle est **fausse sur le fond** : « le corpus ne couvre pas cette question » là où la question est **hors droits**. La ligne de journal porte le même énoncé, ce qui touche E5. | Un renoncement du modèle n'a pas de verdict, donc rien ne peut le figer. 2bis.11 a stabilisé le **chemin**, pas le **texte** : un aiguillage ne fabrique pas un verdict. Le cas `SQL-08` tranche l'arbitrage vers **la voie serveur** — un tool qui refuse au lieu d'être absent. |
| **2bis.9** | Le badge de colonne du comparateur reste **plus strict** que le texte : un incident survenu dans le tour garde la colonne non verte même quand la réponse a été servie. | Écart assumé et documenté au code — le texte dit ce que l'utilisateur obtient, le badge dit ce qui s'est passé. À relire avec 2bis.10. |
| **2bis.4** | **Les six contrôles SQL ne peuvent rien refuser à une requête qui ne référence aucune table.** Observé une fois : `support`, privé de `get_schema`, a obtenu la liste des tables par `SELECT 'clients' AS table_name UNION ALL …` — le générateur récitant son contrat de lecture en littéraux. | Ni fuite (les cinq tables citées sont celles de son périmètre) ni reproductible (3 essais suivants : autre chose). Mais c'est ce que le retrait de `get_schema` visait. Trou de contrôle nommé. |
| **2bis.1** | Un profil à **plus** de droits obtient **moins** de réponses : la redondance du corpus sature les candidats avant rerank. E1 recule là où la matrice s'élargit. | Ouvert — **prochain point de reprise**. |
| **2bis.2** | Le seuil de refus coupe dans le couvert : une question dont le corpus porte la réponse est refusée **sans que le juge la voie**. | À trancher avec la réserve chiffrée du protocole de mesure. |
| **2bis.5** | Les mesures du prompt ont été relevées par des **scripts jetables**, hors dépôt : le chiffre de FUITE-01 n'est pas rejouable. | Cible Make à écrire. |

---

## 9. Écarts diagnostiqués qui n'étaient pas des défauts

À garder, parce qu'ils ont coûté une enquête chacun et que la conclusion « ce n'est pas un
bug » est un résultat.

**BM25 seul à 3/8, quand la conception annonçait 8/8.** Chassé jusqu'à sa cause : le script de
référence tokenise le texte brut **frontmatter compris**, là où l'ingestion le retire de
`indexed_text`. BM25 normalisant par la longueur (`b = 0,75`), retirer 16 tokens suffit à
inverser l'ordre note/notice sur une course serrée — sur 5 des 8 questions. **Ce n'est pas un
défaut du code** : l'exclusion du frontmatter est une décision d'ingestion appliquée au dense
depuis le début ; BM25 est seulement le premier étage à exposer sa sensibilité à la longueur.
Revenir dessus casserait la cohérence « un seul texte indexé ».

**La variabilité de formulation n'était pas une régression du dernier changement.** Vérifié en
restaurant `cli.py` et `api.py` dans leur version `HEAD` (empreintes SHA-256 contrôlées) :
comportement identique. Le dispositif de phrases figées fonctionne — il a une **condition
d'application** que rien n'énonçait : *il suppose qu'un tool a été appelé.* Carnet vide ⇒ le
modèle rédige. C'est ce constat qui a mené à FUITE-01.

**`aucune_ligne` et `introuvable` valent `ok`, et c'est voulu.** Un constat d'absence n'est pas
une panne ; en faire une `error` ferait compter au journal des échecs qui n'ont pas eu lieu et
rendrait E5 illisible. Ce qui protège le client est que la clé de charge utile est absente.
Même arbitrage des deux côtés — SQL et RAG.

---

## 10. Observations non reproduites

**Un `make` rouge sur une suite verte.** La première exécution de `check-rag-tools` après
l'ajout de cinq contrôles a rendu 134 **après** avoir affiché « Tous les contrôles passent » :
`libc++abi … recursive_mutex lock failed`, un teardown natif de torch à la sortie du
processus. Trois exécutions suivantes : 0. Non traité, faute de reproduction — consigné parce
qu'un `make` rouge sur une suite verte est exactement le genre de chose qu'on croit avoir
imaginée.

---

## 11. Déploiement Azure Container Apps (2026-09-09)

Chantier neuf, hors brief au sens strict — il porte le livrable « URL d'une interface
graphique fonctionnelle ». Trois défauts constatés et corrigés, un point de vigilance ouvert.

**DEP-01 · Les images étaient construites pour la mauvaise architecture.** `docker build` sur
un Mac Apple Silicon produit du `linux/arm64` ; Container Apps exécute du `linux/amd64`. Les
images auraient été poussées puis auraient refusé de démarrer, avec un message d'exécution
sans rapport apparent avec l'architecture. *Correctif* : `--platform linux/amd64` sur les deux
images, vérifié par `docker image inspect` avant le push, et l'image amd64 exercée avant
d'être envoyée (chemins absolus, absence de `torch`, dépicklage BM25 à 400 éditions, base à
120 produits). *Contrôlé par* : rien — la vérification est manuelle, à refaire à chaque
construction depuis un poste ARM.

**DEP-02 · `env_file` réinjectait les chemins relatifs de `.env`.** L'image ne contient aucun
`.env` (vérifié), mais le compose de répétition le lisait pour les clés Azure — et `.env` pose
`SORABEL_DB=data/sorabel.db` et `GATEWAY_JOURNAL=logs/journal.jsonl`, qui écrasent les défauts
**absolus** de `config.py`. Mesuré dans le conteneur : `settings.sorabel_db` valait
`data/sorabel.db`. Cela « marchait » tant que le CWD vaut `/app`, donc par coïncidence : un
sous-processus lancé d'ailleurs aurait écrit un **second journal**, et `make journal` aurait lu
le mauvais. *Correctif* : les deux variables neutralisées en absolu dans
`docker-compose.aca.yml`, et **non posées du tout** en Container Apps, où l'absence de `.env`
rend les défauts déjà justes. *Contrôlé par* : la preuve 1 de l'étape de validation par
conteneurs (à rejouer à la main).

**DEP-03 · Le `.dockerignore` faisait tomber un test d'acceptance.** J'excluais
`eval/rapport_*.md` comme « documentation » ; or `tests/acceptance/test_rag.py:57-64` ouvre
`eval/rapport_gain.md` et exige qu'il existe et soit chiffré — la suite vérifie que la mesure
du gain hybride est **publiée**. Résultat : 11/12 dans le conteneur. *Correctif* : `eval/`
ré-inclus en entier ; le test fait foi, et les rapports pèsent une centaine de kilo-octets.
*Contrôlé par* : `pytest` joué **dans** le conteneur (cible `test` du Dockerfile).

**DEP-04 · Crainte NON FONDÉE, tranchée en production le 2026-09-10 — « Connexions non sécurisées : Non autorisé ».**
Les trois apps s'appellent entre elles par leur nom en **HTTP** — `http://sorabel-chroma-…`,
`http://sorabel-gateway-…` — parce que c'est le chemin documenté par Microsoft (« use its name
prefixed with `http://` ») et que le nom court ne correspondrait à aucun certificat, ce qui
exclut `https://`. Or l'ingress est créé avec les connexions non sécurisées **refusées**, ce
qui force une redirection HTTP → HTTPS.

Je crois que cette redirection ne concerne que le trafic externe, **mais ce n'est pas
vérifié**. Si la gateway ne joint pas Chroma, ou le front la gateway, c'est **le premier
endroit à regarder** : `<app>` → `Paramètres` → `Entrée` → autoriser les connexions non
sécurisées. Modifiable en deux clics, sans recréer l'app.

Deux symptômes étaient attendus si c'était la cause : côté Chroma, une erreur « Chroma
injoignable » (`ingest/index.py:99-102`) ; côté front, la phrase figée `FRONT_INDISPONIBLE`.
Aucun des deux ne nommait la redirection, ce qui rendait le diagnostic coûteux — d'où la
consigne écrite d'avance.

**Aucun ne s'est produit.** Sur l'URL déployée, `support` + « REF-8842 » rend la fiche
documentaire **et** le stock dans le même tour — donc l'appel a traversé
`http://sorabel-chroma-demo-sabl` en HTTP, les embeddings `text-embedding-3-small` et le
rerank Cohere. **La redirection HTTP → HTTPS ne s'applique pas au trafic entre apps d'un même
environnement Container Apps.** `allowInsecure: false` peut donc rester, et l'appel par nom
court — le chemin documenté par Microsoft — fonctionne tel quel.

*Ce que la crainte a quand même valu* : les deux symptômes étaient écrits avant le
déploiement, donc le premier échec documentaire aurait été diagnostiqué en une minute au lieu
d'une heure. Une hypothèse fausse écrite d'avance coûte moins qu'une hypothèse juste trouvée
après coup.

**DEP-05 · Le champ « Arguments » du portail se découpe sur les ESPACES, pas sur les
virgules.** Instruction fausse de ma part, signalée comme non vérifiée puis confirmée à
l'écran : `packages.agent.api:app,--host,0.0.0.0,--port,8000` est passé **littéralement** à
uvicorn, qui reçoit un seul argument au lieu de cinq. Le conteneur redémarre en boucle
(« 1/1 Container crashing ») et l'app reste en *Échec* avec 0/1 réplica.

Le message exact, reproduit en local sur l'image poussée avant même de lire les journaux
Azure :

```
ERROR: Error loading ASGI app.
       Attribute "app,--host,0.0.0.0,--port,8000" not found in module "packages.agent.api".
```

*Correctif* : séparer les arguments par des **espaces**. *Méthode qui a payé* : plutôt
qu'attendre l'ingestion Log Analytics (1 à 5 minutes), rejouer la commande exacte en local
sur l'image poussée — le lancement nu réussit (`Uvicorn running on http://0.0.0.0:8000`),
donc ni le code, ni l'image, ni l'absence de variables ; puis reproduire l'hypothèse en
passant les arguments comme une chaîne unique, ce qui rend le message à l'identique.
*Contrôlé par* : rien — configuration de portail.

**Ce qui ne s'est PAS produit, et qu'on croyait probable** : l'audit prédisait qu'un
sous-processus MCP mort laisserait un zombie sous PID 1 et 30 s de `CALL_TIMEOUT` par question.
Mesuré : échec en **1,7 s**, statut `error`, phrase figée, ligne de journal
(`erreur_execution`, `cause=ClosedResourceError`), processus moissonné, et **les autres rôles
intacts**. Le défaut confirmé est l'absence de relance — un redémarrage de 3 s le lève. C'est
ce qui a justifié de ne pas le corriger. Cf. §8.

---

## 12. Ce que le registre apprend

- **Les trois défauts les plus graves du projet n'ont pas été trouvés par une suite** : SQL-01
  en instruisant une demande, FUITE-01 en regardant une colonne à l'écran, GAR-01 en cherchant
  ce que les contrôles ne couvraient pas. Les suites ont attrapé les défauts moyens.
- **Les défauts d'exposition sont des textes, pas du code** : un prompt qui énumère
  (FUITE-01), une description qui renvoie vers un tool fermé (FUITE-02), un schéma dérivé qui
  publie une forme fausse (MCP-01) — et un `enum` qui aurait publié `note_interne` à qui n'y a
  pas droit, écarté avant d'être écrit (API-01). La matrice ferme les tools ; ce sont les mots
  autour qui les rouvrent.
- **Deux défauts ont été rendus atteignables par un correctif** : CLI-01 par le catalogue
  filtré, CLI-02 par le cumul. Ils existaient avant, sans chemin pour y arriver.
