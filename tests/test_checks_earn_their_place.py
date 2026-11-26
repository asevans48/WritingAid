"""4.3: checks earn their place — accepts, skips and dismissals counted per
check, per project, in the readiness file; a check the writer mostly turns
down is toned down (never switched off without the writer's click) and can
be brought back."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai import fix_queue
from src.ai import intentional
from src.ai import readiness as rd
from src.data import check_outcomes as co
from src.data import readiness_state as rs
from tests.test_intentional import _close, _editor, _project, wait_tasks


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    from src.ui import companion_panel
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: False)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fresh():
    co._cache.clear()
    intentional._forget()


# ── The store, without Qt ───────────────────────────────────────────

def test_counts_survive_a_restart_and_stay_in_their_own_project(tmp_path):
    p, other = _project(tmp_path), _project(tmp_path, "Other")
    assert co.record(p, "filler", co.ACCEPTED, 3)
    assert co.record(p, "filler", co.SKIPPED)
    assert co.record(p, "style:transition", co.NOT_A_PROBLEM)
    _fresh()                                                     # as after a restart
    raw = json.loads(rs.readiness_path(p).read_text())
    assert raw["outcomes"]["filler"] == {"accepted": 3, "skipped": 1}
    o = co.outcome(p, "filler")
    assert (o.accepted, o.skipped, o.rejected) == (3, 1, 0)
    assert "3 of 3" in o.rate_line() and "1 skipped" in o.rate_line()
    assert co.counts(other) == {} and co.outcome(other, "filler").answers == 0


def test_a_check_mostly_turned_down_is_toned_down_and_brought_back(tmp_path):
    p = _project(tmp_path)
    co.record(p, "filler", co.ACCEPTED, 3)
    co.record(p, "filler", co.NOT_A_PROBLEM, 15)
    assert "filler" not in co.toned_down(p)                     # 18 answers: too few to judge
    co.record(p, "filler", co.SKIPPED, 30)                      # skips are not rejections
    assert "filler" not in co.toned_down(p)
    co.record(p, "filler", co.INTENDED, 2)
    assert co.toned_down(p) == {"filler"}                       # 3 of 20 accepted
    assert "17 of its last 20" in co.outcome(p, "filler").toned_line()
    assert co.bring_back(p, "filler")
    assert "filler" not in co.toned_down(p)
    o = co.outcome(p, "filler")
    assert (o.accepted, o.not_a_problem, o.intended, o.skipped) == (3, 15, 2, 30)  # kept
    co.record(p, "filler", co.NOT_A_PROBLEM, 19)                # judged again from here
    assert "filler" not in co.toned_down(p)
    co.record(p, "filler", co.NOT_A_PROBLEM)
    assert "filler" in co.toned_down(p)
    co.record(p, "adverbs", co.ACCEPTED, 12)                    # mostly taken: never toned
    co.record(p, "adverbs", co.NOT_A_PROBLEM, 10)
    assert "adverbs" not in co.toned_down(p)


def test_an_older_readiness_file_with_no_counts_loads_and_keeps_its_keys(tmp_path):
    p = _project(tmp_path)
    path = rs.readiness_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"format_version": 1, "manuscripts": {"main": {"route": "agent"}},
           "dismissed": {"intensifier:very": {"text": "very", "label": "Weak intensifiers"}},
           "future_key": {"x": 1}}
    path.write_text(json.dumps(old))
    _fresh()
    assert co.counts(p) == {} and co.toned_down(p) == set()
    assert co.outcome(p, "filler").rate_line() == "No fixes answered yet in this project."
    co.record(p, "filler", co.ACCEPTED)
    data = json.loads(path.read_text())
    assert data["future_key"] == {"x": 1} and data["dismissed"] == old["dismissed"]
    assert data["manuscripts"]["main"]["route"] == "agent"
    # Damaged counts read as zeros, never an error.
    data["outcomes"] = {"filler": {"accepted": "lots", "restored": "?"}, "bad": 3}
    path.write_text(json.dumps(data))
    _fresh()
    assert co.outcome(p, "filler").accepted == 0 and co.outcome(p, "bad").answers == 0


def test_every_leave_it_is_counted_once_from_the_one_store(tmp_path):
    p = _project(tmp_path)
    item = rd.Item(start=0, end=4, text="very", reason="r", kind="intensifier",
                   key="intensifier:very")
    entry = fix_queue.Entry("filler", "Filler and weak intensifiers", "line", "polish", item)
    assert fix_queue.dismiss(p, entry, "Ch 1")
    assert co.outcome(p, "filler").not_a_problem == 1
    intentional.mark_item(p, item, entry.label, "Ch 1")       # already dismissed: not again
    assert co.outcome(p, "filler").rejected == 1
    # The right-click entry: no check named, found from the flag's key.
    intentional.mark(p, "spelling:teh", "teh", label="Spelling", category="spelling",
                     word="teh")
    intentional.mark(p, "passive:was taken", "was taken", label="Passive voice")
    intentional.mark(p, "transition:x", "x", label="Few transitions")
    assert co.outcome(p, "spelling_grammar").intended == 1
    assert co.outcome(p, "passive").intended == 1
    assert co.outcome(p, "style:transition").intended == 1
    # The Critique's That's intended: by its label.
    other = rd.Item(start=0, end=3, text="x", reason="r", kind="pacing", key="pacing:slow")
    intentional.mark_item(p, other, "Pacing")
    rd._load_checks()
    pacing = next((n for n, s in rd.REGISTRY.items() if s.label == "Pacing"), "pacing")
    assert co.outcome(p, pacing).intended == 1


def test_a_toned_down_check_comes_after_the_others_of_its_stage():
    def item(n, kind):
        return rd.Item(start=n, end=n + 3, text="abc", reason="r", kind=kind, key=f"{kind}:{n}")
    a = fix_queue.Entry("style:transition", "Few transitions", "line", "polish", item(0, "transition"))
    b = fix_queue.Entry("style:pronoun", "Pronouns", "line", "polish", item(9, "pronoun"))
    assert [e.check for e in fix_queue.entries(None, "", extra=[a, b])][0] == "style:transition"
    order = fix_queue.entries(None, "", extra=[a, b], toned={"style:transition"})
    assert [e.check for e in order] == ["style:pronoun", "style:transition"]   # lower, not gone


def test_spelling_and_overused_words_are_never_offered_off():
    assert co.can_switch_off("spelling_grammar") == set()
    assert co.can_switch_off("repetition") == set()
    assert co.can_switch_off("filler", {"intensifier", "adverb"}) == {"intensifier"}
    assert co.can_switch_off("style:vague") == {"vague"}


# ── On screen ───────────────────────────────────────────────────────

def test_the_card_counts_its_answers_and_offers_but_never_makes_a_switch_off(app, tmp_path):
    from src.data import check_switches
    p = _project(tmp_path)
    ed = _editor(app, p)
    queue, card = ed.companion.queue, ed.companion.panel.queue
    queue.find()
    wait_tasks(app)
    first = queue.entries[queue.index]
    queue.skip()
    assert co.outcome(p, first.check).skipped == 1
    queue.index = next(n for n, e in enumerate(queue.entries) if e.item.key == "intensifier:very")
    queue.show()
    check = queue.entries[queue.index].check
    assert check == "filler"
    queue.dismiss()
    assert co.outcome(p, check).not_a_problem == 1
    queue.undo_dismiss()                                        # a misclick: not counted
    wait_tasks(app)
    assert co.outcome(p, check).not_a_problem == 0
    co.record(p, check, co.NOT_A_PROBLEM, 19)
    queue.index = next(n for n, e in enumerate(queue.entries) if e.item.key == "intensifier:very")
    queue.show()
    hl = ed.editor.writing_highlighter
    assert "intensifier" in hl._style_kinds
    queue.dismiss()                                             # the twentieth: toned down
    status = card.status.text()
    assert "toned down" in status and "switch-off:filler" in status
    assert "intensifier" in hl._style_kinds                    # nothing switched on its own
    card.status.linkActivated.emit("switch-off:filler")         # the writer confirms
    assert "intensifier" not in hl._style_kinds and "wordy" not in hl._style_kinds
    kinds, _on = check_switches.resolve(p)
    assert "intensifier" not in kinds                           # remembered for this project
    assert "switched off" in card.status.text()
    _close(app, ed)


def test_bring_it_back_from_the_card(app, tmp_path):
    p = _project(tmp_path)
    co.record(p, "filler", co.NOT_A_PROBLEM, 20)
    ed = _editor(app, p)
    queue, card = ed.companion.queue, ed.companion.panel.queue
    queue.find()
    wait_tasks(app)
    line = [e.check for e in queue.entries if e.stage == "line"]
    assert "filler" in line and len(set(line)) > 1
    assert line[line.index("filler"):] == ["filler"] * (len(line) - line.index("filler"))
    queue.index = next(n for n, e in enumerate(queue.entries) if e.check == "filler")
    queue.show()
    assert "bring-back:filler" in card.status.text()
    card.status.linkActivated.emit("bring-back:filler")
    assert "filler" not in co.toned_down(p) and co.outcome(p, "filler").not_a_problem == 20
    assert "back as it was" in card.status.text()
    _close(app, ed)


def test_accept_and_fix_all_count_as_accepts(app, tmp_path):
    p = _project(tmp_path)
    ed = _editor(app, p)
    queue, card = ed.companion.queue, ed.companion.panel.queue
    queue.find()
    wait_tasks(app)
    queue.index = next(n for n, e in enumerate(queue.entries) if e.item.key == "spelling:teh")
    queue.show()
    card._accept()
    wait_tasks(app)
    assert co.outcome(p, "spelling_grammar").accepted == 1
    _close(app, ed)
    from src.ui import check_outcomes_ui
    from src.utils.editor_flags import ErrorType
    from types import SimpleNamespace
    error = SimpleNamespace(error_type=ErrorType.SPELLING, word="teh")
    check_outcomes_ui.fixed_everywhere(SimpleNamespace(_project=p), error, 4)
    assert co.outcome(p, "spelling_grammar").accepted == 5


def test_the_critique_shows_the_rate_and_tones_a_column_down(app, tmp_path):
    from PyQt6.QtGui import QColor
    from src.ui.scorecard_widget import ScorecardWidget
    from src.ui.ui_kit import PALETTE
    p = _project(tmp_path)
    co.record(p, "filler", co.ACCEPTED, 2)
    co.record(p, "filler", co.NOT_A_PROBLEM, 20)
    co.record(p, "adverbs", co.ACCEPTED, 4)
    report = rd.book_report(p)
    sc = ScorecardWidget()
    sc.project = p
    sc._selected = "c1"
    sc._render(report)
    heads = {}
    for c in range(sc.table.columnCount()):
        names = sc._column_checks[c]
        if len(names) == 1:
            heads[names[0]] = c
    assert "filler" in heads
    for name, c in heads.items():                               # every column: its rate
        tip = sc.table.horizontalHeaderItem(c).toolTip()
        assert "Fixes accepted here" in tip or "No fixes answered yet" in tip
    fc = heads["filler"]
    tip = sc.table.horizontalHeaderItem(fc).toolTip()
    assert "2 of 22" in tip and "Toned down" in tip
    assert sc.table.horizontalHeaderItem(fc).foreground().color() == QColor(PALETTE["ink_faint"])
    assert sc.table.item(0, fc).foreground().color() == QColor(PALETTE["ink_faint"])
    assert "4 of 4" in sc.table.horizontalHeaderItem(heads["adverbs"]).toolTip()
    sc._select_chapter("c1", ["filler"])
    assert "Bring it back" in sc.issues.toHtml()
    restore = next(n for n, (kind, _i) in enumerate(sc.issues._links) if kind == "restore")
    from PyQt6.QtCore import QUrl
    sc.issues._on_link(QUrl(f"issue:{restore}"))
    assert "filler" not in co.toned_down(p) and co.outcome(p, "filler").not_a_problem == 20
    assert sc.table.horizontalHeaderItem(fc).foreground().color() != QColor(PALETTE["ink_faint"])
    assert "Bring it back" not in sc.issues.toHtml()
    sc.close()


def test_the_style_checks_menu_gives_each_switch_its_rate(app, tmp_path):
    p = _project(tmp_path)
    co.record(p, "style:vague", co.NOT_A_PROBLEM, 21)
    co.record(p, "filler", co.ACCEPTED, 5)
    ed = _editor(app, p)
    sub = next(a.menu() for a in ed.checks_menu.actions()
               if a.menu() is not None and a.text() == "Style checks")
    sub.aboutToShow.emit()
    acts = ed._style_check_actions
    assert "5 of 5" in acts["intensifier"].toolTip() and "5 of 5" in acts["wordy"].toolTip()
    assert "toned down" in acts["vague"].text() and "Toned down" in acts["vague"].toolTip()
    assert "toned down" not in acts["adverb"].text()
    _close(app, ed)
