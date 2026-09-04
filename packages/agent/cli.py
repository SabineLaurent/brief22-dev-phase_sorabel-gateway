"""Agent conversationnel LangChain, minimal, pour rejouer à la main les questions
d'``eval/questions_rag.jsonl`` et d'``eval/questions_sql.jsonl``.

Cinq outils : ``search_docs`` pour la **documentation** (``rag_machines.retrieval.search``),
et les quatre du chantier Text-to-SQL (``text_to_sql_factory.tools``) — ``ask_to_db``,
``check_stock_by_ref``, ``order_status_by_id``, ``get_db_schema``.

**C'est le LLM qui aiguille**, comme le fera le serveur MCP : les tools y sont
*model-controlled*, et le seul levier du serveur est la rédaction des descriptions. Aucun
aiguillage n'est codé ici — une liste de mots-clés ne pourrait pas être complète, et le
travail de départage des descriptions est déjà fait dans le catalogue de conception.

Les noms exposés diffèrent de ceux du catalogue MCP (``ask_database``, ``check_stock``,
``order_status``, ``get_schema``) : ces tools les **appellent**, ils ne les *sont* pas — le
catalogue n'existera qu'au chantier 3. La matrice, elle, est interrogée sous les noms du
catalogue : c'est elle qui nomme la gouvernance. Pas de mémoire : chaque question part d'un historique
vide, l'agent n'a que la question posée et ce que l'outil lui rend.

**Les quatre tools de base passent par ``handler.handle()``**, le point de passage unique
du chantier 3 : c'est lui qui applique l'étage 2, journalise l'appel entier et ne rend que
la vue client purgée. Ces tools ne voient donc **jamais** la cause technique d'un refus —
ni la colonne fermée, ni le message du moteur, ni la trace d'exception. Ce n'est pas une
précaution de politesse : ce qui arrive ici est recopié dans le contexte d'un LLM, qui le
reformule ensuite librement.

**Et sur un refus, le LLM n'a pas le dernier mot.** Chaque appel dépose sa vue client dans
le carnet de l'appel en cours (:func:`call_record`) ; ``api.py`` y lit la phrase figée et la
rend **telle quelle**, sans repasser par le modèle. Sinon le déterminisme se perdrait au
dernier mètre : le refus ne varie pas, mais sa reformulation, si.

**Banc d'essai, pas la cible.** Le profil est ici un argument, donc *déclaré par
l'appelant* — la conception veut l'inverse : ``SORABEL_PROFILE`` lu au lancement du serveur
MCP, jamais reçu du client, précisément pour que le LLM du client ne puisse pas l'écrire.
Ce raccourci n'existe que pour rendre la matrice observable depuis l'interface de test ; il
disparaît avec le serveur MCP (chantier 3).

Usage :
    uv run python -m packages.agent.cli
    uv run python -m packages.agent.cli --strategy dense --profile commercial
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from pydantic import SecretStr

from config import llm_base_url, settings
from packages.access import authorize
from packages.rag_machines.access_rag import search_for_profile
from packages.rag_machines.retrieval.search import Strategy, citation
from packages.text_to_sql_factory.handler import handle

_SYSTEM_PROMPT = (
    "Tu réponds aux questions sur Sorabel en t'appuyant uniquement sur tes outils — jamais "
    "sur tes propres connaissances.\n\n"
    "Choisis l'outil par le DOMAINE de la question, pas par sa formulation. La forme de la "
    "question est le meilleur indice : un identifiant bien formé oriente vers les données, "
    "un « comment » ou un « pourquoi » vers la documentation.\n"
    "  - search_docs : documentation produit et procédures — caractéristique technique, "
    "procédure SAV, mode opératoire ;\n"
    "  - check_stock_by_ref : le stock d'UNE référence REF-NNNN, entrepôt par entrepôt ;\n"
    "  - order_status_by_id : l'en-tête d'UNE commande CMD-AAAA-NNNN ;\n"
    "  - get_db_schema : ce que la base contient et ce qui est interrogeable — la forme, "
    "jamais les données ;\n"
    "  - ask_to_db : toute autre question chiffrée sur la base — comptage, montant, "
    "classement, plusieurs produits ou plusieurs commandes.\n\n"
    "Entre un outil figé et ask_to_db, prends le figé quand la question porte sur UN objet "
    "identifié : sa réponse est plus sûre. Si l'identifiant est absent ou mal formé, ou si "
    "la question en couvre plusieurs, prends ask_to_db.\n\n"
    "Avec search_docs : cite systématiquement la référence et le titre des sources "
    "utilisées. Si l'outil signale que le corpus ne couvre pas la question, dis-le "
    "clairement au lieu d'inventer une réponse.\n\n"
    "Avec les outils de base : montre TOUJOURS la requête SQL renvoyée avec le résultat, "
    "ainsi que les conventions métier appliquées — c'est ce qui rend le chiffre vérifiable. "
    "N'invente jamais de requête toi-même et ne modifie jamais celle qui t'est rendue. "
    "Quand un outil refuse, rapporte son message TEL QUEL, sans le reformuler et sans "
    "chercher à en expliquer la cause — tu ne la connais pas. Un refus n'est pas une "
    "absence de données, et une absence de données n'est pas un refus. Ne réessaie pas "
    "la même question avec un autre outil pour contourner un refus."
)

#: Au-delà, on ne déverse pas le résultat dans le contexte de l'agent : il en dirait autant
#: avec dix lignes, et le reste ne ferait que coûter des jetons.
_MAX_DISPLAYED_ROWS = 30


#: Le carnet de l'appel en cours. Chaque tool de base y dépose la vue client de sa réponse ;
#: ``api.py`` y relit la phrase figée avant de rendre quoi que ce soit à l'écran.
#:
#: Une ``ContextVar`` et non un attribut de l'agent : l'agent est mis en cache et partagé
#: entre les requêtes, alors que le carnet appartient à **un** appel. Le contexte est recopié
#: dans le fil d'exécution où FastAPI joue une route synchrone, donc le carnet suit l'appel
#: sans suivre l'agent.
_CURRENT_CALL: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "sorabel_current_call", default=None
)


@contextmanager
def call_record() -> Iterator[list[dict[str, Any]]]:
    """Ouvre un carnet pour la durée d'un appel, et le referme quoi qu'il arrive."""
    book: list[dict[str, Any]] = []
    token = _CURRENT_CALL.set(book)
    try:
        yield book
    finally:
        _CURRENT_CALL.reset(token)


def frozen_text(book: list[dict[str, Any]]) -> str | None:
    """La phrase à afficher **telle quelle**, ou ``None`` s'il faut laisser le LLM rédiger.

    C'est le point de décision unique : *le modèle n'entre en jeu que quand il y a un
    résultat à exprimer.* Partout ailleurs — refus, panne, clarification — la phrase est
    déjà écrite et part à l'écran sans passer par lui. Elle ne peut donc pas varier d'un
    appel à l'autre.

    Le **premier** verdict non-``ok`` gagne, et il gagne sur une réponse par ailleurs
    réussie : afficher le texte rédigé masquerait un refus survenu en chemin.
    """
    for view in book:
        if view["status"] == "ok":
            continue
        text = view["message"]
        axes = view["payload"].get("axes")
        if axes:
            text += "\n" + "\n".join(f"  - {axis}" for axis in axes)
        return text
    return None


def _denied_docs(profile: str) -> str | None:
    """Étage 2 du **seul** tool documentaire de ce banc d'essai, ou ``None``.

    Le SQL n'en a plus besoin — ``handle()`` l'applique. Le RAG, lui, n'a pas encore son
    point de passage : il garde donc ce raccourci, texte brut compris, jusqu'à ce que la
    couche du chantier 3 lui soit étendue. C'est un reste assumé, pas un choix.
    """
    if authorize(profile, "search_docs"):
        return None
    return "Cette information n'est pas accessible avec votre profil."


def _serve(tool: str, arguments: dict[str, Any], profile: str) -> str:
    """Appelle un tool du catalogue par le point de passage unique, et note son verdict."""
    view = handle(tool, arguments, profile)
    book = _CURRENT_CALL.get()
    if book is not None:
        book.append(view)
    return _format_database_answer(view, tool)


def _format_database_answer(view: dict[str, Any], tool: str) -> str:
    """Met la vue client d'un tool SQL sous une forme que le modèle peut restituer.

    La requête et les conventions sont rendues au même titre que les lignes : sans elles,
    le chiffre n'est pas vérifiable, et c'est ce que la transparence E3 demande. Le nom du
    tool est rendu aussi : l'aiguillage étant interne, sans lui l'utilisateur ne saurait pas
    si son chiffre vient d'une requête figée ou d'une requête générée.

    Sur un refus, il n'y a **rien** à mettre en forme que la phrase figée : le payload est
    réduit à son code en amont, et c'est ce qui empêche le modèle de reformuler une cause
    qu'il n'a pas.
    """
    payload = view["payload"]
    lines = [f"outil : {tool}", f"code : {payload['code']}"]
    if view["message"]:
        lines.append(f"message : {view['message']}")
    if payload.get("axes"):
        lines.append("axes proposés :\n" + "\n".join(f"  - {axis}" for axis in payload["axes"]))
    if payload.get("sql"):
        lines.append(f"requête exécutée :\n{payload['sql']}")
    rows = payload.get("rows")
    if rows:
        header = " | ".join(payload.get("columns", []))
        shown = rows[:_MAX_DISPLAYED_ROWS]
        body = "\n".join(" | ".join(str(value) for value in row) for row in shown)
        lines.append(f"résultat ({len(rows)} ligne(s)) :\n{header}\n{body}")
        if len(rows) > len(shown):
            lines.append(f"({len(rows) - len(shown)} ligne(s) non affichée(s))")
    if payload.get("total") is not None:
        lines.append(f"total : {payload['total']}")
    if payload.get("schema"):
        lines.append(f"contrat de lecture :\n{payload['schema']}")
    if payload.get("conventions"):
        lines.append("conventions appliquées :\n"
                     + "\n".join(f"  - {rule}" for rule in payload["conventions"]))
    return "\n\n".join(lines)


def build_agent(strategy: Strategy, profile: str = "support"):  # type: ignore[no-untyped-def]
    @tool
    def search_docs(query: str) -> str:
        """Documentation produit et procédures Sorabel. Cherche des extraits dans le corpus
        (fiches techniques, notices, procédures SAV) ; rend les extraits ou un refus motivé.
        Pour un chiffre, un stock ou un montant, utiliser ask_to_db."""
        denied = _denied_docs(profile)
        if denied is not None:
            return denied
        # Étage 3 : le périmètre documentaire du profil part dans la requête, avant la
        # troncature. Le refus d'un profil sans aucune collection tombe ici aussi, et il
        # n'est pas un « hors corpus » — le corpus couvre peut-être la question.
        result = search_for_profile(query, profile, strategy=strategy)
        if result.status != "ok":
            return result.message
        return "\n\n".join(
            f"[{citation(hit)['reference']}] {citation(hit)['titre']} "
            f"(score {hit.score:.3f})\n{hit.text}"
            for hit in result.hits
        )

    @tool
    def ask_to_db(question: str) -> str:
        """Base de données commerciale Sorabel : produits, stocks, clients, commandes,
        ventes. Traduit une question chiffrée en requête SQL de lecture, l'exécute, et rend
        le résultat AVEC la requête qui l'a produit. Pour le stock d'UNE référence, préférer
        check_stock ; pour le statut d'UNE commande, order_status. Pour un « comment » ou un
        « pourquoi », c'est search_docs."""
        # La clé lue dans la matrice reste `ask_database` : c'est le nom du tool AU
        # CATALOGUE, celui que la gouvernance nomme. `ask_to_db` n'est que le nom local de
        # ce banc d'essai — les confondre laisserait croire que le catalogue est implémenté.
        return _serve("ask_database", {"question": question}, profile)

    @tool
    def check_stock_by_ref(reference: str) -> str:
        """Stock d'UNE référence produit Sorabel, entrepôt par entrepôt, avec le total et le
        seuil de réapprovisionnement propre à chaque entrepôt. La référence doit être au
        format REF-NNNN : un libellé de produit ne l'identifie pas. Pour une question de
        stock plus large (plusieurs produits, un classement), c'est ask_to_db."""
        return _serve("check_stock", {"reference": reference}, profile)

    @tool
    def order_status_by_id(order_id: str) -> str:
        """En-tête d'UNE commande Sorabel identifiée : statut, date, montant HT, client.
        L'identifiant doit être au format CMD-AAAA-NNNN. Ne rend pas le détail des lignes de
        vente — pour cela, ou pour plusieurs commandes, c'est ask_to_db."""
        return _serve("order_status", {"order_id": order_id}, profile)

    @tool
    def get_db_schema() -> str:
        """Contrat de lecture de la base Sorabel : les tables et colonnes que ce profil a le
        droit d'interroger, leurs valeurs possibles, la période couverte et les conventions
        métier. Ne rend aucune donnée — c'est la FORME de la base, pas son contenu. Utile
        pour savoir ce qui est interrogeable avant de poser une question chiffrée."""
        return _serve("get_schema", {}, profile)

    if not settings.llm_chat_model:
        raise RuntimeError(
            "LLM_CHAT_MODEL n'est pas renseigné dans .env — c'est le modèle "
            "de chat que cet agent appelle."
        )

    llm = init_chat_model(
        settings.llm_chat_model,
        model_provider="openai",
        base_url=llm_base_url(settings.azure_ai_endpoint),
        api_key=SecretStr(settings.azure_ai_api_key),
    )
    return create_agent(
        llm,
        tools=[search_docs, ask_to_db, check_stock_by_ref, order_status_by_id,
               get_db_schema],
        system_prompt=_SYSTEM_PROMPT,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        choices=["dense", "lexical", "hybrid"],
        default="hybrid",
        help="étage de recherche appelé par l'outil (défaut : hybrid, le meilleur mesuré).",
    )
    parser.add_argument(
        "--profile",
        default="support",
        help="profil de la matrice appliqué au SQL (défaut : support). Un profil inconnu "
             "retombe sur `default`, qui n'a aucun droit.",
    )
    args = parser.parse_args()

    agent = build_agent(args.strategy, args.profile)
    print(f"Agent Sorabel — étage « {args.strategy} », profil SQL « {args.profile} ». "
          "Ctrl+D pour quitter.")
    while True:
        try:
            question = input("\n> ").strip()
        except EOFError:
            print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break
        with call_record() as book:
            response = agent.invoke({"messages": [{"role": "user", "content": question}]})
            # Même règle qu'à l'écran : une phrase figée part telle quelle, le modèle ne
            # la réécrit pas. Sans quoi la CLI et la GUI n'afficheraient pas la même chose
            # pour la même décision.
            print(frozen_text(book) or response["messages"][-1].content)


if __name__ == "__main__":
    main()
