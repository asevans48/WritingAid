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
    segment_paths: list,
    output_path: Path,
    *,
    transitions: Optional[list] = None,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    sample_rate: int = 48000,
) -> Tuple[bool, str]:
    """Stitch ``segment_paths`` into ``output_path`` using
    ffmpeg's ``filter_complex`` ``concat`` filter — NOT the
    concat demuxer.

    Why filter_complex: the concat demuxer requires every
    input to share IDENTICAL stream params (codec, sample
    rate, channel layout, pixel format, timebase). When even
    one segment differs — and per-group renders often DO
    differ because different overlays were composed at
    different rates and channel counts — the demuxer either
    refuses or produces garbled output (audio looping,
    visual cutoffs, the "preview is a mess" the writer
    flagged).

    The filter_complex path normalizes every input through
    ``scale``/``setsar``/``fps``/``aformat`` first so the
    concat filter sees a uniform stream, then re-encodes once
    on the way out. Slightly more expensive but bulletproof.

    ``transitions`` (optional) is a list of ``(kind, seconds)``
    tuples — one per BOUNDARY between consecutive segments
    (so ``len(transitions) == len(segments) - 1`` when set).
    Each tuple describes the cross-segment join:
      * ``("cut", 0.0)`` → hard concat (default).
      * ``("fade", N)`` → xfade for video + acrossfade for
        audio, both at the boundary, for ``N`` seconds.
    Other xfade transition names ("dissolve", "wipeleft",
    "slideleft", etc.) also work — they pass straight to
    ffmpeg.

    Returns ``(success, message)``.
    """
    import shutil as _sh
    import subprocess as _sp
    if _sh.which("ffmpeg") is None:
        return (False, "ffmpeg not found on PATH.")
    if not segment_paths:
        return (False, "No segments to concat.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(segment_paths)
    # Normalize transitions so we can index transitions[i-1]
    # for the i-th boundary safely.
    trans = list(transitions or [])
    while len(trans) < max(0, n - 1):
        trans.append(("cut", 0.0))
    # Probe each segment's duration once — we need it for the
    # xfade offset math AND so the chain knows when each
    # segment ends.
    durations: list = []
    for p in segment_paths:
        d = _ffprobe_duration(p)
        if d <= 0:
            return (False,
                    f"Could not probe duration: {p}")
        durations.append(d)
    inputs: list = []
    for p in segment_paths:
        inputs.extend(["-i", str(Path(p).resolve())])
    # A segment with no narration renders as a SILENT mp4 with no
    # audio stream at all (see ``stitch_slide_deck_to_mp4``). The
    # concat / xfade filters below reference ``[i:a]`` for every
    # input, so a single audio-less segment used to abort the whole
    # export ("Stream specifier ':a' matches no streams") — the
    # deck came out with no file, or the writer's audio-bearing
    # groups lost their sound. Probe each segment and synthesize a
    # matching-length silent track (via ``anullsrc``) for the ones
    # that have no audio, so the graph always sees a uniform
    # audio+video pair per input and audio-bearing groups keep
    # their composed narration in the final render.
    seg_has_audio: list = [
        _ffprobe_has_audio(p) for p in segment_paths]
    # Extra lavfi silence inputs, appended after the real segment
    # inputs. ``silent_input_idx[seg]`` is the ffmpeg input index
    # that carries that segment's synthesized silence.
    silent_input_idx: dict = {}
    next_input = n
    for i, hasa in enumerate(seg_has_audio):
        if not hasa:
            inputs.extend([
                "-f", "lavfi",
                "-t", f"{durations[i]:.3f}",
                "-i",
                (f"anullsrc=channel_layout=stereo:"
                 f"sample_rate={sample_rate}")])
            silent_input_idx[i] = next_input
            next_input += 1
    # Per-input normalize chains. Every input gets scale +
    # pad + setsar + fps for video, aformat + asetnsamples
    # for audio, so the concat / xfade filters see a uniform
    # stream and don't choke on per-segment differences.
    filter_parts: list = []
    scale_pad = (
        f"scale={width}:{height}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,format=yuv420p,fps={fps}")
    aformat = (
        f"aformat=sample_fmts=fltp:"
        f"sample_rates={sample_rate}:channel_layouts=stereo,"
        "asetpts=N/SR/TB")
    for i in range(n):
        filter_parts.append(f"[{i}:v]{scale_pad}[v{i}]")
        a_src = (
            f"[{i}:a]" if seg_has_audio[i]
            else f"[{silent_input_idx[i]}:a]")
        filter_parts.append(f"{a_src}{aformat}[a{i}]")
    # Decide concat-vs-xfade per boundary. ``cumulative`` is
    # the running output time so each xfade offset lands at
    # the right moment in the composed timeline.
    cumulative = durations[0]
    last_v = "v0"
    last_a = "a0"
    for i in range(1, n):
        kind, secs = trans[i - 1]
        kind = (kind or "cut").lower()
        secs = max(0.0, float(secs or 0.0))
        # Cap the transition at the shorter of the two
        # neighbor durations so ffmpeg doesn't complain about
        # an offset past the end of either input.
        max_secs = max(0.0, min(
            durations[i - 1], durations[i]) - 0.05)
        secs = min(secs, max_secs)
        if kind == "cut" or secs <= 0:
            # Hard concat between the current chain and the
            # next segment.
            new_v = f"vx{i}"
            new_a = f"ax{i}"
            filter_parts.append(
                f"[{last_v}][{last_a}][v{i}][a{i}]"
                f"concat=n=2:v=1:a=1[{new_v}][{new_a}]")
            last_v, last_a = new_v, new_a
            cumulative += durations[i]
        else:
            # xfade for video + acrossfade for audio. The
            # xfade ``offset`` is the timestamp in the LEFT
            # input where the crossfade STARTS — i.e. the
            # cumulative duration minus the transition
            # length. acrossfade doesn't need an offset; it
            # just blends the last ``secs`` of left with the
            # first ``secs`` of right.
            offset = max(0.0, cumulative - secs)
            new_v = f"vx{i}"
            new_a = f"ax{i}"
            filter_parts.append(
                f"[{last_v}][v{i}]xfade=transition={kind}:"
                f"duration={secs:.3f}:offset={offset:.3f}"
                f"[{new_v}]")
            filter_parts.append(
                f"[{last_a}][a{i}]acrossfade=d={secs:.3f}:"
                f"c1=tri:c2=tri[{new_a}]")
            last_v, last_a = new_v, new_a
            cumulative = cumulative + durations[i] - secs
    filter_str = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", f"[{last_v}]",
        "-map", f"[{last_a}]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps),
        # Explicit AAC-LC at a fixed rate/bitrate + stereo. QuickTime
        # is fussier than VLC/Chrome about audio: it silently plays
        # NO audio when the profile is unusual or the channel layout
        # metadata is missing. Pin the low-complexity profile and a
        # concrete bitrate so the track is one QuickTime always
        # decodes.
        "-c:a", "aac", "-profile:a", "aac_low",
        "-ar", str(sample_rate), "-b:a", "192k",
        "-ac", "2",
        # +faststart moves the moov atom to the front so players
        # can start immediately instead of after a full scan.
        "-movflags", "+faststart",
        str(output_path.resolve()),
    ]
    try:
        proc = _sp.run(
            cmd, capture_output=True, text=True, timeout=900)
    except _sp.TimeoutExpired:
        return (False, "ffmpeg concat timed out (15 min).")
    if proc.returncode != 0:
        return (False,
                "ffmpeg filter_complex concat failed. "
                "stderr (last 600):\n"
                + (proc.stderr or "")[-600:])
    return (True, f"Concatenated to {output_path}.")


def _mix_background_under_deck(
    video_path: Path,
    background_path: str,
    *,
    gain_db: float = -12.0,
    loop: bool = True,
    sample_rate: int = 48000,
) -> Tuple[bool, str]:
    """Mix a background bed UNDER an already-rendered deck video,
    IN PLACE. The bed is looped (when ``loop``) and trimmed to the
    deck's exact length, ducked by ``gain_db``, and summed with the
    deck's existing narration — so the voice stays on top and the
    music carries underneath the whole runtime. Rewrites
    ``video_path`` on success."""
    import subprocess as _sp
    if not (background_path and Path(background_path).exists()):
        return (False, "background file missing")
    dur = _ffprobe_duration(video_path)
    if dur <= 0:
        return (False, "could not probe deck duration")
    tmp = video_path.with_name(video_path.stem + "_bgmix.mp4")
    loop_args = ["-stream_loop", "-1"] if loop else []
    # Loop → trim to deck length → duck → stereo. Sum with the
    # deck audio (duration=longest, but the bed is already capped
    # to the deck length so the result is exactly the deck length).
    filt = (
        f"[1:a]volume={gain_db:.2f}dB,"
        f"atrim=0:{dur:.3f},asetpts=N/SR/TB,"
        f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:"
        f"channel_layouts=stereo[bg];"
        f"[0:a]aformat=sample_fmts=fltp:sample_rates={sample_rate}:"
        f"channel_layouts=stereo[deck];"
        f"[deck][bg]amix=inputs=2:duration=longest:"
        f"normalize=0[mix]")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        *loop_args,
        "-i", str(Path(background_path).resolve()),
        "-filter_complex", filt,
        "-map", "0:v:0", "-map", "[mix]",
        "-c:v", "copy",
        "-c:a", "aac", "-profile:a", "aac_low",
        "-ar", str(sample_rate), "-b:a", "192k", "-ac", "2",
        "-t", f"{dur:.3f}",
        "-movflags", "+faststart",
        str(tmp.resolve()),
    ]
    try:
        proc = _sp.run(
            cmd, capture_output=True, text=True, timeout=900)
    except _sp.TimeoutExpired:
        return (False, "background mix timed out")
    if proc.returncode != 0:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return (False, (proc.stderr or "")[-300:])
    try:
        tmp.replace(video_path)
    except Exception as e:
        return (False, f"could not finalize: {e}")
    return (True, "")


def _ffprobe_has_audio(path: Path) -> bool:
    """Return True when ``path`` has at least one audio stream.
    Returns False on any probe failure — the concat path then
    synthesizes silence for that segment, which is the safe
    default (never abort the whole export over a probe hiccup)."""
    import shutil as _sh
    import subprocess as _sp
    if _sh.which("ffprobe") is None:
        return False
    try:
        proc = _sp.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-of", "csv=p=0",
             str(Path(path).resolve())],
            capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return False
        return "audio" in (proc.stdout or "")
    except Exception:
        return False


def _ffprobe_duration(path: Path) -> float:
    """Read a file's duration in seconds via ffprobe.
    Returns 0.0 on any failure."""
    import shutil as _sh
    import subprocess as _sp
    if _sh.which("ffprobe") is None:
        return 0.0
    try:
        proc = _sp.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(Path(path).resolve())],
            capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return 0.0
        return float((proc.stdout or "0").strip() or 0.0)
    except Exception:
        return 0.0


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
        scenes_provider=None,
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
        # Pull-on-demand callback that returns the live list
        # of scenes. The group editor's "🔄 Sync favorites
        # from actions" button uses it to find every action's
        # favorite image across the whole project.
        self._scenes_provider = scenes_provider
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
        self._refresh_bg_status()

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

        # ── Stitch Order panel ───────────────────────────────
        # Visible record of how the deck preview / export will
        # assemble the groups: each group renders via the
        # SAME path the group editor's preview uses (so the
        # writer's "this group looks right" carries forward),
        # then this list controls the order and the
        # transition INTO each group from the previous one.
        # Default transition is "cut" so existing decks behave
        # exactly like before — new field, safe default.
        stitch_box = QGroupBox(
            "Deck stitch order (groups → preview / export)")
        stitch_v = QVBoxLayout(stitch_box)
        stitch_v.addWidget(QLabel(
            "Reorder groups with ↑ / ↓. The transition picker "
            "controls what plays at the join from the previous "
            "group's last frame into this group's first."))
        self._stitch_list = QListWidget()
        self._stitch_list.setMaximumHeight(140)
        self._stitch_list.itemSelectionChanged.connect(
            self._on_stitch_selection_changed)
        stitch_v.addWidget(self._stitch_list)
        stitch_row = QHBoxLayout()
        self._stitch_up_btn = QPushButton("↑ Move up")
        self._stitch_up_btn.clicked.connect(
            lambda: self._on_stitch_move(-1))
        self._stitch_down_btn = QPushButton("↓ Move down")
        self._stitch_down_btn.clicked.connect(
            lambda: self._on_stitch_move(+1))
        stitch_row.addWidget(self._stitch_up_btn)
        stitch_row.addWidget(self._stitch_down_btn)
        stitch_row.addWidget(QLabel("  Transition in:"))
        self._stitch_trans_combo = QComboBox()
        # Reuse the chapter transitions list so writers get the
        # same vocabulary across the per-slide and per-group
        # transition pickers.
        from src.video_studio.models import (
            CHAPTER_TRANSITIONS as _CT)
        for key, label in _CT:
            self._stitch_trans_combo.addItem(label, key)
        self._stitch_trans_combo.currentIndexChanged.connect(
            self._on_stitch_transition_kind_changed)
        stitch_row.addWidget(self._stitch_trans_combo)
        self._stitch_trans_secs = QDoubleSpinBox()
        self._stitch_trans_secs.setRange(0.0, 5.0)
        self._stitch_trans_secs.setDecimals(2)
        self._stitch_trans_secs.setSingleStep(0.1)
        self._stitch_trans_secs.setSuffix(" s")
        self._stitch_trans_secs.editingFinished.connect(
            self._on_stitch_transition_secs_changed)
        stitch_row.addWidget(self._stitch_trans_secs)
        stitch_row.addStretch()
        stitch_v.addLayout(stitch_row)
        group_v.addWidget(stitch_box)

        # ── Deck background bed ──────────────────────────────
        # A single track that loops (ducked) UNDER every group for
        # the whole deck — set it from any group's track, or import
        # a music/ambience file.
        bg_box = QGroupBox("Deck background music / ambience")
        bg_v = QVBoxLayout(bg_box)
        self._bg_status = QLabel()
        self._bg_status.setWordWrap(True)
        bg_v.addWidget(self._bg_status)
        bg_btn_row = QHBoxLayout()
        self._bg_from_group_btn = QPushButton(
            "🎼 Set from group track…")
        self._bg_from_group_btn.setToolTip(
            "Use a copy of one group's audio track as the deck-"
            "wide background bed. It loops under every group.")
        self._bg_from_group_btn.clicked.connect(
            self._on_bg_from_group)
        bg_btn_row.addWidget(self._bg_from_group_btn)
        self._bg_import_btn = QPushButton("📂 Import file…")
        self._bg_import_btn.setToolTip(
            "Import a music / ambience file to loop under the "
            "whole deck.")
        self._bg_import_btn.clicked.connect(self._on_bg_import)
        bg_btn_row.addWidget(self._bg_import_btn)
        self._bg_clear_btn = QPushButton("🗑 Clear")
        self._bg_clear_btn.clicked.connect(self._on_bg_clear)
        bg_btn_row.addWidget(self._bg_clear_btn)
        bg_btn_row.addStretch()
        bg_v.addLayout(bg_btn_row)
        bg_opts_row = QHBoxLayout()
        bg_opts_row.addWidget(QLabel("Level:"))
        self._bg_gain_spin = QDoubleSpinBox()
        self._bg_gain_spin.setRange(-40.0, 6.0)
        self._bg_gain_spin.setDecimals(1)
        self._bg_gain_spin.setSingleStep(1.0)
        self._bg_gain_spin.setSuffix(" dB")
        self._bg_gain_spin.setValue(
            float(getattr(self._deck, "background_gain_db", -12.0)
                  or -12.0))
        self._bg_gain_spin.setToolTip(
            "Background level relative to the narration. Negative "
            "ducks it under the voice; -12 dB is a safe default.")
        self._bg_gain_spin.valueChanged.connect(
            self._on_bg_gain_changed)
        bg_opts_row.addWidget(self._bg_gain_spin)
        self._bg_loop_check = QCheckBox("Loop to fill deck")
        self._bg_loop_check.setChecked(
            bool(getattr(self._deck, "background_loop", True)))
        self._bg_loop_check.toggled.connect(
            self._on_bg_loop_toggled)
        bg_opts_row.addWidget(self._bg_loop_check)
        bg_opts_row.addStretch()
        bg_v.addLayout(bg_opts_row)
        group_v.addWidget(bg_box)

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
        # Deck actions row — Preview deck + Export MP4 +
        # Export PowerPoint. These used to live in the dialog
        # footer next to Close; moving them here puts them
        # right under the Stitch Order panel so the writer
        # configures stitching and renders in one workspace.
        # Same button instances + handlers — only the parent
        # layout changed.
        deck_actions_row = QHBoxLayout()
        deck_actions_row.addStretch()
        self._preview_deck_btn = QPushButton("🎬 Preview deck")
        self._preview_deck_btn.setToolTip(
            "Compile every group's slides + audio overlays + "
            "transitions into a temporary MP4 and play it in "
            "a floating window. Same render path as Export "
            "MP4 — what you see here is what ships.")
        self._preview_deck_btn.clicked.connect(
            self._on_preview_deck_clicked)
        deck_actions_row.addWidget(self._preview_deck_btn)
        self._export_mp4_btn = QPushButton("🎬 Export MP4…")
        self._export_mp4_btn.clicked.connect(
            self._on_export_mp4_clicked)
        deck_actions_row.addWidget(self._export_mp4_btn)
        self._export_pptx_btn = QPushButton(
            "📊 Export PowerPoint…")
        self._export_pptx_btn.setToolTip(
            "Save as .pptx: one slide per image with the "
            "per-slide audio embedded to auto-play, and "
            "slide advance times matching the per-slide "
            "durations. No text overlays.")
        self._export_pptx_btn.clicked.connect(
            self._on_export_pptx_clicked)
        deck_actions_row.addWidget(self._export_pptx_btn)
        groups_tab_v.addLayout(deck_actions_row)
        groups_tab_v.addStretch()

        script_tab = QWidget()
        script_tab_v = QVBoxLayout(script_tab)
        script_tab_v.setContentsMargins(6, 6, 6, 6)
        script_tab_v.addWidget(master_box)

        # ── Slide tab REMOVED from the tab widget ─────────────
        # The Group editor (🧩 Edit group…) covers every per-
        # slide field the old Slide tab had — duration, lock,
        # transition, script, audio. Hiding the tab keeps the
        # writer focused on group work without losing any
        # capability. The slide_tab widget + its children stay
        # ALIVE because the slide-list selection handlers
        # (``_on_slide_selected``, ``_set_slide_panel_enabled``,
        # ``_commit_slide_fields``) still call into them.
        # Reparenting to ``self`` + hiding keeps Qt from
        # garbage-collecting the C++ widgets when the tab
        # widget no longer owns them — without this parent
        # bump the writer's first slide click crashes with
        # ``wrapped C/C++ object has been deleted``.
        slide_tab.setParent(self)
        slide_tab.hide()
        self._hidden_slide_tab = slide_tab
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

        # Footer — Close only. Preview deck + Export MP4 +
        # Export PowerPoint moved into the Groups tab so the
        # writer configures stitch order + transitions and
        # renders in one place.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
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
        self.deck_modified.emit()

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
        self.deck_modified.emit()

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
        self.deck_modified.emit()

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
        self.deck_modified.emit()

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
            self.deck_modified.emit()
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
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Master script + AI timings
    # ------------------------------------------------------------------
    def _on_wpm_changed(self, value: int) -> None:
        self._deck.wpm_estimate = int(value)
        self.deck_modified.emit()

    def _on_suggest_timings(self) -> None:
        text = self._master_script_edit.toPlainText()
        n, msg = suggest_timings_from_script(self._deck, text)
        QMessageBox.information(
            self, "Suggested timings", msg)
        self._refresh_slides()
        self.deck_modified.emit()
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
        self._refresh_stitch_list()

    def _refresh_stitch_list(self) -> None:
        """Rebuild the stitch-order list from ``deck.groups``.
        Display order follows ``deck.groups`` so the writer
        knows that's the authoritative source of truth for
        the preview / export concat. Each row's label shows
        the group name + the transition INTO it from the
        previous group (cut, fade Ns, etc.)."""
        if not hasattr(self, "_stitch_list"):
            return
        self._stitch_list.blockSignals(True)
        self._stitch_list.clear()
        for i, g in enumerate(self._deck.groups):
            kind = (
                getattr(
                    g, "inter_group_transition_in", "cut")
                or "cut")
            secs = float(
                getattr(
                    g, "inter_group_transition_seconds", 0.0)
                or 0.0)
            if i == 0:
                trans = "(first group — no incoming)"
            elif kind == "cut" or secs <= 0:
                trans = "cut"
            else:
                trans = f"{kind} {secs:.2f}s"
            self._stitch_list.addItem(
                f"{i + 1}. {g.name or g.id}  ·  {trans}")
        self._stitch_list.blockSignals(False)
        self._refresh_stitch_detail()

    def _refresh_stitch_detail(self) -> None:
        """Push the selected group's transition values into
        the picker controls (combo + secs spinner). The
        controls are disabled when the selection is the very
        first group (it has no incoming join) or there's no
        selection."""
        if not hasattr(self, "_stitch_trans_combo"):
            return
        row = self._stitch_list.currentRow()
        editable = (row > 0)
        self._stitch_trans_combo.setEnabled(editable)
        self._stitch_trans_secs.setEnabled(editable)
        if (row < 0 or row >= len(self._deck.groups)
                or not editable):
            self._stitch_trans_combo.blockSignals(True)
            self._stitch_trans_combo.setCurrentIndex(0)
            self._stitch_trans_combo.blockSignals(False)
            self._stitch_trans_secs.blockSignals(True)
            self._stitch_trans_secs.setValue(0.0)
            self._stitch_trans_secs.blockSignals(False)
            return
        g = self._deck.groups[row]
        cur_kind = (
            getattr(g, "inter_group_transition_in", "cut")
            or "cut")
        idx = self._stitch_trans_combo.findData(cur_kind)
        self._stitch_trans_combo.blockSignals(True)
        self._stitch_trans_combo.setCurrentIndex(
            idx if idx >= 0 else 0)
        self._stitch_trans_combo.blockSignals(False)
        self._stitch_trans_secs.blockSignals(True)
        self._stitch_trans_secs.setValue(float(
            getattr(g, "inter_group_transition_seconds", 0.0)
            or 0.0))
        self._stitch_trans_secs.blockSignals(False)

    def _on_stitch_selection_changed(self) -> None:
        self._refresh_stitch_detail()

    def _on_stitch_move(self, delta: int) -> None:
        """Swap the selected group with its neighbor. Updates
        ``deck.groups`` order, which is what the deck preview /
        export concat walks."""
        row = self._stitch_list.currentRow()
        new_row = row + delta
        if (row < 0 or new_row < 0
                or new_row >= len(self._deck.groups)):
            return
        groups = list(self._deck.groups)
        groups[row], groups[new_row] = (
            groups[new_row], groups[row])
        self._deck.groups = groups
        self._refresh_groups()
        self._stitch_list.setCurrentRow(new_row)
        self.deck_modified.emit()

    def _on_stitch_transition_kind_changed(
            self, _idx: int) -> None:
        row = self._stitch_list.currentRow()
        if row <= 0 or row >= len(self._deck.groups):
            return
        kind = (
            self._stitch_trans_combo.currentData() or "cut")
        self._deck.groups[row].inter_group_transition_in = (
            kind)
        self._refresh_stitch_list()
        self._stitch_list.setCurrentRow(row)
        self.deck_modified.emit()

    def _on_stitch_transition_secs_changed(self) -> None:
        row = self._stitch_list.currentRow()
        if row <= 0 or row >= len(self._deck.groups):
            return
        self._deck.groups[row].inter_group_transition_seconds = (
            float(self._stitch_trans_secs.value()))
        self._refresh_stitch_list()
        self._stitch_list.setCurrentRow(row)
        self.deck_modified.emit()

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
        self.deck_modified.emit()

    def _on_add_to_selected_group(self) -> None:
        gid = self._group_combo.currentData()
        page = self._selected_page()
        if not gid or page is None:
            return
        self._assign_page_to_group(page, gid)
        self._active_group_id = gid
        self._refresh_slides()
        self.deck_modified.emit()

    def _on_remove_from_group(self) -> None:
        """Drop the current slide from its group, if any. The
        sticky destination in the dropdown stays where it is so
        the writer can re-add the slide somewhere else."""
        page = self._selected_page()
        if page is None or not page.group_id:
            return
        self._assign_page_to_group(page, None)
        self._refresh_slides()
        self.deck_modified.emit()

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
            open_in_writer=self._open_in_writer_cb,
            scenes_provider=self._scenes_provider)
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
        self.deck_modified.emit()

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
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Deck background bed
    # ------------------------------------------------------------------
    def _refresh_bg_status(self) -> None:
        """Update the background-bed status label + control
        enabled state from the deck model."""
        if not hasattr(self, "_bg_status"):
            return
        clips = getattr(
            self._deck, "background_audio_clips", None) or []
        has_bg = bool(clips)
        if has_bg:
            src = (getattr(
                self._deck, "background_source_label", "")
                or "custom")
            dur = float(getattr(
                self._deck,
                "background_audio_duration_seconds", 0.0) or 0.0)
            dur_txt = f" · {dur:.1f}s loop" if dur > 0 else ""
            self._bg_status.setText(
                f"🎵 Background set — {src}{dur_txt}. "
                f"Loops under every group on export.")
        else:
            self._bg_status.setText(
                "No background bed. Add music / ambience that "
                "plays under the whole deck.")
        self._bg_clear_btn.setEnabled(has_bg)
        self._bg_gain_spin.setEnabled(has_bg)
        self._bg_loop_check.setEnabled(has_bg)

    def _set_deck_background_clips(
            self, clips: list, label: str) -> None:
        """Point the deck's background bed at ``clips`` (already
        model instances), clear the rendered cache so it
        recomposes, and refresh the UI."""
        self._deck.background_audio_clips = list(clips)
        self._deck.background_audio_path = ""
        self._deck.background_audio_duration_seconds = 0.0
        self._deck.background_source_label = label
        # Compose eagerly so the status shows a duration and the
        # first export doesn't stall on a cold recompose.
        try:
            from src.video_studio.slide_deck import (
                resolve_deck_background)
            resolve_deck_background(self._deck)
        except Exception:
            pass
        self._refresh_bg_status()
        self.deck_modified.emit()

    def _on_bg_from_group(self) -> None:
        """Pick a group + one of its tracks to use as the deck-
        wide background bed (a copy — the group keeps its own)."""
        from src.video_studio.slide_deck import copy_group_track
        groups = [
            g for g in (getattr(self._deck, "groups", None) or [])
            if (getattr(g, "audio_clips", None) or [])]
        if not groups:
            QMessageBox.information(
                self, "No audio",
                "No group has any audio tracks to use as a "
                "background yet.")
            return
        glabels = [(g.name or g.id) for g in groups]
        gchoice, ok = QInputDialog.getItem(
            self, "Background from group",
            "Use a track from which group?", glabels, 0, False)
        if not ok or not gchoice:
            return
        group = groups[glabels.index(gchoice)]
        # Enumerate the group's distinct track indices.
        tracks = sorted({
            int(getattr(c, "track_index", 0) or 0)
            for c in group.audio_clips})
        names = getattr(group, "track_names", None) or {}
        tlabels = [
            (names.get(t) or names.get(str(t)) or f"Track {t + 1}")
            for t in tracks]
        tchoice, ok = QInputDialog.getItem(
            self, "Background track",
            f"Which track from '{gchoice}'?", tlabels, 0, False)
        if not ok or not tchoice:
            return
        track_index = tracks[tlabels.index(tchoice)]
        # Stage onto a scratch group to reuse the deep-copy logic.
        from src.video_studio.models import SlideGroup as _SG
        scratch = _SG(name="_bg")
        copy_group_track(group, track_index, scratch, 0)
        self._set_deck_background_clips(
            scratch.audio_clips,
            f"copied from group '{gchoice}' · {tchoice}")
        QMessageBox.information(
            self, "Background set",
            "That track is now the deck's background bed. Adjust "
            "the level below; it loops under every group on "
            "export.")

    def _on_bg_import(self) -> None:
        """Import an audio file to use as the deck background."""
        from src.video_studio.models import GroupAudioClip
        picked, _ = QFileDialog.getOpenFileName(
            self, "Import background audio", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac "
            "*.opus *.aiff);;All files (*)")
        if not picked:
            return
        src = Path(picked)
        import shutil as _sh
        dest_dir = self._working_dir / "deck_background"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"bg_{stamp}{src.suffix.lower()}"
        try:
            _sh.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(
                self, "Import failed",
                f"Could not copy '{src.name}': {e}")
            return
        dur = probe_audio_duration_seconds(dest)
        clip = GroupAudioClip(
            label=src.stem,
            audio_path=str(dest),
            duration_seconds=float(dur or 0.0),
            start_time_seconds=0.0,
            track_index=0)
        self._set_deck_background_clips(
            [clip], f"imported {src.name}")

    def _on_bg_clear(self) -> None:
        if QMessageBox.question(
                self, "Clear background?",
                "Remove the deck's background bed?") != \
                QMessageBox.StandardButton.Yes:
            return
        self._deck.background_audio_clips = []
        self._deck.background_audio_path = ""
        self._deck.background_audio_duration_seconds = 0.0
        self._deck.background_source_label = ""
        self._refresh_bg_status()
        self.deck_modified.emit()

    def _on_bg_gain_changed(self, value: float) -> None:
        self._deck.background_gain_db = float(value)
        self.deck_modified.emit()

    def _on_bg_loop_toggled(self, checked: bool) -> None:
        self._deck.background_loop = bool(checked)
        self.deck_modified.emit()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _render_deck_via_groups(
        self, out_path: Path,
    ) -> Tuple[bool, str]:
        """Render the full deck into a single MP4 at ``out_path``
        by rendering EACH group separately (via
        ``render_group_to_mp4`` — same path the group editor's
        preview uses) and concatenating with inter-group
        transitions.

        Shared by the deck preview button AND the MP4 export
        button so writers see byte-for-byte the same audio +
        visuals in their exported file as they hear in
        preview. The earlier export path called
        ``stitch_slide_deck_to_mp4`` directly on ``self._deck``,
        which iterates ``deck.pages`` and only honors per-page
        ``audio_path``. In the group-editor world per-page
        audio is empty (the audio lives on the group's
        composed overlay), so exports silently lost every
        narration take. Routing both code paths through this
        helper fixes that without rewriting the stitcher.

        Returns ``(ok, message)``. The caller owns the chosen
        output location — preview uses a temp file under
        ``deck_previews/``; export uses the user-picked path
        from QFileDialog.
        """
        from src.video_studio.slide_deck import (
            render_group_to_mp4)
        # Walk ``deck.groups`` in its current order — that's
        # what the Stitch Order panel controls and what the
        # writer expects. Groups in deck.groups but with NO
        # placed pages get skipped by ``render_group_to_mp4``
        # downstream; orphan slides (no group_id) get
        # collected separately and rendered after the groups.
        groups_by_id = {
            g.id: g
            for g in (getattr(self._deck, "groups", []) or [])
        }
        ordered_groups: list = []  # (group_or_None,
        #                            placed_or_orphan_pages)
        for g in getattr(self._deck, "groups", []) or []:
            ordered_groups.append((g, None))
        orphan_pages: list = []
        for page in self._deck.pages:
            gid = getattr(page, "group_id", None)
            if not gid or gid not in groups_by_id:
                orphan_pages.append(page)
        if orphan_pages:
            ordered_groups.append((None, orphan_pages))
        if not ordered_groups:
            return (
                False, "No groups or slides to render.")
        from datetime import datetime as _dt
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        # Drop segments next to the output file so cleanup is
        # local; if out_path's parent doesn't exist yet
        # (happens when the user types a brand-new folder in
        # the Save As dialog), make it.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        segments_dir = out_path.parent / (
            f"_deck_segments_{stamp}")
        segments_dir.mkdir(parents=True, exist_ok=True)
        segment_paths: list = []
        # Per-boundary transition list — same shape the
        # concat helper expects: ``[(kind, secs), ...]``,
        # one entry per join between consecutive segments
        # that actually rendered.
        seg_transitions: list = []
        # Per-group audio diagnosis, surfaced back to the writer in
        # the export dialog so a "no sound" report can be traced
        # without a terminal. Each entry says what audio the group
        # actually contributed.
        audio_report: list = []
        # Ground-truth probe of each rendered segment file (does the
        # concat input actually carry audio?) — bridges the gap
        # between "overlay resolved" and "final file is silent".
        seg_audio_report: list = []
        try:
            for i, (group, orphans) in enumerate(
                    ordered_groups):
                seg_path = segments_dir / f"seg_{i:03d}.mp4"
                if group is not None:
                    # Inspect exactly what audio this group brings:
                    # placed-slide count, member (tray) slides,
                    # audio-clip count, whether the overlay
                    # resolves on disk, and any per-slide audio.
                    try:
                        from src.video_studio.slide_deck import (
                            resolve_group_overlay)
                        _members = [
                            p for p in self._deck.pages
                            if getattr(p, "group_id", None)
                            == group.id]
                        _placed = [
                            p for p in _members
                            if getattr(
                                p,
                                "start_time_seconds_in_group",
                                None) is not None]
                        _clips = getattr(
                            group, "audio_clips", []) or []
                        _clip_files = sum(
                            1 for c in _clips
                            if getattr(c, "audio_path", "")
                            and Path(c.audio_path).exists())
                        _ov = resolve_group_overlay(
                            group,
                            working_dir=self._deck.working_dir)
                        _ov_ok = bool(
                            _ov and Path(_ov).exists())
                        _per_slide = sum(
                            1 for p in _members
                            if getattr(p, "audio_path", "")
                            and Path(p.audio_path).exists())
                        line = (
                            f"'{group.name or group.id}': "
                            f"members={len(_members)} "
                            f"placed={len(_placed)} "
                            f"clips={len(_clips)} "
                            f"clip_files_on_disk={_clip_files} "
                            f"overlay_ok={_ov_ok} "
                            f"per_slide_audio={_per_slide}")
                        audio_report.append(line)
                        print(f"[deck render] group {line}")
                    except Exception as _diag_exc:
                        audio_report.append(
                            f"'{getattr(group,'name','?')}': "
                            f"diag failed: {_diag_exc}")
                    ok, msg = render_group_to_mp4(
                        self._deck, group, seg_path)
                    _seg_label = group.name or group.id
                    if not ok:
                        seg_audio_report.append(
                            f"seg{i} '{_seg_label}': "
                            f"RENDER FAILED — {msg}")
                        print(
                            f"[deck render] skipping group "
                            f"'{group.name}': {msg}")
                        continue
                else:
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
                    _seg_label = "orphans"
                    if not ok:
                        seg_audio_report.append(
                            f"seg{i} orphans: "
                            f"RENDER FAILED — {msg}")
                        print(
                            f"[deck render] orphan batch "
                            f"failed: {msg}")
                        continue
                # Probe the ACTUAL rendered segment — this is the
                # ground truth of whether the group's audio made it
                # into the segment file, independent of whether the
                # overlay merely resolved.
                _seg_audio = _ffprobe_has_audio(seg_path)
                seg_audio_report.append(
                    f"seg{i} '{_seg_label}': audio={_seg_audio}")
                print(
                    f"[deck render] seg{i} '{_seg_label}' "
                    f"rendered audio={_seg_audio}")
                if segment_paths:
                    kind = (
                        getattr(
                            group,
                            "inter_group_transition_in",
                            "cut")
                        if group is not None else "cut") or "cut"
                    secs = float(
                        (getattr(
                            group,
                            "inter_group_transition_seconds",
                            0.0)
                         if group is not None else 0.0) or 0.0)
                    seg_transitions.append((kind, secs))
                segment_paths.append(seg_path)
            if not segment_paths:
                return (
                    False,
                    "Every group failed to render — nothing "
                    "to concat.")
            ok, msg = _concat_mp4_segments(
                segment_paths, out_path,
                transitions=seg_transitions)
            report = ""
            if seg_audio_report:
                report += (
                    "\n\nRendered segments:\n  • "
                    + "\n  • ".join(seg_audio_report))
            if audio_report:
                report += (
                    "\n\nAudio diagnosis (per group):\n  • "
                    + "\n  • ".join(audio_report))
            if not ok:
                return (
                    False,
                    "CONCAT FAILED: " + (msg or "")
                    + report)
            # Mix the deck-wide background bed under everything —
            # looped to the full deck length and ducked — so the
            # music/ambience carries beneath every group.
            try:
                from src.video_studio.slide_deck import (
                    resolve_deck_background)
                bg = resolve_deck_background(self._deck)
                if bg and Path(bg).exists():
                    bg_ok, bg_msg = _mix_background_under_deck(
                        out_path, bg,
                        gain_db=float(getattr(
                            self._deck,
                            "background_gain_db", -12.0)
                            or -12.0),
                        loop=bool(getattr(
                            self._deck,
                            "background_loop", True)))
                    report += (
                        "\n\nBackground bed: "
                        + ("mixed under deck"
                           if bg_ok
                           else f"FAILED — {bg_msg}"))
            except Exception as _bg_exc:
                report += f"\n\nBackground bed error: {_bg_exc}"
            # Probe the finished file so the writer sees at a
            # glance whether the export actually carries an audio
            # track — the single most useful fact for a
            # "no sound" report.
            final_has_audio = _ffprobe_has_audio(out_path)
            return (
                True,
                (msg or f"Deck rendered to {out_path}.")
                + f"\n\nFinal file has audio track: "
                + ("YES" if final_has_audio else "NO")
                + report)
        finally:
            # Segments are baked into out_path already — drop
            # the temp directory so we don't leak files next
            # to the writer's chosen export location.
            for p in segment_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                segments_dir.rmdir()
            except Exception:
                pass

    def _build_flattened_export_deck(self):
        """Build a synthetic ``SlideDeckProject`` where each
        group's placed slides are expanded in order with
        per-slide holds matching the group editor's timeline,
        and each group's first placed slide carries the
        group's composed overlay audio.

        Used by exports that walk ``deck.pages`` directly and
        only honor per-page ``audio_path`` (notably the PPTX
        exporter). Without this flattening, group overlays are
        invisible to those exporters and writers see silent
        decks. Orphan pages (no group_id) are appended at the
        end and keep whatever audio_path they already had.

        Mirrors the per-slide hold math in
        ``render_group_to_mp4`` so the slide timings the
        writer sees in PowerPoint match the MP4 preview.
        Returns the synthetic deck (does NOT mutate the
        real one).
        """
        from src.video_studio.models import (
            SlideDeckProject as _SDP)
        groups_by_id = {
            g.id: g
            for g in (getattr(self._deck, "groups", []) or [])
        }
        out_pages: list = []
        # Walk groups in deck order so the PPTX matches the
        # Stitch Order panel.
        for g in getattr(self._deck, "groups", []) or []:
            placed = sorted(
                (p for p in self._deck.pages
                 if p.group_id == g.id
                 and getattr(
                     p, "start_time_seconds_in_group", None)
                 is not None),
                key=lambda p: float(
                    getattr(
                        p,
                        "start_time_seconds_in_group", 0.0)
                    or 0.0))
            if not placed:
                continue
            # Resolve (recomposing from audio_clips if the cached
            # WAV is missing) so the PPTX embeds the group's edited
            # narration — gain, de-essing, noise reduction,
            # looping — not a stale/absent cache path.
            from src.video_studio.slide_deck import (
                resolve_group_overlay)
            overlay_path = resolve_group_overlay(
                g, working_dir=self._deck.working_dir)
            overlay_dur = float(
                getattr(
                    g,
                    "overlay_audio_duration_seconds",
                    0.0) or 0.0)
            for i, src in enumerate(placed):
                cur_start = float(
                    getattr(
                        src,
                        "start_time_seconds_in_group",
                        0.0) or 0.0)
                if i + 1 < len(placed):
                    next_start = float(
                        getattr(
                            placed[i + 1],
                            "start_time_seconds_in_group",
                            0.0) or 0.0)
                    hold = max(0.25, next_start - cur_start)
                else:
                    own = max(
                        0.25, float(
                            getattr(
                                src,
                                "duration_seconds", 0.0)
                            or 0.0))
                    tail = max(0.0, overlay_dur - cur_start)
                    # Mirror render_group_to_mp4: cap the trailing
                    # post-narration hold so PowerPoint advances
                    # into the next group promptly instead of
                    # lingering ~0.5s on the last image.
                    if tail > 0:
                        from src.video_studio.slide_deck import (
                            MAX_TRAILING_HOLD_SECONDS)
                        hold = max(
                            tail,
                            min(own,
                                tail + MAX_TRAILING_HOLD_SECONDS))
                    else:
                        hold = own
                copy = src.model_copy(deep=False)
                copy.duration_seconds = round(hold, 3)
                # First placed slide in the group carries the
                # composed overlay audio. Other placed slides
                # play silently (the per-page audio_path is
                # always empty in group-editor land — group
                # owns the audio).
                if (i == 0 and overlay_path
                        and Path(overlay_path).exists()):
                    copy.audio_path = overlay_path
                else:
                    copy.audio_path = ""
                out_pages.append(copy)
        # Orphan pages (no group_id) — keep their own audio
        # paths; they were never under a group's umbrella.
        for page in self._deck.pages:
            gid = getattr(page, "group_id", None)
            if not gid or gid not in groups_by_id:
                out_pages.append(page.model_copy(deep=False))
        return _SDP(
            id=f"flatten_{self._deck.id}",
            name=self._deck.name or "Slide deck",
            working_dir=self._deck.working_dir,
            pages=out_pages,
        )

    def _on_preview_deck_clicked(self) -> None:
        """Render the deck via the shared per-group pipeline
        and play it in a floating preview window. See
        ``_render_deck_via_groups`` for the rendering
        contract."""
        if not self._deck.pages:
            QMessageBox.information(
                self, "Nothing to preview",
                "Add slides to the deck first.")
            return
        from datetime import datetime as _dt
        out_dir = self._working_dir / "deck_previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"deck_preview_{stamp}.mp4"
        self._preview_deck_btn.setEnabled(False)
        self._preview_deck_btn.setText("Rendering…")
        try:
            ok, msg = self._render_deck_via_groups(out_path)
        finally:
            self._preview_deck_btn.setEnabled(True)
            self._preview_deck_btn.setText(
                "🎬 Preview deck")
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
        """Export the deck to a single MP4 using the same
        per-group render + concat pipeline as the deck
        preview.

        The previous implementation called
        ``stitch_slide_deck_to_mp4`` directly on ``self._deck``,
        which only honors per-slide ``audio_path`` — and in the
        group-editor model every slide's audio_path is empty
        (the audio is on the group's composed overlay). The
        result was visually-correct MP4s with no narration at
        all. Routing through ``_render_deck_via_groups`` makes
        the export carry every group's composed audio just
        like preview does.
        """
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
        out_path = Path(out_str)
        self._status_label.setText("Rendering MP4…")
        self._export_mp4_btn.setEnabled(False)
        prior_label = self._export_mp4_btn.text()
        self._export_mp4_btn.setText("Rendering…")
        try:
            ok, msg = self._render_deck_via_groups(out_path)
        finally:
            self._export_mp4_btn.setEnabled(True)
            self._export_mp4_btn.setText(prior_label)
        if not ok:
            self._status_label.setText("")
            QMessageBox.warning(
                self, "Export failed", msg)
            return
        self._status_label.setText(
            f"Saved {out_path.name}.")
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
        # Flatten groups → per-slide pages with on-timeline
        # holds + group overlay audio on the first placed
        # slide of each group. Without this, the PPTX
        # exporter walks ``self._deck.pages`` directly and
        # silently drops every group's narration (per-page
        # audio_path is empty in group-editor land).
        export_deck = self._build_flattened_export_deck()
        if not export_deck.pages:
            export_deck = self._deck
        ok, msg, skipped = export_slide_deck_to_pptx(
            export_deck, Path(out_str))
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
