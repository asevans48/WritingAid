"""Voice groups without a model (piece V.2)."""

import json
import random

import numpy as np
import pytest

from src.ai import voice_fingerprint as vf
from src.ai import voice_groups as vg
from src.data import voice_groups_store as vgs

M = len(vf.MEASURES)
BASE = np.linspace(5.0, 60.0, M)
SD = np.full(M, 2.0)


def voice(shift: float):
    """A voice: the base fingerprint moved by ``shift`` within-voice
    spreads on every measure (so two voices are about |shift| apart)."""
    return BASE + shift * SD


def rows_for(project, centre, n, rng, start_id, character="", notes=""):
    out = []
    for i in range(n):
        v = centre + rng.normal(0.0, 1.0, M) * SD
        out.append({"id": start_id + i, "project_path": project, "character_name": character,
                    "notes": notes, "status": "ok", "vector": [float(x) for x in v]})
    return out


def data(spec, seed=1, n=40):
    """spec: [(project, shift)] -> rows."""
    rng = np.random.default_rng(seed)
    rows, nid = [], 1
    for project, shift in spec:
        rows += rows_for(project, voice(shift), n, rng, nid)
        nid += n
    return rows


def groups_of(state):
    """Frozen sets of project stems, one per group, for easy comparison."""
    out = set()
    for g in state["groups"].values():
        out.add(frozenset(state["sources"][k]["label"] for k in g["sources"]))
    return out


# ── The measure ──────────────────────────────────────────────────────

def test_separation_scales_with_voice_distance_and_ignores_sample_noise():
    rng = np.random.default_rng(3)
    a = rows_for("/p/a.writerproj", voice(0), 60, rng, 1)
    b = rows_for("/p/b.writerproj", voice(0), 60, rng, 100)
    c = rows_for("/p/c.writerproj", voice(1.0), 60, rng, 200)
    va, vb, vc = ([r["vector"] for r in x] for x in (a, b, c))
    assert vg.separation(va, vb) < vg.SAME
    assert vg.separation(va, vc) > vg.APART
    assert 0.7 < vg.separation(va, vc) < 1.3
    assert vg.separation(va, vc) == vg.separation(vc, va)


def test_a_measure_that_never_varies_does_not_break_the_measure():
    rng = np.random.default_rng(4)
    a = rows_for("/p/a.writerproj", voice(0), 40, rng, 1)
    b = rows_for("/p/b.writerproj", voice(0), 40, rng, 100)
    for r in a + b:
        r["vector"][15] = 0.0                    # second person: always 0
    s = vg.separation([r["vector"] for r in a], [r["vector"] for r in b])
    assert np.isfinite(s)
    state = vg.regroup(a + b)
    assert len(state["groups"]) == 1


# ── The groups ───────────────────────────────────────────────────────

def test_two_clearly_different_voices_give_two_groups():
    state = vg.regroup(data([("/w/Teller.writerproj", 0), ("/w/Blood.writerproj", 1.5)]))
    assert groups_of(state) == {frozenset({"Teller"}), frozenset({"Blood"})}


def test_one_voice_in_two_projects_gives_one_group():
    state = vg.regroup(data([("/w/One.writerproj", 0), ("/w/Two.writerproj", 0.05)]))
    assert groups_of(state) == {frozenset({"One", "Two"})}
    g = next(iter(state["groups"].values()))
    assert g["strength"] in ("very alike", "alike")
    assert g["ratings"] == 80


def test_three_distinct_sources_give_three_groups():
    state = vg.regroup(data([("/w/A.writerproj", 0), ("/w/B.writerproj", 1.2),
                             ("/w/C.writerproj", -1.2)]))
    assert len(state["groups"]) == 3


def test_twelve_projects_in_four_voices_give_four_groups():
    spec = [(f"/w/P{v}{i}.writerproj", shift) for v, shift in enumerate((-2.4, -0.8, 0.8, 2.4))
            for i in range(3)]
    state = vg.regroup(data(spec, n=35))
    assert groups_of(state) == {frozenset({f"P{v}{i}" for i in range(3)}) for v in range(4)}


def test_passages_written_in_two_voices_land_in_two_groups():
    """Real text through V.1's fingerprint: first person, short, present
    tense, against third person, long, past tense."""
    rng = random.Random(5)
    nouns = ["door", "rain", "street", "window", "car", "light", "phone", "dog", "coat", "wall"]
    verbs = ["watch", "wait", "turn", "listen", "breathe", "count", "look", "move"]
    def first(i):
        s = []
        for _ in range(rng.randint(8, 14)):
            s.append(f"I {rng.choice(verbs)} at the {rng.choice(nouns)}"
                     f"{rng.choice(['', ' again', ' and wait', ' for a while'])}.")
            if rng.random() < 0.6:
                s.append(f"It is {rng.choice(['cold', 'late', 'quiet', 'dark', 'wet'])} now.")
        return " ".join(s)
    def third(i):
        s = []
        for _ in range(rng.randint(5, 9)):
            s.append(f"She had walked {rng.choice(['slowly', 'carefully', 'quietly'])} along the "
                     f"{rng.choice(['winding', 'narrow', 'ancient'])} road towards the "
                     f"{rng.choice(nouns)}, considering the letter which had arrived that morning"
                     + rng.choice(["", ", and wondered whether her brother had written it himself",
                                   ", though the old clerk had said nothing of it at all"]) + ".")
        return " ".join(s)
    rows, nid = [], 1
    for project, make in (("/w/Close.writerproj", first), ("/w/Far.writerproj", third)):
        for i in range(35):
            fp = vf.fingerprint(make(i))
            assert fp.ok
            rows.append({"id": nid, "project_path": project, "character_name": "",
                         "notes": "", "status": fp.status, "vector": fp.vector})
            nid += 1
    state = vg.regroup(rows)
    assert groups_of(state) == {frozenset({"Close"}), frozenset({"Far"})}
    close = next(g for g in state["groups"].values()
                 if state["sources"][g["sources"][0]]["label"] == "Close")
    assert "first person" in close["description"] and "present tense" in close["description"]


def test_a_source_between_same_and_apart_stays_where_it_was():
    rng = np.random.default_rng(8)
    a = rows_for("/w/A.writerproj", voice(0), 60, rng, 1)
    near = rows_for("/w/B.writerproj", voice(0.1), 60, rng, 1000)
    first = vg.regroup(a + near)
    assert len(first["groups"]) == 1                    # B started in A's voice
    # B drifts to between SAME and APART
    mid = (vg.SAME + vg.APART) / 2
    drifted = rows_for("/w/B.writerproj", voice(mid), 60, np.random.default_rng(9), 1000)
    s = vg.separation([r["vector"] for r in a], [r["vector"] for r in drifted])
    assert vg.SAME < s < vg.APART
    second = vg.regroup(a + drifted, first)
    third = vg.regroup(a + drifted, second)
    assert groups_of(second) == groups_of(third) == {frozenset({"A", "B"})}
    # ... and built fresh, the two are not put together
    assert len(vg.regroup(a + drifted)["groups"]) == 2
    # A source that drifts clearly apart leaves; the larger side keeps the id
    far = rows_for("/w/B.writerproj", voice(2.0), 30, np.random.default_rng(10), 1000)
    gid = next(iter(first["groups"]))
    fourth = vg.regroup(a + far, second)
    assert len(fourth["groups"]) == 2
    assert fourth["sources"][vg.source_key("/w/A.writerproj")]["group"] == gid
    assert any(e["kind"] == "left" for e in fourth["events"])


def test_a_source_with_two_voices_becomes_two_sources():
    rng = np.random.default_rng(11)
    rows = rows_for("/w/Twins.writerproj", voice(0), 40, rng, 1) + \
        rows_for("/w/Twins.writerproj", voice(4.0), 40, rng, 100)
    rng2 = np.random.default_rng(12)
    rng2.shuffle(rows)
    state = vg.regroup(rows)
    key = vg.source_key("/w/Twins.writerproj")
    assert key in state["splits"]
    labels = {s["label"] for s in state["sources"].values()}
    assert labels == {"Twins: voice A", "Twins: voice B"}
    assert len(state["groups"]) == 2
    # every rating lands with its own voice
    member = vg.membership(rows, state)
    by_group = {}
    for r in rows:
        by_group.setdefault(member[r["id"]], set()).add(r["id"] < 100)
    assert all(len(v) == 1 for v in by_group.values())
    assert vg.regroup(rows, state)["splits"].keys() == state["splits"].keys()


def test_one_voice_source_is_not_split():
    rng = np.random.default_rng(13)
    state = vg.regroup(rows_for("/w/One.writerproj", voice(0), 150, rng, 1))
    assert state["splits"] == {}
    assert len(state["groups"]) == 1


def test_a_source_with_too_few_ratings_is_unsorted():
    rows = data([("/w/Big.writerproj", 0)]) + \
        data([("/w/Small.writerproj", 0)], seed=2, n=vg.MIN_SOURCE_RATINGS - 1)
    for i, r in enumerate(rows):
        r["id"] = i + 1
    state = vg.regroup(rows)
    small = state["sources"][vg.source_key("/w/Small.writerproj")]
    assert small["status"] == "unsorted" and small["group"] is None
    member = vg.membership(rows, state)
    assert {member[r["id"]] for r in rows if r["project_path"] == "/w/Small.writerproj"} == {vg.UNSORTED}
    assert vg.group_for(state, "/w/Small.writerproj") is None
    assert vg.group_for(state, "/w/Big.writerproj") is not None


def test_the_same_passage_rated_twice_counts_once():
    rows = data([("/w/A.writerproj", 0)], n=20)
    dupes = [dict(r, id=r["id"] + 500) for r in rows]
    state = vg.regroup(rows + dupes)
    src = state["sources"][vg.source_key("/w/A.writerproj")]
    assert src["ratings"] == 40 and src["passages"] == 20 and src["status"] == "unsorted"


def test_corpus_rows_and_rows_without_a_project_are_left_out():
    rows = data([("/w/A.writerproj", 0)])
    extra = data([("", 3.0)], seed=3) + data([("/w/Corpus.writerproj", 3.0)], seed=4)
    for i, r in enumerate(extra):
        r["id"] = 5000 + i
        if r["project_path"]:
            r["notes"] = "synthesized=gutenberg"
    state = vg.regroup(rows + extra)
    assert set(state["sources"]) == {vg.source_key("/w/A.writerproj")}
    member = vg.membership(rows + extra, state)
    assert {member[r["id"]] for r in extra} == {vg.UNSORTED}
    assert all(member[r["id"]] != vg.UNSORTED for r in rows)   # done when: every one has a group


def test_never_more_than_eight_automatic_groups():
    spec = [(f"/w/V{i:02d}.writerproj", (i - 4.5) * 1.6) for i in range(10)]
    state = vg.regroup(data(spec, n=32))
    assert len(state["groups"]) == vg.MAX_AUTO_GROUPS
    waiting = [k for k, s in state["sources"].items() if s["status"] == "waiting"]
    assert len(waiting) == 2
    assert any(p["kind"] == "merge" and len(p["groups"]) == 2 for p in state["proposals"])


def test_the_same_data_gives_the_same_groups_twice():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 0.1), ("/w/C.writerproj", 1.5),
                 ("/w/D.writerproj", -1.5)])
    one = vg.regroup(rows, now="t")
    two = vg.regroup(list(reversed(rows)), now="t")
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    again = vg.regroup(rows, one, now="t")
    assert again["groups"] == one["groups"] and again["sources"] == one["sources"]


def test_adding_ratings_does_not_rename_or_shuffle_groups():
    spec = [("/w/A.writerproj", 0), ("/w/B.writerproj", 1.5), ("/w/C.writerproj", -1.5)]
    rows = data(spec)
    first = vg.regroup(rows)
    for gid in first["groups"]:
        first = vg.name_from_model(first, gid, f"Name {gid}")
    more = data(spec, seed=21, n=12)
    for i, r in enumerate(more):
        r["id"] = 10_000 + i
    assert vg.needs_check(rows + more, first)            # grew by more than a fifth
    second = vg.regroup(rows + more, first)
    assert {g: v["sources"] for g, v in second["groups"].items()} == \
        {g: v["sources"] for g, v in first["groups"].items()}
    assert {g: v["name"] for g, v in second["groups"].items()} == \
        {g: f"Name {g}" for g in first["groups"]}


def test_a_newly_ready_source_joins_its_voice_or_starts_a_group():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 1.5)])
    first = vg.regroup(rows)
    ga = first["sources"][vg.source_key("/w/A.writerproj")]["group"]
    new = data([("/w/C.writerproj", 0.05), ("/w/D.writerproj", -1.5)], seed=30)
    for i, r in enumerate(new):
        r["id"] = 20_000 + i
    assert vg.needs_check(rows + new, first)
    second = vg.regroup(rows + new, first)
    assert second["sources"][vg.source_key("/w/C.writerproj")]["group"] == ga
    assert len(second["groups"]) == 3
    assert any(e["kind"] == "new" for e in second["events"][len(first["events"]):])


def test_anchors_survive_every_rebuild():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 0.05), ("/w/C.writerproj", 1.5)])
    state = vg.regroup(rows)
    a_key = vg.source_key("/w/A.writerproj")
    state, mine = vg.create_group(state, "My thriller voice", sources=[a_key])
    for _ in range(3):
        state = vg.regroup(rows, state)
        g = state["groups"][mine]
        assert g["name"] == "My thriller voice" and g["named_by"] == "writer"
        assert a_key in g["sources"]
    # B reads like A but the app does not move it into the writer's group:
    # it proposes it
    b_key = vg.source_key("/w/B.writerproj")
    assert state["sources"][b_key]["group"] != mine
    assert any(p["kind"] in ("join", "merge") and mine in p["groups"] for p in state["proposals"])
    # The writer's group with no ratings left is not removed either
    state = vg.regroup(rows[40:], state)
    assert mine in state["groups"] and a_key in state["pins"]
    # A placed source stays put even far from the group's voice
    c_key = vg.source_key("/w/C.writerproj")
    state = vg.place_source(state, c_key, mine)
    state = vg.regroup(rows, state)
    assert state["sources"][c_key]["group"] == mine and state["sources"][c_key]["pinned"]
    assert state["groups"][mine]["strength"] == "loose"


def test_a_group_seeded_with_example_passages_is_kept():
    state, gid = vg.create_group(vg.empty_state(), "", passages=[
        "I run. I stop. I listen to the rain. It is cold. I wait for the bus. "
        "The street is empty. I count the cars. None come. I go home. I sleep. " * 2])
    state = vg.regroup(data([("/w/A.writerproj", 0)]), state)
    assert gid in state["groups"] and state["groups"][gid]["description"]
    assert gid in vg.needs_name(state)                  # V.3 names it


def test_dismissed_proposals_are_not_made_again():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 0.05)])
    state, mine = vg.create_group(vg.empty_state(), "Mine",
                                  sources=[vg.source_key("/w/A.writerproj")])
    state = vg.regroup(rows, state)
    assert state["proposals"]
    key = state["proposals"][0]["key"]
    state = vg.dismiss_proposal(state, key)
    state = vg.regroup(rows, state)
    assert key not in {p["key"] for p in state["proposals"]}


def test_writer_merge_keeps_their_name_and_model_never_overrides_it():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 1.5)])
    state = vg.regroup(rows)
    ga, gb = sorted(state["groups"])
    state = vg.rename_group(state, gb, "Gothic")
    state, keep = vg.merge_groups(state, [ga, gb])
    state = vg.regroup(rows, state)
    assert len(state["groups"]) == 1
    g = state["groups"][keep]
    assert g["name"] == "Gothic" and g["strength"] == "loose"
    state = vg.name_from_model(state, keep, "Something else")
    assert state["groups"][keep]["name"] == "Gothic"
    assert keep not in vg.needs_name(state)


def test_too_few_ratings_overall_means_no_groups():
    state = vg.regroup(data([("/w/A.writerproj", 0)], n=10))
    assert state["groups"] == {}
    assert not vg.needs_check(data([("/w/A.writerproj", 0)], n=10), vg.empty_state())


def test_a_damaged_state_means_defaults():
    for bad in (None, [], "x", {"groups": "nope", "pins": [1]}, {"groups": {"g1": 5}}):
        s = vg.normalise_state(bad)
        assert s["groups"] == {} and s["pins"] == {}
    vg.regroup(data([("/w/A.writerproj", 0)]), {"groups": {"g1": {"sources": 3}}})


# ── Storage and the check ────────────────────────────────────────────

def _db_with_voices(tmp_path, voices):
    from src.data.rephrase_database import RephraseDatabase
    from src.data import voice_fingerprint_store as vfs
    db = RephraseDatabase(tmp_path / "ratings.db")
    rng = random.Random(1)
    words = ["door", "rain", "street", "window", "car", "light", "phone", "dog", "coat", "wall"]
    for project, make in voices:
        for i in range(32):
            text = make(rng, words)
            db.log("the passage", "the rewrite", source_type="rephrase",
                   surrounding_before=text, project_path=project, rating="good")
    db.log("x", "y", source_type="rephrase", surrounding_before=voices[0][1](rng, words),
           project_path="/w/Gen.writerproj", notes="synthesized=gutenberg")
    vfs.backfill(db)
    return db


def _first(rng, words):
    return " ".join(f"I see the {rng.choice(words)}{rng.choice(['', ' again', ' and stop'])}. "
                    + ("It is cold. " if rng.random() < 0.5 else "")
                    for _ in range(rng.randint(14, 20)))


def _third(rng, words):
    return " ".join(f"He had wandered {rng.choice(['slowly', 'idly', 'warily'])} past the "
                    f"{rng.choice(words)} towards the old harbour, where the boats had lain "
                    f"for years" + rng.choice(["", ", and thought of the coat his father had left",
                                               ", though nobody there remembered his name"]) + "."
                    for _ in range(rng.randint(5, 8)))


def test_the_store_checks_saves_and_reads_back(tmp_path):
    db = _db_with_voices(tmp_path, [("/w/Near.writerproj", _first), ("/w/Far.writerproj", _third)])
    assert not vgs.groups_path().exists()
    state = vgs.run_check(db)
    assert len(state["groups"]) == 2
    on_disk = json.loads(vgs.groups_path().read_text())
    assert on_disk["groups"] == state["groups"]
    member = vgs.membership(db)
    assert len(member) == 65 and list(member.values()).count(vg.UNSORTED) == 1
    assert vgs.group_for("/w/Near.writerproj") is not None
    # not due again: the same file comes back unchanged
    before = vgs.groups_path().read_text()
    vgs.run_check(db)
    assert vgs.groups_path().read_text() == before
    # a writer's change, and undo
    gid = state["sources"][vg.source_key("/w/Near.writerproj")]["group"]
    after, old = vgs.apply(vg.rename_group, gid, "Close")
    assert vgs.load_state()["groups"][gid]["name"] == "Close"
    vgs.restore(old)
    assert vgs.load_state()["groups"][gid]["name"] != "Close"


def test_the_ratings_database_is_not_changed(tmp_path):
    import sqlite3
    db = _db_with_voices(tmp_path, [("/w/Near.writerproj", _first)])
    path = db.db_path
    def dump():
        c = sqlite3.connect(path)
        try:
            return (c.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(),
                    c.execute("SELECT * FROM rephrases ORDER BY id").fetchall(),
                    c.execute("SELECT * FROM voice_fingerprints ORDER BY rephrase_id").fetchall())
        finally:
            c.close()
    before = dump()
    vgs.run_check(db, force=True)
    assert dump() == before


def test_a_damaged_file_means_no_groups(tmp_path):
    vgs.groups_path().write_text("{not json")
    assert vgs.load_state()["groups"] == {}
    from src.data.rephrase_database import RephraseDatabase
    db = RephraseDatabase(tmp_path / "empty.db")
    assert vgs.run_check(db, force=True)["groups"] == {}


def test_the_background_check_runs_off_the_calling_thread(tmp_path):
    db = _db_with_voices(tmp_path, [("/w/Near.writerproj", _first)])
    t = vgs.start_background_check(db)
    assert t is not None and t.daemon
    t.join(30)
    assert not t.is_alive()
    assert len(vgs.load_state()["groups"]) == 1


def test_the_app_starts_the_check_later_not_at_once():
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_group_voices_later")
    assert "singleShot" in ast.unparse(fn) and "start_background_check" in ast.unparse(fn)


def test_a_check_is_due_only_when_something_changed():
    rows = data([("/w/A.writerproj", 0), ("/w/B.writerproj", 1.5)])
    small = data([("/w/S.writerproj", 0)], seed=5, n=5)
    for i, r in enumerate(small):
        r["id"] = 9000 + i
    assert vg.needs_check(rows + small, None)
    state = vg.regroup(rows + small)
    state = vg.place_source(state, vg.source_key("/w/S.writerproj"),
                            state["sources"][vg.source_key("/w/A.writerproj")]["group"])
    state = vg.regroup(rows + small, state)
    assert not vg.needs_check(rows + small, state)       # a placed small source is no reason
    assert vg.needs_check(rows[:39] + rows[40:] + small, state) is True   # a rating removed
