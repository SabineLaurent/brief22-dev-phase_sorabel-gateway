"""Ce que la matrice d'accès veut dire **pour le SQL** : les colonnes.

``packages/access.py`` porte la matrice elle-même — le ``Scope``, son chargement, la
retombée sur ``default``, et ``authorize()`` qui vaut pour les huit tools du catalogue. Ce
module-ci ne porte que le lecteur propre à ce chantier : traduire un périmètre de colonnes
en refus nommé.

Le pendant documentaire vit dans ``packages/rag_machines/access_rag.py``. Les deux lisent la
même matrice, par la même fonction : une seconde lecture finirait par diverger de la
première.
"""

from __future__ import annotations

from config import Settings
from packages.access import scope_for


def columns_outside_scope(profile: str, columns: set[tuple[str, str]],
                          settings: Settings | None = None) -> list[tuple[str, str]]:
    """Parmi des couples ``(table, colonne)``, ceux qui tombent hors du périmètre du profil.

    **Ce n'est pas une liste noire** : la fonction ne détient aucune énumération de colonnes
    interdites. Elle lit la liste blanche de la matrice et rend son complément, restreint aux
    seules colonnes qu'on lui soumet. Une colonne qu'une migration ajouterait demain en
    sortirait donc d'office, sans que personne ait à l'inscrire nulle part — c'est la
    fermeture par dérivation (``Q3`` §7).

    Rendus triés : un refus nomme la colonne, et il la nomme toujours pareil.
    """
    allowed = scope_for(profile, settings).columns
    return sorted(column for column in columns if column not in allowed)
