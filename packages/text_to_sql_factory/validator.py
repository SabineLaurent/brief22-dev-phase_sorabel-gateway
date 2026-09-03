"""La validation de la requête générée : cinq contrôles sur l'arbre, la borne, puis l'essai
à blanc contre le moteur.

**Le danger est une opération, pas un mot.** Une liste de mots interdits est définitivement
écartée : ``VACUUM INTO 'copie.db'`` exfiltre les 156 Ko de la base en une instruction, sans
écrire, et ne contient ni ``INSERT``, ni ``UPDATE``, ni ``DELETE``, ni ``DROP``. Le risque
réel est la fuite. On interroge donc l'arbre — quelle est la racine, quelles tables et
colonnes sont *réellement* référencées — au lieu de chercher des sous-chaînes dans du texte.

Les cinq contrôles (Q2 §3 C3) :

1. une seule instruction ;
2. racine ``SELECT``, ``WITH … SELECT`` ou requête composée ;
3. aucun nœud de modification dans tout l'arbre, CTE et sous-requêtes comprises ;
4. aucun ``PRAGMA``, ``ATTACH``, ``DETACH``, ``VACUUM`` ;
5. toutes les tables (5a) **puis** les colonnes (5b) référencées ∈ matrice(profil).

Puis, une fois la borne posée, un sixième contrôle qui n'interroge plus l'arbre mais le
moteur : ``EXPLAIN`` prépare la requête sans lire une ligne (voir ``executor.explain``).
L'arbre et le moteur ne savent pas les mêmes choses, et l'ordre entre les deux est la
propriété qui tient l'ensemble :

- **5a avant 5b**, parce que ``qualify`` ne sait pas résoudre les colonnes d'une table
  qu'il ignore : sans le contrôle des tables, celui des colonnes est aveugle sur elles.
- **6 en dernier**, parce que c'est le seul pas qui touche la base : rien ne l'atteint
  avant que la matrice ait tranché. ``EXPLAIN`` répond « cette requête se prépare », jamais
  « cette requête est permise » — il complète la liste blanche, il ne la remplace pas.

**C'est la seule couche qui produise un refus lisible, motivé et journalisable.** La
connexion en lecture seule refuse elle aussi, mais avec un message SQLite indistinguable
d'un bug d'infrastructure : c'est ici que le test d'acceptance se joue, pas là-bas.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import build_scope

from config import Settings
from config import settings as default_settings
from packages.text_to_sql_factory import SQL_DIALECT
from packages.text_to_sql_factory.access import scope_for
from packages.text_to_sql_factory.contract import TABLES
from packages.text_to_sql_factory.executor import explain

#: Contrôle 3 — les nœuds qui modifient. ``exp.DML`` et ``exp.DDL`` ne suffisent pas :
#: ``DROP`` n'est ni l'un ni l'autre dans sqlglot 30. La liste explicite est donc la
#: barrière, les deux classes de base sont le filet pour ce qui viendrait s'y ajouter.
_WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Merge, exp.DML, exp.DDL,
)

#: Contrôle 4 — les quatre que la connexion laisse passer ou dont elle dépend.
#: ``VACUUM`` n'a pas de nœud propre : sqlglot le range en ``exp.Command``, la classe des
#: instructions qu'il ne sait pas analyser. Refuser tout ``Command`` est donc à la fois
#: nécessaire et prudent — on ne valide pas ce qu'on n'a pas compris.
_ENGINE_NODES = (exp.Pragma, exp.Attach, exp.Detach, exp.Command, exp.Set)

#: Contrôle 2 — les seules racines acceptables. Une requête composée (``UNION``) est
#: admise ici et bornée plus loin : c'est N5 qui refuse si le ``LIMIT`` n'est pas posable.
_QUERY_ROOTS = (exp.Select, exp.SetOperation)


@dataclass(frozen=True)
class Verdict:
    """Ce que la validation décide, et de quoi le journaliser.

    ``code`` est l'un des douze du catalogue. ``sql`` ne porte la requête bornée que sur
    ``ok`` — sur un refus, il n'y a rien à exécuter et rien à montrer d'exécutable.
    """

    code: str
    message: str
    sql: str = ""
    forbidden: tuple[tuple[str, str], ...] = ()
    #: La requête est fausse, pas interdite : le modèle peut se voir rendre l'erreur du
    #: moteur pour une reprise. **Seul le contrôle 6 le pose.** Un refus de droits ne le
    #: porte jamais — il ne se renégocie pas avec le modèle. Le champ ne sort pas du
    #: paquet : l'enveloppe de la DSI est inchangée, aucun code nouveau.
    repairable: bool = False

    @property
    def allowed(self) -> bool:
        return self.code == "ok"


@lru_cache(maxsize=2)
def _database_schema(path: Path, mtime_ns: int) -> dict[str, dict[str, str]]:
    """Le schéma **réel et complet** de la base, pour ``qualify``.

    Complet, et non filtré par le profil : c'est ce qui permet à ``SELECT *`` d'être
    *développé* en ses colonnes nommées avant le contrôle 5. Un schéma filtré développerait
    l'étoile sur les seules colonnes autorisées, et l'étoile ramènerait quand même les
    autres à l'exécution — la barrière deviendrait aveugle à ce qu'elle doit attraper.
    """
    del mtime_ns
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            table: {row[1]: row[2] for row in connection.execute(f"PRAGMA table_info({table})")}
            for table in TABLES
        }
    finally:
        connection.close()


def database_schema(settings: Settings | None = None) -> dict[str, dict[str, str]]:
    """Le schéma réel, mis en cache sur la date de modification du fichier."""
    settings = settings or default_settings
    path = Path(settings.sorabel_db)
    if not path.exists():
        raise RuntimeError(f"base absente : {path} — lancer `make seed`")
    return _database_schema(path, path.stat().st_mtime_ns)


def referenced_tables(tree: exp.Expr) -> set[str]:
    """Les tables réellement citées en source, noms de CTE exclus.

    Une CTE est une source, pas une table : ``WITH t AS (SELECT … FROM stocks) … FROM t``
    ne cite que ``stocks``. La table réelle lue derrière la CTE est vue, elle, et c'est
    elle que le périmètre juge.

    Une source sans nom de table — une fonction de table comme ``generate_series(1, 10)`` —
    est rendue telle qu'écrite plutôt que sous un nom vide : elle n'est dans aucun
    périmètre, et la nommer dans le refus vaut mieux que de la taire.
    """
    declared = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    cited = {
        table.name or table.sql(dialect=SQL_DIALECT) for table in tree.find_all(exp.Table)
    }
    return cited - declared


def referenced_columns(tree: exp.Expr) -> set[tuple[str, str]]:
    """Les couples ``(table, colonne)`` réellement référencés, alias résolus.

    Le piège que cette fonction existe pour désamorcer (Q3 §5) : comparer directement
    ``(col.table, col.name)`` à la matrice laisse passer
    ``SELECT p.nom, SUM(v.marge_ht) FROM ventes v JOIN produits p …`` — l'arbre porte
    ``("v", "marge_ht")``, qui n'est dans aucune liste d'interdits. **Un alias d'une lettre
    suffit à sortir les marges.** On parcourt donc les *scopes*, on résout alias → nom réel
    de table dans chacun, et on compare ensuite. Une colonne cachée dans une CTE est vue
    dans le scope de la CTE.

    Le contrôle porte sur toute occurrence — ``SELECT``, ``WHERE``, ``ORDER BY``,
    ``GROUP BY``, ``HAVING``, ``JOIN … ON`` — et pas sur la projection : ``SELECT ref, nom
    FROM produits ORDER BY marge_pct DESC`` répond à « classement par marge » sans projeter
    la colonne, et 11 requêtes booléennes suffisent à retrouver une marge par dichotomie.
    """
    root = build_scope(tree)
    if root is None:
        return set()
    seen: set[tuple[str, str]] = set()
    for scope in root.traverse():
        sources = {
            name: source.name
            for name, source in scope.sources.items()
            if isinstance(source, exp.Table)
        }
        # Les noms donnés aux colonnes de sortie. `ORDER BY quantite_vendue` désigne un
        # résultat calculé, pas une colonne de table : le compter comme colonne le ferait
        # passer pour inventé, et une requête juste serait rejetée. Écarter ces noms ne
        # rouvre rien — la colonne réellement lue derrière l'alias est vue séparément, avec
        # sa table, et c'est elle que le périmètre juge.
        expression = scope.expression
        aliases = {
            projection.alias
            for projection in (expression.selects if isinstance(expression, exp.Query) else [])
            if isinstance(projection, exp.Alias)
        }
        for column in scope.expression.find_all(exp.Column):
            if not column.table and column.name in aliases:
                continue
            seen.add((sources.get(column.table, column.table), column.name))
    return seen


def _apply_limit(tree: exp.Query, limit: int) -> exp.Query | None:
    """Pose un ``LIMIT`` si la requête n'en porte pas — **jamais en remplacement d'un
    ``LIMIT`` plus petit déjà présent**.

    ``Expression.limit()`` écrase sans regarder : appelée sur ``… LIMIT 5`` avec 200, elle
    rend ``LIMIT 200``. Ce serait élargir une requête que l'utilisateur avait bornée
    lui-même. On lit donc la borne existante d'abord.

    Rend ``None`` quand la borne n'a pas pu être posée (panne P3) : on refuse d'exécuter
    plutôt que d'exécuter sans borne.
    """
    existing = tree.args.get("limit")
    if existing is not None:
        current = existing.expression
        if isinstance(current, exp.Literal) and current.is_int and int(current.name) <= limit:
            return tree
    bounded = tree.limit(limit)
    return bounded if bounded.args.get("limit") is not None else None


def validate(sql: str, profile: str, settings: Settings | None = None) -> Verdict:
    """Passe la requête aux cinq contrôles, puis lui pose sa borne.

    Rend un ``Verdict`` — jamais une exception sur le contenu de la requête : une requête
    hostile est un cas nominal de cette fonction, pas une panne.
    """
    settings = settings or default_settings

    # Contrôle 1 — une seule instruction. Le driver Python refuse déjà les instructions
    # multiples (« You can only execute one statement at a time »), mais son refus n'est ni
    # nommé ni journalisable : on le nomme ici.
    try:
        statements = [tree for tree in sqlglot.parse(sql, dialect=SQL_DIALECT) if tree is not None]
    except ParseError as error:
        return Verdict("erreur_execution", f"requête impossible à analyser : {error}")
    if not statements:
        return Verdict("erreur_execution", "requête vide")
    if len(statements) > 1:
        return Verdict(
            "ecriture_refusee",
            "la requête porte plusieurs instructions ; une seule est exécutable",
        )
    tree = statements[0]

    # Contrôle 3 puis 4 avant le 2 : ils nomment précisément ce qui est refusé, là où le
    # contrôle 2 ne peut dire que « ce n'est pas une lecture ».
    write = tree.find(*_WRITE_NODES)
    if write is not None:
        return Verdict(
            "ecriture_refusee",
            f"la requête modifie la base ({type(write).__name__.upper()}) ; "
            "la gateway est en lecture seule",
        )
    engine = tree.find(*_ENGINE_NODES)
    if engine is not None:
        return Verdict(
            "ecriture_refusee",
            "la requête pilote le moteur (PRAGMA, ATTACH, DETACH, VACUUM) ; "
            "seule l'interrogation des tables est permise",
        )

    # Contrôle 2 — la racine.
    if not isinstance(tree, _QUERY_ROOTS):
        return Verdict(
            "ecriture_refusee",
            f"la requête n'est pas une lecture ({type(tree).__name__.upper()})",
        )

    scope = scope_for(profile, settings)

    # Contrôle 5a — les tables, **avant** les colonnes. L'ordre n'est pas cosmétique :
    # `qualify` ne sait pas résoudre les colonnes d'une table qu'il ignore, il les laisse
    # sans préfixe, et la règle d'alias de `referenced_columns` les écarte alors du
    # contrôle. Une table hors matrice qui passerait ici emporterait donc toutes ses
    # colonnes avec elle — `SELECT sql FROM sqlite_master` rend le DDL complet, marges
    # comprises. C'est la fermeture par dérivation (Q3 §7) : ce qui n'est pas nommé dans la
    # matrice est refusé, y compris une table qu'une migration future ajouterait.
    outside = sorted(referenced_tables(tree) - scope.tables)
    if outside:
        return Verdict(
            "perimetre_interdit",
            f"ce profil n'a pas accès à : {', '.join(outside)}",
        )

    # Contrôle 5b — les colonnes, sur toute occurrence, alias résolus.
    schema = database_schema(settings)
    try:
        qualified = qualify(tree, schema=cast(dict[str, Any], schema), dialect=SQL_DIALECT,
                            validate_qualify_columns=False, quote_identifiers=False)
    except OptimizeError as error:
        return Verdict("erreur_execution", f"requête inexploitable sur ce schéma : {error}")

    columns = referenced_columns(qualified)
    allowed = scope.columns
    forbidden = sorted(
        column for column in columns
        if column not in allowed and column[0] in schema and column[1] in schema[column[0]]
    )
    if forbidden:
        # On refuse en nommant. Réécrire la requête en la privant de ses colonnes
        # interdites l'exécuterait et rendrait un résultat que l'utilisateur croirait
        # complet — c'est le mode d'échec que tout ce chantier cherche à éviter.
        named = ", ".join(f"{table}.{column}" for table, column in forbidden)
        return Verdict(
            "perimetre_interdit",
            f"ce profil n'a pas accès à : {named}",
            forbidden=tuple(forbidden),
        )
    # N5 — la borne.
    bounded = _apply_limit(qualified, settings.sql_default_limit)
    if bounded is None:
        return Verdict(
            "erreur_execution",
            "impossible de borner cette requête par un LIMIT ; elle n'est pas exécutée",
        )

    # Contrôle 6 — l'essai à blanc, sur la chaîne exacte qui sera exécutée. Le moteur
    # prépare la requête sans lire une ligne et tranche ce que l'arbre ne peut pas voir :
    # une fonction que sqlglot n'a pas su transposer (`DATE_TRUNC`, `NOW`), une colonne
    # inventée, une colonne ambiguë entre deux tables jointes. En dernier, exprès : rien
    # n'atteint la base avant que la matrice ait blanchi tables et colonnes.
    #
    # Panne P5 : la requête est fausse, pas interdite — `repairable` la distingue d'un refus
    # de droits, qui ne se renégocie pas.
    final = bounded.sql(dialect=SQL_DIALECT)
    failure = explain(final, settings)
    if failure:
        return Verdict(
            "erreur_execution",
            f"la base a refusé la requête : {failure}",
            repairable=True,
        )
    return Verdict("ok", "", sql=final)
