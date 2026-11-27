"""D.5: the six Analyze ▾ analyses run as Critique reports.

No model is ever run: the AI tier uses a fake model with a fixed reply, and
the no-model tier has none.
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

TEXT = ("The storm broke at dusk. Mara ran to the pier, where Dr. Voss waited. "
        "\"Too late,\" he said. She didn't answer. It was very, very cold. "
        "The Ash Wardens' lanterns burned on the hill above the harbour. Nobody slept.")

REPLY = """## Tone
Tense. “The storm broke at dusk” sets it, and “Nobody slept” closes on dread.

## Advice
- Cut the second “very” in “It was very, very cold”."""

KEYS = ["promises", "prose", "characters", "world", "plot", "hints"]


class FakeLLM:
    model = "fake"

    def __init__(self, reply=REPLY):
        self.reply = reply
        self.prompts = []

    def generate_text(self, prompt, system_prompt="", **kw):
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project():
    from src.models.project import Chapter, Character, WriterProject
    from src.models.project import StoryPromise
    p = WriterProject(name="Sample")
    p.characters = [Character(id="m", name="Mara", character_type="protagonist",
                              personality="guarded", backstory="grew up at the harbour")]
    p.story_planning.main_plot = "Mara hunts for the letter."
    p.story_planning.promises = [StoryPromise(id="p1", promise_type="plot",
                                              title="The letter is found",
                                              description="Mara finds the letter.")]
    p.prose_profile.tone = "foreboding"
    from src.models.project import Place
    p.worldbuilding.places = [Place(id="h", name="The Harbour", place_type="town",
                                  description="A cold port.")]
    p.manuscript.chapters.append(Chapter(id="c1", number=1, title="Chapter 1", content=TEXT))
    return p


@pytest.fixture(autouse=True)
def _quiet_boxes(monkeypatch):
    """No main window here, so quiet messages would fall back to a box."""
    from PyQt6.QtWidgets import QMessageBox
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))


@pytest.fixture
def no_real_model(monkeypatch):
    """Whatever the settings say, the Critique gets the model the test gives."""
    import src.ai.task_llm as tl
    import src.ui.grader_widget as gw
    box = {"llm": None}
    monkeypatch.setattr(tl, "build_critique_llm", lambda spec="": box["llm"])
    monkeypatch.setattr(tl, "build_default_llm", lambda: box["llm"])
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: box["llm"])

    class _Cfg:
        def is_ai_disabled(self):
            return False
    monkeypatch.setattr(gw, "get_ai_config", lambda: _Cfg())
    monkeypatch.setattr(gw.CritiqueWorker, "start", lambda self: self.run())   # synchronous
    import src.ai.voice_profile as vp
    monkeypatch.setattr(vp, "ensure", lambda voice, *a, **k: voice)
    return box


class _Editor:
    """What the runner needs of a ChapterEditor."""

    def __init__(self, project):
        from PyQt6.QtWidgets import QPlainTextEdit
        self.chapter = project.manuscript.chapters[0]
        self.manuscript = project.manuscript
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(self.chapter.content)
        self.opened = []

    def save_to_model(self):
        self.chapter.content = self.editor.toPlainText()

    def parent(self):
        return None

    def __getattr__(self, name):                    # the old windows' methods (gone, D.11)
        if name.startswith("_") and name in ("_check_promises", "_analyze_prose",
                                             "_analyze_characters", "_analyze_world",
                                             "_analyze_plot"):
            return lambda: self.opened.append(name)
        raise AttributeError(name)


def _grader(project):
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    g.set_project(project)
    return g


def _run(qapp, project, key):
    from src.ui import analysis_menu
    g = _grader(project)
    ed = _Editor(project)
    assert analysis_menu.run_in(g, ed, key) is True
    qapp.processEvents()
    return g, ed


def _tabs(g):
    return [g.results_tabs.tabText(i) for i in range(g.results_tabs.count())]


def _history(tmp_path):
    return json.loads((tmp_path / "critique_history.json").read_text())


# ── Each item produces a rated, saved report found again ───────────────

@pytest.mark.parametrize("key", KEYS)
def test_each_item_gives_a_saved_report_found_again_in_history(qapp, no_real_model, tmp_path, key):
    from src.ai import analysis_reports as ar
    no_real_model["llm"] = FakeLLM()
    p = _project()
    g, _ = _run(qapp, p, key)
    kinds = ar.ITEMS[key][1]
    main_label = g.REPORT_TAB_LABELS[kinds[0]]
    assert main_label in _tabs(g)
    assert _tabs(g)[g.results_tabs.currentIndex()] == main_label      # opened on its tab
    # Rated: the tab has its rating bar and rating links.
    browser, sections, _report, rating_bar = g._report_tabs[kinds[0]]
    assert rating_bar is not None and "rate-section:" in browser.toHtml()
    assert sections[0].narrative or sections[0].major_issues
    # Kept in history, under its own bucket; new kinds apart from the old.
    data = _history(tmp_path)
    bucket = data[f"analysis:{key}:main:Chapter 1"][-1]["chapters"]["Chapter 1"]
    for kind in kinds:
        where = bucket["analyses"] if ar.is_kept_apart(kind) else bucket["reports"]
        assert kind.value in where
    assert not any(ar.kind_for(k) for k in bucket["reports"])
    # Saved and loaded again.
    g._project_path = str(tmp_path / "p.json")
    g._save_critique_results()
    back = g._deserialize_report(g._metadata_store.get_critique(
        g._project_path, g._store_key("Chapter 1", None))["data"])
    assert {s.report_type for c in back.chapters for s in c.sections} == set(kinds)


def test_the_analysis_keeps_its_prompt(qapp, no_real_model):
    from src.ai import analysis_prompts
    llm = no_real_model["llm"] = FakeLLM()
    p = _project()
    for key, make in (("prose", lambda: analysis_prompts.prose_prompt(p, TEXT)),
                      ("characters", lambda: analysis_prompts.character_prompt(p, p.manuscript.chapters[0], TEXT)),
                      ("plot", lambda: analysis_prompts.plot_prompt(p, p.manuscript.chapters[0], TEXT))):
        llm.prompts.clear()
        _run(qapp, p, key)
        assert make() in llm.prompts, key
    llm.prompts.clear()
    _run(qapp, p, "promises")
    assert any("STORY PROMISES TO CHECK AGAINST" in x and "The letter is found" in x
               for x in llm.prompts)


def test_writing_hints_is_a_real_report_now(qapp, no_real_model):
    llm = no_real_model["llm"] = FakeLLM()
    g, _ = _run(qapp, _project(), "hints")
    assert any("writing hints" in x.lower() for x in llm.prompts)
    from src.ai.analysis_reports import AnalysisKind
    browser = g._report_tabs[AnalysisKind.HINTS][0]
    assert "Nobody slept" in browser.toPlainText()


def test_quotes_link_to_the_chapter(qapp, no_real_model):
    from src.ai.analysis_reports import AnalysisKind
    from src.ui import analysis_menu
    no_real_model["llm"] = FakeLLM()
    g, _ = _run(qapp, _project(), "prose")
    html = g._report_tabs[AnalysisKind.PROSE_FIT][0].toHtml()
    assert "wa-goto:c1" in html
    shown = []
    g.scorecard.issues.show_requested.connect(lambda cid, q, off: shown.append((cid, q)))
    from src.ai.text_links import make_link
    link = make_link("c1", "The storm broke at dusk").split("(", 1)[1].rstrip(")")
    analysis_menu.on_link(g, link)
    assert shown == [("c1", "The storm broke at dusk")]


def test_copy_and_run_again_links_and_no_old_window(qapp, no_real_model, monkeypatch):
    """D.11: the "Show in a window (old)" link and the old windows went; Copy
    and Run again stay, and an "old" link kept from before runs it again."""
    from PyQt6.QtWidgets import QApplication
    from src.ai.analysis_reports import AnalysisKind
    from src.ui import analysis_menu
    no_real_model["llm"] = FakeLLM()
    g, ed = _run(qapp, _project(), "prose")
    html = g._report_tabs[AnalysisKind.PROSE_FIT][0].toHtml()
    for action in ("again", "copy"):
        assert f"analysis:{action}:prose" in html
    assert "analysis:old:" not in html and "Show in a window" not in html
    analysis_menu.on_link(g, "analysis:copy:prose")
    assert "Tense." in QApplication.clipboard().text()
    runs = []
    monkeypatch.setattr(analysis_menu, "run", lambda ce, key: runs.append(key))
    analysis_menu.on_link(g, "analysis:again:prose")
    analysis_menu.on_link(g, "analysis:old:prose")
    assert runs == ["prose", "prose"] and ed.opened == []
    for kind in (AnalysisKind.HINTS, AnalysisKind.PROMISES, AnalysisKind.PROSE_FIT):
        assert "analysis:old:" not in analysis_menu.tab_links(kind)


# ── No model: one line, the scans, never an empty tab ─────────────────

@pytest.mark.parametrize("key", KEYS)
def test_without_a_model_each_item_says_so_and_shows_the_scans(qapp, no_real_model, monkeypatch, key):
    from PyQt6.QtWidgets import QDialog
    from src.ai import analysis_reports as ar
    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: opened.append(self) or 0)
    monkeypatch.setattr(QDialog, "show", lambda self, *a: opened.append(self))
    no_real_model["llm"] = None
    g, _ = _run(qapp, _project(), key)
    assert not opened                                       # no window, empty or not
    kinds = ar.ITEMS[key][1]
    browser, sections, _r, _bar = g._report_tabs[kinds[0]]
    text = browser.toPlainText()
    assert sections[0].summary and len(text.strip()) > 80
    if ar.is_kept_apart(kinds[0]):
        assert sections[0].summary.startswith("No model is set up")
        assert sections[0].summary.count("\n") == 0                # one line
    if key in ("prose", "hints", "promises"):
        s = sections[0]
        assert s.findings or s.metrics                        # the scans
    assert "Overly descriptive" in " ".join(_tabs(g)) or len(_tabs(g)) > 1


# ── Stored data: old files load, older code skips the new kinds ───────

def test_an_old_history_file_loads_gains_a_new_kind_saves_and_reloads(tmp_path):
    from src.ai.analysis_reports import AnalysisKind
    from src.ai.chapter_analysis_agent import (ChapterReport, CritiqueReport, ReportSection,
                                               ReportType, GENRE_PROFILES)
    from src.data import critique_history as h
    old = {"chapter:Chapter 1": [{"timestamp": "2026-11-01T10:00:00", "scope_label": "",
                                   "has_llm": True, "chapters": {"Chapter 1": {
                                       "words": 30, "style": None, "reports": {
                                           "pacing": {"major": ["Drags."], "minor": [],
                                                      "metrics": {"adverb_pct": 2.0}}}}}}]}
    path = tmp_path / "critique_history.json"
    path.write_text(json.dumps(old))
    p = _project()
    assert h.load(p) == old
    report = CritiqueReport(chapters=[ChapterReport("Chapter 1", 0, 30, sections=[
        ReportSection(AnalysisKind.PROMISES, "Chapter 1", major_issues=["Promise broken."]),
        ReportSection(ReportType.PLOT, "Chapter 1", major_issues=["Stalls."])])],
        genre=GENRE_PROFILES["default"])
    report.run_kind, report.scope_id = "analysis:promises", None
    assert h.record(p, report) is None
    data = h.load(p)
    assert data["chapter:Chapter 1"] == old["chapter:Chapter 1"]          # untouched
    ch = data["analysis:promises:main:Chapter 1"][0]["chapters"]["Chapter 1"]
    assert ch["analyses"]["promises"]["major"] == ["Promise broken."]
    assert set(ch["reports"]) == {"plot"}
    # A second run compares with the first, new kinds included.
    report.chapters[0].sections[0].major_issues = []
    progress = h.record(p, report)
    assert progress["chapters"][0]["fixed"] == [("promises", "Promise broken.")]
    assert progress["trend"][-1]["majors"] == 1


def test_older_code_skips_the_new_kinds():
    """What an older app does with these files: it reads chapter ``sections``
    with ReportType(value), and history ``reports``. Neither holds a new kind."""
    from src.ai.analysis_reports import AnalysisKind
    from src.ai.chapter_analysis_agent import (ChapterReport, CritiqueReport, ReportSection,
                                               ReportType, GENRE_PROFILES)
    from src.ai.critique_parts import stored_sections
    from src.data import critique_history as h
    sections = [ReportSection(AnalysisKind.HINTS, "Chapter 1", narrative="Hints."),
                ReportSection(ReportType.STYLE, "Chapter 1", narrative="Style.")]
    stored = stored_sections(sections)
    for s in stored["sections"]:
        ReportType(s["report_type"])                    # an older app's parse: no failure
    assert [s["report_type"] for s in stored["analysis_sections"]] == ["hints"]
    assert "analysis_sections" not in stored_sections(sections[1:])     # as before
    report = CritiqueReport(chapters=[ChapterReport("Chapter 1", 0, 3, sections=sections)],
                            genre=GENRE_PROFILES["default"])
    snap = h.snapshot(report)["chapters"]["Chapter 1"]
    assert set(snap["reports"]) == {"style"} and set(snap["analyses"]) == {"hints"}


def test_a_stored_type_this_app_does_not_know_does_not_fail(qapp):
    from src.ai.chapter_analysis_agent import ReportType
    from src.ai.critique_parts import section_from_dict
    from src.data import critique_history as h
    from src.ui.grader_widget import GraderWidget
    assert section_from_dict({"report_type": "from_the_future"}).report_type == ReportType.STYLE
    assert section_from_dict({"report_type": "prose_fit"}).report_type.value == "prose_fit"
    g = GraderWidget()
    back = g._deserialize_report({"chapters": [{"chapter_title": "C", "sections": [
        {"report_type": "pacing"}], "analysis_sections": [
        {"report_type": "plot_plan", "narrative": "N"}, {"report_type": "from_the_future"}]}]})
    assert [s.report_type.value for s in back.chapters[0].sections] == ["pacing", "plot_plan", "style"]
    g._render_critique_report(back)                         # draws without failing
    run = {"timestamp": "t", "chapters": {"C": {"words": 1, "reports": {"from_the_future": {
        "major": ["x"], "minor": [], "metrics": {}}}, "analyses": {"other_new": {
        "major": [], "minor": [], "metrics": {}}}}}}
    assert h.compare(run, run)["chapters"][0]["majors"] == [1, 1]


def test_a_saved_critique_from_before_loads_as_before(qapp):
    from src.ui.grader_widget import GraderWidget
    g = GraderWidget()
    data = {"schema_version": 2, "genre_key": "default", "chapters": [{
        "chapter_title": "C", "chapter_index": 0, "word_count": 3,
        "sections": [{"report_type": "voice", "narrative": "Voice."}]}]}
    back = g._deserialize_report(data)
    assert set(g._serialize_report(back)["chapters"][0]) == {
        "chapter_title", "chapter_index", "word_count", "sections"}


# ── The menu: the same six entries, now shortcuts ─────────────────────

def test_analyze_menu_entries_run_in_the_critique(qapp, no_real_model, monkeypatch):
    from PyQt6.QtWidgets import QTabWidget, QWidget
    from src.ui.manuscript_editor import ChapterEditor
    no_real_model["llm"] = FakeLLM()
    p = _project()
    mw = QWidget()
    mw.tab_widget = QTabWidget(mw)
    mw.grader_widget = _grader(p)
    mw.manuscript_editor = QWidget()
    mw.tab_widget.addTab(QWidget(), "Write")
    mw.tab_widget.addTab(mw.grader_widget, "Critique")
    ce = ChapterEditor(p.manuscript.chapters[0], project=p, manuscript=p.manuscript, parent=mw)
    menu = ce.analyze_btn.menu()
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels == ["Critique this chapter (all reports)", "Promises && character consistency",
                      "Prose — tone, style && voice", "Characters", "Worldbuilding",
                      "Plot && pacing", "Writing hints", "Check consistency (names, spellings)…"]
    hints = next(a for a in menu.actions() if a.text() == "Writing hints")
    hints.trigger()
    qapp.processEvents()
    assert mw.tab_widget.currentWidget() is mw.grader_widget
    assert "Writing hints" in _tabs(mw.grader_widget)
    ce._request_ai_hints()                       # the old method name: the same report
    qapp.processEvents()
    assert "Writing hints" in _tabs(mw.grader_widget)


def test_without_a_critique_the_entry_says_where_to_run_it(qapp, monkeypatch):
    from src.ui import analysis_menu, notify
    ed = _Editor(_project())
    said = []
    monkeypatch.setattr(notify, "empty", lambda w, title, text: said.append((title, text)))
    monkeypatch.setattr(analysis_menu, "main_window_of", lambda w: None)
    assert analysis_menu.run(ed, "world") is False
    assert ed.opened == []
    assert said and said[0][0] == "Worldbuilding" and "Critique" in said[0][1]


def test_the_old_windows_are_gone(qapp):
    from src.ui import manuscript_editor as me
    for name in ("ProseAnalysisDialog", "PromiseCheckDialog"):
        assert not hasattr(me, name), name
    for name in ("_check_promises", "_analyze_prose", "_analyze_characters", "_analyze_world",
                 "_analyze_plot", "_prose_analysis_ready", "_get_ai_handler"):
        assert not hasattr(me.ChapterEditor, name), name
    from src.ui import analysis_menu
    assert not hasattr(analysis_menu, "OLD_WINDOWS")


def test_the_no_model_line_names_why_a_local_model_would_not_load(monkeypatch):
    """What the old Promise Check window said, now on the report (D.11)."""
    from src.ai import analysis_reports as ar, task_llm
    monkeypatch.setattr(task_llm, "_last_error", "")
    plain = ar.no_model_line("the check", "Nothing else.")
    assert plain == ar.NO_MODEL.format(what="the check", shown="Nothing else.")
    monkeypatch.setattr(task_llm, "_last_error",
                        "Couldn't load the local model 'mlx-community/x': boom")
    line = ar.no_model_line("the check", "Nothing else.")
    assert line.startswith(plain) and line.endswith("'mlx-community/x': boom.")
    monkeypatch.setattr(task_llm, "_last_error", "AI features are turned off in Settings.")
    assert ar.no_model_line("the check", "Nothing else.") == plain


def test_a_project_from_before_the_piece_runs_an_analysis_and_saves_unchanged(qapp, no_real_model):
    """Nothing in the project changes: open an old project, run an analysis
    on its first chapter, save, reopen; every chapter file is byte-for-byte
    what it was, and the analysis went to the critique history only."""
    import shutil
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from test_project_compat import _v1_project_dir
    from src.models.project import WriterProject
    from src.ui import analysis_menu
    no_real_model["llm"] = FakeLLM()
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    p = WriterProject.load_project(str(path))
    ed = _Editor(p)
    if not ed.editor.toPlainText().strip():
        ed.editor.setPlainText(TEXT)                       # the editor only; not saved
    g = _grader(p)
    ed.save_to_model = lambda: None                        # the editor's save is not under test
    assert analysis_menu.run_in(g, ed, "hints")
    qapp.processEvents()
    p.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    assert len(again.manuscript.chapters) == len(p.manuscript.chapters)
    shutil.rmtree(d)
