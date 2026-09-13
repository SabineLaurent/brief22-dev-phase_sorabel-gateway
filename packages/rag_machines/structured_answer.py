"""La réponse des tools documentaires : un objet, deux vues.

Symétrique de ``packages/text_to_sql_factory/structured_answer.py``, et pour les mêmes
raisons — mais **parallèle, pas partagé**. Le choix mérite d'être dit, parce que
factoriser était l'autre option :

* les deux domaines n'ont pas les mêmes codes. Le SQL ignore ``hors_corpus`` et
  ``contexte_insuffisant`` ; le RAG ignore ``ecriture_refusee``, ``hors_schema`` et
  ``clarification``. Une table commune serait donc une union dont chaque moitié ne
  s'appliquerait qu'à un domaine, et le lecteur ne saurait plus lequel ;
* le SQL est vert sur 183 contrôles déterministes. Généraliser ``DbStructuredAnswer``
  aurait touché ce code-là pour un besoin qui n'est pas le sien.

Ce qui est **effectivement** partagé l'est par là où il doit l'être : le protocole
:class:`packages.journal.Journalable`. Il a été écrit structurel exprès — « le paquet SQL
le satisfait aujourd'hui, le RAG le satisfera demain, et ce module n'a besoin d'importer
ni l'un ni l'autre ». C'est ce module-ci qui honore cette phrase. Un seul journal, un seul
format d'entrée, deux domaines qui l'alimentent sans se connaître.

Le reste suit la discipline arrêtée au chantier précédent :

* la **vue client** (:func:`rag_client_view`) rend les trois champs du contrat DSI —
  ``{"status", "payload", "message"}`` — avec une **phrase figée par code**, et un payload
  réduit à son ``code`` sur tout refus ;
* le **journal** reçoit l'objet entier : la cause technique, les collections refusées,
  l'étage qui a tranché, la trace d'exception.

**La garantie est structurelle, pas conventionnelle.** ``cause``, ``stack`` et
``forbidden`` sont des attributs de dataclass, jamais des clés de dictionnaire. La seule
fonction qui produit un dict sérialisable est :func:`rag_client_view`, et elle travaille
sur liste blanche.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Des codes documentaires vers les statuts du contrat DSI
#: (``docs/cadrage_dsi.md`` §Enveloppe de réponse). Seul endroit de la conversion.
#:
#: Trois décisions s'y lisent :
#:
#: ``aucune_ligne`` et ``introuvable`` sont des ``ok`` — la gateway a fait ce qu'on lui
#: demandait, et le corpus n'a rien à rendre. Les marquer en refus ferait compter au
#: journal des refus qui n'ont jamais eu lieu, et la lecture d'E5 surestimerait la
#: sévérité du système. C'est le même arbitrage qu'``aucune_ligne`` côté SQL.
#:
#: ``contexte_insuffisant`` partage le statut ``hors_corpus`` sans partager son code. Les
#: deux disent à l'utilisateur la même chose — le corpus ne porte pas la réponse — et le
#: contrat DSI n'a pas de sixième statut pour les séparer. Le **code** les distingue, lui,
#: dans le payload et au journal : l'un est un seuil franchi avant tout appel au modèle,
#: l'autre un jugement du modèle sur des extraits qu'il a lus. C'est cette distinction que
#: la mesure exploite ; le statut, lui, n'a qu'à empêcher le client de rendre une
#: non-réponse comme une réponse.
RAG_STATUS_BY_CODE = {
    "ok": "ok",
    "aucune_ligne": "ok",
    "introuvable": "ok",
    "hors_corpus": "hors_corpus",
    "contexte_insuffisant": "hors_corpus",
    "tool_interdit": "refused",
    "perimetre_interdit": "refused",
    "erreur_execution": "error",
}

#: Les deux codes qui sont des **refus** — ce que la gateway a refusé de faire. Le journal
#: en tire sa décision ``denied``.
#:
#: ``hors_corpus`` et ``contexte_insuffisant`` n'en font **pas** partie, et c'est le point
#: le plus facile à se tromper de tout ce module : ils disent « je n'ai pas trouvé », pas
#: « je ne vous le donnerai pas ». Les compter en refus gonflerait E5 de non-réponses
#: documentaires et rendrait le taux de refus illisible.
REFUSAL_CODES = frozenset({"tool_interdit", "perimetre_interdit"})

#: Les codes où la chaîne a été parcourue jusqu'au bout — ``blocked_at`` vaut ``0``.
SERVED_CODES = frozenset({"ok", "aucune_ligne", "introuvable"})

#: Une clé de message qui n'est pas un code — même valeur littérale que côté SQL, pour que
#: le client lise la même phrase quel que soit le domaine. Recopiée plutôt qu'importée : le
#: RAG n'a pas à dépendre du paquet SQL pour énoncer un format d'argument.
MALFORMED_ARGUMENT = "argument_malforme"

#: Ce que l'utilisateur lit, par clé. **Aucune de ces phrases ne nomme une collection, un
#: thème, un tool ni un code.** Elles sont écrites ici une fois et rendues telles quelles.
#:
#: C'est le correctif du chantier précédent, appliqué d'emblée ici : le jet mis de côté
#: passait des textes calculés à l'enveloppe (« collection non ouverte à ce profil :
#: politique-tarifaire »), ce qui nommait au client exactement ce que la matrice ferme et
#: transformait le refus en oracle — en sondant, on cartographiait la matrice. Ces textes
#: existent toujours, mais ils partent en ``cause``, vers le journal.
RAG_CLIENT_MESSAGES = {
    # `ok` n'a pas de phrase : c'est le résultat qui parle.
    "ok": "",
    # Des constats, pas des décisions : la recherche a eu lieu, elle n'a rien remonté.
    "aucune_ligne": "Aucun extrait ne correspond à cette recherche.",
    "introuvable": "Aucune édition ne porte cet identifiant.",
    # Le corpus ne porte pas la réponse. Deux causes, un même recours : reformuler, ou
    # chercher ailleurs. Les phrases restent distinctes parce qu'elles n'invitent pas au
    # même geste — l'une dit « rien trouvé », l'autre « trouvé, mais ça ne répond pas ».
    "hors_corpus": "Le corpus documentaire ne couvre pas cette question.",
    "contexte_insuffisant": ("Les documents trouvés ne portent pas la réponse à cette "
                             "question."),
    # La gateway a refusé. La phrase reste un refus, sans dire ce qui a été refusé.
    "tool_interdit": "Cette information n'est pas accessible avec votre profil.",
    "perimetre_interdit": "Cette information n'est pas accessible avec votre profil.",
    # La gateway n'a pas pu. Le dire évite que l'utilisateur croie le document inexistant
    # alors qu'il est seulement inatteignable.
    "erreur_execution": "Le service est momentanément indisponible. Réessayez plus tard.",
    MALFORMED_ARGUMENT: ("La demande n'est pas au format attendu. Vérifiez l'identifiant "
                         "fourni et réessayez."),
}

#: Repli. Une clé non prévue est traitée comme une panne, jamais comme une réponse.
_FALLBACK = RAG_CLIENT_MESSAGES["erreur_execution"]

#: Les clés de payload qui partent au client sur un code de **résultat**. Ce sont
#: exactement celles du cadrage, tool par tool : ``answer`` + ``sources``
#: (``answer_question``), ``hits`` (``search_docs``), ``text`` + ``metadata``
#: (``get_document``), ``sources`` (``list_sources``).
#:
#: ``latency_ms`` n'y est pas : c'est du diagnostic, il va au journal.
_RESULT_KEYS = ("code", "answer", "sources", "hits", "text", "metadata")

#: Par code, ce que le payload conserve. Tout code absent de cette table — les deux refus,
#: ``hors_corpus``, ``contexte_insuffisant`` et ``erreur_execution`` — voit son payload
#: réduit à ``{"code": …}``.
#:
#: C'est cette asymétrie qui fait le travail sur ``answer_question`` : un client qui n'a
#: pas de clé ``answer`` ne peut pas afficher une non-réponse comme une réponse. La suite
#: d'acceptance le vérifie littéralement (``not result["payload"].get("answer")``).
PAYLOAD_KEPT = {
    "ok": _RESULT_KEYS,
    "aucune_ligne": _RESULT_KEYS,
    "introuvable": _RESULT_KEYS,
}


@dataclass(frozen=True)
class RagStructuredAnswer:
    """Ce qu'un tool documentaire rend : la décision, la charge utile, et la cause.

    Conforme à :class:`packages.journal.Journalable` — c'est la seule contrainte externe
    sur cette classe, et elle est structurelle : le journal n'importe rien d'ici.

    ``cause``, ``stack`` et ``forbidden`` ne sortent **jamais** vers le client. Ils ne sont
    pas dans le payload pour cette raison précise : ils ne peuvent pas être emportés par
    distraction.
    """

    #: L'un des codes de :data:`RAG_STATUS_BY_CODE`.
    code: str
    #: La charge utile, filtrée par :data:`PAYLOAD_KEPT` avant de partir au client. Elle
    #: porte le diagnostic (``latency_ms``, ``n_rows``) que seul le journal lit.
    payload: dict[str, Any] = field(default_factory=dict)
    #: La cause technique, en clair : la collection fermée qui a motivé le refus, le
    #: message du modèle, ``str(exc)``. **Journal seulement.**
    cause: str = ""
    #: ``traceback.format_exc()``, renseigné sur exception. **Journal seulement.**
    stack: str = ""
    #: Les collections ou thèmes fermés qui ont motivé le refus.
    #: **Journal seulement** — les nommer au client renseignerait sur la matrice.
    forbidden: tuple[str, ...] = ()
    #: L'étage de la défense en profondeur qui a tranché : 2 pour le droit d'appeler le
    #: tool, 3 pour le périmètre documentaire, ``None`` hors décision d'accès.
    etage: int | None = None
    #: ``0`` si la réponse a été servie, l'étage bloquant pour une décision de sécurité,
    #: ``None`` si la chaîne s'est arrêtée sur une panne, un seuil ou un jugement du
    #: modèle. Posé ici **en même temps** que la couche, pas après : les sites de
    #: construction de réponse doublent avec les huit tools, et un champ ajouté ensuite
    #: devrait repasser sur chacun.
    blocked_at: int | None = None
    #: Clé de message quand elle diffère du code — un ensemble fermé, cf.
    #: :data:`MALFORMED_ARGUMENT`. Vide dans le cas courant.
    client_key: str = ""

    @property
    def status(self) -> str:
        """Le statut du contrat DSI. Un code inconnu vaut ``error`` : mieux vaut un statut
        trop sévère qu'un refus rendu comme un résultat."""
        return RAG_STATUS_BY_CODE.get(self.code, "error")

    @property
    def message(self) -> str:
        """La phrase figée à afficher. Rendue **telle quelle** : ni reformulée, ni résumée,
        ni enrichie."""
        return RAG_CLIENT_MESSAGES.get(self.client_key or self.code, _FALLBACK)

    @property
    def refused(self) -> bool:
        """La gateway a-t-elle refusé de faire ? Distinct de « n'a-t-elle rien trouvé »."""
        return self.code in REFUSAL_CODES


def build_rag_structured_answer(code: str, *, cause: str = "", stack: str = "",
                                forbidden: tuple[str, ...] = (), etage: int | None = None,
                                blocked_at: int | None = None,
                                client_key: str = "",
                                **payload: Any) -> RagStructuredAnswer:
    """Construit la réponse d'un tool documentaire. ``code`` est toujours dans le payload,
    ``ok`` compris — le journal le lit là, et un client qui veut le motif fin l'y trouve.

    Le texte variable passe par ``cause``, jamais par un message : c'est la séparation qui
    rend l'énoncé déterministe.
    """
    return RagStructuredAnswer(
        code=code,
        payload={"code": code, **payload},
        cause=cause,
        stack=stack,
        forbidden=tuple(forbidden),
        etage=etage,
        blocked_at=(etage if etage is not None else (0 if code in SERVED_CODES else blocked_at)),
        client_key=client_key,
    )


def rag_client_view(answer: RagStructuredAnswer) -> dict[str, Any]:
    """L'objet tel que le client doit le recevoir — **le seul sérialiseur du domaine**.

    Trois clés, celles du contrat DSI, et rien d'autre. Le payload est filtré sur liste
    blanche : ce qui n'est pas explicitement conservé ne part pas, y compris une clé
    ajoutée demain sans y penser.
    """
    kept = PAYLOAD_KEPT.get(answer.code, ("code",))
    return {
        "status": answer.status,
        "payload": {key: answer.payload[key] for key in kept if key in answer.payload},
        "message": answer.message,
    }
