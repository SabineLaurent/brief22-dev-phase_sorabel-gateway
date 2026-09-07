"""Client MCP de test de la gateway.

Lance le serveur en sous-processus (stdio) sous un profil donné, liste le
catalogue de tools, puis appelle un tool si demandé.

Exemples :
    uv run python scripts/mcp_client.py --profile support
    uv run python scripts/mcp_client.py --profile commercial \
        --tool ask_database --args '{"question": "combien de commandes en avril ?"}'
    uv run python scripts/mcp_client.py --profile support \
        --tool search_docs --args '{"query": "REF-8842"}'
    uv run python scripts/mcp_client.py --profile dev        # 5 tools sur 8
    uv run python scripts/mcp_client.py --profile default    # aucun tool

Les profils acceptés sont **ceux de la matrice**, lus dans ``matrice.yaml`` et non écrits
ici : le brief ne demande de démontrer que ``support`` et ``commercial``, mais une liste en
dur diverge de la matrice le jour où un profil y est ajouté — et c'est précisément ce que ce
client sert à montrer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import settings
from packages.access import load_matrix


async def run(profile: str, tool: str | None, args: dict) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env={**os.environ, "SORABEL_PROFILE": profile},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            print(f"— Catalogue ({profile}) —")
            for t in listed.tools:
                print(f"  {t.name}: {(t.description or '').strip().splitlines()[0]}")

            if tool:
                print(f"\n— Appel {tool} {json.dumps(args, ensure_ascii=False)} —")
                result = await session.call_tool(tool, args)
                for block in result.content:
                    text = getattr(block, "text", None)
                    if text:
                        try:
                            print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
                        except json.JSONDecodeError:
                            print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Client de test de la Sorabel Data Gateway")
    parser.add_argument("--profile", default="support", choices=sorted(load_matrix(settings)))
    parser.add_argument("--tool", default=None, help="Nom du tool à appeler")
    parser.add_argument("--args", default="{}", help="Arguments du tool (JSON)")
    ns = parser.parse_args()
    asyncio.run(run(ns.profile, ns.tool, json.loads(ns.args)))


if __name__ == "__main__":
    main()
