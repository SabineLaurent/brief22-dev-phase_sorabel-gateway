"""Commandes internes échangées avec l'exécuteur des tools SQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SqlToolRequest:
    """Appel SQL normalisé à la frontière de la factory.

    ``profile`` est fourni par le processus gateway, jamais par les arguments du client.
    Les arguments restent structurés jusqu'au service ; ils ne sont pas sérialisés en JSON
    entre les deux composants qui vivent dans le même processus.
    """

    tool: str
    profile: str
    arguments: dict[str, Any] = field(default_factory=dict)
