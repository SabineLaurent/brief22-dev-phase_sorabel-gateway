"""Contrôles d'intégrité de l'index documentaire.

À lancer après `python -m ingest.cli`. Vérifie ce que l'ingestion prétend avoir
produit, directement dans Chroma — pas dans les objets Python qui l'ont écrit.
"""

from __future__ import annotations

import re
import sys
from collections import Counter

from config import settings
from ingest.index import connect, get_collection
from retrieval.embedder import build_embedder

_ID_PATTERN = re.compile(r"^(fiches|notices|sav|notes)/[A-Za-z0-9._-]+$")
_EXPECTED_BY_DOC_TYPE = {
    "fiche_technique": 150,
    "notice": 80,
    "procedure_sav": 90,
    "note_interne": 80,
}
#: Clés de données imposées par le contrat — volontairement pas des noms Python.
_REQUIRED_FIELDS = (
    "edition_id", "doc_key", "is_current", "titre",
    "version", "date", "doc_type", "url", "n_caracteres",
)


def main() -> int:
    collection = get_collection(connect(settings), build_embedder(settings), settings)
    batch = collection.get(include=["metadatas"])
    metadatas = [dict(entry) for entry in (batch.get("metadatas") or [])]

    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        print(f"  [{mark}] {label:<34} {actual!r} (attendu {expected!r})")
        if actual != expected:
            failures.append(label)

    print("Index :", settings.chroma_collection, "sur", settings.chroma_url)
    print("\nVolumétrie")
    check("éditions indexées", len(metadatas), 400)
    check("éditions courantes", sum(1 for m in metadatas if m["is_current"]), 350)
    check("documents distincts", len({m["doc_key"] for m in metadatas}), 350)

    print("\nRépartition par doc_type")
    by_doc_type = Counter(m["doc_type"] for m in metadatas)
    for doc_type, expected in sorted(_EXPECTED_BY_DOC_TYPE.items()):
        check(doc_type, by_doc_type.get(doc_type, 0), expected)

    print("\nChamps optionnels — la clé est omise, jamais vide")
    check("reference présente", sum(1 for m in metadatas if "reference" in m), 230)
    check("theme présent", sum(1 for m in metadatas if "theme" in m), 80)
    empty = [m["edition_id"] for m in metadatas if any(v == "" or v is None for v in m.values())]
    check("métadonnées vides ou nulles", len(empty), 0)

    print("\nForme")
    all_scalar = all(
        isinstance(value, (str, int, float, bool)) for m in metadatas for value in m.values()
    )
    check("toutes les valeurs scalaires", all_scalar, True)
    check(
        "champs obligatoires présents",
        all(field in m for m in metadatas for field in _REQUIRED_FIELDS),
        True,
    )
    malformed = [
        m["edition_id"]
        for m in metadatas
        if not (_ID_PATTERN.match(str(m["edition_id"])) and _ID_PATTERN.match(str(m["doc_key"])))
    ]
    check("identifiants au bon motif", len(malformed), 0)
    check(
        "n_caracteres dans la fenêtre du modèle",
        max(int(m["n_caracteres"]) for m in metadatas) <= 923,
        True,
    )

    print("\nVersions — REF-8842 (le cas du test d'acceptance)")
    ref_8842 = sorted(
        (str(m["edition_id"]), str(m["version"]), bool(m["is_current"]), str(m["doc_type"]))
        for m in metadatas
        if m.get("reference") == "REF-8842"
    )
    for edition_id, version, current, doc_type in ref_8842:
        print(f"    {edition_id:<38} v{version}  courante={current}  {doc_type}")
    check("éditions portant REF-8842", len(ref_8842), 3)
    check(
        "fiche courante = v2.1",
        next((v for _, v, current, t in ref_8842 if t == "fiche_technique" and current), None),
        "2.1",
    )

    print("\nInvariant de version — aucune v1.0 courante là où une v2 existe")
    versions_by_document: dict[str, list[tuple[str, bool]]] = {}
    for m in metadatas:
        versions_by_document.setdefault(str(m["doc_key"]), []).append(
            (str(m["version"]), bool(m["is_current"]))
        )
    multi = {k: v for k, v in versions_by_document.items() if len(v) > 1}
    offenders = [
        doc_key
        for doc_key, versions in multi.items()
        if max(versions, key=lambda x: tuple(int(n) for n in x[0].split(".")))[1] is not True
    ]
    check("documents à deux éditions", len(multi), 50)
    check("documents dont la courante n'est pas la plus haute", len(offenders), 0)

    print()
    if failures:
        print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
        return 1
    print("Tous les contrôles passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
