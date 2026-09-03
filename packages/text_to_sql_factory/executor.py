"""L'exécution en lecture seule, bornée, puis les contrôles du résultat.

Deux couches de la défense en profondeur vivent ici (Q2 §3) :

**C2 — la connexion.** ``mode=ro`` *et* ``PRAGMA query_only=ON``, parce que chacun couvre le
contournement de l'autre : ``mode=ro`` protège le fichier mais pas les données —
``ATTACH`` puis ``CREATE TABLE p.vol AS SELECT * FROM produits`` en copie 120 lignes ;
``query_only`` protège la connexion, mais ``PRAGMA query_only=OFF`` le désactive. Et
**neuve à chaque requête** : sur une connexion réutilisée, un premier appel désarme, un
second exfiltre — chaque appel restant une instruction unique qui n'écrit rien.

**C4 — les bornes.** Sur cette base de 156 Ko, un produit cartésien de 40,5 millions de
lignes se calcule en 0,4 s : le risque immédiat n'est pas le temps mais le volume ramené —
``SELECT * FROM ventes, commandes`` rend 337 620 lignes. Le ``LIMIT`` compte donc plus que
le timeout, qui reste la garantie de bord pour une base qui grossira.

Puis **N7, trois contrôles de code, aucune passe LLM**. Ce sont des propriétés du résultat,
décidables par un comptage et une comparaison : elles rendent le même verdict à chaque
exécution. Un juge probabiliste transformerait au hasard un résultat correct en réserve.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from config import Settings
from config import settings as default_settings
from packages.text_to_sql_factory import SQL_DIALECT

#: Colonnes dont une valeur ne désigne pas une ligne : le catalogue porte 120 références
#: pour 52 noms, et 60 comptes clients pour 54 raisons sociales. Filtrer sur l'une d'elles
#: et obtenir plusieurs lignes n'est pas une liste, c'est une désignation ambiguë.
_AMBIGUOUS_FILTERS = frozenset({("produits", "nom"), ("clients", "raison_sociale")})

#: Nombre d'instructions de la machine virtuelle SQLite entre deux appels du garde-temps.
#: Assez petit pour interrompre vite, assez grand pour ne pas peser sur les requêtes brèves.
_PROGRESS_STEP = 1000


@dataclass(frozen=True)
class Execution:
    """Le résultat d'un appel à la base, et de quoi le journaliser.

    ``code`` est l'un des douze. ``aucune_ligne`` et ``ambiguite_donnees`` ne sont **pas**
    des refus : une clé bien formée qui ne désigne rien est un constat sur le monde.
    """

    code: str
    message: str = ""
    columns: tuple[str, ...] = ()
    rows: list[list[Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    truncated: bool = False

    @property
    def n_rows(self) -> int:
        return len(self.rows)


def _connect(settings: Settings) -> sqlite3.Connection:
    """Une connexion neuve, en lecture seule, désarmée pour l'écriture.

    Les deux verrous ensemble ne laissent passer qu'``ATTACH`` seul — qui n'exfiltre rien,
    mais que le validateur refuse de toute façon en amont.
    """
    path = Path(settings.sorabel_db)
    if not path.exists():
        raise RuntimeError(f"base absente : {path} — lancer `make seed`")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _order_keys(tree: exp.Expr) -> int:
    """Le nombre de colonnes du ``ORDER BY``, 0 s'il n'y en a pas.

    Sert à comparer deux lignes sur leur seule clé de tri : deux lignes différentes peuvent
    être à égalité au classement.
    """
    order = tree.args.get("order")
    return len(order.expressions) if order is not None else 0


def _explicit_limit(tree: exp.Expr) -> int | None:
    limit = tree.args.get("limit")
    if limit is None:
        return None
    value = limit.expression
    return int(value.name) if isinstance(value, exp.Literal) and value.is_int else None


def _filters_on_label(tree: exp.Expr) -> bool:
    """La requête filtre-t-elle sur un libellé homonyme ?

    On ne regarde que les conditions : une requête qui *projette* ``nom`` rend une liste,
    une requête qui *filtre* sur ``nom`` cherche un produit — et en trouve quatre.
    """
    where = tree.args.get("where")
    if where is None:
        return False
    return any(
        (column.table or "", column.name) in _AMBIGUOUS_FILTERS
        or any(column.name == name for _, name in _AMBIGUOUS_FILTERS)
        for column in where.find_all(exp.Column)
    )


def _run(sql: str, parameters: tuple[object, ...], ceiling: int,
         settings: Settings) -> tuple[list[tuple[object, ...]], tuple[str, ...], float, str]:
    """Ouvre, exécute, ferme. Rend ``(lignes, colonnes, latence, message d'erreur)``.

    Une ligne de plus que le plafond est ramenée : c'est ce qui permet de savoir qu'il en
    reste, sans avoir à compter deux fois.
    """
    started = time.monotonic()
    deadline = started + settings.sql_timeout_s
    connection = _connect(settings)
    try:
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, _PROGRESS_STEP
        )
        cursor = connection.execute(sql, parameters)
        fetched = cursor.fetchmany(ceiling + 1)
        columns = tuple(description[0] for description in cursor.description or ())
        return fetched, columns, (time.monotonic() - started) * 1000, ""
    except sqlite3.OperationalError as error:
        elapsed = (time.monotonic() - started) * 1000
        # Les lignes déjà ramenées sont jetées : rendre un résultat partiel avec sa requête
        # ferait mentir la garantie « voici le chiffre, et le SQL qui le produit ».
        if time.monotonic() > deadline:
            return [], (), elapsed, (
                f"délai de {settings.sql_timeout_s:g} s dépassé ; la requête a été interrompue"
            )
        return [], (), elapsed, f"la base a refusé la requête : {error}"
    except sqlite3.Error as error:
        return [], (), (time.monotonic() - started) * 1000, f"base indisponible : {error}"
    finally:
        connection.set_progress_handler(None, _PROGRESS_STEP)
        connection.close()


def execute_with_parameters(sql: str, parameters: tuple[object, ...],
                            settings: Settings | None = None) -> Execution:
    """Exécute une requête **figée**, paramétrée.

    Elle ne traverse ni la génération ni la validation d'AST : sa forme est écrite d'avance
    et relue une fois, son paramètre est validé avant l'appel. Elle passe en revanche par la
    même connexion en lecture seule et les mêmes bornes — le figement ne met pas hors
    gouvernance, il déplace la vérification de chaque appel à la revue de code.
    """
    settings = settings or default_settings
    ceiling = settings.sql_max_rows
    fetched, columns, latency_ms, failure = _run(sql, parameters, ceiling, settings)
    if failure:
        return Execution("erreur_execution", failure, latency_ms=latency_ms)
    rows = [list(row) for row in fetched[:ceiling]]
    if not rows:
        return Execution("aucune_ligne", "aucune ligne ne correspond", columns, rows, latency_ms)
    return Execution("ok", "", columns, rows, latency_ms, truncated=len(fetched) > ceiling)


def explain(sql: str, settings: Settings | None = None) -> str:
    """Prépare la requête sans la dérouler. Rend le message du moteur, ou ``""`` si elle tient.

    ``EXPLAIN`` fait passer la requête par le préparateur — résolution des tables, des
    colonnes, des fonctions, des ambiguïtés de jointure — et rend le programme de la machine
    virtuelle sans lire une ligne. C'est le seul juge fiable de « cette requête s'exécute » :
    le refaire sur l'arbre, c'est réimplémenter le résolveur de SQLite, et s'en écarter.

    Ce que l'analyse d'arbre ne peut pas voir et que le moteur voit : ``DATE_TRUNC``, ``NOW``,
    ``generate_series`` — tout ce que sqlglot ne sait pas transposer et recopie tel quel — et
    l'ambiguïté d'une colonne portée par deux tables jointes.

    Même connexion que l'exécution : ``mode=ro``, ``query_only``, neuve. Pas de garde-temps,
    la préparation est bornée par nature — mesurée à 1 ms sur cette base.

    ``EXPLAIN <requête>`` est la graphie portable : SQLite, PostgreSQL (sans ``ANALYZE``),
    MySQL et DuckDB l'acceptent tous. Seule la connexion dépend du moteur, pas ce préfixe.
    """
    settings = settings or default_settings
    connection = _connect(settings)
    try:
        connection.execute(f"EXPLAIN {sql}").fetchall()
        return ""
    except sqlite3.Error as error:
        return str(error)
    finally:
        connection.close()


def execute(sql: str, settings: Settings | None = None) -> Execution:
    """Exécute une requête **générée puis validée**, et rend son résultat avec son verdict.

    La requête est supposée sortie de ``validate()`` : cette fonction borne et exécute, elle
    ne juge pas du droit.
    """
    settings = settings or default_settings

    try:
        tree = sqlglot.parse_one(sql, dialect=SQL_DIALECT)
    except sqlglot.errors.ParseError as error:
        return Execution("erreur_execution", f"requête impossible à analyser : {error}")
    if not isinstance(tree, exp.Query):
        # `validate()` garantit déjà ce point ; la garde est là pour que la fonction reste
        # sûre appelée seule, et non pour rattraper un cas nominal.
        return Execution("erreur_execution", "seule une requête de lecture est exécutable")

    # Une ligne de plus que demandé, pour deux raisons à la fois : savoir si le classement
    # est coupé sur une égalité, et savoir s'il manque des lignes au-delà du plafond.
    limit = _explicit_limit(tree)
    ceiling = min(limit or settings.sql_max_rows, settings.sql_max_rows)
    # La sonde relève le LIMIT d'une unité : sans elle, `fetchmany` ne peut rien ramener
    # au-delà de ce que la requête s'autorise, et l'égalité à la frontière du classement
    # resterait invisible. C'est bien la requête validée, elle seule, qui sera renvoyée à
    # l'appelant — la sonde ne sert qu'à savoir s'il reste une ligne.
    probe = tree.limit(ceiling + 1).sql(dialect=SQL_DIALECT)
    fetched, columns, latency_ms, failure = _run(probe, (), ceiling, settings)
    if failure:
        return Execution("erreur_execution", failure, latency_ms=latency_ms)

    rows = [list(row) for row in fetched[:ceiling]]
    has_more = len(fetched) > ceiling
    # Une requête qui demande `LIMIT 5` et rend 5 lignes n'est pas tronquée : elle a fait ce
    # qu'on lui demandait. La troncature à signaler est celle que le **serveur** impose.
    truncated = has_more and ceiling == settings.sql_max_rows

    # N7 — contrôle 3 : le résultat est vide. Ce n'est ni un refus ni une erreur.
    if not rows:
        return Execution("aucune_ligne", "aucune ligne ne correspond", columns, rows, latency_ms)

    # N7 — contrôle 2 : égalité à la frontière du classement. La ligne sondée au-delà de la
    # borne porte-t-elle la même clé de tri que la dernière rendue ? Alors le classement
    # coupe au milieu d'un ex æquo, et le « top n » n'est qu'un top n possible.
    keys = _order_keys(tree)
    if keys and limit is not None and has_more:
        last, beyond = list(fetched[len(rows) - 1]), list(fetched[len(rows)])
        if last[-keys:] == beyond[-keys:]:
            return Execution(
                "ambiguite_donnees",
                f"égalité à la frontière du classement : la ligne suivante porte la même "
                f"valeur de tri que la {len(rows)}ᵉ — le classement en aurait plusieurs",
                columns, rows, latency_ms,
            )

    # N7 — contrôle 1 : plusieurs lignes là où la question en appelait une. On renvoie
    # toutes les lignes, jamais la première : choisir en silence est le mode d'échec.
    if len(rows) > 1 and _filters_on_label(tree):
        return Execution(
            "ambiguite_donnees",
            f"la désignation correspond à {len(rows)} lignes ; toutes sont rendues, "
            "avec leur référence — préciser la référence pour n'en obtenir qu'une",
            columns, rows, latency_ms,
        )

    if truncated:
        return Execution(
            "ok",
            f"résultat tronqué à {ceiling} lignes ; il en existe davantage",
            columns, rows, latency_ms, truncated=True,
        )
    return Execution("ok", "", columns, rows, latency_ms)
