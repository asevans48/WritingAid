"""The Companion tab beside a chapter: where you left off, margin notes,
a reader's-eye pass, and the story memory."""

from __future__ import annotations

import html
import re
from typing import Any, Callable, List, Optional, Set

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

# Background work runs through the shared helper (R.2). These names are kept
# so existing imports (and tests that wait on ``_RUNNING``) keep working.
from src.ui import background as _background  # noqa: E402

_RUNNING = _background._RUNNING
BackgroundTask = _background.Task


def run_background(fn: Callable[[], Any], on_done: Callable[[Any, str], None]) -> "BackgroundTask":
    return _background.run_background(fn, on_done, label="companion")


# Moved to the shared kit (U.1); imported here so every existing
# ``from src.ui.companion_panel import CollapsibleSection`` keeps working.
from src.ui.ui_kit import CollapsibleSection, section_header  # noqa: E402


def _divider(text: str) -> QLabel:
    return section_header(text)


def _small(text: str = "", color: str = "#6b7280") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color}; font-size: 10px;")
    return label


class CompanionPanel(QWidget):
    jump_requested = pyqtSignal(str)            # text to find and select
    note_action = pyqtSignal(object)            # companion.Note with an action
    note_dismissed = pyqtSignal(object)         # companion.Note
    note_fix_requested = pyqtSignal(object)     # companion.Note → Suggestions
    reader_pass_requested = pyqtSignal()
    fixes_requested = pyqtSignal()
    fix_accepted = pyqtSignal(object, str)      # companion.Fix, replacement sentence
    fix_more_requested = pyqtSignal(object)     # companion.Fix → Suggestions
    overdescribed_requested = pyqtSignal()      # check this chapter (with the model if any)
    expand_requested = pyqtSignal(object)       # overdescription.Flag → Expand dialog
    ask_requested = pyqtSignal(object)          # companion.Note
    style_sheet_changed = pyqtSignal()
    memory_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.chapter_text = ""
        self.notes: list = []
        self.fixes: list = []
        self.flags: list = []
        self.sections: dict = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # Which chapter this is about, and open/close all.
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 4, 0)
        self.chapter_label = QLabel("")
        self.chapter_label.setWordWrap(True)
        self.chapter_label.setStyleSheet("font-weight: bold; color: #312e81; font-size: 12px;")
        top.addWidget(self.chapter_label, 1)
        for label, tip, is_open in (("▾ all", "Open every section", True),
                                    ("▸ all", "Close every section", False)):
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setStyleSheet("QToolButton { border: none; color: #4b5563; font-size: 10px;"
                              " padding: 1px 4px; } QToolButton:hover { background: #e5e7eb;"
                              " border-radius: 3px; }")
            btn.clicked.connect(lambda _=False, o=is_open: self.set_all_open(o))
            top.addWidget(btn)
        outer.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 0, 6, 6)
        layout.setSpacing(2)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        layout.addWidget(_divider("THIS CHAPTER"))

        # Where you left off
        v = self._section(layout, "Where you left off", "left_off")
        self.left_off_label = QLabel("")
        self.left_off_label.setWordWrap(True)
        self.left_off_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.left_off_label)
        self.recap_label = QLabel("")
        self.recap_label.setWordWrap(True)
        self.recap_label.setStyleSheet("color: #4338ca;")
        v.addWidget(self.recap_label)

        # Notes
        v = self._section(layout, "Notes as you write", "notes")
        self.notes_status = _small("Notes appear here when you finish a paragraph.")
        v.addWidget(self.notes_status)
        self.notes_list = QListWidget()
        self.notes_list.setWordWrap(True)
        self.notes_list.setMinimumHeight(110)
        self.notes_list.itemDoubleClicked.connect(lambda _i: self._go_to_note())
        v.addWidget(self.notes_list)
        row = QHBoxLayout()
        self.go_btn = QPushButton("Go to")
        self.go_btn.clicked.connect(self._go_to_note)
        self.fix_note_btn = QPushButton("💡 Suggest fix")
        self.fix_note_btn.setToolTip("Open Suggestions on this sentence, focused on the note")
        self.fix_note_btn.clicked.connect(self._fix_note)
        self.act_btn = QPushButton("Mark beat done")
        self.act_btn.clicked.connect(self._act_on_note)
        self.dismiss_btn = QPushButton("Dismiss")
        self.dismiss_btn.clicked.connect(self._dismiss_note)
        self.ask_btn = QPushButton("💬 Ask")
        self.ask_btn.clicked.connect(self._ask_note)
        for b in (self.go_btn, self.fix_note_btn, self.act_btn, self.ask_btn, self.dismiss_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.notes_list.currentRowChanged.connect(self._update_note_buttons)

        # Today's three fixes
        v = self._section(layout, "Today's three fixes", "fixes")
        self.fixes_btn = QPushButton("🎯 Find the three fixes that matter most")
        self.fixes_btn.clicked.connect(self.fixes_requested.emit)
        v.addWidget(self.fixes_btn)
        self.fixes_status = _small("")
        v.addWidget(self.fixes_status)
        self.fixes_list = QListWidget()
        self.fixes_list.setWordWrap(True)
        self.fixes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fixes_list.setMaximumHeight(110)
        self.fixes_list.itemDoubleClicked.connect(lambda _i: self._go_to_fix())
        self.fixes_list.currentRowChanged.connect(self._show_fix)
        v.addWidget(self.fixes_list)
        # The chosen fix: suggested rewrites, an editable preview, Accept.
        self.fix_detail = QWidget()
        outer_v, v = v, QVBoxLayout(self.fix_detail)
        v.setContentsMargins(0, 0, 0, 0)
        outer_v.addWidget(self.fix_detail)
        self.fix_options = QListWidget()
        self.fix_options.setWordWrap(True)
        self.fix_options.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fix_options.setMaximumHeight(80)
        self.fix_options.currentRowChanged.connect(self._show_fix_option)
        v.addWidget(self.fix_options)
        self.fix_option_notes = _small("", "#b45309")
        v.addWidget(self.fix_option_notes)
        self.fix_preview = QTextEdit()
        self.fix_preview.setMaximumHeight(80)
        self.fix_preview.setPlaceholderText("The sentence — pick a suggestion or edit it here, "
                                            "then Accept.")
        v.addWidget(self.fix_preview)
        row = QHBoxLayout()
        self.fix_accept_btn = QPushButton("✓ Accept")
        self.fix_accept_btn.setToolTip("Put this in place of the sentence in the chapter")
        self.fix_accept_btn.clicked.connect(self._accept_fix)
        self.fix_more_btn = QPushButton("💡 More options…")
        self.fix_more_btn.setToolTip("Open Suggestions on this sentence, focused on the problem")
        self.fix_more_btn.clicked.connect(self._more_fix)
        go = QPushButton("Go to")
        go.clicked.connect(self._go_to_fix)
        for b in (self.fix_accept_btn, self.fix_more_btn, go):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self._show_fix(-1)

        # Overly descriptive statements
        v = self._section(layout, "Overly descriptive", "overdescribed")
        self.over_status = _small("Statements that tell instead of show — “too” and “almost” "
                                  "are clues, not proof.")
        v.addWidget(self.over_status)
        self.over_btn = QPushButton("🔍 Check this chapter")
        self.over_btn.clicked.connect(self.overdescribed_requested.emit)
        v.addWidget(self.over_btn)
        self.over_list = QListWidget()
        self.over_list.setWordWrap(True)
        self.over_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.over_list.setMaximumHeight(140)
        self.over_list.itemDoubleClicked.connect(lambda _i: self._expand_flag())
        v.addWidget(self.over_list)
        row = QHBoxLayout()
        self.expand_btn = QPushButton("Expand…")
        self.expand_btn.setToolTip("Ways to expand it in your voice; accept one to put it in "
                                   "the chapter")
        self.expand_btn.clicked.connect(self._expand_flag)
        go = QPushButton("Go to")
        go.clicked.connect(self._go_to_flag)
        row.addWidget(self.expand_btn)
        row.addWidget(go)
        row.addStretch()
        v.addLayout(row)

        # Reader's eye
        v = self._section(layout, "Reader's eye", "reader")
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

        layout.addWidget(_divider("WHOLE BOOK"))

        # Story memory
        v = self._section(layout, "Story memory", "memory")
        v.addWidget(_small("Decisions you've settled. Every AI tool reads these; 📌 pinned ones "
                           "are always included; “· this chapter” ones are about this chapter."))
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

        # Personal style sheet
        v = self._section(layout, "Your style sheet", "style_sheet")
        v.addWidget(_small("Your own rules — learned from what you ignore and fix, or typed in: "
                           "“allow vethari” · “prefer grey over gray” · “avoid very” · "
                           "“keep passive voice” · or any note."))
        self.style_status = _small("", "#be185d")
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
        layout.addStretch()
        self._apply_collapsed()
        self._update_note_buttons()

    # ── Sections ─────────────────────────────────────────────────────

    def _section(self, layout, title: str, key: str) -> QVBoxLayout:
        section = CollapsibleSection(title, key)
        section.toggled.connect(self._section_toggled)
        self.sections[key] = section
        layout.addWidget(section)
        return section.body_layout

    def _apply_collapsed(self) -> None:
        from src.data import companion_state as cs
        closed = cs.collapsed_sections(self.project) if self.project is not None \
            else set(cs.DEFAULT_COLLAPSED)
        for key, section in self.sections.items():
            section.set_open(key not in closed)

    def _section_toggled(self, key: str, collapsed: bool) -> None:
        from src.data import companion_state as cs
        cs.set_section_collapsed(self.project, key, collapsed)

    def set_all_open(self, is_open: bool) -> None:
        for section in self.sections.values():
            if section.is_open() != is_open:
                section.header.setChecked(is_open)       # saves, like a click

    def open_section(self, key: str) -> None:
        section = self.sections.get(key)
        if section is not None and not section.is_open():
            section.header.setChecked(True)

    def set_chapter(self, chapter, text: str = "") -> None:
        """The chapter everything above “Whole book” is about."""
        self.chapter_text = text or ""
        if chapter is None:
            self.chapter_label.setText("")
            return
        number = getattr(chapter, "number", "") or ""
        title = getattr(chapter, "title", "") or ""
        words = len(self.chapter_text.split())
        name = " — ".join(p for p in (f"Chapter {number}" if number else "", title) if p)
        self.chapter_label.setText(f"📖 {html.escape(name or 'This chapter')}"
                                   f"<span style='color:#6b7280;font-weight:normal;"
                                   f"font-size:10px'> · {words:,} words</span>")

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
        self.sections["notes"].set_count(len(self.notes))
        self._update_note_buttons()

    def _current_note(self):
        row = self.notes_list.currentRow()
        return self.notes[row] if 0 <= row < len(self.notes) else None

    def _update_note_buttons(self, *_):
        note = self._current_note()
        self.go_btn.setEnabled(note is not None)
        self.fix_note_btn.setEnabled(note is not None)
        self.ask_btn.setEnabled(note is not None)
        self.dismiss_btn.setEnabled(note is not None)
        self.act_btn.setVisible(note is not None and bool(note.action))

    def _go_to_note(self):
        note = self._current_note()
        if note is not None and note.excerpt:
            self.jump_requested.emit(note.excerpt)

    def _fix_note(self):
        note = self._current_note()
        if note is not None:
            self.note_fix_requested.emit(note)

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
        self._apply_collapsed()
        self.refresh_memory()
        self.refresh_style_sheet()

    # ── Today's three fixes ─────────────────────────────────────────

    def set_fixes_busy(self, message: str = "Looking…") -> None:
        self.fixes_btn.setEnabled(False)
        self.fixes_list.clear()
        self.fixes_list.addItem(message)
        self.fixes_status.setText("")
        self._show_fix(-1)

    def set_fixes(self, fixes, status: str = "") -> None:
        self.fixes_btn.setEnabled(True)
        self.fixes = list(fixes or [])
        self.fixes_list.clear()
        for n, f in enumerate(self.fixes, 1):
            item = QListWidgetItem(f"{n}. {f.text}" + (f"\n   → {f.why}" if f.why else ""))
            item.setToolTip(f.excerpt)
            self.fixes_list.addItem(item)
        if not self.fixes and fixes is not None:
            self.fixes_list.addItem("Nothing flagged — nice work.")
        self.sections["fixes"].set_count(len(self.fixes))
        self.fixes_status.setText(status)
        if self.fixes:
            self.fixes_list.setCurrentRow(0)
        else:
            self._show_fix(-1)

    def set_fix_options(self, options_by_fix: dict, status: str = "") -> None:
        """Suggested rewrites arrived (fix index → [FixOption])."""
        for i, options in (options_by_fix or {}).items():
            if 0 <= i < len(self.fixes) and options:
                self.fixes[i].options = options
        self.fixes_status.setText(status)
        self._show_fix(self.fixes_list.currentRow())

    def current_fix(self):
        row = self.fixes_list.currentRow()
        return self.fixes[row] if 0 <= row < len(self.fixes) else None

    def _show_fix(self, row: int) -> None:
        fix = self.fixes[row] if 0 <= row < len(self.fixes) else None
        self.fix_options.clear()
        self.fix_preview.clear()
        self.fix_option_notes.setText("")
        for o in (fix.options if fix else []):
            fit = f" · voice {o.voice_fit:.0%}" if o.voice_fit is not None else ""
            tag = "✨ suggested" if o.by_ai else "quick fix (no AI)"
            item = QListWidgetItem(f"{tag}{fit}{' ⚠' if o.notes else ''}: {o.text}")
            item.setToolTip(o.why or o.text)
            self.fix_options.addItem(item)
        has = fix is not None
        self.fix_detail.setVisible(has)
        self.fixes_list.setVisible(bool(self.fixes) or self.fixes_list.count() > 0)
        self.fix_options.setVisible(bool(fix and fix.options))
        self.fix_preview.setEnabled(has)
        self.fix_accept_btn.setEnabled(has)          # your own edit counts too
        self.fix_more_btn.setEnabled(has)
        if fix and fix.options:
            self.fix_options.setCurrentRow(0)
        elif fix:
            self.fix_preview.setPlainText(fix.sentence or "")

    def _show_fix_option(self, row: int) -> None:
        fix = self.current_fix()
        if fix is None or not (0 <= row < len(fix.options)):
            return
        o = fix.options[row]
        self.fix_preview.setPlainText(o.text)
        self.fix_accept_btn.setEnabled(True)
        self.fix_option_notes.setText("⚠ This rewrite " + "; ".join(o.notes) + "."
                                      if o.notes else "")

    def _accept_fix(self) -> None:
        fix = self.current_fix()
        text = self.fix_preview.toPlainText().strip()
        if fix is not None and text:
            self.fix_accepted.emit(fix, text)

    def _more_fix(self) -> None:
        fix = self.current_fix()
        if fix is not None:
            self.fix_more_requested.emit(fix)

    def remove_fix(self, fix, message: str = "") -> None:
        if fix in self.fixes:
            self.fixes.remove(fix)
        self.set_fixes(self.fixes, message)

    def _go_to_fix(self):
        row = self.fixes_list.currentRow()
        if 0 <= row < len(self.fixes) and self.fixes[row].excerpt:
            self.jump_requested.emit(self.fixes[row].excerpt)

    # ── Overly descriptive ─────────────────────────────────────────

    def set_overdescribed(self, flags, status: str = "", busy: bool = False) -> None:
        self.over_btn.setEnabled(not busy)
        if busy:
            self.over_status.setText(status or "Checking…")
            return
        self.flags = list(flags or [])
        self.over_list.clear()
        for f in self.flags:
            cues = ", ".join(c.phrase.strip() for c in f.cues[:2])
            mark = "✨ " if f.source in ("ai", "both") else ""
            item = QListWidgetItem(f"{mark}{_short_text(f.text, 90)}"
                                   + (f"\n   ({cues})" if cues else ""))
            item.setToolTip(f.reason or f.text)
            self.over_list.addItem(item)
        self.sections["overdescribed"].set_count(len(self.flags))
        self.expand_btn.setEnabled(bool(self.flags))
        self.over_status.setText(status or ("Nothing reads as overly descriptive." if not
                                            self.flags else ""))

    def _current_flag(self):
        row = self.over_list.currentRow()
        if not (0 <= row < len(self.flags)):
            row = 0 if self.flags else -1
        return self.flags[row] if row >= 0 else None

    def _expand_flag(self) -> None:
        flag = self._current_flag()
        if flag is not None:
            self.expand_requested.emit(flag)

    def _go_to_flag(self) -> None:
        flag = self._current_flag()
        if flag is not None:
            self.jump_requested.emit(flag.text)

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
        here = self._memory_in_chapter(entries)
        entries.sort(key=lambda e: (e.status != "suggested", e.id not in here, not e.pinned))
        self._memory_ids = []
        for e in entries:
            mark = "📌 " if e.pinned else ("💡 suggested: " if e.status == "suggested" else "")
            item = QListWidgetItem(mark + e.text + (" · this chapter" if e.id in here else ""))
            if e.status == "suggested":
                item.setForeground(Qt.GlobalColor.darkYellow)
            self.memory_list.addItem(item)
            self._memory_ids.append(e.id)

    def _memory_in_chapter(self, entries) -> set:
        """Entries that share a name or two words with this chapter."""
        if not self.chapter_text.strip():
            return set()
        from src.ai.story_memory import _words
        words = _words(self.chapter_text)
        names = {w.lower() for c in getattr(self.project, "characters", None) or []
                 for w in (c.name or "").split() if len(w) > 2}
        out = set()
        for e in entries:
            shared = _words(e.text) & words
            if len(shared) >= 2 or shared & names:
                out.add(e.id)
        return out

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


def _short_text(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── Banner + controller (wired into ChapterEditor) ───────────────────

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QFrame, QToolButton


def close_button(tooltip: str, color: str = "#4b5563", hover: str = "#e5e7eb",
                 label: str = "✕") -> QToolButton:
    """A small, always-visible ✕. A QToolButton, so the app-wide
    QPushButton style (padding, blue fill) can't squeeze the glyph out."""
    btn = QToolButton()
    btn.setText(label)
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if label == "✕":
        btn.setFixedSize(22, 22)
    else:
        btn.setFixedHeight(22)
    btn.setStyleSheet(f"QToolButton {{ border: none; background: transparent; color: {color};"
                      f" font-size: 12px; font-weight: bold; padding: 0 4px; }}"
                      f"QToolButton:hover {{ background: {hover}; border-radius: 3px; }}")
    return btn


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
        self.details_btn = QPushButton("Details")
        self.details_btn.setToolTip("Show or hide the Companion tab in the side panel")
        self.details_btn.setStyleSheet("QPushButton { font-size: 10px; padding: 1px 8px;"
                                       " min-height: 18px; }")
        self.details_btn.clicked.connect(self.open_requested.emit)
        row.addWidget(self.details_btn)
        self.close_btn = close_button("Hide this line (it comes back next time you open "
                                      "the chapter)", "#3730a3", "#c7d2fe")
        self.close_btn.clicked.connect(self.hide)
        row.addWidget(self.close_btn)
        self.hide()

    def set_details_open(self, is_open: bool) -> None:
        self.details_btn.setText("Hide details" if is_open else "Details")

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
        self.panel.note_fix_requested.connect(self.suggest_note_fix)
        self.panel.fix_accepted.connect(self.accept_fix)
        self.panel.fix_more_requested.connect(self.more_fix_options)
        self.panel.overdescribed_requested.connect(self.check_overdescribed)
        self.panel.expand_requested.connect(self.expand_flag)
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
        self.panel.set_chapter(self.chapter, text)
        self.panel.set_project(self.project)
        self.panel.set_notes([], "Notes appear here when you finish a paragraph.")
        self.panel.set_fixes(None, "")           # nothing searched yet
        self._quick_overdescribed(text)
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
        """Details: show the Companion tab, or hide the panel if it's showing."""
        if self.ce.side_panel_open() and self.ce.right_panel.currentWidget() is self.panel:
            self.ce._hide_right_panel()
        else:
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
        self.panel.set_chapter(self.chapter, text)
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

    def _voice_for(self, text: str):
        if self._voice is None and self.project is not None:
            from src.ai.writer_voice import project_voice
            self._voice = project_voice(self.project, self.chapter, text)
        return self._voice

    def _taste(self, text: str) -> str:
        """Rewrites the writer rated in Suggestions and Rephrase."""
        try:
            from src.ai.rewrite_quality import examples_prompt
            path = str(getattr(self.project, "project_path", "") or "")
            return examples_prompt(text[:2000], path)
        except Exception:
            return ""

    def find_three_fixes(self) -> None:
        """The three fixes that matter most, each with suggested rewrites:
        the model (local, server or cloud) picks them with the writer's
        taste and voice and writes the rewrites like Suggestions does;
        without one, the heaviest flags with the editor's own fixes."""
        from src.ai import companion, overdescription as od
        hl = self.ce.editor.writing_highlighter
        if hl.phase == "drafting":
            self.ce.editor._apply_phase("revising")       # asking for fixes = revising
        else:
            hl.rehighlight()
        text = self.ce.editor.toPlainText()
        flags = self.panel.flags or od.scan(text)
        candidates = companion.fix_candidates(hl, self.ce.editor.document(), self.panel.notes,
                                              flags, text)
        if not candidates:
            self.panel.set_fixes([])
            return
        project, chapter = self.project, self.chapter
        context = companion.judge_context(project, chapter, text[:4000]) \
            if project is not None else ""
        voice = self._voice_for(text)
        if voice is not None and hasattr(voice, "to_critique_prompt"):
            context = (context + "\n\n" + voice.to_critique_prompt()).strip()
        taste = self._taste(text)
        self.panel.set_fixes_busy()

        def work():
            llm = self._llm()
            if llm is None:
                return companion.three_fixes_quick(candidates), False
            return companion.three_fixes(llm, candidates, context, taste), True

        def done(result, error):
            if not result:
                self.panel.set_fixes([], error or "")
                return
            fixes, used_model = result
            self.panel.set_fixes(fixes, "Writing suggested fixes in your voice…"
                                 if used_model and fixes else
                                 "" if used_model else
                                 "Quick picks (no AI) — set up a local, server or cloud model "
                                 "for suggested rewrites.")
            if used_model and fixes:
                self._suggest_fix_rewrites(fixes, text)

        run_background(work, done)

    def _suggest_fix_rewrites(self, fixes, text: str) -> None:
        from src.ai import companion
        project, chapter = self.project, self.chapter
        voice = self._voice

        def work():
            llm = self._llm()
            if llm is None:
                return {}
            from src.ai.chapter_analysis_agent import is_local_llm
            compact = is_local_llm(llm)
            out = {}
            for i, fix in enumerate(fixes):
                try:
                    out[i] = companion.suggest_fix_options(llm, project, chapter, text, fix,
                                                           voice, compact)
                except Exception as e:
                    print(f"[companion] fix rewrite failed: {e}")
            return out

        def done(options, error):
            for i, found in (options or {}).items():
                if found:
                    fixes[i].options = found        # by object: accepted fixes may be gone
            if not any(f is p for f in fixes for p in self.panel.fixes):
                return                    # a newer search replaced these
            got = sum(1 for o in (options or {}).values() if any(x.by_ai for x in o))
            self.panel.set_fix_options({}, (
                "Suggested fixes are ready — pick one, edit it if you like, then Accept."
                if got else (error or "No suggested rewrites — try 💡 More options…")))

        run_background(work, done)

    def _span_for(self, paragraph: int, excerpt: str, sentence: str = ""):
        from src.ai import companion
        return companion.locate_sentence(self.ce.editor.toPlainText(), paragraph, excerpt,
                                         sentence)

    def accept_fix(self, fix, replacement: str) -> None:
        span = self._span_for(fix.paragraph, fix.excerpt, fix.sentence)
        if span is None:
            self.panel.fixes_status.setText("That sentence has changed — find the fixes again.")
            return
        text = self.ce.editor.toPlainText()
        original = text[span[0]:span[1]]
        if " ".join(original.split()) == " ".join(replacement.split()):
            self.panel.fixes_status.setText("No change — edit the sentence above or pick a "
                                            "suggestion first.")
            return
        if not self.ce._replace_span(text, span[0], span[1], replacement, "Companion"):
            return
        from src.ai.rewrite_quality import log_rated_rewrite
        log_rated_rewrite(original, replacement, "good", accepted=True,
                          project_path=str(getattr(self.project, "project_path", "") or ""),
                          style="fix")
        self.panel.remove_fix(fix, "Fixed. Your choice teaches future suggestions.")

    def more_fix_options(self, fix) -> None:
        span = self._span_for(fix.paragraph, fix.excerpt, fix.sentence)
        if span is None:
            self.panel.fixes_status.setText("That sentence has changed — find the fixes again.")
            return
        if self.ce.suggest_for_span(span[0], span[1], focus=fix.text):
            self.panel.remove_fix(fix, "Fixed with Suggestions.")

    def suggest_note_fix(self, note) -> None:
        span = self._span_for(note.paragraph, note.excerpt)
        if span is None:
            self.panel.notes_status.setText("That text has changed since the note.")
            return
        if self.ce.suggest_for_span(span[0], span[1], focus=note.text):
            self._on_note_dismissed(note)

    # ── overly descriptive ───────────────────────────────────────────

    def _quick_overdescribed(self, text: str) -> None:
        from src.ai import overdescription as od
        review = od.review_chapter(text, None)
        self.panel.set_overdescribed(
            review.flags, "Word scan (no AI)." + (" Check this chapter to have the model "
                                                  "judge them and look for subtler ones."
                                                  if _companion_ai_enabled() else "")
            if review.flags else "")

    def check_overdescribed(self) -> None:
        from src.ai import overdescription as od
        text = self.ce.editor.toPlainText()
        voice = self._voice_for(text)
        self.panel.set_overdescribed([], "Checking…", busy=True)

        def work():
            llm = self._llm()
            return od.review_chapter(text, llm, voice)

        def done(review, error):
            if review is None:
                self.panel.set_overdescribed([], error or "Couldn't check the chapter.")
                return
            note = ("Judged by the AI" + (f"; {len(review.cleared)} word-scan hits were fine."
                                         if review.cleared else ".")) if review.used_ai else \
                "Word scan (no AI) — set up a local, server or cloud model for judgement."
            self.panel.set_overdescribed(review.flags, note if review.flags or review.used_ai
                                         else "")

        run_background(work, done)

    def expand_flag(self, flag) -> None:
        text = self.ce.editor.toPlainText()
        hits = [m.start() for m in re.finditer(re.escape(flag.text), text)] if flag.text else []
        if not hits:
            self.panel.over_status.setText("That statement has changed — check again.")
            return
        start = min(hits, key=lambda i: abs(i - flag.start))
        if self.ce.expand_statement(start, start + len(flag.text)):
            self.panel.set_overdescribed([f for f in self.panel.flags if f is not flag],
                                         "Expanded.")

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
