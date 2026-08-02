"""Record a short webcam + mic video to a file via ffmpeg.

There is no Qt camera capture in this app (the multimedia recorders are
audio-only and, on macOS, unreliable), so this shells out to ffmpeg's
platform camera input — ``avfoundation`` on macOS, ``dshow`` on
Windows, ``v4l2`` + ALSA on Linux. The clip is used as a "video"
element on a designed slide. No live preview: a red dot + elapsed
timer while recording, then Stop writes a clean file.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QProcess, QTimer, QElapsedTimer, Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)


def _ffmpeg_camera_args(out_path: str) -> Optional[list]:
    """Return the ffmpeg argument list (after the binary) to record
    the default camera + mic to ``out_path`` for this platform, or
    None when the platform isn't supported."""
    if sys.platform == "darwin":
        return [
            "-y", "-f", "avfoundation", "-framerate", "30",
            "-i", "0:0",
            "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "veryfast", out_path]
    if sys.platform.startswith("win"):
        return [
            "-y", "-f", "dshow",
            "-i", "video=default:audio=default",
            "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "veryfast", out_path]
    if sys.platform.startswith("linux"):
        return [
            "-y", "-f", "v4l2", "-i", "/dev/video0",
            "-f", "alsa", "-i", "default",
            "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "veryfast", out_path]
    return None


class VideoRecordDialog(QDialog):
    """Modal recorder. On accept, ``output_path`` holds the recorded
    file; it's None if the writer cancelled or recording failed."""

    def __init__(self, dest_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🎥 Record video")
        self.resize(360, 180)
        self.output_path: Optional[str] = None
        self._dest_dir = dest_dir
        self._proc: Optional[QProcess] = None
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        self._status = QLabel(
            "Ready. Recording uses your default camera + microphone.\n"
            "The first time, your OS may ask for camera/mic "
            "permission.")
        self._status.setWordWrap(True)
        v.addWidget(self._status)
        self._clock = QLabel("● 00:00")
        self._clock.setStyleSheet(
            "font-size: 22px; color: #c0392b;")
        self._clock.setVisible(False)
        v.addWidget(self._clock, alignment=Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout()
        self._record_btn = QPushButton("● Start recording")
        self._record_btn.clicked.connect(self._on_record)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        row.addWidget(self._record_btn)
        row.addWidget(self._stop_btn)
        row.addStretch()
        row.addWidget(self._cancel_btn)
        w = QWidget()
        w.setLayout(row)
        v.addWidget(w)

    def _on_record(self) -> None:
        args = _ffmpeg_camera_args("")
        if args is None:
            QMessageBox.warning(
                self, "Unsupported",
                "Video recording isn't supported on this platform "
                "here. Use 'Choose file…' to import a clip instead.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(Path(self._dest_dir) / f"rec_{stamp}.mp4")
        args = _ffmpeg_camera_args(out)
        self.output_path = out
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._proc.start("ffmpeg", args)
        if not self._proc.waitForStarted(4000):
            QMessageBox.warning(
                self, "Could not start",
                "ffmpeg did not start. Make sure ffmpeg is installed "
                "and on your PATH.")
            self._proc = None
            self.output_path = None
            return
        self._record_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status.setText(
            "Recording… click Stop when you're done.")
        self._clock.setVisible(True)
        self._elapsed.restart()
        self._timer.start(500)

    def _tick(self) -> None:
        secs = self._elapsed.elapsed() // 1000
        self._clock.setText(f"● {secs // 60:02d}:{secs % 60:02d}")

    def _on_stop(self) -> None:
        self._timer.stop()
        self._stop_btn.setEnabled(False)
        self._status.setText("Finishing the file…")
        if self._proc is not None:
            # 'q' tells ffmpeg to stop cleanly and finalize the moov
            # atom (a hard kill would leave an unplayable file).
            try:
                self._proc.write(b"q")
                self._proc.closeWriteChannel()
            except Exception:
                pass
            if not self._proc.waitForFinished(6000):
                self._proc.terminate()
                self._proc.waitForFinished(2000)

    def _on_proc_finished(self, *args) -> None:
        self._timer.stop()
        path = self.output_path
        if path and Path(path).exists() and Path(path).stat().st_size > 0:
            self.accept()
        else:
            QMessageBox.warning(
                self, "Recording failed",
                "No video was captured. Your OS may have blocked "
                "camera/mic access, or the default device wasn't "
                "available. Try 'Choose file…' to import a clip.")
            self.output_path = None
            self._record_btn.setEnabled(True)
            self._cancel_btn.setEnabled(True)
            self._clock.setVisible(False)

    def _on_proc_error(self, *args) -> None:
        # Surfaced by the finished handler's size check; keep the
        # dialog open so the writer can retry or cancel.
        self._timer.stop()
