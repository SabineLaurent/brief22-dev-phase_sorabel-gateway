# Note — Transport et résolution de profil : un catalogue, deux câblages

> **Pourquoi cette note existe.** [Q3](Q3.md) §2 tranche l'origine du profil en s'appuyant
> sur une propriété de **stdio** — « le serveur est un processus lancé par le client » — et
> renvoie le cas HTTP à un paragraphe conditionnel de trois lignes. Or deux des trois clients
> nommés par la note de cadrage DSI, le bot Slack du support et l'IDE des développeurs, ne
> sont pas des postes : stdio ne les sert pas correctement. Cette note traite le transport
> comme une décision de conception à part entière, au lieu d'une hypothèse implicite de Q3.
>
> Les faits d'API cités au §3 viennent du SDK Python MCP (`mcp/server/`), pas de la
> spécification : ils sont vérifiables dans le code du SDK installé.

**Décision : les huit tools forment un catalogue unique, exposé par deux points d'entrée —
stdio pour la démonstration, Streamable HTTP pour les clients de service. Le serveur n'est
pas dupliqué. Deux choses seulement dépendent du transport : la résolution du profil et
l'étage 1 (`tools/list`). Aucune ligne de la matrice ne change.**

## 1. Pourquoi stdio ne suffit pas aux clients réels

E4 dit « un même serveur MCP sert tous les clients internes ». En stdio, « un serveur »
signifie *un binaire, N processus* — un par poste. C'est défendable pour un poste
commercial ; ça ne tient pas pour les deux autres clients :

| Client | Ce que stdio exige de lui | Verdict |
|---|---|---|
| poste des commerciaux | une configuration locale portant `SORABEL_PROFILE` | tient |
| IDE des développeurs | **l'index Chroma et PyTorch installés sur chaque machine** — PyTorch est une dépendance réelle du projet, apportée par le rerank ([../1-rag-avance/Q3.md](../1-rag-avance/Q3.md)) | coûteux |
| bot Slack du support | une configuration **par utilisateur**, qu'un service partagé n'a pas | ne tient pas |

Le bot Slack est le cas dirimant : il n'existe pas d'endroit où accrocher un profil par
utilisateur dans un processus de service. Sous stdio, son profil serait fixé au déploiement
du bot — ce qui est acceptable ici puisque le bot *est* le support, mais cesse de l'être dès
qu'un second client de service porte deux profils.

**Corollaire à ne pas perdre : stdio reste le bon transport pour la démonstration.** Le brief
attend `scripts/mcp_client.py` démontrant deux profils ; une démonstration qui exige un
serveur en marche et un jeton valide n'est pas reproductible par le formateur.

## 2. Ce que la cohabitation coûte : un point d'entrée

La signature du SDK est explicite — `run(transport: Literal["stdio", "sse",
"streamable-http"] = "stdio")` dispatche vers `run_stdio_async()` ou
`run_streamable_http_async()`. Le catalogue de tools est un objet enregistré une fois ;
le transport n'est qu'un choix de flux.

```python
# mcp_server/__main__.py — un catalogue, deux câblages
serveur = construire_serveur()          # les 8 tools, enregistrés une fois
if "--http" in sys.argv:
    serveur.run(transport="streamable-http")
else:
    serveur.run(transport="stdio")
```

C'est la convention des exemples du SDK lui-même : argv nu → stdio, `--http` → serveur ASGI.
**Il n'y a donc pas d'arbitrage à faire entre les deux transports** — c'était l'hypothèse
implicite de Q3 §2, et elle est fausse.

## 3. Le seul code qui diverge

| | stdio | Streamable HTTP |
|---|---|---|
| **`resoudre_profil()`** | lit `SORABEL_PROFILE` — constant pour la vie du processus | vérifie le secret **de cette requête** contre l'annuaire `client → profil` |
| **étage 1 (`tools/list`)** | constant : conforme sans effort | doit suivre l'autorisation de la requête |
| étages 2 et 3 | inchangés | inchangés |
| `matrice.yaml` | inchangée | inchangée |

### Contrainte de signature, à poser maintenant

**`resoudre_profil()` est appelée à chaque appel de tool dans les deux cas** ; l'implémentation
stdio renvoie simplement une constante mémorisée au démarrage.

```python
def resoudre_profil(ctx) -> str:
    """Seule fonction dépendante du transport. Appelée par appel, jamais au démarrage."""
```

Une résolution effectuée *une fois* au démarrage — la lettre de Q3 §2 — produit une signature
qui ne supporte pas HTTP : il faudrait alors rouvrir les huit tools. C'est le seul endroit où
la note anticipe au lieu de constater, et le coût de l'anticipation est un paramètre.

### Ce que l'étage 1 devient en HTTP

La spécification 2026-07-28 encadre le filtrage du catalogue : le jeu de tools
« **MUST NOT** vary per-connection », mais il « **MAY** vary by the authorization presented on
the request — since credentials are per-request input, not connection state ». En Streamable
HTTP chaque requête porte son secret : **filtrer `tools/list` d'après le secret de cette
requête est conforme** ; filtrer d'après un état de processus partagé ne le serait pas.

## 4. Le piège : un en-tête n'est pas une identité

Le SDK expose les en-têtes HTTP au serveur, et son propre docstring porte l'avertissement :

> *« Headers are client-supplied input — never treat one as an identity assertion. »*
> — `mcp/server/.../context.py`, propriété `headers`

C'est mot pour mot l'argument de Q3 §2, déplacé du LLM client vers l'en-tête HTTP. **Un
`X-Sorabel-Profile` serait exactement la panne que Q3 §2 écarte** : le profil redeviendrait
déclaratif, et la matrice décorative. Le profil ne se lit jamais dans un en-tête ; il se
**déduit** d'un secret que le serveur vérifie.

## 5. Ce que HTTP active : l'annuaire déjà prévu

[Q3](Q3.md) §1 sépare deux tables — `client → profil` (l'annuaire, qui bouge) et
`profil → droits` (la matrice, qui est gouvernée). Sous stdio cette séparation est **inerte** :
l'annuaire n'existe nulle part, il est absorbé par la configuration de chaque poste.

Sous HTTP, l'annuaire devient le mécanisme réel :

```yaml
# mcp_server/annuaire.yaml — secrets hors dépôt, référencés par nom d'entrée d'environnement
clients:
  - nom: bot-slack-support     secret_env: SORABEL_SECRET_SLACK   profil: support
  - nom: poste-commercial      secret_env: SORABEL_SECRET_COMM    profil: commercial
  - nom: ide-dev               secret_env: SORABEL_SECRET_DEV     profil: dev
# secret inconnu, absent ou malformé → profil `default`, zéro droit, appel journalisé
```

**Le passage à HTTP ne modifie donc pas la matrice : il active la table que la conception
avait déjà isolée.** C'est la justification rétrospective d'une indirection que le brief
n'exigeait pas — il écrivait « client × tool ».

Trois propriétés à conserver, toutes héritées de Q3 :

1. **comparaison à temps constant** du secret, et jamais de secret dans le dépôt : l'annuaire
   ne porte que le *nom* de l'entrée d'environnement qui le contient ;
2. **`default` reste total** — un secret inconnu produit un refus propre et journalisé, pas une
   trace de pile (Q3 §3) ;
3. **le journal écrit le profil résolu par le serveur**, jamais celui allégué ([Q4](Q4.md) §8) —
   c'est ce qui rend l'audit opposable, et la seule raison pour laquelle « vérifiable » a un
   sens ici.

## 6. Hors périmètre, et assumé comme tel

Ce que cette note **ne** conçoit pas, et qu'un déploiement réel exigerait :

- **OAuth 2.1 / Resource Server.** La spécification en fait la voie normative pour un serveur
  MCP distant. Un secret partagé par application est un raccourci : il authentifie
  l'*application*, pas l'*utilisateur* derrière le bot Slack ;
- **rotation et révocation** des secrets, et TLS de bout en bout ;
- **l'utilisateur derrière un client de service.** Si un jour le support et le commercial
  partagent un même bot, le profil devra suivre l'utilisateur Slack, pas le bot — l'annuaire
  ne suffira plus.

Ces trois points sont hors du périmètre du brief, qui ne demande ni authentification ni
déploiement. Ils sont listés pour que la limite soit nommée plutôt que découverte.

## 7. Comment on sait que c'est tenu

Quatre vérifications, exécutables le jour du développement :

| Vérification | Attendu |
|---|---|
| `python -m mcp_server` puis `scripts/mcp_client.py` | les deux profils démontrés, sans serveur HTTP — le livrable du brief est intact |
| `python -m mcp_server --http` + un appel par secret valide | même réponse que sous stdio, à profil égal |
| appel HTTP **sans secret** ou avec un secret inconnu | `default` : refus sur tout tool, appel journalisé `denied` |
| appel HTTP portant `X-Sorabel-Profile: commercial` avec un secret `support` | droits `support` — l'en-tête est **ignoré**, pas honoré |

Le quatrième est le test qui distingue cette conception d'une conception décorative. Il
appartient au jeu d'acceptance dès que le transport HTTP est livré.

## Renvois

- L'origine du profil et les trois étages — [Q3](Q3.md) §2 et §4.
- Les codes de refus et le journal — [Q4](Q4.md).
- Le filtrage de `tools/list` — [Q2](Q2.md) §8.

## À porter dans les `Qn.md`

1. **Q3 §2** — remplacer « le profil est lu une fois au démarrage » par la contrainte de
   signature du §3 ci-dessus, et renvoyer ici pour le cas HTTP au lieu du paragraphe
   conditionnel actuel ;
2. **Q3 §1** — noter que l'annuaire `client → profil` est inerte sous stdio et devient le
   mécanisme de résolution sous HTTP (§5) ;
3. **Q4** — ajouter le refus `secret_inconnu` (ou rattacher au `default` existant) et vérifier
   que le journal porte bien le profil *résolu*.
