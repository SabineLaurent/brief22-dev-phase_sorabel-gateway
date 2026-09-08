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
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from config import settings
from mcp_server.output_schemas import OUTPUT_SCHEMAS
from packages import journal
from packages.access import authorize
from packages.rag_machines.structured_answer import (
    MALFORMED_ARGUMENT,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.text_to_sql_factory.handler import SQL_TOOLS, handle_request
from packages.text_to_sql_factory.models import SqlToolRequest
from packages.text_to_sql_factory.sql_tool_launcher import SqlToolLauncher
from packages.text_to_sql_factory.structured_answer import (
    build_db_structured_answer,
    client_view,
)

PROFILE = os.environ.get("SORABEL_PROFILE", "support")

#: La description de ``collections``, écrite une fois pour les trois tools qui l'acceptent.
#: Elle dit « restreindre » et non « choisir » : le périmètre du profil est le plafond, cet
#: argument ne peut que descendre en dessous.
_COLLECTIONS = Annotated[
    list[str] | None,
    Field(
        default=None,
        description=(
            "Restreint la recherche à certains types de documents, parmi ceux auxquels "
            "le profil a droit. Omettre pour chercher dans tout le périmètre accessible."
        ),
    ),
]


#: Les quatre tools documentaires, nommés ici et pas importés de leur handler : le module de
#: ce handler charge l'index et l'embedder, et l'import doit rester local aux fonctions de
#: tool (``initialize`` a trente secondes). Quatre chaînes ne dérivent pas — ``list_tools``
#: les confronte au catalogue à chaque appel, et le contrôle de contrat les recompte.
_RAG_TOOL_NAMES = frozenset({"answer_question", "search_docs", "get_document",
                             "list_sources"})


def _marked(result: Any) -> Any:
    """Marque ``isError`` sur les seules enveloppes de statut ``error``, et sur rien d'autre.

    ``isError`` n'est pas une catégorie de panne : la spécification en fait un **canal de
    correction** — « the tool failed, voici de quoi réessayer » — et demande aux clients de
    le remonter au modèle. Il convient donc à ``erreur_execution``, seul des douze codes où
    l'exécution a réellement échoué : argument hors format, tool inconnu, fournisseur
    injoignable. Un refus de droits ne s'y met pas — le modèle n'a rien à corriger, et
    réessayer serait faux. C'est la différence entre un 500 et un 403, que ``isError`` seul
    ne sait pas dire : le discriminant du client reste ``status``, puis ``payload.code``.

    Le coût est nul ici, et c'est ce qui rend le choix sûr : le payload d'``erreur_execution``
    est réduit à ``{"code": …}`` par la liste blanche, donc la validation d'``outputSchema``
    que le SDK client saute sur un résultat marqué ne portait sur rien. Sur un refus, elle
    aurait porté sur l'absence de la clé de charge utile — la garantie qu'on ne veut pas
    perdre.

    Le bloc texte est **réutilisé** quand il existe : le refabriquer ferait diverger le texte
    du champ structuré, ce que tout ce contrat s'emploie à empêcher.
    """
    view = result[1] if isinstance(result, tuple) and len(result) == 2 else result
    if not isinstance(view, dict) or view.get("status") != "error":
        return result
    content = (list(result[0]) if isinstance(result, tuple)
               else [TextContent(type="text", text=json.dumps(view, ensure_ascii=False))])
    return CallToolResult(content=content, structuredContent=view, isError=True)


def _rejected(tool: str, arguments: dict[str, Any], error: Exception) -> dict[str, Any]:
    """L'enveloppe d'un appel que le SDK a refusé **avant** d'atteindre la chaîne.

    Le SDK valide les arguments contre l'``inputSchema`` avant d'appeler la fonction de
    tool, et un tool absent du catalogue n'y arrive jamais. Ces appels ne traversaient donc
    ni l'étage 2, ni le journal — et le SDK rendait à leur place la trace pydantique brute,
    qui n'est pas du JSON. Deux invariants tombaient d'un coup : *toute réponse est une
    enveloppe*, et *tout appel est journalisé* (E5).

    C'est pourquoi cette frontière existe, et pourquoi elle journalise elle-même : personne
    d'autre ne peut le faire, puisque le handler n'est pas atteint. La trace du validateur
    part en ``cause``, comme partout ailleurs — le client lit la phrase figée.

    Le domaine ne sert qu'à choisir le constructeur. Pour un tool inconnu il est
    **indécidable, et sans effet observable** : ``argument_malforme`` porte le même code, le
    même statut et la même phrase dans les deux domaines. Le repli sur le domaine SQL est
    donc un choix d'écriture, pas de comportement, et le contrôle de contrat le vérifie au
    lieu de le supposer.
    """
    cause = f"{type(error).__name__}: {error}"
    if tool in _RAG_TOOL_NAMES:
        answer = build_rag_structured_answer(
            "erreur_execution", client_key=MALFORMED_ARGUMENT, cause=cause)
        journal.record(tool, PROFILE, arguments, answer, settings)
        return rag_client_view(answer)
    db_answer = build_db_structured_answer(
        "erreur_execution", client_key=MALFORMED_ARGUMENT, cause=cause)
    journal.record(tool, PROFILE, arguments, db_answer, settings)
    return client_view(db_answer)


class SorabelMCP(FastMCP):
    """FastMCP avec un catalogue visible limité au profil du processus.

    C'est l'étage 1, et il ne prétend pas être davantage : un client qui appelle un tool
    absent de sa liste n'est pas bloqué ici, il l'est à l'étage 2, dans le handler — qui le
    refuse *et* le journalise. Filtrer la liste sans refuser l'appel serait une porte
    fermée sans serrure ; refuser l'appel sans filtrer la liste marcherait, mais offrirait
    au LLM des outils dont chaque usage échouerait.
    """

    async def list_tools(self) -> list[Any]:
        listed = [tool for tool in await super().list_tools()
                  if authorize(PROFILE, tool.name, settings)]
        for tool in listed:
            # L'``outputSchema`` est **réécrit ici**, et cet endroit n'est pas un choix de
            # commodité : le décorateur ``@mcp.tool`` n'accepte pas de schéma explicite,
            # FastMCP ne sait que le dériver de l'annotation de retour — et un type de
            # retour ne fait pas que décrire la sortie, il la filtre. Cette méthode est
            # déjà celle qui décide du catalogue publié ; c'est aussi elle qui remplit le
            # cache dont le serveur se sert pour valider la sortie. Le schéma servi et le
            # droit d'accès sont donc posés au même endroit, sur la même liste.
            tool.outputSchema = OUTPUT_SCHEMAS[tool.name]
            # La description l'est aussi, et pour la même raison : **filtrer les tools ne
            # filtre pas le contenu de leurs descriptions.** Un renvoi nomme un tool, et
            # un nom servi à qui ne l'a pas publie son existence — mesuré sur ``dev``, à
            # qui ``get_schema`` recommandait ``ask_database``, absent de son catalogue.
            # ``_served_description`` recompose depuis les tables (``_DESCRIPTIONS`` et
            # ``_REFERRALS``), donc l'appel est idempotent sur des objets que FastMCP
            # garde d'un ``tools/list`` à l'autre.
            tool.description = _served_description(tool.name, PROFILE)
        return listed

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """La frontière du serveur : **aucun appel n'en sort sans enveloppe ni sans ligne.**

        Le filet ne double pas celui des handlers, il couvre ce qu'ils ne voient pas. Un
        argument qui viole l'``inputSchema`` — patron de référence, argument requis absent,
        mauvais type — et un tool hors catalogue sont écartés par le SDK **avant** la
        fonction de tool. Mesuré : six appels sur neuf rendaient alors une trace pydantique
        non-JSON, que les trois clients du dépôt passent à ``json.loads``, et aucun n'était
        journalisé.

        Attraper ici est sans risque de masquer autre chose : les tools ne lèvent pas — les
        deux handlers ont leur propre filet et rendent ``erreur_execution``. Ce qui remonte
        jusqu'ici ne peut donc venir que de la couche de validation du SDK.
        """
        try:
            result: Any = await super().call_tool(name, arguments)
        except Exception as error:  # noqa: BLE001 - tout échec du SDK devient une enveloppe
            result = _rejected(name, arguments, error)
        return _marked(result)


#: Ce que le serveur dit au client sur la façon de le consommer — le champ
#: ``instructions`` de la réponse à ``initialize``.
#:
#: **C'est le seul canal du protocole pour ça, et ce n'est pas une primitive.** Les trois
#: primitives serveur sont les ressources, les tools et les prompts ; aucune ne porte une
#: consigne permanente. La spec réserve les prompts au *user control* — « explicit user
#: selection, such as slash commands » — et un ``PromptMessage`` n'admet que les rôles
#: ``user`` et ``assistant``, jamais ``system``. ``instructions``, lui, est décrit pour
#: exactement cet usage : « clients **may** use this information as a hint to improve an
#: LLM's understanding of available tools, such as by incorporating it into a system
#: prompt ».
#:
#: Ce ``may`` est la limite, et elle est assumée : **le serveur recommande, il ne
#: contraint pas.** Même asymétrie que ``readOnlyHint``, dans l'autre sens. Ce qui est
#: garanti quel que soit le client ne passe pas par ici — c'est l'étage 1 (le catalogue
#: filtré), l'étage 2, le périmètre, le journal, et les phrases figées qui voyagent
#: **dans l'enveloppe** : un client peut les reformuler, il ne peut pas les fabriquer.
#:
#: La première consigne est née d'un défaut mesuré le 2026-09-08 dans le client de ce
#: dépôt : son prompt système énumérait les huit tools aux cinq profils, donc le modèle
#: apprenait l'existence de ceux qu'il n'avait pas et le disait à l'utilisateur — « je
#: n'ai pas accès à l'outil de consultation de stock ». L'étage 1 était publié en creux
#: par un chemin parallèle au protocole. Un intégrateur externe peut refaire exactement
#: cette erreur en lisant le README, qui documente les huit.
_INSTRUCTIONS = (
    "Documentation technique et base métier Sorabel, en lecture seule, gouvernées par "
    "profil. Le profil est une propriété de cette connexion : il n'est jamais un "
    "argument, et tu ne peux pas le changer.\n\n"
    "Le catalogue que `tools/list` te rend est CELUI DE TON PROFIL, et il est déjà "
    "filtré. N'évoque aucun autre outil, ne suppose pas qu'il en manque un, et ne dis "
    "pas à l'utilisateur ce que tu ne peux pas faire avant d'avoir essayé ce dont tu "
    "disposes : une question qui n'entre pas dans un outil entre souvent dans un autre — "
    "la documentation porte ce que les données ne portent pas, et l'inverse.\n\n"
    "Entre deux outils DU MÊME DOMAINE dont l'un porte sur UN objet identifié et l'autre "
    "interroge librement, prends le premier : sa réponse est plus sûre. Si l'identifiant "
    "est absent ou mal formé, ou si la question en couvre plusieurs, prends le second. "
    "Cette règle ne départage PAS deux domaines : elle ne dit jamais de préférer un "
    "chiffre à un document, ni l'inverse.\n\n"
    "Chaque réponse est une enveloppe `{status, payload, message}`. Le discriminant est "
    "`payload.code`, jamais `isError`. Quand `status` n'est pas `ok`, RENDS `message` TEL "
    "QUEL : c'est une phrase figée, choisie par le serveur, et la reformuler la rend "
    "variable là où elle doit être constante. N'explique jamais la cause d'un refus — tu "
    "ne la connais pas. Un refus n'est pas une absence de données, et une absence de "
    "données n'est pas un refus. Ne réessaie pas la même question avec un autre outil "
    "pour contourner un refus.\n\n"
    "Avec les outils documentaires : cite systématiquement la référence et le titre des "
    "sources rendues. Avec les outils de base : montre la requête SQL renvoyée et les "
    "conventions métier appliquées — c'est ce qui rend le chiffre vérifiable ; n'invente "
    "jamais de requête et ne modifie jamais celle qui t'est rendue."
)

mcp = SorabelMCP(name="Sorabel Data Gateway", instructions=_INSTRUCTIONS)
SQL_TOOL_LAUNCHER = SqlToolLauncher(SQL_TOOLS, settings)


def _sql_result(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Appelle la façade journalisée du domaine SQL et rend sa vue client.

    **Rendue telle quelle, pas sérialisée.** La sérialisation appartient au SDK, qui écrit
    le bloc texte *et* ``structuredContent`` depuis le même dictionnaire — sérialiser ici
    rendrait une chaîne, et une chaîne ne peut porter aucun ``outputSchema`` utile : c'est
    exactement ce que le serveur publiait avant, un contrat qui promettait ``{"result":
    "<chaîne>"}``.
    """
    request = SqlToolRequest(tool=tool, profile=PROFILE, arguments=arguments)
    return handle_request(request, settings, SQL_TOOL_LAUNCHER)


def _documentary(**arguments: Any) -> dict[str, Any]:
    """Les arguments d'un tool documentaire, **les absents retirés**.

    Un ``None`` transmis serait journalisé comme un argument reçu, alors que le client n'a
    rien envoyé. Le handler l'écarterait de l'appel, mais pas de l'entrée de journal.
    """
    return {name: value for name, value in arguments.items() if value is not None}


def _rag_result(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Appelle la façade journalisée du domaine documentaire.

    L'import est **local à la fonction**, et il doit le rester : au niveau du module, il
    entraînerait le chargement de l'index, de l'embedder et du reranker à l'import du
    serveur — donc avant la réponse à ``initialize``, qui a trente secondes.
    """
    from packages.rag_machines.handler import handle

    return handle(tool, arguments, PROFILE, settings)


# --- Les descriptions servies ---------------------------------------------------------
#
# Les descriptions sont le **seul** aiguillage : aucun code ne choisit le tool, c'est le
# modèle qui lit ces phrases et tranche. Elles disent donc ce que le tool fait *et* vers
# quoi renvoyer quand ce n'est pas lui — un tool qui ne dit pas ce qu'il n'est pas se fait
# appeler à tort.
#
# D'où la coupure en deux tables, et ce n'est pas un rangement : un renvoi nomme un tool,
# et **un nom de tool servi à qui ne l'a pas publie son existence**. C'était mesuré — la
# description de ``get_schema`` renvoyait vers ``ask_database``, que ``dev`` n'a pas :
# le modèle lisait le renvoi, cherchait le tool, ne l'avait pas, et renonçait. C'est le
# défaut du prompt système du 2026-09-08 à l'identique, mais dans le protocole, et
# ``list_tools`` ne l'attrapait pas : il filtre les **tools**, jamais le **contenu de
# leurs descriptions**.
#
# * ``_DESCRIPTIONS`` — le corps, servi à tout profil qui a le tool, en **cinq rubriques**
#   fixes : à quoi ça sert, ce que ça prend, ce que ça rend, quand l'utiliser, quand ne pas
#   l'utiliser. Les quatre premières étaient tenues implicitement ; la cinquième ne l'était
#   nulle part, et c'est celle qui manquait le plus — un tool qui ne dit pas ce qu'il n'est
#   pas se fait appeler à tort, et ``get_document`` recevait des références produit faute
#   de l'exclure. **Aucun nom de tool n'y paraît**, et c'est ce qui rend la garantie
#   structurelle plutôt que conventionnelle : un renvoi ne peut pas s'y glisser sans passer
#   par la table d'à côté ;
# * ``_REFERRALS`` — les renvois, chacun rattaché à sa **cible**, donc filtrables par la
#   matrice comme les tools eux-mêmes.
#
# Les ponts traversent les deux domaines, dans les deux sens : une référence produit a une
# fiche *et* un stock, et rien ne le disait au modèle. Ils sont conditionnels au même
# titre — un pont vers un domaine fermé rejouerait exactement le défaut qu'on referme.

#: Les cinq rubriques de toute description, dans cet ordre. Ce n'est pas une mise en forme :
#: c'est ce qu'un modèle doit savoir pour ne pas se tromper de tool, et les quatre premières
#: rubriques étaient tenues implicitement — la cinquième ne l'était nulle part.
#:
#: ``Ne pas utiliser quand`` vient en **dernier** parce que c'est là que les renvois se
#: collent : un « ne pas utiliser » sans destination laisse le modèle sans issue, et c'est
#: exactement ce qui le faisait renoncer.
_SECTIONS = ("Objet :", "Entrée :", "Sortie :", "Utiliser quand :", "Ne pas utiliser quand :")

_DESCRIPTIONS: dict[str, str] = {
    "answer_question": (
        "Objet : répondre à une question sur la documentation interne Sorabel, en citant "
        "les documents utilisés.\n"
        "Entrée : `question`, en langage naturel. `collections` restreint aux types de "
        "documents voulus, et peut être omis.\n"
        "Sortie : une réponse rédigée et la liste de ses sources (référence, titre) ; ou "
        "une non-réponse quand le corpus ne porte pas de quoi répondre.\n"
        "Utiliser quand : la question porte sur une procédure, une consigne interne, une "
        "notice, ou une caractéristique de produit.\n"
        "Ne pas utiliser quand : la question attend un chiffre ou un état tenu par la base "
        "— la documentation décrit, elle ne compte pas."
    ),
    "search_docs": (
        "Objet : rendre les extraits documentaires les plus pertinents pour une recherche, "
        "sans rédiger de réponse.\n"
        "Entrée : `query`, mots-clés ou question. `collections` restreint aux types de "
        "documents voulus, et peut être omis.\n"
        "Sortie : les extraits classés par pertinence, avec leurs métadonnées — identifiant "
        "d'édition, titre, type, thème.\n"
        "Utiliser quand : il faut lire le texte source lui-même, comparer plusieurs "
        "passages, ou obtenir l'identifiant d'une édition.\n"
        "Ne pas utiliser quand : une réponse formulée est attendue, plutôt que des extraits."
    ),
    "get_document": (
        "Objet : rendre le texte intégral d'une édition documentaire déjà identifiée.\n"
        "Entrée : `doc_id`, un identifiant d'édition de la forme "
        "`notices/notice-REF-1589-v1.0`. `version` peut être omis.\n"
        "Sortie : le texte complet et les métadonnées de l'édition ; ou une non-réponse "
        "quand aucune édition ne porte cet identifiant.\n"
        "Utiliser quand : l'identifiant d'édition est déjà connu, parce qu'un autre tool "
        "documentaire vient de le rendre.\n"
        "Ne pas utiliser quand : l'entrée est une question en langage naturel, ou une "
        "référence produit de la forme REF-NNNN — une référence produit n'est pas un "
        "identifiant d'édition, et ce tool ne la trouvera pas."
    ),
    "list_sources": (
        "Objet : inventorier les documents accessibles, sans déclencher de recherche.\n"
        "Entrée : `collections` restreint aux types de documents voulus, et peut être "
        "omis.\n"
        "Sortie : la liste des documents — identifiant, titre, type — et leur nombre "
        "total.\n"
        "Utiliser quand : il faut savoir ce que le corpus couvre avant de poser une "
        "question, ou récupérer des identifiants d'éditions.\n"
        "Ne pas utiliser quand : la question porte sur le contenu des documents et non sur "
        "leur existence."
    ),
    "ask_database": (
        "Objet : traduire une question chiffrée en une lecture SQL de la base commerciale, "
        "et l'exécuter.\n"
        "Entrée : `question`, en langage naturel.\n"
        "Sortie : les colonnes et les lignes du résultat, la requête SQL exécutée et les "
        "conventions métier appliquées ; ou un refus quand la question sort du périmètre "
        "du profil.\n"
        "Utiliser quand : la question demande un décompte, une somme, une moyenne, un "
        "classement, un filtre ou une période sur les produits, stocks, commandes, clients "
        "ou ventes.\n"
        "Ne pas utiliser quand : la réponse attendue est une procédure ou une "
        "caractéristique décrite dans un document."
    ),
    "get_schema": (
        "Objet : rendre lisible la forme de la base — tables, colonnes, énumérations, "
        "conventions métier.\n"
        "Entrée : aucun argument.\n"
        "Sortie : le schéma des seules tables et colonnes du périmètre, et la plage de "
        "dates couverte.\n"
        "Utiliser quand : il faut savoir ce que la base contient avant de formuler une "
        "question, ou écrire du code contre elle.\n"
        "Ne pas utiliser quand : la question attend une valeur, un décompte ou des lignes "
        "— ce tool ne lit aucune donnée, et le schéma seul ne répond à aucune question "
        "chiffrée."
    ),
    "check_stock": (
        "Objet : rendre le stock d'une référence produit, entrepôt par entrepôt.\n"
        "Entrée : `reference`, de la forme REF-NNNN exactement.\n"
        "Sortie : une ligne par entrepôt — quantité et seuil de réapprovisionnement ; ou "
        "une non-réponse quand la référence n'existe pas.\n"
        "Utiliser quand : la question porte sur la disponibilité ou la quantité d'une "
        "référence connue.\n"
        "Ne pas utiliser quand : l'entrée est un nom de produit et non une référence, ou "
        "la question porte sur ce qu'est le produit — ce tool ne rend que des quantités, "
        "jamais une caractéristique."
    ),
    "order_status": (
        "Objet : rendre l'en-tête d'une commande.\n"
        "Entrée : `order_id`, de la forme CMD-AAAA-NNNN exactement.\n"
        "Sortie : le client, la date, le statut et le montant HT de la commande ; ou une "
        "non-réponse quand l'identifiant n'existe pas.\n"
        "Utiliser quand : la question porte sur une commande unique et identifiée.\n"
        "Ne pas utiliser quand : plusieurs commandes sont visées, ou un agrégat est "
        "demandé."
    ),
}

#: Les renvois, par tool source : ``(tool cible, phrase qui le nomme)``. La phrase n'est
#: servie que si le profil a la cible — sinon elle disparaît, et le corps suffit.
#:
#: Un renvoi par phrase, jamais deux cibles dans la même : une phrase qui en nommerait deux
#: deviendrait fausse le jour où l'une tombe (« celui que rend search_docs ou list_sources »
#: sans ``list_sources``). Les quatre tools documentaires vont toujours ensemble dans la
#: matrice d'aujourd'hui ; la forme ne parie pas là-dessus.
_REFERRALS: dict[str, tuple[tuple[str, str], ...]] = {
    "answer_question": (
        ("search_docs",
         "Pour les extraits bruts sans rédaction, utiliser search_docs."),
        ("ask_database",
         "Pour l'état d'un produit et non sa description — stock, chiffres, commandes —, "
         "utiliser ask_database."),
        ("check_stock",
         "Un seul cas demande DEUX appels, et c'est le seul : une référence donnée SEULE, "
         "sans question — « REF-5313 ». Appeler alors AUSSI check_stock, et rendre la fiche "
         "ET le stock. Hors de ce cas, un seul tool suffit."),
    ),
    "search_docs": (
        ("answer_question",
         "Pour une réponse rédigée et sourcée, utiliser answer_question."),
        ("get_document",
         "Pour le texte intégral d'une édition identifiée, utiliser get_document."),
    ),
    "get_document": (
        ("search_docs", "L'identifiant attendu est celui que rend search_docs."),
        ("list_sources", "list_sources en donne l'inventaire."),
        ("answer_question",
         "Pour une question, ou pour une référence produit REF-NNNN, "
         "utiliser answer_question."),
    ),
    "list_sources": (
        ("search_docs", "Pour chercher, utiliser search_docs."),
        ("answer_question", "Pour une réponse rédigée, utiliser answer_question."),
    ),
    "ask_database": (
        ("check_stock", "Pour le stock d'une référence, utiliser check_stock."),
        ("order_status", "Pour une commande précise, utiliser order_status."),
    ),
    "get_schema": (
        ("ask_database", "Pour obtenir un résultat, utiliser ask_database."),
    ),
    "check_stock": (
        ("answer_question",
         "Pour les caractéristiques d'une référence — fiche technique, notice, "
         "procédure —, utiliser answer_question. Un seul cas demande DEUX appels, et c'est "
         "le seul : une référence donnée SEULE, sans question — « REF-5313 ». Appeler alors "
         "AUSSI answer_question, et rendre la fiche ET le stock. Hors de ce cas, un seul "
         "tool suffit."),
        ("ask_database", "Pour une autre question chiffrée, utiliser ask_database."),
    ),
    "order_status": (
        ("ask_database", "Pour plusieurs commandes ou un agrégat, utiliser ask_database."),
    ),
}


def _served_description(name: str, profile: str) -> str:
    """Le corps du tool, suivi des seuls renvois que ce profil peut suivre.

    Recomposée **depuis les tables**, jamais depuis la description déjà posée sur l'objet :
    ``list_tools`` mute les objets que FastMCP conserve d'un appel à l'autre, et concaténer
    sur l'état muté empilerait les renvois à chaque ``tools/list``.
    """
    referrals = [phrase for target, phrase in _REFERRALS.get(name, ())
                 if authorize(profile, target, settings)]
    return " ".join([_DESCRIPTIONS[name], *referrals])


#: Les huit tools lisent, aucun n'écrit — la gateway est en lecture seule de bout en bout.
_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


# --- Domaine documentaire -------------------------------------------------------------
#
# ``collections`` est exposé sur les trois tools qui le portent, et **sans ``enum``** — les
# deux moitiés de l'arbitrage du 2026-09-07 :
#
# * exposé, parce que l'étage 3 promet de *réduire* un périmètre à la demande. Le retirer
#   rendrait morte la branche « collection fermée au profil » de ``_resolve_perimeter``,
#   qui est contrôlée ;
# * sans ``enum``, parce qu'une énumération statique des quatre ``doc_type`` publierait
#   l'existence de ``note_interne`` à un client ``dev`` qui n'y a pas droit. Un tableau de
#   chaînes libres réutilise l'arbitrage déjà écrit pour ``get_document`` : un nom inventé
#   et un nom fermé rendent le même ``perimetre_interdit``, et ne se distinguent pas.


@mcp.tool(
    title="Réponse documentaire sourcée",
    description=_DESCRIPTIONS["answer_question"],
    annotations=_READ_ONLY,
)
def answer_question(question: str, collections: _COLLECTIONS = None) -> dict[str, Any]:
    return _rag_result("answer_question", _documentary(question=question,
                                                       collections=collections))


@mcp.tool(
    title="Recherche d'extraits documentaires",
    description=_DESCRIPTIONS["search_docs"],
    annotations=_READ_ONLY,
)
def search_docs(query: str, collections: _COLLECTIONS = None) -> dict[str, Any]:
    return _rag_result("search_docs", _documentary(query=query, collections=collections))


@mcp.tool(
    title="Texte intégral d'un document",
    description=_DESCRIPTIONS["get_document"],
    annotations=_READ_ONLY,
)
def get_document(doc_id: str, version: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"doc_id": doc_id}
    if version is not None:
        arguments["version"] = version
    return _rag_result("get_document", arguments)


@mcp.tool(
    title="Inventaire du corpus documentaire",
    description=_DESCRIPTIONS["list_sources"],
    annotations=_READ_ONLY,
)
def list_sources(collections: _COLLECTIONS = None) -> dict[str, Any]:
    return _rag_result("list_sources", _documentary(collections=collections))


# --- Domaine métier -------------------------------------------------------------------


@mcp.tool(
    title="Interrogation de la base métier",
    description=_DESCRIPTIONS["ask_database"],
    annotations=_READ_ONLY,
)
def ask_database(question: str) -> dict[str, Any]:
    return _sql_result("ask_database", {"question": question})


@mcp.tool(
    title="Schéma SQL autorisé",
    description=_DESCRIPTIONS["get_schema"],
    annotations=_READ_ONLY,
)
def get_schema() -> dict[str, Any]:
    return _sql_result("get_schema", {})


@mcp.tool(
    title="Stock d'une référence",
    description=_DESCRIPTIONS["check_stock"],
    annotations=_READ_ONLY,
)
def check_stock(reference: Annotated[str, Field(pattern=r"^REF-\d{4}$")]) -> dict[str, Any]:
    return _sql_result("check_stock", {"reference": reference})


@mcp.tool(
    title="Statut d'une commande",
    description=_DESCRIPTIONS["order_status"],
    annotations=_READ_ONLY,
)
def order_status(order_id: Annotated[str, Field(pattern=r"^CMD-\d{4}-\d{4}$")]) -> dict[str, Any]:
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
