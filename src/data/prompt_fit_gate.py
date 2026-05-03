"""Cheap heuristic gate that drops obvious misfit training pairs at export.

Sits between :meth:`RephraseDatabase._format_row` and the JSONL writer.
For each pair it checks a small set of cheap rules and returns either
``None`` (keep the row) or a short ``reason`` string (drop the row,
counted against that reason in an aggregate report the caller can log).

Rules in priority order:

  1. **Refusal** — output is a generic LLM refusal template
     ("I'm sorry, but I can't…", "As an AI…"). These show up in
     scraped corpora and teach the model to refuse, which is the
     opposite of what fine-tuning a creative writing model needs.
  2. **Tool-call JSON** — output is a raw function/tool call
     payload that escaped the dataset's adapter. The model would
     learn to emit JSON instead of prose.
  3. **Trivially short** — output under ~12 characters of letters.
     Almost always a stub or stripped row.
  4. **Shape-aware semantic gates** — cheap content checks that
     each shape's family expects:

       * ``summarization`` — drop pairs where the summary shares
         essentially zero bigrams with the source. A real summary
         recycles most of the source's words; near-zero overlap
         means the "summary" isn't about the source.
       * ``rephrase_like`` — drop pairs where source and output
         are byte-for-byte identical (zero-information pair) or
         the bigram overlap is near zero (meaningfully different
         content rather than a paraphrase).
       * ``continuation`` — drop pairs where the output starts
         with meta-prose ("Here's a continuation:", "Sure, ...")
         that suggests the row is an instruction-following trace,
         not raw continuation prose.

The gate is intentionally conservative — it only catches things
that are *clearly* broken. Subtler mis-fits are the cluster audit's
job (which surfaces them for human review rather than auto-dropping).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ── Refusal detection ────────────────────────────────────────
#
# Each pattern is matched against the *first ~200 chars* of the
# output (refusals always front-load). Patterns are deliberately
# narrow — we want to catch templated refusals, not creative prose
# that happens to use the word "sorry" mid-paragraph.

_REFUSAL_PREFIXES = [
    re.compile(r"^\s*i'?m\s+(?:sorry|afraid)[,.\s]+(?:but\s+)?"
               r"(?:i\s+)?(?:can'?t|cannot|am\s+not\s+able\s+to)\b",
               re.I),
    re.compile(r"^\s*as\s+an?\s+(?:ai|llm|language\s+model|"
               r"assistant)[,.\s]", re.I),
    re.compile(r"^\s*(?:unfortunately|regrettably)[,.\s]+"
               r"(?:i\s+)?(?:can'?t|cannot|won'?t)\b", re.I),
    re.compile(r"^\s*i\s+(?:can'?t|cannot)\s+(?:help|assist|"
               r"comply|provide|generate|write|create|produce)\b",
               re.I),
    re.compile(r"^\s*i\s+(?:don'?t|do\s+not)\s+feel\s+comfortable\b",
               re.I),
    re.compile(r"^\s*i\s+must\s+(?:decline|refuse)\b", re.I),
    re.compile(r"^\s*sorry[,.\s]+(?:but\s+)?(?:i\s+)?"
               r"(?:can'?t|cannot)\b", re.I),
]


def is_refusal(text: str) -> bool:
    head = (text or "")[:200]
    return any(p.search(head) for p in _REFUSAL_PREFIXES)


# ── Tool-call / structured-output JSON detection ─────────────
#
# Catches scraped agent traces whose adapter passed the raw JSON
# tool-call through as the assistant turn. Pattern: starts with ``{``
# and contains one of the tool-call key names within the first ~150
# chars. We don't try to fully parse — even a partial JSON-shaped
# output is a strong signal.

_TOOL_CALL_KEYS = re.compile(
    r'"(?:tool_calls?|function_call|tool_use|name|arguments|args)"'
    r'\s*:', re.I)


def is_tool_call_json(text: str) -> bool:
    head = (text or "").lstrip()[:300]
    if not head.startswith("{") and not head.startswith("["):
        return False
    return bool(_TOOL_CALL_KEYS.search(head))


# ── Trivial / empty output ───────────────────────────────────
#
# Output that's mostly whitespace or punctuation, or has fewer than
# ~12 letter characters total. The lower bound is loose — a
# legitimate one-word completion ("yes", "no", a name) shouldn't
# trip it. Anything below that is a stub.


_LETTER_RE = re.compile(r"[A-Za-z]")


def is_too_short(text: str, *, min_letters: int = 12) -> bool:
    if not text:
        return True
    n_letters = sum(1 for _ in _LETTER_RE.finditer(text))
    return n_letters < min_letters


# ── Bigram overlap (Jaccard) ────────────────────────────────
#
# Word-level bigrams (lowercased, alphanumeric tokens) are a cheap
# proxy for "do these two strings share content?" — used by the
# shape-aware gates below to spot summaries that don't summarise
# anything in the source, and rephrases whose output isn't actually
# a paraphrase.

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _bigrams(text: str):
    toks = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    return {f"{a} {b}" for a, b in zip(toks, toks[1:])}


def bigram_overlap(a: str, b: str) -> float:
    """Jaccard overlap of word-level bigrams. 0.0–1.0."""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


# ── Shape-aware semantic gates ───────────────────────────────


_CONTINUATION_META_PREFIXES = re.compile(
    r"^\s*(?:here'?s\s+(?:a|the)\s+continuation|"
    r"sure[,.\s]|certainly[,.\s]|"
    r"continuing\s+from\s+where|"
    r"i'?ll\s+(?:continue|pick\s+up))",
    re.I)


def _shape_gate(src: str, out: str, shape: str) -> Optional[str]:
    """Per-shape semantic checks. Returns drop reason or None."""
    if shape == "summarization":
        # A summary should share most of its bigrams with the
        # source — it's recycling source words to compress them.
        # Threshold is lax (0.02) because a heavy paraphrase
        # summary can drift; near-zero means the pair is unrelated.
        if bigram_overlap(src, out) < 0.02:
            return "summarization-no-content-overlap"
        return None
    if shape == "rephrase_like":
        if (src or "").strip() == (out or "").strip():
            return "rephrase-identical-output"
        # The bigram-overlap check is unreliable on short
        # paraphrases — a one-sentence rewrite that swaps every
        # content word ("cat→feline, mat→rug, morning sun→dawn")
        # can legitimately produce zero shared bigrams. Only apply
        # the gate when both sides are long enough that some shared
        # bigrams are essentially guaranteed in a real paraphrase
        # (proper nouns, function-word collocations, etc.).
        if len(src or "") >= 300 and len(out or "") >= 300:
            if bigram_overlap(src, out) < 0.02:
                return "rephrase-no-content-overlap"
        return None
    if shape == "continuation":
        if _CONTINUATION_META_PREFIXES.search(out or ""):
            return "continuation-instruction-meta-prefix"
        return None
    return None


# ── Aggregate report ─────────────────────────────────────────


@dataclass
class GateReport:
    """Counts per drop reason. Caller logs the summary at export end."""
    kept: int = 0
    dropped: int = 0
    reasons: Counter = field(default_factory=Counter)

    def record(self, reason: Optional[str]) -> None:
        if reason is None:
            self.kept += 1
        else:
            self.dropped += 1
            self.reasons[reason] += 1

    def summary_lines(self) -> list:
        if self.dropped == 0:
            return [f"prompt-fit gate: kept {self.kept:,}; "
                    f"dropped 0."]
        out = [f"prompt-fit gate: kept {self.kept:,}; "
               f"dropped {self.dropped:,}:"]
        for reason, n in self.reasons.most_common():
            out.append(f"  • {reason:<38}  {n:>5,}")
        return out


# ── Public entry point ───────────────────────────────────────


def evaluate_pair(*, src: str, out: str,
                  source_type: str, shape: str) -> Optional[str]:
    """Return a drop ``reason`` string or ``None`` to keep the row.

    Reasons are short stable identifiers (used as Counter keys) so
    the export log can summarise drops by category. The actual
    text shown to the user can be derived from the reason when
    needed; the gate itself stays headless.
    """
    if is_refusal(out):
        return "refusal-template"
    if is_tool_call_json(out):
        return "tool-call-json"
    if is_too_short(out):
        return "output-too-short"
    return _shape_gate(src, out, shape)
