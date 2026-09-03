"""Interface Chainlit pour tester l'agent Sorabel par rôle, et rejouer les questions des
jeux d'évaluation (eval/questions_*.jsonl).

Le rôle sélectionné **agit réellement sur les questions chiffrées** : l'API le convertit en
profil de la matrice d'accès, qui décide du droit d'interroger la base et des colonnes
atteignables. Il reste sans effet sur la recherche documentaire.

Écart assumé, le temps du banc d'essai : ici c'est le client qui déclare son rôle, alors que
la conception veut le profil lu côté serveur. Il disparaît avec le serveur MCP.

Pour rejouer une question d'un jeu d'évaluation, taper son identifiant (ex. « RAG-03 »,
« SQL-01 », « CAL-02 ») dans le chat.

Lancement : uv run chainlit run packages/web_client/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import chainlit as cl
import httpx

from packages.agent.api import profile_for_role
from packages.access import scope_for

API_URL = "http://127.0.0.1:8000/chat"

_EVAL_FILES = [
    Path("eval/questions_rag.jsonl"),
    Path("eval/questions_sql.jsonl"),
    Path("eval/questions_calibration.jsonl"),
]


def _load_eval_questions() -> dict[str, str]:
    questions: dict[str, str] = {}
    for path in _EVAL_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            questions[entry["id"]] = entry["question"]
    return questions


_EVAL_QUESTIONS = _load_eval_questions()


@cl.set_chat_profiles
async def chat_profiles() -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(name="support", markdown_description="Rôle **support** (défaut)."),
        cl.ChatProfile(name="dev", markdown_description="Rôle **dev**."),
        cl.ChatProfile(name="commerciale", markdown_description="Rôle **commerciale**."),
        cl.ChatProfile(name="sans_role", markdown_description="**Sans rôle**."),
        cl.ChatProfile(name="admin", markdown_description="Rôle **admin**."),
    ]


@cl.set_starters
async def starters() -> list[cl.Starter]:
    return [
        cl.Starter(label=f"{qid} — {question[:60]}", message=question)
        for qid, question in list(_EVAL_QUESTIONS.items())[:4]
    ]


def _rights_summary(role: str) -> str:
    """Ce que ce rôle peut faire, dit d'avance plutôt que découvert par un refus.

    Un `sans_role` doit apprendre à l'accueil qu'il n'obtiendra aucun chiffre : le lui
    laisser découvrir par un refus donnerait l'impression d'une panne.
    """
    profile = profile_for_role(role)
    scope = scope_for(profile)
    if "ask_database" not in scope.tools:
        # Le cas de `dev` : il a `get_schema` et aucun tool de lecture de données. La forme
        # de la base, jamais son contenu — le dire évite de faire passer pour une panne un
        # schéma qui répond pendant qu'un chiffre est refusé.
        forme = (" Le **schéma** reste consultable : la forme de la base, pas son contenu."
                 if "get_schema" in scope.tools else "")
        return (f"profil `{profile}` — **aucun chiffre** : les questions sur les données "
                f"seront refusées. La documentation reste interrogeable.{forme}")
    sensitive = {("produits", "prix_achat_ht"), ("produits", "marge_pct"),
                 ("ventes", "marge_ht")}
    marges = ("marges et prix d'achat compris" if sensitive <= scope.columns
              else "**sans** les marges ni le prix d'achat")
    return (f"profil `{profile}` — base interrogeable sur {len(scope.columns)} colonnes, "
            f"{marges}.")


@cl.on_chat_start
async def on_chat_start() -> None:
    role = cl.user_session.get("chat_profile") or "support"
    cl.user_session.set("role", role)
    await cl.Message(
        content=(
            f"Rôle actif : **{role}** — {_rights_summary(role)}\n\n"
            "Posez une question, ou tapez un identifiant d'eval "
            "(ex. `RAG-03`, `SQL-01`, `CAL-02`) pour la rejouer."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    role = cl.user_session.get("role", "support")
    question = _EVAL_QUESTIONS.get(message.content.strip().upper(), message.content)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(API_URL, json={"role": role, "question": question})
        data = response.json()

    if data.get("error"):
        await cl.Message(content=f"Erreur : {data['error']}").send()
    else:
        await cl.Message(content=data["answer"]).send()
