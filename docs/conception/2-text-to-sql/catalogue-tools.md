# Catalogue des tools SQL — chantier Text-to-SQL

> Second livrable intermédiaire du chantier 2, pendant du
> [flux](flux-text-to-sql.drawio). Les nœuds cités (`N1`, `N4`, `S1`…) sont ceux du flux ;
> les colonnes citées sont celles de la matrice de [Q3](Q3.md) §3.
>
> **Quatre tools, pas cinq.** Le périmètre et sa justification sont en [Q4](Q4.md) §7.
>
> **Deux corrections portées depuis l'audit de cohérence**
> ([../audit-coherence.md](../audit-coherence.md), D1 et D3) : le paramètre `profil` a
> disparu des signatures exposées — il est lu par le serveur dans son environnement de
> lancement ([../3-exposition-mcp-et-matrice-d-acces/Q3.md](../3-exposition-mcp-et-matrice-d-acces/Q3.md) §2),
> et un paramètre présent dans l'`inputSchema` **serait** rempli par le LLM du client ; et la
> révision de spécification citée est désormais **2026-07-28**, celle qui déplace la
> validation d'entrée hors du protocole. Les signatures de ce document ne décrivent donc plus
> que ce qu'un client peut écrire ; `profil` reste un argument des fonctions internes.

## Vue d'ensemble

| Tool | Nature | Génère du SQL ? | Nœuds traversés | Profils |
|---|---|---|---|---|
| `get_schema` | aide | non | N1 → N2 | commercial · support |
| `ask_database` | génératif | **oui** | N1 → N2 → N3 → N4 → N5 → N6 → N7 | commercial · support |
| `check_stock` | figé | non | N1 → N6 → N7 | commercial · support |
| `order_status` | figé | non | N1 → N6 → N7 | commercial · support |

Les quatre passent par **N1** (matrice d'accès) et alimentent **J** (journal E5). Aucun
n'y échappe, y compris les tools figés : la différence est *quand* leur périmètre est
vérifié, pas *s'il* l'est.

## Qui choisit le tool ?

**Le serveur ne reçoit jamais une question à router.** Il reçoit un `tools/call` : un nom
de tool et des arguments déjà typés. La spécification MCP (**2026-07-28**, *server/tools*,
§« User Interaction Model ») est explicite — les tools sont *model-controlled* : *« Tools in
MCP are designed to be model-controlled, meaning that the language model can discover and
invoke tools automatically based on its contextual understanding and the user's prompts »*.
Son diagramme de flux nomme les trois temps : **Discovery** (`tools/list`), **Tool
Selection** (« LLM → Client : Select tool to use »), **Invocation** (`tools/call`).

La chaîne réelle, pour « quels sont les stocks de la référence REF-8842 ? » :

1. **l'utilisateur** pose sa question à son application — il ne choisit aucun tool, et
   n'a pas à savoir que ce catalogue existe ;
2. **l'application cliente** (bot Slack du support, IDE, poste commercial) a listé les
   tools par `tools/list` ; elle donne à *son* LLM la question **et les descriptions
   ci-dessous**. C'est ce LLM qui tranche : `check_stock(ref="REF-8842")` plutôt que
   `ask_database` ;
3. **le serveur** reçoit l'appel déjà nommé et déjà paramétré.

Le mot « client », dans ce dossier comme dans le brief, désigne donc l'application, pas la
personne. Le [flux](flux-text-to-sql.drawio) ne représente pas les deux premières étapes :
il commence à la frontière du serveur.

**Trois conséquences pour ce catalogue :**

- `ask_database` est le **seul** tool dont un argument est une question en langage naturel ;
  les trois autres reçoivent une valeur typée. La distinction décide de ce que **N4** a à
  valider — et de ce qu'il n'a pas à valider pour les tools figés ;
- le seul levier du serveur sur cet aiguillage est **la rédaction des descriptions**. Si
  `check_stock` ne dit pas qu'il rend le stock *par entrepôt*, le LLM du client enverra la
  question à `ask_database`, qui générera du SQL là où une requête écrite d'avance
  suffisait — et les 114 références présentes dans plusieurs entrepôts (Q4 §1) rendront la
  réponse fausse ou incomplète ;
- le serveur ne peut donc pas **compter** sur un bon aiguillage. `ask_database` doit rester
  capable de répondre à « quel est le stock de REF-8842 ? ». Le figement est une garantie
  de forme et de coût, jamais un préalable au fonctionnement.

C'est la raison pour laquelle « comment décrire les tools pour que les clients et leurs LLM
choisissent le bon » est une question du chantier MCP, et non un détail de rédaction.

---

## `get_schema()`

**À quoi il sert.** Renvoyer le contrat de lecture de la base tel que ce profil a le droit
de le voir. C'est le même artefact que celui injecté dans le prompt de `ask_database`
(Q1 §« Où vit cet artefact ») : un seul objet, construit par le code depuis le schéma réel
et la matrice, jamais écrit à la main.

| | |
|---|---|
| **Entrée** | **aucun argument exposé.** Le profil est lu par le serveur dans son environnement de lancement, jamais reçu du client — `inputSchema` vaut `{"type": "object", "additionalProperties": false}`, la forme que la spécification recommande pour un tool sans paramètre |
| **Sortie** | DDL filtré et commenté · énumérations exactes · plage temporelle · conventions métier |
| **Garantie** | ne mentionne aucune colonne hors matrice du profil — le support ne voit ni `prix_achat_ht`, ni `marge_pct`, ni `marge_ht`, **pas même leur nom** |
| **Ne contient pas** | d'échantillon de lignes — il ferait fuiter des valeurs sensibles dans le prompt lui-même, en amont de toute validation (Q1) |

**Pourquoi l'exposer.** Un client (un IDE, un agent) peut vouloir composer sa question en
connaissance du schéma, sans déclencher de génération. Et c'est le tool qui rend le
périmètre **inspectable** : un profil peut vérifier ce à quoi il a droit.

---

## `ask_database(question)`

**À quoi il sert.** Répondre à toute question qui n'a pas de tool figé — 22 des 24
questions du jeu d'évaluation.

| | |
|---|---|
| **Entrée** | `question` (texte libre) — **seul argument exposé** ; le profil vient du serveur |
| **Sortie nominale** | `{résultat, requête_sql, conventions_appliquées}` — **S1** |
| **Autres sorties** | `clarification` (C1) · `aucune_ligne` (A1) · `ambiguïté_de_données` (A2) · trois refus · erreur d'exécution (R4) |
| **Colonnes** | toutes celles de la matrice du profil — c'est le seul tool dont le périmètre n'est pas énumérable d'avance, d'où la validation à chaque appel |

### Garanties, et le nœud qui les porte

| Garantie | Portée par |
|---|---|
| aucune écriture ne passe | **N4** contrôles 1-4, puis N6 (connexion `mode=ro` + `query_only`) |
| aucune colonne interdite ne sort | **N4** contrôle 5, alias de table résolus par scope (Q3 §5) |
| la requête est renvoyée avec le résultat | **S1** — systématiquement, pas sur demande |
| le refus est lisible, motivé, journalisé | **R1 · R2 · R3** → **J** |
| bornes d'exécution | **N5** (LIMIT injecté) et **N6** (timeout, plafond de lignes) |

### Codes de sortie

| Code | Cas | Exemple du jeu |
|---|---|---|
| `ok` | résultat nominal | SQL-01 |
| `clarification` | ambiguïté de question, axes proposés | SQL-23, SQL-24 |
| `aucune_ligne` | clé bien formée, absente | SQL-08 |
| `ambiguite_donnees` | plusieurs lignes là où une est attendue | SQL-10, SQL-18 |
| `hors_schema` | la question ne porte pas sur la base | SQL-21, SQL-22 |
| `ecriture_refusee` | demande de modification | SQL-13 → 16 |
| `perimetre_interdit` | hors matrice du profil | SQL-17 → 20 |
| `erreur_execution` | timeout, plafond atteint | — |

Trois d'entre eux sont des **refus** — `hors_schema`, `ecriture_refusee`,
`perimetre_interdit` : la requête n'a pas été exécutée. `erreur_execution` n'en est pas un,
c'est un échec technique ; `clarification`, `aucune_ligne` et `ambiguite_donnees` sont des
**résultats**. Les confondre produit une réponse fausse au sens métier même avec un code
irréprochable (Q5 §6).

> Ces codes sont ceux du seul `ask_database`. Le vocabulaire complet des huit tools, la
> forme MCP du refus (`isError`) et le journal sont établis au chantier 3,
> [Q4](../3-exposition-mcp-et-matrice-d-acces/Q4.md).

---

## `check_stock(ref)`

**À quoi il sert.** Le stock d'une référence, entrepôt par entrepôt.

| | |
|---|---|
| **Entrée** | `ref` — validée contre `REF-\d{4}` **avant** exécution ; un libellé est refusé |
| **Sortie** | une ligne par entrepôt : `entrepot`, `quantite`, `seuil_reappro`, `sous_seuil` · plus `total` |
| **Colonnes** | `stocks.ref` `stocks.entrepot` `stocks.quantite` `stocks.seuil_reappro` · `produits.ref` `produits.nom` — **toutes ouvertes aux deux profils** |
| **Garantie** | jamais un scalaire : 114 références sur 120 sont en plusieurs entrepôts, et `sous_seuil` n'a de sens **que par entrepôt** (Q4 §3) |

```
check_stock("REF-8842")
  → LILLE  247  seuil 10   sous_seuil non
    LYON   100  seuil 50   sous_seuil non
    NANTES 427  seuil 20   sous_seuil non
    total  774
```

**Ce qu'il ne fait pas** : résoudre un nom de produit. 120 références pour 52 noms — un
libellé n'identifie rien. La résolution nom → références est le **pont RAG ↔ SQL**, en
amont de ce tool.

---

## `order_status(order_id)`

**À quoi il sert.** Le statut d'une commande.

| | |
|---|---|
| **Entrée** | `order_id` — validé contre `CMD-\d{4}-\d{4}` avant exécution |
| **Sortie** | `id`, `statut`, `date_commande`, `montant_ht`, `client_id` — l'en-tête seul |
| **Colonnes** | `commandes.id` `commandes.statut` `commandes.date_commande` `commandes.montant_ht` `commandes.client_id` |
| **Garantie** | distingue *résultat* · *aucune ligne* · *refus* — `CMD-2026-0042` n'existe pas et n'est pas une erreur (Q4 §5) |

**Ce qu'il ne renvoie pas** : le détail des lignes de vente (2,92 par commande, jusqu'à 5).
Un paramètre `avec_detail` ferait deux tools dans un, avec deux lignes de matrice derrière
une seule signature.

**Point assumé** : `commandes.montant_ht` est ouverte au support d'après la matrice de
Q3 §3. C'est une décision, pas un oubli — le montant d'une commande n'est ni un prix
d'achat ni une marge.

---

## Vérification croisée matrice ↔ signatures

Les **31 colonnes** de la base, confrontées aux quatre tools :

| Colonnes | Exposées par |
|---|---|
| `stocks.ref` `entrepot` `quantite` `seuil_reappro` · `produits.ref` `nom` | `check_stock`, `ask_database`, `get_schema` |
| `commandes.id` `statut` `date_commande` `montant_ht` `client_id` | `order_status`, `ask_database`, `get_schema` |
| `produits.categorie` `fabricant` `unite` `prix_vente_ht` `actif` · `clients.id` `raison_sociale` `segment` `ville` · `ventes.commande_id` `ref` `quantite` `prix_unitaire_ht` `remise_pct` | `ask_database`, `get_schema` |
| `produits.prix_achat_ht` `marge_pct` · `ventes.marge_ht` | `ask_database` et `get_schema`, **profil commercial uniquement** |
| `clients.email` | **aucun tool** — fermée aux deux profils, motif donnée personnelle |
| `stocks.id` `ventes.id` | **aucun tool** — clés techniques `AUTOINCREMENT`, sans usage métier |

**Deux constats à trancher, pas des erreurs :**

1. `stocks.id` et `ventes.id` sont autorisées par la matrice et n'apparaissent dans aucune
   sortie de tool. Inoffensives, mais une liste blanche stricte devrait les exclure : rien
   ne les rend utiles à une question métier ;
2. `clients.email` est la seule colonne fermée aux **deux** profils. Elle sort donc du
   cadre E5 (confidentialité commerciale) et relève d'un autre motif de journalisation.

Aucune signature de tool ne mentionne une colonne absente de la matrice.

## Renvois

- Le **flux** et le rattachement des quatre tests d'acceptance — [flux-text-to-sql.drawio](flux-text-to-sql.drawio)
- La **matrice `profil × (table, colonne)`** — [Q3](Q3.md) §3
- Le **critère de figement** et le troisième tool écarté — [Q4](Q4.md) §1 et §7
- Les **cinq issues non confondues** — [Q5](Q5.md) §6
- Les **tools RAG** (`answer_question`, `search_docs`, `get_document`, `list_sources`) et
  la matrice `client × tool` — chantier MCP
