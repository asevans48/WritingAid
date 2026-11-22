"""The writing companion: where you left off, notes as you write,
reader's-eye pass, story memory."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import companion as cp
from src.ai import story_memory as sm
from src.data import companion_state as cs
from src.models.project import (Chapter, ChapterTodo, Character, StoryEvent, StoryPromise,
                                WriterProject)


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist",
                              physical_description="Tall, grey eyes, black hair cut short.",
                              speaking_style="clipped; never says please"),
                    Character(id="t", name="Tobin", character_type="major")]
    p.story_planning.promises = [StoryPromise(id="p", promise_type="plot",
                                              title="Mara frees her brother")]
    ch = Chapter(id="c1", number=3, title="Night Run", content="")
    ch.planning.pov_character = "Mara Venn"
    ch.planning.events = [StoryEvent(id="e1", text="Meet Tobin at the pier", completed=True),
                          StoryEvent(id="e2", text="Slip past the patrol boat",
                                     description="the patrol lamp nearly finds them")]
    ch.planning.todos = [ChapterTodo(id="t1", text="Plant the key earlier")]
    p.manuscript.chapters = [ch]
    return p


def chapter(project):
    return project.manuscript.chapters[0]


# ── Story memory ──────────────────────────────────────────────────

def test_memory_add_dedupe_pin_and_relevance(project):
    a = sm.add(project, "Tobin doesn't know about the schedule.")
    assert sm.add(project, "Tobin doesn't know about the schedule") is None
    sm.add(project, "The pier burns in chapter nine.")
    sm.add(project, "Mara never apologises.", pinned=True)
    picked = sm.relevant(project, "Tobin rowed toward the schedule board", limit=2)
    assert picked[0].text == "Mara never apologises." and picked[1] is a
    block = sm.prompt_block(project, "Tobin")
    assert block.startswith("STORY DECISIONS") and "Mara never apologises." in block


def test_suggested_entries_stay_out_of_prompts_until_kept(project):
    e = sm.add(project, "The key is sewn into Mara's coat.", suggested=True)
    assert "key is sewn" not in sm.prompt_block(project, "key coat")
    sm.accept(project, e.id)
    assert "key is sewn" in sm.prompt_block(project, "key coat")


def test_memory_survives_save_and_load(project, tmp_path):
    sm.add(project, "Tobin doesn't know about the schedule.", pinned=True)
    path = tmp_path / "p.json"
    project.save_project(str(path))
    loaded = WriterProject.load_project(str(path))
    assert [(e.text, e.pinned) for e in loaded.story_memory] == [
        ("Tobin doesn't know about the schedule.", True)]


def test_older_projects_load_without_memory(tmp_path):
    p = WriterProject(name="Old")
    path = tmp_path / "old.json"
    p.save_project(str(path))
    import json
    data = json.loads(path.read_text())
    data.pop("story_memory", None)
    path.write_text(json.dumps(data))
    assert WriterProject.load_project(str(path)).story_memory == []


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def test_decisions_extracted_only_when_the_writer_settles_something():
    llm = FakeLLM("DECISION: Tobin doesn't know about the schedule.\nDECISION: NONE")
    assert sm.extract_decisions(llm, "What do you think of chapter 3?") == []
    assert llm.prompts == []
    got = sm.extract_decisions(llm, "Let's keep it so Tobin doesn't know about the schedule.")
    assert got == ["Tobin doesn't know about the schedule."]


# ── Where you left off ────────────────────────────────────────────

def test_left_off_card(project):
    before = {"last_session": "2026-11-14T21:10", "words_at_open": 1000, "words_at_close": 1430,
              "stopped_at": "She checked the key again."}
    brief = cp.left_off(project, chapter(project), "text", before, words_today=250, goal=500)
    text = "\n".join(brief.lines)
    assert "added 430 words" in text and "She checked the key again." in text
    assert "Next beat: Slip past the patrol boat" in text
    assert "To do: Plant the key earlier" in text and "250 of 500 words" in text
    assert brief.headline.startswith("Where you left off — last time added 430 words")


def test_first_visit_has_no_last_time(project):
    brief = cp.left_off(project, chapter(project), "", {})
    assert not any(l.startswith("Last time") for l in brief.lines)


def test_session_state_round_trip(project):
    before = cs.mark_opened(project, "c1")
    assert before == {}
    cs.record_session(project, "c1", 100, 340, "The fog closed in.")
    again = cs.mark_opened(project, "c1")
    assert again["words_at_close"] == 340 and again["stopped_at"] == "The fog closed in."
    assert cs.words_today(project) == 240
    cs.record_session(project, "c1", 100, 360, "x")        # same session, updated
    assert cs.words_today(project) == 260                  # the session's latest growth


def test_recap_text_stops_where_the_writer_did():
    text = "One. Two. Three. Four."
    assert cp.recap_text_before(text, "Two.") == "One. Two."
    assert cp.recap_text_before(text, "missing") == text


# ── Notes as you write ────────────────────────────────────────────

def notes_for(project, paragraph, voice=None, profiles=None):
    return cp.paragraph_notes(project, chapter(project), [paragraph], [0], voice, profiles)


def test_head_hop_note(project):
    n = notes_for(project, "The lamp swung past. Tobin wondered if she had sold them out, "
                           "and Mara kept rowing.")
    assert [x.kind for x in n] == ["pov"] and "Tobin wondered" in n[0].excerpt


def test_no_head_hop_inside_dialogue_or_for_the_pov_character(project):
    assert notes_for(project, '"Tobin thought you were dead," Mara said, and she wondered '
                              'why she had come back at all.') == []


def test_tense_slip_note(project):
    from types import SimpleNamespace as NS
    n = notes_for(project, "Mara walks to the pier. She looks at the water and she sees the "
                           "lamp. It is close.", voice=NS(tense="past"))
    assert any(x.kind == "tense" and "present" in x.text for x in n)


def test_beat_written_note_offers_to_mark_it_done(project):
    n = notes_for(project, "They slipped past the patrol boat while the lamp swept over the "
                           "water, so close she could hear the men laughing.")
    beat = [x for x in n if x.kind == "beat"]
    assert beat and beat[0].action == {"type": "mark_beat", "event_id": "e2"}


def test_appearance_contradiction_note(project):
    n = notes_for(project, "Mara Venn turned, her green eyes bright in the lamplight, and "
                           "pushed the boat off.")
    assert any(x.kind == "appearance" and "grey" in x.text and "green" in x.text for x in n)
    assert not any(x.kind == "appearance" for x in notes_for(
        project, "Mara Venn turned, her grey eyes bright in the lamplight, and pushed off."))


def test_out_of_character_line_note(project):
    from src.ai.dialogue_craft import speech_profiles
    n = notes_for(project, '"Please, stay calm and keep rowing," Mara said, and Tobin rowed.',
                  profiles=speech_profiles(project))
    assert any(x.kind == "voice" and "never do" in x.text for x in n)


def test_judge_keeps_real_notes_drops_false_alarms_and_adds_one():
    paras = {0: "Para zero.", 2: "Tobin wondered if she lied."}
    notes = [cp.Note("pov", "Head-hop?", 2, "Tobin wondered"), cp.Note("tense", "Slip?", 0, "x")]
    llm = FakeLLM("1. KEEP\n2. DROP\nNOTE P0: Mara apologises, but she never does.")
    kept = cp.judge_notes(llm, paras, notes, "context")
    assert [n.kind for n in kept] == ["pov", "ai"] and "never does" in kept[1].text
    assert cp.judge_notes(llm, paras, notes, "context") == kept or len(llm.prompts) == 1


def test_judge_failure_keeps_the_quick_notes():
    class Broken:
        def generate_text(self, *a, **k):
            raise RuntimeError("offline")
    notes = [cp.Note("pov", "Head-hop?", 1, "x")]
    assert cp.judge_notes(Broken(), {1: "unique paragraph text"}, notes) == notes


def test_judge_context_has_memory_profiles_and_promises(project):
    sm.add(project, "Tobin doesn't know about the schedule.", pinned=True)
    ctx = cp.judge_context(project, chapter(project), "Mara Venn rowed. Tobin waited.")
    assert "Tobin doesn't know" in ctx and "Mara Venn" in ctx and "frees her brother" in ctx


# ── Reader's eye ──────────────────────────────────────────────────

REPLY = """DIPS:
- "the rhythm came back to her the way" — a long stretch of rowing with nothing new
QUESTIONS:
- Did Mara sell them out?
BEATS:
- "Somewhere on that ship was the door" — dread; it lands
- "a sentence that is not in the chapter" — invented
OVERALL:
Tense and atmospheric, though the middle drifts."""

CHAPTER = ("Mara took an oar. The rhythm came back to her the way it always did. "
           "Somewhere on that ship was the door she had come to open.")


def test_reader_pass_parses_and_drops_invented_quotes(project):
    report = cp.reader_pass(FakeLLM(REPLY), project, chapter(project), CHAPTER)
    assert report.dips[0][0] == "the rhythm came back to her the way"
    assert report.questions == ["Did Mara sell them out?"]
    assert report.beats[0] == ("Somewhere on that ship was the door", "dread; it lands")
    assert report.beats[1][0] == ""                      # not in the chapter: no jump link
    assert report.overall.startswith("Tense and atmospheric")


def test_quick_reader_pass_without_a_model(project):
    slow = " ".join(["The long grey water stretched away beneath a sky that had forgotten "
                     "every colour it once held, and the wind went on and on over it."] * 4)
    text = "\n".join(['"Go," Tobin said.'] * 6 + [slow] * 6)
    report = cp.reader_pass_quick(project, chapter(project), text)
    assert report.quick and report.dips and "pace" in report.dips[0][1]
    assert "Unfinished beat: Slip past the patrol boat" in report.questions


# ── In the chapter editor ─────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait_tasks(app):
    from src.ui import companion_panel
    for t in list(companion_panel._RUNNING):
        t.wait(5000)
    app.processEvents()


def chapter_editor(app, project, content):
    from src.ui.manuscript_editor import ChapterEditor
    chapter(project).content = content
    ed = ChapterEditor(chapter(project), project=project)
    ed.resize(1000, 600)
    ed.show()
    return ed


def test_banner_and_card_on_open(app, project):
    cs.record_session(project, "c1", 10, 60, "The fog closed in.")
    ed = chapter_editor(app, project, "Mara rowed. The fog closed in.")
    assert ed.companion_banner.isVisible()
    assert "next: Slip past the patrol boat" in ed.companion_banner.label.text()
    assert "Next beat" in ed.companion.panel.left_off_label.text()


def test_finished_paragraph_gets_notes_and_beat_can_be_marked(app, project):
    ed = chapter_editor(app, project, "Mara rowed.")
    cursor = ed.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText("\nThey slipped past the patrol boat while the lamp swept the water, and "
                      "Tobin wondered if she had sold them out.\nNew paragraph.")
    ed.editor.setTextCursor(cursor)
    ed.companion.scan_paragraphs()
    wait_tasks(app)
    kinds = sorted(n.kind for n in ed.companion.panel.notes)
    assert kinds == ["beat", "pov"]
    assert ed.right_panel.tabText(ed.right_panel.indexOf(ed.companion.panel)) == "Companion (2)"
    beat_row = next(i for i, n in enumerate(ed.companion.panel.notes) if n.kind == "beat")
    ed.companion.panel.notes_list.setCurrentRow(beat_row)
    ed.companion.panel._act_on_note()
    assert chapter(project).planning.events[1].completed is True
    assert ed.planner_widget.get_planning_data()["events"][1]["completed"] is True


def test_dismissed_note_stays_dismissed(app, project):
    ed = chapter_editor(app, project, "Mara rowed.")
    para = "The lamp swung past and Tobin wondered if she had lied to him."
    cursor = ed.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText("\n" + para + "\nNext.")
    ed.editor.setTextCursor(cursor)
    ed.companion.scan_paragraphs()
    ed.companion.panel.notes_list.setCurrentRow(0)
    ed.companion.panel._dismiss_note()
    assert ed.companion.panel.notes == []
    ed.companion._seen.clear()
    ed.companion.scan_paragraphs()
    assert ed.companion.panel.notes == []


def test_model_judges_the_notes(app, project, monkeypatch):
    import src.ai.word_suggest as ws
    llm = FakeLLM("1. DROP\nNOTE P1: Mara apologises here, but she never does.")
    monkeypatch.setattr(ws, "get_llm", lambda: llm)
    ed = chapter_editor(app, project, "Mara rowed.")
    cursor = ed.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText("\nThe lamp swung past and Tobin wondered if she had lied, so Mara said "
                      "she was sorry for everything.\nNext.")
    ed.editor.setTextCursor(cursor)
    ed.companion.scan_paragraphs()
    wait_tasks(app)
    assert [n.kind for n in ed.companion.panel.notes] == ["ai"]
    assert "STORY CONTEXT" in llm.prompts[-1] and "QUICK-CHECK NOTES" in llm.prompts[-1]


def test_jump_to_selects_the_text(app, project):
    ed = chapter_editor(app, project, "Mara rowed. The fog closed in. Tobin waited.")
    ed.companion.jump_to("The fog closed in")
    assert ed.editor.textCursor().selectedText() == "The fog closed in"


def test_reader_pass_with_and_without_a_model(app, project, monkeypatch):
    import src.ai.word_suggest as ws
    ed = chapter_editor(app, project, CHAPTER)
    ed.companion.run_reader_pass()
    wait_tasks(app)
    assert "Set up a local or cloud model" in ed.companion.panel.reader_view.toPlainText()
    ed.companion._no_model = False
    monkeypatch.setattr(ws, "get_llm", lambda: FakeLLM(REPLY))
    ed.companion.run_reader_pass()
    wait_tasks(app)
    view = ed.companion.panel.reader_view.toHtml()
    assert "Did Mara sell them out?" in view and "jump:" in view


def test_memory_panel_actions(app, project):
    ed = chapter_editor(app, project, "Mara rowed.")
    panel = ed.companion.panel
    sm.add(project, "The key is sewn into Mara's coat.", suggested=True)
    panel.refresh_memory()
    panel.memory_edit.setText("Tobin doesn't know about the schedule.")
    panel._add_memory()
    texts = [panel.memory_list.item(i).text() for i in range(panel.memory_list.count())]
    assert texts[0].startswith("💡 suggested: The key") and "Tobin doesn't know" in texts[-1]
    panel.memory_list.setCurrentRow(0)
    panel._accept_memory()
    panel.memory_list.setCurrentRow(0)
    panel._toggle_pin()
    assert any(e.pinned and e.status == "active" for e in project.story_memory)


def test_leaving_the_chapter_records_the_session(app, project):
    ed = chapter_editor(app, project, "Mara rowed.")
    cursor = ed.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" The fog closed in around them.")
    ed.editor.setTextCursor(cursor)
    ed.save_to_model()
    state = cs.load(project)["chapters"]["c1"]
    assert state["words_at_close"] == 8 and state["stopped_at"] == "The fog closed in around them."


# ── Memory reaches every tool ─────────────────────────────────────

def test_memory_in_suggestions_rephrase_critique_and_chat(project, app, monkeypatch):
    sm.add(project, "Tobin doesn't know about the schedule.", pinned=True)
    from src.ai import passage_critique as pc
    text = "Tobin rowed hard toward the pier."
    assert "Tobin doesn't know" in pc.build_prompt(pc.build_context(project, None, text, 0, len(text)))

    from types import SimpleNamespace as NS
    from src.ui.rephrase_dialog import RephraseDialog
    assert "Tobin doesn't know" in RephraseDialog._memory_block(
        NS(project=project, surrounding_before="", original_text=text))

    from src.ai.chapter_analysis_agent import CritiqueOrchestrator, ReportType
    analyzer = CritiqueOrchestrator(project=project)._build_analyzer(ReportType.PACING, "Night Run")
    assert "Tobin doesn't know" in analyzer._format_context_block("", "", None, "Night Run", 0)

    from src.ui.main_window import ChatWorker
    worker = ChatWorker("hi", {"story_memory": sm.prompt_block(project, "hi")}, "general")
    assert "Tobin doesn't know" in worker._build_context_prompt()


def test_conversation_panel_remember(app, project):
    from src.ui.rewrite_chat_panel import ConversationPanel, remember
    panel = ConversationPanel()
    seen = []
    panel.remember_requested.connect(seen.append)
    panel.add_message("You", "Let's keep Tobin in the dark about the schedule.")
    panel.add_message("Editor", "Got it.")
    panel._remember()
    assert seen == ["Let's keep Tobin in the dark about the schedule."]
    remember(panel, project, seen[0], "suggestions")
    assert panel.status.text() == "Remembered in Story memory."
    assert project.story_memory[-1].source == "suggestions"


def test_chat_widget_remember_button(app):
    from src.ui.chat_widget import ChatWidget
    w = ChatWidget()
    w._current_conversation = [{"role": "user", "content": "Mara never apologises."},
                               {"role": "assistant", "content": "Noted."}]
    got = []
    w.remember_requested.connect(got.append)
    w.remember_btn.click()
    assert got == ["Mara never apologises."]


@pytest.mark.parametrize("message,decision", [
    ("Mara's brother should be called Ilan, and he's younger than her.", True),
    ("Her name is Ilsa, not Elsa.", True),
    ("It turns out Voss was the informant.", True),
    ("What do you think of the opening?", False),
    ("Can you tighten paragraph two?", False),
])
def test_decision_cues(message, decision):
    assert sm.has_decision(message) is decision


def test_side_panel_can_always_be_closed_and_reopened():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QToolButton
    app = QApplication.instance() or QApplication([])
    from src.models.project import Chapter, WriterProject
    from src.ui.manuscript_editor import ChapterEditor
    ce = ChapterEditor(Chapter(id="c", number=1, title="T", content="Hi."),
                       project=WriterProject(name="x"))
    ce.resize(1200, 800)
    ce.show()
    app.processEvents()
    banner = ce.companion_banner
    assert isinstance(banner.close_btn, QToolButton) and banner.close_btn.text() == "✕"
    banner.details_btn.click()                       # Details opens the Companion tab
    assert ce.side_panel_open() and ce.right_panel.currentWidget() is ce.companion.panel
    assert banner.details_btn.text() == "Hide details" and ce.toggle_planner_btn.isChecked()
    assert ce.right_panel.cornerWidget() is ce.close_panel_btn
    ce.close_panel_btn.click()                       # ✕ on the panel closes it
    assert not ce.side_panel_open() and not ce.toggle_planner_btn.isChecked()
    assert banner.details_btn.text() == "Details"
    ce.toggle_planner_btn.click()                    # ◧ Panel reopens it
    assert ce.side_panel_open()
    ce.main_splitter.setSizes([1200, 0])             # dragged shut counts as closed
    ce._on_splitter_moved()
    assert not ce.side_panel_open()
    banner.details_btn.click()
    assert ce.side_panel_open()
    banner.details_btn.click()                       # Details toggles
    assert not ce.side_panel_open()


# ── Details: open/close, about this chapter, suggestion-backed fixes ──

FIX_TEXT = ("Mara rowed hard toward the pier. The water was almost too dark to see. "
            "Tobin waited on the steps.")


def test_sections_open_close_and_remember(app, project):
    ed = chapter_editor(app, project, FIX_TEXT)
    panel = ed.companion.panel
    assert "Night Run" in panel.chapter_label.text() and "Chapter 3" in panel.chapter_label.text()
    assert panel.sections["notes"].is_open()
    assert not panel.sections["memory"].is_open()            # whole-book sections start closed
    panel.sections["notes"].header.click()
    assert not panel.sections["notes"].is_open()
    assert panel.sections["notes"].body.isHidden()
    assert "notes" in cs.collapsed_sections(project)
    ed2 = chapter_editor(app, project, FIX_TEXT)              # remembered for the next chapter
    assert not ed2.companion.panel.sections["notes"].is_open()
    ed2.companion.panel.set_all_open(True)
    assert all(s.is_open() for s in ed2.companion.panel.sections.values())


def test_memory_about_this_chapter_comes_first(app, project):
    sm.add(project, "The lighthouse keeper is dead.")
    sm.add(project, "Tobin owes Mara a boat.")
    ed = chapter_editor(app, project, FIX_TEXT)
    first = ed.companion.panel.memory_list.item(0).text()
    assert first.startswith("Tobin owes Mara") and first.endswith("· this chapter")


def test_overly_descriptive_section_scans_without_a_model(app, project):
    ed = chapter_editor(app, project, FIX_TEXT)
    panel = ed.companion.panel
    assert [f.text for f in panel.flags] == ["The water was almost too dark to see."]
    assert "Overly descriptive  (1)" in panel.sections["overdescribed"].header.text()


def test_three_fixes_without_a_model_offer_quick_fixes(app, project):
    ed = chapter_editor(app, project, FIX_TEXT)
    ed.companion._no_model = True
    ed.companion.find_three_fixes()
    wait_tasks(app)
    panel = ed.companion.panel
    over = next(f for f in panel.fixes if f.kind == "overdescribed")
    panel.fixes_list.setCurrentRow(panel.fixes.index(over))
    assert over.options and not over.options[0].by_ai
    assert panel.fix_preview.toPlainText() == "The water was too dark to see."
    panel._accept_fix()
    assert "The water was too dark to see." in ed.editor.toPlainText()
    assert over not in panel.fixes


def test_three_fixes_with_a_model_write_suggestions_in_voice(app, project, monkeypatch):
    import src.ai.word_suggest as ws
    llm = FakeLLM("PICK 1 — the reader can't picture the dark.",
                  "SUGGESTION 1 (fix):\nThe water swallowed the oar blade a hand below the "
                  "surface.\nWHY: shows the dark.\n\nSUGGESTION 2 (alternative):\nShe could not "
                  "see the oar once it went in.\nWHY: plainer.")
    monkeypatch.setattr(ws, "get_llm", lambda: llm)
    ed = chapter_editor(app, project, FIX_TEXT)
    ed.companion._no_model = False
    ed.companion.find_three_fixes()
    wait_tasks(app)
    wait_tasks(app)
    panel = ed.companion.panel
    fix = panel.fixes[0]
    assert fix.why == "the reader can't picture the dark."
    assert [o.by_ai for o in fix.options] == [True, True, False]   # quick fix stays last
    assert "THE PROBLEM TO FIX" in llm.prompts[1] and "⟦PASSAGE START⟧" in llm.prompts[1]
    assert "Suggested fixes are ready" in panel.fixes_status.text()
    panel.fixes_list.setCurrentRow(0)
    panel.fix_preview.setPlainText("The oar vanished a hand below the surface.")
    panel._accept_fix()
    assert ("Mara rowed hard toward the pier. The oar vanished a hand below the surface. "
            "Tobin waited") in ed.editor.toPlainText()


def test_more_options_and_note_fix_open_suggestions_with_a_focus(app, project, monkeypatch):
    ed = chapter_editor(app, project, FIX_TEXT)
    seen = []
    monkeypatch.setattr(ed, "suggest_for_span",
                        lambda s, e, focus="": seen.append((ed.editor.toPlainText()[s:e], focus))
                        or True)
    fix = cp.Fix("Overly descriptive — tells", excerpt="almost too dark", paragraph=0)
    ed.companion.panel.set_fixes([fix])
    ed.companion.panel._more_fix()
    note = cp.Note("pov", "Head-hop?", 0, "Tobin waited")
    ed.companion.panel.set_notes([note])
    ed.companion.panel.notes_list.setCurrentRow(0)
    ed.companion.panel._fix_note()
    assert seen == [("The water was almost too dark to see.", "Overly descriptive — tells"),
                    ("Tobin waited on the steps.", "Head-hop?")]
    assert ed.companion.panel.fixes == [] and ed.companion.panel.notes == []


def test_suggestions_dialog_takes_a_focus(app, project):
    from src.ui.passage_critique_dialog import PassageCritiqueDialog, SuggestionWorker

    class NoModel(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (None, "off"))

        def start(self):
            self.run()

    dlg = PassageCritiqueDialog(FIX_TEXT, 0, 32, project, chapter(project),
                                worker_factory=NoModel, focus="make the dark felt")
    assert dlg.focus_edit.text() == "make the dark felt"


def test_locate_sentence():
    text = "First line.\nOne. The fog was very thick. Two."
    assert text[slice(*cp.locate_sentence(text, 1, "very thick"))] == "The fog was very thick."
    assert cp.locate_sentence(text, 1, "missing") is None


def test_accepting_your_own_edit_and_unchanged_text(app, project):
    ed = chapter_editor(app, project, FIX_TEXT)
    panel = ed.companion.panel
    fix = cp.Fix("Spelling", excerpt="Tobin waited on the steps.", paragraph=0,
                 sentence="Tobin waited on the steps.")
    panel.set_fixes([fix])
    assert panel.fix_accept_btn.isEnabled()                  # no suggestion, but editable
    panel._accept_fix()
    assert "No change" in panel.fixes_status.text() and panel.fixes == [fix]
    panel.fix_preview.setPlainText("Tobin waited on the stairs.")
    panel._accept_fix()
    assert ed.editor.toPlainText().endswith("Tobin waited on the stairs.")
