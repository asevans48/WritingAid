"""The AI reading of the author's style and voice (when a model is configured)."""

import json
import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import voice_profile as vp
from src.ai.writer_voice import WriterVoice, analyze_writer_voice, project_voice
from src.data import publishing_goal as pg
from src.models.project import Chapter, Manuscript, WriterProject

PARA = ("The rain came in off the river and found every gap in the old boards, and she "
        "sat with it a long time, counting the drips, not moving, because moving meant "
        "deciding and she was not ready to decide anything at all. Cold. Then colder.")
REPLY = """VOICE: Close third person, patient and wry, lingering on weather and small sounds.
STYLE: Long cumulative sentences broken by blunt fragments; few metaphors.
HABIT: Fragments ("Cold. Then colder.") set the rhythm; they are deliberate.
- HABIT: Repeats "and" to build momentum through long sentences.
**HABIT:** Adverbs in dialogue tags, kept short."""


class FakeLLM:
    model = "fake-model"

    def __init__(self, reply=REPLY):
        self.reply, self.calls = reply, []

    def generate_text(self, prompt, system_prompt="", **kw):
        self.calls.append(prompt)
        return self.reply


@pytest.fixture(autouse=True)
def _ai_on(monkeypatch):
    monkeypatch.setattr(vp, "ai_enabled", lambda: True)


def _project(tmp_path, chapters=4):
    path = tmp_path / "book.writerproj"
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(path)
    for i in range(chapters):
        ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"C{i}",
                     folder_root=p.manuscript.folder_root)
        ch.content = "\n\n".join([PARA] * 12 + ['"Go," she said.'])
        p.manuscript.chapters.append(ch)
    return p


def _voice(p):
    return analyze_writer_voice("\n\n".join(c.content for c in p.manuscript.chapters))


def test_reading_is_parsed_from_loose_formats():
    r = vp.parse_reading(REPLY)
    assert r["voice"].startswith("Close third person")
    assert r["style"].startswith("Long cumulative")
    assert len(r["habits"]) == 3 and r["habits"][2] == "Adverbs in dialogue tags, kept short."


def test_one_model_call_then_cached_until_the_prose_changes(tmp_path):
    p, llm = _project(tmp_path), FakeLLM()
    v = vp.ensure(_voice(p), p, None, llm)
    assert v.has_ai_reading and len(v.ai_habits) == 3 and v.ai_model == "fake-model"
    assert len(llm.calls) == 1 and "Cold. Then colder." in llm.calls[0]
    assert '"Go," she said.' not in llm.calls[0]            # narration only
    stored = json.loads(pg.readiness_path(p).read_text())["voice"]["main"]
    assert stored["voice"] == v.ai_voice and stored["sample"]

    vp.ensure(_voice(p), p, None, llm)                       # same prose: cached
    assert len(llm.calls) == 1
    p.manuscript.chapters[0].content = p.manuscript.chapters[0].content.replace("rain", "snow")
    vp.ensure(_voice(p), p, None, llm)                       # changed prose: read again
    assert len(llm.calls) == 2


def test_the_route_and_other_keys_are_kept(tmp_path):
    p = _project(tmp_path)
    pg.set_route(p, None, "self")
    vp.ensure(_voice(p), p, None, FakeLLM())
    assert pg.route_for(p) == "self"
    assert "main" in pg.load(p)["voice"]


def test_nothing_happens_with_ai_off(tmp_path, monkeypatch):
    p, llm = _project(tmp_path), FakeLLM()
    vp.ensure(_voice(p), p, None, llm)                       # stored while on
    monkeypatch.setattr(vp, "ai_enabled", lambda: False)
    v = vp.ensure(_voice(p), p, None, llm)
    assert not v.has_ai_reading and len(llm.calls) == 1
    assert not project_voice(p, p.manuscript.chapters[0]).has_ai_reading


def test_a_model_error_or_nonsense_changes_nothing(tmp_path):
    p = _project(tmp_path)
    for reply in ("Error generating text: timeout", "I cannot help with that."):
        v = vp.ensure(_voice(p), p, None, FakeLLM(reply))
        assert not v.has_ai_reading
    assert not pg.readiness_path(p).exists()


def test_too_little_prose_is_not_read(tmp_path):
    p, llm = _project(tmp_path, chapters=1), FakeLLM()
    p.manuscript.chapters[0].content = PARA
    vp.ensure(_voice(p), p, None, llm)
    assert llm.calls == []


def test_prompts_carry_the_reading():
    v = vp.apply(WriterVoice(), vp.parse_reading(REPLY))
    assert "Deliberate habits" in v.to_critique_prompt()     # no measurements needed
    assert "Fragments" in v.to_prompt()
    measured = vp.apply(analyze_writer_voice("\n\n".join([PARA] * 10)), vp.parse_reading(REPLY))
    text = measured.to_critique_prompt()
    assert "AUTHOR'S MEASURED VOICE" in text and "Close third person" in text
    assert "Close third person" not in vp.build_prompt("sample", measured)   # old reading not fed back


def test_stored_reading_reaches_rewrites_and_the_critique(tmp_path):
    from src.ai.chapter_analysis_agent import VoiceAnalyzer, resolve_genre_profile
    p = _project(tmp_path)
    vp.ensure(_voice(p), p, None, FakeLLM())
    v = project_voice(p, p.manuscript.chapters[1])           # no model call here
    assert v.has_ai_reading
    analyzer = VoiceAnalyzer(project=p)
    analyzer.writer_voice = v
    section = analyzer.run(p.manuscript.chapters[1].content, "C1", 1,
                           resolve_genre_profile("literary"), "", "", None, None)
    assert section.summary.startswith("Your voice, as the model reads it: Close third person")
    prompt, _ = analyzer._build_prompt(p.manuscript.chapters[1].content, section,
                                       resolve_genre_profile("literary"), "", "", None)
    assert "Deliberate habits" in prompt


def test_a_novella_has_its_own_reading(tmp_path):
    p, llm = _project(tmp_path), FakeLLM()
    vp.ensure(_voice(p), p, None, llm)
    assert vp.cached(p, "some-novella") is None
    assert vp.cached(p, None)["voice"].startswith("Close")
