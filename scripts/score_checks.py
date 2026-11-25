"""Score every check against the benchmark (piece Q.2).

    venv/bin/python scripts/score_checks.py             # no model
    venv/bin/python scripts/score_checks.py --model     # also with the configured model judging
    venv/bin/python scripts/score_checks.py --languagetool   # include LanguageTool (needs Java)

Runs the checks the way the editor shows them (the editor's own highlighter,
offscreen, with its quick rules for dialogue and names) over ``benchmark/``:

* **seeded/**: known mistakes inserted into clean prose. Per check: how many
  it found, how many it missed, how many of its flags were wrong.
* **clean/**: well-edited published prose. Flags per 1,000 words; nearly all
  are false alarms.
* **style/marked.json**: hand-marked passages. Per style check: right flags,
  wrong flags (including flags on deliberate choices) and misses.

It also scores the two style analysers side by side (``style_checks`` and
``ProWritingAnalyzer``) on the measures they share, for R.4.

Writes ``docs/publishing/check_scores.md`` (the table) and
``docs/publishing/check_scores.json`` (the numbers, for before/after).
Nothing is sent anywhere without ``--model``; no project or store is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
OUT_MD = ROOT / "docs" / "publishing" / "check_scores.md"
OUT_JSON = ROOT / "docs" / "publishing" / "check_scores.json"

# Targets (open decision 3 in the plan): a check is on by default only if at
# least 4 in 5 of its flags are right, and clean prose draws only a few flags
# per 1,000 words. Adjusted by the writer after the first numbers.
TARGET_PRECISION = 0.8
TARGET_CLEAN_RATE = 3.0

STYLE_KINDS = ["passive", "adverb", "intensifier", "wordy", "cliche", "repeated_start", "echo",
               "long_sentence", "hard_sentence", "sticky_sentence",
               "transition", "pronoun", "alliteration", "acronym"]      # the last four: P.2a
SHARED = ["passive", "adverb", "cliche", "sticky_sentence", "echo"]   # measured by both analysers

Span = Tuple[int, int]


# ── Running the editor's checks offscreen ──────────────────────────────

class Checker:
    def __init__(self, languagetool: bool):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(ROOT))
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import src.utils.proofing as pf
        if not languagetool:
            pf.LanguageToolEngine.ensure_started = lambda self: False
        import src.ai.word_suggest as ws
        ws.get_llm = lambda: None               # the editor's own background review stays off
        from src.ui.enhanced_text_editor import CheckMode
        self.CheckMode = CheckMode
        self._editor = None
        self.languagetool = languagetool

    def flags(self, text: str, llm=None) -> List[Dict[str, Any]]:
        """Every flag the editor would show: [{family, kind, start, end, text}].
        Uses a real (hidden) editor, so every setting matches the app."""
        from src.ui.enhanced_text_editor import EnhancedTextEditor, ErrorType
        ed = self._editor
        if ed is None:
            ed = self._editor = EnhancedTextEditor()
        hl = ed.writing_highlighter
        for setter in (hl.set_spell_mode, hl.set_grammar_mode, hl.set_overuse_mode, hl.set_style_mode):
            setter(self.CheckMode.REALTIME)
        hl.set_style_kinds(set(STYLE_KINDS))      # every style check, the P.2a ones too
        ed.setPlainText(text)
        # In the app the checkers know the project's characters and places
        # (EnhancedTextEditor.set_project_vocabulary). The benchmark has no
        # project, so it gives them what a project would record: the names.
        names = story_names(text)
        ed.spell_checker.set_project_words(names)
        ed.overuse_detector.set_names(names)
        ed.overuse_detector.update_cache(text)
        hl.update_full_text(text)
        if self.languagetool:
            hl.request_grammar_check()
            hl.wait_for_grammar(60000)
        hl.rehighlight()
        doc = ed.document()
        if llm is not None:
            self._judge(hl, doc, llm)
            hl.rehighlight()
        out = []
        family = {ErrorType.SPELLING: "spelling", ErrorType.GRAMMAR: "grammar",
                  ErrorType.OVERUSE: "overuse", ErrorType.OVERUSED_PHRASE: "overused_phrase",
                  ErrorType.STYLE: "style"}
        for block_no, errors in hl._errors.items():
            block = doc.findBlockByNumber(block_no)
            for e in errors:
                fam = family.get(e.error_type, "other")
                kind = getattr(e, "style_kind", "") if fam == "style" else fam
                out.append({"family": fam, "kind": kind, "start": block.position() + e.start,
                            "end": block.position() + e.end, "text": e.word})
        return out

    @staticmethod
    def _judge(hl, doc, llm) -> None:
        from src.ai import flag_judge as fj
        items = fj.collect(hl, doc)
        for category, batch in items.items():
            if batch:
                try:
                    fj.judge(llm, category, batch)
                except Exception as e:          # a model failure leaves the scan result
                    print(f"  [model] {category}: {e}")


def story_names(text: str) -> List[str]:
    """The characters and places a project would have records for: words that
    appear capitalised at least twice and never in lower case."""
    counts = defaultdict(int)
    for m in re.finditer(r"\b[A-Z][a-zà-ÿ]+(?:-[A-Z]?[a-zà-ÿ]+)*\b", text):
        counts[m.group(0)] += 1
    lower = {w.lower() for w in re.findall(r"\b[a-zà-ÿ][a-zà-ÿ-]*\b", text)}
    skip = {"I", "Mr", "Mrs", "Miss", "Sir", "Dr", "Oh", "Ah", "Yes", "No", "But", "And", "For",
            "When", "Then", "So", "Well", "Perhaps", "If", "As", "At", "In", "On"}
    return sorted(w for w, c in counts.items() if c >= 2 and w.lower() not in lower and w not in skip)


def overdescribed(text: str, llm=None) -> List[Dict[str, Any]]:
    from src.ai import overdescription as od
    if llm is None:
        flags = od.scan(text)
    else:
        review = od.review_chapter(text, llm)
        flags = [f for f in review.flags if f.verdict != "fine"]
    return [{"family": "style", "kind": "overdescribed", "start": f.start, "end": f.end,
             "text": f.text} for f in flags]


# ── Scoring ─────────────────────────────────────────────────────────────

def _overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _occurrences(text: str, snippet: str) -> List[Span]:
    return [(m.start(), m.start() + len(snippet)) for m in re.finditer(re.escape(snippet), text)]


def words(text: str) -> int:
    return len(text.split())


def score_seeded(checker, llm=None) -> Dict[str, Any]:
    """Spelling and grammar against inserted mistakes."""
    found = defaultdict(lambda: {"found": 0, "missed": 0})
    flags_right = defaultdict(int)
    flags_wrong = defaultdict(int)
    missed_examples = defaultdict(list)
    for path in sorted((BENCH / "seeded").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        text, ins = data["text"], data["insertions"]
        flags = checker.flags(text, llm)
        for i in ins:
            span = (i["start"] - 1, i["end"] + 1)
            hit_by = {f["family"] for f in flags if _overlaps((f["start"], f["end"]), span)
                      and f["family"] in ("spelling", "grammar")}
            key = i["kind"]
            if hit_by:
                found[key]["found"] += 1
            else:
                found[key]["missed"] += 1
                missed_examples[key].append(i["change"])
        for fam in ("spelling", "grammar"):
            for f in (f for f in flags if f["family"] == fam):
                if any(_overlaps((f["start"], f["end"]), (i["start"] - 1, i["end"] + 1)) for i in ins):
                    flags_right[fam] += 1
                else:
                    flags_wrong[fam] += 1
    return {"by_mistake": dict(found), "flags_right": dict(flags_right),
            "flags_wrong": dict(flags_wrong), "missed_examples": {k: v[:6] for k, v in missed_examples.items()}}


def score_clean(checker, llm=None) -> Dict[str, Any]:
    counts, total_words, examples = defaultdict(int), 0, defaultdict(list)
    for path in sorted((BENCH / "clean").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        total_words += words(text)
        for f in checker.flags(text, llm) + overdescribed(text, llm):
            counts[f["kind"]] += 1
            if len(examples[f["kind"]]) < 4:
                examples[f["kind"]].append(f["text"][:40])
    return {"words": total_words, "counts": dict(counts),
            "per_1000": {k: round(1000 * v / total_words, 1) for k, v in counts.items()},
            "examples": dict(examples)}


def _judge_against_marks(text: str, marks: List[Dict], flags: List[Dict], kinds) -> Dict[str, Dict[str, int]]:
    out = {k: {"right": 0, "wrong": 0, "on_deliberate": 0, "missed": 0, "marked_right": 0} for k in kinds}
    spans = defaultdict(list)
    for m in marks:
        for span in _occurrences(text, m["text"]):
            spans[m["kind"]].append((span, m["flag"]))
    for f in flags:
        k = f["kind"]
        if k not in out:
            continue
        fs = (f["start"], f["end"])
        hits = [flag for span, flag in spans[k] if _overlaps(fs, span)]
        if any(hits):
            out[k]["right"] += 1
        else:
            out[k]["wrong"] += 1
            if hits:                                  # only deliberate marks under it
                out[k]["on_deliberate"] += 1
    for m in marks:
        if not m["flag"] or m["kind"] not in out:
            continue
        out[m["kind"]]["marked_right"] += 1
        if not any(f["kind"] == m["kind"] and _overlaps((f["start"], f["end"]), span)
                   for f in flags for span in _occurrences(text, m["text"])):
            out[m["kind"]]["missed"] += 1
    return out


def _add(total, part):
    for k, v in part.items():
        for kk, vv in v.items():
            total[k][kk] = total[k].get(kk, 0) + vv


def score_marked(checker, llm=None) -> Dict[str, Any]:
    data = json.loads((BENCH / "style" / "marked.json").read_text(encoding="utf-8"))
    kinds = STYLE_KINDS + ["overdescribed"]
    total: Dict[str, Dict[str, int]] = defaultdict(dict)
    for p in data["passages"]:
        flags = [f for f in checker.flags(p["text"], llm) if f["family"] == "style"]
        flags += overdescribed(p["text"], llm)
        # A passage with "scores" (P.2a) is marked only for those kinds.
        scored = [k for k in kinds if k in p["scores"]] if p.get("scores") else kinds
        _add(total, _judge_against_marks(p["text"], p["marks"], flags, scored))
    return {k: total[k] for k in kinds}


def compare_analysers() -> Dict[str, Any]:
    """style_checks and ProWritingAnalyzer on the measures both have (R.4)."""
    from src.utils import style_checks as sc
    from src.utils.writing_stats import ProWritingAnalyzer
    data = json.loads((BENCH / "style" / "marked.json").read_text(encoding="utf-8"))
    result = {"style_checks": defaultdict(dict), "ProWritingAnalyzer": defaultdict(dict)}

    def pwa_flags(text: str) -> List[Dict[str, Any]]:
        s = ProWritingAnalyzer().analyze(text)
        out = []

        def add_text(kind, snippet):
            for span in _occurrences(text, snippet)[:1] or []:
                out.append({"kind": kind, "start": span[0], "end": span[1], "text": snippet})
        for sent in s.passive_sentences or []:
            add_text("passive", sent.strip())
        for word in s.adverbs or []:
            for span in _occurrences(text, word):
                out.append({"kind": "adverb", "start": span[0], "end": span[1], "text": word})
        for phrase in s.cliches or []:
            for span in _occurrences(text.lower(), phrase.lower()):
                out.append({"kind": "cliche", "start": span[0], "end": span[1], "text": phrase})
        for sent in s.sticky_sentences or []:
            add_text("sticky_sentence", sent.strip())
        for word, first, second in s.echoes or []:
            for pos in (first, second):
                out.append({"kind": "echo", "start": pos, "end": pos + len(word), "text": word})
        return out

    for p in data["passages"]:
        if p.get("scores"):
            continue                       # marked for the P.2a kinds only
        t = p["text"]
        sc_flags = [{"kind": i.kind, "start": i.start, "end": i.end, "text": i.text}
                    for i in sc.analyze_document(t) if i.kind in SHARED]
        _add(result["style_checks"], _judge_against_marks(t, p["marks"], sc_flags, SHARED))
        _add(result["ProWritingAnalyzer"], _judge_against_marks(t, p["marks"], pwa_flags(t), SHARED))
    clean_words = 0
    clean = {"style_checks": defaultdict(int), "ProWritingAnalyzer": defaultdict(int)}
    for path in sorted((BENCH / "clean").glob("*.txt")):
        t = path.read_text(encoding="utf-8")
        clean_words += words(t)
        for i in sc.analyze_document(t):
            if i.kind in SHARED:
                clean["style_checks"][i.kind] += 1
        for f in pwa_flags(t):
            clean["ProWritingAnalyzer"][f["kind"]] += 1
    return {"marked": {k: dict(v) for k, v in result.items()},
            "clean_per_1000": {k: {kk: round(1000 * vv / clean_words, 1) for kk, vv in v.items()}
                               for k, v in clean.items()}}


# ── Report ──────────────────────────────────────────────────────────────

def precision(right: int, wrong: int) -> Optional[float]:
    return None if right + wrong == 0 else right / (right + wrong)


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(100 * x)}%"


def verdict(prec: Optional[float], clean_rate: float) -> str:
    if prec is None:
        return "not enough flags to judge" if clean_rate <= TARGET_CLEAN_RATE else "too many on clean prose"
    ok_p, ok_c = prec >= TARGET_PRECISION, clean_rate <= TARGET_CLEAN_RATE
    if ok_p and ok_c:
        return "meets both targets"
    return "; ".join(x for x in (None if ok_p else "below 4 in 5", None if ok_c else "too many on clean prose") if x)


def build_rows(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    seeded, clean, marked = res["seeded"], res["clean"], res["marked"]
    for fam, kinds in (("spelling", ["spelling"]),
                       ("grammar", ["confused_word", "agreement", "punctuation", "repeated_word"])):
        found = sum(seeded["by_mistake"].get(k, {}).get("found", 0) for k in kinds)
        missed = sum(seeded["by_mistake"].get(k, {}).get("missed", 0) for k in kinds)
        right, wrong = seeded["flags_right"].get(fam, 0), seeded["flags_wrong"].get(fam, 0)
        rows.append({"check": fam.capitalize(), "set": "seeded", "found": found, "missed": missed,
                     "right": right, "wrong": wrong, "precision": precision(right, wrong),
                     "recall": found / (found + missed) if found + missed else None,
                     "clean_per_1000": clean["per_1000"].get(fam, 0.0)})
    for kind in ("overuse", "overused_phrase"):
        rows.append({"check": {"overuse": "Overused words", "overused_phrase": "Repeated phrases"}[kind],
                     "set": "clean only", "found": None, "missed": None, "right": None, "wrong": None,
                     "precision": None, "recall": None, "clean_per_1000": clean["per_1000"].get(kind, 0.0)})
    labels = {"passive": "Passive voice", "adverb": "Adverbs", "intensifier": "Weak intensifiers",
              "wordy": "Wordy phrases", "cliche": "Clichés", "repeated_start": "Repeated sentence starts",
              "echo": "Echoes", "long_sentence": "Long sentences", "hard_sentence": "Hard-to-read sentences",
              "sticky_sentence": "Sticky sentences", "overdescribed": "Overly descriptive",
              "transition": "Few transitions", "pronoun": "Pronouns", "alliteration": "Alliteration",
              "acronym": "Acronyms"}
    for kind, label in labels.items():
        m = marked.get(kind, {})
        right, wrong = m.get("right", 0), m.get("wrong", 0)
        marked_right, missed = m.get("marked_right", 0), m.get("missed", 0)
        rows.append({"check": label, "set": "marked", "found": marked_right - missed, "missed": missed,
                     "right": right, "wrong": wrong, "on_deliberate": m.get("on_deliberate", 0),
                     "precision": precision(right, wrong),
                     "recall": (marked_right - missed) / marked_right if marked_right else None,
                     "clean_per_1000": clean["per_1000"].get(kind, 0.0)})
    for r in rows:
        r["verdict"] = verdict(r["precision"], r["clean_per_1000"])
    return rows


def worst(rows: List[Dict[str, Any]], n: int = 4) -> List[Dict[str, Any]]:
    def badness(r):
        p = r["precision"] if r["precision"] is not None else 1.0
        return (1 - p) + max(0.0, r["clean_per_1000"] - TARGET_CLEAN_RATE) / 10
    return sorted(rows, key=badness, reverse=True)[:n]


def to_markdown(res: Dict[str, Any], rows: List[Dict[str, Any]], with_model: Optional[Dict] = None) -> str:
    def cell(x):
        return "—" if x is None else str(x)
    lines = [
        "# How good are the checks?",
        "",
        f"Written by `scripts/score_checks.py` (piece Q.2) on {res['date']}. Rerun it after any",
        "change to a check and compare with this table. The numbers are also in",
        "`check_scores.json`.",
        "",
        "**What the benchmark is** (`benchmark/`, piece Q.1):",
        "",
        f"- **seeded**: {res['seeded_count']} passages of published prose with "
        f"{res['insertion_count']} known mistakes inserted;",
        f"- **clean**: the same {res['clean']['words']:,} words untouched, where nearly every flag is a false alarm;",
        f"- **marked**: {res['marked_passages']} short passages with every style problem marked by hand, "
        "including deliberate choices where a flag would be wrong.",
        "",
        "Checks run as the editor shows them, with its quick rules for dialogue and names, "
        + ("with LanguageTool." if res["languagetool"] else "**without LanguageTool**, "
           "so grammar is the built-in rules only (run with `--languagetool` to include it)."),
        "",
        f"**Targets** (open decision 3, provisional): at least **4 in 5 flags right** "
        f"({round(100 * TARGET_PRECISION)}%), and no more than **{TARGET_CLEAN_RATE:g} flags per "
        "1,000 words** on clean prose.",
        "",
        "| Check | Scored on | Found | Missed | Flags right | Flags wrong | Right (precision) | Found (recall) | Clean prose, per 1,000 words | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['set']} | {cell(r['found'])} | {cell(r['missed'])} | "
                     f"{cell(r['right'])} | {cell(r['wrong'])} | {_pct(r['precision'])} | "
                     f"{_pct(r['recall'])} | {r['clean_per_1000']} | {r['verdict']} |")
    lines += ["", "## The worst checks", ""]
    for r in worst(rows):
        lines.append(f"- **{r['check']}**: {_pct(r['precision'])} of flags right, "
                     f"{r['clean_per_1000']} flags per 1,000 words of clean prose ({r['verdict']}).")
    seeded = res["seeded"]
    lines += ["", "## Seeded mistakes, by kind", "",
              "| Kind of mistake | Found | Missed | Examples missed |", "|---|---|---|---|"]
    for kind, v in sorted(seeded["by_mistake"].items()):
        ex = ", ".join(f"“{e}”" for e in seeded["missed_examples"].get(kind, [])[:4]) or "—"
        lines.append(f"| {kind.replace('_', ' ')} | {v['found']} | {v['missed']} | {ex} |")
    lines += ["", "## On clean published prose", "",
              f"{res['clean']['words']:,} words from twelve books (Gatsby, Styles, Call of the Wild …).",
              "", "| Flag | Count | Per 1,000 words | Examples |", "|---|---|---|---|"]
    for kind, n in sorted(res["clean"]["counts"].items(), key=lambda kv: -kv[1]):
        ex = ", ".join(f"“{e}”" for e in res["clean"]["examples"].get(kind, [])[:3])
        lines.append(f"| {kind} | {n} | {res['clean']['per_1000'][kind]} | {ex} |")
    a = res["analysers"]
    lines += ["", "## The two style analysers side by side (for R.4)", "",
              "On the measures both have. Precision and recall on the marked passages; rate on clean prose.",
              "",
              "**Since R.4** `ProWritingAnalyzer` (the Critique's numbers) calls `style_checks` for all "
              "five, so each check exists once. The columns still differ only because the Critique keeps "
              "whole sentences (passive, sticky) and distinct words (adverbs) where the editor marks each "
              "word, and this report counts what each one lists.",
              "", "| Measure | style_checks: right | recall | clean per 1,000 | ProWritingAnalyzer: right | recall | clean per 1,000 | Better |",
              "|---|---|---|---|---|---|---|---|"]
    for k in SHARED:
        s, w = a["marked"]["style_checks"].get(k, {}), a["marked"]["ProWritingAnalyzer"].get(k, {})
        sp, wp = precision(s.get("right", 0), s.get("wrong", 0)), precision(w.get("right", 0), w.get("wrong", 0))
        sr = None if not s.get("marked_right") else (s["marked_right"] - s["missed"]) / s["marked_right"]
        wr = None if not w.get("marked_right") else (w["marked_right"] - w["missed"]) / w["marked_right"]
        sc_rate = a["clean_per_1000"]["style_checks"].get(k, 0.0)
        pw_rate = a["clean_per_1000"]["ProWritingAnalyzer"].get(k, 0.0)
        better = _better(sp, sr, sc_rate, wp, wr, pw_rate)
        lines.append(f"| {k} | {_pct(sp)} | {_pct(sr)} | {sc_rate} | {_pct(wp)} | {_pct(wr)} | {pw_rate} | {better} |")
    if with_model is not None:
        lines += ["", "## With the configured model judging", ""]
        if with_model.get("unavailable"):
            lines.append(f"Not run: {with_model['unavailable']}")
        else:
            lines += ["| Check | Right without model | Right with model | Clean per 1,000 without | with |",
                      "|---|---|---|---|---|"]
            for r0, r1 in zip(rows, with_model["rows"]):
                lines.append(f"| {r0['check']} | {_pct(r0['precision'])} | {_pct(r1['precision'])} | "
                             f"{r0['clean_per_1000']} | {r1['clean_per_1000']} |")
    lines += ["", "## Limits", "",
              "- The marked set is small (a few dozen marks) and its marks are one editor's judgment, "
              "a draft for the writer to review. A single flag moves a style check's score a lot.",
              "- The seeded mistakes are typical ones, inserted one of each kind per passage; real "
              "drafts make other mistakes too.",
              "- The clean prose is 1898–1925 English. Period spellings and punctuation can draw flags "
              "that modern prose would not.",
              ""]
    return "\n".join(lines)


def _better(sp, sr, sc_rate, wp, wr, pw_rate) -> str:
    def score(p, r, rate):
        return (p or 0) + (r or 0) - rate / 20
    a, b = score(sp, sr, sc_rate), score(wp, wr, pw_rate)
    if abs(a - b) < 0.05:
        return "about the same"
    return "style_checks" if a > b else "ProWritingAnalyzer"


def run(languagetool: bool = False, llm=None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    checker = Checker(languagetool)
    marked = json.loads((BENCH / "style" / "marked.json").read_text(encoding="utf-8"))
    seeded_files = sorted((BENCH / "seeded").glob("*.json"))
    res = {
        "date": time.strftime("%Y-%m-%d"),
        "languagetool": languagetool,
        "model": llm is not None,
        "seeded_count": len(seeded_files),
        "insertion_count": sum(len(json.loads(p.read_text())["insertions"]) for p in seeded_files),
        "marked_passages": len(marked["passages"]),
        "seeded": score_seeded(checker, llm),
        "clean": score_clean(checker, llm),
        "marked": score_marked(checker, llm),
    }
    res["analysers"] = compare_analysers()
    return res, build_rows(res)


def _model():
    try:
        from src.ai.task_llm import build_critique_llm
        return build_critique_llm()
    except Exception as e:
        print(f"  [model] {e}")
        return None


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Score the checks against the benchmark.")
    ap.add_argument("--model", action="store_true", help="also run with the configured model judging")
    ap.add_argument("--languagetool", action="store_true", help="include LanguageTool (needs Java)")
    ap.add_argument("--no-write", action="store_true", help="print only; do not update docs/")
    args = ap.parse_args(argv)
    started = time.time()
    res, rows = run(args.languagetool)
    with_model = None
    if args.model:
        llm = _model()
        if llm is None:
            with_model = {"unavailable": "no model is configured."}
        else:
            res_m, rows_m = run(args.languagetool, llm)
            with_model = {"rows": rows_m}
            res["with_model"] = {"rows": rows_m}
    res["rows"] = rows
    md = to_markdown(res, rows, with_model)
    if not args.no_write:
        OUT_MD.write_text(md, encoding="utf-8")
        OUT_JSON.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str) + "\n",
                            encoding="utf-8")
    for r in rows:
        print(f"{r['check']:26} right {_pct(r['precision']):>5}  found {_pct(r['recall']):>5}  "
              f"clean {r['clean_per_1000']:>5}/1k  {r['verdict']}")
    print(f"Worst: {', '.join(r['check'] for r in worst(rows))}")
    print(f"Done in {time.time() - started:.0f} s" + ("" if args.no_write else f"; wrote {OUT_MD.relative_to(ROOT)}"))
    sys.stdout.flush()
    if args.languagetool:                 # don't leave its Java server running
        try:
            from src.utils.proofing import LanguageToolEngine
            LanguageToolEngine.get().close()
        except Exception as e:
            print(f"  [languagetool] could not close: {e}")
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
