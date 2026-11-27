"""**Details** beside the ribbon's tab names (pieces D.13c and its follow-up).

The writer's answer (27 Nov), after the "Where you left off" line had moved
onto the ribbon: "Move the blue box to a button next to Draft in the bar
where Home, Insert and Draft are. We can call the tab Details. The blue bar
is unnecessary. The text where we left off is no longer required as well."

    ◂ Chapters  Home · Review · Insert · Draft · Details

* **Details** looks like a tab name and does what the blue line's Details
  button did: it opens the whole side panel on the Companion, at "Where you
  left off" (open and scrolled into view), or closes it if that is what is
  showing. It is underlined while the panel shows the Companion.
* The blue line (``CompanionBanner``) is no longer shown above the text or
  on the ribbon. Nothing is lost (rule 11): "Where you left off" and its
  words are still the first section of the Companion, which Details opens,
  and the banner object still receives its text (its hover text names it),
  so everything that sets or reads ``companion_banner`` keeps working.
* Without a ribbon (it could not be built) the old line stays above the
  text, as before.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSizePolicy, QToolButton

DETAILS = "Details"
TIP = ("Details: show or hide the side panel (Companion, Feedback, Planner), "
       "opening on Where you left off.")


def install(ce: Any) -> Optional[QToolButton]:
    """The call line in ``ChapterEditor._init_ui``, after the ribbon."""
    try:
        return _install(ce)
    except Exception as e:                       # the line stays above the text
        print(f"[details] not added to the ribbon: {e}")
        return None


def _style() -> str:
    from src.ui.write_ribbon import PALETTE
    c = PALETTE
    return (
        "QToolButton { background: transparent; border: none;"
        " border-bottom: 3px solid transparent; border-top-left-radius: 4px;"
        " border-top-right-radius: 4px; padding: 4px 14px 3px 14px;"
        f" color: {c['ink_soft']}; font-size: 13px; font-weight: 500; }}"
        f" QToolButton:checked {{ color: {c['ink']}; font-weight: 600;"
        f" border-bottom: 3px solid {c['primary_dark']}; }}"
        f" QToolButton:hover:!checked {{ color: {c['ink']}; background: {c['surface_hover']};"
        f" border-bottom: 3px solid {c['border_strong']}; }}"
        f" QToolButton:focus {{ border: 2px solid {c['primary_dark']};"
        f" border-bottom: 3px solid {c['primary_dark']}; }}")


def _install(ce: Any) -> Optional[QToolButton]:
    ribbon = getattr(ce, "write_ribbon", None)
    banner = getattr(ce, "companion_banner", None)
    if ribbon is None or banner is None:
        return None
    lay = banner.parentWidget().layout() if banner.parentWidget() is not None else None
    if lay is not None and lay.indexOf(banner) >= 0:
        lay.removeWidget(banner)                 # the blue line goes
    banner.setParent(ribbon)
    banner.hide()

    def keep_text(text: str, tooltip: str = "") -> None:   # the words, never the line
        banner.label.setText(text)
        banner.setToolTip(tooltip)
    banner.show_text = keep_text

    btn = QToolButton(ribbon.strip)
    btn.setObjectName("writeRibbonDetails")
    btn.setText(DETAILS)
    btn.setCheckable(True)
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setStyleSheet(_style())
    btn.setToolTip(TIP)
    btn.setAccessibleName(DETAILS)
    btn.setAccessibleDescription(TIP.split(": ", 1)[1])

    def clicked(_=False):
        banner.details_btn.click()               # the same toggle as before
        sync()
    btn.clicked.connect(clicked)

    def sync():
        btn.setChecked(banner.details_btn.text() != DETAILS)   # "Hide details" while open
    original = banner.set_details_open

    def set_details_open(is_open: bool) -> None:
        original(is_open)
        sync()
    banner.set_details_open = set_details_open
    sync()

    ribbon.strip.layout().addWidget(btn)         # right after Draft
    ribbon.details_btn = btn
    ce.details_tab = btn
    return btn
