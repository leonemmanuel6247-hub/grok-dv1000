#!/usr/bin/env python3
"""
grok-bridge-host.py — Hôte nativeMessaging du pont Firefox (référence).

Rôle : relayer les requêtes entre le serveur OpenAI (127.0.0.1:8091, TCP) et
l'extension Firefox via stdin/stdout (protocole « native messaging » de Firefox :
chaque message = uint32 LE length + JSON UTF-8).

Câblage (via install-firefox.sh, voir README.md du dossier) :
  ~/.mozilla/native-messaging-hosts/com.grokbuild.bridge.json pointe sur ce script.

Protocole relayé tel quel :
  server -> host : {"type":"prompt", ...}        (voir nemapi-firefox-server.py)
  host   -> ext  : même objet (stdin natif)
  ext    -> host : {"type":"response","id":"<même id>","content":"...","error":null}
  host   -> server: même objet (socket TCP 8091)

Le host écoute sur TCP 8091, accepte UNE connexion du serveur, et multiplexe
vers l'extension (stdin/stdout du processus lancé par Firefox) tant que les
deux sont vivants.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading

HOST = os.environ.get("GROK_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("GROK_BRIDGE_PORT", "8091"))

MAX_MSG = 64 * 1024 * 1024


def read_exact(stream, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError("stream closed")
        buf += chunk
    return buf


def native_read(stream) -> dict:
    raw_len = read_exact(stream, 4)
    size = struct.unpack("<I", raw_len)[0]
    if size <= 0 or size > MAX_MSG:
        raise ValueError(f"bad native frame size {size}")
    return json.loads(read_exact(stream, size).decode("utf-8"))


def native_write(stream, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("tcp closed")
        buf += chunk
    return buf


def tcp_read(sock: socket.socket) -> dict:
    head = recv_exact(sock, 4)
    n = int.from_bytes(head, "big")
    if n <= 0 or n > MAX_MSG:
        raise ValueError(f"bad tcp frame size {n}")
    return json.loads(recv_exact(sock, n).decode("utf-8"))


def tcp_write(sock: socket.socket, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(len(data).to_bytes(4, "big") + data)


def main() -> int:
    ext_in, ext_out = sys.stdin.buffer, sys.stdout.buffer

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    log(f"en écoute sur {HOST}:{PORT} — ouvrir Firefox sur le profil pont")

    conn, addr = server.accept()
    log(f"serveur OpenAI connecté depuis {addr}")

    stop = threading.Event()

    def pump_server_to_ext():
        try:
            while not stop.is_set():
                msg = tcp_read(conn)
                native_write(ext_out, msg)
        except (EOFError, OSError, ValueError) as exc:
            log(f"serveur -> extension : {exc}")
            stop.set()

    def pump_ext_to_server():
        try:
            while not stop.is_set():
                msg = native_read(ext_in)
                tcp_write(conn, msg)
        except (EOFError, OSError, ValueError, json.JSONDecodeError) as exc:
            log(f"extension -> serveur : {exc}")
            stop.set()

    t1 = threading.Thread(target=pump_server_to_ext, daemon=True)
    t2 = threading.Thread(target=pump_ext_to_server, daemon=True)
    t1.start(); t2.start()
    try:
        while not stop.is_set():
            t1.join(0.5); t2.join(0.5)
            if not t1.is_alive() and not t2.is_alive():
                break
    except KeyboardInterrupt:
        pass
    log("arrêt.")
    return 0


def log(msg: str) -> None:
    sys.stderr.write(f"[grok-bridge-host] {msg}\n")
    sys.stderr.flush()


if __name__ == "__main__":
    sys.exit(main())
