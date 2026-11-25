"""D.8 One look: colours and button styles come from ui_kit, nothing moves."""

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

# Files already cleaned: none may gain a hard-coded colour again. Add each
# file here as a later session cleans it.
CLEANED = [
    "src/ui/manuscript_editor.py", "src/ui/companion_panel.py", "src/ui/next_fixes.py",
    "src/ui/retired_screens.py", "src/ui/chapter_planner_widget.py", "src/ui/feedback_widget.py",
    "src/ui/grader_widget.py", "src/ui/scorecard_widget.py", "src/ui/readiness_issues.py",
    "src/ui/settings_dialog.py", "src/ui/outline_section.py", "src/ui/plan_section.py",
    "src/ui/outline_chart.py",
]
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|['\":\s]#[0-9a-fA-F]{3}\b")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("name", CLEANED)
def test_a_cleaned_file_has_no_hard_coded_colour(name):
    found = [f"{i}: {line.strip()}" for i, line in
             enumerate((ROOT / name).read_text().splitlines(), 1) if HEX.search(line)]
    assert not found, f"use PALETTE from src/ui/ui_kit.py in {name}:\n" + "\n".join(found)


def test_a_plain_button_keeps_the_size_it_had(app):
    from PyQt6.QtWidgets import QPushButton
    from src.ui.ui_kit import plain, plain_qss
    old = QPushButton("Split View")
    old.setStyleSheet("QPushButton { border: none; padding: 3px 8px; font-size: 11px; }")
    new = plain(QPushButton("Split View"))
    assert new.sizeHint() == old.sizeHint()
    assert "border: 1px solid" in plain_qss() and "padding: 2px 7px" in plain_qss()


def test_text_style_reads_the_palette():
    from src.ui.ui_kit import PALETTE, text_style
    assert text_style("ink_soft", 11, bold=True) == \
        f"color: {PALETTE['ink_soft']}; font-size: 11px; font-weight: bold;"
    assert text_style(italic=True, extra="padding: 2px;").endswith("font-style: italic; padding: 2px;")


@pytest.fixture
def old_project():
    from test_project_compat import _v1_project_dir
    return _v1_project_dir()


def test_a_project_from_before_the_piece_shows_and_saves_unchanged(app, old_project):
    """Display only: open an old project on the restyled Write screen, save,
    reopen; every chapter file is byte-for-byte what it was."""
    import shutil
    from src.models.project import WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    d, path = old_project
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    p = WriterProject.load_project(str(path))
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    w.current_chapter_editor.toggle_planner_btn.click()     # the side panel, plain buttons and all
    app.processEvents()
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    assert len(again.manuscript.chapters) == len(p.manuscript.chapters)
    w.deleteLater()
    shutil.rmtree(d)


def test_the_companion_has_one_coloured_button(app):
    """The side panel draws every button plain; the Companion's main action
    (Find the next fixes) keeps its own primary style."""
    from src.ui.companion_panel import CompanionPanel
    from src.ui.ui_kit import PRIMARY_BUTTON
    panel = CompanionPanel()
    coloured = [b.text() for b in panel.findChildren(type(panel.queue.find_btn))
                if b.styleSheet() == PRIMARY_BUTTON]
    assert "🎯 Find the next fixes" in coloured
    assert all(t in ("🎯 Find the next fixes", "✓ Accept") for t in coloured), coloured
