"""Overly descriptive statements: scan, AI review, and the sub-module in
Suggestions, the editor and the Critique tab."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import overdescription as od
from src.ai import passage_critique as pc
from src.models.project import Chapter, Character, WriterProject

TEXT = ("Mara climbed to the attic. The room was almost too dark to see. "
        "She almost fell on the last stair. \"It's too dark,\" she said. "
        "Voss came too, and lit the lamp. The light was pretty.")


def flagged(text):
    return [f.text for f in od.scan(text)]


# ── Scan (no model) ───────────────────────────────────────────────

def test_too_and_almost_are_flagged():
    hits = flagged(TEXT)
    assert "The room was almost too dark to see." in hits
    f = od.scan("The room was almost too dark to see.")[0]
    assert [c.phrase for c in f.cues] == ["almost", "too dark"]
    assert f.hints and "how much" in f.reason


def test_cue_words_are_clues_not_proof():
    hits = flagged(TEXT)
    assert "Mara climbed to the attic." not in hits
    assert "Voss came too, and lit the lamp." not in hits       # "too" = also
    assert not any(h.startswith("\"It's too dark") for h in hits)  # dialogue is the character's
    assert flagged("\"Me too,\" he said.") == []


@pytest.mark.parametrize("sentence,kind", [
    ("The cold, dark, damp cellar stank.", "stacked"),
    ("She felt very angry.", "telling"),
    ("The light seemed to pulse.", "impression"),
    ("He looked tired.", "impression"),
])
def test_other_cues(sentence, kind):
    flags = od.scan(sentence)
    assert flags and kind in [c.category for c in flags[0].cues]


def test_looking_at_something_is_an_action():
    assert flagged("He looked at her.") == []


@pytest.mark.parametrize("before,after", [
    ("The hall was almost empty.", "The hall was empty."),
    ("It was a very old house.", "It was an old house."),
    ("It was nearly silent and a bit cold.", "It was silent and cold."),
    ("The room was almost too dark to see.", "The room was too dark to see."),
    ("She almost fell on the stairs.", "She almost fell on the stairs."),   # an action
    ("He would rather than not.", "He would rather than not."),
])
def test_trimmed(before, after):
    assert od.trimmed(before) == after


def test_offsets_point_into_the_text():
    text = "First line.\n\nThe hall was almost empty. Then nothing."
    f = od.scan(text)[0]
    assert text[f.start:f.end] == "The hall was almost empty."
    assert f.expansions[0].text == "The hall was empty." and not f.expansions[0].by_ai


def test_flag_round_trips_through_a_dict():
    f = od.scan("The hall was almost empty.")[0]
    assert od.Flag.from_dict(f.to_dict()) == f


# ── With a model ──────────────────────────────────────────────────

class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("no reply")
        return self.replies.pop(0)


PASSAGE = ("The room was almost too dark to see. She almost fell on the last stair. "
           "The attic was big and full of things.")

REVIEW = """**STATEMENT [1]:** "The room was almost too dark to see."
VERDICT: overly descriptive
WHY: "Almost too dark" tells; the dark should cost her something.
EXPANSION 1 (show the effect): She felt for the rafters with both hands, blind past her own wrists.
EXPANSION 2 (sensory detail): Dust and the smell of old wool; the window was a grey smear.

STATEMENT [2]: She almost fell on the last stair.
VERDICT: fine — it's an action
WHY: The near fall is an event.

STATEMENT [3]: The attic was big and full of things.
VERDICT: Overly descriptive
WHY: Vague summary.
EXPANSION 1 (sensory detail): Trunks stood shoulder to shoulder under the eaves.
"""


@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.characters = [Character(id="c1", name="Mara", character_type="protagonist")]
    return p


@pytest.fixture
def chapter():
    return Chapter(id="ch", number=1, title="Attic", content=PASSAGE)


def ctx_for(project, chapter, text=PASSAGE):
    return pc.build_context(project, chapter, text, 0, len(text))


def test_ai_confirms_clears_and_finds_nuance(project, chapter):
    llm = FakeLLM(REVIEW)
    r = od.review_passage(llm, ctx_for(project, chapter), compact=False)
    assert r.used_ai
    texts = [f.text for f in r.flags]
    assert texts == ["The room was almost too dark to see.",
                     "The attic was big and full of things."]
    assert [f.text for f in r.cleared] == ["She almost fell on the last stair."]
    first, nuanced = r.flags
    assert first.source == "both" and first.verdict == "over"
    assert "cost her something" in first.reason
    assert first.expansions[0].by_ai and first.expansions[-1].by_ai is False   # trim kept last
    assert nuanced.source == "ai" and not nuanced.cues
    assert nuanced.expansions[0].text.startswith("Trunks")
    prompt = llm.prompts[0]
    assert "clues, not proof" in prompt and "[1] clues: “almost”, “too dark”" in prompt


def test_prompt_carries_the_authors_voice(project, chapter):
    ctx = ctx_for(project, chapter)
    ctx.voice = "AUTHOR'S VOICE: short clipped sentences"
    ctx.style_sheet = "Never use 'suddenly'."
    llm = FakeLLM(REVIEW)
    od.review_passage(llm, ctx, compact=False)
    assert "short clipped sentences" in llm.prompts[0]
    assert "Never use 'suddenly'." in llm.prompts[0]
    assert "author's voice" in llm.prompts[0]


def test_no_model_gives_the_scan(project, chapter):
    r = od.review_passage(None, ctx_for(project, chapter))
    assert not r.used_ai
    assert "The room was almost too dark to see." in [f.text for f in r.flags]


def test_failing_or_unreadable_model_falls_back_to_the_scan(project, chapter):
    for llm in (FakeLLM(), FakeLLM("Sorry, I can't help.")):
        r = od.review_passage(llm, ctx_for(project, chapter), compact=False)
        assert not r.used_ai and r.error
        assert "The room was almost too dark to see." in [f.text for f in r.flags]


def test_expansion_that_invents_a_name_is_dropped(project, chapter):
    reply = REVIEW.replace("blind past her own wrists", "and Zebulon Quarrick laughed")
    r = od.review_passage(FakeLLM(reply), ctx_for(project, chapter), compact=False)
    assert all("Zebulon" not in x.text for x in r.flags[0].expansions)


def test_more_ideas(project, chapter):
    ctx = ctx_for(project, chapter)
    flag = od.scan(PASSAGE)[0]
    llm = FakeLLM("STATEMENT [1]: x\nVERDICT: overly descriptive\nWHY: y\n"
                  "EXPANSION 1 (sound): Somewhere a beam ticked as it cooled.")
    found = od.expand_more(llm, ctx, flag, note="more sound")
    assert [x.text for x in found] == ["Somewhere a beam ticked as it cooled."]
    assert "more sound" in llm.prompts[0]


def test_chapter_review_judges_the_strongest_candidates():
    text = PASSAGE + "\n\nHe looked tired. The door was very old."
    reply = ("STATEMENT [5]: The door was very old.\nVERDICT: fine\nWHY: plain is right.\n\n"
             "STATEMENT [1]: The room was almost too dark to see.\nVERDICT: overly "
             "descriptive\nWHY: tells.")
    llm = FakeLLM(reply)
    r = od.review_chapter(text, llm, compact=True)
    texts = [f.text for f in r.flags]
    assert texts[0] == "The room was almost too dark to see."
    assert "The door was very old." not in texts
    assert r.cleared[0].text == "The door was very old."
    assert "THE CHAPTER" not in llm.prompts[0]          # local models: candidates only
    assert od.review_chapter(text).flags                # no model: the scan


def test_apply_expansion_and_state():
    from src.ui.overdescription_panel import ExpansionState
    flag = od.scan(PASSAGE)[0]
    state = ExpansionState(PASSAGE)
    assert state.apply(0, flag, "Dark.")
    assert state.text.startswith("Dark. She almost fell") and state.changed
    assert state.apply(0, flag, "Pitch dark.")                 # re-accepting replaces
    assert state.text.startswith("Pitch dark. She")
    assert state.apply(0, flag, flag.text) and not state.changed   # keep original


# ── UI ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_suggestions_dialog_has_the_sub_module_without_a_model(app, project, chapter):
    from src.ui.passage_critique_dialog import PassageCritiqueDialog, SuggestionWorker

    class NoModel(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (None, "AI features are turned off."))

        def start(self):
            self.run()

    dlg = PassageCritiqueDialog(PASSAGE, 0, len(PASSAGE), project, chapter,
                                worker_factory=NoModel)
    assert "Overly descriptive (" in dlg.top_tabs.tabText(1)
    assert dlg.passage_view.extraSelections()                  # highlighted
    panel = dlg.over_panel
    assert panel.flag_list.count() >= 1 and not panel.more_btn.isEnabled()
    assert "no AI" in panel.status.text()
    panel.flag_list.setCurrentRow(0)
    panel.preview.setPlainText("She couldn't see her own hands.")
    panel._accept()
    assert dlg.suggestion_list.count() == 1
    assert "Your text, expanded" in dlg.suggestion_list.item(0).text()
    dlg._use_selected()
    assert dlg.replacement.startswith("She couldn't see her own hands. She almost fell")


def test_suggestions_dialog_uses_the_same_model_for_expansions(app, project, chapter):
    from src.ui.passage_critique_dialog import PassageCritiqueDialog, SuggestionWorker
    critique = ("WHAT WORKS:\n- Quick.\n\nSUGGESTION 1:\nShe climbed into the dark attic and "
                "nearly fell on the last stair.\nWHY: a\n\nSUGGESTION 2:\nThe attic was dark, "
                "and she almost fell on the last stair.\nWHY: b\n\nSUGGESTION 3:\nShe stumbled "
                "on the last stair of the dark attic.\nWHY: c")
    llm = FakeLLM(critique, REVIEW)

    class Now(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (llm, ""), search_factory=lambda p: None)

        def start(self):
            self.run()

    dlg = PassageCritiqueDialog(PASSAGE, 0, len(PASSAGE), project, chapter, worker_factory=Now)
    assert dlg.over_panel.flag_list.count() == 2 and dlg.over_panel.more_btn.isEnabled()
    assert "judged 1 other word-scan hit fine" in dlg.over_panel.status.text()
    assert dlg.suggestion_list.count() == 3                     # the critique's rewrites
    dlg.over_panel.flag_list.setCurrentRow(0)
    assert dlg.over_panel.preview.toPlainText().startswith("She felt for the rafters")
    dlg.over_panel._accept()
    assert "Your text, expanded" in dlg.suggestion_list.item(0).text()
    assert dlg.preview_edit.toPlainText().startswith("She felt for the rafters")


def test_expand_dialog_and_editor(app, project, chapter, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    from src.ui import overdescription_panel as op

    class Now(op.ReviewWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (FakeLLM(REVIEW), ""))

        def start(self):
            self.run()

    dlg = op.ExpandStatementDialog(PASSAGE, 0, len(PASSAGE), project, chapter,
                                   worker_factory=Now)
    assert dlg.panel.flag_list.count() == 2 and not dlg.use_btn.isEnabled()
    dlg.panel.flag_list.setCurrentRow(1)
    dlg.panel._accept()
    dlg._use()
    assert dlg.replacement.endswith("Trunks stood shoulder to shoulder under the eaves.")

    # The editor puts the accepted version in place of the passage.
    seen = {}

    class Accepting:
        def __init__(self, text, start, end, *a, **k):
            seen["passage"] = text[start:end]
            self.replacement = "It was dark."

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(op, "ExpandStatementDialog", Accepting)
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    doc = ed.editor.toPlainText()
    i = doc.index("The room")
    ed.expand_statement(i, i + len("The room was almost too dark to see."))
    assert seen["passage"] == "The room was almost too dark to see."
    assert ed.editor.toPlainText() == doc.replace(seen["passage"], "It was dark.")


def test_critique_tab_lists_statements_and_links_to_the_editor(app):
    from src.ui.grader_widget import CritiqueWorker, GraderWidget
    worker = CritiqueWorker([{"title": "Attic", "text": PASSAGE, "index": 0, "id": "ch"}],
                            [], "literary", None)
    data = worker._overdescription(None, None, lambda m: None)
    assert data["Attic"]["id"] == "ch" and not data["Attic"]["used_ai"]
    w = GraderWidget()
    html, total = w._format_overdescription_html(data)
    assert total >= 1 and "too dark" in html and "overdesc:0" in html
    got = []
    w.expand_statement_requested.connect(lambda *a: got.append(a))
    from PyQt6.QtCore import QUrl
    w._handle_link_click(QUrl("overdesc:0"))
    assert got and got[0][0] == "ch" and got[0][2] == "The room was almost too dark to see."
