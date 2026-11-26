"""Screenshot and clutter-count harness (piece U.2).

One command draws screens at every size the plan supports, checks them, and
counts their clutter against the 0.2 baseline:

    venv/bin/python scripts/screen_harness.py                  # every screen
    venv/bin/python scripts/screen_harness.py suggestions companion write
    venv/bin/python scripts/screen_harness.py --list
    venv/bin/python scripts/screen_harness.py --compare <earlier run folder>
    venv/bin/python scripts/screen_harness.py --menus write     # menus as counted

Each screen is opened on a small sample project built in code (never a real
project), drawn at 1024×600, 1440×900 and 2560×1440, and once at 150%
scaling at 1440×900. Every size runs in its own process with a simulated
screen of that size, so "opens no larger than the screen" is tested for
real. Images go to a scratch folder (printed at the end) with ``report.json``.

The report lists:

* windows larger than their screen;
* text-holding widgets drawn smaller than a readable height (rule 12);
* tabs, sections, menu items and visible buttons per screen, compared with
  ``docs/publishing/screens_baseline.json`` (rule 13: no count may rise).
  Menu items follow decision 11: a menu of one closely related group
  (``GROUPED_MENUS``) counts as one entry; the every-item count is in the
  report beside it.

``--compare`` checks every image against an earlier run, pixel for pixel:
the proof that a refactor changed nothing visible.

Exit code 0 = no problems, 1 = a problem was found.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "publishing" / "screens_baseline.json"

SIZES = [(1024, 600, 1.0), (1440, 900, 1.0), (2560, 1440, 1.0), (1440, 900, 1.5)]
COUNT_AT = (1440, 900, 1.0)          # the baseline was measured at this size

SCREENS = {
    # name: (kind, description)  kind: "dialog" | "page" | "panel"
    "suggestions": ("dialog", "Suggestions window (passage critique), with a sample reply"),
    "companion": ("panel", "Write side panel: Companion"),
    "style": ("retired", "Write side panel: Style (retired in D.6)"),
    "planner": ("panel", "Write side panel: Planner"),
    "feedback": ("panel", "Write side panel: Feedback"),
    "write": ("page", "Write tab (chapter list and editor)"),
    "plot": ("page", "Plot tab"),
    "characters": ("page", "Characters tab"),
    "world": ("page", "World tab"),
    "attributions": ("page", "Attributions tab"),
    "visuals": ("page", "Visuals tab"),
    "prose_profile": ("page", "Prose Profile tab"),
    "critique": ("page", "Critique tab"),
    "video_studio": ("page", "Video Studio tab"),
    "publishing": ("page", "Publishing tab"),
    "assistant": ("page", "Sidebar: AI Assistant"),
    "outline": ("page", "Sidebar: Chapter Outline"),
    "companion_goal": ("panel", "Companion with writing goals set and a sample record (H.1)"),
    "habit": ("dialog", "Your writing record: the 12-week window, with a sample record (H.1)"),
    "main_tabs": ("tabs", "Main window's top-level tabs: the five groups, Story open (D.4)"),
    "main_tabs_ten": ("tabs", "The same with the old ten tabs (Settings ▸ Main tabs unticked)"),
    "critique_analysis": ("report", "Critique: Analyze ▾ ▸ Prose run as a report, with a sample reply (D.5)"),
    "critique_analysis_nomodel": ("report", "Critique: Analyze ▾ ▸ Writing hints with no model (D.5)"),
    "critique_character_check": ("report", "Critique: Analyze ▾ ▸ Characters with no model, the scan across the book (P.8)"),
    "character_book": ("page", "Characters: a character's Across the book section, open, on a 12-chapter sample (P.8)"),
    "ratings_by_voice": ("dialog", "Training Studio ▸ Browse rows…, Source: rated rewrites, by voice, on sample ratings (V.5)"),
    "improve": ("dialog", "Improve window: 💡 Suggestions tab, with a sample reply (D.2b)"),
    "improve_critique": ("dialog", "Improve window: 📝 Critique tab, with a sample reply (D.2b)"),
    "improve_expand": ("dialog", "Improve window: 🔍 Expand tab, word scan, no model (D.2b)"),
    "improve_rephrase": ("dialog", "Improve window: ✨ Rephrase tab, with sample options, no "
                                   "model (D.2c)"),
    "publishing_package": ("page", "Publishing tab with 📦 Submission package open: the "
                                   "synopsis filled in from a sample plan, no model (9.3)"),
}
# The Publishing tab with the submission package open (9.3): drawn and
# counted on its own ("publishing" is the tab with nothing chosen in its
# list); its figures joined the baseline on 26 Nov 2026.
PACKAGE_SCREENS = ("publishing_package",)
# The Improve window, one picture per tab (D.2b, D.2c): drawn and counted;
# its figures joined the baseline on 26 Nov 2026.
IMPROVE_SCREENS = {"improve": "suggestions", "improve_critique": "critique",
                   "improve_expand": "expand", "improve_rephrase": "rephrase"}
# The main window's ten screens, with the labels it gives them (D.4 groups
# them; every screen is also drawn on its own above, as before).
TAB_SCREENS = ("main_tabs", "main_tabs_ten")
# Drawn with a sample writing record and goals, which are put back after;
# not counted (not in the 0.2 baseline; the Companion is counted as "companion").
HABIT_SCREENS = ("companion_goal", "habit")
# Analyze ▾ entries run as Critique reports (D.5): drawn, not counted (the
# Critique itself is counted as "critique").
ANALYSIS_SCREENS = ("critique_analysis", "critique_analysis_nomodel", "critique_character_check")
# A character's page with the Across the book section open, on a book of its
# own (P.8): drawn, not counted (the Characters tab is counted as "characters").
CHARACTER_SCREENS = ("character_book",)
# Rated rewrites grouped by voice, in the Training Studio's Browse rows
# dialog, on sample ratings in a database of its own (V.5): drawn, not
# counted (the Training Studio is not in the 0.2 baseline).
VOICE_SCREENS = ("ratings_by_voice",)
# The side panel's tabs, by the widget each is (D.6 retired the Style tab,
# so numbers would shift; the widgets do not).
PANELS = {"planner": lambda ed: ed.planner_widget,
          "feedback": lambda ed: ed.feedback_widget,
          "companion": lambda ed: ed.companion.panel}
# Screens retired by a piece: not drawn, counted as empty, and where they went.
RETIRED = {"style": "D.6: its list is the Companion's next-fix card (✓ Checks ▾ → Style "
                    "issues panel…), its switches are ✓ Checks ▾ → Style checks"}

# How menu items are counted (decision 11, 24 Nov 2026). A menu whose items
# are one closely related group counts as ONE entry: a list of words, one
# setting's choices, one subject's handful of actions. Every other item
# counts on its own, even inside a submenu. ✨ Improve this ▸ was three
# (Rephrase, Suggestions, Overly descriptive?) until decision 16 (25 Nov
# 2026): they open one Improve window, so it counts as one. A submenu or menu button
# is grouped when its title starts with one of these. Change the list, not
# the code, if the writer regroups. Documented in docs/publishing/screens.md.
GROUPED_MENUS = (
    "Style checks",             # ✓ Checks ▾ → one switch per style check
    "Mode",                     # ✓ Checks ▾ → drafting / revising / switch as I write
    "📖 Synonyms for",          # right-click: a list of words (its Antonyms too)
    "Antonyms",
    "Look Up Context",          # right-click: the reference look-ups
    "Heading Style",            # right-click → More: Normal, Heading 1 to 3
    "🔊 Text to Speech",        # right-click → More: read and generate aloud
    "🗣 Read Aloud",            # Write toolbar: the same, as a split button
    "Novellas",                 # Write header: Novellas ▾
    "Drafts",                   # Write header: Drafts ▾ (manuscript drafts)
    "📝",                       # Write toolbar: annotations (add, view all)
    "✨ Improve this",          # right-click: Rephrase, Suggestions, Overly descriptive? (decision 16)
)

SAMPLE_TEXT = (
    "The storm broke at dusk. Mara ran to the pier, where Dr. Voss waited. "
    "\"Too late,\" he said. She didn't answer.\n"
    "It was very, very cold. She was almost too tired to think about the letter, "
    "and the letter was the only thing she could think about.\n"
    "The Ash Wardens' lanterns burned on the hill. Nobody slept. The door was opened "
    "by someone she did not know.")

SAMPLE_REPLY = """WHAT WORKS:
- The storm-to-pier movement is quick.

WHAT DOESN'T WORK:
- Mara's fear is told, not shown.

SUGGESTION 1:
Mara sprinted for the pier.
WHY: Faster verb.

SUGGESTION 2:
The pier. Mara ran for it, and Voss was already there.
WHY: Fragment adds urgency.

SUGGESTION 3:
She reached the pier with salt in her mouth; Voss had waited.
WHY: Sensory anchor.
"""


# ── Parent: run one child per size, then report ───────────────────────

def _screen_config(folder: Path, width: int, height: int) -> Path:
    path = folder / f"screen_{width}x{height}.json"
    path.write_text(json.dumps({"screens": [{
        "name": f"Harness {width}x{height}", "x": 0, "y": 0, "width": width, "height": height,
        "logicalDpi": 96, "dpr": 1}]}))
    return path


def _tag(width: int, height: int, scale: float) -> str:
    return f"{width}x{height}" + ("" if scale == 1.0 else f"@{int(scale * 100)}")


def run(names: List[str], out: Path, sizes=SIZES) -> Dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="harness_home_"))
    results: Dict[str, Any] = {}
    for width, height, scale in sizes:
        tag = _tag(width, height, scale)
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = f"offscreen:configfile={_screen_config(out, width, height)}"
        env["HOME"] = str(home)                       # never the writer's real settings
        env.pop("QT_SCALE_FACTOR", None)
        if scale != 1.0:
            env["QT_SCALE_FACTOR"] = str(scale)
        child_out = out / f"_{tag}.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--child", tag,
               "--out", str(out), "--child-report", str(child_out),
               "--count" if (width, height, scale) == COUNT_AT else "--no-count", *names]
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
                              timeout=900)
        if child_out.exists():
            results[tag] = json.loads(child_out.read_text())
            child_out.unlink()
        else:
            results[tag] = {"_error": (proc.stderr or proc.stdout)[-2000:]}
    return results


def compare_counts(counts: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    """Rule 13: every count that rose above the baseline."""
    rises = []
    for name, now in counts.get("screens", {}).items():
        base = baseline.get("screens", {}).get(name)
        if not base:
            continue
        for key in ("buttons", "menu_items", "sections", "inner_tabs"):
            if now.get(key, 0) > base.get(key, 0):
                rises.append(f"{name}: {key} {base[key]} → {now[key]}")
    for key, value in counts.get("right_click", {}).items():
        base = baseline.get("right_click", {}).get(key)
        if base is not None and value > base:
            rises.append(f"right-click {key}: {base} → {value}")
    for key, value in counts.get("main_window", {}).items():
        base = baseline.get("main_window", {}).get(key)
        if base is not None and value > base:
            rises.append(f"main window {key}: {base} → {value}")
    return rises


def compare_images(old: Path, new: Path) -> Tuple[List[str], List[str]]:
    """(identical, different) image names present in both runs."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QImage
    same, different = [], []
    for img in sorted(new.glob("*.png")):
        before = old / img.name
        if not before.exists():
            continue
        a, b = QImage(str(before)), QImage(str(img))
        (same if a.size() == b.size() and a == b else different).append(img.name)
    return same, different


def summarise(results: Dict[str, Any], baseline: Dict[str, Any]) -> Tuple[List[str], bool]:
    lines, ok = [], True
    for tag, res in results.items():
        if "_error" in res:
            ok = False
            lines.append(f"{tag}: the run failed:\n{res['_error']}")
            continue
        for name, info in res.get("screens", {}).items():
            if "error" in info:
                ok = False
                lines.append(f"{tag} {name}: could not open: {info['error']}")
                continue
            for problem in info.get("problems", []):
                ok = False
                lines.append(f"{tag} {name}: {problem}")
    counts = next((r.get("counts") for r in results.values() if r.get("counts")), None)
    if counts:
        rises = compare_counts(counts, baseline)
        if rises:
            ok = False
            lines.append("Counts above the 0.2 baseline (rule 13):")
            lines.extend(f"  {r}" for r in rises)
    return lines, ok


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("screens", nargs="*", help="screen names (default: all)")
    ap.add_argument("--list", action="store_true", help="list the screens and stop")
    ap.add_argument("--out", help="folder for the images (default: a new scratch folder)")
    ap.add_argument("--compare", help="an earlier run's folder to compare images with")
    ap.add_argument("--menus", action="store_true",
                    help="also print the Write menus and right-click menus as counted")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--child-report", help=argparse.SUPPRESS)
    ap.add_argument("--count", dest="count", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-count", dest="count", action="store_false", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.list:
        for name, (_kind, about) in SCREENS.items():
            print(f"  {name:14} {about}")
        return 0
    names = args.screens or list(SCREENS)
    unknown = [n for n in names if n not in SCREENS]
    if unknown:
        print(f"Unknown screen(s): {', '.join(unknown)}. Use --list.")
        return 1
    if args.child:
        return child(args.child, names, Path(args.out), Path(args.child_report), args.count)

    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "writingaid-screens" / time.strftime("%Y%m%d_%H%M%S")
    started = time.time()
    results = run(names, out)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    (out / "report.json").write_text(json.dumps(results, indent=1))
    lines, ok = summarise(results, baseline)

    images = sorted(p.name for p in out.glob("*.png"))
    print(f"{len(images)} image(s) of {len(names)} screen(s) in {time.time() - started:.0f} s:")
    print(f"  {out}")
    counts = next((r.get("counts") for r in results.values() if r.get("counts")), None)
    if counts:
        print("Counts at 1440x900 (baseline in brackets; menu items grouped as decision 11 "
              "says, every item in braces):")
        for name, c in counts["screens"].items():
            b = baseline.get("screens", {}).get(name, {})
            print("  " + f"{name:14}" + "  ".join(
                f"{k} {c[k]}" + (f" ({b[k]})" if k in b else "")
                + (f" {{{c['menu_items_itemised']}}}" if k == "menu_items"
                   and "menu_items_itemised" in c else "") for k in
                ("buttons", "menu_items", "sections", "inner_tabs"))
                + ("  — retired" if SCREENS.get(name, ("",))[0] == "retired" else ""))
        for key, value in counts.get("main_window", {}).items():
            print(f"  main window {key}: {value} ({baseline.get('main_window', {}).get(key, '?')})")
        every = counts.get("right_click_itemised", {})
        for key, value in counts.get("right_click", {}).items():
            print(f"  right-click {key}: {value} ({baseline.get('right_click', {}).get(key, '?')})"
                  + (f" {{{every[key]}}}" if key in every else ""))
        if args.menus:
            for head, tree in counts.get("menus", {}).items():
                print(f"  {head}")
                for line in tree:
                    print(f"      {line}")
    for name in names:
        if name in RETIRED:
            print(f"  {name}: retired ({RETIRED[name]})")
    if args.compare:
        same, different = compare_images(Path(args.compare), out)
        print(f"Compared with {args.compare}: {len(same)} identical, {len(different)} different")
        for name in different:
            print(f"  DIFFERENT {name}")
        if different:
            ok = False
    for line in lines:
        print(line)
    print("RESULT: " + ("no problems" if ok else "problems found"))
    return 0 if ok else 1


# ── Child: one size, every screen ──────────────────────────────────────

def child(tag: str, names: List[str], out: Path, report_path: Path, count: bool) -> int:
    sys.path.insert(0, str(ROOT))
    from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox

    app = QApplication(sys.argv[:1])
    try:                                      # draw with the app's own style sheet
        from src.ui.styles import get_modern_style
        app.setStyleSheet(get_modern_style())
    except Exception as e:
        print(f"[harness] app style sheet not applied: {e}")
    # Nothing may block, reach a model, or touch real stores.
    QDialog.exec = lambda self, *a, **k: 0
    for n in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    _isolate(Path(os.environ["HOME"]))

    report: Dict[str, Any] = {"screen": _screen_info(app), "screens": {}}
    project = _sample_project()
    for name in names:
        if SCREENS[name][0] == "retired":
            report["screens"][name] = {"retired": RETIRED.get(name, "")}
            continue
        try:
            top, focus = _build(name, project)
            _settle(app)
            img = out / f"{name}_{tag}.png"
            top.grab().save(str(img))
            info = {"image": img.name, "window": [top.width(), top.height()],
                    "problems": _check(top, focus, app)}
            report["screens"][name] = info
            top.close()
            top.deleteLater()
            _settle(app)
        except Exception as e:                    # report it and carry on with the rest
            import traceback
            report["screens"][name] = {"error": f"{type(e).__name__}: {e}",
                                       "trace": traceback.format_exc()[-1500:]}
    if count:
        report["counts"] = _counts(names, _count_project(), app)
    report_path.write_text(json.dumps(report, indent=1))
    sys.stdout.flush()
    os._exit(0)


def _isolate(home: Path) -> None:
    import src.utils.proofing as pf
    pf.LanguageToolEngine.ensure_started = lambda self: False
    import src.ai.word_suggest as ws
    ws.get_llm = lambda: None
    import src.data.companion_state as cs
    cs.state_path = lambda project: home / "companion_state.json"
    import src.data.critique_history as ch
    ch.history_path = lambda project: home / "critique_history.json"
    import src.data.writing_habit as wh
    wh.habit_path = lambda: home / "writing_habit.json"
    try:
        from PyQt6.QtCore import QSettings
        import src.ui.ui_kit as kit
        kit._settings = lambda: QSettings(str(home / "window_geometry.ini"),
                                          QSettings.Format.IniFormat)
    except Exception:
        pass


def _screen_info(app) -> Dict[str, Any]:
    s = app.primaryScreen()
    g = s.availableGeometry()
    return {"available": [g.width(), g.height()], "scale": float(os.environ.get("QT_SCALE_FACTOR", 1))}


def _settle(app, rounds: int = 8) -> None:
    from src.ui import background
    for _ in range(rounds):
        background.wait_all(10000)          # results arrive before the picture
        app.processEvents()


COUNT_TEXT = ("It was very cold. She walked slowly to the door and very quietly "
              "opened it. The wind was blowing. It was very, very cold outside.\n\n"
              "He said that he was going to go. She said nothing at all.")


def _count_project():
    """The project the 0.2 baseline was counted on: two chapters, no
    characters. Counts depend on content, so they must match it."""
    from src.models.project import Chapter, WriterProject
    p = WriterProject(name="count")
    for i in (1, 2):
        p.manuscript.chapters.append(Chapter(id=f"c{i}", number=i, title=f"Ch {i}",
                                             content=COUNT_TEXT))
    return p


def _sample_project():
    from src.models.project import Chapter, Character, WriterProject
    p = WriterProject(name="Sample")
    p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist",
                              personality="guarded", speaking_style="clipped"),
                    Character(id="v", name="Voss", character_type="minor", personality="pedantic")]
    for i in (1, 2):
        p.manuscript.chapters.append(Chapter(id=f"c{i}", number=i, title=f"Chapter {i}",
                                             content=SAMPLE_TEXT))
    return p


def _chapter_editor(project, size=None):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    _show_full(ed)
    return ed


def _show_full(widget) -> None:
    """Show ``widget`` as a window filling the simulated screen."""
    from PyQt6.QtWidgets import QApplication
    avail = QApplication.primaryScreen().availableGeometry()
    widget.resize(avail.width(), avail.height())
    widget.move(avail.topLeft())
    widget.show()


def _build(name: str, project):
    """(window to draw, widget to count in) for a screen."""
    kind = SCREENS[name][0]
    if name == "suggestions":
        return _suggestions(project)
    if name in IMPROVE_SCREENS:
        return _improve(project, IMPROVE_SCREENS[name])
    if name in HABIT_SCREENS:
        return _habit_screen(name, project)
    if name in ANALYSIS_SCREENS:
        return _analysis_screen(name, project)
    if name in CHARACTER_SCREENS:
        return _character_screen(name, project)
    if name in VOICE_SCREENS:
        return _voice_screen(name, project)
    if name in PACKAGE_SCREENS:
        return _package_screen(project)
    if name in TAB_SCREENS:
        win = _main_tabs(project, grouped=name == "main_tabs")
        _show_full(win)
        return win, win.tab_widget
    if kind == "panel":
        ed = _chapter_editor(project)
        panel = PANELS[name](ed)
        ed._show_right_panel(panel)
        return ed, panel
    widget = _page(name, project)
    _show_full(widget)
    return widget, widget


def _habit_screen(name: str, project):
    """The Companion with goals set, or the 12-week window, drawn on a
    sample record in a file of its own; the goals and the file are put
    back afterwards so the other screens draw as before."""
    import json as _json
    from datetime import date, timedelta
    import src.data.writing_habit as wh
    today = date.today()
    days = {}
    for back in range(0, 80):
        d = today - timedelta(days=back)
        if back in (5, 6, 12, 19, 20, 33, 47, 48, 61) or d.weekday() == 6 and back > 7:
            continue
        added = 640 if back == 0 else (back * 137) % 1900
        cut = (back * 53) % 400
        days[d.isoformat()] = {"sample": {
            "name": "Sample", "path": "", "added": added, "cut": cut, "moved": 0,
            "minutes": 20 + back % 50,
            "chapters": {"c1": {"title": "Chapter 1", "added": added, "cut": cut, "moved": 0}}}}
    home = Path(os.environ["HOME"])
    sample = home / "writing_habit_sample.json"
    sample.write_text(_json.dumps({"format_version": 1, "days": days, "folded": {}, "last": {}}))
    old_path, old_goals = wh.habit_path, wh.goals
    wh.habit_path, wh.goals = (lambda: sample), (lambda: (1000, 5000))
    try:
        if name == "habit":
            from src.ui.habit_view import HabitWindow
            win = HabitWindow(None, today=today)
            win.show()
            return win, win
        ed = _chapter_editor(project)
        ed._show_right_panel(ed.companion.panel)
        return ed, ed.companion.panel
    finally:
        wh.habit_path, wh.goals = old_path, old_goals


SAMPLE_PROSE_REPLY = """## Tone
Tense and foreboding. “The storm broke at dusk” opens on threat, and “Nobody slept” closes the scene on dread.

## Style
Short, plain sentences with little ornament; the rhythm loosens in “She was almost too tired to think about the letter”.

## Voice
Close third person, restrained and watchful.

## Alignment with Project Targets
- **Tone:** Strong Match. The dread the profile asks for is on every line.
- **Voice:** Partial Match. “It was very, very cold” drifts toward telling.

## Strengths
- The closing image, “The Ash Wardens' lanterns burned on the hill”, carries the mood.

## Areas to Watch
- Repeated intensifiers (“very, very”) could flatten the voice at book length."""


def _analysis_screen(name: str, project):
    """The Critique showing an Analyze ▾ entry's report (D.5): the prose
    analysis with a fixed sample reply (no model is run), or Writing hints
    with no model."""
    from src.ai import analysis_reports as ar
    from src.ai.chapter_analysis_agent import CritiqueOrchestrator
    from src.ai.critique_parts import run_in_parts
    from src.ui import analysis_menu
    from src.ui.grader_widget import GraderWidget

    class SampleReply:                     # a fixed answer: no model is reached
        model = "sample"

        def generate_text(self, prompt, system_prompt="", **kw):
            return SAMPLE_PROSE_REPLY

    key = {"critique_analysis": "prose", "critique_character_check": "characters"}.get(name,
                                                                                       "hints")
    llm = SampleReply() if key == "prose" else None
    if key == "characters":
        project = _character_project()
    g = GraderWidget()
    g.set_project(project)
    at = 8 if key == "characters" else 0      # Tobin back after five chapters; Mara formal
    chapter = project.manuscript.chapters[at]
    chapters = [{"title": chapter.title, "text": chapter.content, "index": at, "id": chapter.id}]
    kinds = ar.ITEMS[key][1]
    report = run_in_parts(CritiqueOrchestrator(primary_llm=llm, project=project), chapters,
                          kinds, "default", "", extra={"run_kind": "analysis:" + key})
    report.run_kind = "analysis:" + key
    g._on_critique_finished(report)
    _show_full(g)
    analysis_menu._show_result(g, kinds[0])
    return g, g


def _character_project():
    """Twelve chapters: Tobin away for five of them, Mara formal in one (P.8)."""
    from src.models.project import Chapter, Character, WriterProject
    p = WriterProject(name="Sample book")
    p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist",
                              personality="guarded", speaking_style="clipped, casual"),
                    Character(id="t", name="Tobin", character_type="supporting")]
    usual = ('Mara looked at the harbour. "I don\'t know where it\'s gone," Mara said.\n'
             '"We\'ll look again when it\'s light, won\'t we?" Mara said.\n'
             '"It isn\'t far. I\'m sure it\'s past the rocks," Mara said.\n'
             '"Don\'t wait for me," Mara said.\n"I\'ll get the lamp," Mara said.')
    formal = ('Mara looked at the harbour. "I shall not go," Mara said.\n'
              '"Indeed, I do not know where it is," Mara said.\n"It is not possible," Mara said.\n'
              '"We shall see what the morning brings," Mara said.\n"I do not wait," Mara said.')
    for i in range(12):
        text = formal if i == 8 else usual
        if not 3 <= i <= 7:
            text += '\n\nTobin came in from the rain. "Go," Tobin said. "Now."'
        p.manuscript.chapters.append(Chapter(id=f"b{i + 1}", number=i + 1,
                                             title=f"Chapter {i + 1}", content=text))
    return p


def _package_screen(project):
    """Publish ▸ Publishing with 📦 Submission package chosen, on a sample
    plan (9.3). No model: the synopsis is the filled-in template. Its
    drafts file goes under the scratch HOME (the sample is never saved)."""
    from src.models.project import Character, PlotEvent
    from src.ui.agent_manager_widget import AgentManagerWidget
    project = project.model_copy(deep=True)
    project.manuscript.title = "The Pier"
    project.prose_profile.genre = "gothic"
    if not project.characters:                  # the count project has none
        project.characters.append(Character(id="m", name="Mara Venn",
                                            character_type="protagonist"))
    hero = project.characters[0]
    hero.want, hero.need = "to keep her brother out of the fire", "Letting go is not betrayal."
    project.characters.append(Character(id="a", name="Tobin", character_type="antagonist"))
    project.story_planning.main_plot = ("A harbour pilot learns the pier is rigged to burn, "
                                        "and that her brother lit the fuse.")
    project.story_planning.freytag_pyramid.events = [
        PlotEvent(id=str(i), title=t, description=d, stage=s) for i, (t, d, s) in enumerate([
            ("Letter", "Mara finds her brother's letter in the tide box.", "exposition"),
            ("Debt", "Tobin calls in the debt and names the night.", "rising_action"),
            ("Fire", "The pier burns with Mara on it.", "climax"),
            ("Dawn", "Mara rows her brother out past the breakwater.", "resolution")])]
    w = AgentManagerWidget()
    w.set_project(project)
    w.load_data(project.agent_contacts)
    w.agent_list.setCurrentRow(0)
    _show_full(w)
    return w, w


def _character_screen(name: str, project):
    """Story ▸ Characters with Tobin open and Across the book open (P.8)."""
    from src.ui import character_book_section
    from src.ui.characters_widget import CharactersWidget
    project = _character_project()
    w = CharactersWidget()
    w.set_project(project)
    w.load_data(project.characters)
    w.character_list.setCurrentRow(1)
    page = w.current_character_widget
    section = page.across_book
    section.set_open(True)
    character_book_section.refresh(section, sync=True)
    _show_full(w)
    scroll = page.findChild(__import__("PyQt6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)
    if scroll is not None:
        scroll.ensureWidgetVisible(section, 0, 0)
        scroll.verticalScrollBar().setValue(section.y() - 8)
    return w, w


def _voice_screen(name: str, project):
    """Browse rows… showing rated rewrites by voice: three projects in two
    voices, a narrator, one project kept to itself, one still unsorted, and
    a suggestion waiting (V.5). Ratings and groups in a folder of their own."""
    import random
    from src.data import rephrase_database as rd
    from src.data import ratings_privacy, voice_groups_store as vgs
    from src.ai import voice_groups as vg
    from src.data import voice_ratings as vr
    from src.ui.training_tool_window import _CorpusBrowserDialog
    folder = Path(tempfile.mkdtemp(prefix="voice_ratings_"))
    rd.DEFAULT_DB_PATH = folder / "rephrase_history.db"
    vgs.groups_path = lambda: folder / "voice_groups.json"
    db = rd.RephraseDatabase(rd.DEFAULT_DB_PATH)
    rng = random.Random(3)
    things = ["door", "rain", "street", "window", "lamp", "dog", "coat", "wall"]

    def first(r):
        return " ".join(f"I see the {r.choice(things)}{r.choice(['', ' again', ' and stop'])}. "
                        + ("It is cold. " if r.random() < 0.5 else "") for _ in range(r.randint(14, 20)))

    def third(r):
        return " ".join(f"He had wandered {r.choice(['slowly', 'idly', 'warily'])} past the "
                        f"{r.choice(things)} towards the old harbour, where the boats had lain for "
                        "years" + r.choice(["", ", and thought of the coat his father had left"]) + "."
                        for _ in range(r.randint(5, 8)))
    paths = {n: str(folder / f"{n}.writerproj") for n in ("Teller County", "Born in Blood", "Saltmarsh", "Tempest")}
    plan = [("Teller County", "", first, 40), ("Teller County", "Mara", first, 34),
            ("Born in Blood", "", third, 38), ("Saltmarsh", "", third, 48), ("Tempest", "", third, 6)]
    for proj, narrator, make, n in plan:
        for i in range(n):
            db.log(f"The passage {i} as written.", f"A rewrite of passage {i} in {proj}'s voice.",
                   source_type="rephrase", surrounding_before=make(rng), character_name=narrator,
                   project_path=paths[proj], rating=rng.choice(["good", "excellent", "poor"]))
    vgs.run_check(db)
    vr.new_group(db, "Harbour books", [vg.source_key(paths["Born in Blood"])])
    ratings_privacy.set_private(paths["Born in Blood"], True)
    dlg = _CorpusBrowserDialog(rd.DEFAULT_DB_PATH)
    from PyQt6.QtWidgets import QApplication
    avail = QApplication.primaryScreen().availableGeometry()
    dlg.resize(min(1100, avail.width() - 40), min(760, avail.height() - 60))
    dlg.show()
    dlg.source_combo.setCurrentIndex(dlg.source_combo.findData("__by_voice__"))
    view = dlg.voice_groups_view
    src = view._find_item(("source", vg.source_key(paths["Tempest"])))
    if src is not None:
        src.parent().setExpanded(True)
        src.setExpanded(True)
        if src.childCount():
            src.child(1).setSelected(True)
    return dlg, dlg


def _main_tabs(project, grouped: bool = True, placeholders: bool = False):
    """The main window's tab area as the main window builds it: the ten
    screens added in their old order with their labels, then grouped by
    ``screen_groups`` (or left as ten). ``placeholders`` uses empty pages
    (for counting tabs, which do not depend on what a page holds)."""
    from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
    from src.ui import screen_groups as sg
    from src.ui.styles import get_icon
    labels = {"write": f"{get_icon('manuscript')} Write", "plot": f"{get_icon('story')} Plot",
              "characters": f"{get_icon('characters')} Characters",
              "world": f"{get_icon('worldbuilding')} World", "attributions": "📚 Attributions",
              "visuals": f"{get_icon('images')} Visuals", "prose_profile": "🎯 Prose Profile",
              "critique": f"{get_icon('grader')} Critique", "video_studio": "🎬 Video Studio",
              "publishing": f"{get_icon('agents')} Publishing"}
    win = QMainWindow()
    win.tab_widget = QTabWidget()
    win.tab_widget.setDocumentMode(True)
    win.tab_widget.setMovable(True)
    win.setCentralWidget(win.tab_widget)
    for key, attr in sg.OLD_TABS:
        page = QWidget() if placeholders else _page(key, project)
        setattr(win, attr, page)
        win.tab_widget.addTab(page, labels[key])
    previous = sg._get(sg.ARRANGEMENT_KEY, "groups")
    sg._set(sg.ARRANGEMENT_KEY, "groups" if grouped else "ten")
    try:
        sg.install(win)
    finally:
        sg._set(sg.ARRANGEMENT_KEY, previous)
    if grouped:
        sg.show(win, win.characters_widget)          # a group's inner tabs, drawn
    return win


def _suggestions(project):
    from src.ai import passage_critique as pc
    from src.ui.passage_critique_dialog import PassageCritiqueDialog
    chapter = project.manuscript.chapters[0]
    sel = (SAMPLE_TEXT.index("ran to the pier"), SAMPLE_TEXT.index("ran to the pier") + 15)
    s, e = pc.expand_to_sentences(SAMPLE_TEXT, *sel)

    class _Reply:
        def generate_text(self, *a, **k):
            return SAMPLE_REPLY

    factory = None
    try:
        from src.ui.passage_critique_dialog import SuggestionWorker

        class _Now(SuggestionWorker):
            def __init__(self, *a):
                super().__init__(*a, llm_factory=lambda: (_Reply(), ""),
                                 search_factory=lambda p: None)

            def start(self):
                self.run()
        factory = _Now
    except Exception:
        factory = None                      # still drawn, without a reply
    kwargs = {"selection": sel}
    if factory is not None:
        kwargs["worker_factory"] = factory
    dlg = PassageCritiqueDialog(SAMPLE_TEXT, s, e, project, chapter, **kwargs)
    dlg.show()                              # a dialog opens at its own size
    return dlg, dlg


def _improve(project, tab: str):
    """The Improve window (D.2b) on a tab: Suggestions and Critique with the
    sample reply; Expand on its own, as the word scan with no model."""
    from src.ai import passage_critique as pc
    from src.ui.improve_window import ImproveWindow
    from src.ui.overdescription_panel import ReviewWorker
    from src.ui.passage_critique_dialog import SuggestionWorker
    chapter = project.manuscript.chapters[0]
    anchor = "ran to the pier" if tab != "expand" else "very, very cold"
    sel = (SAMPLE_TEXT.index(anchor), SAMPLE_TEXT.index(anchor) + len(anchor))
    s, e = pc.expand_to_sentences(SAMPLE_TEXT, *sel)
    if tab == "expand":
        e = SAMPLE_TEXT.index("\n", e)                # the whole cold paragraph

    class _Reply:
        def generate_text(self, *a, **k):
            return SAMPLE_REPLY

    class _Now(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (_Reply(), ""),
                             search_factory=lambda p: None)

        def start(self):
            self.run()

    class _Scan(ReviewWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (None, "AI is off"))

        def start(self):
            self.run()

    from src.ui import ui_kit                         # drawn at its first-open size
    ui_kit._settings().remove("improve_window")       # on each screen size
    win = ImproveWindow(SAMPLE_TEXT, s, e, project, chapter, tab=tab,
                        selection=None if tab == "expand" else sel,
                        suggestion_worker=_Now, review_worker=_Scan,
                        rephrase_dialog=_sample_rephrase())
    if tab == "rephrase":
        from src.ai.rephrasing_agent import RephraseOption, RephraseResult
        win.tab_objects["rephrase"].dlg._on_generation_complete(RephraseResult(
            original="ran to the pier", model_used="sample", cost_estimate=0.0, options=[
                RephraseOption(t, st, "neutral", "sample") for t, st in (
                    ("raced for the pier", "concise"), ("ran down to the pier", "clearer"),
                    ("ran, lungs burning, to the pier", "elaborate"),
                    ("proceeded to the pier", "formal"))]))
    win.show()
    return win, win


def _sample_rephrase():
    """RephraseDialog with no model: no agent from settings, no scene
    summary (Rephrase uses the on-device model; the harness never runs one)."""
    from src.ai.rephrasing_agent import RephrasingAgent
    from src.ui.rephrase_dialog import RephraseDialog

    class _NoModel(RephraseDialog):
        def _init_agent(self):
            self.agent = RephrasingAgent(project=self.project)

        def _moment_llm(self):
            return None
    return _NoModel


def _page(name: str, project):
    if name == "write":
        from src.ui.manuscript_editor import ManuscriptEditor
        w = ManuscriptEditor()
        w.set_project(project)
        w.load_manuscript(project.manuscript)
        w.open_chapter("c1")
        return w
    simple = {
        "plot": ("src.ui.story_planning_widget", "StoryPlanningWidget", "story_planning"),
        "characters": ("src.ui.characters_widget", "CharactersWidget", "characters"),
        "world": ("src.ui.comprehensive_worldbuilding_widget", "ComprehensiveWorldBuildingWidget",
                  "worldbuilding"),
        "attributions": ("src.ui.attributions_tab", "AttributionsTab", None),
        "visuals": ("src.ui.image_generator_widget", "ImageGeneratorWidget", "generated_images"),
        "prose_profile": ("src.ui.prose_profile_widget", "ProseProfileWidget", "prose_profile"),
        "critique": ("src.ui.grader_widget", "GraderWidget", None),
        "video_studio": ("src.ui.video_studio.studio_widget", "VideoStudioWidget", None),
        "publishing": ("src.ui.agent_manager_widget", "AgentManagerWidget", "agent_contacts"),
        "assistant": ("src.ui.chat_widget", "ChatWidget", None),
        "outline": ("src.ui.outline_panel", "OutlinePanel", None),
    }
    module, cls, data = simple[name]
    w = getattr(__import__(module, fromlist=[cls]), cls)()
    if hasattr(w, "set_project"):
        try:
            w.set_project(project)
        except Exception:
            pass
    if data and hasattr(w, "load_data"):
        w.load_data(getattr(project, data))
    if name == "attributions" and hasattr(w, "set_manuscript"):
        w.set_manuscript(project.manuscript)
    return w


# ── Checks ─────────────────────────────────────────────────────────────

def _check(top, focus, app) -> List[str]:
    """Rule 12 problems in one drawn screen."""
    from PyQt6.QtWidgets import (
        QAbstractItemView, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
        QTextEdit, QToolButton,
    )
    from PyQt6.QtWidgets import QHeaderView
    problems = []
    avail = app.primaryScreen().availableGeometry()
    # A window opens no larger than its screen; a page (tab or panel) must
    # fit in it at its smallest.
    need = top.size().expandedTo(top.minimumSizeHint()).expandedTo(top.minimumSize())
    if need.width() > avail.width() or need.height() > avail.height():
        problems.append(f"needs at least {need.width()}×{need.height()}, more than the "
                        f"screen ({avail.width()}×{avail.height()})")
    one_line = (QLabel, QPushButton, QToolButton, QLineEdit, QComboBox, QHeaderView)
    areas = (QTextEdit, QPlainTextEdit, QAbstractItemView)
    squeezed = []
    for w in focus.findChildren((*one_line, *areas)):
        if not w.isVisibleTo(top) or w.width() <= 0:
            continue
        if isinstance(w, one_line):
            text = w.text() if hasattr(w, "text") and callable(w.text) else "x"
            if isinstance(w, QLabel) and (not text or w.pixmap() is not None and not w.pixmap().isNull()):
                continue
            # Its own smallest readable height (rich text and small print
            # included), never more than one line of its font.
            hint = w.minimumSizeHint().height()
            need = min(w.fontMetrics().height(), hint) if hint > 0 else w.fontMetrics().height()
        else:
            need = 2 * w.fontMetrics().lineSpacing()
        if w.height() < need:
            label = (getattr(w, "text", lambda: "")() if isinstance(w, one_line) else "") or w.objectName()
            squeezed.append(f"{type(w).__name__} “{str(label)[:30]}” {w.height()}px < {need}px")
    # A button narrower than its label needs shows it cut off, or blank.
    narrow = []
    for b in focus.findChildren((QPushButton, QToolButton)):
        if not b.isVisibleTo(top) or b.width() <= 0 or not (b.text() or "").strip():
            continue
        need = b.minimumSizeHint().width()
        if need > 0 and b.width() + 2 < need:
            narrow.append(f"“{b.text()[:20]}” {b.width()}px < {need}px")
    if narrow:
        problems.append(f"{len(narrow)} button(s) too narrow for their label: "
                        + "; ".join(narrow[:6]) + (" …" if len(narrow) > 6 else ""))
    if squeezed:
        problems.append(f"{len(squeezed)} widget(s) below a readable height: "
                        + "; ".join(squeezed[:6]) + (" …" if len(squeezed) > 6 else ""))
    return problems


# ── Counts (rule 13) ───────────────────────────────────────────────────

def grouped(title: str) -> bool:
    """Is a menu with this title (or a menu button with this text) one
    closely related group, counted as one entry (decision 11)?"""
    title = (title or "").replace("&&", "&").strip()
    return any(title.startswith(p) for p in GROUPED_MENUS)


def _menu_items(menu, itemised: bool = False) -> int:
    """Entries in ``menu``. A grouped submenu counts as one, unless
    ``itemised`` (the count before decision 11: every item)."""
    n = 0
    for a in menu.actions():
        if a.isSeparator() or not a.isVisible():
            continue
        sub = a.menu()
        if sub is None:
            n += 1
        elif not itemised and grouped(sub.title()):
            n += 1
        else:
            n += _menu_items(sub, itemised)
    return n


def _button_menu_items(button, itemised: bool = False) -> int:
    if not itemised and grouped(button.text()):
        return 1
    return _menu_items(button.menu(), itemised)


def _tree(menu, indent: str = "") -> List[str]:
    """The menu as lines, each grouped menu marked "= 1" (``--menus``)."""
    lines = []
    for a in menu.actions():
        if a.isSeparator() or not a.isVisible():
            continue
        sub = a.menu()
        text = a.text().replace("&&", "&")
        if sub is None:
            lines.append(f"{indent}{text}")
        elif grouped(sub.title()):
            lines.append(f"{indent}{text} ▸  = 1 ({_menu_items(sub, True)} items)")
        else:
            lines.append(f"{indent}{text} ▸")
            lines.extend(_tree(sub, indent + "    "))
    return lines


def count_widget(top) -> Dict[str, int]:
    """Visible buttons, items behind menu buttons, sections and inner tabs."""
    from PyQt6.QtWidgets import QGroupBox, QPushButton, QTabBar, QTabWidget, QToolBox, QToolButton
    from src.ui.ui_kit import CollapsibleSection

    def vis(w):
        return w.isVisibleTo(top)
    buttons = [b for b in top.findChildren((QPushButton, QToolButton))
               if vis(b) and (b.text().strip() or not b.icon().isNull())]
    with_menu = [b for b in buttons if isinstance(b, QToolButton) and b.menu() is not None]
    menu_items = sum(_button_menu_items(b) for b in with_menu)
    itemised = sum(_button_menu_items(b, itemised=True) for b in with_menu)
    sections = ([s for s in top.findChildren(CollapsibleSection) if vis(s)]
                + [g for g in top.findChildren(QGroupBox) if vis(g)])
    toolbox = sum(t.count() for t in top.findChildren(QToolBox) if vis(t))
    tabs = sum(t.count() for t in top.findChildren(QTabWidget) if vis(t))
    tabs += sum(b.count() for b in top.findChildren(QTabBar)
                if vis(b) and not isinstance(b.parent(), QTabWidget))
    return {"buttons": len(buttons), "menu_items": menu_items,
            "sections": len(sections) + toolbox, "inner_tabs": tabs,
            "menu_items_itemised": itemised}


def _write_menus(top, out: Dict[str, Any]) -> None:
    """The Write screen's menu buttons as trees, for ``--menus``."""
    from PyQt6.QtWidgets import QToolButton
    for b in top.findChildren(QToolButton):
        if b.isVisibleTo(top) and b.menu() is not None:
            head = f"write: {b.text().replace('&&', '&')}"
            out.setdefault("menus", {})[head] = (
                [f"= 1 ({_menu_items(b.menu(), True)} items)"] if grouped(b.text())
                else _tree(b.menu()))


def _counts(names: List[str], project, app) -> Dict[str, Any]:
    from PyQt6.QtWidgets import QMenu
    out: Dict[str, Any] = {"screens": {}, "right_click": {}}
    for name in names:
        if name in IMPROVE_SCREENS or name in PACKAGE_SCREENS:  # windows of their own
            try:
                top, focus = _build(name, project)
                _settle(app)
                out["screens"][name] = count_widget(focus)
                top.close()
            except Exception as e:
                out["screens"][name] = {"error": str(e)[:200]}
            continue
        if name == "suggestions" or name in HABIT_SCREENS or name in ANALYSIS_SCREENS \
                or name in CHARACTER_SCREENS or name in VOICE_SCREENS:
            continue                                    # not in the 0.2 baseline
        if name in TAB_SCREENS:
            if name == "main_tabs":                     # the baseline's top_level_tabs
                win = _main_tabs(project, grouped=True, placeholders=True)
                out["main_window"] = {"top_level_tabs": win.tab_widget.count()}
                win.close()
            continue
        try:
            if SCREENS[name][0] == "retired":
                out["screens"][name] = {"buttons": 0, "menu_items": 0, "sections": 0,
                                        "inner_tabs": 0, "menu_items_itemised": 0}
                continue
            if SCREENS[name][0] == "panel":
                from src.ui.manuscript_editor import ChapterEditor
                ed = ChapterEditor(project.manuscript.chapters[0], project=project)
                _show_full(ed)
                panel = PANELS[name](ed)
                ed._show_right_panel(panel)
                _settle(app)
                panel.resize(panel.size())
                out["screens"][name] = count_widget(panel)
                ed.close()
            else:
                w = _page(name, project)
                _show_full(w)
                _settle(app)
                out["screens"][name] = count_widget(w)
                if name == "write":
                    _write_menus(w, out)
                w.close()
        except Exception as e:
            out["screens"][name] = {"error": str(e)[:200]}
        _settle(app, 2)
    out["screens"] = {k: v for k, v in out["screens"].items() if "error" not in v}

    # Right-click in the chapter text, without and with a selection.
    try:
        from src.ui.manuscript_editor import ChapterEditor
        ed = ChapterEditor(project.manuscript.chapters[0], project=project)
        _show_full(ed)
        _settle(app)
        captured = []
        original_exec = QMenu.exec
        QMenu.exec = lambda self, *a, **k: captured.append(self)
        try:
            cur = ed.editor.textCursor()
            cur.setPosition(9)
            ed.editor.setTextCursor(cur)
            ed._show_context_menu(ed.editor.cursorRect().center())
            cur.setPosition(0)
            cur.setPosition(40, cur.MoveMode.KeepAnchor)
            ed.editor.setTextCursor(cur)
            ed._show_context_menu(ed.editor.cursorRect().center())
        finally:
            QMenu.exec = original_exec
        if len(captured) == 2:
            out["right_click"] = {"text_no_selection": _menu_items(captured[0]),
                                  "text_selection": _menu_items(captured[1])}
            out["right_click_itemised"] = {
                "text_no_selection": _menu_items(captured[0], itemised=True),
                "text_selection": _menu_items(captured[1], itemised=True)}
            out.setdefault("menus", {}).update({
                "right-click, no selection": _tree(captured[0]),
                "right-click, with a selection": _tree(captured[1])})
        ed.close()
    except Exception as e:
        out["right_click_error"] = str(e)[:200]
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
