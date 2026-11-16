"""The Companion tab beside a chapter: where you left off, margin notes,
a reader's-eye pass, and the story memory."""

from __future__ import annotations

import html
from typing import Any, Callable, List, Optional, Set

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget,
)

# A QThread destroyed while running aborts the app; keep them until done.
_RUNNING: Set["BackgroundTask"] = set()


class BackgroundTask(QThread):
    done = pyqtSignal(object, str)          # result, error

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), "")
        except Exception as e:
            self.done.emit(None, str(e))


def run_background(fn: Callable[[], Any], on_done: Callable[[Any, str], None]) -> BackgroundTask:
    task = BackgroundTask(fn)

    def safe(result, error):
        try:
            on_done(result, error)
        except Exception as e:          # an exception escaping a slot aborts PyQt6
            print(f"[companion] {e}")

    task.done.connect(safe)
    _RUNNING.add(task)
    task.finished.connect(lambda t=task: _RUNNING.discard(t))
    task.start()
    return task


def _group(title: str) -> QGroupBox:
    box = QGroupBox(title)
    box.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; margin-top: 8px; }"
                      "QGroupBox::title { subcontrol-origin: margin; left: 6px; }")
    return box


class CompanionPanel(QWidget):
    jump_requested = pyqtSignal(str)            # text to find and select
    note_action = pyqtSignal(object)            # companion.Note with an action
    note_dismissed = pyqtSignal(object)         # companion.Note
    reader_pass_requested = pyqtSignal()
    fixes_requested = pyqtSignal()
    ask_requested = pyqtSignal(object)          # companion.Note
    style_sheet_changed = pyqtSignal()
    memory_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.notes: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # Where you left off
        box = _group("Where you left off")
        v = QVBoxLayout(box)
        self.left_off_label = QLabel("")
        self.left_off_label.setWordWrap(True)
        self.left_off_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.left_off_label)
        self.recap_label = QLabel("")
        self.recap_label.setWordWrap(True)
        self.recap_label.setStyleSheet("color: #4338ca;")
        v.addWidget(self.recap_label)
        layout.addWidget(box)

        # Notes
        box = _group("Notes as you write")
        v = QVBoxLayout(box)
        self.notes_status = QLabel("Notes appear here when you finish a paragraph.")
        self.notes_status.setWordWrap(True)
        self.notes_status.setStyleSheet("color: #6b7280; font-size: 10px;")
        v.addWidget(self.notes_status)
        self.notes_list = QListWidget()
        self.notes_list.setWordWrap(True)
        self.notes_list.setMinimumHeight(110)
        self.notes_list.itemDoubleClicked.connect(lambda _i: self._go_to_note())
        v.addWidget(self.notes_list)
        row = QHBoxLayout()
        self.go_btn = QPushButton("Go to")
        self.go_btn.clicked.connect(self._go_to_note)
        self.act_btn = QPushButton("Mark beat done")
        self.act_btn.clicked.connect(self._act_on_note)
        self.dismiss_btn = QPushButton("Dismiss")
        self.dismiss_btn.clicked.connect(self._dismiss_note)
        self.ask_btn = QPushButton("💬 Ask")
        self.ask_btn.clicked.connect(self._ask_note)
        for b in (self.go_btn, self.act_btn, self.ask_btn, self.dismiss_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.notes_list.currentRowChanged.connect(self._update_note_buttons)
        layout.addWidget(box)

        # Today's three fixes
        box = _group("Today's three fixes")
        v = QVBoxLayout(box)
        self.fixes_btn = QPushButton("🎯 Find the three fixes that matter most")
        self.fixes_btn.clicked.connect(self.fixes_requested.emit)
        v.addWidget(self.fixes_btn)
        self.fixes_list = QListWidget()
        self.fixes_list.setWordWrap(True)
        self.fixes_list.setMaximumHeight(140)
        self.fixes_list.itemDoubleClicked.connect(lambda _i: self._go_to_fix())
        v.addWidget(self.fixes_list)
        go = QPushButton("Go to")
        go.clicked.connect(self._go_to_fix)
        v.addWidget(go)
        self.fixes = []
        layout.addWidget(box)

        # Reader's eye
        box = _group("Reader's eye")
        v = QVBoxLayout(box)
        self.reader_btn = QPushButton("👁 Read this chapter as a reader")
        self.reader_btn.clicked.connect(self.reader_pass_requested.emit)
        v.addWidget(self.reader_btn)
        self.reader_view = QTextBrowser()
        self.reader_view.setOpenLinks(False)
        self.reader_view.anchorClicked.connect(self._reader_link)
        self.reader_view.setMinimumHeight(150)
        self.reader_view.setPlaceholderText(
            "Where attention dips, what a reader is wondering, and which emotional beats land.")
        v.addWidget(self.reader_view)
        layout.addWidget(box)

        # Story memory
        box = _group("Story memory")
        v = QVBoxLayout(box)
        hint = QLabel("Decisions you've settled. Every AI tool reads these; 📌 pinned ones "
                      "are always included.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280; font-size: 10px;")
        v.addWidget(hint)
        self.memory_list = QListWidget()
        self.memory_list.setWordWrap(True)
        self.memory_list.setMinimumHeight(110)
        v.addWidget(self.memory_list)
        row = QHBoxLayout()
        self.memory_edit = QLineEdit()
        self.memory_edit.setPlaceholderText("e.g. Tobin doesn't know about the schedule")
        self.memory_edit.returnPressed.connect(self._add_memory)
        row.addWidget(self.memory_edit, 1)
        add = QPushButton("Add")
        add.clicked.connect(self._add_memory)
        row.addWidget(add)
        v.addLayout(row)
        row = QHBoxLayout()
        self.pin_btn = QPushButton("📌 Pin / unpin")
        self.pin_btn.clicked.connect(self._toggle_pin)
        self.accept_btn = QPushButton("✓ Keep suggestion")
        self.accept_btn.clicked.connect(self._accept_memory)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_memory)
        for b in (self.pin_btn, self.accept_btn, self.delete_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        layout.addWidget(box)
        # Personal style sheet
        box = _group("Your style sheet")
        v = QVBoxLayout(box)
        hint = QLabel("Your own rules — learned from what you ignore and fix, or typed in: "
                      "“allow vethari” · “prefer grey over gray” · “avoid very” · "
                      "“keep passive voice” · or any note.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280; font-size: 10px;")
        v.addWidget(hint)
        self.style_status = QLabel("")
        self.style_status.setWordWrap(True)
        self.style_status.setStyleSheet("color: #be185d; font-size: 10px;")
        v.addWidget(self.style_status)
        self.sheet_list = QListWidget()
        self.sheet_list.setWordWrap(True)
        self.sheet_list.setMinimumHeight(90)
        v.addWidget(self.sheet_list)
        row = QHBoxLayout()
        self.sheet_edit = QLineEdit()
        self.sheet_edit.setPlaceholderText("e.g. prefer grey over gray")
        self.sheet_edit.returnPressed.connect(self._add_rule)
        row.addWidget(self.sheet_edit, 1)
        add_rule = QPushButton("Add")
        add_rule.clicked.connect(self._add_rule)
        row.addWidget(add_rule)
        v.addLayout(row)
        row = QHBoxLayout()
        keep = QPushButton("✓ Keep suggestion")
        keep.clicked.connect(self._accept_rule)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete_rule)
        row.addWidget(keep)
        row.addWidget(delete)
        row.addStretch()
        v.addLayout(row)
        layout.addWidget(box)
        layout.addStretch()
        self._update_note_buttons()

    # ── Where you left off ───────────────────────────────────────────

    def set_left_off(self, brief) -> None:
        items = "".join(f"<li>{html.escape(l)}</li>" for l in brief.lines)
        self.left_off_label.setText(f"<ul style='margin-left:-20px'>{items}</ul>" if items else
                                    "<i>First time in this chapter — happy writing.</i>")
        self.recap_label.setText("")

    def set_recap(self, recap: str) -> None:
        self.recap_label.setText(f"<b>The scene so far:</b> {html.escape(recap)}" if recap else "")

    # ── Notes ────────────────────────────────────────────────────────

    ICONS = {"pov": "👁", "tense": "⏱", "beat": "✓", "appearance": "🎨", "voice": "💬",
             "ai": "✨", "canon": "📖"}

    def set_notes(self, notes: list, status: str = "") -> None:
        self.notes = list(notes)
        self.notes_list.clear()
        for n in self.notes:
            item = QListWidgetItem(f"{self.ICONS.get(n.kind, '•')} {n.text}")
            item.setToolTip(n.excerpt)
            self.notes_list.addItem(item)
        self.notes_status.setText(status or ("No notes — all clear." if not self.notes else
                                             f"{len(self.notes)} note"
                                             f"{'s' if len(self.notes) != 1 else ''}."))
        self._update_note_buttons()

    def _current_note(self):
        row = self.notes_list.currentRow()
        return self.notes[row] if 0 <= row < len(self.notes) else None

    def _update_note_buttons(self, *_):
        note = self._current_note()
        self.go_btn.setEnabled(note is not None)
        self.ask_btn.setEnabled(note is not None)
        self.dismiss_btn.setEnabled(note is not None)
        self.act_btn.setVisible(note is not None and bool(note.action))

    def _go_to_note(self):
        note = self._current_note()
        if note is not None and note.excerpt:
            self.jump_requested.emit(note.excerpt)

    def _act_on_note(self):
        note = self._current_note()
        if note is not None and note.action:
            self.note_action.emit(note)
            self._remove_current()

    def _dismiss_note(self):
        note = self._current_note()
        if note is not None:
            self.note_dismissed.emit(note)
            self._remove_current()

    def _remove_current(self):
        row = self.notes_list.currentRow()
        if 0 <= row < len(self.notes):
            del self.notes[row]
            self.set_notes(self.notes)

    # ── Reader's eye ─────────────────────────────────────────────────

    def set_reader_busy(self, busy: bool) -> None:
        self.reader_btn.setEnabled(not busy)
        if busy:
            self.reader_view.setHtml("<i>Reading…</i>")

    def set_reader_report(self, report, error: str = "") -> None:
        self.reader_btn.setEnabled(True)
        if report is None:
            self.reader_view.setHtml(f"<p style='color:#b00020'>{html.escape(error)}</p>")
            return

        def quote(q, note):
            if not q:
                return html.escape(note)
            href = "jump:" + QUrl.toPercentEncoding(q).data().decode()
            return f"<a href='{href}'>“{html.escape(q)}”</a> — {html.escape(note)}"

        parts = []
        if report.dips:
            parts.append("<b>Where attention dips</b><ul>"
                         + "".join(f"<li>{quote(q, w)}</li>" for q, w in report.dips) + "</ul>")
        if report.questions:
            parts.append("<b>What a reader is wondering</b><ul>"
                         + "".join(f"<li>{html.escape(q)}</li>" for q in report.questions)
                         + "</ul>")
        if report.beats:
            parts.append("<b>Emotional beats</b><ul>"
                         + "".join(f"<li>{quote(q, w)}</li>" for q, w in report.beats) + "</ul>")
        if report.overall:
            parts.append(f"<p><i>{html.escape(report.overall)}</i></p>")
        self.reader_view.setHtml("".join(parts) or "<i>Nothing to report.</i>")

    def _reader_link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("jump:"):
            self.jump_requested.emit(QUrl.fromPercentEncoding(s[5:].encode()))

    # ── Story memory ─────────────────────────────────────────────────

    def set_project(self, project) -> None:
        self.project = project
        self.refresh_memory()
        self.refresh_style_sheet()

    # ── Today's three fixes ─────────────────────────────────────────

    def set_fixes_busy(self) -> None:
        self.fixes_btn.setEnabled(False)
        self.fixes_list.clear()
        self.fixes_list.addItem("Looking…")

    def set_fixes(self, fixes) -> None:
        self.fixes_btn.setEnabled(True)
        self.fixes = list(fixes or [])
        self.fixes_list.clear()
        for n, f in enumerate(self.fixes, 1):
            item = QListWidgetItem(f"{n}. {f.text}" + (f"\n   → {f.why}" if f.why else ""))
            item.setToolTip(f.excerpt)
            self.fixes_list.addItem(item)
        if not self.fixes:
            self.fixes_list.addItem("Nothing flagged — nice work.")

    def _go_to_fix(self):
        row = self.fixes_list.currentRow()
        if 0 <= row < len(self.fixes) and self.fixes[row].excerpt:
            self.jump_requested.emit(self.fixes[row].excerpt)

    def _ask_note(self):
        note = self._current_note()
        if note is not None:
            self.ask_requested.emit(note)

    # ── Style sheet ─────────────────────────────────────────────────

    def refresh_style_sheet(self, message: str = "") -> None:
        if message:
            self.style_status.setText(message)
        self.sheet_list.clear()
        rules = list(getattr(self.project, "style_sheet", None) or [])
        rules.sort(key=lambda r: r.status != "suggested")
        self._rule_ids = []
        for r in rules:
            label = ("💡 suggested: " if r.status == "suggested" else "") + r.text
            item = QListWidgetItem(label)
            if r.status == "suggested":
                item.setForeground(Qt.GlobalColor.darkYellow)
            self.sheet_list.addItem(item)
            self._rule_ids.append(r.id)

    def _current_rule(self):
        row = self.sheet_list.currentRow()
        ids = getattr(self, "_rule_ids", [])
        if self.project is None or not (0 <= row < len(ids)):
            return None
        return next((r for r in self.project.style_sheet if r.id == ids[row]), None)

    def _sheet_changed(self):
        self.refresh_style_sheet()
        self.style_sheet_changed.emit()

    def _add_rule(self):
        from src.ai import style_sheet as ss
        text = self.sheet_edit.text().strip()
        if text and self.project is not None:
            rule = ss.add(self.project, text)
            self.sheet_edit.clear()
            self.style_status.setText(f"Added: {rule.text}" if rule else "Already there.")
            self._sheet_changed()

    def _accept_rule(self):
        r = self._current_rule()
        if r is not None:
            r.status = "active"
            self._sheet_changed()

    def _delete_rule(self):
        from src.ai import style_sheet as ss
        r = self._current_rule()
        if r is not None:
            ss.remove(self.project, r.id)
            self._sheet_changed()

    def refresh_memory(self) -> None:
        self.memory_list.clear()
        entries = list(getattr(self.project, "story_memory", None) or [])
        entries.sort(key=lambda e: (e.status != "suggested", not e.pinned))
        self._memory_ids = []
        for e in entries:
            mark = "📌 " if e.pinned else ("💡 suggested: " if e.status == "suggested" else "")
            item = QListWidgetItem(mark + e.text)
            if e.status == "suggested":
                item.setForeground(Qt.GlobalColor.darkYellow)
            self.memory_list.addItem(item)
            self._memory_ids.append(e.id)

    def _current_memory(self):
        row = self.memory_list.currentRow()
        ids = getattr(self, "_memory_ids", [])
        if not (0 <= row < len(ids)) or self.project is None:
            return None
        return next((e for e in self.project.story_memory if e.id == ids[row]), None)

    def _changed(self):
        self.refresh_memory()
        self.memory_changed.emit()

    def _add_memory(self):
        from src.ai import story_memory
        text = self.memory_edit.text().strip()
        if text and self.project is not None and story_memory.add(self.project, text):
            self.memory_edit.clear()
            self._changed()

    def _toggle_pin(self):
        e = self._current_memory()
        if e is not None:
            e.pinned = not e.pinned
            e.status = "active"
            self._changed()

    def _accept_memory(self):
        e = self._current_memory()
        if e is not None:
            e.status = "active"
            self._changed()

    def _delete_memory(self):
        from src.ai import story_memory
        e = self._current_memory()
        if e is not None:
            story_memory.remove(self.project, e.id)
            self._changed()


# ── Banner + controller (wired into ChapterEditor) ───────────────────

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QFrame


class CompanionBanner(QFrame):
    """One line above the chapter: where you left off."""
    open_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("CompanionBanner { background: #eef2ff; border: 1px solid #c7d2fe;"
                           " border-radius: 4px; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 4, 3)
        self.label = QLabel("")
        self.label.setStyleSheet("color: #3730a3; font-size: 11px;")
        self.label.setWordWrap(False)
        row.addWidget(self.label, 1)
        more = QPushButton("Details")
        more.setStyleSheet("font-size: 10px; padding: 1px 6px;")
        more.clicked.connect(self.open_requested.emit)
        row.addWidget(more)
        close = QPushButton("×")
        close.setFixedWidth(22)
        close.setStyleSheet("font-size: 12px; border: none;")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        self.hide()

    def show_text(self, text: str, tooltip: str = "") -> None:
        self.label.setText(text)
        self.setToolTip(tooltip)
        self.setVisible(bool(text))


def _companion_ai_enabled() -> bool:
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get("companion_ai", True))
    except Exception:
        return True


def _daily_goal() -> int:
    try:
        from src.config.creativeos_config import get_creativeos_config
        return int(get_creativeos_config().get("daily_word_goal", 0) or 0)
    except Exception:
        return 0


class CompanionController(QObject):
    """Runs the companion for one ChapterEditor."""

    NOTES_DELAY_MS = 4000
    MAX_PARAGRAPHS_PER_REVIEW = 4

    def __init__(self, chapter_editor):
        super().__init__(chapter_editor)
        self.ce = chapter_editor
        self.panel = CompanionPanel()
        chapter_editor.right_panel.addTab(self.panel, "Companion")
        self.banner = chapter_editor.companion_banner
        self.banner.open_requested.connect(self.open_panel)
        self.panel.jump_requested.connect(self.jump_to)
        self.panel.note_action.connect(self._on_note_action)
        self.panel.note_dismissed.connect(self._on_note_dismissed)
        self.panel.reader_pass_requested.connect(self.run_reader_pass)
        self.panel.fixes_requested.connect(self.find_three_fixes)
        self.panel.ask_requested.connect(self.ask_about_note)
        self.panel.style_sheet_changed.connect(self._style_sheet_edited)
        chapter_editor.editor.style_sheet_changed.connect(self._style_sheet_learned)
        self.panel.memory_changed.connect(chapter_editor.content_changed.emit)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.NOTES_DELAY_MS)
        self._timer.timeout.connect(self.scan_paragraphs)
        chapter_editor.editor.textChanged.connect(self._timer.start)
        self._seen = {}               # paragraph index → hash already checked
        self._notes = {}              # paragraph text hash → [Note]
        self._words_at_open = 0
        self._voice = None
        self._profiles = None
        self._no_model = False

    @property
    def project(self):
        return getattr(self.ce, "project", None)

    @property
    def chapter(self):
        return getattr(self.ce, "chapter", None)

    def _word_count(self) -> int:
        return len(self.ce.editor.toPlainText().split())

    # ── chapter open / save ──────────────────────────────────────────

    def chapter_loaded(self) -> None:
        from src.ai import companion
        from src.data import companion_state as cs
        text = self.ce.editor.toPlainText()
        self._words_at_open = len(text.split())
        self._seen = {i: hash(p) for i, p in enumerate(text.split("\n"))}
        self._notes = {}
        self._voice = self._profiles = None
        self.panel.set_project(self.project)
        self.panel.set_notes([], "Notes appear here when you finish a paragraph.")
        if self.project is None or self.chapter is None:
            return
        before = cs.mark_opened(self.project, self.chapter.id)
        brief = companion.left_off(self.project, self.chapter, text, before,
                                   cs.words_today(self.project), _daily_goal())
        self.panel.set_left_off(brief)
        self.banner.show_text(brief.headline, "\n".join(brief.lines))
        self._start_recap(text, before.get("stopped_at", ""))

    def chapter_saved(self) -> None:
        from src.data import companion_state as cs
        if self.project is None or self.chapter is None:
            return
        cursor = self.ce.editor.textCursor()
        block = cursor.block().text().strip()
        import re
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", block) if s.strip()]
        cs.record_session(self.project, self.chapter.id, self._words_at_open,
                          self._word_count(), sentences[-1] if sentences else block)

    def open_panel(self) -> None:
        self.ce._show_right_panel(self.panel)

    # ── model helpers ────────────────────────────────────────────────

    def _llm(self):
        if self._no_model or not _companion_ai_enabled():
            return None
        from src.ai import word_suggest
        llm = word_suggest.get_llm()
        if llm is None:
            self._no_model = True
        return llm

    def _start_recap(self, text: str, stopped_at: str) -> None:
        from src.ai import companion, scene_brief
        before = companion.recap_text_before(text, stopped_at)
        if len(before.split()) < scene_brief._MIN_LEAD_UP_WORDS or not _companion_ai_enabled():
            return
        cached = scene_brief.cached_moment(self.chapter, before)
        if cached:
            self.panel.set_recap(cached)
            return
        chapter = self.chapter
        names = [c.name for c in getattr(self.project, "characters", None) or []]

        def work():
            llm = self._llm()
            return scene_brief.moment_summary(llm, chapter, before, names) if llm else ""

        run_background(work, lambda recap, _e: self.panel.set_recap(recap or ""))

    # ── margin notes ─────────────────────────────────────────────────

    def scan_paragraphs(self) -> None:
        """Check paragraphs the writer has finished since the last scan."""
        from src.ai import companion
        from src.data import companion_state as cs
        if self.project is None or self.chapter is None:
            return
        text = self.ce.editor.toPlainText()
        paragraphs = text.split("\n")
        current = self.ce.editor.textCursor().blockNumber()
        changed = [i for i, p in enumerate(paragraphs)
                   if p.strip() and i != current and self._seen.get(i) != hash(p)]
        for i in changed:
            self._seen[i] = hash(paragraphs[i])
        if not changed:
            return
        if self._voice is None:
            from src.ai.writer_voice import project_voice
            self._voice = project_voice(self.project, self.chapter, text)
        if self._profiles is None:
            from src.ai.dialogue_craft import speech_profiles
            self._profiles = speech_profiles(self.project)
        quick = companion.paragraph_notes(self.project, self.chapter, paragraphs, changed,
                                          self._voice, self._profiles)
        hidden = cs.dismissed(self.project)
        quick = [n for n in quick if n.key not in hidden]
        for i in changed:
            self._notes[hash(paragraphs[i])] = [n for n in quick if n.paragraph == i]
        self._show_notes()
        review = changed[-self.MAX_PARAGRAPHS_PER_REVIEW:]
        if not _companion_ai_enabled() or self._no_model:
            return
        project, chapter = self.project, self.chapter
        paras = {i: paragraphs[i] for i in review if len(paragraphs[i].split()) >= 12}
        if not paras:
            return
        candidates = [n for n in quick if n.paragraph in paras]
        context = companion.judge_context(project, chapter, " ".join(paras.values()))

        def work():
            llm = self._llm()
            return companion.judge_notes(llm, paras, candidates, context) if llm else None

        def done(notes, _error):
            if notes is None:
                return
            keep = [n for n in notes if n.key not in cs.dismissed(project)]
            for i, p in paras.items():
                self._notes[hash(p)] = [n for n in keep if n.paragraph == i]
            self._show_notes()

        self.panel.notes_status.setText("Checking…")
        run_background(work, done)

    def _show_notes(self) -> None:
        paragraphs = self.ce.editor.toPlainText().split("\n")
        index = {hash(p): i for i, p in enumerate(paragraphs)}
        notes = []
        for h, found in self._notes.items():
            if h in index:
                for n in found:
                    n.paragraph = index[h]
                    notes.append(n)
        notes.sort(key=lambda n: n.paragraph)
        self.panel.set_notes(notes)
        tab = self.ce.right_panel.indexOf(self.panel)
        if tab >= 0:
            self.ce.right_panel.setTabText(tab, f"Companion ({len(notes)})" if notes else "Companion")

    def _on_note_dismissed(self, note) -> None:
        from src.data import companion_state as cs
        if self.project is not None:
            cs.dismiss(self.project, note.key)
        for found in self._notes.values():
            if note in found:
                found.remove(note)
        self._show_notes()

    def _on_note_action(self, note) -> None:
        action = note.action or {}
        if action.get("type") == "mark_beat":
            self.mark_beat_done(action.get("event_id", ""))
        for found in self._notes.values():
            if note in found:
                found.remove(note)
        self._show_notes()

    def mark_beat_done(self, event_id: str) -> None:
        for e in getattr(getattr(self.chapter, "planning", None), "events", None) or []:
            if e.id == event_id:
                e.completed = True
        try:
            data = self.ce.planner_widget.get_planning_data()
            for e in data.get("events", []):
                if e.get("id") == event_id:
                    e["completed"] = True
            self.ce.planner_widget.set_planning_data(data)
        except Exception as e:
            print(f"[companion] could not update the planner: {e}")
        self.ce.content_changed.emit()

    def jump_to(self, excerpt: str) -> None:
        from PyQt6.QtGui import QTextCursor, QTextDocument
        editor = self.ce.editor
        found = editor.document().find(excerpt.strip()[:80], 0)
        if found.isNull():
            return
        editor.setTextCursor(found)
        editor.ensureCursorVisible()
        editor.setFocus()

    # ── reader's eye ─────────────────────────────────────────────────

    def run_reader_pass(self) -> None:
        from src.ai import companion
        if self.chapter is None:
            return
        text = self.ce.editor.toPlainText()
        project, chapter = self.project, self.chapter
        self.panel.set_reader_busy(True)

        def work():
            llm = self._llm()
            if llm is None:
                return companion.reader_pass_quick(project, chapter, text)
            from src.ai.chapter_analysis_agent import is_local_llm
            return companion.reader_pass(llm, project, chapter, text, compact=is_local_llm(llm))

        run_background(work, lambda report, error: self.panel.set_reader_report(
            report, error or "Couldn't read the chapter."))

    # ── Today's three fixes, 💬 Ask from a note, style sheet ────────────

    def find_three_fixes(self) -> None:
        from src.ai import companion
        hl = self.ce.editor.writing_highlighter
        if hl.phase == "drafting":
            self.ce.editor._apply_phase("revising")       # asking for fixes = revising
        else:
            hl.rehighlight()
        candidates = companion.fix_candidates(hl, self.ce.editor.document(), self.panel.notes)
        if not candidates:
            self.panel.set_fixes([])
            return
        project, chapter = self.project, self.chapter
        context = companion.judge_context(project, chapter, self.ce.editor.toPlainText()[:4000]) \
            if project is not None else ""
        self.panel.set_fixes_busy()

        def work():
            llm = self._llm()
            return (companion.three_fixes(llm, candidates, context) if llm
                    else companion.three_fixes_quick(candidates))

        run_background(work, lambda fixes, _e: self.panel.set_fixes(fixes))

    def ask_about_note(self, note) -> None:
        text = self.ce.editor.toPlainText()
        paragraphs = text.split("\n")
        i = note.paragraph if 0 <= note.paragraph < len(paragraphs) else 0
        paragraph = paragraphs[i] if paragraphs else ""
        block = self.ce.editor.document().findBlockByNumber(i)
        at = max(0, paragraph.find(note.excerpt[:40])) if note.excerpt else 0
        self.ce.editor.open_ask_dialog(paragraph, block.position(), at,
                                       at + max(1, len(note.excerpt or "")), "note",
                                       note.excerpt or paragraph[:40], note.text)

    def _style_sheet_edited(self) -> None:
        self.ce.editor.refresh_style_sheet()
        self.ce.content_changed.emit()

    def _style_sheet_learned(self, message: str) -> None:
        self.panel.refresh_style_sheet(message)
        self.ce.content_changed.emit()
