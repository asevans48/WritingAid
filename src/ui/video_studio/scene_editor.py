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
from src.ui.video_studio.conversation_panel import CreativeConversationPanel


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
        # Optional prompt-composer — receives the scene and returns
        # the assembled backend prompt as a string. When wired, the
        # "Copy generation prompt" button copies the result; when
        # not, the button falls back to scene.prompt alone so the
        # affordance still works without the studio's style block.
        self._compose_prompt_cb: Optional[
            Callable[[Any], str]] = None
        # Optional refinement callback — when wired, the
        # "Preview AI-refined prompt" button asks the LLM to
        # translate the structured composed prompt into proper
        # artwork-direction language and shows the result. The
        # callable signature is callable(scene, target:str) → str
        # where target is "image" or "video".
        self._refine_prompt_cb: Optional[
            Callable[[Any, str], str]] = None
        # Per-action refinement — forwarded to the SceneActionDialog
        # so its "Preview AI-refined prompt" button can show the
        # image-target refinement of the per-action prompt.
        self._refine_action_prompt_cb: Optional[
            Callable[[Any, Any], str]] = None
        # Per-action upload callback — forwarded so the action
        # editor's "📤 Upload image" button can import existing
        # files (Midjourney / RunwayML output, hand-drawn art) into
        # the action's image list.
        self._upload_action_image_cb: Optional[
            Callable[[Any, Any], Optional[Any]]] = None
        # Scene-level upload callback — for the editor's own
        # "📤 Upload image / video" button in the Generate group.
        self._upload_scene_clip_cb: Optional[
            Callable[[Any], None]] = None
        # Sub-dialog (per-action editor, AI extract, image
        # generation, etc.) mutate ``self._scene`` directly. If the
        # writer then Cancels the outer dialog, those mutations are
        # already on the live scene — but ``contentChanged`` only
        # fires on outer-Save, so a Cancel after sub-dialog edits
        # would orphan them until the next save trigger and lose
        # them on a fresh reload. We track an "actions dirty" flag
        # so the host can force-save on close regardless of the
        # outer dialog's Accepted/Rejected state.
        self._actions_dirty: bool = False
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
        compose_prompt: Optional[Callable[[Any], str]] = None,
        refine_prompt: Optional[
            Callable[[Any, str], str]] = None,
        refine_action_prompt: Optional[
            Callable[[Any, Any], str]] = None,
        upload_action_image: Optional[
            Callable[[Any, Any], Optional[Any]]] = None,
        upload_scene_clip: Optional[
            Callable[[Any], None]] = None,
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
        self._compose_prompt_cb = compose_prompt
        self._refine_prompt_cb = refine_prompt
        self._refine_action_prompt_cb = refine_action_prompt
        self._upload_action_image_cb = upload_action_image
        self._upload_scene_clip_cb = upload_scene_clip
        self._refresh_generation_buttons()

    def get_scene(self) -> Scene:
        """Caller picks this up after exec() returns Accepted."""
        return self._scene

    def actions_dirty(self) -> bool:
        """True when any sub-dialog or action-mutating button
        committed changes during this dialog's lifetime. The host
        uses this to decide whether to fire its ``contentChanged``
        signal even when the writer Cancels the outer dialog —
        sub-dialog edits already mutated the live scene and must
        survive to the next disk save."""
        return self._actions_dirty

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
        # Hand-curated character + setting description blocks.
        # The writer can fill these by hand OR via the "+ Lookup"
        # buttons that pull from project.characters /
        # project.worldbuilding.places. Both fold into every
        # backend prompt so the renderer sees the writer's
        # authoritative description — independent of any LLM
        # enhancer.
        char_label_row = QHBoxLayout()
        char_label_row.addWidget(QLabel("Character details:"))
        char_label_row.addStretch()
        self._lookup_char_btn = QPushButton("+ Lookup character…")
        self._lookup_char_btn.setToolTip(
            "Pick a character from the project to append their "
            "appearance / personality / quirks into this box.")
        self._lookup_char_btn.clicked.connect(
            self._on_lookup_character)
        char_label_row.addWidget(self._lookup_char_btn)
        form.addRow(char_label_row)
        self._character_details_edit = QPlainTextEdit()
        self._character_details_edit.setPlaceholderText(
            "Visible character detail — appearance, clothing, "
            "voice cues. The renderer sees this verbatim.")
        self._character_details_edit.setMinimumHeight(80)
        form.addRow(self._character_details_edit)

        setting_label_row = QHBoxLayout()
        setting_label_row.addWidget(QLabel("Setting / worldbuilding:"))
        setting_label_row.addStretch()
        self._lookup_place_btn = QPushButton("+ Lookup place…")
        self._lookup_place_btn.setToolTip(
            "Pick a place from worldbuilding to append its "
            "description / atmosphere / key features.")
        self._lookup_place_btn.clicked.connect(
            self._on_lookup_place)
        setting_label_row.addWidget(self._lookup_place_btn)
        form.addRow(setting_label_row)
        self._setting_details_edit = QPlainTextEdit()
        self._setting_details_edit.setPlaceholderText(
            "Location, atmosphere, key features. Pulled into "
            "every backend prompt for this scene.")
        self._setting_details_edit.setMinimumHeight(80)
        form.addRow(self._setting_details_edit)

        # Free-form additional instructions — the writer's
        # "tell the model THIS too" box. Folded into every backend
        # prompt verbatim, after the structured detail so the
        # directives take precedence in the model's attention.
        self._additional_instructions_edit = QPlainTextEdit()
        self._additional_instructions_edit.setPlaceholderText(
            "Extra directives for the renderer (aspect ratio, "
            "framing notes, 'no text overlays', 'shot from low "
            "angle', etc.). Appended to every backend prompt for "
            "this scene.")
        self._additional_instructions_edit.setMinimumHeight(70)
        form.addRow(
            "Additional instructions",
            self._additional_instructions_edit)

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
        # 0–600 s (10 min) — the prior 60 s cap silently clamped
        # writer input, which surfaced as decks "cut at a minute"
        # in long slideshow scenes.
        self._target_duration_spin.setRange(0.0, 600.0)
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
        # 1–600 s (10 min) — the prior 60 s cap clamped writer
        # input so long-held title cards or 90 s slide holds
        # silently became 60 s. That's the symptom behind decks
        # that "cut everything at a minute."
        self._image_display_spin.setRange(1.0, 600.0)
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
        # Upload existing image / video files into this scene —
        # writers using paid subscriptions (Midjourney, RunwayML,
        # Sora, etc.) can bring rendered output in without leaving
        # the studio. Files are copied into the scene's output
        # folder so the project stays portable.
        self._upload_scene_btn = QPushButton("📤 Upload image / video")
        self._upload_scene_btn.setToolTip(
            "Import existing image or video files into this scene "
            "as clips. Lets writers use output from external "
            "generators (or hand-shot footage) instead of (or "
            "alongside) the in-app backends.")
        self._upload_scene_btn.clicked.connect(
            self._on_upload_scene_clicked)
        gen_row1.addWidget(self._upload_scene_btn)
        gen_layout.addLayout(gen_row1)
        gen_row2 = QHBoxLayout()
        # Preview / copy the assembled prompt — what the backend
        # will actually see (style block + scene prompt + action
        # sequence). Useful for sanity-checking before burning a
        # render or for pasting into an external tool.
        self._copy_prompt_btn = QPushButton("📋 Copy generation prompt")
        self._copy_prompt_btn.setToolTip(
            "Copy the full prompt the video backend would receive "
            "(style + genre + scene prompt + action sequence) to "
            "the clipboard.")
        self._copy_prompt_btn.clicked.connect(
            self._on_copy_prompt_clicked)
        gen_row2.addWidget(self._copy_prompt_btn)
        # AI-refine preview — shows what the LLM-translated
        # artwork prompt looks like before the writer commits to a
        # render. Target is picked from scene.mode (slideshow →
        # image; otherwise video) so the writer sees the same
        # prompt the renderer would receive.
        self._preview_refined_btn = QPushButton(
            "✨ Preview AI-refined prompt")
        self._preview_refined_btn.setToolTip(
            "Run the structured prompt through the LLM to "
            "translate it into proper image / video art-direction "
            "language. Opens a small dialog with the result.")
        self._preview_refined_btn.clicked.connect(
            self._on_preview_refined_clicked)
        gen_row2.addWidget(self._preview_refined_btn)
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
        # Voiceover editor — record / import audio takes,
        # arrange them on a per-second timeline, trim + fade +
        # gain. Always available since voiceover doesn't need a
        # generated visual yet; writers may want to lay down a
        # narration track before they pick a backend.
        self._voiceover_btn = QPushButton(
            "🎤 Voiceover editor…")
        self._voiceover_btn.setToolTip(
            "Record, import, and arrange voiceover takes for "
            "this scene. Multiple takes mix together at stitch "
            "time.")
        self._voiceover_btn.clicked.connect(
            self._on_open_voiceover_editor)
        gen_layout.addWidget(self._voiceover_btn)
        # Until the host wires callbacks (via
        # set_generation_callbacks), every generation button stays
        # disabled with a clear tooltip — the writer sees the
        # affordance but isn't fooled into clicking it. Copy-prompt
        # stays out of this list because it's host-agnostic; the
        # editor handles it directly via _on_copy_prompt_clicked.
        for btn in (self._gen_video_btn, self._gen_image_btn,
                    self._stitch_deck_btn, self._open_folder_btn,
                    self._upload_scene_btn):
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

        # ── AI conversation panel for iterative refinement ────────
        self._conversation_panel = CreativeConversationPanel(
            llm_provider=self._llm_provider,
            context_mode="scene",
        )
        self._conversation_panel.apply_suggestion.connect(
            self._on_chat_apply_suggestion)
        self._conversation_panel.setMaximumHeight(280)
        layout.addWidget(self._conversation_panel)

        # Wrap the content in the scroll area and pin the dialog
        # button row to the bottom of the dialog (outside the scroll
        # viewport) so Save/Cancel stay reachable when the form is
        # taller than the dialog.
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # Dialog buttons. We use Save + Close (instead of the
        # default Save + Cancel) so writers don't silently lose
        # form-level edits when they reach for the X / Esc — both
        # buttons commit the form. Sub-dialog mutations (image
        # generation, action edits, AI enrich) have already
        # written to the live scene by the time we get here, so
        # they survive either choice. The auto-save timer on the
        # main window picks up the change shortly after the dialog
        # closes.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        buttons.button(
            QDialogButtonBox.StandardButton.Close).setText(
                "Close")
        buttons.accepted.connect(self._on_save)
        # Close also commits — we treat it as Save under a quieter
        # label so writers can choose whichever feels right.
        buttons.rejected.connect(self._on_close_commit)
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
        self._character_details_edit.setPlainText(
            getattr(self._scene, "character_details", "") or "")
        self._setting_details_edit.setPlainText(
            getattr(self._scene, "setting_details", "") or "")
        self._additional_instructions_edit.setPlainText(
            getattr(
                self._scene, "additional_instructions", "") or "")
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
        self._sync_conversation_context()

    def _sync_conversation_context(self) -> None:
        """Push current form state into the conversation panel."""
        self._conversation_panel.set_context({
            "name": self._name_edit.text(),
            "description": self._description_edit.toPlainText(),
            "prompt": self._prompt_edit.toPlainText(),
            "character_refs": self._character_refs_edit.text(),
            "character_details": self._character_details_edit.toPlainText(),
            "setting_details": self._setting_details_edit.toPlainText(),
            "additional_instructions": self._additional_instructions_edit.toPlainText(),
            "source_prose": self._source_prose_edit.toPlainText(),
        })

    def _on_chat_apply_suggestion(self, field: str, value: str) -> None:
        """Handle apply_suggestion from the conversation panel."""
        if field == "prompt":
            self._prompt_edit.setPlainText(value)
        elif field == "description":
            self._description_edit.setPlainText(value)
        elif field == "character_details":
            self._character_details_edit.setPlainText(value)
        elif field == "setting_details":
            self._setting_details_edit.setPlainText(value)
        elif field == "additional_instructions":
            self._additional_instructions_edit.setPlainText(value)
        else:
            self._prompt_edit.setPlainText(value)

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
            (self._upload_scene_btn, self._upload_scene_clip_cb),
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
        self._actions_dirty = True
        self._refresh_clip_list()

    def _on_generate_image_clicked(self) -> None:
        if self._generate_image_cb is None:
            return
        self._commit_form_to_scene()
        self._generate_image_cb(self._scene)
        self._actions_dirty = True
        self._refresh_clip_list()

    def _on_stitch_slide_deck_clicked(self) -> None:
        if self._stitch_slide_deck_cb is None:
            return
        self._commit_form_to_scene()
        self._stitch_slide_deck_cb(self._scene)
        self._actions_dirty = True
        self._refresh_clip_list()

    def _on_upload_scene_clicked(self) -> None:
        if self._upload_scene_clip_cb is None:
            return
        self._commit_form_to_scene()
        self._upload_scene_clip_cb(self._scene)
        # Uploads land as new clips on the scene; mark actions
        # dirty so the host fires contentChanged even on Close.
        self._actions_dirty = True
        self._refresh_clip_list()

    def _on_open_output_folder_clicked(self) -> None:
        if self._open_output_folder_cb is None:
            return
        self._open_output_folder_cb(self._scene)

    def _on_open_voiceover_editor(self) -> None:
        """Open the voiceover editor for this scene. Recording and
        imports land in the scene's audio directory (same place
        TTS narration uses) so the project stays self-contained."""
        from src.ui.video_studio.voiceover_editor import (
            VoiceoverEditorDialog,
        )
        audio_dir = self._scene_audio_dir()
        dlg = VoiceoverEditorDialog(
            self._scene, audio_dir, parent=self)
        before = len(self._scene.voiceover_segments)
        dlg.exec()
        if len(self._scene.voiceover_segments) != before:
            # Mark dirty so the scene editor's host fires
            # contentChanged on close even if the writer reaches
            # for Cancel.
            self._actions_dirty = True

    def _on_preview_refined_clicked(self) -> None:
        """Compose the structured prompt, ask the host to refine
        it via the LLM, then show the result in a small read-only
        dialog with a Copy button. Target is image for slideshow
        mode, video otherwise — matches the renderer the writer
        is heading toward."""
        if (self._refine_prompt_cb is None
                or self._compose_prompt_cb is None):
            QMessageBox.information(
                self, "AI refine unavailable",
                "Refinement needs an LLM. Configure one in "
                "Settings → ⚙️ Model Settings, then re-open the "
                "scene editor.")
            return
        # Commit form edits so the refinement sees the freshest
        # detail without forcing a Save round-trip.
        self._commit_form_to_scene()
        target = (
            "image" if self._scene.mode == "slideshow" else "video")
        prev_label = self._preview_refined_btn.text()
        self._preview_refined_btn.setEnabled(False)
        self._preview_refined_btn.setText("Refining…")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            refined = self._refine_prompt_cb(self._scene, target)
        finally:
            self._preview_refined_btn.setEnabled(True)
            self._preview_refined_btn.setText(prev_label)
        if not refined or not refined.strip():
            QMessageBox.information(
                self, "Nothing to refine",
                "The LLM didn't return a refined prompt. Try "
                "filling more detail in the prompt / character / "
                "setting boxes first.")
            return
        self._show_refined_prompt_dialog(refined, target)

    def _show_refined_prompt_dialog(
        self, refined: str, target: str,
    ) -> None:
        """Minimal modal: scrollable read-only text + Copy + Close."""
        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"AI-refined prompt ({target})")
        dlg.resize(640, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "This is the prompt the renderer will receive when "
            f"the studio's ✨ AI refine toggle is on (target: "
            f"<b>{target}</b>). The structured detail you entered "
            "drives the translation — refine the source fields if "
            "anything is off."))
        text = QPlainTextEdit()
        text.setPlainText(refined)
        text.setReadOnly(True)
        v.addWidget(text, stretch=1)
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("📋 Copy")
        close_btn = QPushButton("Close")
        from PyQt6.QtWidgets import QApplication
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(refined))
        close_btn.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dlg.exec()

    def _on_copy_prompt_clicked(self) -> None:
        """Copy the assembled generation prompt to the clipboard.
        Uses the host's composer when wired (full style + genre +
        action sequence); falls back to ``scene.prompt`` so the
        button works even when the dialog is opened standalone."""
        # Commit edits first so a writer who tweaked the prompt /
        # actions in this dialog sees the current values in the
        # copied text.
        self._commit_form_to_scene()
        if self._compose_prompt_cb is not None:
            text = self._compose_prompt_cb(self._scene)
        else:
            text = (self._scene.prompt or "").strip()
        if not text.strip():
            QMessageBox.information(
                self, "Empty prompt",
                "This scene has no prompt yet. Fill in the scene's "
                "prompt (and optionally actions / style) first.")
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        # Brief confirmation — the dialog has no status bar, so a
        # transient label change on the button itself is the least
        # noisy way to acknowledge.
        prev = self._copy_prompt_btn.text()
        self._copy_prompt_btn.setText("✓ Copied to clipboard")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(
            1500, lambda: self._copy_prompt_btn.setText(prev))

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
    # ------------------------------------------------------------------
    # Lookup helpers — append project data into the detail boxes
    # ------------------------------------------------------------------
    def _append_to_plain_text(
        self, edit, snippet: str,
    ) -> None:
        """Append ``snippet`` to a QPlainTextEdit, separated by a
        blank line when the box isn't empty. Mutates in place."""
        existing = edit.toPlainText().rstrip()
        text = (f"{existing}\n\n{snippet.strip()}"
                if existing else snippet.strip())
        edit.setPlainText(text)
        # Scroll to the bottom so the new content is visible.
        bar = edit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_lookup_character(self) -> None:
        chars = list(
            getattr(self._project, "characters", []) or [])
        if not chars:
            QMessageBox.information(
                self, "No characters",
                "This project has no characters yet — add them in "
                "the Characters tab first.")
            return
        from src.ui.image_generator_widget import (
            EntityPickerDialog, _character_snippet,
        )
        items = []
        for ch in chars:
            name = (
                getattr(ch, "name", "") or "").strip() or "(unnamed)"
            kind = (
                getattr(ch, "character_type", "") or "").strip()
            label = name + (f"  —  {kind}" if kind else "")
            items.append((label, _character_snippet(ch)))
        dlg = EntityPickerDialog(
            "Insert character details", items, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            snippet = dlg.selected_snippet()
            if snippet:
                self._append_to_plain_text(
                    self._character_details_edit, snippet)

    def _on_lookup_place(self) -> None:
        wb = getattr(self._project, "worldbuilding", None)
        places = list(getattr(wb, "places", []) or [])
        if not places:
            QMessageBox.information(
                self, "No places",
                "This project has no worldbuilding places yet — "
                "add them in the Worldbuilding tab first.")
            return
        from src.ui.image_generator_widget import (
            EntityPickerDialog, _place_snippet,
        )
        items = []
        for p in places:
            name = (
                getattr(p, "name", "") or "").strip() or "(unnamed)"
            items.append((name, _place_snippet(p)))
        dlg = EntityPickerDialog(
            "Insert setting details", items, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            snippet = dlg.selected_snippet()
            if snippet:
                self._append_to_plain_text(
                    self._setting_details_edit, snippet)

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
        # Commit form first so the picker's AI-highlight call sees
        # the writer's freshest scene context (especially the prompt
        # and description boxes the highlighter grounds against).
        self._commit_form_to_scene()
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
        self._actions_dirty = True
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
        # Commit the scene-level form first so the action editor's
        # prompt composition (which fuses scene baseline with per-
        # action overrides) sees the writer's freshest scene-level
        # character / setting / additional-instructions / prompt
        # edits — not whatever was last persisted via Save.
        self._commit_form_to_scene()
        # Pass the image-generator callback regardless of scene
        # mode — writers need preview renders in video mode too,
        # to lock in the action description before burning a video
        # clip. The mode only changes the slide-deck inclusion
        # semantics, not whether per-action images can be generated.
        dlg = SceneActionDialog(
            action=action,
            scene_mode=self._scene.mode,
            project=self._project,
            generate_image_callback=self._make_action_image_callback(),
            scene=self._scene,
            llm_provider=self._llm_provider,
            rag_provider=self._rag_provider,
            refine_action_prompt=self._refine_action_prompt_cb,
            upload_image_callback=self._upload_action_image_cb,
            parent=self)
        # Even on a Cancel the writer might have triggered an image
        # generation or an enrich, which mutate the action in
        # place — be conservative and mark dirty whenever the
        # sub-dialog actually opened.
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._actions_dirty = True
        else:
            # Sub-dialog enrich / image-gen / etc mutate even on
            # cancel — flag dirty so the host saves.
            self._actions_dirty = True
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
        self._actions_dirty = True
        self._refresh_actions_list()

    def _on_move_action(self, delta: int) -> None:
        action_id = self._selected_action_id()
        if action_id is None:
            return
        if self._scene.move_action(action_id, delta):
            self._actions_dirty = True
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
        # Commit form so the extractor's prompt grounding uses the
        # writer's freshest scene prompt + character / setting /
        # additional-instructions detail rather than the last-saved
        # snapshot.
        self._commit_form_to_scene()
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
        self._actions_dirty = True
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
                    self._actions_dirty = True
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
        self._scene.character_details = (
            self._character_details_edit.toPlainText().strip())
        self._scene.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        self._scene.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
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

    def _on_close_commit(self) -> None:
        """Close button — routes through ``reject()`` so the same
        commit logic applies whether the writer clicks Close, hits
        Esc, or closes the window via the OS chrome."""
        self.reject()

    def reject(self) -> None:
        """Override the default Qt reject so writers don't lose
        form-level edits when they reach for Close / Esc / X.
        Commits first, then signals Accepted so the host treats
        the dialog as a save."""
        try:
            self._commit_form_to_scene()
        except Exception as e:
            print(f"[scene_editor] close commit failed: {e}")
        # Accepted result so the host's contentChanged fires
        # unconditionally.
        self.done(QDialog.DialogCode.Accepted)

    def closeEvent(self, event) -> None:
        """Window-X / OS-quit — commit form changes first."""
        try:
            self._commit_form_to_scene()
            self.setResult(QDialog.DialogCode.Accepted)
        except Exception as e:
            print(f"[scene_editor] closeEvent commit failed: {e}")
        super().closeEvent(event)


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
