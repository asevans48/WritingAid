"""The miss-rate script: seeding and scoring, on the rules alone."""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import measure_misses as mm


def test_extra_mistakes_keep_every_offset_right():
    clean = sorted((mm.BENCH / "clean").glob("*.txt"))[0].read_text(encoding="utf-8")
    from build_benchmark import seed_mistakes
    rng = random.Random(3)
    text, ins = seed_mistakes(clean, rng)
    text, ins = mm.seed_more(text, ins, rng)
    kinds = {i["kind"] for i in ins}
    assert {"harder_confusion", "missing_word"} <= kinds
    assert all(text[i["start"]:i["end"]] == i["text"] for i in ins)


def test_story_cases_are_well_formed():
    cases = json.loads((mm.BENCH / "story" / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 12 and sum(1 for c in cases if c["expect"] is None) >= 4
    for c in cases:
        assert len(c["chapters"]) == 3
        assert c["expect"] is None or c["expect"] in c["chapters"][-1]


def test_the_report_counts_caught_and_missed(monkeypatch):
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    passages = mm.seeded_passages(1)[:2]
    monkeypatch.setattr(mm, "seeded_passages", lambda rounds: passages)
    res = mm.run(rounds=1)
    rules = res["rules"]
    total = sum(len(p["insertions"]) for p in passages)
    assert rules["caught"] + rules["missed"] == total and rules["caught"] > 0
    assert rules["by_kind"]["spelling"]["missed"] == 0
    md = mm.to_markdown(res)
    assert "Rules alone: caught" in md and "Not measured: the story read needs a model" in md


def test_planted_structural_flaws_are_scored(monkeypatch):
    """A stand-in model that outlines the flaws: the scorer counts them."""
    from src.ai import readiness as rd
    monkeypatch.setattr(rd.Scanner, "_languagetool_ready", staticmethod(lambda: False))
    cases = json.loads((mm.BENCH / "story" / "editor_cases.json").read_text())["cases"]
    assert sum(1 for c in cases if c["expect"] is None) >= 1

    class LLM:
        model = "stand-in"

        def generate_text(self, prompt, system="", **kw):
            if "Outline this chapter" in prompt:
                if "fed the hens" in prompt:
                    return ('SCENE | Ilse | chores | NONE | "Next morning Ilse fed the hens"\n'
                            'READER | 1 | nothing happens | "The weather was dry"')
                out = 'SCENE | Ilse | things happen | it changes her position | NONE\n'
                if "thought privately" in prompt:
                    out += ('SLIP | "thought privately that she looked like her mother" | '
                            'from Ilse to the bailiff\n')
                if "pistol wrapped in oilcloth" in prompt:
                    out += 'SETUP | she vows to use the pistol | "her dead father\'s pistol"\n'
                if "met them at the gate" in prompt:
                    out += 'PAYOFF | the pistol is used | "took out her father\'s pistol"\n'
                return out + "READER | 4 | strong | NONE"
            if prompt.startswith("OUTLINE OF THE BOOK"):
                return ("NONE" if "payoff: the pistol is used" in prompt
                        else "1 | the pistol is never used")
            if "Write the manuscript evaluation" in prompt:
                return "ISSUE | Structure | Chapter 3 sags | Chapter 3 | readers drift | cut it"
            return "NONE"

    got = mm.score_editor(LLM())
    assert got["caught"] == got["flawed"] == 4 and got["missed"] == 0
    assert got["control_findings"] == 0 and got["in_letter"] == 2
