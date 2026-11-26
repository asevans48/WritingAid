"""Analyze ▾ entries run as Critique reports (piece D.5).

The editor's six analyses used to open a result window each
(``ProseAnalysisDialog``, ``PromiseCheckDialog``) offering only Copy and
Close. Each entry is now a shortcut: it switches to the Critique (Revise ▸
Critique, or its own window when it is out) and runs the matching reports
on the chapter open in Write (``src/ai/analysis_reports``), where the
result is rated, saved, exported and kept in the critique history.

Each analysis's main tab starts with a line of links, so nothing the old
windows did is lost and nothing is added to a menu or a button row:

* **Run again** (the Promise Check window's "Run Check");
* **Copy** (the old windows' "Copy to Clipboard");
* **Show in a window (old)**: the old window, during the trial (rule 11).

Without a Critique (an editor on its own), an entry opens the old window,
as before.
"""

from __future__ import annotations

from typing import Any, Optional

from src.ui import notify

# Analyze ▾ entry → the ChapterEditor method that opens its old window.
OLD_WINDOWS = {"promises": "_check_promises", "prose": "_analyze_prose",
               "characters": "_analyze_characters", "world": "_analyze_world",
               "plot": "_analyze_plot"}


def install(grader) -> None:
    """Give the Critique the new report kinds' tab names (once per class)."""
    from src.ai.analysis_reports import LABELS
    for kind, label in LABELS.items():
        grader.REPORT_TAB_LABELS.setdefault(kind, label)


def main_window_of(widget) -> Optional[Any]:
    """The main window (the one with the Critique), from any widget in it or
    in one of its detached windows."""
    w = widget
    while w is not None:
        if hasattr(w, "grader_widget") and hasattr(w, "manuscript_editor"):
            return w
        w = w.parent() if hasattr(w, "parent") else None
    try:
        from PyQt6.QtWidgets import QApplication
        for top in QApplication.topLevelWidgets():
            if hasattr(top, "grader_widget") and hasattr(top, "manuscript_editor"):
                return top
    except Exception:
        pass
    return None


# ── Running ────────────────────────────────────────────────────────────

def run(chapter_editor, key: str) -> bool:
    """The Analyze ▾ entry ``key``: run its reports in the Critique. Returns
    False (and opens the old window) when there is no Critique to run in."""
    try:
        mw = main_window_of(chapter_editor)
        grader = getattr(mw, "grader_widget", None)
        if grader is None:
            return _old_window(chapter_editor, key)
        return run_in(grader, chapter_editor, key, mw)
    except Exception as e:                        # never let an exception escape a slot
        print(f"[analysis] could not run {key}: {e}")
        return False


def run_in(grader, chapter_editor, key: str, main_window=None) -> bool:
    from src.ai.analysis_reports import ITEMS, RUN_KIND_PREFIX
    label, kinds = ITEMS[key]
    text = chapter_editor.editor.toPlainText()
    if not text.strip():
        notify.empty(chapter_editor, "Empty Chapter", "Write some of the chapter first, then "
                     f"run “{label}”.")
        return False
    worker = getattr(grader, "_worker", None)
    if worker is not None and worker.isRunning():
        notify.empty(chapter_editor, "Critique running",
                     "A critique is already running in the Critique. Wait for it to finish, "
                     "or press Stop there, then run this again.")
        return False
    chapter = chapter_editor.chapter
    try:
        chapter_editor.save_to_model()
    except Exception as e:
        print(f"[analysis] could not sync the chapter: {e}")
    grader.set_current_chapter(text, chapter.title)
    if main_window is not None:
        from src.ui import screen_groups
        screen_groups.show(main_window, grader)         # D.4: raises its window when out
    grader.scope_single_radio.setChecked(True)
    chapters = [{"title": chapter.title or f"Chapter {chapter.number}", "text": text,
                 "index": _index_of(chapter_editor), "scope": grader._active_scope(),
                 "id": getattr(chapter, "id", "") or ""}]
    grader._start_critique(chapters, list(kinds), run_kind=RUN_KIND_PREFIX + key)
    show = lambda *_: _safe(_show_result, grader, kinds[0])
    worker = grader._worker
    if worker is not None and worker.isRunning():
        worker.finished.connect(show)
    else:                                    # already done: after its result is drawn
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, show)
    grader._analysis_chapter_editor = chapter_editor
    return True


def _index_of(chapter_editor) -> int:
    ms = getattr(chapter_editor, "manuscript", None)
    chapters = getattr(ms, "chapters", None) or []
    for i, c in enumerate(chapters):
        if c is chapter_editor.chapter or getattr(c, "id", None) == getattr(chapter_editor.chapter, "id", ""):
            return i
    return 0


def _show_result(grader, kind) -> None:
    """Open the analysis's main tab and bring the results into view."""
    tabs = grader.results_tabs
    label = grader.REPORT_TAB_LABELS.get(kind, "")
    for i in range(tabs.count()):
        if tabs.tabText(i) == label:
            tabs.setCurrentIndex(i)
            break
    from PyQt6.QtWidgets import QScrollArea
    scroll = grader.findChild(QScrollArea)
    if scroll is not None and scroll.widget() is not None:     # the report at the top
        from PyQt6.QtCore import QPoint
        scroll.verticalScrollBar().setValue(tabs.mapTo(scroll.widget(), QPoint(0, 0)).y())


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as e:                       # an exception escaping a Qt slot aborts PyQt6
        print(f"[analysis] {e}")


# ── The links on an analysis's tab ─────────────────────────────────────

def tab_links(kind: Any) -> str:
    """HTML for the top of the tab, or "" when ``kind`` is no analysis's
    main report."""
    from src.ai.analysis_reports import item_for_kind
    from src.ui.ui_kit import PALETTE
    key = item_for_kind(kind)
    if not key:
        return ""
    links = [f"<a href='analysis:again:{key}'>Run again</a>",
             f"<a href='analysis:copy:{key}'>Copy</a>"]
    if key in OLD_WINDOWS:
        links.append(f"<a href='analysis:old:{key}'>Show in a window (old)</a>")
    return (f"<p style='font-size:12px; color:{PALETTE['ink_faint']};'>"
            "From 🔍 Analyze ▾ in Write · " + " · ".join(links) + "</p>")


def on_link(grader, url: str) -> None:
    """``analysis:<action>:<key>`` and ``wa-goto:`` (a quote) links."""
    try:
        if url.startswith("wa-goto:"):
            from src.ai.text_links import parse_link
            parsed = parse_link(url)
            issues = getattr(getattr(grader, "scorecard", None), "issues", None)
            if parsed and issues is not None:
                issues.show_requested.emit(parsed[0], parsed[1], 0)
            return
        _, action, key = (url.split(":", 2) + ["", ""])[:3]
        if action == "copy":
            _copy(grader, key)
        elif action in ("again", "old"):
            ce = _chapter_editor(grader)
            if ce is None:
                notify.empty(grader, "No chapter open", "Open the chapter in Write first.")
            elif action == "again":
                run(ce, key)
            else:
                _old_window(ce, key)
    except Exception as e:                       # never let an exception escape a slot
        print(f"[analysis] link {url}: {e}")


def _chapter_editor(grader):
    mw = main_window_of(grader)
    ce = getattr(getattr(mw, "manuscript_editor", None), "current_chapter_editor", None)
    return ce or getattr(grader, "_analysis_chapter_editor", None)


def _copy(grader, key: str) -> None:
    from PyQt6.QtWidgets import QApplication
    from src.ai.analysis_reports import ITEMS
    kind = ITEMS[key][1][0]
    browser = (getattr(grader, "_report_tabs", {}).get(kind) or (None,))[0]
    text = browser.toPlainText() if browser is not None else ""
    if text:
        QApplication.clipboard().setText(text)
        notify.done(grader, "Copied", "Report copied to the clipboard.")


def _old_window(chapter_editor, key: str) -> bool:
    name = OLD_WINDOWS.get(key)
    if name is None:                 # Writing hints never had a window
        notify.empty(chapter_editor, "Writing hints",
                     "Writing hints run as a report in the Critique (Revise ▸ Critique).")
        return False
    getattr(chapter_editor, name)()
    return False
