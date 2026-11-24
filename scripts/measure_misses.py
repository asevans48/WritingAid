"""How much does the readiness check miss?

    venv/bin/python scripts/measure_misses.py              # the rules alone
    venv/bin/python scripts/measure_misses.py --model      # also with the configured model
    venv/bin/python scripts/measure_misses.py --rounds 10  # more seeded copies
    venv/bin/python scripts/measure_misses.py --model --limit 6 --cases 8   # a quick sample
    venv/bin/python scripts/measure_misses.py --model --editor --limit 3 --cases 4

With a model on this machine a full run takes hours (about four requests a
passage and three a story case); it prints its progress, and ``--limit`` and
``--cases`` take a sample.

A copyeditor is trusted for what is *not* flagged, so this counts misses,
not just false alarms. It runs the readiness engine itself (what the
scorecard shows) on a throwaway project in a temporary folder:

* **Spelling and grammar.** Every clean benchmark passage is copied
  ``--rounds`` times with known mistakes inserted (the Q.1 kinds, plus a
  missing word and harder confusions such as quite/quiet). Per kind: how
  many the check "Spelling and grammar left" caught, with the rules alone
  and, with ``--model``, after the model proofread.
* **False alarms.** Flags on the untouched passages, per 1,000 words.
* **Story.** ``benchmark/story/cases.json``: short three-chapter books in
  which the last chapter contradicts the first (or doesn't). With
  ``--model``: how many contradictions the story read caught, and how many
  findings it raised on the books with nothing wrong.

Writes ``docs/publishing/miss_rates.md`` and ``miss_rates.json``. Nothing
is sent anywhere without ``--model``; no real project or store is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
OUT_MD = ROOT / "docs" / "publishing" / "miss_rates.md"
OUT_JSON = ROOT / "docs" / "publishing" / "miss_rates.json"

HARDER = [                        # (pattern, replacement, label)
    (r"\bquite\b", "quiet", "quite → quiet"), (r"\bquiet\b", "quite", "quiet → quite"),
    (r"\bpassed\b", "past", "passed → past"), (r"\bpast\b", "passed", "past → passed"),
    (r"\bwhose\b", "who's", "whose → who's"), (r"\bled\b", "lead", "led → lead"),
    (r"\bthrough\b", "though", "through → though"), (r"\bthought\b", "though", "thought → though"),
    (r"\bfrom\b", "form", "from → form"), (r"\bwere\b", "where", "were → where"),
    (r"\bhis\b", "he's", "his → he's"), (r"\bof\b", "off", "of → off"),
]
MISSING = [                       # a word dropped
    (r"\b(in|on|at|of|from|into) the\b", r"\1", "“the” dropped"),
    (r"\b(began|wanted|tried|seemed|had) to\b", r"\1", "“to” dropped"),
    (r"\b(it|he|she|there) was\b", r"\1", "“was” dropped"),
]


def seed_more(text: str, insertions: List[Dict], rng: random.Random) -> Tuple[str, List[Dict]]:
    """Add a harder confusion and a missing word to an already seeded text."""
    for kind, options in (("harder_confusion", HARDER), ("missing_word", MISSING)):
        options = list(options)
        rng.shuffle(options)
        for pattern, new, label in options:
            taken = [(i["start"], i["end"]) for i in insertions]
            matches = [m for m in re.finditer(pattern, text)
                       if all(m.end() + 3 < a or m.start() - 3 > b for a, b in taken)]
            if not matches:
                continue
            m = rng.choice(matches)
            repl = m.expand(new)
            delta = len(repl) - (m.end() - m.start())
            text = text[:m.start()] + repl + text[m.end():]
            for i in insertions:
                if i["start"] >= m.end():
                    i["start"] += delta
                    i["end"] += delta
            insertions.append({"kind": kind, "start": m.start(), "end": m.start() + len(repl),
                               "text": repl, "original": m.group(0), "change": label})
            break
    return text, sorted(insertions, key=lambda i: i["start"])


def seeded_passages(rounds: int) -> List[Dict[str, Any]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_benchmark import seed_mistakes
    out = []
    for path in sorted((BENCH / "clean").glob("*.txt")):
        clean = path.read_text(encoding="utf-8")
        for n in range(rounds):
            rng = random.Random(f"{path.stem}:{n}")
            text, ins = seed_mistakes(clean, rng)
            text, ins = seed_more(text, ins, rng)
            out.append({"name": f"{path.stem} #{n + 1}", "clean": clean, "text": text,
                        "insertions": ins})
    return out


def _project(folder: Path, chapters: List[str], names: List[str]):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Benchmark", manuscript=Manuscript(title="Benchmark"))
    p.project_path = str(folder / "benchmark.writerproj")
    for i, text in enumerate(chapters):
        ch = Chapter(id=f"c{i + 1}", number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = text
        p.manuscript.chapters.append(ch)
    try:
        p.dictionary.words = list(names)             # what a project would record: the names
    except Exception:
        pass
    return p


def _overlaps(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def score_errors(passages: List[Dict[str, Any]], llm=None) -> Dict[str, Any]:
    """Caught and missed per kind, and flags that hit no inserted mistake."""
    from score_checks import story_names
    from src.ai import readiness as rd
    from src.utils import proof_store
    by_kind = defaultdict(lambda: {"caught": 0, "missed": 0, "examples": []})
    wrong = words = clean_flags = clean_words = 0
    for n, ps in enumerate(passages):
        proof_store.clear()
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(Path(tmp), [ps["text"], ps["clean"]], story_names(ps["clean"]))
            seeded = rd.chapter_report(p, p.manuscript.chapters[0], llm=llm,
                                       checks=["spelling_grammar"])
            clean = rd.chapter_report(p, p.manuscript.chapters[1], llm=llm,
                                      checks=["spelling_grammar"])
        items = [i for i in seeded.results["spelling_grammar"].items if i.verdict != "cleared"]
        for ins in ps["insertions"]:
            span = (ins["start"] - 1, ins["end"] + 1)
            hit = any(_overlaps((i.start, i.end), span) for i in items)
            entry = by_kind[ins["kind"]]
            entry["caught" if hit else "missed"] += 1
            if not hit and len(entry["examples"]) < 5:
                entry["examples"].append(ins["change"])
        wrong += sum(1 for i in items
                     if not any(_overlaps((i.start, i.end), (x["start"] - 1, x["end"] + 1))
                                for x in ps["insertions"]))
        words += len(ps["text"].split())
        clean_flags += sum(1 for i in clean.results["spelling_grammar"].items
                           if i.verdict != "cleared")
        clean_words += len(ps["clean"].split())
        if llm is not None:
            print(f"  proofread {n + 1}/{len(passages)} ({time.strftime('%H:%M:%S')})",
                  flush=True)
    caught = sum(v["caught"] for v in by_kind.values())
    missed = sum(v["missed"] for v in by_kind.values())
    return {"by_kind": dict(by_kind), "caught": caught, "missed": missed,
            "wrong_per_1000": round(wrong * 1000.0 / max(words, 1), 2),
            "clean_per_1000": round(clean_flags * 1000.0 / max(clean_words, 1), 2)}


STORY_CHECKS = ("character_disconnects", "plot_jumps", "continuity")


def story_cases(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """The cases; a sample keeps contradictions and controls in proportion."""
    cases = json.loads((BENCH / "story" / "cases.json").read_text(encoding="utf-8"))["cases"]
    if limit and limit < len(cases):
        wrong = [c for c in cases if c["expect"] is not None]
        fine = [c for c in cases if c["expect"] is None]
        n_fine = max(1, round(limit * len(fine) / len(cases)))
        cases = wrong[:limit - n_fine] + fine[:n_fine]
    return cases


def score_story(llm, limit: Optional[int] = None) -> Dict[str, Any]:
    """The story read on the hand-written cases (needs a model)."""
    from src.ai import readiness as rd
    from src.utils import proof_store
    cases = story_cases(limit)
    out = {"caught": 0, "missed": 0, "missed_cases": [], "controls": 0, "false_findings": 0,
           "false_cases": [], "other_findings": 0, "could_not_read": 0, "facts": 0}
    for case in cases:
        proof_store.clear()
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(Path(tmp), case["chapters"], [])
            book = rd.Book(p, None)
            reports = [rd.chapter_report(p, ch, llm=llm, checks=list(STORY_CHECKS), book=book)
                       for ch in p.manuscript.chapters]
            from src.ai import story_ledger
            out["facts"] += len(story_ledger.for_book(book).all_facts())
        found = [(n, i) for n, r in enumerate(reports) for name in STORY_CHECKS
                 if name in r.results for i in r.results[name].items]
        if any(r.results[name].status == rd.Status.COULD_NOT_CHECK
               for r in reports for name in STORY_CHECKS if name in r.results):
            out["could_not_read"] += 1
        if case["expect"] is None:
            out["controls"] += 1
            print(f"  story case {case['id']}: {len(found)} findings (none expected)", flush=True)
            if found:
                out["false_findings"] += len(found)
                out["false_cases"].append(f"{case['id']}: “{found[0][1].text[:60]}”")
            continue
        last = case["chapters"][-1]
        at = last.find(case["expect"])
        span = (at, at + len(case["expect"]))
        hit = any(n == len(case["chapters"]) - 1 and _overlaps((i.start, i.end), span)
                  for n, i in found)
        out["caught" if hit else "missed"] += 1
        if not hit:
            out["missed_cases"].append(f"{case['id']} ({case['note']})")
        out["other_findings"] += sum(1 for n, i in found
                                     if not (n == len(case["chapters"]) - 1
                                             and _overlaps((i.start, i.end), span)))
        print(f"  story case {case['id']}: {'caught' if hit else 'MISSED'}", flush=True)
    return out


EDITOR_CHECKS = ("scene_purpose", "pov_slips", "reader_pull")


def score_editor(llm) -> Dict[str, Any]:
    """The editor's checks and the letter on books with one planted
    structural flaw (needs a model)."""
    from src.ai import editorial_letter
    from src.ai import readiness as rd
    from src.utils import proof_store
    cases = json.loads((BENCH / "story" / "editor_cases.json").read_text(encoding="utf-8"))["cases"]
    out = {"caught": 0, "missed": 0, "missed_cases": [], "in_letter": 0, "flawed": 0,
           "control_findings": 0, "control_cases": [], "letters_unreadable": 0}
    for case in cases:
        proof_store.clear()
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(Path(tmp), case["chapters"], [])
            report = rd.book_report(p, llm=llm)
            try:
                letter = editorial_letter.write(llm, p, None, report, save=False)
            except Exception as e:
                print(f"  letter for {case['id']}: {e}", flush=True)
                letter = None
                out["letters_unreadable"] += 1
        found = {name: [(n, i) for n, ch in enumerate(report.chapters)
                        if name in ch.results for i in ch.results[name].items]
                 for name in EDITOR_CHECKS}
        found["loose_threads"] = [
            (int(i.chapter_id[1:]) - 1, i)
            for i in (report.book_results.get("loose_threads").items
                      if "loose_threads" in report.book_results else [])]
        exp = case["expect"]
        if exp is None:
            n = sum(len(v) for v in found.values())
            out["control_findings"] += n
            if n:
                out["control_cases"].append(f"{case['id']}: {n}")
            print(f"  editor case {case['id']}: {n} findings (none expected)", flush=True)
            continue
        out["flawed"] += 1
        hit = any(n == exp["chapter"] and (exp["quote"] is None
                                           or exp["quote"] in (i.text + " " + i.reason))
                  for n, i in found[exp["check"]])
        out["caught" if hit else "missed"] += 1
        if not hit:
            out["missed_cases"].append(f"{case['id']} ({case['note']})")
        if letter and any(f"c{exp['chapter'] + 1}" in i["chapters"] for i in letter["issues"]):
            out["in_letter"] += 1
        print(f"  editor case {case['id']}: {'caught' if hit else 'MISSED'}", flush=True)
    return out


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / (a + b):.0f}%" if a + b else "—"


LABELS = {"spelling": "Misspelling", "confused_word": "Confused word (their/there, could of)",
          "agreement": "Subject–verb agreement", "punctuation": "Punctuation and capitals",
          "repeated_word": "Doubled word", "harder_confusion": "Harder confusion (quite/quiet)",
          "missing_word": "Missing word"}


def to_markdown(res: Dict[str, Any]) -> str:
    rules, model = res["rules"], res.get("model")
    lines = ["# How much does the check miss?", "",
             f"Written by `scripts/measure_misses.py` on {res['date']}. Rerun it after any "
             "change to a check, the proofreading pass or the story read.", "",
             f"**What was measured:** {res['passages']} copies of the benchmark's clean "
             f"passages with {rules['caught'] + rules['missed']} known mistakes inserted, "
             "read by the readiness check “Spelling and grammar left”"
             + (f"; and {res['story_cases']} short three-chapter books, in most of which the "
                "last chapter contradicts the first." if model else ".")
             + (" With LanguageTool." if res["languagetool"] else " Without LanguageTool."), "",
             "## Spelling and grammar: caught and missed", ""]
    head = "| Mistake | Inserted | Rules alone: caught |"
    rule = "|---|---|---|"
    if model:
        head += f" With the model ({res['model_name']}): caught |"
        rule += "---|"
    lines += [head, rule]
    for kind in LABELS:
        r = rules["by_kind"].get(kind)
        if not r:
            continue
        row = (f"| {LABELS[kind]} | {r['caught'] + r['missed']} | {r['caught']} "
               f"({_pct(r['caught'], r['missed'])}) |")
        if model:
            m = model["errors"]["by_kind"].get(kind, {"caught": 0, "missed": 0})
            row += f" {m['caught']} ({_pct(m['caught'], m['missed'])}) |"
        lines.append(row)
    row = (f"| **All** | {rules['caught'] + rules['missed']} | **{rules['caught']} "
           f"({_pct(rules['caught'], rules['missed'])})** |")
    if model:
        m = model["errors"]
        row += f" **{m['caught']} ({_pct(m['caught'], m['missed'])})** |"
    lines += [row, "",
              f"- Flags that hit no inserted mistake: {rules['wrong_per_1000']} per 1,000 words "
              "with the rules alone"
              + (f", {model['errors']['wrong_per_1000']} with the model." if model else "."),
              f"- Flags on the untouched passages: {rules['clean_per_1000']} per 1,000 words "
              "with the rules alone"
              + (f", {model['errors']['clean_per_1000']} with the model." if model else "."), ""]
    missed = {k: v["examples"] for k, v in (model["errors"] if model else rules)["by_kind"].items()
              if v["examples"]}
    if missed:
        lines += ["**Still missed" + (" with the model" if model else "") + ", for example:**", ""]
        lines += [f"- {LABELS.get(k, k)}: {'; '.join(v)}" for k, v in missed.items()] + [""]
    lines += ["## Story: contradictions caught", ""]
    if model:
        s = model["story"]
        lines += [f"- Contradictions caught: **{s['caught']} of {s['caught'] + s['missed']}** "
                  f"({_pct(s['caught'], s['missed'])}).",
                  f"- Findings on the {s['controls']} books with nothing wrong: "
                  f"**{s['false_findings']}**.",
                  f"- Other findings on the books with a contradiction: {s['other_findings']}.",
                  f"- Facts the model recorded for the style sheet: {s['facts']}."]
        if s["could_not_read"]:
            lines.append(f"- Books where a reply could not be read: {s['could_not_read']}.")
        if s["missed_cases"]:
            lines.append("- Missed: " + "; ".join(s["missed_cases"]) + ".")
        if s["false_cases"]:
            lines.append("- Wrongly raised: " + "; ".join(s["false_cases"]) + ".")
    else:
        lines.append("Not measured: the story read needs a model. Run with `--model`.")
    lines += ["", "## Structure: planted flaws caught", ""]
    if model and model.get("editor"):
        ed = model["editor"]
        lines += [f"- Planted flaws caught by the editor's checks: **{ed['caught']} of "
                  f"{ed['caught'] + ed['missed']}**.",
                  f"- Of those {ed['flawed']} books, the editorial letter named the flawed "
                  f"chapter in an issue for **{ed['in_letter']}**.",
                  f"- Findings on the book with nothing planted: {ed['control_findings']}."]
        if ed["missed_cases"]:
            lines.append("- Missed: " + "; ".join(ed["missed_cases"]) + ".")
        if ed["letters_unreadable"]:
            lines.append(f"- Letters that could not be read: {ed['letters_unreadable']}.")
    else:
        lines.append("Not measured: the outline, the editor's checks and the letter need a "
                     "model. Run with `--model --editor`.")
    lines += ["", "## What this does and doesn't show", "",
              "- The inserted mistakes are common kinds, one of each per copy; real drafts "
              "make others. A caught rate here is an upper bound on trust, not a promise.",
              "- The story cases are short and hand-written, with the contradiction two "
              "chapters after the fact. A novel's contradictions are further apart and "
              "subtler.",
              "- The structure cases are four short chapters with one obvious flaw each: "
              "a floor, not a measure of how the letter does on a real novel.",
              "- Model results vary by model and from run to run; the model is named above.",
              ""]
    return "\n".join(lines)


def _model():
    try:
        from src.ai.task_llm import build_critique_llm
        return build_critique_llm()
    except Exception as e:
        print(f"  [model] {e}")
        return None


def run(rounds: int = 5, languagetool: bool = False, llm=None,
        limit: Optional[int] = None, cases: Optional[int] = None,
        editor: bool = False) -> Dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from src.ai import readiness as rd
    if not languagetool:
        rd.Scanner._languagetool_ready = staticmethod(lambda: False)
    else:
        from src.utils.proofing import LanguageToolEngine
        LanguageToolEngine.get().ensure_started()
        rd.Scanner._languagetool_ready = staticmethod(lambda: True)
    passages = seeded_passages(rounds)
    if limit:
        step = max(1, len(passages) // limit)        # spread over the books
        passages = passages[::step][:limit]
    res: Dict[str, Any] = {"date": time.strftime("%Y-%m-%d"), "rounds": rounds,
                           "passages": len(passages), "languagetool": languagetool,
                           "story_cases": len(story_cases(cases)),
                           "rules": score_errors(passages)}
    if llm is not None:
        res["model_name"] = str(getattr(llm, "model", "") or "model")
        res["model"] = {"editor": score_editor(llm)} if editor else {}
        res["model"].update(story=score_story(llm, cases),
                            errors=score_errors(passages, llm))
    return res


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Count what the readiness check misses.")
    ap.add_argument("--model", action="store_true", help="also with the configured model")
    ap.add_argument("--rounds", type=int, default=5, help="seeded copies of each passage")
    ap.add_argument("--languagetool", action="store_true", help="include LanguageTool")
    ap.add_argument("--limit", type=int, help="only this many passages (a sample)")
    ap.add_argument("--cases", type=int, help="only this many story cases (a sample)")
    ap.add_argument("--editor", action="store_true",
                    help="with --model: also the planted structural flaws and the letter")
    ap.add_argument("--no-write", action="store_true", help="print only")
    args = ap.parse_args(argv)
    # Results are kept in a throwaway folder: no real project or store is touched.
    os.environ["HOME"] = tempfile.mkdtemp(prefix="measure-misses-") \
        if not args.model else os.environ.get("HOME", "")
    llm = None
    if args.model:
        sys.path.insert(0, str(ROOT))
        llm = _model()
        if llm is None:
            print("No model is configured; measuring the rules alone.")
    res = run(args.rounds, args.languagetool, llm, args.limit, args.cases, args.editor)
    md = to_markdown(res)
    print(md)
    if not args.no_write:
        OUT_MD.write_text(md, encoding="utf-8")
        OUT_JSON.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
        print(f"Wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    code = main(sys.argv[1:])
    sys.stdout.flush()
    os._exit(code)
