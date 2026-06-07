"""Video Studio Widget — grid-based storyboard for AI video generation.

Supports two entry flows:
  Flow 1: User selects a chapter, prompts AI to generate scenes.
  Flow 2: User manually adds scenes one at a time.
Both flows can be mixed freely — AI-generated scenes can be rearranged
or manually edited, and manual scenes can be enriched by AI.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QThread
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QScrollArea, QFrame,
    QMessageBox, QProgressDialog, QSplitter, QSpinBox,
    QMenu, QSizePolicy, QApplication, QDialog, QDialogButtonBox,
    QLineEdit, QFormLayout, QTabWidget, QGroupBox, QListWidget,
    QListWidgetItem, QCheckBox,
)

from src.models.project import (
    VideoScene, VideoProject, WriterProject, Character, Chapter,
)


# ═══════════════════════════════════════════════════════════════════════════
# Worker threads
# ═══════════════════════════════════════════════════════════════════════════

class _SceneGenerationWorker(QThread):
    """Background worker: ask AI to generate scenes from a chapter."""
    finished = pyqtSignal(list)  # list[VideoScene]
    error = pyqtSignal(str)

    def __init__(
        self,
        chapter_text: str,
        chapter_id: str,
        num_scenes: int,
        characters: list[Character],
        worldbuilding_context: str,
        user_direction: str,
    ):
        super().__init__()
        self.chapter_text = chapter_text
        self.chapter_id = chapter_id
        self.num_scenes = num_scenes
        self.characters = characters
        self.worldbuilding_context = worldbuilding_context
        self.user_direction = user_direction

    def run(self):
        try:
            from src.ai.video_generation_agent import get_video_generation_agent
            agent = get_video_generation_agent()
            scenes = agent.generate_scenes_from_chapter(
                chapter_text=self.chapter_text,
                chapter_id=self.chapter_id,
                num_scenes=self.num_scenes,
                characters=self.characters,
                worldbuilding_context=self.worldbuilding_context,
                user_direction=self.user_direction,
            )
            self.finished.emit(scenes)
        except Exception as exc:
            self.error.emit(str(exc))


class _PromptOptimizeWorker(QThread):
    """Background worker: optimise a single scene's prompt via AI."""
    finished = pyqtSignal(str, str)  # scene_id, optimized_prompt
    error = pyqtSignal(str, str)  # scene_id, error_message

    def __init__(
        self,
        scene: VideoScene,
        characters: list[Character],
        worldbuilding_context: str,
        chapter_text: str,
    ):
        super().__init__()
        self.scene = scene
        self.characters = characters
        self.worldbuilding_context = worldbuilding_context
        self.chapter_text = chapter_text

    def run(self):
        try:
            from src.ai.video_generation_agent import get_video_generation_agent
            agent = get_video_generation_agent()
            optimized = agent.optimize_prompt(
                scene=self.scene,
                characters=self.characters,
                worldbuilding_context=self.worldbuilding_context,
                chapter_text=self.chapter_text,
            )
            self.finished.emit(self.scene.id, optimized)
        except Exception as exc:
            self.error.emit(self.scene.id, str(exc))


class _VideoRenderWorker(QThread):
    """Background worker: generate a video clip for one scene."""
    finished = pyqtSignal(str, str)  # scene_id, video_path
    error = pyqtSignal(str, str)  # scene_id, error_message
    progress = pyqtSignal(int)

    def __init__(
        self,
        scene: VideoScene,
        model_id: str,
        output_dir: Path,
        fps: int,
        resolution: str,
    ):
        super().__init__()
        self.scene = scene
        self.model_id = model_id
        self.output_dir = output_dir
        self.fps = fps
        self.resolution = resolution

    def run(self):
        try:
            from src.ai.video_generation_agent import get_video_generation_agent
            agent = get_video_generation_agent()
            path = agent.generate_video(
                scene=self.scene,
                model_id=self.model_id,
                output_dir=self.output_dir,
                fps=self.fps,
                resolution=self.resolution,
            )
            self.finished.emit(self.scene.id, str(path))
        except Exception as exc:
            self.error.emit(self.scene.id, str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# Scene Card (individual grid cell)
# ═══════════════════════════════════════════════════════════════════════════

class SceneCard(QFrame):
    """Visual card representing a single VideoScene in the storyboard grid."""

    clicked = pyqtSignal(str)  # scene_id
    double_clicked = pyqtSignal(str)  # scene_id → open editor
    drag_started = pyqtSignal(str)
    request_delete = pyqtSignal(str)
    request_generate = pyqtSignal(str)
    request_optimize = pyqtSignal(str)

    _STATUS_COLORS = {
        "draft": "#f3f4f6",
        "generating": "#fef3c7",
        "completed": "#d1fae5",
        "failed": "#fee2e2",
    }

    def __init__(self, scene: VideoScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._selected = False
        self.setFixedSize(220, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Order badge + title row
        top_row = QHBoxLayout()
        self.order_label = QLabel()
        self.order_label.setFixedSize(24, 24)
        self.order_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.order_label.setStyleSheet(
            "background: #4f46e5; color: white; border-radius: 12px; "
            "font-weight: bold; font-size: 11px;"
        )
        top_row.addWidget(self.order_label)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.title_label.setWordWrap(True)
        top_row.addWidget(self.title_label, 1)
        layout.addLayout(top_row)

        # Thumbnail / placeholder
        self.thumb_label = QLabel("No video yet")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFixedHeight(70)
        self.thumb_label.setStyleSheet(
            "background: #e5e7eb; border-radius: 4px; color: #6b7280; "
            "font-size: 10px;"
        )
        layout.addWidget(self.thumb_label)

        # Prompt preview
        self.prompt_preview = QLabel()
        self.prompt_preview.setWordWrap(True)
        self.prompt_preview.setMaximumHeight(36)
        self.prompt_preview.setStyleSheet("color: #6b7280; font-size: 10px;")
        layout.addWidget(self.prompt_preview)

        # Status + duration row
        bottom = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 9px;")
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        self.duration_label = QLabel()
        self.duration_label.setStyleSheet("font-size: 9px; color: #9ca3af;")
        bottom.addWidget(self.duration_label)
        layout.addLayout(bottom)

    def refresh(self):
        """Update visuals from the scene model."""
        s = self.scene
        self.order_label.setText(str(s.order + 1))
        self.title_label.setText(s.title or "Untitled Scene")
        prompt_text = s.prompt[:80] + ("…" if len(s.prompt) > 80 else "") if s.prompt else "No prompt"
        self.prompt_preview.setText(prompt_text)
        self.status_label.setText(s.status.capitalize())
        self.duration_label.setText(f"{s.duration_seconds:.1f}s")

        bg = self._STATUS_COLORS.get(s.status, "#f3f4f6")
        border_color = "#4f46e5" if self._selected else "#d1d5db"
        border_width = "2px" if self._selected else "1px"
        self.setStyleSheet(
            f"SceneCard {{ background: {bg}; border: {border_width} solid "
            f"{border_color}; border-radius: 8px; }}"
        )

        if s.thumbnail_path and Path(s.thumbnail_path).exists():
            pix = QPixmap(s.thumbnail_path).scaled(
                200, 70, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_label.setPixmap(pix)
        elif s.status == "completed":
            self.thumb_label.setText("Video ready")
            self.thumb_label.setStyleSheet(
                "background: #d1fae5; border-radius: 4px; color: #065f46; "
                "font-size: 10px; font-weight: bold;"
            )
        elif s.status == "generating":
            self.thumb_label.setText("Generating…")
            self.thumb_label.setStyleSheet(
                "background: #fef3c7; border-radius: 4px; color: #92400e; "
                "font-size: 10px;"
            )

    def set_selected(self, selected: bool):
        self._selected = selected
        self.refresh()

    # -- Events --
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.scene.id)
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.scene.id)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            dist = (event.pos() - self._drag_start).manhattanLength()
            if dist >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setText(self.scene.id)
                drag.setMimeData(mime)
                # Mini pixmap for drag feedback
                pix = QPixmap(self.size())
                self.render(pix)
                drag.setPixmap(pix.scaled(
                    110, 90, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                drag.exec(Qt.DropAction.MoveAction)
        super().mouseMoveEvent(event)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Edit Scene…", lambda: self.double_clicked.emit(self.scene.id))
        menu.addAction("Optimize Prompt (AI)", lambda: self.request_optimize.emit(self.scene.id))
        menu.addSeparator()
        menu.addAction("Generate Video", lambda: self.request_generate.emit(self.scene.id))
        menu.addSeparator()
        menu.addAction("Delete Scene", lambda: self.request_delete.emit(self.scene.id))
        menu.exec(self.mapToGlobal(pos))


# ═══════════════════════════════════════════════════════════════════════════
# Scene Editor Dialog
# ═══════════════════════════════════════════════════════════════════════════

class SceneEditorDialog(QDialog):
    """Full editor for a single scene — prompt, description, characters,
    worldbuilding lookup, chapter excerpt, AI enrichment."""

    def __init__(
        self,
        scene: VideoScene,
        project: WriterProject,
        parent=None,
    ):
        super().__init__(parent)
        self.scene = scene
        self.project = project
        self._workers: list[QThread] = []
        self.setWindowTitle(f"Scene Editor — {scene.title or 'Untitled'}")
        self.resize(750, 620)
        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Tab 1: Prompt & Description ──────────────────────────────
        prompt_tab = QWidget()
        pl = QVBoxLayout(prompt_tab)

        fl = QFormLayout()
        self.title_edit = QLineEdit()
        fl.addRow("Title:", self.title_edit)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 30)
        self.duration_spin.setSuffix(" sec")
        fl.addRow("Duration:", self.duration_spin)
        pl.addLayout(fl)

        pl.addWidget(QLabel("Scene Prompt (what the camera sees):"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setMaximumHeight(100)
        pl.addWidget(self.prompt_edit)

        pl.addWidget(QLabel("Narrative Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        pl.addWidget(self.description_edit)

        # AI optimise button
        ai_row = QHBoxLayout()
        self.optimize_btn = QPushButton("Optimize Prompt with AI")
        self.optimize_btn.setStyleSheet(
            "QPushButton { background: #4f46e5; color: white; "
            "padding: 6px 16px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #4338ca; }"
        )
        self.optimize_btn.clicked.connect(self._on_optimize_prompt)
        ai_row.addStretch()
        ai_row.addWidget(self.optimize_btn)
        pl.addLayout(ai_row)

        pl.addWidget(QLabel("Optimised Prompt (sent to video model):"))
        self.optimized_edit = QTextEdit()
        self.optimized_edit.setMaximumHeight(80)
        self.optimized_edit.setStyleSheet("background: #f0fdf4;")
        pl.addWidget(self.optimized_edit)

        tabs.addTab(prompt_tab, "Prompt & Description")

        # ── Tab 2: Characters ────────────────────────────────────────
        char_tab = QWidget()
        cl = QVBoxLayout(char_tab)
        cl.addWidget(QLabel("Select characters present in this scene:"))
        self.char_list = QListWidget()
        self.char_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        cl.addWidget(self.char_list)
        tabs.addTab(char_tab, "Characters")

        # ── Tab 3: Worldbuilding ─────────────────────────────────────
        wb_tab = QWidget()
        wl = QVBoxLayout(wb_tab)
        wl.addWidget(QLabel("Worldbuilding notes relevant to this scene:"))
        self.wb_edit = QTextEdit()
        wl.addWidget(self.wb_edit)

        lookup_row = QHBoxLayout()
        self.wb_query_edit = QLineEdit()
        self.wb_query_edit.setPlaceholderText("Search worldbuilding elements…")
        lookup_row.addWidget(self.wb_query_edit)
        wb_lookup_btn = QPushButton("Lookup")
        wb_lookup_btn.clicked.connect(self._on_wb_lookup)
        lookup_row.addWidget(wb_lookup_btn)
        wl.addLayout(lookup_row)

        self.wb_results = QTextEdit()
        self.wb_results.setReadOnly(True)
        self.wb_results.setMaximumHeight(120)
        self.wb_results.setStyleSheet("background: #f9fafb;")
        wl.addWidget(self.wb_results)
        tabs.addTab(wb_tab, "Worldbuilding")

        # ── Tab 4: Chapter Text ──────────────────────────────────────
        ch_tab = QWidget()
        chl = QVBoxLayout(ch_tab)
        chl.addWidget(QLabel("Relevant chapter excerpt:"))
        self.chapter_text_edit = QTextEdit()
        chl.addWidget(self.chapter_text_edit)

        ch_lookup_row = QHBoxLayout()
        self.ch_query_edit = QLineEdit()
        self.ch_query_edit.setPlaceholderText("Search chapter text…")
        ch_lookup_row.addWidget(self.ch_query_edit)
        ch_lookup_btn = QPushButton("Find in Chapter")
        ch_lookup_btn.clicked.connect(self._on_chapter_lookup)
        ch_lookup_row.addWidget(ch_lookup_btn)
        chl.addLayout(ch_lookup_row)

        self.ch_results = QTextEdit()
        self.ch_results.setReadOnly(True)
        self.ch_results.setMaximumHeight(120)
        self.ch_results.setStyleSheet("background: #f9fafb;")
        chl.addWidget(self.ch_results)
        tabs.addTab(ch_tab, "Chapter Text")

        # ── Tab 5: AI Enrichment ─────────────────────────────────────
        ai_tab = QWidget()
        al = QVBoxLayout(ai_tab)
        al.addWidget(QLabel(
            "Ask AI to enrich this scene's prompt with character details, "
            "worldbuilding elements, and chapter context."
        ))
        self.enrich_btn = QPushButton("Enrich Scene with AI (GraphRAG)")
        self.enrich_btn.setStyleSheet(
            "QPushButton { background: #7c3aed; color: white; "
            "padding: 8px 20px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #6d28d9; }"
        )
        self.enrich_btn.clicked.connect(self._on_enrich_scene)
        al.addWidget(self.enrich_btn)
        self.enrich_status = QLabel("")
        al.addWidget(self.enrich_status)
        al.addStretch()
        tabs.addTab(ai_tab, "AI Enrichment")

        # ── Buttons ──────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._save_and_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate(self):
        s = self.scene
        self.title_edit.setText(s.title)
        self.duration_spin.setValue(int(s.duration_seconds))
        self.prompt_edit.setPlainText(s.prompt)
        self.description_edit.setPlainText(s.description)
        self.optimized_edit.setPlainText(s.optimized_prompt)
        self.wb_edit.setPlainText(s.worldbuilding_notes)
        self.chapter_text_edit.setPlainText(s.chapter_excerpt)

        # Character checkboxes
        for char in self.project.characters:
            item = QListWidgetItem()
            cb = QCheckBox(f"{char.name} — {char.physical_description[:60] if char.physical_description else 'no description'}")
            cb.setProperty("char_id", char.id)
            if char.id in s.character_ids:
                cb.setChecked(True)
            item.setSizeHint(cb.sizeHint())
            self.char_list.addItem(item)
            self.char_list.setItemWidget(item, cb)

    def _save_and_accept(self):
        s = self.scene
        s.title = self.title_edit.text().strip()
        s.duration_seconds = float(self.duration_spin.value())
        s.prompt = self.prompt_edit.toPlainText().strip()
        s.description = self.description_edit.toPlainText().strip()
        s.optimized_prompt = self.optimized_edit.toPlainText().strip()
        s.worldbuilding_notes = self.wb_edit.toPlainText().strip()
        s.chapter_excerpt = self.chapter_text_edit.toPlainText().strip()

        # Collect selected character ids
        ids: list[str] = []
        for i in range(self.char_list.count()):
            item = self.char_list.item(i)
            cb = self.char_list.itemWidget(item)
            if isinstance(cb, QCheckBox) and cb.isChecked():
                ids.append(cb.property("char_id"))
        s.character_ids = ids

        self.accept()

    # ── AI actions ────────────────────────────────────────────────────

    def _on_optimize_prompt(self):
        """Run prompt optimisation in background."""
        chars = [c for c in self.project.characters if c.id in self.scene.character_ids]
        # Temporarily sync from edits
        self.scene.prompt = self.prompt_edit.toPlainText().strip()
        self.scene.description = self.description_edit.toPlainText().strip()

        worker = _PromptOptimizeWorker(
            scene=self.scene,
            characters=chars,
            worldbuilding_context=self.wb_edit.toPlainText(),
            chapter_text=self.chapter_text_edit.toPlainText(),
        )
        worker.finished.connect(self._on_optimize_done)
        worker.error.connect(self._on_optimize_error)
        self._workers.append(worker)
        self.optimize_btn.setEnabled(False)
        self.optimize_btn.setText("Optimizing…")
        worker.start()

    def _on_optimize_done(self, _scene_id: str, optimized: str):
        self.optimized_edit.setPlainText(optimized)
        self.optimize_btn.setEnabled(True)
        self.optimize_btn.setText("Optimize Prompt with AI")

    def _on_optimize_error(self, _scene_id: str, msg: str):
        self.optimize_btn.setEnabled(True)
        self.optimize_btn.setText("Optimize Prompt with AI")
        QMessageBox.warning(self, "Optimisation Failed", msg)

    def _on_wb_lookup(self):
        """Search worldbuilding via RAG."""
        query = self.wb_query_edit.text().strip()
        if not query:
            return
        try:
            from src.ai.enhanced_rag import EnhancedRAGSystem
            rag = EnhancedRAGSystem(self.project)
            results = rag.search(
                query, top_k=5,
                source_types=["faction", "place", "technology", "culture",
                              "myth", "flora", "fauna", "historical_event"],
            )
            lines = []
            for r in results:
                lines.append(f"[{r.source_type}] {r.source_name}\n{r.content[:300]}\n")
            self.wb_results.setPlainText("\n".join(lines) if lines else "No results found.")
        except Exception as exc:
            self.wb_results.setPlainText(f"Search error: {exc}")

    def _on_chapter_lookup(self):
        """Search chapter text for a keyword / phrase."""
        query = self.ch_query_edit.text().strip().lower()
        if not query:
            return
        chapter = self._get_chapter()
        if not chapter:
            self.ch_results.setPlainText("No chapter associated with this scene.")
            return
        text = chapter.content or ""
        # Simple keyword search with context window
        snippets = []
        idx = 0
        lower_text = text.lower()
        while idx < len(lower_text):
            pos = lower_text.find(query, idx)
            if pos == -1:
                break
            start = max(0, pos - 100)
            end = min(len(text), pos + len(query) + 100)
            snippets.append(f"…{text[start:end]}…")
            idx = pos + len(query)
            if len(snippets) >= 5:
                break
        self.ch_results.setPlainText(
            "\n---\n".join(snippets) if snippets else "No matches found."
        )

    def _get_chapter(self) -> Optional[Chapter]:
        if not self.scene.chapter_id:
            return None
        for ch in self.project.manuscript.chapters:
            if ch.id == self.scene.chapter_id:
                return ch
        return None

    def _on_enrich_scene(self):
        """Use GraphRAG to pull in character + worldbuilding context and
        update the prompt, worldbuilding notes, and chapter excerpt."""
        self.enrich_status.setText("Enriching scene with GraphRAG…")
        self.enrich_btn.setEnabled(False)

        try:
            from src.ai.enhanced_rag import EnhancedRAGSystem
            rag = EnhancedRAGSystem(self.project)

            query = self.prompt_edit.toPlainText() or self.description_edit.toPlainText()
            if not query:
                self.enrich_status.setText("Enter a prompt or description first.")
                self.enrich_btn.setEnabled(True)
                return

            results = rag.search(query, top_k=8)

            wb_parts: list[str] = []
            char_parts: list[str] = []
            chapter_parts: list[str] = []

            for r in results:
                if r.source_type in ("faction", "place", "technology", "culture",
                                     "myth", "flora", "fauna", "historical_event"):
                    wb_parts.append(f"[{r.source_type}] {r.source_name}: {r.content[:300]}")
                elif r.source_type == "character":
                    char_parts.append(r.content[:300])
                elif r.source_type == "chapter":
                    chapter_parts.append(r.content[:400])

            if wb_parts:
                existing = self.wb_edit.toPlainText()
                self.wb_edit.setPlainText(
                    existing + ("\n\n" if existing else "") + "\n".join(wb_parts)
                )
            if chapter_parts:
                existing = self.chapter_text_edit.toPlainText()
                self.chapter_text_edit.setPlainText(
                    existing + ("\n\n" if existing else "") + "\n---\n".join(chapter_parts)
                )

            # Auto-check characters mentioned in results
            mentioned_names = {r.source_name.lower() for r in results if r.source_type == "character"}
            for i in range(self.char_list.count()):
                item = self.char_list.item(i)
                cb = self.char_list.itemWidget(item)
                if isinstance(cb, QCheckBox):
                    cid = cb.property("char_id")
                    char = next((c for c in self.project.characters if c.id == cid), None)
                    if char and char.name.lower() in mentioned_names:
                        cb.setChecked(True)

            self.enrich_status.setText(
                f"Done — found {len(results)} relevant context items."
            )
        except Exception as exc:
            self.enrich_status.setText(f"Error: {exc}")
        finally:
            self.enrich_btn.setEnabled(True)


# ═══════════════════════════════════════════════════════════════════════════
# Main Video Studio Widget
# ═══════════════════════════════════════════════════════════════════════════

class VideoStudioWidget(QWidget):
    """Top-level widget: toolbar + storyboard grid + AI panel."""

    content_changed = pyqtSignal()

    GRID_COLUMNS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[WriterProject] = None
        self._video_projects: list[VideoProject] = []
        self._current_vp: Optional[VideoProject] = None
        self._scene_cards: dict[str, SceneCard] = {}
        self._selected_scene_id: Optional[str] = None
        self._workers: list[QThread] = []
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # Video project selector
        toolbar.addWidget(QLabel("Project:"))
        self.vp_combo = QComboBox()
        self.vp_combo.setFixedWidth(150)
        self.vp_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.vp_combo.currentIndexChanged.connect(self._on_vp_changed)
        toolbar.addWidget(self.vp_combo)

        self.new_vp_btn = QPushButton("+ New")
        self.new_vp_btn.setFixedWidth(60)
        self.new_vp_btn.clicked.connect(self._on_new_video_project)
        toolbar.addWidget(self.new_vp_btn)

        toolbar.addWidget(self._vsep())

        # Chapter selector
        toolbar.addWidget(QLabel("Chapter:"))
        self.chapter_combo = QComboBox()
        self.chapter_combo.setFixedWidth(170)
        self.chapter_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toolbar.addWidget(self.chapter_combo)

        toolbar.addWidget(self._vsep())

        # Video model selector
        toolbar.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "Wan-AI/Wan2.1-T2V-14B",
            "Wan-AI/Wan2.1-T2V-1.3B",
            "ali-vilab/text-to-video-ms-1.7b",
            "damo-vilab/text-to-video-ms-1.7b",
        ])
        self.model_combo.setFixedWidth(210)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toolbar.addWidget(self.model_combo)

        toolbar.addStretch()

        # Output directory label
        self.output_label = QLabel("Output: (not set)")
        self.output_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        toolbar.addWidget(self.output_label)

        root.addLayout(toolbar)

        # ── Main content: splitter with grid + AI panel ───────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: storyboard grid inside scroll area
        grid_container = QWidget()
        grid_vbox = QVBoxLayout(grid_container)
        grid_vbox.setContentsMargins(0, 0, 0, 0)

        # Scene action buttons
        scene_toolbar = QHBoxLayout()
        self.add_scene_btn = QPushButton("+ Add Scene")
        self.add_scene_btn.setStyleSheet(
            "QPushButton { background: #10b981; color: white; "
            "padding: 5px 14px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #059669; }"
        )
        self.add_scene_btn.clicked.connect(self._on_add_scene)
        scene_toolbar.addWidget(self.add_scene_btn)

        self.gen_all_btn = QPushButton("Generate All Videos")
        self.gen_all_btn.setStyleSheet(
            "QPushButton { background: #4f46e5; color: white; "
            "padding: 5px 14px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #4338ca; }"
        )
        self.gen_all_btn.clicked.connect(self._on_generate_all)
        scene_toolbar.addWidget(self.gen_all_btn)

        scene_toolbar.addStretch()

        self.scene_count_label = QLabel("0 scenes")
        self.scene_count_label.setStyleSheet("color: #6b7280;")
        scene_toolbar.addWidget(self.scene_count_label)

        grid_vbox.addLayout(scene_toolbar)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setAcceptDrops(True)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_scroll.setWidget(self.grid_widget)
        grid_vbox.addWidget(self.grid_scroll)

        splitter.addWidget(grid_container)

        # Right: AI generation panel
        ai_panel = QFrame()
        ai_panel.setStyleSheet(
            "QFrame { background: #fafafe; border: 1px solid #e5e7eb; "
            "border-radius: 8px; }"
        )
        ai_layout = QVBoxLayout(ai_panel)

        ai_header = QLabel("AI Scene Generator")
        ai_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #4f46e5;")
        ai_layout.addWidget(ai_header)

        ai_layout.addWidget(QLabel("Describe the scenes you want:"))
        self.ai_prompt_edit = QTextEdit()
        self.ai_prompt_edit.setPlaceholderText(
            "e.g. 'Generate 6 cinematic scenes covering the battle in "
            "Chapter 3, focusing on Marcus and Elena's confrontation'\n\n"
            "Leave blank to let AI pick the most compelling moments."
        )
        self.ai_prompt_edit.setMaximumHeight(120)
        ai_layout.addWidget(self.ai_prompt_edit)

        scenes_row = QHBoxLayout()
        scenes_row.addWidget(QLabel("Number of scenes:"))
        self.num_scenes_spin = QSpinBox()
        self.num_scenes_spin.setRange(1, 20)
        self.num_scenes_spin.setValue(5)
        scenes_row.addWidget(self.num_scenes_spin)
        scenes_row.addStretch()
        ai_layout.addLayout(scenes_row)

        self.ai_generate_btn = QPushButton("Generate Scenes with AI")
        self.ai_generate_btn.setStyleSheet(
            "QPushButton { background: #7c3aed; color: white; "
            "padding: 8px 20px; border-radius: 6px; font-weight: bold; "
            "font-size: 13px; }"
            "QPushButton:hover { background: #6d28d9; }"
        )
        self.ai_generate_btn.clicked.connect(self._on_ai_generate_scenes)
        ai_layout.addWidget(self.ai_generate_btn)

        self.ai_status_label = QLabel("")
        self.ai_status_label.setWordWrap(True)
        self.ai_status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        ai_layout.addWidget(self.ai_status_label)

        ai_layout.addStretch()

        # Scene details quick-view (when a card is selected)
        self.detail_group = QGroupBox("Selected Scene")
        dl = QVBoxLayout(self.detail_group)
        self.detail_title = QLabel("No scene selected")
        self.detail_title.setStyleSheet("font-weight: bold;")
        dl.addWidget(self.detail_title)
        self.detail_prompt = QLabel("")
        self.detail_prompt.setWordWrap(True)
        self.detail_prompt.setStyleSheet("color: #374151; font-size: 11px;")
        dl.addWidget(self.detail_prompt)
        self.detail_status = QLabel("")
        dl.addWidget(self.detail_status)

        detail_btns = QHBoxLayout()
        self.edit_scene_btn = QPushButton("Edit")
        self.edit_scene_btn.clicked.connect(self._on_edit_selected_scene)
        detail_btns.addWidget(self.edit_scene_btn)
        self.gen_scene_btn = QPushButton("Generate Video")
        self.gen_scene_btn.clicked.connect(self._on_generate_selected_scene)
        detail_btns.addWidget(self.gen_scene_btn)
        dl.addLayout(detail_btns)

        ai_layout.addWidget(self.detail_group)

        splitter.addWidget(ai_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

    @staticmethod
    def _vsep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #d1d5db;")
        return sep

    # ------------------------------------------------------------------
    # Data load / save
    # ------------------------------------------------------------------

    def set_project(self, project: WriterProject):
        self.project = project
        self._video_projects = project.video_projects
        self._refresh_chapter_combo()
        self._refresh_vp_combo()
        self._update_output_label()

    def load_data(self, video_projects: list[VideoProject]):
        self._video_projects = video_projects
        self._refresh_vp_combo()

    def get_data(self) -> list[VideoProject]:
        return self._video_projects

    def _refresh_chapter_combo(self):
        self.chapter_combo.clear()
        if not self.project:
            return
        self.chapter_combo.addItem("(select chapter)", "")
        for ch in self.project.manuscript.chapters:
            label = f"Ch {ch.number}: {ch.title}" if ch.title else f"Chapter {ch.number}"
            self.chapter_combo.addItem(label, ch.id)

    def _refresh_vp_combo(self):
        self.vp_combo.blockSignals(True)
        self.vp_combo.clear()
        for vp in self._video_projects:
            self.vp_combo.addItem(vp.name, vp.id)
        self.vp_combo.blockSignals(False)
        if self._video_projects:
            self._current_vp = self._video_projects[0]
            self.vp_combo.setCurrentIndex(0)
        else:
            self._current_vp = None
        self._rebuild_grid()

    def _update_output_label(self):
        if self._current_vp and self._current_vp.output_dir:
            self.output_label.setText(f"Output: {self._current_vp.output_dir}")
        elif self.project and self.project.project_path:
            out = str(Path(self.project.project_path) / "videos")
            self.output_label.setText(f"Output: {out}")
        else:
            self.output_label.setText("Output: (save project first)")

    # ------------------------------------------------------------------
    # Grid management
    # ------------------------------------------------------------------

    def _rebuild_grid(self):
        """Clear and re-populate the storyboard grid from the current VP."""
        # Clear existing
        for card in self._scene_cards.values():
            card.setParent(None)
            card.deleteLater()
        self._scene_cards.clear()

        # Remove stretch items
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._current_vp:
            self.scene_count_label.setText("0 scenes")
            return

        scenes = sorted(self._current_vp.scenes, key=lambda s: s.order)
        for idx, scene in enumerate(scenes):
            scene.order = idx  # normalise
            card = SceneCard(scene)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            card.request_delete.connect(self._on_delete_scene)
            card.request_generate.connect(self._on_generate_scene)
            card.request_optimize.connect(self._on_optimize_scene)
            self._scene_cards[scene.id] = card

            row = idx // self.GRID_COLUMNS
            col = idx % self.GRID_COLUMNS
            self.grid_layout.addWidget(card, row, col)

        self.scene_count_label.setText(
            f"{len(scenes)} scene{'s' if len(scenes) != 1 else ''}"
        )

    def _reorder_after_drop(self, dragged_id: str, target_id: str):
        """Move *dragged_id* scene to the position of *target_id*."""
        if not self._current_vp or dragged_id == target_id:
            return
        scenes = self._current_vp.scenes
        dragged = next((s for s in scenes if s.id == dragged_id), None)
        target = next((s for s in scenes if s.id == target_id), None)
        if not dragged or not target:
            return
        scenes.remove(dragged)
        insert_idx = scenes.index(target)
        scenes.insert(insert_idx, dragged)
        for idx, s in enumerate(scenes):
            s.order = idx
        self._rebuild_grid()
        self.content_changed.emit()

    # ------------------------------------------------------------------
    # Slot: card interactions
    # ------------------------------------------------------------------

    def _on_card_clicked(self, scene_id: str):
        # Deselect previous
        if self._selected_scene_id and self._selected_scene_id in self._scene_cards:
            self._scene_cards[self._selected_scene_id].set_selected(False)
        self._selected_scene_id = scene_id
        if scene_id in self._scene_cards:
            self._scene_cards[scene_id].set_selected(True)
        self._refresh_detail_panel()

    def _on_card_double_clicked(self, scene_id: str):
        self._open_scene_editor(scene_id)

    def _refresh_detail_panel(self):
        scene = self._find_scene(self._selected_scene_id)
        if not scene:
            self.detail_title.setText("No scene selected")
            self.detail_prompt.setText("")
            self.detail_status.setText("")
            return
        self.detail_title.setText(scene.title or "Untitled Scene")
        self.detail_prompt.setText(scene.prompt[:200] if scene.prompt else "(no prompt)")
        status_text = f"Status: {scene.status}"
        if scene.video_path:
            status_text += f"\nVideo: {scene.video_path}"
        self.detail_status.setText(status_text)

    # ------------------------------------------------------------------
    # Slot: add / delete scenes
    # ------------------------------------------------------------------

    def _on_add_scene(self):
        if not self._current_vp:
            self._on_new_video_project()
            if not self._current_vp:
                return

        order = len(self._current_vp.scenes)
        chapter_id = self.chapter_combo.currentData() or ""

        scene = VideoScene(
            id=str(uuid.uuid4()),
            order=order,
            title=f"Scene {order + 1}",
            chapter_id=chapter_id if chapter_id else None,
        )
        self._current_vp.scenes.append(scene)
        self._rebuild_grid()
        self.content_changed.emit()

        # Auto-open editor for the new scene
        self._open_scene_editor(scene.id)

    def _on_delete_scene(self, scene_id: str):
        if not self._current_vp:
            return
        reply = QMessageBox.question(
            self, "Delete Scene",
            "Delete this scene? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._current_vp.scenes = [
            s for s in self._current_vp.scenes if s.id != scene_id
        ]
        for idx, s in enumerate(self._current_vp.scenes):
            s.order = idx
        if self._selected_scene_id == scene_id:
            self._selected_scene_id = None
        self._rebuild_grid()
        self._refresh_detail_panel()
        self.content_changed.emit()

    # ------------------------------------------------------------------
    # Slot: video project management
    # ------------------------------------------------------------------

    def _on_new_video_project(self):
        name, ok = _ask_text(self, "New Video Project", "Project name:", "Untitled Video")
        if not ok or not name:
            return
        vp = VideoProject(
            id=str(uuid.uuid4()),
            name=name,
            video_model=self.model_combo.currentText(),
        )
        # Set output directory
        if self.project and self.project.project_path:
            vp.output_dir = str(Path(self.project.project_path) / "videos" / vp.id)
        self._video_projects.append(vp)
        self._refresh_vp_combo()
        self.vp_combo.setCurrentIndex(self.vp_combo.count() - 1)
        self.content_changed.emit()

    def _on_vp_changed(self, index: int):
        if index < 0 or index >= len(self._video_projects):
            self._current_vp = None
        else:
            self._current_vp = self._video_projects[index]
        self._rebuild_grid()
        self._update_output_label()
        self._refresh_detail_panel()

    # ------------------------------------------------------------------
    # Slot: AI scene generation (Flow 1)
    # ------------------------------------------------------------------

    def _on_ai_generate_scenes(self):
        if not self.project:
            QMessageBox.warning(self, "No Project", "Open a project first.")
            return

        chapter_id = self.chapter_combo.currentData()
        if not chapter_id:
            QMessageBox.warning(self, "Select Chapter", "Please select a chapter first.")
            return

        chapter = next(
            (c for c in self.project.manuscript.chapters if c.id == chapter_id), None
        )
        if not chapter:
            QMessageBox.warning(self, "Chapter Not Found", "Could not find the selected chapter.")
            return

        chapter_text = chapter.content or ""
        if not chapter_text:
            QMessageBox.warning(
                self, "Empty Chapter",
                "The selected chapter has no content. Write some chapter text first.",
            )
            return

        # Ensure a video project exists
        if not self._current_vp:
            self._on_new_video_project()
            if not self._current_vp:
                return

        # Build worldbuilding context
        wb_context = self._build_worldbuilding_context()

        user_direction = self.ai_prompt_edit.toPlainText().strip()
        num = self.num_scenes_spin.value()

        self.ai_generate_btn.setEnabled(False)
        self.ai_generate_btn.setText("Generating…")
        self.ai_status_label.setText("AI is planning scenes — this may take a moment…")

        worker = _SceneGenerationWorker(
            chapter_text=chapter_text,
            chapter_id=chapter_id,
            num_scenes=num,
            characters=self.project.characters,
            worldbuilding_context=wb_context,
            user_direction=user_direction,
        )
        worker.finished.connect(self._on_scenes_generated)
        worker.error.connect(self._on_scene_gen_error)
        self._workers.append(worker)
        worker.start()

    def _on_scenes_generated(self, scenes: list):
        self.ai_generate_btn.setEnabled(True)
        self.ai_generate_btn.setText("Generate Scenes with AI")

        if not self._current_vp:
            return

        # Append scenes (preserving any existing ones — mixed flow)
        start_order = len(self._current_vp.scenes)
        for idx, scene in enumerate(scenes):
            scene.order = start_order + idx
            self._current_vp.scenes.append(scene)

        self.ai_status_label.setText(
            f"Added {len(scenes)} scene(s). Edit or rearrange them, "
            "then generate videos."
        )
        self._rebuild_grid()
        self.content_changed.emit()

    def _on_scene_gen_error(self, msg: str):
        self.ai_generate_btn.setEnabled(True)
        self.ai_generate_btn.setText("Generate Scenes with AI")
        self.ai_status_label.setText(f"Error: {msg}")
        QMessageBox.warning(self, "Scene Generation Failed", msg)

    # ------------------------------------------------------------------
    # Slot: video generation
    # ------------------------------------------------------------------

    def _on_generate_scene(self, scene_id: str):
        self._start_video_generation(scene_id)

    def _on_generate_selected_scene(self):
        if self._selected_scene_id:
            self._start_video_generation(self._selected_scene_id)

    def _on_generate_all(self):
        if not self._current_vp or not self._current_vp.scenes:
            return
        reply = QMessageBox.question(
            self, "Generate All",
            f"Generate video for {len(self._current_vp.scenes)} scenes? "
            "This will unload other local AI models to free VRAM.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for scene in self._current_vp.scenes:
            if scene.status != "completed":
                self._start_video_generation(scene.id)

    def _start_video_generation(self, scene_id: str):
        scene = self._find_scene(scene_id)
        if not scene:
            return

        if not (scene.optimized_prompt or scene.prompt):
            QMessageBox.warning(
                self, "No Prompt",
                "This scene has no prompt. Edit the scene first.",
            )
            return

        output_dir = self._resolve_output_dir()
        if not output_dir:
            QMessageBox.warning(
                self, "No Output Directory",
                "Save the project first so videos have a place to go.",
            )
            return

        from src.config.ai_config import get_ai_config
        settings = get_ai_config().get_settings()

        scene.status = "generating"
        if scene_id in self._scene_cards:
            self._scene_cards[scene_id].refresh()

        model_id = self.model_combo.currentText()
        fps = settings.get("video_output_fps", 24)
        resolution = settings.get("video_output_resolution", "720p")

        worker = _VideoRenderWorker(
            scene=scene,
            model_id=model_id,
            output_dir=output_dir,
            fps=fps,
            resolution=resolution,
        )
        worker.finished.connect(self._on_video_rendered)
        worker.error.connect(self._on_video_error)
        self._workers.append(worker)
        worker.start()

    def _on_video_rendered(self, scene_id: str, video_path: str):
        scene = self._find_scene(scene_id)
        if scene:
            scene.status = "completed"
            scene.video_path = video_path
        if scene_id in self._scene_cards:
            self._scene_cards[scene_id].refresh()
        self._refresh_detail_panel()
        self.content_changed.emit()

    def _on_video_error(self, scene_id: str, msg: str):
        scene = self._find_scene(scene_id)
        if scene:
            scene.status = "failed"
            scene.error_message = msg
        if scene_id in self._scene_cards:
            self._scene_cards[scene_id].refresh()
        self._refresh_detail_panel()

    # ------------------------------------------------------------------
    # Slot: prompt optimisation
    # ------------------------------------------------------------------

    def _on_optimize_scene(self, scene_id: str):
        scene = self._find_scene(scene_id)
        if not scene or not self.project:
            return
        chars = [c for c in self.project.characters if c.id in scene.character_ids]
        wb = self._build_worldbuilding_context()
        chapter_text = ""
        if scene.chapter_id:
            ch = next(
                (c for c in self.project.manuscript.chapters if c.id == scene.chapter_id),
                None,
            )
            if ch:
                chapter_text = ch.content or ""

        worker = _PromptOptimizeWorker(
            scene=scene,
            characters=chars,
            worldbuilding_context=wb,
            chapter_text=chapter_text,
        )
        worker.finished.connect(self._on_optimize_done)
        worker.error.connect(self._on_optimize_error)
        self._workers.append(worker)
        worker.start()

    def _on_optimize_done(self, scene_id: str, optimized: str):
        scene = self._find_scene(scene_id)
        if scene:
            scene.optimized_prompt = optimized
        if scene_id in self._scene_cards:
            self._scene_cards[scene_id].refresh()
        self._refresh_detail_panel()
        self.content_changed.emit()

    def _on_optimize_error(self, scene_id: str, msg: str):
        QMessageBox.warning(self, "Optimisation Failed", msg)

    # ------------------------------------------------------------------
    # Scene editor dialog
    # ------------------------------------------------------------------

    def _on_edit_selected_scene(self):
        if self._selected_scene_id:
            self._open_scene_editor(self._selected_scene_id)

    def _open_scene_editor(self, scene_id: str):
        scene = self._find_scene(scene_id)
        if not scene or not self.project:
            return
        dlg = SceneEditorDialog(scene, self.project, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if scene_id in self._scene_cards:
                self._scene_cards[scene_id].refresh()
            self._refresh_detail_panel()
            self.content_changed.emit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_scene(self, scene_id: Optional[str]) -> Optional[VideoScene]:
        if not scene_id or not self._current_vp:
            return None
        return next((s for s in self._current_vp.scenes if s.id == scene_id), None)

    def _resolve_output_dir(self) -> Optional[Path]:
        if self._current_vp and self._current_vp.output_dir:
            return Path(self._current_vp.output_dir)
        if self.project and self.project.project_path:
            d = Path(self.project.project_path) / "videos"
            if self._current_vp:
                d = d / self._current_vp.id
                self._current_vp.output_dir = str(d)
            return d
        return None

    def _build_worldbuilding_context(self) -> str:
        """Summarise key worldbuilding elements for AI context."""
        if not self.project:
            return ""
        wb = self.project.worldbuilding
        parts: list[str] = []
        for place in wb.places[:5]:
            parts.append(f"Place: {place.name} — {getattr(place, 'description', '')[:120]}")
        for fac in wb.factions[:5]:
            parts.append(f"Faction: {fac.name} — {getattr(fac, 'description', '')[:120]}")
        for tech in wb.technologies[:3]:
            parts.append(f"Tech: {tech.name} — {getattr(tech, 'description', '')[:120]}")
        for culture in wb.cultures[:3]:
            parts.append(f"Culture: {culture.name} — {getattr(culture, 'description', '')[:120]}")
        # Include legacy text fields if structured lists are sparse
        if len(parts) < 3:
            for field in ("mythology", "history", "politics", "military"):
                txt = getattr(wb, field, "")
                if txt:
                    parts.append(f"{field.capitalize()}: {txt[:200]}")
        return "\n".join(parts)


# ── Utility ───────────────────────────────────────────────────────────────

def _ask_text(parent, title: str, label: str, default: str = "") -> tuple[str, bool]:
    """Simple text input dialog."""
    from PyQt6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(parent, title, label, text=default)
    return text.strip(), ok
