#!/usr/bin/env python3
"""Rebuild api/_core/authors.json from public-domain texts on Project Gutenberg.

Usage: python3 tools/build_authors.py CACHE_DIR

Downloads each book once into CACHE_DIR, strips the Gutenberg header and
footer, cuts the body into ~1,500-word chunks, measures every chunk with the
same code the plugin uses, and stores only the resulting numbers. No text from
any book is written to the repository.
"""
import json
import os
import re
import statistics
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api", "_core"))
from textstats import measure, METRICS  # noqa: E402

# (author, work, year, genre, gutenberg id). Public domain in the US.
WORKS = [
    ("Mark Twain", "Life on the Mississippi", 1883, "memoir", 245),
    ("Jane Austen", "Pride and Prejudice", 1813, "novel", 1342),
    ("Charles Dickens", "A Tale of Two Cities", 1859, "novel", 98),
    ("Ralph Waldo Emerson", "Essays: First Series", 1841, "essay", 2944),
    ("Henry David Thoreau", "Walden", 1854, "memoir", 205),
    ("Oscar Wilde", "The Picture of Dorian Gray", 1890, "novel", 174),
    ("Frederick Douglass", "Narrative of the Life of Frederick Douglass", 1845, "memoir", 23),
    ("Mary Wollstonecraft", "A Vindication of the Rights of Woman", 1792, "essay", 3420),
    ("Thomas Paine", "Common Sense", 1776, "essay", 147),
    ("Benjamin Franklin", "Autobiography", 1791, "memoir", 148),
    ("Herman Melville", "Moby-Dick", 1851, "novel", 2701),
    ("Mary Shelley", "Frankenstein", 1818, "novel", 84),
    ("Arthur Conan Doyle", "The Adventures of Sherlock Holmes", 1892, "fiction", 1661),
    ("G. K. Chesterton", "Orthodoxy", 1908, "essay", 130),
    ("Edgar Allan Poe", "The Works of Edgar Allan Poe, Volume 2", 1845, "fiction", 2148),
    ("Jonathan Swift", "Gulliver's Travels", 1726, "satire", 829),
]
CHUNK_WORDS = 1500
MAX_CHUNKS = 40


def fetch(gid, cache):
    path = os.path.join(cache, "pg%d.txt" % gid)
    if not os.path.exists(path):
        url = "https://www.gutenberg.org/cache/epub/%d/pg%d.txt" % (gid, gid)
        with urllib.request.urlopen(url, timeout=60) as r:
            open(path, "wb").write(r.read())
    return open(path, encoding="utf-8", errors="replace").read()


def body(text):
    s = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    e = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", text)
    text = text[s.end() if s else 0: e.start() if e else len(text)]
    # Unwrap hard line breaks inside paragraphs; drop short headings and contents lines.
    paras = []
    for p in re.split(r"\n\s*\n", text):
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        if len(p.split()) >= 12 and not p.isupper():
            paras.append(p)
    return paras[len(paras) // 20:]          # skip front matter (prefaces, contents)


def chunks(paras):
    out, cur, n = [], [], 0
    for p in paras:
        cur.append(p)
        n += len(p.split())
        if n >= CHUNK_WORDS:
            out.append("\n\n".join(cur))
            cur, n = [], 0
    step = max(1, len(out) // MAX_CHUNKS)
    return out[::step][:MAX_CHUNKS]


def main():
    cache = sys.argv[1]
    os.makedirs(cache, exist_ok=True)
    authors = []
    for author, work, year, genre, gid in WORKS:
        raw = fetch(gid, cache)
        title_line = re.search(r"Title:\s*(.+)", raw)
        docs = [measure(c) for c in chunks(body(raw))]
        docs = [(m, c) for m, c in docs if m]
        words = sum(c["words"] for _, c in docs)
        center = {k: round(sum(m[k] * c["words"] for m, c in docs) / words, 2) for k in METRICS}
        spread = {k: round(statistics.pstdev([m[k] for m, _ in docs]), 2) for k in METRICS}
        authors.append({"author": author, "work": work, "year": year, "genre": genre,
                        "source": "https://www.gutenberg.org/ebooks/%d" % gid,
                        "chunks": len(docs), "words": words, "center": center, "spread": spread})
        print("%-22s %-45s %3d chunks %7d words  [%s]" % (
            author, work[:45], len(docs), words, title_line.group(1).strip()[:40] if title_line else "?"))
    out = os.path.join(HERE, "..", "api", "_core", "authors.json")
    json.dump({"note": "Measured style features of public-domain works from Project Gutenberg. "
                       "Numbers only; no text is stored. Not personality claims about any person.",
               "chunk_words": CHUNK_WORDS, "authors": authors}, open(out, "w"), indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
