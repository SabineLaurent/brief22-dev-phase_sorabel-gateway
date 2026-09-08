"""Façade d'exécution gouvernée des tools SQL."""

from __future__ import annotations

from collections.abc import Callable

from config import Settings
from packages.access import authorize
from packages.text_to_sql_factory.models import SqlToolRequest
from packages.text_to_sql_factory.structured_answer import (
    MALFORMED_ARGUMENT,
    DbStructuredAnswer,
    build_db_structured_answer,
)


ToolFunction = Callable[..., DbStructuredAnswer]


class SqlToolLauncher:
    """Vérifie puis lance un tool SQL sans connaître le protocole MCP."""

    def __init__(self, tools: dict[str, tuple[ToolFunction, tuple[str, ...]]],
                 settings: Settings) -> None:
        self._tools = tools
        self._settings = settings

    def execute(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Vérifie le tool, le profil et les arguments avant l'appel métier."""
        entry = self._tools.get(request.tool)
        if entry is None:
            return build_db_structured_answer(
                "erreur_execution",
                client_key=MALFORMED_ARGUMENT,
                cause=f"tool inconnu : « {request.tool} »",
            )

        if not authorize(request.profile, request.tool, self._settings):
            return build_db_structured_answer(
                "tool_interdit",
                etage=2,
                cause=(f"le profil « {request.profile} » n'a pas le tool "
                       f"« {request.tool} »"),
            )

        function, names = entry
        missing = [name for name in names if request.arguments.get(name) is None]
        if missing:
            return build_db_structured_answer(
                "erreur_execution",
                client_key=MALFORMED_ARGUMENT,
                cause=(f"argument manquant pour « {request.tool} » : "
                       f"{', '.join(missing)}"),
            )

        return function(
            *(request.arguments[name] for name in names),
            request.profile,
            settings=self._settings,
        )

    def launch(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Dispatch vers la méthode nommée correspondant au tool demandé."""
        methods = {
            "ask_database": self.ask_database,
            "get_schema": self.get_schema,
            "check_stock": self.check_stock,
            "order_status": self.order_status,
        }
        method = methods.get(request.tool)
        return method(request) if method is not None else self.execute(request)

    def ask_database(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Lance ``ask_database`` après vérification de la commande."""
        return self._execute_named(request, "ask_database")

    def get_schema(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Lance ``get_schema`` après vérification de la commande."""
        return self._execute_named(request, "get_schema")

    def check_stock(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Lance ``check_stock`` après vérification de la commande."""
        return self._execute_named(request, "check_stock")

    def order_status(self, request: SqlToolRequest) -> DbStructuredAnswer:
        """Lance ``order_status`` après vérification de la commande."""
        return self._execute_named(request, "order_status")

    def _execute_named(self, request: SqlToolRequest,
                       expected_tool: str) -> DbStructuredAnswer:
        if request.tool != expected_tool:
            return build_db_structured_answer(
                "erreur_execution",
                client_key=MALFORMED_ARGUMENT,
                cause=(f"commande « {request.tool} » reçue par "
                       f"« {expected_tool} »"),
            )
        return self.execute(request)
