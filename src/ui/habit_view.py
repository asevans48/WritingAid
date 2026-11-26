"""What the writer sees of the writing habit (piece H.1).

* ``HabitLink``: one quiet link under "Where you left off" in the
  Companion: "Set a daily goal…" while no goal is set, then "Your writing
  record…".
* ``GoalDialog``: the daily and weekly goals (words a day, words a week).
* ``HabitWindow``: the last 12 weeks as day squares shaded by words, the
  streak, this week and the best week. Clicking a day lists what was worked
  on. Nothing else.
* ``HabitOption``: the same goals and the nudge switch in Settings ▸
  AI Features ▸ Writing habit.

Colours come from ``PALETTE`` and the parts from ``ui_kit`` (D.8). The
record itself is ``src/data/writing_habit.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QToolTip, QVBoxLayout, QWidget,
)

from src.data import writing_habit as wh
from src.ui.ui_kit import DIALOG_MARGIN, GAP, PALETTE, fit_to_screen, scrollable, text_style

DAILY_MAX, WEEKLY_MAX = 50_000, 250_000


def _link(href: str, text: str) -> str:
    return (f"<a href='{href}' style='color:{PALETTE['primary']}; text-decoration:none'>"
            f"{text}</a>")


def _day_name(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def progress(today: Optional[date] = None) -> Optional[Tuple[str, str]]:
    """The Companion's habit line and short form, or None while no goal is set."""
    daily, weekly = wh.goals()
    if not (daily or weekly):
        return None
    try:
        return wh.progress_line(wh.load()["days"], today or date.today(), daily, weekly)
    except Exception as e:                       # noqa: BLE001
        print(f"[habit] {e}")
        return None


# ── The Companion's link ───────────────────────────────────────────────

class HabitLink(QLabel):
    """"Set a daily goal…" (no goal yet) or "Your writing record…"."""

    def __init__(self, on_changed: Callable[[], None], parent=None):
        super().__init__(parent)
        self._on_changed = on_changed
        self._window: Optional[HabitWindow] = None
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setStyleSheet(text_style("", 11))
        self.linkActivated.connect(self._open)
        self.refresh()

    def refresh(self) -> None:
        daily, weekly = wh.goals()
        if daily or weekly:
            self.setText(_link("record", "Your writing record…"))
            self.setToolTip("The last 12 weeks, your streak and your goals")
        else:
            self.setText(_link("goal", "Set a daily goal…"))
            self.setToolTip("A daily or weekly word goal, shared by every project. "
                            "Nothing else changes until you set one.")

    def _open(self, href: str) -> None:
        try:
            if href == "goal":
                if GoalDialog(self).exec() == QDialog.DialogCode.Accepted:
                    self._changed()
            else:
                self._window = HabitWindow(self.window(), on_changed=self._changed)
                self._window.show()
                self._window.raise_()
        except Exception as e:                   # noqa: BLE001
            print(f"[habit] {e}")

    def _changed(self) -> None:
        self.refresh()
        self._on_changed()


# ── Goals ──────────────────────────────────────────────────────────────

def _goal_spin(value: int, maximum: int, step: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, maximum)
    spin.setSingleStep(step)
    spin.setGroupSeparatorShown(True)
    spin.setSpecialValueText("No goal")
    spin.setSuffix(" words")
    spin.setValue(value)
    return spin


class GoalDialog(QDialog):
    """Words a day and words a week; either, both or neither."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Writing goals")
        daily, weekly = wh.goals()
        v = QVBoxLayout(self)
        v.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        v.setSpacing(GAP)
        form = QFormLayout()
        self.daily = _goal_spin(daily or 0, DAILY_MAX, 50)
        self.weekly = _goal_spin(weekly or 0, WEEKLY_MAX, 250)
        if not (daily or weekly):
            self.daily.setValue(500)              # a starting point the writer can change
        form.addRow("Each day:", self.daily)
        form.addRow("Each week:", self.weekly)
        v.addLayout(form)
        note = QLabel("Goals count new words in every project. Any writing, cutting or "
                      "revising keeps your streak going. The week starts on Monday.")
        note.setWordWrap(True)
        note.setStyleSheet(text_style("ink_faint", 11))
        v.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def accept(self) -> None:
        try:
            wh.set_goals(self.daily.value(), self.weekly.value())
        except Exception as e:                   # noqa: BLE001
            print(f"[habit] could not save the goals: {e}")
        super().accept()


# ── The 12-week window ─────────────────────────────────────────────────

def _blend(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


def shade(level: int) -> QColor:
    """No writing: the muted surface; then four shades of ``primary``."""
    if level <= 0:
        return QColor(PALETTE["surface_muted"])
    return _blend(PALETTE["primary_border"], PALETTE["primary"], (level - 1) / 3)


class DayGrid(QWidget):
    """Twelve weeks of day squares, a column a week, Monday at the top."""
    day_clicked = pyqtSignal(object)            # datetime.date

    WEEKS = 12

    def __init__(self, days: wh.Days, today: date, parent=None):
        super().__init__(parent)
        self.days, self.today = days, today
        self.dates = wh.recent_dates(today, self.WEEKS)
        self.selected = today
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # geometry, from the font so it grows with text scaling
    def _cell(self) -> int:
        return max(12, self.fontMetrics().height())

    def _gap(self) -> int:
        return max(2, self._cell() // 6)

    def _left(self) -> int:
        return self.fontMetrics().horizontalAdvance("Wed") + 6

    def _top(self) -> int:
        return self.fontMetrics().height() + 4

    def sizeHint(self) -> QSize:                         # noqa: N802 (Qt)
        step = self._cell() + self._gap()
        return QSize(self._left() + self.WEEKS * step, self._top() + 7 * step)

    def minimumSizeHint(self) -> QSize:                  # noqa: N802 (Qt)
        return self.sizeHint()

    def _rect(self, i: int) -> QRect:
        step = self._cell() + self._gap()
        week, weekday = divmod(i, 7)
        return QRect(self._left() + week * step, self._top() + weekday * step,
                     self._cell(), self._cell())

    def _activity(self, d: date) -> int:
        t = wh.day_totals(self.days.get(d.isoformat()))
        return t["added"] + t["cut"] + t["moved"]

    def date_at(self, pos: QPoint) -> Optional[date]:
        for i, d in enumerate(self.dates):
            if self._rect(i).contains(pos):
                return d
        return None

    def paintEvent(self, event) -> None:                 # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(PALETTE["ink_faint"]))
        for row, name in ((0, "Mon"), (2, "Wed"), (4, "Fri"), (6, "Sun")):
            r = self._rect(row)
            p.drawText(QRect(0, r.top(), self._left() - 4, r.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
        month = None
        for week in range(self.WEEKS):
            monday = self.dates[week * 7]
            if monday.month != month:
                month = monday.month
                r = self._rect(week * 7)
                p.drawText(QRect(r.left(), 0, r.width() * 4, self._top() - 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, f"{monday:%b}")
        for i, d in enumerate(self.dates):
            r = self._rect(i)
            if d > self.today:
                p.setPen(QPen(QColor(PALETTE["border"]), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(shade(wh.shade_level(self._activity(d))))
            p.drawRoundedRect(r, 3, 3)
            if d == self.selected:
                p.setPen(QPen(QColor(PALETTE["ink"]), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        p.end()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            d = self.date_at(e.pos())
            if d is not None:
                t = wh.day_totals(self.days.get(d.isoformat()))
                QToolTip.showText(e.globalPos(), f"{_day_name(d)}: {t['added']:,} added, "
                                                 f"{t['cut']:,} cut", self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mousePressEvent(self, e) -> None:                # noqa: N802 (Qt)
        d = self.date_at(e.position().toPoint())
        if d is not None and d <= self.today:
            self.selected = d
            self.update()
            self.day_clicked.emit(d)


def day_summary(days: wh.Days, d: date) -> str:
    """What was worked on that day, as a few lines of rich text."""
    day = days.get(d.isoformat())
    if not wh.is_writing_day(day):
        return f"<b>{_day_name(d)}</b>: no writing."
    t = wh.day_totals(day)
    parts = [f"{t['added']:,} words added", f"{t['cut']:,} cut"]
    if t["moved"]:
        parts.append(f"{t['moved']:,} pasted or imported")
    if t["minutes"]:
        parts.append(f"{t['minutes']:,} minutes typing")
    lines = [f"<b>{_day_name(d)}</b>: " + ", ".join(parts) + "."]
    for name, titles in wh.worked_on(day):
        if titles:
            lines.append(f"{_esc(name)}: " + ", ".join(_esc(t) for t in titles))
    return "<br>".join(lines)


def _esc(text: str) -> str:
    import html
    return html.escape(text or "")


class HabitWindow(QDialog):
    """The last 12 weeks, the streak, this week and the best week."""

    def __init__(self, parent=None, on_changed: Optional[Callable[[], None]] = None,
                 today: Optional[date] = None):
        super().__init__(parent)
        self.setWindowTitle("Your writing record")
        self.setModal(False)
        self._on_changed = on_changed
        self.today = today or date.today()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        page = QWidget()
        self.body = QVBoxLayout(page)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(GAP)
        outer.addWidget(scrollable(page), 1)
        row = QHBoxLayout()
        self.goals_link = QLabel(_link("goals", "Goals…"))
        self.goals_link.setTextFormat(Qt.TextFormat.RichText)
        self.goals_link.linkActivated.connect(self._edit_goals)
        row.addWidget(self.goals_link)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        row.addWidget(buttons)
        outer.addLayout(row)
        self._build()
        fit_to_screen(self, 560, 440, min_width=360, min_height=300)

    def _build(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        days = wh.load()["days"]
        daily, weekly = wh.goals()
        s = wh.streak(days, self.today)
        self.streak_label = QLabel(f"{s} day{'s' if s != 1 else ''} in a row")
        self.streak_label.setStyleSheet(text_style("primary_ink", 18, bold=True))
        self.body.addWidget(self.streak_label)
        longest = wh.longest_streak(days)
        month = wh.days_this_month(days, self.today)
        facts = QLabel(f"{month} day{'s' if month != 1 else ''} this month · "
                       f"longest streak {longest} day{'s' if longest != 1 else ''}")
        facts.setStyleSheet(text_style("ink_soft", 12))
        self.body.addWidget(facts)
        p = wh.goal_progress(days, self.today, daily, weekly)
        week = f"This week: {p['week']:,}" + (f" of {weekly:,}" if weekly else "") + " words"
        if daily:
            week += f" · today {p['today']:,} of {daily:,}"
        best, best_words = wh.best_week(days)
        if best is not None and best_words:
            week += f" · best week {best_words:,} (from {_day_name(best)})"
        self.week_label = QLabel(week)
        self.week_label.setWordWrap(True)
        self.week_label.setStyleSheet(text_style("ink", 12))
        self.body.addWidget(self.week_label)
        self.grid = DayGrid(days, self.today)
        self.grid.day_clicked.connect(self._show_day)
        self.body.addWidget(self.grid, 0, Qt.AlignmentFlag.AlignLeft)
        hint = QLabel("Darker squares: more words added and cut. Click a day to see what "
                      "you worked on.")
        hint.setWordWrap(True)
        hint.setStyleSheet(text_style("ink_faint", 11))
        self.body.addWidget(hint)
        self.day_label = QLabel("")
        self.day_label.setWordWrap(True)
        self.day_label.setTextFormat(Qt.TextFormat.RichText)
        self.day_label.setStyleSheet(text_style("ink", 12))
        self.body.addWidget(self.day_label)
        self.body.addStretch(1)
        self._days = days
        self._show_day(self.today)

    def _show_day(self, d: date) -> None:
        self.day_label.setText(day_summary(self._days, d))

    def _edit_goals(self, *_):
        if GoalDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._build()
            if self._on_changed:
                self._on_changed()


# ── Settings ▸ AI Features ▸ Writing habit ─────────────────────────────

class HabitOption:
    """The goals and the nudge switch (two call lines in ``SettingsDialog``)."""

    def __init__(self, layout):
        daily, weekly = wh.goals()
        group = QGroupBox("Writing habit")
        form = QFormLayout()
        self.daily = _goal_spin(daily, DAILY_MAX, 50)
        self.weekly = _goal_spin(weekly, WEEKLY_MAX, 250)
        form.addRow("Daily goal:", self.daily)
        form.addRow("Weekly goal:", self.weekly)
        self.nudge = QCheckBox("Nudge me to move on when I've only been revising")
        self.nudge.setToolTip("For a novel or novella still being drafted: after seven writing "
                              "days of revising with almost no new words, the app asks once, "
                              "when you open a chapter, whether to move on.")
        self.nudge.setChecked(wh.nudge_state()["on"])
        form.addRow(self.nudge)
        note = QLabel("Shared by every project. Any writing, cutting or revising keeps your "
                      "streak going; the goals count new words. The week starts on Monday.")
        note.setWordWrap(True)
        note.setStyleSheet(text_style("ink_faint", 11))
        form.addRow(note)
        group.setLayout(form)
        layout.addWidget(group)

    def save(self) -> None:
        try:
            wh.set_goals(self.daily.value(), self.weekly.value())
            wh.set_nudge(on=self.nudge.isChecked())
        except Exception as e:                   # noqa: BLE001
            print(f"[habit] could not save: {e}")
