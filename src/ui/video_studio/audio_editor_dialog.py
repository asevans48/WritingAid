"""Audio editor — trim + denoise + gain for a single recorded
take.

Opens from any take that has audio (slide-deck slides, video
editor voiceover takes, scene-level voiceover segments). The
writer can preview, set in/out points, toggle denoise, dial
gain, and apply — either overwriting the source or saving as a
new file.

Backed by ``src.video_studio.audio_edit.edit_audio`` which uses
ffmpeg's ``afftdn`` / ``volume`` / ``-ss``/``-t`` filters.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from src.video_studio.audio_edit import (
    AudioEditResult, edit_audio, ffmpeg_available,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class AudioEditorDialog(QDialog):
    """Modeless audio editor.

    Constructor takes the source file plus an ``on_applied``
    callback that fires with ``(new_audio_path, new_duration)``
    when the writer applies edits. Hosts use the callback to
    point their model at the new file (and refresh display).
    """

    def __init__(
        self,
        source_path: Path,
        on_applied: Callable[[Path, float], None],
        title: str = "Edit audio",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(None)
        self.setWindowTitle(title)
        self.setModal(False)
        # ``Qt.Tool`` is the polite floater that doesn't steal
        # focus or minimize peers (see ChapterProseWindow for the
        # full rationale).
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        target_w = 560
        target_h = 520
        if avail is not None:
            target_w = max(440, min(target_w, int(avail.width() * 0.5)))
            target_h = max(420, min(target_h, int(avail.height() * 0.85)))
        self.resize(target_w, target_h)
        self.setMinimumSize(420, 420)
        self._source_path = source_path
        self._on_applied = on_applied
        self._duration_seconds = probe_audio_duration_seconds(
            source_path) or 0.0
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        info = QLabel(
            f"<b>{self._source_path.name}</b><br>"
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"{self._source_path}<br>"
            f"Duration: {self._duration_seconds:.2f} s</span>")
        info.setWordWrap(True)
        outer.addWidget(info)

        # Transport.
        transport = QHBoxLayout()
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.clicked.connect(self._on_play_pause)
        transport.addWidget(self._play_btn)
        self._replay_btn = QPushButton("⟲ Replay")
        self._replay_btn.clicked.connect(self._on_replay)
        transport.addWidget(self._replay_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        transport.addWidget(self._stop_btn)
        self._preview_trim_btn = QPushButton(
            "🎧 Preview trimmed range")
        self._preview_trim_btn.setToolTip(
            "Play just the portion between the In and Out points "
            "you've set below. Useful for verifying the cut "
            "without re-running the export.")
        self._preview_trim_btn.clicked.connect(
            self._on_preview_trim)
        transport.addWidget(self._preview_trim_btn)
        transport.addStretch()
        outer.addLayout(transport)
        self._status_label = QLabel("Ready.")
        self._status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        outer.addWidget(self._status_label)

        # Edits.
        edits = QGroupBox("Edits")
        form = QFormLayout(edits)
        # Trim.
        trim_row = QHBoxLayout()
        self._in_spin = QDoubleSpinBox()
        self._in_spin.setRange(0.0, max(0.0, self._duration_seconds))
        self._in_spin.setDecimals(3)
        self._in_spin.setSingleStep(0.1)
        self._in_spin.setSuffix(" s")
        self._in_spin.setToolTip(
            "Trim head — anything before this time is dropped.")
        trim_row.addWidget(QLabel("In:"))
        trim_row.addWidget(self._in_spin)
        self._out_spin = QDoubleSpinBox()
        self._out_spin.setRange(0.0, max(0.0, self._duration_seconds))
        self._out_spin.setDecimals(3)
        self._out_spin.setSingleStep(0.1)
        self._out_spin.setSuffix(" s")
        self._out_spin.setSpecialValueText("end of file")
        self._out_spin.setToolTip(
            "Trim tail — anything after this time is dropped. "
            "0 keeps the file's natural end.")
        trim_row.addWidget(QLabel("Out:"))
        trim_row.addWidget(self._out_spin)
        self._set_in_to_now_btn = QPushButton("Use playhead")
        self._set_in_to_now_btn.setToolTip(
            "Snap the In point to the player's current position.")
        self._set_in_to_now_btn.clicked.connect(
            self._on_snap_in_to_position)
        trim_row.addWidget(self._set_in_to_now_btn)
        self._set_out_to_now_btn = QPushButton("Use playhead")
        self._set_out_to_now_btn.setToolTip(
            "Snap the Out point to the player's current position.")
        self._set_out_to_now_btn.clicked.connect(
            self._on_snap_out_to_position)
        trim_row.addWidget(self._set_out_to_now_btn)
        wrap = QWidget(); wrap.setLayout(trim_row)
        form.addRow("Trim", wrap)

        # Denoise.
        self._denoise_check = QCheckBox("Reduce noise")
        self._denoise_check.setToolTip(
            "FFT-based noise reduction (ffmpeg's ``afftdn``). "
            "Effective against steady-state background hiss / "
            "fans / room hum.")
        form.addRow("", self._denoise_check)
        self._denoise_strength_spin = QDoubleSpinBox()
        self._denoise_strength_spin.setRange(-50.0, -5.0)
        self._denoise_strength_spin.setDecimals(1)
        self._denoise_strength_spin.setSingleStep(1.0)
        self._denoise_strength_spin.setSuffix(" dB noise floor")
        self._denoise_strength_spin.setValue(-25.0)
        self._denoise_strength_spin.setToolTip(
            "Noise-floor estimate. More negative is more "
            "aggressive — start at -25 dB and tune.")
        form.addRow(
            "Denoise strength",
            self._denoise_strength_spin)

        # Gain.
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(-30.0, 12.0)
        self._gain_spin.setDecimals(1)
        self._gain_spin.setSingleStep(0.5)
        self._gain_spin.setSuffix(" dB")
        self._gain_spin.setToolTip(
            "Positive boosts, negative attenuates. Recordings "
            "that came in hot can go to -6 dB; quiet ones to "
            "+3 to +6 dB.")
        form.addRow("Gain", self._gain_spin)

        # Normalize.
        self._normalize_check = QCheckBox(
            "Normalize to -16 LUFS (broadcast loudness)")
        self._normalize_check.setToolTip(
            "Apply EBU R128 single-pass ``loudnorm`` so every "
            "take sits at the same perceived volume. Recommended "
            "for multi-take projects.")
        form.addRow("", self._normalize_check)

        # De-esser (sibilance).
        self._deesser_spin = QDoubleSpinBox()
        self._deesser_spin.setRange(0.0, 1.0)
        self._deesser_spin.setDecimals(2)
        self._deesser_spin.setSingleStep(0.05)
        self._deesser_spin.setValue(0.0)
        self._deesser_spin.setToolTip(
            "Tame harsh 's'/'sh'/'ch' sounds. 0 = off; 0.4–0.6 is "
            "the usual range for close-mic'd dialog; higher starts "
            "to muffle consonants.")
        form.addRow("De-esser", self._deesser_spin)

        # High-pass (rumble removal).
        self._highpass_spin = QDoubleSpinBox()
        self._highpass_spin.setRange(0.0, 300.0)
        self._highpass_spin.setDecimals(0)
        self._highpass_spin.setSingleStep(10.0)
        self._highpass_spin.setSuffix(" Hz")
        self._highpass_spin.setSpecialValueText("Off")
        self._highpass_spin.setValue(0.0)
        self._highpass_spin.setToolTip(
            "Roll off low-frequency rumble / handling noise below "
            "this cutoff. 0 = off; 80–120 Hz suits most voice "
            "recordings.")
        form.addRow("High-pass", self._highpass_spin)

        # Fades.
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 10.0)
        self._fade_in_spin.setDecimals(2)
        self._fade_in_spin.setSingleStep(0.1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setToolTip(
            "Linear fade up from silence at the start of the "
            "(trimmed) take.")
        form.addRow("Fade in", self._fade_in_spin)
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 10.0)
        self._fade_out_spin.setDecimals(2)
        self._fade_out_spin.setSingleStep(0.1)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.setToolTip(
            "Linear fade down to silence at the end of the "
            "(trimmed) take.")
        form.addRow("Fade out", self._fade_out_spin)

        outer.addWidget(edits)

        # Save mode.
        mode_box = QGroupBox("Save mode")
        mv = QVBoxLayout(mode_box)
        self._mode_overwrite = QRadioButton(
            "Replace source file")
        self._mode_overwrite.setChecked(True)
        self._mode_overwrite.setToolTip(
            "Writes back over the original take. The slide / "
            "video editor's references stay the same.")
        mv.addWidget(self._mode_overwrite)
        self._mode_new = QRadioButton(
            "Save as new file (keep the original)")
        mv.addWidget(self._mode_new)
        outer.addWidget(mode_box)

        # Buttons.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        self._apply_btn = QPushButton("✅ Apply")
        self._apply_btn.clicked.connect(self._on_apply)
        buttons.addButton(
            self._apply_btn,
            QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.close)
        outer.addWidget(buttons)

        # Load the source for previewing.
        self._player.setSource(
            QUrl.fromLocalFile(str(self._source_path.resolve())))

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _on_play_pause(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.setText("▶ Resume")
            return
        if state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
            self._play_btn.setText("⏸ Pause")
            return
        # Stopped.
        self._player.play()
        self._play_btn.setText("⏸ Pause")

    def _on_replay(self) -> None:
        self._player.stop()
        self._player.setSource(
            QUrl.fromLocalFile(str(self._source_path.resolve())))
        self._player.setPosition(0)
        self._player.play()
        self._play_btn.setText("⏸ Pause")

    def _on_stop(self) -> None:
        self._player.stop()
        self._play_btn.setText("▶ Play")

    def _on_preview_trim(self) -> None:
        # Seek to the In point and let the player roll; the
        # writer can hit Stop when done.
        in_pt = float(self._in_spin.value() or 0.0)
        self._player.stop()
        self._player.setSource(
            QUrl.fromLocalFile(str(self._source_path.resolve())))
        self._player.setPosition(int(in_pt * 1000))
        self._player.play()
        self._play_btn.setText("⏸ Pause")

    def _on_snap_in_to_position(self) -> None:
        seconds = self._player.position() / 1000.0
        self._in_spin.setValue(seconds)

    def _on_snap_out_to_position(self) -> None:
        seconds = self._player.position() / 1000.0
        self._out_spin.setValue(seconds)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def _on_apply(self) -> None:
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Audio editing needs ffmpeg on PATH.")
            return
        in_pt = float(self._in_spin.value() or 0.0)
        out_pt = float(self._out_spin.value() or 0.0)
        denoise = self._denoise_check.isChecked()
        denoise_strength = float(
            self._denoise_strength_spin.value())
        gain = float(self._gain_spin.value())
        normalize = self._normalize_check.isChecked()
        deesser = float(self._deesser_spin.value())
        highpass = float(self._highpass_spin.value())
        fade_in = float(self._fade_in_spin.value())
        fade_out = float(self._fade_out_spin.value())
        if not (denoise or normalize
                or in_pt > 0 or out_pt > 0
                or abs(gain) > 0.001
                or deesser > 0 or highpass > 0
                or fade_in > 0 or fade_out > 0):
            QMessageBox.information(
                self, "No changes",
                "Set at least one edit (trim, denoise, de-esser, "
                "high-pass, gain, normalize, or fade) before "
                "applying.")
            return
        # Build the dest path.
        if self._mode_overwrite.isChecked():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            staging = (
                self._source_path.parent
                / f"{self._source_path.stem}_edit_{stamp}"
                f"{self._source_path.suffix}")
            dest = staging
            overwrite = True
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = (
                self._source_path.parent
                / f"{self._source_path.stem}_edit_{stamp}"
                f"{self._source_path.suffix}")
            overwrite = False
        # Stop playback so the file isn't held open during the
        # rewrite.
        self._player.stop()
        self._apply_btn.setEnabled(False)
        self._status_label.setText("Applying edits…")
        result: AudioEditResult = edit_audio(
            self._source_path, dest,
            in_point_seconds=in_pt,
            out_point_seconds=out_pt,
            denoise=denoise,
            denoise_strength_db=denoise_strength,
            gain_db=gain,
            normalize=normalize,
            deesser_intensity=deesser,
            highpass_hz=highpass,
            fade_in_seconds=fade_in,
            fade_out_seconds=fade_out)
        self._apply_btn.setEnabled(True)
        if not result.success:
            self._status_label.setText(
                f"Failed: {result.error}")
            QMessageBox.warning(
                self, "Edit failed", result.error)
            return
        if overwrite:
            try:
                self._source_path.unlink(missing_ok=True)
                dest.rename(self._source_path)
                dest = self._source_path
            except Exception as e:
                self._status_label.setText(
                    f"Saved as {dest.name} (overwrite failed: "
                    f"{e})")
        new_duration = result.duration_seconds
        if new_duration <= 0:
            new_duration = probe_audio_duration_seconds(dest)
        try:
            self._on_applied(dest, new_duration)
        except Exception as e:
            print(f"[audio_editor] on_applied failed: {e}")
        self._status_label.setText(
            f"Saved {dest.name} (~{new_duration:.2f} s).")
        # Refresh the player + in/out limits.
        self._duration_seconds = new_duration
        self._in_spin.setMaximum(max(0.0, new_duration))
        self._out_spin.setMaximum(max(0.0, new_duration))
        self._source_path = dest
        self._player.setSource(
            QUrl.fromLocalFile(str(dest.resolve())))

    def closeEvent(self, event) -> None:
        try:
            self._player.stop()
        except Exception:
            pass
        super().closeEvent(event)
