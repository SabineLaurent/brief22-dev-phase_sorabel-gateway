# Livrables d'architecture — Sorabel Data Gateway

Les cinq pièces d'architecture demandées par le brief, à jour de
[`synthese-conception.md`](../synthese-conception.md) et
[`audit-coherence.md`](../audit-coherence.md) — **pas** des premiers jets de
`docs/archives/`, qui restent des témoins historiques.

| # | Livrable demandé | Fichiers | Source qui le spécifie |
|---|---|---|---|
| 1 | Schéma de flux complet | [`01-flux-complet.md`](01-flux-complet.md) (mermaid) + [`01-flux-complet.drawio`](01-flux-complet.drawio) | `synthese-conception.md` « Reste à produire » |
| 2 | Modèle de chunk et métadonnées | [`02-modele-chunk.md`](02-modele-chunk.md) (markdown + json) | [`1-rag-avance/Q2.md`](../1-rag-avance/Q2.md) §3 |
| 3 | Catalogue des tools MCP | [`03-catalogue-tools.drawio`](03-catalogue-tools.drawio) (tableau) + [`03-catalogue-tools.md`](03-catalogue-tools.md) | [`3-…/Q1.md`](../3-exposition-mcp-et-matrice-d-acces/Q1.md), [`Q2.md`](../3-exposition-mcp-et-matrice-d-acces/Q2.md), [`Q4.md`](../3-exposition-mcp-et-matrice-d-acces/Q4.md), [`Q5.md`](../3-exposition-mcp-et-matrice-d-acces/Q5.md) |
| 4 | Chemin Text-to-SQL | [`04-chemin-text-to-sql.drawio`](04-chemin-text-to-sql.drawio) (V3) + [`04-chemin-text-to-sql.md`](04-chemin-text-to-sql.md) (séquence mermaid) | [`2-text-to-sql/`](../2-text-to-sql/) `Q1` → `Q5` |
| 5 | Matrice d'accès | [`05-matrice-acces.drawio`](05-matrice-acces.drawio) (tableau) + [`matrice.yaml`](matrice.yaml) | [`3-…/Q3.md`](../3-exposition-mcp-et-matrice-d-acces/Q3.md) §3, §9 |

## Comment lire ce dossier

Commencer par [`01-flux-complet.md`](01-flux-complet.md) : c'est le synoptique, il renvoie
vers tout le reste. Le serveur MCP y est représenté comme une **barrière** — les clients
au-dessus, les sources en dessous, la mécanique de régulation à l'intérieur.

`matrice.yaml` est la pièce pivot : les fichiers 3, 4 et 5 s'y réfèrent tous, et sa
cohérence avec `data/sorabel.db` est vérifiée mécaniquement (33 contrôles, voir plus bas).
Sa destination au développement est `mcp_server/matrice.yaml` — chemin déjà anticipé par
`.gitignore` à la racine du dépôt.

## Fichiers `.drawio`

draw.io est absent de cette machine (pas de CLI). Les quatre fichiers sont livrés
**éditables**, à ouvrir dans [app.diagrams.net](https://app.diagrams.net) ou l'app desktop —
export en PNG/SVG à faire à la main, comme pour les schémas de chantier existants.

`04-chemin-text-to-sql.drawio` est un **patch ciblé** de
[`2-text-to-sql/flux-text-to-sql-v2.drawio`](../2-text-to-sql/flux-text-to-sql-v2.drawio),
passé en V3 : la V2 n'est pas modifiée, elle reste la version de travail du chantier 2. Les
cinq corrections apportées sont listées dans [`04-chemin-text-to-sql.md`](04-chemin-text-to-sql.md).

## Écarts signalés en écrivant ces livrables

Trois points relevés en confrontant la conception consolidée aux notes de chantier ; aucun
n'a nécessité de modifier les fichiers sources, chacun est tranché ici et documenté à
l'endroit concerné :

| Écart | Tranché dans | Décision |
|---|---|---|
| `EXPLAIN` cité dans le nœud N4 de la V2, sans trace dans aucune note de conception (`grep` négatif sur tous les `.md`) | [`04-chemin-text-to-sql.md`](04-chemin-text-to-sql.md) §1, [`04-chemin-text-to-sql.drawio`](04-chemin-text-to-sql.drawio) | retiré de la V3 |
| `stocks.id` / `ventes.id` dites « autorisées » par `2-text-to-sql/catalogue-tools.md`, exclues par `3-…/Q3.md` §3 | [`matrice.yaml`](matrice.yaml), [`03-catalogue-tools.md`](03-catalogue-tools.md) §9 | exclues — la matrice de `Q3.md` est normative |
| `get_schema` donné à « commercial · support » par `2-text-to-sql/catalogue-tools.md`, à trois profils par `3-…/Q3.md` §9 | [`03-catalogue-tools.md`](03-catalogue-tools.md) §9 | accordé aussi à `dev` |

## Vérifications effectuées

Sans dépendance installée (PyYAML et mermaid-cli sont absents de la machine, aucune n'a été
ajoutée) :

- **XML** — les quatre `.drawio` sont bien formés (`xml.etree.ElementTree`) et sans
  chevauchement de boîtes ;
- **JSON** — les quatre blocs de [`02-modele-chunk.md`](02-modele-chunk.md) sont valides ;
  les trois exemples sont conformes au schéma (requis, types, `enum`, `pattern`,
  `additionalProperties`) et couvrent les trois formes possibles (référence sans thème,
  thème sans référence, ni l'un ni l'autre) ; les trois fichiers source cités existent
  réellement dans `data/corpus/` ;
- **`matrice.yaml`** — 33 contrôles contre `data/sorabel.db` : aucune colonne ni table
  inventée, `default` à zéro droit, les trois colonnes sensibles fermées à `support` et
  `dev`, `clients.email` fermée aux quatre profils, `stocks.id`/`ventes.id` exclues,
  décomptes de colonnes (28 commercial · 25 support · 25 dev · 0 default) et d'éditions
  courantes éligibles (350 · 318 · 270 · 0) exacts ;
- **Mermaid** — les deux diagrammes (flowchart et sequenceDiagram) ont leurs blocs
  équilibrés, tous leurs identifiants résolus ; rendu réel non vérifié ici (mermaid-cli
  absent) — à confirmer par affichage GitHub ou aperçu VS Code ;
- **Non-régression** — aucun fichier hors ce dossier n'a été modifié.
