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
from PyQt6.QtGui import (
    QGuiApplication, QKeySequence, QPixmap, QShortcut,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QMenu, QScrollArea, QVBoxLayout, QWidget,
)

from src.ui.video_studio.group_timeline_widget import (
    GroupTimelineWidget, start_slide_drag,
)
from src.video_studio.audio_recorder import AudioRecorder
from src.video_studio.models import (
    CHAPTER_TRANSITIONS, SlideDeckProject, SlideGroup, SlidePage,
)
from src.video_studio.tts.base import probe_audio_duration_seconds


class _ClipDragList(QListWidget):
    """The audio-clip list widget. Drag starts our custom
    audio-clip-id QDrag (consumed by the timeline) regardless
    of where the cursor moves. The previous attempt routed the
    drag through a manual ``mouseMoveEvent`` check, but Qt's
    own internal-move ``startDrag`` fired first and stole the
    event — so the writer's drag never reached our handler.
    Overriding ``startDrag`` runs once Qt has already decided
    a drag is happening, which is the right hook to substitute
    our payload."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Drag is enabled so Qt's drag-distance threshold +
        # OS-native pickup behavior fire normally. We DON'T
        # use ``InternalMove`` — that would consume the drag
        # and prevent it from reaching the timeline. Reorder
        # lives on the right-click menu (⬆ / ⬇ Move) instead.
        self.setDragEnabled(True)
        self.setDragDropMode(
            QListWidget.DragDropMode.DragOnly)

    def startDrag(self, supportedActions) -> None:
        item = self.currentItem()
        if item is None:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        if not clip_id:
            return
        # Don't fall through to ``super().startDrag`` — we
        # provide the full payload ourselves so the timeline's
        # drop handler picks up our audio-clip-id MIME.
        from src.ui.video_studio.group_timeline_widget import (
            start_audio_clip_drag)
        start_audio_clip_drag(self, clip_id, item.text())


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
        chapters_provider: Optional[Callable[[], Any]] = None,
        save_chapter_text: Optional[Callable[[str, str], None]] = None,
        open_in_writer: Optional[Callable[[str], None]] = None,
        scenes_provider: Optional[Callable[[], Any]] = None,
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
        # Chapter-prose plumbing — same shape the slide editor
        # uses for its Master script tab. The 📖 Read chapter
        # prose button is hidden when no ``chapters_provider``
        # was wired (e.g. dialog opened standalone in a test).
        self._chapters_provider = chapters_provider
        # Read-only access to every scene in the studio. Powers
        # the tray's "🔄 Sync favorites from actions" button —
        # walks each action's ``favorite_image()`` and either
        # creates or updates the matching slide page.
        self._scenes_provider = scenes_provider
        self._save_chapter_text_cb = save_chapter_text
        self._open_in_writer_cb = open_in_writer
        # Single shared prose window — re-used so the writer
        # doesn't end up with a stack of duplicate windows when
        # they click the button more than once.
        self._prose_window = None
        # ── Multi-clip audio migration ────────────────────────
        # Legacy decks carry ``overlay_audio_path`` directly.
        # Promote it to a single-entry ``audio_clips`` list so
        # the rest of the editor speaks one language. Subsequent
        # records APPEND to this list; recompose stitches them
        # back into ``overlay_audio_path`` (the rendered file
        # that playback + export still read).
        self._maybe_migrate_overlay_to_clips()
        # Reconcile ``page_ids`` with each page's
        # authoritative ``group_id`` so a deck loaded with
        # drifted indexes self-heals on open. Without this,
        # an unplace could leave a slide invisible in the
        # tray (the tray walked ``page_ids``).
        self._reconcile_group_page_ids()
        # Player for overlay-audio preview.
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        self._player.positionChanged.connect(
            self._on_player_position)
        self._player.playbackStateChanged.connect(
            lambda *_: self._refresh_play_button())
        # ``setSource`` is async — the file decode happens on a
        # background thread, so a ``setPosition`` fired right
        # after returns silently because the media isn't loaded
        # yet. Result: playback started from 0 instead of from
        # the red line. We park the requested seek in
        # ``_pending_seek_ms`` and apply it when the media
        # reports it's ready.
        self._pending_seek_ms: Optional[int] = None
        self._player.mediaStatusChanged.connect(
            self._on_media_status_changed)
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
        # Per-clip undo history. Keyed by clip id, value is a
        # ``collections.deque`` of model_dump() snapshots of
        # the clip BEFORE recent edits. Capped at 2 entries
        # per the writer's "save two previous copies" ask;
        # each ↶ Undo pops the most recent snapshot and
        # restores the clip's fields. Cleared on group switch.
        from collections import deque as _deque
        self._clip_edit_history: dict = {}
        # Hold a reference to deque so closure captures the
        # right class without re-importing later.
        self._deque_cls = _deque
        self._build_ui()
        self._refresh_tray()
        self._refresh_overlay_status()
        self._refresh_detail_panel()
        self._refresh_tracks_count_label()

    # ------------------------------------------------------------------
    # Multi-clip overlay
    # ------------------------------------------------------------------
    def _reconcile_group_page_ids(self) -> None:
        """Self-heal ``page_ids`` from each page's authoritative
        ``group_id``.

        Two repairs:
          1. ADD any page that names this group via
             ``page.group_id`` but is missing from
             ``page_ids``. Without this, an unplace silently
             drops the slide because the tray walks
             ``page_ids``.
          2. REMOVE any pid from ``page_ids`` that no longer
             matches a page (deleted from deck) or that
             names a different group now. Keeps the index
             from growing stale ghost references.

        Preserves the existing ``page_ids`` order for known
        ids and appends fresh ids in deck.pages order.
        """
        if (self._group is None
                or self._deck is None):
            return
        gid = self._group.id
        # Map every deck page's group_id for quick lookup.
        pages_by_id = {
            p.id: p for p in self._deck.pages}
        # Step 2: prune ids that no longer belong.
        kept = [
            pid for pid in (
                getattr(self._group, "page_ids", []) or [])
            if pid in pages_by_id
            and getattr(
                pages_by_id[pid], "group_id", None) == gid
        ]
        # Step 1: append any page that names us but wasn't in
        # page_ids yet, in deck.pages order.
        known = set(kept)
        for p in self._deck.pages:
            if (getattr(p, "group_id", None) == gid
                    and p.id not in known):
                kept.append(p.id)
                known.add(p.id)
        self._group.page_ids = kept

    def _maybe_migrate_overlay_to_clips(self) -> None:
        """Older decks have a single ``overlay_audio_path`` and
        no ``audio_clips`` — promote it to a one-entry clips
        list so the rest of the editor only sees clips. Then
        ensure every clip has a concrete ``start_time_seconds``
        (auto-place sequentially using ``crossfade_seconds`` as
        the overlap). Idempotent and safe to call every open."""
        from src.video_studio.models import GroupAudioClip
        clips = getattr(self._group, "audio_clips", None)
        if not clips:
            path = getattr(
                self._group, "overlay_audio_path", "") or ""
            if path:
                dur = float(
                    getattr(
                        self._group,
                        "overlay_audio_duration_seconds",
                        0.0) or 0.0)
                self._group.audio_clips = [
                    GroupAudioClip(
                        label="Take 1",
                        audio_path=path,
                        duration_seconds=dur,
                        trim_in_seconds=float(
                            getattr(
                                self._group,
                                "overlay_trim_in_seconds",
                                0.0) or 0.0),
                        trim_out_seconds=float(
                            getattr(
                                self._group,
                                "overlay_trim_out_seconds",
                                0.0) or 0.0),
                        start_time_seconds=0.0,
                    )
                ]
        # Backfill ``start_time_seconds`` for any clip that
        # arrived without one (older save written before the
        # positional refactor). Walk in list order, honoring
        # the legacy ``crossfade_seconds`` as overlap so the
        # rendered output matches what the writer last heard.
        clips = getattr(self._group, "audio_clips", None) or []
        running = 0.0
        for i, clip in enumerate(clips):
            if clip.start_time_seconds is not None:
                running = clip.start_time_seconds + \
                    self._clip_kept_seconds(clip)
                continue
            xf = float(
                getattr(clip, "crossfade_seconds", 0.15)
                or 0.0)
            start = 0.0 if i == 0 else max(0.0, running - xf)
            clip.start_time_seconds = start
            running = start + self._clip_kept_seconds(clip)

    def _recompose_overlay(self) -> bool:
        """Stitch ``audio_clips`` into a fresh rendered overlay
        WAV. Updates ``overlay_audio_path`` /
        ``overlay_audio_duration_seconds`` so the existing
        playback + export pipelines pick up the new file with
        no further changes. Returns True on success.

        Called after any structural mutation (record, delete,
        reorder, per-clip transform). Cheap on small clip lists
        because ffmpeg's acrossfade chain is essentially copy +
        a brief overlap.
        """
        clips = getattr(self._group, "audio_clips", None) or []
        if not clips:
            # No clips left — clear the rendered overlay so the
            # timeline goes back to the "no audio yet" state.
            self._group.overlay_audio_path = ""
            self._group.overlay_audio_duration_seconds = 0.0
            self._group.overlay_trim_in_seconds = 0.0
            self._group.overlay_trim_out_seconds = 0.0
            self._refresh_overlay_status()
            self._timeline.refresh_waveform()
            self._timeline.update()
            self._maybe_recompute_durations()
            self.deck_modified.emit()
            return True
        from src.video_studio.audio_edit import compose_clips
        from datetime import datetime as _dt
        dest_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")
        ) / "group_overlay"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / (
            f"{self._group.id}_composed_{stamp}.wav")
        # Stop the player so the OS lets us replace the file
        # we're about to render (Windows).
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        result = compose_clips(
            clips, dest,
            track_gain_db=getattr(
                self._group, "track_gain_db", None),
            track_deesser_intensity=getattr(
                self._group,
                "track_deesser_intensity", None),
            track_muted=getattr(
                self._group, "track_muted", None),
            track_background=getattr(
                self._group, "track_background", None))
        if not result.success:
            QMessageBox.warning(
                self, "Compose failed",
                result.error or "Unknown ffmpeg error.")
            return False
        self._group.overlay_audio_path = str(dest)
        self._group.overlay_audio_duration_seconds = float(
            result.duration_seconds)
        # The composed file IS the trimmed result — reset any
        # leftover whole-overlay trim handles since they don't
        # apply to the freshly-stitched file.
        self._group.overlay_trim_in_seconds = 0.0
        self._group.overlay_trim_out_seconds = 0.0
        self._refresh_overlay_status()
        self._timeline.refresh_waveform()
        self._timeline.update()
        self._maybe_recompute_durations()
        self.deck_modified.emit()
        return True

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
        # When this group is a title / ending CARD, surface its
        # appearance editor right here so the writer edits the card
        # AND records its audio in one place.
        from src.video_studio.slide_deck import group_card_page
        self._card_page = group_card_page(self._deck, self._group)
        if self._card_page is not None:
            self._edit_card_btn = QPushButton("🎬 Edit card…")
            self._edit_card_btn.setToolTip(
                "Edit this card's background, text, colors, fade, "
                "duration, and transition.")
            self._edit_card_btn.clicked.connect(
                self._on_edit_card_appearance)
            top.addWidget(self._edit_card_btn)
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
        # 📖 Read chapter prose — opens a floating ChapterProseWindow
        # so the writer can scroll the script alongside the audio
        # bar while recording. Mirrors the slide editor's Master
        # script tab control. Hidden when no chapters provider
        # was wired (dialog opened standalone in a test).
        self._read_prose_btn = QPushButton(
            "📖 Read chapter prose…")
        self._read_prose_btn.setToolTip(
            "Open the chapter's prose in a floating window so "
            "you can scroll through it while recording the "
            "group's narration. The window stays on top by "
            "default and saves edits back to the chapter.")
        self._read_prose_btn.clicked.connect(
            self._on_read_prose)
        self._read_prose_btn.setVisible(
            self._chapters_provider is not None)
        ab.addWidget(self._read_prose_btn)
        self._import_btn = QPushButton("📥 Import…")
        self._import_btn.clicked.connect(self._on_import)
        ab.addWidget(self._import_btn)
        # Audio editing is inline now — see the transforms
        # strip below the timeline. The old modal Edit Audio
        # dialog used to live here.
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setToolTip(
            "Play from the red line. ⏸ Pause keeps the player "
            "position; ■ Stop ends playback but the red line "
            "stays where it was so the next ▶ Play resumes "
            "from the same spot. Use ↺ Reset to rewind the "
            "red line to 0.")
        self._play_btn.clicked.connect(self._on_play_pause)
        ab.addWidget(self._play_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setToolTip(
            "End playback. The red line stays where it was "
            "(use ↺ Reset to rewind it).")
        self._stop_btn.clicked.connect(self._on_stop)
        ab.addWidget(self._stop_btn)
        # Reset = red line back to t=0. Separate from Stop so
        # writers don't lose their scrub position every time
        # they want to halt playback.
        self._reset_btn = QPushButton("↺ Reset")
        self._reset_btn.setToolTip(
            "Rewind the red line to the start of the "
            "timeline. The next ▶ Play starts from the very "
            "beginning of the first clip.")
        self._reset_btn.clicked.connect(
            self._on_reset_playhead)
        ab.addWidget(self._reset_btn)
        # ➕ Track adds a fresh empty audio lane. Writers use it
        # to stack music / SFX above the narration without
        # individual clips colliding. Tracks are persisted via
        # ``track_gain_db`` / ``track_names`` on the group so
        # they survive save / load even before any clips land.
        self._add_track_btn = QPushButton("➕ Track")
        self._add_track_btn.setToolTip(
            "Add a new audio lane below the current ones. "
            "Stack music, SFX, or alternate takes — clips on "
            "different lanes mix together at export time "
            "without competing for timeline slots.")
        self._add_track_btn.clicked.connect(self._on_add_track)
        ab.addWidget(self._add_track_btn)
        self._delete_btn = QPushButton("🗑 Delete")
        self._delete_btn.setToolTip(
            "Detach the audio from the group. Optionally "
            "delete the file on disk too.")
        self._delete_btn.clicked.connect(self._on_delete_audio)
        ab.addWidget(self._delete_btn)
        ab.addStretch()
        # Now-playing readout — updated on every player
        # positionChanged tick and after every reset. Shows
        # which clip the red line is on + the time within
        # that clip + the absolute timeline time.
        self._play_status_label = QLabel("")
        self._play_status_label.setStyleSheet(
            "color: #f97316; font-size: 11px; "
            "font-weight: bold;")
        ab.addWidget(self._play_status_label)
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

        # ── Clip list ─────────────────────────────────────────
        # Each Record click appends a take here. Writers can
        # reorder (drag), rename inline, or delete. After any
        # mutation we call ``_recompose_overlay`` which restitches
        # the rendered file the timeline / playback use.
        clips_box = QGroupBox(
            "Audio clips (record line-by-line, "
            "auto-crossfaded)")
        cb = QVBoxLayout(clips_box)
        cb_hint = QLabel(
            "<i>Each Record adds a new take. <b>Drag a row "
            "onto the timeline</b> to set its start time; on "
            "the timeline, drag block edges to trim and drag "
            "the block body to reposition. Right-click a row "
            "(or block) for delete / move up / move down / "
            "fade / gain.</i>")
        cb_hint.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        cb.addWidget(cb_hint)
        self._clip_list = _ClipDragList()
        self._clip_list.setMaximumHeight(140)
        # InternalMove is gone — the subclass overrides
        # ``startDrag`` to fire our audio-clip drag instead, and
        # InternalMove would steal that event. Reorder via the
        # right-click ⬆ / ⬇ Move entries.
        self._clip_list.itemChanged.connect(
            self._on_clip_renamed)
        # Delete / Backspace on the focused clip row deletes
        # via the same shift-aware helper the right-click menu
        # uses. ``WidgetShortcut`` scopes the binding so it
        # only fires when the clip list has focus — won't
        # collide with anywhere else Delete is meaningful (the
        # script editor, etc.).
        for keyseq in (
                QKeySequence(QKeySequence.StandardKey.Delete),
                QKeySequence(Qt.Key.Key_Backspace)):
            sc = QShortcut(keyseq, self._clip_list)
            sc.setContext(
                Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(
                self._on_delete_selected_clip)
        self._clip_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._clip_list.customContextMenuRequested.connect(
            self._on_clip_context_menu)
        cb.addWidget(self._clip_list)
        outer.addWidget(clips_box)
        self._refresh_clip_list()

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
            self._on_slide_activated)
        self._timeline.timelineChanged.connect(
            self._on_timeline_changed)
        self._timeline.trimChanged.connect(
            lambda *_: self._refresh_overlay_status())
        # Right-click anywhere on the audio bar pops the
        # transforms menu — the only audio-configuration
        # surface now that the bottom strip is gone.
        self._timeline.audioContextRequested.connect(
            self._on_audio_context_menu)
        # Per-clip block interaction on the audio bar — click
        # to select a clip (highlights the matching row in the
        # clip list), drag to reposition, right-click for trim
        # / fade / gain / delete.
        self._timeline.audioClipSelected.connect(
            self._on_audio_clip_selected_from_timeline)
        self._timeline.audioClipContextRequested.connect(
            self._on_audio_clip_context_from_timeline)
        self._timeline.audioClipMoved.connect(
            self._on_audio_clip_moved_from_timeline)
        # Lane header right-click → rename, set volume,
        # delete the lane.
        self._timeline.audioLaneContextRequested.connect(
            self._on_audio_lane_context_from_timeline)
        # Zoom changed → adjust the horizontal scrollbar so
        # the time under the cursor stays under the cursor
        # across the zoom step. Also refresh the px/s label.
        self._timeline.zoomChanged.connect(
            self._on_timeline_zoom_changed)
        # Slide block right-click → per-slide menu with
        # remove-from-timeline + remove-from-group + open-
        # preview.
        self._timeline.slideContextRequested.connect(
            self._on_slide_context_from_timeline)
        # Horizontal scroll wrapper. The timeline claims a
        # minimum width proportional to its audio duration
        # (see ``MIN_PIXELS_PER_SECOND``); when the window
        # narrower than that minimum, this scroll area shows a
        # horizontal scrollbar. When wider, the timeline
        # stretches because ``setWidgetResizable(True)`` lets
        # the widget grow past its sizeHint. Vertical scroll
        # is off — the outer dialog body scroll handles tall
        # content.
        # Timeline scroll area — scrolls BOTH dimensions so
        # the writer can pan to any part of the arrangement
        # regardless of dialog size:
        #   * Horizontal: long audio → scroll left/right.
        #   * Vertical:   stacked tracks → scroll up/down.
        # ``setWidgetResizable(True)`` lets the widget grow
        # past the viewport via its own minimumWidth /
        # minimumHeight (which ``_refresh_min_width`` keeps
        # in sync with audio duration + lane count). When the
        # widget's minimum exceeds the viewport in either
        # axis, the corresponding scrollbar engages.
        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidget(self._timeline)
        self._timeline_scroll.setWidgetResizable(True)
        self._timeline_scroll.setFrameShape(
            QScrollArea.Shape.NoFrame)
        self._timeline_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._timeline_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Fixed minimum viewport — the timeline is the main
        # work surface so it claims most of the dialog's
        # vertical room, but we cap the minimum so the dialog
        # itself can shrink and stay usable. Adding tracks no
        # longer balloons the dialog; the new lane just
        # appears under the existing ones and the vertical
        # scrollbar engages once we exceed this height.
        self._timeline_scroll.setMinimumHeight(280)
        # Tracks bar — sits directly above the timeline so the
        # writer always sees the lane count and has a one-click
        # path to add a new lane. The audio toolbar's ➕ Track
        # button has been the only path for a while, but on
        # narrow windows it scrolled off the right end of the
        # toolbar; this row is anchored next to the timeline
        # so it's impossible to miss.
        tracks_bar = QHBoxLayout()
        self._tracks_count_label = QLabel("Audio tracks: 1")
        self._tracks_count_label.setStyleSheet(
            "color: #94a3b8; font-size: 11px;")
        tracks_bar.addWidget(self._tracks_count_label)
        tracks_bar.addStretch()
        # Zoom controls — ➖ zooms out (more time per pixel,
        # see more arrangement at once), ➕ zooms in (more
        # pixels per second, easier to nudge clips precisely).
        # Both are anchored at the center of the visible
        # viewport via the scrollbar's value mid-range. The
        # writer can also Ctrl-wheel directly on the timeline
        # for cursor-anchored zoom.
        self._zoom_out_btn = QPushButton("➖")
        self._zoom_out_btn.setToolTip(
            "Zoom out — show more of the timeline at once. "
            "Ctrl-scroll on the timeline does the same "
            "anchored at the cursor.")
        self._zoom_out_btn.setFixedWidth(36)
        self._zoom_out_btn.clicked.connect(
            lambda: self._on_zoom_button(out=True))
        tracks_bar.addWidget(self._zoom_out_btn)
        self._zoom_label = QLabel("100 px/s")
        self._zoom_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        self._zoom_label.setFixedWidth(72)
        self._zoom_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        tracks_bar.addWidget(self._zoom_label)
        self._zoom_in_btn = QPushButton("➕")
        self._zoom_in_btn.setToolTip(
            "Zoom in — easier to nudge clip edges. "
            "Ctrl-scroll on the timeline does the same "
            "anchored at the cursor.")
        self._zoom_in_btn.setFixedWidth(36)
        self._zoom_in_btn.clicked.connect(
            lambda: self._on_zoom_button(out=False))
        tracks_bar.addWidget(self._zoom_in_btn)
        # 🎬 Preview compiles THIS group (slides + overlay
        # audio + transitions) into a temp MP4 and plays it in
        # a floating window. Lets writers spot-check what the
        # final exported deck will look like for the group
        # without exporting the whole project.
        self._preview_group_btn = QPushButton(
            "🎬 Preview")
        self._preview_group_btn.setToolTip(
            "Render this group's placed slides + composed "
            "audio into a temp MP4 and play it in a floating "
            "window. Same render path the deck export uses, "
            "so transitions / volumes / clip timings appear "
            "exactly as they'll ship.")
        self._preview_group_btn.clicked.connect(
            self._on_preview_group)
        tracks_bar.addWidget(self._preview_group_btn)
        self._add_track_btn_inline = QPushButton(
            "➕ Add audio track")
        self._add_track_btn_inline.setToolTip(
            "Add a new audio lane below the existing ones. "
            "Stack music, SFX, or alternate takes — clips on "
            "different lanes mix together at export time "
            "without competing for timeline slots.")
        self._add_track_btn_inline.clicked.connect(
            self._on_add_track)
        tracks_bar.addWidget(self._add_track_btn_inline)
        # ⟲ Reset timeline — sweep every placed slide back to
        # the tray and every audio clip back to the clip list,
        # WITHOUT deleting a single one. Nothing is unlinked
        # from the group; only the placement fields are
        # cleared (``start_time_seconds_in_group`` on pages,
        # ``start_time_seconds`` on clips). Writers asked for
        # this after several rounds of "let me start the
        # arrangement over" — the previous path was
        # right-click every block one at a time, which they
        # kept forgetting to do for one or two clips.
        self._reset_timeline_btn = QPushButton(
            "⟲ Reset timeline")
        self._reset_timeline_btn.setToolTip(
            "Move every placed slide back to the tray and "
            "every audio clip back to the clip list. Nothing "
            "is deleted — only the placement is cleared, so "
            "you can rearrange from scratch without losing "
            "any recordings or images.")
        self._reset_timeline_btn.clicked.connect(
            self._on_reset_timeline)
        tracks_bar.addWidget(self._reset_timeline_btn)
        # 🗑 Split-purpose escape hatches. These operate on
        # the MODEL directly (not the paint layer), so a
        # slide / clip stranded at a coordinate the widget
        # can't paint or the scroll can't reach still gets
        # unplaced. Writer never has to right-click / drag
        # the stranded block. Clicked once, the arrangement
        # for that half of the timeline is empty and the
        # writer can rebuild it from the tray / clip list.
        self._clear_images_btn = QPushButton(
            "🗑 Remove all images from timeline")
        self._clear_images_btn.setToolTip(
            "Unplace every slide from the image track. "
            "Slides return to the tray with their audio + "
            "duration + labels intact. Use when a slide is "
            "stranded outside the scrollable area — this "
            "walks the model directly, so it works even for "
            "slides you can't reach visually.")
        self._clear_images_btn.clicked.connect(
            self._on_all_slides_to_tray)
        tracks_bar.addWidget(self._clear_images_btn)
        self._clear_audio_btn = QPushButton(
            "🗑 Remove all audio from timeline")
        self._clear_audio_btn.setToolTip(
            "Unplace every audio clip from the audio "
            "tracks. Recordings return to the clip list with "
            "their trims + fades + gain intact. Same model-"
            "level escape as the image button: works even "
            "when a clip is stranded off-screen.")
        self._clear_audio_btn.clicked.connect(
            self._on_all_audio_to_list)
        tracks_bar.addWidget(self._clear_audio_btn)
        cv.addLayout(tracks_bar)
        cv.addWidget(self._timeline_scroll, stretch=1)

        # Tray row.
        tray_header = QHBoxLayout()
        tray_header.addWidget(QLabel(
            "Available slides — drag onto the timeline"))
        tray_header.addStretch()
        # 🔄 Sync favorites from actions — bulk-import every
        # action's current favorite image as a slide page in
        # THIS group. New favorites become new slides in the
        # tray; existing slides (matched by source_action_id)
        # get their image_path + label refreshed so a re-
        # favorited action shows up here without manual work.
        self._sync_favorites_btn = QPushButton(
            "🔄 Sync favorites from actions")
        self._sync_favorites_btn.setToolTip(
            "Pull every action's current favorite image "
            "into this group's tray. Slides keep their "
            "action's name as label so provenance survives "
            "the import.")
        self._sync_favorites_btn.clicked.connect(
            self._on_sync_favorites_from_actions)
        # Hide when no scenes_provider was wired (dialog
        # opened standalone in a test, or before this feature
        # was plumbed) — the button would be dead weight.
        if self._scenes_provider is None:
            self._sync_favorites_btn.setVisible(False)
        tray_header.addWidget(self._sync_favorites_btn)
        self._add_to_group_btn = QPushButton(
            "➕ Add slide from deck…")
        self._add_to_group_btn.clicked.connect(
            self._on_add_from_deck)
        tray_header.addWidget(self._add_to_group_btn)
        # ➕ New slide — create a brand-new slide in THIS group from
        # an imported image. It joins the tray; drag it onto the
        # timeline like any other. Shows up in the main slide
        # editor's "Slides (in order)" list under this group.
        self._new_slide_btn = QPushButton("➕ New slide…")
        self._new_slide_btn.setToolTip(
            "Create a new slide in this group from an image file. "
            "It appears in the tray (and in the main editor's slide "
            "list under this group).")
        self._new_slide_btn.clicked.connect(self._on_new_slide)
        tray_header.addWidget(self._new_slide_btn)
        # ➕ New designed slide — a PowerPoint-style slide built from
        # scratch: pick a background (solid color / image / video),
        # type a title + subtitle, and style them (color, position,
        # outline, shadow, box). It renders to a still image so it
        # flows through the deck exactly like any other slide, and can
        # be re-opened and re-designed later.
        self._new_designed_btn = QPushButton("➕ New designed slide…")
        self._new_designed_btn.setToolTip(
            "Build a slide from scratch — background color/image, "
            "styled title + subtitle — like a PowerPoint slide. Lands "
            "in the tray; drag it onto the timeline.")
        self._new_designed_btn.clicked.connect(
            self._on_new_designed_slide)
        tray_header.addWidget(self._new_designed_btn)
        # ⤴ Pull every placed slide back to the tray — a
        # smaller-blast-radius option than "Reset timeline"
        # (which also sweeps audio clips). Necessary because
        # a slide dropped at a huge start time or one dragged
        # past a subsequent scroll-shrink can end up outside
        # the reachable viewport, where the writer can't
        # right-click / drag it. This button always works
        # regardless of scroll position because it walks the
        # model directly.
        self._all_slides_to_tray_btn = QPushButton(
            "⤴ Bring all slides to tray")
        self._all_slides_to_tray_btn.setToolTip(
            "Move every slide on the timeline back to the "
            "tray (audio clips stay put). Rescues slides "
            "stranded off-screen when the timeline width "
            "changed under them — the writer doesn't have "
            "to reach them by scrolling.")
        self._all_slides_to_tray_btn.clicked.connect(
            self._on_all_slides_to_tray)
        tray_header.addWidget(self._all_slides_to_tray_btn)
        cv.addLayout(tray_header)
        self._tray = _SlideTray(self._begin_tray_drag)
        # Double-click on a tray thumbnail opens the same
        # full-size viewer the placed-block double-click uses.
        # Single click stays as "select for drag", drag is
        # mouse-move based and unaffected.
        self._tray.itemDoubleClicked.connect(
            self._on_tray_double_clicked)
        # Right-click on a tray thumbnail offers an explicit
        # "Place at end of timeline" path — discoverable
        # alternative to drag for writers who didn't realize
        # they could drag, or who prefer keyboard / menu nav.
        self._tray.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._tray.customContextMenuRequested.connect(
            self._on_tray_context_menu)
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
        # Walk ``deck.pages`` filtered by ``page.group_id`` —
        # that's the authoritative source for membership. The
        # earlier version iterated ``self._group.page_ids``,
        # but that index can drift out of sync with the
        # canonical ``page.group_id`` (the drop handler only
        # rebuilds it when the page moves BETWEEN groups, and
        # legacy data can land with mismatches). Reading from
        # ``page.group_id`` guarantees an unplaced slide
        # always reappears in the tray.
        # Stable ordering: use ``page_ids`` order when the
        # page id is listed there, otherwise append at the end
        # in deck.pages order. Keeps the tray's row order
        # consistent with what the writer set up.
        order_lookup = {
            pid: idx
            for idx, pid in enumerate(
                getattr(self._group, "page_ids", []) or [])}
        def _sort_key(p):
            return order_lookup.get(p.id, 10_000_000)
        candidates = sorted(
            (p for p in self._deck.pages
             if getattr(p, "group_id", None)
             == self._group.id),
            key=_sort_key)
        for page in candidates:
            if page.start_time_seconds_in_group is not None:
                continue
            # Self-heal ``page_ids`` so the index doesn't
            # stay stale — future code paths that read it
            # (export, recompose helpers) get a consistent
            # view without a separate migration pass.
            if page.id not in self._group.page_ids:
                self._group.page_ids.append(page.id)
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
        """Dispatch tray double-click. The QListWidget hands us the
        item; we pull the page id off its UserRole data."""
        page_id = item.data(Qt.ItemDataRole.UserRole)
        if page_id:
            self._on_slide_activated(str(page_id))

    def _on_slide_activated(self, page_id) -> None:
        """Double-click on a slide (tray OR timeline). A DESIGNED
        slide (one carrying a ``card``) opens the designer so the
        writer edits what they built; any other slide opens the
        full-size image viewer."""
        page = self._find_page(str(page_id)) if page_id else None
        if page is None:
            return
        if getattr(page, "card", None) is not None:
            self._redesign_slide(page)
        else:
            self._view_slide(str(page_id))

    def _on_tray_context_menu(self, point) -> None:
        """Right-click on a tray thumbnail — offer to place
        the slide on the timeline (alternative to drag) or
        open the full-size viewer."""
        item = self._tray.itemAt(point)
        if item is None:
            return
        page_id = item.data(Qt.ItemDataRole.UserRole)
        page = self._find_page(page_id) if page_id else None
        if page is None:
            return
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        view_act = menu.addAction("🔍  Preview slide image…")
        # Designed slides (built via "New designed slide") carry a
        # ``card`` — offer to re-open the designer and re-render.
        redesign_act = None
        if getattr(page, "card", None) is not None:
            redesign_act = menu.addAction("🎨  Redesign slide…")
            redesign_act.setToolTip(
                "Re-open the background + text designer for this "
                "slide and re-render it.")
        menu.addSeparator()
        place_act = menu.addAction(
            "📥  Place at end of timeline")
        place_act.setToolTip(
            "Add this slide to the timeline right after the "
            "last placed slide. You can also drag the thumb "
            "directly onto the timeline to position it.")
        menu.addSeparator()
        remove_act = menu.addAction(
            "🗑  Remove from group")
        remove_act.setToolTip(
            "Drop this slide from the group (stays in the deck).")
        delete_act = menu.addAction(
            "❌  Delete slide from the deck")
        delete_act.setToolTip(
            "Delete this slide everywhere. Cannot be undone.")
        action = menu.exec(
            self._tray.viewport().mapToGlobal(point))
        if action is view_act:
            self._view_slide(page_id)
        elif redesign_act is not None and action is redesign_act:
            self._redesign_slide(page)
        elif action is place_act:
            self._place_slide_at_end(page)
        elif action is remove_act:
            # Drop from the group (stays in the deck) — direct by id.
            pg = self._find_page(page_id)
            if pg is not None:
                pg.group_id = None
                pg.start_time_seconds_in_group = None
                pg.updated_at = datetime.now()
                self._group.page_ids = [
                    pid for pid in self._group.page_ids
                    if pid != page_id]
                self._refresh_tray()
                self.deck_modified.emit()
        elif action is delete_act:
            self._delete_slide(page_id)

    def _place_slide_at_end(self, page) -> None:
        """Drop an unplaced slide back onto the timeline,
        landing just after the last currently-placed slide.
        Mirrors ``_place_audio_clip_at_end`` for the audio
        path."""
        if page is None:
            return
        placed = [
            p for p in self._deck.pages
            if p.id != page.id
            and p.group_id == self._group.id
            and p.start_time_seconds_in_group is not None
        ]
        if not placed:
            new_start = 0.0
        else:
            last = max(
                placed,
                key=lambda p: float(
                    getattr(p, "start_time_seconds_in_group",
                            0.0) or 0.0)
                + max(0.25, float(
                    getattr(p, "duration_seconds", 0.0)
                    or 0.0)))
            new_start = (
                float(
                    getattr(
                        last,
                        "start_time_seconds_in_group", 0.0)
                    or 0.0)
                + max(0.25, float(
                    getattr(last, "duration_seconds", 0.0)
                    or 0.0)))
        page.start_time_seconds_in_group = round(
            max(0.0, new_start), 3)
        page.updated_at = datetime.now()
        self._refresh_tray()
        self._timeline.update()
        self._maybe_recompute_durations()
        self.deck_modified.emit()

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

    def _on_all_audio_to_list(self) -> None:
        """Sweep every placed audio clip back to the clip list
        without touching image slides.

        Model-direct — walks ``self._group.audio_clips`` and
        clears ``start_time_seconds`` on each one. Rescues
        clips stranded off-screen without needing to right-
        click them (which would need them to be visible). No
        clip is deleted, no trim / fade / gain is lost.
        """
        clips = (
            getattr(self._group, "audio_clips", None) or [])
        placed = [
            c for c in clips
            if getattr(c, "start_time_seconds", None)
            is not None]
        if not placed:
            QMessageBox.information(
                self, "Nothing to move",
                "No audio clips on the timeline right now.")
            return
        for clip in placed:
            clip.start_time_seconds = None
        # Full refresh — timeline redraws (empty audio lanes)
        # and the clip list picks up the unplaced state so the
        # writer can drag them back onto whichever lane they
        # want.
        self._timeline.clear_selection()
        self._timeline.refresh_waveform()
        self._timeline.update()
        self._refresh_clip_list()
        self._refresh_detail_panel()
        self.deck_modified.emit()

    def _on_all_slides_to_tray(self) -> None:
        """Sweep every placed slide back to the tray without
        touching audio.

        Different from ``_on_reset_timeline`` (which also
        clears audio-clip placement) because writers sometimes
        just want to rebuild the visual arrangement while
        keeping their recorded takes right where they are.
        And unlike the right-click-a-block path, this
        succeeds even when a slide is stranded outside the
        reachable scroll area — the model walk doesn't need
        the slide to be visible.
        """
        # Walk deck.pages by ``group_id`` — authoritative
        # membership. Reading from ``page_ids`` would miss a
        # page that drifted after a legacy migration; reading
        # from group_id catches every slide the writer sees on
        # the timeline.
        placed = [
            p for p in self._deck.pages
            if getattr(p, "group_id", None) == self._group.id
            and getattr(
                p, "start_time_seconds_in_group", None)
            is not None]
        if not placed:
            QMessageBox.information(
                self, "Nothing to move",
                "No slides on the timeline right now.")
            return
        now = datetime.now()
        for page in placed:
            page.start_time_seconds_in_group = None
            page.updated_at = now
        self._timeline.clear_selection()
        self._timeline.refresh_waveform()
        self._timeline.update()
        self._refresh_tray()
        self._refresh_detail_panel()
        self.deck_modified.emit()

    def _on_reset_timeline(self) -> None:
        """Sweep every placed slide back to the tray and every
        audio clip back to the clip list without deleting a
        single one.

        Clears ``start_time_seconds_in_group`` on every page
        that belongs to this group, and ``start_time_seconds``
        on every clip in ``audio_clips``. The clip files stay
        on disk; the pages stay linked to the group via
        ``page_ids``; the slide images stay in place. Writers
        get a blank timeline they can rearrange from scratch
        without having to re-record or re-pick anything.

        Confirms first — this is a bulk operation and undoing
        it means dragging every block back manually.
        """
        pages = self._group_pages()
        placed_pages = [
            p for p in pages
            if getattr(
                p, "start_time_seconds_in_group", None)
            is not None]
        placed_clips = [
            c for c in (
                getattr(self._group, "audio_clips", None)
                or [])
            if getattr(c, "start_time_seconds", None)
            is not None]
        if not placed_pages and not placed_clips:
            QMessageBox.information(
                self, "Nothing to reset",
                "Timeline is already empty.")
            return
        counts = []
        if placed_pages:
            counts.append(
                f"{len(placed_pages)} slide"
                f"{'s' if len(placed_pages) != 1 else ''}")
        if placed_clips:
            counts.append(
                f"{len(placed_clips)} audio clip"
                f"{'s' if len(placed_clips) != 1 else ''}")
        reply = QMessageBox.question(
            self, "Reset timeline",
            "Move "
            + " and ".join(counts)
            + " back to the tray / clip list?\n\n"
            "Nothing is deleted — slides stay in the group, "
            "clips stay recorded. Only the placement on the "
            "timeline is cleared so you can rearrange from "
            "scratch.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        now = datetime.now()
        for page in placed_pages:
            page.start_time_seconds_in_group = None
            page.updated_at = now
        for clip in placed_clips:
            clip.start_time_seconds = None
        self._timeline.clear_selection()
        self._timeline.refresh_waveform()
        self._timeline.update()
        self._refresh_tray()
        self._refresh_detail_panel()
        self._refresh_clip_list()
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

    def _on_edit_card_appearance(self) -> None:
        """Open the DESIGNER on the group's card slide (the same
        canvas the writer used to build it) so editing is consistent
        with double-click / 'Redesign slide'."""
        page = getattr(self, "_card_page", None)
        if page is None or getattr(page, "card", None) is None:
            return
        self._redesign_slide(page)

    def _on_edit_card_appearance_legacy(self) -> None:
        """(Unused) legacy title/subtitle form editor, superseded by
        the canvas designer."""
        page = getattr(self, "_card_page", None)
        if page is None or getattr(page, "card", None) is None:
            return
        from src.ui.video_studio.card_editor_dialog import (
            CardEditorDialog)
        bg_group = getattr(self._deck, "background_group", None)
        deck_has_bg = bool(
            bg_group is not None
            and (getattr(bg_group, "audio_clips", None) or []))
        dlg = CardEditorDialog(
            page.card,
            title_bar=(page.label or "Card"),
            deck_has_background=deck_has_bg,
            deck_background_enabled=not bool(getattr(
                self._group, "suppress_deck_background", False)),
            parent=self)
        dlg.set_timing(
            float(getattr(page, "duration_seconds", 4.0) or 4.0),
            getattr(self._group, "inter_group_transition_in", "cut"),
            getattr(
                self._group,
                "inter_group_transition_seconds", 0.0))
        if dlg.exec():
            page.duration_seconds = dlg.duration_seconds()
            self._group.inter_group_transition_in = (
                dlg.transition_kind())
            self._group.inter_group_transition_seconds = (
                dlg.transition_seconds())
            self._group.suppress_deck_background = (
                not dlg.deck_background_enabled())
            from datetime import datetime as _dt
            page.updated_at = _dt.now()
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
        """Enforce the no-overlap upper bound on every placed
        slide's ``duration_seconds`` — DON'T stretch durations
        to fill gaps.

        The earlier version of this method rewrote each
        slide's duration to the gap-to-next-slide, which
        clobbered any manual edge-drag resize the moment the
        writer clicked elsewhere (the resize fired
        ``timelineChanged`` → this method → duration snapped
        back to the gap). The fix: only ever SHRINK to prevent
        overlap with the next slide, plus optionally STRETCH
        the LAST slide to the audio end when the writer asked
        for ``fill_last_slide_to_audio``. Every other slide's
        duration stays as the writer set it.
        """
        placed = sorted(
            (p for p in self._group_pages()
             if p.start_time_seconds_in_group is not None),
            key=lambda p: p.start_time_seconds_in_group or 0.0)
        if not placed:
            return
        # Audio end for the fill-last toggle.
        natural = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        trim_out = float(
            getattr(
                self._group,
                "overlay_trim_out_seconds", 0.0) or 0.0)
        audio_end = trim_out if trim_out > 0 else natural
        for i, p in enumerate(placed):
            start = float(
                p.start_time_seconds_in_group or 0.0)
            cur_dur = max(0.25, float(
                getattr(p, "duration_seconds", 0.0) or 0.0))
            if i + 1 < len(placed):
                next_start = float(
                    placed[i + 1].start_time_seconds_in_group
                    or start)
                # Cap so the block doesn't overlap the next.
                max_dur = max(0.25, next_start - start)
                if cur_dur > max_dur + 0.005:
                    p.duration_seconds = round(max_dur, 3)
                    p.updated_at = datetime.now()
                # Don't extend — the writer's gap is intentional.
            else:
                # Last slide: stretch to audio end ONLY when
                # the writer asked for fill-to-audio. Otherwise
                # leave whatever the writer set.
                if (self._group.fill_last_slide_to_audio
                        and audio_end > start):
                    target = max(0.25, audio_end - start)
                    if abs(cur_dur - target) > 0.01:
                        p.duration_seconds = round(target, 3)
                        p.updated_at = datetime.now()

    # ------------------------------------------------------------------
    # Add slides from deck
    # ------------------------------------------------------------------
    def _on_sync_favorites_from_actions(self) -> None:
        """Refresh THIS group's slides with the current
        favorite image of the action each one was seeded from.

        Scoped to the group: we only walk slides in
        ``self._group.page_ids`` that carry a
        ``source_action_id``. Each one gets its
        ``image_path`` + ``label`` updated from the
        matching action's current favorite. No new slides
        are imported — the earlier version pulled in EVERY
        action's favorite across every scene, which dumped a
        pile of unrelated images into the tray. Writers
        wanted "refresh what's here", not "import the
        world."

        Pages whose ``source_action_id`` resolves but the
        action no longer has a usable favorite (missing
        file, no favorite set, action deleted) are left
        alone — better to keep a stale image than blank
        the slide out. The skipped count surfaces these so
        the writer knows.
        """
        if self._scenes_provider is None:
            QMessageBox.warning(
                self, "Sync unavailable",
                "Scene access wasn't wired into this editor.")
            return
        try:
            scenes = list(self._scenes_provider() or [])
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not load scenes", str(exc))
            return
        # Build a quick action_id → (scene_label, action) map
        # once instead of looping the scene graph per slide.
        action_by_id: dict = {}
        for scene in scenes:
            scene_label = (
                getattr(scene, "name", "") or "Scene")
            for action in (
                    getattr(scene, "actions", []) or []):
                aid = getattr(action, "id", None)
                if aid:
                    action_by_id[aid] = (
                        scene, scene_label, action)
        from datetime import datetime as _dt
        refreshed = 0
        unchanged = 0
        no_favorite = 0
        no_provenance = 0
        action_not_found = 0
        # Walk THIS group's pages only — sync is scoped to
        # the actions already represented in the group.
        for pid in list(self._group.page_ids):
            page = self._find_page(pid)
            if page is None:
                continue
            aid = getattr(page, "source_action_id", None)
            if not aid:
                # Page wasn't seeded from an action (e.g.
                # manually imported image); nothing to sync.
                no_provenance += 1
                continue
            tup = action_by_id.get(aid)
            if tup is None:
                # The action this page was seeded from is no
                # longer in the studio (scene / action
                # deleted). Leave the page alone.
                action_not_found += 1
                continue
            scene, scene_label, action = tup
            try:
                fav = (
                    action.favorite_image()
                    if hasattr(action, "favorite_image")
                    else None)
            except Exception:
                fav = None
            if fav is None:
                no_favorite += 1
                continue
            path_str = (
                getattr(fav, "file_path", "") or "").strip()
            if (not path_str
                    or not Path(path_str).exists()):
                no_favorite += 1
                continue
            action_name = (
                getattr(action, "name", "") or "action")
            label = f"{scene_label} → {action_name}"
            changed = False
            if page.image_path != path_str:
                page.image_path = path_str
                changed = True
            if page.label != label:
                page.label = label
                changed = True
            # Keep source_scene_id in lockstep when the action
            # moved between scenes (rare but possible after
            # restructure).
            new_sid = getattr(scene, "id", "") or ""
            if (new_sid
                    and getattr(page, "source_scene_id", "")
                    != new_sid):
                page.source_scene_id = new_sid
                changed = True
            if changed:
                page.updated_at = _dt.now()
                refreshed += 1
            else:
                unchanged += 1
        if refreshed:
            self._refresh_tray()
            self._timeline.update()
            self.deck_modified.emit()
        # Summary — terse but honest about the buckets.
        parts = [
            f"• {refreshed} slide(s) refreshed",
            f"• {unchanged} slide(s) already current",
        ]
        if no_favorite:
            parts.append(
                f"• {no_favorite} action(s) had no usable "
                "favorite (file missing or no favorite set)")
        if action_not_found:
            parts.append(
                f"• {action_not_found} slide(s) point at an "
                "action that's no longer in the studio")
        if no_provenance:
            parts.append(
                f"• {no_provenance} slide(s) have no action "
                "provenance (added by hand)")
        QMessageBox.information(
            self, "Sync complete",
            "Synced this group's slides to current action "
            "favorites:\n\n" + "\n".join(parts))

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

    def _on_new_slide(self) -> None:
        """Create a brand-new slide in this group from an imported
        image. It lands in the tray; the writer drags it onto the
        timeline. Appears in the main editor's slide list too."""
        picked, _ = QFileDialog.getOpenFileName(
            self, "New slide — pick an image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;"
            "All files (*)")
        if not picked:
            return
        src = Path(picked)
        dest_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")) / "slides"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"slide_{stamp}{src.suffix.lower()}"
        try:
            import shutil as _sh
            _sh.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(
                self, "Import failed",
                f"Could not copy '{src.name}': {e}")
            return
        page = SlidePage(
            label=src.stem,
            image_path=str(dest),
            duration_seconds=4.0,
            group_id=self._group.id)
        self._deck.pages.append(page)
        self._group.page_ids.append(page.id)
        self._refresh_tray()
        self.deck_modified.emit()
        QMessageBox.information(
            self, "Slide added",
            "New slide added to the tray — drag it onto the "
            "timeline to place it.")

    def _on_new_designed_slide(self) -> None:
        """Create a brand-new PowerPoint-style slide in this group:
        open the card designer (background + styled text), render the
        result to a still image, and add it as a slide. The page keeps
        its ``card`` so the writer can re-open the designer later."""
        from src.video_studio.models import TitleCard, SlideElement
        from src.video_studio.slide_deck import render_card_to_png
        from src.ui.video_studio.card_editor_dialog import (
            CardEditorDialog)
        card = TitleCard(
            role="content",
            kind="color",
            bg_color="#1e1e28",
            text_fade_seconds=0.0,
            elements=[
                SlideElement(
                    kind="text", text="Title", z=0,
                    x=0.15, y=0.34, w=0.70, h=0.18,
                    font_size=96, color="#FFFFFF", bold=True),
                SlideElement(
                    kind="text", text="Subtitle", z=1,
                    x=0.20, y=0.56, w=0.60, h=0.12,
                    font_size=48, color="#DDDDDD")])
        bg_group = getattr(self._deck, "background_group", None)
        deck_has_bg = bool(
            bg_group is not None
            and (getattr(bg_group, "audio_clips", None) or []))
        dlg = CardEditorDialog(
            card,
            title_bar="Designed slide",
            deck_has_background=deck_has_bg,
            deck_background_enabled=not bool(getattr(
                self._group, "suppress_deck_background", False)),
            canvas_mode=True,
            parent=self)
        dlg.set_timing(4.0, "cut", 0.0)
        if not dlg.exec():
            return
        # Render the designed card to a still image the pipeline can
        # treat as a normal slide.
        dest_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")) / "slides"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"designed_{stamp}.png"
        if not render_card_to_png(card, dest):
            QMessageBox.warning(
                self, "Render failed",
                "Could not render the designed slide to an image. "
                "Check that Pillow is installed.")
            return
        page = SlidePage(
            label=self._card_label(card),
            image_path=str(dest),
            card=card,
            duration_seconds=dlg.duration_seconds(),
            group_id=self._group.id)
        self._group.suppress_deck_background = (
            not dlg.deck_background_enabled())
        self._deck.pages.append(page)
        self._group.page_ids.append(page.id)
        self._refresh_tray()
        self.deck_modified.emit()
        QMessageBox.information(
            self, "Designed slide added",
            "Your designed slide is in the tray — drag it onto the "
            "timeline to place it. Re-open the group's card editor "
            "to redesign it later.")

    @staticmethod
    def _card_label(card) -> str:
        """Best label for a designed slide: first non-empty text
        element (by layer order), else the legacy title, else a
        generic name."""
        for e in sorted(
                (getattr(card, "elements", None) or []),
                key=lambda e: getattr(e, "z", 0)):
            if getattr(e, "kind", "text") != "text":
                continue
            t = (getattr(e, "text", "") or "").strip()
            if t:
                return t.splitlines()[0][:40]
        return (getattr(card, "title", "") or "").strip() \
            or "Designed slide"

    def _redesign_slide(self, page) -> None:
        """Re-open the card designer on an existing designed slide and
        re-render its still image in place."""
        card = getattr(page, "card", None)
        if card is None:
            return
        from src.video_studio.slide_deck import render_card_to_png
        from src.ui.video_studio.card_editor_dialog import (
            CardEditorDialog)
        bg_group = getattr(self._deck, "background_group", None)
        deck_has_bg = bool(
            bg_group is not None
            and (getattr(bg_group, "audio_clips", None) or []))
        dlg = CardEditorDialog(
            card,
            title_bar=(page.label or "Designed slide"),
            deck_has_background=deck_has_bg,
            deck_background_enabled=not bool(getattr(
                self._group, "suppress_deck_background", False)),
            canvas_mode=True,
            parent=self)
        dlg.set_timing(
            float(getattr(page, "duration_seconds", 4.0) or 4.0),
            "cut", 0.0)
        if not dlg.exec():
            return
        # Re-render over the SAME image file so placements/thumbnails
        # pick up the change without a new path.
        dest = Path(page.image_path) if page.image_path else (
            Path(self._deck.working_dir or (
                Path.home() / ".writingaid_slides")) / "slides"
            / f"designed_{datetime.now():%Y%m%d_%H%M%S}.png")
        if not render_card_to_png(card, dest):
            QMessageBox.warning(
                self, "Render failed",
                "Could not re-render the designed slide.")
            return
        page.image_path = str(dest)
        page.label = self._card_label(card)
        page.duration_seconds = dlg.duration_seconds()
        self._group.suppress_deck_background = (
            not dlg.deck_background_enabled())
        page.updated_at = datetime.now()
        self._refresh_tray()
        self._timeline.update()
        self.deck_modified.emit()

    def _delete_slide(self, page_id: str) -> None:
        """Delete a slide entirely from the group AND the deck."""
        page = next(
            (p for p in self._deck.pages if p.id == page_id), None)
        if page is None:
            return
        if QMessageBox.question(
                self, "Delete slide?",
                f"Delete '{page.label or 'slide'}' from the deck? "
                "This removes it everywhere, not just this "
                "group.") != QMessageBox.StandardButton.Yes:
            return
        self._deck.pages = [
            p for p in self._deck.pages if p.id != page_id]
        for g in self._deck.groups:
            g.page_ids = [
                pid for pid in g.page_ids if pid != page_id]
        self._timeline.select_audio_clip(None)
        self._reconcile_group_page_ids()
        self._refresh_tray()
        self._timeline.refresh_waveform()
        self._timeline.update()
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

    def _on_read_prose(self) -> None:
        """Open the chapter prose in a floating non-modal
        window so the writer can scroll the script while
        recording the group's narration. Mirrors the slide
        editor's master-script tab control."""
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
                    self, "Could not load chapters", f"{e}")
                return
        if not chapters:
            QMessageBox.information(
                self, "No chapters",
                "This project has no chapters with prose yet. "
                "Open the writer to draft prose first, then "
                "come back here to read along.")
            return
        from src.ui.video_studio.chapter_prose_window import (
            ChapterProseWindow)
        # Pre-select the deck's chapter when it matches one in
        # the snapshot, so the writer doesn't have to pick again
        # for the obvious case.
        initial = getattr(self._deck, "chapter_id", None) or None
        self._prose_window = ChapterProseWindow(
            chapters=chapters,
            initial_chapter_id=initial,
            on_save=self._save_chapter_text_cb,
            on_open_in_writer=(
                self._wrap_open_in_writer(
                    self._open_in_writer_cb)
                if self._open_in_writer_cb else None),
            parent=self)
        self._prose_window.show()

    def _wrap_open_in_writer(self, cb):
        """Wrap the host's open-in-writer callback so this
        dialog closes too — keeps focus moving in one direction
        so the writer doesn't end up with a stack of half-open
        windows when they hand off to the main writer."""
        def _wrapped(chapter_id: str) -> None:
            cb(chapter_id)
            self.close()
        return _wrapped

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
        # APPEND the take to the clips list, then recompose so
        # playback / export see a single rendered file. The
        # crossfade default (0.15 s) hides the click that bare
        # WAV concat would otherwise produce between takes —
        # writers no longer hear harsh joins between lines.
        self._append_audio_clip(
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
        # Imports are clips too — append + recompose, same as
        # record. Lets writers mix recorded takes with imported
        # bed music / SFX without any special-case path.
        self._append_audio_clip(dest)

    def _append_audio_clip(
            self, path: Path,
            duration: Optional[float] = None) -> None:
        """Add ``path`` as a new clip placed at the end of the
        current timeline. With ``start_time_seconds`` set the
        writer can immediately drag the block in the timeline
        to a different position; the default behavior matches
        the old append-and-stitch flow."""
        from src.video_studio.models import GroupAudioClip
        if duration is None or duration <= 0:
            duration = (
                probe_audio_duration_seconds(path) or 0.0)
        clips = getattr(self._group, "audio_clips", None)
        if clips is None:
            self._group.audio_clips = []
            clips = self._group.audio_clips
        # Auto-position at the END of the existing arrangement.
        # If the previous take has a positive trailing fade, we
        # tuck the new clip under that fade by the same amount
        # so transitions stay smooth without manual tweaking.
        place_at = 0.0
        if clips:
            last = clips[-1]
            last_end = (
                (last.start_time_seconds or 0.0)
                + self._clip_kept_seconds(last))
            # Default 0.15 s overlap so a writer reading line
            # by line doesn't get a hard cut between takes.
            place_at = max(0.0, last_end - 0.15)
        # First clip ignores crossfade_seconds (no previous to
        # fade from), but we still store the default so a later
        # reorder doesn't suddenly need a value.
        idx = len(clips) + 1
        clips.append(GroupAudioClip(
            label=f"Take {idx}",
            audio_path=str(path),
            duration_seconds=float(duration),
            start_time_seconds=place_at,
        ))
        self._refresh_clip_list()
        self._recompose_overlay()

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

        # Per-clip variants when the playhead is sitting on a
        # clip block; whole-overlay fallback when it's in a gap.
        # Label calls out the active scope so the writer knows
        # whether they're chopping one clip or the rendered mix.
        under_clip = None
        if playhead_inside:
            under_clip = self._clip_under_playhead(playhead)
        if under_clip is not None:
            before_label = (
                f"⏪  Trim '{under_clip.label}' from start to "
                "red line (keep the tail)")
            after_label = (
                f"⏩  Trim '{under_clip.label}' from red line "
                "to end (keep the head)")
        else:
            before_label = (
                "⏪  Trim before red line (keep what comes "
                "after)")
            after_label = (
                "⏩  Trim after red line (keep what comes "
                "before)")
        trim_before_act = menu.addAction(before_label)
        trim_before_act.setEnabled(playhead_inside)
        trim_before_act.setToolTip(
            "Scoped to the clip the red line is on when it's "
            "sitting on a block; falls back to whole-overlay "
            "trim when the playhead is in a gap. The trim is "
            "stored on the clip itself, so it survives the "
            "next recompose.")
        trim_before_act.triggered.connect(
            self._op_trim_before_playhead)

        trim_after_act = menu.addAction(after_label)
        trim_after_act.setEnabled(playhead_inside)
        trim_after_act.setToolTip(
            "Scoped to the clip the red line is on. Survives "
            "recompose because it writes to the clip's "
            "trim_out, not the rendered cache.")
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
        self._apply_overlay_trim(trim_in, trim_out)

    def _op_trim_before_playhead(self) -> None:
        """Chop a single clip from its start to the red line.

        Scoped to the clip the playhead is *over* — bumps that
        clip's ``trim_in`` to the playhead time (in source
        coordinates), leaves every other clip alone. If the
        playhead is over empty timeline (a gap between clips),
        falls back to the legacy whole-overlay behavior so
        writers can still trim the head of a multi-clip
        arrangement.
        """
        playhead = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        if playhead <= 0:
            return
        clip = self._clip_under_playhead(playhead)
        if clip is not None:
            self._trim_clip_to_playhead(
                clip, playhead, side="in")
            return
        composed = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if composed <= 0:
            return
        self._apply_overlay_trim(playhead, composed)

    def _op_trim_after_playhead(self) -> None:
        """Chop a single clip from the red line to its end.
        Symmetric to ``_op_trim_before_playhead`` — scoped to
        the clip the playhead is on. The playhead-in-a-gap
        fallback drops to the legacy whole-overlay path."""
        playhead = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        duration = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if playhead <= 0 or playhead >= duration:
            return
        clip = self._clip_under_playhead(playhead)
        if clip is not None:
            self._trim_clip_to_playhead(
                clip, playhead, side="out")
            return
        self._apply_overlay_trim(0.0, playhead)

    def _clip_under_playhead(
            self, playhead: float):
        """Find the clip whose timeline block covers
        ``playhead``. Routed through the timeline widget so
        we use one consistent definition of "effective
        duration"."""
        if not hasattr(self, "_timeline"):
            return None
        clip_id = self._timeline.audio_clip_at_seconds(
            playhead)
        if not clip_id:
            return None
        for c in (
                getattr(
                    self._group, "audio_clips", []) or []):
            if c.id == clip_id:
                return c
        return None

    def _trim_clip_to_playhead(
            self, clip, playhead: float,
            *, side: str) -> None:
        """Adjust ``clip.trim_in`` or ``clip.trim_out`` so the
        clip's visible window ends at the playhead. The math
        translates playhead (group-timeline time) into source
        time by:
            source_offset = playhead - clip.start_time
                            + current_trim_in
        Clamps to leave at least 10 ms of audio so we don't
        ask ffmpeg to render a zero-length clip.
        """
        start = float(
            getattr(clip, "start_time_seconds", 0.0) or 0.0)
        full = float(
            getattr(clip, "duration_seconds", 0.0) or 0.0)
        tin = max(0.0, float(
            getattr(clip, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(clip, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > full:
            tout = full
        offset_in_source = tin + max(0.0, playhead - start)
        offset_in_source = max(
            tin + 0.01,
            min(full - 0.01, offset_in_source))
        if side == "in":
            # Keep tail: shift trim_in forward.
            if offset_in_source >= tout:
                return
            clip.trim_in_seconds = round(
                offset_in_source, 3)
        else:
            # Keep head: pull trim_out back.
            if offset_in_source <= tin:
                return
            clip.trim_out_seconds = (
                0.0
                if abs(offset_in_source - full) < 0.005
                else round(offset_in_source, 3))
        self._refresh_clip_list()
        self._recompose_overlay()

    def _apply_overlay_trim(
            self, trim_in: float, trim_out: float) -> None:
        """Map a trim selection on the COMPOSED overlay back to
        per-clip trim_in/out values so the trim survives the
        next recompose. Three cases:

          1. No clips (legacy decks that escaped migration) →
             fall back to the old ``_apply_audio_op`` which
             bakes a trim into the rendered file directly.
          2. Single clip → apply to that clip.
          3. Multi-clip → translate the selection into
             cumulative offsets, then update the first
             enclosed clip's trim_in + the last enclosed
             clip's trim_out, dropping any clips that fall
             entirely outside the kept window.

        Without this routing the writer's trim would silently
        get undone the next time they recorded a take, because
        ``compose_clips`` always restitches from the original
        sources.
        """
        clips = getattr(self._group, "audio_clips", None) or []
        if not clips:
            self._apply_audio_op(
                "Trim",
                in_point_seconds=trim_in,
                out_point_seconds=trim_out)
            return
        if len(clips) == 1:
            c = clips[0]
            c.trim_in_seconds = round(max(0.0, trim_in), 3)
            full = float(
                getattr(c, "duration_seconds", 0.0) or 0.0)
            c.trim_out_seconds = (
                0.0
                if abs(trim_out - full) < 0.01
                else round(trim_out, 3))
            self._refresh_clip_list()
            # Clear the overlay handles — their job is done now
            # that the trim lives on the clip.
            self._group.overlay_trim_in_seconds = 0.0
            self._group.overlay_trim_out_seconds = 0.0
            self._recompose_overlay()
            return
        # Multi-clip path. Walk clips to find which contain
        # the trim_in / trim_out markers in composed-time.
        offsets: list[float] = []
        running = 0.0
        for i, c in enumerate(clips):
            if i > 0:
                xf = max(
                    0.0, float(
                        getattr(c, "crossfade_seconds", 0.15)
                        or 0.0))
                running -= xf
            offsets.append(running)
            running += self._clip_kept_seconds(c)
        # offsets[i] = start of clip i in composed coordinates.
        end_offsets = [
            offsets[i] + self._clip_kept_seconds(clips[i])
            for i in range(len(clips))]
        first_idx = next(
            (i for i in range(len(clips))
             if end_offsets[i] > trim_in + 1e-3),
            None)
        last_idx = next(
            (i for i in range(len(clips) - 1, -1, -1)
             if offsets[i] < trim_out - 1e-3),
            None)
        if first_idx is None or last_idx is None or first_idx > last_idx:
            QMessageBox.warning(
                self, "Trim selection out of range",
                "The selection didn't land on any clip.")
            return
        kept = clips[first_idx:last_idx + 1]
        # Adjust the in/out of the EDGE clips. Each adjustment
        # is in clip-source coordinates: subtract the
        # composed-time offset of the clip's start, then add
        # the clip's existing trim_in (because the source's
        # zero is shifted by the writer's earlier trim).
        first_clip = kept[0]
        delta_in = max(0.0, trim_in - offsets[first_idx])
        first_clip.trim_in_seconds = round(
            (first_clip.trim_in_seconds or 0.0) + delta_in, 3)
        last_clip = kept[-1]
        last_full = float(
            getattr(last_clip, "duration_seconds", 0.0) or 0.0)
        last_existing_in = float(
            getattr(last_clip, "trim_in_seconds", 0.0) or 0.0)
        delta_kept = max(
            0.0, trim_out - offsets[last_idx])
        new_last_out = last_existing_in + delta_kept
        if new_last_out >= last_full:
            last_clip.trim_out_seconds = 0.0
        else:
            last_clip.trim_out_seconds = round(
                new_last_out, 3)
        self._group.audio_clips = kept
        self._group.overlay_trim_in_seconds = 0.0
        self._group.overlay_trim_out_seconds = 0.0
        self._refresh_clip_list()
        self._recompose_overlay()

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
        """Play / pause toggle. Play picks up FROM the current
        red-line position so the writer can scrub via double-
        click (or stop mid-clip and resume from there) instead
        of always replaying from the beginning. Pause leaves
        the player position alone; the player itself remembers
        where it was. Stop is a separate button — it ends
        playback without rewinding."""
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
        # Stopped state — fresh load + seek to the playhead so
        # play resumes from wherever the writer parked the red
        # line (via scrub, double-click, or last Stop click).
        seek_seconds = max(
            0.0,
            float(
                getattr(
                    self._timeline,
                    "_playhead_seconds", 0.0)))
        # If playhead sits past the file end we'd never get a
        # ``positionChanged`` event — clamp to a hair before
        # the end so play loads but immediately stops.
        composed_dur = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if composed_dur > 0:
            seek_seconds = min(
                seek_seconds, max(0.0, composed_dur - 0.05))
        # Legacy single-clip trims still get honored when the
        # writer hasn't moved the playhead.
        trim_in = float(
            getattr(
                self._group,
                "overlay_trim_in_seconds", 0.0) or 0.0)
        if seek_seconds <= 0 and trim_in > 0:
            seek_seconds = trim_in
        # Park the seek and let ``_on_media_status_changed``
        # apply it once the file is actually loaded — calling
        # setPosition right after setSource silently drops the
        # seek because the decoder isn't ready yet (that was
        # the "play always starts from the beginning" report).
        self._pending_seek_ms = int(seek_seconds * 1000)
        self._player.setSource(
            QUrl.fromLocalFile(str(path.resolve())))
        # Start playback now; the status handler will seek to
        # ``_pending_seek_ms`` the moment the media reports
        # LoadedMedia / BufferedMedia.
        self._player.play()

    def _on_media_status_changed(self, status) -> None:
        """Fires whenever the player's underlying media changes
        state. We use the loaded / buffered transitions to
        flush any pending seek that was requested before the
        decoder was ready."""
        if self._pending_seek_ms is None:
            return
        try:
            loaded_ok = status in (
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
                QMediaPlayer.MediaStatus.BufferingMedia,
            )
        except Exception:
            loaded_ok = True
        if not loaded_ok:
            return
        # Apply once, clear the pending value so a subsequent
        # status change (e.g. buffering glitches) doesn't snap
        # the playhead back to the original seek target.
        seek_ms = self._pending_seek_ms
        self._pending_seek_ms = None
        try:
            self._player.setPosition(int(seek_ms))
        except Exception as e:
            print(
                f"[group_editor] deferred seek failed: {e}")

    def _on_stop(self) -> None:
        """End playback but leave the red line where it landed
        — the next ▶ Play resumes from there. Use the ↺ Reset
        button to rewind the playhead to 0."""
        self._player.stop()
        # Don't touch ``_playhead_seconds`` — Qt's stop()
        # already cleared the player's internal cursor, but
        # our visual playhead is independent and the writer
        # expects it to mark "where I stopped."

    def _on_add_track(self) -> None:
        """Append a new audio lane below the existing ones.
        The presence of the lane is signaled via
        ``track_gain_db`` getting a zero-dB key, which is what
        ``_track_count`` reads from. We honor the timeline's
        current count (which already includes the implicit
        lane 0 when nothing is recorded yet), so the first
        click creates lane 1, not lane 0."""
        gains = dict(
            getattr(self._group, "track_gain_db", None) or {})
        # Normalize keys to ints; JSON round-trips can turn
        # them into strings.
        clean_gains: dict = {}
        for k, v in gains.items():
            try:
                clean_gains[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        # Start at the lane index one past whatever's currently
        # visible — that's the implicit-or-explicit count from
        # the timeline. Guarantees a new lane appears every
        # click, even when the writer hasn't touched lane 0.
        new_idx = self._timeline._track_count()
        clean_gains[new_idx] = 0.0
        self._group.track_gain_db = clean_gains
        # Friendly default name; writer can rename via the
        # lane header's right-click menu.
        names = dict(
            getattr(self._group, "track_names", None) or {})
        clean_names: dict = {}
        for k, v in names.items():
            try:
                clean_names[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        clean_names[new_idx] = f"Track {new_idx + 1}"
        self._group.track_names = clean_names
        self._timeline._refresh_min_width()
        self._timeline.update()
        self._refresh_tracks_count_label()
        # Auto-scroll the timeline scroll area to the bottom
        # so the writer sees the new lane right away. Without
        # this, the new lane lives below the viewport and the
        # writer has to scroll to notice it appeared.
        try:
            vbar = self._timeline_scroll.verticalScrollBar()
            vbar.setValue(vbar.maximum())
        except Exception:
            pass
        self.deck_modified.emit()

    def _on_zoom_button(self, *, out: bool) -> None:
        """➕ / ➖ buttons step the zoom by 1.5x. Anchored at
        the center of the visible viewport so the scrollbar
        stays roughly where it was (writer's center of
        attention doesn't jump)."""
        factor = (1.0 / 1.5) if out else 1.5
        cur = self._timeline.zoom_px_per_sec()
        # Compute an anchor at the midpoint of the visible
        # viewport, expressed in timeline-widget coordinates.
        viewport = self._timeline_scroll.viewport()
        midpoint_x = (
            self._timeline_scroll.horizontalScrollBar().value()
            + viewport.width() // 2)
        from PyQt6.QtCore import QPoint
        anchor = QPoint(int(midpoint_x), 0)
        self._timeline.set_zoom_px_per_sec(
            cur * factor, anchor_pos=anchor)

    def _on_timeline_zoom_changed(
            self, before_x: int, after_x: int) -> None:
        """Keep the time under the anchor (cursor / viewport
        center) under the same screen pixel by nudging the
        scrollbar by the post-zoom delta."""
        if hasattr(self, "_zoom_label"):
            self._zoom_label.setText(
                f"{int(round(self._timeline.zoom_px_per_sec()))} "
                "px/s")
        if before_x != after_x:
            hbar = (
                self._timeline_scroll.horizontalScrollBar())
            delta = after_x - before_x
            hbar.setValue(hbar.value() + delta)

    def _on_preview_group(self) -> None:
        """Compile this group into a temp MP4 + play it in a
        floating window. The render path is the same one the
        deck export uses (``stitch_slide_deck_to_mp4``), so
        what the writer sees in the preview is what they'll
        ship.

        Render shape:
          * Pull the group's PLACED slides, ordered by start
            time on the group timeline.
          * Build a slim synthetic ``SlideDeckProject`` whose
            ``pages`` are copies of those slides with
            ``duration_seconds`` adjusted to the gap-to-next-
            slide (so a placed slide that holds for a long
            silence renders for that long instead of the
            ``duration_seconds`` field's bare value).
          * Attach the group's composed overlay (the file
            that's already been mixed across all tracks +
            volume) as the first slide's per-slide audio —
            ``stitch_slide_deck_to_mp4`` delays it by zero so
            it plays through the whole render.
          * Render to ``working_dir/group_previews/<group>_<ts>.mp4``
            and open in ``GroupPreviewWindow``.
        """
        from src.video_studio.slide_deck import (
            render_group_to_mp4)
        from src.ui.video_studio.group_preview_window import (
            GroupPreviewWindow)
        # Quick sanity check: refuse to render an empty group
        # so the writer gets a friendlier message than
        # ``render_group_to_mp4``'s generic "no placed slides".
        placed = [
            p for p in self._deck.pages
            if p.group_id == self._group.id
            and p.start_time_seconds_in_group is not None]
        if not placed:
            QMessageBox.information(
                self, "Nothing to preview",
                "Place at least one slide on the timeline "
                "first (drag it from the tray, or use the "
                "tray's right-click → Place at end of "
                "timeline).")
            return
        # Render to a temp file. Stamp with the group id so
        # concurrent group editors don't clobber each other.
        out_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")
        ) / "group_previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / (
            f"{self._group.id}_{stamp}.mp4")
        self._preview_group_btn.setEnabled(False)
        self._preview_group_btn.setText("Rendering…")
        try:
            # Single source of truth — the deck editor's
            # "Preview deck" button also concatenates outputs
            # of THIS helper, so what the writer sees here is
            # exactly what they'll see in the deck preview's
            # segment for this group.
            ok, msg = render_group_to_mp4(
                self._deck, self._group, out_path)
        finally:
            self._preview_group_btn.setEnabled(True)
            self._preview_group_btn.setText("🎬 Preview")
        if not ok:
            QMessageBox.warning(
                self, "Preview render failed", msg)
            return
        # Hold a strong reference so the window survives this
        # method's return — without this, Qt eats it. Reuse
        # the slot for repeat clicks so we don't pile windows.
        try:
            if (getattr(self, "_group_preview_window", None)
                    is not None):
                self._group_preview_window.close()
        except Exception:
            pass
        self._group_preview_window = GroupPreviewWindow(
            out_path,
            group_name=self._group.name or "group")
        self._group_preview_window.show()

    def _refresh_tracks_count_label(self) -> None:
        """Sync the inline "Audio tracks: N" label with the
        current lane count. Called from ``_on_add_track`` and
        from the lane-removal path so the readout stays
        honest."""
        if not hasattr(self, "_tracks_count_label"):
            return
        n = self._timeline._track_count()
        self._tracks_count_label.setText(
            f"Audio tracks: {n}")

    def _on_reset_playhead(self) -> None:
        """Send the red line back to t=0 and stop any playback
        in progress so the next ▶ Play starts at the very
        beginning."""
        self._player.stop()
        self._timeline.set_playhead(0.0)
        self._refresh_play_status()

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
        # Update the now-playing readout (block name + time
        # within the block) on every position tick.
        self._refresh_play_status()

    def _refresh_play_status(self) -> None:
        """Write the playhead's clip + within-clip offset into
        the status label. Empty when no audio is loaded."""
        if not hasattr(self, "_play_status_label"):
            return
        composed = float(
            getattr(
                self._group,
                "overlay_audio_duration_seconds", 0.0) or 0.0)
        if composed <= 0:
            self._play_status_label.setText("")
            return
        ph = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        clip_id = self._timeline.audio_clip_at_seconds(ph)
        if clip_id:
            clip = next(
                (c for c in (
                    getattr(
                        self._group, "audio_clips", [])
                    or [])
                 if c.id == clip_id),
                None)
            if clip is not None:
                start = float(
                    getattr(
                        clip, "start_time_seconds", 0.0)
                    or 0.0)
                offset_in_clip = max(0.0, ph - start)
                eff = self._clip_kept_seconds(clip)
                self._play_status_label.setText(
                    f"▶ {clip.label}  ·  "
                    f"{offset_in_clip:.2f}s / {eff:.2f}s  "
                    f"  (timeline {ph:.2f}s)")
                return
        # Playhead is in a gap or past the end.
        self._play_status_label.setText(
            f"⏸ (between clips)  ·  timeline {ph:.2f}s "
            f"/ {composed:.2f}s")

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

    # ------------------------------------------------------------------
    # Clip list handlers
    # ------------------------------------------------------------------
    def _refresh_clip_list(self) -> None:
        """Rebuild the QListWidget rows from ``audio_clips``.
        Bails when the widget isn't built yet (called from
        ``_append_audio_clip`` before ``_build_ui`` exists)."""
        if not hasattr(self, "_clip_list"):
            return
        from PyQt6.QtWidgets import QListWidgetItem
        from pathlib import Path as _P
        self._clip_list.blockSignals(True)
        self._clip_list.clear()
        from PyQt6.QtGui import QBrush, QColor
        for idx, clip in enumerate(
                getattr(self._group, "audio_clips", []) or []):
            label = clip.label or f"Take {idx + 1}"
            name = _P(clip.audio_path).name if clip.audio_path else "—"
            dur = clip.duration_seconds or 0.0
            xf = (
                f"  · ⤳{clip.crossfade_seconds:.2f}s"
                if idx > 0 else "")
            # Mark unplaced clips clearly so the writer can
            # see at a glance which clips are on the timeline
            # vs parked in the list. Right-click → Add to
            # timeline puts them back; drag-from-list also
            # works.
            unplaced = (
                getattr(clip, "start_time_seconds", None)
                is None)
            placement_mark = (
                "🚫 unplaced — " if unplaced else "")
            text = (
                f"{idx + 1}.  {placement_mark}{label}    "
                f"({dur:.2f}s · {name}){xf}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, clip.id)
            # Allow inline rename via F2 / double-click.
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEditable)
            if unplaced:
                # Dimmed slate text so the row reads as
                # "inactive" without making it unreadable.
                item.setForeground(
                    QBrush(QColor("#94a3b8")))
            self._clip_list.addItem(item)
        self._clip_list.blockSignals(False)

    def _on_clip_renamed(self, item) -> None:
        """Inline rename from the list — strip the rendered
        prefix back off so we just store the writer's label."""
        cid = item.data(Qt.ItemDataRole.UserRole)
        clip = next(
            (c for c in (
                getattr(self._group, "audio_clips", []) or [])
             if c.id == cid),
            None)
        if clip is None:
            return
        # The rendered text is "{n}.  {label}    (...)" — extract
        # the writer-typed slice before the metadata in parens.
        # The optional "🚫 unplaced — " marker prefix for off-
        # timeline clips needs to be stripped too, otherwise
        # renaming an unplaced clip would bake the marker into
        # its stored label.
        raw = item.text() or ""
        import re
        m = re.match(r"^\s*\d+\.\s*(.*?)\s*(?:\(.*)?$", raw)
        candidate = (
            m.group(1).strip() if m else raw.strip())
        if candidate.startswith("🚫 unplaced — "):
            candidate = candidate[
                len("🚫 unplaced — "):].strip()
        clip.label = candidate
        self._refresh_clip_list()
        # Block labels live on the timeline canvas — repaint
        # so the new name shows up on the clip block too. The
        # now-playing readout also reads from the label so it
        # picks up the rename on the next position tick (or
        # immediately for whoever's paused on this clip).
        self._timeline.update()
        self._refresh_play_status()
        self.deck_modified.emit()

    def _on_audio_lane_context_from_timeline(
            self, track_index: int, global_pos) -> None:
        """Right-click on a lane HEADER. Lets the writer
        rename the lane, set its volume in dB, or remove it
        (clips on the removed lane fall back to lane 0)."""
        names = (
            getattr(self._group, "track_names", None) or {})
        gains = (
            getattr(self._group, "track_gain_db", None) or {})
        deessers = (
            getattr(
                self._group,
                "track_deesser_intensity", None) or {})
        mutes = (
            getattr(self._group, "track_muted", None) or {})
        bgs = (
            getattr(
                self._group, "track_background", None) or {})
        cur_name = (
            names.get(track_index)
            or names.get(str(track_index))
            or f"Track {track_index + 1}")
        cur_gain = float(
            gains.get(
                track_index,
                gains.get(str(track_index), 0.0)) or 0.0)
        cur_deesser = float(
            deessers.get(
                track_index,
                deessers.get(str(track_index), 0.0)) or 0.0)
        cur_muted = bool(
            mutes.get(
                track_index,
                mutes.get(str(track_index), False)))
        cur_bg = bool(
            bgs.get(
                track_index,
                bgs.get(str(track_index), False)))
        deesser_summary = (
            f"{cur_deesser:.2f}" if cur_deesser > 0 else "off")
        mute_summary = "MUTED" if cur_muted else "audible"
        bg_summary = "BACKGROUND ↻" if cur_bg else "foreground"
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        header = menu.addAction(
            f"🎚  {cur_name}  ·  {cur_gain:+.1f} dB  ·  "
            f"de-esser {deesser_summary}  ·  {mute_summary}  "
            f"·  {bg_summary}")
        header.setEnabled(False)
        menu.addSeparator()
        rename_act = menu.addAction("✏️  Rename track…")
        volume_act = menu.addAction(
            f"🔊  Set volume…  (current {cur_gain:+.1f} dB)")
        deesser_act = menu.addAction(
            f"🎤  De-esser…  (current {deesser_summary})")
        deesser_act.setToolTip(
            "Tame sibilance ('s', 'sh', 'ch' sounds) in "
            "this track. 0 = off, 0.4–0.6 is the usual "
            "range for close-mic'd dialog. Higher values "
            "start to muffle consonants. Applied to every "
            "clip on this lane when the overlay renders.")
        # ─ Mute toggle ─
        mute_act = menu.addAction(
            "🔈  Unmute track"
            if cur_muted
            else "🔇  Mute track")
        mute_act.setToolTip(
            "Silence every clip on this lane when the overlay "
            "renders. Clips stay visible on the timeline (just "
            "dimmed) so you can still edit them; toggling back "
            "brings them right into the mix. Useful for "
            "soloing the lane you're currently working on "
            "without moving anything around.")
        # ─ Background toggle ─
        bg_act = menu.addAction(
            "🎵  Set as foreground track"
            if cur_bg
            else "🎵  Set as background track (loop ↻)")
        bg_act.setToolTip(
            "Mark this lane as a background bed (music, "
            "ambient loop). Every clip on the lane will loop "
            "at render time until the last stopping point of "
            "the foreground lanes — or until the next clip on "
            "this same lane, whichever comes first. Clips "
            "still show at their native length on the timeline "
            "with a ↻ badge; the loop is applied by "
            "``compose_clips`` at recompose time.")
        menu.addSeparator()
        # ─ Replicate this lane into another group ─
        other_groups = [
            g for g in (getattr(self._deck, "groups", None) or [])
            if g.id != self._group.id]
        copy_act = menu.addAction(
            "📋  Copy this track to another group…")
        copy_act.setToolTip(
            "Replicate every clip on this lane — with its gain, "
            "fades, de-esser and background-loop settings — into "
            "another group. The copy is independent: editing it "
            "later won't touch this one. Handy for reusing a "
            "music bed or a recurring SFX across groups.")
        copy_act.setEnabled(bool(other_groups))
        # ─ Promote this lane to the deck-wide background bed ─
        deck_bg_act = menu.addAction(
            "🎼  Use this track as the deck background…")
        deck_bg_act.setToolTip(
            "Copy this lane's clips into the deck-wide background "
            "bed — it will loop (ducked) under EVERY group for the "
            "whole deck. Set the level from the deck's Background "
            "controls in the slide editor.")
        menu.addSeparator()
        remove_act = menu.addAction(
            "🗑  Remove track (clips fall to Track 1)")
        # Lane 0 is the canonical primary; refusing its removal
        # keeps the model sane (every clip needs a lane).
        remove_act.setEnabled(track_index != 0)
        action = menu.exec(global_pos)
        if action is None:
            return
        if action is copy_act:
            self._copy_track_to_group(track_index, other_groups)
            return
        if action is deck_bg_act:
            self._track_to_deck_background(track_index, cur_name)
            return
        if action is rename_act:
            from PyQt6.QtWidgets import (
                QInputDialog as _QID)
            new_name, ok = _QID.getText(
                self, "Rename track",
                "Track name:", text=cur_name)
            if ok and new_name.strip():
                clean_names = {
                    int(k): str(v)
                    for k, v in (names or {}).items()
                    if str(k).lstrip("-").isdigit()}
                clean_names[track_index] = new_name.strip()
                self._group.track_names = clean_names
                self._timeline.update()
                self.deck_modified.emit()
        elif action is volume_act:
            val = self._param_popup(
                "Track volume",
                f"Volume for '{cur_name}' in dB. Positive "
                "boosts, negative attenuates. Applied on top "
                "of each clip's own gain when the overlay "
                "renders.",
                value=cur_gain, min_v=-30.0, max_v=20.0,
                decimals=1, step=0.5, suffix=" dB")
            if val is not None:
                clean_gains = {
                    int(k): float(v)
                    for k, v in (gains or {}).items()
                    if str(k).lstrip("-").isdigit()}
                clean_gains[track_index] = float(val)
                self._group.track_gain_db = clean_gains
                self._timeline.update()
                self._recompose_overlay()
        elif action is deesser_act:
            val = self._param_popup(
                "Track de-esser",
                f"De-esser intensity for '{cur_name}'. "
                "0 turns the filter off. 0.4–0.6 is the "
                "usual range for taming sibilance on "
                "close-mic'd dialog; >0.8 starts to muffle "
                "consonants. The filter targets 5–8 kHz "
                "where harsh 'ess' and 'sh' sounds live.",
                value=cur_deesser, min_v=0.0, max_v=1.0,
                decimals=2, step=0.05, suffix="")
            if val is not None:
                clean_de = {
                    int(k): float(v)
                    for k, v in (deessers or {}).items()
                    if str(k).lstrip("-").isdigit()}
                if float(val) <= 0:
                    clean_de.pop(track_index, None)
                else:
                    clean_de[track_index] = float(val)
                self._group.track_deesser_intensity = (
                    clean_de)
                self._timeline.update()
                self._recompose_overlay()
        elif action is mute_act:
            # Flip the lane's mute state; drop entries that
            # go back to False so the dict stays minimal.
            clean_mutes = {
                int(k): bool(v)
                for k, v in (mutes or {}).items()
                if str(k).lstrip("-").isdigit()
                and bool(v)}
            if cur_muted:
                clean_mutes.pop(track_index, None)
            else:
                clean_mutes[track_index] = True
            self._group.track_muted = clean_mutes
            self._timeline.update()
            self._recompose_overlay()
        elif action is bg_act:
            # Flip the lane's background flag; same minimal-
            # dict discipline as ``track_muted``.
            clean_bgs = {
                int(k): bool(v)
                for k, v in (bgs or {}).items()
                if str(k).lstrip("-").isdigit()
                and bool(v)}
            if cur_bg:
                clean_bgs.pop(track_index, None)
            else:
                clean_bgs[track_index] = True
            self._group.track_background = clean_bgs
            self._timeline.update()
            self._recompose_overlay()
        elif action is remove_act:
            # Move clips to lane 0 and drop the gain/name
            # entries.
            for c in (
                    getattr(
                        self._group, "audio_clips", [])
                    or []):
                if int(getattr(c, "track_index", 0)
                       or 0) == track_index:
                    c.track_index = 0
            clean_gains = {
                int(k): float(v)
                for k, v in (gains or {}).items()
                if str(k).lstrip("-").isdigit()
                and int(k) != track_index}
            clean_names = {
                int(k): str(v)
                for k, v in (names or {}).items()
                if str(k).lstrip("-").isdigit()
                and int(k) != track_index}
            self._group.track_gain_db = clean_gains
            self._group.track_names = clean_names
            # Drop the de-esser entry too so re-adding a lane
            # at the same index doesn't inherit stale config.
            clean_de = {
                int(k): float(v)
                for k, v in (deessers or {}).items()
                if str(k).lstrip("-").isdigit()
                and int(k) != track_index}
            self._group.track_deesser_intensity = clean_de
            clean_mutes = {
                int(k): bool(v)
                for k, v in (mutes or {}).items()
                if str(k).lstrip("-").isdigit()
                and int(k) != track_index
                and bool(v)}
            self._group.track_muted = clean_mutes
            clean_bgs = {
                int(k): bool(v)
                for k, v in (bgs or {}).items()
                if str(k).lstrip("-").isdigit()
                and int(k) != track_index
                and bool(v)}
            self._group.track_background = clean_bgs
            self._timeline._refresh_min_width()
            self._timeline.update()
            self._refresh_tracks_count_label()
            self._recompose_overlay()

    def _recompose_group_overlay(self, group) -> None:
        """Recompose an ARBITRARY group's overlay from its clips
        (used when we mutate a group other than the one open in
        this editor — e.g. after copying a track into it). Writes
        a fresh rendered WAV and updates the group's cache so the
        next export / open picks it up without a manual recompose.
        """
        from src.video_studio.audio_edit import compose_clips
        from datetime import datetime as _dt
        clips = getattr(group, "audio_clips", None) or []
        if not clips:
            group.overlay_audio_path = ""
            group.overlay_audio_duration_seconds = 0.0
            return
        dest_dir = Path(
            self._deck.working_dir
            or (Path.home() / ".writingaid_slides")) / "group_overlay"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"{group.id}_composed_{stamp}.wav"
        result = compose_clips(
            clips, dest,
            track_gain_db=getattr(group, "track_gain_db", None),
            track_deesser_intensity=getattr(
                group, "track_deesser_intensity", None),
            track_muted=getattr(group, "track_muted", None),
            track_background=getattr(
                group, "track_background", None))
        if result.success:
            group.overlay_audio_path = str(dest)
            group.overlay_audio_duration_seconds = float(
                result.duration_seconds or 0.0)

    def _copy_track_to_group(
            self, track_index: int, other_groups: list) -> None:
        """Replicate this lane into another group the writer
        picks, then recompose that group so its audio is ready."""
        from src.video_studio.slide_deck import copy_group_track
        if not other_groups:
            return
        labels = [
            (g.name or g.id) for g in other_groups]
        choice, ok = QInputDialog.getItem(
            self, "Copy track to group",
            "Copy this track into which group?",
            labels, 0, False)
        if not ok or not choice:
            return
        target = other_groups[labels.index(choice)]
        new_idx = copy_group_track(
            self._group, track_index, target)
        self._recompose_group_overlay(target)
        self.deck_modified.emit()
        QMessageBox.information(
            self, "Track copied",
            f"Copied this track into '{target.name or target.id}' "
            f"as Track {new_idx + 1}. Open that group to fine-tune "
            f"its placement.")

    def _track_to_deck_background(
            self, track_index: int, track_name: str) -> None:
        """Copy this lane's clips into the deck-wide background bed
        so it loops (ducked) under every group."""
        from src.video_studio.slide_deck import copy_group_track
        clips = [
            c for c in (getattr(
                self._group, "audio_clips", None) or [])
            if int(getattr(c, "track_index", 0) or 0)
            == track_index]
        if not clips:
            QMessageBox.information(
                self, "Empty track",
                "This track has no clips to use as a background.")
            return
        existing = getattr(self._deck, "background_group", None)
        if existing is not None and (
                getattr(existing, "audio_clips", None) or []):
            if QMessageBox.question(
                    self, "Replace deck background?",
                    "The deck already has a background bed. "
                    "Replace it with this track?") != \
                    QMessageBox.StandardButton.Yes:
                return
        # Copy this lane (clips + its lane treatment) into a fresh
        # background group so the deck bed is fully editable and
        # independent of this group.
        from src.video_studio.models import SlideGroup as _SG
        bg = _SG(name="Deck background")
        copy_group_track(self._group, track_index, bg, 0)
        self._deck.background_group = bg
        self._deck.background_source_label = (
            f"copied from group "
            f"'{self._group.name or self._group.id}' · "
            f"{track_name}")
        self.deck_modified.emit()
        QMessageBox.information(
            self, "Deck background set",
            "This track is now the deck's background bed — it will "
            "loop (ducked) under every group on export. Adjust its "
            "level from the slide editor's Background controls.")

    def _on_slide_context_from_timeline(
            self, page_id: str, global_pos) -> None:
        """Right-click on a slide block. Pops a slim menu at
        the click with view + remove-from-timeline +
        remove-from-group. Mirrors the audio-clip menu so the
        writer learns one set of gestures."""
        page = next(
            (p for p in self._deck.pages if p.id == page_id),
            None)
        if page is None:
            return
        self._timeline.select_audio_clip(None)
        self._timeline._selected_page_id = page_id
        self._timeline.update()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        # Header — non-actionable, shows label + position.
        raw = page.label or "(unnamed)"
        disp = raw if len(raw) <= 24 else raw[:21] + "…"
        start = float(
            getattr(
                page, "start_time_seconds_in_group", 0.0)
            or 0.0)
        header = menu.addAction(
            f"🖼  {disp}  ·  at {start:.2f}s")
        header.setEnabled(False)
        menu.addSeparator()
        view_act = menu.addAction("🔍  Preview slide image…")
        # Transition INTO this slide — the exporter applies it
        # at the join with the previous slide. Two entries
        # for discoverability:
        #   * Top-level "🎞  Set transition…" opens a combined
        #     type+duration dialog. This is the obvious path
        #     writers find first; submenus are easy to miss.
        #   * "Quick pick" submenu lists every transition type
        #     for one-click changes; doesn't ask for duration
        #     (uses current).
        cur_trans = (
            getattr(page, "transition_in", "cut") or "cut")
        cur_trans_secs = float(
            getattr(page, "transition_seconds", 0.7) or 0.7)
        set_transition_act = menu.addAction(
            f"🎞  Set transition…  "
            f"(currently {cur_trans}"
            + (f" {cur_trans_secs:.2f}s"
               if cur_trans != "cut" else "")
            + ")")
        set_transition_act.setToolTip(
            "Opens a dialog to pick the transition INTO this "
            "slide + how long it should last. The exporter "
            "honors both — picked transition + duration land "
            "in the final MP4 / preview.")
        transition_menu = menu.addMenu(
            "🎞  Quick pick transition")
        from src.video_studio.models import (
            CHAPTER_TRANSITIONS as _CT)
        trans_actions = {}
        for key, label in _CT:
            act = transition_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(key == cur_trans)
            trans_actions[act] = key
        unplace_act = menu.addAction(
            "⤴  Remove from timeline (keep in group)")
        unplace_act.setToolTip(
            "Drops the block off the timeline; the slide "
            "stays a member of the group. Drag it from the "
            "tray to put it back on the timeline.")
        menu.addSeparator()
        remove_act = menu.addAction(
            "🗑  Remove from group entirely")
        remove_act.setToolTip(
            "Drops the slide from the group's member list. "
            "The slide stays in the deck and other groups.")
        delete_act = menu.addAction(
            "❌  Delete slide from the deck")
        delete_act.setToolTip(
            "Delete this slide everywhere — removes it from the "
            "group AND the whole deck. Cannot be undone.")
        action = menu.exec(global_pos)
        if action is None:
            return
        if action is view_act:
            self._view_slide(page_id)
        elif action is set_transition_act:
            self._open_slide_transition_dialog(page)
        elif action in trans_actions:
            new_key = trans_actions[action]
            page.transition_in = new_key
            page.updated_at = datetime.now()
            # Non-cut transitions need a duration. Pop a follow-
            # up popup pre-seeded with the current value so the
            # writer can keep tweaking without losing context.
            if new_key != "cut":
                val = self._param_popup(
                    "Transition length",
                    f"How long the {new_key} transition "
                    "into this slide should run, in seconds.",
                    value=cur_trans_secs,
                    min_v=0.05, max_v=5.0,
                    decimals=2, step=0.1, suffix=" s")
                if val is not None:
                    page.transition_seconds = float(val)
            self._timeline.update()
            self.deck_modified.emit()
        elif action is unplace_act:
            self._on_unplace_selected()
        elif action is remove_act:
            self._on_remove_from_group()
        elif action is delete_act:
            self._delete_slide(page_id)

    def _open_slide_transition_dialog(self, page) -> None:
        """Modal dialog to pick the transition INTO ``page`` +
        its duration. Both values land on the page model and
        the timeline repaints. The exporter
        (``stitch_slide_deck_to_mp4``) reads ``transition_in``
        + ``transition_seconds`` per page when stitching, so
        whatever the writer picks shows up in the final deck.
        """
        from PyQt6.QtWidgets import (
            QDialog as _QD, QComboBox as _QC,
            QDoubleSpinBox as _DS, QFormLayout as _FL,
            QDialogButtonBox as _DBB, QLabel as _QL,
            QVBoxLayout as _VL,
        )
        from src.video_studio.models import (
            CHAPTER_TRANSITIONS as _CT)
        dlg = _QD(self)
        dlg.setWindowTitle(
            f"Transition — {page.label or 'slide'}")
        dlg.setModal(True)
        outer = _VL(dlg)
        info = _QL(
            "Pick the transition that plays INTO this slide "
            "(at the join with the previous slide). The "
            "duration controls how long the blend lasts; "
            "0.7s is a typical crossfade.")
        info.setWordWrap(True)
        outer.addWidget(info)
        form = _FL()
        type_combo = _QC()
        cur_key = (
            getattr(page, "transition_in", "cut") or "cut")
        cur_idx = 0
        for i, (key, label) in enumerate(_CT):
            type_combo.addItem(label, key)
            if key == cur_key:
                cur_idx = i
        type_combo.setCurrentIndex(cur_idx)
        form.addRow("Type", type_combo)
        dur_spin = _DS()
        dur_spin.setRange(0.05, 5.0)
        dur_spin.setDecimals(2)
        dur_spin.setSingleStep(0.1)
        dur_spin.setSuffix(" s")
        dur_spin.setValue(float(
            getattr(page, "transition_seconds", 0.7) or 0.7))
        form.addRow("Length", dur_spin)
        outer.addLayout(form)
        # Disable duration when "cut" is selected (no blend
        # length matters for an instant cut).
        def _toggle_dur_enabled(_i: int) -> None:
            key = type_combo.currentData()
            dur_spin.setEnabled(key != "cut")
        type_combo.currentIndexChanged.connect(
            _toggle_dur_enabled)
        _toggle_dur_enabled(0)
        buttons = _DBB(
            _DBB.StandardButton.Ok
            | _DBB.StandardButton.Cancel)
        outer.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec() != _QD.DialogCode.Accepted:
            return
        new_key = type_combo.currentData() or "cut"
        new_dur = float(dur_spin.value())
        page.transition_in = new_key
        if new_key == "cut":
            # Preserve the previous duration on the model in
            # case the writer flips back to a non-cut, but the
            # exporter reads transition_in first and skips
            # blending entirely when it's "cut".
            pass
        else:
            page.transition_seconds = new_dur
        page.updated_at = datetime.now()
        self._timeline.update()
        self.deck_modified.emit()

    def _on_audio_clip_selected_from_timeline(
            self, clip_id: str) -> None:
        """A timeline block was clicked. Highlight the matching
        row in the clip list (and clear the row selection when
        ``clip_id`` is empty / not found)."""
        if not hasattr(self, "_clip_list"):
            return
        for i in range(self._clip_list.count()):
            item = self._clip_list.item(i)
            if (item is not None
                    and item.data(Qt.ItemDataRole.UserRole)
                    == clip_id):
                self._clip_list.setCurrentItem(item)
                return
        self._clip_list.clearSelection()

    def _on_audio_clip_context_from_timeline(
            self, clip_id: str, global_pos) -> None:
        """Right-click on a timeline audio block. Pops a slim
        menu AT THE CLICK with a non-actionable header showing
        the clip's truncated name + its current start time. The
        old path forwarded to the clip-list menu, which both
        showed the wrong items (Move up/down don't apply
        from the timeline) and rendered in the wrong screen
        location."""
        clip = next(
            (c for c in (
                getattr(self._group, "audio_clips", []) or [])
             if c.id == clip_id),
            None)
        if clip is None:
            return
        # Mirror the selection into the clip list so the
        # writer can see which clip the menu is operating on
        # without leaving the timeline.
        if hasattr(self, "_clip_list"):
            for i in range(self._clip_list.count()):
                item = self._clip_list.item(i)
                if (item is not None
                        and item.data(Qt.ItemDataRole.UserRole)
                        == clip_id):
                    self._clip_list.setCurrentItem(item)
                    break
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        # Header — disabled action that just shows the clip
        # label (truncated) + position. The truncation keeps
        # the menu narrow when a writer named their take
        # something long; we want them to see ~24 chars and
        # the ellipsis tells them the rest exists.
        raw_label = clip.label or "(unnamed)"
        if len(raw_label) > 24:
            disp_label = raw_label[:21] + "…"
        else:
            disp_label = raw_label
        start = float(
            getattr(clip, "start_time_seconds", 0.0) or 0.0)
        kept = self._clip_kept_seconds(clip)
        header = menu.addAction(
            f"🔊  {disp_label}  ·  at {start:.2f}s  "
            f"·  {kept:.2f}s long")
        header.setEnabled(False)
        menu.addSeparator()
        rename_act = menu.addAction("✏️  Rename…")
        trim_act = menu.addAction(
            f"✂️  Trim clip…  (kept: {kept:.2f}s of "
            f"{clip.duration_seconds:.2f}s)")
        # Playhead-relative trim entries — only meaningful when
        # the red line is sitting inside THIS clip's block. The
        # actions chop from the clip's start to the playhead
        # (before) or from the playhead to the clip's end
        # (after); the source WAV stays untouched, the trim is
        # baked into the clip's ``trim_in`` / ``trim_out``.
        playhead = float(
            getattr(
                self._timeline, "_playhead_seconds", 0.0))
        clip_end = start + kept
        playhead_in_clip = (
            start + 0.01 < playhead < clip_end - 0.01)
        before_label = (
            "⏪  Trim from start to red line"
            if playhead_in_clip
            else "⏪  Trim from start to red line "
                 "(red line not in this clip)")
        trim_before_act = menu.addAction(before_label)
        trim_before_act.setEnabled(playhead_in_clip)
        trim_before_act.setToolTip(
            "Move this clip's trim_in to the playhead "
            "position. The discarded slice stays in the "
            "source file — you can drag the left handle "
            "back to recover it later.")
        after_label = (
            "⏩  Trim from red line to end"
            if playhead_in_clip
            else "⏩  Trim from red line to end "
                 "(red line not in this clip)")
        trim_after_act = menu.addAction(after_label)
        trim_after_act.setEnabled(playhead_in_clip)
        trim_after_act.setToolTip(
            "Move this clip's trim_out to the playhead "
            "position. The discarded slice stays in the "
            "source file.")
        fade_in_act = menu.addAction(
            f"🌅  Fade in… (current: "
            f"{clip.fade_in_seconds:.2f} s)")
        fade_out_act = menu.addAction(
            f"🌇  Fade out… (current: "
            f"{clip.fade_out_seconds:.2f} s)")
        gain_act = menu.addAction(
            f"🔊  Gain… (current: {clip.gain_db:+.1f} dB)")
        # Per-clip noise reduction. Negative dB enables
        # afftdn at that noise floor; 0 turns it off. Per
        # clip (not per lane) because noise profiles vary
        # between takes — even on the same mic, a take with
        # the AC on differs from one without.
        cur_denoise = float(
            getattr(clip, "denoise_floor_db", 0.0) or 0.0)
        denoise_summary = (
            f"{cur_denoise:.1f} dB floor"
            if cur_denoise < 0 else "off")
        denoise_act = menu.addAction(
            f"🔇  Reduce noise… (current: {denoise_summary})")
        denoise_act.setToolTip(
            "FFT-based noise reduction (afftdn). Set the "
            "noise floor in dB — anything quieter than this "
            "level gets attenuated. Typical values: −25 dB "
            "for clean studio mics, −15 dB for noisy "
            "laptops. 0 turns the filter off.")
        # Per-clip de-esser. Overrides the lane-level
        # setting for THIS clip (useful for a single harsh
        # take on an otherwise-clean lane).
        cur_deesser = float(
            getattr(clip, "deesser_intensity", 0.0) or 0.0)
        deesser_summary = (
            f"{cur_deesser:.2f}"
            if cur_deesser > 0 else "off (uses lane)")
        deesser_act = menu.addAction(
            f"🎤  De-esser… (current: {deesser_summary})")
        deesser_act.setToolTip(
            "Tame sibilance on THIS clip. 0 = off (the "
            "lane's de-esser setting still applies). "
            "Setting >0 here OVERRIDES the lane value for "
            "this clip only.")
        start_act = menu.addAction(
            f"⏱️  Start time… (current: {start:.2f} s)")
        menu.addSeparator()
        # Undo — restores the clip's prior state (label,
        # trim, fades, gain, denoise, deesser, position).
        # Up to 2 snapshots kept per clip. Disabled when
        # there's nothing to undo.
        undo_stack = self._clip_edit_history.get(clip.id)
        has_undo = bool(undo_stack)
        undo_act = menu.addAction(
            "↶  Undo last edit"
            + (f"  ({len(undo_stack)} step(s) available)"
               if has_undo else "  (no edits to undo)"))
        undo_act.setEnabled(has_undo)
        undo_act.setToolTip(
            "Restore this clip's settings to the state "
            "before your most recent edit. Up to 2 prior "
            "states are remembered per clip.")
        # Writer-managed backup. One named slot per clip —
        # saved on demand, restored on demand. Survives close /
        # reload because it persists on the model. Separate
        # from undo because undo is automatic + short-lived,
        # whereas a backup is a deliberate "checkpoint before I
        # try something risky."
        backup = getattr(clip, "backup_snapshot", None)
        backup_when = ""
        if backup:
            try:
                from datetime import datetime as _dt
                backup_when = _dt.fromisoformat(
                    str(backup.get("saved_at", "")))
                backup_when = backup_when.strftime(
                    "%Y-%m-%d %H:%M")
            except Exception:
                backup_when = "earlier"
        save_backup_act = menu.addAction(
            "📌  Save backup of this clip"
            + (f"  (overwrites backup from {backup_when})"
               if backup_when else ""))
        save_backup_act.setToolTip(
            "Snapshot this clip's current settings into the "
            "backup slot. Single slot per clip — saving a "
            "new backup overwrites the previous one. The "
            "snapshot persists with the project so you can "
            "revert to it after a close + reopen.")
        restore_backup_act = menu.addAction(
            "↺  Restore from backup"
            + (f"  (saved {backup_when})"
               if backup_when else "  (no backup saved)"))
        restore_backup_act.setEnabled(bool(backup))
        restore_backup_act.setToolTip(
            "Roll this clip's settings back to whatever was "
            "in the backup slot. The current state is pushed "
            "onto the undo stack first so ↶ Undo still gets "
            "you back if the restore wasn't what you wanted.")
        menu.addSeparator()
        # Non-destructive remove: drops the block off the
        # timeline but keeps the clip in the list (and the
        # source WAV on disk). The writer can re-add by
        # dragging from the list back onto the timeline OR
        # via the list's right-click "Add to timeline".
        unplace_act = menu.addAction(
            "⤴  Remove from timeline (keep in clip list)")
        unplace_act.setToolTip(
            "The clip stays in the list — drag it from there "
            "back onto the timeline whenever you want it "
            "playing again.")
        menu.addSeparator()
        delete_act = menu.addAction("🗑  Delete clip")
        action = menu.exec(global_pos)
        if action is None:
            return
        if action is unplace_act:
            self._unplace_audio_clip(clip)
            return
        if action is rename_act:
            if hasattr(self, "_clip_list"):
                item = self._clip_list.currentItem()
                if item is not None:
                    self._clip_list.editItem(item)
        elif action is trim_act:
            self._snapshot_clip(clip)
            self._open_clip_trim_dialog(clip)
        elif action is trim_before_act:
            self._snapshot_clip(clip)
            # Bake the playhead into this clip's trim_in. The
            # generic ``_trim_clip_to_playhead`` math handles
            # the source-coordinate translation + recompose.
            self._trim_clip_to_playhead(
                clip, playhead, side="in")
        elif action is trim_after_act:
            self._snapshot_clip(clip)
            self._trim_clip_to_playhead(
                clip, playhead, side="out")
        elif action is fade_in_act:
            eff = self._clip_kept_seconds(clip)
            val = self._param_popup(
                "Clip fade in",
                f"Fade-in length for '{clip.label}'.",
                value=clip.fade_in_seconds,
                min_v=0.0, max_v=max(0.05, eff),
                decimals=2, step=0.05, suffix=" s")
            if val is not None:
                self._snapshot_clip(clip)
                clip.fade_in_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is fade_out_act:
            eff = self._clip_kept_seconds(clip)
            val = self._param_popup(
                "Clip fade out",
                f"Fade-out length for '{clip.label}'.",
                value=clip.fade_out_seconds,
                min_v=0.0, max_v=max(0.05, eff),
                decimals=2, step=0.05, suffix=" s")
            if val is not None:
                self._snapshot_clip(clip)
                clip.fade_out_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is gain_act:
            val = self._param_popup(
                "Clip gain",
                f"Gain for '{clip.label}' in dB.",
                value=clip.gain_db, min_v=-30.0, max_v=30.0,
                decimals=1, step=0.5, suffix=" dB")
            if val is not None:
                self._snapshot_clip(clip)
                clip.gain_db = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is denoise_act:
            val = self._param_popup(
                "Reduce noise",
                f"Noise floor for '{clip.label}'. More "
                "negative = more aggressive. Typical: −25 "
                "(clean studio) to −15 (noisy laptop). "
                "0 disables the filter.",
                value=cur_denoise if cur_denoise else -25.0,
                min_v=-50.0, max_v=0.0,
                decimals=1, step=1.0, suffix=" dB")
            if val is not None:
                self._snapshot_clip(clip)
                # Negative or zero only — anything >=0 turns
                # the filter off in compose_clips.
                clip.denoise_floor_db = (
                    0.0 if float(val) >= 0
                    else round(float(val), 1))
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is deesser_act:
            val = self._param_popup(
                "Clip de-esser",
                f"De-esser intensity for '{clip.label}'. "
                "0 = off (lane setting applies). 0.4–0.6 "
                "is the usual range for sibilance.",
                value=cur_deesser, min_v=0.0, max_v=1.0,
                decimals=2, step=0.05, suffix="")
            if val is not None:
                self._snapshot_clip(clip)
                clip.deesser_intensity = max(
                    0.0, min(1.0, float(val)))
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is undo_act:
            self._undo_clip_edit(clip)
        elif action is save_backup_act:
            self._save_clip_backup(clip)
        elif action is restore_backup_act:
            self._restore_clip_backup(clip)
        elif action is start_act:
            val = self._param_popup(
                "Clip start time",
                "Seconds from the start of the timeline.",
                value=start, min_v=0.0, max_v=3600.0,
                decimals=3, step=0.1, suffix=" s")
            if val is not None:
                self._snapshot_clip(clip)
                clip.start_time_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is delete_act:
            self._delete_audio_clip(clip)

    def _on_audio_clip_moved_from_timeline(
            self, clip_id: str, new_start: float) -> None:
        """The writer dragged (or dropped) a clip block on
        the timeline. Recompose so the rendered overlay
        reflects the new position, and refresh the list so
        its rendered metadata (start time) matches."""
        # ``audio_clip_drag`` already mutated the clip in
        # place during the drag, so we just need to publish
        # + recompose.
        self._refresh_clip_list()
        self._recompose_overlay()

    def _on_clip_context_menu(self, point) -> None:
        """Right-click on a clip row — delete, change
        crossfade, set gain."""
        item = self._clip_list.itemAt(point)
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        clips = (
            getattr(self._group, "audio_clips", []) or [])
        clip = next(
            (c for c in clips if c.id == cid), None)
        if clip is None:
            return
        clip_idx = clips.index(clip)
        menu = QMenu(self)
        rename_act = menu.addAction("✏️  Rename…")
        # Per-clip trim — operates on the SOURCE file's range,
        # so the cropped region survives every recompose. The
        # audio-bar trim used to silently lose its setting on
        # the next take because compose_clips always re-stitches
        # from the original sources.
        trim_act = menu.addAction(
            f"✂️  Trim clip…  (kept: "
            f"{self._clip_kept_seconds(clip):.2f}s of "
            f"{clip.duration_seconds:.2f}s)")
        fade_in_act = menu.addAction(
            f"🌅  Fade in… (current: "
            f"{clip.fade_in_seconds:.2f} s)")
        fade_out_act = menu.addAction(
            f"🌇  Fade out… (current: "
            f"{clip.fade_out_seconds:.2f} s)")
        gain_act = menu.addAction(
            f"🔊  Gain… (current: {clip.gain_db:+.1f} dB)")
        # Per-clip start time editor — useful when the writer
        # wants a precise number instead of dragging the block.
        start_act = menu.addAction(
            f"⏱️  Start time… (current: "
            f"{float(getattr(clip, 'start_time_seconds', 0.0) or 0.0):.2f} s)")
        if clip_idx > 0:
            xf_act = menu.addAction(
                f"⤳  Crossfade from previous… "
                f"(current: {clip.crossfade_seconds:.2f} s)")
        else:
            xf_act = None
        # Reorder shortcuts — drag also works, but right-click
        # gives the writer a discoverable path.
        menu.addSeparator()
        move_up_act = menu.addAction("⬆️  Move up")
        move_up_act.setEnabled(clip_idx > 0)
        move_down_act = menu.addAction("⬇️  Move down")
        move_down_act.setEnabled(clip_idx < len(clips) - 1)
        menu.addSeparator()
        # Toggle the clip between "placed on the timeline" and
        # "unplaced" (lives in the list only). Different label
        # depending on current state so the writer always sees
        # what the click will DO.
        if clip.start_time_seconds is None:
            unplace_act = None
            place_act = menu.addAction(
                "📥  Add to timeline (at end)")
            place_act.setToolTip(
                "Drop this clip back on the timeline after "
                "the last placed clip. You can also drag it "
                "directly from the list to position it.")
        else:
            place_act = None
            unplace_act = menu.addAction(
                "⤴  Remove from timeline "
                "(keep in clip list)")
            unplace_act.setToolTip(
                "The clip stays in the list — drag it from "
                "there back onto the timeline whenever you "
                "want it playing again.")
        menu.addSeparator()
        delete_act = menu.addAction("🗑  Delete clip")
        delete_act.setShortcut(QKeySequence("Backspace"))
        action = menu.exec(
            self._clip_list.viewport().mapToGlobal(point))
        if action is None:
            return
        if action is rename_act:
            self._clip_list.editItem(item)
        elif action is trim_act:
            self._open_clip_trim_dialog(clip)
        elif action is fade_in_act:
            eff = self._clip_kept_seconds(clip)
            val = self._param_popup(
                "Clip fade in",
                f"Fade-in length for '{clip.label}'. "
                "Smooths the start of this clip so the join "
                "from silence (or an overlapping previous "
                "clip) doesn't click.",
                value=clip.fade_in_seconds,
                min_v=0.0,
                max_v=max(0.05, eff),
                decimals=2, step=0.05, suffix=" s")
            if val is not None:
                clip.fade_in_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is fade_out_act:
            eff = self._clip_kept_seconds(clip)
            val = self._param_popup(
                "Clip fade out",
                f"Fade-out length for '{clip.label}'. "
                "Smooths the end so it doesn't slam-cut into "
                "the next clip / silence.",
                value=clip.fade_out_seconds,
                min_v=0.0,
                max_v=max(0.05, eff),
                decimals=2, step=0.05, suffix=" s")
            if val is not None:
                clip.fade_out_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is start_act:
            current = float(
                getattr(
                    clip, "start_time_seconds", 0.0) or 0.0)
            val = self._param_popup(
                "Clip start time",
                "When this clip begins playing inside the "
                "group's overlay, measured in seconds from "
                "the start of the timeline. Negative isn't "
                "allowed; gaps render as silence.",
                value=current, min_v=0.0, max_v=3600.0,
                decimals=3, step=0.1, suffix=" s")
            if val is not None:
                clip.start_time_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif action is move_up_act:
            self._reorder_clip(clip_idx, clip_idx - 1)
        elif action is move_down_act:
            self._reorder_clip(clip_idx, clip_idx + 1)
        elif action is gain_act:
            val = self._param_popup(
                "Clip gain",
                f"Gain for '{clip.label}' in dB. Positive "
                "boosts, negative attenuates. Applied during "
                "recompose, so the source file stays untouched.",
                value=clip.gain_db, min_v=-30.0, max_v=30.0,
                decimals=1, step=0.5, suffix=" dB")
            if val is not None:
                clip.gain_db = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif xf_act is not None and action is xf_act:
            val = self._param_popup(
                "Crossfade",
                "Smooth transition between this clip and the "
                "previous one. Larger values blend more of the "
                "tail of the previous take with the head of "
                "this one. Default 0.15 s hides recording-stop "
                "clicks without making the join obvious.",
                value=clip.crossfade_seconds, min_v=0.0,
                max_v=2.0, decimals=2, step=0.05, suffix=" s")
            if val is not None:
                clip.crossfade_seconds = float(val)
                self._refresh_clip_list()
                self._recompose_overlay()
        elif unplace_act is not None and action is unplace_act:
            self._unplace_audio_clip(clip)
        elif place_act is not None and action is place_act:
            self._place_audio_clip_at_end(clip)
        elif action is delete_act:
            # Routed through the shared helper so the shift-
            # subsequent-clips behavior matches the timeline
            # right-click + Delete shortcut paths.
            self._delete_audio_clip(clip)

    # Fields we snapshot for undo. Anything else on the clip
    # (id, audio_path, created_at, track_index) we want to
    # KEEP across an undo since they're identity / placement
    # metadata, not editable settings.
    _CLIP_UNDO_FIELDS = (
        "label",
        "trim_in_seconds",
        "trim_out_seconds",
        "gain_db",
        "fade_in_seconds",
        "fade_out_seconds",
        "crossfade_seconds",
        "deesser_intensity",
        "denoise_floor_db",
        "start_time_seconds",
    )

    def _snapshot_clip(self, clip) -> None:
        """Capture the editable fields of ``clip`` so a later
        ↶ Undo can restore them. The deque caps at 2 entries
        per clip — the third snapshot evicts the oldest.

        Called BEFORE every mutating clip edit (gain,
        denoise, deesser, trim, fade, start time, rename).
        Cheap (just a dict of primitives) so no perf concern
        even when the writer is rapid-firing edits.
        """
        snap = {
            f: getattr(clip, f, None)
            for f in self._CLIP_UNDO_FIELDS}
        stack = self._clip_edit_history.get(clip.id)
        if stack is None:
            stack = self._deque_cls(maxlen=2)
            self._clip_edit_history[clip.id] = stack
        stack.append(snap)

    def _undo_clip_edit(self, clip) -> None:
        """Pop the most recent snapshot for ``clip`` and write
        its values back onto the clip. Refreshes the list +
        recomposes so the writer sees the rollback in both
        the clip list AND the rendered overlay immediately."""
        stack = self._clip_edit_history.get(clip.id)
        if not stack:
            return
        snap = stack.pop()
        for f, v in snap.items():
            try:
                setattr(clip, f, v)
            except Exception as exc:
                print(
                    f"[group_editor] undo could not "
                    f"restore {f!r}: {exc}")
        # Don't push a counter-snapshot — undo is one-way
        # here (no redo) since the writer's "save 2 previous
        # copies" implies a simple back-button history.
        self._refresh_clip_list()
        self._timeline.update()
        self._recompose_overlay()

    def _save_clip_backup(self, clip) -> None:
        """Snapshot the clip's current editable settings into
        ``clip.backup_snapshot``. Persists on the model so it
        survives close + reopen. Single slot — saving again
        overwrites whatever was there.
        """
        from datetime import datetime as _dt
        fields = {
            f: getattr(clip, f, None)
            for f in self._CLIP_UNDO_FIELDS}
        clip.backup_snapshot = {
            "saved_at": _dt.now().isoformat(),
            "fields": fields,
        }
        # Fire deck_modified so autosave persists the backup
        # immediately — writers expect a backup to survive
        # even an unexpected quit right after.
        self._refresh_clip_list()
        self.deck_modified.emit()
        QMessageBox.information(
            self, "Backup saved",
            f"Saved a backup of '{clip.label}'. Use "
            "↺ Restore from backup on the same right-click "
            "menu to roll back here later.")

    def _restore_clip_backup(self, clip) -> None:
        """Apply ``clip.backup_snapshot`` to the live clip.
        Pushes the current state onto the undo stack first so
        the writer can still ↶ Undo back out of the restore
        if it wasn't what they expected.
        """
        backup = getattr(clip, "backup_snapshot", None)
        if not backup:
            return
        fields = backup.get("fields") or {}
        if not fields:
            return
        # Snapshot CURRENT state into the undo stack before
        # overwriting — gives the writer a one-step out.
        self._snapshot_clip(clip)
        for f, v in fields.items():
            if f in self._CLIP_UNDO_FIELDS:
                try:
                    setattr(clip, f, v)
                except Exception as exc:
                    print(
                        f"[group_editor] restore could not "
                        f"set {f!r}: {exc}")
        self._refresh_clip_list()
        self._timeline.update()
        self._recompose_overlay()

    @staticmethod
    def _clip_kept_seconds(clip) -> float:
        """trim_out − trim_in (with the sentinel resolved). The
        amount of the source file that actually plays."""
        full = float(
            getattr(clip, "duration_seconds", 0.0) or 0.0)
        tin = max(0.0, float(
            getattr(clip, "trim_in_seconds", 0.0) or 0.0))
        tout = float(
            getattr(clip, "trim_out_seconds", 0.0) or 0.0)
        if tout <= 0 or tout > full:
            tout = full
        return max(0.0, tout - tin)

    def _unplace_audio_clip(self, clip) -> None:
        """Take an audio clip off the timeline without
        deleting it. The clip's row stays in the clip list
        with an "unplaced" marker; ``start_time_seconds``
        becomes None so ``compose_clips`` skips it and the
        timeline stops rendering its block. Subsequent clips
        slide left to close the gap, mirroring what
        ``_delete_audio_clip`` does — the writer's intent in
        both cases is "this clip is gone from playback right
        now."""
        if clip is None:
            return
        start = float(
            getattr(clip, "start_time_seconds", 0.0) or 0.0)
        eff = self._clip_kept_seconds(clip)
        clips = (
            getattr(self._group, "audio_clips", []) or [])
        # Shift placed clips that started AFTER this one to
        # close the gap.
        for c in clips:
            if c.id == clip.id:
                continue
            other_start = getattr(
                c, "start_time_seconds", None)
            if other_start is None:
                continue
            os = float(other_start)
            if os > start:
                c.start_time_seconds = round(
                    max(0.0, os - eff), 3)
        clip.start_time_seconds = None
        # Drop selection so the next paint doesn't try to
        # highlight a block that isn't on the timeline.
        if hasattr(self, "_timeline"):
            try:
                self._timeline.select_audio_clip(None)
            except Exception:
                pass
        self._refresh_clip_list()
        self._recompose_overlay()

    def _place_audio_clip_at_end(self, clip) -> None:
        """Drop an unplaced clip back onto the timeline,
        landing just after the last currently-placed clip
        (with a 0.15 s overlap so reads stay smooth — same
        default the append-on-record path uses)."""
        if clip is None:
            return
        clips = (
            getattr(self._group, "audio_clips", []) or [])
        placed = [
            c for c in clips
            if c.id != clip.id
            and getattr(c, "start_time_seconds", None)
            is not None
        ]
        if not placed:
            new_start = 0.0
        else:
            last = max(
                placed,
                key=lambda c: float(
                    getattr(c, "start_time_seconds", 0.0)
                    or 0.0)
                + self._clip_kept_seconds(c))
            last_end = (
                float(
                    getattr(
                        last, "start_time_seconds", 0.0)
                    or 0.0)
                + self._clip_kept_seconds(last))
            new_start = max(0.0, last_end - 0.15)
        clip.start_time_seconds = round(new_start, 3)
        self._refresh_clip_list()
        self._recompose_overlay()

    def _delete_audio_clip(
            self, clip, *, confirm: bool = True) -> None:
        """Remove a clip and shift every clip that started
        AFTER it to the left by the deleted clip's effective
        duration. Same gesture from the clip list, the
        timeline right-click, and the Delete / Backspace
        shortcut — they all route here so the shift semantics
        stay identical."""
        if clip is None:
            return
        if confirm:
            choice = QMessageBox.question(
                self, "Delete clip",
                f"Remove '{clip.label}' from this group?\n\n"
                "Clips that started AFTER it slide left to "
                "fill the gap. The source WAV stays on disk; "
                "only the clip entry is dropped.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if choice != QMessageBox.StandardButton.Yes:
                return
        clips = (
            getattr(self._group, "audio_clips", []) or [])
        deleted_start = float(
            getattr(clip, "start_time_seconds", 0.0) or 0.0)
        deleted_eff = self._clip_kept_seconds(clip)
        new_clips = []
        for c in clips:
            if c.id == clip.id:
                continue
            c_start = float(
                getattr(c, "start_time_seconds", 0.0) or 0.0)
            # Strict > so a sibling clip that happened to share
            # the deleted clip's exact start (rare, but
            # possible when the writer dragged two there) stays
            # put rather than rewinding into negative time.
            if c_start > deleted_start:
                c.start_time_seconds = round(
                    max(0.0, c_start - deleted_eff), 3)
            new_clips.append(c)
        self._group.audio_clips = new_clips
        # Selection clean-up so the highlight doesn't dangle on
        # a clip that just disappeared.
        if hasattr(self, "_timeline"):
            try:
                self._timeline.select_audio_clip(None)
            except Exception:
                pass
        self._refresh_clip_list()
        self._recompose_overlay()

    def _on_delete_selected_clip(self) -> None:
        """Triggered by Delete / Backspace on the focused clip
        list row. Reuses ``_delete_audio_clip`` so the shift +
        confirm flow matches the right-click path."""
        if not hasattr(self, "_clip_list"):
            return
        item = self._clip_list.currentItem()
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        clip = next(
            (c for c in (
                getattr(self._group, "audio_clips", []) or [])
             if c.id == cid),
            None)
        if clip is not None:
            self._delete_audio_clip(clip)

    def _reorder_clip(
            self, from_idx: int, to_idx: int) -> None:
        """Move a clip's position in ``audio_clips`` then
        recompose. Used by the explicit Move up / Move down
        menu items; drag-to-reorder is wired separately via
        the QListWidget's rowsMoved signal."""
        clips = getattr(self._group, "audio_clips", None) or []
        if not (0 <= from_idx < len(clips)
                and 0 <= to_idx < len(clips)
                and from_idx != to_idx):
            return
        c = clips.pop(from_idx)
        clips.insert(to_idx, c)
        self._refresh_clip_list()
        self._recompose_overlay()

    def _open_clip_trim_dialog(self, clip) -> None:
        """Pop a small modal for the writer to set the clip's
        trim_in / trim_out in seconds. The dialog seeds with
        the current values and resolves the sentinel
        ``trim_out == 0`` to the source duration so the writer
        works in absolute coordinates; on apply we collapse it
        back to 0 if the writer left ``trim_out`` at the end."""
        from PyQt6.QtWidgets import (
            QDialog as _QD, QDoubleSpinBox as _DS,
            QFormLayout as _FL, QDialogButtonBox as _DBB,
            QLabel as _QL, QVBoxLayout as _VL,
        )
        full = float(
            getattr(clip, "duration_seconds", 0.0) or 0.0)
        if full <= 0:
            QMessageBox.warning(
                self, "Trim unavailable",
                "This clip has no known duration to trim "
                "against.")
            return
        current_in = max(0.0, float(
            getattr(clip, "trim_in_seconds", 0.0) or 0.0))
        current_out_raw = float(
            getattr(clip, "trim_out_seconds", 0.0) or 0.0)
        current_out = (
            current_out_raw
            if 0 < current_out_raw <= full else full)

        dlg = _QD(self)
        dlg.setWindowTitle(f"Trim — {clip.label}")
        dlg.setModal(True)
        outer = _VL(dlg)
        header = _QL(
            f"Source: <b>{Path(clip.audio_path).name}</b>"
            f"<br>Full duration: <b>{full:.3f} s</b><br>"
            "Set the in / out points; everything outside is "
            "skipped on recompose. The source file stays "
            "untouched.")
        header.setWordWrap(True)
        outer.addWidget(header)
        form = _FL()
        in_spin = _DS()
        in_spin.setRange(0.0, full)
        in_spin.setDecimals(3)
        in_spin.setSingleStep(0.05)
        in_spin.setSuffix(" s")
        in_spin.setValue(current_in)
        form.addRow("In", in_spin)
        out_spin = _DS()
        out_spin.setRange(0.0, full)
        out_spin.setDecimals(3)
        out_spin.setSingleStep(0.05)
        out_spin.setSuffix(" s")
        out_spin.setValue(current_out)
        form.addRow("Out", out_spin)
        kept_label = _QL("")
        kept_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        form.addRow("Kept", kept_label)
        outer.addLayout(form)

        def _refresh_kept():
            kept = max(0.0, out_spin.value() - in_spin.value())
            kept_label.setText(
                f"{kept:.3f} s "
                f"({100 * kept / full:.1f}% of source)")
        in_spin.valueChanged.connect(lambda _: _refresh_kept())
        out_spin.valueChanged.connect(lambda _: _refresh_kept())
        _refresh_kept()

        buttons = _DBB(
            _DBB.StandardButton.Ok
            | _DBB.StandardButton.Cancel
            | _DBB.StandardButton.Reset)
        outer.addWidget(buttons)
        reset_btn = buttons.button(
            _DBB.StandardButton.Reset)
        reset_btn.setText("↺ Reset (use full source)")
        def _reset():
            in_spin.setValue(0.0)
            out_spin.setValue(full)
        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec() != _QD.DialogCode.Accepted:
            return
        new_in = float(in_spin.value())
        new_out = float(out_spin.value())
        if new_out <= new_in + 0.01:
            QMessageBox.warning(
                self, "Empty trim",
                "Out must be at least 10 ms after In.")
            return
        clip.trim_in_seconds = round(new_in, 3)
        # Collapse "out at the end" back to the 0 sentinel so
        # future recordings of the same source don't suddenly
        # land past a hard-coded out.
        clip.trim_out_seconds = (
            0.0
            if abs(new_out - full) < 0.01
            else round(new_out, 3))
        self._refresh_clip_list()
        self._recompose_overlay()

    def _refresh_overlay_status(self) -> None:
        path_str = getattr(
            self._group, "overlay_audio_path", "") or ""
        if not path_str:
            self._overlay_status.setText("(no overlay)")
            for w in (
                    self._play_btn, self._stop_btn,
                    self._reset_btn, self._delete_btn):
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
                self._reset_btn, self._delete_btn):
            w.setEnabled(True)
        # Now-playing readout starts in sync with the current
        # red-line position so the writer doesn't see a stale
        # "▶ Take 1 0.00s" until they actually press Play.
        self._refresh_play_status()

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
        # Same treatment for the chapter prose window so it
        # doesn't outlive the editor as a dangling top-level.
        try:
            if self._prose_window is not None:
                self._prose_window.close()
                self._prose_window = None
        except Exception:
            pass
        super().closeEvent(event)
