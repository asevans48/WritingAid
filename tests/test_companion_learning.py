"""The companion learns your style, knows when to speak, focuses on what
matters, and talks about any flag."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import style_sheet as ss
from src.models.project import Chapter, WriterProject


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.manuscript.chapters = [Chapter(id="c1", number=1, title="One", content="")]
    return p


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_judges():
    from src.ai import flag_judge as fj
    fj._CACHE.clear()
    yield
    fj._CACHE.clear()


# ── 1. The style sheet ────────────────────────────────────────────

@pytest.mark.parametrize("text,kind,subject,replacement", [
    ("allow vethari", "allow", "vethari", ""),
    ("vethari is a word", "allow", "vethari", ""),
    ("prefer grey over gray", "prefer", "gray", "grey"),
    ("grey, not gray", "prefer", "gray", "grey"),
    ("avoid very", "avoid", "very", ""),
    ("keep passive voice", "keep", "passive", ""),
    ("Fragments in dialogue are deliberate", "note", "", ""),
])
def test_rules_parse(text, kind, subject, replacement):
    assert ss.parse(text) == {"kind": kind, "subject": subject, "replacement": replacement}


def test_add_dedupes_and_typing_a_suggested_rule_keeps_it(project):
    r = ss.add(project, "", suggested=True, kind="avoid", subject="very")
    assert r.status == "suggested" and r.text == "Avoid “very”"
    assert ss.add(project, "avoid very") is r and r.status == "active"
    assert ss.add(project, "avoid very") is None


def test_style_sheet_survives_save_and_load(project, tmp_path):
    ss.add(project, "prefer grey over gray")
    path = tmp_path / "p.json"
    project.save_project(str(path))
    loaded = WriterProject.load_project(str(path))
    assert [(r.kind, r.subject, r.replacement) for r in loaded.style_sheet] == [("prefer", "gray", "grey")]


def editor(app, project, text):
    from types import SimpleNamespace as NS
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    ed.resize(800, 400)
    ed.show()
    ed.writing_highlighter.set_style_mode(CheckMode.REALTIME)
    ed.writing_highlighter.set_overuse_mode(CheckMode.REALTIME)
    ed.setPlainText(text)
    ed.set_project_vocabulary(project)
    ed.do_initial_check()
    return ed


def marks(ed, kind=None):
    from src.ui.enhanced_text_editor import ErrorType
    out = []
    for errs in ed.writing_highlighter._errors.values():
        for e in errs:
            if kind is None or e.error_type == kind or getattr(e, "style_kind", "") == kind:
                out.append(e.word)
    return out


def test_rules_change_what_the_checks_show(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    text = "The gray gate was barred. A vethari sang. She was very tired."
    ed = editor(app, project, text)
    assert "vethari" in marks(ed, ErrorType.SPELLING) and "was barred" in marks(ed, "passive")
    ss.add(project, "allow vethari")
    ss.add(project, "keep passive voice")
    ss.add(project, "prefer grey over gray")
    ss.add(project, "avoid very")
    ed.refresh_style_sheet()
    assert "vethari" not in marks(ed, ErrorType.SPELLING)
    assert "was barred" not in marks(ed, "passive")
    prefs = [e for errs in ed.writing_highlighter._errors.values() for e in errs
             if getattr(e, "style_kind", "") == "preference"]
    assert {e.word for e in prefs} == {"gray", "very"}
    gray = next(e for e in prefs if e.word == "gray")
    assert gray.suggestions == ["grey"] and "Your style sheet" in gray.reason


def test_kept_kind_still_shows_when_a_model_confirms_it(app, project):
    from src.ai import flag_judge as fj
    from src.ai.word_suggest import sentence_around
    text = "The gate was barred by somebody."
    ss.add(project, "keep passive voice")
    ed = editor(app, project, text)
    assert "was barred" not in marks(ed, "passive")
    fj.remember({fj.key("style", "was barred", sentence_around(text, 9, 19).text, "passive"):
                 (True, "hides who acted")})
    ed.refresh_style_sheet()
    assert "was barred" in marks(ed, "passive")


def test_allowed_word_is_not_an_overused_word(app, project):
    text = "The vethari sang. The vethari wept. The vethari slept. The vethari woke."
    ed = editor(app, project, text)
    assert any(w.lower() == "vethari" for w in marks(ed))
    ss.add(project, "allow vethari")
    ed.refresh_style_sheet()
    assert not any(w.lower() == "vethari" for w in marks(ed))


def test_it_learns_from_ignores_and_fixes(app, project):
    from PyQt6.QtGui import QTextCursor
    from src.ui.enhanced_text_editor import ErrorType, WritingError
    ed = editor(app, project, "x")
    learned = []
    ed.style_sheet_changed.connect(learned.append)
    for _ in range(3):
        ed.writing_highlighter.ignore_style_issue("passive", "was barred")
    for _ in range(2):
        ed._ignore_error(0, 0, "Vethari", ErrorType.SPELLING)
    for _ in range(3):
        ed.setPlainText("It was very cold.")
        cur = QTextCursor(ed.document())
        cur.setPosition(7)
        cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
        error = WritingError(ErrorType.STYLE, "very", 7, 11, "Weak intensifier", [""])
        error.style_kind = "intensifier"
        ed._apply_fix(cur, "", error)
    suggested = {(r.kind, r.subject) for r in project.style_sheet if r.status == "suggested"}
    assert suggested == {("keep", "passive"), ("allow", "vethari"), ("avoid", "very")}
    assert len(learned) == 3 and learned[0].startswith("💡 Suggested for your style sheet")


def test_style_sheet_reaches_the_prompts(project):
    ss.add(project, "avoid very")
    from src.ai import companion, passage_critique as pc
    text = "Mara was very tired."
    assert "Avoid “very”" in pc.build_prompt(pc.build_context(project, None, text, 0, len(text)))
    assert "Avoid “very”" in companion.judge_context(project, None, text)
    from types import SimpleNamespace as NS
    from src.ui.rephrase_dialog import RephraseDialog
    assert "Avoid “very”" in RephraseDialog._memory_block(
        NS(project=project, surrounding_before="", original_text=text))
    from src.ai import flag_judge as fj, repetition_judge as rj
    assert "Avoid “very”" in rj.build_prompt([{"key": "w:x", "text": "x", "count": 3,
                                                "sentences": ["x"]}], ss.prompt_block(project))
    assert "Avoid “very”" in fj.build_prompt("style", [{"key": "k", "text": "very", "detail": "",
                                                        "sentence": text}], ss.prompt_block(project))


# ── 2. Drafting and revising ──────────────────────────────────────

TEXT = "The gate was barred by the Wardens. She walked very slowly. Tobin recieved it."


def test_drafting_shows_only_spelling(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    ed = editor(app, project, TEXT)
    assert marks(ed, "passive")
    ed.set_phase_setting("drafting")
    kinds = {e.error_type for errs in ed.writing_highlighter._errors.values() for e in errs}
    assert kinds == {ErrorType.SPELLING}
    ed.set_phase_setting("revising")
    assert marks(ed, "passive")


def test_auto_switches_with_how_you_write(app, project):
    ed = editor(app, project, "\n".join([TEXT] * 6))
    ed.set_phase_setting("auto")
    phases = []
    ed.phase_changed.connect(phases.append)
    ed._update_phase()                                     # baseline sample
    cursor = ed.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" " + "and then the tide came in over the stones " * 2)
    ed.setTextCursor(cursor)
    ed._update_phase()
    assert ed.writing_highlighter.phase == "drafting"
    cursor.setPosition(3)
    ed.setTextCursor(cursor)
    ed._update_phase()
    assert ed.writing_highlighter.phase == "revising" and phases == ["drafting", "revising"]


def test_one_long_paragraph_still_has_an_elsewhere(app, project):
    ed = editor(app, project, " ".join([TEXT] * 8))
    ed.set_phase_setting("auto")
    ed._update_phase()
    cursor = ed.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" " + "and then the tide came in over the stones " * 2)
    ed.setTextCursor(cursor)
    ed._update_phase()
    assert ed.writing_highlighter.phase == "drafting"
    cursor.setPosition(3)
    ed.setTextCursor(cursor)
    ed._update_phase()
    assert ed.writing_highlighter.phase == "revising"


def test_manual_mode_is_not_overridden(app, project):
    ed = editor(app, project, TEXT)
    ed.set_phase_setting("revising")
    cursor = ed.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" " + "more words " * 10)
    ed._update_phase()
    assert ed.writing_highlighter.phase == "revising"


def test_checks_menu_has_modes_and_shows_drafting(app, project):
    from src.ui.manuscript_editor import ChapterEditor
    ce = ChapterEditor(Chapter(id="c1", number=1, title="One", content=TEXT), project=project)
    assert set(ce._phase_actions) == {"auto", "drafting", "revising"}
    ce._phase_actions["drafting"].trigger()
    assert "✍ drafting" in ce.checks_btn.text() and ce.checks_btn.text().startswith("✓ Checks · ")


# ── 3. Focus and today's three fixes ──────────────────────────────

def test_focus_keeps_the_top_two_per_paragraph(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    text = "Tobin recieved it very slowly, and the gate was barred by them in order to wait."
    ed = editor(app, project, text)
    assert len(ed.writing_highlighter._errors[0]) > 2
    ed.set_focus(True)
    kept = ed.writing_highlighter._errors[0]
    assert len(kept) == 2
    assert ErrorType.SPELLING in {e.error_type for e in kept}   # the typo always outranks style
    ed.set_focus(False)
    assert len(ed.writing_highlighter._errors[0]) > 2


def test_three_fixes_quick_and_with_a_model(app, project):
    from src.ai import companion
    text = ("He recieved it.\nShe walked very slowly.\nThe gate was barred.\n"
            "It was decided that they wait.")
    ed = editor(app, project, text)
    cands = companion.fix_candidates(ed.writing_highlighter, ed.document())
    quick = companion.three_fixes_quick(cands)
    assert len(quick) == 3 and "recieved" in quick[0].text
    assert len({f.excerpt for f in quick}) == 3

    class Picker:
        def generate_text(self, prompt, system_prompt=None, **kw):
            lines = [l for l in prompt.splitlines() if l[:1].isdigit()]
            n = next(i for i, l in enumerate(lines, 1) if "decided" in l)
            return f"PICK {n} — hides who made the choice\nPICK 1 — a reader trips on it"

    fixes = companion.three_fixes(Picker(), cands)
    assert "decided" in fixes[0].excerpt and fixes[0].why == "hides who made the choice"


def test_companion_panel_finds_fixes_and_jumps(app, project):
    from src.ui import companion_panel
    from src.ui.manuscript_editor import ChapterEditor
    ce = ChapterEditor(Chapter(id="c1", number=1, title="One",
                               content="He recieved it.\nShe walked very slowly."),
                       project=project)
    ce.companion.find_three_fixes()
    for t in list(companion_panel._RUNNING):
        t.wait(5000)
    app.processEvents()
    card = ce.companion.panel.queue                 # D.6: the three show on the card
    assert card.fix is not None and "recieved" in card.fix.text
    card.goto_btn.click()
    assert ce.editor.textCursor().selectedText() == "He recieved it."


# ── 5. 💬 Ask ──────────────────────────────────────────────────────

class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def wait_dialog(dlg, app):
    if dlg._chat_worker is not None:
        dlg._chat_worker.wait(5000)
    app.processEvents()


def ask_dialog(app, project, llm, **kw):
    from src.ui.flag_chat_dialog import FlagChatDialog
    para = "The gate was barred by the Wardens before dusk. Mara waited."
    replaced = {}
    rules = []
    dlg = FlagChatDialog(paragraph=para, start=9, end=19, category=kw.get("category", "style"),
                         word="was barred", reason="Passive voice", kind="passive",
                         project=project, llm_factory=lambda: llm,
                         on_replace=lambda old, new: replaced.update(old=old, new=new) or True,
                         on_rule=rules.append)
    return dlg, replaced, rules


def test_ask_explains_offers_versions_and_uses_one(app, project):
    llm = FakeLLM("It hides who barred it — the Wardens are the point.\n\nVERSION 1 (active):\n"
                  "The Wardens barred the gate before dusk.\nWHY: puts them first")
    dlg, replaced, _ = ask_dialog(app, project, llm)
    assert dlg.sentence == "The gate was barred by the Wardens before dusk."
    dlg.send("why is this a problem?")
    wait_dialog(dlg, app)
    assert "hides who barred it" in dlg.chat.plain_text()
    assert "THE FLAG" in llm.prompts[0] and "Passive voice" in llm.prompts[0]
    dlg.versions_list.setCurrentRow(0)
    dlg.use_selected()
    assert replaced == {"old": "The gate was barred by the Wardens before dusk.",
                        "new": "The Wardens barred the gate before dusk."}


def test_saying_its_deliberate_adds_a_rule(app, project):
    llm = FakeLLM("Understood — the focus on the gate is the point.")
    dlg, _, rules = ask_dialog(app, project, llm)
    dlg.send("It's deliberate — the gate matters here, remember that.")
    wait_dialog(dlg, app)
    assert [(r.kind, r.subject) for r in project.style_sheet] == [("keep", "passive")]
    assert rules and "Added to your style sheet" in dlg.chat.status.text()


def test_ask_without_a_model_still_marks_deliberate(app, project):
    dlg, _, _ = ask_dialog(app, project, None, category="spelling")
    dlg.send("why?")
    wait_dialog(dlg, app)
    assert "needs a local or cloud model" in dlg.chat.plain_text()
    dlg.word = "vethari"
    dlg.mark_deliberate()
    assert [(r.kind, r.subject) for r in project.style_sheet] == [("allow", "vethari")]


def test_card_and_menu_offer_ask(app, project, monkeypatch):
    from PyQt6.QtWidgets import QPushButton
    ed = editor(app, project, "The gate was barred by the Wardens before dusk.")
    rect = ed.cursorRect(ed._cursor_at(12))
    assert ed._show_error_tooltip(ed.viewport().mapToGlobal(rect.center()), rect.center())
    assert "💬 Ask" in {b.text() for b in ed.error_card.findChildren(QPushButton)}
    labels = []
    monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", lambda self, *a: labels.extend(
        a.text() for a in self.actions()))
    ed._show_context_menu(rect.center())
    assert "💬 Ask about this…" in labels


# ── Spelling and grammar always show; overuse when it makes sense ──

ERRORS = ("She could of gone home. They was late. The bell rang and rang. "
          "\"Hello,\" she said, \"i am here.\" The vethril glowed.")


def kinds_shown(ed):
    out = {}
    for errs in ed.writing_highlighter._errors.values():
        for e in errs:
            out.setdefault(e.error_type, []).append(e.word)
    return out


def test_every_check_is_on_by_default(app, project):
    from src.ui.manuscript_editor import ChapterEditor
    ed = editor(app, project, ERRORS)
    assert ed.phase_setting == "revising" and ed.writing_highlighter.phase == "revising"
    cursor = ed.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" " + "and the tide came in over the old stones " * 3)
    ed._update_phase()                       # writing at the end no longer hides anything
    assert ed.writing_highlighter.phase == "revising"
    ce = ChapterEditor(Chapter(id="c1", number=1, title="One", content=ERRORS), project=project)
    assert ce._phase_actions["revising"].isChecked()


def test_drafting_keeps_spelling_and_grammar(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    ed = editor(app, project, ERRORS)
    ed.set_phase_setting("drafting")
    shown = kinds_shown(ed)
    assert {"could of", "was", "i"} <= set(shown[ErrorType.GRAMMAR])
    assert "vethril" in shown[ErrorType.SPELLING]
    assert ErrorType.STYLE not in shown and ErrorType.OVERUSE not in shown


def test_a_model_cannot_hide_grammar_it_only_comments(app, project):
    from src.ai import flag_judge as fj
    from src.ai.word_suggest import sentence_around
    from src.ui.enhanced_text_editor import ErrorType
    fj.remember({fj.key("grammar", "could of", sentence_around(ERRORS, 4, 12).text):
                 (False, "dialect, fine here")})
    ed = editor(app, project, ERRORS)
    g = [e for errs in ed.writing_highlighter._errors.values() for e in errs
         if e.error_type == ErrorType.GRAMMAR and e.word == "could of"]
    assert g and "Editor's view: may be fine — dialect, fine here" in g[0].reason


def test_real_slips_in_dialogue_still_show(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    ed = editor(app, project, ERRORS)
    assert "i" in kinds_shown(ed)[ErrorType.GRAMMAR]      # inside quotes, still marked


def test_lowercase_misspelling_always_shows(app, project):
    from src.ai import flag_judge as fj
    from src.ui.enhanced_text_editor import ErrorType
    fj.remember({fj.key("spelling", "recieved"): (False, "deliberate")})
    text = "He recieved one. She recieved two. They recieved three. Tobin smiled."
    ed = editor(app, project, text)
    assert kinds_shown(ed)[ErrorType.SPELLING].count("recieved") == 3   # model + 3 uses: still marked
    fj.remember({fj.key("spelling", "Tobin"): (False, "a name")})
    ed.refresh_style_sheet()
    assert "Tobin" not in kinds_shown(ed).get(ErrorType.SPELLING, [])    # a name may be excused
    ss.add(project, "allow recieved")                                    # …or the writer allows it
    ed.refresh_style_sheet()
    assert ErrorType.SPELLING not in kinds_shown(ed)


def test_focus_never_hides_spelling_or_grammar(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    text = "She could of gone very slowly. They was late. He recieved it. It was decided by them."
    ed = editor(app, project, text)
    before = kinds_shown(ed)
    ed.set_focus(True)
    after = kinds_shown(ed)
    assert after[ErrorType.SPELLING] == before[ErrorType.SPELLING]
    assert sorted(after[ErrorType.GRAMMAR]) == sorted(before[ErrorType.GRAMMAR])
    assert ErrorType.STYLE not in after          # the paragraph's slots went to the errors


def test_a_close_repeat_shows_even_if_a_model_says_fine(app, project):
    from src.ui.enhanced_text_editor import ErrorType
    far = " ".join(["Filler words keep the pages turning onward."] * 12)
    text = (f"The lantern swung. The lantern dimmed. The lantern died. {far} The cart creaked by. {far} "
            f"The cart stopped. {far} The cart rolled on.")
    ed = editor(app, project, text)
    ed.overuse_detector.apply_verdicts({"w:lantern": (False, "fine"), "w:cart": (False, "fine")})
    ed.writing_highlighter.update_full_text(ed.toPlainText())
    ed.writing_highlighter.rehighlight()
    over = [w.lower() for w in kinds_shown(ed).get(ErrorType.OVERUSE, [])]
    assert "lantern" in over                  # two uses a few words apart: a reader hears it
    assert "cart" not in over                 # spread out: the model's call stands
    assert not any(i["text"] == "lantern" for i in ed.overuse_detector.review_items())


def test_a_lenient_model_cannot_wipe_out_style_flags():
    from src.ai import flag_judge as fj

    class Lenient:
        def generate_text(self, prompt, system_prompt=None, **kw):
            n = sum(1 for l in prompt.splitlines() if l[:1].isdigit() and "“" in l)
            return "\n".join(f"{i}. DROP — fine" for i in range(1, n + 1))

    items = [{"key": f"k{i}", "text": f"w{i}", "detail": "", "sentence": "s"} for i in range(4)]
    assert all(keep for keep, _ in fj.judge(Lenient(), "style", items).values())
    items2 = [{"key": f"g{i}", "text": f"w{i}", "detail": "", "sentence": "s"} for i in range(4)]
    assert not any(keep for keep, _ in fj.judge(Lenient(), "grammar", items2).values())
