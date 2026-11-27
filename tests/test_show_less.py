"""D.7: show less at once. Nothing removed: every action still one click away."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.models.project import Chapter, WriterProject


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project(tmp_path):
    p = WriterProject(name="Saga")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One",
                                     content="Teh rain fell on teh harbor all night.")]
    p.project_path = str(tmp_path / "Saga.writerproj")
    return p


# ── Part 1: the Write screen ──────────────────────────────────────────

@pytest.fixture
def me(app, project):
    from src.ui.manuscript_editor import ManuscriptEditor
    w = ManuscriptEditor()
    w.set_project(project)
    w.load_manuscript(project.manuscript)
    w.open_chapter("c1")
    w.resize(1440, 900)
    w.show()
    app.processEvents()
    return w


def _visible_buttons(top):
    from PyQt6.QtWidgets import QPushButton, QToolButton
    return [b for b in top.findChildren((QPushButton, QToolButton))
            if b.isVisibleTo(top) and (b.text().strip() or not b.icon().isNull())]


def test_the_write_screen_shows_18_buttons_not_24(me):
    # D.7 made 24 into 19; D.10 folded Novellas ▾ into the manuscript tree,
    # and D.11 retired it with the old row (its entries are the tree's).
    texts = [b.text() for b in _visible_buttons(me)]
    assert len(texts) == 18, texts
    for gone in ("＋ Novella", "⇢ Move main chapters…", "🗑 Drop novella", "↗", "📋",
                 "Novellas ▾"):
        assert gone not in texts
    assert "Drafts ▾" in texts and "⇅ Split View" in texts


@pytest.mark.parametrize("menu_attr,label,button_attr", [
    ("drafts_menu_btn", "＋ Save the manuscript as a new draft", "new_draft_btn"),
    ("drafts_menu_btn", "🗑 Drop this draft…", "drop_draft_btn"),
    ("drafts_menu_btn", "↗ Open a draft in its own window…", "popout_draft_btn"),
])
def test_each_moved_button_is_a_menu_item_that_does_the_same(me, menu_attr, label, button_attr):
    button = getattr(me, button_attr)
    clicked = []
    button.clicked.disconnect()                  # don't open real dialogs
    button.clicked.connect(lambda *_: clicked.append(True))
    menu = getattr(me, menu_attr).menu()
    act = next(a for a in menu.actions() if a.text() == label)
    menu.aboutToShow.emit()
    act.trigger()
    assert clicked
    button.setEnabled(False)                     # a disabled button: a disabled item
    menu.aboutToShow.emit()
    assert not act.isEnabled()


def test_one_annotation_button_keeps_both_actions_and_the_shortcut(app, project):
    from src.ui.manuscript_editor import ChapterEditor
    ce = ChapterEditor(project.manuscript.chapters[0], project=project)
    btn = next(t.annotations_btn for t in [w for w in ce.findChildren(object)
                                           if hasattr(w, "annotations_btn")])
    add = btn.defaultAction()
    assert add.shortcut().toString() == "Ctrl+Shift+N"
    labels = [a.text() for a in btn.menu().actions()]
    assert labels[0].startswith("📝 Add annotation here") and labels[1] == "📋 View all annotations"
    assert all(not a.shortcut().toString() for a in btn.menu().actions())   # no clash
    seen = []
    ce._view_annotations_list = lambda: seen.append("view")
    view_action = next(a for a in ce.findChildren(type(add)) if a.text() == "📋")
    view_action.triggered.disconnect()
    view_action.triggered.connect(lambda: seen.append("view"))
    btn.menu().actions()[1].trigger()
    assert seen == ["view"]


# ── Part 2: the hover card ────────────────────────────────────────────

def test_the_card_keeps_fixes_and_ignore_in_view_and_folds_the_rest(app, project):
    from PyQt6.QtWidgets import QCheckBox, QPushButton
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.resize(800, 300)
    ed.show()
    ed.setPlainText(project.manuscript.chapters[0].content)
    ed.set_project_vocabulary(project)
    ed.do_initial_check()
    at = ed.toPlainText().find("teh")
    rect = ed.cursorRect(ed._cursor_at(at + 1))
    assert ed._show_error_tooltip(ed.viewport().mapToGlobal(rect.center()), rect.center())
    card = ed.error_card
    links = {b.text(): b for b in card.findChildren(QPushButton) if b.objectName() == "act"}
    shown = {t for t, b in links.items() if b.isVisibleTo(card)}
    assert {"Ignore", "Add to dictionary", "More ▾"} <= shown
    assert "💬 Ask" not in shown and "See all 2…" not in shown
    assert any(b.isVisibleTo(card) for b in card.findChildren(QCheckBox))   # Fix all box
    assert any(b.objectName() == "fix" and b.isVisibleTo(card)
               for b in card.findChildren(QPushButton))
    links["More ▾"].click()
    app.processEvents()
    assert links["💬 Ask"].isVisibleTo(card) and links["See all 2…"].isVisibleTo(card)
    assert card.isVisible()                                  # no pop-up, the card stays


# ── Part 3: Companion sections by stage ───────────────────────────────

def _closed(project, stage):
    from src.ai import chapter_stages as cst
    from src.ui.companion_stage_sections import closed
    cst.set_stage(project, None, ["c1"], stage)
    keys = ["left_off", "notes", "fixes", "overdescribed", "reader", "memory", "style_sheet"]
    return closed(project, project.manuscript.chapters[0], keys)


def test_copyedit_opens_the_style_sheet_and_closes_the_rest(project):
    shut = _closed(project, "copyedit")
    assert "style_sheet" not in shut and "left_off" not in shut and "fixes" not in shut
    assert {"reader", "memory", "notes", "overdescribed"} <= shut


def test_structure_opens_the_reader_and_memory(project):
    shut = _closed(project, "structure")
    assert not {"reader", "memory", "notes", "fixes"} & shut and "style_sheet" in shut


def test_no_stage_keeps_today_s_defaults(project):
    from src.data import companion_state as cs
    assert _closed(project, "") == set(cs.DEFAULT_COLLAPSED)


def test_a_section_set_by_hand_stays_as_the_writer_left_it(project):
    from src.data import companion_state as cs
    cs.set_section_collapsed(project, "reader", True)       # closed by hand
    assert "reader" in _closed(project, "structure")        # the stage would open it
    cs.set_section_collapsed(project, "style_sheet", False)  # opened by hand
    assert "style_sheet" not in _closed(project, "structure")


def test_states_saved_before_this_piece_never_move(project):
    from src.data import companion_state as cs
    data = cs.load(project)
    data["ui"] = {"collapsed": ["notes"]}                    # an older file
    cs.save(project, data)
    assert _closed(project, "copyedit") == {"notes"}         # exactly as it was


def test_the_panel_applies_it_when_a_chapter_opens(app, project):
    from src.ai import chapter_stages as cst
    from src.ui.companion_panel import CompanionPanel
    cst.set_stage(project, None, ["c1"], "copyedit")
    panel = CompanionPanel()
    panel.set_project(project)
    panel.set_chapter(project.manuscript.chapters[0], "Teh rain.")
    assert panel.sections["style_sheet"].is_open() and not panel.sections["reader"].is_open()
    panel.sections["reader"].header.click()                  # by hand: opened
    panel.set_chapter(project.manuscript.chapters[0], "Teh rain.")
    assert panel.sections["reader"].is_open()
