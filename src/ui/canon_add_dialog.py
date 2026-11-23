"""Add a world element or a character found by the Critique.

In the Critique's Worldbuilding report each line under "New elements (not in
worldbuilding)" gets an **＋ Add to World…** link. In the Characters report
each line under "Speakers with no character record" gets **＋ Add as a
character…**. The link opens this pop-up:

* the fields start from what the report said (name, kind, description);
* **✨ Fill with AI** drafts the empty fields from the passages where the
  name appears (a configured model, in the background). Fields the writer
  has typed in are never overwritten;
* everything is editable; **Add** saves it through the app's existing
  creators (``MainWindow._create_from_plot_ai_suggestion``), so an element
  that already exists under a similar name has its empty fields filled
  instead of being duplicated.

With no model, the pop-up is a form with the passages beside it.
"""

from __future__ import annotations

import hashlib
import html
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton,
    QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from src.ai import canon_from_critique as cc
from src.ui.ui_kit import PALETTE, fit_to_screen, primary_button, scrollable

WORLD_HEADING = "New elements (not in worldbuilding)"
CHARACTER_HEADING = "Speakers with no character record"


class CanonAddDialog(QDialog):
    def __init__(self, project: Any, kind: str, item_text: str, parent=None,
                 llm_factory=None):
        """``kind`` is "world" or "character"; ``item_text`` the report's line."""
        super().__init__(parent)
        self.project = project
        self.is_character = kind == "character"
        self._llm_factory = llm_factory or _default_llm
        self._task = None
        self._auto: Dict[str, str] = {}            # field → text last put there by the app
        parsed = cc.parse_item(item_text)
        self.setWindowTitle("Add a character" if self.is_character else "Add to World")

        outer = QVBoxLayout(self)
        intro = QLabel(
            ("The Critique found this character speaking but not in your Characters. "
             if self.is_character else
             "The Critique found this in your chapters but not in your World. ")
            + "Fill in what you know, or let a model draft it from the passages, then edit.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {PALETTE['ink_soft']};")
        outer.addWidget(intro)
        self.mode_new = QRadioButton("Add as a new element")
        self.mode_connect = QRadioButton("Connect to something already in your World")
        self.mode_connect.setToolTip(
            "For a new name that refers to an element or term you already have: another "
            "name for it, a part of it, or something that belongs to it. It goes in your "
            "World's Encyclopedia, linked to that element.")
        modes = QButtonGroup(self)
        for b in (self.mode_new, self.mode_connect):
            modes.addButton(b)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_new)
        mode_row.addWidget(self.mode_connect)
        mode_row.addStretch()
        if not self.is_character:
            outer.addLayout(mode_row)
        else:
            self.mode_new.hide()
            self.mode_connect.hide()

        self.name_edit = QLineEdit(parsed["name"])
        name_row = QFormLayout()
        name_row.addRow("Name", self.name_edit)
        outer.addLayout(name_row)

        body = QWidget()
        cols = QHBoxLayout(body)
        cols.setContentsMargins(0, 0, 0, 0)
        form_box = QWidget()
        self.form = QFormLayout(form_box)
        self.kind_combo = QComboBox()
        if self.is_character:
            for role in cc.CHARACTER_ROLES:
                self.kind_combo.addItem(role.title(), role)
            self.form.addRow("Role", self.kind_combo)
        else:
            for key, (label, _list) in cc.WORLD_KINDS.items():
                self.kind_combo.addItem(label, key)
            i = self.kind_combo.findData(parsed["kind"] or "place")
            self.kind_combo.setCurrentIndex(max(0, i))
            self.form.addRow("Kind", self.kind_combo)
        self._kind_set_by_writer = bool(parsed["kind"])
        self.kind_combo.activated.connect(lambda _i: setattr(self, "_kind_set_by_writer", True))
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._build_fields())
        self.fields: Dict[str, Any] = {}
        self._field_rows = []
        self._seed = {"description": parsed["description"]}
        if parsed["example"]:
            self._seed["notes"] = f"In the text: “{parsed['example']}”"
        self._build_fields()
        self.stack = QStackedWidget()
        self.stack.addWidget(form_box)
        self.stack.addWidget(self._connect_page(parsed))
        cols.addWidget(self.stack, 3)

        side = QVBoxLayout()
        side.addWidget(QLabel("Where it appears"))
        self.passages = QTextBrowser()
        self._found = cc.passages(project, parsed["name"])
        self._show_passages()
        side.addWidget(self.passages, 1)
        cols.addLayout(side, 2)
        outer.addWidget(scrollable(body), 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {PALETTE['ink_faint']};")
        outer.addWidget(self.status)
        self._show_existing()
        self.name_edit.textChanged.connect(lambda _t: self._show_existing())
        self.mode_new.toggled.connect(lambda _on: self._on_mode())

        row = QHBoxLayout()
        self.ai_btn = QPushButton("✨ Fill with AI")
        self.ai_btn.setToolTip("Draft the empty fields from the passages where the name "
                               "appears. Anything you've typed stays as it is.")
        self.ai_btn.clicked.connect(self.fill_with_ai)
        row.addWidget(self.ai_btn)
        row.addStretch()
        buttons = QDialogButtonBox()
        self.add_btn = primary_button("Add character" if self.is_character else "Add to World")
        buttons.addButton(self.add_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        outer.addLayout(row)
        # Start on "connect" when the name shares a word with something recorded.
        likely = (not self.is_character and self._ranked
                  and self._ranked[0][0] >= 3.0)
        (self.mode_connect if likely else self.mode_new).setChecked(True)
        self._on_mode()
        if not _ai_available():
            self.ai_btn.setEnabled(False)
            self.ai_btn.setToolTip("No model is set up (or AI is switched off). Fill the "
                                   "fields in by hand; the passages are on the right.")
        fit_to_screen(self, 900, 620)

    # ── Fields ───────────────────────────────────────────────────

    def kind(self) -> str:
        if self.is_character:
            return "character"
        return "term" if self.connecting() else self.kind_combo.currentData()

    def connecting(self) -> bool:
        return not self.is_character and self.mode_connect.isChecked()

    # ── Connecting to something already recorded ─────────────────

    def _connect_page(self, parsed) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._ranked = [] if self.is_character else cc.rank_targets(
            self.project, parsed["name"], cc.passages(self.project, parsed["name"]))
        self.target_search = QLineEdit()
        self.target_search.setPlaceholderText("Search your World…")
        self.target_search.textChanged.connect(self._fill_targets)
        form.addRow("Connect to", self.target_search)
        self.target_list = QListWidget()
        self.target_list.setMinimumHeight(self.target_list.fontMetrics().lineSpacing() * 6)
        self.target_list.itemClicked.connect(lambda _i: setattr(self, "_target_by_writer", True))
        self.target_list.currentItemChanged.connect(lambda *_: self._show_existing())
        form.addRow("", self.target_list)
        self.relation_combo = QComboBox()
        for key, phrase in cc.RELATIONS.items():
            self.relation_combo.addItem(f"{phrase} it", key)
        self.relation_combo.activated.connect(
            lambda _i: setattr(self, "_relation_by_writer", True))
        self.relation_combo.currentIndexChanged.connect(lambda _i: self._show_existing())
        form.addRow("The new name is", self.relation_combo)
        self.definition_edit = QPlainTextEdit(parsed["description"])
        self.definition_edit.setMinimumHeight(self.definition_edit.fontMetrics().lineSpacing() * 3 + 12)
        if parsed["description"]:
            self._auto["definition"] = parsed["description"]
        form.addRow("What it means", self.definition_edit)
        self.term_notes = QPlainTextEdit(
            f"In the text: “{parsed['example']}”" if parsed["example"] else "")
        self.term_notes.setMinimumHeight(self.term_notes.fontMetrics().lineSpacing() * 2 + 12)
        form.addRow("Notes", self.term_notes)
        self._target_by_writer = self._relation_by_writer = False
        self._fill_targets()
        return page

    def _fill_targets(self, _text: str = "") -> None:
        query = self.target_search.text().strip().lower()
        chosen = self.target()
        self.target_list.clear()
        for score, t in self._ranked:
            label = f"{t['name']} — {t['category']}"
            if query and query not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, t)
            item.setToolTip(t.get("summary", "") or label)
            self.target_list.addItem(item)
        if self.target_list.count() == 0:
            item = QListWidgetItem("Nothing in your World matches yet." if self._ranked
                                   else "Your World has no elements or terms yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.target_list.addItem(item)
            return
        self.select_target(chosen["name"] if chosen else
                           (self._ranked[0][1]["name"] if self._ranked and self._ranked[0][0] >= 1.5
                            and not query else ""))

    def target(self) -> Optional[Dict[str, str]]:
        item = self.target_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def select_target(self, name: str) -> bool:
        for i in range(self.target_list.count()):
            t = self.target_list.item(i).data(Qt.ItemDataRole.UserRole)
            if t and t["name"].lower() == (name or "").lower():
                self.target_list.setCurrentRow(i)
                return True
        return False

    def _on_mode(self) -> None:
        connecting = self.connecting()
        self.stack.setCurrentIndex(1 if connecting else 0)
        self.kind_combo.setEnabled(not connecting)
        self.add_btn.setText("Connect" if connecting else
                             ("Add character" if self.is_character else "Add to World"))
        self._show_existing()

    def _build_fields(self) -> None:
        """The fields for the chosen kind; what's typed carries over."""
        kept = {k: self._text(w) for k, w in self.fields.items()}
        for label, widget in self._field_rows:
            self.form.removeRow(widget)
        self.fields, self._field_rows = {}, []
        for key, label, multi in cc.FIELDS[self.kind()]:
            w = QPlainTextEdit() if multi else QLineEdit()
            if multi:
                w.setTabChangesFocus(True)
                lines = 3 if key in ("description", "personality", "backstory") else 2
                w.setMinimumHeight(w.fontMetrics().lineSpacing() * lines + 12)
            text = kept.get(key) or self._seed.get(key, "")
            self._set(w, text)
            if text and key in self._seed and text == self._seed[key]:
                self._auto[key] = text
            self.form.addRow(label, w)
            self.fields[key] = w
            self._field_rows.append((label, w))

    @staticmethod
    def _text(w) -> str:
        return (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()

    @staticmethod
    def _set(w, text: str) -> None:
        if isinstance(w, QPlainTextEdit):
            w.setPlainText(text)
        else:
            w.setText(text)

    def data(self) -> Dict[str, Any]:
        """What the creators read, plus the extra fields; for a connected
        term, its Encyclopedia entry."""
        if self.connecting():
            target = self.target() or {"name": "", "category": ""}
            return cc.term_entry(self.name_edit.text().strip(), target,
                                 self.relation_combo.currentData(),
                                 self.definition_edit.toPlainText(), self.term_notes.toPlainText())
        d: Dict[str, Any] = {"name": self.name_edit.text().strip()}
        for key, w in self.fields.items():
            text = self._text(w)
            if text:
                d[key] = text
        if self.is_character:
            d["character_type"] = self.kind_combo.currentData()
        return d

    def _show_passages(self) -> None:
        if not self._found:
            self.passages.setHtml(f"<p style='color:{PALETTE['ink_faint']}'><i>The name "
                                  "isn't found in the chapters as written.</i></p>")
            return
        name = html.escape(self.name_edit.text().strip())
        parts = []
        for p in self._found:
            esc = html.escape(p)
            if name:
                esc = esc.replace(name, f"<b>{name}</b>")
            parts.append(f"<p>{esc}</p>")
        self.passages.setHtml("".join(parts))

    def _show_existing(self) -> None:
        from src.utils.fuzzy_match import find_similar_element
        name = self.name_edit.text().strip()
        if not hasattr(self, "add_btn"):
            return                                  # still being built
        if self.connecting():
            t = self.target()
            self.status.setText(
                f"“{name}” goes in your World's Encyclopedia as "
                f"{cc.RELATIONS[self.relation_combo.currentData()].lower()} {t['name']}. "
                "A mention of it then counts as a mention of that element." if t and name
                else "Pick what it refers to.")
            return
        items = (getattr(self.project, "characters", None) if self.is_character else
                 [x for _k, (_l, attr) in cc.WORLD_KINDS.items()
                  for x in getattr(getattr(self.project, "worldbuilding", None), attr, None) or []])
        match = find_similar_element(name, items or [], threshold=0.85) if name else None
        if match is not None:
            self.status.setText(f"“{match.name}” is already recorded: adding fills in its "
                                "empty fields and keeps everything already there.")
        else:
            self.status.setText("")

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            self.status.setText("Give it a name first.")
            return
        if self.connecting() and self.target() is None:
            self.status.setText("Pick what it refers to, or choose “Add as a new element”.")
            return
        self.accept()

    # ── AI ───────────────────────────────────────────────────────

    def fill_with_ai(self) -> None:
        from src.ui.background import run_background
        if self._task is not None:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText("Give it a name first.")
            return
        kind = self.kind()
        genre = getattr(getattr(self.project, "prose_profile", None), "genre", "") or ""
        found = self._found or cc.passages(self.project, name)
        if kind == "term":
            candidates = [t for _s, t in self._ranked[:15]]
            prompt = cc.build_connect_prompt(name, found, candidates)
        else:
            prompt = cc.build_prompt(kind, name, found, genre, cc.known_names(self.project, kind),
                                     self._seed.get("description", ""))
        factory = self._llm_factory
        task_name = "character" if self.is_character else "worldbuilding"

        def work():
            llm = factory(task_name)
            if llm is None:
                raise RuntimeError("no model is set up")
            reply = llm.generate_text(prompt, cc.SYSTEM_PROMPT, max_tokens=700, temperature=0.4)
            if (reply or "").startswith("Error generating text:"):
                raise RuntimeError(reply.split(":", 1)[1].strip())
            if kind == "term":
                return {"_connect": True, **cc.parse_connect_reply(reply, candidates)}
            return cc.parse_reply(kind, reply)

        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("Drafting…")
        self.status.setText("Drafting from the passages…")
        self._task = run_background(work, self._filled, owner=self, label="canon-fill")

    def _filled(self, result: Optional[Dict[str, str]], error: str) -> None:
        self._task = None
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("✨ Fill with AI")
        if error or not result:
            self.status.setText(f"Couldn't draft it: {error or 'the model gave nothing usable'}.")
            return
        if result.pop("_connect", False):
            self._connected(result)
            return
        if not self.is_character and result.get("kind") and not self._kind_set_by_writer:
            i = self.kind_combo.findData(result["kind"])
            if i >= 0 and i != self.kind_combo.currentIndex():
                self.kind_combo.setCurrentIndex(i)          # rebuilds the fields
        if self.is_character and result.get("character_type"):
            i = self.kind_combo.findData(result["character_type"])
            if i >= 0:
                self.kind_combo.setCurrentIndex(i)
        filled = 0
        for key, w in self.fields.items():
            value = (result.get(key) or "").strip()
            current = self._text(w)
            if value and (not current or current == self._auto.get(key)):
                self._set(w, value)
                self._auto[key] = value
                filled += 1
        self.status.setText(f"Drafted {filled} field{'s' if filled != 1 else ''}. "
                            "Edit anything, then add it." if filled else
                            "The model had nothing to add beyond what's there.")


    def _connected(self, result: Dict[str, str]) -> None:
        """A model's suggestion for a connection; the writer's own choices stay."""
        done = []
        if result.get("target") and not self._target_by_writer:
            self.target_search.clear()
            if self.select_target(result["target"]):
                done.append("what it refers to")
        if result.get("relation") and not self._relation_by_writer:
            self.relation_combo.setCurrentIndex(self.relation_combo.findData(result["relation"]))
            done.append("how")
        current = self.definition_edit.toPlainText().strip()
        if result.get("definition") and (not current or current == self._auto.get("definition")):
            self.definition_edit.setPlainText(result["definition"])
            self._auto["definition"] = result["definition"]
            done.append("what it means")
        self._show_existing()
        if done:
            self.status.setText("Suggested " + ", ".join(done) + ". " + self.status.text())
        else:
            self.status.setText("The model had nothing to add beyond what's there.")


def _ai_available() -> bool:
    try:
        from src.config.ai_config import get_ai_config
        return not get_ai_config().is_ai_disabled()
    except Exception:
        return False


def _default_llm(task: str):
    from src.ai.task_llm import build_default_llm, build_task_llm_override
    return build_task_llm_override(task) or build_default_llm()


# ── The Critique's side ────────────────────────────────────────────────

def canon_link(grader, heading: str, text: str) -> str:
    """An "add" link after a new-element or unrecorded-speaker line."""
    if heading == WORLD_HEADING:
        kind, label = "world", "＋ Add or connect…"
    elif heading == CHARACTER_HEADING:
        kind, label = "character", "＋ Add as a character…"
    else:
        return ""
    key = hashlib.sha1(f"{kind}\n{text}".encode("utf-8")).hexdigest()[:12]
    links = grader.__dict__.setdefault("_canon_links", {})
    links[key] = (kind, text)
    return f" · <a href='addcanon:{key}'>{label}</a>"


def open_from_link(grader, url: str) -> None:
    """The pop-up for a clicked link; on Add, ask the main window to save."""
    kind, text = grader.__dict__.get("_canon_links", {}).get(url.split(":", 1)[1], (None, None))
    if kind is None or grader.project is None:
        return
    dlg = CanonAddDialog(grader.project, kind, text, grader)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        grader.create_canon_requested.emit(dlg.kind(), dlg.data())


def add_from_critique(main_window, kind: str, data: Dict[str, Any]) -> bool:
    """Save through the app's own creators, then fill the extra fields and
    refresh the World and Characters tabs."""
    if kind == "term":
        return _add_term(main_window, data)
    ok = main_window._create_from_plot_ai_suggestion(kind, dict(data))
    name = data.get("name", "")
    if ok:
        record = cc.find_record(main_window.current_project, kind, name)
        if record is not None:
            cc.apply_extras(record, kind, data)
        try:
            main_window._refresh_project_widgets()
        except Exception as e:
            print(f"[canon] could not refresh the tabs: {e}")
        where = "Characters" if kind == "character" else "World"
        main_window.statusBar().showMessage(f"Added “{name}” to {where}.", 6000)
    else:
        main_window.statusBar().showMessage(f"Couldn't add “{name}”.", 6000)
    return ok


def _add_term(main_window, entry: Dict[str, str]) -> bool:
    """A connected term goes in the World's Encyclopedia."""
    project = main_window.current_project
    result = cc.add_term(project, entry)
    name, target = entry.get("title", ""), entry.get("refers_to", "")
    if result:
        main_window._on_content_changed()
        try:
            main_window._refresh_project_widgets()
        except Exception as e:
            print(f"[canon] could not refresh the tabs: {e}")
    message = {"added": f"Connected “{name}” to {target} (World → Encyclopedia).",
               "updated": f"“{name}” was already in the Encyclopedia; filled in what it lacked.",
               "": f"“{name}” is already in the Encyclopedia."}[result]
    main_window.statusBar().showMessage(message, 6000)
    return bool(result) or result == ""

