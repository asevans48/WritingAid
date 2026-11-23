"""Build the benchmark set for the checks (piece Q.1).

    venv/bin/python scripts/build_benchmark.py

Writes ``benchmark/`` in the repository:

* ``clean/``  well-edited published prose: one passage from each of twelve
  public-domain books in different genres (taken from the Project Gutenberg
  downloads the app already keeps in ``~/.creativeos/corpus_downloads``).
  The right answer: almost nothing should be flagged.
* ``seeded/`` the same passages with known mistakes inserted (spelling,
  confused words, agreement, punctuation, repeated words). The right answer
  is the list of insertions, stored beside each passage.
* ``style/marked.json`` is written by hand, not by this script: short
  passages with every style problem marked, including deliberate fragments,
  dialect and dialogue where a flag would be wrong.

The output is fixed (same books, same offsets, same random seed), so
rebuilding gives the same files. Only public-domain text is used; nothing
from the writer's own projects.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "benchmark"
CORPORA = Path.home() / ".creativeos" / "corpus_downloads"

# (corpus id, genre, title, year). 20th-century or late-19th-century English,
# so period spellings do not dominate the spelling numbers.
BOOKS = [
    ("gutenberg-great-gatsby", "literary", "The Great Gatsby", 1925),
    ("gutenberg-age-of-innocence", "literary", "The Age of Innocence", 1920),
    ("gutenberg-my-antonia", "literary", "My Ántonia", 1918),
    ("gutenberg-mysterious-affair-styles", "mystery", "The Mysterious Affair at Styles", 1920),
    ("gutenberg-father-brown", "mystery", "The Innocence of Father Brown", 1911),
    ("gutenberg-thirty-nine-steps", "thriller", "The Thirty-Nine Steps", 1915),
    ("gutenberg-call-of-wild", "adventure", "The Call of the Wild", 1903),
    ("gutenberg-princess-mars", "science fiction", "A Princess of Mars", 1912),
    ("gutenberg-war-of-worlds", "science fiction", "The War of the Worlds", 1898),
    ("gutenberg-riders-purple-sage", "western", "Riders of the Purple Sage", 1912),
    ("gutenberg-willows", "horror", "The Willows", 1907),
    ("gutenberg-anne-green-gables", "general", "Anne of Green Gables", 1908),
]
START_AT = 0.4            # how far into the book the passage starts
# Where the default lands on something unrepresentative (a page of broad
# Scots dialect in The Thirty-Nine Steps), start elsewhere.
START_OVERRIDE = {"gutenberg-thirty-nine-steps": 0.6}
MIN_WORDS, MAX_WORDS = 320, 460
SEED = 20261123


# ── Clean passages ──────────────────────────────────────────────────────

def _body(raw: str) -> str:
    start = re.search(r"\*\*\*\s*START OF.*?\*\*\*", raw)
    end = re.search(r"\*\*\*\s*END OF", raw)
    return raw[start.end() if start else 0: end.start() if end else len(raw)]


def _paragraphs(body: str) -> List[str]:
    out = []
    for block in re.split(r"\n\s*\n", body.replace("\r", "")):
        text = " ".join(line.strip() for line in block.splitlines() if line.strip())
        text = re.sub(r"_([^_]+)_", r"\1", text)          # _italics_ → italics
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        letters = [c for c in text if c.isalpha()]
        if len(text.split()) < 12 or (letters and sum(c.isupper() for c in letters) > 0.5 * len(letters)):
            continue                                       # headings, notes, short lines
        if re.search(r"\[(Illustration|Footnote)|^CHAPTER\b|\bgutenberg\b", text, re.I):
            continue
        out.append(text)
    return out


def clean_passage(corpus_id: str) -> Optional[str]:
    path = CORPORA / f"{corpus_id}.txt"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    # The catalog is not always right about a download's language (its
    # "Lovecraft" file is a Finnish book): trust Gutenberg's own header.
    language = re.search(r"^Language:\s*(\w+)", raw[:5000], re.M)
    if not language or language.group(1).lower() != "english":
        print(f"  skipped {corpus_id}: not in English")
        return None
    paras = _paragraphs(_body(raw))
    if not paras:
        return None
    taken, words = [], 0
    for para in paras[int(len(paras) * START_OVERRIDE.get(corpus_id, START_AT)):]:
        if words + len(para.split()) > MAX_WORDS and words >= MIN_WORDS:
            break
        if words + len(para.split()) > MAX_WORDS:
            continue                                       # one paragraph too long: skip it
        taken.append(para)
        words += len(para.split())
        if words >= MIN_WORDS:
            break
    return "\n".join(taken) if words >= MIN_WORDS // 2 else None


# ── Seeded mistakes ─────────────────────────────────────────────────────

MISSPELLINGS = {
    "receive": "recieve", "believe": "beleive", "separate": "seperate", "tomorrow": "tommorow",
    "definitely": "definately", "occurred": "occured", "until": "untill", "beginning": "begining",
    "which": "wich", "because": "becuase", "friend": "freind", "thought": "thougth",
    "through": "throught", "really": "realy", "strength": "strenght", "different": "diffrent",
    "across": "accross", "probably": "probaly", "suddenly": "suddently", "believed": "beleived",
    "himself": "himslef", "nothing": "nothign", "something": "somthing", "without": "withuot",
    "another": "anotehr", "against": "agianst", "almost": "allmost", "always": "allways",
    "people": "poeple", "little": "littel", "before": "befor", "would": "woudl",
}
CONFUSED = [                      # (pattern, replacement, label)
    (r"\bcould have\b", "could of", "could have → could of"),
    (r"\bwould have\b", "would of", "would have → would of"),
    (r"\bshould have\b", "should of", "should have → should of"),
    (r"\bmore than\b", "more then", "than → then"),
    (r"\brather than\b", "rather then", "than → then"),
    (r"\bless than\b", "less then", "than → then"),
    (r"\bit is\b", "its", "it is → its"),
    (r"\bthey are\b", "there are", "they are → there are"),
    (r"\byou are\b", "your", "you are → your"),
    (r"\btheir\b", "there", "their → there"),
    (r"\bits\b", "it's", "its → it's"),
    (r"\bto lose\b", "to loose", "lose → loose"),
    (r"\bthan\b", "then", "than → then"),
    (r"\bthere\b", "their", "there → their"),
    (r"\bwhere\b", "were", "where → were"),
    (r"\bto(?= [a-z]+\b)", "too", "to → too"),
]
AGREEMENT = [
    (r"\bthey were\b", "they was"), (r"\bwe were\b", "we was"), (r"\byou were\b", "you was"),
    (r"\bhe has\b", "he have"), (r"\bshe has\b", "she have"), (r"\bit has\b", "it have"),
    (r"\bthey have\b", "they has"), (r"\bhe does\b", "he do"), (r"\bshe does\b", "she do"),
    (r"\bhe doesn['’]t\b", "he don't"), (r"\bshe doesn['’]t\b", "she don't"),
    (r"\bthere are\b", "there is"), (r"\bI am\b", "I is"), (r"\bhe was\b", "he were"),
    (r"\bshe was\b", "she were"),
]
PUNCTUATION = [
    (r"\bdon['’]t\b", "dont", "missing apostrophe"), (r"\bdidn['’]t\b", "didnt", "missing apostrophe"),
    (r"\bcan['’]t\b", "cant", "missing apostrophe"), (r"\bwasn['’]t\b", "wasnt", "missing apostrophe"),
    (r"\bI['’]m\b", "Im", "missing apostrophe"), (r"\bit['’]s\b", "its", "missing apostrophe"),
    (r"(\w), (\w)", r"\1 , \2", "space before a comma"),
    (r"\. ([A-Z][a-z]+)", None, "no capital after a full stop"),
]
REPEATS = ["the", "a", "to", "and", "of", "in"]


def _choose(rng: random.Random, text: str, pattern: str, taken: List[Tuple[int, int]]):
    """A random match of ``pattern`` that does not touch an earlier change."""
    matches = [m for m in re.finditer(pattern, text)
               if all(m.end() + 2 < a or m.start() - 2 > b for a, b in taken)]
    return rng.choice(matches) if matches else None


def seed_mistakes(text: str, rng: random.Random) -> Tuple[str, List[Dict]]:
    """Insert one mistake of each kind where the passage allows. Returns the
    new text and the insertions, with offsets into the new text."""
    plans = []                       # (start, end, new text, kind, label)
    taken: List[Tuple[int, int]] = []

    def plan(m, new, kind, label):
        plans.append((m.start(), m.end(), new, kind, label))
        taken.append((m.start(), m.end()))

    # Spelling: a common misspelling if the word is there, else a transposed letter.
    words = [w for w in MISSPELLINGS if re.search(rf"\b{w}\b", text)]
    rng.shuffle(words)
    m = _choose(rng, text, rf"\b{words[0]}\b", taken) if words else None
    if m:
        plan(m, MISSPELLINGS[m.group(0)], "spelling", f"{m.group(0)} → {MISSPELLINGS[m.group(0)]}")
    else:
        m = _choose(rng, text, r"\b[a-z]{7,}\b", taken)
        if m:
            w = m.group(0)
            i = rng.randrange(2, len(w) - 3)
            typo = w[:i] + w[i + 1] + w[i] + w[i + 2:]
            plan(m, typo, "spelling", f"{w} → {typo}")

    for kind, options in (("confused_word", CONFUSED), ("agreement", AGREEMENT)):
        options = list(options)
        rng.shuffle(options)
        for option in options:
            pattern, new = option[0], option[1]
            m = _choose(rng, text, pattern, taken)
            if m:
                label = option[2] if len(option) > 2 else f"{m.group(0)} → {new}"
                plan(m, new, kind, label)
                break

    options = list(PUNCTUATION)
    rng.shuffle(options)
    for pattern, new, label in options:
        m = _choose(rng, text, pattern, taken)
        if not m:
            continue
        if new is None:                                  # lower-case the next sentence
            replacement = ". " + m.group(1)[0].lower() + m.group(1)[1:]
        else:
            replacement = m.expand(new)
        plan(m, replacement, "punctuation", label)
        break

    word = rng.choice(REPEATS)
    m = _choose(rng, text, rf"\b{word}\b", taken)
    if m:
        plan(m, f"{word} {word}", "repeated_word", f"{word} {word}")

    out, insertions, shift = text, [], 0
    for start, end, new, kind, label in sorted(plans):
        a, b = start + shift, end + shift
        out = out[:a] + new + out[b:]
        insertions.append({"kind": kind, "start": a, "end": a + len(new), "text": new,
                           "original": text[start:end], "change": label})
        shift += len(new) - (end - start)
    return out, insertions


# ── Build ───────────────────────────────────────────────────────────────

def build() -> Dict[str, int]:
    rng = random.Random(SEED)
    (OUT / "clean").mkdir(parents=True, exist_ok=True)
    (OUT / "seeded").mkdir(parents=True, exist_ok=True)
    manifest, counts = [], {"clean": 0, "seeded": 0, "insertions": 0, "words": 0}
    for corpus_id, genre, title, year in BOOKS:
        text = clean_passage(corpus_id)
        if text is None:
            print(f"  skipped {corpus_id}: not downloaded")
            continue
        name = corpus_id.replace("gutenberg-", "")
        (OUT / "clean" / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        seeded, insertions = seed_mistakes(text, rng)
        (OUT / "seeded" / f"{name}.json").write_text(json.dumps(
            {"source": name, "text": seeded, "insertions": insertions}, indent=1,
            ensure_ascii=False) + "\n", encoding="utf-8")
        manifest.append({"file": f"{name}.txt", "title": title, "genre": genre, "year": year,
                         "words": len(text.split()), "source": f"Project Gutenberg ({corpus_id})",
                         "license": "public domain in the US"})
        counts["clean"] += 1
        counts["seeded"] += 1
        counts["insertions"] += len(insertions)
        counts["words"] += len(text.split())
    (OUT / "clean" / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False)
                                                 + "\n", encoding="utf-8")
    return counts


if __name__ == "__main__":
    c = build()
    print(f"benchmark/: {c['clean']} clean passages ({c['words']:,} words), "
          f"{c['seeded']} seeded passages with {c['insertions']} known mistakes.")
    sys.exit(0 if c["clean"] else 1)
