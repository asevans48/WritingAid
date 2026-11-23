"""U.1: the shared interface parts."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QWIDGETSIZE_MAX = (1 << 24) - 1


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def kit(app):
    import src.ui.ui_kit as kit
    return kit


def _avail():
    from PyQt6.QtGui import QGuiApplication
    return QGuiApplication.primaryScreen().availableGeometry()


# ── Fitting the screen ──────────────────────────────────────────────────

def test_fit_to_screen_never_exceeds_the_screen(kit):
    from PyQt6.QtWidgets import QWidget
    w = QWidget()
    size = kit.fit_to_screen(w, 10_000, 10_000)
    assert size.width() <= _avail().width() - 40 and size.height() <= _avail().height() - 60
    assert (w.width(), w.height()) == (size.width(), size.height())


def test_fit_to_screen_keeps_a_minimum(kit):
    from PyQt6.QtWidgets import QWidget
    w = QWidget()
    assert (kit.fit_to_screen(w, 100, 100).width(), w.height()) == (480, 360)


def test_size_class(kit):
    from PyQt6.QtWidgets import QWidget
    w = QWidget()
    for width, expected in ((1024, "narrow"), (1440, "normal"), (2560, "wide")):
        w.resize(width, 600)
        assert kit.size_class(w) == expected


def test_window_comes_back_where_it_was(kit):
    from PyQt6.QtWidgets import QWidget
    a = QWidget()
    assert kit.remember_geometry(a, "test/win") is False      # nothing saved yet
    a.resize(500, 400)
    a.move(30, 40)
    a.show()
    a.close()                                                  # saves on close
    b = QWidget()
    assert kit.remember_geometry(b, "test/win") is True
    assert (b.width(), b.height(), b.x(), b.y()) == (500, 400, 30, 40)


def test_window_whose_monitor_is_gone_opens_on_a_visible_screen(kit):
    from PyQt6.QtWidgets import QWidget
    s = kit._settings()
    s.setValue("test/gone/rect", [9000, 9000, 600, 400])       # far off any screen
    s.setValue("test/gone/screen", "Monitor that was unplugged")
    s.sync()
    w = QWidget()
    assert kit.remember_geometry(w, "test/gone") is False
    assert _avail().intersects(w.geometry())


def test_damaged_saved_position_is_ignored(kit):
    from PyQt6.QtWidgets import QWidget
    s = kit._settings()
    s.setValue("test/bad/rect", ["not", "numbers"])
    s.sync()
    w = QWidget()
    assert kit.remember_geometry(w, "test/bad") is False      # no error, just fitted


# ── Scrolling and parts ────────────────────────────────────────────────

def test_scrollable(kit):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QScrollArea, QWidget
    content = QWidget()
    area = kit.scrollable(content)
    assert isinstance(area, QScrollArea) and area.widget() is content
    assert area.widgetResizable()
    assert area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


def test_collapsible_section_still_importable_from_the_companion(kit):
    from src.ui.companion_panel import CollapsibleSection
    assert CollapsibleSection is kit.CollapsibleSection


def test_collapsible_section_opens_closes_and_reports(kit):
    sec = kit.CollapsibleSection("Notes", "notes")
    seen = []
    sec.toggled.connect(lambda key, collapsed: seen.append((key, collapsed)))
    sec.header.click()
    assert not sec.is_open() and seen == [("notes", True)]
    sec.set_open(True)                      # quiet: no signal
    assert sec.is_open() and seen == [("notes", True)]
    sec.set_count(3)
    assert "(3)" in sec.header.text()


def test_parts_build_and_hold_no_fixed_heights(kit):
    parts = [kit.card(), kit.status_chip("Line", "line"), kit.section_header("THIS CHAPTER"),
             kit.primary_button("Run"), kit.empty_state("Nothing yet — run a check."),
             kit.CollapsibleSection("A", "a")]
    for part in parts:
        assert part.maximumHeight() == QWIDGETSIZE_MAX, type(part).__name__
        assert part.minimumHeight() == 0, type(part).__name__


def test_primary_button_is_the_default_action(kit):
    btn = kit.primary_button("Run")
    assert btn.isDefault() and "}}" not in btn.styleSheet()


# ── Colours ─────────────────────────────────────────────────────────────

def test_every_style_check_has_its_own_colour(kit):
    from src.utils.style_checks import KINDS
    for kind, (_label, colour, _sentence) in KINDS.items():
        assert kit.PROBLEM_COLOURS[kind] == colour


def test_editor_flag_colours_come_from_the_kit(kit):
    from src.ui.enhanced_text_editor import ErrorCard
    assert ErrorCard.COLORS is kit.FLAG_COLOURS


def test_stage_colours_come_from_the_palette(kit):
    from src.ui.styles import COLORS
    assert set(kit.STAGE_COLOURS) == {"structure", "scene", "line", "copyedit", "proof"}
    assert set(kit.STAGE_COLOURS.values()) <= set(COLORS.values())


def test_colour_for_falls_back_quietly(kit):
    assert kit.colour_for("spelling") == kit.FLAG_COLOURS["spelling"]
    assert kit.colour_for("proof") == kit.STAGE_COLOURS["proof"]
    assert kit.colour_for("success") == kit.PALETTE["success"]
    assert kit.colour_for("no such kind").startswith("#")
