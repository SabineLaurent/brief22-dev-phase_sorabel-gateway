# E5 chiffrée — qui est arrêté, par quel étage, et ce qui n'en sort jamais

Axe 5 du [protocole de mesure](protocole-mesure.md). E5 porte **deux** obligations,
et elles ne se prouvent pas de la même façon : *tout appel est journalisé* se compte,
*les colonnes sensibles ne sortent jamais pour `support`* se cherche. Les deux
sections finales font l'une et l'autre.

Les 10 scénarios ci-dessous sont joués sous **chacun des 5 profils** de la matrice, soit
50 appels. **Aucun refus ne coûte un appel de modèle** — les étages 2 et 3 tranchent
avant la génération ; seuls les appels servis en dépensent un. Le journal est écrit dans
un répertoire temporaire : cette mesure ne pollue pas `logs/journal.jsonl`.

## Les trois étages ne se lisent pas au même endroit

| étage | ce qu'il décide | où il se lit |
|---|---|---|
| **1** | le catalogue visible | `tools/list` — **jamais dans le journal** |
| **2** | le droit d'appeler le tool | `blocked_at == 2` |
| **3** | le périmètre : colonnes, collections, thèmes | `blocked_at == 3` |

**L'étage 1 ne peut pas apparaître dans `blocked_at`**, et ce n'est pas un oubli : il
filtre une liste, il n'arrête aucun appel. Un client qui appelle un tool qu'il n'a pas
listé est refusé à l'étage 2 — c'est celui-là qui est journalisé. Mesurer E5 sur le
seul journal manquerait donc un étage entier.

C'est aussi pourquoi l'étage 1 est de l'**ergonomie** et non de la sécurité :
il évite au modèle d'essayer, il n'empêche rien.

Vérifié sur les 50 appels : **aucun ne porte `blocked_at = 1`** (0 occurrence). Ce n'est
pas un hasard de jeu — aucun site du code ne peut l'écrire.

## Étage 1 — le catalogue par profil

| Profil | Tools listés | Tools accordés par `matrice.yaml` |
|---|---:|---:|
| `default` | **0** / 8 | 0 / 8 |
| `dev` | **5** / 8 | 5 / 8 |
| `support` | **7** / 8 | 7 / 8 |
| `commercial` | **8** / 8 | 8 / 8 |
| `admin` | **8** / 8 | 8 / 8 |

Les deux colonnes coïncident, et c'est la seule chose que cette table doit établir :
le catalogue servi **est** la matrice, pas une copie qui pourrait en dériver.
`default` en liste 0 — un agent construit sur ce catalogue n'a aucun
tool, et c'est le comportement voulu, pas une panne.

## Étages 2 et 3 — ce que le journal dit de chaque appel

| Profil | servi `blocked_at=0` | arrêté à l'étage 2 | arrêté à l'étage 3 | non-réponse `blocked_at=None` |
|---|---:|---:|---:|---:|
| `default` | 0 | **10** | 0 | 0 |
| `dev` | 5 | **4** | **1** | 0 |
| `support` | 7 | **1** | **2** | 0 |
| `commercial` | 10 | 0 | 0 | 0 |
| `admin` | 10 | 0 | 0 | 0 |

**`blocked_at=None` n'est pas un refus, et les confondre rendrait E5 illisible.** Ce
sont les non-réponses : le seuil documentaire (`hors_corpus`), le jugement du
rédacteur (`contexte_insuffisant`), une clarification demandée, une panne. Aucune
n'est dans `REFUSAL_CODES`, aucune ne vaut `denied` au journal. Une gateway qui
compterait « je n'ai pas trouvé » comme « je refuse » gonflerait son propre chiffre de
gouvernance.

### Le même appel, cinq profils — les scénarios qui séparent

| Scénario | Ce qu'il vise | `default` | `dev` | `support` | `commercial` | `admin` |
|---|---|---|---|---|---|---|
| `doc-nominal` | réponse documentaire ordinaire — l'étage 2 seul est en jeu | **étage 2** | servi | servi | servi | servi |
| `doc-extraits` | extraits bruts, aucune barrière de refus documentaire sur ce tool | **étage 2** | servi | servi | servi | servi |
| `doc-fiche` | une édition ouverte à tous les profils dotés d'un périmètre | **étage 2** | servi | servi | servi | servi |
| `doc-note-fermee` | **l'étage 3 documentaire** : un thème de note fermé à `dev` et à `support` | **étage 2** | **étage 3** | **étage 3** | servi | servi |
| `doc-inventaire` | l'inventaire, qui dit ce que le périmètre du profil couvre | **étage 2** | servi | servi | servi | servi |
| `sql-nominal` | lecture chiffrée ordinaire — l'étage 2 seul est en jeu | **étage 2** | **étage 2** | servi | servi | servi |
| `sql-marge` | **l'étage 3 métier** : les trois colonnes sensibles d'E5 | **étage 2** | **étage 2** | **étage 3** | servi | servi |
| `sql-schema` | la forme de la base, retirée à `support` par arbitrage | **étage 2** | servi | **étage 2** | servi | servi |
| `sql-stock` | tool figé, argument contraint par motif | **étage 2** | **étage 2** | servi | servi | servi |
| `sql-commande` | tool figé, argument contraint par motif | **étage 2** | **étage 2** | servi | servi | servi |

## E5, première obligation — tout appel est journalisé

**50 appels, 50 entrées de journal.** Un appel, une ligne, refusé comme servi.

Aucune exception. C'est le point de passage unique qui le garantit et non une
discipline d'écriture : les deux `handle()` appliquent l'étage 2, **journalisent,**
puis purgent — dans cet ordre. Un refus prononcé avant la journalisation serait un
refus invisible, et c'est exactement ce que l'ordre interdit.

## E5, seconde obligation — les colonnes sensibles ne sortent pas

Cherchées dans la **vue client sérialisée**, celle qui part vraiment : `prix_achat_ht`,
`marge_pct`, `marge_ht`. Pas dans les objets internes — c'est la chaîne rendue qui
prouve quelque chose.

| Profil | La matrice les ouvre ? | Occurrences dans les vues client |
|---|---|---:|
| `default` | **non** | 0 |
| `dev` | **non** | 0 |
| `support` | **non** | 0 |
| `commercial` | oui | 2 |
| `admin` | oui | 2 |

**Zéro occurrence chez `default`, `dev` et `support`.** Les trois colonnes sont
fermées ensemble, et c'est délibéré : `marge_pct` se dérive de `prix_achat_ht` sur
120 produits sur 120, et `prix_achat_ht` de `marge_ht` sur 993 lignes de vente sur
993. En fermer deux sur trois ne fermerait rien.

Ce que ce zéro ne dit pas : il porte sur ces scénarios, pas sur toute requête
concevable. La garantie de fond est ailleurs — le contrat de lecture ne **décrit**
au modèle que les colonnes du périmètre, et le contrôle 5b de `validate()` refuse
les autres sur l'arbre, alias résolus. Les 83 contrôles de `make check-sql` en
tiennent le détail ; ce tableau atteste que la chaîne complète les respecte.

## « Nommer, pas numéroter » — tranché : on numérote

La réserve laissée ouverte au journal de développement se tranche ici, puisque c'est
cette mesure qui lit le champ pour la première fois. `blocked_at` reste un **entier**.

| | Pourquoi |
|---|---|
| `etage` porte déjà le même entier | deux vocabulaires pour une seule notion divergeraient le jour où l'un des deux serait retouché |
| les numéros sont ceux de la conception | `03-catalogue-tools.md` §3 numérote ses trois étages ; renommer ici obligerait à traduire à chaque lecture |
| un entier se compare | `blocked_at > 0` dit « arrêté par la gouvernance » en trois caractères ; un nom demanderait une table |

**Le nom appartient à la lecture, pas à l'écriture.** C'est ce rapport qui nomme les
étages — catalogue, tool, périmètre — et c'est le bon endroit : un lecteur humain lit
un rapport, une requête lit un entier.

*Rejouer : `make mesure-acces`.*
