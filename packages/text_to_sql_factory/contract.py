"""Le contrat de lecture de la base, filtré par profil.

On ne donne pas « le schéma de la base » au modèle, on lui donne un **contrat de lecture**
construit par le code depuis le schéma réel et la matrice (Q1). Cinq blocs :

1. le DDL filtré, commenté colonne par colonne — le type d'une colonne ne dit pas ce qu'elle
   contient : ``montant_ht REAL`` est vrai et inutile ;
2. les énumérations exactes — ``livree`` sans accent, ``LILLE`` en capitales,
   ``collectivité`` accentué en minuscules : trois conventions dans la même base, dont
   aucune ne se devine. ``statut = 'livrée'`` est syntaxiquement parfait, passe la
   validation, et renvoie zéro ligne sans que rien ne le signale ;
3. la plage temporelle réellement couverte, pas une année de référence ;
4. trois à cinq exemples question → SQL, chacun choisi pour le piège qu'il désamorce ;
5. les conventions métier, énoncées comme des consignes.

**Aucun échantillon de lignes.** Il ferait fuiter ``prix_achat_ht`` dans le prompt lui-même,
en amont de toute génération — donc dans un endroit que le validateur SQL ne regarde pas.

Un seul artefact, deux consommateurs : le prompt d'``ask_database`` et le tool
``get_schema``. Un prompt recopié à la main dériverait du schéma dès la première migration,
et cette dérive est silencieuse : un DDL faux produit du SQL faux, pas une erreur.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import Settings
from config import settings as default_settings
from packages.access import Scope, scope_for

#: Les cinq tables de la base. Ordre de lecture, pas ordre alphabétique : on décrit le
#: catalogue avant ce qu'on en vend.
TABLES = ("produits", "stocks", "clients", "commandes", "ventes")

#: Notes qui remplacent le commentaire de `docs/schema.sql` là où il ne suffit pas — ou
#: là où la mesure le contredit. Elles portent les pièges chiffrés de la conception
#: (`2-text-to-sql/description-base.md` §5), que le schéma de référence ne dit pas.
#:
#: Le cas `ventes.prix_unitaire_ht` est un **écart assumé** : `docs/schema.sql` le commente
#: « remise déduite », alors que la mesure dit l'inverse — `SUM(quantite × prix_unitaire_ht)`
#: reconstitue `montant_ht` sur 340 commandes sur 340. Le document livré n'est pas modifié ;
#: c'est le contrat donné au modèle qui porte le fait mesuré, sans quoi la génération
#: hériterait d'une fausseté.
_COLUMN_NOTES: dict[tuple[str, str], str] = {
    ("produits", "nom"): "libellé commercial — 120 références pour 52 noms : un libellé "
                         "n'identifie PAS un produit",
    ("produits", "prix_achat_ht"): "prix d'achat fournisseur",
    ("produits", "marge_pct"): "marge en % du prix de vente ; sans rapport avec ventes.marge_ht",
    ("stocks", "quantite"): "quantité de CETTE ligne, donc de cet entrepôt ; le stock d'une "
                            "référence est la SOMME de ses lignes",
    ("stocks", "seuil_reappro"): "seuil propre à CET entrepôt — ils diffèrent d'un entrepôt "
                                 "à l'autre pour une même référence",
    ("clients", "raison_sociale"): "60 comptes pour 54 raisons sociales : 6 enseignes ont "
                                   "deux comptes",
    ("commandes", "montant_ht"): "montant BRUT, AVANT remise (vérifié sur 340 commandes sur "
                                 "340) ; les remises sont dans ventes.remise_pct",
    ("ventes", "prix_unitaire_ht"): "prix unitaire AVANT remise ; SUM(quantite × "
                                    "prix_unitaire_ht) reconstitue commandes.montant_ht",
    ("ventes", "marge_ht"): "marge en euros de CETTE ligne ; sans rapport avec "
                            "produits.marge_pct",
}

#: Commentaires de table, que le DDL ne porte pas.
_TABLE_NOTES: dict[str, str] = {
    "stocks": "quantités par entrepôt — environ 2,6 lignes par référence, "
              "114 références sur 120 sont dans plusieurs entrepôts",
    "ventes": "LIGNES DE COMMANDE ; ne porte AUCUNE date — pour filtrer par date, "
              "joindre commandes.date_commande",
}

#: Colonnes dont les valeurs forment un *vocabulaire* et non du *contenu* : au-delà de ce
#: nombre de valeurs distinctes, énumérer serait publier des données.
_ENUM_MAX_CARDINALITY = 15

#: Les exemples de Q1 §4. Chacun déclare les colonnes qu'il touche : un exemple qui
#: mentionne une colonne fermée au profil apprendrait son existence — il est donc écarté,
#: comme les axes de clarification le sont (Q5 §3).
_EXAMPLES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "quelle marge totale sur les ventes de mai 2026 ?",
        "SELECT SUM(v.marge_ht) FROM ventes v JOIN commandes c ON c.id = v.commande_id "
        "WHERE c.date_commande LIKE '2026-05-%' AND c.statut <> 'annulee'",
        (("ventes", "marge_ht"), ("ventes", "commande_id"),
         ("commandes", "id"), ("commandes", "date_commande"), ("commandes", "statut")),
    ),
    (
        "quel est le stock total de la REF-8842 ?",
        "SELECT entrepot, quantite, seuil_reappro FROM stocks WHERE ref = 'REF-8842'",
        (("stocks", "entrepot"), ("stocks", "quantite"),
         ("stocks", "seuil_reappro"), ("stocks", "ref")),
    ),
    (
        "prix de vente HT du disjoncteur tétrapolaire 40 A",
        "SELECT ref, nom, prix_vente_ht FROM produits WHERE nom LIKE '%tétrapolaire%40 A%'",
        (("produits", "ref"), ("produits", "nom"), ("produits", "prix_vente_ht")),
    ),
    (
        "liste des commandes livrées en juin 2026",
        "SELECT id, date_commande, montant_ht FROM commandes "
        "WHERE statut = 'livree' AND date_commande LIKE '2026-06-%'",
        (("commandes", "id"), ("commandes", "date_commande"),
         ("commandes", "montant_ht"), ("commandes", "statut")),
    ),
)

#: Les conventions métier de Q1 §5 et Q5 §4. Ce sont des choix, pas des faits du schéma :
#: sans elles le résultat n'est pas interprétable. Elles sont renvoyées avec le résultat.
CONVENTIONS: tuple[str, ...] = (
    "les commandes annulées (statut = 'annulee') sont exclues des chiffres de vente, "
    "de marge et de quantité — jamais d'un simple comptage de commandes",
    "le montant d'une commande est commandes.montant_ht, brut",
    "un produit s'identifie par sa référence ; désigné par son nom, on renvoie tous "
    "les candidats avec leur ref, jamais le premier",
    "les clients se regroupent par compte (clients.id), la seule identification non ambiguë",
)

_TABLE_BLOCK = re.compile(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", re.DOTALL)
_COLUMN_LINE = re.compile(r"^\s{2}(\w+)\s+([A-Z]+)")


def _months_between(first: str, last: str) -> list[str]:
    """Les mois ``AAAA-MM`` couverts, bornes comprises. La plage est courte — douze mois —
    et l'énumérer vaut mieux que de la décrire : le modèle n'a plus à la déduire."""
    year, month = int(first[:4]), int(first[5:7])
    end = last[:7]
    months = []
    while True:
        current = f"{year:04d}-{month:02d}"
        months.append(current)
        if current == end:
            return months
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


@dataclass(frozen=True)
class ReadContract:
    """Ce qu'un profil a le droit de savoir de la base — et rien de plus.

    C'est le même objet qui est injecté au prompt de génération et rendu par ``get_schema``.
    """

    profile: str
    ddl: str
    enumerations: dict[str, list[str]]
    date_range: tuple[str, str] | None
    examples: tuple[tuple[str, str], ...]
    conventions: tuple[str, ...]

    def as_text(self) -> str:
        """Le contrat en un seul bloc de texte : la forme qu'attendent le prompt et
        ``get_schema`` — dont le contrat DSI dit ``{"schema": str}``."""
        parts = [
            "-- Schéma lisible par ce profil. Les colonnes absentes de ce DDL ne sont pas "
            "interrogeables.",
            self.ddl,
        ]
        if self.enumerations:
            lines = ["-- Valeurs exactes des colonnes énumérées. La casse et les accents "
                     "comptent :", "-- une valeur mal orthographiée renvoie zéro ligne sans "
                     "erreur."]
            lines += [f"--   {column} : {' | '.join(values)}"
                      for column, values in sorted(self.enumerations.items())]
            parts.append("\n".join(lines))
        if self.date_range is not None:
            first, last = self.date_range
            months = " ".join(_months_between(first, last))
            parts.append(
                f"-- Période couverte : du {first} au {last}, soit les mois :\n"
                f"--   {months}\n"
                f"-- Chaque mois du calendrier n'y apparaît qu'une fois : un mois cité sans "
                f"année désigne\n-- la seule occurrence de ce mois dans cette liste. Sans "
                f"cela, une requête datée sur l'année\n-- courante renverrait zéro ligne.\n"
                f"-- Le dernier mois est tronqué au {last} : une tendance calculée dessus "
                f"est un artefact de calendrier."
            )
        if self.examples:
            lines = ["-- Exemples de questions et de la requête attendue :"]
            for question, sql in self.examples:
                lines += [f"--   {question}", f"--     {sql}"]
            parts.append("\n".join(lines))
        if self.conventions:
            lines = ["-- Conventions métier à appliquer :"]
            lines += [f"--   - {convention}" for convention in self.conventions]
            parts.append("\n".join(lines))
        return "\n\n".join(parts)


def _parse_schema_doc(path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Lit le schéma commenté et rend, par table, ses ``(colonne, type, commentaire)``.

    Le commentaire est celui du document, débarrassé des annotations de gouvernance
    (``SENSIBLE : …``) : elles s'adressent au lecteur humain de la conception, pas au
    modèle — et la colonne qu'elles décrivent n'atteint le contrat que si le profil y a
    droit, ce qui rend la mise en garde sans objet à cet endroit.
    """
    text = path.read_text(encoding="utf-8")
    by_table: dict[str, list[tuple[str, str, str]]] = {}
    for table, body in _TABLE_BLOCK.findall(text):
        columns: list[tuple[str, str, str]] = []
        for line in body.splitlines():
            match = _COLUMN_LINE.match(line)
            if not match:
                continue
            name, sql_type = match.group(1), match.group(2)
            comment = line.split("--", 1)[1].strip() if "--" in line else ""
            comment = re.sub(r"^SENSIBLE\s*:\s*", "", comment).split(" — ne sort jamais")[0]
            columns.append((name, sql_type, comment.strip()))
        by_table[table] = columns
    return by_table


def build_ddl(scope: Scope, settings: Settings | None = None) -> str:
    """Le DDL des seules colonnes autorisées, commenté.

    Une colonne hors périmètre n'est pas commentée autrement : elle est **absente**.
    Décrire ``marge_pct`` à qui ne doit pas la lire, c'est déjà en publier l'existence.
    """
    settings = settings or default_settings
    declared = _parse_schema_doc(Path(settings.schema_doc))
    blocks: list[str] = []
    for table in TABLES:
        allowed = set(scope.columns_of(table))
        if not allowed:
            continue
        lines = [f"CREATE TABLE {table} ("]
        if table in _TABLE_NOTES:
            lines[0] += f"  -- {_TABLE_NOTES[table]}"
        rows = [
            (name, sql_type, _COLUMN_NOTES.get((table, name), comment))
            for name, sql_type, comment in declared.get(table, [])
            if name in allowed
        ]
        width = max((len(name) for name, _, _ in rows), default=0)
        for index, (name, sql_type, comment) in enumerate(rows):
            end = "," if index < len(rows) - 1 else ""
            declaration = f"  {name:<{width}} {sql_type}{end}"
            lines.append(f"{declaration}  -- {comment}" if comment else declaration)
        lines.append(");")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _read_enumerations(scope: Scope, connection: sqlite3.Connection) -> dict[str, list[str]]:
    """Les valeurs distinctes des colonnes autorisées à faible cardinalité.

    Un vocabulaire, pas du contenu : au-delà de ``_ENUM_MAX_CARDINALITY`` valeurs, on
    n'énumère pas — ``produits.nom`` et ``clients.raison_sociale`` tombent d'eux-mêmes.
    """
    enumerations: dict[str, list[str]] = {}
    for table, column in sorted(scope.columns):
        rows = connection.execute(
            f"SELECT DISTINCT {column} FROM {table} "  # noqa: S608 - noms issus de la matrice
            f"ORDER BY {column} LIMIT {_ENUM_MAX_CARDINALITY + 1}"
        ).fetchall()
        if len(rows) > _ENUM_MAX_CARDINALITY:
            continue
        values = [str(row[0]) for row in rows if row[0] is not None]
        # Une colonne à valeur unique ou à identifiant libre n'apprend rien ; les nombres
        # non plus, sauf quand ils forment un barème fermé comme remise_pct.
        if len(values) > 1 or (table, column) == ("produits", "actif"):
            enumerations[f"{table}.{column}"] = values
    return enumerations


def build_read_contract(profile: str, settings: Settings | None = None) -> ReadContract:
    """Le contrat de lecture de ce profil, construit depuis la base et la matrice.

    Lève ``RuntimeError`` si la base est absente : c'est une panne d'installation, avec un
    remède, pas un cas métier.
    """
    settings = settings or default_settings
    scope = scope_for(profile, settings)
    database = Path(settings.sorabel_db)
    if not database.exists():
        raise RuntimeError(f"base absente : {database} — lancer `make seed`")

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        enumerations = _read_enumerations(scope, connection)
        date_range = None
        if ("commandes", "date_commande") in scope.columns:
            first, last = connection.execute(
                "SELECT MIN(date_commande), MAX(date_commande) FROM commandes"
            ).fetchone()
            date_range = (str(first), str(last))
    finally:
        connection.close()

    examples = tuple(
        (question, sql)
        for question, sql, columns in _EXAMPLES
        if all(column in scope.columns for column in columns)
    )
    return ReadContract(
        profile=scope.profile,
        ddl=build_ddl(scope, settings),
        enumerations=enumerations,
        date_range=date_range,
        examples=examples,
        conventions=CONVENTIONS,
    )
