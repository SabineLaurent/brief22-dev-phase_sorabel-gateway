# TODO post-revue — 2026-09-07

Issu de [`2026-09-07-revue-brief22-phase-developpement.md`](2026-09-07-revue-brief22-phase-developpement.md).
Ordre : **ce que le brief exige** d'abord, **ce que la revue a trouvé** ensuite, **les
décisions à prendre** enfin. Chaque entrée porte son critère de succès — sans quoi on ne
sait pas quand la barrer.

État de départ, mesuré le 2026-09-07 : `make test` 12/12 (48,46 s) · `check-sql` 81 ·
`check-feedback` 103 · `check-rag-tools` 62 · `check-perimetre` 31.
Après la vague 1 : `check-sql` **83** · `check-rag-tools` **67** · `make lint` **au vert**.
Après §3.5 : `check-contrat` **121** — cible neuve, premier contrôle du serveur MCP.

**Les mesures citées ici ont été relevées par des scripts jetables**, hors dépôt et non
conservés : refaire la mesure fait partie de la tâche qui la cite (§2.1, §2.2, §2.3, §2.4).
Les chiffres, eux, sont dans ce fichier — ils servent de valeur attendue, pas de preuve.

---

## 1. Exigé par le brief — non livré

### 1.1 Le mini guide d'accès

- [ ] **Écrire le mini guide d'accès des équipes clientes.**

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

- [ ] **Publier un lien de l'IGU.**

Livrable : « Un lien d'une interface graphique du produit fonctionnel ». L'interface existe
et fonctionne (`make web`, port 8100, adossée à `make api`), cinq rôles qui agissent
réellement — un sous-processus serveur MCP par profil. **Aucune URL n'est publiée.**

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

- [x] **Écrire les deux motifs dans `mcp_server/matrice.yaml`.** *Fait le 2026-09-07* —
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
par code, champ `hint` portant le recours. **Le code n'implémente rien de tout cela** : il
sert `{status, payload, message}` de `docs/cadrage_dsi.md`, en un seul `TextContent`, sans
`outputSchema` déclaré, sans `isError`, sans `hint`.

Ce n'est pas une régression — le cadrage est le contrat imposé, la suite d'acceptance lit
`result["status"]` et `payload["answer"]` — mais **la validation du dossier de conception est
la porte d'entrée du brief**, et le jury lira une spécification que le code contredit sur
son point le plus visible.

À écrire, en une demi-page : le contrat retenu et pourquoi (le cadrage prime, le test fait
foi) · ce qui est perdu (le mécanisme `structuredContent`/`isError`, que §4 défendait comme
« le chemin correct sans avoir à y penser ») · **ce qui le remplace** — l'absence de la clé
`answer` sur les non-réponses (`PAYLOAD_KEPT`), qui tient la même garantie par liste
blanche, et que la suite vérifie littéralement (`not result["payload"].get("answer")`) · le
sort du champ `hint`, abandonné sans remplaçant.

> **Succès** : la question « pourquoi votre catalogue conçu ne ressemble pas à votre
> serveur ? » a une réponse écrite d'avance, avec ce qu'elle coûte.

## 4. Dérives documentaires — mineures

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
| 11 | **1.1** mini guide d'accès | 3.1 · 3.4 · 3.5 |
| 12 | **5** aligner le dossier ou tenir le tableau d'écarts | 3.5 |
| 13 | **2.4** réserve sur le seuil au protocole | — |
| 14 | **4** + **2.7** en-têtes, docstrings, contournement `literalai` | — |
| 15 | **1.3** URL de l'IGU | un choix d'hébergement, pas du code |

**Si le temps manque**, l'ordre de sacrifice est l'inverse : 15, puis 14, puis 12. Ne pas
sacrifier 1 à 5 — ce sont les seules qui changent ce que le produit **fait** ou ce qu'on peut
**prouver** qu'il fait. Et ne pas sacrifier 11 : c'est un livrable nommé au brief.
