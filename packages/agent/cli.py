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
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import StructuredTool
from pydantic import SecretStr

from config import llm_base_url, settings
from packages.agent.gateway import Gateway, build_tools, gateway_session
from packages.text_to_sql_factory.structured_answer import CLIENT_MESSAGES

#: La consigne du **client**, et seulement elle : qui est cet agent.
#:
#: Tout ce qui concerne l'usage de *cette* gateway — n'évoquer que les tools de
#: ``tools/list``, essayer un autre domaine avant de renoncer, rendre ``message`` tel quel
#: sur un refus, citer les sources, montrer le SQL — a été **déplacé dans les
#: ``instructions`` du serveur** (``mcp_server/server.py``), que ``build_agent`` préfixe
#: ici. Une seule source par sujet : ces règles décrivent comment consommer la gateway,
#: donc elles lui appartiennent, et tout client qui lit le ``initialize`` en hérite — pas
#: seulement celui de ce dépôt.
#:
#: Ce prompt en énumérait les huit tools, pour les cinq profils, avec la clause « si l'un
#: de ceux cités ci-dessus ne t'est pas proposé, il ne t'est pas accessible ». Deux
#: défauts en sortaient, mesurés le 2026-09-08 : le prompt **publiait l'étage 1 en creux**
#: (le modèle apprenait l'existence des tools fermés et le disait à l'utilisateur), et il
#: **faisait renoncer les profils partiels** — `dev` n'essayait jamais la documentation sur
#: une référence nue, donc aucun tool appelé, donc aucun verdict, donc **aucune phrase
#: figée** : un faux refus rédigé par le modèle, variable et absent du journal.
#: L'énumération était de surcroît redondante, les descriptions des tools présents arrivant
#: déjà par le protocole.
_SYSTEM_PROMPT = (
    "Tu es l'assistant du banc d'essai Sorabel : tu réponds aux questions sur la "
    "documentation technique et la base métier de Sorabel en t'appuyant uniquement sur "
    "tes outils — jamais sur tes propres connaissances. Tu n'as pas de mémoire d'une "
    "question à l'autre."
)

#: L'en-tête sous lequel la consigne du serveur est présentée au modèle. Nommer sa
#: provenance n'est pas cosmétique : elle vient d'en face, elle peut changer sans que ce
#: fichier bouge, et le modèle doit la lire comme la règle de la gateway et non comme une
#: préférence de son client.
_SERVER_INSTRUCTIONS_HEADER = "Consigne d'usage déclarée par la gateway Sorabel :"

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

#: Le tool par lequel le modèle **déclare qu'il ne peut pas répondre**. Il est **local au
#: banc d'essai** : il n'est pas au catalogue MCP, il n'atteint aucune donnée, et il ne
#: traverse jamais le protocole. Ce n'est donc pas une entorse à l'étage 1 — la matrice
#: décide de ce qui touche aux données, et celui-ci ne touche à rien.
#:
#: Il existe parce qu'un **renoncement du modèle n'a pas de verdict**, et que rien ne peut
#: figer ce qui n'en a pas. Mesuré le 2026-09-08 sur ``SQL-01`` sous ``dev`` : quatre
#: appels, trois tournures différentes, et une colonne verte à l'écran alors que
#: l'utilisateur n'avait rien obtenu — ``get_schema`` avait réussi, puis le modèle avait
#: renoncé. Le client ne pouvait pas le savoir sans lire le texte, ce qu'il ne doit pas
#: faire ; le serveur ne le sait pas non plus, puisque aucun de ses tools n'a échoué. **Le
#: seul qui le sache est le modèle**, et jusqu'ici rien ne lui permettait de le dire
#: autrement qu'en rédigeant.
NO_ANSWER_TOOL = "declare_no_answer"

#: Le code de cette déclaration. Il est **distinct de ``tool_interdit``** — décidé le
#: 2026-09-09 : un renoncement du modèle n'est pas un refus de la matrice, et leur donner le
#: même code les confondrait au journal comme à la mesure.
NO_ANSWER_CODE = "aucun_tool_adapte"

#: Son statut, et il n'est **aucun des cinq du contrat DSI**. C'est voulu, et c'est sans
#: danger : cette enveloppe est fabriquée ici, elle ne vient pas d'un tool de la gateway et
#: n'y retourne pas. Lui donner ``refused`` en ferait un refus qu'aucune barrière n'a
#: prononcé — la faute que ``REFUSAL_CODES`` évite déjà aux deux non-réponses documentaires
#: ; lui donner ``ok`` rendrait la colonne verte, c'est-à-dire le défaut qu'on corrige.
NO_ANSWER_STATUS = "sans_reponse"

#: La phrase servie, et elle est **nouvelle** : « Cette information n'est pas accessible
#: avec votre profil. » était le candidat naturel, mais elle décrit un refus de droits, et
#: un renoncement n'en est pas un. Deux mécanismes différents, deux phrases.
NO_ANSWER_MESSAGE = "Aucun outil disponible ne permet de répondre à cette question."

#: La description lue par le modèle — **le seul aiguillage**, comme pour les huit tools du
#: serveur, et suivant les mêmes cinq rubriques. Deux précautions y sont écrites : ne rien
#: dire des tools absents (c'est la fuite d'existence fermée le 2026-09-08), et ne pas
#: appeler ce tool quand une donnée a déjà été rendue — sans quoi il jetterait ce à quoi
#: l'utilisateur a droit, ce que le correctif du même jour venait d'empêcher.
_NO_ANSWER_DESCRIPTION = """Objet : déclarer que tu ne peux pas répondre à la question.
Entrée : aucun argument.
Sortie : la phrase qui sera servie à l'utilisateur ; elle remplace ce que tu rédigerais.
Utiliser quand : aucun des outils proposés ne permet d'obtenir ce qui est demandé, ou bien ceux que tu as appelés n'ont rien rendu qui y réponde. Appelle-le au lieu d'expliquer toi-même pourquoi tu ne peux pas répondre, et sans commenter ce dont tu disposes ou non.
Ne pas utiliser quand : un outil a rendu la donnée demandée — sers-la ; ni pour une salutation ou une question qui ne porte ni sur la documentation ni sur la base."""


@dataclass(frozen=True)
class CallNote:
    """Ce qu'un tool a rendu pendant l'appel : son nom, et l'enveloppe telle qu'elle est
    arrivée du serveur.

    **Une dataclass et non une clé de plus dans l'enveloppe.** Le nom du tool est une note
    du client, pas un champ du contrat servi ; l'écrire dans le dictionnaire de l'enveloppe
    en ferait une sixième clé indistinguable des trois que le DSI a fixées. La séparation
    est structurelle — un `CallNote` ne peut pas être sérialisé par mégarde à la place d'une
    enveloppe.
    """

    tool: str
    envelope: dict[str, Any]


#: Le carnet de l'appel en cours. Chaque tool y dépose l'enveloppe de sa réponse ;
#: ``api.py`` y relit la phrase figée avant de rendre quoi que ce soit à l'écran.
#:
#: Une ``ContextVar`` et non un attribut de l'agent : l'agent est mis en cache et partagé
#: entre les requêtes, alors que le carnet appartient à **un** appel.
_CURRENT_CALL: ContextVar[list[CallNote] | None] = ContextVar(
    "sorabel_current_call", default=None
)


@contextmanager
def call_record() -> Iterator[list[CallNote]]:
    """Ouvre un carnet pour la durée d'un appel, et le referme quoi qu'il arrive."""
    book: list[CallNote] = []
    token = _CURRENT_CALL.set(book)
    try:
        yield book
    finally:
        _CURRENT_CALL.reset(token)


def _frozen_of(view: dict[str, Any]) -> str:
    """La phrase figée d'une enveloppe, axes de clarification compris."""
    text: str = view["message"]
    axes = view["payload"].get("axes")
    if axes:
        text += "\n" + "\n".join(f"  - {axis}" for axis in axes)
    return text


def _served(book: list[CallNote]) -> bool:
    """Un appel du tour a-t-il rendu quelque chose ? C'est le pivot des deux fonctions
    suivantes, et il ne regarde que le statut : ce qui est ``ok`` a déjà passé les étages 2
    et 3, donc c'est autorisé, donc c'est servable."""
    return any(note.envelope["status"] == "ok" for note in book)


#: Les statuts qui **expliquent mieux qu'un renoncement**. Un refus, une panne ou une
#: clarification sont des verdicts prononcés par la gateway : ils nomment la cause, et la
#: taire derrière la phrase du renoncement effacerait un refus de la matrice à l'écran —
#: une régression d'E5, lisible par l'utilisateur.
#:
#: ``hors_corpus`` n'y est **pas**, et c'est le cœur du correctif : c'est précisément le
#: verdict que ``SQL-08`` sous ``dev`` fait sortir — le modèle, privé du tool qui lit les
#: commandes, se rabat sur le corpus, qui répond honnêtement *pour lui-même* qu'il ne porte
#: pas la réponse. La phrase est alors **fausse sur le fond** : la question n'est pas hors
#: corpus, elle est hors des outils de ce profil.
_EXPLICIT_VERDICTS = frozenset({"refused", "error", "clarification"})


def _no_answer_note() -> CallNote:
    """La note que le renoncement dépose au carnet, sous la forme d'une enveloppe.

    **Une enveloppe fabriquée ici, et la seule du module.** Toutes les autres arrivent du
    protocole. Celle-ci en emprunte la forme pour une raison précise : :func:`frozen_text`,
    :func:`frozen_notes` et le badge du comparateur lisent tous ``status``, et un renoncement
    doit passer par le même chemin qu'un verdict — sinon il faudrait une seconde lecture du
    carnet, et deux lectures finissent par diverger.
    """
    return CallNote(
        NO_ANSWER_TOOL,
        {"status": NO_ANSWER_STATUS,
         "payload": {"code": NO_ANSWER_CODE},
         "message": NO_ANSWER_MESSAGE},
    )


def renounced(book: list[CallNote]) -> bool:
    """Le modèle a-t-il déclaré, pendant ce tour, qu'il ne pouvait pas répondre ?"""
    return any(note.envelope["status"] == NO_ANSWER_STATUS for note in book)


def frozen_text(book: list[CallNote]) -> str | None:
    """La phrase qui **remplace** la réponse, ou ``None`` s'il y a autre chose à servir.

    C'est le point de décision unique : *le modèle n'entre en jeu que quand il y a un
    résultat à exprimer.* Partout ailleurs — refus, panne, clarification, non-réponse — la
    phrase est déjà écrite et part à l'écran sans passer par lui. Elle ne peut donc pas
    varier d'un appel à l'autre.

    **La règle a un domaine, et il a fallu le border quand l'agent s'est mis à appeler deux
    tools pour une même question.** « Le premier verdict non-``ok`` gagne, sur tout » était
    juste tant qu'un tour n'avait qu'un appel : il n'y avait rien à écraser. Dès que deux
    domaines répondent, elle devient fausse — mesuré le 2026-09-08 sur une référence nue,
    trois passes sur trois : ``answer_question`` rendait ``contexte_insuffisant`` et
    ``check_stock`` rendait son résultat, et l'écran affichait « les documents ne portent pas
    la réponse » en **jetant le stock**.

    D'où la coupure : **on substitue quand rien n'a été servi, on complète sinon**
    (:func:`frozen_notes`). Ce qui est ``ok`` a franchi les étages d'accès — le refuser à
    l'écran ne protège rien, ça prive l'utilisateur de ce à quoi il a droit. Et ce qui n'a
    pas abouti reste dit, **avec sa phrase**, jamais avec celle du modèle.

    **Le renoncement est la seule exception à cette coupure**, et il passe devant tout le
    reste sauf un verdict de la gateway (:data:`_EXPLICIT_VERDICTS`). C'est le seul cas où
    le client sait qu'un appel ``ok`` n'a pas répondu à la question — parce que le modèle
    l'a déclaré, et qu'il est le seul à avoir lu le résultat.
    """
    if renounced(book):
        # Un verdict de la gateway explique mieux qu'un renoncement, et il garde donc la
        # parole ; sinon c'est le renoncement qui parle — y compris par-dessus un appel
        # servi, et c'est assumé. `get_schema·ok` sous `dev` **a** été servi, au modèle ;
        # l'utilisateur, lui, n'a rien obtenu, et le seul à savoir lequel des deux est vrai
        # est celui qui a lu le résultat.
        for note in book:
            if note.envelope["status"] in _EXPLICIT_VERDICTS:
                return _frozen_of(note.envelope)
        return NO_ANSWER_MESSAGE
    if _served(book):
        return None
    for note in book:
        if note.envelope["status"] != "ok":
            return _frozen_of(note.envelope)
    return None


def frozen_notes(book: list[CallNote]) -> list[str]:
    """Les phrases figées à **ajouter** à une réponse servie : ce qui n'a pas abouti pendant
    que le reste aboutissait.

    Vide quand rien n'a été servi — c'est alors :func:`frozen_text` qui parle, et une phrase
    ne doit pas sortir deux fois. Les doublons sont écartés en gardant l'ordre : deux tools
    du même domaine refusés pour le même motif rendent la même phrase, et la répéter
    donnerait à lire une insistance qui n'existe pas.
    """
    if renounced(book) or not _served(book):
        return []
    return list(dict.fromkeys(_frozen_of(note.envelope) for note in book
                              if note.envelope["status"] != "ok"))


def compose_answer(book: list[CallNote], drafted: str) -> str:
    """Ce qui part à l'écran : la phrase figée seule, ou le texte du modèle suivi des
    phrases figées de ce qui n'a pas abouti.

    **Un seul point d'assemblage pour la CLI et l'API**, et ce n'est pas de l'économie : les
    deux affichaient déjà la même décision par deux chemins parallèles, ce qui les laissait
    libres de diverger au prochain changement. Celui-ci en était un.
    """
    frozen = frozen_text(book)
    if frozen is not None:
        return frozen
    # Une phrase que le modèle a **déjà recopiée** ne s'ajoute pas : la consigne du serveur
    # lui demande de rendre `message` tel quel, et il le fait — mesuré, deux passes sur trois
    # sur une référence inexistante, où la phrase de non-réponse sortait donc deux fois.
    # L'égalité est stricte, sur la phrase entière : une paraphrase du modèle ne compte pas
    # comme la phrase figée, et celle-ci doit alors bien être ajoutée.
    notes = [note for note in frozen_notes(book) if note not in drafted]
    return "\n\n".join([drafted, *notes]) if notes else drafted


def render(tool: str, view: dict[str, Any]) -> str:
    """Note l'enveloppe au carnet, puis la met sous une forme que le modèle peut restituer.

    C'est le ``render`` que ``gateway.build_tools`` appelle après chaque tool, et il fait
    exactement ce que faisait l'ancien ``_serve()`` : noter, puis mettre en forme. Le point
    de bascule tient dans le fait que l'enveloppe vient maintenant du protocole.
    """
    book = _CURRENT_CALL.get()
    if book is not None:
        book.append(CallNote(tool, view))
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


def _compose_prompt(gateway: Gateway) -> str:
    """La consigne du client, précédée de celle que le serveur a déclarée.

    Le champ ``instructions`` est **optionnel** dans le protocole : un serveur peut n'en
    rendre aucune, et un client ne doit pas dépendre de sa présence. D'où la composition
    plutôt que la concaténation en dur — sans instructions, le prompt reste celui du
    client, et l'agent fonctionne.
    """
    if not gateway.instructions:
        return _SYSTEM_PROMPT
    return (f"{_SYSTEM_PROMPT}\n\n{_SERVER_INSTRUCTIONS_HEADER}\n"
            f"{gateway.instructions}")


async def _declare_no_answer() -> str:
    """Ce que fait le tool de renoncement : noter, et rendre sa phrase.

    Il ne touche à rien d'autre. Le texte rendu au modèle **est** la phrase servie, et non
    un accusé de réception : s'il la recopie dans sa rédaction — ce que la consigne du
    serveur lui demande de faire des ``message`` — il recopie la bonne, et
    :func:`compose_answer` la servira de toute façon telle quelle.
    """
    book = _CURRENT_CALL.get()
    if book is not None:
        book.append(_no_answer_note())
    return NO_ANSWER_MESSAGE


def _no_answer_tool() -> StructuredTool:
    """Le tool de renoncement, **ajouté au catalogue du serveur, jamais mêlé à lui**.

    Sans argument : il n'y a rien à en tirer. Une « raison » rédigée par le modèle serait du
    texte libre de plus à filtrer, et c'est exactement ce dont on cherche à se passer.
    """
    return StructuredTool(
        name=NO_ANSWER_TOOL,
        description=_NO_ANSWER_DESCRIPTION,
        args_schema={"type": "object", "properties": {}},
        coroutine=_declare_no_answer,
    )


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
    # Après le catalogue, et seulement s'il n'est pas vide : un profil sans aucun tool n'a
    # pas à *déclarer* qu'il ne peut pas répondre, `EMPTY_CATALOGUE` le dit déjà, et sans
    # dépendre d'un appel de modèle.
    tools.append(_no_answer_tool())

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
    return create_agent(llm, tools=tools, system_prompt=_compose_prompt(gateway))


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
                # Même règle qu'à l'écran, et par le même code : une phrase figée part telle
                # quelle, le modèle ne la réécrit pas. Sans quoi la CLI et la GUI
                # n'afficheraient pas la même chose pour la même décision.
                print(compose_answer(book, response["messages"][-1].content))


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
