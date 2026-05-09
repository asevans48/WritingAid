"""Reusable rating + save-for-training widget.

Used by the critique tabs and the long-form writing completion to let
the author rate AI-generated output and (optionally) save it as
training data via the existing ``rephrase_database`` infrastructure.

The widget is deliberately minimal — four rating buttons + a
"Save for training" checkbox + an inline status label. It emits a
``rated`` signal when the user clicks a rating; the caller is
responsible for persisting via ``RephraseDatabase.log()`` (the widget
exposes a ``persist`` helper that handles the common case).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QWidget,
)


_RATING_BUTTONS = [
    ("excellent", "⭐ Excellent", "#10b981"),
    ("good",      "👍 Good",      "#3b82f6"),
    ("poor",      "👎 Poor",      "#f59e0b"),
    ("bad",       "✖ Bad",        "#ef4444"),
]


class RatingBar(QWidget):
    """A compact rating row with save-for-training toggle.

    Signals:
        rated(str): emitted with the rating value (excellent | good
            | poor | bad) when the user clicks a rating button.
    """

    rated = pyqtSignal(str)

    def __init__(
        self,
        label: str = "Rate this:",
        parent: Optional[QWidget] = None,
        compact: bool = False,
    ):
        super().__init__(parent)
        self._buttons: Dict[str, QPushButton] = {}
        self._selected_rating: str = ""
        self._save_default = self._is_collection_enabled_default()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(lbl)

        for value, text, color in _RATING_BUTTONS:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #f3f4f6; color: #374151;
                    border: 1px solid #d1d5db; border-radius: 4px;
                    padding: 3px 10px; font-size: 11px;
                }}
                QPushButton:checked {{
                    background-color: {color}; color: white;
                    border-color: {color};
                }}
                QPushButton:hover {{ background-color: #e5e7eb; }}
                QPushButton:checked:hover {{ background-color: {color}; }}
            """)
            btn.clicked.connect(lambda _checked=False, v=value: self._on_clicked(v))
            self._buttons[value] = btn
            layout.addWidget(btn)

        self.save_check = QCheckBox("Save for training")
        self.save_check.setToolTip(
            "When checked, the rated output is logged to the local "
            "training database so future model runs can learn from "
            "your judgments. Requires data collection to be enabled "
            "in Creative OS settings.")
        self.save_check.setChecked(self._save_default)
        self.save_check.setStyleSheet("font-size: 11px; color: #4b5563;")
        layout.addWidget(self.save_check)

        layout.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #059669; font-size: 11px; font-style: italic;")
        layout.addWidget(self.status_label)

        if compact:
            # Hide labels in compact mode to save vertical space; the
            # buttons themselves are self-describing.
            lbl.hide()

    # ── Public API ────────────────────────────────────────────────

    def selected_rating(self) -> str:
        return self._selected_rating

    def is_save_enabled(self) -> bool:
        return self.save_check.isChecked()

    def set_status(self, text: str, ok: bool = True):
        """Display a short status message (used after persist)."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color: {color}; font-size: 11px; font-style: italic;".format(
                color="#059669" if ok else "#dc2626"))

    def reset(self):
        """Clear the selected rating + status (for re-use in another row)."""
        for btn in self._buttons.values():
            btn.setChecked(False)
        self._selected_rating = ""
        self.status_label.setText("")

    def persist(
        self,
        source_text: str,
        output_text: str,
        source_type: str = "chat_writing",
        notes: str = "",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist the current rating to the rephrase database.

        Returns True on success, False if collection is disabled, the
        save toggle is off, no rating was selected, or the DB rejects
        the row.
        """
        if not self._selected_rating:
            self.set_status("Pick a rating first.", ok=False)
            return False
        if not self.save_check.isChecked():
            self.set_status(
                f"Rated {self._selected_rating} (not saved)", ok=True)
            return True
        try:
            from src.data.rephrase_database import (
                get_rephrase_database, is_collection_enabled)
        except Exception as e:
            self.set_status(f"DB unavailable: {e}", ok=False)
            return False
        if not is_collection_enabled():
            self.set_status(
                "Rated. Enable data collection in Creative OS "
                "settings to save for training.", ok=False)
            return False
        try:
            db = get_rephrase_database()
            db.log(
                source_text=source_text or "(no source)",
                output_text=output_text or "(empty)",
                source_type=source_type,
                rating=self._selected_rating,
                accepted=self._selected_rating in ("excellent", "good"),
                notes=notes,
                **(extra_fields or {}),
            )
            self.set_status(
                f"Saved as {self._selected_rating} for training", ok=True)
            return True
        except Exception as e:
            self.set_status(f"Save failed: {e}", ok=False)
            return False

    # ── Internals ─────────────────────────────────────────────────

    def _on_clicked(self, value: str):
        """Single-select behavior: clicking a rating uncheck the others."""
        for v, btn in self._buttons.items():
            btn.setChecked(v == value)
        self._selected_rating = value
        self.set_status(f"Rated {value}", ok=True)
        self.rated.emit(value)

    @staticmethod
    def _is_collection_enabled_default() -> bool:
        try:
            from src.data.rephrase_database import is_collection_enabled
            return bool(is_collection_enabled())
        except Exception:
            return False


def attach_rating_bar(
    parent_layout,
    label: str = "Rate this:",
    on_rate: Optional[Callable[[str], None]] = None,
    compact: bool = False,
) -> RatingBar:
    """Helper: build a RatingBar, add it to ``parent_layout``, and return it.

    Pass ``on_rate`` as a shortcut when you don't want to wire the
    ``rated`` signal manually — the callback gets the rating value.
    """
    bar = RatingBar(label=label, compact=compact)
    if on_rate is not None:
        bar.rated.connect(on_rate)
    parent_layout.addWidget(bar)
    return bar


# ── Long-form rating dialog ──────────────────────────────────────────


from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton


class LongFormRatingDialog(QDialog):
    """Modeless dialog surfaced after a long-form draft completes.

    Shows a one-line summary + a RatingBar + Close. When the user
    picks a rating, the dialog persists ONE row per beat to the
    rephrase database — each row pairs the beat's title + description
    (source) with the generated prose (output) so the trainer can
    learn from per-beat preferences. The bar's save toggle gates
    persistence in the usual way.
    """

    def __init__(
        self,
        chapter_title: str,
        beats: list,  # list of (title, description, prose, prompt)
        plan_summary: str = "",
        project_path: str = "",
        genre: str = "",
        voice: str = "",
        pov: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Rate the draft")
        self.setModal(False)
        self.setMinimumWidth(540)
        # Normalise to 4-tuples so older callers passing 3-tuples
        # (title, description, prose) still work — the prompt is just
        # empty in that case and the persister falls back to a
        # reconstructed instruction.
        normalised = []
        for entry in beats:
            if len(entry) == 4:
                normalised.append(entry)
            elif len(entry) == 3:
                t, d, p = entry
                normalised.append((t, d, p, ""))
        self._beats = normalised
        self._project_path = project_path
        self._genre = genre
        self._voice = voice
        self._pov = pov
        self._chapter_title = chapter_title

        layout = QVBoxLayout(self)
        header = QLabel(
            f"<b>Draft of \"{chapter_title}\" finished.</b> "
            f"Rate the result so the trainer can learn from it.")
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(header)
        if plan_summary:
            sub = QLabel(plan_summary)
            sub.setWordWrap(True)
            sub.setStyleSheet(
                "color: #6b7280; font-size: 11px; padding: 2px 4px;")
            layout.addWidget(sub)
        self.bar = RatingBar(label="Rate this draft:", compact=False)
        self.bar.rated.connect(self._on_rated)
        layout.addWidget(self.bar)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_rated(self, value: str):
        """Persist one row per beat with the chosen rating.

        Each row is a real (instruction, completion) pair: the
        ``source_text`` is the actual LLM prompt the agent used for
        that beat (chapter constraints + running synopsis + RAG
        context + the beat brief), and ``output_text`` is the prose
        the model produced. Saved under ``SOURCE_LONG_FORM`` so the
        trainer can filter / weight long-form rows directly.
        """
        if not self.bar.is_save_enabled():
            self.bar.set_status(
                f"Rated {value} (not saved)", ok=True)
            return
        try:
            from src.data.rephrase_database import (
                get_rephrase_database, is_collection_enabled,
                SOURCE_LONG_FORM,
            )
        except Exception as e:
            self.bar.set_status(f"DB unavailable: {e}", ok=False)
            return
        if not is_collection_enabled():
            self.bar.set_status(
                "Rated. Enable data collection in Creative OS "
                "settings to save for training.", ok=False)
            return
        try:
            db = get_rephrase_database()
            saved = 0
            for i, (title, description, prose, prompt) in enumerate(
                    self._beats):
                if not (prose or "").strip():
                    continue
                # Prefer the real prompt the LLM saw. When the upstream
                # didn't capture one (e.g. an older worker version),
                # fall back to a synthesised instruction so the row is
                # still trainable — but flag it in notes so the
                # trainer can down-weight or skip stub instructions.
                if prompt and prompt.strip():
                    source_text = prompt
                    prompt_kind = "real"
                else:
                    source_text = (
                        f"Write the next scene-beat of \"{self._chapter_title}\".\n"
                        f"Beat: {title}\n"
                        f"Description: {description}\n"
                        f"POV: {self._pov or '(unspecified)'}\n"
                        f"Voice: {self._voice or '(unspecified)'}\n"
                        f"Genre: {self._genre or '(unspecified)'}").strip()
                    prompt_kind = "synthesised"
                notes_parts = [
                    f"long_form_chapter={self._chapter_title}",
                    f"beat_index={i+1}/{len(self._beats)}",
                    f"beat_title={title}",
                    f"prompt_kind={prompt_kind}",
                ]
                if self._genre:
                    notes_parts.append(f"genre={self._genre}")
                if self._pov:
                    notes_parts.append(f"pov={self._pov}")
                notes = " ".join(notes_parts)
                db.log(
                    source_text=source_text,
                    output_text=prose,
                    source_type=SOURCE_LONG_FORM,
                    rating=value,
                    accepted=value in ("excellent", "good"),
                    notes=notes,
                    project_path=self._project_path,
                    genre=self._genre,
                    voice=self._voice,
                )
                saved += 1
            self.bar.set_status(
                f"Saved {saved} beat(s) as {value} for training",
                ok=True)
        except Exception as e:
            self.bar.set_status(f"Save failed: {e}", ok=False)
