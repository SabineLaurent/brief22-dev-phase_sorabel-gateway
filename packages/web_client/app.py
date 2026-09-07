"""Interface Chainlit pour tester l'agent Sorabel par rôle, et rejouer les questions des
jeux d'évaluation (eval/questions_*.jsonl).

Le rôle sélectionné **agit réellement**, sur les deux domaines : l'API le convertit en profil
de la matrice d'accès, qui décide du droit d'interroger la base et des colonnes atteignables,
et du droit d'interroger le corpus — collections ouvertes et thèmes de notes.

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
JOURNAL_URL = "http://127.0.0.1:8000/journal"
ALLOWED_URL = "http://127.0.0.1:8000/journal/allowed"

#: Le mot tapé au chat pour relire le journal. Un mot plutôt qu'un bouton : l'interface est
#: un banc d'essai, et un bouton laisserait croire que la lecture est acquise — alors que
#: c'est la matrice qui tranche, appel par appel, et que le refus est lui-même journalisé.
JOURNAL_COMMAND = "journal"

#: Les champs d'une entrée affichés en clair, dans cet ordre. La trace d'exception n'y est
#: pas : elle est rendue par l'API, mais un `stack` de quarante lignes dans une bulle de chat
#: noie les dix-neuf autres entrées. Elle est affichée à part, et seulement si elle existe.
_JOURNAL_FIELDS = ("timestamp", "profile", "tool", "status", "code", "decision", "etage",
                   "cause", "sql", "n_rows", "latency_ms", "forbidden")

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


# `type: ignore[arg-type]` — dette amont, pas la nôtre : les stubs de Chainlit déclarent
# un rappel prenant un `User | None`, que le décorateur n'envoie pas. La signature sans
# argument est celle de la documentation et celle qui fonctionne ; l'annoter avec un
# paramètre jamais fourni la rendrait fausse à l'exécution pour plaire au typeur.
@cl.set_chat_profiles  # type: ignore[arg-type]
async def chat_profiles() -> list[cl.ChatProfile]:
    # `name` est l'identifiant du rôle : c'est lui qui part vers l'API et que
    # `profile_for_role()` convertit. `display_name` est ce que le sélecteur montre — la
    # langue du dépôt veut du français en surface, et l'identifiant brut n'en est pas.
    return [
        cl.ChatProfile(name="support", display_name="Support",
                       markdown_description="Rôle **support** (défaut)."),
        cl.ChatProfile(name="dev", display_name="Dev",
                       markdown_description="Rôle **dev**."),
        cl.ChatProfile(name="commerciale", display_name="Commerciale",
                       markdown_description="Rôle **commerciale**."),
        cl.ChatProfile(name="sans_role", display_name="Sans rôle",
                       markdown_description="**Sans rôle**."),
        cl.ChatProfile(name="admin", display_name="Admin",
                       markdown_description="Rôle **admin**."),
    ]


# Même stub Chainlit, même motif qu'au-dessus.
@cl.set_starters  # type: ignore[arg-type]
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
    # La documentation se lit dans la matrice, elle ne se promet pas en dur : `default` n'a
    # aucun tool, `search_docs` compris. L'étage 2 lui est désormais appliqué comme aux
    # quatre tools SQL, et le périmètre documentaire du profil part dans la requête — la
    # phrase dit donc ce qui se passe, plus seulement ce qui devrait se passer.
    docs = (" La documentation reste interrogeable." if "search_docs" in scope.tools
            else " La documentation ne lui est pas ouverte non plus.")
    if "ask_database" not in scope.tools:
        # Le cas de `dev` : il a `get_schema` et aucun tool de lecture de données. La forme
        # de la base, jamais son contenu — le dire évite de faire passer pour une panne un
        # schéma qui répond pendant qu'un chiffre est refusé.
        forme = (" Le **schéma** reste consultable : la forme de la base, pas son contenu."
                 if "get_schema" in scope.tools else "")
        return (f"profil `{profile}` — **aucun chiffre** : les questions sur les données "
                f"seront refusées.{docs}{forme}")
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
            "(ex. `RAG-03`, `SQL-01`, `CAL-02`) pour la rejouer.\n\n"
            f"Tapez `{JOURNAL_COMMAND}` pour relire le journal des appels — la matrice dit "
            "qui en a le droit, et la tentative est journalisée dans les deux cas."
        )
    ).send()


def _format_entry(entry: dict) -> str:
    """Une entrée de journal, mise à plat. Rendue **entière** côté API ; ici seulement mise
    en forme, jamais expurgée — l'affichage n'est pas la barrière."""
    lines = [f"- **{field}** : `{entry[field]}`"
             for field in _JOURNAL_FIELDS
             if entry.get(field) not in (None, "", [], 0, 0.0)]
    stack = entry.get("stack")
    if stack:
        lines.append(f"```\n{stack.strip()}\n```")
    return "\n".join(lines)


async def _show_journal(role: str) -> None:
    """Affiche le journal, ou le refus que la matrice oppose à ce rôle.

    Aucun contrôle de droits n'est fait ici : l'API refuse, et son refus arrive sous la même
    forme que n'importe quelle autre réponse — un `status` et une phrase figée. Le doubler
    d'un contrôle côté interface donnerait deux barrières à maintenir, dont une seule
    journalisée.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(JOURNAL_URL, params={"role": role, "limit": 20})
        data = response.json()

    if data["status"] != "ok":
        await cl.Message(content=data["message"]).send()
        return

    entries = data.get("entries") or []
    body = "\n\n---\n\n".join(_format_entry(entry) for entry in reversed(entries))
    await cl.Message(
        content=f"**Journal — {len(entries)} dernière(s) entrée(s), la plus récente "
                f"d'abord**\n\n{body}"
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    role = cl.user_session.get("role", "support")
    typed = message.content.strip()

    if typed.lower() == JOURNAL_COMMAND:
        await _show_journal(role)
        return

    question = _EVAL_QUESTIONS.get(typed.upper(), message.content)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(API_URL, json={"role": role, "question": question})
        data = response.json()

    # `error` ne porte plus qu'une phrase figée : l'API ne laisse plus sortir de message
    # d'exception. Le préfixe reste, il dit à l'utilisateur que rien n'a abouti.
    if data.get("error"):
        await cl.Message(content=f"Erreur : {data['error']}").send()
    else:
        await cl.Message(content=data["answer"]).send()
