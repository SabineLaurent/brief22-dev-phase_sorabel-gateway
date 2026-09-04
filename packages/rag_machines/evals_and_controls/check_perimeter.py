"""Contrôles du filtre de périmètre documentaire — déterministes, sans appel de modèle.

Ils exécutent ce que la conception avait laissé en suspens : la forme du ``where`` est
arrêtée depuis ``Q3`` §8, où elle est explicitement « documentée, **pas exécutée** » faute
d'un ``chromadb`` installé. Ce script est la vérification annoncée pour « le premier jour du
développement », sur les quatre profils, avec la version figée.

Les périmètres sont lus dans ``matrice.yaml`` — jamais réécrits ici. Les décomptes attendus,
eux, sont en dur : ce sont les chiffres annotés dans la matrice et publiés au catalogue, et
c'est précisément ce qu'on veut confronter à l'index.

Usage : make check-perimetre
"""

from __future__ import annotations

import sys

from config import settings
from packages.rag_machines.access_rag import (
    STATUS_FORBIDDEN_PERIMETER,
    perimeter_for,
    search_for_profile,
)
from packages.rag_machines.ingest.index import collection_name, connect, get_collection
from packages.rag_machines.retrieval.embedder import build_embedder
from packages.rag_machines.retrieval.lexical import (
    LexicalIndex,
    bm25_path,
    load_lexical_index,
)
from packages.rag_machines.retrieval.perimeter import NOTES, Perimeter

#: Les éditions **courantes** que chaque profil atteint, annotées dans `matrice.yaml`.
#: `commercial` et `admin` sont identiques : les deux sont contrôlés, un seul ne dirait
#: rien de la lecture de la matrice pour l'autre.
_CURRENT_BY_PROFILE = {"dev": 270, "support": 318, "commercial": 350, "admin": 350}

#: Les mêmes, filtre de version levé. Si l'un retombe à la valeur ci-dessus, c'est que le
#: filtre de version et le filtre de gouvernance se sont fondus l'un dans l'autre.
_ALL_VERSIONS_BY_PROFILE = {"dev": 320, "support": 368, "commercial": 400, "admin": 400}

#: Les profils que la matrice ferme entièrement. `Xyz` n'existe pas : la matrice est totale,
#: il retombe sur `default` et doit être refusé de la même façon.
_FORBIDDEN_PROFILES = ("default", "Xyz")


def main() -> int:
    try:
        collection = get_collection(connect(settings), build_embedder(settings), settings)
    except (RuntimeError, ValueError) as error:
        print(f"Index illisible : {error}", file=sys.stderr)
        return 1

    try:
        lexical = load_lexical_index(bm25_path(collection_name(settings)))
    except RuntimeError as error:
        print(f"Index BM25 illisible : {error}", file=sys.stderr)
        return 1

    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        print(f"  [{mark}] {label:<52} {actual!r} (attendu {expected!r})")
        if actual != expected:
            failures.append(label)

    def verdict() -> int:
        print()
        if failures:
            print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
            return 1
        print("Tous les contrôles passent.")
        return 0

    def ids_for(perimeter: Perimeter, version_filter: bool) -> set[str]:
        batch = collection.get(where=perimeter.where(version_filter), include=[])  # type: ignore[arg-type]
        return {str(edition_id) for edition_id in (batch.get("ids") or [])}

    def metadatas_for(perimeter: Perimeter) -> list[dict]:
        batch = collection.get(where=perimeter.where(True), include=["metadatas"])  # type: ignore[list-item]
        return [dict(entry) for entry in (batch.get("metadatas") or [])]

    print("Index :", collection_name(settings), "sur", settings.chroma_url)
    print("Matrice :", settings.matrix_path)

    print("\nDécomptes en or — éditions courantes atteintes par profil")
    for profile, expected in _CURRENT_BY_PROFILE.items():
        perimeter = perimeter_for(profile)
        assert perimeter is not None, profile
        check(f"{profile} — éditions courantes", len(ids_for(perimeter, True)), expected)

    print("\n`is_current` reste une clause à part — mêmes périmètres, filtre de version levé")
    for profile, expected in _ALL_VERSIONS_BY_PROFILE.items():
        perimeter = perimeter_for(profile)
        assert perimeter is not None, profile
        check(f"{profile} — toutes versions", len(ids_for(perimeter, False)), expected)

    print("\nPérimètre vide — un refus, jamais un filtre vide")
    for profile in _FORBIDDEN_PROFILES:
        check(f"{profile} — aucun périmètre constructible", perimeter_for(profile), None)
    # Le refus est prononcé avant toute requête : `search_for_profile` ne construit ni
    # embedder ni connexion. Un embedder local coûte plusieurs secondes de chargement —
    # que ce contrôle réponde instantanément est déjà un signe.
    refused = search_for_profile("procédure de retour sous garantie", "default")
    check("default — statut du refus", refused.status, STATUS_FORBIDDEN_PERIMETER)
    check("default — aucun résultat rendu", refused.hits, [])
    check("un refus de périmètre n'est pas un hors-corpus", refused.is_out_of_corpus, False)

    empty = Perimeter(frozenset(), frozenset())
    try:
        produced: object = empty.where(True)
    except RuntimeError:
        produced = "RuntimeError"
    check("un périmètre vide lève au lieu de rendre {}", produced, "RuntimeError")

    print("\nSémantique — la règle, pas seulement le compte")
    for profile in _CURRENT_BY_PROFILE:
        perimeter = perimeter_for(profile)
        assert perimeter is not None, profile
        violations = [
            m for m in metadatas_for(perimeter)
            if not perimeter.allows(str(m["doc_type"]), m.get("theme"))  # type: ignore[arg-type]
        ]
        check(f"{profile} — violations de la règle", len(violations), 0)

    # Le piège majeur, en négatif. Une conjonction naïve `doc_type` ET `theme` ne rendrait
    # que les 48 notes ouvertes au support : les 270 fiches, notices et procédures n'ont pas
    # de clé `theme` et disparaîtraient sans qu'aucune erreur ne le signale.
    support = perimeter_for("support")
    assert support is not None
    support_meta = metadatas_for(support)
    check("support — éditions courantes hors notes (naïf : 48)",
          sum(1 for m in support_meta if m["doc_type"] != NOTES), 270)
    check("support — notes ouvertes", sum(1 for m in support_meta if m["doc_type"] == NOTES), 48)
    check("support — notes fermées atteintes",
          sum(1 for m in support_meta
              if m["doc_type"] == NOTES
              and m.get("theme") in {"politique-tarifaire", "reunion-achat"}), 0)
    dev = perimeter_for("dev")
    assert dev is not None
    check("dev — notes internes atteintes",
          sum(1 for m in metadatas_for(dev) if m["doc_type"] == NOTES), 0)

    print("\nParité dense / lexical — sans quoi une note fuirait par la fusion RRF")
    for profile in _CURRENT_BY_PROFILE:
        perimeter = perimeter_for(profile)
        assert perimeter is not None, profile
        lexical_ids = {
            edition_id
            for edition_id, _, current, doc_type, theme in zip(
                lexical.edition_ids, lexical.edition_ids, lexical.is_current,
                lexical.doc_types, lexical.themes)
            if current and perimeter.allows(doc_type, theme)
        }
        check(f"{profile} — mêmes éditions des deux côtés",
              lexical_ids == ids_for(perimeter, True), True)

    print("\nCohérence du pickle BM25 avec l'index")
    check("éditions dans le pickle", len(lexical.edition_ids), 400)
    check("`theme` renseigné dans le pickle",
          sum(1 for theme in lexical.themes if theme is not None), 80)
    check("notes dans le pickle", sum(1 for t in lexical.doc_types if t == NOTES), 80)

    print("\nGarde-fou — un index antérieur au filtre se signale au chargement")
    stale = object.__new__(LexicalIndex)
    stale.__dict__.update(edition_ids=["a"], is_current=[True], bm25=None)
    try:
        from packages.rag_machines.retrieval.lexical import _check_schema
        _check_schema(stale, bm25_path("factice"))
        raised: object = "aucune erreur"
    except RuntimeError as error:
        raised = "make ingest" in str(error)
    check("l'erreur nomme le remède", raised, True)

    print("\nNon-régression — le filtre est un no-op sur le profil de mesure")
    commercial = perimeter_for("commercial")
    assert commercial is not None
    reference = collection.get(where={"is_current": True}, include=[])
    check("commercial == filtre de version seul",
          ids_for(commercial, True) == {str(i) for i in (reference.get("ids") or [])}, True)

    return verdict()


if __name__ == "__main__":
    raise SystemExit(main())
