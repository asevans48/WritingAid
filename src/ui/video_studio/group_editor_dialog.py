"""Group editor — visual timeline for slide groups.

The slide editor's "🧩 Edit group…" button opens this dialog.
The flow it supports:

  1. Record (or import) **group-level audio** — a single track
     that plays under every slide in the group. This is the
     primary unit of recording; per-slide audio is for layering
     narration over a bed.
  2. Drag slides off the "tray" onto the timeline to pin them
     to a moment in the audio.
  3. Drag placed slide blocks left/right to adjust the moment
     each visual appears.
  4. Drag trim handles on the audio bar to chop dead air.
  5. Pick the transition that plays INTO the selected slide.
  6. Toggle "last slide fills to end" if the writer prefers the
     final visual to ride out the audio.

The recording path uses ``AudioRecorder`` (PortAudio +
soundfile) because PyQt6's QMediaRecorder Wave format silently
produces zero-byte files on macOS — that's the "mic works but
no audio was captured" bug.

The dialog mutates the deck and group **in place**. Closing it
returns control to the slide editor, which refreshes its lists
and lets the studio widget persist on its own close.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from src.ui.video_studio.audio_editor_dialog import (
    AudioEditorDialog)
from src.ui.video_studio.group_timeline_widget import (
    GroupTimelineWidget, start_slide_drag,
)
from src.video_studio.audio_recorder import AudioRecorder
from src.video_studio.models import (
    CHAPTER_TRANSITIONS, SlideDeckProject, SlideGroup, SlidePage,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class _SlideTray(QListWidget):
    """The "unplaced" slide list. Each item carries a page id;
    starting a drag from it hands the timeline a piece of MIME
    data the timeline knows how to drop on itself."""

    def __init__(
        self,
        on_drag_start: Callable[[str, str, Optional[QPixmap]], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_drag_start = on_drag_start
        self.setDragEnabled(True)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(2)
        self._mouse_down_pos = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() & Qt.MouseButton.LeftButton
                and self._mouse_down_pos is not None):
            delta = (
                event.position().toPoint() - self._mouse_down_pos)
            # Skip micro-jitter; only trigger drag on real motion.
            if delta.manhattanLength() > 8:
                item = self.itemAt(self._mouse_down_pos)
                if item is not None:
                    pid = item.data(Qt.ItemDataRole.UserRole)
                    pix = item.data(
                        Qt.ItemDataRole.UserRole + 1)
                    self._on_drag_start(
                        pid, item.text(), pix)
                    self._mouse_down_pos = None
                    return
        super().mouseMoveEvent(event)


class GroupEditorDialog(QDialog):
    """The visual group editor."""

    def __init__(
        self,
        deck: SlideDeckProject,
        group: SlideGroup,
        mic_device_getter: Optional[Callable[[], Any]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(None)
        self.setWindowTitle(
            f"Group editor — {group.name or 'group'}")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        target_w = 1100
        target_h = 760
        if avail is not None:
            target_w = max(
                900, min(target_w, int(avail.width() * 0.85)))
            target_h = max(
                620, min(target_h, int(avail.height() * 0.9)))
        self.resize(target_w, target_h)
        self.setMinimumSize(900, 620)
        self._deck = deck
        self._group = group
        self._mic_device_getter = mic_device_getter
        # Player for overlay-audio preview.
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        self._player.positionChanged.connect(
            self._on_player_position)
        self._player.playbackStateChanged.connect(
            lambda *_: self._refresh_play_button())
        # Recorder — sounddevice-backed.
        self._recorder = AudioRecorder()
        self._record_target_path: Optional[Path] = None
        self._record_pulse = QTimer(self)
        self._record_pulse.timeout.connect(self._pulse_record_label)
        self._record_pulse_state = False
        self._build_ui()
        self._refresh_tray()
        self._refresh_overlay_status()
        self._refresh_detail_panel()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        # ── Top bar: name + overlay audio controls ────────────
        top = QHBoxLayout()
        top.addWidget(QLabel("Group:"))
        self._name_edit = QLineEdit(self._group.name)
        self._name_edit.editingFinished.connect(
            self._on_name_changed)
        top.addWidget(self._name_edit, stretch=1)
        outer.addLayout(top)

        audio_box = QGroupBox(
            "Group audio (plays under every slide)")
        ab = QHBoxLayout(audio_box)
        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip(
            "Record the narration / bed for the whole group.\n"
            "Uses PortAudio so the WAV file is always written\n"
            "(QMediaRecorder's Wave format is broken on macOS).")
        self._record_btn.clicked.connect(
            self._on_record_toggled)
        ab.addWidget(self._record_btn)
        self._record_indicator = QLabel("")
        self._record_indicator.setStyleSheet(
            "color: #dc2626; font-weight: bold;")
        ab.addWidget(self._record_indicator)
        self._import_btn = QPushButton("📥 Import…")
        self._import_btn.clicked.connect(self._on_import)
        ab.addWidget(self._import_btn)
        self._edit_audio_btn = QPushButton("✏️ Edit audio…")
        self._edit_audio_btn.setToolTip(
            "Open the audio editor: trim, denoise, gain, "
            "normalize.")
        self._edit_audio_btn.clicked.connect(
            self._on_edit_audio)
        ab.addWidget(self._edit_audio_btn)
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.clicked.connect(self._on_play_pause)
        ab.addWidget(self._play_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        ab.addWidget(self._stop_btn)
        self._delete_btn = QPushButton("🗑 Delete")
        self._delete_btn.setToolTip(
            "Detach the audio from the group. Optionally "
            "delete the file on disk too.")
        self._delete_btn.clicked.connect(self._on_delete_audio)
        ab.addWidget(self._delete_btn)
        ab.addStretch()
        self._overlay_status = QLabel("(no overlay)")
        self._overlay_status.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        ab.addWidget(self._overlay_status)
        outer.addWidget(audio_box)

        # ── Center: tray + timeline + detail ──────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tray.
        tray_panel = QWidget()
        tv = QVBoxLayout(tray_panel)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(QLabel(
            "Available slides — drag onto the timeline"))
        self._tray = _SlideTray(self._begin_tray_drag)
        tv.addWidget(self._tray, stretch=1)
        tray_btns = QHBoxLayout()
        self._add_to_group_btn = QPushButton(
            "➕ Add slide from deck…")
        self._add_to_group_btn.clicked.connect(
            self._on_add_from_deck)
        tray_btns.addWidget(self._add_to_group_btn)
        tray_btns.addStretch()
        tv.addLayout(tray_btns)
        splitter.addWidget(tray_panel)

        # Timeline + per-slide detail (vertical).
        right_panel = QWidget()
        rv = QVBoxLayout(right_panel)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel(
            "Timeline — drag blocks to set when each slide "
            "appears. Drag the yellow handles to trim the audio."))
        timeline_scroll = QScrollArea()
        timeline_scroll.setWidgetResizable(True)
        timeline_scroll.setFrameShape(
            QScrollArea.Shape.NoFrame)
        self._timeline = GroupTimelineWidget(
            self._deck, self._group,
            on_request_image=self._pixmap_for_page)
        self._timeline.slideSelected.connect(
            self._on_timeline_select)
        self._timeline.slideDoubleClicked.connect(
            self._on_timeline_unplace)
        self._timeline.timelineChanged.connect(
            self._on_timeline_changed)
        self._timeline.trimChanged.connect(
            lambda *_: self._refresh_overlay_status())
        timeline_scroll.setWidget(self._timeline)
        rv.addWidget(timeline_scroll, stretch=1)

        # Detail / fill controls.
        detail_box = QGroupBox("Selected slide")
        form = QFormLayout(detail_box)
        self._selected_label = QLabel("(nothing selected)")
        form.addRow("Slide", self._selected_label)
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 3600.0)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.25)
        self._start_spin.setSuffix(" s")
        self._start_spin.editingFinished.connect(
            self._on_start_changed)
        form.addRow("Start time", self._start_spin)
        self._transition_combo = QComboBox()
        for key, label in CHAPTER_TRANSITIONS:
            self._transition_combo.addItem(label, key)
        self._transition_combo.currentIndexChanged.connect(
            self._on_transition_changed)
        form.addRow("Transition in", self._transition_combo)
        self._transition_secs = QDoubleSpinBox()
        self._transition_secs.setRange(0.0, 5.0)
        self._transition_secs.setDecimals(2)
        self._transition_secs.setSingleStep(0.1)
        self._transition_secs.setSuffix(" s")
        self._transition_secs.editingFinished.connect(
            self._on_transition_secs_changed)
        form.addRow(
            "Transition length", self._transition_secs)
        action_row = QHBoxLayout()
        self._unplace_btn = QPushButton("⤴ Move back to tray")
        self._unplace_btn.clicked.connect(
            self._on_unplace_selected)
        action_row.addWidget(self._unplace_btn)
        self._remove_from_group_btn = QPushButton(
            "🗑 Remove from group")
        self._remove_from_group_btn.clicked.connect(
            self._on_remove_from_group)
        action_row.addWidget(self._remove_from_group_btn)
        action_row.addStretch()
        form.addRow("", self._wrap_layout(action_row))
        rv.addWidget(detail_box)
        self._fill_check = QCheckBox(
            "Last placed slide fills to the audio's end")
        self._fill_check.setChecked(
            bool(getattr(
                self._group,
                "fill_last_slide_to_audio", True)))
        self._fill_check.toggled.connect(
            self._on_fill_toggled)
        rv.addWidget(self._fill_check)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, stretch=1)

        # Close.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        outer.addWidget(buttons)
        self._set_detail_enabled(False)

    @staticmethod
    def _wrap_layout(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _set_detail_enabled(self, enabled: bool) -> None:
        for w in (
                self._start_spin, self._transition_combo,
                self._transition_secs, self._unplace_btn,
                self._remove_from_group_btn):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _refresh_tray(self) -> None:
        self._tray.blockSignals(True)
        self._tray.clear()
        for pid in self._group.page_ids:
            page = self._find_page(pid)
            if page is None:
                continue
            if page.start_time_seconds_in_group is not None:
                continue
            text = page.label or "Slide"
            if page.image_path:
                text += "  · 🖼"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            pix = self._pixmap_for_page(page.id)
            if pix is not None:
                item.setData(
                    Qt.ItemDataRole.UserRole + 1, pix)
            self._tray.addItem(item)
        self._tray.blockSignals(False)

    def _begin_tray_drag(
            self, page_id: str, label: str,
            pix: Optional[QPixmap]) -> None:
        start_slide_drag(self._tray, page_id, label, pix)
        # The timeline emits ``timelineChanged`` after a
        # successful drop, which calls back into us.

    def _pixmap_for_page(
            self, page_id: str) -> Optional[QPixmap]:
        page = self._find_page(page_id)
        if page is None or not page.image_path:
            return None
        path = Path(page.image_path)
        if not path.exists():
            return None
        pix = QPixmap(str(path))
        return pix if not pix.isNull() else None

    # ------------------------------------------------------------------
    # Timeline events
    # ------------------------------------------------------------------
    def _on_timeline_select(self, page_id: str) -> None:
        self._refresh_detail_panel(
            selected_id=page_id or None)

    def _on_timeline_unplace(self, page_id: str) -> None:
        # Double-click on a placed slide moves it back to the
        # tray — quick way to "uncommit" a placement without
        # also removing the slide from the group.
        self._timeline.remove_placed(page_id)
        self._refresh_tray()
        self._refresh_detail_panel()

    def _on_timeline_changed(self) -> None:
        self._refresh_tray()
        self._refresh_detail_panel()
        self._maybe_recompute_durations()

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------
    def _refresh_detail_panel(
            self,
            selected_id: Optional[str] = None) -> None:
        pid = (
            selected_id
            if selected_id is not None
            else self._timeline.selected_page_id())
        page = self._find_page(pid) if pid else None
        if (page is None
                or page.start_time_seconds_in_group is None):
            self._selected_label.setText("(nothing selected)")
            for w in (
                    self._start_spin, self._transition_combo,
                    self._transition_secs):
                w.blockSignals(True)
            self._start_spin.setValue(0.0)
            self._transition_combo.setCurrentIndex(0)
            self._transition_secs.setValue(0.0)
            for w in (
                    self._start_spin, self._transition_combo,
                    self._transition_secs):
                w.blockSignals(False)
            self._set_detail_enabled(False)
            return
        self._set_detail_enabled(True)
        self._selected_label.setText(page.label or "Slide")
        for w in (
                self._start_spin, self._transition_combo,
                self._transition_secs):
            w.blockSignals(True)
        self._start_spin.setValue(
            float(page.start_time_seconds_in_group or 0.0))
        idx = self._transition_combo.findData(
            page.transition_in or "cut")
        self._transition_combo.setCurrentIndex(
            idx if idx >= 0 else 0)
        self._transition_secs.setValue(
            float(page.transition_seconds or 0.0))
        for w in (
                self._start_spin, self._transition_combo,
                self._transition_secs):
            w.blockSignals(False)
        # First placed slide has no transition INTO it.
        sorted_placed = sorted(
            (p for p in self._group_pages()
             if p.start_time_seconds_in_group is not None),
            key=lambda p: p.start_time_seconds_in_group or 0.0)
        is_first = (
            sorted_placed
            and sorted_placed[0].id == page.id)
        self._transition_combo.setEnabled(not is_first)
        self._transition_secs.setEnabled(not is_first)

    def _selected_page(self) -> Optional[SlidePage]:
        pid = self._timeline.selected_page_id()
        return self._find_page(pid) if pid else None

    def _on_start_changed(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.start_time_seconds_in_group = float(
            self._start_spin.value())
        page.updated_at = datetime.now()
        self._timeline.update()
        self._maybe_recompute_durations()

    def _on_transition_changed(self, _idx: int) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.transition_in = (
            self._transition_combo.currentData() or "cut")
        page.updated_at = datetime.now()
        self._timeline.update()

    def _on_transition_secs_changed(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.transition_seconds = float(
            self._transition_secs.value())
        page.updated_at = datetime.now()
        self._timeline.update()

    def _on_unplace_selected(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        self._timeline.remove_placed(page.id)
        self._refresh_tray()
        self._refresh_detail_panel()

    def _on_remove_from_group(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.group_id = None
        page.start_time_seconds_in_group = None
        page.updated_at = datetime.now()
        self._group.page_ids = [
            pid for pid in self._group.page_ids
            if pid != page.id]
        self._timeline.clear_selection()
        self._timeline.update()
        self._refresh_tray()
        self._refresh_detail_panel()

    # ------------------------------------------------------------------
    # Name + fill
    # ------------------------------------------------------------------
    def _on_name_changed(self) -> None:
        self._group.name = self._name_edit.text().strip()
        self.setWindowTitle(
            f"Group editor — {self._group.name or 'group'}")

    def _on_fill_toggled(self, checked: bool) -> None:
        self._group.fill_last_slide_to_audio = bool(checked)
        self._maybe_recompute_durations()
        self._timeline.update()

    def _maybe_recompute_durations(self) -> None:
        """Sync each placed slide's ``duration_seconds`` to the
        gap between its start and the next slide's start (or the
        audio end for the last one). The timeline view derives
        durations from start times directly, but the export
        pipeline still reads ``duration_seconds`` — so we keep
        them in lockstep."""
        placed = sorted(
            (p for p in self._group_pages()
             if p.start_time_seconds_in_group is not None),
            key=lambda p: p.start_time_seconds_in_group or 0.0)
        if not placed:
            return
        # The audio's effective end is its trim_out (or its
        # natural length when no trim is set).
        natural = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        trim_out = float(
            getattr(
                self._group,
                "overlay_trim_out_seconds", 0.0) or 0.0)
        audio_end = trim_out if trim_out > 0 else natural
        if audio_end <= 0:
            audio_end = (
                (placed[-1].start_time_seconds_in_group or 0.0)
                + max(1.0, placed[-1].duration_seconds))
        for i, p in enumerate(placed):
            start = float(
                p.start_time_seconds_in_group or 0.0)
            if i + 1 < len(placed):
                end = float(
                    placed[i + 1].start_time_seconds_in_group
                    or start)
            else:
                end = (
                    audio_end
                    if self._group.fill_last_slide_to_audio
                    else max(
                        start + p.duration_seconds,
                        start + 1.0))
            new_dur = max(0.25, end - start)
            if abs(new_dur - p.duration_seconds) > 0.01:
                p.duration_seconds = round(new_dur, 3)
                p.updated_at = datetime.now()

    # ------------------------------------------------------------------
    # Add slides from deck
    # ------------------------------------------------------------------
    def _on_add_from_deck(self) -> None:
        candidates = [
            p for p in self._deck.pages
            if p.id not in self._group.page_ids
        ]
        if not candidates:
            QMessageBox.information(
                self, "No slides to add",
                "Every slide in the deck is already in this "
                "group.")
            return
        labels = [
            f"{i + 1}. {p.label or 'Slide'}"
            for i, p in enumerate(candidates)
        ]
        picked, ok = QInputDialog.getItem(
            self, "Add slide to group",
            "Pick a slide to add to this group:",
            labels, 0, False)
        if not ok:
            return
        idx = labels.index(picked)
        page = candidates[idx]
        if page.group_id and page.group_id != self._group.id:
            for g in self._deck.groups:
                if g.id == page.group_id:
                    g.page_ids = [
                        pid for pid in g.page_ids
                        if pid != page.id]
                    break
        page.group_id = self._group.id
        page.start_time_seconds_in_group = None
        page.updated_at = datetime.now()
        self._group.page_ids.append(page.id)
        self._refresh_tray()

    # ------------------------------------------------------------------
    # Audio: record / import / edit / play / delete
    # ------------------------------------------------------------------
    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        # The picker hands us a Qt ``QAudioDevice``; we hand its
        # ``description()`` to PortAudio's substring lookup.
        device_name: Optional[str] = None
        try:
            if self._mic_device_getter is not None:
                qdev = self._mic_device_getter()
                if qdev is not None:
                    device_name = qdev.description()
        except Exception as e:
            print(f"[group_editor] mic resolve failed: {e}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")
        ) / "group_overlay"
        dest_dir.mkdir(parents=True, exist_ok=True)
        self._record_target_path = dest_dir / (
            f"{self._group.id}_{stamp}.wav")
        try:
            self._recorder.start(
                self._record_target_path,
                device_name=device_name)
        except Exception as e:
            QMessageBox.warning(
                self, "Recording failed",
                f"Could not start recording: {e}")
            self._record_btn.blockSignals(True)
            self._record_btn.setChecked(False)
            self._record_btn.blockSignals(False)
            return
        self._record_btn.setText("⏹ Stop recording")
        self._record_pulse.start(500)
        self._record_indicator.setText("● REC")

    def _stop_recording(self) -> None:
        self._record_pulse.stop()
        self._record_indicator.setText("")
        take = None
        try:
            take = self._recorder.stop()
        except Exception as e:
            QMessageBox.warning(
                self, "Recording finalize failed", str(e))
        self._record_btn.setText("🎤 Record")
        self._record_btn.blockSignals(True)
        self._record_btn.setChecked(False)
        self._record_btn.blockSignals(False)
        if take is None:
            return
        if (not take.path.exists()
                or take.path.stat().st_size == 0):
            QMessageBox.warning(
                self, "Recording empty",
                "The recorder finalized but the WAV file is "
                "empty. Check microphone permissions in System "
                "Settings → Privacy & Security → Microphone.")
            return
        self._attach_overlay(
            take.path, duration=take.duration_seconds)

    def _pulse_record_label(self) -> None:
        self._record_pulse_state = not self._record_pulse_state
        self._record_indicator.setText(
            "● REC" if self._record_pulse_state else "○ REC")

    def _on_import(self) -> None:
        picked, _ = QFileDialog.getOpenFileName(
            self, "Import overlay audio", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac *.opus "
            "*.aiff);;All files (*)")
        if not picked:
            return
        src = Path(picked)
        import shutil as _sh
        dest_dir = Path(
            self._deck.working_dir
            or src.parent) / "group_overlay"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / (
            f"{self._group.id}_{stamp}{src.suffix.lower()}")
        try:
            _sh.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        self._attach_overlay(dest)

    def _attach_overlay(
            self, path: Path,
            duration: Optional[float] = None) -> None:
        self._group.overlay_audio_path = str(path)
        if duration is None or duration <= 0:
            duration = probe_audio_duration_seconds(path) or 0.0
        self._group.overlay_audio_duration_seconds = float(
            duration)
        # Reset trim values when the audio swaps — a stale
        # out-trim from a longer prior take would silently clip
        # the new one and waste time debugging.
        self._group.overlay_trim_in_seconds = 0.0
        self._group.overlay_trim_out_seconds = 0.0
        self._refresh_overlay_status()
        self._timeline.update()
        self._maybe_recompute_durations()

    def _on_edit_audio(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            QMessageBox.information(
                self, "No audio",
                "Record or import audio first.")
            return
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"The audio file is missing:\n{path}")
            return
        dlg = AudioEditorDialog(
            source_path=path,
            on_applied=self._on_audio_edited,
            parent=None)
        dlg.show()

    def _on_audio_edited(
            self, new_path: Path, duration: float) -> None:
        self._attach_overlay(new_path, duration=duration)

    def _on_play_pause(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            return
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"The audio file is missing:\n{path}")
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            return
        if state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
            return
        self._player.setSource(
            QUrl.fromLocalFile(str(path.resolve())))
        # Seek to trim_in so preview honors the trim handles.
        trim_in_ms = int(
            (getattr(
                self._group,
                "overlay_trim_in_seconds", 0.0) or 0.0) * 1000)
        if trim_in_ms > 0:
            self._player.setPosition(trim_in_ms)
        self._player.play()

    def _on_stop(self) -> None:
        self._player.stop()
        self._timeline.set_playhead(0.0)

    def _refresh_play_button(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setText("⏸ Pause")
        else:
            self._play_btn.setText("▶ Play")

    def _on_player_position(self, ms: int) -> None:
        seconds = ms / 1000.0
        self._timeline.set_playhead(seconds)
        # Honor trim_out — pause playback when we hit the trim.
        trim_out = float(
            getattr(
                self._group,
                "overlay_trim_out_seconds", 0.0) or 0.0)
        if trim_out > 0 and seconds >= trim_out:
            self._player.pause()

    def _on_delete_audio(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            QMessageBox.information(
                self, "No audio",
                "There's no overlay audio attached to this "
                "group.")
            return
        path = Path(path_str)
        # Stop playback before deleting — on Windows the OS
        # won't let us unlink a file the player has open.
        self._player.stop()
        self._player.setSource(QUrl())
        choice = QMessageBox.question(
            self, "Delete audio",
            f"Detach the overlay from this group?\n\n"
            f"File: {path}\n\n"
            "Click YES to also delete the file on disk, "
            "or NO to only detach it (the file stays).",
            (QMessageBox.StandardButton.Yes
             | QMessageBox.StandardButton.No
             | QMessageBox.StandardButton.Cancel))
        if choice == QMessageBox.StandardButton.Cancel:
            return
        if (choice == QMessageBox.StandardButton.Yes
                and path.exists()):
            try:
                path.unlink()
            except Exception as e:
                QMessageBox.warning(
                    self, "Delete failed",
                    f"Could not delete file:\n{e}")
        self._group.overlay_audio_path = ""
        self._group.overlay_audio_duration_seconds = 0.0
        self._group.overlay_trim_in_seconds = 0.0
        self._group.overlay_trim_out_seconds = 0.0
        self._refresh_overlay_status()
        self._timeline.update()

    def _refresh_overlay_status(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            self._overlay_status.setText("(no overlay)")
            for w in (
                    self._edit_audio_btn, self._play_btn,
                    self._stop_btn, self._delete_btn):
                w.setEnabled(False)
            return
        path = Path(path_str)
        duration = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if not path.exists():
            self._overlay_status.setText(
                f"(missing: {path.name})")
        else:
            trim_in = float(
                getattr(
                    self._group,
                    "overlay_trim_in_seconds", 0.0) or 0.0)
            trim_out = float(
                getattr(
                    self._group,
                    "overlay_trim_out_seconds", 0.0) or 0.0)
            kept = (
                f"  · keep "
                f"{trim_in:.2f}–"
                f"{trim_out if trim_out > 0 else duration:.2f}s")
            self._overlay_status.setText(
                f"{path.name}  ·  {duration:.2f} s{kept}")
        for w in (
                self._edit_audio_btn, self._play_btn,
                self._stop_btn, self._delete_btn):
            w.setEnabled(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_page(
            self, page_id: Optional[str]) -> Optional[SlidePage]:
        if not page_id:
            return None
        for p in self._deck.pages:
            if p.id == page_id:
                return p
        return None

    def _group_pages(self) -> List[SlidePage]:
        return [
            p for pid in self._group.page_ids
            for p in [self._find_page(pid)]
            if p is not None
        ]

    def closeEvent(self, event) -> None:
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            if self._recorder.is_recording:
                self._recorder.stop()
        except Exception:
            pass
        super().closeEvent(event)
