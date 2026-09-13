"""La réponse des tools SQL : un objet, deux vues.

Le refus est déterministe — même question, même profil, même code. Mais entre la décision et
l'écran, le texte du refus était jusqu'ici **écrit par le modèle** : ``generation.reason`` sur
``ecriture_refusee`` et ``hors_schema``, ``generation.question`` sur ``clarification``. La même
demande refusée deux fois produisait donc deux phrases différentes, et le LLM de chat du
client en produisait une troisième en reformulant. La décision ne variait pas ; son énoncé,
si.

Le remède n'est pas de mieux instruire le modèle, c'est de **ne plus lui donner la parole
sur ce point**. Une phrase figée ne se reformule pas.

D'où un objet et deux vues, parce qu'il y a deux lecteurs et qu'ils n'ont pas les mêmes
besoins :

* la **vue client** (:func:`client_view`) rend les trois champs du contrat DSI —
  ``{"status", "payload", "message"}`` de ``docs/cadrage_dsi.md`` §Enveloppe de réponse — avec
  une phrase figée par code, et un ``payload`` réduit à son ``code`` sur tout refus. Ni nom de
  table, ni nom de colonne, ni requête, ni message d'exception ;
* le **journal** (``packages/journal.py``) reçoit l'objet entier : la cause technique, la
  requête, les colonnes refusées, l'étage qui a tranché, la trace d'exception. C'est là que
  le débug métier se fait, et ce lecteur-là n'est pas un LLM.

**La garantie est structurelle, pas conventionnelle.** ``cause``, ``stack`` et ``forbidden``
sont des attributs de dataclass, jamais des clés de dictionnaire. Un ``json.dumps`` distrait
sur l'objet échoue ; il ne fuit pas. La seule fonction qui produit un dict sérialisable est
:func:`client_view`, et elle travaille sur liste blanche.

**Un refus reste lisible comme un refus.** « Aucune donnée disponible » dirait une absence là
où il y a une interdiction : l'utilisateur en conclurait que la donnée n'existe pas et ne
demanderait jamais l'habilitation. Les phrases ci-dessous ne nomment rien, mais elles ne
mentent pas non plus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Des codes du catalogue vers les cinq statuts du contrat DSI. C'est le seul endroit de la
#: conversion : un statut calculé ailleurs finirait par diverger.
#:
#: `aucune_ligne` et `ambiguite_donnees` sont des `ok` : le serveur a fait ce qu'on lui
#: demandait, et le résultat n'a rien donné ou plusieurs choses. Les marquer en refus ferait
#: compter au journal des refus qui n'ont jamais eu lieu, et la lecture d'E5 surestimerait
#: la sévérité du système.
DB_STATUS_BY_CODE = {
    "ok": "ok",
    "aucune_ligne": "ok",
    "ambiguite_donnees": "ok",
    "clarification": "clarification",
    "tool_interdit": "refused",
    "perimetre_interdit": "refused",
    "ecriture_refusee": "refused",
    "hors_schema": "refused",
    "erreur_execution": "error",
}

#: Les quatre codes qui sont des **refus** — ce que la gateway a refusé de faire. Le journal
#: en tire sa décision ``denied``. ``erreur_execution`` n'en fait pas partie : rien n'a été
#: refusé, l'exécution a échoué. C'est le seul code où les deux notions se séparent.
REFUSAL_CODES = frozenset({"tool_interdit", "perimetre_interdit", "ecriture_refusee",
                           "hors_schema"})

SERVED_CODES = frozenset({"ok", "aucune_ligne", "ambiguite_donnees", "clarification"})

#: Une clé de message qui n'est pas un code. ``erreur_execution`` recouvre deux situations
#: que l'utilisateur ne vit pas du tout pareil : l'appel était mal formé (il peut corriger),
#: ou le service a échoué (il ne peut qu'attendre). Le catalogue n'a pas de code pour la
#: première — l'arbitrage est consigné au journal de développement — mais leur confondre le
#: message ferait réessayer indéfiniment la même référence invalide. Ensemble **fermé** : la
#: variation reste choisie par le code, jamais rédigée par le modèle.
MALFORMED_ARGUMENT = "argument_malforme"

#: Ce que l'utilisateur lit, par clé. **Aucune de ces phrases ne nomme une table, une
#: colonne, un tool ni un code.** Elles sont écrites ici une fois et rendues telles quelles.
#:
#: Trois familles, parce que le recours de l'utilisateur diffère :
#:   - je n'ai pas le droit → il peut demander une habilitation ;
#:   - il n'y en a pas       → il peut reformuler, ou chercher ailleurs ;
#:   - ça n'a pas marché     → il peut corriger, ou réessayer plus tard.
#: Les confondre en une seule phrase supprimerait le recours avec la distinction.
CLIENT_MESSAGES = {
    # `ok` n'a pas de phrase : c'est le résultat qui parle. Le contrat DSI n'exige un
    # message que pour les statuts autres que `ok`.
    "ok": "",
    # La gateway a fait ce qu'on lui demandait, et le monde n'a rien à rendre ou plusieurs
    # choses. Ce sont des constats, pas des décisions.
    "aucune_ligne": "Aucune donnée ne correspond à cette demande.",
    "ambiguite_donnees": ("Plusieurs enregistrements correspondent à cette demande ; "
                          "ils sont tous rendus."),
    # Un tour rendu à l'utilisateur. Les `axes` du payload complètent la phrase : ils sont
    # calculés par le code et filtrés par la matrice, donc déjà déterministes.
    "clarification": ("Votre question admet plusieurs lectures. Précisez laquelle vous "
                      "intéresse."),
    # La gateway a refusé. La phrase reste un refus, sans dire ce qui a été refusé :
    # l'énumération des colonnes fermées transformerait le refus en oracle — en sondant, on
    # cartographierait la matrice.
    "tool_interdit": "Cette information n'est pas accessible avec votre profil.",
    "perimetre_interdit": "Cette information n'est pas accessible avec votre profil.",
    "ecriture_refusee": ("La gateway est en lecture seule : aucune modification n'est "
                         "possible."),
    "hors_schema": "Cette question ne porte pas sur les données disponibles.",
    # La gateway n'a pas pu. Le dire évite que l'utilisateur croie la donnée inexistante
    # alors qu'elle est seulement inatteignable.
    "erreur_execution": "Le service est momentanément indisponible. Réessayez plus tard.",
    MALFORMED_ARGUMENT: ("La demande n'est pas au format attendu. Vérifiez l'identifiant "
                         "fourni et réessayez."),
}

#: Repli. Une clé non prévue est traitée comme une panne, jamais comme une réponse : mieux
#: vaut annoncer une indisponibilité à tort que rendre un refus comme un résultat.
_FALLBACK = CLIENT_MESSAGES["erreur_execution"]

#: Les clés de payload qui partent au client sur un code de **résultat**. C'est la forme du
#: cadrage — ``{"sql", "columns", "rows"}`` — plus ce que les tools figés ajoutent et les
#: conventions de calcul, sans lesquelles un chiffre de marge n'est pas vérifiable.
#:
#: ``n_rows`` et ``latency_ms`` n'y sont pas : c'est du diagnostic, il va au journal. Le
#: client compte les lignes qu'il a reçues.
#:
#: ``entries`` est la charge utile de la lecture du journal — un résultat comme un autre,
#: réservé au profil qui en a le droit par la matrice.
_RESULT_KEYS = ("code", "sql", "columns", "rows", "total", "reference", "order_id",
                "conventions", "schema", "truncated", "entries")

#: Sur ``clarification``, les axes suivent la phrase figée — sans eux, l'utilisateur ne sait
#: pas entre quoi choisir.
_CLARIFICATION_KEYS = ("code", "axes")

#: Par code, ce que le payload conserve. Tout code absent de cette table — les quatre refus
#: et ``erreur_execution`` — voit son payload réduit à ``{"code": …}``.
#:
#: C'est cette asymétrie qui fait le travail : un client qui lit le champ structuré n'a rien
#: à afficher sur un refus, donc il ne peut pas afficher un refus comme une réponse. Un
#: champ vide, lui, se rend sans qu'on y pense.
PAYLOAD_KEPT = {
    "ok": _RESULT_KEYS,
    "aucune_ligne": _RESULT_KEYS,
    "ambiguite_donnees": _RESULT_KEYS,
    "clarification": _CLARIFICATION_KEYS,
}


@dataclass(frozen=True)
class DbStructuredAnswer:
    """Ce qu'un tool SQL rend : la décision, la charge utile, et la cause.

    Les trois derniers champs — ``cause``, ``stack``, ``forbidden`` — ne sortent **jamais**
    vers le client. Ils ne sont pas dans le payload pour cette raison précise : ils ne
    peuvent pas être emportés par distraction.
    """

    #: L'un des codes de :data:`DB_STATUS_BY_CODE`.
    code: str
    #: La charge utile, filtrée par :data:`PAYLOAD_KEPT` avant de partir au client. Elle
    #: porte le diagnostic (``n_rows``, ``latency_ms``) que seul le journal lit.
    payload: dict[str, Any] = field(default_factory=dict)
    #: La cause technique, en clair : le texte du modèle, le message SQLite, ``str(exc)``.
    #: **Journal seulement.**
    cause: str = ""
    #: ``traceback.format_exc()``, renseigné sur exception. **Journal seulement.**
    stack: str = ""
    #: Les colonnes fermées qui ont motivé le refus, en ``table.colonne``.
    #: **Journal seulement** — les nommer au client renseignerait sur la matrice.
    forbidden: tuple[str, ...] = ()
    #: L'étage de la défense en profondeur qui a tranché : 3 pour la matrice et l'AST, 2
    #: réservé au droit d'appeler un tool (serveur MCP), ``None`` hors décision d'accès.
    #: C'est ce champ qui rend la défense en profondeur vérifiable au journal.
    etage: int | None = None
    #: ``0`` si la réponse a été servie, l'étage bloquant pour une décision de sécurité,
    #: ``None`` si la chaîne s'est arrêtée sur une panne ou une décision du modèle.
    blocked_at: int | None = None
    #: Clé de message quand elle diffère du code — un ensemble fermé, cf.
    #: :data:`MALFORMED_ARGUMENT`. Vide dans le cas courant.
    client_key: str = ""

    @property
    def status(self) -> str:
        """Le statut du contrat DSI. Un code inconnu vaut ``error`` : mieux vaut un statut
        trop sévère qu'un refus rendu comme un résultat."""
        return DB_STATUS_BY_CODE.get(self.code, "error")

    @property
    def message(self) -> str:
        """La phrase figée à afficher. Rendue **telle quelle** : ni reformulée, ni résumée,
        ni enrichie. C'est ce qui rend l'affichage aussi déterministe que la décision."""
        return CLIENT_MESSAGES.get(self.client_key or self.code, _FALLBACK)

    @property
    def refused(self) -> bool:
        """La gateway a-t-elle refusé de faire ? Distinct de « a-t-elle échoué »."""
        return self.code in REFUSAL_CODES

def build_db_structured_answer(code: str, *, cause: str = "", stack: str = "",
                               forbidden: tuple[str, ...] = (), etage: int | None = None,
                               blocked_at: int | None = None,
                               client_key: str = "",
                               **payload: Any) -> DbStructuredAnswer:
    """Construit la réponse d'un tool SQL. ``code`` est toujours dans le payload, ``ok``
    compris — le journal le lit là, et un client qui veut le motif fin l'y trouve.

    Le texte variable passe par ``cause``, jamais par un message : c'est la séparation qui
    rend l'énoncé déterministe.
    """
    return DbStructuredAnswer(
        code=code,
        payload={"code": code, **payload},
        cause=cause,
        stack=stack,
        forbidden=tuple(forbidden),
        etage=etage,
        blocked_at=(etage if etage is not None else (0 if code in SERVED_CODES else blocked_at)),
        client_key=client_key,
    )


def client_view(answer: DbStructuredAnswer) -> dict[str, Any]:
    """L'objet tel que le client doit le recevoir — **le seul sérialiseur**.

    Trois clés, celles du contrat DSI, et rien d'autre. Le payload est filtré sur liste
    blanche : ce qui n'est pas explicitement conservé ne part pas, y compris une clé ajoutée
    demain sans y penser. C'est le sens de la liste blanche plutôt que d'une liste noire.
    """
    kept = PAYLOAD_KEPT.get(answer.code, ("code",))
    return {
        "status": answer.status,
        "payload": {key: answer.payload[key] for key in kept if key in answer.payload},
        "message": answer.message,
    }
