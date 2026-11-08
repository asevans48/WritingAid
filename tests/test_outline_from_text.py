"""Populate a chapter outline from the chapter text; regenerating
erases the old outline first and replaces it."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPLY = """Here is the outline:

1. [exposition] Walking the Pier
  Mara walks the length of the pier at Greywater and counts the boats.

2. [rising] Tobin's Warning
  Tobin tells her the tide won't wait and that the Gull left before dawn.

3. [climax] Into the Black Sea
  Mara dives off the pier into the sea.
"""


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def yes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)


def _editor(app, content, reply=REPLY, outline=""):
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    ch = Chapter(id="c1", number=1, title="The Pier", content=content)
    ch.planning.outline = outline
    ed = ChapterEditor(ch, project=WriterProject(name="t"))
    prompts = []

    def handler(prompt, model):
        prompts.append(prompt)
        return reply(prompt) if callable(reply) else reply
    ed.planner_widget.set_ai_handler(handler)
    signals = []
    ed.events_cleared.connect(lambda cid: signals.append(("cleared", cid)))
    ed.events_replaced.connect(lambda cid: signals.append(("replaced", cid)))
    return ed, prompts, signals


def _wait(planner, timeout=10):
    from PyQt6.QtCore import QCoreApplication
    end = time.time() + timeout
    while planner._current_callback is not None and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()


def _titles(planner):
    return [w.get_data()["text"] for w in planner._event_widgets]


TEXT = ("Mara walked the length of the pier at Greywater. She counted the boats.\n"
        "\"You're late,\" Tobin said. \"The Gull left before dawn.\"\n"
        "Mara dove off the pier into the black sea without a second thought.\n") * 3


def test_populates_outline_from_chapter_text(app, yes):
    ed, prompts, signals = _editor(app, TEXT)
    p = ed.planner_widget
    p._populate_outline_from_text()
    _wait(p)
    assert _titles(p) == ["Walking the Pier", "Tobin's Warning", "Into the Black Sea"]
    assert len(prompts) == 1 and "dove off the pier" in prompts[0]
    assert signals == [("replaced", "c1")]     # nothing existed, so nothing erased


def test_regenerating_erases_then_replaces(app, yes):
    ed, prompts, signals = _editor(app, TEXT, outline="## [ ] Beat 1: Old Outline Beat")
    p = ed.planner_widget
    p._add_event_item(text="Old Beat One", description="stale")
    p._add_event_item(text="Old Beat Two")
    p._populate_outline_from_text()
    # Erased before the model is even called.
    assert _titles(p) == [] and signals[0] == ("cleared", "c1")
    _wait(p)
    assert _titles(p) == ["Walking the Pier", "Tobin's Warning", "Into the Black Sea"]
    assert signals == [("cleared", "c1"), ("replaced", "c1")]
    # The old outline never reaches the model.
    assert "Old Beat" not in prompts[0] and "Old Outline Beat" not in prompts[0]


def test_cancel_keeps_existing_outline(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    ed, prompts, signals = _editor(app, TEXT)
    p = ed.planner_widget
    p._add_event_item(text="Keep Me")
    p._populate_outline_from_text()
    assert _titles(p) == ["Keep Me"] and prompts == [] and signals == []


def test_failed_generation_restores_previous_outline(app, yes):
    ed, prompts, signals = _editor(app, TEXT, reply="I can't help with that.")
    p = ed.planner_widget
    p._add_event_item(text="Keep Me", description="original")
    p._populate_outline_from_text()
    _wait(p)
    assert _titles(p) == ["Keep Me"]
    assert signals == [("cleared", "c1"), ("replaced", "c1")]


def test_long_chapter_is_read_section_by_section(app, yes):
    para = ("Mara searched the harbor for the missing ship and questioned every sailor "
            "she met along the docks while the fog rolled in. ") * 6
    middle_marker = "THE-MIDDLE-SCENE: Kessa reveals the map."
    paras = [para] * 60
    paras[30] = middle_marker + " " + para
    text = "\n".join(paras)                      # ~7,000+ words

    def reply(prompt):
        return "- Mara searches the docks" if prompt.startswith("List the story beats") else REPLY
    ed, prompts, signals = _editor(app, text, reply=reply)
    p = ed.planner_widget
    p._populate_outline_from_text()
    _wait(p)
    section_prompts = [x for x in prompts if x.startswith("List the story beats")]
    assert len(section_prompts) >= 3
    assert any(middle_marker in x for x in section_prompts)   # middle isn't skipped
    assert prompts[-1].startswith("TASK: Build the outline") and "BEATS FOUND" in prompts[-1]
    assert len(_titles(p)) == 3


def test_uses_editor_selection_when_present(app, yes):
    from PyQt6.QtGui import QTextCursor
    other = "Ilsa rode north through the snow toward the abbey and the old king's tomb. " * 10
    ed, prompts, _ = _editor(app, TEXT + other)
    c = ed.editor.textCursor()
    start = ed.editor.toPlainText().index("Ilsa")
    c.setPosition(start)
    c.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(c)
    ed.planner_widget._populate_outline_from_text()
    _wait(ed.planner_widget)
    assert "Ilsa rode north" in prompts[0] and "Mara walked" not in prompts[0]


def test_ai_generate_also_replaces_and_drops_old_plan(app, yes):
    ed, prompts, signals = _editor(app, TEXT)
    p = ed.planner_widget
    p._add_event_item(text="Old Beat One")
    p._get_context = lambda question="": {"chapter_title": "The Pier",
                                          "current_plan": "OLD PLAN TEXT"}
    p._generate_events()
    assert _titles(p) == []
    _wait(p)
    assert _titles(p) == ["Walking the Pier", "Tobin's Warning", "Into the Black Sea"]
    assert "OLD PLAN TEXT" not in prompts[0] and "Old Beat One" not in prompts[0]


def test_main_window_syncs_outline_panel(app):
    from types import SimpleNamespace as NS
    from src.models.project import Chapter, StoryEvent
    from src.ui.main_window import MainWindow
    ch = Chapter(id="c1", number=1, title="The Pier")
    ch.planning.events = [StoryEvent(id="e1", text="Walking the Pier", description="Mara walks."),
                          StoryEvent(id="e2", text="Into the Black Sea")]
    written = []
    panel = NS(current_chapter_id=lambda: "c1", set_outline_text=written.append)
    fake = NS(current_project=object(), _find_chapter_by_id=lambda cid: ch,
              manuscript_editor=NS(current_chapter_editor=None),
              chat_widget=NS(outline_panel=panel), _auto_save_project=lambda: None)
    fake._events_to_outline_markdown = lambda ev: MainWindow._events_to_outline_markdown(fake, ev)
    MainWindow._handle_chapter_events_replaced(fake, "c1")
    assert "Walking the Pier" in ch.planning.outline and "Into the Black Sea" in ch.planning.outline
    assert written == [ch.planning.outline]
