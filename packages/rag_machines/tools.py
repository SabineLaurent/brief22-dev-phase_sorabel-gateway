"""Les quatre tools documentaires, en fonctions Python.

Symétrique de ``packages/text_to_sql_factory/tools.py``, et pour les mêmes raisons : elles
rendent un :class:`RagStructuredAnswer` **complet**, aucune n'écrit au journal, aucune ne
connaît de client. La frontière — journaliser puis purger — est dans ``handler.py``.

Le paramètre ``profile`` est un argument **interne**. Il ne figure dans aucune signature
exposée : le serveur MCP le lira dans son environnement, jamais dans ce que le client
envoie — un paramètre présent dans l'``inputSchema`` serait rempli par le LLM du client.

Le clivage entre les quatre n'est pas « haut niveau contre briques », c'est le **mode
d'adressage** (``03-catalogue-tools.md``) : ``answer_question`` et ``search_docs`` cherchent
par *similarité*, ``get_document`` et ``list_sources`` adressent par *identité*. Les deux
premiers passent par le filtre d'index du périmètre ; les deux seconds ne l'empruntent pas
et vérifient l'autorisation autrement — sans quoi la fermeture des notes serait
contournable par un simple chemin de fichier (``Q3`` §8).

**Le texte variable ne va jamais au client.** Une collection fermée, un message de SDK, une
exception : tout cela part en ``cause``, vers le journal. Le client lit une phrase figée
choisie sur le code. C'est le correctif du chantier précédent, appliqué ici d'emblée — le
jet mis de côté nommait au client la collection qu'il venait de lui refuser, ce qui
transformait le refus en oracle sur la matrice.
"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from config import REPO_ROOT, Settings
from config import settings as default_settings
from packages.rag_machines.access_rag import perimeter_for
from packages.rag_machines.ingest.index import collection_name, connect
from packages.rag_machines.ingest.normalize import classify, normalize
from packages.rag_machines.retrieval.perimeter import Perimeter
from packages.rag_machines.retrieval.search import (
    STATUS_OUT_OF_CORPUS,
    Hit,
    Strategy,
    citation,
    search,
)
from packages.rag_machines.structured_answer import (
    RagStructuredAnswer,
    build_rag_structured_answer,
)
from packages.rag_machines.writer import AnswerWriter, build_writer

__all__ = ["answer_question", "search_docs", "get_document", "list_sources",
           "question_for_writer", "threshold_for"]

#: L'étage de recherche servi par les tools. La configuration C est celle que la mesure E6
#: retient — Hit@1 8/8 contre 2/8 en dense seul (``eval/rapport_gain.md``). Les autres
#: valeurs restent atteignables par argument : c'est ce qui permet au harnais de mesure de
#: rejouer une configuration sans passer par une variante de tool.
DEFAULT_STRATEGY: Strategy = "hybrid"

_FORBIDDEN_PERIMETER = "perimetre_interdit"

#: Une question réduite à une référence produit, et rien d'autre : « REF-5313 ». Le motif
#: est **ancré sur toute la chaîne** exprès — une référence citée au milieu d'une phrase
#: est déjà une question, et la compléter la déformerait.
_RE_BARE_REFERENCE = re.compile(r"^\s*(REF-\d{4})\s*\??\s*$", re.IGNORECASE)


def threshold_for(strategy: Strategy, settings: Settings) -> float | None:
    """Le seuil de refus de la configuration demandée — jamais celui d'une autre.

    Les échelles ne sont pas comparables (``Q5`` §4) : ``dense`` note en similarité cosinus,
    ``hybrid`` sur l'échelle apprise du reranker, et ``lexical`` n'a pas d'échelle bornée du
    tout — la case est vide, et c'est un résultat, pas un trou. Servir le seuil dense à une
    recherche hybride ferait refuser presque tout ; l'inverse ne refuserait jamais rien.
    """
    if strategy == "dense":
        return settings.refusal_threshold
    if strategy == "hybrid":
        return settings.rerank_threshold
    return None


def _resolve_perimeter(
    profile: str, collections: list[str] | None, settings: Settings
) -> tuple[Perimeter | None, RagStructuredAnswer | None]:
    """Le périmètre effectif du profil, réduit aux collections demandées. Ou un refus.

    Deux refus distincts, tous deux ``perimetre_interdit`` à l'étage 3 :

    * le profil n'ouvre aucune collection — le refus tombe **avant** toute requête à
      l'index, donc rien n'est lu et rien ne peut fuir par une clause mal formée ;
    * le client demande explicitement une collection qui lui est fermée. On **refuse**, on
      ne rogne pas en silence (``Q3`` §8) : une intersection muette rendrait un résultat
      vide ou partiel que le client lirait « rien à ce sujet ». Les collections en cause
      partent en ``forbidden``, vers le journal — jamais au client.

    L'argument ``collections`` **réduit** un périmètre, il ne le définit jamais : le filtre
    appliqué à l'index est construit depuis la matrice, jamais recopié depuis le client.
    """
    perimeter = perimeter_for(profile, settings)
    if perimeter is None:
        return None, build_rag_structured_answer(
            _FORBIDDEN_PERIMETER, etage=3,
            cause=f"aucune collection ouverte au profil « {profile} »",
        )
    if not collections:
        return perimeter, None

    asked = list(dict.fromkeys(collections))
    closed = [name for name in asked if name not in perimeter.doc_types]
    if closed:
        return None, build_rag_structured_answer(
            _FORBIDDEN_PERIMETER, etage=3,
            forbidden=tuple(closed),
            cause=(f"collections fermées au profil « {profile} » : "
                   f"{', '.join(closed)}"),
        )
    return Perimeter(doc_types=frozenset(asked), themes=perimeter.themes), None


def _source(doc_id: str, metadata: dict[str, Any]) -> dict[str, str]:
    """Une source, dans la forme du contrat DSI.

    Passe par ``citation()`` plutôt que de relire les métadonnées ici : la règle de repli de
    ``reference`` sur ``doc_key`` — imposée par le test T1, qui interroge une procédure SAV
    et exige pourtant une référence non vide — n'a qu'un seul endroit où vivre. Écrite deux
    fois, elle divergerait le jour où l'une des deux serait corrigée.
    """
    return citation(Hit(doc_id=doc_id, score=0.0, text="", metadata=metadata))


def _read_collection(settings: Settings):  # type: ignore[no-untyped-def]
    """La collection, ouverte **en lecture seule**, sans embedder.

    ``get_collection()`` d'``ingest/index.py`` construit un ``Embedder`` pour l'attacher à la
    collection : c'est indispensable pour indexer ou interroger par vecteur, et inutile ici
    — ``get_document`` et ``list_sources`` n'appellent que ``get()``, qui ne vectorise rien.
    Charger ``multilingual-e5-base`` pour lire une métadonnée coûterait plusieurs secondes au
    premier appel, et le serveur MCP a trente secondes pour répondre à ``initialize``.
    """
    return connect(settings).get_collection(name=collection_name(settings))


def question_for_writer(question: str) -> str:
    """La question telle que le **rédacteur** la reçoit. Identique, sauf référence nue.

    « REF-5313 » n'est pas une question : le retrieval est parfait — score 1,0000, la bonne
    fiche au premier rang — et le rédacteur cherche pourtant un énoncé, n'en trouve pas, et
    déclare l'insuffisance. Le refus vient alors de la forme de la demande, pas du corpus.

    **La recherche garde la référence nue** : c'est cette forme-là que BM25 attrape. Seul
    l'énoncé passé au modèle est complété, et il l'est **ici** plutôt que dans le
    ``_SYSTEM_PROMPT`` du rédacteur. Mesuré, les deux corrigent RAG-03 et RAG-05 ; la règle
    écrite au prompt desserre en plus la barrière 2 au-delà du cas visé — RAG-18 et RAG-20,
    stables en ``contexte_insuffisant`` sur trois passes, basculent en ``ok`` alors que le
    corpus ne porte pas leur réponse, ce qui est un recul d'E1. Une règle générale dans un
    prompt ne sait pas rester locale ; un cas nommé dans le code, si.
    """
    match = _RE_BARE_REFERENCE.match(question)
    if match is None:
        return question
    return f"Quelles sont les caractéristiques de la référence {match.group(1).upper()} ?"


def _elapsed(started: float) -> int:
    """La latence en millisecondes, arrondie. Diagnostic : elle ne part qu'au journal."""
    return round((perf_counter() - started) * 1000)


def search_docs(
    query: str,
    profile: str,
    *,
    collections: list[str] | None = None,
    settings: Settings | None = None,
    strategy: Strategy = DEFAULT_STRATEGY,
    **kwargs: Any,
) -> RagStructuredAnswer:
    """Les extraits classés, sans génération. La brique de l'IDE, qui a son propre LLM.

    **Aucune barrière de refus documentaire ici** : ``search_docs`` ne connaît ni
    ``hors_corpus`` ni ``contexte_insuffisant`` (``03-catalogue-tools.md``, sa fiche). Deux
    raisons, et la seconde est la vraie : le client compose lui-même, donc c'est à lui de
    juger ; et c'est le seul tool sur lequel E6 est mesurable — un seuil qui masque les
    résultats sous la barre rendrait le rang inobservable, et la mesure de gain sans objet.

    Une recherche qui ne remonte rien rend ``aucune_ligne``, pas un refus : la gateway a
    fait ce qu'on lui demandait.
    """
    settings = settings or default_settings
    started = perf_counter()
    perimeter, refusal = _resolve_perimeter(profile, collections, settings)
    if refusal is not None:
        return refusal

    result = search(query, strategy=strategy, threshold=None, perimeter=perimeter,
                    settings=settings, **kwargs)
    latency = _elapsed(started)
    if not result.hits:
        return build_rag_structured_answer("aucune_ligne", hits=[], n_rows=0,
                                           latency_ms=latency)
    return build_rag_structured_answer(
        "ok",
        hits=[
            {"doc_id": hit.doc_id, "score": round(hit.score, 6), "text": hit.text,
             "metadata": dict(hit.metadata)}
            for hit in result.hits
        ],
        n_rows=len(result.hits),
        latency_ms=latency,
    )


def answer_question(
    question: str,
    profile: str,
    *,
    collections: list[str] | None = None,
    settings: Settings | None = None,
    strategy: Strategy = DEFAULT_STRATEGY,
    writer: AnswerWriter | None = None,
    **kwargs: Any,
) -> RagStructuredAnswer:
    """La réponse rédigée et sourcée. **Le seul endroit où E1 existe.**

    Deux barrières, dans cet ordre :

    1. ``hors_corpus`` — le score du premier résultat est sous le seuil de la configuration.
       Déterministe, aveugle au contenu, et surtout **avant tout appel au modèle** : aucun
       token dépensé, aucune occasion d'inventer ;
    2. ``contexte_insuffisant`` — les extraits sont passés au modèle, qui dit qu'ils ne
       portent pas la réponse. Probabiliste, mais elle lit ce que la première ne lit pas.

    Dans les deux cas, ``answer`` est **absent** du payload servi — les deux codes sont hors
    de ``PAYLOAD_KEPT``. C'est ce qui empêche un client de rendre une non-réponse comme une
    réponse : il n'y a rien à afficher.

    La question part **telle quelle** à la recherche, et passe par
    :func:`question_for_writer` avant d'atteindre le rédacteur : une référence nue n'est pas
    un énoncé, et la barrière 2 la refusait sur un retrieval parfait.

    Les ``sources`` sont construites en Python depuis les métadonnées. Le modèle ne rend que
    les *numéros* des extraits qu'il a utilisés ; ceux qui sortent des bornes sont ignorés.
    Il ne peut donc pas citer un document qu'on ne lui a pas montré, ni inventer une
    référence — il n'écrit aucune référence.
    """
    settings = settings or default_settings
    started = perf_counter()
    perimeter, refusal = _resolve_perimeter(profile, collections, settings)
    if refusal is not None:
        return refusal

    result = search(question, strategy=strategy, threshold=threshold_for(strategy, settings),
                    perimeter=perimeter, settings=settings, **kwargs)
    if result.status == STATUS_OUT_OF_CORPUS or not result.hits:
        # Le seuil a tranché, ou la recherche n'a rien remonté du tout. Le message de
        # `SearchResult` est descriptif, pas destiné au client : il part en cause.
        return build_rag_structured_answer(
            "hors_corpus",
            cause=result.message or "aucun extrait au-dessus du seuil de refus",
            latency_ms=_elapsed(started),
        )

    try:
        writer = writer or build_writer(settings)
        answer = writer.write(question_for_writer(question),
                              [hit.text for hit in result.hits])
    except Exception as error:  # noqa: BLE001 - toute panne du fournisseur est la même ici
        return build_rag_structured_answer(
            "erreur_execution",
            cause=f"rédaction indisponible : {type(error).__name__}: {error}",
            latency_ms=_elapsed(started),
        )

    latency = _elapsed(started)
    if not answer.is_sufficient:
        # Ce que le modèle dit manquer est *son* énoncé : il va au journal, pas à l'écran.
        return build_rag_structured_answer("contexte_insuffisant",
                                           cause=answer.insufficient, latency_ms=latency)

    used = [rank for rank in answer.used if 1 <= rank <= len(result.hits)]
    cited = [result.hits[rank - 1] for rank in used] or [result.hits[0]]
    return build_rag_structured_answer(
        "ok",
        answer=answer.text,
        sources=[_source(hit.doc_id, dict(hit.metadata)) for hit in cited],
        n_rows=len(cited),
        latency_ms=latency,
    )


def get_document(
    doc_id: str,
    profile: str,
    *,
    version: str | None = None,
    settings: Settings | None = None,
) -> RagStructuredAnswer:
    """Une édition précise, nommée. Le texte intégral, liens sortants compris.

    **L'autorisation se décide sur le seul argument, avant tout accès à l'index** : le
    ``doc_id`` porte la collection et — pour une note — le thème, tous deux dérivés du nom de
    fichier (``classify()``). Sans cette vérification, la fermeture des notes serait
    contournable par un chemin de fichier : ``get_document("notes/note-…-politique-tarifaire-71")``
    rendrait au support une marge cible que ``search_docs`` lui refuse.

    **Le refus est ``perimetre_interdit``, jamais ``introuvable``** (``Q3`` §8). Répondre
    « introuvable » ferait croire à une absence et supprimerait le recours. Conséquence
    assumée : un identifiant inventé sous un thème fermé reçoit ``perimetre_interdit`` alors
    qu'il n'existe pas — ce qui n'apprend rien sur son existence, et c'est le bon compromis.

    ``doc_id`` accepte un ``edition_id`` (``fiches/REF-8842-v2.1``) comme un ``doc_key``
    (``fiches/REF-8842``) : la suite d'acceptance y passe le ``doc_id`` d'un résultat de
    ``search_docs``, qui est un ``edition_id``. Sans ``version``, c'est l'édition courante.
    """
    settings = settings or default_settings
    started = perf_counter()

    identity = classify(doc_id)
    if identity is None:
        return build_rag_structured_answer(
            "introuvable", cause=f"identifiant hors corpus : « {doc_id} »")
    doc_type, theme = identity

    perimeter = perimeter_for(profile, settings)
    if perimeter is None:
        return build_rag_structured_answer(
            _FORBIDDEN_PERIMETER, etage=3,
            cause=f"aucune collection ouverte au profil « {profile} »",
        )
    if not perimeter.allows(doc_type, theme):
        return build_rag_structured_answer(
            _FORBIDDEN_PERIMETER, etage=3,
            forbidden=(f"{doc_type}/{theme}" if theme else doc_type,),
            cause=(f"« {doc_id} » hors du périmètre du profil « {profile} »"),
        )

    try:
        collection = _read_collection(settings)
        metadata = _locate(collection, doc_id, version)
    except Exception as error:  # noqa: BLE001 - index injoignable, pas une décision métier
        return build_rag_structured_answer(
            "erreur_execution", cause=f"{type(error).__name__}: {error}")

    if metadata is None:
        return build_rag_structured_answer(
            "introuvable", cause=f"aucune édition pour « {doc_id} » (version={version})")

    path = REPO_ROOT / str(metadata.get("url", ""))
    try:
        text = normalize(path, settings.corpus_dir).full_text
    except Exception as error:  # noqa: BLE001 - fichier déplacé ou illisible
        return build_rag_structured_answer(
            "erreur_execution",
            cause=f"édition illisible sur disque : {type(error).__name__}: {error}")

    return build_rag_structured_answer(
        "ok",
        text=text,
        metadata=dict(metadata),
        latency_ms=_elapsed(started),
    )


def _locate(collection, doc_id: str, version: str | None) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    """Les métadonnées de l'édition désignée, ou ``None``.

    Trois cas, dans cet ordre : l'identifiant désigne une édition et aucune version n'est
    demandée — on la rend telle quelle ; une version est demandée — on cherche cette version
    du document ; sinon — l'édition courante du document. Le ``doc_key`` est relu depuis les
    métadonnées quand l'identifiant est un ``edition_id``, plutôt que dérivé une seconde fois
    par expression régulière : c'est l'ingestion qui l'a posé, elle fait foi.
    """
    exact = collection.get(ids=[doc_id], include=["metadatas"])
    found = [dict(entry) for entry in (exact.get("metadatas") or [])]
    if found and version is None:
        return found[0]

    doc_key = str(found[0].get("doc_key", doc_id)) if found else doc_id
    clause: dict[str, Any] = (
        {"version": {"$eq": version}} if version is not None else {"is_current": {"$eq": True}}
    )
    matched = collection.get(
        where={"$and": [{"doc_key": {"$eq": doc_key}}, clause]}, include=["metadatas"]
    )
    entries = [dict(entry) for entry in (matched.get("metadatas") or [])]
    return entries[0] if entries else None


def list_sources(
    profile: str,
    *,
    collections: list[str] | None = None,
    settings: Settings | None = None,
) -> RagStructuredAnswer:
    """L'inventaire de ce que le corpus couvre, **tel que ce profil a le droit de le voir**.

    Le pendant documentaire de ``get_schema`` : il rend le périmètre inspectable sans
    déclencher de recherche, et fait de « hors corpus » un fait vérifiable *avant* la
    question plutôt qu'un constat après un refus.

    **L'inventaire est construit depuis le périmètre, jamais par un parcours du corpus.** Un
    inventaire non filtré publierait l'existence et le nombre des notes fermées au profil, ce
    qui est déjà une information : il annoncerait 350 éditions à un profil ``dev`` qui n'en
    atteint que 270, et nommerait les thèmes fermés au ``support``. Les effectifs qu'il
    annonce sont exactement ceux qu'une recherche peut atteindre.

    Seules les éditions **courantes** y figurent, comme dans la recherche. L'édition
    antérieure d'un document reste atteignable par ``get_document`` avec sa ``version`` —
    c'est la raison d'être de ce tool-là.
    """
    settings = settings or default_settings
    started = perf_counter()
    perimeter, refusal = _resolve_perimeter(profile, collections, settings)
    if refusal is not None:
        return refusal
    if perimeter is None:  # pragma: no cover - _resolve_perimeter rend l'un ou l'autre
        return build_rag_structured_answer(
            _FORBIDDEN_PERIMETER, etage=3, cause="périmètre non résolu")

    try:
        collection = _read_collection(settings)
        listed = collection.get(where=perimeter.where(True), include=["metadatas"])
    except Exception as error:  # noqa: BLE001 - index injoignable, pas une décision métier
        return build_rag_structured_answer(
            "erreur_execution", cause=f"{type(error).__name__}: {error}")

    sources = sorted(
        (
            {**_source(str(metadata.get("edition_id", "")), dict(metadata)),
             "doc_id": str(metadata.get("edition_id", "")),
             "doc_type": str(metadata.get("doc_type", ""))}
            for metadata in (dict(entry) for entry in (listed.get("metadatas") or []))
        ),
        key=lambda source: source["doc_id"],
    )
    code = "ok" if sources else "aucune_ligne"
    return build_rag_structured_answer(
        code,
        sources=sources,
        n_rows=len(sources),
        latency_ms=_elapsed(started),
    )
