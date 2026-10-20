"""Model drift dialog — compare a trained model's data with the chosen mix.

Renders a :class:`src.ai.model_drift.DriftReport`: recommendation,
coverage and distribution-shift signals, recipe changes, the optional
performance check (loss on unseen examples) and past checks. The
recommendation's action buttons hand back to the Training Studio.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from src.ai.model_drift import (
    DataFingerprint, DriftReport, append_drift_log, compare_fingerprints,
    compute_fingerprint, load_drift_log,
)

_LEVEL = {
    "low": ("#15803d", "● low"),
    "moderate": ("#b45309", "● moderate"),
    "high": ("#b91c1c", "● high"),
    "info": ("#6b7280", "info"),
}
_REC = {
    "none": ("#15803d", "#f0fdf4", "✅ No retraining needed"),
    "monitor": ("#1d4ed8", "#eff6ff", "👀 Monitor"),
    "continue": ("#b45309", "#fffbeb", "▶ Continue training recommended"),
    "retrain": ("#b91c1c", "#fef2f2", "🔁 Retrain recommended"),
}


class FingerprintWorker(QThread):
    """Fingerprints the currently chosen mix off the UI thread."""

    finished_ok = pyqtSignal(object)  # DataFingerprint
    failed = pyqtSignal(str)

    def __init__(self, jsonl_path: Path, tasks: List[str],
                 recipe: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.jsonl_path, self.tasks, self.recipe = jsonl_path, tasks, recipe

    def run(self):  # noqa: D401 — Qt slot
        try:
            self.finished_ok.emit(compute_fingerprint(
                self.jsonl_path, tasks=self.tasks, recipe=self.recipe))
        except Exception as e:
            self.failed.emit(str(e))


class PerformanceWorker(QThread):
    """Scores the model on unseen examples (needs torch)."""

    log = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, **kwargs):
        super().__init__(kwargs.pop("parent", None))
        self.kwargs = kwargs

    def run(self):  # noqa: D401 — Qt slot
        try:
            from src.ai.drift_eval import evaluate_drift_performance
            self.finished_ok.emit(evaluate_drift_performance(
                log=self.log.emit, **self.kwargs))
        except Exception as e:
            self.failed.emit(str(e))


def drift_report_html(r: DriftReport) -> str:
    fg, bg, label = _REC.get(r.recommendation, _REC["none"])
    reasons = "".join(f"<li>{html.escape(x)}</li>" for x in r.reasons)
    rows = []
    for s in r.signals:
        c, lvl = _LEVEL.get(s.level, ("#374151", s.level))
        rows.append(
            f"<tr><td><b>{html.escape(s.name)}</b></td>"
            f"<td>{html.escape(s.value)}</td>"
            f"<td style='color:{c}'>{lvl}</td>"
            f"<td style='color:#6b7280'>{html.escape(s.explanation)}</td></tr>")
    recipe = ""
    if r.recipe_changes:
        recipe = ("<p><b>Recipe changes since training</b></p><ul>"
                  + "".join(f"<li>{html.escape(c)}</li>" for c in r.recipe_changes)
                  + "</ul>")
    return (
        f"<table width='100%' cellpadding='8' style='background:{bg}'><tr><td>"
        f"<b style='font-size:14px;color:{fg}'>{label}</b> "
        f"<span style='color:#6b7280'>(drift score {r.drift_score:.2f})</span><br>"
        f"{html.escape(r.headline)}<ul style='margin:4px 0 0 -20px'>{reasons}</ul>"
        f"</td></tr></table>"
        f"<p>Trained on <b>{r.baseline_unique:,}</b> unique examples"
        + (f" on {html.escape(r.trained_at[:10])}" if r.trained_at else "")
        + f"; the chosen mix now has <b>{r.current_unique:,}</b>.</p>"
        "<table cellpadding='3'><tr style='color:#6b7280'><td>Signal</td>"
        "<td>Value</td><td>Drift</td><td></td></tr>" + "".join(rows) + "</table>"
        + recipe)


def drift_history_html(history: List[Dict[str, Any]]) -> str:
    if not history:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(str(h.get('checked_at', ''))[:16])}</td>"
        f"<td>{html.escape(str(h.get('recommendation', '')))}</td>"
        f"<td align='right'>{h.get('drift_score', 0):.2f}</td>"
        f"<td align='right'>{h.get('new_fraction', 0):.0%}</td>"
        f"<td align='right'>{'×%.2f' % h['performance_ratio'] if h.get('performance_ratio') else '—'}</td></tr>"
        for h in history[-6:])
    return ("<p><b>Previous checks</b></p><table cellpadding='3'>"
            "<tr style='color:#6b7280'><td>When</td><td>Result</td><td>Score</td>"
            "<td>Unseen</td><td>Loss ratio</td></tr>" + rows + "</table>")


class ModelDriftDialog(QDialog):
    """Runs the drift check for one model and shows the result."""

    def __init__(self, *, model_name: str, model_dir: Path, base_model: str,
                 baseline: DataFingerprint, current_jsonl: Path,
                 current_tasks: List[str], current_recipe: Dict[str, Any],
                 baseline_loss: Optional[float],
                 on_continue: Callable[[], None],
                 on_retrain: Callable[[DataFingerprint], None],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Model drift — {model_name}")
        self.resize(820, 720)
        self.model_name, self.model_dir = model_name, Path(model_dir)
        self.base_model, self.baseline = base_model, baseline
        self.current_jsonl, self.baseline_loss = current_jsonl, baseline_loss
        self.on_continue, self.on_retrain = on_continue, on_retrain
        self.current: Optional[DataFingerprint] = None
        self.performance: Optional[Dict[str, Any]] = None
        self.report: Optional[DriftReport] = None
        self._logged = False  # this dialog's check is in the log

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.body_label = QLabel("Comparing the chosen mix with the model's "
                                 "training data…")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.body_label)
        self.perf_label = QLabel("")
        self.perf_label.setWordWrap(True)
        lay.addWidget(self.perf_label)
        self.history_label = QLabel(drift_history_html(load_drift_log(self.model_dir)))
        self.history_label.setWordWrap(True)
        lay.addWidget(self.history_label)
        lay.addStretch()

        btns = QHBoxLayout()
        self.perf_btn = QPushButton("🔬 Measure performance on unseen data")
        self.perf_btn.setToolTip(
            "Load the model and score up to 64 examples it never saw. "
            "Compares their loss with the model's validation loss at "
            "training time — the most direct drift measurement. Needs the "
            "training libraries; can take a few minutes for large bases.")
        self.perf_btn.setEnabled(False)
        self.perf_btn.clicked.connect(self._run_performance)
        btns.addWidget(self.perf_btn)
        btns.addStretch()
        self.continue_btn = QPushButton("▶ Continue training this model")
        self.continue_btn.setToolTip(
            "Train more on top of this model with the current mix "
            "(keeps what it learned, adds the new data).")
        self.continue_btn.clicked.connect(self._continue)
        self.retrain_btn = QPushButton("🔁 Retrain from base")
        self.retrain_btn.setToolTip(
            "Start a fresh fine-tune of the same base model on the current mix.")
        self.retrain_btn.clicked.connect(self._retrain)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        for b in (self.continue_btn, self.retrain_btn):
            b.setEnabled(False)
            btns.addWidget(b)
        btns.addWidget(close_btn)
        outer.addLayout(btns)

        self._fp_worker = FingerprintWorker(current_jsonl, current_tasks,
                                            current_recipe, parent=self)
        self._fp_worker.finished_ok.connect(self._on_current_fingerprint)
        self._fp_worker.failed.connect(
            lambda m: self.body_label.setText(
                f"<span style='color:#b91c1c'>Drift check failed: "
                f"{html.escape(m)}</span>"))
        self._fp_worker.start()

    def _on_current_fingerprint(self, fp: DataFingerprint) -> None:
        self.current = fp
        self._refresh(log=True)
        self.perf_btn.setEnabled(self.report is not None and self.report.new_examples > 0)
        if self.report is not None and self.report.new_examples == 0:
            self.perf_btn.setToolTip("No unseen examples to score.")

    def _refresh(self, *, log: bool) -> None:
        if self.current is None:
            return
        self.report = compare_fingerprints(
            self.baseline, self.current, model_name=self.model_name,
            performance=self.performance)
        self.body_label.setText(drift_report_html(self.report))
        for b in (self.continue_btn, self.retrain_btn):
            b.setEnabled(True)
        primary = ("QPushButton { background-color: #10b981; color: white; "
                   "padding: 5px 12px; border-radius: 5px; font-weight: bold; }")
        self.continue_btn.setStyleSheet(
            primary if self.report.recommendation == "continue" else "")
        self.retrain_btn.setStyleSheet(
            primary if self.report.recommendation == "retrain" else "")
        if log:
            try:
                append_drift_log(self.model_dir, self.report,
                                 replace_last=self._logged)
                self._logged = True
                self.history_label.setText(
                    drift_history_html(load_drift_log(self.model_dir)))
            except OSError:
                pass

    def _run_performance(self) -> None:
        self.perf_btn.setEnabled(False)
        self.perf_label.setText("<span style='color:#6b7280'>Loading the model "
                                "and scoring unseen examples…</span>")
        self._perf_worker = PerformanceWorker(
            model_dir=self.model_dir, base_model=self.base_model,
            jsonl_path=self.current_jsonl, baseline_keys=self.baseline.keys,
            baseline_loss=self.baseline_loss, parent=self)
        self._perf_worker.log.connect(
            lambda m: self.perf_label.setText(
                f"<span style='color:#6b7280'>{html.escape(m)}</span>"))
        self._perf_worker.finished_ok.connect(self._on_performance)
        self._perf_worker.failed.connect(self._on_performance_failed)
        self._perf_worker.start()

    def _on_performance(self, perf: Dict[str, Any]) -> None:
        self.performance = perf
        if perf.get("new_loss") is None:
            self.perf_label.setText(html.escape(perf.get("note", "Nothing to score.")))
        else:
            known = (f", {perf['known_loss']:.3f} on {perf['n_known']} examples it "
                     f"trained on" if perf.get("known_loss") is not None else "")
            base = (f"; validation loss at training was {perf['baseline_loss']:.3f}"
                    if perf.get("baseline_loss") else
                    "; no training-time validation loss is recorded for this model, "
                    "so there's no baseline to compare against")
            self.perf_label.setText(
                f"<b>Performance check:</b> loss {perf['new_loss']:.3f} on "
                f"{perf['n_new']} unseen examples{known}{base}.")
        self._refresh(log=True)

    def _on_performance_failed(self, msg: str) -> None:
        self.perf_btn.setEnabled(True)
        self.perf_label.setText(
            f"<span style='color:#b91c1c'>Performance check unavailable: "
            f"{html.escape(msg)}</span><br><span style='color:#6b7280'>The data "
            f"drift result above doesn't depend on it.</span>")

    def _continue(self) -> None:
        self.accept()
        self.on_continue()

    def _retrain(self) -> None:
        self.accept()
        self.on_retrain(self.baseline)
