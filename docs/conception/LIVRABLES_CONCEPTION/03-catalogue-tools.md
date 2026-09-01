# Catalogue des tools MCP — les huit

> Ce document est le **livrable** « catalogue des tools MCP : nom, entrées, sorties,
> garanties » du brief, étendu aux **huit** tools. Le tableau demandé est en drawio :
> [`03-catalogue-tools.drawio`](03-catalogue-tools.drawio) ; ce fichier porte ce qu'un
> tableau ne peut pas contenir — les descriptions rédigées, l'`outputSchema` d'union et les
> douze codes.
>
> Les quatre fiches SQL reprennent
> [`2-text-to-sql/catalogue-tools.md`](../2-text-to-sql/catalogue-tools.md), à jour de la
> matrice consolidée (§9 signale les deux écarts corrigés au passage). Les quatre fiches
> documentaires sont écrites ici pour la première fois.
>
> Spécification de référence : **MCP révision 2026-07-28**.

## 1. Le clivage réel n'est pas « haut niveau vs briques »

Le brief nomme quatre familles — RAG complet, briques du RAG, tools SQL figés, tool SQL
génératif. Elles sont conservées dans le tableau drawio, parce que c'est le vocabulaire de
l'énoncé. Mais **ce n'est pas ce qui sépare vraiment les tools documentaires** : les quatre
se distinguent par leur **mode d'adressage**.

| Mode d'adressage | Ce que l'appelant sait | Tools | Exemple de question |
|---|---|---|---|
| **Similarité** | il ne sait pas quel document il veut | `answer_question` · `search_docs` | « quel disjoncteur pour du triphasé ? » |
| **Identité** | il sait ce qu'il veut et le nomme — par `doc_key` + `version`, **jamais** par référence produit | `get_document` · `list_sources` | « la notice de REF-8842, version 1.0 » |

Le pipeline d'`answer_question` **ne contient pas** `list_sources` : « haut niveau » et
« briques » ne sont donc pas en rapport de composition, contrairement à ce que la
formulation suggère.

## 2. Vue d'ensemble

| Tool | Famille du brief | Adressage | Génère du SQL | Rédige du texte | `default` | `dev` | `support` | `commercial` |
|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `answer_question` | RAG complet | similarité | non | **oui** | ✗ | ✓ | ✓ | ✓ |
| `search_docs` | brique du RAG | similarité | non | non | ✗ | ✓ | ✓ | ✓ |
| `get_document` | brique du RAG | identité | non | non | ✗ | ✓ | ✓ | ✓ |
| `list_sources` | brique du RAG | identité | non | non | ✗ | ✓ | ✓ | ✓ |
| `get_schema` | aide SQL | — | non | non | ✗ | ✓ | ✓ | ✓ |
| `ask_database` | SQL génératif | — | **oui** | non | ✗ | ✗ | ✓ | ✓ |
| `check_stock` | SQL figé | — | non | non | ✗ | ✗ | ✓ | ✓ |
| `order_status` | SQL figé | — | non | non | ✗ | ✗ | ✓ | ✓ |

Trois faits que ce tableau porte :

- **`answer_question` est le seul endroit où E1 existe.** C'est le seul tool qui rédige,
  donc le seul qui puisse citer ou refuser de citer ;
- **`search_docs` est le seul sur lequel E6 est mesurable.** Sur `answer_question`, la
  génération s'interpose entre le classement et la réponse : on ne mesure plus le retrieval ;
- **`dev` a `get_schema` sans aucun tool de lecture de données.** `get_schema` rend la
  **forme**, les trois autres tools SQL rendent du **contenu**.

## 3. Les descriptions sont le seul levier du serveur sur l'aiguillage

Les tools sont *model-controlled* : **c'est le LLM du client qui choisit**. Le serveur ne
contrôle ni le prompt du client ni son modèle. Il ne contrôle que trois choses : le `name`,
la `description`, et l'`inputSchema`.

Une description ne s'écrit donc pas dans l'absolu, elle s'écrit **contre le tool voisin** :
un LLM ne compare pas huit descriptions, il s'arrête sur la première qui ressemble à la
question. D'où les six collisions à traiter explicitement.

| Paire confusable | Discriminant à écrire | Coût si on ne l'écrit pas |
|---|---|---|
| `answer_question` ↔ `ask_database` | **texte** de documentation vs **chiffres** de la base | le plus coûteux : en langue naturelle, les deux noms disent la même chose. D'où le **domaine en premiers mots** de la description, jamais le verbe |
| `answer_question` ↔ `search_docs` | réponse rédigée + citations vs chunks bruts à composer | un client qui voulait composer reçoit de la prose ; un client qui voulait une réponse reçoit des extraits **sans garantie E1** |
| `search_docs` ↔ `get_document` | similarité vs adressage explicite par `doc_key` + `version` | l'édition antérieure reste inatteignable — 50 documents ont deux éditions |
| `check_stock` ↔ `ask_database` | stock d'**une** référence, entrepôt par entrepôt | du SQL généré là où une requête figée suffisait, et un agrégat **faux** pour les 114 références présentes dans plusieurs entrepôts |
| `order_status` ↔ `ask_database` | en-tête d'**une** commande identifiée | idem, et le détail des lignes attendu à tort |
| `get_schema` ↔ `ask_database` | connaître le périmètre vs obtenir un résultat | un appel de génération là où l'inspection suffisait |

**Le discriminant transverse est la forme de la question, pas son sujet** : un identifiant
bien formé oriente vers les données, un « comment » ou « pourquoi » vers la documentation.

Une partie du travail vit dans l'`inputSchema`, pas dans la phrase : `"pattern":
"^REF-\\d{4}$"` écarte un libellé plus sûrement que trois lignes de prose, et **beaucoup de
clients valident avant l'envoi** — l'appel fautif n'est alors pas refusé, il n'a pas lieu.

Les huit tools portent `readOnlyHint: true`. C'est la déclaration lisible par machine de E3.
Mais **l'annotation dit ce que le serveur promet ; la barrière est ce qu'il applique** : une
annotation retirée ne change rien à la sécurité, une annotation ajoutée à tort ne
l'affaiblit pas non plus. Elles n'appartiennent pas à la même couche.

## 4. L'`outputSchema` d'union

La spécification 2026-07-28 impose deux choses qui, ensemble, dictent la forme :

- *« Servers **MUST** provide structured results that conform to this schema »* — **un refus
  aussi doit conformer**. Le schéma d'un tool est donc une **union** : un seul schéma pour la
  réponse et pour le refus ;
- *« a tool that returns structured content **SHOULD** also return the serialized JSON in a
  TextContent block »* — le duplicata texte n'est pas évitable.

D'où la règle de forme, valable pour les huit tools :

> **`code` est requis dans tous les cas. Tous les autres champs sont optionnels et
> *absents* quand il n'y a rien à mettre dedans.**

C'est l'asymétrie qui fait le travail de sécurité :

| Ce que le client rend | Sur `ok` | Sur `perimetre_interdit` |
|---|---|---|
| `structuredContent.reponse` | la réponse | **rien** — le champ est absent |
| `content[0].text` | la réponse | **le refus, à la place de la réponse** |

Un client qui lit le champ structuré est correct **sans avoir à y penser** : il n'a rien à
afficher, donc il ne peut pas afficher un refus comme une réponse. Un client qui rend le bloc
texte — comportement par défaut de la plupart des clients — commet exactement l'erreur que
le brief redoute. On ne peut pas supprimer le bloc texte, la rétrocompatibilité l'exige ; on
peut rendre l'autre chemin plus attractif, et le documenter comme le chemin normal.

### Le socle commun aux huit tools

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sorabel.local/schemas/tool-output-base.json",
  "title": "Socle d'outputSchema — commun aux huit tools",
  "description": "Union réponse | refus. Le champ code est le seul requis : c'est lui, et non isError, qui porte la décision. Les champs de charge utile sont ajoutés par chaque tool et restent optionnels.",
  "type": "object",
  "required": ["code"],
  "properties": {
    "code": {
      "type": "string",
      "enum": [
        "ok", "clarification", "aucune_ligne", "introuvable", "ambiguite_donnees",
        "hors_corpus", "contexte_insuffisant",
        "tool_interdit", "perimetre_interdit", "ecriture_refusee", "hors_schema",
        "erreur_execution"
      ],
      "description": "Les douze codes. Quatre seulement sont des refus."
    },
    "message": {
      "type": "string",
      "description": "Ce qui s'est passé, en clair. Présent sur tout code autre que ok."
    },
    "hint": {
      "type": "string",
      "description": "Le recours : le tool à appeler, la reformulation à tenter, le profil qui aurait le droit. Doit citer EXACTEMENT le tool nommé dans la description du tool appelé, sinon le LLM client reçoit deux conseils divergents et réessaie à l'identique."
    }
  }
}
```

### Un exemple complet : `answer_question`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "outputSchema de answer_question",
  "type": "object",
  "required": ["code"],
  "properties": {
    "code": { "type": "string", "enum": ["ok", "hors_corpus", "contexte_insuffisant", "tool_interdit", "perimetre_interdit"] },
    "message": { "type": "string" },
    "hint": { "type": "string" },
    "reponse": {
      "type": "string",
      "description": "La réponse rédigée. ABSENTE dès que code n'est pas ok — c'est ce qui empêche un client de rendre un refus comme une réponse."
    },
    "citations": {
      "type": "array",
      "description": "Construites en Python depuis les métadonnées du chunk, JAMAIS rédigées par le LLM. Champ séparé et non prose : un client qui résume une réponse rédigée laisse tomber les références sans s'en apercevoir.",
      "items": {
        "type": "object",
        "required": ["titre", "version", "date", "doc_key"],
        "additionalProperties": false,
        "properties": {
          "titre":     { "type": "string" },
          "reference": { "type": "string", "pattern": "^REF-[0-9]{4}$", "description": "Omise sur les 210 éditions qui n'en portent pas." },
          "version":   { "type": "string" },
          "date":      { "type": "string", "format": "date" },
          "doc_key":   { "type": "string", "description": "Permet au client de rappeler l'édition par get_document." }
        }
      }
    }
  }
}
```

Deux exemples de résultats conformes à ce schéma — le même schéma pour les deux :

```json
{
  "code": "ok",
  "reponse": "Pour un réseau triphasé 400 V, le disjoncteur tétrapolaire REF-8842 (40 A, courbe C) convient : 3P+N, pouvoir de coupure 6 kA, norme NF EN 60898-1.",
  "citations": [
    { "titre": "Disjoncteur tétrapolaire triphasé 40 A courbe C", "reference": "REF-8842",
      "version": "2.1", "date": "2024-05-25", "doc_key": "fiches/REF-8842" }
  ]
}
```

```json
{
  "code": "hors_corpus",
  "message": "aucun document du corpus ne couvre ce sujet",
  "hint": "list_sources donne l'inventaire de ce qui est couvert ; pour un chiffre, utiliser ask_database"
}
```

## 5. Les douze codes, et la ligne de partage

Le chantier 2 avait posé huit codes pour le seul `ask_database`. Ils ne sont pas remplacés :
ils sont **étendus aux quatre tools documentaires**, et chacun est tranché sur `isError`.

> **Règle : `isError` marque ce que le serveur a refusé de faire ou n'a pas pu faire —
> jamais ce qu'il a fait et qui n'a rien donné.**

| Code | Refus | `isError` | Origine, et où il est exercé |
|---|:--:|:--:|---|
| `ok` | | non | résultat nominal |
| `clarification` | | non | ambiguïté de **question**, axes fermés proposés |
| `aucune_ligne` | | non | clé bien formée, absente de la base |
| `introuvable` | | non | `doc_key` ou version inexistante — `get_document` |
| `ambiguite_donnees` | | non | plusieurs lignes là où une est attendue |
| `hors_corpus` | | non | meilleur score sous le seuil du reranker — barrière 1 |
| `contexte_insuffisant` | | non | seuil franchi, extraits qui ne portent pas la réponse — barrière 2 |
| `tool_interdit` | ✔ | **oui** | le profil n'a pas ce tool — étage 2 |
| `perimetre_interdit` | ✔ | **oui** | cible hors matrice : colonne SQL **ou** thème de notes — étage 3 |
| `ecriture_refusee` | ✔ | **oui** | demande de modification — contrôles 1 à 4 de l'AST |
| `hors_schema` | ✔ | **oui** | la question ne porte pas sur la base |
| `erreur_execution` | | **oui** | timeout, plafond, base indisponible |

Tous portent `resultType: "complete"` — un refus est un résultat **abouti**.
`resultType: "input_required"` n'est **pas utilisé** : la clarification est renvoyée comme
un résultat, pas comme une demande de saisie.

Trois conséquences, qui sont les vrais arbitrages :

**`introuvable` n'est pas un refus** — c'est le pendant documentaire d'`aucune_ligne`. Une
clé bien formée qui ne désigne rien est un **constat sur le monde**, pas une décision du
serveur.

**`hors_corpus` non plus, et c'est le point discutable.** L'argument contraire est réel :
sans `isError`, un LLM client pourrait compléter avec ses propres connaissances, ce qu'E1
interdit. Mais `isError` n'est pas un mécanisme anti-hallucination — E1 est tenue en amont,
par `answer_question` qui **ne rédige pas** quand la barrière tombe. Marquer `isError` un
appel qui s'est déroulé exactement comme prévu casserait la lecture du journal.

**`erreur_execution` porte `isError` sans être un refus.** C'est le seul des douze où les
deux notions se séparent : rien n'a été refusé, l'exécution a échoué.

> **Le discriminant du client est `code`, pas `isError`.** Un client qui branche sur
> `isError` laisse passer une erreur sur trois, dont `hors_corpus`, la plus dangereuse.
> **24 des 54 questions des jeux fournis (44 %) sont mal rendues** par un client qui se
> contente d'afficher le bloc texte.

---

# Les huit fiches

## `answer_question(question, collections)`

**À quoi il sert.** Rendre une réponse rédigée et sourcée à une question documentaire.
C'est le tool du bot Slack du support.

| | |
|---|---|
| **`title`** | Réponse documentaire sourcée |
| **Description, premiers mots** | « **Documentation produit et procédures.** Répond… » — le **domaine** d'abord, jamais le verbe : c'est ce qui le sépare d'`ask_database` |
| **Entrée** | `question` (texte libre) · `collections` (optionnel, liste de `doc_type`) — **pas** de `profil` : il est lu dans `SORABEL_PROFILE` |
| **Sortie** | `reponse` rédigée + `citations` structurées |
| **Périmètre** | les collections et **thèmes** de la matrice du profil — 350 éditions pour `commercial`, 318 pour `support`, 270 pour `dev` |
| **Garanties** | **E1** : citations construites en Python depuis les métadonnées, jamais rédigées par le LLM · **ne rédige pas** quand une barrière tombe · lecture seule (rien n'est écrit) · journalisé |
| **Codes** | `ok` · `hors_corpus` · `contexte_insuffisant` · `tool_interdit` · `perimetre_interdit` |
| **Ne fait pas** | il ne rend pas les chunks bruts — pour composer soi-même, c'est `search_docs`. Il ne touche pas la base — pour un chiffre, c'est `ask_database` |

**Le seul endroit où E1 existe.** La citation prend la forme `titre + version + date`, plus
`reference` **quand elle existe** : 210 des 400 éditions n'en portent pas, dont les 90
procédures SAV. C'est un écart assumé avec la lettre du brief, qui parlait de « référence ».

**Deux barrières de refus**, pas une : le seuil sur le score du **reranker**
(`hors_corpus`), puis la garde de suffisance du LLM (`contexte_insuffisant`). Un seuil sur
BM25 serait impossible — les plages hors-corpus (1,1 à 5,3) et couverte (4,7 à 19,0) se
chevauchent. Les deux échouent pour des raisons opposées : l'une dit « je n'ai rien trouvé »,
l'autre « j'ai trouvé, ça ne répond pas ». Le recours de l'utilisateur n'est pas le même —
reformuler, ou préciser.

---

## `search_docs(question, collections)`

**À quoi il sert.** Rendre les extraits classés, **sans** générer. C'est le tool de l'IDE
des développeurs, qui a son propre LLM.

| | |
|---|---|
| **Entrée** | `question` (texte libre) · `collections` (optionnel) |
| **Sortie** | une liste d'extraits, chacun avec ses **onze métadonnées** et son rang |
| **Périmètre** | identique à `answer_question` — même `filtre_index(profil)` |
| **Garanties** | même filtrage documentaire · aucune génération, donc aucun risque d'hallucination · journalisé |
| **Codes** | `ok` · `aucune_ligne` · `tool_interdit` · `perimetre_interdit` |
| **Ne fait pas** | il ne rédige pas et **ne garantit pas E1** : c'est au client de citer. Il masque les éditions anciennes — pour une édition précise, c'est `get_document` |

**Le seul tool sur lequel E6 est mesurable.** C'est sa raison d'être principale : sur
`answer_question`, la génération s'interpose entre le classement et la réponse, et le gain
de l'hybride devient inobservable. La mesure compare **trois** configurations — dense seul,
BM25 seul, hybride + rerank — car sans témoin lexical, le gain de l'hybride inclut celui de
BM25, déjà à 8/8 sur les questions à référence exacte.

C'est aussi le tool sur lequel E2 se vérifie : « la recherche `REF-8842` fait remonter la
fiche en tête ».

> **Point ouvert :** le nombre d'extraits rendus (`top_k`) **n'est arrêté nulle part** dans
> la conception. Il n'est donc pas inventé ici — à trancher au développement.

---

## `get_document(doc_key, version)`

**À quoi il sert.** Rendre une édition précise, nommée.

| | |
|---|---|
| **Entrée** | `doc_key` (obligatoire) · `version` (optionnel — l'édition courante par défaut) |
| **Sortie** | le texte de l'édition, **liens sortants inclus**, avec ses métadonnées |
| **Périmètre** | décidé **sur le seul argument, avant tout accès à l'index** : `doc_key` porte la collection et le thème, tous deux dérivés du nom de fichier |
| **Garanties** | vérifie la collection **et le thème** — sans quoi le même secret sortirait par une troisième porte (écart **S3** de l'audit) · un thème interdit donne `perimetre_interdit`, **jamais `introuvable`** |
| **Codes** | `ok` · `introuvable` · `tool_interdit` · `perimetre_interdit` |
| **Ne fait pas** | il **n'adresse pas par référence produit**. Les 90 procédures SAV n'en portent aucune, et ce sont précisément celles dont l'historique a un sens métier |

**Il existe parce que `search_docs` cache quelque chose, à raison** : la recherche masque les
éditions non courantes. Sans `get_document`, l'édition antérieure de 50 documents serait
inatteignable — or comparer deux versions d'une procédure SAV est un besoin réel du support.

**Le refus doit être `perimetre_interdit`, pas `introuvable`.** Répondre « introuvable » sur
une note fermée publierait son inexistence supposée, ce qui est faux, et rendrait le
périmètre indevinable ; répondre en nommant le refus est à la fois honnête et vérifiable au
journal.

---

## `list_sources(collections)`

**À quoi il sert.** Rendre l'inventaire de ce que le corpus couvre, **tel que ce profil a le
droit de le voir**. C'est le pendant documentaire de `get_schema`.

| | |
|---|---|
| **Entrée** | `collections` (optionnel) |
| **Sortie** | par collection : le nombre de documents et d'éditions, les `doc_key`, la plage de dates. Pour les notes : **les thèmes autorisés seulement** |
| **Périmètre** | construit **depuis `filtre_index(profil)`**, jamais par un parcours du corpus |
| **Garanties** | ne publie pas l'existence des notes fermées · les effectifs qu'il annonce sont exactement ceux qu'une recherche peut atteindre |
| **Codes** | `ok` · `tool_interdit` |
| **Ne fait pas** | il ne cherche pas et ne rend aucun contenu — c'est un inventaire |

**Il rend « hors corpus » vérifiable *avant* la question.** Sans lui, un utilisateur
n'apprend les limites du corpus que par un refus, question après question. Les 8 questions
`hors_corpus` du jeu d'évaluation deviennent prévisibles au lieu d'être subies.

**Son filtrage n'est pas un confort** : un inventaire non filtré annoncerait 350 documents à
un profil `dev` qui n'en atteint que 270, et nommerait les thèmes fermés au `support`.

---

## `get_schema()`

**À quoi il sert.** Rendre le contrat de lecture de la base tel que ce profil a le droit de
le voir. C'est **le même artefact** que celui injecté dans le prompt d'`ask_database` : un
seul objet, construit par le code depuis le schéma réel et la matrice, jamais écrit à la main.

| | |
|---|---|
| **Entrée** | **aucun argument exposé** — `inputSchema` vaut `{"type": "object", "additionalProperties": false}` |
| **Sortie** | DDL filtré et commenté colonne par colonne · énumérations exactes · plage temporelle réellement couverte · conventions métier |
| **Périmètre** | les colonnes de la matrice du profil : 28 pour `commercial`, 25 pour `support` et `dev` |
| **Garanties** | ne mentionne aucune colonne hors matrice — le support ne voit ni `prix_achat_ht`, ni `marge_pct`, ni `marge_ht`, **pas même leur nom** |
| **Codes** | `ok` · `tool_interdit` |
| **Ne contient pas** | d'échantillon de lignes — il ferait fuiter des valeurs sensibles dans le prompt lui-même, en amont de toute validation |

**Pourquoi l'exposer.** Un client peut vouloir composer sa question en connaissance du
schéma, sans déclencher de génération. Et c'est le tool qui rend le périmètre
**inspectable** : un profil peut vérifier ce à quoi il a droit.

**Pourquoi `dev` l'a, et lui seul parmi les tools de base.** Il rend la **forme** ; les trois
autres tools SQL rendent du **contenu**. Un intégrateur a besoin de la première pour coder,
le contenu ne lui apprendrait rien qu'il puisse mettre dans son code. Ses colonnes sensibles
restent fermées : décrire `marge_pct` à qui ne doit pas la lire, c'est déjà en publier
l'existence et la définition.

---

## `ask_database(question)`

**À quoi il sert.** Répondre à toute question chiffrée qui n'a pas de tool figé — 22 des 24
questions du jeu d'évaluation.

| | |
|---|---|
| **`title`** | Interrogation de la base métier |
| **Description, premiers mots** | « **Base de données commerciale.** Traduit une question… » |
| **Entrée** | `question` (texte libre) — seul argument exposé |
| **Sortie nominale** | le résultat, **la requête SQL qui l'a produit**, et les conventions métier appliquées |
| **Périmètre** | toutes les colonnes de la matrice du profil — **le seul tool dont le périmètre n'est pas énumérable d'avance**, d'où la validation à chaque appel |
| **Codes** | `ok` · `clarification` · `aucune_ligne` · `ambiguite_donnees` · `hors_schema` · `ecriture_refusee` · `perimetre_interdit` · `erreur_execution` |
| **Ne fait pas** | il ne touche pas au corpus — pour un « comment » ou un « pourquoi », c'est `answer_question` |

### Garanties, et l'étape qui les porte

| Garantie | Portée par |
|---|---|
| aucune écriture ne passe | validation d'AST, contrôles 1 à 4, **puis** connexion `mode=ro` + `query_only=ON` |
| aucune colonne interdite ne sort | contrôle 5 de l'AST, sur **toute occurrence** dans l'arbre et non sur la projection, alias résolus par scope |
| la requête est renvoyée avec le résultat | systématiquement, pas sur demande — test **T1** |
| le refus est lisible, motivé, journalisé, et **nomme la colonne** | `ecriture_refusee` · `perimetre_interdit` · `hors_schema` |
| bornes d'exécution | `LIMIT` injecté s'il manque, plafond de lignes, timeout |

**La liste de mots interdits est définitivement écartée** : `VACUUM INTO` exfiltre les 156 Ko
de la base en une instruction, **sans écrire** et sans contenir aucun mot d'une liste noire.
Le risque réel est la fuite, pas l'écriture.

**Une seule passe LLM**, à sortie structurée, trois branches — `{sql}` | `{clarification}` |
`{refus}` — plus **une quatrième décision ajoutée par le code après exécution** :
l'ambiguïté de données. La clarification est **fermée** : une liste d'axes calculables
nommés et filtrés par la matrice (4 axes au `support`, 5 au `commercial`), jamais un
« pouvez-vous préciser ? ».

---

## `check_stock(ref)`

**À quoi il sert.** Le stock d'**une** référence, entrepôt par entrepôt.

| | |
|---|---|
| **`title`** | Stock d'une référence par entrepôt |
| **Entrée** | `ref` — `"pattern": "^REF-\\d{4}$"`, validé **avant** exécution ; un libellé est refusé |
| **Sortie** | une ligne par entrepôt : `entrepot`, `quantite`, `seuil_reappro`, `sous_seuil`, plus le `total` |
| **Colonnes** | `stocks.ref` `entrepot` `quantite` `seuil_reappro` · `produits.ref` `nom` — toutes ouvertes aux deux profils |
| **Garanties** | requête **écrite d'avance** : ni schéma à fournir, ni modèle à appeler, ni arbre à valider · **jamais un scalaire** |
| **Codes** | `ok` · `aucune_ligne` · `tool_interdit` · `erreur_execution` |
| **Ne fait pas** | résoudre un nom de produit. 120 références pour 52 noms — un libellé n'identifie rien |

```
check_stock("REF-8842")
  → LILLE  247  seuil 10   sous_seuil non
    LYON   100  seuil 50   sous_seuil non
    NANTES 427  seuil 20   sous_seuil non
    total  774
```

**Pourquoi le figer.** Trois critères réunis : forme unique, paramètre typé, et **sémantique
piégeuse** — 114 références sur 120 sont en plusieurs entrepôts, et l'oubli du `SUM` rend
247 au lieu de 774. `sous_seuil` n'a de sens **que par entrepôt**. Coût mesuré : 10,7 ms pour
1000 appels.

La résolution nom → référence est le **pont RAG ↔ SQL**, en amont de ce tool : elle passe
par `search_docs`.

---

## `order_status(order_id)`

**À quoi il sert.** Le statut d'**une** commande identifiée.

| | |
|---|---|
| **Entrée** | `order_id` — `"pattern": "^CMD-\\d{4}-\\d{4}$"`, validé avant exécution |
| **Sortie** | `id`, `statut`, `date_commande`, `montant_ht`, `client_id` — l'en-tête seul |
| **Colonnes** | `commandes.id` `statut` `date_commande` `montant_ht` `client_id` |
| **Garanties** | requête écrite d'avance · distingue **résultat** · **aucune ligne** · **refus** — `CMD-2026-0042` n'existe pas, et ce n'est pas une erreur |
| **Codes** | `ok` · `aucune_ligne` · `tool_interdit` · `erreur_execution` |
| **Ne renvoie pas** | le détail des lignes de vente (2,92 par commande, jusqu'à 5). Un paramètre `avec_detail` ferait deux tools dans un, avec deux lignes de matrice derrière une seule signature |

**Point assumé** : `commandes.montant_ht` est ouverte au `support`. C'est une décision, pas
un oubli — le montant d'une commande n'est ni un prix d'achat ni une marge. À signaler au
client en revanche : `montant_ht` **ignore les remises** (vérifié sur 340 / 340 commandes),
et les commandes annulées portent des lignes de vente.

---

## 6. Ce que le journal retient de chaque appel

Un événement JSONL par appel, **servi comme refusé**, append-only.

| Champ | Rôle |
|---|---|
| `ts` · `client` · `profil` | qui, quand |
| `tool` · `args` | quoi — **l'entrée, oui ; la sortie, jamais** |
| `decision` | `allowed` · `denied` · `error` |
| **`etage`** | **1, 2 ou 3 — c'est ce qui rend la défense en profondeur vérifiable** |
| `code` | l'un des douze |
| `sql` · `n_rows` | E3 : la requête exécutée est tracée |
| `citations` | E1 : les sources rendues |
| `latency_ms` | diagnostic |

**Marquer `aucune_ligne` ou `hors_corpus` en `isError` les ferait journaliser `denied`** : le
fichier censé prouver la gouvernance compterait des refus qui n'ont jamais eu lieu, et la
lecture d'E5 **surestimerait** la sévérité du système.

## 7. Vérification croisée matrice ↔ signatures

Les **31 colonnes** de la base, confrontées aux quatre tools SQL :

| Colonnes | Exposées par |
|---|---|
| `stocks.ref` `entrepot` `quantite` `seuil_reappro` · `produits.ref` `nom` | `check_stock` · `ask_database` · `get_schema` |
| `commandes.id` `statut` `date_commande` `montant_ht` `client_id` | `order_status` · `ask_database` · `get_schema` |
| `produits.categorie` `fabricant` `unite` `prix_vente_ht` `actif` · `clients.id` `raison_sociale` `segment` `ville` · `ventes.commande_id` `ref` `quantite` `prix_unitaire_ht` `remise_pct` | `ask_database` · `get_schema` |
| `produits.prix_achat_ht` `marge_pct` · `ventes.marge_ht` | `ask_database` · `get_schema`, **profil `commercial` uniquement** |
| `clients.email` | **aucun tool** — fermée aux quatre profils, motif donnée personnelle, hors E5 |
| `stocks.id` · `ventes.id` | **aucun tool** — clés techniques `AUTOINCREMENT`, exclues de la liste blanche |

Et les **quatre collections**, confrontées aux quatre tools documentaires :

| Collection | `dev` | `support` | `commercial` |
|---|:--:|:--:|:--:|
| `fiche_technique` · `notice` · `procedure_sav` | ✓ | ✓ | ✓ |
| `note_interne`, thèmes `alerte-qualite` `logistique` `retour-terrain` | ✗ | ✓ | ✓ |
| `note_interne`, thèmes `politique-tarifaire` `reunion-achat` | ✗ | ✗ | ✓ |
| **éditions courantes atteignables** | **270** | **318** | **350** |

Aucune signature de tool ne mentionne une colonne, une collection ou un thème absent de
[`matrice.yaml`](matrice.yaml).

## 8. Où la matrice s'applique, pour les huit

| Étage | Ce qu'il tranche | Nature |
|---|---|---|
| `tools/list` filtré | quels tools le client **voit** | **ergonomie** — un tool visible mais toujours refusé transforme la matrice en source d'échecs pour le LLM client |
| intercepteur d'entrée | ce profil a-t-il droit à **ce tool** ? | **garantie** — `tool_interdit` |
| dans le tool | à **ces** collections, thèmes, tables, colonnes ? | **garantie** — `perimetre_interdit`. **Seul endroit où E5 est vérifiable** |

**L'étage 3 ne fait aucune hypothèse sur l'étage 2.** Et **on refuse en nommant, on ne rogne
pas en silence** : une collection interdite demandée explicitement produit un refus, jamais
une intersection muette qui se lirait « rien à ce sujet ».

## 9. Écarts relevés en écrivant ce catalogue

Trois divergences entre `2-text-to-sql/catalogue-tools.md` et la conception consolidée. Elles
sont corrigées **ici** ; le fichier du chantier 2 n'a pas été modifié.

| # | Écart | Décision retenue |
|---|---|---|
| 1 | `get_schema` y est accordé à « commercial · support » | **`dev` l'a aussi** — `3-…/Q3.md` §9 le lui accorde explicitement. Le catalogue du chantier 2 a été écrit avant l'introduction du profil `dev` |
| 2 | `stocks.id` et `ventes.id` y sont dites « autorisées par la matrice » | **exclues.** Le catalogue lui-même recommandait de les exclure ; `Q3.md` §3 l'a fait. `matrice.yaml` suit la décision la plus récente |
| 3 | son en-tête renvoie à `flux-text-to-sql.drawio` (**V1**) | le flux à jour est [`04-chemin-text-to-sql.drawio`](04-chemin-text-to-sql.drawio) (**V3**). Écart déjà relevé par l'audit de cohérence, non refermé |

Un point ouvert, non tranché ici : le `top_k` de `search_docs` (voir sa fiche).

## Renvois

- tableau du catalogue : [`03-catalogue-tools.drawio`](03-catalogue-tools.drawio)
- quels tools exposer : [`3-…/Q1.md`](../3-exposition-mcp-et-matrice-d-acces/Q1.md)
- rédaction des descriptions : [`3-…/Q2.md`](../3-exposition-mcp-et-matrice-d-acces/Q2.md)
- matrice, forme et étages : [`3-…/Q3.md`](../3-exposition-mcp-et-matrice-d-acces/Q3.md)
- refus et journal : [`3-…/Q4.md`](../3-exposition-mcp-et-matrice-d-acces/Q4.md)
- ce qu'un client doit en faire : [`3-…/Q5.md`](../3-exposition-mcp-et-matrice-d-acces/Q5.md)
- fiches SQL d'origine : [`2-text-to-sql/catalogue-tools.md`](../2-text-to-sql/catalogue-tools.md)
- matrice exécutable : [`matrice.yaml`](matrice.yaml) · tableau : [`05-matrice-acces.drawio`](05-matrice-acces.drawio)
