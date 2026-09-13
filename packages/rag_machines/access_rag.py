"""Ce que la matrice d'accès veut dire **pour le corpus** : collections et thèmes.

``packages/access.py`` porte la matrice — le ``Scope``, son chargement, ``authorize()``.
Ce module-ci ne porte que le lecteur documentaire : convertir un profil en périmètre, et
prononcer le refus quand ce périmètre est vide.

C'est le **seul** module qui importe à la fois la matrice et la recherche. ``retrieval/``
ne connaît que des périmètres déjà résolus ; la gouvernance s'arrête ici.

Le pendant SQL vit dans ``packages/text_to_sql_factory/access_sql.py``.
"""

from __future__ import annotations

from typing import Any

from config import Settings
from packages.access import scope_for
from packages.rag_machines.retrieval.perimeter import NOTES, Perimeter
from packages.rag_machines.retrieval.search import SearchResult, search

#: Le profil n'ouvre aucune collection : ce n'est pas une absence de résultats, c'est un
#: refus. Le corpus couvre peut-être la question — c'est le profil qui ne couvre pas le
#: corpus, et les deux n'appellent pas la même action de l'utilisateur.
STATUS_FORBIDDEN_PERIMETER = "perimetre_interdit"

_FORBIDDEN_MESSAGE = "Aucune collection documentaire n'est ouverte à ce profil."


def perimeter_for(profile: str, settings: Settings | None = None) -> Perimeter | None:
    """Le périmètre documentaire d'un profil, ou ``None`` s'il n'en a aucun.

    ``None`` couvre les deux formes du périmètre vide : aucune collection, ou les seules
    notes internes sans aucun thème ouvert. Dans les deux cas, aucune branche de filtre
    n'est constructible — et un filtre vide **ne filtre rien**. C'est la raison d'être de
    cette valeur de retour : la distinction ne peut pas attendre la couche d'en dessous.
    """
    scope = scope_for(profile, settings)
    if not scope.collections or (scope.collections == {NOTES} and not scope.themes_notes):
        return None
    return Perimeter(doc_types=scope.collections, themes=scope.themes_notes)


def search_for_profile(query: str, profile: str, *, settings: Settings | None = None,
                       **kwargs: Any) -> SearchResult:
    """Cherche dans ce que ce profil a le droit de lire. Refuse s'il n'a droit à rien.

    Le refus tombe **avant** toute requête à l'index : rien n'est lu, donc rien ne peut
    fuir par une clause mal formée. C'est la première des deux barrières contre le périmètre
    vide ; la seconde est l'invariant de ``Perimeter.where()``.
    """
    perimeter = perimeter_for(profile, settings)
    if perimeter is None:
        return SearchResult(status=STATUS_FORBIDDEN_PERIMETER, hits=[],
                            message=_FORBIDDEN_MESSAGE)
    return search(query, settings=settings, perimeter=perimeter, **kwargs)
