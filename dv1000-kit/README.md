# Kit dv1000 — Grok Build via pont Firefox (NemApi)

Une seule clé (`NEMAPI_API_KEY`), **aucun sous-agent**, toute l'inférence
routée vers l'onglet du fournisseur ouvert dans Firefox.

```
grok CLI --HTTP--> http://127.0.0.1:8090/v1   (serveur du pont)
         --> socket TCP 127.0.0.1:8091        (bridge natif)
         --> nativeMessaging                  (extension Firefox)
         --> content.js écrit dans l'onglet web
         --> réponse lue dans le DOM, remontée au CLI
```

**Condition préalable absolue** : Firefox doit tourner sur le profil du pont
ET l'onglet fournisseur doit être ouvert/connecté AVANT de lancer le CLI.
Sinon : `native_unreachable`.

## Ordre d'installation (dv1000, Debian 12 i386)

```bash
# 1) Config CLI (ici, dans ce dépôt)
cd ~/Téléchargements/grok-build && ./scripts/apply-nemapi-config.sh
#     -> écrit ~/.grok/config.toml + ~/.grok/rules/grok-bridge-system.md

# 2) Clé unique (factice locale)
export NEMAPI_API_KEY=local

# 3) Pont Firefox (paquet firefox-addon, séparé de ce dépôt)
cd ~/Téléchargements/firefox-addon && ./install-firefox.sh
#     -> host natif + profil + extension + serveur 8090

# 4) Firefox sur le profil du pont ; ouvrir LE SITE du modèle, se connecter
firefox --profile "$HOME/.mozilla/firefox/grokbuild"

# 5) Vérifier le pont
curl -s http://127.0.0.1:8090/health

# 6) Test direct
./xai-grok-pager --single "bonjour" --model deepseek-chat

# 7) TUI interactif
./xai-grok-pager

# 8) Arrêt
./stop.sh && fermer Firefox
```

## Fichiers installés et leur rôle

| Fichier | Rôle |
|---------|------|
| `~/.grok/config.toml` | `[models]` (default/web_search/image_description/session_summary/allowed_models/agent_type), `[endpoints]` tous sur `127.0.0.1:8090/v1`, `[auth]` api_key, `[features]` telemetry=false remote_fetch=false write_file=true subagent_model_inheritance=true, et 7 blocs `[model.*]` |
| `~/.grok/rules/grok-bridge-system.md` | Rules scannées TOUJOURS : identité, mono-clé, mono-canal, gestion d'erreurs du pont, comportement code, interdits, style |
| `~/.mozilla/native-messaging-hosts/com.grokbuild.bridge.json` | Host natif (créé par install-firefox.sh) |
| `~/.mozilla/firefox/grokbuild/` | Profil Firefox du pont (créé par install-firefox.sh) |

### Onglets fournisseurs ↔ `--model`

| `--model` | Site |
|-----------|------|
| `deepseek-chat` (défaut) | chat.deepseek.com |
| `qwen-chat` | chat.qwen.ai |
| `claude-chat` | claude.ai |
| `gemini-chat` | gemini.google.com |
| `gpt-chat` | chatgpt.com |
| `kimi-chat` | kimi.com |
| `glm-chat` | chat.z.ai |

Pourquoi les `[model.*]` sont-ils obligatoires ? Le CLI résout `-m/--model`
contre le catalogue **résolu** : `config.toml [model.*]` > prefetched >
défauts compilés. Déclarés ici, les modèles sont valides même absents du
binaire (sinon : `Invalid params: unknown model id`).

## Pièces jointes (images / PDF / DOCX / TXT)

- Format OpenAI : bloc `image_url` (data-URL base64) dans `content`.
- Format étendu : `attachments` = `[{name, mime, data(base64)}]`.
- MIME reconnus : png, jpeg, gif, webp, bmp, pdf, docx, doc, txt, md, csv.
- L'extension convertit base64 → `File` et injecte dans `input[type=file]`
  via DataTransfer, sinon par événements drag & drop.
- Fichiers > ~1 Mo : découpés par le bridge (limite native messaging) puis
  réassemblés côté extension — transparent.
- **Ordre** : attacher les fichiers AVANT d'écrire le texte et d'envoyer.

## Variables d'environnement

| Variable | Rôle | Défaut |
|----------|------|--------|
| `NEMAPI_API_KEY` | clé unique (factice) | aucune |
| `NEMAPI_PORT` | port du serveur OpenAI | 8090 |
| `GROK_BRIDGE_PORT` | socket TCP du bridge natif | 8091 |
| `GROK_BRIDGE_TIMEOUT` | timeout d'une génération (s) | 660 |
| `GROK_BRIDGE_LOG` | log du bridge | logs/bridge-host.log |
| `GROK_FF_PROFILE` | profil Firefox du pont | ~/.mozilla/firefox/grokbuild |
| `GROK_HOME` | racine config CLI | ~/.grok |

## Supprimer / allonger le timeout d'attente de réponse

Aucune recompilation : `GROK_BRIDGE_TIMEOUT` est lu au lancement (défaut 660 s).
Pour pratiquement supprimer l'attente max, exporte une valeur énorme :

```bash
export GROK_BRIDGE_TIMEOUT=86400   # 24 h
```

Si ton bridge accepte la valeur `0` comme « sans limite », `export GROK_BRIDGE_TIMEOUT=0`
convient aussi — le code du bridge n'étant pas dans ce dépôt, la sémantique de `0`
n'est pas garantie ; une valeur très grande marche toujours.

Mémo ordre complet :

```bash
./scripts/apply-nemapi-config.sh
export NEMAPI_API_KEY=local
export GROK_BRIDGE_TIMEOUT=86400
```

Note : un timeout HTTP interne au CLI lui-même (hors pont) serait compilé dans le
binaire et demanderait un patch + rebuild ; ce n'est PAS le cas du timeout du pont.

## Timeout côté CLI (inférence, hors pont)

Le binaire `dv1000` fourni embarque, depuis le commit courant, un **défaut de
600 s relevé à 86400 s** pour le timeout d'attente de réponse de l'inférence
(`resolve_inference_idle_timeout_secs`). Tu peux aussi le fixer par toi-même
sans recompiler, pour un modèle précis ou globalement :

```toml
[models]                         # global, défaut pour tous les modèles
inference_idle_timeout_secs = 86400
# [model.deepseek-chat]          # ou par modèle
# inference_idle_timeout_secs = 86400
```

## Diagnostic rapide

| Symptôme | Cause | Correction |
|----------|-------|-----------|
| `unknown model id` | modèle absent du catalogue | ajouter un bloc `[model.<id>]` (déjà fait pour les 7) |
| `native_unreachable` | pont/Firefox non lancé | `./install-firefox.sh` + ouvrir Firefox + onglet |
| `no_provider_tab` | onglet fournisseur fermé | ouvrir/connecter le site |
| `input_not_found` | sélecteurs du site changés | ajuster `content.js` (extension) |
| `send_button_not_found` | bouton non reconnu | fallback Entree (géré par le pont) |
| `timeout` | génération très longue | augmenter `GROK_BRIDGE_TIMEOUT` |
| version ancienne (1.0.0) | vieux zip / cache Firefox | fermer Firefox + relancer install-firefox.sh |
| fournisseur « aucun » (popup) | aucune requête encore OU mauvais profil | envoyer une requête / bon profil |

## Améliorations du pont (FIREFOX bridge)

État dans CE dépôt :
- `rules/grok-bridge-system.md` — **durci** : format unique JSON de tool_call,
  **interdiction de toute réponse sans appel d'outil**, prompt système une seule
  fois, travail en delta.

À appliquer dans le paquet **firefox-addon** (NON fourni ici) — voir
`dv1000-kit/PONT-AMELIORATIONS.md` :
nettoyage/extraction du premier JSON d'outil, validation des noms contre la liste
`tools` reçue, `finish_reason:"tool_calls"` propre, prompt système une seule fois
par session, envois en delta, streaming texte→tool_calls→[DONE], audit.

## Sécurité / limites

- `NEMAPI_API_KEY=local` est volontairement factice ; ne PAS mettre de vraie
  clé en dur dans un dépôt ni scanner le système.
- Le pont lit/écrit le DOM du site fournisseur : les sélecteurs peuvent se
  casser sans préavis quand le site change.
- Le binaire `xai-grok-pager` fourni est buildé pour i686 (Debian 12),
  avec `stock,sandbox-enforce`. Pas de télémétrie (voir `[features]`).
