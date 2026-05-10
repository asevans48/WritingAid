"""Per-chapter outline panel for the AI Assistant sidebar.

Lives inside the right-hand sidebar's Chapter Outline tab. Edits
sync back to ``chapter.planning.outline`` so the outline travels
with the project — the chapter writer mirrors it into
``chapter.plan`` + ``chapters/chapter_NNN/plan.md`` so the outline
also lands as a per-chapter file alongside the prose revisions.

The panel has two modes:

  * **Checklist** (default) — beats parsed from ``## ``-level
    headings render as cards with checkboxes. Checking a beat
    rewrites its heading line in the markdown source from
    ``## [ ] Beat 1: …`` ↔ ``## [x] Beat 1: …`` so completion
    state lives in the source-of-truth markdown.
  * **Edit** — raw markdown editing. Toggle back to Checklist to
    re-parse and re-render with current completion state.

Beat-heading grammar (a single line):
    ``## [<marker>] <title>``  where ``<marker>`` is " " (open) or
    "x"/"X" (done). The marker is optional on read — headings
    without a marker default to open and gain ``[ ]`` only when
    the user toggles something (we never rewrite on pure render).

Writer-mode OUTLINE output is routed here instead of being inserted
into the chapter prose — see :meth:`set_outline_text`.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import re

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QFocusEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class _ClickToEditLineEdit(QLineEdit):
    """QLineEdit that reads as a label until double-clicked.

    Default state is ``readOnly=True`` so a single click does
    nothing visible (the user can't accidentally start editing).
    A double-click unlocks editing, selects all text, and grabs
    focus. Pressing Enter or losing focus returns to read-only.
    The standard ``textChanged`` signal still fires while the
    user types in unlocked mode, so existing wiring keeps working.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setReadOnly(True)
        # When done editing (Enter), drop back to read-only.
        self.editingFinished.connect(self._exit_edit_mode)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.isReadOnly():
            self.setReadOnly(False)
            self.selectAll()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self._exit_edit_mode()

    def _exit_edit_mode(self) -> None:
        if not self.isReadOnly():
            self.setReadOnly(True)
            # Drop any selection so the value reads cleanly.
            self.deselect()


class _ClickToEditTextEdit(QTextEdit):
    """QTextEdit that reads as rendered text until double-clicked.

    Same edit-mode-on-double-click pattern as
    :class:`_ClickToEditLineEdit`. The ``textChanged`` signal
    continues to fire while the user types in unlocked mode.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)  # paste as plain text

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.isReadOnly():
            self.setReadOnly(False)
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            # Defer to the default handler so the double-click also
            # selects the word under the cursor — gives a quick
            # "type to replace" affordance.
            super().mouseDoubleClickEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        if not self.isReadOnly():
            self.setReadOnly(True)
            # Clear the selection so the rendered view reads cleanly.
            cursor = self.textCursor()
            cursor.clearSelection()
            self.setTextCursor(cursor)


# Beat heading: optional task-list marker + title.
#   ## Beat 1: arrival
#   ## [ ] Beat 1: arrival
#   ## [x] Beat 1: arrival
_BEAT_HEADING_RE = re.compile(
    r"^##\s+(?:\[(?P<marker>[ xX])\]\s+)?(?P<title>.+?)\s*$")


@dataclass
class _Beat:
    checked: bool
    title: str
    body_lines: List[str] = field(default_factory=list)


def _parse_beats(markdown: str) -> Tuple[str, List[_Beat]]:
    """Split ``markdown`` into (preamble_text, [beat, ...]).

    Lines before the first ``## `` heading are the preamble.
    Each beat owns its heading + every subsequent line up to the
    next ``## `` heading.
    """
    preamble: List[str] = []
    beats: List[_Beat] = []
    current: Optional[_Beat] = None
    for line in (markdown or "").splitlines():
        m = _BEAT_HEADING_RE.match(line)
        if m:
            if current is not None:
                beats.append(current)
            checked = (m.group("marker") or "").lower() == "x"
            current = _Beat(
                checked=checked,
                title=m.group("title").strip(),
            )
        elif current is None:
            preamble.append(line)
        else:
            current.body_lines.append(line)
    if current is not None:
        beats.append(current)
    return ("\n".join(preamble).strip("\n"), beats)


def _serialize_beats(preamble: str, beats: List[_Beat]) -> str:
    """Inverse of _parse_beats. Always writes [x]/[ ] markers."""
    parts: List[str] = []
    if preamble.strip():
        parts.append(preamble.rstrip("\n"))
    for b in beats:
        marker = "[x]" if b.checked else "[ ]"
        parts.append(f"## {marker} {b.title}")
        # Trim trailing blank lines on each body so adjacent beat
        # headings don't accumulate extra spacing on every save.
        body = "\n".join(b.body_lines).rstrip("\n")
        if body:
            parts.append(body)
    text = "\n\n".join(p for p in parts if p)
    return text + ("\n" if text and not text.endswith("\n") else "")


class _BeatCard(QFrame):
    """One beat row.

    Layout: [✓] [▾] <title-input> [↑][↓][×][✨]
            <rendered body markdown (read-only)>

    The title is INLINE-EDITABLE (no markdown syntax to learn).
    The body remains rendered-markdown read-only — users edit body
    bullets via the Source toggle. Action buttons emit signals
    that the parent OutlinePanel uses to mutate ``_beats`` and
    rebuild ``_source``.
    """

    toggled = pyqtSignal(int, bool)             # (idx, new_checked)
    title_edited = pyqtSignal(int, str)          # (idx, new_title)
    body_edited = pyqtSignal(int, str)           # (idx, new_body_md)
    move_requested = pyqtSignal(int, int)        # (idx, direction +1/-1)
    remove_requested = pyqtSignal(int)           # (idx)
    ai_help_requested = pyqtSignal(int)          # (idx)

    def __init__(self, index: int, beat: _Beat,
                 total: int = 1,
                 expanded: bool = True,
                 parent=None) -> None:
        # ``parent`` MUST be the eventual container — without it the
        # card is a transient top-level widget on macOS, which (when
        # the host app is in fullscreen) triggers a Spaces switch
        # and drops the writer window behind the launcher.
        super().__init__(parent)
        self._index = index
        self._total = total
        self._checked = beat.checked
        self._expanded = expanded
        self._suppress_title_signal = False
        self.setObjectName("beatCard")
        self._apply_card_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(4)
        # Every child widget below passes ``self`` (the card) as
        # parent at construction. Without that, each widget is a
        # transient top-level until its layout is added to the
        # card's QVBoxLayout — and macOS treats every transient
        # top-level as a new desktop window, which triggers a
        # Spaces switch when the writer is in fullscreen.
        self.checkbox = QCheckBox(self)
        self.checkbox.setChecked(beat.checked)
        self.checkbox.setToolTip(
            "Mark this beat done. The check shows in the saved "
            "markdown as [x].")
        self.checkbox.toggled.connect(self._on_toggled)
        top.addWidget(
            self.checkbox, 0, Qt.AlignmentFlag.AlignTop)

        # Chevron toggle — expand/collapse the rendered body.
        # Tooltip is set unconditionally on init (was previously
        # only applied when a body existed, leaving an empty
        # tooltip on re-creates).
        self.expand_btn = QPushButton("▾", self)
        self.expand_btn.setFlat(True)
        self.expand_btn.setToolTip(
            "Hide the beat's details (you can show them again "
            "with the same arrow).")
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            " color: #6b7280; font-size: 11px; "
            " padding: 0 4px; min-width: 16px; } "
            "QPushButton:hover { color: #4f46e5; }")
        self.expand_btn.clicked.connect(self._toggle_expanded)
        top.addWidget(
            self.expand_btn, 0, Qt.AlignmentFlag.AlignTop)

        # Title — read-only label by default; double-click to edit.
        # We strip the ``Beat N:`` prefix when populating so users
        # edit just the title text; the prefix is reapplied at
        # serialization. Edits propagate to chapter.planning.events
        # via the existing outline_changed → sync chain.
        display_title = self._strip_beat_prefix(
            beat.title or "")
        self.title_input = _ClickToEditLineEdit(display_title, self)
        self.title_input.setPlaceholderText(
            f"Beat {index + 1} title…")
        self.title_input.setToolTip(
            "Double-click to rename. Renaming a beat renames the "
            "matching event in the chapter plot arc too (the event "
            "id is preserved).")
        self._apply_title_style()
        # Edit signal fires on every keystroke; OutlinePanel
        # debounces the source rebuild.
        self.title_input.textChanged.connect(self._on_title_edited)
        top.addWidget(self.title_input, stretch=1)

        # Action buttons — ↑ ↓ × ✨
        action_btn_style = (
            "QPushButton { background: transparent; border: none; "
            " color: #6b7280; font-size: 12px; "
            " padding: 0 4px; min-width: 18px; } "
            "QPushButton:hover { color: #4f46e5; "
            "  background: #eef2ff; border-radius: 3px; } "
            "QPushButton:disabled { color: #d1d5db; }")
        self.up_btn = QPushButton("↑", self)
        self.up_btn.setStyleSheet(action_btn_style)
        self.up_btn.setToolTip(
            "Move this beat up one slot. The chapter plot arc "
            "reorders to match.")
        self.up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.up_btn.setEnabled(index > 0)
        self.up_btn.clicked.connect(
            lambda: self.move_requested.emit(self._index, -1))
        top.addWidget(self.up_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.down_btn = QPushButton("↓", self)
        self.down_btn.setStyleSheet(action_btn_style)
        self.down_btn.setToolTip(
            "Move this beat down one slot. The chapter plot arc "
            "reorders to match.")
        self.down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.down_btn.setEnabled(index < total - 1)
        self.down_btn.clicked.connect(
            lambda: self.move_requested.emit(self._index, +1))
        top.addWidget(self.down_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.delete_btn = QPushButton("×", self)
        self.delete_btn.setStyleSheet(
            action_btn_style.replace(
                "color: #6b7280;", "color: #b91c1c;"))
        self.delete_btn.setToolTip(
            "Remove this beat. The matching event is also removed "
            "from the chapter plot arc.")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._index))
        top.addWidget(self.delete_btn, 0,
                       Qt.AlignmentFlag.AlignTop)

        self.ai_btn = QPushButton("✨", self)
        self.ai_btn.setStyleSheet(action_btn_style)
        self.ai_btn.setToolTip(
            "Ask the AI Assistant to help develop this beat — "
            "opens outline mode focused on it.")
        self.ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_btn.clicked.connect(
            lambda: self.ai_help_requested.emit(self._index))
        top.addWidget(self.ai_btn, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(top)

        # Body — rendered markdown by default; double-click to edit.
        # We round-trip through Qt's setMarkdown / toMarkdown so the
        # user types prose, not markdown syntax. Created even when
        # there's no body so the user can double-click to start
        # typing; we show a placeholder hint and keep the widget
        # short until they type.
        body_md = "\n".join(beat.body_lines).strip()
        self._suppress_body_signal = False
        self.body = _ClickToEditTextEdit(self)
        self.body.setFrameShape(QFrame.Shape.StyledPanel)
        self.body.setToolTip(
            "Double-click to edit. The structured bullet sections "
            "(WHAT HAPPENS, WHO'S IN IT, etc.) are rendered from "
            "markdown — type freely; bold/lists are kept.")
        self.body.setStyleSheet(
            "QTextEdit { background: rgba(254, 252, 232, 0.5); "
            " border: 1px dashed transparent; "
            " border-radius: 4px; "
            " padding: 4px 6px; "
            " color: #374151; font-size: 12px; } "
            "QTextEdit:hover { border-color: #fde68a; } "
            "QTextEdit:focus { border-color: #f59e0b; "
            "  background: white; }")
        if body_md:
            self._suppress_body_signal = True
            try:
                self.body.setMarkdown(body_md)
            finally:
                self._suppress_body_signal = False
        else:
            # Empty body — show a placeholder so the user knows
            # they can click in to add detail.
            self.body.setPlaceholderText(
                "Click to add details — what happens, who's in "
                "it, where, sensory hooks…")
        doc = self.body.document()
        doc.setTextWidth(360)
        content_h = int(doc.size().height()) + 8
        self.body.setFixedHeight(min(max(content_h, 60), 280))
        self.body.setVisible(self._expanded)
        # Wire up edits — debounced source rebuild via parent.
        self.body.textChanged.connect(self._on_body_edited)
        layout.addWidget(self.body)
        self.expand_btn.setText("▾" if self._expanded else "▸")
        self.expand_btn.setToolTip(
            "Hide the beat's details (you can show them again "
            "with the same arrow)."
            if self._expanded
            else "Show the beat's details (collapsed for "
                 "compact view).")

    @staticmethod
    def _strip_beat_prefix(title: str) -> str:
        """Drop a leading ``Beat N: `` so the input shows just the title."""
        import re as _re
        m = _re.match(
            r"^\s*Beat\s+\d+\s*[:\-—]\s*(.*)$", title or "",
            _re.IGNORECASE)
        return (m.group(1).strip() if m else (title or "").strip())

    def _on_title_edited(self, text: str) -> None:
        if self._suppress_title_signal:
            return
        self.title_edited.emit(self._index, text)

    def _on_body_edited(self) -> None:
        """User typed in the body — capture as markdown + bubble up."""
        if self._suppress_body_signal:
            return
        # Qt's toMarkdown is the inverse of setMarkdown — preserves
        # bold sections + bullets reasonably for our skeleton. The
        # parent OutlinePanel debounces the source rebuild.
        try:
            md = self.body.toMarkdown()
        except Exception:
            md = self.body.toPlainText()
        self.body_edited.emit(self._index, md)

    def _apply_card_style(self) -> None:
        if self._checked:
            self.setStyleSheet(
                "QFrame#beatCard { background-color: #ecfdf5; "
                " border: 1px solid #a7f3d0; border-radius: 6px; }")
        else:
            self.setStyleSheet(
                "QFrame#beatCard { background-color: #ffffff; "
                " border: 1px solid #fde68a; border-radius: 6px; }")

    def _apply_title_style(self) -> None:
        # Style the QLineEdit so it reads like inline editable text
        # (no boxy form-input look) but still shows a hover cue +
        # focus border so the user knows it's editable.
        if self._checked:
            self.title_input.setStyleSheet(
                "QLineEdit { font-size: 13px; font-weight: 600; "
                " color: #6b7280; background: transparent; "
                " border: 1px solid transparent; padding: 2px 4px; "
                " border-radius: 3px; } "
                "QLineEdit:hover { border-color: #fde68a; "
                " background: rgba(254, 243, 199, 0.4); } "
                "QLineEdit:focus { border-color: #f59e0b; "
                " background: white; }")
        else:
            self.title_input.setStyleSheet(
                "QLineEdit { font-size: 13px; font-weight: 600; "
                " color: #111827; background: transparent; "
                " border: 1px solid transparent; padding: 2px 4px; "
                " border-radius: 3px; } "
                "QLineEdit:hover { border-color: #fde68a; "
                " background: rgba(254, 243, 199, 0.4); } "
                "QLineEdit:focus { border-color: #f59e0b; "
                " background: white; }")

    def _on_toggled(self, checked: bool) -> None:
        self._checked = checked
        self._apply_card_style()
        self._apply_title_style()
        self.toggled.emit(self._index, checked)

    def _toggle_expanded(self) -> None:
        if self.body is None:
            return
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.expand_btn.setText("▾" if self._expanded else "▸")
        self.expand_btn.setToolTip(
            "Hide beat details" if self._expanded
            else "Show beat details")

    def is_expanded(self) -> bool:
        return self._expanded


class OutlinePanel(QWidget):
    """Beat-by-beat outline checklist bound to a chapter."""

    outline_changed = pyqtSignal(str)
    # Per-beat AI help — ferried up from a card's ✨ button so
    # MainWindow can route into the outline chat.
    # (beat_title, beat_body_md, beat_stage)
    beat_ai_help_requested = pyqtSignal(str, str, str)

    _AUTOSAVE_DEBOUNCE_MS = 600
    _PLACEHOLDER_NO_CHAPTER = (
        "Open a chapter to view or write its outline.\n\n"
        "When you're in Writer mode and ask for an outline, it lands "
        "here instead of being inserted into the chapter prose.")
    _PLACEHOLDER_EMPTY = (
        "No outline yet for this chapter.\n\n"
        "Switch the AI Assistant to Writer mode + Output: Outline, "
        "and ask for an outline — beats will render as a checklist "
        "here.")

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("outlinePanel")
        # Suppress autosave when WE are mutating widgets (chapter
        # switch / AI write / mode toggle / checkbox-driven rewrite).
        self._suppress_autosave = False
        self._current_chapter_title: Optional[str] = None
        self._current_chapter_id: Optional[str] = None
        # Canonical markdown source — checklist + edit views are both
        # derived from this. Edit mode mirrors edits back into _source
        # via _on_edit_text_changed.
        self._source: str = ""
        # Default to Checklist view.
        self._checklist_mode: bool = True
        # Holds the parsed beats currently shown so checkbox toggles
        # can rewrite the right line. Re-populated on every render.
        self._beats: List[_Beat] = []
        self._preamble: str = ""

        self._init_ui()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._emit_outline_changed)

    # ── UI setup ──────────────────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.header_frame = QFrame()
        self.header_frame.setStyleSheet(
            "QFrame { background-color: #4f46e5; border-radius: 6px; }")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)

        title_label = QLabel("📋  Chapter Outline")
        title_label.setStyleSheet(
            "QLabel { background-color: transparent; color: white; "
            " font-size: 12px; font-weight: 600; padding: 2px; }")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.chapter_label = QLabel("(no chapter)")
        self.chapter_label.setStyleSheet(
            "color: rgba(255, 255, 255, 0.85); font-size: 11px;")
        header_layout.addWidget(self.chapter_label)

        # Mode toggle — flips between Checklist (rendered + per-beat
        # editing via inline title field + add/move/remove buttons)
        # and Source (raw markdown for power users).
        self.mode_btn = QPushButton("📝 Source")
        self.mode_btn.setToolTip(
            "Switch to raw-markdown source view.")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.15); "
            " color: white; border: 1px solid rgba(255,255,255,0.3); "
            " border-radius: 4px; padding: 2px 8px; font-size: 11px; "
            " font-weight: 500; } "
            "QPushButton:hover { background-color: "
            " rgba(255,255,255,0.25); }")
        self.mode_btn.clicked.connect(self._toggle_mode)
        header_layout.addWidget(self.mode_btn)

        layout.addWidget(self.header_frame)

        # Stack: page 0 = checklist (scroll area), page 1 = raw edit.
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        # Checklist page — scroll area wrapping a vertical list of
        # _BeatCard widgets (plus a preamble label when present).
        # Always show the vertical scrollbar so the user can see
        # there's more content below the visible area; horizontal
        # scroll never shows (cards wrap text instead).
        self._checklist_scroll = QScrollArea()
        self._checklist_scroll.setWidgetResizable(True)
        self._checklist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._checklist_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._checklist_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._checklist_scroll.setStyleSheet(
            "QScrollArea { background-color: #fefce8; "
            " border: 1px solid #fde68a; border-radius: 6px; } "
            "QScrollBar:vertical { background: #fef3c7; "
            " width: 10px; border-radius: 5px; margin: 4px 2px; } "
            "QScrollBar::handle:vertical { background: #fbbf24; "
            " border-radius: 5px; min-height: 24px; } "
            "QScrollBar::handle:vertical:hover { "
            " background: #f59e0b; } "
            "QScrollBar::add-line:vertical, "
            "QScrollBar::sub-line:vertical { height: 0; } "
            "QScrollBar::add-page:vertical, "
            "QScrollBar::sub-page:vertical { background: transparent; }")
        self._checklist_container = QWidget()
        self._checklist_container.setStyleSheet(
            "background: transparent;")
        self._checklist_layout = QVBoxLayout(self._checklist_container)
        self._checklist_layout.setContentsMargins(8, 8, 8, 8)
        self._checklist_layout.setSpacing(8)
        self._checklist_layout.addStretch()
        self._checklist_scroll.setWidget(self._checklist_container)
        self._stack.addWidget(self._checklist_scroll)

        # Raw-edit page — QTextEdit that holds the markdown source.
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(self._PLACEHOLDER_NO_CHAPTER)
        self.editor.setStyleSheet(
            "QTextEdit { background-color: #fefce8; "
            " border: 1px solid #fde68a; border-radius: 6px; "
            " padding: 8px; font-family: 'SF Mono', Menlo, "
            " Consolas, monospace; font-size: 12px; "
            " line-height: 1.45; } "
            "QTextEdit:focus { border-color: #f59e0b; }")
        self.editor.textChanged.connect(self._on_edit_text_changed)
        self._stack.addWidget(self.editor)

        # Start in checklist mode.
        self._stack.setCurrentIndex(0)
        self.setEnabled(False)  # disabled until a chapter loads

    # ── public API ────────────────────────────────────────────────

    def load_chapter(self,
                     chapter_id: Optional[str],
                     chapter_title: Optional[str],
                     outline_text: Optional[str]) -> None:
        """Bind the panel to a chapter and load its outline."""
        # Flush any pending autosave for the previous chapter BEFORE
        # we swap state — otherwise we'd write the new outline back
        # under the new chapter's id and shred the old chapter's
        # outline.
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._emit_outline_changed()

        self._current_chapter_id = chapter_id
        self._current_chapter_title = chapter_title
        self._source = outline_text or ""

        if chapter_id is None:
            self.chapter_label.setText("(no chapter)")
            self.setEnabled(False)
            self.editor.setPlaceholderText(self._PLACEHOLDER_NO_CHAPTER)
            self._render()
            return

        label = (chapter_title or "(untitled)").strip()
        if len(label) > 40:
            label = label[:37] + "…"
        self.chapter_label.setText(label)
        self.setEnabled(True)
        self.editor.setPlaceholderText(self._PLACEHOLDER_EMPTY)
        self._render()

    def set_outline_text(self, text: str) -> None:
        """Programmatically replace the outline (e.g. AI write)."""
        self._source = text or ""
        self._render()
        self._emit_outline_changed()

    def append_outline_text(self, text: str) -> None:
        """Append text to the outline (e.g. AI Edit-mode refinement)."""
        if not text:
            return
        existing = self.get_outline_text()
        merged = (existing.rstrip() + "\n\n" + text.strip()
                  if existing.strip() else text.strip())
        self._source = merged
        self._render()
        self._emit_outline_changed()

    def get_outline_text(self) -> str:
        """Return the canonical markdown source.

        In Edit mode, captures any pending user edits from the
        editor first so callers always see the freshest text.
        """
        if not self._checklist_mode:
            self._source = self.editor.toPlainText()
        return self._source

    def has_content(self) -> bool:
        return bool(self.get_outline_text().strip())

    def current_chapter_id(self) -> Optional[str]:
        return self._current_chapter_id

    def current_chapter_title(self) -> Optional[str]:
        return self._current_chapter_title

    def is_checklist_mode(self) -> bool:
        return self._checklist_mode

    def set_checklist_mode(self, checklist: bool) -> None:
        if checklist == self._checklist_mode:
            return
        self._toggle_mode()

    # Public for tests — exposes the parsed beat list of the
    # currently-rendered checklist (read-only snapshot).
    def beats(self) -> List[Tuple[bool, str]]:
        return [(b.checked, b.title) for b in self._beats]

    # ── render path ───────────────────────────────────────────────

    def _render(self) -> None:
        """Push self._source into the active view."""
        self._suppress_autosave = True
        try:
            if self._checklist_mode:
                self._render_checklist()
                self._stack.setCurrentIndex(0)
            else:
                self.editor.setPlainText(self._source or "")
                self._stack.setCurrentIndex(1)
        finally:
            self._suppress_autosave = False

    def _render_checklist(self) -> None:
        """Re-parse the source + rebuild the beat-card list."""
        # Parse first so _beats / _preamble are current before we
        # repopulate the layout — checkbox callbacks consult them.
        self._preamble, self._beats = _parse_beats(self._source)

        # Tear down existing beat-card widgets (preserve the
        # trailing stretch).
        layout = self._checklist_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # Preamble line — only when there's text BEFORE the first
        # beat. AI outputs typically start with `[OUTLINE — REMAINING
        # BEATS]` then the first `## Beat 1: …` heading.
        # Pass the scroll container as parent at construction (see
        # _BeatCard.__init__ for the macOS-fullscreen Spaces-switch
        # rationale).
        if self._preamble.strip():
            preamble_view = QTextEdit(self._checklist_container)
            preamble_view.setReadOnly(True)
            preamble_view.setFrameShape(QFrame.Shape.NoFrame)
            preamble_view.setStyleSheet(
                "QTextEdit { background: transparent; "
                " border: none; color: #6b7280; "
                " font-size: 11px; padding: 0; }")
            preamble_view.setMarkdown(self._preamble)
            doc = preamble_view.document()
            doc.setTextWidth(360)
            h = int(doc.size().height()) + 8
            preamble_view.setFixedHeight(min(max(h, 24), 120))
            layout.insertWidget(0, preamble_view)
            insert_at = 1
        else:
            insert_at = 0

        if not self._beats:
            empty = QLabel(
                self._PLACEHOLDER_EMPTY, self._checklist_container)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                "QLabel { color: #9ca3af; font-size: 12px; "
                " padding: 12px; }")
            layout.insertWidget(insert_at, empty)
        else:
            total = len(self._beats)
            for i, beat in enumerate(self._beats):
                card = _BeatCard(
                    i, beat, total=total,
                    parent=self._checklist_container)
                card.toggled.connect(self._on_beat_toggled)
                card.title_edited.connect(self._on_beat_title_edited)
                card.body_edited.connect(self._on_beat_body_edited)
                card.move_requested.connect(self._on_beat_move_requested)
                card.remove_requested.connect(
                    self._on_beat_remove_requested)
                card.ai_help_requested.connect(
                    self._on_beat_ai_help_requested)
                layout.insertWidget(insert_at + i, card)
            insert_at += total

        # "+ Add Beat" button at the bottom — always visible so the
        # user can grow the outline without diving into source mode.
        add_btn = QPushButton("+ Add Beat", self._checklist_container)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            "QPushButton { background: #fef3c7; "
            " border: 1px dashed #fbbf24; border-radius: 6px; "
            " color: #92400e; font-size: 12px; "
            " font-weight: 500; padding: 8px; } "
            "QPushButton:hover { background: #fde68a; "
            " border-color: #d97706; color: #78350f; }")
        add_btn.clicked.connect(self._on_beat_add_requested)
        layout.insertWidget(insert_at, add_btn)

    # ── event handlers ────────────────────────────────────────────

    def _on_edit_text_changed(self) -> None:
        if self._suppress_autosave:
            return
        if self._checklist_mode:
            return
        # User editing raw markdown — capture into source + debounce
        # the autosave.
        self._source = self.editor.toPlainText()
        self._autosave_timer.start(self._AUTOSAVE_DEBOUNCE_MS)

    def _on_beat_toggled(self, index: int, checked: bool) -> None:
        if self._suppress_autosave:
            return
        if not (0 <= index < len(self._beats)):
            return
        self._beats[index].checked = checked
        # Rewrite the canonical source. Serialization always emits
        # [x]/[ ] markers — beats that previously had no marker gain
        # one on this save. That's intentional: the user just took an
        # action that justifies normalizing the file.
        self._source = _serialize_beats(self._preamble, self._beats)
        # Persist immediately — checkbox state changes feel like a
        # commit, not a draft, so don't debounce.
        self._emit_outline_changed()

    def _on_beat_title_edited(self,
                                index: int, new_title: str) -> None:
        """Inline title edit — rebuild source + debounced save."""
        if self._suppress_autosave:
            return
        if not (0 <= index < len(self._beats)):
            return
        # Renumber the title back into "Beat N: <title>" form. The
        # serializer doesn't add the prefix; titles are stored
        # verbatim in _Beat.title and the prefix is part of that
        # title (the parser keeps it).
        bare = (new_title or "").strip()
        self._beats[index].title = (
            f"Beat {index + 1}: {bare}" if bare
            else f"Beat {index + 1}")
        self._source = _serialize_beats(
            self._preamble, self._beats)
        # Title-edit is a typing event — debounce so we don't
        # autosave on every keystroke.
        self._autosave_timer.start(self._AUTOSAVE_DEBOUNCE_MS)

    def _on_beat_body_edited(self,
                               index: int, new_body_md: str) -> None:
        """Inline body edit — rebuild source + debounced save.

        The body comes back as a markdown string from Qt's
        ``toMarkdown``. We split into lines so the serializer can
        rejoin them under the beat heading. Reconciliation with
        ``chapter.planning.events`` happens via the existing
        ``outline_changed`` signal listener in main_window.
        """
        if self._suppress_autosave:
            return
        if not (0 <= index < len(self._beats)):
            return
        # Strip trailing whitespace lines from the toMarkdown output
        # so the source doesn't accumulate blank lines on every
        # keystroke.
        body_lines = (new_body_md or "").rstrip().split("\n")
        self._beats[index].body_lines = body_lines
        self._source = _serialize_beats(
            self._preamble, self._beats)
        self._autosave_timer.start(self._AUTOSAVE_DEBOUNCE_MS)

    def _on_beat_move_requested(self,
                                  index: int, direction: int) -> None:
        """Swap the beat with its neighbour + re-render."""
        if not (0 <= index < len(self._beats)):
            return
        target = index + direction
        if not (0 <= target < len(self._beats)):
            return
        beats = self._beats
        beats[index], beats[target] = beats[target], beats[index]
        # Renumber titles to match new positions ("Beat N: title").
        self._renumber_beat_titles()
        self._source = _serialize_beats(
            self._preamble, self._beats)
        # Re-render so the cards land in the new order.
        self._render_checklist()
        self._emit_outline_changed()

    def _on_beat_remove_requested(self, index: int) -> None:
        """Remove the beat + renumber + re-render."""
        if not (0 <= index < len(self._beats)):
            return
        del self._beats[index]
        self._renumber_beat_titles()
        self._source = _serialize_beats(
            self._preamble, self._beats)
        self._render_checklist()
        self._emit_outline_changed()

    def _on_beat_add_requested(self) -> None:
        """Append a new empty beat at the end + re-render."""
        new_index = len(self._beats) + 1
        self._beats.append(_Beat(
            checked=False,
            title=f"Beat {new_index}: ",
            body_lines=[],
        ))
        self._source = _serialize_beats(
            self._preamble, self._beats)
        self._render_checklist()
        self._emit_outline_changed()

    def _on_beat_ai_help_requested(self, index: int) -> None:
        """Bubble per-beat AI help up to MainWindow."""
        if not (0 <= index < len(self._beats)):
            return
        beat = self._beats[index]
        body = "\n".join(beat.body_lines).strip()
        # Strip "Beat N:" prefix for a cleaner title.
        bare_title = _BeatCard._strip_beat_prefix(beat.title)
        self.beat_ai_help_requested.emit(
            bare_title, body, "")

    def _renumber_beat_titles(self) -> None:
        """Rewrite each beat title's ``Beat N`` prefix to match index."""
        import re as _re
        for i, beat in enumerate(self._beats):
            bare = _re.sub(
                r"^\s*Beat\s+\d+\s*[:\-—]\s*", "",
                beat.title or "", flags=_re.IGNORECASE).strip()
            beat.title = (
                f"Beat {i + 1}: {bare}" if bare
                else f"Beat {i + 1}")

    def _emit_outline_changed(self) -> None:
        if self._current_chapter_id is None:
            return
        if not self._checklist_mode:
            self._source = self.editor.toPlainText()
        self.outline_changed.emit(self._source)

    def _toggle_mode(self) -> None:
        if self._checklist_mode:
            # Checklist → Source view (raw markdown for advanced edits).
            self._checklist_mode = False
            self.mode_btn.setText("☑ Checklist")
            self.mode_btn.setToolTip(
                "Switch back to the beat-by-beat checklist view.")
            self._render()
            # Focus the source editor so the user can type
            # immediately. Deferred to the next event-loop tick
            # because calling setFocus in the middle of a stack
            # switch on macOS can race with the Cocoa focus chain
            # and (when in fullscreen) trigger a Spaces switch.
            QTimer.singleShot(
                0,
                lambda: self.editor.setFocus(
                    Qt.FocusReason.OtherFocusReason))
        else:
            # Source → Checklist: capture pending source edits before
            # parsing back into beats.
            self._source = self.editor.toPlainText()
            self._checklist_mode = True
            self.mode_btn.setText("📝 Source")
            self.mode_btn.setToolTip(
                "Switch to raw-markdown source view.")
            self._render()
            # Focus the scroll area so wheel scroll works without
            # a second click into the panel. Deferred for the same
            # macOS-fullscreen reason as the source-mode branch.
            QTimer.singleShot(
                0,
                lambda: self._checklist_scroll.setFocus(
                    Qt.FocusReason.OtherFocusReason))
            # If the user actually edited the source while in Edit
            # mode, persist now so leaving Edit mode is a commit
            # boundary. The autosave debounce may not have fired yet.
            self._emit_outline_changed()
