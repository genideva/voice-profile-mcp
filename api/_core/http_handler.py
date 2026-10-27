"""HTTP layer shared by the Vercel function and the local server.

Routes:
  POST /mcp                                   MCP streamable HTTP (JSON responses)
  GET  /.well-known/openai-apps-challenge     domain-verification token (env OPENAI_APPS_CHALLENGE)
  GET  /                                      try-it page for browsers (Accept: text/html), else plain text

Privacy: request bodies are never logged. log_message is silenced so even the
local server prints nothing about requests.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler

import mcp_protocol

MAX_BODY_BYTES = 1_500_000
RATE_PER_MINUTE = 60          # per client address, per running instance; held in memory only
_hits = {}
_DEMO = None


def _demo_page():
    """The try-it page at / for browsers. Same origin as /mcp, so no CORS needed."""
    global _DEMO
    if _DEMO is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.html"), "rb") as f:
            _DEMO = f.read()
    return _DEMO


def _rate_ok(addr):
    now = time.time()
    window = [t for t in _hits.get(addr, []) if now - t < 60]
    if len(window) >= RATE_PER_MINUTE:
        _hits[addr] = window
        return False
    window.append(now)
    _hits[addr] = window
    if len(_hits) > 5000:                     # keep memory bounded
        _hits.clear()
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "voice-profile-mcp"

    def log_message(self, *args):             # never log requests
        pass

    def _send(self, status, body=None, ctype="application/json"):
        data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _path(self):
        return self.path.split("?")[0].rstrip("/") or "/"

    def do_GET(self):
        p = self._path()
        if p == "/.well-known/openai-apps-challenge":
            token = os.environ.get("OPENAI_APPS_CHALLENGE", "").strip()
            return self._send(200 if token else 404, token.encode(), "text/plain")
        if p in ("/", "/api/mcp", "/mcp"):
            if p == "/":
                if "text/html" in (self.headers.get("Accept") or ""):
                    return self._send(200, _demo_page(), "text/html; charset=utf-8")
                return self._send(200, b"voice-profile MCP server. POST JSON-RPC to /mcp. "
                                       b"Source: https://github.com/genideva/voice-profile-mcp\n", "text/plain")
            return self._send(405, {"error": "Use POST for MCP requests."})
        self._send(404, {"error": "Not found"})

    def do_DELETE(self):
        self._send(405, {"error": "No sessions to delete; this server is stateless."})

    def do_POST(self):
        if self._path() not in ("/mcp", "/api/mcp"):
            return self._send(404, {"error": "Not found"})
        addr = (self.headers.get("x-forwarded-for") or self.client_address[0] or "").split(",")[0].strip()
        if not _rate_ok(addr):
            return self._send(429, {"error": "Too many requests. Try again in a minute."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY_BYTES:
            return self._send(413 if n > MAX_BODY_BYTES else 400,
                              {"error": "Body must be 1 to %d bytes." % MAX_BODY_BYTES})
        status, out = mcp_protocol.handle_body(self.rfile.read(n))
        self._send(status, out)
