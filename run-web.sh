#!/bin/sh
# Lancement du front Chainlit. Même motif que `run-api.sh` : le champ « Arguments » du
# portail ne découpe pas, donc rien ne doit y être saisi.
#
# `--headless` : sans lui Chainlit tente d'ouvrir un navigateur au démarrage.
exec chainlit run packages/web_client/app.py --host 0.0.0.0 --port "${PORT:-8100}" --headless
