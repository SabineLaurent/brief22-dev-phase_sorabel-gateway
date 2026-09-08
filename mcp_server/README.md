# Mini guide d'accès — Sorabel Data Gateway

Ce guide s'adresse à qui **branche un client MCP** sur la gateway. Il suffit à lui seul : rien
ici n'oblige à ouvrir le code. Pour les décisions d'architecture, voir
[`docs/journal-developpement.md`](../docs/journal-developpement.md) ; pour le contrat imposé
par la DSI, [`docs/cadrage_dsi.md`](../docs/cadrage_dsi.md), qui fait foi.

---

## 1. Ce que c'est

Un **serveur MCP en stdio** qui expose huit tools sur deux ensembles de données Sorabel : le
corpus documentaire (fiches techniques, notices, procédures SAV, notes internes) et la base
métier (produits, stocks, commandes, clients, ventes).

Trois choses à savoir d'emblée :

- **lecture seule de bout en bout.** Aucun tool n'écrit. Côté SQL, la connexion est ouverte en
  `mode=ro` avec `query_only`, et toute requête de modification est refusée avant exécution ;
- **le catalogue dépend du profil du processus.** Deux clients branchés sur deux processus ne
  voient pas les mêmes tools. C'est la matrice d'accès, et c'est le §3 ;
- **toute réponse est une enveloppe JSON à trois clés**, y compris les refus et les erreurs.
  Il n'y a pas de cas où la gateway rend autre chose.

Ce qu'il n'est **pas** : pas de `resources`, pas de `prompts`, pas de transport HTTP ou SSE —
stdio uniquement. Pas de streaming, pas de tâches longues.

---

## 2. Se brancher

### Prérequis

**Python 3.11** (le projet est épinglé `>=3.11,<3.12`), **[uv](https://docs.astral.sh/uv/)**
et **Docker** — ce dernier pour la seule base vectorielle.

```bash
uv sync --extra vector        # l'extra est nécessaire : sans lui l'embedder local casse
cp .env.example .env          # aucune valeur du modèle n'est un secret
make up                       # Chroma, via docker compose, port 8002
make seed                     # génère data/sorabel.db
make ingest                   # indexe le corpus (~400 éditions)
```

`.env` n'est pas obligatoire : **les vingt réglages ont un défaut**. Il le devient pour les
appels de modèle — `AZURE_AI_ENDPOINT`, `AZURE_AI_API_KEY`, `LLM_CHAT_MODEL` — dont dépendent
`answer_question` (la rédaction) et `ask_database` (la génération SQL). **Les six autres tools
fonctionnent sans** : la recherche et le reclassement tournent en local par défaut.

### Le bloc de configuration

À coller dans la configuration de votre client MCP :

```json
{
  "mcpServers": {
    "sorabel": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_server.server"],
      "cwd": "/chemin/absolu/vers/brief22-dev-phase_sorabel-gateway",
      "env": {
        "SORABEL_PROFILE": "commercial",
        "TOKENIZERS_PARALLELISM": "false"
      }
    }
  }
}
```

`cwd` est obligatoire : le serveur résout le corpus, la base et la matrice relativement à la
racine du dépôt. `TOKENIZERS_PARALLELISM` n'est pas fonctionnel — il fait taire un
avertissement de la bibliothèque d'embeddings qui, sinon, encombre la console du client.

> **Préférez ce bloc à une commande en ligne de commande.** Certains clients — l'Inspector
> officiel en fait partie — analysent les arguments de la commande et **avalent le `-m`**, ce
> qui lance `python` sans module : le processus lit alors le JSON-RPC sur son entrée standard
> et le prend pour du code. Le symptôme est un `NameError: name 'true' is not defined` suivi
> d'un délai d'attente dépassé. Le bloc de configuration n'a pas ce problème.

### Vérifier que ça répond

```bash
make serve                    # le serveur, en stdio, profil dans SORABEL_PROFILE
make client                   # un client de test : le catalogue du profil
PROFILE=commercial make client
```

Avec l'[Inspector officiel](https://modelcontextprotocol.io), en enregistrant le bloc ci-dessus
dans un fichier :

```bash
npx @modelcontextprotocol/inspector --cli \
  --config mon-serveur.json --server sorabel --method tools/list --format json
```

---

## 3. Choisir son profil

Le profil se pose dans **`SORABEL_PROFILE`**, dans l'environnement du processus serveur. Il
est lu **une seule fois, au chargement du module**, et un client n'a aucun moyen d'en changer.

Ce n'est pas un détail d'implémentation, c'est la garantie elle-même : un profil passé en
argument de tool figurerait dans l'`inputSchema`, donc serait **rempli par le modèle** ; un
profil passé en en-tête serait **déclaré par l'appelant**. Ici, il est décidé par qui lance le
processus. Un client par profil, un processus par client.

Valeur par défaut : `support`. Un profil inconnu ou mal orthographié n'est pas une erreur — il
retombe sur `default`, qui n'a **aucun** tool. Un catalogue vide est donc le symptôme d'un nom
de profil erroné.

### Profil × tools

| Tool | `default` | `dev` | `support` | `commercial` | `admin` |
|---|:--:|:--:|:--:|:--:|:--:|
| `answer_question` | | ✔ | ✔ | ✔ | ✔ |
| `search_docs` | | ✔ | ✔ | ✔ | ✔ |
| `get_document` | | ✔ | ✔ | ✔ | ✔ |
| `list_sources` | | ✔ | ✔ | ✔ | ✔ |
| `ask_database` | | | ✔ | ✔ | ✔ |
| `get_schema` | | ✔ | | ✔ | ✔ |
| `check_stock` | | | ✔ | ✔ | ✔ |
| `order_status` | | | ✔ | ✔ | ✔ |
| **total** | **0** | **5** | **7** | **8** | **8** |

Le profil borne aussi ce que les tools **atteignent**, pas seulement ceux qu'ils voient :

| Profil | Collections documentaires | Éditions atteignables | Colonnes SQL |
|---|---|---:|---:|
| `default` | aucune | 0 | 0 |
| `dev` | fiches, notices, SAV — **pas les notes** | 270 | 25 |
| `support` | les quatre, notes sur 3 thèmes | 318 | 25 |
| `commercial` | les quatre, notes sur 5 thèmes | 350 | 28 |
| `admin` | idem `commercial` | 350 | 28 |

Les trois colonnes qui séparent `commercial` de `support` sont `produits.prix_achat_ht`,
`produits.marge_pct` et `ventes.marge_ht`. Elles sont fermées **ensemble** : chacune se dérive
des autres, donc en ouvrir une revient à ouvrir les trois. `clients.email` est fermée aux cinq
profils, pour un motif de protection des données et non d'accès.

Ce tableau se régénère plutôt que se recopier :

```bash
for p in default dev support commercial admin; do
  printf "%-11s %s\n" "$p" "$(uv run python scripts/mcp_client.py --profile $p | grep -c '^  ')"
done
```

---

## 4. Le catalogue

Huit tools, tous en lecture seule (`readOnlyHint`, `idempotentHint`), tous rendant la même
enveloppe.

### Documentaire

| Tool | Arguments | Rend | Quand ce n'est pas lui |
|---|---|---|---|
| `answer_question` | `question` (requis), `collections` | une réponse rédigée et ses sources | pour les extraits bruts : `search_docs` ; pour un chiffre ou un état : `ask_database` |
| `search_docs` | `query` (requis), `collections` | les extraits classés, avec métadonnées, **sans rédaction** | pour une réponse rédigée : `answer_question` ; pour un texte intégral : `get_document` |
| `get_document` | `doc_id` (requis), `version` | le texte complet et les métadonnées d'une édition | n'accepte **ni** une question en langage naturel **ni** une référence produit `REF-NNNN` |
| `list_sources` | `collections` | l'inventaire de ce qui est accessible, sans recherche | pour chercher : `search_docs` ou `answer_question` |

`doc_id` est celui que rendent `search_docs` et `list_sources` (par exemple
`fiches/REF-8842-v2.1`). Sans `version`, c'est l'édition courante. Une référence produit
`REF-NNNN` n'en est **pas** un : `get_document` répond alors `introuvable`, ce qui est une
non-réponse et non un refus.

### Base métier

| Tool | Arguments | Rend | Quand ce n'est pas lui |
|---|---|---|---|
| `ask_database` | `question` (requis) | le résultat **et la requête SQL exécutée** | stock d'une référence : `check_stock` ; une commande : `order_status` |
| `get_schema` | — | le schéma lisible par ce profil, sans lire de données | pour un résultat : `ask_database` |
| `check_stock` | `reference` (requis, `REF-NNNN`) | le stock par entrepôt, avec le seuil de réapprovisionnement | n'accepte **pas** un nom de produit ; pour les caractéristiques d'une référence : `answer_question` |
| `order_status` | `order_id` (requis, `CMD-AAAA-NNNN`) | l'en-tête d'une commande | plusieurs commandes ou un agrégat : `ask_database` |

`get_schema` est **filtré par le profil** : les colonnes fermées n'y figurent pas. C'est le
moyen de connaître son périmètre avant de poser une question — le pendant SQL de
`list_sources`.

### Les descriptions servies, et pourquoi elles ne sont pas les mêmes pour tous

La description que `tools/list` rend pour chaque tool suit **cinq rubriques**, dans cet
ordre : `Objet`, `Entrée`, `Sortie`, `Utiliser quand`, `Ne pas utiliser quand`. Les quatre
premières sont constantes. **La cinquième dépend du profil**, et c'est délibéré : les renvois
qu'elle porte — la colonne « quand ce n'est pas lui » du tableau ci-dessus — ne sont servis
que si leur cible est dans votre catalogue.

Un exemple, sur le même tool : à `commercial`, `get_schema` se termine par « Pour obtenir un
résultat, utiliser `ask_database` » ; à `dev`, qui n'a pas `ask_database`, cette phrase
**n'apparaît pas**. Le motif est le même que pour le catalogue lui-même — nommer un tool à qui
ne l'a pas en publie l'existence, et invite un modèle à renoncer en cherchant un outil qu'il ne
trouvera jamais.

**Conséquence pour vous** : ne recopiez pas ces descriptions dans votre prompt système, et ne
les mettez pas en cache d'un profil à l'autre. Lisez-les de `tools/list`, à chaque session, et
passez-les telles quelles à votre modèle.

### L'argument `collections`

Un tableau de chaînes libres parmi `fiche_technique`, `notice`, `procedure_sav`,
`note_interne`. Il **restreint** le périmètre du profil, il ne le définit jamais : le profil
est le plafond, cet argument ne peut que descendre en dessous. Omettez-le pour chercher dans
tout ce qui est accessible.

Demander une collection fermée à votre profil produit un **refus**, pas un résultat vide : un
rognage silencieux se lirait « rien à ce sujet », ce qui est faux et sans recours.

---

## 5. Lire une réponse

Toute réponse est un objet à **trois clés, toujours les trois** :

```json
{"status": "…", "payload": {"code": "…", "…": "…"}, "message": "…"}
```

Il arrive en deux exemplaires dans le `CallToolResult` : dans `structuredContent`, et sérialisé
dans le premier bloc de texte. **Lisez `structuredContent`** — le bloc texte n'existe que pour
la compatibilité des clients qui ne savent pas lire l'autre.

Chaque tool publie son `outputSchema` dans `tools/list` : vous pouvez le valider.

### Les cinq statuts

| `status` | Sens | Ce que le client doit faire |
|---|---|---|
| `ok` | servi | afficher le payload |
| `clarification` | la question admet plusieurs lectures | afficher `message` **et** `payload.axes` |
| `hors_corpus` | le corpus ne porte pas la réponse — **ce n'est pas un refus** | afficher `message`, ne rien compléter |
| `refused` | la gouvernance a tranché | afficher `message`, **ne pas réessayer** |
| `error` | l'exécution a échoué | afficher `message`, réessayer plus tard |

### Les douze codes

`payload.code` est **toujours présent** et plus fin que `status`. C'est lui le discriminant.

| Code | `status` | Sens | Ce qu'il ne faut **jamais** faire |
|---|---|---|---|
| `ok` | `ok` | résultat nominal | — |
| `aucune_ligne` | `ok` | la clé est bien formée, la donnée n'existe pas | dire « erreur » : la gateway a fait ce qu'on demandait |
| `introuvable` | `ok` | aucun document ne porte cet identifiant | idem |
| `ambiguite_donnees` | `ok` | plusieurs enregistrements là où un était attendu | n'en montrer qu'un : ils sont tous rendus |
| `clarification` | `clarification` | ambiguïté de **question** | choisir un axe à la place de l'utilisateur |
| `hors_corpus` | `hors_corpus` | aucun document au-dessus du seuil | **compléter avec ses propres connaissances** |
| `contexte_insuffisant` | `hors_corpus` | des documents trouvés, mais ils ne répondent pas | idem |
| `tool_interdit` | `refused` | ce profil n'a pas ce tool | réessayer, ou deviner pourquoi |
| `perimetre_interdit` | `refused` | la cible est hors du périmètre du profil | réessayer avec un autre argument au hasard |
| `ecriture_refusee` | `refused` | une modification a été demandée | reformuler pour contourner |
| `hors_schema` | `refused` | la question ne porte pas sur les données disponibles | insister |
| `erreur_execution` | `error` | panne, délai dépassé, argument mal formé | présenter comme une absence de donnée |

**Sur `hors_corpus`, `contexte_insuffisant` et les quatre refus, la clé de charge utile est
absente** — pas vide : absente. Il n'y a ni `answer`, ni `rows`. C'est structurel, et
l'`outputSchema` le déclare : un client n'a donc rien à afficher, et ne peut pas rendre un
refus comme une réponse en oubliant d'y penser.

### `isError` ne suffit pas

MCP n'a **aucun équivalent de `403` ni de `404`** : le protocole n'offre qu'un booléen,
`isError`, et des codes JSON-RPC de structure. C'est pour cela que les douze codes ci-dessus
existent — ils jouent dans le payload le rôle qu'un code HTTP joue nativement.

La gateway pose `isError: true` **sur le seul `erreur_execution`**, où quelque chose a
réellement échoué et où réessayer a un sens. Un refus de droits rend `isError: false` : c'est
un résultat abouti, et le marquer inviterait à réessayer à l'identique.

**Branchez donc sur `status`, puis sur `payload.code`. Jamais sur `isError` seul** : il ne
distingue pas un refus d'une réponse.

### Plusieurs appels dans un même tour : ce qui est `ok` se rend

Un tour peut appeler plusieurs tools — c'est même recommandé sur une référence produit donnée
seule, qui a une fiche *et* un stock. Vous obtenez alors plusieurs enveloppes, et la règle
d'affichage n'est pas évidente :

> **Une enveloppe non-`ok` ne doit pas effacer une enveloppe `ok` obtenue dans le même tour.**

Un `status` `ok` signifie que l'appel a franchi les trois étages : la donnée est autorisée. La
retenir à l'écran ne protège rien — ça prive votre utilisateur de ce à quoi il a droit. Ce qui
n'a pas abouti se dit **à côté**, avec son `message` tel quel.

La substitution reste la bonne réponse quand **rien** n'a été servi : le tour n'a alors qu'une
chose à dire, et c'est la phrase figée.

C'est un défaut que ce dépôt a commis puis mesuré chez lui, 3 fois sur 3 : sur une référence
inexistante, une non-réponse documentaire écrasait le résultat de la base, qui disait pourtant
quelque chose de juste. Attention en particulier à l'asymétrie des deux domaines — côté SQL,
« aucune ligne » porte le statut **`ok`** ; côté documentaire, « rien trouvé » porte
`hors_corpus`. Deux non-réponses, deux statuts.

### La clause à mettre dans votre prompt système

Si votre client est un agent LLM, cette clause suffit :

```
Les outils dont tu disposes sont ceux que `tools/list` te rend, et ils sont déjà
filtrés : n'en évoque aucun autre, et n'énumère jamais de noms d'outils dans ton
prompt système — le catalogue est décidé par la connexion, pas par toi.

Quand un tool rend un `status` autre que `ok` :
  - ne complète jamais avec tes propres connaissances ;
  - rends le `message` tel quel, sans le reformuler ni l'adoucir ;
  - ne présente pas un refus comme une absence de donnée.
```

La première clause n'est pas de la prudence rhétorique : c'est le défaut que ce dépôt a
commis puis mesuré chez lui. Un prompt qui énumérait les huit tools apprenait au modèle
l'existence de ceux qu'il n'avait pas, et il le disait à l'utilisateur — « je n'ai pas accès à
l'outil de consultation de stock ». Le serveur vous sert la même consigne dans le champ
`instructions` de `initialize` ; la reprendre ici vous évite d'avoir à la lire pour en
bénéficier.

---

## 6. Les citations

Sur `answer_question`, `payload.sources` porte les documents effectivement utilisés, avec
`titre`, `reference`, `version`, `date` et `doc_key`.

**Elles ne sont pas rédigées par le modèle.** Il ne rend que les *numéros* des extraits qu'il a
consultés ; les références sont construites en Python depuis les métadonnées de l'index. Il ne
peut donc ni citer un document qu'on ne lui a pas montré, ni inventer une référence.

Deux obligations en découlent pour un client : **afficher les citations reçues** — un résumé
qui les laisse tomber détruit la seule traçabilité de la réponse — et **n'en fabriquer
aucune**. `reference` est garantie non vide : pour les éditions qui ne portent pas de référence
produit, elle retombe sur le `doc_key`, qui identifie le document exactement.

`doc_key` permet de rappeler l'édition par `get_document`.

---

## 7. Ce que le serveur garantit — et ce qu'il ne garantit pas

**Trois étages d'accès**, qui se cumulent :

1. le **catalogue** — `tools/list` ne rend que les tools du profil ;
2. le **droit d'appeler** — un tool absent du catalogue, appelé quand même, est refusé et
   journalisé ;
3. le **périmètre** — collections, thèmes de notes et colonnes SQL, vérifiés à chaque appel.

**Tout appel est journalisé**, servi comme refusé, arguments compris. Le journal est en JSONL
(`GATEWAY_JOURNAL`, par défaut `logs/journal.jsonl`) et n'est lisible que par le profil
`admin`.

**Aucune écriture SQL ne passe** : six contrôles sur l'arbre de la requête, puis une connexion
`mode=ro` avec `query_only` réarmé, puis des bornes sur le résultat.

En revanche :

- **`readOnlyHint` est une déclaration du serveur, pas une garantie vérifiable par vous.**
  L'annotation dit « ce tool ne modifie rien » ; rien dans le protocole ne l'atteste. Ce qui la
  tient est la matrice et les contrôles SQL, c'est-à-dire du code que vous ne voyez pas. Un
  client ne devrait jamais faire reposer une décision de sécurité sur une annotation MCP,
  d'aucun serveur ;
- les **réponses rédigées** passent par un modèle de langage : elles ne sont pas déterministes.
  Les refus déterministes le sont — le seuil documentaire et les trois étages ne dépendent
  d'aucun modèle ;
- le périmètre est celui de la **matrice au moment de l'appel** (`mcp_server/matrice.yaml`).
  C'est un fichier de configuration versionné : il peut changer sans que le protocole en
  informe votre client ;
- **ce que le serveur vous dit de faire, il ne peut pas vous le faire faire.** Les
  `instructions` de l'`initialize` et les descriptions des tools sont des *recommandations* —
  la spec le dit d'ailleurs mot pour mot pour les premières, « clients **may** use this
  information ». Même asymétrie que `readOnlyHint`, dans l'autre sens : là c'était nous qui
  déclarions sans preuve, ici c'est vous qui appliquez sans contrainte.
  Concrètement, si votre prompt système énumère les huit tools de ce guide, votre modèle
  apprendra l'existence de ceux que votre profil n'a pas, et il en parlera à vos utilisateurs
  — **c'est arrivé dans le client de ce dépôt, et c'est ce qui a été mesuré : 4 cellules sur 20
  annonçaient un outil absent**. Le serveur ne peut pas l'empêcher.
  Ce qui est garanti **quel que soit votre client** est ailleurs, et n'a besoin d'aucune
  coopération de votre part : les trois étages, le journal, et les phrases figées qui voyagent
  **dans l'enveloppe** — vous pouvez les reformuler, vous ne pouvez pas les fabriquer. Le pire
  qu'un client négligent obtienne est de mal *raconter* un refus, jamais d'obtenir une donnée
  fermée.

Les preuves chiffrées de ces garanties sont publiées, chacune avec la commande qui la refait :
[gain de la recherche](../eval/rapport_gain.md) ·
[conformité SQL](../eval/rapport_sql.md) ·
[refus documentaire](../eval/rapport_refus.md) ·
[périmètre documentaire](../eval/rapport_perimetre.md) ·
[journalisation et colonnes fermées](../eval/rapport_acces.md).

---

## 8. Limites pratiques

| | |
|---|---|
| Poignée de main (`initialize`) | ~0,6 s |
| Premier appel de recherche | **~8 s** — l'embedder et le reranker se chargent à ce moment |
| Appels de recherche suivants | ~0,16 s |
| Lignes rendues par une requête SQL | 200 par défaut, 1000 au maximum |
| Délai d'une requête SQL | 5 s |

Le premier appel documentaire est lent **par conception** : charger les modèles à l'import
dépasserait le délai d'`initialize`. Ce n'est pas un incident, et il ne se reproduit pas.

**Sur un argument invalide, vous recevez une enveloppe, jamais une trace technique.** Un
argument hors format (`check_stock` avec un nom de produit), un argument requis absent, un
mauvais type ou un tool hors catalogue rendent `erreur_execution` avec `isError: true`, la
phrase figée correspondante — et une ligne de journal. Le détail technique part au journal, pas
au client.

`read_journal` n'est **pas** un tool MCP : c'est un droit de la matrice, exposé par l'API du
banc d'essai, pas par ce serveur.

---

## 9. Démontrer deux profils

```bash
PROFILE=support make client
PROFILE=commercial make client
```

`support` voit sept tools, `commercial` les huit — la différence est `get_schema`. Puis un
appel qui aboutit et un appel qui est refusé, sur le même tool et le même argument :

```bash
# servi : commercial lit les marges
uv run python scripts/mcp_client.py --profile commercial \
  --tool ask_database --args '{"question": "Quelle est la marge moyenne par produit ?"}'

# refusé : support ne les lit pas — même tool, même question
uv run python scripts/mcp_client.py --profile support \
  --tool ask_database --args '{"question": "Quelle est la marge moyenne par produit ?"}'
```

Le second rend `status: "refused"`, `code: "perimetre_interdit"`, et **pas de `rows`**. Le refus
porte sur le périmètre, pas sur le tool : `support` a bien le droit d'interroger la base.

Le journal des deux appels :

```bash
make journal
```

---

## 10. Écarts assumés

Le dossier de conception et la note de cadrage DSI ne coïncident pas partout avec ce que le
serveur sert. Les écarts sont décidés et motivés, chacun consigné au journal de développement.

| Écart | Raison |
|---|---|
| Le payload sert **plus de clés** que le cadrage n'en énumère : `code` partout, `conventions` et `truncated` sur `ask_database`, cinq clés de citation là où il en nomme trois | ajouts, jamais retraits : un client écrit sur le cadrage trouve toujours ce qu'il cherche |
| Les noms de champs sont ceux du cadrage (`answer`, `sources`) et non ceux du catalogue conçu (`reponse`, `citations`) | le cadrage est le contrat imposé, et la suite d'acceptance le lit littéralement |
| Le champ `hint` prévu par la conception **n'existe pas** | le cadrage ne le prévoit pas ; sa fonction est tenue par les descriptions des tools, qui nomment déjà le recours |
| `isError` est posé sur **un** code, là où la conception en marquait cinq | c'est un canal de correction : un refus de droits n'a rien à corriger. Voir §5 |
| `support` accède aux notes internes, que le cadrage lui ferme | le grain de fermeture est le **thème**, pas la collection : fermer la collection priverait le support de ses notes d'alerte qualité tout en laissant passer d'autres notes sensibles |
| `support` accède à la table `ventes`, que le cadrage déclare inaccessible | E5 ferme des **colonnes**, pas une table. `ventes.marge_ht` est fermée ; le reste de la table est légitime pour du support |

---

*Le catalogue publié par `tools/list` fait foi sur les arguments et les schémas : ce guide le
décrit, il ne le remplace pas.*
