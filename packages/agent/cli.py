"""Agent conversationnel LangChain, minimal, **client du serveur MCP**.

Sert à rejouer à la main les questions d'``eval/questions_rag.jsonl`` et
d'``eval/questions_sql.jsonl``, et à rendre la matrice d'accès observable au clic.

**Il n'y a plus qu'une façade.** Cet agent n'appelle plus aucun handler en direct : il
ouvre une session MCP (``packages.agent.gateway``) et n'atteint la gateway que par le
protocole, comme le ferait n'importe quel client externe. Trois choses en découlent, et
aucune n'est codée ici :

* **le profil n'est plus un argument.** Il est écrit dans ``SORABEL_PROFILE``, dans
  l'environnement du sous-processus serveur ; le LLM n'a aucun moyen de l'atteindre ;
* **le catalogue n'est plus en dur.** Les tools sont ceux que ``tools/list`` rend pour ce
  profil — sept pour ``support``, huit pour ``commercial``, cinq pour ``dev``, **zéro**
  pour ``default``. Un tool absent du catalogue n'existe pas pour le modèle ;
* **les quatre tools documentaires passent par leur handler**, donc par l'étage 2, le
  seuil de refus et la journalisation. Le ``search_docs`` local les court-circuitait.

**C'est le LLM qui aiguille** : les tools sont *model-controlled*, et le seul levier est
la rédaction des descriptions — qui viennent désormais du serveur, pas d'ici. Aucun
aiguillage n'est codé. Pas de mémoire : chaque question part d'un historique vide.

**Rien de technique ne remonte au modèle.** Les enveloppes que ce module met en forme sont
déjà purgées par les handlers : ni colonne fermée, ni message du moteur, ni trace
d'exception. Ce n'est pas une précaution de politesse — ce qui arrive ici est recopié dans
le contexte d'un LLM, qui le reformule ensuite librement.

**Et sur un refus, le LLM n'a pas le dernier mot.** Chaque appel dépose son enveloppe dans
le carnet de l'appel en cours (:func:`call_record`) ; ``api.py`` y lit la phrase figée et
la rend **telle quelle**, sans repasser par le modèle. Sinon le déterminisme se perdrait
au dernier mètre : le refus ne varie pas, mais sa reformulation, si.

Usage :
    uv run python -m packages.agent.cli
    uv run python -m packages.agent.cli --profile commercial
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from pydantic import SecretStr

from config import llm_base_url, settings
from packages.agent.gateway import Gateway, build_tools, gateway_session
from packages.text_to_sql_factory.structured_answer import CLIENT_MESSAGES

_SYSTEM_PROMPT = (
    "Tu réponds aux questions sur Sorabel en t'appuyant uniquement sur tes outils — jamais "
    "sur tes propres connaissances.\n\n"
    "Choisis l'outil par le DOMAINE de la question, pas par sa formulation. La forme de la "
    "question est le meilleur indice : un identifiant bien formé oriente vers les données, "
    "un « comment » ou un « pourquoi » vers la documentation.\n"
    "  - answer_question : une réponse rédigée et sourcée sur la documentation interne — "
    "procédure, caractéristique produit, consigne. C'est l'outil documentaire par "
    "défaut ;\n"
    "  - search_docs : les extraits bruts, classés, sans rédaction — quand tu veux voir "
    "sur quoi une réponse s'appuierait avant de la formuler ;\n"
    "  - get_document : le texte intégral d'un document déjà identifié, par son "
    "identifiant. N'accepte pas une question ;\n"
    "  - list_sources : ce que le corpus contient, sans recherche ;\n"
    "  - check_stock : le stock d'UNE référence REF-NNNN, entrepôt par entrepôt ;\n"
    "  - order_status : l'en-tête d'UNE commande CMD-AAAA-NNNN ;\n"
    "  - get_schema : ce que la base contient et ce qui est interrogeable — la forme, "
    "jamais les données ;\n"
    "  - ask_database : toute autre question chiffrée sur la base — comptage, montant, "
    "classement, plusieurs produits ou plusieurs commandes.\n\n"
    "Tu ne disposes que des outils qui te sont présentés : si l'un de ceux cités ci-dessus "
    "ne t'est pas proposé, il ne t'est pas accessible. Ne le réclame pas et n'essaie pas "
    "d'obtenir son résultat autrement.\n\n"
    "Entre un outil figé et ask_database, prends le figé quand la question porte sur UN "
    "objet identifié : sa réponse est plus sûre. Si l'identifiant est absent ou mal formé, "
    "ou si la question en couvre plusieurs, prends ask_database.\n\n"
    "Avec les outils documentaires : cite systématiquement la référence et le titre des "
    "sources utilisées. Si l'outil signale que le corpus ne couvre pas la question, "
    "dis-le clairement au lieu d'inventer une réponse.\n\n"
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

#: Même raison, côté documentaire : les extraits sont longs, et le modèle n'a pas besoin
#: des vingt premiers pour rédiger.
_MAX_DISPLAYED_HITS = 5

#: Les tools du catalogue qui rendent une enveloppe documentaire. Le partage entre les deux
#: domaines s'arrête aux trois clés du contrat : le payload, lui, n'a ni les mêmes clés ni
#: les mêmes codes, et une seule mise en forme pour les huit mentirait sur l'un des deux.
_RAG_TOOLS = frozenset({"answer_question", "search_docs", "get_document", "list_sources"})


#: Le carnet de l'appel en cours. Chaque tool y dépose l'enveloppe de sa réponse ;
#: ``api.py`` y relit la phrase figée avant de rendre quoi que ce soit à l'écran.
#:
#: Une ``ContextVar`` et non un attribut de l'agent : l'agent est mis en cache et partagé
#: entre les requêtes, alors que le carnet appartient à **un** appel.
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


def render(tool: str, view: dict[str, Any]) -> str:
    """Note l'enveloppe au carnet, puis la met sous une forme que le modèle peut restituer.

    C'est le ``render`` que ``gateway.build_tools`` appelle après chaque tool, et il fait
    exactement ce que faisait l'ancien ``_serve()`` : noter, puis mettre en forme. Le point
    de bascule tient dans le fait que l'enveloppe vient maintenant du protocole.
    """
    book = _CURRENT_CALL.get()
    if book is not None:
        book.append(view)
    if tool in _RAG_TOOLS:
        return _format_documentary_answer(view, tool)
    return _format_database_answer(view, tool)


def _preamble(view: dict[str, Any], tool: str) -> list[str]:
    """L'en-tête commun aux deux domaines : quel outil a répondu, et sous quel code.

    Le nom du tool est rendu au modèle parce que l'aiguillage est interne : sans lui,
    l'utilisateur ne saurait pas si son chiffre vient d'une requête figée ou générée, ni
    si sa réponse a été rédigée ou seulement extraite.
    """
    lines = [f"outil : {tool}", f"code : {view['payload']['code']}"]
    if view["message"]:
        lines.append(f"message : {view['message']}")
    return lines


def _format_database_answer(view: dict[str, Any], tool: str) -> str:
    """Met l'enveloppe d'un tool SQL sous une forme que le modèle peut restituer.

    La requête et les conventions sont rendues au même titre que les lignes : sans elles,
    le chiffre n'est pas vérifiable, et c'est ce que la transparence E3 demande.

    Sur un refus, il n'y a **rien** à mettre en forme que la phrase figée : le payload est
    réduit à son code en amont, et c'est ce qui empêche le modèle de reformuler une cause
    qu'il n'a pas.
    """
    payload = view["payload"]
    lines = _preamble(view, tool)
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


def _format_documentary_answer(view: dict[str, Any], tool: str) -> str:
    """Met l'enveloppe d'un tool documentaire sous la même forme, avec ses clés à lui.

    Cinq clés seulement, celles que ``PAYLOAD_KEPT`` laisse passer : ``answer`` et
    ``sources`` pour ``answer_question``, ``hits`` pour ``search_docs``, ``text`` et
    ``metadata`` pour ``get_document``, ``sources`` pour ``list_sources``. Toute autre est
    filtrée en amont — il n'y a rien à prévoir ici pour une clé qui n'arrivera pas.

    Les sources sont rendues avec la réponse, jamais séparées : c'est E1 — une réponse
    documentaire sans ses références n'est pas vérifiable. Le modèle a pour consigne de
    les citer, et il ne peut citer que ce qu'on lui montre ici.
    """
    payload = view["payload"]
    lines = _preamble(view, tool)
    if payload.get("answer"):
        lines.append(f"réponse rédigée :\n{payload['answer']}")
    if payload.get("text"):
        lines.append(f"texte du document :\n{payload['text']}")
    sources = payload.get("sources")
    if sources:
        shown = sources[:_MAX_DISPLAYED_ROWS]
        lines.append(f"sources ({len(sources)}) :\n" + "\n".join(
            f"  - [{source.get('reference', '?')}] {source.get('titre', '')}"
            for source in shown
        ))
        if len(sources) > len(shown):
            lines.append(f"({len(sources) - len(shown)} source(s) non affichée(s))")
    hits = payload.get("hits")
    if hits:
        shown = hits[:_MAX_DISPLAYED_HITS]
        lines.append(f"extraits ({len(hits)}) :\n" + "\n\n".join(
            f"[{hit.get('doc_id', '?')}] (score {hit.get('score', 0):.3f})\n"
            f"{hit.get('text', '')}"
            for hit in shown
        ))
        if len(hits) > len(shown):
            lines.append(f"({len(hits) - len(shown)} extrait(s) non affiché(s))")
    if payload.get("metadata"):
        lines.append("métadonnées :\n" + "\n".join(
            f"  - {key} : {value}" for key, value in payload["metadata"].items()
        ))
    return "\n\n".join(lines)


#: Ce qu'on répond quand le profil n'a **aucun** tool. C'est la phrase figée du refus, la
#: même que rendrait l'étage 2 si un tool existait pour la prononcer.
EMPTY_CATALOGUE = CLIENT_MESSAGES["tool_interdit"]


async def build_agent(gateway: Gateway):  # type: ignore[no-untyped-def]
    """Construit l'agent sur le catalogue que **le serveur** sert à ce profil.

    Rend ``None`` quand ce catalogue est **vide** — le cas du profil ``default``. Ce n'est
    pas une optimisation : un modèle sans outil répond quand même, et il répond en
    annonçant une action qu'il ne peut pas faire (« je vais interroger la base… »). Il
    n'aurait pas menti avant le branchement, parce que le tool existait alors pour se faire
    refuser et rendre sa phrase figée. Le catalogue filtré supprime l'appel *et* le refus
    qui l'accompagnait : la phrase, elle, doit rester — c'est :data:`EMPTY_CATALOGUE`.

    Il n'y a plus de paramètre ``profile`` : le profil appartient au processus au bout de
    la session. Il n'y a plus de paramètre ``strategy`` non plus — l'étage de recherche
    est décidé par les tools du serveur, qui sont ceux que la mesure a réglés.
    """
    tools = await build_tools(gateway, render)
    if not tools:
        return None

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
    return create_agent(llm, tools=tools, system_prompt=_SYSTEM_PROMPT)


async def run(profile: str) -> None:
    async with gateway_session(profile) as gateway:
        catalogue = await gateway.catalogue()
        agent = await build_agent(gateway)
        names = ", ".join(card.name for card in catalogue) or "aucun"
        print(f"Agent Sorabel — profil « {profile} », {len(catalogue)} tool(s) : {names}.")
        if agent is None:
            print(EMPTY_CATALOGUE)
            return
        print("Ctrl+D pour quitter.")
        while True:
            try:
                # `to_thread` parce que `input()` bloque : la session MCP vit dans cette
                # boucle, et la bloquer empêcherait le sous-processus d'être servi.
                question = (await asyncio.to_thread(input, "\n> ")).strip()
            except EOFError:
                print()
                break
            if not question:
                continue
            if question.lower() in {"exit", "quit"}:
                break
            with call_record() as book:
                response = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": question}]}
                )
                # Même règle qu'à l'écran : une phrase figée part telle quelle, le modèle
                # ne la réécrit pas. Sans quoi la CLI et la GUI n'afficheraient pas la
                # même chose pour la même décision.
                print(frozen_text(book) or response["messages"][-1].content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default="support",
        help="profil de la matrice, passé au serveur MCP dans SORABEL_PROFILE (défaut : "
             "support). Un profil inconnu retombe sur `default`, qui n'a aucun droit.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.profile))


if __name__ == "__main__":
    main()
