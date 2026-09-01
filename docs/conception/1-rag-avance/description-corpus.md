# Description du corpus

> Document de référence factuel du chantier RAG. Toutes les valeurs sont **mesurées** sur
> le dossier `data/corpus/` livré par le formateur, et reproductibles par les commandes
> du §7. Aucun chiffre de ce document n'est estimé.
>
> Pour les *conséquences de conception* tirées de ces faits, voir
> [../docs/2026-08-27-sonde-corpus.md](../docs/2026-08-27-sonde-corpus.md).

## 1. Vocabulaire

Trois mots à distinguer, sans quoi tous les décomptes deviennent ambigus :

| Terme | Désigne | Exemple |
|---|---|---|
| **édition** | un fichier sur le disque, une version datée | `proc-…-01-v2.0.html` |
| **document** | la chose, indépendamment de ses versions | « la procédure panne batterie 01 » |
| **clé de document** | ce qui regroupe les éditions d'un document | `sav/proc-…-01` |

**La clé de document est le chemin privé de son suffixe `-vX.Y`.** Le nommage du corpus
est parfaitement régulier : il n'y a rien à deviner, aucune heuristique à écrire.

```
sav/proc-panne-batterie-electroportatif-01-v1.0.html ─┐
sav/proc-panne-batterie-electroportatif-01-v2.0.html ─┴─► un document, deux éditions
```

Le mot « famille », employé au départ, est écarté : chez un distributeur de matériel
électrique, il désigne déjà une famille d'articles.

## 2. Inventaire

```
data/
├── corpus/
│   ├── fiches/     150 PDF
│   ├── notices/     80 PDF
│   ├── sav/         90 HTML
│   └── notes/       80 Markdown
└── sorabel.db      192 Ko, SQLite
```

**400 éditions · 350 documents · 50 documents à deux éditions.**

| Collection | `doc_type` | Éditions | Documents | dont à 2 éditions | Suffixes observés |
|---|---|---:|---:|---:|---|
| `fiches/` | `fiche_technique` | 150 | 120 | 30 | `v1.0` · `v2.1` |
| `notices/` | `notice` | 80 | 70 | 10 | `v1.0` · `v1.1` |
| `sav/` | `procedure_sav` | 90 | 80 | 10 | `v1.0` · `v2.0` |
| `notes/` | `note_interne` | 80 | 80 | 0 | — (frontmatter `1.0`) |
| **total** | | **400** | **350** | **50** | |

Le compte se vérifie : 300 documents à une édition + 50 × 2 = 400 fichiers.

**Le `doc_type` vient du nom du dossier.** Aucune inférence, aucune heuristique.

## 3. Taille du texte extrait

Mesure du **texte extrait**, pas des octets du fichier — c'est le texte extrait qui part
à l'embedding.

| Collection | Format | n | Médiane | **Maximum** | ≈ tokens | Édition la plus longue |
|---|---|---:|---:|---:|---:|---|
| `fiches/` | PDF | 150 | 435 | **632** | ~158 | `REF-8842-v2.1.pdf` |
| `notices/` | PDF | 80 | 651 | **666** | ~166 | `notice-REF-8842-v1.0.pdf` |
| `sav/` | HTML | 90 | 892 | **923** | ~230 | `proc-diagnostic-disjoncteur-declenche-08-v1.0.html` |
| `notes/` | Markdown | 80 | 309 | **348** | ~87 | `note-2024-12-25-politique-tarifaire-61.md` |

**La plus longue édition du corpus fait 923 caractères, soit environ 230 tokens.**

Deux précisions qui élargissent encore la marge :

- le **923** du HTML est une borne haute : balises retirées mais espaces bruts. Après
  normalisation des espaces — le texte réellement indexé — **876 caractères**. Le fichier
  pèse 1 221 octets, dont environ 300 de balisage.
- le **348** du Markdown est le fichier entier, frontmatter YAML compris. Le corps seul,
  celui qu'on embedde : **232 caractères**.

**Conséquence.** La fenêtre des modèles d'embedding courants (`all-MiniLM`, `e5`, `bge`)
est de 512 tokens ; la pire édition en occupe **45 %**. Il reste plus de la moitié de la
fenêtre en marge — assez pour absorber un tokenizer moins efficace sur le français sans
jamais frôler la troncature silencieuse.

## 4. Où vivent les métadonnées, par format

| Format | Texte | Titre | Version | Date | Référence |
|---|---|---|---|---|---|
| PDF | `pypdf.extract_text()` | 1re ligne | ligne `Version : 2.1` **et** nom de fichier | ligne `Date : 2024-05-25` | ligne `Référence produit : REF-8842` |
| HTML | balises retirées | `<title>` | `<meta name="version">` **et** nom de fichier | `<meta name="date">` | absente (voir §5) |
| Markdown | corps après le frontmatter | `titre:` | `version:` (frontmatter) | `date:` (frontmatter) | dans le corps, jamais en frontmatter |

**La version figure deux fois** — nom de fichier et contenu. Cela offre un contrôle de
cohérence gratuit à l'ingestion :

```python
assert version_du_nom == version_du_contenu, f"{chemin} : version incohérente"
```

**Le `mtime` des fichiers est inutilisable** : les 400 fichiers portent le même
horodatage, celui de la copie du dossier. La date doit être lue dans le contenu — ce
qu'elle permet, puisque chaque édition porte la sienne.

**Plages de dates observées** (lues dans le contenu) :

| Collection | De | À |
|---|---|---|
| `fiches/` | 2022-01-11 | 2025-09-27 |
| `notices/` | 2022-06-17 | 2025-02-25 |
| `sav/` | 2023-01-24 | 2026-05-27 |
| `notes/` | 2024-01-02 | 2026-07-04 |

## 5. La référence produit et ses deux pièges

**120 références ancrées dans `fiches/`, 70 dans `notices/`, aucune dans `sav/` ni
`notes/`.** La référence est donc **optionnelle** dans le modèle de données.

### Piège 1 — chaque fiche cite trois références

```
REF-8842-v2.1.pdf
  toutes les REF trouvées au fil du texte : REF-8842, REF-5147, REF-6463
  référence ancrée sur son étiquette      : REF-8842
```

Les deux autres sont des **liens sortants** — la ligne « Accessoires et produits
associés ». Un `grep -o 'REF-[0-9]*'` naïf les attrape toutes les trois et fait remonter
la fiche de `REF-8842` sur une recherche `REF-6463` : exactement le faux positif que
sanctionne le test d'acceptance « la fiche correspondante remonte en tête ».

> **Règle : la référence est ancrée sur son étiquette `Référence produit :`, jamais
> cherchée au fil du texte.**

### Piège 2 — les procédures SAV citent une référence qui n'est pas leur sujet

```html
<p>Version 2.0 — mise à jour du 2026-04-24. Applicable à tout le catalogue,
exemple traité sur la référence REF-8094.</p>
```

Les 90 procédures sont **génériques**. La référence citée est un exemple pédagogique, et
elle **change entre la v1.0 et la v2.0** d'une même procédure — ce qui prouve qu'elle
n'identifie rien.

> **Règle : `reference` reste vide pour les procédures SAV.**

## 6. Deux propriétés structurantes

### La jointure corpus ↔ base SQL est exacte

Les **120 références** de `fiches/` correspondent aux **120 lignes** de la table
`produits`, sans écart dans un sens ni dans l'autre. Aucune fiche sans produit, aucun
produit sans fiche. La métadonnée `reference` comme **pont entre le RAG et le SQL** est
confirmée par les données, pas seulement par le raisonnement.

### `notes/` porte de l'information sensible

80 notes internes réparties sur 5 thèmes (16 chacun) : `alerte-qualite` · `logistique` ·
`politique-tarifaire` · `retour-terrain` · `reunion-achat`.

Les 16 notes `politique-tarifaire` parlent de **marge** et portent la mention « Diffusion
restreinte ». C'est le levier de l'exigence **E5 côté documentaire** : l'information
sensible n'existe pas seulement dans les colonnes SQL, elle est aussi dans le corpus. La
matrice d'accès doit donc pouvoir fermer une collection au niveau du RAG.

*Question ouverte, à trancher au chantier MCP :* fermer `notes/` entièrement au profil
support, ou seulement le thème `politique-tarifaire` ? Fermer la collection est plus
simple et plus sûr ; le grain par thème est plus juste métier — une `alerte-qualite`
intéresse le support.

### Ce que le corpus ne contient pas

| Attendu par le brief ou par prudence | Constat |
|---|---|
| tableaux dans les PDF techniques | **aucun** sur 400 éditions |
| pages scannées, images | **aucune** — PDF de 1,3 à 1,6 Ko, une page, une police |
| doublons stricts | **aucun** hash d'octets dupliqué |
| `eval/questions_rag.jsonl` | **absent** du dossier livré — les 30 questions sont transcrites depuis `question-rag.png` au §7 ; le fichier reste à demander au formateur |

## 7. Les 30 questions d'évaluation, confrontées au corpus

> Transcrites depuis `question-rag.png`. **`eval/questions_rag.jsonl` n'est pas dans
> `data/`** : la conception est écrivable, l'exécution des tests d'acceptance ne l'est pas.
> Trois `attendu_type` sont coupés au bord droit de l'image (RAG-11, RAG-19, RAG-21) ; ils
> sont **déduits** du contexte et signalés par un astérisque.

### 7.1 · `reference_exacte` — 8 questions, 7 références

Toutes portent un `attendu_reference`. La question **est** la référence, nue ou précédée de
« fiche technique ».

| # | Question | `attendu_reference` | Fiche ancrée | Autres fiches qui la citent |
|---|---|---|:--:|:--:|
| 01 | `REF-8842` | REF-8842 | ✔ 2 éditions | 2 |
| 02 | fiche technique `REF-8842` | REF-8842 | ✔ 2 éditions | 2 |
| 03 | `REF-5313` | REF-5313 | ✔ | 2 |
| 04 | `REF-8836` | REF-8836 | ✔ | 4 |
| 05 | `REF-5719` | REF-5719 | ✔ | 3 |
| 06 | `REF-5603` | REF-5603 | ✔ | 3 |
| 07 | `REF-4581` | REF-4581 | ✔ | 2 |
| 08 | `REF-9382` | REF-9382 | ✔ | 5 |

**Les huit références existent toutes**, ancrées sur leur étiquette `Référence produit :`.
Trois conséquences :

1. **le piège 1 du §5 est exercé par ces huit questions** — chaque référence attendue est
   citée par 2 à 5 *autres* fiches au titre des « Accessoires et produits associés ». Un
   `grep` au fil du texte fait remonter jusqu'à 5 fiches concurrentes sur RAG-08 ;
2. **RAG-01 et RAG-02 partagent la même référence** : 8 questions, 7 références distinctes.
   Une mesure de rappel qui compterait les références au lieu des questions se tromperait ;
3. **aucune question ne porte sur une référence absente.** Le cas « référence bien formée,
   document inexistant » n'est testé par rien — voir
   [../3-exposition-mcp-et-matrice-d-acces/Q4.md](../3-exposition-mcp-et-matrice-d-acces/Q4.md)
   §12, où il porte le code `introuvable`.

### 7.2 · `couverte` — 14 questions, et 4 trous lexicaux

| # | Question | Attendu | Terme distinctif | Où il se trouve réellement |
|---|---|---|---|---|
| 09 | quel disjoncteur pour un départ moteur en triphasé ? | `REF-8842` | « départ**s** moteur**s** » | **2 fiches** — les deux éditions de REF-8842 |
| 10 | disjoncteur qui déclenche de façon répétée | `procedure_sav` | « déclenche » | 9 procédures |
| 11 | retour d'un produit défectueux sous garantie | `procedure_sav`\* | « garantie » | 90 SAV **et 93 fiches** |
| 12 | délai annoncé pour un échange standard | `procedure_sav` | « échange standard » | les 90 SAV |
| 13 | précautions avant d'installer un produit électrique | `notice` | « précaution » | **nulle part** — les notices disent « consignes de sécurité » (80) |
| 14 | que vérifier 48 heures après la mise en service | `notice` | « 48 h » | les 80 notices |
| 15 | quelle norme s'applique aux disjoncteurs modulaires | `fiche_technique` | « norme » | 57 fiches |
| 16 | garantie fabricant par défaut sur le catalogue | `fiche_technique` | « garantie » | 93 fiches **et 90 SAV** |
| 17 | que faire si un colis arrive endommagé | `procedure_sav` | « endommag… » | 9 procédures |
| 18 | comment demander un duplicata de facture | `procedure_sav` | « duplicata » | 9 procédures |
| 19 | quel différentiel pour un circuit avec plaque de cuisson | `fiche_technique`\* | « plaque de cuisson » | **nulle part** — « différentiel » seul : 7 fiches, 5 notices, 9 SAV |
| 20 | quelle section de conducteur pour un disjoncteur 40 A | `fiche_technique` | « section » | **les 80 notices, aucune fiche** |
| 21 | réparer une batterie d'outillage sans fil | `procedure_sav`\* | « batterie » | 9 procédures |
| 22 | température de service d'un câble R2V | `fiche_technique` | « R2V » | 7 fiches, 5 notices |

Répartition des attendus : **6 `procedure_sav` · 5 `fiche_technique` · 2 `notice` ·
1 `attendu_reference`**.

> **Aucune des 30 questions n'attend une note interne.** `notes/` n'est la source attendue
> de rien — ce qui rend la fermeture par thème décidée au chantier MCP sans coût sur la
> mesure E6.

**Quatre questions ne sont pas résolubles par le lexique**, et ce sont elles qui justifient
la partie dense de la recherche hybride (E6) :

| # | Nature du trou | Ce qu'il faut pour y répondre |
|---|---|---|
| 09 | **flexion** — la question dit « départ moteur », la fiche « départs moteurs » | une racinisation, ou le dense |
| 13 | **synonymie** — « précautions » vs « consignes de sécurité » | le dense seul |
| 19 | **absence** — « plaque de cuisson » n'existe dans aucun document | une abstention légitime, ou une réponse partielle sur « différentiel » |
| 20 | **collection contredite** — l'attendu dit `fiche_technique`, le terme n'est que dans les notices | à confirmer avec le formateur : l'attendu du jeu paraît en tension avec le corpus livré |

Deux autres questions sont **ambiguës entre collections** : RAG-11 et RAG-16 portent toutes
deux sur la « garantie », présente à la fois dans 90 procédures SAV et 93 fiches — et leurs
`attendu_type` sont opposés. Le discriminant est le contexte (`retour défectueux` vs
`catalogue`), pas le mot-clé.

### 7.3 · `hors_corpus` — 8 questions, toutes confirmées vides

RAG-23 → 30 portent sur des sujets **RH et vie interne** : télétravail, chiffre d'affaires,
VPN, grilles de salaires, planning des congés, recrutement d'alternants, contrat
d'électricité, politique RSE.

**Aucun des huit sujets n'apparaît dans aucun des 400 documents.** Le corpus est
« proprement » hors sujet sur ces questions : c'est ce qui rend le seuil de refus (E1)
calibrable sans arbitrage douteux.

Une seule est proche du domaine — RAG-29, « résilier le contrat d'électricité de l'entrepôt
de Lyon » : elle mêle un vocabulaire électrique et un entrepôt qui existe dans la base SQL.
C'est la question la plus susceptible de passer le seuil à tort.

## 8. Reproduire les mesures

```bash
# éditions et documents, par collection
for d in fiches notices sav notes; do
  n=$(ls data/corpus/$d | wc -l)
  f=$(ls data/corpus/$d | sed -E 's/-v[0-9]+\.[0-9]+\././' | sort -u | wc -l)
  m=$(ls data/corpus/$d | sed -E 's/-v[0-9]+\.[0-9]+\././' | sort | uniq -d | wc -l)
  echo "$d : $n éditions, $f documents, $m à deux éditions"
done

# jointure corpus ↔ base
ls data/corpus/fiches | sed 's/-v.*//' | sort -u > /tmp/refs_corpus
sqlite3 data/sorabel.db "SELECT ref FROM produits ORDER BY ref;" > /tmp/refs_base
comm -3 /tmp/refs_corpus /tmp/refs_base        # attendu : vide

# doublons stricts
find data/corpus -type f -exec shasum -a 256 {} \; \
  | awk '{print $1}' | sort | uniq -d | wc -l    # attendu : 0
```

Les tailles de texte extrait et les plages de dates se mesurent par le script Python cité
au §3 et au §4 (lecture `pypdf` pour les PDF, retrait des balises pour le HTML,
`yaml.safe_load` du frontmatter pour le Markdown).

**Précaution non négociable : figer la version de `pypdf`** (mesuré avec `6.14.2`). Une
montée de version change la sortie de `extract_text()`, donc le contenu de l'index, donc
la comparabilité de la mesure E6 avant/après.

### Les mesures du §7

Le §7 confronte chaque question au **texte extrait**, pas aux noms de fichiers : il faut
donc passer par `pypdf`. Le script charge une fois les 400 documents, puis cherche.

```python
import pathlib, re, collections
from pypdf import PdfReader

root = pathlib.Path("data/corpus")
T = {}
for p in sorted(root.rglob("*")):
    # `data/corpus/.DS_Store` traîne dans le dossier livré : un rglob naïf l'ingère
    if not p.is_file() or p.name.startswith("."):
        continue
    T[str(p.relative_to(root))] = (
        "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
        if p.suffix == ".pdf" else p.read_text(encoding="utf-8", errors="replace"))
assert len(T) == 400

def ou(pattern):                      # dans quelles collections ce terme apparaît-il ?
    rx = re.compile(pattern, re.I)
    return dict(collections.Counter(k.split("/")[0] for k, t in T.items() if rx.search(t)))

# §7.2 — les quatre trous lexicaux (attendu : les deux premiers vides)
print(ou(r"pr[ée]caution"))           # {} — les notices disent « consignes de sécurité »
print(ou(r"cuisson"))                 # {}
print(ou(r"d[ée]parts? moteurs?"))    # {'fiches': 2}  ← RAG-09 n'est trouvable qu'au pluriel
print(ou(r"section"))                 # {'notices': 80} ← RAG-20 attend pourtant une fiche

# §7.3 — les 8 sujets hors corpus (attendu : {} pour les huit)
for p in [r"t[ée]l[ée]travail", r"chiffre d[’']affaires", r"\bVPN\b",
          r"salaire|r[ée]mun[ée]rat", r"cong[ée]s?\b", r"recrutement|alternant",
          r"r[ée]silier|contrat d[’'][ée]lectricit[ée]", r"\bRSE\b"]:
    print(p, ou(p))
```

> **Deux pièges de mesure rencontrés en écrivant le §7**, qui valent pour l'indexation
> elle-même : chercher `RSE` sans `\b` remonte les 90 procédures SAV (« cou**rse** »,
> « dive**rse** »), et chercher « départ moteur » au singulier ne remonte **rien** alors que
> les deux fiches attendues disent « départs moteurs ». Une mesure de rappel écrite sans
> précaution conclurait à un corpus lacunaire qu'il n'est pas.
