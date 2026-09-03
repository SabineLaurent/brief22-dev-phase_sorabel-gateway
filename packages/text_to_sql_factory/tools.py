"""Les quatre tools SQL, en fonctions Python.

Elles rendent l'**enveloppe du contrat d'intégration** — ``{"status", "payload",
"message"}`` de ``docs/cadrage_dsi.md`` — et non l'``outputSchema`` d'union de la
conception. C'est l'arbitrage déjà consigné au journal : là où le dossier de conception et
les tests divergent, le test fait foi. Les douze codes ne sont pas perdus pour autant :
ils vivent dans ``payload["code"]``, où le chantier 3 les reprendra pour le journal.

Aucune de ces fonctions n'écrit au journal et aucune ne connaît de client : ce sont des
fonctions de bibliothèque. Elles rendent en revanche tout ce qu'il faut pour journaliser —
le code, la requête exécutée, le nombre de lignes, la latence.

Le paramètre ``profile`` est un argument **interne**. Il ne figure dans aucune signature
exposée : le serveur MCP le lira dans son environnement, jamais dans ce que le client
envoie — un paramètre présent dans l'``inputSchema`` serait rempli par le LLM du client.
"""

from __future__ import annotations

import re
from typing import Any

from config import Settings
from config import settings as default_settings
from packages.access import scope_for
from packages.text_to_sql_factory.access_sql import columns_outside_scope
from packages.text_to_sql_factory.contract import CONVENTIONS, build_read_contract
from packages.text_to_sql_factory.executor import Execution, execute, execute_with_parameters
from packages.text_to_sql_factory.generator import SqlGenerator, build_generator, clarification_axes
from packages.text_to_sql_factory.validator import validate

#: Des douze codes vers les cinq statuts du contrat DSI. C'est le seul endroit de la
#: conversion : un statut calculé ailleurs finirait par diverger.
#:
#: `aucune_ligne` et `ambiguite_donnees` sont des `ok` : le serveur a fait ce qu'on lui
#: demandait, et le résultat n'a rien donné ou plusieurs choses. Les marquer en refus ferait
#: compter au journal des refus qui n'ont jamais eu lieu, et la lecture d'E5 surestimerait
#: la sévérité du système.
_STATUS_BY_CODE = {
    "ok": "ok",
    "aucune_ligne": "ok",
    "ambiguite_donnees": "ok",
    "clarification": "clarification",
    "tool_interdit": "refused",
    "perimetre_interdit": "refused",
    "ecriture_refusee": "refused",
    "hors_schema": "refused",
    "erreur_execution": "error",
}

#: Ce à quoi une question fait allusion quand elle nomme une colonne sans la nommer.
#: Sert **après** un refus, jamais comme barrière : ce n'est pas une liste de mots interdits
#: — elle ne protège rien, elle qualifie. Sans elle, le support s'entend répondre « la base
#: ne porte pas cette donnée » là où la donnée existe et lui est seulement fermée : un refus
#: exact, mais un message faux, et l'utilisateur ne sait pas qu'il peut demander l'accès.
_COLUMN_HINTS: tuple[tuple[tuple[str, str], tuple[str, ...]], ...] = (
    (("produits", "prix_achat_ht"), ("prix d'achat", "prix achat", "cout d'achat",
                                     "coût d'achat", "achat fournisseur")),
    (("produits", "marge_pct"), ("marge", "marges", "marginalite", "marginalité")),
    (("ventes", "marge_ht"), ("marge", "marges")),
    (("clients", "email"), ("email", "e-mail", "courriel", "adresse mail")),
)

_REFERENCE = re.compile(r"^REF-\d{4}$")
_ORDER_ID = re.compile(r"^CMD-\d{4}-\d{4}$")

#: Les requêtes des deux tools figés, écrites et relues **une fois**. Leur périmètre se
#: vérifie à la revue de code, pas à chaque appel : c'est tout l'intérêt du figement.
_STOCK_SQL = (
    "SELECT s.entrepot, s.quantite, s.seuil_reappro, "
    "CASE WHEN s.quantite < s.seuil_reappro THEN 1 ELSE 0 END AS sous_seuil "
    "FROM stocks s WHERE s.ref = ? ORDER BY s.entrepot"
)
_ORDER_SQL = (
    "SELECT id, statut, date_commande, montant_ht, client_id "
    "FROM commandes WHERE id = ?"
)
#: Les colonnes que chaque tool figé touche — des lignes de la matrice, comme les autres.
_STOCK_COLUMNS = (("stocks", "ref"), ("stocks", "entrepot"), ("stocks", "quantite"),
                  ("stocks", "seuil_reappro"))
_ORDER_COLUMNS = (("commandes", "id"), ("commandes", "statut"), ("commandes", "date_commande"),
                  ("commandes", "montant_ht"), ("commandes", "client_id"))


def envelope(code: str, message: str = "", **payload: Any) -> dict[str, Any]:
    """Construit l'enveloppe. ``code`` est toujours dans le payload, y compris sur ``ok``.

    Le champ ``rows`` est **absent** de tout refus. C'est l'asymétrie qui fait le travail :
    un client qui lit le champ structuré n'a rien à afficher, donc il ne peut pas afficher
    un refus comme une réponse.
    """
    return {
        "status": _STATUS_BY_CODE.get(code, "error"),
        "payload": {"code": code, **payload},
        "message": message,
    }


def _denied_scope(profile: str, settings: Settings) -> dict[str, Any] | None:
    """Refus immédiat quand le profil n'a aucun périmètre — sans appeler le modèle.

    Un périmètre vide est un refus, jamais une intersection muette qui se lirait « rien à
    ce sujet ».
    """
    if scope_for(profile, settings).columns:
        return None
    return envelope(
        "perimetre_interdit",
        f"le profil « {profile} » n'a accès à aucune table de la base",
    )


def _from_execution(result: Execution, sql: str, conventions: tuple[str, ...] = (),
                    **extra: Any) -> dict[str, Any]:
    """Traduit un résultat d'exécution en enveloppe, requête comprise.

    La requête est renvoyée **systématiquement, pas sur demande** : c'est la garantie de
    transparence E3, et le test T1 la lit. Les conventions l'accompagnent — un chiffre de
    marge sans mention du sort des commandes annulées n'est pas vérifiable par le métier.
    """
    if result.code == "erreur_execution":
        return envelope("erreur_execution", result.message, sql=sql, latency_ms=result.latency_ms)
    payload: dict[str, Any] = {
        "sql": sql,
        "columns": list(result.columns),
        "rows": result.rows,
        "n_rows": result.n_rows,
        "latency_ms": result.latency_ms,
        **extra,
    }
    if conventions:
        payload["conventions"] = list(conventions)
    if result.truncated:
        payload["truncated"] = True
    return envelope(result.code, result.message, **payload)


def get_schema(profile: str, settings: Settings | None = None) -> dict[str, Any]:
    """Le contrat de lecture de la base, tel que ce profil a le droit de le voir.

    Aucun argument exposé. C'est **le même artefact** que celui injecté au prompt
    d'``ask_database`` : un client peut vouloir composer sa question en connaissance du
    schéma, sans déclencher de génération. Et c'est le tool qui rend le périmètre
    inspectable.
    """
    settings = settings or default_settings
    denied = _denied_scope(profile, settings)
    if denied is not None:
        return denied
    try:
        contract = build_read_contract(profile, settings)
    except RuntimeError as error:
        return envelope("erreur_execution", str(error))
    return envelope("ok", schema=contract.as_text())


def ask_database(question: str, profile: str, settings: Settings | None = None,
                 generator: SqlGenerator | None = None) -> dict[str, Any]:
    """Traduit une question métier en requête, la valide, l'exécute, et rend les deux.

    L'ordre compte, et il est celui du flux : la matrice borne le périmètre **avant** que le
    modèle ne soit appelé — il ne voit jamais une colonne interdite. Le contrôle d'AST
    rattrape ensuite ce qu'il aurait inventé hors du contrat.
    """
    settings = settings or default_settings
    denied = _denied_scope(profile, settings)
    if denied is not None:
        return denied
    try:
        contract = build_read_contract(profile, settings)
        generator = generator or build_generator(settings)
    except RuntimeError as error:
        return envelope("erreur_execution", str(error))

    axes = clarification_axes(profile, settings)
    try:
        generation = generator.generate(question, contract, axes)
    except Exception as error:  # noqa: BLE001 - toute panne du fournisseur est une erreur d'appel
        return envelope("erreur_execution", f"génération indisponible : {error}")

    if generation.branch == "panne":
        return envelope("erreur_execution", generation.reason)
    if generation.branch == "refus":
        if generation.motive == "ecriture":
            return envelope("ecriture_refusee", generation.reason)
        return _refusal_out_of_scope(question, profile, settings) or envelope(
            "hors_schema", generation.reason
        )
    if generation.branch == "clarification":
        return envelope("clarification", generation.question, axes=list(generation.axes))

    verdict = validate(generation.sql, profile, settings)
    if verdict.repairable:
        # Une reprise, une seule, et seulement sur une requête fausse : le contrôle 6 a dit
        # que le moteur la refuse, pas que la matrice l'interdit. Rendre l'erreur au modèle
        # rattrape ce qu'un refus sec ferait porter à l'utilisateur — une fonction Postgres
        # échappée du modèle n'est pas une question mal posée.
        try:
            repaired = generator.generate(question, contract, axes,
                                          rejected=(generation.sql, verdict.message))
        except Exception:  # noqa: BLE001 - la reprise est un bonus, sa panne n'en est pas une
            repaired = None
        if repaired is not None and repaired.branch == "sql" and repaired.sql:
            # Le second verdict repasse **tous** les contrôles, périmètre compris : la
            # reprise ne peut pas sortir de la matrice. Si elle échoue à son tour, c'est son
            # refus qui est rendu — pas celui de la première tentative, désormais périmé.
            generation = repaired
            verdict = validate(generation.sql, profile, settings)
    if not verdict.allowed:
        # La requête refusée n'est pas renvoyée : elle n'a pas été exécutée, et la montrer
        # comme « la requête qui a produit ce résultat » serait faux. Le motif, lui, nomme
        # la colonne en cause.
        payload = {"forbidden": [f"{t}.{c}" for t, c in verdict.forbidden]} if verdict.forbidden \
            else {}
        return envelope(verdict.code, verdict.message, **payload)

    return _from_execution(execute(verdict.sql, settings), verdict.sql, CONVENTIONS)


def _refusal_out_of_scope(question: str, profile: str,
                          settings: Settings) -> dict[str, Any] | None:
    """Requalifie en ``perimetre_interdit`` un refus qui porte sur une colonne fermée.

    Le modèle a refusé parce que la colonne n'était pas dans son contrat — il ne pouvait pas
    dire autre chose, et c'est voulu : il ne voit jamais une colonne interdite. Mais les deux
    refus n'appellent pas la même action de l'utilisateur. « Hors schéma » invite à
    reformuler ; « hors périmètre » invite à demander l'accès au profil correspondant. On
    refuse en nommant la colonne : lui apprendre que ``marge_pct`` existe est un moindre mal
    comparé à un refus qu'il ne peut pas comprendre.
    """
    allowed = scope_for(profile, settings).columns
    asked = question.lower()
    named = [
        column for column, hints in _COLUMN_HINTS
        if column not in allowed and any(hint in asked for hint in hints)
    ]
    if not named:
        return None
    listed = ", ".join(f"{table}.{column}" for table, column in sorted(set(named)))
    return envelope(
        "perimetre_interdit",
        f"ce profil n'a pas accès à : {listed}",
        forbidden=[f"{table}.{column}" for table, column in sorted(set(named))],
    )


def check_stock(reference: str, profile: str, settings: Settings | None = None) -> dict[str, Any]:
    """Le stock d'une référence, **entrepôt par entrepôt**, plus le total.

    Jamais un scalaire : 114 références sur 120 sont stockées dans plusieurs entrepôts, et
    l'oubli du ``SUM`` rend 247 au lieu de 774 — un nombre juste pour un entrepôt et faux
    pour la question, sans erreur SQL ni avertissement.

    ``sous_seuil`` est rendu **par ligne**, jamais agrégé : les seuils diffèrent par
    entrepôt (10 · 50 · 20 pour REF-8842), et un booléen global serait une information
    inventée.

    Le paramètre est une référence, **jamais un libellé** : 120 références pour 52 noms.
    La résolution nom → référence est le pont RAG ↔ SQL, en amont de ce tool.
    """
    settings = settings or default_settings
    denied = _denied_scope(profile, settings)
    if denied is not None:
        return denied
    if not _REFERENCE.match(reference or ""):
        # Un paramètre malformé n'est pas une requête à tenter. Ce n'est pas non plus un
        # refus de droit : l'appel est mal formé, et l'`inputSchema` MCP l'aura normalement
        # écarté avant l'envoi.
        return envelope(
            "erreur_execution",
            f"référence attendue au format REF-NNNN, reçu « {reference} »",
        )
    forbidden = _forbidden(profile, _STOCK_COLUMNS, settings)
    if forbidden is not None:
        return forbidden

    result = execute_with_parameters(_STOCK_SQL, (reference,), settings)
    total = sum(int(row[1]) for row in result.rows) if result.rows else 0  # quantite
    return _from_execution(result, _STOCK_SQL, total=total, reference=reference)


def order_status(order_id: str, profile: str, settings: Settings | None = None) -> dict[str, Any]:
    """L'en-tête d'une commande identifiée — le détail des lignes est un autre besoin.

    ``CMD-2026-0042`` n'existe pas : la numérotation est globale et trouée par année.
    Répondre « aucune ligne » est correct ; répondre « refusé » serait faux.
    """
    settings = settings or default_settings
    denied = _denied_scope(profile, settings)
    if denied is not None:
        return denied
    if not _ORDER_ID.match(order_id or ""):
        return envelope(
            "erreur_execution",
            f"identifiant attendu au format CMD-AAAA-NNNN, reçu « {order_id} »",
        )
    forbidden = _forbidden(profile, _ORDER_COLUMNS, settings)
    if forbidden is not None:
        return forbidden

    result = execute_with_parameters(_ORDER_SQL, (order_id,), settings)
    return _from_execution(result, _ORDER_SQL, order_id=order_id)


def _forbidden(profile: str, columns: tuple[tuple[str, str], ...],
               settings: Settings) -> dict[str, Any] | None:
    """Le figement ne dispense pas de la matrice : les colonnes de sortie d'un tool figé
    sont des lignes de la matrice comme les autres."""
    missing = columns_outside_scope(profile, set(columns), settings)
    if not missing:
        return None
    named = ", ".join(f"{table}.{column}" for table, column in missing)
    return envelope("perimetre_interdit", f"ce profil n'a pas accès à : {named}")
