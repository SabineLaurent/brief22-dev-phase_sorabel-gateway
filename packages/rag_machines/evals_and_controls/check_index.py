"""Contrôles d'intégrité de l'index documentaire.

À lancer après `python -m packages.rag_machines.ingest.cli`. Vérifie ce que l'ingestion prétend avoir
produit, directement dans Chroma — pas dans les objets Python qui l'ont écrit.

Un contrôle qui plante ne contrôle rien. Ce script est écrit pour **rapporter**
les index qu'il doit attraper — vide, incomplet, mal formé — et non pour lever
une exception dessus : c'est précisément sur ces index-là qu'on a besoin de lire
sa sortie.
"""

from __future__ import annotations

import re
import sys
from collections import Counter

from chromadb.api.types import IncludeEnum

from config import settings
from packages.rag_machines.ingest.index import collection_name, connect, get_collection
from packages.rag_machines.ingest.registry import version_sort_key
from packages.rag_machines.retrieval.embedder import build_embedder

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
#: Fenêtre du modèle d'embeddings, en caractères.
_MAX_CHARS = 923


def main() -> int:
    try:
        collection = get_collection(connect(settings), build_embedder(settings), settings)
    except (RuntimeError, ValueError) as error:
        print(f"Index illisible : {error}", file=sys.stderr)
        return 1
    # `IncludeEnum.metadatas` plutôt que la chaîne : c'est ce que le SDK typé attend, et
    # ici la collection est typée — ailleurs dans le dépôt elle passe par un `get_collection`
    # non annoté, ce qui masque l'écart sans le corriger.
    batch = collection.get(include=[IncludeEnum.metadatas])
    metadatas = [dict(entry) for entry in (batch.get("metadatas") or [])]

    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        print(f"  [{mark}] {label:<34} {actual!r} (attendu {expected!r})")
        if actual != expected:
            failures.append(label)

    def verdict() -> int:
        print()
        if failures:
            print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
            return 1
        print("Tous les contrôles passent.")
        return 0

    print("Index :", collection_name(settings), "sur", settings.chroma_url)
    print("\nVolumétrie")
    check("éditions indexées", len(metadatas), 400)
    if not metadatas:
        print("\nIndex vide : les contrôles suivants sont sans objet. Lancer `make ingest`.")
        return verdict()

    # Les contrôles qui lisent un champ ne portent que sur les entrées qui le
    # portent : une métadonnée manquante doit ressortir en échec ci-dessous, pas
    # en KeyError au premier accès.
    complete: list[dict] = []
    incomplete: list[dict] = []
    for m in metadatas:
        (complete if all(field in m for field in _REQUIRED_FIELDS) else incomplete).append(m)

    check("éditions courantes", sum(1 for m in complete if m["is_current"]), 350)
    check("documents distincts", len({m["doc_key"] for m in complete}), 350)

    print("\nRépartition par doc_type")
    by_doc_type = Counter(m["doc_type"] for m in complete)
    for doc_type, expected in sorted(_EXPECTED_BY_DOC_TYPE.items()):
        check(doc_type, by_doc_type.get(doc_type, 0), expected)

    print("\nChamps optionnels — la clé est omise, jamais vide")
    check("reference présente", sum(1 for m in metadatas if "reference" in m), 230)
    check("theme présent", sum(1 for m in metadatas if "theme" in m), 80)
    empty = [m for m in metadatas if any(v == "" or v is None for v in m.values())]
    check("métadonnées vides ou nulles", len(empty), 0)

    print("\nForme")
    all_scalar = all(
        isinstance(value, (str, int, float, bool)) for m in metadatas for value in m.values()
    )
    check("toutes les valeurs scalaires", all_scalar, True)
    check("champs obligatoires présents", len(incomplete), 0)
    if incomplete:
        print(f"    {len(incomplete)} entrée(s) incomplète(s), écartée(s) des contrôles de champ")
    malformed = [
        m["edition_id"]
        for m in complete
        if not (_ID_PATTERN.match(str(m["edition_id"])) and _ID_PATTERN.match(str(m["doc_key"])))
    ]
    check("identifiants au bon motif", len(malformed), 0)
    char_counts = [m["n_caracteres"] for m in complete if isinstance(m["n_caracteres"], int)]
    check(
        "n_caracteres dans la fenêtre du modèle",
        len(char_counts) == len(complete) and max(char_counts, default=0) <= _MAX_CHARS,
        True,
    )

    print("\nVersions — REF-8842 (le cas du test d'acceptance)")
    ref_8842 = sorted(
        (str(m["edition_id"]), str(m["version"]), bool(m["is_current"]), str(m["doc_type"]))
        for m in complete
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
    for m in complete:
        versions_by_document.setdefault(str(m["doc_key"]), []).append(
            (str(m["version"]), bool(m["is_current"]))
        )
    multi = {k: v for k, v in versions_by_document.items() if len(v) > 1}
    # Même classement que l'ingestion, importé et non réécrit : deux tris
    # différents feraient dénoncer au contrôle un coupable qui n'en est pas un.
    offenders = [
        doc_key
        for doc_key, versions in multi.items()
        if max(versions, key=lambda x: version_sort_key(x[0]))[1] is not True
    ]
    check("documents à deux éditions", len(multi), 50)
    check("documents dont la courante n'est pas la plus haute", len(offenders), 0)

    return verdict()


if __name__ == "__main__":
    sys.exit(main())
