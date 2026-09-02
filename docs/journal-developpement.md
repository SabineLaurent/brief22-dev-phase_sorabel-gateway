# Journal de développement — Sorabel Data Gateway

Tenu au fil de la phase de développement du brief 22. Une entrée par étape livrée :
ce qui a été décidé, ce qui a été écrit, ce qui a été vérifié, et ce qui reste ouvert.
Objectif : pouvoir reprendre le fil — ou justifier un choix en soutenance — sans
relire le code.

Le découpage suit celui du brief : trois chantiers (RAG avancé, Text-to-SQL, serveur
MCP), et trois étapes à l'intérieur du chantier RAG. **Une étape est implémentée,
vérifiée et journalisée avant que la suivante ne commence.**

Documents de référence : `docs/cadrage_dsi.md` (contrat DSI, normatif),
`docs/conception/LIVRABLES_CONCEPTION/` (dossier de conception), `tests/` (suite d'acceptance).

---

## 2026-09-02 — Chantier RAG, étape 1 : ingestion du corpus

> *« Construire l'ingestion du corpus : normalisation PDF/HTML/Markdown, gestion des
> versions et doublons, chunking, métadonnées (référence produit, version, date),
> indexation dans Chroma. »*

### Périmètre tenu

**Dans l'étape** : normalisation des 4 formats, registre des versions, extraction des
métadonnées, embedder commutable, indexation Chroma, CLI, rapport d'ingestion, script
de contrôle.

**Volontairement hors étape** : BM25 (le brief le place à l'étape 3), toute la
recherche, les tools, l'enveloppe MCP, le journal des appels, la matrice, le serveur.
Les dépendances `openai` et `sqlglot` ne sont pas ajoutées — elles servent aux
chantiers suivants.

Conséquence assumée : **aucun test d'acceptance ne passe à ce stade**, ils exigent
tous un serveur MCP. La vérification se fait sur l'index produit
(`scripts/check_index.py`).

### Choix d'inférence retenus pour tout le projet

- **LLM** : Azure AI Foundry en OpenAI-compatible, **API v1** — client OpenAI standard
  avec `base_url=f"{endpoint}/openai/v1"`, le nom de déploiement passe en `model`,
  **pas d'`api_version`**. Vérifié sur la documentation Foundry avant d'être câblé.
- **Embeddings** : commutables. Azure si `AZURE_EMBEDDING_DEPLOYMENT` et
  `AZURE_AI_ENDPOINT` sont renseignés, sinon `intfloat/multilingual-e5-base` en local.
  Aujourd'hui : chemin local (aucun déploiement Azure configuré).
- **Reranker** (étape 3) : les deux implémentations, commutables — cross-encoder local
  `mmarco-mMiniLMv2-L12` et rerank LLM Azure — pour pouvoir les comparer dans le
  rapport de gain E6.
- **Chroma** : le service `docker compose` du scaffold, port 8002.
- **Matrice d'accès** : son *contenu* est arbitré au chantier 3, pas maintenant.

### Arbitrages conception ↔ tests d'acceptance

Relevés en lisant `tests/conftest.py`, qui ne fait **aucun import du code applicatif** :
la suite lance `python -m mcp_server.server` en stdio et lit une enveloppe JSON. Là où
le dossier de conception diverge du contrat DSI ou des tests, **le test fait foi**.
Ces quatre écarts concernent les chantiers suivants — ils sont consignés ici pour ne
pas être redécouverts trop tard.

| Point | Dossier de conception | Ce qu'imposent les tests | Résolution retenue |
|---|---|---|---|
| Enveloppe de réponse | `{code, message, hint, …}`, 12 codes | `{status, payload, message}`, `status` ∈ `ok\|refused\|clarification\|hors_corpus\|error` | `status` = contrat DSI ; les 12 codes vivent dans `payload.code` et dans le journal |
| `get_schema` pour `support` | accordé par `matrice.yaml` | `refused` (`conftest.TOOLS_BY_PROFILE`, T9/T10/T12) | à retirer à `support` |
| `get_document` | `(doc_key, version)` | argument **`doc_id`**, valeur = `hits[0]["doc_id"]` | `get_document(doc_id, version=None)`, `doc_id` acceptant un `edition_id` ou un `doc_key` ; `hits[].doc_id` = `edition_id` |
| `check_stock` | `(ref)` | `{"reference": "REF-8842"}` | paramètre nommé `reference` |

À quoi s'ajoute une contrainte sur les citations (E1) : le test T1 exige `titre`,
`reference` et `date` **non vides sur toutes les sources**, or la question testée porte
sur une procédure SAV, qui n'a pas de référence produit. → `sources[].reference` devra
retomber sur le `doc_key` quand la référence produit n'existe pas.

### Décisions d'ingestion appliquées

Toutes reprises de `docs/conception/LIVRABLES_CONCEPTION/02-modele-chunk.md`, et confirmées sur le
corpus réel avant d'être codées.

- **Pas de chunker.** Une édition = un chunk. Le plus long document indexé fait
  799 caractères, très en deçà de la fenêtre de 512 tokens du modèle.
- **Pas de dédoublonnage strict.** Le risque réel est la ré-ingestion, traité par un
  **`upsert` sur `edition_id`, jamais `add`** — idempotence vérifiée.
- **Les 400 éditions sont indexées**, pas seulement les 350 courantes : `is_current`
  est une métadonnée, le filtre de version s'appliquera **à la requête** (étape 2).
- **Le texte indexé n'est pas le texte du fichier** : le bloc « Accessoires et produits
  associés » cite des références qui ne sont pas le sujet du document et sort de
  l'index ; il reste dans le texte complet, pour l'affichage.
- **Clé omise, jamais vide** : Chroma refuse `None`, et `""` serait une valeur qui se
  compare et se trie. `reference` et `theme` sont absents quand ils n'existent pas.
- **Une seule collection physique**, `doc_type` en métadonnée — c'est sur ce champ que
  la matrice filtrera.
- **Le texte intégral n'est pas stocké dans l'index** : `get_document` le relira depuis
  le chemin porté par la métadonnée `url`.

Deux points de structure du corpus, découverts à l'inspection et qui ont dicté le code :

1. La fiche technique met `Référence produit`, `Version` et `Date` sur des **lignes
   distinctes**, la notice les met **sur une seule ligne**. D'où des expressions
   régulières **par champ, appliquées au texte entier**, et non un découpage ligne à ligne.
2. Les versions se comparent **numériquement** (`1.10` après `1.9`), pas
   lexicographiquement.

### Ce qui a été écrit

| Fichier | Rôle |
|---|---|
| `config.py` | `Settings` (pydantic-settings). Source unique ; l'environnement prime sur `.env` — c'est ce qui permettra au client de fixer son profil au lancement |
| `ingest/normalize.py` | Les 4 lecteurs → dataclass `Edition`. Dérivation `edition_id` / `doc_key`, retrait des liens sortants |
| `ingest/registry.py` | `doc_key → version courante`, pose de `is_current`, contrôle de cohérence nom ↔ contenu, construction des 11 métadonnées |
| `ingest/index.py` | Connexion Chroma, `upsert`, adaptateur `EmbeddingFunction`. Porte le point de greffe documenté de BM25 pour l'étape 3 |
| `ingest/cli.py` | `make ingest` (option `--dry-run`), rapport d'ingestion |
| `retrieval/embedder.py` | Interface `Embedder`, implémentations Azure et locale, préfixes `passage:` / `query:` (la famille e5 est asymétrique), chargement paresseux du modèle |
| `scripts/check_index.py` | `make check-index` — 18 contrôles joués sur l'index réel, pas sur les objets qui l'ont écrit |

Modifications du scaffold : `pyproject.toml` (ajout de `pyyaml` et `types-pyyaml`,
déclaration de `py-modules = ["config"]` — sans elle `scripts/` ne peut pas importer la
configuration) ; `.env.example` (bloc Azure, collection Chroma, correction du modèle
d'embeddings en `-base` conformément à la conception, le scaffold portait `-small`) ;
`Makefile` (cibles `ingest` et `check-index`).

`ruff check .` et `mypy ingest retrieval config.py` : verts.

### Vérifications passées

| Contrôle | Résultat |
|---|---|
| éditions indexées | 400 |
| éditions courantes (`is_current`) | 350 |
| documents distincts (`doc_key`) | 350 |
| répartition `doc_type` | 150 fiche_technique · 80 notice · 90 procedure_sav · 80 note_interne |
| `reference` présente | 230 |
| `theme` présent | 80 (5 thèmes × 16) |
| métadonnées vides ou nulles | 0 |
| valeurs toutes scalaires, identifiants au bon motif | oui |
| `REF-8842` | 3 éditions ; fiche courante = v2.1 |
| documents à deux éditions | 50, tous avec la version la plus haute en courante |
| idempotence (2ᵉ passe) | toujours 400 éditions |

Aucun fichier illisible, aucune incohérence de version dans le corpus fourni : les 400
fichiers sont normalisés et indexés.

### Écarts constatés entre le dossier de conception et le corpus réel

1. **`reference` : 230 éditions, et non 190.** `02-modele-chunk.md` affiche « 190 / 400 ».
   Vérification faite : 190 est le nombre de **documents** porteurs d'une référence
   (120 fiches + 70 notices), affiché sur un dénominateur d'**éditions**. Le compte par
   édition est bien 230 (150 + 80). Le tableau du livrable mélange deux granularités.
2. **`n_caracteres` maximum : 799, et non 923.** Écart attendu : la mesure porte sur le
   texte indexé, après retrait du bloc de liens sortants et des lignes vides. La
   contrainte de fenêtre reste très largement tenue.
3. **Les 7 références du jeu d'éval ont toutes une fiche technique**, y compris
   `REF-5719`, `REF-4581` et `REF-9382` — une exploration préalable avait conclu
   l'inverse, c'est faux, vérifié fichier par fichier.

### Relevé conservé pour la mesure E6

Sonde de recherche **dense seule** sur l'index fraîchement construit, filtrée sur les
éditions courantes :

```
« REF-8842 »
   0.810  note_interne     —         notes/note-2025-04-24-politique-tarifaire-01
   0.806  notice           REF-8842  notices/notice-REF-8842-v1.0
   0.804  fiche_technique  REF-8443  fiches/REF-8443-v1.0
```

La fiche technique de REF-8842 **n'est pas dans le top 3** : la recherche dense rend une
note tarifaire, puis la notice, puis une fiche portant une **référence différente**
(REF-8443, proche typographiquement). C'est exactement le défaut que décrit le brief et
que sanctionne le test d'acceptance sur `search_docs`. Ce relevé est le point de départ
chiffré du rapport `eval/rapport_gain.md` à l'étape 3.

À noter pour le classement : `REF-8842` est aussi cité dans une procédure SAV
(`proc-panne-batterie-electroportatif-04`) et dans une note tarifaire
(`note-2025-04-24-politique-tarifaire-01`) — deux concurrents lexicaux à surveiller.

### Points ouverts

- **`top_k` de `search_docs`** : laissé explicitement ouvert par le dossier de
  conception, à arrêter sur les mesures de l'étape 3.
- **Seuil de refus `hors_corpus`** : à calibrer à l'étape 2 puis à l'étape 3, sur les
  8 questions `hors_corpus` et les 14 `couverte` du jeu d'éval. Réglage le plus délicat
  du chantier — deux tests tirent en sens inverse.
- **CI** : `.github/workflows/quality.yml` fait `uv sync` sans `--extra vector`, ne
  lance pas Docker et n'a pas de secret Azure. Elle restera rouge tant qu'elle n'aura
  pas été mise à jour ou déclarée hors périmètre. À trancher en fin de parcours.
- **Contenu de la matrice d'accès** : `matrice.yaml` ouvre à `support` les notes
  internes (3 thèmes) et la table `ventes` hors marge, là où `docs/cadrage_dsi.md` les
  ferme. Aucun test ne tranche. Arbitrage prévu au chantier 3.

### Correctif — nommage des identifiants

Le code de l'étape 1 avait d'abord été écrit avec des fonctions et des variables en
français (`normaliser`, `construire_embedder`, `reglages`, `chemin`) : la langue de
l'énoncé et du dossier de conception avait été calquée sur le code, à tort. Tous les
identifiants Python ont été renommés en anglais. Docstrings, commentaires et messages
restent en français.

Règle posée à cette occasion, et écrite dans `CLAUDE.md` :
**l'anglais côté Python, le contrat côté données.** Les clés de métadonnées ne sont pas
des identifiants — `titre` et `n_caracteres` sont imposés par le JSON Schema de
`02-modele-chunk.md` et par `tests/acceptance/test_rag.py`, qui lit littéralement
`src["titre"]`. La conversion attribut → clé se fait au seul endroit qui construit les
métadonnées, `build_metadata()` dans `ingest/registry.py`.

Preuve que la distinction a été tenue : `scripts/check_index.py` a été rejoué **sur
l'index d'avant le renommage**, sans réindexation, et ses 18 contrôles passent. Aucune
clé de données n'a bougé.

### Environnement de la session

Python 3.11.15 · torch 2.13.0 · sentence-transformers · chromadb 0.5.23 (docker, port
8002) · uv 0.11.14 · macOS. Première ingestion complète : ~2 min 10 s, téléchargement
du modèle e5-base compris.

### Rejouer cette étape

```bash
make up && make ingest && make check-index
```

---

## 2026-09-02 — Chantier RAG, étape 1 : revue de code et correctifs

Revue de l'étape 1 avant d'ouvrir l'étape 2, sur la branche de travail `rag`. Neuf
constats, tous latents : l'ingestion était juste sur le corpus réel (400/400, 18
contrôles au vert), les défauts se déclenchaient sur d'autres données ou une autre
configuration. Les neuf sont corrigés et vérifiés un par un.

### Le constat qui comptait — une édition écartée en promouvait une périmée

`build_registry()` filtrait les éditions dont la version du nom de fichier contredit
celle du contenu, **puis** désignait l'édition courante sur ce qui restait. Si
`REF-8842-v2.1` annonçait `2.0` dans son corps — exactement le cas que ce contrôle
existe pour attraper —, elle était écartée et `REF-8842-v1.0` devenait la seule
survivante de son `doc_key` : elle héritait de `is_current`. La gateway aurait servi
une édition périmée avec l'assurance d'une édition courante, ce que le contrôle était
censé empêcher.

Décision : **un document dont une édition est écartée n'a plus d'édition courante du
tout.** Aucune ne fait autorité tant que l'incohérence n'est pas corrigée à la source.
Le registre trace ces `doc_key` (`undetermined_doc_keys`), le rapport les nomme, et
l'ingestion sort en échec. Fermer plutôt que deviner : sur un corpus documentaire sous
matrice d'accès, servir la mauvaise version coûte plus cher que ne rien servir.

### Les huit autres

1. **Code de sortie aveugle** (`ingest/cli.py`). Le code ne dépendait que des fichiers
   illisibles : une édition écartée, un `CORPUS_DIR` mal pointé (quatre globs vides,
   « éditions normalisées : 0 ») sortaient en 0. C'est ainsi que le constat ci-dessus
   serait passé inaperçu en intégration continue. Désormais toute anomalie sort en 1,
   avec un motif sur `stderr`.
2. **Aucune réconciliation des suppressions** (`ingest/index.py`). L'`upsert` seul rend
   la ré-ingestion idempotente sur un corpus qui ne fait que croître — pas au-delà. Un
   fichier supprimé, renommé (l'`edition_id` est son chemin : le renommer en crée un
   nouveau et laisse l'ancien orphelin) ou nouvellement écarté survivait dans l'index
   avec son `is_current` de la passe précédente. La passe se termine maintenant par une
   suppression des `edition_id` absents du registre, comptés dans le rapport.
3. **Le type déclaré primait sur le dossier** (`ingest/normalize.py`). Le commentaire
   disait « le dossier fait foi », le code faisait gagner le `<meta name="type">` du
   fichier. Comme la matrice d'accès filtre sur `doc_type`, une balise erronée dans un
   fichier de `sav/` aurait reclassé ce document dans une autre classe d'accès sans un
   mot — un défaut d'autorisation, pas un détail de style. Le dossier fait foi, et une
   divergence lève désormais `NormalizationError`.
4. **Le vérificateur plantait sur les index qu'il doit attraper**
   (`scripts/check_index.py`). `max()` sur une collection vide levait `ValueError` :
   `make check-index` avant `make ingest` rendait une trace de pile au lieu de la ligne
   « éditions indexées 0 (attendu 400) ÉCHEC » qu'il s'apprêtait à écrire. Même classe
   sur les champs obligatoires, déréférencés avant le contrôle de leur présence. Les
   entrées incomplètes sont maintenant mises de côté et rapportées ; les 18 contrôles
   restent les mêmes.
5. **`CHROMA_URL` : schéma perdu, port faux** (`ingest/index.py`). Aucun `ssl=` n'était
   passé (`https://` se connectait en clair), une URL sans port retombait sur 8000 alors
   que tout le projet est en 8002, et `localhost:8002` sans schéma donnait
   `hostname=None` donc `localhost:8000`. Parsing strict : hôte et schéma obligatoires,
   port implicite déduit du schéma, TLS transmis.
6. **Le modèle d'embeddings n'était pas persisté** (`ingest/index.py`). Le commentaire
   « Chroma persiste ce nom avec la collection » est faux pour chromadb 0.5.23 —
   vérifié dans le paquet installé : la fonction d'embeddings reste côté client, son nom
   n'est ni stocké ni comparé. Changer `EMBEDDING_MODEL` pour un autre modèle en 768
   dimensions et ré-ingérer aurait réussi, en mélangeant deux espaces vectoriels dans la
   même collection, sans erreur. L'empreinte du modèle est maintenant écrite dans la
   métadonnée de la collection et vérifiée à l'ouverture.
7. **Tri de versions dupliqué** (`scripts/check_index.py`). Le contrôle réécrivait le
   classement de l'ingestion sans son garde-fou : une version non numérique le faisait
   planter là où l'ingestion l'acceptait, et deux tris divergents auraient pu dénoncer
   un coupable qui n'en était pas un. `version_sort_key()` est devenue publique et est
   importée.
8. **L'adaptateur d'embeddings devinait** (`ingest/index.py`). `ChromaEmbeddingFunction`
   routait tout vers `embed_documents()`, donc préfixait `passage:`. Un appel à
   `collection.query(query_texts=…)` — l'API la plus naturelle de Chroma, et le piège
   tendu à l'étape 2 — aurait encodé chaque question comme un document, dégradant le
   rappel sans rien signaler. L'adaptateur lève désormais une exception : la gateway
   fournit toujours ses vecteurs explicitement.

### Conséquence opérationnelle : `make reindex`

Le contrôle d'empreinte refuse une collection qui n'en porte pas — celle de la première
ingestion, construite avant le contrôle. Plutôt qu'une suppression manuelle,
l'ingestion reçoit `--reset`, exposé en `make reindex`, nommé dans le message d'erreur.
L'index a été reconstruit avec : 400 éditions, 350 documents, 350 courantes, 18
contrôles au vert, chiffres identiques à ceux de la première ingestion.

### Vérifications

Chaque correctif a été vérifié par un scénario de reproduction, pas seulement relu :
registre avec une édition incohérente (le document perd sa courante, le document voisin
garde la sienne), HTML au type contradictoire (refusé), corpus introuvable / vide /
avec écart (code 1 dans les trois cas), sept formes de `CHROMA_URL`, adaptateur appelé
(lève), collection au modèle divergent (refusée), collection non estampillée (refusée
puis reconstruite par `--reset`), disparition d'une édition du corpus (retirée de
l'index à la passe suivante), index vide et entrée incomplète (rapportés, pas de trace
de pile). Puis `make lint`, `make reindex`, `make check-index`, et une ré-ingestion à
vide pour l'idempotence.

### Ce qui n'a pas bougé

Aucune clé de données n'a changé : `titre`, `n_caracteres` et les neuf autres champs
suivent toujours le contrat, et `build_metadata()` reste le seul point de conversion.
Les 18 contrôles de `check_index.py` sont les mêmes, aux mêmes valeurs attendues.

### Écarté après vérification

Quatre pistes examinées et closes : le découpage du frontmatter sur la sous-chaîne
`---` (les cas dégénérés échouent bruyamment), la troncature YAML d'un `version:` non
quoté (les 80 notes le quotent), `_RE_OUTBOUND_LINKS` en mono-ligne (le bloc accessoires
tient sur une ligne dans les PDF, vérifié), et l'écart `n_caracteres` 799 vs 923 (déjà
documenté plus haut).

---

## 2026-09-02 — Confrontation de l'étape 1 au dossier de conception

Le dossier de conception complet est arrivé dans le dépôt (`docs/conception/`) : les cinq
questions de chaque chantier, la description du corpus et de la base, les notes de
transport. L'étape 1 avait été écrite en s'appuyant surtout sur `docs/cadrage_dsi.md`,
`tests/acceptance/` et `02-modele-chunk.md` ; elle est ici confrontée point par point à ce
que `1-rag-avance/` prévoit. Tous les chiffres ci-dessous sont mesurés sur le corpus réel,
pas relus.

### Ce qui est conforme

Vérifié un par un contre Q1, Q2 et le livrable `02-modele-chunk.md` :

- **un document = un chunk**, aucun chunker, la citation E1 ne peut pas être coupée ;
- **400 éditions indexées, 350 courantes**, `is_current` en métadonnée et non en filtre
  d'index — l'option « indexer 350 » écartée en Q1 §5 l'est aussi dans le code ;
- **règle de dérivation des identifiants** : `edition_id` = chemin relatif privé de
  l'extension, `doc_key` = `edition_id` privé du suffixe de version, `doc_key == edition_id`
  pour les notes. Le motif du JSON Schema est celui que `check_index.py` contrôle ;
- **onze champs scalaires**, exactement ceux du schéma, dont les neuf `required` ;
  `additionalProperties: false` tenu — rien d'autre n'est écrit ;
- **la clé absente est omise, jamais vide** (§5 du livrable), pour `reference` et `theme` ;
- **`doc_type` vient du dossier** (Q1 §1) — c'est ce que la revue de code avait corrigé la
  veille sans connaître ce texte, qui le dit explicitement ;
- **`version` ∈ {1.0, 1.1, 2.0, 2.1}** : mesuré, l'`enum` du schéma est exact ;
- **`theme`** : 5 valeurs, 16 notes chacune, dérivé du nom de fichier ;
- **`url`** : chemin relatif depuis la racine du dépôt ;
- **`upsert` déterministe, jamais `add`** (Q1 §3) ;
- **contrôle version du nom / version du contenu** (Q1 §6) — et le durcissement apporté par
  la revue de code va plus loin que le dossier, qui ne dit pas ce que devient le document
  dont une édition est écartée ;
- **tri sur la version, pas sur la date** (Q1 §7) ;
- **préfixes `passage:` / `query:`** de la famille e5, signalés en Q3 §6 comme le piège
  d'implémentation à ne pas découvrir en route ;
- **`.DS_Store` non ingéré** (Q1 §1) : le filtrage par extension l'écarte.

### Divergence réelle — les références-exemples des procédures SAV

Q2 §2 étend le nettoyage du texte indexé au-delà des seuls blocs « Accessoires et produits
associés » : les 90 procédures SAV citent une référence **en exemple**, qui change d'une
édition à l'autre, et le dossier la neutralise aussi. La fonction `sans_liens()` de Q3 §8
est normative sur ce point ; l'ingestion ne retire que les liens sortants.

Mesure sur les 7 références des 8 questions `reference_exacte`, sur les 400 éditions —
« éditions contenant la référence (dont parasites) » :

| réf | annoncé Q2 §2 | règle du dossier, rejouée | index actuel |
|---|---|---|---|
| `REF-8842` | 4 (1) | 4 (1) | **5 (2)** |
| `REF-5313` | 3 (1) | 3 (1) | **5 (3)** |
| `REF-8836` | 3 (0) | 3 (0) | **5 (2)** |
| `REF-5719` | 3 (1) | 3 (1) | 3 (1) |
| `REF-5603` | 3 (0) | 3 (0) | **4 (1)** |
| `REF-4581` | 1 (0) | 1 (0) | 1 (0) |
| `REF-9382` | 3 (1) | 3 (1) | **4 (2)** |

**11 parasites au lieu de 4**, et **90 procédures SAV sur 90** portent encore une référence
produit dans leur texte indexé. La règle du dossier reproduit sa propre table à
l'identique : c'est bien l'ingestion qui s'en écarte, pas la table qui serait fausse.

L'enjeu n'est pas cosmétique : Q3 §2 attribue au nettoyage **+5 en Hit@3** sur les huit
questions par référence exacte, et c'est la mesure que le brief demande de publier (E6).
Laisser ces parasites gonflerait artificiellement l'écart entre les configurations.

**À corriger avant l'étape 2** — le texte indexé doit être celui du dossier avant qu'on
mesure quoi que ce soit dessus.

### Trois écarts documentaires, où c'est le dossier qui se trompe

1. **`reference` : 190 / 400 annoncé, 230 mesuré.** Confirmé une seconde fois : 230
   **éditions** portent une référence (150 fiches + 80 notices), pour 190 **documents**
   distincts. Le livrable affiche un décompte de documents sur un dénominateur d'éditions.
   Q2 §4 porte la même erreur (« 190 éditions sur 400 en portent une, aucune dans `sav/` ni
   `notes/` » — les deux moitiés de la phrase se contredisent). Le code a raison.
2. **`n_caracteres` : les deux exemples du livrable §7 ne suivent pas la même règle.**
   L'exemple SAV (`sav/proc-casse-transport-01-v2.0`, 793) correspond **exactement** au
   texte indexé produit par l'ingestion. L'exemple fiche (`fiches/REF-8842-v2.1`, 633)
   correspond au texte **brut**, liens sortants compris : l'extraction brute fait 631
   caractères, et la ligne « Accessoires » en fait 53. L'ingestion suit la règle écrite au
   §2 du livrable — « après ces deux retraits » —, donc 563. C'est l'exemple qui est
   incohérent avec sa propre règle, pas l'ingestion.
3. **Le maximum de 923 n'est reproductible par aucune méthode.** Avec le nettoyage du
   dossier et son extraction par expression régulière (espaces conservés) : 882. Avec
   l'ingestion (BeautifulSoup + condensation) : 799. Les deux tiennent la contrainte
   `maximum: 923` du schéma, qui reste un majorant valide.

### Divergence de spécification sans effet mesuré

Q1 §1 prescrit de lire le titre d'une procédure SAV dans `<title>` ; l'ingestion le lit dans
`<h1>`. **Vérifié : les deux balises portent la même chaîne sur les 90 fichiers, zéro
écart.** Aucun effet sur la citation E1, mais l'écart est nommé ici plutôt que laissé
implicite. À aligner sur `<title>` en même temps que le nettoyage ci-dessus, le coût étant nul.

### Point bloquant du dossier : levé

Q5 §9 signalait `eval/questions_rag.jsonl` absent du dossier livré, et les 30 questions
transcrites depuis une capture d'écran. **Le fichier est présent dans le dépôt** :
30 questions, 8 `reference_exacte` · 14 `couverte` · 8 `hors_corpus`, 7 références
distinctes pour 8 questions — le dénominateur que Q5 §6.5 met en garde de ne pas confondre.
Nuance : `attendu_type` n'est présent que sur **13** des 14 questions `couverte`. Les
mesures E6 pourront donc être publiées comme résultat, et non plus comme ordre de grandeur.

### Ce que le dossier impose aux étapes suivantes, et qui n'est pas encore fait

Relevé ici pour n'avoir pas à le redécouvrir :

- **le filtre `is_current` s'applique dans chaque liste avant sa troncature**, jamais après
  la fusion RRF (Q1 §5) — côté Chroma, `where={"is_current": True}` dans la requête ;
- **la citation est construite en Python**, jamais rédigée par le modèle, et porte
  `titre + version + date`, plus `reference` quand elle existe (Q4 §2). C'est un écart
  assumé avec la lettre d'E1, motivé par 52 titres pour 150 fiches ;
- **deux barrières de refus, deux codes** : `hors_corpus` (seuil) et `contexte_insuffisant`
  (garde de suffisance), aucun des deux n'étant une erreur au sens du journal (Q4 §7) ;
- **le seuil de refus ne peut pas porter sur un score lexical** : les plages BM25 des
  questions couvertes et hors corpus se chevauchent (Q4 §3). Il porte sur le score du
  reranker — qui n'existe qu'à l'étape 3. **Pour l'étape 2, Q5 §4 prévoit explicitement le
  critère de la configuration A : la distance cosinus du premier résultat**, bornée donc
  comparable. C'est ce qu'il faut implémenter, en le nommant comme tel ;
- **huit questions hors corpus supplémentaires**, écrites par nous, servent à calibrer ; les
  huit du jeu servent à mesurer (Q4 §6). À versionner à côté du jeu fourni, jamais mélangées ;
- **règle de départage fiche / notice**, exprimée en rangs et non en scores, `FENETRE = 3`,
  publiée avec et sans (Q3 §5) ;
- **trois configurations A / B / C** et non deux, mesure publiée sur le profil `commercial`
  (Q5 §2 et §5).

### Conclusion

L'étape 1 est conforme au dossier sur tout ce qui touche au modèle de données et au
versionnement. Elle s'en écarte sur **un** point de fond — le périmètre du nettoyage du
texte indexé — et sur un point de forme sans effet. Trois chiffres du dossier sont, eux, à
corriger. Rien de tout cela ne remet en cause l'index existant au-delà d'une réindexation.

---

## 2026-09-02 — Protocole de mesure arrêté avant l'étape 2

Décision prise avant d'écrire la recherche, pour que le protocole ne se façonne pas au fil
de l'implémentation. Le détail est dans **`eval/protocole-mesure.md`** ; ne sont consignées
ici que les décisions et leur motif.

**Un « RAG simple » construit de bout en bout est écarté.** L'intention — disposer d'un point
de comparaison — est juste et nécessaire, mais un pipeline naïf séparé produirait un seul
chiffre indécomposable, mélangeant le nettoyage du texte (+5 en Hit@3 à lui seul, Q3 §2), le
filtre de version (dénominateur 350 au lieu de 400) et la stratégie de recherche — la seule
que le brief demande de mesurer. C'est exactement le défaut que Q5 §2 reproche au protocole
à deux configurations.

**À la place : quatre drapeaux orthogonaux et deux axes.** `--text clean|raw` à l'ingestion ;
`--config A|B|C`, `--version-filter on|off`, `--tiebreak on|off` à la recherche. Axe 1 = la
recherche à ingestion constante (c'est E6) ; axe 2 = l'ingestion à recherche constante (que
le dossier ne mesure pas). Le « RAG simple » devient un **coin de l'espace** — `raw`, `A`,
`off`, `off` — publiable comme ligne parlante, jamais à la place de la décomposition.

**Le dédoublonnage n'est pas un axe.** Zéro doublon d'octets sur 400 fichiers (Q1 §3) : une
étape qui ne se déclenche jamais. Le doublon réel est l'édition multiple — 50 documents à
0,965 de similarité — et c'est `--version-filter` qui le traite.

**Pas d'évaluateur de RAG** (RAGAS, DeepEval, LLM-juge). Quatre raisons, dont deux
décisives : le jeu n'a pas de réponses de référence, donc il faudrait les écrire puis se
noter dessus ; et ces métriques sont jugées par un LLM, donc non déterministes, sur un
sous-ensemble de huit questions. Surtout, l'architecture a retiré le besoin : la citation
étant construite en Python et jamais rédigée par le modèle (Q4 §1), il n'y a pas de fidélité
à vérifier après coup. À écrire comme un choix argumenté dans le rapport, pas comme un oubli.

**Outillage.** Le harnais est `scripts/eval_rag.py`, lancé par chemin comme
`scripts/check_index.py`, et il attaque la recherche **sans passer par le serveur MCP** —
c'est ce qui permet de mesurer E6 dès l'étape 2, alors que les tests d'acceptance attendent
le chantier 3. **Une cible Make par mesure publiée** — `mesure-dense`,
`mesure-lexical`, `mesure-hybride`, `mesure-sans-nettoyage`, `mesure-sans-versions`,
`mesure-rag-simple`, plus `mesure` qui rejoue les sept, `calibrer` et `ingest-brut`. Le
premier jet de ce protocole écartait cette solution au motif que les quatre drapeaux font
24 combinaisons : l'argument était faux, on n'en publie que **sept**, et à ce nombre-là la
cible nommée est meilleure que la chaîne de drapeaux — elle est rejouable telle quelle, elle
suit la convention du dépôt, et elle tranche du même coup la langue du vocabulaire publié
(français, comme les autres cibles). Les drapeaux restent sous les cibles pour
l'exploration ; les CSV portent le nom de leur cible.

**Deux fichiers de questions, jamais mélangés** : `questions_rag.jsonl` mesure,
`questions_calibration.jsonl` — huit questions hors corpus à écrire — calibre les seuils
(Q4 §6).

### Conséquence sur l'étape 2

**La recherche prend sa collection et sa stratégie en paramètres, jamais en constantes.**
C'est la seule contrainte d'architecture qu'impose ce protocole. Et le seuil de refus de
l'étape 2 porte sur la **distance cosinus** du premier résultat — le critère que Q5 §4
prévoit pour la configuration A, faute de reranker avant l'étape 3.

---

## 2026-09-02 — Dédoublonnage par proximité : impossible, mesuré

Question posée : puisque les procédures SAV partagent leur contenu, les fusionner et garder
les références-exemples dans un champ `ref_examples` améliorerait-il le RAG ?

**Le dossier avait déjà tranché l'essentiel, et cette entrée ne le refait pas.** Sont déjà
établis, et à citer plutôt qu'à re-démontrer :

| Fait | Où |
|---|---|
| les 90 procédures sont **génériques**, leur référence est un exemple qui change entre deux versions | `description-corpus.md` §5 |
| 86 % de leur texte est une trame partagée ; le dense y forme « un peloton très serré », car « ce qui distingue deux documents est ce qu'un embedding pondère le moins » | Q3 §1 |
| deux éditions à 0,97 de similarité prennent **deux places du top-5** — d'où le filtre de version | Q1 §4 et §5 |
| **« pas de liste de références associées »** : Chroma refuse les champs non scalaires, et `additionalProperties: false` interdit un douzième champ | `02-modele-chunk.md` §8 |
| zéro doublon d'octets sur les 400 fichiers | Q1 §3 |

Autrement dit, `ref_examples` est nommé et clos par le contrat, et l'avantage du lexical sur
le dense face à une trame partagée est déjà argumenté. Rien à rouvrir.

### La seule mesure qui manquait

Q1 §4 mesure la similarité **entre les deux versions d'un même document** — 0,965 minimum,
0,977 médiane sur 50 paires. **Personne n'avait mesuré la similarité entre documents
différents.** Faite ici, sur les 3 160 paires de procédures SAV courantes :

| | similarité |
|---|---|
| entre procédures **différentes** — 3 160 paires | 0,932 – **0,996**, médiane 0,952 |
| entre v1.0 et v2.0 du **même** document — 10 paires | 0,983 – 0,986 |

**Les deux bandes se recouvrent entièrement** : deux procédures différentes peuvent être
plus semblables que deux versions du même document. Aucun seuil de proximité ne les sépare —
réglé sous 0,95 il efface 79 procédures sur 80, au-dessus il ne dédoublonne rien.

C'est la même figure que le seuil BM25 impossible de Q4 §3, et c'est ce qui fait de
`doc_key` + `version` la **seule** séparation valide entre deux éditions. Reporté dans
`eval/protocole-mesure.md`, où il ferme l'axe du dédoublonnage.

Vérification de forme au passage : deux procédures différentes ne diffèrent que par leur
titre, leur date et les deux occurrences de leur référence-exemple — « Conditions »,
« Étapes » et « Cas hors périmètre » sont identiques au caractère près sur les 80.

### Deux conséquences à retenir

**La fusion est écartée** : le corps est identique mais le titre ne l'est pas, et c'est tout
le contenu — « Colis reçu endommagé » et « Livraison incomplète ou erronée » sont deux
situations distinctes. Fusionner supprimerait 79 réponses et ferait citer à E1 un titre qui
ne correspond pas à la question.

**Le titre est le seul discriminant des 80 procédures**, et le nettoyage SAV rendra leur
corps identique à 100 %. Les 6 questions `couverte` qui attendent une `procedure_sav`
trouveront donc le bon *type* trivialement et la bonne *procédure* par le seul titre — à
déclarer avant de lire ces chiffres, sous peine de prendre une propriété du corpus pour un
gain de recherche. Ajouté aux limites du protocole.

---

## 2026-09-02 — Chantier RAG, étape 2 : recherche dense, citations, refus

> *« Recherche dense, citations, refus hors corpus. »*

### Périmètre tenu

`retrieval/search.py`, `scripts/calibrate_threshold.py`, `eval/questions_calibration.jsonl`,
plus le correctif de nettoyage de l'étape 1. Le lexical, le RRF et le rerank restent à
l'étape 3 ; la génération de la réponse et la garde de suffisance (Q4 §5) arrivent avec le
tool `answer_question`, au chantier MCP — elles supposent un appel au modèle.

**Tout est paramétré, rien n'est câblé** : collection et profil de texte, étage de
recherche, filtre de version, règle de départage, seuil de refus. C'est la contrainte que
pose `eval/protocole-mesure.md`, et elle se prend maintenant ou jamais : Q5 §6 exige de
rejouer la configuration A **après** la C.

### Le correctif de nettoyage, d'abord

Les 90 procédures SAV citaient encore une référence en exemple dans le texte indexé. Après
correctif, la table de Q2 §2 est reproduite **exactement** sur les sept références du jeu
d'évaluation — 4 parasites au lieu de 11, et 0 procédure sur 90 porte encore une `REF-`.
Le titre des procédures se lit désormais dans `<title>`, comme le prescrit Q1 §1. Index
reconstruit, 18 contrôles au vert, `n_caracteres` maximum à 783.

### La mesure « avant » — configuration A

Sur les 8 questions `reference_exacte`, dense seul, index nettoyé, filtre de version actif :

| critère | dense seul | BM25 seul (dossier, Q3 §2) |
|---|---|---|
| Hit@1 — référence attendue | **2 / 8** | 8 / 8 |
| Hit@1 — fiche technique en tête | **2 / 8** | 2 / 8 |

Les deux succès sont RAG-02 (« fiche technique REF-8842 », où les mots aident) et RAG-07.
Les six autres remontent une note interne ou une fiche portant une **autre** référence —
`REF-5313` rend `fiches/REF-4316`, `REF-8836` rend `fiches/REF-5849`. C'est exactement
l'effondrement que décrit Q3 §1 : le vecteur d'une référence nue encode « ceci est une
référence », pas *laquelle*. Le point de départ chiffré d'E6 est posé.

La règle de départage ne se déclenche pas sur ces questions : elle exige que le premier
résultat porte une référence, or il n'en porte pas. C'est son comportement voulu — elle
départage, elle ne repêche pas.

### Le seuil de refus : le dossier supposait, la mesure corrige

Q5 §4 retient pour la configuration A la distance cosinus, « bornée, comparable entre
requêtes ». **Bornée ne veut pas dire séparable.** Mesuré sur le jeu de calibration :

| population | plage du score du premier résultat |
|---|---|
| couverte (6) | 0,820 – 0,882 |
| hors corpus (8) | 0,793 – 0,831 |

Les deux se chevauchent — la famille e5 comprime ses similarités dans une bande étroite.
C'est la même figure que les plages BM25 de Q4 §3, que le dossier croyait propre au lexical.

**Seuil retenu : 0,831**, choisi sur le jeu de calibration seul. Rejoué sur le jeu de
mesure, qui n'a servi à rien d'autre :

| | résultat |
|---|---|
| refus corrects | **7 / 8** |
| réponses tenues | **13 / 14** |

Les deux écarts sont nommés d'avance par le dossier, et aucun n'est une régression :

* le refus manqué est **« résilier le contrat d'électricité de l'entrepôt de Lyon »**
  (0,845) — la question que Q4 §4 mesure déjà comme la plus haute des huit en BM25 (5,3).
  Elle trompe le dense et le lexical de la même façon ;
* le refus à tort est **RAG-19**, « quel différentiel pour un circuit avec plaque de
  cuisson » — que `description-corpus.md` §7.2 signale comme portant sur un sujet **absent
  du corpus**. Refuser y est sémantiquement juste ; c'est le jeu qui l'étiquette `couverte`.
  Q5 §3 prévoit ce cas : « une configuration qui les rate n'a pas régressé ».

### L'arbitrage de citation : le test contre le dossier

Q4 §2 fait porter à la citation « `reference` quand elle existe », 210 éditions n'en ayant
pas. **Le test d'acceptance dit autre chose** : il interroge sur une procédure de retour
sous garantie — donc une procédure SAV, sans référence — puis exige
`src["reference"].strip()` non vide sur *chaque* source. Une clé absente échoue.

`CLAUDE.md` tranche : le test fait foi. Conduite retenue, qui ne sacrifie ni l'un ni
l'autre : **la métadonnée reste fidèle au contrat de données** — clé omise, parce que le
JSON Schema, les contrôles d'index et le filtrage de la matrice en dépendent — et **c'est la
citation qui garantit une chaîne non vide**, en retombant sur `doc_key`. Une procédure est
donc citée « titre + `sav/proc-retour-produit-defectueux-07` + version + date », ce qui
l'identifie exactement.

### Le jeu de calibration

`eval/questions_calibration.jsonl` : 8 questions hors corpus écrites pour ce projet, plus 6
couvertes — il faut les deux populations pour placer un seuil. Vocabulaire vérifié absent du
corpus mot par mot. Trois visent le point faible de Q4 §4 : deux portent le mot
« politique », une mêle « panne », vocabulaire des 90 procédures, à la vie interne. Ce
fichier **ne se mélange jamais** à `questions_rag.jsonl` : calibrer et mesurer sur les mêmes
questions ferait constater un réglage au lieu de mesurer une capacité (Q4 §6).

### Points ouverts

- **`top_k` = 5**, imposé par la métrique Recall@5 ; le dossier le laisse ouvert, à arrêter
  sur les mesures de l'étape 3 ;
- **le seuil est réglé sur 14 questions.** Limite méthodologique, déjà nommée par Q4 §6 et
  non corrigeable à cette échelle ;
- **la garde de suffisance** (barrière 2) et la génération de la réponse arrivent avec
  `answer_question`. Le refus `contexte_insuffisant` n'existe donc pas encore.

### Rejouer cette étape

```bash
make up && make reindex && make check-index && make calibrer
```

---

## 2026-09-02 — Chantier RAG, étape 3 : hybride BM25 + RRF + rerank, mesure du gain E6

> *« BM25 + dense + RRF + rerank, mesure du gain de la recherche avancée sur la recherche
> simple (E6). »*

### Périmètre tenu

`retrieval/lexical.py` (BM25), `retrieval/reranker.py` (cross-encoder / LLM Azure,
commutables), les stratégies `lexical` et `hybrid` de `retrieval/search.py`, la
construction de l'index BM25 à l'ingestion (`ingest/index.py`), `scripts/calibrate_threshold.py
--config C`, `scripts/eval_rag.py` (nouveau — le harnais de mesure), sept cibles Make.
Rien de tout cela n'était à inventer sur le fond : les formules (RRF, départage), les
modèles et les seuils sont ceux de `Q3.md`, `Q4.md`, `Q5.md` et `eval/protocole-mesure.md`.
Seules les valeurs d'implémentation que le dossier laisse ouvertes ont été tranchées ici,
et le sont explicitement ci-dessous.

**Hors périmètre, comme prévu** : `answer_question`, la garde de suffisance
(`contexte_insuffisant`), le serveur MCP — ils supposent un appel au modèle et arrivent
au chantier 3.

### Décisions d'implémentation prises ici

Le dossier fixe la formule et les modèles ; il ne fixe pas ces valeurs-là.

- **`rerank_candidates = 20`** : profondeur des deux listes (BM25, dense) avant fusion RRF,
  et nombre de candidats effectivement notés par le reranker. Choisi sans balayage formel —
  assez large pour laisser RRF un vrai choix (`top_k` vaut 5), assez étroit pour qu'un
  cross-encoder CPU reste rapide sur 30 questions.
- **Score du reranker borné par sigmoïde.** `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
  rend des logits, pas un score natif dans `[0, 1]` : `Q4` §3 exige une échelle bornée pour
  qu'un seuil soit une opération sensée, la sigmoïde le garantit sans dépendre de la plage
  de sortie du modèle.
- **BM25 : `rank-bm25` (`BM25Okapi`, `k1=1.5`, `b=0.75`)**, les mêmes paramètres que le
  script de référence de `Q3.md` §8, plutôt qu'une réécriture — la dépendance était déjà
  posée en prévision de cette étape.
- **L'index BM25 est reconstruit en entier à chaque ingestion**, sur les 400 éditions comme
  le dense, et sérialisé à côté de lui (`data/bm25/<collection>.pkl`, gitignoré comme
  `data/sorabel.db`). BM25 n'a pas de mise à jour incrémentale sensée : l'IDF de chaque
  terme dépend de tout le corpus.
- **`--tiebreak` n'est pas un drapeau du harnais de mesure**, conformément à
  `eval/protocole-mesure.md` §10 : chaque question est jouée une seule fois par le pipeline
  (`tiebreak=False` côté `search()`), puis `apply_tiebreak()` — pure — est rejouée localement
  pour produire la seconde colonne. Un rerank ne coûte donc jamais deux fois.
- **Schéma du CSV** : `id, type, critere, rang_avec_departage, rang_sans_departage, score,
  refus, code`. Les questions `reference_exacte` écrivent **deux lignes** (`critere`
  = `reference` puis `fiche_technique`) pour porter les deux critères de Hit@1 exigés par
  `Q5` §3 sans les confondre dans une seule colonne. Le refus est calculé **pour toute
  question**, pas seulement `hors_corpus` : une question `couverte` refusée à tort doit
  pouvoir se lire dans le CSV (c'est le cas de RAG-19, voir plus bas).
- **Rerank LLM Azure** : un seul appel `chat.completions.create` par requête, les candidats
  numérotés dans le prompt, sortie JSON `{"scores": [{"index", "score"}, …]}`. Écrit sur le
  même modèle que `AzureEmbedder` (import paresseux d'`openai`, même message d'erreur) mais
  **non exercé contre un déploiement réel** : aucun déploiement Azure n'est configuré dans
  cette session, comme pour les embeddings depuis l'étape 1.

### Calibration

`make calibrer` (config A) reproduit exactement le seuil de l'étape 2 : **0,8308**, 8/8
refus corrects, 5/6 réponses tenues sur les 6 `couverte` du jeu de calibration — l'index
n'a pas changé, la configuration A non plus.

`make calibrer-hybride` (config C), en revanche, change la nature du problème : le score du
reranker **sépare proprement** les deux populations, ce que la distance cosinus de la
configuration A ne faisait qu'approximativement (étape 2) :

| population | plage du score reranker |
|---|---|
| couverte (6) | 0,053 – 0,993 |
| hors_corpus (8) | 0,000 – 0,016 |

**Seuil retenu : 0,0530**, séparable (`min(couverte) > max(hors_corpus)`), 8/8 refus
corrects et 6/6 réponses tenues sur le jeu de calibration. Les deux seuils sont écrits en
dur dans `config.py` — même convention que `refusal_threshold` depuis l'étape 2, il n'existe
pas de `.env` local dans cette session.

### La mesure E6

Profil `commercial`, texte nettoyé, filtre de version actif, départage appliqué dans les
trois configurations (`eval/protocole-mesure.md` §1). Table complète dans
`eval/rapport_gain.md`, générée par `make mesure` :

| sous-ensemble | métrique | A dense | B lexical | C hybride |
|---|---|---:|---:|---:|
| reference_exacte | Hit@1 (référence) | 2/8 | 3/8 | **8/8** |
| reference_exacte | Hit@1 (fiche technique) | 2/8 | 3/8 | **8/8** |
| reference_exacte | MRR | 0,375 | 0,688 | **1,000** |
| couverte | Recall@5 (`attendu_type`, n=13) | 11/13 | 11/13 | 12/13 |
| hors_corpus | refus corrects | 7/8 | n/a (`Q4` §3) | 5/8 |

**La démonstration tient** : l'hybride résout à 8/8 sur les deux critères de Hit@1 ce que le
dense seul résout à 2/8 — exactement le trou que `Q3.md` décrit — et le fait *mieux* que
prévu par le dossier, qui n'attendait le Hit@1 fiche à 8/8 qu'au prix d'une règle de
départage qui se déclenche ; ici RRF et le reranker corrigent déjà la moitié des cas avant
même le départage (voir plus bas). La ligne « RAG simple » (A, texte brut, filtre et
départage désactivés) confirme l'écart : **1/8** contre **8/8** pour le RAG avancé.

### Écart mesuré, chassé jusqu'à sa cause — B lexical à 3/8, pas 8/8

`Q3.md` §2 annonce le lexical seul à 8/8 en Hit@1 référence. La mesure en rend **3/8**.
Chassé, pas ignoré : rejouer le script de référence de `Q3.md` §8 caractère pour caractère
confirme ses propres chiffres (`notice 6,10 · note 5,47 · fiche 4,49` sur « REF-8842 ») —
donc l'écart n'est pas une erreur de formule BM25 ni de paramètres (`rank-bm25` en
`k1=1,5, b=0,75` est le même calcul).

**La cause : la longueur du document.** Le script de `Q3.md` tokenize le texte brut du
fichier, frontmatter YAML compris, pour les notes. L'ingestion de l'étape 1 — décision prise
avant cette étape, pour toutes les recherches, dense comme lexicale — retire le frontmatter
de `indexed_text` : c'est une métadonnée structurée, pas de la prose à indexer. Conséquence
mesurée sur la note `politique-tarifaire-01`, seule à changer entre les deux méthodes :

| | note (tokens) | notice (tokens) | note devant la notice ? |
|---|---:|---:|---|
| script `Q3.md` (frontmatter inclus) | 49 | 94 | non — 5,47 < 6,10 |
| index de la gateway (frontmatter exclu) | 33 | 94 | **oui** — 5,88 > 5,77 |

BM25 normalise par la longueur du document (`b = 0,75`) : une note plus courte, à occurrence
égale du terme cherché, obtient un score plus haut. Retirer 16 tokens de frontmatter suffit à
inverser l'ordre note/notice sur une course déjà serrée. Le même mécanisme joue sur 5 des 8
questions `reference_exacte` : une note interne, sans métadonnée `reference`, prend le rang 1
à la place de la notice ou de la fiche.

**Ce n'est pas un défaut du code.** L'exclusion du frontmatter est une décision de l'étape 1,
déjà appliquée au dense depuis le début — BM25 est seulement le premier étage à exposer sa
sensibilité à la longueur, que le dense (un vecteur par document, sans normalisation
croisée) ne partage pas. Revenir dessus casserait la cohérence « un seul texte indexé »
qui tient tout le pipeline depuis `Q2.md`, pour un score BM25 « témoin » dont le rôle — `Q5`
§2 le dit — n'est pas d'être la mesure publiée mais la comparaison qui empêche l'hybride de
s'attribuer un gain qui ne serait pas le sien. La règle de départage confirme le diagnostic
sans le résoudre : elle sait échanger une notice contre une fiche (Hit@1 fiche passe de 1/8 à
3/8 avec départage), mais une note interne n'a pas de `reference` — `apply_tiebreak()`
s'arrête à sa première condition (`if not top.reference: return hits`) et ne la déplace
jamais. C'est voulu : la règle départage, elle ne classe pas.

### Le refus en configuration C : 5/8, trois cas distincts

- **RAG-19** (« différentiel pour une plaque de cuisson ») est refusé — score 0,0049, très
  en dessous du seuil. C'est correct : `description-corpus.md` §7.2 signale ce sujet comme
  absent du corpus, l'étiquette `couverte` du jeu est ce qui est en tension, pas la réponse
  du pipeline (`Q5` §3 : « une configuration qui les rate n'a pas régressé »).
- **RAG-23** (« politique de télétravail », 0,0868) et **RAG-29** (« résilier le contrat
  d'électricité de l'entrepôt de Lyon », 0,5175) passent le seuil à tort. RAG-29 est déjà
  identifié à l'étape 2 comme le piège le plus difficile du jeu, en dense comme en BM25 — il
  reste un piège dans l'hybride.
- **RAG-24** (« chiffre d'affaires de Sorabel en 2025 », 0,8422) est un piège **nouveau,
  découvert ici** : le cross-encoder attribue un score élevé à une fiche technique de
  goulotte sans rapport, dont la métadonnée porte `Date : 2025-09-02`. Le modèle semble
  accrocher sur la présence du seul terme « 2025 » commun aux deux textes — un faux ami
  lexical que ni le jeu de calibration ni la mesure de l'étape 2 ne pouvaient exposer, aucune
  de leurs questions ne portant une année. Limite méthodologique déjà nommée par `Q4` §6 :
  un seuil réglé sur huit questions ne peut pas anticiper tous les pièges d'un corpus de 400
  documents.

### Axe 2 — nettoyage et versionnement, effet nul sur l'hybride

Chiffre notable, à l'opposé de ce que `Q3.md` §2 mesure sur BM25 seul (+5 en Hit@3) :
`mesure-sans-nettoyage` (texte brut) et `mesure-sans-versions` (filtre désactivé) rendent
**exactement** les mêmes chiffres que `mesure-hybride` — 8/8, 8/8, 12/13, 5/8. Le RRF et le
reranker absorbent le bruit que le nettoyage retirait et les doublons de version que le
filtre écartait : sur ce corpus et à cette profondeur de candidats (`rerank_candidates=20`),
les décisions d'ingestion mesurées à l'axe 2 ne changent plus le résultat final une fois le
reranker en bout de chaîne. Ne pas généraliser : la mesure porte sur 8 questions
`reference_exacte`, et le nettoyage reste requis en amont — c'est lui qui évite qu'un
candidat parasite occupe une des 20 places avant la fusion.

### Ce qui a été écrit

| Fichier | Rôle |
|---|---|
| `retrieval/lexical.py` | Tokenizer (regex de `Q3.md` §8), `LexicalIndex` (BM25Okapi + filtre de version avant troncature), sérialisation |
| `retrieval/reranker.py` | `Reranker` (protocole), `LocalReranker` (cross-encoder + sigmoïde), `AzureReranker` (LLM-juge), sélecteur |
| `ingest/index.py` | Construction de l'index BM25 en fin d'`index_editions()` — remplace le commentaire « point de greffe » |
| `retrieval/search.py` | `_reciprocal_rank_fusion`, `_lexical_search`, `_hybrid_search`, `_fetch` (un aller-retour Chroma par lot d'identifiants) |
| `scripts/calibrate_threshold.py` | `--config {A,C}` |
| `scripts/eval_rag.py` | Nouveau — mode run (une configuration, un CSV) et mode `--report` (les sept CSV → `eval/rapport_gain.md`) |
| `Makefile` | `calibrer-hybride`, les sept cibles de mesure, `mesure` |
| `config.py`, `.env.example` | `rerank_candidates`, `reranker_model`, `azure_rerank_deployment`, `rerank_threshold` |
| `.gitignore` | `data/bm25/` — dérivé de l'ingestion, comme `data/sorabel.db` |

`ruff check .` et `mypy ingest retrieval sql mcp_server` : verts.

### Vérifications passées

`make reindex`, `make ingest-brut` : 400 éditions, 350 courantes, index BM25 écrit dans les
deux collections. `make check-index` : 18 contrôles toujours au vert, inchangés. `make
calibrer` puis `make calibrer-hybride` : seuils ci-dessus. Les sept cibles de mesure jouées
individuellement puis `make mesure --report` : `eval/rapport_gain.md` généré, chiffres
recoupés à la main contre les CSV et contre les ordres de grandeur de `Q3.md`/`Q4.md`/`Q5.md`
pour la configuration A (identiques à l'étape 2 — aucune régression).

### Environnement de la session

`uv sync --extra vector` a dû être rejoué (`sentence-transformers`/`torch` absents au début
de cette session). Une ingestion `--text raw` a une fois planté **après** avoir écrit son
rapport et son index (« `recursive_mutex lock failed` », une exception native à la fermeture
de l'interpréteur) ; rejouée, exit 0. Le conteneur Chroma a une fois été recréé par `docker
compose up -d` juste après un démarrage à froid de Docker Desktop ; les données ont survécu
(volume monté sur `.docker-data/chroma`), vérifié par comptage (400/400 dans les deux
collections). Aucun des deux n'a affecté un résultat mesuré — consignés ici pour ne pas être
repris pour un défaut du code s'ils se reproduisent.

### Points ouverts

- **`answer_question` et la garde de suffisance** (`contexte_insuffisant`) : chantier 3,
  inchangé.
- **Le rerank LLM Azure n'est pas exercé** contre un déploiement réel — même situation que
  `AzureEmbedder` depuis l'étape 1. Le prompt et le format de sortie sont un choix
  d'implémentation, à revoir à la première exécution réelle.
- **`rerank_candidates = 20`** n'a pas fait l'objet d'un balayage — une valeur plus grande
  pourrait changer le taux de refus (RAG-24 en particulier) sans changer les Hit@1, déjà à
  8/8.
- **Le seuil de la configuration C reste réglé sur 8 questions hors corpus**, comme celui de
  la configuration A à l'étape 2 — limite méthodologique nommée par `Q4` §6, RAG-24 en est
  une illustration mesurée, pas une raison de recalibrer sur le jeu de mesure.

### Rejouer cette étape

```bash
make up && make reindex && make ingest-brut && make check-index
make calibrer && make calibrer-hybride
make mesure
```

---

## 2026-09-02 — Piste non retenue : tester avec/sans calibration

> Note en marge, prise en construisant le schéma pédagogique du protocole de mesure — pas
> une étape livrée, un point ouvert à évaluer plus tard.

Question posée : ne serait-il pas intéressant de mesurer l'effet du calibrage lui-même —
seuil calibré vs seuil par défaut/non ajusté — dans le même esprit que le témoin BM25 qui
isole la part imputable à l'hybridation plutôt qu'à la seule recherche lexicale ?

**Pas retenu comme axe du protocole tel qu'écrit.** La calibration n'est pas un des quatre
drapeaux de `eval/protocole-mesure.md` ; c'est une entrée fixe, appliquée identiquement à
toutes les cibles mesurées. En faire un axe obligerait à rejouer les sept cibles une seconde
fois pour une question assez orthogonale à E6 (le gain de la recherche), que le protocole
visait justement à isoler seul.

Piste plus légère, si creusée un jour : une mesure ciblée « seuil calibré vs seuil par
défaut », limitée au sous-ensemble `hors_corpus` (8 questions), sans toucher aux cibles
existantes ni au reste du protocole.

**Outils de calibration envisagés, hors du script maison** (`scripts/calibrate_threshold.py`,
balayage manuel sur 14 questions) :

- `sklearn.metrics.roc_curve` / `precision_recall_curve` — seuil optimal choisi
  systématiquement (point de Youden, F-bêta maximal) plutôt qu'à l'œil ;
- `sklearn.calibration` (Platt scaling, isotonic regression) — suppose un score déjà
  probabiliste en entrée, ce qui n'est pas le cas ici (cosinus brut, non borné/séparable
  comme déjà constaté plus haut pour BM25 et le seuil dense) ;
- **conformal prediction** (ex. bibliothèque `MAPIE`) — donnerait un seuil avec une garantie
  statistique de taux d'erreur plutôt qu'un point choisi sur un petit échantillon ; piste la
  plus pertinente sur le principe pour une décision de refus, mais réclame plus de données de
  calibration que les 14 questions actuelles pour être fiable ;
- **RAGAS** — écarté : c'est un cadre d'évaluation de la qualité d'une réponse déjà générée
  (fidélité, pertinence, precision/recall du contexte), via LLM-juge — pas un outil de choix
  de seuil. Son générateur de jeux de test synthétiques pourrait en revanche aider à étoffer
  le jeu de calibration au-delà des 14 questions écrites à la main.

---

## 2026-09-02 — Piste exécutée : impact de la calibration, seuil calibré vs seuil naïf

Suite de la note ci-dessus. La piste « plus légère » qu'elle retenait — seuil calibré contre
seuil par défaut, limitée au sous-ensemble `hors_corpus`, sans toucher aux cibles existantes
ni au protocole — est exécutée ici.

**Méthode.** Aucune ré-exécution de `search()` n'est nécessaire : `scripts/eval_rag.py` écrit
déjà, pour les 30 questions, une colonne `score` calculée **indépendamment du seuil** dans
`eval/resultats/mesure-dense.csv` (config A) et `eval/resultats/mesure-hybride.csv`
(config C) — la décision de refus y est recalculée après coup. La comparaison relit ces deux
CSV déjà publiés et réapplique la règle `refusé si score < seuil` pour deux seuils : le seuil
calibré en dur dans `config.py` (`refusal_threshold=0,8308`, `rerank_threshold=0,0530`), et un
seuil « naïf » choisi ici.

**Seuil naïf retenu : 0,5.** Aucune valeur non calibrée n'existe dans le dépôt — 0,5 est le
choix d'un score borné `[0, 1]` sans aucune mesure, exactement le sens que porte la sigmoïde
du score du reranker (`retrieval/reranker.py`), pensée comme une probabilité. Pour le score
dense (cosinus), 0,5 est un choix moins naturel mais porte la même absence de mesure — c'est
précisément le point : montrer ce qui se passe si l'étape de calibration est sautée.

**Résultat**, recalculé sur les CSV déjà publiés :

| config | seuil | refus_corrects (/8 hors_corpus) | réponses_tenues (/14 couverte) |
|---|---|---:|---:|
| A — dense | calibré 0,8308 | 7/8 | 12/14 |
| A — dense | naïf 0,5 | **0/8** | 14/14 |
| C — hybride | calibré 0,0530 | 5/8 | 13/14 |
| C — hybride | naïf 0,5 | 6/8 | **9/14** |

**Lecture.** En config A, le seuil naïf rend la barrière **totalement inopérante** (0/8) : les
scores cosinus vivent tous dans une bande étroite (0,7976 à 0,8962), hors_corpus et couverte
confondus, bien au-dessus de 0,5 — sans calibration, rien n'est jamais refusé. En config C, le
seuil naïf améliore même légèrement le taux de refus brut (6/8 contre 5/8) mais au prix d'un
effondrement des réponses tenues (9/14 contre 13/14) : il refuse à tort des questions couvertes
dont le score reranker, légitime, tombe entre 0,05 et 0,5 (`RAG-12`, `RAG-13`, `RAG-15`,
`RAG-19`, `RAG-21`).

**Conclusion.** La calibration n'a pas le même enjeu selon la stratégie : pour le dense, c'est
la différence entre une barrière qui fonctionne et une qui ne fait rien ; pour l'hybride, c'est
un arbitrage entre refus et réponses tenues, et un seuil choisi au jugé peut sembler « mieux »
sur le seul taux de refus (6/8 > 5/8) tout en dégradant fortement l'autre versant. C'est
exactement pourquoi `best_threshold()` (`scripts/calibrate_threshold.py`) optimise la somme des
deux termes (refus corrects + réponses tenues) et non le taux de refus seul — un seuil qui
maximise un seul terme est trompeur.

Piste refermée : aucun script ni cible Make ajoutés, aucun code applicatif modifié — la mesure
est reproductible par quiconque relit les deux CSV et réapplique la règle ci-dessus.
