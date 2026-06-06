"""Per-action edit dialog for SceneAction.

Used by the scene editor when the writer clicks Add / Edit on an
action row. Lets them refine the action's name, description, the
characters and locations present in this beat (with read-only
"badge" lines showing what worldbuilding / character details we'll
pass to the backend so they can verify the level of detail), plus
extra scenery notes (props, lighting, weather, camera cues).

When the dialog is shown for slideshow scenes, the user also sees
the per-action image list with an include-in-deck checkbox so they
control which images make it into the final slide deck.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from src.video_studio.models import ActionImage, SceneAction


class SceneActionDialog(QDialog):
    """Edit one SceneAction.

    The dialog mutates ``action`` in place — caller passes a
    reference, exec returns Accepted/Rejected, and on Accepted the
    action's fields reflect the user's edits. Cancel leaves the
    action untouched (we work on a copy internally and only commit
    on accept).
    """

    def __init__(
        self,
        action: SceneAction,
        scene_mode: str = "video",
        project: Optional[Any] = None,
        generate_image_callback: Optional[
            Callable[[SceneAction], Optional[ActionImage]]] = None,
        scene: Optional[Any] = None,
        llm_provider: Optional[Callable[[], Any]] = None,
        rag_provider: Optional[Callable[[], Any]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit action")
        self.setModal(True)
        self.resize(640, 720 if scene_mode == "slideshow" else 600)
        self._action = action
        self._scene_mode = scene_mode
        self._project = project
        self._generate_image_callback = generate_image_callback
        # Optional refs the graphRAG enrich button needs. ``scene``
        # gives us the parent scene's prompt + chapter_id for
        # settings lookup; ``llm_provider`` / ``rag_provider`` are
        # callables returning the active LLM client and RAG system
        # respectively. All optional so existing callers keep
        # working — the enrich button disables itself when any are
        # missing.
        self._scene = scene
        self._llm_provider = llm_provider
        self._rag_provider = rag_provider
        self._build_ui()
        self._load_from_action()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(
            "4–8 word verb phrase: 'Mara crosses the threshold'")
        form.addRow("Name", self._name_edit)
        self._description_edit = QPlainTextEdit()
        self._description_edit.setPlaceholderText(
            "1–2 sentences of concrete visible action — who does "
            "what, where, with what immediate consequence.")
        self._description_edit.setFixedHeight(120)
        form.addRow("Description", self._description_edit)
        self._character_edit = QLineEdit()
        self._character_edit.setPlaceholderText(
            "Comma-separated character names present in this action")
        form.addRow("Characters", self._character_edit)
        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText(
            "Comma-separated location names used in this action")
        form.addRow("Locations", self._location_edit)
        self._scenery_edit = QPlainTextEdit()
        self._scenery_edit.setPlaceholderText(
            "Props, lighting, weather, camera notes — extra detail "
            "the writer wants the backend to honor.")
        self._scenery_edit.setFixedHeight(80)
        form.addRow("Scenery details", self._scenery_edit)
        # Source prose excerpt — the verbatim passage the AI matched
        # to this action (or empty for manually-created actions).
        # The writer can edit it; the edited text is what backends
        # see when this action contributes to the image prompt.
        self._prose_excerpt_edit = QPlainTextEdit()
        self._prose_excerpt_edit.setPlaceholderText(
            "Source prose excerpt — the passage from the chapter "
            "this beat covers. Edit freely; backends see this text "
            "verbatim when generating the image / video prompt.")
        self._prose_excerpt_edit.setFixedHeight(110)
        form.addRow("Prose excerpt", self._prose_excerpt_edit)
        # Per-action slide-deck display time. 0 means "inherit from
        # the scene's image_display_seconds" so writers can set a
        # uniform cadence on the scene and only override the beats
        # that should linger or flash by.
        self._display_seconds_spin = QDoubleSpinBox()
        self._display_seconds_spin.setRange(0.0, 30.0)
        self._display_seconds_spin.setDecimals(1)
        self._display_seconds_spin.setSingleStep(0.5)
        self._display_seconds_spin.setSpecialValueText(
            "use scene default")
        self._display_seconds_spin.setSuffix(" s")
        self._display_seconds_spin.setToolTip(
            "How long this action's slide holds on screen when the "
            "slide-deck stitcher walks the scene. 0 → inherit from "
            "Scene → Image display.")
        form.addRow("Slide time", self._display_seconds_spin)
        layout.addLayout(form)

        # AI enrich row — uses graphRAG over project entities to fold
        # character / worldbuilding detail into the description and
        # scenery. Disabled when llm or rag aren't wired so the user
        # gets a clear "not available" signal rather than a silent
        # no-op.
        ai_row = QHBoxLayout()
        self._enrich_btn = QPushButton(
            "AI: enrich description from graphRAG")
        self._enrich_btn.setToolTip(
            "Use the project's character entries, worldbuilding "
            "places, and graphRAG retrieval to flesh out the "
            "description and scenery details. The result is loaded "
            "into the fields above — edit freely before saving.")
        self._enrich_btn.clicked.connect(self._on_enrich_with_rag)
        rag_available = (
            self._llm_provider is not None
            and self._scene is not None)
        self._enrich_btn.setEnabled(rag_available)
        if not rag_available:
            self._enrich_btn.setToolTip(
                "Enrichment requires an LLM (set in Settings) and a "
                "scene context — open this dialog via the scene "
                "editor.")
        ai_row.addWidget(self._enrich_btn)
        ai_row.addStretch()
        layout.addLayout(ai_row)

        # Read-only badges showing what data we'd pull for the
        # named characters / locations. Reassures the writer that
        # the backend has enough material to render this beat.
        self._badges_box = QGroupBox(
            "Linked detail (pulled into the prompt)")
        badges_layout = QVBoxLayout(self._badges_box)
        self._character_badges = QLabel("")
        self._character_badges.setWordWrap(True)
        self._character_badges.setStyleSheet(
            "color: #4338ca; padding: 2px 0;")
        badges_layout.addWidget(self._character_badges)
        self._location_badges = QLabel("")
        self._location_badges.setWordWrap(True)
        self._location_badges.setStyleSheet(
            "color: #047857; padding: 2px 0;")
        badges_layout.addWidget(self._location_badges)
        layout.addWidget(self._badges_box)

        # Live refresh of the badges as the writer types.
        self._character_edit.textChanged.connect(
            self._refresh_badges)
        self._location_edit.textChanged.connect(
            self._refresh_badges)

        # Slideshow image controls — visible only when the scene is
        # in slideshow mode.
        if self._scene_mode == "slideshow":
            images_box = QGroupBox(
                "Slide-deck images for this action")
            images_layout = QVBoxLayout(images_box)
            images_layout.addWidget(QLabel(
                "Check images you want in the final slide deck. "
                "Double-click to open in the system viewer."))
            self._images_list = QListWidget()
            self._images_list.itemDoubleClicked.connect(
                self._open_image_externally)
            images_layout.addWidget(self._images_list)
            btn_row = QHBoxLayout()
            self._generate_image_btn = QPushButton(
                "Generate image for this action")
            self._generate_image_btn.clicked.connect(
                self._on_generate_image)
            self._generate_image_btn.setEnabled(
                self._generate_image_callback is not None)
            self._delete_image_btn = QPushButton("Delete image")
            self._delete_image_btn.clicked.connect(
                self._on_delete_image)
            btn_row.addWidget(self._generate_image_btn)
            btn_row.addWidget(self._delete_image_btn)
            btn_row.addStretch()
            images_layout.addLayout(btn_row)
            layout.addWidget(images_box, stretch=1)

        # Save / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Data load / save
    # ------------------------------------------------------------------
    def _load_from_action(self) -> None:
        a = self._action
        self._name_edit.setText(a.name)
        self._description_edit.setPlainText(a.description)
        self._character_edit.setText(", ".join(a.character_refs))
        self._location_edit.setText(", ".join(a.location_refs))
        self._scenery_edit.setPlainText(a.scenery_details)
        self._prose_excerpt_edit.setPlainText(a.prose_excerpt)
        self._display_seconds_spin.setValue(
            float(a.display_seconds or 0.0))
        self._refresh_badges()
        if self._scene_mode == "slideshow":
            self._refresh_image_list()

    def _on_save(self) -> None:
        a = self._action
        a.name = self._name_edit.text().strip()
        a.description = (
            self._description_edit.toPlainText().strip())
        a.character_refs = [
            x.strip() for x in self._character_edit.text().split(",")
            if x.strip()]
        a.location_refs = [
            x.strip() for x in self._location_edit.text().split(",")
            if x.strip()]
        a.scenery_details = (
            self._scenery_edit.toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())
        from datetime import datetime
        a.updated_at = datetime.now()
        self.accept()

    # ------------------------------------------------------------------
    # GraphRAG enrich
    # ------------------------------------------------------------------
    def _on_enrich_with_rag(self) -> None:
        """Fold current dialog state into the action, then ask the
        director to enrich it using graphRAG + character/worldbuilding
        summaries. Suggestions land back in the form fields; the
        writer can edit before saving."""
        if self._llm_provider is None or self._scene is None:
            return
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            QMessageBox.information(
                self, "No LLM configured",
                "Configure an LLM in Settings to use AI enrichment.")
            return
        rag = None
        if self._rag_provider is not None:
            try:
                rag = self._rag_provider()
            except Exception:
                rag = None
        # Push current edits onto the action so the enricher sees
        # the latest user input.
        a = self._action
        a.name = self._name_edit.text().strip()
        a.description = (
            self._description_edit.toPlainText().strip())
        a.character_refs = [
            x.strip() for x in self._character_edit.text().split(",")
            if x.strip()]
        a.location_refs = [
            x.strip() for x in self._location_edit.text().split(",")
            if x.strip()]
        a.scenery_details = (
            self._scenery_edit.toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())

        prev_label = self._enrich_btn.text()
        self._enrich_btn.setEnabled(False)
        self._enrich_btn.setText("Enriching…")
        try:
            from src.video_studio.ai_director import (
                enrich_action_with_graphrag,
            )
            suggestion = enrich_action_with_graphrag(
                action=a, scene=self._scene, project=self._project,
                llm=llm, rag_system=rag)
        finally:
            self._enrich_btn.setEnabled(True)
            self._enrich_btn.setText(prev_label)
        if not suggestion:
            QMessageBox.information(
                self, "Nothing to enrich",
                "GraphRAG didn't find additional detail for this "
                "action. Try adding character / worldbuilding "
                "entries linked to this scene, then try again.")
            return
        if "description" in suggestion:
            self._description_edit.setPlainText(
                suggestion["description"])
        if "scenery_details" in suggestion:
            self._scenery_edit.setPlainText(
                suggestion["scenery_details"])
        # Merge ref suggestions with the user's existing list — never
        # drop names the writer typed, only add names the LLM found.
        if "character_refs" in suggestion:
            merged = list(dict.fromkeys(
                a.character_refs + suggestion["character_refs"]))
            self._character_edit.setText(", ".join(merged))
        if "location_refs" in suggestion:
            merged = list(dict.fromkeys(
                a.location_refs + suggestion["location_refs"]))
            self._location_edit.setText(", ".join(merged))
        self._refresh_badges()

    # ------------------------------------------------------------------
    # Badges — read-only summary of linked entities
    # ------------------------------------------------------------------
    def _refresh_badges(self) -> None:
        char_names = [
            x.strip() for x in self._character_edit.text().split(",")
            if x.strip()]
        loc_names = [
            x.strip() for x in self._location_edit.text().split(",")
            if x.strip()]
        if char_names:
            self._character_badges.setText(
                "<b>Characters:</b> "
                + self._badge_text_for_characters(char_names))
        else:
            self._character_badges.setText(
                "<i>No characters listed — backends will infer them "
                "from the scene prompt.</i>")
        if loc_names:
            self._location_badges.setText(
                "<b>Locations:</b> "
                + self._badge_text_for_locations(loc_names))
        else:
            self._location_badges.setText(
                "<i>No locations listed — the action plays in the "
                "scene's default setting.</i>")

    def _badge_text_for_characters(
        self, names: List[str],
    ) -> str:
        """Look up each named character in the project and render a
        compact badge: name (✓ has appearance, ✓ has voice). Lets
        the writer see at a glance whether the linked detail is
        rich enough to influence the prompt."""
        result: List[str] = []
        chars_by_name = self._project_lookup_characters()
        for name in names:
            char = chars_by_name.get(name.lower())
            if char is None:
                result.append(
                    f"<span style='color:#dc2626'>{name} "
                    f"(no entry — backend will use only the "
                    f"name)</span>")
                continue
            flags: List[str] = []
            if (getattr(char, "physical_description", "") or "").strip():
                flags.append("appearance")
            if (getattr(char, "personality", "") or "").strip():
                flags.append("personality")
            if (getattr(char, "speaking_style", "") or "").strip():
                flags.append("voice")
            if (getattr(char, "motivations", "") or "").strip():
                flags.append("motivations")
            tail = (
                f" (✓ {', '.join(flags)})" if flags
                else " (entry exists but is empty)")
            result.append(f"{name}{tail}")
        return ", ".join(result)

    def _badge_text_for_locations(
        self, names: List[str],
    ) -> str:
        result: List[str] = []
        places_by_name = self._project_lookup_places()
        for name in names:
            place = places_by_name.get(name.lower())
            if place is None:
                result.append(
                    f"<span style='color:#dc2626'>{name} "
                    f"(no worldbuilding entry)</span>")
                continue
            flags: List[str] = []
            if (getattr(place, "description", "") or "").strip():
                flags.append("description")
            if (getattr(place, "atmosphere", "") or "").strip():
                flags.append("atmosphere")
            if (getattr(place, "climate", "") or "").strip():
                flags.append("climate")
            if getattr(place, "key_features", None):
                flags.append("features")
            tail = (
                f" (✓ {', '.join(flags)})" if flags
                else " (entry exists but is empty)")
            result.append(f"{name}{tail}")
        return ", ".join(result)

    def _project_lookup_characters(self) -> dict:
        if self._project is None:
            return {}
        out: dict = {}
        for c in getattr(self._project, "characters", []) or []:
            name = (getattr(c, "name", "") or "").strip().lower()
            if name:
                out[name] = c
        return out

    def _project_lookup_places(self) -> dict:
        if self._project is None:
            return {}
        wb = getattr(self._project, "worldbuilding", None)
        out: dict = {}
        for p in (getattr(wb, "places", []) or []) if wb else []:
            name = (getattr(p, "name", "") or "").strip().lower()
            if name:
                out[name] = p
        return out

    # ------------------------------------------------------------------
    # Slideshow image handlers
    # ------------------------------------------------------------------
    def _refresh_image_list(self) -> None:
        self._images_list.clear()
        for img in self._action.images:
            self._images_list.addItem(
                self._build_image_list_item(img))

    def _build_image_list_item(
        self, img: ActionImage,
    ) -> QListWidgetItem:
        path = Path(img.file_path) if img.file_path else None
        name = path.name if path else img.id
        suffix = ""
        if img.is_placeholder:
            suffix = "  (placeholder)"
        item = QListWidgetItem(
            f"{'☑' if img.included_in_slideshow else '☐'}  {name}"
            f"{suffix}")
        item.setData(Qt.ItemDataRole.UserRole, img.id)
        return item

    def _on_generate_image(self) -> None:
        if self._generate_image_callback is None:
            return
        # Save current edits first so the callback sees fresh data.
        a = self._action
        a.name = self._name_edit.text().strip()
        a.description = (
            self._description_edit.toPlainText().strip())
        a.character_refs = [
            x.strip() for x in self._character_edit.text().split(",")
            if x.strip()]
        a.location_refs = [
            x.strip() for x in self._location_edit.text().split(",")
            if x.strip()]
        a.scenery_details = (
            self._scenery_edit.toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())
        if not a.description and not a.name:
            return
        new_img = self._generate_image_callback(a)
        if new_img is not None:
            self._refresh_image_list()

    def _on_delete_image(self) -> None:
        item = self._images_list.currentItem()
        if item is None:
            return
        img_id = item.data(Qt.ItemDataRole.UserRole)
        target = next(
            (i for i in self._action.images if i.id == img_id),
            None)
        if target is None:
            return
        try:
            p = Path(target.file_path)
            if p.exists():
                p.unlink()
            sp = Path(target.sidecar_path) if target.sidecar_path else None
            if sp and sp.exists():
                sp.unlink()
        except Exception as e:
            print(f"[scene_action] image cleanup failed: {e}")
        self._action.images = [
            i for i in self._action.images if i.id != img_id]
        if self._action.favorite_image_id == img_id:
            self._action.favorite_image_id = (
                self._action.images[0].id
                if self._action.images else None)
        self._refresh_image_list()

    def _open_image_externally(
        self, item: QListWidgetItem,
    ) -> None:
        img_id = item.data(Qt.ItemDataRole.UserRole)
        target = next(
            (i for i in self._action.images if i.id == img_id),
            None)
        if target is None or not target.file_path:
            return
        # Also toggle the include checkbox on double-click — quick
        # way to flip inclusion without opening a sub-menu.
        target.included_in_slideshow = (
            not target.included_in_slideshow)
        self._refresh_image_list()
        # And then open the file too.
        try:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(target.file_path).resolve())))
        except Exception:
            pass
