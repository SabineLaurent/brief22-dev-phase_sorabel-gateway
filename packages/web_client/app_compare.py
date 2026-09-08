"""Interface Chainlit de **comparaison** : une question, quatre profils, côte à côte.

Second front, distinct de ``app.py`` et lancé sur son propre port. Le mono-rôle reste le
banc d'essai — on y pose une question *en tant que* quelqu'un ; celui-ci répond à une autre
question, la seule que le brief demande de démontrer : **qu'est-ce qui change quand le
profil change ?**

Ce que chaque colonne montre, et pourquoi ces trois choses-là :

* **le catalogue** (``n tools``) — l'**étage 1**, celui que ``tools/list`` applique. C'est
  le seul étage qu'aucune réponse ne révèle : un tool absent du catalogue n'est pas refusé,
  il n'existe pas pour le modèle, et rien dans le texte rendu ne le dit ;
* **le statut et les codes des tools appelés** — les étages 2 et 3. Deux colonnes qui
  affichent ``ask_database · ok`` et ``ask_database · perimetre_interdit`` sur la même
  question, c'est E5 lisible sans ouvrir le journal ;
* **la réponse servie telle quelle** — phrase figée comprise. L'interface ne reformule
  rien : c'est ``api.py`` qui a déjà tranché entre le texte du modèle et la phrase du refus.

**Aucun droit n'est évalué ici.** Les quatre colonnes tapent la même API, qui parle à
quatre sous-processus serveur MCP distincts, chacun avec son ``SORABEL_PROFILE``. La
séparation est celle des processus ; cette interface ne fait que la regarder.

Lancement : ``make web-compare`` (l'API doit tourner : ``make api``).

Ce front a **son propre ``CHAINLIT_APP_ROOT``** — ``compare_root/`` — et donc sa propre
configuration Chainlit et son propre ``public/elements/``. Ce n'est pas un rangement :
Chainlit efface ``<root>/.files`` à l'arrêt, et deux fronts qui partagent un root
partagent ce dossier ; arrêter le mono-rôle faisait alors échouer les éléments de
celui-ci, resté debout.
"""

from __future__ import annotations

import asyncio
from typing import Any

import chainlit as cl
import httpx

from packages.agent.api import profile_for_role
from packages.web_client.evals import load_eval_questions

API_URL = "http://127.0.0.1:8000/chat"
CATALOGUE_URL = "http://127.0.0.1:8000/catalogue"

#: Les quatre rôles comparés, **par droits croissants** — c'est ce qui rend la grille
#: lisible de gauche à droite : zéro tool, puis le schéma sans les données, puis les
#: données sans les marges, puis tout. ``admin`` n'y est pas : son intérêt est le journal,
#: qui se lit dans le front mono-rôle et ne tiendrait pas dans une colonne.
COLONNES = [
    ("sans_role", "Sans rôle"),
    ("dev", "Dev"),
    ("support", "Support"),
    ("commerciale", "Commerciale"),
]

#: Panne de l'interface elle-même — API injoignable, réponse illisible. Une phrase figée
#: comme partout ailleurs, et distincte de celles du contrat : ce n'est pas la gateway qui
#: a échoué, c'est le banc d'essai qui ne l'a pas jointe. Confondre les deux ferait chercher
#: un refus là où il n'y a qu'un service arrêté.
FRONT_INDISPONIBLE = "L'API de test n'a pas répondu. Vérifier qu'elle tourne (`make api`)."

#: Au-delà, la question est considérée perdue. Large : le premier appel documentaire d'un
#: profil charge l'embedder et le reranker dans son sous-processus (mesuré : ~8 s).
TIMEOUT = 180

_EVAL_QUESTIONS = load_eval_questions()


# `type: ignore[arg-type]` — même dette amont que dans `app.py` : les stubs de Chainlit
# déclarent un rappel prenant un `User | None` que le décorateur n'envoie pas.
@cl.set_starters  # type: ignore[arg-type]
async def starters() -> list[cl.Starter]:
    # Une question de chaque famille, choisies parce qu'elles *séparent* les colonnes :
    # une question de marge oppose support et commerciale, une question documentaire
    # oppose sans_role au reste.
    return [
        cl.Starter(
            label="Marge — sépare support et commerciale",
            message="Quelle est la marge totale sur les ventes d'avril ?",
        ),
        cl.Starter(
            label="Documentaire — REF-8842",
            message="Que dit la fiche technique de la référence REF-8842 ?",
        ),
        cl.Starter(
            label="Schéma — sépare dev du reste",
            message="Quelles tables contient la base ?",
        ),
    ]


def _colonnes_initiales(question: str) -> list[dict[str, Any]]:
    """Les quatre colonnes en attente, avant tout appel."""
    return [
        {
            "role": role,
            "libelle": libelle,
            "profil": profile_for_role(role),
            # `None` et non `[]` : « pas encore demandé » n'est pas « zéro tool », et la
            # différence se voit — `sans_role` a bel et bien zéro tool, et c'est un fait à
            # afficher, pas une absence de réponse.
            "tools": None,
            "statut": "en_cours",
            "reponse": "",
            "calls": [],
        }
        for role, libelle in COLONNES
    ]


def _statut(data: dict[str, Any]) -> str:
    """Le statut de la colonne, dérivé des appels de tools — jamais du texte rendu.

    **Le premier verdict non-``ok`` gagne, et il gagne sur une réponse par ailleurs
    réussie.** Une colonne verte alors qu'un refus a eu lieu en chemin serait exactement le
    contresens que cette interface doit empêcher.

    **C'est volontairement plus strict que ``cli.compose_answer``**, qui depuis le
    2026-09-08 sert la réponse et *complète* par les phrases figées de ce qui n'a pas abouti.
    Les deux ne répondent pas à la même question : le texte dit à l'utilisateur ce qu'il
    obtient, le badge dit à l'observateur ce qui s'est passé. Un incident survenu dans le
    tour doit rester lisible ici même quand la réponse, elle, a été servie — et le badge
    ``tool · code`` de chaque appel le détaille au-dessous.
    """
    if data.get("error"):
        return "error"
    calls = data.get("calls") or []
    if not calls:
        # Catalogue vide, ou question à laquelle le modèle a répondu sans outil. Les deux
        # se lisent pareil ici : rien n'a été demandé à la gateway.
        return "aucun_appel"
    for call in calls:
        if call["status"] != "ok":
            return call["status"]
    return "ok"


async def _publier(element: cl.CustomElement, verrou: asyncio.Lock) -> None:
    """Pousse l'état courant des colonnes vers l'écran.

    Le verrou n'est pas décoratif : les quatre colonnes se terminent dans le désordre et
    appellent toutes ``update()``. Sans sérialisation, deux envois concurrents se
    disputeraient le même élément.
    """
    async with verrou:
        await element.update()


async def _remplir(
    client: httpx.AsyncClient,
    colonne: dict[str, Any],
    question: str,
    element: cl.CustomElement,
    verrou: asyncio.Lock,
) -> None:
    """Interroge une colonne et la publie — deux fois : le catalogue, puis la réponse.

    Le catalogue d'abord parce qu'il revient en une fraction de seconde alors que la
    réponse peut prendre dix secondes : l'utilisateur voit l'étage 1 pendant qu'il attend
    les étages 2 et 3.
    """
    role = colonne["role"]
    try:
        catalogue = await client.get(CATALOGUE_URL, params={"role": role})
        colonne["tools"] = catalogue.json()["tools"]
        await _publier(element, verrou)

        response = await client.post(API_URL, json={"role": role, "question": question})
        data = response.json()
    except Exception:  # noqa: BLE001 - dernier filet avant l'écran, cf. FRONT_INDISPONIBLE
        colonne["statut"] = "error"
        colonne["reponse"] = FRONT_INDISPONIBLE
    else:
        colonne["statut"] = _statut(data)
        colonne["reponse"] = data.get("error") or data["answer"]
        colonne["calls"] = data.get("calls") or []
    await _publier(element, verrou)


@cl.on_chat_start
async def on_chat_start() -> None:
    roles = ", ".join(f"**{libelle}**" for _, libelle in COLONNES)
    await cl.Message(
        content=(
            f"Une question, quatre profils : {roles}.\n\n"
            "Chaque colonne est adossée à **son propre processus serveur MCP**, lancé avec "
            "son `SORABEL_PROFILE` : ce n'est pas l'interface qui filtre.\n\n"
            "Posez une question, ou tapez un identifiant d'eval (ex. `RAG-03`, `SQL-01`) "
            "pour la rejouer sur les quatre."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    typed = message.content.strip()
    question = _EVAL_QUESTIONS.get(typed.upper(), message.content)

    colonnes = _colonnes_initiales(question)
    element = cl.CustomElement(
        name="Comparaison",
        props={"question": question, "colonnes": colonnes},
        display="inline",
    )
    await cl.Message(content="", elements=[element]).send()

    verrou = asyncio.Lock()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # `gather` et non une boucle : les quatre profils partent ensemble, et chacun
        # publie sa colonne dès qu'il a fini. Séquentiellement, la dernière colonne
        # attendrait la somme des trois autres.
        await asyncio.gather(
            *(_remplir(client, colonne, question, element, verrou) for colonne in colonnes)
        )
