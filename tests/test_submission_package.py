"""9.3: the submission package (synopsis, query letter, blurb, readers and
comps) in the Publishing tab. The template tier needs no model; the model
tier is tried only with fake models."""

import json
import os
import threading
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import submission_package as sp
from src.data import safe_store
from src.data import submission_store as store
from src.models.project import (Chapter, Character, CharacterTension, Manuscript, PlotEvent,
                                Theme, WriterProject)

PROSE = ('The storm broke at dusk. Mara ran to the pier, where Voss waited. "Too late," '
         'he said. She did not answer him. The water rose against the posts. ')


@pytest.fixture(autouse=True)
def _no_real_settings(monkeypatch):
    """The writer's contact details come from the app's settings: never read them."""
    import src.data.writer_contact as wc
    from src.ui import notify
    told = []
    monkeypatch.setattr(notify, "_notify", lambda parent, title, text, kind, path: told.append(text))
    monkeypatch.setattr(wc, "load", lambda config=None: {"name": "Ann Writer", "phone": "",
                                                         "email": "ann@example.com",
                                                         "address": ""})
    safe_store._reset_for_tests()


def _project(tmp_path, full=True, genre="gothic"):
    path = tmp_path / "Teller County.writerproj"
    p = WriterProject(name="Teller County", manuscript=Manuscript(title="The Pier"))
    p.project_path = str(path)
    p.prose_profile.genre = genre
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = PROSE * 40
    p.manuscript.chapters.append(ch)
    if full:
        p.prose_profile.tone = "dark, tense"
        p.characters = [Character(id="m", name="Mara Venn", character_type="protagonist",
                                  want="to save her brother", need="Letting go is not betrayal."),
                        Character(id="t", name="Tobin", character_type="antagonist")]
        sp_ = p.story_planning
        sp_.main_plot = "A harbour pilot learns the pier is rigged to burn."
        sp_.freytag_pyramid.events = [
            PlotEvent(id="1", title="Letter", description="Mara finds her brother's letter",
                      stage="exposition"),
            PlotEvent(id="2", title="Debt", description="Tobin calls in the debt",
                      stage="rising_action"),
            PlotEvent(id="3", title="Fire", description="The pier burns", stage="climax"),
            PlotEvent(id="4", title="Dawn", description="Mara rows her brother out",
                      stage="resolution")]
        sp_.tensions = [CharacterTension(id="x", title="Debt", stakes="Her brother hangs")]
        sp_.theme_details = [Theme(id="th", title="The cost of loyalty")]
    return path, p


# ── Without a model: the template is the full tier ───────────────────────

def test_every_document_is_complete_on_an_empty_project(tmp_path):
    _, p = _project(tmp_path, full=False, genre="")
    for kind in sp.DOCS:
        text = sp.template(kind, p)
        assert text.strip() and "[" in text, kind           # gaps say what to add
        assert "None" not in text and "{" not in text, kind


def test_templates_are_filled_from_the_plot_and_characters(tmp_path):
    _, p = _project(tmp_path)
    syn = sp.template("synopsis", p)
    for fact in ("The Pier", "Mara Venn wants to save her brother", "Tobin calls in the debt",
                 "The pier burns", "Mara rows her brother out", "letting go is not betrayal",
                 "the cost of loyalty"):
        assert fact in syn, fact
    assert syn.index("Tobin calls") < syn.index("The pier burns") < syn.index("rows her brother")
    q = sp.template("query", p, chosen_comps=["Dracula — Bram Stoker"])
    assert "Dear [Agent's name]" in q and "THE PIER is a gothic novel" in q
    assert "Dracula by Bram Stoker" in q and "Ann Writer" in q and "ann@example.com" in q
    assert "If Mara Venn fails, her brother hangs." in q
    blurb = sp.template("blurb", p)
    assert "rows her brother out" not in blurb                # a blurb keeps the ending back


def test_story_memory_reaches_the_model_prompt(tmp_path):
    from src.ai import story_memory
    _, p = _project(tmp_path)
    story_memory.add(p, "Tobin never learns the schedule.")
    fake = _Fake("Mara Venn has one night. " * 10)
    sp.draft(fake, "synopsis", p)
    assert "Tobin never learns the schedule" in fake.prompts[0]


def test_where_it_sits_is_information_and_says_what_it_is_measured_against(tmp_path):
    _, p = _project(tmp_path)
    text = sp.template("audience", p)
    assert "Typical for a gothic novel sent to agents" in text
    assert "rule of thumb" in text and "not measured from published books" in text
    assert "knows nothing about sales" in text
    for verdict in ("too short", "will sell", "bestseller"):
        assert verdict not in text.lower()


def test_comp_candidates_come_only_from_the_genre_list(tmp_path):
    from src.data import genres
    _, p = _project(tmp_path)
    cands = sp.comp_candidates(p)
    every = {c for k in genres.all_keys() for c in genres.info_for(k).get("comps", [])}
    assert cands and set(cands) <= every and len(cands) <= sp.MAX_CANDIDATES
    assert cands[0] in genres.info_for("gothic")["comps"]     # the book's genre first
    _, q = _project(tmp_path, genre="")
    assert sp.comp_candidates(q) == []
    assert sp.chosen_comps(["A — B"], "C — D; A — B\nE — F") == ["A — B", "C — D", "E — F"]


# ── Where the drafts are kept, and nothing is lost ───────────────────────

def test_drafts_are_kept_beside_the_project_never_in_it(tmp_path):
    path, p = _project(tmp_path)
    assert store.path_for(p) == tmp_path / "Teller County.submission.json"
    assert "beside the project file" in store.where(p)
    assert not store.path_for(p).exists()                    # reading never creates it
    assert store.text(p, None, "synopsis") == ""
    store.put_draft(p, None, "synopsis", "Draft one.", "template")
    assert store.text(p, None, "synopsis") == "Draft one."
    p.save_project(str(path))
    assert "Draft one" not in path.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("*.md")) or all(
        "Draft one" not in f.read_text(encoding="utf-8") for f in tmp_path.rglob("*.md"))


def test_a_new_draft_never_silently_replaces_an_edit(tmp_path):
    _, p = _project(tmp_path)
    store.put_draft(p, None, "query", "Template text.", "template")
    store.set_text(p, None, "query", "My edited letter.")
    assert store.is_edited(store.document(p, None, "query"))
    got = store.put_draft(p, None, "query", "Model text.", "model", model="fake")
    assert got["kept"]
    doc = store.document(p, None, "query")
    assert doc["text"] == "Model text."
    assert doc["versions"][-1]["text"] == "My edited letter."
    assert doc["versions"][-1]["source"] == "writer"
    back = store.restore(p, None, "query", len(doc["versions"]) - 1)
    assert back == "My edited letter."
    assert "Model text." in [v["text"] for v in store.document(p, None, "query")["versions"]]


def test_each_manuscript_has_its_own_package(tmp_path):
    _, p = _project(tmp_path)
    nov = p.create_subproject("The Pier at Night")
    store.put_draft(p, None, "blurb", "Main blurb.", "template")
    store.put_draft(p, nov.id, "blurb", "Novella blurb.", "template")
    assert store.text(p, None, "blurb") == "Main blurb."
    assert store.text(p, nov.id, "blurb") == "Novella blurb."


def test_unknown_keys_are_kept_and_a_newer_file_is_never_written(tmp_path):
    _, p = _project(tmp_path)
    f = store.path_for(p)
    f.write_text(json.dumps({"format_version": 1, "later": {"x": 1}, "manuscripts": {}}))
    store.put_draft(p, None, "synopsis", "Text.", "template")
    assert json.loads(f.read_text())["later"] == {"x": 1}
    newer = {"format_version": 99, "manuscripts": {"main": {"synopsis": {"text": "Newer."}}}}
    f.write_text(json.dumps(newer))
    assert store.text(p, None, "synopsis") == "Newer."
    assert not store.set_text(p, None, "synopsis", "Mine.")
    assert json.loads(f.read_text()) == newer


def test_an_unreadable_file_is_set_aside_not_saved_over(tmp_path):
    _, p = _project(tmp_path)
    f = store.path_for(p)
    f.write_text("{ not json")
    assert store.text(p, None, "synopsis") == ""
    assert list(tmp_path.glob("Teller County.submission.json.unreadable-*"))


def test_a_project_saved_before_the_piece_opens_and_saves_unchanged(tmp_path, app):
    """Rule 11: open a project saved before 9.3, use the package, save, reopen."""
    path, p = _project(tmp_path)
    p.save_project(str(path))
    def chapter_files():                 # the save's own backup_*.md copies aside
        return {f.relative_to(tmp_path): f.read_bytes() for f in tmp_path.rglob("*.md")
                if not f.name.startswith("backup_")}
    before_chapters = chapter_files()
    again = WriterProject.load_project(str(path))
    from src.ui.agent_manager_widget import AgentManagerWidget
    w = AgentManagerWidget()
    w.load_data(again.agent_contacts)
    w.set_project(again)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    assert store.text(again, None, "synopsis").strip()
    again.save_project(str(path))
    third = WriterProject.load_project(str(path))
    assert [c.content for c in third.manuscript.chapters] == [c.content for c in p.manuscript.chapters]
    assert before_chapters and before_chapters == chapter_files()
    assert "submission" not in json.loads(path.read_text(encoding="utf-8"))
    w.close()


# ── With a model (fakes only) ────────────────────────────────────────────

class _Fake:
    model = "fake-model"

    def __init__(self, reply, local=False):
        self.reply, self.prompts, self.locked = reply, [], []
        self.compact_prompts = local

    def generate_text(self, prompt, system=None, max_tokens=0, temperature=0.0):
        from src.ai.mlx_utils import MLX_GENERATE_LOCK
        self.prompts.append(prompt)
        held = {}

        def probe():                      # can another thread take the lock now?
            got = MLX_GENERATE_LOCK.acquire(blocking=False)
            held["free"] = got
            if got:
                MLX_GENERATE_LOCK.release()
        t = threading.Thread(target=probe)
        t.start()
        t.join()
        self.locked.append(not held["free"])
        return self.reply


def test_the_model_drafts_from_the_facts_with_only_the_chosen_comps(tmp_path):
    _, p = _project(tmp_path)
    fake = _Fake("Mara Venn pilots the harbour. " * 12)
    got = sp.draft(fake, "query", p, chosen_comps=["Carmilla — J. Sheridan Le Fanu"])
    prompt = fake.prompts[0]
    assert "Carmilla — J. Sheridan Le Fanu" in prompt and "ONLY those listed" in prompt
    assert "Dracula" not in prompt                             # an unchosen candidate is not offered
    assert "Mara Venn wants to save her brother" in prompt
    assert got["text"].startswith("Mara Venn") and got["model"] == "fake-model"
    assert got["fit"] is None or 0 <= got["fit"] <= 1


def test_an_on_device_model_runs_under_the_mlx_lock(tmp_path):
    _, p = _project(tmp_path)
    local = _Fake("Back cover words for the book. " * 8, local=True)
    sp.draft(local, "blurb", p)
    assert local.locked == [True]
    cloud = _Fake("Back cover words for the book. " * 8, local=False)
    sp.draft(cloud, "blurb", p)
    assert cloud.locked == [False]


def test_a_failed_or_empty_reply_raises_and_changes_nothing(tmp_path):
    _, p = _project(tmp_path)
    with pytest.raises(RuntimeError):
        sp.draft(_Fake("Error generating text: offline"), "synopsis", p)
    with pytest.raises(RuntimeError):
        sp.draft(_Fake("Too short."), "synopsis", p)


def test_readers_keep_the_apps_facts_not_the_models(tmp_path):
    _, p = _project(tmp_path)
    got = sp.draft(_Fake("Readers who like dark harbours and family debts will love it. " * 3),
                   "audience", p, chosen_comps=["Dracula — Bram Stoker"])
    t = got["text"]
    assert t.startswith("Who it's for") and "- Dracula — Bram Stoker" in t
    assert "Where it sits" in t and "Typical for a gothic novel" in t


# ── The Publishing tab ───────────────────────────────────────────────────

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _settle(app):
    from src.ui import background
    for _ in range(6):
        background.wait_all(10000)
        app.processEvents()


def _tab(tmp_path, app, monkeypatch, model=False):
    from src.ui import submission_package_view as spv
    from src.ui.agent_manager_widget import AgentManagerWidget
    from src.models.project import AgentContact
    monkeypatch.setattr(spv, "ai_available", lambda: model)
    path, p = _project(tmp_path)
    p.agent_contacts = [AgentContact(id="a1", name="Agent One")]
    w = AgentManagerWidget()
    w.load_data(p.agent_contacts)
    w.set_project(p)
    w.resize(1024, 600)
    w.show()
    return w, p


def test_the_package_is_the_first_entry_and_opens_in_place(tmp_path, app, monkeypatch):
    from src.ui.submission_package_view import PackageView
    w, p = _tab(tmp_path, app, monkeypatch)
    assert w.agent_list.item(0).text() == "📦 Submission package"
    assert w.agent_list.count() == 2
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.details_scroll.widget()
    assert isinstance(view, PackageView)
    assert "Mara Venn" in view.editor.toPlainText()             # filled in, no model
    assert view.draft_btn.text() == "✍ Fill in from the story"
    assert "Teller County.submission.json" in view.status.text()
    # Agents still work, the package is kept, and Remove leaves it alone.
    w.agent_list.setCurrentRow(1)
    assert w.current_agent_widget is not None and w.current_agent_widget.agent.name == "Agent One"
    w.agent_list.setCurrentRow(0)
    assert w.details_scroll.widget() is view
    w._remove_agent()
    assert w.agent_list.count() == 2
    assert [a.name for a in w.get_data()] == ["Agent One"]
    w.close()


def test_edits_are_stored_and_a_redraft_keeps_them(tmp_path, app, monkeypatch):
    w, p = _tab(tmp_path, app, monkeypatch)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    view.editor.setPlainText("My own synopsis.")
    view.flush()
    assert store.text(p, None, "synopsis") == "My own synopsis."
    view.draft(use_model=False)
    _settle(app)
    doc = store.document(p, None, "synopsis")
    assert "Mara Venn" in doc["text"]
    assert "My own synopsis." in [v["text"] for v in doc["versions"]]
    assert "earlier text is kept" in view.status.text()
    view._fill_versions()
    restore = [a for a in view.versions_menu.actions() if "My own synopsis" in a.text()]
    restore[0].trigger()
    assert view.editor.toPlainText() == "My own synopsis."
    w.close()


def test_the_model_draft_runs_off_the_gui_thread(tmp_path, app, monkeypatch):
    from src.ai import word_suggest
    w, p = _tab(tmp_path, app, monkeypatch, model=True)
    threads = []

    class Fake(_Fake):
        def generate_text(self, *a, **k):
            threads.append(threading.current_thread())
            return super().generate_text(*a, **k)
    monkeypatch.setattr(word_suggest, "get_llm", lambda: Fake("Mara Venn sails at dusk. " * 10))
    w.agent_list.setCurrentRow(0)
    _settle(app)                                               # the template fills it first
    view = w.package_view
    assert view.draft_btn.text() == "✍ Draft in my voice"
    view.doc_pick.setCurrentIndex(view.doc_pick.findData("blurb"))
    _settle(app)
    view.draft()
    _settle(app)
    assert threads and threading.main_thread() not in threads
    doc = store.document(p, None, "blurb")
    assert doc["source"] == "model" and doc["text"].startswith("Mara Venn sails")
    assert doc["versions"]                                     # the template kept
    assert "drafted by fake-model" in view.status.text()
    w.close()


def test_a_late_draft_lands_in_the_document_it_was_asked_for(tmp_path, app, monkeypatch):
    from src.ai import word_suggest
    w, p = _tab(tmp_path, app, monkeypatch, model=True)
    monkeypatch.setattr(word_suggest, "get_llm", lambda: _Fake("A synopsis by the model. " * 10))
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    view.draft()                                               # synopsis, then move away at once
    view.doc_pick.setCurrentIndex(view.doc_pick.findData("query"))
    _settle(app)
    assert store.text(p, None, "synopsis").startswith("A synopsis by the model")
    assert view.kind == "query" and "Dear [Agent's name]" in view.editor.toPlainText()
    w.close()


def test_a_model_failure_leaves_the_text_and_says_so(tmp_path, app, monkeypatch):
    from src.ai import word_suggest
    w, p = _tab(tmp_path, app, monkeypatch, model=True)
    monkeypatch.setattr(word_suggest, "get_llm", lambda: None)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    before = view.editor.toPlainText()
    view.draft()
    _settle(app)
    assert view.editor.toPlainText() == before
    assert "unchanged" in view.status.text()
    w.close()


def test_comps_are_ticked_and_saved(tmp_path, app, monkeypatch):
    from PyQt6.QtCore import Qt
    w, p = _tab(tmp_path, app, monkeypatch)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    view.doc_pick.setCurrentIndex(view.doc_pick.findData("audience"))
    _settle(app)
    assert view.comps_box.isVisible() and view.comp_list.count() > 0
    first = view.comp_list.item(0)
    first.setCheckState(Qt.CheckState.Checked)
    view.own_comps.setText("The Night Pier — A. Writer")
    assert store.comps(p, None) == {"chosen": [first.text()], "own": "The Night Pier — A. Writer"}
    view.draft(use_model=False)
    _settle(app)
    text = view.editor.toPlainText()
    assert f"- {first.text()}" in text and "- The Night Pier — A. Writer" in text
    w.close()


def test_one_document_and_the_whole_package_export(tmp_path, app, monkeypatch):
    from docx import Document
    w, p = _tab(tmp_path, app, monkeypatch)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    for kind in ("query", "audience", "blurb"):
        view.doc_pick.setCurrentIndex(view.doc_pick.findData(kind))
        _settle(app)
    one = tmp_path / "out" / "blurb.docx"
    one.parent.mkdir()
    assert view.export(everything=False, path=str(one), fmt="docx")
    paras = [x.text for x in Document(str(one)).paragraphs]
    assert "Blurb" in paras and not any(x == "Synopsis" for x in paras)
    whole = tmp_path / "out" / "package.txt"
    assert view.export(everything=True, path=str(whole), fmt="txt")
    text = whole.read_text(encoding="utf-8")
    for label in ("Synopsis", "Query letter", "Blurb", "Readers and comps", "The Pier"):
        assert label in text
    w.close()
