"""Machinerie Text-to-SQL de la Sorabel Data Gateway.

Le chemin complet, dans l'ordre où il s'exécute (conception :
``docs/conception/LIVRABLES_CONCEPTION/04-chemin-text-to-sql.md``) :

``access``     N1 — le périmètre du profil, lu dans la matrice
``contract``   N2 — le contrat de lecture : DDL filtré, énumérations, plage, conventions
``generator``  N3 — une seule passe LLM, sortie structurée à trois branches
``validator``  N4 · N5 — les cinq contrôles sur l'arbre, puis le ``LIMIT`` injecté
``executor``   N6 · N7 — connexion neuve en lecture seule, bornée ; contrôles du résultat
``tools``      les quatre tools SQL, en fonctions Python rendant l'enveloppe de la DSI

Ce paquet est une **bibliothèque** : il ne parle à aucun client et n'écrit aucun journal.
L'exposition MCP, l'étage 2 (``tool_interdit``) et le journal JSONL relèvent du chantier 3
— les fonctions de ``tools`` rendent tout ce qu'il faut pour journaliser.
"""

#: Le dialecte parlé par sqlglot dans tout le paquet — analyse, qualification, génération
#: de la chaîne finale, sonde de l'exécuteur. Un seul point de bascule : la gateway ne
#: connaît qu'une base, mais le littéral répété six fois cachait ce fait au lieu de l'énoncer.
SQL_DIALECT = "sqlite"
