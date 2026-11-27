"""Scene markers on screen (piece 7.4): the outline's links, Write's
margin line and its right-click entry.

The markers themselves (storage, anchoring, Undo) are
``src/data/scene_marks``. Nothing here changes the chapter's text.

* **In the Critique's Scene outline ▸** (7.1's section, opened): a ✕ after
  each scene a marker starts; "Use the model's scenes", which shows the
  paragraphs 7.2's reading starts a scene at and marks them when the
  writer confirms; one line for a marker whose paragraph is gone; and,
  after each change, "… · Undo" (Ctrl+Z in the outline does the same).
  Links inside the existing section: no new button, section or window.
* **On Write:** a thin dashed line across the gap above each marked
  paragraph, "Scene 2" etc. on hover. It is drawn over the editor's
  viewport by a see-through widget, so it is never in the document:
  copying, word counts, grammar checks and saving don't see it.
* **Write's right-click:** "Scene break here" / "Remove scene break" in
  More ▸ 📝 Note or scene break ▸, beside Add Annotation (both are marks
  kept beside the text, at a line). After a change the status bar says
  so, with Undo.
* **Write's Insert tab** (D.13): the same entry as a button, for the
  paragraph the text cursor is in (``at_cursor``, ``toggle_at_cursor``).
"""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import QMainWindow, QPushButton, QStatusBar, QToolTip, QWidget

from src.ui.ui_kit import PALETTE

NOTE_MENU = "📝 Note or scene break"
ADD = "Scene break here"
REMOVE = "Remove scene break"
NOTICE_MS = 30000
REFRESH_MS = 1500


def _e(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _sm():
    from src.data import scene_marks
    return scene_marks


# ── The outline (Critique) ────────────────────────────────────────────

def _project(issues: Any) -> Any:
    from src.ui import plan_section
    return plan_section._project(issues)


def offsets(issues: Any, chapter_report: Any, text: str) -> List[int]:
    """The chapter's markers, for ``reverse_outline.outline``."""
    project = _project(issues)
    return _sm().offsets(project, chapter_report.chapter_id, text,
                         getattr(chapter_report, "scope", None)) if project is not None else []


def _resolved(issues: Any, chapter_report: Any, text: str):
    project = _project(issues)
    if project is None:
        return None
    return _sm().for_text(project, chapter_report.chapter_id, text,
                          getattr(chapter_report, "scope", None))


def row_html(issues: Any, chapter_report: Any, text: str, scene: Any, resolved=None) -> str:
    """" · marked ✕" after a scene that a marker starts, or ""."""
    resolved = resolved if resolved is not None else _resolved(issues, chapter_report, text)
    if resolved is None:
        return ""
    for f in resolved.found:
        if f.para > 0 and f.offset <= scene.start and not text[f.offset:scene.start].strip():
            return (f" <span style='color:{PALETTE['ink_faint']}'>· marked</span> "
                    f"<a href='{issues._link('marks', ('remove', f.para))}' "
                    f"title='Remove this scene marker (your text is not changed)'>✕</a>")
    return ""


def after_html(issues: Any, chapter_report: Any, text: str, has_reading: bool,
               resolved=None) -> str:
    """Below the scenes: a lost marker, the model's scenes, and Undo."""
    project = _project(issues)
    if project is None:
        return ""
    sm = _sm()
    cid, scope = chapter_report.chapter_id, getattr(chapter_report, "scope", None)
    resolved = resolved if resolved is not None else sm.for_text(project, cid, text, scope)
    faint, soft = PALETTE["ink_faint"], PALETTE["ink_soft"]
    parts = []
    if resolved.lost:
        n = len(resolved.lost)
        first = _e(resolved.lost[0].get("w", ""))
        parts.append(f"<div style='color:{faint}'>{'A scene marker was' if n == 1 else f'{n} scene markers were'}"
                     f" left out: {'its paragraph' if n == 1 else 'their paragraphs'} "
                     f"(“{first}…”{'' if n == 1 else ' …'}) "
                     f"{'is' if n == 1 else 'are'} no longer in the chapter. "
                     f"<a href='{issues._link('marks', ('forget',))}'>Forget</a></div>")
    if has_reading:
        proposal = sm.from_model(project, cid, text, scope)
        if getattr(issues, "scene_preview", None) == cid and proposal:
            rows = "".join(f"<li>“{_e(w)}…”</li>" for _p, w in proposal)
            parts.append(f"<div style='color:{soft}'>The model's reading starts a scene at "
                         f"{'this paragraph' if len(proposal) == 1 else 'these paragraphs'}. "
                         f"Marking {'it' if len(proposal) == 1 else 'them'} changes nothing in "
                         "your text:</div>"
                         f"<ul style='margin-top:2px'>{rows}</ul><div>"
                         f"<a href='{issues._link('marks', ('confirm',))}'>Mark "
                         f"{'it' if len(proposal) == 1 else f'these {len(proposal)}'}</a> · "
                         f"<a href='{issues._link('marks', ('cancel',))}'>Cancel</a></div>")
        elif proposal:
            parts.append(f"<div style='color:{soft}'><a href='{issues._link('marks', ('model',))}'>"
                         f"Use the model's scenes</a> <span style='color:{faint}'>(marks "
                         f"{len(proposal)} more scene{'s' if len(proposal) != 1 else ''} "
                         "beside the text, shown first)</span></div>")
    notice = getattr(issues, "scene_notice", None)
    if notice and sm.last_change(project) is not None:
        parts.append(f"<div style='color:{soft}'>{_e(notice)} · "
                     f"<a href='{issues._link('marks', ('undo',))}'>Undo</a></div>")
    return "".join(parts)


def _redraw(issues: Any) -> None:
    if getattr(issues, "_shown", None):
        issues.show_chapter(*issues._shown)


def on_link(issues: Any, item: Any) -> None:
    """A marker link in the outline (``readiness_issues`` kind "marks")."""
    try:
        shown = getattr(issues, "_shown", None)
        project = _project(issues)
        if not shown or project is None or not shown[2]:
            return
        ch, text = shown[0], shown[2]
        cid, scope = ch.chapter_id, getattr(ch, "scope", None)
        sm = _sm()
        what = item[0]
        said = None
        if what == "remove" and sm.remove(project, cid, text, item[1], scope):
            said = "Scene marker removed"
        elif what == "forget" and sm.forget_lost(project, cid, text, scope):
            said = "Lost scene markers forgotten"
        elif what == "model":
            issues.scene_preview = cid
        elif what == "cancel":
            issues.scene_preview = None
        elif what == "confirm":
            issues.scene_preview = None
            paras = [p for p, _w in sm.from_model(project, cid, text, scope)]
            n = sm.add(project, cid, text, paras, scope, "The model's scenes marked")
            if n:
                said = f"{n} scene{'s' if n != 1 else ''} marked from the model's reading"
        elif what == "undo":
            undo(issues)
            return
        if said:
            issues.scene_notice = said
            announce(issues, said, lambda: undo(issues))
        _redraw(issues)
    except Exception as e:                       # never out of a Qt slot
        print(f"[scene marks] {e}")


def undo(issues: Any) -> bool:
    """Undo the last marker change (the outline's Undo and Ctrl+Z)."""
    project = _project(issues)
    if project is None or _sm().undo_last(project) is None:
        return False
    issues.scene_notice = None
    announce(issues, "Scene markers put back", None)
    _redraw(issues)
    return True


def install_outline(scorecard: Any) -> None:
    """The chart's markers, and Ctrl+Z in the issue list."""
    from src.ai import plan_match

    def source(chapter_id: str, text: str) -> List[int]:
        project = getattr(scorecard, "project", None)
        report = getattr(scorecard, "report", None)
        return _sm().offsets(project, chapter_id, text,
                             getattr(report, "scope", None)) if project is not None else []
    plan_match.set_marks_source(source)
    issues = scorecard.issues
    if getattr(issues, "_scene_undo_key", None) is None:
        issues._scene_undo_key = _UndoKey(issues)
        issues.installEventFilter(issues._scene_undo_key)


class _UndoKey(QObject):
    """Ctrl+Z in the outline's issue list undoes the last marker change
    (taken before any window-wide shortcut, only when there is one)."""

    def __init__(self, issues: Any):
        super().__init__(issues)
        self.issues = issues

    def _wanted(self, event) -> bool:
        try:
            return (event.matches(QKeySequence.StandardKey.Undo)
                    and _sm().last_change(_project(self.issues)) is not None)
        except Exception:
            return False

    def eventFilter(self, obj: QObject, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.ShortcutOverride and self._wanted(event):
            event.accept()
            return True
        if kind == QEvent.Type.KeyPress and self._wanted(event):
            undo(self.issues)
            return True
        return False


# ── The status line ───────────────────────────────────────────────────

def announce(widget: Any, text: str, undo_fn) -> None:
    """"… · Undo" on the window's status bar, as D.10's moves do; nothing
    when the window has none (the outline shows its own Undo)."""
    try:
        win = widget.window()
        if not isinstance(win, QMainWindow) or win.findChild(QStatusBar) is None:
            return
        bar = win.statusBar()
        btn = getattr(win, "_scene_undo_btn", None)
        if btn is None:
            btn = QPushButton("Undo")
            btn.setFlat(True)
            btn.setStyleSheet("QPushButton { text-decoration: underline; padding: 0 6px; }")
            bar.addPermanentWidget(btn)
            win._scene_undo_btn = btn
            bar.messageChanged.connect(
                lambda m, w=win, b=btn: b.setVisible(bool(m) and m == getattr(w, "_scene_undo_text", None)))
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        if undo_fn is not None:
            btn.clicked.connect(lambda _=False: undo_fn())
        win._scene_undo_text = text if undo_fn is not None else None
        bar.showMessage(text, NOTICE_MS)
        btn.setVisible(undo_fn is not None)
    except Exception as e:
        print(f"[scene marks] {e}")


# ── Write: the margin line ────────────────────────────────────────────

def _chapter_place(ce: Any):
    """(project, chapter id, scope) of the chapter in a ChapterEditor."""
    project = getattr(ce, "project", None)
    chapter = getattr(ce, "chapter", None)
    if project is None or chapter is None:
        return None
    cid = getattr(chapter, "id", "")
    return project, cid, _sm().scope_of(project, cid, chapter)


class SceneMarkLayer(QWidget):
    """A see-through layer over the editor's viewport that draws a dashed
    line above each marked paragraph. Not part of the document."""

    def __init__(self, ce: Any):
        super().__init__(ce.editor.viewport())
        self.ce = ce
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("scene_mark_layer")
        self._key = None
        self._lines: List[tuple] = []          # (block number, scene number)
        vp = ce.editor.viewport()
        self.setGeometry(vp.rect())
        vp.installEventFilter(self)
        ed = ce.editor
        ed.verticalScrollBar().valueChanged.connect(self.update)
        ed.textChanged.connect(self.update)
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(REFRESH_MS)
        self._refresh.timeout.connect(self.refresh_anchors)
        ed.textChanged.connect(self._refresh.start)
        self.raise_()

    def marks(self) -> List[tuple]:
        """[(block number, scene number)] for the text as it is now."""
        place = _chapter_place(self.ce)
        if place is None:
            return []
        project, cid, scope = place
        doc = self.ce.editor.document()
        sm = _sm()
        try:
            from src.data import readiness_state as rs
            path = rs.read_path(project)
            stamp = path.stat().st_mtime_ns if path.exists() else 0
        except Exception:
            stamp = 0
        key = (cid, scope, doc.revision(), stamp)
        if key == self._key:
            return self._lines
        self._key = key
        text = self.ce.editor.toPlainText()
        found = [f for f in sm.for_text(project, cid, text, scope).found if f.para > 0]
        lines = []
        if found:
            from src.ai.reverse_outline import split_scenes
            starts = [s for s, _e in split_scenes(text, [f.offset for f in found])]
            for f in found:
                number = next((i for i, s in enumerate(starts, 1) if s == f.offset), None)
                if number:
                    lines.append((f.line, number))
        self._lines = lines
        return lines

    def line_y(self, block_number: int) -> Optional[int]:
        """Where the dashed line goes in the viewport: in the gap above the paragraph."""
        ed = self.ce.editor
        doc = ed.document()
        block = doc.findBlockByNumber(block_number)
        if not block.isValid():
            return None
        layout = doc.documentLayout()
        top = layout.blockBoundingRect(block).top()
        prev = block.previous()
        if prev.isValid() and not prev.text().strip():
            r = layout.blockBoundingRect(prev)
            top = r.top() + r.height() / 2
        else:
            top -= 1
        return int(top - ed.verticalScrollBar().value())

    def paintEvent(self, event) -> None:
        try:
            lines = self.marks()
            if not lines:
                return
            p = QPainter(self)
            pen = QPen(QColor(PALETTE["primary"]))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            p.setPen(pen)
            margin = int(self.ce.editor.document().documentMargin())
            for block, _n in lines:
                y = self.line_y(block)
                if y is not None and -2 <= y <= self.height() + 2:
                    p.drawLine(margin, y, self.width() - margin, y)
            p.end()
        except Exception as e:
            print(f"[scene marks] {e}")

    def scene_at(self, y: int) -> Optional[int]:
        for block, n in self.marks():
            ly = self.line_y(block)
            if ly is not None and abs(ly - y) <= 4:
                return n
        return None

    def eventFilter(self, obj: QObject, event) -> bool:
        try:
            if event.type() == QEvent.Type.Resize:
                self.setGeometry(obj.rect())
            elif event.type() == QEvent.Type.ToolTip:
                n = self.scene_at(event.pos().y())
                if n is not None:
                    QToolTip.showText(event.globalPos(), f"Scene {n} (a marker kept beside "
                                      "the text)", obj)
                    return True
        except Exception as e:
            print(f"[scene marks] {e}")
        return False

    def refresh_anchors(self) -> None:
        """After an edit: each marker's place and opening words follow its paragraph."""
        place = _chapter_place(self.ce)
        if place is None:
            return
        project, cid, scope = place
        try:
            _sm().refresh(project, cid, self.ce.editor.toPlainText(), scope)
        except Exception as e:
            print(f"[scene marks] {e}")


def install(ce: Any) -> Optional[SceneMarkLayer]:
    """The call line for ``ChapterEditor._init_ui``."""
    try:
        ce.scene_mark_layer = SceneMarkLayer(ce)
        return ce.scene_mark_layer
    except Exception as e:
        print(f"[scene marks] margin line unavailable: {e}")
        return None


# ── Write: the right-click entry ──────────────────────────────────────

def add_to_menu(ce: Any, menu: Any, position: QPoint) -> None:
    """"Scene break here" or "Remove scene break" for the paragraph
    right-clicked (in ``menu``: More ▸ 📝 Note or scene break ▸)."""
    place = _chapter_place(ce)
    if place is None:
        return
    project, cid, scope = place
    sm = _sm()
    text = ce.editor.toPlainText()
    para = sm.para_at_line(text, ce.editor.cursorForPosition(position).blockNumber())
    if para is None:
        return
    menu.addSeparator()
    if sm.marked_at(project, cid, text, para, scope) is not None:
        menu.addAction(REMOVE).triggered.connect(lambda _=False: _change(ce, para, False))
        return
    act = menu.addAction(ADD)
    act.setToolTip("Mark a new scene at this paragraph. The mark is kept beside the text; "
                   "your text is not changed.")
    if para == 0:
        act.setEnabled(False)
        act.setToolTip("The chapter's first paragraph already starts a scene.")
    act.triggered.connect(lambda _=False: _change(ce, para, True))


def at_cursor(ce: Any):
    """(paragraph, marked) for the paragraph the text cursor is in, or None
    (no chapter, a blank line): Write's Insert tab (D.13)."""
    place = _chapter_place(ce)
    if place is None:
        return None
    project, cid, scope = place
    sm = _sm()
    text = ce.editor.toPlainText()
    para = sm.para_at_line(text, ce.editor.textCursor().blockNumber())
    if para is None:
        return None
    return para, sm.marked_at(project, cid, text, para, scope) is not None


def toggle_at_cursor(ce: Any) -> bool:
    """Scene break here, or Remove scene break, at the text cursor (the
    Insert tab's button; the same change as the right-click entry)."""
    state = at_cursor(ce)
    if state is None or (state[0] == 0 and not state[1]):
        return False
    _change(ce, state[0], not state[1])
    return True


def _change(ce: Any, para: int, add: bool) -> None:
    try:
        place = _chapter_place(ce)
        if place is None:
            return
        project, cid, scope = place
        sm = _sm()
        text = ce.editor.toPlainText()
        ok = (sm.add(project, cid, text, [para], scope) if add
              else sm.remove(project, cid, text, para, scope))
        if ok:
            announce(ce, "Scene break marked" if add else "Scene break removed",
                     lambda: undo_write(ce))
        layer = getattr(ce, "scene_mark_layer", None)
        if layer is not None:
            layer._key = None
            layer.update()
    except Exception as e:                       # never out of a Qt slot
        print(f"[scene marks] {e}")


def undo_write(ce: Any) -> bool:
    """The status bar's Undo after a change on Write."""
    place = _chapter_place(ce)
    if place is None or _sm().undo_last(place[0]) is None:
        return False
    announce(ce, "Scene markers put back", None)
    layer = getattr(ce, "scene_mark_layer", None)
    if layer is not None:
        layer._key = None
        layer.update()
    return True
