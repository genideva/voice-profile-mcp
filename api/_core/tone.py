"""How a piece of writing reads: tone markers and Big Five traits as expressed in text.

Everything here is counted, not guessed. Each marker is a short, fixed word list
(written for this project, after the word-category approach in Pennebaker & King
1999, Yarkoni 2010 and Schwartz et al. 2013). Each trait is a fixed combination
of markers, scored against the author library.

The traits describe how the TEXT reads ("reads as warm"), never who the writer is.
Word-category links to personality are real but modest, so this is a writing
aid: change the words and the reading changes.

Kept separate from textstats.py so the plugin's vendored code stays byte-identical.
"""
import math
import re
import statistics

from textstats import ABBREV_RE, PROTECT, SENT_SPLIT_RE, WORD_RE, clean


def _words(*groups):
    return frozenset(w for g in groups for w in g.split())


# Marker -> (label, single words, phrases). Rates are per 1,000 words.
LEXICONS = {
    "reasoning": ("reasoning words (because, therefore, however)", _words(
        "because therefore thus hence consequently however although though whereas",
        "nevertheless nonetheless despite instead otherwise accordingly unless"), ("so that", "as a result")),
    "hedges": ("hedges (perhaps, might, seems)", _words(
        "perhaps maybe might possibly probably apparently somewhat likely unlikely",
        "seem seems seemed appear appears suggest suggests guess suppose arguably"),
        ("sort of", "kind of", "i think", "i believe", "i feel", "it may be")),
    "certainty": ("certainty words (clearly, always, must)", _words(
        "clearly certainly definitely obviously undoubtedly surely always never must",
        "absolutely indeed plainly unquestionably"), ("of course", "no doubt")),
    "intensifiers": ("intensifiers (very, really, extremely)", _words(
        "very really extremely incredibly totally truly highly deeply utterly",
        "enormously remarkably especially hugely"), ()),
    "social": ("social words (we, together, people)", _words(
        "we us our ours ourselves together friend friends people team everyone",
        "talk talked meet met share shared join joined party community"), ()),
    "positive": ("warm, positive words (glad, thanks, love)", _words(
        "good great love loved happy glad thank thanks grateful kind warm enjoy",
        "enjoyed hope nice wonderful beautiful best pleasure help helped care",
        "appreciate delighted proud fun"), ()),
    "negative": ("worry and negative words (afraid, wrong, tired)", _words(
        "worry worried afraid fear anxious nervous sad angry hate hurt pain lonely",
        "terrible awful bad wrong fail failed failure stress stressed upset lost",
        "problem problems tired sorry regret"), ()),
    "order": ("order and goal words (first, plan, finish)", _words(
        "first second third finally next plan planned plans goal goals step steps",
        "task tasks finish finished complete completed achieve deadline schedule",
        "organize organized prepare prepared result results"), ()),
    "insight": ("curiosity words (imagine, consider, idea)", _words(
        "imagine wonder wondered consider idea ideas curious explore understand",
        "realize realized learn learned meaning possible discover create theory",
        "insight perspective"), ()),
}
TONE_LABELS = {k: v[0] for k, v in LEXICONS.items()}
TONE_LABELS.update({
    "pct_exclaim": "% sentences ending in !",
    "pct_long_words": "% words of 7+ letters",
})
TONE_FEATURES = list(TONE_LABELS)

# Trait -> (name, low label, high label, weighted markers, tip to read higher, tip to read lower).
TRAITS = [
    ("extraversion", "Outgoing", "Reserved", "Outgoing",
     {"social": 1.0, "positive": 0.5, "pct_exclaim": 0.5},
     "Bring people in: more we, us and together, name who was there, let some energy show.",
     "Fewer we/us and exclamation marks; let the ideas carry it instead of the crowd."),
    ("agreeableness", "Warm", "Cool", "Warm",
     {"positive": 1.0, "social": 0.5, "negative": -0.5},
     "Add a thank-you, credit someone, say what you liked before what you'd change.",
     "Trim the softeners and compliments; state the point first."),
    ("conscientiousness", "Organized", "Loose", "Organized",
     {"order": 1.0, "reasoning": 0.5, "negative": -0.25},
     "Signpost: first, next, finally. Name the goal and the next step.",
     "Drop some of the scaffolding; not every paragraph needs a 'first' and a 'finally'."),
    ("openness", "Curious", "Concrete", "Curious",
     {"insight": 1.0, "pct_long_words": 0.75},
     "Ask what it means, offer an idea, imagine an alternative.",
     "Swap abstract words for concrete ones: a number, a name, a thing you can see."),
    ("neuroticism", "Tense", "Calm", "Tense",
     {"negative": 1.0, "hedges": 0.5, "certainty": -0.25},
     "This reads calm and steady. Keep it.",
     "Cut worry words and hedges; say what you know plainly, and what you'll do about the rest."),
]
TONE_MARKERS = [  # shown directly, with their own five-level labels
    ("argumentative", "reasoning", ("Assertive", "Argumentative")),
    ("hedged", "hedges", ("Direct", "Hedged")),
    ("confident", "certainty", ("Tentative", "Confident")),
    ("emphatic", "intensifiers", ("Understated", "Emphatic")),
]
TIPS = {
    "argumentative": ("Show your reasoning: because, therefore, however. Claims land harder with the why attached.",
                      "Lots of reasoning words. Check each 'however' earns its place."),
    "hedged": ("Very few hedges. Good, as long as you're as sure as you sound.",
               "Cut perhaps/might/I think where you actually know. Keep one hedge where the doubt is real."),
    "confident": ("Few certainty words. Where you are sure, say so: 'this will', not 'this may'.",
                  "Heavy on always/never/clearly. Readers push back on absolutes; keep the ones you can prove."),
    "emphatic": ("Understated. Let the facts be the emphasis; it reads as calm authority.",
                 "Cut very/really/extremely; pick a stronger word instead of propping up a weak one."),
}
LEVELS = ["Very {lo}", "{lo}", "Neither", "{hi}", "Very {hi}"]


def measure_tone(raw):
    """Per-1,000-word rates for each marker, plus % exclamations and % long words."""
    text = clean(raw)
    words = [w.lower().strip("'’-") for w in WORD_RE.findall(text)]
    words = [w for w in words if w]
    if not words:
        return None
    k = 1000.0 / len(words)
    low = " " + " ".join(words) + " "
    out = {}
    for key, (_, singles, phrases) in LEXICONS.items():
        n = sum(1 for w in words if w in singles)
        n += sum(low.count(" " + p + " ") for p in phrases)
        out[key] = n * k
    flat = re.sub(r"\s*\n\s*", " ", text)
    flat = ABBREV_RE.sub(lambda m: m.group(0)[:-1] + PROTECT, flat)
    sents = [s for s in SENT_SPLIT_RE.split(flat) if s.strip()]
    out["pct_exclaim"] = 100.0 * sum(1 for s in sents if s.rstrip("\"'”’) ").endswith("!")) / max(len(sents), 1)
    out["pct_long_words"] = 100.0 * sum(1 for w in words if len(w.replace("'", "")) >= 7) / len(words)
    return out


def _level(z):
    return 0 if z <= -1.25 else 1 if z <= -0.4 else 2 if z < 0.4 else 3 if z < 1.25 else 4


def library_scale(authors):
    """Mean and spread of each tone feature across library authors that have tone numbers."""
    rows = [a["tone"] for a in authors if a.get("tone")]
    if len(rows) < 5:
        return None
    return {k: (statistics.mean(r[k] for r in rows), statistics.pstdev([r[k] for r in rows]) or 1.0)
            for k in TONE_FEATURES}


def _trait_z(tone, weights, scale):
    total = sum(abs(w) for w in weights.values())
    return sum(w * (tone[k] - scale[k][0]) / scale[k][1] for k, w in weights.items()) / total


def how_it_reads(tone, authors):
    """Five traits and four markers for one text, each placed on a five-level scale against the library."""
    scale = library_scale(authors)
    if scale is None or tone is None:
        return None
    lib = [a for a in authors if a.get("tone")]
    traits = []
    for key, name, lo, hi, weights, tip_up, tip_down in TRAITS:
        z = _trait_z(tone, weights, scale)
        lvl = _level(z)
        nearest = min(lib, key=lambda a: abs(_trait_z(a["tone"], weights, scale) - z))
        drivers = sorted(weights, key=lambda k: -abs(weights[k] * (tone[k] - scale[k][0]) / scale[k][1]))[:2]
        traits.append({
            "trait": key, "name": name, "reads_as": LEVELS[lvl].format(lo=lo, hi=hi).replace("Neither", "Balanced"),
            "level": lvl - 2, "score": round(z, 2),
            "drivers": [{"marker": TONE_LABELS[k], "you": round(tone[k], 1), "library_typical": round(scale[k][0], 1)}
                        for k in drivers],
            "reads_like": nearest["author"],
            "tip": tip_down if lvl >= 3 else tip_up if lvl <= 1 else None,
        })
    markers = []
    for key, feat, (lo, hi) in TONE_MARKERS:
        z = (tone[feat] - scale[feat][0]) / scale[feat][1]
        lvl = _level(z)
        markers.append({
            "marker": key, "reads_as": LEVELS[lvl].format(lo=lo, hi=hi).replace("Neither", "Balanced"),
            "level": lvl - 2, "you": round(tone[feat], 1), "library_typical": round(scale[feat][0], 1),
            "per": TONE_LABELS[feat] + " per 1,000 words",
            "tip": TIPS[key][1] if lvl >= 3 else TIPS[key][0] if lvl <= 1 else None,
        })
    return {
        "traits": traits,
        "markers": markers,
        "note": "How the writing reads, not who the writer is. Each trait is a fixed mix of counted word "
                "categories, scored against %d public-domain books. Word-category links to personality are "
                "modest, so treat this as a writing aid: change the words and the reading changes." % len(lib),
    }
