# Modèle des chunks et métadonnées

> Ce document est le **livrable** « modèle des chunks et métadonnées (avec référence produit
> et version) » du brief. Il fixe la forme exacte de ce qui entre dans l'index.
> Il ne rejustifie pas les décisions : celles-ci sont argumentées et mesurées dans
> [`1-rag-avance/Q2.md`](../1-rag-avance/Q2.md), dont ce fichier est la mise au format demandé
> (markdown + `.json`).

## 1. Il n'y a pas de chunker

**Un document = un chunk.** La plus longue édition du corpus fait **923 caractères**
(~230 tokens), soit **45 %** de la fenêtre du modèle d'embedding retenu
(`intfloat/multilingual-e5-base`, 512 tokens). Découper coûterait de la complexité et de la
cohérence de citation sans rien acheter.

Conséquence de vocabulaire, tenue dans tout le dossier :

| Terme | Ce qu'il désigne | Effectif |
|---|---|---|
| **édition** | un fichier du corpus, une version d'un document | **400** |
| **document** | la famille des éditions d'un même sujet (`doc_key`) | **350** |
| **chunk** | l'unité indexée — ici, **une édition** | **400** |

Les 400 éditions sont indexées, pas seulement les 350 courantes : le filtre de version
s'applique **à la requête**, par la métadonnée `is_current`.

## 2. Le texte indexé n'est pas le texte du fichier

Deux transformations, et elles ne sont pas cosmétiques :

1. **les liens sortants sortent de l'index** — les blocs « Accessoires et produits associés »
   citent des références qui ne sont pas le sujet de l'édition. Les retirer vaut **+5 en
   Hit@3** ; ils restent **à l'affichage**, où ils ont une valeur métier ;
2. **les métadonnées sont extraites, pas laissées dans le texte** — elles vivent à trois
   endroits selon le format : dans le corps du texte pour les PDF, dans les balises
   `<meta>` pour les HTML, dans le frontmatter YAML pour les notes.

`n_caracteres` mesure donc **le texte indexé**, après ces deux retraits.

## 3. Les onze champs

Tous **scalaires** — contrainte de Chroma, qui n'accepte en métadonnée que `str`, `int`,
`float`, `bool`. Ils servent quatre usages, et chaque champ est là pour au moins un : la
**citation** (E1), le **filtrage** par la matrice d'accès (E4/E5), le **versionnement**, la
**traçabilité**.

| Champ | Type | Rôle | Présence | Valeurs |
|---|---|---|---|---|
| `edition_id` | `str` | clé primaire de l'index, `upsert` déterministe | 400 / 400 | `fiches/REF-8842-v2.1` |
| `doc_key` | `str` | regroupe les éditions ; adressage de `get_document` | 400 / 400 | `fiches/REF-8842` |
| `is_current` | `bool` | filtre de version appliqué à la requête | 400 / 400 | `true` sur **350** |
| `titre` | `str` | citation E1 | 400 / 400 | — |
| `reference` | `str` | filtre exact · citation · **pont vers la base SQL** | **190 / 400** | `REF-8842` |
| `version` | `str` | citation · ciblage de `get_document` | 400 / 400 | `1.0` `1.1` `2.0` `2.1` |
| `date` | `str` ISO | citation E1 · arbitrage de récence | 400 / 400 | `2022-01-11` → `2026-07-04` |
| `doc_type` | `str` | filtre de collection de la matrice | 400 / 400 | 4 valeurs |
| `theme` | `str` | **filtre de thème de la matrice** (E5 documentaire) | **80 / 400** | 5 valeurs, `notes/` seulement |
| `url` | `str` | traçabilité vers la source | 400 / 400 | chemin relatif |
| `n_caracteres` | `int` | contrôle d'ingestion, diagnostic de troncature | 400 / 400 | ≤ **923** |

### Les quatre valeurs de `doc_type`

`doc_type` **est** la collection : le premier jet portait les deux champs, ils tiennent le
même fait — le nom du dossier — et deux champs synchronisés à la main finissent par diverger.
`doc_type` est conservé parce que c'est le nom qu'emploie le jeu d'évaluation dans son
`attendu_type`. **La matrice d'accès filtre donc sur `doc_type`.**

| `doc_type` | Dossier | Format | Éditions | Documents |
|---|---|---|---|---|
| `fiche_technique` | `fiches/` | PDF | 150 | 120 |
| `notice` | `notices/` | PDF | 80 | 70 |
| `procedure_sav` | `sav/` | HTML | 90 | 80 |
| `note_interne` | `notes/` | Markdown | 80 | 80 |

### Les cinq valeurs de `theme`

16 notes chacune, dérivées du nom de fichier, régulières sur les 80 notes.

| `theme` | `support` | `commercial` |
|---|:--:|:--:|
| `alerte-qualite` | ✓ | ✓ |
| `logistique` | ✓ | ✓ |
| `retour-terrain` | ✓ | ✓ |
| `politique-tarifaire` | ✗ | ✓ |
| `reunion-achat` | ✗ | ✓ |

`theme` **n'est pas un confort** : il est imposé par la matrice d'accès. La fermeture des
notes sensibles au support se fait **par thème**, ni par collection — fermer `note_interne`
coûterait au support ses 16 notes `alerte-qualite`, son métier même — ni par le marqueur
« Diffusion restreinte », qui ne couvre que **16 des 32** notes sensibles.

## 4. La règle de dérivation des identifiants

`edition_id` est **le chemin relatif du fichier dans `data/corpus/`, privé de son
extension**. `doc_key` est `edition_id` privé de son suffixe de version, quand il en porte un.

| Fichier | `edition_id` | `doc_key` |
|---|---|---|
| `fiches/REF-8842-v2.1.pdf` | `fiches/REF-8842-v2.1` | `fiches/REF-8842` |
| `sav/proc-casse-transport-01-v2.0.html` | `sav/proc-casse-transport-01-v2.0` | `sav/proc-casse-transport-01` |
| `notes/note-2024-03-03-politique-tarifaire-21.md` | `notes/note-2024-03-03-politique-tarifaire-21` | *identique* |

Les notes ne portent pas de suffixe de version dans leur nom : leur `version` vient du
frontmatter, et chacune est sa propre et unique édition — `doc_key == edition_id`.

## 5. La clé absente est omise, jamais vide

`reference` manque sur **210** éditions, `theme` sur **320**. Chroma n'accepte pas `None` en
métadonnée. Trois conduites étaient possibles, une seule est retenue :

| Conduite | Verdict |
|---|---|
| `None` | **impossible** — Chroma le refuse |
| chaîne vide `""` | **écartée** — `{"reference": {"$ne": ""}}` fonctionne, mais `""` est une valeur : elle se compare, se trie, s'affiche. Une citation peut sortir avec une référence vide |
| **clé omise** | **retenue** — l'absence est absente. Un filtre sur `reference` ne remonte que les éditions qui en ont une |

> **Le prix à connaître :** Chroma évalue `$in` à **`false`** sur une clé absente. C'est
> exactement ce qui produirait la panne silencieuse du filtre d'index si celui-ci était
> écrit en conjonction — d'où la **disjonction** de `filtre_index(profil)`
> ([`3-…/Q3.md`](../3-exposition-mcp-et-matrice-d-acces/Q3.md) §8, écart **S1** de l'audit).

## 6. Le schéma, en JSON

JSON Schema draft 2020-12. Les neuf champs toujours présents sont `required` ; `reference` et
`theme` en sont **absents**, et `additionalProperties: false` interdit d'y glisser autre chose.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sorabel.local/schemas/chunk-metadata.json",
  "title": "Métadonnées d'un chunk — Sorabel Data Gateway",
  "description": "Un chunk = une édition du corpus. 400 chunks pour 350 documents. Onze champs scalaires ; reference et theme sont omis quand ils ne s'appliquent pas, jamais vides ni nuls.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "edition_id",
    "doc_key",
    "is_current",
    "titre",
    "version",
    "date",
    "doc_type",
    "url",
    "n_caracteres"
  ],
  "properties": {
    "edition_id": {
      "type": "string",
      "description": "Clé primaire de l'index : chemin relatif dans data/corpus/ privé de l'extension. Rend l'upsert déterministe et la réindexation idempotente.",
      "pattern": "^(fiches|notices|sav|notes)/[A-Za-z0-9._-]+$",
      "examples": ["fiches/REF-8842-v2.1", "sav/proc-casse-transport-01-v2.0"]
    },
    "doc_key": {
      "type": "string",
      "description": "Regroupe les éditions d'un même document : edition_id privé de son suffixe de version. Seul mode d'adressage de get_document — jamais la référence produit.",
      "pattern": "^(fiches|notices|sav|notes)/[A-Za-z0-9._-]+$",
      "examples": ["fiches/REF-8842", "sav/proc-casse-transport-01"]
    },
    "is_current": {
      "type": "boolean",
      "description": "Vrai pour l'édition la plus récente de son doc_key. Vrai sur 350 des 400 éditions. Le filtre de version s'applique à la requête, dans chaque liste avant troncature — jamais après la fusion RRF."
    },
    "titre": {
      "type": "string",
      "minLength": 1,
      "description": "Élément de citation E1. N'identifie rien à lui seul : 52 titres distincts pour 150 fiches, 5 pour 80 notes.",
      "examples": ["Disjoncteur tétrapolaire triphasé 40 A courbe C"]
    },
    "reference": {
      "type": "string",
      "pattern": "^REF-[0-9]{4}$",
      "description": "Référence produit. Présente sur 190 des 400 éditions ; ABSENTE (clé omise) sur les 210 autres, dont les 90 procédures SAV — celles-ci citent une référence en exemple, qui n'est pas leur sujet. Filtre exact, élément de citation, et unique pont vers produits.ref de la base SQL.",
      "examples": ["REF-8842"]
    },
    "version": {
      "type": "string",
      "enum": ["1.0", "1.1", "2.0", "2.1"],
      "description": "Élément de citation E1 et paramètre de ciblage de get_document. Toujours présente : les notes la portent dans leur frontmatter."
    },
    "date": {
      "type": "string",
      "format": "date",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
      "description": "Date de l'édition, ISO 8601. Élément de citation E1 et seul arbitre du dédoublonnage applicatif. Plage réelle du corpus : 2022-01-11 à 2026-07-04.",
      "examples": ["2024-05-25"]
    },
    "doc_type": {
      "type": "string",
      "enum": ["fiche_technique", "notice", "procedure_sav", "note_interne"],
      "description": "La collection. Filtre de la matrice d'accès. Nom repris du champ attendu_type du jeu d'évaluation."
    },
    "theme": {
      "type": "string",
      "enum": [
        "alerte-qualite",
        "logistique",
        "retour-terrain",
        "politique-tarifaire",
        "reunion-achat"
      ],
      "description": "Thème d'une note interne, dérivé du nom de fichier. Présent sur les 80 notes uniquement (16 par thème) ; clé OMISE sur les 320 autres éditions. Porte E5 côté documentaire : politique-tarifaire et reunion-achat sont fermés au profil support."
    },
    "url": {
      "type": "string",
      "description": "Chemin relatif du fichier source depuis la racine du dépôt. Traçabilité : permet de remonter du chunk au fichier sans reconstruire de chemin.",
      "examples": ["data/corpus/fiches/REF-8842-v2.1.pdf"]
    },
    "n_caracteres": {
      "type": "integer",
      "minimum": 1,
      "maximum": 923,
      "description": "Longueur du TEXTE INDEXÉ, après retrait des balises et des liens sortants. Contrôle d'ingestion : un écart brutal signale une extraction ratée. Le maximum mesuré sur le corpus est 923, ce qui justifie l'absence de chunker."
    }
  }
}
```

## 7. Trois exemples, un par forme

Valeurs relevées sur les fichiers réels du corpus — pas des illustrations.

**Une fiche technique : les onze champs sauf `theme`.** C'est le cas complet, et c'est la
référence du test d'acceptance E2 du brief.

```json
{
  "edition_id": "fiches/REF-8842-v2.1",
  "doc_key": "fiches/REF-8842",
  "is_current": true,
  "titre": "Disjoncteur tétrapolaire triphasé 40 A courbe C",
  "reference": "REF-8842",
  "version": "2.1",
  "date": "2024-05-25",
  "doc_type": "fiche_technique",
  "url": "data/corpus/fiches/REF-8842-v2.1.pdf",
  "n_caracteres": 633
}
```

**Une note interne : `theme` présent, `reference` omise.** Le seul cas où `theme` existe, et
celui qui rend E5 documentaire applicable. Cette note est fermée au profil `support`.

```json
{
  "edition_id": "notes/note-2024-03-03-politique-tarifaire-21",
  "doc_key": "notes/note-2024-03-03-politique-tarifaire-21",
  "is_current": true,
  "titre": "Point politique tarifaire",
  "version": "1.0",
  "date": "2024-03-03",
  "doc_type": "note_interne",
  "theme": "politique-tarifaire",
  "url": "data/corpus/notes/note-2024-03-03-politique-tarifaire-21.md",
  "n_caracteres": 223
}
```

**Une procédure SAV : `reference` et `theme` tous deux omis.** C'est le cas qui prouve la
règle du §5. Le corps de cette procédure contient `REF-9196`, cité **en exemple** — ce n'est
pas son sujet, elle est « applicable à tout le catalogue ». Indexer cette référence comme
métadonnée ferait remonter la procédure sur une recherche par référence exacte, à tort.

```json
{
  "edition_id": "sav/proc-casse-transport-01-v2.0",
  "doc_key": "sav/proc-casse-transport-01",
  "is_current": true,
  "titre": "Procédure SAV — Colis reçu endommagé : constat et prise en charge (01)",
  "version": "2.0",
  "date": "2026-04-05",
  "doc_type": "procedure_sav",
  "url": "data/corpus/sav/proc-casse-transport-01-v2.0.html",
  "n_caracteres": 793
}
```

> La v1.0 de cette même procédure existe (`sav/proc-casse-transport-01-v1.0`, du
> 2024-02-23). Elle est **indexée** avec `is_current: false`, et reste atteignable par
> `get_document("sav/proc-casse-transport-01", version="1.0")`. C'est la raison d'être de ce
> tool : `search_docs` masque les éditions anciennes, à raison.

## 8. Ce que le chunk ne contient pas

| Absent | Pourquoi |
|---|---|
| `collection` | doublon de `doc_type` — un seul champ pour un seul fait |
| `auteur` | présent dans le frontmatter des notes seulement, sur 80 / 400. Ne sert ni la citation E1, ni un filtre de la matrice |
| `sensible` / `diffusion_restreinte` | le marqueur ne couvre que 16 des 32 notes sensibles. La fermeture passe par `theme`, qui est régulier |
| le texte lui-même | c'est le document indexé, pas une métadonnée |
| tout champ non scalaire | Chroma ne l'accepte pas — pas de liste de références associées, par exemple |

## Renvois

- décisions et mesures : [`1-rag-avance/Q2.md`](../1-rag-avance/Q2.md)
- inventaire du corpus : [`1-rag-avance/description-corpus.md`](../1-rag-avance/description-corpus.md)
- usage des métadonnées dans la citation E1 : [`1-rag-avance/Q4.md`](../1-rag-avance/Q4.md)
- filtre d'index par profil : [`3-…/Q3.md`](../3-exposition-mcp-et-matrice-d-acces/Q3.md) §8
- matrice qui consomme `doc_type` et `theme` : [`matrice.yaml`](matrice.yaml)
