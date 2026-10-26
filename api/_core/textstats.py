"""Shared text cleaning and surface metrics. Standard library only."""
import re
import statistics

# 's is only a contraction for a short list of words; everywhere else it is a
# possessive ("the paper's", "Anna's") and must not count.
S_CONTRACTIONS = {
    "it", "that", "here", "there", "what", "who", "where", "when", "why", "how",
    "let", "he", "she", "everyone", "everything", "nothing", "something",
    "someone", "nobody", "somebody", "this",
}
CONTRACTION_RE = re.compile(r"\b([A-Za-z]+)['’](s|t|re|ve|ll|d|m)\b")
FIRST_PERSON_RE = re.compile(r"\b(?:I|me|my|mine|myself)\b")
SECOND_PERSON_RE = re.compile(r"\b(?:you|your|yours|yourself|yourselves)\b", re.I)
WORD_RE = re.compile(r"[A-Za-z0-9'’-]+")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])[\"'”’)]*\s+")
# Periods that do not end a sentence: initials ("J. Smith") and common abbreviations.
ABBREV_RE = re.compile(r"\b(?:[A-Z]|e\.g|i\.e|etc|vs|Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|Inc|Ltd|No|Fig|al|approx|U\.S)\.(?=\s)")
# A trailing sources/references list is not prose.
REFERENCES_RE = re.compile(r"^\s*(?:#+\s*|\*\*)?(?:sources|references|bibliography|works cited)(?:\*\*)?\s*:?\s*$", re.I | re.M)
PROTECT = "․"  # one-dot leader, stands in for a non-final period while splitting

# Metric name -> human label. Order is the display order.
METRICS = {
    "mean_sent_len": "mean sentence length (words)",
    "median_sent_len": "median sentence length (words)",
    "stdev_sent_len": "sentence-length standard deviation",
    "pct_short_le8": "% sentences of 8 words or fewer",
    "pct_long_ge25": "% sentences of 25 words or more",
    "contractions_per_1k": "contractions per 1,000 words",
    "first_person_per_1k": "first person (I/me/my) per 1,000 words",
    "second_person_per_1k": "second person (you/your) per 1,000 words",
    "pct_questions": "% sentences that are questions",
    "sents_per_para": "sentences per paragraph",
}


def clean(text):
    """Strip markup so only running prose is measured.

    Drops front matter, code, tables, headings, HTML, block quotes, URLs and
    list items that are fragments. Keeps paragraph breaks.
    """
    text = text.replace("\r\n", "\n")
    m = REFERENCES_RE.search(text)                                      # trailing sources list
    if m and m.start() > len(text) * 0.5:
        text = text[:m.start()]
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)          # front matter
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)                  # html comments
    text = re.sub(r"```.*?```", "", text, flags=re.S)                   # code fences
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                    # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)                # links -> text
    text = re.sub(r"https?://\S+", "", text)                            # bare urls
    text = re.sub(r"<[^>]+>", "", text)                                 # html tags
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(("#", "|", ">", "---", "***", "===")):
            continue
        # A list item that does not end like a sentence is a fragment; skip it.
        if re.match(r"^([-*+]|\d+[.)])\s", s):
            item = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
            if not re.search(r"[.!?][\"'”’)]*$", item):
                continue
            s = item
        s = re.sub(r"[*_`]{1,3}", "", s)                                 # emphasis
        out.append(s)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def count_contractions(text):
    n = 0
    for word, suffix in CONTRACTION_RE.findall(text):
        if suffix.lower() == "s" and word.lower() not in S_CONTRACTIONS:
            continue
        n += 1
    return n


def measure(raw):
    """Return (metrics dict, counts dict) for one document, or (None, counts)."""
    text = clean(raw)
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    flat = re.sub(r"\s*\n\s*", " ", text)
    flat = ABBREV_RE.sub(lambda m: m.group(0)[:-1] + PROTECT, flat)
    sents = [s.strip().replace(PROTECT, ".") for s in SENT_SPLIT_RE.split(flat) if s.strip()]
    words = WORD_RE.findall(text)
    counts = {"words": len(words), "sentences": len(sents), "paragraphs": len(paras)}
    if not sents or not words:
        return None, counts
    lengths = [len(s.split()) for s in sents]
    k = 1000.0 / len(words)
    m = {
        "mean_sent_len": statistics.mean(lengths),
        "median_sent_len": statistics.median(lengths),
        "stdev_sent_len": statistics.pstdev(lengths),
        "pct_short_le8": 100.0 * sum(1 for x in lengths if x <= 8) / len(lengths),
        "pct_long_ge25": 100.0 * sum(1 for x in lengths if x >= 25) / len(lengths),
        "contractions_per_1k": count_contractions(text) * k,
        "first_person_per_1k": len(FIRST_PERSON_RE.findall(text)) * k,
        "second_person_per_1k": len(SECOND_PERSON_RE.findall(text)) * k,
        "pct_questions": 100.0 * sum(1 for s in sents if s.rstrip("\"'”’)").endswith("?")) / len(sents),
        "sents_per_para": len(sents) / max(len(paras), 1),
    }
    counts.update({
        "contractions": count_contractions(text),
        "questions": sum(1 for s in sents if s.rstrip("\"'”’)").endswith("?")),
        "em_dashes": raw.count("—"),
    })
    return m, counts
