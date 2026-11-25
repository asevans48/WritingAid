"""Compute the genre baseline once (piece P.3) and store it.

Measures every public-domain book the Training Studio has downloaded
(~/.creativeos/corpus_downloads) that a genre lists in src/data/genres.py,
with the readiness checks' own code, and writes the per-genre ranges to
~/.creativeos/genre_baseline.json. The readiness checks read that file;
without it they keep their fixed figures. A genre with fewer than five
books is stored but not used ("too little data").

When CONLIT (the Training Studio's statistics for about 2,750 contemporary
books, ~/.creativeos/conlit/CONLIT_META.csv or the path in
~/.creativeos/conlit_path.txt) is there, sentence length comes from it for
the genres it has five or more books for (mystery, science fiction,
romance; historical fiction stands in for literary), converted from its
tokens per sentence to the app's words per sentence. Other measures are
always the Gutenberg books'.

    venv/bin/python scripts/genre_baseline.py            # build and store
    venv/bin/python scripts/genre_baseline.py --show     # print what is stored
    venv/bin/python scripts/genre_baseline.py --corpus DIR --no-write
    venv/bin/python scripts/genre_baseline.py --conlit CONLIT_META.csv   # or --no-conlit

Nothing is downloaded. Takes about a second a chapter.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def show(data) -> None:
    from src.ai import genre_baseline as gb
    genres = data.get("genres") or {}
    if not genres:
        print("No genre baseline stored.")
        return
    print(f"Source: {data.get('source', '?')} ({data.get('made_at', '?')})\n")
    conlit = data.get("conlit")
    if conlit:
        print(f"CONLIT: {conlit.get('books', 0):,} books; sentence lengths divided by "
              f"{conlit.get('ratio')} (tokens per word, likely {conlit.get('ratio_range')}).")
        print(f"  Books per genre: {conlit.get('genres') or 'none mapped'}")
        print(f"  Check: median characters per token {conlit.get('chars_per_token')}, "
              f"word length {conlit.get('avg_word_length')}. If punctuation counts as a token "
              "expect about 4.5 and 3.7; if not, about 5.3 and 4.2.\n")
    else:
        print("CONLIT: not used (not found when this was built).\n")
    for genre, block in sorted(genres.items()):
        n = block.get("books", 0)
        flag = "" if n >= gb.MIN_BOOKS else f"   (too little data: {gb.MIN_BOOKS} books needed)"
        print(f"{genre}: {n} books{flag}")
        for m, v in (block.get("measures") or {}).items():
            note = ("   not used: the same in every book" if v['p90'] <= v['p10'] else "")
            count = (f"{v['books']:,} CONLIT books" if v.get("source") == "conlit"
                     else f"{v['chapters']} chapters")
            print(f"    {m:17} {v['p10']:>8} {v['p50']:>8} {v['p90']:>8}   ({count}){note}")
        print(f"    sentence length from: {_sentence_source(block)}")


def _sentence_source(block) -> str:
    v = (block.get("measures") or {}).get("sentence_length")
    other = (block.get("sentence_length_sources") or {})
    if v and v.get("source") == "conlit":
        g = other.get("gutenberg")
        was = f"; Gutenberg books gave {g['p10']} to {g['p90']}" if g else ""
        return f"CONLIT ({v.get('note', '')}, {v['books']:,} books){was}"
    c = other.get("conlit")
    why = f"; CONLIT has only {c['books']} books" if c else ""
    return f"Gutenberg books measured by the app{why}" if v else "nothing"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=None)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--conlit", type=Path, default=None, help="CONLIT_META.csv")
    ap.add_argument("--no-conlit", action="store_true")
    args = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from src.ai import genre_baseline as gb
    if args.show:
        show(gb.load())
        return 0
    books = gb.downloaded_books(args.corpus)
    print(f"{len(books)} downloaded books listed by a genre")
    conlit = [] if args.no_conlit else gb.load_conlit(args.conlit)
    where = gb.conlit_csv(args.conlit) if not args.no_conlit else None
    print(f"CONLIT: {len(conlit):,} books from {where}" if conlit else
          "CONLIT: not found, sentence length from the Gutenberg books only")
    summary = {} if (conlit or args.no_conlit) else gb.load_conlit_summary()
    if summary:
        print(f"CONLIT: the file is gone, so its saved summary is used "
              f"({gb.conlit_summary_path()}, {summary.get('n_books_total', '?')} books; "
              "10th and 90th percentiles estimated from the mean and spread)")
    data = gb.build_from_downloads(args.corpus, progress=print, conlit=conlit)
    if summary:
        gb.add_conlit_summary(data, summary)
    show(data)
    if not args.no_write:
        print("\nSaved to", gb.baseline_path() if gb.save(data) else "nothing (could not write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
