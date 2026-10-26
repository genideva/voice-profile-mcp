#!/usr/bin/env python3
"""Turn metrics.json into profile.json: one band set per register.

Usage:
  python3 build_profile.py metrics.json [--out profile.json] [--banned banned.txt]
  python3 build_profile.py metrics.json --suggest-registers

Registers come from the 'register' column of your manifest. If you left it
blank and have 8+ written documents, --suggest-registers looks for a two-mode
split and prints which documents fall where. You then label them and re-run
measure.py. With fewer than 8 documents, label registers by genre yourself
(argument vs reflection, memo vs essay) instead of trusting a clustering of
a handful of points.

Bands are working ranges, not constants. With few documents per register they
are padded to a minimum width so one quirky document cannot set a target.
"""
import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textstats import METRICS  # noqa: E402

# Minimum half-width of a band, per metric, so small corpora do not produce
# razor-thin targets.
MIN_HALF = {
    "mean_sent_len": 2.5, "median_sent_len": 3.0, "stdev_sent_len": 2.0,
    "pct_short_le8": 8.0, "pct_long_ge25": 7.0, "contractions_per_1k": 7.0,
    "first_person_per_1k": 8.0, "second_person_per_1k": 8.0,
    "pct_questions": 4.0, "sents_per_para": 1.0,
}
# Variation in sentence length is a floor only: more variety never fails.
FLOOR_ONLY = {"stdev_sent_len"}
CLUSTER_FEATURES = ["contractions_per_1k", "first_person_per_1k", "pct_questions",
                    "stdev_sent_len", "pct_short_le8", "mean_sent_len"]


def pct(vals, q):
    vals = sorted(vals)
    i = (len(vals) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return vals[lo] + (vals[hi] - vals[lo]) * (i - lo)


def bands_for(docs):
    out, center = {}, {}
    total_words = sum(d["counts"]["words"] for d in docs)
    for k in METRICS:
        vals = [d["metrics"][k] for d in docs]
        c = sum(d["metrics"][k] * d["counts"]["words"] for d in docs) / total_words
        if len(vals) >= 8:
            lo, hi = pct(vals, 0.10), pct(vals, 0.90)
        else:
            lo, hi = min(vals), max(vals)
        pad = 0.10 * (hi - lo)
        lo = max(0.0, min(lo - pad, c - MIN_HALF[k]))
        hi = max(hi + pad, c + MIN_HALF[k])
        if k in FLOOR_ONLY:
            hi = None
        out[k] = [round(lo, 1), None if hi is None else round(hi, 1)]
        center[k] = round(c, 1)
    return out, center


def fails(metrics, bands):
    n = 0
    for k, (lo, hi) in bands.items():
        v = metrics[k]
        if v < lo or (hi is not None and v > hi):
            n += 1
    return n


def two_means(docs):
    feats = []
    for k in CLUSTER_FEATURES:
        vals = [d["metrics"][k] for d in docs]
        mu, sd = statistics.mean(vals), statistics.pstdev(vals) or 1.0
        feats.append([(v - mu) / sd for v in vals])
    pts = list(zip(*feats))

    def dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    i, j = max(((i, j) for i in range(len(pts)) for j in range(i + 1, len(pts))),
               key=lambda ij: dist(pts[ij[0]], pts[ij[1]]))
    cents = [pts[i], pts[j]]
    assign = [0] * len(pts)
    for _ in range(50):
        assign = [0 if dist(p, cents[0]) <= dist(p, cents[1]) else 1 for p in pts]
        new = []
        for c in (0, 1):
            members = [p for p, a in zip(pts, assign) if a == c] or [cents[c]]
            new.append(tuple(statistics.mean(col) for col in zip(*members)))
        if new == cents:
            break
        cents = new
    within = statistics.mean(dist(p, cents[a]) for p, a in zip(pts, assign))
    between = dist(cents[0], cents[1])
    return assign, between / (within or 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("metrics")
    ap.add_argument("--out", default="profile.json")
    ap.add_argument("--banned", help="text file, one banned word or phrase per line")
    ap.add_argument("--suggest-registers", action="store_true")
    a = ap.parse_args()

    data = json.load(open(a.metrics))
    written = [d for d in data["docs"] if d["lane"] == "written"]
    spoken = [d for d in data["docs"] if d["lane"] == "spoken"]
    if not written:
        sys.exit("No written documents. Bands come from written prose only.")

    if a.suggest_registers:
        if len(written) < 8:
            sys.exit("Only %d written documents. Label registers by genre yourself; "
                     "clustering this few points is noise." % len(written))
        assign, sep = two_means(written)
        sizes = [assign.count(0), assign.count(1)]
        print("Two-mode separation score: %.2f (between-mode distance / within-mode spread)" % sep)
        if sep < 1.5 or min(sizes) < 3:
            print("No clear second mode. Treat your writing as one register.")
        else:
            print("Likely two registers. Read each group and name the genre it shares:")
        for c in (0, 1):
            print("\n  group %d (%d docs)" % (c + 1, sizes[c]))
            for d, g in zip(written, assign):
                if g == c:
                    m = d["metrics"]
                    print("    %-44s contr %5.1f  I %5.1f  q %4.1f%%  sd %4.1f" % (
                        d["path"][-44:], m["contractions_per_1k"], m["first_person_per_1k"],
                        m["pct_questions"], m["stdev_sent_len"]))
        print("\nPut your labels in the manifest's register column, re-run measure.py, then build.")
        return

    regs = {}
    for d in written:
        regs.setdefault(d["register"] or "default", []).append(d)
    if "default" in regs and len(regs) > 1:
        print("WARNING: %d written documents have no register label; they form their own "
              "'default' register." % len(regs["default"]))

    profile = {"registers": {}, "spoken": None, "banned": [], "doc_checks": []}
    for name, docs in regs.items():
        b, c = bands_for(docs)
        profile["registers"][name] = {
            "n_docs": len(docs),
            "words": sum(d["counts"]["words"] for d in docs),
            "bands": b,
            "center": c,
            "provisional": len(docs) < 5 or sum(d["counts"]["words"] for d in docs) < 3000,
        }
    if spoken:
        _, c = bands_for(spoken)
        profile["spoken"] = {"n_docs": len(spoken), "words": sum(d["counts"]["words"] for d in spoken),
                             "center": c, "note": "report only; never use spoken numbers as prose targets"}
    if a.banned and os.path.exists(a.banned):
        profile["banned"] = [l.strip() for l in open(a.banned) if l.strip() and not l.startswith("#")]

    names = list(profile["registers"])
    for d in written:
        row = {"path": d["path"], "register": d["register"] or "default"}
        for n in names:
            row["fails_vs_" + n] = fails(d["metrics"], profile["registers"][n]["bands"])
        profile["doc_checks"].append(row)
    json.dump(profile, open(a.out, "w"), indent=1)

    for n, r in profile["registers"].items():
        print("\nRegister '%s': %d docs, %d words%s" % (n, r["n_docs"], r["words"],
              "  [PROVISIONAL: thin evidence]" if r["provisional"] else ""))
        for k, label in METRICS.items():
            lo, hi = r["bands"][k]
            print("  %-42s %6.1f   band %5.1f - %s" % (label, r["center"][k], lo,
                  "no ceiling" if hi is None else "%5.1f" % hi))
    if profile["spoken"]:
        s = profile["spoken"]["center"]
        print("\nSpoken lane (report only): contractions %.1f/1k, mean sentence %.1f words"
              % (s["contractions_per_1k"], s["mean_sent_len"]))
    if len(names) > 1:
        print("\nCross-check: average failed checks when a document is scored against each register")
        print("  %-12s" % "doc's own" + "".join("%12s" % ("vs " + n) for n in names))
        for own in names:
            rows = [r for r in profile["doc_checks"] if r["register"] == own]
            print("  %-12s" % own + "".join("%12.1f" % statistics.mean(r["fails_vs_" + n] for r in rows)
                                             for n in names))
        print("  Distinct registers show low numbers on the diagonal and high numbers off it.")
    bad = [r for r in profile["doc_checks"] if r["fails_vs_" + r["register"]] >= 3]
    for r in bad:
        print("  NOTE: %s fails %d checks against its own register. Mislabelled, or a third mode?"
              % (r["path"], r["fails_vs_" + r["register"]]))
    print("\nWrote", a.out)


if __name__ == "__main__":
    main()
