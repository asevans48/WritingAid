# Benchmark for the checks

Passages with the right answers stored beside them, so the app can say how
often each check is right (piece Q.1). `scripts/score_checks.py` scores every
check against them (piece Q.2) and writes `docs/publishing/check_scores.md`.

| Folder | What | The right answer |
|---|---|---|
| `clean/` | 12 passages of well-edited published fiction, about 350 words each, one per book, in eight genres (1898–1925, public domain in the US, from Project Gutenberg). `manifest.json` lists each source. | Almost nothing should be flagged. |
| `seeded/` | The same passages with known mistakes inserted: spelling, confused words, agreement, punctuation, repeated words (58 in all). | The `insertions` list in each file: kind, offsets, the change made. |
| `style/marked.json` | 24 short passages written for the benchmark, with every style problem marked by hand. Each mark says whether a flag there would be **right** (a real weakness) or **wrong** (a deliberate choice: a character's voice, a fragment, a passive that fits). | The marks. A flag of a kind that matches no mark of that kind counts as wrong. |

**Rebuilding** `clean/` and `seeded/`:

    venv/bin/python scripts/build_benchmark.py

It reads the Gutenberg downloads the app keeps in
`~/.creativeos/corpus_downloads`, checks each book's own `Language:` header
(the catalog's "Lovecraft" download is a Finnish book), and always produces
the same passages and the same mistakes (fixed offsets and random seed).
`style/marked.json` is written by hand and is not touched by the script.

**Scoring:**

    venv/bin/python scripts/score_checks.py --languagetool    # as the app runs
    venv/bin/python scripts/score_checks.py                   # built-in grammar rules only
    venv/bin/python scripts/score_checks.py --model           # also with the configured model judging

**The marks are a draft.** They are one editor's judgment, made when the set
was built, and the writer should review them: a style check's score can move a
lot on a single mark. Change a mark by editing `style/marked.json` (set
`flag` to `true` or `false`, and say why), then score again.

Nothing here comes from the writer's own projects.
