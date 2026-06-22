"""Floating preview window for a compiled SlideGroup.

Pops out of the group editor's **🎬 Preview** button. Pipeline:

  1. Host builds a temp ``SlideDeckProject`` containing only
     this group's placed slides, with the group's composed
     overlay audio attached to slide 0 (the stitcher's audio
     mixer puts it at offset 0 and lets it play through the
     full video).
  2. ``stitch_slide_deck_to_mp4`` renders that to a temp MP4
     under the deck's working dir.
  3. This window opens with a ``QVideoWidget`` pointed at the
     freshly-rendered file and auto-plays.

The window stays open until the writer closes it; reopening
the preview after edits re-renders so the writer always sees
what they'd ship today.

Design choices:
  * ``Qt.Tool`` flag so it floats above the group editor
    without stealing focus on macOS (same pattern as the slide
    preview window).
  * Transport: play / pause / stop / restart. No scrubbing —
    the preview is short by design (one group).
  * Status footer shows the source MP4 path + duration so the
    writer can spot-check what was rendered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)


class GroupPreviewWindow(QDialog):
    """Plays the rendered group MP4 in a floating window."""

    def __init__(
        self,
        video_path: Path,
        group_name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(None)
        self.setWindowTitle(
            f"🎬 Group preview — {group_name or 'group'}")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        target_w = 800
        target_h = 540
        if avail is not None:
            target_w = max(
                420, min(target_w, int(avail.width() * 0.7)))
            target_h = max(
                320, min(target_h, int(avail.height() * 0.7)))
        self.resize(target_w, target_h)
        self.setMinimumSize(360, 240)
        self._video_path = Path(video_path)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._video_widget = QVideoWidget()
        self._player.setVideoOutput(self._video_widget)
        self._player.playbackStateChanged.connect(
            lambda *_: self._refresh_play_button())
        self._player.errorOccurred.connect(
            self._on_player_error)
        self._build_ui()
        if self._video_path.exists():
            self._player.setSource(
                QUrl.fromLocalFile(
                    str(self._video_path.resolve())))
            self._player.play()
        else:
            self._status.setText(
                f"⚠️ Preview file missing: "
                f"{self._video_path}")

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(self._video_widget, stretch=1)
        controls = QHBoxLayout()
        self._play_btn = QPushButton("⏸ Pause")
        self._play_btn.clicked.connect(self._on_play_pause)
        controls.addWidget(self._play_btn)
        restart_btn = QPushButton("⟲ Restart")
        restart_btn.setToolTip(
            "Rewind to the start and play from the top.")
        restart_btn.clicked.connect(self._on_restart)
        controls.addWidget(restart_btn)
        stop_btn = QPushButton("■ Stop")
        stop_btn.clicked.connect(self._player.stop)
        controls.addWidget(stop_btn)
        controls.addStretch()
        self._status = QLabel(
            f"Source: {self._video_path.name}")
        self._status.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        controls.addWidget(self._status)
        v.addLayout(controls)

    def _on_play_pause(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_restart(self) -> None:
        self._player.setPosition(0)
        self._player.play()

    def _refresh_play_button(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setText("⏸ Pause")
        else:
            self._play_btn.setText("▶ Play")

    def _on_player_error(self, *args) -> None:
        try:
            err = self._player.errorString() or "Unknown error"
        except Exception:
            err = "Unknown error"
        self._status.setText(f"⚠ Player error: {err}")

    def closeEvent(self, event) -> None:
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        super().closeEvent(event)
