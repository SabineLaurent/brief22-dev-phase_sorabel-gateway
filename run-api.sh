#!/bin/sh
# Lancement de l'API — le processus parent qui ouvre les serveurs MCP en sous-processus.
#
# POURQUOI UN SCRIPT PLUTÔT QUE LA COMMANDE AU PORTAIL : le champ « Arguments » d'Azure
# Container Apps transmet sa valeur comme UN SEUL argument — ni les virgules ni les espaces
# ne la découpent. Mesuré : `packages.agent.api:app --host,0.0.0.0 --port,8000` arrive à
# uvicorn en un bloc, et il cherche un attribut nommé « app --host,0.0.0.0 --port,8000 ».
# Un script ne laisse rien à découper : Commande = /app/run-api.sh, Arguments = vide.
#
# `--host 0.0.0.0` : sans lui uvicorn se lie à 127.0.0.1 et reste injoignable depuis
# l'extérieur du conteneur. PAS de `--reload` : son superviseur ajoute un étage de PID et
# casse la propagation des signaux, donc l'arrêt propre des sous-processus MCP.
exec uvicorn packages.agent.api:app --host 0.0.0.0 --port "${PORT:-8000}"
