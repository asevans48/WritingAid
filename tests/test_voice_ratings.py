"""Managing ratings by voice (piece V.5)."""

import random
import shutil
import sqlite3

import pytest

from src.ai import voice_groups as vg
from src.data import voice_groups_store as vgs
from src.data import voice_ratings as vr

WORDS = ["door", "rain", "street", "window", "car", "light", "phone", "dog", "coat", "wall"]


def _first(rng):
    return " ".join(f"I see the {rng.choice(WORDS)}{rng.choice(['', ' again', ' and stop'])}. "
                    + ("It is cold. " if rng.random() < 0.5 else "")
                    for _ in range(rng.randint(14, 20)))


def _third(rng):
    return " ".join(f"He had wandered {rng.choice(['slowly', 'idly', 'warily'])} past the "
                    f"{rng.choice(WORDS)} towards the old harbour, where the boats had lain "
                    f"for years" + rng.choice(["", ", and thought of the coat his father had left",
                                               ", though nobody there remembered his name"]) + "."
                    for _ in range(rng.randint(5, 8)))


@pytest.fixture(scope="module")
def _built(tmp_path_factory):
    from src.data.rephrase_database import RephraseDatabase
    folder = tmp_path_factory.mktemp("voice_ratings")
    db = RephraseDatabase(folder / "ratings.db")
    rng = random.Random(1)
    paths = {name: str(folder / f"{name}.writerproj") for name in ("Near", "Twin", "Far", "Small")}
    for name, make, n in (("Near", _first, 32), ("Twin", _first, 32), ("Far", _third, 32),
                          ("Small", _third, 5)):
        for i in range(n):
            db.log(f"{name} passage {i}", f"{name} rewrite {i}", source_type="rephrase",
                   surrounding_before=make(rng), project_path=paths[name], rating="good")
    db._conn().close()
    db._local.conn = None
    return folder / "ratings.db", paths


@pytest.fixture
def made(_built, tmp_path):
    """A fresh copy of the ratings and an empty groups file, checked once."""
    from src.data.rephrase_database import RephraseDatabase
    src, paths = _built
    shutil.copy(src, tmp_path / "ratings.db")
    db = RephraseDatabase(tmp_path / "ratings.db")
    vgs.run_check(db)
    return db, paths


def key(paths, name):
    return vg.source_key(paths[name])


def group_of(db, paths, name):
    return vr.overview(db)["sources"][key(paths, name)]["group"]


def rows_of(db):
    return [tuple(r) for r in db._conn().execute("SELECT * FROM rephrases ORDER BY id")]


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── What the writer sees ─────────────────────────────────────────────

def test_overview_shows_groups_projects_strength_and_unsorted(made):
    db, paths = made
    o = vr.overview(db)
    assert len(o["groups"]) == 2
    big, single = o["groups"]
    assert sorted(big["projects"]) == ["Near", "Twin"] and big["ratings"] == 64
    assert big["strength"] in ("very alike", "alike")
    assert single["projects"] == ["Far"] and single["strength"] == "one project"
    assert [e["label"] for e in o["unsorted"]] == ["Small"]
    assert o["unsorted"][0]["needs"] == vg.MIN_SOURCE_RATINGS - 5
    assert o["ratings"] == 101
    assert str(vg.MAX_AUTO_GROUPS) in vr.WHY_COUNT


def test_a_narrator_alone_is_one_narrator():
    assert vr.strength_words({}, [{"character_name": "Mara"}]) == "one narrator"
    assert vr.strength_words({}, [{"character_name": ""}]) == "one project"


# ── Done when: found, moved, removed; a moved source stays put ───────

def test_a_moved_source_stays_where_the_writer_put_it_after_a_rebuild(made):
    db, paths = made
    far = group_of(db, paths, "Far")
    after, before = vr.move(db, [key(paths, "Twin")], far)
    assert group_of(db, paths, "Twin") == far
    assert after["pins"][key(paths, "Twin")] == far
    vr.rebuild(db)
    vgs.run_check(db, force=True)
    assert group_of(db, paths, "Twin") == far
    vr.undo(before)
    assert group_of(db, paths, "Twin") == group_of(db, paths, "Near")


def test_an_unsorted_source_can_be_moved_into_a_group(made):
    db, paths = made
    far = group_of(db, paths, "Far")
    vr.move(db, [key(paths, "Small")], far)
    o = vr.overview(db)
    assert o["sources"][key(paths, "Small")]["group"] == far
    assert not o["unsorted"]


def test_a_rating_can_be_found(made):
    db, paths = made
    ids = vr.overview(db)["sources"][key(paths, "Far")]["ids"]
    hits = vr.find(db, "Far rewrite 7", ids)
    assert len(hits) == 1
    assert vr.ratings_for(db, list(hits))[0]["output_text"] == "Far rewrite 7"


def test_removing_asks_first_and_removes_one_row_only(made, qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    view = VoiceGroupsView(db=db)
    view.refresh()
    rid = vr.overview(db)["sources"][key(paths, "Near")]["ids"][3]
    before = rows_of(db)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Cancel))
    assert view.remove_ratings([rid]) == 0 and asked and rows_of(db) == before
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes))
    assert view.remove_ratings([rid]) == 1
    after = rows_of(db)
    assert len(after) == len(before) - 1
    assert [r for r in before if r[0] != rid] == after
    assert vr.overview(db)["sources"][key(paths, "Near")]["ratings"] == 31


def test_change_a_rating_and_take_it_back(made, qapp):
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    view = VoiceGroupsView(db=db)
    view.refresh()
    rid = vr.overview(db)["sources"][key(paths, "Far")]["ids"][0]
    view.change_rating(rid, "poor")
    assert vr.ratings_for(db, [rid])[0]["rating"] == "poor"
    view.undo_last()
    assert vr.ratings_for(db, [rid])[0]["rating"] == "good"


# ── Merge, rename, new group, remove group ───────────────────────────

def test_a_merge_keeps_every_rating_and_undo_splits_them_back(made):
    db, paths = made
    o = vr.overview(db)
    gids = [g["id"] for g in o["groups"]]
    state = o["state"]
    assert vr.merge_is_loose(db, state, gids)          # first and third person
    after, before = vr.merge(db, gids)
    o2 = vr.overview(db)
    assert len(o2["groups"]) == 1
    assert o2["groups"][0]["ratings"] == sum(g["ratings"] for g in o["groups"]) == 96
    assert o2["groups"][0]["strength"] == "loose"
    vr.rebuild(db)
    assert len(vr.overview(db)["groups"]) == 1          # the writer's merge holds
    vr.undo(before)
    assert len(vr.overview(db)["groups"]) == 2


def test_a_loose_merge_asks_first(made, qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui.voice_groups_view import VoiceGroupsView
    db, _paths = made
    view = VoiceGroupsView(db=db)
    view.refresh()
    gids = [g["id"] for g in view._data["groups"]]
    said = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda parent, title, text, *a: said.append(text) or QMessageBox.StandardButton.Cancel))
    view.merge(gids)
    assert said and vr.LOOSE_WARNING in said[0]
    assert len(vr.overview(db)["groups"]) == 2
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes))
    view.merge(gids)
    assert len(vr.overview(db)["groups"]) == 1
    view.undo_last()
    assert len(vr.overview(db)["groups"]) == 2


def test_merging_alike_groups_does_not_ask(made, qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    # Near and Twin in two groups of the writer's, then merged: alike, no question
    _a, _b, g1 = vr.new_group(db, "Mine", [key(paths, "Near")])
    near_twin = group_of(db, paths, "Twin")
    assert near_twin != g1
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: pytest.fail("asked")))
    view = VoiceGroupsView(db=db)
    view.refresh()
    view.merge([g1, near_twin])
    o = vr.overview(db)
    merged = [g for g in o["groups"] if key(paths, "Near") in [s["key"] for s in g["sources"]]][0]
    assert merged["name"] == "Mine"                    # the writer's name is kept
    assert {s["label"] for s in merged["sources"]} == {"Near", "Twin"}


def test_rename_is_kept_through_a_rebuild(made):
    db, paths = made
    gid = group_of(db, paths, "Far")
    vr.rename(db, gid, "Harbour voice")
    vr.rebuild(db)
    g = [g for g in vr.overview(db)["groups"] if g["id"] == gid][0]
    assert g["name"] == "Harbour voice" and g["writer_named"]


def test_new_group_from_a_project_or_from_passages(made):
    db, paths = made
    after, before, gid = vr.new_group(db, "", [key(paths, "Small")])
    assert gid and group_of(db, paths, "Small") == gid
    rng = random.Random(5)
    passages = [_third(rng) for _ in range(3)] + ["Too short."]
    _a, _b, g2 = vr.new_group(db, "Examples", [], passages)
    g = vgs.load_state()["groups"][g2]
    assert len(g["seed_passages"]) == 3 and g["anchor"]
    assert [x for x in vr.overview(db)["groups"] if x["id"] == g2][0]["strength"] == "example passages"


def test_split_passages():
    assert vr.split_passages("one\n---\ntwo\n\n***\n three \n---\n") == ["one", "two", "three"]


def test_removing_a_group_sorts_its_sources_again(made):
    db, paths = made
    _a, before, gid = vr.new_group(db, "Mine", [key(paths, "Far")])
    vr.remove_group(db, gid)
    assert gid not in vgs.load_state()["groups"]
    assert group_of(db, paths, "Far") is not None       # back in an app-made group


# ── Proposals ────────────────────────────────────────────────────────

def test_a_join_proposal_can_be_accepted_or_declined(made):
    db, paths = made
    # the writer's own group holds Near; Twin, same voice, is proposed to join it
    vgs.restore(vg.empty_state())
    _a, _b, gid = vr.new_group(db, "Mine", [key(paths, "Near")])
    props = vr.overview(db)["proposals"]
    join = [p for p in props if p["kind"] == "join"]
    assert join and "Twin" in join[0]["text"] and "Add it there?" in join[0]["text"]
    vr.decline(db, join[0]["proposal"])
    assert not [p for p in vr.overview(db)["proposals"] if p["kind"] == "join"]
    vr.rebuild(db)
    assert not [p for p in vr.overview(db)["proposals"] if p["kind"] == "join"]
    # accepted instead
    vgs.restore(vg.empty_state())
    _a, _b, gid = vr.new_group(db, "Mine", [key(paths, "Near")])
    join = [p for p in vr.overview(db)["proposals"] if p["kind"] == "join"][0]
    vr.accept(db, join["proposal"])
    assert group_of(db, paths, "Twin") == gid


def test_a_source_asked_to_leave_starts_on_its_own():
    state = vg.empty_state()
    state["groups"]["g1"] = {"id": "g1", "anchor": True}
    state["sources"]["/p/a.writerproj::"] = {"group": "g1"}
    state["pins"]["/p/a.writerproj::"] = "g1"
    out = vr.leave_group(state, "/p/a.writerproj::")
    assert "/p/a.writerproj::" not in out["pins"]
    assert out["sources"]["/p/a.writerproj::"]["group"] not in out["groups"]
    assert state["pins"]                                 # the state before is untouched


def test_split_and_join_records():
    state = vg.empty_state()
    state["groups"]["g1"] = {"id": "g1", "anchor": True}
    state["sources"]["k::"] = {"group": "g1"}
    out = vr.split_source(state, "k::", {"A": [0], "B": [1], "scale": [1]})
    assert out["pins"]["k::#A"] == "g1" and out["splits"]["k::"]
    back = vr.join_source(out, "k::")
    assert "k::" not in back["splits"] and back["pins"]["k::"] == "g1"


def test_the_over_eight_line_shows_only_when_the_merge_stays_strong(made):
    db, paths = made
    state = vgs.load_state()
    gids = [g for g in state["groups"]]
    state["proposals"] = [{"key": "merge:x", "kind": "merge", "groups": gids, "sources": [],
                           "why": "more than 8 voices: merging the closest two would make room"}]
    assert vr.proposals(db, state) == []                 # Near/Twin with Far: loose
    near = group_of(db, paths, "Near")
    _a, _b, g1 = vr.new_group(db, "", [key(paths, "Twin")])
    state = vgs.load_state()
    state["proposals"] = [{"key": "merge:y", "kind": "merge", "groups": [near, g1],
                           "sources": [], "why": "more than 8 voices: merging"}]
    lines = vr.proposals(db, state)
    assert len(lines) == 1 and lines[0]["text"].startswith("More than 8 voices")


# ── Keep this project's ratings to itself ────────────────────────────

def test_the_keep_to_itself_switch_is_shown_and_changed_here(made, qapp):
    from src.data import ratings_privacy
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    view = VoiceGroupsView(db=db)
    view.refresh()
    assert not view._data["sources"][key(paths, "Far")]["private"]
    view.set_private(paths["Far"], True)
    assert ratings_privacy.is_private(paths["Far"])
    assert view._data["sources"][key(paths, "Far")]["private"]
    item = view._find_item(("source", key(paths, "Far")))
    assert "🔒" in item.text(0) and "kept to itself" in item.text(2)
    view.undo_last()
    assert not ratings_privacy.is_private(paths["Far"])


# ── The view, the menu and where it lives ────────────────────────────

def test_the_view_lists_groups_sources_and_ratings(made, qapp):
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    view = VoiceGroupsView(db=db)
    view.refresh()
    top = [view.tree.topLevelItem(i) for i in range(view.tree.topLevelItemCount())]
    tags = [t.data(0, 0x0100)[0] for t in top]
    assert tags.count("group") == 2 and tags[-1] == "unsorted"
    src_item = view._find_item(("source", key(paths, "Far")))
    assert src_item.childCount() == 0                    # ratings load when opened
    src_item.setExpanded(True)
    assert src_item.childCount() == 32
    assert "2 voice groups" in view.header.text()
    from PyQt6.QtWidgets import QMenu
    menu = QMenu()
    view._fill_menu(menu, [("source", key(paths, "Far"))])
    texts = [a.text() for a in menu.actions()]
    assert "Move to" in texts and "Keep this project's ratings to itself" in texts
    assert "Rebuild the groups" in texts and "New group…" in texts
    view._fill_menu(menu, [("group", g["id"]) for g in view._data["groups"]])
    assert "Merge 2 groups" in [a.text() for a in menu.actions()]


def test_search_shows_only_the_matching_rating(made, qapp):
    from src.ui.voice_groups_view import VoiceGroupsView
    db, paths = made
    view = VoiceGroupsView(db=db)
    view.refresh("Twin rewrite 12")
    item = view._find_item(("source", key(paths, "Twin")))
    assert item.childCount() == 1 and not item.isHidden()
    assert view._find_item(("source", key(paths, "Far"))).isHidden()


def test_the_browse_rows_dialog_offers_rated_rewrites_by_voice(made, qapp, monkeypatch):
    from src.data import rephrase_database as rd
    from src.ui import voice_groups_view as vgv
    from src.ui.training_tool_window import _CorpusBrowserDialog
    db, paths = made
    monkeypatch.setattr(rd, "DEFAULT_DB_PATH", db.db_path)
    dlg = _CorpusBrowserDialog(db.db_path)
    view = dlg.voice_groups_view
    assert view is not None and view.shared
    i = dlg.source_combo.findData(vgv.VOICE)
    assert i == dlg.source_combo.findData("rephrase") + 1
    dlg.show()
    dlg.source_combo.setCurrentIndex(i)
    assert view.isVisible() and not dlg.table.isVisible()
    assert not dlg.drop_matching_btn.isVisible()
    assert len(view._data["groups"]) == 2
    dlg.source_combo.setCurrentIndex(0)
    assert dlg.table.isVisible() and not view.isVisible() and dlg.drop_matching_btn.isVisible()
    dlg.close()


def test_another_database_shows_no_groups_and_changes_nothing(made, qapp, tmp_path):
    from src.ui.voice_groups_view import VoiceGroupsView
    db, _paths = made
    before = vgs.groups_path().read_text()
    view = VoiceGroupsView(db=db, shared=False)
    view.refresh()
    assert "another database" in view.header.text()
    assert not view.menu_btn.isEnabled()
    assert vgs.groups_path().read_text() == before


def test_managing_groups_never_changes_the_ratings(made):
    db, paths = made
    before = rows_of(db)
    gids = [g["id"] for g in vr.overview(db)["groups"]]
    vr.rename(db, gids[0], "A")
    vr.move(db, [key(paths, "Small")], gids[1])
    vr.merge(db, gids)
    vr.rebuild(db)
    assert rows_of(db) == before


def test_the_new_group_form_needs_a_source_or_a_long_enough_passage(made, qapp):
    from src.ui.voice_groups_view import NewGroupDialog
    db, paths = made
    sources = vr.overview(db)["sources"]
    dlg = NewGroupDialog(sources, [key(paths, "Far")])
    name, keys, passages = dlg.values()
    assert keys == [key(paths, "Far")] and not passages and name == ""
    empty = NewGroupDialog(sources, [])
    empty._ok()
    assert empty.result() == 0 and "Tick a project" in empty.note.text()
    empty.passages.setPlainText(_third(random.Random(2)) + "\n---\nToo short.")
    empty._ok()
    assert "too short" in empty.note.text() and empty.result() == 0
    empty._ok()                                          # OK again: goes on without it
    assert empty.result() == 1 and len(empty.values()[2]) == 1
