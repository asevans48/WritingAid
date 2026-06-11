"""Voiceover editor for a single scene.

Lets the writer:
  * Preview the scene's visuals (image, video clip, or slide deck).
  * Record a take from the system microphone via QMediaRecorder.
  * Import an existing audio file (mp3, wav, m4a, …).
  * Arrange multiple takes on a per-second timeline.
  * Trim each take (in / out points within the source).
  * Adjust per-take gain (dB), fade-in, fade-out, mute.
  * Anchor a take to a specific action so it auto-moves when the
    writer reorders the slide deck.

The stitcher honors these segments at mux time — see
``stitcher.mix_voiceover_segments`` for how the dB / fade /
trim values become ffmpeg ``filter_complex`` graph.

The dialog mutates ``scene.voiceover_segments`` in place. Caller
fires the studio's ``contentChanged`` signal on close so autosave
picks up the new takes.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtMultimedia import (
    QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaFormat,
    QMediaPlayer, QMediaRecorder, QMediaDevices,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from src.video_studio.models import Scene, VoiceoverSegment
from src.video_studio.tts.base import probe_audio_duration_seconds


_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac",
               ".aiff", ".aif", ".wma", ".opus"}


class VoiceoverEditorDialog(QDialog):
    """Dialog for arranging voiceover takes on a scene.

    Constructor wants ``audio_dir`` so recorded + imported files
    land in a stable per-scene folder. The host (scene editor)
    passes it from the studio root path; the dialog never has to
    care about the project's on-disk layout.
    """

    def __init__(
        self,
        scene: Scene,
        audio_dir: Path,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            f"Voiceover — {scene.name or 'Untitled scene'}")
        self.setModal(True)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_h = int(avail.height() * 0.9) if avail else 720
        max_w = int(avail.width() * 0.9) if avail else 1024
        self.resize(min(1024, max_w), min(720, max_h))
        self.setMinimumSize(720, 480)
        self._scene = scene
        self._audio_dir = Path(audio_dir)
        self._audio_dir.mkdir(parents=True, exist_ok=True)

        # Recording machinery — built lazily on first Record click
        # so PyQt6's audio plumbing doesn't spin up needlessly.
        self._record_session: Optional[QMediaCaptureSession] = None
        self._recorder: Optional[QMediaRecorder] = None
        self._audio_input: Optional[QAudioInput] = None
        self._record_target_path: Optional[Path] = None

        # Playback machinery — separate from recording so the
        # writer can play one take while preparing the next.
        self._player = QMediaPlayer(self)
        self._player_output = QAudioOutput(self)
        self._player.setAudioOutput(self._player_output)
        self._player.positionChanged.connect(
            self._on_player_position_changed)
        self._player.errorOccurred.connect(
            lambda *_: None)

        self._selected_segment_id: Optional[str] = None
        self._build_ui()
        self._refresh_segments()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        header = QLabel(
            "Record, import, and arrange voiceover takes for "
            "this scene. Multiple takes mix together at stitch "
            "time — layer narration over an ambient bed, drop "
            "stingers in front of slide flips, or split a long "
            "read into trimmed segments.")
        header.setWordWrap(True)
        header.setStyleSheet("color: #475569; font-size: 11px;")
        outer.addWidget(header)

        # Splitter: segment list on the left, segment detail
        # on the right.
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: segment list + add/import/record/delete ───────
        left = QWidget()
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)

        timeline_label = QLabel(
            f"Scene visual duration: ~{self._scene_visual_duration():.1f}s")
        timeline_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        left_v.addWidget(timeline_label)

        self._segment_list = QListWidget()
        self._segment_list.itemSelectionChanged.connect(
            self._on_segment_selected)
        left_v.addWidget(self._segment_list, stretch=1)

        actions_row = QHBoxLayout()
        self._import_btn = QPushButton("📥 Import…")
        self._import_btn.setToolTip(
            "Pick an existing audio file. It's copied into the "
            "scene's audio folder so the project stays portable.")
        self._import_btn.clicked.connect(self._on_import_file)
        actions_row.addWidget(self._import_btn)

        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip(
            "Record from the default system microphone. Click "
            "again to stop. The take lands at the end of the "
            "timeline; reposition by setting Start (s).")
        self._record_btn.clicked.connect(self._on_record_toggled)
        actions_row.addWidget(self._record_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setToolTip(
            "Drop the selected take from the timeline. The audio "
            "file on disk is left in place.")
        self._remove_btn.clicked.connect(self._on_remove_segment)
        actions_row.addWidget(self._remove_btn)
        actions_row.addStretch()
        left_v.addLayout(actions_row)

        splitter.addWidget(left)

        # ── Right: detail panel for the selected segment ─────────
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QScrollArea.Shape.NoFrame)
        right_inner = QWidget()
        right_v = QVBoxLayout(right_inner)

        detail_box = QGroupBox("Segment details")
        form = QFormLayout(detail_box)

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText(
            "Friendly label (e.g. 'intro', 'stinger')")
        self._label_edit.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow("Label", self._label_edit)

        self._anchor_combo = QComboBox()
        self._anchor_combo.addItem("None — use raw start time", "")
        for a in self._scene.actions:
            self._anchor_combo.addItem(
                f"Anchor to: {a.name or a.id}", a.id)
        self._anchor_combo.currentIndexChanged.connect(
            self._commit_segment_fields)
        form.addRow("Anchor", self._anchor_combo)

        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 600.0)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.1)
        self._start_spin.setSuffix(" s")
        self._start_spin.setToolTip(
            "Where this take starts on the scene's audio "
            "timeline. Ignored when an anchor is set — the "
            "anchor's slide-start time wins.")
        self._start_spin.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow("Start", self._start_spin)

        trim_row = QHBoxLayout()
        self._in_point_spin = QDoubleSpinBox()
        self._in_point_spin.setRange(0.0, 600.0)
        self._in_point_spin.setDecimals(2)
        self._in_point_spin.setSingleStep(0.1)
        self._in_point_spin.setSuffix(" s")
        self._in_point_spin.editingFinished.connect(
            self._commit_segment_fields)
        trim_row.addWidget(QLabel("In:"))
        trim_row.addWidget(self._in_point_spin)
        self._out_point_spin = QDoubleSpinBox()
        self._out_point_spin.setRange(0.0, 600.0)
        self._out_point_spin.setDecimals(2)
        self._out_point_spin.setSingleStep(0.1)
        self._out_point_spin.setSpecialValueText("end of source")
        self._out_point_spin.setSuffix(" s")
        self._out_point_spin.editingFinished.connect(
            self._commit_segment_fields)
        trim_row.addWidget(QLabel("Out:"))
        trim_row.addWidget(self._out_point_spin)
        form.addRow(
            "Trim (within source)",
            self._wrap_layout_as_widget(trim_row))

        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(-60.0, 20.0)
        self._gain_spin.setDecimals(1)
        self._gain_spin.setSingleStep(0.5)
        self._gain_spin.setSuffix(" dB")
        self._gain_spin.setToolTip(
            "Negative reduces volume; +6 ≈ double the perceived "
            "loudness. Stitcher applies this as the volume "
            "filter.")
        self._gain_spin.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow("Gain", self._gain_spin)

        fades_row = QHBoxLayout()
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 60.0)
        self._fade_in_spin.setDecimals(2)
        self._fade_in_spin.setSingleStep(0.1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.editingFinished.connect(
            self._commit_segment_fields)
        fades_row.addWidget(QLabel("Fade in:"))
        fades_row.addWidget(self._fade_in_spin)
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 60.0)
        self._fade_out_spin.setDecimals(2)
        self._fade_out_spin.setSingleStep(0.1)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.editingFinished.connect(
            self._commit_segment_fields)
        fades_row.addWidget(QLabel("Fade out:"))
        fades_row.addWidget(self._fade_out_spin)
        form.addRow(
            "Fades", self._wrap_layout_as_widget(fades_row))

        self._mute_check = QCheckBox("Mute this take")
        self._mute_check.setToolTip(
            "Skip this segment at mux without removing it — "
            "useful for A/B testing two reads.")
        self._mute_check.toggled.connect(
            self._commit_segment_fields)
        form.addRow("", self._mute_check)

        right_v.addWidget(detail_box)

        # ── Preview controls ─────────────────────────────────────
        preview_box = QGroupBox("Preview")
        preview_v = QVBoxLayout(preview_box)
        preview_v.addWidget(QLabel(
            "Play the selected take to verify trim points + "
            "fades. Use the external player for full visual "
            "review (image / video / slide deck)."))
        preview_row = QHBoxLayout()
        self._play_btn = QPushButton("▶ Play take")
        self._play_btn.clicked.connect(self._on_play_take)
        preview_row.addWidget(self._play_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop_take)
        preview_row.addWidget(self._stop_btn)
        self._open_visual_btn = QPushButton("👁 Open scene visual")
        self._open_visual_btn.setToolTip(
            "Open the scene's favorite image / video clip / "
            "stitched slide deck in the system viewer so you "
            "can review the visual side-by-side.")
        self._open_visual_btn.clicked.connect(
            self._on_open_visual)
        preview_row.addWidget(self._open_visual_btn)
        preview_row.addStretch()
        preview_v.addLayout(preview_row)

        self._playback_status = QLabel("Idle.")
        self._playback_status.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        preview_v.addWidget(self._playback_status)

        right_v.addWidget(preview_box)

        right_v.addStretch()
        right.setWidget(right_inner)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, stretch=1)

        # Dialog buttons. Close commits and dismisses; Cancel
        # discards by reverting in-memory edits — but since we
        # mutate the live scene throughout, "Cancel" really just
        # closes without further edits. We label it Close for
        # honesty.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

        # Disable details until something is selected.
        self._set_detail_panel_enabled(False)

    def _wrap_layout_as_widget(self, layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _scene_visual_duration(self) -> float:
        """How long the scene's visuals last. Used as the timeline
        end for segment editing. Honors slideshow mode (sum of
        action display_seconds) and target_duration_seconds."""
        target = float(
            self._scene.target_duration_seconds or 0.0)
        if target > 0:
            return target
        if self._scene.is_slideshow():
            total = 0.0
            scene_default = float(
                self._scene.image_display_seconds or 4.0)
            for a in self._scene.actions:
                if not a.included_images():
                    continue
                dur = float(a.display_seconds or 0.0) or scene_default
                total += dur
            if total > 0:
                return total
        return float(self._scene.image_display_seconds or 4.0)

    def _set_detail_panel_enabled(self, enabled: bool) -> None:
        for w in (self._label_edit, self._anchor_combo,
                  self._start_spin, self._in_point_spin,
                  self._out_point_spin, self._gain_spin,
                  self._fade_in_spin, self._fade_out_spin,
                  self._mute_check, self._play_btn,
                  self._stop_btn):
            w.setEnabled(enabled)

    def _selected_segment(self) -> Optional[VoiceoverSegment]:
        if self._selected_segment_id is None:
            return None
        for s in self._scene.voiceover_segments:
            if s.id == self._selected_segment_id:
                return s
        return None

    def _refresh_segments(self) -> None:
        self._segment_list.clear()
        for i, seg in enumerate(
                self._scene.voiceover_segments, start=1):
            name = seg.label or f"Take {i}"
            duration = seg.effective_duration()
            mark = " 🔇" if seg.muted else ""
            text = (
                f"{name}{mark}\n"
                f"  start {seg.start_at:.2f}s · "
                f"~{duration:.2f}s · {seg.gain_db:+.1f} dB")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, seg.id)
            self._segment_list.addItem(item)
        # Restore selection.
        for i in range(self._segment_list.count()):
            item = self._segment_list.item(i)
            if (item.data(Qt.ItemDataRole.UserRole)
                    == self._selected_segment_id):
                self._segment_list.setCurrentRow(i)
                return
        self._selected_segment_id = None
        self._set_detail_panel_enabled(False)

    def _on_segment_selected(self) -> None:
        item = self._segment_list.currentItem()
        if item is None:
            self._selected_segment_id = None
            self._set_detail_panel_enabled(False)
            return
        self._selected_segment_id = item.data(
            Qt.ItemDataRole.UserRole)
        seg = self._selected_segment()
        if seg is None:
            return
        self._set_detail_panel_enabled(True)
        # Block signals so loading values doesn't fire commits.
        for w in (self._label_edit, self._anchor_combo,
                  self._start_spin, self._in_point_spin,
                  self._out_point_spin, self._gain_spin,
                  self._fade_in_spin, self._fade_out_spin,
                  self._mute_check):
            w.blockSignals(True)
        self._label_edit.setText(seg.label)
        idx = self._anchor_combo.findData(
            seg.anchored_to_action_id or "")
        self._anchor_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._start_spin.setValue(float(seg.start_at))
        self._in_point_spin.setValue(float(seg.in_point))
        self._out_point_spin.setValue(float(seg.out_point))
        self._gain_spin.setValue(float(seg.gain_db))
        self._fade_in_spin.setValue(float(seg.fade_in_seconds))
        self._fade_out_spin.setValue(float(seg.fade_out_seconds))
        self._mute_check.setChecked(bool(seg.muted))
        for w in (self._label_edit, self._anchor_combo,
                  self._start_spin, self._in_point_spin,
                  self._out_point_spin, self._gain_spin,
                  self._fade_in_spin, self._fade_out_spin,
                  self._mute_check):
            w.blockSignals(False)
        # Start spin is only meaningful when no anchor is set.
        self._start_spin.setEnabled(
            seg.anchored_to_action_id in (None, ""))

    def _commit_segment_fields(self) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        seg.label = self._label_edit.text().strip()
        seg.anchored_to_action_id = (
            self._anchor_combo.currentData() or None)
        seg.start_at = float(self._start_spin.value())
        seg.in_point = float(self._in_point_spin.value())
        seg.out_point = float(self._out_point_spin.value())
        seg.gain_db = float(self._gain_spin.value())
        seg.fade_in_seconds = float(self._fade_in_spin.value())
        seg.fade_out_seconds = float(self._fade_out_spin.value())
        seg.muted = bool(self._mute_check.isChecked())
        seg.updated_at = datetime.now()
        self._refresh_segments()
        self._start_spin.setEnabled(
            seg.anchored_to_action_id in (None, ""))

    # ------------------------------------------------------------------
    # Import + record
    # ------------------------------------------------------------------
    def _on_import_file(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(
            self, "Import audio for voiceover", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac *.aiff "
            "*.opus);;All files (*)")
        if not picked:
            return
        for src_str in picked:
            src = Path(src_str)
            if src.suffix.lower() not in _AUDIO_EXTS:
                continue
            seg = self._import_audio_to_segment(src)
            if seg is not None:
                self._scene.voiceover_segments.append(seg)
        self._refresh_segments()

    def _import_audio_to_segment(
        self, src: Path,
    ) -> Optional[VoiceoverSegment]:
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            n = len(self._scene.voiceover_segments) + 1
            dest = self._audio_dir / (
                f"vo_{n:03d}_{stamp}{src.suffix.lower()}")
            shutil.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(
                self, "Import failed",
                f"Could not copy '{src.name}': {e}")
            return None
        duration = probe_audio_duration_seconds(dest)
        # New segment lands at the end of the current timeline so
        # writers can stack reads without overlap. They can drag
        # the start time afterward.
        start = self._next_free_timeline_position()
        return VoiceoverSegment(
            label=src.stem,
            audio_path=str(dest),
            source="imported",
            start_at=start,
            source_duration_seconds=duration,
        )

    def _next_free_timeline_position(self) -> float:
        """Return a start time after the latest existing segment so
        a fresh import / recording doesn't immediately overlap."""
        last_end = 0.0
        for s in self._scene.voiceover_segments:
            end = s.start_at + max(0.0, s.effective_duration())
            if end > last_end:
                last_end = end
        return round(last_end, 2)

    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        # Build the recording graph lazily so unused dialogs don't
        # claim the microphone.
        if self._recorder is None:
            self._record_session = QMediaCaptureSession(self)
            default_input = QMediaDevices.defaultAudioInput()
            self._audio_input = QAudioInput(default_input, self)
            self._record_session.setAudioInput(self._audio_input)
            self._recorder = QMediaRecorder(self)
            self._record_session.setRecorder(self._recorder)
            fmt = QMediaFormat()
            fmt.setFileFormat(QMediaFormat.FileFormat.Wave)
            fmt.setAudioCodec(QMediaFormat.AudioCodec.Wave)
            self._recorder.setMediaFormat(fmt)
            self._recorder.setQuality(
                QMediaRecorder.Quality.HighQuality)
            self._recorder.recorderStateChanged.connect(
                self._on_recorder_state_changed)
            self._recorder.errorOccurred.connect(
                self._on_recorder_error)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        n = len(self._scene.voiceover_segments) + 1
        self._record_target_path = self._audio_dir / (
            f"vo_{n:03d}_{stamp}_rec.wav")
        self._recorder.setOutputLocation(
            QUrl.fromLocalFile(
                str(self._record_target_path.resolve())))
        self._recorder.record()
        self._record_btn.setText("⏹ Stop recording")
        self._playback_status.setText(
            "Recording from default microphone…")

    def _stop_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()

    def _on_recorder_state_changed(self, state) -> None:
        if state == QMediaRecorder.RecorderState.StoppedState:
            self._record_btn.setText("🎤 Record")
            self._record_btn.blockSignals(True)
            self._record_btn.setChecked(False)
            self._record_btn.blockSignals(False)
            # If the target file exists + has bytes, attach as a
            # segment. PyQt6 sometimes writes the file after the
            # state change; retry once if missing.
            QTimer.singleShot(120, self._finalize_recording)

    def _finalize_recording(self) -> None:
        target = self._record_target_path
        if target is None:
            return
        if not target.exists() or target.stat().st_size == 0:
            # One retry in case QMediaRecorder hasn't flushed.
            QTimer.singleShot(
                400, self._finalize_recording_retry)
            return
        self._attach_recorded_segment(target)

    def _finalize_recording_retry(self) -> None:
        target = self._record_target_path
        if target is None:
            return
        if not target.exists() or target.stat().st_size == 0:
            self._playback_status.setText(
                "Recording finished but no audio file was "
                "written. Check microphone permissions.")
            return
        self._attach_recorded_segment(target)

    def _attach_recorded_segment(self, path: Path) -> None:
        duration = probe_audio_duration_seconds(path)
        seg = VoiceoverSegment(
            label=f"Recording {len(self._scene.voiceover_segments) + 1}",
            audio_path=str(path),
            source="recorded",
            start_at=self._next_free_timeline_position(),
            source_duration_seconds=duration,
        )
        self._scene.voiceover_segments.append(seg)
        self._selected_segment_id = seg.id
        self._refresh_segments()
        self._playback_status.setText(
            f"Captured {path.name} (~{duration:.2f}s).")
        self._record_target_path = None

    def _on_recorder_error(self, *_args) -> None:
        if self._recorder is None:
            return
        err = self._recorder.errorString() or "Unknown error"
        self._playback_status.setText(
            f"Recorder error: {err}")
        self._record_btn.blockSignals(True)
        self._record_btn.setChecked(False)
        self._record_btn.setText("🎤 Record")
        self._record_btn.blockSignals(False)

    # ------------------------------------------------------------------
    # Segment removal
    # ------------------------------------------------------------------
    def _on_remove_segment(self) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        reply = QMessageBox.question(
            self, "Remove take?",
            f"Drop '{seg.label or seg.id}' from the voiceover "
            "timeline? (The audio file on disk is kept.)")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._scene.voiceover_segments = [
            s for s in self._scene.voiceover_segments
            if s.id != seg.id]
        self._selected_segment_id = None
        self._refresh_segments()

    # ------------------------------------------------------------------
    # Preview playback
    # ------------------------------------------------------------------
    def _on_play_take(self) -> None:
        seg = self._selected_segment()
        if seg is None or not seg.audio_path:
            return
        path = Path(seg.audio_path)
        if not path.exists():
            self._playback_status.setText(
                f"Source missing: {path}")
            return
        self._player.stop()
        self._player.setSource(
            QUrl.fromLocalFile(str(path.resolve())))
        # Seek to in_point on play. The trim's out_point is
        # enforced by the position-changed handler so writers
        # hear the exact slice that will be muxed.
        if seg.in_point > 0:
            QTimer.singleShot(
                100, lambda: self._player.setPosition(
                    int(seg.in_point * 1000)))
        self._player.play()
        self._playback_status.setText(
            f"Playing {path.name}…")

    def _on_player_position_changed(self, ms: int) -> None:
        seg = self._selected_segment()
        if seg is None or seg.out_point <= 0:
            return
        if (seg.out_point > seg.in_point
                and ms >= seg.out_point * 1000):
            self._player.stop()
            self._playback_status.setText("Reached out-point.")

    def _on_stop_take(self) -> None:
        self._player.stop()
        self._playback_status.setText("Stopped.")

    def _on_open_visual(self) -> None:
        clip = self._scene.favorite_clip()
        if clip is None or not clip.file_path:
            QMessageBox.information(
                self, "No visual",
                "This scene has no favorite clip / image / slide "
                "deck yet. Generate one first.")
            return
        path = Path(clip.file_path)
        if not path.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"Favorite clip is recorded as {path} but the "
                "file isn't on disk.")
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(path.resolve())))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        # Stop playback + recording on close so we don't leak
        # the microphone or audio output.
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            if self._recorder is not None:
                self._recorder.stop()
        except Exception:
            pass
        super().closeEvent(event)
