"""Top-level Video Studio widget.

Composes:
  * Toolbar — Add scene, AI-fill from chapter, backend picker, stitch
  * Canvas — node-graph view of scenes + hops
  * Side panel — backend info, character refs editor, install help

The widget receives a ``WriterProject`` via ``set_project`` from the
main window. Scene data is persisted on
``project.video_studio`` and saved through the normal project save
path; no separate save button.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QPointF, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout,
    QWidget,
)

from src.video_studio.ai_director import (
    auto_link_scenes_into_sequence,
    generate_scenes_for_chapter,
    rewrite_scene,
)
from src.video_studio.backends.base import (
    GenerationRequest, VideoBackend,
)
from src.video_studio.backends.image_base import (
    ImageBackend, ImageGenerationRequest,
)
from src.video_studio.backends.registry import (
    all_backends, all_image_backends, available_image_backends,
    default_backend, default_image_backend, get_backend,
    get_image_backend,
)
from src.video_studio.models import (
    Scene, VideoClip, VideoStudio,
)
from src.video_studio.stitcher import stitch_clips, ffmpeg_available
from src.video_studio import resource_manager
from src.ui.video_studio.scene_canvas import SceneCanvasView
from src.ui.video_studio.scene_editor import (
    AISceneGenerationDialog, SceneEditorDialog,
)


class VideoStudioWidget(QWidget):
    """Studio tab. Owns the canvas, side panel, and toolbar."""
    contentChanged = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._project: Optional[Any] = None
        self._llm_provider: Optional[Callable[[], Any]] = None
        self._rag_provider: Optional[Callable[[], Any]] = None
        self._current_backend: VideoBackend = default_backend()
        self._current_image_backend: ImageBackend = (
            default_image_backend())
        self._build_ui()
        # Honor Settings-stored backend choice on first open — even
        # before a project is loaded — so the indicator label and
        # any generate-before-set_project paths use the right
        # renderer.
        self._sync_backends_from_settings()
        self._refresh_backend_info()

    # ------------------------------------------------------------------
    # Public API — main window wires these
    # ------------------------------------------------------------------
    def set_project(self, project: Any) -> None:
        self._project = project
        if project is None:
            self._canvas.load_studio(VideoStudio())
            self._update_status("No project loaded.")
            return
        # Lazy attach a VideoStudio if the project's never had one.
        studio = getattr(project, "video_studio", None)
        if studio is None:
            studio = VideoStudio()
            try:
                project.video_studio = studio
            except Exception:
                pass
        self._canvas.load_studio(studio)
        # Backend selection comes from Settings → 🎨 Image
        # Generation; falls back to studio.backend_preference for
        # legacy projects that pre-date the Settings consolidation.
        self._sync_backends_from_settings()
        self._refresh_backend_info()
        self._load_styles_into_toolbar()
        self._update_status(
            f"{len(studio.scenes)} scene(s), {len(studio.hops)} hop(s).")

    def set_llm_provider(self, provider: Callable[[], Any]) -> None:
        """Inject a callable returning a configured LLMClient.
        Called lazily so the studio doesn't hold a stale client when
        the user changes models in Settings."""
        self._llm_provider = provider

    def set_rag_provider(
        self, provider: Callable[[], Any],
    ) -> None:
        self._rag_provider = provider

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Toolbar (split across two compact rows so it fits a
        # 1366×768 laptop without truncating button text). Row 1
        # holds the primary "what do I want to make?" controls; row
        # 2 holds backend settings + board management.
        # ──────────────────────────────────────────────────────────
        toolbar_row1 = QHBoxLayout()
        toolbar_row1.setSpacing(6)
        toolbar_row1.setContentsMargins(0, 0, 0, 0)

        self._add_scene_btn = QPushButton("➕ Add")
        self._add_scene_btn.setToolTip(
            "Drop a new empty scene on the canvas (at the first "
            "free grid cell).")
        self._add_scene_btn.clicked.connect(
            lambda: self._add_scene_at_first_free_cell())
        toolbar_row1.addWidget(self._add_scene_btn)

        self._ai_fill_btn = QPushButton("✨ AI-fill")
        self._ai_fill_btn.setToolTip(
            "Use the AI director to storyboard a chapter into a "
            "sequence of scenes. Uses graph-aware RAG for grounding.")
        self._ai_fill_btn.clicked.connect(self._ai_fill_from_chapter)
        toolbar_row1.addWidget(self._ai_fill_btn)

        toolbar_row1.addWidget(self._vline())

        # ---- Visual style (applies to every scene's render) ----
        # The combo + freeform description feed into every backend
        # prompt via ``_format_style_block`` so look-and-feel stays
        # consistent across the storyboard.
        toolbar_row1.addWidget(QLabel("Style:"))
        self._style_combo = QComboBox()
        from src.video_studio.models import STYLE_PRESETS as _SP
        for key, phrase in _SP:
            label = (phrase if not key
                     else key.replace("_", " ").title())
            self._style_combo.addItem(label, key)
        self._style_combo.setToolTip(
            "Pick a base visual style. The selected preset is folded "
            "into every backend prompt verbatim — the renderer sees "
            "the same style cue you do.")
        self._style_combo.currentIndexChanged.connect(
            self._on_style_preset_changed)
        # Cap the combo's pop-up width so a really long preset name
        # doesn't push the rest of the toolbar off-screen on a
        # 1366px display.
        self._style_combo.setMaximumWidth(180)
        toolbar_row1.addWidget(self._style_combo)
        self._style_description_edit = QLineEdit()
        self._style_description_edit.setPlaceholderText(
            "Embellish (rim-lit, neon, gritty…)")
        # Reduced from 260 → 180; the field expands to fill the row
        # via the QSizePolicy when extra space is available.
        self._style_description_edit.setMinimumWidth(160)
        self._style_description_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed)
        self._style_description_edit.setToolTip(
            "Freeform style notes — appended after the preset. Use "
            "this alone (with no preset) to describe the visual from "
            "scratch.")
        self._style_description_edit.editingFinished.connect(
            self._on_style_description_changed)
        toolbar_row1.addWidget(self._style_description_edit)

        # AI prompt-refinement toggle. When checked, the studio
        # routes the structured composed prompt through the LLM
        # (target-aware: image / video) before sending to the
        # backend. Disabled when no LLM is wired so the writer
        # sees the affordance and the reason.
        self._refine_prompt_check = QCheckBox("✨ AI refine")
        self._refine_prompt_check.setToolTip(
            "Ask the LLM to translate the structured prompt (style "
            "+ characters + setting + actions + directives) into "
            "proper image / video art-direction language before "
            "sending to the renderer. Falls back to the raw "
            "structured prompt on any LLM failure.")
        self._refine_prompt_check.toggled.connect(
            self._on_refine_toggle)
        toolbar_row1.addWidget(self._refine_prompt_check)

        toolbar_row1.addWidget(self._vline())

        self._stitch_btn = QPushButton("🎬 Stitch")
        self._stitch_btn.setToolTip(
            "Concatenate every scene's favorite clip into a single "
            "video, in the order their hops define (BFS from the "
            "first scene).")
        self._stitch_btn.clicked.connect(self._stitch_favorites)
        toolbar_row1.addWidget(self._stitch_btn)

        # Chapter-deck editor — arrange + transition + voiceover
        # the finished deck before exporting. Sits next to the
        # plain export button so writers who just want a quick MP4
        # don't have to wade through the editor first.
        self._slide_editor_btn = QPushButton("🎤 Slide editor")
        self._slide_editor_btn.setToolTip(
            "Open the chapter's action images as a slide editor: "
            "record audio per slide, pick transitions between "
            "slides, auto-fit times to the recording, paste a "
            "script and ✨ Suggest timings, group slides, then "
            "export as PowerPoint or MP4 with per-slide narration.")
        self._slide_editor_btn.clicked.connect(
            self._open_slide_editor)
        toolbar_row1.addWidget(self._slide_editor_btn)

        self._export_deck_btn = QPushButton("📑 Export deck")
        self._export_deck_btn.setToolTip(
            "Stitch every scene in a chapter (their chosen image / "
            "video / slide-deck output) into a single chapter-wide "
            "deck. Optionally adds a title card before each scene.")
        self._export_deck_btn.clicked.connect(
            self._export_chapter_deck)
        toolbar_row1.addWidget(self._export_deck_btn)

        toolbar_row1.addWidget(self._vline())

        self._toggle_side_btn = QPushButton("▶◀")
        self._toggle_side_btn.setToolTip(
            "Collapse / expand the right-hand info panel.")
        self._toggle_side_btn.setCheckable(True)
        self._toggle_side_btn.setChecked(True)  # panel starts open
        self._toggle_side_btn.clicked.connect(self._toggle_side_panel)
        toolbar_row1.addWidget(self._toggle_side_btn)

        root.addLayout(toolbar_row1)

        # ── Toolbar row 2 — backend indicator + board management ─
        # Backend selection now lives in Settings → Image
        # Generation → "Video Studio Backends" so writers
        # configure both the image and video processor in one
        # place instead of duplicating it on the studio toolbar.
        # Row 2 surfaces the current selection as a read-only
        # label and offers a one-click "Install…" button for the
        # currently-selected video backend.
        toolbar_row2 = QHBoxLayout()
        toolbar_row2.setSpacing(6)
        toolbar_row2.setContentsMargins(0, 0, 0, 0)

        self._backends_label = QLabel("Backends: …")
        self._backends_label.setStyleSheet(
            "color: #475569; font-size: 11px;")
        self._backends_label.setToolTip(
            "Image and video backends are configured in "
            "Settings → 🎨 Image Generation → Video Studio "
            "Backends. Click 'Install…' below to install the "
            "current selection if it isn't ready yet.")
        toolbar_row2.addWidget(self._backends_label)

        self._install_help_btn = QPushButton("Install…")
        self._install_help_btn.setToolTip(
            "Install the currently-selected video backend in-app, "
            "or read the manual install instructions if it doesn't "
            "support automated install. Change the backend "
            "selection in Settings → 🎨 Image Generation.")
        self._install_help_btn.clicked.connect(
            self._show_install_help)
        toolbar_row2.addWidget(self._install_help_btn)

        toolbar_row2.addWidget(self._vline())

        # ---- Storyboard board management ----
        self._save_board_btn = QPushButton("Save")
        self._save_board_btn.setToolTip(
            "Export the current storyboard (scenes, hops, character "
            "references, narration metadata) as a standalone JSON "
            "file. Reusable across projects.")
        self._save_board_btn.clicked.connect(self._save_storyboard)
        toolbar_row2.addWidget(self._save_board_btn)

        self._load_board_btn = QPushButton("Load")
        self._load_board_btn.setToolTip(
            "Load a storyboard JSON file, replacing the current "
            "board. Asks for confirmation before discarding any "
            "existing scenes.")
        self._load_board_btn.clicked.connect(self._load_storyboard)
        toolbar_row2.addWidget(self._load_board_btn)

        self._arrange_btn = QPushButton("Arrange")
        self._arrange_btn.setToolTip(
            "Re-flow scene cards into a tidy grid. Order follows "
            "the hops (topological) when possible; falls back to "
            "creation order on cycles.")
        self._arrange_btn.clicked.connect(self._auto_arrange_board)
        toolbar_row2.addWidget(self._arrange_btn)

        self._clear_board_btn = QPushButton("Clear")
        self._clear_board_btn.setToolTip(
            "Delete every scene and hop on the board. Character "
            "references and backend preferences are kept.")
        self._clear_board_btn.clicked.connect(self._clear_board)
        toolbar_row2.addWidget(self._clear_board_btn)

        self._fit_view_btn = QPushButton("Fit")
        self._fit_view_btn.setToolTip(
            "Zoom and pan so the whole board fits in view. "
            "Ctrl + mouse wheel zooms manually.")
        self._fit_view_btn.clicked.connect(self._fit_canvas_to_view)
        toolbar_row2.addWidget(self._fit_view_btn)

        toolbar_row2.addStretch()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #475569; font-size: 11px;")
        self._status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred)
        # Cap status text width so a long status doesn't elbow row 2
        # widgets off-screen — it ellipsizes via the layout's
        # default behavior when the label runs out of room.
        self._status_label.setMinimumWidth(0)
        toolbar_row2.addWidget(self._status_label, stretch=1)
        root.addLayout(toolbar_row2)

        # ── Splitter: canvas (left) + side panel (right) ──────────
        # Collapsible right panel so the user can hide tips/backend
        # info and get more canvas real-estate. The toggle button
        # added in the toolbar above snaps the panel between its
        # last-known width and zero; the splitter handle still lets
        # them drag manually.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        self._splitter = splitter
        # Remembered width for the right panel — used to restore the
        # previous size after a toggle-collapse.
        self._side_panel_last_width = 320

        # Canvas
        self._canvas = SceneCanvasView()
        self._canvas.sceneEditRequested.connect(self._open_editor)
        self._canvas.addSceneRequested.connect(self._add_scene_at_pos)
        self._canvas.connectRequested.connect(self._connect_scenes)
        self._canvas.deleteSceneRequested.connect(self._delete_scene)
        self._canvas.manageHopsRequested.connect(
            self._open_hop_manager)
        self._canvas.generateClipRequested.connect(
            self._generate_clip_for_scene)
        self._canvas.generateImageRequested.connect(
            self._generate_image_for_scene)
        self._canvas.generateSlideDeckRequested.connect(
            self._generate_slide_deck_for_scene)
        self._canvas.stitchSlideDeckRequested.connect(
            self._stitch_slide_deck_for_scene)
        self._canvas.openLastClipRequested.connect(
            self._open_latest_clip_for_scene)
        self._canvas.openOutputFolderRequested.connect(
            self._open_output_folder_for_scene)
        self._canvas.copyPromptRequested.connect(
            self._copy_prompt_for_scene)
        self._canvas.uploadClipRequested.connect(
            self._upload_clip_from_canvas)
        self._canvas.switchModeRequested.connect(
            self._switch_scene_mode)
        self._canvas.sceneMoved.connect(
            lambda *_: self.contentChanged.emit())
        splitter.addWidget(self._canvas)

        # Side panel
        side = QWidget()
        side.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(4, 4, 4, 4)
        side_layout.setSpacing(6)

        # Backend status — kept minimal. The label is already in the
        # toolbar dropdown, so we don't echo it big-and-bold here.
        # What this block contributes is a one-liner status (with
        # the placeholder situation called out clearly) plus the
        # backend's description for users who want to know what
        # they picked.
        info_box = QGroupBox("Backend status")
        info_layout = QVBoxLayout(info_box)
        self._backend_status = QLabel("")
        self._backend_status.setWordWrap(True)
        self._backend_status.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addWidget(self._backend_status)
        self._backend_desc = QLabel("")
        self._backend_desc.setWordWrap(True)
        self._backend_desc.setStyleSheet("color: #475569;")
        info_layout.addWidget(self._backend_desc)
        side_layout.addWidget(info_box)

        tips_box = QGroupBox("Hints")
        tips_layout = QVBoxLayout(tips_box)
        tips = QLabel(
            "• Drag cards on the canvas to reorder.\n"
            "• Double-click a card to edit name / description / prompt.\n"
            "• Right-click a card: connect, generate, or delete.\n"
            "• Right-click the empty canvas: add a scene at that cell.\n"
            "• Use 'AI-fill from chapter' to storyboard automatically.\n"
            "• Mark a clip 'favorite' inside a card — the stitcher "
            "uses favorites when building the final video.\n"
            "• Placeholder clips are 0 bytes; install a real backend "
            "to render actual video.")
        tips.setWordWrap(True)
        tips.setStyleSheet("color: #334155;")
        tips_layout.addWidget(tips)
        side_layout.addWidget(tips_box)

        side_layout.addStretch()
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 320])
        root.addWidget(splitter, stretch=1)

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # ------------------------------------------------------------------
    # Studio access
    # ------------------------------------------------------------------
    def _studio(self) -> Optional[VideoStudio]:
        return (getattr(self._project, "video_studio", None)
                if self._project is not None else None)

    def _update_status(self, text: str) -> None:
        self._status_label.setText(text)

    # ------------------------------------------------------------------
    # Backend selection — driven by Settings → 🎨 Image Generation
    # ------------------------------------------------------------------
    def _sync_backends_from_settings(self) -> None:
        """Pull both backends from ``GenAIConfig`` and update the
        in-memory selections.

        Video: per-project preference → ``video_studio_video_backend``
        setting → registry default.

        Image: ALWAYS the unified ``ConfiguredImageBackend`` when a
        model is set in ``image_model_id``; otherwise placeholder.
        Image generation has been consolidated to flow through the
        same model the Visuals tab uses, so there's no separate
        studio-specific image backend selection any more.
        """
        try:
            from src.config.genai_config import get_genai_config
            settings = get_genai_config().get_settings()
        except Exception:
            settings = {}
        studio = self._studio()
        # Video backend.
        vid_name = (
            settings.get("video_studio_video_backend")
            or (getattr(studio, "backend_preference", "")
                if studio is not None else "")
            or "")
        vid = get_backend(vid_name) if vid_name else None
        if vid is not None:
            self._current_backend = vid
        # Image backend — unified through ConfiguredImageBackend.
        configured = get_image_backend("configured")
        if (configured is not None
                and configured.is_installed()):
            self._current_image_backend = configured
        else:
            # No model set in Settings → fall back to placeholder so
            # the studio still produces valid (if black-frame)
            # output and the writer sees a clear "no model
            # configured" status.
            placeholder = get_image_backend("placeholder_image")
            if placeholder is not None:
                self._current_image_backend = placeholder

    def _on_style_preset_changed(self, _index: int) -> None:
        studio = self._studio()
        if studio is None:
            return
        studio.style_preset = (
            self._style_combo.currentData() or "")
        self.contentChanged.emit()

    def _on_style_description_changed(self) -> None:
        studio = self._studio()
        if studio is None:
            return
        studio.style_description = (
            self._style_description_edit.text().strip())
        self.contentChanged.emit()

    def _load_styles_into_toolbar(self) -> None:
        """Mirror the current studio's style fields into the
        toolbar controls. Called whenever a project / board loads."""
        studio = self._studio()
        if studio is None:
            return
        # Block signals during programmatic load so we don't fire
        # contentChanged in a loop.
        self._style_combo.blockSignals(True)
        idx = self._style_combo.findData(
            getattr(studio, "style_preset", "") or "")
        if idx >= 0:
            self._style_combo.setCurrentIndex(idx)
        self._style_combo.blockSignals(False)
        self._style_description_edit.blockSignals(True)
        self._style_description_edit.setText(
            getattr(studio, "style_description", "") or "")
        self._style_description_edit.blockSignals(False)
        # Refine toggle — checkbox state mirrors the studio's
        # ``use_ai_prompt_refinement`` field, and we disable when
        # no LLM provider is wired so the writer sees why it isn't
        # firing.
        self._refine_prompt_check.blockSignals(True)
        self._refine_prompt_check.setChecked(
            bool(getattr(
                studio, "use_ai_prompt_refinement", True)))
        self._refine_prompt_check.blockSignals(False)
        llm_available = self._llm_provider is not None
        self._refine_prompt_check.setEnabled(llm_available)
        if not llm_available:
            self._refine_prompt_check.setToolTip(
                "Ask the LLM to translate the structured prompt "
                "into proper image / video art-direction language. "
                "Disabled until an LLM is configured in Settings.")

    def _on_refine_toggle(self, checked: bool) -> None:
        studio = self._studio()
        if studio is None:
            return
        studio.use_ai_prompt_refinement = bool(checked)
        self.contentChanged.emit()

    def _compose_action_prompt(self, scene: Scene, action) -> str:
        """Build the structured per-action image prompt the
        backend would see (before optional AI refinement). Same
        composition as ``_generate_image_for_action`` — factored
        out so the action editor's '✨ Preview AI-refined' button
        sees the identical input."""
        action_prompt = (
            f"{(scene.prompt or '').strip()}. "
            f"Action: {getattr(action, 'name', '')}. "
            f"{getattr(action, 'description', '')}").strip()
        sc_char = (
            getattr(scene, "character_details", "") or "").strip()
        if sc_char:
            action_prompt += f" Characters: {sc_char}."
        a_char = (
            getattr(action, "character_details", "") or "").strip()
        if a_char:
            action_prompt += f" Characters (action): {a_char}."
        sc_setting = (
            getattr(scene, "setting_details", "") or "").strip()
        if sc_setting:
            action_prompt += f" Setting: {sc_setting}."
        a_setting = (
            getattr(action, "setting_details", "") or "").strip()
        if a_setting:
            action_prompt += f" Setting (action): {a_setting}."
        scenery = getattr(action, "scenery_details", "") or ""
        if scenery:
            action_prompt += f" Scenery: {scenery}."
        sc_extra = (
            getattr(scene, "additional_instructions", "")
            or "").strip()
        if sc_extra:
            action_prompt += (
                f" Additional instructions: {sc_extra}.")
        a_extra = (
            getattr(action, "additional_instructions", "")
            or "").strip()
        if a_extra:
            action_prompt += (
                f" Additional instructions (action): {a_extra}.")
        if getattr(action, "prose_excerpt", ""):
            action_prompt += f" Prose: {action.prose_excerpt}"
        style_block = self._format_style_block()
        if style_block:
            action_prompt = f"{style_block} {action_prompt}"
        return action_prompt

    def _refine_action_prompt_for_preview(
        self, scene: Scene, action,
    ) -> str:
        """Compose + refine the per-action prompt for the action
        editor's preview button. Always target='image'."""
        composed = self._compose_action_prompt(scene, action)
        if not composed.strip() or self._llm_provider is None:
            return composed
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            return composed
        from src.video_studio.ai_director import (
            refine_visual_prompt,
        )
        return refine_visual_prompt(
            composed_prompt=composed, target="image", llm=llm)

    def _refine_scene_prompt_for_preview(
        self, scene: Scene, target: str,
    ) -> str:
        """Public refinement adapter for the scene editor's
        '✨ Preview AI-refined prompt' button. Composes the
        structured prompt and asks the LLM to refine — bypasses
        the studio's enable toggle so the writer can preview the
        refined version even when the auto-refine is off."""
        composed = self._compose_scene_prompt(scene)
        if not composed.strip() or self._llm_provider is None:
            return composed
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            return composed
        from src.video_studio.ai_director import (
            refine_visual_prompt,
        )
        return refine_visual_prompt(
            composed_prompt=composed, target=target, llm=llm)

    def _refine_prompt_if_enabled(
        self, composed: str, target: str,
    ) -> str:
        """Optionally pass ``composed`` through
        ``refine_visual_prompt`` based on the studio toggle + LLM
        availability. Always returns SOMETHING usable — the raw
        composed prompt when refinement is off, no LLM is wired,
        or the LLM call fails."""
        if not composed or not composed.strip():
            return composed
        studio = self._studio()
        if (studio is None
                or not getattr(
                    studio, "use_ai_prompt_refinement", True)):
            return composed
        if self._llm_provider is None:
            return composed
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            return composed
        from src.video_studio.ai_director import (
            refine_visual_prompt,
        )
        return refine_visual_prompt(
            composed_prompt=composed,
            target=target, llm=llm)

    def _compose_scene_prompt(self, scene: Scene) -> str:
        """Build the prompt the video backend WOULD see for this
        scene — same composition as ``_generate_clip_for_scene``,
        factored out so the writer can copy / preview it without
        actually running the backend.

        Layout: ``<style block>\\n\\n<scene.prompt>\\n\\nAction
        sequence:\\n1. ...``. Style block omitted when neither a
        preset nor description nor genre is set. Action block
        omitted when the scene has no actions.
        """
        base = (scene.prompt or "").strip()
        # Fold scene-level character + setting detail BEFORE the
        # action sequence so the backend sees the baseline before
        # the per-beat overrides. Editorial detail only — backends
        # are free to interpret style + composition themselves.
        scene_char = (
            getattr(scene, "character_details", "") or "").strip()
        scene_setting = (
            getattr(scene, "setting_details", "") or "").strip()
        scene_extra = (
            getattr(scene, "additional_instructions", "")
            or "").strip()
        extras: list = []
        if scene_char:
            extras.append(f"Characters: {scene_char}")
        if scene_setting:
            extras.append(f"Setting: {scene_setting}")
        if scene_extra:
            extras.append(f"Additional instructions: {scene_extra}")
        if extras:
            base = (
                f"{base}\n\n" + "\n\n".join(extras)
                if base else "\n\n".join(extras))
        if scene.actions:
            beats: list = []
            for idx, a in enumerate(scene.actions, start=1):
                line = f"{idx}. {a.name}"
                if a.description:
                    line += f" — {a.description}"
                # Per-action overrides on the same baseline fields.
                a_char = (
                    getattr(a, "character_details", "") or "").strip()
                if a_char:
                    line += f" Characters: {a_char}"
                a_setting = (
                    getattr(a, "setting_details", "") or "").strip()
                if a_setting:
                    line += f" Setting: {a_setting}"
                if a.scenery_details:
                    line += f" Scenery: {a.scenery_details}"
                a_extra = (
                    getattr(a, "additional_instructions", "")
                    or "").strip()
                if a_extra:
                    line += f" Instructions: {a_extra}"
                if a.prose_excerpt:
                    line += f" Prose: {a.prose_excerpt}"
                beats.append(line)
            base = (
                f"{base}\n\n"
                f"Action sequence:\n" + "\n".join(beats))
        style_block = self._format_style_block()
        if style_block:
            base = f"{style_block}\n\n{base}"
        return base

    def _copy_prompt_for_scene(self, scene_id: str) -> None:
        """Copy the assembled generation prompt to the clipboard so
        the writer can paste it into another tool, share it for
        review, or just verify what the backend actually sees."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        text = self._compose_scene_prompt(scene)
        if not text.strip():
            QMessageBox.information(
                self, "Empty prompt",
                "This scene has no prompt yet. Fill in the scene's "
                "prompt (and optionally actions / style) first.")
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        char_count = len(text)
        line_count = text.count("\n") + 1
        self._update_status(
            f"Copied {char_count} chars / {line_count} line(s) of "
            f"prompt for '{scene.name}' to clipboard.")

    def _format_style_block(self) -> str:
        """Render the style + genre block that gets folded into
        every backend prompt. Empty string when neither side has
        anything to say. Composed as a single line so backends with
        short context windows don't waste tokens on whitespace.
        """
        studio = self._studio()
        if studio is None:
            return ""
        from src.video_studio.models import style_preset_phrase
        preset_phrase = style_preset_phrase(
            getattr(studio, "style_preset", "") or "")
        custom = (
            getattr(studio, "style_description", "") or "").strip()
        # Pull genre from the project's prose profile when available.
        genre = ""
        if self._project is not None:
            pp = getattr(self._project, "prose_profile", None)
            if pp is not None:
                genre = (getattr(pp, "genre", "") or "").strip()
        parts: list = []
        style_bits: list = []
        if preset_phrase:
            style_bits.append(preset_phrase)
        if custom:
            style_bits.append(custom)
        if style_bits:
            parts.append("Style: " + "; ".join(style_bits) + ".")
        if genre:
            parts.append(
                f"Genre: {genre}. Visuals MUST match this genre's "
                f"conventions.")
        return " ".join(parts)

    def _refresh_backend_info(self) -> None:
        b = self._current_backend
        installed = b.is_installed()
        # The placeholder backend is technically "installed" but
        # produces no video — saying "Installed." for it is
        # misleading. Special-case the message so the user
        # immediately understands why generation would create
        # 0-byte clip files. Other backends get the green/red
        # install state.
        if b.name == "placeholder":
            self._backend_status.setText(
                "<span style='color:#b45309'>"
                "<b>No real renderer selected.</b> Generate will "
                "create stub clips (0 bytes) so the studio flow "
                "works end-to-end, but they will not play. "
                "Pick another backend in Settings → 🎨 Image "
                "Generation → Video Studio Backends."
                "</span>")
        elif installed:
            self._backend_status.setText(
                "<span style='color:#15803d'>"
                "Installed and ready.</span>")
        else:
            self._backend_status.setText(
                "<span style='color:#b91c1c'>"
                "Not installed — generate will fail. Click "
                "<b>Install…</b> on the toolbar to set up."
                "</span>")
        self._backend_desc.setText(b.description)
        self._install_help_btn.setEnabled(not installed
                                          or b.name != "placeholder")
        # Compact toolbar indicator: "Video: <vid> · Image: <img>".
        img_label = (
            getattr(self._current_image_backend, "label",
                    "Image backend")
            if self._current_image_backend is not None else
            "(none)")
        vid_check = "✓" if installed else "⚠"
        img_check = (
            "✓" if (self._current_image_backend is not None
                    and self._current_image_backend.is_installed())
            else "⚠")
        self._backends_label.setText(
            f"<b>Backends</b> &nbsp;Video: {b.label} {vid_check} "
            f"&nbsp;·&nbsp; Image: {img_label} {img_check}")

    def _toggle_side_panel(self) -> None:
        """Snap the right panel between its remembered width and 0.

        Manual splitter drags still work — the toggle button just
        provides a single-click affordance. We remember the most
        recent non-zero width so a toggle-back restores the panel
        to wherever the user had it sized."""
        sizes = self._splitter.sizes()
        if len(sizes) < 2:
            return
        canvas_w, side_w = sizes[0], sizes[1]
        total = canvas_w + side_w
        if self._toggle_side_btn.isChecked():
            # Was just toggled ON → expand panel back to last width.
            target = self._side_panel_last_width or 320
            self._splitter.setSizes(
                [max(200, total - target), target])
        else:
            # Was just toggled OFF → remember + collapse.
            if side_w > 0:
                self._side_panel_last_width = side_w
            self._splitter.setSizes([total, 0])

    def _show_install_help(self) -> None:
        """Open the install dialog. When the backend supports
        ``install_steps()``, the user gets a runnable installer;
        otherwise they get text-only manual steps."""
        b = self._current_backend
        from src.ui.video_studio.install_dialog import InstallDialog
        dlg = InstallDialog(b, parent=self)
        dlg.exec()
        # Re-check install state after the user is done — backend
        # may have just become available. The Settings dialog reads
        # backend install state at open time too, so the writer's
        # next trip there shows the freshest ✓ badges.
        self._refresh_backend_info()

    # ------------------------------------------------------------------
    # Scene CRUD
    # ------------------------------------------------------------------
    def _add_scene_at_first_free_cell(self) -> None:
        studio = self._studio()
        if studio is None:
            QMessageBox.information(
                self, "No project",
                "Open or create a project first.")
            return
        sc = Scene(name=f"Scene {len(studio.scenes) + 1}")
        studio.add_scene(sc)
        self._canvas.refresh_all()
        # Offer to inherit hops from a recently-deleted scene before
        # opening the editor so the writer sees the question first.
        self._offer_rebind_orphaned_hops(sc)
        self._open_editor(sc.id)
        self.contentChanged.emit()

    def _add_scene_at_pos(self, scene_pos: QPointF) -> None:
        studio = self._studio()
        if studio is None:
            return
        from src.ui.video_studio.scene_canvas import (
            SceneCanvasView as _Cv,
        )
        col, row = _Cv._pixel_to_cell(scene_pos)
        sc = Scene(name=f"Scene {len(studio.scenes) + 1}",
                   grid_col=max(col, 0), grid_row=max(row, 0))
        studio.add_scene(sc)
        self._canvas.refresh_all()
        # If a previously-deleted scene lived at this cell, offer
        # to reattach its hops — the common "swap one card for
        # another mid-chain" workflow.
        self._offer_rebind_orphaned_hops(sc)
        self._open_editor(sc.id)
        self.contentChanged.emit()

    def _delete_scene(self, scene_id: str) -> None:
        studio = self._studio()
        if studio is None:
            return
        s = studio.get_scene(scene_id)
        if s is None:
            return
        reply = QMessageBox.question(
            self, "Delete scene?",
            f"Remove '{s.name or 'this scene'}' and all its "
            f"{len(s.clips)} clip(s)? Clip files on disk will also "
            f"be deleted.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Capture the hops that touched this scene BEFORE delete
        # cascades them away. Stash on a session-scoped memory
        # keyed by (col, row, name) so the writer can re-bind them
        # to a fresh scene placed at the same spot — a common flow
        # when a beat gets reworked into a new card.
        from time import time as _time
        hops_in = [
            (h.from_scene_id, h.label) for h in studio.hops
            if h.to_scene_id == scene_id]
        hops_out = [
            (h.to_scene_id, h.label) for h in studio.hops
            if h.from_scene_id == scene_id]
        if hops_in or hops_out:
            if not hasattr(self, "_orphaned_hops_memory"):
                self._orphaned_hops_memory: list = []
            self._orphaned_hops_memory.append({
                "deleted_at": _time(),
                "col": s.grid_col,
                "row": s.grid_row,
                "name": s.name or "",
                "hops_in": hops_in,
                "hops_out": hops_out,
            })
            # Cap memory so a long session doesn't accumulate
            # forever — 30 most recent deletions is plenty.
            self._orphaned_hops_memory = (
                self._orphaned_hops_memory[-30:])
        # Clean clip files first; ignore failures so a deleted-on-
        # disk clip doesn't block the scene removal.
        for c in s.clips:
            for path_str in (c.file_path, c.sidecar_path):
                if not path_str:
                    continue
                try:
                    p = Path(path_str)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    print(f"[video_studio] clip cleanup: {e}")
        studio.delete_scene(scene_id)
        self._canvas.refresh_all()
        self.contentChanged.emit()

    def _offer_rebind_orphaned_hops(self, new_scene) -> None:
        """When a new scene lands on the canvas, see if a recently-
        deleted scene matches its grid cell (or was deleted within
        the last 60 s) and ask the writer whether to re-attach the
        old hops to the new scene. This makes the swap-a-card-mid-
        chain workflow painless — delete the old beat, add the new
        beat, click Yes to keep the predecessor/successor links.
        """
        if not getattr(self, "_orphaned_hops_memory", None):
            return
        from time import time as _time
        now = _time()
        studio = self._studio()
        if studio is None:
            return
        # Prefer same-cell match; fall back to most-recent within 60 s.
        same_cell = [
            m for m in self._orphaned_hops_memory
            if m["col"] == new_scene.grid_col
            and m["row"] == new_scene.grid_row]
        if same_cell:
            memory = same_cell[-1]
        else:
            recent = [
                m for m in self._orphaned_hops_memory
                if now - m["deleted_at"] <= 60.0]
            if not recent:
                return
            memory = recent[-1]
        # Filter the remembered hops down to ones whose other
        # endpoint still exists.
        live_in = [
            (other, label) for other, label in memory["hops_in"]
            if studio.get_scene(other) is not None]
        live_out = [
            (other, label) for other, label in memory["hops_out"]
            if studio.get_scene(other) is not None]
        n_in = len(live_in)
        n_out = len(live_out)
        if not (n_in or n_out):
            return
        prev_name = memory["name"] or "the previous scene"
        msg = (
            f"'{prev_name}' was just deleted with "
            f"{n_in} incoming and {n_out} outgoing hop"
            + ("s" if (n_in + n_out) != 1 else "")
            + ".\n\nReattach those hops to "
            f"'{new_scene.name or 'this new scene'}'?")
        reply = QMessageBox.question(
            self, "Inherit hops from deleted scene?", msg)
        if reply != QMessageBox.StandardButton.Yes:
            return
        added = 0
        for other_id, label in live_in:
            if studio.add_hop(other_id, new_scene.id, label):
                added += 1
        for other_id, label in live_out:
            if studio.add_hop(new_scene.id, other_id, label):
                added += 1
        # Drop the memory entry so a second new scene doesn't get
        # offered the same hops.
        self._orphaned_hops_memory = [
            m for m in self._orphaned_hops_memory
            if m is not memory]
        self._canvas.refresh_all()
        self.contentChanged.emit()
        self._update_status(
            f"Reattached {added} hop"
            + ("s" if added != 1 else "")
            + f" to '{new_scene.name}'.")

    def _open_hop_manager(self, scene_id: str) -> None:
        """Open the list-based hop editor for one scene. The dialog
        mutates the studio in place; we just refresh + emit on close
        so the canvas redraws hops and autosave runs."""
        studio = self._studio()
        if studio is None:
            return
        from src.ui.video_studio.hop_manager_dialog import (
            HopManagerDialog,
        )
        before = len(studio.hops)
        dlg = HopManagerDialog(studio, scene_id, parent=self)
        dlg.exec()
        if len(studio.hops) != before:
            self._canvas.refresh_all()
            self.contentChanged.emit()

    def _connect_scenes(self, from_id: str, to_id: str) -> None:
        studio = self._studio()
        if studio is None:
            return
        hop = studio.add_hop(from_id, to_id, label="next")
        if hop is None:
            QMessageBox.information(
                self, "No hop added",
                "That connection couldn't be created (self-loop or "
                "missing scene).")
            return
        self._canvas.refresh_all()
        self.contentChanged.emit()

    # ------------------------------------------------------------------
    # Scene editor + AI rewrite
    # ------------------------------------------------------------------
    def _open_editor(self, scene_id: str) -> None:
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        rewrite_cb = self._make_rewrite_callback()
        # Hand the editor the live project + project_dir + LLM
        # provider so the narration UX can pull chapter prose, store
        # audio files in the right per-project place, and use the
        # LLM for AI-highlight + action-summary inside the chapter
        # text picker.
        dlg = SceneEditorDialog(
            scene,
            rewrite_callback=rewrite_cb,
            project=self._project,
            project_dir=getattr(self._project, "project_path", None),
            llm_provider=self._llm_provider,
            rag_provider=self._rag_provider,
            parent=self,
        )
        # Wire the per-action image generator so the editor can ask
        # the current image backend for slide-deck images. The
        # callback signature is callable(SceneAction) →
        # Optional[ActionImage] — see
        # ``_generate_image_for_action`` for the implementation.
        dlg.set_image_generator(
            lambda action, scene=scene: (
                self._generate_image_for_action(scene, action)))
        # Surface the same scene-level generation actions that live
        # on the canvas card's right-click menu inside the editor,
        # so the writer can render + iterate without closing the
        # dialog. The handlers below take a Scene and bounce to the
        # existing scene_id-based pipelines (which run resource
        # checks, mutate scene.clips, refresh the card, etc.).
        dlg.set_generation_callbacks(
            generate_video=(
                lambda s: self._generate_clip_for_scene(s.id)),
            generate_image=(
                lambda s: self._generate_image_for_scene(s.id)),
            stitch_slide_deck=(
                lambda s: self._stitch_slide_deck_for_scene(s.id)),
            open_output_folder=(
                lambda s: self._open_output_folder_for_scene(s.id)),
            compose_prompt=self._compose_scene_prompt,
            refine_prompt=self._refine_scene_prompt_for_preview,
            refine_action_prompt=(
                self._refine_action_prompt_for_preview),
            upload_action_image=self._upload_image_for_action,
            upload_scene_clip=self._upload_clip_for_scene,
        )
        accepted = (dlg.exec() == QDialog.DialogCode.Accepted)
        # ``actions_dirty()`` covers the case where a sub-dialog
        # (per-action editor, AI extract, image generation, slide-
        # deck stitch) mutated the live scene and the writer then
        # Cancels the outer dialog: contentChanged still needs to
        # fire so the project autosave flushes those mutations to
        # disk. Otherwise the next reload would read the stale
        # state and the action edits would silently disappear.
        if accepted or dlg.actions_dirty():
            self._canvas.refresh_scene_card(scene_id)
            # Push any per-action favorite-image changes the
            # writer made inside the scene editor (or its
            # nested action dialog) into the live slide decks.
            # Without this, a deck that was seeded from this
            # scene's actions keeps showing the OLD favorite
            # until the writer manually re-syncs.
            self._propagate_action_favorites_to_slide_decks()
            self.contentChanged.emit()

    def _make_rewrite_callback(self) -> Optional[
            Callable[[Scene, str], Scene]]:
        if self._llm_provider is None:
            return None
        llm = self._llm_provider()
        if llm is None:
            return None
        rag = self._rag_provider() if self._rag_provider else None
        project = self._project

        def _cb(scene: Scene, instruction: str) -> Scene:
            chapter = self._find_chapter_for_scene(scene)
            return rewrite_scene(
                scene, chapter, project, llm, rag, instruction)
        return _cb

    def _find_chapter_for_scene(self, scene: Scene):
        if self._project is None:
            return None
        if not scene.chapter_id:
            return None
        ms = getattr(self._project, "manuscript", None)
        chapters = getattr(ms, "chapters", None) if ms else None
        if not chapters:
            return None
        for ch in chapters:
            if getattr(ch, "id", "") == scene.chapter_id:
                return ch
        return None

    # ------------------------------------------------------------------
    # AI fill from chapter
    # ------------------------------------------------------------------
    def _ai_fill_from_chapter(self) -> None:
        if self._project is None:
            QMessageBox.information(
                self, "No project",
                "Open or create a project first.")
            return
        ms = getattr(self._project, "manuscript", None)
        chapters = list(getattr(ms, "chapters", []) or []) if ms else []
        if not chapters:
            QMessageBox.information(
                self, "No chapters",
                "This project has no chapters to storyboard.")
            return
        studio = self._studio()
        default_dur = (
            studio.default_duration_seconds if studio else 8.0)
        dlg = AISceneGenerationDialog(
            chapters, default_count=6,
            default_duration=default_dur,
            project=self._project,
            parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chapter = dlg.selected_chapter()
        count = dlg.scene_count()
        duration = dlg.duration_seconds()
        auto_link = dlg.auto_link()
        use_planned = dlg.use_planned_beats()
        llm = self._llm_provider() if self._llm_provider else None
        rag = self._rag_provider() if self._rag_provider else None

        # Pre-fetch the planned beat count for the status line so the
        # user sees "Generating from chapter's 5 planned beats" vs.
        # "Generating 6 scenes from prose" — accurate either way.
        from src.video_studio.ai_director import (
            detect_planned_beats_count,
        )
        planned_n = detect_planned_beats_count(
            chapter, self._project) if use_planned else 0
        if planned_n > 0:
            self._update_status(
                f"Following {planned_n} planned beat(s) from "
                f"'{getattr(chapter, 'title', 'chapter')}'…")
        else:
            self._update_status(
                f"Generating {count} scene(s) from "
                f"'{getattr(chapter, 'title', 'chapter')}'…")
        scenes = generate_scenes_for_chapter(
            chapter=chapter,
            project=self._project,
            llm=llm,
            rag_system=rag,
            scene_count=count,
            default_duration=duration,
            prefer_planned_beats=use_planned,
        )
        if not scenes:
            QMessageBox.warning(
                self, "Generation failed",
                "Couldn't produce scenes from this chapter. Check "
                "that the chapter has content and that an LLM is "
                "configured if you want AI direction.")
            self._update_status("")
            return
        # Drop on canvas — first row, then wrap.
        cols = studio.grid_cols if studio else 6
        for i, sc in enumerate(scenes):
            sc.grid_col = i % cols
            sc.grid_row = i // cols
            studio.add_scene(sc)
        if auto_link:
            auto_link_scenes_into_sequence(studio, scenes)
        self._canvas.refresh_all()
        self.contentChanged.emit()
        self._update_status(
            f"Added {len(scenes)} scene(s).")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def _generate_clip_for_scene(self, scene_id: str) -> None:
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        backend = self._current_backend
        if not backend.is_installed():
            QMessageBox.warning(
                self, "Backend not installed",
                f"{backend.label} isn't ready. Use the placeholder "
                f"backend or install this one — see 'Install help'.")
            return
        if not scene.prompt.strip():
            QMessageBox.information(
                self, "Empty prompt",
                "This scene has no prompt yet. Open the editor and "
                "add one (or ask the AI to write it).")
            return

        # Pre-flight RAM / VRAM check. Backends declare what they
        # need; if there isn't headroom we offer to drop the local
        # LLM / shared HF model cache and re-check. This is the
        # main guard against OOM during a multi-minute generation.
        if not self._ensure_resources_for(backend):
            return

        out_dir = self._scene_output_dir(scene)
        out_dir.mkdir(parents=True, exist_ok=True)
        clip_count = len(scene.clips)
        out_path = out_dir / (
            f"clip_{clip_count + 1:03d}_{backend.name}.mp4")

        # Gather grounding data for the request.
        char_refs_payload = []
        for ref_name in scene.character_refs:
            ref = studio.get_character_reference(ref_name)
            if ref:
                char_refs_payload.append({
                    "name": ref.name,
                    "appearance_prompt": ref.appearance_prompt,
                    "seed": ref.seed,
                })
            else:
                char_refs_payload.append({
                    "name": ref_name,
                    "appearance_prompt": "",
                    "seed": None,
                })

        # Honor the scene's target duration when set (overrides the
        # studio default); falls back to studio.default_duration_seconds
        # via Scene.effective_duration.
        effective_duration = scene.effective_duration(
            studio.default_duration_seconds)
        # Style + actions + scene prompt are all assembled the same
        # way the "Copy generation prompt" affordance shows them —
        # one helper keeps preview and runtime in sync.
        full_prompt = self._compose_scene_prompt(scene)
        # Optional AI refinement: translate structured detail into
        # proper video art-direction language before the backend
        # sees it. Falls back to the raw composed prompt on any
        # LLM failure or when the toggle is off.
        full_prompt = self._refine_prompt_if_enabled(
            full_prompt, target="video")
        req = GenerationRequest(
            prompt=full_prompt,
            duration_seconds=effective_duration,
            output_path=out_path,
            scene_name=scene.name,
            character_refs=char_refs_payload,
        )
        self._update_status(
            f"Generating clip for '{scene.name}' via "
            f"{backend.label}…")
        result = backend.generate(req)
        if not result.success:
            QMessageBox.warning(
                self, "Generation failed",
                f"Backend reported:\n{result.error}")
            self._update_status("")
            return
        clip = VideoClip(
            file_path=str(result.output_path),
            sidecar_path=str(result.sidecar_path),
            backend=backend.name,
            prompt_at_generation=full_prompt,
            duration_seconds=effective_duration,
            is_placeholder=result.is_placeholder,
            clip_type="video",
        )
        scene.add_clip(clip)
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"Clip added to '{scene.name}'"
            + (" (placeholder)" if result.is_placeholder else "")
            + ".")

    def _promote_to_real_image_backend(self):
        """Return an image backend to render with.

        With image generation now unified through the
        ``ConfiguredImageBackend`` adapter, the placeholder→real
        swap is rarely needed — the studio already picked the
        Configured backend whenever Settings has a model id. The
        only path that lands here on placeholder is one where the
        writer hasn't picked a model yet, so we surface a one-time
        prompt steering them to Settings → 🎨 Image Generation.
        """
        current = self._current_image_backend
        is_placeholder = (
            current is not None
            and current.name == "placeholder_image")
        if not is_placeholder:
            return current
        # See if the Configured backend would work — happens when
        # the writer has picked a model in Settings since the last
        # sync. If so, swap silently and remember it.
        configured = get_image_backend("configured")
        if (configured is not None
                and configured.is_installed()):
            self._current_image_backend = configured
            self._refresh_backend_info()
            return configured
        # No model configured yet — point the writer at Settings
        # once per session so they understand the placeholder
        # output is intentional and how to fix it.
        if not getattr(self, "_warned_no_real_backend", False):
            QMessageBox.information(
                self, "No image model configured",
                "The studio is rendering with the placeholder "
                "(black frames) because Settings → 🎨 Image "
                "Generation has no model picked.\n\n"
                "Open Settings, choose a model (FLUX / SDXL / "
                "SD 3.5 / DALL-E / etc.), then come back to "
                "the studio — the next render will use it.")
            self._warned_no_real_backend = True
        return current

    def _ensure_resources_for(self, backend: VideoBackend) -> bool:
        """Pre-flight RAM + VRAM check for ``backend.generate()``.

        Returns True when generation is safe to proceed, OR when
        the writer explicitly chooses to **proceed anyway** past a
        tight-memory warning. The catalog's vram/ram numbers are
        safety bars — many modern models can dynamically swap to
        CPU offload or quantize on the fly, so writers shouldn't
        be blocked from trying.

        UI:
          * First-pass short → buttons: ``Free models & retry`` /
            ``Proceed anyway`` / ``Cancel``.
          * Still short after eviction → ``Proceed anyway`` /
            ``Cancel``.
          * A session-level flag (``_skip_memory_checks_session``)
            shortcuts the dialogs entirely once the writer has
            explicitly chosen to proceed anyway during this
            session — keeps the iteration loop fast.
        """
        # Honor the session-wide "I know, just run it" flag set by
        # a prior Proceed-anyway click.
        if getattr(self, "_skip_memory_checks_session", False):
            return True
        reqs = backend.memory_requirements()
        # Cheap exit when the backend declares no requirements
        # (placeholder, cloud-API backends).
        if reqs.vram_mb == 0 and reqs.ram_mb == 0:
            return True
        result = resource_manager.check(reqs)
        if result.satisfied:
            return True
        # First-pass short — offer to evict OR proceed.
        snap = result.snapshot
        msg = (
            f"This backend may not have enough memory to run:\n\n"
            f"  Needs: {reqs.ram_mb} MB RAM, "
            f"{reqs.vram_mb} MB VRAM\n"
            f"  Available: {snap.ram_available_mb} MB RAM, "
            f"{snap.vram_available_mb} MB VRAM "
            f"({snap.accelerator.upper()})\n\n"
            f"{result.explanation}\n\n"
            "Pick one:\n"
            "  • Free models & retry — drops the LLM + shared "
            "model cache, then re-checks\n"
            "  • Proceed anyway — try the render with the "
            "current memory state (CPU offload / quantization may "
            "still let it succeed)\n"
            "  • Cancel — abort this render")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Memory budget tight")
        box.setText(msg)
        free_btn = box.addButton(
            "Free models && retry",
            QMessageBox.ButtonRole.AcceptRole)
        proceed_btn = box.addButton(
            "Proceed anyway",
            QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(free_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_btn:
            self._update_status("Generation cancelled by user.")
            return False
        if clicked == proceed_btn:
            # Persist for the session so the writer isn't
            # re-prompted on every per-action generation in a
            # tight iteration loop.
            self._skip_memory_checks_session = True
            self._update_status(
                "Proceeding past memory warning — backend may "
                "OOM mid-render.")
            return True
        # Free + retry.
        self._update_status("Freeing other models…")
        freed = resource_manager.free_other_models()
        self._update_status(
            f"Freed: {freed.llm_clients_unloaded} LLM client(s), "
            f"{freed.model_cache_cleared_count} cached model(s)"
            + (", CUDA cache" if freed.cuda_cache_emptied else "")
            + (", MPS cache" if freed.mps_cache_emptied else "")
            + ".")
        result2 = resource_manager.check(reqs)
        if result2.satisfied:
            return True
        # Still short — offer Proceed anyway as the last option,
        # rather than blocking the writer outright.
        box2 = QMessageBox(self)
        box2.setIcon(QMessageBox.Icon.Warning)
        box2.setWindowTitle("Still short on memory")
        box2.setText(
            "Even after freeing other models the system is below "
            "this backend's declared budget.\n\n"
            f"{result2.explanation}\n\n"
            "The render may still succeed (CPU offload / "
            "quantization), but it can also fail mid-way. Proceed?")
        proceed2 = box2.addButton(
            "Proceed anyway",
            QMessageBox.ButtonRole.ActionRole)
        cancel2 = box2.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole)
        box2.setDefaultButton(cancel2)
        box2.exec()
        if box2.clickedButton() == proceed2:
            self._skip_memory_checks_session = True
            self._update_status(
                "Proceeding past memory warning — backend may "
                "OOM mid-render.")
            return True
        self._update_status("")
        return False

    def reset_memory_check_skip(self) -> None:
        """Re-enable the memory pre-flight after a session-wide
        ``Proceed anyway``. Useful for the Project menu / a future
        toolbar reset, or for tests that need to restore the
        prompt-on-tight-memory behavior."""
        self._skip_memory_checks_session = False

    def _generate_image_for_scene(self, scene_id: str) -> None:
        """Generate an image still for a scene via the current
        ImageBackend. Uses ``scene.image_display_seconds`` as the
        clip's duration so the stitcher knows how long to hold the
        frame on screen."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        backend = self._promote_to_real_image_backend()
        if backend is None or not backend.is_installed():
            QMessageBox.warning(
                self, "Image backend not installed",
                f"{backend.label} isn't ready. Pick the placeholder "
                f"image backend or install this one via Install / "
                f"Help.")
            return
        if not scene.prompt.strip():
            QMessageBox.information(
                self, "Empty prompt",
                "This scene has no prompt yet. Open the editor and "
                "add one (or ask the AI to write it).")
            return
        # Image backends use less memory than video backends but the
        # pre-flight still runs — small SDXL models can OOM on 8 GB
        # GPUs when an LLM is loaded too.
        if not self._ensure_resources_for(backend):
            return

        out_dir = self._scene_output_dir(scene)
        out_dir.mkdir(parents=True, exist_ok=True)
        clip_count = len(scene.clips)
        out_path = out_dir / (
            f"still_{clip_count + 1:03d}_{backend.name}.png")

        char_refs_payload = []
        for ref_name in scene.character_refs:
            ref = studio.get_character_reference(ref_name)
            if ref:
                char_refs_payload.append({
                    "name": ref.name,
                    "appearance_prompt": ref.appearance_prompt,
                    "seed": ref.seed,
                })
            else:
                char_refs_payload.append({
                    "name": ref_name,
                    "appearance_prompt": "",
                    "seed": None,
                })

        style_block = self._format_style_block()
        image_prompt = (
            f"{style_block}\n\n{scene.prompt}"
            if style_block else scene.prompt)
        # Optional AI refinement → image art-direction language.
        image_prompt = self._refine_prompt_if_enabled(
            image_prompt, target="image")
        req = ImageGenerationRequest(
            prompt=image_prompt,
            output_path=out_path,
            scene_name=scene.name,
            character_refs=char_refs_payload,
        )
        self._update_status(
            f"Generating image still for '{scene.name}' via "
            f"{backend.label}…")
        result = backend.generate(req)
        if not result.success:
            QMessageBox.warning(
                self, "Image generation failed",
                f"Backend reported:\n{result.error}")
            self._update_status("")
            return
        # Image clips reuse VideoClip but carry clip_type="image_still"
        # and use the scene's image_display_seconds as their stored
        # duration — that's what the stitcher honors when looping the
        # image into the final video.
        display = float(scene.image_display_seconds or 4.0)
        clip = VideoClip(
            file_path=str(result.output_path),
            sidecar_path=str(result.sidecar_path),
            backend=backend.name,
            prompt_at_generation=image_prompt,
            duration_seconds=display,
            is_placeholder=result.is_placeholder,
            clip_type="image_still",
        )
        scene.add_clip(clip)
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"Image still added to '{scene.name}' via "
            f"{backend.label} (display "
            f"{display:.1f}s"
            + (", placeholder" if result.is_placeholder else "")
            + ").")

    # ------------------------------------------------------------------
    # Storyboard save / load / clear / arrange
    # ------------------------------------------------------------------
    def _save_storyboard(self) -> None:
        """Write the current VideoStudio (scenes + hops + character
        refs) to a standalone JSON file. Independent of the project
        save — useful for backing up a board or sharing it with a
        collaborator."""
        studio = self._studio()
        if studio is None:
            QMessageBox.information(
                self, "No project",
                "Open a project before saving a storyboard.")
            return
        if not studio.scenes:
            reply = QMessageBox.question(
                self, "Empty board",
                "The board has no scenes yet. Save anyway?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        # Default filename: <project slug>_storyboard.json next to
        # the project so users find it easily.
        from PyQt6.QtWidgets import QFileDialog
        slug = "storyboard"
        if self._project is not None:
            name = (getattr(self._project, "name", "")
                    or "").strip().lower().replace(" ", "_")
            slug = (name or "storyboard") + "_storyboard"
        default_path = str(Path.home() / f"{slug}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save storyboard", default_path,
            "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            text = studio.model_dump_json(indent=2)
            Path(path).write_text(text, encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(
                self, "Save failed",
                f"Could not write storyboard:\n{e}")
            return
        self._update_status(
            f"Saved {len(studio.scenes)} scene(s) and "
            f"{len(studio.hops)} hop(s) to {Path(path).name}.")

    def _load_storyboard(self) -> None:
        """Read a storyboard JSON file and REPLACE the current board.
        Asks for confirmation when existing content would be
        discarded."""
        studio = self._studio()
        if studio is None or self._project is None:
            QMessageBox.information(
                self, "No project",
                "Open a project before loading a storyboard.")
            return
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Load storyboard", str(Path.home()),
            "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            loaded = VideoStudio.model_validate_json(text)
        except Exception as e:
            QMessageBox.warning(
                self, "Load failed",
                f"Could not parse storyboard:\n{e}")
            return
        # Confirm before discarding non-empty boards.
        if studio.scenes or studio.hops:
            existing = (
                f"{len(studio.scenes)} scene(s) and "
                f"{len(studio.hops)} hop(s)")
            incoming = (
                f"{len(loaded.scenes)} scene(s) and "
                f"{len(loaded.hops)} hop(s)")
            reply = QMessageBox.question(
                self, "Replace current board?",
                f"Loading will REPLACE the current board "
                f"({existing}) with the file's contents "
                f"({incoming}).\n\nContinue?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        # Atomic-ish swap: assign onto the project; the canvas
        # rebuilds from the new state.
        self._project.video_studio = loaded
        self._canvas.load_studio(loaded)
        self.contentChanged.emit()
        self._update_status(
            f"Loaded {len(loaded.scenes)} scene(s), "
            f"{len(loaded.hops)} hop(s) from {Path(path).name}.")

    def _clear_board(self) -> None:
        """Drop every scene + hop on the board. Character references
        and backend preferences stick around so the user doesn't
        have to re-configure defaults."""
        studio = self._studio()
        if studio is None or not studio.scenes:
            return
        reply = QMessageBox.question(
            self, "Clear the board?",
            f"Delete {len(studio.scenes)} scene(s) and "
            f"{len(studio.hops)} hop(s)?\n\n"
            "Character references and backend preferences are "
            "kept. This cannot be undone (use Save board first if "
            "you want a backup).")
        if reply != QMessageBox.StandardButton.Yes:
            return
        dropped = studio.clear_board()
        self._canvas.refresh_all()
        self.contentChanged.emit()
        self._update_status(f"Cleared {dropped} scene(s) from the board.")

    def _fit_canvas_to_view(self) -> None:
        """Zoom + pan so every card is visible. No-op on an empty
        board."""
        studio = self._studio()
        if studio is None or not studio.scenes:
            return
        self._canvas.fit_to_view()

    def _auto_arrange_board(self) -> None:
        """Re-flow card positions into a tidy grid in topological
        order. Visual aid when scenes have accumulated organically
        and the layout has drifted; doesn't change story content."""
        studio = self._studio()
        if studio is None or not studio.scenes:
            return
        studio.auto_arrange()
        self._canvas.refresh_all()
        self.contentChanged.emit()
        self._update_status(
            f"Arranged {len(studio.scenes)} scene(s) into a "
            f"{studio.grid_cols}×{studio.grid_rows} grid.")

    def _generate_slide_deck_for_scene(self, scene_id: str) -> None:
        """Generate one image per action in the scene, for slideshow
        mode. Skips actions that already have at least one image so
        repeated invocations top up missing slides rather than
        regenerating the whole deck."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        if not scene.actions:
            QMessageBox.information(
                self, "No actions",
                "This scene has no actions yet. Open the editor and "
                "use 'AI: extract from prose' or add actions "
                "manually first.")
            return
        backend = self._promote_to_real_image_backend()
        if backend is None or not backend.is_installed():
            QMessageBox.warning(
                self, "Image backend not installed",
                f"{getattr(backend, 'label', 'Image backend')} "
                f"isn't ready. Install one via the toolbar.")
            return
        if not self._ensure_resources_for(backend):
            return
        # Promote the scene to slideshow mode if it isn't already —
        # the user explicitly asked for per-action images.
        if scene.mode != "slideshow":
            scene.mode = "slideshow"
        generated = 0
        skipped = 0
        for action in scene.actions:
            if action.images:
                skipped += 1
                continue
            img = self._generate_image_for_action(scene, action)
            if img is not None:
                generated += 1
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"Slide deck for '{scene.name}': {generated} new image"
            + ("s" if generated != 1 else "")
            + (f", {skipped} action"
               + ("s" if skipped != 1 else "")
               + " kept" if skipped else "")
            + ".")

    def _propagate_action_favorites_to_slide_decks(
            self) -> int:
        """Push every action's current favorite-image path into
        the matching slide pages.

        Slide pages carry ``source_action_id`` as provenance —
        we use it to look the action back up, pull the live
        favorite, and write its file_path onto ``page.image_path``.
        Runs after the scene editor closes; without this, a
        favorite change in the card editor would leave the
        slide deck stuck on whatever image was favorited when
        the deck was first stitched.

        Returns the count of pages whose ``image_path`` actually
        changed (zero is the common case — most closes don't
        touch favorites).
        """
        studio = self._studio()
        if studio is None:
            return 0
        # Build action_id → favorite file_path lookup once;
        # cheaper than calling ``action.favorite_image()`` per
        # page when the deck is big.
        action_favorites: dict = {}
        for scene in (getattr(studio, "scenes", []) or []):
            for action in (
                    getattr(scene, "actions", []) or []):
                try:
                    fav = action.favorite_image()
                except Exception:
                    fav = None
                if fav is None:
                    continue
                path = getattr(fav, "file_path", "") or ""
                if path:
                    action_favorites[action.id] = path
        if not action_favorites:
            return 0
        updated = 0
        from datetime import datetime as _dt
        for deck in (
                getattr(studio, "slide_decks", []) or []):
            for page in (getattr(deck, "pages", []) or []):
                aid = getattr(page, "source_action_id", None)
                if not aid:
                    continue
                new_path = action_favorites.get(aid)
                if not new_path:
                    continue
                if (getattr(page, "image_path", "")
                        != new_path):
                    page.image_path = new_path
                    try:
                        page.updated_at = _dt.now()
                    except Exception:
                        pass
                    updated += 1
        # If the slide editor is open, ask it to refresh so the
        # writer sees the swap immediately. We call the
        # dedicated ``refresh_after_external_change`` which
        # updates BOTH the slide list AND the popup preview
        # window — ``_refresh_slides`` alone leaves the popup
        # showing the old image because it only repaints list
        # text. ``QPixmap`` doesn't cache by path, so re-calling
        # ``set_current`` on the preview re-reads from disk.
        active = getattr(
            self, "_active_slide_editor", None)
        if active is not None and updated > 0:
            try:
                from PyQt6 import sip as _sip
                if not _sip.isdeleted(active):
                    if hasattr(
                            active,
                            "refresh_after_external_change"):
                        active.refresh_after_external_change()
                    elif hasattr(active, "_refresh_slides"):
                        # Older slide-editor builds without
                        # the dedicated entry point — at
                        # least update the list text.
                        active._refresh_slides()
            except Exception as exc:
                print(
                    f"[studio] could not refresh open "
                    f"slide editor: {exc}")
        return updated

    def _stitch_slide_deck_for_scene(self, scene_id: str) -> None:
        """Stitch this scene's per-action images into a single
        slide-deck video. Walks the actions in order and takes
        each action's ``favorite_image()`` (the favorite when the
        writer has starred one, otherwise the first generated
        image as a safe default) as that action's slide. Each
        slide holds for the action's own ``display_seconds`` or,
        when that's 0, the scene's ``image_display_seconds``.

        Actions with no images at all — or whose favorite file is
        gone from disk — are skipped with a confirmation so the
        writer doesn't accidentally ship a half-finished deck.

        The resulting MP4 is attached to the scene as a VideoClip
        with ``clip_type="slideshow"`` so it surfaces in the
        editor's clip list and gets exported the same way as a
        backend-generated clip.
        """
        from src.video_studio.stitcher import (
            stitch_clips, ffmpeg_available)
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Slide-deck stitching needs ffmpeg on PATH. Install "
                "it (brew install ffmpeg / apt install ffmpeg) and "
                "try again.")
            return
        # One slide per action, in action order. The favorite is
        # the writer's chosen "best take" for that beat — that's
        # the slide we use. If no favorite is set explicitly we
        # fall back to the first image so an action with a single
        # generation Just Works without forcing a star click.
        clip_paths: List[Path] = []
        clip_durations: List[float] = []
        scene_default = float(scene.image_display_seconds or 4.0)
        missing_actions: List[str] = []
        # Console trace of the selection — writers debugging
        # "missing actions" or "deck cut at a minute" can read
        # this to see exactly which image fed each slide, what
        # duration it held, and why any action was skipped.
        print(
            f"[slide-deck] '{scene.name or scene.id}' — "
            f"{len(scene.actions)} action(s); "
            f"scene default hold {scene_default:.2f}s")
        for idx, action in enumerate(scene.actions, start=1):
            chosen = action.favorite_image()
            label = action.name or action.id
            if chosen is None:
                missing_actions.append(label)
                print(
                    f"  [{idx}] {label}: skipped "
                    f"(no images on action)")
                continue
            if not chosen.file_path:
                missing_actions.append(label)
                print(
                    f"  [{idx}] {label}: skipped "
                    f"(image record has empty file_path)")
                continue
            path = Path(chosen.file_path)
            try:
                if not path.exists():
                    missing_actions.append(label)
                    print(
                        f"  [{idx}] {label}: skipped "
                        f"(file not found: {path})")
                    continue
                if path.stat().st_size == 0:
                    missing_actions.append(label)
                    print(
                        f"  [{idx}] {label}: skipped "
                        f"(file is 0 bytes: {path})")
                    continue
            except Exception as e:
                missing_actions.append(label)
                print(
                    f"  [{idx}] {label}: skipped "
                    f"(stat error: {e})")
                continue
            dur = float(action.display_seconds or 0.0)
            using_default = dur <= 0
            if using_default:
                dur = scene_default
            dur = max(0.5, dur)
            why = (
                "favorite" if action.favorite_image_id
                else "first-image fallback")
            print(
                f"  [{idx}] {label}: include {path.name} "
                f"({why}); hold {dur:.2f}s"
                + (" [scene default]" if using_default else ""))
            clip_paths.append(path)
            clip_durations.append(dur)
        total_runtime = sum(clip_durations)
        print(
            f"[slide-deck] '{scene.name or scene.id}' — "
            f"{len(clip_paths)} slide(s) selected, "
            f"~{total_runtime:.2f}s total; "
            f"{len(missing_actions)} skipped")
        if not clip_paths:
            QMessageBox.information(
                self, "Nothing to stitch",
                "No actions have a favorite image yet. Click the "
                "📑 Deck button (or use 'Generate slide deck' from "
                "the right-click menu) to render images, then mark "
                "a favorite per action in the action editor.")
            return
        if missing_actions:
            # Partial stitches are common while iterating — confirm
            # rather than block. The skip list calls out which
            # actions had no favorite image so the writer can
            # decide whether to fix them first or ship as-is.
            reply = QMessageBox.question(
                self, "Skip actions without a favorite image?",
                f"{len(missing_actions)} action(s) don't have a "
                f"favorite image yet and will be skipped:\n  • "
                + "\n  • ".join(missing_actions[:6])
                + ("\n  • …" if len(missing_actions) > 6 else "")
                + f"\n\nStitch the remaining {len(clip_paths)} "
                f"slide(s) anyway?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        out_dir = self._scene_output_dir(scene)
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = sum(
            1 for c in scene.clips if c.clip_type == "slideshow") + 1
        out_path = out_dir / f"slideshow_{idx:03d}.mp4"
        self._update_status(
            f"Stitching {len(clip_paths)} slide(s) for "
            f"'{scene.name}'…")
        result = stitch_clips(
            clip_paths, out_path, clip_durations=clip_durations)
        if not result.success:
            QMessageBox.warning(
                self, "Stitch failed", result.error)
            self._update_status("")
            return
        # Total duration = sum of per-slide times (best estimate,
        # since the stitcher's image segments use exactly those
        # durations).
        total = sum(clip_durations)
        clip = VideoClip(
            file_path=str(result.output_path),
            sidecar_path="",
            backend="stitcher",
            prompt_at_generation=(
                f"Slide deck for '{scene.name}' "
                f"({len(clip_paths)} slides)"),
            duration_seconds=float(total),
            is_placeholder=False,
            clip_type="slideshow",
        )
        scene.add_clip(clip)
        # The newly-stitched deck IS the current truth for this
        # scene — always make it the favorite so chapter export
        # pulls the latest assembly. Without this, a writer who
        # adds actions and re-stitches keeps shipping the stale
        # earlier stitch (add_clip only sets favorite when none
        # exists), which is the actions-cut-off symptom reported
        # during deck exports.
        scene.favorite_clip_id = clip.id
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"Slide deck stitched: {len(clip_paths)} slide(s), "
            f"~{total:.1f}s total. Saved to {out_path.name}.")

    def _open_latest_clip_for_scene(self, scene_id: str) -> None:
        """Open the scene's favorite (or most recent) clip in the
        system viewer — works for video clips, image stills, and
        slideshow stitches alike since they all share the VideoClip
        record."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None or not scene.clips:
            QMessageBox.information(
                self, "No output yet",
                "This scene hasn't generated anything yet. Use the "
                "🎬/🖼/📑 buttons on the card to create a clip "
                "first.")
            return
        clip = scene.favorite_clip() or scene.clips[-1]
        path = Path(clip.file_path) if clip.file_path else None
        if path is None or not path.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"The clip file is missing on disk:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _upload_clip_from_canvas(self, scene_id: str) -> None:
        """Canvas-context-menu adapter: resolves the scene id and
        delegates to ``_upload_clip_for_scene``."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        self._upload_clip_for_scene(scene)

    def _upload_clip_for_scene(
        self, scene: Scene,
        src_paths: Optional[List[Path]] = None,
    ) -> None:
        """Ingest one or more existing image / video files into a
        scene as VideoClip records. Lets writers bring in output
        from external generators (Midjourney, RunwayML, Sora, etc.)
        or hand-shot footage and use it in the studio just like
        in-app renders.

        When ``src_paths`` is None we open a file picker. The file
        is COPIED into the scene's output dir (so the project is
        portable) — never moved. Image files become VideoClip
        records with ``clip_type="image_still"``; .mp4 / .mov /
        .webm / .mkv become regular video clips. First upload
        becomes the favorite when no favorite is set yet.
        """
        if src_paths is None:
            picked, _ = QFileDialog.getOpenFileNames(
                self,
                f"Upload clip / image for '{scene.name}'",
                "",
                "Media (*.png *.jpg *.jpeg *.webp *.gif "
                "*.mp4 *.mov *.webm *.mkv);;Image (*.png *.jpg "
                "*.jpeg *.webp *.gif);;Video (*.mp4 *.mov *.webm "
                "*.mkv);;All files (*)")
            if not picked:
                return
            src_paths = [Path(p) for p in picked]
        out_dir = self._scene_output_dir(scene)
        out_dir.mkdir(parents=True, exist_ok=True)
        IMAGE_EXTS = {
            ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif",
            ".tiff"}
        VIDEO_EXTS = {
            ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
        from datetime import datetime
        import shutil as _shutil
        imported = 0
        skipped: List[str] = []
        for src in src_paths:
            if not src.exists() or src.stat().st_size == 0:
                skipped.append(f"{src.name}: empty or missing")
                continue
            ext = src.suffix.lower()
            if ext in IMAGE_EXTS:
                clip_type = "image_still"
                duration = float(
                    scene.image_display_seconds or 4.0)
            elif ext in VIDEO_EXTS:
                clip_type = "video"
                duration = 0.0  # backends typically read length
            else:
                skipped.append(
                    f"{src.name}: unsupported format ({ext})")
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            idx = sum(
                1 for c in scene.clips
                if "upload" in c.backend) + 1
            dest = out_dir / (
                f"upload_{idx:03d}_{stamp}{ext}")
            try:
                _shutil.copy2(src, dest)
            except Exception as e:
                skipped.append(
                    f"{src.name}: copy failed ({e})")
                continue
            clip = VideoClip(
                file_path=str(dest),
                sidecar_path="",
                backend="upload",
                prompt_at_generation=(
                    f"Uploaded by writer: {src.name}"),
                duration_seconds=duration,
                is_placeholder=False,
                clip_type=clip_type,
            )
            scene.add_clip(clip)
            imported += 1
        if imported == 0:
            QMessageBox.warning(
                self, "Nothing imported",
                "No files were imported.\n\n"
                + "\n".join(skipped[:10]))
            return
        self._canvas.refresh_scene_card(scene.id)
        self.contentChanged.emit()
        msg = (
            f"Imported {imported} file"
            + ("s" if imported != 1 else "")
            + f" into '{scene.name}'.")
        if skipped:
            msg += (
                f"\n\nSkipped {len(skipped)}:\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        self._update_status(msg.split("\n")[0])
        QMessageBox.information(
            self, "Upload complete", msg)

    def _upload_image_for_action(
        self, scene: Scene, action,
        src_paths: Optional[List[Path]] = None,
    ) -> Optional[Any]:
        """Ingest one or more existing image files as ActionImage
        records on the given action. Mirrors
        ``_upload_clip_for_scene`` but at action granularity, so
        writers can bring in external renders or hand-drawn
        artwork for each beat. Returns the FIRST imported
        ActionImage (or None) so the action editor can auto-
        select it for preview.
        """
        if src_paths is None:
            picked, _ = QFileDialog.getOpenFileNames(
                self,
                f"Upload images for action '{action.name}'",
                "",
                "Image (*.png *.jpg *.jpeg *.webp *.gif);;"
                "All files (*)")
            if not picked:
                return None
            src_paths = [Path(p) for p in picked]
        out_dir = (
            self._scene_output_dir(scene)
            / "actions" / action.id)
        out_dir.mkdir(parents=True, exist_ok=True)
        IMAGE_EXTS = {
            ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif",
            ".tiff"}
        from datetime import datetime
        import shutil as _shutil
        from src.video_studio.models import ActionImage
        imported_first: Optional[Any] = None
        imported = 0
        skipped: List[str] = []
        for src in src_paths:
            if not src.exists() or src.stat().st_size == 0:
                skipped.append(f"{src.name}: empty or missing")
                continue
            ext = src.suffix.lower()
            if ext not in IMAGE_EXTS:
                skipped.append(
                    f"{src.name}: unsupported format ({ext})")
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            idx = len(action.images) + 1
            dest = out_dir / (
                f"upload_{idx:03d}_{stamp}{ext}")
            try:
                _shutil.copy2(src, dest)
            except Exception as e:
                skipped.append(
                    f"{src.name}: copy failed ({e})")
                continue
            img = ActionImage(
                file_path=str(dest),
                sidecar_path="",
                backend="upload",
                prompt_at_generation=(
                    f"Uploaded by writer: {src.name}"),
                is_placeholder=False,
                included_in_slideshow=True,
                display_seconds=float(
                    scene.image_display_seconds or 4.0),
            )
            action.images.append(img)
            if action.favorite_image_id is None:
                action.favorite_image_id = img.id
            imported += 1
            if imported_first is None:
                imported_first = img
        if imported == 0:
            QMessageBox.warning(
                self, "Nothing imported",
                "No files were imported.\n\n"
                + "\n".join(skipped[:10]))
            return None
        from datetime import datetime as _dt
        action.updated_at = _dt.now()
        self.contentChanged.emit()
        self._update_status(
            f"Imported {imported} image"
            + ("s" if imported != 1 else "")
            + f" into action '{action.name}'.")
        if skipped:
            QMessageBox.information(
                self, "Upload complete",
                f"Imported {imported}. "
                f"Skipped {len(skipped)}:\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        return imported_first

    def _open_output_folder_for_scene(self, scene_id: str) -> None:
        """Open the scene's output directory in the system file
        manager — gives the writer a fast way to browse every
        generated clip / image / slide."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None:
            return
        out_dir = self._scene_output_dir(scene)
        out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(out_dir.resolve())))

    def _switch_scene_mode(self, scene_id: str, new_mode: str) -> None:
        """Toggle a scene between video and slideshow render modes
        from the canvas context menu. Updates the model, refreshes
        the card chip, and emits contentChanged so the save flag
        ticks."""
        studio = self._studio()
        if studio is None:
            return
        scene = studio.get_scene(scene_id)
        if scene is None or new_mode not in ("video", "slideshow"):
            return
        if scene.mode == new_mode:
            return
        scene.mode = new_mode
        from datetime import datetime
        scene.updated_at = datetime.now()
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"'{scene.name}' switched to "
            f"{'🖼 slideshow' if new_mode == 'slideshow' else '🎬 video'}"
            f" mode.")

    def _generate_image_for_action(
        self, scene: Scene, action,
    ) -> Optional[Any]:
        """Generate one image for a SceneAction using the current
        image backend. Returns the new ``ActionImage`` (which the
        callback also appends to ``action.images``), or None on
        failure / no installed backend.
        """
        backend = self._promote_to_real_image_backend()
        if backend is None or not backend.is_installed():
            QMessageBox.warning(
                self, "Image backend not installed",
                f"{getattr(backend, 'label', 'Image backend')} isn't "
                f"ready. Install one via the toolbar.")
            return None
        if not self._ensure_resources_for(backend):
            return None
        # Per-action image lives under the scene's output dir so
        # cleanup follows the scene's lifecycle.
        out_dir = self._scene_output_dir(scene) / "actions" / action.id
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = len(action.images) + 1
        out_path = out_dir / f"slide_{idx:03d}_{backend.name}.png"
        # Structured composition lives in ``_compose_action_prompt``
        # so the action editor's '✨ Preview AI-refined' button
        # sees the same source string the renderer does. Optional
        # AI refinement runs here: per-action images are still
        # IMAGE prompts even when the scene's primary mode is
        # video, so target="image".
        action_prompt = self._compose_action_prompt(scene, action)
        action_prompt = self._refine_prompt_if_enabled(
            action_prompt, target="image")
        # Build character refs payload from action's chosen subset.
        studio = self._studio()
        char_refs_payload = []
        for ref_name in (action.character_refs or scene.character_refs):
            if studio is None:
                continue
            ref = studio.get_character_reference(ref_name)
            if ref:
                char_refs_payload.append({
                    "name": ref.name,
                    "appearance_prompt": ref.appearance_prompt,
                    "seed": ref.seed,
                })
            else:
                char_refs_payload.append({
                    "name": ref_name,
                    "appearance_prompt": "",
                    "seed": None,
                })
        req = ImageGenerationRequest(
            prompt=action_prompt,
            output_path=out_path,
            scene_name=f"{scene.name} → {action.name}",
            character_refs=char_refs_payload,
        )
        self._update_status(
            f"Generating image for action '{action.name}' "
            f"via {backend.label}…")
        result = backend.generate(req)
        if not result.success:
            QMessageBox.warning(
                self, "Image generation failed",
                f"Backend reported:\n{result.error}")
            self._update_status("")
            return None
        from src.video_studio.models import ActionImage
        img = ActionImage(
            file_path=str(result.output_path),
            sidecar_path=str(result.sidecar_path),
            backend=backend.name,
            prompt_at_generation=action_prompt,
            is_placeholder=result.is_placeholder,
            included_in_slideshow=True,
            display_seconds=float(scene.image_display_seconds or 4.0),
        )
        action.images.append(img)
        if action.favorite_image_id is None:
            action.favorite_image_id = img.id
        from datetime import datetime
        action.updated_at = datetime.now()
        self.contentChanged.emit()
        self._update_status(
            f"Image added for action '{action.name}' via "
            f"{backend.label}"
            + (" (placeholder)" if result.is_placeholder else "")
            + ".")
        return img

    def _studio_root_dir(self) -> Path:
        """Filesystem root where all video studio outputs land for
        the current project.

        ``project.project_path`` points at the ``.writerproj`` FILE,
        not a directory, so we take its parent and place the output
        in a sibling folder named after the project. (Treating the
        file path itself as a directory was the source of the
        ``NotADirectoryError`` users hit on external drives.)
        """
        if self._project is not None:
            proj_path = getattr(self._project, "project_path", None)
            if proj_path:
                p = Path(proj_path)
                # Honor an already-directory path historically used
                # by some callers; otherwise use the file's parent +
                # a stem-namespaced subfolder so multiple .writerproj
                # files in one folder don't collide.
                if p.is_dir():
                    return p
                return p.parent / f"{p.stem}_video_studio"
        return Path.home() / ".writingaid_videos"

    def _scene_output_dir(self, scene: Scene) -> Path:
        """Where this scene's clip files live on disk."""
        return self._studio_root_dir() / "scenes" / scene.id

    # ------------------------------------------------------------------
    # Stitching
    # ------------------------------------------------------------------
    def _classify_chapter_export_scenes(
        self, scenes: list,
    ) -> tuple:
        """Split chapter scenes into (ready, stitchable, missing)
        based on whether their output is usable for the deck.

        Ready
            Has a real (non-placeholder, on-disk) favorite clip.
            ``favorite_clip()`` falls back to the first clip when
            no favorite is set, so unfavorited-but-rendered scenes
            count as ready.
        Stitchable
            Slideshow scene with no usable scene-level clip yet,
            BUT every (or enough) action has a favorite image on
            disk. The export can stitch these on the fly without
            asking the writer to generate anything new — the
            images they starred ARE the deck.
        Missing
            No images anywhere, only placeholders, or the favorite
            file is gone. These are the scenes the writer can be
            offered "generate now?" for.
        """
        ready: list = []
        stitchable: list = []
        missing: list = []
        for scene in scenes:
            has_clip = self._scene_has_usable_favorite_clip(scene)
            can_stitch = (
                self._scene_can_stitch_from_action_favorites(scene))
            if has_clip:
                # For slideshow scenes, a stale stitch (the writer
                # added new action images after the last stitch)
                # would otherwise ship as ready and the chapter
                # deck would cut off the newer beats. Force re-
                # stitch whenever a fresher action image exists.
                if (scene.mode == "slideshow"
                        and can_stitch
                        and not self._slideshow_stitch_is_current(
                            scene)):
                    stitchable.append(scene)
                    continue
                ready.append(scene)
                continue
            if can_stitch:
                stitchable.append(scene)
                continue
            missing.append(scene)
        return ready, stitchable, missing

    def _slideshow_stitch_is_current(self, scene) -> bool:
        """True when the scene's latest stitched-slideshow clip is
        as fresh as (or fresher than) every action's favorite
        image. False when the writer added / re-rolled an image
        after the last stitch — that's the signal to re-stitch so
        the new beats actually land in the deck.

        Non-slideshow scenes return True (the check doesn't apply).
        """
        if scene.mode != "slideshow":
            return True
        latest_stitch = None
        for c in scene.clips:
            if getattr(c, "clip_type", "") != "slideshow":
                continue
            if (latest_stitch is None
                    or c.created_at > latest_stitch.created_at):
                latest_stitch = c
        if latest_stitch is None:
            return False
        latest_image_time = None
        for a in getattr(scene, "actions", None) or []:
            img = a.favorite_image()
            if img is None:
                continue
            t = getattr(img, "created_at", None)
            if t is None:
                continue
            if (latest_image_time is None
                    or t > latest_image_time):
                latest_image_time = t
        if latest_image_time is None:
            return True
        return latest_stitch.created_at >= latest_image_time

    def _scene_has_usable_favorite_clip(self, scene) -> bool:
        """True when the scene already has a real clip on disk —
        either explicitly favorited or as a fallback non-placeholder
        clip the writer rendered without starring."""
        clip = scene.favorite_clip()
        if clip is None:
            return False
        file_path = (clip.file_path or "").strip()
        if not file_path:
            return False
        try:
            p = Path(file_path)
            if not p.exists() or p.stat().st_size == 0:
                return False
        except Exception:
            return False
        if not getattr(clip, "is_placeholder", False):
            return True
        # Placeholder favorite — accept the scene if a real backup
        # clip exists elsewhere on it (writer rendered without
        # re-marking favorite).
        for c in scene.clips:
            if (c.file_path
                    and not c.is_placeholder
                    and Path(c.file_path).exists()
                    and Path(c.file_path).stat().st_size > 0):
                return True
        return False

    def _scene_can_stitch_from_action_favorites(
        self, scene,
    ) -> bool:
        """True when this is a slideshow scene with at least one
        action whose favorite image is real and on disk. The
        chapter export uses this to stitch silently — no need to
        prompt the writer for generation when the images they
        already favorited can become the deck right now."""
        if scene.mode != "slideshow":
            return False
        actions = getattr(scene, "actions", None) or []
        if not actions:
            return False
        for a in actions:
            img = a.favorite_image()
            if img is None:
                continue
            path_str = (img.file_path or "").strip()
            if not path_str:
                continue
            try:
                p = Path(path_str)
                if p.exists() and p.stat().st_size > 0:
                    return True
            except Exception:
                continue
        return False

    def _can_generate_now(self) -> bool:
        """True when we have at least an image backend installed —
        enough to render an image still or per-action slide.
        Chapter export doesn't need a video backend; image is the
        common denominator across slideshow + single-still + video
        modes."""
        b = self._current_image_backend
        try:
            return bool(b is not None and b.is_installed())
        except Exception:
            return False

    def _generate_for_chapter_export(
        self, missing_scenes: list,
    ) -> tuple:
        """Best-effort generate a usable favorite for each scene
        that the deck would otherwise skip. Slideshow scenes get
        their per-action slide deck rendered + stitched; other
        scenes get a single image still.

        Returns (filled, still_missing) — scenes that now have a
        usable favorite vs. those generation couldn't help.
        """
        filled: list = []
        still_missing: list = []
        for scene in missing_scenes:
            self._update_status(
                f"Generating for '{scene.name or scene.id}'…")
            try:
                if (scene.mode == "slideshow"
                        and getattr(scene, "actions", None)):
                    # Per-action images, then stitch. Each action's
                    # favorite_image() is the slide; we only stitch
                    # when at least one action has one so the
                    # stitch path doesn't pop its own "nothing to
                    # do" dialog during the batch.
                    self._generate_slide_deck_for_scene(scene.id)
                    if any(
                        a.favorite_image() is not None
                        for a in scene.actions):
                        self._stitch_slide_deck_for_scene(
                            scene.id)
                else:
                    self._generate_image_for_scene(scene.id)
            except Exception as e:
                print(
                    f"[video_studio] auto-gen for "
                    f"'{scene.name}' raised: {e}")
            # Re-classify just this one scene. ``ready`` OR
            # ``stitchable`` both count as filled — the export
            # auto-stitches stitchable scenes a moment later, no
            # extra writer input needed.
            ready, stitchable, _ = (
                self._classify_chapter_export_scenes([scene]))
            if ready or stitchable:
                filled.append(scene)
            else:
                still_missing.append(scene)
        return filled, still_missing

    def _auto_stitch_for_chapter_export(
        self, stitchable_scenes: list,
    ) -> list:
        """Stitch each ``stitchable`` slideshow scene silently from
        its existing per-action favorites so the chapter deck has a
        usable scene-level clip to pick up. Returns the list of
        scenes that still aren't ready after the silent pass
        (e.g. ffmpeg failed) so the caller can warn or skip them.
        """
        still_missing: list = []
        # Patch QMessageBox briefly so the existing per-scene stitch
        # helper's confirm-skip and ffmpeg dialogs don't interrupt
        # the batch. We only suppress the "skip actions without a
        # favorite" prompt (Yes by default), and the "Nothing to
        # stitch" info; real errors still propagate via the return
        # classification.
        from PyQt6.QtWidgets import QMessageBox
        orig_question = QMessageBox.question
        orig_info = QMessageBox.information
        QMessageBox.question = staticmethod(
            lambda *a, **kw: QMessageBox.StandardButton.Yes)
        QMessageBox.information = staticmethod(
            lambda *a, **kw: None)
        try:
            for scene in stitchable_scenes:
                try:
                    self._stitch_slide_deck_for_scene(scene.id)
                except Exception as e:
                    print(
                        f"[video_studio] auto-stitch for "
                        f"'{scene.name}' raised: {e}")
                ready, stitchable, _ = (
                    self._classify_chapter_export_scenes([scene]))
                if not (ready or stitchable):
                    still_missing.append(scene)
        finally:
            QMessageBox.question = orig_question
            QMessageBox.information = orig_info
        return still_missing

    def _open_slide_editor(self) -> None:
        """Open the slide editor directly.

        Behavior is designed to be a single click in the common
        case:
          * 0 chapters with scenes → friendly message, no picker.
          * 1 chapter with scenes → open the editor on it directly.
          * 2+ chapters → tiny chapter-only picker (no format combo,
            no title-card toggle — those belong in the export
            flow, not in "open the editor").
        """
        from src.video_studio.deck_export import (
            collect_chapter_scenes)
        from src.video_studio.slide_deck import (
            build_slide_deck_from_chapter)
        studio = self._studio()
        if studio is None or not studio.scenes:
            QMessageBox.information(
                self, "Nothing to edit",
                "Add scenes first.")
            return
        chapters_with_counts = self._enumerate_chapters_with_scenes(
            studio)
        if not chapters_with_counts:
            QMessageBox.information(
                self, "No chapters",
                "None of your scenes are linked to a chapter yet. "
                "Open a scene editor and use 'Pull from chapter' "
                "to associate scenes with chapters.")
            return
        chapter_id = self._pick_chapter_for_editor(
            chapters_with_counts,
            title="Slide editor",
            prompt=(
                "Pick a chapter to open in the slide editor. "
                "Each action's favorite image becomes one slide; "
                "you can record audio, fit timings, add "
                "transitions, and export to MP4 or PowerPoint."))
        if chapter_id is None:
            return
        chapter_label = next(
            (lbl for cid, lbl, _ in chapters_with_counts
             if cid == chapter_id),
            "Chapter")
        scenes = collect_chapter_scenes(studio, chapter_id)
        if not scenes:
            QMessageBox.information(
                self, "No scenes",
                "That chapter has no scenes linked to it.")
            return
        # Working dir for recordings + the rendered MP4.
        working_dir = (
            self._studio_root_dir() / "slide_decks" / chapter_id)
        working_dir.mkdir(parents=True, exist_ok=True)
        # Re-use an existing slide deck project for this chapter,
        # otherwise seed a fresh one from the scenes.
        deck = next(
            (d for d in studio.slide_decks
             if d.chapter_id == chapter_id),
            None)
        if deck is None:
            deck = build_slide_deck_from_chapter(
                scenes, working_dir,
                chapter_id=chapter_id,
                chapter_label=chapter_label)
            studio.slide_decks.append(deck)
        if not deck.pages:
            QMessageBox.information(
                self, "No slides",
                "None of this chapter's scenes have a favorite "
                "image on disk. Generate or mark favorites first.")
            return
        # Run the favorite propagation BEFORE we open the
        # editor so any stale ``page.image_path`` values get
        # rewritten to the current favorites. Self-heals decks
        # that drifted from the source actions while the editor
        # was closed (e.g. writer changed a favorite from the
        # scene canvas right-click menu, then opened the deck
        # for the first time).
        try:
            self._propagate_action_favorites_to_slide_decks()
        except Exception as exc:
            print(
                f"[studio] pre-open favorite sweep failed: "
                f"{exc}")
        from src.ui.video_studio.slide_editor_dialog import (
            SlideEditorDialog)
        dlg = SlideEditorDialog(
            deck,
            chapters_provider=self._chapters_snapshot_for_reading,
            save_chapter_text=self._save_chapter_text,
            open_in_writer=self._jump_to_writer,
            scenes_provider=self._scenes_snapshot_for_reading,
            parent=self)
        # Non-modal show so the floating chapter prose window
        # remains interactive — a modal slide editor would block
        # input to every other window in the app. Hold a
        # reference so Python doesn't GC the window the moment
        # this method returns.
        self._active_slide_editor = dlg
        # Two save triggers:
        #   * ``finished`` (close) — fires ``flushSaveRequested``
        #     so the host runs ``_auto_save_project``
        #     synchronously RIGHT NOW. The previous
        #     ``contentChanged``-only path went through the
        #     2.5 s debounce timer; if the writer closed the
        #     slide editor and quit the app within that window
        #     the final mutation was lost (autosave queued for
        #     2.5 s but never fired). Flushing on close
        #     guarantees the deck — and every group, audio
        #     clip, image swap inside it — lands on disk before
        #     the dialog goes away.
        #   * ``deck_modified`` (per-mutation) — keeps the
        #     debounce path for mid-session edits so a writer
        #     iterating in the group editor for an hour
        #     persists their work continuously, not just on
        #     close.
        dlg.finished.connect(
            lambda *_: self.flushSaveRequested.emit())
        dlg.deck_modified.connect(self.contentChanged)
        # ``show()`` alone — no raise_() / activateWindow(). On
        # macOS those force-grab focus and trigger the focus-
        # stealing path that minimizes other open windows of the
        # app and (on dual-screen setups) blanks the second
        # monitor. The OS handles stacking just fine when we
        # don't fight it. Writers can always click the editor in
        # the taskbar / Mission Control if it ended up behind
        # something else.
        dlg.show()

    def _pick_chapter_for_editor(
        self,
        chapters_with_counts,
        *, title: str, prompt: str,
    ):
        """Lightweight chapter picker — combo + OK / Cancel only.
        Auto-skips the dialog when there's exactly one chapter to
        pick from. Returns the chosen ``chapter_id`` or None when
        the writer cancels.
        """
        if len(chapters_with_counts) == 1:
            return chapters_with_counts[0][0]
        from PyQt6.QtWidgets import (
            QComboBox, QDialog, QDialogButtonBox, QLabel,
            QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.resize(460, 200)
        v = QVBoxLayout(dlg)
        label = QLabel(prompt)
        label.setWordWrap(True)
        v.addWidget(label)
        combo = QComboBox()
        for cid, lbl, count in chapters_with_counts:
            combo.addItem(
                f"{lbl}  —  {count} scene"
                + ("s" if count != 1 else ""),
                cid)
        v.addWidget(combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Open editor")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return combo.currentData()


    def _export_chapter_deck(self) -> None:
        """Stitch every scene in one chapter into a single deck.

        Flow:
          1. Pre-flight (ffmpeg + project + scenes-with-chapter).
          2. Build the chapter picker; user picks the chapter and
             whether to render title cards.
          3. Resolve the scenes' favorite outputs + (optional)
             title cards via ``deck_export.build_deck_entries``.
          4. Stitch via ``stitcher.stitch_clips``.
          5. Report skipped scenes + save path.
        """
        from src.video_studio.deck_export import (
            build_deck_entries, collect_chapter_scenes,
        )
        from src.video_studio.stitcher import (
            stitch_clips, ffmpeg_available)
        studio = self._studio()
        if studio is None or not studio.scenes:
            QMessageBox.information(
                self, "Nothing to export",
                "Add scenes and generate at least one clip "
                "(video, image still, or slide-deck stitch) first.")
            return
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Exporting a chapter deck needs ffmpeg on PATH. "
                "Install it (brew install ffmpeg / apt install "
                "ffmpeg) and try again.")
            return
        # Build (chapter_id, label, scene_count) list — only
        # chapters with at least one scene attached qualify.
        chapters_with_counts = self._enumerate_chapters_with_scenes(
            studio)
        from src.ui.video_studio.chapter_deck_export_dialog import (
            ChapterDeckExportDialog,
        )
        dlg = ChapterDeckExportDialog(
            chapters_with_counts, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chapter_id = dlg.selected_chapter_id()
        if not chapter_id:
            return
        with_titles = dlg.include_title_cards()
        export_format = dlg.selected_format()
        scenes = collect_chapter_scenes(studio, chapter_id)
        if not scenes:
            QMessageBox.information(
                self, "No scenes",
                "That chapter has no scenes linked to it yet.")
            return
        # ── Pre-pass: figure out which scenes already have a real
        # favorite image / video, which can be stitched from
        # already-favorited action images, and which truly need
        # generation. We auto-stitch the stitchable bucket
        # silently — the writer already starred favorites per
        # action, so prompting them to "generate" would be wrong.
        ready, stitchable, missing = (
            self._classify_chapter_export_scenes(scenes))
        if stitchable:
            self._update_status(
                f"Stitching {len(stitchable)} slide deck"
                + ("s" if len(stitchable) != 1 else "")
                + " from existing favorites…")
            still_pending = self._auto_stitch_for_chapter_export(
                stitchable)
            # Re-classify so the next prompt sees the freshly-
            # stitched scenes as ready; anything stitcher couldn't
            # save lands back in the missing bucket.
            ready, _, missing = (
                self._classify_chapter_export_scenes(scenes))
        if missing:
            can_gen = self._can_generate_now()
            if can_gen:
                names = [
                    s.name or f"Scene {i+1}"
                    for i, s in enumerate(missing)]
                prompt_text = (
                    f"{len(missing)} of {len(scenes)} scene"
                    + ("s" if len(scenes) != 1 else "")
                    + " in this chapter don't have a favorite "
                    "image / video yet:\n  • "
                    + "\n  • ".join(names[:8])
                    + ("\n  • …" if len(names) > 8 else "")
                    + "\n\nGenerate them now using the current "
                    "image backend?")
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(
                    "Generate missing scene images?")
                box.setText(prompt_text)
                gen_btn = box.addButton(
                    "Generate now",
                    QMessageBox.ButtonRole.AcceptRole)
                skip_btn = box.addButton(
                    "Skip them",
                    QMessageBox.ButtonRole.ActionRole)
                cancel_btn = box.addButton(
                    "Cancel export",
                    QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(gen_btn)
                box.exec()
                clicked = box.clickedButton()
                if clicked == cancel_btn:
                    self._update_status(
                        "Chapter deck export cancelled.")
                    return
                if clicked == gen_btn:
                    filled, still_missing = (
                        self._generate_for_chapter_export(
                            missing))
                    if filled:
                        ready = ready + filled
                    missing = still_missing
            # else: no usable image backend → fall through to
            # build_deck_entries which already reports each skip.
        if not ready:
            QMessageBox.information(
                self, "Nothing to stitch",
                "No scenes have a usable favorite output yet."
                + (" Configure an image backend in Settings to "
                   "enable in-place generation."
                   if not self._can_generate_now() else
                   " Try generating per-scene first."))
            return
        # Resolve chapter label for filenames + (video) title cards.
        chapter_label = next(
            (label for cid, label, _ in chapters_with_counts
             if cid == chapter_id),
            "Chapter")
        out_root = self._studio_root_dir() / "chapter_decks"
        out_root.mkdir(parents=True, exist_ok=True)
        safe_label = (
            chapter_label.replace("/", "-")
                         .replace(":", "-").strip() or "chapter")
        if export_format == "pptx":
            self._save_chapter_deck_as_pptx(
                scenes=scenes,
                chapter_label=chapter_label,
                out_root=out_root,
                safe_label=safe_label)
        else:
            self._save_chapter_deck_as_video(
                scenes=scenes,
                chapter_id=chapter_id,
                chapter_label=chapter_label,
                with_titles=with_titles,
                out_root=out_root,
                safe_label=safe_label)

    def _save_chapter_deck_as_video(
        self, *, scenes, chapter_id, chapter_label, with_titles,
        out_root, safe_label,
    ) -> None:
        """Stitch the chapter into a single MP4 — the legacy path,
        broken out so the PPTX branch stays parallel."""
        from src.video_studio.deck_export import build_deck_entries
        from src.video_studio.stitcher import stitch_clips
        title_card_dir = (
            out_root / f"{chapter_id}_titles" if with_titles else None)
        paths, durations, skipped = build_deck_entries(
            scenes,
            title_card_dir=title_card_dir,
            chapter_title=chapter_label)
        if not paths:
            QMessageBox.information(
                self, "Nothing to stitch",
                "None of this chapter's scenes have a usable "
                "favorite output. Generate clips / images first, "
                "then mark the ones you want included as "
                "favorite.\n\nSkipped:\n  • "
                + "\n  • ".join(skipped[:8])
                + ("\n  • …" if len(skipped) > 8 else ""))
            return
        suggested = out_root / f"{safe_label}_deck.mp4"
        n = 1
        while suggested.exists():
            n += 1
            suggested = (
                out_root / f"{safe_label}_deck_{n:02d}.mp4")
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save chapter deck",
            str(suggested), "MP4 video (*.mp4)")
        if not out_str:
            return
        self._update_status(
            f"Stitching chapter deck — {len(scenes)} scene(s)…")
        result = stitch_clips(
            paths, Path(out_str), clip_durations=durations)
        if not result.success:
            QMessageBox.warning(
                self, "Export failed", result.error)
            self._update_status("")
            return
        total = sum(durations)
        msg = (
            f"Saved chapter deck:\n{result.output_path}\n\n"
            f"Stitched {len(scenes) - len(skipped)} scene(s)"
            + (f" + {len(scenes)} title card(s)" if with_titles
               else "")
            + f", ~{total:.1f}s total.")
        if skipped:
            msg += (
                f"\n\nSkipped {len(skipped)} scene(s):\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        QMessageBox.information(self, "Chapter deck exported", msg)
        self._update_status(
            f"Chapter deck saved: {Path(out_str).name}")

    def _save_chapter_deck_as_pptx(
        self, *, scenes, chapter_label, out_root, safe_label,
    ) -> None:
        """Compose the chapter into a .pptx via the deck_export
        helper. One slide per scene; embedded images, embedded
        movies for video / slideshow clips. python-pptx is an
        optional dep — when missing we surface a clear hint."""
        from src.video_studio.deck_export import (
            export_chapter_pptx)
        suggested = out_root / f"{safe_label}_deck.pptx"
        n = 1
        while suggested.exists():
            n += 1
            suggested = (
                out_root / f"{safe_label}_deck_{n:02d}.pptx")
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save chapter deck",
            str(suggested), "PowerPoint (*.pptx)")
        if not out_str:
            return
        self._update_status(
            f"Composing PowerPoint deck — "
            f"{len(scenes)} scene(s)…")
        success, message, skipped = export_chapter_pptx(
            scenes=scenes,
            output_path=Path(out_str),
            chapter_title=chapter_label)
        if not success:
            QMessageBox.warning(
                self, "Export failed", message)
            self._update_status("")
            return
        body = (
            f"Saved PowerPoint deck:\n{out_str}\n\n"
            f"Composed {len(scenes)} slide(s) for "
            f"{chapter_label}.")
        if skipped:
            body += (
                f"\n\nNotes:\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        QMessageBox.information(
            self, "Chapter deck exported", body)
        self._update_status(
            f"PowerPoint deck saved: {Path(out_str).name}")

    def _enumerate_chapters_with_scenes(
        self, studio: Any,
    ) -> list:
        """Return ``[(chapter_id, label, scene_count), ...]`` for
        every chapter the project knows about that has at least one
        scene attached. Label is "Ch. N — <title>" when both fields
        exist, falling back gracefully otherwise."""
        scene_chapter_ids = {
            getattr(s, "chapter_id", None) for s in studio.scenes
        }
        scene_chapter_ids.discard(None)
        scene_chapter_ids.discard("")
        if not scene_chapter_ids:
            return []
        # Resolve labels via the project's manuscript when available.
        ch_meta: dict = {}  # chapter_id → (number, title)
        if self._project is not None:
            ms = getattr(self._project, "manuscript", None)
            for ch in getattr(ms, "chapters", []) or []:
                if getattr(ch, "id", "") in scene_chapter_ids:
                    ch_meta[ch.id] = (
                        getattr(ch, "chapter_number", None),
                        getattr(ch, "title", "") or "")
        out: list = []
        for cid in scene_chapter_ids:
            count = sum(
                1 for s in studio.scenes
                if getattr(s, "chapter_id", None) == cid)
            number, title = ch_meta.get(cid, (None, ""))
            if number is not None and title:
                label = f"Ch. {number} — {title}"
            elif number is not None:
                label = f"Ch. {number}"
            elif title:
                label = title
            else:
                label = f"Chapter ({cid[:8]}…)"
            out.append((cid, label, count))
        # Order by chapter number when known, label otherwise.
        out.sort(key=lambda t: (
            ch_meta.get(t[0], (9999, ""))[0] or 9999, t[1]))
        return out

    def _stitch_favorites(self) -> None:
        studio = self._studio()
        if studio is None or not studio.scenes:
            QMessageBox.information(
                self, "Nothing to stitch",
                "Add some scenes and generate clips first.")
            return
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Stitching needs ffmpeg on PATH. Install it "
                "(brew install ffmpeg / apt install ffmpeg) and try "
                "again. The rest of the studio works without it.")
            return
        # Build the order: BFS from the first scene that has any
        # outgoing hops, else just the scene list order.
        start_id = (
            studio.scenes[0].id if studio.scenes else "")
        ordered_scenes = (
            studio.topological_order_starting_at(start_id)
            if start_id else [])
        if not ordered_scenes:
            ordered_scenes = list(studio.scenes)
        clip_paths: List[Path] = []
        clip_durations: List[float] = []
        skipped = 0
        for s in ordered_scenes:
            fav = s.favorite_clip()
            if fav is None or not fav.file_path or fav.is_placeholder:
                skipped += 1
                continue
            p = Path(fav.file_path)
            if not p.exists():
                skipped += 1
                continue
            clip_paths.append(p)
            # For image stills, ``fav.duration_seconds`` was captured
            # at generation time from scene.image_display_seconds —
            # that's the hold time we want. For video clips the
            # value is the clip length; ffmpeg ignores ``-t`` on
            # already-encoded videos in the manifest, so passing the
            # length through is harmless.
            clip_durations.append(float(fav.duration_seconds) or 4.0)
        if not clip_paths:
            QMessageBox.information(
                self, "Nothing to stitch",
                "No favorite clips found that are real video files. "
                "Generate clips with an installed backend first, "
                "then mark favorites.")
            return
        # Pick output path. Anchored to the studio root so it lands
        # alongside the per-scene output folders, not inside the
        # .writerproj file (which would explode with
        # NotADirectoryError).
        suggested = self._studio_root_dir() / "stitched.mp4"
        suggested.parent.mkdir(parents=True, exist_ok=True)
        out_str, _ = QFileDialog.getSaveFileName(
            self, "Save stitched video",
            str(suggested),
            "MP4 video (*.mp4)")
        if not out_str:
            return
        result = stitch_clips(
            clip_paths, Path(out_str),
            clip_durations=clip_durations)
        if not result.success:
            QMessageBox.warning(
                self, "Stitch failed", result.error)
            return
        # The stitch's true purpose is to hand the writer a finished
        # MP4 they can lay voiceover over — open the video editor
        # immediately rather than make them confirm. The editor
        # itself is dismissable if they decide they're done.
        skipped_note = (
            f" Skipped {skipped} (no favorite / placeholder / "
            f"missing)."
            if skipped else "")
        self._update_status(
            f"Stitched {len(clip_paths)} clip(s) → "
            f"{Path(result.output_path).name}.{skipped_note}")
        self._open_video_editor(Path(result.output_path))

    def _open_video_editor(self, video_path: Path) -> None:
        """Open the post-stitch video editor on a finished MP4.

        Reusable from anywhere that produces a final video (the
        favorites stitcher today; the slide editor's MP4 export
        wires through here too on demand)."""
        from src.ui.video_studio.video_editor_dialog import (
            VideoEditorDialog)
        if not video_path.exists():
            QMessageBox.warning(
                self, "Missing file",
                f"Could not find {video_path}. The stitch may "
                "have failed silently — check the status line.")
            return
        self._update_status(
            f"Opening video editor on {video_path.name}…")
        working_dir = (
            self._studio_root_dir() / "video_editor_takes"
            / video_path.stem)
        working_dir.mkdir(parents=True, exist_ok=True)
        try:
            editor = VideoEditorDialog(
                source_path=video_path,
                working_dir=working_dir,
                chapters_provider=(
                    self._chapters_snapshot_for_reading),
                save_chapter_text=self._save_chapter_text,
                open_in_writer=self._jump_to_writer,
                load_session=self._load_video_editor_session,
                save_session=self._save_video_editor_session,
                session_record_provider=(
                    self._video_editor_session_record),
                parent=self)
        except Exception as e:
            # Catch any construction failure (multimedia plugin
            # missing, codec init crash, etc.) and surface it
            # instead of letting the call site silently swallow it.
            QMessageBox.critical(
                self, "Video editor failed to open",
                f"The video editor couldn't be constructed:\n\n{e}"
                f"\n\nThe stitched file is still saved at:\n"
                f"{video_path}")
            return
        # Hold a reference so Python doesn't garbage-collect the
        # non-modal window the instant this method returns.
        self._active_video_editor = editor
        # Flush save the moment the dialog closes — see the
        # slide-editor opener for the rationale. Without this,
        # any take recorded right before the writer closes the
        # editor and quits the app could sit in the 2.5 s
        # autosave debounce window and never reach disk.
        try:
            editor.finished.connect(
                lambda *_: self.flushSaveRequested.emit())
        except Exception:
            # Some VideoEditorDialog incarnations may lack a
            # standard ``finished`` signal — don't crash the
            # opener if so; the debounce path still catches
            # mid-session edits via ``_save_video_editor_session``.
            pass
        # Non-modal show — the writer can keep the studio in
        # focus, the dialog still surfaces on its own. show +
        # raise + activate force focus across platforms.
        # ``show()`` alone — see the slide-editor opener for why
        # raise_() / activateWindow() are bad here. macOS treats
        # the focus grab as "this app wants to take over the
        # display" and starts minimizing peers + can blank a
        # second monitor.
        editor.show()

    # ------------------------------------------------------------------
    # Chapter access for the slim prose editor
    # ------------------------------------------------------------------
    def _load_video_editor_session(
        self, source_path,
    ):
        """Find the saved video-editor session for ``source_path``
        and return its voiceover list (deep-copied so the editor
        can mutate freely without touching the project until it
        calls back into ``_save_video_editor_session``). Returns
        an empty list when no prior session exists or when the
        project isn't ready."""
        from pathlib import Path as _P
        studio = self._studio()
        if studio is None:
            return []
        key = str(_P(source_path).resolve())
        for sess in (
                getattr(studio, "video_editor_sessions", [])
                or []):
            if (sess.source_path
                    and _P(sess.source_path).resolve()
                    == _P(key).resolve()):
                # Deep-copy so the editor's mutations don't
                # leak into the stored model until it explicitly
                # saves them back through the save callback.
                return [v.model_copy(deep=True)
                        for v in sess.voiceovers]
        return []

    def _video_editor_session_record(self, source_path):
        """Return the live (mutable) ``VideoEditorSession`` so
        callers like the video editor's mic picker can read
        ``microphone_device_name`` without copying. Returns None
        when no session exists or the project isn't ready."""
        from pathlib import Path as _P
        studio = self._studio()
        if studio is None:
            return None
        key = str(_P(source_path).resolve())
        for sess in (
                getattr(studio, "video_editor_sessions", [])
                or []):
            if (sess.source_path
                    and _P(sess.source_path).resolve()
                    == _P(key).resolve()):
                return sess
        return None

    def _save_video_editor_session(
        self, source_path, voiceovers, working_dir=None,
        microphone_device_name=None,
    ) -> bool:
        """Persist the editor's current voiceover list back to
        the studio's ``video_editor_sessions``. Creates a new
        session when none exists for this source path; otherwise
        replaces the voiceovers list and bumps ``updated_at``.
        Fires ``contentChanged`` so the autosave timer flushes
        the project file shortly after."""
        from pathlib import Path as _P
        from datetime import datetime as _dt
        from src.video_studio.models import VideoEditorSession
        studio = self._studio()
        if studio is None:
            return False
        key = str(_P(source_path).resolve())
        target = None
        for sess in (
                getattr(studio, "video_editor_sessions", [])
                or []):
            if (sess.source_path
                    and _P(sess.source_path).resolve()
                    == _P(key).resolve()):
                target = sess
                break
        if target is None:
            target = VideoEditorSession(
                source_path=key,
                working_dir=str(working_dir or ""))
            if not hasattr(studio, "video_editor_sessions"):
                studio.video_editor_sessions = []
            studio.video_editor_sessions.append(target)
        # Replace the voiceovers list with deep copies so the
        # editor's later edits don't shadow the saved state.
        target.voiceovers = [
            v.model_copy(deep=True) for v in voiceovers]
        target.updated_at = _dt.now()
        if working_dir and not target.working_dir:
            target.working_dir = str(working_dir)
        # Mic name is opt-in via kwarg so callers that don't care
        # don't overwrite a previously-saved choice with empty.
        if microphone_device_name is not None:
            target.microphone_device_name = (
                microphone_device_name or "")
        self.contentChanged.emit()
        return True

    def _save_chapter_text(
        self, chapter_id: str, new_text: str,
    ) -> bool:
        """Write the slim editor's edits back to the live
        chapter. Looks up the chapter on
        ``project.manuscript.chapters`` by id and assigns
        ``chapter.content``. Returns True on success so the
        prose window can clear its dirty flag.

        The studio's ``contentChanged`` signal fires after the
        write so the main window's autosave timer picks the
        change up the same way it does for any other in-app edit.
        """
        project = self._project
        if project is None or not chapter_id:
            return False
        manuscript = getattr(project, "manuscript", None)
        if manuscript is None:
            return False
        for ch in getattr(manuscript, "chapters", []) or []:
            if getattr(ch, "id", "") == chapter_id:
                try:
                    ch.content = new_text
                except Exception:
                    return False
                from datetime import datetime
                try:
                    ch.updated_at = datetime.now()
                except Exception:
                    pass
                # ``contentChanged`` triggers the project
                # autosave; ``chapterContentChanged`` lets the
                # main window refresh the Write tab if it's on
                # the same chapter so the two views stay in
                # sync.
                self.chapterContentChanged.emit(chapter_id)
                self.contentChanged.emit()
                return True
        return False

    # Signal the main window listens for to jump to the writer
    # tab and focus a specific chapter. The handler usually:
    #   * Switches the main tab widget to the Writer pane.
    #   * Opens the chapter in the manuscript editor.
    # When nothing is connected, the click is a no-op (with a
    # gentle status message) so the dialog at least stops being
    # confusing.
    jumpToWriterRequested = pyqtSignal(str)  # chapter_id

    # Fired AFTER the slim prose editor (slide / video editor)
    # writes a chapter's new ``content`` back to the project
    # model. The main window listens so it can refresh the
    # manuscript editor's visible buffer when the writer is
    # editing the same chapter in two surfaces — without this
    # signal, the Write tab kept showing stale prose after a
    # save from the slide deck editor.
    chapterContentChanged = pyqtSignal(str)  # chapter_id

    # Like ``contentChanged`` but asks the host to SAVE NOW —
    # synchronously, bypassing any debounce. Emitted from
    # close/finish paths of editor dialogs (slide editor,
    # video editor) so the writer's last in-place mutations
    # (audio takes, slide trims, group reorders, transitions)
    # are flushed to disk the moment the dialog closes.
    # Without this, the 2.5 s autosave debounce could swallow
    # the final edit if the writer quits the app within that
    # window — they'd reopen and see stale state.
    flushSaveRequested = pyqtSignal()

    def _jump_to_writer(self, chapter_id: str) -> None:
        """Emitted from the slim editor's 📝 Open in writer
        button. Lets the main window route the writer to the
        correct chapter."""
        self.jumpToWriterRequested.emit(chapter_id or "")

    def _scenes_snapshot_for_reading(self):
        """Return the live list of scenes for read-only walks
        (e.g. the group editor's "Sync favorites from actions"
        button needs to enumerate every action's favorite image
        across every scene). Returns ``[]`` when no studio is
        attached. The list is the LIVE one — callers should
        only read, never mutate, because mutations bypass the
        studio's own dirty / autosave plumbing."""
        studio = self._studio()
        if studio is None:
            return []
        return list(
            getattr(studio, "scenes", []) or [])

    def _chapters_snapshot_for_reading(self):
        """Flatten the project's chapters into a list of
        ``(chapter_id, label, text)`` triples suitable for the
        floating ChapterProseWindow. Tolerates different shapes
        of the project model — the writer's project carries
        chapters as ``manuscript.chapters`` with ``content`` or
        ``html_content`` text fields."""
        project = self._project
        if project is None:
            return []
        manuscript = getattr(project, "manuscript", None)
        if manuscript is None:
            return []
        out = []
        for ch in getattr(manuscript, "chapters", []) or []:
            cid = getattr(ch, "id", "") or ""
            title = (getattr(ch, "title", "") or "").strip()
            number = getattr(ch, "chapter_number", None)
            if title and number is not None:
                label = f"Ch. {number} — {title}"
            elif number is not None:
                label = f"Chapter {number}"
            elif title:
                label = title
            else:
                label = f"Chapter ({cid[:8]}…)" if cid else "Chapter"
            text = (
                getattr(ch, "content", "")
                or getattr(ch, "text", "")
                or "")
            # Strip basic HTML when present — the prose window
            # shows plain text only. Falls back to the raw string
            # if BeautifulSoup isn't around.
            if text and "<" in text and ">" in text:
                try:
                    from bs4 import BeautifulSoup
                    text = BeautifulSoup(
                        text, "html.parser").get_text(
                            separator="\n")
                except Exception:
                    pass
            out.append((cid, label, text))
        return out
