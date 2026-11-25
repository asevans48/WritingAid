"""The scorecard: the Critique tab's front page (piece 2.1).

**Path to publish** for one manuscript at a time: chapters down the side,
checks across the top grouped by stage, each cell coloured by its status and
showing a count, and one figure for the book, "ready for readers". It reads
``readiness.book_report`` (1.2b) in the background and shows scan results.

The detailed critique is unchanged and one click away: its set-up (scope,
reports, writing context) folds into one "Detailed critique" section under
the scorecard, which remembers whether it is open; Run Critique, the
results, rating, saving, loading and exporting stay where they were.
Double-clicking a chapter's row prepares a detailed critique of that
chapter.

``install_scorecard`` does the wiring, so the Critique tab's own file only
gains the lines that call it.
"""

from __future__ import annotations

import textwrap
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.ui.ui_kit import (
    PALETTE, STAGE_COLOURS, CollapsibleSection, empty_state, primary_button, relayout,
    size_class,
)

HONEST_LINE = ("This covers the mechanics an edit would fix. It cannot tell you whether the "
               "story works, or whether an agent or publisher will take it: that turns on "
               "taste, comparable books and the market.")
SETUP_TITLE = "Detailed critique: scope, reports and writing context"
SETUP_KEY = "critique/setup_open"

STATUS_COLOURS = {
    "ready": PALETTE["success"],
    "needs_work": PALETTE["warning"],
    "problem": PALETTE["error"],
    "needs_model": PALETTE["border_strong"],
    "could_not_check": PALETTE["border_strong"],
    "info": PALETTE["info"],
}
LEGEND = (("ready", "Ready"), ("needs_work", "Needs work"), ("problem", "Problem"),
          ("needs_model", "Needs a model (not counted)"),
          ("could_not_check", "Could not check (not counted)"))
_WORST = ("problem", "needs_work", "could_not_check", "needs_model", "ready", "info")


def tint(colour: str, amount: float = 0.72) -> QColor:
    """``colour`` mixed with white (cell backgrounds stay readable)."""
    c = QColor(colour)
    return QColor(round(c.red() + (255 - c.red()) * amount),
                  round(c.green() + (255 - c.green()) * amount),
                  round(c.blue() + (255 - c.blue()) * amount))


class ScorecardWidget(QWidget):
    chapter_chosen = pyqtSignal(object, str)      # scope, chapter id (double-click)
    chapter_selected = pyqtSignal(object, str)    # scope, chapter id (click)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Any = None
        self.report = None                         # the BookReport shown
        self._reports: Dict[str, Any] = {}         # scope key → BookReport
        self._task = None
        self._live_source = None                   # the manuscript editor
        self._expanded: Set[str] = set()           # stages flipped from their default
        self._narrow = False
        self._stale = True
        self._selected: Optional[str] = None       # chapter id whose issues are shown
        self._selected_checks: Optional[List[str]] = None   # None: every check
        self._column_checks: List[List[str]] = []  # check names under each column
        self._followed: Optional[str] = None       # the chapter last followed from Write
        self.llm_factory = None                    # () → the analysis model, or None (2.3)
        self._model_run = False
        from PyQt6.QtCore import QTimer
        self._bg_timer = QTimer(self)              # judge changed chapters while writing (2.3)
        self._bg_timer.setInterval(5 * 60 * 1000)
        self._bg_timer.timeout.connect(self._background_tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel("Path to publish")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {PALETTE['ink']};")
        top.addWidget(title)
        self.manuscript_combo = QComboBox()
        self.manuscript_combo.setToolTip("The main manuscript or a novella: each has its own "
                                         "scorecard and its own figure.")
        self.manuscript_combo.currentIndexChanged.connect(self._on_manuscript)
        top.addWidget(self.manuscript_combo)
        top.addStretch()
        # Judging with the model is the writer's choice (2.3): a link beside the
        # button, shown when a model is set up and the book isn't fully judged.
        self.model_link = QLabel("<a href='model'>Check the book with the model…</a>")
        self.model_link.setTextFormat(Qt.TextFormat.RichText)
        self.model_link.setToolTip("Have the model judge every flag, chapter by chapter, in the "
                                   "background. You'll see an estimate first.")
        self.model_link.linkActivated.connect(self._on_note_link)
        self.model_link.setVisible(False)
        top.addWidget(self.model_link)
        self.check_btn = primary_button("Check readiness")
        self.check_btn.setToolTip("Check every chapter of this manuscript. Chapters you "
                                  "haven't changed since the last check are not checked again.")
        self.check_btn.clicked.connect(self._on_check_clicked)
        top.addWidget(self.check_btn)
        outer.addLayout(top)

        # Progress while the model judges the book (2.3): hidden otherwise.
        self.progress_row = QWidget()
        prow = QHBoxLayout(self.progress_row)
        prow.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        prow.addWidget(self.progress_bar, 2)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {PALETTE['ink_soft']};")
        prow.addWidget(self.progress_label, 3)
        self.progress_row.setVisible(False)
        outer.addWidget(self.progress_row)

        figure_row = QHBoxLayout()
        self.figure_label = QLabel("—")            # the verdict (a finish line, not a score)
        self.figure_label.setTextFormat(Qt.TextFormat.RichText)
        self.figure_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {PALETTE['ink']};")
        figure_row.addWidget(self.figure_label)
        words = QVBoxLayout()
        words.setSpacing(0)
        self.figure_caption = QLabel("")           # what stands between the book and the line
        self.figure_caption.setWordWrap(True)
        self.figure_caption.setStyleSheet(f"font-weight: bold; color: {PALETTE['ink_soft']};")
        words.addWidget(self.figure_caption)
        honest = QLabel(HONEST_LINE)
        honest.setWordWrap(True)
        honest.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
        words.addWidget(honest)
        figure_row.addLayout(words, 1)
        self.trend_label = QLabel("")             # change since the last check, and a trend (2.4)
        self.trend_label.setStyleSheet(f"color: {PALETTE['ink_soft']}; font-size: 12px;")
        figure_row.addWidget(self.trend_label)
        outer.addLayout(figure_row)

        self.note_label = QLabel("")
        self.note_label.setTextFormat(Qt.TextFormat.RichText)
        self.note_label.linkActivated.connect(self._on_note_link)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {PALETTE['ink_soft']}; font-size: 11px;")
        outer.addWidget(self.note_label)

        self.ribbon = QLabel("")
        self.ribbon.setTextFormat(Qt.TextFormat.RichText)
        self.ribbon.setWordWrap(True)
        self.ribbon.linkActivated.connect(self._toggle_stage)
        outer.addWidget(self.ribbon)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # The chosen chapter is marked on its name, so its cells keep their colours.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        hh = self.table.horizontalHeader()
        # Column widths are set by _fit_columns (measured from the bold
        # header text, then stretched into the room there is).
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        bold = hh.font()
        bold.setBold(True)
        hh.setFont(bold)                   # the header is sized with the font it draws
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                                        | Qt.AlignmentFlag.AlignVCenter)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Each click is handled once Qt has finished with it: opening a
        # chapter or redrawing the table inside the table's own mouse
        # handling can crash the app (a crash seen on double-click).
        later = lambda fn: (lambda *a: QTimer.singleShot(0, lambda: fn(*a)))
        self.table.cellDoubleClicked.connect(later(self._fix_cell))       # to the fix (2.2)
        self.table.verticalHeader().sectionDoubleClicked.connect(later(self._choose_row))
        self.table.cellClicked.connect(later(self._on_cell))
        self.table.verticalHeader().sectionClicked.connect(
            later(lambda row: self._select_row(row, None)))
        self.table.setToolTip("Click a chapter to see what the checks found, or a cell for "
                              "one check. Double-click a cell to fix it in the chapter; "
                              "double-click a chapter's name for its detailed critique.")
        outer.addWidget(self.table)

        self.empty = empty_state("")
        outer.addWidget(self.empty)

        legend = QHBoxLayout()
        legend.setSpacing(10)
        for status, text in LEGEND:
            swatch = QLabel(f"<span style='color:{STATUS_COLOURS[status]}'>■</span> {text}")
            swatch.setStyleSheet(f"color: {PALETTE['ink_soft']}; font-size: 11px;")
            legend.addWidget(swatch)
        legend.addStretch()
        self.legend = QWidget()
        self.legend.setLayout(legend)
        outer.addWidget(self.legend)

        from src.ui.readiness_issues import ChapterIssues
        self.issues = ChapterIssues()
        self.issues.sheet_change_requested.connect(self._change_style_sheet)
        self.issues.letter_requested.connect(self._letter)
        self.issues.intended_requested.connect(self._set_intended)
        self.issues.brief_requested.connect(self._save_brief)
        self.issues.chapter_requested.connect(self._show_chapter_row)
        from src.ui import chapter_stage_ui; chapter_stage_ui.install_on_scorecard(self)   # 3.1
        self.issues.show_all_requested.connect(
            lambda: self._select_chapter(self._selected, None))
        outer.addWidget(self.issues)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-style: italic;")
        outer.addWidget(self.status_label)
        self._show_empty("Open a project to see its path to publish.")

    # ── Project and manuscripts ──────────────────────────────────

    def set_project(self, project: Any) -> None:
        """A project was opened, or its manuscripts changed."""
        if project is not self.project:
            self._reports.clear()
        self.project = project
        self._stale = True
        wanted = self.manuscript_combo.currentData()
        self.manuscript_combo.blockSignals(True)
        self.manuscript_combo.clear()
        if project is not None:
            from src.data.publishing_goal import manuscripts
            try:
                for scope, name, _ms in manuscripts(project):
                    self.manuscript_combo.addItem(name, scope or "")
            except Exception as e:
                print(f"[scorecard] {e}")
        i = self.manuscript_combo.findData(wanted if wanted is not None else "")
        self.manuscript_combo.setCurrentIndex(max(0, i))
        self.manuscript_combo.blockSignals(False)
        self.manuscript_combo.setVisible(self.manuscript_combo.count() > 1)
        if project is None:
            self._show_empty("Open a project to see its path to publish.")
        elif self.isVisible():
            self.refresh()
        else:
            self._render(self._reports.get(self._scope_key()))

    def set_live_source(self, manuscript_editor: Any) -> None:
        """Where the open chapter's live text comes from."""
        self._live_source = manuscript_editor

    def scope(self) -> Optional[str]:
        return self.manuscript_combo.currentData() or None

    def _scope_key(self) -> str:
        return self.scope() or "main"

    def _on_manuscript(self, _i: int) -> None:
        report = self._reports.get(self._scope_key())
        self._render(report)
        if report is None and self.project is not None:
            self.refresh()

    def showEvent(self, event):
        """Re-check whenever the tab is shown: the writing may have changed.
        Unchanged chapters come from the cache, so this is quick."""
        super().showEvent(event)
        if self.project is not None:
            self._follow_writing()
        if self.project is not None and self._task is None:
            self.refresh()

    def _follow_writing(self) -> None:
        """Start on the manuscript and chapter open in Write, when that
        changed since the last look; otherwise keep the writer's pick."""
        ce = getattr(self._live_source, "current_chapter_editor", None)
        cid = getattr(getattr(ce, "chapter", None), "id", None)
        if not cid or cid == self._followed:
            return
        self._followed = cid
        scope = None
        try:
            scope, _ = self.project.find_chapter_with_scope(cid)
        except Exception:
            scope = getattr(self.project, "active_subproject_id", None)
        i = self.manuscript_combo.findData(scope or "")
        if i >= 0 and i != self.manuscript_combo.currentIndex():
            self.manuscript_combo.blockSignals(True)
            self.manuscript_combo.setCurrentIndex(i)
            self.manuscript_combo.blockSignals(False)
            self._render(self._reports.get(self._scope_key()))
        self._selected, self._selected_checks = cid, None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = size_class(self) == "narrow"
        if narrow != self._narrow:
            self._narrow = narrow
            self._expanded.clear()
            if self.report is not None:
                self._render(self.report)
        elif self.report is not None and self.table.columnCount():
            self._fit_columns()
            self._fit_height()

    # ── Checking ─────────────────────────────────────────────────

    def _live(self):
        """({chapter id: live text}, the open editor's highlighter or None),
        read on the GUI thread."""
        ce = getattr(self._live_source, "current_chapter_editor", None)
        try:
            return ({ce.chapter.id: ce.editor.toPlainText()},
                    ce.editor.writing_highlighter)
        except Exception:
            return {}, None

    def _on_check_clicked(self) -> None:
        if self._model_run and self._task is not None:
            self._task.stop()                         # Stop: finished chapters are kept
            self.status_label.setText("Stopped. Chapters already judged are kept.")
            self._end_model_run()
            return
        self.refresh(force=False)

    def _on_note_link(self, href: str) -> None:
        if href == "model":
            self.start_model_check()

    def start_model_check(self) -> None:
        """Estimate, ask, then judge the book with the model (2.3)."""
        from src.ai import readiness as rd
        from src.ui import scorecard_model_run as smr
        if self.project is None:
            return
        texts, _hl = self._live()
        todo, total = rd.model_work(self.project, self.scope(), texts)
        start, keep = smr.confirm(self, todo, total)
        smr.set_background(keep)
        self._sync_background()
        if start:
            self.refresh(judge=True)

    def _sync_background(self) -> None:
        from src.ui import scorecard_model_run as smr
        if smr.background_on() and self.llm_factory is not None:
            self._bg_timer.start()
        else:
            self._bg_timer.stop()

    def _background_tick(self) -> None:
        """Every few minutes, when chosen: judge chapters changed since."""
        from src.ai import readiness as rd
        from src.ui import scorecard_model_run as smr
        if (self.project is None or self._task is not None or self.llm_factory is None
                or not smr.background_on() or not smr.ai_available()):
            return
        texts, _hl = self._live()
        if rd.model_work(self.project, self.scope(), texts)[0]:
            self.refresh(judge=True, quiet=True)

    def _end_model_run(self) -> None:
        self._model_run = False
        self.progress_row.setVisible(False)
        self.model_link.setVisible(False)          # the next render decides
        self.check_btn.setText("Check readiness")
        self.check_btn.setEnabled(True)

    def refresh(self, force: bool = False, judge: bool = False, quiet: bool = False) -> None:
        """Check the chosen manuscript in the background (cached chapters
        are not checked again). ``judge``: with the model (2.3)."""
        if self.project is None:
            return
        if self._task is not None:
            self._task.stop()
        from src.ui.background import run_background
        from src.utils.editor_flags import FlagState
        project, scope = self.project, self.scope()
        texts, hl = self._live()
        base = None
        if hl is not None:
            try:
                base = FlagState.from_highlighter(hl)     # ignored words, LanguageTool results
            except Exception as e:
                print(f"[scorecard] editor settings unavailable: {e}")
        self._stale = False
        factory = self.llm_factory if judge else None
        self._model_run = bool(judge)
        if judge:
            from src.ai import readiness as _rd
            try:
                self._run_todo = _rd.model_work(project, scope, texts)[0]
            except Exception:
                self._run_todo = 0
            self.progress_bar.setRange(0, 0)           # busy until the first chapter starts
            self.progress_bar.setFormat("Starting the model…")
            self.progress_label.setText("")
            self.progress_row.setVisible(True)
            self.model_link.setVisible(False)
            self.check_btn.setText("Stop")
            self.check_btn.setEnabled(True)
            self.status_label.setText("Judging in the background…" if quiet else
                                      "Starting the model…")
        else:
            self.check_btn.setEnabled(False)
            self.status_label.setText("Checking…")

        def work(task):
            from src.ai import readiness as rd
            scanner = rd.Scanner(project, base)
            llm = None
            if factory is not None:
                try:
                    llm = factory()
                except Exception as e:
                    print(f"[scorecard] model unavailable: {e}")
                if llm is None:
                    task.report("No model is set up, so this is a scan.")
            verb = "Judging" if llm is not None else "Checking"

            timing = {"last": None, "slow": 0, "slow_time": 0.0}

            def progress(done, total, title):
                import time as _t
                now = _t.monotonic()
                if timing["last"] is not None:
                    took = now - timing["last"]
                    if took > 1.0:                    # the model worked on it (not cached)
                        timing["slow"] += 1
                        timing["slow_time"] += took
                timing["last"] = now
                if title:
                    task.report(f"{verb} {title}… ({done + 1} of {total})")
                if llm is not None:
                    task.send(("progress", done, total, title, timing["slow"],
                               timing["slow_time"]))
            report = rd.book_report(project, scope, texts=texts, scanner=scanner,
                                    use_cache=not force, progress=progress,
                                    stop=lambda: task.stopping, llm=llm,
                                    partial=task.send if llm is not None else None)
            report.no_model = factory is not None and llm is None
            return report

        self._task = run_background(work, self._done, on_progress=self.status_label.setText,
                                    on_data=self._partial, owner=self, label="scorecard")

    def _partial(self, report) -> None:
        """A chapter finished: show the grid so far, keeping the writer's place.
        (Progress updates come through here too.)"""
        if isinstance(report, tuple) and report and report[0] == "progress":
            self._show_progress(*report[1:])
            return
        if report is not None and (report.scope or "main") == self._scope_key():
            self._render(report)

    def _show_progress(self, done: int, total: int, title: str, slow: int,
                       slow_time: float) -> None:
        """"Chapter 3 of 40 · about 12 minutes left", and the chapter being judged.
        The time left counts only chapters the model works on (cached ones
        are instant)."""
        self.progress_row.setVisible(True)
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(min(done, total))
        left = ""
        remaining = max(0, getattr(self, "_run_todo", total) - slow)
        if slow and remaining and done < total:
            seconds = slow_time / slow * remaining
            left = (" · under a minute left" if seconds < 60 else
                    f" · about {round(seconds / 60)} minute{'s' if round(seconds / 60) != 1 else ''} left"
                    if seconds < 5400 else f" · about {seconds / 3600:.1f} hours left")
        elif done < total and not slow:
            left = " · working out the time left…"
        shown = min(done + 1, total) if done < total else total
        self.progress_bar.setFormat(f"Chapter {shown} of {total}{left}")
        self.progress_label.setText(f"Judging “{title}”…" if title and done < total
                                    else "Finishing the whole-book checks…")

    def _done(self, report, error: str) -> None:
        self._task = None
        was_model = self._model_run
        self._end_model_run()
        if error or report is None:
            self.status_label.setText(f"Couldn't check: {error or 'no result'}")
            return
        self.status_label.setText(
            "No model is set up (or AI is off), so this was a scan." if getattr(report, "no_model", False)
            else "Judged by the model." if was_model and report.tier == "model" else "")
        self._reports[(report.scope or "main")] = report
        if (report.scope or "main") == self._scope_key():
            self._render(report)
        if was_model:
            from src.ui import scorecard_model_run as smr
            smr.show_corrections_in_editor(self)

    # ── Drawing ──────────────────────────────────────────────────

    def _show_empty(self, text: str) -> None:
        self.report = None
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.setVisible(False)
        self.legend.setVisible(False)
        self.issues.setVisible(False)
        self.ribbon.setText("")
        self.figure_label.setText("—")
        self.figure_label.setToolTip("")
        self.figure_caption.setText("")
        self.trend_label.setText("")
        self.note_label.setText("")
        self.empty.setText(text)
        self.empty.setVisible(True)

    def _render(self, report) -> None:
        if report is None:
            if self.project is not None:
                self._show_empty("Click “Check readiness” to check this manuscript.")
            return
        if not report.chapters:
            name = report.name or "This manuscript"
            self._show_empty(f"{name} has no chapters yet. Write a chapter, then check "
                             "readiness here.")
            return
        self.report = report
        self.empty.setVisible(False)
        self.table.setVisible(True)
        self.legend.setVisible(True)
        self.issues.setVisible(True)
        self._show_verdict(report)
        self._show_trend(report)
        self.note_label.setText(self._note(report))
        self._fill_grid(report)
        self._restore_selection()

    SPARK = "▁▂▃▄▅▆▇█"

    VERDICT_COLOURS = {"ready": "success", "nearly": "warning", "revise": "error",
                       "unchecked": "ink_faint"}

    def _show_verdict(self, report) -> None:
        """Ready to send / Nearly there / Needs a revision pass, coloured, with
        what stands in the way. The old percentage is in the tooltip."""
        from src.ai.readiness import verdict
        v = verdict(report)
        colour = PALETTE[self.VERDICT_COLOURS.get(v.level, "ink")]
        self.figure_label.setText(f"<span style='color:{colour}'>●</span> {v.title}")
        self.figure_caption.setText(v.detail)
        pct = f"{round(report.readiness * 100)}%" if report.cells else "—"
        self.figure_label.setToolTip(
            "Major issues come first: spelling and grammar left, character disconnects, "
            "plot jumps and continuity. Then the other factors (pacing, dialogue, the "
            "opening pages, consistency). Style is optional polish and never blocks, as "
            "published books have polish left too.\n\n"
            f"Ready for readers: {pct} of the checks that count are ready "
            "(needs work counts half).")

    def _show_trend(self, report) -> None:
        """"▼ 3 major issues since 21 Nov" and a small trend of the last 30
        checks (fewer is better)."""
        from datetime import date
        from src.ai.readiness import majors_change
        hist = [e for e in (report.history or []) if "majors" in e][-30:]
        text, tip = "", ""
        change = majors_change(report)
        if change is not None:
            delta, day = change
            try:
                d = date.fromisoformat(day)
                when = f"{d.day} {d.strftime('%b')}"
            except Exception:
                when = day
            n = abs(delta)
            noun = f"major issue{'s' if n != 1 else ''}"
            if delta < 0:
                text, colour = f"▼ {n} {noun} since {when}", PALETTE["success"]
            elif delta > 0:
                text, colour = f"▲ {n} {noun} since {when}", PALETTE["error"]
            else:
                text, colour = f"＝ no change since {when}", PALETTE["ink_soft"]
            text = f"<span style='color:{colour}'>{text}</span>"
        if len(hist) >= 2:
            vals = [e["majors"] for e in hist]
            lo, hi = min(vals), max(vals)
            spark = "".join(self.SPARK[0 if hi == lo else
                                       round((v - lo) / (hi - lo) * (len(self.SPARK) - 1))]
                            for v in vals)
            text = (text + "&nbsp;&nbsp;" if text else "") + \
                f"<span style='color:{PALETTE['primary']}; letter-spacing:1px'>{spark}</span>"
            tip = "\n".join(f"{e['date']}: {e['majors']} major issue"
                            f"{'s' if e['majors'] != 1 else ''}" for e in hist)
        self.trend_label.setText(text)
        self.trend_label.setToolTip(("Major issues, one count a day (the latest check of each "
                                     "day); lower is better:\n" + tip) if tip else
                                    "Check on another day to see the change.")

    def _note(self, report) -> str:
        from src.ai import readiness as rd
        bits = [{"scan": "A scan: no model judged these results.",
                 "mixed": "Partly judged by a model: chapters changed since are a scan.",
                 }.get(report.tier, "Judged by a model (one reader's view): what it cleared doesn't count.")]
        left = {n: why for n, why in report.left_out.items() if why != "information only"}
        if left:
            names = [f"{rd.REGISTRY[n].label} ({why})" if n in rd.REGISTRY else n
                     for n, why in left.items()]
            bits.append("Not counted yet: " + "; ".join(names) + ".")
        if not report.cells:
            bits.append("Nothing counts toward the verdict yet.")
        if not report.complete:
            bits.append("The check stopped part way; click Check readiness to finish.")
        if not report.saved:
            bits.append("These results weren't saved: the readiness file is from a newer "
                        "version of the app, or couldn't be written.")
        import html as _html
        from src.ui import scorecard_model_run as smr
        self.model_link.setVisible(self.llm_factory is not None and smr.ai_available()
                                   and report.tier != "model" and not self._model_run)
        return _html.escape(" ".join(bits))

    def _collapsed(self, stage: str) -> bool:
        """Stages are open on a wide window and closed on a narrow one; a
        click on a stage in the ribbon flips it."""
        return self._narrow != (stage in self._expanded)

    def _toggle_stage(self, stage: str) -> None:
        self._expanded ^= {stage}
        if self.report is not None:
            self._fill_grid(self.report)

    def _ribbon_html(self, stages_with_checks: List[str]) -> str:
        from src.ai.readiness import STAGE_LABELS, STAGES
        parts = []
        for stage in STAGES:
            colour = STAGE_COLOURS.get(stage, PALETTE["ink"])
            label = STAGE_LABELS[stage]
            if stage in stages_with_checks:
                mark = " ▸" if self._collapsed(stage) else ""
                parts.append(f"<a href='{stage}' style='color:{colour}; font-weight:bold; "
                             f"text-decoration:none'>{label}{mark}</a>")
            else:
                parts.append(f"<span style='color:{PALETTE['ink_faint']}' "
                             f"title='No checks for this stage yet'>{label}</span>")
        hint = (f"<span style='color:{PALETTE['ink_faint']}; font-size:11px'>"
                "&nbsp;&nbsp;(click a stage to show or hide its checks)</span>")
        return " › ".join(parts) + hint

    def _fill_grid(self, report) -> None:
        from src.ai import readiness as rd
        from src.ui import chapter_stage_ui
        g = rd.grid(report)
        groups = g.stages()
        self.ribbon.setText(self._ribbon_html([s for s, _ in groups]))
        # Columns: each check, or one per collapsed stage.
        columns: List[tuple] = []            # ("check", spec) | ("stage", stage, [specs])
        for stage, specs in groups:
            if self._collapsed(stage):
                columns.append(("stage", stage, specs))
            else:
                columns.extend(("check", spec) for spec in specs)
        self._column_checks = [[col[1].name] if col[0] == "check" else [s.name for s in col[2]]
                               for col in columns]
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setRowCount(len(g.rows))
        for c, col in enumerate(columns):
            if col[0] == "check":
                spec = col[1]
                item = QTableWidgetItem(f"{rd.STAGE_LABELS.get(spec.stage, spec.stage)}\n{spec.label}")
                item.setData(Qt.ItemDataRole.UserRole,
                             (rd.STAGE_LABELS.get(spec.stage, spec.stage), spec.label))
                tip = [spec.description]
                if spec.threshold is not None:
                    tip.append(spec.threshold.describe())
                if spec.name in report.left_out:
                    tip.append(f"Not in the figure: {report.left_out[spec.name]}.")
                item.setToolTip("\n\n".join(t for t in tip if t))
                stage = spec.stage
            else:
                stage, specs = col[1], col[2]
                item = QTableWidgetItem(f"{rd.STAGE_LABELS.get(stage, stage)} ▸\n"
                                        f"{len(specs)} check{'s' if len(specs) != 1 else ''}")
                item.setToolTip("Click the stage in the ribbon above to see each check.")
            item.setForeground(QColor(STAGE_COLOURS.get(stage, PALETTE["ink"])))
            self.table.setHorizontalHeaderItem(c, item)
        self._rows = [ch for ch, _cells in g.rows]
        for r, (ch, cells) in enumerate(g.rows):
            name = f"{ch.number}. {ch.title}" if ch.number else ch.title
            head = QTableWidgetItem(chapter_stage_ui.row_name(name, ch))   # with its stage (3.1)
            if ch.chapter_id == rd.BOOK_ROW:
                font = head.font()
                font.setItalic(True)
                head.setFont(font)
                head.setToolTip(f"Checks of the whole manuscript ({ch.words:,} words). Click "
                                "to see what they found, chapter by chapter.")
            else:
                head.setToolTip(f"{name}\n{ch.words:,} words"
                                + (" · the opening chapter" if ch.is_opening else "")
                                + "\nDouble-click for this chapter's detailed critique.")
            self.table.setVerticalHeaderItem(r, head)
            by_name = {spec.name: res for spec, res in zip(g.columns, cells)}
            for c, col in enumerate(columns):
                if col[0] == "check":
                    item = self._cell(col[1], by_name.get(col[1].name))
                else:
                    item = self._stage_cell(col[1], [(s, by_name.get(s.name)) for s in col[2]])
                self.table.setItem(r, c, item)
        self._fit_columns()
        self._fit_height()

    def _fit_columns(self) -> None:
        """All columns the same width: at least wide enough for each check's
        name wrapped at about 16 letters (measured in the header's bold
        font, with its margins), stretched into the room there is up to
        about twice that. Names are then wrapped to the width they got, so
        they sit on one line whenever there's room, and the header is as
        tall as its longest name."""
        t = self.table
        hh = t.horizontalHeader()
        n = t.columnCount()
        if not n:
            return
        fm = hh.fontMetrics()
        pad = fm.horizontalAdvance("MM") + 2 * hh.style().pixelMetric(
            hh.style().PixelMetric.PM_HeaderMargin)
        heads = []
        least = fm.horizontalAdvance("0000") + pad
        for c in range(n):
            item = t.horizontalHeaderItem(c)
            parts = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not parts:                                  # a folded stage: fixed lines
                parts = (None, item.text() if item else "")
            heads.append((item, parts))
            stage, label = parts
            lines = ([stage] if stage else []) + (textwrap.wrap(label, 16) if stage
                                                  else label.split("\n"))
            least = max(least, max(fm.horizontalAdvance(x) for x in lines) + pad)
        room = t.viewport().width() or (t.width() - t.verticalHeader().width())
        width = max(least, min(room // n, int(least * 2.2)))
        most = 1
        for c, (item, (stage, label)) in enumerate(heads):
            hh.resizeSection(c, width)
            if stage:
                lines = [stage] + _wrap_to(label, fm, width - pad)
                item.setText("\n".join(lines))
            else:
                lines = label.split("\n")
            most = max(most, len(lines))
        hh.setFixedHeight(fm.lineSpacing() * most + fm.height() // 2 + 6)

    def _cell(self, spec, result) -> QTableWidgetItem:
        from src.ai.readiness import Status
        if result is None:
            item = QTableWidgetItem("")
            item.setToolTip("Not checked")
            return item
        if result.status == Status.INFO:            # information: its figure, no colour
            item = QTableWidgetItem(f"{result.measure:,.0f}" if result.measure is not None else "·")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(PALETTE["ink_soft"]))
            item.setToolTip(f"{spec.label}: information, not counted.\n{result.message}".strip())
            return item
        text = "?" if result.status == Status.COULD_NOT_CHECK else str(result.count)
        if result.status == Status.NEEDS_MODEL and not result.found:
            text = "–"                                    # not read yet: nobody has looked
        if getattr(spec, "display", "count") == "measure" and result.measure is not None \
                and result.status != Status.COULD_NOT_CHECK:
            text = f"{result.measure:g}"                  # a score, not a count
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setBackground(tint(STATUS_COLOURS.get(result.status, PALETTE["border"])))
        item.setForeground(QColor(PALETTE["ink"]))
        if result.status in (Status.NEEDS_MODEL, Status.COULD_NOT_CHECK):
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            item.setForeground(QColor(PALETTE["ink_faint"]))
        tip = [f"{spec.label}: {Status.LABELS.get(result.status, result.status)}",
               f"{result.count} found" if result.status != Status.COULD_NOT_CHECK else ""]
        if result.measure is not None and result.status != Status.COULD_NOT_CHECK:
            tip.append(f"{result.measure:g} per 1,000 words")
        if result.message:
            tip.append(result.message)
        item.setToolTip("\n".join(t for t in tip if t))
        return item

    def _stage_cell(self, stage, pairs) -> QTableWidgetItem:
        from src.ai.readiness import STAGE_LABELS, Status
        statuses = [res.status for _s, res in pairs if res is not None]
        worst = next((s for s in _WORST if s in statuses), "")
        counted = [res.count for spec, res in pairs
                   if res is not None and res.status in Status.VERDICTS]
        scanned = [res.count for _s, res in pairs
                   if res is not None and res.status == Status.NEEDS_MODEL]
        text = str(sum(counted)) if counted else (str(sum(scanned)) if scanned
                                                  else ("?" if statuses else ""))
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if worst:
            item.setBackground(tint(STATUS_COLOURS.get(worst, PALETTE["border"])))
        item.setForeground(QColor(PALETTE["ink"] if counted else PALETTE["ink_faint"]))
        if not counted:
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
        lines = [f"{STAGE_LABELS.get(stage, stage)}: worst is "
                 f"{Status.LABELS.get(worst, 'not checked').lower()}"]
        lines += [f"• {spec.label}: {Status.LABELS.get(res.status, res.status)} ({res.count})"
                  for spec, res in pairs if res is not None]
        item.setToolTip("\n".join(lines))
        return item

    def _fit_height(self) -> None:
        """Exactly tall enough for every chapter, up to about twelve rows
        and never more than about a third of the window, so the rest of the
        Critique stays in reach; then it scrolls with the chapter names and
        check names in view. Measured from the rows, so it grows with text
        scaling."""
        t = self.table
        t.resizeRowsToContents()
        row_h = max(t.rowHeight(0) if t.rowCount() else 0, t.fontMetrics().height() + 6)
        window = self.window().height() if self.window() is not None else 900
        fit = max(3, int(window * 0.34) // row_h - 2)
        shown = min(t.rowCount(), 12, fit)
        rows = sum(t.rowHeight(r) for r in range(shown)) or t.fontMetrics().height() + 10
        header = max(t.horizontalHeader().sizeHint().height(), t.horizontalHeader().minimumHeight())
        wide = t.horizontalHeader().length() > t.viewport().width()
        bar = t.horizontalScrollBar().sizeHint().height() if wide else 0
        height = header + rows + bar + 2 * t.frameWidth() + 2
        if t.minimumHeight() != height or t.maximumHeight() != height:
            t.setMinimumHeight(height)
            t.setMaximumHeight(height)
            relayout(self)                    # only when it changed (resizes come back here)

    # ── Choosing a chapter, and what it found ────────────────────

    def _row_of(self, chapter_id: Optional[str]) -> int:
        if self.report is None or not chapter_id:
            return -1
        return next((r for r, ch in enumerate(getattr(self, "_rows", None) or self.report.chapters)
                     if ch.chapter_id == chapter_id), -1)

    def _row_report(self, row: int):
        rows = getattr(self, "_rows", None) or (self.report.chapters if self.report else [])
        return rows[row] if 0 <= row < len(rows) else None

    def _on_cell(self, row: int, col: int) -> None:
        checks = self._column_checks[col] if 0 <= col < len(self._column_checks) else None
        self._select_row(row, checks)

    def _select_row(self, row: int, checks: Optional[List[str]]) -> None:
        from src.ai.readiness import BOOK_ROW
        ch = self._row_report(row)
        if ch is None:
            return
        self._select_chapter(ch.chapter_id, checks)
        if ch.chapter_id != BOOK_ROW:
            self.chapter_selected.emit(ch.scope, ch.chapter_id)

    def _select_chapter(self, chapter_id: Optional[str], checks: Optional[List[str]]) -> None:
        self._selected, self._selected_checks = chapter_id, checks
        self._restore_selection()

    def _restore_selection(self) -> None:
        """Highlight the chosen chapter's row and list what it found."""
        row = self._row_of(self._selected)
        self._mark_row(row)
        if row < 0:
            self.issues.show_message("Click a chapter to see what the checks found in it, "
                                     "or a cell to see one check.")
            return
        if self.table.item(row, 0) is not None:
            self.table.scrollToItem(self.table.item(row, 0))
        from src.ai.readiness import BOOK_ROW
        titles = {ch.chapter_id: (f"{ch.number}. {ch.title}" if ch.number else ch.title)
                  for ch in self.report.chapters}
        if self._selected == BOOK_ROW:
            self._load_style_sheet()
            from src.ai import editor_pass, editorial_letter
            self.issues.letter = editorial_letter.stored(self.project, self.report.scope)
            self.issues.editor_plan = editor_pass.plan(self.report, self.issues.letter)
        self.issues.show_chapter(self._row_report(row), self._selected_checks,
                                 None if self._selected == BOOK_ROW
                                 else self._chapter_text(self._selected), titles)

    def apply_stages(self) -> None:
        """The chapters' stages changed: show them (3.1)."""
        from src.ui import chapter_stage_ui; chapter_stage_ui.apply_stages(self)

    def _titles(self) -> Dict[str, str]:
        return {ch.chapter_id: ch.title for ch in self.report.chapters} if self.report else {}

    def _show_chapter_row(self, chapter_id: str) -> None:
        """A chapter named in the letter: show its row and what was found."""
        if self._row_of(chapter_id) >= 0:
            self._selected, self._selected_checks = chapter_id, None
            self._restore_selection()

    def _set_intended(self, item, check: str, on: bool) -> None:
        """The writer answers a query: it's intended (or takes that back).
        It stops counting, and goes into the editor's brief."""
        from src.ai import editor_pass
        from src.ai import readiness as rd
        if self.project is None or self.report is None:
            return
        spec = rd.REGISTRY.get(check)
        cid = item.chapter_id or (self._selected if self._selected != rd.BOOK_ROW else "")
        editor_pass.set_intended(self.project, item, spec.label if spec else check,
                                 self._titles().get(cid, ""), on)
        # The stored results are kept; only what counts changes.
        for row in list(self.report.chapters) + [self.report]:
            results = (list(row.results.values()) if hasattr(row, "results")
                       else list(row.book_results.values()) + list(row.opening_results.values()))
            for r in results:
                for i in r.items:
                    if i.key == item.key and i.dismissed != on and i.verdict != "cleared":
                        i.dismissed = on
                        r.count = max(0, r.count + (-1 if on else 1))
        self._restore_selection()
        self.status_label.setText(
            "Marked as intended; it goes in the editor's brief. Check readiness to update "
            "the grid." if on else "Taken back. Check readiness to update the grid.")

    def _save_brief(self) -> None:
        """Save the editor's brief (Markdown) where the writer chooses."""
        import os
        from PyQt6.QtWidgets import QFileDialog
        from src.ai import editor_pass
        if self.project is None or self.report is None:
            return
        folder = os.path.dirname(getattr(self.project, "project_path", "") or "") or \
            os.path.expanduser("~")
        name = "".join(c for c in (self.report.name or "manuscript") if c.isalnum() or c in " -_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the editor's brief",
            os.path.join(folder, f"{name.strip() or 'manuscript'} - editor's brief.md"),
            "Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        try:
            text = editor_pass.brief(self.project, self.report.scope, self.report)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.status_label.setText(f"Editor's brief saved: {path}")
        except Exception as e:
            self.status_label.setText(f"Couldn't save the brief: {e}")

    def _letter(self, action: str) -> None:
        """Show the editorial letter, or write it (in the background, 8.2)."""
        from src.ai import editorial_letter
        from src.ui import scorecard_model_run as smr
        from src.ui.background import run_background
        if self.project is None or self.report is None:
            return
        if action == "show" and self.issues.letter:
            self.issues.show_letter(self._titles())
            return
        if getattr(self, "_letter_task", None) is not None:
            return
        project, scope, report = self.project, self.report.scope, self.report
        factory = self.llm_factory if smr.ai_available() else None

        def work(task):
            llm = factory() if factory is not None else None
            task.report("Writing the editorial letter…")
            return editorial_letter.write(llm, project, scope, report)

        def done(letter, error):
            self._letter_task = None
            if error or not letter:
                self.status_label.setText(f"Couldn't write the letter: {error or 'no result'}")
                return
            self.status_label.setText("")
            self.issues.letter = dict(letter, stale=False)
            self.issues.show_letter(self._titles())

        self.status_label.setText("Writing the editorial letter…")
        self._letter_task = run_background(work, done, on_progress=self.status_label.setText,
                                           owner=self, label="editorial letter")

    def _load_style_sheet(self):
        """The book's style sheet, shown from the Whole manuscript row."""
        try:
            from src.ai import story_ledger
            ledger = story_ledger.for_project(self.project, self.report.scope)
            self.issues.style_sheet = ledger.all_facts()
            self.issues.style_sheet_removed = ledger.removed_facts()
            return ledger
        except Exception:
            self.issues.style_sheet, self.issues.style_sheet_removed = [], []
            return None

    def _change_style_sheet(self, action: str, fact) -> None:
        """The writer rewords, removes or puts back a fact."""
        ledger = self._load_style_sheet()
        if ledger is None:
            return
        cid, quote = fact.get("chapter_id", ""), fact.get("quote", "")
        if action == "edit":
            from PyQt6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, "Reword this fact",
                f"Established by “{quote[:80]}”.\nWho or what, a colon, then the fact:",
                text=f"{fact.get('subject', '')}: {fact.get('fact', '')}")
            subject, _, what = text.partition(":")
            if not ok or not ledger.edit(cid, quote, subject, what):
                return
        elif action == "remove":
            ledger.remove(cid, quote)
        elif action == "restore":
            ledger.restore(cid, quote)
        self._load_style_sheet()
        self.issues.show_style_sheet()
        self.status_label.setText("Style sheet changed. Chapters read against that fact will "
                                  "be read again by the next check with the model.")

    def _mark_row(self, row: int) -> None:
        """The chosen chapter's name in bold on a tint; the others plain."""
        for r in range(self.table.rowCount()):
            head = self.table.verticalHeaderItem(r)
            if head is None:
                continue
            font = head.font()
            font.setBold(r == row)
            head.setFont(font)
            head.setBackground(QColor(PALETTE["primary_tint"]) if r == row else QColor(0, 0, 0, 0))
            head.setForeground(QColor(PALETTE["primary_ink"] if r == row else PALETTE["ink"]))

    def selected_row(self) -> int:
        return self._row_of(self._selected)

    def _chapter_text(self, chapter_id: str) -> Optional[str]:
        texts, _hl = self._live()
        if chapter_id in texts:
            return texts[chapter_id]
        try:
            _scope, ch = self.project.find_chapter_with_scope(chapter_id)
            return ch.content if ch is not None else None
        except Exception:
            return None

    def _fix_cell(self, row: int, col: int) -> None:
        """Double-click: open the chapter with this cell's findings in the
        Companion, the first selected in the text."""
        ch = self._row_report(row)
        checks = self._column_checks[col] if 0 <= col < len(self._column_checks) else []
        if ch is None or not checks or not self.issues.request_companion(ch, checks):
            self._select_row(row, checks or None)        # nothing to fix: show the details

    def _choose_row(self, row: int) -> None:
        from src.ai.readiness import BOOK_ROW
        ch = self._row_report(row)
        if ch is not None and ch.chapter_id != BOOK_ROW:
            self.chapter_chosen.emit(ch.scope, ch.chapter_id)


def _wrap_to(text: str, fm, width: int) -> List[str]:
    """``text`` broken into lines no wider than ``width`` pixels (a word
    longer than that gets a line of its own)."""
    lines: List[str] = []
    for word in text.split():
        if lines and fm.horizontalAdvance(lines[-1] + " " + word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


# ── Wiring into the Critique tab ─────────────────────────────────────────

def _settings():
    from src.ui.ui_kit import _settings as kit_settings
    return kit_settings()


def install_scorecard(grader, layout, setup_groups) -> ScorecardWidget:
    """Put the scorecard at the top of the Critique tab, fold its set-up
    groups into one "Detailed critique" section (closed unless the writer
    left it open), and wire a chapter's row to the detailed critique.
    Every control keeps its object, its signals and its behaviour."""
    first = min(layout.indexOf(g) for g in setup_groups)
    for g in setup_groups:
        layout.removeWidget(g)
    setup = CollapsibleSection(SETUP_TITLE, SETUP_KEY)
    for g in setup_groups:
        setup.body_layout.addWidget(g)
    try:
        is_open = str(_settings().value(SETUP_KEY, "false")).lower() == "true"
    except Exception:
        is_open = False
    setup.set_open(is_open)
    setup.toggled.connect(lambda _k, collapsed: _remember_setup(not collapsed))
    scorecard = ScorecardWidget()

    def critique_model():                         # the Critique's own analysis model
        from src.ai.task_llm import build_critique_llm
        return build_critique_llm(grader._analysis_model_spec())
    scorecard.llm_factory = critique_model
    scorecard._sync_background()
    layout.insertWidget(first, scorecard)
    layout.insertWidget(first + 1, setup)
    grader.critique_setup = setup

    def point_at(scope, chapter_id, open_setup):
        """Set the detailed critique to this chapter: "Current chapter" when
        it is the one open in Write, else "Selected chapters" with it ticked.
        The writer can still pick as before."""
        try:
            live = getattr(getattr(scorecard._live_source, "current_chapter_editor", None),
                           "chapter", None)
            if getattr(live, "id", None) == chapter_id and not open_setup:
                grader.scope_single_radio.setChecked(True)
            else:
                grader.scope_multi_radio.setChecked(True)
                if getattr(grader.project, "subprojects", None):
                    i = grader.manuscript_combo.findData(scope or "")
                    if i >= 0:
                        grader.manuscript_combo.setCurrentIndex(i)
                grader._populate_chapter_list()
                picker = grader.chapter_picker
                for i in range(picker.count()):
                    item = picker.item(i)
                    item.setSelected(item.data(Qt.ItemDataRole.UserRole + 1) == chapter_id)
            if open_setup:
                setup.set_open(True, quiet=False)
                grader.critique_btn.setFocus()
                grader.status_label.setText("Chapter chosen: pick the reports, then Run Critique.")
                grader.status_label.setVisible(True)
        except Exception as e:                   # never break the tab
            print(f"[scorecard] could not set the chapter: {e}")

    def open_chapter(scope, chapter_id):
        point_at(scope, chapter_id, True)
    scorecard.chapter_selected.connect(lambda scope, cid: point_at(scope, cid, False))
    scorecard.issues.expand_requested.connect(grader.expand_statement_requested.emit)
    scorecard.chapter_chosen.connect(open_chapter)
    return scorecard


def _remember_setup(is_open: bool) -> None:
    try:
        _settings().setValue(SETUP_KEY, "true" if is_open else "false")
    except Exception:
        pass
