# Bridge de référence — SERVEUR (8090) + HÔTE NATIF (8091)

Implémentation de référence, **stdlib-only**, du serveur OpenAI du pont et de
l'hôte natif `nativeMessaging`. Elle applique les parties **1 (SERVEUR)** et
**2 (PONT/SESSIONS)** de `../PONT-AMELIORATIONS.md`. L'extension `content.js`
est hors périmètre (le site peut changer ses sélecteurs sans préavis).

> ⚠️ Ce sont des **références à installer/adapter**, pas un patch du fichier
> `nemapi-firefox-server.py` de TON paquet `firefox-addon` (absent de ce
> dépôt). Si ton pont existe déjà, reprends-y les mêmes fonctions ; sinon,
> ce répertoire est un serveur complet prêt à l'emploi.

## Contenu

| Fichier | Rôle |
|---------|------|
| `nemapi-firefox-server.py` | Serveur OpenAI 127.0.0.1:**8090** — chat/completions, models, health, `/reset`, sessions delta-only, extraction/validation des tool_calls, audit JSONL |
| `grok-bridge-host.py` | Hôte natif — TCP 127.0.0.1:**8091** ↔ stdin/stdout `nativeMessaging` (frames uint32 LE) |
| `test_bridge.py` | Tests hors-ligne (extraction, delta, sessions, round-trip avec extension factice, refus d'outils non déclarés) |
| `com.grokbuild.bridge.json.example` | Exemple de manifest native messaging (chemin à adapter) |
| `logs/bridge-host.log` | Audit JSONL (créé à l'exécution) — tool_calls nettoyés, arguments **hashés**, jamais en clair |

## Boucle complète

```
grok CLI --HTTP--> 127.0.0.1:8090        (nemapi-firefox-server.py)
          --TCP---> 127.0.0.1:8091        (grok-bridge-host.py)
          --nativeMessaging--> extension Firefox --> content.js --> onglet web
```

## Contrat filaire TCP 8091

Serveur → hôte (frame = uint32 **big-endian** + JSON UTF-8) :

```json
{"type":"prompt","id":"<hex>","model":"deepseek-chat","reset":true,
 "first":true,
 "delta":[{"role":"system","content":"…(UNE FOIS)"},
          {"role":"user","content":"…(dernier message uniquement)"}],
 "tools":["read_file","write_file"]}
```

Hôte → serveur (même `id`) :

```json
{"type":"response","id":"<hex>","content":"…texte possiblement sale…",
 "error":null}
```

`error` ∈ `null | native_unreachable | no_provider_tab | timeout | …`.

## Ce qui est implémenté (checklist spec)

SERVEUR (partie 1) :
- [x] Liste `tools` de chaque requête conservée (noms valides)
- [x] Extraction du **premier** JSON d'outil valide : ```json fence → `<tool_call>` → objet `{…}` équilibré
- [x] Tout le reste (prose, Markdown, justificatifs) est **jeté**
- [x] Validation stricte : `name` ∈ `tools` reçus, sinon `finish_reason:"stop"` — **jamais** d'outil inventé
- [x] `arguments` parsés (string JSON acceptée) ; non-dict → rejet → fallback texte
- [x] Sortie OpenAI propre : `arguments` = **string JSON**, `content:null`, `finish_reason:"tool_calls"` ; sinon `stop` + texte nettoyé
- [x] Rôle `tool` entrant réinjecté préfixé `[tool: <nom>]`
- [x] SSE : chunk delta → chunk `finish_reason` → `data: [DONE]` (jamais `[DONE]` avant le tool_call)
- [x] Audit `logs/bridge-host.log` (nom d'outil + SHA-256 des arguments, jamais les arguments en clair)
- [x] Refus des outils non déclarés (candidat rejeté, fallback texte)

PONT/SESSIONS (partie 2) :
- [x] Prompt système **une seule fois** par conversation (clé = `conversation_id` / `x-grok-conv-group-id` / `x-conversation-id`, sinon `model:<id>`)
- [x] **Delta uniquement** : system/developer exclus, blocs `image_url` aplatis en `[image]`, messages `tool` conservés préfixés
- [x] Reset explicite : `POST /reset {conversation_id}` (ou sans corps → toutes les sessions) → le prochain tour renverra le prompt système

Hors périmètre (par décision) : extension `content.js` (reset UI, bouton « nouveau chat ») — voir partie 3 de `../PONT-AMELIORATIONS.md`.

## Installer / lancer la référence

```bash
cd dv1000-kit/bridge

# 1) Hôte natif + manifest (adapter le chemin absolu !)
mkdir -p ~/.mozilla/native-messaging-hosts
sed "s|__BRIDGE_HOST_PATH__|$PWD/grok-bridge-host.py|g" \
    com.grokbuild.bridge.json.example \
    > ~/.mozilla/native-messaging-hosts/com.grokbuild.bridge.json
chmod +x grok-bridge-host.py nemapi-firefox-server.py

# 2) Terminal A : hôte natif (Firefox le lance normalement tout seul en
#    nativeMessaging ; l'exemple couvre le mode TCP manuel/test)
# python3 grok-bridge-host.py          # écoute 127.0.0.1:8091

# 3) Terminal B : serveur OpenAI
python3 nemapi-firefox-server.py       # écoute 127.0.0.1:8090

# 4) Firefox (profil du pont) + onglet fournisseur ouvert/connecté
firefox --profile "$HOME/.mozilla/firefox/grokbuild"

# 5) Vérifications
curl -s http://127.0.0.1:8090/health
curl -s http://127.0.0.1:8090/v1/models
curl -s http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-chat","conversation_id":"demo-1",
       "messages":[{"role":"user","content":"lis /tmp/x"}],
       "tools":[{"type":"function","function":{"name":"read_file","parameters":{"type":"object"}}}]}'

# 6) Reset d'une conversation (force le prompt système au prochain tour)
curl -s -X POST http://127.0.0.1:8090/reset -H 'Content-Type: application/json' \
  -d '{"conversation_id":"demo-1"}'
```

Variables d'environnement : `NEMAPI_PORT` (8090), `GROK_BRIDGE_HOST` (127.0.0.1),
`GROK_BRIDGE_PORT` (8091), `GROK_BRIDGE_TIMEOUT` (660 s),
`GROK_BRIDGE_SYSTEM_FILE` (`~/.grok/rules/grok-bridge-system.md`),
`GROK_BRIDGE_LOG` (`logs/bridge-host.log`).

## Tests hors-ligne (aucune dépendance)

```bash
python3 dv1000-kit/bridge/test_bridge.py
```

Couvre : extraction (fence/tag/JSON équilibré/`{"function":…}`/string-arguments),
refus d'outil non déclaré, fallback texte, delta/`is_first_turn`, round-trip
HTTP complet avec une « extension » factice sur TCP 8091 (cas tool_calls et
cas texte), `/v1/models`.

## Limites connues

- Le canal DOM → serveur est un relais : si l'onglet est fermé/déconnecté,
  l'hôte renvoie `native_unreachable` (502) ou `timeout` (504) ; rien n'est inventé.
- Le `usage` est à 0 (le site web ne facture pas de tokens).
- La clé `NEMAPI_API_KEY` n'est pas vérifiée côté pont (canal local factice) —
  ne pas exposer le port 8090 hors de localhost.
