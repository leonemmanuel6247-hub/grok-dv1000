#!/usr/bin/env python3
"""Minimal local OpenAI-compatible mock for testing the NemApi wiring.

Implements the slice of the OpenAI Chat Completions surface grok-build uses, so
you can validate the client against a local server without loading the real
NemApi browser gateway. Not derived from NemApi's proprietary code.

Endpoints:
  POST /v1/chat/completions
  GET  /v1/models

Run:
  python3 scripts/nemapi-mock.py [port]   (default 8090)
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090

MODELS = [
    {"id": "deepseek-chat", "object": "model", "owned_by": "mock"},
    {"id": "qwen-chat", "object": "model", "owned_by": "mock"},
    {"id": "claude-chat", "object": "model", "owned_by": "mock"},
    {"id": "gemini-chat", "object": "model", "owned_by": "mock"},
    {"id": "gpt-chat", "object": "model", "owned_by": "mock"},
    {"id": "kimi-chat", "object": "model", "owned_by": "mock"},
    {"id": "glm-chat", "object": "model", "owned_by": "mock"},
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models"):
            self._send_json(200, {"object": "list", "data": MODELS})
        else:
            self._send_json(404, {"error": {"message": "not_found", "type": "not_found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid json", "type": "invalid_request"}})
            return
        model = req.get("model", "deepseek-chat")
        messages = req.get("messages", [])
        last = next((m for m in reversed(messages) if m.get("content")), {})
        content = last.get("content", "").strip() or "pong"
        if self.path.rstrip("/").endswith("/v1/chat/completions"):
            self._send_json(
                200,
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "created": 1730000000,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        else:
            self._send_json(404, {"error": {"message": "not_found", "type": "not_found"}})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"NemApi mock listening on http://127.0.0.1:{PORT}/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
