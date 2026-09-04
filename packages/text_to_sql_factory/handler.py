"""Le point de passage unique des tools SQL : journalise, puis purge.

Les fonctions de ``tools.py`` sont de la bibliothèque : elles décident, et elles rendent un
objet complet. Ce module est la **frontière** — le seul endroit où cet objet devient un
dictionnaire destiné à un client, et le seul endroit où il devient une ligne de journal.

Trois choses, dans cet ordre, **et l'ordre est la garantie** :

1. l'appel du tool, sous ``except Exception`` : ce qui échappe à la bibliothèque est
   rattrapé ici et devient un ``erreur_execution`` avec sa trace. Il en existe au moins un
   cas réel — le ``RuntimeError`` de ``executor._connect()`` sur base absente n'est attrapé
   nulle part le long de ``validate() → explain()/execute()`` ;
2. l'écriture au journal, sur l'objet **entier** ;
3. la vue client, purgée.

Journaliser après la purge effacerait la cause pour tout le monde, débug compris. C'est
pourquoi il n'y a qu'un chemin, et qu'il passe par ici.

**L'étage 2 est exercé ici.** Le chantier Text-to-SQL ne l'appliquait pas — il n'avait pas de
client à qui refuser. Ce module en a un, donc ``authorize()`` (écrit au chantier précédent et
jamais encore exercé) prend enfin son sens : un tool hors matrice produit un
``tool_interdit`` avant tout travail, et le refus est journalisé comme les autres. Les
fonctions de ``tools.py`` restent inchangées : appelées en direct — par ``check_sql`` par
exemple — elles ne connaissent toujours que l'étage 3.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from config import Settings
from config import settings as default_settings
from packages import journal
from packages.access import authorize
from packages.text_to_sql_factory.structured_answer import (
    DbStructuredAnswer,
    build_db_structured_answer,
    client_view,
)
from packages.text_to_sql_factory.models import SqlToolRequest
from packages.text_to_sql_factory.sql_tool_launcher import SqlToolLauncher
from packages.text_to_sql_factory.tools import (
    ask_database,
    check_stock,
    get_schema,
    order_status,
)

#: Les quatre tools SQL du catalogue DSI, avec le nom de leurs arguments **exposés** dans
#: l'ordre positionnel attendu. ``profile`` n'y figure pas : c'est un argument interne, lu
#: dans l'environnement du serveur et jamais dans ce que le client envoie — un paramètre
#: présent dans l'``inputSchema`` serait rempli par le LLM du client.
#:
#: Une table plutôt qu'une cascade de ``if`` : le catalogue est fermé, et l'aiguillage doit
#: se lire d'un coup d'œil pour qu'on voie qu'aucun tool n'a de chemin dérobé.
SQL_TOOLS: dict[str, tuple[Callable[..., DbStructuredAnswer], tuple[str, ...]]] = {
    "ask_database": (ask_database, ("question",)),
    "get_schema": (get_schema, ()),
    "check_stock": (check_stock, ("reference",)),
    "order_status": (order_status, ("order_id",)),
}


def _deliver(tool: str, profile: str, arguments: dict[str, Any],
             answer: DbStructuredAnswer, settings: Settings) -> dict[str, Any]:
    """Journalise l'objet entier, puis rend la vue client. **Jamais dans l'autre sens.**"""
    journal.record(tool, profile, arguments, answer, settings)
    return client_view(answer)


def handle(tool: str, arguments: dict[str, Any], profile: str,
           settings: Settings | None = None) -> dict[str, Any]:
    """Appelle un tool SQL au nom d'un profil, et rend les trois champs du contrat DSI.

    Aucune exception ne sort de cette fonction : un appel se termine toujours par une
    entrée de journal et une réponse. C'est ce qui rend la fuite de trace impossible côté
    client plutôt que seulement improbable.
    """
    return handle_request(
        SqlToolRequest(tool=tool, profile=profile, arguments=dict(arguments)),
        settings,
    )


def handle_request(request: SqlToolRequest,
                   settings: Settings | None = None,
                   launcher: SqlToolLauncher | None = None) -> dict[str, Any]:
    """Journalise et sérialise une commande SQL déjà construite par l'adaptateur."""
    settings = settings or default_settings
    launcher = launcher or SqlToolLauncher(SQL_TOOLS, settings)

    try:
        answer = launcher.launch(request)
    except Exception as error:  # noqa: BLE001 - le filet de dernier recours, et il est voulu
        # Ce qui arrive ici est un défaut, pas un cas prévu : la trace part au journal
        # entière, et le client reçoit une phrase qui ne dit rien de la pile.
        answer = build_db_structured_answer(
            "erreur_execution",
            cause=f"{type(error).__name__}: {error}",
            stack=traceback.format_exc(),
        )
    return _deliver(request.tool, request.profile, request.arguments, answer, settings)


def read_feedback(profile: str, limit: int = 50,
                  settings: Settings | None = None) -> dict[str, Any]:
    """Le journal, rendu au front — **réservé au profil qui en a le droit par la matrice**.

    C'est l'autre moitié de la journalisation : sans lecture, le journal n'est consultable
    qu'en se connectant à la machine, et les équipes métier n'en tirent rien.

    Le garde-fou passe par ``authorize()``, pas par un ``if profile == "admin"`` : la règle
    appartient à la matrice, où elle se lit en face du profil qui la porte. Tout autre profil
    reçoit un ``tool_interdit``, de la même forme que n'importe quel refus — et ce refus est
    lui-même journalisé, parce qu'une tentative de lecture du journal est précisément ce
    qu'une revue de conformité veut voir.

    Les entrées sont rendues **entières**, trace d'exception comprise. C'est assumé : ce tool
    n'est pas une commodité d'affichage, c'est la surface de débug, et l'expurger la rendrait
    inutile à ce pour quoi elle existe. Sa protection est son droit d'accès, pas son contenu.
    """
    settings = settings or default_settings
    tool = settings.journal_reader_tool
    arguments = {"limit": limit}

    if not authorize(profile, tool, settings):
        answer = build_db_structured_answer(
            "tool_interdit", etage=2,
            cause=f"le profil « {profile} » n'a pas le tool « {tool} »",
        )
        return _deliver(tool, profile, arguments, answer, settings)

    entries = journal.tail(limit, settings)
    code = "ok" if entries else "aucune_ligne"
    answer = build_db_structured_answer(code, entries=entries, n_rows=len(entries))
    return _deliver(tool, profile, arguments, answer, settings)
