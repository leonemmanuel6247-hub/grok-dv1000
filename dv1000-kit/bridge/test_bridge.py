#!/usr/bin/env python3
"""
test_bridge.py — Tests hors-ligne du serveur de référence.

Vérifie : extraction tool_call (formats + validation + refus), delta, sessions
(prompt système une seule fois), réponses OpenAI (tool_calls vs stop), SSE,
et un round-trip HTTP complet avec une "extension" factice sur TCP 8091.

Usage : python3 test_bridge.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "nemapi-firefox-server.py")
COMPAT_FILE = os.path.normpath(os.path.join(HERE, "..", "..", "rules", "grok-json-compat-retry.md"))

import importlib.util
_spec = importlib.util.spec_from_file_location("nemapi_firefox_server", SERVER)
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


def frame(obj: dict) -> bytes:
    data = json.dumps(obj, ensure_ascii=False).encode()
    return len(data).to_bytes(4, "big") + data


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


CAPTURED = []

def fake_extension(replies, ready: threading.Event, stop: threading.Event):
    """Extension factice : répond dans l'ordre aux `len(replies)` prompts TCP."""
    if isinstance(replies, str):
        replies = [replies]
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(("127.0.0.1", 8091))
    lsock.listen(len(replies) + 1)
    ready.set()
    for reply_content in replies:
        if stop.is_set():
            break
        conn, _ = lsock.accept()
        conn.settimeout(10)
        head = recv_exact(conn, 4)
        n = int.from_bytes(head, "big")
        req = json.loads(recv_exact(conn, n).decode())
        assert req["type"] == "prompt"
        CAPTURED.append(req)
        resp = {"type": "response", "id": req["id"],
                "content": reply_content, "error": None}
        conn.sendall(frame(resp))
        conn.close()
    lsock.close()


def post(payload: dict, port: int = 8090, path: str = "/v1/chat/completions"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def test_clean_tool_call():
    tools = ["read_file", "write_file", "run_command"]
    raw_fence = 'Bien sûr ! Voici la lecture:\n```json\n{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n```\nVoilà.'
    tc = srv.clean_tool_call(raw_fence, tools)
    assert tc == {"name": "read_file", "arguments": {"path": "/tmp/x"}}, tc

    raw_tag = '<tool_call>{"name":"write_file","arguments":{"path":"a","content":"b"}}</tool_call>'
    tc = srv.clean_tool_call(raw_tag, tools)
    assert tc["name"] == "write_file" and tc["arguments"]["content"] == "b"

    raw_raw = 'blah {"name": "run_command", "arguments": {"cmd": "ls"}} blah'
    tc = srv.clean_tool_call(raw_raw, tools)
    assert tc["name"] == "run_command"

    raw_invalid = '{"name": "rm_rf_everything", "arguments": {}}'
    assert srv.clean_tool_call(raw_invalid, tools) is None   # refusé: hors liste

    raw_badjson = 'pas de json du tout'
    assert srv.clean_tool_call(raw_badjson, tools) is None

    raw_str_args = '{"name": "read_file", "arguments": "{\\"path\\": \\"/tmp/y\\"}"}'
    tc = srv.clean_tool_call(raw_str_args, tools)
    assert tc["arguments"]["path"] == "/tmp/y"

    print("PASS clean_tool_call")


def test_delta_and_first():
    msgs = [{"role": "system", "content": "you are..."},
            {"role": "user", "content": "bonjour"}]
    assert srv.is_first_turn(msgs) is True
    d = srv.delta_messages(msgs)
    assert all(m["role"] != "system" for m in d)
    msgs2 = msgs + [{"role": "assistant", "content": "..."},
                    {"role": "tool", "name": "read_file", "content": "data"}]
    assert srv.is_first_turn(msgs2) is False
    d2 = srv.delta_messages(msgs2)
    assert any(m["role"] == "tool" for m in d2)
    print("PASS delta/first")


def test_roundtrip():
    CAPTURED.clear()
    reply = ('Réponse :\n```json\n{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n```\n'
             'Le reste est jeté.')
    ready, stop = threading.Event(), threading.Event()
    th = threading.Thread(target=fake_extension, args=(reply, ready, stop), daemon=True)
    th.start()
    assert ready.wait(5)

    env = dict(os.environ)
    env["GROK_BRIDGE_PORT"] = "8091"
    env["NEMAPI_PORT"] = "8099"          # port de test distinct
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat",
                            "conversation_id": "test-conv-1",
                            "messages": [{"role": "user", "content": "lis /tmp/x"}],
                            "tools": [{"type": "function",
                                       "function": {"name": "read_file",
                                                    "parameters": {"type": "object"}}}]},
                           port=8099)
        assert status == 200, out
        msg = out["choices"][0]
        assert msg["finish_reason"] == "tool_calls", out
        tc = msg["message"]["tool_calls"][0]
        assert tc["function"]["name"] == "read_file"
        args = json.loads(tc["function"]["arguments"])
        assert args == {"path": "/tmp/x"}
        print("PASS roundtrip tool_calls")

        with urllib.request.urlopen("http://127.0.0.1:8099/v1/models", timeout=5) as r:
            models = json.loads(r.read().decode())
        assert any(m["id"] == "deepseek-chat" for m in models["data"])
        print("PASS /v1/models")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_speech_thought_roundtrip():
    ready, stop = threading.Event(), threading.Event()
    threading.Thread(target=fake_extension,
                     args=('{"name":"thought","arguments":{"text":"analyse interne"}}',
                           ready, stop), daemon=True).start()
    assert ready.wait(5)
    env = dict(os.environ)
    env["GROK_BRIDGE_PORT"] = "8091"
    env["NEMAPI_PORT"] = "8095"
    env["GROK_BRIDGE_COMPAT_FILE"] = COMPAT_FILE
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat", "conversation_id": "speech-test",
                            "messages": [{"role": "user", "content": "bonjour"}],
                            "tools": [{"type": "function", "function": {"name": "read_file"}}]},
                           port=8095)
        assert status == 200, out
        choice = out["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["content"] == "analyse interne"
        print("PASS thought channel")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ready, stop = threading.Event(), threading.Event()
    threading.Thread(target=fake_extension,
                     args=('{"name":"speech","arguments":{"text":"Réponse directe"}}',
                           ready, stop), daemon=True).start()
    assert ready.wait(5)
    env["NEMAPI_PORT"] = "8095"
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat", "conversation_id": "speech-test-2",
                            "messages": [{"role": "user", "content": "bonjour"}],
                            "tools": [{"type": "function", "function": {"name": "read_file"}}]},
                           port=8095)
        assert status == 200, out
        choice = out["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["content"] == "Réponse directe"
        print("PASS speech channel")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_compat_retry_recovers_then_fails():
    # 1) réessai gagnant : 1re réponse invalide, 2e valide -> tool_calls
    CAPTURED.clear()
    ready, stop = threading.Event(), threading.Event()
    replies = ['du baratin sans aucune structure exploitable',
               '```json\n{"name":"read_file","arguments":{"target_file":"/tmp/retry"}}\n```']
    threading.Thread(target=fake_extension, args=(replies, ready, stop), daemon=True).start()
    assert ready.wait(5)
    env = dict(os.environ)
    env["GROK_BRIDGE_PORT"] = "8091"
    env["NEMAPI_PORT"] = "8089"
    env["GROK_BRIDGE_COMPAT_FILE"] = COMPAT_FILE
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat", "conversation_id": "retry-test",
                            "messages": [{"role": "user", "content": "lis /tmp/retry"}],
                            "tools": [{"type": "function",
                                       "function": {"name": "read_file",
                                                    "parameters": {"type": "object",
                                                                   "properties": {"target_file": {"type": "string"}}}}}]},
                           port=8089)
        assert status == 200, out
        choice = out["choices"][0]
        assert choice["finish_reason"] == "tool_calls", out
        assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"target_file": "/tmp/retry"}
        assert len(CAPTURED) == 2, CAPTURED
        assert "correction obligatoire" in json.dumps(CAPTURED[1]["delta"], ensure_ascii=False)
        print("PASS compat retry recovered")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # 2) réessai perdant : 2 réponses invalides -> stop + texte, 2 prompts capturés
    CAPTURED.clear()
    ready, stop = threading.Event(), threading.Event()
    replies = ['toujours pas de json ici', 'encore pas de json']
    threading.Thread(target=fake_extension, args=(replies, ready, stop), daemon=True).start()
    assert ready.wait(5)
    env["NEMAPI_PORT"] = "8089"
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat", "conversation_id": "retry-fail",
                            "messages": [{"role": "user", "content": "lis /x"}],
                            "tools": [{"type": "function", "function": {"name": "read_file"}}]},
                           port=8089)
        assert status == 200, out
        choice = out["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert len(CAPTURED) == 2, CAPTURED
        print("PASS compat retry gives up cleanly")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_text_fallback_roundtrip():
    CAPTURED.clear()
    reply = ["Voici une réponse explicative purement textuelle, aucun outil.",
             "Toujours que du texte, pas de JSON."]
    ready, stop = threading.Event(), threading.Event()
    th = threading.Thread(target=fake_extension, args=(reply, ready, stop), daemon=True)
    th.start()
    assert ready.wait(5)

    env = dict(os.environ)
    env["GROK_BRIDGE_PORT"] = "8091"
    env["NEMAPI_PORT"] = "8098"
    env["GROK_BRIDGE_COMPAT_FILE"] = COMPAT_FILE
    proc = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        time.sleep(2.0)
        status, out = post({"model": "deepseek-chat",
                            "conversation_id": "test-conv-2",
                            "messages": [{"role": "user", "content": "bonjour"}],
                            "tools": [{"type": "function",
                                       "function": {"name": "read_file"}}]},
                           port=8098)
        assert status == 200, out
        msg = out["choices"][0]
        assert msg["finish_reason"] == "stop", out
        assert msg["message"]["content"] == "Toujours que du texte, pas de JSON.", out
        assert len(CAPTURED) == 2, CAPTURED
        print("PASS roundtrip text fallback")
    finally:
        proc.terminate(); stop.set()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    test_clean_tool_call()
    test_delta_and_first()
    test_roundtrip()
    test_speech_thought_roundtrip()
    test_compat_retry_recovers_then_fails()
    test_text_fallback_roundtrip()
    print("TOUS LES TESTS PASSENT")
