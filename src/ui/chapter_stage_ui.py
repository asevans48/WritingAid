"""Chapter stages on screen, and from the assistant (piece 3.1).

The scorecard and the Companion's chapter header show each chapter's stage
and let the writer change it: forward or back, one chapter or several. When
every check of the stage passes, both suggest moving on; the writer
decides. The assistant can do the same ("move chapters 3 to 7 to
copyedit"): it says what it will move, the writer confirms, then it moves
them. All of it goes through ``chapter_stages.set_stage``.
"""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, Iterable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QMenu, QMessageBox, QVBoxLayout)

from src.ai import chapter_stages as cst
from src.ai.readiness import STAGES


def confirm(parent, text: str) -> bool:
    """Ask before the assistant moves chapters (patched in tests)."""
    answer = QMessageBox.question(parent, "Move chapters", text,
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.Yes)
    return answer == QMessageBox.StandardButton.Yes


def stage_menu(parent, current: str, on_pick: Callable[[str], None],
               several: Optional[Callable[[], None]] = None) -> QMenu:
    """The stages, the current one ticked; "No stage"; and, when given,
    "Several chapters…"."""
    menu = QMenu(parent)
    for stage in list(STAGES) + [""]:
        act = QAction(cst.label(stage), menu)
        act.setCheckable(True)
        act.setChecked(stage == (current or ""))
        act.triggered.connect(lambda _=False, s=stage: on_pick(s))
        if stage == "":
            menu.addSeparator()
        menu.addAction(act)
    if several is not None:
        menu.addSeparator()
        menu.addAction("Several chapters…").triggered.connect(lambda _=False: several())
    return menu


def show_menu(parent, current: str, on_pick, several=None) -> None:
    stage_menu(parent, current, on_pick, several).exec(QCursor.pos())


class ChaptersDialog(QDialog):
    """Tick chapters, pick a stage: one move for several chapters."""

    def __init__(self, project: Any, scope: Optional[str], chosen: Iterable[str] = (),
                 stage: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set the stage of several chapters")
        now = cst.stages(project, scope)
        lay = QVBoxLayout(self)
        heading = QLabel(f"Chapters of “{html.escape(project.scope_label(scope))}”:")
        heading.setWordWrap(True)          # U.3a: a long novella name wraps, never widens
        heading.setTextFormat(Qt.TextFormat.RichText)   # the name is escaped: show it as typed
        lay.addWidget(heading)
        self.list = QListWidget()
        self.list.setWordWrap(True)        # long chapter names wrap
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chosen = set(chosen)
        ms = next((m for s, m in project.iter_manuscripts() if s == scope), None)
        self.ids: List[str] = []
        for ch in getattr(ms, "chapters", None) or []:
            name = f"{ch.number}. {ch.title}" if getattr(ch, "number", 0) else ch.title
            item = QListWidgetItem(f"{name}  —  {cst.label(now.get(ch.id, ''))}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if ch.id in chosen
                               else Qt.CheckState.Unchecked)
            self.list.addItem(item)
            self.ids.append(ch.id)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Move them to:"))
        self.stage = QComboBox()
        for s in list(STAGES) + [""]:
            self.stage.addItem(cst.label(s), s)
        self.stage.setCurrentIndex(max(0, self.stage.findData(stage or STAGES[0])))
        row.addWidget(self.stage, 1)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Move", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        from src.ui.ui_kit import fit_to_screen
        fit_to_screen(self, 460, 480)

    def chosen(self) -> List[str]:
        return [cid for n, cid in enumerate(self.ids)
                if self.list.item(n).checkState() == Qt.CheckState.Checked]

    def chosen_stage(self) -> str:
        return self.stage.currentData() or ""


def choose_several(parent, project: Any, scope: Optional[str], chosen=(), stage="") -> bool:
    """The dialog, then the move. True when something was moved."""
    dlg = ChaptersDialog(project, scope, chosen, stage, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen():
        return False
    return cst.set_stage(project, scope, dlg.chosen(), dlg.chosen_stage())


# ── For the Companion's header ──────────────────────────────────────

def stored_statuses(project: Any, scope: Optional[str], chapter_id: str) -> Dict[str, str]:
    from src.data import readiness_state as rs
    results = rs.stored_chapter(project, scope, chapter_id).get("results") or {}
    return {n: r.get("status", "") for n, r in results.items() if isinstance(r, dict)}


def header_html(project: Any, chapter: Any) -> str:
    """" · Stage: Line ▾" (a link), and the suggestion when it is earned."""
    if project is None or chapter is None:
        return ""
    try:
        scope, _ch = project.find_chapter_with_scope(chapter.id)
        stage = cst.stage_of(project, scope, chapter.id)
        nxt = cst.suggestion_for(stage, stored_statuses(project, scope, chapter.id))
    except Exception:
        return ""
    out = (f"<span style='color:#6b7280;font-weight:normal;font-size:10px'> · Stage: "
           f"<a href='stage:menu' style='color:#4338ca'>{html.escape(cst.label(stage))} ▾</a>")
    if nxt:
        out += (f" · every {html.escape(cst.label(stage))} check passes: "
                f"<a href='stage:{nxt}' style='color:#4338ca'>move to "
                f"{html.escape(cst.label(nxt))}</a>")
    return out + "</span>"


def on_header_link(parent, project: Any, chapter: Any, href: str,
                   changed: Callable[[], None]) -> None:
    """A click on the header's stage link."""
    if project is None or chapter is None or not href.startswith("stage:"):
        return
    scope, _ch = project.find_chapter_with_scope(chapter.id)
    what = href[6:]

    def pick(stage: str) -> None:
        if cst.set_stage(project, scope, [chapter.id], stage):
            changed()

    def several() -> None:
        if choose_several(parent, project, scope, [chapter.id],
                          cst.stage_of(project, scope, chapter.id)):
            changed()
    if what == "menu":
        show_menu(parent, cst.stage_of(project, scope, chapter.id), pick, several)
    elif what in STAGES:
        pick(what)


# ── For the scorecard ───────────────────────────────────────────────

ROW_NAME = 36                      # characters of a row's name


def row_name(name: str, chapter_report: Any) -> str:
    """A scorecard row's name with its stage: "3. The Harbor · Line"."""
    stage = getattr(chapter_report, "stage", "") or ""
    from src.ai.readiness import BOOK_ROW, OPENING_ROW
    if getattr(chapter_report, "chapter_id", "") in (BOOK_ROW, OPENING_ROW) or not stage:
        return name if len(name) <= ROW_NAME else name[:ROW_NAME - 1] + "…"
    tag = f" · {cst.label(stage)}"
    room = ROW_NAME - len(tag) + 6
    return (name if len(name) <= room else name[:room - 1] + "…") + tag


def install_on_scorecard(sc: Any) -> None:
    """Right-click a chapter's name to change its stage; the issues
    panel's stage links do the same."""
    header = sc.table.verticalHeader()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.customContextMenuRequested.connect(
        lambda pos: _row_menu(sc, header.logicalIndexAt(pos)))
    sc.issues.stage_requested.connect(lambda what: _issues_link(sc, what))


def _move(sc: Any, chapter_report: Any, stage: str) -> None:
    if cst.set_stage(sc.project, chapter_report.scope, [chapter_report.chapter_id], stage):
        apply_stages(sc)


def _several(sc: Any, chapter_report: Any) -> None:
    scope = chapter_report.scope
    if choose_several(sc, sc.project, scope, [chapter_report.chapter_id],
                      cst.stage_of(sc.project, scope, chapter_report.chapter_id)):
        apply_stages(sc)


def _row_menu(sc: Any, row: int) -> None:
    from src.ai.readiness import BOOK_ROW, OPENING_ROW
    ch = sc._row_report(row)
    if ch is None or sc.project is None or ch.chapter_id in (BOOK_ROW, OPENING_ROW):
        return
    show_menu(sc, ch.stage, lambda s: _move(sc, ch, s), lambda: _several(sc, ch))


def _issues_link(sc: Any, what: str) -> None:
    ch = sc._row_report(sc.selected_row())
    if ch is None or sc.project is None:
        return
    if what == "menu":
        show_menu(sc, ch.stage, lambda s: _move(sc, ch, s), lambda: _several(sc, ch))
    elif what in STAGES:
        _move(sc, ch, what)


def apply_stages(sc: Any) -> None:
    """Read the stages back into the shown report(s) and redraw."""
    if sc.project is None:
        return
    for report in [sc.report] + list(getattr(sc, "_reports", {}).values()):
        if report is None:
            continue
        now = cst.stages(sc.project, report.scope)
        for ch in report.chapters:
            ch.stage = now.get(ch.chapter_id, "")
    if sc.report is not None and sc.report.chapters:
        sc._render(sc.report)


# ── The assistant ───────────────────────────────────────────────────

def stages_changed(main_window: Any) -> None:
    """Show the new stages wherever they are on screen."""
    try:
        main_window.grader_widget.scorecard.apply_stages()
    except Exception:
        pass
    try:
        ce = main_window.manuscript_editor.current_chapter_editor
        ce.companion.panel.refresh_stage()
    except Exception:
        pass


def run_chat(main_window: Any, message: str) -> bool:
    """"Move chapters 3 to 7 to copyedit": confirm, then move. False when
    the message isn't such a request after all (it goes to the model)."""
    project = getattr(main_window, "current_project", None)
    chat = main_window.chat_widget
    if project is None:
        return False
    names = [project.scope_label(s) for s, _ in project.iter_manuscripts()]
    req = cst.parse_request(message, names)
    if req is None:
        return False
    current = (None, "")
    ce = getattr(getattr(main_window, "manuscript_editor", None), "current_chapter_editor", None)
    if ce is not None and getattr(ce, "chapter", None) is not None:
        scope, _ch = project.find_chapter_with_scope(ce.chapter.id)
        current = (scope, ce.chapter.id)
    elif getattr(project, "active_subproject_id", None):
        current = (project.active_subproject_id, "")
    scope, chapters, problem = cst.resolve(project, req, current, message)
    if problem:
        reply = problem
    else:
        what = cst.describe(project, scope, chapters, req.stage)
        if not confirm(main_window, f"Move {what}?"):
            reply = "Left as they were; nothing was moved."
        elif cst.set_stage(project, scope, [c.id for c in chapters], req.stage, by="assistant"):
            reply = (f"Moved {what}. You can change any of them by hand in the Critique's "
                     "scorecard or the Companion's header.")
            stages_changed(main_window)
        else:
            reply = "The stages couldn't be saved; nothing was moved."
    chat.add_message("Assistant", reply)
    try:
        main_window._record_chat_turn(message, reply)
    except Exception:
        pass
    return True
