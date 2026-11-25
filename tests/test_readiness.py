"""1.2b: the readiness engine, its file, and its first two checks."""

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.data import publishing_goal as pg
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("Its a beutiful day and he dont care. The rain fell on the roofs of the town.\n"
        "The night was very dark and terribly cold and frightening and so very lonely.\n"
        "Vethari walked to the harbor, where Vethari waited for the boats.\n") * 6
CLEAN = ("The rain fell on the roofs of the town. She walked to the harbor.\n"
         "Gulls turned over the water and the boats came in one by one.\n") * 10


def _chapter(p_ms, n, text):
    ch = Chapter(id=str(uuid.uuid4()), number=n, title=f"Chapter {n}", folder_root=p_ms.folder_root)
    ch.content = text
    return ch


def _project(tmp_path, texts=(TEXT, CLEAN), novella=()):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i, t in enumerate(texts):
        p.manuscript.chapters.append(_chapter(p.manuscript, i + 1, t))
    if novella:
        sp = p.create_subproject("Novella")
        for i, t in enumerate(novella):
            sp.manuscript.chapters.append(_chapter(sp.manuscript, i + 1, t))
    return p


def _folder_hashes(folder: Path):
    return {str(f.relative_to(folder)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(folder.rglob("*")) if f.is_file()}


# 1. A report for a sample chapter, with both first checks.
def test_report_for_a_sample_chapter(tmp_path):
    p = _project(tmp_path)
    r = rd.chapter_report(p, p.manuscript.chapters[0])
    assert r.scope is None and r.is_opening and r.words == len(TEXT.split())
    sg = r.results["spelling_grammar"]
    words = {i.text.lower() for i in sg.items}
    assert {"beutiful", "its", "dont"} & words
    assert "vethari" not in words                      # a name used often is not a misspelling
    assert sg.status == rd.Status.PROBLEM and sg.count == len(sg.items)
    assert all(i.key.startswith(("spelling:", "grammar:")) for i in sg.items)
    od = r.results["overdescribed"]
    assert od.status == rd.Status.NEEDS_MODEL and od.count > 0     # shown, not in the figure
    clean = rd.chapter_report(p, p.manuscript.chapters[1])
    assert clean.results["spelling_grammar"].status == rd.Status.READY
    assert not clean.is_opening


def test_the_engine_counts_what_the_editor_underlines(tmp_path, qapp):
    from src.ui.enhanced_text_editor import EnhancedTextEditor, ErrorType
    p = _project(tmp_path)
    ed = EnhancedTextEditor()
    ed.set_project_vocabulary(p)
    ed.setPlainText(TEXT)
    ed.overuse_detector.update_cache(TEXT)
    ed.writing_highlighter.update_full_text(TEXT)
    ed.writing_highlighter.rehighlight()
    shown = sorted(e.word for errs in ed.writing_highlighter._errors.values() for e in errs
                   if e.error_type in (ErrorType.SPELLING, ErrorType.GRAMMAR))
    r = rd.chapter_report(p, p.manuscript.chapters[0], text=TEXT)
    assert sorted(i.text for i in r.results["spelling_grammar"].items) == shown


# 2. The cache.
def test_cache_used_when_unchanged_and_refreshed_when_changed(tmp_path, monkeypatch):
    p = _project(tmp_path)
    ch = p.manuscript.chapters[0]
    calls = []
    spec = rd.REGISTRY["spelling_grammar"] if rd.checks_for() else None
    real = spec.fn

    def counting(ctx):
        calls.append(ctx.text)
        return real(ctx)
    monkeypatch.setattr(spec, "fn", counting)
    first = rd.chapter_report(p, ch)
    rd.chapter_report(p, ch)
    assert len(calls) == 1                                       # unchanged: cached
    again = rd.chapter_report(p, ch)
    assert again.from_cache == len(again.results) >= 2
    assert again.results["spelling_grammar"].count == first.results["spelling_grammar"].count

    ch.content = TEXT + "Anothr line.\n"                          # text changed
    rd.chapter_report(p, ch)
    assert len(calls) == 2
    monkeypatch.setattr(spec, "version", 2)                       # the check changed
    rd.chapter_report(p, ch)
    assert len(calls) == 3
    pg.set_route(p, None, "self")                                 # the route changed
    rd.chapter_report(p, ch)
    assert len(calls) == 4
    rd.chapter_report(p, ch, use_cache=False)
    assert len(calls) == 5


def test_live_text_is_checked_not_the_stored_text(tmp_path):
    p = _project(tmp_path)
    r = rd.chapter_report(p, p.manuscript.chapters[0], text=CLEAN)
    assert r.results["spelling_grammar"].status == rd.Status.READY


# 3. A check that raises.
def test_a_failing_check_is_could_not_check(tmp_path, monkeypatch):
    p = _project(tmp_path)
    spec = rd.checks_for() and rd.REGISTRY["overdescribed"]

    def boom(ctx):
        raise RuntimeError("scan broke")
    monkeypatch.setattr(spec, "fn", boom)
    r = rd.chapter_report(p, p.manuscript.chapters[0])
    od = r.results["overdescribed"]
    assert od.status == rd.Status.COULD_NOT_CHECK and "scan broke" in od.error
    assert r.results["spelling_grammar"].status == rd.Status.PROBLEM      # the rest carries on
    book = rd.book_report(p)
    assert book.left_out["overdescribed"] == "could not check"
    stored = rs.stored_chapter(p, None, p.manuscript.chapters[0].id)
    assert "overdescribed" not in stored.get("results", {})              # a failure isn't cached


# 4. Per manuscript.
def test_book_report_per_manuscript(tmp_path):
    p = _project(tmp_path, texts=(CLEAN,), novella=(TEXT, CLEAN))
    reports = rd.project_report(p)
    assert [r.scope for r in reports] == [None, p.subprojects[0].id]
    main, nov = reports
    assert len(main.chapters) == 1 and len(nov.chapters) == 2
    assert nov.kind == "novella" and nov.name == "Novella"
    assert nov.chapters[0].is_opening and nov.chapters[0].scope == nov.scope
    sg = lambda r, i: r.chapters[i].results["spelling_grammar"].status
    assert sg(main, 0) == rd.Status.READY
    assert sg(nov, 0) == rd.Status.PROBLEM and sg(nov, 1) == rd.Status.READY
    assert nov.readiness < main.readiness                          # the novella has the slips
    assert main.readiness == pytest.approx(rd.readiness_figure(main)) and main.cells > 1
    assert "spelling_grammar" in main.counted
    assert main.left_out["overdescribed"] == "needs a model"
    assert main.left_out["chapter_length"] == "information only"
    data = json.loads(rs.readiness_path(p).read_text())
    assert set(data["manuscripts"]) == {"main", nov.scope}
    assert len(data["manuscripts"][nov.scope]["chapters"]) == 2


def test_figure_weights(tmp_path):
    book = rd.BookReport(scope=None, name="B", kind="novel")
    for status in (rd.Status.READY, rd.Status.NEEDS_WORK, rd.Status.PROBLEM, rd.Status.NEEDS_MODEL):
        ch = rd.ChapterReport(None, str(uuid.uuid4()), 1, "C", 100, "h")
        ch.results["spelling_grammar"] = rd.CheckResult("spelling_grammar", "copyedit", status, 0)
        book.chapters.append(ch)
    assert rd.readiness_figure(book) == pytest.approx(0.5)        # (1 + ½ + 0) / 3


def test_grid_and_helpers(tmp_path):
    p = _project(tmp_path)
    book = rd.book_report(p)
    g = rd.grid(book)
    stages = [st for st, _ in g.stages()]
    assert stages == sorted(stages, key=rd.STAGES.index)                     # stage order
    names = [s.name for s in g.columns]
    assert names.index("overdescribed") < names.index("spelling_grammar")
    assert len(g.rows) == 4 and g.rows[-1][0].chapter_id == rd.BOOK_ROW   # + whole manuscript
    assert g.rows[0][0].chapter_id == rd.OPENING_ROW                       # + opening pages
    assert g.rows[1][1][names.index("spelling_grammar")].status == rd.Status.PROBLEM
    assert g.rows[-1][1][names.index("manuscript_length")].status == rd.Status.INFO
    items = rd.items_for(book.chapters[0], "spelling_grammar")
    assert items and items[0].paragraph >= 0
    fixes = rd.fix_candidates_for(book, "copyedit")
    assert fixes and {"label", "excerpt", "sentence", "weight", "paragraph", "kind", "fixed",
                      "chapter_id"} <= set(fixes[0])


def test_stop_and_progress(tmp_path):
    p = _project(tmp_path, texts=(TEXT, CLEAN, CLEAN))
    seen = []
    book = rd.book_report(p, progress=lambda d, t, title: seen.append((d, t)),
                          stop=lambda: len(seen) >= 2)
    assert not book.complete and len(book.chapters) == 2
    assert len(rs.load(p)["manuscripts"]["main"]["chapters"]) == 2       # saved as it went


# 5. Rule 11: older projects and files.
def test_a_project_saved_before_1_2(tmp_path):
    from src.ui.enhanced_text_editor import EnhancedTextEditor  # noqa: F401 (as in the app)
    p = _project(tmp_path)
    path = tmp_path / "book.writerproj"
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))
    before = {k: v for k, v in _folder_hashes(tmp_path).items() if "readiness" not in k}
    book = rd.book_report(again)
    assert len(book.chapters) == 2 and book.saved
    after = {k: v for k, v in _folder_hashes(tmp_path).items() if "readiness" not in k}
    assert after == before                       # 6. nothing but readiness.json is written
    again.save_project(str(path))
    third = WriterProject.load_project(str(path))
    assert [c.content for c in third.manuscript.chapters] == [TEXT, CLEAN]


def test_a_1_1_file_is_read_kept_and_copied_aside(tmp_path):
    p = _project(tmp_path)
    old = {"format_version": 1, "manuscripts": {"main": {"route": "self"}}, "extra": {"x": 1}}
    rs.readiness_path(p).write_text(json.dumps(old))
    rd.book_report(p)
    data = json.loads(rs.readiness_path(p).read_text())
    assert data["manuscripts"]["main"]["route"] == "self" and data["extra"] == {"x": 1}
    assert data["manuscripts"]["main"]["chapters"]
    path = rs.readiness_path(p)
    aside = path.with_name(path.stem + ".before-1.2.json")
    assert json.loads(aside.read_text()) == old
    assert pg.route_for(p) == "self"


def test_a_newer_file_is_never_written(tmp_path):
    p = _project(tmp_path)
    newer = {"format_version": 99, "manuscripts": {"main": {"route": "self", "future": True}}}
    path = rs.readiness_path(p)
    path.write_text(json.dumps(newer))
    stamp = path.read_bytes()
    book = rd.book_report(p)
    assert len(book.chapters) == 2 and not book.saved
    assert pg.route_for(p) == "self"                                   # still read
    assert not pg.set_route(p, None, "agent")
    assert path.read_bytes() == stamp


def test_an_unreadable_file_is_set_aside_not_overwritten(tmp_path):
    p = _project(tmp_path)
    path = rs.readiness_path(p)
    path.write_text("{not json")
    rd.book_report(p)
    asides = [f for f in tmp_path.iterdir() if "readiness" in f.name and f != path]
    assert any(f.read_text() == "{not json" for f in asides)


# 7. Two projects stay apart.
def test_two_projects_stay_apart(tmp_path):
    a = _project(tmp_path / "a" if (tmp_path / "a").mkdir() is None else None)
    b = _project(tmp_path / "b" if (tmp_path / "b").mkdir() is None else None)
    rs.update(a, lambda d: d.setdefault("dismissed", {}).__setitem__(
        "spelling:beutiful", {"check": "spelling_grammar", "at": "2026-11-23"}))
    rs.store_chapter(a, None, a.manuscript.chapters[0].id, {"stage": "line"})
    ra = rd.chapter_report(a, a.manuscript.chapters[0])
    rb = rd.chapter_report(b, b.manuscript.chapters[0])
    assert ra.stage == "line" and rb.stage == ""
    assert any(i.dismissed for i in ra.results["spelling_grammar"].items)
    assert not any(i.dismissed for i in rb.results["spelling_grammar"].items)
    assert ra.results["spelling_grammar"].count < rb.results["spelling_grammar"].count


def test_runs_on_a_worker_thread(tmp_path):
    import threading
    p = _project(tmp_path)
    scanner = rd.Scanner(p)                        # built first (the GUI thread in the app)
    out = []
    t = threading.Thread(target=lambda: out.append(rd.book_report(p, scanner=scanner)))
    t.start()
    t.join(120)
    assert out and len(out[0].chapters) == 2


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
