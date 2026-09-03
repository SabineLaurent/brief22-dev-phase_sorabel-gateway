"""Contrôles d'intégrité de la machinerie Text-to-SQL.

À lancer après `make seed`. Rejoue, sur la base réelle, **les cas mesurés dans le dossier
de conception** — ceux de `2-text-to-sql/Q2.md` §6, `Q3.md` §8 et `Q4.md` §7 — et vérifie
que le code rend le verdict que la conception annonce.

**Aucun appel de modèle.** Ce script couvre ce qui est déterministe : le périmètre, la
validation d'AST, l'essai à blanc du contrôle 6, les bornes d'exécution et les deux tools
figés — c'est-à-dire E3 et E5. La génération, elle, ne l'est pas ; elle se mesure séparément
par `eval_sql`.

La boucle de reprise du contrôle 6 est exercée par `_ScriptedGenerator`, une **doublure de
test** définie plus bas : elle rend des requêtes écrites d'avance pour que le chemin de la
reprise soit parcouru sans appeler aucun modèle. Voir sa docstring pour le détail.

Un contrôle qui plante ne contrôle rien : le script est écrit pour **rapporter** les
verdicts, y compris quand ils sont faux, et non pour lever une exception dessus.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from config import settings
from packages.text_to_sql_factory.access import scope_for
from packages.text_to_sql_factory.contract import ReadContract, build_read_contract
from packages.text_to_sql_factory.executor import execute, explain
from packages.text_to_sql_factory.generator import Generation, SqlGenerator, clarification_axes
from packages.text_to_sql_factory.tools import ask_database, check_stock, get_schema, order_status
from packages.text_to_sql_factory.validator import validate

#: Les trois colonnes sensibles. Elles sont un seul secret en trois exemplaires :
#: `marge_pct` se dérive de `prix_achat_ht` sur 120 produits sur 120, et `prix_achat_ht` de
#: `marge_ht` sur 993 lignes de vente sur 993. Les trois sont fermées ensemble ou aucune.
SENSITIVE = ("prix_achat_ht", "marge_pct", "marge_ht")

#: Les cas de validation, avec le code attendu. Chacun vient d'un contournement **mesuré**
#: dans la conception, pas d'une précaution de principe.
VALIDATION_CASES: tuple[tuple[str, str, str, str], ...] = (
    ("commercial", "SELECT COUNT(*) FROM commandes", "ok", "lecture nominale"),
    ("commercial", "DELETE FROM commandes", "ecriture_refusee", "suppression"),
    ("commercial", "UPDATE produits SET prix_vente_ht=1", "ecriture_refusee", "mise à jour"),
    ("commercial", "INSERT INTO clients VALUES ('x','y','z','w','v')", "ecriture_refusee",
     "insertion"),
    ("commercial", "DROP TABLE ventes", "ecriture_refusee", "suppression de table"),
    ("commercial", "CREATE TABLE p.vol AS SELECT * FROM produits", "ecriture_refusee",
     "copie par CREATE AS SELECT"),
    ("commercial", "VACUUM INTO '/tmp/copie.db'", "ecriture_refusee",
     "exfiltration par VACUUM INTO"),
    ("commercial", "ATTACH DATABASE '/tmp/x.db' AS p", "ecriture_refusee", "ATTACH"),
    ("commercial", "DETACH DATABASE p", "ecriture_refusee", "DETACH"),
    ("commercial", "PRAGMA query_only=OFF", "ecriture_refusee", "désarmement du PRAGMA"),
    ("commercial", "SELECT 1; SELECT 2", "ecriture_refusee", "deux instructions"),
    ("support", "SELECT marge_pct FROM produits", "perimetre_interdit", "colonne projetée"),
    ("support", "SELECT ref FROM produits ORDER BY marge_pct DESC", "perimetre_interdit",
     "colonne en ORDER BY, non projetée"),
    ("support", "SELECT 1 FROM produits WHERE marge_pct > 47", "perimetre_interdit",
     "colonne en WHERE — la dichotomie booléenne"),
    ("support", "SELECT p.nom, SUM(v.marge_ht) FROM ventes v JOIN produits p ON p.ref=v.ref"
                " GROUP BY 1", "perimetre_interdit", "colonne derrière un alias"),
    ("support", "WITH t AS (SELECT ref, marge_pct FROM produits) SELECT ref FROM t",
     "perimetre_interdit", "colonne dans une CTE"),
    ("support", "SELECT * FROM produits", "perimetre_interdit", "étoile développée"),
    ("commercial", "SELECT * FROM clients", "perimetre_interdit",
     "étoile sur clients — email est fermée aux quatre profils"),
    ("support", "SELECT p.nom FROM produits p JOIN stocks s ON s.ref=p.ref", "ok",
     "jointure licite, non bloquée"),
    ("support", "SELECT ref FROM produits WHERE inexistante = 1", "erreur_execution",
     "colonne inventée : fausse, pas interdite"),
    ("default", "SELECT ref FROM produits", "perimetre_interdit", "profil sans périmètre"),

    # Contrôle 5a — les tables. Sans lui, une table hors matrice emporte ses colonnes :
    # `qualify` ne les résout pas, la règle d'alias les écarte, et le DDL complet sort.
    ("support", "SELECT sql FROM sqlite_master", "perimetre_interdit",
     "table hors matrice : le DDL porte les marges"),
    ("support", "SELECT * FROM sqlite_master", "perimetre_interdit",
     "table hors matrice, sans aucune colonne nommée"),
    ("support", "SELECT * FROM generate_series(1,10)", "perimetre_interdit",
     "source sans nom de table"),

    # Contrôle 6 — l'essai à blanc. Ce que l'arbre ne peut pas voir.
    ("support", "SELECT zzz FROM commandes", "erreur_execution",
     "colonne inventée en projection — sinon servie comme la chaîne 'zzz'"),
    ("support", "SELECT DATE_TRUNC('month', date_commande) FROM commandes",
     "erreur_execution", "fonction que sqlglot n'a pas su transposer"),
    ("support", "SELECT id FROM commandes c JOIN clients cl ON c.client_id=cl.id",
     "erreur_execution", "colonne ambiguë entre deux tables jointes"),

    # Ce que le bloc `unknown` retiré refusait à tort : le moteur, lui, résout.
    ("support", "WITH t AS (SELECT ref, quantite FROM stocks) SELECT ref, SUM(quantite)"
                " FROM t GROUP BY ref", "ok", "CTE légitime"),
    ("support", "SELECT x.ref FROM (SELECT ref FROM produits) x", "ok",
     "sous-requête en FROM"),
)


class _ScriptedGenerator(SqlGenerator):
    """**Doublure de test. Sert uniquement à ce script, jamais au chemin servi.**

    Un générateur qui rend des requêtes écrites d'avance, sans appeler aucun modèle. Il
    n'imite pas l'intelligence du modèle — il n'en a aucune : il tient sa **place** dans le
    pipeline pour que tout le reste du chemin tourne pour de vrai (`ask_database` →
    `validate` → contrôle 6 → reprise → `validate` → `execute`).

    **Pourquoi il faut le construire au lieu d'appeler le modèle.** La boucle de reprise ne
    se déclenche que sur une requête que l'`EXPLAIN` refuse, et le vrai modèle n'en produit
    pas : le contrat lui impose SQLite. Vérifié — les 24 questions du jeu, plus trois
    questions temporelles écrites exprès pour le pousser vers `DATE_TRUNC`, ont toutes donné
    du SQLite correct (`STRFTIME`, `SUBSTRING`). Sans doublure, le code de la reprise ne
    serait **exécuté nulle part**, et l'invariant qui compte — aucune reprise sur un refus
    de droits — ne serait vérifié nulle part.

    S'y ajoutent les deux raisons qui valent pour tout ce script : la sortie du modèle varie
    d'un appel à l'autre, donc le contrôle passerait ou échouerait au hasard ; et
    `check_sql` est le script déterministe du projet, sans appel de modèle par construction.
    Les 24 appels réels vivent dans `eval_sql`, séparément.

    Une fois la liste épuisée, il constate la panne plutôt que de recycler la dernière
    requête — répéter la même relancerait la boucle sans fin si jamais le plafond d'une
    reprise sautait.
    """

    def __init__(self, answers: list[str]) -> None:
        super().__init__("", "", "scripté")
        self._answers = list(answers)
        #: Les invites vues, pour vérifier que l'erreur du moteur est bien transmise.
        self.seen: list[str] = []

    def generate(self, question: str, contract: ReadContract,  # type: ignore[override]
                 axes: tuple[str, ...] = (),
                 rejected: tuple[str, str] | None = None) -> Generation:
        if rejected is not None:
            self.repairs += 1
            self.seen.append(f"{rejected[0]} | {rejected[1]}")
        if not self._answers:
            return Generation("panne", reason="générateur scripté épuisé")
        return Generation("sql", sql=self._answers.pop(0))


def main() -> int:
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

    database = Path(settings.sorabel_db)
    print("Base :", database)
    if not database.exists():
        print("\nBase absente : les contrôles sont sans objet. Lancer `make seed`.")
        return 1
    print("Matrice :", settings.matrix_path)

    print("\nPérimètre — décompte de contrôle sur les 31 colonnes de la base")
    check("colonnes du profil commercial", len(scope_for("commercial").columns), 28)
    check("colonnes du profil support", len(scope_for("support").columns), 25)
    check("colonnes du profil dev", len(scope_for("dev").columns), 25)
    check("colonnes du profil default", len(scope_for("default").columns), 0)
    check("un profil inconnu retombe sur default", scope_for("Xyz").profile, "default")
    check("clients.email fermée aux quatre profils",
          any(("clients", "email") in scope_for(p).columns
              for p in ("default", "dev", "support", "commercial")), False)

    print("\nContrat de lecture — ce que le modèle a le droit de voir")
    for profile, visible in (("commercial", True), ("support", False), ("dev", False)):
        text = build_read_contract(profile).as_text()
        cited = sorted(name for name in SENSITIVE if name in text)
        check(f"colonnes sensibles citées au profil {profile}",
              bool(cited), visible)
    support_contract = build_read_contract("support")
    check("exemples proposés au support", len(support_contract.examples), 3)
    check("exemples proposés au commercial", len(build_read_contract("commercial").examples), 4)
    check("axes de clarification au support", len(clarification_axes("support")), 4)
    check("axes de clarification au commercial", len(clarification_axes("commercial")), 5)
    check("plage temporelle annoncée", support_contract.date_range,
          ("2025-09-04", "2026-08-19"))

    print("\nValidation — les contournements mesurés de Q2 §6 et Q3 §8")
    for profile, sql, expected, label in VALIDATION_CASES:
        check(f"{label} ({profile})", validate(sql, profile).code, expected)

    print("\nLe refus nomme la colonne")
    named = validate("SELECT * FROM produits", "support").forbidden
    check("colonnes nommées par le refus", named,
          (("produits", "marge_pct"), ("produits", "prix_achat_ht")))

    print("\nBornes — le LIMIT injecté, jamais élargi")
    check("aucun LIMIT : injecté à la valeur par défaut",
          validate("SELECT ref FROM produits", "support").sql.endswith(
              f"LIMIT {settings.sql_default_limit}"), True)
    check("LIMIT plus petit : conservé",
          validate("SELECT ref FROM produits LIMIT 5", "support").sql.endswith("LIMIT 5"), True)
    check("LIMIT plus grand : ramené au défaut",
          validate("SELECT ref FROM produits LIMIT 5000", "support").sql.endswith(
              f"LIMIT {settings.sql_default_limit}"), True)
    check("plafond de lignes appliqué",
          execute("SELECT * FROM ventes, commandes").n_rows, settings.sql_max_rows)
    check("plafond signalé comme troncature",
          execute("SELECT * FROM ventes, commandes").truncated, True)

    print("\nConnexion — la lecture seule tient sans passer par le validateur (C2)")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, isolation_level=None)
    connection.execute("PRAGMA query_only=ON")
    for label, sql in (("UPDATE refusé par la connexion", "UPDATE produits SET prix_vente_ht=1"),
                       ("VACUUM INTO refusé par la connexion", "VACUUM INTO '/tmp/sorabel.db'")):
        try:
            connection.execute(sql)
            check(label, "passé", "refusé")
        except sqlite3.Error:
            check(label, "refusé", "refusé")
    connection.close()

    print("\nExécution et contrôles du résultat (N7)")
    check("T1 — commandes d'avril 2026",
          execute("SELECT COUNT(*) FROM commandes WHERE date_commande LIKE '2026-04-%'").rows,
          [[27]])
    check("stock total de REF-8842 (SUM, pas la première ligne)",
          execute("SELECT SUM(quantite) FROM stocks WHERE ref='REF-8842'").rows, [[774]])
    check("résultat vide → aucune ligne, pas un refus",
          execute("SELECT id FROM commandes WHERE id='CMD-2026-0042'").code, "aucune_ligne")
    check("désignation par libellé homonyme → ambiguïté",
          execute("SELECT ref, nom FROM produits WHERE nom LIKE '%tétrapolaire%40 A%'").code,
          "ambiguite_donnees")
    check("liste légitime de 11 lignes → pas une ambiguïté",
          execute("SELECT id FROM commandes WHERE statut='livree' "
                  "AND date_commande LIKE '2026-06-%'").code, "ok")
    check("égalité à la frontière du classement (374 = 374)",
          execute("SELECT ref, SUM(quantite) s FROM ventes GROUP BY ref "
                  "ORDER BY s DESC LIMIT 1").code, "ambiguite_donnees")
    check("top 5 : l'égalité n'est pas à la frontière",
          execute("SELECT ref, SUM(quantite) s FROM ventes GROUP BY ref "
                  "ORDER BY s DESC LIMIT 5").code, "ok")
    # SQLite traite un identifiant entre guillemets doubles qui ne résout pas comme une
    # chaîne : `SELECT "zzz"` rendait 200 lignes de « zzz », servies comme un résultat.
    # `quote_identifiers=False` au contrôle 5b, puis le contrôle 6, ferment les deux moitiés.
    check("colonne inventée : rien d'exécutable n'est rendu",
          validate("SELECT zzz FROM commandes", "support").sql, "")
    check("EXPLAIN refuse la colonne inventée",
          bool(explain("SELECT zzz FROM commandes")), True)
    check("EXPLAIN laisse passer la même, entre guillemets — d'où quote_identifiers=False",
          bool(explain('SELECT "zzz" FROM commandes')), False)

    print("\nPasse de réparation — une reprise, et seulement sur une requête fausse")
    # Le modèle réel écrit du SQLite correct : le contrat le lui impose, et les 24 questions
    # du jeu ne déclenchent aucune reprise. Le chemin ne serait donc jamais exercé. Un
    # générateur en dur le rend déterministe — et surtout, il épingle l'invariant : un refus
    # de droits ne se renégocie pas.
    scripted = _ScriptedGenerator([
        "SELECT DATE_TRUNC('month', date_commande) AS mois FROM commandes GROUP BY mois",
        "SELECT STRFTIME('%Y-%m', date_commande) AS mois FROM commandes GROUP BY mois",
    ])
    answer = ask_database("les commandes par mois", "commercial", settings, scripted)
    check("une requête fausse déclenche une reprise", scripted.repairs, 1)
    check("la reprise est exécutée", answer["payload"]["code"], "ok")
    check("c'est bien la seconde requête qui sert",
          "STRFTIME" in str(answer["payload"]["sql"]), True)
    check("l'erreur du moteur a été rendue au modèle",
          any("DATE_TRUNC" in prompt for prompt in scripted.seen), True)

    forbidden = _ScriptedGenerator(["SELECT marge_pct FROM produits"])
    answer = ask_database("les marges", "support", settings, forbidden)
    check("un refus de droits ne déclenche aucune reprise", forbidden.repairs, 0)
    check("et reste un refus de droits", answer["payload"]["code"], "perimetre_interdit")

    exhausted = _ScriptedGenerator([
        "SELECT DATE_TRUNC('month', date_commande) FROM commandes",
        "SELECT NOW() FROM commandes",
    ])
    answer = ask_database("les commandes par mois", "commercial", settings, exhausted)
    check("une reprise, jamais deux", exhausted.repairs, 1)
    check("reprise ratée → le refus de la seconde tentative",
          answer["payload"]["code"], "erreur_execution")

    print("\nTools figés")
    stock = check_stock("REF-8842", "support")
    check("check_stock — une ligne par entrepôt", len(stock["payload"]["rows"]), 3)
    check("check_stock — le total, jamais la première ligne", stock["payload"]["total"], 774)
    check("check_stock — sous_seuil par ligne, non agrégé",
          [row[3] for row in stock["payload"]["rows"]], [0, 0, 0])
    check("check_stock — libellé refusé", check_stock("disjoncteur", "support")["status"], "error")
    check("check_stock — référence absente → aucune ligne",
          check_stock("REF-9999", "support")["payload"]["code"], "aucune_ligne")
    order = order_status("CMD-2025-0042", "support")
    check("order_status — en-tête de la commande", order["payload"]["rows"],
          [["CMD-2025-0042", "livree", "2025-11-22", 28524.27, "CLI-1015"]])
    check("order_status — CMD-2026-0042 n'existe pas, ce n'est pas un refus",
          order_status("CMD-2026-0042", "support")["payload"]["code"], "aucune_ligne")
    check("order_status — identifiant malformé",
          order_status("42", "support")["status"], "error")

    print("\nEnveloppe et périmètre des tools")
    check("get_schema — le support y a droit ici, le serveur MCP tranchera l'étage 2",
          get_schema("support")["status"], "ok")
    check("get_schema — profil sans périmètre", get_schema("default")["status"], "refused")
    check("ask_database — profil sans périmètre, aucun appel de modèle",
          ask_database("combien de commandes ?", "default")["payload"]["code"],
          "perimetre_interdit")
    refused = ask_database("combien de commandes ?", "default")
    check("un refus ne porte aucune ligne", "rows" in refused["payload"], False)

    return verdict()


if __name__ == "__main__":
    sys.exit(main())
