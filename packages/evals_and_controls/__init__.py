"""Mesures **transverses aux deux domaines**.

Ce paquet existe pour une seule raison, et elle est structurelle : ``rag_machines`` et
``text_to_sql_factory`` ne s'importent pas l'un l'autre — leur seul lien est le protocole
``Journalable`` de ``packages/journal.py``. Une mesure qui porte sur les **huit** tools ne
peut donc vivre dans ni l'un ni l'autre sans y créer cette dépendance.

``eval_access``      mesure de l'axe 5 : E5 — étages d'arrêt, journalisation, colonnes fermées
"""
