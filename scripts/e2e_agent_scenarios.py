"""Rejoue les 12 scénarios de tests/acceptance/ via l'agent conversationnel
(packages/agent), en langage naturel, contre l'API locale (POST /chat) — comme le ferait la
GUI. Contrairement à tests/acceptance/, qui appelle un tool nommé avec des arguments fixés,
ici c'est le LLM routeur qui choisit le tool : la comparaison porte sur les champs
structurés que l'API rend (`calls`, `statut` — packages/agent/api.py::ChatResponse), jamais
sur une lecture du texte de la réponse.

Lancé par scripts/test-accept-agent-local.sh, qui démarre l'API au préalable.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RAPPORTS = REPO_ROOT / "docs" / "tests-acceptance-rapports"
BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    dict(id="RAG-1", role="support",
         question="quelle est la procédure de retour d'un produit défectueux sous garantie ?",
         attendu_tool="answer_question", attendu_statut=None, forcable=True,
         source="test_answer_question_cite_ses_sources"),
    dict(id="RAG-2", role="support",
         question="quelle est la politique de télétravail chez Sorabel ?",
         attendu_tool="answer_question", attendu_statut=None, forcable=True,
         source="test_hors_corpus_signale_sans_inventer"),
    dict(id="RAG-3", role="support", question="REF-8842",
         attendu_tool="search_docs", attendu_statut=None, forcable=False,
         source="test_recherche_par_reference_exacte (proxy — non forçable)"),
    dict(id="SQL-1", role="commercial", question="combien de commandes en avril ?",
         attendu_tool="ask_database", attendu_statut="ok", forcable=True,
         source="test_ask_database_repond_et_montre_sa_requete"),
    dict(id="SQL-2", role="commercial", question="supprime les commandes de test",
         attendu_tool="ask_database", attendu_statut="refused", forcable=True,
         source="test_ecriture_refusee_et_journalisee"),
    dict(id="SQL-3", role="support", question="quelle est la marge sur la REF-8842 ?",
         attendu_tool="ask_database", attendu_statut="refused", forcable=True,
         source="test_profil_support_jamais_de_marge"),
    dict(id="SQL-4", role="commercial", question="quelle est la météo à Lille demain ?",
         attendu_tool="ask_database", attendu_statut="refused", forcable=True,
         source="test_hors_schema_refus_propre"),
    dict(id="MCP-1", role="support", question="quelles sont les tables de la base ?",
         attendu_tool="get_schema (hors matrice support — absent du catalogue)",
         attendu_statut=None, forcable=False,
         source="test_refus_message_clair_et_journalise (proxy)"),
    dict(id="MCP-2a", role="support", question="délai d'un échange standard ?",
         attendu_tool="answer_question", attendu_statut=None, forcable=True,
         source="test_journal_exhaustif_autorises_et_refuses (1/3)"),
    dict(id="MCP-2b", role="support", question="quel est le stock de la REF-8842 ?",
         attendu_tool="check_stock", attendu_statut="ok", forcable=True,
         source="test_journal_exhaustif_autorises_et_refuses (2/3)"),
    dict(id="MCP-3", role="commercial",
         question=("cherche les documents qui parlent du retour d'un produit défectueux "
                    "sous garantie, sans rédiger de réponse, donne-moi juste les résultats "
                    "de la recherche"),
         attendu_tool="search_docs puis get_document, jamais answer_question",
         attendu_statut=None, forcable=False,
         source="test_briques_du_rag_utilisables_separement (proxy — non forçable)"),
]


def evalue(sc: dict, data: dict) -> tuple[bool | None, str]:
    """(réussite, motif). `None` = non noté (scénario marqué non forçable : le routeur
    choisit, aucune formulation ne garantit le tool attendu — cf. docs/2026-09-11-
    checklist-e2e-gui.md). Ne juge que sur `calls`/`statut`, jamais sur le texte."""
    if not sc["forcable"]:
        return None, "proxy — non forçable, non noté"
    tools_appeles = [c["tool"] for c in data.get("calls", [])]
    if sc["attendu_tool"] not in tools_appeles:
        return False, f"tool {sc['attendu_tool']} attendu, appelés={tools_appeles}"
    if sc["attendu_statut"] and data.get("statut") != sc["attendu_statut"]:
        return False, f"statut {sc['attendu_statut']} attendu, observé {data.get('statut')}"
    return True, ""


def _matrice_par_profil() -> dict[str, list[str]]:
    """Les tools attendus par profil, lus dans mcp_server/matrice.yaml — jamais recopiés à
    la main : une matrice modifiée reste la source, ce script ne fige rien.

    `read_journal` est retiré : ce n'est pas un tool MCP (mcp_server/server.py n'en sert
    que huit), c'est un droit de matrice contrôlé par la route /journal de l'API,
    directement via `authorize()`. L'inclure ferait un faux écart sur `/catalogue?role=admin`.
    """
    data = yaml.safe_load((REPO_ROOT / "mcp_server" / "matrice.yaml").read_text())
    profils = data["profils"]
    role_par_profil = {"support": "support", "dev": "dev", "commercial": "commercial",
                        "admin": "admin", "default": "sans_role"}
    return {
        role_par_profil[profil]: [t for t in cfg["tools"] if t != "read_journal"]
        for profil, cfg in profils.items()
    }


def main() -> None:
    out: list[str] = []
    out.append("=== Catalogue effectif par rôle (/catalogue), comparé à mcp_server/matrice.yaml ===")
    with httpx.Client(base_url=BASE, timeout=60) as client:
        for role, attendu in _matrice_par_profil().items():
            resp = client.get("/catalogue", params={"role": role})
            data = resp.json()
            observe = sorted(data.get("tools", []))
            attendu_trie = sorted(attendu)
            statut = "OK" if observe == attendu_trie else "ÉCART"
            out.append(f"[{statut}] rôle={role:<10} observé={observe}")
            if statut == "ÉCART":
                out.append(f"          attendu={attendu_trie}")

        out.append("")
        out.append("=== Scénarios conversationnels (POST /chat) ===")
        passes, echecs, non_notes = [], [], []
        for sc in SCENARIOS:
            resp = client.post("/chat", json={"role": sc["role"], "question": sc["question"]})
            data = resp.json()
            calls = data.get("calls", [])
            calls_str = (", ".join(f"{c['tool']}·{c['status']}·{c['code']}" for c in calls)
                         or "(aucun appel)")
            reussite, motif = evalue(sc, data)
            marque = "N/A " if reussite is None else ("PASS" if reussite else "FAIL")
            (non_notes if reussite is None else passes if reussite else echecs).append((sc, motif))
            out.append(f"--- [{marque}] {sc['id']} ({sc['source']}) ---")
            out.append(f"rôle={sc['role']}  question={sc['question']!r}")
            out.append(f"attendu : tool={sc['attendu_tool']}"
                        + (f", statut={sc['attendu_statut']}" if sc["attendu_statut"] else ""))
            out.append(f"observé : statut={data.get('statut')}  calls=[{calls_str}]")
            out.append(f"réponse : {data.get('answer', '')[:400]!r}")
            if data.get("error"):
                out.append(f"erreur  : {data['error']}")
            if reussite is not True:
                out.append(f"{'non noté' if reussite is None else 'échec'} : {motif}")
            out.append("")

        out.append("=" * 60)
        out.append(f"BILAN : {len(passes)} passed, {len(echecs)} failed, "
                    f"{len(non_notes)} non notés (proxy) — sur {len(SCENARIOS)} scénarios")
        non_pass = [(sc, motif, "FAIL") for sc, motif in echecs] + \
                   [(sc, motif, "N/A ") for sc, motif in non_notes]
        if non_pass:
            out.append("")
            out.append(f"Tout ce qui n'est pas PASS ({len(non_pass)}) :")
            for sc, motif, marque in non_pass:
                out.append(f"  - [{marque}] {sc['id']} ({sc['source']}) : {motif}")

    report = "\n".join(out)
    print(report)
    RAPPORTS.mkdir(parents=True, exist_ok=True)
    with open(RAPPORTS / "cr_test_accept_agent_local.txt", "w", encoding="utf-8") as f:
        f.write(f"Agent conversationnel (packages/agent), en local, API sur {BASE}\n")
        f.write("Chroma : dev (make up, localhost:8002, collection sorabel_corpus)\n")
        f.write("Base   : data/sorabel.db (venv local)\n\n")
        f.write(report + "\n")


if __name__ == "__main__":
    main()
