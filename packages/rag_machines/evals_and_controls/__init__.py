"""Contrôles et mesures du chantier RAG.

Deux natures, et le protocole de mesure (``eval/protocole-mesure.md``) tient à ce qu'on ne
les confonde pas :

``check_index``      contrôles d'intégrité de l'index — déterministes, sans appel de modèle
``check_perimeter``  contrôles du filtre de périmètre documentaire, décomptes en or
``check_rag_tools``  contrôles des quatre tools et de leur journal, rédaction en doublure
``eval_rag``         mesure du gain E6, une configuration par cible Make
``eval_perimeter``   mesure de l'axe 3 : ce que coûte un filtre appliqué trop tard
"""
