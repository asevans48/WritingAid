"""Floating slim chapter editor — read along + small edits.

Opens from both the slide and video editors. Lets the writer
scroll through chapter prose while recording (the original ask)
and now also lets them fix typos or tighten a sentence in place
without leaving the video studio. Edits flow back into the live
project via an ``on_save`` callback the host wires up; an
"📝 Open in writer" button hands off to the main writer when the
writer needs heavier tools.

Design choices for a laptop-friendly UI:
  * A single top-row of controls (chapter, font, on-top toggle).
  * Find bar that collapses into one row.
  * Big ``QPlainTextEdit`` body — the writer spends most of their
    time here, so it gets all the room.
  * Status footer with word count + read-time + dirty marker so
    the writer always knows where they stand.
  * Modest default size (~520 × 640) that fits a 13" laptop and
    docks beside the parent without overlapping.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)


class ChapterProseWindow(QDialog):
    """Non-modal slim chapter editor.

    Constructor takes a list of ``(chapter_id, chapter_label,
    chapter_text)`` triples — the caller flattens the project
    model so this window stays decoupled. When ``on_save`` is
    wired, edits flow back via ``on_save(chapter_id, new_text)``;
    when None, the window stays read-only. ``on_open_in_writer``
    handoff is shown as a button when wired — clicking it closes
    this window and jumps to the main writer on the current
    chapter.
    """

    def __init__(
        self,
        chapters: List[Any],
        initial_chapter_id: Optional[str] = None,
        on_save: Optional[Callable[[str, str], bool]] = None,
        on_open_in_writer: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(None)
        self.setWindowTitle("📖 Chapter editor")
        self.setModal(False)
        # ``Qt.Tool`` is the right floater type on macOS — it
        # behaves like Xcode's quick-find palette: stays above its
        # peers, takes focus when clicked, but doesn't activate
        # the whole app or minimize other windows when it opens.
        # Using ``Qt.Window`` here triggers macOS's focus-stealing
        # heuristic which can blank the second monitor on dual-
        # screen rigs and minimize the studio when the prose
        # window opens.
        #
        # Window flags are set ONCE here at construction. Calling
        # ``setWindowFlag`` again later forces a hide → re-show
        # cycle that macOS treats as "this is a brand-new window"
        # and re-runs the focus-stealing path, which is the same
        # bug. The "on top" checkbox is wired to a NoOp / minimize
        # toggle instead of a flag reassignment.
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setWindowFlags(flags)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Modest default size so it docks comfortably beside the
        # parent editor on a 13" laptop without stealing too much
        # canvas.
        target_w = 520
        target_h = 640
        if avail is not None:
            target_w = max(380, min(target_w, int(avail.width() * 0.42)))
            target_h = max(420, min(target_h, int(avail.height() * 0.85)))
        self.resize(target_w, target_h)
        self.setMinimumSize(360, 360)
        self._chapters = list(chapters or [])
        self._on_save = on_save
        self._on_open_in_writer = on_open_in_writer
        # Track which chapter's edits are pending so the autosave
        # timer flushes the right one even after the writer
        # switched chapters mid-edit.
        self._dirty_chapter_id: Optional[str] = None
        # Debounced autosave — fires 1.2 s after the last keystroke.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1200)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._build_ui()
        if initial_chapter_id:
            for i, (cid, _, _) in enumerate(self._chapters):
                if cid == initial_chapter_id:
                    self._chapter_combo.setCurrentIndex(i)
                    break
        if parent is not None and avail is not None:
            try:
                pgeom = parent.frameGeometry()
                self.move(
                    min(avail.right() - self.width(),
                        pgeom.right() + 12),
                    pgeom.top())
            except Exception:
                pass

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Chapter:"))
        self._chapter_combo = QComboBox()
        for cid, label, _text in self._chapters:
            self._chapter_combo.addItem(label or cid, cid)
        self._chapter_combo.currentIndexChanged.connect(
            self._on_chapter_changed)
        header_row.addWidget(self._chapter_combo, stretch=1)
        header_row.addWidget(QLabel("Size:"))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 36)
        self._font_size_spin.setValue(14)
        self._font_size_spin.setSuffix(" pt")
        self._font_size_spin.valueChanged.connect(
            self._on_font_size_changed)
        header_row.addWidget(self._font_size_spin)
        self._always_on_top_check = QCheckBox("On top")
        self._always_on_top_check.setChecked(True)
        self._always_on_top_check.setToolTip(
            "Keep this window above the editor so you can read "
            "along while recording. Turn off if it gets in the way.")
        self._always_on_top_check.toggled.connect(
            self._on_always_on_top_toggled)
        header_row.addWidget(self._always_on_top_check)
        v.addLayout(header_row)

        # Find bar — narrow and single-row.
        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find:"))
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("Search this chapter…")
        self._find_edit.returnPressed.connect(self._on_find_next)
        find_row.addWidget(self._find_edit, stretch=1)
        self._find_next_btn = QPushButton("↓")
        self._find_next_btn.setMaximumWidth(36)
        self._find_next_btn.setToolTip("Find next")
        self._find_next_btn.clicked.connect(self._on_find_next)
        find_row.addWidget(self._find_next_btn)
        self._find_prev_btn = QPushButton("↑")
        self._find_prev_btn.setMaximumWidth(36)
        self._find_prev_btn.setToolTip("Find previous")
        self._find_prev_btn.clicked.connect(self._on_find_prev)
        find_row.addWidget(self._find_prev_btn)
        v.addLayout(find_row)

        # Main editor body.
        self._text_view = QPlainTextEdit()
        # Read-only when no save callback is wired (legacy
        # read-along use); editable when the host wired ``on_save``.
        self._text_view.setReadOnly(self._on_save is None)
        self._text_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._text_view.textChanged.connect(self._on_text_changed)
        self._set_font_size(14)
        v.addWidget(self._text_view, stretch=1)

        # Bottom row: status + action buttons.
        bottom_row = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        bottom_row.addWidget(self._status_label, stretch=1)
        self._save_btn = QPushButton("💾 Save")
        self._save_btn.setToolTip(
            "Write the current text back to the chapter. "
            "Auto-save runs ~1 second after each keystroke too.")
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._save_btn.setVisible(self._on_save is not None)
        bottom_row.addWidget(self._save_btn)
        self._open_writer_btn = QPushButton("📝 Open in writer")
        self._open_writer_btn.setToolTip(
            "Saves the current text and switches to the main "
            "writer for heavier editing. The video / slide editor "
            "state stays put — come back any time.")
        self._open_writer_btn.clicked.connect(
            self._on_open_in_writer_clicked)
        self._open_writer_btn.setVisible(
            self._on_open_in_writer is not None)
        bottom_row.addWidget(self._open_writer_btn)
        v.addLayout(bottom_row)

        if not self._chapters:
            self._text_view.setPlainText(
                "No chapters available in this project. Open a "
                "chapter editor to write prose first.")
            self._chapter_combo.setEnabled(False)
            self._find_edit.setEnabled(False)
            self._find_next_btn.setEnabled(False)
            self._find_prev_btn.setEnabled(False)
            self._save_btn.setEnabled(False)
            self._open_writer_btn.setEnabled(False)
        else:
            self._refresh_text()

    # ------------------------------------------------------------------
    # Chapter switching + loading
    # ------------------------------------------------------------------
    def _refresh_text(self) -> None:
        idx = self._chapter_combo.currentIndex()
        if idx < 0 or idx >= len(self._chapters):
            return
        _cid, _label, text = self._chapters[idx]
        # Loading text fires textChanged; suppress so it doesn't
        # mark a fresh chapter dirty.
        self._text_view.blockSignals(True)
        self._text_view.setPlainText(
            text or "(This chapter has no prose yet.)")
        self._text_view.blockSignals(False)
        self._dirty_chapter_id = None
        self._refresh_status()

    def _on_chapter_changed(self, _index: int) -> None:
        # Flush any pending edits on the OLD chapter before
        # switching — losing typed text to a chapter change is
        # the worst kind of papercut.
        if (self._dirty_chapter_id is not None
                and self._dirty_chapter_id
                != self._chapter_combo.currentData()):
            self._do_autosave()
        self._refresh_text()

    def _refresh_status(self) -> None:
        idx = self._chapter_combo.currentIndex()
        if idx < 0 or idx >= len(self._chapters):
            self._status_label.setText("")
            return
        _cid, label, _text = self._chapters[idx]
        text = self._text_view.toPlainText()
        words = len(text.split())
        seconds = round(words / 150 * 60) if words else 0
        m, s = divmod(seconds, 60)
        time_hint = f"{m}m {s}s" if m else f"{s}s"
        dirty_mark = " · ●unsaved" if self._dirty_chapter_id else ""
        self._status_label.setText(
            f"{label} — {words} word"
            + ("s" if words != 1 else "")
            + f" · ~{time_hint}{dirty_mark}")

    # ------------------------------------------------------------------
    # Edit + save
    # ------------------------------------------------------------------
    def _on_text_changed(self) -> None:
        if self._on_save is None:
            return
        # Mark the currently-visible chapter dirty + (re)start the
        # debounced autosave timer.
        cid = self._chapter_combo.currentData()
        if cid:
            self._dirty_chapter_id = cid
            self._autosave_timer.start()
            self._refresh_status()

    def _do_autosave(self) -> None:
        if self._on_save is None:
            return
        cid = self._dirty_chapter_id
        if not cid:
            return
        # ``_on_chapter_changed`` calls us BEFORE swapping the
        # combo's text view, so reading from the view here always
        # reflects the dirty chapter's content even when the combo
        # just moved to a different entry. The dirty_chapter_id is
        # the authoritative key.
        text = self._text_view.toPlainText()
        try:
            ok = bool(self._on_save(cid, text))
        except Exception as e:
            self._status_label.setText(f"Save failed: {e}")
            return
        if ok:
            self._dirty_chapter_id = None
            # Mirror the saved text back into the in-memory list
            # so a chapter-switch round-trip sees the new content.
            for i, (chap_id, label, _t) in enumerate(self._chapters):
                if chap_id == cid:
                    self._chapters[i] = (chap_id, label, text)
                    break
            self._refresh_status()

    def _on_save_clicked(self) -> None:
        if self._on_save is None:
            return
        # Cancel any pending debounce so the manual save doesn't
        # race the timer.
        self._autosave_timer.stop()
        cid = self._chapter_combo.currentData()
        if not cid:
            return
        text = self._text_view.toPlainText()
        try:
            ok = bool(self._on_save(cid, text))
        except Exception as e:
            QMessageBox.warning(
                self, "Save failed",
                f"Could not save chapter: {e}")
            return
        if ok:
            self._dirty_chapter_id = None
            for i, (chap_id, label, _t) in enumerate(self._chapters):
                if chap_id == cid:
                    self._chapters[i] = (chap_id, label, text)
                    break
            self._refresh_status()

    def _on_open_in_writer_clicked(self) -> None:
        if self._on_open_in_writer is None:
            return
        # Flush dirty text first so the writer view opens on the
        # freshest content.
        if self._dirty_chapter_id is not None:
            self._do_autosave()
        cid = self._chapter_combo.currentData() or ""
        try:
            self._on_open_in_writer(cid)
        except Exception as e:
            QMessageBox.warning(
                self, "Open in writer failed",
                f"Could not jump to the main writer: {e}")
            return
        self.close()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def _set_font_size(self, pt: int) -> None:
        font = QFont()
        font.setPointSize(pt)
        self._text_view.setFont(font)

    def _on_font_size_changed(self, pt: int) -> None:
        self._set_font_size(pt)

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        # Reassigning ``WindowStaysOnTopHint`` after show forces a
        # hide → re-show cycle that minimizes peer windows on
        # macOS and (on multi-monitor rigs) can blank the other
        # screen. ``lower()`` / ``raise_()`` get us 95 % of the
        # behavior writers actually want without that cost: when
        # the box is checked we make sure the window is at the
        # front; unchecking just drops it behind the focused
        # window. The window keeps the Tool flag throughout.
        if checked:
            self.raise_()
        else:
            self.lower()

    # ------------------------------------------------------------------
    # Find
    # ------------------------------------------------------------------
    def _on_find_next(self) -> None:
        needle = self._find_edit.text()
        if not needle:
            return
        if not self._text_view.find(needle):
            self._text_view.moveCursor(
                QTextCursor.MoveOperation.Start)
            if not self._text_view.find(needle):
                self._status_label.setText(
                    f"'{needle}' not found.")

    def _on_find_prev(self) -> None:
        needle = self._find_edit.text()
        if not needle:
            return
        from PyQt6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag.FindBackward
        if not self._text_view.find(needle, flags):
            self._text_view.moveCursor(
                QTextCursor.MoveOperation.End)
            if not self._text_view.find(needle, flags):
                self._status_label.setText(
                    f"'{needle}' not found.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        # Flush any pending edits so closing doesn't drop them.
        if self._dirty_chapter_id is not None:
            self._autosave_timer.stop()
            self._do_autosave()
        super().closeEvent(event)
