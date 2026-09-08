"""Contrôles du dernier mètre : ce que le client affiche, à partir de ce que la gateway rend.

**Le premier contrôle du client.** Les cinq suites existantes portent sur les couches en
dessous — ``check-sql``, ``check-feedback`` et ``check-rag-tools`` sur les deux domaines,
``check-perimetre`` sur le corpus, ``check-contrat`` sur le serveur MCP. Aucune ne regardait
``packages/agent``, et ``frozen_text`` — qui décide si l'utilisateur lit une phrase du serveur
ou un texte du modèle — n'était couvert par rien.

Ce que ce contrôle ancre est une **table de vérité**, et elle a une histoire : la règle
d'origine était « le premier verdict non-``ok`` gagne, sur tout », juste tant qu'un tour
n'avait qu'un seul appel de tool. Le 2026-09-08, l'aiguillage s'est mis à en appeler deux pour
une même question, et la règle est devenue fausse — mesuré trois fois sur trois : une
non-réponse documentaire écrasait un résultat SQL obtenu à côté, et l'utilisateur perdait une
donnée à laquelle il avait droit.

La règle est donc bornée : **on substitue quand rien n'a été servi, on complète sinon.** Deux
propriétés qu'aucun test d'intégration ne donnerait, parce qu'elles portent sur des
combinaisons que le modèle ne produit pas à la demande :

1. **ce qui est ``ok`` est toujours servi** — il a franchi les étages 2 et 3, donc le retenir
   à l'écran ne protège rien ;
2. **ce qui n'a pas abouti est toujours dit, et dit avec SA phrase** — jamais avec celle du
   modèle, jamais reformulé, jamais silencieux.

**Aucun appel de modèle, aucun accès à Chroma, à SQLite ou au journal.** Les enveloppes sont
construites par les sérialiseurs réels des deux domaines — ``client_view()`` et
``rag_client_view()`` — et non recopiées à la main : une table de vérité bâtie sur des
enveloppes fabriquées ne contrôlerait que sa propre fabrication.

Un contrôle qui plante ne contrôle rien : le script **rapporte** ses verdicts, y compris quand
ils sont faux.
"""

from __future__ import annotations

import sys
from typing import Any

from packages.agent.cli import CallNote, compose_answer, frozen_notes, frozen_text
from packages.rag_machines.structured_answer import (
    RAG_CLIENT_MESSAGES,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    build_db_structured_answer,
    client_view,
)

#: Le texte que le modèle aurait rédigé. Sa valeur est indifférente : ce qui est contrôlé est
#: s'il survit, et ce qui s'y ajoute.
DRAFTED = "Le texte rédigé par le modèle."


def _sql(code: str, **charge: Any) -> CallNote:
    return CallNote("ask_database", client_view(build_db_structured_answer(code, **charge)))


def _rag(code: str, **charge: Any) -> CallNote:
    return CallNote("answer_question",
                    rag_client_view(build_rag_structured_answer(code, **charge)))


def main() -> int:
    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        rendered = repr(actual)
        if len(rendered) > 70:
            rendered = rendered[:67] + "..."
        print(f"  [{mark}] {label:<58} {rendered}")
        if actual != expected:
            failures.append(label)

    # Les charges utiles minimales de chaque code servi : `client_view` filtre par code, donc
    # une enveloppe `ok` sans ses clés ne serait pas celle qu'un tool rend.
    ok_sql = _sql("ok", sql="SELECT 1", columns=["a"], rows=[[1]])
    ok_rag = _rag("ok", answer="x", sources=[])
    aucune = _sql("aucune_ligne", sql="SELECT 1", columns=[], rows=[])
    refus_sql = _sql("perimetre_interdit", etage=3, forbidden=["produits.marge_pct"])
    refus_rag = _rag("tool_interdit", etage=2)
    panne = _sql("erreur_execution", cause="X")
    clarif = _sql("clarification", axes=["par mois", "par région"])
    vide_rag = _rag("contexte_insuffisant")
    hors = _rag("hors_corpus")

    print("Les statuts, tels que les domaines les posent")
    # Le pivot de toute la table : `aucune_ligne` est SERVI (`ok`), là où les deux
    # non-réponses documentaires ne le sont pas. C'est cette asymétrie qui rendait le
    # comportement d'origine incohérent d'un domaine à l'autre.
    check("ok SQL et ok RAG sont servis",
          [ok_sql.envelope["status"], ok_rag.envelope["status"]], ["ok", "ok"])
    check("aucune_ligne est servi, lui aussi", aucune.envelope["status"], "ok")
    check("les deux non-réponses documentaires ne le sont pas",
          [vide_rag.envelope["status"], hors.envelope["status"]],
          ["hors_corpus", "hors_corpus"])
    check("un refus, une panne et une clarification non plus",
          [refus_sql.envelope["status"], panne.envelope["status"], clarif.envelope["status"]],
          ["refused", "error", "clarification"])

    print("\nRien n'a été servi : la phrase figée REMPLACE la réponse")
    # Le comportement d'origine, et il ne bouge pas : c'est la garantie que le refus ne se
    # renégocie pas au dernier mètre.
    for label, note, expected in (
        ("un refus SQL", refus_sql, CLIENT_MESSAGES["perimetre_interdit"]),
        ("un refus documentaire", refus_rag, RAG_CLIENT_MESSAGES["tool_interdit"]),
        ("une panne", panne, CLIENT_MESSAGES["erreur_execution"]),
        ("une non-réponse documentaire", hors, RAG_CLIENT_MESSAGES["hors_corpus"]),
        ("un contexte insuffisant", vide_rag, RAG_CLIENT_MESSAGES["contexte_insuffisant"]),
    ):
        check(f"{label} — substitue", compose_answer([note], DRAFTED), expected)
    # Une clarification emporte ses axes : la phrase seule ne dit pas quoi préciser.
    rendu = compose_answer([clarif], DRAFTED)
    check("une clarification — substitue avec ses axes",
          rendu.startswith(CLIENT_MESSAGES["clarification"]) and "par mois" in rendu, True)

    print("\nQuelque chose a été servi : la phrase figée COMPLÈTE la réponse")
    # Le cas mesuré le 2026-09-08, trois passes sur trois : une non-réponse documentaire
    # écrasait le stock. Elle le complète désormais, et sa phrase reste mot pour mot.
    mesure = compose_answer([vide_rag, aucune], DRAFTED)
    check("le cas mesuré — le texte servi survit", mesure.startswith(DRAFTED), True)
    check("le cas mesuré — et la non-réponse est dite",
          RAG_CLIENT_MESSAGES["contexte_insuffisant"] in mesure, True)
    for label, book in (
        ("ok + non-réponse", [ok_sql, hors]),
        ("non-réponse + ok — l'ordre n'y change rien", [hors, ok_sql]),
        ("ok + refus", [ok_rag, refus_sql]),
        ("ok + panne", [ok_sql, panne]),
        ("ok + clarification", [ok_rag, clarif]),
    ):
        rendu = compose_answer(book, DRAFTED)
        check(f"{label} — le texte survit", rendu.startswith(DRAFTED), True)
        check(f"{label} — la phrase figée est ajoutée",
              rendu.count(DRAFTED) == 1 and len(rendu) > len(DRAFTED), True)

    print("\nCe qui est servi seul, et ce qui ne se répète pas")
    check("deux appels servis — le texte du modèle, et lui seul",
          compose_answer([ok_sql, ok_rag], DRAFTED), DRAFTED)
    check("aucun appel — le texte du modèle", compose_answer([], DRAFTED), DRAFTED)
    check("aucune_ligne ne complète rien : il est servi",
          compose_answer([ok_sql, aucune], DRAFTED), DRAFTED)
    # Deux tools refusés pour le même motif rendent la même phrase ; la répéter donnerait à
    # lire une insistance qui n'existe pas.
    double = compose_answer([ok_sql, refus_rag, CallNote("search_docs", refus_rag.envelope)],
                            DRAFTED)
    check("un motif répété ne se dit qu'une fois",
          double.count(RAG_CLIENT_MESSAGES["tool_interdit"]), 1)
    # Et le modèle lui-même recopie la phrase quand la consigne du serveur le lui demande —
    # mesuré, deux passes sur trois sur une référence inexistante. Elle ne s'ajoute donc pas
    # une seconde fois.
    deja = f"{DRAFTED} {RAG_CLIENT_MESSAGES['hors_corpus']}"
    check("une phrase déjà recopiée par le modèle n'est pas ajoutée",
          compose_answer([ok_sql, hors], deja).count(RAG_CLIENT_MESSAGES["hors_corpus"]), 1)
    check("mais elle y est bien restée une fois",
          RAG_CLIENT_MESSAGES["hors_corpus"] in compose_answer([ok_sql, hors], deja), True)
    # Une paraphrase du modèle ne compte pas comme la phrase figée : celle-ci doit alors être
    # ajoutée, faute de quoi rien ne garantirait plus qu'elle soit servie mot pour mot.
    check("une paraphrase ne dispense pas de la phrase",
          RAG_CLIENT_MESSAGES["hors_corpus"] in compose_answer(
              [ok_sql, hors], "Je n'ai rien trouvé dans les documents."), True)
    # Deux motifs distincts se disent tous les deux, dans l'ordre du carnet.
    deux = frozen_notes([ok_sql, hors, refus_sql])
    check("deux motifs distincts, dans l'ordre du carnet", deux,
          [RAG_CLIENT_MESSAGES["hors_corpus"], CLIENT_MESSAGES["perimetre_interdit"]])

    print("\nLes deux fonctions sont exclusives")
    # Une phrase qui remplace ne doit pas aussi compléter : elle sortirait deux fois.
    for label, book in (
        ("rien servi", [hors]),
        ("un servi", [ok_sql, hors]),
        ("tout servi", [ok_sql]),
        ("carnet vide", []),
    ):
        check(f"{label} — jamais les deux à la fois",
              frozen_text(book) is not None and bool(frozen_notes(book)), False)
    check("rien servi — frozen_text parle seul",
          (frozen_text([hors]) is not None, frozen_notes([hors])), (True, []))
    check("un servi — frozen_notes parle seul",
          (frozen_text([ok_sql, hors]), len(frozen_notes([ok_sql, hors]))), (None, 1))

    print("\nLa phrase servie est celle du domaine, jamais une reconstruction")
    # La recherche porte sur l'égalité stricte : une phrase reformulée, tronquée ou
    # concaténée passerait un test de sous-chaîne.
    check("le refus SQL, mot pour mot", frozen_text([refus_sql]),
          CLIENT_MESSAGES["perimetre_interdit"])
    check("la non-réponse documentaire, mot pour mot", frozen_notes([ok_sql, hors]),
          [RAG_CLIENT_MESSAGES["hors_corpus"]])
    # Et la colonne fermée ne part pas au client, même en régime de complément : c'est E5,
    # au dernier mètre.
    servi = compose_answer([ok_sql, refus_sql], DRAFTED)
    check("aucune colonne fermée dans le texte servi",
          [motif for motif in ("marge_pct", "prix_achat_ht", "marge_ht") if motif in servi],
          [])

    print()
    if failures:
        print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
        return 1
    print("Tous les contrôles passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
