"""The writing habit (H.1): a record of each day shared by every project,
the streak, daily and weekly goals, and the nudge to move on."""

import json
import os
import sys
from pathlib import Path
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from src.data import companion_state as cs
from src.data import writing_habit as wh
from src.models.project import Chapter, WriterProject

TUE = date(2026, 11, 24)          # a Tuesday
MON = date(2026, 11, 23)


def day(added=0, cut=0, moved=0, project="p", chapters=None):
    return {project: {"name": project, "path": "", "added": added, "cut": cut, "moved": moved,
                      "minutes": 0, "chapters": chapters or {}}}



def days_back(n, today=TUE, **kw):
    return {(today - timedelta(days=i)).isoformat(): day(**kw) for i in range(n)}


@pytest.fixture
def project(tmp_path):
    p = WriterProject(name="Saga")
    p.project_path = str(tmp_path / "Saga.writerproj")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="Mara rowed."),
                             Chapter(id="c2", number=2, title="Two", content="Fog.")]
    return p


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── Writing days and the streak ────────────────────────────────────────

def test_any_writing_counts_toward_the_streak_with_or_without_a_goal():
    days = {TUE.isoformat(): day(added=10),
            (TUE - timedelta(days=1)).isoformat(): day(cut=300),          # only cutting
            (TUE - timedelta(days=2)).isoformat(): day(added=40, cut=40)}  # revising
    assert wh.streak(days, TUE) == 3
    assert wh.is_writing_day(days[(TUE - timedelta(days=1)).isoformat()])


def test_a_day_with_no_writing_ends_the_streak():
    days = {TUE.isoformat(): day(added=5),
            (TUE - timedelta(days=2)).isoformat(): day(added=900)}
    assert wh.streak(days, TUE) == 1
    assert wh.longest_streak(days) == 1
    assert wh.days_this_month(days, TUE) == 2


def test_today_without_writing_yet_keeps_yesterdays_streak():
    days = days_back(4, today=TUE - timedelta(days=1), added=10)
    assert wh.streak(days, TUE) == 4
    assert wh.streak(days, TUE + timedelta(days=1)) == 0


def test_writing_at_half_past_midnight_counts_on_the_new_day(project):
    # 23:50 to 00:30: the words go to the days the minutes were typed on.
    wh.record(project, "c1", "One", added=100,
              minutes={MON.isoformat(): 1, TUE.isoformat(): 3}, day=TUE)
    days = wh.load()["days"]
    assert wh.words_on(days, MON) == 25 and wh.words_on(days, TUE) == 75
    wh.record(project, "c1", "One", added=50, minutes={TUE.isoformat(): 2}, day=TUE)
    assert wh.words_on(wh.load()["days"], TUE) == 125
    assert wh.streak(wh.load()["days"], TUE) == 2


def test_daily_and_weekly_goals_are_measured_separately_and_the_week_starts_on_monday():
    sunday = MON - timedelta(days=1)
    days = {
        sunday.isoformat(): day(added=4000), MON.isoformat(): day(added=700),
        TUE.isoformat(): day(added=300)}
    assert wh.week_start(TUE) == MON and MON.weekday() == 0
    assert wh.week_words(days, TUE) == 1000                 # Sunday is last week
    p = wh.goal_progress(days, TUE, daily=500, weekly=1000)
    assert (p["daily_met"], p["weekly_met"]) == (False, True)
    line, head = wh.progress_line(days, TUE, 500, 1000)
    assert line == "Today: 300 of 500 words · this week 1,000 of 1,000 · 3 days in a row"
    assert head == "300/500 words today"
    best, words = wh.best_week(days)
    assert best == sunday - timedelta(days=6) and words == 4000


def test_two_projects_on_one_day_count_once_with_the_words_of_both(tmp_path):
    a, b = WriterProject(name="A"), WriterProject(name="B")
    a.project_path, b.project_path = str(tmp_path / "A.writerproj"), str(tmp_path / "B.writerproj")
    wh.record(a, "x", "X", added=200, day=TUE)
    wh.record(b, "y", "Y", added=300, cut=20, day=TUE)
    days = wh.load()["days"]
    assert wh.streak(days, TUE) == 1
    assert wh.words_on(days, TUE) == 500
    assert [n for n, _ in wh.worked_on(days[TUE.isoformat()])] == ["A", "B"]


def test_a_cut_paragraph_and_a_new_one_do_not_cancel_out():
    before = "One two three four.\n\nOld paragraph goes away now."
    after = "One two three four.\n\nA brand new paragraph arrives here."
    added, cut = wh.word_changes(before, after)
    assert (added, cut) == (5, 4)                 # "paragraph" stays
    assert wh.word_changes("a b c", "a b c") == (0, 0)


def test_the_record_is_never_trimmed_and_keeps_unknown_keys(project):
    data = wh.load()
    data["days"] = days_back(900, added=1)
    data["from_a_later_version"] = {"x": 1}
    wh.save(data)
    wh.record(project, "c1", "One", added=5, day=TUE + timedelta(days=1))
    again = wh.load()
    assert len(again["days"]) == 901 and again["from_a_later_version"] == {"x": 1}


def test_an_unreadable_record_is_set_aside_not_saved_over(project):
    path = wh.habit_path()
    path.write_text("{ not json")
    assert wh.load()["days"] == {}
    assert any(p.name.startswith("writing_habit.json.unreadable") for p in path.parent.iterdir())


# ── Old sessions ───────────────────────────────────────────────────────

def test_old_sessions_fold_in_once_and_the_old_key_is_still_written(project, app):
    cs.record_session(project, "c1", 100, 340, "x")           # an older app's session
    data = cs.load(project)
    data["sessions"]["c1@2026-10-01T09:00:00"] = {"date": "2026-10-01", "added": 500}
    cs.save(project, data)
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    days = wh.load()["days"]
    assert wh.words_on(days, date(2026, 10, 1)) == 500
    assert wh.words_on(days, date.today()) == 240
    ed2 = ChapterEditor(project.manuscript.chapters[1], project=project)   # not again
    assert wh.words_on(wh.load()["days"], date(2026, 10, 1)) == 500
    # The old key is still written by the new app.
    ed2.editor.setPlainText("Fog. And then more words arrived here.")
    ed2.save_to_model()
    assert any(k.startswith("c2@") for k in cs.load(project)["sessions"])
    assert cs.words_today(project) >= 240
    ed.deleteLater(), ed2.deleteLater()


# ── Counting in the editor ─────────────────────────────────────────────

def test_typing_counts_and_a_large_paste_is_moved_not_written(project, app):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    cur = ed.editor.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    cur.insertText(" She shipped the oars.")
    ed.save_to_model()
    t = wh.day_totals(wh.load()["days"][date.today().isoformat()])
    assert (t["added"], t["moved"]) == (4, 0)
    cur.movePosition(cur.MoveOperation.End)
    cur.insertText("\n" + " ".join(f"word{i}" for i in range(400)))     # one paste
    ed.save_to_model()
    t = wh.day_totals(wh.load()["days"][date.today().isoformat()])
    assert (t["added"], t["moved"]) == (4, 400)
    entry = wh.load()["days"][date.today().isoformat()][wh.project_key(project)]
    assert entry["chapters"]["c1"]["title"] == "One"
    ed.deleteLater()


def test_key_presses_count_minutes_once_per_minute(project, app, monkeypatch):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    from src.ui import habit_tracker
    from src.ui.manuscript_editor import ChapterEditor
    monkeypatch.setattr(habit_tracker, "_now", lambda: datetime(2026, 11, 24, 10, 15, 30))
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    for ch in "abc":
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, ch)
        ed.companion.habit.eventFilter(ed.editor, ev)
    ed.editor.setPlainText(ed.editor.toPlainText() + " abc")
    ed.save_to_model()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a")
    ed.companion.habit.eventFilter(ed.editor, ev)                   # the same minute again
    ed.editor.setPlainText(ed.editor.toPlainText() + " a")
    ed.save_to_model()
    assert wh.day_totals(wh.load()["days"]["2026-11-24"])["minutes"] == 1
    ed.deleteLater()


def test_meeting_a_goal_puts_one_quiet_line_in_the_status_bar(project, app, monkeypatch):
    from src.ui import notify
    from src.ui.manuscript_editor import ChapterEditor
    wh.set_goals(5, 0)
    said = []
    monkeypatch.setattr(notify, "done", lambda parent, title, text, path=None: said.append(text))
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    ed.editor.setPlainText("Mara rowed. One two three four five six.")
    ed.save_to_model()
    ed.editor.setPlainText("Mara rowed. One two three four five six seven.")
    ed.save_to_model()
    assert said == ["Daily goal met: 5 words"]
    assert "Today: 8 of 5 words" in ed.companion.panel.left_off_label.text()
    ed.deleteLater()


# ── The Companion ──────────────────────────────────────────────────────

def test_with_no_goal_the_companion_shows_what_it_did_before_plus_one_link(project, app):
    from src.ai import companion
    from src.ui.manuscript_editor import ChapterEditor
    cs.record_session(project, "c1", 10, 60, "Mara rowed.")
    before = cs.load(project)["chapters"]["c1"]
    expected = companion.left_off(project, project.manuscript.chapters[0], "Mara rowed.",
                                  dict(before), cs.words_today(project), 0)
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    panel = ed.companion.panel
    for line in expected.lines:
        assert line.replace("“", "").split()[0] in panel.left_off_label.text()
    assert ed.companion_banner.label.text() == expected.headline
    assert "Today: 50 words so far." in panel.left_off_label.text()
    assert "in a row" not in panel.left_off_label.text()
    assert "Set a daily goal…" in panel.habit_link.text()
    ed.deleteLater()


def test_with_a_goal_the_companion_shows_today_the_week_and_the_streak(project, app):
    from src.ui.manuscript_editor import ChapterEditor
    wh.set_goals(1000, 5000)
    wh.record(project, "c1", "One", added=640, day=date.today())
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    text = ed.companion.panel.left_off_label.text()
    assert "Today: 640 of 1,000 words · this week" in text and "of 5,000 · 1 day in a row" in text
    assert "640/1,000 words today" in ed.companion_banner.label.text()
    assert "Your writing record…" in ed.companion.panel.habit_link.text()
    ed.deleteLater()


def test_the_goal_dialog_and_the_link(project, app):
    from src.ui.habit_view import GoalDialog, HabitLink
    changed = []
    link = HabitLink(lambda: changed.append(1))
    assert "Set a daily goal…" in link.text()
    dlg = GoalDialog()
    dlg.daily.setValue(750)
    dlg.weekly.setValue(0)
    dlg.accept()
    assert wh.goals() == (750, 0)
    link._changed()
    assert "Your writing record…" in link.text() and changed == [1]


def test_the_twelve_week_window_lists_a_day_when_clicked(project, app):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent
    from src.ui.habit_view import HabitWindow
    wh.record(project, "c2", "Two", added=120, cut=30, day=TUE - timedelta(days=2))
    wh.record(project, "c1", "One", added=10, day=TUE)
    win = HabitWindow(None, today=TUE)
    assert win.streak_label.text() == "1 day in a row"
    assert len(win.grid.dates) == 84 and win.grid.dates[0].weekday() == 0
    i = win.grid.dates.index(TUE - timedelta(days=2))
    centre = QPointF(win.grid._rect(i).center())
    win.grid.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, centre,
                                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
    assert "120 words added, 30 cut" in win.day_label.text() and "Saga: Two" in win.day_label.text()
    win.close()


# ── The nudge ──────────────────────────────────────────────────────────

def test_the_nudge_asks_after_seven_revising_days_and_not_with_new_words():
    key = "p"
    days = {}
    for i in range(7):
        days[(TUE - timedelta(days=i * 2)).isoformat()] = day(added=60, cut=50)
    assert wh.revising_only(days, key) == {"days": 7, "added": 420, "cut": 350, "growth": 70}
    assert wh.revising_only(dict(list(days.items())[:6]), key) is None      # six days
    days[TUE.isoformat()] = day(added=400, cut=0)
    assert wh.revising_only(days, key) is None                              # new words
    assert wh.revising_only(days, "another project") is None


def test_keep_revising_waits_seven_more_writing_days():
    days = {(TUE - timedelta(days=i)).isoformat(): day(cut=20) for i in range(10)}
    asked = TUE - timedelta(days=3)
    assert wh.revising_only(days, "p") is not None
    assert wh.revising_only(days, "p", since=asked) is None         # only 3 days since
    later = TUE + timedelta(days=4)
    days.update({(TUE + timedelta(days=i)).isoformat(): day(cut=5) for i in range(1, 5)})
    assert wh.revising_only(days, "p", since=asked) is not None and later


def test_not_for_a_short_story_and_not_once_a_chapter_is_past_drafting(project):
    from src.ai import chapter_stages
    assert wh.nudge_applies(project, None)
    story = project.create_subproject("Ghost", kind="short story")
    assert not wh.nudge_applies(project, story.id)
    novella = project.create_subproject("Long one")
    assert wh.nudge_applies(project, novella.id)
    chapter_stages.set_stage(project, None, ["c1"], "line")
    assert not wh.nudge_applies(project, None)


def _revising_record(project):
    for i in range(7):
        wh.record(project, "c1", "One", added=10, cut=12, day=date.today() - timedelta(days=i + 1))


def test_the_nudge_in_the_editor_stop_then_settings_turn_it_back_on(project, app, monkeypatch):
    from src.ui import habit_tracker, notify
    from src.ui.manuscript_editor import ChapterEditor
    monkeypatch.setattr(notify, "done", lambda *a, **k: None)
    _revising_record(project)
    asked = []
    monkeypatch.setattr(habit_tracker, "ask", lambda parent, reason: asked.append(reason) or "stop")
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    ed.companion.habit.maybe_nudge()
    assert len(asked) == 1 and asked[0]["days"] == 7
    assert wh.nudge_state()["on"] is False
    ed.companion.habit.maybe_nudge()
    assert len(asked) == 1                                   # off for good
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from src.ui.habit_view import HabitOption
    holder = QWidget()
    option = HabitOption(QVBoxLayout(holder))
    assert not option.nudge.isChecked()
    option.nudge.setChecked(True)
    option.save()
    assert wh.nudge_state()["on"] is True
    ed.deleteLater()


def test_keep_revising_does_not_ask_again_the_same_week(project, app, monkeypatch):
    from src.ui import habit_tracker
    from src.ui.manuscript_editor import ChapterEditor
    _revising_record(project)
    asked = []
    monkeypatch.setattr(habit_tracker, "ask", lambda parent, reason: asked.append(1) or "keep")
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    ed.companion.habit.maybe_nudge()
    ed.companion.habit.maybe_nudge()
    assert asked == [1] and wh.nudge_state()["on"] is True
    assert wh.last_asked() == date.today()
    ed.deleteLater()


def test_go_to_the_next_chapter_opens_the_one_after_the_last_worked_on(project, app, monkeypatch):
    from src.ui import habit_tracker
    from src.ui.manuscript_editor import ManuscriptEditor
    _revising_record(project)                                # last worked on: c1
    monkeypatch.setattr(habit_tracker, "ask", lambda parent, reason: "next")
    w = ManuscriptEditor()
    w.set_project(project)
    w.load_manuscript(project.manuscript)
    w.open_chapter("c1")
    w.current_chapter_editor.companion.habit.maybe_nudge()
    app.processEvents()
    assert w.current_chapter_editor.chapter.id == "c2"
    w.deleteLater()


# ── Backwards compatible ───────────────────────────────────────────────

def test_an_install_without_goals_gains_no_setting_until_one_is_set(app):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from src.ui.habit_view import HabitOption
    store = wh._config()
    holder = QWidget()
    option = HabitOption(QVBoxLayout(holder))
    option.save()
    assert dict(store) == {}
    wh.set_goals(0, 2000)
    assert dict(store) == {"weekly_word_goal": 2000}


def test_a_project_and_settings_from_before_open_and_save_unchanged(app):
    import shutil
    from test_project_compat import _v1_project_dir
    from src.ui.manuscript_editor import ManuscriptEditor
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    project_json = json.loads(path.read_text())
    p = WriterProject.load_project(str(path))
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    w.current_chapter_editor.save_to_model()
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    assert [c.title for c in again.manuscript.chapters] == \
        [c["title"] for c in project_json["manuscript"]["chapters"]]
    assert dict(wh._config()) == {}                    # no setting written
    w.deleteLater()
    shutil.rmtree(d)


def test_a_day_with_only_a_paste_or_import_is_not_a_writing_day():
    """The writer, 24 Nov 2026: "just a paste or an import should not count"."""
    from datetime import date
    from src.data import writing_habit as wh
    assert not wh.is_writing_day(day(moved=400))
    assert wh.is_writing_day(day(cut=3))
    days = {"2026-11-22": day(added=50), "2026-11-23": day(moved=900), "2026-11-24": day(added=10)}
    assert wh.streak(days, date(2026, 11, 24)) == 1        # the paste-only day broke it
