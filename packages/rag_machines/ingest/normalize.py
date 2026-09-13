"""Normalisation du corpus hétérogène en une structure unique : l'édition.

Le corpus vit dans quatre formats (PDF techniques, PDF de notices, HTML de
procédures SAV, Markdown de notes internes) et porte ses métadonnées de trois
façons différentes : dans le texte pour les PDF, dans les balises ``<meta>`` pour
le HTML, dans le frontmatter YAML pour les notes. Ce module ramène les quatre à
une même dataclass :class:`Edition`.

Deux décisions de conception sont matérialisées ici :

* **le texte indexé n'est pas le texte du fichier** — les blocs « Accessoires et
  produits associés » citent des références qui ne sont pas le sujet du document
  et sortent de l'index (ils restent dans ``full_text``, pour l'affichage) ;
* **pas de chunker** — un document tient dans la fenêtre du modèle d'embeddings
  (799 caractères au plus, soit moins de la moitié des 512 tokens), donc une
  édition = un chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

#: Le répertoire porte le type documentaire ; les PDF n'ont aucune métadonnée
#: structurée d'où le déduire. Les valeurs sont celles du contrat DSI.
#: Les deux textes indexables. « clean » est le contrat ; « raw » n'existe que pour
#: mesurer ce que le nettoyage apporte (eval/protocole-mesure.md, axe 2).
TextProfile = Literal["clean", "raw"]

DOC_TYPE_BY_FOLDER = {
    "fiches": "fiche_technique",
    "notices": "notice",
    "sav": "procedure_sav",
    "notes": "note_interne",
}

_RE_REFERENCE = re.compile(r"Référence produit\s*:\s*(REF-\d{4})")
_RE_VERSION = re.compile(r"Version\s*:\s*(\d+\.\d+)")
_RE_DATE = re.compile(r"Date\s*:\s*(\d{4}-\d{2}-\d{2})")
_RE_PDF_TITLE = re.compile(r"^(?:FICHE TECHNIQUE|NOTICE D'INSTALLATION)\s*-\s*")
#: Bloc de liens sortants des fiches : retiré du texte indexé, conservé à l'affichage.
_RE_OUTBOUND_LINKS = re.compile(r"^Accessoires et produits associés\s*:.*$", re.MULTILINE)
#: Les deux tournures par lesquelles une procédure SAV cite une référence en exemple.
_RE_EXAMPLE_LINE = re.compile(
    r"^.*(?:exemple traité sur la référence|référence exacte \(ex\.).*$", re.MULTILINE
)
_RE_REFERENCE_TOKEN = re.compile(r"REF-\d{4}")
#: Suffixe de version dans un nom de fichier (`REF-8842-v2.1` → `REF-8842`).
_RE_VERSION_SUFFIX = re.compile(r"-v(\d+\.\d+)$")
#: Nom d'une note : `note-AAAA-MM-JJ-<theme>-NN`.
_RE_NOTE_FILENAME = re.compile(r"^note-\d{4}-\d{2}-\d{2}-(?P<theme>.+)-\d+$")


class NormalizationError(Exception):
    """Le fichier n'a pas pu être ramené à une édition exploitable."""


@dataclass(frozen=True)
class Edition:
    """Une version d'un document — l'unité indexée.

    ``indexed_text`` est ce qui part dans l'index (liens sortants retirés) ;
    ``full_text`` est ce que ``get_document`` rendra plus tard. Le texte intégral
    n'est pas stocké dans l'index : il se relit depuis ``url``.

    Les noms d'attributs sont en anglais ; les clés de métadonnées écrites dans
    l'index suivent le contrat et restent celles du dossier de conception. La
    correspondance se fait dans ``registry.build_metadata()``.
    """

    edition_id: str
    doc_key: str
    title: str
    version: str
    date: str
    doc_type: str
    url: str
    indexed_text: str
    full_text: str
    reference: str | None = None
    theme: str | None = None
    #: Version lue dans le nom du fichier — sert au contrôle de cohérence.
    filename_version: str | None = None

    @property
    def char_count(self) -> int:
        return len(self.indexed_text)

    def text_for(self, profile: TextProfile) -> str:
        """Le texte à indexer selon le profil. Un seul endroit décide, pour que
        ``n_caracteres`` ne puisse pas décrire un autre texte que celui qui est indexé."""
        return self.indexed_text if profile == "clean" else self.full_text


def _identifiers(path: Path, root: Path) -> tuple[str, str, str | None]:
    """Rend ``(edition_id, doc_key, version_du_nom_de_fichier)``.

    ``edition_id`` est le chemin relatif au corpus, privé de son extension ;
    ``doc_key`` est ce même identifiant privé de son suffixe de version. Les
    notes n'en portent pas : leur ``doc_key`` est égal à leur ``edition_id``.
    """
    relative = path.relative_to(root).with_suffix("")
    edition_id = relative.as_posix()
    match = _RE_VERSION_SUFFIX.search(edition_id)
    if match is None:
        return edition_id, edition_id, None
    return edition_id, edition_id[: match.start()], match.group(1)


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _read_pdf(path: Path, root: Path, doc_type: str) -> Edition:
    """Fiches techniques et notices : tout est dans le texte extrait.

    La fiche met référence, version et date sur des lignes séparées, la notice
    les met sur une seule — d'où des expressions régulières par champ, appliquées
    au texte entier, plutôt qu'un découpage ligne à ligne.
    """
    full_text = _pdf_text(path).strip()
    if not full_text:
        raise NormalizationError("aucun texte extractible du PDF")

    version = _RE_VERSION.search(full_text)
    date = _RE_DATE.search(full_text)
    reference = _RE_REFERENCE.search(full_text)
    if version is None or date is None:
        raise NormalizationError("version ou date introuvable dans le texte du PDF")

    first_line = full_text.splitlines()[0].strip()
    title = _RE_PDF_TITLE.sub("", first_line).strip()
    if not title:
        raise NormalizationError("titre introuvable en première ligne du PDF")

    edition_id, doc_key, filename_version = _identifiers(path, root)
    return Edition(
        edition_id=edition_id,
        doc_key=doc_key,
        title=title,
        version=version.group(1),
        date=date.group(1),
        doc_type=doc_type,
        url=path.relative_to(root.parent.parent).as_posix(),
        indexed_text=_strip_foreign_references(full_text),
        full_text=full_text,
        reference=reference.group(1) if reference else None,
        filename_version=filename_version,
    )


def _read_html(path: Path, root: Path, doc_type: str) -> Edition:
    """Procédures SAV : métadonnées dans les ``<meta>``, titre dans le ``<h1>``."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    def meta(name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        content = tag.get("content") if tag else None
        return content.strip() if isinstance(content, str) and content.strip() else None

    version, date = meta("version"), meta("date")
    if version is None or date is None:
        raise NormalizationError("balise <meta> version ou date manquante")

    # Q1 §1 prescrit `<title>` ; `<h1>` porte la même chaîne sur les 90 fichiers, mais
    # c'est la balise du dossier qui fait foi.
    title_tag = soup.find("title") or soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        raise NormalizationError("titre introuvable : ni <title> ni <h1>")

    body = soup.body or soup
    full_text = _condense(body.get_text(separator="\n"))
    edition_id, doc_key, filename_version = _identifiers(path, root)
    return Edition(
        edition_id=edition_id,
        doc_key=doc_key,
        title=title,
        version=version,
        date=date,
        doc_type=_resolve_doc_type(meta("type"), doc_type),
        url=path.relative_to(root.parent.parent).as_posix(),
        indexed_text=_strip_foreign_references(full_text),
        full_text=full_text,
        filename_version=filename_version,
    )


def _read_markdown(path: Path, root: Path, doc_type: str) -> Edition:
    """Notes internes : frontmatter YAML, thème déduit du nom de fichier."""
    raw = path.read_text(encoding="utf-8")
    front_matter, body = _split_front_matter(raw)
    if front_matter is None:
        raise NormalizationError("frontmatter YAML absent ou malformé")

    title = str(front_matter.get("titre", "")).strip()
    version = str(front_matter.get("version", "")).strip()
    date = str(front_matter.get("date", "")).strip()
    if not (title and version and date):
        raise NormalizationError("frontmatter incomplet : titre, version ou date manquant")

    edition_id, doc_key, filename_version = _identifiers(path, root)
    match = _RE_NOTE_FILENAME.match(path.stem)
    full_text = _condense(body)
    return Edition(
        edition_id=edition_id,
        doc_key=doc_key,
        title=title,
        version=version,
        date=date,
        doc_type=_resolve_doc_type(front_matter.get("type"), doc_type),
        url=path.relative_to(root.parent.parent).as_posix(),
        indexed_text=_strip_foreign_references(full_text),
        full_text=full_text,
        theme=match.group("theme") if match else None,
        filename_version=filename_version,
    )


def _resolve_doc_type(declared: object, doc_type: str) -> str:
    """Le dossier fait foi ; un type déclaré divergent est une erreur, pas un choix.

    Les HTML et les Markdown portent leur type documentaire (``<meta name="type">``,
    frontmatter ``type:``) ; les PDF n'ont rien de tel, d'où l'arbitrage sur le
    dossier, seul indice commun aux quatre formats.

    Laisser la valeur du fichier l'emporter serait pire qu'un détail de style :
    ``doc_type`` est le champ sur lequel la matrice d'accès filtre. Un
    ``content="fiche_technique"`` égaré dans un fichier de ``sav/`` reclasserait ce
    document dans une autre classe d'accès sans que rien ne le signale. On refuse
    donc le fichier plutôt que d'arbitrer entre deux sources qui se contredisent.
    """
    if declared is None:
        return doc_type
    declared_type = str(declared).strip()
    if declared_type and declared_type != doc_type:
        raise NormalizationError(
            f"type documentaire contradictoire : le fichier déclare "
            f"« {declared_type} », son dossier impose « {doc_type} »"
        )
    return doc_type


def _split_front_matter(raw: str) -> tuple[dict | None, str]:
    if not raw.startswith("---"):
        return None, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None, raw
    try:
        front_matter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, raw
    return (front_matter if isinstance(front_matter, dict) else None), parts[2]


def _strip_foreign_references(text: str) -> str:
    """Retire du texte indexé les références qui ne sont pas le sujet du document.

    Deux endroits en portent, et aucun ne décrit le document qui les héberge :

    * la ligne « Accessoires et produits associés » des fiches, qui cite deux autres
      produits — elle sort entièrement ;
    * la référence citée **en exemple** par les 90 procédures SAV, qui sont génériques
      (« applicable à tout le catalogue »). Preuve qu'elle n'identifie rien : elle change
      entre la v1.0 et la v2.0 d'une même procédure. Seul le jeton ``REF-XXXX`` est retiré,
      la phrase reste — c'est la règle du dossier, et la reproduire à l'identique est ce qui
      permet de retrouver ses chiffres.

    Sans ce retrait, une référence est portée par jusqu'à sept éditions au lieu de trois :
    pour BM25 c'est un terme à IDF très élevé, et la fiche de ``REF-8842`` remonterait sur
    une recherche ``REF-4581`` aussi haut que la fiche de ``REF-4581``. Le dossier chiffre
    le nettoyage à **+5 en Hit@3**.

    Rien n'est perdu : ``full_text`` conserve le texte entier, que rendront l'extrait cité
    et ``get_document``.
    """
    text = _RE_OUTBOUND_LINKS.sub("", text)
    text = _RE_EXAMPLE_LINE.sub(lambda match: _RE_REFERENCE_TOKEN.sub("", match.group(0)), text)
    return _condense(text)


def _condense(text: str) -> str:
    """Supprime les lignes vides et les espaces de bord, sans toucher au reste."""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


_READERS = {".pdf": _read_pdf, ".html": _read_html, ".md": _read_markdown}


def normalize(path: Path, root: Path) -> Edition:
    """Ramène un fichier du corpus à une édition. Lève :class:`NormalizationError`."""
    folder = path.relative_to(root).parts[0]
    doc_type = DOC_TYPE_BY_FOLDER.get(folder)
    if doc_type is None:
        raise NormalizationError(f"dossier inconnu du corpus : {folder}")
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise NormalizationError(f"format non pris en charge : {path.suffix}")
    return reader(path, root, doc_type)


def corpus_files(root: Path) -> list[Path]:
    """Les fichiers exploitables du corpus, dans un ordre stable."""
    return sorted(
        path
        for folder in DOC_TYPE_BY_FOLDER
        for path in (root / folder).glob("*")
        if path.suffix.lower() in _READERS
    )


def classify(doc_id: str) -> tuple[str, str | None] | None:
    """Rend ``(doc_type, theme)`` d'un ``edition_id`` ou d'un ``doc_key``, sans lire l'index.

    Les deux identifiants sont des chemins relatifs au corpus, privés d'extension —
    ``fiches/REF-1024-v2.1``, ``notes/note-2024-01-02-reunion-achat-32``. Le dossier porte
    donc la collection, et le nom de fichier porte le thème quand il s'agit d'une note.
    C'est ce que ``Q3`` §8 appelle « décidable sur le seul argument » : ``get_document`` doit
    pouvoir refuser **avant tout accès à l'index**, sans quoi la fermeture des notes serait
    contournable par un simple chemin de fichier.

    Rend ``None`` quand l'identifiant ne désigne aucune collection connue — un dossier
    inventé, ou un identifiant sans dossier du tout. C'est un ``introuvable``, pas un refus :
    l'appelant tranche.
    """
    head, _, tail = doc_id.strip().strip("/").partition("/")
    if not tail:
        return None
    doc_type = DOC_TYPE_BY_FOLDER.get(head)
    if doc_type is None:
        return None
    if doc_type != "note_interne":
        return doc_type, None
    match = _RE_NOTE_FILENAME.match(tail.rsplit("/", 1)[-1])
    return doc_type, (match.group("theme") if match else None)
