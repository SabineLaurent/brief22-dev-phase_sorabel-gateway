"""La rédaction de la réponse documentaire : une passe, deux issues.

Le modèle rend ``{reponse}`` ou ``{insuffisant}`` — jamais les deux. C'est la **seconde
barrière** de ``Q4`` §5 : la première, ``hors_corpus``, est déterministe et aveugle au
contenu — un seuil sur le score du premier résultat ; celle-ci lit les extraits et dit s'ils
portent la réponse. Les deux échouent pour des raisons opposées, d'où deux codes : l'une dit
« je n'ai rien trouvé », l'autre « j'ai trouvé, ça ne répond pas ». Le recours de
l'utilisateur n'est pas le même — reformuler, ou préciser.

**Le modèle ne rédige aucune citation.** Il ne rend que les *numéros* des extraits qu'il a
utilisés ; les références sont construites en Python depuis les métadonnées
(``retrieval/search.citation``). C'est la garantie E1 : il ne peut pas mentir sur ses
sources, parce qu'il n'écrit pas ses sources.

Pas de repli local : il n'existe pas de modèle de rédaction embarqué dans ce dépôt, et
faire semblant d'en avoir un rendrait une réponse fabriquée indiscernable d'une réponse
sourcée.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from config import Settings
from config import settings as default_settings
from packages.rag_machines.retrieval.azure_client import build_azure_openai_client

_SYSTEM_PROMPT = (
    "Tu réponds à une question à partir d'extraits de la documentation interne Sorabel, "
    "et de rien d'autre.\n\n"
    "Règles, sans exception :\n"
    "  - n'utilise que le contenu des extraits fournis ; n'ajoute aucune connaissance "
    "personnelle, même vraie ;\n"
    "  - si les extraits ne portent pas la réponse, ne réponds pas : dis ce qui manque ;\n"
    "  - ne cite pas les sources dans ta réponse : donne les numéros des extraits utilisés, "
    "les références sont ajoutées ensuite.\n\n"
    "Réponds uniquement par un objet JSON à trois champs, dont un seul des deux premiers "
    "est rempli :\n"
    '  {"reponse": "<réponse en français>", "insuffisant": null, "extraits": [1, 3]}\n'
    '  {"reponse": null, "insuffisant": "<ce que les extraits ne disent pas>", '
    '"extraits": []}\n'
)


@dataclass(frozen=True)
class Answer:
    """Ce que rend une passe de rédaction.

    ``used`` porte les **rangs** (1-based) des extraits que le modèle déclare avoir
    utilisés. L'appelant les intersecte avec ce qu'il a fourni : un rang hors bornes est
    ignoré, jamais suivi.
    """

    text: str
    insufficient: str
    used: tuple[int, ...] = ()

    @property
    def is_sufficient(self) -> bool:
        return bool(self.text) and not self.insufficient


def _parse(payload: str) -> Answer:
    """Lit la sortie du modèle. Une sortie hors format est une insuffisance, pas un
    plantage : on préfère ne pas répondre à répondre n'importe quoi."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return Answer("", "le modèle n'a pas rendu de réponse exploitable")
    if not isinstance(data, dict):
        return Answer("", "le modèle n'a pas rendu de réponse exploitable")

    text = str(data.get("reponse") or "").strip()
    insufficient = str(data.get("insuffisant") or "").strip()
    raw = data.get("extraits")
    used = tuple(int(rank) for rank in raw if isinstance(rank, int)) if isinstance(raw, list) else ()

    if text and insufficient:
        # Les deux champs remplis : le modèle n'a pas tranché, donc on tranche pour lui, et
        # dans le sens qui n'invente rien.
        return Answer("", insufficient, used)
    if not text and not insufficient:
        return Answer("", "les extraits ne portent pas la réponse à cette question")
    return Answer(text, insufficient, used)


class AnswerWriter:
    """Azure AI Foundry en OpenAI-compatible, API v1 — client construit paresseusement."""

    def __init__(self, endpoint: str, api_key: str, deployment: str) -> None:
        self.name = deployment
        self._endpoint = endpoint
        self._api_key = api_key
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            self._client = build_azure_openai_client(
                self._endpoint, self._api_key,
                setting_name="LLM_CHAT_MODEL", fallback="aucune rédaction documentaire",
            )
        return self._client

    def write(self, question: str, excerpts: list[str]) -> Answer:
        """Une passe, une décision. Les extraits sont numérotés à partir de 1 — c'est ce
        numéro que le modèle rend, et lui seul."""
        numbered = "\n\n".join(
            f"[{rank}]\n{excerpt}" for rank, excerpt in enumerate(excerpts, start=1)
        )
        # Pas de `temperature` : le déploiement en service refuse toute valeur autre que la
        # sienne. La sortie est tenue par le format JSON imposé.
        response = self._get_client().chat.completions.create(
            model=self.name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"Extraits :\n\n{numbered}\n\nQuestion : {question}"},
            ],
            response_format={"type": "json_object"},
        )
        return _parse(response.choices[0].message.content or "{}")


def build_writer(settings: Settings | None = None) -> AnswerWriter:
    """Rend le rédacteur configuré, ou dit ce qui manque pour l'avoir."""
    settings = settings or default_settings
    if not (settings.llm_chat_model and settings.azure_ai_endpoint):
        raise RuntimeError(
            "rédaction documentaire indisponible : renseigner LLM_CHAT_MODEL et "
            "AZURE_AI_ENDPOINT"
        )
    return AnswerWriter(settings.azure_ai_endpoint, settings.azure_ai_api_key,
                        settings.llm_chat_model)
