"""Measure the voice-group thresholds on published books (piece V.2).

The voice groups (src/ai/voice_groups.py) need three constants: how far
apart two samples of ONE voice land by chance (SAME), how far apart two
DIFFERENT voices are at the least (APART), and how many ratings a source
needs before its fingerprint can be trusted (MIN_SOURCE_RATINGS). This
script measures them on text whose answer is known: the public-domain
books already downloaded for the genre baseline (P.3;
~/.creativeos/corpus_downloads, read only), one author per book.

Each book is cut into passages the size of a rating's text (150 to 300
words of running prose, which is what the writer's ratings carry: median
about 190 words) and each passage is fingerprinted (V.1).

- same voice: two random halves of one book's passages, n each, many
  times; the separation between the halves.
- different voices: n passages from each of two books by different
  authors.

    SAME  = 95th percentile of the same-voice figures (at n = MIN)
    APART = max(1.5 x SAME, 10th percentile of the different-author figures)
    MIN_SOURCE_RATINGS = the smallest n at which the same-voice 95th
                         percentile is within a tenth of its large-sample
                         value (the mean at the three largest sizes)

It also measures the two-voice test (a source split two ways): how often
one book wrongly splits, and how often two authors mixed in one source
are found.

    venv/bin/python scripts/voice_thresholds.py                 # the table
    venv/bin/python scripts/voice_thresholds.py --reps 40 --max-books 60
    venv/bin/python scripts/voice_thresholds.py --writer        # also the writer's sources (read only)

Nothing is written anywhere. No model. A few minutes at the defaults.
"""

import argparse
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIZES = (5, 10, 15, 20, 25, 30, 40, 50, 60, 80)


def _author(path: Path, cid: str) -> str:
    from src.data.corpus_catalog import find_entry
    e = find_entry(cid)
    if e is not None and (e.author or "").strip():
        return e.author.strip().lower()
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:3000]
    except OSError:
        return cid
    m = re.search(r"^Author:\s*(.+)$", head, re.M)
    return m.group(1).strip().lower() if m else cid


def _body_paragraphs(text: str):
    """Paragraphs of running prose: by chapter when the book has chapter
    headings, else the body between Gutenberg's markers, the first and
    last twentieth (front and back matter) dropped."""
    from src.ai.genre_baseline import chapters_of
    chapters = chapters_of(text)
    if len(chapters) < 3:
        t = text.replace("\r\n", "\n")
        start, end = t.find("*** START"), t.find("*** END")
        body = t[max(start, 0): end if end > 0 else None]
        body = re.sub(r"(?<!\n)\n(?!\n)", " ", body)
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        cut = len(paras) // 20
        chapters = ["\n\n".join(paras[cut: len(paras) - cut])]
    for chapter in chapters:
        yield [p.strip() for p in re.split(r"\n\s*\n", chapter) if p.strip()]


def passages_of(text: str, rng: random.Random, lo: int = 150, hi: int = 300):
    """Running prose cut at paragraph ends into passages of lo..hi words
    (a heading or a short line alone is not prose: needs 4+ words)."""
    out = []
    for paras in _body_paragraphs(text):
        buf, words, target = [], 0, rng.randint(lo, hi)
        for p in paras:
            if len(p.split()) < 4:
                continue
            buf.append(p)
            words += len(p.split())
            if words >= target:
                if words <= hi * 2:
                    out.append("\n\n".join(buf))
                buf, words, target = [], 0, rng.randint(lo, hi)
    return out


def load_books(max_books: int, max_passages: int, rng: random.Random):
    from src.ai.genre_baseline import downloaded_books
    from src.ai import voice_fingerprint as vf
    seen, books = set(), []
    for _genre, title, f in downloaded_books():
        if f in seen:
            continue
        seen.add(f)
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ps = passages_of(text, rng)
        if len(ps) > max_passages:            # keep book order: an even spread
            step = len(ps) / max_passages
            ps = [ps[int(i * step)] for i in range(max_passages)]
        vecs = [v for v in (vf.vector_of(p) for p in ps) if v is not None]
        if len(vecs) >= 40:
            books.append({"title": title, "author": _author(f, f.stem),
                          "vectors": np.asarray(vecs, dtype=float)})
        if len(books) >= max_books:
            break
    return books


def pct(values, q):
    return float(np.percentile(values, q)) if len(values) else float("nan")


def same_voice(books, n, reps, rng):
    from src.ai.voice_groups import separation
    out = []
    for b in books:
        v = b["vectors"]
        if len(v) < 2 * n:
            continue
        for _ in range(reps):
            idx = rng.sample(range(len(v)), 2 * n)
            out.append(separation(v[idx[:n]], v[idx[n:]]))
    return out


def same_voice_contiguous(books, n, reps, rng):
    """First half of the book against its second half (chapters differ)."""
    from src.ai.voice_groups import separation
    out = []
    for b in books:
        v = b["vectors"]
        h = len(v) // 2
        if h < n:
            continue
        for _ in range(reps):
            out.append(separation(v[rng.sample(range(h), n)],
                                  v[[h + i for i in rng.sample(range(len(v) - h), n)]]))
    return out


def different_voice(books, n, pairs, rng):
    from src.ai.voice_groups import separation
    cand = [(i, j) for i in range(len(books)) for j in range(i + 1, len(books))
            if books[i]["author"] != books[j]["author"]
            and len(books[i]["vectors"]) >= n and len(books[j]["vectors"]) >= n]
    rng.shuffle(cand)
    out = []
    for i, j in cand[:pairs]:
        a, b = books[i]["vectors"], books[j]["vectors"]
        out.append(separation(a[rng.sample(range(len(a)), n)], b[rng.sample(range(len(b)), n)]))
    return out


def same_author(books, n, rng):
    from src.ai.voice_groups import separation
    out = []
    for i in range(len(books)):
        for j in range(i + 1, len(books)):
            if books[i]["author"] == books[j]["author"]:
                a, b = books[i]["vectors"], books[j]["vectors"]
                if len(a) >= n and len(b) >= n:
                    out.append(separation(a[rng.sample(range(len(a)), n)],
                                          b[rng.sample(range(len(b)), n)]))
    return out


def split_rates(books, n_half, threshold, rng, min_side, reps=300):
    """The two-voice test on sources of 2 x n_half passages, as the app runs
    it (2-means, each side at least min_side): how often one book is split
    wrongly, and how often a mix of two authors is found (all pairs, and
    pairs whose voices are far apart: separation 1.0 or more)."""
    from src.ai.voice_groups import separation, two_means
    def test(v):
        side = two_means(v)
        if side is None:
            return False, 0.0
        a, b = v[side], v[~side]
        if len(a) < min_side or len(b) < min_side:
            return False, 0.0
        s = separation(a, b)
        return s >= threshold, s
    out = {"false": 0, "one": 0, "found": 0, "tried": 0, "far_found": 0, "far_tried": 0, "one_s": []}
    for b in books:
        if len(b["vectors"]) < 2 * n_half:
            continue
        v = b["vectors"][rng.sample(range(len(b["vectors"])), 2 * n_half)]
        hit, sep = test(v)
        out["false"] += hit
        out["one"] += 1
        out["one_s"].append(sep)
    cand = [(i, j) for i in range(len(books)) for j in range(i + 1, len(books))
            if books[i]["author"] != books[j]["author"]
            and len(books[i]["vectors"]) >= n_half and len(books[j]["vectors"]) >= n_half]
    rng.shuffle(cand)
    for i, j in cand[:reps]:
        a, b = books[i]["vectors"], books[j]["vectors"]
        v = np.vstack([a[rng.sample(range(len(a)), n_half)], b[rng.sample(range(len(b)), n_half)]])
        hit, _ = test(v)
        out["found"] += hit
        out["tried"] += 1
        if separation(a, b) >= 1.0:
            out["far_found"] += hit
            out["far_tried"] += 1
    return out


def writer_sources():
    """The writer's real sources, from ~/.creativeos/rephrase_history.db
    opened READ ONLY; fingerprints computed in memory, nothing stored,
    grouped by the app's own code (src/ai/voice_groups.py) in memory."""
    from src.ai import voice_fingerprint as vf
    from src.ai import voice_groups as vg
    path = Path.home() / ".creativeos" / "rephrase_history.db"
    if not path.is_file():
        print("No ratings database.")
        return
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    got = conn.execute(
        "SELECT id, project_path, character_name, notes, source_text, surrounding_before, "
        "surrounding_after FROM rephrases WHERE source_type = 'rephrase' ORDER BY id").fetchall()
    conn.close()
    rows, skipped = [], 0
    for rid, p, ch, notes, s, b, a in got:
        fp = vf.fingerprint(vf.rating_text(b or "", s or "", a or ""))
        rows.append({"id": rid, "project_path": p or "", "character_name": ch or "",
                     "notes": notes or "", "status": fp.status, "vector": fp.vector})
    elig = [r for r in rows if vg.eligible(r)]
    print(f"\nThe writer's ratings (read only, fingerprints in memory): {len(rows)} rated rewrites, "
          f"{len(elig)} grouped (the rest: made from corpora, no project, or too little text)")
    srcs = vg.collect_sources(elig)
    for k, s in sorted(srcs.items()):
        print(f"  {s.label}: {len(s.ids)} ratings of {s.passages} distinct passages"
              f"{'' if s.passages >= vg.MIN_SOURCE_RATINGS else '  (Unsorted: too few)'}")
    keys = sorted(srcs)
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            a, b = srcs[x], srcs[y]
            if a.passages >= 2 and b.passages >= 2:
                print(f"  {a.label}  vs  {b.label}: separation "
                      f"{vg.separation(a.matrix(), b.matrix()):.2f} (n = {a.passages}, {b.passages})")
    for k in keys:
        s = srcs[k]
        if s.passages >= 2 * vg.MIN_SOURCE_RATINGS:
            m = s.matrix()
            side = vg.two_means(m)
            if side is not None:
                print(f"  {s.label} split two ways: {int(side.sum())} / {int((~side).sum())} passages, "
                      f"separation {vg.separation(m[side], m[~side]):.2f}")
    one = vg.regroup(rows, None, now="calibration")
    two = vg.regroup(rows, one, now="calibration")
    print(f"  Groups the app would make: {len(one['groups'])}")
    for gid, g in sorted(one["groups"].items()):
        print(f"    {gid}: {vg.display_name(g)} ({g['strength']}): "
              f"{', '.join(one['sources'][k]['label'] for k in g['sources'])}")
    same = {k: v["group"] for k, v in one["sources"].items()} == \
           {k: v["group"] for k, v in two["sources"].items()}
    print(f"  Rebuilt a second time: {'the same groups' if same else 'DIFFERENT groups'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=300, help="samples per book and size")
    ap.add_argument("--pairs", type=int, default=800, help="author pairs per size")
    ap.add_argument("--max-books", type=int, default=150)
    ap.add_argument("--max-passages", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--writer", action="store_true", help="also the writer's real sources (read only)")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    t0 = time.time()
    books = load_books(args.max_books, args.max_passages, rng)
    if len(books) < 4:
        print("Too few downloaded books (need 4 or more in ~/.creativeos/corpus_downloads).")
        return 1
    largest = SIZES[-1]
    # One fixed set of books for the same-voice figures at every size, so
    # the figures change with n and not with which books are long enough.
    long_books = [b for b in books if len(b["vectors"]) >= 2 * largest]
    authors = len({b["author"] for b in books})
    print(f"{len(books)} books ({len(long_books)} with {2 * largest}+ passages), {authors} authors, "
          f"{sum(len(b['vectors']) for b in books)} passages of 150-300 words, "
          f"{time.time() - t0:.0f} s to fingerprint")

    print("\nSeparation (0 = alike), n passages on each side:")
    print("   n | one voice: book halves     | one voice: random halves | different authors")
    print("     |   p50    p95    count      |   p50    p95             |   p10    p50   within book-halves p95")
    table = {}
    for n in SIZES:
        c = same_voice_contiguous(long_books, n, args.reps, rng)
        s = same_voice(long_books, n, args.reps, rng)
        d = different_voice(books, n, args.pairs, rng)
        table[n] = (c, s, d)
        c95 = pct(c, 95)
        over = (np.asarray(d) <= c95).mean() if d else float("nan")
        print(f"{n:4d} | {pct(c, 50):5.2f}  {c95:5.2f}  {len(c):6d}      | "
              f"{pct(s, 50):5.2f}  {pct(s, 95):5.2f}             | {pct(d, 10):5.2f}  {pct(d, 50):5.2f}"
              f"   {over:5.1%}")

    # The large-sample value: the mean of the p95 at the three largest
    # sizes (one size alone is noisy: a book has only so many passages).
    big95 = float(np.mean([pct(table[n][0], 95) for n in SIZES[-3:]]))
    min_n = largest
    for n in SIZES:
        if pct(table[n][0], 95) <= 1.1 * big95:
            min_n = n
            break
    same = pct(table[min_n][0], 95)
    d10 = pct(table[min_n][2], 10)
    apart = max(1.5 * same, d10)
    print(f"\nMIN_SOURCE_RATINGS = {min_n}   (book-halves p95 within a tenth of the large-sample value, {big95:.2f}, the mean at n = {", ".join(map(str, SIZES[-3:]))})")
    print(f"SAME  = {same:.2f}   (book-halves p95 at n = {min_n})")
    print(f"APART = {apart:.2f}   (max of 1.5 x SAME = {1.5 * same:.2f} and different-author p10 = {d10:.2f})")
    d = np.asarray(table[min_n][2])
    c = np.asarray(table[min_n][0])
    print(f"Overlap at n = {min_n}: {np.mean(d <= same):.1%} of different-author pairs within SAME; "
          f"{np.mean(c >= apart):.1%} of one-book halves at or beyond APART")
    rs = np.asarray(table[min_n][1])
    print(f"(Random halves at n = {min_n}: p95 {pct(rs, 95):.2f}; the separation removes chance, "
          f"so two shuffled halves of one book land near 0 and the figure keeps falling with n.)")
    sa = same_author(books, min_n, rng)
    if sa:
        print(f"Same author, different books (n = {min_n}): {len(sa)} pairs, "
              f"p50 {pct(sa, 50):.2f}, p95 {pct(sa, 95):.2f}, within SAME {np.mean(np.asarray(sa) <= same):.0%}")

    print("\nTwo-voice test (2-means on one source, each side at least MIN):")
    for n_half in (min_n, 2 * min_n):
        r = split_rates(books, n_half, apart, random.Random(args.seed + n_half), min_n)
        keep, split = pct(r["one_s"], 95), pct(r["one_s"], 99)
        r2 = split_rates(books, n_half, max(apart, split), random.Random(args.seed + n_half), min_n)
        print(f"  sources of {2 * n_half}: one book split two ways lands p50 {pct(r['one_s'], 50):.2f}, "
              f"p95 {keep:.2f}, p99 {split:.2f} apart")
        print(f"    at APART ({apart:.2f}): one book split wrongly {r['false']}/{r['one']}; "
              f"two authors found {r['found']}/{r['tried']} (far apart: {r['far_found']}/{r['far_tried']})")
        print(f"    at p99 ({split:.2f}): one book split wrongly {r2['false']}/{r2['one']}; "
              f"two authors found {r2['found']}/{r2['tried']} (far apart: {r2['far_found']}/{r2['far_tried']})")
    print(f"\n{time.time() - t0:.0f} s in all")
    if args.writer:
        writer_sources()
    return 0


if __name__ == "__main__":
    sys.exit(main())
