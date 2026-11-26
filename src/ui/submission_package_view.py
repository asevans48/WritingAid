"""The submission package in the Publishing tab (piece 9.3).

Opened from the first entry in the tab's list, "📦 Submission package",
and shown where an agent's details are shown. No new tab, screen or
section: one document picker, one editable draft, one button, and one
More ▾ menu for the rest.

* **Draft** fills in the template from the story (no model), or, with a
  model set up, drafts in the writer's voice. Both are in More ▾ too.
* Every edit is kept as it is typed, in the project's own drafts file
  (``submission_store``), never in the manuscript.
* A new draft never replaces the writer's text silently: the text it
  replaces is kept, and More ▾ › Earlier versions puts any of it back
  (keeping the current text the same way).
* Model work runs on a worker thread (``background.run_background``); its
  result is stored for the document it was asked for, even if the writer
  has moved to another one.
"""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPlainTextEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from src.ai import submission_package as sp
from src.data import submission_store as store
from src.ui import notify, ui_kit
from src.ui.ui_kit import GAP, PALETTE

SOURCES = {"template": "filled in from your plot and story memory",
           "model": "drafted by {model}", "writer": "written by you"}


def ai_available() -> bool:
    from src.ui.scorecard_model_run import ai_available as on
    return on()


def model_draft(kind: str, project: Any, scope: Optional[str], comps: List[str]):
    """Worker-thread work: the writing model's draft (never on the GUI thread)."""
    from src.ai import word_suggest
    llm = word_suggest.get_llm()
    if llm is None:
        raise RuntimeError("no model is set up")
    return sp.draft(llm, kind, project, scope, comps)


class PackageView(QWidget):
    """The package for one project: pick a document, edit it, draft, export."""

    SAVE_AFTER_MS = 700

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Any = None
        self.scope: Optional[str] = None
        self.kind = sp.DOCS[0]
        self._loading = True                 # until built: no signal reaches the store
        self._busy = False
        self._task = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.SAVE_AFTER_MS)
        self._timer.timeout.connect(self.flush)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(ui_kit.PANEL_MARGIN, ui_kit.PANEL_MARGIN,
                                 ui_kit.PANEL_MARGIN, ui_kit.PANEL_MARGIN)
        outer.setSpacing(GAP)

        top = QHBoxLayout()
        title = QLabel("Submission package")
        title.setStyleSheet(ui_kit.text_style("ink", 14, bold=True))
        top.addWidget(title)
        self.doc_pick = QComboBox()
        for k in sp.DOCS:
            self.doc_pick.addItem(sp.LABELS[k], k)
        self.doc_pick.setToolTip("Which document to show")
        self.doc_pick.currentIndexChanged.connect(self._doc_changed)
        top.addWidget(self.doc_pick)
        self.scope_pick = QComboBox()
        self.scope_pick.setToolTip("Which manuscript: each has its own package")
        self.scope_pick.currentIndexChanged.connect(self._scope_changed)
        top.addWidget(self.scope_pick)
        top.addStretch(1)
        outer.addLayout(top)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(ui_kit.text_style("ink_faint"))
        outer.addWidget(self.status)

        # Readers and comps: candidates from the genre list, ticked by the writer.
        self.comps_box = QWidget()
        cb = QVBoxLayout(self.comps_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(GAP)
        honest = QLabel(sp.COMPS_HONESTY)
        honest.setWordWrap(True)
        honest.setStyleSheet(ui_kit.text_style("ink_soft"))
        cb.addWidget(honest)
        self.comp_list = QListWidget()
        rows = self.comp_list.fontMetrics().lineSpacing() + 6
        self.comp_list.setMaximumHeight(rows * 5 + 8)       # five rows, scales with the text
        self.comp_list.itemChanged.connect(lambda *_: self._save_comps())
        cb.addWidget(self.comp_list)
        self.no_genre = QLabel("Set the book's genre in Prose Profile to see candidates "
                               "from the genre list.")
        self.no_genre.setWordWrap(True)
        self.no_genre.setStyleSheet(ui_kit.text_style("ink_faint", italic=True))
        cb.addWidget(self.no_genre)
        self.own_comps = QLineEdit()
        self.own_comps.setPlaceholderText("Your own comparable titles: Title — Author; Title — Author")
        self.own_comps.textChanged.connect(lambda *_: self._save_comps())
        cb.addWidget(self.own_comps)
        outer.addWidget(self.comps_box)

        self.editor = QPlainTextEdit()
        self.editor.setTabChangesFocus(True)
        lines = self.editor.fontMetrics().lineSpacing()
        self.editor.setMinimumHeight(lines * 8)
        # A comfortable line length on a wide screen (rule 12), scaled with the text.
        self.editor.setMaximumWidth(self.editor.fontMetrics().horizontalAdvance("x") * 110)
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor.textChanged.connect(self._edited)
        outer.addWidget(self.editor, 1)

        row = QHBoxLayout()
        self.draft_btn = QPushButton("✍ Draft")
        self.draft_btn.clicked.connect(self.draft)
        row.addWidget(self.draft_btn)
        self.more_btn = QToolButton()
        self.more_btn.setText("More ▾")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        ui_kit.plain(self.more_btn, size=12, pad="6px 12px")
        self.menu = QMenu(self.more_btn)
        self.act_template = self.menu.addAction("Fill in from the story (no model)",
                                                lambda: self.draft(use_model=False))
        self.act_model = self.menu.addAction("Draft in my voice with the model",
                                             lambda: self.draft(use_model=True))
        self.menu.addSeparator()
        self.menu.addAction("Export this document…", lambda: self.export(everything=False))
        self.menu.addAction("Export the whole package…", lambda: self.export(everything=True))
        self.menu.addSeparator()
        self.versions_menu = self.menu.addMenu("Earlier versions")
        self.versions_menu.aboutToShow.connect(self._fill_versions)
        self.menu.aboutToShow.connect(self._menu_state)
        self.more_btn.setMenu(self.menu)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        outer.addLayout(row)
        self.comps_box.setVisible(False)
        self._loading = False

    # ── Project and choices ──────────────────────────────────────────

    def set_project(self, project: Any) -> None:
        self.flush()
        self.project = project
        self._loading = True
        self.scope_pick.clear()
        if project is not None:
            from src.data import publishing_goal as pg
            for scope, name, _ms in pg.manuscripts(project):
                self.scope_pick.addItem(name, scope)
        self.scope_pick.setVisible(self.scope_pick.count() > 1)
        self.scope = self.scope_pick.currentData() if self.scope_pick.count() else None
        self._loading = False
        self.show_document(self.kind)

    def show_document(self, kind: str) -> None:
        """Show one document; an empty one is filled in from the story."""
        self.flush()
        self.kind = kind
        i = self.doc_pick.findData(kind)
        if i >= 0 and self.doc_pick.currentIndex() != i:
            self._loading = True
            self.doc_pick.setCurrentIndex(i)
            self._loading = False
        self.comps_box.setVisible(kind == "audience")
        if kind == "audience":
            self._load_comps()
        self._load_text()
        self._label_buttons()
        self._fill_if_empty()

    def _fill_if_empty(self) -> None:
        """An empty document is filled in from the story (no model)."""
        if self.project is not None and not self.editor.toPlainText().strip() and not self._busy:
            self.draft(use_model=False)

    def _doc_changed(self, _i: int) -> None:
        if not self._loading:
            self.show_document(self.doc_pick.currentData())

    def _scope_changed(self, _i: int) -> None:
        if self._loading:
            return
        self.flush()
        self.scope = self.scope_pick.currentData()
        self.show_document(self.kind)

    def _load_text(self) -> None:
        entry = store.document(self.project, self.scope, self.kind) if self.project else {}
        self._loading = True
        self.editor.setPlainText(entry.get("text") or "")
        self._loading = False
        self._show_status(entry)

    def _show_status(self, entry: dict, extra: str = "") -> None:
        if self.project is None:
            self.status.setText("Open a project to prepare its submission package.")
            return
        src = entry.get("source") or ""
        made = SOURCES.get(src, "").format(model=entry.get("model") or "the model")
        bits = []
        if made:
            bits.append(f"{sp.LABELS[self.kind]} {made}" + (f", {entry['made_at']}"
                                                            if entry.get("made_at") else ""))
        if store.is_edited(entry) and src != "writer":
            bits.append("edited by you")
        if isinstance(entry.get("fit"), (int, float)):
            bits.append(f"voice fit {round(entry['fit'] * 100)}% (rough)")
        n = len(entry.get("versions") or [])
        if n:
            bits.append(f"{n} earlier version{'s' if n != 1 else ''} kept")
        text = " · ".join(bits) or sp.LABELS[self.kind]
        text += f". Kept in {store.where(self.project)}."
        if extra:
            text = f"{extra} {text}"
        self.status.setText(text)

    def _label_buttons(self) -> None:
        with_model = ai_available()
        self.draft_btn.setText("✍ Draft in my voice" if with_model else "✍ Fill in from the story")
        self.draft_btn.setToolTip(
            "Ask the model for a draft in your voice, from your plot, characters and story "
            "memory. Your current text is kept as an earlier version." if with_model else
            "Fill in the template from your plot, characters and story memory. Your current "
            "text is kept as an earlier version.")

    def showEvent(self, event):
        try:
            self._label_buttons()            # a model set up in Settings since
        except Exception as e:               # an exception escaping a Qt event aborts the app
            print(f"[submission] {e}")
        super().showEvent(event)

    def hideEvent(self, event):
        try:
            self.flush()
        except Exception as e:               # also called while the widget is torn down
            print(f"[submission] {e}")
        super().hideEvent(event)

    # ── Comparable titles ────────────────────────────────────────────

    def _load_comps(self) -> None:
        self._loading = True
        self.comp_list.clear()
        saved = store.comps(self.project, self.scope) if self.project else {"chosen": [], "own": ""}
        candidates = sp.comp_candidates(self.project) if self.project else []
        for c in candidates + [c for c in saved["chosen"] if c not in candidates]:
            item = QListWidgetItem(c)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c in saved["chosen"]
                               else Qt.CheckState.Unchecked)
            self.comp_list.addItem(item)
        self.comp_list.setVisible(self.comp_list.count() > 0)
        self.no_genre.setVisible(self.comp_list.count() == 0)
        self.own_comps.setText(saved["own"])
        self._loading = False

    def ticked(self) -> List[str]:
        return [self.comp_list.item(i).text() for i in range(self.comp_list.count())
                if self.comp_list.item(i).checkState() == Qt.CheckState.Checked]

    def _save_comps(self) -> None:
        if self._loading or self.project is None:
            return
        store.set_comps(self.project, self.scope, self.ticked(), self.own_comps.text())

    def comps(self) -> List[str]:
        saved = store.comps(self.project, self.scope) if self.project else {"chosen": [], "own": ""}
        return sp.chosen_comps(saved["chosen"], saved["own"])

    # ── Editing ──────────────────────────────────────────────────────

    def _edited(self) -> None:
        if not self._loading:
            self._timer.start()

    def flush(self) -> None:
        """Store the writer's text now, if it changed."""
        self._timer.stop()
        if self.project is None or self._loading:
            return
        typed = self.editor.toPlainText()
        if typed != store.text(self.project, self.scope, self.kind):
            store.set_text(self.project, self.scope, self.kind, typed)

    # ── Drafting ─────────────────────────────────────────────────────

    def _menu_state(self) -> None:
        self.act_model.setEnabled(ai_available() and not self._busy)
        self.act_template.setEnabled(not self._busy)

    def draft(self, use_model: Optional[bool] = None) -> None:
        """A new draft of the document shown: the template, or the model's."""
        if self.project is None or self._busy:
            return
        self.flush()
        if use_model is None:
            use_model = ai_available()
        project, scope, kind, comps = self.project, self.scope, self.kind, self.comps()
        self._set_busy(True, "Drafting with the model…" if use_model else "Filling in…")

        def work():
            if use_model:
                return model_draft(kind, project, scope, comps)
            return {"text": sp.template(kind, project, scope, chosen_comps=comps),
                    "model": "", "fit": None}

        def done(result, error):
            self._set_busy(False)
            if error or not result:
                same = self.project is project and self.scope == scope and self.kind == kind
                if self.project is not None:
                    self._show_status(
                        store.document(self.project, self.scope, self.kind),
                        f"Couldn't make the draft ({error or 'no reply'}); your text is "
                        "unchanged." if same else "")
            else:
                self.land(project, scope, kind, result, "model" if use_model else "template")
            if use_model or (result and not error):
                self._fill_if_empty()      # a document opened while this one was drafting

        from src.ui.background import run_background
        self._task = run_background(work, done, owner=self, label="submission")

    def land(self, project: Any, scope: Optional[str], kind: str, result: dict,
             source: str) -> None:
        """Store a finished draft for the document it was asked for; show
        it only if that document is still on screen."""
        if self.project is project and self.scope == scope and self.kind == kind:
            self.flush()                     # the writer's latest typing is kept first
        got = store.put_draft(project, scope, kind, result["text"], source,
                              model=result.get("model", ""), fit=result.get("fit"))
        if not (self.project is project and self.scope == scope and self.kind == kind):
            if self.project is not None:      # the busy message gives way to the shown document's
                self._show_status(store.document(self.project, self.scope, self.kind))
            return
        self._load_text()
        if got["kept"]:
            self._show_status(store.document(project, scope, kind),
                              "New draft. Your earlier text is kept: More ▾ › Earlier versions.")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.draft_btn.setEnabled(not busy)
        if busy:
            self.status.setText(message)

    # ── Earlier versions ─────────────────────────────────────────────

    def _fill_versions(self) -> None:
        self.versions_menu.clear()
        versions = store.document(self.project, self.scope, self.kind).get("versions") \
            if self.project else []
        if not versions:
            a = self.versions_menu.addAction("None yet")
            a.setEnabled(False)
            return
        for i in reversed(range(len(versions))):
            v = versions[i]
            words = " ".join((v.get("text") or "").split()[:8])
            who = {"writer": "yours", "model": "model", "template": "template"}.get(
                v.get("source", ""), v.get("source", ""))
            self.versions_menu.addAction(f"{v.get('saved_at', '')} · {who} · {words}…",
                                         lambda i=i: self.restore(i))

    def restore(self, index: int) -> None:
        self.flush()
        if store.restore(self.project, self.scope, self.kind, index) is not None:
            self._load_text()
            self._show_status(store.document(self.project, self.scope, self.kind),
                              "Earlier version back; the text it replaced is kept too.")

    # ── Export ───────────────────────────────────────────────────────

    def export(self, everything: bool = False, path: str = "", fmt: str = "") -> bool:
        if self.project is None:
            return False
        self.flush()
        kinds = sp.DOCS if everything else (self.kind,)
        texts = {k: store.text(self.project, self.scope, k) for k in kinds}
        if not any(t.strip() for t in texts.values()):
            notify.empty(self, "Export", "Nothing to export yet: fill in a document first.")
            return False
        if not path:
            name = "Submission package" if everything else sp.LABELS[self.kind]
            filters = ";;".join(sp.EXPORT_FORMATS.values())
            path, chosen = QFileDialog.getSaveFileName(self, f"Export {name.lower()}",
                                                       f"{name}.docx", filters)
            if not path:
                return False
            fmt = next((k for k, v in sp.EXPORT_FORMATS.items() if v == chosen), "")
        fmt = fmt or (path.rsplit(".", 1)[-1].lower() if "." in path else "docx")
        if fmt not in sp.EXPORT_FORMATS:
            fmt = "docx"
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        ok = sp.export(self.project, self.scope, texts, path, fmt)
        if ok:
            notify.done(self, "Exported", f"Saved to {path}", path=path)
        else:
            notify.notice(self, "Export", "The export failed; nothing was changed.")
        return ok


def show_in(manager: Any, wanted: bool) -> bool:
    """Show the package in the Publishing tab's details area (``wanted``),
    or put it away, kept for next time, when an agent is chosen instead.
    Returns ``wanted``. The caller has already saved the agent shown."""
    area = manager.details_scroll
    view = manager.package_view
    if wanted:
        if view is None:
            view = manager.package_view = PackageView()
            view.set_project(manager.project)
        manager.current_agent_widget = None     # replaced (and deleted) below
        if area.widget() is not view:
            area.setWidget(view)
        view.show()
        # Room for the drafts: the page scrolls on a small screen instead.
        area.setMinimumHeight(view.fontMetrics().lineSpacing() * 24)
        return True
    if view is not None and area.widget() is view:
        view.flush()
        area.takeWidget()
        view.hide()
        view.setParent(manager)                 # kept, hidden, for next time
        area.setMinimumHeight(0)
    return False
