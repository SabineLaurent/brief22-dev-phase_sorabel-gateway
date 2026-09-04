"""Serveur MCP stdio pour le premier incrément SQL de la gateway."""

from __future__ import annotations

import json
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from config import settings
from packages.access import authorize
from packages.text_to_sql_factory.handler import SQL_TOOLS, handle_request
from packages.text_to_sql_factory.models import SqlToolRequest
from packages.text_to_sql_factory.sql_tool_launcher import SqlToolLauncher


PROFILE = os.environ.get("SORABEL_PROFILE", "support")


class SorabelMCP(FastMCP):
    """FastMCP avec un catalogue visible limité au profil du processus."""

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        return [tool for tool in tools if authorize(PROFILE, tool.name, settings)]


mcp = SorabelMCP(
    name="Sorabel Data Gateway",
    instructions="Gateway SQL en lecture seule, gouvernée par profil.",
)
SQL_TOOL_LAUNCHER = SqlToolLauncher(SQL_TOOLS, settings)


def _json_result(tool: str, arguments: dict[str, Any]) -> str:
    """Appelle la façade journalisée et sérialise uniquement sa vue client."""
    request = SqlToolRequest(tool=tool, profile=PROFILE, arguments=arguments)
    return json.dumps(
        handle_request(request, settings, SQL_TOOL_LAUNCHER),
        ensure_ascii=False,
    )


_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


@mcp.tool(
    title="Interrogation de la base métier",
    description=(
        "Base de données commerciale. Traduit une question chiffrée en lecture SQL "
        "et rend le résultat avec la requête exécutée. Pour le stock d'une référence, "
        "utiliser check_stock ; pour une commande précise, utiliser order_status."
    ),
    annotations=_READ_ONLY,
)
def ask_database(question: str) -> str:
    return _json_result("ask_database", {"question": question})


@mcp.tool(
    title="Schéma SQL autorisé",
    description=(
        "Base de données commerciale. Rend le schéma et le périmètre lisibles, sans "
        "exécuter de question ni lire de données. Pour obtenir un résultat, utiliser "
        "ask_database."
    ),
    annotations=_READ_ONLY,
)
def get_schema() -> str:
    return _json_result("get_schema", {})


@mcp.tool(
    title="Stock d'une référence",
    description=(
        "Base de données commerciale. Rend le stock d'une référence REF-NNNN, "
        "entrepôt par entrepôt, avec le seuil de réapprovisionnement. N'accepte pas "
        "un nom de produit ; pour une autre question chiffrée, utiliser ask_database."
    ),
    annotations=_READ_ONLY,
)
def check_stock(reference: Annotated[str, Field(pattern=r"^REF-\d{4}$")]) -> str:
    return _json_result("check_stock", {"reference": reference})


@mcp.tool(
    title="Statut d'une commande",
    description=(
        "Base de données commerciale. Rend l'en-tête d'une commande CMD-AAAA-NNNN. "
        "Pour plusieurs commandes ou un agrégat, utiliser ask_database."
    ),
    annotations=_READ_ONLY,
)
def order_status(order_id: Annotated[str, Field(pattern=r"^CMD-\d{4}-\d{4}$")]) -> str:
    return _json_result("order_status", {"order_id": order_id})


if __name__ == "__main__":
    mcp.run(transport="stdio")
