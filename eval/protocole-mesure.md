# Protocole de mesure — ce qui varie, ce qui ne varie pas

Ce document fixe **l'espace des configurations comparables** avant que la moindre mesure
soit produite. Il existe pour une raison précise : un chiffre de gain n'a de valeur que si
l'on peut dire à quelle décision il est imputable.

Référence normative : [`Q5`](../docs/conception/1-rag-avance/Q5.md) §1.

> « Même corpus, même index nettoyé, même filtre de version, même jeu de questions, même
> règle de départage. **Seul l'étage de recherche change** — sinon on ne mesure pas ce
> qu'on croit mesurer. »

## 1. Le principe : une seule chose change à la fois

Un « RAG simple » construit de bout en bout — sa propre ingestion, son propre index, sa
propre recherche — produirait **un seul chiffre indécomposable**, qui additionnerait :

| Ce qui change | Gain attribuable mesuré ou attendu |
|---|---|
| le nettoyage du texte indexé | **+5 en Hit@3** sur 8 questions ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2) |
| le filtre de version | change le dénominateur : 350 candidats au lieu de 400 |
| la stratégie de recherche | **la seule chose que le brief demande de mesurer** |

Un tel chiffre est flatteur et indéfendable : impossible de répondre à « quelle part vient
du reranker ? ». C'est le reproche que [`Q5`](../docs/conception/1-rag-avance/Q5.md) §2
adresse déjà au protocole à deux configurations.

**Décision : aucune mesure ne fait varier plus d'un drapeau à la fois.**

## 2. Six drapeaux orthogonaux

L'espace de mesure est un produit de six paramètres, pas une collection de pipelines.

| Drapeau | Valeurs | Où il s'applique | Ce qu'il change |
|---|---|---|---|
| `--text` | `clean` *(défaut)* · `raw` | ingestion | le texte indexé : avec ou sans retrait des liens sortants et des références-exemples des SAV ([`Q2`](../docs/conception/1-rag-avance/Q2.md) §2) |
| `--config` | `A` · `B` · `C` | recherche | l'étage de recherche : dense seul · lexical seul · hybride BM25+dense+RRF+rerank |
| `--version-filter` | `on` *(défaut)* · `off` | recherche | `is_current` appliqué dans chaque liste **avant sa troncature** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §5), ou pas de filtre |
| `--tiebreak` | `on` · `off` | recherche | la règle de départage fiche/notice, en rangs, `FENETRE = 3` ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §5) |
| `--embeddings` | `local` *(défaut)* · `azure-small` | ingestion **et** recherche | le modèle qui fabrique les vecteurs : `intfloat/multilingual-e5-base` en local, `text-embedding-3-small` sur Azure AI Foundry — **ajouté le 2026-09-08** |
| `--rerank` | `local` *(défaut)* · `cohere` | recherche seule | le modèle qui classe les candidats : le cross-encoder `mmarco-mMiniLMv2-L12-H384-v1` en local, `Cohere-rerank-v4.0-pro` sur Azure AI Foundry — **ajouté le 2026-09-08** |

### Ce que chaque levier change, concrètement

**`--text` — texte nettoyé ou brut.** Ce qui part dans l'**index**, jamais ce qui est
affiché : le texte rendu par `get_document` et l'extrait cité restent complets dans les deux
cas. Le nettoyage retire les deux endroits où une édition cite une référence **qui n'est pas
son sujet** :

```
Référence produit : REF-8842                            <- le sujet, conservé
Accessoires et produits associés : REF-4581, REF-6825   <- ligne retirée      (fiches)
… exemple traité sur la référence REF-2303.             <- la REF est retirée (SAV)
```

Sans ce retrait, la fiche de `REF-8842` remonte sur une recherche `REF-4581` aussi haut que
la fiche de `REF-4581` elle-même : pour BM25 une référence est un terme à IDF très élevé.
Chiffré à **+5 en Hit@3** ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2).

**`--version-filter` — le filtre `is_current`.** Les 400 éditions sont indexées ; 350 sont
la version la plus récente de leur document.

| | Ce que la recherche voit | Effet |
|---|---|---|
| `on` | les **350** éditions courantes | un document = une place |
| `off` | les **400** | les deux éditions d'un même document sortent côte à côte — elles se ressemblent à **0,965** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §4) — soit deux places du top-5 pour un contenu unique |

**`--tiebreak` — le départage fiche / notice.** Une règle de fin de course, appliquée à la
liste finale. Sur la requête `REF-8842`, où la question *est* la référence, nue :

```
1. notices/notice-REF-8842     <- la notice cite la référence 2 fois
2. notes/…-politique-tarifaire
3. fiches/REF-8842-v2.1        <- la fiche la cite 1 fois
```

Le test d'acceptance exige la **fiche** en tête, or rien dans la requête ne demande une fiche
plutôt qu'une notice — aucun étage de recherche ne peut le deviner
([`Q3`](../docs/conception/1-rag-avance/Q3.md) §5). D'où la règle : **à référence égale,
dans les trois premiers, la fiche technique passe devant la notice.** Un seul échange, jamais
un reclassement, et elle ne lit jamais le texte de la question.

**`--embeddings` — le modèle qui fabrique les vecteurs.** Seul drapeau qui s'applique des
deux côtés à la fois : le même modèle doit encoder les documents à l'ingestion **et** la
question à la requête, sinon les deux vecteurs ne vivent pas dans le même espace. C'est
d'ailleurs ce qu'un garde-fou d'ingestion refuse déjà — l'empreinte du modèle est écrite dans
la métadonnée de la collection et vérifiée à l'ouverture.

Deux différences de nature, à connaître avant de lire les chiffres :

| | `local` | `azure-small` |
|---|---|---|
| modèle | `intfloat/multilingual-e5-base` | `text-embedding-3-small` |
| dimensions | 768 | 1536 |
| forme | **asymétrique** — préfixes `query:` / `passage:` | **symétrique** — aucun préfixe |
| où il tourne | dans le processus (PyTorch) | appel réseau (Foundry, API v1) |

L'asymétrie est le point qui compte : e5 est entraîné à encoder une *question* et un
*document* différemment, ce que les modèles OpenAI ne font pas. Ce n'est pas joué d'avance
dans un sens ni dans l'autre sur un corpus français, et c'est précisément ce que l'axe 6
mesure au lieu de le supposer.

**`--rerank` — le modèle qui classe.** Contrairement à `--embeddings`, il ne touche **pas
l'index** : le rerank note des candidats déjà trouvés. Donc **pas de réindexation, pas de
collection supplémentaire, et `REFUSAL_THRESHOLD` n'est pas concerné** — la configuration A
ne rerank pas. C'est l'axe le moins cher du protocole, et le seul dont le coût ne croît pas
avec la taille du corpus.

Ce qui change en revanche, et qui est la seule chose à ne pas oublier : **`RERANK_THRESHOLD`
est sur l'échelle du reranker**. Un cross-encoder rend un logit passé au sigmoïde, Cohere un
`relevance_score` natif ; les deux vivent dans `[0, 1]` sans y avoir la même distribution.

**Chaque valeur de `--text` et de `--embeddings` a sa collection Chroma**, parce que le texte
indexé **et le modèle** déterminent les vecteurs : `sorabel_corpus` pour `clean` + `local`,
`sorabel_corpus_raw` pour `raw`, `sorabel_corpus_azure_small` pour `clean` + `azure-small`.
Les trois autres drapeaux ne touchent pas à l'index et se règlent à la requête.

**`--embeddings` n'est pas un drapeau du script**, contrairement aux quatre autres : il se
pose par l'environnement, `CHROMA_COLLECTION` et `AZURE_EMBEDDING_DEPLOYMENT` devant la
commande — l'environnement primant sur `.env`. Aucune ligne de code ne le connaît, et les
deux index coexistent, ce qui est la condition pour rejouer la comparaison dans les deux
sens. La cible Make reste l'interface, comme pour les autres (§10).

> **Le rerank n'est pas ce drapeau-ci.** `AZURE_RERANK_DEPLOYMENT` bascule le reranker sur un
> LLM-juge sans toucher à l'index — c'est un changement de *classement*, pas d'*espace
> vectoriel*. Il demande sa propre mesure et sa propre recalibration du seuil hybride ; le
> mêler à celle-ci ferait varier deux choses à la fois (§1).

**Le filtre de version est un drapeau de recherche, pas d'ingestion.** Les 400 éditions sont
indexées dans les deux collections, `is_current` étant une métadonnée
([`Q1`](../docs/conception/1-rag-avance/Q1.md) §5). Le désactiver ne demande donc pas un
second index — c'est ce qui rend l'axe 2 bon marché.

## 3. Les sept axes de mesure

### Axe 1 — la recherche, à ingestion constante

C'est **E6**, l'exigence du brief et du test d'acceptance.

| | Constant | Varie |
|---|---|---|
| | `--text clean` · `--version-filter on` · `--tiebreak` publié dans les deux positions | `--config A` → `B` → `C` |

| | Étage de recherche | Rôle |
|---|---|---|
| **A** | embedding + top-k | l'« avant » que le brief nomme *recherche dense initiale* |
| **B** | BM25 + top-k | **le témoin** — déjà 8/8 en Hit@1 sur le critère du jeu ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §2) |
| **C** | BM25 + dense + RRF + rerank | l'« après » |

B n'est pas demandé par le brief. Sans lui, le gain attribué à l'hybride inclut celui de
BM25 seul, et le chiffre ment par omission
([`Q5`](../docs/conception/1-rag-avance/Q5.md) §2).

### Axe 2 — l'ingestion, à recherche constante

Le dossier ne le mesure pas. Il répond à : **que valent les décisions d'ingestion ?**

| | Constant | Varie |
|---|---|---|
| nettoyage | `--config` fixée · `--version-filter on` | `--text clean` → `raw` |
| versionnement | `--config` fixée · `--text clean` | `--version-filter on` → `off` |

Deux mesures distinctes, un drapeau chacune. La première chiffre le nettoyage sur ce corpus
et doit retrouver le **+5 en Hit@3** annoncé par [`Q3`](../docs/conception/1-rag-avance/Q3.md) §2 —
si elle ne le retrouve pas, c'est l'implémentation qui s'écarte du dossier, et on le saura.

La seconde chiffre ce que coûte l'absence de versionnement. L'attendu est nommé avant d'être
mesuré, pour ne pas l'ajuster après coup : **50 documents ont deux éditions à 0,965 de
similarité** ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §4). Sans filtre, les deux
occupent deux places du même top-5 pour un contenu unique.

> **Le dédoublonnage n'est pas un axe de mesure, et aucune de ses deux formes n'est
> praticable ici.**
>
> *Par hash* : **zéro doublon d'octets sur les 400 fichiers**
> ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §3) — une étape qui ne se déclenche jamais.
>
> *Par proximité* : impossible, mesuré. Les 80 procédures SAV courantes sont **un même
> gabarit** — le dossier les dit « génériques »
> ([`description-corpus.md`](../docs/conception/1-rag-avance/description-corpus.md) §5) et
> chiffre à 86 % leur part de texte partagé ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §1).
> Vérifié ligne à ligne : deux procédures **différentes** ne diffèrent que par leur titre,
> leur date et les deux occurrences de leur référence-exemple ; « Conditions », « Étapes » et
> « Cas hors périmètre » sont identiques au caractère près sur les 80.
>
> | | similarité |
> |---|---|
> | entre procédures **différentes** — 3 160 paires | 0,932 – **0,996**, médiane 0,952 |
> | entre v1.0 et v2.0 du **même** document — 10 paires | 0,983 – 0,986 |
>
> **Les deux bandes se recouvrent entièrement** : deux procédures différentes peuvent être
> plus semblables que deux versions du même document. Aucun seuil ne les sépare — réglé sous
> 0,95 il efface **79 procédures sur 80**, réglé au-dessus il ne dédoublonne rien. C'est la
> même figure que le seuil BM25 impossible de [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3,
> et c'est ce qui fait de `doc_key` + `version` la **seule** manière de séparer deux éditions.
>
> Le seul risque de doublon d'index reste la ré-ingestion, déjà couverte par l'`upsert`
> déterministe.

### Axe 3 — le moment du filtrage de périmètre, à recherche constante

**Ajouté le 2026-09-03**, au chantier du filtre de périmètre documentaire. Ce document a été
arrêté avant l'implémentation exprès pour ne pas se façonner sur elle : *ajouter* un axe
n'est pas *ajuster* une mesure existante, et la distinction est consignée au journal. Les
sept mesures publiées précédemment sont inchangées, et rejouées à l'identique — `git diff`
vide sur `eval/resultats/` — après la régénération des index BM25 qu'a demandée ce chantier.

Il répond à : **que coûte un périmètre appliqué après la troncature plutôt qu'avant ?**

| | Constant | Varie |
|---|---|---|
| | `--config C` · `--text clean` · `--version-filter on` · profil fixé | **P0** (après) → **P1** (avant) |

La matrice d'accès ferme le corpus par collection et par thème de note. Comme `is_current`,
ce filtre doit s'appliquer **avant** la troncature à `top_k` ([`Q1`](../docs/conception/1-rag-avance/Q1.md) §5) :
c'est la propriété que ce chantier a retenue, et cet axe la chiffre au lieu de l'argumenter.

**P0 n'existe pas dans le code de production.** Elle se fabrique dans le script de mesure, à
partir du classement de référence : `search(perimeter=None)` puis retrait des résultats
interdits. Les deux configurations partent donc littéralement du même classement, et aucune
branche morte n'est entretenue pour les besoins d'une mesure.

Trois profils, dont un **témoin** : `dev` et `support` perdent des éditions, `commercial`
couvre tout le corpus courant — le filtre y est un no-op, et P0 doit y égaler P1 à la ligne
près. Un écart chez lui signalerait un défaut du protocole, pas du filtre.

Métriques : **résultats rendus**, **questions vidées** (en distinguant les couvertes des
hors-corpus) et **seuil évalué sur un résultat interdit**. Pas Hit@1, et l'attendu est nommé
avant la mesure : aucune des 30 questions ne vise une note interne, donc **aucune cible n'est
rendue inatteignable** et Hit@1 ne doit pas bouger. S'il bougeait, ce serait le signe que le
filtre écarte autre chose que ce qu'il doit écarter.

Publié dans [`rapport_perimetre.md`](rapport_perimetre.md), cible `make mesure-perimetre`.

### Axe 4 — le refus tel qu'il est servi, à recherche constante

**Ajouté le 2026-09-07**, à la revue de fin de chantier. Comme l'axe 3, *ajouter* un axe
n'est pas *ajuster* une mesure existante : les sept mesures des axes 1 et 2 sont inchangées.

Il répond à : **combien de barrières le client rencontre-t-il réellement ?**

| | Constant | Varie |
|---|---|---|
| | `--config C` · `--text clean` · `--version-filter on` · profil `commercial` | **le nombre de barrières prises en compte** |

`answer_question` a **deux** barrières, et l'axe 1 n'en mesure qu'une :

| | Où | Ce qu'elle lit | Nature |
|---|---|---|---|
| **barrière 1** `hors_corpus` | `search(threshold=…)` | le score du premier résultat | déterministe, avant tout appel au modèle |
| **barrière 2** `contexte_insuffisant` | la garde de suffisance du rédacteur ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §5) | les extraits eux-mêmes | jugement du modèle, **non déterministe** |

La ligne « refus corrects » de l'axe 1 porte sur la barrière 1 seule — c'est le bon périmètre
pour comparer trois étages de recherche, et c'est un chiffre de recherche, **pas une mesure
d'E1**. Publier les deux colonnes est la seule manière d'empêcher cette lecture.

**Une exception assumée au §11.** Ce protocole refuse tout juge probabiliste *dans la
mesure*. Ici le juge est dans le **produit** : mesurer ce que la gateway fait suppose de
faire ce qu'elle fait, appel de modèle compris. La conséquence est publiée plutôt que
masquée — la cible joue **trois passes**, et le rapport donne une plage `n–m` sur toute
métrique qui bouge, avec le nom des questions qui bougent. Jamais une moyenne : elle
cacherait laquelle.

`search_docs` n'entre pas dans cet axe. Il n'a aucune barrière et n'en aura pas
([`03-catalogue-tools.md`](../docs/conception/LIVRABLES_CONCEPTION/03-catalogue-tools.md)) :
c'est le tool sur lequel E6 se mesure, et un seuil qui masque les résultats sous la barre
rend le rang inobservable.

Publié dans [`rapport_refus.md`](rapport_refus.md), cible `make mesure-refus`.

### Axe 5 — les étages d'accès, à corpus et base constants

**Ajouté le 2026-09-07**, même revue. C'est **E5**, la seule des six exigences qui n'avait
pas de preuve chiffrée publiée.

Il répond à : **qui est arrêté, par quel étage, et qu'est-ce qui ne sort jamais ?**

| | Constant | Varie |
|---|---|---|
| | dix scénarios d'appel, un par tool plus deux qui visent l'étage 3 | **le profil** — les cinq de la matrice |

E5 porte deux obligations qui ne se prouvent pas de la même façon, et l'axe fait les deux :
*tout appel est journalisé* se **compte** (autant d'entrées que d'appels), *les colonnes
sensibles ne sortent jamais pour `support`* se **cherche** — dans la vue client sérialisée,
qui est la seule chaîne qui parte vraiment.

**Deux sources, parce que les trois étages ne se lisent pas au même endroit.** L'étage 1 se
lit dans `tools/list` ; les étages 2 et 3 dans le champ `blocked_at` du journal. L'étage 1 ne
peut **pas** apparaître dans `blocked_at` : il filtre une liste, il n'arrête aucun appel — un
client qui appelle un tool non listé est refusé à l'étage 2. Mesurer E5 sur le seul journal
manquerait donc un étage entier.

Aucun refus ne coûte un appel de modèle : les étages 2 et 3 tranchent avant la génération.
La mesure écrit son journal dans un répertoire temporaire — elle ne pollue pas
`logs/journal.jsonl`.

Publié dans [`rapport_acces.md`](rapport_acces.md), cible `make mesure-acces`.

### Axe 6 — le modèle d'embeddings, à texte et recherche constants

**Ajouté le 2026-09-08**, et il n'est pas demandé par le brief : c'est une mesure de
curiosité, assumée comme telle. Elle répond à une question que le dossier a tranchée par un
choix par défaut plutôt que par un chiffre — **que vaut `multilingual-e5-base` face à un
modèle d'embeddings de service ?**

| | Constant | Varie |
|---|---|---|
| | `--text clean` · `--version-filter on` · `--tiebreak on` · le reranker | `--embeddings local` → `azure-small` |

**Deux configurations de recherche sont publiées, pas une** :

| | Ce qu'elle isole |
|---|---|
| **A** (dense seul) | l'embedder **seul**, sans BM25 pour le sauver — le vrai verdict sur le modèle |
| **C** (hybride) | ce que le produit servi y gagne ou y perd — le seul chiffre qui décide d'un changement |

L'écart entre les deux est attendu, et c'est le résultat le plus intéressant de l'axe : sur
les 8 questions `reference_exacte`, **BM25 fait l'essentiel du travail** — une `REF-NNNN` est
un terme à IDF très élevé — donc un embedder meilleur peut n'y rien changer du tout. Lire les
trois sous-ensembles séparément, jamais le total : c'est sur `couverte` que l'embedder se
joue.

**Le seuil de refus est recalibré pour chaque modèle**, et ce n'est pas un détail de méthode :
deux espaces vectoriels n'ont pas la même distribution de scores. Comparer deux modèles à
seuil constant mesurerait le seuil. Le dépôt a déjà connu ce défaut exactement — deux
configurations jugées par la même formule, avec un résultat vrai par construction — et il est
consigné (`docs/BUGS.md`, MES-01).

> **Réserve d'échantillon, à écrire dans le rapport avant les chiffres.** Huit questions par
> sous-ensemble : une seule question qui bascule vaut **12,5 points** de Hit@1. Sur une
> comparaison de modèles, où l'écart attendu est petit, cette réserve pèse plus lourd que sur
> l'axe 1 — où l'écart mesuré (1/8 → 8/8) dépassait le bruit de plusieurs longueurs. Un écart
> d'une ou deux questions ne conclut rien.

### Axe 7 — le reranker, à index et texte constants

**Ajouté le 2026-09-08**, en même temps que l'axe 6 et pour la même raison : le dossier a
choisi le reranker par un tableau de conception, pas par une mesure. La question est
**que vaut le cross-encoder local face à un reranker de service ?**

| | Constant | Varie |
|---|---|---|
| | `--text clean` · `--embeddings local` · `--version-filter on` · `--tiebreak on` | `--rerank local` → `cohere` |

**`--embeddings` reste `local` dans cet axe, et ce n'est pas un détail** : c'est la seule
façon d'attribuer l'écart au reranker. La cellule « les deux changent » ne se lit qu'après
les axes 6 et 7 pris séparément, sinon elle ne dit rien de qui a fait quoi.

Seule la configuration **C** est concernée — A ne rerank pas, B non plus. L'axe publie donc
une seule ligne par valeur du drapeau, et le seuil hybride est **recalibré pour chacune**.

> **Ce que l'axe ne dira pas.** Le reranker note les candidats que la recherche lui donne.
> Sur les 8 questions `reference_exacte`, ces candidats sont déjà les bons — BM25 y fait
> l'essentiel du travail. Un meilleur reranker ne peut donc y gagner que des places, jamais
> des documents. C'est sur `couverte`, et sur le **refus** (le score du premier sert de
> critère), qu'il se joue.

## 4. Le « RAG simple » est un coin de l'espace, pas un second projet

Il ne se construit pas, il se **désactive**.

| | `--text` | `--config` | `--version-filter` | `--tiebreak` |
|---|---|---|---|---|
| **RAG simple** | `raw` | `A` | `off` | `off` |
| **RAG avancé** | `clean` | `C` | `on` | `on` |

Cette ligne-là **peut** être publiée — elle parle, et c'est celle qu'un lecteur non
technique comprend. Mais elle est publiée **en plus** des axes 1 et 2, jamais à leur place,
et toujours accompagnée de leur décomposition. Un écart global sans ventilation n'est pas
une mesure, c'est une affiche.

## 5. Le refus n'a pas la même grandeur selon la configuration

[`Q5`](../docs/conception/1-rag-avance/Q5.md) §4 : la configuration A n'a pas de reranker,
donc pas du score sur lequel [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3 fait porter le
seuil. Il n'existe pas de grandeur commune aux trois.

| Configuration | Critère de refus | Grandeur |
|---|---|---|
| **A** | similarité cosinus du premier résultat | bornée, comparable entre requêtes — **mais pas séparable**, voir ci-dessous |
| **B** | **aucun seuil possible** — case vide, et c'est un résultat | — |
| **C** | score du reranker | bornée, apprise |

> **Mesuré à l'étape 2, et le dossier ne l'anticipait pas.** Q5 §4 retient la distance
> cosinus pour la configuration A parce qu'elle est *bornée*. Bornée ne veut pas dire
> *séparable* : sur le jeu de calibration, les scores des questions couvertes tiennent dans
> **0,820 – 0,882** et ceux des questions hors corpus dans **0,793 – 0,831**. Les deux
> populations se chevauchent, exactement comme les plages BM25 de
> [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3 — la famille e5 comprime ses similarités
> dans une bande étroite. Le meilleur seuil, 0,831, refuse 8 questions hors corpus sur 8 au
> prix d'une question couverte sur 6. **La barrière de la configuration A existe donc, mais
> elle est marginale** — ce qui renforce l'argument de Q4 §3 : le seuil a besoin d'une
> échelle apprise, celle du reranker.

> La ligne se lit **« chaque configuration à son meilleur réglage »**, jamais « le même
> seuil ». Le seuil de chacune est calibré sur le **même jeu de calibration** — huit
> questions hors corpus écrites par nous, distinctes des huit du jeu d'évaluation
> ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §6).

Conséquence pour l'étape 2, à ne pas manquer : la recherche dense seule doit poser son seuil
sur **la distance cosinus**, nommée comme telle. Un seuil écrit sur un score non borné
serait à jeter à l'étape 3.

## 6. Ce qui ne varie dans aucune mesure

- le **corpus** : `data/corpus/`, 400 éditions, inchangé ;
- le **jeu de questions** : `eval/questions_rag.jsonl`, 30 questions — 8 `reference_exacte`,
  14 `couverte`, 8 `hors_corpus` ;
- le **profil d'accès** : `commercial`, périmètre documentaire complet, donc le cas le plus
  difficile pour le refus et le seul indépendant d'un filtre de gouvernance
  ([`Q5`](../docs/conception/1-rag-avance/Q5.md) §5). Le taux du profil `support` est
  indiqué en second, **comme effet de la matrice, pas comme gain de recherche** ;
- les **versions figées** : `pypdf`, le reranker — elles déterminent le contenu de l'index et
  le classement ([`Q3`](../docs/conception/1-rag-avance/Q3.md) §6). **Le modèle d'embeddings
  et le reranker ont quitté cette liste le 2026-09-08** : ils sont devenus les drapeaux
  `--embeddings` (axe 6) et `--rerank` (axe 7). Ils restent invariants *dans chacune des cinq
  autres mesures* — ce qui change est qu'ils sont désormais nommés dans le rapport plutôt que
  supposés ;
- la **graine** et l'**ordre de parcours** du corpus ;
- le **compte** : on compte les **questions**, pas les références — 8 questions pour
  7 références distinctes, vérifié sur le fichier réel.

## 7. Ce qui est publié

`eval_rag.py` écrit **un CSV par question** — configuration, id, critère, rang du bon
document, score, refus oui/non, code renvoyé — puis imprime le tableau de synthèse.

Le CSV importe autant que le tableau : c'est lui qui permet de dire *quelle* question a
échoué et pourquoi. Trois sous-ensembles, trois métriques
([`Q5`](../docs/conception/1-rag-avance/Q5.md) §3) :

| Sous-ensemble | n | Métrique |
|---|---:|---|
| `reference_exacte` | 8 | Hit@1 **sur deux critères** — référence attendue, et fiche technique en tête — plus MRR |
| `couverte` | 14 | Recall@5 sur `attendu_type`, et rang du premier document du bon type |
| `hors_corpus` | 8 | taux de refus correct |

**Les deux critères de Hit@1 sont publiés côte à côte** : ils diffèrent de 6 points sur 8 en
BM25 seul. Le critère exigeant est celui du test d'acceptance ; celui du jeu se calcule sans
interprétation. Et `--tiebreak` est publié **dans ses deux positions, sur les trois
sous-ensembles** — c'est sur `couverte` que la règle peut nuire.

## 8. Nommage

**Le vocabulaire publié est celui des cibles Make, en français** — c'est lui qui apparaît
dans le rapport et qui doit rester stable une fois qu'un chiffre le cite. Les drapeaux du
script restent en anglais par cohérence avec `--dry-run` et `--reset` ; ils sont un détail
d'implémentation, pas l'interface. Voir §10.

## 9. Ce que ce protocole ne mesure pas — à dire, pas à cacher

- **huit questions par sous-ensemble**, c'est un échantillon minuscule. Le seuil de refus
  reste réglé sur une base étroite : limite méthodologique, pas corrigeable à cette échelle ;
- **`attendu_type` ne prend que trois valeurs** sur les questions `couverte` — et n'est
  présent que sur **13** des 14. Ce sous-ensemble détecte une régression, il ne démontre pas
  un gain ;
- **sur les 6 questions `couverte` qui attendent une `procedure_sav`, le titre est le seul
  discriminant.** Le corps des 80 procédures est le même gabarit, et le nettoyage SAV le rend
  identique à 100 % en retirant la référence-exemple. Trouver le bon *type* est donc trivial ;
  trouver la bonne *procédure* repose entièrement sur la ligne de titre. À lire avant les
  chiffres de `couverte`, sous peine de prendre pour un gain de recherche ce qui n'est qu'une
  propriété du corpus ;
- **deux questions sont en tension avec le corpus** : RAG-19 porte sur un sujet absent,
  RAG-20 attend une fiche technique là où le terme n'existe qu'en notice. Elles sont
  mesurées comme les autres et **signalées dans le rapport** : une configuration qui les
  rate n'a pas régressé ;
- **rejouer A après C**, pas seulement avant
  ([`Q5`](../docs/conception/1-rag-avance/Q5.md) §6) : une mesure « avant » faite sur un
  index qui a changé entre-temps n'est pas une mesure.

## 10. Comment ça se joue

### Le harnais lit les `.jsonl`, il ne passe pas par le serveur MCP

Le jeu d'évaluation est du **JSON Lines** — une question par ligne, pas un `.json` unique :

```
eval/questions_rag.jsonl          30 questions fournies — 8 reference_exacte · 14 couverte · 8 hors_corpus
eval/questions_calibration.jsonl  14 questions écrites par nous — 8 hors_corpus · 6 couverte — CALIBRATION SEULEMENT
eval/questions_sql.jsonl          chantier 2, hors de ce protocole
```

**Le jeu de calibration ne porte aucune référence produit** — 0 question sur 14, contre 8 sur
30 dans le jeu de mesure. Il n'existe que pour placer une frontière couvert / hors-corpus, et
c'est légitime ; mais il ne teste jamais le point faible d'un modèle sur les identifiants,
donc il est **non représentatif pour comparer deux modèles**. Les axes 6 et 7 l'ont constaté
deux fois, en sens contraire : la calibration y a annoncé l'inverse du résultat. La leçon est
plus précise que « un jeu de réglage ne prédit pas » — **un jeu qui ne contient pas le cas
difficile ne peut rien dire du cas difficile.**

Le harnais lit `questions_rag.jsonl`, rejoue **chaque question dans chaque configuration**,
et écrit une ligne de CSV par couple (question, configuration).

> **Les deux fichiers de questions ne se mélangent jamais.**
> `questions_calibration.jsonl` sert à régler les seuils,
> `questions_rag.jsonl` à les mesurer. Les confondre ferait constater un réglage au lieu de
> mesurer une capacité ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §6). Le harnais refuse
> de calibrer et de mesurer sur le même fichier.

**Le harnais attaque la recherche directement, sans serveur MCP.** C'est ce qui permet de
mesurer E6 dès l'étape 2, alors que les tests d'acceptance — qui exigent le serveur —
ne passeront qu'au chantier 3. Ce sont deux vérifications différentes, sur deux chemins
différents, et elles n'ont pas le même calendrier.

Le script est `packages/rag_machines/evals_and_controls/eval_rag.py`, lancé **en module** :
`python -m packages.rag_machines.evals_and_controls.eval_rag`. Il a vécu sous `scripts/` et
« lancé par chemin » le temps du chantier RAG ; la crainte d'alors — nommer un paquet `eval` —
ne s'applique plus, le paquet s'appelle `evals_and_controls` et le dossier `eval/` ne porte
que des données et des rapports.

### Une cible Make par mesure publiée

Les six drapeaux forment 96 combinaisons, mais **on n'en publie que onze** — auxquelles
s'ajoutent les trois axes qui ne se règlent pas par un drapeau de recherche (périmètre, refus,
accès), une cible chacun. À ce
nombre-là, une cible nommée par mesure vaut mieux qu'une chaîne de drapeaux : c'est la
convention du dépôt — tous les flux passent par `make` —, c'est ce qui rend un chiffre
rejouable tel quel, et c'est le seul endroit où le protocole se lit d'un coup d'œil.

```make
# — ingestion —
ingest                   # texte nettoyé -> sorabel_corpus        (défaut, existant)
ingest-brut              # texte brut    -> sorabel_corpus_raw    (axe 2a)

# — axe 1 : la recherche, à ingestion constante —
mesure-dense             # A · clean · filtre on   — l'« avant » du brief
mesure-lexical           # B · clean · filtre on   — le témoin
mesure-hybride           # C · clean · filtre on   — l'« après »

# — axe 2 : l'ingestion, à recherche constante —
mesure-sans-nettoyage    # C · raw   · filtre on   — ce que vaut le nettoyage
mesure-sans-versions     # C · clean · filtre off  — ce que vaut le versionnement

# — axe 4 : le refus servi, à recherche constante —
mesure-refus             # C · clean · filtre on   — les deux barrières, 3 passes

# — axe 5 : les étages d'accès —
mesure-acces             # E5 : dix scénarios × cinq profils, journal + colonnes fermées

# — axe 6 : le modèle d'embeddings, à texte et recherche constants —
ingest-azure-small       # texte nettoyé, embeddings OpenAI -> sorabel_corpus_azure_small
mesure-embeddings        # A et C, les deux modèles côte à côte, seuils recalibrés chacun

# — axe 7 : le reranker, à index et texte constants —
calibrer-cohere          # le seuil hybride sur l'échelle de Cohere
mesure-rerank            # C · clean · embeddings local, les deux rerankers côte à côte

# — la ligne parlante —
mesure-rag-simple        # A · raw   · filtre off · départage off

# — orchestration —
mesure                   # rejoue les sept et réécrit eval/rapport_gain.md
calibrer                 # règle les seuils sur questions_calibration.jsonl
```

**Les cibles sont l'interface publiée ; les drapeaux restent dessous.** Le script les accepte
— il en a besoin — mais aucun chiffre du rapport ne cite une ligne de commande à drapeaux :
il cite une cible. L'exploration ponctuelle et le débogage passent par le script directement,
sans que ça devienne une manière de produire un résultat publiable.

```bash
uv run python scripts/eval_rag.py --config A --text raw --version-filter off   # exploration
make mesure-rag-simple                                                          # publication
```

**`--tiebreak` n'a pas sa cible.** La règle de départage est un réordonnancement de la liste
finale : le harnais calcule les deux positions dans la même passe et publie les deux colonnes
([`Q3`](../docs/conception/1-rag-avance/Q3.md) §5). Une cible par position doublerait le
nombre de runs pour un post-traitement qui ne coûte rien.

**Les noms de cibles sont en français**, comme le reste du `Makefile` et comme le fixe
`CLAUDE.md`. Les drapeaux du script restent en anglais, par cohérence avec `--dry-run` et
`--reset` — ils ne sont plus le vocabulaire publié, donc la question de leur langue ne se
pose plus.

### Ce qui est écrit sur le disque

```
eval/resultats/mesure-dense.csv            une ligne par question
eval/resultats/mesure-sans-nettoyage.csv
eval/resultats/…                           un fichier par cible
eval/resultats/mesure-refus.csv            axe 4 — une ligne par (question, passe)
eval/resultats/mesure-acces.csv            axe 5 — une ligne par (profil, scénario)
eval/rapport_gain.md                       le tableau de synthèse publié
eval/rapport_perimetre.md                  axe 3
eval/rapport_refus.md                      axe 4
eval/rapport_acces.md                      axe 5
```

**Le CSV porte le nom de la cible qui l'a produit**, et son en-tête tient sur **deux lignes de
commentaire** :

```
# cible=mesure-hybride config=C text=clean version_filter=on
# candidats=vivier:20/budget:20/plafond:aucun seuil=0.0530
```

La première rappelle les quatre drapeaux effectifs. La seconde porte ce dont dépend chaque
chiffre de la colonne `refused` et que le nom de la cible ne dit pas : la **politique de
candidats** — vivier récupéré par étage, budget réellement noté par le reranker, plafond de
places par titre — et le **seuil** appliqué. Elle vaut `candidats=sans-objet` en `A` et en `B`,
qui ne passent ni par un vivier ni par un reranker.

Un fichier de résultats dont on ne peut pas relire la configuration n'est pas une mesure, c'est
un souvenir — et le nom de la cible est la manière la plus courte de la relire, puisqu'il suffit
de la relancer. **Le nom ne suffit pourtant pas quand la configuration change sous un nom
constant** : c'est exactement ce qui manquait, et deux CSV joués de part et d'autre d'un
changement de profondeur étaient indiscernables.

Un run d'exploration lancé au script écrit dans `eval/resultats/adhoc-*.csv`, jamais sous un
nom de cible : ce qui n'est pas reproductible par un `make` ne prend pas la place de ce qui
l'est. Et `make mesure` réécrit `rapport_gain.md` **en entier**, jamais par retouche — un
rapport à moitié régénéré mélangerait deux exécutions.

## 11. Pas d'évaluateur de RAG — et c'est une décision, pas une paresse

La question se pose : RAGAS, DeepEval, TruLens, promptfoo, ou un LLM-juge maison. **Non**,
et [`Q5`](../docs/conception/1-rag-avance/Q5.md) §3 le tranche explicitement :

> « La mesure reste une comparaison de chaînes dans les deux cas — **pas de LLM-juge, pas
> d'annotation manuelle**, deux exécutions donnent le même chiffre. »

Quatre raisons, dans l'ordre où elles pèsent.

**1. Les métriques demandées sont des métriques de *retrieval*, pas de génération.** Hit@1,
MRR, Recall@5, taux de refus : toutes se calculent par égalité de chaînes contre
`attendu_reference` et `attendu_type`.

```python
top = resultats[0]
hit_reference = top.metadata["reference"] == question["attendu_reference"]
hit_fiche     = hit_reference and top.metadata["doc_type"] == "fiche_technique"
```

Un évaluateur n'ajouterait rien à ces trois lignes, sinon une dépendance.

**2. Le corpus d'évaluation n'a pas de réponses de référence.** `questions_rag.jsonl` porte
`id`, `type`, `question`, `attendu_reference` — et rien d'autre. Les métriques centrales de
RAGAS (*faithfulness*, *answer relevancy*, *context recall*) exigent une réponse ou un
contexte attendus. Il faudrait donc les **écrire nous-mêmes**, puis noter nos réponses
contre nos propres attendus : corriger sa propre copie.

**3. Ces métriques sont elles-mêmes jugées par un LLM, donc non déterministes — sur
`n = 8`.** Le sous-ensemble `reference_exacte` compte huit questions. Une métrique dont deux
exécutions ne donnent pas le même chiffre introduirait une variance du même ordre que le
gain à démontrer. Q5 §6 exige au contraire de figer les versions, la graine et l'ordre de
parcours : un juge probabiliste va exactement contre.

**4. L'architecture a déjà retiré le besoin.** C'est le point à défendre en soutenance :

| Ce qu'un évaluateur mesurerait | Pourquoi c'est sans objet ici |
|---|---|
| *faithfulness* — la réponse est-elle fidèle aux sources ? | la **citation n'est pas rédigée par le modèle**, elle est construite en Python depuis les métadonnées ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §1). Elle est exacte par construction — il n'y a rien à vérifier après coup |
| *context precision / recall* | c'est Hit@1 et Recall@5, calculés sur `attendu_*` |
| le refus est-il justifié ? | le contrat de sortie porte un `code` — `hors_corpus`, `contexte_insuffisant`, ou une réponse. Comparaison de chaînes |
| la réponse suffit-elle ? | la **garde de suffisance** ([`Q4`](../docs/conception/1-rag-avance/Q4.md) §5) est *dans* le pipeline, en sortie structurée, pas dans l'évaluateur |

Un pipeline où la citation est générée par le modèle *a besoin* d'un évaluateur de fidélité.
Celui-ci n'en a pas besoin parce qu'il ne peut pas mentir sur ses sources.

> **Ce qu'on écrit dans le rapport**, plutôt que de faire semblant de ne pas connaître ces
> outils : les évaluateurs de RAG ont été examinés et écartés, avec ces quatre raisons. Un
> outil écarté pour une raison mesurée vaut mieux qu'un outil branché sans raison.

**La seule chose qui pourrait faire revenir la question** : si le brief demandait de noter
la *qualité rédactionnelle* des réponses. Il ne le demande pas — E1 porte sur la citation et
le refus, E6 sur le gain de la recherche. Les deux sont structurels et déterministes.

## Conséquence sur le code à écrire

**La recherche prend sa collection et sa stratégie en paramètres, jamais en constantes.**
C'est la seule décision d'architecture qu'impose ce protocole, et elle se prend à l'étape 2 :
si elle est prise, chaque axe de mesure coûte un drapeau ; si elle ne l'est pas, il faudra
rouvrir la recherche à l'étape 3, au moment précis où il faudra la rejouer à l'identique.

## Renvois

- protocole normatif : [`Q5`](../docs/conception/1-rag-avance/Q5.md)
- refus et seuils : [`Q4`](../docs/conception/1-rag-avance/Q4.md) §3 et §6
- étages de recherche, RRF, départage : [`Q3`](../docs/conception/1-rag-avance/Q3.md)
- texte indexé et nettoyage : [`Q2`](../docs/conception/1-rag-avance/Q2.md) §2
- filtre de version et éditions courantes : [`Q1`](../docs/conception/1-rag-avance/Q1.md) §5
