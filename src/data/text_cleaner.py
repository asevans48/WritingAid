"""Conservative text cleaner shared by every corpus ingestion path.

The trainer turns *whatever's in the database* into the model's voice
and behaviour. If the database has Project Gutenberg "Produced by"
boilerplate, AI refusal templates ("As an AI language model…"), tool
call JSON, or stray TOC fragments, the model learns to produce them.
That's the source of most "model output looks weird" complaints in
small-corpus fine-tunes.

This module's job: scrub the obvious junk while preserving substance.

**Design priorities, in order:**

1. **Preserve substance.** Cleaning should never strip whole prose
   passages. Every drop rule is keyed on a recognisable junk signature
   — not on length/style heuristics that could discard real writing.
2. **Be transparent.** ``clean_passages`` returns
   ``(passages, stats)`` so the caller can log "kept N, dropped M
   for reason X" rather than the user mysteriously losing rows.
3. **Be format-aware.** Gutenberg, Markdown, EPUB, and chat dumps
   each have their own classes of junk; the cleaner takes a
   ``format_hint`` and applies the right pass.
4. **Be cheap.** No LLM calls — pure regex/string ops so the cleaner
   is safe to run inside the streaming tokenization pass.

**What gets cleaned (default rules, every format):**

* HTML entities decoded (``&amp;`` → ``&``)
* Common ligatures normalised (``ﬁ`` → ``fi``, ``ﬂ`` → ``fl``)
* Soft hyphens / zero-width chars stripped
* Whitespace collapsed (3+ blank lines → 2; intra-paragraph
  whitespace → single space)
* Underscore-italic markers removed (``_word_`` → ``word``) on
  Gutenberg only, where they're a digitisation artifact

**What gets dropped (entire passage):**

* Passages outside [80, 2500] chars (too short = noise; too long =
  blow the LLM context window — caller can override the bounds)
* All-caps headings / bare chapter markers
* PG header/footer remnants ("Produced by…", "Transcriber's note…")
* AI refusal / boilerplate templates
* Tool-call JSON blocks
* Pure-numeric or roman-numeral lines (page numbers)
* Outline placeholders ("[TBD]", "[insert scene]")
* Single bracketed metadata items ("[Illustration]", "[Footnote 1]")
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Length bounds ──────────────────────────────────────────
# Defaults tuned for fiction-sized passages: a Hemingway opener fits
# 80 chars; a long Faulkner sentence rarely exceeds 2500. Override via
# ``clean_passages(min_len=…, max_len=…)`` for unusual corpora.
DEFAULT_MIN_LEN = 80
DEFAULT_MAX_LEN = 2500


# ── Drop signatures ────────────────────────────────────────
#
# Every entry here is a regex that, when matched against a passage,
# means the passage is junk. Patterns are anchored where appropriate
# and tested against representative examples in tests/test_text_cleaner.py
# (or the smoke test below). Adding a new pattern means: regex + a comment
# explaining what real-world junk it targets + ideally an example.

# PG START/END markers (defensive — _parse_gutenberg already slices them
# out, but if a passage somehow survives that pass we still drop it).
_PG_MARKER_RE = re.compile(
    r'\*{3,}\s*(START|END)\s+OF\s+(THE|THIS)?\s*PROJECT\s+GUTENBERG',
    re.IGNORECASE)

# PG transcription notes — typically near the top of older PG files.
# Example: "Produced by Charles Franks and the Online Distributed
# Proofreading Team."
_PG_PRODUCED_BY_RE = re.compile(
    r'^\s*Produced\s+by\s+', re.IGNORECASE)

# Transcriber's notes — typically near the bottom. Example:
# "Transcriber's note: Some inconsistencies in spelling have been
# preserved as printed."
_TRANSCRIBER_NOTE_RE = re.compile(
    r"^\s*Transcriber'?s?\s+notes?\b", re.IGNORECASE)

# Pure ALL-CAPS heading lines (>60 chars catches things like
# "CHAPTER ONE — THE BEGINNING OF AN ENDLESS DAY"). Below 60 chars
# the length filter handles it.
_ALL_CAPS_RE = re.compile(r'^[A-Z0-9\s\W]+$')

# "Chapter N" / "Book N" / "Part N" / "Volume N" / "Act N" / "Scene N"
# alone — possibly with a roman numeral or a colon-style subtitle.
_SECTION_HEADING_RE = re.compile(
    r'^\s*(chapter|book|part|volume|act|scene)\s+'
    r'([IVXLCDM]+|\d+|[a-zA-Z]+)?\.?(\s*[—:.\-]\s*\w+.*)?\s*$',
    re.IGNORECASE)

# Pure roman-numeral chapter heading ("II", "III", "XIV") possibly
# with a trailing dot.
_ROMAN_HEADING_RE = re.compile(
    r'^\s*[IVXLCDM]{1,8}\.?\s*$')

# Pure digits — page numbers ("47", "128.")
_PAGE_NUMBER_RE = re.compile(r'^\s*\d{1,4}\.?\s*$')

# AI assistant refusal/boilerplate prefixes. We drop ENTIRE passages
# that *open* with these — partial matches inside a larger passage
# stay (the model might have gone on to write something useful).
_AI_BOILERPLATE_RE = re.compile(
    r'^\s*(as an ai language model|i cannot (assist|help|provide|generate)|'
    r"i'm sorry,? but|i'm just an ai|"
    r'i (cannot|can\'?t) (fulfill|complete|do) that)',
    re.IGNORECASE)

# Tool-call JSON-shaped passages. Match arrays / objects whose first
# substantive token is one of the standard tool keywords.
_TOOL_CALL_RE = re.compile(
    r'^\s*[\[\{]\s*"?(tool|tool_calls?|function|name|arguments|action)"?\s*:',
    re.IGNORECASE)

# Single bracketed metadata items: "[Illustration]", "[Footnote 1]",
# "[TBD]", "[insert scene]". Real prose with a stray "[Footnote 1]"
# inside it is preserved — only stripped when the WHOLE passage is
# bracketed metadata.
_BRACKET_METADATA_RE = re.compile(
    r'^\s*\[\s*(illustration|footnote|figure|fig\.|image|table|tbd|todo|'
    r'insert|placeholder|to do|wip)\b[^\]]*\]\s*\.?\s*$',
    re.IGNORECASE)

# Markdown front matter line ("---" between key:value lines). Just the
# delimiter — the YAML body still passes through length filtering.
_MARKDOWN_FRONTMATTER_DELIM_RE = re.compile(r'^\s*-{3,}\s*$')

# Markdown comment containing only a TODO / placeholder. Preserves
# regular HTML comments inside prose.
_MARKDOWN_COMMENT_RE = re.compile(
    r'^\s*<!--\s*(tbd|todo|fixme|placeholder)[^>]*-->\s*$',
    re.IGNORECASE)


# ── Character-level normalisations (apply BEFORE drop checks) ─

# Unicode ligatures common in OCR-scanned books. Map to ASCII.
_LIGATURE_MAP = {
    "ﬀ": "ff",  # ﬀ
    "ﬁ": "fi",  # ﬁ
    "ﬂ": "fl",  # ﬂ
    "ﬃ": "ffi", # ﬃ
    "ﬄ": "ffl", # ﬄ
    "ﬅ": "ft",  # ﬅ
    "ﬆ": "st",  # ﬆ
}
_LIGATURE_RE = re.compile("|".join(map(re.escape, _LIGATURE_MAP)))

# Zero-width / formatting chars that creep in from web copy/paste.
_ZWSP_RE = re.compile(
    r'[​‌‍⁠﻿­]')

# Underscore-italic markers used in 19th-c PG files. Conservative —
# only strips the markers when they bracket a SINGLE word so we don't
# eat real underscores in code / URLs.
_PG_UNDERSCORE_ITALIC_RE = re.compile(
    r'\b_(\w+)_\b')


@dataclass
class CleanStats:
    """Accounting from a cleaning pass.

    The caller uses this to log "kept N, dropped M (X for boilerplate,
    Y for length, Z for tool-call JSON…)" so the user understands what
    happened to their data.
    """
    kept: int = 0
    dropped_total: int = 0
    drops_by_reason: Dict[str, int] = field(default_factory=dict)

    def note_drop(self, reason: str) -> None:
        self.dropped_total += 1
        self.drops_by_reason[reason] = (
            self.drops_by_reason.get(reason, 0) + 1)

    def summary(self) -> str:
        if self.dropped_total == 0:
            return f"kept {self.kept} (no junk dropped)"
        breakdown = ", ".join(
            f"{n} {reason}"
            for reason, n in sorted(self.drops_by_reason.items(),
                                    key=lambda kv: -kv[1])[:5])
        return (f"kept {self.kept}, dropped {self.dropped_total} "
                f"({breakdown})")


def _normalise_chars(text: str, *, format_hint: str = "plain") -> str:
    """Cheap character-level fixes that apply to every format."""
    if not text:
        return ""
    # HTML entities — applies first since they may contain whitespace
    # patterns we collapse next.
    if "&" in text and ";" in text:
        try:
            text = html.unescape(text)
        except Exception:
            pass
    # Ligatures + zero-width chars.
    if _LIGATURE_RE.search(text):
        text = _LIGATURE_RE.sub(lambda m: _LIGATURE_MAP[m.group(0)], text)
    text = _ZWSP_RE.sub("", text)
    # PG-specific: drop underscore-italic markers (a digitisation
    # artifact, never the author's intent).
    if format_hint == "gutenberg":
        text = _PG_UNDERSCORE_ITALIC_RE.sub(r"\1", text)
    return text


_TOOL_CALL_KEY_NAMES = {
    "tool", "tool_call", "tool_calls", "function", "function_call",
    "arguments", "action", "name", "parameters",
}


def _looks_like_tool_call_json(parsed) -> bool:
    """Recurse one level into a parsed JSON value, return True if any
    tool-call shaped key (``tool``, ``function``, ``arguments``…) is
    present. Real prose never has this shape, so a positive match is
    a clean signal to drop."""
    if isinstance(parsed, dict):
        return any(k in _TOOL_CALL_KEY_NAMES for k in parsed.keys())
    if isinstance(parsed, list):
        for item in parsed[:5]:  # only peek the first few
            if isinstance(item, dict) and any(
                    k in _TOOL_CALL_KEY_NAMES for k in item.keys()):
                return True
    return False


def _is_junk(text: str, *, format_hint: str = "plain",
             min_len: int = DEFAULT_MIN_LEN,
             max_len: int = DEFAULT_MAX_LEN) -> Tuple[bool, str]:
    """Decide if a passage is junk. Returns ``(is_junk, reason)``.

    The reason is a short stable string used for stats accounting and
    for the optional "why did this row drop" diagnostic UI.

    Order of checks: signature-based junk patterns FIRST, then length
    bounds. The point of returning a specific reason like
    ``"section_heading"`` is more useful than a generic
    ``"too_short"`` — the user (and the diagnostic UI) can act on
    "drop everything that looks like a chapter heading" but not on
    "drop everything under 80 chars."
    """
    if text is None:
        return True, "empty"

    stripped = text.strip()
    if not stripped:
        return True, "empty"

    # ── Junk-signature checks (specific, ordered most-specific first) ─

    # PG markers — defensive; the gutenberg adapter slices them out
    # but leaked-through fragments still get caught here.
    if _PG_MARKER_RE.search(stripped):
        return True, "pg_marker"
    if _PG_PRODUCED_BY_RE.match(stripped):
        return True, "pg_produced_by"
    if _TRANSCRIBER_NOTE_RE.match(stripped):
        return True, "transcriber_note"

    # Single-line section labels.
    single_line = (stripped if "\n" not in stripped
                   else stripped.splitlines()[0])
    if _SECTION_HEADING_RE.match(single_line) and len(stripped) < 120:
        return True, "section_heading"
    if _ROMAN_HEADING_RE.match(stripped):
        return True, "roman_heading"
    if _PAGE_NUMBER_RE.match(stripped):
        return True, "page_number"

    # ALL-CAPS heading — the >60 char catch is for big title lines
    # where length alone wouldn't drop them.
    if len(stripped) >= 60 and _ALL_CAPS_RE.match(stripped):
        return True, "all_caps_heading"

    # Boilerplate / refusal templates.
    if _AI_BOILERPLATE_RE.match(stripped):
        return True, "ai_boilerplate"

    # JSON-shaped junk: distinguish tool-call JSON (high-signal junk —
    # always drop) from generic JSON blobs (also drop, but tagged
    # separately for stats). Regex is cheap; parse is the certainty
    # path that catches nested shapes the regex missed.
    if _TOOL_CALL_RE.match(stripped):
        return True, "tool_call_json"
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (list, dict)):
            if _looks_like_tool_call_json(parsed):
                return True, "tool_call_json"
            return True, "json_blob"

    # Single bracketed metadata items.
    if _BRACKET_METADATA_RE.match(stripped):
        return True, "bracket_metadata"

    # Markdown-specific signatures.
    if format_hint in ("markdown", "md"):
        if _MARKDOWN_FRONTMATTER_DELIM_RE.match(stripped):
            return True, "markdown_frontmatter"
        if _MARKDOWN_COMMENT_RE.match(stripped):
            return True, "markdown_todo_comment"

    # ── Length bounds (last resort fallback) ─────────────────

    if len(stripped) < min_len:
        return True, "too_short"
    if len(stripped) > max_len:
        return True, "too_long"

    return False, ""


def clean_passage(text: str, *, format_hint: str = "plain",
                   min_len: int = DEFAULT_MIN_LEN,
                   max_len: int = DEFAULT_MAX_LEN) -> Tuple[str, str]:
    """Clean a single passage. Returns ``(cleaned_text, drop_reason)``.

    If ``drop_reason`` is empty, ``cleaned_text`` is the (possibly
    normalised) passage to keep. If ``drop_reason`` is non-empty,
    ``cleaned_text`` is empty and the passage was rejected.
    """
    if text is None:
        return "", "empty"
    normalised = _normalise_chars(text, format_hint=format_hint)
    is_junk, reason = _is_junk(
        normalised, format_hint=format_hint,
        min_len=min_len, max_len=max_len)
    if is_junk:
        return "", reason
    return normalised, ""


def clean_passages(passages: List[str], *,
                   format_hint: str = "plain",
                   min_len: int = DEFAULT_MIN_LEN,
                   max_len: int = DEFAULT_MAX_LEN
                   ) -> Tuple[List[str], CleanStats]:
    """Clean a list of passages. Returns ``(kept, stats)``.

    Drops are tracked by reason in ``stats.drops_by_reason`` so the
    caller can log "kept 2,453 — dropped 18 ai_boilerplate, 7 tool_call_json,
    3 page_number" instead of just "dropped 28."
    """
    stats = CleanStats()
    kept: List[str] = []
    for p in passages:
        cleaned, reason = clean_passage(
            p, format_hint=format_hint,
            min_len=min_len, max_len=max_len)
        if reason:
            stats.note_drop(reason)
        else:
            kept.append(cleaned)
            stats.kept += 1
    return kept, stats


# ── Chat / conversation cleaner ───────────────────────────
#
# Chat dumps need a different pass: we preserve the user's prose but
# strip refusal templates, system messages, and tool-call JSON before
# letting the passage pipeline see the text.

def clean_chat_message(content: str) -> Tuple[str, str]:
    """Clean a single chat message's text content.

    Returns ``(cleaned, drop_reason)``. Empty drop_reason = keep.
    Used by the agent / writing-tool import path before logging chat
    rows to the database.

    Order of operations:
      1. Normalise characters (entities, ligatures, ZWSP).
      2. Strip the "As an AI language model…" preamble — but keep
         what follows. The actual answer often comes after this
         disclaimer; we don't want to lose it.
      3. Check the remainder for whole-message refusal templates
         (e.g. "I cannot help with that.") — drop if that's all
         that's left.
      4. Check for tool-call / JSON shapes — drop those entire
         messages outright; they aren't prose.
    """
    if not content:
        return "", "empty"
    text = _normalise_chars(content, format_hint="plain").strip()
    if not text:
        return "", "empty"

    # Strip leading "As an AI language model, " preamble FIRST so
    # otherwise-substantive replies survive. Repeat until the prefix
    # no longer matches (some messages stack the boilerplate).
    stripped_prefix = re.sub(
        r'^\s*(as an ai language model[,.\s]+)+',
        '', text, flags=re.IGNORECASE).strip()
    if not stripped_prefix:
        return "", "ai_boilerplate"
    text = stripped_prefix

    # Now check whether the REMAINDER is a whole-message refusal.
    if _AI_BOILERPLATE_RE.match(text):
        return "", "ai_boilerplate"
    # Short residuals that begin with refusal verbs — "I cannot.",
    # "I can't.", "I won't help" — are also refusals. We only fire
    # this on short residuals (<50 chars) so we don't accidentally
    # drop legitimate dialogue like "I cannot believe what happened
    # next, the room had been empty for hours…"
    if len(text) < 50 and re.match(
            r"^\s*i (cannot|can'?t|won'?t|will\s+not)\b",
            text, flags=re.IGNORECASE):
        return "", "ai_boilerplate"

    # JSON-shaped junk: same two-stage classification as the passage
    # cleaner — regex catches the obvious shape, parse + key-peek
    # catches nested forms the regex misses, and tool-call JSON gets
    # tagged separately from generic JSON for stats clarity.
    if _TOOL_CALL_RE.match(text):
        return "", "tool_call_json"
    if text.startswith(("[", "{")):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (list, dict)):
            if _looks_like_tool_call_json(parsed):
                return "", "tool_call_json"
            return "", "json_blob"

    return text, ""
