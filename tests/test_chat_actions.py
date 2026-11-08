"""AI chat actions: overall critique, redo chapter outline, edit the story
outline and worldbuilding through conversation."""

import os
import time
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chat_actions as ca
from src.models.project import PlotEvent, StoryPlanning, Subplot


# ── Intent detection ──────────────────────────────────────────────

@pytest.mark.parametrize("msg,expected", [
    ("Give me an overall critique", {"kind": "critique", "scope": "chapter"}),
    ("can you critique this chapter?", {"kind": "critique", "scope": "chapter"}),
    ("Run a full critique of the whole book", {"kind": "critique", "scope": "manuscript"}),
    ("Review my manuscript please", {"kind": "critique", "scope": "manuscript"}),
    ("critique", {"kind": "critique", "scope": "chapter"}),
    ("Redo the chapter outline", {"kind": "chapter_outline", "source": "text"}),
    ("regenerate this chapter's outline from the plan", {"kind": "chapter_outline", "source": "plan"}),
    ("rebuild the outline", {"kind": "chapter_outline", "source": "text"}),
    ("Change the main plot to: Mara must find the Gull before the Wardens burn the harbor.",
     {"kind": "story_outline",
      "data": {"main_plot": "Mara must find the Gull before the Wardens burn the harbor."}}),
    ("set the climax to \"The harbor burns and Mara chooses the sea.\"",
     {"kind": "story_outline", "data": {"climax": "The harbor burns and Mara chooses the sea."}}),
])
def test_detect_intent(msg, expected):
    assert ca.detect_intent(msg) == expected


@pytest.mark.parametrize("msg", [
    "What do you think of Mara's motivation?",
    "Help me edit the story outline so the climax lands in act 3",   # model handles via tags
    "Tell me about the Ash Wardens",
    "Is the pacing too slow in the opening?",
    "Rewrite this paragraph to be tenser",
])
def test_no_intent_for_ordinary_conversation(msg):
    assert ca.detect_intent(msg) is None


# ── Action tags ───────────────────────────────────────────────────

def test_extract_actions_json_and_self_closing():
    reply = ('Sure — tightening act 2.\n<update_plot_event>{"title": "The Betrayal", '
             '"updates": {"act": 2,}}</update_plot_event>\n<run_critique scope="manuscript"/>')
    actions, cleaned = ca.extract_actions(reply)
    assert actions == [("update_plot_event", {"title": "The Betrayal", "updates": {"act": 2}}),
                       ("run_critique", {"scope": "manuscript"})]
    assert cleaned == "Sure — tightening act 2."


def _sp():
    sp = StoryPlanning(main_plot="Old plot")
    sp.freytag_pyramid.events = [
        PlotEvent(id="e1", title="The Betrayal", description="Tobin sells the map."),
        PlotEvent(id="e2", title="Storm at Greywater"),
    ]
    sp.subplots = [Subplot(id="s1", title="The Missing Gull", description="Where did it go?")]
    return sp


def test_story_outline_edits():
    sp = _sp()
    assert ca.apply_story_outline_update(sp, {"main_plot": "New plot", "climax": "The flood",
                                              "rising": "Pressure builds"}) \
        == ["main plot", "climax", "rising action"]
    assert sp.main_plot == "New plot" and sp.freytag_pyramid.climax == "The flood"
    r = ca.update_plot_event(sp, {"title": "the betrayal",
                                  "updates": {"stage": "climax", "intensity": 140, "act": "3"}})
    ev = sp.freytag_pyramid.events[0]
    assert r and ev.stage == "climax" and ev.intensity == 100 and ev.act == 3
    assert ca.update_plot_event(sp, {"title": "Storm at Greywatr",          # fuzzy
                                     "updates": {"description": "It hits."}})
    assert ca.delete_plot_event(sp, {"title": "Storm at Greywater"}) == "Storm at Greywater"
    assert [e.title for e in sp.freytag_pyramid.events] == ["The Betrayal"]
    assert ca.update_subplot(sp, {"title": "The Missing Gull", "updates": {"status": "resolved"}})
    assert sp.subplots[0].status == "resolved"
    assert ca.update_plot_event(sp, {"title": "Nope", "updates": {"act": 1}}) is None


def test_update_worldbuilding_element():
    import tests.test_critique_canon_reports as canon
    proj = canon._project()
    r = ca.update_element(proj, {
        "element_type": "faction", "name": "Ash Wardens",
        "set": {"description": "A zealous order that rules Greywater."},
        "append": {"description": "They fear the sea."},
        "rename": "Ash Wardens of Greywater"})
    f = proj.worldbuilding.factions[0]
    assert f.name == "Ash Wardens of Greywater"
    assert f.description == "A zealous order that rules Greywater. They fear the sea."
    assert "renamed from Ash Wardens" in r
    assert ca.update_element(proj, {"element_type": "character", "name": "Mara",
                                    "set": {"fears": "fire"}}) and proj.characters[0].fears == "fire"
    assert ca.update_element(proj, {"element_type": "place", "name": "Atlantis",
                                    "set": {"description": "x"}}) is None


# ── Main-window handlers (with a stand-in window) ─────────────────

def _fake_window(project):
    from src.ui.main_window import MainWindow
    msgs, refreshed = [], []
    win = NS(current_project=project, chat_widget=NS(add_message=lambda who, m: msgs.append(m)),
             _refresh_story_planning_after_create=lambda: refreshed.append("story"),
             _refresh_project_widgets=lambda: refreshed.append("world"),
             _on_content_changed=lambda: refreshed.append("changed"),
             _chat_history=[], _compact_chat_history=lambda: None)
    for name in ("_apply_chat_actions", "_run_chat_intent", "_record_chat_turn",
                 "_on_chat_critique_done", "_chat_regenerate_chapter_outline",
                 "_start_chat_critique", "_chapters_for_links", "_current_chapter_id"):
        setattr(win, name, getattr(MainWindow, name).__get__(win))
    return win, msgs, refreshed


def test_apply_chat_actions_edits_and_defers():
    import tests.test_critique_canon_reports as canon
    proj = canon._project()
    proj.story_planning = _sp()
    win, msgs, refreshed = _fake_window(proj)
    actions, _ = ca.extract_actions(
        '<update_story_outline>{"main_plot": "Mara must leave Greywater."}</update_story_outline>'
        '<update_element>{"element_type": "place", "name": "Greywater", '
        '"set": {"description": "A drowning city."}}</update_element>'
        '<run_critique>{"scope": "chapter"}</run_critique>')
    notes, deferred = win._apply_chat_actions(actions)
    assert proj.story_planning.main_plot == "Mara must leave Greywater."
    assert proj.worldbuilding.places[0].description == "A drowning city."
    assert notes == ["Story outline updated: main plot", "Updated place: Greywater (description)"]
    assert deferred == [{"kind": "critique", "scope": "chapter"}]
    assert {"story", "world", "changed"} <= set(refreshed)


def test_dictated_story_outline_change_applies_verbatim():
    import tests.test_critique_canon_reports as canon
    proj = canon._project()
    proj.story_planning = _sp()
    win, msgs, refreshed = _fake_window(proj)
    msg = "Change the main plot to: Mara must find the Gull before the Wardens burn the harbor."
    assert win._run_chat_intent(ca.detect_intent(msg), msg)
    assert proj.story_planning.main_plot == ("Mara must find the Gull before the Wardens "
                                             "burn the harbor.")
    assert "now reads" in msgs[-1] and win._chat_history[0]["content"] == msg


def test_chat_outline_regeneration_uses_planner():
    import tests.test_critique_canon_reports as canon
    win, msgs, _ = _fake_window(canon._project())
    calls = []
    planner = NS(_populate_outline_from_text=lambda: calls.append("text") or True,
                 _generate_events=lambda: calls.append("plan") or True)
    ce = NS(planner_widget=planner, editor=NS(toPlainText=lambda: "Some prose."),
            chapter=NS(id="c1", title="The Pier"),
            right_panel=NS(setVisible=lambda v: None, setCurrentWidget=lambda w: None))
    win.manuscript_editor = NS(current_chapter_editor=ce)
    assert win._run_chat_intent({"kind": "chapter_outline", "source": "text"}, "redo the outline")
    assert calls == ["text"] and win._chat_outline_pending == "c1"
    planner._populate_outline_from_text = lambda: False          # writer cancelled
    win._run_chat_intent({"kind": "chapter_outline", "source": "text"}, "redo")
    assert win._chat_outline_pending is None and "left unchanged" in msgs[-1]


# ── End to end: chat critique through the Critique tab ────────────

def test_chat_critique_runs_reports_and_promise_check(monkeypatch):
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    import tests.test_critique_canon_reports as canon
    from src.models.project import StoryPromise
    app = QApplication.instance() or QApplication([])
    import src.ai.task_llm as tl
    llm = canon.LocalLLM()
    orig = llm.generate_text

    def gen(prompt, system=None, **kw):
        if "ensuring consistency in storytelling" in (system or ""):   # PromiseChecker
            return "OVERALL_ADHERENCE: needs_attention\nSUMMARY: The Gull promise stalls.\n"
        return orig(prompt, system, **kw)
    llm.generate_text = gen
    monkeypatch.setattr(tl, "build_critique_llm", lambda spec="": llm)

    from src.ui.grader_widget import GraderWidget
    proj = canon._project()
    proj.story_planning = StoryPlanning()
    proj.story_planning.promises = [StoryPromise(id="p1", promise_type="plot",
                                                 title="The Gull returns")]
    proj.project_path = ""
    proj.manuscript.chapters[0].content = canon.CHAPTER
    grader = GraderWidget()
    grader.set_project(proj)
    grader.set_current_chapter(canon.CHAPTER, "Chapter 2")

    win, msgs, _ = _fake_window(proj)
    win.grader_widget = grader
    win.statusBar = lambda: NS(showMessage=lambda *a: None)
    win.manuscript_editor = NS(current_chapter_editor=NS(
        save_to_model=lambda: None, editor=NS(toPlainText=lambda: canon.CHAPTER),
        chapter=NS(title="Chapter 2", id="ch2")))
    assert win._run_chat_intent({"kind": "critique", "scope": "chapter"}, "overall critique")
    assert "Running an overall critique" in msgs[-1]
    grader._worker.wait(60000)
    end = time.time() + 10
    while len(msgs) < 2 and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    out = msgs[-1]
    assert out.startswith("**Overall critique**")
    assert "wa-goto:" in out                                       # findings link to the text
    assert "Characters" in out and "Worldbuilding" in out and "Grammar" in out
    assert "Promise & consistency check" in out
    assert "ten years ago" in out                                  # worldbuilding drift surfaced
    assert win._chat_history[-1]["content"].startswith("[Overall critique results]")
    assert grader._last_report.promise_results                     # full report in the tab
