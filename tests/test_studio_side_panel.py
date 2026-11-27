"""The Video Studio's side panel: dropped by default, on right-click
(the writer's request, 26 Nov 2026; ``src/ui/video_studio/studio_side_panel``).

Settings go to a throwaway file (``tests/conftest.py``)."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _settle(app, rounds=6):
    for _ in range(rounds):
        app.processEvents()


def _studio(app):
    from src.ui.video_studio.studio_widget import VideoStudioWidget
    w = VideoStudioWidget()
    w.resize(1024, 560)
    w.show()
    _settle(app)
    return w


def _menu_texts(w):
    from PyQt6.QtWidgets import QMenu
    menu = QMenu()
    w._canvas._add_extra_actions(menu)
    return menu, [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_panel_starts_dropped_and_the_canvas_has_the_width(app):
    w = _studio(app)
    assert not w._toggle_side_btn.isChecked()
    assert w._splitter.sizes()[1] == 0
    assert w._toggle_side_btn.isVisible()            # ▶◀ still brings it back
    w.close()


def test_toggling_it_open_is_remembered(app):
    w = _studio(app)
    w._toggle_side_btn.click()                       # open
    _settle(app)
    assert w._splitter.sizes()[1] > 0
    w.close()
    w2 = _studio(app)
    assert w2._toggle_side_btn.isChecked() and w2._splitter.sizes()[1] > 0
    w2._toggle_side_btn.click()                      # and closed again
    w2.close()
    w3 = _studio(app)
    assert not w3._toggle_side_btn.isChecked() and w3._splitter.sizes()[1] == 0
    w3.close()


def test_right_click_offers_backend_status_and_hints(app):
    w = _studio(app)
    menu, texts = _menu_texts(w)
    assert texts == ["Backend status…", "Hints…"]
    menu.actions()[-1].trigger()                     # Hints…
    _settle(app)
    from PyQt6.QtWidgets import QDialog, QLabel
    dlg = next(d for d in w.findChildren(QDialog) if d.windowTitle() == "Hints")
    assert any("Drag cards" in l.text() for l in dlg.findChildren(QLabel))
    dlg.close()
    menu.actions()[-2].trigger()                     # Backend status…
    _settle(app)
    dlg = next(d for d in w.findChildren(QDialog) if d.windowTitle() == "Backend status")
    assert any(l.text().strip() for l in dlg.findChildren(QLabel))
    dlg.close()
    w.close()


def test_a_canvas_without_the_studio_entries_is_as_before(app):
    from PyQt6.QtWidgets import QMenu
    from src.ui.video_studio.scene_canvas import SceneCanvasView
    view = SceneCanvasView()
    menu = QMenu()
    view._add_extra_actions(menu)
    assert menu.actions() == []
