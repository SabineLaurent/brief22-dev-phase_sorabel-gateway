# Flux Text-to-SQL

Ces diagrammes décrivent le code présent dans le dépôt. Le Text-to-SQL possède deux façades distinctes :

- le banc d'essai frontend Chainlit, qui passe par l'API FastAPI et un agent LangChain ;
- le serveur MCP stdio, appelé directement par un client MCP.

Les deux façades convergent vers `packages.text_to_sql_factory.handler`, mais le frontend n'appelle pas le serveur MCP.

## Schéma du flux

```mermaid
flowchart TD
    U[Utilisateur] --> F[Frontend Chainlit<br/>packages/web_client/app.py:on_message]
    F -->|POST /chat<br/>role + question| A[API FastAPI<br/>packages/agent/api.py:chat]
    A --> P[profile_for_role]
    P --> AG[_agent_for<br/>puis build_agent]
    AG --> L[Agent LangChain<br/>choisit un tool selon sa description]

    L --> FT{Tool SQL frontend}
    FT -->|ask_to_db| ASK[_serve ask_database, question]
    FT -->|check_stock_by_ref| STOCK[_serve check_stock, reference]
    FT -->|order_status_by_id| ORDER[_serve order_status, order_id]
    FT -->|get_db_schema| SCHEMA[_serve get_schema]

    M[Client MCP<br/>scripts/mcp_client.py ou client externe] -->|stdio<br/>list_tools / call_tool| S[Serveur MCP<br/>mcp_server/server.py]
    S --> MP{Tool MCP}
    MP -->|ask_database| M_ASK[_json_result]
    MP -->|check_stock| M_STOCK[_json_result]
    MP -->|order_status| M_ORDER[_json_result]
    MP -->|get_schema| M_SCHEMA[_json_result]

    ASK --> H
    STOCK --> H
    ORDER --> H
    SCHEMA --> H
    M_ASK --> RQ[SqlToolRequest<br/>outil + profil + arguments]
    M_STOCK --> RQ
    M_ORDER --> RQ
    M_SCHEMA --> RQ
    RQ --> H[handler.handle_request]

    H --> LAUNCH[SqlToolLauncher.launch / execute]
    LAUNCH --> AUTH{authorize<br/>profil + tool}
    AUTH -->|non autorisé| DENY2[DbStructuredAnswer<br/>tool_interdit, étage 2]
    AUTH -->|autorisé| ARGS{Arguments présents ?}
    ARGS -->|non| BAD[DbStructuredAnswer<br/>erreur_execution / argument_malforme]
    ARGS -->|oui| TOOL{Fonction métier dans tools.py}

    TOOL -->|ask_database| DBASK[ask_database]
    TOOL -->|check_stock| DBSTOCK[check_stock<br/>SQL figé paramétré]
    TOOL -->|order_status| DBORDER[order_status<br/>SQL figé paramétré]
    TOOL -->|get_schema| DBSCHEMA[get_schema<br/>contrat filtré]

    DBASK --> CONTRACT[build_read_contract<br/>colonnes accessibles au profil]
    CONTRACT --> GEN[SqlGenerator.generate<br/>LLM SQL structuré]
    GEN --> BRANCH{Branche de génération}
    BRANCH -->|clarification| CLAR[DbStructuredAnswer<br/>clarification + axes codés]
    BRANCH -->|refus| REF[DbStructuredAnswer<br/>ecriture_refusee ou hors_schema]
    BRANCH -->|panne| ERR[DbStructuredAnswer<br/>erreur_execution]
    BRANCH -->|sql| VALID[validate<br/>sqlglot + matrice + LIMIT]
    VALID -->|refus| VREF[DbStructuredAnswer<br/>perimetre_interdit ou ecriture_refusee]
    VALID -->|erreur moteur, repairable| REPAIR[Une seule nouvelle génération<br/>avec l'erreur EXPLAIN]
    REPAIR --> VALID
    VALID -->|ok| EXPLAIN[EXPLAIN SQLite<br/>préparation sans lecture]
    EXPLAIN -->|échec| REPAIR
    EXPLAIN -->|ok| EXEC[execute<br/>SQLite mode=ro + query_only]
    EXEC --> CHECK[Contrôles du résultat<br/>vide, ambiguïté, troncature]

    DBSTOCK --> RUN[execute_with_parameters]
    DBORDER --> RUN
    RUN --> CHECK
    DBSCHEMA --> ANSWER
    CHECK --> ANSWER
    CLAR --> ANSWER
    REF --> ANSWER
    ERR --> ANSWER
    VREF --> ANSWER
    DENY2 --> ANSWER
    BAD --> ANSWER
    ANSWER[DbStructuredAnswer complet] --> JOURNAL[journal.record<br/>entrée complète]
    JOURNAL --> VIEW[client_view<br/>status + payload + message]

    VIEW -->|retour JSON| MCPRET[Réponse du tool MCP<br/>json.dumps dans _json_result]
    MCPRET --> M
    VIEW -->|retour de _serve| TOOLTEXT[Texte rendu à l'agent]
    TOOLTEXT --> L
    L -->|réponse rédigée ou refus figé| APIRET[ChatResponse]
    APIRET --> F
    F --> U
```

### Points de lecture

- Les noms frontend sont des wrappers locaux : `ask_to_db` appelle le catalogue `ask_database`, `check_stock_by_ref` appelle `check_stock`, `order_status_by_id` appelle `order_status` et `get_db_schema` appelle `get_schema`.
- Le serveur MCP lit le profil dans `SORABEL_PROFILE`, tandis que l'API frontend convertit le rôle reçu avec `profile_for_role()`.
- `ask_database` donne au générateur uniquement le contrat de lecture du profil. La validation AST contrôle ensuite les tables, les colonnes, les écritures, la borne `LIMIT`, puis le moteur via `EXPLAIN`.
- Une erreur signalée par `EXPLAIN` peut provoquer une seule reprise du générateur. Un refus de matrice n'est pas renégocié.
- `journal.record()` reçoit la réponse interne complète avant `client_view()`. Les causes, traces et colonnes interdites restent donc hors de la vue client.

## Diagramme de séquence

```mermaid
sequenceDiagram
    autonumber
    actor User as Utilisateur
    participant Front as Frontend Chainlit
    participant API as API FastAPI
    participant Agent as Agent LangChain
    participant MCPClient as Client MCP
    participant MCP as Serveur MCP stdio
    participant Handler as handler.handle_request
    participant Launcher as SqlToolLauncher
    participant Tool as Fonction SQL
    participant LLM as Modèle de génération SQL
    participant Validator as validate / EXPLAIN
    participant DB as SQLite
    participant Journal as journal.record

    alt Voie frontend
        User->>Front: Saisit une question
        Front->>API: POST /chat {role, question}
        API->>API: profile_for_role(role)
        API->>Agent: _agent_for(strategy, profile)
        API->>Agent: invoke(messages=[question])
        Agent->>Agent: Choisit un tool SQL selon sa description
        Agent->>Tool: _serve(tool catalogue, arguments, profile)
        Tool->>Handler: handle(tool, arguments, profile)
        Handler->>Launcher: launch(SqlToolRequest)
    else Voie MCP
        MCPClient->>MCP: initialize puis list_tools()
        MCP->>MCP: Filtre les tools avec authorize(PROFILE, tool)
        MCP-->>MCPClient: Catalogue autorisé
        MCPClient->>MCP: call_tool(name, arguments)
        MCP->>MCP: _json_result(tool, arguments)
        MCP->>Handler: handle_request(SqlToolRequest)
        Handler->>Launcher: launch(SqlToolRequest)
    end

    Launcher->>Launcher: Vérifie le nom du tool
    alt Tool inconnu ou argument manquant
        Launcher-->>Handler: DbStructuredAnswer(erreur_execution)
    else Tool interdit
        Launcher->>Launcher: authorize(profile, tool) = false
        Launcher-->>Handler: DbStructuredAnswer(tool_interdit, étage 2)
    else Tool autorisé
        Launcher->>Tool: Appelle la fonction avec profile et settings
        alt get_schema
            Tool->>Tool: _denied_scope puis build_read_contract
            Tool-->>Handler: DbStructuredAnswer(ok, schema)
        else check_stock ou order_status
            Tool->>Tool: Valide l'identifiant
            Tool->>DB: Requête figée paramétrée
            DB-->>Tool: Lignes, colonnes et latence
            Tool->>Tool: Contrôles du résultat
            Tool-->>Handler: DbStructuredAnswer
        else ask_database
            Tool->>Tool: build_read_contract(profile)
            Tool->>LLM: generate(question, contrat, axes)
            LLM-->>Tool: sql, clarification ou refus
            alt Clarification
                Tool-->>Handler: DbStructuredAnswer(clarification, axes)
            else Refus du modèle
                Tool-->>Handler: DbStructuredAnswer(ecriture_refusee ou hors_schema)
            else SQL généré
                Tool->>Validator: validate(sql, profile)
                Validator->>Validator: sqlglot : instruction, racine,\nécriture, tables, colonnes, LIMIT
                Validator->>DB: EXPLAIN requête bornée
                DB-->>Validator: Succès ou erreur de préparation
                alt Erreur EXPLAIN réparable
                    Validator-->>Tool: Verdict(repairable = true)
                    Tool->>LLM: generate(question, contrat, axes, rejected)
                    LLM-->>Tool: SQL corrigé
                    Tool->>Validator: validate(SQL corrigé, profile)
                else Refus ou erreur de validation
                    Validator-->>Tool: Verdict non autorisé ou erreur
                end
                alt Requête validée
                    Validator-->>Tool: Verdict(ok, SQL borné)
                    Tool->>DB: execute(SQL borné)\nconnexion mode=ro + query_only
                    DB-->>Tool: Résultat borné
                    Tool->>Tool: Contrôles vide, ambiguïté, troncature
                    Tool-->>Handler: DbStructuredAnswer
                else Requête refusée ou invalide
                    Tool-->>Handler: DbStructuredAnswer
                end
            end
        end
    end

    Handler->>Journal: record(tool, profile, arguments, réponse complète)
    Handler->>Handler: client_view(réponse)

    alt Retour MCP
        Handler-->>MCP: Vue {status, payload, message}
        MCP-->>MCPClient: JSON sérialisé par _json_result
        MCPClient-->>User: Réponse du client MCP
    else Retour frontend
        Handler-->>Agent: Vue client rendue par _serve
        Agent-->>API: Réponse rédigée ou résultat du tool
        API->>API: frozen_text(book)
        alt Statut non-ok
            API-->>Front: ChatResponse avec message figé
        else Statut ok
            API-->>Front: ChatResponse avec réponse de l'agent
        end
        Front-->>User: Affiche la réponse
    end
```

Le code ne montre pas de frontend appelant `mcp_server.server` : les deux parcours sont donc représentés comme deux façades distinctes partageant le handler SQL.
