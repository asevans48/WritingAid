"""The One Improve window (piece D.2b, designed in D.2a).

One window for help with a passage. Tabs along the top, in the order the
writer chose (decision 16): 💡 Suggestions · 📝 Critique · ✨ Rephrase (D.2c,
``improve_rephrase``) · 🔍 Expand. Each tab has its own few options at the
top; below them everything is shared:

* the **passage** strip (overly descriptive statements highlighted, the
  "your highlight was widened" note, and ▾ context: the text around it);
* one **versions** list, whichever tab made them; switching tabs hides none;
* **Your version**, editable, with ✏ edited and ↺ Reset. Edits stay with
  their version, so picking another and coming back keeps them (no
  "Discard your edit?" question);
* **Why** and ⚠ notes, and the **changes** from your text;
* the **rating** row and 🚫 Avoid a phrase…;
* **Talk it through**: a third column on a normal or wide window, a
  closed section under the preview on a narrow one;
* **Close** and **✓ Accept**, which never scroll away.

The window never builds a model: each tab (``improve_tabs``) runs the
workers its old window ran. It never writes the chapter either: after
Accept it holds ``replacement``, ``span`` and ``tool``, and the caller
applies them (``improve.apply``).

Keys: Ctrl+1 … Ctrl+4 pick a tab, Ctrl+Return accepts, Esc closes; Return
in a one-line box does that box's action and never accepts by accident.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QStackedWidget, QTabBar, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from src.ui import improve
from src.ui.ui_kit import (
    DIALOG_MARGIN, GAP, CollapsibleSection, fit_to_screen, plain, primary_button,
    relayout, remember_geometry, scrollable, size_class, text_style,
)

GEOMETRY_KEY = "improve_window"
TALK_OPEN_KEY = "improve/talk_open"

RATE_TIP = ("Ratings teach Suggestions and Rephrase your taste, and become "
            "training data (when data collection is on in Settings).")
RATINGS = (("excellent", "★ Excellent"), ("good", "Good"), ("poor", "Poor"), ("bad", "Bad"))


@dataclass(eq=False)
class Version:
    """One version of the passage, from whichever tab made it."""
    text: str
    source: str                      # the tab that made it: "suggestions", "expand", …
    kind: str = "suggestion"         # "suggestion", "revised", "expanded"
    why: str = ""
    notes: List[str] = field(default_factory=list)
    voice_fit: Optional[float] = None
    angle: str = ""
    edited: Optional[str] = None     # the writer's edit, kept with the version
    rating: str = ""
    span: Optional[tuple] = None     # what it replaces, when not the passage (Rephrase)
    data: Any = None                 # the source's own record (a RephraseOption)

    @property
    def current(self) -> str:
        return self.text if self.edited is None else self.edited


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _lines(widget: QWidget, n: float) -> int:
    """``n`` lines of ``widget``'s font, plus its frame: heights follow the
    text size, so 150% and 200% scaling hold."""
    return int(widget.fontMetrics().lineSpacing() * n) + 12


class ImproveWindow(QDialog):
    """See the module notes. ``replacement`` holds the accepted (possibly
    edited) text after Accept, ``span`` the (start, end) it replaces and
    ``tool`` the tab whose call puts it in place."""

    def __init__(self, text: str, start: int, end: int, project=None, chapter=None,
                 parent=None, *, tab: str = "suggestions", selection: tuple = None,
                 focus: str = "", suggestion_worker=None, review_worker=None,
                 more_worker=None, rephrase: Optional[dict] = None, rephrase_dialog=None):
        super().__init__(parent)
        self.text, self.start, self.end = text, start, end
        self.span = (start, end)
        self.selection = selection            # the writer's own highlight, if widened
        self.project, self.chapter = project, chapter
        self.passage = text[start:end]
        self.replacement: Optional[str] = None
        self.tool = ""
        self.versions: List[Version] = []
        self._showing: Optional[Version] = None
        self._status: Dict[str, str] = {}
        self._rate_tips: Dict[str, str] = {}
        self._filling = False
        self.setWindowTitle(f"Improve — {_short(self.passage, 40)}")
        self.setModal(True)
        self._build_ui(selection)
        from src.ui import improve_tabs
        self.tab_objects = improve_tabs.build(self, suggestion_worker=suggestion_worker,
                                              review_worker=review_worker,
                                              more_worker=more_worker, rephrase=rephrase,
                                              rephrase_dialog=rephrase_dialog)
        self._add_tabs()
        fit_to_screen(self, 1100, 780)
        remember_geometry(self, GEOMETRY_KEY, QSize(self.width(), self.height()))
        self._place_talk()
        if focus and "suggestions" in self.tab_objects:
            self.tab_objects["suggestions"].focus_edit.setText(focus)  # the Companion's fix or note
        self._keys()
        self.select_tab(tab if tab in self.tab_objects else "suggestions")

    # ── Building ─────────────────────────────────────────────────────

    def _build_ui(self, selection) -> None:
        from src.ui.passage_critique_dialog import widened_note
        outer = QVBoxLayout(self)
        outer.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        outer.setSpacing(GAP)
        content = QWidget()
        self.scroll_area = scrollable(content)
        outer.addWidget(self.scroll_area, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(GAP)
        self.content_layout = layout

        # The passage strip.
        self.passage_view = QTextEdit()
        self.passage_view.setReadOnly(True)
        self.passage_view.setPlainText(self.passage)
        self.passage_view.setToolTip("The passage you are improving. Overly descriptive "
                                     "statements are highlighted.")
        self.passage_view.setMinimumHeight(_lines(self.passage_view, 2))
        self.passage_view.setMaximumHeight(_lines(self.passage_view, 4))
        strip = QHBoxLayout()
        strip.addWidget(self.passage_view, 1)
        # ▾ context: the text around the passage (Rephrase's "Show
        # surrounding context"), for every tab.
        before, after = self.text[:self.start][-200:], self.text[self.end:][:200]
        self.context_link = QLabel("<a href='context'>▾ context</a>")
        self.context_link.setToolTip("Show the text around the passage")
        self.context_link.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.context_link.linkActivated.connect(self._toggle_context)
        self.context_link.setVisible(bool(before.strip() or after.strip()))
        strip.addWidget(self.context_link)
        layout.addLayout(strip)
        self.context_view = QTextEdit()
        self.context_view.setReadOnly(True)
        self.context_view.setPlainText((f"…{before}" if before else "") + f"\n>>> {self.passage} <<<\n"
                                       + (f"{after}…" if after else ""))
        self.context_view.setStyleSheet(text_style("ink_soft", 11))
        self.context_view.setMinimumHeight(_lines(self.context_view, 3))
        self.context_view.setMaximumHeight(_lines(self.context_view, 6))
        self.context_view.setVisible(False)
        layout.addWidget(self.context_view)
        self.expanded_label = QLabel(widened_note(self.text, self.start, self.end, selection))
        self.expanded_label.setWordWrap(True)
        self.expanded_label.setStyleSheet(text_style("ink_faint", 11))
        self.expanded_label.setVisible(bool(self.expanded_label.text()))
        layout.addWidget(self.expanded_label)

        # The tabs: each tab's own options. A tab bar over a stack (not a
        # QTabWidget, which is as tall as its tallest page), so the area
        # takes the height of the page in view.
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)
        # Only the page in view is shown, so a hidden page's height (Expand
        # needs room) never pads another.
        self.tab_pages = QWidget()
        self.tab_pages_layout = QVBoxLayout(self.tab_pages)
        self.tab_pages_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tab_pages)
        self._pages: List[QWidget] = []
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setStyleSheet(text_style("ink_soft", italic=True))
        self.status_label.linkActivated.connect(self.select_tab)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # The shared lower half: versions | your version | (talk).
        lower = QWidget()
        lower_row = QHBoxLayout(lower)
        lower_row.setContentsMargins(0, 0, 0, 0)
        lower_row.setSpacing(GAP * 2)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Versions</b>"))
        self.version_list = QListWidget()
        self.version_list.setMinimumWidth(200)
        self.version_list.setMaximumWidth(280)
        self.version_list.setMinimumHeight(_lines(self.version_list, 6))
        self.version_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.version_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.version_list.currentRowChanged.connect(self._show_version)
        left.addWidget(self.version_list, 1)
        lower_row.addLayout(left)

        right = QVBoxLayout()
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Your version</b>"))
        head.addStretch()
        self.edited_badge = QLabel("✏ edited")
        self.edited_badge.setStyleSheet(text_style("warning_ink", 11, bold=True))
        self.edited_badge.setVisible(False)
        head.addWidget(self.edited_badge)
        self.reset_btn = plain(QPushButton("↺ Reset"))
        self.reset_btn.setToolTip("Back to the version as it was made")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self._reset)
        head.addWidget(self.reset_btn)
        right.addLayout(head)
        self.preview_edit = QTextEdit()
        self.preview_edit.setPlaceholderText("Pick a version — you can edit it before you "
                                             "accept it.")
        self.preview_edit.setMinimumHeight(_lines(self.preview_edit, 4))
        self.preview_edit.textChanged.connect(self._on_edit)
        right.addWidget(self.preview_edit, 2)
        self.why_label = QLabel("")
        self.why_label.setWordWrap(True)
        self.why_label.setStyleSheet(text_style("ink_soft"))
        right.addWidget(self.why_label)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(text_style("warning_ink", 11))
        right.addWidget(self.notes_label)
        changes = QLabel("Changes from your text:")
        changes.setStyleSheet(text_style("ink_faint", 11))
        right.addWidget(changes)
        self.changes_view = QTextBrowser()
        self.changes_view.setMinimumHeight(_lines(self.changes_view, 2))
        self.changes_view.setMaximumHeight(_lines(self.changes_view, 6))
        right.addWidget(self.changes_view, 1)
        lower_row.addLayout(right, 2)

        self.talk_column = QWidget()
        self.talk_column.setMinimumWidth(260)
        self.talk_column_layout = QVBoxLayout(self.talk_column)
        self.talk_column_layout.setContentsMargins(0, 0, 0, 0)
        lower_row.addWidget(self.talk_column, 1)
        layout.addWidget(lower, 1)

        # The rating row.
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Rate:"))
        self.rate_buttons: Dict[str, QPushButton] = {}
        for value, label in RATINGS:
            btn = plain(QPushButton(label))
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setToolTip(RATE_TIP)
            btn.clicked.connect(lambda _=False, v=value: self._rate(v))
            rate_row.addWidget(btn)
            self.rate_buttons[value] = btn
        self.avoid_btn = plain(QPushButton("🚫 Avoid a phrase…"))
        self.avoid_btn.setToolTip("Select a phrase in your version you never want to see "
                                  "again. Suggestions and Rephrase will avoid it and replace "
                                  "rewrites that use it.")
        self.avoid_btn.clicked.connect(self._avoid_phrase)
        rate_row.addWidget(self.avoid_btn)
        rate_row.addStretch()
        self.rating_status = QLabel("")
        self.rating_status.setStyleSheet(text_style("ink_faint", 11))
        rate_row.addWidget(self.rating_status)
        layout.addLayout(rate_row)

        # Talk it through: one slot, the conversation of the tab you are on.
        self.talk_box = QWidget()
        talk_layout = QVBoxLayout(self.talk_box)
        talk_layout.setContentsMargins(0, 0, 0, 0)
        self.talk_intro = QLabel("<b>Talk it through</b> — ask why, give direction, or ask "
                                 "for changes; new versions go to the top of the list.")
        self.talk_intro.setWordWrap(True)
        talk_layout.addWidget(self.talk_intro)
        self.talk_stack = QStackedWidget()
        talk_layout.addWidget(self.talk_stack, 1)
        self.talk_section = CollapsibleSection("Talk it through", "talk")
        self.talk_section.set_open(self._talk_open())
        self.talk_section.toggled.connect(self._remember_talk)
        layout.addWidget(self.talk_section)

        # Close and Accept never scroll away.
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_btn = plain(QPushButton("Close"), pad="6px 14px")
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        self.accept_btn = primary_button("✓ Accept")
        self.accept_btn.setToolTip("Put your version in place of the passage (Ctrl+Return). "
                                   "Ctrl+Z in the chapter undoes it.")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self._accept)
        buttons.addWidget(self.accept_btn)
        outer.addLayout(buttons)

    def _add_tabs(self) -> None:
        self._keys_order: List[str] = []
        self.tabs.blockSignals(True)
        for key in improve.TABS:
            tab = self.tab_objects.get(key)
            if tab is None:
                continue                      # a tab not built
            index = self.tabs.addTab(tab.title)
            self.tab_pages_layout.addWidget(tab.widget)
            tab.widget.setVisible(False)
            self._pages.append(tab.widget)
            n = improve.TABS.index(key) + 1
            self.tabs.setTabToolTip(index, f"{tab.tip} (Ctrl+{n})")
            self._keys_order.append(key)
            if getattr(tab, "talk", None) is not None:
                self.talk_stack.addWidget(tab.talk)
        self.tabs.blockSignals(False)

    def _keys(self) -> None:
        for n, key in enumerate(improve.TABS, 1):
            QShortcut(QKeySequence(f"Ctrl+{n}"), self,
                      activated=lambda k=key: self.select_tab(k))
        for seq in ("Ctrl+Return", "Ctrl+Enter", "Ctrl+Shift+Return"):
            QShortcut(QKeySequence(seq), self, activated=self._accept)

    def keyPressEvent(self, event) -> None:
        # Return in a one-line box (Focus, a direction, Talk it through) does
        # that box's action; it must not also press ✓ Accept.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and not event.modifiers() & Qt.KeyboardModifier.ControlModifier \
                and isinstance(self.focusWidget(), QLineEdit):
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_context(self, _link: str = "") -> None:
        show = self.context_view.isHidden()
        self.context_view.setVisible(show)
        self.context_link.setText(f"<a href='context'>{'▴ hide context' if show else '▾ context'}</a>")

    # ── Talk it through: a column, or a section on a narrow window ──

    def _talk_open(self) -> bool:
        try:
            return str(improve._settings().value(TALK_OPEN_KEY, "false")).lower() == "true"
        except Exception:
            return False

    def _remember_talk(self, _key: str, collapsed: bool) -> None:
        try:
            s = improve._settings()
            s.setValue(TALK_OPEN_KEY, "false" if collapsed else "true")
            s.sync()
        except Exception as e:
            print(f"[improve] could not remember the section: {e}")

    def _place_talk(self) -> None:
        wide = size_class(self) != "narrow"
        target = self.talk_column_layout if wide else self.talk_section.body_layout
        if self.talk_box.parentWidget() is not (self.talk_column if wide
                                                else self.talk_section.body):
            target.addWidget(self.talk_box)
        self.talk_column.setVisible(wide)
        self.talk_section.setVisible(not wide)
        self.talk_box.setVisible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            self._place_talk()
        except Exception as e:                  # never let a resize raise
            print(f"[improve] {e}")

    # ── Tabs ─────────────────────────────────────────────────────────

    def tab_key(self) -> str:
        i = self.tabs.currentIndex()
        return self._keys_order[i] if 0 <= i < len(self._keys_order) else ""

    def select_tab(self, key: str) -> None:
        if key not in self._keys_order:
            return
        i = self._keys_order.index(key)
        if self.tabs.currentIndex() == i:
            self._on_tab_changed(i)
        else:
            self.tabs.setCurrentIndex(i)

    def set_tab_title(self, key: str, title: str) -> None:
        if key in self._keys_order:
            self.tabs.setTabText(self._keys_order.index(key), title)

    def _on_tab_changed(self, index: int) -> None:
        try:
            key = self.tab_key()
            tab = self.tab_objects.get(key)
            if tab is None:
                return
            # The tab area takes the height of the page in view, not the tallest.
            for i, page in enumerate(self._pages):
                page.setVisible(i == index)
            talk = getattr(tab, "talk", None) or getattr(
                self.tab_objects.get("suggestions"), "talk", None)
            if talk is not None:
                self.talk_stack.setCurrentWidget(talk)
            self._show_status()
            tab.start()                           # runs the first time only
            relayout(self.tab_pages)
        except Exception as e:                    # an exception escaping a slot aborts PyQt6
            print(f"[improve] could not switch tabs: {e}")

    def set_status(self, key: str, text: str) -> None:
        self._status[key] = text or ""
        self._show_status()

    def _show_status(self) -> None:
        tab = self.tab_objects.get(self.tab_key())
        key = getattr(tab, "status_key", self.tab_key())
        text = self._status.get(key, "")
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_rate_tip(self, source: str, tip: str) -> None:
        self._rate_tips[source] = tip
        if self._showing is not None:
            self._show_rating(self._showing)

    def highlight(self, flags) -> None:
        from src.ui.overdescription_panel import highlight_flags
        highlight_flags(self.passage_view, self.passage, flags)

    # ── Versions ─────────────────────────────────────────────────────

    def put_expanded(self, version: Optional[Version]) -> None:
        """Keep one "Your text, expanded" version, at the top."""
        self.versions = [v for v in self.versions if v.kind != "expanded"]
        if version is not None:
            self.versions.insert(0, version)
        self._fill(0)

    def replace_versions(self, source: str, new: List[Version]) -> None:
        """A tab's fresh run: its old versions go, the new ones come after
        "Your text, expanded"; other tabs' versions stay."""
        rest = [v for v in self.versions if v.source != source or v.kind == "expanded"]
        at = 1 if rest and rest[0].kind == "expanded" else 0
        self.versions = rest[:at] + list(new) + rest[at:]
        self._fill(0)

    def add_versions(self, new: List[Version]) -> None:
        """New versions (from Talk it through) go to the top."""
        self.versions = list(new) + self.versions
        self._fill(0)

    def label(self, v: Version) -> str:
        i = self.versions.index(v) + 1 if v in self.versions else 0
        fit = f" · voice {v.voice_fit:.0%}" if v.voice_fit is not None else ""
        flag = " ⚠" if v.notes else ""
        edited = " ✏" if v.edited is not None else ""
        if v.kind == "expanded":
            name = "Your text, expanded"
        elif v.source == "rephrase":
            name = f"Rephrase · {v.angle or 'option'}"
        else:
            name = f"Suggestion {i}" + (" · revised" if v.kind == "revised" else "")
        return f"{name}{fit}{flag}{edited}\n{_short(v.current)}"

    def _fill(self, select: int = 0) -> None:
        self._filling = True
        try:
            self.version_list.clear()
            for v in self.versions:
                item = QListWidgetItem(self.label(v))
                item.setToolTip(v.why or v.text[:300])
                self.version_list.addItem(item)
        finally:
            self._filling = False
        if self.versions:
            self.version_list.setCurrentRow(min(select, len(self.versions) - 1))
            self._show_version(self.version_list.currentRow())
        else:
            self._show_version(-1)

    def current_version(self) -> Optional[Version]:
        return self._showing

    def _show_version(self, row: int) -> None:
        if self._filling:
            return
        v = self.versions[row] if 0 <= row < len(self.versions) else None
        self._showing = None                      # no edit is recorded while loading
        self.preview_edit.setPlainText(v.current if v is not None else "")
        self._showing = v
        self._tell_tabs("shown", v)
        if v is None:
            self.why_label.setText("")
            self.notes_label.setText("")
            self.changes_view.clear()
            for btn in self.rate_buttons.values():
                btn.setEnabled(False)
                btn.setChecked(False)
            self.accept_btn.setEnabled(False)
            self._show_edited(None)
            return
        self.why_label.setText(f"<b>Why:</b> {html.escape(v.why)}" if v.why else "")
        self.notes_label.setText("⚠ This rewrite " + "; ".join(v.notes) + "." if v.notes else "")
        self._show_rating(v)
        self.rating_status.setText("")
        self._show_edited(v)
        self._update_changes()

    def _show_rating(self, v: Version) -> None:
        tip = self._rate_tips.get(v.source, RATE_TIP)
        for value, btn in self.rate_buttons.items():
            btn.setEnabled(True)
            btn.setChecked(value == v.rating)
            btn.setToolTip(tip)

    def _show_edited(self, v: Optional[Version]) -> None:
        edited = v is not None and v.edited is not None
        self.edited_badge.setVisible(edited)
        self.reset_btn.setEnabled(edited)
        self.accept_btn.setEnabled(v is not None and bool(self.preview_edit.toPlainText().strip()))

    def _on_edit(self) -> None:
        v = self._showing
        if v is not None:
            text = self.preview_edit.toPlainText()
            was = v.edited is not None
            v.edited = None if text == v.text else text
            row = self.version_list.currentRow()
            if was != (v.edited is not None) and 0 <= row < self.version_list.count():
                self.version_list.item(row).setText(self.label(v))
            self._show_edited(v)
            self._tell_tabs("edited", v, text)
        self._update_changes()

    def _tell_tabs(self, what: str, *args) -> None:
        """Tabs that keep their own state (Rephrase) hear which version is
        shown and what is typed in Your version."""
        for tab in self.tab_objects.values():
            hook = getattr(tab, what, None)
            if hook is not None:
                try:
                    hook(*args)
                except Exception as e:            # never let a tab break the window
                    print(f"[improve] {e}")

    def original_for(self, v: Optional[Version]) -> str:
        """The text a version replaces: the passage, or (Rephrase) your
        exact highlight."""
        if v is not None and v.span:
            return self.text[v.span[0]:v.span[1]]
        return self.passage

    def _update_changes(self) -> None:
        from src.ai.rewrite_quality import diff_html
        text = self.preview_edit.toPlainText()
        base = self.original_for(self._showing)
        self.changes_view.setHtml(diff_html(base, text) if text.strip() else "")

    def _reset(self) -> None:
        v = self._showing
        if v is not None:
            v.edited = None
            self.preview_edit.setPlainText(v.text)

    # ── Rating, avoiding, accepting ──────────────────────────────────

    def _tab_for(self, v: Version):
        return self.tab_objects.get(v.source)

    def _rate(self, value: str) -> None:
        v = self._showing
        if v is None:
            return
        v.rating = value
        for name, btn in self.rate_buttons.items():
            btn.setChecked(name == value)
        try:
            message = self._tab_for(v).rate(v, value, self.preview_edit.toPlainText().strip())
        except Exception as e:                    # a rating never breaks the window
            message = f"Couldn't save: {e}"
        self.rating_status.setText(message)

    def _avoid_phrase(self, _checked: bool = False, phrase: Optional[str] = None) -> None:
        from src.ui.passage_critique_dialog import avoid_phrase
        message = avoid_phrase(self, self.preview_edit, phrase)
        if message is not None:
            self.rating_status.setText(message)

    def _accept(self) -> None:
        v = self._showing
        text = self.preview_edit.toPlainText().strip()
        if v is None or not text or not self.accept_btn.isEnabled():
            return
        tab = self._tab_for(v)
        try:
            self.tool = tab.accept(v, text) if tab is not None else v.source
        except Exception as e:                    # a rating row never blocks the text
            print(f"[improve] could not record the accept: {e}")
            self.tool = v.source
        self.span = tuple(v.span) if v.span else (self.start, self.end)
        self.replacement = text
        self.accept()

    def done(self, code: int) -> None:
        # Workers still running keep running (background keeps them alive);
        # their results are dropped.
        for tab in self.tab_objects.values():
            try:
                tab.stop()
            except Exception as e:
                print(f"[improve] {e}")
        super().done(code)
