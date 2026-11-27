"""Whole tab names (piece D.13c).

The cause of tab names cut short ("Plan…", "Feedb…", "Companio…") while
the side panel had room for them: the panel's style sheet set the tab
names' size on the tab alone (``QTabBar::tab { font-size: 11px }``). Qt
measures each tab, and decides whether its name must be shortened, with
the tab *bar's* own font (13 px, from the app's ``QWidget`` rule), but
draws the name with the tab's font (11 px). On macOS a tab bar shortens
names that do not fit (``ElideRight`` is the Mac style's default), so a
name measured at 13 px for a tab sized for 11 px was cut with "…" even
with room to spare. Qt's own style (the harness draws with it offscreen)
never shortens, so the pictures did not show it.

``whole(tabs, px)`` gives the bar the same font as its tabs, so a name is
measured as it is drawn, and makes every platform behave alike: a name
shortens with "…" only when the bar is really too narrow for it, and
never hides behind scroll arrows.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabBar, QTabWidget

# The weight the app's style sheet gives every tab name (styles.py,
# ``QTabBar::tab { font-weight: 500 }``): kept, so the names look as before.
APP_TAB_WEIGHT = 500


def font_rule(px: int, weight: int = APP_TAB_WEIGHT) -> str:
    """The same font for the bar and its tabs (later rules win, so this is
    added after the sheet's own)."""
    return (f" QTabBar {{ font-size: {px}px; font-weight: {weight}; }}"
            f" QTabBar::tab {{ font-size: {px}px; font-weight: {weight}; }}")


def bar_of(tabs: Any) -> QTabBar:
    return tabs.tabBar() if isinstance(tabs, QTabWidget) else tabs


def whole(tabs: Any, px: int, weight: int = APP_TAB_WEIGHT) -> None:
    """Tab names of ``px`` pixels, measured as drawn, whole unless the bar
    is too narrow (then shortened with "…", on every platform)."""
    try:
        rule = font_rule(px, weight)
        sheet = tabs.styleSheet() or ""
        if rule not in sheet:
            tabs.setStyleSheet(sheet + rule)
        bar = bar_of(tabs)
        bar.setElideMode(Qt.TextElideMode.ElideRight)
        bar.setUsesScrollButtons(False)
    except Exception as e:                       # the names stay as they were
        print(f"[tab names] {e}")
