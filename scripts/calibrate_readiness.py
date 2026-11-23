"""Rates of each readiness check on published chapters (for THRESHOLDS).

Takes full chapters from the Q.1 benchmark's public-domain books (in
~/.creativeos/corpus_downloads), runs every check through the readiness
engine, one book per project, and prints each check's rate per 1,000 words
at the 50th, 75th, 90th and 100th percentile. Thresholds are then set so a
published chapter normally reads as ready (piece 1.3).

    venv/bin/python scripts/calibrate_readiness.py [--chapters 3]
"""

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CORPUS = Path.home() / ".creativeos" / "corpus_downloads"
HEADING = re.compile(r"\n\s*\n\s*(?:CHAPTER|Chapter|BOOK|[IVXLC]+\.)\s*[IVXLC\d]*[^\n]{0,60}\n", re.M)


def chapters_of(text: str, take: int):
    start = text.find("*** START")
    end = text.find("*** END")
    body = text[start + 1 if start >= 0 else 0: end if end > 0 else None]
    parts = [p.strip() for p in HEADING.split(body)]
    parts = [p for p in parts if 1200 <= len(p.split()) <= 9000]
    mid = len(parts) // 3
    return parts[mid: mid + take]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapters", type=int, default=3)
    args = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from build_benchmark import BOOKS
    from src.ai import readiness as rd
    from src.models.project import Chapter, Manuscript, WriterProject
    from score_checks import story_names
    rates = {}
    statuses = {}
    used = 0
    for corpus_id, genre, title, _year in BOOKS:
        f = CORPUS / f"{corpus_id}.txt"
        if not f.exists():
            continue
        chs = chapters_of(f.read_text(errors="ignore").replace("\r\n", "\n"), args.chapters)
        if not chs:
            print(f"(no chapters found in {corpus_id})")
            continue
        p = WriterProject(name=title, manuscript=Manuscript(title=title))
        p.project_path = str(Path(tempfile.mkdtemp()) / "book.writerproj")
        p.prose_profile.genre = genre
        p.dictionary.words = story_names("\n".join(chs))       # a project would know its names
        for i, t in enumerate(chs):
            ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"{title} {i + 1}",
                         folder_root=p.manuscript.folder_root)
            ch.content = re.sub(r"(?<!\n)\n(?!\n)", " ", t)       # unwrap Gutenberg lines
            p.manuscript.chapters.append(ch)
        report = rd.book_report(p, use_cache=False)
        for cr in report.chapters:
            used += 1
            for name, r in cr.results.items():
                if r.status in ("info", "could_not_check"):
                    continue
                rate = (r.measure if name == "sentence_variety" else
                        r.count if name in ("pacing", "consistency", "dialogue_fit") else
                        r.count * 1000.0 / max(cr.words, 1))
                rates.setdefault(name, []).append(round(rate, 2))
                statuses.setdefault(name, []).append(r.status)
    print(f"{used} published chapters\n")
    print(f"{'check':22} {'p50':>7} {'p75':>7} {'p90':>7} {'max':>7}   current")
    for name, vals in sorted(rates.items()):
        vals = sorted(vals)
        q = lambda x: vals[min(len(vals) - 1, int(round(x * (len(vals) - 1))))]
        th = rd._thresholds().get(name)
        cur = th.per_1000 or th.count if th else ""
        st = statuses.get(name, [])
        share = lambda k: f"{100 * st.count(k) // max(len(st), 1)}%"
        print(f"{name:22} {q(.5):7.1f} {q(.75):7.1f} {q(.9):7.1f} {vals[-1]:7.1f}   {str(cur):14}"
              f" ready {share('ready')}, work {share('needs_work')}, problem {share('problem')}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
