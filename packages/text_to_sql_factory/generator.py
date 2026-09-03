"""La passe de génération : une seule, à sortie structurée, trois branches.

Le modèle rend ``{sql}``, ``{clarification}`` ou ``{refus}`` — un seul champ rempli, les
deux autres vides. Un seul appel, parce que « classer la question » puis « générer le SQL »
en deux appels double la latence et le coût pour une décision que le modèle prend de toute
façon en lisant la question. Le code ajoute une quatrième décision **après** exécution,
que le modèle ne peut pas prendre : l'ambiguïté de données.

**Le modèle ne voit jamais une colonne interdite** : elle n'est pas dans le contrat qu'on
lui donne. Le contrôle 5 de l'AST rattrape ce qu'il *invente* hors du contrat, pas ce qu'on
lui a montré — les deux lisent la même matrice, l'amont est l'aide, l'aval la garantie.

La clarification est **fermée** : une liste d'axes calculables nommés et définis, filtrés
par le périmètre du profil. Jamais un « pouvez-vous préciser ? » — sur « quel est le
meilleur client ? », l'axe choisi change le gagnant, et l'utilisateur n'a aucun moyen de
deviner que « hors commandes annulées » est un axe disponible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from config import Settings
from config import settings as default_settings
from packages.rag_machines.retrieval.azure_client import build_azure_openai_client
from packages.text_to_sql_factory.access import scope_for
from packages.text_to_sql_factory.contract import ReadContract

#: Les axes de « meilleur client », avec les colonnes que chacun exige. Proposer un axe qui
#: sera refusé au tour suivant est un aller-retour inutile — et nommer `marge_ht` dans une
#: suggestion apprendrait au support qu'elle existe. La conclusion s'inverse par rapport au
#: refus, où nommer la colonne est actionnable : là, l'utilisateur sait quoi demander.
_CLARIFICATION_AXES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("montant commandé, brut", "somme de commandes.montant_ht, toutes commandes",
     (("commandes", "montant_ht"),)),
    ("montant hors commandes annulées", "somme de commandes.montant_ht, statut <> 'annulee'",
     (("commandes", "montant_ht"), ("commandes", "statut"))),
    ("nombre de commandes", "compte des commandes passées", (("commandes", "id"),)),
    ("marge réalisée", "somme de ventes.marge_ht sur les commandes non annulées",
     (("ventes", "marge_ht"), ("commandes", "statut"))),
    ("récence", "date de la dernière commande", (("commandes", "date_commande"),)),
)

#: Les deux motifs de refus, et la phrase à servir quand le modèle n'en fournit aucune.
_REFUSAL_MESSAGES = {
    "hors_schema": "la base ne porte pas la donnée demandée",
    "ecriture": "la gateway est en lecture seule : aucune modification des données n'est "
                "possible, quelle que soit la formulation",
}

_SYSTEM_PROMPT = (
    "Tu traduis une question métier en une requête SQLite de LECTURE, sur la base décrite "
    "ci-dessous et sur elle seule.\n\n"
    "Réponds uniquement par un objet JSON à quatre champs, dont un seul des trois premiers "
    "est rempli :\n"
    '  {"sql": "<requête SELECT>", "clarification": null, "refus": null, "motif": null}\n'
    '  {"sql": null, "clarification": {"question": "<ce qui manque>", '
    '"axes": ["<axe 1>", "<axe 2>"]}, "refus": null, "motif": null}\n'
    '  {"sql": null, "clarification": null, "refus": "<phrase en français>", '
    '"motif": "hors_schema"}\n\n'
    "Choisis `sql` quand la question porte sur les données décrites et n'a qu'une lecture "
    "raisonnable.\n"
    "Choisis `clarification` quand plusieurs réponses également correctes existent ET "
    "qu'aucune convention métier énoncée ne tranche entre elles. Les conventions "
    "s'appliquent d'office : ne demande JAMAIS s'il faut exclure les commandes annulées, "
    "quel montant utiliser, ni comment regrouper les clients — c'est déjà décidé, et la "
    "convention appliquée est renvoyée avec le résultat. Quand tu clarifies, propose des "
    "axes pris DANS la liste fournie, jamais inventés, et ne demande jamais de préciser "
    "sans proposer de choix. Préfère les périodes complètes (mois clos) aux périodes "
    "tronquées.\n"
    "Choisis `refus` dans deux cas, et renseigne alors OBLIGATOIREMENT `motif` :\n"
    '  - `motif` = "ecriture" si la demande consiste à modifier, supprimer, insérer, vider '
    "ou mettre à jour des données. La gateway est en lecture seule : aucune écriture n'est "
    "générée, même à titre d'exemple.\n"
    '  - `motif` = "hors_schema" si la base ne porte pas la donnée demandée.\n'
    "Le champ `refus` est une PHRASE adressée à l'utilisateur ; le motif va dans `motif`, "
    "jamais dans `refus`.\n\n"
    "Contraintes sur le SQL : une seule instruction, un SELECT (éventuellement précédé d'un "
    "WITH), aucun point-virgule final, aucune colonne absente du schéma ci-dessous. "
    "Applique les conventions métier énoncées. Aucun texte hors du JSON."
)


@dataclass(frozen=True)
class Generation:
    """Ce que le modèle a rendu, ramené à une branche.

    ``branch`` vaut ``sql``, ``clarification``, ``refus`` — ou ``panne`` quand la sortie
    n'est pas exploitable (JSON invalide, zéro ou deux branches remplies : la panne P1 du
    flux). Une panne n'est pas un refus : rien n'a été refusé, la génération a échoué.
    """

    branch: str
    sql: str = ""
    question: str = ""
    axes: tuple[str, ...] = ()
    reason: str = ""
    #: Sur la branche ``refus`` : ``hors_schema`` ou ``ecriture``. Les deux appellent des
    #: actions différentes de l'utilisateur — reformuler, ou rien : E3 est absolue.
    motive: str = ""


def clarification_axes(profile: str, settings: Settings | None = None) -> tuple[str, ...]:
    """Les axes que ce profil peut se voir proposer : cinq au commercial, quatre au support."""
    allowed = scope_for(profile, settings).columns
    return tuple(
        f"{name} — {definition}"
        for name, definition, columns in _CLARIFICATION_AXES
        if all(column in allowed for column in columns)
    )


def _parse(payload: str) -> Generation:
    """Ramène la sortie du modèle à une branche, ou constate la panne.

    Exactement un champ rempli : zéro branche remplie est une non-réponse, deux branches
    remplies est une réponse contradictoire. Ni l'une ni l'autre n'est exploitable, et
    choisir à la place du modèle reviendrait à inventer sa décision.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        return Generation("panne", reason=f"sortie du modèle illisible : {error}")
    if not isinstance(data, dict):
        return Generation("panne", reason="sortie du modèle hors format")

    sql = (data.get("sql") or "").strip() if isinstance(data.get("sql"), str) else ""
    raw_clarification = data.get("clarification")
    clarification = raw_clarification if isinstance(raw_clarification, dict) else None

    # Le motif est un champ racine : un modèle le remplit plus fidèlement qu'un champ
    # imbriqué. Les deux formes tolérées ensuite ne sont pas de la complaisance — un refus
    # par ailleurs juste ne doit pas échouer sur sa mise en forme.
    raw_refus = data.get("refus")
    if isinstance(raw_refus, dict):
        motive = str(raw_refus.get("motif") or "")
        refus = str(raw_refus.get("explication") or "").strip()
    elif isinstance(raw_refus, str):
        motive, refus = str(data.get("motif") or ""), raw_refus.strip()
    else:
        # Motif seul, sans phrase : le modèle a bien décidé de refuser, il n'a pas rédigé.
        motive, refus = str(data.get("motif") or ""), ""
    # Le motif rendu à la place de la phrase : on le reconnaît comme motif plutôt que
    # d'afficher ce mot nu à l'utilisateur.
    if refus in _REFUSAL_MESSAGES:
        motive, refus = refus, ""
    if motive and not refus:
        refus = _REFUSAL_MESSAGES.get(motive, "la base ne peut pas répondre")

    filled = [bool(sql), clarification is not None, bool(refus)]
    if sum(filled) != 1:
        return Generation(
            "panne",
            reason=f"le modèle a rempli {sum(filled)} branches sur trois ; une seule est "
                   "attendue",
        )
    if sql:
        return Generation("sql", sql=sql.rstrip(";").strip())
    if refus:
        motive = motive if motive in _REFUSAL_MESSAGES else "hors_schema"
        return Generation("refus", reason=refus, motive=motive)

    assert clarification is not None
    axes = clarification.get("axes")
    return Generation(
        "clarification",
        question=str(clarification.get("question") or "la question admet plusieurs lectures"),
        axes=tuple(str(axis) for axis in axes) if isinstance(axes, list) else (),
    )


class SqlGenerator:
    """Azure AI Foundry en OpenAI-compatible, API v1 — client construit paresseusement."""

    def __init__(self, endpoint: str, api_key: str, deployment: str) -> None:
        self.name = deployment
        #: Nombre de reprises demandées depuis la construction. Compté ici parce que c'est
        #: ici que le fait est connu : ni l'enveloppe ni le verdict ne le portent, et la
        #: mesure n'a pas à deviner ce qu'une passe a coûté.
        self.repairs = 0
        self._endpoint = endpoint
        self._api_key = api_key
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            self._client = build_azure_openai_client(
                self._endpoint, self._api_key,
                setting_name="LLM_CHAT_MODEL", fallback="aucune génération SQL",
            )
        return self._client

    def generate(self, question: str, contract: ReadContract,
                 axes: tuple[str, ...] = (),
                 rejected: tuple[str, str] | None = None) -> Generation:
        """Une passe, une décision. Rend une ``Generation``, jamais une exception sur le
        contenu de la réponse — une sortie hors format est la panne P1, pas un plantage.

        ``rejected`` porte ``(requête, erreur du moteur)`` d'une tentative que le contrôle 6
        a écartée : la passe devient alors une reprise. Une seule est jamais demandée, et
        seulement sur une requête **fausse** — jamais sur une requête interdite, qui ne se
        renégocie pas.
        """
        user = [f"Schéma et conventions :\n\n{contract.as_text()}"]
        if axes:
            user.append(
                "Axes de clarification disponibles (n'en proposer aucun autre) :\n"
                + "\n".join(f"  - {axis}" for axis in axes)
            )
        user.append(f"Question : {question}")
        if rejected is not None:
            self.repairs += 1
            previous, reason = rejected
            # L'erreur est donnée telle que le moteur l'a écrite : « no such function:
            # DATE_TRUNC » nomme la faute mieux qu'une reformulation, et le modèle sait
            # quoi en faire. Le périmètre n'est pas rappelé — il n'a pas été enfreint.
            user.append(
                "Cette requête a déjà été tentée et le moteur l'a refusée. La corriger,\n"
                "sans changer ce qu'elle cherche à répondre :\n"
                f"  requête : {previous}\n"
                f"  erreur  : {reason}\n"
                "N'employer que des fonctions que SQLite connaît."
            )
        # Pas de `temperature` : le déploiement en service refuse toute valeur autre que la
        # sienne (« Unsupported value: 'temperature' does not support 0 »), comportement des
        # modèles de raisonnement. La sortie est tenue par le format JSON imposé, pas par un
        # réglage d'échantillonnage.
        response = self._get_client().chat.completions.create(
            model=self.name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user)},
            ],
            response_format={"type": "json_object"},
        )
        return _parse(response.choices[0].message.content or "{}")


def build_generator(settings: Settings | None = None) -> SqlGenerator:
    """Rend le générateur configuré, ou dit ce qui manque pour l'avoir.

    Pas de repli local : il n'existe pas de modèle de génération SQL embarqué dans ce
    dépôt, et faire semblant d'en avoir un rendrait le refus indiscernable d'une réponse.
    """
    settings = settings or default_settings
    if not (settings.llm_chat_model and settings.azure_ai_endpoint):
        raise RuntimeError(
            "génération SQL indisponible : renseigner LLM_CHAT_MODEL et AZURE_AI_ENDPOINT"
        )
    return SqlGenerator(settings.azure_ai_endpoint, settings.azure_ai_api_key,
                        settings.llm_chat_model)
