"""A model names and refines the voice groups (piece V.3). Fake models only."""

import random
import shutil
import threading

import pytest

from src.ai import voice_groups as vg
from src.ai import voice_naming as vn
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
    folder = tmp_path_factory.mktemp("voice_naming")
    db = RephraseDatabase(folder / "ratings.db")
    rng = random.Random(1)
    paths = {name: str(folder / f"{name}.writerproj") for name in ("Near", "Twin", "Far")}
    for name, make, n in (("Near", _first, 32), ("Twin", _first, 32), ("Far", _third, 32)):
        for i in range(n):
            db.log(f"{name} passage {i}", f"{name} rewrite {i}", source_type="rephrase",
                   surrounding_before=make(rng), project_path=paths[name], rating="good")
    db._conn().close()
    db._local.conn = None
    return folder / "ratings.db", paths


@pytest.fixture
def made(_built, tmp_path):
    from src.data.rephrase_database import RephraseDatabase
    src, paths = _built
    shutil.copy(src, tmp_path / "ratings.db")
    db = RephraseDatabase(tmp_path / "ratings.db")
    vgs.run_check(db)
    return db, paths


class FakeLLM:
    """Fixed replies, one per call (the last repeats); records prompts."""

    def __init__(self, *replies, local=False, fail=False, during=None):
        self.replies = list(replies) or ["NAME: Plain voice\nDESCRIPTION: Plain."]
        self.prompts = []
        self.compact_prompts = local
        self.fail = fail
        self.during = during

    def generate_text(self, prompt, system_prompt=None, max_tokens=0, temperature=0.7, **kw):
        self.prompts.append(prompt)
        if self.during:
            self.during()
        if self.fail:
            raise RuntimeError("model fell over")
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def groups_file():
    return vgs.groups_path().read_bytes()


def gid_of(db, paths, name):
    return vr.overview(db)["sources"][vg.source_key(paths[name])]["group"]


# ── Done when: groups have names ─────────────────────────────────────

def test_a_readable_reply_names_each_new_group(made):
    db, paths = made
    todo = vg.needs_name(vgs.load_state())
    assert len(todo) == 2
    llm = FakeLLM("NAME: **Clipped present-tense narrator**\nDESCRIPTION: Short first-person "
                  "sentences that stop and look",
                  "NAME: “Drifting harbour past”\nDESCRIPTION: Long third-person sentences.")
    got = vn.name_groups(db, llm)
    assert sorted(got["named"]) == sorted(todo) and not got["failed"]
    state = vgs.load_state()
    names = {g["name"] for g in state["groups"].values()}
    assert names == {"Clipped present-tense narrator", "Drifting harbour past"}
    assert all(g["named_by"] == "model" for g in state["groups"].values())
    assert vg.needs_name(state) == []
    # The samples are the group's own rated passages.
    near = gid_of(db, paths, "Near")
    prompt = llm.prompts[sorted(todo).index(near)]
    assert "Near passage" in prompt or "Twin passage" in prompt
    assert "Far passage" not in prompt
    # V.5 shows the name with the model's line, and the measures in the tooltip.
    g = next(x for x in vr.overview(db)["groups"] if x["id"] == near)
    assert g["named"] and g["description"].endswith(".") and g["measures"]


def test_a_second_run_asks_nothing_new(made):
    db, _ = made
    vn.name_groups(db, FakeLLM("NAME: One\nDESCRIPTION: A.", "NAME: Two\nDESCRIPTION: B."))
    llm = FakeLLM("NAME: Three\nDESCRIPTION: C.")
    assert vn.name_groups(db, llm)["named"] == [] and llm.prompts == []


# ── Done when: a failed or unreadable reply changes nothing ──────────

@pytest.mark.parametrize("llm", [
    FakeLLM("I think this voice is lovely and wistful."),
    FakeLLM("NAME: {name}\nDESCRIPTION: {description}"),
    FakeLLM("NAME: a name that is far too long to be a short human name at all"),
    FakeLLM(""),
    FakeLLM(None),
    FakeLLM(fail=True),
])
def test_an_unreadable_or_failed_reply_changes_nothing(made, llm):
    db, _ = made
    before = groups_file()
    got = vn.name_groups(db, llm)
    assert got["named"] == [] and len(got["failed"]) == 2
    assert groups_file() == before


def test_without_a_model_the_plain_words_stand(made, monkeypatch):
    db, _ = made
    monkeypatch.setattr(vn, "model_if_ready", lambda: None)
    before = groups_file()
    got = vn.name_groups(db)
    assert got["model"] is False and groups_file() == before
    assert all(g["name"].startswith(("Short", "Long")) or not g["named"]
               for g in vr.overview(db)["groups"])


# ── Names the writer gave are never changed ──────────────────────────

def test_a_writer_name_is_never_replaced(made):
    db, paths = made
    near = gid_of(db, paths, "Near")
    vr.rename(db, near, "Teller")
    llm = FakeLLM("NAME: Model name\nDESCRIPTION: X.")
    vn.name_groups(db, llm)
    state = vgs.load_state()
    assert state["groups"][near]["name"] == "Teller"
    assert state["groups"][near]["named_by"] == "writer"
    assert len(llm.prompts) == 1                    # only the other group was asked about


def test_a_writer_rename_while_the_model_thinks_wins(made):
    db, paths = made
    near = gid_of(db, paths, "Near")
    llm = FakeLLM("NAME: Model name\nDESCRIPTION: X.",
                  during=lambda: vgs.apply(vg.rename_group, near, "Mine", db=db))
    vn.name_groups(db, llm)
    assert vgs.load_state()["groups"][near]["name"] == "Mine"


def test_a_merge_keeps_the_writer_name_and_an_unnamed_merge_is_named_afresh(made):
    db, paths = made
    near, far = gid_of(db, paths, "Near"), gid_of(db, paths, "Far")
    vn.name_groups(db, FakeLLM("NAME: Alpha\nDESCRIPTION: A.", "NAME: Beta\nDESCRIPTION: B."))
    after, before = vr.merge(db, [near, far])
    keep = next(iter(after["groups"]))
    assert vg.needs_name(vgs.load_state()) == [keep]
    vn.name_groups(db, FakeLLM("NAME: Gamma\nDESCRIPTION: Both."))
    assert vgs.load_state()["groups"][keep]["name"] == "Gamma"
    vr.undo(before)
    vr.rename(db, far, "Harbour")
    after, _ = vr.merge(db, [near, far])
    keep = next(iter(after["groups"]))
    assert after["groups"][keep]["name"] == "Harbour"
    assert vg.needs_name(vgs.load_state()) == []


def test_the_writers_own_unnamed_group_is_named(made):
    db, paths = made
    after, before, gid = vr.new_group(db, "", [vg.source_key(paths["Twin"])])
    assert gid in vg.needs_name(vgs.load_state())
    vn.name_groups(db, FakeLLM("NAME: One\nDESCRIPTION: A.", "NAME: Two\nDESCRIPTION: B.",
                               "NAME: Three\nDESCRIPTION: C."))
    g = vgs.load_state()["groups"][gid]
    assert g["name"] and g["named_by"] == "model" and g["anchor"]


def test_two_groups_never_get_the_same_name(made):
    db, _ = made
    vn.name_groups(db, FakeLLM("NAME: Same name\nDESCRIPTION: A."))
    names = [g["name"] for g in vgs.load_state()["groups"].values()]
    assert names.count("Same name") == 1 and "" in names
    llm = FakeLLM("NAME: Other name\nDESCRIPTION: B.")
    vn.name_groups(db, llm)
    assert "Same name" in llm.prompts[0]           # told which names are taken


def test_the_ratings_database_is_unchanged(made):
    db, _ = made
    rows = lambda: [tuple(r) for r in db._conn().execute("SELECT * FROM rephrases ORDER BY id")]
    before = rows()
    vn.name_groups(db, FakeLLM())
    assert rows() == before


# ── The on-device model: never loaded, never used while busy ────────

def test_a_local_model_gets_a_compact_prompt(made):
    db, _ = made
    big, small = FakeLLM(), FakeLLM(local=True)
    vn.name_groups(db, big)
    vgs.restore(vg.empty_state())
    vgs.run_check(db, force=True)
    vn.name_groups(db, small)
    assert len(small.prompts[0]) < len(big.prompts[0])


def test_a_busy_on_device_model_is_left_alone(made):
    from src.ai.mlx_utils import MLX_GENERATE_LOCK
    db, _ = made
    held, release = threading.Event(), threading.Event()

    def other_feature():
        with MLX_GENERATE_LOCK:
            held.set()
            release.wait(5)
    t = threading.Thread(target=other_feature)
    t.start()
    held.wait(5)
    try:
        before = groups_file()
        llm = FakeLLM(local=True)
        got = vn.name_groups(db, llm, wait=0)
        assert got["busy"] and llm.prompts == [] and groups_file() == before
    finally:
        release.set()
        t.join()


def test_an_on_device_model_is_never_loaded_just_for_names(monkeypatch):
    from src.ai import word_suggest as ws
    monkeypatch.setattr(ws, "_LLM", {})
    monkeypatch.setattr(vn, "_configured_local", lambda: "mlx-community/some-model")
    monkeypatch.setattr(vn, "_resident", lambda _m: False)
    monkeypatch.setattr(ws, "get_llm", lambda: pytest.fail("would load the model"))
    assert vn.model_if_ready() is None
    monkeypatch.setattr(vn, "_configured_local", lambda: None)     # nothing set up
    assert vn.model_if_ready() is None


def test_the_rephrase_model_is_used_when_it_is_ready(monkeypatch):
    from src.ai import word_suggest as ws
    fake = FakeLLM()
    monkeypatch.setattr(ws, "_LLM", {"llm": fake})
    assert vn.model_if_ready() is fake
    monkeypatch.setattr(ws, "_LLM", {})
    monkeypatch.setattr(vn, "_configured_local", lambda: "")       # a cloud or server model
    monkeypatch.setattr(ws, "get_llm", lambda: fake)
    assert vn.model_if_ready() is fake


def test_background_naming_runs_only_for_the_apps_own_ratings(made, monkeypatch):
    db, _ = made
    assert not vn.is_app_db(db)
    assert vn.start_naming(db, llm=FakeLLM()) is None
    monkeypatch.setattr(vn, "is_app_db", lambda _db: True)
    monkeypatch.setitem(vn._job, "at", 0.0)
    seen = []
    t = vn.start_naming(db, on_done=seen.append, llm=FakeLLM(
        "NAME: One\nDESCRIPTION: A.", "NAME: Two\nDESCRIPTION: B."), force=True)
    t.join(10)
    assert seen and len(seen[0]["named"]) == 2
    assert vn.start_naming(db, llm=FakeLLM()) is None              # not again straight away


# ── Proposals only: borderline pairs and the "more than 8" merge ─────

def test_a_borderline_pair_the_model_reads_as_one_voice_is_proposed(made, monkeypatch):
    db, paths = made
    near, far = gid_of(db, paths, "Near"), gid_of(db, paths, "Far")
    a, b = sorted([near, far])
    monkeypatch.setattr(vn, "_pair_distances",
                        lambda state, srcs: [((vg.SAME + vg.APART) / 2, a, b)])
    vn.name_groups(db, FakeLLM("NAME: One\nDESCRIPTION: A.", "NAME: Two\nDESCRIPTION: B.",
                               "SAME: yes\nWHY: Both plain and close."))
    state = vgs.load_state()
    assert len(state["groups"]) == 2                               # nothing merged
    props = vr.overview(db)["proposals"]
    assert len(props) == 1 and props[0]["kind"] == "merge"
    assert "model reads" in props[0]["text"]
    # Asked once: a second run puts no question.
    llm = FakeLLM("SAME: yes")
    vn.name_groups(db, llm)
    assert llm.prompts == []
    # Declined stays declined; accepted merges (the writer decides).
    vr.decline(db, props[0]["proposal"])
    assert vr.overview(db)["proposals"] == []


def test_a_no_or_unreadable_verdict_proposes_nothing(made, monkeypatch):
    db, paths = made
    a, b = sorted([gid_of(db, paths, "Near"), gid_of(db, paths, "Far")])
    monkeypatch.setattr(vn, "_pair_distances",
                        lambda state, srcs: [((vg.SAME + vg.APART) / 2, a, b)])
    for reply in ("SAME: no\nWHY: Different person.", "Hard to say."):
        vgs.restore(dict(vgs.load_state(), model_advice={}))
        vn.name_groups(db, FakeLLM("NAME: X\nDESCRIPTION: A.", "NAME: Y\nDESCRIPTION: B.", reply))
        assert vr.overview(db)["proposals"] == []


def _state_with(groups, proposals=(), advice=None, dismissed=()):
    st = vg.empty_state()
    for gid, sources in groups.items():
        st["groups"][gid] = {"id": gid, "name": "", "sources": list(sources)}
    st["proposals"] = list(proposals)
    st["dismissed"] = list(dismissed)
    if advice is not None:
        st["model_advice"] = advice
    return st


def test_over_eight_groups_the_model_picks_which_pair_to_suggest():
    over = {"key": "merge:g1+g2|w", "kind": "merge", "groups": ["g1", "g2"], "sources": ["w"],
            "why": "more than 8 voices: merging the closest two"}
    groups = {"g1": ["a"], "g2": ["b"], "g3": ["c"]}
    assert vn.with_advice(_state_with(groups, [over])) == [over]
    advice = {"most_alike": {"pair": ["g2", "g3"], "pair_sources": "b|c"}}
    got = vn.with_advice(_state_with(groups, [over], advice))
    assert len(got) == 1 and got[0]["groups"] == ["g2", "g3"] and got[0]["sources"] == ["w"]
    # The groups have changed since: the advice is ignored.
    stale = {"most_alike": {"pair": ["g2", "g3"], "pair_sources": "b|x"}}
    assert vn.with_advice(_state_with(groups, [over], stale)) == [over]
    # The writer declined the model's pair: V.2's own suggestion stands.
    st = _state_with(groups, [over], advice, dismissed=["merge:g2+g3|w"])
    assert vn.with_advice(st) == [over]


def test_with_advice_ignores_damaged_advice():
    st = _state_with({"g1": ["a"]}, advice={"same_voice": {"x": {"same": True, "groups": "bad"}},
                                            "most_alike": "bad"})
    assert vn.with_advice(st) == []


# ── Reading replies ──────────────────────────────────────────────────

def test_reading_replies():
    assert vn.parse_name("Sure!\nNAME: wry first-person narrator\nDESCRIPTION: dry, quick") == \
        ("Wry first-person narrator", "Dry, quick.")
    assert vn.parse_name("NAME: Quiet Watcher") == ("Quiet Watcher", "")
    assert vn.parse_name("Name - Quiet") is None
    assert vn.parse_same("SAME: **No**\nWHY: tense differs") == (False, "tense differs")
    assert vn.parse_same("same: yes") == (True, "")
    assert vn.parse_same("maybe") is None
    assert vn.parse_pair("PAIR: 2", 3) == 1
    assert vn.parse_pair("PAIR: 7", 3) is None and vn.parse_pair("two", 3) is None


# ── The names just appear in V.5's tree ──────────────────────────────

def test_names_appear_in_the_groups_view_without_new_controls(made, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QPushButton
    from src.ui.voice_groups_view import VoiceGroupsView
    app = QApplication.instance() or QApplication([])
    db, _ = made
    view = VoiceGroupsView(db=db, shared=False)
    view.refresh()
    buttons = len(view.findChildren(QPushButton))
    view.name_later(force=True)                     # another database: nothing starts
    assert vn._job["thread"] is None or not vn._job["thread"].is_alive()
    view.shared = True
    monkeypatch.setattr(vn, "is_app_db", lambda _db: True)
    monkeypatch.setattr(vn, "model_if_ready", lambda: FakeLLM(
        "NAME: Clipped watcher\nDESCRIPTION: Short looks.", "NAME: Harbour drift\nDESCRIPTION: Long."))
    view.show()
    view.name_later(force=True)
    vn._job["thread"].join(10)
    app.processEvents()
    texts = [view.tree.topLevelItem(i).text(0) for i in range(view.tree.topLevelItemCount())]
    assert any(t.startswith("Clipped watcher — Short looks.") for t in texts)
    assert len(view.findChildren(QPushButton)) == buttons
    view.close()
    view.deleteLater()
