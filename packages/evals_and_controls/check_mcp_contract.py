"""Contrôles du contrat publié : ce que ``tools/list`` promet, et ce que les tools rendent.

**Le premier contrôle du serveur MCP lui-même.** Les quatre suites existantes — ``check-sql``,
``check-feedback``, ``check-rag-tools``, ``check-perimetre`` — portent toutes sur les couches
*en dessous* du protocole. Le catalogue publié n'était vu que par ``eval_access.py``, et
seulement en décompte.

Ce contrôle existe pour une raison précise. Les ``outputSchema`` de ``mcp_server`` sont
**écrits à la main** : c'est le seul moyen de décrire le payload, puisque FastMCP ne sait
dériver un schéma que d'un type de retour — et qu'un type de retour ne se contente pas de
décrire la sortie, il la filtre. Le prix de ce choix est qu'un schéma écrit est une source de
vérité **séparée du code**, donc capable de dériver. C'est ce contrôle qui l'ancre.

Il porte quatre choses, et la deuxième est celle qu'aucun schéma ne peut se donner à
lui-même :

1. **Le schéma est publié, et il a la forme du cadrage** — les trois clés requises, ``code``
   requis dans le payload. Le ``is not None`` compte autant que le reste : FastMCP renonce en
   silence quand une dérivation échoue, et un schéma perdu ne se voit nulle part.
2. **L'énumération des statuts est celle des tables de domaine.** Elle est calculée par
   ``status_enum()``, mais un contrôle qui relit la table attrape le jour où quelqu'un
   remplacerait ce calcul par une liste écrite. C'est la seule contrainte **dure** de ces
   schémas : le serveur refuse une sortie qui la viole, et la refuse en rendant un bloc texte
   qui n'est pas du JSON — ce que les trois clients du dépôt passent à ``json.loads``.
3. **Les enveloppes réelles des dix-sept codes valident contre le schéma publié.** Pas des
   enveloppes reconstituées : celles que ``client_view()`` et ``rag_client_view()`` rendent.
4. **Deux contrôles négatifs**, qui prouvent que le schéma mord et qu'il ne mord pas trop :
   un statut inventé est refusé, et aucun schéma ne ferme ``additionalProperties`` — un objet
   fermé refuserait ``conventions`` et ``truncated``, que le payload sert et que le schéma ne
   nomme pas tous.

**Aucun appel de modèle, aucun accès à Chroma, à SQLite ou au journal du dépôt.** Tout est de
la construction et de la sérialisation ; le seul contact avec le serveur est ``tools/list``,
qui ne touche à rien.

Un contrôle qui plante ne contrôle rien : le script **rapporte** ses verdicts, y compris
quand ils sont faux.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from typing import Any

import jsonschema

from config import Settings
from config import settings as base_settings
from mcp_server.output_schemas import OUTPUT_SCHEMAS, status_enum
from packages.access import load_matrix
from packages.rag_machines.structured_answer import (
    RAG_CLIENT_MESSAGES,
    RAG_STATUS_BY_CODE,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    DB_STATUS_BY_CODE,
    build_db_structured_answer,
    client_view,
)

#: Les trois clés du contrat d'intégration, et elles seules.
DSI_KEYS = ["message", "payload", "status"]

#: Une clé de message qui n'est **pas** un code : elle choisit une phrase, elle ne paraît
#: jamais dans ``payload["code"]``, qui vaut alors ``erreur_execution``. Les deux tables de
#: messages la portent, les deux tables de statuts non — d'où l'écart de un entre elles.
MESSAGE_ONLY = "argument_malforme"

#: Les quatre tools de chaque domaine. Le schéma d'un tool documentaire n'énumère pas les
#: mêmes statuts que celui d'un tool SQL — c'est le point que le contrôle 2 vérifie.
RAG_TOOLS = ("answer_question", "search_docs", "get_document", "list_sources")
SQL_TOOLS = ("ask_database", "get_schema", "check_stock", "order_status")

#: Une charge de payload par code, prise sur les clés que les tools posent réellement. Elle
#: est volontairement **plus large** que ce qu'un tool donné sert : la liste blanche
#: ``PAYLOAD_KEPT`` est par *code* et commune aux quatre tools d'un domaine, donc c'est bien
#: cette union-là que le schéma doit accepter.
CHARGES: dict[str, dict[str, Any]] = {
    "ok": {"sql": "SELECT 1", "columns": ["a"], "rows": [[1]], "answer": "x",
           "sources": [], "hits": [], "text": "x", "metadata": {}, "schema": "s",
           "total": 1, "reference": "REF-8842", "order_id": "CMD-2024-0001",
           "conventions": ["c"], "truncated": True, "entries": [{"a": 1}]},
    "aucune_ligne": {"sql": "SELECT 1", "columns": [], "rows": [], "hits": [],
                     "sources": []},
    "ambiguite_donnees": {"sql": "SELECT 1", "columns": [], "rows": [[1], [2]]},
    "clarification": {"axes": ["par mois", "par région"]},
}


def _catalogue(profile: str) -> list[Any]:
    """Le catalogue publié à ce profil, **relu du serveur**.

    Le serveur lit ``SORABEL_PROFILE`` une fois au chargement — c'est ce qui rend le profil
    inaccessible au client — donc un seul processus ne peut pas interroger deux catalogues
    sans relancer le module. Même motif que ``eval_access._catalogue_sizes()``.
    """
    previous = os.environ.get("SORABEL_PROFILE")
    try:
        os.environ["SORABEL_PROFILE"] = profile
        sys.modules.pop("mcp_server.server", None)
        server = importlib.import_module("mcp_server.server")
        return list(asyncio.run(server.mcp.list_tools()))
    finally:
        sys.modules.pop("mcp_server.server", None)
        if previous is None:
            os.environ.pop("SORABEL_PROFILE", None)
        else:
            os.environ["SORABEL_PROFILE"] = previous


def main() -> int:
    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        rendered = repr(actual)
        if len(rendered) > 70:
            rendered = rendered[:67] + "..."
        print(f"  [{mark}] {label:<56} {rendered}")
        if actual != expected:
            failures.append(label)

    def verdict() -> int:
        print()
        if failures:
            print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
            return 1
        print("Tous les contrôles passent.")
        return 0

    return _run(base_settings, check, verdict)


def _run(settings: Settings, check, verdict) -> int:  # noqa: ANN001 - deux fermetures locales
    print("Catalogue des schémas")
    check("un schéma par tool du catalogue", sorted(OUTPUT_SCHEMAS),
          sorted(RAG_TOOLS + SQL_TOOLS))
    # Le catalogue des schémas et celui de la matrice doivent porter les mêmes noms : un tool
    # ajouté à la matrice sans schéma ferait lever un KeyError dans `list_tools`, donc à
    # l'initialisation d'une session — un plantage au pire moment, et loin de sa cause.
    matrix = load_matrix(settings)
    declared = {tool for scope in matrix.values() for tool in scope.tools}
    check("aucun tool de la matrice sans schéma",
          sorted(declared - set(OUTPUT_SCHEMAS) - {settings.journal_reader_tool}), [])

    print("\nLe schéma publié, tel que tools/list le rend")
    listed = {tool.name: tool for tool in _catalogue("commercial")}
    check("le profil commercial voit les huit tools", len(listed), 8)
    for name in RAG_TOOLS + SQL_TOOLS:
        schema = listed[name].outputSchema
        # FastMCP renonce en silence quand une dérivation échoue (`logger.info`, puis
        # `outputSchema` à None) : l'absence se contrôle donc explicitement.
        check(f"{name} — schéma publié", schema is not None, True)
        check(f"{name} — les trois clés du DSI requises",
              sorted(schema["required"]), DSI_KEYS)
        check(f"{name} — code requis dans le payload",
              schema["properties"]["payload"]["required"], ["code"])

    print("\nL'énumération des statuts vient de la table du domaine")
    # Le seul contrôle qu'un schéma ne peut pas se donner à lui-même. `status` est calculé
    # par `TABLE.get(code, "error")` ; si l'énumération publiée cessait de suivre la table,
    # un statut légitime deviendrait une violation de schéma — donc un `isError` et un bloc
    # texte non-JSON, sur un appel qui s'est déroulé normalement.
    check("les quatre tools documentaires",
          {name: listed[name].outputSchema["properties"]["status"]["enum"]
           for name in RAG_TOOLS},
          {name: status_enum(RAG_STATUS_BY_CODE) for name in RAG_TOOLS})
    check("les quatre tools SQL",
          {name: listed[name].outputSchema["properties"]["status"]["enum"]
           for name in SQL_TOOLS},
          {name: status_enum(DB_STATUS_BY_CODE) for name in SQL_TOOLS})
    # Et les deux domaines n'émettent pas les mêmes : un schéma unique aurait publié
    # `clarification` sur un tool documentaire qui ne l'émet jamais.
    check("les deux domaines diffèrent",
          status_enum(RAG_STATUS_BY_CODE) == status_enum(DB_STATUS_BY_CODE), False)
    check("hors_corpus n'est promis que côté documentaire",
          "hors_corpus" in status_enum(DB_STATUS_BY_CODE), False)
    check("clarification n'est promise que côté SQL",
          "clarification" in status_enum(RAG_STATUS_BY_CODE), False)

    print("\nLes enveloppes réelles des dix-sept codes, contre le schéma publié")
    # Les deux domaines sont parcourus séparément : leurs constructeurs et leurs
    # sérialiseurs ne sont pas interchangeables, et les apparier dans une seule boucle les
    # rendrait indistinguables au typeur comme au lecteur.
    served_by_code: list[tuple[str, str, dict[str, Any]]] = [
        ("SQL", code, client_view(build_db_structured_answer(code, **CHARGES.get(code, {}))))
        for code in sorted(CLIENT_MESSAGES) if code != MESSAGE_ONLY
    ] + [
        ("RAG", code,
         rag_client_view(build_rag_structured_answer(code, **CHARGES.get(code, {}))))
        for code in sorted(RAG_CLIENT_MESSAGES) if code != MESSAGE_ONLY
    ]
    check("dix-sept codes, neuf côté SQL et huit côté RAG", len(served_by_code), 17)
    for label, code, served in served_by_code:
        check(f"{label} {code} — trois clés servies", sorted(served), DSI_KEYS)
        for name in (SQL_TOOLS if label == "SQL" else RAG_TOOLS):
            try:
                jsonschema.validate(instance=served, schema=listed[name].outputSchema)
                valid: object = True
            except jsonschema.ValidationError as error:
                valid = str(error).splitlines()[0]
            check(f"{label} {code} — valide pour {name}", valid, True)

    print("\nCe que le schéma refuse, et ce qu'il doit laisser passer")
    schema = listed["answer_question"].outputSchema
    invented = {"status": "inconnu", "payload": {"code": "ok"}, "message": ""}
    try:
        jsonschema.validate(instance=invented, schema=schema)
        refused = False
    except jsonschema.ValidationError:
        refused = True
    check("un statut inventé est refusé", refused, True)
    # Un objet fermé refuserait les clés que le schéma ne nomme pas — `conventions` et
    # `truncated` aujourd'hui, la première ajoutée demain. Le schéma dit ce qu'un client
    # peut lire, jamais ce qu'il recevra seul.
    check("aucun schéma ne ferme additionalProperties",
          [name for name, published in OUTPUT_SCHEMAS.items()
           if "false" in json.dumps(published.get("properties", {}))
           or published.get("additionalProperties") is False], [])
    surplus = client_view(build_db_structured_answer(
        "ok", sql="SELECT 1", columns=[], rows=[], conventions=["c"], truncated=True))
    try:
        jsonschema.validate(instance=surplus, schema=listed["ask_database"].outputSchema)
        accepted: object = True
    except jsonschema.ValidationError as error:
        accepted = str(error).splitlines()[0]
    check("les clés hors cadrage passent", accepted, True)

    return verdict()


if __name__ == "__main__":
    sys.exit(main())
