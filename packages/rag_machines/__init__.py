"""Machinerie RAG de la Sorabel Data Gateway.

Deux temps, et ils ne se jouent pas au même moment : l'ingestion est hors ligne et se
rejoue par ``make ingest`` ; le reste sert une question.

Hors ligne — ``ingest/`` :

``normalize``           un fichier du corpus ramené à une **édition** : texte nettoyé,
                        métadonnées, ``classify()`` qui décide collection et thème sur le
                        seul identifiant
``registry``            la conversion attribut Python → clé de données, en **un seul
                        endroit** (``build_metadata()``) : le contrat prime sur le style
``index``               Chroma — connexion, collection, écriture, réconciliation
``cli``                 le point d'entrée de ``make ingest`` / ``reindex`` / ``ingest-brut``

En ligne, dans l'ordre où une question les traverse :

``access_rag``          N1 — le périmètre documentaire du profil, lu dans la matrice
                        (elle-même dans ``packages/access.py``, transverse aux huit tools).
                        Seul module qui connaisse à la fois la matrice et la recherche
``retrieval/perimeter`` le périmètre sous ses **deux formes exécutables** : un ``where``
                        pour Chroma, un prédicat pour BM25 — une seule règle, parce que
                        l'hybride fusionne les deux listes
``retrieval/embedder``  les vecteurs — Azure si configuré, sinon ``multilingual-e5-base``
``retrieval/lexical``   BM25, l'étage qui rattrape les références et les sigles
``retrieval/reranker``  le cross-encoder, ou le rerank LLM Azure — commutables
``retrieval/search``    N2 — les trois étages (dense · lexical · hybride RRF + rerank), la
                        règle de départage, le seuil de refus, et ``citation()`` : la
                        source est construite en Python, **jamais rédigée par un modèle**
``writer``              N3 — la rédaction : une passe, deux issues (une réponse, ou la
                        garde de suffisance). Le modèle rend les *numéros* des extraits
                        qu'il a utilisés, jamais leurs références
``tools``               les quatre tools documentaires, en fonctions Python

Puis la frontière :

``structured_answer``   la réponse comme **objet** : ``RagStructuredAnswer``, et
                        ``rag_client_view()`` — le seul sérialiseur du domaine
``handler``             le point de passage unique : l'étage 2, la journalisation, la
                        purge — **dans cet ordre**
``models``              ``RagToolRequest``, la commande normalisée

**Où passe la ligne bibliothèque / frontière.** ``tools.py`` reste de la bibliothèque
pure : appelé en direct — par ``check_rag_tools``, par exemple — il ne connaît que
l'étage 3, le périmètre documentaire, et n'écrit aucun journal. C'est ``handler.py`` qui
parle à un client : il applique l'étage 2 (``tool_interdit``), journalise l'objet
**entier**, puis rend la vue purgée.

**Le clivage entre les quatre tools est le mode d'adressage**, pas le niveau
(``03-catalogue-tools.md``) : ``answer_question`` et ``search_docs`` cherchent par
*similarité* et passent par le filtre d'index ; ``get_document`` et ``list_sources``
adressent par *identité* et ne l'empruntent pas — ils vérifient par
``Perimeter.allows()``, sans quoi la fermeture des notes serait contournable par un simple
chemin de fichier.

Le domaine métier a son pendant exact dans ``packages/text_to_sql_factory/``, et les deux
alimentent le même journal par le protocole ``Journalable`` de ``packages/journal.py``.

Les contrôles et les mesures vivent dans ``evals_and_controls/``.
"""
