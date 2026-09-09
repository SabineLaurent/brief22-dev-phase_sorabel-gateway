"""Contrôles de la réponse structurée et du journal, côté documentaire.

**Aucun appel de modèle.** La rédaction passe par une doublure ; la recherche, elle, tape
bien l'index — c'est le seul moyen de vérifier que le périmètre filtre pour de vrai, et
Chroma est déterministe à index constant. Le journal est écrit dans un répertoire
temporaire, jamais dans celui du dépôt.

Le pendant de ``check_feedback.py`` pour le RAG, et il établit les mêmes sept points :

1. **Forme** — la vue client rend exactement les trois champs du contrat DSI.
2. **Étanchéité** — la cause technique, la trace d'exception et les collections refusées ne
   se retrouvent **nulle part** dans le JSON servi. La recherche porte sur la sous-chaîne,
   pas sur l'absence de clé : une fuite par concaténation serait invisible à un contrôle de
   clés.
3. **Déterminisme** — des appels identiques rendent des réponses identiques. C'est ce que
   la phrase figée garantit, et ce que le jet mis de côté ne garantissait pas : il servait
   au client le nom de la collection qu'il venait de lui refuser.
4. **Complétude** — tout code a sa phrase et son statut. Sans ce contrôle, un code ajouté
   demain tomberait silencieusement sur le repli « service indisponible ».
5. **Filet** — une panne à l'intérieur d'un tool ne traverse pas le handler.
6. **Journal** — une ligne par appel, dans l'ordre, avec ``blocked_at`` renseigné selon la
   couche qui a tranché.
7. **Périmètre** — les décomptes en or de ``check_perimeter.py`` (270 / 318 / 350) se
   retrouvent à travers ``list_sources``, c'est-à-dire à travers la matrice **et** la vue
   client. Le filtre est déjà contrôlé en amont ; ce qui est vérifié ici, c'est qu'il
   arrive intact jusqu'au bout de la chaîne de réponse.

Un contrôle qui plante ne contrôle rien : le script **rapporte** les verdicts, y compris
quand ils sont faux.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from config import Settings
from config import settings as base_settings
from packages import journal
from packages.rag_machines.handler import RAG_TOOLS, handle
from packages.rag_machines.structured_answer import (
    PAYLOAD_KEPT,
    RAG_CLIENT_MESSAGES,
    RAG_STATUS_BY_CODE,
    REFUSAL_CODES,
    SERVED_CODES,
    build_rag_structured_answer,
    rag_client_view,
)
from packages.rag_machines.retrieval.search import cap_per_title
from packages.rag_machines.tools import (
    answer_question,
    question_for_writer,
    threshold_for,
)
from packages.rag_machines.writer import Answer, AnswerWriter

#: Le texte que la doublure « écrit ». Reconnaissable exprès : on le cherche ensuite dans
#: la vue client (il ne doit pas y être) et dans le journal (il doit y être). Une chaîne
#: banale ne prouverait rien.
MODEL_TEXT = "TEXTE-DU-MODELE-A-NE-PAS-AFFICHER"

#: Les trois champs du contrat d'intégration, et eux seuls.
DSI_KEYS = {"status", "payload", "message"}

#: Une note fermée au support par son thème, ouverte au commercial. C'est le contournement
#: que ``get_document`` doit refuser : le chemin de fichier seul suffirait sans l'étage 3.
CLOSED_NOTE = "notes/note-2024-05-04-politique-tarifaire-71"

#: Décomptes en or, vérifiés contre l'index par ``check_perimeter.py``. Ils sont recopiés
#: ici pour être relus **à travers la chaîne de réponse** plutôt qu'à travers le filtre.
GOLDEN_COUNTS = {"dev": 270, "support": 318, "commercial": 350}


class _SufficientWriter(AnswerWriter):
    """**Doublure de test.** Un rédacteur qui répond, sans appeler Azure."""

    def __init__(self) -> None:
        super().__init__("", "", "scripté")

    def write(self, question: str, excerpts: list[str]) -> Answer:  # type: ignore[override]
        return Answer("Réponse scriptée.", "", (1,))


class _InsufficientWriter(AnswerWriter):
    """**Doublure de test.** Un rédacteur qui déclare les extraits insuffisants.

    C'est le cas qui motive la séparation : le texte qu'il rend est *son* énoncé, il doit
    partir au journal et non à l'écran.
    """

    def __init__(self) -> None:
        super().__init__("", "", "scripté")

    def write(self, question: str, excerpts: list[str]) -> Answer:  # type: ignore[override]
        return Answer("", MODEL_TEXT)


class _ExplodingWriter(AnswerWriter):
    """**Doublure de test.** Un rédacteur qui lève, comme le ferait un SDK injoignable."""

    def __init__(self) -> None:
        super().__init__("", "", "scripté")

    def write(self, question: str, excerpts: list[str]) -> Answer:  # type: ignore[override]
        raise RuntimeError(MODEL_TEXT)


class _CapturingWriter(AnswerWriter):
    """**Doublure de test.** Un rédacteur qui répond, et retient l'énoncé qu'on lui a passé.

    C'est le seul moyen de contrôler la réécriture de la référence nue sans appeler de
    modèle : ce qui est vérifié n'est pas ce que le modèle en fait, c'est ce que la gateway
    lui donne à lire.
    """

    def __init__(self) -> None:
        super().__init__("", "", "scripté")
        self.asked: list[str] = []

    def write(self, question: str, excerpts: list[str]) -> Answer:  # type: ignore[override]
        self.asked.append(question)
        return Answer("Réponse scriptée.", "", (1,))


def main() -> int:
    failures: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        mark = "ok  " if actual == expected else "ÉCHEC"
        print(f"  [{mark}] {label:<58} {actual!r} (attendu {expected!r})")
        if actual != expected:
            failures.append(label)

    def verdict() -> int:
        print()
        if failures:
            print(f"{len(failures)} contrôle(s) en échec : " + ", ".join(failures))
            return 1
        print("Tous les contrôles passent.")
        return 0

    with TemporaryDirectory() as tmp:
        settings = base_settings.model_copy(
            update={"gateway_journal": Path(tmp) / "journal.jsonl"}
        )
        return _run(settings, check, verdict)


def _run(settings: Settings, check, verdict) -> int:  # noqa: ANN001 - deux fermetures locales
    journal_file = Path(settings.gateway_journal)

    def lines() -> list[dict]:
        """Les entrées du journal, relues **du fichier** — pas de la mémoire."""
        if not journal_file.exists():
            return []
        return [json.loads(line)
                for line in journal_file.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    print("Tables de codes")
    check("les quatre tools du catalogue documentaire", sorted(RAG_TOOLS),
          ["answer_question", "get_document", "list_sources", "search_docs"])
    check("tout code a un statut et une phrase",
          sorted(RAG_STATUS_BY_CODE) == sorted(set(RAG_CLIENT_MESSAGES) - {"argument_malforme"}),
          True)
    check("les statuts sont ceux du contrat DSI",
          sorted(set(RAG_STATUS_BY_CODE.values())),
          ["error", "hors_corpus", "ok", "refused"])
    # Le piège le plus facile de ce module : `hors_corpus` dit « je n'ai pas trouvé », pas
    # « je ne vous le donnerai pas ». Le compter en refus gonflerait E5 de non-réponses.
    check("hors_corpus n'est pas un refus", "hors_corpus" in REFUSAL_CODES, False)
    check("contexte_insuffisant n'est pas un refus non plus",
          "contexte_insuffisant" in REFUSAL_CODES, False)
    check("les deux refus sont ceux de la matrice", sorted(REFUSAL_CODES),
          ["perimetre_interdit", "tool_interdit"])
    check("aucun refus ne conserve de payload",
          [code for code in REFUSAL_CODES if code in PAYLOAD_KEPT], [])
    check("hors_corpus ne conserve pas de payload non plus",
          "hors_corpus" in PAYLOAD_KEPT, False)
    check("les codes servis portent blocked_at = 0",
          {code: build_rag_structured_answer(code).blocked_at for code in sorted(SERVED_CODES)},
          {"aucune_ligne": 0, "introuvable": 0, "ok": 0})

    print("\nPlafond de candidats par titre")
    # Cinq séries de 16 notes datées portent le même titre : sans plafond, deux séries
    # suffisent à remplir les 20 places du budget de rerank, et le document qui répond
    # n'est jamais noté (`2bis.1`). Les contrôles portent sur la fonction, pas sur une
    # question : elle est pure, donc son résultat est un fait et non une observation.
    serie = [(f"n{i}", "", {"titre": "Alerte qualité fournisseur"}) for i in range(16)]
    autres = [(f"p{i}", "", {"titre": f"Procédure SAV {i}"}) for i in range(4)]
    plafonne = cap_per_title(serie + autres, 3)
    check("rien n'est perdu — différer, jamais exclure",
          len(plafonne), len(serie + autres))
    check("le titre redondant n'occupe que ses places",
          [doc_id for doc_id, _, meta in plafonne[:7]
           if meta["titre"] == "Alerte qualité fournisseur"],
          ["n0", "n1", "n2"])
    check("les autres titres remontent dans le budget",
          [doc_id for doc_id, _, _ in plafonne[:7]],
          ["n0", "n1", "n2", "p0", "p1", "p2", "p3"])
    check("les différés repassent en queue, dans leur ordre",
          [doc_id for doc_id, _, _ in plafonne[7:]],
          [f"n{i}" for i in range(3, 16)])
    check("un vivier pauvre en titres garde le budget plein",
          len(cap_per_title(serie, 3)), 16)
    # `None` est le réglage d'avant le correctif, et c'est ce qui rend la couche
    # inerte : la même liste ressort, identique et dans le même ordre.
    check("sans plafond, la liste est rendue telle quelle",
          cap_per_title(serie + autres, None) == serie + autres, True)

    print("\nSeuil de refus, par configuration")
    # Les échelles ne sont pas comparables : servir l'un pour l'autre ferait refuser
    # presque tout, ou ne refuserait jamais rien.
    check("dense", threshold_for("dense", settings), settings.refusal_threshold)
    check("hybride", threshold_for("hybrid", settings), settings.rerank_threshold)
    check("lexical n'a pas d'échelle bornée", threshold_for("lexical", settings), None)

    print("\nÉtage 2 — le droit d'appeler le tool")
    view = handle("list_sources", {}, "default", settings)
    check("un profil sans droits est refusé", view["status"], "refused")
    check("et n'apprend rien du refus", view["payload"], {"code": "tool_interdit"})
    check("le journal dit quelle couche a bloqué", lines()[-1]["blocked_at"], 2)
    check("et la nomme en clair", lines()[-1]["etage"], 2)
    check("la décision est un refus", lines()[-1]["decision"], "denied")

    print("\nÉtage 3 — le périmètre documentaire")
    view = handle("get_document", {"doc_id": CLOSED_NOTE}, "support", settings)
    check("une note fermée par son thème est refusée", view["status"], "refused")
    check("le refus est de périmètre, pas d'introuvable",
          lines()[-1]["code"], "perimetre_interdit")
    check("la couche bloquante est la troisième", lines()[-1]["blocked_at"], 3)
    # Le contournement que cet étage existe pour fermer : le chemin de fichier seul
    # suffirait, puisque get_document n'emprunte pas le filtre d'index.
    check("le thème fermé est nommé au journal", lines()[-1]["forbidden"],
          ["note_interne/politique-tarifaire"])
    check("mais jamais au client", "politique-tarifaire" in json.dumps(view), False)
    granted = handle("get_document", {"doc_id": CLOSED_NOTE}, "commercial", settings)
    check("le commercial la lit", granted["payload"]["code"], "ok")
    check("et en reçoit le texte", bool(granted["payload"]["text"].strip()), True)

    # `introuvable` partage le statut `ok` avec une lecture servie — c'est un constat
    # d'absence, pas une panne, et en faire une `error` ferait compter au journal des
    # échecs qui n'ont pas eu lieu. Ce que le client ne peut pas faire, c'est confondre
    # les deux : la clé `text` est absente, donc il n'a rien à afficher.
    absent = handle("get_document", {"doc_id": "fiches/REF-0000-v9.9"}, "commercial", settings)
    check("un document absent n'est pas une erreur", absent["payload"]["code"], "introuvable")
    check("ni un refus", lines()[-1]["decision"], "allowed")
    check("mais il n'y a rien à afficher", "text" in absent["payload"], False)
    check("et la phrase le dit", absent["message"],
          RAG_CLIENT_MESSAGES["introuvable"])

    print("\nForme et étanchéité de la vue client")
    check("trois clés, celles du DSI", set(view), DSI_KEYS)
    check("un tool inconnu n'est pas un refus de droits",
          handle("drop_everything", {}, "commercial", settings)["payload"]["code"],
          "erreur_execution")
    check("et ne dit pas ce qu'il ne connaît pas",
          "drop_everything" in json.dumps(handle("drop_everything", {}, "commercial", settings)),
          False)
    check("argument manquant", handle("search_docs", {}, "support", settings)["status"],
          "error")
    check("le format attendu est dit sans nommer d'interne",
          handle("search_docs", {}, "support", settings)["message"],
          RAG_CLIENT_MESSAGES["argument_malforme"])

    print("\nDéterminisme de l'énoncé")
    repeated = [handle("get_document", {"doc_id": CLOSED_NOTE}, "support", settings)
                for _ in range(4)]
    check("quatre refus identiques", len({json.dumps(v, sort_keys=True) for v in repeated}), 1)

    print("\nSeconde barrière — le modèle juge les extraits insuffisants")
    answer = answer_question("délai d'un échange standard ?", "support", settings=settings,
                             writer=_InsufficientWriter())
    check("le code distingue les deux non-réponses", answer.code, "contexte_insuffisant")
    check("mais le statut est celui du contrat", answer.status, "hors_corpus")
    check("le texte du modèle reste dans la cause", answer.cause, MODEL_TEXT)
    served = rag_client_view(answer)
    check("le client ne lit pas le texte du modèle", MODEL_TEXT in json.dumps(served), False)
    check("il lit une phrase figée", served["message"],
          RAG_CLIENT_MESSAGES["contexte_insuffisant"])
    check("et n'a rien à afficher comme réponse", served["payload"].get("answer"), None)
    # `blocked_at` reste None : aucune couche de sécurité n'a tranché — c'est le corpus qui
    # ne porte pas la réponse, et la distinction est précisément ce que le champ mesure.
    check("aucune couche de sécurité n'a bloqué", answer.blocked_at, None)

    print("\nRédaction servie")
    answer = answer_question("délai d'un échange standard ?", "support", settings=settings,
                             writer=_SufficientWriter())
    check("la réponse est servie", answer.code, "ok")
    check("toutes les couches sont franchies", answer.blocked_at, 0)
    served = rag_client_view(answer)
    check("le client reçoit la réponse", served["payload"]["answer"], "Réponse scriptée.")
    check("et ses sources", len(served["payload"]["sources"]), 1)
    check("chaque source est citable", sorted(served["payload"]["sources"][0]),
          ["date", "doc_key", "reference", "titre", "version"])
    # E1 : la citation est construite en Python depuis les métadonnées. Le test T1 exige une
    # référence non vide sur une procédure SAV, qui n'a pas de référence produit — d'où le
    # repli sur `doc_key`, qui identifie le document exactement.
    check("la référence n'est jamais vide",
          bool(served["payload"]["sources"][0]["reference"].strip()), True)

    print("\nRéférence nue — l'énoncé complété pour le rédacteur, la recherche intacte")
    # La forme de RAG-03 et RAG-05 : une référence et rien d'autre. Le retrieval était
    # parfait et la barrière 2 refusait quand même, faute d'énoncé à satisfaire.
    check("une référence nue devient une question",
          question_for_writer("REF-8842"),
          "Quelles sont les caractéristiques de la référence REF-8842 ?")
    # L'ancrage est la moitié qui compte : une règle qui déborderait toucherait les 22
    # questions couvertes, dont RAG-18 et RAG-20 que la barrière 2 doit continuer de refuser.
    check("une référence dans une phrase n'est pas touchée",
          question_for_writer("que vaut REF-8842 ?"), "que vaut REF-8842 ?")
    scribe = _CapturingWriter()
    answer = answer_question("REF-8842", "commercial", settings=settings, writer=scribe)
    check("elle ne produit plus contexte_insuffisant", answer.code, "ok")
    check("le rédacteur a reçu l'énoncé complété", scribe.asked,
          ["Quelles sont les caractéristiques de la référence REF-8842 ?"])
    # Et la recherche, elle, a bien vu la référence nue : c'est ce que BM25 attrape, et
    # c'est ce qui met la bonne édition au premier rang.
    check("la recherche a retrouvé la bonne référence",
          rag_client_view(answer)["payload"]["sources"][0]["reference"], "REF-8842")

    print("\nFilet de dernier recours")
    answer = answer_question("délai d'un échange standard ?", "support", settings=settings,
                             writer=_ExplodingWriter())
    check("la panne devient une erreur d'exécution", answer.code, "erreur_execution")
    check("le message du SDK reste dans la cause", MODEL_TEXT in answer.cause, True)
    check("le client lit une indisponibilité", rag_client_view(answer)["message"],
          RAG_CLIENT_MESSAGES["erreur_execution"])
    check("et rien de la pile", rag_client_view(answer)["payload"],
          {"code": "erreur_execution"})

    print("\nPérimètre documentaire, relu à travers la chaîne de réponse")
    for profile, expected in GOLDEN_COUNTS.items():
        view = handle("list_sources", {}, profile, settings)
        check(f"{profile} atteint {expected} éditions courantes",
              len(view["payload"]["sources"]), expected)
    # Une collection fermée demandée explicitement : on refuse, on ne rogne pas en silence.
    view = handle("list_sources", {"collections": ["note_interne"]}, "dev", settings)
    check("une collection fermée demandée est refusée", view["status"], "refused")
    check("la collection en cause va au journal", lines()[-1]["forbidden"], ["note_interne"])
    check("jamais au client", "note_interne" in json.dumps(view), False)

    print("\nJournal — une ligne par appel, dans l'ordre")
    before = len(lines())
    for tool, arguments in (("search_docs", {"query": "REF-8842"}),
                            ("get_document", {"doc_id": CLOSED_NOTE}),
                            ("list_sources", {})):
        handle(tool, arguments, "support", settings)
    written = lines()[before:]
    check("trois appels, trois lignes", len(written), 3)
    check("dans l'ordre d'appel", [entry["tool"] for entry in written],
          ["search_docs", "get_document", "list_sources"])
    check("un refus et deux servis", [entry["decision"] for entry in written],
          ["allowed", "denied", "allowed"])
    check("la latence est journalisée", all(entry["latency_ms"] >= 0 for entry in written
                                            if entry["decision"] == "allowed"), True)
    check("le journal se relit par tail()", len(journal.tail(3, settings)), 3)

    return verdict()


if __name__ == "__main__":
    sys.exit(main())
