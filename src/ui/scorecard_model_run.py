"""Check the book with the model (piece 2.3): the estimate and the choice.

The scan runs by itself whenever the Critique tab opens. Judging with a
model is the writer's choice, because on a local or home-server model it can
take a long time: "Check the book with the model…" (a link in the
scorecard's note, no new button) shows an estimate first. While it runs,
Check readiness becomes Stop, the grid fills as each chapter finishes, and
each chapter's result is saved as it finishes, so stopping or closing the
app loses nothing and the next run carries on from where it stopped.

An option in the same dialog keeps judging changed chapters in the
background while the writer works (off by default).
"""

from __future__ import annotations

from typing import Tuple

BACKGROUND_KEY = "critique/judge_in_background"
# The story read (which also records the chapter's facts for the style
# sheet), the chapter's outline, proofreading, and about one request per
# stage with findings.
REQUESTS_PER_CHAPTER = 7
REQUESTS_PER_CHAPTER_LOCAL = 13   # a local model proofreads in smaller pieces
SECONDS_LOCAL = (15, 45)          # per request, a rough range
SECONDS_CLOUD = (3, 8)


def ai_available() -> bool:
    try:
        from src.config.ai_config import get_ai_config
        return not get_ai_config().is_ai_disabled()
    except Exception:
        return False


def _minutes(seconds: float) -> str:
    if seconds < 90:
        return "about a minute"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"about {minutes} minutes"
    return f"about {seconds / 3600:.1f} hours"


def estimate(todo: int, total: int) -> str:
    """One plain paragraph: what will be judged and roughly how long."""
    if todo == 0:
        return (f"All {total} chapters were judged by the model since they last changed; "
                "nothing new to judge.")
    requests = todo * REQUESTS_PER_CHAPTER
    cloud = _minutes(requests * sum(SECONDS_CLOUD) / 2)
    local = _minutes(todo * REQUESTS_PER_CHAPTER_LOCAL * sum(SECONDS_LOCAL) / 2)
    which = (f"{todo} of {total} chapters" if todo < total else f"all {total} chapters")
    return (f"The model will judge {which} (the others haven't changed since it last did): "
            f"about {requests} requests. That's {cloud} with a cloud model, or {local} on a "
            "local or home-server model, which proofreads in smaller pieces.\n\nThe model "
            "reads each chapter for character disconnects, plot jumps and continuity against "
            "the facts of the chapters before it, outlines its scenes, proofreads it, and "
            "judges what the scan found.\n\nIt runs in the background, so you can keep "
            "writing. Stop keeps every chapter already judged, and the next run carries on "
            "from there.")


def background_on() -> bool:
    try:
        from src.ui.ui_kit import _settings
        return str(_settings().value(BACKGROUND_KEY, "false")).lower() == "true"
    except Exception:
        return False


def set_background(on: bool) -> None:
    try:
        from src.ui.ui_kit import _settings
        _settings().setValue(BACKGROUND_KEY, "true" if on else "false")
    except Exception:
        pass


def show_corrections_in_editor(widget) -> None:
    """After a model run: the open chapter's underlines take in the
    corrections the model just found (they are ordinary grammar flags)."""
    try:
        ce = widget.window().manuscript_editor.current_chapter_editor
        if ce is not None:
            ce.editor.writing_highlighter.rehighlight()
    except Exception:
        pass                      # no editor open (or the Critique is in its own window)


def confirm(parent, todo: int, total: int) -> Tuple[bool, bool]:
    """(start, keep judging in the background) from the writer."""
    from PyQt6.QtWidgets import QCheckBox, QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle("Check the book with the model")
    box.setText(estimate(todo, total))
    keep = QCheckBox("Also judge changed chapters in the background while I write")
    keep.setChecked(background_on())
    box.setCheckBox(keep)
    start = box.addButton("Start" if todo else "Check anyway", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is start, keep.isChecked()
