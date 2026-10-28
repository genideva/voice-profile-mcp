"""Run: python3 -m unittest discover tests"""
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CORE = os.path.join(ROOT, "api", "_core")
sys.path.insert(0, CORE)
import mcp_protocol  # noqa: E402
import voice_tools as vt  # noqa: E402

PLUGIN_SCRIPTS = os.path.join(ROOT, "..", "voice-profile", "skills", "build", "scripts")

ARGUE = [
    "Most teams measure the wrong thing. They count launches. They don't count what each launch earned, "
    "and that gap hides every bad bet for a quarter or more. Why does this keep happening? Because a launch "
    "is easy to see and a dollar is hard to trace. Fix the tracing first. Then argue about the roadmap, "
    "because until you can see the money you're arguing about opinions, and opinions are cheap.",
    "Stop buying tools to fix a process problem. A tool encodes the process you already have, so if the "
    "process is broken you've just made it faster to be wrong. Map the work by hand. Find the step where "
    "things wait. That's your bottleneck. It's rarely where the loudest person says it is, and it's almost "
    "never solved by another dashboard that nobody opens after the second week.",
    "Here's the test I use. Can a new hire explain the goal in one sentence? If not, the goal isn't clear, "
    "and no amount of planning will save it. Write the sentence. Cut it in half. Ship against that, and "
    "check every Friday whether the week moved the number you wrote down, or only moved the furniture.",
]
REFLECT = [
    "I spent most of that winter tired in a way that sleep did not touch. I remember standing in the kitchen "
    "at six in the morning, holding a cold cup of coffee, trying to recall what I had promised to do that "
    "day. It took me months to understand that the problem was not the work itself. It was that I had "
    "stopped noticing which parts of it still mattered to me, and which parts I kept only out of habit.",
    "My grandmother kept a notebook of small things she wanted to remember, and I have started to do the "
    "same. Some days I write a single line about a conversation, or the way the light came through the "
    "window in the afternoon. I am not sure it makes me wiser. It does make me slower, and I have come to "
    "think that slowing down was the thing I needed most during that long and difficult year.",
    "When I finally asked for help, I was surprised by how quickly people said yes. A friend from my first "
    "job called every Sunday for a month. My sister drove four hours to sit with me while I sorted papers "
    "I had been avoiding. I had imagined that asking would cost me something, but it gave me back the "
    "feeling that I was part of something larger than my own long list of unfinished things.",
]


def samples():
    # two paragraphs each, so every sample clears the 5-sentence minimum
    def two(group, i):
        return group[i] + "\n\n" + group[(i + 1) % len(group)]
    s = [{"text": two(ARGUE, i), "title": "argue %d" % i, "ai_touched": "no", "register": "argue"} for i in range(3)]
    s += [{"text": two(REFLECT, i), "title": "reflect %d" % i, "ai_touched": "no", "register": "reflect"} for i in range(3)]
    return s


def rpc(method, params=None, rid=1):
    status, body = mcp_protocol.handle_body(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                                        "params": params or {}}))
    return status, body


def call(name, args):
    _, body = rpc("tools/call", {"name": name, "arguments": args})
    return body["result"]


class Protocol(unittest.TestCase):
    def test_initialize_and_list(self):
        _, b = rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(b["result"]["protocolVersion"], "2025-06-18")
        _, b = rpc("tools/list")
        tools = b["result"]["tools"]
        self.assertEqual({t["name"] for t in tools},
                         {"analyze_writing", "build_voice_profile", "check_draft", "compare_to_authors"})
        for t in tools:
            self.assertEqual(t["annotations"], {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
            self.assertTrue(t["description"])

    def test_notification_gets_202(self):
        status, body = mcp_protocol.handle_body(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual((status, body), (202, None))

    def test_bad_json_and_unknown_method(self):
        self.assertEqual(mcp_protocol.handle_body("{nope")[0], 400)
        _, b = rpc("nope/nope")
        self.assertEqual(b["error"]["code"], -32601)


class Tools(unittest.TestCase):
    def test_ai_touched_is_enforced(self):
        r = call("analyze_writing", {"samples": [{"text": ARGUE[0], "ai_touched": "unsure"}]})
        out = r["structuredContent"]
        self.assertEqual(out["measured"], 0)
        self.assertIn("ai_touched", out["skipped"][0]["reason"])

    def test_build_check_compare_round_trip(self):
        prof = call("build_voice_profile", {"samples": samples()})["structuredContent"]["profile"]
        self.assertEqual(set(prof["registers"]), {"argue", "reflect"})
        chk = call("check_draft", {"profile": prof, "draft": ARGUE[1], "register": "argue"})["structuredContent"]
        self.assertIn("checks", chk)
        cmp_ = call("compare_to_authors", {"text": REFLECT[0] + " " + REFLECT[1]})["structuredContent"]
        self.assertEqual(len(cmp_["nearest_authors"]), 3)

    def test_register_required_when_ambiguous(self):
        prof = call("build_voice_profile", {"samples": samples()})["structuredContent"]["profile"]
        r = call("check_draft", {"profile": prof, "draft": ARGUE[1]})
        self.assertTrue(r["isError"])
        self.assertIn("Pick a register", r["content"][0]["text"])

    def test_length_split_is_flagged_not_called_two_modes(self):
        # same voice, very different lengths: short single paragraphs vs long six-paragraph pieces
        short = [{"text": ARGUE[i % 3], "title": "short %d" % i, "ai_touched": "no"} for i in range(4)]
        long_ = [{"text": "\n\n".join(ARGUE[(i + j) % 3] for j in range(6)), "title": "long %d" % i, "ai_touched": "no"}
                 for i in range(4)]
        out = call("analyze_writing", {"samples": short + long_})["structuredContent"]
        sug = out["register_suggestion"]
        self.assertGreaterEqual(max(sug["median_words"]), 3 * min(sug["median_words"]))
        self.assertFalse(sug["two_modes_likely"])
        self.assertIn("driven by length", sug["length_warning"])

    def test_similar_lengths_get_no_length_warning(self):
        s = [dict(x, register="") for x in samples()] + [dict(x, register="", title=x["title"] + "b") for x in samples()]
        out = call("analyze_writing", {"samples": s})["structuredContent"]
        self.assertTrue(out["register_suggestion"]["two_modes_likely"])   # real argue/reflect split survives
        self.assertNotIn("length_warning", out["register_suggestion"])

    def test_short_samples_are_named(self):
        tiny = {"text": "One. Two here. Three now. Four is it. Five done.", "title": "tiny", "ai_touched": "no"}
        out = call("analyze_writing", {"samples": [tiny]})["structuredContent"]
        self.assertEqual(out["short_samples"]["titles"], ["tiny"])
        prof = call("build_voice_profile", {"samples": samples() + [dict(tiny, register="argue")]})["structuredContent"]
        self.assertTrue(any("under 150 words" in f for f in prof["flags"]))

    def test_errors_do_not_echo_input(self):
        secret = "SECRET-PHRASE-123 " * 3
        r = call("check_draft", {"profile": {"registers": {}}, "draft": secret})
        self.assertTrue(r["isError"])
        self.assertNotIn("SECRET-PHRASE", r["content"][0]["text"])


@unittest.skipUnless(os.path.isdir(PLUGIN_SCRIPTS), "voice-profile plugin repo not alongside")
class Parity(unittest.TestCase):
    def test_vendored_code_is_identical(self):
        for f in ("textstats.py", "build_profile.py", "verify.py"):
            a = hashlib.sha256(open(os.path.join(CORE, f), "rb").read()).hexdigest()
            b = hashlib.sha256(open(os.path.join(PLUGIN_SCRIPTS, f), "rb").read()).hexdigest()
            self.assertEqual(a, b, f + " differs from the plugin; copy it over")

    def test_server_bands_match_plugin_cli(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for i, s in enumerate(samples()):
                p = os.path.join(d, "s%d.txt" % i)
                open(p, "w").write(s["text"])
                rows.append([os.path.basename(p), "2019", "written", s["register"], "no"])
            # the CLI labels docs by path; give the server the same labels
            with open(os.path.join(d, "corpus.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["path", "date", "lane", "register", "ai_touched"])
                w.writerows(rows)
            subprocess.run([sys.executable, os.path.join(PLUGIN_SCRIPTS, "measure.py"), "corpus.csv",
                            "--out", "metrics.json"], cwd=d, check=True, capture_output=True)
            subprocess.run([sys.executable, os.path.join(PLUGIN_SCRIPTS, "build_profile.py"), "metrics.json",
                            "--out", "profile.json"], cwd=d, check=True, capture_output=True)
            cli = json.load(open(os.path.join(d, "profile.json")))
        srv = vt.build_voice_profile(samples())["profile"]
        for reg in ("argue", "reflect"):
            self.assertEqual(cli["registers"][reg]["bands"], srv["registers"][reg]["bands"])
            self.assertEqual(cli["registers"][reg]["center"], srv["registers"][reg]["center"])


if __name__ == "__main__":
    unittest.main()
