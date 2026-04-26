"""Pre-training corpus quality check.

Runs after the user clicks Start Training but BEFORE the GPU work
kicks off. Three goals:

  1. **Show what will actually be trained on.** Most training
     surprises come from the user not realising what's in the
     dataset — wrong intent, near-duplicates, dominated by one
     source. Surface concrete numbers and sample passages so the
     user can sanity-check the recipe before paying for it.
  2. **Catch insufficient or damaged corpora.** The retroactive
     cleaner can over-prune; legacy data may have been ingested
     with bad delimiters; a "voice" intent on 20 rows is a waste
     of money. Deterministic rules flag these before training.
  3. **Honest assessment from an LLM** when one's configured —
     "is this dataset actually good for the task?" The LLM sees
     stats + samples and produces a verdict with concrete reasons.
     Falls back to deterministic-only when no LLM is available.

**Public API**:

  * :class:`CorpusStats` — what the deterministic pass measures.
  * :class:`Verdict` — pass/warn/fail + reasoning. The dialog
    renders one verdict from the deterministic pass and (when
    available) a second verdict from the LLM.
  * :func:`compute_stats` — deterministic stats from the JSONL.
  * :func:`deterministic_verdict` — rules-based assessment.
  * :func:`llm_verdict` — LLM-based assessment. Caller passes the
    LLMClient (already constructed elsewhere) so this module
    stays import-safe without LLM dependencies.
  * :func:`sample_passages` — pull N random rows for the dialog.

**What the dialog never decides**: the user's final go/no-go.
Verdicts can warn or fail, but the dialog still has a "Continue
anyway" button — we don't gatekeep someone who wants to do
something the heuristics think is unwise. We just make sure they
saw the warning.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Stats ──────────────────────────────────────────────────


@dataclass
class CorpusStats:
    """Deterministic measurements of a dataset JSONL.

    All fields are derived from a single sequential read of the
    JSONL file the trainer is about to consume — same data, no
    risk of drift between what we report and what gets trained on.
    """
    n_rows: int = 0
    by_source: Dict[str, int] = field(default_factory=dict)
    by_intent: Dict[str, int] = field(default_factory=dict)
    # Length distributions (in characters) for the user-message side
    # (what the model sees as input) and the assistant side (what it
    # learns to produce). Both matter — short prompts with long
    # responses train differently than balanced.
    user_lens: List[int] = field(default_factory=list)
    output_lens: List[int] = field(default_factory=list)
    # Uniqueness — how many rows have a one-of-a-kind opening N
    # tokens. Catches duplicate paragraphs from over-aggressive
    # corpus expansion.
    n_unique_openers: int = 0
    n_duplicate_openers: int = 0
    # Type-token ratio over the assistant outputs. ~0.5 is rich
    # prose; <0.2 is rote / templatey / repetitive.
    type_token_ratio: float = 0.0
    # % of rows whose output is shorter than 80 chars or longer
    # than 2500. Length filtering already happens in the cleaner,
    # so high values here mean either the cleaner was bypassed or
    # the user has weird custom data.
    pct_too_short: float = 0.0
    pct_too_long: float = 0.0
    # Genre / tone tag overlap with the user's selection. None when
    # the user didn't pick any genres/tones.
    pct_matching_genres: Optional[float] = None
    pct_matching_tones: Optional[float] = None
    # Voice/style tag presence — surfaced because voice intents
    # need voice-tagged corpus rows; if 0% of rows have a voice
    # tag, training a "voice" model will fall back to whatever
    # generic style the corpus authors had.
    n_voice_tagged: int = 0
    # Sample passages for the dialog. Stored here so the caller
    # doesn't have to re-read the JSONL.
    samples: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def median_user_len(self) -> int:
        return int(_percentile(self.user_lens, 50))

    @property
    def median_output_len(self) -> int:
        return int(_percentile(self.output_lens, 50))

    @property
    def p10_output_len(self) -> int:
        return int(_percentile(self.output_lens, 10))

    @property
    def p90_output_len(self) -> int:
        return int(_percentile(self.output_lens, 90))

    @property
    def pct_unique_openers(self) -> float:
        total = self.n_unique_openers + self.n_duplicate_openers
        return (self.n_unique_openers / total * 100.0) if total else 0.0


def _percentile(values: List[int], pct: float) -> float:
    """Cheap percentile without numpy. ``values`` may be empty."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100.0
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return (sorted_vals[f] * (c - k)
            + sorted_vals[c] * (k - f))


# ── Compute stats from JSONL ───────────────────────────────


def compute_stats(jsonl_path: Path, *,
                  selected_genres: Optional[List[str]] = None,
                  selected_tones: Optional[List[str]] = None,
                  n_samples: int = 5,
                  rng_seed: int = 42,
                  ) -> CorpusStats:
    """Single-pass scan of the dataset JSONL.

    Yields a :class:`CorpusStats` ready for the deterministic
    verdict + dialog rendering. Works on the JSONL the trainer
    will actually read, not the raw DB — so the numbers reflect
    rating filter + source-type filter + oversample.

    ``selected_genres`` / ``selected_tones`` are the user's
    Step-1 picks; we report the percentage of rows whose metadata
    overlaps. ``None`` skips the comparison.
    """
    stats = CorpusStats()
    rng = random.Random(rng_seed)
    reservoir: List[Dict[str, Any]] = []

    # Token-level accumulators for the type-token ratio.
    total_tokens = 0
    unique_tokens: set = set()

    # Opener tracking — first 80 chars of the user-side text.
    openers_seen: set = set()
    duplicate_count = 0
    unique_count = 0

    selected_genres_set = set(selected_genres or [])
    selected_tones_set = set(selected_tones or [])
    matching_genre_rows = 0
    matching_tone_rows = 0
    rows_with_genre_metadata = 0
    rows_with_tone_metadata = 0

    if not Path(jsonl_path).exists():
        return stats

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            stats.n_rows += 1

            # Reservoir sampling for the dialog.
            if len(reservoir) < n_samples:
                reservoir.append(rec)
            else:
                idx = rng.randint(0, stats.n_rows - 1)
                if idx < n_samples:
                    reservoir[idx] = rec

            # Source / intent counts come from the record's
            # metadata block, which the DB exporter populates.
            meta = rec.get("metadata") or {}
            st = (meta.get("source_type")
                  or rec.get("source_type") or "unknown")
            stats.by_source[st] = stats.by_source.get(st, 0) + 1
            ftype = (meta.get("format_type")
                     or rec.get("format_type") or "instruction")
            stats.by_intent[ftype] = stats.by_intent.get(ftype, 0) + 1

            # Length distributions. We use Alpaca-format records
            # (instruction + input + output); for chat-format
            # records (with 'messages'), use the assistant turn.
            user_len, output_len = _row_text_lengths(rec)
            stats.user_lens.append(user_len)
            stats.output_lens.append(output_len)
            if output_len < 80:
                stats.pct_too_short += 1
            elif output_len > 2500:
                stats.pct_too_long += 1

            # Opener uniqueness — first 80 chars of user-side text.
            opener = _row_opener(rec)
            if opener:
                if opener in openers_seen:
                    duplicate_count += 1
                else:
                    openers_seen.add(opener)
                    unique_count += 1

            # Type-token accounting on assistant outputs.
            output_text = _row_output(rec)
            if output_text:
                tokens = _tokenize(output_text)
                total_tokens += len(tokens)
                unique_tokens.update(tokens)

            # Genre / tone match.
            row_genre = (meta.get("genre")
                         or rec.get("genre") or "").lower()
            row_voice = (meta.get("voice")
                         or rec.get("voice") or "").strip()
            row_notes = (meta.get("notes")
                         or rec.get("notes") or "")

            if row_genre:
                rows_with_genre_metadata += 1
                if any(g.lower() in row_genre
                       for g in selected_genres_set):
                    matching_genre_rows += 1

            # Tones live in notes for now (synthesized=tone /
            # tone=grimdark in the notes string), so do a contains
            # check rather than a strict field lookup.
            if selected_tones_set and row_notes:
                rows_with_tone_metadata += 1
                if any(t.lower() in row_notes.lower()
                       for t in selected_tones_set):
                    matching_tone_rows += 1

            if row_voice:
                stats.n_voice_tagged += 1

    if stats.n_rows == 0:
        return stats

    # Finalize ratios and percentages.
    stats.pct_too_short = stats.pct_too_short / stats.n_rows * 100.0
    stats.pct_too_long = stats.pct_too_long / stats.n_rows * 100.0
    stats.n_unique_openers = unique_count
    stats.n_duplicate_openers = duplicate_count
    stats.type_token_ratio = (
        len(unique_tokens) / total_tokens if total_tokens else 0.0)

    if selected_genres_set and rows_with_genre_metadata:
        stats.pct_matching_genres = (
            matching_genre_rows / rows_with_genre_metadata * 100.0)
    if selected_tones_set and rows_with_tone_metadata:
        stats.pct_matching_tones = (
            matching_tone_rows / rows_with_tone_metadata * 100.0)

    stats.samples = reservoir
    return stats


def _row_text_lengths(rec: Dict[str, Any]) -> Tuple[int, int]:
    """Return ``(user_chars, output_chars)`` for one record."""
    if "messages" in rec and isinstance(rec["messages"], list):
        user_text = ""; assistant_text = ""
        for msg in rec["messages"]:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "user":
                user_text += content + "\n"
            elif role == "assistant":
                assistant_text = content
        return len(user_text), len(assistant_text)
    instr = rec.get("instruction") or ""
    inp = rec.get("input") or ""
    out = rec.get("output") or ""
    return len((instr + " " + inp).strip()), len(out)


def _row_opener(rec: Dict[str, Any]) -> str:
    """First 80 chars of the user-side text — a stable hash key
    for "is this row a duplicate of one we've already seen"."""
    if "messages" in rec and isinstance(rec["messages"], list):
        for msg in rec["messages"]:
            if msg.get("role") == "user":
                return (msg.get("content") or "")[:80].strip()
        return ""
    inp = rec.get("input") or ""
    if inp:
        return inp[:80].strip()
    return (rec.get("instruction") or "")[:80].strip()


def _row_output(rec: Dict[str, Any]) -> str:
    if "messages" in rec and isinstance(rec["messages"], list):
        for msg in reversed(rec["messages"]):
            if msg.get("role") == "assistant":
                return msg.get("content") or ""
        return ""
    return rec.get("output") or ""


def _tokenize(text: str) -> List[str]:
    """Lowercased word tokens — coarse but sufficient for
    type-token ratio measurement."""
    return re.findall(r"[a-z][a-z']*", text.lower())


def sample_passages(stats: CorpusStats, n: int = 3) -> List[Dict[str, str]]:
    """Render N samples from the stats reservoir into a UI-friendly
    ``{user, assistant}`` shape."""
    out: List[Dict[str, str]] = []
    for rec in stats.samples[:n]:
        if "messages" in rec:
            user = ""; asst = ""
            for msg in rec["messages"]:
                if msg.get("role") == "user":
                    user = msg.get("content") or ""
                elif msg.get("role") == "assistant":
                    asst = msg.get("content") or ""
            out.append({"user": user, "assistant": asst})
        else:
            user = (rec.get("instruction") or "").strip()
            inp = (rec.get("input") or "").strip()
            if inp:
                user = (user + "\n\n" + inp).strip()
            out.append({"user": user,
                        "assistant": (rec.get("output") or "").strip()})
    return out


# ── Verdicts ───────────────────────────────────────────────


@dataclass
class Verdict:
    """A single assessment, deterministic or LLM-derived.

    ``severity`` is one of:
      * ``"pass"`` — looks fine, training will go ahead cleanly.
      * ``"warn"`` — concerns flagged; user should consider
        cleaning / adding data, but training won't fail.
      * ``"fail"`` — likely to produce a poor or broken model.
        Training is still allowed (the user might have a reason)
        but the dialog defaults to Cancel.

    ``reasons`` is the list of "what's wrong". Each reason is a
    short user-facing string like *"Only 18 rows for a voice
    intent — voice fine-tunes need 200+ for stable acquisition."*
    """
    severity: str
    summary: str
    reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    source: str = "deterministic"  # or "llm"

    @property
    def color(self) -> str:
        return {
            "pass": "#16a34a",   # green
            "warn": "#b45309",   # amber
            "fail": "#b91c1c",   # red
        }.get(self.severity, "#6b7280")

    @property
    def emoji(self) -> str:
        return {"pass": "✅", "warn": "⚠️", "fail": "🛑"}.get(
            self.severity, "•")


# Per-intent minimum row counts — below these, training is
# unlikely to produce a coherent model, regardless of how clean
# the data is. These are conservative; users with high-quality
# small corpora can still proceed but we'll flag it.
_MIN_ROWS_BY_INTENT = {
    "voice": 100,        # voice acquisition needs many examples
    "rephrase": 60,
    "plot": 40,
    "worldbuilding": 30,
    "character": 30,
    "chat": 50,
    "general": 50,
}


def deterministic_verdict(stats: CorpusStats, *,
                           intent: str = "general") -> Verdict:
    """Apply rules to ``stats`` and return a verdict.

    Rules are intentionally conservative — fail when the data is
    *very* unlikely to produce a usable model, warn when there
    are concerns, pass when the deterministic checks find nothing
    obviously wrong. The LLM verdict (when available) provides the
    qualitative judgement on top of these quantitative checks.
    """
    reasons: List[str] = []
    suggestions: List[str] = []
    severity = "pass"

    intent_norm = (intent or "general").lower()
    min_rows = _MIN_ROWS_BY_INTENT.get(intent_norm, 30)

    # Hard fail: too few rows.
    if stats.n_rows < min_rows // 2:
        severity = "fail"
        reasons.append(
            f"Only {stats.n_rows} rows. The {intent_norm} intent "
            f"typically needs {min_rows}+ for stable training; "
            f"this run will overfit or memorize.")
        suggestions.append(
            "Add more data: ingest more corpora, lower the rating "
            "filter, or include more source types.")
    elif stats.n_rows < min_rows:
        severity = _bump(severity, "warn")
        reasons.append(
            f"{stats.n_rows} rows is below the recommended "
            f"minimum ({min_rows}) for the {intent_norm} intent — "
            f"the model may produce inconsistent output.")
        suggestions.append(
            "Consider adding 1-2 more genre corpora, or accept "
            "more rows by lowering the rating filter to 'good'.")

    # Heavy duplication.
    if stats.pct_unique_openers < 75 and stats.n_rows >= 50:
        severity = _bump(severity, "warn")
        reasons.append(
            f"Only {stats.pct_unique_openers:.0f}% of rows have a "
            f"unique opener — {stats.n_duplicate_openers} rows "
            f"may be near-duplicates.")
        suggestions.append(
            "Run 'Clean existing rows' on Step 1 — the cleaner "
            "drops boilerplate that often produces duplicate "
            "openers.")

    # Type-token ratio — very low means rote / templated.
    if stats.type_token_ratio and stats.type_token_ratio < 0.05:
        severity = _bump(severity, "warn")
        reasons.append(
            f"Vocabulary diversity is very low "
            f"(type-token ratio {stats.type_token_ratio:.3f}). "
            f"Real prose typically scores 0.05-0.20; lower means "
            f"the model will learn a narrow palette.")
        suggestions.append(
            "Add corpora with broader vocabulary, or check that "
            "the existing rows aren't all templatey "
            "synthesised data.")

    # Length distribution sanity.
    if stats.pct_too_short > 5:
        severity = _bump(severity, "warn")
        reasons.append(
            f"{stats.pct_too_short:.0f}% of rows have outputs "
            f"shorter than 80 chars — the model may learn to "
            f"generate stub responses.")
        suggestions.append(
            "Increase the minimum-length filter in the cleaner, "
            "or upload longer source material.")

    # Voice intent without voice-tagged rows.
    if intent_norm == "voice" and stats.n_rows > 0:
        pct_voiced = stats.n_voice_tagged / stats.n_rows * 100.0
        if pct_voiced < 10:
            severity = _bump(severity, "warn")
            reasons.append(
                f"Only {pct_voiced:.0f}% of rows have a voice tag "
                f"(needed: ~50%+ for voice intent). The trained "
                f"model will reflect the corpus authors' generic "
                f"style, not a specific voice.")
            suggestions.append(
                "Tag your own writing rows with a voice in the "
                "Upload dialog, or boost the user-voice oversample "
                "factor in the recipe.")

    # Genre / tone misalignment.
    if (stats.pct_matching_genres is not None
            and stats.pct_matching_genres < 30):
        severity = _bump(severity, "warn")
        reasons.append(
            f"Only {stats.pct_matching_genres:.0f}% of tagged "
            f"rows match the genres you ticked on Step 1 — "
            f"the genre filter is doing little work.")
        suggestions.append(
            "Either ingest genre-specific corpora (Library), or "
            "uncheck the genre filter on Step 1.")

    # Compose summary.
    if severity == "pass":
        summary = (
            f"Looks good — {stats.n_rows} rows, "
            f"vocab diversity {stats.type_token_ratio:.2f}, "
            f"{stats.pct_unique_openers:.0f}% unique openers.")
    elif severity == "warn":
        summary = (f"Concerns flagged ({len(reasons)}). "
                   f"Training will run but may produce a weaker "
                   f"model than expected.")
    else:
        summary = (f"This corpus is unlikely to train a usable "
                   f"{intent_norm} model. Address the issues "
                   f"below before spending GPU time.")

    return Verdict(
        severity=severity,
        summary=summary,
        reasons=reasons,
        suggestions=suggestions,
        source="deterministic")


def _bump(current: str, new: str) -> str:
    order = {"pass": 0, "warn": 1, "fail": 2}
    return new if order[new] > order[current] else current


# ── LLM verdict ────────────────────────────────────────────


def llm_verdict(stats: CorpusStats, *,
                 intent: str,
                 llm_generate: Callable[[str, str], str],
                 ) -> Verdict:
    """Ask the configured LLM for an honest assessment.

    ``llm_generate(prompt, system) -> str`` is the same shape the
    rephrase synthesizer and pacing synthesizer use, so a caller
    can wire any of the existing LLMClient providers (Claude,
    GPT, Gemini, local HF/MLX) without this module needing to
    know about them.

    The prompt is deliberately framed for skepticism — we want
    "what could go wrong" not "this is great." Output is parsed
    into a Verdict; if parsing fails we fall back to a "warn"
    verdict pointing at the raw text.
    """
    samples = sample_passages(stats, n=3)
    sample_text = "\n---\n".join(
        f"USER: {s['user'][:200]}\nASSISTANT: {s['assistant'][:300]}"
        for s in samples)

    system = (
        "You are a critical ML reviewer. The user is about to "
        "fine-tune a model on the dataset described below. Be "
        "honest, specific, and skeptical. Identify what could go "
        "wrong, what's missing, and whether this dataset is "
        "actually fit for the stated training intent. Don't "
        "cheerlead.\n\n"
        "Respond ONLY in this exact format:\n"
        "VERDICT: pass | warn | fail\n"
        "SUMMARY: <one sentence>\n"
        "REASONS:\n- <reason 1>\n- <reason 2>\n"
        "SUGGESTIONS:\n- <suggestion 1>\n- <suggestion 2>\n")

    prompt = (
        f"Training intent: {intent}\n"
        f"Dataset stats:\n"
        f"  Total rows: {stats.n_rows}\n"
        f"  Source breakdown: {dict(stats.by_source)}\n"
        f"  Median user-side length: "
        f"{stats.median_user_len} chars\n"
        f"  Median output length: "
        f"{stats.median_output_len} chars (p10={stats.p10_output_len}, "
        f"p90={stats.p90_output_len})\n"
        f"  Vocabulary diversity (type-token): "
        f"{stats.type_token_ratio:.3f}\n"
        f"  Unique-opener rate: "
        f"{stats.pct_unique_openers:.1f}%\n"
        f"  Voice-tagged rows: {stats.n_voice_tagged}\n"
    )
    if stats.pct_matching_genres is not None:
        prompt += (f"  Genre-tag match: "
                   f"{stats.pct_matching_genres:.0f}% of tagged rows\n")
    if stats.pct_matching_tones is not None:
        prompt += (f"  Tone match (notes): "
                   f"{stats.pct_matching_tones:.0f}% of tagged rows\n")
    prompt += f"\nSample rows:\n{sample_text}\n"

    try:
        raw = llm_generate(prompt, system)
    except Exception as e:
        return Verdict(
            severity="warn", source="llm",
            summary=f"LLM assessment failed: {e}",
            reasons=["Couldn't reach the configured LLM. "
                     "Deterministic verdict still applies."])
    return _parse_llm_verdict(raw or "")


def _parse_llm_verdict(raw: str) -> Verdict:
    """Extract VERDICT / SUMMARY / REASONS / SUGGESTIONS from the
    LLM's free-form response.

    Tolerant of formatting drift — uses regex over substring
    matching. If the LLM ignored the format entirely, returns a
    "warn" verdict containing the raw text so the user can still
    read what the model said.
    """
    severity = "warn"
    m = re.search(r'VERDICT\s*:\s*(pass|warn|fail)', raw, re.IGNORECASE)
    if m:
        severity = m.group(1).lower()

    summary = ""
    m = re.search(
        r'SUMMARY\s*:\s*(.+?)(?=\n[A-Z]+:|\Z)',
        raw, re.DOTALL | re.IGNORECASE)
    if m:
        summary = m.group(1).strip().splitlines()[0]

    reasons = _extract_bullets(raw, "REASONS")
    suggestions = _extract_bullets(raw, "SUGGESTIONS")

    if not summary and not reasons:
        # Format drift — don't lose the LLM's output.
        return Verdict(
            severity="warn", source="llm",
            summary="LLM responded but didn't follow the format.",
            reasons=[raw[:600]])
    return Verdict(
        severity=severity,
        summary=summary or "(no summary)",
        reasons=reasons,
        suggestions=suggestions,
        source="llm")


def _extract_bullets(raw: str, header: str) -> List[str]:
    pat = (rf'{header}\s*:\s*\n((?:\s*[-•]\s*.+\n?)+)')
    m = re.search(pat, raw, re.IGNORECASE)
    if not m:
        return []
    return [line.lstrip("-•* ").strip()
            for line in m.group(1).splitlines()
            if line.strip()]
