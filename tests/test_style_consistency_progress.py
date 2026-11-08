"""Inline style checks + panel, the consistency checker, and critique
progress tracking across revisions."""

import os
import time
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils.style_checks import analyze_document, analyze_paragraph, summarize
from src.utils.consistency_checks import ConsistencyChecker, apply_group, number_to_words


# ── 1. Style checks ───────────────────────────────────────────────

def _kinds(text):
    return [(i.kind, i.text) for i in analyze_paragraph(text)]


@pytest.mark.parametrize("text,kind,flagged", [
    ("The map was taken by the guards.", "passive", "was taken"),
    ("The letters were written in haste.", "passive", "were written"),
    ("She ran quickly.", "adverb", "quickly"),
    ("It was very cold.", "intensifier", "very"),
    ("He left in order to think.", "wordy", "in order to"),
    ("She made a decision to go.", "wordy", "made a decision"),
    ("It was crystal clear.", "cliche", "crystal clear"),
    ("She ran. She hid. She waited.", "repeated_start", "She"),
    ("The lantern swung and the lantern died.", "echo", "lantern"),
])
def test_style_detectors(text, kind, flagged):
    assert (kind, flagged) in _kinds(text)


@pytest.mark.parametrize("text", [
    "She was tired and scared.",          # adjectives, not passive
    "The only family she had was early.",  # -ly words that aren't adverbs
    "Mara walked to the pier.",
])
def test_style_detectors_avoid_false_positives(text):
    kinds = {k for k, _ in _kinds(text)}
    assert not kinds & {"passive", "adverb"}, _kinds(text)


def test_sentence_level_checks_and_document_offsets():
    long = " ".join(["word"] * 35) + "."
    hard = ("Notwithstanding considerable institutional resistance, the administration's "
            "comprehensive reorganization ultimately facilitated unprecedented "
            "interdepartmental collaboration among historically antagonistic constituencies.")
    text = "Short one.\n" + long + "\n" + hard
    issues = analyze_document(text)
    long_issue = next(i for i in issues if i.kind == "long_sentence")
    assert text[long_issue.start:long_issue.end] == long and long_issue.sentence_level
    hard_issue = next(i for i in issues if i.kind == "hard_sentence")
    assert text[hard_issue.start:hard_issue.end] == hard
    s = summarize(issues, len(text.split()))
    assert s["total"] == len(issues) and s["by_kind"]["long_sentence"] == 1


def test_wordy_fix_keeps_capitalisation():
    issue = next(i for i in analyze_paragraph("In order to win, she ran.") if i.kind == "wordy")
    assert issue.suggestions == ["To"]


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def chapter_editor(app, monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor

    def make(text):
        return ChapterEditor(Chapter(id="c1", number=1, title="One", content=text),
                             project=WriterProject(name="t"))
    return make


def _formats(editor):
    out = []
    b = editor.document().begin()
    while b.isValid():
        for f in b.layout().formats():
            out.append((b.text()[f.start:f.start + f.length], f.format))
        b = b.next()
    return out


def test_style_highlighting_and_panel_fixes(chapter_editor):
    from src.ui.enhanced_text_editor import CheckMode, ErrorType
    ed = chapter_editor("She very quickly ran to the door in order to escape. Tommorow she left.")
    assert not any(f.underlineColor().name() == "#16a34a" for _, f in _formats(ed.editor))
    ed._toggle_style_check()                                   # on
    assert ed.editor.get_style_mode() == CheckMode.ON_DEMAND
    fm = _formats(ed.editor)
    assert any(t == "in order to" and f.underlineColor().name() == "#16a34a" for t, f in fm)
    # Misspelling still wins on hover inside a style-tinted sentence.
    hl = ed.editor.writing_highlighter
    pos = ed.editor.toPlainText().index("Tommorow") + 2
    assert hl.get_error_at(0, pos).error_type == ErrorType.SPELLING
    panel = ed.style_panel
    panel.refresh()
    kinds = [i.kind for _, _, i in panel._shown]
    assert {"intensifier", "adverb", "wordy"} <= set(kinds)
    panel.list.setCurrentRow(kinds.index("wordy"))
    assert panel.fix_btn.text() == "Fix → “to”"
    panel._fix()
    panel.list.setCurrentRow([i.kind for _, _, i in panel._shown].index("intensifier"))
    panel._fix()
    assert ed.editor.toPlainText().startswith("She quickly ran to the door to escape.")
    # Toggling a check off removes it from the list.
    panel.kind_boxes["adverb"][0].setChecked(False)
    assert "adverb" not in [i.kind for _, _, i in panel._shown]
    ed._toggle_style_check()                                   # off
    assert ed.editor.get_style_mode() == CheckMode.OFF


def test_rewrite_with_ai_selects_sentence_and_passes_hint(chapter_editor, monkeypatch):
    ed = chapter_editor("First line here. The map was taken by the guards at dawn. Last.")
    got = []
    ed.editor.style_rewrite_requested.disconnect()
    ed.editor.style_rewrite_requested.connect(lambda a, b, h: got.append((a, b, h)))
    panel = ed.style_panel
    panel.refresh()
    panel.list.setCurrentRow([i.kind for _, _, i in panel._shown].index("passive"))
    panel._rewrite()
    a, b, hint = got[0]
    assert ed.editor.toPlainText()[a:b] == "The map was taken by the guards at dawn."
    assert hint.startswith("Fix the passive voice")


def test_context_menu_replacement_uses_exact_span(chapter_editor):
    ed = chapter_editor("He left in order to think.")
    from PyQt6.QtGui import QTextCursor
    cur = QTextCursor(ed.editor.document())
    cur.setPosition(8)
    cur.setPosition(19, QTextCursor.MoveMode.KeepAnchor)
    ed.editor._replace_word(cur, "to")
    assert ed.editor.toPlainText() == "He left to think."
    cur = QTextCursor(ed.editor.document())
    cur.setPosition(3)
    cur.setPosition(7, QTextCursor.MoveMode.KeepAnchor)       # delete "left"
    ed.editor._replace_word(cur, "")
    assert ed.editor.toPlainText() == "He to think."


# ── 2. Consistency ────────────────────────────────────────────────

CHS = [("c1", "One", 'Mara walked past the grey wall. Marra laughed. The Council met. '
        '"Hi," she said... The ash wardens came. Ash Wardens ruled. It was okay. '
        'She had 3 coins and two daggers. An e-mail arrived.'),
       ("c2", "Two", "The gray sky over Greywater and Grewater. The council was quiet. The "
        "Council voted. OK then… An email too. Three men came, with 4 dogs. “Go,” he said. "
        "Towards the sea; toward home. The grey cat.")]
CANON = ["Mara", "Ash Wardens", "Greywater", "Tobin"]


def _groups():
    return {g.key: g for g in ConsistencyChecker(CHS, CANON).run()}


def test_consistency_finds_every_kind():
    g = _groups()
    assert [o.text for o in g["name:Mara"].changes()] == ["Marra"]
    assert [o.text for o in g["name:Greywater"].changes()] == ["Grewater"]
    assert [o.text for o in g["case:Ash Wardens"].changes()] == ["ash wardens"]
    grey = g["variant:grey/gray"]
    assert grey.preferred == "grey" and [o.text for o in grey.changes()] == ["gray"]
    assert [o.text for o in grey.changes("gray")] == ["grey", "grey"]
    assert [o.text for o in g["variant:okay/ok/o.k."].changes()] == ["OK"]
    assert g["variant:okay/ok/o.k."].replacement_for(g["variant:okay/ok/o.k."].changes()[0], "okay") == "Okay"
    assert "hyphen:email" in g
    assert g["caps:council"].review
    assert [(o.text, o.replacement) for o in g["numbers"].changes()] == [("3", "three"), ("4", "four")]
    assert [o.replacement for o in g["quotes"].changes()] == ["“", "”"]
    assert [o.replacement for o in g["ellipsis"].changes()] == ["…"]


def test_consistency_any_form_can_be_chosen_and_applied():
    grey = _groups()["variant:grey/gray"]
    assert grey.targets == ["grey", "gray"]
    texts = {c[0]: c[2] for c in CHS}
    new, n = apply_group(grey, "gray", texts)
    assert n == 2 and "gray wall" in new["c1"] and "The gray cat" in new["c2"]
    # Edited-since occurrences are skipped, not corrupted.
    texts["c2"] = texts["c2"].replace("The gray sky", "A blue sky!!")
    new, n = apply_group(grey, "grey", texts)
    assert n == 0 and "A blue sky!!" in new["c2"]


def test_numbers_helper():
    assert [number_to_words(n) for n in (3, 15, 40, 42)] == ["three", "fifteen", "forty", "forty-two"]


def test_apply_consistency_in_open_and_closed_chapters(app):
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    from src.ui.main_window import MainWindow
    p = WriterProject(name="t")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content=CHS[0][2]),
                             Chapter(id="c2", number=2, title="Two", content=CHS[1][2])]
    me = ManuscriptEditor(p)
    me.load_manuscript(p.manuscript)
    me.open_chapter("c1")
    changed = []
    win = NS(current_project=p, manuscript_editor=me, _on_content_changed=lambda: changed.append(1),
             statusBar=lambda: NS(showMessage=lambda *a: None))
    win._chapters_for_links = MainWindow._chapters_for_links.__get__(win)
    chapters = MainWindow._consistency_chapters(win, "manuscript")
    group = next(g for g in ConsistencyChecker(chapters, CANON).run() if g.key == "variant:grey/gray")
    n = MainWindow._apply_consistency(win, group, "gray")
    assert n == 2 and changed
    assert "gray wall" in me.current_chapter_editor.editor.toPlainText()   # open chapter, via editor
    assert "The gray cat" in p.manuscript.chapters[1].content               # closed chapter, model
    me.current_chapter_editor.editor.undo()
    assert "grey wall" in me.current_chapter_editor.editor.toPlainText()   # one undo step


def test_consistency_dialog_lists_groups(app):
    from src.ui.consistency_dialog import ConsistencyDialog
    applied = []
    dlg = ConsistencyDialog(lambda scope: CHS, CANON, navigate=lambda *a: applied.append(("nav", a)),
                            apply_changes=lambda g, t: applied.append((g.key, t)) or 1)
    tops = [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())]
    assert tops[0].startswith("Name spellings") and any(t.startswith("Punctuation") for t in tops)
    group_item = dlg.tree.topLevelItem(0).child(0)
    dlg.tree.setCurrentItem(group_item)
    assert dlg.apply_btn.isEnabled() and dlg.apply_btn.text() == "Change all (1)"
    dlg.tree.setCurrentItem(group_item.child(0))
    dlg._jump(group_item.child(0))
    dlg.tree.setCurrentItem(group_item)
    dlg._apply()
    assert applied[0][0] == "nav" and applied[1] == ("name:Mara", "Mara")
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0).child(0))
    dlg._ignore()
    assert "name:Mara" in dlg.ignored


# ── 6. Progress across revisions ──────────────────────────────────

def _report(majors, style_total, words=1000, metrics=None):
    from src.ai.chapter_analysis_agent import (
        ChapterReport, CritiqueReport, ReportSection, ReportType, resolve_genre_profile)
    s = ReportSection(report_type=ReportType.STYLE, chapter_title="One",
                      major_issues=list(majors), metrics=metrics or {})
    r = CritiqueReport(chapters=[ChapterReport("One", 0, words, [s])],
                       genre=resolve_genre_profile("default"))
    r.style_stats = {"One": {"total": style_total, "words": words, "by_kind": {},
                             "per_1000": round(style_total * 1000 / words, 1)}}
    return r


def test_progress_tracking_across_runs():
    from src.data.critique_history import format_progress_markdown, record
    proj = NS(project_path="", name="t")
    assert record(proj, _report(["Passive voice 18% above genre cap 10%.",
                                 "Mara — Fears: dives in fearlessly"], 40,
                                metrics={"passive_pct": 18.0, "flesch_reading_ease": 60.0})) is None
    prog = record(proj, _report(["Passive voice 12% above genre cap 10%.",
                                 "Tobin — Speaking style: suddenly formal"], 25,
                                metrics={"passive_pct": 12.0, "flesch_reading_ease": 68.0}))
    ch = prog["chapters"][0]
    assert ch["majors"] == [2, 2] and ch["style"][:2] == (40, 25)
    assert [f for _, f in ch["fixed"]] == ["Mara — Fears: dives in fearlessly"]
    assert [n for _, n in ch["new"]] == ["Tobin — Speaking style: suddenly formal"]
    assert ("Passive %", 18.0, 12.0, True) in ch["metrics"]
    assert ("Reading ease", 60.0, 68.0, True) in ch["metrics"]
    md = format_progress_markdown(prog)
    assert "style issues 40 → 25 ▼✓" in md and "✓ fixed" in md and "History" in md


def test_grader_records_and_shows_progress(app, monkeypatch):
    import src.ai.task_llm as tl
    from src.ai.chapter_analysis_agent import ReportType
    from src.models.project import Chapter, WriterProject
    from src.ui.grader_widget import GraderWidget
    monkeypatch.setattr(tl, "build_critique_llm", lambda spec="": None)
    monkeypatch.setattr(tl, "build_default_llm", lambda: None)
    from PyQt6.QtCore import QCoreApplication
    p = WriterProject(name="t")
    text = "The map was taken by the guards. She very quickly ran in order to escape."
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content=text)]
    g = GraderWidget()
    g.set_project(p)
    reports = []
    for content in (text, "The guards took the map. She ran."):
        p.manuscript.chapters[0].content = content
        assert g.run_manuscript_critique(None, report_types=[ReportType.STYLE], confirm=False,
                                         on_done=lambda r, e: reports.append(r)) is None
        g._worker.wait(30000)
        end = time.time() + 5
        n = len(reports)
        while len(reports) == n - 0 and time.time() < end and len(reports) < (2 if content != text else 1):
            QCoreApplication.processEvents()
            time.sleep(0.01)
    assert reports[0].progress is None and reports[0].style_stats["One"]["total"] > 0
    prog = reports[1].progress
    assert prog and prog["chapters"][0]["style"][1] < prog["chapters"][0]["style"][0]
    assert "Progress since the last critique" in g._format_summary_html(reports[1])


def test_name_case_flagged_even_without_a_correct_occurrence():
    groups = {g.key: g for g in ConsistencyChecker(
        [("c1", "One", "The ash wardens watched. Later the ash wardens left.")],
        ["Ash Wardens"]).run()}
    assert [o.text for o in groups["case:Ash Wardens"].changes()] == ["ash wardens"] * 2
