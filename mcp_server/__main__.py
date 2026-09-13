"""Lancement du serveur par ``python -m mcp_server``.

Cette forme courte est celle que nomment ``note-transport.md`` §7 et l'exemple de
configuration client de ``Q3`` §2 (``"args": ["-m", "mcp_server"]``). La forme longue
``python -m mcp_server.server`` reste valide — c'est celle du contrat d'intégration de
``docs/cadrage_dsi.md`` et celle que lance la suite d'acceptance — et les deux mènent au
même :func:`mcp_server.server.main`.

Deux noms pour un point d'entrée, parce que deux documents en attendent chacun un, et
qu'aucun des deux n'est négociable : le cadrage est le contrat du client, la note de
transport est la décision de conception.
"""

from mcp_server.server import main

main()
