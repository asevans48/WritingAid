"""Editor for a title / ending card — background (color / image /
video), styled title + subtitle text, fade, position, duration, and
the transition INTO the card. Audio is edited via the group editor
(a card is its own group), reached with the "🎤 Edit audio…" button.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from src.video_studio.models import TitleCard


def _color_button(initial: str) -> "QPushButton":
    btn = QPushButton(initial or "#000000")
    return btn


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
        self.setWindowTitle(f"🎬 {title_bar}")
        self.resize(460, 640)
        self._build_ui()
        self._load_from_card()

    # -- UI ------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)

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

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        v.addWidget(self._buttons)
        self._sync_kind()

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
