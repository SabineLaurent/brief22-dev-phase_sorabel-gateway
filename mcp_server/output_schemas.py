"""L'``outputSchema`` des huit tools : le contrat de réponse, déclaré au protocole.

`tools/list` est au serveur MCP ce que `/openapi.json` est à une API REST, à une différence
près qui est tout l'intérêt : ce n'est pas un fichier maintenu à côté du code, c'est une
méthode **du** serveur. Chez nous, `SorabelMCP.list_tools` en fait même l'expression de la
matrice — le catalogue publié *est* le droit d'accès, il n'en est pas une copie.

**Pourquoi ces schémas sont écrits à la main et non dérivés d'un type.** FastMCP dérive
l'``outputSchema`` de l'annotation de retour, et le décorateur n'accepte pas de schéma
explicite. Mais un type de retour joue **deux** rôles : il décrit la sortie *et* il la
filtre, par ``model_validate`` puis ``model_dump``. Un type plus étroit que le dictionnaire
rendu fait donc **diverger les deux moitiés de la réponse** — mesuré : ``content[0].text``
est sérialisé depuis le dictionnaire brut et garde la clé, ``structuredContent`` la perd en
silence. Or le payload servi est un **surensemble** du cadrage : ``code`` partout,
``conventions`` et ``truncated`` sur ``ask_database``, cinq clés de citation là où le
cadrage en nomme trois. Un schéma calqué sur le cadrage serait plus étroit que le servi.

D'où le partage : le type de retour reste ``dict[str, Any]``, donc il ne filtre rien ; et le
schéma publié est réécrit dans ``list_tools``, là où le catalogue est déjà décidé.

**Trois règles de forme, et chacune évite une panne précise.**

* ``status`` porte une énumération, et elle est **calculée** depuis les tables de statuts des
  domaines. Un enum recopié dériverait le jour où un domaine gagne un statut ; celui-ci ne
  peut pas, il *est* la table. C'est aussi la seule contrainte forte de ces schémas — le
  serveur refuse la sortie qui la viole, et cette sévérité-là est voulue ;
* ``payload.code`` est **décrit sans énumération**. Un enum incomplet transformerait une
  réponse valide en panne, et les codes ne sont pas relevables par lecture : côté RAG
  ``perimetre_interdit`` passe par une constante, côté SQL ``aucune_ligne`` et
  ``ambiguite_donnees`` sont propagés depuis le résultat d'exécution. C'est la même forme
  d'arbitrage que ``collections`` exposé sans ``enum`` — décrire sans contraindre ;
* **aucun schéma ne ferme ``additionalProperties``**. Un objet fermé refuserait les clés que
  le schéma ne nomme pas — donc ``conventions`` et ``truncated`` aujourd'hui, et la première
  clé ajoutée demain. Le schéma dit ce qu'un client peut lire, jamais ce qu'il recevra seul.

Ce qui n'est **pas** repris de ``03-catalogue-tools.md`` §4 : le champ ``hint``, jamais servi
et absent du cadrage — sa fonction est tenue par les descriptions des tools, qui nomment
déjà le recours ; et ``isError`` tranché code par code — le serveur ne le pose que sur une
violation de schéma, et le discriminant du client reste ``status``, puis ``payload.code``.
"""

from __future__ import annotations

from typing import Any

from packages.rag_machines.structured_answer import RAG_STATUS_BY_CODE
from packages.text_to_sql_factory.structured_answer import DB_STATUS_BY_CODE

__all__ = ["OUTPUT_SCHEMAS", "status_enum"]

#: Le repli des deux domaines : un code inconnu de la table vaut ``error``. Il appartient
#: donc à l'énumération même s'il n'est écrit dans aucune des deux.
_FALLBACK_STATUS = "error"


def status_enum(*tables: dict[str, str]) -> list[str]:
    """Les statuts qu'un domaine peut réellement émettre, **lus dans sa table**.

    Ni recopiés ni devinés : c'est ``status`` qui est calculé par
    ``TABLE.get(self.code, "error")``, et cette fonction lit la même table. Un statut ajouté
    à un domaine apparaît donc au schéma sans qu'on y touche, et le contrôle de contrat
    confronte les deux pour que ce lien ne se défasse pas en silence.
    """
    values = {value for table in tables for value in table.values()}
    return sorted(values | {_FALLBACK_STATUS})


#: Ce que chaque statut veut dire. La description publiée n'en retient que les statuts
#: réellement atteignables par le tool : les deux domaines n'émettent pas les mêmes, et
#: décrire ``clarification`` sur un tool documentaire — qui ne l'émet jamais — inviterait un
#: client à prévoir une branche morte.
_STATUS_MEANING = {
    "ok": "« ok » : servi.",
    "refused": "« refused » : la gouvernance a tranché.",
    "clarification": "« clarification » : la question admet plusieurs lectures.",
    "hors_corpus": ("« hors_corpus » : le corpus ne porte pas la réponse — ce n'est pas un "
                    "refus."),
    "error": "« error » : l'exécution a échoué.",
}


def _envelope(statuses: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    """Le socle des huit schémas : l'enveloppe de ``docs/cadrage_dsi.md``.

    Les trois clés sont requises, et elles le sont vraiment : ``client_view()`` et
    ``rag_client_view()`` les écrivent toutes les trois, en dur, sans branche qui en omette
    une. Le schéma ne fait donc que publier une garantie déjà tenue.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "description": (
            "Enveloppe de réponse de la gateway Sorabel. Le discriminant est « status », "
            "puis « payload.code » qui distingue les cas d'un même statut. Ne jamais "
            "rendre à l'utilisateur un payload dont la clé de charge utile est absente : "
            "c'est un refus ou une non-réponse, et il n'y a rien à afficher."
        ),
        "required": ["status", "payload", "message"],
        "properties": {
            "status": {
                "type": "string",
                "enum": statuses,
                "description": "L'issue de l'appel. " + " ".join(
                    _STATUS_MEANING[status] for status in statuses
                ),
            },
            "payload": payload,
            "message": {
                "type": "string",
                "description": (
                    "Phrase figée choisie sur le code, destinée à l'utilisateur. Vide sur "
                    "« ok », non vide sur tout autre statut. Elle ne contient jamais de "
                    "texte de modèle, de message de moteur ni de nom d'interne."
                ),
            },
        },
    }


#: La clé présente dans **tous** les payloads, servis comme refusés. Sans énumération :
#: cf. la deuxième règle de forme dans la docstring du module.
_CODE: dict[str, Any] = {
    "type": "string",
    "description": (
        "Le cas précis, plus fin que « status ». Toujours présent. Douze valeurs, dont "
        "quatre refus : tool_interdit, perimetre_interdit, ecriture_refusee, hors_schema. "
        "Les autres : ok, aucune_ligne, introuvable, ambiguite_donnees, clarification, "
        "hors_corpus, contexte_insuffisant, erreur_execution."
    ),
}

#: Une citation, telle que ``citation()`` la construit — cinq clés, toutes des chaînes.
#: ``reference`` est garantie non vide : elle retombe sur ``doc_key`` pour les éditions qui
#: ne portent pas de référence produit, ce qu'exige le test T1 sur une procédure SAV.
_CITATION: dict[str, Any] = {
    "type": "object",
    "required": ["titre", "reference", "version", "date", "doc_key"],
    "properties": {
        "titre": {"type": "string"},
        "reference": {
            "type": "string",
            "description": (
                "Référence produit (REF-XXXX), ou le doc_key quand l'édition n'en porte "
                "pas. Jamais vide. Construite en Python depuis les métadonnées, jamais "
                "rédigée par le modèle."
            ),
        },
        "version": {"type": "string"},
        "date": {"type": "string"},
        "doc_key": {
            "type": "string",
            "description": "Permet de rappeler l'édition par get_document.",
        },
    },
}

_METADATA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Métadonnées de l'édition, telles qu'indexées : edition_id, doc_key, is_current, "
        "titre, version, date, doc_type, url, n_caracteres, puis reference et theme quand "
        "l'édition en porte."
    ),
}

_RAG_STATUSES = status_enum(RAG_STATUS_BY_CODE)
_SQL_STATUSES = status_enum(DB_STATUS_BY_CODE)


def _payload(**properties: Any) -> dict[str, Any]:
    """Un payload : ``code`` requis, le reste optionnel et **absent** quand il n'y a rien.

    C'est l'asymétrie qui fait le travail de sécurité, et le seul endroit du contrat où elle
    est visible d'un client : sur un refus ou une non-réponse, la clé de charge utile n'est
    pas vide, elle n'est **pas là**. Un client n'a donc rien à afficher, et il ne peut pas
    rendre un refus comme une réponse en oubliant d'y penser.
    """
    return {
        "type": "object",
        "required": ["code"],
        "properties": {"code": _CODE, **properties},
    }


#: Par tool, le schéma publié dans ``tools/list``. Les clés décrites sont celles que la
#: liste blanche ``PAYLOAD_KEPT`` de chaque domaine laisse passer — pas celles du cadrage,
#: qui en énumère moins que le code n'en sert.
OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "answer_question": _envelope(
        _RAG_STATUSES,
        _payload(
            answer={
                "type": "string",
                "description": (
                    "La réponse rédigée à partir des seuls extraits fournis. ABSENTE dès "
                    "que code n'est pas ok — sur hors_corpus et contexte_insuffisant, il "
                    "n'y a rien à afficher, et c'est ce qui tient la garantie de "
                    "non-invention."
                ),
            },
            sources={
                "type": "array",
                "items": _CITATION,
                "description": (
                    "Les documents effectivement utilisés. Construites en Python depuis "
                    "les métadonnées : le modèle ne rend que les numéros des extraits, il "
                    "n'écrit aucune référence et ne peut donc pas en inventer."
                ),
            },
        ),
    ),
    "search_docs": _envelope(
        _RAG_STATUSES,
        _payload(
            hits={
                "type": "array",
                "description": (
                    "Les extraits classés, sans rédaction. Aucun seuil de refus ici : le "
                    "client compose lui-même, donc c'est à lui de juger. Une recherche "
                    "sans résultat rend aucune_ligne, pas un refus."
                ),
                "items": {
                    "type": "object",
                    "required": ["doc_id", "score", "text", "metadata"],
                    "properties": {
                        "doc_id": {"type": "string"},
                        "score": {
                            "type": "number",
                            "description": (
                                "Sur l'échelle du reranker, non comparable à celle d'un "
                                "autre étage de recherche."
                            ),
                        },
                        "text": {"type": "string"},
                        "metadata": _METADATA,
                    },
                },
            }
        ),
    ),
    "get_document": _envelope(
        _RAG_STATUSES,
        _payload(
            text={
                "type": "string",
                "description": "Le texte intégral de l'édition, liens sortants compris.",
            },
            metadata=_METADATA,
        ),
    ),
    "list_sources": _envelope(
        _RAG_STATUSES,
        _payload(
            sources={
                "type": "array",
                "description": (
                    "L'inventaire du corpus, tel que ce profil a le droit de le voir : les "
                    "effectifs annoncés sont exactement ceux qu'une recherche peut "
                    "atteindre. Éditions courantes seulement."
                ),
                "items": {
                    "type": "object",
                    "required": [
                        "doc_id", "doc_type", "titre", "reference", "version", "date",
                        "doc_key",
                    ],
                    "properties": {
                        "doc_id": {"type": "string"},
                        "doc_type": {
                            "type": "string",
                            "description": (
                                "fiche_technique | notice | procedure_sav | note_interne"
                            ),
                        },
                        **_CITATION["properties"],
                    },
                },
            }
        ),
    ),
    "ask_database": _envelope(
        _SQL_STATUSES,
        _payload(
            sql={
                "type": "string",
                "description": (
                    "La requête réellement exécutée, rendue pour que le chiffre soit "
                    "vérifiable. Lecture seule, validée avant exécution."
                ),
            },
            columns={"type": "array", "items": {"type": "string"}},
            rows={
                "type": "array",
                "items": {"type": "array"},
                "description": "Les lignes, dans l'ordre des colonnes. Bornées.",
            },
            conventions={
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Les conventions de calcul appliquées, sans lesquelles un chiffre de "
                    "marge n'est pas interprétable."
                ),
            },
            truncated={
                "type": "boolean",
                "description": "Présent et vrai quand le plafond de lignes a coupé.",
            },
            axes={
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Sur clarification : entre quoi l'utilisateur doit choisir. Les axes "
                    "proposés sont bornés par le périmètre du profil."
                ),
            },
        ),
    ),
    "get_schema": _envelope(
        _SQL_STATUSES,
        _payload(
            schema={
                "type": "string",
                "description": (
                    "Le contrat de lecture, **filtré par le profil** : les colonnes "
                    "fermées n'y figurent pas. C'est le pendant SQL de list_sources — il "
                    "rend le périmètre inspectable avant la question."
                ),
            }
        ),
    ),
    "check_stock": _envelope(
        _SQL_STATUSES,
        _payload(
            sql={"type": "string"},
            columns={"type": "array", "items": {"type": "string"}},
            rows={"type": "array", "items": {"type": "array"}},
            total={"type": "integer", "description": "Le stock total pour la référence."},
            reference={"type": "string", "description": "La référence interrogée."},
            truncated={"type": "boolean"},
        ),
    ),
    "order_status": _envelope(
        _SQL_STATUSES,
        _payload(
            sql={"type": "string"},
            columns={"type": "array", "items": {"type": "string"}},
            rows={"type": "array", "items": {"type": "array"}},
            order_id={"type": "string", "description": "La commande interrogée."},
            truncated={"type": "boolean"},
        ),
    ),
}
