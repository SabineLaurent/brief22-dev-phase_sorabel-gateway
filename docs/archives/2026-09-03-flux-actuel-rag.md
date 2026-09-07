# Flux actuel — de la question Chainlit à la réponse restituée (2026-09-03)

Ce document décrit le chemin **tel qu'il est aujourd'hui**, à la clôture du chantier RAG :
interface Chainlit → API FastAPI → agent LangChain → couche de recherche. Ce n'est pas le
flux cible du dossier de conception (`01-flux-complet.md`), qui passe par le serveur MCP —
celui-ci n'existe pas encore, et la matrice d'accès n'est donc appliquée nulle part.

Deux écarts sont représentés explicitement, parce qu'ils comptent pour la démo :

- **le rôle n'est qu'une étiquette** transmise à l'API, aucun filtrage ne s'appuie dessus ;
- **la barrière de refus `hors_corpus` n'est pas empruntée** : le tool `search_docs` appelle
  `search()` sans `threshold`, dont la valeur par défaut est `None`. E1 ne tient ici que par
  le prompt système. Voir `docs/2026-09-03-points-ouverts-fin-chantier-rag.md` §2.

## 1. Schéma de flux

```mermaid
flowchart TD
    subgraph NAV["Navigateur"]
        U["Utilisateur — choisit un profil de rôle,<br/>pose une question ou tape un identifiant d'eval"]
    end

    subgraph WEB["Chainlit — port 8100 · packages/web_client/app.py"]
        RESOLVE["on_message : résout RAG-03 / SQL-01 / CAL-02<br/>via eval/questions_*.jsonl, sinon garde le texte"]
        POST["httpx : POST 127.0.0.1:8000/chat<br/>{role, question}"]
        RENDER["cl.Message : affiche answer, ou « Erreur : … »"]
    end

    subgraph API["FastAPI — port 8000 · packages/agent/api.py"]
        CHECK{"role dans ROLES ?"}
        REJECT["ChatResponse{error: rôle inconnu}"]
        CACHE["_agent_for(strategy) — lru_cache par stratégie"]
        WRAP["ChatResponse{answer} · exception remontée en error"]
    end

    subgraph AGENT["Agent LangChain — packages/agent/cli.py"]
        INVOKE["create_agent : prompt système + tool search_docs"]
        FORMAT["Formate les extraits :<br/>[reference] titre (score) + texte"]
    end

    LLM["LLM Azure AI Foundry — API v1<br/>init_chat_model(LLM_CHAT_MODEL)"]

    subgraph SEARCH["Recherche — packages/rag_machines/retrieval/search.py"]
        ENTRY["search(query, strategy='hybrid')"]
        DENSE["_dense_query — where is_current=True<br/>profondeur rerank_candidates = 20"]
        LEX["lexical.py — BM25 dépicklé, même profondeur"]
        RRF["_reciprocal_rank_fusion — k = 60"]
        RERANK["reranker.py — cross-encoder local ou LLM Azure<br/>son score devient le score final"]
        TIE["apply_tiebreak — fenêtre 3, fiche avant notice"]
        THRESH{"threshold ?"}
        REFUSE["SearchResult{status: hors_corpus}"]
        CITE["citation() — titre, reference (repli doc_key),<br/>version, date · construite en Python"]
    end

    CHROMA[("Chroma — port 8002<br/>collection d'éditions + embedder")]
    BM25[("Index BM25 — pickle par collection")]

    U --> RESOLVE --> POST --> CHECK
    CHECK -- non --> REJECT --> RENDER
    CHECK -- oui --> CACHE --> INVOKE
    INVOKE -->|"question + schéma du tool"| LLM
    LLM -->|"demande l'appel de search_docs"| INVOKE
    INVOKE -->|"appel du tool search_docs"| ENTRY
    ENTRY --> DENSE --> CHROMA
    ENTRY --> LEX --> BM25
    DENSE --> RRF
    LEX --> RRF
    RRF --> RERANK --> TIE --> THRESH
    THRESH -- "ok" --> CITE
    THRESH -. "inactif ici : threshold=None,<br/>jamais passé par search_docs" .-> REFUSE
    REFUSE -. "message de refus" .-> FORMAT
    CITE --> FORMAT
    FORMAT -->|"extraits rendus au modèle"| LLM
    LLM -->|"réponse rédigée"| WRAP --> RENDER --> U

    classDef inactif stroke-dasharray:5 5,color:#888;
    class REFUSE inactif;
```

## 2. Diagramme de séquence

```mermaid
sequenceDiagram
    autonumber
    actor U as Utilisateur
    participant W as Chainlit<br/>app.py
    participant A as FastAPI<br/>api.py
    participant G as Agent LangChain<br/>cli.py
    participant M as LLM Azure
    participant S as "search()"
    participant C as Chroma
    participant B as BM25
    participant R as Reranker

    U->>W: choisit un profil de rôle, puis pose sa question
    W->>W: résout l'identifiant d'eval s'il y en a un
    W->>A: POST /chat {role, question}
    A->>A: role dans ROLES ?
    A->>G: _agent_for(strategy).invoke(messages)
    G->>M: question + prompt système + schéma du tool
    M-->>G: demande l'appel de search_docs(query)
    G->>S: search(query, strategy="hybrid")

    par étage dense
        S->>C: query embeddings, where is_current=True, n=20
        C-->>S: 20 éditions candidates
    and étage lexical
        S->>B: BM25, top 20, filtre de version
        B-->>S: 20 éditions candidates
    end

    S->>S: RRF (k=60) sur les deux listes
    S->>R: score(query, documents fusionnés)
    R-->>S: scores bornés — score final
    S->>S: apply_tiebreak (fenêtre 3, fiche avant notice)

    opt refus hors_corpus — non emprunté dans ce flux
        Note over S: threshold=None : search_docs ne le passe pas.<br/>Sinon : hits[0].score < seuil → SearchResult(hors_corpus)
        S-->>G: message de refus, sans aucun extrait
    end

    S-->>G: SearchResult{status: ok, hits} + citation() par hit
    G->>M: extraits « [reference] titre (score) + texte »
    M-->>G: réponse rédigée, sources citées
    G-->>A: messages[-1].content
    A-->>W: ChatResponse{answer, error}

    alt réponse
        W-->>U: cl.Message(answer)
    else exception côté API
        W-->>U: cl.Message("Erreur : …")
    end
```

## 3. Écarts avec le flux cible

| point | flux actuel | flux cible (dossier de conception) |
|---|---|---|
| point d'entrée | API FastAPI privée, un seul tool | serveur MCP, catalogue complet de huit tools |
| tools RAG | `search_docs` uniquement, interne à l'agent | `answer_question`, `search_docs`, `get_document`, `list_sources` |
| rôle | étiquette transmise, sans effet | matrice d'accès appliquée à l'entrée et dans chaque tool (E4) |
| refus | seuil non branché ; une seule barrière existe dans le code | `hors_corpus` **et** `contexte_insuffisant`, tous deux actifs (E1) |
| citation | construite par `citation()`, restituée par le modèle dans sa prose | champ `sources` structuré de l'enveloppe de réponse |
| journalisation | aucune | tout appel journalisé, autorisé comme refusé (E5) |
