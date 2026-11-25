"""A model judges the readiness checks' candidates (piece 1.7).

The scans are deliberately eager: every adverb, every unknown word, every
sentence that *might* tell instead of show. With a model, each stage's
candidates in a chapter go to it in **one request**, each with its
sentence, and it answers per item:

* **REAL**: a problem a good editor would fix. The item is confirmed.
* **FINE**: a false alarm (deliberate style, dialogue, dialect, a name, one
  of the author's own habits). The item is kept, marked "cleared", with the
  model's reason, and stops counting.

The author's voice reading (``voice_profile``), when there is one, goes in
the prompt so their deliberate habits are let through. Local models get a
shorter prompt and fewer items. A failed or unreadable reply leaves the
scan's result as it was.

Near-certain mechanical flags (a doubled word, a space before a comma, and
subject–verb agreement outside dialogue) are not sent: there is nothing for
a model to weigh, and it can only clear a real mistake
(``docs/publishing/miss_rates.md``: the model cleared a narrated "you was").
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_ITEMS = 40               # per stage per chapter (cloud models)
MAX_ITEMS_COMPACT = 20       # on-device models
LAZY_SHARE = 0.9             # a model that clears nearly everything isn't trusted
SURE_RULES = frozenset({"REPEATED_WORD", "SPACE_BEFORE_PUNCT", "SPACE_AFTER_PUNCT",
                        "SPACE_AFTER_PERIOD", "DOUBLE_SPACE", "LOWERCASE_I"})


NARRATION_SURE_RULES = frozenset({"AGREEMENT"})    # "you was": dialect only in speech


def in_dialogue(text: str, start: int) -> bool:
    """Whether ``start`` falls inside quoted speech in its paragraph."""
    para_start = text.rfind("\n", 0, start) + 1
    before = text[para_start:start]
    if "“" in before or "”" in before:
        return before.count("“") > before.count("”")
    return before.count('"') % 2 == 1


def is_sure(item: Any, text: str = "") -> bool:
    """A rule flag that is right whenever it fires; the model doesn't judge
    it. Agreement ("you was") is sure in narration; in speech it may be the
    character's dialect, so there the model judges it."""
    parts = str(getattr(item, "key", "") or "").split(":")
    if len(parts) < 2 or parts[0] != "grammar":
        return False
    if parts[1] in SURE_RULES:
        return True
    return (parts[1] in NARRATION_SURE_RULES and bool(text)
            and not in_dialogue(text, getattr(item, "start", 0)))

SYSTEM = ("You are an experienced fiction editor reviewing an automatic checker's flags in "
          "one chapter. You keep real problems a good editor would fix, and clear false "
          "alarms: deliberate style, dialogue and dialect, names and invented words, and the "
          "author's own stated habits.")

STAGE_WORDS = {"line": "sentence-level style", "copyedit": "spelling, grammar and consistency",
               "scene": "dialogue", "structure": "structure", "proof": "proofreading"}

_LINE = re.compile(r"^\s*\**\s*(\d+)\s*[.):]?\s*\**\s*(?:[“\"'][^”\"'\n]*[”\"']\s*[—:\-–]?\s*)?"
                   r"\**\s*(REAL|FINE|KEEP|DROP|PROBLEM|OK|CLEAR|CLEARED)\b\**\s*[—:\-–]*\s*(.*)$",
                   re.I | re.M)


def sentence_around(text: str, start: int, end: int, reach: int = 220) -> str:
    """The sentence holding ``text[start:end]``, trimmed."""
    if not text or not (0 <= start < end <= len(text)):
        return ""
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(rights) + 1 if rights else len(text)
    left = max(left, start - reach)
    right = min(right, end + reach)
    return " ".join(text[left:right].split())


def voice_block(project: Any, scope: Optional[str]) -> str:
    """The author's stored voice reading, as context (no model call)."""
    try:
        from src.ai import voice_profile
        if not voice_profile.ai_enabled():
            return ""
        entry = voice_profile.cached(project, scope)
    except Exception:
        return ""
    if not entry:
        return ""
    bits = [f"The author's voice: {entry.get('voice', '')} {entry.get('style', '')}".strip()]
    habits = entry.get("habits") or []
    if habits:
        bits.append("Deliberate habits of this author (FINE unless clearly harmful here): "
                    + "; ".join(habits))
    return "\n".join(bits)


def candidates(stage_results: Sequence[Tuple[Any, Any]], text: str, limit: int) -> List[Dict]:
    """[{n, spec, item, sentence}] for one stage: items with a place in the
    text, most important checks first, up to ``limit``."""
    out = []
    ordered = sorted(stage_results, key=lambda sr: -sr[0].weight)
    for spec, result in ordered:
        for item in result.items:
            if item.verdict or item.end <= item.start or item.chapter_id or is_sure(item, text):
                continue
            out.append({"spec": spec, "item": item,
                        "sentence": sentence_around(text, item.start, item.end) or item.text})
            if len(out) >= limit:
                return out
    return out


def build_prompt(stage: str, cands: List[Dict], context: str = "", compact: bool = False) -> str:
    lines = []
    for n, c in enumerate(cands, 1):
        spec, item = c["spec"], c["item"]
        reason = "" if compact else f" — {item.reason[:90]}"
        flagged = item.text if len(item.text) <= 80 else item.text[:77] + "…"
        sentence = c["sentence"] if c["sentence"] != item.text else ""
        lines.append(f"{n}. [{spec.label}] “{flagged}”{reason}"
                     + (f": «{sentence}»" if sentence else ""))
    head = (f"{context.strip()}\n\n" if context.strip() else "")
    return (head + f"Flags from an automatic {STAGE_WORDS.get(stage, stage)} checker, each "
            "with its sentence. For each, would a skilled editor change it (REAL), or is it "
            "fine as written (FINE)?\n\n" + "\n".join(lines) + "\n\n"
            "Answer one line per item, in order, nothing else:\n"
            "1. REAL — <why, under 12 words>\n2. FINE — <why, under 12 words>")


def parse(reply: str, count: int) -> Dict[int, Tuple[bool, str]]:
    """{item index: (real, why)} from the model's lines."""
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply or "")
    except Exception:
        reply = reply or ""
    out: Dict[int, Tuple[bool, str]] = {}
    for m in _LINE.finditer(reply):
        n = int(m.group(1)) - 1
        if 0 <= n < count and n not in out:
            real = m.group(2).upper() in ("REAL", "KEEP", "PROBLEM")
            out[n] = (real, m.group(3).strip().strip("*_ ").rstrip("."))
    return out


def judge_stage(llm: Any, stage: str, stage_results, text: str, context: str = "",
                compact: bool = False) -> int:
    """Judge one stage's candidates in place; returns how many were judged
    (0 when the model failed or gave nothing usable)."""
    cands = candidates(stage_results, text, MAX_ITEMS_COMPACT if compact else MAX_ITEMS)
    if not cands:
        return 0
    try:
        reply = llm.generate_text(build_prompt(stage, cands, context, compact), SYSTEM,
                                  max_tokens=40 + 24 * len(cands), temperature=0.2)
    except Exception as e:
        print(f"[readiness] model judging failed ({stage}): {e}")
        return 0
    if (reply or "").startswith("Error generating text:"):
        print(f"[readiness] model judging failed ({stage}): {reply[:160]}")
        return 0
    verdicts = parse(reply, len(cands))
    if not verdicts:
        return 0
    fine = sum(1 for real, _ in verdicts.values() if not real)
    if len(verdicts) >= 8 and fine > LAZY_SHARE * len(verdicts):
        print(f"[readiness] the model cleared {fine}/{len(verdicts)} ({stage}); keeping the scan")
        return 0
    for n, (real, why) in verdicts.items():
        item = cands[n]["item"]
        item.verdict = "problem" if real else "cleared"
        item.note = why
    return len(verdicts)
