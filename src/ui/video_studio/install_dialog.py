"""In-app installer for video backends.

The runner executes ``InstallStep``s in a background thread, streams
each subprocess's stdout/stderr line-by-line into the UI, and lets
the user cancel mid-step (sends SIGTERM, then SIGKILL after 5s if
still running). Each step's ``check`` re-runs after the subprocess
exits — when it returns True, the step is marked complete even if
the subprocess return code is non-zero (some pip / huggingface CLI
flows succeed with weird exit codes).

The dialog confirms multi-GB downloads up front, with the cumulative
size visible to the user before they commit.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from src.video_studio.backends.base import InstallStep, VideoBackend


# tqdm progress lines look like:
#   Downloading shards:  45%|████▌     | 4/9 [01:23<01:33, 18.71s/it]
#   weights.bin: 100%|██████████| 9.86G/9.86G [03:21<00:00, 49.0MB/s]
# We grab the percentage so the dialog's per-step progress bar can
# move in real time. Anchored to a digit-then-percent token so we
# don't pick up unrelated numbers in stdout.
_PCT_RE = re.compile(r"(\d{1,3})\s*%")


def _parse_percent(line: str) -> Optional[int]:
    """Return the first 0–100 percentage in ``line``, or None.

    Skips numbers like ``150%`` (some tools quote scaling factors)
    by clamping to the valid range — anything outside [0, 100] is
    treated as "not a progress percentage".
    """
    m = _PCT_RE.search(line)
    if not m:
        return None
    val = int(m.group(1))
    if 0 <= val <= 100:
        return val
    return None


def _iter_progress_lines(stream, cancel_check):
    """Yield logical "lines" from ``stream``, splitting on both
    ``\\n`` and ``\\r`` so tqdm-style progress (which only emits
    ``\\r``) flows in real time instead of buffering until the
    download finishes.

    Reads one character at a time. CPython handles single-char
    text-mode reads fast enough that this isn't a bottleneck for
    typical download throughput, and it dodges the OS-level line
    buffering that ``for line in stream`` falls into. Reads stop
    promptly on ``cancel_check`` so Cancel feels responsive.
    """
    buf = []
    while True:
        if cancel_check():
            break
        try:
            ch = stream.read(1)
        except Exception:
            break
        if not ch:
            # EOF — drain any trailing buffer as one last line.
            tail = "".join(buf).rstrip()
            if tail:
                yield tail
            return
        if ch == "\n" or ch == "\r":
            if buf:
                line = "".join(buf).rstrip()
                buf = []
                if line:
                    yield line
        else:
            buf.append(ch)


def _humanize_bytes(n: int) -> str:
    """Pretty bytes: 1.4 GB / 280 MB / 96 KB."""
    if n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------
# Runner — QThread
# ---------------------------------------------------------------------
class InstallRunner(QThread):
    """Background runner for a sequence of InstallSteps.

    Emits:
      * stepStarted(index, label)
      * stepLine(index, text)         — single stdout/stderr line
      * stepFinished(index, success, message)
      * finished()                    — Qt default; emitted when run() returns

    Cancellation is cooperative: ``request_cancel()`` sends SIGTERM
    to the active subprocess and sets a flag; the run loop notices
    the flag after the current step exits and stops.
    """
    stepStarted = pyqtSignal(int, str)
    stepLine = pyqtSignal(int, str)
    stepProgress = pyqtSignal(int, int)        # step_idx, percent 0-100
    stepFinished = pyqtSignal(int, bool, str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        steps: List[InstallStep],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._steps = steps
        self._cancel = False
        self._active_proc: Optional[subprocess.Popen] = None
        # Successful steps so the caller can render check marks even
        # after cancel.
        self.results: List[bool] = []

    def _cancel_check(self) -> bool:
        """Used by the line iterator to break out promptly when the
        user clicks Cancel mid-stream."""
        return self._cancel

    def request_cancel(self) -> None:
        self._cancel = True
        proc = self._active_proc
        if proc is None:
            return
        # Try a graceful term first, then escalate.
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
        except Exception:
            pass

        def _kill_after_grace() -> None:
            time.sleep(5)
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        threading.Thread(target=_kill_after_grace, daemon=True).start()

    def run(self) -> None:
        for idx, step in enumerate(self._steps):
            if self._cancel:
                self.cancelled.emit()
                return
            self.stepStarted.emit(idx, step.label)
            # Idempotency — skip the work when the check already
            # succeeds (e.g. user re-runs the installer after a
            # previous partial completion).
            try:
                if step.check is not None and step.check():
                    self.stepLine.emit(
                        idx, "(already satisfied — skipped)")
                    self.results.append(True)
                    self.stepFinished.emit(
                        idx, True, "Already installed.")
                    continue
            except Exception:
                # Check function shouldn't raise but we treat any
                # error as "not satisfied — proceed".
                pass

            success, message = self._run_one(idx, step)
            self.results.append(success)
            self.stepFinished.emit(idx, success, message)
            if not success and step.required:
                # Stop the chain on the first hard failure; downstream
                # steps depend on this one's output.
                return
        # All done — Qt emits finished() automatically.

    def _run_one(
        self, idx: int, step: InstallStep,
    ) -> tuple:
        # Pre-flight: command exists?
        if not step.command:
            return False, "Step has no command."
        cmd_head = step.command[0]
        # Allow argv[0] to be ``sys.executable`` (full path) or a
        # CLI on PATH. Only check PATH-relative names.
        if "/" not in cmd_head and "\\" not in cmd_head:
            if shutil.which(cmd_head) is None:
                # Sometimes argv[0] is "huggingface-cli" but only the
                # python module is installed. Fall through to the
                # subprocess invocation; it'll error cleanly.
                pass
        # Build the subprocess environment. Start from the parent's
        # env (PATH / venv / locale) and merge step.env_overrides on
        # top — that's how backends inject secrets like HF_TOKEN
        # without putting them in argv. We also force a few download-
        # friendly flags so progress streams in real time:
        #   * PYTHONUNBUFFERED=1: stops Python from buffering stdout
        #   * HF_HUB_DISABLE_PROGRESS_BARS=0: explicit "yes show bars"
        #   * TQDM_MININTERVAL=0.25: cap the update rate at 4 Hz
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
        env.setdefault("TQDM_MININTERVAL", "0.25")
        if step.env_overrides:
            env.update(step.env_overrides)
        try:
            self._active_proc = subprocess.Popen(
                step.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=step.cwd,
                env=env,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError as e:
            return False, f"Command not found: {e}"
        except Exception as e:
            return False, f"Could not start subprocess: {e}"

        try:
            assert self._active_proc.stdout is not None
            for line in _iter_progress_lines(
                    self._active_proc.stdout, self._cancel_check):
                # Mirror to the console with a step prefix so the
                # user can also watch download progress from a
                # terminal (useful when the dialog log is hidden
                # behind another window).
                try:
                    print(f"  [{step.label}] {line}", flush=True)
                except Exception:
                    # ``print`` can fail on Windows when the app is
                    # built without a console; degrade silently.
                    pass
                self.stepLine.emit(idx, line)
                # Best-effort percentage parse for the dialog's
                # progress bar. ``_parse_percent`` returns None when
                # the line doesn't carry one.
                pct = _parse_percent(line)
                if pct is not None:
                    self.stepProgress.emit(idx, pct)
            rc = self._active_proc.wait()
        finally:
            self._active_proc = None

        if self._cancel:
            return False, "Cancelled."

        # The check is the authority — some commands exit non-zero
        # but still succeed; others exit zero but the install wasn't
        # actually completed.
        if step.check is not None:
            try:
                if step.check():
                    return True, (
                        f"OK (exit {rc}, check passed)."
                        if rc != 0 else "OK.")
                return False, (
                    f"Check failed after exit code {rc}. "
                    f"See log above.")
            except Exception as e:
                return False, f"Check raised: {e}"
        # No check — trust exit code.
        if rc == 0:
            return True, "OK."
        return False, f"Subprocess exited {rc}. See log above."


# ---------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------
class InstallDialog(QDialog):
    """Modal dialog walking the user through a backend's install.

    Pre-confirms the install if any step is marked
    ``is_large_download``. Streams each step's output into a log
    pane. Cancel is wired to ``InstallRunner.request_cancel`` so the
    UI stays responsive even when a multi-hour download is running.
    """

    def __init__(
        self,
        backend: VideoBackend,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._backend = backend
        self._steps = backend.install_steps()
        self._runner: Optional[InstallRunner] = None
        self.setWindowTitle(f"Install {backend.label}")
        self.setModal(True)
        self.resize(760, 600)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(
            f"<b>{self._backend.label}</b> — "
            f"{self._backend.description}")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Cumulative size summary
        total_bytes = sum(s.bytes_estimate for s in self._steps)
        large_steps = [s for s in self._steps if s.is_large_download]
        size_line = QLabel(
            f"Estimated total download: "
            f"<b>{_humanize_bytes(total_bytes)}</b>"
            + (f" — <span style='color:#b91c1c'>"
               f"includes large download(s); confirm before "
               f"starting.</span>" if large_steps else ""))
        size_line.setTextFormat(Qt.TextFormat.RichText)
        size_line.setWordWrap(True)
        layout.addWidget(size_line)

        # Step list
        self._step_list = QListWidget()
        self._step_items: List[QListWidgetItem] = []
        for i, step in enumerate(self._steps):
            badge = ""
            if step.is_large_download:
                badge = "  (large download)"
            elif not step.required:
                badge = "  (optional)"
            item = QListWidgetItem(f"○  {step.label}{badge}")
            self._step_list.addItem(item)
            self._step_items.append(item)
        layout.addWidget(self._step_list)

        # Progress bar — sub-step granularity. We use a 0–1000 range
        # so we can represent "step 3 of 5, 47% into this step" as
        # 2*200 + 200*47/100 = 494 / 1000. The label tells the user
        # which step is happening; the bar's tick is the current
        # step's tqdm percentage.
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # Output log
        log_label = QLabel("Output:")
        layout.addWidget(log_label)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        font = QFont("Menlo", 10)
        self._log.setFont(font)
        layout.addWidget(self._log, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start install")
        self._start_btn.clicked.connect(self._on_start)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        # Initial state — nothing running.
        self._cancel_btn.setEnabled(False)

        if not self._steps:
            # Backend has no install steps — show text-only help.
            self._log.setPlainText(self._backend.install_instructions())
            self._start_btn.setEnabled(False)
            self._start_btn.setText(
                "No in-app installer for this backend")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        # Pre-confirm large downloads.
        large_steps = [
            s for s in self._steps if s.is_large_download]
        if large_steps:
            sizes = ", ".join(
                _humanize_bytes(s.bytes_estimate) for s in large_steps)
            reply = QMessageBox.question(
                self, "Confirm large download",
                f"This install will download:\n  {sizes}\n\n"
                "The download may take a long time and consumes "
                "significant disk space. Continue?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._close_btn.setEnabled(False)
        self._log.appendPlainText(
            f"Starting install of {self._backend.label}…\n")
        self._runner = InstallRunner(self._steps, parent=self)
        self._runner.stepStarted.connect(self._on_step_started)
        self._runner.stepLine.connect(self._on_step_line)
        self._runner.stepProgress.connect(self._on_step_progress)
        self._runner.stepFinished.connect(self._on_step_finished)
        self._runner.cancelled.connect(self._on_cancelled)
        self._runner.finished.connect(self._on_runner_finished)
        self._runner.start()

    def _on_cancel(self) -> None:
        if self._runner is None:
            return
        self._cancel_btn.setEnabled(False)
        self._log.appendPlainText(
            "\n(cancelling — sending SIGTERM; will SIGKILL after 5s "
            "if needed)\n")
        self._runner.request_cancel()

    def _on_step_started(self, idx: int, label: str) -> None:
        item = self._step_items[idx]
        item.setText(f"▶  {label}  (running…)")
        self._log.appendPlainText(f"\n--- Step {idx + 1}: {label} ---")

    def _on_step_line(self, idx: int, text: str) -> None:
        self._log.appendPlainText(text)

    def _on_step_progress(self, idx: int, percent: int) -> None:
        """Move the bar to ``step_idx + percent / 100`` of the
        total. Lets users see download progress accumulate in real
        time instead of jumping from "step 1 done" to "step 2 done"
        with a long blank in between."""
        n = max(1, len(self._steps))
        per_step = 1000 // n
        value = idx * per_step + int(per_step * percent / 100)
        self._progress.setValue(min(value, 1000))

    def _on_step_finished(
        self, idx: int, success: bool, message: str,
    ) -> None:
        item = self._step_items[idx]
        step = self._steps[idx]
        suffix = ""
        if step.is_large_download:
            suffix = "  (large download)"
        if success:
            item.setText(f"✓  {step.label}{suffix}")
        else:
            item.setText(f"✗  {step.label}{suffix} — {message}")
        self._log.appendPlainText(f"({message})")
        # Snap the progress bar to the completed step.
        n = max(1, len(self._steps))
        self._progress.setValue(
            min((idx + 1) * (1000 // n), 1000))

    def _on_cancelled(self) -> None:
        self._log.appendPlainText("\n(cancelled by user)\n")

    def _on_runner_finished(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        # Re-enable Start so the user can retry failed steps.
        self._start_btn.setEnabled(True)
        self._start_btn.setText("Re-run install")
        # Final status line.
        if self._backend.is_installed():
            self._log.appendPlainText(
                "\n✓ Backend reports installed. You can close this "
                "dialog and start generating.")
        else:
            self._log.appendPlainText(
                "\nBackend still reports not installed. Check the "
                "failures above; you may need to address them "
                "manually.")

    # Block close while runner is active so users don't accidentally
    # leave a multi-hour download orphaned without cancelling.
    def closeEvent(self, event) -> None:
        if self._runner is not None and self._runner.isRunning():
            reply = QMessageBox.question(
                self, "Install in progress",
                "An install is still running. Cancel it before "
                "closing?")
            if reply == QMessageBox.StandardButton.Yes:
                self._runner.request_cancel()
                self._runner.wait(8000)  # up to 8s for graceful exit
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
