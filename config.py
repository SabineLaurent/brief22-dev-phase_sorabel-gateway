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
    #: **Non calibré** : à régler sur eval/questions_calibration.jsonl, jamais sur le
    #: jeu de mesure. `None` désactive la barrière.
    refusal_threshold: float | None = None

    @property
    def uses_azure_embeddings(self) -> bool:
        return bool(self.azure_embedding_deployment and self.azure_ai_endpoint)


settings = Settings()
