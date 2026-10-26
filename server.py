#!/usr/bin/env python3
"""Run the MCP server locally: python3 server.py [port]  ->  http://localhost:8787/mcp"""
import os
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "_core"))
from http_handler import Handler  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print("voice-profile MCP on http://localhost:%d/mcp" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
