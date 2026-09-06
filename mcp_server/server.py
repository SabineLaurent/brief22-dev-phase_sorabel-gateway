"""Serveur MCP stdio de la Sorabel Data Gateway : les huit tools du catalogue.

**Un seul serveur, une seule barrière, un profil par processus** — c'est la forme arrêtée
par le contrat d'intégration (``docs/cadrage_dsi.md`` §Contrat d'intégration) et par
``01-flux-complet.md``, qui représente le serveur comme *une barrière*, pas comme une étape
parmi d'autres.

Le profil est lu dans ``SORABEL_PROFILE``, **une fois au chargement du module**. Ce n'est
pas une commodité : c'est ce qui le rend inaccessible au client. Un profil passé en
argument de tool serait dans l'``inputSchema``, donc rempli par le LLM ; un profil passé en
en-tête serait déclaré par l'appelant. Ici, il est dans l'environnement du processus, et le
client qui parle à ce serveur n'a aucun moyen d'en changer.

Ce module ne décide rien. Il enregistre les tools, filtre le catalogue, et passe la main
aux deux handlers — ``text_to_sql_factory.handler`` et ``rag_machines.handler`` — qui
portent chacun leur étage 2, leur journalisation et leur vue client. La seule chose que ce
fichier ajoute à la chaîne, c'est **l'étage 1** : le catalogue que le client voit.

Trois étages, et ils ne font pas le même travail (``03-catalogue-tools.md`` §3) :

1. ``tools/list`` filtré — de l'**ergonomie**. Le LLM ne voit pas ce qu'il n'a pas le droit
   d'appeler, donc il ne l'essaie pas. Ce n'est pas une sécurité : un client peut appeler un
   tool qu'il n'a pas listé ;
2. l'étage 2, dans les handlers — le droit d'appeler le tool. C'est **là** que le refus se
   prononce, et il est journalisé ;
3. l'étage 3, dans les tools — le périmètre : colonnes fermées côté SQL, collections et
   thèmes côté documentaire.

**Le chargement est paresseux, et c'est une contrainte de protocole**, pas une optimisation :
la suite d'acceptance borne ``initialize`` à trente secondes. Les modules du RAG sont donc
importés à l'intérieur des fonctions de tool — importer ``rag_machines.handler`` au niveau
du module ferait charger l'embedder et le reranker avant la première poignée de main.
"""

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
    """FastMCP avec un catalogue visible limité au profil du processus.

    C'est l'étage 1, et il ne prétend pas être davantage : un client qui appelle un tool
    absent de sa liste n'est pas bloqué ici, il l'est à l'étage 2, dans le handler — qui le
    refuse *et* le journalise. Filtrer la liste sans refuser l'appel serait une porte
    fermée sans serrure ; refuser l'appel sans filtrer la liste marcherait, mais offrirait
    au LLM des outils dont chaque usage échouerait.
    """

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        return [tool for tool in tools if authorize(PROFILE, tool.name, settings)]


mcp = SorabelMCP(
    name="Sorabel Data Gateway",
    instructions=(
        "Documentation technique et base métier Sorabel, en lecture seule, gouvernées "
        "par profil."
    ),
)
SQL_TOOL_LAUNCHER = SqlToolLauncher(SQL_TOOLS, settings)


def _sql_result(tool: str, arguments: dict[str, Any]) -> str:
    """Appelle la façade journalisée du domaine SQL et sérialise sa vue client."""
    request = SqlToolRequest(tool=tool, profile=PROFILE, arguments=arguments)
    return json.dumps(
        handle_request(request, settings, SQL_TOOL_LAUNCHER),
        ensure_ascii=False,
    )


def _rag_result(tool: str, arguments: dict[str, Any]) -> str:
    """Appelle la façade journalisée du domaine documentaire.

    L'import est **local à la fonction**, et il doit le rester : au niveau du module, il
    entraînerait le chargement de l'index, de l'embedder et du reranker à l'import du
    serveur — donc avant la réponse à ``initialize``, qui a trente secondes.
    """
    from packages.rag_machines.handler import handle

    return json.dumps(handle(tool, arguments, PROFILE, settings), ensure_ascii=False)


#: Les huit tools lisent, aucun n'écrit — la gateway est en lecture seule de bout en bout.
_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


# --- Domaine documentaire -------------------------------------------------------------
#
# Les descriptions sont le **seul** aiguillage : aucun code ne choisit le tool, c'est le
# modèle qui lit ces phrases et tranche. Elles disent donc ce que le tool fait *et* vers
# quoi renvoyer quand ce n'est pas lui — un tool qui ne dit pas ce qu'il n'est pas se fait
# appeler à tort.


@mcp.tool(
    title="Réponse documentaire sourcée",
    description=(
        "Documentation interne Sorabel. Rédige une réponse à une question et cite les "
        "documents utilisés. À utiliser pour toute question de procédure, de "
        "caractéristique produit ou de consigne interne. Pour obtenir les extraits bruts "
        "sans rédaction, utiliser search_docs."
    ),
    annotations=_READ_ONLY,
)
def answer_question(question: str) -> str:
    return _rag_result("answer_question", {"question": question})


@mcp.tool(
    title="Recherche d'extraits documentaires",
    description=(
        "Documentation interne Sorabel. Rend les extraits les plus pertinents pour une "
        "recherche, classés, avec leurs métadonnées — sans rédiger de réponse. Pour une "
        "réponse rédigée et sourcée, utiliser answer_question ; pour le texte intégral "
        "d'un document identifié, utiliser get_document."
    ),
    annotations=_READ_ONLY,
)
def search_docs(query: str) -> str:
    return _rag_result("search_docs", {"query": query})


@mcp.tool(
    title="Texte intégral d'un document",
    description=(
        "Documentation interne Sorabel. Rend le texte complet et les métadonnées d'une "
        "édition désignée par son identifiant, tel que rendu par search_docs ou "
        "list_sources. N'accepte pas une question en langage naturel."
    ),
    annotations=_READ_ONLY,
)
def get_document(doc_id: str, version: str | None = None) -> str:
    arguments: dict[str, Any] = {"doc_id": doc_id}
    if version is not None:
        arguments["version"] = version
    return _rag_result("get_document", arguments)


@mcp.tool(
    title="Inventaire du corpus documentaire",
    description=(
        "Documentation interne Sorabel. Rend la liste des documents accessibles, sans "
        "déclencher de recherche : utile pour savoir ce que le corpus couvre avant de "
        "poser une question. Pour chercher, utiliser search_docs ou answer_question."
    ),
    annotations=_READ_ONLY,
)
def list_sources() -> str:
    return _rag_result("list_sources", {})


# --- Domaine métier -------------------------------------------------------------------


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
    return _sql_result("ask_database", {"question": question})


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
    return _sql_result("get_schema", {})


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
    return _sql_result("check_stock", {"reference": reference})


@mcp.tool(
    title="Statut d'une commande",
    description=(
        "Base de données commerciale. Rend l'en-tête d'une commande CMD-AAAA-NNNN. "
        "Pour plusieurs commandes ou un agrégat, utiliser ask_database."
    ),
    annotations=_READ_ONLY,
)
def order_status(order_id: Annotated[str, Field(pattern=r"^CMD-\d{4}-\d{4}$")]) -> str:
    return _sql_result("order_status", {"order_id": order_id})


def main() -> None:
    """Point d'entrée du serveur, en stdio.

    Le transport Streamable HTTP est conçu (``note-transport.md``) mais hors périmètre :
    il suppose une identité de client — un annuaire, des secrets, une résolution du profil
    *par appel* — là où la démonstration a un processus par profil.
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
