"""U.3b: the remaining screens fit 1024 × 600, 150 % and the tiled share.

Video Studio needed 1,407 px wide (and so the whole main window 1,415 px)
and World 545 px high: the Studio's toolbar wraps (``FlowLayout``) and its
side panel scrolls; World's sections each scroll. Rows of buttons follow
the writer's rule (26 Nov): shorter words first (``short_label``), then
wrap. Dialogs taller than a small screen scroll with their buttons kept
below (``scroll_dialog``).
"""

import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SMALL = (1024, 600)
AT_150 = (960, 600)            # 1440 × 900 at 150 %: what the harness draws
TILED = 420                    # a screen in its own window, at its narrowest share


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from src.ui.styles import get_modern_style
    before = app.styleSheet()
    app.setStyleSheet(get_modern_style())          # sizes as the app draws them
    yield app
    app.setStyleSheet(before)                      # other test files size without it


@pytest.fixture(autouse=True)
def no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


def _settle(app, rounds=6):
    for _ in range(rounds):
        app.processEvents()


def _row(buttons, width):
    """A FlowLayout row of ``buttons`` in a host ``width`` wide."""
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from src.ui.ui_kit import FlowLayout
    host = QWidget()
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    row = FlowLayout()
    for b in buttons:
        row.addWidget(b)
    outer.addLayout(row)
    outer.addStretch()
    host.resize(width, 300)
    host.show()
    return host, row


def _lines(buttons):
    return len({b.geometry().top() for b in buttons if b.isVisible()})


# ── Shorter words, then wrap ─────────────────────────────────────────────

def _note_buttons():
    from PyQt6.QtWidgets import QPushButton
    from src.ui.ui_kit import short_label
    go, fix, beat = QPushButton("Go to"), QPushButton("💡 Suggest fix"), QPushButton("Mark beat done")
    ask, dismiss = QPushButton("💬 Ask"), QPushButton("Dismiss")
    fix.setToolTip("Open Suggestions on this sentence")
    for b, s in ((fix, "💡 Fix"), (beat, "✓ Beat"), (dismiss, "✕")):
        short_label(b, s)
    return [go, fix, beat, ask, dismiss]


def test_a_row_reads_in_full_when_it_has_room(app):
    buttons = _note_buttons()
    host, row = _row(buttons, 1000)
    _settle(app)
    assert [b.text() for b in buttons] == ["Go to", "💡 Suggest fix", "Mark beat done",
                                           "💬 Ask", "Dismiss"]
    assert buttons[1].toolTip() == "Open Suggestions on this sentence"
    assert _lines(buttons) == 1
    host.close()


def test_a_narrow_row_switches_to_short_words_before_it_wraps(app):
    from src.ui.ui_kit import full_text
    buttons = _note_buttons()
    full = sum(b.sizeHint().width() for b in buttons) + 4 * 6
    host, row = _row(buttons, full - 40)          # a little short of room
    _settle(app)
    assert [b.text() for b in buttons] == ["Go to", "💡 Fix", "✓ Beat", "💬 Ask", "✕"]
    assert _lines(buttons) == 1                    # short words fit: no wrap
    assert [full_text(b) for b in buttons] == ["Go to", "💡 Suggest fix", "Mark beat done",
                                               "💬 Ask", "Dismiss"]
    # The full name heads the tooltip; a button's own tip follows it.
    assert buttons[1].toolTip() == "💡 Suggest fix\nOpen Suggestions on this sentence"
    assert buttons[4].toolTip() == "Dismiss"
    for b in buttons:                              # nothing cut
        assert b.width() >= b.minimumSizeHint().width()
    # With room again it reads as before, its own tip restored.
    host.resize(1000, 300)
    _settle(app)
    assert buttons[1].text() == "💡 Suggest fix" and buttons[4].text() == "Dismiss"
    assert buttons[1].toolTip() == "Open Suggestions on this sentence"
    assert buttons[4].toolTip() == ""
    host.close()


def test_it_wraps_only_when_short_words_still_do_not_fit(app):
    buttons = _note_buttons()
    host, row = _row(buttons, 150)
    _settle(app)
    assert buttons[1].text() == "💡 Fix"           # short, and wrapped
    assert _lines(buttons) > 1
    for a in buttons:
        assert a.geometry().right() <= host.width()
        for b in buttons:
            if a is not b:
                assert not a.geometry().intersects(b.geometry())
    host.close()


def test_a_flow_row_is_a_drop_in_for_a_toolbar_row(app):
    """Stretch, a stretching status, dividers and "Label:" pairs."""
    from PyQt6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton
    from src.ui.ui_kit import ElidedLabel
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    a, b = QPushButton("Save"), QPushButton("Load")
    sort, combo = QLabel("Sort:"), QComboBox()
    combo.addItems(["Name", "Type"])
    status = ElidedLabel("0 scene(s), 0 hop(s) — all chapters, and a long status line")
    host, row = _row([], 10)
    for w in (a, line, b):
        row.addWidget(w)
    row.addSpacing(16)
    row.addStretch()                               # nothing: the row is left-aligned
    row.insertWidget(3, sort)
    row.insertWidget(4, combo)
    row.addWidget(status, stretch=1)
    host.resize(a.sizeHint().width() + b.sizeHint().width() + sort.sizeHint().width() + 60, 300)
    _settle(app)
    # "Sort:" stays on the line of the box it names.
    assert abs(sort.geometry().center().y() - combo.geometry().center().y()) <= 2
    # A divider is never drawn at the start or end of a line.
    assert line.width() == 0 or line.geometry().left() > a.geometry().left()
    # The status takes the rest of its line, elided, never past the edge.
    assert status.geometry().right() <= host.width()
    host.resize(2000, 300)
    _settle(app)
    assert status.geometry().right() >= host.width() - 2   # stretched to the end
    host.close()


def test_an_elided_label_can_show_its_text_and_its_own_tip(app):
    from src.ui.ui_kit import ElidedLabel
    label = ElidedLabel("<b>Backends</b> Video: Placeholder ✓ · Image: Configured Model ✓",
                        text_in_tip=True)
    label.setToolTip("Set in Settings → Image Generation.")
    label.resize(60, 20)
    label.show()
    _settle(app)
    assert label.is_cut()
    assert label.toolTip() == ("Backends Video: Placeholder ✓ · Image: Configured Model ✓"
                               "\n\nSet in Settings → Image Generation.")
    label.resize(label.sizeHint().width() + 10, 20)
    _settle(app)
    assert label.toolTip() == "Set in Settings → Image Generation."
    label.hide()


# ── U.3a's rows, with the narrow-rows rule ──────────────────────────────

def test_the_companions_note_buttons_shorten_in_a_narrow_panel(app):
    from src.ui.companion_panel import CompanionPanel
    from src.ui.ui_kit import full_text
    panel = CompanionPanel()
    panel.resize(1000, 700)
    panel.show()
    panel.act_btn.setVisible(True)                 # as for a note with a beat
    _settle(app)
    assert panel.fix_note_btn.text() == "💡 Suggest fix"
    assert panel.act_btn.text() == "Mark beat done" and panel.dismiss_btn.text() == "Dismiss"
    panel.resize(300, 700)
    _settle(app)
    assert panel.fix_note_btn.text() == "💡 Fix"
    assert panel.act_btn.text() == "✓ Beat" and panel.dismiss_btn.text() == "✕"
    assert panel.go_btn.text() == "Go to" and panel.ask_btn.text() == "💬 Ask"
    assert full_text(panel.dismiss_btn) == "Dismiss"
    assert panel.dismiss_btn.toolTip().startswith("Dismiss")
    panel.close()


def test_the_rating_bar_shortens_then_wraps(app):
    from PyQt6.QtWidgets import QPushButton
    from src.ui.rating_bar import RatingBar
    bar = RatingBar(label="Rate this critique overall:")
    bar.resize(900, 80)
    bar.show()
    _settle(app)
    words = lambda: [b.text() for b in bar.findChildren(QPushButton)]   # noqa: E731
    assert "⭐ Excellent" in words() and bar.save_check.text() == "Save for training"
    bar.resize(330, 80)
    _settle(app)
    assert "⭐ Best" in words() and bar.save_check.text() == "Save"
    assert bar.save_check.toolTip().startswith("Save for training\n")
    bar.close()


def test_add_hierarchy_reads_whole_in_its_wider_column(app):
    """The column's cap went from 250 to 290 px (the writer, 26 Nov), so
    "➕ Add Hierarchy" reads whole beside 🗑️ and 📥 Import."""
    from PyQt6.QtWidgets import QPushButton
    from src.ui.ui_kit import full_text
    from src.ui.worldbuilding.hierarchy_builder import HierarchyBuilderWidget
    w = HierarchyBuilderWidget()
    w.resize(1024, 560)
    w.show()
    _settle(app)
    add = next(b for b in w.findChildren(QPushButton) if full_text(b) == "➕ Add Hierarchy")
    imp = next(b for b in w.findChildren(QPushButton) if b.text() == "📥 Import")
    assert add.text() == "➕ Add Hierarchy"
    assert add.geometry().top() == imp.geometry().top()      # one line: no wrap needed
    assert add.width() >= add.minimumSizeHint().width()
    w.close()


def test_the_studio_board_actions_sit_behind_plus(app):
    """Save and Load stay on the toolbar; Arrange, Clear and Fit are in "+"
    (the writer, 26 Nov). Each entry clicks its old button."""
    from PyQt6.QtWidgets import QToolButton
    from src.ui.video_studio.studio_widget import VideoStudioWidget
    w = VideoStudioWidget()
    w.resize(1024, 560)
    w.show()
    _settle(app)
    assert w._save_board_btn.isVisible() and w._load_board_btn.isVisible()
    plus = next(b for b in w.findChildren(QToolButton) if b.text() == "+")
    assert plus.isVisible()
    names = [a.text() for a in plus.menu().actions()]
    assert names == ["Arrange", "Clear", "Fit"]
    for b in (w._arrange_btn, w._clear_board_btn, w._fit_view_btn):
        assert not b.isVisible()
    hits = []
    w._fit_view_btn.clicked.connect(lambda: hits.append("fit"))
    plus.menu().actions()[2].trigger()
    assert hits == ["fit"]
    w.close()


# ── Video Studio and World ───────────────────────────────────────────────

def test_video_studio_fits_a_small_screen_and_its_tiled_share(app):
    from src.ui.ui_kit import FlowLayout
    from src.ui.video_studio.studio_widget import VideoStudioWidget
    w = VideoStudioWidget()
    rows = w.findChildren(FlowLayout)
    assert len(rows) >= 2, "the two toolbar rows wrap"
    w.resize(1600, 800)
    w.show()
    _settle(app)
    assert w._slide_editor_btn.text() == "🎤 Slide editor"        # full width: as before
    assert w._export_deck_btn.text() == "📑 Export deck"
    need = w.minimumSizeHint()
    assert need.width() <= TILED, need                              # was 1,407
    w.resize(TILED, 600)
    _settle(app)
    assert w.minimumSizeHint().height() <= AT_150[1]
    assert w._slide_editor_btn.text() == "🎤 Slides"                # shorter, then wrapped
    for b in (w._stitch_btn, w._slide_editor_btn, w._export_deck_btn, w._save_board_btn):
        assert b.geometry().right() <= w.width() and b.width() >= b.minimumSizeHint().width()
    # The side panel scrolls instead of drawing its words over each other.
    from PyQt6.QtWidgets import QScrollArea
    assert any(a.widget() is not None and a.widget().findChild(type(w._backend_status))
               is not None for a in w.findChildren(QScrollArea))
    w.close()


def test_world_fits_600_high_and_its_tiled_share(app):
    from PyQt6.QtWidgets import QScrollArea
    from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
    w = ComprehensiveWorldBuildingWidget()
    need = w.minimumSizeHint()
    assert need.height() <= 400 and need.width() <= TILED, need      # was 677 × 545
    for i in range(w.stack.count()):                                 # every section scrolls
        assert isinstance(w.stack.widget(i), QScrollArea)
    assert w.stack.widget(2).widget() is w.history_widget              # the tall one
    w.deleteLater()


def test_the_main_window_fits_1024_by_600_again(tmp_path):
    """Video Studio made the whole main window need 1,415 × 641."""
    h = _harness()
    names = ["video_studio", "world", "main_tabs", "video_studio_tiled",
             "world_tiled", "characters_tiled", "visuals_tiled"]
    report = h.run(names, tmp_path, sizes=[(1024, 600, 1.0)])["1024x600"]
    for name in names:
        info = report["screens"][name]
        assert "error" not in info, info
        assert info["problems"] == [], (name, info["problems"])
        assert info["needs"][0] <= 1024 and info["needs"][1] <= 600, (name, info["needs"])


# ── Windows taller than the screen ──────────────────────────────────────

def test_scroll_dialog_keeps_the_buttons_below_and_opens_within_the_screen(app):
    from PyQt6.QtWidgets import (
        QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
    )
    from src.ui.ui_kit import scroll_dialog
    dlg = QDialog()
    layout = QVBoxLayout(dlg)
    for _ in range(6):
        edit = QTextEdit()
        edit.setMinimumHeight(200)                  # 1,200 px of form
        layout.addWidget(edit)
    row = QHBoxLayout()
    save = QPushButton("Save")
    row.addStretch()
    row.addWidget(save)
    layout.addLayout(row)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    layout.addWidget(box)
    dlg.setMinimumSize(900, 700)
    area = scroll_dialog(dlg, 1000, 800)
    assert isinstance(area, QScrollArea)
    screen = dlg.screen().availableGeometry()
    assert dlg.width() <= screen.width() and dlg.height() <= screen.height()
    assert dlg.minimumSizeHint().height() < 600
    assert not area.widget().isAncestorOf(save) and not area.widget().isAncestorOf(box)
    assert area.widget().findChildren(QTextEdit).__len__() == 6
    dlg.deleteLater()


def test_scroll_dialog_scrolls_a_main_windows_centre(app):
    from PyQt6.QtWidgets import QLabel, QMainWindow, QScrollArea
    from src.ui.ui_kit import scroll_dialog
    win = QMainWindow()
    centre = QLabel("x")
    centre.setMinimumSize(900, 900)
    win.setCentralWidget(centre)
    scroll_dialog(win, 1100, 720)
    assert isinstance(win.centralWidget(), QScrollArea)
    assert win.centralWidget().widget() is centre
    assert win.minimumSizeHint().height() < 600
    win.deleteLater()


def test_the_world_editors_fit_a_small_screen(app):
    from src.ui.worldbuilding.map_builder_widgets import EventEditorDialog
    from src.ui.worldbuilding.military_builder import ArmyEditorDialog
    for cls in (EventEditorDialog, ArmyEditorDialog):
        dlg = cls()
        need = dlg.minimumSizeHint().expandedTo(dlg.minimumSize())
        assert need.height() <= 540 and need.width() <= 960, (cls.__name__, need)  # was 820
        dlg.deleteLater()


def test_the_verdict_puts_its_words_under_it_in_a_narrow_window(app):
    from PyQt6.QtWidgets import QBoxLayout
    from src.ui.scorecard_widget import ScorecardWidget
    card = ScorecardWidget()
    card.figure_label.setText("● Ready, as far as checked")
    card.resize(1400, 600)
    card.show()
    _settle(app)
    row = next(lay for lay in card.findChildren(QBoxLayout)
               if lay.indexOf(card.figure_label) >= 0)
    assert row.direction() == QBoxLayout.Direction.LeftToRight      # as before, beside it
    card.resize(TILED, 600)
    _settle(app)
    assert row.direction() == QBoxLayout.Direction.TopToBottom      # under it, not squeezed
    card.close()


def test_characters_and_visuals_scroll_sideways_when_tiled(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QScrollArea
    from src.models.project import Character
    from src.ui.characters_widget import CharacterWidget
    from src.ui.image_generator_widget import ImageGeneratorWidget
    for w in (CharacterWidget(Character(id="c1", name="Mara Venn", character_type="minor")),
              ImageGeneratorWidget()):
        area = w.findChild(QScrollArea)
        assert area.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        w.deleteLater()


# ── The harness ──────────────────────────────────────────────────────────

def _harness():
    spec = importlib.util.spec_from_file_location("screen_harness",
                                                  ROOT / "scripts" / "screen_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_new_screens_are_in_the_harness():
    h = _harness()
    for key in ("plot", "characters", "world", "visuals", "video_studio", "prose_profile",
                "attributions", "publishing"):
        assert f"{key}_tiled" in h.SCREENS and f"{key}_tiled" in h.SWEEP_SCREENS
    for name in ("world_event_editor", "army_editor", "import_guide", "launcher", "model_hub"):
        assert name in h.SCREENS and name in h.SWEEP_SCREENS


def test_the_harness_reports_a_screen_wider_than_its_share(app):
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
    h = _harness()
    top = QWidget()
    label = QLabel("x")
    label.setMinimumWidth(600)
    QVBoxLayout(top).addWidget(label)
    top.setProperty("harness_share", 430)
    top.show()
    _settle(app)
    assert any("more than its share" in p for p in h._check(top, top, app))
    top.close()


def test_the_dialogs_pass_the_harness_at_the_small_size(tmp_path):
    h = _harness()
    names = ["world_event_editor", "world_place_editor", "star_system_editor", "army_editor",
             "import_guide", "json_import", "launcher", "model_hub", "modal_cost",
             "local_corpus"]
    report = h.run(names, tmp_path, sizes=[(1024, 600, 1.0)])["1024x600"]
    for name in names:
        info = report["screens"][name]
        assert "error" not in info, info
        assert info["problems"] == [], (name, info["problems"])
        assert info["window"][0] <= 1024 and info["window"][1] <= 600, (name, info["window"])
