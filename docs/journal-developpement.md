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
sur `dev`, `support`, et `commercial` en témoin.

| Profil | Rendus P0 → P1 | Vidées P0 | Seuil décidé sur un interdit, P0 |
|---|---|---|---|
| `dev` | 4,17 → 5,00 | 3 | 5 |
| `support` | 4,73 → 5,00 | 1 | 1 |
| `commercial` *(témoin)* | 5,00 → 5,00 | 0 | 0 |

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
