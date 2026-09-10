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

import ast
import sys
from pathlib import Path
from typing import Any

from packages import journal
from packages.access import load_matrix
from packages.agent.api import ROLES, profile_for_role, role_cards
from packages.agent.cli import (
    NO_ANSWER_CODE,
    NO_ANSWER_MESSAGE,
    NO_ANSWER_STATUS,
    NO_ANSWER_TOOL,
    CallNote,
    NoAnswer,
    compose_answer,
    frozen_notes,
    served_status,
    frozen_text,
    renounced,
)
from packages.agent.cli import _no_answer_note as no_answer_note
from packages.agent.cli import _no_answer_tool as no_answer_tool
from packages.rag_machines.structured_answer import (
    RAG_CLIENT_MESSAGES,
    RAG_STATUS_BY_CODE,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    DB_STATUS_BY_CODE,
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

    print("\nLe renoncement du modèle — la seule enveloppe que le client fabrique")
    # Il existe parce qu'un renoncement n'a pas de verdict : aucun tool n'a échoué, donc
    # rien ne pouvait figer la phrase ni éteindre le vert de la colonne.
    renonce = no_answer_note()
    check("il porte le nom du tool, son code et sa phrase",
          (renonce.tool, renonce.envelope["payload"]["code"], renonce.envelope["message"]),
          (NO_ANSWER_TOOL, NO_ANSWER_CODE, NO_ANSWER_MESSAGE))
    # Le contrôle qui compte : son statut n'est aucun de ceux que les domaines posent. S'il
    # en devenait un, il serait compté comme un refus (E5) ou comme un service rendu.
    check("son statut n'est aucun de ceux des deux domaines",
          NO_ANSWER_STATUS in set(DB_STATUS_BY_CODE.values()) | set(RAG_STATUS_BY_CODE.values()),
          False)
    check("sa phrase est distincte de celle d'un refus de droits",
          NO_ANSWER_MESSAGE in (CLIENT_MESSAGES["tool_interdit"],
                                RAG_CLIENT_MESSAGES["tool_interdit"]), False)
    check("il est reconnu au carnet", (renounced([renonce]), renounced([ok_sql])),
          (True, False))

    print("\nCe que le renoncement remplace, et ce qui garde la parole devant lui")
    check("seul — sa phrase est servie", compose_answer([renonce], DRAFTED),
          NO_ANSWER_MESSAGE)
    # Le cas `SQL-01` sous `dev` : un appel a réussi — pour le modèle — et l'utilisateur
    # n'a rien obtenu. La rédaction ne passe pas, et c'est ce qui éteint le vert.
    check("par-dessus un appel servi — sa phrase, pas la rédaction",
          compose_answer([ok_sql, renonce], DRAFTED), NO_ANSWER_MESSAGE)
    # Le cas `SQL-08` sous `dev` : le corpus dit honnêtement qu'il ne porte pas la réponse,
    # et cette phrase est fausse sur le fond — la question est hors des outils du profil.
    check("par-dessus une non-réponse documentaire — sa phrase, pas celle du corpus",
          compose_answer([hors, renonce], DRAFTED), NO_ANSWER_MESSAGE)
    check("par-dessus un contexte insuffisant — la sienne aussi",
          compose_answer([vide_rag, renonce], DRAFTED), NO_ANSWER_MESSAGE)
    # Mais un verdict de la gateway nomme la cause : la taire effacerait un refus à l'écran.
    for label, note, expected in (
        ("un refus SQL", refus_sql, CLIENT_MESSAGES["perimetre_interdit"]),
        ("un refus documentaire", refus_rag, RAG_CLIENT_MESSAGES["tool_interdit"]),
        ("une panne", panne, CLIENT_MESSAGES["erreur_execution"]),
    ):
        check(f"{label} garde la parole devant le renoncement",
              compose_answer([note, renonce], DRAFTED), expected)
    rendu = compose_answer([clarif, renonce], DRAFTED)
    check("une clarification aussi, avec ses axes",
          rendu.startswith(CLIENT_MESSAGES["clarification"]) and "par mois" in rendu, True)
    check("l'ordre du carnet n'y change rien",
          compose_answer([renonce, refus_sql], DRAFTED),
          CLIENT_MESSAGES["perimetre_interdit"])

    print("\nLe renoncement n'ouvre pas de seconde voie")
    # Une phrase qui remplace ne complète pas : elle sortirait deux fois.
    for label, book in (
        ("seul", [renonce]),
        ("avec un servi", [ok_sql, renonce]),
        ("avec un refus", [refus_sql, renonce]),
    ):
        check(f"{label} — jamais les deux à la fois",
              frozen_text(book) is not None and bool(frozen_notes(book)), False)
    check("rien ne se complète sous un renoncement", frozen_notes([ok_sql, hors, renonce]),
          [])
    # La description est le seul aiguillage du tool, et elle suit la règle posée pour les
    # huit du serveur : aucun nom de tool dans un corps de description, faute de quoi elle
    # recommanderait ce que la matrice ferme.
    description = no_answer_tool("dev").description
    nommes = [nom for nom in ("ask_database", "answer_question", "get_schema",
                              "check_stock", "order_status", "search_docs",
                              "get_document", "list_sources") if nom in description]
    check("sa description ne nomme aucun tool", nommes, [])
    check("elle n'attend aucun argument",
          no_answer_tool("dev").args_schema, {"type": "object", "properties": {}})

    print("\nSa ligne de journal — la seconde moitié de ce que 2bis.10 demande")
    # `entry_for` est pure : elle n'écrit rien, elle met en forme. Le contrôle porte donc sur
    # la ligne telle qu'elle serait écrite, sans toucher au journal du dépôt.
    ligne = journal.entry_for(NO_ANSWER_TOOL, "dev", {"question": "SQL-08"}, NoAnswer())
    check("elle est reconnue journalisable", isinstance(NoAnswer(), journal.Journalable), True)
    # Le champ qui décide d'E5 : un renoncement du modèle n'est pas un refus de la gateway,
    # et le compter `denied` gonflerait le taux de refus de non-réponses.
    check("sa décision est `allowed`, jamais `denied` ni `error`",
          ligne["decision"], "allowed")
    check("le code et le statut sont les siens",
          (ligne["code"], ligne["status"]), (NO_ANSWER_CODE, NO_ANSWER_STATUS))
    # Aucune couche n'a bloqué : `etage` et `blocked_at` restent vides, et c'est ce qui
    # distingue cette ligne d'un arrêt à l'étage 2.
    check("aucune couche n'a bloqué", (ligne["etage"], ligne["blocked_at"], ligne["forbidden"]),
          (None, None, []))
    check("le profil et la question y sont",
          (ligne["profile"], ligne["arguments"]), ("dev", {"question": "SQL-08"}))
    check("la phrase lue par l'utilisateur y est, mot pour mot",
          ligne["client_message"], NO_ANSWER_MESSAGE)
    check("rien de technique n'y a été inventé",
          (ligne["cause"], ligne["stack"], ligne["sql"]), ("", "", ""))

    print("\nLe statut du tour — ce que la colonne affiche, et 2bis.9")
    # Le défaut, tel qu'il a été relevé le 2026-09-08 : `get_schema` réussit, le modèle
    # renonce, tous les verdicts sont `ok`, donc la colonne était verte sur une colonne qui
    # n'avait rien obtenu.
    check("le cas de 2bis.9 — un appel servi, puis un renoncement",
          served_status([ok_sql, renonce]), NO_ANSWER_STATUS)
    check("et il n'est surtout pas `ok`", served_status([ok_sql, renonce]) == "ok", False)
    check("le cas de SQL-08 — la non-réponse documentaire ne colore plus la colonne",
          served_status([hors, renonce]), NO_ANSWER_STATUS)
    # Ce que la règle garde de sa sévérité : un incident reste lisible même quand la réponse
    # a été servie à côté. Le badge et le texte ne répondent pas à la même question.
    check("un refus survenu en chemin colore la colonne, réponse servie ou non",
          served_status([ok_sql, refus_sql]), "refused")
    check("une panne aussi", served_status([ok_rag, panne]), "error")
    check("et il passe devant le renoncement",
          served_status([refus_sql, renonce]), "refused")
    check("sinon, la première non-réponse", served_status([ok_sql, hors]), "hors_corpus")
    check("tout servi — `ok`", served_status([ok_sql, ok_rag]), "ok")
    check("aucun appel — ni `ok` ni un statut du contrat", served_status([]), "aucun_appel")
    # La garantie qui ferme 2bis.9 : sur aucun carnet la colonne ne peut être verte pendant
    # qu'une phrase figée remplace la réponse. C'est la cohérence des deux lectures.
    carnets = [[renonce], [ok_sql, renonce], [hors, renonce], [vide_rag, renonce],
               [refus_sql], [panne], [hors], [clarif], [ok_sql, refus_sql, renonce]]
    verts = [i for i, book in enumerate(carnets)
             if frozen_text(book) is not None and served_status(book) == "ok"]
    check("jamais vert pendant qu'une phrase figée remplace la réponse", verts, [])

    print("\nLes rôles servis — le front n'a plus de liste, ni de lecture de la matrice")
    # Ce que ces contrôles ancrent : *ce que le client affiche des droits, il le demande au
    # serveur*. La règle a été posée à l'étape C pour le catalogue et jamais étendue au reste ;
    # le découplage du front l'a rendue exigible, parce que deux processus séparés ne
    # partagent plus un `matrice.yaml` sur le même disque.
    cards = role_cards()
    check("une carte par rôle, dans l'ordre servi", [c.role for c in cards], ROLES)
    # Une liste en dur côté front divergerait de la matrice le jour où un profil y est ajouté
    # ou renommé — et un rôle inconnu retombe SILENCIEUSEMENT sur `default`. C'est le défaut
    # que `scripts/mcp_client.py` a corrigé de son côté ; ici on interdit qu'il revienne.
    matrix = load_matrix()
    inconnus = [c.role for c in cards if profile_for_role(c.role) not in matrix]
    check("chaque rôle servi désigne un profil qui existe dans la matrice", inconnus, [])
    check("`sans_role` désigne le profil à zéro droit", profile_for_role("sans_role"),
          "default")
    check("un rôle inconnu aussi", profile_for_role("profil-inexistant"), "default")
    check("chaque carte porte un libellé et une phrase de droits",
          [c.role for c in cards if not c.display_name or not c.summary], [])
    # La phrase est calculée sur la matrice, pas écrite : un profil qui n'a pas le tool de
    # lecture de données doit l'annoncer, sinon un refus passe pour une panne.
    muets = [c.role for c in cards
             if "ask_database" not in matrix[profile_for_role(c.role)].tools
             and "aucun chiffre" not in c.summary]
    check("un profil sans lecture de données l'annonce", muets, [])

    # Le contrôle structurel, et le seul qui empêche le découplage de se refermer : un import
    # suffirait à réintroduire une seconde copie de la source d'autorité. Contrôlé sur l'arbre
    # syntaxique et non par recherche de texte — un commentaire ou une chaîne ne compte pas.
    front = sorted(Path(__file__).resolve().parents[2].glob("packages/web_client/*.py"))
    interdits = ("packages.access", "packages.agent", "config", "mcp_server")
    fautifs = []
    for module in front:
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                noms = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                noms = [node.module or ""]
            else:
                continue
            if any(nom == bad or nom.startswith(f"{bad}.")
                   for nom in noms for bad in interdits):
                fautifs.append(f"{module.name}:{node.lineno}")
    check("le front n'importe aucune source d'autorité du backend", fautifs, [])
    check("et il y a bien des modules de front à contrôler", len(front) >= 3, True)

    print()
    if failures:
        print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
        return 1
    print("Tous les contrôles passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
