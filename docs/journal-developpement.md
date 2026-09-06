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

---

## 2026-09-02 — Piste exécutée : le rang RRF avant rerank, contribution de chaque étage

Question posée en marge du gain E6 : dans la configuration C (BM25 + dense + RRF + rerank),
combien du gain vient de la **fusion RRF** seule, et combien vient du **rerank** ? Ni le
protocole ni les quatre drapeaux mesurés ne l'isolent — `_hybrid_search`
(`retrieval/search.py:289-294`) refuse même de tourner sans reranker. La question est jugée
**non couverte** par le livrable E6 (qui ne demande que le gain du pipeline complet) mais
**pertinente** comme diagnostic, motivée par le constat de l'axe 2 : « nettoyage et
versionnement, effet nul sur l'hybride » suggérait déjà que le reranker absorbe le bruit en
aval, donc fait le plus gros du travail. Vérifié ici.

**Méthode.** Aucune modification du code : un script ad hoc rejoue exactement la séquence de
`_hybrid_search` jusqu'à la fusion RRF (`search.py:295-304`, `depth=rerank_candidates=20`,
`version_filter=True`, texte `clean`), **sans appeler le reranker** — arrêt juste avant
`search.py:313`. Les 8 questions `reference_exacte` de `eval/questions_rag.jsonl`, tronquées à
`top_k=5` pour comparer à la même profondeur que les métriques publiées, avec et sans la règle
de départage (`apply_tiebreak`, réutilisée telle quelle — elle ne lit que les métadonnées, pas
un score).

**Résultat**, comparé au CSV déjà publié (`eval/resultats/mesure-hybride.csv`, RRF + rerank) :

| | Hit@1 référence | Hit@1 fiche technique |
|---|---:|---:|
| RRF seul, sans départage | 4/8 | 2/8 |
| RRF seul, avec départage | 4/8 | 4/8 |
| RRF + rerank (publié, config C) | **8/8** | **8/8** |

Sur les 16 lignes (8 questions × 2 critères), **le bon document est systématiquement présent
dans les 5 premiers résultats de la fusion RRF** — jamais un cas où RRF l'aurait laissé au-delà
du top-5. Le reranker ne repêche donc jamais un candidat absent, il ne fait que réordonner.

**Lecture.** Les deux étages ont des rôles distincts, pas redondants : **RRF assure le rappel**
— faire entrer le bon candidat dans les cinq (16/16, sans exception) — et **le rerank assure la
précision** — le faire remonter au rang 1 (de 4/8 ou 4/8 à 8/8). La règle de départage récupère
la moitié de l'écart sur le critère fiche (2/8 → 4/8, en échangeant une notice contre une fiche
de même référence, exactement son rôle documenté), mais c'est le rerank qui referme tout le
reste. Ça confirme, chiffré, l'intuition de l'axe 2 : le cross-encoder fait la majorité du
travail de précision dans le pipeline hybride.

Piste refermée : aucun script ni cible Make ajoutés, aucun code applicatif modifié.

## 2026-09-03 — Chantier Text-to-SQL : le moteur en bibliothèque

**Périmètre arbitré avec l'utilisateur avant d'écrire une ligne.** Les quatre tests
d'acceptance SQL passent tous par `mcp_server.server`, qui relève du chantier 3. Deux
lectures étaient possibles : livrer un serveur MCP minimal pour verdir T1→T4 tout de suite,
ou livrer le moteur en bibliothèque et laisser les tests rouges. **La bibliothèque a été
retenue**, conformément au rythme du dépôt — une étape à la fois — et parce qu'un serveur
écrit ici pour quatre tools devrait être rouvert au chantier 3 pour les huit.

Trois conséquences assumées : ni serveur MCP, ni étage 2 (`tool_interdit`), **ni journal
JSONL**. Le journal est une couche transverse aux huit tools ; l'écrire pour quatre
reviendrait à le réécrire. En contrepartie, les fonctions de `tools.py` rendent tout ce
qu'il faut pour journaliser — `code`, `sql`, `n_rows`, `latency_ms` — de sorte que le
chantier 3 branche au lieu de recalculer.

**Emplacement** : `packages/text_to_sql_factory/`, choisi par l'utilisateur. Les squelettes
`sql/` et `mcp_server/` restent au chantier 3 ; `mcp_server/matrice.yaml` y a été posée dès
maintenant, à sa destination normative, parce que c'est une donnée de configuration et non
du code.

### Les huit modules, et l'ordre du flux

`access` (N1, la matrice) · `contract` (N2, le contrat de lecture) · `generator` (N3, une
passe LLM) · `validator` (N4 · N5, cinq contrôles puis la borne) · `executor` (N6 · N7,
connexion en lecture seule puis contrôles du résultat) · `tools` (les quatre tools) ·
`check_sql` (contrôles déterministes) · `eval_sql` (les 24 questions).

### Décisions prises, là où la conception laissait ouvert

| Point ouvert | Décision | Motif |
|---|---|---|
| `LIMIT` par défaut, plafond, timeout — jamais chiffrés (Q2 §3 C4) | 200 · 1000 · 5,0 s, dans `Settings` | révisables sans toucher au code ; le plafond est la vraie garde (337 620 lignes en 0,4 s) |
| mécanisme de timeout — les deux vérifiés, aucun choisi | `set_progress_handler` | pas de thread minuteur : moins de surface pour un gain nul ici |
| convention « annulées exclues » vs T1 | **consigne de prompt, jamais une réécriture de requête** | elle porte sur les chiffres de vente, marge et quantité, pas sur un comptage de commandes — c'est ce qui préserve T1, dont l'attendu (27) ignore le statut |
| enveloppe : 12 codes vs `{status, payload, message}` | `status` en surface, les douze codes dans `payload["code"]` | arbitrage déjà posé à l'étape 1 : le test fait foi |
| matrice : `cadrage_dsi.md` ferme `ventes` au support, `matrice.yaml` l'ouvre sauf `marge_ht` | `matrice.yaml` fait foi | aucun test ne tranche, et l'écart ne change aucun verdict : SQL-17→20 tombent tous sur les trois colonnes sensibles. Arbitrage de fond toujours au chantier 3 |
| profils | les quatre de `matrice.yaml` | `default` = zéro droit, atteint par tout profil inconnu — vérifié |

### Trois écarts constatés en écrivant, et ce qui a été fait

**1. `docs/schema.sql` commente `ventes.prix_unitaire_ht` « remise déduite » ; la mesure dit
l'inverse.** `SUM(quantite × prix_unitaire_ht)` reconstitue `montant_ht` sur 340 commandes
sur 340 (`description-base.md` §5.1). Le document livré n'a pas été modifié : c'est le
contrat donné au modèle qui porte le fait mesuré, via `_COLUMN_NOTES` dans `contract.py`.
Transmettre au modèle un commentaire faux produirait du SQL faux, pas une erreur.

**2. Le catalogue liste `produits.nom` parmi les colonnes de `check_stock` ; le contrat de
sortie de `Q4` §3 ne le montre pas.** Le contrat de sortie explicite a été suivi : trois
lignes `entrepot · quantite · seuil_reappro · sous_seuil`, plus le `total`. Écart signalé,
non refermé.

**3. Le paramètre malformé n'a pas de code dans le catalogue.** `check_stock("disjoncteur")`
n'est ni un refus de droit ni une absence de donnée. Retenu : `erreur_execution`, donc
`status: error`, avec le format attendu dans le message — et de toute façon l'`inputSchema`
MCP l'écartera avant l'envoi au chantier 3.

### Deux bugs trouvés par les contrôles, pas par la lecture

**`Expression.limit()` élargit une requête déjà bornée.** Appelée avec 200 sur `… LIMIT 5`,
elle rend `LIMIT 200` — exactement ce que Q2 §3 C4 interdit (« jamais en remplacement d'un
`LIMIT` plus petit »). `_apply_limit()` lit donc la borne existante avant de poser la sienne.

**Un alias de projection était pris pour une colonne inventée.** `SELECT SUM(v.quantite) AS
quantite_vendue … ORDER BY quantite_vendue` faisait échouer SQL-04 en `erreur_execution` :
`quantite_vendue` n'est dans aucune table. Les alias de sortie du scope sont désormais
écartés — sans rouvrir quoi que ce soit, puisque la colonne réellement lue derrière l'alias
reste vue avec sa table (vérifié : `marge_pct AS x` est toujours refusé au support, tandis
que `nom AS marge_pct` passe, et ne fait fuir que `nom`).

### Le premier appel LLM réellement exercé du projet

Le rerank Azure n'avait jamais tourné contre un déploiement réel. Deux enseignements :

- **le déploiement refuse `temperature`** (« Unsupported value: 'temperature' does not
  support 0 »), comportement des modèles de raisonnement. Le paramètre a été retiré ; la
  sortie est tenue par le format JSON imposé, pas par un réglage d'échantillonnage ;
- **le motif de refus doit être un champ racine.** Imbriqué dans un objet `refus`, le modèle
  le rendait en chaîne nue, et les quatre demandes d'écriture sortaient en `hors_schema`
  avec « ecriture » pour message. À plat, avec la consigne que `refus` est une phrase et
  `motif` un code, les quatre sortent en `ecriture_refusee`.

Un troisième ajustement a été nécessaire : le modèle demandait une clarification là où une
convention tranche déjà (SQL-06, SQL-12). Le prompt dit maintenant que les conventions
s'appliquent d'office et qu'on ne demande jamais s'il faut exclure les annulées.

**`hors_schema` requalifié en `perimetre_interdit`.** Le modèle ne voit jamais une colonne
fermée : sur SQL-17→20, il refuse donc « la base ne porte pas cette donnée », ce qui est un
refus exact mais un message faux — la donnée existe, elle est fermée. Le code requalifie
après coup, en nommant la colonne. Ce n'est **pas** une liste de mots interdits : elle ne
protège rien, elle qualifie un refus déjà prononcé, et sans elle l'utilisateur ne saurait
pas qu'il peut demander l'accès.

### Vérification

`make check-sql` — **tous les contrôles passent** : décompte 28/25/25/0 sur les 31 colonnes,
`clients.email` fermée aux quatre profils, les trois colonnes sensibles absentes du contrat
du support (pas même leur nom), les 21 cas de validation de Q2 §6 et Q3 §8 au verdict
attendu (`VACUUM INTO`, `ATTACH`, `PRAGMA`, deux instructions, l'alias, la CTE, l'étoile
développée, la dichotomie booléenne, la jointure licite non bloquée), la lecture seule tenue
par la connexion seule, T1 = 27, stock = 774, `CMD-2026-0042` en `aucune_ligne`, l'égalité
374 = 374 détectée à la frontière du classement mais pas au top 5 — conforme à Q5 §4.

`make eval-sql` — **24/24 conformes** au premier run après correction, publié dans
`eval/rapport_sql.md`. Chiffres recoupés avec `description-base.md` §8 : SQL-01 = 27,
SQL-03 = 11 lignes, SQL-06 = 432 245,90 €, SQL-07 = 3, SQL-09 = 41. SQL-02 rend les trois
lignes par entrepôt qui somment à 774, et non le scalaire — c'est le comportement voulu.

**Nommage séparé, exprès** : `eval-sql` et `rapport_sql.md`, jamais le préfixe `mesure-` ni
`rapport_gain.md`. `eval/protocole-mesure.md` §10 range `questions_sql.jsonl` « hors de ce
protocole » : un chiffre SQL ne doit pas pouvoir se lire comme un chiffre E6.

### Points ouverts, laissés au chantier 3

- **les quatre tests d'acceptance SQL restent rouges** — `mcp_server.server` n'existe pas ;
- **`pytest` n'arrive même pas à collecter — et la cause n'est pas dans `tests/`.**
  `literalai` 0.1.201, dépendance de `chainlit` arrivée avec le client web, publie son
  propre dossier `tests/` **à la racine de `site-packages`**, avec un `__init__.py`. Un
  paquet régulier l'emporte toujours sur un dossier qui n'en a pas, quel que soit l'ordre
  de `sys.path` : le `tests/` du dépôt est masqué, et `from tests.conftest import …`
  échoue. Vérifié en écartant temporairement le dossier parasite, puis en le restaurant :
  la collecte repart, **11 échecs et 1 succès** — le succès étant
  `test_gain_hybride_mesure_et_documente`, les 11 échecs tous « module
  `mcp_server.server` introuvable ». C'est-à-dire **exactement l'état annoncé à la clôture
  du chantier RAG** : la suite de tests est saine, c'est l'empaquetage de `literalai` qui
  est fautif. Rien n'a été touché dans `tests/` — décision de l'utilisateur, la suite est
  arrivée avec le dépôt et posée par le formateur. Contournement possible sans y toucher :
  retirer `site-packages/tests/` après chaque `uv sync`, ce dossier ne servant qu'aux tests
  internes de `literalai` et n'étant jamais importé à l'exécution ;
- **trois erreurs `mypy` préexistantes** dans `packages/web_client/app.py` et
  `packages/rag_machines/check_index.py`, hors du périmètre de ce chantier ;
- le journal JSONL, l'étage 2, et l'arbitrage de fond sur le contenu de la matrice.

## 2026-09-03 — Banc d'essai : le Text-to-SQL branché sur l'agent conversationnel

Le chantier 2 avait livré le moteur SQL en bibliothèque, sans appelant. L'agent LangChain
de `packages/agent/` n'avait qu'un tool, `search_docs` : le SQL n'était observable qu'en
Python, donc invisible depuis l'interface Chainlit. Ce palier le rend testable au clic,
**pour le développement et la visualisation uniquement**.

### L'écart assumé, et sa date de péremption

Le profil est ici **déclaré par le client** : `chat_profile` Chainlit → `role` de l'API →
profil de matrice. La conception veut l'inverse — `SORABEL_PROFILE` lu au lancement du
serveur MCP, jamais reçu du client, précisément pour que le LLM du client ne puisse pas
l'écrire. Décision prise avec l'utilisateur : le raccourci est accepté pour le banc d'essai,
et il disparaît au chantier 3.

**Ce qui n'est pas court-circuité** : la matrice et la validation d'AST s'appliquent à
l'identique. Le raccourci porte sur *qui déclare le profil*, pas sur *ce que le profil
autorise*.

### Décisions

| Point | Décision | Motif |
|---|---|---|
| nom du tool exposé à l'agent | **`ask_to_db`** | le tool LangChain n'est pas le `ask_database` du catalogue MCP : il l'appelle. Deux noms identiques laisseraient croire que le catalogue est implémenté, alors qu'il ne le sera qu'au chantier 3 |
| clé lue dans la matrice | reste **`ask_database`** | c'est le nom du tool *au catalogue*, celui que la gouvernance nomme. Le nom local du banc d'essai n'a pas à contaminer la matrice |
| tools exposés | **les quatre du chantier 2** : `ask_to_db`, `check_stock_by_ref`, `order_status_by_id`, `get_db_schema` | voir « le détour par le point d'entrée unique » ci-dessous |
| portée de la matrice | **étage 2 sur les quatre tools SQL** | le SQL est gouverné de bout en bout ; `search_docs` reste ouvert à tous les rôles, donc aucune régression sur la démo RAG — vérifié, un profil `default` obtient toujours sa réponse documentaire sourcée |
| rôle UI `admin` | **nouveau profil `admin` dans `matrice.yaml`** | sans lui, il retombait sur `default` et ne pouvait rien faire : juste au sens de la matrice, illisible dans une UI qui affiche « admin » |
| périmètre d'`admin` | 8 tools, **28 colonnes** — celles de `commercial` | `clients.email` reste fermée aux **cinq** profils : son motif est le RGPD, pas E5, et l'agent qui appelle ces tools *est* un LLM. Un rôle d'administration ne lève pas cette raison-là |

`authorize()`, écrite au chantier 2 sans appelant, trouve ici son premier usage. C'est ce
qui rend `dev` conforme à la matrice — elle lui donne `get_schema` mais **aucun tool de
lecture de données** — et `default` sans aucun droit SQL.

### Deux détails d'implémentation qui auraient mordu

**`_agent_for` était un `lru_cache` sur la seule stratégie.** Le profil étant capturé à la
construction du tool, le premier rôle utilisé aurait été servi à tous les suivants : un
`sans_role` aurait hérité des droits d'un `commerciale` passé avant lui. La clé de cache est
désormais le couple `(stratégie, profil)`.

**Les rôles de l'UI ne portent pas les noms des profils** : `commerciale` vaut `commercial`,
`sans_role` vaut `default`. La conversion vit à un seul endroit, `profile_for_role()` dans
`api.py`, et rend `default` sur un rôle inconnu — la conversion est totale comme la matrice.

L'accueil Chainlit annonce désormais les droits effectifs du rôle actif (profil, colonnes
atteignables, marges ou non, accès à la base ou non). Un `sans_role` apprend à l'accueil
qu'il n'obtiendra aucun chiffre, au lieu de le découvrir par un refus qui ressemblerait à
une panne.

### Vérification

`make check-sql` reste intégralement vert — il relit la matrice, c'est lui qui aurait
attrapé une erreur dans l'ajout du profil `admin`. Décompte : `commercial 28 · admin 28 ·
support 25 · dev 25 · default 0`.

Le scénario complet rejoué sur l'agent :

| Profil | Question | Obtenu |
|---|---|---|
| `commercial` | combien de commandes en avril ? | **27**, avec la requête et la convention |
| `support` | quelle est la marge sur la REF-8842 ? | refus `perimetre_interdit` nommant `produits.marge_pct` et `ventes.marge_ht` |
| `commercial` | marge totale des ventes de mai 2026 | **113 604,48 €** — la valeur *hors annulées* de Q1 §5, donc la convention est bien appliquée |
| `dev` | « que contient la base ? » | le contrat de lecture — `get_schema` lui est accordé |
| `dev` · `default` | question chiffrée | `tool_interdit`, avec le renvoi vers `search_docs` |
| `admin` | marge totale de mai 2026 | le chiffre — le profil ne retombe plus sur `default` |
| `default` | délai d'un échange standard ? | réponse documentaire sourcée : le RAG est intact |

### Le détour par le point d'entrée unique, et pourquoi il a été rebroussé

Une première décision avait retenu **un seul tool `ask_to_db`** aiguillant en interne vers
les quatre fonctions, selon la forme de la question. L'implémentation a été commencée puis
abandonnée en cours de route, sur ce qu'elle produisait :

```python
_STOCK_WORDS  = ("stock", "entrepôt", "réappro", "disponib")
_STATUS_WORDS = ("statut", "état", "où en est", "avancement", "livrée")
```

**Une liste de mots pour décider d'une opération** — le raisonnement que Q2 §2 écarte
« définitivement », ici pour l'aiguillage et non pour la sécurité, mais avec le même défaut :
elle ne peut pas être complète, il faudrait avoir prévu chaque formulation. « Quelles lignes
de vente dans CMD-2025-0042 ? » porte un identifiant de commande et ne doit justement *pas*
aller vers `order_status`, qui ne rend que l'en-tête.

Trois raisons ont fait basculer sur quatre tools distincts :

1. **c'est le LLM qui aiguille, et le catalogue l'a déjà outillé pour ça** — sa section 3
   traite les six collisions de descriptions, « le domaine en premiers mots, jamais le
   verbe ». Un aiguilleur maison jette ce travail pour des regex ;
2. **la matrice redevient observable** — le rôle `dev` obtient `get_db_schema` et **rien
   d'autre**, exactement ce que dit la matrice, visible au clic. Avec un point d'entrée
   unique, il aurait vu un tool qui marche parfois ;
3. **c'était du code jetable** — le serveur MCP exposera quatre tools distincts ; quatre
   tools LangChain le préfigurent, l'aiguilleur aurait été supprimé.

Vérifié après bascule, sans aucune heuristique dans le code : « quel est le stock de la
REF-8842 ? » → `check_stock_by_ref` (774, trois entrepôts) · « statut de la commande
CMD-2025-0042 » → `order_status_by_id` · « que contient la base ? » → `get_db_schema` ·
« combien de commandes en avril ? » → `ask_to_db` (27). Le modèle choisit juste à chaque
fois, sur les seules descriptions.

### Points ouverts

Inchangés : le serveur MCP, et le retrait de ce raccourci de profil quand `SORABEL_PROFILE`
sera lu côté serveur.

**E5 reste à moitié ouverte, et c'est un écart au brief, décidé.** Confrontation faite le
2026-09-03 : le brief nomme « E3, E5 » dans l'**étape 1 du chantier Text-to-SQL**, et le
test T2 exige une demande d'écriture « refusée **et journalisée** ». La seconde moitié
d'E5 — « les colonnes sensibles ne sortent jamais pour le profil support » — est tenue et
vérifiée sur 21 cas par `make check-sql`. La première — « tout appel, autorisé ou refusé,
est journalisé » — **n'est pas implémentée**.

Décision de l'utilisateur : la garder pour le chantier 3. Le motif tient : le journal est
transverse aux **huit** tools, et l'écrire pour quatre obligerait à le réécrire. Ce n'est
donc pas un oubli mais un report, et il est consigné ici pour qu'on ne le relise pas comme
tel.

Ce qui reste à faire, quand le moment viendra : une écriture JSONL vers `GATEWAY_JOURNAL`
au format du cadrage (`timestamp`, `profile`, `tool`, `arguments`, `status`, `message`),
enrichie de `code`, `sql`, `n_rows`, `latency_ms` et du champ `etage`. **Les quatre tools
rendent déjà tout cela** — c'est la raison pour laquelle leurs enveloppes portent
`latency_ms` et `n_rows` alors que rien ne les lit encore. Le chantier 3 branche, il ne
recalcule pas.

## 2026-09-03 — Contrôle 6 : confronter la requête au moteur avant de l'exécuter

Le validateur jugeait la requête sur son seul arbre sqlglot, puis on l'exécutait pour de
vrai. Entre les deux, rien ne vérifiait qu'elle *tourne*. Demande de l'utilisateur : un
essai « en vrai mais pour de faux » par `EXPLAIN`, entre la validation de forme et
l'exécution.

### La séquence, et pourquoi cet ordre

L'utilisateur a proposé la séquence — table autorisée pour le rôle, puis forme sqlglot,
puis `EXPLAIN`. Un ajustement : sqlglot doit parser d'abord, sinon on ne sait pas quelles
tables la requête cite. L'ordre retenu :

```
1. sqlglot    forme : une instruction, pas d'écriture, racine = lecture
2. tables     ∈ scope.tables du rôle          (5a, nouveau)
3. colonnes   ∈ scope.columns du rôle          (5b, existant)
4. LIMIT
5. EXPLAIN    essai à blanc                    (contrôle 6, nouveau)
```

Deux propriétés que l'ordre inverse ne donnerait pas :

- **5a avant 5b.** `qualify` ne sait pas résoudre les colonnes d'une table qu'il ignore :
  il les laisse sans préfixe, et la règle d'alias de `referenced_columns` les écarte alors
  du contrôle. Sans le contrôle des tables, celui des colonnes est **aveugle sur elles** —
  une table hors matrice emportait toutes ses colonnes avec elle.
- **6 en dernier.** C'est le seul pas qui touche la base : rien ne l'atteint avant que la
  matrice ait tranché. Et le motif du refus reste juste — `SELECT sql FROM sqlite_master`
  est un `perimetre_interdit` (la table existe, elle n'est pas à ce profil), pas un
  `erreur_execution` (« ta requête est fausse »). C'est ce que le journal doit enregistrer.

### Ce que l'essai à blanc rattrape, et ce qu'il ne rattrape pas

sqlglot **transpile déjà** `ILIKE` → `LOWER(…) LIKE LOWER(…)`, `::` → `CAST`, `STRING_AGG`
→ `GROUP_CONCAT`. Le trou n'était pas là. Il est dans ce que sqlglot ne sait pas transposer
et recopie tel quel, et que le validateur déclarait `ok` :

| requête, après `validate` | avant | après |
|---|---|---|
| `DATE_TRUNC('month', date_commande)` | `ok`, échec à l'exécution | `erreur_execution`, avant exécution |
| `WHERE date_commande > NOW()` | `ok` | `erreur_execution` |
| `EXTRACT(EPOCH FROM date_commande)` | `ok` | `erreur_execution` |
| `SELECT id FROM commandes c JOIN clients cl …` | `ok` | `erreur_execution` (ambiguë) |

`EXPLAIN` répond « cette requête se prépare », jamais « cette requête est permise » :
`SELECT * FROM commandes, commandes b, commandes c` le passe sans broncher. Il **complète**
la liste blanche, il ne la remplace pas. C'est le contrôle 5a, pas lui, qui ferme
`sqlite_master`.

### Le trou trouvé en instruisant la demande — le plus grave des trois

`qualify()` met tous les identifiants entre guillemets doubles, et SQLite applique la
misfeature *double-quoted string literal* : **un identifiant entre guillemets qui ne résout
pas devient une chaîne de caractères**. Avant correction, sans rien de spécial :

```
validate("SELECT zzz FROM commandes", "support")
  → ok, sql = 'SELECT "zzz" AS "zzz" FROM "commandes" AS "commandes" LIMIT 200'
execute(…)
  → code=ok, columns=('zzz',), 200 lignes de ['zzz']
```

Une colonne hallucinée par le modèle rendait **200 lignes d'une valeur inventée, servies
comme un résultat**, avec le SQL à l'appui — le mode d'échec que tout ce chantier existe
pour empêcher. Le bloc `unknown` ne le voyait pas : `qualify` avait produit
`SELECT "zzz" AS "zzz"`, et la règle d'alias de `referenced_columns` écarte précisément
cette colonne — l'ensemble rendu était **vide**. Le cas `WHERE inexistante = 1` de
`check_sql` ne passait que parce qu'en `WHERE`, aucun alias n'est créé.

Correctif : `quote_identifiers=False` dans `qualify()`. Vérifié sans régression sur les 31
colonnes des 5 tables, plus jointures, CTE et sous-requête — 0 échec ; les identifiants
Sorabel sont tous en snake_case simple. Les deux moitiés du trou sont fermées ensemble : le
guillemet ne déguise plus l'identifiant, et le contrôle 6 refuse ce qui reste.

### Le bloc `unknown` retiré

`validator.py` réimplémentait à la main la résolution d'alias, de CTE et de sous-requêtes
pour décider si une colonne existe. C'est là qu'il se trompait : `WITH t AS (SELECT ref,
quantite FROM stocks) SELECT ref, SUM(quantite) FROM t GROUP BY ref` était refusée en
`erreur_execution` — « référence ce qui n'existe pas : t.quantite, t.ref » — alors que la
CTE est légitime et que le contrôle 2 l'autorise explicitement. Idem pour
`SELECT x.ref FROM (SELECT ref FROM produits) x`.

Le validateur ne garde donc que la moitié **autorisation** (cette colonne est-elle dans
`scope.columns` ?) et délègue l'**existence** au moteur, qui résout correctement. Sept
lignes en moins, deux faux refus en moins.

### La passe de réparation

Sur échec du contrôle 6, l'erreur du moteur est rendue au modèle pour **une** reprise,
jamais deux. Décision de l'utilisateur : refuser sec faisait porter à l'utilisateur une
fonction Postgres échappée du modèle, qui n'est pas une question mal posée.

L'invariant tient dans un champ : `Verdict.repairable`, posé **par le seul contrôle 6**.
Un `perimetre_interdit` ou un `ecriture_refusee` ne le porte jamais — un refus de droits ne
se renégocie pas avec le modèle. Et la reprise repasse **tous** les contrôles, périmètre
compris : elle ne peut pas sortir de la matrice. Le champ ne quitte pas le paquet :
l'enveloppe de la DSI est inchangée, aucun code nouveau.

### Le dialecte

Le littéral `"sqlite"` était répété cinq fois dans deux fichiers. Il devient
`SQL_DIALECT` dans `__init__.py`. **Aucun chemin PostgreSQL n'est construit** — la gateway
ne connaît qu'une base ; le littéral répété cachait ce fait au lieu de l'énoncer.
`EXPLAIN <requête>` est en revanche la graphie portable : SQLite, PostgreSQL (sans
`ANALYZE`), MySQL et DuckDB l'acceptent. Seule la connexion dépend du moteur.

### Vérification

`make check-sql` : **81 contrôles, tous au vert**, contre 46 avant. Les nouveaux — trois
sur le contrôle 5a (`sqlite_master` projetée, `sqlite_master` en étoile, source sans nom de
table), trois sur le contrôle 6 (colonne inventée, `DATE_TRUNC`, ambiguïté de jointure),
deux sur ce que le bloc `unknown` refusait à tort (CTE, sous-requête), trois sur la faille
DQS, huit sur la passe de réparation.

Un de ces contrôles **épingle la misfeature elle-même** :
`explain('SELECT "zzz" FROM commandes')` rend une chaîne vide, `explain("SELECT zzz FROM
commandes")` refuse. Si ce cas bascule un jour, on saura pourquoi `quote_identifiers=False`
est là.

**La passe de réparation est exercée sans appel de modèle**, par un `_ScriptedGenerator`
qui rend des requêtes écrites d'avance. Ce n'est pas de la commodité : le modèle réel écrit
du SQLite correct — le contrat le lui impose — et **aucune des 24 questions du jeu ne
déclenche de reprise**. Trois questions temporelles écrites exprès pour l'y pousser
(« chiffre d'affaires par mois », « par trimestre ») ont produit `STRFTIME` et
`SUBSTRING`, jamais `DATE_TRUNC`. Sans générateur scripté, le chemin ne serait jamais
exercé, et l'invariant de sécurité — pas de reprise sur un refus de droits — ne serait
vérifié nulle part.

`make eval-sql` : **24/24 conformes**, zéro reprise. Le rapport porte désormais la section
« Reprises après l'essai à blanc » et une colonne `reprise` par question, pour que ce zéro
soit lu comme une mesure et non comme une absence de mesure.

`make lint` : ruff au vert, mypy sans erreur sur `text_to_sql_factory` (trois erreurs
préexistantes subsistent dans `rag_machines/check_index.py` et `web_client/app.py`,
hors périmètre).

Coût mesuré de l'`EXPLAIN` : **~1 ms, zéro ligne lue**, sur une connexion neuve `mode=ro` +
`query_only` — la même que l'exécution, doctrine C2 inchangée. Pas de garde-temps : la
préparation est bornée par nature.

### Écarts à consigner

1. **`EXPLAIN` avait été retiré de la conception V3.**
   `docs/conception/LIVRABLES_CONCEPTION/README.md:46` : « cité dans le nœud N4 de la V2,
   sans trace dans aucune note de conception (`grep` négatif sur tous les `.md`) → retiré de
   la V3 ». On y revient délibérément. Le motif qui manquait à l'époque est la faille DQS
   documentée ci-dessus : elle n'était pas connue quand la décision a été prise.
2. **La passe de réparation ajoute un second appel LLM** sur une branche. `make eval-sql`
   peut donc varier d'une exécution à l'autre sur les questions concernées — le rapport
   compte désormais les reprises. `make check-sql` reste entièrement déterministe : il
   appelle `validate` sans passer par `tools`.

### Points ouverts

Le constat de revue sur `_filters_on_label` (le disjoncteur ignore la table du couple),
sur `truncated` (jamais vrai pour le `LIMIT` injecté), sur `N7` (compare les dernières
colonnes projetées, pas les clés de tri) et sur `MIN`/`MAX` en table vide **restent
ouverts** : ils ne touchent pas au chemin de validation et n'ont pas été traités ici.

---

## 2026-09-03 — La matrice gouverne aussi le corpus : module d'accès partagé et filtre de périmètre

### Ce qui l'a déclenché

Une capture d'écran de l'accueil Chainlit. Le rôle `sans_role` y lisait : « profil `default`
— aucun chiffre : les questions sur les données seront refusées. **La documentation reste
interrogeable.** » Or `default` n'a aucun tool dans la matrice, `search_docs` compris, et
aucune collection. La phrase était fausse au regard de `matrice.yaml`, et ne passait
inaperçue que parce que le banc d'essai n'appliquait l'étage 2 qu'aux quatre tools SQL : la
recherche documentaire répondait, effectivement, à un profil qui n'y avait pas droit.

Deux corrections successives, dans cet ordre : le libellé a d'abord été branché sur
`scope.tools` en disant l'écart ; puis l'écart lui-même a été supprimé.

### Le module d'accès, remonté d'un cran

`packages/text_to_sql_factory/access.py` → **`packages/access.py`**. Le `Scope` qu'il porte
décrit les deux domaines — `columns` pour le SQL, `collections` et `themes_notes` pour le
corpus — et laisser son unique lecteur dans le paquet SQL aurait fait dépendre le chantier
RAG du chantier Text-to-SQL.

**Le fichier n'a pas été dupliqué**, malgré la tentation d'un `access_sql.py` et d'un
`access_rag.py` autonomes. Sur ses 143 lignes, une dizaine seulement sont spécifiques au
SQL : tout le reste — le `Scope`, le chargement défensif, le cache sur le mtime, la
retombée sur `default`, `authorize()` — est commun. Et `authorize()` ne se coupe pas en
deux : c'est l'étage 2 des **huit** tools du catalogue, et `tools:` est une seule liste
blanche par profil. Deux `authorize()` auraient répondu à la même question sur la même
donnée. `matrice.yaml` le dit d'ailleurs en tête : « lue partout par une fonction unique ».

Ce qui s'est séparé, ce sont les **lecteurs** : `text_to_sql_factory/access_sql.py` et
`rag_machines/access_rag.py`, un par domaine, sur une matrice lue une seule fois.

`forbidden_columns` a été renommée **`columns_outside_scope`** au passage. Le nom laissait
croire à une liste noire alors que la fonction dérive de la liste blanche et n'énumère rien.
Elle était surtout **morte** — zéro appelant — pendant que `tools.py:_forbidden()`
réimplémentait son corps mot pour mot. Elle est maintenant branchée, et c'est son seul
appelant. Le contrôle 5b du validator n'a **pas** été touché : sa condition supplémentaire
`column[0] in schema` distingue « hors périmètre » de « hors schéma », ce n'est pas la même
fonction malgré la ressemblance.

### Le filtre de périmètre : une vérification que la conception avait différée

La forme du `where` n'a pas été inventée. Elle est écrite en pseudo-code exact dans
`3-exposition-mcp-et-matrice-d-acces/Q3.md` §8, sous une note explicite : « la forme
ci-dessus est **documentée, pas exécutée** : `chromadb` n'est pas installé dans
l'environnement du projet. Le premier jour du développement la vérifie sur les quatre
profils, avec la version figée. » Ce chantier est ce premier jour.

**Une disjonction, jamais une conjonction.** La clé `theme` est *omise* des métadonnées sur
les 320 éditions qui ne sont pas des notes, et Chroma évalue à faux toute comparaison sur
une clé absente. Un `$and` de `doc_type` et `theme` n'aurait donc remonté **que des notes** —
48 éditions au lieu de 318 pour le support — sans qu'aucune erreur ne le signale. La forme
retenue met les collections ordinaires dans une branche qui ne mentionne jamais `theme`.

**`$nin` a été examiné et écarté.** Il exprimerait « clé absente » en une ligne — Chroma le
compile en `NOT IN` que les éditions sans clé traversent — mais il demande d'énumérer ce qui
est fermé là où la matrice n'énumère que ce qui est ouvert. Un thème ajouté demain y serait
ouvert par défaut : l'inverse de la liste blanche tenue partout ailleurs. Le motif du rejet
est écrit dans la docstring de `perimeter.py`, pour que personne ne « simplifie » dans six
mois.

**Un objet à deux rendus, pas deux ensembles nus.** `Perimeter` porte `where()` pour Chroma
et `allows()` pour BM25. La règle s'applique deux fois, et la configuration hybride fusionne
les deux listes par RRF : une note qui fuirait par le seul étage lexical entrerait dans la
fusion et sortirait au résultat. Écrite à deux endroits, la divergence ne se serait vue que
par une réponse fausse ; écrite une fois, elle se contrôle.

**`search()` reçoit un périmètre, jamais un profil.** `retrieval/` n'importe pas
`packages/access.py` et reste « paramétré, jamais câblé ». La conversion et le refus vivent
dans `access_rag.py`, seul module à connaître les deux mondes.

**Deux barrières contre le périmètre vide**, parce qu'un `where={}` ne filtre rien et
ferait lire le corpus entier à `default` : le refus est prononcé dans `perimeter_for()`
avant toute requête, et `Perimeter.where()` lève plutôt que de rendre un filtre vide.

### Avant la troncature, et pourquoi ça se paie

Le filtre part **dans la requête**, comme `is_current`. Côté BM25, cela imposait de porter
`doc_type` et `theme` dans le pickle : `LexicalIndex` a gagné deux listes parallèles, et les
deux index — `sorabel_corpus.pkl` et `sorabel_corpus_raw.pkl` — ont été régénérés. Un
`_check_schema` au chargement refuse désormais un pickle antérieur en nommant `make ingest` :
sans lui, un index périmé se dépicklait sans bruit et cassait au premier `search` filtré,
loin de sa cause.

Les scores BM25 ne bougent pas — on n'ôte rien du corpus, donc rien des fréquences
documentaires ; on écarte des candidats après le calcul, exactement comme `is_current` le
fait depuis l'étape 2. Vérifié : `mesure-lexical` et `mesure-hybride` rejouées après
régénération, **`git diff` vide** sur les six CSV publiés, Hit@1 8/8 et MRR 1,000 inchangés.

### La mesure, plutôt que l'argument — axe 3 du protocole

Le choix « avant la troncature » a été chiffré au lieu d'être seulement défendu.
`make mesure-perimetre` compare **P0** (filtrage après troncature, fabriqué dans le script à
partir du classement de référence — aucune branche morte en production) et **P1** (avant),
sur les quatre profils que la matrice dote d'un périmètre. `default` en est exclu : il n'a
rien à filtrer, son refus tombe avant toute requête, et `check_perimeter.py` le couvre.

| Profil | Rendus P0 → P1 | Vidées P0 | Seuil décidé sur un interdit, P0 |
|---|---|---|---|
| `dev` | 4,17 → 5,00 | 3 | 5 |
| `support` | 4,73 → 5,00 | 1 | 1 |
| `commercial` *(témoin)* | 5,00 → 5,00 | 0 | 0 |
| `admin` *(témoin)* | 5,00 → 5,00 | 0 | 0 |

**Deux témoins plutôt qu'un.** `admin` a exactement le périmètre documentaire de
`commercial` — même quatre collections, mêmes cinq thèmes ; `matrice.yaml` le dit
délibérément (« il n'a PAS plus »). Les jouer tous les deux ne mesure donc rien de neuf sur
le filtre, mais atteste que cette propriété de la matrice est bien lue : leurs 60 lignes de
CSV coïncident une à une, `stage` par `stage`. Un seul des deux n'aurait rien dit de l'autre.

Hit@1 et MRR sont identiques partout — attendu, et annoncé avant la mesure : **aucune des 30
questions ne vise une note interne**, donc aucune cible n'est rendue inatteignable. Le filtre
ne retire pas de réponses, il libère des places.

**Ce que la mesure n'établit pas, et qui est publié comme tel** : les questions que P0 vide
entièrement sont toutes des `hors_corpus` (RAG-27, 29, 30 pour `dev`). Les refuser est juste —
P0 les refuse pour la mauvaise raison, avec le bon résultat. Le refus indu redouté ne se
produit pas sur ce jeu, faute d'une question couverte dont tout le top-5 soit interdit.
L'écart réel tient donc aux deux autres colonnes : **0,83 résultat perdu par question** chez
`dev`, et **cinq questions où le seuil de refus a été décidé sur un document que
l'utilisateur ne verrait jamais**.

### Écarts et décisions à consigner

1. **`eval/protocole-mesure.md` a gagné un axe 3.** Ce document avait été arrêté *avant*
   l'implémentation exprès pour ne pas se façonner sur elle. Ajouter un axe n'est pas
   ajuster une mesure existante — les sept mesures publiées sont inchangées et rejouées à
   l'identique — mais la distinction est notée ici pour n'avoir pas à être reconstituée.
2. **`make lint` reste rouge**, sur les **trois mêmes** erreurs mypy qu'avant ce chantier
   (`rag_machines/check_index.py:45`, `web_client/app.py:51` et `:70` — décorateurs Chainlit
   et `IncludeEnum`). Vérifié par `git stash` : 32 fichiers avant, 37 après, zéro erreur
   introduite. Elles ne sont pas traitées ici, hors périmètre.
3. **Le profil reste déclaré par le client** dans le banc d'essai. L'écart est inchangé et
   tombe toujours avec le serveur MCP.

### Points ouverts

`get_document` et `list_sources` **ne passent pas par ce filtre** : le premier décide sur le
seul `doc_key`, le second construit son inventaire depuis le périmètre (`Q3` §9). Tant qu'ils
n'existent pas, la fermeture du corpus reste contournable par un chemin de fichier. Ils
appartiennent au chantier 3, et `Perimeter.allows()` est déjà la brique qui leur servira.

Le jeu `questions_rag.jsonl` n'a **aucune question dont la réponse soit une note interne**.
Tant que c'est le cas, l'axe 3 ne peut pas montrer de refus indu sur une question couverte.
Si on veut ce chiffre, il faudra des questions visant `politique-tarifaire` ou
`reunion-achat` — dans un fichier **distinct**, les mesures publiées dépendant de celui-ci.

## 2026-09-04 — Revue de code du chantier « matrice sur le corpus » : le seuil de P0 portait sur la mauvaise pièce

### Ce qui l'a déclenché

Revue de code sur `04e9bdf..HEAD` — les trois commits du chantier, 21 fichiers. **Rien dans
le chemin de production.** Vérifié en exécution et non par lecture seule : la disjonction de
`Perimeter.where()` sur les cinq profils, les décomptes en or contre les vrais pickles, le
garde-fou d'index périmé, l'absence de tout appelant résiduel de l'ancien
`text_to_sql_factory/access.py`, et l'absence de chemin de recherche contournant le
périmètre hors `eval_*` / `calibrate_*`. Les neuf constats sont tous dans la couche
mesure et documentation. Un seul est de fond.

### Le défaut : les deux configurations jugées par la même formule

`_outcome` calculait `refused` sur `ordered[0]` — le premier de la liste qu'on lui passe.
Pour P1 c'est juste. Pour **P0 c'est faux** : la liste qu'on lui passe est
`_allowed(reference, perimeter)`, déjà nettoyée, donc le seuil était comparé au premier
résultat **autorisé**. Or P0 est défini partout ailleurs — docstring du script,
`rapport_perimetre.md`, `protocole-mesure.md` §3 — comme un filtrage *après* la décision du
moteur : le seuil y porte sur le premier du classement complet, interdit ou non.

Le cas concret, avec τ = 0,053 : une note interdite en tête à 0,4, le meilleur résultat
autorisé à 0,01. Le vrai P0 accepte (0,4 ≥ τ) puis retire la note ; le script enregistrait
`refused=oui`. Comme le score autorisé est toujours ≤ le score de référence, l'erreur ne va
que dans un sens — et surtout, elle faisait juger P0 et P1 par la **même** formule sur des
listes presque identiques. La ligne « Questions couvertes refusées » ne pouvait donc
pratiquement pas montrer d'écart : le `1 / 1` publié était vrai par construction, pas par
mesure. La colonne `threshold_on_forbidden` (5 questions à `dev`) attestait pourtant que les
deux tops diffèrent.

### Le correctif

`_outcome` reçoit un `decision_top` explicite — le résultat sur lequel le seuil a
réellement porté : `reference_top` en P0, le premier de la liste filtrée en P1. Les deux
colonnes du CSV se dissocient volontairement : `score` reste celui du premier résultat
**rendu** (ce que l'utilisateur reçoit), `refused` celui de la pièce qui a **décidé**. Qu'ils
divergent est précisément le fait que l'axe 3 mesure.

### Ce que ça change, et ce que ça révèle

**Une ligne sur 240** : `dev,P0,RAG-29` passe de `refused=oui` à `refused=non`. Les tableaux
publiés ne bougent pas, `refused_answerable` ne comptant que les questions couvertes et
RAG-29 étant `hors_corpus`. Le `1 / 1` était donc juste, pour une raison qui ne tenait pas.

Mais le P0 corrigé fait apparaître un cas qui était invisible : **il accepte RAG-29 pour
`dev`, puis rend zéro résultat.** Le seuil a été franchi par un document interdit, le filtre
a vidé la liste ensuite — le profil reçoit une acceptation sans une seule source. C'est le
défaut du seuil décidé en amont du filtre dans sa forme la plus nette, et c'est pire que le
refus qu'il aurait dû recevoir. P1 refuse cette même question.

**Cela corrige une phrase de l'entrée du 2026-09-03**, qui n'est pas réécrite : « P0 les
refuse pour la mauvaise raison, avec le bon résultat » vaut pour **3 des 4** questions que P0
vide, pas pour les quatre. RAG-29 à `dev` en est l'exception, et c'est le seul endroit de ce
jeu où P0 fait réellement pire que P1 sur une décision de refus.

### La prose du rapport, dérivée des données plutôt que recopiée

Le constat 4 de la revue visait les conclusions codées en dur dans `write_report` — des
chaînes figées dans un fichier régénéré à chaque exécution. C'est exactement ce qui venait
de se produire : le paragraphe citant « RAG-27, RAG-29 et RAG-30 » avait été écrit quand il
était vrai, et le run suivant l'aurait laissé contredire les chiffres au-dessus de lui.

Réglé **sur ce paragraphe seulement** : `_cite()` dérive les identifiants des lignes
mesurées, le décompte « P0 en refuse 3 sur 4 » est calculé, et le nouveau paragraphe
« P0 accepte, et ne rend rien » est **conditionnel** — il ne s'imprime que si le cas existe
dans les données. Le reste de la prose figée est inchangé, et listé en points ouverts.

### Écarts et constats à consigner

1. **L'entrée du 2026-09-03 du banc d'essai ne décrit plus le code** sur un point :
   « `search_docs` reste ouvert à tous les rôles » était vrai à `cf62d39`, plus à `49e216c`,
   qui a ajouté `_denied(profile, "search_docs")` dans `cli.py`. **`default` reçoit désormais
   `tool_interdit`** et n'obtient plus de réponse documentaire. Ce n'est pas une régression —
   `default` a zéro droit par construction, la matrice ne lui donne aucun tool — mais la
   phrase du journal affirmait le contraire et est corrigée ici.
2. **Le correctif déborde légèrement du strict `_outcome`** : la prose du rapport a été
   touchée parce que le laisser contredire son propre CSV n'était pas tenable. Décidé et
   assumé, mentionné pour n'avoir pas à être reconstitué.
3. `ruff` et `mypy` verts sur `eval_perimeter.py`. `make lint` reste rouge sur les **trois
   mêmes** erreurs préexistantes.

### Points ouverts — les constats de revue non traités

| # | Où | Quoi |
|---|---|---|
| 3 | `eval_perimeter.py:62` | `threshold_on_forbidden` absent de `_CSV_FIELDS`, jeté en silence par `extrasaction="ignore"` : la métrique en gras de chaque tableau n'est pas auditable depuis le CSV publié |
| 2 | `eval_perimeter.py:249` | `r["returned"] < 5` en littéral au lieu de `settings.search_top_k` ; avec `SEARCH_TOP_K=10` tous les profils publieraient `0 / 30` sous un en-tête « top-5 ». Idem pour les `30` codés en dur (`:226`, `:255`) |
| 4 | `eval_perimeter.py:242` | Prose figée restante : la ventilation « 6 `procedure_sav`, 3 `notice` et 4 `fiche_technique` ». Vraie aujourd'hui, du même bois que celle qui vient de casser |
| 5 | `eval/protocole-mesure.md:179` | L'axe 3 y décrit **trois** profils dont un témoin ; le code en joue **quatre** avec deux témoins depuis `cc40220`. Le document normatif n'a pas suivi le code qu'il gouverne |
| 6 | `packages/agent/api.py:5` | Docstring « sans effet sur la recherche documentaire, inchangée » — faux depuis `49e216c`. Le jumeau de `web_client/app.py` a été corrigé, pas celui-ci |
| 7 | `packages/agent/cli.py:143` | `status == "ok"` avec `hits == []` rend `""` au modèle, sans message ni refus. Nouvellement atteignable : un `doc_type` de `matrice.yaml` absent du corpus passe le test de vacuité de `perimeter_for`, construit un `where` valide, et ne remonte rien |
| 8 | `check_perimeter.py:153` | `edition_ids` passé deux fois dans le `zip`, le second lié à `_`. Sans effet, mais imite la forme de `LexicalIndex.search` où le second opérande est `scores` |
| 9 | `Makefile:56` | La cible `mesure` n'agrège pas `mesure-perimetre` : le point d'entrée « rejouer toutes les mesures publiées » saute l'axe 3, le seul dont le rapport est régénéré de zéro et donc le plus exposé à la dérive |

---

## 2026-09-04 — Chantier 3, étape 1 : la réponse devient déterministe, et le journal existe

**Le jet précédent est mis de côté**, commit `78933ed` sur la branche `mcp`. Il attaquait le
serveur MCP, l'enveloppe partagée, le journal, le RAG et le SQL d'un seul mouvement et n'a
pas satisfait la revue. On repart de `dev` sur `mcp-second-try`, **côté Text-to-SQL
seulement** : deux couches posées et vérifiées avant de les étendre au RAG, puis au serveur.

### Le défaut réel : la forme était déterministe, l'énoncé ne l'était pas

Le point de départ était une question de l'utilisatrice — *« c'est le LLM du Text-to-SQL qui
construit la réponse ? »* — et la réponse était non, à la lettre : `envelope()`
(`tools.py:85`) était dix lignes de Python et `_STATUS_BY_CODE` un dictionnaire figé. Mais
l'intuition portait, et la lecture du code l'a chiffrée. Le champ `message`, lui, était
**écrit par le modèle** en quatre endroits :

| Site | Ce qui devenait le `message` |
|---|---|
| `tools.py:185`, `:188` | `generation.reason` sur `ecriture_refusee` et `hors_schema` — le texte rédigé par le modèle (`generator.py:137`, champ `explication` de son JSON) |
| `tools.py:191` | `generation.question` sur `clarification`, et `generation.axes`, ses chaînes libres |
| `tools.py:179`, `:173` | le message brut d'une exception du SDK Azure, puis d'un `RuntimeError` |
| `executor.py:141,143`, `validator.py:317` | le texte natif de `sqlite3`, concaténé |

Conséquence : **la même demande d'écriture refusée deux fois produisait deux phrases
différentes**, et le LLM de chat de `packages/agent` en produisait une troisième en
reformulant. La décision ne variait pas ; son énoncé, si. Le remède n'est pas de mieux
instruire le modèle, c'est de **ne plus lui donner la parole sur ce point** : une phrase
figée ne se reformule pas.

S'y ajoutaient deux fuites vraies, l'une potentielle et l'autre déjà en service :

- `RuntimeError("base absente : …")` levée par `executor._connect()` n'était attrapée
  **nulle part** le long de `validate() → explain()/execute() → ask_database()` ;
- `packages/agent/api.py:81` renvoyait `str(exc)` au front, que `web_client/app.py:130`
  affichait tel quel — un message d'exception de SDK sous les yeux d'un agent du support.

### Un objet, deux vues

Le nom `envelope` ne survit pas, sur demande : la fonction devient
`build_db_structured_answer()` et l'objet un `db_structured_answer`. Les **trois clés du
contrat DSI ne changent pas** — `status`, `payload`, `message` conviennent, et la suite
d'acceptance les lit.

`packages/text_to_sql_factory/structured_answer.py` porte la dataclass figée
`DbStructuredAnswer`. Trois de ses champs ne sortent **jamais** vers un client :

| Champ | Contenu | Lecteur |
|---|---|---|
| `cause` | texte du modèle, message SQLite, `str(exc)` | journal |
| `stack` | `traceback.format_exc()` | journal |
| `forbidden` | les colonnes fermées, en `table.colonne` | journal |
| `etage` | 3 matrice/AST · 2 droit au tool · `None` hors décision d'accès | journal |

**La garantie est structurelle, pas conventionnelle.** Ce sont des attributs de dataclass,
jamais des clés de dictionnaire : un `json.dumps` distrait sur l'objet échoue, il ne fuit
pas. Le seul sérialiseur est `client_view()`, et il filtre le payload sur **liste blanche** —
ce qui n'est pas explicitement conservé ne part pas, y compris une clé ajoutée demain sans y
penser. Sur les quatre refus et sur `erreur_execution`, le payload est réduit à `{"code"}`.

`CLIENT_MESSAGES` tient une phrase par code, et aucune ne nomme une table, une colonne, un
tool ni un code. Trois familles, parce que le recours de l'utilisateur diffère : *je n'ai pas
le droit* → demander une habilitation ; *il n'y en a pas* → reformuler ; *ça n'a pas marché*
→ corriger, ou réessayer. Les confondre supprimerait le recours avec la distinction.

### Deux décisions à l'intérieur, qui méritent d'être retrouvées

**1. `erreur_execution` a deux phrases, et ce n'est pas une entorse.** Le code recouvre deux
situations que l'utilisateur ne vit pas pareil : l'appel était mal formé (il peut corriger)
ou le service a échoué (il ne peut qu'attendre). Le catalogue n'a pas de code pour la
première — arbitrage déjà consigné plus haut — mais leur donner le même message ferait
réessayer indéfiniment la même référence invalide. D'où `MALFORMED_ARGUMENT`, une clé de
message qui n'est pas un code, dans un ensemble **fermé** : la variation reste choisie par
le code, jamais rédigée par le modèle.

**2. Les `axes` de `clarification` sont désormais ceux du code.** `clarification_axes()`
(`generator.py:104`) les calcule depuis la matrice et les filtre par profil ; le modèle en
rendait sa propre version en chaînes libres. C'était le seul code où le payload accompagne
encore la phrase, donc le seul endroit où le déterminisme pouvait se perdre par le payload.

### Le point de passage unique

`packages/text_to_sql_factory/handler.py` fait trois choses, **et l'ordre est la
garantie** : appeler le tool sous `except Exception`, journaliser l'objet **entier**, rendre
la vue client. Journaliser après la purge effacerait la cause pour tout le monde, débug
compris.

**L'étage 2 est exercé ici, pour la première fois.** `authorize()` avait été écrit au
chantier précédent et n'était appelé par personne — le Text-to-SQL n'avait pas de client à
qui refuser. Le handler en a un : un tool hors matrice produit un `tool_interdit` avant tout
travail, sans aller-retour au modèle. Les fonctions de `tools.py` restent inchangées :
appelées en direct — par `check_sql` — elles ne connaissent toujours que l'étage 3.

### Le journal

`packages/journal.py`, à la racine comme `packages/access.py` : **transverse aux huit
tools**, et c'était la raison même de son report du chantier 2. Une ligne JSONL par appel,
servi comme refusé, en ajout, vers `settings.gateway_journal` — `GATEWAY_JOURNAL`, défaut
`logs/journal.jsonl`, tel que le contrat d'intégration le fixait depuis le début et que le
code ne l'implémentait pas encore.

L'entrée porte les six champs du cadrage (`timestamp`, `profile`, `tool`, `arguments`,
`status`, `message`) puis ceux de la conception : `code`, `decision`, `etage`, `sql`,
`n_rows`, `latency_ms`, `forbidden`, `cause`, `client_message`, `stack`.

Deux choix à retrouver :

- **`message` porte la cause**, pas la phrase figée : ce lecteur-ci veut le pourquoi. Ce que
  l'utilisateur a réellement lu est conservé à côté sous `client_message` — sans quoi un
  signalement (« on m'a affiché ceci ») serait impossible à raccorder à son appel ;
- **`Journalable` est un `Protocol`**, pas un import du paquet SQL. Importer
  `DbStructuredAnswer` ici inverserait la dépendance et obligerait le RAG à passer par le
  SQL pour journaliser. Tous ses membres sont des propriétés en lecture seule : ce module
  lit une réponse, il n'en construit ni n'en modifie aucune.

`n_rows` et `latency_ms` **quittent la vue client** : c'est du diagnostic, le cadrage ne
prévoit que `sql`, `columns`, `rows`, et `eval_sql` les lit sur le retour du **tool**, pas
sur la vue purgée. La séparation des deux vues paie ici sans rien coûter.

### La lecture du journal, et son garde-fou

`read_feedback()` est l'autre moitié : sans lecture, le journal ne se consulte qu'en se
connectant à la machine, et les équipes métier n'en tirent rien. Il est **réservé au profil
`admin`**, et le garde-fou passe par `authorize()` — pas par un `if profile == "admin"` : la
règle appartient à la matrice, où elle se lit en face du profil qui la porte. `matrice.yaml`
gagne donc une neuvième ligne à `admin` seul, `read_journal`, nommée dans
`settings.journal_reader_tool`.

Les entrées sont rendues **entières**, trace comprise. C'est assumé : ce n'est pas une
commodité d'affichage mais la surface de débug, et l'expurger la rendrait inutile à ce pour
quoi elle existe. **Sa protection est son droit d'accès, pas son contenu.** Et la tentative
de lecture est elle-même journalisée, refusée comme accordée : qui a cherché à lire le
journal est précisément ce qu'une revue de conformité veut voir.

### Le dernier mètre : le LLM n'a pas le mot final sur un refus

C'est là que le déterminisme se perdait encore. Les quatre tools de `packages/agent/cli.py`
rendent une chaîne au LLM, qui la reformule avant l'écran. Chaque appel dépose maintenant sa
vue client dans le **carnet de l'appel en cours** (`call_record()`, une `ContextVar` — l'agent
est mis en cache et partagé entre requêtes, le carnet appartient à *un* appel) ; `api.py` y
relit `frozen_text()` et rend la phrase **telle quelle**, sans repasser par le modèle. Le
premier verdict non-`ok` gagne, et il gagne sur une réponse par ailleurs réussie : afficher
le texte rédigé masquerait un refus survenu en chemin. La boucle CLI applique la même règle,
sinon les deux interfaces n'afficheraient pas la même chose pour la même décision.

`api.py` perd son `str(exc)` : la trace part au journal sous le tool `chat`, l'écran reçoit
une phrase figée. Un rôle inconnu n'est plus renvoyé en écho. `web_client/app.py` gagne la
commande `journal`, qui affiche les vingt dernières entrées — ou le refus que la matrice
oppose au rôle, sous la même forme que n'importe quelle autre réponse. **Aucun contrôle de
droits n'est doublé côté interface** : deux barrières à maintenir dont une seule journalisée
serait pire qu'une.

### Écart corrigé au passage, parce qu'il devenait bloquant

`get_schema` était accordé à `support` dans `matrice.yaml` alors que T9, T10 et T12 attendent
un `refused` — divergence déjà consignée dans le tableau d'arbitrages de ce journal, avec sa
résolution (« à retirer à `support` »). Elle était sans effet tant que rien n'exerçait
l'étage 2 ; le handler l'exerce, donc la matrice devait dire la même chose que les tests.
Retiré, avec le motif écrit en face : le support lit des **données**, il n'a pas à lire la
**forme** de la base — décrire une colonne à qui ne doit pas la lire, c'est déjà en publier
l'existence, le même motif que pour `dev`.

### Vérification

`make check-feedback` → `packages/text_to_sql_factory/check_feedback.py`, **102 contrôles
déterministes, aucun appel de modèle**, journal écrit dans un répertoire temporaire. Ce
qu'ils établissent, et pourquoi chacun compte :

1. **Forme** — pour chacun des neuf codes, la vue client rend exactement les trois clés du
   DSI, sur un payload volontairement trop riche : on vérifie que la liste blanche *coupe*,
   pas que le tool a bien fait de ne rien mettre ;
2. **Étanchéité** — la recherche porte sur la **sous-chaîne** dans le JSON servi, pas sur
   l'absence de clé : une fuite par concaténation serait invisible à un contrôle de clés ;
3. **Déterminisme** — quatre appels identiques, une seule réponse, sur le refus rédigé par
   le modèle comme sur trois chemins sans modèle ;
4. **Complétude** — tout code a sa phrase, et tout statut autre que `ok` a un message. Sans
   ce contrôle, un code ajouté demain tomberait en silence sur le repli ;
5. **Filet** — un tool remplacé par un tool qui explose : `status: error`, rien de la pile au
   client, `Traceback` entier au journal ;
6. **Journal** — une ligne par appel, dans l'ordre, `etage` posé sur la seule décision
   d'accès (`[None, 2, None, None]` sur quatre appels choisis), et la cause du modèle
   présente au journal **et** absente de la vue client — les deux moitiés du même appel,
   vérifiées ensemble ;
7. **Garde-fou** — `support` refusé, `admin` servi entier, et les deux tentatives au journal.

Non-régression : `make check-sql` **81/81** au vert, `make eval-sql` **24/24 conformes**.
`ruff` vert ; `make lint` reste rouge sur les **trois mêmes** erreurs préexistantes.
`make test` ne passe toujours pas — `mcp_server.server` n'existe pas — mais **T2 devient
satisfaisable** : le journal qu'il relit existe désormais, il ne manque plus que le serveur
pour l'appeler.

### Écarts et points ouverts

1. **Le format attendu d'un argument malformé n'est plus dit au client.** « référence
   attendue au format REF-NNNN, reçu « … » » devient « La demande n'est pas au format
   attendu. » La distinction *corriger / attendre* est préservée par
   `MALFORMED_ARGUMENT`, mais le format lui-même part au journal. Assumé : l'`inputSchema`
   MCP écartera l'appel en amont au chantier suivant.
2. **Le RAG n'est pas couvert**, et c'était le périmètre décidé. `search_docs` garde son
   étage 2 local dans `cli.py` (`_denied_docs`, texte brut) et ses messages de refus écrits
   par `access_rag` ; le point ouvert n°7 de la revue précédente (`status == "ok"` avec
   `hits == []`) n'est pas traité. La couche leur sera étendue à l'étape suivante.
3. **`etage` reste `None` sur un refus décidé par le modèle** (`hors_schema`,
   `ecriture_refusee` avant l'AST). C'est délibéré : le modèle n'est pas une barrière, et lui
   attribuer un étage rendrait la défense en profondeur fausse à la lecture du journal.
   **En revanche le `None` sur un succès est un autre sujet, et c'en est un défaut** : il
   confond « toutes les couches franchies » et « aucune décision d'accès en jeu ». Traité par
   l'entrée « Piste à instruire : quelle couche a bloqué la chaîne de réponse », plus bas.
4. **Aucune politique de rétention**, aucun `trace_id`. Vide documentaire réel — ni le
   cadrage ni la conception n'en parlent — et non un oubli d'implémentation. Le journal est
   append-only, sans rotation : à trancher avant toute mise en service.
5. **`packages/agent/api.py:5`** (point ouvert n°6 de la revue précédente) reste faux et
   n'est pas corrigé ici ; la docstring a été augmentée sans que cette phrase soit reprise.

---

## 2026-09-04 — Piste à instruire : quelle couche a bloqué la chaîne de réponse

**Idée de l'utilisatrice, formulée en testant la GUI, et à instruire à la fin du chantier 3**
— quand les huit tools passeront par la couche posée le même jour. Consignée ici parce qu'elle
touche un champ déjà écrit en seize endroits : la rétro-ajouter coûtera cher si le motif est
perdu.

### L'idée

Journaliser **quel point de contrôle a bloqué la chaîne de réponse**, `0` valant « réponse
servie, toutes les couches franchies ». Le succès devient une valeur **mesurée**, pas une
absence.

### Ce que ça corrige, et qui est un défaut réel d'aujourd'hui

`etage` vaut `None` **à la fois** quand tout est passé et quand aucune décision d'accès n'était
en jeu — le refus `hors_schema` décidé par le modèle. Deux faits très différents, une seule
valeur. Le point ouvert n°3 de l'entrée précédente reste vrai sur les refus du modèle, mais il
ne dit rien du succès : c'est cette moitié-là que la piste traite.

### Oignon ou pipeline — la précision qui rend la mesure honnête

Le mot « oignon » est plus généreux que ce qu'on a. Un oignon au sens strict suppose des
couches **concentriques et indépendantes gardant la même chose**. Ce qu'on a est surtout un
**pipeline** : chaque étage vérifie *autre chose* — droit au tool, périmètre, syntaxe,
ressources, divulgation — et franchir l'un ne dit rien de l'autre.

Mais **deux endroits sont de vrais oignons**, et ce sont eux qui portent la valeur du champ :

| Propriété | Gardée | Où |
|---|---|---|
| l'écriture | **trois fois** | le contrat l'interdit au modèle · contrôles 1 à 4 de l'AST · connexion `mode=ro` + `query_only` |
| les colonnes fermées | **deux fois** | la matrice filtre le contrat *avant* que le modèle le voie · contrôle 5b revérifie l'AST |

Un numéro de couche mesure la **progression** sur un pipeline et la **redondance** sur un
oignon. Ce ne sont pas les mêmes chiffres, et la mesure devra dire lequel elle publie.

### Que ça se fait, et sous quels noms

| Domaine | Ce qui est journalisé |
|---|---|
| WAF / IDS | l'**ID de règle** qui a bloqué, pas seulement « bloqué » |
| Envoy / Istio | `response_flags` + le filtre qui a refusé |
| IAM AWS | la **policy** qui a tranché, sur un refus comme sur un accord |
| Kubernetes | le nom du **webhook d'admission** qui a rejeté |
| OPA | le **chemin de politique** évalué |
| Aviation, médecine | modèle du **fromage suisse** (Reason, 1990) : des couches trouées, et l'intérêt est de savoir *laquelle* a rattrapé |
| Sûreté industrielle | **LOPA** — on compte les couches de protection indépendantes et leur probabilité de défaillance |

Usage opérationnel constant, et c'est là que le champ sert : **une couche qui ne se déclenche
jamais est soit redondante, soit non testée ; une couche qui se déclenche en dernier signifie
que tout l'amont a fui.**

### Deux réserves de conception, à ne pas perdre

1. **Nommer, pas numéroter.** Le refus du modèle (`hors_schema`, `ecriture_refusee` avant
   l'AST) n'est **pas** une barrière : il peut se tromper dans les deux sens. Lui donner un
   rang ferait mentir la profondeur. Donc un `blocked_at` sur un **ensemble fermé de points
   nommés**, le rang se dérivant de la position — on peut alors y ranger un point qui n'est
   pas une barrière sans corrompre le chiffre.
2. **Capter tôt, publier tard.** Le champ doit être posé **au moment où la couche est étendue
   au RAG**, pas après : les sites de construction de réponse sont déjà seize, et il y en aura
   le double avec les huit tools.

### La mesure à publier, et la question qu'elle répond

Sur les 24 questions de `make eval-sql` et les 81 contrôles de `make check-sql` : **quel point
de contrôle a décidé chaque refus.** Elle répond à une question que le dépôt ne sait pas
trancher aujourd'hui — **le contrôle 5b se déclenche-t-il une seule fois sur le chemin
nominal ?**

Il ne devrait pas : la matrice a filtré le contrat en amont, le modèle ne voit jamais la
colonne fermée. S'il ne se déclenche jamais, le constat se publie tel quel — *la profondeur
est réelle, mais le chemin normal ne la teste pas* — et c'est précisément pourquoi `check_sql`
lui consacre 21 cas écrits à la main.

### Où ça atterrira dans le code

- **le champ** : `etage` de `DbStructuredAnswer`
  (`packages/text_to_sql_factory/structured_answer.py`), à élargir ou à doubler d'un
  `blocked_at` ;
- **l'entrée de journal** : `entry_for()` dans `packages/journal.py` ;
- **les sites qui le posent** : les seize appels à `build_db_structured_answer()` de
  `packages/text_to_sql_factory/tools.py` et de `handler.py` ;
- **la mesure** : une cible Make dédiée, comme l'exige `eval/protocole-mesure.md` — une cible
  par mesure publiée, à lire **avant** d'écrire la moindre ligne d'évaluation.

---

## 2026-09-04 — Chantier MCP, incrément SQL : frontière typée et serveur stdio

### Décision

Le premier incrément MCP expose les quatre tools SQL, sans API HTTP intermédiaire et sans
routage sémantique dans la gateway. Le choix du tool reste celui du LLM client à partir du
catalogue MCP ; la gateway effectue le dispatch technique et le contrôle du profil.

La frontière interne est désormais une commande Python typée : `SqlToolRequest`. Elle est
transmise à `SqlToolLauncher`, qui vérifie de nouveau le couple profil/tool et les arguments
avant d'appeler la fonction SQL concernée. Le client ne peut pas fournir le profil ni une liste
de colonnes autorisées.

### Réalisation

- `packages/text_to_sql_factory/models.py` : commande `SqlToolRequest` ;
- `packages/text_to_sql_factory/sql_tool_launcher.py` : façade d'exécution gouvernée des
  tools SQL ;
- `mcp_server/server.py` : serveur FastMCP en stdio, catalogue filtré par profil, enveloppe
  DSI conservée en JSON texte ;
- `packages/journal.py` et `structured_answer.py` : champ `blocked_at`, dérivé de l'étage
  de blocage, avec `0` quand la chaîne est franchie ;
- `Makefile` : cibles SQL et feedback alignées sur `evals_and_controls/`.

### Vérification

`make check-feedback`, `make check-sql`, Ruff et la compilation Python passent. Un appel direct
à `get_schema` au profil `support` est refusé et journalisé, même si le tool n'apparaît pas
dans `tools/list`. Le profil `commercial` voit les quatre tools SQL.

Les quatre tools RAG et la suite d'acceptance MCP complète restent hors de cet incrément ; ils
seront branchés après création de leur handler transverse.

### Correctif de revue — 2026-09-04

La revue a relevé quatre points, corrigés sans changer le périmètre :

- `blocked_at` est désormais porté explicitement par `DbStructuredAnswer` : `0` pour une
  réponse servie, l'étage pour une décision de sécurité, `None` pour une panne ou un refus
  décidé par le modèle ;
- les schemas MCP portent les motifs `REF-NNNN` et `CMD-AAAA-NNNN`, en complément de la
  validation serveur qui reste obligatoire ;
- `SqlToolLauncher.launch()` utilise réellement les méthodes nommées des quatre tools ;
- le serveur conserve une instance configurée du launcher, tandis que `handle()` reste une
  compatibilité pour les appels internes et les tests à réglages personnalisés.

`make check-feedback`, `make check-sql`, Ruff et mypy restent au vert après ce correctif.

---

## 2026-09-06 — Chantier 3, étapes A et B : les quatre tools RAG, puis les huit au serveur

Le point de départ n'est pas une exigence du brief, c'est une gêne exprimée par
l'utilisatrice : *« le fait que le MCP ne soit pas sollicité par l'agent alors que tout est
en place côté SQL me chagrine »*. La gêne était fondée, et le diagnostic n'était pas celui
qu'on croyait.

### Ce que l'exploration a corrigé dans l'énoncé du problème

**Le serveur MCP existait déjà.** `mcp_server/server.py` (102 lignes, `3672f56`) servait les
quatre tools SQL, filtrait son catalogue par `authorize()`, et `make serve` / `make client`
fonctionnaient. `docs/flux-text-to-sql.md` — écrit la veille — le disait déjà : « les deux
façades convergent vers le handler, mais le frontend n'appelle pas le serveur MCP ».

Le défaut n'était donc pas l'absence de serveur, c'était que **le serveur ne servait que la
moitié du catalogue**. Six des douze tests d'acceptance appelaient `answer_question`,
`search_docs` ou `get_document` et échouaient sur un tool inconnu. Brancher l'agent sur ce
serveur-là lui aurait retiré le RAG : l'ordre s'imposait de lui-même — compléter le
catalogue d'abord, brancher l'agent ensuite.

Périmètre arrêté avec l'utilisatrice : **étapes A et B seulement**. Le branchement de
l'agent en client MCP et le front comparatif par rôle attendent les feux verts.

### A1 — une couche de réponse parallèle, cousue par le protocole

Le choix structurant est de **ne pas** généraliser `DbStructuredAnswer`. Trois raisons, dont
la troisième est la vraie :

* les deux domaines n'ont pas les mêmes codes — le SQL ignore `hors_corpus` et
  `contexte_insuffisant`, le RAG ignore `ecriture_refusee`, `hors_schema` et
  `clarification`. Une table commune aurait été une union dont chaque moitié ne vaut que
  pour un domaine ;
* le SQL est vert sur 183 contrôles déterministes, qu'un refactor aurait touchés pour un
  besoin qui n'est pas le sien ;
* **la couture nécessaire existait déjà**, et elle avait été écrite pour ça. Le protocole
  `Journalable` de `packages/journal.py:34` porte en toutes lettres : « le paquet SQL le
  satisfait aujourd'hui, le RAG le satisfera demain, et ce module n'a besoin d'importer ni
  l'un ni l'autre ». `RagStructuredAnswer` honore cette phrase. Un seul journal, un seul
  format d'entrée, deux domaines qui l'alimentent sans se connaître.

Deux décisions de table méritent d'être consignées, parce que ni l'une ni l'autre n'est
évidente :

**`contexte_insuffisant` partage le statut `hors_corpus` sans partager son code.** Le
contrat DSI n'a que cinq statuts et n'en offre pas un sixième pour séparer « je n'ai rien
trouvé » de « j'ai trouvé, ça ne répond pas ». Le *code* les distingue, lui, dans le payload
et au journal — et c'est le code que la mesure exploitera. Le statut n'a qu'un travail :
empêcher le client de rendre une non-réponse comme une réponse.

**Ni `hors_corpus` ni `contexte_insuffisant` ne sont des refus.** C'est le piège le plus
facile de ce module, et il a son contrôle dédié : les compter dans `REFUSAL_CODES` ferait
dire `denied` au journal sur des non-réponses documentaires, et le taux de refus d'E5
deviendrait illisible. Les deux seuls refus du domaine sont `tool_interdit` (étage 2) et
`perimetre_interdit` (étage 3).

**`blocked_at` a été posé en même temps que la couche, pas après.** C'est exactement ce que
l'entrée « Piste à instruire » du 2026-09-04 exigeait — « capter tôt, publier tard », parce
que « les sites de construction de réponse sont déjà seize, et il y en aura le double avec
les huit tools ». Ils sont désormais trente et un, tous instrumentés dès l'écriture. Reste
ouvert, comme prévu : la réserve « nommer, pas numéroter » et la cible Make de mesure.

### A3 — ce que le jet mis de côté servait au client, et qu'il ne fallait pas

Le brouillon `78933ed` portait déjà les quatre tools, en bon état de marche. Il a été relu,
pas recopié : il écrivait sur l'ancienne `envelope()`, et surtout il passait des **textes
calculés** au client —

```python
envelope(_FORBIDDEN_PERIMETER,
         "collection non ouverte à ce profil : " + ", ".join(closed))
```

— c'est-à-dire qu'il **nommait à l'utilisateur exactement ce que la matrice lui ferme**. En
sondant collection par collection, on cartographiait la matrice : le refus devenait un
oracle. C'est le même défaut que celui corrigé côté SQL deux jours plus tôt, sous une autre
forme : là le texte venait du modèle, ici il venait du code, mais dans les deux cas il
variait avec ce qu'il ne devait pas révéler. Ces textes existent toujours — ils partent en
`cause` et en `forbidden`, vers le journal, où le lecteur est humain et habilité.

### B — le serveur, et le seul étage que ce fichier ajoute

Les huit tools sont enregistrés, avec un aiguillage par domaine vers les deux handlers.
`mcp_server/server.py` ne décide rien : l'étage 2 et la journalisation vivent dans les
handlers, l'étage 3 dans les tools. La seule chose que ce fichier ajoute à la chaîne, c'est
**l'étage 1** — le catalogue que le client voit — et sa docstring dit désormais qu'il n'est
pas une sécurité : un client peut appeler un tool qu'il n'a pas listé, et c'est l'étage 2
qui le refuse *et* le journalise.

**L'import du handler RAG est local aux fonctions de tool, et c'est une contrainte de
protocole.** `conftest.py` borne `initialize` à trente secondes ; un import au niveau du
module chargerait l'embedder et le reranker avant la première poignée de main. Mesuré : le
premier appel de recherche coûte 8,2 s, les suivants sont immédiats — la latence est payée
au premier appel, jamais à la connexion.

`mcp_server/__main__.py` ajoute la forme courte `python -m mcp_server`, celle que nomment
`note-transport.md` §7 et l'exemple de configuration client de `Q3` §2. La forme longue du
cadrage reste valide et reste celle que lance la suite d'acceptance.

### Le résultat : `make test` passe, pour la première fois du projet

```
tests/acceptance/test_mcp.py ....    tests/acceptance/test_rag.py ....
tests/acceptance/test_sql.py ....    12 passed in 47.06s
```

Deux effets attendus se sont confirmés sans code défensif :

* `test_matrice_d_acces_respectee` échouait parce qu'un tool inconnu rendait
  `erreur_execution` → `error` au lieu de `refused`. Les huit tools enregistrés, tout tool
  hors matrice **existe**, et c'est `authorize()` qui tranche → `tool_interdit` → `refused` ;
* les catalogues servis correspondent exactement à `TOOLS_BY_PROFILE` du conftest —
  `support` 7 tools sans `get_schema`, `commercial` 8. Vérifié aussi hors suite : `dev` 5,
  `default` 0.

T2 (« une demande d'écriture est refusée **et journalisée** ») n'est plus seulement
satisfaisable : il est satisfait.

`make check-rag-tools` : **62 contrôles déterministes**, tous au vert. `make check-sql`
(81), `make check-feedback` (102) et `make check-perimetre` (31) sont inchangés — c'est la
preuve que la couche RAG n'a rien cassé de ce qui l'était déjà.

### Un contrôle qui s'est trompé lui-même, et ce qu'on en a gardé

En écrivant `check_rag_tools.py`, un contrôle a lu `granted["status"] == "ok"` pour vérifier
qu'un document était bien servi — et il est passé sur un document **introuvable**, qui
partage ce statut. Le mapping n'était pas en cause : `introuvable` est un constat d'absence,
pas une panne, et en faire une `error` ferait compter au journal des échecs qui n'ont pas eu
lieu — même arbitrage qu'`aucune_ligne` côté SQL. Ce qui protège le client, c'est que la clé
`text` est absente : il n'a rien à afficher. Le contrôle a été réécrit pour nommer ce qu'il
vérifie — le **code**, pas le statut — et un contrôle explicite a été ajouté sur la
distinction. L'incident est consigné parce qu'il montre où le mapping se lit mal, ce qui est
une information sur la couche, pas seulement sur le contrôle.

### Écarts décidés, à ne pas re-débattre

| Écart | Décision |
|---|---|
| `search_docs(query)` / `get_document(doc_id)` contre `search_docs(question)` / `get_document(doc_key)` de `03-catalogue-tools.md` | **Le test fait foi** (règle d'arbitrage du dépôt). Les noms suivent `tests/acceptance/` |
| Transport Streamable HTTP, `annuaire.yaml`, `resolve_profil(ctx)` par appel | Hors périmètre. Ils supposent une identité de client, hors sujet pour une démonstration à un processus par profil |
| Le seuil de refus dans le flux agent → API → Chainlit | Toujours ouvert. Il est branché dans `answer_question` côté MCP, pas dans le `search_docs` du banc d'essai |
| Cible Make de mesure de `blocked_at` | À écrire quand les huit tools auront tourné, comme prévu |

### Points ouverts que cette étape ne referme pas

* **Le profil reste déclaré par le client dans le banc d'essai.** L'agent LangChain appelle
  toujours `handle()` en direct : les deux façades restent parallèles. C'est l'étape
  suivante, et c'est elle qui fera tomber l'écart.
* **Point n°7 de la revue du 2026-09-04** (`agent/cli.py:143`, `status == "ok"` avec
  `hits == []`) : non traité, et il appartient au chemin de l'agent, pas à celui du serveur.
* **`make lint` a été réparé, et redevient rouge pour la bonne raison.** Il faisait
  `mypy packages sql mcp_server` alors que `sql/__init__.py` est supprimé : mypy s'arrêtait
  sur `cannot read file 'sql'` **avant de vérifier quoi que ce soit**. Le lint ne lintait
  donc plus rien — une cible verte-par-accident aurait été pire, mais celle-ci était muette.
  `sql` retiré du Makefile et `sql*` de l'`include` de `pyproject.toml` (celui-ci purement
  cosmétique : le glob ne correspondait à rien et n'émettait pas d'erreur). `make lint`
  vérifie de nouveau ses 50 fichiers et rend les **trois erreurs préexistantes** connues
  (Chainlit ×2, `IncludeEnum`). Aucune dette neuve : `ruff check` passe sur tout le code
  ajouté.
  Vérifié au passage : `include = ["packages*", …]` couvre déjà tous les sous-paquets — le
  `*` de fnmatch matche aussi les points — donc `rag_machines` et `text_to_sql_factory`
  n'avaient rien à y ajouter. En revanche les deux dossiers `evals_and_controls` n'avaient
  pas d'`__init__.py` : ils n'étaient **pas empaquetés** et ne fonctionnaient qu'en PEP 420,
  depuis la racine du dépôt. Sans effet en développement — ce sont des outils, jamais
  importés par le code servi — mais un `pip install` du projet ne les aurait pas emportés,
  et les cibles `make check-*` auraient échoué sur une installation. Les deux `__init__.py`
  ont été ajoutés, avec la table des modules de chaque dossier en docstring : setuptools
  trouve désormais dix paquets au lieu de huit, et `mypy` en vérifie 52 fichiers au lieu de
  50, toujours sur les mêmes trois erreurs.
* **Le contournement `literalai`** doit être rejoué après chaque `uv sync` : le paquet
  installe son propre `tests/` à la racine de `site-packages`, qui masque celui du dépôt et
  empêche pytest de collecter. Il a été écarté par renommage, pas par suppression.

## 2026-09-06 — Chantier 3, étape C : l'agent du banc d'essai devient client MCP

L'étape précédente s'était arrêtée sur une phrase : « le profil reste déclaré par le
client dans le banc d'essai. L'agent LangChain appelle toujours `handle()` en direct :
les deux façades restent parallèles. C'est l'étape suivante, et c'est elle qui fera
tomber l'écart. » C'est fait. `packages/agent/` n'appelle plus ni `handle()`, ni
`handle_request()`, ni `search_for_profile()` — vérifiable par `grep`, et c'est la
condition d'arrêt qu'on s'était donnée.

### Le prérequis que la revue de code a fait apparaître

La revue de `1c97113` a relevé que `search()` fait `embedder or build_embedder(settings)`
(`retrieval/search.py:375`) et `build_reranker(settings)` (`:389`), et qu'**aucun des deux
builders n'est mémoïsé** — contrairement à l'index BM25, `lru_cache`é dans `lexical.py`.
`LocalEmbedder` et `LocalReranker` chargent leur modèle paresseusement, mais **par
instance** : une instance neuve à chaque appel, c'est un chargement à chaque appel.

Le constat intéressant n'est pas le cache manquant, c'est **pourquoi personne ne l'avait
vu**. La suite d'acceptance relance un processus serveur par appel : elle ne peut pas
distinguer un coût de démarrage d'un coût par appel, les deux se confondent chez elle.
Le chiffre « 8,2 s au premier appel, immédiat ensuite » publié à l'étape B décrivait donc
un comportement que le code ne tenait pas dans un serveur qui vit. Mesuré, trois
recherches d'affilée dans un même processus :

| | appel 1 | appel 2 | appel 3 |
|---|---|---|---|
| avant (cache vidé entre les appels) | 5,00 s | 4,22 s | 3,77 s |
| après | 5,35 s | **0,16 s** | **0,16 s** |

Le branchement rendait ce défaut bloquant : il repose sur **un processus serveur gardé
vivant par profil**, et `answer_question` (embedding + rerank + complétion Azure) aurait
dépassé le `CALL_TIMEOUT` de 30 s. Le correctif tient en deux `@lru_cache`, posés sur les
seuls champs lus de `Settings` — qui n'est pas hachable, et dont on ne veut pas faire une
clé de cache implicite.

**Ce que ça dit sur la mesure**, au-delà du correctif : un banc de test qui isole chaque
appel dans son processus ne mesure jamais ce que coûte le deuxième. C'est le genre de
biais que `eval/protocole-mesure.md` cherche à nommer.

### Le lien client : `packages/agent/gateway.py`

Un module neuf, et **le seul endroit du code servi qui parle le protocole MCP**. Il ferme
au passage la duplication qui s'installait entre `scripts/mcp_client.py` et
`tests/conftest.py` — sans toucher à `tests/`, gelé par convention du dépôt.

Trois pièces :

* `gateway_session(profile)` lance `python -m mcp_server.server` en sous-processus avec
  `SORABEL_PROFILE=<profil>` et `cwd` **explicite** sur la racine du dépôt. Le `cwd` n'est
  pas cosmétique : `logs/journal.jsonl` est relatif, et un répertoire différent aurait créé
  un second journal au lieu d'alimenter celui que `make journal` lit ;
* `GatewayRegistry` tient une session par profil pour l'API. **Chaque session est ouverte
  et fermée dans une tâche à elle**, et c'est une contrainte, pas un style : `stdio_client`
  ouvre un groupe de tâches anyio dont la portée d'annulation doit être quittée par la
  tâche qui l'a entrée. Un `AsyncExitStack` partagé — entré dans une requête, fermé au
  `lifespan` — lève une erreur au moment précis où l'on cherche à ranger proprement. La
  tâche gardienne ouvre, publie la session, puis attend le signal d'arrêt ;
* `build_tools(gateway, render)` adapte le catalogue en tools LangChain. **Adaptateur
  maison, ~30 lignes, aucune dépendance ajoutée** : `StructuredTool` accepte un
  `args_schema` sous forme de dictionnaire JSON Schema (`langchain_core/tools/base.py:584`
  et `:614`), donc l'`inputSchema` du serveur passe tel quel — le `pattern`
  `^REF-\d{4}$` de `check_stock` compris, vérifié. `langchain-mcp-adapters` aurait fait le
  travail en une ligne, mais aurait mis une boîte noire à l'endroit exact où la
  démonstration doit être lisible, et modifié `pyproject.toml` sans nécessité.

`render` est le seul point d'extension : `gateway.py` ne connaît que le protocole, et
c'est `cli.py` qui décide ce qu'un modèle a le droit de voir d'une enveloppe.

### Ce que le branchement apporte sans qu'on l'ait codé

**Le catalogue n'est plus en dur.** Les tools de l'agent sont ceux que `tools/list` rend,
donc filtrés par `authorize()` côté serveur. Vérifié, les cinq profils :

```
support     7  answer_question, ask_database, check_stock, get_document, list_sources, order_status, search_docs
commercial  8  (+ get_schema)
dev         5  answer_question, get_document, get_schema, list_sources, search_docs
admin       8
default     0  (vide)
```

L'étage 1 était écrit depuis l'étape B, mais **rien du banc d'essai ne l'exerçait**.

**Les quatre tools documentaires passent enfin par leur handler.** Le `search_docs` local
appelait `search_for_profile()` et portait son étage 2 en dur (`_denied_docs`) : il
court-circuitait l'étage 2, le seuil de refus **et** la journalisation. Les trois tombent
d'un coup. L'écart n°3 du tableau de l'étape B — « le seuil de refus dans le flux agent →
API → Chainlit, toujours ouvert » — est refermé : question hors corpus posée à `support`,
réponse « Le corpus documentaire ne couvre pas cette question. », entrée au journal avec
`code: hors_corpus`, `blocked_at: null` (ce n'est pas un refus, conformément à l'arbitrage
de l'étape A).

Le **point n°7 de la revue du 2026-09-04** (`status == "ok"` avec `hits == []`) disparaît
avec le code qui le portait.

### Le défaut que le branchement a introduit, et qu'il fallait corriger

Un catalogue vide ne rend pas un modèle muet. Premier essai sous `sans_role` :

> « Je vais interroger la base pour compter les commandes d'avril 2024. »

Il annonçait une action qu'il ne pouvait pas faire. Il ne mentait pas **avant** le
branchement, parce que le tool existait alors pour se faire refuser et rendre sa phrase
figée. Le catalogue filtré supprime l'appel *et* le refus qui l'accompagnait ; la phrase,
elle, doit rester. `build_agent()` rend donc `None` sur un catalogue vide, et la CLI comme
l'API rendent `EMPTY_CATALOGUE` — la même phrase figée que l'étage 2 aurait prononcée.

**Effet de bord à consigner** : un profil sans aucun tool ne produit plus d'entrée au
journal, puisqu'aucun appel n'a lieu. Ce n'est pas une perte de traçabilité — c'est
exactement ce que dit `03-catalogue-tools.md` §3 de l'étage 1 (« le LLM ne voit pas ce
qu'il n'a pas le droit d'appeler, donc il ne l'essaie pas ») — mais E5 ne comptera plus
ces tentatives-là. Tout tool appelé hors catalogue reste refusé **et** journalisé par
l'étage 2, ce que la suite d'acceptance vérifie en appelant directement.

### L'API : le rôle choisit un processus, plus un argument

`profile_for_role()` n'a pas bougé d'une ligne. Ce qui a changé, c'est ce qu'on fait de son
résultat : il désigne désormais **quel sous-processus** on interroge. Le `@lru_cache` sur
`_agent_for` devient un dictionnaire — l'agent est lié à une session — et son commentaire
sur la fuite de droits entre rôles reste valable mot pour mot, avec une garantie de plus :
la séparation est maintenant **doublée** par celle des processus. `POST /chat` passe en
`async`, `agent.invoke` en `await agent.ainvoke`, et un `lifespan` ferme les sessions —
sans quoi arrêter l'API laisserait derrière elle autant de serveurs MCP que de rôles
utilisés, chacun tenant son embedder en mémoire. Vérifié : arrêt propre, aucune erreur de
portée d'annulation.

`GET /journal` et `/journal/allowed` ne changent pas : le journal se lit sur le système de
fichiers, pas par le protocole.

### Écarts décidés, à ne pas re-débattre

| Écart | Décision |
|---|---|
| `--strategy` disparaît de la CLI, `strategy` de `ChatRequest` | **Conséquence du protocole, pas un choix** : les tools MCP n'exposent pas d'étage de recherche. Le serveur décide, avec la configuration que la mesure a réglée (hybride). Comparer les étages reste possible par `make mesure-*`, qui est l'endroit prévu pour ça |
| Un profil à zéro tool ne journalise plus ses tentatives | Assumé, cf. ci-dessus. C'est le sens de l'étage 1 |
| Les descriptions de tools ne sont plus dans `cli.py` | Elles viennent du serveur. Deux copies auraient divergé, et c'est le serveur qui fait autorité sur l'aiguillage |
| Le prompt système reste dans `cli.py` | Il n'appartient pas au catalogue : c'est la consigne du client, pas celle de la gateway |

### Points ouverts que cette étape ne referme pas

* **Le front Chainlit splitté par rôle** — l'étape suivante. `packages/web_client/app.py`
  n'a pas été touché : il parle à l'API en HTTP (`{role, question}`) et bénéficie du
  branchement sans le voir. Vérifié au niveau du contrat qu'ils partagent, pas au
  navigateur ;
* **La cible Make de mesure de `blocked_at`** — toujours à écrire. Les huit tools tournent
  désormais dans le flux réel, donc la matière existe ;
* **« Nommer, pas numéroter »** — la réserve posée le 2026-09-04 sur `blocked_at` ;
* Les six autres constats de la revue de `1c97113` : métadonnées `url` rendues au client
  par `get_document`, `classify()` qui décide sur un chemin non normalisé, le repli
  `or [result.hits[0]]` de `answer_question`, `journal.record()` hors du `try` des deux
  handlers, `check_rag_tools` qui s'interrompt au lieu de rapporter, et
  `docs/archives/flux-text-to-sql.md` qui documente `_json_result` renommé `_sql_result`.
  Aucun n'est sur le chemin de cette étape.

### Vérifications

`make test` **12/12** (46 s). `make check-sql` 81, `make check-feedback` 102,
`make check-rag-tools` 62, `make check-perimetre` 31 — tous inchangés. `make lint` : les
**trois** erreurs préexistantes (Chainlit ×2, `IncludeEnum`), sur 53 fichiers au lieu de
52. Journal relu après essais : une entrée par appel, `profile` égal à celui du
sous-processus, `blocked_at` renseigné (0 servi, 2 tool interdit, 3 périmètre, `null` hors
décision d'accès), et **un seul** `logs/journal.jsonl`.

## 2026-09-06 — Piste à instruire : passer d'un processus par profil à un service pour vingt utilisateurs

**Question de l'utilisatrice, posée juste après le branchement de l'étape C** : « dans la
vraie vie, comment ça fonctionnerait pour 20 utilisateurs ? On multiplierait comme ici ? »
Consignée parce que la réponse est **déjà écrite pour moitié** dans le dossier de conception
— `3-exposition-mcp-et-matrice-d-acces/note-transport.md` — et que l'autre moitié est un
constat neuf de cette session, qui n'apparaît nulle part ailleurs.

### Ce que le branchement multiplie aujourd'hui, et ce qu'il ne multiplie pas

`GatewayRegistry` indexe ses sessions **par profil**, jamais par session cliente ni par
requête : vingt utilisateurs répartis sur cinq rôles font cinq sous-processus, pas vingt.
Ce n'est donc pas le nombre d'utilisateurs qui met la forme actuelle en défaut.

Ce qui la met en défaut, c'est **stdio**, où « un serveur » veut dire *un binaire, N
processus* — un par poste. `note-transport.md` §1 le chiffre client par client, et le verdict
n'appelle pas de débat : le poste commercial tient, l'IDE des développeurs coûte cher (il
faut l'index Chroma **et PyTorch** sur chaque machine), le bot Slack **ne tient pas** — un
service partagé n'a nulle part où accrocher un profil par utilisateur. E4 dit « un même
serveur MCP sert tous les clients internes » ; à vingt postes, stdio ne le tient plus.

### Ce que la conception a déjà tranché — à ne pas re-débattre

* **Transport Streamable HTTP, un seul processus, N connexions.** Il n'y a *pas* d'arbitrage
  entre les deux transports : le catalogue est un objet enregistré une fois, et
  `run(transport=…)` n'est qu'un choix de flux. Les deux câblages cohabitent derrière le
  même point d'entrée (§2) ;
* **le profil est résolu par appel, jamais lu dans un en-tête.** Un `X-Sorabel-Profile`
  serait la panne que `Q3` §2 écarte, déplacée du LLM vers HTTP — le SDK porte
  l'avertissement en toutes lettres : *« headers are client-supplied input — never treat one
  as an identity assertion »*. Le profil se **déduit** d'un secret que le serveur vérifie
  (§4) ;
* **la matrice ne bouge pas d'une ligne.** `Q3` §1 sépare déjà `client → profil` (l'annuaire,
  qui bouge) de `profil → droits` (la matrice, qui est gouvernée). Sous stdio l'annuaire est
  **inerte**, absorbé par la configuration de chaque poste ; sous HTTP il devient le
  mécanisme réel (`annuaire.yaml`, secrets hors dépôt, référencés par nom d'entrée
  d'environnement). Passer à HTTP n'étend pas la gouvernance : ça active une indirection
  déjà isolée (§5) ;
* **trois propriétés à conserver** : comparaison du secret à temps constant, `default` reste
  total (secret inconnu → refus propre et journalisé, pas une trace de pile), et le journal
  écrit le profil **résolu par le serveur**, jamais celui allégué.

### Ce que la note ne traite pas, et qui est le vrai goulot

**Les huit tools sont synchrones, et FastMCP les exécute dans sa boucle d'événements.**
Vérifié dans le SDK : `call_fn_with_arg_validation` fait `return fn(**arguments_parsed_dict)`
sans thread quand la fonction ne l'est pas
(`mcp/server/fastmcp/utilities/func_metadata.py:115`). Un serveur MCP traite donc ses appels
**en série**. Aujourd'hui c'est sans conséquence — un processus par profil, un utilisateur à
la fois. À vingt utilisateurs sur **un** processus, vingt questions documentaires se
mettraient à la queue leu leu, à ~5 s la première puis le temps du modèle.

Le passage à HTTP ne le corrige pas : il l'expose. C'est la première chose à instruire, et
elle est indépendante du transport.

La mémoïsation de l'embedder et du reranker (étape C, étape 0) va dans le bon sens sans
suffire : elle est **par processus**, donc un modèle partagé par les vingt au lieu d'un par
appel — mais elle ne rend pas les appels concurrents.

### Ce qu'il reste à instruire

1. **Rendre les tools concurrents.** `async def` côté serveur avec la partie bloquante en
   `anyio.to_thread`, ou un pool. À mesurer avant de choisir : quelle part du temps est
   CPU-bound (embedding, rerank local) et quelle part est attente réseau (Azure). Les deux
   n'appellent pas la même réponse, et le journal porte déjà `latency_ms` pour trancher ;
2. **la sûreté de ce qui est partagé** entre appels concurrents dans un processus unique :
   l'embedder et le reranker mémoïsés, le client Chroma, la connexion SQLite `mode=ro`.
   C'est la question que la sérialisation actuelle masque entièrement ;
3. **`resolve_profil(ctx)` et `annuaire.yaml`**, tels que `note-transport.md` §5 les décrit ;
4. **ce que devient `GatewayRegistry`** côté banc d'essai : un registre de sous-processus
   n'a plus d'objet face à un service HTTP — il devient un client par secret, ou rien.

### Hors périmètre, et nommé comme tel

`note-transport.md` §6 les liste déjà, et ils le restent : **OAuth 2.1 / Resource Server**
(voie normative pour un serveur MCP distant — un secret par application authentifie
l'*application*, pas l'*utilisateur* derrière le bot Slack), **rotation et révocation** des
secrets, **TLS** de bout en bout, et **l'utilisateur derrière un client de service** — si le
support et le commercial partageaient un même bot, le profil devrait suivre l'utilisateur
Slack et l'annuaire ne suffirait plus.

## 2026-09-06 — Le secret de l'annuaire : ce qu'il prouve, ce qu'il ne prouve pas

**Question de l'utilisatrice** : « comment ça marche cette histoire de secret ? Dans la vraie
vie (en prod et dans une boîte) cela fonctionnerait aussi comme ça ? » Consignée parce que la
réponse sépare **ce qui est un bouchon** de **ce qui est de l'architecture réelle** dans la
conception d'accès du projet — et que la distinction est exactement ce qu'une soutenance
interroge. `note-transport.md` §4 et §5 décrit le mécanisme ; ce qui suit dit *pourquoi* il a
cette forme, et jusqu'où elle tient hors du brief.

### D'où vient la question, et un point de brief à ne pas re-débattre

Elle est arrivée en instruisant le déploiement, sur l'idée qu'il faudrait une URL pour le
serveur MCP, donc un transport autre que stdio. **Relecture du brief : il ne demande pas
d'URL pour le MCP.** Les deux livrables se lisent littéralement :

* « Le serveur MCP (`mcp_server/`) exposant le catalogue complet **ainsi qu'un mini guide
  d'accès** » — un répertoire et un guide, pas un point d'accès réseau ;
* « **Un lien** d'une interface graphique du produit fonctionnel » — l'URL est là, et elle
  porte sur l'IGU.

Le brief assume stdio ailleurs, explicitement : chantier MCP étape 3, « démontrer deux profils
différents **avec `scripts/mcp_client.py`** ». C'est ce que fait déjà `make client
PROFILE=support|commercial`. **stdio tient donc le livrable**, et le déploiement à instruire
est celui de l'interface, pas celui du protocole. Le `--transport` sur `main()` reste possible
à peu de frais (`server.py:223-230`) si un client externe doit être branché à l'oral ; il ne
préempte aucune décision de `note-transport.md`, puisque le profil resterait dans
`SORABEL_PROFILE`, un déploiement par profil.

### Le mécanisme, et le sens de la déduction

Trois temps :

1. **l'annuaire associe un nom de client à un profil, et dit *où* est son secret** — jamais le
   secret lui-même. Le YAML est versionné, le secret vit dans l'environnement du serveur.
   Même discipline que le `.env` actuel ;
2. **le client envoie son secret à chaque requête**. Pas son profil : son secret ;
3. **le serveur compare et en déduit le profil** — comparaison à temps constant, pour ne pas
   fuir l'information par la durée. Secret absent, inconnu ou malformé → `default`, zéro
   droit, appel journalisé.

**Le client ne dit jamais qui il est ; il prouve qu'il détient un secret, et le serveur en
conclut qui il est.** C'est toute la raison pour laquelle un `X-Sorabel-Profile` doit être
**ignoré** et non honoré : un en-tête est une déclaration, un secret est une preuve. Le
quatrième contrôle du §7 de la note — secret `support` + en-tête `commercial` → droits
`support` — ne vérifie rien d'autre que ça, et c'est lui qui distingue la conception de sa
version décorative.

### En production : oui pour la moitié, non pour l'autre

**Le motif existe en production**, et le projet l'utilise déjà sans le nommer :
`AZURE_AI_API_KEY` est exactement ça. Elle n'authentifie pas l'utilisatrice, elle authentifie
*l'application* auprès d'Azure, qui en déduit l'abonnement et les déploiements autorisés.
Clés d'API et comptes de service sont le pain quotidien du service-à-service.

**Il ne suffit pas dès que les droits dépendent de la personne** — le cas d'ici, puisque la
matrice cloisonne des données métier sensibles. Le secret partagé authentifie l'application,
pas l'utilisateur derrière elle : le bot Slack a *un* secret et sert *N* personnes. Le jour où
un commercial et un agent du support écrivent au même bot, le serveur ne peut plus les
distinguer. `note-transport.md` §6 le nomme déjà comme hors périmètre — c'est la bonne limite
à annoncer plutôt qu'à laisser découvrir.

Ce qui remplace le secret sur ce cas-là, en entreprise :

* **un fournisseur d'identité** (Entra ID, Okta, Keycloak) authentifie la personne, pas
  l'application ;
* **le serveur MCP devient Resource Server OAuth 2.1** : il ne compare plus un secret, il
  valide la **signature** d'un jeton émis par l'IdP et lit ses *claims* — identité, groupes,
  rôles ;
* **la délégation d'identité** fait que le bot parle *au nom de* l'utilisateur, au lieu de
  parler en son nom propre ;
* **rotation et révocation** deviennent gratuites : un jeton expire seul. Un secret statique
  qui fuit oblige à redéployer tous les clients qui le portent — c'est la vraie raison pour
  laquelle on ne bâtit pas un accès utilisateur sur des secrets partagés.

### Ce qui tient tel quel en production, et qu'il ne faut pas brader

**La séparation en deux tables de `Q3` §1 n'est pas un artifice pédagogique : c'est la forme
du contrôle d'accès réel.**

| | ici | en production |
|---|---|---|
| `client → profil` | `annuaire.yaml` + secret | les *claims* du jeton (groupes de l'annuaire d'entreprise) |
| `profil → droits` | `matrice.yaml` | **inchangée** |

Seule la colonne de gauche change de source. La matrice, les trois étages, et le journal qui
écrit le profil **résolu** et jamais celui allégué survivent intacts au passage à OAuth. **Le
secret est un bouchon sur la brique d'identité, pas une erreur d'architecture** — et c'est la
réponse à donner si la question vient à l'oral.

La règle « ne jamais traiter un en-tête comme une identité » ne bouge pas d'un iota non plus :
en OAuth, l'en-tête `Authorization` n'est pas cru davantage, il est *vérifié* — sa signature
est validée contre la clé publique de l'IdP. Même geste, preuve plus solide.

### Ce que cette entrée ne change pas

Aucune ligne de code. Elle consigne un arbitrage de lecture du brief (stdio tient le livrable
serveur) et la portée réelle d'un mécanisme conçu mais non implémenté. Les points ouverts de
l'entrée précédente restent ouverts, dans le même ordre.

## 2026-09-06 — Piste à instruire : de l'application à la personne, une chaîne de délégation

**Chaîne proposée par l'utilisatrice**, en cinq mouvements, après l'entrée précédente sur le
secret d'annuaire. Consignée parce qu'elle **re-dérive depuis le besoin un motif standard** —
la délégation d'identité, *On-Behalf-Of* chez Microsoft, échange de jetons OAuth 2.0 en
RFC 8693 — et parce qu'elle referme au passage un point ouvert de la piste « vingt
utilisateurs ». Les quatre corrections du §« Ce qui est resserré » font partie de la piste :
c'est elle *avec* elles qui est consignée, pas la version brute.

### La chaîne, telle que proposée

1. l'API agent porte une clé d'API, partagée avec le front Chainlit : le front a le droit de
   l'appeler ;
2. l'API accepte la communication parce que la clé est présente et correcte. L'utilisateur se
   connecte — `user-du-support` et son mot de passe — ce qui met en route le JWT ;
3. l'utilisateur connecté fait passer l'agent de `default` (zéro droit) à `support` ;
4. l'agent se branche au serveur MCP, qui porte lui aussi une clé d'API que l'agent connaît
   dans ses secrets ;
5. l'agent, mandaté par `user-du-support`, s'authentifie auprès du MCP **comme acteur pour le
   compte** de cet utilisateur, dont le profil est `support`.

### Ce que la chaîne a de juste, et qu'il ne faut pas perdre

* **Les deux niveaux sont séparés.** Les mouvements 1-2 et 4 authentifient une *application* ;
  3 et 5 authentifient une *personne*. C'est la distinction que le secret d'annuaire de
  `note-transport.md` §6 ne franchissait pas, et c'est l'erreur la plus courante de la confondre ;
* **le refus par défaut est propagé à chaque saut** — la propriété 2 de `matrice.yaml`, tenue
  de bout en bout ;
* **l'invariant du projet survit au multi-utilisateurs, et ce n'est pas accidentel.** L'agent
  est un LLM : il choisit ses tools sur les descriptions, et une question portant une
  injection peut le pousser à en appeler un qu'il ne doit pas. La chaîne tient parce que le
  profil se résout **côté serveur, depuis un jeton signé** — il n'apparaît nulle part dans ce
  que le modèle manipule. C'est la propriété que `SORABEL_PROFILE` donne aujourd'hui, portée
  intacte.

### Les quatre corrections, qui font partie de la piste

**1. Le mouvement 4 n'est pas un état, et il ne précède pas le 5.** L'énoncé initial mettait
le profil à `default` au mouvement 4, « parce que never trust user input ». Ça décrit deux
échanges successifs, donc **une fenêtre où l'agent parle au MCP sans utilisateur**. En
pratique c'est **un seul appel portant deux justificatifs** — la clé de l'application *et* le
jeton de l'utilisateur — vérifiés ensemble et résolus une fois. Jeton absent ou invalide →
`default` ; valide → `support`. Modéliser 4 et 5 en séquence invite à écrire cette fenêtre, et
c'est là que les défauts se logent.
Et `default` n'y est pas le produit d'une *méfiance* mais d'une **résolution absente ou
échouée** : la méfiance ne produit pas un profil, elle produit une vérification.

**2. « Prouver son identité » doit vouloir dire transmettre le jeton, pas l'affirmer.**
L'agent **retransmet le jeton signé tel quel** ; le serveur MCP en vérifie la **signature**
contre la clé de l'émetteur. Si l'agent pouvait *déclarer* « je suis mandaté par
`user-du-support` », ce serait le piège de l'en-tête (§4 de `note-transport.md`) une troisième
fois, un étage plus haut.
Corollaire à poser tout de suite : **l'API agent devient l'émetteur** de jetons — c'est elle
qui tient la table utilisateurs — et le serveur MCP doit pouvoir les vérifier : clé publique
partagée, ou secret de signature commun. C'est le contenu technique réel du mouvement 5.

**3. Le mouvement 1 fait moins qu'il n'y paraît, et ce n'est pas grave.** La clé entre
Chainlit et l'API tient **parce que Chainlit tourne côté serveur** : c'est un processus Python
qui fait ses appels HTTP lui-même. Une clé d'API dans un front navigateur serait publique et
ne prouverait rien. Les mouvements 1 et 4 sont des **grilles de transport** — elles empêchent
un inconnu d'atteindre le service, elles ne décident d'aucun droit. La garantie est au
mouvement 5, et nulle part ailleurs.

**4. Le risque neuf que la chaîne introduit.** Si le jeton transite **par** l'agent, le
processus agent détient des jetons d'utilisateurs, et un processus unique servant plusieurs
personnes **ne doit jamais mélanger deux jetons entre sessions concurrentes**. C'est le point
ouvert n° 2 de l'entrée « vingt utilisateurs » — la sûreté de ce qui est partagé entre appels
concurrents — mais **il change de nature** : problème de performance jusqu'ici, il devient un
problème de sécurité. À traiter **avant** la chaîne, pas après.

### Ce que la chaîne referme

**Le point ouvert n° 4 de la piste « vingt utilisateurs » : ce que devient `GatewayRegistry`.**
Si le profil voyage dans le jeton, **l'agent n'a plus besoin d'être instancié par profil** :
un agent, N utilisateurs, le profil porté par l'appel. Le registre indexé par profil n'a plus
d'objet.

Ça simplifie aussi l'étiquette proposée : `agent-support` n'a pas lieu d'être. Il n'y a qu'**un**
agent, acteur pour le compte de N sujets — soit exactement les deux champs de RFC 8693,
`act` = l'agent et `sub` = l'utilisateur, et non un nom composé. Le journal peut alors porter
les deux : **qui**, et **par l'intermédiaire de qui**.

### Position par rapport aux deux autres voies

| Voie | Ce qu'elle authentifie | État |
|---|---|---|
| `SORABEL_PROFILE` (aujourd'hui) | le *processus* | livré, tient le brief |
| `annuaire.yaml` + secret (`note-transport.md` §5) | l'*application* | conçu, non implémenté |
| comptes + JWT + délégation (cette entrée) | la *personne* | piste instruite |

Les trois partagent la même colonne de droite : `matrice.yaml`, les trois étages, et le
journal qui écrit le profil **résolu** et jamais celui allégué. **Seule la source de
`client → profil` change** — c'est la séparation de `Q3` §1, et c'est ce qui rend ces voies
substituables sans rouvrir la gouvernance.

### Réserve de périmètre, nommée

Quatre mécanismes d'authentification, une table utilisateurs, une IGU de connexion et un
émetteur de jetons. **Rien de tout cela n'est noté** : le brief ne demande ni authentification
ni déploiement, et `make mesure-acces` comme le mini guide d'accès le sont, eux.

Et la limite de fond reste celle de l'entrée précédente : cette chaîne **construit un
fournisseur d'identité**. En entreprise on ne le fait pas — on se branche sur celui de la
maison, précisément pour ne pas gérer soi-même mots de passe, rotation, révocation et cycle de
vie des comptes. Défendable pour un projet interne ; délégué en production.
