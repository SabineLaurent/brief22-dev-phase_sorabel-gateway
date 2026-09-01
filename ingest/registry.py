"""Registre des clés de document : versions courantes et contrôle de cohérence.

Le corpus porte 400 éditions pour 350 documents : 50 documents existent en deux
versions. Ce module désigne, pour chaque ``doc_key``, l'édition courante.

Les 400 éditions sont **toutes** indexées : le filtre de version (``is_current``)
s'applique à la requête, pas à l'index — l'édition antérieure doit rester
atteignable, mais jamais faire autorité par défaut.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ingest.normalize import Edition


@dataclass(frozen=True)
class VersionMismatch:
    """Un écart entre la version annoncée par le nom de fichier et le contenu."""

    edition_id: str
    filename_version: str
    content_version: str

    def __str__(self) -> str:
        return (
            f"{self.edition_id} : nom de fichier v{self.filename_version} "
            f"mais contenu v{self.content_version}"
        )


@dataclass
class Registry:
    """Le résultat du scan : ce qui est indexable, et ce qui ne l'est pas."""

    #: Éditions retenues, dans un ordre stable.
    editions: list[Edition]
    #: ``doc_key`` → version courante.
    current_version: dict[str, str]
    #: Les ``edition_id`` qui portent la version courante de leur document.
    current_edition_ids: set[str]
    #: Éditions écartées de l'index, avec leur motif.
    mismatches: list[VersionMismatch]

    def is_current(self, edition: Edition) -> bool:
        return edition.edition_id in self.current_edition_ids


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Ordonne les versions numériquement : 1.10 vient après 1.9, pas avant."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def build_registry(editions: list[Edition]) -> Registry:
    """Contrôle la cohérence des versions, puis désigne les éditions courantes.

    Une édition dont le nom de fichier annonce une version différente de celle
    de son contenu n'est **pas** indexée : on ne sait pas laquelle fait foi, et
    l'indexer fausserait le classement des versions de son document. L'écart est
    tracé dans le rapport d'ingestion.
    """
    kept: list[Edition] = []
    mismatches: list[VersionMismatch] = []
    for edition in editions:
        if edition.filename_version is not None and edition.filename_version != edition.version:
            mismatches.append(
                VersionMismatch(edition.edition_id, edition.filename_version, edition.version)
            )
            continue
        kept.append(edition)

    by_document: dict[str, list[Edition]] = defaultdict(list)
    for edition in kept:
        by_document[edition.doc_key].append(edition)

    current_version: dict[str, str] = {}
    current_edition_ids: set[str] = set()
    for doc_key, group in by_document.items():
        current = max(group, key=lambda e: _version_sort_key(e.version))
        current_version[doc_key] = current.version
        current_edition_ids.add(current.edition_id)

    return Registry(
        editions=kept,
        current_version=current_version,
        current_edition_ids=current_edition_ids,
        mismatches=mismatches,
    )


def build_metadata(edition: Edition, registry: Registry) -> dict[str, str | int | bool]:
    """Les onze champs de métadonnées, prêts pour l'index.

    C'est le seul endroit où les attributs Python (anglais) deviennent des clés
    de données. Ces clés suivent le contrat — le JSON Schema du dossier de
    conception et les tests d'acceptance —, d'où ``titre`` et ``n_caracteres``.

    Toutes les valeurs sont scalaires — Chroma n'accepte rien d'autre — et **la
    clé est omise lorsque la valeur est absente** : ``None`` est refusé par
    Chroma, et une chaîne vide serait une valeur, qui se compare et se trie.
    """
    fields: dict[str, str | int | bool] = {
        "edition_id": edition.edition_id,
        "doc_key": edition.doc_key,
        "is_current": registry.is_current(edition),
        "titre": edition.title,
        "version": edition.version,
        "date": edition.date,
        "doc_type": edition.doc_type,
        "url": edition.url,
        "n_caracteres": edition.char_count,
    }
    if edition.reference is not None:
        fields["reference"] = edition.reference
    if edition.theme is not None:
        fields["theme"] = edition.theme
    return fields
