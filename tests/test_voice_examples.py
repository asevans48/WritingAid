"""Suggestions learn from the same voice (piece V.4), and "Keep this
project's ratings to itself" (README decision 5)."""

import json
import random

import pytest

from src.ai import rewrite_quality as rq
from src.ai import voice_examples as ve
from src.ai import voice_groups as vg
from src.data import ratings_privacy as rp
from src.data import voice_groups_store as vgs

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


@pytest.fixture
def world(tmp_path):
    """Two projects in two voices, 32 rated passages each. The far voice's
    ratings are all "excellent", so today's choice prefers them even for
    a passage in the near voice."""
    from src.data.rephrase_database import RephraseDatabase
    db = RephraseDatabase(tmp_path / "ratings.db")
    near, far = str(tmp_path / "Near.writerproj"), str(tmp_path / "Far.writerproj")
    rng = random.Random(1)
    texts = {}
    for project, make, tag, rating in ((near, _first, "near", "good"),
                                       (far, _third, "far", "excellent")):
        for i in range(32):
            text = make(rng)
            row = db.log(f"The {tag} passage {i}.", f"The {tag} rewrite {i}.",
                         source_type="rephrase", surrounding_before=text, project_path=project,
                         rating=rating, accepted=True)
            texts[row] = text
        db.log(f"The {tag} passage 99.", f"A {tag} rewrite they hated.", source_type="rephrase",
               surrounding_before=make(rng), project_path=project, rating="bad", accepted=False)
    state = vgs.run_check(db)
    assert len(state["groups"]) == 2
    return db, near, far, texts, rng


def _projects(choice):
    return [r["project_path"] for r in choice.chosen + choice.rejected]


def _old_examples_prompt(passage, project_path="", *, chosen=2, rejected=1, max_chars=500, db):
    """examples_prompt as it was before V.4, to prove nothing changed."""
    rows = db.rated_examples(project_path=project_path)

    def pick(items, n):
        usable = [r for r in items if r.get("source_text") and r.get("output_text")
                  and len(r["source_text"]) <= max_chars and len(r["output_text"]) <= max_chars]
        usable.sort(key=lambda r: (-(r.get("rating") == "excellent")
                                   - (r.get("project_path") == project_path) * 0.5
                                   - rq._overlap(passage, r["source_text"])))
        return usable[:n]

    good, bad = pick(rows.get("chosen", []), chosen), pick(rows.get("rejected", []), rejected)
    if not good and not bad:
        return ""
    lines = ["REWRITES THIS AUTHOR RATED (learn their taste; don't reuse the content):"]
    for r in good:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They chose: \"{r['output_text']}\"")
    for r in bad:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They rejected: \"{r['output_text']}\"")
    return "\n".join(lines)


# ── The voice decides ────────────────────────────────────────────────

def test_today_would_give_the_other_voice(world):
    db, near, far, _, rng = world
    old = _old_examples_prompt("A passage.", near, db=db)
    assert "far rewrite" in old            # excellent ratings from the other book win today


def test_a_passage_never_gets_the_other_voice_while_its_group_has_enough(world):
    db, near, far, _, rng = world
    for _ in range(5):
        for project, make in ((near, _first), (far, _third)):
            got = ve.choose("A passage.", project, db=db, before=make(rng))
            assert got.group_id and not got.filled
            assert set(_projects(got)) == {project}
            assert len(got.chosen) == 2 and len(got.rejected) == 1
    note = {}
    block = rq.examples_prompt("A passage.", near, db=db, before=_first(rng), note=note)
    assert "far" not in block and "near rewrite" in block
    assert "in the voice of this passage" in block
    assert note["from"].startswith("from your voice group “")


def test_closest_to_the_passage_voice_comes_first(world):
    db, near, _, texts, _ = world
    rows = {r["id"]: r for r in db.rated_examples(project_path=near, limit=200)["chosen"]}
    target = [i for i in sorted(rows) if rows[i]["project_path"] == near][7]
    got = ve.choose(rows[target]["source_text"], near, db=db, before=texts[target], chosen=1)
    assert got.chosen[0]["id"] == target


def test_too_few_in_the_group_and_the_nearest_fills_in(world):
    db, near, far, _, rng = world
    got = ve.choose("A passage.", near, db=db, before=_first(rng), chosen=35)
    projects = [r["project_path"] for r in got.chosen]
    assert projects[:32] == [near] * 32 and projects[32:] == [far] * 3
    assert got.filled and "nearest group filling in" in got.label


def test_an_unsorted_source_learns_as_today(world, tmp_path):
    db, near, far, _, rng = world
    new = str(tmp_path / "New.writerproj")       # no ratings yet: Unsorted
    assert vgs.group_for(new) is None
    for project in (new, ""):
        note = {}
        got = rq.examples_prompt("The near passage.", project, db=db, before=_first(rng), note=note)
        assert got == _old_examples_prompt("The near passage.", project, db=db)
        assert note["from"] == "from all your ratings"


def test_with_one_group_or_none_the_examples_are_exactly_todays(world, monkeypatch):
    db, near, far, _, rng = world
    state = vgs.load_state()
    one = dict(state, groups=dict(list(state["groups"].items())[:1]))
    for st in (one, vg.empty_state()):
        monkeypatch.setattr(vgs, "load_state", lambda st=st: vg.normalise_state(st))
        for project in (near, far):
            for passage in ("The near passage.", "The far passage 3."):
                assert (rq.examples_prompt(passage, project, db=db, before=_first(rng))
                        == _old_examples_prompt(passage, project, db=db))


def test_without_a_groups_file_or_fingerprints_nothing_changes(tmp_path):
    from src.data.rephrase_database import RephraseDatabase
    db = RephraseDatabase(tmp_path / "plain.db")
    db.log("The ship came in at dusk.", "The ship limped home.", source_type="rephrase",
           rating="good", accepted=True, project_path="/p/a.json")
    db.log("Other.", "Other choice.", source_type="rephrase", rating="excellent",
           accepted=True, project_path="/p/b.json")
    assert not vgs.groups_path().exists()
    assert (rq.examples_prompt("The ship.", "/p/a.json", db=db)
            == _old_examples_prompt("The ship.", "/p/a.json", db=db))
    assert rq.examples_prompt("x", db=RephraseDatabase(tmp_path / "empty.db")) == ""


def test_a_broken_groups_read_falls_back_to_today(world, monkeypatch):
    db, near, _, _, rng = world

    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(vgs, "read_rows", boom)
    assert (rq.examples_prompt("The near passage.", near, db=db, before=_first(rng))
            == _old_examples_prompt("The near passage.", near, db=db))


def test_the_ratings_database_is_only_read(world):
    db, near, _, _, rng = world

    def dump():
        c = db._conn()
        return [tuple(r) for r in c.execute("SELECT * FROM rephrases ORDER BY id")]
    before = dump()
    groups = vgs.groups_path().read_text()
    ve.choose("A passage.", near, db=db, before=_first(rng), chosen=35)
    assert dump() == before and vgs.groups_path().read_text() == groups


# ── Keep this project's ratings to itself ────────────────────────────

def test_the_switch_is_off_by_default_and_kept_beside_the_project(tmp_path):
    project = tmp_path / "Book.writerproj"
    assert rp.is_private(str(project)) is False
    assert rp.is_private("") is False and rp.set_private("", True) is False
    assert rp.set_private(str(project), True)
    assert rp.settings_path(str(project)) == tmp_path / "Book.ratings.json"
    assert json.loads((tmp_path / "Book.ratings.json").read_text())["keep_to_itself"] is True
    assert rp.is_private(str(project)) is True
    assert rp.set_private(str(project), False) and rp.is_private(str(project)) is False

    class P:
        project_path = str(project)
    assert rp.set_private(P(), True) and rp.is_private(P()) is True


def test_a_damaged_switch_file_means_off(tmp_path):
    project = tmp_path / "Book.writerproj"
    (tmp_path / "Book.ratings.json").write_text("{not json")
    assert rp.is_private(str(project)) is False


def test_a_kept_apart_project_never_reaches_another_projects_examples(world, tmp_path):
    db, near, far, _, rng = world
    rp.set_private(far, True)
    new = str(tmp_path / "New.writerproj")
    cases = [("The far passage 3.", new, _third), ("The far passage 3.", "", _third),
             ("A passage.", near, _first)]
    for passage, project, make in cases:
        for n in (2, 35, 80):
            got = ve.choose(passage, project, db=db, before=make(rng), chosen=n, rejected=n)
            assert far not in _projects(got)
            block = rq.examples_prompt(passage, project, db=db, before=make(rng), chosen=n)
            assert "far rewrite" not in block and "far passage" not in block
    # the kept-apart project still learns from its own ratings and from the others
    own = ve.choose("A passage.", far, db=db, before=_third(rng), chosen=40)
    assert set(_projects(own)) == {far, near}
    # nothing was deleted or moved
    assert len(db.rated_examples(project_path=far, limit=200)["chosen"]) == 64
    rp.set_private(far, False)
    assert far in _projects(ve.choose("x", new, db=db))


# ── Every place that rewrites passes the passage's surroundings ─────

def test_the_companions_fixes_measure_the_voice_around_the_sentence(monkeypatch):
    from src.ai import companion
    seen = {}

    def fake(passage, path="", **kw):
        seen.update(kw, passage=passage)
        return ""
    monkeypatch.setattr(rq, "examples_prompt", fake)

    class LLM:
        def generate_text(self, *a, **k):
            return ""
    text = "First para here. It is long.\n\nThe sentence to fix is here.\n\nAfter that, more."
    fix = companion.Fix(text="Tighten", why="wordy", excerpt="The sentence to fix is here.",
                        paragraph=2)
    try:
        companion.suggest_fix_options(LLM(), None, None, text, fix)
    except Exception:
        pass
    assert "First para" in seen["before"] and "After that" in seen["after"]


def test_a_new_book_in_a_known_voice_learns_from_that_voice(world, tmp_path, monkeypatch):
    db, near, far, _, rng = world
    new = str(tmp_path / "Sequel.writerproj")
    state = vgs.load_state()
    gid = state["sources"][vg.source_key(near)]["group"]
    state["sources"][vg.source_key(new)] = {"group": gid}
    monkeypatch.setattr(vgs, "load_state", lambda: vg.normalise_state(state))
    assert "far rewrite" in _old_examples_prompt("A passage.", new, db=db)   # today
    got = ve.choose("A passage.", new, db=db, before=_first(rng))
    assert set(_projects(got)) == {near} and got.group_id == gid
