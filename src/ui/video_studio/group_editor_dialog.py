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

from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QMenu, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from src.ui.video_studio.group_timeline_widget import (
    GroupTimelineWidget, start_slide_drag,
)
from src.video_studio.audio_recorder import (
    AudioRecorder, recorder_dependencies_available,
)
from src.video_studio.models import (
    CHAPTER_TRANSITIONS, SlideDeckProject, SlideGroup, SlidePage,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class _SlideTray(QListWidget):
    """The "unplaced" slide list — laid out as a horizontal
    thumbnail strip so it tucks under the timeline without
    eating horizontal room from it. Each item carries a page id;
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
        # Horizontal-flow icon strip. ``IconMode`` would normally
        # wrap into rows; ``setWrapping(False)`` keeps everything
        # on one line with a horizontal scrollbar — far more
        # laptop-friendly than the old vertical list which ate
        # 200+ px of width.
        from PyQt6.QtCore import QSize
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setIconSize(QSize(96, 64))
        self.setGridSize(QSize(116, 96))
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(108)
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

    # Fires after EVERY structural / settings mutation. The
    # slide editor connects this to its own ``deck_modified``
    # bubble, which in turn drives the studio widget's
    # ``contentChanged`` and the 1.2 s debounced autosave.
    # Without this signal, the writer would have to close the
    # slide editor (its ``finished`` is what currently triggers
    # the save) to persist group edits, which is invisible
    # behavior the writer's actually asked us to fix.
    deck_modified = pyqtSignal()

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
        # Default sized for a 1366×768 laptop with dock + menu
        # bar removed. Minimum height drops to 420 because the
        # outer scroll area now handles any further squeeze —
        # writers on a 13" MacBook can shrink the window and
        # scroll through the timeline + tabs instead of seeing
        # panels squish into illegibility.
        target_w = 1080
        target_h = 700
        if avail is not None:
            target_w = max(
                820, min(target_w, int(avail.width() * 0.85)))
            target_h = max(
                420, min(target_h, int(avail.height() * 0.9)))
        self.resize(target_w, target_h)
        self.setMinimumSize(820, 420)
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
        # Single shared preview window — re-used across double-
        # clicks so the writer doesn't end up with a stack of
        # viewer windows. ``None`` means no instance yet; the
        # first ``_view_slide`` call creates it.
        self._preview_window = None
        self._build_ui()
        self._refresh_tray()
        self._refresh_overlay_status()
        self._refresh_detail_panel()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Two-level layout: the dialog itself owns a vertical
        # layout with a QScrollArea (the body) and the Close
        # button. Everything else lives in the scroll area, so
        # if the dialog gets too short to show the timeline +
        # tabs at their natural sizes nothing collapses — the
        # writer just scrolls. That's what the laptop-cramping
        # report was actually asking for: stop squishing,
        # scroll instead.
        dialog_v = QVBoxLayout(self)
        dialog_v.setContentsMargins(0, 0, 0, 0)
        dialog_v.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Vertical scroll only — horizontal scroll on a dialog
        # this dense is disorienting. Better to let the content
        # match the window width and scroll up/down.
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(10, 10, 10, 10)

        # ── Top bar: name + mic picker ────────────────────────
        # The mic picker lives in the group editor (not the
        # slide editor) because this is the only place slide
        # narration gets recorded. Pick once, record across all
        # the slides in this group's track.
        top = QHBoxLayout()
        top.addWidget(QLabel("Group:"))
        self._name_edit = QLineEdit(self._group.name)
        self._name_edit.editingFinished.connect(
            self._on_name_changed)
        top.addWidget(self._name_edit, stretch=1)
        # Built lazily so the picker only enumerates devices
        # when the writer actually opens this dialog (saves a
        # ~50ms hit on cold launch).
        from src.ui.video_studio.microphone_picker import (
            MicrophonePicker)
        self._mic_picker = MicrophonePicker(
            initial_description=(
                getattr(
                    self._deck,
                    "microphone_device_name", "") or ""))
        self._mic_picker.device_changed.connect(
            self._on_mic_changed)
        top.addWidget(QLabel("Mic:"))
        top.addWidget(self._mic_picker, stretch=1)
        outer.addLayout(top)

        # Up-front check of recording prerequisites. We compute
        # this once and reuse: ``deps_diag`` is None when
        # everything is good, otherwise a non-empty string the
        # banner + tooltips surface verbatim. Doing it once
        # (instead of calling ``recorder_dependencies_available``
        # twice without context) means the writer sees a single
        # consistent explanation everywhere.
        deps_diag = self._diagnose_recorder_deps()

        audio_box = QGroupBox(
            "Group audio (plays under every slide)")
        audio_outer = QVBoxLayout(audio_box)
        # Inline banner — only visible when something is wrong.
        # Tooltips are too easy to miss; a red banner under the
        # buttons makes the cause impossible to ignore.
        if deps_diag is not None:
            warn = QLabel(deps_diag)
            warn.setWordWrap(True)
            warn.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            warn.setStyleSheet(
                "background: #fee2e2; color: #7f1d1d; "
                "border: 1px solid #dc2626; "
                "border-radius: 4px; padding: 6px 8px; "
                "font-size: 11px;")
            audio_outer.addWidget(warn)
        ab = QHBoxLayout()
        audio_outer.addLayout(ab)
        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip(
            "Record the narration / bed for the whole group.\n"
            "Uses PortAudio so the WAV file is always written\n"
            "(QMediaRecorder's Wave format is broken on macOS).")
        self._record_btn.clicked.connect(
            self._on_record_toggled)
        # If the PortAudio + soundfile pair isn't installed, the
        # record button can't do its job — disable it up-front
        # and put the install hint in the tooltip so the writer
        # sees a clear "why" without pressing record first.
        if deps_diag is not None:
            self._record_btn.setEnabled(False)
            self._record_btn.setToolTip(deps_diag)
        ab.addWidget(self._record_btn)
        self._record_indicator = QLabel("")
        self._record_indicator.setStyleSheet(
            "color: #dc2626; font-weight: bold;")
        ab.addWidget(self._record_indicator)
        # "Test mic" — records 0.5 s and reports peak level +
        # sample rate. Lets the writer confirm capture works
        # before committing to a full take. The peak number is
        # the smoking gun for permission / wrong-device issues:
        # 0.0 means PortAudio opened but isn't capturing.
        self._test_mic_btn = QPushButton("🔍 Test mic")
        self._test_mic_btn.setToolTip(
            "Record 0.5 seconds, then report the peak level "
            "and sample rate. Quick check that the device + "
            "permission are wired before starting a real take.")
        self._test_mic_btn.clicked.connect(self._on_test_mic)
        if deps_diag is not None:
            self._test_mic_btn.setEnabled(False)
            self._test_mic_btn.setToolTip(deps_diag)
        ab.addWidget(self._test_mic_btn)
        self._import_btn = QPushButton("📥 Import…")
        self._import_btn.clicked.connect(self._on_import)
        ab.addWidget(self._import_btn)
        # Audio editing is inline now — see the transforms
        # strip below the timeline. The old modal Edit Audio
        # dialog used to live here.
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
        # Discoverability hint for the new right-click menu.
        # Tiny, italic, sits below the toolbar so the writer
        # learns where transforms live now that the bottom
        # strip is gone.
        audio_outer.addWidget(QLabel(
            "<i>Drag on the audio bar to select a range. "
            "Right-click the audio to trim, reduce noise, "
            "or apply other transforms.</i>"))
        outer.addWidget(audio_box)

        # ── Center: timeline on top, tray underneath ──────────
        # Vertical stack — the timeline (audio + slide drop
        # band) is the main work surface, the tray slides in
        # as a thin horizontal thumbnail strip beneath it. This
        # replaces the old left-tray / right-timeline split that
        # ate horizontal width and cramped both on a laptop.
        center_panel = QWidget()
        cv = QVBoxLayout(center_panel)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(QLabel(
            "Timeline — drag blocks to set when each slide "
            "appears. Drag the yellow handles to trim the audio."))
        # Embed the timeline directly — no inner QScrollArea.
        # Nesting scroll areas (timeline_scroll inside the
        # dialog body scroll) led to the timeline shrinking to
        # its minimum and not scrolling the outer chrome,
        # which is the squish the writer was reporting. With
        # the dialog body owning the only scroll, the timeline
        # claims its real minimum height (300 px) and the
        # writer scrolls if the window is shorter.
        self._timeline = GroupTimelineWidget(
            self._deck, self._group,
            on_request_image=self._pixmap_for_page)
        self._timeline.slideSelected.connect(
            self._on_timeline_select)
        # Double-click on a placed slide opens the full-size
        # image viewer. The unplace path (used to live here)
        # moved to the "⤴ Move back to tray" button in the
        # Selected slide tab — writers asked for view-on-double-
        # click instead.
        self._timeline.slideDoubleClicked.connect(
            self._view_slide)
        self._timeline.timelineChanged.connect(
            self._on_timeline_changed)
        self._timeline.trimChanged.connect(
            lambda *_: self._refresh_overlay_status())
        # Right-click anywhere on the audio bar pops the
        # transforms menu — the only audio-configuration
        # surface now that the bottom strip is gone.
        self._timeline.audioContextRequested.connect(
            self._on_audio_context_menu)
        cv.addWidget(self._timeline)

        # Tray row.
        tray_header = QHBoxLayout()
        tray_header.addWidget(QLabel(
            "Available slides — drag onto the timeline"))
        tray_header.addStretch()
        self._add_to_group_btn = QPushButton(
            "➕ Add slide from deck…")
        self._add_to_group_btn.clicked.connect(
            self._on_add_from_deck)
        tray_header.addWidget(self._add_to_group_btn)
        cv.addLayout(tray_header)
        self._tray = _SlideTray(self._begin_tray_drag)
        # Double-click on a tray thumbnail opens the same
        # full-size viewer the placed-block double-click uses.
        # Single click stays as "select for drag", drag is
        # mouse-move based and unaffected.
        self._tray.itemDoubleClicked.connect(
            self._on_tray_double_clicked)
        cv.addWidget(self._tray)
        outer.addWidget(center_panel, stretch=1)

        # Audio transforms live in the right-click menu on the
        # audio bar — the old bottom strip is gone. State that
        # used to be UI widgets (the save-as-new toggle) is
        # now stored on the group itself
        # (``save_audio_edits_as_new``) so the choice survives
        # a close and reopen.
        self._save_as_new: bool = bool(
            getattr(
                self._group,
                "save_audio_edits_as_new", False))

        # ── Selected slide panel ────────────────────────────
        detail_box = QGroupBox("🎞 Selected slide")
        form = QFormLayout(detail_box)
        form.setContentsMargins(8, 8, 8, 8)
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
        self._fill_check = QCheckBox(
            "Last placed slide fills to the audio's end")
        self._fill_check.setChecked(
            bool(getattr(
                self._group,
                "fill_last_slide_to_audio", True)))
        self._fill_check.toggled.connect(
            self._on_fill_toggled)
        form.addRow("", self._fill_check)

        outer.addWidget(detail_box)
        outer.addStretch()

        # Mount the body into the scroll area, then anchor the
        # close button OUTSIDE so it's always reachable without
        # scrolling — primary navigation shouldn't be a target
        # the writer has to hunt for.
        self._scroll.setWidget(body)
        dialog_v.addWidget(self._scroll, stretch=1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        button_row = QWidget()
        bl = QHBoxLayout(button_row)
        bl.setContentsMargins(10, 6, 10, 10)
        bl.addStretch()
        bl.addWidget(buttons)
        dialog_v.addWidget(button_row)
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
        from PyQt6.QtGui import QIcon
        self._tray.blockSignals(True)
        self._tray.clear()
        for pid in self._group.page_ids:
            page = self._find_page(pid)
            if page is None:
                continue
            if page.start_time_seconds_in_group is not None:
                continue
            text = page.label or "Slide"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            pix = self._pixmap_for_page(page.id)
            if pix is not None:
                # Scale to the tray's icon size at construction
                # time so the painter doesn't have to scale on
                # every paint.
                scaled = pix.scaled(
                    96, 64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                item.setIcon(QIcon(scaled))
                item.setData(
                    Qt.ItemDataRole.UserRole + 1, pix)
            item.setToolTip(page.label or "Slide")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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

    def _on_tray_double_clicked(self, item) -> None:
        """Dispatch tray double-click to the shared viewer.
        The QListWidget hands us the item; we pull the page id
        off its UserRole data."""
        page_id = item.data(Qt.ItemDataRole.UserRole)
        if page_id:
            self._view_slide(str(page_id))

    def _view_slide(self, page_id: str) -> None:
        """Open (or focus) the floating preview window showing
        ``page_id`` at full size. Re-uses
        ``SlidePreviewWindow`` — the same widget the slide
        editor pops out — so writers get a consistent viewer
        across both surfaces."""
        page = self._find_page(page_id)
        if page is None:
            return
        if not page.image_path:
            QMessageBox.information(
                self, "No image",
                f"'{page.label or 'Slide'}' has no image "
                "attached yet.")
            return
        from src.ui.video_studio.slide_preview_window import (
            SlidePreviewWindow)
        # Recycle the existing instance when it's still alive —
        # otherwise the writer ends up with a stack of preview
        # windows after a few clicks.
        if (self._preview_window is None
                or not self._preview_window.isVisible()):
            self._preview_window = SlidePreviewWindow(
                self._deck, initial_slide_id=page_id)
        else:
            # Deck may have mutated since the window was last
            # opened (new slides, new images); push the fresh
            # snapshot before selecting.
            self._preview_window.set_deck(self._deck)
            self._preview_window.set_current(page_id)
        self._preview_window.show()
        self._preview_window.raise_()
        self._preview_window.activateWindow()

    def _on_timeline_changed(self) -> None:
        self._refresh_tray()
        self._refresh_detail_panel()
        self._maybe_recompute_durations()
        # Single central emit for every timeline-driven mutation
        # (trim drag, slide drag, slide drop, slide unplace).
        # The slide editor forwards this to the studio widget,
        # which triggers the 1.2 s debounced autosave.
        self.deck_modified.emit()

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
        self.deck_modified.emit()

    def _on_transition_changed(self, _idx: int) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.transition_in = (
            self._transition_combo.currentData() or "cut")
        page.updated_at = datetime.now()
        self._timeline.update()
        self.deck_modified.emit()

    def _on_transition_secs_changed(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        page.transition_seconds = float(
            self._transition_secs.value())
        page.updated_at = datetime.now()
        self._timeline.update()
        self.deck_modified.emit()

    def _on_unplace_selected(self) -> None:
        page = self._selected_page()
        if page is None:
            return
        self._timeline.remove_placed(page.id)
        self._refresh_tray()
        self._refresh_detail_panel()
        self.deck_modified.emit()

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
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Name + fill
    # ------------------------------------------------------------------
    def _on_name_changed(self) -> None:
        self._group.name = self._name_edit.text().strip()
        self.setWindowTitle(
            f"Group editor — {self._group.name or 'group'}")
        self.deck_modified.emit()

    def _on_mic_changed(self, description: str) -> None:
        """Persist the mic pick on the deck so the next session
        picks it up. The deck is the live model on
        ``VideoStudio.slide_decks``; the bubbled
        ``deck_modified`` signal kicks the autosave timer."""
        self._deck.microphone_device_name = description or ""
        self.deck_modified.emit()

    def _on_fill_toggled(self, checked: bool) -> None:
        self._group.fill_last_slide_to_audio = bool(checked)
        self._maybe_recompute_durations()
        self._timeline.update()
        self.deck_modified.emit()

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
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Audio: record / import / edit / play / delete
    # ------------------------------------------------------------------
    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    @staticmethod
    def _diagnose_recorder_deps() -> Optional[str]:
        """Return ``None`` when sounddevice + soundfile import
        cleanly, or a multi-line install hint when one (or
        both) is missing.

        The hint includes the **exact Python executable** that's
        running so the writer knows where to install — the
        common failure mode is "I installed sounddevice but the
        app is launched from a different interpreter than my
        terminal."
        """
        import sys
        missing = []
        for name in ("sounddevice", "soundfile"):
            try:
                __import__(name)
            except ImportError as exc:
                missing.append(f"{name} ({exc})")
        if not missing:
            return None
        return (
            f"Recording is disabled — Python can't import: "
            f"{', '.join(missing)}.\n"
            f"\nThis app is running from:\n  {sys.executable}\n"
            f"\nInstall the packages into THAT interpreter:\n"
            f"  {sys.executable} -m pip install "
            f"sounddevice soundfile\n"
            f"\nThen close and reopen the group editor."
        )

    def _on_test_mic(self) -> None:
        """Quick diagnostic — record half a second to a temp
        WAV, then read the peak amplitude back and show what
        rate + level we actually got. Surfaces both PortAudio
        open errors and silent-capture (mic muted / wrong
        device) bugs without committing to a real take."""
        import time
        from src.video_studio.audio_recorder import AudioRecorder
        device_name = self._resolve_mic_name()
        rec = AudioRecorder()
        dest = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")
        ) / "group_overlay" / "_mic_test.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._test_mic_btn.setEnabled(False)
        self._test_mic_btn.setText("🎤 Listening…")
        try:
            try:
                rec.start(dest, device_name=device_name)
            except Exception as e:
                QMessageBox.warning(
                    self, "Mic test failed", str(e))
                return
            # Block briefly on the GUI thread; 0.5s is short
            # enough that writers don't notice the freeze.
            time.sleep(0.55)
            take = rec.stop()
        finally:
            self._test_mic_btn.setEnabled(True)
            self._test_mic_btn.setText("🔍 Test mic")
        if take is None or not take.path.exists():
            QMessageBox.warning(
                self, "Mic test failed",
                "No WAV file was written.")
            return
        # Read the peak level back.
        peak = 0.0
        rms = 0.0
        try:
            import soundfile as sf
            import numpy as np
            data, _ = sf.read(str(take.path), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            if data.size > 0:
                peak = float(np.max(np.abs(data)))
                rms = float(np.sqrt(np.mean(data * data)))
        except Exception as e:
            print(f"[group_editor] mic test read failed: {e}")
        # Translate to dBFS for a more familiar number.
        import math
        peak_db = (
            20.0 * math.log10(peak) if peak > 0 else -200.0)
        rms_db = (
            20.0 * math.log10(rms) if rms > 0 else -200.0)
        diagnosis = ""
        if peak <= 1e-4:
            diagnosis = (
                "\n\n⚠️ Peak is essentially zero — the stream "
                "opened but no audio came through. On macOS "
                "this almost always means the app doesn't have "
                "Microphone permission. Check System Settings "
                "→ Privacy & Security → Microphone, enable "
                "this app, then restart the studio.")
        elif peak < 0.01:
            diagnosis = (
                "\n\nLevel is very low. Check the mic gain on "
                "the device itself (most USB mics have a "
                "hardware knob) or pick a different device.")
        QMessageBox.information(
            self, "Mic test",
            f"Device: {device_name or '<system default>'}\n"
            f"Sample rate: {take.samplerate} Hz\n"
            f"Duration captured: "
            f"{take.duration_seconds:.3f} s\n"
            f"Peak: {peak:.4f} ({peak_db:.1f} dBFS)\n"
            f"RMS:  {rms:.4f} ({rms_db:.1f} dBFS)"
            + diagnosis)
        # Clean up the diagnostic file.
        try:
            take.path.unlink()
        except Exception:
            pass

    def _resolve_mic_name(self) -> Optional[str]:
        """Pull a device description from the mic picker, with
        the optional ``_mic_device_getter`` callback as a
        fallback. Returns ``None`` to mean "system default"."""
        try:
            qdev = self._mic_picker.selected_device()
            if qdev is not None:
                return qdev.description()
        except Exception as e:
            print(f"[group_editor] mic resolve failed: {e}")
        try:
            if self._mic_device_getter is not None:
                qdev = self._mic_device_getter()
                if qdev is not None:
                    return qdev.description()
        except Exception as e:
            print(f"[group_editor] mic getter failed: {e}")
        return None

    def _start_recording(self) -> None:
        device_name = self._resolve_mic_name()
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
        except ModuleNotFoundError as e:
            # sounddevice / soundfile not installed. Show the
            # install hint verbatim so the writer can copy-paste
            # the pip command out of the dialog.
            QMessageBox.warning(
                self, "Recording dependencies missing", str(e))
            self._record_btn.setEnabled(False)
            self._record_btn.blockSignals(True)
            self._record_btn.setChecked(False)
            self._record_btn.blockSignals(False)
            return
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
            duration: Optional[float] = None,
            reset_trim: bool = True) -> None:
        """Wire ``path`` as the group's overlay audio. When
        ``reset_trim`` is True (the default — covers record /
        import / brand-new file), the trim handles snap back to
        full file. The transform-apply path passes False to
        preserve the writer's current trim window."""
        self._group.overlay_audio_path = str(path)
        if duration is None or duration <= 0:
            duration = probe_audio_duration_seconds(path) or 0.0
        self._group.overlay_audio_duration_seconds = float(
            duration)
        if reset_trim:
            # Stale trim from a longer prior take would silently
            # clip the new one and waste time debugging.
            self._group.overlay_trim_in_seconds = 0.0
            self._group.overlay_trim_out_seconds = 0.0
        self._refresh_overlay_status()
        # Drop the cached waveform so the timeline reloads peaks
        # from the new file on the next paint.
        self._timeline.refresh_waveform()
        self._timeline.update()
        self._maybe_recompute_durations()
        # Single emit covers record, import, and apply-transform —
        # every code path that lands a new file goes through here.
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Right-click context menu on the audio bar
    # ------------------------------------------------------------------
    def _has_selection(self) -> bool:
        """``True`` when the trim handles describe a real range
        (not "whole file"). Used to enable/disable the
        Trim-to-selection action in the context menu."""
        dur = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if dur <= 0:
            return False
        trim_in = float(
            getattr(
                self._group,
                "overlay_trim_in_seconds", 0.0) or 0.0)
        trim_out = float(
            getattr(
                self._group,
                "overlay_trim_out_seconds", 0.0) or 0.0)
        # "Whole file" looks like trim_in=0 and trim_out either
        # 0 (the sentinel) or >= dur.
        whole = (
            trim_in <= 0.001
            and (trim_out <= 0.001 or trim_out >= dur - 0.001))
        return not whole

    def _on_save_as_new_toggled(self, checked: bool) -> None:
        """Persist the writer's apply-mode preference on the
        group so it survives a close + reopen."""
        self._save_as_new = bool(checked)
        self._group.save_audio_edits_as_new = bool(checked)
        self.deck_modified.emit()

    def _on_audio_context_menu(self, global_pos) -> None:
        """Show the audio transforms menu at ``global_pos``.
        Items map 1:1 to single-purpose ffmpeg filters; the
        old multi-checkbox panel that lived at the bottom of
        this dialog is gone."""
        menu = QMenu(self)
        has_sel = self._has_selection()
        playhead = float(
            getattr(self._timeline, "_playhead_seconds", 0.0))
        duration = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        # The trim-by-playhead ops only make sense when the red
        # line is actually inside the file. At t=0 or t=end
        # they'd produce a zero-length / no-op cut.
        playhead_inside = (
            duration > 0
            and 0.05 < playhead < duration - 0.05)

        trim_act = menu.addAction("✂️  Trim to selection")
        trim_act.setEnabled(has_sel)
        trim_act.setToolTip(
            "Bake the highlighted region into the audio file. "
            "Everything before / after the selection is "
            "discarded.")
        trim_act.triggered.connect(self._op_trim_to_selection)

        trim_before_act = menu.addAction(
            "⏪  Trim before red line (keep what comes after)")
        trim_before_act.setEnabled(playhead_inside)
        trim_before_act.setToolTip(
            "Discard audio from 0 → playhead. Use this to chop "
            "off a noisy intro.")
        trim_before_act.triggered.connect(
            self._op_trim_before_playhead)

        trim_after_act = menu.addAction(
            "⏩  Trim after red line (keep what comes before)")
        trim_after_act.setEnabled(playhead_inside)
        trim_after_act.setToolTip(
            "Discard audio from playhead → end. Use this to "
            "stop the take early without re-recording.")
        trim_after_act.triggered.connect(
            self._op_trim_after_playhead)

        clear_sel_act = menu.addAction(
            "✗  Clear selection")
        clear_sel_act.setEnabled(has_sel)
        clear_sel_act.setToolTip(
            "Drop the highlighted region without modifying the "
            "audio file. Equivalent to a single click on the "
            "audio bar.")
        clear_sel_act.triggered.connect(self._op_clear_selection)

        menu.addSeparator()

        denoise_act = menu.addAction("🔇  Reduce noise…")
        denoise_act.setToolTip(
            "FFT-based noise reduction (afftdn). Pops a popup "
            "for the noise floor in dB.")
        denoise_act.triggered.connect(self._op_reduce_noise)

        rumble_act = menu.addAction(
            "🌬️  Remove rumble (100 Hz high-pass)")
        rumble_act.setToolTip(
            "Roll off room rumble, AC hum, handheld-mic boom.")
        rumble_act.triggered.connect(self._op_remove_rumble)

        norm_act = menu.addAction(
            "📊  Normalize loudness (−16 LUFS)")
        norm_act.setToolTip(
            "EBU R128 loudness target. Best applied after "
            "trim + denoise.")
        norm_act.triggered.connect(self._op_normalize)

        menu.addSeparator()

        gain_act = menu.addAction("🔊  Gain…")
        gain_act.triggered.connect(self._op_gain)
        fade_in_act = menu.addAction("🌅  Fade in…")
        fade_in_act.triggered.connect(self._op_fade_in)
        fade_out_act = menu.addAction("🌇  Fade out…")
        fade_out_act.triggered.connect(self._op_fade_out)

        menu.addSeparator()
        save_new_act = menu.addAction(
            "Save edits as new file (keep original)")
        save_new_act.setCheckable(True)
        save_new_act.setChecked(self._save_as_new)
        save_new_act.setToolTip(
            "Off (default): each transform replaces the source "
            "WAV in place. On: writes a new sibling file and "
            "switches the group's overlay to it; the original "
            "stays on disk untouched.")
        save_new_act.toggled.connect(self._on_save_as_new_toggled)

        # ToolTips on QAction don't show by default — explicit.
        menu.setToolTipsVisible(True)
        menu.exec(global_pos)

    def _op_trim_to_selection(self) -> None:
        trim_in = float(
            getattr(
                self._group,
                "overlay_trim_in_seconds", 0.0) or 0.0)
        trim_out = float(
            getattr(
                self._group,
                "overlay_trim_out_seconds", 0.0) or 0.0)
        if trim_out <= trim_in:
            return
        self._apply_audio_op(
            "Trim",
            in_point_seconds=trim_in,
            out_point_seconds=trim_out)

    def _op_trim_before_playhead(self) -> None:
        """Discard audio from 0 → playhead. Keeps the tail."""
        playhead = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        if playhead <= 0:
            return
        self._apply_audio_op(
            "Trim before red line",
            in_point_seconds=playhead,
            out_point_seconds=0.0)

    def _op_trim_after_playhead(self) -> None:
        """Discard audio from playhead → end. Keeps the head."""
        playhead = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        duration = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if playhead <= 0 or playhead >= duration:
            return
        self._apply_audio_op(
            "Trim after red line",
            in_point_seconds=0.0,
            out_point_seconds=playhead)

    def _op_clear_selection(self) -> None:
        """Drop the trim window without touching the audio file
        — non-destructive equivalent of a single click on the
        audio bar."""
        self._group.overlay_trim_in_seconds = 0.0
        self._group.overlay_trim_out_seconds = 0.0
        self._refresh_overlay_status()
        self._timeline.update()
        self.deck_modified.emit()

    def _op_reduce_noise(self) -> None:
        floor = self._param_popup(
            "Reduce noise",
            "Noise floor (more negative = more aggressive). "
            "Clean studio mic: −30 dB. Noisy laptop mic: −20 dB.",
            value=-25.0, min_v=-50.0, max_v=-5.0,
            decimals=1, step=1.0, suffix=" dB")
        if floor is None:
            return
        self._apply_audio_op(
            "Noise reduction",
            denoise=True,
            denoise_strength_db=floor)

    def _op_remove_rumble(self) -> None:
        self._apply_audio_op(
            "Rumble removal", highpass_hz=100.0)

    def _op_normalize(self) -> None:
        self._apply_audio_op(
            "Loudness normalization", normalize=True)

    def _op_gain(self) -> None:
        gain = self._param_popup(
            "Apply gain",
            "Gain (positive boosts, negative attenuates).",
            value=0.0, min_v=-30.0, max_v=30.0,
            decimals=1, step=0.5, suffix=" dB")
        if gain is None:
            return
        self._apply_audio_op("Gain", gain_db=gain)

    def _op_fade_in(self) -> None:
        secs = self._param_popup(
            "Fade in",
            "Fade in length (linear ramp from silence).",
            value=0.5, min_v=0.05, max_v=10.0,
            decimals=2, step=0.1, suffix=" s")
        if secs is None:
            return
        self._apply_audio_op(
            "Fade in", fade_in_seconds=secs)

    def _op_fade_out(self) -> None:
        secs = self._param_popup(
            "Fade out",
            "Fade out length (linear ramp to silence).",
            value=0.5, min_v=0.05, max_v=10.0,
            decimals=2, step=0.1, suffix=" s")
        if secs is None:
            return
        self._apply_audio_op(
            "Fade out", fade_out_seconds=secs)

    def _param_popup(
        self,
        title: str,
        label: str,
        *,
        value: float,
        min_v: float,
        max_v: float,
        decimals: int = 1,
        step: float = 0.1,
        suffix: str = "",
    ) -> Optional[float]:
        """Modal one-spinner popup. Returns the chosen value or
        ``None`` on cancel. Used by every parameter-needing
        transform op so the writer can dial in a value without
        the configuration cluttering the main dialog."""
        from PyQt6.QtWidgets import (
            QDialog as _QDialog, QDialogButtonBox as _Bb,
            QDoubleSpinBox as _Spin, QLabel as _Lbl,
            QVBoxLayout as _V)
        dlg = _QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        v = _V(dlg)
        prompt = _Lbl(label)
        prompt.setWordWrap(True)
        v.addWidget(prompt)
        spin = _Spin()
        spin.setRange(min_v, max_v)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(value)
        v.addWidget(spin)
        bb = _Bb(
            _Bb.StandardButton.Ok | _Bb.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        spin.setFocus()
        spin.selectAll()
        if dlg.exec() == _QDialog.DialogCode.Accepted:
            return float(spin.value())
        return None

    def _apply_audio_op(
            self, op_name: str, **edit_kwargs) -> None:
        """Run ``edit_audio`` with ``edit_kwargs`` against the
        group's overlay file and either replace it in place or
        save as a new sibling (per ``self._save_as_new``).

        Trim handles are NOT applied unless the caller passes
        ``in_point_seconds`` / ``out_point_seconds`` explicitly
        — that's the Trim-to-selection op's job. Pure audio
        transforms (denoise, gain, etc.) leave the duration
        alone.
        """
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            QMessageBox.information(
                self, "No audio",
                "Record or import audio first.")
            return
        src = Path(path_str)
        if not src.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"The audio file is missing:\n{src}")
            return
        # Stop playback so the file isn't held open during the
        # replace step (Windows-safe; POSIX wouldn't care).
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        save_as_new = self._save_as_new
        if save_as_new:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = src.with_name(
                f"{src.stem}_edit_{stamp}{src.suffix}")
        else:
            # Atomic swap path: ffmpeg writes a temp sibling,
            # we replace the source. ffmpeg failure leaves the
            # source intact.
            dest = src.with_name(
                f"{src.stem}.applying{src.suffix}")
        from src.video_studio.audio_edit import edit_audio
        result = edit_audio(src, dest, **edit_kwargs)
        if not result.success:
            QMessageBox.warning(
                self, f"{op_name} failed", result.error)
            if not save_as_new and dest.exists():
                try:
                    dest.unlink()
                except Exception:
                    pass
            return
        if save_as_new:
            self._attach_overlay(
                dest, duration=result.duration_seconds,
                reset_trim=True)
        else:
            try:
                dest.replace(src)
            except Exception as e:
                QMessageBox.warning(
                    self, "Replace failed",
                    f"Transformed file landed at {dest} but "
                    f"could not replace the original:\n{e}")
                return
            self._attach_overlay(
                src, duration=result.duration_seconds,
                reset_trim=True)
        QMessageBox.information(
            self, f"{op_name} applied",
            f"Audio is now {result.duration_seconds:.2f} s.")

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
        self._timeline.refresh_waveform()
        self._timeline.update()
        self.deck_modified.emit()

    def _refresh_overlay_status(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            self._overlay_status.setText("(no overlay)")
            for w in (
                    self._play_btn, self._stop_btn,
                    self._delete_btn):
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
                self._play_btn, self._stop_btn,
                self._delete_btn):
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
        # Tear down the floating image viewer too — a dangling
        # top-level Qt.Tool window otherwise outlives the editor
        # and quietly holds a reference to the (now stale) deck.
        try:
            if self._preview_window is not None:
                self._preview_window.close()
                self._preview_window = None
        except Exception:
            pass
        super().closeEvent(event)
