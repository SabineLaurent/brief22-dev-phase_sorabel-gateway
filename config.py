"""Configuration unique de la Sorabel Data Gateway.

Source de vérité unique : tous les modules lisent leurs réglages ici, jamais
directement dans ``os.environ``. Les variables déjà posées dans l'environnement
priment sur le fichier ``.env`` (comportement par défaut de pydantic-settings) —
c'est ce qui permet à un client de fixer son profil au lancement du serveur.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent


def llm_base_url(endpoint: str) -> str:
    """Rend la ``base_url`` de l'API v1 pour un endpoint donné.

    Le suffixe ``/openai/v1`` est ajouté s'il manque, et jamais dupliqué : le portail
    Azure affiche l'endpoint tantôt nu, tantôt déjà suffixé, et la duplication rend un
    404 « Resource not found » indiscernable d'un déploiement inexistant.
    """
    return endpoint.rstrip("/").removesuffix("/openai/v1").rstrip("/") + "/openai/v1"


class Settings(BaseSettings):
    """Réglages de la gateway, lus dans l'environnement puis dans ``.env``."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Corpus documentaire -------------------------------------------------
    corpus_dir: Path = REPO_ROOT / "data" / "corpus"

    # --- Index vectoriel -----------------------------------------------------
    chroma_url: str = "http://localhost:8002"
    chroma_collection: str = "sorabel_corpus"

    # --- Embeddings ----------------------------------------------------------
    #: Modèle local, utilisé quand aucun déploiement Azure n'est configuré.
    embedding_model: str = "intfloat/multilingual-e5-base"
    #: Renseigné ⇒ les embeddings partent sur Azure AI Foundry (API v1).
    azure_embedding_deployment: str = ""
    azure_ai_endpoint: str = ""
    azure_ai_api_key: str = ""

    # --- Recherche --------------------------------------------------------------
    #: Nombre de résultats rendus. Le dossier laisse `top_k` explicitement ouvert,
    #: à arrêter sur les mesures ; 5 est la valeur qu'impose la métrique Recall@5.
    search_top_k: int = 5
    #: Score minimal du premier résultat sous lequel la recherche refuse (Q4 §3).
    #: Calibré sur eval/questions_calibration.jsonl — jamais sur le jeu de mesure —
    #: par `make calibrer`. `None` désactive la barrière, ce que fait la mesure de
    #: rappel pour ne pas se masquer un résultat.
    refusal_threshold: float | None = 0.8308

    # --- Recherche hybride (étape 3) ------------------------------------------
    #: Profondeur des listes avant fusion RRF et avant rerank. Le dossier ne fixe
    #: pas cette valeur ; elle doit dépasser `search_top_k` pour laisser RRF un
    #: choix entre plusieurs candidats.
    rerank_candidates: int = 20

    # --- Reranker --------------------------------------------------------------
    #: Cross-encoder local, utilisé quand aucun déploiement Azure n'est renseigné.
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    #: Déploiement de rerank sur Azure AI Foundry (Cohere). Les TROIS champs
    #: ``azure_rerank_*`` sont nécessaires ensemble : un reranker à moitié configuré
    #: retombe sur le cross-encoder local plutôt que d'échouer à la première question.
    azure_rerank_deployment: str = ""
    #: Endpoint propre au déploiement de rerank — il n'est PAS OpenAI-compatible
    #: (``POST {endpoint}/v2/rerank``), donc il ne réutilise rien d'``azure_ai_endpoint``.
    azure_rerank_endpoint: str = ""
    #: Clé propre au déploiement de rerank, pour la même raison.
    azure_rerank_api_key: str = ""
    #: Modèle de chat (API v1), utilisé par l'agent conversationnel de
    #: packages/agent/cli.py — aucune fonction du RAG lui-même n'en dépend.
    llm_chat_model: str = ""
    #: Score minimal du premier résultat, sur l'échelle du reranker — critère de
    #: refus de la configuration hybride (Q4 §3, Q5 §4). Calibré par
    #: `make calibrer-hybride`, jamais sur le jeu de mesure.
    rerank_threshold: float | None = 0.0530

    # --- Base métier (chantier Text-to-SQL) ----------------------------------
    sorabel_db: Path = REPO_ROOT / "data" / "sorabel.db"
    #: Schéma commenté de référence : la matière première du contrat de lecture.
    schema_doc: Path = REPO_ROOT / "docs" / "schema.sql"
    #: Matrice d'accès, donnée de configuration versionnée — jamais du code.
    matrix_path: Path = REPO_ROOT / "mcp_server" / "matrice.yaml"
    #: `LIMIT` injecté quand la requête générée n'en porte pas (Q2 §3 C4). Jamais en
    #: remplacement d'un `LIMIT` plus petit déjà présent.
    sql_default_limit: int = 200
    #: Plafond de lignes ramenées, indépendant du `LIMIT` : sur cette base, un produit
    #: cartésien rend 337 620 lignes en 0,4 s — le volume compte plus que le temps.
    sql_max_rows: int = 1000
    #: Délai au-delà duquel l'exécution est interrompue. SQLite n'a pas de
    #: `statement_timeout` : la garde passe par `set_progress_handler`.
    sql_timeout_s: float = 5.0

    # --- Journalisation (chantier 3) -----------------------------------------
    #: Fichier JSONL du journal, une entrée par appel — servi comme refusé. Le nom de la
    #: variable d'environnement (`GATEWAY_JOURNAL`) et le défaut sont ceux du contrat
    #: d'intégration de docs/cadrage_dsi.md : la suite d'acceptance le fixe par
    #: l'environnement au lancement du serveur, pour lire le journal d'un test dans son
    #: propre répertoire temporaire.
    gateway_journal: Path = REPO_ROOT / "logs" / "journal.jsonl"
    #: Le tool qui donne droit de lire le journal. Nommé ici plutôt qu'en dur dans le code
    #: qui refuse : le garde-fou se lit alors dans la matrice, en face du profil qui le
    #: porte, et non dans une condition enfouie.
    journal_reader_tool: str = "read_journal"

    @property
    def uses_azure_embeddings(self) -> bool:
        return bool(self.azure_embedding_deployment and self.azure_ai_endpoint)

    @property
    def uses_azure_rerank(self) -> bool:
        """Tout ou rien : les trois, ou le cross-encoder local."""
        return bool(
            self.azure_rerank_deployment
            and self.azure_rerank_endpoint
            and self.azure_rerank_api_key
        )


settings = Settings()
