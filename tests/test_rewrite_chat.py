"""Talking the results through in Suggestions and Rephrase."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import rewrite_chat as rc
from src.ai.rewrite_quality import check_rewrite

PASSAGE = ("Mara went to the bathroom and washed her face. "
           "Then she returned to her room and locked the door.")


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


# ── Engine ────────────────────────────────────────────────────────

def test_question_gets_an_answer_and_no_versions():
    r = rc.parse_chat_reply("EDITOR: Version 2 drops the mirror beat, so the pause is lost.")
    assert r.reply == "Version 2 drops the mirror beat, so the pause is lost." and not r.versions


def test_reply_and_versions_are_separated():
    r = rc.parse_chat_reply("Sure — here's a darker take.\n\nVERSION 1 (darker):\nMara "
                            "dragged herself to the bathroom.\nWHY: heavier verbs\n\n"
                            "VERSION 2 (quiet):\nMara washed her face in the dark.\nWHY: hush")
    assert r.reply == "Sure — here's a darker take."
    assert [v.text for v in r.versions] == ["Mara dragged herself to the bathroom.",
                                            "Mara washed her face in the dark."]
    assert r.versions[0].angle == "darker" and r.versions[0].why == "heavier verbs"


def test_prompt_carries_versions_history_and_the_new_message():
    turns = [rc.ChatTurn("author", "make it darker"), rc.ChatTurn("editor", "Done — see 1.")]
    prompt = rc.build_chat_prompt([("THE SCENE", "Night, the house asleep.")], PASSAGE,
                                  [("tightened", "Mara washed up."), ("", "Mara went in.")],
                                  turns, "combine 1 and 2")
    assert "[1] (tightened) Mara washed up." in prompt and "[2] Mara went in." in prompt
    assert "AUTHOR: make it darker\nEDITOR: Done — see 1." in prompt
    assert prompt.index("THE AUTHOR NOW SAYS") < prompt.index("combine 1 and 2")
    assert "Night, the house asleep." in prompt


def test_only_recent_turns_are_kept():
    turns = [rc.ChatTurn("author", f"message {i}") for i in range(20)]
    prompt = rc.build_chat_prompt([], PASSAGE, [], turns, "now")
    assert "message 19" in prompt and "message 11" not in prompt


def checker(message=""):
    def check(found):
        return [check_rewrite(PASSAGE, v.text, focus=message) for v in found]
    return check


def test_a_version_that_reverses_events_gets_one_retry():
    reversed_ = ("Mara returned to her room and locked the door. She went to the bathroom and "
                 "washed her face.")
    llm = FakeLLM(f"Here you go.\n\nVERSION 1 (tighter):\n{reversed_}\nWHY: x",
                  "VERSION 1 (tighter):\nMara washed her face in the bathroom, then returned "
                  "to her room and locked the door.\nWHY: y")
    r = rc.chat_turn(llm, system="s", context=[], passage=PASSAGE, versions=[], turns=[],
                     message="tighten it", check=checker("tighten it"))
    assert r.versions[0].text.startswith("Mara washed her face in the bathroom")
    assert "REJECTED" in llm.prompts[1] and "reverses the order" in llm.prompts[1]


def test_reorder_the_author_asks_for_is_allowed():
    swapped = ("Mara returned to her room and locked the door. She went to the bathroom and "
               "washed her face.")
    llm = FakeLLM(f"Swapped.\n\nVERSION 1 (swapped):\n{swapped}\nWHY: as asked")
    r = rc.chat_turn(llm, system="s", context=[], passage=PASSAGE, versions=[], turns=[],
                     message="swap the order so she locks the door first",
                     check=checker("swap the order so she locks the door first"))
    assert r.versions[0].text == swapped and len(llm.prompts) == 1


def test_empty_reply_is_explained():
    r = rc.chat_turn(FakeLLM(""), system="s", context=[], passage=PASSAGE, versions=[],
                     turns=[], message="hi")
    assert "didn't reply" in r.reply


# ── Suggestions dialog ────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait(dlg, app):
    if dlg._chat_worker is not None:
        dlg._chat_worker.wait(5000)
    app.processEvents()


def suggestions_dialog(app, llm):
    """The Improve window's 💡 Suggestions (the old Suggestions window it
    replaced went in D.12)."""
    from src.ui.improve_window import ImproveWindow
    from src.ui.passage_critique_dialog import SuggestionWorker

    class Now(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (llm, ""), search_factory=lambda p: None)

        def start(self):
            self.run()

    return ImproveWindow(PASSAGE, 0, len(PASSAGE), None, None, suggestion_worker=Now)


FIRST = ("WHAT WORKS:\n- Clear sequence.\n\nWHAT DOESN'T WORK:\n- Flat verbs.\n\n"
         "SUGGESTION 1 (tightened):\nMara washed her face in the bathroom, then returned to "
         "her room and locked the door.\nWHY: a\n\nSUGGESTION 2 (restructured):\nIn the "
         "bathroom Mara splashed her face. Back in her room, she turned the lock.\nWHY: b\n\n"
         "SUGGESTION 3 (new focus):\nCold water on her face, then the long hall back to her "
         "room, where she locked the door.\nWHY: c")


def test_suggestions_conversation(app):
    llm = FakeLLM(FIRST,
                  "",           # the overly-descriptive review (nothing readable: scan only)
                  "Suggestion 2 splits the beats so the lock lands as its own moment.",
                  "Here's 1 and 3 together.\n\nVERSION 1 (combined):\nCold water on her face "
                  "in the bathroom; then the long hall back to her room, and the lock.\nWHY: "
                  "best of both")
    win = suggestions_dialog(app, llm)
    tab = win.tab_objects["suggestions"]
    assert win.version_list.count() == 3 and tab.talk.send_btn.isEnabled()

    tab._send("why is 2 better?")
    wait(tab, app)
    assert "splits the beats" in tab.talk.plain_text()
    assert win.version_list.count() == 3                        # a question: no new versions
    assert "YOUR CRITIQUE OF THE PASSAGE" in llm.prompts[-1] and "Flat verbs" in llm.prompts[-1]

    tab._send("combine 1 and 3")
    wait(tab, app)
    assert win.version_list.count() == 4
    assert win.version_list.item(0).text().startswith("Suggestion 1 · revised")
    assert win.preview_edit.toPlainText().startswith("Cold water on her face in the bathroom")
    assert "AUTHOR: why is 2 better?" in llm.prompts[-1]           # remembers the conversation
    assert "1 new version at the top" in tab.talk.status.text()


def test_new_critique_starts_a_new_conversation(app):
    llm = FakeLLM(FIRST, "", "Because it's tighter.", FIRST)   # "": overly-descriptive review
    win = suggestions_dialog(app, llm)
    tab = win.tab_objects["suggestions"]
    tab._send("why?")
    wait(tab, app)
    assert tab.turns
    tab._worker = None
    tab.generate()
    assert tab.turns == [] and tab.talk.plain_text() == ""


# ── Rephrase dialog ───────────────────────────────────────────────

@pytest.fixture
def rephrase(app, monkeypatch):
    from src.ai.rephrasing_agent import RephraseOption, RephraseResult, RephrasingAgent
    from src.ui import rephrase_dialog as rd
    llm = FakeLLM("Option 1 rushes the lock — here's a slower one.\n\nVERSION 1 (slower):\n"
                  "Mara washed her face slowly in the bathroom. Then she returned to her room "
                  "and locked the door.\nWHY: pacing")
    monkeypatch.setattr(rd.RephraseDialog, "_init_agent",
                        lambda self: setattr(self, "agent", RephrasingAgent()))
    monkeypatch.setattr(rd.RephraseDialog, "_moment_llm", lambda self: llm)
    monkeypatch.setattr(rd.RephraseDialog, "_get_rag_for_refinement", lambda self, r: "")
    dlg = rd.RephraseDialog(PASSAGE, None, None)
    dlg._on_generation_complete(RephraseResult(
        original=PASSAGE, model_used="m", cost_estimate=0.0,
        options=[RephraseOption("Mara washed up and locked herself in.", "concise", "neutral", "e")]))
    dlg.llm = llm
    return dlg


def test_rephrase_conversation_replies_and_adds_versions(rephrase, app):
    rephrase.chat.message_sent.emit("it feels rushed")
    wait(rephrase, app)
    assert "rushes the lock" in rephrase.chat.plain_text()
    assert rephrase.options_list.count() == 2
    assert rephrase.result.options[0].style == "revised: slower"
    assert rephrase.result.options[0].text.startswith("Mara washed her face slowly")
    prompt = rephrase.llm.prompts[-1]
    assert "[1] (concise) Mara washed up and locked herself in." in prompt
    assert "EVENTS IN THE ORDER THEY HAPPEN" in prompt


def test_rephrase_without_a_model_still_regenerates(rephrase, monkeypatch):
    rephrase.agent.use_python_libraries = True
    calls = []
    monkeypatch.setattr(rephrase, "_generate_options", lambda refinement=None: calls.append(refinement))
    rephrase._refine_results("make it darker")
    assert calls and calls[0]["instructions"] == ["make it darker"]
    assert "can't follow written feedback" in rephrase.chat.plain_text()
