"""D.13b: Write's ribbon, polished (legible tab names, an icon and words on
every control, hover text and screen-reader names, the two renames) and
7.4's two export answers (Publisher Ready marks scene breaks; the export
tick is remembered per project).

Projects are built in ``tmp_path``; HOME and the window-state settings are
the test's own (conftest); no model runs; LanguageTool is never started.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractButton, QComboBox, QSpinBox, QWidget

from src.data import readiness_state as rs
from src.data import scene_marks as sm
from src.models.project import Chapter, Manuscript, WriterProject
from src.ui import write_ribbon as wr

TEXT = ("Rain fell on the harbor all night. Mara watched the boats.\n\n"
        "Next morning the ferry came in late, and Voss was on it.\n\n"
        "That evening Tobin burned the letter in the stove.")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


@pytest.fixture(autouse=True)
def fresh_marks():
    sm._UNDO.clear()
    sm._cache.clear()
    yield
    sm._UNDO.clear()
    sm._cache.clear()


def _project(tmp_path, name="Saga"):
    p = WriterProject(name=name, manuscript=Manuscript(title="Main Manuscript"))
    p.manuscript.chapters = [Chapter(id=f"m{i}", number=i, title=t, content=TEXT)
                             for i, t in enumerate(["The Storm", "The Pier"], 1)]
    p._normalize_manuscript_roots()
    p.save_project(str(tmp_path / f"{name}.writerproj"))
    return p


def _editor(app, p, size=(1440, 900)):
    from src.ui.manuscript_editor import ManuscriptEditor
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    w.resize(*size)
    w.show()
    for _ in range(3):
        app.processEvents()
    return w


def _done(app, w):
    from src.ui import background, companion_panel
    for t in list(companion_panel._RUNNING):
        try:
            t.wait(10000)
        except RuntimeError:
            pass
    background.wait_all(10000)
    w.close()
    w.deleteLater()
    app.processEvents()


def _controls(ribbon):
    """Every control the writer can reach on every tab, and before the tab names."""
    out = []
    pages = [ribbon.stack.widget(n) for n in range(ribbon.stack.count())]
    lead = [ribbon.lead.itemAt(n).widget() for n in range(ribbon.lead.count())]
    for page in pages:
        for w in page.findChildren(QWidget):
            if isinstance(w, (QAbstractButton, QComboBox, QSpinBox)) and not w.isHidden() \
                    and w.parentWidget() is page:
                out.append(w)
    return out + [w for w in lead if w is not None and not w.isHidden()]


# ── Every control: hover text, a name, an icon and words, keyboard reach ──

def test_every_ribbon_control_has_hover_text_a_name_and_words(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    controls = _controls(ce.write_ribbon)
    assert len(controls) >= 15
    for c in controls:
        name, tip = c.accessibleName(), c.toolTip()
        assert name, c
        assert tip.startswith(name), (name, tip)      # leads with its full name
        assert len(tip) > len(name) + 10, tip         # then what it does
        assert c.accessibleDescription(), c
        assert c.focusPolicy() != Qt.FocusPolicy.NoFocus, name   # Tab reaches it
        if isinstance(c, QAbstractButton) and c.text() not in ("B", "I", "U"):
            text = c.text()
            # an icon (a symbol first) and its words: never icon-only
            assert any(ch.isalpha() for ch in text), text
            assert not text[0].isalpha() or not c.icon().isNull(), text
    # a shortcut is named in the hover text, as this computer writes it
    for key, btn_text in (("bold", "B"), ("improve", wr.IMPROVE)):
        btn = next(c for c in controls if isinstance(c, QAbstractButton) and c.text() == btn_text)
        keys = wr.keys_of(btn.defaultAction())
        assert keys and btn.toolTip().startswith(f"{wr.TIPS[key][0]} ({keys}): ")
    _done(app, w)


def test_the_tabs_are_legible_and_reachable(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    bar = ce_bar = w.current_chapter_editor.write_ribbon.bar
    sheet = bar.styleSheet()
    assert "font-size: 13px" in sheet                 # the app's body size, not 12
    assert ":selected" in sheet and ":hover" in sheet and ":focus" in sheet
    assert bar.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert bar.accessibleName()
    for n in range(bar.count()):
        assert bar.tabToolTip(n).startswith(bar.tabText(n) + ":")
    # still compact: a few pixels more than D.13's strip, not a second row
    assert ce_bar.sizeHint().height() <= 32
    _done(app, w)


def test_checks_hover_text_keeps_its_name_as_the_checks_change(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    assert ce.checks_btn.toolTip().startswith("Checks: ")
    for act in ce._check_actions.values():
        act.setChecked(False)
    ce._update_checks_button()
    assert ce.checks_btn.toolTip().startswith("Checks: ") and "All are off" in ce.checks_btn.toolTip()
    ce._check_actions["spell"].setChecked(True)
    ce._update_checks_button()
    assert ce.checks_btn.toolTip().startswith("Checks: ") and "On: " in ce.checks_btn.toolTip()
    _done(app, w)


def test_the_sidebar_arrow_has_its_word_and_says_what_a_click_does(app, tmp_path):
    p = _project(tmp_path)
    w = _editor(app, p)
    btn = w.sidebar_toggle_btn
    assert btn.text() == wr.SIDEBAR and not btn.icon().isNull()
    assert btn.toolTip().startswith(f"{wr.SIDEBAR}: Hide")
    btn.click()
    app.processEvents()
    assert w.left_panel.isHidden() and btn.toolTip().startswith(f"{wr.SIDEBAR}: Show")
    btn.click()
    assert btn.toolTip().startswith(f"{wr.SIDEBAR}: Hide")
    _done(app, w)


# ── The renames: same menus, same entries ─────────────────────────────

def test_chapter_and_manuscript_menus_are_renamed_with_every_entry(app, tmp_path):
    from PyQt6.QtWidgets import QLabel
    p = _project(tmp_path)
    w = _editor(app, p)
    ce = w.current_chapter_editor
    wr.show_tab(w, wr.DRAFT, remember=False)
    app.processEvents()
    assert ce.draft_btn.text() == wr.CHAPTER_MENU == "📄 Chapter ▾"
    assert [a.text() for a in ce.draft_btn.menu().actions() if a.text()] == [
        "Save draft", "View drafts…", "Import from Word…", "Export to Word…",
        "Clean up formatting"]
    assert w.drafts_menu_btn.text() == wr.MANUSCRIPT_MENU == "📚 Manuscript ▾"
    assert [a.text() for a in w.drafts_menu_btn.menu().actions()] == [
        "＋ Save the manuscript as a new draft", "🗑 Drop this draft…",
        "↗ Open a draft in its own window…"]
    page = ce.write_ribbon.stack.currentWidget()
    labels = [l.text() for l in page.findChildren(QLabel) if l.isVisibleTo(page)]
    assert wr.THIS_CHAPTER not in labels                # the name says it now
    # the old buttons the menu clicks are still there, hidden (D.7)
    assert w.new_draft_btn.isHidden() and w.drop_draft_btn.isHidden()
    _done(app, w)


def test_harness_still_groups_the_renamed_manuscript_menu():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "scripts" / "screen_harness.py"
    spec = importlib.util.spec_from_file_location("screen_harness_d13b", path)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    assert h.grouped(wr.MANUSCRIPT_MENU) and h.grouped("Drafts ▾")


# ── 7.4 (b): Publisher Ready always marks scene breaks ─────────────────

def _docx_texts(path):
    from docx import Document
    return Document(str(path)).paragraphs


def test_publisher_ready_marks_the_scenes_the_writer_marked(tmp_path):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from src.export.manuscript_exporter import ManuscriptExporter
    p = _project(tmp_path)
    ms = p.manuscript
    before = tmp_path / "before.docx"
    assert ManuscriptExporter(ms).export_publisher_ready(str(before), project=p)
    plain = [x.text for x in _docx_texts(before)]
    assert "#" not in plain                             # no markers: as before
    legacy = tmp_path / "legacy.docx"                   # and the old call, unchanged
    assert ManuscriptExporter(ms).export_publisher_ready(str(legacy))
    assert [x.text for x in _docx_texts(legacy)] == plain

    paras = [line for _n, _o, line in sm.paragraphs(TEXT)]
    sm.add(p, "m1", TEXT, [next(i for i, t in enumerate(paras) if t.startswith("Next"))])
    marked = tmp_path / "marked.docx"
    assert ManuscriptExporter(ms).export_publisher_ready(str(marked), project=p)
    out = _docx_texts(marked)
    texts = [x.text for x in out]
    at = texts.index("#")
    assert texts[at + 1].startswith("Next morning") and texts[at - 1].startswith("Rain fell")
    assert out[at].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert texts.count("#") == 1                        # chapter 2 has no marker
    assert [t for t in texts if t != "#"] == plain
    assert ms.chapters[0].content == TEXT               # the chapter itself: untouched


def test_main_window_publisher_ready_passes_the_project(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog, QWidget
    from src.export import manuscript_exporter as mx
    from src.ui import notify
    from src.ui.main_window import MainWindow
    p = _project(tmp_path)
    seen = {}

    def fake(self, path, kind="Novel", project=None):
        seen["project"] = project
        return True
    monkeypatch.setattr(mx.ManuscriptExporter, "export_publisher_ready", fake)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "o.docx"), "")))
    monkeypatch.setattr(notify, "done", lambda *a, **k: None)
    win = QWidget()
    win.current_project = p
    win._collect_project_data = lambda: None
    MainWindow._export_manuscript(win, "publisher")
    assert seen["project"] is p


# ── 7.4 (c): the export tick, remembered per project ───────────────────

def test_the_export_tick_is_remembered_per_project(app, tmp_path):
    from src.ui.export_document_dialog import ExportDocumentDialog
    a = _project(tmp_path, "A")
    b = _project(tmp_path, "B")
    path_a = rs.readiness_path(a)
    # a project without markers: no tick, nothing written by the dialog
    dlg = ExportDocumentDialog(True, scene_marks=sm.any_marks(a), project=a)
    dlg.accept()
    assert not path_a.exists()
    paras = [line for _n, _o, line in sm.paragraphs(TEXT)]
    for p in (a, b):
        sm.add(p, "m1", TEXT, [next(i for i, t in enumerate(paras) if t.startswith("Next"))])
    saved = path_a.read_bytes()
    # no stored choice: unticked, as before; accepting unticked writes nothing
    dlg = ExportDocumentDialog(True, scene_marks=True, project=a)
    assert not dlg._marks.isChecked()
    dlg.accept()
    assert path_a.read_bytes() == saved
    # ticked and exported: the next export of A starts ticked, B does not
    dlg = ExportDocumentDialog(True, scene_marks=True, project=a)
    dlg._marks.setChecked(True)
    dlg.accept()
    assert sm.export_tick(a) and not sm.export_tick(b)
    assert sm.stored(a, "m1")                            # the markers are kept
    assert ExportDocumentDialog(True, scene_marks=True, project=a)._marks.isChecked()
    assert not ExportDocumentDialog(True, scene_marks=True, project=b)._marks.isChecked()
    # cancelled: nothing remembered
    dlg = ExportDocumentDialog(True, scene_marks=True, project=a)
    dlg._marks.setChecked(False)
    dlg.reject()
    assert sm.export_tick(a)
    # unticked and exported: back to the default, the key gone
    dlg = ExportDocumentDialog(True, scene_marks=True, project=a)
    dlg._marks.setChecked(False)
    dlg.accept()
    assert not sm.export_tick(a)
    import json
    assert sm.EXPORT_KEY not in json.loads(path_a.read_text())
    # the old call (no project) behaves exactly as 7.4 left it
    dlg = ExportDocumentDialog(True, scene_marks=True)
    assert not dlg._marks.isChecked()
    dlg.accept()


def test_an_unreadable_or_older_readiness_file_means_unticked(tmp_path):
    p = _project(tmp_path)
    path = rs.readiness_path(p)
    path.write_text("{ not json")
    assert sm.export_tick(p) is False
    path.write_text('{"format_version": 1, "scene_marks_export": "yes"}')
    assert sm.export_tick(p) is False                    # only a stored true ticks it
    assert sm.export_tick(None) is False and sm.remember_export_tick(None, True) is False


# ── A project saved before D.13b opens, saves and reopens unchanged ────

def test_a_project_saved_before_opens_and_saves_unchanged(app, tmp_path):
    p = _project(tmp_path)
    path = tmp_path / "Saga.writerproj"
    w = _editor(app, p)
    w.current_chapter_editor.write_ribbon.show_tab(wr.DRAFT)
    _done(app, w)
    again = WriterProject.load_project(str(path))
    assert [c.content for c in again.manuscript.chapters] == [TEXT, TEXT]
    again.save_project(str(path))
    assert [c.content for c in WriterProject.load_project(str(path)).manuscript.chapters] \
        == [TEXT, TEXT]
    assert not rs.readiness_path(p).exists()             # the ribbon writes no project state
