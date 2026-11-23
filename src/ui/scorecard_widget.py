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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.ui.ui_kit import (
    PALETTE, STAGE_COLOURS, CollapsibleSection, empty_state, primary_button, size_class,
)

HONEST_LINE = ("This measures the mechanics of the writing. It cannot tell you whether the "
               "story works; readers and an editor can.")
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
        self.check_btn = primary_button("Check readiness")
        self.check_btn.setToolTip("Check every chapter of this manuscript. Chapters you "
                                  "haven't changed since the last check are not checked again.")
        self.check_btn.clicked.connect(lambda: self.refresh(force=False))
        top.addWidget(self.check_btn)
        outer.addLayout(top)

        figure_row = QHBoxLayout()
        self.figure_label = QLabel("—")
        self.figure_label.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {PALETTE['ink']};")
        figure_row.addWidget(self.figure_label)
        words = QVBoxLayout()
        words.setSpacing(0)
        self.figure_caption = QLabel("ready for readers")
        self.figure_caption.setStyleSheet(f"font-weight: bold; color: {PALETTE['ink_soft']};")
        words.addWidget(self.figure_caption)
        honest = QLabel(HONEST_LINE)
        honest.setWordWrap(True)
        honest.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
        words.addWidget(honest)
        figure_row.addLayout(words, 1)
        outer.addLayout(figure_row)

        self.note_label = QLabel("")
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
        self.table.cellDoubleClicked.connect(lambda row, _col: self._choose_row(row))
        self.table.verticalHeader().sectionDoubleClicked.connect(self._choose_row)
        self.table.cellClicked.connect(self._on_cell)
        self.table.verticalHeader().sectionClicked.connect(lambda row: self._select_row(row, None))
        self.table.setToolTip("Click a chapter to see what the checks found; click a cell "
                              "for that check alone.")
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

    def refresh(self, force: bool = False) -> None:
        """Check the chosen manuscript in the background (cached chapters
        are not checked again)."""
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
        self.check_btn.setEnabled(False)
        self.status_label.setText("Checking…")

        def work(task):
            from src.ai import readiness as rd
            scanner = rd.Scanner(project, base)

            def progress(done, total, title):
                if title:
                    task.report(f"Checking {title}… ({done + 1} of {total})")
            return rd.book_report(project, scope, texts=texts, scanner=scanner,
                                  use_cache=not force, progress=progress,
                                  stop=lambda: task.stopping)

        self._task = run_background(work, self._done, on_progress=self.status_label.setText,
                                    owner=self, label="scorecard")

    def _done(self, report, error: str) -> None:
        self._task = None
        self.check_btn.setEnabled(True)
        if error or report is None:
            self.status_label.setText(f"Couldn't check: {error or 'no result'}")
            return
        self.status_label.setText("")
        self._reports[(report.scope or "main")] = report
        if (report.scope or "main") == self._scope_key():
            self._render(report)

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
        self.figure_label.setText(f"{round(report.readiness * 100)}%" if report.cells else "—")
        self.note_label.setText(self._note(report))
        self._fill_grid(report)
        self._restore_selection()

    def _note(self, report) -> str:
        from src.ai import readiness as rd
        bits = ["A scan: no model judged these results." if report.tier == "scan"
                else "Judged by a model."]
        if report.left_out:
            names = [f"{rd.REGISTRY[n].label} ({why})" if n in rd.REGISTRY else n
                     for n, why in report.left_out.items()]
            bits.append("Left out of the figure: " + "; ".join(names) + ".")
        if not report.cells:
            bits.append("Nothing counts toward the figure yet.")
        if not report.complete:
            bits.append("The check stopped part way; click Check readiness to finish.")
        if not report.saved:
            bits.append("These results weren't saved: the readiness file is from a newer "
                        "version of the app, or couldn't be written.")
        return " ".join(bits)

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
        self.table.setRowCount(len(report.chapters))
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
        for r, (ch, cells) in enumerate(g.rows):
            name = f"{ch.number}. {ch.title}" if ch.number else ch.title
            head = QTableWidgetItem(name if len(name) <= 36 else name[:35] + "…")
            head.setToolTip(f"{name}\n{ch.words:,} words" + (" · the opening chapter" if ch.is_opening
                                                     else "")
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
        text = "?" if result.status == Status.COULD_NOT_CHECK else str(result.count)
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
        t.setMinimumHeight(height)
        t.setMaximumHeight(height)

    # ── Choosing a chapter, and what it found ────────────────────

    def _row_of(self, chapter_id: Optional[str]) -> int:
        if self.report is None or not chapter_id:
            return -1
        return next((r for r, ch in enumerate(self.report.chapters)
                     if ch.chapter_id == chapter_id), -1)

    def _on_cell(self, row: int, col: int) -> None:
        checks = self._column_checks[col] if 0 <= col < len(self._column_checks) else None
        self._select_row(row, checks)

    def _select_row(self, row: int, checks: Optional[List[str]]) -> None:
        if self.report is None or not (0 <= row < len(self.report.chapters)):
            return
        ch = self.report.chapters[row]
        self._select_chapter(ch.chapter_id, checks)
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
        self.issues.show_chapter(self.report.chapters[row], self._selected_checks,
                                 self._chapter_text(self._selected))

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

    def _choose_row(self, row: int) -> None:
        if self.report is None or not (0 <= row < len(self.report.chapters)):
            return
        ch = self.report.chapters[row]
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
