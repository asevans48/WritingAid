"""7.2: each scene's tension from a (fake) model, stored by chapter hash, drawn on the chart."""

from types import SimpleNamespace as NS

import pytest

from src.ai import plan_match, scene_tension as st
from src.ai import reverse_outline as ro

TEXT = ("Rain fell on the harbor. Mara watched the boats.\n\n***\n\n"
        "The knife came out. Tobin backed against the wall.\n\n***\n\n"
        "Morning came cold and grey.")


class FakeLLM:
    model = "fake"

    def __init__(self, reply=None):
        self.calls, self.prompts = 0, []
        self.reply = reply or ("TENSION | 1 | 2 | a quiet watch\n"
                               "TENSION | 2 | 5 | a knife at his throat\n"
                               "TENSION | scene 3 | 1 | calm after")

    def generate_text(self, prompt, system, **kw):
        self.calls += 1
        self.prompts.append((prompt, kw))
        return self.reply


def _project(tmp_path):
    return NS(project_path=str(tmp_path / "Book.writerproj"), name="Book")


def test_one_request_numbers_the_outlines_scenes():
    llm = FakeLLM()
    got = st.rate_chapter(llm, NS(title="One"), TEXT)
    assert got["values"] == [2, 5, 1] and got["scenes"] == 3
    assert got["why"][1] == "a knife at his throat"
    prompt, kw = llm.prompts[0]
    assert "[SCENE 1]" in prompt and "[SCENE 3]" in prompt and "[SCENE 4]" not in prompt
    assert kw["temperature"] == st.TEMPERATURE and llm.calls == 1


def test_a_scene_the_model_skipped_has_no_rating_and_nonsense_is_an_error():
    got = st.parse("TENSION | 2 | 4 | x\nTENSION | 9 | 5 | no such scene", 3)
    assert got["values"] == [None, 4, None]
    with pytest.raises(RuntimeError):
        st.rate_chapter(FakeLLM("I think it is tense."), NS(title="One"), TEXT)


def test_a_long_chapter_is_cut_evenly_and_keeps_every_scene():
    text = "\n\n***\n\n".join(" ".join(["word"] * 3000) for _ in range(3))
    prompt = st.build_prompt(NS(title="Long"), text, ro.split_scenes(text))
    assert prompt.count("[SCENE") == 3 and len(prompt.split()) < st.MAX_WORDS + 200


def test_stored_by_chapter_hash_and_asked_once(tmp_path):
    project, llm = _project(tmp_path), FakeLLM()
    ch = NS(id="c1", title="One")
    first = st.ensure(llm, project, None, ch, TEXT)
    again = st.ensure(llm, project, None, ch, TEXT)
    assert llm.calls == 1 and again["values"] == first["values"] == [2, 5, 1]
    assert st.stored(project, "c1", TEXT)["values"] == [2, 5, 1]
    assert st.stored(project, "c1", TEXT + " Changed.") is None        # an edit: read again
    st.ensure(llm, project, None, ch, TEXT + " Changed.")
    assert llm.calls == 2


def test_other_readiness_keys_are_kept(tmp_path):
    from src.data import readiness_state as rs
    project = _project(tmp_path)
    assert rs.update(project, lambda d: d.__setitem__("digest", {"_": {"c9": {"x": 1}}}))
    st.ensure(FakeLLM(), project, None, NS(id="c1", title="One"), TEXT)
    data = rs.load(project)
    assert data["digest"] == {"_": {"c9": {"x": 1}}} and "tension" in data


def test_a_damaged_file_means_no_tension(tmp_path, monkeypatch):
    from src.data import safe_store
    monkeypatch.setattr(safe_store, "_notifier", None)       # no window to tell here
    (tmp_path / "Book.readiness.json").write_text("{broken")
    assert st.stored(_project(tmp_path), "c1", TEXT) is None


def test_the_chart_gets_tension_only_from_stored_ratings(tmp_path):
    project = _project(tmp_path)
    try:
        st.install(lambda: project)
        points = plan_match.book_pacing([("c1", TEXT)])
        assert [p.tension for p in points] == [None, None, None]            # not read yet
        st.ensure(FakeLLM(), project, None, NS(id="c1", title="One"), TEXT)
        points = plan_match.book_pacing([("c1", TEXT)])
        assert [p.tension for p in points] == [0.25, 1.0, 0.0]
    finally:
        plan_match.set_tension_source(None)


def test_agreement_measures():
    g = st.agreement([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert g["exact"] == 1 and g["within_one"] == 1 and g["kappa"] == 1
    g = st.agreement([3, 3, 3], [3, 3, 3])                  # one rating everywhere: unknown
    assert g["kappa"] != g["kappa"]
    g = st.agreement([1, 5, None], [5, 1, 2])
    assert g["n"] == 2 and g["within_one"] == 0 and g["kappa"] < 0


# ── Made with the outline, when the book is checked with the model ────

DIGEST = 'SCENE | Mara | Mara watches | NONE | "Rain fell on the harbor"\nREADER | 3 | ok | NONE'


class CheckLLM:
    model = "fake"

    def __init__(self, tension="TENSION | 1 | 2 | x\nTENSION | 2 | 5 | y\nTENSION | 3 | 1 | z"):
        self.prompts, self.tension = [], tension

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        if "Outline this chapter" in prompt:
            return DIGEST
        if "Begin your answer with: TENSION" in prompt:
            return self.tension
        return "NONE"


def _book(tmp_path):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="Chapter 1", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


def _tension_asks(llm):
    return [x for x in llm.prompts if "Begin your answer with: TENSION" in x]


def test_the_model_check_rates_tension_once_with_the_outline(tmp_path, monkeypatch):
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    p, llm = _book(tmp_path), CheckLLM()
    rd.chapter_report(p, p.manuscript.chapters[0], llm=llm)
    assert len(_tension_asks(llm)) == 1
    assert st.stored(p, "c1", TEXT)["values"] == [2, 5, 1]
    llm2 = CheckLLM()
    rd.chapter_report(p, p.manuscript.chapters[0], llm=llm2, use_cache=False)
    assert not _tension_asks(llm2)                                  # stored: not asked again


def test_an_unreadable_tension_answer_never_fails_the_outline(tmp_path, monkeypatch):
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    p = _book(tmp_path)
    r = rd.chapter_report(p, p.manuscript.chapters[0], llm=CheckLLM("no idea")).results
    assert r["scene_purpose"].status != rd.Status.COULD_NOT_CHECK
    assert r["scene_purpose"].count == 1
    assert st.stored(p, "c1", TEXT) is None


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_outline_shows_each_scenes_tension(app, tmp_path):
    from PyQt6.QtCore import QUrl
    from src.ui.readiness_issues import ChapterIssues
    project = _project(tmp_path)
    st.ensure(FakeLLM(), project, None, NS(id="c1", title="One"), TEXT)
    view = ChapterIssues()
    view.outline_project = lambda: project
    ch = NS(chapter_id="c1", number=1, title="One", words=20, text_hash="", is_opening=False,
            results={}, stage="", scope=None)
    view.show_chapter(ch, None, TEXT, {})
    toggle = next(i for i, (k, _) in enumerate(view._links) if k == "outline")
    view._on_link(QUrl(f"issue:{toggle}"))
    page = view.toPlainText()
    assert "Tension 5 of 5: a knife at his throat" in page and "Tension 1 of 5: calm after" in page


# ── The firmer prompt and reading bare rows (27 Nov) ──────────────────

def test_the_prompt_asks_for_each_scene_as_a_whole_with_an_example():
    llm = FakeLLM()
    st.rate_chapter(llm, NS(title="One"), TEXT)
    prompt = llm.prompts[0][0]
    assert "as a whole" in prompt and "Do not split a scene" in prompt
    assert "exactly 3 lines" in prompt and "there are 3 scenes" in prompt
    assert prompt.rstrip().endswith("Begin your answer with: TENSION | 1 |")
    assert "TENSION | 2 | 4 | the stranger draws a knife" in prompt          # the example


def test_bare_rows_are_read_when_they_are_one_per_numbered_scene():
    assert st.parse("1 | 2 | quiet\n2 | 5 | knife\n3 | 1 | calm", 3)["values"] == [2, 5, 1]
    cydonia = ("TENSION | scene number | 1 to 5 | why, under 12 words\n"
               "1 | 1 | 3 | a\n2 | 2 | 4 | b")
    got = st.parse(cydonia, 2)
    assert got["values"] == [3, 4] and got["why"] == ["a", "b"]


def test_rows_for_beats_or_unclear_columns_are_never_guessed():
    beats = "TENSION | scene number | 1 to 5 | why\n1 | 1 | 3 | a\n2 | 1 | 2 | b\n3 | 1 | 3 | c"
    assert st.parse(beats, 1)["values"] == [None]                     # beats of one scene
    numbered = "1 | 1 | 3 | a\n2 | 2 | 2 | b\n3 | 3 | 1 | c"
    assert st.parse(numbered, 1)["values"] == [None]                  # three rows, one scene
    assert st.parse("1 | 3 | 2 | which is the rating?", 1)["values"] == [None]
    assert st.parse("2 | 4 | x\n1 | 3 | y", 2)["values"] == [None, None]   # out of order
    # TENSION lines win over bare rows
    assert st.parse("TENSION | 2 | 5 | x\n1 | 1 | 1 | y", 2)["values"] == [None, 5]


# ── "Couldn't be read" is stored, and that model is not asked again ───

class NamedLLM(FakeLLM):
    def __init__(self, model, reply="I would say it is tense."):
        super().__init__(reply)
        self.model = model


def _ensure(llm, project, text=TEXT):
    try:
        return st.ensure(llm, project, None, NS(id="c1", title="One"), text)
    except st.Unreadable:
        return None


def test_an_unreadable_answer_is_stored_and_that_model_not_asked_again(tmp_path):
    project, llm = _project(tmp_path), NamedLLM("cydonia")
    assert _ensure(llm, project) is None and _ensure(llm, project) is None
    assert llm.calls == 1
    assert st.stored(project, "c1", TEXT) is None                    # nothing shown
    try:
        st.install(lambda: project)
        assert [p.tension for p in plan_match.book_pacing([("c1", TEXT)])] == [None] * 3
    finally:
        plan_match.set_tension_source(None)


def test_asked_again_when_the_chapter_the_model_or_the_markers_change(tmp_path, monkeypatch):
    project, cyd = _project(tmp_path), NamedLLM("cydonia")
    _ensure(cyd, project)
    _ensure(cyd, project, TEXT + " Changed.")                         # the chapter changed
    assert cyd.calls == 2
    gemma = NamedLLM("gemma", FakeLLM().reply)                        # another model in Settings
    assert _ensure(gemma, project)["values"] == [2, 5, 1] and gemma.calls == 1
    project2, cyd2 = _project(tmp_path / "other"), NamedLLM("cydonia")
    (tmp_path / "other").mkdir()
    _ensure(cyd2, project2)
    monkeypatch.setattr(st, "_marks", lambda *a: [TEXT.index("The knife")])   # a marker moved
    _ensure(cyd2, project2)
    assert cyd2.calls == 2


def test_a_failure_to_answer_is_not_stored(tmp_path):
    project, llm = _project(tmp_path), NamedLLM("cydonia", "Error generating text: no memory")
    _ensure_raises = lambda: st.ensure(llm, project, None, NS(id="c1", title="One"), TEXT)  # noqa: E731
    import pytest as _pytest
    for _ in range(2):
        with _pytest.raises(RuntimeError):
            _ensure_raises()
    assert llm.calls == 2                                             # asked again next time


def test_unreadable_from_the_older_prompt_is_asked_again(tmp_path):
    from src.ai.readiness import text_hash
    project, llm = _project(tmp_path), NamedLLM("cydonia", FakeLLM().reply)
    st.save(project, None, "c1", dict(unreadable=True, model="cydonia", prompt=1,
                                      text_hash=text_hash(TEXT), v=st.VERSION, scenes=3))
    assert _ensure(llm, project)["values"] == [2, 5, 1] and llm.calls == 1


def test_older_stored_ratings_stay_valid(tmp_path):
    from src.ai.readiness import text_hash
    project, llm = _project(tmp_path), NamedLLM("cydonia")
    old = dict(values=[3, 4, 2], why=["", "", ""], scenes=3, model="gemma",
               text_hash=text_hash(TEXT), v=st.VERSION)                 # no "prompt" key
    st.save(project, None, "c1", old)
    assert st.stored(project, "c1", TEXT)["values"] == [3, 4, 2]
    assert _ensure(llm, project)["values"] == [3, 4, 2] and llm.calls == 0
