"""The Critique as it runs: results as they are ready, and Stop.

* Each finished report appears in its tab straight away. The tab the writer
  is reading stays open at the same scroll position while others arrive.
* While a critique runs, **Run Critique** becomes **Stop** (no new button).
  Stopping keeps every finished report; running again with the same
  settings picks up where it stopped (``critique_parts``).
"""

from __future__ import annotations

from typing import Any

RUN_TEXT = "Run Critique"
STOP_TEXT = "Stop"


def watch_run(grader, worker) -> None:
    """Wire a started CritiqueWorker to the screen."""
    btn = grader.critique_btn
    partial = getattr(worker, "partial", None)
    if partial is None or not hasattr(worker, "finished"):
        btn.setEnabled(False)           # a stand-in worker: no Stop, as before
        return
    partial.connect(lambda report: _safe(show_partial, grader, report))

    def stop():
        worker.stop_requested = True
        btn.setText("Stopping…")
        btn.setEnabled(False)
        grader.status_label.setText("Stopping after the report in progress; finished "
                                    "reports are kept.")
        grader.status_label.setVisible(True)

    def restore(*_):
        try:
            btn.clicked.disconnect(stop)
        except (TypeError, RuntimeError):
            pass
        try:
            btn.clicked.connect(grader._run_reports)
        except RuntimeError:
            return
        btn.setText(RUN_TEXT)
        btn.setToolTip("Run the selected reports across the chosen scope.")
        btn.setEnabled(True)

    try:
        btn.clicked.disconnect(grader._run_reports)
    except (TypeError, RuntimeError):
        pass
    btn.clicked.connect(stop)
    btn.setText(STOP_TEXT)
    btn.setToolTip("Stop after the report in progress. Finished reports are kept; run "
                   "again with the same settings to finish.")
    btn.setEnabled(True)
    worker.finished.connect(restore)
    if hasattr(worker, "error"):
        worker.error.connect(restore)


def show_partial(grader, report) -> None:
    """Show the reports finished so far, keeping the writer's place."""
    tabs = grader.results_tabs
    current = tabs.tabText(tabs.currentIndex()) if tabs.count() else ""
    scroll = _scroll_of(tabs.currentWidget())
    done, total = getattr(report, "parts_done", 0), getattr(report, "parts_total", 0)
    report.overall_summary = (f"Working… {done} of {total} reports ready. Each report's tab "
                              "appears as soon as it is finished; you can read them while the "
                              "rest run.")
    grader._render_critique_report(report)
    for i in range(tabs.count()):
        if tabs.tabText(i) == current:
            tabs.setCurrentIndex(i)
            if scroll is not None:
                bar = _bar_of(tabs.widget(i))
                if bar is not None:
                    bar.setValue(scroll)
            break


def _bar_of(widget: Any):
    from PyQt6.QtWidgets import QTextBrowser
    if widget is None:
        return None
    if isinstance(widget, QTextBrowser):
        return widget.verticalScrollBar()
    found = widget.findChild(QTextBrowser)
    return found.verticalScrollBar() if found is not None else None


def _scroll_of(widget: Any):
    bar = _bar_of(widget)
    return bar.value() if bar is not None else None


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as e:              # an exception escaping a Qt slot aborts PyQt6
        print(f"[critique] could not show partial results: {e}")
