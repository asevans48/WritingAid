"""New world elements and characters from the Critique: links, pop-up, saving."""

import os
import types
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import canon_from_critique as cc
from src.models.project import Chapter, Manuscript, WriterProject

TEXT = ("They met at Thessaly Wharf before dawn. The smugglers of Thessaly Wharf trade "
        "after dark, under lamps of whale oil.\n\n"
        "\"Keep your voice down,\" Brannoc said, rubbing the scar on his jaw.\n\n"
        "Brannoc had sailed with the Grey Fleet for ten years.\n")


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _ai_on(monkeypatch):
    import src.ui.canon_add_dialog as cad
    monkeypatch.setattr(cad, "_ai_available", lambda: True)


def _project(tmp_path):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = TEXT
    p.manuscript.chapters.append(ch)
    return p


def test_report_lines_are_read():
    a = cc.parse_item("Thessaly Wharf — Place — Brine-soaked market quarter by the harbor")
    assert a == {"name": "Thessaly Wharf", "kind": "place",
                 "description": "Brine-soaked market quarter by the harbor", "example": ""}
    b = cc.parse_item('Brannoc (5×) — e.g. "Keep your voice down,"')
    assert b["name"] == "Brannoc" and b["example"] == "Keep your voice down,"
    assert cc.parse_item("Grey Fleet — Organization — a navy")["kind"] == "faction"


def test_model_reply_is_read():
    reply = ("KIND: Place\nDESCRIPTION: A market quarter by the harbor\nwhere smugglers trade.\n"
             "SIGNIFICANCE: <importance to the story>\nNOTES: none\n")
    out = cc.parse_reply("place", reply)
    assert out == {"kind": "place",
                   "description": "A market quarter by the harbor where smugglers trade."}
    ch = cc.parse_reply("character", "ROLE: Major character\n**PERSONALITY:** Wary.\n")
    assert ch == {"character_type": "major", "personality": "Wary."}


def test_passages_find_the_name(tmp_path):
    found = cc.passages(_project(tmp_path), "Brannoc")
    assert len(found) == 2 and "scar on his jaw" in found[0]


def test_critique_lists_get_add_links(qapp):
    from src.ai.chapter_analysis_agent import CritiqueReport, ChapterReport, ReportSection, \
        ReportType, resolve_genre_profile
    from src.ui.grader_widget import GraderWidget
    sec_w = ReportSection(ReportType.WORLDBUILDING, "One")
    sec_w.extra_lists = {"New elements (not in worldbuilding)": ["Thessaly Wharf — Place — x"],
                         "Recommendations": ["Do a thing"]}
    sec_c = ReportSection(ReportType.CHARACTER, "One")
    sec_c.extra_lists = {"Speakers with no character record": ['Brannoc (1×) — e.g. "Hi"']}
    report = CritiqueReport([ChapterReport("One", 0, 50, [sec_w, sec_c])],
                            resolve_genre_profile("literary"))
    report.scope_label = ""
    g = GraderWidget()
    world = g._format_report_tab_html(ReportType.WORLDBUILDING, [sec_w], report)
    chars = g._format_report_tab_html(ReportType.CHARACTER, [sec_c], report)
    assert world.count("addcanon:") == 1 and "Add or connect" in world
    assert chars.count("addcanon:") == 1 and "Add as a character" in chars


def _wait(qapp, dlg):
    from src.ui import background
    for _ in range(100):
        background.wait_all(5000)
        qapp.processEvents()
        if dlg._task is None:
            return


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def generate_text(self, prompt, system="", **kw):
        self.prompts.append(prompt)
        return self.reply


def test_popup_starts_from_the_report_and_fills_with_ai(qapp, tmp_path):
    from src.ui.canon_add_dialog import CanonAddDialog
    p = _project(tmp_path)
    llm = FakeLLM("KIND: Place\nDESCRIPTION: A smugglers' quarter on the harbor.\n"
                  "SIGNIFICANCE: Where the heist is planned.\nNOTES: Lit by whale-oil lamps.")
    dlg = CanonAddDialog(p, "world", "Thessaly Wharf — Place — Brine-soaked market",
                         llm_factory=lambda task: llm)
    assert dlg.name_edit.text() == "Thessaly Wharf" and dlg.kind() == "place"
    assert dlg._text(dlg.fields["description"]) == "Brine-soaked market"
    dlg._set(dlg.fields["notes"], "My own note.")              # the writer typed this
    dlg.fill_with_ai()
    _wait(qapp, dlg)
    assert "Thessaly Wharf" in llm.prompts[0] and "whale oil" in llm.prompts[0]   # the passages
    d = dlg.data()
    assert d["description"] == "A smugglers' quarter on the harbor."   # replaced the report's hint
    assert d["significance"] == "Where the heist is planned."
    assert d["notes"] == "My own note."                                  # never overwritten
    assert "Drafted" in dlg.status.text()


def test_ai_can_set_the_kind_unless_the_writer_chose(qapp, tmp_path):
    from src.ui.canon_add_dialog import CanonAddDialog
    p = _project(tmp_path)
    llm = FakeLLM("KIND: Faction\nDESCRIPTION: A navy.\nIDEOLOGY: Order at sea.")
    dlg = CanonAddDialog(p, "world", "Grey Fleet (2×) — e.g. \"…\"", llm_factory=lambda t: llm)
    dlg.fill_with_ai()
    _wait(qapp, dlg)
    assert dlg.kind() == "faction" and dlg.data()["ideology"] == "Order at sea."


def test_without_a_model_it_is_a_form(qapp, tmp_path, monkeypatch):
    import src.ui.canon_add_dialog as cad
    monkeypatch.setattr(cad, "_ai_available", lambda: False)
    dlg = cad.CanonAddDialog(_project(tmp_path), "character", 'Brannoc (2×) — e.g. "Hi"')
    assert not dlg.ai_btn.isEnabled()
    assert "scar on his jaw" in dlg.passages.toPlainText()
    assert dlg.data() == {"name": "Brannoc", "notes": "In the text: “Hi”",
                          "character_type": "minor"}


def _main_window_like(project):
    """The real MainWindow creators, bound to a stand-in window."""
    from src.ui.main_window import MainWindow
    shown = []
    fake = types.SimpleNamespace(current_project=project, _on_content_changed=lambda: None,
                                 _refresh_project_widgets=lambda: shown.append("refresh"),
                                 statusBar=lambda: types.SimpleNamespace(
                                     showMessage=lambda m, t=0: shown.append(m)))
    for name in dir(MainWindow):
        if name.startswith("_create_") and name.endswith("_from_json") or name in (
                "_create_from_plot_ai_suggestion", "_find_similar_existing",
                "_update_existing_element"):
            setattr(fake, name, types.MethodType(getattr(MainWindow, name), fake))
    return fake, shown


def test_saving_uses_the_apps_creators(qapp, tmp_path):
    from src.ui.canon_add_dialog import add_from_critique
    p = _project(tmp_path)
    mw, shown = _main_window_like(p)
    assert add_from_critique(mw, "character", {
        "name": "Brannoc", "character_type": "major", "personality": "Wary.",
        "speaking_style": "Low and clipped.", "motivations": "Clear his name."})
    c = cc.find_record(p, "character", "Brannoc")
    assert c.character_type == "major" and c.personality == "Wary."
    assert c.speaking_style == "Low and clipped." and c.motivations == "Clear his name."
    assert "refresh" in shown and any("Added “Brannoc” to Characters" in m for m in shown
                                       if isinstance(m, str))
    for kind in ("place", "faction", "technology", "myth", "historical_event", "fauna"):
        assert add_from_critique(mw, kind, {"name": f"New {kind}", "description": "d"})
        assert cc.find_record(p, kind, f"New {kind}") is not None


def test_a_similar_record_is_filled_not_duplicated(qapp, tmp_path):
    from src.models.project import Character
    from src.ui.canon_add_dialog import add_from_critique
    p = _project(tmp_path)
    p.characters.append(Character(id="b", name="Brannoc", character_type="minor",
                                  personality="Kept by the writer."))
    mw, _ = _main_window_like(p)
    add_from_critique(mw, "character", {"name": "Brannoc", "personality": "AI text",
                                        "backstory": "Ten years with the Grey Fleet."})
    assert len(p.characters) == 1
    assert p.characters[0].personality == "Kept by the writer."
    assert p.characters[0].backstory == "Ten years with the Grey Fleet."



# ── Connecting a term to something already in the World ─────────────────

def _world(tmp_path):
    from src.models.worldbuilding_objects import Place, PlaceType, Faction, FactionType
    p = _project(tmp_path)
    p.worldbuilding.places.append(Place(id="p1", name="Port Thessaly", place_type=PlaceType.OTHER,
                                        description="A harbor city."))
    p.worldbuilding.factions.append(Faction(id="f1", name="Grey Fleet",
                                            faction_type=list(FactionType)[0]))
    p.worldbuilding.custom_encyclopedia.append({"title": "Whale oil", "category": "Custom",
                                                "summary": "Lamp fuel."})
    return p


def test_likely_targets_come_first(tmp_path):
    p = _world(tmp_path)
    ranked = cc.rank_targets(p, "Thessaly Wharf", cc.passages(p, "Thessaly Wharf"))
    names = [t["name"] for _s, t in ranked]
    assert names[0] == "Port Thessaly"                      # shares a word
    assert "Whale oil" in names and "Grey Fleet" in names   # terms and elements both offered


def test_connecting_a_term_from_the_popup(qapp, tmp_path):
    from src.ui.canon_add_dialog import CanonAddDialog
    p = _world(tmp_path)
    dlg = CanonAddDialog(p, "world", "Thessaly Wharf — Place — Brine-soaked market",
                         llm_factory=lambda t: None)
    assert dlg.connecting() and dlg.add_btn.text() == "Connect"     # a likely match: connect
    assert dlg.target()["name"] == "Port Thessaly"
    dlg.relation_combo.setCurrentIndex(dlg.relation_combo.findData("part"))
    entry = dlg.data()
    assert dlg.kind() == "term"
    assert entry["title"] == "Thessaly Wharf" and entry["refers_to"] == "Port Thessaly"
    assert entry["relation"] == "part" and entry["summary"].startswith("Part of Port Thessaly")
    assert all(isinstance(v, str) for v in entry.values())          # the project file's format
    dlg.mode_new.setChecked(True)                                    # or a new element after all
    assert dlg.kind() == "place" and dlg.add_btn.text() == "Add to World"


def test_ai_suggests_the_connection(qapp, tmp_path):
    from src.ui.canon_add_dialog import CanonAddDialog
    p = _world(tmp_path)
    llm = FakeLLM("TARGET: Grey Fleet\nRELATION: belongs\nDEFINITION: The fleet's anchorage.")
    dlg = CanonAddDialog(p, "world", "Thessaly Wharf — Place — x", llm_factory=lambda t: llm)
    dlg.fill_with_ai()
    _wait(qapp, dlg)
    assert "Port Thessaly" in llm.prompts[0] and "Grey Fleet" in llm.prompts[0]
    assert dlg.target()["name"] == "Grey Fleet"
    assert dlg.relation_combo.currentData() == "belongs"
    assert dlg.definition_edit.toPlainText() == "The fleet's anchorage."


def test_a_connected_term_counts_as_its_element(tmp_path):
    from src.ai.canon_index import collect_world_entities, find_mentions, world_name_variants
    p = _world(tmp_path)
    target = {"name": "Port Thessaly", "category": "Place"}
    assert cc.add_term(p, cc.term_entry("Thessaly Wharf", target, "part", "Its market.")) == "added"
    entities = collect_world_entities(p.worldbuilding)
    port = next(e for e in entities if e.name == "Port Thessaly")
    assert "Thessaly Wharf" in port.aliases
    assert any(e.name == "Thessaly Wharf" and e.category == "Term" for e in entities)
    assert "Port Thessaly" in find_mentions(TEXT, world_name_variants(entities))
    # The same term again fills only what's empty.
    assert cc.add_term(p, cc.term_entry("Thessaly Wharf", target, "alias", "Other.")) == ""
    assert len([e for e in p.worldbuilding.custom_encyclopedia
                if e.get("title") == "Thessaly Wharf"]) == 1


def test_saving_a_term_shows_in_the_world_tab_and_saves(qapp, tmp_path):
    from src.ui.canon_add_dialog import add_from_critique
    from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
    p = _world(tmp_path)
    mw, shown = _main_window_like(p)
    entry = cc.term_entry("Thessaly Wharf", {"name": "Port Thessaly", "category": "Place"},
                          "part")
    assert add_from_critique(mw, "term", entry)
    assert any("Connected “Thessaly Wharf” to Port Thessaly" in m for m in shown
               if isinstance(m, str))
    w = ComprehensiveWorldBuildingWidget()
    w.load_data(p.worldbuilding)
    titles = [e.get("title") for e in w.encyclopedia_widget.get_custom_entries()]
    assert "Thessaly Wharf" in titles
    saved = w.get_data()                                   # the World tab saves with it
    assert any(e.get("refers_to") == "Port Thessaly" for e in saved.custom_encyclopedia)


def test_world_tab_entries_no_longer_break_saving(qapp):
    """An Encyclopedia entry made in the World tab (with tags) used to make
    the World fail to save."""
    from src.models.project import WorldBuilding
    from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
    w = ComprehensiveWorldBuildingWidget()
    w.load_data(WorldBuilding())
    w.encyclopedia_widget._custom_entries.append(
        {"title": "Grey Tide", "category": "Custom", "summary": "s", "tags": ["sea", "storm"],
         "is_custom": True})
    saved = w.get_data()
    assert saved.custom_encyclopedia[0]["tags"] == "sea, storm"
    again = ComprehensiveWorldBuildingWidget()
    again.load_data(saved)
    assert again.encyclopedia_widget._custom_entries[0]["tags"] == ["sea", "storm"]


# ── Another name for a character ─────────────────────────────────────────

NICK_TEXT = ("\"Keep your voice down,\" Bran said. Brannoc never raised his.\n\n"
             "\"Move,\" said Bran, and the crew moved.\n")


def _with_brannoc(tmp_path, notes=""):
    from src.models.project import Character
    p = _project(tmp_path)
    p.manuscript.chapters[0].content = NICK_TEXT
    p.characters.append(Character(id="b", name="Brannoc", character_type="major", notes=notes))
    return p


def test_nicknames_come_from_the_notes_line(tmp_path):
    from src.ai.canon_index import character_aliases, character_name_variants, find_mentions
    p = _with_brannoc(tmp_path, "Gruff.\nAlso called: Bran, The Captain.")
    c = p.characters[0]
    assert character_aliases(c) == ["Bran", "The Captain"]
    assert "Bran" in character_name_variants([c])["Brannoc"]
    assert find_mentions("Bran said nothing.", character_name_variants([c]))


def test_add_nickname_writes_one_line(tmp_path):
    p = _with_brannoc(tmp_path, "Gruff.")
    assert cc.add_nickname(p, "Brannoc", "Bran") == "added"
    assert p.characters[0].notes == "Gruff.\n\nAlso called: Bran"
    assert cc.add_nickname(p, "Brannoc", "The Captain") == "added"
    assert p.characters[0].notes.endswith("Also called: Bran, The Captain")
    assert cc.add_nickname(p, "Brannoc", "bran") == ""                 # already there
    assert cc.add_nickname(p, "Nobody", "X") == "missing"


def test_popup_offers_another_name_for_a_character(qapp, tmp_path):
    from src.ui.canon_add_dialog import CanonAddDialog
    p = _with_brannoc(tmp_path)
    llm = FakeLLM("TARGET: Brannoc\nRELATION: alias\nDEFINITION: x")
    dlg = CanonAddDialog(p, "character", 'Bran (2×) — e.g. "Move,"', llm_factory=lambda t: llm)
    assert dlg.mode_connect.isVisible() or not dlg.isVisible()
    assert dlg.connecting() and dlg.kind() == "nickname"            # "Bran" is in "Brannoc"
    assert dlg.target()["name"] == "Brannoc"
    assert dlg.data() == {"nickname": "Bran", "character": "Brannoc"}
    assert not dlg.relation_combo.isVisibleTo(dlg)                  # just "another name"
    dlg.fill_with_ai()
    _wait(qapp, dlg)
    assert "which recorded character it names" in llm.prompts[0]
    dlg.mode_new.setChecked(True)
    assert dlg.kind() == "character" and dlg.add_btn.text() == "Add character"


def test_saving_a_nickname_and_the_report_knows_it(qapp, tmp_path):
    from src.ai.chapter_analysis_agent import CharacterAnalyzer, resolve_genre_profile
    from src.ui.canon_add_dialog import add_from_critique
    p = _with_brannoc(tmp_path)

    def speakers():
        a = CharacterAnalyzer(project=p, manuscript=p.manuscript)
        sec = a.run(NICK_TEXT, "One", 0, resolve_genre_profile("literary"), "", "", None, None)
        return " ".join(sec.extra_lists.get("Speakers with no character record", []))
    assert "Bran" in speakers()
    mw, shown = _main_window_like(p)
    assert add_from_critique(mw, "nickname", {"nickname": "Bran", "character": "Brannoc"})
    assert "Also called: Bran" in p.characters[0].notes
    assert any("another name for Brannoc" in m for m in shown if isinstance(m, str))
    assert "Bran" not in speakers()


def test_spell_checker_learns_nicknames(tmp_path):
    from src.utils.editor_flags import project_vocabulary
    p = _with_brannoc(tmp_path, "Also called: Branno")
    words, names = project_vocabulary(p)
    assert "Branno" in words and "Branno" in names
