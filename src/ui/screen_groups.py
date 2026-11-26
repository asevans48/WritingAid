"""Five top-level tabs instead of ten, and one way to put a screen in its
own window (piece D.4, settled decisions 10 and 11).

The ten screens are grouped:

    Write    · Write
    Story    · Plot, Characters, World
    Revise   · Critique, Prose Profile, Attributions
    Publish  · Publishing
    Studio   · Visuals, Video Studio

A group with one screen shows no inner tab bar, so Write and Publish look as
they did. Screens keep their names inside their group, and each group
remembers the screen last used in it.

**One mechanism for detaching.** Right-click any tab (a group, or a screen
inside one) → "Open … in Its Own Window". The Critique menu's "Critique in
Its Own Window" (piece 2.5) and View ▸ Multi-Window Mode use the same mover.
The first time, a window is tiled beside the main window; after that it
opens where it was left. The tab it came from says "Show it · Bring it back
here"; choosing that tab raises the window; closing the window brings the
screen back.

**Backwards compatible.**

* ``show(main_window, widget)`` is the one call that shows a screen: its
  group, then its inner tab, or its window if it is out. The main window's
  ``tab_widget.setCurrentWidget(screen)`` and ``tab_widget.currentWidget()``
  are routed through it too, so older code that names a screen still lands
  on it.
* ``OLD_TABS`` is the old order of the ten tabs; ``old_tab`` maps an old
  index to its screen (tested for every value).
* The old ten-tab arrangement is one switch away: Settings ▸ Features ▸
  Main tabs (``ARRANGEMENT_KEY``), during the trial (rule 11).
* No saved window layout existed before this piece (Multi-Window Mode never
  stored one); the Critique's own window kept ``critique_window/geometry``
  and ``critique_window/out``, and both are still read and written.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QByteArray, QEvent, QObject, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QGroupBox, QLabel, QMenu, QTabWidget, QVBoxLayout, QWidget,
)

# The ten tabs before D.4, in their old order: (key, main-window attribute).
# The index in this tuple is the tab's old index.
OLD_TABS: Tuple[Tuple[str, str], ...] = (
    ("write", "manuscript_editor"),
    ("plot", "story_planning_widget"),
    ("characters", "characters_widget"),
    ("world", "worldbuilding_widget"),
    ("attributions", "attributions_tab"),
    ("visuals", "image_generator"),
    ("prose_profile", "prose_profile_widget"),
    ("critique", "grader_widget"),
    ("video_studio", "video_studio_widget"),
    ("publishing", "agent_manager"),
)

# The five groups (decision 11): (key, label, screens in order).
GROUPS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("write", "✍️ Write", ("write",)),
    ("story", "📖 Story", ("plot", "characters", "world")),
    ("revise", "📊 Revise", ("critique", "prose_profile", "attributions")),
    ("publish", "📧 Publish", ("publishing",)),
    ("studio", "🎬 Studio", ("visuals", "video_studio")),
)

ARRANGEMENT_KEY = "screen_groups/arrangement"     # "groups" (default) or "ten"
LAST_KEY = "screen_groups/last/{group}"           # the screen last used in a group
GEOMETRY_KEY = "screen_windows/{key}/geometry"    # where a screen's window was left
# The Critique's window kept these before D.4 (piece 2.5); still read and written.
CRITIQUE_GEOMETRY_KEY = "critique_window/geometry"
CRITIQUE_OUT_KEY = "critique_window/out"
SHARE = 0.42                                       # of the screen's width, the first time

NOTE = ("<p style='font-size:14px'>{name} is open in its own window.</p>"
        "<p><a href='raise'>Show it</a> · <a href='back'>Bring it back here</a></p>")


def _settings():
    from src.ui.ui_kit import _settings as kit_settings
    return kit_settings()


def _get(key: str, default: str = "") -> str:
    try:
        value = _settings().value(key, default)
        return default if value is None else str(value)
    except Exception:
        return default


def _set(key: str, value: Any) -> None:
    try:
        s = _settings()
        s.setValue(key, value)
        s.sync()
    except Exception as e:                      # window state never breaks the app
        print(f"[screen groups] could not record {key}: {e}")


def grouped() -> bool:
    """True for the five groups (the default), False for the old ten tabs."""
    return _get(ARRANGEMENT_KEY, "groups") != "ten"


def _plain_name(label: str) -> str:
    """"📖 Story" → "Story"."""
    first, _, rest = (label or "").strip().partition(" ")
    if rest and not any(ch.isalnum() for ch in first):
        return rest.strip()
    return (label or "").strip()


# ── The parts ────────────────────────────────────────────────────────

class Slot(QWidget):
    """A tab's page: holds a screen (or a group's inner tabs) and, while it
    is in its own window, a note saying so."""

    def __init__(self, unit: "Unit"):
        super().__init__()
        self.unit = unit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(unit.content)
        unit.content.setVisible(True)        # a tab page left hidden by its old stack
        self.note = QLabel(NOTE.format(name=unit.name))
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setVisible(False)
        lay.addWidget(self.note)


class ScreenWindow(QWidget):
    """A screen (or a whole group) in its own window."""

    def __init__(self, unit: "Unit", parent: QWidget):
        super().__init__(parent, Qt.WindowType.Window)
        self.unit = unit
        self.setWindowTitle(unit.name)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

    def closeEvent(self, event):
        self.unit.save_geometry()
        event.accept()
        self.unit.owner.bring_back(self.unit, from_close=True)


class Unit:
    """Something that can go into its own window: one screen, or a group of
    several (its inner tabs)."""

    def __init__(self, owner: "Groups", key: str, label: str, content: QWidget,
                 inner: Optional[QTabWidget] = None):
        self.owner = owner
        self.key = key
        self.label = label
        self.name = _plain_name(label)
        self.content = content
        self.inner = inner                      # a group's inner tabs
        self.window: Optional[ScreenWindow] = None
        self.slot = Slot(self)
        self.slot.note.linkActivated.connect(
            lambda href: self.raise_window() if href == "raise" else owner.bring_back(self))

    @property
    def is_out(self) -> bool:
        return self.window is not None

    @property
    def geometry_key(self) -> str:
        return CRITIQUE_GEOMETRY_KEY if self.key == "critique" else GEOMETRY_KEY.format(key=self.key)

    def raise_window(self) -> None:
        w = self.window
        if w is not None:
            w.showNormal() if w.isMinimized() else w.show()
            w.raise_()
            w.activateWindow()

    def save_geometry(self) -> None:
        if self.window is not None:
            _set(self.geometry_key, self.window.saveGeometry())


# ── The grouping ─────────────────────────────────────────────────────

class _CloseWatch(QObject):
    """Records where each open window is when the main window closes."""

    def __init__(self, owner: "Groups"):
        super().__init__(owner.tabs)
        self.owner = owner

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Close:
            for unit in self.owner.all_units():
                unit.save_geometry()
        return False


class Groups:
    """Owns the main window's top-level tabs."""

    def __init__(self, main_window: Any):
        self.mw = main_window
        self.tabs: QTabWidget = main_window.tab_widget
        self._building = False
        self._shown: Optional[QWidget] = None
        # Every page the main window added, in its order, with its label.
        pages = [(QTabWidget.widget(self.tabs, i), self.tabs.tabText(i))
                 for i in range(self.tabs.count())]
        by_widget = {id(w): (w, label) for w, label in pages}
        self.screens: Dict[str, Unit] = {}
        for key, attr in OLD_TABS:
            widget = getattr(main_window, attr, None)
            if widget is not None and id(widget) in by_widget:
                self.screens[key] = Unit(self, key, by_widget.pop(id(widget))[1], widget)
        self.extra: List[Tuple[QWidget, str]] = [p for p in pages if id(p[0]) in by_widget]
        self.groups: Dict[str, Unit] = {}
        self._inner_of: Dict[str, Unit] = {}      # screen key → its group (several screens)
        self.flat = not grouped()

    # ── Building ─────────────────────────────────────────────────────

    def build(self) -> None:
        """Lay the tabs out as groups, or as the old ten."""
        self._building = True
        blocked = self.tabs.blockSignals(True)
        try:
            while self.tabs.count():
                self.tabs.removeTab(0)
            old_groups, self.groups, self._inner_of = self.groups, {}, {}
            for unit in old_groups.values():          # free the screens from old inner tabs
                if unit.inner is not None:
                    while unit.inner.count():
                        page = unit.inner.widget(0)
                        unit.inner.removeTab(0)
                        page.setParent(None)      # not deleted with the old group
            if self.flat:
                for key, _attr in OLD_TABS:
                    unit = self.screens.get(key)
                    if unit is not None:
                        self.tabs.addTab(unit.slot, unit.label)
            else:
                for key, label, members in GROUPS:
                    units = [self.screens[m] for m in members if m in self.screens]
                    if not units:
                        continue
                    if len(units) == 1:
                        index = self.tabs.addTab(units[0].slot, label)
                        self.tabs.setTabToolTip(index, units[0].name)
                        continue
                    group = self._group(key, label, units)
                    index = self.tabs.addTab(group.slot, label)
                    self.tabs.setTabToolTip(index, " · ".join(u.name for u in units))
            for widget, label in self.extra:
                self.tabs.addTab(widget, label)
            for unit in old_groups.values():
                if unit.window is not None:
                    unit.window.hide()
                    unit.window.deleteLater()
                unit.slot.deleteLater()
        finally:
            self.tabs.blockSignals(blocked)
            self._building = False

    def _group(self, key: str, label: str, units: List[Unit]) -> Unit:
        inner = QTabWidget()
        inner.setDocumentMode(True)
        inner.setMovable(True)
        for unit in units:
            inner.addTab(unit.slot, unit.label)
        last = self.screens.get(_get(LAST_KEY.format(group=key)))
        if last is not None and last in units:
            inner.setCurrentWidget(last.slot)
        bar = inner.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(lambda pos, i=inner: self._inner_menu(i, pos))
        group = Unit(self, key, label, inner, inner=inner)
        inner.currentChanged.connect(lambda index, g=group: self._inner_changed(g, index))
        for unit in units:
            self._inner_of[unit.key] = group
        self.groups[key] = group
        return group

    def arrange(self, flat: bool) -> None:
        """Switch between the five groups and the old ten tabs, live."""
        if flat == self.flat:
            return
        showing = self.current_screen()
        self.bring_all_back()
        self.flat = flat
        self.build()
        if showing is not None:
            self.show(showing)

    # ── Finding things ───────────────────────────────────────────────

    def all_units(self) -> List[Unit]:
        return list(self.screens.values()) + list(self.groups.values())

    def screen_unit(self, widget: Any) -> Optional[Unit]:
        return next((u for u in self.screens.values() if u.content is widget), None)

    def group_of(self, unit: Unit) -> Optional[Unit]:
        return self._inner_of.get(unit.key)

    def _unit_for_page(self, page: Any) -> Optional[Unit]:
        return next((u for u in self.all_units() if u.slot is page), None)

    def _screen_in(self, page: Any) -> Optional[QWidget]:
        unit = self._unit_for_page(page)
        if unit is None:
            return page
        if unit.inner is not None:
            inner = self._unit_for_page(unit.inner.currentWidget())
            return inner.content if inner is not None else None
        return unit.content

    def current_screen(self) -> Optional[QWidget]:
        """The screen the main window's current tab shows (inside its group)."""
        return self._screen_in(QTabWidget.currentWidget(self.tabs))

    def shown_screen(self) -> Optional[QWidget]:
        """The screen last chosen, in the main window or in a group's window."""
        return self._shown if self._shown is not None else self.current_screen()

    # ── Showing a screen ─────────────────────────────────────────────

    def show(self, widget: Any) -> None:
        """Select ``widget``'s group, then its inner tab; raise its window
        if it is out."""
        unit = self.screen_unit(widget)
        if unit is None:
            if widget is not None and self.tabs.indexOf(widget) >= 0:
                QTabWidget.setCurrentWidget(self.tabs, widget)
            return
        group = self.group_of(unit)
        if group is not None:
            group.inner.setCurrentWidget(unit.slot)
        page = group.slot if group is not None else unit.slot
        QTabWidget.setCurrentWidget(self.tabs, page)
        self._shown = widget
        if unit.is_out:
            unit.raise_window()
        elif group is not None and group.is_out:
            group.raise_window()
        elif any(u.is_out for u in self.all_units()):
            self.mw.raise_()                       # out of sight behind a window
            self.mw.activateWindow()

    def show_old_tab(self, index: int) -> None:
        widget = old_tab(self.mw, index)
        if widget is not None:
            self.show(widget)

    def _outer_changed(self, index: int) -> None:
        if self._building:
            return
        unit = self._unit_for_page(QTabWidget.widget(self.tabs, index))
        self._shown = self._screen_in(QTabWidget.widget(self.tabs, index))
        if unit is None:
            return
        if unit.is_out:
            unit.raise_window()
        elif unit.inner is not None:
            inner = self._unit_for_page(unit.inner.currentWidget())
            if inner is not None and inner.is_out:
                inner.raise_window()

    def _inner_changed(self, group: Unit, index: int) -> None:
        if self._building:
            return
        unit = self._unit_for_page(group.inner.widget(index))
        if unit is None:
            return
        _set(LAST_KEY.format(group=group.key), unit.key)
        self._shown = unit.content
        if unit.is_out:
            unit.raise_window()
        on_changed = getattr(self.mw, "_on_tab_changed", None)
        if callable(on_changed):
            try:
                on_changed(self.tabs.currentIndex())
            except Exception as e:                 # never break a tab switch
                print(f"[screen groups] {e}")

    # ── Out and back (the one mover) ─────────────────────────────────

    def detach(self, unit: Unit) -> None:
        if unit.is_out:
            unit.raise_window()
            return
        showing = self.current_screen()
        holds = [unit.content] if unit.inner is None else [
            u.content for u in self.screens.values() if self.group_of(u) is unit]
        window = ScreenWindow(unit, self.mw)
        unit.window = window
        unit.slot.layout().removeWidget(unit.content)
        window.layout().addWidget(unit.content)
        unit.content.show()
        unit.slot.note.setVisible(True)
        self._place(window, unit)
        window.show()
        window.raise_()
        window.activateWindow()
        if unit.key == "critique":
            _set(CRITIQUE_OUT_KEY, "true")
        write = self.screens.get("write")
        if showing in holds and write is not None and write.content not in holds:
            self.show(write.content)               # Write, beside it
        self._status(f"“{unit.name}” is in its own window. Close it to bring it back.")

    def bring_back(self, unit: Unit, from_close: bool = False) -> None:
        window, unit.window = unit.window, None
        if window is None:
            return
        if not from_close:
            try:
                _set(unit.geometry_key, window.saveGeometry())
            except Exception:
                pass
        window.layout().removeWidget(unit.content)
        unit.slot.note.setVisible(False)
        unit.slot.layout().insertWidget(0, unit.content)
        unit.content.show()
        if unit.key == "critique":
            _set(CRITIQUE_OUT_KEY, "false")
        if not from_close:
            window.hide()
        window.deleteLater()
        if unit.inner is not None:
            current = self._unit_for_page(unit.inner.currentWidget())
            QTabWidget.setCurrentWidget(self.tabs, unit.slot)
            if current is not None:
                self._shown = current.content
        else:
            self.show(unit.content)

    def bring_all_back(self) -> None:
        for unit in self.all_units():
            if unit.is_out:
                self.bring_back(unit)

    def toggle(self, unit: Unit) -> None:
        self.bring_back(unit) if unit.is_out else self.detach(unit)

    def _place(self, window: ScreenWindow, unit: Unit) -> None:
        """Where it was left; the first time, tiled with the main window
        (the main window on the left, this one on the right)."""
        try:
            saved = _settings().value(unit.geometry_key)
        except Exception:
            saved = None
        if isinstance(saved, (QByteArray, bytes)) and window.restoreGeometry(saved):
            return
        screen = self.mw.screen() if hasattr(self.mw, "screen") else None
        if screen is None:
            window.resize(560, 700)
            return
        area = screen.availableGeometry()
        right = max(420, int(area.width() * SHARE))
        left = area.width() - right
        mw = self.mw
        if mw.isMaximized() or mw.isFullScreen():
            mw.showNormal()
        if mw.width() > left:
            mw.setGeometry(area.left(), area.top(), left, area.height())
        window.setGeometry(area.left() + left, area.top(), right, area.height())

    def _status(self, text: str) -> None:
        try:
            self.mw.statusBar().showMessage(text, 4000)
        except Exception:
            pass

    # ── Right-click a tab ────────────────────────────────────────────

    def _menu_for(self, menu: QMenu, unit: Unit) -> None:
        if unit.is_out:
            menu.addAction(f"Bring “{unit.name}” Back").triggered.connect(
                lambda _=False, u=unit: self.bring_back(u))
        else:
            menu.addAction(f"Open “{unit.name}” in Its Own Window").triggered.connect(
                lambda _=False, u=unit: self.detach(u))

    def outer_menu(self, pos) -> None:
        bar = self.tabs.tabBar()
        index = bar.tabAt(pos)
        unit = self._unit_for_page(QTabWidget.widget(self.tabs, index)) if index >= 0 else None
        if unit is None:
            return
        menu = QMenu(self.tabs)
        self._menu_for(menu, unit)
        menu.exec(bar.mapToGlobal(pos))

    def _inner_menu(self, inner: QTabWidget, pos) -> None:
        bar = inner.tabBar()
        index = bar.tabAt(pos)
        unit = self._unit_for_page(inner.widget(index)) if index >= 0 else None
        if unit is None:
            return
        menu = QMenu(inner)
        self._menu_for(menu, unit)
        group = self.group_of(unit)
        if group is not None and group.is_out:      # as Multi-Window's "Merge to Main Window"
            menu.addAction(f"Bring “{group.name}” Back to the Main Window").triggered.connect(
                lambda _=False, g=group: self.bring_back(g))
        menu.exec(bar.mapToGlobal(pos))


# ── Call lines (rule 14) ─────────────────────────────────────────────

def install(main_window: Any) -> Optional[Groups]:
    """Called once the main window has added its ten tabs."""
    existing = getattr(main_window, "screen_groups", None)
    if existing is not None:
        return existing
    tabs = getattr(main_window, "tab_widget", None)
    if tabs is None:
        return None
    pages = [(tabs.widget(i), tabs.tabText(i)) for i in range(tabs.count())]
    try:
        groups = Groups(main_window)
        groups.build()
    except Exception as e:                        # never lose a tab: put the ten back
        print(f"[screen groups] not available: {e}")
        while tabs.count():
            tabs.removeTab(0)
        for widget, label in pages:
            tabs.addTab(widget, label)
        return None
    main_window.screen_groups = groups
    tabs.currentChanged.connect(groups._outer_changed)
    # Older code that names a screen still lands on it.
    tabs.setCurrentWidget = lambda widget: groups.show(widget)
    tabs.currentWidget = groups.current_screen
    try:
        main_window.installEventFilter(_CloseWatch(groups))
    except Exception:
        pass
    return groups


def ensure(main_window: Any) -> Optional[Groups]:
    return getattr(main_window, "screen_groups", None) or install(main_window)


def show(main_window: Any, widget: Any) -> None:
    """Show a screen, wherever it is. The one call every "open X" uses."""
    groups = getattr(main_window, "screen_groups", None)
    if groups is not None:
        groups.show(widget)
    else:
        main_window.tab_widget.setCurrentWidget(widget)


def current_screen(main_window: Any) -> Optional[QWidget]:
    groups = getattr(main_window, "screen_groups", None)
    if groups is not None:
        return groups.shown_screen()
    tabs = getattr(main_window, "tab_widget", None)
    return tabs.currentWidget() if tabs is not None else None


def old_tab(main_window: Any, index: int) -> Optional[QWidget]:
    """The screen an old tab index (0 to 9, the ten-tab order) meant."""
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(OLD_TABS):
        return None
    return getattr(main_window, OLD_TABS[index][1], None)


def tab_menu(main_window: Any, pos) -> None:
    """Right-click a top-level tab."""
    groups = getattr(main_window, "screen_groups", None)
    if groups is not None:
        groups.outer_menu(pos)


def detach_tab(main_window: Any, tab_index: int) -> None:
    """Multi-Window Mode's "Create New Window" for a top-level tab."""
    groups = getattr(main_window, "screen_groups", None)
    if groups is None:
        return
    unit = groups._unit_for_page(QTabWidget.widget(groups.tabs, tab_index))
    if unit is not None:
        groups.detach(unit)


def bring_all_back(main_window: Any) -> None:
    groups = getattr(main_window, "screen_groups", None)
    if groups is not None:
        groups.bring_all_back()


def set_grouped(on: bool, main_window: Any = None) -> None:
    """Record the arrangement and apply it to the open main window."""
    _set(ARRANGEMENT_KEY, "groups" if on else "ten")
    if main_window is None:
        try:
            from src.ui.window_manager import WindowManager
            main_window = WindowManager().get_main_window()
        except Exception:
            main_window = None
    groups = getattr(main_window, "screen_groups", None)
    if groups is not None:
        groups.arrange(not on)


class TabsOption:
    """Settings ▸ Features ▸ Main tabs: the five groups, or the old ten
    (two call lines in ``SettingsDialog``)."""

    def __init__(self, layout):
        group = QGroupBox("Main tabs")
        lay = QVBoxLayout()
        self.box = QCheckBox("Group the tabs into five: Write · Story · Revise · Publish · Studio")
        self.box.setToolTip("Untick for the ten tabs as they were. Either way, right-click "
                            "any tab to open it in its own window.")
        self.box.setChecked(grouped())
        lay.addWidget(self.box)
        group.setLayout(lay)
        layout.addWidget(group)

    def save(self) -> None:
        try:
            if self.box.isChecked() != grouped():
                set_grouped(self.box.isChecked())
        except Exception as e:                       # noqa: BLE001
            print(f"[screen groups] could not save: {e}")
