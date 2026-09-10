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
    #:
    #: **Cette valeur appartient à un modèle et à un index** : 0,8308 a été calibré
    #: pour ``intfloat/multilingual-e5-base`` sur la collection ``sorabel_corpus``.
    #: Un autre embedder produit une autre distribution de scores, et **rien dans le
    #: code ne relie ce seuil au modèle qui l'a produit** — le contrôle d'empreinte
    #: protège l'appariement index ↔ modèle, pas seuil ↔ modèle. Changer d'embedder
    #: sans `make calibrer` règle donc le refus sur une distribution étrangère, en
    #: silence. Garde-fou manquant, consigné.
    refusal_threshold: float | None = 0.8308

    # --- Recherche hybride (étape 3) ------------------------------------------
    #: Nombre de documents réellement notés par le reranker — le **budget**. C'est
    #: le seul étage coûteux de la chaîne, donc le seul nombre qu'on ne veut pas
    #: laisser grossir. Le dossier ne fixe pas cette valeur ; elle doit dépasser
    #: `search_top_k` pour laisser RRF un choix entre plusieurs candidats.
    rerank_candidates: int = 20
    #: Profondeur récupérée **par étage** avant fusion RRF — le **vivier**. `None`
    #: le fait valoir `rerank_candidates`, c'est-à-dire vivier == budget : la forme
    #: d'avant le correctif de `2bis.1`, où un seul nombre servait aux deux rôles.
    #:
    #: Les séparer est ce qui donne au plafond par titre de la matière à repêcher.
    #: Un vivier égal au budget n'en laisse aucune : pour le profil `support`, les
    #: 20 places étaient occupées par 20 documents mais **2 titres** — 80 notes
    #: internes pour 5 titres distincts, redondance 16× — et la procédure SAV
    #: n'entrait jamais dans la liste. Le reranker ne se trompait pas, on ne lui
    #: montrait pas le document.
    #:
    #: Ce qui grossit avec ce nombre est un `collection.query` et un
    #: `bm25.get_scores` — qui calcule déjà sur le corpus entier —, jamais le
    #: nombre d'appels au reranker.
    #:
    #: **60 est mesuré, pas choisi** : à 20 le vivier de `support` porte 2 titres
    #: distincts, à 60 il en porte 30 (`make check-perimetre`). Le vivier doit
    #: porter au moins `rerank_candidates // max_candidates_per_title` titres pour
    #: que le budget se remplisse de sujets et non de doublons.
    #:
    #: Un vivier plus profond ne fait pas *ajouter* des candidats — le budget est
    #: fixe — il change *lesquels* : les scores RRF se recomposent sur une union
    #: plus large, et un document présent dans les deux listes profondes peut
    #: évincer un document qui n'était que dans une liste courte. Un score de rang
    #: 1 peut donc baisser, et c'est pourquoi le seuil est recalibré avec.
    search_pool: int | None = 60
    #: Places maximales par **titre** dans le budget de rerank. `None` désactive le
    #: plafond, ce qui est la forme d'avant le correctif de `2bis.1`.
    #:
    #: La clé est `titre` et non `theme` (omis sur les 320 éditions qui ne sont pas
    #: des notes) ni `doc_key` (déjà unique par document) : c'est le seul des onze
    #: champs de métadonnées qui porte la redondance de série, et il vaut pour tout
    #: le corpus. Les candidats au-delà du plafond sont **différés, pas exclus** —
    #: ils repassent en fin de liste, si bien que le budget reste plein quand le
    #: vivier est pauvre en titres.
    #:
    #: À 3, les 20 places du budget portent ~7 sujets au lieu de 2. Un plafond
    #: supérieur à la taille du vivier équivaut à `None` : rien n'est différé.
    max_candidates_per_title: int | None = 3

    # --- Reranker --------------------------------------------------------------
    #: Cross-encoder local, utilisé quand aucun déploiement Azure n'est renseigné.
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    #: Déploiement de rerank sur Azure AI Foundry (Cohere). Les TROIS champs
    #: ``azure_rerank_*`` sont nécessaires ensemble : un reranker à moitié configuré
    #: retombe sur le cross-encoder local plutôt que d'échouer à la première question.
    azure_rerank_deployment: str = ""
    #: **URL complète** de l'appel de rerank, pas une base : Azure AI Foundry sert les
    #: modèles partenaires sous ``services.ai.azure.com/providers/<nom>/…``, et le chemin
    #: dépend du fournisseur. Elle se lit dans le *détail* du déploiement — le champ
    #: « point de terminaison » du panneau affiche l'endpoint générique de la ressource,
    #: qui rend 404 sur le rerank. Rien de commun avec ``azure_ai_endpoint``.
    azure_rerank_endpoint: str = ""
    #: Clé propre au déploiement de rerank, pour la même raison.
    azure_rerank_api_key: str = ""
    #: Modèle de chat (API v1), utilisé par l'agent conversationnel de
    #: packages/agent/cli.py — aucune fonction du RAG lui-même n'en dépend.
    llm_chat_model: str = ""
    #: Score minimal du premier résultat, sur l'échelle du reranker — critère de
    #: refus de la configuration hybride (Q4 §3, Q5 §4). Calibré par
    #: `make calibrer-hybride`, jamais sur le jeu de mesure.
    #:
    #: **Même réserve que ``refusal_threshold``, sur l'autre échelle** : 0,0530 a été
    #: calibré pour le cross-encoder ``mmarco-mMiniLMv2-L12-H384-v1``. Un reranker
    #: Cohere rend un ``relevance_score`` d'une autre distribution ; brancher les
    #: trois ``azure_rerank_*`` sans `make calibrer-hybride` déplace le refus sans
    #: rien signaler.
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
        """Tout ou rien : les **trois**, ou le modèle local — comme pour le rerank.

        La clé entrait dans l'appel sans entrer dans la condition : deux variables sur trois
        faisaient donc basculer en distant, et l'absence de la troisième n'échouait qu'au
        premier appel HTTP, en `401`. Une panne de configuration se présentait en panne de
        réseau. Symétrique de :attr:`uses_azure_rerank`, qui exigeait déjà les trois.
        """
        return bool(
            self.azure_embedding_deployment
            and self.azure_ai_endpoint
            and self.azure_ai_api_key
        )

    @property
    def uses_azure_rerank(self) -> bool:
        """Tout ou rien : les trois, ou le cross-encoder local."""
        return bool(
            self.azure_rerank_deployment
            and self.azure_rerank_endpoint
            and self.azure_rerank_api_key
        )


#: Les seuils de refus **calibrés**, par couple (embedder, reranker) — sur l'échelle du
#: reranker, donc pour la configuration hybride, la seule servie.
#:
#: **Ce que cette table ferme.** Les docstrings de ``refusal_threshold`` et de
#: ``rerank_threshold`` disaient depuis le début que « rien dans le code ne relie ce seuil au
#: modèle qui l'a produit », et le nommaient « garde-fou manquant, consigné ». Le voici : le
#: nom du couple servi est lisible sans réseau et sans charger un modèle — ``build_embedder``
#: et ``build_reranker`` exposent tous deux un ``.name`` —, donc l'appariement est
#: vérifiable. ``check-rag-tools`` le vérifie ; **un couple absent de cette table est un
#: échec**, pas un défaut silencieux.
#:
#: **Ce que le défaut coûterait.** 0,0530 (mmarco) contre 0,6203 (Cohere) : plus d'un ordre
#: de grandeur. Servir le premier avec le second ne refuserait **jamais rien** — le score
#: Cohere du premier résultat est presque toujours très supérieur à 0,053 — et l'inverse
#: refuserait presque tout. Aucune trace, aucune exception : seulement une barrière 1 muette.
#:
#: **Les quatre valeurs sont celles des axes 6 et 7**, publiées dans
#: ``eval/rapport_local_vs_distant.md`` et reprises en défauts du Makefile
#: (``SEUIL_LOCAL_C``, ``SEUIL_DISTANT``, ``SEUIL_COHERE``, ``SEUIL_AZURE_C``). Chaque cellule
#: a été calibrée pour elle-même : comparer à seuil constant mesurerait le seuil.
#:
#: **Ce n'est pas une garde à l'exécution, et c'est voulu** : ``make mesure-rerank``,
#: ``mesure-embeddings`` et ``mesure-candidats`` posent délibérément des seuils par variable
#: d'environnement sur des couples arbitraires. Une garde dans ``threshold_for()`` les
#: casserait ; un contrôle sur la configuration servie ne gêne aucune mesure.
CALIBRATED_THRESHOLDS: dict[tuple[str, str], float] = {
    # ① servie en local — la cellule décrite par les cinq rapports publiés
    ("intfloat/multilingual-e5-base", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"): 0.0530,
    # ② embedder distant, reranker local
    ("text-embedding-3-small", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"): 0.0153,
    # ③ embedder local, reranker distant
    ("intfloat/multilingual-e5-base", "Cohere-rerank-v4.0-pro"): 0.5923,
    # ④ les deux en distant — la cellule déployée, sans PyTorch dans l'image
    ("text-embedding-3-small", "Cohere-rerank-v4.0-pro"): 0.6203,
}


settings = Settings()
