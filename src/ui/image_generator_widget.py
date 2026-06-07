"""Image and cover art generator widget."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QComboBox, QGroupBox,
    QMessageBox, QFileDialog, QScrollArea, QProgressDialog,
    QInputDialog, QMenu, QDialog, QDialogButtonBox, QLineEdit,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QPixmap
from typing import Any, List, Optional
from pathlib import Path
import uuid
import logging

from src.models.project import GeneratedImage, Character
from src.ai.image_generation_agent import get_image_generation_agent

logger = logging.getLogger(__name__)


def _character_snippet(ch: Any) -> str:
    """Format a single character into the multi-line snippet the
    EntityPicker appends into the character-details box. We surface
    the fields the renderer actually benefits from (appearance,
    clothing cues, personality / mannerisms) and keep each value
    short so multiple character snippets compose cleanly."""
    name = (getattr(ch, "name", "") or "").strip() or "(unnamed)"
    lines = [name + ":"]
    fields = (
        ("appearance", getattr(ch, "physical_description", "")),
        ("personality", getattr(ch, "personality", "")),
        ("speaking style", getattr(ch, "speaking_style", "")),
        ("quirks", getattr(ch, "quirks", "")),
        ("emotional baseline",
         getattr(ch, "emotional_baseline", "")),
    )
    for label, value in fields:
        v = (value or "").strip()
        if v:
            lines.append(f"- {label}: {v[:240]}")
    return "\n".join(lines)


def _place_snippet(place: Any) -> str:
    """Format a worldbuilding Place into a snippet for the setting
    box. Pulls description, atmosphere, key features, climate, and
    cultural significance when present."""
    name = (
        getattr(place, "name", "") or "").strip() or "(unnamed)"
    lines = [name + ":"]
    ptype = getattr(place, "place_type", "")
    if ptype:
        try:
            ptype_str = (
                ptype.value if hasattr(ptype, "value")
                else str(ptype)).strip().replace("_", " ")
        except Exception:
            ptype_str = str(ptype)
        if ptype_str:
            lines.append(f"- type: {ptype_str}")
    desc = (getattr(place, "description", "") or "").strip()
    if desc:
        lines.append(f"- description: {desc[:300]}")
    atm = (getattr(place, "atmosphere", "") or "").strip()
    if atm:
        lines.append(f"- atmosphere: {atm[:200]}")
    climate = (getattr(place, "climate", "") or "").strip()
    if climate:
        lines.append(f"- climate: {climate[:160]}")
    features = list(getattr(place, "key_features", []) or [])
    if features:
        lines.append(
            "- key features: "
            + ", ".join(str(f) for f in features[:8]))
    cultural = (
        getattr(place, "cultural_significance", "") or "").strip()
    if cultural:
        lines.append(
            f"- cultural significance: {cultural[:200]}")
    return "\n".join(lines)


def _plot_event_snippet(ev: Any) -> str:
    """Format a plot event into a setting-box snippet."""
    title = (
        getattr(ev, "title", "") or "").strip() or "(untitled)"
    lines = [title + ":"]
    stage = (getattr(ev, "stage", "") or "").strip()
    if stage:
        lines.append(
            f"- stage: {stage.replace('_', ' ').title()}")
    desc = (getattr(ev, "description", "") or "").strip()
    if desc:
        lines.append(f"- what happens: {desc[:300]}")
    outcome = (getattr(ev, "outcome", "") or "").strip()
    if outcome:
        lines.append(f"- outcome: {outcome[:240]}")
    return "\n".join(lines)


class EntityPickerDialog(QDialog):
    """Generic searchable picker for inserting project entities
    (characters / places / plot beats / etc.) into a context box.

    Takes a flat ``items`` list of ``(label, snippet)`` tuples;
    ``label`` is what we show in the list (typically the entity's
    name), ``snippet`` is the multi-line text appended to the
    target field when the writer accepts.
    """

    def __init__(
        self,
        title: str,
        items: List[Any],   # List[Tuple[str, str]]
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(560, 460)
        self._items = list(items)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔎 Filter by name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh_list)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(
            lambda *_: self.accept())
        self._list.currentItemChanged.connect(
            self._on_selection_changed)
        layout.addWidget(self._list, stretch=2)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText(
            "Select an entry to preview the snippet that will be "
            "appended.")
        layout.addWidget(self._preview, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Insert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_list(self) -> None:
        needle = (self._search.text() or "").strip().lower()
        self._list.clear()
        for label, snippet in self._items:
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, snippet)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            self._preview.clear()
            return
        snippet = current.data(Qt.ItemDataRole.UserRole) or ""
        self._preview.setPlainText(snippet)

    def selected_snippet(self) -> Optional[str]:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)


class ImageGenerationWorker(QThread):
    """Worker thread for image generation to avoid blocking UI."""

    finished = pyqtSignal(object)  # Emits Path or None
    error = pyqtSignal(str)

    def __init__(self, image_type: str, prompt: str, style: str = "", character: Optional[Character] = None):
        super().__init__()
        self.image_type = image_type
        self.prompt = prompt
        self.style = style
        self.character = character

    def run(self):
        """Run image generation in background."""
        try:
            agent = get_image_generation_agent()

            if self.image_type == "Character Portrait" and self.character:
                result_path = agent.generate_character_image(
                    character=self.character,
                    additional_prompt=self.style
                )
            else:
                # Scene or cover art
                combined_prompt = self.prompt
                if self.style:
                    combined_prompt = f"{self.prompt}, {self.style}"

                result_path = agent.generate_scene_image(
                    scene_description=combined_prompt,
                    style=""
                )

            self.finished.emit(result_path)

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            self.error.emit(str(e))


class ImageGeneratorWidget(QWidget):
    """Widget for generating cover art and scene images."""

    content_changed = pyqtSignal()

    def __init__(self, characters: Optional[List[Character]] = None):
        """Initialize image generator widget.

        Args:
            characters: Optional list of characters for portrait generation
        """
        super().__init__()
        self.images: List[GeneratedImage] = []
        self.characters = characters or []
        # Extra project data sources for the inline context-box
        # pickers. Optional so existing callers (tests, older
        # bootstraps) keep working — the pickers degrade gracefully
        # when the list is empty.
        self.places: List[Any] = []
        self.plot_events: List[Any] = []
        self.selected_character: Optional[Character] = None
        self.worker: Optional[ImageGenerationWorker] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Content widget inside scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        # Header
        header = QLabel("Image & Cover Art Generator")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Generator section
        generator_group = QGroupBox("Generate New Image")
        generator_layout = QVBoxLayout()

        # Image type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Image Type:"))

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Cover Art", "Character Portrait", "Scene Visualization"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)

        generator_layout.addLayout(type_layout)

        # Character selection (shown only for character portraits)
        self.character_layout = QHBoxLayout()
        self.character_layout.addWidget(QLabel("Character:"))

        self.character_combo = QComboBox()
        self._update_character_list()
        self.character_combo.currentIndexChanged.connect(self._on_character_selected)
        self.character_layout.addWidget(self.character_combo)

        self.character_widget = QWidget()
        self.character_widget.setLayout(self.character_layout)
        self.character_widget.setVisible(False)  # Hidden by default
        generator_layout.addWidget(self.character_widget)

        # Description
        generator_layout.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Describe what's in the frame — subject, action, "
            "framing, lighting. The context fields below add "
            "character / setting / plot detail on top.")
        self.description_edit.setMaximumHeight(100)
        generator_layout.addWidget(self.description_edit)

        # ---- Character context (editable, with a lookup helper) ----
        # The lookup buttons APPEND project data into the box; the
        # writer can also free-type. With no LLM configured, this
        # is the writer's hand-curated detail that the renderer
        # sees verbatim.
        char_label_row = QHBoxLayout()
        char_label_row.addWidget(QLabel("Character details:"))
        char_label_row.addStretch()
        self.lookup_character_btn = QPushButton("+ Lookup character…")
        self.lookup_character_btn.setToolTip(
            "Pick a character from the project to append their "
            "appearance, personality, and quirks to this box.")
        self.lookup_character_btn.clicked.connect(
            self._on_lookup_character)
        char_label_row.addWidget(self.lookup_character_btn)
        generator_layout.addLayout(char_label_row)
        self.character_details_edit = QTextEdit()
        self.character_details_edit.setPlaceholderText(
            "Appearance, clothing, voice / mannerisms — what the "
            "renderer needs to draw the right person. Click "
            "'+ Lookup character…' to pull from the project.")
        self.character_details_edit.setMaximumHeight(110)
        generator_layout.addWidget(self.character_details_edit)

        # ---- Setting / worldbuilding context ----
        setting_label_row = QHBoxLayout()
        setting_label_row.addWidget(QLabel("Setting / worldbuilding:"))
        setting_label_row.addStretch()
        self.lookup_place_btn = QPushButton("+ Lookup place…")
        self.lookup_place_btn.setToolTip(
            "Pick a place from the project to append its "
            "description, atmosphere, and key features to this "
            "box.")
        self.lookup_place_btn.clicked.connect(
            self._on_lookup_place)
        setting_label_row.addWidget(self.lookup_place_btn)
        generator_layout.addLayout(setting_label_row)
        self.setting_edit = QTextEdit()
        self.setting_edit.setPlaceholderText(
            "Location, atmosphere, key features, lighting / "
            "weather. Click '+ Lookup place…' to pull from "
            "worldbuilding.")
        self.setting_edit.setMaximumHeight(110)
        generator_layout.addWidget(self.setting_edit)

        # ---- Plot context ----
        plot_label_row = QHBoxLayout()
        plot_label_row.addWidget(QLabel("Plot context:"))
        plot_label_row.addStretch()
        self.lookup_plot_btn = QPushButton("+ Lookup plot beat…")
        self.lookup_plot_btn.setToolTip(
            "Pick a plot event to append its description (helps "
            "the renderer understand the emotional context of the "
            "shot).")
        self.lookup_plot_btn.clicked.connect(
            self._on_lookup_plot)
        plot_label_row.addWidget(self.lookup_plot_btn)
        generator_layout.addLayout(plot_label_row)
        self.plot_edit = QTextEdit()
        self.plot_edit.setPlaceholderText(
            "What's happening in the story right now — the beat "
            "this image illustrates. Click '+ Lookup plot beat…' "
            "to pull from the plot pyramid.")
        self.plot_edit.setMaximumHeight(90)
        generator_layout.addWidget(self.plot_edit)

        # Style preferences
        generator_layout.addWidget(QLabel("Style Preferences (optional):"))
        self.style_edit = QTextEdit()
        self.style_edit.setPlaceholderText("e.g., photorealistic, oil painting, digital art, fantasy, sci-fi...")
        self.style_edit.setMaximumHeight(60)
        generator_layout.addWidget(self.style_edit)

        # ---- Composed prompt preview + Generate ----
        # The preview is read-only so writers can verify what the
        # backend will actually see (description + character +
        # setting + plot + style) — especially useful without an
        # LLM enhancer in the loop.
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Composed prompt preview:"))
        preview_row.addStretch()
        refresh_preview_btn = QPushButton("↻ Refresh")
        refresh_preview_btn.setToolTip(
            "Re-render the preview from the current fields.")
        refresh_preview_btn.clicked.connect(
            self._refresh_prompt_preview)
        preview_row.addWidget(refresh_preview_btn)
        generator_layout.addLayout(preview_row)
        self.prompt_preview = QTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setMaximumHeight(110)
        self.prompt_preview.setStyleSheet(
            "background:#f8fafc; border:1px solid #e2e8f0; "
            "color:#334155; font-family:monospace; font-size:11px;")
        generator_layout.addWidget(self.prompt_preview)

        # Live refresh of the preview as the writer edits.
        for edit in (self.description_edit,
                     self.character_details_edit,
                     self.setting_edit, self.plot_edit,
                     self.style_edit):
            edit.textChanged.connect(self._refresh_prompt_preview)

        # Generate button
        generate_button = QPushButton("Generate Image")
        generate_button.clicked.connect(self._generate_image)
        generator_layout.addWidget(generate_button)

        generator_group.setLayout(generator_layout)
        layout.addWidget(generator_group)

        # Image gallery
        gallery_group = QGroupBox("Generated Images")
        gallery_layout = QHBoxLayout()

        # Image list with context menu
        list_container = QVBoxLayout()

        self.image_list = QListWidget()
        self.image_list.currentItemChanged.connect(self._on_image_selected)
        self.image_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self._show_image_context_menu)
        list_container.addWidget(self.image_list)

        # Rename / Delete buttons
        list_btn_layout = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.setToolTip("Rename the selected image")
        rename_btn.clicked.connect(self._rename_image)
        list_btn_layout.addWidget(rename_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected image")
        delete_btn.clicked.connect(self._delete_image)
        list_btn_layout.addWidget(delete_btn)

        list_btn_layout.addStretch()
        list_container.addLayout(list_btn_layout)

        gallery_layout.addLayout(list_container)

        # Image preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)

        self.preview_label = QLabel("No image selected")
        self.preview_label.setFixedSize(400, 400)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        preview_layout.addWidget(self.preview_label)

        self.prompt_display = QTextEdit()
        self.prompt_display.setReadOnly(True)
        self.prompt_display.setMaximumHeight(80)
        self.prompt_display.setPlaceholderText("Image prompt will appear here")
        preview_layout.addWidget(self.prompt_display)

        save_button = QPushButton("Save Image As...")
        save_button.clicked.connect(self._save_image)
        preview_layout.addWidget(save_button)

        gallery_layout.addWidget(preview_widget)

        gallery_group.setLayout(gallery_layout)
        layout.addWidget(gallery_group)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _generate_image(self):
        """Generate image using AI."""
        image_type = self.type_combo.currentText()

        # Validate character portrait requirements
        if image_type == "Character Portrait":
            if not self.selected_character:
                QMessageBox.warning(
                    self,
                    "No Character Selected",
                    "Please select a character for portrait generation."
                )
                return
        else:
            # For non-character images, require SOMETHING — the
            # composed prompt counts even when the writer left the
            # top description box empty (they may have used the
            # character / setting / plot boxes exclusively).
            composed_for_check = self._compose_full_prompt()
            if not composed_for_check:
                QMessageBox.warning(
                    self,
                    "Missing Description",
                    "Add a description or fill at least one of "
                    "the character / setting / plot context boxes "
                    "below before generating."
                )
                return

        # Compose the full prompt from description + context boxes
        # + style. Works the same whether or not the agent has an
        # LLM enhancer wired in — the agent gets a rich starting
        # point either way.
        full_prompt = self._compose_full_prompt()
        style = self.style_edit.toPlainText().strip()

        # Start generation in worker thread
        self.worker = ImageGenerationWorker(
            image_type=image_type,
            prompt=full_prompt,
            style=style,
            character=self.selected_character if image_type == "Character Portrait" else None
        )
        self.worker.finished.connect(self._on_generation_finished)
        self.worker.error.connect(self._on_generation_error)
        self.worker.start()

        # Show progress dialog
        self.progress = QProgressDialog("Generating image...", "Cancel", 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self._cancel_generation)
        self.progress.show()

    def _cancel_generation(self):
        """Cancel ongoing generation."""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            logger.info("Image generation cancelled by user")

    def _on_generation_finished(self, result_path: Optional[Path]):
        """Handle completion of image generation."""
        if self.progress:
            self.progress.close()

        if result_path and result_path.exists():
            # Create GeneratedImage entry
            image_type = self.type_combo.currentText().lower().replace(" ", "_")
            image = GeneratedImage(
                id=str(uuid.uuid4()),
                image_path=str(result_path),
                prompt=self.description_edit.toPlainText().strip(),
                image_type=image_type,
                associated_id=self.selected_character.id if self.selected_character else None
            )
            self.images.append(image)

            # Update UI
            item = QListWidgetItem(f"{image_type}: {image.id[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, image.id)
            self.image_list.addItem(item)
            self.image_list.setCurrentItem(item)

            self.content_changed.emit()

            QMessageBox.information(
                self,
                "Success",
                f"Image generated successfully!\n\nSaved to: {result_path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Generation Failed",
                "Failed to generate image. Check logs for details."
            )

    def _on_generation_error(self, error_msg: str):
        """Handle generation error."""
        if self.progress:
            self.progress.close()

        QMessageBox.critical(
            self,
            "Error",
            f"Image generation failed:\n\n{error_msg}"
        )

    def _on_image_selected(self, current, previous):
        """Handle image selection."""
        if not current:
            return

        image_id = current.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)

        if image:
            pixmap = QPixmap(image.image_path)
            self.preview_label.setPixmap(
                pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.prompt_display.setPlainText(image.prompt)

    def _save_image(self):
        """Save selected image to a new location."""
        current_item = self.image_list.currentItem()
        if not current_item:
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        source = Path(image.image_path)
        if not source.exists():
            QMessageBox.warning(self, "File Not Found", f"Source image not found:\n{source}")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", source.name,
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        if file_path:
            import shutil
            try:
                shutil.copy2(str(source), file_path)
                QMessageBox.information(self, "Saved", f"Image saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save image:\n{e}")

    def _show_image_context_menu(self, position):
        """Show context menu for image list."""
        item = self.image_list.itemAt(position)
        if not item:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        save_action = menu.addAction("Save As...")

        action = menu.exec(self.image_list.mapToGlobal(position))
        if action == rename_action:
            self._rename_image()
        elif action == delete_action:
            self._delete_image()
        elif action == save_action:
            self._save_image()

    def _rename_image(self):
        """Rename the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Select an image to rename.")
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        # Use current display name as default
        current_name = current_item.text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Image", "Enter a new name:", text=current_name
        )
        if ok and new_name.strip():
            # Store custom display name on the model
            image.display_name = new_name.strip()
            current_item.setText(new_name.strip())
            self.content_changed.emit()

    def _delete_image(self):
        """Delete the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Select an image to delete.")
            return

        image_id = current_item.data(Qt.ItemDataRole.UserRole)
        image = next((img for img in self.images if img.id == image_id), None)
        if not image:
            return

        reply = QMessageBox.question(
            self, "Delete Image",
            f"Delete this image?\n\nThis will remove the file from disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Remove from disk
        file_path = Path(image.image_path)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"Could not delete image file: {e}")

        # Remove from data
        self.images = [img for img in self.images if img.id != image_id]

        # Remove from list
        row = self.image_list.row(current_item)
        self.image_list.takeItem(row)

        # Clear preview
        self.preview_label.setText("No image selected")
        self.preview_label.setPixmap(QPixmap())
        self.prompt_display.clear()

        self.content_changed.emit()

    def _on_type_changed(self, image_type: str):
        """Handle image type change."""
        # Show/hide character selection for character portraits
        self.character_widget.setVisible(image_type == "Character Portrait")

        # Auto-fill description if character is selected
        if image_type == "Character Portrait" and self.selected_character:
            self._update_description_for_character()

    def _on_character_selected(self, index: int):
        """Handle character selection."""
        if index >= 0 and index < len(self.characters):
            self.selected_character = self.characters[index]
            self._update_description_for_character()
        else:
            self.selected_character = None

    def _update_character_list(self):
        """Update character combo box."""
        self.character_combo.clear()
        for char in self.characters:
            self.character_combo.addItem(char.name)

        # Auto-select first character if available
        if self.characters:
            self.character_combo.setCurrentIndex(0)
            self.selected_character = self.characters[0]

    def _update_description_for_character(self):
        """Auto-fill description from character info."""
        if not self.selected_character:
            return

        char = self.selected_character
        parts = []

        if char.physical_description:
            parts.append(char.physical_description)
        else:
            # Fallback to generic description
            parts.append(f"Portrait of {char.name}")

        if char.personality:
            parts.append(f"Personality: {char.personality[:100]}")

        self.description_edit.setPlainText("\n".join(parts))

    def set_characters(self, characters: List[Character]):
        """Update available characters."""
        self.characters = characters
        self._update_character_list()

    def set_places(self, places: List[Any]) -> None:
        """Update the worldbuilding places available to the
        '+ Lookup place…' picker. Safe to call with an empty list."""
        self.places = list(places or [])

    def set_plot_events(self, plot_events: List[Any]) -> None:
        """Update the plot events / beats available to the
        '+ Lookup plot beat…' picker. Pass the project's flat list
        of FreytagPyramid.events (and any subplot events the host
        wants surfaced)."""
        self.plot_events = list(plot_events or [])

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def _append_to_box(self, edit: QTextEdit, snippet: str) -> None:
        """Append a snippet to a context box, separated by a blank
        line when the box already has content. Mutates in place."""
        existing = edit.toPlainText().rstrip()
        if existing:
            edit.setPlainText(f"{existing}\n\n{snippet.strip()}")
        else:
            edit.setPlainText(snippet.strip())
        # Scroll to the bottom so the just-inserted text is visible.
        edit.verticalScrollBar().setValue(
            edit.verticalScrollBar().maximum())

    def _on_lookup_character(self) -> None:
        if not self.characters:
            QMessageBox.information(
                self, "No characters",
                "This project has no characters yet — add them in "
                "the Characters tab first.")
            return
        items = []
        for ch in self.characters:
            name = (ch.name or "").strip() or "(unnamed)"
            kind = (
                getattr(ch, "character_type", "") or "").strip()
            label = f"{name}" + (f"  —  {kind}" if kind else "")
            items.append((label, _character_snippet(ch)))
        dlg = EntityPickerDialog(
            "Insert character details", items, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        snippet = dlg.selected_snippet()
        if snippet:
            self._append_to_box(self.character_details_edit, snippet)

    def _on_lookup_place(self) -> None:
        if not self.places:
            QMessageBox.information(
                self, "No places",
                "This project has no worldbuilding places yet — "
                "add them in the Worldbuilding tab first.")
            return
        items = []
        for p in self.places:
            name = (getattr(p, "name", "") or "").strip() or "(unnamed)"
            items.append((name, _place_snippet(p)))
        dlg = EntityPickerDialog(
            "Insert setting details", items, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        snippet = dlg.selected_snippet()
        if snippet:
            self._append_to_box(self.setting_edit, snippet)

    def _on_lookup_plot(self) -> None:
        if not self.plot_events:
            QMessageBox.information(
                self, "No plot beats",
                "This project has no plot events yet — add them in "
                "the Story Planning tab first.")
            return
        items = []
        for ev in self.plot_events:
            title = (getattr(ev, "title", "") or "").strip() or "(untitled)"
            stage = (getattr(ev, "stage", "") or "").replace(
                "_", " ").title()
            act = getattr(ev, "act", None)
            tag_bits = [stage]
            if act:
                tag_bits.append(f"Act {act}")
            label = f"{title}  —  {', '.join(tag_bits)}"
            items.append((label, _plot_event_snippet(ev)))
        dlg = EntityPickerDialog(
            "Insert plot beat", items, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        snippet = dlg.selected_snippet()
        if snippet:
            self._append_to_box(self.plot_edit, snippet)

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------
    def _compose_full_prompt(self) -> str:
        """Build the prompt that goes to the image agent. Always
        runs locally so it works whether or not an LLM enhancer is
        configured — the agent's enhancer (when present) just gets
        a richer starting point."""
        description = (
            self.description_edit.toPlainText().strip())
        char_details = (
            self.character_details_edit.toPlainText().strip())
        setting = self.setting_edit.toPlainText().strip()
        plot = self.plot_edit.toPlainText().strip()
        style = self.style_edit.toPlainText().strip()

        parts: List[str] = []
        if description:
            parts.append(description)
        if char_details:
            parts.append(f"Characters: {char_details}")
        if setting:
            parts.append(f"Setting: {setting}")
        if plot:
            parts.append(f"Plot context: {plot}")
        if style:
            parts.append(f"Style: {style}")
        return "\n\n".join(parts).strip()

    def _refresh_prompt_preview(self) -> None:
        composed = self._compose_full_prompt()
        if composed:
            self.prompt_preview.setPlainText(composed)
        else:
            self.prompt_preview.setPlainText("")
            self.prompt_preview.setPlaceholderText(
                "Fill in the fields above — the composed prompt "
                "renders here as you type.")

    def load_data(self, images: List[GeneratedImage]):
        """Load generated images."""
        self.images = images
        self.image_list.clear()

        for image in images:
            label = image.display_name or f"{image.image_type}: {image.id[:8]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, image.id)
            self.image_list.addItem(item)

    def get_data(self) -> List[GeneratedImage]:
        """Get generated images data."""
        return self.images
