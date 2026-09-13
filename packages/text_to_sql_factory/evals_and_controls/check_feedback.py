"""Contrôles de la réponse structurée et du journal, côté Text-to-SQL.

**Aucun appel de modèle.** Tout ce qui est vérifié ici est déterministe par construction :
c'est même l'objet du contrôle. Le journal est écrit dans un répertoire temporaire, jamais
dans celui du dépôt.

Ce que ce script établit, et pourquoi chacun de ces sept points mérite un contrôle :

1. **Forme** — la vue client rend exactement les trois champs du contrat DSI. Une quatrième
   clé qui apparaîtrait un jour ne partirait pas au client sans que ce contrôle le dise.
2. **Étanchéité** — la cause technique, la trace d'exception et les colonnes refusées ne se
   retrouvent **nulle part** dans le JSON servi. La recherche porte sur la sous-chaîne, pas
   sur l'absence de clé : une fuite par concaténation serait invisible à un contrôle de clés.
3. **Déterminisme** — quatre appels identiques rendent quatre réponses identiques. C'est le
   défaut d'origine : le texte du refus était écrit par le modèle, donc il variait.
4. **Complétude** — tout code a sa phrase. Sans ce contrôle, un code ajouté demain
   tomberait silencieusement sur le repli « service indisponible ».
5. **Filet** — une panne à l'intérieur d'un tool ne traverse pas le handler. C'est ce qui
   rend la fuite de trace *impossible* plutôt que seulement improbable.
6. **Journal** — une ligne par appel, dans l'ordre, avec ce qu'il faut pour déboguer : le
   code, l'étage qui a tranché, la requête, la cause. Et la cause y est **alors qu'elle est
   absente de la vue client** : les deux moitiés du même appel, vérifiées ensemble.
7. **Garde-fou de lecture** — le journal est lisible par un seul profil, et sa lecture est
   elle-même journalisée.

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
from packages.text_to_sql_factory import handler
from packages.text_to_sql_factory.contract import ReadContract
from packages.text_to_sql_factory.generator import Generation, SqlGenerator
from packages.text_to_sql_factory.handler import handle, read_feedback
from packages.text_to_sql_factory.structured_answer import (
    CLIENT_MESSAGES,
    DB_STATUS_BY_CODE,
    build_db_structured_answer,
    client_view,
)
from packages.text_to_sql_factory.tools import ask_database

#: Le texte que le modèle « écrit » dans la doublure ci-dessous. Il est reconnaissable
#: exprès : on le cherche ensuite dans la vue client (il ne doit pas y être) et dans le
#: journal (il doit y être). Une chaîne banale ne prouverait rien.
MODEL_TEXT = "TEXTE-DU-MODELE-A-NE-PAS-AFFICHER"

#: Les trois champs du contrat d'intégration, et eux seuls.
DSI_KEYS = {"status", "payload", "message"}


class _RefusingGenerator(SqlGenerator):
    """**Doublure de test.** Un générateur qui refuse en rédigeant, comme le vrai le fait.

    C'est le cas qui motive tout ce chantier : sur ``ecriture_refusee`` et ``hors_schema``,
    ``tools.py`` prenait la phrase du modèle pour énoncé. Cette doublure la rend
    reconnaissable pour qu'on puisse vérifier où elle atterrit — et où elle n'atterrit pas.
    """

    def __init__(self, motive: str) -> None:
        super().__init__("", "", "scripté")
        self._motive = motive

    def generate(self, question: str, contract: ReadContract,  # type: ignore[override]
                 axes: tuple[str, ...] = (),
                 rejected: tuple[str, str] | None = None) -> Generation:
        return Generation("refus", reason=MODEL_TEXT, motive=self._motive)


class _ExplodingGenerator(SqlGenerator):
    """**Doublure de test.** Un générateur qui lève, comme le ferait un SDK injoignable."""

    def generate(self, question: str, contract: ReadContract,  # type: ignore[override]
                 axes: tuple[str, ...] = (),
                 rejected: tuple[str, str] | None = None) -> Generation:
        raise RuntimeError(MODEL_TEXT)


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

    database = Path(base_settings.sorabel_db)
    print("Base :", database)
    if not database.exists():
        print("\nBase absente : les contrôles sont sans objet. Lancer `make seed`.")
        return 1

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

    # ------------------------------------------------------------- 1. et 4. la table
    print("\nComplétude de la table des phrases")
    orphans = sorted(code for code in DB_STATUS_BY_CODE if code not in CLIENT_MESSAGES)
    check("tout code a sa phrase figée — jamais de repli silencieux", orphans, [])
    check("les cinq statuts du contrat DSI, et pas un sixième",
          sorted(set(DB_STATUS_BY_CODE.values())),
          ["clarification", "error", "ok", "refused"])
    check("un statut autre que `ok` a toujours un message",
          [code for code, status in DB_STATUS_BY_CODE.items()
           if status != "ok" and not CLIENT_MESSAGES.get(code)], [])

    print("\nForme de la vue client, code par code")
    for code in DB_STATUS_BY_CODE:
        # Une charge utile volontairement trop riche : on vérifie que la liste blanche
        # coupe, et non que le tool a bien fait de ne rien mettre.
        answer = build_db_structured_answer(
            code, cause=MODEL_TEXT, stack=MODEL_TEXT, forbidden=("produits.marge_pct",),
            etage=3, sql="SELECT 1", rows=[[1]], columns=["x"], n_rows=1, latency_ms=4.2,
            axes=["axe"],
        )
        view = client_view(answer)
        check(f"{code} — trois champs, ceux du DSI", set(view) == DSI_KEYS, True)
        check(f"{code} — statut", view["status"], DB_STATUS_BY_CODE[code])
        check(f"{code} — phrase figée", view["message"], CLIENT_MESSAGES[code])
        served = json.dumps(view, ensure_ascii=False)
        check(f"{code} — ni cause ni trace ni colonne", MODEL_TEXT in served, False)
        check(f"{code} — aucune colonne nommée", "marge_pct" in served, False)
        check(f"{code} — le diagnostic ne part pas",
              "n_rows" in served or "latency_ms" in served, False)
        if DB_STATUS_BY_CODE[code] in ("refused", "error"):
            check(f"{code} — un refus ne porte que son code", view["payload"], {"code": code})

    # ------------------------------------------------------- 2., 3. et 6. bout en bout
    print("\nLe texte du modèle : au journal, jamais à l'écran")
    answer = ask_database("supprime les commandes", "commercial", settings,
                          _RefusingGenerator("ecriture"))
    served = json.dumps(client_view(answer), ensure_ascii=False)
    check("le refus d'écriture est bien un refus", answer.code, "ecriture_refusee")
    check("la phrase du modèle est la cause", answer.cause, MODEL_TEXT)
    check("elle n'atteint pas le client", MODEL_TEXT in served, False)
    check("et le client lit la phrase figée",
          client_view(answer)["message"], CLIENT_MESSAGES["ecriture_refusee"])

    print("\nDéterminisme : quatre appels, une seule réponse")
    # Sur le refus rédigé par le modèle — le cas qui variait. La doublure rend un texte
    # différent à chaque construction ? Non : elle rend toujours le même. Ce qui est
    # vérifié ici, c'est que ce texte ne passe plus dans la réponse, donc qu'aucune
    # variation du modèle ne peut y passer non plus.
    quatre = {json.dumps(client_view(ask_database("supprime les commandes", "commercial",
                                                  settings, _RefusingGenerator("ecriture"))),
                         ensure_ascii=False, sort_keys=True)
              for _ in range(4)}
    check("quatre refus rédigés → une seule réponse", len(quatre), 1)
    determinisme = settings.model_copy(
        update={"gateway_journal": journal_file.parent / "determinisme.jsonl"})
    for tool, arguments, profile in (("get_schema", {}, "support"),
                                     ("check_stock", {"reference": "pas-une-ref"}, "support"),
                                     ("order_status", {"order_id": "CMD-2026-0042"}, "support")):
        rendus = {json.dumps(handle(tool, arguments, profile, determinisme),
                             ensure_ascii=False, sort_keys=True) for _ in range(4)}
        check(f"{tool} — quatre appels, une seule réponse", len(rendus), 1)

    print("\nLe filet : une panne ne traverse pas le handler")
    before = len(lines())
    original = handler.SQL_TOOLS["get_schema"]
    try:
        # On remplace un tool par un tool qui explose. C'est le seul moyen d'exercer le
        # `except Exception` du handler : la bibliothèque, elle, attrape déjà ses propres
        # pannes — et c'est bien ce qui *n'est pas* garanti qu'on veut vérifier.
        handler.SQL_TOOLS["get_schema"] = (
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(MODEL_TEXT)),
            (),
        )
        view = handle("get_schema", {}, "admin", settings)
    finally:
        handler.SQL_TOOLS["get_schema"] = original
    check("aucune exception ne sort", view["status"], "error")
    check("le client ne lit rien de la pile", MODEL_TEXT in json.dumps(view), False)
    check("mais le journal la porte entière",
          MODEL_TEXT in lines()[-1]["stack"] and "Traceback" in lines()[-1]["stack"], True)
    check("et l'appel a bien produit une ligne", len(lines()) - before, 1)

    print("\nJournal : une ligne par appel, dans l'ordre")
    fresh = settings.model_copy(update={"gateway_journal": journal_file.parent / "ordre.jsonl"})
    calls: tuple[tuple[str, dict, str], ...] = (
        ("check_stock", {"reference": "REF-8842"}, "support"),      # ok
        ("get_schema", {}, "support"),                              # tool_interdit, étage 2
        ("check_stock", {"reference": "pas-une-ref"}, "support"),    # argument malformé
        ("order_status", {"order_id": "CMD-2026-0042"}, "support"),  # aucune_ligne
    )
    views = [handle(tool, arguments, profile, fresh) for tool, arguments, profile in calls]
    entries = journal.tail(100, fresh)
    check("autant de lignes que d'appels", len(entries), len(calls))
    check("dans l'ordre des appels",
          [entry["tool"] for entry in entries], [tool for tool, _, _ in calls])
    check("les statuts servis et journalisés concordent",
          [entry["status"] for entry in entries], [view["status"] for view in views])
    check("les codes attendus",
          [entry["code"] for entry in entries],
          ["ok", "tool_interdit", "erreur_execution", "aucune_ligne"])
    check("l'étage n'est posé que sur la décision d'accès",
          [entry["etage"] for entry in entries], [None, 2, None, None])
    check("blocked_at décrit le point d'arrêt",
          [entry["blocked_at"] for entry in entries], [0, 2, None, 0])
    check("la requête exécutée est tracée", entries[0]["sql"].startswith("SELECT"), True)
    check("le diagnostic est au journal", entries[0]["n_rows"], 3)
    check("la latence aussi", entries[0]["latency_ms"] > 0, True)
    check("la décision, en trois valeurs",
          [entry["decision"] for entry in entries],
          ["allowed", "denied", "error", "allowed"])
    check("les arguments de l'appel sont tracés",
          entries[0]["arguments"], {"reference": "REF-8842"})
    check("ce que l'utilisateur a lu est conservé à côté",
          entries[1]["client_message"], CLIENT_MESSAGES["tool_interdit"])
    check("un refus de tool nomme sa cause au journal",
          "n'a pas le tool" in entries[1]["cause"], True)

    print("\nLes colonnes refusées : nommées au journal, jamais au client")
    marge = settings.model_copy(update={"gateway_journal": journal_file.parent / "marge.jsonl"})
    view = handle("ask_database", {"question": "la marge par produit"}, "support", marge)
    entry = journal.tail(1, marge)[0]
    check("le support n'a pas la marge", view["payload"]["code"], "perimetre_interdit")
    check("le client ne voit aucune colonne", "marge" in json.dumps(view), False)
    check("le journal nomme la cause", bool(entry["cause"]), True)
    check("l'étage 3 a tranché", entry["etage"], 3)

    print("\nLecture du journal : un seul profil")
    refused = read_feedback("support", 10, marge)
    check("le support ne lit pas le journal", refused["status"], "refused")
    check("et n'en apprend rien", refused["payload"], {"code": "tool_interdit"})
    granted = read_feedback("admin", 10, marge)
    check("l'admin le lit", granted["status"], "ok")
    check("les entrées sont rendues entières",
          "cause" in granted["payload"]["entries"][0], True)
    # Les entrées vont de la plus ancienne à la plus récente : le refus de périmètre, puis
    # la tentative de lecture refusée, puis la lecture accordée. Une revue de conformité
    # veut précisément voir les deux dernières — qui a cherché à lire le journal, et qui a
    # pu. Le journal se journalise donc lui-même.
    check("la lecture du journal est journalisée, refusée comme accordée",
          [entry["code"] for entry in journal.tail(3, marge)],
          ["perimetre_interdit", "tool_interdit", "ok"])

    print("\nAppels hors catalogue")
    view = handle("drop_everything", {}, "admin", marge)
    check("un tool inconnu n'est pas un refus de droits", view["payload"]["code"],
          "erreur_execution")
    check("et ne dit pas ce qu'il ne connaît pas", "drop_everything" in json.dumps(view),
          False)
    view = handle("check_stock", {}, "support", marge)
    check("argument manquant", view["status"], "error")
    check("le format attendu est dit sans nommer d'interne",
          view["message"], CLIENT_MESSAGES["argument_malforme"])

    print("\nPanne du fournisseur d'inférence")
    panne = settings.model_copy(update={"gateway_journal": journal_file.parent / "panne.jsonl"})
    answer = ask_database("combien de produits ?", "commercial", panne,
                          _ExplodingGenerator("", "", ""))
    check("la panne devient une erreur d'exécution", answer.code, "erreur_execution")
    check("le message du SDK reste dans la cause", MODEL_TEXT in answer.cause, True)
    check("le client lit une indisponibilité",
          client_view(answer)["message"], CLIENT_MESSAGES["erreur_execution"])

    return verdict()


if __name__ == "__main__":
    sys.exit(main())
