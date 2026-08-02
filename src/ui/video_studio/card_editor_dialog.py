"""Editor for a title / ending card — background (color / image /
video), styled title + subtitle text, fade, position, duration, and
the transition INTO the card. Audio is edited via the group editor
(a card is its own group), reached with the "🎤 Edit audio…" button.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.video_studio.models import TitleCard


class CardEditorDialog(QDialog):
    """Edit a single ``TitleCard``. Mutates the card in place on
    Accept. ``on_edit_audio`` (optional) is called when the writer
    clicks 🎤 Edit audio — the host opens the group editor."""

    def __init__(
        self,
        card: TitleCard,
        *,
        title_bar: str = "Title card",
        on_edit_audio=None,
        deck_has_background: bool = False,
        deck_background_enabled: bool = True,
        text_overlay_mode: bool = False,
        canvas_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._card = card
        self._on_edit_audio = on_edit_audio
        self._deck_has_background = deck_has_background
        self._deck_bg_enabled_initial = deck_background_enabled
        # In overlay mode the slide's own image is the background,
        # so the background + timing/transition + audio sections are
        # hidden — only text + effects remain.
        self._overlay_mode = text_overlay_mode
        # In canvas mode the writer designs the slide on a live
        # WYSIWYG canvas — drag/resize free-floating text boxes,
        # PowerPoint-style — instead of the fixed title/subtitle form.
        self._canvas_mode = canvas_mode
        self._loading_props = False
        self.setWindowTitle(f"🎬 {title_bar}")
        if canvas_mode:
            # Fits a 13" laptop (min height ~600); the content scrolls
            # so every control stays reachable on a small screen.
            self.resize(900, 680)
            self.setMinimumSize(640, 480)
        else:
            self.resize(460, 640)
            self.setMinimumSize(380, 420)
        self._build_ui()
        self._load_from_card()

    # -- UI ------------------------------------------------------------
    def _build_ui(self) -> None:
        # All sections live inside a scroll area so the dialog fits a
        # laptop screen — the OK/Cancel bar is pinned OUTSIDE it so
        # it's always reachable no matter how tall the content grows.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        v = QVBoxLayout(content)

        bg_box = QGroupBox("Background")
        bg_form = QFormLayout(bg_box)
        self._kind = QComboBox()
        self._kind.addItem("Solid color", "color")
        self._kind.addItem("Image", "image")
        self._kind.addItem("Video", "video")
        self._kind.currentIndexChanged.connect(self._sync_kind)
        bg_form.addRow("Type", self._kind)
        color_row = QHBoxLayout()
        self._bg_color = QLineEdit("#000000")
        self._bg_color_btn = QPushButton("Pick…")
        self._bg_color_btn.clicked.connect(
            lambda: self._pick_color(self._bg_color))
        color_row.addWidget(self._bg_color)
        color_row.addWidget(self._bg_color_btn)
        cw = QWidget()
        cw.setLayout(color_row)
        bg_form.addRow("Color", cw)
        media_row = QHBoxLayout()
        self._bg_media = QLineEdit()
        self._bg_media.setPlaceholderText("Image / video file…")
        self._bg_media_btn = QPushButton("Browse…")
        self._bg_media_btn.clicked.connect(self._pick_media)
        media_row.addWidget(self._bg_media)
        media_row.addWidget(self._bg_media_btn)
        mw = QWidget()
        mw.setLayout(media_row)
        bg_form.addRow("Media", mw)
        # Overlay mode: the slide image IS the background — hide the
        # background picker (kept in the layout so its widgets stay
        # alive).
        v.addWidget(bg_box)
        if self._overlay_mode:
            bg_box.hide()

        txt_box = QGroupBox("Text")
        txt_form = QFormLayout(txt_box)
        self._title = QLineEdit()
        txt_form.addRow("Title", self._title)
        title_row = QHBoxLayout()
        self._title_color = QLineEdit("#FFFFFF")
        self._title_color_btn = QPushButton("Pick…")
        self._title_color_btn.clicked.connect(
            lambda: self._pick_color(self._title_color))
        self._title_size = QSpinBox()
        self._title_size.setRange(8, 300)
        self._title_size.setValue(72)
        self._title_size.setSuffix(" px")
        title_row.addWidget(self._title_color)
        title_row.addWidget(self._title_color_btn)
        title_row.addWidget(self._title_size)
        tw = QWidget()
        tw.setLayout(title_row)
        txt_form.addRow("Title style", tw)
        self._subtitle = QLineEdit()
        txt_form.addRow("Subtitle", self._subtitle)
        sub_row = QHBoxLayout()
        self._sub_color = QLineEdit("#DDDDDD")
        self._sub_color_btn = QPushButton("Pick…")
        self._sub_color_btn.clicked.connect(
            lambda: self._pick_color(self._sub_color))
        self._sub_size = QSpinBox()
        self._sub_size.setRange(8, 200)
        self._sub_size.setValue(40)
        self._sub_size.setSuffix(" px")
        sub_row.addWidget(self._sub_color)
        sub_row.addWidget(self._sub_color_btn)
        sub_row.addWidget(self._sub_size)
        sw = QWidget()
        sw.setLayout(sub_row)
        txt_form.addRow("Subtitle style", sw)
        self._position = QComboBox()
        for label, key in (
                ("Center", "center"), ("Top", "top"),
                ("Bottom", "bottom")):
            self._position.addItem(label, key)
        txt_form.addRow("Position", self._position)
        self._fade = QDoubleSpinBox()
        self._fade.setRange(0.0, 5.0)
        self._fade.setSingleStep(0.1)
        self._fade.setDecimals(2)
        self._fade.setSuffix(" s")
        self._fade.setValue(0.6)
        self._fade.setToolTip(
            "Seconds to fade the text in at the start and out at "
            "the end. 0 = hard on/off." + (
                "  (Ignored for a per-slide overlay — it's baked "
                "onto a still.)" if self._overlay_mode else ""))
        if self._overlay_mode:
            self._fade.setEnabled(False)
        txt_form.addRow("Text fade", self._fade)
        v.addWidget(txt_box)

        # ── Effects (outline, shadow, legibility box) ──
        fx_box = QGroupBox("Effects")
        fx_form = QFormLayout(fx_box)
        out_row = QHBoxLayout()
        self._outline_color = QLineEdit("")
        self._outline_color.setPlaceholderText("none")
        self._outline_btn = QPushButton("Pick…")
        self._outline_btn.clicked.connect(
            lambda: self._pick_color(self._outline_color))
        self._outline_w = QSpinBox()
        self._outline_w.setRange(0, 20)
        self._outline_w.setSuffix(" px")
        out_row.addWidget(self._outline_color)
        out_row.addWidget(self._outline_btn)
        out_row.addWidget(self._outline_w)
        ow = QWidget()
        ow.setLayout(out_row)
        fx_form.addRow("Outline", ow)
        self._shadow = QCheckBox("Drop shadow behind text")
        fx_form.addRow("Shadow", self._shadow)
        box_row = QHBoxLayout()
        self._box_color = QLineEdit("")
        self._box_color.setPlaceholderText("none")
        self._box_btn = QPushButton("Pick…")
        self._box_btn.clicked.connect(
            lambda: self._pick_color(self._box_color))
        self._box_opacity = QDoubleSpinBox()
        self._box_opacity.setRange(0.0, 1.0)
        self._box_opacity.setSingleStep(0.1)
        self._box_opacity.setDecimals(2)
        self._box_opacity.setValue(0.5)
        box_row.addWidget(self._box_color)
        box_row.addWidget(self._box_btn)
        box_row.addWidget(self._box_opacity)
        bxw = QWidget()
        bxw.setLayout(box_row)
        fx_form.addRow("Box behind", bxw)
        v.addWidget(fx_box)

        tim_box = QGroupBox("Timing & transition")
        tim_form = QFormLayout(tim_box)
        self._duration = QDoubleSpinBox()
        self._duration.setRange(0.5, 120.0)
        self._duration.setDecimals(2)
        self._duration.setSingleStep(0.5)
        self._duration.setSuffix(" s")
        self._duration.setValue(4.0)
        tim_form.addRow("Duration", self._duration)
        self._transition = QComboBox()
        from src.video_studio.models import (
            CHAPTER_TRANSITIONS as _CT)
        for key, label in _CT:
            self._transition.addItem(label, key)
        tim_form.addRow("Transition in", self._transition)
        self._trans_secs = QDoubleSpinBox()
        self._trans_secs.setRange(0.0, 5.0)
        self._trans_secs.setDecimals(2)
        self._trans_secs.setSingleStep(0.1)
        self._trans_secs.setSuffix(" s")
        self._trans_secs.setValue(0.7)
        tim_form.addRow("Transition secs", self._trans_secs)

        audio_row = QHBoxLayout()
        self._edit_audio_btn = QPushButton("🎤 Edit audio…")
        self._edit_audio_btn.setToolTip(
            "Record / import / edit the card's narration or music — "
            "the same audio timeline as any group.")
        self._edit_audio_btn.clicked.connect(self._on_edit_audio_clicked)
        self._edit_audio_btn.setEnabled(self._on_edit_audio is not None)
        audio_row.addWidget(self._edit_audio_btn)
        audio_row.addStretch()
        # Deck-wide background bed under THIS card (only meaningful
        # when the deck actually has a background bed).
        self._bg_under_card = QCheckBox(
            "Play deck background music under this card")
        self._bg_under_card.setToolTip(
            "When the deck has a background bed, this controls "
            "whether it plays under this card. Turn it OFF for a "
            "silent card, or one that carries only its own audio.")
        self._bg_under_card.setChecked(
            bool(self._deck_bg_enabled_initial))
        if not self._deck_has_background:
            self._bg_under_card.setEnabled(False)
            self._bg_under_card.setText(
                "Play deck background under this card "
                "(no deck background set)")
        # Timing / transition / audio are card-group concepts —
        # a per-slide overlay has none of them (the slide owns its
        # own duration + transition), so hide them in overlay mode
        # (kept in the layout so their widgets stay alive).
        v.addWidget(tim_box)
        v.addLayout(audio_row)
        v.addWidget(self._bg_under_card)
        if self._overlay_mode:
            tim_box.hide()
            self._edit_audio_btn.hide()
            self._bg_under_card.hide()

        if self._canvas_mode:
            self._build_canvas_section(v, bg_box, txt_box, fx_box)
        # Content goes in the scroll area; buttons stay pinned below.
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)
        self._sync_kind()

    # -- WYSIWYG canvas (canvas_mode) ---------------------------------
    def _build_canvas_section(
        self, v, bg_box, txt_box, fx_box,
    ) -> None:
        """Insert the live design canvas (with a draggable element
        palette) at the top and a per-element properties panel below
        the background controls. The fixed title/subtitle text form
        and the card-level effects box are hidden — in canvas mode
        every piece is a free, layered element."""
        from src.ui.video_studio.slide_canvas import (
            SlideDesignCanvas, ElementPalette)
        txt_box.hide()
        fx_box.hide()
        canvas_box = QGroupBox(
            "Design canvas — drag a piece from the palette onto the "
            "slide, then drag to move, drag edges to resize, "
            "double-click to edit")
        cbl = QVBoxLayout(canvas_box)
        toolbar = QHBoxLayout()
        self._del_btn = QPushButton("🗑 Delete")
        self._del_btn.clicked.connect(self._on_delete_element)
        self._up_btn = QPushButton("⬆ Layer up")
        self._up_btn.clicked.connect(self._on_layer_up)
        self._down_btn = QPushButton("⬇ Layer down")
        self._down_btn.clicked.connect(self._on_layer_down)
        toolbar.addWidget(QLabel("Drag from palette →"))
        toolbar.addStretch()
        toolbar.addWidget(self._up_btn)
        toolbar.addWidget(self._down_btn)
        toolbar.addWidget(self._del_btn)
        cbl.addLayout(toolbar)
        # Palette on the left, canvas on the right.
        row = QHBoxLayout()
        self._palette = ElementPalette()
        self._palette.itemDoubleClicked.connect(
            self._on_palette_double_click)
        row.addWidget(self._palette)
        self._canvas = SlideDesignCanvas()
        self._canvas.selectionChanged.connect(self._on_canvas_selection)
        self._canvas.editRequested.connect(self._on_edit_element_text)
        self._canvas.addMediaRequested.connect(self._on_add_media)
        row.addWidget(self._canvas, 1)
        cbl.addLayout(row, 1)
        v.insertWidget(0, canvas_box, 1)
        self._props_box = self._build_element_props()
        v.insertWidget(2, self._props_box)
        # Background edits update the canvas live.
        self._kind.currentIndexChanged.connect(self._update_canvas_bg)
        self._bg_color.textChanged.connect(self._update_canvas_bg)
        self._bg_media.textChanged.connect(self._update_canvas_bg)
        self._on_canvas_selection(None)

    def _build_element_props(self) -> QGroupBox:
        box = QGroupBox("Selected element")
        outer = QVBoxLayout(box)
        self._kind_label = QLabel("—")
        outer.addWidget(self._kind_label)
        # ── Text controls (shown for text elements) ──
        self._text_props = QWidget()
        form = QFormLayout(self._text_props)
        form.setContentsMargins(0, 0, 0, 0)
        self._pb_text = QPlainTextEdit()
        self._pb_text.setPlaceholderText("Type the text…")
        self._pb_text.setFixedHeight(56)
        self._pb_text.textChanged.connect(self._push_props)
        form.addRow("Text", self._pb_text)
        style_row = QHBoxLayout()
        self._pb_size = QSpinBox()
        self._pb_size.setRange(8, 400)
        self._pb_size.setValue(72)
        self._pb_size.setSuffix(" px")
        self._pb_size.valueChanged.connect(self._push_props)
        self._pb_color = QLineEdit("#FFFFFF")
        self._pb_color.textChanged.connect(self._push_props)
        pick = QPushButton("Pick…")
        pick.clicked.connect(lambda: self._pick_color(self._pb_color))
        style_row.addWidget(QLabel("Size"))
        style_row.addWidget(self._pb_size)
        style_row.addWidget(QLabel("Color"))
        style_row.addWidget(self._pb_color)
        style_row.addWidget(pick)
        sw = QWidget()
        sw.setLayout(style_row)
        form.addRow("Font", sw)
        align_row = QHBoxLayout()
        self._pb_align = QComboBox()
        for lbl, key in (("Left", "left"), ("Center", "center"),
                         ("Right", "right")):
            self._pb_align.addItem(lbl, key)
        self._pb_align.setCurrentIndex(1)
        self._pb_align.currentIndexChanged.connect(self._push_props)
        self._pb_valign = QComboBox()
        for lbl, key in (("Top", "top"), ("Middle", "middle"),
                         ("Bottom", "bottom")):
            self._pb_valign.addItem(lbl, key)
        self._pb_valign.setCurrentIndex(1)
        self._pb_valign.currentIndexChanged.connect(self._push_props)
        self._pb_bold = QCheckBox("Bold")
        self._pb_bold.toggled.connect(self._push_props)
        self._pb_italic = QCheckBox("Italic")
        self._pb_italic.toggled.connect(self._push_props)
        align_row.addWidget(QLabel("Align"))
        align_row.addWidget(self._pb_align)
        align_row.addWidget(self._pb_valign)
        align_row.addWidget(self._pb_bold)
        align_row.addWidget(self._pb_italic)
        aw = QWidget()
        aw.setLayout(align_row)
        form.addRow("Layout", aw)
        fill_row = QHBoxLayout()
        self._pb_fill = QLineEdit("")
        self._pb_fill.setPlaceholderText("none")
        self._pb_fill.textChanged.connect(self._push_props)
        fill_pick = QPushButton("Pick…")
        fill_pick.clicked.connect(
            lambda: self._pick_color(self._pb_fill))
        self._pb_fill_op = QDoubleSpinBox()
        self._pb_fill_op.setRange(0.0, 1.0)
        self._pb_fill_op.setSingleStep(0.1)
        self._pb_fill_op.setValue(0.5)
        self._pb_fill_op.valueChanged.connect(self._push_props)
        fill_row.addWidget(self._pb_fill)
        fill_row.addWidget(fill_pick)
        fill_row.addWidget(QLabel("Opacity"))
        fill_row.addWidget(self._pb_fill_op)
        fw = QWidget()
        fw.setLayout(fill_row)
        form.addRow("Box fill", fw)
        fx_row = QHBoxLayout()
        self._pb_outline = QLineEdit("")
        self._pb_outline.setPlaceholderText("none")
        self._pb_outline.textChanged.connect(self._push_props)
        out_pick = QPushButton("Pick…")
        out_pick.clicked.connect(
            lambda: self._pick_color(self._pb_outline))
        self._pb_outline_w = QSpinBox()
        self._pb_outline_w.setRange(0, 20)
        self._pb_outline_w.setSuffix(" px")
        self._pb_outline_w.valueChanged.connect(self._push_props)
        self._pb_shadow = QCheckBox("Shadow")
        self._pb_shadow.toggled.connect(self._push_props)
        fx_row.addWidget(self._pb_outline)
        fx_row.addWidget(out_pick)
        fx_row.addWidget(self._pb_outline_w)
        fx_row.addWidget(self._pb_shadow)
        xw = QWidget()
        xw.setLayout(fx_row)
        form.addRow("Effects", xw)
        outer.addWidget(self._text_props)
        # ── Media controls (shown for image / video elements) ──
        self._media_props = QWidget()
        mform = QFormLayout(self._media_props)
        mform.setContentsMargins(0, 0, 0, 0)
        self._pm_file = QLabel("(no file)")
        self._pm_file.setWordWrap(True)
        mform.addRow("File", self._pm_file)
        mbtn_row = QHBoxLayout()
        self._pm_replace = QPushButton("Choose file…")
        self._pm_replace.clicked.connect(self._on_replace_media)
        self._pm_record = QPushButton("● Record video…")
        self._pm_record.clicked.connect(self._on_record_media)
        mbtn_row.addWidget(self._pm_replace)
        mbtn_row.addWidget(self._pm_record)
        mbtn_w = QWidget()
        mbtn_w.setLayout(mbtn_row)
        mform.addRow("Source", mbtn_w)
        vid_row = QHBoxLayout()
        self._pm_muted = QCheckBox("Muted")
        self._pm_muted.toggled.connect(self._push_props)
        self._pm_loop = QCheckBox("Loop to slide length")
        self._pm_loop.toggled.connect(self._push_props)
        vid_row.addWidget(self._pm_muted)
        vid_row.addWidget(self._pm_loop)
        vid_row.addStretch()
        vw = QWidget()
        vw.setLayout(vid_row)
        mform.addRow("Video", vw)
        outer.addWidget(self._media_props)
        self._media_props.hide()
        return box

    def _update_canvas_bg(self, *args) -> None:
        if not self._canvas_mode:
            return
        self._canvas.set_background(
            self._kind.currentData() or "color",
            self._bg_color.text().strip() or "#000000",
            self._bg_media.text().strip())

    def _on_palette_double_click(self, item) -> None:
        # Double-clicking a palette entry adds it at the frame center.
        kind = item.data(Qt.ItemDataRole.UserRole)
        self._canvas.add_element(kind)

    def _on_delete_element(self) -> None:
        self._canvas.delete_selected()

    def _on_layer_up(self) -> None:
        self._canvas.raise_selected()

    def _on_layer_down(self) -> None:
        self._canvas.lower_selected()

    def _on_edit_element_text(self, item) -> None:
        self._pb_text.setFocus()
        self._pb_text.selectAll()

    def _on_add_media(self, item) -> None:
        """A newly dropped image/video needs a file. For a video,
        offer record-or-choose; for an image, just choose."""
        if item.kind == "video":
            from PyQt6.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setWindowTitle("Add video")
            box.setText("Record a new video, or choose an existing "
                        "file?")
            rec = box.addButton(
                "● Record…", QMessageBox.ButtonRole.AcceptRole)
            cho = box.addButton(
                "Choose file…", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is rec:
                self._record_into(item)
            elif box.clickedButton() is cho:
                self._choose_media(item, "video")
        else:
            self._choose_media(item, "image")

    def _on_replace_media(self) -> None:
        item = self._canvas.selected()
        if item is not None and item.kind in ("image", "video"):
            self._choose_media(item, item.kind)

    def _on_record_media(self) -> None:
        item = self._canvas.selected()
        if item is not None:
            self._record_into(item)

    def _choose_media(self, item, kind: str) -> None:
        if kind == "video":
            filt = "Video (*.mp4 *.mov *.mkv *.webm);;All files (*)"
        else:
            filt = ("Image (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;"
                    "All files (*)")
        picked, _ = QFileDialog.getOpenFileName(
            self, f"Choose {kind}", "", filt)
        if not picked:
            return
        item.media_path = picked
        item.reload_pixmap()
        if kind == "video":
            self._set_video_preview(item, picked)
        self._on_canvas_selection(item)
        item.update()

    def _record_into(self, item) -> None:
        """Record a webcam+mic video and use it as this element."""
        from src.ui.video_studio.video_record_dialog import (
            VideoRecordDialog)
        dest_dir = self._recording_dir()
        dlg = VideoRecordDialog(dest_dir, parent=self)
        if dlg.exec() and dlg.output_path:
            item.kind = "video"
            item.media_path = dlg.output_path
            self._set_video_preview(item, dlg.output_path)
            self._on_canvas_selection(item)
            item.update()

    def _set_video_preview(self, item, path: str) -> None:
        """Extract a first frame so the video element shows a real
        thumbnail on the canvas."""
        try:
            from pathlib import Path as _P
            from PyQt6.QtGui import QPixmap
            from src.video_studio.slide_deck import _video_first_frame
            frame = _P(self._recording_dir()) / (
                f"_prev_{item.el_id or 'v'}.png")
            if _video_first_frame(path, frame):
                item.set_preview_pixmap(QPixmap(str(frame)))
        except Exception:
            pass

    def _recording_dir(self) -> str:
        from pathlib import Path as _P
        d = _P.home() / ".writingaid_slides" / "designed"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _on_canvas_selection(self, item) -> None:
        """Populate the properties panel from the selected element, or
        disable it when nothing is selected. Shows text OR media
        controls depending on the element kind."""
        has = item is not None
        self._props_box.setEnabled(has)
        for w in (self._del_btn, self._up_btn, self._down_btn):
            w.setEnabled(has)
        if not has:
            self._kind_label.setText("Select or drop an element to "
                                     "edit it.")
            self._text_props.hide()
            self._media_props.hide()
            return
        is_text = item.kind == "text"
        self._text_props.setVisible(is_text)
        self._media_props.setVisible(not is_text)
        self._kind_label.setText({
            "text": "📝 Text element",
            "image": "🖼 Image element",
            "video": "🎞 Video element (plays in export)",
        }.get(item.kind, item.kind))
        self._loading_props = True
        try:
            if is_text:
                self._pb_text.setPlainText(item.text or "")
                self._pb_size.setValue(int(item.font_size or 72))
                self._pb_color.setText(item.color or "#FFFFFF")
                self._pb_align.setCurrentIndex(max(
                    0, self._pb_align.findData(item.align or "center")))
                self._pb_valign.setCurrentIndex(max(
                    0, self._pb_valign.findData(
                        item.valign or "middle")))
                self._pb_bold.setChecked(bool(item.bold))
                self._pb_italic.setChecked(bool(item.italic))
                self._pb_fill.setText(item.box_color or "")
                self._pb_fill_op.setValue(
                    float(item.box_opacity or 0.5))
                self._pb_outline.setText(item.outline_color or "")
                self._pb_outline_w.setValue(
                    int(item.outline_width or 0))
                self._pb_shadow.setChecked(bool(item.shadow))
            else:
                name = (item.media_path or "").rsplit("/", 1)[-1]
                self._pm_file.setText(name or "(no file yet)")
                self._pm_record.setVisible(item.kind == "video")
                self._pm_muted.setVisible(item.kind == "video")
                self._pm_loop.setVisible(item.kind == "video")
                self._pm_muted.setChecked(bool(item.video_muted))
                self._pm_loop.setChecked(bool(item.video_loop))
        finally:
            self._loading_props = False

    def _push_props(self, *args) -> None:
        """Write the properties panel back onto the selected element
        and repaint it — live, as the writer edits."""
        if self._loading_props:
            return
        item = self._canvas.selected()
        if item is None:
            return
        if item.kind == "text":
            item.text = self._pb_text.toPlainText()
            item.font_size = int(self._pb_size.value())
            item.color = self._pb_color.text().strip() or "#FFFFFF"
            item.align = self._pb_align.currentData() or "center"
            item.valign = self._pb_valign.currentData() or "middle"
            item.bold = bool(self._pb_bold.isChecked())
            item.italic = bool(self._pb_italic.isChecked())
            item.box_color = self._pb_fill.text().strip()
            item.box_opacity = float(self._pb_fill_op.value())
            item.outline_color = self._pb_outline.text().strip()
            item.outline_width = int(self._pb_outline_w.value())
            item.shadow = bool(self._pb_shadow.isChecked())
        else:
            item.video_muted = bool(self._pm_muted.isChecked())
            item.video_loop = bool(self._pm_loop.isChecked())
        item.update()

    # -- helpers -------------------------------------------------------
    def _pick_color(self, target: QLineEdit) -> None:
        cur = QColor(target.text().strip() or "#000000")
        c = QColorDialog.getColor(
            cur if cur.isValid() else QColor("#000000"),
            self, "Pick color")
        if c.isValid():
            target.setText(c.name().upper())

    def _pick_media(self) -> None:
        kind = self._kind.currentData()
        if kind == "video":
            filt = "Video (*.mp4 *.mov *.mkv *.webm);;All files (*)"
        else:
            filt = ("Image (*.png *.jpg *.jpeg *.webp *.bmp);;"
                    "All files (*)")
        picked, _ = QFileDialog.getOpenFileName(
            self, "Pick background media", "", filt)
        if picked:
            self._bg_media.setText(picked)

    def _sync_kind(self) -> None:
        kind = self._kind.currentData()
        is_color = kind == "color"
        self._bg_color.setEnabled(is_color)
        self._bg_color_btn.setEnabled(is_color)
        self._bg_media.setEnabled(not is_color)
        self._bg_media_btn.setEnabled(not is_color)

    def _on_edit_audio_clicked(self) -> None:
        if self._on_edit_audio is not None:
            self._on_edit_audio()

    # -- load / save ---------------------------------------------------
    def _load_from_card(self) -> None:
        c = self._card
        idx = self._kind.findData(c.kind or "color")
        self._kind.setCurrentIndex(idx if idx >= 0 else 0)
        self._bg_color.setText(c.bg_color or "#000000")
        self._bg_media.setText(c.bg_media_path or "")
        self._title.setText(c.title or "")
        self._title_color.setText(c.title_color or "#FFFFFF")
        self._title_size.setValue(int(c.title_size or 72))
        self._subtitle.setText(c.subtitle or "")
        self._sub_color.setText(c.subtitle_color or "#DDDDDD")
        self._sub_size.setValue(int(c.subtitle_size or 40))
        pidx = self._position.findData(c.text_position or "center")
        self._position.setCurrentIndex(pidx if pidx >= 0 else 0)
        self._fade.setValue(float(c.text_fade_seconds or 0.0))
        # Effects.
        self._outline_color.setText(
            getattr(c, "text_outline_color", "") or "")
        self._outline_w.setValue(
            int(getattr(c, "text_outline_width", 0) or 0))
        self._shadow.setChecked(bool(getattr(c, "text_shadow", False)))
        self._box_color.setText(
            getattr(c, "text_box_color", "") or "")
        self._box_opacity.setValue(
            float(getattr(c, "text_box_opacity", 0.5) or 0.5))
        if self._canvas_mode:
            self._canvas.load_card(c)
        self._sync_kind()

    def _on_accept(self) -> None:
        c = self._card
        c.kind = self._kind.currentData() or "color"
        c.bg_color = self._bg_color.text().strip() or "#000000"
        c.bg_media_path = self._bg_media.text().strip()
        c.title = self._title.text().strip()
        c.title_color = self._title_color.text().strip() or "#FFFFFF"
        c.title_size = int(self._title_size.value())
        c.subtitle = self._subtitle.text().strip()
        c.subtitle_color = self._sub_color.text().strip() or "#DDDDDD"
        c.subtitle_size = int(self._sub_size.value())
        c.text_position = self._position.currentData() or "center"
        c.text_fade_seconds = float(self._fade.value())
        # Effects.
        c.text_outline_color = self._outline_color.text().strip()
        c.text_outline_width = int(self._outline_w.value())
        c.text_shadow = bool(self._shadow.isChecked())
        c.text_box_color = self._box_color.text().strip()
        c.text_box_opacity = float(self._box_opacity.value())
        if self._canvas_mode:
            self._canvas.apply_to_card(c)
        self.accept()

    # Values the host reads after exec() for the card's group / page.
    def duration_seconds(self) -> float:
        return float(self._duration.value())

    def transition_kind(self) -> str:
        return self._transition.currentData() or "cut"

    def transition_seconds(self) -> float:
        return float(self._trans_secs.value())

    def deck_background_enabled(self) -> bool:
        """Whether the deck bed should play under this card."""
        return bool(self._bg_under_card.isChecked())

    def set_timing(
            self, duration: float, trans_kind: str,
            trans_secs: float) -> None:
        self._duration.setValue(max(0.5, float(duration or 4.0)))
        tidx = self._transition.findData(trans_kind or "cut")
        self._transition.setCurrentIndex(tidx if tidx >= 0 else 0)
        self._trans_secs.setValue(float(trans_secs or 0.0))
