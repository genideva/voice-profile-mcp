"""The four voice-profile tools. Pure functions: text in, numbers out.

Nothing here stores, logs or forwards the text it receives. The measurement
code (textstats, build_profile, verify) is the same code the voice-profile
plugin ships; tests/test_parity.py proves the numbers match.
"""
import json
import math
import os
import re
import statistics

from textstats import measure, clean, METRICS
import tone
from build_profile import bands_for, fails, two_means
from verify import COUPLED

HERE = os.path.dirname(os.path.abspath(__file__))
AUTHORS = json.load(open(os.path.join(HERE, "authors.json")))

MAX_SAMPLES = 60
MAX_TOTAL_WORDS = 120_000
MAX_DRAFT_WORDS = 15_000
MIN_SENTENCES = 5
REGISTER_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
# Contractions are left out of author comparison: older printed English used
# elisions ("receiv'd", "'tis") that inflate or distort the count.
COMPARE_FEATURES = [k for k in METRICS if k != "contractions_per_1k"]


class ToolError(Exception):
    """A problem with the caller's input. Returned to the model as a tool error."""


def _round(d, n=1):
    return {k: round(v, n) for k, v in d.items()}


def _measure_samples(samples, need_register=False):
    if not isinstance(samples, list) or not samples:
        raise ToolError("samples must be a non-empty list.")
    if len(samples) > MAX_SAMPLES:
        raise ToolError("Too many samples: %d (max %d)." % (len(samples), MAX_SAMPLES))
    docs, skipped, total = [], [], 0
    for i, s in enumerate(samples):
        label = (s.get("title") or "sample %d" % (i + 1))[:80]
        ai = (s.get("ai_touched") or "").lower()
        if ai != "no":
            skipped.append({"title": label, "reason": "ai_touched must be 'no' (got '%s'). AI-assisted text "
                            "measures the assistant's version of the writer, so it is never used." % (ai or "missing")})
            continue
        text = s.get("text") or ""
        m, counts = measure(text)
        total += counts["words"]
        if total > MAX_TOTAL_WORDS:
            raise ToolError("Samples exceed %d words in total. Send fewer or shorter samples." % MAX_TOTAL_WORDS)
        if m is None or counts["sentences"] < MIN_SENTENCES:
            skipped.append({"title": label, "reason": "fewer than %d sentences of prose after cleaning" % MIN_SENTENCES})
            continue
        reg = (s.get("register") or "").strip().lower()
        if reg and not REGISTER_RE.match(reg):
            raise ToolError("register '%s' must be lowercase letters, digits or hyphens, up to 24 characters." % reg)
        if need_register and not reg:
            reg = "default"
        docs.append({"path": label, "register": reg, "lane": "written", "tone": tone.measure_tone(text),
                     "metrics": m, "counts": {k: counts[k] for k in ("words", "sentences", "paragraphs")}})
    return docs, skipped


def analyze_writing(samples):
    docs, skipped = _measure_samples(samples)
    if not docs:
        return {"measured": 0, "skipped": skipped, "message": "Nothing to measure."}
    summary = {}
    for k in METRICS:
        vals = sorted(d["metrics"][k] for d in docs)
        summary[k] = {"label": METRICS[k], "min": round(vals[0], 1),
                      "median": round(vals[len(vals) // 2], 1), "max": round(vals[-1], 1)}
    words = sum(d["counts"]["words"] for d in docs)
    out = {
        "measured": len(docs),
        "words": words,
        "skipped": skipped,
        "summary": summary,
        "samples": [{"title": d["path"], "register": d["register"] or None, "words": d["counts"]["words"],
                     "metrics": _round(d["metrics"]),
                     "tone": _round(d["tone"], 2) if d.get("tone") else None} for d in docs],
    }
    if words < 3000:
        out["warning"] = "Under 3,000 words. Any profile built from this will be provisional."
    if len(docs) >= 8 and not any(d["register"] for d in docs):
        assign, sep = two_means(docs)
        sizes = [assign.count(0), assign.count(1)]
        out["register_suggestion"] = {
            "separation": round(sep, 2),
            "two_modes_likely": sep >= 1.5 and min(sizes) >= 3,
            "groups": [[d["path"] for d, g in zip(docs, assign) if g == c] for c in (0, 1)],
            "next_step": "Read each group, name the genre it shares, and pass that name as each sample's register.",
        }
    return out


def build_voice_profile(samples, banned=None):
    docs, skipped = _measure_samples(samples, need_register=True)
    if not docs:
        raise ToolError("No usable samples. Every sample needs ai_touched='no' and at least %d sentences." % MIN_SENTENCES)
    regs = {}
    for d in docs:
        regs.setdefault(d["register"], []).append(d)
    profile = {"format": "voice-profile/1", "registers": {}, "spoken": None,
               "banned": [str(b)[:60] for b in (banned or [])][:100], "doc_checks": []}
    for name, group in regs.items():
        b, c = bands_for(group)
        words = sum(d["counts"]["words"] for d in group)
        profile["registers"][name] = {"n_docs": len(group), "words": words, "bands": b, "center": c,
                                      "provisional": len(group) < 5 or words < 3000}
    names = list(profile["registers"])
    for d in docs:
        row = {"path": d["path"], "register": d["register"]}
        for n in names:
            row["fails_vs_" + n] = fails(d["metrics"], profile["registers"][n]["bands"])
        profile["doc_checks"].append(row)
    flags = [r["path"] for r in profile["doc_checks"] if r["fails_vs_" + r["register"]] >= 3]
    return {
        "profile": profile,
        "skipped": skipped,
        "flags": ["'%s' fails 3+ checks against its own register: mislabelled, or a third mode?" % p for p in flags],
        "save_instructions": "Save the 'profile' object as profile.json. Pass it to check_draft to score drafts. "
                             "This service keeps nothing, so the user must keep the file.",
    }


def _validate_profile(profile):
    if not isinstance(profile, dict) or not isinstance(profile.get("registers"), dict) or not profile["registers"]:
        raise ToolError("profile must be the 'profile' object returned by build_voice_profile.")
    for name, r in profile["registers"].items():
        bands = r.get("bands") if isinstance(r, dict) else None
        if not isinstance(bands, dict) or set(bands) != set(METRICS):
            raise ToolError("profile register '%s' is missing bands or has unknown ones." % name)
        for k, v in bands.items():
            if not (isinstance(v, list) and len(v) == 2 and isinstance(v[0], (int, float))
                    and (v[1] is None or isinstance(v[1], (int, float)))):
                raise ToolError("profile band '%s' in register '%s' is malformed." % (k, name))


def check_draft(profile, draft, register=None):
    _validate_profile(profile)
    regs = list(profile["registers"])
    if register is None:
        if len(regs) > 1:
            raise ToolError("Pick a register first. This profile has: %s. Scoring against the wrong register "
                            "is worse than not scoring." % ", ".join(regs))
        register = regs[0]
    if register not in regs:
        raise ToolError("Unknown register '%s'. This profile has: %s." % (register, ", ".join(regs)))
    m, counts = measure(draft or "")
    if m is None:
        raise ToolError("No prose found in the draft after cleaning.")
    if counts["words"] > MAX_DRAFT_WORDS:
        raise ToolError("Draft is over %d words. Check it in sections." % MAX_DRAFT_WORDS)
    r = profile["registers"][register]
    rows, failed, notes = [], 0, []
    for k in METRICS:
        lo, hi = r["bands"][k]
        v = m[k]
        ok = v >= lo and (hi is None or v <= hi)
        direction = None if ok else ("raise" if v < lo else "lower")
        failed += 0 if ok else 1
        rows.append({"metric": k, "label": METRICS[k], "value": round(v, 1), "low": lo, "high": hi,
                     "pass": ok, "move": direction})
        if not ok and k in COUPLED:
            notes.append(COUPLED[k])
    text = clean(draft)
    hits = [w for w in profile.get("banned", []) if re.search(r"\b" + re.escape(str(w)) + r"\b", text, re.I)]
    failed += 1 if hits else 0
    return {"register": register, "words": counts["words"], "in_band": failed == 0, "failed_checks": failed,
            "checks": rows, "banned_words_found": hits, "notes": list(dict.fromkeys(notes)),
            "provisional_profile": bool(r.get("provisional")),
            "reminder": "A failed check means look, not wrong. Re-read for tone (hedging, softening) as well."}


def _author_scale():
    scale = {}
    for k in COMPARE_FEATURES:
        vals = [a["center"][k] for a in AUTHORS["authors"]]
        scale[k] = (statistics.mean(vals), statistics.pstdev(vals) or 1.0)
    return scale


def compare_to_authors(text=None, profile=None, register=None, top_n=3):
    if (text is None) == (profile is None):
        raise ToolError("Pass either text (a writing sample) or profile with a register, not both.")
    if text is not None:
        m, counts = measure(text)
        if m is None or counts["sentences"] < MIN_SENTENCES:
            raise ToolError("Need at least %d sentences of prose to compare." % MIN_SENTENCES)
        if counts["words"] > MAX_DRAFT_WORDS:
            raise ToolError("Text is over %d words. Send a shorter sample." % MAX_DRAFT_WORDS)
        mine, basis = m, "the text provided (%d words)" % counts["words"]
        reads = tone.how_it_reads(tone.measure_tone(text), AUTHORS["authors"])
    else:
        _validate_profile(profile)
        regs = list(profile["registers"])
        register = register or (regs[0] if len(regs) == 1 else None)
        if register not in regs:
            raise ToolError("Pick a register: %s." % ", ".join(regs))
        mine, basis = profile["registers"][register]["center"], "profile register '%s'" % register
        reads = None
    top_n = max(1, min(int(top_n or 3), 8))
    scale = _author_scale()
    ranked = []
    for a in AUTHORS["authors"]:
        z = {k: (mine[k] - a["center"][k]) / scale[k][1] for k in COMPARE_FEATURES}
        dist = math.sqrt(sum(v * v for v in z.values()) / len(z))
        ranked.append((dist, a, z))
    ranked.sort(key=lambda x: x[0])
    nearest = []
    for dist, a, z in ranked[:top_n]:
        closest = sorted(z, key=lambda k: abs(z[k]))[:3]
        furthest = sorted(z, key=lambda k: -abs(z[k]))[:2]
        nearest.append({
            "author": a["author"], "work": a["work"], "year": a["year"], "genre": a["genre"],
            "source": a["source"], "distance": round(dist, 2),
            "most_alike_on": [METRICS[k] for k in closest],
            "most_different_on": [{"feature": METRICS[k], "you": round(mine[k], 1),
                                   "author": a["center"][k]} for k in furthest],
        })
    per_feature = {}
    for k in COMPARE_FEATURES:
        best = min(AUTHORS["authors"], key=lambda a: abs(a["center"][k] - mine[k]))
        per_feature[METRICS[k]] = {"you": round(mine[k], 1), "closest_author": best["author"],
                                   "their_value": best["center"][k]}
    out = {
        "basis": basis,
        "nearest_authors": nearest,
        "closest_author_per_feature": per_feature,
        "method": "Distance across nine surface features (contractions excluded because older print used elisions), "
                  "each scaled by how much it varies across the %d authors. Lower is closer." % len(AUTHORS["authors"]),
        "caveat": "The author match compares measurable style only: rhythm, sentence shape, pronouns, questions. "
                  "how_it_reads scores how the text reads, never who wrote it, and says nothing about the authors as "
                  "people. Library: public-domain works from Project Gutenberg.",
    }
    if reads:
        out["how_it_reads"] = reads
    return out


def list_authors():
    return [{"author": a["author"], "work": a["work"], "year": a["year"], "genre": a["genre"]}
            for a in AUTHORS["authors"]]
