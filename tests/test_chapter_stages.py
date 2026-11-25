"""3.1: chapter stages — set by hand or by asking, remembered, suggested."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chapter_stages as cst
from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, Subproject, WriterProject

TEXT = "She walked to the door. The boats rocked in the harbor.\n"


def _project(tmp_path, n=8, novella=True):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    for i in range(n):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = TEXT
        p.manuscript.chapters.append(ch)
    if novella:
        sp = Subproject(id="nov1", name="The Long Night",
                        manuscript=Manuscript(title="The Long Night"))
        for i in range(3):
            sp.manuscript.chapters.append(Chapter(id=f"n{i + 1}", number=i + 1,
                                                  title=f"Night {i + 1}", content=TEXT))
        p.subprojects.append(sp)
    return p


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))


def test_a_stage_is_stored_beside_the_results_and_read_by_the_report(tmp_path):
    p = _project(tmp_path)
    rd.chapter_report(p, p.manuscript.chapters[0])             # results stored first
    assert cst.set_stage(p, None, ["c1"], "line")
    entry = rs.load(p)["manuscripts"]["main"]["chapters"]["c1"]
    assert entry["stage"] == "line" and entry["results"]      # results kept
    assert entry["stage_set"]["by"] == "hand"
    report = rd.chapter_report(p, p.manuscript.chapters[0])
    assert report.stage == "line"
    assert cst.stages(p, None) == {"c1": "line"}
    rd.chapter_report(p, p.manuscript.chapters[0], use_cache=False)
    assert cst.stage_of(p, None, "c1") == "line"              # a new check keeps it
    assert cst.set_stage(p, None, ["c1"], "")                  # cleared
    assert cst.stage_of(p, None, "c1") == "" and cst.label("") == "No stage"
    assert not cst.set_stage(p, None, ["c1"], "nonsense")


def test_a_novella_chapter_keeps_its_own_stage(tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "proof")
    cst.set_stage(p, "nov1", ["n1"], "scene")
    assert cst.stage_of(p, None, "c1") == "proof"
    assert cst.stage_of(p, "nov1", "n1") == "scene" and cst.stage_of(p, "nov1", "c1") == ""


@pytest.mark.parametrize("message,stage,numbers,every,current", [
    ("move chapters 3 to 7 to copyedit", "copyedit", [3, 4, 5, 6, 7], False, False),
    ("Please move chapter 4 to proof.", "proof", [4], False, False),
    ("put chapters 1, 2 and 5 into the line stage", "line", [1, 2, 5], False, False),
    ("set chapters 2-4 to copy editing", "copyedit", [2, 3, 4], False, False),
    ("move this chapter to scene", "scene", [], False, True),
    ("put the novella back to line", "line", [], True, False),
    ("move all chapters to structure", "structure", [], True, False),
])
def test_requests_are_read(message, stage, numbers, every, current):
    req = cst.parse_request(message)
    assert req is not None and req.stage == stage and req.numbers == numbers
    assert req.every == every and req.current == current


@pytest.mark.parametrize("message", [
    "move the dog to the kitchen", "put the kettle on", "line edit this paragraph",
    "move the scene where she leaves to chapter 5", "what stage is chapter 3 in?"])
def test_other_messages_are_not_requests(message):
    assert cst.parse_request(message) is None


def test_a_request_resolves_to_chapters_in_the_right_manuscript(tmp_path):
    p = _project(tmp_path)
    names = [p.scope_label(s) for s, _ in p.iter_manuscripts()]
    scope, chs, problem = cst.resolve(p, cst.parse_request("move chapters 3 to 5 to line"))
    assert scope is None and [c.id for c in chs] == ["c3", "c4", "c5"] and not problem
    msg = "put the novella back to line"
    scope, chs, problem = cst.resolve(p, cst.parse_request(msg), message=msg)
    assert scope == "nov1" and [c.id for c in chs] == ["n1", "n2", "n3"]
    msg = "move chapter 2 of The Long Night to proof"
    scope, chs, _ = cst.resolve(p, cst.parse_request(msg, names), message=msg)
    assert scope == "nov1" and [c.id for c in chs] == ["n2"]
    scope, chs, _ = cst.resolve(p, cst.parse_request("move this chapter to proof"),
                                current=("nov1", "n3"))
    assert scope == "nov1" and [c.id for c in chs] == ["n3"]
    assert "chapters 3–5 of “Book” to Line" == cst.describe(p, None, p.manuscript.chapters[2:5],
                                                           "line")


def test_chapters_that_do_not_exist_change_nothing_and_say_so(tmp_path):
    p = _project(tmp_path)
    before = rs.load(p)
    scope, chs, problem = cst.resolve(p, cst.parse_request("move chapters 7 to 12 to proof"))
    assert not chs and "no chapter 9, 10, 11, 12" in problem and "Nothing was moved" in problem
    assert rs.load(p) == before


def test_the_suggestion_appears_when_every_check_of_the_stage_passes(tmp_path):
    rd._load_checks()
    line = [s.name for s in rd.checks_for("line") if s.counts][:2]
    other = next(s.name for s in rd.checks_for("copyedit") if s.counts)
    ready, work = rd.Status.READY, rd.Status.NEEDS_WORK
    assert cst.suggestion_for("line", {line[0]: ready, line[1]: ready, other: work}) == "copyedit"
    assert cst.suggestion_for("line", {line[0]: ready, line[1]: work}) is None
    assert cst.suggestion_for("line", {other: ready}) is None          # nothing of its stage
    assert cst.suggestion_for("", {line[0]: ready}) is None            # no stage: no nudge
    proof = next(s.name for s in rd.checks_for("proof") if s.counts) \
        if rd.checks_for("proof") else None
    if proof:
        assert cst.suggestion_for("proof", {proof: ready}) is None     # nowhere further


# ── On screen and through the assistant ──────────────────────────────

@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class Chat:
    def __init__(self):
        self.messages = []

    def add_message(self, who, text):
        self.messages.append((who, text))


class Window:
    """Enough of the main window for the assistant's route."""

    def __init__(self, project):
        self.current_project = project
        self.chat_widget = Chat()
        self.manuscript_editor = None
        self.turns = []

    def _record_chat_turn(self, user, reply):
        self.turns.append((user, reply))


def test_set_by_hand_and_through_the_assistant_are_stored_the_same_way(qapp, tmp_path,
                                                                      monkeypatch):
    from src.ai.chat_actions import detect_intent
    from src.ui import chapter_stage_ui as ui
    p = _project(tmp_path)
    asked = []
    monkeypatch.setattr(ui, "confirm", lambda parent, text: asked.append(text) or True)
    message = "move chapters 3 to 7 to copyedit"
    assert detect_intent(message) == {"kind": "stage"}
    w = Window(p)
    assert ui.run_chat(w, message)
    assert asked == ["Move chapters 3–7 of “Book” to Copyedit?"]
    assert "Moved chapters 3–7" in w.chat_widget.messages[-1][1]
    cst.set_stage(p, None, ["c1"], "copyedit")                   # by hand
    chapters = rs.load(p)["manuscripts"]["main"]["chapters"]
    assert {k: v["stage"] for k, v in chapters.items()} == {
        f"c{i}": "copyedit" for i in (1, 3, 4, 5, 6, 7)}
    assert chapters["c3"]["stage_set"]["by"] == "assistant"
    cst.set_stage(p, None, ["c3"], "scene")                      # moved by hand afterwards
    assert cst.stage_of(p, None, "c3") == "scene"


def test_the_assistant_says_no_and_changes_nothing(qapp, tmp_path, monkeypatch):
    from src.ui import chapter_stage_ui as ui
    p = _project(tmp_path)
    monkeypatch.setattr(ui, "confirm", lambda parent, text: False)
    w = Window(p)
    assert ui.run_chat(w, "move chapters 1 to 2 to proof")
    assert "nothing was moved" in w.chat_widget.messages[-1][1] and cst.stages(p, None) == {}
    monkeypatch.setattr(ui, "confirm", lambda parent, text: pytest.fail("not asked"))
    assert ui.run_chat(w, "move chapter 40 to proof")
    assert "no chapter 40" in w.chat_widget.messages[-1][1]
    assert not ui.run_chat(w, "move the dog to the kitchen")    # goes to the model


def test_the_scorecard_shows_and_changes_the_stage(qapp, tmp_path):
    from src.ui import chapter_stage_ui as ui
    from src.ui.scorecard_widget import ScorecardWidget
    p = _project(tmp_path, n=3, novella=False)
    cst.set_stage(p, None, ["c2"], "line")
    sc = ScorecardWidget()
    sc.set_project(p)
    sc._render(rd.book_report(p))
    name = lambda cid: sc.table.verticalHeaderItem(sc._row_of(cid)).text()
    assert name("c2").endswith("· Line") and "·" not in name("c1")
    sc._select_row(sc._row_of("c2"), None)
    assert "Stage: Line · change" in sc.issues.toPlainText()
    ui._move(sc, sc._row_report(sc._row_of("c1")), "proof")
    assert name("c1").endswith("· Proof")
    assert cst.stage_of(p, None, "c1") == "proof"


def test_the_companion_header_shows_the_stage_and_the_nudge(qapp, tmp_path, monkeypatch):
    from src.ui import chapter_stage_ui as ui
    from src.ui.companion_panel import CompanionPanel
    p = _project(tmp_path, n=2, novella=False)
    cst.set_stage(p, None, ["c1"], "line")
    panel = CompanionPanel()
    panel.set_chapter(p.manuscript.chapters[0], TEXT)
    panel.set_project(p)
    assert "Stage: <a href='stage:menu'" in panel.chapter_label.text()
    assert "Line ▾" in panel.chapter_label.text() and "move to" not in panel.chapter_label.text()
    monkeypatch.setattr(ui, "stored_statuses",
                        lambda project, scope, cid: {s.name: rd.Status.READY
                                                     for s in rd.checks_for("line")})
    panel.refresh_stage()
    assert "href='stage:copyedit'" in panel.chapter_label.text()
    panel._on_stage_link("stage:copyedit")                       # the writer takes it
    assert cst.stage_of(p, None, "c1") == "copyedit"
    assert "Copyedit ▾" in panel.chapter_label.text()


def test_several_chapters_at_once(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from src.ui.chapter_stage_ui import ChaptersDialog
    p = _project(tmp_path, n=4, novella=False)
    dlg = ChaptersDialog(p, None, ["c2"], "scene")
    assert dlg.chosen() == ["c2"] and dlg.chosen_stage() == "scene"
    dlg.list.item(3).setCheckState(Qt.CheckState.Checked)
    assert dlg.chosen() == ["c2", "c4"]
    cst.set_stage(p, None, dlg.chosen(), dlg.chosen_stage())
    assert cst.stages(p, None) == {"c2": "scene", "c4": "scene"}
