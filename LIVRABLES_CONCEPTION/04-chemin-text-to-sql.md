# Chemin Text-to-SQL — diagramme de séquence

> Ce document est le **livrable** « chemin Text-to-SQL » du brief, dans sa forme séquence :
> question → génération → validation → exécution lecture seule → **résultat + requête**.
>
> Le schéma de flux du même chemin, avec ses refus, ses sorties latérales et ses pannes, est
> en drawio : [`04-chemin-text-to-sql.drawio`](04-chemin-text-to-sql.drawio) (**V3**).
> Les décisions sont argumentées dans [`2-text-to-sql/`](../2-text-to-sql/) `Q1` → `Q5`.

## 1. Le chemin nominal, et ses huit sorties

Un diagramme de séquence dit **qui parle à qui, et dans quel ordre** — ce que le schéma de
flux ne montre pas. On y lit en particulier que **le LLM n'est appelé qu'une fois**, et
qu'il est appelé **après** que la matrice a borné le périmètre, jamais avant.

```mermaid
sequenceDiagram
    autonumber
    actor U as Utilisateur
    participant C as Client MCP
    participant S as Serveur MCP
    participant M as autoriser sur matrice.yaml
    participant L as LLM de génération
    participant G as sqlglot
    participant D as SQLite en mode=ro
    participant J as Journal JSONL

    Note over S: SORABEL_PROFILE est lu au lancement.<br/>Le client ne déclare jamais son profil.

    U->>C: « quel est le chiffre d'affaires de mai 2026 ? »
    C->>S: tools/call ask_database avec question

    rect rgb(213, 232, 212)
    S->>M: étage 2 — ce profil a-t-il ce tool ?
    end
    alt profil absent, inconnu, ou tool non accordé
        S->>J: decision=denied, etage=2, code=tool_interdit
        S-->>C: isError, code=tool_interdit
        C-->>U: refus nommé
    end

    rect rgb(213, 232, 212)
    S->>M: N1 — périmètre de ce profil : tables et colonnes
    M-->>S: liste blanche des couples table-colonne
    end
    S->>S: N2 — construit le contrat de lecture<br/>DDL filtré, énumérations, plage, conventions

    Note over S,L: Aucun échantillon de lignes n'entre dans le prompt.<br/>prix_achat_ht fuirait en amont de toute validation.

    S->>L: N3 — une seule passe, sortie structurée imposée
    L-->>S: sql, ou clarification, ou refus

    alt le modèle refuse — la base ne porte pas cette donnée
        S->>J: decision=denied, code=hors_schema
        S-->>C: isError, code=hors_schema
    else le modèle demande à préciser
        S->>M: filtre les axes de clarification par le périmètre
        S->>J: decision=allowed, code=clarification
        S-->>C: code=clarification avec des choix fermés
    else le modèle rend une requête
        rect rgb(213, 232, 212)
        S->>G: N4 — cinq contrôles sur l'arbre, pas sur le texte
        G-->>S: verdict
        end
        alt contrôles 1 à 4 — écriture, instructions multiples, commande moteur
            S->>J: decision=denied, etage=3, code=ecriture_refusee
            S-->>C: isError, code=ecriture_refusee
        else contrôle 5 — une colonne hors matrice, alias résolus
            S->>J: decision=denied, etage=3, code=perimetre_interdit<br/>la colonne en cause est nommée
            S-->>C: isError, code=perimetre_interdit
        else les cinq contrôles passent
            S->>S: N5 — injecte un LIMIT si la requête n'en porte pas
            rect rgb(213, 232, 212)
            S->>D: N6 — connexion neuve, mode=ro et query_only=ON, timeout
            end
            alt la base répond
                D-->>S: lignes
                S->>S: N7 — trois contrôles de code, aucune passe LLM
                alt aucune ligne
                    S->>J: decision=allowed, code=aucune_ligne
                    S-->>C: code=aucune_ligne avec la requête
                else des lignes homonymes
                    S->>J: decision=allowed, code=ambiguite_donnees
                    S-->>C: code=ambiguite_donnees, chaque ligne avec sa référence
                else résultat exploitable
                    S->>J: decision=allowed, code=ok, sql, n_rows, latency_ms
                    S-->>C: code=ok — le résultat, LA REQUÊTE QUI L'A PRODUIT,<br/>et les conventions métier appliquées
                    C-->>U: le chiffre, et le SQL qui le justifie
                end
            else timeout, plafond, base indisponible
                S->>J: decision=error, code=erreur_execution
                S-->>C: isError, code=erreur_execution
            end
        end
    end

    Note over J: Tous les chemins y aboutissent — servis, refusés, échoués.<br/>Journal non écrit = appel non servi : E5 n'admet pas d'appel non tracé.
```

## 2. Ce que la séquence montre et que le flux ne montrait pas

| Fait rendu visible | Pourquoi il compte |
|---|---|
| **la matrice parle avant le LLM** — étage 2, puis N1, puis seulement N3 | le modèle ne voit jamais une colonne interdite : elle n'est pas dans le contrat qu'on lui donne. Le contrôle 5 de l'AST rattrape ce qu'il **invente** hors du contrat, pas ce qu'on lui a montré |
| **un seul aller-retour avec le LLM** | pas de boucle de correction, pas de second appel. La sortie est structurée à trois branches, et le code ajoute la quatrième décision *après* exécution |
| **`sqlglot` est consulté, il ne décide pas seul** | il rend un verdict sur l'arbre ; c'est le serveur qui traduit ce verdict en code, en journal et en réponse |
| **la connexion est ouverte tard, et pour une seule requête** | elle est neuve à chaque appel : aucun état de connexion ne survit d'un appel au suivant |
| **le journal est écrit avant la réponse**, sur les huit sorties | un refus non journalisé serait indétectable ; c'est l'ordre des flèches qui le garantit |

## 3. Les trois autres tools SQL, sur le même chemin

`ask_database` est **le seul** qui produise du SQL, donc le seul à traverser N3 et N4.

| Tool | Étapes traversées | Ce qu'il saute, et pourquoi |
|---|---|---|
| `ask_database` | étage 2 · N1 · N2 · N3 · N4 · N5 · N6 · N7 | — |
| `get_schema` | étage 2 · N1 · N2 → **s'arrête** | il rend le **contrat de lecture** lui-même. Aucun SQL n'est généré : un client peut vouloir composer sa question sans rien déclencher |
| `check_stock` | étage 2 · N1 · N6 · N7 | sa requête est **écrite d'avance** : ni schéma à fournir, ni modèle à appeler, ni arbre à valider |
| `order_status` | étage 2 · N1 · N6 · N7 | idem |

**Les quatre passent par l'étage 2 et par N1, et les quatre aboutissent au journal.** Ce qui
change d'un tool à l'autre, c'est **quand** leur périmètre est vérifié — pas **s'il** l'est.

## 4. Les quatre tests d'acceptance du volet, et l'étape qui les fait passer

| Test | Attendu | Étape |
|---|---|---|
| **T1** | le résultat est rendu avec la requête qui l'a produit | la réponse `ok` porte `sql` |
| **T2** | une demande d'écriture est refusée, et journalisée | N4 contrôles 1 à 4 → `ecriture_refusee` + journal |
| **T3** | les marges sont refusées au profil support | N4 contrôle 5 → `perimetre_interdit`, colonne nommée |
| **T4** | une question hors schéma est refusée | branche `refus` de N3 → `hors_schema`, aucune requête produite ni tentée |

## Renvois

- schéma de flux, V3 : [`04-chemin-text-to-sql.drawio`](04-chemin-text-to-sql.drawio)
- de la question à la requête : [`2-text-to-sql/Q1.md`](../2-text-to-sql/Q1.md)
- les quatre couches de la lecture seule : [`2-text-to-sql/Q2.md`](../2-text-to-sql/Q2.md)
- périmètre par profil, alias, `SELECT *` : [`2-text-to-sql/Q3.md`](../2-text-to-sql/Q3.md)
- les tools figés : [`2-text-to-sql/Q4.md`](../2-text-to-sql/Q4.md)
- question ambiguë ou hors schéma : [`2-text-to-sql/Q5.md`](../2-text-to-sql/Q5.md)
- les douze codes : [`03-catalogue-tools.md`](03-catalogue-tools.md) §codes
- pièce factuelle sur la base : [`2-text-to-sql/description-base.md`](../2-text-to-sql/description-base.md)
