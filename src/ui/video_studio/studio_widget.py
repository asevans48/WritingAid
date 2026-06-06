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
    QComboBox, QDialog, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
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
        # Restore last selected backend.
        if studio.backend_preference:
            b = get_backend(studio.backend_preference)
            if b is not None:
                self._current_backend = b
        self._canvas.load_studio(studio)
        self._sync_backend_picker()
        self._refresh_backend_info()
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

        # ── Toolbar row ───────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._add_scene_btn = QPushButton("➕ Add scene")
        self._add_scene_btn.setToolTip(
            "Drop a new empty scene on the canvas (at the first "
            "free grid cell).")
        self._add_scene_btn.clicked.connect(
            lambda: self._add_scene_at_first_free_cell())
        toolbar.addWidget(self._add_scene_btn)

        self._ai_fill_btn = QPushButton("✨ AI-fill from chapter")
        self._ai_fill_btn.setToolTip(
            "Use the AI director to storyboard a chapter into a "
            "sequence of scenes. Uses graph-aware RAG for grounding.")
        self._ai_fill_btn.clicked.connect(self._ai_fill_from_chapter)
        toolbar.addWidget(self._ai_fill_btn)

        toolbar.addWidget(self._vline())

        toolbar.addWidget(QLabel("Video:"))
        self._backend_combo = QComboBox()
        for b in all_backends():
            self._backend_combo.addItem(
                b.label + (" ✓" if b.is_installed() else "  (install)"),
                b.name)
        self._backend_combo.currentIndexChanged.connect(
            self._on_backend_changed)
        toolbar.addWidget(self._backend_combo)

        toolbar.addWidget(QLabel("Image:"))
        self._image_backend_combo = QComboBox()
        for b in all_image_backends():
            self._image_backend_combo.addItem(
                b.label + (" ✓" if b.is_installed() else "  (install)"),
                b.name)
        self._image_backend_combo.currentIndexChanged.connect(
            self._on_image_backend_changed)
        self._image_backend_combo.setToolTip(
            "Backend used when 'Generate image still' is invoked "
            "from a scene's context menu.")
        toolbar.addWidget(self._image_backend_combo)

        self._install_help_btn = QPushButton("Install / Help")
        self._install_help_btn.setToolTip(
            "Install this backend in-app, or read the manual install "
            "instructions if it doesn't support automated install.")
        self._install_help_btn.clicked.connect(
            self._show_install_help)
        toolbar.addWidget(self._install_help_btn)

        toolbar.addWidget(self._vline())

        self._stitch_btn = QPushButton("🎬 Stitch favorites")
        self._stitch_btn.setToolTip(
            "Concatenate every scene's favorite clip into a single "
            "video, in the order their hops define (BFS from the "
            "first scene).")
        self._stitch_btn.clicked.connect(self._stitch_favorites)
        toolbar.addWidget(self._stitch_btn)

        toolbar.addWidget(self._vline())

        # ---- Storyboard board management ----
        self._save_board_btn = QPushButton("Save board…")
        self._save_board_btn.setToolTip(
            "Export the current storyboard (scenes, hops, character "
            "references, narration metadata) as a standalone JSON "
            "file. Reusable across projects.")
        self._save_board_btn.clicked.connect(self._save_storyboard)
        toolbar.addWidget(self._save_board_btn)

        self._load_board_btn = QPushButton("Load board…")
        self._load_board_btn.setToolTip(
            "Load a storyboard JSON file, replacing the current "
            "board. Asks for confirmation before discarding any "
            "existing scenes.")
        self._load_board_btn.clicked.connect(self._load_storyboard)
        toolbar.addWidget(self._load_board_btn)

        self._arrange_btn = QPushButton("Arrange")
        self._arrange_btn.setToolTip(
            "Re-flow scene cards into a tidy grid. Order follows "
            "the hops (topological) when possible; falls back to "
            "creation order on cycles.")
        self._arrange_btn.clicked.connect(self._auto_arrange_board)
        toolbar.addWidget(self._arrange_btn)

        self._clear_board_btn = QPushButton("Clear")
        self._clear_board_btn.setToolTip(
            "Delete every scene and hop on the board. Character "
            "references and backend preferences are kept.")
        self._clear_board_btn.clicked.connect(self._clear_board)
        toolbar.addWidget(self._clear_board_btn)

        self._fit_view_btn = QPushButton("Fit")
        self._fit_view_btn.setToolTip(
            "Zoom and pan so the whole board fits in view. "
            "Ctrl + mouse wheel zooms manually.")
        self._fit_view_btn.clicked.connect(self._fit_canvas_to_view)
        toolbar.addWidget(self._fit_view_btn)

        self._toggle_side_btn = QPushButton("▶◀")
        self._toggle_side_btn.setToolTip(
            "Collapse / expand the right-hand info panel.")
        self._toggle_side_btn.setCheckable(True)
        self._toggle_side_btn.setChecked(True)  # panel starts open
        self._toggle_side_btn.clicked.connect(self._toggle_side_panel)
        toolbar.addWidget(self._toggle_side_btn)

        toolbar.addStretch()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #475569;")
        toolbar.addWidget(self._status_label)
        root.addLayout(toolbar)

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
    # Backend picker
    # ------------------------------------------------------------------
    def _sync_backend_picker(self) -> None:
        for i in range(self._backend_combo.count()):
            if self._backend_combo.itemData(i) == self._current_backend.name:
                self._backend_combo.setCurrentIndex(i)
                return

    def _on_backend_changed(self, index: int) -> None:
        name = self._backend_combo.itemData(index)
        b = get_backend(name)
        if b is None:
            return
        self._current_backend = b
        studio = self._studio()
        if studio is not None:
            studio.backend_preference = b.name
            self.contentChanged.emit()
        self._refresh_backend_info()

    def _on_image_backend_changed(self, index: int) -> None:
        name = self._image_backend_combo.itemData(index)
        b = get_image_backend(name)
        if b is None:
            return
        self._current_image_backend = b
        # Image backend preference stored separately so the picker
        # restores correctly across sessions.
        studio = self._studio()
        if studio is not None and hasattr(studio,
                                            "image_backend_preference"):
            studio.image_backend_preference = b.name
            self.contentChanged.emit()

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
                "Pick another backend in the toolbar to render "
                "actual video."
                "</span>")
        elif installed:
            self._backend_status.setText(
                "<span style='color:#15803d'>"
                "Installed and ready.</span>")
        else:
            self._backend_status.setText(
                "<span style='color:#b91c1c'>"
                "Not installed — generate will fail. Click "
                "<b>Install / Help</b> on the toolbar to set up."
                "</span>")
        self._backend_desc.setText(b.description)
        self._install_help_btn.setEnabled(not installed
                                          or b.name != "placeholder")

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
        # may have just become available.
        self._refresh_backend_info()
        # Refresh the backend combo's "✓ / (install)" badge too.
        for i in range(self._backend_combo.count()):
            name = self._backend_combo.itemData(i)
            backend = get_backend(name)
            if backend is None:
                continue
            badge = " ✓" if backend.is_installed() else "  (install)"
            self._backend_combo.setItemText(i, backend.label + badge)

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
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # The dialog mutated the scene in place; refresh card.
            self._canvas.refresh_scene_card(scene_id)
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
        # When the scene has user-curated actions, give the backend
        # an explicit shot list — most video models follow ordered
        # beats better than a single dense prompt.
        full_prompt = scene.prompt
        if scene.actions:
            beats = []
            for idx, a in enumerate(scene.actions, start=1):
                line = f"{idx}. {a.name}"
                if a.description:
                    line += f" — {a.description}"
                if a.scenery_details:
                    line += f" Scenery: {a.scenery_details}"
                if a.prose_excerpt:
                    line += f" Prose: {a.prose_excerpt}"
                beats.append(line)
            full_prompt = (
                f"{scene.prompt.strip()}\n\n"
                f"Action sequence:\n" + "\n".join(beats))
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

    def _ensure_resources_for(self, backend: VideoBackend) -> bool:
        """Pre-flight RAM + VRAM check for ``backend.generate()``.

        Returns True when generation is safe to proceed. When the
        live snapshot is short of the backend's declared
        requirements, prompts the user to free other models — if
        they accept, drops local LLM weights + shared model cache +
        accelerator caches and re-checks. If still short, surfaces a
        clear blocker dialog and returns False (caller skips the
        generate call rather than risk an OOM mid-render).
        """
        reqs = backend.memory_requirements()
        # Cheap exit when the backend declares no requirements
        # (placeholder, cloud-API backends).
        if reqs.vram_mb == 0 and reqs.ram_mb == 0:
            return True
        result = resource_manager.check(reqs)
        if result.satisfied:
            return True
        # First-pass short — offer to evict.
        snap = result.snapshot
        msg = (
            f"This backend may not have enough memory to run:\n\n"
            f"  Needs: {reqs.ram_mb} MB RAM, "
            f"{reqs.vram_mb} MB VRAM\n"
            f"  Available: {snap.ram_available_mb} MB RAM, "
            f"{snap.vram_available_mb} MB VRAM "
            f"({snap.accelerator.upper()})\n\n"
            f"{result.explanation}\n\n"
            "Drop any loaded LLM and shared model cache to free "
            "memory, then retry?")
        reply = QMessageBox.question(
            self, "Memory budget tight", msg,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            self._update_status("Generation cancelled by user.")
            return False
        # Evict and re-check.
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
        # Still short — block.
        QMessageBox.warning(
            self, "Still short on memory",
            "Even after freeing other models the system doesn't "
            "have enough headroom for this backend.\n\n"
            f"{result2.explanation}\n\n"
            "Close other heavy apps, switch to a smaller backend "
            "variant, or use a machine with more RAM/VRAM.")
        self._update_status("")
        return False

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
        backend = self._current_image_backend
        if not backend.is_installed():
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

        req = ImageGenerationRequest(
            prompt=scene.prompt,
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
            prompt_at_generation=scene.prompt,
            duration_seconds=display,
            is_placeholder=result.is_placeholder,
            clip_type="image_still",
        )
        scene.add_clip(clip)
        self._canvas.refresh_scene_card(scene_id)
        self.contentChanged.emit()
        self._update_status(
            f"Image still added to '{scene.name}' (display "
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
        backend = self._current_image_backend
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

    def _stitch_slide_deck_for_scene(self, scene_id: str) -> None:
        """Stitch this scene's per-action images into a single
        slide-deck video. Walks the actions in order, picks the
        favorite image for each (or the first ``included_in_slideshow``
        if no favorite set), and holds each slide for either the
        action's own ``display_seconds`` or — when that's 0 — the
        scene's ``image_display_seconds``.

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
        # Collect one image per action, in order. Favorite first;
        # fall back to first included; skip the action when no
        # included image exists so the user sees a clean error
        # instead of a half-stitched deck.
        clip_paths: List[Path] = []
        clip_durations: List[float] = []
        scene_default = float(scene.image_display_seconds or 4.0)
        missing_actions: List[str] = []
        for action in scene.actions:
            included = action.included_images()
            if not included:
                missing_actions.append(action.name or action.id)
                continue
            chosen = action.favorite_image() or included[0]
            if (not chosen or not chosen.file_path
                    or not Path(chosen.file_path).exists()):
                missing_actions.append(action.name or action.id)
                continue
            dur = float(action.display_seconds or 0.0)
            if dur <= 0:
                dur = scene_default
            clip_paths.append(Path(chosen.file_path))
            clip_durations.append(max(0.5, dur))
        if not clip_paths:
            QMessageBox.information(
                self, "Nothing to stitch",
                "This scene has no included action images yet. "
                "Click the 📑 Deck button (or use 'Generate slide "
                "deck' from the right-click menu) first, then try "
                "again.")
            return
        if missing_actions:
            # Confirm — partial stitches are common while iterating.
            reply = QMessageBox.question(
                self, "Skip actions without images?",
                f"{len(missing_actions)} action(s) have no included "
                f"image yet and will be skipped:\n  • "
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
        backend = self._current_image_backend
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
        # Compose a prompt that fuses the scene's overall prompt
        # with the action's specifics so the image stays inside the
        # scene's visual frame.
        action_prompt = (
            f"{(scene.prompt or '').strip()}. "
            f"Action: {action.name}. {action.description}").strip()
        if action.scenery_details:
            action_prompt += f" Scenery: {action.scenery_details}."
        # Include the verbatim prose excerpt when present — gives
        # the image model the writer's exact language, which often
        # carries detail the structured fields don't capture.
        if action.prose_excerpt:
            action_prompt += f" Prose: {action.prose_excerpt}"
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
            f"Generating image for action '{action.name}'…")
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
            f"Image added for action '{action.name}'"
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
        msg = (
            f"Saved stitched video to:\n{result.output_path}\n\n"
            f"Combined {len(clip_paths)} clip(s)."
            + (f"\nSkipped {skipped} (no favorite / placeholder / "
               f"missing)." if skipped else ""))
        QMessageBox.information(self, "Stitched", msg)
