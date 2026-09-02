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

from dataclasses import dataclass, field
from typing import Literal, cast

from config import Settings
from config import settings as default_settings
from ingest.index import connect, get_collection
from ingest.normalize import TextProfile
from retrieval.embedder import Embedder, build_embedder

#: Les trois étages de recherche comparés par le protocole. Seul « dense » existe à
#: l'étape 2 ; les deux autres arrivent à l'étape 3, sans changer cette signature.
Strategy = Literal["dense", "lexical", "hybrid"]

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


def _dense_search(
    query: str,
    top_k: int,
    version_filter: bool,
    settings: Settings,
    embedder: Embedder,
    text: TextProfile,
) -> list[Hit]:
    """Recherche dense seule — la configuration A, l'« avant » que nomme le brief.

    Le filtre de version part **dans la requête** : Chroma l'applique avant de tronquer à
    ``top_k``, ce qui est exactement ce que demande ``Q1`` §5. Filtrer après coup rendrait
    le rang ininterprétable, et c'est le rang que consommera la fusion RRF de l'étape 3.
    """
    collection = get_collection(connect(settings), embedder, settings, text)
    response = collection.query(
        query_embeddings=[embedder.embed_query(query)],  # type: ignore[arg-type]
        n_results=top_k,
        where={"is_current": True} if version_filter else None,
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


_STRATEGIES = {"dense": _dense_search}


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
) -> SearchResult:
    """Cherche dans le corpus. Rend des résultats, ou un refus ``hors_corpus``.

    Chaque paramètre est un axe du protocole de mesure, et aucun n'a de valeur en dur
    ailleurs que dans la configuration.

    ``threshold`` est un **score minimal** — la similarité cosinus du premier résultat,
    soit ``1 - distance``. ``Q4`` §3 établit qu'un seuil ne peut pas porter sur un score
    lexical, non borné et incomparable d'une requête à l'autre ; ``Q5`` §4 désigne pour la
    configuration dense la distance cosinus, qui est bornée. C'est elle qu'on lit ici.
    Passer ``None`` désactive le refus — utile pour mesurer le rappel sans que la barrière
    ne masque un résultat.
    """
    settings = settings or default_settings
    embedder = embedder or build_embedder(settings)
    top_k = top_k or settings.search_top_k

    run = _STRATEGIES.get(strategy)
    if run is None:
        raise NotImplementedError(
            f"étage de recherche « {strategy} » non disponible : seul « dense » existe à "
            "l'étape 2, le lexical et l'hybride arrivent à l'étape 3."
        )

    hits = run(query, top_k, version_filter, settings, embedder, text)
    if tiebreak:
        hits = apply_tiebreak(hits)

    if threshold is not None and (not hits or hits[0].score < threshold):
        # Le refus tombe ici, avant tout appel au modèle : aucun token dépensé, aucune
        # occasion d'inventer (Q4 §3).
        return SearchResult(
            status=STATUS_OUT_OF_CORPUS, hits=[], message=_OUT_OF_CORPUS_MESSAGE
        )
    return SearchResult(status=STATUS_OK, hits=hits)
