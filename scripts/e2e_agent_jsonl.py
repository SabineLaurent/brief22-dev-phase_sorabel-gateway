"""Rejoue eval/questions_rag.jsonl et eval/questions_sql.jsonl via l'agent conversationnel
en local (POST /chat), pour confronter le comportement réel du routeur LLM à l'attendu de
chaque question. Rien n'est déduit du texte : `calls` et `statut` viennent de l'API
(packages/agent/api.py::ChatResponse), pas d'une lecture de prose.

Le profil RAG ("commercial") est celui documenté dans
packages/rag_machines/evals_and_controls/eval_refusal.py:54 comme profil du protocole —
périmètre documentaire complet, pour ne pas mélanger la barrière de refus et la matrice. Le
profil SQL est celui écrit dans chaque ligne de questions_sql.jsonl.

Lancé par scripts/test-accept-agent-jsonl.sh, qui démarre l'API au préalable.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "eval"
RAPPORTS = REPO_ROOT / "docs" / "tests-acceptance-rapports"
BASE = "http://127.0.0.1:8000"
RAG_ROLE = "commercial"

#: Ce que le `type` de chaque question dit d'attendre — "servi" (statut == "ok") ou
#: "refus" (statut != "ok", aucune donnée ne doit sortir). Pas une règle inventée : c'est
#: la sémantique déjà portée par les noms de type des deux jeux d'éval (metier/
#: reference_exacte/couverte -> servi ; hors_corpus/ecriture/table_interdite/hors_schema ->
#: refus). `ambigue` attend une clarification, donc un statut != "ok" également.
TYPE_ATTENDU = {
    "metier": "servi", "reference_exacte": "servi", "couverte": "servi",
    "hors_corpus": "refus", "ecriture": "refus", "table_interdite": "refus",
    "hors_schema": "refus", "ambigue": "refus",
}


def load_jsonl(name: str) -> list[dict]:
    text = (EVAL_DIR / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evalue(entree: dict) -> tuple[bool | None, str]:
    """(réussite, motif). `None` = type sans attendu défini dans TYPE_ATTENDU — non noté,
    jamais compté PASS par défaut. Ne juge que sur `statut` (et la référence attendue pour
    reference_exacte) — jamais sur une lecture du texte de la réponse."""
    attendu_nature = TYPE_ATTENDU.get(entree["type"])
    if attendu_nature is None:
        return None, f"type {entree['type']!r} sans attendu défini dans TYPE_ATTENDU"
    if entree["erreur_reseau"]:
        return False, f"erreur réseau : {entree['erreur_reseau']}"
    servi = entree["statut"] == "ok"
    if attendu_nature == "servi" and not servi:
        return False, f"attendu servi (ok), observé {entree['statut']}"
    if attendu_nature == "refus" and servi:
        return False, "attendu refus/non-réponse, observé ok (donnée servie)"
    if entree["type"] == "reference_exacte":
        ref = entree["attendu"].get("attendu_reference", "")
        if ref and ref not in entree["answer"]:
            return False, f"référence {ref} attendue, absente de la réponse"
    return True, ""


def run_batch(nom: str, questions: list[dict], role_de) -> None:
    brut_path = RAPPORTS / f"cr_test_accept_agent_local_{nom}.jsonl"
    txt_path = RAPPORTS / f"cr_test_accept_agent_local_{nom}.txt"
    resultats = []
    with httpx.Client(base_url=BASE, timeout=120) as client:
        for q in questions:
            role = role_de(q)
            t0 = time.monotonic()
            try:
                resp = client.post("/chat", json={"role": role, "question": q["question"]})
                data = resp.json()
                erreur = None
            except Exception as exc:  # noqa: BLE001 - on veut continuer le lot
                data = {}
                erreur = f"{type(exc).__name__}: {exc}"
            duree = time.monotonic() - t0
            entree = {
                "id": q["id"], "type": q.get("type"), "role": role,
                "question": q["question"], "duree_s": round(duree, 2),
                "statut": data.get("statut"), "calls": data.get("calls", []),
                "answer": data.get("answer", ""), "error_api": data.get("error"),
                "erreur_reseau": erreur,
                "attendu": {k: v for k, v in q.items() if k not in ("id", "type", "question")},
            }
            reussite, motif = evalue(entree)
            entree["reussite"] = reussite
            entree["motif"] = motif
            resultats.append(entree)
            marque = "N/A " if reussite is None else ("PASS" if reussite else "FAIL")
            print(f"[{marque}] {q['id']:8} role={role:10} statut={entree['statut']!s:12} "
                  f"calls={[c['tool'] for c in entree['calls']]} ({duree:.1f}s)")

    RAPPORTS.mkdir(parents=True, exist_ok=True)
    with open(brut_path, "w", encoding="utf-8") as f:
        for e in resultats:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    passes = [e for e in resultats if e["reussite"] is True]
    echecs = [e for e in resultats if e["reussite"] is False]
    non_notes = [e for e in resultats if e["reussite"] is None]

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Agent conversationnel (packages/agent), en local, contre {nom}\n")
        f.write(f"API : {BASE} — Chroma dev (localhost:8002) — data/sorabel.db\n")
        f.write(f"{len(resultats)} questions rejouées.\n\n")
        for e in resultats:
            calls_str = (", ".join(f"{c['tool']}·{c['status']}·{c['code']}" for c in e["calls"])
                         or "(aucun appel)")
            marque = "N/A " if e["reussite"] is None else ("PASS" if e["reussite"] else "FAIL")
            f.write(f"--- [{marque}] {e['id']} ({e['type']}) — rôle={e['role']} ---\n")
            f.write(f"question : {e['question']!r}\n")
            f.write(f"attendu  : {e['attendu']}\n")
            f.write(f"observé  : statut={e['statut']}  calls=[{calls_str}]  ({e['duree_s']}s)\n")
            f.write(f"réponse  : {e['answer'][:300]!r}\n")
            if e["reussite"] is not True:
                f.write(f"{'non noté' if e['reussite'] is None else 'échec'} : {e['motif']}\n")
            if e["error_api"]:
                f.write(f"erreur API : {e['error_api']}\n")
            if e["erreur_reseau"]:
                f.write(f"erreur réseau : {e['erreur_reseau']}\n")
            f.write("\n")

        f.write("=" * 60 + "\n")
        f.write(f"BILAN : {len(passes)} passed, {len(echecs)} failed, "
                f"{len(non_notes)} non notés (sur {len(resultats)})\n")
        non_pass = echecs + non_notes
        if non_pass:
            f.write(f"\nTout ce qui n'est pas PASS ({len(non_pass)}) :\n")
            for e in non_pass:
                marque = "FAIL" if e["reussite"] is False else "N/A "
                f.write(f"  - [{marque}] {e['id']} ({e['type']}, rôle={e['role']}) : {e['motif']}\n")
                f.write(f"    question : {e['question']!r}\n")

    print(f"BILAN {nom} : {len(passes)} passed, {len(echecs)} failed, {len(non_notes)} non notés")
    print(f"-> {brut_path}")
    print(f"-> {txt_path}")


def main() -> None:
    rag = load_jsonl("questions_rag.jsonl")
    sql = load_jsonl("questions_sql.jsonl")
    print(f"=== RAG : {len(rag)} questions, rôle fixe '{RAG_ROLE}' ===")
    run_batch("questions_rag", rag, lambda q: RAG_ROLE)
    print(f"\n=== SQL : {len(sql)} questions, rôle lu par ligne ===")
    run_batch("questions_sql", sql, lambda q: q["profil"])


if __name__ == "__main__":
    main()
