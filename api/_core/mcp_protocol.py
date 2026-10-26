"""Minimal stateless MCP server over streamable HTTP (JSON responses only).

Implements initialize, notifications/*, ping, tools/list and tools/call.
No sessions, no server-sent events, no storage. Each POST is handled on its
own, which is what lets the service promise it keeps nothing.
"""
import json

import voice_tools as vt

SERVER_INFO = {"name": "voice-profile", "version": "0.1.0"}
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = (
    "Voice Profile measures how a person writes from their own pre-AI writing. Use analyze_writing to measure "
    "samples, build_voice_profile to create a profile the user saves, check_draft to score a draft against that "
    "profile, and compare_to_authors to show which public-domain authors their style sits closest to. Only send "
    "writing the user marks as not AI-assisted. The service stores nothing, so give the user the profile to keep."
)
ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The full text of one piece of the user's own writing."},
        "title": {"type": "string", "description": "Short label for the piece, e.g. '2019 conference talk'."},
        "ai_touched": {"type": "string", "enum": ["no", "yes", "unsure"],
                       "description": "The user's answer: did AI help write this? Only 'no' is measured."},
        "register": {"type": "string", "description": "Optional writing-mode label chosen with the user, "
                     "lowercase, e.g. 'argue' or 'reflect'."},
    },
    "required": ["text", "ai_touched"],
}
PROFILE_SCHEMA = {"type": "object", "description": "The 'profile' object returned by build_voice_profile."}

TOOLS = [
    {
        "name": "analyze_writing",
        "title": "Analyze writing",
        "description": "Measure ten surface features of the user's own writing (sentence length and variation, "
                       "short and long sentence shares, contractions, first and second person, questions, paragraph "
                       "length) per sample and overall. Use first, on writing the user produced before using AI. "
                       "With 8+ unlabeled samples it also suggests whether they write in two distinct modes. "
                       "Read-only: nothing is stored.",
        "inputSchema": {"type": "object", "properties": {"samples": {"type": "array", "items": SAMPLE_SCHEMA,
                        "maxItems": vt.MAX_SAMPLES}}, "required": ["samples"]},
        "annotations": ANNOTATIONS,
    },
    {
        "name": "build_voice_profile",
        "title": "Build voice profile",
        "description": "Turn the user's labeled samples into a voice profile: a working range for each feature, "
                       "per writing mode (register), plus a cross-check of how distinct the modes are. Returns the "
                       "profile for the user to save; the service keeps no copy. Use after analyze_writing, once "
                       "registers are agreed with the user.",
        "inputSchema": {"type": "object", "properties": {
            "samples": {"type": "array", "items": SAMPLE_SCHEMA, "maxItems": vt.MAX_SAMPLES},
            "banned": {"type": "array", "items": {"type": "string"},
                       "description": "Optional words or phrases the user never wants in their writing."}},
            "required": ["samples"]},
        "annotations": ANNOTATIONS,
    },
    {
        "name": "check_draft",
        "title": "Check draft",
        "description": "Score a draft against one register of a saved voice profile. Returns pass or fail per "
                       "feature with the direction to move, plus any banned words found. Use when the user asks "
                       "whether a draft sounds like them, or while rewriting a draft into their voice.",
        "inputSchema": {"type": "object", "properties": {
            "profile": PROFILE_SCHEMA,
            "draft": {"type": "string", "description": "The draft text to score."},
            "register": {"type": "string", "description": "Which register to score against. Required when the "
                         "profile has more than one."}},
            "required": ["profile", "draft"]},
        "annotations": ANNOTATIONS,
    },
    {
        "name": "compare_to_authors",
        "title": "Compare to authors",
        "description": "Compare a writing sample, or one register of a saved profile, with a fixed library of %d "
                       "public-domain authors, fiction and non-fiction (Twain, Austen, Dickens, Emerson, Wilde, "
                       "Douglass, Arnold Bennett, Helen Keller, William James, and others) "
                       "on measured style features. Returns the closest authors and the closest author per feature. "
                       "Compares style only, never personality." % len(vt.AUTHORS["authors"]),
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string", "description": "A writing sample of at least five sentences."},
            "profile": PROFILE_SCHEMA,
            "register": {"type": "string"},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3}}},
        "annotations": ANNOTATIONS,
    },
]

DISPATCH = {
    "analyze_writing": lambda a: vt.analyze_writing(a.get("samples")),
    "build_voice_profile": lambda a: vt.build_voice_profile(a.get("samples"), a.get("banned")),
    "check_draft": lambda a: vt.check_draft(a.get("profile"), a.get("draft"), a.get("register")),
    "compare_to_authors": lambda a: vt.compare_to_authors(a.get("text"), a.get("profile"), a.get("register"),
                                                          a.get("top_n", 3)),
}


def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_message(msg):
    """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, req_id, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if req_id is None:                       # notification: no response
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(req_id, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                                "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in DISPATCH:
            return _error(req_id, -32602, "Unknown tool: %s" % name)
        try:
            out = DISPATCH[name](args)
            return _result(req_id, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                                    "structuredContent": out if isinstance(out, dict) else {"items": out},
                                    "isError": False})
        except vt.ToolError as e:
            return _result(req_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception:                    # never echo input or stack traces back
            return _result(req_id, {"content": [{"type": "text", "text": "Internal error while processing the request."}],
                                    "isError": True})
    return _error(req_id, -32601, "Method not found: %s" % method)


def handle_body(raw):
    """Handle a POST body (single message or batch). Returns (status, response_body or None)."""
    try:
        data = json.loads(raw)
    except Exception:
        return 400, _error(None, -32700, "Parse error")
    if isinstance(data, list):
        out = [r for r in (handle_message(m) for m in data) if r is not None]
        return (200, out) if out else (202, None)
    r = handle_message(data)
    return (200, r) if r is not None else (202, None)
