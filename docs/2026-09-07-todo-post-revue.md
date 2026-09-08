# TODO post-revue — 2026-09-07

Issu de [`2026-09-07-revue-brief22-phase-developpement.md`](2026-09-07-revue-brief22-phase-developpement.md),
**complété le 2026-09-08** par ce que le front de comparaison a fait apparaître (§2 bis).
Ordre : **ce que le brief exige** d'abord, **ce que la revue a trouvé** ensuite, **ce que le
front a révélé**, **les décisions à prendre** enfin. Chaque entrée porte son critère de
succès — sans quoi on ne sait pas quand la barrer.

État de départ, mesuré le 2026-09-07 : `make test` 12/12 (48,46 s) · `check-sql` 81 ·
`check-feedback` 103 · `check-rag-tools` 62 · `check-perimetre` 31.
Après la vague 1 : `check-sql` **83** · `check-rag-tools` **67** · `make lint` **au vert**.
Après §3.5 : `check-contrat` **145** — cible neuve, premier contrôle du serveur MCP, et la
frontière `call_tool` qu'il a fait apparaître (6 exceptions client sur 9 → 0, 3 lignes de
journal sur 9 → 9).
Après §2 bis (2026-09-08) : **tous les décomptes inchangés** — 83 · 103 · 67 · 31 · 145,
`make test` 12/12, `lint` vert. Le correctif du prompt ne touche aucune couche contrôlée ;
sa mesure propre est la fuite d'existence, **4 cellules sur 20 → 1**.

**Les mesures citées ici ont été relevées par des scripts jetables**, hors dépôt et non
conservés : refaire la mesure fait partie de la tâche qui la cite (§2.1, §2.2, §2.3, §2.4,
et **§2bis.3** — d'où §2bis.5, qui porte cette dette).
Les chiffres, eux, sont dans ce fichier — ils servent de valeur attendue, pas de preuve.

---

## 1. Exigé par le brief — non livré

### 1.1 Le mini guide d'accès

- [x] **Écrire le mini guide d'accès des équipes clientes.** *Fait le 2026-09-07* —
  `mcp_server/README.md`, dix sections, écrites pour un intégrateur.
  `docs/mini-guide-acces.md` est un renvoi ; la section « Contrat d'intégration » du README
  racine en devient un aussi — **une seule source pour le contrat**.

  **Le brief exigeait une seconde chose sur le même sujet, que cette liste avait manquée** :
  `brief22-updated.md:130` — « documenter le catalogue pour les équipes clientes **et
  démontrer deux profils différents avec `scripts/mcp_client.py` (support vs commercial)** ».
  Le livrable comprend donc une démonstration scriptée. D'où le §9 du guide, et l'ouverture de
  `--profile` **aux cinq profils lus dans la matrice** : une liste en dur (`support`,
  `commercial`) divergeait de la matrice, et c'est justement ce que ce client sert à montrer.

  **Deux points du sommaire de `Q5.md` §9 avaient changé d'état** : « lire
  `structuredContent.code`, pas `isError` » est **devenu vrai** dans la soirée, et
  l'obligation d'afficher le `hint` est **périmée**. La table des douze codes de `Q4.md` §4
  n'est pas périmée mais **trop large** : sa colonne `isError` en marque cinq, le code en
  marque un.

  **Écarts repris au guide**, comme §3.4 et §3.5 le demandaient : les deux de `matrice.yaml`,
  les noms de champs, `hint`, `isError` réduit à un code, et le payload servi qui est un
  surensemble du cadrage — six lignes avec leur raison.

Livrable nommé au même titre que `mcp_server/` : « Le serveur MCP (mcp_server/) exposant le
catalogue complet **ainsi qu'un mini guide d'accès** ». Il n'existe aucun fichier qui le
porte.

C'est aussi l'endroit du **bloc de configuration stdio** pour un client externe, donc la
réponse à « essai du service » des modalités d'évaluation.

Contenu minimal : les 8 tools (nom, arguments, ce qu'ils rendent, vers quoi renvoyer quand
ce n'est pas eux) · l'enveloppe `{status, payload, message}` et les 5 statuts · les 12 codes
et ce qu'un client doit en faire (ne jamais rendre un refus comme une réponse) · le
lancement (`python -m mcp_server.server`, `SORABEL_PROFILE`, `GATEWAY_JOURNAL`) · le bloc de
config client prêt à coller · le tableau profil × tools.

> **Succès** : un intégrateur branche un client MCP externe sans lire le code.

### 1.2 E5 chiffrée

- [x] **`make mesure-acces` → `eval/rapport_acces.md`.** *Fait le 2026-09-07* —
  `packages/evals_and_controls/eval_access.py` (paquet nouveau : c'est la seule mesure
  transverse aux deux domaines, la mettre dans l'un lui ferait importer l'autre).
  Dix scénarios × cinq profils = 50 appels, axe 5 du protocole. **E5 est chiffrée sur ses
  deux obligations** : 50/50 appels journalisés, **0 occurrence** des trois colonnes
  sensibles dans les vues client de `default`, `dev` et `support`. Étage 1 par `tools/list`
  (0 · 5 · 7 · 8 · 8, égal à la matrice), étages 2 et 3 par `blocked_at`.
  **Réserve « nommer, pas numéroter » : tranchée — on numérote**, avec les trois motifs
  écrits dans le rapport et dans la docstring.

**E5 est la seule des six exigences sans preuve chiffrée publiée** ; les cinq autres ont
`rapport_gain.md`, `rapport_sql.md` ou `rapport_perimetre.md`. Le champ `blocked_at` est
déjà posé sur les huit tools (`0` = servi, l'étage bloquant sinon) — il n'a jamais été lu.

Trancher à cette occasion la réserve **« nommer, pas numéroter »** laissée ouverte au
journal de développement.

> **Succès** : un rapport qui dit, par profil et par tool, combien d'appels ont été arrêtés
> et **par quel étage** — et qui distingue un refus (`denied`) d'une non-réponse
> (`hors_corpus`, `contexte_insuffisant`), lesquelles ne sont pas dans `REFUSAL_CODES`.

### 1.3 Une URL pour l'interface graphique

- [x] **L'interface graphique splittée par rôle.** *Faite le 2026-09-08* —
  `packages/web_client/app_compare.py`, `compare_root/public/elements/Comparaison.jsx`,
  `make web-compare` (port 8101). Quatre colonnes — `default`, `dev`, `support`,
  `commercial`, par droits croissants — chacune adossée à son propre sous-processus MCP,
  les quatre interrogées en `asyncio.gather`. Chaque colonne affiche son catalogue
  (**étage 1**, par la route neuve `GET /catalogue`), les badges `tool · code` de ses
  appels (**étages 2 et 3**, par `calls` sur `ChatResponse`) et la réponse servie telle
  quelle. Vérifié au navigateur à trois largeurs. Détail et les quatre décisions que la
  mesure a renversées : journal du 2026-09-08.
- [ ] **Publier un lien de l'IGU.**

Livrable : « Un lien d'une interface graphique du produit fonctionnel ». Les deux interfaces
existent et fonctionnent (`make web` port 8100, `make web-compare` port 8101, adossées à
`make api`), cinq rôles qui agissent réellement — un sous-processus serveur MCP par profil.
**Aucune URL n'est publiée.**

Arbitrage déjà consigné : l'URL exigée porte sur l'**IGU**, pas sur le serveur MCP ; stdio
tient le livrable serveur.

> **Succès** : un lien qu'on ouvre depuis une autre machine, ou à défaut la décision écrite
> de ne pas déployer et ce qui la remplace en soutenance.

---

## 2. Trouvé par la revue — à corriger

### 2.1 Publier le refus documentaire tel qu'il est servi

- [x] **`make mesure-refus` → `eval/rapport_refus.md`.** *Fait le 2026-09-07* —
  `packages/rag_machines/evals_and_controls/eval_refusal.py`, axe 4 du protocole.
  **Un seul appel de `answer_question` par question suffit aux deux colonnes** : le code
  rendu dit lequel des deux étages a tranché. Mesuré, profil `commercial` :
  refus corrects **5/8 → 8/8**, faux refus **1/22 → 3–4/22**.
  La cible joue **trois passes** parce que la barrière 2 est un jugement de modèle : le
  rapport publie une plage `n–m` et **nomme** les questions qui bougent (RAG-05, RAG-08),
  jamais une moyenne. Le renvoi depuis `rapport_gain.md` est écrit dans le générateur —
  il n'apparaîtra qu'à la prochaine régénération, cf. §2.8.

**Aucun code de production touché** — c'est un script de mesure. Le chiffre existe déjà, il
a été relevé pendant la revue.

`eval_rag.py` mesure le refus sur `search()` + comparaison au seuil, donc la **barrière 1
seule**, et le publie dans la ligne « refus corrects » du rapport E6. Or E1 vit dans
`answer_question`, qui a **deux** barrières. Mesuré à travers les deux, profil
`commercial` :

| | Mesuré le 2026-09-07 |
|---|---|
| refus corrects sur les 8 `hors_corpus` | **8/8** (barrière 1 : 5/8 ; la 2 rattrape RAG-23 · 24 · 29) |
| faux refus sur les 22 questions à cible | **5/22**, dont 2 seulement sont un défaut (cf. 2.2) |

Le rapport doit publier les **deux colonnes** — barrière 1, puis l'ensemble — sinon on relit
un chiffre de l'étage de recherche comme une mesure d'E1. C'est exactement l'erreur commise
dans la première version de la revue.

> **Succès** : la ligne « refus corrects » du rapport E6 renvoie explicitement vers
> `rapport_refus.md`, et plus personne ne peut lire 5/8 comme le refus servi.

### 2.2 La référence nue refusée par la barrière 2

- [x] **Expliciter la question transmise au rédacteur quand elle est réduite à une
  référence.** *Fait le 2026-09-07* — `question_for_writer()` dans
  `packages/rag_machines/tools.py`, appelée au seul bord de `writer.write()`.
  `check-rag-tools` **62 → 67** contrôles, au vert. `make mesure-refus` rejoué :
  faux refus **3–4/22 → 3/22**, et **la plage disparaît**.

  **Le critère de succès n'est atteint qu'à moitié, et l'autre moitié était mal posée.**
  Le « 5/22 → 2/22 » ci-dessous vient d'un relevé jetable ; le chiffre *commité* était
  `3–4/22`, et il tombe à `3/22`. Les trois qui restent sont RAG-19 (barrière 1, sujet
  absent du corpus), RAG-18 et RAG-20 (barrière 2, le corpus ne porte pas la réponse) —
  soit **exactement les trois que ce fichier annonçait comme devant rester refusées**. Zéro
  défaut résiduel, et non « 2/22 ».

  **L'effet qu'on n'avait pas prévu, et qui vaut plus que le chiffre** : les deux questions
  qui changeaient de verdict d'une passe à l'autre — RAG-05 et RAG-08 — ne bougent plus.
  Sur trois passes, **aucune question ne change de verdict**. C'était la référence nue qui
  rendait la barrière 2 instable : sur un énoncé qui n'en est pas un, le modèle n'avait rien
  de stable à juger. Le rapport publie donc trois colonnes fermes là où il publiait une plage.

  **Reste un choix d'écriture** : le rapport excuse RAG-19 et RAG-20 en citant le protocole
  §9, qui ne nomme pas RAG-18. Le motif de RAG-18 est établi (mesuré ici), il n'est écrit
  nulle part dans le rapport. À porter au générateur, ou à laisser au journal.

RAG-03 « REF-5313 » et RAG-05 « REF-5719 » : retrieval **parfait** (score 1,0000, Hit@1
8/8) et pourtant `contexte_insuffisant`. Cause : une référence nue n'est pas une question,
le rédacteur en cherche une, n'en trouve pas, déclare l'insuffisance.

Forme retenue, **testée hors dépôt** : la recherche garde la référence **nue** — c'est elle
que BM25 attrape — et **seule** la question passée à `writer.write()` devient « Quelles sont
les caractéristiques de la référence X ? ».

| | Avant | Après |
|---|---|---|
| RAG-03 · RAG-05 | `contexte_insuffisant` | **`ok`** |
| RAG-18 · RAG-20 · RAG-23 | `contexte_insuffisant` | inchangés |

⚠️ **Ne pas porter cette règle dans le `_SYSTEM_PROMPT` du rédacteur.** Mesuré aussi : elle
corrige RAG-03/05, mais **desserre la barrière 2 au-delà du cas visé** — RAG-18 et RAG-20,
stables en `contexte_insuffisant` sur trois passes, basculent en `ok`. Sur RAG-18 c'est un
recul d'E1 : le corpus ne porte pas cette réponse. Une règle générale dans un prompt ne sait
pas rester locale ; un cas nommé dans le code, si.

> **Succès** : `make check-rag-tools` couvre le cas (une référence nue ne produit pas
> `contexte_insuffisant`), et `rapport_refus.md` passe de 5/22 à 2/22 faux refus.

### 2.3 Contrôler l'invariant qui tient la lecture seule — pas seulement les charges

- [x] **Ajouter à `check_sql.py` un contrôle du réarmement de `query_only` sur connexion
  neuve.** *Fait le 2026-09-07* — bloc « Connexion (C2) », `_connect` importé nommément pour
  que le contrôle porte sur la fonction du service et non sur une connexion réécrite.
  Critère de succès vérifié : `_connect` remplacé par une connexion gardée → `(0, 0)` au lieu
  de `(0, 1)`, `check-sql` rouge sur ce seul contrôle.

**Les charges d'exfiltration sont déjà couvertes**, vérifié le 2026-09-07 : `check_sql.py`
les passe toutes au validateur (`VACUUM INTO`, `ATTACH`, `DETACH`,
`PRAGMA query_only=OFF`, `CREATE TABLE … AS SELECT`, deux instructions, `sqlite_master`
×2 → `ecriture_refusee` ou `perimetre_interdit`) **et** en repasse deux par la connexion
seule, hors validateur (`UPDATE`, `VACUUM INTO` → refusés). Il n'y a pas de trou de ce
côté-là.

Le trou est sur la **propriété qui porte réellement la garantie**. Mesuré ce jour :

| Couche | Ce qu'elle arrête seule | Contrôlé ? |
|---|---|---|
| `mode=ro` seul | rien de l'exfiltration : `ATTACH` + `CREATE TABLE p.vol AS SELECT * FROM produits` copie **120 lignes / 24 Ko, `prix_achat_ht` et `marge_pct` comprises** | — (c'est le contre-exemple, il n'a pas à être contrôlé) |
| `query_only=ON` | l'exfiltration… **jusqu'à `PRAGMA query_only=OFF`**, qui passe sur la connexion | ✅ le PRAGMA est refusé au validateur |
| **connexion neuve par requête** | **tout le reste** — le désarmement ne survit pas d'un appel au suivant | ❌ **non contrôlé** |

Mesure de l'invariant : connexion 1 après `PRAGMA query_only=OFF` → `query_only=0` ;
connexion 2 neuve → `query_only=1`. Une fois désarmée, la même connexion exfiltre
**159 744 o — la base entière — par un seul `VACUUM INTO`**.

**Pourquoi c'est le contrôle qui manque le plus.** `_connect()` ouvre une connexion neuve à
chaque `_run()`. Rien n'en atteste, et **le dépôt a déjà fait ce geste ailleurs** : au
chantier 3 étape C, `build_embedder` et `build_reranker` ont été mémoïsés pour la
performance (4 s par question). Le même réflexe appliqué à `_connect` — un `lru_cache`, un
pool, une connexion gardée au niveau du module — laisserait les **81 contrôles au vert** et
ferait tomber la lecture seule en silence, puisque le premier appel qui désarme profiterait
au suivant.

Forme du contrôle : ouvrir deux connexions par `_connect()`, désarmer la première, vérifier
que la seconde rend `query_only=1`. Trois lignes, dans le bloc « Connexion — la lecture
seule tient sans passer par le validateur (C2) ».

- [x] *Fait le 2026-09-07.* Accessoirement, au même endroit : `execute()` appelée **directement** avec une
  non-lecture rend `erreur_execution` (« seule une requête de lecture est exécutable »).
  Garde de dernier recours, jamais atteinte puisque `validate()` passe avant — mais elle
  n'est pas contrôlée non plus.

> **Succès** : mémoïser `_connect()` fait **rougir** `make check-sql`.

### 2.4 Consigner que le seuil du reranker n'est pas l'organe de refus

- [ ] **Ajouter la réserve chiffrée à `eval/protocole-mesure.md`.** Rien à recalibrer.

Les deux populations se chevauchent **irréductiblement** sur l'échelle du reranker :

| Population | Étendue du score du 1ᵉʳ résultat |
|---|---|
| `reference_exacte` (8) | 0,9998 – 1,0000 |
| `couverte` (14) | **0,0049** · 0,0732 … 0,9997 |
| `hors_corpus` (8) | 0,0015 … 0,5175 · **0,8422** |

Aucun seuil ne les sépare. Relever `rerank_threshold` de 0,0530 à 0,09 pour attraper RAG-23
(0,0868) refuserait RAG-13 (0,0732), une question réellement couverte. **Le seuil bas est le
bon réglage** : la barrière 1 est un pré-filtre bon marché — elle épargne un appel LLM sur 5
hors-corpus sur 8 —, la barrière 2 est le juge.

À écrire aussi, pour l'honnêteté de la comparaison : le 7/8 dense n'est pas une meilleure
séparation. Ses 8 scores hors corpus tiennent dans 0,798–0,845 pour un seuil à 0,8308 —
0,014 de marge sur RAG-29. C'est du cosinus comprimé, pas un discriminant.

> **Succès** : la question « faut-il relever le seuil ? » est fermée par un chiffre publié,
> pas par une opinion.

---

### 2.5 E1 n'est pas auditable depuis le journal

- [ ] **Décider si les sources rendues entrent au journal.**

`03-catalogue-tools.md` §6 liste `citations` parmi les champs de l'entrée de journal, avec le
motif « **E1 : les sources rendues** ». `journal.entry_for()` ne le porte pas. Conséquence :
sur un `answer_question` servi, le journal atteste qu'une réponse est partie et avec quelle
latence, mais **pas qu'elle citait ses sources** — la seule preuve d'E1 après coup est le
test d'acceptance, pas la trace.

Deux issues, et la seconde est défendable :

- **ajouter** les `doc_key` (ou les citations entières) à l'entrée sur `code="ok"`. Le
  journal étant réservé à `admin`, ce n'est pas une fuite ; c'est du volume ;
- **consigner** que la conception se contredit sur ce point : le même §6 écrit « `tool` ·
  `args` — **l'entrée, oui ; la sortie, jamais** », et `citations` est une sortie. Si l'on
  retient cette règle, `citations` n'a rien à faire au journal, et E1 s'atteste par la suite
  d'acceptance et `rapport_refus.md`.

> **Succès** : le choix est écrit quelque part, avec son motif. Aujourd'hui c'est un champ
> promis et absent, ce qui se lit comme un oubli.

### 2.6 `make lint` est rouge

- [x] **Corriger l'erreur qui nous appartient, neutraliser les deux autres.** *Fait le
  2026-09-07* — `make lint` **au vert** : `IncludeEnum.metadatas` dans `check_index.py`,
  et deux `# type: ignore[arg-type]` sur les décorateurs Chainlit, motif écrit au-dessus.
  À noter : mypy **refuse tout texte après le code d'erreur** sur la ligne du `ignore`
  (`Invalid "type: ignore" comment`) — le motif va sur la ligne précédente, pas à la
  suite. `make check-index` rejoué au vert : l'`IncludeEnum` n'est pas qu'une annotation,
  c'est l'argument réellement passé au SDK.

Vérifié le 2026-09-07 : `ruff` passe, `mypy` rend **3 erreurs** — celles que `CLAUDE.md`
annonce, ni plus ni moins.

| Fichier | Erreur | À qui elle appartient |
|---|---|---|
| `evals_and_controls/check_index.py:45` | `List item 0 has incompatible type "str"; expected "IncludeEnum"` | **à nous** — corrigible : passer `IncludeEnum.metadatas` au lieu de la chaîne |
| `web_client/app.py:64` et `:83` | signatures de `set_chat_profiles` / `set_starters` | **à Chainlit** — ses stubs attendent un `User \| None` que le décorateur n'envoie pas |

Un `make lint` rouge en soutenance se lit comme une dette, même quand deux erreurs sur trois
sont en amont. Corriger la première, et marquer les deux autres (`# type: ignore[arg-type]`
avec le motif en commentaire) pour que le rouge devienne vert **sans mentir** — un `ignore`
motivé est une décision, un lint rouge est une question sans réponse.

> **Succès** : `make lint` passe, et les deux `ignore` disent en une ligne pourquoi.

### 2.7 Le contournement `literalai` — le rendre durable ou vérifier qu'il est périmé

- [ ] **Trancher.**

État constaté : le dossier est déjà écarté sur cette machine
(`.venv/…/site-packages/_literalai_tests_ecarte`), et `make test` collecte les 12 tests. Le
contournement **fonctionne**, mais il est manuel et `CLAUDE.md` prévient qu'il faut le
rejouer après chaque `uv sync`.

Deux choses à vérifier, dans cet ordre :

1. **est-il encore nécessaire ?** `make test` passe `--import-mode=importlib`, qui résout
   précisément les collisions de noms de paquets. Renommer le dossier à l'endroit et
   relancer `make test` répond en une minute. Si les 12 tests passent, le contournement est
   périmé et la note de `CLAUDE.md` avec lui ;
2. s'il l'est encore, **l'automatiser** — une étape de `make install` après `uv sync`, plutôt
   qu'une consigne à se rappeler. Un contournement qu'on oublie de rejouer produit une suite
   qui ne collecte plus, symptôme éloigné de sa cause.

> **Succès** : plus aucune manipulation à retenir de tête après un `uv sync`.

### 2.8 Les cibles de mesure étaient cassées — et `rapport_gain.md` ne se régénère plus à l'identique

- [x] **Corriger `REPO_ROOT` dans les trois modules de mesure.** *Fait le 2026-09-07.*

**Trouvé en écrivant §2.1**, pas par la revue : `make eval-sql` échouait à l'instant sur
`packages/eval/questions_sql.jsonl` — un chemin qui n'existe pas. Même défaut sur
`eval_rag.py` et `eval_perimeter.py`, donc sur **les sept cibles `mesure-*` et `make mesure`**.

| | |
|---|---|
| Cause | `REPO_ROOT = parents[2]` — juste avant `dc5e9eb` (2026-09-04, « un sous-répertoire par domaine »), faux après. Les trois modules ont gagné un niveau, la constante non |
| Portée | `eval-sql`, `mesure-dense`, `mesure-lexical`, `mesure-hybride`, `mesure-perimetre`, `mesure-sans-nettoyage`, `mesure-sans-versions`, `mesure-rag-simple`, `mesure` |
| Échec | bruyant — `FileNotFoundError` à la lecture du jeu. Rien n'a été publié en silence |
| Correctif | `parents[3]`, avec le motif en commentaire. Vérifié : les quatre modules résolvent la racine |

`make mesure-perimetre` rejoué deux fois de suite : **déterministe**. Il diffère de la
version commitée d'**une ligne** — RAG-07 perd une place du top-5 chez `dev` et `support`
(P0 rend 4 au lieu de 5). Conclusion de l'axe 3 inchangée.

- [x] **DÉCISION prise le 2026-09-07 : republier.** `make mesure` rejoué en entier,
  `rapport_gain.md` régénéré, et les quatre endroits qui citaient « 2/8 » reprise :
  `CLAUDE.md` (deux lignes), la revue du jour, l'aide-mémoire ci-dessous. **Le journal du
  2026-09-02 garde ses chiffres** — on n'y réécrit pas l'histoire, on l'annote d'un renvoi
  vers l'entrée du jour.

C'est le vrai constat, et il est plus gênant que le chemin. `rapport_gain.md` **ne se
régénère pas à l'identique**, et pour deux raisons superposées :

1. **le rapport et ses propres CSV ne s'accordent plus.** `04e9bdf` (2026-09-03,
   « mesure-dense rejouée ») a réécrit `eval/resultats/mesure-dense.csv` **sans régénérer le
   rapport**. Régénérer à partir des CSV commités donne déjà MRR 0,354 et Recall 9/13 là où
   le rapport publie 0,375 et 11/13 ;
2. **l'index a changé depuis.** Une passe fraîche donne d'autres chiffres encore — les scores
   de RAG-06, RAG-07, RAG-13, RAG-17 et RAG-18 ont bougé, jusqu'à +0,04. Ce n'est pas du
   bruit numérique : c'est un texte indexé différent, cohérent avec la réingestion du
   chantier du périmètre.

| Configuration A (dense) | rapport commité | ses CSV commités | passe fraîche |
|---|---:|---:|---:|
| Hit@1 référence | **2/8** | 2/8 | **1/8** |
| Hit@1 fiche | 2/8 | 1/8 | 1/8 |
| MRR | 0,375 | 0,354 | 0,271 |
| Recall@5 type | 11/13 | 9/13 | 11/13 |

**Ce qui ne bouge pas** : `mesure-hybride` est rejoué **bit pour bit identique** (`git diff`
vide), donc B 3/8 et C 8/8 sont intacts. La thèse d'E6 n'est pas en cause — l'« avant »
devient *plus mauvais*, donc le gain publié est sous-estimé, jamais surestimé.

**Recommandation : republier.** Un rapport que ses propres entrées contredisent ne se défend
pas, et l'écart joue en faveur du produit. Mais c'est une décision : « 2/8 → 8/8 » est cité
dans `CLAUDE.md`, dans le journal de développement et dans la revue du jour. Republier
demande de reprendre les trois.

Le travail est prêt et vérifié — `make mesure` tourne en 49 s, sans appel de modèle. L'arbre
a été **restauré à HEAD** en attendant la décision : aucun chiffre publié n'a bougé.

> **Succès** : `make mesure` puis `git diff` sur `eval/` ne rend que ce qu'on a décidé de
> changer. Et le renvoi vers `rapport_refus.md` (§2.1) apparaît enfin dans le rapport.
> **Atteint.**

### 2.9 Les seuils n'ont pas bougé — vérifié, pas supposé

- [x] **Rejouer les deux calibrations après réindexation.** *Fait le 2026-09-07.*

La question se posait, et elle était fondée : un seuil de refus est réglé **sur des scores**,
et les scores ont bougé. Réponse mesurée, `make calibrer` et `make calibrer-hybride` :

| | Configuré | Reproposé après réindexation | Verdict |
|---|---:|---:|---|
| `REFUSAL_THRESHOLD` (A, cosinus) | 0,8308 | **0,8308** | inchangé |
| `RERANK_THRESHOLD` (C, reranker) | 0,0530 | **0,0530** | inchangé |

**Rien à reporter dans la configuration.** Et la raison est instructive : la calibration se
règle sur `questions_calibration.jsonl`, huit questions écrites pour ça, distinctes des trente
du jeu de mesure (`Q4` §6). Ce sont les scores du *jeu de mesure* qui ont bougé ; l'optimum
sur le *jeu de calibration* est resté au même endroit.

Les deux distributions sont reconduites telles quelles : A « populations **NON** séparables »
(couverte 0,820–0,882 contre hors corpus 0,799–0,831 — elles se chevauchent), C
« populations **séparables** » (0,053–0,993 contre 0,001–0,016). C'est l'argument de `Q4` §3
qui se rejoue à l'identique : le seuil a besoin d'une échelle apprise.

### 2.10 Le nettoyage du texte coûte 3/8 au dense — décomposé

- [ ] **Décider si ce constat entre dans `rapport_gain.md` ou reste au journal.**

La republication fait apparaître un chiffre contre-intuitif : la ligne « RAG simple » rend
**4/8** là où la configuration A « propre » rend **1/8**. Le baseline censé être le plus
faible bat la mesure « avant » du brief. Décomposé sur place, un drapeau à la fois :

| Configuration A (dense seul) | Hit@1 référence | MRR |
|---|---:|---:|
| `clean` · filtre **on** *(mesure-dense)* | 1/8 | 0,271 |
| `clean` · filtre **off** | 1/8 | 0,292 |
| `raw` · filtre **on** | **4/8** | 0,573 |
| `raw` · filtre **off** *(mesure-rag-simple)* | **4/8** | 0,573 |

**C'est le texte brut, et lui seul.** Le filtre de version ne change rien au Hit@1.

Ce n'est pas une contradiction du dossier, c'est une **précision de son périmètre** :
`Q3` §2 justifie le nettoyage par « +5 en Hit@3 », et le mesure **sur BM25**, où une
référence est un terme à IDF très élevé. Sur le dense, le même retrait coûte trois questions
sur huit. La décision de nettoyer n'est pas invalidée — dans la configuration **servie** (C),
`raw` et `clean` donnent tous deux 8/8 : le reranker rend l'arbitrage invisible.

À rejouer :
```bash
uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text raw --version-filter on
uv run python -m packages.rag_machines.evals_and_controls.eval_rag --config A --text clean --version-filter off
```

> **Succès** : personne ne peut demander en soutenance « pourquoi votre RAG simple bat votre
> mesure avant ? » sans obtenir la décomposition et son motif.

---

## 2 bis. Trouvé par le front de comparaison — 2026-09-08

Le front multirôle (`make web-compare`) a fait apparaître neuf défauts en une soirée, tous
**antérieurs à lui** — sauf **2bis.9**, qui est le sien : côte à côte, on voit un profil renoncer là où son voisin répond. En
mono-rôle il fallait penser à comparer. Détail et mesures : journal du 2026-09-08.

**À la reprise, commencer par 2bis.7 et 2bis.8** — décision de l'utilisatrice le 2026-09-08.
Ce sont les deux que la démonstration de soutenance expose le plus directement : elles
décident ce qu'une colonne affiche sur la question la plus simple qu'on puisse taper.

### 2bis.1 La redondance du corpus sature les candidats avant rerank

- [ ] **Donner au rerank de quoi trancher, sur un périmètre large.**

Constat : `dev` sert « Comment procéder à un retour ? », `support` et `commercial` la
**refusent** — alors qu'ils voient un **surensemble** du corpus de `dev` (318 et 350 éditions
contre 270). Plus de droits, moins de réponses.

Cause mesurée — la redondance est très inégale :

| type | documents | titres distincts | redondance |
|---|---|---|---|
| `procedure_sav` | 80 | **80** | 1,0× |
| `notice` | 70 | 43 | 1,6× |
| `fiche_technique` | 120 | 52 | 2,3× |
| **`note_interne`** | 80 | **5** | **16,0×** |

Cinq séries de 16 notes datées, même titre. Pour `support`, les 20 candidats fusionnés sont
20 documents distincts mais **2 titres seulement** — 12 « Alerte qualité fournisseur » et
8 « Retour terrain équipe commerciale ». La diversité effective est de **2**, et la procédure
SAV n'entre jamais dans les candidats. Le reranker ne se trompe pas : il ne voit pas le
document. Pour `dev`, dont le périmètre exclut `note_interne` : 20 candidats, **20 titres**.

Trois correctifs possibles, du plus juste au plus rapide :

| correctif | portée |
|---|---|
| **plafond de candidats par titre** avant rerank | attaque la cause ; à 3 par titre, 20 places portent ~7 sujets au lieu de 2 ; profite à toutes les questions |
| `rerank_candidates` **proportionnel au périmètre** | empêche la régression de revenir si un thème est rouvert ; ne règle pas la redondance elle-même |
| constante 20 → 40 | une ligne ; **pansement** — il faudrait dépasser ~48 places pour que `support` voie un 3ᵉ sujet de façon fiable. Que `depth=30` ait suffi sur cette question est un accident, pas une garantie |

⚠️ **Azure ne change rien à ce défaut**, mesuré : l'étage lexical est du BM25, aucun modèle, et
les 16 notes matchent « retour » à l'identique ; l'étage dense est dominé lui aussi (top-20 de
`support` entièrement composé de `note_interne`). Cf. §3.6.

> **Succès** : `support` et `commercial` servent ce que `dev` sert, et un contrôle interdit
> qu'un profil à périmètre plus large obtienne moins de réponses qu'un profil plus étroit.

### 2bis.2 Le seuil de refus coupe dans la population couverte

- [ ] **Trancher le sort de la barrière 1.** Lié à **§2.4**, qui documentait déjà le
  chevauchement mais pas sa portée.

« comment retourner un article ? » : retrieval **parfait** — la bonne procédure au rang 1 —
et pourtant `hors_corpus`, parce que le score de rerank vaut 0,0251 pour un seuil de 0,0530.
Le cas échoue **pour les trois profils** et à **toutes** les profondeurs : ce n'est pas 2bis.1.

Le même document, selon la tournure :

| question | score | verdict |
|---|---|---|
| « retour produit défectueux » | **0,9843** | servi |
| « Comment procéder à un retour ? » | 0,0859 | servi |
| « comment retourner un article ? » | 0,0251 | **refus** |
| « retourner un article » | 0,0107 | **refus** |

**Facteur 100 sur le même document.** Le §2.4 relevait la dispersion *entre* questions
(population `couverte` de 0,0049 à 0,9997) ; celle-ci est **intra-question**, ce qui en fait un
défaut du critère et non un cas limite. Et le seuil de 0,0530 est **au-dessus** du minimum
connu de la population couverte : il coupe mécaniquement dedans.

Aucune de ces formulations n'est dans un jeu d'évaluation — le faux refus publié à 3/22 ne les
voyait pas. Tous les refus observés portent le code `hors_corpus` : **la barrière 1, jamais le
modèle.**

E1 ne dépend pas d'elle : §2.1 mesure la barrière 1 seule à **5/8** et les deux à **8/8**. Le
seuil est une économie d'appels LLM (5 sur 8), pas la garantie.

> **Succès** : une question dont le corpus porte la réponse n'est plus refusée sans que le juge
> l'ait vue — et le rapport de refus publie le nouveau chiffre sur les quatre formulations.

### 2bis.3 Le prompt système publiait l'étage 1 en creux — **corrigé**

- [x] **Retirer l'énumération des tools du prompt, et déclarer la consigne côté serveur.**
  *Fait le 2026-09-08.*

`_SYSTEM_PROMPT` était une constante passée aux **cinq** profils, énumérant les **huit** tools,
suivie de « si l'un de ceux cités ci-dessus ne t'est pas proposé, il ne t'est pas accessible.
Ne le réclame pas et n'essaie pas d'obtenir son résultat autrement ». Deux défauts :

* **fuite** — le modèle apprenait l'existence des tools fermés et le disait : « je n'ai pas
  accès à l'outil de consultation de stock ». C'est le motif que `matrice.yaml` invoque pour
  fermer `get_schema` à `support`. La fuite **ne traversait pas le protocole** : le serveur ne
  servait bien que 5 tools à `dev`, c'est le client qui racontait les trois autres ;
* **renoncement** — `dev` n'essayait jamais la documentation sur une référence nue. Aucun tool
  appelé ⇒ aucun verdict ⇒ **aucune phrase figée** ⇒ un faux refus rédigé par le modèle,
  variable d'un appel à l'autre et absent du journal. Or `answer_question("REF-5313",
  profile="dev")` rend `ok`.

L'énumération était **redondante** : les descriptions des tools présents arrivent déjà par le
protocole. Le correctif est donc une **suppression**, puis un **déplacement** vers
`InitializeResult.instructions` — le seul canal du protocole pour une consigne permanente
(les prompts sont *user-controlled* et `PromptMessage.role` n'admet pas `system`). `gateway.py`
jetait le résultat du `initialize` ; il le lit désormais.

Mesure encadrante, 5 questions × 4 profils :

| | avant | prompt corrigé | consigne côté serveur |
|---|---|---|---|
| cellules avec fuite | **4 / 20** | 1 / 20 | **1 / 20** (faux positif du lexique) |
| sans aucun appel de tool | 11 / 20 | 8 / 20 | **8 / 20** |

Les trois cellules qui bougent sont exactement les trois fuites réelles ; les douze autres sont
inchangées, et les quatre « bonjour » restent sans appel. `dev` sur « REF-5313 » finit à
`answer_question·ok`. **Aucune mesure publiée n'est concernée** — vérifié : `build_agent` n'est
importé que par `cli.py` et `api.py`, les suites appellent les couches en dessous.

### 2bis.4 Une requête SQL qui ne référence aucune table

- [ ] **Décider si `ask_database` doit refuser une requête sans table.**

Observé une fois sur quatre : `support` obtient `ask_database·ok` sur « quelles tables contient
la base ? », profil auquel la matrice **retire** `get_schema`. Le SQL rendu récite le contrat
de lecture en littéraux — `SELECT 'clients' AS table_name UNION ALL …` — sans lire la base.

**Pas une fuite** : les cinq tables citées sont exactement celles de son périmètre, aucune
donnée ni colonne ne sort. **Pas reproductible** : trois essais de plus donnent deux
`contexte_insuffisant` et un `hors_schema`, tous en phrase figée.

Le constat structurel reste : **les six contrôles ne peuvent rien refuser à une requête sans
table.** 5a et 5b portent sur les tables et colonnes citées — il n'y en a aucune — et le
contrôle 6 `EXPLAIN` prépare sans peine un `SELECT` de littéraux.

> **Succès** : soit un septième contrôle (« une requête qui n'interroge aucune table n'a rien à
> faire dans `ask_database` ») avec son cas dans `check_sql.py`, soit la décision écrite que
> réciter un périmètre qu'on a le droit de lire n'est pas un défaut.

### 2bis.5 La mesure du prompt vient d'un script jetable

- [ ] **Porter la mesure en cible Make.**

Les chiffres de 2bis.3 ont été relevés hors dépôt, non conservés — exactement ce que l'en-tête
de ce fichier reproche aux mesures de la revue. Les chiffres sont au journal du 2026-09-08 ;
la mesure, elle, n'est pas rejouable.

Elle porte trois métriques par cellule (question × profil) : les tools appelés avec leur code,
et **si le texte nomme un tool absent du catalogue**. Le lexique de détection est explicite et
imparfait (« stock » apparaît légitimement quand `get_schema` liste la table `stocks`) — à
conserver tel quel, sa valeur étant d'être **identique avant et après**.

> **Succès** : `make mesure-prompt` rejoue les 20 cellules et publie un rapport, comme les cinq
> autres axes.

### 2bis.6 Le guide doit dire à l'intégrateur de ne pas énumérer le catalogue

- [ ] **Ajouter la consigne à `mcp_server/README.md`.**

Un intégrateur externe peut refaire **exactement** l'erreur de 2bis.3 : énumérer les huit tools
dans son prompt système parce que le guide les documente tous. Il publierait alors à son modèle
des tools que la matrice lui a fermés, et son modèle en parlerait à ses utilisateurs.

À écrire au §7 : **n'énumérez pas le catalogue dans votre prompt système — utilisez celui que
`tools/list` vous sert**, et lisez les `instructions` du `initialize`. Avec la limite, au même
titre que `readOnlyHint` : le serveur **recommande**, il ne contraint pas ; ce qui est garanti
quel que soit le client est ailleurs — étages 1 à 3, journal, et les phrases figées qui
voyagent dans l'enveloppe.

> **Succès** : le guide dit ce qu'un client ne doit pas faire de son côté, et pourquoi le
> serveur ne peut pas l'en empêcher.

### 2bis.7 Une référence nue : le stock ou la fiche ? — **par là qu'on reprend**

- [ ] **Décider ce que le produit répond à une référence nue.**

Sur `RAG-03` (« REF-5313 »), les quatre colonnes ne divergent pas par droits mais par
**aiguillage** :

| profil | ce qu'il rend | pourquoi |
|---|---|---|
| `dev` | la **fiche** documentaire | il n'a pas `check_stock` |
| `support` · `commercial` | le **stock** (SQL) | `check_stock` est décrit « le stock d'UNE référence REF-NNNN », et « REF-5313 » **est** littéralement cet argument |

**Le support a bien accès à la fiche**, vérifié : `answer_question("Quelles sont les
caractéristiques de la référence REF-5313 ?", profile="support")` rend `ok` avec la fiche
entière — perceuse à colonne 500 W, Torqua, garantie 2 ans, 118,30 € HT — et ses sources.
Aucun défaut de droits : le modèle s'arrête simplement au premier tool qui répond `ok`.

**L'agent n'est pas limité à une voie**, mesuré : sur les 80 cellules de la nuit, `dev` sur la
marge d'avril enchaîne `get_schema·ok` **puis** `answer_question·hors_corpus` — deux domaines
dans un seul appel. La boucle de `create_agent` n'est bornée par rien dans `cli.py`. Rien ne
l'empêche donc de faire les deux ; rien ne lui dit non plus qu'une référence produit a une
fiche **et** un stock.

Trois réponses possibles, et c'est un choix **produit**, pas un réglage :

| | pour | contre |
|---|---|---|
| le **stock** seul (actuel) | le tool figé correspond littéralement à l'argument | `RAG-03` attend la fiche |
| la **fiche** seule | c'est la cible du jeu RAG | perd le stock, que l'utilisateur voulait peut-être |
| **les deux** | objectivement la meilleure réponse | demande une consigne au serveur, et le §2.2 a mesuré qu'une règle générale de prompt ne reste pas locale |

⚠️ Les mesures RAG publiées **ne voient pas ce choix** : `eval_rag` et `eval_refusal`
appellent `answer_question` en direct. Le changer n'invalide aucun rapport.

> **Succès** : ce que rend une référence nue est écrit quelque part, et la démonstration de
> soutenance ne laisse plus croire à un effet de droits là où il n'y en a pas.

### 2bis.8 `dev` est instable sur une référence nue

- [ ] **Dissuader `get_document` d'accepter une référence produit.**

Deux passes consécutives, même question, même profil :

| passe | appel | résultat |
|---|---|---|
| 1 | `search_docs·ok` | la fiche remonte |
| 2 | `get_document·introuvable` | **« Aucune édition ne porte cet identifiant. »** |

`get_document` attend un identifiant d'**édition** (`notices/notice-REF-1589-v1.0`), pas une
référence produit. Sa description dit déjà « le texte intégral d'un document déjà identifié,
par son identifiant. N'accepte pas une question » — insuffisant pour écarter `REF-5313`, qui
*ressemble* à un identifiant.

Le levier est la **description côté serveur** — c'est l'aiguillage officiel, et le seul
(`gateway.py` la passe telle quelle). Y nommer la forme attendue et l'opposer explicitement à
une référence produit coûte une ligne, et se mesure sur trois passes puisque c'est un
jugement de modèle.

Noter le lot de consolation : `introuvable` est un code **servi** (`status: ok`), pas un refus,
et sa phrase est figée. L'échec est propre — mais c'est une non-réponse là où le corpus porte
la fiche.

> **Succès** : trois passes sur « REF-5313 » sous `dev` donnent le même tool documentaire, et
> aucune ne rend `introuvable`.

### 2bis.9 La colonne dit « servi » sur un renoncement — défaut du front

- [ ] **Faire dépendre le statut de colonne de la réponse, pas seulement des tools appelés.**

Relevé sur `SQL-01` (« combien de commandes en avril ? ») par l'utilisatrice, le 2026-09-08 :

| profil | badge | statut affiché | texte rendu |
|---|---|---|---|
| `dev` | `get_schema · ok` | **« servi », en vert** | « Je ne peux pas déterminer le nombre de commandes d'avril avec les outils accessibles. » |
| `support` · `commercial` | `ask_database · ok` | « servi » | **27 commandes**, avec le SQL |

`_statut()` dans `app_compare.py` prend le **premier verdict non-`ok` parmi les tools
appelés**, sinon `ok` — la règle de `cli.frozen_text`, reprise volontairement pour ne pas
avoir deux lectures du même carnet. Elle répond à « la gateway a-t-elle refusé quelque
chose ? », pas à « l'utilisateur a-t-il obtenu sa réponse ? ». `dev` appelle `get_schema`,
qui réussit, puis renonce : tous les verdicts sont `ok`, donc la colonne est verte.

**Le vert est faux du point de vue du lecteur**, et c'est le plus trompeur des trois états
possibles : sur une démonstration côte à côte, il fait croire que `dev` a été servi alors
qu'il n'a rien obtenu.

Le cas est le même que 2bis.3 vu d'un autre bord : **un renoncement du modèle n'a pas de
statut**, puisque aucun verdict ne le porte. Ici il en emprunte un — celui d'un appel
réussi qui n'a pas produit la réponse.

Pistes, à peser :

| piste | ce qu'elle coûte |
|---|---|
| un état d'affichage « **appelé, sans réponse** » quand aucun call n'a produit la donnée demandée | demande de savoir ce qui « produit la donnée » — non trivial, et le front ne doit pas juger le contenu |
| reprendre le **dernier** verdict au lieu du premier | ne règle rien ici : `get_schema·ok` est le seul |
| n'afficher « servi » que si le texte ne vient **pas** d'une rédaction libre du modèle — c'est-à-dire si une phrase figée ou un payload de données a été rendu | le plus honnête ; demande que `ChatResponse` dise **d'où vient le texte** (phrase figée, payload, ou rédaction) |

La troisième piste rejoint une lacune déjà nommée : rien ne distingue aujourd'hui, côté
client, un texte figé d'un texte rédigé. `frozen_text` le sait — il le jette.

> **Succès** : aucune colonne n'est verte quand l'utilisateur n'a pas obtenu de réponse, et
> le front n'a pas eu à juger le contenu pour le savoir.

### 2bis.10 La non-réponse d'un profil partiel n'a ni phrase ni chemin stables

- [ ] **Donner une phrase figée au renoncement, ou un verdict qui la porte.**

Question de l'utilisatrice le 2026-09-08 : « la formulation de l'agent `dev` est-elle celle
attendue ? » Non. Mesuré, quatre appels — même profil, même question (`SQL-01`) :

| | tool appelé | texte rendu |
|---|---|---|
| 1 | `get_schema·ok` | « …à partir du schéma seul. » |
| 2 | `get_schema·ok` | « …à partir du seul schéma disponible. La période couverte… » |
| 3 | **`answer_question·hors_corpus`** | **« Le corpus documentaire ne couvre pas cette question. »** — phrase figée |
| 4 | `get_schema·ok` | « …à partir du seul schéma de la base. » |

Trois défauts distincts, et le deuxième est le plus gênant :

1. **le texte varie** — trois tournures sur quatre, là où tout le dispositif du projet vise
   une non-réponse constante ;
2. **le chemin varie aussi.** Le tool appelé change, donc le **code journalisé** change :
   même profil, même question, deux lignes de journal différentes. Une mesure d'E5 sur ce cas
   serait instable, et une fois sur quatre le hasard fait sortir une **vraie phrase figée** —
   le même cas rend tantôt du figé, tantôt du rédigé ;
3. **l'allusion subsiste.** « à partir du seul schéma », « avec les outils accessibles » : le
   correctif de 2bis.3 a supprimé la *nomination* d'un tool absent, pas l'*allusion* à son
   absence. Le lexique de la mesure ne l'attrape pas — **limite à écrire dans le rapport**
   quand 2bis.5 sera fait.

**Il n'existe aucune phrase attendue pour ce cas**, et c'est la racine commune avec 2bis.3 et
2bis.9 : un renoncement du modèle n'a pas de verdict, donc rien ne peut le figer. Candidat
naturel — la phrase de `tool_interdit`, « Cette information n'est pas accessible avec votre
profil. » : elle est **vraie du point de vue de l'utilisateur** même si aucun refus technique
n'a eu lieu, et elle est déjà celle que `sans_role` reçoit.

Mais la poser côté client demanderait de savoir *quand* le modèle renonce — ce que le front ne
peut pas juger sans lire le contenu (cf. 2bis.9). Deux voies :

| voie | ce qu'elle implique |
|---|---|
| **côté serveur** : un tool refuse au lieu d'être absent — l'étage 1 laisse voir, l'étage 2 refuse | rend un verdict, donc une phrase figée **et** une ligne de journal ; mais c'est revenir sur l'étage 1, dont l'absence de journalisation est un écart **déjà décidé** le 2026-09-06 |
| **côté client** : `ChatResponse` dit d'où vient son texte, et une rédaction libre sur une question de domaine est remplacée par la phrase figée | ne touche pas la gateway ; demande de distinguer « question de domaine » d'une salutation, que rien ne fait aujourd'hui |

> **Succès** : trois appels identiques sous `dev` sur une question hors de ses droits rendent
> **la même phrase** et **la même ligne de journal**.

---

## 3. Décisions

**Trois sur cinq ont été tranchées le 2026-09-07** (3.1 · 3.4 · 3.5) : elles portent
désormais une action et son motif, plus une question. Restent ouvertes 3.2 et, pour
mémoire, le constat 3.3.

### 3.1 L'argument `collections` — **tranché le 2026-09-07 : l'exposer, sans `enum`**

- [x] **Exposer `collections` sur `answer_question`, `search_docs` et `list_sources`** —
  `collections: list[str] | None = None` dans `mcp_server/server.py`, transmis tel quel au
  handler, qui le consomme déjà. *Fait le 2026-09-07* — un `_COLLECTIONS` annoté écrit une
  fois pour les trois, description incluse, **sans `enum`** ; `_documentary()` retire les
  arguments absents pour qu'un `None` ne soit pas journalisé comme un argument reçu.
  Exercé de bout en bout sous `dev` : 270 sources sans argument, 120 en `fiche_technique`,
  et `note_interne` (fermée) rend le même `perimetre_interdit` que `zzz_inexistante`
  (inventée) — indistinguables, comme l'arbitrage le voulait.

`03-catalogue-tools.md` promet `answer_question(question, collections)`,
`search_docs(…, collections)`, `list_sources(collections)`. La logique existe et est
testée (`_resolve_perimeter` : refus explicite sur collection fermée, jamais de rognage
muet), mais **les tools MCP ne l'exposent pas** — elle est donc inatteignable depuis un
client.

**Pourquoi exposer plutôt que retirer la promesse.** Retirer rendrait morte la branche
`closed` de `_resolve_perimeter` et les contrôles de `check-rag-tools` qui la couvrent —
on remplacerait un delta de catalogue par du code mort, ce qui est le plus mauvais des deux
échanges. Exposer referme le delta et garde le code vivant.

**Pourquoi *sans* `enum`, et c'est le point qui se discute.** Un `enum` des quatre
`doc_type` dans l'`inputSchema` publierait l'existence de `note_interne` à un client `dev`,
qui ne peut pas l'atteindre — exactement ce que la doctrine du dépôt refuse partout
ailleurs (`list_sources` filtré, refus qui ne nomme rien, liste blanche). Un **tableau libre
de chaînes** n'a pas ce défaut : un nom inventé et un nom fermé reçoivent **tous deux**
`perimetre_interdit`.

C'est l'arbitrage déjà écrit pour `get_document`, mot pour mot : « un identifiant inventé
sous un thème fermé reçoit `perimetre_interdit` alors qu'il n'existe pas — ce qui n'apprend
rien sur son existence, et c'est le bon compromis ». On réapplique une décision prise, on
n'en invente pas une.

> **Succès** : `scripts/mcp_client.py --profile dev --tool search_docs --args
> '{"query":"…","collections":["note_interne"]}'` rend `refused`, et le journal porte
> l'`etage` 3 avec la collection en `forbidden`. Aucune phrase servie au client ne nomme
> `note_interne`.

### 3.2 `access_rag.search_for_profile()` : sans consommateur

- [ ] **Décider.**

Seul appelant : `check_perimeter.py:106`. Aucun tool ne l'emprunte — `tools.py` appelle
`perimeter_for()` puis `search()` directement. Soit un tool l'emprunte, soit elle descend
dans `check_perimeter.py`, qui est la seule chose qui s'en sert.

### 3.3 Deux gardes défensifs jamais franchis — à laisser, mais sachant

Constat, pas action. Ni bug ni dette, mais ce ne sont pas des garanties vérifiées :

- le garde `strategy="lexical"` + `threshold` de `search()` lève `ValueError` à juste titre,
  mais **aucun appelant ne peut le déclencher** : `threshold_for("lexical", …)` rend `None`
  (vérifié par `check_rag_tools.py:170`) et les deux harnais passent toujours
  `threshold=None` ;
- `top_k` n'est **jamais varié** : `eval_rag` lui passe le défaut.

---

### 3.4 Matrice vs cadrage DSI — **tranché le 2026-09-07 : ne rien changer, et écrire le motif**

- [x] **Écrire les deux motifs dans `mcp_server/matrice.yaml`, puis les reprendre au mini
  guide.** *Les deux faits le 2026-09-07* — §10 du guide les porte en tableau —
  écrits **au ras des lignes concernées** plutôt qu'en tête : chacun ouvre par
  « ÉCART AU CADRAGE, ASSUMÉ » et cite le cadrage, dans le bloc `support`, à côté de
  `themes_notes` pour les notes et de `ventes` pour la table. **Matrice inchangée** :
  `revision`, profils, tools, collections, thèmes et colonnes sont identiques (relu par
  `yaml.safe_load`).
  Reste à faire : **les reprendre dans le mini guide (§1.1).**

`docs/cadrage_dsi.md` est le document **normatif pour la DSI**, et il est plus restrictif
que `mcp_server/matrice.yaml` :

| Point | Cadrage DSI | Matrice implémentée |
|---|---|---|
| notes internes | « **réservées** au profil `commercial` » | `support` a `note_interne` sur **3 thèmes** — 318 éditions atteignables |
| table `ventes` pour `support` | « `ventes.*` (**table non accessible**) » | `support` lit `ventes` **moins `marge_ht`** — 5 colonnes sur 6 |

**Motif du point 1 — les notes.** Déjà argumenté en conception (`Q3` §6) : le grain de
fermeture est le **thème**, pas la collection. Fermer `note_interne` coûterait au support ses
**16 notes `alerte-qualite`**, son métier même ; et le marqueur « Diffusion restreinte » ne
couvre que 16 des 32 notes sensibles, donc ne peut pas servir de critère. Motif existant, à
recopier là où il sera cherché.

**Motif du point 2 — `ventes`. Il manquait ; il a été trouvé le 2026-09-07, et il est
décisif.** `check_sql.py:61` teste, **au profil `support`** :

```sql
SELECT p.nom, SUM(v.marge_ht) FROM ventes v JOIN produits p ON p.ref = v.ref
```

C'est **le seul cas `support` qui exerce la résolution d'alias du contrôle 5b** — « un alias
d'une lettre suffit à sortir les marges », la panne que `referenced_columns()` existe pour
désamorcer. Fermer `ventes` au support ferait attraper cette requête au contrôle **5a** (la
table) au lieu de **5b** (la colonne, alias résolu) : le test resterait **vert pour la
mauvaise raison**, et le contrôle le plus subtil du validateur perdrait sa seule épreuve.

C'est le raisonnement déjà écrit dans `matrice.yaml` à propos d'`ask_database` au support —
« retirer le tool ferait passer les tests pour la mauvaise raison ». Même argument, autre
ligne.

Vérifié au passage, pour ne pas se tromper sur ce qui protège quoi : les **4 questions
`table_interdite` du support** (SQL-17 → SQL-20) portent toutes sur les **marges**, jamais
sur `ventes` comme table. Fermer `ventes` ne les casserait donc pas — ce n'est pas l'éval qui
tient ce choix, c'est le contrôle 5b. À dire ainsi, et pas autrement.

> **Succès** : la question « le cadrage dit `ventes` non accessible au support, pourquoi
> l'ouvrez-vous ? » a une réponse en deux phrases, et elle porte sur une propriété de test,
> pas sur une préférence.

### 3.5 Le contrat de réponse — **rouvert et refermé le 2026-09-07 : le contrat servi est déclaré**

- [x] **Déclarer au protocole l'enveloppe DSI, et consigner ce qui reste d'écart.**
  *Fait le 2026-09-07* — `mcp_server/output_schemas.py` (les huit schémas),
  `mcp_server/server.py` (les huit tools rendent l'enveloppe, `list_tools` publie le schéma),
  `make check-contrat` : **121 contrôles**, le premier contrôle du serveur MCP du projet.

**La décision initiale reposait sur deux faits faux. Les voici, et ce qu'ils étaient.**

1. « `outputSchema` non déclaré » (revue §B.1) — **faux**. FastMCP le dérive de l'annotation
   de retour sans qu'on le lui demande : `-> str` publiait
   `{"required":["result"],"properties":{"result":{"type":"string"}}}` et rendait
   `structuredContent = {"result": "<l'enveloppe en chaîne>"}`. **Le défaut n'était pas une
   absence, c'était un contrat qui promettait une chaîne** — publié dans `tools/list`, donc lu
   par tout client externe, et validé par le SDK sans rien attraper ;
2. « cela changerait `content[0].text`, on mettrait 12/12 en risque » — **faux**. Le bloc texte
   passe de `json.dumps(view, ensure_ascii=False)` à `pydantic_core.to_json(view, indent=2)` :
   le même objet à l'indentation près. Les trois seuls clients MCP du dépôt font tous
   `json.loads`. `make test` reste 12/12, vérifié.

**Ce qui a été décidé, et le pourquoi de chaque tiers.** Un type de retour joue *deux* rôles
dans FastMCP : il dérive le schéma **et** il filtre la sortie. Mesuré sur un modèle plus
étroit que le dict rendu : `content[0].text` garde la clé, `structuredContent` la perd — **les
deux moitiés de la réponse divergent en silence**. Or le payload servi est un surensemble du
cadrage (`code` partout, `conventions`, `truncated`, cinq clés de citation contre trois). D'où
le partage :

| Partie du schéma | D'où elle vient | Pourquoi |
|---|---|---|
| `status` | **calculée** depuis `DB_STATUS_BY_CODE` / `RAG_STATUS_BY_CODE` | elle *est* la table, elle ne la recopie pas — un enum qui ne peut pas dériver |
| `payload` | **écrit à la main**, par tool | la seule moitié qui dit quelque chose, et le §4 conçu la spécifiait déjà |
| `payload.code` | décrit, **sans `enum`** | un enum incomplet transforme une réponse valide en panne — et les codes ne sont pas relevables par lecture : `perimetre_interdit` passe par une constante, `aucune_ligne` est propagé depuis l'exécution |

Le type de retour reste `dict[str, Any]`, donc **rien n'est filtré et rien ne peut diverger**.
Le schéma publié est réécrit dans `SorabelMCP.list_tools` — le décorateur n'accepte pas de
schéma, et cette méthode est déjà celle qui décide du catalogue *et* celle qui remplit le cache
dont le serveur se sert pour valider. Le schéma servi et le droit d'accès sont posés au même
endroit, sur la même liste.

**Le champ `hint` du §4 est abandonné sans remplaçant**, décidé et consigné : le cadrage ne le
prévoit pas, et l'ajouter au payload ouvrirait un écart dans l'autre sens. Sa fonction est
tenue par les descriptions des tools, qui nomment déjà le recours — « Pour obtenir les extraits
bruts sans rédaction, utiliser `search_docs` ». `isError` tranché code par code reste abandonné
lui aussi : le serveur ne le pose que sur une violation de schéma, et le discriminant du client
est `status`, puis `payload.code`.

**Ce qui reste d'écart, et il faut l'écrire au mini guide** : les **noms de champs**. Le §4
conçu dit `code` / `hint` / `reponse` / `citations` ; le servi dit `status` / `payload` /
`message`, avec `code` dans le payload. Ce sont deux contrats concurrents, et un `outputSchema`
ne peut décrire que celui qui est servi. La portée de cette case a donc changé : **on déclare le
contrat servi, on n'adopte pas le contrat conçu.**

`03-catalogue-tools.md` §4 spécifie, sur trois pages et avec un JSON Schema par tool, une
sortie MCP 2026-07-28 : `outputSchema` d'union, `structuredContent`, `isError` tranché code
par code, champ `hint` portant le recours. Le code en implémente désormais **les deux
premiers** : il sert `{status, payload, message}` de `docs/cadrage_dsi.md`, en un seul
`TextContent` **et** en `structuredContent`, sous un `outputSchema` déclaré par tool. Restent
non implémentés `isError` tranché code par code et `hint` — les deux **abandonnés par
décision**, pas par omission.

Ce n'est pas une régression — le cadrage est le contrat imposé, la suite d'acceptance lit
`result["status"]` et `payload["answer"]` — mais **la validation du dossier de conception est
la porte d'entrée du brief**, et le jury lira une spécification dont le code s'écarte encore
sur les noms de champs.

À reprendre au mini guide : le contrat retenu et pourquoi (le cadrage prime, le test fait
foi) · **ce qui a été regagné** — `structuredContent` et l'`outputSchema`, que §4 défendait
comme « le chemin correct sans avoir à y penser », et que le schéma publie en décrivant
l'asymétrie de `PAYLOAD_KEPT` (« `answer` ABSENTE dès que `code` n'est pas `ok` ») · ce qui
reste écarté et pourquoi : `isError` — le discriminant du client est `status` puis
`payload.code` — et `hint`, **abandonné sans remplaçant**, sa fonction étant tenue par les
descriptions des tools, qui nomment déjà le recours.

> **Succès** : la question « pourquoi votre catalogue conçu ne ressemble pas à votre
> serveur ? » a une réponse écrite d'avance, avec ce qu'elle coûte.

### 3.6 Passer embeddings et rerank sur Azure — **à décider, pas avant l'IGU**

- [ ] **Décider si l'on bascule.** Question de l'utilisatrice le 2026-09-08, pendant le
  cadrage de l'IGU : « si je configure l'embedder en azure foundry, ça change le besoin en
  ram ? » Réponse mesurée : **oui, et moins qu'on croit.**

| Configuration | Pic (`ru_maxrss`) par processus |
|---|---|
| embedder local seul | 770 Mo |
| reranker local seul | **762 Mo** |
| les deux locaux | 1 053 Mo |

Les trois chiffres disent la même chose : **~700 Mo, c'est torch + sentence-transformers**,
pas les poids — chaque modèle n'ajoute que ~290 Mo par-dessus le runtime partagé. Donc
l'embedder seul sur Azure ne fait descendre le pic que de 28 % ; le gain réel n'arrive
qu'en basculant **les deux**, torch n'étant alors jamais importé. Et la RSS *résidente*
mesurée sur des serveurs vivants est bien plus basse que le pic (**245–280 Mo** après un
appel documentaire, **~90 Mo** avant), donc la RAM est un motif faible.

Ce que ça coûte, en revanche, est lourd et connu :

| Ce qu'il faut refaire | Pourquoi |
|---|---|
| `make reindex` | l'index Chroma porte des vecteurs e5-base à 768 dimensions ; `text-embedding-3-*` n'a ni la même géométrie ni la même dimension |
| `make calibrer` | le seuil dense **0,8308** est sur l'échelle de e5 |
| `make calibrer-hybride` | `rerank_threshold` **0,0530** est sur l'échelle du reranker ; un rerank LLM la change |
| rejouer `rapport_gain.md`, `rapport_perimetre.md`, `rapport_refus.md`, `rapport_acces.md` | les chiffres publiés le 2026-09-07 deviennent caducs |

**Le reranker se commute sans réindexer** ; l'embedder, non. Les deux demandent une
recalibration.

**Et le motif qui restait est tombé le 2026-09-08** : la bascule **ne règle pas §2bis.1**,
mesuré. L'étage lexical est du BM25 — aucun modèle, un comptage de termes — et les 16 notes
« Retour terrain » matchent « retour » à l'identique ; l'étage dense est dominé lui aussi
(top-20 de `support` entièrement composé de `note_interne`). Le seul organe qui tranche
correctement est le rerank, et il tranche déjà bien : 0,0859 contre 0,0050, facteur 17. Il ne
se trompe pas, **on ne lui montre pas le document** — un reranker Azure noterait la même liste
de candidats, même angle mort. Il ne reste donc à cette bascule aucun motif technique dans ce
dossier, seulement la RAM, dont le §ci-dessus montre qu'elle est un motif faible.

> **Succès** : soit une bascule mesurée « avant/après » (les deux seuils recalibrés, les
> quatre rapports rejoués, le gain de démarrage chiffré), soit la décision écrite de rester
> en local avec le motif — et dans les deux cas, plus jamais dans le cadre d'un travail
> d'interface.

## 4. Dérives documentaires — mineures

- [ ] **`CLAUDE.md` décrit encore l'IGU splittée comme « le dernier livrable nommé qui
  manque ».** Elle est livrée le 2026-09-08 (`make web-compare`). Ce qui manque désormais est
  l'**URL** (§1.3), pas l'interface. À reprendre dans la section « Où en est le projet »,
  avec les quatre suites de contrôles inchangées et les deux nouvelles cibles de front.

- [ ] `eval/rapport_gain.md` annonce « Généré par `scripts/eval_rag.py --report` » ; le
  script vit dans `packages/rag_machines/evals_and_controls/eval_rag.py`. Le rapport n'est
  pas faux, son en-tête l'est. **Corriger le générateur**, pas le fichier — `make mesure` le
  réécrit en entier.
- [ ] `packages/web_client/app.py` porte encore en docstring « Écart assumé […] ici c'est le
  client qui déclare son rôle […] Il disparaît avec le serveur MCP ». **L'écart est
  refermé** depuis l'étape C : le rôle choisit *quel processus* on interroge, jamais *quel
  argument* on passe.
- [x] ~~`CLAUDE.md` annonce `make check-feedback` à 102 contrôles ; la cible en rend **103**.~~ *Fait le 2026-09-07* — les deux occurrences corrigées, et les décomptes de la vague 1 mis à jour dans la foulée (`check-sql` 83, `check-rag-tools` 67, `lint` au vert).
  Et `check-sql` y est annoncé à 81 : il en rend **83** depuis §2.3.
  Écart de décompte, pas de régression.

---

## 5. Aligner le dossier de conception, ou consigner l'écart

Le dossier de conception est **évalué** (« validation du dossier de conception : porte
d'entrée du brief »). Quatre endroits où il décrit autre chose que le code. Aucun n'est un
défaut de code — **le développement a eu raison à chaque fois** —, mais chacun se lit comme
une incohérence si personne ne l'a écrit.

Deux conduites possibles, et il faut choisir **une seule** et l'appliquer aux quatre :
mettre le dossier à jour (il devient le reflet du livré), ou le laisser tel quel et tenir un
**tableau d'écarts** unique — le journal de développement en tient déjà un, à compléter.

- [ ] **`04-chemin-text-to-sql.md` — « cinq contrôles » et « un seul aller-retour ».** Le
  code en a **six** (le 6ᵉ est `EXPLAIN`, que la V3 avait explicitement retiré) et fait
  **une reprise** sur requête fausse. Les deux sont justifiés dans `validator.py` et mesurés
  (`rapport_sql.md` : 0/24 reprises déclenchées sur le jeu). Le diagramme de séquence et le
  drawio V3 disent encore cinq et zéro.
- [ ] **`02-modele-chunk.md` — le JSON Schema dit `doc_key` « seul mode d'adressage de
  `get_document` ».** Le code accepte aussi un `edition_id`, parce que T11 lui passe le
  `doc_id` d'un hit de `search_docs`. Une phrase à corriger.
- [ ] **`03-catalogue-tools.md` — la sortie de `list_sources`.** Conçue « par collection :
  nombre de documents et d'éditions, plage de dates », implémentée en **liste plate**, qui
  est la forme du cadrage. Le filtrage par périmètre, lui, est bien conforme.
- [ ] **`03-catalogue-tools.md` §2 et `matrice.yaml` — quatre profils contre cinq.** `admin`
  a été ajouté au développement, avec un neuvième droit (`read_journal`) qui n'est pas un
  tool du catalogue DSI. Motivé dans `mcp_server/matrice.yaml`, absent du dossier.

> **Succès** : un lecteur du dossier qui ouvre le code ne trouve aucune surprise non
> annoncée.

## 6. Pour la soutenance — où vit la réponse

Aide-mémoire, pas une tâche. Les six exigences seront « respectées **et démontrées** » ; les
choix d'architecture seront « justifiés ». Voici ce qui répond, et ce qui manque encore.

| Question probable | Réponse, et où elle vit |
|---|---|
| « Prouvez le gain de l'hybride » | `eval/rapport_gain.md` — 1/8 → **8/8** Hit@1, MRR 1,000, avec ses limites méthodologiques publiées |
| « Le refus hors corpus marche-t-il ? » | **8/8**, deux barrières — à publier dans `rapport_refus.md` (§2.1). Ne **pas** citer le 5/8 du rapport E6 : c'est la barrière 1 seule |
| « Aucune écriture ne passe ? » | 6 contrôles + `mode=ro`/`query_only` + **une instruction, une connexion neuve**. Mesures d'attaque dans la revue §A.2 ; contrôle de l'invariant à ajouter (§2.3) |
| « Pourquoi pas une liste de mots interdits ? » | `VACUUM INTO` sort **159 744 o** sans écrire et sans mot noir. `mode=ro` seul laisse copier **120 lignes, marges comprises**. Mesuré |
| « Le support voit-il une marge ? » | non — trois colonnes fermées **ensemble** (fermeture par dérivation), contrôlé sur la projection, le `WHERE`, l'`ORDER BY` et les alias résolus par scope |
| « Montrez le journal » | `make journal`, et T12 vérifie une ligne par appel, servi comme refusé |
| « Et E5, chiffrée ? » | **rien à montrer aujourd'hui** — c'est §1.2, le trou le plus visible du dossier |
| « Où est le mini guide d'accès ? » | **`mcp_server/README.md`** — et `make client PROFILE=…` démontre les cinq profils |
| « Votre catalogue conçu ne ressemble pas à votre serveur » | **§3.5, fait** — l'`outputSchema` du §4 est publié (`mcp_server/output_schemas.py`) ; reste l'écart de **noms de champs**, à écrire au mini guide |
| « Le cadrage dit `ventes` non accessible au support » | §3.4, à écrire avant |
| « Un lien vers l'interface ? » | §1.3 |

## Ordre d'attaque proposé

Trois vagues. La règle : **ce qui protège une garantie d'abord, ce qui la prouve ensuite,
ce qui la raconte en dernier** — et rien de ce qui touche au code servi après avoir commencé
à écrire les livrables.

### Vague 1 — protéger et prouver (code + mesure)

| # | Tâche | Pourquoi à ce rang | Taille |
|---|---|---|---|
| 1 | ~~**2.3** invariant `query_only`~~ **fait le 2026-09-07** | le seul de la liste dont l'absence peut faire **tomber une garantie en silence** | `check-sql` 81 → **83** |
| 2 | ~~**2.1** `make mesure-refus`~~ | **fait le 2026-09-07** — axe 4, 3 passes, `rapport_refus.md` | 5/8 → **8/8** |
| 3 | ~~**1.2** `make mesure-acces`~~ | **fait le 2026-09-07** — axe 5, `rapport_acces.md`, E5 sur ses deux moitiés | 50/50 · **0 fuite** |
| 4 | ~~**2.2** référence nue~~ | **fait le 2026-09-07** — faux refus 3–4/22 → **3/22**, et la plage disparaît | `check-rag-tools` 62 → **67** |
| 5 | ~~**2.6** `make lint` au vert~~ | **fait le 2026-09-07** — un rouge en soutenance est une question sans réponse | `lint` **au vert** |
| 6 | ~~**2.8** republier `rapport_gain.md`~~ | **fait le 2026-09-07** — décision prise, `make mesure` rejoué en entier | `mesure-hybride` identique |

**La vague 1 est close.** Les six items sont faits, et les deux garanties qu'elle protégeait
sont désormais contrôlées (`query_only` sur connexion neuve) ou mesurées (le refus servi sur
ses deux barrières). Plus rien de ce qui change ce que le produit *fait* n'est en attente.

### Vague 1 bis — ce que le front a révélé (2026-09-08)

Elle est de la même nature que la vague 1 : **ce qui protège une garantie d'abord.** Un seul
item est fait, et c'est celui qui fermait une fuite.

| # | Tâche | Pourquoi à ce rang | État |
|---|---|---|---|
| 1b | ~~**2bis.3** le prompt publiait l'étage 1~~ | une **fuite** d'existence, et la cause des faux refus non journalisés | **fait le 2026-09-08** — fuites 4/20 → 1/20 |
| 2b | **2bis.7** référence nue : stock ou fiche | **par là qu'on reprend** — décide ce qu'affiche la colonne sur la question la plus simple qu'on puisse taper | **ouvert** |
| 3b | **2bis.8** `dev` instable sur une référence nue | même cause visible, et `introuvable` là où le corpus porte la fiche | **ouvert** |
| 4b | **2bis.1** saturation par redondance | un profil à **plus** de droits obtient **moins** de réponses : c'est E1 qui recule là où la matrice s'élargit | **ouvert** |
| 5b | **2bis.2** le seuil coupe dans le couvert | refuse une question dont le corpus porte la réponse, **sans que le juge la voie** | **ouvert**, à trancher avec §2.4 |
| 6b | **2bis.5** cible Make de la mesure | sans elle, le chiffre de 1b n'est pas rejouable | **ouvert** |
| 7b | **2bis.4** requête SQL sans table | ni fuite ni reproductible, mais un trou de contrôle nommé | **ouvert** |
| 8b | **2bis.6** consigne au guide | un intégrateur peut refaire 2bis.3 chez lui | **ouvert**, écriture |
| 9b | **2bis.9** colonne verte sur un renoncement | le seul défaut **du front lui-même** ; trompeur en démonstration | **ouvert** |
| 10b | **2bis.10** la non-réponse n'a ni phrase ni chemin stables | même racine que 1b et 9b : un renoncement n'a pas de verdict, donc rien ne le fige | **ouvert** |

**Ordre de sacrifice** : 7b, puis 8b, puis 6b. Ne pas sacrifier 2b à 5b — ce sont les quatre
seuls de cette liste qui changent ce que le produit **répond**.

### Vague 2 — décider (rien à coder avant)

Les trois qui bloquaient le mini guide sont **tranchées**. **6 et 7 sont appliquées** (2026-09-07) ;
8 est de l'écriture, elle passe donc de fait en vague 3 avec le mini guide.

**Il ne reste que 9 et 10** — deux décisions, aucune ne bloque le mini guide.

| # | Tâche | État |
|---|---|---|
| 6 | ~~**3.1** exposer `collections` sans `enum`~~ | **fait le 2026-09-07** — `server.py`, schéma vérifié sans `enum` |
| 7 | ~~**3.4** motifs dans `matrice.yaml`~~ | **fait le 2026-09-07** — écrits au ras des lignes ; reste leur reprise au mini guide (§1.1) |
| 8 | ~~**3.5** contrat de réponse~~ | **fait le 2026-09-07** — rouvert : deux faits faux le fondaient. `outputSchema` déclaré, 121 contrôles |
| 9 | **2.5** `citations` au journal | **ouvert** — ajouter, ou consigner la contradiction de la conception |
| 10 | **3.2** `search_for_profile()` | **ouvert** — sans effet sur le reste ; à trancher avant de la voir grossir |

### Vague 3 — raconter (écriture, une fois les décisions prises)

| # | Tâche | Dépend de |
|---|---|---|
| 11 | ~~**1.1** mini guide d'accès~~ | **fait le 2026-09-07** — `mcp_server/README.md`, et la seconde exigence du brief (démonstration scriptée) relevée à cette occasion |
| 12 | **5** aligner le dossier ou tenir le tableau d'écarts | 3.5 |
| 13 | **2.4** réserve sur le seuil au protocole | — |
| 14 | **4** + **2.7** en-têtes, docstrings, contournement `literalai` | — |
| 15 | **1.3** URL de l'IGU | un choix d'hébergement, pas du code |

**Si le temps manque**, l'ordre de sacrifice est l'inverse : 15, puis 14, puis 12. Ne pas
sacrifier 1 à 5 — ce sont les seules qui changent ce que le produit **fait** ou ce qu'on peut
**prouver** qu'il fait. Et ne pas sacrifier 11 : c'est un livrable nommé au brief.
