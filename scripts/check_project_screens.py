"""The safety check's screen step (piece 0.3): open the main screens on a
COPY of a project, then save it the way the app does, and report anything
that errored or changed.

Normally run for you by the safety check:

    venv/bin/python scripts/check_project_safety.py "/path/to/Book.writerproj"

It can also be run on its own on a project file; the project is copied to
a temporary folder first, as the safety check does, and the original is
never opened by the app:

    venv/bin/python scripts/check_project_screens.py "/path/to/Book.writerproj"

The app's main window is built in a separate process with a scratch home
folder (never your settings), no model, no LanguageTool and no dialogs
that wait. The copy is opened in it, and then, for every manuscript (the
main one and each novella), the first chapter is opened in Write with its
Companion, Planner and Feedback panels, and every one of the ten screens is
shown and drawn. Then the window saves the copy (File ▸ Save), and the copy
is opened again and compared with how it was before the window opened it.

A problem is reported if a screen raises an error, the save fails, a file
is deleted, a chapter's text or revisions change, a field disappears from
the project file, or any part of the project differs after the save. Only
names, counts and checksums are printed.

Exit code 0 = safe, 1 = a problem was found.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

# The Write screen's side panels, by the widget each is.
PANELS = (("Companion", lambda ed: ed.companion.panel),
          ("Planner", lambda ed: ed.planner_widget),
          ("Feedback", lambda ed: ed.feedback_widget))
WINDOW_SIZE = (1440, 900)


def _safety():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import check_project_safety
    return check_project_safety


# ── Parent: run the window in its own process ─────────────────────────

def _child_env(home: Path) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET"))}
    env["HOME"] = str(home)                      # never the writer's settings or stores
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("QT_SCALE_FACTOR", None)
    return env


def run(copy_file: Path, timeout: int = 900) -> Dict[str, Any]:
    """Open the screens on ``copy_file`` (already a copy, in a temporary
    folder) in a child process. Returns its report: ``problems``,
    ``notes`` and ``screens`` (names opened)."""
    copy_file = Path(copy_file)
    with tempfile.TemporaryDirectory(prefix="project_screens_home_") as home:
        report_path = Path(home) / "_screens_report.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--child",
               str(copy_file), str(report_path)]
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), env=_child_env(Path(home)),
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"problems": [f"the screens did not finish within {timeout} seconds"],
                    "notes": [], "screens": []}
        if report_path.exists():
            return json.loads(report_path.read_text(encoding="utf-8"))
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        return {"problems": ["the screen check stopped before it finished: "
                             + " | ".join(line.strip()[:160] for line in tail)],
                "notes": [], "screens": []}


def check(copy_file: Path) -> Tuple[List[str], List[str]]:
    """Run the screen step on a copy and print its lines. (problems, notes)."""
    report = run(copy_file)
    screens = report.get("screens", [])
    if screens:
        print(f"  screens: opened {len(screens)} on the copy "
              f"({report.get('manuscripts', 1)} manuscript(s)), then saved it from the window")
    return list(report.get("problems", [])), list(report.get("notes", []))


# ── Child: build the window, open everything, save, compare ───────────

def _quiet_everything(home: Path, messages: List[str], put=setattr) -> None:
    """Nothing may block, reach a model, or touch the writer's stores.
    ``put`` sets each patch (a test passes ``monkeypatch.setattr`` so they
    are put back afterwards)."""
    from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox
    put(QDialog, "exec", lambda self, *a, **k: 0)

    def boxed(kind):
        def box(*a, **k):
            title = next((x for x in a if isinstance(x, str)), "")
            messages.append(f"{kind}: {title[:80]}")
            return QMessageBox.StandardButton.No
        return staticmethod(box)
    for kind in ("information", "warning", "critical", "question"):
        put(QMessageBox, kind, boxed(kind))
    put(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    put(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))

    # Panel sizes and the like that screens remember (QSettings by name)
    # go to files in the scratch home, never the writer's own preferences
    # (on a Mac those ignore HOME).
    import PyQt6.QtCore as QtCore
    real = QtCore.QSettings
    if not getattr(real, "_scratch", False):
        class ScratchSettings(real):
            _scratch = True

            def __init__(self, *a, **k):
                if not k and (not a or (isinstance(a[0], str) and all(
                        isinstance(x, str) for x in a[1:2]))):
                    name = "_".join(a) or "default"
                    super().__init__(str(home / f"qsettings_{name}.ini"), real.Format.IniFormat)
                else:
                    super().__init__(*a, **k)
        put(QtCore, "QSettings", ScratchSettings)
        for mod in list(sys.modules.values()):
            if (getattr(mod, "__name__", "") or "").startswith("src.") \
                    and getattr(mod, "QSettings", None) is real:
                put(mod, "QSettings", ScratchSettings)

    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import screen_harness
    import src.ai.word_suggest as ws
    import src.data.companion_state as cs
    import src.data.critique_history as ch
    import src.data.writing_habit as wh
    import src.ui.ui_kit as kit
    import src.utils.proofing as pf
    touched = ((pf.LanguageToolEngine, "ensure_started"), (ws, "get_llm"),
               (cs, "state_path"), (ch, "history_path"), (wh, "habit_path"),
               (kit, "_settings"))
    kept = [(obj, name, getattr(obj, name)) for obj, name in touched if hasattr(obj, name)]
    for obj, name, value in kept:                # registered, so a test puts them back
        put(obj, name, value)
    screen_harness._isolate(home)
    # The Companion state and critique history beside the copy are shown
    # as they are (they are copies too, in the same temporary folder).
    originals = {(id(obj), name): value for obj, name, value in kept}
    put(cs, "state_path", originals[(id(cs), "state_path")])
    put(ch, "history_path", originals[(id(ch), "history_path")])
    try:
        import src.ai.task_llm as tl
        for name in ("build_task_llm_override", "build_llm_from_spec",
                     "build_critique_llm", "build_default_llm"):
            if hasattr(tl, name):
                put(tl, name, lambda *a, **k: None)
    except Exception:
        pass
    try:
        from src.ai.llm_client import LLMClient

        def no_model(self, *a, **k):
            raise RuntimeError("no model is run by the safety check")
        put(LLMClient, "generate_text", no_model)
    except Exception:
        pass


def _settle(app, rounds: int = 6) -> None:
    from src.ui import background
    for _ in range(rounds):
        background.wait_all(10000)
        app.processEvents()


def child(copy_file: Path, report_path: Path) -> int:
    """The child process: open the screens, write the report, leave."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    report = open_and_save(copy_file, Path(os.environ["HOME"]), app)
    report_path.write_text(json.dumps(report))
    sys.stdout.flush()
    os._exit(0)


def open_and_save(copy_file: Path, home: Path, app, put=setattr) -> Dict[str, Any]:
    """Open the main window on ``copy_file``, open every screen, save from
    the window, and compare. Returns {problems, notes, screens, manuscripts}."""
    sys.path.insert(0, str(ROOT))
    safety = _safety()
    problems: List[str] = []
    notes: List[str] = []
    messages: List[str] = []
    errors: List[str] = []
    opened: List[str] = []
    log = io.StringIO()
    state: Dict[str, Any] = {}

    def hook(kind, value, tb):                   # errors escaping a Qt slot
        errors.append(f"{kind.__name__}: {str(value)[:160]}")
    put(sys, "excepthook", hook)

    def finish(manuscripts: int = 0) -> Dict[str, Any]:
        win = state.get("win")
        if win is not None:
            try:
                win._video_studio_autosave_timer.stop()
            except Exception:
                pass
            win.hide()
            win.deleteLater()
            app.processEvents()
        out = [line.strip() for line in log.getvalue().splitlines()
               if any(w in line.lower() for w in ("error", "failed", "traceback"))]
        if out:
            notes.append("messages while the screens were open: "
                         + " | ".join(line[:160] for line in out[:6]))
        if messages:
            notes.append("message boxes the window tried to show: " + " | ".join(messages[:6]))
        return {"problems": problems, "notes": notes, "screens": opened,
                "manuscripts": manuscripts}

    _quiet_everything(home, messages, put)
    from src.models.project import WriterProject
    from src.ui import screen_groups as sg
    from src.ui.main_window import MainWindow
    put(MainWindow, "_startup_load_project", lambda self: None)
    put(MainWindow, "_confirm_unsaved_changes", lambda self: True)
    put(MainWindow, "_update_project_summary", lambda self: None)   # would ask a model
    put(MainWindow, "_init_rag_system", lambda self: None)          # search index only

    folder = copy_file.parent
    before_files = safety.snapshot(folder)
    raw_before = json.loads(copy_file.read_text(encoding="utf-8"))
    with contextlib.redirect_stdout(log):
        opened_first = WriterProject.load_project(str(copy_file))
        first = safety.describe(opened_first)
        empty_before = {k for k, v in opened_first.model_dump(mode="json").items() if not v}

    def attempt(label: str, action) -> bool:
        before = len(errors)
        try:
            with contextlib.redirect_stdout(log):
                action()
                _settle(app)
        except Exception as e:
            problems.append(f"{label}: {type(e).__name__}: {str(e)[:160]}")
            log.write(traceback.format_exc()[-600:])
            return False
        if len(errors) > before:
            problems.append(f"{label}: " + "; ".join(errors[before:][:3]))
            return False
        return True

    def build():
        win = MainWindow()
        win.resize(*WINDOW_SIZE)
        win.show()
        state["win"] = win

    if not attempt("building the main window", build):
        return finish()
    win = state["win"]

    def load():
        win.current_project = WriterProject.load_project(str(copy_file))
        win._load_project_into_ui()
        win.project_name_label.setText(win.current_project.name)

    if not attempt("opening the project in the window", load):
        return finish()
    project = win.current_project
    editor = win.manuscript_editor
    start = project.active_subproject_id
    scopes = [start] + [s for s in [None] + [sp.id for sp in project.subprojects] if s != start]

    def draw(label: str):
        def go():
            win.grab()
        if attempt(label, go):
            opened.append(label)

    for scope in scopes:
        where = "main manuscript" if scope is None else "novella " + str(
            [sp.id for sp in project.subprojects].index(scope) + 1)
        if scope != project.active_subproject_id:
            if not attempt(f"switching to the {where}", lambda: editor.switch_subproject(scope)):
                continue
        sg.show(win, editor)
        chapters = project.manuscript.chapters
        if not chapters:
            draw(f"Write ({where}, no chapters)")
            continue
        chosen = next((c for c in chapters if (c.content or "").strip()), chapters[0])
        if not attempt(f"opening chapter {chosen.number} of the {where}",
                       lambda: editor.open_chapter(chosen.id)):
            continue
        draw(f"Write ({where}, chapter {chosen.number})")
        ed = editor.current_chapter_editor
        if ed is None:
            problems.append(f"chapter {chosen.number} of the {where} did not open in Write")
            continue
        for name, panel in PANELS:
            if attempt(f"{name} panel ({where})", lambda: ed._show_right_panel(panel(ed))):
                draw(f"{name} panel ({where})")
    if project.active_subproject_id != start:
        attempt("switching back to the manuscript the project opens on",
                lambda: editor.switch_subproject(start))

    for key, attr in sg.OLD_TABS:
        widget = getattr(win, attr, None)
        if widget is None:
            problems.append(f"the {key} screen is missing from the window")
            continue
        if attempt(f"showing the {key} screen", lambda: sg.show(win, widget)):
            draw(f"{key} screen")
    sg.show(win, editor)

    # Save the way File ▸ Save does, then compare.
    critical_before = sum(m.startswith("critical") for m in messages)
    attempt("saving from the window", win._save_project)
    if sum(m.startswith("critical") for m in messages) > critical_before:
        problems.append("saving from the window failed (it showed an error)")

    after_files = safety.snapshot(folder)
    d = safety.diff_snapshots(before_files, after_files)
    if d["deleted"]:
        problems.append(f"the window deleted {len(d['deleted'])} file(s): {d['deleted'][:5]}")
    prose = [k for k in d["changed"] if "revision_" in k]
    if prose:
        problems.append(f"opening the screens and saving changed {len(prose)} chapter file(s): "
                        f"{prose[:5]}")
    shrunk = [k for k in d["shrunk"] if k.endswith(".md")]
    if shrunk:
        problems.append(f"saving from the window made {len(shrunk)} text file(s) smaller: "
                        f"{shrunk[:5]}")
    if d["added"]:
        notes.append(f"the window added {len(d['added'])} file(s) beside the copy: "
                     f"{d['added'][:4]}")
    try:
        raw_after = json.loads(copy_file.read_text(encoding="utf-8"))
        lost = sorted(safety._keys(raw_before) - safety._keys(raw_after))
        if lost:
            problems.append(f"saving from the window dropped {len(lost)} field(s) from the "
                            f"project file: {lost[:8]}")
        with contextlib.redirect_stdout(log):
            second = safety.describe(WriterProject.load_project(str(copy_file)))
        for p in safety.compare_descriptions(first, second):
            p = (p.replace("after save and reopen", "after the window saved it")
                 .replace("after reopen", "after the window saved it"))
            section = p.split("'")[1] if p.startswith("section '") else None
            if section in empty_before:            # was empty: the window filled in defaults
                notes.append(f"the window filled in '{section}' with its defaults (it was empty)")
            else:
                problems.append(p)
    except Exception as e:
        problems.append(f"the copy did not open again after the window saved it: "
                        f"{type(e).__name__}: {str(e)[:160]}")
    return finish(len(scopes))


def main(argv: List[str]) -> int:
    if len(argv) == 3 and argv[0] == "--child":
        return child(Path(argv[1]), Path(argv[2]))
    if not argv:
        print(__doc__)
        return 1
    safety = _safety()
    ok = True
    for arg in argv:
        path = Path(arg).expanduser()
        if not path.is_file():
            print(f"Not found: {path}")
            ok = False
            continue
        print(f"Project: {path.name}")
        original = safety.snapshot(path.parent)
        with tempfile.TemporaryDirectory(prefix="project_screens_") as tmp:
            work = Path(tmp) / "copy"
            safety.copy_project(path.parent, work)
            problems, notes = check(work / path.name)
        if safety.snapshot(path.parent) != original:
            problems.append("THE ORIGINAL PROJECT CHANGED DURING THE CHECK")
        else:
            print("  original untouched")
        for n in notes:
            print(f"  note: {n}")
        for p in problems:
            print(f"  PROBLEM: {p}")
        print("  RESULT: " + ("safe — the screens open and the window saves it unchanged"
                              if not problems else f"{len(problems)} problem(s)"))
        print()
        ok = ok and not problems
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
