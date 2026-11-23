"""Q.1 and Q.2: the benchmark set is consistent, and the scorer measures
what it claims to."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _restore_what_the_scorer_switches_off(monkeypatch):
    """The scorer turns LanguageTool and the background model off for the
    whole process (fine for a script). Inside pytest, put them back after
    each test so later tests see the real ones."""
    import src.ai.word_suggest as ws
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", pf.LanguageToolEngine.ensure_started)
    monkeypatch.setattr(ws, "get_llm", ws.get_llm)


def _scorer():
    spec = importlib.util.spec_from_file_location("score_checks", ROOT / "scripts" / "score_checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Q.1: the set ────────────────────────────────────────────────────────

def test_clean_passages_and_manifest_agree():
    manifest = json.loads((BENCH / "clean" / "manifest.json").read_text())
    files = sorted(p.name for p in (BENCH / "clean").glob("*.txt"))
    assert sorted(m["file"] for m in manifest) == files and len(files) >= 10
    assert len({m["genre"] for m in manifest}) >= 6
    for m in manifest:
        assert 150 <= m["words"] <= 500


def test_every_seeded_mistake_is_where_it_says():
    total = 0
    for path in (BENCH / "seeded").glob("*.json"):
        data = json.loads(path.read_text())
        clean = (BENCH / "clean" / f"{data['source']}.txt").read_text().rstrip("\n")
        assert data["text"] != clean
        for i in data["insertions"]:
            assert data["text"][i["start"]:i["end"]] == i["text"], (path.name, i)
            assert i["kind"] in {"spelling", "confused_word", "agreement", "punctuation", "repeated_word"}
            total += 1
    assert total >= 40


def test_every_mark_is_in_its_passage():
    data = json.loads((BENCH / "style" / "marked.json").read_text())
    kinds = set(_scorer().STYLE_KINDS) | {"overdescribed"}
    for p in data["passages"]:
        for m in p["marks"]:
            assert m["text"] in p["text"], (p["id"], m["text"])
            assert m["kind"] in kinds and isinstance(m["flag"], bool) and m.get("why")
    flags = [m["flag"] for p in data["passages"] for m in p["marks"]]
    assert any(flags) and not all(flags)        # right flags and deliberate choices


def test_no_passage_is_in_another_language():
    for path in (BENCH / "clean").glob("*.txt"):
        text = path.read_text()
        assert sum(text.count(w) for w in (" the ", " and ", " of ")) > 10, path.name


# ── Q.2: the scorer ─────────────────────────────────────────────────────

def test_marks_are_judged_by_overlap_and_kind():
    s = _scorer()
    text = "The door was kicked open. He was born there."
    marks = [{"kind": "passive", "text": "was kicked", "flag": True},
             {"kind": "passive", "text": "was born", "flag": False}]
    flags = [{"kind": "passive", "start": 9, "end": 19},       # right
             {"kind": "passive", "start": 29, "end": 37},      # on a deliberate choice
             {"kind": "adverb", "start": 0, "end": 3}]         # another kind: not counted here
    got = s._judge_against_marks(text, marks, flags, ["passive"])["passive"]
    assert got == {"right": 1, "wrong": 1, "on_deliberate": 1, "missed": 0, "marked_right": 1}


def test_a_mark_covers_every_occurrence():
    s = _scorer()
    text = "light here, light there"
    marks = [{"kind": "echo", "text": "light", "flag": True}]
    flags = [{"kind": "echo", "start": 12, "end": 17}]
    assert s._judge_against_marks(text, marks, flags, ["echo"])["echo"]["right"] == 1


def test_names_are_found_the_way_a_project_would_record_them():
    s = _scorer()
    text = "Buck ran. The dogs followed Buck. Spitz snarled, and Buck turned. Spitz ran. buck"
    assert s.story_names(text) == ["Spitz"]        # 'buck' also appears in lower case


def test_targets_and_verdicts():
    s = _scorer()
    assert s.verdict(0.9, 1.0) == "meets both targets"
    assert "below 4 in 5" in s.verdict(0.5, 1.0)
    assert "too many" in s.verdict(0.9, 20.0)


@pytest.fixture
def results():
    return _scorer().run(languagetool=False)


def test_the_scorer_runs_and_names_the_worst_checks(results):
    s = _scorer()
    res, rows = results
    checks = {r["check"] for r in rows}
    assert {"Spelling", "Grammar", "Passive voice", "Sticky sentences", "Overly descriptive"} <= checks
    assert res["seeded"]["by_mistake"]["spelling"]["found"] >= 10     # obvious misspellings are caught
    assert len(s.worst(rows)) == 4
    md = s.to_markdown({**res, "date": "test"}, rows)
    assert "| Check |" in md and "## The worst checks" in md


def test_the_model_tier_runs_with_a_model_that_keeps_everything(monkeypatch):
    """--model path: a model that answers nothing useful changes nothing and
    breaks nothing."""
    s = _scorer()

    class Silent:
        def generate_text(self, *a, **k):
            return ""
    c = s.Checker(False)
    text = (BENCH / "clean" / "call-of-wild.txt").read_text()
    without = c.flags(text)
    with_model = c.flags(text, Silent())
    assert len(with_model) == len(without)
