"""The Prose Profile tab's "This chapter" panel and the chat's prose profile."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QGroupBox, QPlainTextEdit, QPushButton, QToolButton

from src.ai import prose_chat, prose_snapshot
from src.ai.chat_actions import detect_intent, extract_actions
from src.models.project import Chapter, WriterProject

TEXT = ('He ran quickly down the hall. "Stop!" she shouted. The door was opened by someone. '
        'It was very dark and he could not see. ') * 30


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_cache():
    prose_snapshot._CACHE.clear()
    yield
    prose_snapshot._CACHE.clear()


def _project(genre="thriller", tone="tense"):
    p = WriterProject(name="Saga")
    p.prose_profile.genre = genre
    p.prose_profile.tone = tone
    return p


# ── The measures ───────────────────────────────────────────────────────

def test_measures_beside_the_genre_targets():
    snap = prose_snapshot.measure(_project(), TEXT, "One")
    labels = [r.label for r in snap.rows]
    assert labels == ["Sentence length", "Sentence variety", "Dialogue", "Adverbs",
                      "Passive voice", "Readability", "Length"]
    length = snap.rows[0]
    assert length.verdict == "below" and "words" in length.target     # 6 words, thriller 8–16
    assert snap.genre_label.startswith("Thriller")
    assert ("Tone", "tense") in snap.targets


def test_headline_counts_only_measures_with_a_target():
    snap = prose_snapshot.measure(_project(), TEXT, "One")
    compared = [r for r in snap.rows if r.verdict]
    assert f"of {len(compared)} measures" in snap.headline()
    assert snap.rows[5].verdict == ""             # readability: no published figures in tests


def test_a_short_chapter_says_so():
    snap = prose_snapshot.measure(_project(), "Too short.", "One")
    assert not snap.rows and "at least" in snap.headline()


def test_no_genre_uses_general_fiction():
    snap = prose_snapshot.measure(_project(genre="", tone=""), TEXT, "One")
    assert snap.genre_label == "general fiction" and snap.targets == []


def test_markdown_and_context():
    snap = prose_snapshot.measure(_project(), TEXT, "One")
    md = snap.markdown()
    assert "“One”" in md and "review my prose" in md and "**Tone** tense" in md
    assert "review my prose" not in snap.markdown(review_hint=False)
    assert snap.context_text().startswith("=== CURRENT CHAPTER MEASURED")


def test_remembered_until_the_text_or_profile_changes():
    p = _project()
    a = prose_snapshot.measure(p, TEXT, "One")
    assert prose_snapshot.measure(p, TEXT, "One") is a
    p.prose_profile.tone = "warm"
    assert prose_snapshot.measure(p, TEXT, "One") is not a


# ── What the chat recognises ───────────────────────────────────────────

@pytest.mark.parametrize("message,depth", [
    ("prose profile", "summary"),
    ("Can I get a prose summary?", "summary"),
    ("summarise my prose", "summary"),
    ("How does this chapter compare to the genre?", "summary"),
    ("review my prose", "review"),
    ("analyse the chapter's voice", "review"),
    ("Does this chapter fit the profile?", "review"),
])
def test_chat_requests(message, depth):
    assert detect_intent(message) == {"kind": "prose_profile", "depth": depth}


@pytest.mark.parametrize("message", [
    "set the tone to dark", "Change the prose profile voice to wry",
    "what is prose?", "write the next scene",
])
def test_not_a_prose_request(message):
    assert prose_chat.detect(message) is None


def test_the_critique_requests_are_unchanged():
    assert detect_intent("critique this chapter") == {"kind": "critique", "scope": "chapter"}
    assert detect_intent("give me a full review of the manuscript")["scope"] == "manuscript"


def test_the_model_can_ask_for_it():
    actions, rest = extract_actions('Here you go. <prose_profile>{"depth": "review"}</prose_profile>')
    assert actions == [("prose_profile", {"depth": "review"})]
    assert "prose_profile" not in rest


# ── The panel and the chat, on a stand-in main window ──────────────────

class _Chat:
    def __init__(self):
        self.messages = []

    def add_message(self, who, text):
        self.messages.append((who, text))


def _window(app, text=TEXT):
    from src.ui.prose_profile_widget import ProseProfileWidget
    project = _project()
    editor = QPlainTextEdit()
    editor.setPlainText(text)
    ce = SimpleNamespace(chapter=Chapter(id="c1", number=1, title="One", content=text),
                         editor=editor)
    widget = ProseProfileWidget()
    widget.load_data(project.prose_profile)
    turns = []
    mw = SimpleNamespace(current_project=project, prose_profile_widget=widget,
                         manuscript_editor=SimpleNamespace(current_chapter_editor=ce),
                         chat_widget=_Chat(),
                         _record_chat_turn=lambda u, a: turns.append((u, a)))
    mw.turns = turns
    return mw


def test_panel_shows_this_chapter_with_links_not_buttons(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    widget = mw.prose_profile_widget
    before = (len(widget.findChildren((QPushButton, QToolButton))),
              len(widget.findChildren(QGroupBox)))
    panel = ppc.install(mw)
    assert ppc.install(mw) is panel                               # once only
    panel.refresh()
    assert panel.title.text() == "This chapter: One"
    assert "Sentence length" in panel.body.text()
    assert "Full review in the Critique" in panel.links.text()
    after = (len(widget.findChildren((QPushButton, QToolButton))),
             len(widget.findChildren(QGroupBox)))
    assert after == before                                         # rule 13


def test_panel_uses_the_targets_as_typed(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    panel = ppc.install(mw)
    mw.prose_profile_widget.genre_edit.setText("")                  # not saved yet
    panel.refresh()
    assert "general fiction" in panel.body.text()


def test_panel_without_a_chapter(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    mw.manuscript_editor.current_chapter_editor = None
    panel = ppc.install(mw)
    panel.refresh()
    assert "Open a chapter" in panel.body.text() and panel.links.isHidden()


def test_panel_sends_the_summary_to_the_chat(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    panel = ppc.install(mw)
    panel.refresh()
    panel._on_link("chat")
    assert "Prose profile" in mw.chat_widget.messages[-1][1]


def test_panel_review_runs_the_prose_report(app, monkeypatch):
    from src.ui import analysis_menu, prose_profile_chapter as ppc
    ran = []
    monkeypatch.setattr(analysis_menu, "run", lambda ce, key: ran.append(key) or True)
    mw = _window(app)
    ppc.install(mw)._on_link("review")
    assert ran == ["prose"]


def test_chat_summary_answers_at_once(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    assert ppc.run_chat(mw, {"kind": "prose_profile", "depth": "summary"}, "prose profile")
    text = mw.chat_widget.messages[-1][1]
    assert "Sentence length" in text and "review my prose" in text
    assert mw.turns == [("prose profile", text)]


def test_chat_review_also_starts_the_report(app, monkeypatch):
    from src.ui import analysis_menu, prose_profile_chapter as ppc
    ran = []
    monkeypatch.setattr(analysis_menu, "run", lambda ce, key: ran.append(key) or True)
    mw = _window(app)
    ppc.run_chat(mw, {"kind": "prose_profile", "depth": "review"}, "review my prose")
    assert ran == ["prose"]
    assert "Prose profile fit" in mw.chat_widget.messages[-1][1]


def test_chat_without_a_chapter(app):
    from src.ui import prose_profile_chapter as ppc
    mw = _window(app)
    mw.manuscript_editor.current_chapter_editor = None
    ppc.run_chat(mw, {"kind": "prose_profile", "depth": "summary"}, "prose profile")
    assert "Open a chapter" in mw.chat_widget.messages[-1][1]
    assert ppc.context_for(mw) == ""


def test_chat_context_has_the_measures(app):
    from src.ui import prose_profile_chapter as ppc
    assert "Sentence length" in ppc.context_for(_window(app))
