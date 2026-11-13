# Améliorations du pont Firefox — guide d'implémentation

Ce document décrit QUOI changer dans le paquet **firefox-addon** (le pont :
`nemapi-firefox-server.py`, `content.js`, gestion des sessions), qui n'est
**pas dans ce dépôt**. Sans ces changements côté pont, le renforcement du
prompt (rules/grok-bridge-system.md) aide mais ne suffit pas : le CLI
dépend de la propreté formelle du `tool_calls`.

## Rappel de la boucle

```
CLI → (conversation + liste tools) → pont → onglet web
CLI ← (texte OU tool_calls propres) ← pont ← réponse DOM
CLI → (résultats role "tool") → pont → onglet → ...
```

Le maillon fragile est (b) : le modèle web répond en langage naturel autour
du JSON d'outil. Le pont doit **nettoyer**, pas "inventer" le protocole.

## 1. Serveur — `nemapi-firefox-server.py`

Checklist (à intégrer, fonction par fonction) :

1. **Conserver la liste `tools`** de chaque requête (noms valides + schéma).
2. **Consigne de format univoque** envoyée avec la demande à l'onglet :
   « Réponds UNIQUEMENT par UN bloc JSON `{"name": ..., "arguments": {...}}`,
   zéro texte hors JSON ». Un seul bloc demandé, explicitement.
3. **Extraction du premier JSON outil valide** de la réponse DOM, dans
   l'ordre : bloc ```json …```, balises `<tool_call>…</tool_call>`, JSON pur
   (regex robuste sur le premier objet équilibré `{…}`).
4. **JETER tout le reste** : phrases, explications, Markdown, félicitations.
   Règle d'or : SEUL le JSON d'outil traverse, jamais le texte ambiant.
5. **Validation stricte** :
   - `name` ∈ liste `tools` reçue, sinon `finish_reason:"stop"` (ne JAMAIS inventer un outil) ;
   - `arguments` parsés en JSON, types contrôlés contre le schéma de l'outil si connu ;
   - en cas d'ambiguïté → fallback texte (`finish_reason:"stop"`), pas d'invention.
6. **Format de sortie OpenAI propre** :
   ```json
   {"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant","content":null,
     "tool_calls":[{"id":"call_…","type":"function",
       "function":{"name":"…","arguments":"{\"…\":…}"}}]}}]}
   ```
   `arguments` = **string JSON**, pas un objet. `content` = `null` (ou chaîne vide si ton client l'exige).
   Sinon : `finish_reason:"stop"` + texte nettoyé.
7. **Rôle `tool` entrant** : les résultats d'outils renvoyés par le CLI sont
   réinjectés dans l'onglet (bloc étiqueté `tool: <nom>` + contenu) pour que
   le modèle poursuive la boucle.
8. **Streaming** : d'abord les deltas texte ; PUIS un chunk final portant le
   tool_call complet + `finish_reason:"tool_calls"` ; ne pas émettre
   `[DONE]` avant d'avoir transmis les tool_calls.
9. **Audit** : journaliser chaque tool_call nettoyé (nom + arguments hashés)
   dans `logs/bridge-host.log` — jamais les arguments entiers s'ils peuvent
   contenir des secrets.
10. **Refus des outils non déclarés** : tout `name` absent de `tools` est rejeté.

Pseudo-cœur d'extraction :

```python
def clean_tool_call(raw: str, valid_names: set[str]):
    for blob in extract_json_candidates(raw):   # ```json, <tool_call>, {..} équilibré
        try:
            obj = json.loads(blob)
        except Exception:
            continue
        obj = normalize(obj)                    # accepte {"function":{...}} aussi
        name = str(obj.get("name", "")).strip()
        args = obj.get("arguments") if "arguments" in obj else obj.get("input")
        if name in valid_names and args is not None:
            if isinstance(args, str):
                args = json.loads(args)         # arguments en string JSON -> objet
            if isinstance(args, dict):
                return {"name": name, "arguments": args}
    return None                                 # fallback: texte pur, finish_reason stop

def to_openai(tc):
    return {"id": "call_" + uuid4().hex[:24], "type": "function",
            "function": {"name": tc["name"],
                          "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}}
```

## 2. Pont / sessions

1. **Prompt système UNE SEULE FOIS** : table `sessions[cle] -> initialized`.
   Clé = conversation id si présent, sinon `modele + fenêtre temporelle`.
   Premier envoi = prompt système + premier message ; envois suivants = delta.
2. **DELTA seulement** : NE JAMAIS renvoyer l'historique complet à l'onglet —
   le contexte vit déjà dans le site. Moins de trafic, moins de risque
   anti-bot, réponses plus cohérentes.
3. **Nouvelle conversation explicite** : action de reset (bouton
   « nouveau chat ») plutôt que rechargement automatique du contexte.

## 3. Extension — `content.js`

1. Bouton « nouvelle conversation » (reset) déclenché par le pont.
2. Nettoyer la zone de saisie entre deux DELTAS si nécessaire.
3. Laisser le contexte vivre dans l'onglet ; ne pas réinjecter l'historique.

## 4. Prompt système (déjà fait dans ce dépôt)

`rules/grok-bridge-system.md` a été durci : format unique JSON, **interdiction
de toute réponse sans appel d'outil**, envois en delta, une seule
transmission du prompt système. Limites à connaître :

- Interdire toute prose empêche aussi les réponses purement explicatives ;
  c'est exactement ce que tu as demandé — à assumer (le CLI acceptera quand
  même `finish_reason:"stop"` en repli si tu relâches plus tard).
- Le prompt seul ne garantit rien si le site ignore les consignes :
  l'extraction côté serveur (partie 1) reste la ceinture de sécurité.

## 5. Ordre conseillé d'application (firefox-addon)

1. Extraction + validation `tool_calls` (partie 1.3–1.6) — gain immédiat.
2. `finish_reason:"tool_calls"` propre + `[DONE]` après tool_calls (1.8).
3. Sessions une seule fois + delta (partie 2).
4. Reset conversation (3).
5. Audit logging (1.9) et refus des outils non déclarés (1.10).

Après chaque étape, tester avec :

```bash
curl -s http://127.0.0.1:8090/v1/chat/completions \
  -H "Authorization: Bearer $NEMAPI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"lis le fichier /tmp/x"}],
       "tools":[{"type":"function","function":{"name":"read_file","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}}]}' | jq .
```

→ réponse attendue : `finish_reason:"tool_calls"`, un seul tool_call, zéro texte parasite.
