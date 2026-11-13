# ÉCHEC JSON — message de correction envoyé par le pont après une sortie invalide

> Envoyé par le pont (jamais par l'utilisateur) en réponse automatique à une
> production NON-JSON ou JSON non conforme. À utiliser tel quel comme message
> `role: user` injecté en delta sur la MÊME conversation, avec la même liste
> `tools`. NE PAS modifier la logique : un seul essai
> de correction, puis repli texte.

---

**Production invalide — correction obligatoire.**

Ta réponse précédente n'était PAS un objet JSON unique, parsable et conforme
au contrat. État EXACT de ta production précédente :

1. **Elle est morte et n'a JAMAIS été exécutée.** Aucun outil n'a été appelé,
   aucun fichier n'a été lu ou écrit, aucune commande n'a tourné, aucun résultat
   n'existe dans ma mémoire. Ne construis sur RIEN de ce que tu as émis.
2. **Rien de ton action précédente n'est acquis.** Si tu croyais "avoir fait"
   quelque chose dans ta réponse précédente, c'est faux : il n'a jamais eu lieu.
3. **Ton précédent JSON est un cadavre** : même s'il contenait un nom d'outil
   plausible, il n'a servi à rien. Tu repars de zéro.

Ta tâche maintenant, sans exception :

**Écrire UNE NOUVELLE réponse qui EST UN UNIQUE objet JSON valide**, au format :

```json
{"name": "<nom EXACT>", "arguments": { ... }}
```

Les trois SEULES issues autorisées — choisis-en UNE selon la situation :

**(A) AGIR** — `name` ∈ la liste `tools` que tu reçois à CHAQUE requête,
arguments conformes au schéma de l'outil (clés exactes, types exacts) :

```json
{"name": "read_file", "arguments": {"target_file": "chemin/exact"}}
```

**(B) RÉPONDRE** — si la demande n'exige aucune action, utilise le canal `speech` :

```json
{"name": "speech", "arguments": {"text": "<ta réponse complète, en texte>"}}
```

**(C) RÉFLÉCHIR** — si tu cours vers l'erreur, expose d'abord ton plan avec `thought`
(le contenu est affiché comme simple texte) :

```json
{"name": "thought", "arguments": {"text": "<ton raisonnement, concis>"}}
```

Varier les outils, mode d'emploi :

- Outil plus adapté qu'un autre ? Change de nom d'outil, PAS de format.
  Le format (`{"name", "arguments"}`) ne change JAMAIS ; seul `name` varie,
  et UNIQUEMENT parmi la liste `tools`.
- Mauvais arguments ? Garde le même outil, corrige CLÉS et TYPES selon le
  schéma. Un argument en trop, une clé inventée, un mauvais type = rejet.
- Pas d'outil pertinent ? N'inventes RIEN : bascule sur `speech` (réponse) ou
  `thought` (plan). Ces deux canaux existent pour ça ; s'en servir n'est pas
  une échappatoire, c'est la bonne réponse.
- Besoin d'information avant d'agir ? Utilise l'outil d'inspection le plus
  petit possible (liste, lecture, recherche) plutôt que de spéculer.

Ce qui sera de nouveau REJETÉ (sortie morte encore) :

- Du texte hors du JSON, du Markdown, des balises ``` ou <tool_call>.
- Plusieurs objets JSON. Un JSON avec virgules traînantes ou clés non quotées.
- `arguments` en chaîne au lieu d'objet. Un `name` inconnu ou inventé.
- Des clés d'arguments inventées ou des types incorrects.


Si ta sortie est morte à cause des caractères spéciaux (cause n°1 des échecs) :

- Antislash brut (ex. chemin Windows) → DOUBLÉ : `\\`.
- Guillemet double brut dans une chaîne → `\"`.
- Saut de ligne physique dans la réponse ou dans une chaîne → `\n` ÉCHAPPÉ.
- Caractère spécial douteux → `\uXXXX` en HEXADÉCIMAL (ex. `@` = `\u0040`,
  `#` = `\u0023`). Le décimal n'existe PAS en JSON : `\u064`, `&#64;` = rejet.
- `/ @ # $ €` ne s'échappent PAS du tout : écris-les tels quels.
- Base64 interdit pour une valeur produite par toi (sortie corrompue).

Ordre de remédiation (applique-le mot pour mot) :

1. Relis la liste `tools` qui accompagne CETTE requête.
2. Repère LA famille : agir → (A) ; répondre → (B) ; planifier → (C).
3. Écris l'UNIQUE objet JSON. Valide-le mentalement (parseable ; deux clés
   `name`/`arguments` ; types exacts).
4. Émets-le SEUL, sans un caractère de plus.
