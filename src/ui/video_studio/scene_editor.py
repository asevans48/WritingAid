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
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
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
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Scene — {scene.name or 'Untitled'}")
        self.setModal(True)
        self.resize(720, 720)
        self._scene = scene
        self._rewrite_callback = rewrite_callback
        self._build_ui()
        self._load_scene_into_form()

    def get_scene(self) -> Scene:
        """Caller picks this up after exec() returns Accepted."""
        return self._scene

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

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
        layout.addWidget(form_box)

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

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Data binding
    # ------------------------------------------------------------------
    def _load_scene_into_form(self) -> None:
        self._name_edit.setText(self._scene.name)
        self._description_edit.setPlainText(self._scene.description)
        self._prompt_edit.setPlainText(self._scene.prompt)
        self._character_refs_edit.setText(
            ", ".join(self._scene.character_refs))
        # Durations — 0 indicates "use studio default" (rendered by
        # the spin's specialValueText).
        target = self._scene.target_duration_seconds or 0.0
        self._target_duration_spin.setValue(float(target))
        self._image_display_spin.setValue(
            float(self._scene.image_display_seconds or 4.0))
        self._refresh_clip_list()

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
        # Target duration — 0 means "use studio default", which we
        # store as None so the model's effective_duration helper
        # correctly falls back.
        target = float(self._target_duration_spin.value())
        self._scene.target_duration_seconds = (
            target if target > 0 else None)
        self._scene.image_display_seconds = float(
            self._image_display_spin.value())
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
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Generate Scenes from Chapter")
        self.setModal(True)
        self.resize(480, 280)
        self._chapters = chapters
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

        self._auto_link = QCheckBox(
            "Connect generated scenes with hops in order")
        self._auto_link.setChecked(True)
        form.addRow("", self._auto_link)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Generate")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_chapter(self):
        return self._chapter_combo.currentData()

    def scene_count(self) -> int:
        return self._count_spin.value()

    def duration_seconds(self) -> float:
        return float(self._duration_spin.value())

    def auto_link(self) -> bool:
        return self._auto_link.isChecked()
