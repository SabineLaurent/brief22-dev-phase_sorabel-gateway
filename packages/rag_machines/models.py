"""Commandes internes échangées avec l'exécuteur des tools documentaires."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RagToolRequest:
    """Appel documentaire normalisé à la frontière du paquet.

    ``profile`` est fourni par le processus gateway, jamais par les arguments du client.
    Les arguments restent structurés jusqu'au tool ; ils ne sont pas sérialisés en JSON
    entre deux composants qui vivent dans le même processus.
    """

    tool: str
    profile: str
    arguments: dict[str, Any] = field(default_factory=dict)
