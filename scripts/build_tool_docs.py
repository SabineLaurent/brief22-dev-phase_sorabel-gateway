"""La page du catalogue des tools, **générée depuis le serveur lui-même**.

L'équivalent de Swagger UI pour cette gateway. La différence avec une documentation
rédigée tient en une phrase : cette page ne peut pas mentir, parce qu'elle n'est pas
écrite — elle est le rendu de ce que ``tools/list`` répond vraiment, profil par profil.
Un argument renommé, un tool retiré à un profil, un renvoi qui change : la page suit au
prochain ``make doc-tools``, sans qu'on ait à y penser.

Ce qu'un Swagger ne saurait pas rendre, et qui est l'intérêt principal ici : **le catalogue
dépend du profil**. Cinq profils, cinq catalogues, et les descriptions elles-mêmes
diffèrent — ``get_schema`` ne recommande pas ``ask_database`` à un profil qui ne l'a pas.
La page montre les cinq côte à côte, ce qui en fait une démonstration de la matrice autant
qu'une documentation d'API.

**Aucun appel de modèle**, donc aucun coût : la page se construit sur ``initialize`` et
``tools/list``, plus **deux** appels de tools choisis pour ne toucher que SQLite — un
résultat et un refus, dont la page montre les enveloppes réelles.

**Elle est autosuffisante.** Un intégrateur doit pouvoir se brancher avec ce seul fichier,
sans dépendre d'un guide à côté qui peut changer de forme : d'où la section « se brancher »,
seule partie rédigée, et les deux chiffres qu'elle cite lus dans ``pyproject.toml`` et dans
``Settings`` plutôt qu'écrits.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tomllib
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import Settings, settings
from packages.access import load_matrix
from packages.rag_machines.structured_answer import RAG_STATUS_BY_CODE
from packages.rag_machines.structured_answer import REFUSAL_CODES as RAG_REFUSALS
from packages.text_to_sql_factory.structured_answer import DB_STATUS_BY_CODE
from packages.text_to_sql_factory.structured_answer import REFUSAL_CODES as DB_REFUSALS

#: La page est écrite à côté du serveur qu'elle décrit : elle se régénère depuis lui, et un
#: lecteur qui ouvre `mcp_server/` doit tomber dessus.
PAGE_PATH = Path("mcp_server/SMG-guide-d-acces.html")

#: Les cinq rubriques d'une description servie (``mcp_server/server.py``). Les renvois
#: conditionnels sont collés à la dernière : c'est là que la différence entre profils se voit.
SECTIONS = ("Objet :", "Entrée :", "Sortie :", "Utiliser quand :", "Ne pas utiliser quand :")


async def _catalogue(profile: str) -> list[Any]:
    """Ce que ``tools/list`` rend à ce profil — un sous-processus serveur par profil.

    Le profil se pose dans l'environnement, comme en production : il n'est pas un argument
    du protocole, et cette page ne peut donc pas le demander autrement que le ferait un
    vrai client.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env={**os.environ, "SORABEL_PROFILE": profile},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return list((await session.list_tools()).tools)


async def collect(profiles: list[str]) -> dict[str, list[Any]]:
    """Les catalogues des cinq profils. Séquentiel : cinq poignées de main, pas une charge."""
    catalogues = {}
    for profile in profiles:
        catalogues[profile] = await _catalogue(profile)
        print(f"  {profile:11} {len(catalogues[profile])} tools")
    return catalogues


#: Les deux appels dont la page montre la réponse, **choisis pour être reproductibles** :
#: aucun des deux n'appelle de modèle ni n'ouvre l'index vectoriel. Le premier sert un
#: résultat, le second un refus — c'est le couple qui montre l'asymétrie du payload.
EXAMPLES: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    ("support", "check_stock", {"reference": "REF-8842"},
     "Un résultat — la charge utile est là, <code>message</code> est vide."),
    ("support", "get_schema", {},
     "Un refus — <code>support</code> n'a pas ce tool. <b>La clé de charge utile n'est pas "
     "vide : elle est absente.</b> Il n'y a rien à afficher, et c'est ce qui empêche un "
     "client de rendre un refus comme une réponse."),
)


async def samples() -> list[tuple[str, str, dict[str, Any], str, str]]:
    """Appelle réellement les deux tools d'exemple et rend leurs enveloppes.

    Un exemple recopié à la main vieillit ; celui-ci est rejoué à chaque génération, donc il
    ne peut pas décrire une forme de réponse que le serveur ne sert plus.
    """
    collected = []
    for profile, tool, arguments, comment in EXAMPLES:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            env={**os.environ, "SORABEL_PROFILE": profile},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
        # Le contenu d'un résultat MCP est une union de types de blocs ; seul le bloc texte
        # porte l'enveloppe sérialisée. `getattr` plutôt qu'un accès direct : les autres
        # types n'ont pas d'attribut `text`.
        blocks = [getattr(block, "text", None) for block in result.content]
        raw = next((text for text in blocks if text), "{}")
        pretty = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        collected.append((profile, tool, arguments, comment, pretty))
        print(f"  exemple {tool} ({profile}) : {json.loads(raw).get('status')}")
    return collected


# --- Lecture des schémas ---------------------------------------------------------------


def _type_of(schema: dict[str, Any]) -> str:
    """Le type d'un argument, y compris sous la forme ``anyOf`` d'un optionnel."""
    if "type" in schema:
        return str(schema["type"])
    options = [str(item.get("type", "?")) for item in schema.get("anyOf", [])
               if item.get("type") != "null"]
    return " | ".join(options) or "?"


def _constraint(schema: dict[str, Any]) -> str:
    """La contrainte de format, quand l'``inputSchema`` en porte une.

    C'est elle qui fait le vrai travail de tri : ``^REF-\\d{4}$`` écarte un libellé plus
    sûrement qu'une phrase de description, et beaucoup de clients valident avant l'envoi.
    """
    for source in (schema, *schema.get("anyOf", [])):
        if "pattern" in source:
            return f"<code>{escape(str(source['pattern']))}</code>"
        if "items" in source:
            return "tableau de " + _type_of(source["items"])
    return "—"


def _arguments(tool: Any) -> str:
    schema = tool.inputSchema or {}
    properties = schema.get("properties") or {}
    if not properties:
        return "<p class='none'>Aucun argument.</p>"
    required = set(schema.get("required") or [])
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(name)}</code></td>"
        f"<td>{escape(_type_of(body))}</td>"
        f"<td>{'requis' if name in required else 'optionnel'}</td>"
        f"<td>{_constraint(body)}</td>"
        "</tr>"
        for name, body in properties.items()
    )
    return ("<table><thead><tr><th>Argument</th><th>Type</th><th>Présence</th>"
            f"<th>Contrainte</th></tr></thead><tbody>{rows}</tbody></table>")


def _response(tool: Any) -> str:
    """Les statuts et les clés de charge utile que l'``outputSchema`` déclare."""
    schema = tool.outputSchema or {}
    properties = schema.get("properties") or {}
    statuses = (properties.get("status") or {}).get("enum") or []
    payload = ((properties.get("payload") or {}).get("properties") or {})
    keys = [key for key in payload if key != "code"]
    return (
        "<dl class='resp'>"
        f"<dt>Statuts possibles</dt><dd>{' · '.join(f'<code>{escape(s)}</code>' for s in statuses)}</dd>"
        f"<dt>Clés de charge utile</dt><dd>{' · '.join(f'<code>{escape(k)}</code>' for k in keys) or '—'}"
        " <span class='note'>absentes sur un refus ou une non-réponse</span></dd>"
        "</dl>"
    )


def _sections(description: str) -> list[tuple[str, str]]:
    """La description servie, découpée sur ses cinq rubriques."""
    parts: list[tuple[str, str]] = []
    for index, marker in enumerate(SECTIONS):
        start = description.find(marker)
        if start < 0:
            continue
        end = len(description)
        for later in SECTIONS[index + 1:]:
            found = description.find(later, start)
            if found >= 0:
                end = min(end, found)
        parts.append((marker.rstrip(" :"), description[start + len(marker):end].strip()))
    return parts or [("Description", description)]


def _definitions(parts: list[tuple[str, str]]) -> str:
    return "<dl class='desc'>" + "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(body)}</dd>" for label, body in parts
    ) + "</dl>"


# --- Rendu -----------------------------------------------------------------------------


def _matrix_table(profiles: list[str], catalogues: dict[str, list[Any]],
                  names: list[str], off_protocol: list[str],
                  granted: dict[str, set[str]]) -> str:
    """Le tableau profil × tools, **plus les droits de la matrice qui ne sont pas des tools**.

    Sans la seconde moitié, ``admin`` et ``commercial`` s'affichent identiques — huit tools
    chacun — alors que la matrice accorde au premier un droit de plus. Le lecteur en
    conclurait que le profil ``admin`` ne sert à rien. Ces lignes sont **calculées**, par
    différence entre ce que la matrice déclare et ce que ``tools/list`` rend : un tool
    ajouté à la matrice et oublié au serveur apparaîtrait ici tout seul.
    """
    head = "".join(f"<th>{escape(p)}</th>" for p in profiles)
    visible = {p: {tool.name for tool in tools} for p, tools in catalogues.items()}

    def cells(name: str, holders: dict[str, set[str]], mark: str) -> str:
        return "".join(
            f"<td class='{'yes' if name in holders[p] else 'no'}'>"
            f"{mark if name in holders[p] else '·'}</td>"
            for p in profiles
        )

    rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td>{cells(name, visible, '✔')}</tr>"
        for name in names
    )
    totals = "".join(f"<td class='total'>{len(visible[p])}</td>" for p in profiles)
    rows += (f"<tr class='sum'><td><b>total du catalogue</b></td>{totals}</tr>")
    for name in off_protocol:
        rows += (f"<tr class='offband'><td><code>{escape(name)}</code>"
                 " <span class='note'>hors protocole</span></td>"
                 f"{cells(name, granted, '✔')}</tr>")
    return (f"<table class='matrix'><thead><tr><th>Tool</th>{head}</tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _envelope_section(tool: Any) -> str:
    """L'enveloppe, **lue dans l'``outputSchema`` publié** plutôt que redite ici.

    Les phrases rendues sont celles que le serveur envoie déjà à tout client dans
    ``tools/list`` : les recopier dans cette page les ferait diverger du jour où l'une des
    deux serait retouchée. C'est la même règle que pour les descriptions de tools.
    """
    schema = tool.outputSchema or {}
    properties = schema.get("properties") or {}
    required = ", ".join(f"<code>{escape(key)}</code>" for key in schema.get("required", []))
    def described(key: str) -> str:
        """Ce que le schéma dit de cette clé — ou, à défaut, ce que sa forme impose.

        ``payload`` est la seule des trois à ne porter aucune ``description`` : elle est
        décrite par sa structure, pas par une phrase. On rend donc sa structure, toujours
        lue dans le schéma.
        """
        body = properties.get(key) or {}
        text = str(body.get("description", "")).strip()
        if text:
            return escape(text)
        always = ", ".join(f"<code>{escape(k)}</code>" for k in body.get("required", []))
        return (f"Objet. Toujours présent : {always}. Les autres clés dépendent du tool "
                "— voir sa fiche — et sont <b>absentes</b>, jamais vides, quand il n'y a "
                "rien à mettre dedans.")

    rows = "".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{described(key)}</td></tr>"
        for key in schema.get("required", [])
    )
    return (
        f"<p>{escape(str(schema.get('description', '')))}</p>"
        f"<p class='lede'>Les trois clés sont <b>toujours</b> présentes : {required}.</p>"
        "<table><thead><tr><th>Clé</th><th>Ce que le serveur en dit</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _codes_table() -> str:
    """Les douze codes, par différence entre les tables de statuts des deux domaines.

    Le tableau n'est pas écrit : il est la réunion de ``DB_STATUS_BY_CODE`` et de
    ``RAG_STATUS_BY_CODE``, les mêmes tables dont ``output_schemas.py`` calcule les
    énumérations publiées. Un code ajouté à un domaine apparaît ici sans qu'on y touche.
    """
    refusals = RAG_REFUSALS | DB_REFUSALS
    rows = ""
    for code in sorted(set(DB_STATUS_BY_CODE) | set(RAG_STATUS_BY_CODE)):
        domains = [label for label, table in (("base", DB_STATUS_BY_CODE),
                                              ("documentaire", RAG_STATUS_BY_CODE))
                   if code in table]
        statuses = sorted({table[code] for table in (DB_STATUS_BY_CODE, RAG_STATUS_BY_CODE)
                           if code in table})
        refused = code in refusals
        rows += (
            f"<tr class='{'refus' if refused else ''}'>"
            f"<td><code>{escape(code)}</code></td>"
            f"<td>{' · '.join(f'<code>{escape(s)}</code>' for s in statuses)}</td>"
            f"<td>{' et '.join(domains)}</td>"
            f"<td>{'<b>oui</b>' if refused else 'non'}</td>"
            "</tr>"
        )
    return ("<table><thead><tr><th>Code</th><th>Statut</th><th>Domaine</th>"
            f"<th>Refus ?</th></tr></thead><tbody>{rows}</tbody></table>")


def _samples_section(collected: list[tuple[str, str, dict[str, Any], str, str]]) -> str:
    blocks = ""
    for profile, tool, arguments, comment, pretty in collected:
        call = f"{tool} {json.dumps(arguments, ensure_ascii=False)}"
        blocks += (
            f"<h4><code>{escape(call)}</code> — profil <code>{escape(profile)}</code></h4>"
            f"<p class='lede'>{comment}</p>"
            f"<pre><code>{escape(pretty)}</code></pre>"
        )
    return blocks


def _tool_card(name: str, profiles: list[str], catalogues: dict[str, list[Any]]) -> str:
    """La fiche d'un tool, et **les variantes de sa description selon le profil**.

    Les descriptions identiques sont regroupées : afficher cinq fois la même noierait la
    seule chose qu'on veut voir, c'est-à-dire les endroits où elles diffèrent.
    """
    served = {p: tool for p in profiles for tool in catalogues[p] if tool.name == name}
    reference = served[next(iter(served))]
    holders = " ".join(f"<span class='chip'>{escape(p)}</span>" for p in served)

    variants: dict[str, list[str]] = {}
    for profile, tool in served.items():
        variants.setdefault(tool.description or "", []).append(profile)

    # La première variante en entier ; les suivantes **réduites aux rubriques qui
    # changent**. Répéter cinq rubriques identiques noierait la seule chose à voir — et
    # cette seule chose, c'est le renvoi qu'un profil reçoit et qu'un autre non.
    blocks, first = "", None
    for description, owners in variants.items():
        parts = _sections(description)
        if first is None:
            first = dict(parts)
            blocks += ("" if len(variants) == 1
                       else f"<p class='variant'>Servie à : {', '.join(owners)}</p>")
            blocks += _definitions(parts)
            continue
        changed = [(label, body) for label, body in parts if first.get(label) != body]
        blocks += (f"<p class='variant'>Servie à : {', '.join(owners)}"
                   " <span class='note'>— seules les rubriques ci-dessous changent</span>"
                   "</p>")
        blocks += _definitions(changed)

    annotations = reference.annotations
    hints = " · ".join(
        f"<code>{key}</code>" for key, value in
        (("readOnlyHint", getattr(annotations, "readOnlyHint", None)),
         ("idempotentHint", getattr(annotations, "idempotentHint", None)))
        if value
    ) or "—"

    return f"""
<section class="tool" id="{escape(name)}">
  <h3><code>{escape(name)}</code></h3>
  <p class="title">{escape(reference.title or '')}</p>
  <p class="holders">Visible par : {holders}</p>
  <h4>Arguments</h4>
  {_arguments(reference)}
  <h4>Réponse</h4>
  {_response(reference)}
  <h4>Description servie{'' if len(variants) == 1 else ' — elle diffère selon le profil'}</h4>
  {blocks}
  <p class="hints">Annotations : {hints}</p>
</section>"""


#: Les variables sans lesquelles les deux tools génératifs ne peuvent pas répondre. Les six
#: autres tournent sans : la recherche et le reclassement sont locaux par défaut, et les
#: trois tools SQL non génératifs ne lisent que SQLite.
MODEL_SETTINGS = ("AZURE_AI_ENDPOINT", "AZURE_AI_API_KEY", "LLM_CHAT_MODEL")


def _connect() -> str:
    """La section « se brancher » — **la seule rédigée**, parce qu'aucun schéma ne la porte.

    Elle est volontairement autosuffisante : un intégrateur doit pouvoir démarrer avec ce
    seul fichier, sans dépendre d'un guide à côté. Les deux seuls chiffres qu'elle cite —
    la version de Python et le nombre de réglages — sont **lus** plutôt qu'écrits, parce
    que ce sont exactement ceux qui vieillissent (le guide en prose annonçait vingt
    réglages ; il y en a davantage depuis).
    """
    with Path("pyproject.toml").open("rb") as handle:
        python = tomllib.load(handle)["project"]["requires-python"]
    fields = Settings.model_fields
    required = [name for name, field in fields.items() if field.is_required()]
    defaults = ("ont <b>tous</b> un défaut" if not required else
                f"ont un défaut, sauf {', '.join(f'<code>{n}</code>' for n in required)}")
    model_vars = ", ".join(f"<code>{name}</code>" for name in MODEL_SETTINGS)

    return f"""
<p>Le serveur parle <b>stdio</b> : ni port, ni URL, ni jeton. Un processus par profil, et le
   profil est posé par <b>qui lance le processus</b> — jamais par le client, jamais par le
   modèle.</p>

<h3>Prérequis</h3>
<p>Python <code>{escape(python)}</code>, <a href="https://docs.astral.sh/uv/">uv</a>, et
   Docker — ce dernier pour la seule base vectorielle.</p>
<pre><code>uv sync --extra vector        # l'extra est nécessaire : sans lui l'embedder local casse
cp .env.example .env          # aucune valeur du modèle n'est un secret
make up                       # Chroma, via docker compose, port 8002
make seed                     # génère data/sorabel.db
make ingest                   # indexe le corpus (~400 éditions)</code></pre>
<p><code>.env</code> n'est pas obligatoire : les <b>{len(fields)} réglages</b> {defaults}.
   Il le devient pour les appels de modèle —
   {model_vars} — dont dépendent <code>answer_question</code> (la rédaction) et
   <code>ask_database</code> (la génération SQL). <b>Les six autres tools fonctionnent
   sans</b> : la recherche et le reclassement tournent en local par défaut.</p>

<h3>Le bloc de configuration</h3>
<p>À coller dans la configuration de votre client MCP :</p>
<pre><code>{{
  "mcpServers": {{
    "sorabel": {{
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_server.server"],
      "cwd": "/chemin/absolu/vers/brief22-dev-phase_sorabel-gateway",
      "env": {{
        "SORABEL_PROFILE": "commercial",
        "TOKENIZERS_PARALLELISM": "false"
      }}
    }}
  }}
}}</code></pre>
<p><code>cwd</code> est <b>obligatoire</b> : le corpus, la base et la matrice sont résolus
   relativement à la racine du dépôt. <code>TOKENIZERS_PARALLELISM</code> n'est pas
   fonctionnel — il fait taire un avertissement de la bibliothèque d'embeddings qui, sinon,
   encombre la console du client. <code>SORABEL_PROFILE</code> vaut <code>support</code> par
   défaut ; un nom inconnu retombe sur <code>default</code>, qui n'a aucun tool — un
   catalogue vide est donc le symptôme d'un profil mal orthographié, pas d'une panne.</p>
<p><b>Préférez ce bloc à une commande en ligne de commande.</b> Certains clients —
   l'Inspector officiel en fait partie — analysent les arguments et <b>avalent le
   <code>-m</code></b>, ce qui lance <code>python</code> sans module : le processus lit alors
   le JSON-RPC sur son entrée standard et le prend pour du code. Le symptôme est un
   <code>NameError: name 'true' is not defined</code> suivi d'un délai d'attente dépassé.</p>

<h3>Vérifier que ça répond</h3>
<pre><code>make serve                    # le serveur, en stdio, profil dans SORABEL_PROFILE
make client                   # un client de test : le catalogue du profil
PROFILE=commercial make client

# avec l'Inspector officiel, le bloc ci-dessus enregistré dans mon-serveur.json :
npx @modelcontextprotocol/inspector --cli \\
  --config mon-serveur.json --server sorabel --method tools/list --format json</code></pre>
"""

STYLE = """
:root { --ink:#1b1b1b; --soft:#666; --line:#d8d8d8; --bg:#fbfbfa; --accent:#7a5195; }
* { box-sizing: border-box; }
body { margin:0; padding:0 20px 60px; background:var(--bg); color:var(--ink);
       font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif; }
main { max-width: 980px; margin: 0 auto; }
header { border-bottom:2px solid var(--ink); padding:32px 0 18px; margin-bottom:28px; }
h1 { margin:0 0 6px; font-size:26px; }
h2 { margin:44px 0 14px; font-size:19px; border-bottom:1px solid var(--line);
     padding-bottom:6px; }
h3 { margin:0 0 2px; font-size:17px; }
h4 { margin:20px 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.06em;
     color:var(--soft); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:.92em;
       background:#efeeec; padding:1px 5px; border-radius:3px; }
table { border-collapse:collapse; width:100%; margin:8px 0; font-size:14px; }
th, td { border:1px solid var(--line); padding:6px 9px; text-align:left; }
th { background:#f0efed; font-weight:600; }
.matrix td:not(:first-child), .matrix th:not(:first-child) { text-align:center; }
.matrix .yes { color:#2e7d32; font-weight:700; }
.matrix .no { color:#bbb; }
.matrix .sum td { background:#f0efed; }
.matrix .offband td { background:#faf6ff; border-top:2px solid var(--accent); }
.matrix .total { text-align:center; font-weight:700; }
.tool { border:1px solid var(--line); border-left:4px solid var(--accent);
        background:#fff; padding:18px 20px; margin:18px 0; }
.title { margin:0 0 10px; color:var(--soft); font-style:italic; }
.chip { display:inline-block; background:#efeeec; border:1px solid var(--line);
        border-radius:10px; padding:1px 9px; font-size:12.5px; }
.holders { margin:0; }
dl.desc, dl.resp { margin:6px 0; display:grid; grid-template-columns:170px 1fr; gap:4px 14px; }
dl.desc dt, dl.resp dt { color:var(--soft); font-size:13px; text-transform:uppercase;
                         letter-spacing:.04em; }
dl.desc dd, dl.resp dd { margin:0; }
.variant { margin:14px 0 2px; font-weight:600; font-size:13.5px; color:var(--accent); }
pre { background:#f4f3f1; border:1px solid var(--line); border-radius:4px; padding:12px 14px;
      overflow-x:auto; font-size:13px; line-height:1.45; }
pre code { background:none; padding:0; }
.refus td:first-child code { background:#fde8e4; }
.note, .hints { color:var(--soft); font-size:13px; }
.hints { margin:16px 0 0; }
.none { color:var(--soft); font-style:italic; }
.lede { color:var(--soft); margin:4px 0; }
footer { margin-top:44px; padding-top:14px; border-top:1px solid var(--line);
         color:var(--soft); font-size:13.5px; }
@media (max-width:640px) {
  dl.desc, dl.resp { grid-template-columns:1fr; }
  dl.desc dt, dl.resp dt { margin-top:8px; }
}
"""


def render(profiles: list[str], catalogues: dict[str, list[Any]],
           collected: list[tuple[str, str, dict[str, Any], str, str]]) -> str:
    richest = max(profiles, key=lambda p: len(catalogues[p]))
    names = [tool.name for tool in catalogues[richest]]
    cards = "".join(_tool_card(name, profiles, catalogues) for name in names)

    #: L'enveloppe est la même partout : n'importe quel tool en porte le schéma.
    reference_tool = catalogues[richest][0]
    codes = set(DB_STATUS_BY_CODE) | set(RAG_STATUS_BY_CODE)

    # Ce que la matrice accorde et que le protocole ne publie pas. Aujourd'hui : la lecture
    # du journal, portée par `admin` seul et servie par une route de l'API du banc d'essai,
    # jamais par `tools/list`.
    matrix = load_matrix(settings)
    granted = {profile: set(matrix[profile].tools) for profile in profiles}
    served = {name for tools in catalogues.values() for name in (t.name for t in tools)}
    off_protocol = sorted({tool for tools in granted.values() for tool in tools} - served)
    aside = ""
    if off_protocol:
        holders = ", ".join(
            f"<code>{escape(name)}</code> ({', '.join(p for p in profiles if name in granted[p])})"
            for name in off_protocol
        )
        aside = (
            "<p class='lede'><b>Deux colonnes identiques ne veulent pas dire deux profils "
            f"identiques.</b> La matrice accorde {holders} — un droit qui n'est "
            "<b>pas</b> un tool MCP : il n'est publié par aucun <code>tools/list</code>, et "
            "s'exerce par l'API du banc d'essai. Deux profils au même catalogue peuvent "
            "donc différer par là.</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sorabel MCP gateway - Guide d'accès</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<header>
  <h1>Sorabel MCP gateway - Guide d'accès</h1>
  <p class="lede">Page <b>générée</b> le {date.today().isoformat()} par
     <code>make doc-tools</code>, depuis ce que <code>tools/list</code> répond réellement,
     profil par profil. Elle n'est pas rédigée : un argument renommé ou un tool retiré à un
     profil s'y voit à la régénération suivante.</p>
  <p class="lede">Cette page se suffit à elle-même : se brancher, lire une réponse, et les
     huit fiches. Ce qu'elle ne porte pas — les garanties détaillées, les limites chiffrées
     et les écarts assumés — vit dans le guide d'intégration du dépôt.</p>
</header>

<h2>1 · Se brancher</h2>
{_connect()}

<h2>2 · Profil × tools — l'étage 1, tel que le serveur l'applique</h2>
<p class="lede">Chaque colonne est un catalogue réellement obtenu, en lançant le serveur
   avec <code>SORABEL_PROFILE</code> à cette valeur. Un profil ne voit pas seulement moins
   de tools : les <b>descriptions</b> qu'il reçoit diffèrent aussi — voir les fiches.</p>
{_matrix_table(profiles, catalogues, names, off_protocol, granted)}
{aside}

<h2>3 · Lire une réponse</h2>
<p class="lede">Les huit tools rendent la <b>même</b> enveloppe, servie comme refusée. Ce
   qui suit est lu dans l'<code>outputSchema</code> que le serveur publie — c'est le texte
   que reçoit déjà votre client, pas une paraphrase.</p>
{_envelope_section(reference_tool)}

<h3>Les {len(codes)} codes</h3>
<p class="lede">Le <code>status</code> dit l'issue, le <code>code</code> dit le cas précis.
   <b>Branchez sur <code>code</code></b> : deux codes très différents partagent parfois un
   statut. Quatre codes seulement sont des refus — les autres sont des constats, et les
   traiter comme des erreurs surestimerait la sévérité du système.</p>
{_codes_table()}

<h3>Deux réponses réelles</h3>
<p class="lede">Obtenues en appelant le serveur pendant la génération de cette page, pas
   recopiées.</p>
{_samples_section(collected)}

<h2>4 · Les {len(names)} tools</h2>
{cards}

<footer>
  Généré par <code>scripts/build_tool_docs.py</code> — <code>initialize</code>,
  <code>tools/list</code>, et les deux appels dont les réponses sont montrées plus haut.
  Aucun appel de modèle.
  Le contrat de réponse est déclaré dans <code>mcp_server/output_schemas.py</code>,
  la matrice dans <code>mcp_server/matrice.yaml</code>.
</footer>
</main>
</body>
</html>
"""


def main() -> None:
    profiles = list(load_matrix(settings))
    print(f"Catalogues relevés sur {len(profiles)} profils :")
    catalogues = asyncio.run(collect(profiles))
    print("Exemples de réponse, appelés pour de vrai :")
    collected = asyncio.run(samples())
    PAGE_PATH.write_text(render(profiles, catalogues, collected), encoding="utf-8")
    print(f"\nÉcrit : {PAGE_PATH}")


if __name__ == "__main__":
    main()
