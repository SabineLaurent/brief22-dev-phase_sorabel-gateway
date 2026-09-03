"""La matrice d'accès : ce qu'un profil a le droit d'atteindre.

`mcp_server/matrice.yaml` est une **donnée de configuration versionnée**, jamais du code.
Elle est lue ici, à un seul endroit, et les modules métier ne portent aucun `if profile ==`.

Trois propriétés délibérées, reprises du fichier lui-même :

1. **liste blanche partout** — une colonne ajoutée par une migration future est refusée par
   défaut, pas exposée par défaut ;
2. **`default` est un profil, pas une exception** — un profil absent, inconnu ou mal typé
   retombe dessus, avec zéro droit. Jamais de `KeyError`, jamais de `None` qui se propage ;
3. **le profil ne vient jamais du client** — il est lu dans l'environnement du serveur.
   Ici, c'est simplement un argument des fonctions internes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from config import Settings
from config import settings as default_settings


@dataclass(frozen=True)
class Scope:
    """Le périmètre d'un profil, tel que la matrice le décrit.

    ``columns`` porte des couples ``(table, colonne)`` : c'est la granularité du contrôle.
    « Table interdite » est un mauvais nom — fermer `produits` au support casserait le stock
    d'une référence ; ce qui se ferme, ce sont deux colonnes sur neuf.
    """

    profile: str
    tools: frozenset[str]
    collections: frozenset[str]
    themes_notes: frozenset[str]
    columns: frozenset[tuple[str, str]]

    @property
    def tables(self) -> frozenset[str]:
        """Les tables qu'au moins une colonne autorisée rend atteignables."""
        return frozenset(table for table, _ in self.columns)

    def columns_of(self, table: str) -> tuple[str, ...]:
        """Les colonnes autorisées d'une table, dans l'ordre de la matrice n'étant pas
        garanti par un ensemble : l'appelant qui a besoin d'un ordre stable trie."""
        return tuple(sorted(column for owner, column in self.columns if owner == table))


#: Périmètre vide, servi à tout profil que la matrice ne nomme pas. Un périmètre vide est
#: un refus, jamais une intersection muette.
EMPTY_SCOPE = Scope(
    profile="default",
    tools=frozenset(),
    collections=frozenset(),
    themes_notes=frozenset(),
    columns=frozenset(),
)


def _build_scope(profile: str, entry: object) -> Scope:
    """Construit un périmètre depuis une entrée de la matrice, défensivement.

    Une entrée mal typée — une chaîne là où une liste est attendue, une clé absente — ne
    doit pas lever : elle doit produire un périmètre vide sur la partie fautive. La matrice
    est de la configuration, et une configuration cassée doit refuser, pas planter.
    """
    if not isinstance(entry, dict):
        return Scope(profile, frozenset(), frozenset(), frozenset(), frozenset())

    def as_set(key: str) -> frozenset[str]:
        value = entry.get(key) or []
        return frozenset(str(item) for item in value) if isinstance(value, list) else frozenset()

    tables = entry.get("tables") or {}
    columns: set[tuple[str, str]] = set()
    if isinstance(tables, dict):
        for table, allowed in tables.items():
            if isinstance(allowed, list):
                columns.update((str(table), str(column)) for column in allowed)

    return Scope(
        profile=profile,
        tools=as_set("tools"),
        collections=as_set("collections"),
        themes_notes=as_set("themes_notes"),
        columns=frozenset(columns),
    )


@lru_cache(maxsize=4)
def _load_matrix(path: Path, mtime_ns: int) -> dict[str, Scope]:
    """Lit la matrice et la met en cache sur ``(chemin, date de modification)``.

    ``mtime_ns`` n'est pas utilisé dans le corps : il est là pour que le cache s'invalide
    tout seul quand le fichier change — même motif que l'index BM25.
    """
    del mtime_ns
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles = raw.get("profils") or {}
    if not isinstance(profiles, dict):
        return {}
    return {str(name): _build_scope(str(name), entry) for name, entry in profiles.items()}


def load_matrix(settings: Settings | None = None) -> dict[str, Scope]:
    """Rend la matrice entière, profil par profil."""
    settings = settings or default_settings
    path = Path(settings.matrix_path)
    if not path.exists():
        raise RuntimeError(
            f"matrice d'accès introuvable : {path} — la copier depuis "
            "docs/conception/LIVRABLES_CONCEPTION/matrice.yaml"
        )
    return _load_matrix(path, path.stat().st_mtime_ns)


def scope_for(profile: str, settings: Settings | None = None) -> Scope:
    """Le périmètre d'un profil. **Total** : un profil inconnu rend le périmètre de
    ``default``, et à défaut un périmètre vide. Jamais d'exception sur le nom du profil."""
    matrix = load_matrix(settings)
    return matrix.get(profile) or matrix.get("default") or EMPTY_SCOPE


def authorize(profile: str, tool: str, settings: Settings | None = None) -> bool:
    """Ce profil a-t-il droit à ce tool ? C'est l'étage 2, exercé par le serveur MCP.

    Le chantier Text-to-SQL ne l'appelle pas — il n'a pas de client à qui refuser — mais la
    règle appartient à la matrice, pas au serveur : elle est écrite là où elle se lit.
    """
    return tool in scope_for(profile, settings).tools
