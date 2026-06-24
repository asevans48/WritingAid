"""Slide editor dialog — arrange slides, set per-slide timings
and transitions, paste scripts + AI-suggest timings, group
slides, and preview the deck.

Built around a ``SlideDeckProject`` the host seeds from a chapter
(via ``slide_deck.build_slide_deck_from_chapter``). The dialog
mutates the project in place; on close the studio's autosave
timer flushes it to disk.

Recording moved to the group editor (see
``group_editor_dialog``). The slide editor only plays / imports
/ edits / deletes audio that's already attached to a slide; the
mic and Record button live in the group editor, which is where
the writer arranges slides on a single continuous audio track.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
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


def _concat_mp4_segments(
    segment_paths: list, output_path: Path,
) -> Tuple[bool, str]:
    """Concatenate ``segment_paths`` into ``output_path`` via
    ffmpeg's concat demuxer with re-encode.

    Re-encode (rather than stream copy) because per-group
    renders may differ in codec parameters (different audio
    sample rates from different overlays, different image
    sizes from different sources, etc.) — stream copy would
    fail or produce garbled output. The re-encode is fast
    for the typical few-MB segments a deck produces.

    Returns ``(success, message)``.
    """
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf
    if _sh.which("ffmpeg") is None:
        return (False, "ffmpeg not found on PATH.")
    if not segment_paths:
        return (False, "No segments to concat.")
    # ffmpeg concat demuxer reads a list file with one
    # ``file '...'`` line per segment. Use a temp file in
    # the output's parent so any relative path quirks resolve.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _tf.NamedTemporaryFile(
            mode="w", suffix=".txt",
            dir=str(output_path.parent),
            delete=False, encoding="utf-8") as list_file:
        for p in segment_paths:
            # Escape single quotes for the concat demuxer's
            # quoting rules.
            safe = str(Path(p).resolve()).replace("'", "'\\''")
            list_file.write(f"file '{safe}'\n")
        list_path = Path(list_file.name)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            # Re-encode video + audio with sensible defaults.
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(output_path.resolve()),
        ]
        try:
            proc = _sp.run(
                cmd, capture_output=True, text=True,
                timeout=900)
        except _sp.TimeoutExpired:
            return (False,
                    "ffmpeg concat timed out (15 min).")
        if proc.returncode != 0:
            return (False,
                    "ffmpeg concat failed. stderr (last "
                    "400):\n" + (proc.stderr or "")[-400:])
        return (True, f"Concatenated to {output_path}.")
    finally:
        try:
            list_path.unlink(missing_ok=True)
        except Exception:
            pass


class SlideEditorDialog(QDialog):
    """Editor for a SlideDeckProject."""

    # Fires when the editor (or its child group editor) mutates
    # the deck. The studio widget wires this to its
    # ``contentChanged`` and the 1.2 s debounced autosave —
    # before this signal existed, deck mutations only persisted
    # when the editor finally closed, so a long editing session
    # without a close meant no autosaves.
    deck_modified = pyqtSignal()

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
        # Use ``setWindowFlags`` (plural) to set the COMPLETE flag
        # set in one call. ``setWindowFlag`` (singular) is an
        # add/remove operation that on macOS triggers a hide →
        # re-show cycle, which is the focus-stealing path the
        # writer flagged. We set flags once at construction and
        # never touch them again after show().
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint)
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
        # Sized for a 1366x768 laptop with the dock + menu bar
        # subtracted — the old 1180x740 / 960x600 wouldn't fit
        # on common laptop screens once the OS chrome ate its
        # share, and writers complained about the three columns
        # being "smashed together". The layout below puts the
        # slide list on the left and a tabbed work surface on
        # the right so only ONE big section needs horizontal
        # room at a time.
        self.resize(1100, 680)
        self.setMinimumSize(880, 560)
        self._deck = deck
        self._working_dir = Path(deck.working_dir) if deck.working_dir else None
        if self._working_dir is None or not self._working_dir.exists():
            # Fall back to a temp dir keyed by deck id so recordings
            # still land somewhere stable across the session.
            self._working_dir = Path.home() / ".writingaid_slides" / deck.id
        self._working_dir.mkdir(parents=True, exist_ok=True)

        # Playback only — slide-level recording moved to the
        # group editor. The remaining player is what powers the
        # ▶ Play / ■ Stop buttons on existing per-slide takes
        # (imported audio, or audio recorded back when slide-
        # level recording existed).
        self._player = QMediaPlayer(self)
        self._player_audio = QAudioOutput(self)
        self._player.setAudioOutput(self._player_audio)
        # Floating preview window — lazily created on first
        # 🖥 Preview click. Held here so the slide editor can
        # push selection changes into it while it's open.
        self._preview_window = None

        self._selected_page_id: Optional[str] = None
        # Sticky "active" group: the dropdown's current value
        # persists across slide navigation. When the writer
        # navigates to an UNTAGGED slide, the active group is
        # auto-applied to that slide. When they navigate to a
        # slide that's already in a group, the active follows
        # the slide so subsequent moves continue the run.
        # Picking "(none)" clears the active so untagged slides
        # stay untagged.
        self._active_group_id: str = ""
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

        # Outer horizontal splitter — slide list on the left,
        # tabbed work surface on the right. Both panes are
        # collapsible so a writer on a small screen can fully
        # hide the list and use the tabs at full width while
        # reading prose into the mic. Default stretch favors
        # the tabs (3:1) since the per-slide form + preview
        # need most of the room.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)

        # ── Left pane: slide list only ───────────────────────────
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
        left.setMinimumWidth(180)
        splitter.addWidget(left)

        # ── Right pane: tabbed work surface ──────────────────────
        # Three tabs:
        #   * Slide     — per-slide form + audio controls + the
        #                 preview thumb (split inside the tab so
        #                 writers can still see what they're
        #                 recording).
        #   * Groups    — group combo + group actions. Lives in
        #                 its own tab because the group editor
        #                 (see ``group_editor_dialog``) is where
        #                 the real arrangement work happens; the
        #                 tab is just a launcher.
        #   * Script    — master script paste, WPM, AI Suggest.
        #                 Only used at the start of a session,
        #                 so out-of-the-way is fine.
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # ── Groups tab body ──────────────────────────────────
        # The real arrangement work happens inside the
        # interactive group editor (``group_editor_dialog``);
        # this panel is just for picking the active group,
        # adding the current slide to it, and launching the
        # editor.
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
        self._add_to_group_btn = QPushButton(
            "Add slide to selected group")
        self._add_to_group_btn.clicked.connect(
            self._on_add_to_selected_group)
        self._remove_from_group_btn = QPushButton(
            "Remove slide from group")
        self._remove_from_group_btn.setToolTip(
            "Drops the currently-selected slide from whatever "
            "group it's a member of. The slide stays in the deck "
            "and the group keeps its other slides.")
        self._remove_from_group_btn.clicked.connect(
            self._on_remove_from_group)
        self._edit_group_btn = QPushButton("🧩 Edit group…")
        self._edit_group_btn.setToolTip(
            "Open the interactive group editor: reorder slides, "
            "set per-slide durations + transitions, attach group "
            "overlay audio, and auto-fill the last slide to the "
            "overlay's duration.")
        self._edit_group_btn.clicked.connect(
            self._on_edit_group)
        group_actions.addWidget(self._new_group_btn)
        group_actions.addWidget(self._add_to_group_btn)
        group_actions.addWidget(self._remove_from_group_btn)
        group_actions.addWidget(self._edit_group_btn)
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

        # ── Slide tab body: form + script + audio ────────────
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
        # Flexible vertical sizing — the old ``setFixedHeight(140)``
        # capped this box even when the writer had room and forced
        # a scrollbar on long prose. Now it grows with the tab.
        self._script_edit.setMinimumHeight(80)
        self._script_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding)
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
        # Recording moved to the group editor — see the
        # 🧩 Groups tab → 🧩 Edit group… The slide editor only
        # plays / imports / edits / deletes audio that's
        # already attached to the slide, so it doesn't need a
        # mic picker or a record button anymore. Keeping
        # recording in just one surface also means there's only
        # one place where the writer hits the sounddevice
        # dependency, which keeps the install hint discoverable.
        recording_hint = QLabel(
            "🎤 To <b>record</b>, open the group editor: "
            "<b>🧩 Groups → 🧩 Edit group…</b> "
            "Recording lives there because each group plays "
            "one continuous audio track under its slides."
        )
        recording_hint.setWordWrap(True)
        recording_hint.setStyleSheet(
            "color: #475569; font-size: 11px; "
            "padding: 4px 6px; background: #f1f5f9; "
            "border: 1px solid #cbd5e1; border-radius: 4px;")
        av.addWidget(recording_hint)
        rec_row = QHBoxLayout()
        self._import_audio_btn = QPushButton(
            "📥 Import audio…")
        self._import_audio_btn.setToolTip(
            "Attach a pre-recorded audio file to this slide.")
        self._import_audio_btn.clicked.connect(
            self._on_import_audio)
        rec_row.addWidget(self._import_audio_btn)
        # Play / Pause is one button that toggles based on the
        # player's actual state. Restart rewinds to 0 and plays.
        self._play_audio_btn = QPushButton("▶ Play")
        self._play_audio_btn.setToolTip(
            "Play the slide's audio. While playing, this button "
            "shows '⏸ Pause' to pause without losing position.")
        self._play_audio_btn.clicked.connect(
            self._on_play_or_pause_audio)
        rec_row.addWidget(self._play_audio_btn)
        self._replay_audio_btn = QPushButton("⟲ Replay")
        self._replay_audio_btn.setToolTip(
            "Rewind to the start and play from the top.")
        self._replay_audio_btn.clicked.connect(
            self._on_replay_audio)
        rec_row.addWidget(self._replay_audio_btn)
        self._stop_audio_btn = QPushButton("■ Stop")
        self._stop_audio_btn.clicked.connect(self._on_stop_audio)
        rec_row.addWidget(self._stop_audio_btn)
        self._edit_audio_btn = QPushButton("✏️ Edit…")
        self._edit_audio_btn.setToolTip(
            "Trim, reduce noise, adjust gain, or normalize the "
            "slide's audio. Replace the source or save as a new "
            "file.")
        self._edit_audio_btn.clicked.connect(self._on_edit_audio)
        rec_row.addWidget(self._edit_audio_btn)
        self._clear_audio_btn = QPushButton("🗑 Delete")
        self._clear_audio_btn.setToolTip(
            "Detach this slide's audio. Optionally delete the "
            "underlying WAV file from disk too.")
        self._clear_audio_btn.clicked.connect(self._on_clear_audio)
        rec_row.addWidget(self._clear_audio_btn)
        rec_row.addStretch()
        av.addLayout(rec_row)
        form.addRow(audio_box)

        # Slide tab assembly: form fills the whole tab. The
        # preview used to live here as a right-pane splitter,
        # but on a 1366x768 laptop the form ate so much space
        # that the preview was reduced to a thumbnail. Pop-out
        # window now (see ``slide_preview_window``).
        slide_tab = QWidget()
        slide_tab_v = QVBoxLayout(slide_tab)
        slide_tab_v.setContentsMargins(0, 0, 0, 0)
        # Top action row: Preview pop-out + status hint.
        preview_row = QHBoxLayout()
        self._open_preview_btn = QPushButton(
            "🖥 Preview…")
        self._open_preview_btn.setToolTip(
            "Open a floating preview window. Hit Play in the "
            "window to run through the deck — each slide stays "
            "on for its duration and group-overlay audio plays "
            "in sync.")
        self._open_preview_btn.clicked.connect(
            self._on_open_preview)
        preview_row.addWidget(self._open_preview_btn)
        self._preview_hint = QLabel(
            "Opens in a separate window — park it anywhere.")
        self._preview_hint.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        preview_row.addWidget(self._preview_hint)
        preview_row.addStretch()
        slide_tab_v.addLayout(preview_row)
        # Scrollable form: form + script + audio controls.
        slide_form_scroll = QScrollArea()
        slide_form_scroll.setWidgetResizable(True)
        slide_form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        slide_form_inner = QWidget()
        slide_form_v = QVBoxLayout(slide_form_inner)
        slide_form_v.setContentsMargins(0, 0, 0, 0)
        slide_form_v.addWidget(slide_box)
        slide_form_v.addStretch()
        slide_form_scroll.setWidget(slide_form_inner)
        slide_tab_v.addWidget(slide_form_scroll, stretch=1)

        # ── Master script tab body ───────────────────────────
        master_box = QGroupBox(
            "Master script (paste, then ✨ Suggest)")
        mv = QVBoxLayout(master_box)
        # "Read chapter prose" button — opens a floating non-modal
        # window so the writer can scroll prose while reading
        # along into the mic. Hidden when no chapter provider was
        # wired in (e.g. dialog used standalone in a test).
        prose_row = QHBoxLayout()
        self._read_prose_btn = QPushButton(
            "📖 Read chapter prose…")
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
        # Flex vertically — the master script tab is mostly
        # this box; capping it at 140 px wasted the rest of
        # the surface on whitespace.
        self._master_script_edit.setMinimumHeight(140)
        self._master_script_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding)
        mv.addWidget(self._master_script_edit, stretch=1)
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

        # Tab wrappers (each tab gets its own QWidget so it can
        # set its own margins without bleeding into the group
        # box layouts).
        groups_tab = QWidget()
        groups_tab_v = QVBoxLayout(groups_tab)
        groups_tab_v.setContentsMargins(6, 6, 6, 6)
        groups_tab_v.addWidget(group_box)
        groups_tab_v.addStretch()

        script_tab = QWidget()
        script_tab_v = QVBoxLayout(script_tab)
        script_tab_v.setContentsMargins(6, 6, 6, 6)
        script_tab_v.addWidget(master_box)

        self._tabs.addTab(slide_tab, "🎞 Slide")
        self._tabs.addTab(groups_tab, "🧩 Groups")
        self._tabs.addTab(script_tab, "📝 Master script")
        splitter.addWidget(self._tabs)
        # Tabs claim ~3x the room of the slide list — the list
        # is just a navigator, the tabs are the workspace.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, stretch=1)

        # Slim status bar — used by playback / export progress
        # messages. Used to live in the (now removed) preview
        # pane; keeping a single line at the dialog bottom is
        # cheap and survives across tab switches.
        self._status_label = QLabel("Idle.")
        self._status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px; padding: 2px 4px;")
        outer.addWidget(self._status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        # Two-format export — writers asked for both:
        #  * MP4 = stitched silent video with audio mux for
        #          handing to colleagues who just want to watch.
        #  * PPTX = editable deck with per-slide images + audio
        #           (auto-plays on slide entry) + auto-advance
        #           timings for further editing in PowerPoint /
        #           Keynote / Slides.
        # 🎬 Preview deck — same render path as Export MP4 but
        # to a temp file in working_dir/previews/, then opens
        # in a floating playback window. Lets writers spot-check
        # what the full deck (every group, every slide, every
        # group-overlay audio + transition) plays like without
        # picking a save destination first.
        self._preview_deck_btn = QPushButton("🎬 Preview deck")
        self._preview_deck_btn.setToolTip(
            "Compile every group's slides + audio overlays + "
            "transitions into a temporary MP4 and play it in "
            "a floating window. Same render path as Export "
            "MP4 — what you see here is what ships.")
        self._preview_deck_btn.clicked.connect(
            self._on_preview_deck_clicked)
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
            self._preview_deck_btn,
            QDialogButtonBox.ButtonRole.ActionRole)
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
            self._script_edit, self._import_audio_btn,
            self._play_audio_btn, self._stop_audio_btn,
            self._clear_audio_btn,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Slide list
    # ------------------------------------------------------------------
    def _refresh_slides_text_only(self) -> None:
        """Refresh each list row's label without recreating the
        items — preserves selection without re-firing
        ``itemSelectionChanged`` (which would re-enter the page-
        load handler we may already be inside)."""
        for i, page in enumerate(self._deck.pages, start=1):
            if i - 1 >= self._slide_list.count():
                break
            item = self._slide_list.item(i - 1)
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
            item.setText(
                f"{i}. {page.label or 'Slide'}{group_mark}\n"
                f"   {page.duration_seconds:.2f}s"
                f"{audio_mark}{lock_mark}")

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
            self._sync_preview_window_selection(None)

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
        self._sync_preview_window_selection(page.id)
        # Sticky group picker: the dropdown shows the writer's
        # last-chosen group as the destination for the next
        # "Add slide to selected group" click — it does NOT
        # follow the current slide's existing tag and never
        # auto-tags anything. The slide's actual group (if any)
        # is shown on its list-row label. Navigating between
        # slides leaves the dropdown untouched so the writer can
        # keep adding a run of slides to the same group with one
        # button click each.

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

    def _on_open_preview(self) -> None:
        """Open the floating preview window (or focus it if
        already open). The window is non-modal; the writer can
        keep editing while it plays through the deck.

        We reuse a single instance so the writer doesn't end up
        with a stack of preview windows after clicking the
        button several times.
        """
        from src.ui.video_studio.slide_preview_window import (
            SlidePreviewWindow)
        if (self._preview_window is None
                or not self._preview_window.isVisible()):
            self._preview_window = SlidePreviewWindow(
                self._deck,
                initial_slide_id=self._selected_page_id)
            self._preview_window.show()
        else:
            # Already open — just refresh the deck snapshot
            # (it might have changed since open) and bring it
            # to the front.
            self._preview_window.set_deck(self._deck)
            self._preview_window.set_current(
                self._selected_page_id)
            self._preview_window.raise_()
            self._preview_window.activateWindow()

    def _sync_preview_window_selection(
            self, slide_id: Optional[str]) -> None:
        """Push a slide-list selection change into the preview
        window when one is open. No-op otherwise — opening the
        window picks up the current selection in
        ``_on_open_preview``."""
        if (self._preview_window is not None
                and self._preview_window.isVisible()):
            try:
                self._preview_window.set_current(slide_id)
            except Exception as e:
                print(
                    f"[slide_editor] preview sync failed: {e}")

    def refresh_after_external_change(self) -> None:
        """Public entry point the studio can call after it
        mutates this editor's live ``deck`` from the outside —
        e.g. when the writer changes an action's favorite
        image in the scene editor and the studio rewrites
        affected ``SlidePage.image_path`` values.

        Three layers to refresh:
          1. The slide LIST — text is regenerated so any
             label / duration changes show up immediately.
          2. The preview WINDOW (when open) — re-call
             ``set_current`` so the popup re-reads the
             current slide's image_path from disk and the
             writer sees the new image. ``QPixmap`` doesn't
             cache by path so a re-load picks up the new
             file contents.
          3. The selection state — if the writer was on a
             page that got reassigned, the selection might
             still point at it but the image changed; the
             ``_sync_preview_window_selection`` call handles
             the visual swap.
        """
        try:
            self._refresh_slides()
        except Exception as exc:
            print(
                f"[slide_editor] external-refresh list "
                f"failed: {exc}")
        try:
            self._sync_preview_window_selection(
                self._selected_page_id)
        except Exception as exc:
            print(
                f"[slide_editor] external-refresh preview "
                f"failed: {exc}")

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

    def _on_play_or_pause_audio(self) -> None:
        """Toggle between play, pause, and resume.

        When nothing's playing yet, this loads the current slide's
        audio and starts. When already playing, it pauses without
        losing the position. When paused, it resumes from the same
        spot — the "pause and replay" flow the writer asked for.
        """
        from PyQt6.QtMultimedia import QMediaPlayer
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_audio_btn.setText("▶ Resume")
            self._status_label.setText("Paused.")
            return
        if state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
            self._play_audio_btn.setText("⏸ Pause")
            self._status_label.setText("Playing.")
            return
        # Stopped — load the slide's audio and start fresh.
        page = self._selected_page()
        if page is None or not page.audio_path:
            return
        p = Path(page.audio_path)
        if not p.exists():
            return
        self._player.setSource(
            QUrl.fromLocalFile(str(p.resolve())))
        self._player.play()
        self._play_audio_btn.setText("⏸ Pause")
        self._status_label.setText(
            f"Playing {p.name}…")

    def _on_replay_audio(self) -> None:
        """Rewind to position 0 and play. Works whether currently
        playing, paused, or stopped."""
        page = self._selected_page()
        if page is None or not page.audio_path:
            return
        p = Path(page.audio_path)
        if not p.exists():
            return
        # Re-set the source so the player rewinds cleanly even
        # when ``stop`` + ``play`` had race issues on some Qt
        # builds.
        self._player.stop()
        self._player.setSource(
            QUrl.fromLocalFile(str(p.resolve())))
        self._player.setPosition(0)
        self._player.play()
        self._play_audio_btn.setText("⏸ Pause")
        self._status_label.setText(
            f"Replaying {p.name} from start.")

    def _on_stop_audio(self) -> None:
        self._player.stop()
        self._play_audio_btn.setText("▶ Play")
        self._status_label.setText("Stopped.")

    def _on_edit_audio(self) -> None:
        """Open the audio editor on the current slide's audio
        file. The editor mutates the file in place (or writes a
        new one) and calls back with the new path + duration."""
        page = self._selected_page()
        if page is None or not page.audio_path:
            QMessageBox.information(
                self, "No audio",
                "Record or import audio for this slide first.")
            return
        path = Path(page.audio_path)
        if not path.exists():
            QMessageBox.warning(
                self, "Audio missing",
                f"The slide's audio file is gone:\n{path}")
            return
        from src.ui.video_studio.audio_editor_dialog import (
            AudioEditorDialog)
        def _on_applied(new_path: Path, new_duration: float):
            page.audio_path = str(new_path)
            page.audio_duration_seconds = float(new_duration)
            page.updated_at = datetime.now()
            self._refresh_slides()
            self._refresh_audio_status()
        self._audio_editor = AudioEditorDialog(
            source_path=path,
            on_applied=_on_applied,
            title=f"Edit audio — {page.label or 'slide'}",
            parent=self)
        self._audio_editor.show()

    def _on_clear_audio(self) -> None:
        """Detach the slide's audio. Offer to also delete the
        underlying WAV file — useful when a writer recorded a
        dud and wants the file gone too, not just unlinked from
        the slide."""
        page = self._selected_page()
        if page is None:
            return
        path = (
            Path(page.audio_path)
            if page.audio_path else None)
        # Stop playback first so Windows lets us delete.
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        if path is not None and path.exists():
            choice = QMessageBox.question(
                self, "Delete audio",
                f"Detach this slide's audio?\n\nFile: {path}\n\n"
                "YES = also delete the file from disk.\n"
                "NO = only detach (file stays).",
                (QMessageBox.StandardButton.Yes
                 | QMessageBox.StandardButton.No
                 | QMessageBox.StandardButton.Cancel))
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Yes:
                try:
                    path.unlink()
                except Exception as e:
                    QMessageBox.warning(
                        self, "Delete failed",
                        f"Could not delete file:\n{e}")
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
        # Rebuild the combo items, but DO NOT change the writer's
        # sticky pick. The combo represents the destination for
        # the next "Add slide to selected group" click — it
        # follows ``_active_group_id`` rather than the current
        # slide's existing group. The slide's actual group (if
        # any) shows up on its list-row label.
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem("(none)", "")
        for g in self._deck.groups:
            self._group_combo.addItem(g.name or g.id, g.id)
        idx = self._group_combo.findData(
            self._active_group_id or "")
        self._group_combo.setCurrentIndex(
            idx if idx >= 0 else 0)
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
        # The combo is a pure destination picker now — picking
        # a group only updates the sticky ``_active_group_id``
        # and refreshes the target-time spin. No slide is
        # modified until the writer explicitly clicks
        # "Add slide to selected group".
        self._active_group_id = (
            self._group_combo.currentData() or "")
        self._refresh_group_target_spin()

    def _assign_page_to_group(
        self, page, new_gid: Optional[str],
    ) -> None:
        """Move ``page`` from its current group (if any) to
        ``new_gid``. Idempotent on no-ops, safe when ``new_gid``
        is None (drops the slide from its group)."""
        if new_gid == "":
            new_gid = None
        if page.group_id == new_gid:
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

    def _on_new_group(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New slide group", "Group name:")
        if not ok or not name.strip():
            return
        g = SlideGroup(name=name.strip())
        self._deck.groups.append(g)
        # Make the new group the sticky destination so the next
        # "Add slide to selected group" click drops into it. The
        # combo selection change updates ``_active_group_id`` via
        # the standard signal handler — no slide is touched yet.
        self._refresh_groups()
        idx = self._group_combo.findData(g.id)
        if idx >= 0:
            self._group_combo.setCurrentIndex(idx)

    def _on_add_to_selected_group(self) -> None:
        gid = self._group_combo.currentData()
        page = self._selected_page()
        if not gid or page is None:
            return
        self._assign_page_to_group(page, gid)
        self._active_group_id = gid
        self._refresh_slides()

    def _on_remove_from_group(self) -> None:
        """Drop the current slide from its group, if any. The
        sticky destination in the dropdown stays where it is so
        the writer can re-add the slide somewhere else."""
        page = self._selected_page()
        if page is None or not page.group_id:
            return
        self._assign_page_to_group(page, None)
        self._refresh_slides()

    def _on_edit_group(self) -> None:
        """Open the interactive GroupEditorDialog on the
        currently-selected group. Reflect any structural changes
        (reordered slides, removed members, new overlay audio)
        back into the deck list when the writer closes it."""
        gid = self._group_combo.currentData()
        if not gid:
            QMessageBox.information(
                self, "Pick a group",
                "Select a group in the dropdown first, then click "
                "Edit group.")
            return
        g = next(
            (gg for gg in self._deck.groups if gg.id == gid),
            None)
        if g is None:
            return
        from src.ui.video_studio.group_editor_dialog import (
            GroupEditorDialog)
        # The group editor owns its own mic picker (recording
        # lives there now). Forward the same chapter-prose
        # plumbing the slide editor uses so the group editor's
        # 📖 Read chapter prose button can pop the same
        # floating ChapterProseWindow.
        dlg = GroupEditorDialog(
            self._deck, g,
            chapters_provider=self._chapters_provider,
            save_chapter_text=self._save_chapter_text_cb,
            open_in_writer=self._open_in_writer_cb)
        dlg.finished.connect(
            lambda *_a: self._after_group_edit())
        # Forward every group-editor mutation up to the studio
        # widget's autosave path. Without this, edits made
        # while the group editor is open would only persist when
        # the SLIDE editor closes (its ``finished`` emit is
        # what currently triggers the studio's autosave) —
        # writers reported that closing the group editor without
        # also closing the slide editor lost in-flight edits on
        # crash / quit.
        dlg.deck_modified.connect(self.deck_modified)
        dlg.show()
        dlg.raise_()

    def _after_group_edit(self) -> None:
        self._refresh_slides()
        self._refresh_groups()
        # Final emit on close — covers anything that might have
        # mutated state without going through a handler that
        # already emitted (defensive belt + suspenders).
        self.deck_modified.emit()

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
    def _on_preview_deck_clicked(self) -> None:
        """Render each group separately (via
        ``render_group_to_mp4`` — same path the group editor's
        preview uses), then concatenate the per-group MP4s
        into a single deck preview.

        The earlier "flatten + single stitcher pass" approach
        was producing weird audio behavior (writers reported
        "first group loops mid-way then cuts off"). The
        single-pass stitcher mixes ALL audio across the entire
        deck via amix, and per-clip ``adelay`` offsets must
        cumulatively line up with the visual segments — too
        many edge cases for nested groups + transitions.

        Concat-of-per-group-MP4s is bulletproof: each segment
        is independently rendered + verified, then ffmpeg's
        concat demuxer (no re-encode of streams that match)
        joins them. What the writer sees in the deck preview
        for any group EQUALS what they see when they preview
        that group alone.
        """
        if not self._deck.pages:
            QMessageBox.information(
                self, "Nothing to preview",
                "Add slides to the deck first.")
            return
        from src.video_studio.slide_deck import (
            render_group_to_mp4)
        # Walk deck.pages in writer order; emit each group
        # exactly once (the first time we hit any of its
        # members). Orphan slides become a one-slide synthetic
        # group rendered the same way.
        groups_by_id = {
            g.id: g
            for g in (getattr(self._deck, "groups", []) or [])
        }
        ordered_groups: list = []  # list of (group_or_None,
        #                                    placed_or_orphan_pages)
        seen_group_ids: set = set()
        orphan_pages: list = []
        for page in self._deck.pages:
            gid = getattr(page, "group_id", None)
            if not gid or gid not in groups_by_id:
                orphan_pages.append(page)
                continue
            if gid in seen_group_ids:
                continue
            seen_group_ids.add(gid)
            ordered_groups.append((groups_by_id[gid], None))
        if orphan_pages:
            # Orphans appear at the END after every group, in
            # their deck.pages order. (We could interleave by
            # original deck position too, but writers seem to
            # think of orphans as "extras" so trailing them is
            # the least surprising default.)
            ordered_groups.append((None, orphan_pages))
        if not ordered_groups:
            QMessageBox.information(
                self, "Nothing to preview",
                "No groups or slides to render.")
            return
        # Render each group / orphan batch to its own MP4.
        from datetime import datetime as _dt
        out_dir = self._working_dir / "deck_previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        segments_dir = out_dir / f"_segments_{stamp}"
        segments_dir.mkdir(parents=True, exist_ok=True)
        segment_paths: list = []
        self._preview_deck_btn.setEnabled(False)
        self._preview_deck_btn.setText("Rendering…")
        try:
            for i, (group, orphans) in enumerate(
                    ordered_groups):
                seg_path = segments_dir / f"seg_{i:03d}.mp4"
                if group is not None:
                    ok, msg = render_group_to_mp4(
                        self._deck, group, seg_path)
                    if not ok:
                        # Empty / broken groups don't kill the
                        # preview — skip them. Writers see the
                        # message in the dialog at the end if
                        # nothing rendered.
                        print(
                            f"[deck preview] skipping group "
                            f"'{group.name}': {msg}")
                        continue
                else:
                    # Orphan batch — render as a single
                    # synthetic deck. No overlay; each
                    # slide's own audio (if any) plays.
                    from src.video_studio.models import (
                        SlideDeckProject as _SDP)
                    synth = _SDP(
                        id=f"orphans_{self._deck.id}",
                        name="Orphan slides",
                        working_dir=self._deck.working_dir,
                        pages=[
                            p.model_copy(deep=False)
                            for p in orphans],
                    )
                    ok, msg = stitch_slide_deck_to_mp4(
                        synth, seg_path)
                    if not ok:
                        print(
                            f"[deck preview] orphan batch "
                            f"failed: {msg}")
                        continue
                segment_paths.append(seg_path)
            if not segment_paths:
                QMessageBox.warning(
                    self, "Preview render failed",
                    "Every group failed to render — nothing "
                    "to play.")
                return
            # Concat the segments via ffmpeg concat demuxer.
            # Re-encode video + audio so segment-to-segment
            # parameter mismatches (different codecs, sample
            # rates, color spaces) don't poison the concat —
            # the cost is a small re-encode but the writer
            # gets a guaranteed-playable file.
            out_path = (
                out_dir / f"deck_preview_{stamp}.mp4")
            ok, msg = _concat_mp4_segments(
                segment_paths, out_path)
            if not ok:
                QMessageBox.warning(
                    self, "Preview concat failed", msg)
                return
        finally:
            self._preview_deck_btn.setEnabled(True)
            self._preview_deck_btn.setText(
                "🎬 Preview deck")
            # Clean up the segment files — they're already
            # baked into out_path.
            try:
                for p in segment_paths:
                    p.unlink(missing_ok=True)
                segments_dir.rmdir()
            except Exception:
                pass
        if not ok:
            QMessageBox.warning(
                self, "Preview render failed", msg)
            return
        from src.ui.video_studio.group_preview_window import (
            GroupPreviewWindow)
        # Reuse the playback widget the group preview uses —
        # it's a generic MP4 player. Hold a strong reference
        # so Qt doesn't GC the window the moment this method
        # returns, and close any prior preview so we don't
        # accumulate windows.
        try:
            if (getattr(self, "_deck_preview_window", None)
                    is not None):
                self._deck_preview_window.close()
        except Exception:
            pass
        self._deck_preview_window = GroupPreviewWindow(
            out_path,
            group_name=self._deck.name or "deck")
        # Override the window title since it's a deck preview
        # not a single-group preview.
        self._deck_preview_window.setWindowTitle(
            f"🎬 Deck preview — "
            f"{self._deck.name or 'deck'}")
        self._deck_preview_window.show()

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
        self._status_label.setText("Rendering MP4…")
        ok, msg = stitch_slide_deck_to_mp4(
            self._deck, Path(out_str))
        if not ok:
            QMessageBox.warning(
                self, "Export failed", msg)
            return
        self._status_label.setText(
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
        self._status_label.setText(
            "Composing PowerPoint…")
        ok, msg, skipped = export_slide_deck_to_pptx(
            self._deck, Path(out_str))
        if not ok:
            QMessageBox.warning(
                self, "Export failed", msg)
            self._status_label.setText("")
            return
        self._status_label.setText(
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
            if self._prose_window is not None:
                self._prose_window.close()
                self._prose_window = None
        except Exception:
            pass
        try:
            if self._preview_window is not None:
                self._preview_window.close()
                self._preview_window = None
        except Exception:
            pass
        super().closeEvent(event)
