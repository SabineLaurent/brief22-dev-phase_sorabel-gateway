# Déployer la gateway sur Azure Container Apps — le pas-à-pas réel

Ce document décrit **ce qui a été fait le 2026-09-09/10**, pas une procédure idéale : les
commandes sont celles qui ont réellement tourné, y compris celles de vérification, et les
cinq obstacles rencontrés sont à leur place dans la séquence — parce que chacun coûte du
temps la première fois et rien la seconde.

Le raisonnement, les arbitrages et les mesures vivent dans `docs/journal-developpement.md`
à la même date. Les défauts sont indexés dans `docs/BUGS.md` §11 sous `DEP-01` à `DEP-05`.

**Ce qui est déployé, et l'URL du livrable :**

```
https://sorabel-web-demo-sabl.delightfulpond-41840da3.francecentral.azurecontainerapps.io
```

---

## 0. L'architecture, en une image

```
sorabel-web-demo-sabl       Chainlit          ingress EXTERNE   port 8100  ← l'URL
        │ SORABEL_API_URL=http://sorabel-gateway-demo-sabl
sorabel-gateway-demo-sabl   API + MCP stdio   ingress INTERNE   port 8000
        │ CHROMA_URL=http://sorabel-chroma-demo-sabl
sorabel-chroma-demo-sabl    Chroma + index    ingress INTERNE   port 8002
```

**Trois apps, pas un sidecar.** Le sidecar aurait fait parler les conteneurs en
`localhost:8002` ; la répétition locale (`docker-compose.aca.yml`) a validé la version
« hostnames distincts ». On ne déploie pas une variante non testée.

**Le serveur MCP n'est pas une app.** Il parle en stdio, donc sans port ni adresse : c'est un
**sous-processus** de l'API, lancé à la demande, un par profil. C'est pourquoi la machinerie
backend est une seule image.

---

## 1. Prérequis — la machine de construction, pas un clone

**Le build ne peut PAS partir d'un clone propre.** Trois artefacts sont gitignorés et
nécessaires :

| artefact | comment il existe | pourquoi il n'est pas reconstruit |
|---|---|---|
| `.docker-data/chroma` (33 Mo) | `make ingest` | c'est le **référent de la calibration** — le rebâtir invalide le seuil en silence |
| `data/bm25/*.pkl` | `make ingest` | reconstruire passe par la même passe Azure, pour 300 Ko |
| `data/sorabel.db` | `make seed` | **celui-là est reconstruit dans l'image** : déterministe (graine 8842) |

Vérifier avant de construire :

```bash
ls .docker-data/chroma data/bm25/ data/sorabel.db
```

---

## 2. Construire les images — **`--platform linux/amd64`**

> **DEP-01.** `docker build` sur un Mac Apple Silicon produit du `linux/arm64` ; Container
> Apps exécute du `linux/amd64`. Sans le drapeau, les images se poussent puis refusent de
> démarrer, avec un message d'exécution sans rapport apparent avec l'architecture.

```bash
docker build --platform linux/amd64 -t acrsablvelmo.azurecr.io/sorabel-chroma:v1 -f Dockerfile.chroma .
docker build --platform linux/amd64 -t acrsablvelmo.azurecr.io/sorabel-app:v1 .
```

**Vérifier l'architecture avant de pousser** — c'est deux secondes et ça évite un aller-retour :

```bash
for i in acrsablvelmo.azurecr.io/sorabel-chroma:v1 acrsablvelmo.azurecr.io/sorabel-app:v1; do
  echo "$i : $(docker image inspect $i --format '{{.Os}}/{{.Architecture}}')"
done
```

Attendu : `linux/amd64` pour les deux. Tailles obtenues : chroma **146 Mo**, app **312 Mo**.

**Vérifier que l'image est saine**, toujours avant le push :

```bash
docker run --rm --platform linux/amd64 acrsablvelmo.azurecr.io/sorabel-app:v1 sh -c '
  test ! -e /app/.env && echo "aucun .env : OK"
  python -c "from config import settings, REPO_ROOT; print(REPO_ROOT, settings.sorabel_db, settings.gateway_journal)"
'
```

Attendu : `/app /app/data/sorabel.db /app/logs/journal.jsonl` — **absolus**. Un chemin relatif
ici signifie qu'un `.env` s'est glissé dans l'image (cf. `.dockerignore`).

---

## 3. Pousser vers le registre

Le portail ACR **n'a pas d'upload** : le transfert d'images passe forcément par un terminal.
`az` n'est pas nécessaire — les identifiants admin suffisent (`ACR` → `Paramètres` →
`Clés d'accès` → activer *Utilisateur administrateur*).

```bash
docker login acrsablvelmo.azurecr.io -u <utilisateur> -p <mot-de-passe>
docker push acrsablvelmo.azurecr.io/sorabel-chroma:v1
docker push acrsablvelmo.azurecr.io/sorabel-app:v1
```

**Régénérer le mot de passe après coup** si la commande a transité par un canal partagé.
Container Apps ne s'en sert pas : le portail crée une **identité managée** avec le rôle
*AcrPull* (visible sous le nom `AcrPullRoleAssignmentDeployment` au déploiement).

Vérifier ce que le registre contient, sans rien y écrire :

```bash
for t in v1 v2; do
  echo -n "sorabel-app:$t → "
  docker manifest inspect acrsablvelmo.azurecr.io/sorabel-app:$t >/dev/null 2>&1 && echo présente || echo absente
done
```

---

## 4. `sorabel-chroma-demo-sabl` — la première app

Au portail : `Créer une ressource` → **App conteneur** (pas « Travail d'app conteneur », qui
est fait pour des tâches qui se terminent et n'a pas d'ingress).

**Général** — créer l'environnement au passage :

| champ | valeur |
|---|---|
| environnement | `cae-sorabel-demo-sabl`, **Consommation uniquement** |
| région | celle du **Foundry** — c'est là que partent les appels à chaque question |
| Log Analytics | `log-sabl-sorabel-dev-001` |

**Conteneur** — décocher « image de démarrage rapide », source *Azure Container Registry*,
image `sorabel-chroma`, étiquette `v1`, **commande et arguments vides** (l'image officielle a
son point d'entrée), 0,5 UC / 1 Gio.

**Entrée** — activée, **limitée à l'environnement**, HTTP, Auto, **port 8002**, pas
d'affinité.

> Le port 8002 vient de l'image : `Dockerfile.chroma` pose `CHROMA_HOST_PORT=8002`. On déplace
> Chroma plutôt que l'API pour que `chroma_url` garde son défaut `http://localhost:8002` et que
> la configuration déployée soit identique à celle du poste.

**Après création** : `Mettre à l'échelle` → min **1**, max **1**, puis `Enregistrer en tant que
nouvelle révision`. Sans ça l'app descend à zéro et la première question paie son démarrage.

**Vérifier** — `Surveillance` → `Flux de journaux`, catégorie **Application** (et non
« Système », qui ne montre que l'orchestrateur) :

```
Starting 'uvicorn chromadb.app:app' with args: --workers 1 --host 0.0.0.0 --port 8002
Starting component SqliteDB / LocalSegmentManager / SegmentAPI
Uvicorn running on http://0.0.0.0:8002
```

Les trois composants confirment que **l'index embarqué dans l'image est lu**.

---

## 5. `sorabel-gateway-demo-sabl` — l'API et ses sous-processus

### 5.1 Les secrets, d'abord

`Paramètres` → `Secrets` → `+ Ajouter`, type **Secret Container Apps** (pas « Référence Key
Vault », qui suppose un coffre provisionné et une identité managée) :

| nom du secret | valeur |
|---|---|
| `azure-ai-api-key` | `AZURE_AI_API_KEY` du `.env` |
| `azure-rerank-api-key` | `AZURE_RERANK_API_KEY` du `.env` |

### 5.2 Créer l'app

Image `sorabel-app` **`v1`**, **1 UC / 2 Gio** (mesuré : 409 Mio avec quatre sous-processus
MCP), entrée **interne** port **8000**, pas d'affinité, échelle 1/1.

### 5.3 Les dix variables

Huit en clair, deux en **référence au secret** :

```
CHROMA_URL                  http://sorabel-chroma-demo-sabl
CHROMA_COLLECTION           sorabel_corpus_azure_small
AZURE_EMBEDDING_DEPLOYMENT  text-embedding-3-small
AZURE_RERANK_DEPLOYMENT     Cohere-rerank-v4.0-pro
RERANK_THRESHOLD            0.6203
AZURE_AI_ENDPOINT           https://<ressource>.openai.azure.com/openai/v1
AZURE_RERANK_ENDPOINT       https://<ressource>.services.ai.azure.com/providers/cohere/v2/rerank
LLM_CHAT_MODEL              <le déploiement de chat>

AZURE_AI_API_KEY            → Référencer un secret → azure-ai-api-key
AZURE_RERANK_API_KEY        → Référencer un secret → azure-rerank-api-key
```

> **DEP-02 — ne poser NI `SORABEL_DB` NI `GATEWAY_JOURNAL`.** Sans `.env` dans l'image, les
> défauts de `config.py` sont déjà absolus. Les poser réintroduirait les chemins **relatifs**
> du `.env`, qui ne « marchent » que tant que le CWD vaut `/app`.

> **`secretref:` n'existe qu'en CLI.** Au portail, c'est un **type de champ** : choisir
> *Référencer un secret* et sélectionner le nom **nu** (`azure-ai-api-key`). Saisir
> `secretref:azure-ai-api-key` en valeur manuelle envoie cette chaîne de 26 caractères comme
> clé d'API — et rend un `401 Access denied due to invalid subscription key`.

> **`--set-env-vars` REMPLACE l'ensemble des variables**, il ne les ajoute pas. Une commande
> qui n'en porte que trois efface les sept autres.

### 5.4 La commande et les arguments — **par YAML, pas par le portail**

> **DEP-05.** Le champ « Remplacement des arguments » du portail transmet sa valeur comme **un
> seul argument** : ni les virgules ni les espaces ne la découpent. Mesuré deux fois. Le
> symptôme est `1/1 Container crashing` et, dans les journaux Application :
>
> ```
> ERROR: Error loading ASGI app.
>        Attribute "app --host,0.0.0.0 --port,8000" not found in module "packages.agent.api".
> ```
>
> Le fait que l'attribut contienne **les séparateurs** prouve qu'il n'y a eu aucun découpage.

En YAML, `command` et `args` sont des **listes** — un élément par argument. C'est le seul
endroit qui sait l'exprimer. Dans **Cloud Shell** (icône `>_` du portail, pas besoin
d'installer `az`) :

```bash
az containerapp show -n sorabel-gateway-demo-sabl -g slaurentRG -o yaml > app.yaml

python3 - <<'PY'
import yaml
d = yaml.safe_load(open('app.yaml'))
c = d['properties']['template']['containers'][0]
c['command'] = ['uvicorn']
c['args'] = ['packages.agent.api:app', '--host', '0.0.0.0', '--port', '8000']
yaml.safe_dump(d, open('app.yaml', 'w'), default_flow_style=False, allow_unicode=True)
print('command:', c['command'])
print('args   :', c['args'])
print('env    :', len(c.get('env', [])), 'variables conservées')
PY

az containerapp update -n sorabel-gateway-demo-sabl -g slaurentRG --yaml app.yaml
```

L'export-puis-réécriture **préserve les variables** — le script le confirme avant d'appliquer.

**Bonne nouvelle mesurée** : le portail affiche mal une liste d'arguments mais **ne la détruit
pas** en réenregistrant. On pose la liste une fois par YAML, le reste s'édite au portail.

### 5.5 Vérifier

```bash
az containerapp show -n sorabel-gateway-demo-sabl -g slaurentRG \
  --query "properties.template.containers[0].{image:image, command:command, args:args, nb_env:length(env)}" -o yaml
```

Attendu :

```yaml
image: acrsablvelmo.azurecr.io/sorabel-app:v1
command:
- uvicorn
args:
- packages.agent.api:app
- --host
- 0.0.0.0
- --port
- '8000'
nb_env: 10
```

```bash
az containerapp revision list -n sorabel-gateway-demo-sabl -g slaurentRG \
  --query "[?properties.active].{revision:name, etat:properties.runningState, replicas:properties.replicas}" -o table
```

Attendu : `RunningAtMaxScale`, 1 réplica.

---

## 6. Valider la chaîne — depuis l'intérieur du conteneur

> **`curl`, `wget` et `ps` n'existent pas dans l'image** — `python:3.11-slim` est minimal.
> Toute commande de test qui les utilise échoue avec un `ClusterExecFailure … code: 500`
> opaque. **`httpx` est là**, utilisez-le.

> Un `ClusterExecFailure` survient aussi quand le conteneur **redémarre en boucle** : il n'y a
> alors aucun processus dans lequel ouvrir un shell. C'est un symptôme, pas une panne de la
> console.

Ouvrir un shell :

```bash
az containerapp exec -n sorabel-gateway-demo-sabl -g slaurentRG --command "/bin/sh"
```

**Le catalogue de rôles** — prouve que l'API répond et lit la matrice :

```sh
python -c "import httpx; print(httpx.get('http://localhost:8000/roles').text[:400])"
```

**La chaîne SQL complète** — API → sous-processus MCP → validateur → SQLite → LLM Foundry :

```sh
python -c "import httpx; print(httpx.post('http://localhost:8000/chat', json={'role':'support','question':'Combien de produits actifs ?'}, timeout=180).text[:600])"
```

Obtenu : `"statut":"ok"`, **120 produits**, `ask_database·ok`, avec le `LIMIT 200` injecté par
le validateur.

**La chaîne documentaire** — Chroma en HTTP interne, embeddings `text-embedding-3-small`,
rerank Cohere, seuil 0,6203 :

```sh
python -c "import httpx; print(httpx.post('http://localhost:8000/chat', json={'role':'support','question':'REF-8842'}, timeout=180).text[:700])"
```

Obtenu : la **fiche technique et le stock** dans le même tour — le cumul de `2bis.7`. C'est ce
test qui a tranché `DEP-04` : la redirection HTTPS de l'ingress interne **n'est pas** un
obstacle à l'appel `http://<app>` entre apps du même environnement.

**Le journal métier** — à ne pas confondre avec les journaux stdout du portail, qui ne portent
ni profil ni étage :

```sh
python -c "from config import settings; p=settings.gateway_journal; print(p, '| existe:', p.exists(), '| taille:', p.stat().st_size if p.exists() else 0)"
tail -c 1200 /app/logs/journal.jsonl
```

Chaque ligne porte `profile`, `tool`, `code`, `decision`, `etage`, `blocked_at`, `forbidden`,
`sql`, `n_rows`, `latency_ms`. C'est là qu'un refus se diagnostique — un `perimetre_interdit`
y nomme l'étage (`3`) et ce qui a été refusé.

> **Coller une commande multi-lignes dans Cloud Shell mange souvent la dernière ligne** — donc
> le guillemet fermant. Écrire ces `python -c` **sur une seule ligne**.

`Ctrl+D` pour ressortir.

---

## 7. `sorabel-web-demo-sabl` — le front, et l'URL

Même image **`sorabel-app:v1`** — attention à ne pas sélectionner une image d'un autre projet
présente dans le même registre. 0,5 UC / 1 Gio.

**Entrée** — c'est la seule des trois à être publique :

| | |
|---|---|
| Trafic | **Accepter le trafic de n'importe où** |
| Port cible | **8100** |
| Connexions non sécurisées | **Non autorisé** — le trafic public est forcé en HTTPS |
| **Affinité de session** | **activée** — Chainlit garde `cl.user_session` en mémoire du processus |

Échelle **1/1** : même motif, l'état de session ne survit pas à un changement de réplica.

**Une seule variable** :

```
SORABEL_API_URL   http://sorabel-gateway-demo-sabl
```

**Les arguments, par YAML** comme pour la gateway — et l'occasion de corriger l'image dans le
même passage :

```bash
az containerapp show -n sorabel-web-demo-sabl -g slaurentRG -o yaml > web.yaml

python3 - <<'PY'
import yaml
d = yaml.safe_load(open('web.yaml'))
c = d['properties']['template']['containers'][0]
print('image actuelle :', c['image'])
c['image'] = 'acrsablvelmo.azurecr.io/sorabel-app:v1'
c['command'] = ['chainlit']
c['args'] = ['run', 'packages/web_client/app.py', '--host', '0.0.0.0', '--port', '8100', '--headless']
yaml.safe_dump(d, open('web.yaml', 'w'), default_flow_style=False, allow_unicode=True)
print('image posée    :', c['image'])
print('command:', c['command'])
print('args   :', c['args'])
print('variables      :', [e.get('name') for e in c.get('env', [])])
PY

az containerapp update -n sorabel-web-demo-sabl -g slaurentRG --yaml web.yaml
```

**L'URL du livrable** :

```bash
az containerapp show -n sorabel-web-demo-sabl -g slaurentRG \
  --query properties.configuration.ingress.fqdn -o tsv
```

---

## 8. Ce qu'il faut voir dans le navigateur

| ce qu'on regarde | ce que ça établit |
|---|---|
| le sélecteur propose **cinq rôles** avec leurs droits en clair | `/roles` répond, donc le front joint la gateway |
| l'accueil ouvre sur **Support** | `DEFAULT_ROLE`, exigence du brief |
| **quatre starters** | les chemins d'éval résolvent (`evals.py` en absolu) |
| une référence nue rend **fiche + stock** | les deux domaines, et le cumul `2bis.7` |
| taper `journal` en **Admin** affiche les entrées | `read_feedback()` et son garde-fou de matrice — **E5 démontrée en production** |
| taper `journal` en **Support** refuse | la matrice s'exerce, et la tentative est journalisée |

---

## 9. Les cinq obstacles, en résumé

| | ce qui s'est passé | comment on le voit | remède |
|---|---|---|---|
| **DEP-01** | images `arm64`, Container Apps est `amd64` | l'app ne démarre pas | `--platform linux/amd64`, vérifié avant le push |
| **DEP-02** | `env_file`/`.env` réinjecte des chemins relatifs | `settings.sorabel_db` relatif dans le conteneur | ne pas poser `SORABEL_DB` ni `GATEWAY_JOURNAL` |
| **DEP-03** | `.dockerignore` excluait `eval/rapport_*.md`, qu'un test exige | 11/12 dans le conteneur | `eval/` inclus en entier |
| **DEP-04** | crainte d'une redirection HTTPS sur l'ingress interne | — | **non fondée**, prouvé par la réponse documentaire |
| **DEP-05** | le champ Arguments ne découpe pas | `Error loading ASGI app` en boucle | poser `command`/`args` en **listes**, par YAML |

Plus deux pièges d'outillage : **`secretref:` n'existe qu'en CLI** (au portail c'est un type de
champ), et **`--set-env-vars` remplace** l'ensemble des variables au lieu de les compléter.

---

## 10. Ce qui n'est pas fait, et qui est assumé

**Aucune authentification.** Le rôle est déclaré par le client : n'importe qui ouvrant l'URL
peut choisir `Admin` et lire le journal. L'ingress interne protège la gateway d'un accès
direct, mais c'est du **périmètre réseau**, pas une serrure. La chaîne d'identité (comptes,
JWT, OBO) est hors périmètre du brief, et consignée comme telle.

**Le journal est éphémère.** Il survit à un redémarrage — le conteneur est réutilisé — mais
disparaît au **remplacement** du conteneur, donc à chaque nouvelle révision. Décision assumée :
pas de volume. E5 reste prouvée par `eval/rapport_acces.md`, joué en local.

**Un sous-processus MCP mort n'est pas relancé.** Le rôle concerné échoue alors en 1,7 s avec
une phrase figée et une ligne de journal (`erreur_execution`, `cause=ClosedResourceError`) ; les
autres rôles restent intacts, et un redémarrage de 3 s lève le défaut. Décision motivée dans le
journal du 2026-09-09 : le correctif toucherait la seule machinerie asynchrone que les six
suites ne couvrent pas.

**Le build ne part pas d'un clone propre** (§1). C'est pourquoi il n'est pas branché sur
`quality.yml` — la CI part d'un clone, et rebâtir l'index invaliderait la calibration.
