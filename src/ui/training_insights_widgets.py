"""Training Studio widgets for dataset readiness and run assessment.

* :class:`LossChartWidget` — live training vs. validation loss chart.
* :func:`readiness_html` — Step 3 dataset size/quality/readiness panel.
* :class:`ReadinessWorker` — runs :func:`analyze_dataset` off the UI thread.
* :class:`TrainingReportDialog` — post-training metrics, curves and alerts.

All logic lives in :mod:`src.ai.training_insights`; this module only
renders it.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QScrollArea, QVBoxLayout,
    QWidget,
)

from src.ai.training_insights import (
    DatasetReport, RegularizationPlan, TrainingAssessment, analyze_dataset,
    tasks_label,
)

TRAIN_COLOR = "#2563eb"
EVAL_COLOR = "#dc2626"
_STATUS_STYLE = {
    "insufficient": ("#b91c1c", "🛑 Not enough"),
    "workable": ("#b45309", "⚠️ Workable"),
    "good": ("#15803d", "✅ Good"),
    "strong": ("#15803d", "✅ Strong"),
}
_LEVEL_STYLE = {
    "critical": ("#b91c1c", "#fef2f2", "🛑"),
    "warning": ("#b45309", "#fffbeb", "⚠️"),
    "info": ("#1d4ed8", "#eff6ff", "ℹ️"),
}
_VERDICT_STYLE = {
    "healthy": ("#15803d", "#f0fdf4", "✅ Healthy run"),
    "review": ("#b45309", "#fffbeb", "⚠️ Review the alerts"),
    "problem": ("#b91c1c", "#fef2f2", "🛑 Quality problems detected"),
    "unknown": ("#374151", "#f3f4f6", "No metrics recorded"),
}


# ── Loss chart ─────────────────────────────────────────────


class LossChartWidget(QWidget):
    """Training loss (thin raw line + smoothed line) and validation loss
    (points + line) against optimizer step. The best validation point
    is marked so the user can see where the saved checkpoint came from.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._train: List[Tuple[int, float]] = []
        self._eval: List[Tuple[int, float]] = []

    def clear(self) -> None:
        self._train, self._eval = [], []
        self.update()

    def add_metrics(self, m: Dict[str, Any]) -> None:
        step = int(m.get("step", 0))
        if _ok(m.get("loss")):
            self._train.append((step, float(m["loss"])))
        if _ok(m.get("eval_loss")):
            self._eval.append((step, float(m["eval_loss"])))
        self.update()

    def set_curves(self, train: Sequence[Tuple[int, float]],
                   evals: Sequence[Tuple[int, float]]) -> None:
        self._train = [(int(s), float(v)) for s, v in train if _ok(v)]
        self._eval = [(int(s), float(v)) for s, v in evals if _ok(v)]
        self.update()

    def has_data(self) -> bool:
        return bool(self._train or self._eval)

    def paintEvent(self, _event):  # noqa: N802 — Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        left, right, top, bottom = 48, 12, 22, 24
        plot = QRectF(left, top, max(10, w - left - right),
                      max(10, h - top - bottom))
        p.setPen(QPen(QColor("#e5e7eb")))
        p.drawRect(plot)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 2))
        p.setFont(small)

        pts = self._train + self._eval
        if not pts:
            p.setPen(QColor("#9ca3af"))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter,
                       "Loss curves appear here once training starts")
            p.end()
            return

        xs = [s for s, _ in pts]
        ys = [v for _, v in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 == x0:
            x1 = x0 + 1
        pad = (y1 - y0) * 0.08 or 0.05
        y0, y1 = y0 - pad, y1 + pad

        def to_px(step, val):
            return QPointF(plot.left() + (step - x0) / (x1 - x0) * plot.width(),
                           plot.bottom() - (val - y0) / (y1 - y0) * plot.height())

        # Gridlines + axis labels
        p.setPen(QColor("#6b7280"))
        for i in range(5):
            val = y0 + (y1 - y0) * i / 4
            y = plot.bottom() - plot.height() * i / 4
            p.setPen(QPen(QColor("#f3f4f6")))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor("#6b7280"))
            p.drawText(QRectF(0, y - 8, left - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:.2f}")
        p.drawText(QRectF(plot.left(), plot.bottom() + 4, plot.width(), 16),
                   Qt.AlignmentFlag.AlignLeft, f"step {x0}")
        p.drawText(QRectF(plot.left(), plot.bottom() + 4, plot.width(), 16),
                   Qt.AlignmentFlag.AlignRight, f"step {x1}")

        if self._train:
            raw = QColor(TRAIN_COLOR)
            raw.setAlpha(60)
            self._polyline(p, [to_px(s, v) for s, v in self._train], raw, 1.0)
            self._polyline(p, [to_px(s, v) for s, v in _ema(self._train)],
                           QColor(TRAIN_COLOR), 2.0)
        if self._eval:
            ev = [to_px(s, v) for s, v in self._eval]
            self._polyline(p, ev, QColor(EVAL_COLOR), 2.0)
            p.setPen(QPen(QColor(EVAL_COLOR), 1.5))
            p.setBrush(QColor("#ffffff"))
            for pt in ev:
                p.drawEllipse(pt, 3, 3)
            bs, bv = min(self._eval, key=lambda sv: sv[1])
            bp = to_px(bs, bv)
            p.setBrush(QColor(EVAL_COLOR))
            p.drawEllipse(bp, 4.5, 4.5)
            dash = QPen(QColor("#9ca3af"), 1, Qt.PenStyle.DashLine)
            p.setPen(dash)
            p.drawLine(QPointF(bp.x(), plot.top()), QPointF(bp.x(), plot.bottom()))
            p.setPen(QColor(EVAL_COLOR))
            p.drawText(QRectF(bp.x() + 4, plot.top() + 2, 160, 14),
                       Qt.AlignmentFlag.AlignLeft, f"best val {bv:.3f}")

        # Legend
        p.setPen(QColor(TRAIN_COLOR))
        p.drawText(QRectF(left, 3, 200, 16), Qt.AlignmentFlag.AlignLeft,
                   "━ training (fit) loss")
        p.setPen(QColor(EVAL_COLOR))
        p.drawText(QRectF(left + 150, 3, 200, 16), Qt.AlignmentFlag.AlignLeft,
                   "━● validation loss")
        p.end()

    @staticmethod
    def _polyline(p: QPainter, pts: List[QPointF], color: QColor, width: float):
        if len(pts) < 2:
            return
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        p.setPen(QPen(color, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def _ema(points: Sequence[Tuple[int, float]], alpha: float = 0.15):
    out, acc = [], None
    for s, v in points:
        acc = v if acc is None else alpha * v + (1 - alpha) * acc
        out.append((s, acc))
    return out


# ── Readiness panel ────────────────────────────────────────


def readiness_html(report: DatasetReport,
                   plan: Optional[RegularizationPlan] = None) -> str:
    """Rich-text summary of dataset size, quality and task coverage."""
    color, verdict = _STATUS_STYLE.get(report.readiness, ("#374151", ""))
    q = report.quality_score
    q_color = "#15803d" if q >= 0.8 else "#b45309" if q >= 0.6 else "#b91c1c"
    rows = []
    for c in report.coverage:
        c_color, c_label = _STATUS_STYLE.get(c.status, ("#374151", c.status))
        est = " (est.)" if c.estimated else ""
        need = (f"needs ~{c.shortfall:,} more effective"
                if c.shortfall else "meets recommendation")
        rows.append(
            f"<tr><td><b>{html.escape(c.label)}</b></td>"
            f"<td align='right'>{c.rows:,}{est}</td>"
            f"<td align='right'>{c.effective:,.0f}</td>"
            f"<td align='right'>{c.minimum:,} / {c.recommended:,} / {c.strong:,}</td>"
            f"<td style='color:{c_color}'>{c_label}</td>"
            f"<td style='color:#6b7280'>{need}</td></tr>")
    combo = ""
    if len(report.coverage) > 1:
        combo = (f"<br>Combined target for {html.escape(tasks_label(report.tasks))}: "
                 f"~{report.total_recommended:,} effective examples "
                 f"(each task needs its own coverage).")
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in report.quality_notes)
    notes = f"<ul style='margin:4px 0 0 -20px'>{notes}</ul>" if notes else ""
    plan_html = ""
    if plan is not None:
        plan_html = ("<p style='margin-top:6px'><b>Recommended overfitting "
                     "protection:</b></p><ul style='margin:0 0 0 -20px'>"
                     + "".join(f"<li>{html.escape(r)}</li>" for r in plan.rationale)
                     + "</ul>")
    copyedit_note = ""
    if "copyedit" in report.tasks:
        copyedit_note = ("<p style='color:#6b7280;font-size:11px'>Copyediting "
                         "examples are rewrite pairs (rephrase / agent / "
                         "writing-chat) whose output keeps ≥75% of the input's "
                         "wording.</p>")
    return (
        f"<p style='margin:0'><b style='color:{color}'>{verdict}</b> for "
        f"<b>{html.escape(tasks_label(report.tasks))}</b> — "
        f"{report.n_rows:,} rows exported, <b>{report.n_unique:,} unique</b>"
        f" ({report.duplicate_rate:.0%} copies), quality score "
        f"<b style='color:{q_color}'>{q:.2f}</b>, ~{report.eval_rows:,} held out "
        f"for validation.{combo}</p>"
        "<table cellspacing='0' cellpadding='3' style='margin-top:6px'>"
        "<tr style='color:#6b7280'><td>Task</td><td align='right'>Rows</td>"
        "<td align='right'>Effective</td>"
        "<td align='right'>Min / Rec / Strong</td><td>Status</td><td></td></tr>"
        + "".join(rows) + "</table>"
        + copyedit_note + notes + plan_html
        + "<p style='color:#9ca3af;font-size:10px;margin-top:4px'>Effective = "
          "unique rows × quality (ratings, empty/identical/too-short/truncated "
          "outputs). Targets are rules of thumb for LoRA fine-tunes of 1-8B "
          "instruction models.</p>")


class ReadinessWorker(QThread):
    """Runs :func:`analyze_dataset` without blocking the UI."""

    finished_ok = pyqtSignal(object)  # DatasetReport
    failed = pyqtSignal(str)

    def __init__(self, jsonl_path: Path, tasks: Sequence[str], *,
                 max_length_tokens: int = 512, eval_fraction: float = 0.15,
                 parent=None):
        super().__init__(parent)
        self.jsonl_path = jsonl_path
        self.tasks = list(tasks)
        self.max_length_tokens = max_length_tokens
        self.eval_fraction = eval_fraction

    def run(self):  # noqa: D401 — Qt slot
        try:
            self.finished_ok.emit(analyze_dataset(
                self.jsonl_path, self.tasks,
                max_length_tokens=self.max_length_tokens,
                eval_fraction=self.eval_fraction))
        except Exception as e:
            self.failed.emit(str(e))


# ── Report dialog ──────────────────────────────────────────


def alerts_html(assessment: TrainingAssessment) -> str:
    if not assessment.alerts:
        return "<p style='color:#15803d'>No quality issues detected.</p>"
    order = {"critical": 0, "warning": 1, "info": 2}
    parts = []
    for al in sorted(assessment.alerts, key=lambda a: order.get(a.level, 3)):
        fg, bg, icon = _LEVEL_STYLE.get(al.level, ("#374151", "#f9fafb", "•"))
        fix = (f"<br><span style='color:#374151'><i>What to do:</i> "
               f"{html.escape(al.suggestion)}</span>" if al.suggestion else "")
        parts.append(
            f"<table width='100%' cellpadding='6' style='background:{bg};"
            f"margin-bottom:4px'><tr><td><b style='color:{fg}'>{icon} "
            f"{html.escape(al.title)}</b><br>{html.escape(al.detail)}{fix}"
            f"</td></tr></table>")
    return "".join(parts)


def _fmt(v, fmt="{:.3f}", none="—"):
    return none if v is None else fmt.format(v)


class TrainingReportDialog(QDialog):
    """Post-training report: verdict, fit/validation metrics, loss curves,
    alerts and the dataset/settings the run used."""

    def __init__(self, assessment: TrainingAssessment, *,
                 dataset: Optional[Dict[str, Any]] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 title: str = "Training report",
                 header_html: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        if header_html:
            h = QLabel(header_html)
            h.setWordWrap(True)
            h.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(h)

        fg, bg, label = _VERDICT_STYLE.get(assessment.verdict,
                                           _VERDICT_STYLE["unknown"])
        n_crit = sum(a.level == "critical" for a in assessment.alerts)
        n_warn = sum(a.level == "warning" for a in assessment.alerts)
        banner = QLabel(f"<b style='font-size:14px;color:{fg}'>{label}</b>"
                        f"<span style='color:#6b7280'> — {n_crit} critical, "
                        f"{n_warn} warning(s)</span>")
        banner.setStyleSheet(f"background:{bg}; padding:8px; border-radius:6px;")
        lay.addWidget(banner)

        a = assessment
        grid = QGridLayout()
        metrics = [
            ("Training (fit) loss", f"{_fmt(a.initial_train_loss)} → "
                                    f"{_fmt(a.final_train_loss)}",
             "Mean of the first vs. last logged steps."),
            ("Training loss reduction", _fmt(a.train_loss_reduction, "{:.0%}"),
             "How much the model adapted to the training set."),
            ("Best validation loss",
             f"{_fmt(a.best_eval_loss)} (step {a.best_eval_step})"
             if a.best_eval_loss is not None else "—",
             "Lowest held-out loss — the checkpoint that was kept."),
            ("Final validation loss", _fmt(a.final_eval_loss),
             "Held-out loss at the last evaluation."),
            ("Validation perplexity", _fmt(a.eval_perplexity, "{:.2f}"),
             "exp(validation loss) of the saved model; lower is better."),
            ("Generalization gap", _fmt(a.generalization_gap, "{:+.3f}"),
             "Validation minus training loss; large = memorizing."),
            ("Validation rise from best", _fmt(a.eval_rise_from_best, "{:+.1%}"),
             "Positive = validation got worse after its best point (overfitting)."),
            ("Steps", f"{a.total_steps}" + (" (stopped early)" if a.early_stopped
                                            else ""), ""),
        ]
        for i, (name, value, tip) in enumerate(metrics):
            n = QLabel(f"<span style='color:#6b7280'>{name}</span>")
            v = QLabel(f"<b>{html.escape(value)}</b>")
            n.setToolTip(tip)
            v.setToolTip(tip)
            grid.addWidget(n, i // 2, (i % 2) * 2)
            grid.addWidget(v, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(grid)

        chart = LossChartWidget()
        chart.setMinimumHeight(220)
        chart.set_curves(a.train_curve, a.eval_curve)
        lay.addWidget(chart)

        lay.addWidget(QLabel("<b>Alerts</b>"))
        alerts = QLabel(alerts_html(a))
        alerts.setWordWrap(True)
        alerts.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(alerts)

        if dataset:
            ds = QLabel(_dataset_summary_html(dataset))
            ds.setWordWrap(True)
            lay.addWidget(ds)
        if settings:
            st = QLabel("<b>Settings used</b><br><span style='color:#374151'>"
                        + ", ".join(f"{html.escape(str(k))}={html.escape(str(v))}"
                                    for k, v in settings.items()) + "</span>")
            st.setWordWrap(True)
            lay.addWidget(st)
        lay.addStretch()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        outer.addWidget(bb)


def _dataset_summary_html(d: Dict[str, Any]) -> str:
    cov = d.get("coverage") or []
    tasks = ", ".join(
        f"{c.get('task')}: {c.get('rows', 0):,} rows (~{c.get('effective', 0):,.0f} "
        f"effective, {c.get('status')})" for c in cov)
    return (f"<b>Dataset</b><br><span style='color:#374151'>"
            f"{d.get('n_rows', 0):,} rows, {d.get('n_unique', 0):,} unique, "
            f"quality {d.get('quality_score', 0):.2f}, ~{d.get('eval_rows', 0):,} "
            f"held out. {html.escape(tasks)}</span>")
