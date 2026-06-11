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
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from src.video_studio.models import ActionImage, SceneAction
from src.ui.video_studio.conversation_panel import CreativeConversationPanel


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
        refine_action_prompt: Optional[
            Callable[[Any, "SceneAction"], str]] = None,
        upload_image_callback: Optional[
            Callable[[Any, "SceneAction"], Optional["ActionImage"]]
        ] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit action")
        self.setModal(True)
        # Cap the dialog at ~85% of the screen so 1366×768 / 1440×900
        # laptops never open with Save/Cancel pushed off-screen.
        # The form is wrapped in a QScrollArea in ``_build_ui`` so
        # the writer can shrink the dialog and still reach every
        # field via the inner scrollbar.
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_h = int(avail.height() * 0.85) if avail else 720
        max_w = int(avail.width() * 0.9) if avail else 640
        natural_h = 720 if scene_mode == "slideshow" else 600
        self.resize(min(640, max_w), min(natural_h, max_h))
        self.setMinimumSize(520, 360)
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
        # Optional refinement adapter — the studio passes a
        # callable that composes the per-action prompt (style +
        # scene baseline + per-action overrides) and runs it
        # through ``refine_visual_prompt`` with target=image.
        # Receives (scene, action), returns the refined prompt
        # string. None disables the "✨ Preview AI-refined" button.
        self._refine_action_prompt_cb = refine_action_prompt
        # Optional uploader — receives (scene, action) and opens a
        # file picker, copies the chosen files into the action's
        # output folder, attaches them as ActionImage records, and
        # returns the first imported image (or None). None hides
        # the "📤 Upload image" affordance.
        self._upload_image_cb = upload_image_callback
        self._build_ui()
        self._load_from_action()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Outer layout holds a vertical scroll area for the form +
        # a pinned button row at the bottom. On small laptops the
        # dialog can shrink below the natural form height and the
        # inner scroll area takes over.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)

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
        # Hand-curated character + setting blocks for THIS action.
        # Lookup buttons (when ``project`` is available) pull from
        # ``project.characters`` and ``project.worldbuilding.places``.
        # Both fold into the per-action prompt so the renderer sees
        # the writer's authoritative description for this beat.
        char_row = QHBoxLayout()
        char_row.addWidget(QLabel("Character details:"))
        char_row.addStretch()
        self._lookup_char_btn = QPushButton("+ Lookup character…")
        self._lookup_char_btn.setToolTip(
            "Pick a character to append their appearance / "
            "personality / quirks into this box.")
        self._lookup_char_btn.clicked.connect(
            self._on_lookup_character)
        char_row.addWidget(self._lookup_char_btn)
        form.addRow(char_row)
        self._character_details_edit = QPlainTextEdit()
        self._character_details_edit.setPlaceholderText(
            "Visible character detail for THIS action — what "
            "they're wearing, posing, expressing in this beat. "
            "Pulled into the per-action image / video prompt.")
        self._character_details_edit.setFixedHeight(90)
        form.addRow(self._character_details_edit)

        setting_row = QHBoxLayout()
        setting_row.addWidget(QLabel("Setting / worldbuilding:"))
        setting_row.addStretch()
        self._lookup_place_btn = QPushButton("+ Lookup place…")
        self._lookup_place_btn.setToolTip(
            "Pick a place from worldbuilding to append its "
            "description / atmosphere / key features.")
        self._lookup_place_btn.clicked.connect(
            self._on_lookup_place)
        setting_row.addWidget(self._lookup_place_btn)
        form.addRow(setting_row)
        self._setting_details_edit = QPlainTextEdit()
        self._setting_details_edit.setPlaceholderText(
            "Location, atmosphere, key features for THIS action — "
            "the scene-wide setting box covers the baseline; this "
            "is the moment-specific detail.")
        self._setting_details_edit.setFixedHeight(90)
        form.addRow(self._setting_details_edit)

        self._scenery_edit = QPlainTextEdit()
        self._scenery_edit.setPlaceholderText(
            "Props, lighting, weather, camera notes — extra detail "
            "the writer wants the backend to honor.")
        self._scenery_edit.setFixedHeight(80)
        form.addRow("Scenery details", self._scenery_edit)
        # Free-form per-action directives layered on top of the
        # scene-level additional_instructions. Use for beat-
        # specific directives like "tight close-up", "no text in
        # this frame", "Dutch tilt".
        self._additional_instructions_edit = QPlainTextEdit()
        self._additional_instructions_edit.setPlaceholderText(
            "Extra directives for THIS action — framing, camera "
            "notes, 'no text overlays', etc. Layered on top of "
            "the scene's additional instructions.")
        self._additional_instructions_edit.setFixedHeight(70)
        form.addRow(
            "Additional instructions",
            self._additional_instructions_edit)
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
        # 0–600 s (10 min) per-slide hold. The earlier 30 s ceiling
        # silently clamped longer holds the writer typed, which
        # showed up downstream as a slide deck that "cut at a
        # minute" once a couple of long beats stacked up.
        self._display_seconds_spin.setRange(0.0, 600.0)
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

        # Image controls — always visible. In slideshow mode these
        # are the slides that get stitched; in video mode they're
        # reference renders the writer uses to verify the
        # description before burning a video clip. Either way the
        # iteration loop is the same: edit description → generate
        # → eyeball → edit again. Hiding it behind a mode toggle
        # made that loop invisible to video-mode users, which the
        # writer specifically asked for.
        is_slideshow = (self._scene_mode == "slideshow")
        images_box = QGroupBox(
            "Slide-deck images for this action" if is_slideshow
            else "Preview images for this action")
        images_layout = QVBoxLayout(images_box)
        images_layout.addWidget(QLabel(
            ("Check images you want in the final slide deck. "
             "Double-click to open in the system viewer.")
            if is_slideshow else
            ("Generate reference images to lock in the action "
             "description before rendering video / slide decks. "
             "Double-click an image to open it in the system "
             "viewer.")))
        self._images_list = QListWidget()
        # Selection updates the inline preview pane; double-click
        # explicitly opens the system viewer when the writer wants
        # the bigger version. Both stay inside this dialog's focus
        # context — no auto-launch of Preview / Photos, which on
        # macOS steals app focus and traps the writer behind the
        # external app.
        self._images_list.currentItemChanged.connect(
            self._on_preview_image_changed)
        self._images_list.itemDoubleClicked.connect(
            self._open_image_externally)
        # Maximum height so the list doesn't push the preview pane
        # below the fold on small dialogs.
        self._images_list.setMaximumHeight(110)
        images_layout.addWidget(self._images_list)

        # Inline preview pane — shows the currently-selected image
        # so the writer can iterate (edit → generate → eyeball →
        # edit) without leaving the dialog. Click "Open image" or
        # double-click the row when they need a full-size view.
        self._image_preview = QLabel(
            "Generate an image to preview it here.")
        self._image_preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setMinimumHeight(260)
        self._image_preview.setStyleSheet(
            "QLabel { border: 1px solid #cbd5e1; "
            "background: #f8fafc; color: #64748b; "
            "border-radius: 4px; padding: 8px; }")
        images_layout.addWidget(self._image_preview, stretch=1)

        btn_row = QHBoxLayout()
        self._generate_image_btn = QPushButton(
            "🖼 Generate image for this action")
        self._generate_image_btn.clicked.connect(
            self._on_generate_image)
        self._generate_image_btn.setEnabled(
            self._generate_image_callback is not None)
        if self._generate_image_callback is None:
            self._generate_image_btn.setToolTip(
                "Pick an image backend in the studio toolbar "
                "before generating reference images.")
        else:
            self._generate_image_btn.setToolTip(
                "Generate one reference image for this action "
                "using the studio's selected image backend. The "
                "image appears in the preview pane below as soon "
                "as it's ready.")
        # Upload existing images (from Midjourney / RunwayML /
        # hand-drawn art / etc.) into the action. Files are copied
        # into the action's output folder so the project stays
        # portable. Disabled when the host hasn't wired the
        # uploader, with a tooltip explaining why.
        self._upload_image_btn = QPushButton("📤 Upload image…")
        self._upload_image_btn.setToolTip(
            "Import existing image files into this action — "
            "pictures from external generators (Midjourney, "
            "RunwayML, Sora image, etc.) or hand-drawn art. "
            "Each upload becomes an ActionImage you can mark as "
            "favorite or include in the slide deck.")
        self._upload_image_btn.clicked.connect(
            self._on_upload_image)
        if self._upload_image_cb is None:
            self._upload_image_btn.setEnabled(False)
            self._upload_image_btn.setToolTip(
                self._upload_image_btn.toolTip()
                + "\n\n(Open the action editor from the studio "
                "to enable uploads.)")
        self._delete_image_btn = QPushButton("Delete image")
        self._delete_image_btn.clicked.connect(
            self._on_delete_image)
        self._open_image_btn = QPushButton("Open image")
        self._open_image_btn.setToolTip(
            "Open the selected image in the system viewer.")
        self._open_image_btn.clicked.connect(
            self._on_open_selected_image)
        # Mark the selected image as this action's favorite — the
        # one the slide-deck stitcher uses when the writer renders
        # the chapter deck. The list shows a ★ next to the
        # favorite so the writer always sees which it is.
        self._set_favorite_btn = QPushButton("★ Set favorite")
        self._set_favorite_btn.setToolTip(
            "Mark the selected image as this action's favorite. "
            "The slide-deck stitcher picks the favorite image when "
            "assembling the chapter deck — pick the best render.")
        self._set_favorite_btn.clicked.connect(
            self._on_set_favorite_image)
        btn_row.addWidget(self._generate_image_btn)
        btn_row.addWidget(self._upload_image_btn)
        btn_row.addWidget(self._set_favorite_btn)
        btn_row.addWidget(self._open_image_btn)
        btn_row.addWidget(self._delete_image_btn)
        btn_row.addStretch()
        images_layout.addLayout(btn_row)

        # AI-refine preview — see the prompt the LLM would
        # translate the structured detail into BEFORE rendering.
        # Target is always "image" here since this widget renders
        # per-action stills.
        refine_row = QHBoxLayout()
        self._preview_refined_btn = QPushButton(
            "✨ Preview AI-refined prompt")
        self._preview_refined_btn.setToolTip(
            "Run the structured per-action prompt through the LLM "
            "to translate it into proper image art-direction "
            "language. Opens a small dialog with the result.")
        self._preview_refined_btn.clicked.connect(
            self._on_preview_refined_clicked)
        # Disabled until the studio wires the refinement adapter.
        self._preview_refined_btn.setEnabled(
            self._refine_action_prompt_cb is not None
            and self._scene is not None)
        refine_row.addWidget(self._preview_refined_btn)
        refine_row.addStretch()
        images_layout.addLayout(refine_row)
        layout.addWidget(images_box, stretch=1)

        # ── AI conversation panel for iterative refinement ────────
        self._conversation_panel = CreativeConversationPanel(
            llm_provider=self._llm_provider,
            context_mode="action",
        )
        self._conversation_panel.apply_suggestion.connect(
            self._on_chat_apply_suggestion)
        self._conversation_panel.setMaximumHeight(250)
        layout.addWidget(self._conversation_panel)

        # Wrap the content in the scroll area and pin Save/Cancel
        # to the bottom outside the scroll viewport.
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # Save / Close — both commit. The writer flagged silent
        # data loss when reaching for Cancel or the X; treating
        # Close as a commit (under a quieter label than Save)
        # eliminates that surprise. Sub-dialog mutations (image
        # generation, AI enrich, etc.) have already mutated the
        # action in place by the time we get here, so the dialog's
        # choice only governs the form-level edits.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        buttons.button(
            QDialogButtonBox.StandardButton.Close).setText(
                "Close")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self._on_close_commit)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(8, 4, 8, 8)
        button_row.addWidget(buttons)
        outer.addLayout(button_row)

    # ------------------------------------------------------------------
    # Data load / save
    # ------------------------------------------------------------------
    def _load_from_action(self) -> None:
        a = self._action
        self._name_edit.setText(a.name)
        self._description_edit.setPlainText(a.description)
        self._character_edit.setText(", ".join(a.character_refs))
        self._location_edit.setText(", ".join(a.location_refs))
        self._character_details_edit.setPlainText(
            getattr(a, "character_details", "") or "")
        self._setting_details_edit.setPlainText(
            getattr(a, "setting_details", "") or "")
        self._additional_instructions_edit.setPlainText(
            getattr(a, "additional_instructions", "") or "")
        self._scenery_edit.setPlainText(a.scenery_details)
        self._prose_excerpt_edit.setPlainText(a.prose_excerpt)
        self._display_seconds_spin.setValue(
            float(a.display_seconds or 0.0))
        self._refresh_badges()
        # Image list is now always visible (slideshow + video both
        # benefit from preview renders to verify the description).
        self._refresh_image_list()
        self._sync_conversation_context()

    def _sync_conversation_context(self) -> None:
        """Push current form state into the conversation panel."""
        self._conversation_panel.set_context({
            "name": self._name_edit.text(),
            "description": self._description_edit.toPlainText(),
            "character_refs": self._character_edit.text(),
            "character_details": self._character_details_edit.toPlainText(),
            "setting_details": self._setting_details_edit.toPlainText(),
            "scenery_details": self._scenery_edit.toPlainText(),
            "additional_instructions": self._additional_instructions_edit.toPlainText(),
            "source_prose": self._prose_excerpt_edit.toPlainText(),
        })

    def _on_chat_apply_suggestion(self, field: str, value: str) -> None:
        """Handle apply_suggestion from the conversation panel."""
        if field == "prompt" or field == "description":
            self._description_edit.setPlainText(value)
        elif field == "character_details":
            self._character_details_edit.setPlainText(value)
        elif field == "setting_details":
            self._setting_details_edit.setPlainText(value)
        elif field == "scenery_details":
            self._scenery_edit.setPlainText(value)
        elif field == "additional_instructions":
            self._additional_instructions_edit.setPlainText(value)
        else:
            self._description_edit.setPlainText(value)

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
        a.character_details = (
            self._character_details_edit.toPlainText().strip())
        a.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        a.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())
        from datetime import datetime
        a.updated_at = datetime.now()
        self.accept()

    def _on_close_commit(self) -> None:
        """Close button — routes through ``reject()`` so all close
        paths (button, Esc, X) share the commit logic."""
        self.reject()

    def reject(self) -> None:
        """Override the default Qt reject so writers don't lose
        form-level edits when reaching for Close / Esc / X."""
        try:
            # ``_on_save`` commits + calls accept(); since we want
            # to bypass accept and close via done(Accepted) for
            # consistency with the scene editor, inline the commit
            # without the final accept call.
            self._commit_form_to_action()
        except Exception as e:
            print(f"[scene_action] close commit failed: {e}")
        self.done(QDialog.DialogCode.Accepted)

    def closeEvent(self, event) -> None:
        """Window-X / OS-quit — commit before closing."""
        try:
            self._commit_form_to_action()
        except Exception as e:
            print(
                f"[scene_action] closeEvent commit failed: {e}")
        super().closeEvent(event)

    def _commit_form_to_action(self) -> None:
        """Pure-commit version of _on_save without the accept()
        call — used by close paths that ``done()`` directly."""
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
        a.character_details = (
            self._character_details_edit.toPlainText().strip())
        a.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        a.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())
        from datetime import datetime
        a.updated_at = datetime.now()

    # ------------------------------------------------------------------
    # GraphRAG enrich
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Lookup helpers — append project data into the detail boxes
    # ------------------------------------------------------------------
    def _append_to_plain_text(
        self, edit, snippet: str,
    ) -> None:
        existing = edit.toPlainText().rstrip()
        text = (f"{existing}\n\n{snippet.strip()}"
                if existing else snippet.strip())
        edit.setPlainText(text)
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
        a.character_details = (
            self._character_details_edit.toPlainText().strip())
        a.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        a.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
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
        # Seed the inline preview pane — select the favorite (or
        # the most recent) image so the writer sees something
        # useful the moment the dialog opens. Selection signal
        # will route through _on_preview_image_changed.
        if self._action.images:
            favorite = self._action.favorite_image()
            target_id = (
                favorite.id if favorite
                else self._action.images[-1].id)
            for i in range(self._images_list.count()):
                item = self._images_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == target_id:
                    self._images_list.setCurrentRow(i)
                    break
        else:
            # Reset preview when the action has no images yet.
            self._image_preview.clear()
            self._image_preview.setText(
                "Generate an image to preview it here.")

    def _build_image_list_item(
        self, img: ActionImage,
    ) -> QListWidgetItem:
        path = Path(img.file_path) if img.file_path else None
        name = path.name if path else img.id
        suffix = ""
        if img.is_placeholder:
            suffix = "  (placeholder)"
        # ★ glyph marks the action's favorite — the image the
        # slide-deck stitcher will pick when assembling the
        # chapter deck.
        favorite_glyph = (
            "★ "
            if self._action.favorite_image_id == img.id
            else "  ")
        item = QListWidgetItem(
            f"{favorite_glyph}"
            f"{'☑' if img.included_in_slideshow else '☐'}  "
            f"{name}{suffix}")
        item.setData(Qt.ItemDataRole.UserRole, img.id)
        return item

    def _on_upload_image(self) -> None:
        """Open a file picker via the host's uploader, refresh the
        list when files arrive, and auto-select the first one so
        the inline preview shows it immediately."""
        if self._upload_image_cb is None or self._scene is None:
            return
        new_img = self._upload_image_cb(self._scene, self._action)
        if new_img is None:
            return
        self._refresh_image_list()
        for i in range(self._images_list.count()):
            if (self._images_list.item(i).data(
                    Qt.ItemDataRole.UserRole) == new_img.id):
                self._images_list.setCurrentRow(i)
                break

    def _on_set_favorite_image(self) -> None:
        """Mark the currently-selected image as the action's
        favorite — the one the slide-deck stitcher and chapter
        deck exporter will pick when assembling output."""
        item = self._images_list.currentItem()
        if item is None:
            QMessageBox.information(
                self, "No image selected",
                "Pick an image in the list first, then click "
                "'★ Set favorite' to mark it.")
            return
        img_id = item.data(Qt.ItemDataRole.UserRole)
        if not any(i.id == img_id for i in self._action.images):
            return
        self._action.favorite_image_id = img_id
        # Refresh the list so the ★ moves to the new favorite.
        # Preserve the current selection so the writer doesn't
        # lose context.
        self._refresh_image_list()
        for i in range(self._images_list.count()):
            if (self._images_list.item(i).data(
                    Qt.ItemDataRole.UserRole) == img_id):
                self._images_list.setCurrentRow(i)
                break

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
        a.character_details = (
            self._character_details_edit.toPlainText().strip())
        a.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        a.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())
        a.display_seconds = float(
            self._display_seconds_spin.value())
        if not a.description and not a.name:
            return
        # Brief in-place "Generating…" label so the writer sees the
        # backend is doing something — the callback can block for
        # several seconds on a real model.
        prev_label = self._generate_image_btn.text()
        self._generate_image_btn.setEnabled(False)
        self._generate_image_btn.setText("Generating…")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            new_img = self._generate_image_callback(a)
        finally:
            self._generate_image_btn.setEnabled(True)
            self._generate_image_btn.setText(prev_label)
        if new_img is None:
            return
        self._refresh_image_list()
        # Auto-select the new image so the Open / Delete buttons
        # target it without an extra click.
        for i in range(self._images_list.count()):
            item = self._images_list.item(i)
            if (item.data(Qt.ItemDataRole.UserRole)
                    == new_img.id):
                self._images_list.setCurrentRow(i)
                break
        # Show the freshly-rendered image in the inline preview
        # pane below the list. We deliberately DO NOT auto-launch
        # the system viewer here — on macOS Preview steals focus
        # from the modal dialog, leaving the writer stranded
        # behind it and unable to get back to the action editor.
        # The Open image button (and double-click on the row) are
        # still available when the writer wants the full-size view.
        self._update_image_preview_for(new_img)

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

    # ------------------------------------------------------------------
    # AI-refined prompt preview
    # ------------------------------------------------------------------
    def _on_preview_refined_clicked(self) -> None:
        if (self._refine_action_prompt_cb is None
                or self._scene is None):
            return
        # Commit current edits so the refinement sees fresh state.
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
        a.character_details = (
            self._character_details_edit.toPlainText().strip())
        a.setting_details = (
            self._setting_details_edit.toPlainText().strip())
        a.additional_instructions = (
            self._additional_instructions_edit
                .toPlainText().strip())
        a.prose_excerpt = (
            self._prose_excerpt_edit.toPlainText().strip())

        prev_label = self._preview_refined_btn.text()
        self._preview_refined_btn.setEnabled(False)
        self._preview_refined_btn.setText("Refining…")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            refined = self._refine_action_prompt_cb(
                self._scene, self._action)
        finally:
            self._preview_refined_btn.setEnabled(True)
            self._preview_refined_btn.setText(prev_label)
        if not refined or not refined.strip():
            QMessageBox.information(
                self, "Nothing to refine",
                "The LLM didn't return a refined prompt. Try "
                "filling more detail in the action's character / "
                "setting / scenery boxes first.")
            return
        # Tiny read-only dialog with Copy + Close.
        from PyQt6.QtWidgets import QDialog as _QDialog
        dlg = _QDialog(self)
        dlg.setWindowTitle("AI-refined prompt (image)")
        dlg.resize(620, 400)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "This is the prompt the image renderer will receive "
            "when the studio's ✨ AI refine toggle is on. Refine "
            "the source fields above if anything is off."))
        text = QPlainTextEdit()
        text.setPlainText(refined)
        text.setReadOnly(True)
        v.addWidget(text, stretch=1)
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("📋 Copy")
        close_btn = QPushButton("Close")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(refined))
        close_btn.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dlg.exec()

    # ------------------------------------------------------------------
    # Inline preview pane
    # ------------------------------------------------------------------
    def _on_preview_image_changed(self, current, _previous) -> None:
        """Driver for the inline preview pane — fires on every
        list-selection change."""
        if current is None:
            self._image_preview.clear()
            self._image_preview.setText(
                "Select an image to preview it here.")
            return
        img_id = current.data(Qt.ItemDataRole.UserRole)
        target = next(
            (i for i in self._action.images if i.id == img_id),
            None)
        self._update_image_preview_for(target)

    def _update_image_preview_for(self, img) -> None:
        """Render ``img`` into the preview QLabel. Handles missing
        files, placeholder images, and any decode failure
        gracefully — the label always shows SOMETHING informative,
        never a blank box."""
        if img is None or not img.file_path:
            self._image_preview.clear()
            self._image_preview.setText(
                "No image to preview.")
            return
        path = Path(img.file_path)
        if not path.exists():
            self._image_preview.clear()
            self._image_preview.setText(
                f"Image file missing on disk:\n{path}")
            return
        if getattr(img, "is_placeholder", False):
            self._image_preview.clear()
            self._image_preview.setText(
                "Placeholder image (no real render). Pick a real "
                "image backend in Settings → 🎨 Image Generation "
                "to see the actual frame here.")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._image_preview.clear()
            self._image_preview.setText(
                f"Could not decode image:\n{path.name}")
            return
        # Scale to fit the preview label's width while preserving
        # aspect ratio — keeps the iteration loop visual at a
        # glance without forcing the writer to open Preview.
        target_w = max(
            240, self._image_preview.width() - 24)
        target_h = max(
            220, self._image_preview.height() - 24)
        scaled = pixmap.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._image_preview.setPixmap(scaled)
        self._image_preview.setText("")

    def _on_open_selected_image(self) -> None:
        """Open the currently-selected image in the system viewer.
        Mirrors the existing double-click affordance — gives the
        writer a button-based path so the action is discoverable
        without remembering the double-click shortcut.
        """
        item = self._images_list.currentItem()
        if item is None:
            return
        img_id = item.data(Qt.ItemDataRole.UserRole)
        target = next(
            (i for i in self._action.images if i.id == img_id),
            None)
        if target is None or not target.file_path:
            return
        try:
            p = Path(target.file_path)
            if p.exists():
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(p.resolve())))
        except Exception as e:
            print(f"[scene_action] open image failed: {e}")

    def _open_image_externally(
        self, item: QListWidgetItem,
    ) -> None:
        img_id = item.data(Qt.ItemDataRole.UserRole)
        target = next(
            (i for i in self._action.images if i.id == img_id),
            None)
        if target is None or not target.file_path:
            return
        # Toggle the include checkbox on double-click ONLY in
        # slideshow mode — in video mode the include flag is
        # meaningless and the toggle would surprise the writer
        # who just wanted to peek at a preview render.
        if self._scene_mode == "slideshow":
            target.included_in_slideshow = (
                not target.included_in_slideshow)
            self._refresh_image_list()
        try:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(target.file_path).resolve())))
        except Exception:
            pass
