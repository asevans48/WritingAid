"""Dialogue craft: speech profiles, the exchange, scan checks, and their
use in Suggestions, Rephrase and the Critique tab's Dialog report."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import dialogue_craft as dc
from src.ai import passage_critique as pc
from src.models.project import Chapter, Character, CharacterTension, WriterProject

MARA_LINES = ['"No."', '"Row."', '"Not yet."', '"Get the rope."', '"Quiet."', '"Fine."',
              '"Move."']
TOBIN_LINES = ['"Well, I was thinking we could maybe wait until the bells stop, couldn\'t we?"',
               '"You don\'t think they\'ll see us out here, do you, with the lamps and all?"',
               '"I\'ve got a bad feeling about this whole thing, honestly I have."',
               '"Can\'t we just go back and try again tomorrow when it\'s darker?"',
               '"What if they\'ve doubled the patrol? What then?"']


def book_chapter():
    paras = []
    for m, t in zip(MARA_LINES, TOBIN_LINES):
        paras.append(f"{t} Tobin said.")
        paras.append(f"{m} Mara said.")
    return "\n".join(paras)


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.characters = [
        Character(id="m", name="Mara Venn", character_type="protagonist",
                  speaking_style="clipped; never says please", want="free her brother",
                  secret="she sold the patrol schedule", social_network={"Tobin": "old crewmate"}),
        Character(id="t", name="Tobin", character_type="major", speaking_style="rambles",
                  want="get out alive"),
    ]
    p.story_planning.tensions = [CharacterTension(
        id="x", title="Eroding trust", description="Tobin suspects Mara sold them out.",
        characters_involved=["Mara", "Tobin"])]
    ch1 = Chapter(id="c1", number=1, title="Earlier", content=book_chapter())
    ch2 = Chapter(id="c2", number=2, title="Pier", content="")
    ch2.planning.events = []
    p.manuscript.chapters = [ch1, ch2]
    return p


# ── Detection and profiles ────────────────────────────────────────

def test_dialogue_detection():
    assert dc.is_dialogue('"Go," he said. "Now."')
    assert dc.is_dialogue('"I have been waiting here for hours and hours," she said.')
    assert not dc.is_dialogue("The tide came in over the stones. Nobody moved.")


def test_profiles_measure_each_speaker(project):
    profiles = dc.speech_profiles(project)
    mara, tobin = profiles["Mara Venn"], profiles["Tobin"]
    assert len(mara.lines) == 5 and len(tobin.lines) == 5
    assert mara.words_per_line < 3 < tobin.words_per_line
    assert tobin.contractions_per_100 > mara.contractions_per_100
    assert "clipped" in mara.to_prompt() and "Sounds like" in mara.to_prompt()


def test_line_that_sounds_like_someone_else(project):
    profiles = dc.speech_profiles(project)
    note = dc.line_fit("Well, couldn't we maybe wait until it's darker, don't you think?",
                       "Mara Venn", profiles)
    assert "sounds more like Tobin" in note
    assert dc.line_fit("Get down.", "Mara Venn", profiles) == ""


def test_exchange_context_has_wants_secrets_relationship_and_tension(project):
    text = dc.exchange_context(project, None, ["Mara Venn", "Tobin"])
    assert "free her brother" in text and "hides: she sold the patrol schedule" in text
    assert "to Tobin: old crewmate" in text and "Eroding trust" in text


# ── Scan checks ───────────────────────────────────────────────────

NAMES = ["Mara Venn", "Tobin"]


@pytest.mark.parametrize("text,kind", [
    ('"Go," Tobin hissed.', "bookism"),
    ('"Go," Tobin said angrily.', "tag_adverb"),
    ('"Mara, listen," Tobin said.\n"Tobin, no," Mara said.', "names"),
    ('"As you know, the patrol comes at dusk," Tobin said.', "exposition"),
    ('"Well, fine," Tobin said.\n"Oh, sure," Mara said.', "filler"),
    ('"' + "word " * 75 + '," Tobin said.', "long_turn"),
    ('"Go."\n"No."\n"Why?"\n"Because."', "lost_speaker"),
    ('Tobin stood up slowly. He turned to the sea. He wiped his hands. He looked at the boats. '
     'He cracked his knuckles. "Go."',
     "stage_directions"),
])
def test_dialogue_issues(text, kind):
    found = [i.kind for i in dc.dialogue_issues(text, NAMES)]
    assert kind in found, found


def test_clean_dialogue_has_no_issues():
    text = '"Row," Mara said.\nTobin pulled at the oars. "They\'ll hear us."\n"Then row quieter."'
    assert dc.dialogue_issues(text, NAMES) == []


def test_rewrite_adding_a_bookism_is_serious_and_wrong_voice_is_a_note(project):
    profiles = dc.speech_profiles(project)
    serious, minor = dc.rewrite_dialogue_problems(
        '"Row," Mara said.',
        '"Well, couldn\'t we maybe row a little faster, don\'t you think?" Mara hissed.',
        NAMES, profiles)
    assert any("said-bookism" in s for s in serious)
    assert any("sounds more like Tobin" in m for m in minor)


# ── Suggestions ───────────────────────────────────────────────────

SCENE = ('Tobin rowed hard.\n'
         '"Mara, please, tell me you brought the papers," Tobin hissed.\n'
         '"As you know, I always do," Mara said.')


def scene_ctx(project):
    start = SCENE.index('"Mara, please')
    return pc.build_context(project, project.manuscript.chapters[1], SCENE, start, len(SCENE))


def test_dialogue_mode_context(project):
    ctx = scene_ctx(project)
    assert ctx.dialogue_mode
    prompt = pc.build_prompt(ctx)
    assert "This passage is mostly dialogue" in prompt
    assert "HOW THESE CHARACTERS TALK" in prompt and "Sounds like" in prompt
    assert "WHAT'S BETWEEN THE SPEAKERS" in prompt and "she sold the patrol schedule" in prompt
    assert "DIALOGUE:\n- <voice" in prompt
    assert any("bookism" in n for n in ctx.dialogue_notes)
    assert any("as you know" in n.lower() for n in ctx.dialogue_notes)


def test_prose_passage_stays_in_prose_mode(project):
    text = "The tide came in. Nobody moved on the pier."
    assert not pc.build_context(project, None, text, 0, len(text)).dialogue_mode


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


def test_dialogue_section_parsed_and_rewrite_with_bookism_replaced(project):
    ctx = scene_ctx(project)
    good1 = '"Tell me you brought the papers," Tobin said.\n"I did," Mara said.'
    bad = '"Papers. Tell me you have them," Tobin growled.\n"I do," Mara said.'
    good3 = 'Tobin missed a stroke. "The papers?"\nMara touched her coat. "Row."'
    llm = FakeLLM(
        "WHAT WORKS:\n- Tension.\n\n**Dialogue:**\n- Mara's “As you know” line is exposition.\n\n"
        f"SUGGESTION 1 (tightened):\n{good1}\nWHY: a\n\nSUGGESTION 2 (restructured):\n{bad}\n"
        f"WHY: b\n\nSUGGESTION 3 (new focus):\n{good3}\nWHY: c",
        'SUGGESTION 1 (restructured):\n"You have the papers," Tobin said, not asking.\n'
        '"Row," Mara said.\nWHY: d')
    r = pc.critique_passage(llm, ctx)
    assert r.dialogue[0].startswith("Mara's “As you know”")
    assert any("bookism" in d for d in r.dialogue)
    assert bad not in [s.text for s in r.suggestions]


# ── Rephrase ──────────────────────────────────────────────────────

def test_rephrase_retries_an_option_that_adds_a_bookism(project):
    from src.ai.rephrasing_agent import RephraseStyle, RephrasingAgent

    class LLM:
        def __init__(self):
            self.prompts = []
            self.out = ['OPTION 1 (concise):\n"Row," Mara snarled.\nEXPLANATION: e',
                        'OPTION 1 (concise):\n"Row," Mara said.\nEXPLANATION: e']

        def generate_text(self, prompt, *a, **k):
            self.prompts.append(prompt)
            return self.out.pop(0)

    llm = LLM()
    result = RephrasingAgent(llm_client=llm, project=project).rephrase(
        '"Row now," Mara said.', styles=[RephraseStyle.CONCISE])
    assert len(llm.prompts) == 2 and result.options[0].text == '"Row," Mara said.'


def test_rephrase_dialog_builds_dialogue_guidance(project):
    from types import SimpleNamespace as NS
    from src.ui.rephrase_dialog import RephraseDialog
    fake = NS(project=project, original_text='"As you know, I always do," Mara said.',
              surrounding_before='"The papers?" Tobin said.\n', chapter=None)
    guidance = RephraseDialog._dialogue_guidance(fake)
    assert "mostly dialogue" in guidance and "HOW THESE CHARACTERS TALK" in guidance
    assert "she sold the patrol schedule" in guidance and "as you know" in guidance.lower()


# ── Critique tab: Dialog report ───────────────────────────────────

def dialog_report(project, text, title="Pier"):
    from src.ai.chapter_analysis_agent import (CritiqueOrchestrator, ReportSection, ReportType,
                                               resolve_genre_profile)
    orch = CritiqueOrchestrator(project=project)
    analyzer = orch._build_analyzer(ReportType.DIALOG, title)
    section = ReportSection(report_type=ReportType.DIALOG, chapter_title=title)
    analyzer._compute(text, section, resolve_genre_profile("default"), None)
    return analyzer, section


def test_dialog_report_flags_alike_speakers_drift_and_silence(project):
    # In this chapter Mara talks exactly like Tobin, and Tobin talks like Mara did.
    swapped = "\n".join([f"{t} Mara said." for t in TOBIN_LINES]
                        + [f"{m} Tobin said." for m in MARA_LINES[:5]])
    project.manuscript.chapters[1].content = swapped
    project.manuscript.chapters[1].planning.characters_featured = ["Mara Venn"]
    analyzer, section = dialog_report(project, swapped)
    drift = section.extra_lists["Voice drift from earlier chapters"]
    assert any(d.startswith("Mara Venn:") for d in drift)
    assert section.metrics["lines_by_speaker"] == {"Mara Venn": 5, "Tobin": 5}
    assert "HOW THE SPEAKERS TALK" in analyzer._build_prompt(
        swapped, section, __import__("src.ai.chapter_analysis_agent", fromlist=["x"])
        .resolve_genre_profile("default"), "", "", None)[0]


def test_dialog_report_lists_scan_checks_and_lost_speakers(project):
    text = '"Go," Tobin hissed.\n"Why?"\n"Because."\n"When?"\n"Now."'
    _a, section = dialog_report(project, text)
    checks = section.extra_lists["Dialogue checks"]
    assert any("bookism" in c for c in checks)
    assert any("no clear speaker" in f and "risk of" in f for f in section.findings)


def test_dialog_report_flags_a_featured_character_who_never_speaks(project):
    text = ('"Go," Tobin said. Mara watched him.\n' * 3)
    project.manuscript.chapters[1].planning.characters_featured = ["Mara Venn"]
    _a, section = dialog_report(project, text)
    assert "Mara Venn is featured in this chapter but never speaks." in section.extra_lists["Who talks"]


# ── Fixes from the Gemma run ──────────────────────────────────────

def test_untagged_lines_alternate_in_a_two_person_exchange():
    from src.ai.dialogue_speakers import attribute_lines
    text = ('"The patrol changes at midnight," Tobin said.\n"I know," Mara said.\n'
            '"Someone sold us out, Mara."\n"Maybe it was luck."')
    got = [(l.speaker, l.certainty) for l in attribute_lines(text, NAMES)]
    assert got == [("Tobin", "tag"), ("Mara Venn", "tag"),
                   ("Tobin", "likely"), ("Mara Venn", "likely")]


def test_merged_paragraphs_and_lost_speakers_are_serious():
    original = '"Go," Tobin said.\n"No," Mara said.\n"Why?" Tobin asked.'
    merged = '"Go," Tobin said. "No," Mara said. "Why?" Tobin asked.'
    untagged = '"Go."\n"No."\n"Why?"'
    serious, _ = dc.rewrite_dialogue_problems(original, merged, NAMES)
    assert "runs several speakers' lines together in one paragraph" in serious
    serious, _ = dc.rewrite_dialogue_problems(original, untagged, NAMES)
    assert "leaves readers unsure who is speaking" in serious


def test_checklist_keeps_character_voices_separate_from_narration():
    assert "a rambler still rambles" in dc.DIALOGUE_CHECKLIST


def test_rephrase_keeps_dialogue_paragraphs(project):
    from src.ai.rephrasing_agent import RephraseStyle, RephrasingAgent

    class LLM:
        def generate_text(self, prompt, *a, **k):
            return 'OPTION 1 (concise):\n"Go," Tobin said.\n"No," Mara said.\nEXPLANATION: e'

    out = RephrasingAgent(llm_client=LLM(), project=project).rephrase(
        '"Go now," Tobin said.\n"No," Mara said.', styles=[RephraseStyle.CONCISE])
    assert out.options[0].text == '"Go," Tobin said.\n"No," Mara said.'

    class Wrapped:
        def generate_text(self, prompt, *a, **k):
            return "OPTION 1 (concise):\nThe tide came in over\nthe stones.\nEXPLANATION: e"

    prose = RephrasingAgent(llm_client=Wrapped()).rephrase(
        "The tide rolled in over the stones.", styles=[RephraseStyle.CONCISE])
    assert prose.options[0].text == "The tide came in over the stones."


def test_rephrase_guidance_labels_speakers(project):
    from types import SimpleNamespace as NS
    from src.ui.rephrase_dialog import RephraseDialog
    fake = NS(project=project, original_text='"No," Mara said.\n"Why not?" Tobin asked.',
              surrounding_before="", chapter=None)
    guidance = RephraseDialog._dialogue_guidance(fake)
    assert "WHO SPEAKS EACH LINE" in guidance and "“Why not?” — Tobin" in guidance


def test_one_tag_then_alternation_is_followable():
    from src.ai.dialogue_speakers import attribute_lines
    text = ('"The patrol changes at midnight, Mara," Tobin said.\n"Keep rowing."\n'
            '"Someone sold us out."\n"Maybe it was luck."')
    assert [l.speaker for l in attribute_lines(text, NAMES)] == [
        "Tobin", "Mara Venn", "Tobin", "Mara Venn"]
    serious, _ = dc.rewrite_dialogue_problems(
        '"Go," Tobin said.\n"No," Mara said.\n"Why?" Tobin asked.\n"Because."',
        '"Go, Mara," Tobin said.\n"No."\n"Why?"\n"Because."', NAMES)
    assert "leaves readers unsure who is speaking" not in serious


def test_never_says_from_the_profile(project):
    profiles = dc.speech_profiles(project)
    assert profiles["Mara Venn"].never == ["please"]
    found = dc.dialogue_issues('"Please stay calm," Mara said.', NAMES, profiles=profiles)
    assert any(i.kind == "out_of_character" and "never do" in i.message for i in found)
    serious, _ = dc.rewrite_dialogue_problems('"Stay calm," Mara said.',
                                             '"Please, stay calm," Mara said.', NAMES, profiles)
    assert any("never use" in s for s in serious)


def test_alternation_uses_a_name_from_later_in_the_exchange():
    from src.ai.dialogue_speakers import attribute_lines
    text = ('"The patrol changes at midnight," Tobin said.\n"Keep rowing."\n'
            '"Someone told them, Mara."\n"Maybe it was luck."')
    assert [l.speaker for l in attribute_lines(text, NAMES)] == [
        "Tobin", "Mara Venn", "Tobin", "Mara Venn"]


# ── Dialogue run together (U+2029 selections, Markdown paragraphs) ──

def test_separate_speakers_splits_at_each_new_speaker_keeping_beats():
    para = ('"Go," Tobin said. "No," Mara said. Tobin missed a stroke. '
            '"Why not?" "Because," Mara said.')
    assert dc.separate_speakers(para, NAMES) == [
        '"Go," Tobin said.', '"No," Mara said.', 'Tobin missed a stroke. "Why not?"',
        '"Because," Mara said.']


def test_one_speaker_paragraph_is_left_alone():
    para = '"Go," Tobin said. He leaned on the oars. "Now."'
    assert dc.separate_speakers(para, NAMES) == [para]


def test_tidy_matches_markdown_paragraphs():
    original = '"Go," Tobin said.\n\n"No," Mara said.'
    rewrite = '"Go now," Tobin said.\n"No," Mara said.'
    assert dc.tidy_paragraphs(original, rewrite, NAMES) == '"Go now," Tobin said.\n\n"No," Mara said.'
    assert dc.tidy_paragraphs(original, '"Go now," Tobin said. "No," Mara said.', NAMES) == \
        '"Go now," Tobin said.\n\n"No," Mara said.'


def test_tidy_joins_wrapped_prose_but_keeps_real_paragraphs():
    assert dc.tidy_paragraphs("The tide came in.", "The tide came\nin over the stones.") == \
        "The tide came in over the stones."
    assert dc.tidy_paragraphs("One.\n\nTwo.", "One more.\nTwo more.") == "One more.\n\nTwo more."


def test_qt_paragraph_separators_become_line_breaks():
    assert dc.normalize_breaks('"Go."\u2029\u2029"No."') == '"Go."\n\n"No."'


def test_rephrase_keeps_paragraphs_from_a_qt_selection(project):
    from src.ai.rephrasing_agent import RephraseStyle, RephrasingAgent

    class LLM:
        def __init__(self):
            self.prompt = ""

        def generate_text(self, prompt, *a, **k):
            self.prompt = prompt
            return 'OPTION 1 (concise):\n"Go," Tobin said. "No," Mara said.\nEXPLANATION: e'

    llm = LLM()
    out = RephrasingAgent(llm_client=llm, project=project).rephrase(
        '"Go now," Tobin said.\u2029\u2029"No," Mara said.', styles=[RephraseStyle.CONCISE])
    assert "\u2029" not in llm.prompt
    assert out.options[0].text == '"Go," Tobin said.\n\n"No," Mara said.'


def test_suggestions_are_paragraphed_like_the_chapter(project):
    text = 'Tobin rowed.\n\n"Go now," Tobin said.\n\n"No," Mara said.'
    start = text.index('"Go now,')
    ctx = pc.build_context(project, None, text, start, len(text))
    llm = FakeLLM('WHAT WORKS:\n- ok\n\nSUGGESTION 1 (tightened):\n"Go," Tobin said. "No," Mara '
                  'said.\nWHY: a\n\nSUGGESTION 2 (restructured):\n"Now," Tobin said.\n"No," '
                  'Mara said.\nWHY: b')
    r = pc.critique_passage(llm, ctx)
    assert {s.text for s in r.suggestions} >= {'"Go," Tobin said.\n\n"No," Mara said.',
                                                '"Now," Tobin said.\n\n"No," Mara said.'}


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_editor_inserts_rewrites_as_separate_paragraphs(qapp, project, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QDialog
    from src.models.project import Chapter
    import src.ui.improve_window as iw
    from src.ui.manuscript_editor import ChapterEditor

    seen = {}

    class Improve:
        """Stands in for the Improve window (every way in since D.11)."""
        def __init__(self, text, start, end, *a, tab="", selection=None, rephrase=None, **k):
            self.tool = tab
            if tab == "rephrase":
                seen["text"] = rephrase["text"]
                self.span = selection                    # Rephrase: exactly the highlight
                self.replacement = '"Row," Tobin said.\n"Fine," Mara said.'
            else:
                self.span = (start, end)
                self.replacement = '"Go," Tobin said. "No," Mara said.'

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(iw, "ImproveWindow", Improve)
    content = 'Tobin rowed.\n\n"Go now," Tobin said.\n\n"No," Mara said.\n\nFog.'
    ed = ChapterEditor(Chapter(id="c", number=1, title="T", content=content), project=project)

    def select(a, b):
        doc = ed.editor.toPlainText()
        c = ed.editor.textCursor()
        c.setPosition(doc.index(a))
        c.setPosition(doc.index(b) + len(b), QTextCursor.MoveMode.KeepAnchor)
        ed.editor.setTextCursor(c)

    select('"Go now,', 'Mara said.')
    ed._suggest_for_selection()
    assert ed.editor.toPlainText() == 'Tobin rowed.\n\n"Go," Tobin said.\n\n"No," Mara said.\n\nFog.'
    select('"Go,"', 'Mara said.')
    ed._rephrase_selection()
    # The editor hands over Qt's selection; RephraseDialog normalises it on open.
    from src.ai.dialogue_craft import normalize_breaks
    assert normalize_breaks(seen["text"]) == '"Go," Tobin said.\n\n"No," Mara said.'
    assert ed.editor.toPlainText() == 'Tobin rowed.\n\n"Row," Tobin said.\n\n"Fine," Mara said.\n\nFog.'
