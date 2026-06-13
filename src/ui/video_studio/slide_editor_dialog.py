"""Slide editor dialog — record audio per slide, fit timings to
audio, paste script + AI-suggest timings, group slides, and
preview the deck.

Built around a ``SlideDeckProject`` the host seeds from a chapter
(via ``slide_deck.build_slide_deck_from_chapter``). The dialog
mutates the project in place; on close the studio's autosave
timer flushes it to disk.

Recording is wired to the writer's default microphone via
``QMediaRecorder``. While recording, the selected slide's image
is held on the right pane so the writer can read along; when
stop is hit, the take's duration probes ffprobe and (when the
slide isn't ``locked_duration``) the slide's time auto-fits the
audio length.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import (
    QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaFormat,
    QMediaPlayer, QMediaRecorder, QMediaDevices,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from src.video_studio.models import (
    SlideDeckProject, SlideGroup, SlidePage,
)
from src.video_studio.slide_deck import (
    MIN_SLIDE_SECONDS, adjust_slide_to_audio,
    distribute_group_timings, export_slide_deck_to_pptx,
    stitch_slide_deck_to_mp4, suggest_timings_from_script,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class SlideEditorDialog(QDialog):
    """Editor for a SlideDeckProject."""

    def __init__(
        self,
        deck: SlideDeckProject,
        chapters_provider=None,
        save_chapter_text=None,
        open_in_writer=None,
        parent: Optional[QWidget] = None,
    ):
        # Independent top-level so the floating chapter prose
        # window remains interactive when it's opened. A modal
        # parent would freeze input to every other window in the
        # app — writers couldn't click into the prose editor to
        # fix a typo while the slide editor was up.
        super().__init__(None)
        self.setWindowTitle(
            f"Slide editor — {deck.name or 'Slide deck'}")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        # Pull-on-open callback that returns (chapter_id, label,
        # text) triples — drives the "📖 Read chapter prose"
        # button. When None, the button is hidden. The slide
        # editor pre-selects the deck's chapter_id when it can.
        self._chapters_provider = chapters_provider
        # Optional save-back / jump-to-writer callbacks. The slim
        # editor inside the prose window uses these to write
        # chapter edits home + bounce to the main writer for
        # heavier work. Wired by the studio widget.
        self._save_chapter_text_cb = save_chapter_text
        self._open_in_writer_cb = open_in_writer
        self._prose_window = None
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)
        self._deck = deck
        self._working_dir = Path(deck.working_dir) if deck.working_dir else None
        if self._working_dir is None or not self._working_dir.exists():
            # Fall back to a temp dir keyed by deck id so recordings
            # still land somewhere stable across the session.
            self._working_dir = Path.home() / ".writingaid_slides" / deck.id
        self._working_dir.mkdir(parents=True, exist_ok=True)

        # Playback + recording.
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        self._record_session: Optional[QMediaCaptureSession] = None
        self._recorder: Optional[QMediaRecorder] = None
        self._audio_input: Optional[QAudioInput] = None
        self._record_target_path: Optional[Path] = None
        self._recording_page_id: Optional[str] = None

        self._selected_page_id: Optional[str] = None
        self._build_ui()
        self._refresh_slides()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        header = QLabel(
            "Record narration for each slide, fit timings to the "
            "audio, and group slides with a shared budget. Paste a "
            "script + use ✨ Suggest timings to map words to slides "
            "with a WPM estimate.")
        header.setWordWrap(True)
        header.setStyleSheet("color: #475569; font-size: 11px;")
        outer.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left column: slide list + group controls ─────────────
        left = QWidget()
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.addWidget(QLabel("Slides (in order):"))
        self._slide_list = QListWidget()
        self._slide_list.itemSelectionChanged.connect(
            self._on_slide_selected)
        left_v.addWidget(self._slide_list, stretch=1)
        slide_btns = QHBoxLayout()
        self._move_up_btn = QPushButton("↑")
        self._move_up_btn.clicked.connect(
            lambda: self._move_slide(-1))
        self._move_down_btn = QPushButton("↓")
        self._move_down_btn.clicked.connect(
            lambda: self._move_slide(+1))
        self._remove_slide_btn = QPushButton("Remove")
        self._remove_slide_btn.clicked.connect(
            self._on_remove_slide)
        slide_btns.addWidget(self._move_up_btn)
        slide_btns.addWidget(self._move_down_btn)
        slide_btns.addWidget(self._remove_slide_btn)
        slide_btns.addStretch()
        left_v.addLayout(slide_btns)

        group_box = QGroupBox("Slide groups")
        group_v = QVBoxLayout(group_box)
        group_v.addWidget(QLabel(
            "Group consecutive slides under a shared timing budget."))
        self._group_combo = QComboBox()
        self._group_combo.addItem("(none)", "")
        self._group_combo.currentIndexChanged.connect(
            self._on_group_combo_changed)
        group_v.addWidget(self._group_combo)
        group_actions = QHBoxLayout()
        self._new_group_btn = QPushButton("+ New group")
        self._new_group_btn.clicked.connect(self._on_new_group)
        self._add_to_group_btn = QPushButton("Add slide to selected group")
        self._add_to_group_btn.clicked.connect(
            self._on_add_to_selected_group)
        group_actions.addWidget(self._new_group_btn)
        group_actions.addWidget(self._add_to_group_btn)
        group_v.addLayout(group_actions)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target total:"))
        self._group_target_spin = QDoubleSpinBox()
        self._group_target_spin.setRange(0.0, 1800.0)
        self._group_target_spin.setDecimals(2)
        self._group_target_spin.setSingleStep(0.5)
        self._group_target_spin.setSuffix(" s")
        self._group_target_spin.setSpecialValueText(
            "(no target)")
        self._group_target_spin.editingFinished.connect(
            self._on_group_target_changed)
        target_row.addWidget(self._group_target_spin)
        self._distribute_btn = QPushButton(
            "Distribute across group")
        self._distribute_btn.setToolTip(
            "Evenly split the target time across the group's "
            "UNLOCKED slides. Locked slides keep their exact "
            "times; the remainder is divided between the rest.")
        self._distribute_btn.clicked.connect(
            self._on_distribute_group)
        target_row.addWidget(self._distribute_btn)
        group_v.addLayout(target_row)
        left_v.addWidget(group_box)
        splitter.addWidget(left)

        # ── Center column: per-slide controls ─────────────────────
        center = QScrollArea()
        center.setWidgetResizable(True)
        center.setFrameShape(QScrollArea.Shape.NoFrame)
        center_inner = QWidget()
        center_v = QVBoxLayout(center_inner)

        slide_box = QGroupBox("Selected slide")
        form = QFormLayout(slide_box)
        self._label_edit = QLineEdit()
        self._label_edit.editingFinished.connect(
            self._commit_slide_fields)
        form.addRow("Label", self._label_edit)

        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(
            float(MIN_SLIDE_SECONDS), 600.0)
        self._duration_spin.setDecimals(2)
        self._duration_spin.setSingleStep(0.25)
        self._duration_spin.setSuffix(" s")
        self._duration_spin.editingFinished.connect(
            self._commit_slide_fields)
        form.addRow("Duration", self._duration_spin)

        self._lock_check = QCheckBox(
            "Lock this duration (script / audio won't change it)")
        self._lock_check.toggled.connect(
            self._commit_slide_fields)
        form.addRow("", self._lock_check)

        # Transition INTO this slide. First slide ignores it
        # (no previous slide to cross from). Matches the 14
        # ffmpeg xfade options and PowerPoint transition names
        # (mapped via the PPTX exporter).
        from src.video_studio.models import (
            CHAPTER_TRANSITIONS as _CT)
        self._transition_combo = QComboBox()
        for key, label in _CT:
            self._transition_combo.addItem(label, key)
        self._transition_combo.setToolTip(
            "How this slide transitions IN from the previous "
            "one. The first slide ignores its transition.")
        self._transition_combo.currentIndexChanged.connect(
            self._commit_slide_fields)
        form.addRow("Transition in", self._transition_combo)

        self._transition_seconds_spin = QDoubleSpinBox()
        self._transition_seconds_spin.setRange(0.0, 5.0)
        self._transition_seconds_spin.setDecimals(2)
        self._transition_seconds_spin.setSingleStep(0.1)
        self._transition_seconds_spin.setSuffix(" s")
        self._transition_seconds_spin.editingFinished.connect(
            self._commit_slide_fields)
        form.addRow(
            "Transition length",
            self._transition_seconds_spin)

        script_box = QGroupBox("Script for this slide")
        sv = QVBoxLayout(script_box)
        sv.addWidget(QLabel(
            "Paste what you'll say. ✨ Suggest timings sets the "
            "duration from word count + WPM."))
        self._script_edit = QPlainTextEdit()
        self._script_edit.setPlaceholderText(
            "Paste the narration for THIS slide…")
        self._script_edit.setFixedHeight(140)
        self._script_edit.textChanged.connect(
            self._commit_slide_fields)
        sv.addWidget(self._script_edit)
        form.addRow(script_box)

        audio_box = QGroupBox("Slide audio")
        av = QVBoxLayout(audio_box)
        self._audio_status_label = QLabel("(no audio)")
        self._audio_status_label.setStyleSheet(
            "color: #475569; font-size: 11px;")
        av.addWidget(self._audio_status_label)
        rec_row = QHBoxLayout()
        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip(
            "Records from the default microphone. The slide image "
            "stays on the preview pane so you can read along.")
        self._record_btn.clicked.connect(self._on_record_toggled)
        rec_row.addWidget(self._record_btn)
        self._import_audio_btn = QPushButton("📥 Import audio…")
        self._import_audio_btn.clicked.connect(
            self._on_import_audio)
        rec_row.addWidget(self._import_audio_btn)
        self._play_audio_btn = QPushButton("▶ Play")
        self._play_audio_btn.clicked.connect(self._on_play_audio)
        rec_row.addWidget(self._play_audio_btn)
        self._stop_audio_btn = QPushButton("■ Stop")
        self._stop_audio_btn.clicked.connect(self._on_stop_audio)
        rec_row.addWidget(self._stop_audio_btn)
        self._clear_audio_btn = QPushButton("Clear")
        self._clear_audio_btn.clicked.connect(self._on_clear_audio)
        rec_row.addWidget(self._clear_audio_btn)
        av.addLayout(rec_row)
        form.addRow(audio_box)

        center_v.addWidget(slide_box)

        # ── Master script + AI timing ─────────────────────────────
        master_box = QGroupBox("Master script (paste, then ✨ Suggest)")
        mv = QVBoxLayout(master_box)
        # "Read chapter prose" button — opens a floating non-modal
        # window so the writer can scroll prose while reading
        # along into the mic. The button lives on its own row so
        # the description text below doesn't squeeze it off-
        # screen when the dialog is narrow. Hidden when no
        # chapter provider was wired in (e.g. dialog used
        # standalone in a test).
        prose_row = QHBoxLayout()
        self._read_prose_btn = QPushButton("📖 Read chapter prose…")
        self._read_prose_btn.setToolTip(
            "Open the chapter's prose in a floating window so "
            "you can scroll through it while recording. The "
            "window stays on top by default.")
        self._read_prose_btn.clicked.connect(self._on_read_prose)
        self._read_prose_btn.setVisible(
            self._chapters_provider is not None)
        prose_row.addWidget(self._read_prose_btn)
        prose_row.addStretch()
        mv.addLayout(prose_row)
        description_label = QLabel(
            "Paste the whole narration here. Blank-line "
            "paragraphs split across slides; the editor sets "
            "each slide's duration from its word count + WPM.")
        description_label.setWordWrap(True)
        mv.addWidget(description_label)
        self._master_script_edit = QPlainTextEdit()
        self._master_script_edit.setPlaceholderText(
            "Paste the full chapter narration here…")
        self._master_script_edit.setFixedHeight(140)
        mv.addWidget(self._master_script_edit)
        wpm_row = QHBoxLayout()
        wpm_row.addWidget(QLabel("Reading speed:"))
        self._wpm_spin = QSpinBox()
        self._wpm_spin.setRange(60, 400)
        self._wpm_spin.setSingleStep(10)
        self._wpm_spin.setSuffix(" WPM")
        self._wpm_spin.setValue(int(self._deck.wpm_estimate or 150))
        self._wpm_spin.valueChanged.connect(
            self._on_wpm_changed)
        wpm_row.addWidget(self._wpm_spin)
        wpm_row.addStretch()
        self._suggest_btn = QPushButton(
            "✨ Suggest timings from script")
        self._suggest_btn.clicked.connect(
            self._on_suggest_timings)
        wpm_row.addWidget(self._suggest_btn)
        mv.addLayout(wpm_row)
        center_v.addWidget(master_box)

        center_v.addStretch()
        center.setWidget(center_inner)
        splitter.addWidget(center)

        # ── Right column: slide preview + record indicator ───────
        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.addWidget(QLabel("Preview (plays during record):"))
        self._preview_label = QLabel("Select a slide.")
        self._preview_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(360)
        self._preview_label.setStyleSheet(
            "border: 1px solid #cbd5e1; background: #0f172a; "
            "color: #94a3b8;")
        right_v.addWidget(self._preview_label, stretch=1)
        self._record_status_label = QLabel("Idle.")
        self._record_status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        right_v.addWidget(self._record_status_label)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        outer.addWidget(splitter, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        # Two-format export — writers asked for both:
        #  * MP4 = stitched silent video with audio mux for
        #          handing to colleagues who just want to watch.
        #  * PPTX = editable deck with per-slide images + audio
        #           (auto-plays on slide entry) + auto-advance
        #           timings for further editing in PowerPoint /
        #           Keynote / Slides.
        self._export_mp4_btn = QPushButton("🎬 Export MP4…")
        self._export_mp4_btn.clicked.connect(
            self._on_export_mp4_clicked)
        self._export_pptx_btn = QPushButton("📊 Export PowerPoint…")
        self._export_pptx_btn.setToolTip(
            "Save as .pptx: one slide per image with the per-slide "
            "audio embedded to auto-play, and slide advance times "
            "matching the per-slide durations. No text overlays.")
        self._export_pptx_btn.clicked.connect(
            self._on_export_pptx_clicked)
        buttons.addButton(
            self._export_mp4_btn,
            QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(
            self._export_pptx_btn,
            QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

        self._refresh_groups()
        self._set_slide_panel_enabled(False)

    def _set_slide_panel_enabled(self, enabled: bool) -> None:
        for w in (
            self._label_edit, self._duration_spin, self._lock_check,
            self._transition_combo, self._transition_seconds_spin,
            self._script_edit, self._record_btn,
            self._import_audio_btn, self._play_audio_btn,
            self._stop_audio_btn, self._clear_audio_btn,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Slide list
    # ------------------------------------------------------------------
    def _refresh_slides(self) -> None:
        self._slide_list.clear()
        for i, page in enumerate(self._deck.pages, start=1):
            audio_mark = ""
            if page.audio_path:
                audio_mark = (
                    f" 🔊 {page.audio_duration_seconds:.1f}s")
            lock_mark = " 🔒" if page.locked_duration else ""
            group_mark = ""
            if page.group_id:
                group = next(
                    (g for g in self._deck.groups
                     if g.id == page.group_id),
                    None)
                if group:
                    group_mark = f"  [{group.name}]"
            text = (
                f"{i}. {page.label or 'Slide'}{group_mark}\n"
                f"   {page.duration_seconds:.2f}s"
                f"{audio_mark}{lock_mark}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            self._slide_list.addItem(item)
        for i in range(self._slide_list.count()):
            if (self._slide_list.item(i).data(
                    Qt.ItemDataRole.UserRole)
                    == self._selected_page_id):
                self._slide_list.setCurrentRow(i)
                return
        if self._selected_page_id is not None:
            self._selected_page_id = None
            self._set_slide_panel_enabled(False)
            self._preview_label.setText("Select a slide.")
            self._preview_label.setPixmap(QPixmap())

    def _selected_page(self) -> Optional[SlidePage]:
        if self._selected_page_id is None:
            return None
        for p in self._deck.pages:
            if p.id == self._selected_page_id:
                return p
        return None

    def _on_slide_selected(self) -> None:
        item = self._slide_list.currentItem()
        if item is None:
            self._selected_page_id = None
            self._set_slide_panel_enabled(False)
            return
        self._selected_page_id = item.data(
            Qt.ItemDataRole.UserRole)
        page = self._selected_page()
        if page is None:
            return
        self._set_slide_panel_enabled(True)
        for w in (self._label_edit, self._duration_spin,
                  self._lock_check, self._transition_combo,
                  self._transition_seconds_spin,
                  self._script_edit):
            w.blockSignals(True)
        self._label_edit.setText(page.label)
        self._duration_spin.setValue(
            float(page.duration_seconds))
        self._lock_check.setChecked(page.locked_duration)
        trans_idx = self._transition_combo.findData(
            page.transition_in or "cut")
        self._transition_combo.setCurrentIndex(
            trans_idx if trans_idx >= 0 else 0)
        self._transition_seconds_spin.setValue(
            float(page.transition_seconds))
        self._script_edit.setPlainText(page.script_text)
        for w in (self._label_edit, self._duration_spin,
                  self._lock_check, self._transition_combo,
                  self._transition_seconds_spin,
                  self._script_edit):
            w.blockSignals(False)
        # First slide has nothing to transition from.
        is_first = (
            self._deck.pages
            and self._deck.pages[0].id == page.id)
        self._transition_combo.setEnabled(not is_first)
        self._transition_seconds_spin.setEnabled(not is_first)
        self._refresh_audio_status()
        self._show_slide_preview(page)
        # Sync the group combo to the page's current group.
        group_id = page.group_id or ""
        idx = self._group_combo.findData(group_id)
        self._group_combo.blockSignals(True)
        self._group_combo.setCurrentIndex(
            idx if idx >= 0 else 0)
        self._group_combo.blockSignals(False)

    def _commit_slide_fields(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.label = self._label_edit.text().strip()
        page.duration_seconds = max(
            float(MIN_SLIDE_SECONDS),
            float(self._duration_spin.value()))
        page.locked_duration = bool(
            self._lock_check.isChecked())
        page.transition_in = (
            self._transition_combo.currentData() or "cut")
        page.transition_seconds = float(
            self._transition_seconds_spin.value())
        page.script_text = (
            self._script_edit.toPlainText().strip())
        page.updated_at = datetime.now()
        self._refresh_slides()

    def _move_slide(self, delta: int) -> None:
        page = self._selected_page()
        if page is None:
            return
        idx = next(
            (i for i, p in enumerate(self._deck.pages)
             if p.id == page.id),
            -1)
        new_idx = idx + delta
        if idx < 0 or not (0 <= new_idx < len(self._deck.pages)):
            return
        self._deck.pages.pop(idx)
        self._deck.pages.insert(new_idx, page)
        for i, p in enumerate(self._deck.pages):
            p.index = i
        self._refresh_slides()

    def _on_remove_slide(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        reply = QMessageBox.question(
            self, "Remove slide?",
            f"Drop '{page.label or page.id}' from the deck?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._deck.pages = [
            p for p in self._deck.pages if p.id != page.id]
        for g in self._deck.groups:
            g.page_ids = [
                pid for pid in g.page_ids if pid != page.id]
        self._selected_page_id = None
        self._refresh_slides()

    def _show_slide_preview(self, page: SlidePage) -> None:
        if not page.image_path or not Path(page.image_path).exists():
            self._preview_label.setText(
                "(slide image missing on disk)")
            self._preview_label.setPixmap(QPixmap())
            return
        pix = QPixmap(page.image_path)
        if pix.isNull():
            self._preview_label.setText("(cannot load image)")
            return
        scaled = pix.scaled(
            self._preview_label.width(),
            self._preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._preview_label.setPixmap(scaled)
        self._preview_label.setText("")

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------
    def _refresh_audio_status(self) -> None:
        page = self._selected_page()
        if page is None or not page.audio_path:
            self._audio_status_label.setText("(no audio)")
            return
        self._audio_status_label.setText(
            f"🔊 {Path(page.audio_path).name} "
            f"— {page.audio_duration_seconds:.2f}s")

    def _on_record_toggled(self, checked: bool) -> None:
        page = self._selected_page()
        if page is None:
            self._record_btn.setChecked(False)
            return
        if checked:
            self._start_recording(page)
        else:
            self._stop_recording()

    def _start_recording(self, page: SlidePage) -> None:
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
        self._record_target_path = (
            self._working_dir
            / f"slide_{page.index:03d}_{stamp}.wav")
        self._recording_page_id = page.id
        self._recorder.setOutputLocation(
            QUrl.fromLocalFile(
                str(self._record_target_path.resolve())))
        self._recorder.record()
        self._record_btn.setText("⏹ Stop recording")
        self._record_status_label.setText(
            "Recording — read along with the slide.")
        # Visual cue: keep the preview pinned to the recording slide.
        self._show_slide_preview(page)

    def _stop_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()

    def _on_recorder_state_changed(self, state) -> None:
        if state == QMediaRecorder.RecorderState.StoppedState:
            self._record_btn.setText("🎤 Record")
            self._record_btn.blockSignals(True)
            self._record_btn.setChecked(False)
            self._record_btn.blockSignals(False)
            QTimer.singleShot(150, self._finalize_recording)

    def _finalize_recording(self) -> None:
        target = self._record_target_path
        if target is None:
            return
        if not target.exists() or target.stat().st_size == 0:
            QTimer.singleShot(400, self._finalize_recording_retry)
            return
        self._attach_recorded_audio(target)

    def _finalize_recording_retry(self) -> None:
        target = self._record_target_path
        if target is None:
            return
        if not target.exists() or target.stat().st_size == 0:
            self._record_status_label.setText(
                "Recording stopped but no file was written. "
                "Check microphone permissions.")
            return
        self._attach_recorded_audio(target)

    def _attach_recorded_audio(self, path: Path) -> None:
        page_id = self._recording_page_id
        self._recording_page_id = None
        if page_id is None:
            return
        page = next(
            (p for p in self._deck.pages if p.id == page_id),
            None)
        if page is None:
            return
        duration = probe_audio_duration_seconds(path)
        page.audio_path = str(path)
        page.audio_duration_seconds = float(duration)
        page.updated_at = datetime.now()
        changed = adjust_slide_to_audio(page)
        msg = (
            f"Captured {path.name} (~{duration:.2f}s)."
            + (" Slide duration auto-fit."
               if changed else
               " Slide kept its locked duration."))
        self._record_status_label.setText(msg)
        # Sync the spinner with the new duration when not locked.
        if self._selected_page_id == page_id:
            self._duration_spin.blockSignals(True)
            self._duration_spin.setValue(
                float(page.duration_seconds))
            self._duration_spin.blockSignals(False)
        self._refresh_slides()
        self._refresh_audio_status()
        self._record_target_path = None

    def _on_recorder_error(self, *_args) -> None:
        if self._recorder is None:
            return
        err = self._recorder.errorString() or "Unknown error"
        self._record_status_label.setText(
            f"Recorder error: {err}")
        self._record_btn.blockSignals(True)
        self._record_btn.setChecked(False)
        self._record_btn.setText("🎤 Record")
        self._record_btn.blockSignals(False)

    def _on_import_audio(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        picked, _ = QFileDialog.getOpenFileName(
            self, "Import audio for slide", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac "
            "*.opus *.aiff);;All files (*)")
        if not picked:
            return
        src = Path(picked)
        import shutil as _sh
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = (
            self._working_dir
            / f"slide_{page.index:03d}_{stamp}{src.suffix.lower()}")
        try:
            _sh.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(
                self, "Import failed",
                f"Could not copy '{src.name}': {e}")
            return
        duration = probe_audio_duration_seconds(dest)
        page.audio_path = str(dest)
        page.audio_duration_seconds = float(duration)
        page.updated_at = datetime.now()
        adjust_slide_to_audio(page)
        if self._selected_page_id == page.id:
            self._duration_spin.blockSignals(True)
            self._duration_spin.setValue(
                float(page.duration_seconds))
            self._duration_spin.blockSignals(False)
        self._refresh_slides()
        self._refresh_audio_status()

    def _on_play_audio(self) -> None:
        page = self._selected_page()
        if page is None or not page.audio_path:
            return
        p = Path(page.audio_path)
        if not p.exists():
            return
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(p.resolve())))
        self._player.play()
        self._record_status_label.setText(
            f"Playing {p.name}…")

    def _on_stop_audio(self) -> None:
        self._player.stop()
        self._record_status_label.setText("Stopped.")

    def _on_clear_audio(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.audio_path = ""
        page.audio_duration_seconds = 0.0
        page.updated_at = datetime.now()
        self._refresh_slides()
        self._refresh_audio_status()

    # ------------------------------------------------------------------
    # Master script + AI timings
    # ------------------------------------------------------------------
    def _on_wpm_changed(self, value: int) -> None:
        self._deck.wpm_estimate = int(value)

    def _on_suggest_timings(self) -> None:
        text = self._master_script_edit.toPlainText()
        n, msg = suggest_timings_from_script(self._deck, text)
        QMessageBox.information(
            self, "Suggested timings", msg)
        self._refresh_slides()
        # If the currently-selected slide got a new script, sync
        # the editor's per-slide controls.
        page = self._selected_page()
        if page is not None:
            self._script_edit.blockSignals(True)
            self._script_edit.setPlainText(page.script_text)
            self._duration_spin.setValue(
                float(page.duration_seconds))
            self._script_edit.blockSignals(False)

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------
    def _refresh_groups(self) -> None:
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem("(none)", "")
        for g in self._deck.groups:
            self._group_combo.addItem(g.name or g.id, g.id)
        page = self._selected_page()
        if page is not None and page.group_id:
            idx = self._group_combo.findData(page.group_id)
            if idx >= 0:
                self._group_combo.setCurrentIndex(idx)
        self._group_combo.blockSignals(False)
        self._refresh_group_target_spin()

    def _refresh_group_target_spin(self) -> None:
        gid = self._group_combo.currentData()
        if not gid:
            self._group_target_spin.blockSignals(True)
            self._group_target_spin.setValue(0.0)
            self._group_target_spin.blockSignals(False)
            self._group_target_spin.setEnabled(False)
            self._distribute_btn.setEnabled(False)
            return
        g = next(
            (gg for gg in self._deck.groups if gg.id == gid),
            None)
        if g is None:
            return
        self._group_target_spin.blockSignals(True)
        self._group_target_spin.setValue(
            float(g.target_total_seconds))
        self._group_target_spin.blockSignals(False)
        self._group_target_spin.setEnabled(True)
        self._distribute_btn.setEnabled(True)

    def _on_group_combo_changed(self, _idx: int) -> None:
        self._refresh_group_target_spin()
        # Update the selected slide's group membership too.
        page = self._selected_page()
        if page is None:
            return
        new_gid = self._group_combo.currentData() or None
        if new_gid == page.group_id:
            return
        # Drop from old group.
        if page.group_id:
            for g in self._deck.groups:
                if g.id == page.group_id:
                    g.page_ids = [
                        pid for pid in g.page_ids
                        if pid != page.id]
        # Add to new group.
        if new_gid:
            for g in self._deck.groups:
                if g.id == new_gid and page.id not in g.page_ids:
                    g.page_ids.append(page.id)
        page.group_id = new_gid
        page.updated_at = datetime.now()
        self._refresh_slides()

    def _on_new_group(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New slide group", "Group name:")
        if not ok or not name.strip():
            return
        g = SlideGroup(name=name.strip())
        self._deck.groups.append(g)
        self._refresh_groups()
        # Select the new group in the combo.
        idx = self._group_combo.findData(g.id)
        if idx >= 0:
            self._group_combo.setCurrentIndex(idx)

    def _on_add_to_selected_group(self) -> None:
        gid = self._group_combo.currentData()
        page = self._selected_page()
        if not gid or page is None:
            return
        page.group_id = gid
        for g in self._deck.groups:
            if g.id == gid and page.id not in g.page_ids:
                g.page_ids.append(page.id)
        self._refresh_slides()

    def _on_group_target_changed(self) -> None:
        gid = self._group_combo.currentData()
        if not gid:
            return
        for g in self._deck.groups:
            if g.id == gid:
                g.target_total_seconds = float(
                    self._group_target_spin.value())

    def _on_distribute_group(self) -> None:
        gid = self._group_combo.currentData()
        if not gid:
            return
        g = next(
            (gg for gg in self._deck.groups if gg.id == gid),
            None)
        if g is None:
            return
        n = distribute_group_timings(self._deck, g)
        QMessageBox.information(
            self, "Group timings",
            f"Updated {n} slide(s) inside '{g.name}'.")
        self._refresh_slides()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _on_export_mp4_clicked(self) -> None:
        if not self._deck.pages:
            QMessageBox.information(
                self, "Nothing to export",
                "Add slides first.")
            return
        suggested = (
            self._working_dir
            / f"{(self._deck.name or 'deck').replace('/', '-')}_slides.mp4")
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save slide deck (MP4)",
            str(suggested),
            "MP4 video (*.mp4)")
        if not out_str:
            return
        self._record_status_label.setText("Rendering MP4…")
        ok, msg = stitch_slide_deck_to_mp4(
            self._deck, Path(out_str))
        if not ok:
            QMessageBox.warning(
                self, "Export failed", msg)
            return
        self._record_status_label.setText(
            f"Saved {Path(out_str).name}.")
        QMessageBox.information(
            self, "Slide deck rendered", msg)

    def _on_export_pptx_clicked(self) -> None:
        """Save the deck as .pptx with per-slide images + audio.

        Each slide is one image (centered, aspect-preserved). The
        audio take embeds as a media object set to auto-play on
        slide entry, and the slide's transition is set to advance
        automatically after ``page.duration_seconds``. Writers can
        open the result in PowerPoint / Keynote / Slides and edit
        freely from there.
        """
        if not self._deck.pages:
            QMessageBox.information(
                self, "Nothing to export",
                "Add slides first.")
            return
        suggested = (
            self._working_dir
            / f"{(self._deck.name or 'deck').replace('/', '-')}_slides.pptx")
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save slide deck (PowerPoint)",
            str(suggested),
            "PowerPoint (*.pptx)")
        if not out_str:
            return
        self._record_status_label.setText(
            "Composing PowerPoint…")
        ok, msg, skipped = export_slide_deck_to_pptx(
            self._deck, Path(out_str))
        if not ok:
            QMessageBox.warning(
                self, "Export failed", msg)
            self._record_status_label.setText("")
            return
        self._record_status_label.setText(
            f"Saved {Path(out_str).name}.")
        body = msg
        if skipped:
            body += (
                "\n\nNotes:\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        QMessageBox.information(
            self, "PowerPoint deck saved", body)

    def _on_read_prose(self) -> None:
        """Open the chapter prose in a floating non-modal window
        so the writer can scroll the script while recording."""
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
        # Pre-select the deck's chapter if it matches one in the
        # snapshot — saves the writer a click. ``on_save`` lets
        # the writer fix typos in-place; ``on_open_in_writer``
        # closes this dialog and hands off to the main writer.
        self._prose_window = ChapterProseWindow(
            chapters=chapters,
            initial_chapter_id=self._deck.chapter_id or None,
            on_save=self._save_chapter_text_cb,
            on_open_in_writer=(
                self._wrap_open_in_writer(
                    self._open_in_writer_cb)
                if self._open_in_writer_cb else None),
            parent=self)
        self._prose_window.show()

    def _wrap_open_in_writer(self, cb):
        """Wrap the host's open-in-writer callback so this dialog
        closes too — keeps focus moving in one direction so the
        writer doesn't end up with a stack of half-open windows."""
        def _wrapped(chapter_id: str) -> None:
            cb(chapter_id)
            self.accept()
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
        try:
            if self._prose_window is not None:
                self._prose_window.close()
                self._prose_window = None
        except Exception:
            pass
        super().closeEvent(event)
