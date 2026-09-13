"""Interface Chainlit pour tester l'agent Sorabel par rôle, et rejouer les questions des
jeux d'évaluation (eval/questions_*.jsonl).

Le rôle sélectionné **agit réellement**, sur les deux domaines : l'API le convertit en profil
de la matrice d'accès, qui décide du droit d'interroger la base et des colonnes atteignables,
et du droit d'interroger le corpus — collections ouvertes et thèmes de notes.

Écart assumé, le temps du banc d'essai : ici c'est le client qui déclare son rôle, alors que
la conception veut le profil lu côté serveur. Il disparaît avec une chaîne d'identité.

**Ce module n'importe rien du backend.** Ni la matrice, ni la conversion rôle → profil : les
rôles proposés, leurs libellés et leurs droits viennent de ``GET /roles``. C'est la règle déjà
appliquée au catalogue à l'étape C — *ce que le client affiche des droits, il le demande au
serveur* — étendue à ce qui restait. Sans elle, un front déployé séparément embarquerait sa
propre copie de ``matrice.yaml``, et deux exemplaires d'une source d'autorité divergent.

Pour rejouer une question d'un jeu d'évaluation, taper son identifiant (ex. « RAG-03 »,
« SQL-01 », « CAL-02 ») dans le chat.

Lancement : uv run chainlit run packages/web_client/app.py
"""

from __future__ import annotations

import os

import chainlit as cl
import httpx

from packages.web_client.evals import load_eval_questions

#: L'adresse du backend. Surchargeable parce que le front et l'API sont deux processus
#: distincts au déploiement : le défaut vaut pour la boucle de développement, où les deux
#: tournent sur la même machine.
API_BASE = os.environ.get("SORABEL_API_URL", "http://127.0.0.1:8000").rstrip("/")

API_URL = f"{API_BASE}/chat"
JOURNAL_URL = f"{API_BASE}/journal"
ROLES_URL = f"{API_BASE}/roles"

#: Le rôle actif quand le sélecteur n'en a désigné aucun, à l'**ouverture** d'une session.
#: `support` parce que le brief demande une interface qui démontre la conversation en langue
#: naturelle sous ce rôle ; c'est aussi le premier de la liste servie, donc celui que
#: Chainlit propose de lui-même.
DEFAULT_ROLE = "support"

#: Ce qu'on prend quand une session **avait** un rôle et l'a perdu. Ce n'est PAS le même cas
#: que ci-dessus, et pas le même défaut : `cl.user_session` vit en mémoire du processus, sans
#: persistance, donc une reconnexion sur une autre réplique revient ici. Retomber sur
#: `support` y serait une **élévation de privilèges silencieuse** — un `sans_role` obtiendrait
#: les droits du support sans que rien ne le signale. `sans_role` en fait un échec fermé :
#: zéro tool, refus explicite, et la matrice le journalise.
FALLBACK_ROLE = "sans_role"

#: Le mot tapé au chat pour relire le journal. Un mot plutôt qu'un bouton : l'interface est
#: un banc d'essai, et un bouton laisserait croire que la lecture est acquise — alors que
#: c'est la matrice qui tranche, appel par appel, et que le refus est lui-même journalisé.
JOURNAL_COMMAND = "journal"

#: Les champs d'une entrée affichés en clair, dans cet ordre. La trace d'exception n'y est
#: pas : elle est rendue par l'API, mais un `stack` de quarante lignes dans une bulle de chat
#: noie les dix-neuf autres entrées. Elle est affichée à part, et seulement si elle existe.
_JOURNAL_FIELDS = ("timestamp", "profile", "tool", "status", "code", "decision", "etage",
                   "cause", "sql", "n_rows", "latency_ms", "forbidden")

_EVAL_QUESTIONS = load_eval_questions()

#: Phrase figée quand l'API n'a pas répondu au démarrage. Figée pour la même raison que les
#: autres : un message d'exception sous les yeux d'un agent du support ne dit rien d'utile.
API_INDISPONIBLE = ("L'API n'a pas répondu — les rôles n'ont pas pu être chargés. "
                    "Vérifiez qu'elle est démarrée, puis rechargez la page.")

#: Les droits de chaque rôle, tels que l'API les a dits au démarrage. Un cache d'affichage,
#: **jamais une autorité** : la matrice tranche côté serveur, appel par appel. Il existe
#: parce que Chainlit appelle `chat_profiles()` une fois et `on_chat_start()` à chaque
#: session — refaire l'appel à chacune n'apprendrait rien de neuf.
_ROLE_SUMMARIES: dict[str, str] = {}


async def _fetch_roles() -> list[dict]:
    """Les rôles servis par l'API, ou une liste vide si elle n'a pas répondu.

    Remplit `_ROLE_SUMMARIES` au passage. Ne lève jamais : un front qui refuse de démarrer
    parce que le backend n'est pas encore là serait ingérable au déploiement, où l'ordre de
    lancement des deux processus n'est pas garanti.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cards = (await client.get(ROLES_URL)).json()["roles"]
    except Exception:  # noqa: BLE001 - cf. API_INDISPONIBLE, aucune trace à l'écran
        return []
    _ROLE_SUMMARIES.update({card["role"]: card["summary"] for card in cards})
    return list(cards)


# `type: ignore[arg-type]` — dette amont, pas la nôtre : les stubs de Chainlit déclarent
# un rappel prenant un `User | None`, que le décorateur n'envoie pas. La signature sans
# argument est celle de la documentation et celle qui fonctionne ; l'annoter avec un
# paramètre jamais fourni la rendrait fausse à l'exécution pour plaire au typeur.
@cl.set_chat_profiles  # type: ignore[arg-type]
async def chat_profiles() -> list[cl.ChatProfile]:
    """Les rôles du sélecteur, **demandés à l'API**.

    Une liste en dur ici divergerait de la matrice le jour où un profil y est ajouté ou
    renommé — et le front enverrait alors un rôle inconnu, qui retombe silencieusement sur
    `default`. C'est le défaut que `scripts/mcp_client.py` a corrigé de son côté.

    `name` est l'identifiant du rôle : c'est lui qui part vers l'API. `display_name` est ce
    que le sélecteur montre — la langue du dépôt veut du français en surface, et
    l'identifiant brut n'en est pas.
    """
    cards = await _fetch_roles()
    if not cards:
        # Repli de démarrage, pas de sécurité : rien ne garantit l'ordre de lancement des
        # deux processus. Un seul rôle, et l'accueil dira que l'API n'a pas répondu — sans
        # lui le sélecteur serait vide et l'interface inutilisable.
        return [cl.ChatProfile(name=DEFAULT_ROLE, display_name="Support",
                               markdown_description=API_INDISPONIBLE)]
    return [cl.ChatProfile(name=card["role"], display_name=card["display_name"],
                           markdown_description=card["summary"])
            for card in cards]


# Même stub Chainlit, même motif qu'au-dessus.
@cl.set_starters  # type: ignore[arg-type]
async def starters() -> list[cl.Starter]:
    return [
        cl.Starter(label=f"{qid} — {question[:60]}", message=question)
        for qid, question in list(_EVAL_QUESTIONS.items())[:4]
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    role = cl.user_session.get("chat_profile") or DEFAULT_ROLE
    cl.user_session.set("role", role)
    if not _ROLE_SUMMARIES:
        # Le sélecteur a démarré sur son repli : l'API n'avait pas répondu. Réessayer ici
        # rattrape le cas fréquent où le backend a fini de monter entre-temps.
        await _fetch_roles()
    summary = _ROLE_SUMMARIES.get(role) or API_INDISPONIBLE
    await cl.Message(
        content=(
            f"Rôle actif : **{role}** — {summary}\n\n"
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
    role = cl.user_session.get("role", FALLBACK_ROLE)
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
