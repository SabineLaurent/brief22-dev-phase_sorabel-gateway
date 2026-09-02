"""Registre des clés de document : versions courantes et contrôle de cohérence.

Le corpus porte 400 éditions pour 350 documents : 50 documents existent en deux
versions. Ce module désigne, pour chaque ``doc_key``, l'édition courante.

Les 400 éditions sont **toutes** indexées : le filtre de version (``is_current``)
s'applique à la requête, pas à l'index — l'édition antérieure doit rester
atteignable, mais jamais faire autorité par défaut.

Corollaire : quand une édition est écartée, son document perd son édition
courante. Aucune autre ne prend sa place — voir :func:`build_registry`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ingest.normalize import Edition, TextProfile


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
    #: ``doc_key`` dont l'édition courante est indécidable : une de leurs
    #: éditions a été écartée, donc aucune ne fait autorité.
    undetermined_doc_keys: set[str]

    def is_current(self, edition: Edition) -> bool:
        return edition.edition_id in self.current_edition_ids


def version_sort_key(version: str) -> tuple[int, ...]:
    """Ordonne les versions numériquement : 1.10 vient après 1.9, pas avant.

    Publique parce que ``scripts/check_index.py`` rejoue le même classement sur
    l'index produit : deux implémentations pourraient diverger, et le contrôle
    validerait alors autre chose que ce que l'ingestion a écrit.
    """
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def build_registry(editions: list[Edition]) -> Registry:
    """Contrôle la cohérence des versions, puis désigne les éditions courantes.

    Une édition dont le nom de fichier annonce une version différente de celle
    de son contenu n'est **pas** indexée : on ne sait pas laquelle fait foi, et
    l'indexer fausserait le classement des versions de son document.

    Écarter ne suffit pas. Si ``REF-8842-v2.1`` annonce ``2.0`` dans son corps et
    qu'on se contente de la retirer, ``REF-8842-v1.0`` devient la seule survivante
    de son ``doc_key`` et hérite de ``is_current`` : la gateway servirait alors une
    édition périmée avec l'assurance d'une édition courante. **Un document dont une
    édition est écartée n'a donc plus d'édition courante du tout** — aucune ne fait
    autorité tant que l'incohérence n'est pas corrigée à la source. Les deux écarts
    sont tracés dans le rapport d'ingestion, qui sort en échec.
    """
    kept: list[Edition] = []
    mismatches: list[VersionMismatch] = []
    undetermined_doc_keys: set[str] = set()
    for edition in editions:
        if edition.filename_version is not None and edition.filename_version != edition.version:
            mismatches.append(
                VersionMismatch(edition.edition_id, edition.filename_version, edition.version)
            )
            undetermined_doc_keys.add(edition.doc_key)
            continue
        kept.append(edition)

    by_document: dict[str, list[Edition]] = defaultdict(list)
    for edition in kept:
        by_document[edition.doc_key].append(edition)

    current_version: dict[str, str] = {}
    current_edition_ids: set[str] = set()
    for doc_key, group in by_document.items():
        if doc_key in undetermined_doc_keys:
            continue
        current = max(group, key=lambda e: version_sort_key(e.version))
        current_version[doc_key] = current.version
        current_edition_ids.add(current.edition_id)

    return Registry(
        editions=kept,
        current_version=current_version,
        current_edition_ids=current_edition_ids,
        mismatches=mismatches,
        undetermined_doc_keys=undetermined_doc_keys,
    )


def build_metadata(
    edition: Edition, registry: Registry, text: TextProfile = "clean"
) -> dict[str, str | int | bool]:
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
        "n_caracteres": len(edition.text_for(text)),
    }
    if edition.reference is not None:
        fields["reference"] = edition.reference
    if edition.theme is not None:
        fields["theme"] = edition.theme
    return fields
