"""Le périmètre documentaire d'un profil, sous ses deux formes exécutables.

La matrice d'accès ferme le corpus à **deux grains** : la collection (``doc_type``) et,
pour les seules notes internes, le thème. Ce module traduit ce périmètre — déjà résolu par
``packages/rag_machines/access_rag.py`` — en ce que les deux étages de recherche savent
consommer : un ``where`` pour Chroma, un prédicat pour BM25.

**Un objet, deux rendus, une seule règle.** La règle s'applique deux fois, et la
configuration hybride fusionne les deux listes par RRF : une note qui fuirait par le seul
étage lexical entrerait dans la fusion et sortirait au résultat. Écrite à deux endroits,
une divergence ne se verrait que par une réponse fausse. Écrite ici, elle se contrôle
(``check_perimeter.py``, contrôle de parité).

Ce module ne lit pas la matrice et n'importe pas ``packages/access.py`` : il reçoit un
périmètre déjà résolu. C'est ce qui laisse ``retrieval/`` « paramétré, jamais câblé ».

La forme du ``where`` n'est pas inventée ici : elle est arrêtée depuis la conception, dans
``docs/conception/3-exposition-mcp-et-matrice-d-acces/Q3.md`` §8, où elle est explicitement
« documentée, pas exécutée » — ``chromadb`` n'était pas installé. Ce module l'exécute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: La seule collection dont le thème qualifie les éditions. Les trois autres n'ont pas de
#: clé ``theme`` du tout — c'est la conduite tranchée à l'ingestion (``Q3`` §8), et c'est
#: elle qui oblige à une disjonction plutôt qu'à une conjonction.
NOTES = "note_interne"


@dataclass(frozen=True)
class Perimeter:
    """Ce qu'un profil a le droit d'atteindre dans le corpus.

    ``doc_types`` vient de ``collections`` dans la matrice, ``themes`` de ``themes_notes``.
    Un périmètre dont aucune branche n'est constructible ne se représente pas ici : c'est un
    refus, et il est prononcé en amont (cf. ``access_rag.perimeter_for``).
    """

    doc_types: frozenset[str]
    themes: frozenset[str]

    def _branches(self) -> list[dict[str, Any]]:
        """Les branches du périmètre, dans l'ordre : les collections ordinaires, puis les
        notes qualifiées par leur thème.

        C'est ici que se joue le piège de la clé absente. Une conjonction — ``doc_type``
        ET ``theme`` dans le même ``where`` — ne remonterait **que des notes** : les 320
        autres éditions n'ont pas de clé ``theme``, et Chroma évalue à faux toute
        comparaison sur une clé absente. Elles disparaîtraient sans qu'aucune erreur ne le
        signale. D'où la disjonction : la branche des collections ordinaires ne mentionne
        jamais ``theme``.

        Une forme plus courte existe et tient en une ligne — fermer les thèmes interdits par
        ``{"theme": {"$nin": [...]}}``, que Chroma compile en un ``NOT IN`` que les éditions
        sans clé traversent. Elle est **écartée** : elle demande d'énumérer ce qui est fermé
        là où la matrice n'énumère que ce qui est ouvert. Un thème ajouté demain y serait
        donc ouvert par défaut — l'inverse de la liste blanche que le dépôt tient partout
        ailleurs.
        """
        branches: list[dict[str, Any]] = []
        others = sorted(self.doc_types - {NOTES})
        if others:
            branches.append({"doc_type": {"$in": others}})
        if NOTES in self.doc_types and self.themes:
            branches.append({"$and": [{"doc_type": {"$eq": NOTES}},
                                      {"theme": {"$in": sorted(self.themes)}}]})
        return branches

    def where(self, version_filter: bool) -> dict[str, Any]:
        """La clause ``where`` de Chroma pour ce périmètre.

        ``is_current`` reste une clause **à part**, en ``$and`` avec le périmètre : le
        filtre de version fixe le dénominateur de la mesure E6 à 350 éditions (``Q1`` §5),
        le filtre de gouvernance dépend du profil. Les fondre l'un dans l'autre rendrait
        impossible de dire lequel a écarté quoi.

        Deux contraintes de Chroma, que la forme respecte par construction : ``$and`` et
        ``$or`` veulent au moins deux opérandes — le profil `dev`, qui n'a que des
        collections ordinaires, produit une branche unique qu'il ne faut **pas** envelopper
        —, et ``$in`` n'accepte pas de liste vide.
        """
        branches = self._branches()
        if not branches:
            # Un ``where`` vide ne filtre rien : ce profil lirait le corpus entier. C'est la
            # panne inverse de celle qu'on corrige, et la plus grave des deux. L'appelant
            # devait refuser avant d'arriver ici — s'il ne l'a pas fait, on s'arrête.
            raise RuntimeError(
                "périmètre vide : aucune collection ouverte à ce profil. Le refus se "
                "prononce dans access_rag.perimeter_for(), avant toute requête à l'index."
            )
        perimeter = branches[0] if len(branches) == 1 else {"$or": branches}
        if not version_filter:
            return perimeter
        return {"$and": [{"is_current": {"$eq": True}}, perimeter]}

    def allows(self, doc_type: str, theme: str | None) -> bool:
        """La même règle, en Python : pour BM25, qui n'a pas de moteur de requête.

        Sert aussi de contrôle de parité avec ``where()``, et servira à ``get_document`` au
        chantier 3 : le ``doc_key`` porte la collection et le thème, décidables avant tout
        accès à l'index.
        """
        if doc_type not in self.doc_types:
            return False
        if doc_type != NOTES:
            return True
        return theme is not None and theme in self.themes
