"""3.2: the next-fix queue — the chapter's findings for its stage, one at a time."""

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import chapter_stages as cst
from src.ai import fix_queue
from src.ai import readiness as rd
from src.data import readiness_state as rs
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("Teh rain fell on the harbor and the boats rocked slowly.\n"
        "She walked very quickly to the door and really quietly opened it.\n"
        "He smiled warmly, sadly, and then he turned teh lamp down low.\n")


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    from src.ui import companion_panel
    monkeypatch.setattr(companion_panel, "_companion_ai_enabled", lambda: False)


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="Harbor", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


# ── The order, without Qt ───────────────────────────────────────────

def _item(key, start, verdict=""):
    return rd.Item(start=start, end=start + 3, text="xyz", reason="r", kind="", key=key,
                   verdict=verdict)


def _result(name, status, items):
    spec = rd.REGISTRY[name]
    return rd.CheckResult(check=name, stage=spec.stage, status=status, count=len(items),
                          items=items)


def test_the_queue_is_the_stage_most_important_first_and_skips_go_to_the_back():
    rd._load_checks()
    by_stage = {s: [x for x in rd.checks_for(s) if x.level == "chapter"] for s in rd.STAGES}
    line = by_stage["line"][0].name
    copy = by_stage["copyedit"][0].name
    struct = next(x.name for s in ("structure", "scene") for x in by_stage[s])
    report = NS(chapter_id="c1", results={
        line: _result(line, rd.Status.NEEDS_WORK, [_item("l1", 50), _item("l2", 10),
                                                    _item("l3", 5, verdict="cleared")]),
        copy: _result(copy, rd.Status.PROBLEM, [_item("c1", 80)]),
        struct: _result(struct, rd.Status.NEEDS_WORK, [_item("s1", 0)])})
    everything = fix_queue.entries(report)
    assert everything[0].check == struct                      # no stage: structure first
    assert [e.item.key for e in everything if e.check == line] == ["l2", "l1"]  # by place
    assert all(e.item.key != "l3" for e in everything)        # cleared by the model
    at_copyedit = fix_queue.entries(report, "copyedit")
    assert [e.check for e in at_copyedit] == [copy]           # no structure fix at copyedit
    at_line = fix_queue.entries(report, "line")
    skipped = fix_queue.entries(report, "line", skipped=[at_line[0].key])
    assert [e.item.key for e in skipped] == ["l1", "l2"]      # the skipped one at the back


def test_before_and_after_is_coloured_word_by_word():
    from src.ui.next_fixes import before_after
    out = before_after("She walked very quickly to the door.", "She hurried to the door.")
    assert "line-through" in out and "walked very quickly" in out and "hurried" in out
    assert out.startswith("She ")


# ── In the Companion ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait_tasks(app):
    from src.ui import background, companion_panel
    for _ in range(20):
        for t in list(companion_panel._RUNNING):
            t.wait(10000)
        background.wait_all(10000)
        app.processEvents()
        if not companion_panel._RUNNING:
            return


def chapter_editor(app, project):
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(project.manuscript.chapters[0], project=project)
    ed.resize(1100, 700)
    ed.show()
    app.processEvents()
    return ed


def test_the_card_offers_the_stage_s_fixes_one_at_a_time(app, tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "copyedit")
    ed = chapter_editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    assert queue.entries and all(e.stage == "copyedit" for e in queue.entries)
    card = ed.companion.panel.queue
    assert card.fix is not None and "1 of" in card.status.text()
    assert "Copyedit fixes" in card.status.text()
    first = queue.entries[0].key
    queue.skip()
    assert queue.entries[-1].key == first and "skipped before" not in card.status.text()
    queue.back()
    assert "skipped before" in card.status.text()


def test_accepting_a_fix_updates_the_report_and_the_cells_turn(app, tmp_path):
    p = _project(tmp_path)
    cst.set_stage(p, None, ["c1"], "copyedit")
    ed = chapter_editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    before = rs.stored_chapter(p, None, "c1")["results"]["spelling_grammar"]["count"]
    assert before >= 2
    for _ in range(10):                                   # work through it
        card = ed.companion.panel.queue
        if card.fix is None or not card.option_text():
            break
        card._accept()
        wait_tasks(app)
    assert "teh" not in ed.editor.toPlainText().lower()
    stored = rs.stored_chapter(p, None, "c1")["results"]["spelling_grammar"]
    assert stored["count"] < before
    report = rd.chapter_report(p, p.manuscript.chapters[0], text=ed.editor.toPlainText())
    assert report.results["spelling_grammar"].status == rd.Status.READY


def test_a_chapter_with_no_stage_is_offered_every_stage(app, tmp_path):
    p = _project(tmp_path)
    ed = chapter_editor(app, p)
    ed.companion.queue.find()
    wait_tasks(app)
    stages = {e.stage for e in ed.companion.queue.entries}
    assert len(stages) >= 2 and "every stage" in ed.companion.panel.queue.status.text()


def test_the_older_sections_stay_but_start_closed(app, tmp_path):
    p = _project(tmp_path)
    ed = chapter_editor(app, p)
    panel = ed.companion.panel
    assert len(panel.sections) == 7                              # none added (rule 13)
    assert panel.sections["fixes"].is_open() and not panel.sections["overdescribed"].is_open()
    # D.6: Today's three fixes is retired; the model's three show on the card.
    assert not hasattr(panel, "older_fixes") and not hasattr(panel, "fixes_btn")
    assert "href='three'" not in panel.queue.status.text()    # no model here: not offered
    from src.ui import companion_panel
    companion_panel._companion_ai_enabled = lambda: True      # a model may be set up
    ed.companion._no_model = False                            # (the fixture puts it back)
    ed.companion.queue.chapter_loaded()
    assert "href='three'" in panel.queue.status.text()
    from src.ai.companion import Fix
    ed.companion.queue.show_fixes([Fix("Spelling: Teh", excerpt="Teh")], "The three that matter most")
    assert panel.queue.fix is not None and "The three that matter most" in panel.queue.status.text()


# ── 3.3: Skip and Not a problem ─────────────────────────────────────

def _two_chapters(tmp_path, name="Book"):
    p = WriterProject(name=name, manuscript=Manuscript(title=name))
    folder = tmp_path / name                         # each project in its own folder
    folder.mkdir(exist_ok=True)
    p.project_path = str(folder / f"{name}.writerproj")
    for n, text in ((1, TEXT), (2, "It was very late. The tide was very high.\n")):
        ch = Chapter(id=f"c{n}", number=n, title=f"Ch {n}", folder_root=p.manuscript.folder_root)
        ch.content = text
        p.manuscript.chapters.append(ch)
    return p


def _keys(p, cid):
    r = rd.chapter_report(p, next(c for c in p.manuscript.chapters if c.id == cid))
    return [e.item.key for e in fix_queue.entries(r)]


def test_not_a_problem_lasts_everywhere_in_the_project_and_nowhere_else(app, tmp_path):
    p = _two_chapters(tmp_path)
    other = _two_chapters(tmp_path, "Other")
    assert "intensifier:very" in _keys(p, "c1") and "intensifier:very" in _keys(p, "c2")
    ed = chapter_editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    queue.index = next(n for n, e in enumerate(queue.entries) if e.item.key == "intensifier:very")
    queue.show()
    queue.dismiss()
    assert all(e.item.key != "intensifier:very" for e in queue.entries)
    assert "won't be raised again" in ed.companion.panel.queue.status.text()
    assert "intensifier:very" not in _keys(p, "c1")                # the next check
    assert "intensifier:very" not in _keys(p, "c2")                # another chapter
    stored = rs.load(p)["dismissed"]["intensifier:very"]          # on disk: lasts a restart
    assert stored["as"] == fix_queue.NOT_A_PROBLEM and stored["label"]
    assert "intensifier:very" in _keys(other, "c2")                 # another project: no effect
    from src.ai import editor_pass
    assert all(d["key"] != "intensifier:very" for d in editor_pass.intended(p))  # not in brief
    queue.undo_dismiss()
    wait_tasks(app)
    assert "intensifier:very" in _keys(p, "c2")                     # taken back


def test_skip_brings_it_back_later(app, tmp_path):
    p = _two_chapters(tmp_path)
    ed = chapter_editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    n = len(queue.entries)
    first = queue.entries[0].key
    queue.skip()
    assert len(queue.entries) == n and queue.entries[-1].key == first
    for _ in range(n - 1):
        queue.skip()
    assert queue.entries[queue.index].key == first                  # round again
    assert "skipped before" in ed.companion.panel.queue.status.text()


# ── D.3: the Style tab's issues in the queue; its switches in the Checks menu ──

STYLE_TEXT = ("It was a very long and winding road that went on and on past the farms and the "
              "fields and the woods and the river and the mill and the church and the school "
              "and the inn until at last it reached the sea where the boats were waiting.\n"
              "She ran. She ran. She ran again.\n")


def test_every_style_issue_is_in_the_queue_and_can_be_fixed_or_rewritten(app, tmp_path):
    from src.utils.style_checks import KINDS
    p = _project(tmp_path)
    p.manuscript.chapters[0].content = STYLE_TEXT
    cst.set_stage(p, None, ["c1"], "line")
    ed = chapter_editor(app, p)
    queue = ed.companion.queue
    queue.find()
    wait_tasks(app)
    in_queue = {(e.item.kind, e.item.start) for e in queue.entries}
    # D.6: the Style tab's list is the card's "every style issue" list.
    style_tab = {(e.item.kind, e.item.start) for e in queue._style_flags(every_kind=True)}
    assert style_tab and style_tab <= in_queue          # everything the Style tab lists
    assert any(e.check.startswith("style:") for e in queue.entries)
    entry = next(e for e in queue.entries if e.check.startswith("style:"))
    queue.index = queue.entries.index(entry)
    queue.show()
    asked = []
    ed.editor.style_rewrite_requested.disconnect()      # not the real dialog in a test
    ed.editor.style_rewrite_requested.connect(lambda a, b, why: asked.append(why))
    queue.more(ed.companion.panel.queue.fix)
    assert asked and asked[0].startswith("Fix the ")     # the Style tab's own ✨ rewrite
    queue.dismiss()                                      # its Ignore
    hl = ed.editor.writing_highlighter
    assert any(k == entry.item.kind for k, _t in hl._style_ignored)
    queue.undo_dismiss()
    wait_tasks(app)
    assert not any(k == entry.item.kind for k, _t in hl._style_ignored)


def test_the_style_switches_are_in_the_checks_menu_and_the_style_tab_follows(app, tmp_path):
    from src.utils.style_checks import KINDS
    p = _project(tmp_path)
    p.manuscript.chapters[0].content = STYLE_TEXT
    ed = chapter_editor(app, p)
    sub = next(a.menu() for a in ed.checks_menu.actions() if a.menu() is not None
               and a.text() == "Style checks")
    sub.aboutToShow.emit()                              # counted as the menu opens
    labels = [a.text() for a in sub.actions() if a.isCheckable()]
    assert len(labels) == len(KINDS) and any("(" in l and not l.endswith("(0)") for l in labels)
    assert "issue" in sub.actions()[0].text() and not sub.actions()[0].isEnabled()  # the summary
    names = [a.text() for a in ed.checks_menu.actions()]
    assert names.index("Style checks") == names.index("Style issues panel…") - 1
    act = ed._style_check_actions["adverb"]
    act.setChecked(False)
    assert "adverb" not in ed.editor.writing_highlighter._style_kinds
    act.setChecked(True)
    assert "adverb" in ed.editor.writing_highlighter._style_kinds
    # D.6: the Style tab is retired; the panel has Planner, Feedback, Companion.
    tabs = [ed.right_panel.tabText(i) for i in range(ed.right_panel.count())]
    assert "Style" not in tabs and len(tabs) == 3
