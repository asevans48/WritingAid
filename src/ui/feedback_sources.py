"""One Feedback tab (piece D.13c): feedback from the app's other places.

Under the writer's own feedback (+ Feedback, Analyze: unchanged and first),
the side panel's Feedback tab lists, for the open chapter, what three other
places have said about it, read-only, each under a small heading that folds
(with its count) and each item naming where it came from:

* **From the Companion:** "Notes as you write" (the notes the Companion
  shows now) and the last Reader's eye report (this session). Read from
  the Companion itself (``CompanionPanel.notes``, ``reader_report``).
* **From the Critique:** the readiness checks' findings for this chapter
  (needing work or a problem; read from the project's readiness file,
  ``readiness_state``), and the Critique's reports, the newest of each kind
  (read from ``critique_history``).
* **From the Improve window:** what each Improve window opened on a
  passage of this chapter said (its critique and its versions), kept for
  the project when the window closes (D.14b: appended to
  ``<project>.improve_notes.json``, ``src/data/improve_notes.py``; in
  memory for the session only if that file cannot be written), and the
  rated versions saved for this project when data collection is on (read
  from ``rephrase_database``, opened read-only), each while its passage or
  the accepted words are still in the chapter. An Improve item can be
  dismissed here (**Dismiss**): hidden, and kept in the file as dismissed.

Newest first within a heading where a time is known; the Companion's notes
are in its own order (by paragraph). Each item has **Go to** (the passage,
where there is one) and **Open in …** (its source). Nothing is moved out of
the Companion, the Critique or the Improve window (rule 11): this is one
more place to read them. Dismissing in the source hides it here too (the
Companion's notes are read live; the Critique's dismissed findings are
left out). Reading writes nothing: the files are read directly, never
through a loader that could set a damaged file aside. Written: which
headings are folded (with the window settings), the Improve window's notes
when it closes, and an Improve item's Dismiss.
"""

from __future__ import annotations

import html
import json
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.ui.ui_kit import PALETTE, CollapsibleSection, text_style

# The words for the writer (decision 18: one place, so F.1 can change them).
CHAPTER = "chapter"
COMPANION, CRITIQUE, IMPROVE = SOURCES = ("companion", "critique", "improve")
TITLES = {COMPANION: "From the Companion", CRITIQUE: "From the Critique",
          IMPROVE: "From the Improve window"}
OPEN_WORDS = {COMPANION: "Open in the Companion", CRITIQUE: "Open in the Critique",
              IMPROVE: "Open in Improve"}
EMPTY = {
    COMPANION: f"Nothing yet. The Companion's notes appear as you write; Reader's eye "
               f"shows here once you run it on this {CHAPTER}.",
    CRITIQUE: f"Nothing yet for this {CHAPTER}. Revise ▸ Critique checks it and keeps its "
              "reports.",
    IMPROVE: "Nothing yet. What ✨ Improve says about a passage here is kept with the project "
             f"and shows while the passage is in the {CHAPTER} (and the versions you rate, "
             "when data collection is on).",
}
DISMISS = "Dismiss"               # an Improve item: hidden, kept in the file (D.14b)
CLOSED_KEY = "feedback/sources_closed"
MAX_SHOWN = 30                    # per heading; the rest are counted, in their source
SHOWN_STATUSES = ("needs_work", "problem")


@dataclass
class Item:
    source: str                   # COMPANION | CRITIQUE | IMPROVE
    kind: str                     # where in it: "Notes as you write", a check's name …
    text: str                     # what it says
    passage: str = ""             # the chapter's words it is about ("" when none)
    offset: int = -1              # where they were, when known (Python index)
    when: str = ""                # ISO time, when known (newest first)
    ref: Any = None               # what "Open in …" opens
    dismiss: Any = None           # how to hide it (an Improve note's item; D.14b)


# ── Reading (nothing is written) ───────────────────────────────────────

def _read_json(path: Optional[Path]) -> Dict[str, Any]:
    try:
        if path is None or not Path(path).is_file():
            return {}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                            # unreadable: nothing to show
        return {}


def _readiness_data(project: Any) -> Dict[str, Any]:
    from src.data import readiness_state as rs
    return _read_json(rs.read_path(project))


def _history_data(project: Any) -> Dict[str, Any]:
    from src.data import critique_history as chist
    return _read_json(chist.history_path(project))


def _db_path() -> Optional[Path]:
    try:
        from src.data import rephrase_database as rdb
        inst = getattr(rdb, "_instance", None)
        return Path(getattr(inst, "db_path", None) or rdb.DEFAULT_DB_PATH)
    except Exception:
        return None


def _db_rows(project: Any) -> List[Dict[str, Any]]:
    """Rated versions saved for this project (data collection on), newest
    first. Opened read-only; a missing database means none."""
    path = _db_path()
    project_path = str(getattr(project, "project_path", "") or "")
    if path is None or not path.is_file() or not project_path:
        return []
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT created_at, source_text, output_text, style, rating, accepted "
                "FROM rephrases WHERE project_path = ? AND source_type = 'rephrase' "
                "ORDER BY created_at DESC LIMIT 400", (project_path,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception as e:
        print(f"[feedback] ratings not read: {e}")
        return []


def _short(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def when_words(iso: str) -> str:
    """"today 14:05" or "24 Nov"."""
    try:
        t = datetime.fromisoformat(iso)
    except Exception:
        return ""
    if t.date() == datetime.now().date():
        return f"today {t:%H:%M}"
    return f"{t.day} {t:%b}" + (f" {t.year}" if t.year != datetime.now().year else "")


def _newest_first(items: List[Item]) -> List[Item]:
    return sorted(items, key=lambda i: i.when or "", reverse=True)    # stable: ties keep order


def companion_items(ce: Any) -> List[Item]:
    panel = getattr(getattr(ce, "companion", None), "panel", None)
    if panel is None:
        return []
    icons = getattr(panel, "ICONS", {})
    items = [Item(COMPANION, "Notes as you write", f"{icons.get(n.kind, '•')} {n.text}",
                  passage=n.excerpt or "", ref=("notes", n))
             for n in list(getattr(panel, "notes", None) or [])]
    report, when = getattr(panel, "reader_report", None), getattr(panel, "reader_time", "")
    if report is not None:
        for q, w in getattr(report, "dips", None) or []:
            items.append(Item(COMPANION, "Reader's eye: where attention dips", w or q,
                              passage=q or "", when=when, ref=("reader", None)))
        for q in getattr(report, "questions", None) or []:
            items.append(Item(COMPANION, "Reader's eye: what a reader is wondering", q,
                              when=when, ref=("reader", None)))
        for q, w in getattr(report, "beats", None) or []:
            items.append(Item(COMPANION, "Reader's eye: an emotional beat", w or q,
                              passage=q or "", when=when, ref=("reader", None)))
        if getattr(report, "overall", ""):
            items.append(Item(COMPANION, "Reader's eye: overall", report.overall, when=when,
                              ref=("reader", None)))
    return items


def _scope(project: Any, chapter: Any) -> Optional[str]:
    try:
        scope, _ = project.find_chapter_with_scope(chapter.id)
        return scope
    except Exception:
        return None


def _report_label(kind: str) -> str:
    try:
        from src.ai.analysis_reports import LABELS, AnalysisKind
        return LABELS[AnalysisKind(kind)]
    except Exception:
        return kind.replace("_", " ").capitalize()


def critique_items(project: Any, chapter: Any, text: str) -> List[Item]:
    if project is None or chapter is None:
        return []
    items: List[Item] = []
    # The readiness checks (the scorecard's findings for this chapter).
    try:
        from src.ai import readiness as rd
        from src.data import readiness_state as rs
        data = _readiness_data(project)
        ms = (data.get("manuscripts") or {}).get(rs.scope_key(_scope(project, chapter))) or {}
        entry = ((ms.get("chapters") if isinstance(ms, dict) else None) or {}).get(chapter.id)
        entry = entry if isinstance(entry, dict) else {}
        results = entry.get("results") if isinstance(entry.get("results"), dict) else {}
        dismissed = data.get("dismissed")
        dismissed = set(dismissed) if isinstance(dismissed, dict) else set()
        stale = bool(results) and entry.get("text_hash") != rd.text_hash(text)
        when = str(entry.get("made_at", "") or "")
        specs = {s.name: s for s in rd.checks_for(level="chapter")}
        for name in [n for n in specs if n in results]:
            try:
                r = rd.CheckResult.from_dict(results[name])
            except Exception:
                continue
            if r.status not in SHOWN_STATUSES:
                continue
            label = specs[name].label + (" (last check; the text has changed since)"
                                         if stale else "")
            live = [i for i in r.items if i.verdict != "cleared"
                    and not (i.key and i.key in dismissed)]
            for i in live:
                about = _short(i.text, 90)
                items.append(Item(CRITIQUE, label, f"“{about}” — {i.reason}" if about
                                  else i.reason, passage=i.text, offset=i.start, when=when,
                                  ref=("check", name)))
            if not live and r.items == [] and r.message:
                items.append(Item(CRITIQUE, label, r.message, when=when, ref=("check", name)))
    except Exception as e:
        print(f"[feedback] readiness not read: {e}")
    # The Critique's reports: the newest of each kind for this chapter.
    try:
        titles = {getattr(chapter, "title", "") or "",
                  f"Chapter {getattr(chapter, 'number', '')}"}
        runs = [r for rs_ in _history_data(project).values() if isinstance(rs_, list)
                for r in rs_ if isinstance(r, dict)]
        seen = set()
        for run in sorted(runs, key=lambda r: str(r.get("timestamp", "")), reverse=True):
            chapters = run.get("chapters") if isinstance(run.get("chapters"), dict) else {}
            ch = next((chapters[t] for t in titles if t and isinstance(chapters.get(t), dict)),
                      None)
            if ch is None:
                continue
            reports = dict(ch.get("reports") or {}, **(ch.get("analyses") or {}))
            for kind, rep in reports.items():
                if kind in seen or not isinstance(rep, dict):
                    continue
                seen.add(kind)
                for level, words in (("major", ""), ("minor", ", minor")):
                    for finding in rep.get(level) or []:
                        items.append(Item(CRITIQUE, f"{_report_label(kind)} report{words}",
                                          str(finding), when=str(run.get("timestamp", "")),
                                          ref=("report", kind)))
    except Exception as e:
        print(f"[feedback] critique reports not read: {e}")
    return _newest_first(items)


# The Improve window's words kept in memory, only when they could not be
# written to the project's Improve notes file (D.14b; D.13c kept them all here).
_SESSION: Dict[tuple, List[Dict[str, Any]]] = {}
_SESSION_KEEP = 20
_VIEWS: "weakref.WeakSet" = weakref.WeakSet()
TAB_WORDS = {"suggestions": "💡 Suggestions", "critique": "📝 Critique",
             "rephrase": "✨ Rephrase", "expand": "🔍 Expand"}


def _key(project: Any, chapter: Any) -> tuple:
    path = str(getattr(project, "project_path", "") or "") if project is not None else ""
    return (path or f"unsaved:{id(project)}", getattr(chapter, "id", "") or "")


def remember_improve(window: Any, code: int = 0) -> None:
    """The call line in ``ImproveWindow.done``: what the window said about
    its passage, appended to the project's Improve notes (D.14b), or kept
    for this session when that cannot be written."""
    try:
        chapter = getattr(window, "chapter", None)
        if chapter is None or not getattr(chapter, "id", ""):
            return
        tabs = getattr(window, "tab_objects", {}) or {}
        result = getattr(tabs.get("suggestions"), "result", None)
        critique = {}
        for part in ("issues", "dialogue", "order", "works"):
            critique[part] = [str(x) for x in (getattr(result, part, None) or [])]
        versions = [{"text": v.current, "source": v.source, "why": v.why or "",
                     "rating": v.rating or ""} for v in getattr(window, "versions", []) or []
                    if (v.current or "").strip()]
        if not versions and not any(critique.values()):
            return
        record = {"when": datetime.now().isoformat(timespec="seconds"),
                  "passage": getattr(window, "passage", "") or "",
                  "accepted": getattr(window, "replacement", None) or "",
                  "critique": critique, "versions": versions}
        if _write_note(window.project, chapter, record):
            for view in list(_VIEWS):
                view.refresh_later()
            return
        try:
            record["project"] = weakref.ref(window.project) if window.project is not None \
                else None
        except TypeError:                         # cannot be referenced weakly: no check
            record["project"] = None
        runs = _SESSION.setdefault(_key(window.project, chapter), [])
        runs.append(record)
        del runs[:-_SESSION_KEEP]
        for view in list(_VIEWS):
            view.refresh_later()
    except Exception as e:                       # never in the way of the window closing
        print(f"[feedback] Improve not kept: {e}")


def _write_note(project: Any, chapter: Any, record: Dict[str, Any]) -> bool:
    """Append to the project's Improve notes; False when not written."""
    if project is None:
        return False
    try:
        from src.data import improve_notes
        return improve_notes.append(project, _chapter_scope(project, chapter), chapter.id,
                                    dict(record)) is not None
    except Exception as e:
        print(f"[feedback] Improve notes not written: {e}")
        return False


def _chapter_scope(project: Any, chapter: Any) -> Optional[str]:
    """The manuscript holding this chapter object (ids can repeat)."""
    try:
        from src.data import scene_marks
        return scene_marks.scope_of(project, chapter.id, chapter)
    except Exception:
        return _scope(project, chapter)


def _improve_records(project: Any, chapter: Any) -> List[tuple]:
    """(record, how to dismiss one of its items) for this chapter: the
    project's Improve notes, then any kept in memory this session."""
    out: List[tuple] = []
    if project is not None:
        try:
            from src.data import improve_notes
            scope = _chapter_scope(project, chapter)
            for rec in improve_notes.read(project, scope, chapter.id):
                out.append((rec, ("file", project, scope, chapter.id, rec.get("id", ""))))
        except Exception as e:
            print(f"[feedback] Improve notes not read: {e}")
    for rec in _SESSION.get(_key(project, chapter), []):
        ref = rec.get("project")
        if ref is not None and ref() is not project:      # another project, gone since
            continue
        out.append((rec, ("session", rec)))
    return out


def dismiss_item(item: "Item", key: str = "") -> bool:
    """Hide an Improve item: noted as dismissed in the file (or in this
    session's memory), nothing removed. True when it was noted."""
    how = item.dismiss
    if not how:
        return False
    key = key or how[-1]
    if how[0] == "session":
        gone = how[1].setdefault("dismissed", [])
        if key not in gone:
            gone.append(key)
        return True
    from src.data import improve_notes
    _where, project, scope, cid, rid, _key = how
    return improve_notes.dismiss(project, scope, cid, rid, key)


def _str_list(value: Any) -> List[str]:
    return [str(x) for x in value] if isinstance(value, list) else []


CRITIQUE_PARTS = (("issues", "What doesn't work"), ("dialogue", "Dialogue"),
                  ("order", "Order and flow"), ("works", "What works"))


def improve_items(project: Any, chapter: Any, text: str) -> List[Item]:
    if chapter is None:
        return []
    items: List[Item] = []
    shown = set()
    for rec, how in _improve_records(project, chapter):
        accepted, passage = str(rec.get("accepted") or ""), str(rec.get("passage") or "")
        versions = [v for v in rec.get("versions") or [] if isinstance(v, dict)]
        for v in versions:
            shown.add(str(v.get("text") or "").strip())
        here = [w for w in (accepted, passage) if w.strip() and w in text]
        if not here:                             # its words are no longer in the chapter
            continue
        at = here[0]
        gone = set(_str_list(rec.get("dismissed")))
        critique = rec.get("critique") if isinstance(rec.get("critique"), dict) else {}
        when = str(rec.get("when") or "")
        for part, words in CRITIQUE_PARTS:
            for n, line in enumerate(_str_list(critique.get(part))):
                key = f"c:{part}:{n}"
                if key in gone:
                    continue
                items.append(Item(IMPROVE, f"📝 Critique: {words}", line, passage=at,
                                  when=when, ref=("critique", at), dismiss=how + (key,)))
        for n, v in enumerate(versions):
            key = f"v:{n}"
            vtext = str(v.get("text") or "")
            if key in gone or not vtext.strip():
                continue
            source, why, rating = (str(v.get("source") or "suggestions"),
                                   str(v.get("why") or ""), str(v.get("rating") or ""))
            took = vtext.strip() == accepted.strip()
            extra = "; you accepted it" if took else (f"; rated {rating}" if rating else "")
            kind = f"{TAB_WORDS.get(source, source.capitalize())}: a version{extra}"
            items.append(Item(IMPROVE, kind, vtext + (f" — {why}" if why else ""),
                              passage=vtext if took and vtext in text else at, when=when,
                              ref=("expand" if source == "expand" else "suggestions", at),
                              dismiss=how + (key,)))
    for row in _db_rows(project):
        out, src = (row.get("output_text") or "").strip(), (row.get("source_text") or "").strip()
        if not out or out in shown or not (out in text or (src and src in text)):
            continue
        shown.add(out)
        style = row.get("style") or "suggestion"
        took = bool(row.get("accepted")) and out in text
        what = "you accepted it" if took else f"rated {row.get('rating') or 'neutral'}"
        at = out if out in text else src
        items.append(Item(IMPROVE, f"A {style} version, {what}", out, passage=at,
                          when=str(row.get("created_at") or ""),
                          ref=("expand" if style == "expansion" else "suggestions", at)))
    return _newest_first(items)


def collect(ce: Any) -> Dict[str, List[Item]]:
    project, chapter = getattr(ce, "project", None), getattr(ce, "chapter", None)
    text = ce.editor.toPlainText() if getattr(ce, "editor", None) is not None else ""
    out = {}
    for source, fn in ((COMPANION, lambda: companion_items(ce)),
                       (CRITIQUE, lambda: critique_items(project, chapter, text)),
                       (IMPROVE, lambda: improve_items(project, chapter, text))):
        try:
            out[source] = fn()
        except Exception as e:                   # one source failing leaves the others
            print(f"[feedback] {source}: {e}")
            out[source] = []
    return out


# ── Acting on an item ──────────────────────────────────────────────────

def find_passage(text: str, passage: str, offset: int = -1) -> int:
    """Where ``passage`` is in ``text`` (its old place first), or -1."""
    passage = passage or ""
    if not passage.strip():
        return -1
    if 0 <= offset and text[offset:offset + len(passage)] == passage:
        return offset
    at = text.find(passage)
    if at < 0 and len(passage) > 80:
        at = text.find(passage[:80])
    return at


def go_to(ce: Any, passage: str, offset: int = -1) -> bool:
    from PyQt6.QtGui import QTextCursor
    from src.ai.passage_critique import py_to_qt_index
    text = ce.editor.toPlainText()
    start = find_passage(text, passage, offset)
    if start < 0:
        return False
    end = start + (len(passage) if text[start:start + len(passage)] == passage else 80)
    cursor = QTextCursor(ce.editor.document())
    cursor.setPosition(py_to_qt_index(text, start))
    cursor.setPosition(py_to_qt_index(text, min(end, len(text))), QTextCursor.MoveMode.KeepAnchor)
    ce.editor.setTextCursor(cursor)
    ce.editor.ensureCursorVisible()
    ce.editor.setFocus()
    return True


def open_source(ce: Any, item: Item) -> str:
    """Open the place ``item`` came from. A message when it cannot."""
    kind, arg = item.ref if isinstance(item.ref, tuple) else (None, None)
    if item.source == COMPANION:
        panel = ce.companion.panel
        ce._show_right_panel(panel)
        section = panel.sections.get("reader" if kind == "reader" else "notes")
        if section is not None:
            section.set_open(True)               # for now; the writer's own choice is kept
            panel.scroll.ensureWidgetVisible(section, 0, 0)
        if kind == "notes" and arg in panel.notes:
            panel.notes_list.setCurrentRow(panel.notes.index(arg))
        return ""
    if item.source == CRITIQUE:
        from src.ui.analysis_menu import main_window_of
        mw = main_window_of(ce)
        grader = getattr(mw, "grader_widget", None)
        if grader is None:
            return "The Critique is in Revise ▸ Critique."
        from src.ui import screen_groups
        screen_groups.show(mw, grader)
        card = getattr(grader, "scorecard", None)
        cid = getattr(getattr(ce, "chapter", None), "id", "")
        if card is not None and cid and kind == "check":
            QTimer.singleShot(0, lambda: card._show_chapter_row(cid))
        return ""
    if item.source == IMPROVE:
        text = ce.editor.toPlainText()
        start = find_passage(text, arg or item.passage)
        if start < 0:
            return "That passage is no longer in the chapter, so Improve can't open on it."
        from src.ui import improve
        tab = kind if kind in improve.TABS and kind != "rephrase" else "suggestions"
        improve.open(ce, tab, text, start, start + len(arg or item.passage))
        return ""
    return ""


# ── The view under the writer's own feedback ───────────────────────────

class SourcesView(QWidget):
    def __init__(self, ce: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ce = ce
        self.items: List[Item] = []
        self.sections: Dict[str, CollapsibleSection] = {}
        self.bodies: Dict[str, QVBoxLayout] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(2)
        closed = _closed()
        for source in SOURCES:
            section = CollapsibleSection(TITLES[source], f"feedback_{source}")
            section.header.setToolTip(f"Click to open or close. Read-only: "
                                      f"{OPEN_WORDS[source].lower()} to work on it there.")
            section.set_open(source not in closed)
            section.toggled.connect(lambda _k, c, s=source: _remember(s, c))
            self.sections[source] = section
            self.bodies[source] = section.body_layout
            section.body_layout.setSpacing(4)
            layout.addWidget(section)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(text_style("accent_ink", 10))
        self.status.setVisible(False)
        layout.addWidget(self.status)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        _VIEWS.add(self)

    def showEvent(self, event) -> None:          # noqa: N802
        super().showEvent(event)
        self.refresh()                           # read afresh each time the tab is shown

    def refresh_later(self) -> None:
        try:
            if self.isVisible():
                self._timer.start()
        except RuntimeError:                     # deleted meanwhile
            pass

    def refresh(self) -> None:
        try:
            self.show_items(collect(self.ce))
        except Exception as e:                   # never escape a slot
            print(f"[feedback] {e}")

    def show_items(self, found: Dict[str, List[Item]]) -> None:
        self.items = []
        self.status.setVisible(False)
        for source in SOURCES:
            body = self.bodies[source]
            while body.count():
                w = body.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            items = found.get(source) or []
            self.sections[source].set_count(len(items))
            if not items:
                body.addWidget(_note(EMPTY[source]))
                continue
            for item in items[:MAX_SHOWN]:
                self.items.append(item)
                body.addWidget(self._label(item, len(self.items) - 1))
            if len(items) > MAX_SHOWN:
                more = _note(f"… and {len(items) - MAX_SHOWN} more. "
                             f"<a href='more:{source}'>{OPEN_WORDS[source]}</a>")
                more.linkActivated.connect(self._more)
                body.addWidget(more)

    def _label(self, item: Item, n: int) -> QLabel:
        c = PALETTE
        head = html.escape(item.kind) + (f" · {when_words(item.when)}" if when_words(item.when)
                                          else "")
        links = []
        if item.passage.strip():
            links.append(f"<a href='go:{n}'>Go to</a>")
        links.append(f"<a href='open:{n}'>{OPEN_WORDS[item.source]}</a>")
        if item.dismiss:
            links.append(f"<a href='dismiss:{n}'>{DISMISS}</a>")
        label = QLabel(
            f"<div style='color:{c['ink_faint']};font-size:10px'>{head}</div>"
            f"<div style='color:{c['ink']}'>{html.escape(_short(item.text, 400))}</div>"
            f"<div style='font-size:11px'>{' · '.join(links)}</div>")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                      | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        label.setStyleSheet(f"QLabel {{ padding: 3px 2px 5px 2px; border-bottom: 1px solid "
                            f"{c['border']}; font-size: 11px; }}")
        label.setAccessibleName(f"{TITLES[item.source]}: {item.kind}")
        label.setAccessibleDescription(item.text)
        if item.passage:
            label.setToolTip(_short(item.passage, 300))
        label.linkActivated.connect(self._link)
        return label

    def _link(self, href: str) -> None:
        try:
            what, _, n = href.partition(":")
            item = self.items[int(n)]
            if what == "go":
                if not go_to(self.ce, item.passage, item.offset):
                    self._say(f"That passage is no longer in the {CHAPTER}.")
            elif what == "dismiss":
                if dismiss_item(item):
                    self.refresh()
                else:
                    self._say("Could not dismiss it: the Improve notes file could not be "
                              "saved.")
            else:
                self._say(open_source(self.ce, item))
        except Exception as e:                   # never escape a slot
            print(f"[feedback] {e}")

    def _more(self, href: str) -> None:
        source = href.partition(":")[2]
        first = next((i for i in self.items if i.source == source), None)
        if first is not None:
            self._say(open_source(self.ce, first))

    def _say(self, message: str) -> None:
        self.status.setText(message or "")
        self.status.setVisible(bool(message))


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setStyleSheet(text_style("ink_faint", 10))
    return label


def _closed() -> set:
    try:
        from src.ui.ui_kit import _settings
        value = _settings().value(CLOSED_KEY) or ""
        return {s for s in str(value).split(",") if s in SOURCES}
    except Exception:                            # unreadable: every heading open
        return set()


def _remember(source: str, collapsed: bool) -> None:
    try:
        from src.ui.ui_kit import _settings
        closed = _closed()
        (closed.add if collapsed else closed.discard)(source)
        s = _settings()
        s.setValue(CLOSED_KEY, ",".join(sorted(closed)))
        s.sync()
    except Exception as e:
        print(f"[feedback] fold not remembered: {e}")


# ── The call line in ``ChapterEditor._init_ui`` ─────────────────────────

def install(ce: Any) -> Optional[SourcesView]:
    try:
        fw = ce.feedback_widget
        view = SourcesView(ce)
        fw.sources_layout.addWidget(view)
        ce.feedback_sources = view
        panel = getattr(getattr(ce, "companion", None), "panel", None)
        if panel is not None and hasattr(panel, "notes_changed"):
            panel.notes_changed.connect(view.refresh_later)
        ce.right_panel.currentChanged.connect(lambda _i: view.refresh_later())
        return view
    except Exception as e:                       # the Feedback tab stays as it was
        print(f"[feedback] other sources not added: {e}")
        return None
