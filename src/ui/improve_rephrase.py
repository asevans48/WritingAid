"""The Improve window's ✨ Rephrase tab (piece D.2c, designed in D.2a §10).

Rephrase is **hosted, not rewritten**. The tab holds a real
``RephraseDialog`` (``hosted=True``), never shown itself, and shows its
parts: the Scene with ↻ Refresh, **Generate Options**, a one-line summary
of the choices and, behind **▸ Change options**, its 25 options (writing
style, tone with Custom, point of view, character voice, genre, cloud or
local). Its conversation is the tab's Talk it through.

The window forwards to the dialog, so every line of Rephrase's logic and
every rating row stays where it is:

* a picked Rephrase version selects its row in the dialog's hidden
  ``options_list`` (its delayed save and edit tracking run as before);
* edits in Your version are copied into the dialog's ``preview_edit``;
* a rating click calls ``_on_rating_clicked`` (saved 0.9 s after you stop
  editing, marked "edited" when you changed it);
* ✓ Accept calls ``_use_selected`` (a Poor or Bad rating first, the
  accepted row, and the "neutral" row for the unedited option).

Each version keeps its own edit and rating, so there is no "Discard your
edit?" question (decision 16). The dialog is built the first time the tab
is shown: opening the window on another tab starts no Rephrase work.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.ui.ui_kit import GAP, CollapsibleSection, plain, text_style

OPTIONS_OPEN_KEY = "improve/rephrase_options_open"


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


class RephraseTab:
    key = "rephrase"
    status_key = "rephrase"
    title = "✨ Rephrase"
    tip = ("AI Text Rephrasing: options in the styles and tones you pick, in your voice and "
           "the speaker's. Press Generate Options; you can edit a result before you accept it")

    def __init__(self, win, dialog_factory=None, args: Optional[dict] = None):
        self.win = win
        self.dialog_factory = dialog_factory
        self.args = args
        self.dlg = None
        self.started = False
        # The exact text Rephrase rewrites (Python indices): your highlight,
        # not the passage widened to whole sentences.
        self.span = tuple(win.selection) if win.selection else (win.start, win.end)

        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)
        self.layout.setContentsMargins(0, GAP, 0, GAP)
        self.layout.setSpacing(GAP)
        # The talk slot holds the dialog's conversation once it is built.
        self.talk = QWidget()
        self.talk_layout = QVBoxLayout(self.talk)
        self.talk_layout.setContentsMargins(0, 0, 0, 0)

    # ── Building (the first time the tab is shown) ───────────────────

    def _dialog_args(self) -> dict:
        if self.args is not None:
            return dict(self.args)
        # Opened on another tab: the same arguments the Write screen gives.
        text = self.win.text
        s, e = self.span
        return dict(text=text[s:e], surrounding_context=(text[max(0, s - 500):s], text[e:e + 500]),
                    chapter_content=text, chapter=self.win.chapter, text_before=text[:s])

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        try:
            self._build()
        except Exception as e:          # never let the tab break the window
            print(f"[improve] could not open Rephrase: {e}")
            self.win.set_status(self.key, f"Rephrase could not start: {e}")

    def _build(self) -> None:
        from src.ui.improve_window import _lines
        if self.dialog_factory is None:
            from src.ui.rephrase_dialog import RephraseDialog
            self.dialog_factory = RephraseDialog
        args = self._dialog_args()
        text = args.pop("text")
        d = self.dialog_factory(text, self.win.project, self.win, hosted=True, **args)
        self.dlg = d
        d.options_ready.connect(self._on_options)
        d.save_status.connect(self._on_save_status)
        lay = self.layout

        if self.span != (self.win.start, self.win.end):
            only = QLabel(f"Rephrase works on exactly what you highlighted: "
                          f"“{_short(d.original_text)}”")
            only.setWordWrap(True)
            only.setStyleSheet(text_style("ink_faint", 11))
            lay.addWidget(only)

        # The choices in one line; the 25 options behind ▸ Change options.
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(text_style("ink_soft"))
        lay.addWidget(self.summary)
        d.detect_status_label.setStyleSheet(text_style("ink_soft", 11, italic=True))
        lay.addWidget(d.detect_status_label)            # who was detected
        self.options = CollapsibleSection(
            "Change options (style, tone, point of view, character voice, genre, cloud or "
            "local)", "rephrase_options")
        body = self.options.body_layout
        genre_row = QHBoxLayout()
        genre_row.addWidget(QLabel("Genre:"))
        genre_row.addWidget(d.genre_combo, 1)
        body.addLayout(genre_row)
        groups = QHBoxLayout()
        groups.setSpacing(GAP)
        for g in (next(iter(d.style_checkboxes.values())).parentWidget(),
                  d.pov_combo.parentWidget(), d.custom_tone_cb.parentWidget()):
            groups.addWidget(g)
        body.addLayout(groups)
        body.addWidget(d.cloud_radio.parentWidget())    # AI Model: Cloud / Local
        self.options.set_open(self._options_open())
        self.options.toggled.connect(self._remember_options)
        lay.addWidget(self.options)

        # The Scene, in view, with ↻ Refresh (and a style flag's hint in it).
        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("<b>Scene</b>"))
        d.scene_status_label.setStyleSheet(text_style("ink_faint", 11))
        scene_row.addWidget(d.scene_status_label, 1)
        plain(d.scene_refresh_btn)
        d.scene_refresh_btn.setAutoDefault(False)
        scene_row.addWidget(d.scene_refresh_btn)
        lay.addLayout(scene_row)
        d.scene_desc_edit.setMinimumHeight(_lines(d.scene_desc_edit, 2))
        d.scene_desc_edit.setMaximumHeight(_lines(d.scene_desc_edit, 4))
        lay.addWidget(d.scene_desc_edit)
        run_row = QHBoxLayout()
        run_row.addWidget(d.progress_bar, 1)            # busy while generating
        run_row.addStretch()
        plain(d.generate_btn, pad="5px 14px", bold=True)
        d.generate_btn.setAutoDefault(False)
        run_row.addWidget(d.generate_btn)
        lay.addLayout(run_row)

        # Talk it through: Rephrase's own conversation.
        d.chat.set_busy(True, "Talk it through opens once you have generated options.")
        self.talk_layout.addWidget(d.chat)

        self._watch_choices()
        self._update_summary()
        if not d.python_mode_label.isHidden():          # no model: the Python libraries
            self.win.set_status(self.key, d.python_mode_label.text())

    def _options_open(self) -> bool:
        from src.ui import improve
        try:
            return str(improve._settings().value(OPTIONS_OPEN_KEY, "false")).lower() == "true"
        except Exception:
            return False

    def _remember_options(self, _key: str, collapsed: bool) -> None:
        from src.ui import improve
        try:
            s = improve._settings()
            s.setValue(OPTIONS_OPEN_KEY, "false" if collapsed else "true")
            s.sync()
        except Exception as e:
            print(f"[improve] could not remember the section: {e}")

    # ── The summary line ─────────────────────────────────────────────

    def _watch_choices(self) -> None:
        d = self.dlg
        for cb in list(d.style_checkboxes.values()) + list(d.tone_checkboxes.values()) + [
                d.custom_tone_cb, d.cloud_radio, d.local_radio]:
            cb.toggled.connect(lambda *_: self._update_summary())
        d.custom_tone_edit.textChanged.connect(lambda *_: self._update_summary())
        d.pov_combo.currentIndexChanged.connect(lambda *_: self._update_summary())
        d.genre_combo.currentIndexChanged.connect(lambda *_: self._update_summary())
        d.char_list.itemSelectionChanged.connect(self._update_summary)

    def summary_text(self) -> str:
        from PyQt6.QtCore import Qt
        d = self.dlg
        styles = [cb.text() for cb in d.style_checkboxes.values() if cb.isChecked()]
        tones = [cb.text() for cb in d.tone_checkboxes.values() if cb.isChecked()]
        custom = d._get_custom_tone()
        if custom:
            tones.append(f"“{custom}”")
        bits = [" · ".join(styles) if styles else "No style chosen",
                "Tone: " + (", ".join(tones) or "Neutral"),
                "POV: " + ("keep" if d.pov_combo.currentIndex() <= 0
                           else d.pov_combo.currentText())]
        voices = [i for i in d.char_list.selectedItems()]
        if voices:
            auto = any(i.data(Qt.ItemDataRole.UserRole) == "__auto__" for i in voices)
            names = [i.text().split(" (")[0] for i in voices
                     if i.data(Qt.ItemDataRole.UserRole) != "__auto__"]
            bits.append("Voice: " + ", ".join((["auto-detect"] if auto else []) + names))
        if d._get_selected_genre():
            bits.append("Genre: " + d.genre_combo.currentText())
        if not d.python_mode_label.isHidden():
            bits.append("Python libraries")
        elif d.local_radio.isChecked():
            bits.append("Local")
        else:
            bits.append("Cloud")
        return "  ·  ".join(bits)

    def _update_summary(self) -> None:
        try:
            self.summary.setText(self.summary_text())
        except Exception as e:          # an exception escaping a slot aborts PyQt6
            print(f"[improve] {e}")

    # ── Versions ─────────────────────────────────────────────────────

    def _on_options(self, result) -> None:
        """The dialog's options (after Generate, or new versions from the
        talk) become the window's Rephrase versions. Versions already shown
        keep their edits and ratings."""
        try:
            from src.ui.improve_window import Version
            d = self.dlg
            had = {id(v.data): v for v in self.win.versions if v.source == self.key}
            versions = []
            for opt in result.options:
                v = had.get(id(opt))
                if v is None:
                    v = Version(opt.text, self.key,
                                kind="revised" if opt.style.startswith("revised") else "suggestion",
                                why=f"Style: {opt.style} | Tone: {opt.tone} — {opt.explanation}",
                                angle=opt.style, span=self.span, data=opt)
                versions.append(v)
            d.chat.set_busy(False, "")
            learned = (getattr(d, "_examples_from", None) or {}).get("from", "")
            from src.ui.improve_window import RATE_TIP
            self.win.set_rate_tip(self.key, RATE_TIP + (
                f"\nLearned from rewrites you rated, {learned}." if learned else ""))
            self._update_summary()                       # who was detected
            self.win.replace_versions(self.key, versions)
        except Exception as e:          # an exception escaping a slot aborts PyQt6
            print(f"[improve] could not show the rephrase options: {e}")

    def _row(self, version) -> int:
        d = self.dlg
        if d is None or d.result is None:
            return -1
        for i, opt in enumerate(d.result.options):
            if opt is version.data:
                return i
        return -1

    def shown(self, version) -> None:
        """The window shows ``version``: select its row in the dialog, with
        its own edit and rating. Leaving a Rephrase version saves a rating
        still waiting, as switching options always did."""
        d = self.dlg
        if d is None or d.result is None:
            return
        if version is None or version.source != self.key:
            if d._pending_rating:
                d._save_timer.stop()
                d._flush_pending_rating_save()
            return
        row = self._row(version)
        if row < 0:
            return
        # The rating shown is the rating saved (each version keeps its own).
        d._selected_rating = version.rating or "neutral"
        for value, btn in (("excellent", d.rate_excellent_btn), ("good", d.rate_good_btn),
                           ("poor", d.rate_poor_btn), ("bad", d.rate_bad_btn)):
            btn.setChecked(value == version.rating)
        if d.options_list.currentRow() != row:
            d.options_list.setCurrentRow(row)            # flushes a waiting rating, loads it
        elif d.preview_edit.toPlainText() != version.text and version.edited is None:
            d._reset_preview_edit()
        if version.edited is not None and d.preview_edit.toPlainText() != version.edited:
            d.preview_edit.setPlainText(version.edited)  # marks it edited, as typing did

    def edited(self, version, text: str) -> None:
        """Typing in Your version: the same text in the dialog's preview."""
        if self.dlg is not None and version is not None and version.source == self.key:
            self._sync(version, text)

    def _sync(self, version, text: str) -> None:
        d = self.dlg
        if self._row(version) != d.options_list.currentRow():
            self.shown(version)
        if d.preview_edit.toPlainText() != text:
            d.preview_edit.setPlainText(text)

    def _on_save_status(self, text: str) -> None:
        v = self.win.current_version()
        if v is not None and v.source == self.key:
            self.win.rating_status.setText(text)

    # ── Rating and accepting (RephraseDialog's own calls) ────────────

    def rate(self, version, value: str, text: str) -> str:
        d = self.dlg
        self._sync(version, text)
        d._on_rating_clicked(value)
        return d._save_status_label.text()

    def accept(self, version, text: str) -> str:
        d = self.dlg
        self._sync(version, text)
        d._selected_rating = version.rating or "neutral"
        d._use_selected()
        return self.key

    def stop(self) -> None:
        d = self.dlg
        if d is None:
            return
        try:
            if d._pending_rating:                        # closing: save it now, not later
                d._save_timer.stop()
                d._flush_pending_rating_save()
        except Exception as e:
            print(f"[improve] {e}")
        for signal, slot in ((d.options_ready, self._on_options),
                             (d.save_status, self._on_save_status)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        d.done(0)                                        # its workers' results are dropped
