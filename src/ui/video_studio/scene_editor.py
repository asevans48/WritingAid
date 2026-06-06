"""Scene editor dialog + AI scene generation dialog.

The editor lets the user adjust a scene's name, description, prompt,
and character refs by hand, OR ask the AI director to rewrite them.
It also lists the scene's generated clips with open/favorite/delete
buttons.

The AI generation dialog (``AISceneGenerationDialog``) is the entry
point for "fill scenes from this chapter" — picks a chapter + count
and kicks the AI director.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.video_studio.models import Scene, VideoClip


class SceneEditorDialog(QDialog):
    """Edit a scene by hand or via the AI director.

    Constructor accepts a ``rewrite_callback`` so the studio widget
    can wire the LLM + RAG + project at call time. When None, the
    "Ask AI to improve" button is disabled.
    """

    def __init__(
        self,
        scene: Scene,
        rewrite_callback: Optional[
            Callable[[Scene, str], Scene]] = None,
        project: Optional[Any] = None,
        project_dir: Optional[str] = None,
        llm_provider: Optional[Callable[[], Any]] = None,
        rag_provider: Optional[Callable[[], Any]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Scene — {scene.name or 'Untitled'}")
        self.setModal(True)
        # Larger laptops can show the whole form at once; smaller
        # laptops shrink the dialog and rely on the inner scroll
        # area added in ``_build_ui``. We cap the initial height to
        # ~85% of the available screen so 1366×768 laptops don't
        # open with Save/Cancel pushed off-screen.
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_h = int(avail.height() * 0.85) if avail else 820
        max_w = int(avail.width() * 0.9) if avail else 760
        self.resize(min(760, max_w), min(820, max_h))
        self.setMinimumSize(560, 360)
        self._scene = scene
        self._rewrite_callback = rewrite_callback
        # Optional refs used by the narration UX. ``project`` gives
        # us chapter prose; ``project_dir`` is where per-scene audio
        # files land. ``llm_provider`` enables the AI-highlight +
        # action-summary path in the "Pull from chapter" picker
        # (no-op when None). All default to None so existing
        # callers that didn't pass them continue to work.
        self._project = project
        self._project_dir = project_dir
        self._llm_provider = llm_provider
        # Optional graphRAG provider — when wired in, the per-action
        # edit dialog exposes an "enrich from graphRAG" button that
        # folds character / worldbuilding detail into the action's
        # description and scenery.
        self._rag_provider = rag_provider
        # Optional callback set by the host so the editor can
        # generate images for individual actions when the scene is
        # in slideshow mode. Shape: callable(SceneAction) →
        # Optional[ActionImage]. None means "no image backend
        # available" and the dialog's image controls degrade
        # cleanly.
        self._image_generator: Optional[
            Callable[[Any], Optional[Any]]] = None
        # Host-supplied generation callbacks. All optional — the
        # editor degrades cleanly (buttons stay disabled with a
        # tooltip explanation) when the studio hasn't wired them.
        # Each callable takes the Scene reference and is expected
        # to mutate scene.clips in place; the editor refreshes its
        # clip list after each call.
        self._generate_video_cb: Optional[
            Callable[[Any], None]] = None
        self._generate_image_cb: Optional[
            Callable[[Any], None]] = None
        self._stitch_slide_deck_cb: Optional[
            Callable[[Any], None]] = None
        self._open_output_folder_cb: Optional[
            Callable[[Any], None]] = None
        self._build_ui()
        self._load_scene_into_form()

    def set_image_generator(
        self,
        callback: Optional[Callable[[Any], Optional[Any]]],
    ) -> None:
        """Wire the host's per-action image generator. Callable takes a
        SceneAction and returns the new ActionImage (or None when
        generation failed). Called by the studio widget after the
        editor is constructed."""
        self._image_generator = callback

    def set_generation_callbacks(
        self,
        generate_video: Optional[Callable[[Any], None]] = None,
        generate_image: Optional[Callable[[Any], None]] = None,
        stitch_slide_deck: Optional[Callable[[Any], None]] = None,
        open_output_folder: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Wire the host's scene-level generation callbacks. Each
        callable receives the Scene and is expected to mutate
        ``scene.clips`` (or open a file). Any callback left as None
        leaves its corresponding button disabled. Called by the
        studio widget after the editor is constructed.
        """
        self._generate_video_cb = generate_video
        self._generate_image_cb = generate_image
        self._stitch_slide_deck_cb = stitch_slide_deck
        self._open_output_folder_cb = open_output_folder
        self._refresh_generation_buttons()

    def get_scene(self) -> Scene:
        """Caller picks this up after exec() returns Accepted."""
        return self._scene

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Outer layout holds a vertical scroll area for the scene
        # content + a pinned button row at the bottom. On small
        # laptops the dialog itself can be resized below the natural
        # height of the form and the inner scroll area takes over.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)

        form_box = QGroupBox("Scene details")
        form = QFormLayout(form_box)
        self._name_edit = QLineEdit()
        form.addRow("Name", self._name_edit)
        self._description_edit = QPlainTextEdit()
        self._description_edit.setPlaceholderText(
            "What happens in this scene? 1-3 sentences. The "
            "AI director uses this to ground its rewrites.")
        self._description_edit.setMinimumHeight(110)
        form.addRow("Description", self._description_edit)
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText(
            "Terse visual prompt — concrete imagery, lighting, "
            "camera, characters by name. This goes directly to the "
            "video backend.")
        self._prompt_edit.setMinimumHeight(110)
        form.addRow("Prompt", self._prompt_edit)
        self._character_refs_edit = QLineEdit()
        self._character_refs_edit.setPlaceholderText(
            "Comma-separated character names present in this beat")
        form.addRow("Characters", self._character_refs_edit)
        # Source prose — the chapter passage the writer picked via
        # "Pull from chapter". Distinct from the narration TTS text
        # (which is for audio) and from the prompt (which is for
        # the backend). This is the editorial grounding that the AI
        # director uses for action extraction and graphRAG enrich.
        self._source_prose_edit = QPlainTextEdit()
        self._source_prose_edit.setPlaceholderText(
            "The chapter excerpt that grounds this scene. Use "
            "'Pull from chapter…' in the Narration section, or "
            "paste a passage here directly. The AI director uses "
            "this text for action extraction and graphRAG enrich.")
        self._source_prose_edit.setMinimumHeight(90)
        form.addRow("Source prose", self._source_prose_edit)

        # Duration controls — one for video target length, one for
        # how long image stills should be displayed when stitched.
        # Both fall back to the studio default at runtime.
        duration_row = QHBoxLayout()
        self._target_duration_spin = QDoubleSpinBox()
        self._target_duration_spin.setRange(0.0, 60.0)
        self._target_duration_spin.setDecimals(1)
        self._target_duration_spin.setSingleStep(0.5)
        self._target_duration_spin.setSpecialValueText(
            "use studio default")
        self._target_duration_spin.setSuffix(" s")
        self._target_duration_spin.setToolTip(
            "Target length for video clips generated for this "
            "scene. 0 means use the studio's default duration.")
        duration_row.addWidget(QLabel("Video target:"))
        duration_row.addWidget(self._target_duration_spin)
        duration_row.addSpacing(20)
        self._image_display_spin = QDoubleSpinBox()
        self._image_display_spin.setRange(1.0, 60.0)
        self._image_display_spin.setDecimals(1)
        self._image_display_spin.setSingleStep(0.5)
        self._image_display_spin.setSuffix(" s")
        self._image_display_spin.setToolTip(
            "How long an image still for this scene is held on "
            "screen when stitched into the final video.")
        duration_row.addWidget(QLabel("Image display:"))
        duration_row.addWidget(self._image_display_spin)
        duration_row.addStretch()
        form.addRow("Durations", duration_row)

        # Scene mode — determines whether the scene renders as a
        # single video clip or as a slideshow of per-action images.
        mode_row = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Video — one clip per scene", "video")
        self._mode_combo.addItem(
            "Slideshow — one image per action", "slideshow")
        self._mode_combo.setToolTip(
            "Video mode generates a single video clip from the "
            "scene's prompt + actions. Slideshow mode generates one "
            "image per action and the stitcher walks the selected "
            "images as a slide deck.")
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch()
        form.addRow("Render mode", mode_row)
        layout.addWidget(form_box)

        # Actions section — per-action breakdown of the scene.
        actions_box = QGroupBox(
            "Actions (per-shot beats inside this scene)")
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.addWidget(QLabel(
            "Break the scene into discrete actions. Each action "
            "becomes one shot inside the video, or one image in the "
            "slide deck. Each action can link to characters and "
            "locations the writer wants the backend to honor."))
        self._actions_list = QListWidget()
        self._actions_list.itemDoubleClicked.connect(
            self._on_edit_action)
        self._actions_list.itemSelectionChanged.connect(
            self._refresh_action_buttons)
        actions_layout.addWidget(self._actions_list)
        actions_btn_row = QHBoxLayout()
        self._add_action_btn = QPushButton("Add action")
        self._add_action_btn.clicked.connect(self._on_add_action)
        self._edit_action_btn = QPushButton("Edit")
        self._edit_action_btn.clicked.connect(self._on_edit_action)
        self._remove_action_btn = QPushButton("Remove")
        self._remove_action_btn.clicked.connect(
            self._on_remove_action)
        self._move_action_up_btn = QPushButton("↑")
        self._move_action_up_btn.clicked.connect(
            lambda: self._on_move_action(-1))
        self._move_action_down_btn = QPushButton("↓")
        self._move_action_down_btn.clicked.connect(
            lambda: self._on_move_action(+1))
        self._ai_extract_actions_btn = QPushButton(
            "AI: extract from prose")
        self._ai_extract_actions_btn.setToolTip(
            "Ask the LLM to break this scene into discrete "
            "actions based on the scene's prompt + the linked "
            "chapter's prose + project characters / worldbuilding.")
        self._ai_extract_actions_btn.clicked.connect(
            self._on_ai_extract_actions)
        self._ai_extract_actions_btn.setEnabled(
            self._llm_provider is not None)
        actions_btn_row.addWidget(self._add_action_btn)
        actions_btn_row.addWidget(self._edit_action_btn)
        actions_btn_row.addWidget(self._remove_action_btn)
        actions_btn_row.addWidget(self._move_action_up_btn)
        actions_btn_row.addWidget(self._move_action_down_btn)
        actions_btn_row.addStretch()
        actions_btn_row.addWidget(self._ai_extract_actions_btn)
        actions_layout.addLayout(actions_btn_row)
        # Slideshow-only button to bulk-generate images for every
        # action in one go. Hidden in video mode.
        self._generate_slide_deck_btn = QPushButton(
            "Generate slide-deck images for all actions")
        self._generate_slide_deck_btn.setToolTip(
            "For each action that has no image yet, generate one "
            "image using the current image backend. Use the per-"
            "action edit dialog to refine / re-roll individual "
            "images.")
        self._generate_slide_deck_btn.clicked.connect(
            self._on_generate_slide_deck)
        self._generate_slide_deck_btn.setVisible(False)
        actions_layout.addWidget(self._generate_slide_deck_btn)
        layout.addWidget(actions_box)

        # Re-wire mode picker → toggle slideshow controls.
        self._mode_combo.currentIndexChanged.connect(
            self._on_mode_changed)

        # AI rewrite row
        ai_row = QHBoxLayout()
        self._ai_instruction = QLineEdit()
        self._ai_instruction.setPlaceholderText(
            "Instruction for the AI (optional) — e.g. \"sharper "
            "visual language\", \"add tension\"")
        self._ai_button = QPushButton("Ask AI to improve")
        self._ai_button.setToolTip(
            "Rewrite the description and prompt using the project's "
            "graph-aware RAG context.")
        self._ai_button.clicked.connect(self._run_ai_rewrite)
        self._ai_button.setEnabled(self._rewrite_callback is not None)
        if self._rewrite_callback is None:
            self._ai_button.setToolTip(
                "No LLM is configured — set one up in Settings to "
                "enable AI rewrites.")
        ai_row.addWidget(self._ai_instruction, stretch=1)
        ai_row.addWidget(self._ai_button)
        layout.addLayout(ai_row)

        # Narration (TTS or imported audio)
        narration_box = QGroupBox("Narration")
        narration_layout = QVBoxLayout(narration_box)
        # Help line above the text edit so the user understands what
        # goes in there.
        narration_layout.addWidget(QLabel(
            "Spoken text. Either generate via TTS or import a "
            "pre-recorded audio file. Pull from chapter to grab "
            "actual prose from the linked chapter."))
        self._narration_text = QPlainTextEdit()
        self._narration_text.setPlaceholderText(
            "Text the narrator will speak (or transcript of "
            "imported audio).")
        self._narration_text.setMaximumHeight(120)
        narration_layout.addWidget(self._narration_text)

        narration_btn_row = QHBoxLayout()
        self._pull_chapter_btn = QPushButton("Pull from chapter…")
        self._pull_chapter_btn.clicked.connect(
            self._on_pull_from_chapter)
        narration_btn_row.addWidget(self._pull_chapter_btn)
        narration_btn_row.addWidget(QLabel("TTS:"))
        self._tts_combo = QComboBox()
        # Populated lazily so we get current install state every
        # time the editor opens (user may have installed a backend
        # since last time).
        try:
            from src.video_studio.tts.registry import (
                all_tts_backends,
            )
            for b in all_tts_backends():
                badge = " ✓" if b.is_installed() else "  (install)"
                self._tts_combo.addItem(b.label + badge, b.name)
        except Exception:
            pass
        narration_btn_row.addWidget(self._tts_combo)
        self._tts_generate_btn = QPushButton("Generate TTS")
        self._tts_generate_btn.clicked.connect(self._on_generate_tts)
        narration_btn_row.addWidget(self._tts_generate_btn)
        self._import_audio_btn = QPushButton("Import audio…")
        self._import_audio_btn.clicked.connect(self._on_import_audio)
        narration_btn_row.addWidget(self._import_audio_btn)
        self._clear_narration_btn = QPushButton("Clear")
        self._clear_narration_btn.clicked.connect(
            self._on_clear_narration)
        narration_btn_row.addWidget(self._clear_narration_btn)
        narration_btn_row.addStretch()
        narration_layout.addLayout(narration_btn_row)

        # Status (file, duration) + mismatch picker
        narration_status_row = QHBoxLayout()
        self._narration_status_label = QLabel(
            "<i>No narration attached.</i>")
        self._narration_status_label.setTextFormat(
            Qt.TextFormat.RichText)
        narration_status_row.addWidget(
            self._narration_status_label, stretch=1)
        narration_status_row.addSpacing(12)
        narration_status_row.addWidget(QLabel("If audio ≠ video:"))
        self._mismatch_combo = QComboBox()
        # The labels are friendlier than the internal mode names.
        for value, label in [
            ("trim",
             "Trim to shorter (default)"),
            ("loop",
             "Loop video to fill audio"),
            ("fade_extend",
             "Hold last frame + fade to black"),
            ("extend_silent",
             "Pad audio with silence"),
        ]:
            self._mismatch_combo.addItem(label, value)
        self._mismatch_combo.setToolTip(
            "How the stitcher should reconcile a video / audio "
            "length mismatch when this scene is exported.")
        narration_status_row.addWidget(self._mismatch_combo)
        narration_layout.addLayout(narration_status_row)
        layout.addWidget(narration_box)

        # Generation controls — same actions that live on the canvas
        # card's right-click menu, surfaced inside the editor so the
        # writer can render + iterate without closing the dialog.
        # All four buttons enable themselves only when the host
        # wires the matching callback via
        # ``set_generation_callbacks``; otherwise they sit disabled
        # with an explanatory tooltip.
        gen_box = QGroupBox("Generate output")
        gen_layout = QVBoxLayout(gen_box)
        gen_layout.addWidget(QLabel(
            "Render this scene with the currently-selected video / "
            "image backend (set in the studio toolbar). Outputs land "
            "in the scene's output folder and appear in the list "
            "below."))
        gen_row1 = QHBoxLayout()
        self._gen_video_btn = QPushButton("🎬 Generate video clip")
        self._gen_video_btn.setToolTip(
            "Render a video clip using the studio's selected video "
            "backend. Honors the scene's target duration.")
        self._gen_video_btn.clicked.connect(
            self._on_generate_video_clicked)
        self._gen_image_btn = QPushButton("🖼 Generate image still")
        self._gen_image_btn.setToolTip(
            "Render a single image still using the studio's selected "
            "image backend. Held for 'Image display' seconds when "
            "stitched into the final video.")
        self._gen_image_btn.clicked.connect(
            self._on_generate_image_clicked)
        gen_row1.addWidget(self._gen_video_btn)
        gen_row1.addWidget(self._gen_image_btn)
        gen_layout.addLayout(gen_row1)
        gen_row2 = QHBoxLayout()
        self._stitch_deck_btn = QPushButton(
            "📑 Stitch slide deck → video")
        self._stitch_deck_btn.setToolTip(
            "Stitch each action's favorite image into a single "
            "video. Per-action 'Slide time' (set in the action "
            "editor) controls how long each beat holds; 0 falls "
            "back to the scene's 'Image display' value below.")
        self._stitch_deck_btn.clicked.connect(
            self._on_stitch_slide_deck_clicked)
        self._open_folder_btn = QPushButton("📁 Open output folder")
        self._open_folder_btn.setToolTip(
            "Browse this scene's output files in the system file "
            "manager.")
        self._open_folder_btn.clicked.connect(
            self._on_open_output_folder_clicked)
        gen_row2.addWidget(self._stitch_deck_btn)
        gen_row2.addWidget(self._open_folder_btn)
        gen_layout.addLayout(gen_row2)
        # Until the host wires callbacks (via
        # set_generation_callbacks), every generation button stays
        # disabled with a clear tooltip — the writer sees the
        # affordance but isn't fooled into clicking it.
        for btn in (self._gen_video_btn, self._gen_image_btn,
                    self._stitch_deck_btn, self._open_folder_btn):
            btn.setEnabled(False)
            btn.setToolTip(
                btn.toolTip()
                + "\n\n(Host has not wired this action.)")
        layout.addWidget(gen_box)

        # Clips list
        clips_box = QGroupBox("Generated clips")
        clips_layout = QVBoxLayout(clips_box)
        self._clips_list = QListWidget()
        self._clips_list.itemDoubleClicked.connect(
            self._open_clip_externally)
        clips_layout.addWidget(self._clips_list)
        clip_buttons = QHBoxLayout()
        self._open_clip_btn = QPushButton("Open")
        self._open_clip_btn.clicked.connect(self._open_selected_clip)
        self._favorite_btn = QPushButton("Mark favorite")
        self._favorite_btn.clicked.connect(self._mark_favorite)
        self._delete_clip_btn = QPushButton("Delete clip")
        self._delete_clip_btn.clicked.connect(self._delete_selected_clip)
        clip_buttons.addWidget(self._open_clip_btn)
        clip_buttons.addWidget(self._favorite_btn)
        clip_buttons.addWidget(self._delete_clip_btn)
        clip_buttons.addStretch()
        clips_layout.addLayout(clip_buttons)
        layout.addWidget(clips_box, stretch=1)

        # Wrap the content in the scroll area and pin the dialog
        # button row to the bottom of the dialog (outside the scroll
        # viewport) so Save/Cancel stay reachable when the form is
        # taller than the dialog.
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(8, 4, 8, 8)
        button_row.addWidget(buttons)
        outer.addLayout(button_row)

    # ------------------------------------------------------------------
    # Data binding
    # ------------------------------------------------------------------
    def _load_scene_into_form(self) -> None:
        self._name_edit.setText(self._scene.name)
        self._description_edit.setPlainText(self._scene.description)
        self._prompt_edit.setPlainText(self._scene.prompt)
        self._character_refs_edit.setText(
            ", ".join(self._scene.character_refs))
        self._source_prose_edit.setPlainText(
            self._scene.source_prose or "")
        # Durations — 0 indicates "use studio default" (rendered by
        # the spin's specialValueText).
        target = self._scene.target_duration_seconds or 0.0
        self._target_duration_spin.setValue(float(target))
        self._image_display_spin.setValue(
            float(self._scene.image_display_seconds or 4.0))
        # Render mode (video / slideshow).
        for i in range(self._mode_combo.count()):
            if self._mode_combo.itemData(i) == self._scene.mode:
                self._mode_combo.setCurrentIndex(i)
                break
        self._on_mode_changed(self._mode_combo.currentIndex())
        # Actions — load the list and refresh row decorations.
        self._refresh_actions_list()
        # Narration — text + status + mismatch picker. Sets default
        # mode to "trim" when the scene has no narration yet (the
        # combo's first entry).
        narration = self._scene.narration
        self._narration_text.setPlainText(
            narration.text if narration else "")
        self._refresh_narration_status()
        mode = self._scene.video_audio_mismatch or "trim"
        for i in range(self._mismatch_combo.count()):
            if self._mismatch_combo.itemData(i) == mode:
                self._mismatch_combo.setCurrentIndex(i)
                break
        self._refresh_clip_list()

    def _refresh_narration_status(self) -> None:
        n = self._scene.narration
        if n is None or not n.audio_path:
            self._narration_status_label.setText(
                "<i>No narration attached.</i>")
            return
        from pathlib import Path
        p = Path(n.audio_path)
        bits = []
        if n.source == "tts":
            who = (f"{n.tts_backend}" + (f" / {n.tts_voice}"
                                          if n.tts_voice else ""))
            bits.append(f"<b>TTS</b> ({who})")
        elif n.source == "imported":
            bits.append("<b>Imported</b>")
        elif n.source == "recorded":
            bits.append("<b>Recorded</b>")
        bits.append(p.name)
        if n.duration_seconds:
            bits.append(f"{n.duration_seconds:.1f}s")
        if not p.exists():
            bits.append("<span style='color:red'>FILE MISSING</span>")
        self._narration_status_label.setText(
            " · ".join(bits))

    # ------------------------------------------------------------------
    # Scene-level generation handlers
    # ------------------------------------------------------------------
    def _refresh_generation_buttons(self) -> None:
        """Enable each generation button only when the host wired
        the matching callback. Tooltip stays explanatory either
        way."""
        pairs = [
            (self._gen_video_btn, self._generate_video_cb),
            (self._gen_image_btn, self._generate_image_cb),
            (self._stitch_deck_btn, self._stitch_slide_deck_cb),
            (self._open_folder_btn, self._open_output_folder_cb),
        ]
        for btn, cb in pairs:
            wired = cb is not None
            btn.setEnabled(wired)
            tip = btn.toolTip()
            # Strip a previously-appended "host not wired" hint so
            # rewiring later cleans up.
            tip = tip.split("\n\n(Host has not wired this action.)")[0]
            if not wired:
                tip = (
                    tip + "\n\n(Host has not wired this action.)")
            btn.setToolTip(tip)

    def _on_generate_video_clicked(self) -> None:
        if self._generate_video_cb is None:
            return
        # Commit form edits so the callback sees current prompt /
        # duration values without forcing a Save round-trip.
        self._commit_form_to_scene()
        self._generate_video_cb(self._scene)
        self._refresh_clip_list()

    def _on_generate_image_clicked(self) -> None:
        if self._generate_image_cb is None:
            return
        self._commit_form_to_scene()
        self._generate_image_cb(self._scene)
        self._refresh_clip_list()

    def _on_stitch_slide_deck_clicked(self) -> None:
        if self._stitch_slide_deck_cb is None:
            return
        self._commit_form_to_scene()
        self._stitch_slide_deck_cb(self._scene)
        self._refresh_clip_list()

    def _on_open_output_folder_clicked(self) -> None:
        if self._open_output_folder_cb is None:
            return
        self._open_output_folder_cb(self._scene)

    def _refresh_clip_list(self) -> None:
        self._clips_list.clear()
        fav = self._scene.favorite_clip_id
        for c in self._scene.clips:
            star = "★ " if c.id == fav else ""
            placeholder_mark = " [placeholder]" if c.is_placeholder else ""
            label = (
                f"{star}{c.backend} · {c.duration_seconds:.1f}s"
                f"{placeholder_mark} — {c.file_path}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self._clips_list.addItem(item)
        no_clips = len(self._scene.clips) == 0
        self._open_clip_btn.setEnabled(not no_clips)
        self._favorite_btn.setEnabled(not no_clips)
        self._delete_clip_btn.setEnabled(not no_clips)

    def _selected_clip(self) -> Optional[VideoClip]:
        item = self._clips_list.currentItem()
        if item is None:
            return None
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        for c in self._scene.clips:
            if c.id == clip_id:
                return c
        return None

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _run_ai_rewrite(self) -> None:
        if self._rewrite_callback is None:
            return
        # Pull current form values into the scene first so the AI
        # sees the user's in-progress edits.
        self._commit_form_to_scene()
        instruction = self._ai_instruction.text().strip()
        self._ai_button.setEnabled(False)
        self._ai_button.setText("Asking AI…")
        try:
            updated = self._rewrite_callback(self._scene, instruction)
            self._scene = updated
            self._load_scene_into_form()
        except Exception as e:
            QMessageBox.warning(
                self, "AI rewrite failed",
                f"Could not rewrite scene:\n{e}")
        finally:
            self._ai_button.setEnabled(True)
            self._ai_button.setText("Ask AI to improve")

    def _open_selected_clip(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            return
        self._open_clip_path(clip.file_path, clip.is_placeholder)

    def _open_clip_externally(self, item: QListWidgetItem) -> None:
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        for c in self._scene.clips:
            if c.id == clip_id:
                self._open_clip_path(c.file_path, c.is_placeholder)
                return

    def _open_clip_path(self, path: str, is_placeholder: bool) -> None:
        if not path:
            return
        if is_placeholder:
            QMessageBox.information(
                self, "Placeholder clip",
                "This clip was generated by the placeholder backend "
                "and isn't a playable video. Install a real backend "
                "and regenerate to view actual video.")
            return
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(
                self, "Clip missing",
                f"File no longer exists:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def _mark_favorite(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            return
        self._scene.favorite_clip_id = clip.id
        self._refresh_clip_list()

    def _delete_selected_clip(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            return
        reply = QMessageBox.question(
            self, "Delete clip?",
            f"Remove this clip from the scene?\n\n{clip.file_path}\n\n"
            "The file on disk will also be deleted.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Best-effort file removal — failures don't block model
        # update so we don't leave the scene pointing at a clip the
        # user thinks they deleted.
        try:
            p = Path(clip.file_path)
            if p.exists():
                p.unlink()
            sp = Path(clip.sidecar_path) if clip.sidecar_path else None
            if sp and sp.exists():
                sp.unlink()
        except Exception as e:
            print(f"[video_studio] clip file cleanup failed: {e}")
        self._scene.remove_clip(clip.id)
        self._refresh_clip_list()

    # ------------------------------------------------------------------
    # Narration handlers
    # ------------------------------------------------------------------
    def _on_pull_from_chapter(self) -> None:
        """Open the chapter-text picker.

        When the host wired in an LLM provider, the picker
        auto-highlights the prose passage it thinks corresponds to
        this scene; the user can accept that highlight or re-select
        to override. On accept, the picker also returns a 2-3
        sentence action summary of the selected prose, which we
        push into the scene's description so the storyboard card's
        actions stay grounded in what's actually written.
        """
        chapters = self._chapters_in_project()
        if not chapters:
            QMessageBox.information(
                self, "No chapters",
                "This project has no chapters yet — write some "
                "prose first, then come back.")
            return
        from src.ui.video_studio.chapter_text_picker import (
            ChapterTextPickerDialog,
        )
        dlg = ChapterTextPickerDialog(
            chapters=chapters,
            initial_chapter_id=self._scene.chapter_id,
            scene=self._scene,
            llm_provider=self._llm_provider,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.selected_text()
        if not text.strip():
            return
        self._narration_text.setPlainText(text)
        # Persist the chosen excerpt on the scene AND mirror it into
        # the visible "Source prose" editor so the writer sees the
        # text was saved (and can edit it). Both writes are kept in
        # sync — the form-commit on Save uses the visible field as
        # the source of truth.
        self._source_prose_edit.setPlainText(text)
        self._scene.source_prose = text
        # Summary lands on the scene's description so the
        # storyboard card's actions reflect what the prose actually
        # depicts. Only overwrite when we got one — preserves any
        # description the writer already wrote when no LLM is
        # configured.
        summary = dlg.selected_text_summary()
        if summary:
            self._description_edit.setPlainText(summary)
            self._scene.description = summary
        # If the user picked a different chapter than the scene's
        # current anchor, update the anchor so future "Pull from
        # chapter" calls land there by default.
        new_chapter_id = dlg.selected_chapter_id()
        if new_chapter_id and new_chapter_id != self._scene.chapter_id:
            self._scene.chapter_id = new_chapter_id

    def _on_generate_tts(self) -> None:
        text = self._narration_text.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "No text",
                "Add narration text first (or use 'Pull from "
                "chapter…').")
            return
        backend_name = self._tts_combo.currentData()
        from src.video_studio.tts.registry import get_tts_backend
        from src.video_studio.tts.base import TTSRequest
        backend = get_tts_backend(backend_name) if backend_name else None
        if backend is None or not backend.is_installed():
            QMessageBox.warning(
                self, "TTS not available",
                "The selected TTS backend isn't installed. Pick "
                "another or follow its install help.")
            return
        out_dir = self._scene_audio_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        # Use .wav on Linux/Windows (espeak / SAPI native); .aiff on
        # macOS (say native). The stitcher transcodes either way.
        import sys
        ext = ".aiff" if sys.platform == "darwin" else ".wav"
        out = out_dir / f"narration_{backend.name}{ext}"
        req = TTSRequest(
            text=text, output_path=out,
            scene_name=self._scene.name,
        )
        result = backend.synthesize(req)
        if not result.success:
            QMessageBox.warning(
                self, "TTS failed",
                f"Backend reported: {result.error}")
            return
        from src.video_studio.models import Narration
        self._scene.narration = Narration(
            source="tts",
            text=text,
            audio_path=str(result.output_path),
            duration_seconds=float(result.duration_seconds or 0.0),
            tts_backend=backend.name,
            sidecar_path=str(result.sidecar_path),
        )
        self._refresh_narration_status()

    def _on_import_audio(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import audio for narration",
            "",
            "Audio files (*.mp3 *.wav *.m4a *.aiff *.flac *.ogg "
            "*.opus);;All files (*)")
        if not path:
            return
        # Copy into the scene's audio dir so the project stays
        # self-contained (no broken links if the user moves the
        # source file).
        from pathlib import Path
        import shutil as _shutil
        src = Path(path)
        out_dir = self._scene_audio_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"narration_imported{src.suffix.lower()}"
        try:
            _shutil.copy2(src, dest)
        except Exception as e:
            QMessageBox.warning(
                self, "Import failed",
                f"Could not copy audio file: {e}")
            return
        # Probe duration via ffprobe (best-effort).
        from src.video_studio.tts.base import (
            probe_audio_duration_seconds,
        )
        dur = probe_audio_duration_seconds(dest)
        from src.video_studio.models import Narration
        # Use the existing narration text as the transcript when set.
        transcript = self._narration_text.toPlainText().strip()
        self._scene.narration = Narration(
            source="imported",
            text=transcript,
            audio_path=str(dest),
            duration_seconds=float(dur),
        )
        self._refresh_narration_status()

    def _on_clear_narration(self) -> None:
        if self._scene.narration is None:
            return
        reply = QMessageBox.question(
            self, "Clear narration?",
            "Remove the narration audio from this scene? "
            "(The audio file on disk will also be deleted.)")
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Best-effort file cleanup so the user's project dir doesn't
        # accumulate orphaned audio.
        try:
            from pathlib import Path
            p = Path(self._scene.narration.audio_path)
            if p.exists():
                p.unlink()
            if self._scene.narration.sidecar_path:
                sp = Path(self._scene.narration.sidecar_path)
                if sp.exists():
                    sp.unlink()
        except Exception as e:
            print(f"[video_studio] narration cleanup failed: {e}")
        self._scene.narration = None
        self._refresh_narration_status()

    # ------------------------------------------------------------------
    # Actions section
    # ------------------------------------------------------------------
    def _refresh_actions_list(self) -> None:
        from PyQt6.QtCore import Qt as _Qt
        self._actions_list.clear()
        for i, a in enumerate(self._scene.actions):
            img_tail = ""
            if a.images:
                inc = sum(1 for i in a.images if i.included_in_slideshow)
                img_tail = f"  [{inc}/{len(a.images)} images]"
            item = QListWidgetItem(
                f"{i + 1}.  {a.name or '(unnamed)'}{img_tail}")
            item.setData(_Qt.ItemDataRole.UserRole, a.id)
            self._actions_list.addItem(item)
        self._refresh_action_buttons()

    def _refresh_action_buttons(self) -> None:
        has_sel = self._actions_list.currentItem() is not None
        self._edit_action_btn.setEnabled(has_sel)
        self._remove_action_btn.setEnabled(has_sel)
        self._move_action_up_btn.setEnabled(has_sel)
        self._move_action_down_btn.setEnabled(has_sel)

    def _selected_action_id(self) -> Optional[str]:
        item = self._actions_list.currentItem()
        if item is None:
            return None
        from PyQt6.QtCore import Qt as _Qt
        return item.data(_Qt.ItemDataRole.UserRole)

    def _on_add_action(self) -> None:
        action = self._scene.add_action(
            name="New action",
            description="")
        self._refresh_actions_list()
        # Open the edit dialog immediately so the user can fill it
        # in without an extra click.
        self._open_action_dialog(action)

    def _on_edit_action(self, *args) -> None:
        action_id = self._selected_action_id()
        if action_id is None:
            return
        action = next(
            (a for a in self._scene.actions if a.id == action_id),
            None)
        if action is None:
            return
        self._open_action_dialog(action)

    def _open_action_dialog(self, action) -> None:
        from src.ui.video_studio.scene_action_dialog import (
            SceneActionDialog,
        )
        dlg = SceneActionDialog(
            action=action,
            scene_mode=self._scene.mode,
            project=self._project,
            generate_image_callback=(
                self._make_action_image_callback()
                if self._scene.mode == "slideshow" else None),
            scene=self._scene,
            llm_provider=self._llm_provider,
            rag_provider=self._rag_provider,
            parent=self)
        dlg.exec()
        self._refresh_actions_list()

    def _on_remove_action(self) -> None:
        action_id = self._selected_action_id()
        if action_id is None:
            return
        # Clean up any image files attached to this action so they
        # don't accumulate in the project dir.
        action = next(
            (a for a in self._scene.actions if a.id == action_id),
            None)
        if action is not None:
            for img in action.images:
                try:
                    p = Path(img.file_path)
                    if p.exists():
                        p.unlink()
                    sp = (Path(img.sidecar_path)
                          if img.sidecar_path else None)
                    if sp and sp.exists():
                        sp.unlink()
                except Exception as e:
                    print(f"[scene] action image cleanup failed: {e}")
        self._scene.remove_action(action_id)
        self._refresh_actions_list()

    def _on_move_action(self, delta: int) -> None:
        action_id = self._selected_action_id()
        if action_id is None:
            return
        if self._scene.move_action(action_id, delta):
            self._refresh_actions_list()
            # Restore selection on the moved row.
            from PyQt6.QtCore import Qt as _Qt
            for i in range(self._actions_list.count()):
                if (self._actions_list.item(i).data(
                        _Qt.ItemDataRole.UserRole) == action_id):
                    self._actions_list.setCurrentRow(i)
                    break

    def _on_ai_extract_actions(self) -> None:
        """Ask the LLM to break the scene into actions."""
        if self._llm_provider is None:
            return
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            QMessageBox.information(
                self, "No LLM configured",
                "Configure an LLM in Settings to use AI action "
                "extraction.")
            return
        # Pull chapter prose for grounding.
        chapter_text = ""
        if (self._project is not None
                and self._scene.chapter_id):
            ms = getattr(self._project, "manuscript", None)
            chapters = getattr(ms, "chapters", []) if ms else []
            for ch in chapters or []:
                if getattr(ch, "id", "") == self._scene.chapter_id:
                    chapter_text = (
                        getattr(ch, "content", "") or "")
                    break
        from src.video_studio.ai_director import (
            extract_actions_from_scene,
        )
        actions = extract_actions_from_scene(
            scene=self._scene,
            chapter_text=chapter_text,
            project=self._project,
            llm=llm)
        if not actions:
            QMessageBox.warning(
                self, "AI extraction returned nothing",
                "The LLM didn't return any actions. Try adding "
                "more detail to the scene's prompt and "
                "description first.")
            return
        # Confirm replacement when the scene already has actions.
        if self._scene.actions:
            reply = QMessageBox.question(
                self, "Replace existing actions?",
                f"This scene already has "
                f"{len(self._scene.actions)} action(s). Replace "
                f"them with the {len(actions)} AI-extracted "
                f"action(s)?")
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._scene.actions = []
        for a in actions:
            self._scene.add_action(
                name=a["name"],
                description=a["description"],
                character_refs=a.get("character_refs", []),
                location_refs=a.get("location_refs", []),
            )
            # Scenery details + prose excerpt — attach directly
            # since add_action doesn't take them as kwargs.
            self._scene.actions[-1].scenery_details = (
                a.get("scenery_details", ""))
            self._scene.actions[-1].prose_excerpt = (
                a.get("prose_excerpt", ""))
        self._refresh_actions_list()

    def _on_mode_changed(self, _index: int) -> None:
        mode = self._mode_combo.currentData()
        self._generate_slide_deck_btn.setVisible(
            mode == "slideshow")

    def _make_action_image_callback(self):
        """Build the per-action image-generation callback the
        SceneActionDialog uses. Returns None when the host hasn't
        wired an image backend in."""
        if self._image_generator is None:
            return None
        return self._image_generator

    def _on_generate_slide_deck(self) -> None:
        """For every action lacking images, generate one via the
        host's image generator. The host wired
        ``set_image_generator()`` to a callable returning an
        ActionImage given a SceneAction; we just iterate."""
        if self._image_generator is None:
            QMessageBox.information(
                self, "No image backend",
                "Pick an image backend in the studio toolbar "
                "before generating slide-deck images.")
            return
        if not self._scene.actions:
            QMessageBox.information(
                self, "No actions",
                "Add or extract actions first.")
            return
        created = 0
        for a in self._scene.actions:
            if a.images:
                continue
            try:
                img = self._image_generator(a)
                if img is not None:
                    created += 1
            except Exception as e:
                print(f"[scene] action image gen failed: {e}")
        self._refresh_actions_list()
        if created == 0:
            QMessageBox.information(
                self, "Nothing to do",
                "Every action already has at least one image. "
                "Use the per-action edit dialog to add more.")

    def _scene_audio_dir(self):
        """Per-scene audio output dir. Mirrors the studio's per-scene
        clip directory layout.

        ``self._project_dir`` is the ``.writerproj`` FILE path the
        host passes in, not a directory — taking ``.parent`` and a
        stem-namespaced subfolder mirrors ``_studio_root_dir`` in
        studio_widget so audio lands next to the video output.
        """
        from pathlib import Path
        base = Path(self._project_dir) if self._project_dir else Path(".")
        if self._project_dir and not base.is_dir():
            base = base.parent / f"{base.stem}_video_studio"
        return base / "scenes" / self._scene.id / "audio"

    def _chapters_in_project(self):
        """Pull the list of chapters from the parent studio widget's
        bound project — needed by the chapter-text picker. Falls
        back to empty list if the project isn't reachable.
        """
        try:
            return list(self._project.manuscript.chapters)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _commit_form_to_scene(self) -> None:
        self._scene.name = self._name_edit.text().strip()
        self._scene.description = (
            self._description_edit.toPlainText().strip())
        self._scene.prompt = self._prompt_edit.toPlainText().strip()
        refs_raw = self._character_refs_edit.text().strip()
        self._scene.character_refs = [
            r.strip() for r in refs_raw.split(",") if r.strip()]
        # Persist the source prose excerpt the writer chose / edited.
        self._scene.source_prose = (
            self._source_prose_edit.toPlainText().strip())
        # Target duration — 0 means "use studio default", which we
        # store as None so the model's effective_duration helper
        # correctly falls back.
        target = float(self._target_duration_spin.value())
        self._scene.target_duration_seconds = (
            target if target > 0 else None)
        self._scene.image_display_seconds = float(
            self._image_display_spin.value())
        # Mode picker → scene.mode
        mode = self._mode_combo.currentData()
        if mode in ("video", "slideshow"):
            self._scene.mode = mode
        # Narration text edits propagate so the user can type a new
        # transcript / TTS prompt without re-generating.
        if self._scene.narration is not None:
            self._scene.narration.text = (
                self._narration_text.toPlainText().strip())
        # Mismatch handler — combo holds the canonical mode name as
        # itemData on each entry.
        mode = self._mismatch_combo.currentData()
        if mode:
            self._scene.video_audio_mismatch = mode
        from datetime import datetime
        self._scene.updated_at = datetime.now()

    def _on_save(self) -> None:
        self._commit_form_to_scene()
        self.accept()


# ---------------------------------------------------------------------
# AI generate-from-chapter dialog
# ---------------------------------------------------------------------
class AISceneGenerationDialog(QDialog):
    """Pick a chapter + scene count + duration, then kick the AI
    director. The actual call is done by the caller (studio widget)
    so the dialog stays UI-only and easy to test."""

    def __init__(
        self,
        chapters: List,  # List[Chapter] — typed loosely to avoid import cycle
        default_count: int = 6,
        default_duration: float = 8.0,
        project: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Generate Scenes from Chapter")
        self.setModal(True)
        self.resize(540, 360)
        self._chapters = chapters
        # ``project`` lets us detect planned beats per-chapter so the
        # count spinner can pre-fill to the chapter's plan. Optional
        # so existing callers without a project keep working.
        self._project = project
        self._build_ui(default_count, default_duration)

    def _build_ui(self, default_count: int,
                  default_duration: float) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Pick a chapter to storyboard. The AI director uses the "
            "chapter prose, the chapter's planning notes, and the "
            "project's graph-aware RAG context to produce a scene "
            "sequence."))
        form = QFormLayout()
        self._chapter_combo = QComboBox()
        for ch in self._chapters:
            num = getattr(ch, "number", 0)
            title = getattr(ch, "title", "") or "(untitled)"
            label = f"Ch. {num}: {title}" if num else title
            self._chapter_combo.addItem(label, ch)
        # Re-check planned beats whenever the chapter changes so the
        # status hint + count spinner reflect what's in scope.
        self._chapter_combo.currentIndexChanged.connect(
            self._on_chapter_changed)
        form.addRow("Chapter", self._chapter_combo)

        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 12)
        self._count_spin.setValue(default_count)
        form.addRow("Number of scenes", self._count_spin)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(2, 30)
        self._duration_spin.setValue(int(default_duration))
        self._duration_spin.setSuffix(" s")
        form.addRow("Default clip duration", self._duration_spin)

        self._use_planned_check = QCheckBox(
            "Use the chapter's planned scenes / plot events when "
            "available (recommended)")
        self._use_planned_check.setChecked(True)
        self._use_planned_check.setToolTip(
            "When the chapter has scene_list entries OR plot events "
            "tied to its featured characters, those become the "
            "storyboard skeleton — the AI fills in the visuals but "
            "doesn't drop or invent beats. Uncheck to ignore the "
            "writing-module structure and generate freely.")
        # Toggle visibility/usefulness of the count spinner — it's
        # ignored when planned beats are used.
        self._use_planned_check.toggled.connect(
            self._on_planned_toggle)
        form.addRow("", self._use_planned_check)

        self._auto_link = QCheckBox(
            "Connect generated scenes with hops in order")
        self._auto_link.setChecked(True)
        form.addRow("", self._auto_link)
        layout.addLayout(form)

        # Planned-beats hint surfaces what we detected so the user
        # isn't surprised when the count differs from the spinner.
        self._planned_hint = QLabel("")
        self._planned_hint.setWordWrap(True)
        self._planned_hint.setStyleSheet(
            "color: #2563eb; padding: 4px 0;")
        layout.addWidget(self._planned_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Generate")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Initial state — show hint for whichever chapter is selected.
        self._on_chapter_changed(self._chapter_combo.currentIndex())

    def _on_chapter_changed(self, index: int) -> None:
        """Update the planned-beats hint + pre-fill the count
        spinner with the number of beats detected for this chapter
        (when "Use planned" is checked)."""
        chapter = self._chapter_combo.itemData(index)
        if chapter is None:
            self._planned_hint.setText("")
            return
        try:
            from src.video_studio.ai_director import (
                detect_planned_beats_count,
            )
            n = detect_planned_beats_count(chapter, self._project)
        except Exception:
            n = 0
        if n > 0:
            self._planned_hint.setText(
                f"<i>This chapter has <b>{n}</b> planned "
                f"beat(s) — the storyboard will follow them when "
                f"<i>Use the chapter's planned scenes</i> is "
                f"checked. The number-of-scenes spinner is ignored "
                f"in that case.</i>")
            if self._use_planned_check.isChecked():
                self._count_spin.setValue(min(12, max(1, n)))
                self._count_spin.setEnabled(False)
            else:
                self._count_spin.setEnabled(True)
        else:
            self._planned_hint.setText(
                "<i>No planned beats detected for this chapter — "
                "the AI will generate scenes from the prose using "
                "the number-of-scenes setting.</i>")
            self._count_spin.setEnabled(True)

    def _on_planned_toggle(self, checked: bool) -> None:
        """Re-evaluate the count spinner's enabled state when the
        user toggles planned-beats usage."""
        self._on_chapter_changed(self._chapter_combo.currentIndex())

    def selected_chapter(self):
        return self._chapter_combo.currentData()

    def scene_count(self) -> int:
        return self._count_spin.value()

    def duration_seconds(self) -> float:
        return float(self._duration_spin.value())

    def auto_link(self) -> bool:
        return self._auto_link.isChecked()

    def use_planned_beats(self) -> bool:
        """Whether the caller should pass ``prefer_planned_beats=True``
        to the AI director. Wired to the new checkbox."""
        return self._use_planned_check.isChecked()
