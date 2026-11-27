"""7.4: scene markers, kept beside the text (``src/data/scene_marks``,
``src/ui/scene_marks_ui``).

The writer's rule: scenes are marked, never in the text. Every test here
checks a part of that: the chapter's text and its saved files stay byte
for byte as they were. Every project is built in ``tmp_path``; no model
is run (the model's reading is a stored, made-up one).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import plan_match, reverse_outline as ro
from src.data import readiness_state as rs
from src.data import scene_marks as sm
from src.models.project import Chapter, Manuscript, WriterProject

ROOT = Path(__file__).resolve().parent.parent

TEXT = ("Rain fell on the harbor all night. Mara watched the boats.\n\n"
        "She counted the lanterns on the hill, one by one.\n\n"
        "Next morning the ferry came in late, and Voss was on it.\n\n"
        "He did not wave. She did not wave back.\n\n"
        "That evening Tobin burned the letter in the stove.\n\n"
        "The ash rose and was gone.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


@pytest.fixture(autouse=True)
def fresh_undo():
    sm._UNDO.clear()
    sm._cache.clear()
    yield
    sm._UNDO.clear()
    plan_match.set_marks_source(None)


def _wait_tasks(app):
    """Let the Companion's background work finish, so no task outlives its
    editor (as test_intentional does)."""
    from src.ui import background, companion_panel
    for _ in range(20):
        for t in list(companion_panel._RUNNING):
            t.wait(10000)
        background.wait_all(10000)
        app.processEvents()
        if not companion_panel._RUNNING:
            return


def _close(app, ed):
    _wait_tasks(app)
    ed.close()
    _wait_tasks(app)


def _project(tmp_path, text=TEXT):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = text
    p.manuscript.chapters.append(ch)
    return p


def _para(text, starts):
    return next(i for i, (_n, _o, line) in enumerate(sm.paragraphs(text))
                if line.startswith(starts))


# ── Anchoring ────────────────────────────────────────────────────────

def test_a_marker_splits_the_scenes_and_follows_its_paragraph_through_edits(tmp_path):
    p = _project(tmp_path)
    assert len(ro.split_scenes(TEXT)) == 1                    # no break lines: one scene
    assert sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning"), _para(TEXT, "That evening")]) == 2
    at = sm.offsets(p, "c1", TEXT)
    scenes = ro.outline(TEXT, [], at)
    assert [s.opening.split()[0] for s in scenes] == ["Rain", "Next", "That"]
    # text added above: the marker follows its paragraph, not its old place
    added = "A gull cried.\n\nAnother gull answered.\n\n" + TEXT
    assert [added[o:o + 12] for o in sm.offsets(p, "c1", added)] == ["Next morning", "That evening"]
    # text cut above
    cut = TEXT.replace("She counted the lanterns on the hill, one by one.\n\n", "")
    assert [cut[o:o + 12] for o in sm.offsets(p, "c1", cut)] == ["Next morning", "That evening"]
    # the opening itself edited a little: still found, nearest its place
    edited = TEXT.replace("Next morning the ferry", "Next morning, the ferry")
    assert edited[sm.offsets(p, "c1", edited)[0]:].startswith("Next morning, the ferry")
    # a marker already at a break line, or at the very start, changes nothing
    with_break = TEXT.replace("Next morning", "***\n\nNext morning")
    assert len(ro.split_scenes(with_break, sm.offsets(p, "c1", with_break))) == 3
    assert ro.split_scenes(TEXT, [0]) == ro.split_scenes(TEXT)


def test_two_paragraphs_that_open_alike_keep_the_nearest(tmp_path):
    text = "He waited.\n\nIt was late.\n\nHe waited.\n\nIt was later."
    p = _project(tmp_path, text)
    sm.add(p, "c1", text, [2])
    assert sm.offsets(p, "c1", text) == [text.index("He waited.", 5)]
    assert sm.add(p, "c1", text, [2]) == 0                   # already marked


def test_a_lost_paragraph_is_left_out_noted_and_kept_until_forgotten(app, tmp_path):
    p = _project(tmp_path)
    sm.add(p, "c1", TEXT, [_para(TEXT, "That evening")])
    gone = TEXT.replace("That evening Tobin burned the letter in the stove.\n\n", "")
    r = sm.for_text(p, "c1", gone)
    assert r.found == [] and len(r.lost) == 1 and sm.offsets(p, "c1", gone) == []
    assert len(ro.split_scenes(gone, sm.offsets(p, "c1", gone))) == 1
    sm.refresh(p, "c1", gone)                                 # edits never drop it
    assert len(sm.stored(p, "c1")) == 1
    assert len(sm.offsets(p, "c1", TEXT)) == 1               # the paragraph back (Undo, a paste)
    view = _view(p, gone)
    page = view.toPlainText()
    assert "A scene marker was left out: its paragraph (“That evening Tobin burned the letter" in page
    _click(view, "marks", ("forget",))
    assert sm.stored(p, "c1") == []


def test_refresh_brings_the_anchor_up_to_date_and_is_not_an_undo_step(tmp_path):
    p = _project(tmp_path)
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning")])
    sm._UNDO.clear()
    moved = "New first paragraph.\n\n" + TEXT.replace("Next morning the", "Next morning, the")
    assert sm.refresh(p, "c1", moved)
    (m,) = sm.stored(p, "c1")
    assert m["p"] == 3 and m["w"].startswith("Next morning, the")
    assert sm.last_change(p) is None and not sm.refresh(p, "c1", moved)


# ── Storage: beside the text, and an older file ─────────────────────

def test_stored_only_beside_the_project_and_an_old_file_reads_as_none(tmp_path):
    p = _project(tmp_path)
    path = rs.readiness_path(p)
    old = {"format_version": 1, "manuscripts": {"main": {"route": "agent", "chapters": {
        "c1": {"stage": "line", "results": {}}}}}, "digest": {"main": {}}, "later": [1]}
    path.write_text(json.dumps(old))
    before = path.read_bytes()
    # reading, outlining and drawing the chart never write
    assert sm.stored(p, "c1") == [] and sm.offsets(p, "c1", TEXT) == [] and not sm.any_marks(p)
    ro.outline(TEXT, [], sm.offsets(p, "c1", TEXT))
    assert path.read_bytes() == before
    # a marker: its own key; everything else kept
    sm.add(p, "c1", TEXT, [2])
    data = json.loads(path.read_text())
    for k in ("manuscripts", "digest", "later"):
        assert data[k] == old[k]
    assert data["scene_marks"] == {"main": {"c1": {"v": 1, "marks": [
        {"p": 2, "w": "Next morning the ferry came in late, and"}]}}}
    # the last one removed: the key goes again
    sm.remove(p, "c1", TEXT, 2)
    assert "scene_marks" not in json.loads(path.read_text())
    # unreadable: no markers, no crash
    from src.data import safe_store
    safe_store._notifier, keep = None, safe_store._notifier
    try:
        path.write_text("{not json")
        sm._cache.clear()
        assert sm.offsets(p, "c1", TEXT) == []
    finally:
        safe_store._notifier = keep


def test_a_project_without_markers_is_unchanged_byte_for_byte(app, tmp_path):
    p = _project(tmp_path)
    view = _view(p, TEXT)                                     # outline drawn
    plan_match.set_marks_source(lambda cid, text: sm.offsets(p, cid, text))
    plan_match.book_pacing([("c1", TEXT)])                    # chart drawn
    sm.with_breaks(p, p.manuscript.chapters)                  # export copies made
    assert "No scene breaks found" in view.toPlainText()
    assert not rs.readiness_path(p).exists()


# ── Text and saved files: byte for byte ─────────────────────────────

def _chapter_files(d: Path):
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and f.suffix == ".md"}


def test_the_text_and_its_saved_files_never_change(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    from src.ui import write_menu
    from src.ui.manuscript_editor import ChapterEditor
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main"))
    ch = Chapter(id="c1", number=1, title="One", content=TEXT)
    p.manuscript.chapters = [ch]
    p._normalize_manuscript_roots()
    p.save_project(str(path))
    ch.add_revision(notes="second", content=TEXT, project_dir=tmp_path)
    p.save_project(str(path))
    p.save_project(str(path))
    p.save_project(str(path))                                  # backup_*.md settled
    files = _chapter_files(tmp_path)
    assert any("revision_" in k for k in files) and any("backup_" in k for k in files)

    ce = ChapterEditor(ch, project=p)
    ce.resize(900, 500)
    ce.show()
    app.processEvents()
    doc = ce.editor.document()
    modified, undo, revision = doc.isModified(), doc.isUndoAvailable(), doc.revision()
    # mark a scene from the right-click
    block = doc.findBlockByNumber(sm.paragraphs(TEXT)[2][0])
    c = ce.editor.textCursor()
    c.setPosition(block.position() + 3)
    ce.editor.setTextCursor(c)
    shown = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.setdefault("menu", self))
    write_menu.show(ce, ce.editor.cursorRect().center())
    _find(shown["menu"], "Scene break here").trigger()
    assert len(sm.stored(p, "c1")) == 1
    ce.scene_mark_layer.refresh_anchors()
    app.processEvents()
    # the document: same text, not modified, no undo step, nothing added
    assert ce.editor.toPlainText() == TEXT and ch.content == TEXT
    assert (doc.isModified(), doc.isUndoAvailable(), doc.revision()) == (modified, undo, revision)
    assert "#" not in ce.editor.toPlainText() and doc.blockCount() == TEXT.count("\n") + 1
    # copying all copies the text alone; the word count is the text's
    ce.editor.selectAll()
    ce.editor.copy()
    from PyQt6.QtWidgets import QApplication
    assert QApplication.clipboard().text().replace(" ", "\n") == TEXT
    assert str(len(TEXT.split())) in ce.word_count_label.text().replace(",", "")
    # saving the chapter and the project leaves every chapter file as it was
    p.save_project(str(path))
    after = _chapter_files(tmp_path)
    kept = lambda fs: {k: v for k, v in fs.items() if "backup_" not in k}
    assert kept(after) == kept(files)                         # every draft, byte for byte
    for name, data in after.items():                          # a saved copy is the same text
        if "backup_" in name:
            assert data.decode().strip() == TEXT.strip(), name
    _close(app, ce)


# ── Moves (D.10), the id clash, and Undo ────────────────────────────

@pytest.fixture
def saga(tmp_path):
    path = tmp_path / "Saga.writerproj"
    p = WriterProject(name="Saga", manuscript=Manuscript(title="Main"))
    p.manuscript.chapters = [Chapter(id="m1", number=1, title="Storm", content=TEXT),
                             Chapter(id="m2", number=2, title="Pier", content="One.\n\nTwo.")]
    fall = p.create_subproject("The Fall")
    fall.manuscript.chapters = [Chapter(id="f1", number=1, title="Fall", content="Fall text.")]
    p._normalize_manuscript_roots()
    p.save_project(str(path))
    return tmp_path, path, p, fall.id


def test_markers_move_with_the_chapter_and_come_back_with_undo(saga):
    from src.data import chapter_move as cm
    _d, path, p, fall = saga
    sm.add(p, "m1", TEXT, [_para(TEXT, "Next morning")])
    before = rs.readiness_path(p).read_bytes()
    r = cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    sm._cache.clear()
    data = json.loads(rs.readiness_path(p).read_text())
    assert "m1" in data["scene_marks"][fall] and not data["scene_marks"].get("main")
    ch = p.find_chapter("m1") if hasattr(p, "find_chapter") else p.find_chapter_with_scope("m1")[1]
    assert sm.offsets(p, "m1", TEXT, sm.scope_of(p, "m1", ch)) == [TEXT.index("Next morning")]
    assert sm.offsets(p, "m1", TEXT) == [TEXT.index("Next morning")]   # found by id too
    cm.undo(p, r, project_file=str(path))
    assert rs.readiness_path(p).read_bytes() == before
    sm._cache.clear()
    assert sm.offsets(p, "m1", TEXT, None) == [TEXT.index("Next morning")]


def test_an_id_clash_carries_the_markers_to_the_new_id_and_undo_brings_them_back(saga):
    from src.data import chapter_move as cm
    _d, path, p, fall = saga
    p.get_manuscript_for(fall).chapters.append(
        Chapter(id="m1", number=2, title="Other", content="Not the same chapter."))
    p._normalize_manuscript_roots()
    p.save_project(str(path))
    sm.add(p, "m1", TEXT, [_para(TEXT, "That evening")], scope=None)
    before = rs.readiness_path(p).read_bytes()
    r = cm.move_chapters(p, [(None, "m1")], fall, project_file=str(path))
    (moved,) = r.renamed
    new_id = moved.chapter_id
    assert new_id != "m1"
    sm._cache.clear()
    data = json.loads(rs.readiness_path(p).read_text())
    assert list(data["scene_marks"][fall]) == [new_id]
    assert sm.offsets(p, new_id, TEXT, fall) == [TEXT.index("That evening")]
    assert sm.stored(p, "m1", fall) == []                     # not the other chapter's
    cm.undo(p, r, project_file=str(path))
    assert rs.readiness_path(p).read_bytes() == before
    sm._cache.clear()
    assert sm.offsets(p, "m1", TEXT, None) == [TEXT.index("That evening")]


# ── The outline, the chart and the tension ──────────────────────────

def _view(project, text):
    from src.ui.readiness_issues import ChapterIssues
    view = ChapterIssues()
    view.resize(700, 900)
    view.outline_names = lambda: []
    view.outline_project = lambda: project
    view.outline_open = True
    ch = NS(chapter_id="c1", number=1, title="One", words=80, text_hash="",
            is_opening=False, results={}, stage="", scope=None)
    view.show_chapter(ch, None, text, {})
    return view


def _click(view, kind, item=None):
    from PyQt6.QtCore import QUrl
    i = next(i for i, (k, it) in enumerate(view._links)
             if k == kind and (item is None or it == item))
    view._on_link(QUrl(f"issue:{i}"))


def _store_digest(project, text, starts):
    from src.ai import chapter_digest
    from src.ai.readiness import text_hash
    scenes = [{"quote": text[text.index(s):text.index(s) + len(s)], "start": text.index(s),
               "end": text.index(s) + len(s), "pov": "Mara", "what": f"scene at {s}",
               "purpose": "moves on"} for s in starts]
    entry = {"scenes": scenes, "slips": [], "setups": [], "payoffs": [], "changes": [],
             "reader": None, "text_hash": text_hash(text), "v": chapter_digest.VERSION}
    rs.update(project, lambda d: d.setdefault(chapter_digest.KEY, {}).setdefault(
        "main", {}).__setitem__("c1", entry))


def test_the_outline_uses_the_models_scenes_after_showing_them_and_undo(app, tmp_path):
    p = _project(tmp_path)
    _store_digest(p, TEXT, ["Rain fell", "Next morning", "That evening"])
    view = _view(p, TEXT)
    page = view.toPlainText()
    assert "Scene outline (1 scene)" in page and "Use the model's scenes" in page
    assert "marks 2 more scenes beside the text, shown first" in page
    _click(view, "marks", ("model",))                          # shown first
    page = view.toPlainText()
    assert "The model's reading starts a scene at these paragraphs" in page
    assert "“Next morning the ferry came in late, and…”" in page and sm.stored(p, "c1") == []
    _click(view, "marks", ("confirm",))
    page = view.toPlainText()
    assert "Scene outline (3 scenes)" in page and page.count("· marked ✕") == 2
    assert "Use the model's scenes" not in page               # nothing left to mark
    # each model scene sits under its own scene now
    assert page.index("scene at Next morning") > page.index("“Next morning")
    assert "2 scenes marked from the model's reading · Undo" in page
    # ✕ on one marker line, then Undo
    first = next(it for k, it in view._links if k == "marks" and it[0] == "remove")
    _click(view, "marks", first)
    assert "Scene outline (2 scenes)" in view.toPlainText()
    assert "Scene marker removed · Undo" in view.toPlainText()
    _click(view, "marks", ("undo",))
    assert "Scene outline (3 scenes)" in view.toPlainText()
    # Ctrl+Z in the outline undoes too (the model's two markers)
    from src.ui import scene_marks_ui
    scene_marks_ui.install_outline(NS(issues=view, project=p, report=None))
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)   # Cmd+Z on a Mac
    app.processEvents()
    assert sm.stored(p, "c1") == [] and "Scene outline (1 scene)" in view.toPlainText()


def test_the_chart_and_plan_matching_see_the_markers(app, tmp_path):
    p = _project(tmp_path)
    plan_match.set_marks_source(lambda cid, text: sm.offsets(p, cid, text))
    assert len(plan_match.book_pacing([("c1", TEXT)])) == 1
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning")])
    points = plan_match.book_pacing([("c1", TEXT)])
    assert [pt.number for pt in points] == [1, 2]
    assert sum(pt.words for pt in points) == len(TEXT.split())
    # the Critique's chart through the outline: "Scenes across this chapter (2)"
    view = _view(p, TEXT)
    assert "Scenes across this chapter (2):" in view.toPlainText()


def test_tension_is_rated_for_the_marked_scenes_and_a_new_marker_asks_again(tmp_path):
    from src.ai import scene_tension as st

    class FakeLLM:
        model = "fake"
        calls = 0

        def generate_text(self, prompt, system, **kw):
            FakeLLM.calls += 1
            self.prompt = prompt
            return "TENSION | 1 | 2 | quiet\nTENSION | 2 | 4 | the ferry\nTENSION | 3 | 3 | ash"
    p = _project(tmp_path)
    llm = FakeLLM()
    ch = NS(id="c1", title="One")
    st.ensure(llm, p, None, ch, TEXT)                         # one scene
    assert st.stored(p, "c1", TEXT)["scenes"] == 1
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning"), _para(TEXT, "That evening")])
    assert st.stored(p, "c1", TEXT) is None                   # made for another split
    got = st.ensure(llm, p, None, ch, TEXT)
    assert "[SCENE 3]" in llm.prompt and got["values"] == [2, 4, 3] and FakeLLM.calls == 2
    assert st.stored(p, "c1", TEXT)["values"] == [2, 4, 3]
    st.ensure(llm, p, None, ch, TEXT)
    assert FakeLLM.calls == 2                                 # stored for this split


# ── Write: the right-click and the margin line ──────────────────────

def _find(menu, label):
    for a in menu.actions():
        if a.text() == label:
            return a
        if a.menu() is not None:
            f = _find(a.menu(), label)
            if f is not None:
                return f
    return None


@pytest.fixture
def ce(app, tmp_path):
    from src.ui.manuscript_editor import ChapterEditor
    p = _project(tmp_path)
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(900, 600)
    ed.show()
    app.processEvents()
    yield ed
    _close(app, ed)


def _menu_at(ce, monkeypatch, starts, select=False):
    from PyQt6.QtWidgets import QMenu
    from src.ui import write_menu
    text = ce.editor.toPlainText()
    c = ce.editor.textCursor()
    c.setPosition(text.index(starts) + 2)
    if select:
        c.setPosition(text.index(starts) + 9, c.MoveMode.KeepAnchor)
    ce.editor.setTextCursor(c)
    shown = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.setdefault("menu", self))
    write_menu.show(ce, ce.editor.cursorRect().center())
    return shown["menu"]


def test_the_right_click_marks_and_unmarks_with_undo_and_no_count_rises(ce, monkeypatch):
    spec = importlib.util.spec_from_file_location("screen_harness",
                                                  ROOT / "scripts" / "screen_harness.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    base = json.loads((ROOT / "docs" / "publishing" / "screens_baseline.json").read_text())
    p = ce.project
    menu = _menu_at(ce, monkeypatch, "Next morning")
    note = _find(menu, sm_ui().NOTE_MENU)
    assert note is not None and _find(menu, "More").menu().actions()[0].menu() is not None
    labels = [a.text() for a in note.menu().actions() if a.text()]
    assert labels == ["📝 Add Annotation", "Scene break here"]
    assert h._menu_items(menu) <= base["right_click"]["text_no_selection"]
    sel = _menu_at(ce, monkeypatch, "Next morning", select=True)
    assert h._menu_items(sel) <= base["right_click"]["text_selection"]
    # mark, then the same paragraph offers Remove
    _find(menu, "Scene break here").trigger()
    assert sm.offsets(p, "c1", TEXT) == [TEXT.index("Next morning")]
    menu = _menu_at(ce, monkeypatch, "Next morning")
    assert _find(menu, "Scene break here") is None
    _find(menu, "Remove scene break").trigger()
    assert sm.stored(p, "c1") == []
    # Undo (the status line's) puts it back
    from src.ui import scene_marks_ui
    assert scene_marks_ui.undo_write(ce) and len(sm.stored(p, "c1")) == 1
    # the first paragraph already starts a scene
    first = _find(_menu_at(ce, monkeypatch, "Rain fell"), "Scene break here")
    assert first is not None and not first.isEnabled()
    # Add Annotation still calls what it called
    called = []
    monkeypatch.setattr(ce, "_add_annotation", lambda n: called.append(n))
    _find(_menu_at(ce, monkeypatch, "Next morning"), "📝 Add Annotation").trigger()
    assert called


def sm_ui():
    from src.ui import scene_marks_ui
    return scene_marks_ui


def test_the_margin_line_is_drawn_beside_the_text_with_its_scene_on_hover(ce, app):
    from PyQt6.QtCore import Qt
    p = ce.project
    layer = ce.scene_mark_layer
    assert layer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert layer.parent() is ce.editor.viewport()
    assert layer.marks() == []
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning"), _para(TEXT, "That evening")])
    layer._key = None
    lines = layer.marks()
    assert lines == [(4, 2), (8, 3)]                          # (block, "Scene N")
    y = layer.line_y(4)
    block_top = ce.editor.document().documentLayout().blockBoundingRect(
        ce.editor.document().findBlockByNumber(4)).top() - ce.editor.verticalScrollBar().value()
    assert y < block_top                                      # in the gap above the paragraph
    assert layer.scene_at(y) == 2 and layer.scene_at(y + 40) is None
    img = layer.grab()                                        # it draws
    assert not img.isNull()
    # typing above moves the line with its paragraph
    c = ce.editor.textCursor()
    c.setPosition(0)
    ce.editor.setTextCursor(c)
    ce.editor.insertPlainText("A gull cried.\n\n")
    assert [n for n, _s in layer.marks()] == [6, 10]


# ── Export ──────────────────────────────────────────────────────────

def test_export_leaves_the_text_as_written_unless_ticked(app, tmp_path):
    from docx import Document
    from src.export.manuscript_exporter import ManuscriptExporter
    from src.ui.export_document_dialog import ExportDocumentDialog
    p = _project(tmp_path)
    ms = p.manuscript
    chapters = list(ms.chapters)
    plain_txt, plain_docx = tmp_path / "a.txt", tmp_path / "a.docx"
    ManuscriptExporter(ms).export_document(str(plain_txt), "txt", chapters=chapters)
    ManuscriptExporter(ms).export_document(str(plain_docx), "docx", chapters=chapters)
    # the dialog: no tick without markers
    dlg = ExportDocumentDialog(True, scene_marks=sm.any_marks(p))
    assert not dlg._marks.isVisibleTo(dlg) and not dlg.mark_scenes()
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning")])
    dlg = ExportDocumentDialog(True, scene_marks=sm.any_marks(p))
    dlg.show()
    assert dlg._marks.isVisible() and not dlg._marks.isChecked() and not dlg.mark_scenes()
    # unticked: byte for byte the export before any marker
    again = tmp_path / "b.txt"
    ManuscriptExporter(ms).export_document(str(again), "txt", chapters=chapters)
    assert again.read_bytes() == plain_txt.read_bytes()
    # ticked: a centred "#" at the marker, in the copy only
    dlg._marks.setChecked(True)
    assert dlg.mark_scenes()
    copies = sm.with_breaks(p, chapters)
    assert chapters[0].content == TEXT and copies[0] is not chapters[0]
    ticked_txt, ticked_docx = tmp_path / "c.txt", tmp_path / "c.docx"
    ManuscriptExporter(ms).export_document(str(ticked_txt), "txt", chapters=copies,
                                           centre_breaks=True)
    ManuscriptExporter(ms).export_document(str(ticked_docx), "docx", chapters=copies,
                                           centre_breaks=True)
    out = ticked_txt.read_text()
    assert "one by one.\n\n#\n\nNext morning" in out
    assert out.replace("#\n\n", "") == plain_txt.read_text()
    paras = Document(str(ticked_docx)).paragraphs
    hash_para = next(x for x in paras if x.text == "#")
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    assert hash_para.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert [x.text for x in paras if x.text != "#"] == \
        [x.text for x in Document(str(plain_docx)).paragraphs]
    assert ms.chapters[0].content == TEXT                     # the chapter itself: untouched
    # ODT and RTF centre it too
    for fmt in ("odt", "rtf"):
        f = tmp_path / f"c.{fmt}"
        assert ManuscriptExporter(ms).export_document(str(f), fmt, chapters=copies,
                                                      centre_breaks=True)
    import zipfile
    content = zipfile.ZipFile(tmp_path / "c.odt").read("content.xml").decode()
    assert '<text:p text:style-name="SceneBreak">#</text:p>' in content
    assert r"\qc #\par" in (tmp_path / "c.rtf").read_text()


def test_single_newline_prose_gets_its_break_on_its_own_line(tmp_path):
    text = "First line.\nSecond line.\nThird line."
    p = _project(tmp_path, text)
    sm.add(p, "c1", text, [2])
    (copy,) = sm.with_breaks(p, p.manuscript.chapters)
    assert copy.content == "First line.\nSecond line.\n#\nThird line."


@pytest.mark.parametrize("tick", [False, True])
def test_file_export_chapter_or_book_uses_the_tick(app, tmp_path, monkeypatch, tick):
    """The main window's File → Export Chapter / Book, on a stand-in window."""
    from PyQt6.QtWidgets import QFileDialog
    from src.ui import export_document_dialog as edd, notify
    from src.ui.main_window import MainWindow
    p = _project(tmp_path)
    sm.add(p, "c1", TEXT, [_para(TEXT, "Next morning")])
    out = tmp_path / "out.txt"
    seen = {}

    def fake_exec(dlg):
        seen["visible"] = dlg._has_marks
        dlg._format.setCurrentIndex(next(i for i in range(dlg._format.count())
                                         if dlg._format.itemData(i)[0] == "txt"))
        dlg._marks.setChecked(tick)
        return True
    monkeypatch.setattr(edd.ExportDocumentDialog, "exec", fake_exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(notify, "done", lambda *a, **k: None)
    from PyQt6.QtWidgets import QWidget
    win = QWidget()
    win.current_project = p
    win._collect_project_data = lambda: None
    win.manuscript_editor = NS(get_current_chapter=lambda: p.manuscript.chapters[0])
    MainWindow._export_document(win)
    assert seen["visible"] and out.exists()
    assert ("\n#\n" in out.read_text()) is tick
    assert p.manuscript.chapters[0].content == TEXT
