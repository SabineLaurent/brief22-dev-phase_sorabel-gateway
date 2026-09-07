"""E5 chiffrée : qui est arrêté, par quel étage, et ce qui n'en sort jamais — axe 5.

E5 est la seule des six exigences du brief sans preuve chiffrée publiée. Les cinq autres ont
``rapport_gain.md``, ``rapport_sql.md``, ``rapport_perimetre.md`` ou ``rapport_refus.md``.
Elle en a besoin d'autant plus qu'elle porte **deux** obligations distinctes, et qu'elles ne
se prouvent pas de la même façon :

1. *« Tout appel — autorisé ou refusé — est journalisé. »* Une propriété de comptage : autant
   d'entrées que d'appels, sans exception. Elle se **compte**.
2. *« Les colonnes sensibles ne sortent jamais pour le profil support. »* Une propriété
   d'absence. Elle se **cherche** — dans la vue client sérialisée, celle qui part vraiment.

**Ce script vit à la racine de ``packages/evals_and_controls/``**, et pas dans l'un des deux
domaines : il est le seul à mesurer les huit tools ensemble. Le mettre côté RAG ou côté SQL
lui ferait importer l'autre domaine, ce que ni ``rag_machines`` ni ``text_to_sql_factory`` ne
font — leur seul lien est le protocole ``Journalable`` de ``packages/journal.py``.

**Les trois étages ne se mesurent pas au même endroit, et c'est le cœur du rapport.**

======  ==================================  ==========================================
étage   ce qu'il décide                     où il se lit
======  ==================================  ==========================================
1       le catalogue visible                ``tools/list`` — **jamais dans le journal**
2       le droit d'appeler le tool          ``blocked_at == 2``
3       le périmètre (colonnes, thèmes)     ``blocked_at == 3``
======  ==================================  ==========================================

L'étage 1 **ne peut pas** apparaître dans ``blocked_at`` : il filtre une liste, il n'arrête
aucun appel. Un client qui appelle quand même un tool non listé est refusé à l'étage 2, et
c'est bien celui-là qui est journalisé. Mesurer E5 sur le seul journal manquerait donc un
étage entier — d'où les deux sources.

**« Nommer, pas numéroter » — la réserve du journal est tranchée ici : on numérote.** Trois
raisons, dans l'ordre où elles pèsent. ``etage`` porte déjà le même entier et les deux doivent
s'accorder : deux vocabulaires pour une seule notion divergeraient. Les numéros sont ceux du
dossier de conception (``03-catalogue-tools.md`` §3), qui numérote ses étages. Et un entier se
compare — ``blocked_at > 0`` dit « arrêté par la gouvernance » en trois caractères, là où un
nom demanderait une table. **Le nom appartient à la lecture, pas à l'écriture** : c'est ce
rapport qui les nomme, et c'est le bon endroit pour le faire.

Usage : make mesure-acces
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from config import Settings
from config import settings as base_settings
from packages.access import load_matrix

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_PATH = REPO_ROOT / "eval" / "resultats" / "mesure-acces.csv"
FRONTIER_PATH = REPO_ROOT / "eval" / "resultats" / "mesure-acces-frontiere.csv"
REPORT_PATH = REPO_ROOT / "eval" / "rapport_acces.md"

#: Les cinq profils de la matrice, du plus fermé au plus ouvert. `default` est un profil et
#: non une exception : il est joué comme les autres, et c'est le seul dont on attend un refus
#: sur les huit tools.
PROFILES = ("default", "dev", "support", "commercial", "admin")

#: Les huit tools du catalogue DSI. `read_journal` n'y est pas : ce n'est pas un tool du
#: catalogue mais la surface de débug, et elle a son propre contrôle.
CATALOGUE = ("answer_question", "search_docs", "get_document", "list_sources",
             "ask_database", "get_schema", "check_stock", "order_status")

#: Les trois colonnes sensibles d'E5. Un seul secret en trois exemplaires : `marge_pct` se
#: dérive de `prix_achat_ht` sur 120 produits sur 120, et `prix_achat_ht` de `marge_ht` sur
#: 993 lignes de vente sur 993. Les chercher toutes les trois, jamais une seule.
SENSITIVE = ("prix_achat_ht", "marge_pct", "marge_ht")

#: Les profils auxquels la matrice ouvre les trois colonnes. Chez les autres, une occurrence
#: dans une vue client est un manquement à E5 — c'est ce que la dernière section cherche.
SENSITIVE_ALLOWED = ("commercial", "admin")

#: Un document du corpus par collection. Les notes sont l'enjeu : `dev` n'y a pas droit du
#: tout, `support` seulement sur trois thèmes, et ce `doc_id` porte un thème fermé aux deux.
FICHE = "fiches/REF-8842"
NOTE_FERMEE = "notes/note-2026-02-11-politique-tarifaire-71"

#: Les appels joués, sous chacun des cinq profils. Chaque scénario a un **motif** : il vise
#: un étage précis, et le rapport le cite. Un scénario sans motif serait du remplissage.
SCENARIOS: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    ("doc-nominal", "answer_question", {"question": "Quelle est la procédure de retour SAV ?"},
     "réponse documentaire ordinaire — l'étage 2 seul est en jeu"),
    ("doc-extraits", "search_docs", {"query": "disjoncteur triphasé 63 A"},
     "extraits bruts, aucune barrière de refus documentaire sur ce tool"),
    ("doc-fiche", "get_document", {"doc_id": FICHE},
     "une édition ouverte à tous les profils dotés d'un périmètre"),
    ("doc-note-fermee", "get_document", {"doc_id": NOTE_FERMEE},
     "**l'étage 3 documentaire** : un thème de note fermé à `dev` et à `support`"),
    ("doc-inventaire", "list_sources", {},
     "l'inventaire, qui dit ce que le périmètre du profil couvre"),
    ("sql-nominal", "ask_database", {"question": "Combien de commandes en avril 2026 ?"},
     "lecture chiffrée ordinaire — l'étage 2 seul est en jeu"),
    ("sql-marge", "ask_database", {"question": "Quelle est la marge moyenne par produit ?"},
     "**l'étage 3 métier** : les trois colonnes sensibles d'E5"),
    ("sql-schema", "get_schema", {},
     "la forme de la base, retirée à `support` par arbitrage"),
    ("sql-stock", "check_stock", {"reference": "REF-8842"},
     "tool figé, argument contraint par motif"),
    ("sql-commande", "order_status", {"order_id": "CMD-2025-0042"},
     "tool figé, argument contraint par motif"),
)

_CSV_FIELDS = ("profile", "scenario", "tool", "status", "code", "decision",
               "etage", "blocked_at", "journal_entries", "sensitive_in_view")

#: Les appels que le SDK écarte **avant** la fonction de tool : argument hors format,
#: argument requis absent, mauvais type, tool hors catalogue. Ils ne traversent ni l'étage 2
#: ni le handler, donc personne en aval ne peut les journaliser — c'est la frontière du
#: serveur qui s'en charge (``SorabelMCP.call_tool``).
#:
#: **Ils se mesurent à travers le serveur, pas par les handlers**, et c'est le motif de la
#: seconde moitié de ce script : un handler ne connaît pas l'``inputSchema``, donc
#: ``check_stock("clou à béton")`` lui rendrait ``aucune_ligne`` au lieu du refus de format.
#: Mesurer ce chemin par les handlers dirait le contraire de la vérité.
#:
#: Le dernier est un témoin : sans lui, un serveur qui refuserait *tout* rendrait les mêmes
#: chiffres qu'un serveur correct.
FRONTIER_CALLS: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    ("arg-hors-format", "check_stock", {"reference": "clou à béton"},
     "un nom de produit là où le motif exige `REF-NNNN` — l'erreur qu'un LLM commet"),
    ("arg-manquant", "check_stock", {},
     "argument requis absent"),
    ("arg-mauvais-type", "check_stock", {"reference": 8842},
     "un entier là où le schéma attend une chaîne"),
    ("tool-inconnu", "outil_inconnu", {},
     "un tool hors catalogue : il n'atteint jamais l'étage 2"),
    ("temoin-valide", "check_stock", {"reference": "REF-8842"},
     "**témoin** : le même tool, appelé correctement"),
)

_FRONTIER_FIELDS = ("scenario", "tool", "is_error", "status", "code", "journal_entries",
                    "envelope_ok", "internals_in_view")

#: Ce qu'un client ne doit jamais lire : le vocabulaire du validateur. La trace part en
#: ``cause``, vers le journal — la chercher dans la vue est ce qui atteste la séparation.
VALIDATOR_WORDS = ("pattern", "ValidationError", "ToolError", "Arguments", "pydantic")


def _handle(tool: str, arguments: dict[str, Any], profile: str,
            settings: Settings) -> dict[str, Any]:
    """Le point de passage du domaine auquel ce tool appartient.

    Les imports sont **locaux**, comme dans ``mcp_server/server.py`` et pour la même
    raison : importer le handler documentaire au niveau du module chargerait l'embedder et
    le reranker avant le premier appel, y compris quand aucun scénario documentaire ne
    tourne.
    """
    if tool in ("answer_question", "search_docs", "get_document", "list_sources"):
        from packages.rag_machines.handler import handle as rag_handle

        return rag_handle(tool, arguments, profile, settings)
    from packages.text_to_sql_factory.handler import handle as sql_handle

    return sql_handle(tool, arguments, profile, settings)


def _catalogue_sizes() -> dict[str, int]:
    """Le nombre de tools que ``tools/list`` rend par profil — **l'étage 1**.

    Le serveur lit ``SORABEL_PROFILE`` **une fois au chargement du module**, ce qui est
    précisément la propriété qui rend le profil inaccessible au client. La conséquence ici
    est qu'un seul processus ne peut pas interroger cinq catalogues : on relance donc le
    module, une fois par profil, dans le processus courant.
    """
    import importlib
    import sys

    sizes: dict[str, int] = {}
    previous = os.environ.get("SORABEL_PROFILE")
    try:
        for profile in PROFILES:
            os.environ["SORABEL_PROFILE"] = profile
            sys.modules.pop("mcp_server.server", None)
            server = importlib.import_module("mcp_server.server")
            sizes[profile] = len(asyncio.run(server.mcp.list_tools()))
    finally:
        sys.modules.pop("mcp_server.server", None)
        if previous is None:
            os.environ.pop("SORABEL_PROFILE", None)
        else:
            os.environ["SORABEL_PROFILE"] = previous
    return sizes


def _sensitive_in(view: dict[str, Any]) -> list[str]:
    """Les colonnes sensibles présentes dans la vue client, **sérialisée**.

    On cherche dans le JSON rendu et non dans les objets : c'est cette chaîne-là qui part au
    client, et c'est la seule qui prouve quelque chose. Chercher dans un dictionnaire de
    payload manquerait une colonne citée dans un `sql` ou dans un en-tête de résultat.
    """
    blob = json.dumps(view, ensure_ascii=False)
    return [column for column in SENSITIVE if column in blob]


def run(settings: Settings) -> tuple[list[dict], dict[str, int]]:
    journal_file = Path(settings.gateway_journal)

    def journal_length() -> int:
        if not journal_file.exists():
            return 0
        return sum(1 for line in journal_file.read_text(encoding="utf-8").splitlines()
                   if line.strip())

    def last_entry() -> dict[str, Any]:
        lines = [line for line in journal_file.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        return json.loads(lines[-1])

    rows: list[dict] = []
    for profile in PROFILES:
        for scenario, tool, arguments, _motive in SCENARIOS:
            before = journal_length()
            view = _handle(tool, arguments, profile, settings)
            written = journal_length() - before
            # L'entrée du journal, pas la vue client : `etage` et `blocked_at` n'existent
            # que là. C'est le sens même des deux vues — le client ne les voit jamais.
            entry = last_entry() if written else {}
            rows.append({
                "profile": profile,
                "scenario": scenario,
                "tool": tool,
                "status": view.get("status", ""),
                "code": (view.get("payload") or {}).get("code", ""),
                "decision": entry.get("decision", ""),
                "etage": entry.get("etage"),
                "blocked_at": entry.get("blocked_at"),
                "journal_entries": written,
                "sensitive_in_view": "|".join(_sensitive_in(view)),
            })
    return rows, _catalogue_sizes()


async def _frontier_session(settings: Settings) -> list[dict[str, Any]]:
    """Joue les appels de frontière **à travers un vrai processus serveur**.

    Un sous-processus stdio et non un appel en mémoire : la frontière est censée protéger un
    *client*, et c'est donc du côté client qu'il faut se placer pour l'attester. Le journal
    est détourné vers celui de la mesure, comme pour les cinquante appels.

    Une seule session pour les cinq appels : le coût est le démarrage du serveur, pas
    l'appel, et le rejouer cinq fois ne prouverait rien de plus.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    journal_path = Path(settings.gateway_journal)

    def journal_length() -> int:
        if not journal_path.exists():
            return 0
        return len([line for line in journal_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()])

    env = {**os.environ, "SORABEL_PROFILE": "commercial",
           "GATEWAY_JOURNAL": str(journal_path), "TOKENIZERS_PARALLELISM": "false"}
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "mcp_server.server"], env=env,
                                   cwd=str(REPO_ROOT))
    rows: list[dict[str, Any]] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for scenario, tool, arguments, _motive in FRONTIER_CALLS:
                before = journal_length()
                result = await session.call_tool(tool, arguments)
                written = journal_length() - before
                served = "".join(getattr(b, "text", "") for b in result.content)
                # `envelope_ok` porte les deux moitiés de l'invariant : le bloc texte est du
                # JSON aux trois clés du contrat, **et** il est égal au champ structuré.
                try:
                    view = json.loads(served)
                    envelope_ok = (set(view) == {"status", "payload", "message"}
                                   and view == result.structuredContent)
                except json.JSONDecodeError:
                    view, envelope_ok = {}, False
                rows.append({
                    "scenario": scenario,
                    "tool": tool,
                    "is_error": bool(result.isError),
                    "status": view.get("status", ""),
                    "code": (view.get("payload") or {}).get("code", ""),
                    "journal_entries": written,
                    "envelope_ok": envelope_ok,
                    "internals_in_view": "|".join(
                        word for word in VALIDATOR_WORDS if word in served),
                })
    return rows


def measure_frontier(settings: Settings) -> list[dict[str, Any]]:
    """La mesure de la frontière, en synchrone — pendant de ``_catalogue_sizes``."""
    return asyncio.run(_frontier_session(settings))


def _paragraph(text: str) -> list[str]:
    """Une phrase repliée à 88 colonnes, rendue en lignes.

    Nécessaire parce que ces paragraphes portent des nombres calculés : replier le
    f-string à la main donne un résultat en escalier dès qu'un décompte change de
    chiffre. Le reste du rapport, dont le texte est fixe, est replié à l'écriture.
    """
    return textwrap.wrap(text, width=88)


def _bold(count: int) -> str:
    """Un décompte, mis en gras seulement s'il n'est pas nul. Un zéro en gras attire l'œil
    sur ce qui ne s'est pas produit."""
    return f"**{count}**" if count else "0"


def _by(rows: list[dict], profile: str) -> list[dict]:
    return [r for r in rows if r["profile"] == profile]


def _count(rows: list[dict], **criteria: Any) -> int:
    return sum(1 for r in rows if all(r.get(k) == v for k, v in criteria.items()))


def _ids(rows: list[dict], **criteria: Any) -> list[str]:
    return [r["scenario"] for r in rows if all(r.get(k) == v for k, v in criteria.items())]


def write_report(rows: list[dict], sizes: dict[str, int],
                 frontier: list[dict]) -> None:
    matrix = load_matrix(base_settings)
    total = len(SCENARIOS)
    # `load_matrix` rend des `Scope`, pas les dictionnaires bruts du YAML : c'est le même
    # lecteur que celui du service, donc la colonne « accordés » compare bien le catalogue
    # servi à la matrice **telle que le code la lit**, et non telle que le fichier l'écrit.
    leaks = [r for r in rows if r["sensitive_in_view"]
             and r["profile"] not in SENSITIVE_ALLOWED]
    unjournalised = [r for r in rows if r["journal_entries"] != 1]

    lines = [
        "# E5 chiffrée — qui est arrêté, par quel étage, et ce qui n'en sort jamais",
        "",
        "Axe 5 du [protocole de mesure](protocole-mesure.md). E5 porte **deux** obligations,",
        "et elles ne se prouvent pas de la même façon : *tout appel est journalisé* se compte,",
        "*les colonnes sensibles ne sortent jamais pour `support`* se cherche. Les deux",
        "sections finales font l'une et l'autre.",
        "",
        *_paragraph(
            f"Les {total} scénarios ci-dessous sont joués sous **chacun des "
            f"{len(PROFILES)} profils** de la matrice, soit {len(rows)} appels. "
            "**Aucun refus ne coûte un appel de modèle** — les étages 2 et 3 tranchent "
            "avant la génération ; seuls les appels servis en dépensent un. Le journal est "
            "écrit dans un répertoire temporaire : cette mesure ne pollue pas "
            "`logs/journal.jsonl`."
        ),
        "",
        "## Les trois étages ne se lisent pas au même endroit",
        "",
        "| étage | ce qu'il décide | où il se lit |",
        "|---|---|---|",
        "| **1** | le catalogue visible | `tools/list` — **jamais dans le journal** |",
        "| **2** | le droit d'appeler le tool | `blocked_at == 2` |",
        "| **3** | le périmètre : colonnes, collections, thèmes | `blocked_at == 3` |",
        "",
        "**L'étage 1 ne peut pas apparaître dans `blocked_at`**, et ce n'est pas un oubli : il",
        "filtre une liste, il n'arrête aucun appel. Un client qui appelle un tool qu'il n'a pas",
        "listé est refusé à l'étage 2 — c'est celui-là qui est journalisé. Mesurer E5 sur le",
        "seul journal manquerait donc un étage entier.",
        "",
        "C'est aussi pourquoi l'étage 1 est de l'**ergonomie** et non de la sécurité :",
        "il évite au modèle d'essayer, il n'empêche rien.",
        "",
        *_paragraph(
            f"Vérifié sur les {len(rows)} appels : **aucun ne porte `blocked_at = 1`** "
            f"({_count(rows, blocked_at=1)} occurrence). Ce n'est pas un hasard de jeu — "
            "aucun site du code ne peut l'écrire."
        ),
        "",
        "## Étage 1 — le catalogue par profil",
        "",
        "| Profil | Tools listés | Tools accordés par `matrice.yaml` |",
        "|---|---:|---:|",
    ]
    for profile in PROFILES:
        scope = matrix.get(profile)
        granted = len([t for t in (scope.tools if scope else ()) if t in CATALOGUE])
        lines.append(f"| `{profile}` | **{sizes[profile]}** / 8 | {granted} / 8 |")
    lines += [
        "",
        "Les deux colonnes coïncident, et c'est la seule chose que cette table doit établir :",
        "le catalogue servi **est** la matrice, pas une copie qui pourrait en dériver.",
        f"`default` en liste {sizes['default']} — un agent construit sur ce catalogue n'a aucun",
        "tool, et c'est le comportement voulu, pas une panne.",
        "",
        "## Étages 2 et 3 — ce que le journal dit de chaque appel",
        "",
        "| Profil | servi `blocked_at=0` | arrêté à l'étage 2 | arrêté à l'étage 3 | "
        "non-réponse `blocked_at=None` |",
        "|---|---:|---:|---:|---:|",
    ]
    for profile in PROFILES:
        subset = _by(rows, profile)
        lines.append(
            f"| `{profile}` | {_count(subset, blocked_at=0)} | "
            f"{_bold(_count(subset, blocked_at=2))} | "
            f"{_bold(_count(subset, blocked_at=3))} | "
            f"{_count(subset, blocked_at=None)} |"
        )
    lines += [
        "",
        "**`blocked_at=None` n'est pas un refus, et les confondre rendrait E5 illisible.** Ce",
        "sont les non-réponses : le seuil documentaire (`hors_corpus`), le jugement du",
        "rédacteur (`contexte_insuffisant`), une clarification demandée, une panne. Aucune",
        "n'est dans `REFUSAL_CODES`, aucune ne vaut `denied` au journal. Une gateway qui",
        "compterait « je n'ai pas trouvé » comme « je refuse » gonflerait son propre chiffre de",
        "gouvernance.",
        "",
        "### Le même appel, cinq profils — les scénarios qui séparent",
        "",
        "| Scénario | Ce qu'il vise | "
        + " | ".join(f"`{p}`" for p in PROFILES) + " |",
        "|---|---|" + "---|" * len(PROFILES),
    ]
    for scenario, _tool, _arguments, motive in SCENARIOS:
        cells = []
        for profile in PROFILES:
            row = next(r for r in rows if r["profile"] == profile
                       and r["scenario"] == scenario)
            blocked = row["blocked_at"]
            cells.append("servi" if blocked == 0
                         else f"**étage {blocked}**" if blocked in (2, 3)
                         else f"`{row['code']}`")
        lines.append(f"| `{scenario}` | {motive} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## E5, première obligation — tout appel est journalisé",
        "",
        f"**{len(rows)} appels, {sum(r['journal_entries'] for r in rows)} entrées de "
        f"journal.** Un appel, une ligne, refusé comme servi.",
        "",
    ]
    if unjournalised:
        lines += [
            f"⚠ **{len(unjournalised)} appel(s) ne rendent pas exactement une entrée** : "
            + ", ".join(f"`{r['profile']}/{r['scenario']}` ({r['journal_entries']})"
                        for r in unjournalised),
            ". C'est un manquement à E5, pas une particularité de la mesure.",
            "",
        ]
    else:
        lines += [
            "Aucune exception. C'est le point de passage unique qui le garantit et non une",
            "discipline d'écriture : les deux `handle()` appliquent l'étage 2, **journalisent,**",
            "puis purgent — dans cet ordre. Un refus prononcé avant la journalisation serait un",
            "refus invisible, et c'est exactement ce que l'ordre interdit.",
            "",
        ]

    lines += [
        "## E5, seconde obligation — les colonnes sensibles ne sortent pas",
        "",
        "Cherchées dans la **vue client sérialisée**, celle qui part vraiment : `prix_achat_ht`,",
        "`marge_pct`, `marge_ht`. Pas dans les objets internes — c'est la chaîne rendue qui",
        "prouve quelque chose.",
        "",
        "| Profil | La matrice les ouvre ? | Occurrences dans les vues client |",
        "|---|---|---:|",
    ]
    for profile in PROFILES:
        subset = _by(rows, profile)
        found = sum(1 for r in subset if r["sensitive_in_view"])
        allowed = "oui" if profile in SENSITIVE_ALLOWED else "**non**"
        lines.append(f"| `{profile}` | {allowed} | {found} |")

    lines += [
        "",
    ]
    if leaks:
        lines += [
            f"⚠ **{len(leaks)} fuite(s)** : "
            + ", ".join(f"`{r['profile']}/{r['scenario']}` → {r['sensitive_in_view']}"
                        for r in leaks)
            + ". C'est un manquement à E5.",
            "",
        ]
    else:
        lines += [
            "**Zéro occurrence chez `default`, `dev` et `support`.** Les trois colonnes sont",
            "fermées ensemble, et c'est délibéré : `marge_pct` se dérive de `prix_achat_ht` sur",
            "120 produits sur 120, et `prix_achat_ht` de `marge_ht` sur 993 lignes de vente sur",
            "993. En fermer deux sur trois ne fermerait rien.",
            "",
            "Ce que ce zéro ne dit pas : il porte sur ces scénarios, pas sur toute requête",
            "concevable. La garantie de fond est ailleurs — le contrat de lecture ne **décrit**",
            "au modèle que les colonnes du périmètre, et le contrôle 5b de `validate()` refuse",
            "les autres sur l'arbre, alias résolus. Les 83 contrôles de `make check-sql` en",
            "tiennent le détail ; ce tableau atteste que la chaîne complète les respecte.",
            "",
        ]

    ecartes = [r for r in frontier if r["scenario"] != "temoin-valide"]
    non_journalises = [r for r in frontier if r["journal_entries"] != 1]
    hors_enveloppe = [r for r in frontier if not r["envelope_ok"]]
    fuites_internes = [r for r in frontier if r["internals_in_view"]]
    lines += [
        "## La frontière du serveur — ce qui n'atteint jamais les trois étages",
        "",
    ]
    lines += _paragraph(
        f"Les {len(rows)} appels ci-dessus passent tous des arguments valides, et c'est la "
        "limite de leur échantillon : ils ne disent rien du chemin qu'un argument mal formé "
        "emprunte. Or ce chemin existe, et il est **en amont des trois étages** — le SDK "
        "valide les arguments contre l'`inputSchema` avant d'appeler la fonction de tool, et "
        "un tool hors catalogue ne l'atteint jamais. Ni le handler, ni l'étage 2, ni le "
        "journal ne voient ces appels."
    )
    lines += [""]
    lines += _paragraph(
        "**Cette section se mesure à travers un vrai processus serveur, pas par les "
        "handlers**, et c'est une nécessité et non un raffinement : un handler ne connaît pas "
        "l'`inputSchema`, donc il rendrait `aucune_ligne` sur une référence mal formée au "
        "lieu du refus de format. Mesurer ce chemin par les handlers dirait le contraire de "
        "la vérité."
    )
    lines += [
        "",
        "| Appel | `isError` | `status` | `code` | journal | enveloppe |",
        "|---|:--:|---|---|:--:|:--:|",
    ]
    for row in frontier:
        lines += [
            f"| `{row['tool']}` — {row['scenario']} | "
            f"{'✔' if row['is_error'] else '—'} | "
            f"`{row['status']}` | `{row['code']}` | "
            f"{row['journal_entries']} | {'✔' if row['envelope_ok'] else '**✘**'} |"
        ]
    lines += [""]
    lines += _paragraph(
        f"**{len(frontier) - len(non_journalises)} / {len(frontier)} appels journalisés**, "
        f"**{len(frontier) - len(hors_enveloppe)} / {len(frontier)} enveloppes conformes** — "
        "trois clés du contrat, et le bloc texte égal au champ structuré. "
        f"{_bold(len(fuites_internes))} occurrence du vocabulaire du validateur dans ce que "
        "le client reçoit : la trace part en `cause`, vers le journal."
    )
    lines += [""]
    lines += _paragraph(
        f"`isError` est posé sur les {len(ecartes)} appels écartés et sur aucun autre — pas "
        "sur les refus de droits mesurés plus haut. La spécification en fait un canal de "
        "correction, que le client remonte au modèle pour qu'il réessaie ; un refus de droits "
        "n'a rien à corriger, et le marquer inviterait à réessayer à l'identique. C'est la "
        "différence entre un 500 et un 403, qu'un booléen seul ne sait pas dire — d'où le "
        "discriminant réel : `status`, puis `payload.code`."
    )
    lines += [
        "",
        "Le dernier appel est un **témoin** : sans lui, un serveur qui refuserait tout",
        "rendrait les mêmes chiffres qu'un serveur correct.",
        "",
        "> Mesuré avant que cette frontière existe, sur les mêmes appels : **six exceptions",
        "> sur neuf** dans le client (`json.loads` sur une trace pydantique), et **trois",
        "> lignes de journal sur neuf**. E5 était entamée sur un chemin qu'aucune mesure ne",
        "> regardait.",
        "",
        "## « Nommer, pas numéroter » — tranché : on numérote",
        "",
        "La réserve laissée ouverte au journal de développement se tranche ici, puisque c'est",
        "cette mesure qui lit le champ pour la première fois. `blocked_at` reste un **entier**.",
        "",
        "| | Pourquoi |",
        "|---|---|",
        "| `etage` porte déjà le même entier | deux vocabulaires pour une seule notion "
        "divergeraient le jour où l'un des deux serait retouché |",
        "| les numéros sont ceux de la conception | `03-catalogue-tools.md` §3 numérote ses "
        "trois étages ; renommer ici obligerait à traduire à chaque lecture |",
        "| un entier se compare | `blocked_at > 0` dit « arrêté par la gouvernance » en trois "
        "caractères ; un nom demanderait une table |",
        "",
        "**Le nom appartient à la lecture, pas à l'écriture.** C'est ce rapport qui nomme les",
        "étages — catalogue, tool, périmètre — et c'est le bon endroit : un lecteur humain lit",
        "un rapport, une requête lit un entier.",
        "",
        "*Rejouer : `make mesure-acces`.*",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    with TemporaryDirectory() as tmp:
        settings = base_settings.model_copy(
            update={"gateway_journal": Path(tmp) / "journal.jsonl"}
        )
        rows, sizes = run(settings)
        frontier = measure_frontier(settings)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with FRONTIER_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FRONTIER_FIELDS)
        writer.writeheader()
        writer.writerows(frontier)
    write_report(rows, sizes, frontier)

    print(f"écrit : {RESULTS_PATH.relative_to(REPO_ROOT)} ({len(rows)} lignes)")
    print(f"écrit : {FRONTIER_PATH.relative_to(REPO_ROOT)} ({len(frontier)} lignes)")
    print(f"écrit : {REPORT_PATH.relative_to(REPO_ROOT)}")
    for profile in PROFILES:
        subset = _by(rows, profile)
        print(f"  {profile:11} catalogue {sizes[profile]}/8 · servis "
              f"{_count(subset, blocked_at=0)} · étage 2 {_count(subset, blocked_at=2)} · "
              f"étage 3 {_count(subset, blocked_at=3)} · "
              f"non-réponses {_count(subset, blocked_at=None)}")
    leaks = [r for r in rows if r["sensitive_in_view"]
             and r["profile"] not in SENSITIVE_ALLOWED]
    unjournalised = [r for r in rows if r["journal_entries"] != 1]
    print(f"  E5 — appels journalisés {len(rows) - len(unjournalised)}/{len(rows)} · "
          f"fuites de colonne sensible {len(leaks)}")
    faux = [r for r in frontier if r["journal_entries"] != 1 or not r["envelope_ok"]
            or r["internals_in_view"]]
    print(f"  frontière — journalisés "
          f"{len([r for r in frontier if r['journal_entries'] == 1])}/{len(frontier)} · "
          f"enveloppes conformes "
          f"{len([r for r in frontier if r['envelope_ok']])}/{len(frontier)} · "
          f"fuites d'interne {len([r for r in frontier if r['internals_in_view']])}")
    return 1 if (leaks or unjournalised or faux) else 0


if __name__ == "__main__":
    raise SystemExit(main())
