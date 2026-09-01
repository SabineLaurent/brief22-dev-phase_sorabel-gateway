# Journal de développement — Sorabel Data Gateway

Tenu au fil de la phase de développement du brief 22. Une entrée par étape livrée :
ce qui a été décidé, ce qui a été écrit, ce qui a été vérifié, et ce qui reste ouvert.
Objectif : pouvoir reprendre le fil — ou justifier un choix en soutenance — sans
relire le code.

Le découpage suit celui du brief : trois chantiers (RAG avancé, Text-to-SQL, serveur
MCP), et trois étapes à l'intérieur du chantier RAG. **Une étape est implémentée,
vérifiée et journalisée avant que la suivante ne commence.**

Documents de référence : `docs/cadrage_dsi.md` (contrat DSI, normatif),
`LIVRABLES_CONCEPTION/` (dossier de conception), `tests/` (suite d'acceptance).

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

Toutes reprises de `LIVRABLES_CONCEPTION/02-modele-chunk.md`, et confirmées sur le
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
