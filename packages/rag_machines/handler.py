"""Le point de passage unique des tools documentaires : journalise, puis purge.

Décalque de ``packages/text_to_sql_factory/handler.py``, et volontairement plus court : le
pendant SQL porte une classe ``SqlToolLauncher`` avec une méthode par tool, produit d'une
revue antérieure. Rien ici ne demande cette indirection — l'aiguillage tient dans une
table, et une table se lit d'un coup d'œil, ce qui est exactement ce qu'on veut d'un
endroit où l'on vérifie qu'aucun tool n'a de chemin dérobé.

Trois choses, dans cet ordre, **et l'ordre est la garantie** :

1. l'appel du tool, sous ``except Exception`` : ce qui échappe à la bibliothèque est
   rattrapé ici et devient un ``erreur_execution`` avec sa trace ;
2. l'écriture au journal, sur l'objet **entier** ;
3. la vue client, purgée.

Journaliser après la purge effacerait la cause pour tout le monde, débug compris.

**L'étage 2 est exercé ici**, par le même ``authorize()`` que le SQL : un tool hors matrice
produit un ``tool_interdit`` avant tout travail, et le refus est journalisé comme les
autres. Les fonctions de ``tools.py`` restent inchangées : appelées en direct — par les
contrôles déterministes par exemple — elles ne connaissent que l'étage 3.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from config import Settings
from config import settings as default_settings
from packages import journal
from packages.access import authorize
from packages.rag_machines.models import RagToolRequest
from packages.rag_machines.structured_answer import (
    MALFORMED_ARGUMENT,
    RagStructuredAnswer,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.rag_machines.tools import (
    answer_question,
    get_document,
    list_sources,
    search_docs,
)

#: Les quatre tools documentaires du catalogue DSI. Par tool : la fonction, les arguments
#: **requis** dans l'ordre positionnel, et les arguments **optionnels** passés par mot-clé.
#:
#: ``profile`` n'y figure pas : c'est un argument interne, lu dans l'environnement du
#: serveur et jamais dans ce que le client envoie — un paramètre présent dans
#: l'``inputSchema`` serait rempli par le LLM du client.
#:
#: **Les noms d'arguments suivent la suite d'acceptance, pas le dossier de conception.**
#: ``03-catalogue-tools.md`` écrit ``search_docs(question)`` et ``get_document(doc_key)`` ;
#: ``tests/acceptance/`` appelle ``search_docs {"query": …}`` et
#: ``get_document {"doc_id": …}``. La règle d'arbitrage du dépôt est que le test fait foi,
#: et l'écart est consigné au journal de développement.
RAG_TOOLS: dict[
    str, tuple[Callable[..., RagStructuredAnswer], tuple[str, ...], tuple[str, ...]]
] = {
    "answer_question": (answer_question, ("question",), ("collections",)),
    "search_docs": (search_docs, ("query",), ("collections",)),
    "get_document": (get_document, ("doc_id",), ("version",)),
    "list_sources": (list_sources, (), ("collections",)),
}


def _deliver(tool: str, profile: str, arguments: dict[str, Any],
             answer: RagStructuredAnswer, settings: Settings) -> dict[str, Any]:
    """Journalise l'objet entier, puis rend la vue client. **Jamais dans l'autre sens.**"""
    journal.record(tool, profile, arguments, answer, settings)
    return rag_client_view(answer)


def _launch(request: RagToolRequest, settings: Settings) -> RagStructuredAnswer:
    """Vérifie le tool, le profil et les arguments, puis appelle.

    L'ordre compte : le tool inconnu d'abord — on ne peut pas autoriser ce qu'on ne connaît
    pas —, puis l'étage 2, puis la forme des arguments. Vérifier les arguments avant les
    droits renseignerait sur la signature d'un tool interdit.
    """
    entry = RAG_TOOLS.get(request.tool)
    if entry is None:
        return build_rag_structured_answer(
            "erreur_execution",
            client_key=MALFORMED_ARGUMENT,
            cause=f"tool inconnu : « {request.tool} »",
        )

    if not authorize(request.profile, request.tool, settings):
        return build_rag_structured_answer(
            "tool_interdit",
            etage=2,
            cause=(f"le profil « {request.profile} » n'a pas le tool "
                   f"« {request.tool} »"),
        )

    function, required, optional = entry
    missing = [name for name in required if request.arguments.get(name) is None]
    if missing:
        return build_rag_structured_answer(
            "erreur_execution",
            client_key=MALFORMED_ARGUMENT,
            cause=(f"argument manquant pour « {request.tool} » : "
                   f"{', '.join(missing)}"),
        )

    # Les optionnels absents ne sont pas passés du tout : c'est le défaut de la fonction
    # qui décide, pas un `None` transmis qui écraserait ce défaut.
    extra = {name: request.arguments[name] for name in optional
             if request.arguments.get(name) is not None}
    return function(
        *(request.arguments[name] for name in required),
        request.profile,
        settings=settings,
        **extra,
    )


def handle(tool: str, arguments: dict[str, Any], profile: str,
           settings: Settings | None = None) -> dict[str, Any]:
    """Appelle un tool documentaire au nom d'un profil, et rend les trois champs du DSI.

    Aucune exception ne sort de cette fonction : un appel se termine toujours par une
    entrée de journal et une réponse. C'est ce qui rend la fuite de trace impossible côté
    client plutôt que seulement improbable.
    """
    return handle_request(
        RagToolRequest(tool=tool, profile=profile, arguments=dict(arguments)),
        settings,
    )


def handle_request(request: RagToolRequest,
                   settings: Settings | None = None) -> dict[str, Any]:
    """Journalise et sérialise une commande documentaire déjà construite par l'adaptateur."""
    settings = settings or default_settings

    try:
        answer = _launch(request, settings)
    except Exception as error:  # noqa: BLE001 - le filet de dernier recours, et il est voulu
        # Ce qui arrive ici est un défaut, pas un cas prévu : la trace part au journal
        # entière, et le client reçoit une phrase qui ne dit rien de la pile.
        answer = build_rag_structured_answer(
            "erreur_execution",
            cause=f"{type(error).__name__}: {error}",
            stack=traceback.format_exc(),
        )
    return _deliver(request.tool, request.profile, request.arguments, answer, settings)
