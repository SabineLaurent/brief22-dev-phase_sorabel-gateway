"""Machinerie Text-to-SQL de la Sorabel Data Gateway.

Le chemin complet, dans l'ordre où il s'exécute (conception :
``docs/conception/LIVRABLES_CONCEPTION/04-chemin-text-to-sql.md``) :

``access_sql``          N1 — le périmètre du profil, lu dans la matrice (elle-même dans
                        ``packages/access.py``, transverse aux huit tools)
``contract``            N2 — le contrat de lecture : DDL filtré, énumérations, plage,
                        conventions
``generator``           N3 — une seule passe LLM, sortie structurée à trois branches, plus
                        une reprise sur requête fausse
``validator``           N4 · N5 — les cinq contrôles sur l'arbre (tables en 5a **avant**
                        colonnes en 5b), le ``LIMIT`` injecté, puis le contrôle 6 qui
                        confronte la requête au moteur par ``EXPLAIN``
``executor``            N6 · N7 — connexion neuve en lecture seule, bornée ; contrôles du
                        résultat ; ``explain()``, la sonde du contrôle 6
``tools``               les quatre tools SQL, en fonctions Python

Puis la frontière, ajoutée au chantier 3 :

``structured_answer``   la réponse comme **objet** : ``DbStructuredAnswer``, et
                        ``client_view()`` — le seul sérialiseur
``handler``             le point de passage unique : l'étage 2, la journalisation, la
                        purge — **dans cet ordre**
``sql_tool_launcher``   la vérification du tool, du profil et des arguments avant l'appel
``models``              ``SqlToolRequest``, la commande normalisée

**La distinction bibliothèque / frontière n'a pas disparu, elle s'est déplacée.**
``tools.py`` reste de la bibliothèque pure : appelé en direct — par ``check_sql``, par
exemple — il ne connaît que l'étage 3 et n'écrit aucun journal. C'est ``handler.py`` qui
parle à un client : il applique l'étage 2 (``tool_interdit``), journalise l'objet **entier**,
puis rend la vue purgée. Le domaine documentaire a son pendant exact dans
``packages/rag_machines/``, et les deux alimentent le même journal par le protocole
``Journalable`` de ``packages/journal.py``.
"""

#: Le dialecte parlé par sqlglot dans tout le paquet — analyse, qualification, génération
#: de la chaîne finale, sonde de l'exécuteur. Un seul point de bascule : la gateway ne
#: connaît qu'une base, mais le littéral répété six fois cachait ce fait au lieu de l'énoncer.
SQL_DIALECT = "sqlite"
