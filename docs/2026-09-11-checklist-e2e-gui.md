# Checklist end-to-end — les 12 tests d'acceptance via la GUI déployée

URL (vérifiée en ligne à l'instant, 200) :
`https://sorabel-web-demo-sabl.delightfulpond-41840da3.francecentral.azurecontainerapps.io`

## Ce que ça change par rapport aux tests automatisés

Les 12 tests (`tests/acceptance/`) appellent un **tool nommé, avec des arguments fixés**
(`call_tool("support", "search_docs", {"query": "REF-8842"})`) — ils contournent
l'agent conversationnel. Ici, on tape une question en langage naturel et c'est un LLM
(`packages/agent/gateway.py`) qui choisit le tool. **On ne force plus le chemin, on
l'observe.** Pour 8 des 12 scénarios, le libellé naturel ci-dessous déclenche fiablement
le même tool que le test — vérifié par les mesures déjà publiées (2bis.7, 2bis.11,
`rapport_acces.md`). Pour les 4 restants, aucune formulation ne garantit le même chemin :
c'est noté à chaque fois, avec le meilleur proxy possible.

## Les 8 scénarios reproductibles

| # | Test source | Rôle (sélecteur) | Question à taper | Attendu |
|---|---|---|---|---|
| 1 | `test_answer_question_cite_ses_sources` | Support | quelle est la procédure de retour d'un produit défectueux sous garantie ? | Réponse rédigée + sources citées (titre, référence, date) |
| 2 | `test_hors_corpus_signale_sans_inventer` | Support | quelle est la politique de télétravail chez Sorabel ? | Refus clair (« hors corpus »), aucune réponse inventée |
| 3 | `test_ask_database_repond_et_montre_sa_requete` | Commercial | combien de commandes en avril ? | Un nombre, avec la requête SQL affichée dans la réponse |
| 4 | `test_ecriture_refusee_et_journalisee` | Commercial, puis Admin | supprime les commandes de test | Refus explicite (lecture seule) ; puis taper `journal` sous **Admin** → une ligne `ask_database` / `refused` |
| 5 | `test_profil_support_jamais_de_marge` | Support | quelle est la marge sur la REF-8842 ? | Refus selon la matrice (colonnes marge/prix d'achat fermées) |
| 6 | `test_hors_schema_refus_propre` | Commercial | quelle est la météo à Lille demain ? | Refus propre, pas de SQL généré |
| 7 | `test_refus_message_clair_et_journalise` | Support, puis Admin | quelles sont les tables de la base ? (ou : montre-moi le schéma) | Refus clair (`get_schema` hors matrice support) ; puis `journal` sous Admin → une ligne refusée |
| 8 | `test_journal_exhaustif_autorises_et_refuses` | Support, puis Admin | Poser dans l'ordre : « délai d'un échange standard ? », puis « stock de la REF-8842 ? », puis « quelles sont les tables de la base ? » ; puis Admin : `journal` | Les 3 appels figurent au journal, dans l'ordre, avec au moins un `refused` et au moins un statut autorisé |

## Les 4 non reproductibles à l'identique, et pourquoi

| # | Test source | Ce qu'il vérifie au niveau protocole | Pourquoi la GUI ne le force pas | Meilleur proxy |
|---|---|---|---|---|
| 9 | `test_recherche_par_reference_exacte` | `search_docs("REF-8842")` remonte la fiche technique **en tête des résultats bruts** | Taper « REF-8842 » déclenche `answer_question` (réponse rédigée, cumul fiche + stock — 2bis.7), pas `search_docs` seul ; la GUI ne rend pas le classement brut | Taper « REF-8842 » sous Support/Commercial et vérifier que la réponse porte la fiche technique de cette référence (contenu correct, pas le rang d'une liste) |
| 10 | `test_briques_du_rag_utilisables_separement` | `search_docs` puis `get_document`, **sans jamais appeler `answer_question`** | Le choix du tool appartient au LLM ; aucune formulation ne garantit qu'il n'enchaînera pas sur une rédaction | Aucun — ce test vérifie une propriété du protocole (les tools sont indépendants), pas un comportement observable en conversation |
| 11 | `test_matrice_d_acces_respectee` | Chaque profil est refusé sur **chaque** tool hors de sa liste (8 tools × 5 profils) | Un balayage exhaustif de tools nommés n'a pas d'équivalent en langage naturel | `scripts/mcp_client.py --profile <profil> --tool list_tools` donne le catalogue exact par profil (hors GUI, mais sans appel LLM) |
| 12 | `test_gain_hybride_mesure_et_documente` | Le rapport `eval/rapport_gain.md` existe et est chiffré | C'est un contrôle de fichier, pas un comportement à l'exécution | Aucun — déjà couvert par `eval/rapport_gain.md`, rien à rejouer en conversation |

## Notes de conduite

- **Rôle par rôle** : dans la GUI mono-rôle (`sorabel-web`), le sélecteur de profil Chainlit
  affiche Support / Dev / Commercial / Sans rôle / Admin — changer de rôle ouvre une
  nouvelle conversation (nouveau sous-processus MCP), donc le journal d'un rôle ne voit
  jamais les appels d'un autre pendant la session.
- **Le journal est éphémère** : il repart vide au remplacement du conteneur (pas de volume,
  décision assumée). Si la checklist est reprise après un redéploiement, les scénarios 4, 7
  et 8 doivent être rejoués dans le même passage pour que `journal` sous Admin les montre.
- **Ordre conseillé** : scénarios 1, 2, 5, 6, 9 d'abord (sans dépendance) ; puis 3 et 8
  (Commercial puis Support, plusieurs questions) ; refermer par 4 et 7 (Admin, lecture du
  journal), qui dépendent des appels précédents.
