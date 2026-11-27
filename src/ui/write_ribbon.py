"""Write's ribbon (pieces D.13 and D.13b).

Four tabs over one row of controls, like Word's tab names, in D.8's one
look (plain buttons)::

    ◂ Chapters   Home · Review · Insert · Draft
    [Arial] [12] │ B I U │ [Normal] │ ✨ Improve

* **Home:** font, size, B I U, heading style and ✨ Improve (Ctrl+R).
* **Review:** ✓ Checks ▾, 🔊 Read Aloud and 🔍 Analyze ▾ (from the bottom row).
* **Insert:** 📝 Annotation (click adds, Ctrl+Shift+N; its arrow lists them),
  📋 View annotations, and 🎬 Scene break here / Remove scene break at the
  text cursor (7.4's marker; the right-click entry is unchanged).
* **Draft:** Editing: [manuscript or draft], 📚 Manuscript ▾ (was "Drafts
  ▾") and ⇅ Split View (the top row's), then 📄 Chapter ▾ (was "This
  chapter:" 📄 Draft ▾, the bottom row's). Same menus, same entries.

**D.13b, the polish.** The tab names are the app's body size with room
around them; the chosen one is bold and underlined, a hover tints the
others, and the keyboard focus draws a ring. Every control has an icon
(the app's emoji style, as its other buttons) and its words: no icon-only
buttons, B I U and the boxes excepted. Every control has hover text that
leads with its name, then its shortcut, then what it does (``TIPS``), and
the same as its accessible name and description; Tab reaches each one and
shows a focus ring. On a narrow Write the tab names wrap under "◂
Chapters" rather than scroll.

The top row is gone: its Total joins the bottom row ("Words: 67  Total:
12,480"), its ◂ (hide the chapter sidebar) sits before the tab names, and
its draft controls are on Draft. The Chapter Title row is hidden too:
chapters are renamed in the manuscript tree (``manuscript_tree``,
double-click, F2 or right-click ▸ Rename…).

**Nothing removed** (rule 11). The same widgets and actions are moved, not
rebuilt, so everything wired to them works as before. The old toolbar is
kept, hidden, holding B I U and ✨ (their buttons on Home show the same
actions); each action with a shortcut is also put on the chapter editor,
so Ctrl+B, Ctrl+I, Ctrl+U, Ctrl+R, Ctrl+Shift+N and Ctrl+Shift+H work
whichever tab is showing. The title box is kept, hidden, and still saved.

**Home is shown first**; the tab last chosen is remembered (``TAB_KEY`` in
the window-state settings; anything unreadable there means Home).

**Narrow screens:** each tab's row is a ``FlowLayout``: a few buttons take
shorter words, then the row wraps; nothing is cut off.

**When no chapter is open** (an empty manuscript, a switch in progress) the
old top row comes back with Total and the draft controls, so they are
never out of reach.
"""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QTabBar, QToolBar, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from src.ui import ui_kit
from src.ui.ui_kit import PALETTE, FlowLayout, plain, short_label

HOME, REVIEW, INSERT, DRAFT = TABS = ("Home", "Review", "Insert", "Draft")
TAB_KEY = "write/ribbon_tab"

# The words for the writer (decision 18: one place, so F.1 can change them).
CHAPTER = "chapter"
MANUSCRIPT = "manuscript"
THIS_CHAPTER = f"This {CHAPTER}:"            # D.13's label; gone since D.13b named the menu
ANNOTATION = "📝 Annotation"
VIEW_ANNOTATIONS = "📋 View annotations"
# D.13b: icons with words (the app's emoji style), and the two renames.
IMPROVE = "✨ Improve"
SCENE_ICON = "🎬"
CHAPTER_MENU = f"📄 {CHAPTER.capitalize()} ▾"        # was "📄 Draft ▾" (this chapter's drafts)
MANUSCRIPT_MENU = f"📚 {MANUSCRIPT.capitalize()} ▾"  # was "Drafts ▾" (the manuscript's drafts)
SIDEBAR = f"{CHAPTER.capitalize()}s"                  # the ◂ before the tab names

# Hover text and screen-reader words for every control (D.13b): its full
# name, its shortcut (added from the action when it has one), then what it
# does in one sentence. Name, then what it does.
TIPS = {
    "font": ("Font", "The typeface for the selected text, or for what you type next."),
    "size": ("Font size", "The size, in points, of the selected text or of what you type next."),
    "bold": ("Bold", "Make the selected text bold, or what you type next."),
    "italic": ("Italic", "Make the selected text italic, or what you type next."),
    "underline": ("Underline", "Underline the selected text, or what you type next."),
    "heading": ("Heading style", "Make this paragraph normal text, a title or a heading "
                "(H1 to H4); headings carry into Word, HTML and Markdown."),
    "improve": ("Improve", "Open the Improve window on the selected text: rephrasings, "
                "suggestions and an over-description check."),
    "checks": ("Checks", "Choose which writing checks underline the text, and when they run."),
    "read": ("Read Aloud", "Read the chapter aloud, or the selection; click again to pause. "
             "The arrow has Stop, Read chapters… and Export audio file…"),
    "analyze": ("Analyze", f"Run a critique or a report on this {CHAPTER} (shown in the "
                "Critique), or check names and spellings."),
    "annotation": ("Annotation", "Add a note at the current line; the arrow lists every "
                   "annotation."),
    "view": ("View annotations", f"List every annotation in this {CHAPTER}."),
    "editing": ("Editing", f"Switch between the main {MANUSCRIPT} and a saved draft of it; "
                "edits are kept separately for each draft."),
    "manuscript": (MANUSCRIPT.capitalize(), f"Save the {MANUSCRIPT} as a new draft, drop this "
                   "draft, or open a draft in its own window."),
    "split": ("Split View", "Show another draft beside this one, in this window."),
    "chapter": (CHAPTER.capitalize(), f"Save or view this {CHAPTER}'s drafts, import from or "
                "export to Word, or clean up its formatting."),
}
TAB_TIPS = {
    HOME: "Home: font, size, bold, italic, underline, heading style and Improve.",
    REVIEW: "Review: writing checks, Read Aloud and Analyze.",
    INSERT: "Insert: annotations and scene breaks.",
    DRAFT: f"Draft: the {MANUSCRIPT}'s drafts, Split View, and this {CHAPTER}'s drafts.",
}

# Where each toolbar widget goes; anything not named stays on Home.
_TOOLBAR_TABS = {"checks_btn": REVIEW, "tts_speak_btn": REVIEW}


# ── The remembered tab ─────────────────────────────────────────────────

def saved_tab() -> str:
    try:
        value = ui_kit._settings().value(TAB_KEY)
        return value if value in TABS else HOME
    except Exception:                            # unreadable state: the default
        return HOME


def save_tab(name: str) -> None:
    try:
        s = ui_kit._settings()
        s.setValue(TAB_KEY, name)
        s.sync()
    except Exception as e:                       # never break a tab switch
        print(f"[write ribbon] tab not remembered: {e}")


# ── The ribbon ─────────────────────────────────────────────────────────

def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet(f"color: {PALETTE['border']};")
    return line


def keys_of(action: Any) -> str:
    """An action's shortcut as this computer writes it (⌘B on a Mac)."""
    try:
        return action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    except Exception:
        return ""


def tip_text(name: str, what: str, keys: str = "") -> str:
    """"Name (keys): what it does." (D.13b)"""
    return f"{name} ({keys}): {what}" if keys else f"{name}: {what}"


def describe(widget: QWidget, key: str, keys: str = "", tip: bool = True) -> None:
    """Hover text, accessible name and description for a ribbon control,
    from ``TIPS``. ``tip=False`` leaves the hover text to the code that
    keeps it up to date."""
    name, what = TIPS[key]
    if tip:
        widget.setToolTip(tip_text(name, what, keys))
    widget.setAccessibleName(name)
    widget.setAccessibleDescription(what + (f" Shortcut: {keys}." if keys else ""))


def _focus_rule(widget: QWidget) -> str:
    for cls in ("QToolButton", "QPushButton", "QComboBox", "QSpinBox"):
        if widget.inherits(cls):
            return f"{cls}:focus {{ border: 2px solid {PALETTE['primary_dark']}; }}"
    return ""


def focus_ring(widget: QWidget) -> None:
    """A visible ring when the control has the keyboard focus (Tab)."""
    rule = _focus_rule(widget)
    sheet = widget.styleSheet() or ""
    if not rule or rule in sheet:
        return
    if sheet.strip() and "{" not in sheet:       # bare declarations: give them a selector
        sheet = f"{rule.split(':')[0]} {{ {sheet} }}"
    widget.setStyleSheet((sheet + "\n" if sheet.strip() else "") + rule)
    if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
        widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)


def tab_style() -> str:
    """Legible tab names (D.13b): body-text size, room around each, the
    chosen tab underlined and bold, a hover tint and a focus ring."""
    c = PALETTE
    return (
        "QTabBar { font-size: 13px; font-weight: 500; }"   # D.13c: measured as drawn
        " QTabBar::tab { background: transparent; border: none;"
        " border-bottom: 3px solid transparent; border-top-left-radius: 4px;"
        " border-top-right-radius: 4px; padding: 4px 14px 3px 14px; margin: 0 4px 0 0;"
        f" color: {c['ink_soft']}; font-size: 13px; }}"
        f" QTabBar::tab:selected {{ color: {c['ink']}; font-weight: 600;"
        f" border-bottom: 3px solid {c['primary_dark']}; }}"
        f" QTabBar::tab:hover:!selected {{ color: {c['ink']}; background: {c['surface_hover']};"
        f" border-bottom: 3px solid {c['border_strong']}; }}"
        f" QTabBar::tab:focus {{ border: 2px solid {c['primary_dark']};"
        f" border-bottom: 3px solid {c['primary_dark']}; }}")


class Ribbon(QWidget):
    """Tab names over one row of controls per tab."""

    tab_shown = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("writeRibbon")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#writeRibbon {{ border-bottom: 1px solid {PALETTE['border']}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 0, 6, 3)
        outer.setSpacing(1)

        # The ◂ and the tab names: a row that wraps (D.13b), so on a narrow
        # Write the tab names go under "◂ Chapters" rather than scrolling.
        self.strip = QWidget(self)
        strip = FlowLayout(self.strip, spacing=6)
        strip.setContentsMargins(0, 0, 0, 0)
        lead_box = QWidget(self.strip)
        self.lead = QHBoxLayout(lead_box)        # the sidebar's ◂ when in Write
        self.lead.setContentsMargins(0, 0, 0, 0)
        strip.addWidget(lead_box)
        self.bar = QTabBar(self)
        self.bar.setObjectName("writeRibbonTabs")
        for name in TABS:
            self.bar.addTab(name)
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setDocumentMode(True)
        self.bar.setStyleSheet(tab_style())
        self.bar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # Tab reaches it; arrows switch
        self.bar.setAccessibleName("Write ribbon tabs")
        self.bar.setAccessibleDescription("Home, Review, Insert and Draft; the arrow keys "
                                          "switch between them.")
        for n, name in enumerate(TABS):
            self.bar.setTabToolTip(n, TAB_TIPS[name])
        self.bar.setUsesScrollButtons(False)     # every name whole, never behind arrows
        self.bar.setElideMode(Qt.TextElideMode.ElideNone)
        strip.addWidget(self.bar)
        outer.addWidget(self.strip)

        self.stack = QStackedWidget(self)
        self.rows = {}
        for name in TABS:
            page = QWidget()
            page.setObjectName(f"writeRibbon{name}")
            row = FlowLayout(page, spacing=4)
            row.setContentsMargins(0, 2, 0, 0)
            self.stack.addWidget(page)
            self.rows[name] = row
        outer.addWidget(self.stack)
        # As tall as its row needs, never taller: the rest is the text's.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._remember = True
        self.bar.currentChanged.connect(self._changed)
        self.show_tab(saved_tab(), remember=False)

    def current(self) -> str:
        return TABS[max(0, self.bar.currentIndex())]

    def show_tab(self, name: str, remember: bool = True) -> None:
        i = TABS.index(name) if name in TABS else 0
        self._remember = remember
        try:
            if self.bar.currentIndex() != i:
                self.bar.setCurrentIndex(i)
            else:
                self._changed(i)
        finally:
            self._remember = True

    def _changed(self, i: int) -> None:
        try:
            self.stack.setCurrentIndex(i)
            # Only the tab shown counts for the ribbon's height: a tab whose
            # row has wrapped does not make the others taller.
            for n in range(self.stack.count()):
                page = self.stack.widget(n)
                policy = QSizePolicy.Policy.Preferred if n == i else QSizePolicy.Policy.Ignored
                page.setSizePolicy(policy, policy)
            # ...but every tab is at least one line of the tallest controls,
            # so the text does not jump when the tab changes.
            line = max((self.rows[t].itemAt(n).sizeHint().height()
                        for t in TABS for n in range(self.rows[t].count())
                        if self.rows[t].itemAt(n).widget() is not None
                        and not self.rows[t].itemAt(n).widget().isHidden()), default=0)
            self.stack.setMinimumHeight(line + 2 if line else 0)
            self.stack.updateGeometry()
            if self._remember:
                save_tab(TABS[i])
            self.tab_shown.emit(TABS[i])
        except Exception as e:                   # never escape a slot
            print(f"[write ribbon] {e}")

    def add(self, tab: str, widget: QWidget, separate: bool = False) -> None:
        row = self.rows[tab]
        if separate and row.count():
            row.addWidget(_separator())
        row.addWidget(widget)


# ── A chapter editor's ribbon (the call line in ``ChapterEditor._init_ui``) ──

def build(ce: Any) -> Optional[Ribbon]:
    """Put ``ce``'s toolbar, its bottom row's Analyze ▾ and Draft ▾ and the
    annotation and scene-break entries into a ribbon where the toolbar was,
    and hide the Chapter Title row. If it cannot, the screen stays as it was."""
    try:
        return _build(ce)
    except Exception as e:                       # never break the Write tab
        print(f"[write ribbon] not built: {e}")
        return None


def _layout_holding(layout: Any, widget: QWidget) -> Any:
    """The layout, at any depth under ``layout``, that holds ``widget``."""
    stack = [layout]
    while stack:
        lay = stack.pop()
        if lay.indexOf(widget) >= 0:
            return lay
        for n in range(lay.count()):
            child = lay.itemAt(n).layout()
            if child is not None:
                stack.append(child)
    return None


def _placed_widget(toolbar: QToolBar, act: Any) -> Optional[QWidget]:
    """The editor's own widget that ``act`` puts on ``toolbar`` (the font
    box, the size box, a menu button…), or None for a plain action (B, I,
    U, ✨), which the toolbar draws as its own button.

    Asked of the toolbar rather than by ``isinstance(act, QWidgetAction)``:
    in a long run PyQt can hand back an older Python wrapper for a new
    action, so the type test sometimes failed and the widget was left on
    the hidden toolbar."""
    widget = toolbar.widgetForAction(act)
    if widget is None:
        return None
    if isinstance(widget, QToolButton) and widget.defaultAction() is act:
        return None                              # the toolbar's own button for a plain action
    return widget


def _build(ce: Any) -> Ribbon:
    editor_widget = ce.main_splitter.widget(0)
    lay = editor_widget.layout()
    toolbar = next(t for t in editor_widget.findChildren(QToolBar)
                   if lay.indexOf(t) >= 0)
    bottom = _layout_holding(lay, ce.word_count_label)
    title_row = _layout_holding(lay, ce.title_edit)

    ribbon = Ribbon(editor_widget)
    lay.replaceWidget(toolbar, ribbon)           # at the toolbar's place (split view counts on it)
    toolbar.setParent(ribbon)                    # kept, hidden: its actions live on
    toolbar.hide()
    ce.write_ribbon = ribbon
    ce.ribbon_bottom = bottom

    # Home (and Review / Insert for the widgets that go there), in the
    # toolbar's order; a toolbar separator becomes a line on Home.
    annotations_btn = getattr(toolbar, "annotations_btn", None)
    homes = {id(getattr(ce, a, None)): t for a, t in _TOOLBAR_TABS.items()}
    gap = False
    for act in list(toolbar.actions()):
        if act.isSeparator():
            gap = True
            continue
        if act.shortcut().toString():
            ce.addAction(act)                    # its keys work whichever tab shows
        widget = _placed_widget(toolbar, act)
        if widget is not None:
            if widget is annotations_btn:
                tab = INSERT
            else:
                tab = homes.get(id(widget), HOME)
            toolbar.removeAction(act)            # the toolbar lets go of it, hidden
            ribbon.add(tab, widget, separate=gap and tab == HOME)
            widget.setVisible(True)
        else:                                    # B, I, U, ✨: a button for the same action
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setAutoRaise(True)
            _home_button(btn, act)
            ribbon.add(HOME, btn, separate=gap)
        gap = False

    # Review: 🔍 Analyze ▾ from the bottom row, after the checks and reading.
    _from_bottom(bottom, ce.analyze_btn)
    ribbon.add(REVIEW, ce.analyze_btn, separate=True)
    plain(ce.analyze_btn, 12, "3px 9px")         # one look on every tab (D.13b)
    plain(ce.tts_speak_btn, 12, "3px 9px")
    _split_button(ce.tts_speak_btn)
    ce.tts_speak_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

    # Insert: the annotation button, View annotations, the scene break.
    if annotations_btn is not None:
        add = annotations_btn.defaultAction()
        if add is not None and add.shortcut().toString():
            ce.addAction(add)                    # Ctrl+Shift+N from any tab
        if add is not None:                      # the button shows its action's hover text
            add.setToolTip(tip_text(*TIPS["annotation"], keys_of(add)))
        annotations_btn.setText(ANNOTATION)
        annotations_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        plain(annotations_btn, 12, "3px 9px")
        _split_button(annotations_btn)
        describe(annotations_btn, "annotation", keys_of(add) if add is not None else "", tip=False)
        if add is not None:                      # its words stay when the action changes
            add.changed.connect(lambda b=annotations_btn: b.setText(ANNOTATION))
        view = next((a for a in annotations_btn.menu().actions()
                     if a.text().startswith("📋")), None)
        if view is not None:
            vbtn = QToolButton()
            vbtn.setText(VIEW_ANNOTATIONS)
            describe(vbtn, "view")
            plain(vbtn, 12, "3px 9px")
            short_label(vbtn, "📋 View")
            vbtn.clicked.connect(view.trigger)
            ribbon.add(INSERT, vbtn)
            ce.view_annotations_btn = vbtn
    ce.scene_break_btn = _scene_button(ce, ribbon)
    ribbon.add(INSERT, ce.scene_break_btn, separate=True)

    # Draft: this chapter's 📄 Chapter ▾ (was "📄 Draft ▾" after "This
    # chapter:"; D.13b: the name says it). The manuscript's controls join
    # it in front, from ``attach``.
    _from_bottom(bottom, ce.draft_btn)
    ribbon.draft_line = _separator()
    ribbon.draft_line.setVisible(False)
    ribbon.rows[DRAFT].addWidget(ribbon.draft_line)
    ce.draft_btn.setText(CHAPTER_MENU)
    plain(ce.draft_btn, 12, "3px 9px")
    describe(ce.draft_btn, "chapter")
    ribbon.rows[DRAFT].addWidget(ce.draft_btn)

    # Every control: hover text, a name for screen readers, a focus ring.
    describe(ce.font_combo, "font")
    describe(ce.font_size_spin, "size")
    describe(ce.heading_combo, "heading")
    describe(ce.analyze_btn, "analyze")
    describe(ce.tts_speak_btn, "read")
    describe(ce.checks_btn, "checks", tip=False)
    _keep_checks_tip(ce)
    for page in (ribbon.stack.widget(n) for n in range(ribbon.stack.count())):
        for w in page.findChildren(QWidget):
            focus_ring(w)

    # The Chapter Title row: hidden, kept (the tree renames; it still saves).
    if title_row is not None:
        for n in range(title_row.count()):
            w = title_row.itemAt(n).widget()
            if w is not None:
                w.setVisible(False)
    return ribbon


_HOME_KEYS = {"B": ("bold", "bold"), "I": ("italic", "italic"), "U": ("underline", "underline"),
              "✨": ("improve", None)}


def _home_button(btn: QToolButton, act: Any) -> None:
    """B, I and U drawn bold, italic and underlined; ✨ with its word; each
    with its hover text and name."""
    key, look = _HOME_KEYS.get(act.text(), (None, None))
    if key is None:
        return
    keys = keys_of(act)
    act.setToolTip(tip_text(*TIPS[key], keys))  # the button shows its action's hover text
    describe(btn, key, keys, tip=False)
    if look:
        font = btn.font()
        getattr(font, "set" + look.capitalize())(True)
        btn.setFont(font)
    else:                                        # ✨ → ✨ Improve (no icon-only buttons)
        btn.setText(IMPROVE)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setAutoRaise(False)
        plain(btn, 12, "3px 9px")
        act.changed.connect(lambda b=btn: b.setText(IMPROVE))


def _split_button(btn: QToolButton) -> None:
    """A click-and-arrow button (Read Aloud, Annotation) in the plain look:
    the arrow in its own narrow part, inside the button's border."""
    c = PALETTE
    rule = (f"QToolButton {{ padding-right: 18px; }}"
            f" QToolButton::menu-button {{ border: none; border-left: 1px solid "
            f"{c['border_strong']}; width: 15px; }}"
            f" QToolButton::menu-button:hover {{ background: {c['surface_hover']}; }}")
    if rule not in (btn.styleSheet() or ""):
        btn.setStyleSheet((btn.styleSheet() or "") + " " + rule)


def _keep_checks_tip(ce: Any) -> None:
    """The checks button's hover text leads with its name (its code keeps
    it up to date with which checks are on)."""
    update = getattr(ce, "_update_checks_button", None)
    if update is None:
        return

    def checks_tip():
        update()
        try:
            name, what = TIPS["checks"]
            now = ce.checks_btn.toolTip()
            if not now.startswith(name + ":"):
                now = now.replace("Writing checks — ", "", 1)
                now = "All are off" if now.startswith("all off") else "On: " + now
                ce.checks_btn.setToolTip(f"{name}: {what} {now}.")
        except Exception as e:                   # never break the checks
            print(f"[write ribbon] checks hover text: {e}")
    ce._update_checks_button = checks_tip
    checks_tip()


def _from_bottom(bottom: Any, widget: QWidget) -> None:
    if bottom is not None and bottom.indexOf(widget) >= 0:
        bottom.removeWidget(widget)


# ── Scene break here (7.4's marker, at the text cursor) ────────────────

def _scene_button(ce: Any, ribbon: Ribbon) -> QToolButton:
    from src.ui import scene_marks_ui
    btn = QToolButton()
    btn.setText(scene_text(scene_marks_ui.ADD))
    plain(btn, 12, "3px 9px")
    btn.setAccessibleName(scene_marks_ui.ADD)
    btn.setToolTip(tip_text(scene_marks_ui.ADD, "Mark a new scene at the paragraph the cursor "
                            "is in. The mark is kept beside the text; your text is not changed."))
    btn.setAccessibleDescription("Mark a new scene at the paragraph the cursor is in.")
    btn.clicked.connect(lambda _=False: _toggle_scene(ce, btn))
    timer = QTimer(btn)
    timer.setSingleShot(True)
    timer.setInterval(250)
    timer.timeout.connect(lambda: sync_scene_button(ce, btn))
    ce.editor.cursorPositionChanged.connect(
        lambda: timer.start() if ribbon.current() == INSERT else None)
    ribbon.tab_shown.connect(lambda name: sync_scene_button(ce, btn) if name == INSERT else None)
    if ribbon.current() == INSERT:
        sync_scene_button(ce, btn)
    return btn


def sync_scene_button(ce: Any, btn: QToolButton) -> None:
    """"Scene break here", "Remove scene break", or greyed with the reason,
    for the paragraph the text cursor is in."""
    try:
        from src.ui import scene_marks_ui
        add, remove = scene_marks_ui.ADD, scene_marks_ui.REMOVE
        state = scene_marks_ui.at_cursor(ce)
        if state is not None and state[1]:
            _scene_says(btn, remove, True, "Remove the scene break at the paragraph the "
                        "cursor is in.")
            return
        if state is None:
            _scene_says(btn, add, False, "Put the cursor in a paragraph to mark a new "
                        "scene there.")
        elif state[0] == 0:
            _scene_says(btn, add, False, f"The {CHAPTER}'s first paragraph already starts "
                        "a scene.")
        else:
            _scene_says(btn, add, True, "Mark a new scene at the paragraph the cursor is "
                        "in. The mark is kept beside the text; your text is not changed.")
    except Exception as e:                       # never escape a slot
        print(f"[write ribbon] scene break: {e}")


def scene_text(words: str) -> str:
    """The scene button's words with its icon (D.13b)."""
    return f"{SCENE_ICON} {words}"


def _scene_says(btn: QToolButton, words: str, enabled: bool, what: str) -> None:
    btn.setText(scene_text(words))
    btn.setEnabled(enabled)
    btn.setToolTip(tip_text(words, what))
    btn.setAccessibleName(words)
    btn.setAccessibleDescription(what)


def _toggle_scene(ce: Any, btn: QToolButton) -> None:
    try:
        from src.ui import scene_marks_ui
        scene_marks_ui.toggle_at_cursor(ce)
    except Exception as e:
        print(f"[write ribbon] scene break: {e}")
    sync_scene_button(ce, btn)


# ── The manuscript's part (call lines in ``ManuscriptEditor``) ──────────

class _Keeper(QObject):
    """Takes the manuscript's widgets back before the chapter editor that
    shows them is deleted, whatever deletes it."""

    def __init__(self, me: Any):
        super().__init__(me)
        self.me = me

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.DeferredDelete and obj is getattr(self.me, "_ribbon_host", None):
            detach(self.me)
        return False


def install(manuscript_editor: Any) -> None:
    """The top row becomes ``write_header``, shown only while no chapter
    is open; its widgets join the open chapter's ribbon (``attach``)."""
    me = manuscript_editor
    try:
        outer = me.layout()
        hdr = _layout_holding(outer, me.sidebar_toggle_btn)
        at = next(n for n in range(outer.count()) if outer.itemAt(n).layout() is hdr)
        header = QWidget(me)
        header.setObjectName("writeHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(hdr.contentsMargins())
        row.setSpacing(hdr.spacing())
        draft: List[QWidget] = []
        past_stretch = False
        while hdr.count():
            item = hdr.takeAt(0)
            w = item.widget()
            if w is None:
                if item.spacerItem() is not None:
                    row.addStretch(1)
                    past_stretch = True
                continue
            row.addWidget(w)
            if past_stretch:
                draft.append(w)
        outer.takeAt(at)
        outer.insertWidget(at, header)
        me.write_header = header
        me._ribbon_draft = draft
        me._ribbon_host = None
        me._ribbon_keeper = _Keeper(me)
        me._ribbon_total_style = me.total_word_count_label.styleSheet()
        short_label(me.compare_drafts_btn, "⇅ Split")
        _name_manuscript_controls(me)

        clear = me._clear_editor                 # the chapter editor goes: take ours back

        def clear_editor():
            detach(me)
            clear()
        me._clear_editor = clear_editor
    except Exception as e:                       # the top row stays as it was
        print(f"[write ribbon] top row not moved: {e}")


def _name_manuscript_controls(me: Any) -> None:
    """D.13b: "Drafts ▾" → "📚 Manuscript ▾" (same menu, same entries);
    hover text and names for the draft controls; ◂ gets its word."""
    try:
        drafts = getattr(me, "drafts_menu_btn", None)
        if drafts is not None:
            drafts.setText(MANUSCRIPT_MENU)
            plain(drafts, 12, "3px 9px")         # one look with the ribbon's other menus
            describe(drafts, "manuscript")
        describe(me.draft_selector, "editing")
        describe(me.compare_drafts_btn, "split")
        plain(me.compare_drafts_btn, 12, "3px 9px")
        for w in me.write_header.findChildren(QLabel):
            if w.text() == "Editing:":
                w.setBuddy(me.draft_selector)    # a screen reader names the box
        for w in (drafts, me.draft_selector, me.compare_drafts_btn):
            if w is not None:
                focus_ring(w)
        _sidebar_words(me)
    except Exception as e:                       # the words stay as they were
        print(f"[write ribbon] draft controls not named: {e}")


def _sidebar_words(me: Any) -> None:
    """The sidebar's ◂ with a word beside it ("◂ Chapters"): no icon-only
    button on the ribbon. Its arrow and hover text are still the editor's."""
    btn = me.sidebar_toggle_btn
    btn.setMinimumSize(0, 0)
    btn.setMaximumSize(16777215, 16777215)
    btn.setText(SIDEBAR)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    btn.setStyleSheet(
        f"QToolButton {{ border: none; border-radius: 3px; background: transparent;"
        f" color: {PALETTE['ink_soft']}; font-size: 12px; padding: 2px 4px; }}"
        f" QToolButton:hover {{ background: {PALETTE['surface_hover']}; }}"
        f" QToolButton:focus {{ border: 2px solid {PALETTE['primary_dark']}; }}")

    def name():
        panel = getattr(me, "left_panel", None)
        shown = panel is None or not panel.isHidden()
        what = f"{'Hide' if shown else 'Show'} the {CHAPTER} list on the left."
        btn.setToolTip(tip_text(SIDEBAR, what))
        btn.setAccessibleName(SIDEBAR)
        btn.setAccessibleDescription(what)

    def after_click(_=False):
        try:
            name()
        except Exception as e:
            print(f"[write ribbon] sidebar words: {e}")
    btn.clicked.connect(after_click)             # after the editor's own toggle
    name()


def attach(manuscript_editor: Any, ce: Any) -> None:
    """The open chapter's ribbon takes the sidebar's ◂ (before the tab
    names) and the draft controls (Draft tab); its bottom row takes Total.
    The call line after a chapter editor is put in place."""
    me = manuscript_editor
    try:
        ribbon = getattr(ce, "write_ribbon", None)
        if ribbon is None or getattr(me, "write_header", None) is None:
            return
        detach(me)
        ribbon.lead.addWidget(me.sidebar_toggle_btn)
        row = ribbon.rows[DRAFT]
        for n, w in enumerate(me._ribbon_draft):
            row.insertWidget(n, w)
        ribbon.draft_line.setVisible(True)
        bottom = ce.ribbon_bottom
        total = me.total_word_count_label
        if bottom is not None:
            bottom.insertWidget(bottom.indexOf(ce.word_count_label) + 1, total)
            total.setStyleSheet(ui_kit.text_style("ink_soft", 11, extra="padding-left: 8px;"))
        me.write_header.setVisible(False)
        me._ribbon_host = ce
        ce.installEventFilter(me._ribbon_keeper)
        try:
            me._update_total_word_count()
        except Exception:
            pass
    except Exception as e:
        print(f"[write ribbon] not attached: {e}")
        detach(me)


def detach(manuscript_editor: Any) -> None:
    """Put the sidebar's ◂, Total and the draft controls back in the top
    row, shown while no chapter is open."""
    me = manuscript_editor
    ce = getattr(me, "_ribbon_host", None)
    header = getattr(me, "write_header", None)
    if header is None:
        return
    me._ribbon_host = None
    try:
        if ce is not None:
            try:
                ce.removeEventFilter(me._ribbon_keeper)
                ce.write_ribbon.draft_line.setVisible(False)
            except RuntimeError:
                pass
        row = header.layout()
        row.insertWidget(0, me.sidebar_toggle_btn)
        row.insertWidget(1, me.total_word_count_label)
        me.total_word_count_label.setStyleSheet(me._ribbon_total_style)
        for w in me._ribbon_draft:
            row.addWidget(w)
        header.setVisible(True)
    except Exception as e:
        print(f"[write ribbon] not put back: {e}")


def show_tab(manuscript_editor_or_ce: Any, name: str, remember: bool = True) -> bool:
    """Show a tab of the open chapter's ribbon (the harness, tests)."""
    obj = manuscript_editor_or_ce
    ce = getattr(obj, "current_chapter_editor", None) or obj
    ribbon = getattr(ce, "write_ribbon", None)
    if ribbon is None:
        return False
    ribbon.show_tab(name, remember=remember)
    return True
