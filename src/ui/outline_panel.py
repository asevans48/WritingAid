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
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


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
    """One beat row — checkbox + title + collapsible body markdown."""

    toggled = pyqtSignal(int, bool)  # (beat_index, new_checked)

    def __init__(self, index: int, beat: _Beat,
                 expanded: bool = True) -> None:
        super().__init__()
        self._index = index
        self._checked = beat.checked
        self._expanded = expanded
        self.setObjectName("beatCard")
        self._apply_card_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(beat.checked)
        self.checkbox.toggled.connect(self._on_toggled)
        top.addWidget(
            self.checkbox, 0, Qt.AlignmentFlag.AlignTop)

        # Chevron toggle — clicking expands/collapses the body.
        # Hidden when there's no body to reveal.
        self.expand_btn = QPushButton()
        self.expand_btn.setFlat(True)
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            " color: #6b7280; font-size: 11px; "
            " padding: 0 4px; min-width: 16px; } "
            "QPushButton:hover { color: #4f46e5; }")
        self.expand_btn.clicked.connect(self._toggle_expanded)
        top.addWidget(
            self.expand_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel(beat.title or "(untitled beat)")
        self.title_label.setWordWrap(True)
        self._apply_title_style()
        top.addWidget(self.title_label, stretch=1)
        layout.addLayout(top)

        body_md = "\n".join(beat.body_lines).strip()
        if body_md:
            self.body = QTextEdit()
            self.body.setReadOnly(True)
            self.body.setFrameShape(QFrame.Shape.NoFrame)
            self.body.setStyleSheet(
                "QTextEdit { background: transparent; "
                " border: none; padding: 0; "
                " color: #374151; font-size: 12px; }")
            self.body.setMarkdown(body_md)
            # Size to its rendered content so each beat card stays
            # compact. Cap the height so a runaway beat doesn't take
            # over the whole sidebar — internal scroll kicks in.
            doc = self.body.document()
            doc.setTextWidth(360)
            content_h = int(doc.size().height()) + 8
            self.body.setFixedHeight(min(max(content_h, 24), 280))
            self.body.setVisible(self._expanded)
            layout.addWidget(self.body)
            self.expand_btn.setText("▾" if self._expanded else "▸")
            self.expand_btn.setToolTip(
                "Hide beat details" if self._expanded
                else "Show beat details")
        else:
            self.body = None
            # No body to toggle — hide the chevron entirely.
            self.expand_btn.setVisible(False)

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
        if self._checked:
            self.title_label.setStyleSheet(
                "QLabel { font-size: 13px; font-weight: 600; "
                " color: #6b7280; }")
        else:
            self.title_label.setStyleSheet(
                "QLabel { font-size: 13px; font-weight: 600; "
                " color: #111827; }")

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

        # Mode toggle — flips between Checklist (rendered + checkable)
        # and Edit (raw markdown source).
        self.mode_btn = QPushButton("📝 Edit")
        self.mode_btn.setToolTip(
            "Switch to raw-markdown editing.")
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
        if self._preamble.strip():
            preamble_view = QTextEdit()
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
            empty = QLabel(self._PLACEHOLDER_EMPTY)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                "QLabel { color: #9ca3af; font-size: 12px; "
                " padding: 12px; }")
            layout.insertWidget(insert_at, empty)
            return

        for i, beat in enumerate(self._beats):
            card = _BeatCard(i, beat)
            card.toggled.connect(self._on_beat_toggled)
            layout.insertWidget(insert_at + i, card)

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

    def _emit_outline_changed(self) -> None:
        if self._current_chapter_id is None:
            return
        if not self._checklist_mode:
            self._source = self.editor.toPlainText()
        self.outline_changed.emit(self._source)

    def _toggle_mode(self) -> None:
        if self._checklist_mode:
            # Checklist → Edit: source is already current (checkbox
            # toggles serialize on the spot).
            self._checklist_mode = False
            self.mode_btn.setText("☑ Checklist")
            self.mode_btn.setToolTip(
                "Switch back to the beat-by-beat checklist view.")
            self._render()
        else:
            # Edit → Checklist: capture pending edits before parsing.
            self._source = self.editor.toPlainText()
            self._checklist_mode = True
            self.mode_btn.setText("📝 Edit")
            self.mode_btn.setToolTip(
                "Switch to raw-markdown editing.")
            self._render()
            # If the user actually edited the source while in Edit
            # mode, persist now so leaving Edit mode is a commit
            # boundary. The autosave debounce may not have fired yet.
            self._emit_outline_changed()
