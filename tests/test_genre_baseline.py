"""P.3: every measure compared with the genre.

With genre figures a check's threshold and message come from published
books in the genre; without them, everything is exactly as before; a genre
backed by too few books says so and keeps the fixed figure; the baseline
is computed once, stored and reused.
"""

import json
import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import genre_baseline as gb
from src.ai import readiness as rd
from src.models.project import Chapter, Manuscript, WriterProject

CLEAN = ("Rain came in off the river before dawn. Mara pulled her coat tight and walked "
         "the length of the wharf, counting the boats.\n\n"
         "Three had sailed. The fourth sat low, its hull dark with weed, a lantern swinging "
         "from the mast though no one stood on deck.\n\n"
         "She stopped. Somewhere below, a pump clanked twice and fell silent.\n\n"
         "\"Anyone there?\" she called. Nobody answered, and the gulls went on with their "
         "quarrel over a fish head on the stones.\n") * 4
ADVERBY = CLEAN + ("He walked slowly. She smiled warmly. They spoke quietly and sadly. "
                   "It ended suddenly.\n") * 3


def _project(tmp_path, *texts, genre="thriller"):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / f"book-{uuid.uuid4().hex[:6]}.writerproj")
    p.prose_profile.genre = genre
    for i, t in enumerate(texts):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    return p


def _m(p10, p50, p90, books=12):
    return {"p10": p10, "p50": p50, "p90": p90, "books": books, "chapters": books * 6}


def _store(books=12, genre="thriller", **over):
    measures = {"sentence_length": _m(9.0, 12.0, 16.0, books),
                "sentence_variety": _m(30.0, 45.0, 60.0, books),
                "dialogue_share": _m(35.0, 42.0, 50.0, books),
                "adverbs": _m(2.0, 5.0, 8.0, books),
                "passive": _m(1.0, 2.5, 4.0, books),
                "readability": _m(65.0, 72.0, 80.0, books),
                "chapter_length": _m(2100.0, 3200.0, 4800.0, books)}
    measures.update(over)
    data = {"format_version": 1, "source": "test", "min_books": gb.MIN_BOOKS,
            "genres": {genre: {"books": books, "titles": [], "measures": measures}}}
    gb.baseline_path().write_text(json.dumps(data))
    gb._LOADED["key"] = None
    return data


def _ctx(p, genre="thriller", opening=False):
    ch = p.manuscript.chapters[0]
    return rd.CheckContext(p, None, ch, ch.content, is_opening=opening, route="agent",
                           genre=genre)


def test_without_genre_figures_every_threshold_and_message_is_todays(tmp_path):
    p = _project(tmp_path, ADVERBY, CLEAN)
    ctx = _ctx(p)
    for name in ("adverbs", "passive", "echoes", "spelling_grammar"):
        assert ctx.threshold(name) == rd._thresholds()[name], name
    r = rd.chapter_report(p, p.manuscript.chapters[1]).results
    assert r["adverbs"].message == "" and r["passive"].message == ""
    assert r["pacing"].message == "Measured against Thriller."
    assert r["chapter_length"].message.endswith("(chapters commonly run 2,000–5,000; a rough guide).")
    assert "genre's 45" in r["sentence_variety"].message       # the thriller profile's, as before
    assert "published" not in r["sentence_variety"].message


def test_with_genre_figures_the_threshold_and_message_come_from_the_genre(tmp_path):
    _store()
    p = _project(tmp_path, ADVERBY, CLEAN)
    ctx = _ctx(p)
    assert ctx.threshold("adverbs").per_1000 == (8.0, 12.0)
    assert ctx.threshold("passive").per_1000 == (4.0, 6.0)
    assert ctx.threshold("echoes") == rd._thresholds()["echoes"]          # not a genre measure
    opening = _ctx(p, opening=True).threshold("adverbs").per_1000           # opening: tighter still
    assert opening == (round(8.0 * 0.75, 2), round(12.0 * 0.75, 2))
    assert _ctx(p, genre="romance").threshold("adverbs") == rd._thresholds()["adverbs"]
    r = rd.chapter_report(p, p.manuscript.chapters[0]).results
    adv = r["adverbs"]
    assert "published thrillers 2 to 8 per 1,000 words (12 books)" in adv.message
    assert adv.message.startswith("Adverbs ")
    rate = adv.count * 1000 / max(len(ADVERBY.split()), 1)
    assert adv.status == rd._status_from(rd.Threshold(per_1000=(8.0, 12.0)), adv.count,
                                         len(ADVERBY.split()))
    assert rate > 8.0 and adv.status != rd.Status.READY
    pacing = r["pacing"].message
    assert "Dialogue" in pacing and "published thrillers 35 to 50% (12 books)" in pacing
    assert "Readability" in pacing and "Sentences" in pacing
    assert "published thrillers" in r["sentence_variety"].message
    ln = r["chapter_length"].message
    assert "published thrillers commonly run 2,100–4,800; 12 books" in ln


def test_the_pacing_band_comes_from_the_genre(tmp_path):
    p = _project(tmp_path, CLEAN)
    before = rd.chapter_report(p, p.manuscript.chapters[0]).results["pacing"]
    assert not any("above" in i.reason for i in before.items)
    # A band CLEAN can't fit: its sentences run longer than 2 to 3 words.
    _store(sentence_length=_m(2.0, 2.5, 3.0))
    after = rd.chapter_report(p, p.manuscript.chapters[0]).results["pacing"]
    assert any("above" in i.reason and "(2–3)" in i.reason for i in after.items)
    assert after.count == before.count + 1


def test_too_little_data_keeps_the_fixed_figure_and_says_so(tmp_path):
    _store(books=2)
    p = _project(tmp_path, ADVERBY)
    assert _ctx(p).threshold("adverbs") == rd._thresholds()["adverbs"]
    r = rd.chapter_report(p, p.manuscript.chapters[0]).results
    thin = "Published thrillers: too little data to compare (2 books; 5 needed)"
    for name in ("adverbs", "passive", "pacing", "sentence_variety", "chapter_length"):
        assert thin in r[name].message, name
    assert r["pacing"].message.count(thin) == 1
    assert gb.fingerprint("thriller", used_only=True) == ""


def test_a_measure_the_same_in_every_book_is_not_used(tmp_path):
    """Found on the writer's own run: sentence variety was 100 in every
    published chapter (the score tops out), which would have set the bar at
    100 and flagged nearly every chapter. Such a measure keeps the fixed bar."""
    from src.ai.chapter_analysis_agent import resolve_genre_profile
    _store(sentence_variety=_m(100.0, 100.0, 100.0))
    assert gb.usable("thriller", "sentence_variety") is None
    assert gb.line("thriller", "sentence_variety") == ""
    p = _project(tmp_path, CLEAN)
    r = rd.chapter_report(p, p.manuscript.chapters[0]).results["sentence_variety"]
    fixed = resolve_genre_profile("thriller").variety_score_target
    assert f"{fixed:g}" in r.message and "100 to 100" not in r.message
    assert "sentence variety" not in gb.stricter("thriller")


def test_cached_results_are_recomputed_when_the_figures_arrive(tmp_path):
    p = _project(tmp_path, ADVERBY)
    first = rd.chapter_report(p, p.manuscript.chapters[0])
    again = rd.chapter_report(p, p.manuscript.chapters[0])
    assert again.from_cache == len(again.results)
    _store()
    after = rd.chapter_report(p, p.manuscript.chapters[0])
    assert "published thrillers" in after.results["adverbs"].message
    assert after.from_cache < len(after.results)
    assert first.results["echoes"].status == after.results["echoes"].status
    for name in ("adverbs", "passive", "sentence_variety", "pacing", "chapter_length"):
        assert rd.REGISTRY[name].version == 2


def _to_yesterday(p):
    """Make every history entry an earlier day's (as if checked yesterday)."""
    from src.data import readiness_state as rs

    def change(data):
        for e in rs.manuscript_entry(data, None).get("history") or []:
            e["date"] = "2026-01-01"
    rs.update(p, change)


def test_the_critique_says_once_that_the_comparison_changed(tmp_path, qapp):
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path, ADVERBY, CLEAN)
    first = rd.book_report(p)
    assert "genre_note" not in first.info
    _to_yesterday(p)
    _store()
    second = rd.book_report(p)
    note = second.info.get("genre_note", "")
    assert note.startswith("Now compared with published thrillers (12 books)")
    assert "adverbs and passive voice" in note                    # both stricter than fixed
    sc = ScorecardWidget()
    sc.set_project(p)
    assert "Now compared with published thrillers" in sc._note(second)
    # Said all that day, so a refresh straight after can't swallow it ...
    assert rd.book_report(p).info.get("genre_note") == note
    # ... and not on the next day.
    _to_yesterday(p)
    later = rd.book_report(p)
    assert "genre_note" not in later.info
    assert "Now compared" not in sc._note(later)
    assert later.history[-1]["baseline"] == gb.fingerprint("thriller", used_only=True)


def test_a_change_of_figures_is_not_shown_as_progress(tmp_path):
    from src.data import readiness_state as rs
    p = _project(tmp_path, ADVERBY)
    base = {"readiness": 0.5, "figure_version": rd.FIGURE_VERSION,
            "thresholds_version": rd.THRESHOLDS_VERSION, "majors": 1, "cells": 4}
    rs.record_history(p, None, dict(base, date="2026-11-01"))               # older entry: no key
    rs.record_history(p, None, dict(base, date="2026-11-02", readiness=0.6))
    report = rd.BookReport(scope=None, name="Book", kind="novel",
                           history=rs.history(p, None))
    assert rd.change_since_last(report) == (0.1, "2026-11-01")              # old entries compare
    rs.record_history(p, None, dict(base, date="2026-11-03", readiness=0.9, baseline="abc"))
    report.history = rs.history(p, None)
    assert rd.change_since_last(report) is None                             # measured differently


def test_an_older_readiness_file_opens_and_keeps_its_keys(tmp_path):
    from src.data import readiness_state as rs
    p = _project(tmp_path, CLEAN)
    old = {"format_version": 2, "route": "self", "something_older": {"kept": True},
           "manuscripts": {"main": {"history": [{"date": "2026-11-01", "readiness": 0.5,
                                                 "figure_version": 1, "thresholds_version": 5,
                                                 "majors": 0, "cells": 3}]}}}
    path = rs.readiness_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(old))
    _store()
    book = rd.book_report(p)
    assert book.chapters and "adverbs" in book.chapters[0].results
    saved = json.loads(path.read_text())
    assert saved["something_older"] == {"kept": True} and saved["route"] == "self"
    assert saved["manuscripts"]["main"]["history"][0]["date"] == "2026-11-01"


def _book(title, n=8):
    """A Gutenberg-style book: headings, wrapped lines, chapters of ~600 words."""
    para = ("The night train ran north through the hills, and Hannay watched the dark "
            "fields go by. \"They will be waiting at the junction,\" said the stranger "
            "quietly. Nobody answered him. The carriage was cold and the lamp was dim. "
            "He thought of the letter in his coat, and of the man who had died for it.\n")
    chapters = "".join(f"\n\nCHAPTER {i + 1}\n\n" + (para * 9).replace(". ", ".\n", 2)
                       for i in range(n))
    return f"Title: {title}\n*** START OF THE BOOK ***\n{chapters}\n*** END OF THE BOOK ***\n"


def test_the_baseline_is_computed_once_stored_and_reused(tmp_path, monkeypatch):
    from src.data import genres, safe_store
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    ids = [c for c in genres.GENRES["thriller"]["corpora"] if c.startswith("gutenberg-")]
    for cid in ids:
        (corpus / f"{cid}.txt").write_text(_book(cid))
    found = gb.downloaded_books(corpus)
    assert {g for g, _, _ in found} >= {"thriller"}
    data = gb.build_from_downloads(corpus)
    th = data["genres"]["thriller"]
    assert th["books"] == len(ids) and set(th["measures"]) == set(gb.MEASURES)
    m = th["measures"]
    assert m["chapter_length"]["chapters"] == 8 * len(ids)
    assert m["adverbs"]["chapters"] == gb.CHAPTERS_PER_BOOK * len(ids)
    assert 0 < m["dialogue_share"]["p50"] < 100 and m["sentence_length"]["p10"] > 0
    assert gb.save(data)
    reads = []
    real = safe_store.load
    monkeypatch.setattr(safe_store, "load", lambda *a, **k: reads.append(1) or real(*a, **k))
    gb._LOADED["key"] = None
    for _ in range(5):
        gb.usable("thriller", "adverbs")
    assert len(reads) == 1                                       # read once, then reused
    assert gb.range_for("thriller", "adverbs").books == len(ids)


def test_an_unreadable_baseline_means_fixed_figures(tmp_path):
    gb.baseline_path().write_text("{not json")
    gb._LOADED["key"] = None
    p = _project(tmp_path, ADVERBY)
    assert _ctx(p).threshold("adverbs") == rd._thresholds()["adverbs"]
    assert gb.load() == {}


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── CONLIT for sentence length (24 Nov 2026) ───────────────────────────

def _conlit_csv(path, rows):
    """A CONLIT_META.csv with the columns conlit_loader reads."""
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ID", "Category", "Genre", "token_count",
                                          "total_characters", "avg_sentence_length",
                                          "avg_word_length"])
        w.writeheader()
        for i, (genre, asl) in enumerate(rows):
            w.writerow({"ID": f"b{i}", "Category": "FIC", "Genre": genre, "token_count": 100000,
                        "total_characters": 454000, "avg_sentence_length": asl,
                        "avg_word_length": 3.7})
    return path


CONLIT_ROWS = ([("MY", v) for v in (12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0)]
               + [("HIST", v) for v in (17.0, 18.0, 19.0, 20.0, 21.0, 22.0)]
               + [("SF", v) for v in (14.0, 15.0, 16.0)]          # too few
               + [("YA", 11.0)] * 8)                              # not one of the app's genres


def test_without_conlit_the_build_is_exactly_as_before(tmp_path):
    assert gb.conlit_csv() is None and gb.load_conlit() == []
    books = [("thriller", "One", _book("One"))]
    plain = gb.build(books)
    empty = gb.build(books, conlit=gb.load_conlit())
    for d in (plain, empty):
        d.pop("made_at")
    assert plain == empty
    assert set(plain) == {"format_version", "source", "min_books", "genres"}
    assert plain["source"] == gb.SOURCE
    block = plain["genres"]["thriller"]
    assert set(block) == {"books", "titles", "measures"}
    assert set(block["measures"]["sentence_length"]) == {"p10", "p50", "p90", "books", "chapters"}


def test_conlit_sets_sentence_length_where_it_has_enough_books(tmp_path):
    from src.data.conlit_loader import _DEFAULT_LOCAL_CONLIT_DIR
    _conlit_csv(_DEFAULT_LOCAL_CONLIT_DIR / "CONLIT_META.csv", CONLIT_ROWS)   # the Studio's place
    rows = gb.load_conlit()
    assert len(rows) == len(CONLIT_ROWS)
    data = _store(books=7, genre="mystery")
    gutenberg = dict(data["genres"]["mystery"]["measures"]["sentence_length"])
    gb.add_conlit(data, rows)
    myst = data["genres"]["mystery"]
    sl = myst["measures"]["sentence_length"]
    assert sl["source"] == "conlit" and sl["books"] == 7 and sl["note"] == "contemporary, CONLIT"
    assert sl["p50"] == round(15.0 / gb.CONLIT_RATIO, 2)                 # tokens → app words
    assert sl["tokens"]["p50"] == 15.0
    assert myst["sentence_length_sources"]["gutenberg"] == gutenberg      # kept, for --show
    assert myst["measures"]["adverbs"]["books"] == 7                       # other measures untouched
    lit = data["genres"]["literary"]                                       # no Gutenberg books needed
    assert lit["books"] == 0 and set(lit["measures"]) == {"sentence_length"}
    assert lit["measures"]["sentence_length"]["note"] == "contemporary historical fiction, CONLIT"
    assert "scifi" not in data["genres"]                                   # 3 books: too few
    assert data["conlit"]["genres"] == {"literary": 6, "mystery": 7, "scifi": 3}
    assert data["conlit"]["used"] == {"literary": 6, "mystery": 7}
    assert data["conlit"]["chars_per_token"] == 4.54
    gb.save(data)

    # What the writer reads
    p = _project(tmp_path, CLEAN, genre="mystery")
    pacing = rd.chapter_report(p, p.manuscript.chapters[0]).results["pacing"].message
    lo, hi = gb._fmt("sentence_length", sl["p10"]), gb._fmt("sentence_length", sl["p90"])
    assert f"published mysteries {lo} to {hi} words (contemporary, CONLIT, 7 books)" in pacing
    assert "published mysteries 35 to 50% (12 books)" not in pacing
    assert "(7 books)" in pacing                                            # dialogue: Gutenberg
    r = gb.usable("literary", "sentence_length")
    assert r is not None and r.books == 6
    assert gb.usable("literary", "adverbs") is None
    assert gb.line("literary", "dialogue_share", 30.0) == ""
    assert gb.fingerprint("literary", used_only=True) != ""
    assert gb.change_note("literary", "", gb.fingerprint("literary", used_only=True)) == (
        "Sentence length now compared with published literary novels (contemporary "
        "historical fiction, CONLIT, 6 books) rather than a fixed figure.")
    assert "sentence length: contemporary, CONLIT, 7 books" in gb.change_note(
        "mystery", "", gb.fingerprint("mystery", used_only=True))
    assert gb.change_note("mystery", "older-figures", gb.fingerprint("mystery", used_only=True)) == (
        "Sentence length now compared with published mysteries (contemporary, CONLIT, "
        "7 books); the other measures as before.")
    lit_p = _project(tmp_path, CLEAN, genre="literary")
    lit_r = rd.chapter_report(lit_p, lit_p.manuscript.chapters[0]).results
    assert "(contemporary historical fiction, CONLIT, 6 books)" in lit_r["pacing"].message
    assert lit_r["adverbs"].message == ""                                   # fixed, as before


def test_the_script_uses_conlit_and_shows_where_sentence_length_came_from(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "genre_baseline_script", Path(__file__).resolve().parent.parent / "scripts" / "genre_baseline.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    csv_path = _conlit_csv(tmp_path / "elsewhere" / "CONLIT_META.csv", CONLIT_ROWS)
    assert script.main(["--corpus", str(corpus), "--conlit", str(csv_path)]) == 0
    out = capsys.readouterr().out
    assert f"CONLIT: {len(CONLIT_ROWS)} books from {csv_path}" in out
    assert "sentence length from: CONLIT (contemporary, CONLIT, 7 books)" in out
    assert gb.load()["conlit"]["used"] == {"literary": 6, "mystery": 7}
    data = _store(books=7, genre="mystery")                                 # an older file
    script.show(data)
    out = capsys.readouterr().out
    assert "CONLIT: not used" in out
    assert "sentence length from: Gutenberg books measured by the app" in out
    assert script.main(["--corpus", str(corpus), "--no-conlit", "--no-write"]) == 0
    assert "CONLIT: not found" in capsys.readouterr().out


def test_conlit_saved_summary_stands_in_when_the_file_is_gone(tmp_path):
    """The writer's CONLIT_META.csv had moved; the Training Studio's saved
    summary (mean, median, spread per genre) gives sentence length instead."""
    summary = {"n_books_total": 2754, "by_genre": {
        "mystery": {"n_books": 300, "avg_sentence_length__mean": 14.0,
                    "avg_sentence_length__stdev": 2.0, "avg_sentence_length__median": 13.8,
                    "avg_sentence_length__n": 300},
        "scifi": {"n_books": 3, "avg_sentence_length__mean": 15.0,
                  "avg_sentence_length__stdev": 2.0, "avg_sentence_length__n": 3}}}
    data = {"genres": {}}
    gb.add_conlit_summary(data, summary)
    m = data["genres"]["mystery"]["measures"]["sentence_length"]
    assert m["source"] == "conlit" and m["books"] == 300 and m["from_summary"]
    assert m["p10"] == round((14.0 - 1.2816 * 2.0) / gb.CONLIT_RATIO, 2)
    assert m["p90"] == round((14.0 + 1.2816 * 2.0) / gb.CONLIT_RATIO, 2)
    assert "scifi" not in data["genres"]                    # too few, nothing else known
    assert data["conlit"]["used"] == {"mystery": 300}
    assert gb.add_conlit_summary({"genres": {}}, {"by_genre": {"x": {}}}) == {"genres": {}}
