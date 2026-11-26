"""The proof for voice drift (piece 4.2): can the measure tell an
untouched chapter, one the writer revised, and one a model rewrote apart?

**Result (26 Nov 2026): it cannot, and the piece was dropped.** The
numbers are in the 4.2 brief's *Outcome*. The measure lives here, not in
``src/``, because nothing in the app uses it.

Reads only. No model is run: the model rewrites are the ones already in
the ratings database (opened read-only, ``mode=ro``), each beside the
writer's original.

    venv/bin/python scripts/voice_drift_gate.py                 # published books only
    venv/bin/python scripts/voice_drift_gate.py --writer \
        --earlier-drafts "<folder of .docx chapters>"           # and the writer's data

**The measure.** A chapter is cut into passages of about
:data:`PASSAGE_WORDS` words at paragraph ends; each passage gets V.1's
voice fingerprint (``voice_fingerprint``: the 23 measures of
``writer_voice``). A chapter's drift is V.2's separation
(``voice_groups.separation``) between its passages and those of every
other chapter of the manuscript: the distance between the means in
within-voice spreads, less the part chance gives (0 = the book's voice).

1. **Published books** (the downloaded Gutenberg books, P.3): every
   chapter against the rest of its book (untouched), and against a book
   by another author (a different voice). Gives the bar ``MOVED``.
2. **The writer, untouched:** each chapter of their projects against the
   rest of the same manuscript (and of the earlier drafts).
3. **The writer, revised:** the current chapters against the earlier
   drafts of the same book, and the chapter's own two revisions.
4. **A model's rewrites** of the writer's passages: a) wholly rewritten
   sets against the writer's versions of the same passages; b) rewrites
   in their own context, eight to a chapter-sized set, and the rewrite
   mark on each; c) rewrites put in place in the chapter they came from,
   beside the writer's own revised paragraphs.
5. **A word-based measure, for comparison:** the same tests with the
   rates of 100 common words (Burrows-style) instead of the 23 measures.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import os
import random
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ai import voice_fingerprint as vf  # noqa: E402
from src.ai import voice_groups as vg  # noqa: E402

# ── The measure ──────────────────────────────────────────────────────

PASSAGE_WORDS = 200          # V.2 calibrated on 150-300-word passages (median ~190)
MIN_PASSAGES = 4             # a chapter needs ~800 measurable words to be judged
MIN_BASELINE_PASSAGES = 12   # and the rest of the book ~2,400
MOVED = 0.70                 # published untouched chapters: ~96% fall below it
PASSAGE_PERCENTILE = 95      # rewrite mark: the passage reads less like the book than this
REWRITE_STEP = 0.35          # ...and at least this much further than before
MIN_CHANGED_WORDS = 8        # a change of fewer words is never marked
_SPREAD_FLOOR = 0.1


def passages(text: str, target: int = PASSAGE_WORDS):
    """Running prose cut at paragraph ends into passages of about
    ``target`` words (lines under four words skipped; a last passage of at
    least half the target kept)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", (text or "").replace("\r\n", "\n"))
             if len(p.split()) >= 4]
    out, buf, words = [], [], 0
    for p in paras:
        buf.append(p)
        words += len(p.split())
        if words >= target:
            out.append("\n\n".join(buf))
            buf, words = [], 0
    if buf and words >= target // 2:
        out.append("\n\n".join(buf))
    return out


def vectors(text: str):
    """The fingerprint of each measurable passage."""
    return [v for v in (vf.vector_of(p) for p in passages(text)) if v is not None]


class Drift:
    def __init__(self, score, moves):
        self.score, self.moves = score, moves

    @property
    def flagged(self) -> bool:
        return self.score >= MOVED


def _stats(base):
    mu = base.mean(axis=0)
    return mu, np.maximum(base.std(axis=0), _SPREAD_FLOOR * (np.abs(mu) + 1.0))


def _phrase(measure: str, up: bool) -> str:
    return f"{'more' if up else 'less'} {vf.LABELS.get(measure, measure)}"


def moves(a, b, top: int = 2):
    """The measures that moved most, in plain words."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape[1] != len(vf.MEASURES):
        return []                                   # the word-based measure: no labels
    mu, sd = _stats(b)
    z = (a.mean(axis=0) - mu) / sd
    return [_phrase(vf.MEASURES[i], z[i] > 0) for i in np.argsort(-np.abs(z))[:top]
            if abs(z[i]) >= 0.5]


def drift(chapter_vectors, baseline_vectors):
    """A chapter's passages against the baseline's; None when too small."""
    if len(chapter_vectors) < MIN_PASSAGES or len(baseline_vectors) < MIN_BASELINE_PASSAGES:
        return None
    score = vg.separation(chapter_vectors, baseline_vectors)
    if score != score:
        return None
    return Drift(round(float(score), 2), moves(chapter_vectors, baseline_vectors))


def book_drift(chapter_vectors):
    """Each chapter against every other chapter (leave one out)."""
    out = {}
    for cid, mine in chapter_vectors.items():
        d = drift(mine, [v for o, vs in chapter_vectors.items() if o != cid for v in vs])
        if d is not None:
            out[cid] = d
    return out


def _window(text: str, start: int, end: int, target: int = PASSAGE_WORDS):
    """The paragraphs around ``text[start:end]``, widened until ~``target`` words."""
    ws = text.rfind("\n", 0, start) + 1
    we = text.find("\n", end)
    we = len(text) if we < 0 else we
    while len(text[ws:we].split()) < target and (ws > 0 or we < len(text)):
        if ws > 0:
            ws = text.rfind("\n", 0, max(0, ws - 1)) + 1
        if len(text[ws:we].split()) < target and we < len(text):
            nxt = text.find("\n", we + 1)
            we = len(text) if nxt < 0 else nxt
    return ws, we


def changed_words(old: str, new: str) -> int:
    sm = difflib.SequenceMatcher(None, old.split(), new.split(), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


class RewriteDrift:
    def __init__(self, before, after, far):
        self.before, self.after, self.far = before, after, far

    @property
    def marked(self) -> bool:
        return self.after > self.far and self.after - self.before >= REWRITE_STEP


def rewrite_drift(text: str, start: int, end: int, new: str, book_vectors):
    """The passage around ``text[start:end]`` before and after ``new`` is
    put in, each as its distance from the book's passages (RMS of the
    measures in the book's spreads); ``far`` is the book's own
    PASSAGE_PERCENTILE. None for a change of a few words or too little text."""
    if not text or not (0 <= start <= end <= len(text)):
        return None
    if changed_words(text[start:end], new or "") < MIN_CHANGED_WORDS:
        return None
    if len(book_vectors) < MIN_BASELINE_PASSAGES:
        return None
    ws, we = _window(text, start, end)
    old_v = vf.vector_of(text[ws:we])
    new_v = vf.vector_of(text[ws:start] + (new or "") + text[end:we])
    if old_v is None or new_v is None:
        return None
    base = np.asarray(book_vectors, dtype=float)
    mu, sd = _stats(base)

    def dist(v):
        return float(np.sqrt((((np.asarray(v, dtype=float) - mu) / sd) ** 2).mean()))

    far = float(np.percentile([dist(b) for b in base], PASSAGE_PERCENTILE))
    return RewriteDrift(dist(old_v), dist(new_v), far)


# The word-based measure (section 5): rates of common words per passage.
_WORD = re.compile(r"[a-z']+")
COMMON_WORDS = """the and to of a i in was he that it his her you with for had on at as but
she him they not be is my me all so we have were from them this out up one or what there
would could their no then like into been when an by if just back down over did about said
its only now some through too more before than again even still while who off""".split()


def word_vectors(text: str):
    out = []
    for p in passages(text):
        w = _WORD.findall(p.lower())
        if len(w) >= 100:
            c = Counter(w)
            out.append([100.0 * c[f] / len(w) for f in COMMON_WORDS])
    return out


def pct(xs, *ps):
    xs = np.asarray(xs, dtype=float)
    return " ".join(f"p{p} {np.percentile(xs, p):.2f}" for p in ps) + f" max {xs.max():.2f}"


def share(xs, bar):
    xs = np.asarray(xs, dtype=float)
    return f"{100.0 * (xs >= bar).mean():.1f}%"


# ── 1. Published books ───────────────────────────────────────────────

def published(max_books: int, rng: random.Random):
    from src.ai.genre_baseline import chapters_of, downloaded_books
    sys.path.insert(0, str(ROOT / "scripts"))
    from voice_thresholds import _author
    seen, books = set(), []
    for _g, title, f in downloaded_books():
        if f in seen:
            continue
        seen.add(f)
        try:
            chapters = chapters_of(f.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        pairs = [(vectors(c), word_vectors(c)) for c in chapters]
        pairs = [p for p in pairs if len(p[0]) >= MIN_PASSAGES and len(p[1]) >= MIN_PASSAGES]
        if len(pairs) >= 6:
            books.append({"title": title, "author": _author(f, f.stem),
                          "chapters": [p[0] for p in pairs], "words": [p[1] for p in pairs]})
        if len(books) >= max_books:
            break
    return books


def run_published(books, rng, key="chapters", label="the 23 voice measures"):
    same, other, sizes = [], [], []
    for b in books:
        d = book_drift({str(i): v for i, v in enumerate(b[key])})
        same.extend(x.score for x in d.values())
        sizes.extend(len(v) for v in b[key])
    for b in books:
        others = [o for o in books if o["author"] != b["author"]]
        for ch in b[key]:
            o = rng.choice(others)
            d = drift(ch, [v for c in o[key] for v in c])
            if d is not None:
                other.append(d.score)
    print(f"\n{'1' if key == 'chapters' else '5'}. Published books, {label}: {len(books)} books, "
          f"{len(same)} chapters (median {int(np.median(sizes))} passages of ~{PASSAGE_WORDS} words)")
    print(f"   untouched chapter vs rest of its book : {pct(same, 50, 90, 95, 97, 99)}")
    print(f"   chapter vs a book by another author   : {pct(other, 10, 25, 50, 75)}")
    for bar in ((0.4, 0.5, 0.6, 0.7, 0.8, 1.0) if key == "chapters" else (0.3, 0.4, 0.5, 0.6)):
        print(f"   at {bar:.1f}: untouched flagged {share(same, bar):>6}   other author caught "
              f"{share(other, bar):>6}")
    return same, other


# ── The writer's data (read only) ────────────────────────────────────

def chapter_texts(project_dir: Path):
    """{label: latest revision text} for every chapter folder (novellas too)."""
    out = {}
    dirs = sorted(glob.glob(str(project_dir / "chapters" / "chapter_*")))
    dirs += sorted(glob.glob(str(project_dir / "subprojects" / "*" / "chapters" / "chapter_*")))
    for d in dirs:
        revs = sorted(glob.glob(d + "/revision_*.md"))
        if not revs:
            continue
        with open(revs[-1], encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if len(text.split()) >= 300:
            out[os.path.relpath(d, project_dir)] = text
    return out


def revisions(project_dir: Path):
    """[(label, first revision, last revision)] for chapters with two or more."""
    out = []
    for d in sorted(glob.glob(str(project_dir / "chapters" / "chapter_*"))):
        revs = sorted(glob.glob(d + "/revision_*.md"))
        if len(revs) >= 2:
            a = open(revs[0], encoding="utf-8", errors="ignore").read()
            b = open(revs[-1], encoding="utf-8", errors="ignore").read()
            out.append((os.path.basename(d), a, b))
    return out


def docx_chapters(folder: Path):
    import docx
    out = {}
    for f in sorted(folder.glob("Ch *.docx")):
        d = docx.Document(str(f))
        out[f.stem] = "\n".join(p.text for p in d.paragraphs if p.text.strip())
    return out


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _num(label: str):
    m = re.search(r"(\d+)", label)
    return int(m.group(1)) if m else None


def run_writer(db_path: str, drafts_dir: Path, rng: random.Random):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    paths = [r[0] for r in db.execute(
        "SELECT DISTINCT project_path FROM rephrases WHERE source_type='rephrase' "
        "AND project_path LIKE '%.writerproj'")]
    projects = {}
    for p in paths:
        d = Path(p).parent
        texts = chapter_texts(d) if d.is_dir() else {}
        if len(texts) >= 3:
            projects[Path(p).stem] = (p, d, texts)
    drafts = docx_chapters(drafts_dir) if drafts_dir and drafts_dir.is_dir() else {}

    print("\n2. The writer, untouched: each chapter against the rest of its manuscript")
    untouched = []
    books = dict((k, v[2]) for k, v in projects.items())
    if drafts:
        books["earlier drafts"] = drafts
    vecs = {}
    for name, texts in books.items():
        by_scope = {}
        for label, t in texts.items():
            scope = label.split("/chapters/")[0] if "/chapters/" in label else ""
            by_scope.setdefault(scope, {})[label] = vectors(t)
        for scope, cv in by_scope.items():
            vecs[(name, scope)] = cv
            d = book_drift(cv)
            scores = [x.score for x in d.values()]
            untouched.extend(scores)
            if scores:
                print(f"   {name}{' / ' + scope if scope else ''}: {len(cv)} chapters, "
                      f"{sum(len(v) for v in cv.values())} passages; {len(scores)} judged: "
                      f"{pct(scores, 50, 90)}; at or over {MOVED}: "
                      f"{sum(s >= MOVED for s in scores)}")
    if untouched:
        print(f"   all: {len(untouched)} chapters {pct(untouched, 50, 90, 95)}")

    print("\n3. The writer, revised")
    revised = []
    drafts_vecs = vecs.get(("earlier drafts", ""), {})
    for name, (p, d, texts) in projects.items():
        if not drafts_vecs or "Born in Blood" not in name:
            continue
        for label, t in texts.items():
            n = _num(label)
            same = [k for k in drafts if _num(k) == n]
            base = [v for k, vs in drafts_vecs.items() if k not in same for v in vs]
            dd = drift(vectors(t), base)
            if dd is None:
                continue
            sim = max((similarity(drafts[k], t) for k in same), default=0.0)
            revised.append(dd.score)
            print(f"   {name} {label} (words kept from the earlier draft {sim:.0%}) vs the "
                  f"earlier drafts: {dd.score:.2f} {', '.join(dd.moves)}")
        for label, a, b in revisions(d):
            base = [v for k, vs in drafts_vecs.items() if _num(k) != _num(label) for v in vs]
            for which, t in (("first revision", a), ("last revision", b)):
                dd = drift(vectors(t), base)
                if dd is not None:
                    print(f"   {name} {label} {which} vs the earlier drafts: {dd.score:.2f}")
            sim = similarity(a, b)
            va, vb = vectors(a), vectors(b)
            if len(va) >= 2 and len(vb) >= 2:
                print(f"   {label} first vs last revision ({sim:.0%} of words kept): "
                      f"{vg.separation(va, vb):.2f}")

    print("\n4. A model's rewrites of the writer's passages (no model run here)")
    rows = db.execute(
        "SELECT source_text, output_text, style, notes, project_path, accepted FROM rephrases "
        "WHERE source_type='rephrase' AND style NOT LIKE '%edited%' AND style != 'suggestion' "
        "AND length(output_text) > 40").fetchall()
    sets = {
        "plain (concise / clearer), asked for by the writer":
            [r for r in rows if r[4] and re.match(r"(concise|clearer)", r[2] or "")],
        "in a tone (noir, comedic, light ...), made from Born in Blood passages":
            [r for r in rows if "synthesized=" in (r[3] or "")],
    }
    base_all = [v for (name, _s), cv in vecs.items() for vs in cv.values() for v in vs
                if "Born in Blood" in name or name == "earlier drafts"]
    base_tc = [v for (name, _s), cv in vecs.items() for vs in cv.values() for v in vs
               if "Teller" in name]
    model_scores, control_scores = [], []

    def sets_of(rs, words=1100):
        """Consecutive rows gathered until the writer's side has ``words``."""
        out, cur, n = [], [], 0
        for r in rs:
            cur.append(r)
            n += len(r[0].split())
            if n >= words:
                out.append(cur)
                cur, n = [], 0
        return out

    print("   a) Wholly rewritten: the model's versions of a set of passages against the "
          "writer's versions of the same passages (separation; 0 = one voice)")
    for label, rs in sets.items():
        rs = list(rs)
        rng.shuffle(rs)
        groups = sets_of(rs)
        pair, null = [], []
        for g in groups:
            o, s = vectors("\n".join(r[1] for r in g)), vectors("\n".join(r[0] for r in g))
            if len(o) >= 3 and len(s) >= 3:
                pair.append(vg.separation(o, s))
        for g1, g2 in zip(groups[::2], groups[1::2]):        # two writer sets, no model
            a, b = vectors("\n".join(r[0] for r in g1)), vectors("\n".join(r[0] for r in g2))
            if len(a) >= 3 and len(b) >= 3:
                null.append(vg.separation(a, b))
        if pair:
            model_scores.extend(pair)
            control_scores.extend(null)
            print(f"      {label}: {len(rs)} rewrites, {len(pair)} sets of ~1,100 words")
            print(f"         model vs writer, same passages: {' '.join(f'{x:.2f}' for x in pair)}")
            print(f"         writer vs writer, other passages: {' '.join(f'{x:.2f}' for x in null)}")
            print(f"         at or over {MOVED}: model {sum(x >= MOVED for x in pair)} of "
                  f"{len(pair)}, writer {sum(x >= MOVED for x in null)} of {len(null)}")
        # Pooled: every rewrite at once (the most power the data has), with both measures.
        h = len(rs) // 2
        for name, fn in (("23 voice measures", vectors), ("common words (section 5)", word_vectors)):
            o, s = fn("\n".join(r[1] for r in rs)), fn("\n".join(r[0] for r in rs))
            s1, s2 = fn("\n".join(r[0] for r in rs[:h])), fn("\n".join(r[0] for r in rs[h:]))
            if len(o) >= 3 and len(s) >= 3 and len(s1) >= 2 and len(s2) >= 2:
                print(f"         pooled, {name}: model vs writer {vg.separation(o, s):.2f} "
                      f"({len(o)} and {len(s)} passages); writer's two halves "
                      f"{vg.separation(s1, s2):.2f}")

    print("   b) Partly rewritten: each rewrite in its own ~200 words of context (the "
          "rating's text before and after), eight to a chapter-sized set, against the book")
    ctx_rows = db.execute(
        "SELECT source_text, output_text, surrounding_before, surrounding_after, project_path "
        "FROM rephrases WHERE source_type='rephrase' AND style NOT LIKE '%edited%' "
        "AND style != 'suggestion' AND project_path LIKE '%.writerproj' "
        "AND length(surrounding_before) + length(surrounding_after) >= 600").fetchall()
    mark = [0, 0]
    for proj, base in (("Teller", base_tc), ("Born in Blood", base_all)):
        rs = [r for r in ctx_rows if proj in r[4]]
        w_s, m_s, share_s = [], [], []
        for i in range(0, len(rs) - 7, 8):
            g = rs[i:i + 8]
            w = "\n\n".join(f"{r[2]} {r[0]} {r[3]}" for r in g)
            m = "\n\n".join(f"{r[2]} {r[1]} {r[3]}" for r in g)
            dw, dm = drift(vectors(w), base), drift(vectors(m), base)
            if dw and dm:
                w_s.append(dw.score)
                m_s.append(dm.score)
                share_s.append(sum(len(r[1].split()) for r in g) / max(1, len(m.split())))
        for r in rs:
            text = f"{r[2]} {r[0]} {r[3]}"
            at = len(r[2]) + 1
            rd = rewrite_drift(text, at, at + len(r[0]), r[1], base)
            if rd is not None:
                mark[1] += 1
                mark[0] += rd.marked
        if w_s:
            print(f"      {proj}: {len(rs)} rewrites, {len(w_s)} sets (the model wrote "
                  f"{100 * np.mean(share_s):.0f}% of the words)")
            print(f"         writer's version: {' '.join(f'{x:.2f}' for x in w_s)}")
            print(f"         with the rewrites: {' '.join(f'{x:.2f}' for x in m_s)}")
    print(f"      rewrite mark on these rewrites in context: {mark[0]} of {mark[1]} marked")

    # Rewrites put in place in the chapter they came from.
    print("\n   Each rewrite put in place in its chapter (the rewrite mark):")
    all_books = [(n, t) for n, (p, d, ts) in projects.items() for t in ts.values()]
    all_books += [("earlier drafts", t) for t in drafts.values()]
    marked = {"model": [0, 0], "writer": [0, 0]}
    for name, text in all_books:
        bookv = [v for (bn, _s), cv in vecs.items() if bn == name for vs in cv.values() for v in vs]
        for src, out, style, notes, pp, acc in rows:
            src = src.strip()
            at = text.find(src) if len(src) > 30 else -1
            if at < 0:
                continue
            rd = rewrite_drift(text, at, at + len(src), out, bookv)
            if rd is None:
                continue
            marked["model"][1] += 1
            marked["model"][0] += rd.marked
    # The writer's own revised paragraphs (earlier draft -> current chapter).
    for name, (p, d, texts) in projects.items():
        if "Born in Blood" not in name:
            continue
        bookv = [v for (bn, _s), cv in vecs.items() if bn == name for vs in cv.values() for v in vs]
        for label, t in texts.items():
            for k in [k for k in drafts if _num(k) == _num(label)]:
                old_p = [x for x in drafts[k].split("\n") if x.strip()]
                new_p = [x for x in t.split("\n") if x.strip()]
                sm = difflib.SequenceMatcher(None, old_p, new_p, autojunk=False)
                draft = "\n".join(old_p)
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    if op != "replace":
                        continue
                    old = "\n".join(old_p[i1:i2])
                    at = draft.find(old)
                    rd = rewrite_drift(draft, at, at + len(old), "\n".join(new_p[j1:j2]),
                                          bookv)
                    if rd is None:
                        continue
                    marked["writer"][1] += 1
                    marked["writer"][0] += rd.marked
    for who, (m, n) in marked.items():
        print(f"      {who}'s rewrites measured: {n}; marked {m}"
              + (f" ({100.0 * m / n:.0f}%)" if n else ""))
    return untouched, revised, model_scores, control_scores


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--writer", action="store_true", help="add the writer's data (read only)")
    ap.add_argument("--db", default=str(Path.home() / ".creativeos" / "rephrase_history.db"))
    ap.add_argument("--earlier-drafts", default="", help="a folder of earlier .docx chapters")
    ap.add_argument("--max-books", type=int, default=64)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    t0 = time.time()
    books = published(args.max_books, rng)
    if books:
        run_published(books, rng)
        run_published(books, random.Random(args.seed), key="words",
                      label="rates of 100 common words")
    else:
        print("No downloaded books (P.3): the published calibration is skipped.")
    if args.writer:
        run_writer(args.db, Path(args.earlier_drafts) if args.earlier_drafts else None, rng)
    print(f"\n{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
