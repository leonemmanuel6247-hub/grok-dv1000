#!/usr/bin/env python3
"""
nemapi-firefox-server.py — Pont local Grok Build (CLI) <-> onglet web via Firefox.

Implémentation de référence du serveur du pont (PARTIE 1+2 du document
"grok-build-firefox-bridge-PROBLEME-AMELIORATIONS.txt"). Python stdlib only.

Flux :
  grok CLI --HTTP--> 127.0.0.1:8090  (ce programme, API OpenAI compatible)
            --> TCP 127.0.0.1:8091   (bridge natif : grok-bridge-host.py)
            --> nativeMessaging --> extension Firefox --> content.js (onglet)

Rôles implémentés :
  1. API OpenAI : GET /health, GET /v1/models, POST /v1/chat/completions
  2. Prompt système ENVOYÉ UNE SEULE FOIS par conversation (table de sessions)
  3. Envoi en DELTA : seuls les nouveaux messages (user / tool) sont relayés
  4. Extraction du premier JSON d'outil valide (```json, <tool_call>, {..} équilibré)
  5. Validation stricte : name dans la liste `tools` reçue, arguments JSON valides
     (sinon finish_reason="stop" — JAMAIS d'invention d'outil)
  6. Sortie OpenAI propre : tool_calls (arguments en string JSON) ou stop
  7. SSE streaming : deltas texte puis chunk(s) tool_calls puis [DONE]
  8. Sessions : POST /reset {conversation_id} pour forcer le prochain prompt système
  9. Audit : log JSONL des tool_calls nettoyés vers logs/bridge-host.log

Contrat FILAIRE TCP 8091 (voir grok-bridge-host.py et README.md du même dossier) :
  -> {"type":"prompt","id":"<uuid>","model":"<id>","reset":bool,
      "delta":[{"role":"user"|"tool","content":"..."}, ...],
      "tools":["name1",...], "first":bool}
  <- {"type":"response","id":"<uuid>","content":"<texte (possiblement sale)>",
      "error": null|"native_unreachable"|"no_provider_tab"|"timeout"|...}

  La liste `tools` envoyée est la liste des NOMS d'outils (pas les schémas) ;
  l'extraction n'exige pas le schéma, seulement l'appartenance à la liste.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_IDS = ["deepseek-chat", "qwen-chat", "claude-chat", "gemini-chat",
             "gpt-chat", "kimi-chat", "glm-chat"]
OWNER = "nemapi-firefox-bridge"

BRIDGE_HOST = os.environ.get("GROK_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("GROK_BRIDGE_PORT", "8091"))
BRIDGE_TIMEOUT = float(os.environ.get("GROK_BRIDGE_TIMEOUT", "660"))
LISTEN = int(os.environ.get("NEMAPI_PORT", "8090"))
SYSTEM_PROMPT_FILE = os.environ.get(
    "GROK_BRIDGE_SYSTEM_FILE",
    os.path.expanduser("~/.grok/rules/grok-bridge-system.md"),
)
AUDIT_LOG = os.environ.get("GROK_BRIDGE_LOG", "logs/bridge-host.log")

_sessions_lock = threading.Lock()
_initialized: set[str] = set()          # conversation_id -> prompt système envoyé
_sessions_lock2 = threading.Lock()


def log_audit(event: dict) -> None:
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG) or ".", exist_ok=True)
        event = {"ts": time.time(), **event}
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_system_prompt() -> str:
    try:
        with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        # Le pont reste fonctionnel sans rules file sur disque ; le système
        # est alors chargé depuis les règles CLI elles-mêmes (déjà en amont).
        return ""


SYSTEM_PROMPT = load_system_prompt()


def conversation_key(body: dict, headers) -> str:
    for cand in (
        body.get("conversation_id"),
        body.get("conv_id"),
        headers.get("x-grok-conv-group-id"),
        headers.get("x-conversation-id"),
    ):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    # Pas d'id fourni : regroupe par modèle (le système n'est renvoyé qu'une fois
    # par modèle, ce qui reste raisonnable pour l'onglet courant).
    return f"model:{body.get('model', 'default')}"


def delta_messages(messages: list[dict]) -> list[dict]:
    """Ne garder que les nouveaux messages utiles (user / tool)."""
    out = []
    for msg in messages:
        role = (msg.get("role") or "").lower()
        if role in ("system", "developer"):
            continue                      # le système est envoyé une seule fois, au 1er tour
        content = msg.get("content")
        if isinstance(content, list):     # format blocs (image_url etc.) -> texte aplatie
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, dict) and block.get("type") == "image_url":
                    parts.append("[image]")
            content = "\n".join(p for p in parts if p)
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        content = content.strip()
        if not content:
            continue
        if role == "tool":
            name = msg.get("name") or "tool"
            content = f"[tool: {name}]\n{content}"
        out.append({"role": role or "user", "content": content})
    return out


def is_first_turn(messages: list[dict]) -> bool:
    users = [m for m in messages if (m.get("role") or "").lower() == "user"]
    tools = [m for m in messages if (m.get("role") or "").lower() == "tool"]
    return len(users) <= 1 and not tools


# --------------------------------------------------------------------------
# Extraction / validation d'un appel d'outil depuis une réponse "sale".
# --------------------------------------------------------------------------
_BALANCED_RE = re.compile(r"\{")

_FENCE_RE = re.compile(r"```(?:json|tool_call)?\s*(\{.*?\})\s*```", re.S | re.I)
_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S | re.I)


def _balanced_objects(text: str):
    for m in _BALANCED_RE.finditer(text):
        depth, start = 0, m.start()
        in_str, esc = False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    break


def _normalize(obj):
    if not isinstance(obj, dict):
        return None
    # {"function": {"name","arguments"}}
    if isinstance(obj.get("function"), dict):
        obj = obj["function"]
    name = obj.get("name")
    args = obj.get("arguments")
    if args is None:
        args = obj.get("input")
    if name is None and isinstance(obj.get("tool"), str):
        name = obj["tool"]
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip(), args


def clean_tool_call(raw: str, valid_names: list[str] | None):
    """Retourne {"name","arguments(dict)"} ou None (fallback -> texte)."""
    valid = set(valid_names or [])
    candidates = []
    candidates += _FENCE_RE.findall(raw)
    candidates += _TAG_RE.findall(raw)
    candidates += list(_balanced_objects(raw))
    for blob in candidates:
        try:
            obj = json.loads(blob)
        except Exception:
            continue
        norm = _normalize(obj)
        if not norm:
            continue
        name, args = norm
        if valid and name not in valid:
            continue                       # refus : outil non déclaré
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                continue
        if args is None:
            args = {}
        if not isinstance(args, dict):
            continue
        return {"name": name, "arguments": args}
    return None


def text_fallback(raw: str) -> str:
    """Retirer le bruit évident et renvoyer le texte utile (mode stop)."""
    txt = re.sub(r"```.*?```", "", raw, flags=re.S)
    txt = re.sub(r"<tool_call>.*?</tool_call>", "", txt, flags=re.S | re.I)
    return txt.strip()


# --------------------------------------------------------------------------
# Bridge TCP <-> native host (grok-bridge-host.py)
# --------------------------------------------------------------------------
class BridgeError(Exception):
    pass


def bridge_request(payload: dict) -> dict:
    req = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=10) as sock:
            sock.sendall(len(req).to_bytes(4, "big") + req)
            sock.settimeout(BRIDGE_TIMEOUT)
            head = _recv_exact(sock, 4)
            if not head:
                raise BridgeError("native_unreachable")
            n = int.from_bytes(head, "big")
            if n <= 0 or n > 64 * 1024 * 1024:
                raise BridgeError("bad_frame")
            data = _recv_exact(sock, n)
            if not data:
                raise BridgeError("native_unreachable")
            return json.loads(data.decode("utf-8"))
    except socket.timeout:
        raise BridgeError("timeout") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"native_unreachable: {exc}") from None


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


# --------------------------------------------------------------------------
# OpenAI payload helpers
# --------------------------------------------------------------------------

def tool_names(tools) -> list[str]:
    names = []
    for t in tools or []:
        if isinstance(t, dict):
            fn = t.get("function") if isinstance(t.get("function"), dict) else {}
            name = fn.get("name") or t.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def openai_response(model: str, content: str = "", tool_call: dict | None = None,
                    finish: str = "stop") -> dict:
    msg: dict = {"role": "assistant"}
    if tool_call:
        msg["content"] = None
        msg["tool_calls"] = [{
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": tool_call["name"],
                         "arguments": json.dumps(tool_call["arguments"], ensure_ascii=False)},
        }]
        finish = "tool_calls"
    else:
        msg["content"] = content
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def sse_chunk(cid: str, model: str, delta: dict, finish: str | None = None) -> bytes:
    chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
             "model": model,
             "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")


def handle_completion(body: dict, headers) -> tuple[int, dict, bool, str]:
    """Renvoie (status, payload, stream?, raw_sse_text)."""
    model = body.get("model", "deepseek-chat")
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return 400, {"error": {"message": "messages requis", "type": "invalid_request_error"}}, False, ""
    stream = bool(body.get("stream", False))
    tools = tool_names(body.get("tools"))

    conv = conversation_key(body, headers)
    first = is_first_turn(messages)
    with _sessions_lock:
        fresh = conv not in _initialized
        if fresh:
            _initialized.add(conv)

    delta = delta_messages(messages)
    # Injecter le prompt système UNE seule fois, dans le delta du 1er tour.
    if fresh and SYSTEM_PROMPT:
        delta = [{"role": "system", "content": SYSTEM_PROMPT}] + delta

    payload = {"type": "prompt", "id": uuid.uuid4().hex, "model": model,
               "reset": fresh, "first": first, "delta": delta, "tools": tools}
    try:
        resp = bridge_request(payload)
    except BridgeError as exc:
        err = str(exc)
        if err.startswith("timeout"):
            code, msg = 504, "timeout"
        else:
            code, msg = 502, "native_unreachable"
        log_audit({"event": "bridge_error", "error": msg, "model": model, "conv": hashlib.sha256(conv.encode()).hexdigest()[:12]})
        return code, {"error": {"message": msg, "type": "bridge_error"}}, False, ""

    raw = (resp or {}).get("content") or ""
    remote_err = (resp or {}).get("error")
    if remote_err:
        msg = str(remote_err)
        if msg == "native_unreachable":
            code = 502
        elif msg == "timeout":
            code = 504
        else:
            code = 502
        log_audit({"event": "bridge_error", "error": msg, "model": model})
        return code, {"error": {"message": msg, "type": "bridge_error"}}, False, ""

    tc = clean_tool_call(raw, tools) if tools else None
    audit = {"event": "tool_call" if tc else "text", "model": model,
             "conv": hashlib.sha256(conv.encode()).hexdigest()[:12]}
    if tc:
        audit["tool"] = tc["name"]
        audit["args_sha256"] = hashlib.sha256(json.dumps(tc["arguments"], sort_keys=True).encode()).hexdigest()
        log_audit(audit)
        return 200, openai_response(model, tool_call=tc), stream, ""
    txt = text_fallback(raw)
    log_audit(audit)
    return 200, openai_response(model, content=txt, finish="stop"), stream, ""


class Handler(BaseHTTPRequestHandler):
    server_version = "nemapi-firefox-server/1.0"

    def log_message(self, *args):
        pass

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path in ("/health", "/v1/health"):
            return self._json(200, {"status": "ok", "sessions": len(_initialized)})
        if path == "/v1/models":
            return self._json(200, {"object": "list",
                                    "data": [{"id": m, "object": "model", "owned_by": OWNER} for m in MODEL_IDS]})
        return self._json(404, {"error": {"message": "not_found", "type": "not_found"}})

    def do_POST(self):
        path = self.path.rstrip("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": {"message": "invalid json", "type": "invalid_request_error"}})

        if path == "/reset":
            conv = body.get("conversation_id") or body.get("model") or ""
            with _sessions_lock:
                before = len(_initialized)
                if conv:
                    _initialized.discard(conv)
                else:
                    _initialized.clear()
            return self._json(200, {"reset": True, "sessions_before": before, "sessions": len(_initialized)})

        if path == "/v1/chat/completions":
            code, payload, stream, _ = handle_completion(body, self.headers)
            if not stream or code != 200:
                return self._json(code, payload)
            # SSE : on émet le contenu en un chunk (le DOM est lu d'un bloc) + [DONE].
            cid = "chatcmpl-" + uuid.uuid4().hex[:24]
            model = payload.get("model", "deepseek-chat")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            choice = payload["choices"][0]
            delta, finish = ({}, choice["finish_reason"])
            if choice["finish_reason"] == "tool_calls":
                delta = {"role": "assistant", "content": None,
                         "tool_calls": choice["message"]["tool_calls"]}
            else:
                delta = {"role": "assistant", "content": choice["message"]["content"]}
            self.wfile.write(sse_chunk(cid, model, delta, None))
            self.wfile.write(sse_chunk(cid, model, {}, finish))
            self.wfile.write(b"data: [DONE]\n\n")
            return

        return self._json(404, {"error": {"message": "not_found", "type": "not_found"}})


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", LISTEN), Handler)
    print(f"nemapi-firefox-server : OpenAI bridge sur http://127.0.0.1:{LISTEN}/v1", flush=True)
    print(f"bridge natif attendu sur {BRIDGE_HOST}:{BRIDGE_PORT} (GROK_BRIDGE_PORT)", flush=True)
    print(f"prompt systeme charge : {SYSTEM_PROMPT_FILE} ({len(SYSTEM_PROMPT)} chars)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\narret.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
