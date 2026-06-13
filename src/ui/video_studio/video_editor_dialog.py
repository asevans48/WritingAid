"""Post-stitch video editor — lay voiceover over a finished MP4.

Opens after the studio's "Stitch favorites" finishes (or on
demand when the writer wants to revise a finished render). Loads
the source MP4 into a QMediaPlayer for preview, lets the writer
record / import / arrange voiceover takes on a master timeline
that maps to the video's running time, and exports a muxed copy.

Reuses ``mix_voiceover_segments`` from the stitcher and
``mux_audio`` to mate the resulting voice track with the video.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtMultimedia import (
    QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaFormat,
    QMediaPlayer, QMediaRecorder, QMediaDevices,
)
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from src.video_studio.models import VoiceoverSegment
from src.video_studio.stitcher import (
    ffmpeg_available, mix_voiceover_segments, mux_audio,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class VideoEditorDialog(QDialog):
    """Voiceover-over-video editor for a finished MP4.

    ``source_path`` is the MP4 the writer just stitched (or any
    other video they want to revise). ``working_dir`` is where
    recordings and the exported muxed copy land.
    """

    def __init__(
        self,
        source_path: Path,
        working_dir: Path,
        chapters_provider=None,
        save_chapter_text=None,
        open_in_writer=None,
        parent: Optional[QWidget] = None,
    ):
        # Independent top-level so the writer can keep it open
        # while iterating in the studio window. Modal video editors
        # had a habit of opening behind the parent on macOS and
        # never being seen — non-modal sidesteps that entirely.
        super().__init__(None)
        self.setWindowTitle(f"Video editor — {source_path.name}")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        # Pull-on-open callback that returns the project's chapter
        # snapshots — a list of (chapter_id, label, text). The
        # "Read chapter prose" button uses it to spawn a non-modal
        # reading window. None disables the affordance.
        self._chapters_provider = chapters_provider
        # Optional save-back + jump-to-writer callbacks for the
        # slim editor inside the prose window. Allows quick typo
        # fixes without leaving the video editor and a clean
        # handoff back to the main writer when needed.
        self._save_chapter_text_cb = save_chapter_text
        self._open_in_writer_cb = open_in_writer
        self._prose_window = None
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Compute a comfortable starting size that falls back
        # gracefully when the screen geometry isn't reachable
        # (headless tests, broken multi-monitor setups, etc.) —
        # never resize to a zero / negative dimension or the dialog
        # would render invisible.
        target_w = 1100
        target_h = 720
        if avail is not None:
            target_w = max(820, min(target_w, int(avail.width() * 0.9)))
            target_h = max(540, min(target_h, int(avail.height() * 0.85)))
        self.resize(target_w, target_h)
        self.setMinimumSize(820, 540)
        self._source_path = source_path
        self._working_dir = working_dir
        self._working_dir.mkdir(parents=True, exist_ok=True)
        self._video_duration_seconds = (
            probe_audio_duration_seconds(source_path) or 0.0)

        self._voiceovers: List[VoiceoverSegment] = []
        self._selected_id: Optional[str] = None

        # Playback (video + audio).
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        self._video_widget = QVideoWidget()
        self._player.setVideoOutput(self._video_widget)
        self._player.positionChanged.connect(
            self._on_video_position_changed)

        # Recording.
        self._record_session: Optional[QMediaCaptureSession] = None
        self._recorder: Optional[QMediaRecorder] = None
        self._audio_input: Optional[QAudioInput] = None
        self._record_target_path: Optional[Path] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        header = QLabel(
            "Record narration over the finished video. The video "
            "keeps its own audio; voiceover takes mix over the top "
            "at the offset you set. Export saves a muxed copy.")
        header.setWordWrap(True)
        header.setStyleSheet("color: #475569; font-size: 11px;")
        outer.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: video preview + transport ─────────────────────
        left = QWidget()
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.addWidget(self._video_widget, stretch=1)
        controls = QHBoxLayout()
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.clicked.connect(self._on_play_video)
        controls.addWidget(self._play_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop_video)
        controls.addWidget(self._stop_btn)
        self._position_label = QLabel("0.00 / "
                                      f"{self._video_duration_seconds:.2f} s")
        self._position_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        controls.addWidget(self._position_label)
        controls.addStretch()
        self._read_prose_btn = QPushButton("📖 Read chapter prose")
        self._read_prose_btn.setToolTip(
            "Open the chapter's prose in a floating window so you "
            "can scroll through it while recording. The window "
            "stays on top by default.")
        self._read_prose_btn.clicked.connect(self._on_read_prose)
        controls.addWidget(self._read_prose_btn)
        self._publish_btn = QPushButton("📤 Publish…")
        self._publish_btn.setToolTip(
            "Upload this video to YouTube, TikTok, or other "
            "platforms with metadata (title, description, tags, "
            "privacy, thumbnail). Credentials are stored in your "
            "system keychain.")
        self._publish_btn.clicked.connect(self._on_publish_clicked)
        controls.addWidget(self._publish_btn)
        left_v.addLayout(controls)
        splitter.addWidget(left)

        # ── Right: voiceover list + per-take controls ───────────
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QScrollArea.Shape.NoFrame)
        right_inner = QWidget()
        right_v = QVBoxLayout(right_inner)
        right_v.addWidget(QLabel("Voiceover takes:"))
        self._vo_list = QListWidget()
        self._vo_list.itemSelectionChanged.connect(
            self._on_take_selected)
        right_v.addWidget(self._vo_list, stretch=1)

        take_btns = QHBoxLayout()
        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.clicked.connect(self._on_record_toggled)
        self._import_btn = QPushButton("📥 Import…")
        self._import_btn.clicked.connect(self._on_import)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        take_btns.addWidget(self._record_btn)
        take_btns.addWidget(self._import_btn)
        take_btns.addWidget(self._remove_btn)
        take_btns.addStretch()
        right_v.addLayout(take_btns)

        detail_box = QGroupBox("Selected take")
        form = QFormLayout(detail_box)
        self._label_edit = QLineEdit()
        self._label_edit.editingFinished.connect(self._commit_take)
        form.addRow("Label", self._label_edit)
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 36000.0)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.25)
        self._start_spin.setSuffix(" s")
        self._start_spin.setToolTip(
            "Where the take begins on the video's timeline. Use "
            "the video preview to find the right moment.")
        self._start_spin.editingFinished.connect(self._commit_take)
        form.addRow("Start at", self._start_spin)
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(-60.0, 20.0)
        self._gain_spin.setDecimals(1)
        self._gain_spin.setSingleStep(0.5)
        self._gain_spin.setSuffix(" dB")
        self._gain_spin.editingFinished.connect(self._commit_take)
        form.addRow("Gain", self._gain_spin)
        fade_row = QHBoxLayout()
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 60.0)
        self._fade_in_spin.setDecimals(2)
        self._fade_in_spin.setSingleStep(0.1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.editingFinished.connect(self._commit_take)
        fade_row.addWidget(QLabel("In:"))
        fade_row.addWidget(self._fade_in_spin)
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 60.0)
        self._fade_out_spin.setDecimals(2)
        self._fade_out_spin.setSingleStep(0.1)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.editingFinished.connect(self._commit_take)
        fade_row.addWidget(QLabel("Out:"))
        fade_row.addWidget(self._fade_out_spin)
        wrap = QWidget(); wrap.setLayout(fade_row)
        form.addRow("Fades", wrap)
        self._snap_to_position_btn = QPushButton(
            "Set start to current video position")
        self._snap_to_position_btn.clicked.connect(
            self._on_snap_start_to_position)
        form.addRow("", self._snap_to_position_btn)
        right_v.addWidget(detail_box)

        self._status_label = QLabel(
            f"Video duration: {self._video_duration_seconds:.2f} s")
        self._status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        right_v.addWidget(self._status_label)
        right_v.addStretch()
        right.setWidget(right_inner)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        self._export_btn = QPushButton("🎬 Export muxed MP4…")
        self._export_btn.clicked.connect(self._on_export)
        buttons.addButton(
            self._export_btn,
            QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

        # Initial media source.
        self._player.setSource(
            QUrl.fromLocalFile(str(self._source_path.resolve())))
        self._set_take_panel_enabled(False)

    def _set_take_panel_enabled(self, enabled: bool) -> None:
        for w in (
            self._label_edit, self._start_spin, self._gain_spin,
            self._fade_in_spin, self._fade_out_spin,
            self._snap_to_position_btn,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _on_play_video(self) -> None:
        self._player.play()

    def _on_stop_video(self) -> None:
        self._player.stop()

    def _on_video_position_changed(self, ms: int) -> None:
        self._position_label.setText(
            f"{ms / 1000.0:.2f} / "
            f"{self._video_duration_seconds:.2f} s")

    # ------------------------------------------------------------------
    # Take list
    # ------------------------------------------------------------------
    def _refresh_list(self) -> None:
        self._vo_list.clear()
        for i, seg in enumerate(self._voiceovers, start=1):
            name = seg.label or f"Take {i}"
            text = (
                f"{name}  @ {seg.start_at:.2f}s "
                f"({seg.gain_db:+.1f} dB)")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, seg.id)
            self._vo_list.addItem(item)
        for i in range(self._vo_list.count()):
            if (self._vo_list.item(i).data(
                    Qt.ItemDataRole.UserRole)
                    == self._selected_id):
                self._vo_list.setCurrentRow(i)
                return
        if self._selected_id is not None:
            self._selected_id = None
            self._set_take_panel_enabled(False)

    def _selected_take(self) -> Optional[VoiceoverSegment]:
        if self._selected_id is None:
            return None
        for s in self._voiceovers:
            if s.id == self._selected_id:
                return s
        return None

    def _on_take_selected(self) -> None:
        item = self._vo_list.currentItem()
        if item is None:
            self._selected_id = None
            self._set_take_panel_enabled(False)
            return
        self._selected_id = item.data(Qt.ItemDataRole.UserRole)
        seg = self._selected_take()
        if seg is None:
            return
        self._set_take_panel_enabled(True)
        for w in (self._label_edit, self._start_spin,
                  self._gain_spin, self._fade_in_spin,
                  self._fade_out_spin):
            w.blockSignals(True)
        self._label_edit.setText(seg.label)
        self._start_spin.setValue(float(seg.start_at))
        self._gain_spin.setValue(float(seg.gain_db))
        self._fade_in_spin.setValue(float(seg.fade_in_seconds))
        self._fade_out_spin.setValue(float(seg.fade_out_seconds))
        for w in (self._label_edit, self._start_spin,
                  self._gain_spin, self._fade_in_spin,
                  self._fade_out_spin):
            w.blockSignals(False)

    def _commit_take(self) -> None:
        seg = self._selected_take()
        if seg is None:
            return
        seg.label = self._label_edit.text().strip()
        seg.start_at = float(self._start_spin.value())
        seg.gain_db = float(self._gain_spin.value())
        seg.fade_in_seconds = float(self._fade_in_spin.value())
        seg.fade_out_seconds = float(self._fade_out_spin.value())
        seg.updated_at = datetime.now()
        self._refresh_list()

    def _on_snap_start_to_position(self) -> None:
        seg = self._selected_take()
        if seg is None:
            return
        seconds = self._player.position() / 1000.0
        self._start_spin.setValue(seconds)
        self._commit_take()

    def _on_remove(self) -> None:
        seg = self._selected_take()
        if seg is None:
            return
        self._voiceovers = [
            s for s in self._voiceovers if s.id != seg.id]
        self._selected_id = None
        self._refresh_list()

    # ------------------------------------------------------------------
    # Record / import
    # ------------------------------------------------------------------
    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._recorder is None:
            self._record_session = QMediaCaptureSession(self)
            self._audio_input = QAudioInput(
                QMediaDevices.defaultAudioInput(), self)
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
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        n = len(self._voiceovers) + 1
        self._record_target_path = (
            self._working_dir
            / f"vo_{n:03d}_{stamp}.wav")
        self._recorder.setOutputLocation(
            QUrl.fromLocalFile(
                str(self._record_target_path.resolve())))
        # Snap the start time to the video's current position so
        # the writer can record while watching, and the take lands
        # where the cursor was.
        snap_start = self._player.position() / 1000.0
        self._record_btn.setText("⏹ Stop recording")
        self._status_label.setText(
            f"Recording from microphone (will land at "
            f"{snap_start:.2f} s)…")
        self._player.play()
        self._pending_start_at = snap_start
        self._recorder.record()

    def _stop_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()
        self._player.pause()

    def _on_recorder_state_changed(self, state) -> None:
        if state == QMediaRecorder.RecorderState.StoppedState:
            self._record_btn.blockSignals(True)
            self._record_btn.setChecked(False)
            self._record_btn.setText("🎤 Record")
            self._record_btn.blockSignals(False)
            QTimer.singleShot(150, self._finalize_recording)

    def _finalize_recording(self) -> None:
        target = self._record_target_path
        if target is None or not target.exists():
            return
        if target.stat().st_size == 0:
            self._status_label.setText("No audio captured.")
            return
        duration = probe_audio_duration_seconds(target)
        seg = VoiceoverSegment(
            label=f"Take {len(self._voiceovers) + 1}",
            source="recorded",
            audio_path=str(target),
            source_duration_seconds=duration,
            start_at=float(getattr(self, "_pending_start_at", 0.0)),
        )
        self._voiceovers.append(seg)
        self._selected_id = seg.id
        self._refresh_list()
        self._record_target_path = None
        self._status_label.setText(
            f"Captured {target.name} (~{duration:.2f} s).")

    def _on_import(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(
            self, "Import voiceover audio", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac *.opus "
            "*.aiff);;All files (*)")
        if not picked:
            return
        import shutil as _sh
        snap_start = self._player.position() / 1000.0
        for src_str in picked:
            src = Path(src_str)
            if not src.exists():
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            n = len(self._voiceovers) + 1
            dest = (
                self._working_dir
                / f"vo_{n:03d}_{stamp}{src.suffix.lower()}")
            try:
                _sh.copy2(src, dest)
            except Exception:
                continue
            duration = probe_audio_duration_seconds(dest)
            seg = VoiceoverSegment(
                label=src.stem,
                source="imported",
                audio_path=str(dest),
                source_duration_seconds=duration,
                start_at=snap_start,
            )
            self._voiceovers.append(seg)
            snap_start += max(0.5, duration)
        self._refresh_list()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _on_export(self) -> None:
        if not self._voiceovers:
            QMessageBox.information(
                self, "Nothing to export",
                "Record or import at least one voiceover take "
                "first.")
            return
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Export needs ffmpeg on PATH.")
            return
        suggested = (
            self._source_path.with_name(
                self._source_path.stem
                + "_with_voiceover.mp4"))
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save muxed video",
            str(suggested),
            "MP4 video (*.mp4)")
        if not out_str:
            return
        out_path = Path(out_str)
        self._status_label.setText("Mixing voiceover…")
        mix_target = (
            self._working_dir
            / f"{out_path.stem}_voiceover_mix.wav")
        mix_result = mix_voiceover_segments(
            self._voiceovers,
            scene_visual_duration=max(
                1.0, self._video_duration_seconds),
            output_path=mix_target)
        if not mix_result.success:
            QMessageBox.warning(
                self, "Mix failed", mix_result.error)
            self._status_label.setText("")
            return
        self._status_label.setText("Muxing into video…")
        mux = mux_audio(
            self._source_path, mix_target, out_path,
            mode="extend_silent",
            video_duration=self._video_duration_seconds,
            audio_duration=self._video_duration_seconds)
        if not mux.success:
            QMessageBox.warning(
                self, "Mux failed", mux.error)
            return
        self._status_label.setText(f"Saved {out_path.name}.")
        QMessageBox.information(
            self, "Video saved",
            f"Saved muxed video:\n{out_path}")

    def _on_publish_clicked(self) -> None:
        """Open the Social Upload dialog on this editor's source
        video. The dialog is non-modal so the writer can keep
        working on voiceover takes while the upload runs."""
        from src.ui.video_studio.social_upload_dialog import (
            SocialUploadDialog)
        # Seed the title with the video's filename and the
        # description with a short note about voiceover takes
        # if any are present — the writer can edit either freely.
        suggested_title = self._source_path.stem.replace(
            "_", " ").replace("-", " ").strip().title()
        suggested_desc = ""
        if self._voiceovers:
            n = len(self._voiceovers)
            suggested_desc = (
                f"Recorded with {n} voiceover take"
                + ("s" if n != 1 else "")
                + " in the WritingAid Video Studio.")
        self._publish_dialog = SocialUploadDialog(
            video_path=self._source_path,
            suggested_title=suggested_title,
            suggested_description=suggested_desc,
            parent=self)
        self._publish_dialog.show()

    def _on_read_prose(self) -> None:
        """Open the chapter prose in a floating non-modal window.
        Reuses an existing window when already open so the writer
        doesn't end up with stacks of duplicates."""
        if (self._prose_window is not None
                and self._prose_window.isVisible()):
            self._prose_window.raise_()
            self._prose_window.activateWindow()
            return
        chapters = []
        if self._chapters_provider is not None:
            try:
                chapters = self._chapters_provider() or []
            except Exception as e:
                QMessageBox.warning(
                    self, "Could not load chapters",
                    f"{e}")
                return
        if not chapters:
            QMessageBox.information(
                self, "No chapters",
                "This project has no chapters with prose yet. "
                "Open the writer to draft prose first, then come "
                "back here to read along.")
            return
        from src.ui.video_studio.chapter_prose_window import (
            ChapterProseWindow)
        self._prose_window = ChapterProseWindow(
            chapters=chapters,
            on_save=self._save_chapter_text_cb,
            on_open_in_writer=(
                self._wrap_open_in_writer(
                    self._open_in_writer_cb)
                if self._open_in_writer_cb else None),
            parent=self)
        self._prose_window.show()

    def _wrap_open_in_writer(self, cb):
        """Close this editor when the handoff fires so focus
        moves cleanly to the main writer instead of stacking."""
        def _wrapped(chapter_id: str) -> None:
            cb(chapter_id)
            self.close()
        return _wrapped

    def closeEvent(self, event) -> None:
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            if self._recorder is not None:
                self._recorder.stop()
        except Exception:
            pass
        # Tear down the floating prose window if it's still open
        # so we don't leak a dangling top-level widget.
        try:
            if self._prose_window is not None:
                self._prose_window.close()
                self._prose_window = None
        except Exception:
            pass
        super().closeEvent(event)
