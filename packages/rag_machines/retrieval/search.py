"""Recherche documentaire — la couche que les tools MCP consommeront.

Tout y est **paramétré, jamais câblé** : la collection, l'étage de recherche, le filtre de
version, la règle de départage, le seuil de refus. C'est la contrainte que pose
``eval/protocole-mesure.md`` : chaque axe de mesure doit coûter un argument, et la
configuration A devra être rejouée à l'identique après la C.

Trois décisions du dossier sont matérialisées ici :

* **le filtre de version s'applique dans la requête**, donc avant toute troncature — jamais
  après une fusion (``Q1`` §5). Chroma le fait nativement par ``where`` ;
* **la citation est construite ici, jamais rédigée par un modèle** (``Q4`` §1) : elle est
  exacte par construction, il n'y a rien à valider après coup ;
* **le refus tombe avant tout appel au LLM** (``Q4`` §3) : aucun token dépensé, et surtout
  aucune occasion d'inventer.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Literal, cast

from chromadb.api.models.Collection import Collection

from config import Settings
from config import settings as default_settings
from packages.rag_machines.ingest.index import collection_name, connect, get_collection
from packages.rag_machines.retrieval.perimeter import Perimeter
from packages.rag_machines.ingest.normalize import TextProfile
from packages.rag_machines.retrieval.embedder import Embedder, build_embedder
from packages.rag_machines.retrieval.lexical import bm25_path, load_lexical_index
from packages.rag_machines.retrieval.reranker import Reranker, build_reranker

#: Les trois étages de recherche comparés par le protocole (``Q5`` §2) : A — dense seul,
#: B — lexical seul (le témoin), C — hybride BM25 + dense + RRF + rerank.
Strategy = Literal["dense", "lexical", "hybrid"]

#: Constante de la fusion RRF (``Q3`` §4) : pas de calibration, la décroissance en
#: ``1 / (k + rang)`` est volontairement douce.
_RRF_K = 60

#: Statuts du contrat DSI. `contexte_insuffisant` est la seconde barrière (Q4 §5), qui
#: vit au niveau de `answer_question` — elle suppose un appel au modèle.
STATUS_OK = "ok"
STATUS_OUT_OF_CORPUS = "hors_corpus"

#: Fenêtre de la règle de départage (Q3 §5) : la fiche de REF-8842 est au rang 3 en
#: lexical seul, une fenêtre plus large exposerait des questions en langage naturel à un
#: réordonnancement non désiré.
TIEBREAK_WINDOW = 3

_OUT_OF_CORPUS_MESSAGE = "Le corpus documentaire ne couvre pas cette question."


@dataclass(frozen=True)
class Hit:
    """Un résultat de recherche, dans la forme qu'attend le contrat d'intégration.

    ``doc_id`` est l'``edition_id`` : c'est lui qui désigne une édition précise, et c'est
    la clé que la suite d'acceptance lit.
    """

    doc_id: str
    score: float
    text: str
    metadata: dict[str, str | int | bool] = field(default_factory=dict)

    @property
    def reference(self) -> str | None:
        value = self.metadata.get("reference")
        return str(value) if value else None

    @property
    def doc_type(self) -> str:
        return str(self.metadata.get("doc_type", ""))


@dataclass(frozen=True)
class SearchResult:
    """Ce que rend une recherche : des résultats, ou un refus motivé."""

    status: str
    hits: list[Hit]
    message: str = ""

    @property
    def is_out_of_corpus(self) -> bool:
        return self.status == STATUS_OUT_OF_CORPUS


def citation(hit: Hit) -> dict[str, str]:
    """La citation E1, construite depuis les métadonnées — jamais rédigée par le modèle.

    Le contrat DSI demande « titre + référence + date ». ``Q4`` §2 objecte, mesures à
    l'appui, que cette forme n'identifie rien sur la moitié du corpus : 52 titres pour
    150 fiches, et **210 éditions sans référence produit**, dont les 90 procédures SAV.
    Il en conclut que la citation porte « ``reference`` quand elle existe ».

    **Le test d'acceptance tranche autrement, et il fait foi** : il interroge sur une
    procédure de retour sous garantie — donc une procédure SAV — puis exige
    ``src["reference"].strip()`` non vide sur *chaque* source. Une clé absente ou vide
    échoue.

    D'où la conduite retenue : **la métadonnée reste fidèle au contrat de données** — la
    clé ``reference`` est omise quand l'édition n'en porte pas, parce que le JSON Schema,
    les contrôles d'index et le filtrage de la matrice en dépendent — et **c'est la
    citation qui garantit une chaîne non vide**, en retombant sur ``doc_key``, qui
    identifie le document exactement. La version et la date restent là où ``Q4`` §2 les
    met : ce sont elles qui rendent une procédure SAV citable sans ambiguïté.
    """
    metadata = hit.metadata
    return {
        "titre": str(metadata.get("titre", "")),
        "reference": str(metadata.get("reference") or metadata.get("doc_key", hit.doc_id)),
        "version": str(metadata.get("version", "")),
        "date": str(metadata.get("date", "")),
        "doc_key": str(metadata.get("doc_key", "")),
    }


def apply_tiebreak(hits: list[Hit], window: int = TIEBREAK_WINDOW) -> list[Hit]:
    """À référence égale, la fiche technique passe devant la notice (``Q3`` §5).

    Sur une requête réduite à une référence nue, rien ne demande une fiche plutôt qu'une
    notice : les deux portent cette référence et lui sont également pertinentes. Aucun
    étage de recherche ne peut deviner l'intention — d'où cette règle, explicite et
    publiée, plutôt qu'un score qu'on aurait bricolé.

    Trois propriétés la rendent défendable :

    * **elle s'exprime en rangs**, jamais en scores : c'est la seule grandeur commune aux
      trois configurations, et la configuration lexicale n'a pas d'échelle de score ;
    * **elle ne lit jamais la question**, seulement les métadonnées des résultats. Un
      aiguillage par expression régulière sur la requête ferait venir le résultat de la
      règle, et la mesure E6 ne démontrerait plus rien ;
    * **elle départage, elle ne classe pas** : un seul échange, borné à la fenêtre, entre
      deux documents portant la *même* référence.
    """
    if not hits:
        return hits
    top = hits[0]
    if not top.reference or top.doc_type == "fiche_technique":
        return hits
    for rank, hit in enumerate(hits[1:window], start=1):
        if hit.reference == top.reference and hit.doc_type == "fiche_technique":
            return [hit] + hits[:rank] + hits[rank + 1 :]
    return hits


def _fetch(collection: Collection, ids: list[str]) -> dict[str, tuple[str, dict]]:
    """Récupère textes et métadonnées de plusieurs éditions en un seul aller-retour
    Chroma. ``collection.get()`` ne garantit pas de rendre les identifiants dans l'ordre
    demandé — c'est à l'appelant de reclasser depuis ce dictionnaire."""
    if not ids:
        return {}
    fetched = collection.get(ids=ids, include=["metadatas", "documents"])  # type: ignore[list-item]
    return {
        edition_id: (str(document or ""), dict(metadata or {}))
        for edition_id, document, metadata in zip(
            fetched["ids"],
            cast(list, fetched["documents"] or []),
            cast(list, fetched["metadatas"] or []),
        )
    }


def _reciprocal_rank_fusion(id_lists: list[list[str]], k: int = _RRF_K) -> list[str]:
    """Fusionne des classements sans mélanger leurs scores (``Q3`` §4) : chaque
    identifiant reçoit ``1 / (k + rang)`` par liste où il apparaît, puis le tri se fait
    sur la somme. Un document excellent dans une seule liste survit ; un document moyen
    dans les deux remonte — le comportement voulu entre deux étages aux angles morts
    complémentaires (dense : synonymie et flexion ; lexical : références et sigles)."""
    scores: dict[str, float] = collections.defaultdict(float)
    for ids in id_lists:
        for rank, edition_id in enumerate(ids, start=1):
            scores[edition_id] += 1 / (k + rank)
    return sorted(scores, key=lambda edition_id: scores[edition_id], reverse=True)


def _dense_query(
    collection: Collection, embedder: Embedder, query: str, top_k: int, version_filter: bool,
    perimeter: Perimeter | None = None,
) -> list[Hit]:
    """Le corps de la recherche dense, sur une collection déjà résolue.

    Séparée de ``_dense_search`` pour que ``_hybrid_search`` puisse réutiliser la même
    collection pour son étage dense et pour son ``_fetch`` final, au lieu d'ouvrir une
    deuxième connexion Chroma pour la même collection dans le même appel.

    Le filtre de version part **dans la requête** : Chroma l'applique avant de tronquer à
    ``top_k``, ce qui est exactement ce que demande ``Q1`` §5. Filtrer après coup rendrait
    le rang ininterprétable, et c'est le rang que consomme la fusion RRF de la
    configuration hybride. Le filtre de périmètre part au même endroit, pour la même raison.

    Sans périmètre, la clause reste **littéralement** celle d'avant : c'est ce qui rend les
    mesures publiées rejouables à l'identique sans avoir à en discuter.
    """
    where = (perimeter.where(version_filter) if perimeter is not None
             else ({"is_current": True} if version_filter else None))
    response = collection.query(
        query_embeddings=[embedder.embed_query(query)],  # type: ignore[arg-type]
        n_results=top_k,
        where=where,  # type: ignore[arg-type]
        include=["metadatas", "documents", "distances"],  # type: ignore[list-item]
    )

    def column(name: str) -> list:
        """Chroma rend une liste par requête ; on n'en pose qu'une."""
        values = cast(list, response.get(name) or [[]])
        return values[0] or []

    hits = []
    for doc_id, document, metadata, distance in zip(
        column("ids"), column("documents"), column("metadatas"), column("distances")
    ):
        # Chroma rend une distance cosinus (0 = identique) ; le contrat attend un score,
        # et un score qui monte avec la pertinence se lit mieux dans un rapport.
        hits.append(
            Hit(
                doc_id=str(doc_id),
                score=1.0 - float(distance),
                text=str(document or ""),
                metadata=dict(metadata or {}),
            )
        )
    return hits


def _dense_search(
    query: str,
    top_k: int,
    version_filter: bool,
    settings: Settings,
    embedder: Embedder,
    reranker: Reranker | None,
    text: TextProfile,
    perimeter: Perimeter | None,
) -> list[Hit]:
    """Recherche dense seule — la configuration A, l'« avant » que nomme le brief.

    ``reranker`` n'est pas utilisé : cette configuration n'en a pas. Il reste dans la
    signature pour que les trois étages partagent le même point d'appel dans
    ``_STRATEGIES``.
    """
    collection = get_collection(connect(settings), embedder, settings, text)
    return _dense_query(collection, embedder, query, top_k, version_filter, perimeter)


def _lexical_search(
    query: str,
    top_k: int,
    version_filter: bool,
    settings: Settings,
    embedder: Embedder,
    reranker: Reranker | None,
    text: TextProfile,
    perimeter: Perimeter | None,
) -> list[Hit]:
    """Recherche lexicale seule — la configuration B, le témoin (``Q3`` §2, ``Q5`` §2).

    ``embedder`` et ``reranker`` ne sont pas utilisés : BM25 ne vectorise rien et ne se
    reclasse pas. Ils restent dans la signature pour le même point d'appel commun.

    Le score rendu est le score BM25 brut, non borné : c'est la case B de ``Q5`` §4,
    « aucun seuil de refus possible » — un résultat, pas un trou.
    """
    index = load_lexical_index(bm25_path(collection_name(settings, text)))
    ranked = index.search(query, top_k, version_filter, perimeter)
    if not ranked:
        return []
    found = _fetch(get_collection(connect(settings), embedder, settings, text), [i for i, _ in ranked])
    return [
        Hit(doc_id=edition_id, score=score, text=found[edition_id][0], metadata=found[edition_id][1])
        for edition_id, score in ranked
        if edition_id in found
    ]


def _hybrid_search(
    query: str,
    top_k: int,
    version_filter: bool,
    settings: Settings,
    embedder: Embedder,
    reranker: Reranker | None,
    text: TextProfile,
    perimeter: Perimeter | None,
) -> list[Hit]:
    """BM25 + dense + RRF + rerank — la configuration C, l'« après » (``Q3`` §4-5).

    Les deux listes qui entrent dans la fusion sont chacune filtrées par version à leur
    propre profondeur ``rerank_candidates`` — plus large que ``top_k`` pour laisser RRF un
    choix entre plusieurs candidats. Le reranker ne note que les candidats fusionnés,
    jamais tout le corpus, et c'est son score qui devient le score final : c'est la seule
    échelle bornée du pipeline (``Q4`` §3), et ``search()`` a déjà résolu ``reranker``
    avant d'appeler cette fonction.
    """
    if reranker is None:
        # search() construit toujours reranker avant d'appeler cette fonction pour la
        # stratégie « hybrid » — un appel direct qui ne le ferait pas est un bug appelant,
        # pas un cas à absorber silencieusement (Python retire les `assert` sous `-O`,
        # ce message resterait, lui, une erreur explicite dans tous les cas).
        raise RuntimeError("_hybrid_search : reranker manquant — passer par search(), pas cette fonction.")
    depth = settings.rerank_candidates

    # Une seule collection, réutilisée pour l'étage dense et le _fetch final : deux
    # allers-retours Chroma évitables pour la même collection dans le même appel.
    collection = get_collection(connect(settings), embedder, settings, text)
    dense_ids = [hit.doc_id
                 for hit in _dense_query(collection, embedder, query, depth, version_filter, perimeter)]
    lexical_index = load_lexical_index(bm25_path(collection_name(settings, text)))
    lexical_ids = [i for i, _ in lexical_index.search(query, depth, version_filter, perimeter)]

    fused_ids = _reciprocal_rank_fusion([dense_ids, lexical_ids])[:depth]
    if not fused_ids:
        return []

    found = _fetch(collection, fused_ids)
    ordered = [(edition_id, *found[edition_id]) for edition_id in fused_ids if edition_id in found]
    if not ordered:
        return []

    scores = reranker.score(query, [document for _, document, _ in ordered])
    hits = [
        Hit(doc_id=edition_id, score=score, text=document, metadata=metadata)
        for (edition_id, document, metadata), score in zip(ordered, scores)
    ]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


_STRATEGIES = {"dense": _dense_search, "lexical": _lexical_search, "hybrid": _hybrid_search}


def search(
    query: str,
    *,
    strategy: Strategy = "dense",
    text: TextProfile = "clean",
    top_k: int | None = None,
    version_filter: bool = True,
    tiebreak: bool = True,
    threshold: float | None = None,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    perimeter: Perimeter | None = None,
) -> SearchResult:
    """Cherche dans le corpus. Rend des résultats, ou un refus ``hors_corpus``.

    Chaque paramètre est un axe du protocole de mesure, et aucun n'a de valeur en dur
    ailleurs que dans la configuration.

    ``threshold`` est un **score minimal**, sur l'échelle propre à ``strategy`` — jamais la
    même grandeur d'une configuration à l'autre (``Q5`` §4) : la similarité cosinus du
    premier résultat pour ``dense`` (``1 - distance``, bornée), le score du reranker pour
    ``hybrid`` (bornée, apprise). ``lexical`` n'a pas d'échelle sur laquelle un seuil soit
    une opération sensée (``Q4`` §3) — passer un ``threshold`` avec ``strategy="lexical"``
    lève ``ValueError`` plutôt que de comparer silencieusement un score BM25 non borné à
    une valeur qui n'aurait aucun sens sur cette échelle. Passer ``None`` désactive le refus
    — utile pour mesurer le rappel sans que la barrière ne masque un résultat.

    ``reranker`` n'est construit — via ``build_reranker`` — que si ``strategy="hybrid"`` :
    inutile de charger le cross-encoder, ou d'appeler Azure, pour une mesure dense ou
    lexicale seule.

    ``perimeter`` est un périmètre **déjà résolu**, jamais un profil : cette fonction ne lit
    pas la matrice d'accès et ne sait pas ce qu'est un profil. La conversion vit dans
    ``packages/rag_machines/access_rag.py``, qui est aussi le seul endroit où un périmètre
    vide se change en refus. ``None`` — la valeur par défaut — ne filtre rien : c'est ce qui
    laisse les mesures publiées rejouables sans drapeau supplémentaire.
    """
    settings = settings or default_settings
    embedder = embedder or build_embedder(settings)
    top_k = settings.search_top_k if top_k is None else top_k

    if strategy == "lexical" and threshold is not None:
        raise ValueError(
            "un seuil de refus n'a pas de sens pour la configuration lexicale : le score "
            "BM25 n'est pas borné (Q4 §3). Passer threshold=None pour « lexical »."
        )

    run = _STRATEGIES.get(strategy)
    if run is None:
        raise NotImplementedError(f"étage de recherche « {strategy} » inconnu.")

    if reranker is None and strategy == "hybrid":
        reranker = build_reranker(settings)

    hits = run(query, top_k, version_filter, settings, embedder, reranker, text, perimeter)
    if tiebreak:
        hits = apply_tiebreak(hits)

    if threshold is not None and (not hits or hits[0].score < threshold):
        # Le refus tombe ici, avant tout appel au modèle : aucun token dépensé, aucune
        # occasion d'inventer (Q4 §3).
        return SearchResult(
            status=STATUS_OUT_OF_CORPUS, hits=[], message=_OUT_OF_CORPUS_MESSAGE
        )
    return SearchResult(status=STATUS_OK, hits=hits)
