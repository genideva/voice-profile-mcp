#!/usr/bin/env python3
"""Score a draft against one register of your profile.

Usage:
  python3 verify.py profile.json draft.md --register argue
  python3 verify.py profile.json draft.md --all        # score against every register
  python3 verify.py profile.json draft.md --register argue --json

Exit code is the number of failed checks, so it works as a gate in scripts.
A FAIL is a prompt to look, not a verdict: bands are working ranges.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textstats import measure, clean, METRICS  # noqa: E402

# Pairs that trade against each other; a note is printed when one fails.
COUPLED = {
    "pct_short_le8": "Short and long shares trade against each other. Fixing one by brute force breaks the other.",
    "pct_long_ge25": "Short and long shares trade against each other. Fixing one by brute force breaks the other.",
    "contractions_per_1k": "Check this first. Instructions to be blunt or direct tend to pull a model formal, and formal prose drops contractions.",
}


def score(profile, reg, raw):
    r = profile["registers"][reg]
    m, counts = measure(raw)
    if m is None:
        return None
    rows, fails = [], 0
    for k in METRICS:
        lo, hi = r["bands"][k]
        v = m[k]
        ok = v >= lo and (hi is None or v <= hi)
        fails += 0 if ok else 1
        rows.append({"metric": k, "value": round(v, 1), "lo": lo, "hi": hi, "pass": ok})
    text = clean(raw)
    hits = [w for w in profile.get("banned", []) if re.search(r"\b" + re.escape(w) + r"\b", text, re.I)]
    fails += 1 if hits else 0
    return {"register": reg, "counts": counts, "rows": rows, "banned_hits": hits, "fails": fails,
            "provisional": r.get("provisional", False)}


def show(res, path):
    c = res["counts"]
    print("--- %s | register '%s' | %d words, %d sentences, %d paragraphs%s ---" % (
        os.path.basename(path), res["register"], c["words"], c["sentences"], c["paragraphs"],
        " | provisional bands" if res["provisional"] else ""))
    notes = []
    for row in res["rows"]:
        hi = "  max" if row["hi"] is None else "%5.1f" % row["hi"]
        print("  %-42s %7.1f   band %5.1f-%s   %s" % (METRICS[row["metric"]], row["value"], row["lo"],
              hi if row["hi"] is not None else " none", "PASS" if row["pass"] else "FAIL"))
        if not row["pass"] and row["metric"] in COUPLED:
            notes.append(COUPLED[row["metric"]])
    print("  %-42s %s" % ("banned words", ", ".join(res["banned_hits"]) or "none  PASS"))
    print("  %-42s %d (reported, not scored)" % ("em dashes", c.get("em_dashes", 0)))
    for n in dict.fromkeys(notes):
        print("  note: " + n)
    print("  => %s (%d checks failed)\n" % ("IN BAND" if res["fails"] == 0 else "OUT OF BAND", res["fails"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("draft")
    ap.add_argument("--register")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    profile = json.load(open(a.profile))
    regs = list(profile["registers"])
    if a.all:
        chosen = regs
    elif a.register:
        if a.register not in regs:
            sys.exit("Unknown register '%s'. Profile has: %s" % (a.register, ", ".join(regs)))
        chosen = [a.register]
    elif len(regs) == 1:
        chosen = regs
    else:
        sys.exit("Pick a register first (--register NAME). Profile has: %s. "
                 "Scoring against the wrong register is worse than not scoring." % ", ".join(regs))

    raw = open(a.draft, encoding="utf-8", errors="replace").read()
    results = [score(profile, r, raw) for r in chosen]
    if any(r is None for r in results):
        sys.exit("No prose found in draft after cleaning.")
    if a.json:
        print(json.dumps(results, indent=1))
    else:
        for res in results:
            show(res, a.draft)
    sys.exit(min(results, key=lambda r: r["fails"])["fails"] if a.all else results[0]["fails"])


if __name__ == "__main__":
    main()
