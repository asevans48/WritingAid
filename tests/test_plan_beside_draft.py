"""7.3: the draft beside the plan (no-model tier), in the Critique's
scene outline, with its one small chart."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import plan_match as pm
from src.ai import reverse_outline as ro
from src.models.project import Chapter, Manuscript, StoryEvent, WriterProject

# A realistic chapter: six scenes. Scene 4 (the lighthouse keeper's
# memory) is not in the plan; the planned "Tobin burns the letter" has no
# scene. The other five planned events each have one scene.
SCENES = [
    "Rain came in off the harbor in long grey sheets. Mara stood under the awning of the "
    "fish market with her collar up, watching the ferry nose against the pilings. She had "
    "not been back to Kestrel Bay in eleven years, and the town looked smaller than she "
    "remembered, as if the sea had been chewing at it. “You’re late,” said a voice behind "
    "her. She did not turn. “The ferry was late,” she said.",
    "Her aunt’s house smelled of camphor and old paper. Mara set her bag down in the hall "
    "and went room to room, touching nothing. In the study the desk drawers had been pulled "
    "out and left hanging. Someone had been through the papers already. On the floor, under "
    "the window, lay a single envelope addressed to her in her aunt’s cramped hand, the seal "
    "unbroken.",
    "The Anchor was nearly empty at that hour. Tobin was behind the bar drying glasses, and "
    "when he saw her his hands stopped. “Mara Quinn,” he said. “I heard you sold the house "
    "in your head before the funeral was over.” She sat on the stool across from him. “I "
    "heard you were the last one to see her.” He set the glass down very carefully. “Who "
    "told you that?”",
    "Old Ferris had kept the light on the point for forty years, and he still climbed the "
    "iron stairs every evening though the lamp had been automatic since the eighties. He "
    "remembered the night the Albatross went down, the way the beam had swept the water "
    "and found nothing, again and again. He remembered a girl on the rocks, soaked, "
    "refusing to come inside.",
    "Mara opened the envelope at the kitchen table with a butter knife. Inside was a key, "
    "small and brass, and a note: Boathouse. Don’t tell Tobin. She read it three times. "
    "Then she put the key in her pocket and the note in the stove, and watched the paper "
    "curl and blacken before she shut the door on it.",
    "The boathouse door was swollen with damp and she had to put her shoulder to it. Inside, "
    "under a tarpaulin, was her uncle’s old skiff, the one everyone said had gone down with "
    "the Albatross. Its hull was dry. Someone had kept it oiled. Mara crouched by the bow "
    "and found, scratched into the wood, a date she knew.",
]
TEXT = "\n\n***\n\n".join(SCENES)
NAMES = ["Mara", "Tobin", "Ferris"]
EVENTS = [
    StoryEvent(id="e1", text="Beat 1: Mara arrives at Kestrel Bay on the ferry", order=0),
    StoryEvent(id="e2", text="She finds her aunt's study searched and an unopened envelope",
               order=1),
    StoryEvent(id="e3", text="Confrontation with Tobin at the Anchor", description=
               "He was the last to see the aunt alive", order=2),
    StoryEvent(id="e4", text="The envelope holds a key and a warning about Tobin", order=3),
    StoryEvent(id="e5", text="Tobin burns the letter he wrote to the aunt", order=4),
    StoryEvent(id="e6", text="In the boathouse Mara discovers the skiff thought lost "
                             "with the Albatross", order=5),
]
EXPECTED = {1: ["e1"], 2: ["e2"], 3: ["e3"], 4: [], 5: ["e4"], 6: ["e6"]}


def _events():
    return [pm.PlannedEvent(e.id, e.text, e.description) for e in EVENTS]


def test_matches_a_realistic_chapter_and_marks_both_sides():
    scenes = ro.outline(TEXT, NAMES)
    assert len(scenes) == 6
    comp = pm.compare(scenes, TEXT, _events(), NAMES)
    got = {m.number: m.event_ids for m in comp.scenes}
    assert got == EXPECTED
    assert [e.id for e in comp.missing] == ["e5"]          # planned, no scene
    assert [m.number for m in comp.unplanned] == [4]       # scene, not planned
    assert all(m.source == "suggested" for m in comp.scenes)


def test_precision_over_shuffled_and_trimmed_plans():
    """Every match the rules suggest is right on this chapter, whatever the
    plan's order and whichever event is left out."""
    scenes = ro.outline(TEXT, NAMES)
    truth = {e: n for n, ids in EXPECTED.items() for e in ids}
    right = wrong = 0
    events = _events()
    for drop in range(len(events)):
        for plan in (events[:drop] + events[drop + 1:],
                     list(reversed(events[:drop] + events[drop + 1:]))):
            comp = pm.compare(scenes, TEXT, plan, NAMES)
            for m in comp.scenes:
                for i in m.event_ids:
                    if truth.get(i) == m.number:
                        right += 1
                    else:
                        wrong += 1
    assert wrong == 0 and right == 50          # every drafted event, every time


def test_a_paraphrased_plan_suggests_less_but_nothing_wrong():
    """Plans seldom use the draft's words. Fewer matches then, but none
    false; a character's name alone is not a match."""
    plan = [pm.PlannedEvent("e1", "Homecoming: our heroine returns to town by boat"),
            pm.PlannedEvent("e2", "Someone has ransacked the aunt's desk"),
            pm.PlannedEvent("e3", "Bar scene, tense talk with the barman"),
            pm.PlannedEvent("e4", "Key and note found inside"),
            pm.PlannedEvent("e5", "Tobin burns the letter he wrote"),
            pm.PlannedEvent("e6", "The old skiff is dry and oiled")]
    comp = pm.compare(ro.outline(TEXT, NAMES), TEXT, plan, NAMES)
    got = {m.number: m.event_ids for m in comp.scenes}
    assert got == {1: [], 2: ["e2"], 3: [], 4: [], 5: ["e4"], 6: ["e6"]}


def test_corrections_win_and_take_the_event_from_the_suggestion():
    scenes = ro.outline(TEXT, NAMES)
    k4, k5 = pm.scene_key(scenes[3].opening), pm.scene_key(scenes[4].opening)
    comp = pm.compare(scenes, TEXT, _events(), NAMES, {k4: ["e5"], k5: []})
    got = {m.number: (m.event_ids, m.source) for m in comp.scenes}
    assert got[4] == (["e5"], "yours") and got[5] == ([], "yours")
    assert [e.id for e in comp.missing] == ["e4"]
    # an event the writer has placed is not suggested anywhere else
    comp = pm.compare(scenes, TEXT, _events(), NAMES, {k4: ["e1"]})
    assert comp.scenes[0].event_ids == [] and comp.scenes[3].event_ids == ["e1"]


def test_unknown_event_ids_in_a_correction_are_ignored():
    scenes = ro.outline(TEXT, NAMES)
    k1 = pm.scene_key(scenes[0].opening)
    comp = pm.compare(scenes, TEXT, _events(), NAMES, {k1: ["gone", "e1"]})
    assert comp.scenes[0].event_ids == ["e1"]


def test_book_pacing_and_the_tension_hook():
    points = pm.book_pacing([("c1", TEXT), ("c2", "One scene only."), ("c3", "")])
    assert [p.chapter_id for p in points] == ["c1"] * 6 + ["c2"]
    assert points[2].dialogue_share > 0 and points[3].dialogue_share == 0
    assert all(p.tension is None for p in points)
    try:
        pm.set_tension_source(lambda cid, text, spans: [0.5] * len(spans) if cid == "c1" else None)
        points = pm.book_pacing([("c1", TEXT), ("c2", "One scene only.")])
        assert [p.tension for p in points] == [0.5] * 6 + [None]
        pm.set_tension_source(lambda *a: 1 / 0)              # a broken hook never breaks it
        assert pm.book_pacing([("c1", TEXT)])[0].tension is None
    finally:
        pm.set_tension_source(None)


# ── In the Critique ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="Kestrel Bay", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    ch.planning.events = [e.model_copy() for e in EVENTS]
    p.manuscript.chapters.append(ch)
    return p


def _view(project):
    from types import SimpleNamespace as NS
    from src.ui.readiness_issues import ChapterIssues
    view = ChapterIssues()
    view.resize(700, 900)
    view.outline_names = lambda: NAMES
    view.outline_project = lambda: project
    view.outline_open = True
    ch = NS(chapter_id="c1", number=1, title="Kestrel Bay", words=600, text_hash="",
            is_opening=False, results={}, stage="", scope=None)
    view.show_chapter(ch, None, TEXT, {})
    return view


def test_the_critique_marks_the_missing_event_and_the_unplanned_scene(app, tmp_path):
    view = _view(_project(tmp_path))
    page = view.toPlainText()
    assert "1 planned event not drafted · 1 scene not in the plan" in page
    assert "Plan: Mara arrives at Kestrel Bay on the ferry (suggested)" in page   # "Beat 1:" dropped
    assert "Not in the plan (no planned event shares its words)" in page
    assert "Planned, not found in the draft (1):" in page
    assert "Tobin burns the letter he wrote to the aunt" in page
    assert "Scenes across this chapter (6):" in page
    assert "Without a model this shows pacing, not tension." in page
    # the chart is drawn
    name = next(iter(view.outline_charts))
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QTextDocument
    img = view.loadResource(QTextDocument.ResourceType.ImageResource.value, QUrl(name))
    assert img is not None and not img.isNull()


def test_a_correction_survives_a_restart(app, tmp_path):
    from src.data import plan_matches, readiness_state as rs
    from src.models.project import WriterProject as WP
    from src.ui import plan_section
    project = _project(tmp_path)
    view = _view(project)
    scenes = ro.outline(TEXT, NAMES)
    k4 = pm.scene_key(scenes[3].opening)
    # the menu offers each event, Not in the plan, and Use the suggestion
    menu = plan_section.plan_menu(view, k4)
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels[-2:] == ["Not in the plan", "Use the suggestion"]
    assert not menu.actions()[-1].isEnabled()
    next(a for a in menu.actions() if a.text().startswith("Tobin burns")).trigger()
    assert "Plan: Tobin burns the letter he wrote to the aunt (yours)" in view.toPlainText()
    assert "Every planned event has a scene." in view.toPlainText()
    # stored under its own key; the rest of the readiness file is untouched
    data = json.loads(rs.readiness_path(project).read_text())
    assert data["plan_matches"]["main"]["c1"] == {k4: ["e5"]}
    assert data["format_version"] == 1
    # a restart: a new project object read from the same place, a new view
    again = _project(tmp_path)
    assert isinstance(again, WP)
    assert plan_matches.corrections(again, None, "c1") == {k4: ["e5"]}
    assert "Plan: Tobin burns the letter he wrote to the aunt (yours)" in \
        _view(again).toPlainText()
    # back to the suggestion
    plan_section.correct(view, k4, None)
    assert "Not in the plan (no planned event shares its words)" in view.toPlainText()
    assert plan_matches.corrections(again, None, "c1") == {}


def test_older_readiness_files_and_unknown_keys_are_kept(tmp_path):
    from src.data import plan_matches, readiness_state as rs
    project = _project(tmp_path)
    path = rs.readiness_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"format_version": 1, "manuscripts": {"main": {"route": "agent", "chapters": {
        "c1": {"stage": "line", "results": {}}}}}, "dismissed": {"k": 1}, "later": [1]}
    path.write_text(json.dumps(old))
    assert plan_matches.corrections(project, None, "c1") == {}      # an older file: none
    assert plan_matches.set_correction(project, None, "c1", "rain came", [])
    data = json.loads(path.read_text())
    for k in ("manuscripts", "dismissed", "later"):
        assert data[k] == old[k]
    assert data["plan_matches"] == {"main": {"c1": {"rain came": []}}}
    path.write_text("{not json")                                    # unreadable: no crash
    assert plan_matches.corrections(project, None, "c1") == {}


def test_no_plan_says_so_and_no_project_shows_only_the_outline(app, tmp_path):
    from types import SimpleNamespace as NS
    from src.ui.readiness_issues import ChapterIssues
    p = _project(tmp_path)
    p.manuscript.chapters[0].planning.events = []
    page = _view(p).toPlainText()
    assert "No planned events for this chapter" in page and "Plan:" not in page
    view = ChapterIssues()
    view.outline_open = True
    ch = NS(chapter_id="c1", number=1, title="One", words=1, text_hash="", is_opening=False,
            results={}, stage="", scope=None)
    view.show_chapter(ch, None, TEXT, {})
    page = view.toPlainText()
    assert "Plan:" not in page and "No planned events" not in page
    assert "Scenes across this chapter (6):" in page


def test_the_scorecard_charts_the_whole_manuscript(app, tmp_path, monkeypatch):
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path)
    ch2 = Chapter(id="c2", number=2, title="Two", folder_root=p.manuscript.folder_root)
    ch2.content = "The tide went out.\n\n***\n\nThe tide came back."
    p.manuscript.chapters.append(ch2)
    sc = ScorecardWidget()
    sc.set_project(p)
    sc._render(rd.book_report(p))
    sc.issues.outline_open = True
    sc._select_row(sc._row_of("c1"), None)
    page = sc.issues.toPlainText()
    assert "Scenes across the book (8):" in page and "(this chapter in colour)" in page
    assert "1 planned event not drafted" in page
