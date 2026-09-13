"""Le journal de la gateway : une ligne JSONL par appel, servi comme refusé.

Ce module vit à la racine de ``packages/`` pour la même raison que ``packages/access.py`` :
le journal est **transverse aux huit tools**. Un fichier, un format, une fonction d'écriture
— sinon la forme des entrées divergerait entre le SQL et le documentaire, et le journal
cesserait d'être lisible d'un seul coup d'œil. C'est aussi la raison pour laquelle la
journalisation avait été reportée du chantier 2 au chantier 3 : l'écrire pour quatre tools
aurait obligé à la réécrire.

**Ce module ne connaît aucune forme de réponse client.** Il ne sait ni construire une
enveloppe, ni refuser un appel : il écrit et il relit. La conversion vers les trois champs
du contrat DSI appartient au module qui les possède — d'où le :class:`Journalable`
structurel plutôt qu'un import du paquet SQL, qui inverserait la dépendance et empêcherait
le RAG de s'y brancher sans détour.

**Le journal est l'autre lecteur.** Le client reçoit une phrase figée qui ne nomme rien ;
ici on écrit tout : le code, l'étage qui a tranché, les colonnes fermées, la requête
exécutée, la cause technique, la trace d'exception. Ce lecteur-là est humain, il débogue, et
il n'est pas un LLM. Deux besoins, deux vues, un seul objet à la source.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from config import Settings
from config import settings as default_settings


@runtime_checkable
class Journalable(Protocol):
    """Ce qu'une réponse de tool doit exposer pour être journalisable.

    Un protocole plutôt qu'une classe : le paquet SQL le satisfait aujourd'hui avec
    ``DbStructuredAnswer``, le RAG le satisfera demain avec le sien, et ce module n'a besoin
    d'importer ni l'un ni l'autre.
    """

    #: Tout en lecture seule : ce module lit une réponse, il n'en construit ni n'en modifie
    #: aucune. Déclarer les membres en propriétés le dit au vérificateur de types autant
    #: qu'au lecteur — et laisse la réponse être une dataclass figée.
    @property
    def code(self) -> str: ...
    @property
    def payload(self) -> dict[str, Any]: ...
    @property
    def cause(self) -> str: ...
    @property
    def stack(self) -> str: ...
    @property
    def forbidden(self) -> tuple[str, ...]: ...
    @property
    def etage(self) -> int | None: ...
    @property
    def status(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def refused(self) -> bool: ...
    @property
    def blocked_at(self) -> int | None: ...


def decision_of(answer: Journalable) -> str:
    """``allowed`` · ``denied`` · ``error`` — le champ que la conception réclame
    (``03-catalogue-tools.md`` §Journal).

    La ligne de partage n'est pas « ça a marché ou non », c'est **la gateway a-t-elle refusé
    de faire, ou n'a-t-elle pas pu ?** ``erreur_execution`` est le seul code où les deux
    notions se séparent : rien n'a été refusé, l'exécution a échoué. Les confondre ferait
    compter à E5 des refus qui n'ont jamais eu lieu.
    """
    if answer.refused:
        return "denied"
    if answer.status == "error":
        return "error"
    return "allowed"


def entry_for(tool: str, profile: str, arguments: dict[str, Any],
              answer: Journalable) -> dict[str, Any]:
    """L'entrée de journal, dans l'ordre où on la lit.

    Les six premiers champs sont ceux du contrat d'intégration
    (``docs/cadrage_dsi.md`` §Journal) — c'est ce que la suite d'acceptance relit. Les
    suivants viennent du dossier de conception, et ce sont eux qui rendent l'entrée utile au
    débug : ``etage`` est ce qui rend la défense en profondeur **vérifiable**, et ``cause``
    ce qui dit pourquoi, en clair.

    ``message`` porte la cause quand il y en a une : ce lecteur-ci veut le pourquoi, pas la
    formule d'accueil. Ce que l'utilisateur a réellement lu est conservé à côté, sous
    ``client_message`` — sans quoi un signalement (« on m'a affiché ceci ») serait
    impossible à raccorder à son appel.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "profile": profile,
        "tool": tool,
        "arguments": arguments,
        "status": answer.status,
        "message": answer.cause or answer.message,
        "code": answer.code,
        "decision": decision_of(answer),
        "etage": answer.etage,
        "blocked_at": answer.blocked_at,
        "sql": answer.payload.get("sql", ""),
        "n_rows": answer.payload.get("n_rows", 0),
        "latency_ms": answer.payload.get("latency_ms", 0.0),
        "forbidden": list(answer.forbidden),
        "cause": answer.cause,
        "client_message": answer.message,
        "stack": answer.stack,
    }


def record(tool: str, profile: str, arguments: dict[str, Any], answer: Journalable,
           settings: Settings | None = None) -> None:
    """Écrit une entrée, en ajout. Un appel, une ligne — autorisé comme refusé.

    ``ensure_ascii=False`` : le journal est relu par des humains francophones, et
    ``\\u00e9`` n'aide personne. ``default=str`` : un ``Path`` ou une ``date`` glissé dans
    les arguments ne doit pas faire échouer un appel par ailleurs correct — **journaliser ne
    doit jamais casser ce qu'on journalise**.
    """
    settings = settings or default_settings
    path = Path(settings.gateway_journal)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry_for(tool, profile, arguments, answer),
                      ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def tail(limit: int = 50, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Les ``limit`` dernières entrées, de la plus ancienne à la plus récente.

    Aucun contrôle de droits ici : le garde-fou appartient à l'appelant, qui seul connaît le
    profil et la matrice. Un journal absent rend une liste vide — ce n'est pas une erreur,
    c'est un journal qui n'a rien à dire.

    Une ligne illisible est **passée**, pas remontée en exception : un fichier tronqué par
    un arrêt brutal ne doit pas rendre les mille lignes valides inaccessibles.
    """
    path = Path(settings.gateway_journal if settings else default_settings.gateway_journal)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:] if limit > 0 else lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries
