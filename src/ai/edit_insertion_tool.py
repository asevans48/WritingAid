"""Tag parser for the ``<edit_last_insertion>`` chat tool.

The chapter-focus / writer chat surfaces ``RECENT AI INSERTIONS`` with
indexed entries so the model can refer back to what it just wrote.
When the user asks to edit one ("add more tension to that scene you
wrote"), the model emits::

    <edit_last_insertion>
    {"index": 0, "instructions": "add more tension"}
    </edit_last_insertion>

The engine intercepts the tag, runs an edit LLM call against the
recorded prose with the user's instructions + surrounding chapter
context, and replaces the original range in the editor with the
revised prose. The insertion record is updated to point at the new
range so a follow-up edit chains correctly.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


_EDIT_TAG_RX = re.compile(
    r"<edit_last_insertion>\s*(\{.*?\})\s*</edit_last_insertion>",
    re.DOTALL | re.IGNORECASE,
)


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    """Forgiving JSON parse — tolerates single quotes, trailing commas."""
    if not raw:
        return {}
    candidates = [
        raw,
        raw.replace("'", '"'),
        re.sub(r",\s*([}\]])", r"\1", raw),
    ]
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return {}


def extract_edit_calls(response: str) -> List[Dict[str, Any]]:
    """Pull every <edit_last_insertion> tag from a model response.

    Each entry is ``{"params": {...}, "raw": "<full match>"}``.
    Multiple tags in one reply are returned in order; the dispatcher
    typically only honours the first one (chained edits would
    interleave editor mutations).
    """
    out: List[Dict[str, Any]] = []
    for m in _EDIT_TAG_RX.finditer(response):
        params = _safe_json_loads(m.group(1))
        out.append({"params": params, "raw": m.group(0)})
    return out


def strip_edit_calls(response: str) -> str:
    """Remove all <edit_last_insertion> tags from a chat response."""
    return _EDIT_TAG_RX.sub("", response).strip()


def has_edit_calls(response: str) -> bool:
    return bool(_EDIT_TAG_RX.search(response))


def resolve_index(
    raw_index: Any,
    n_records: int,
) -> Optional[int]:
    """Normalise an index value passed in the JSON params.

    Accepts:
      * Integer in ``[0, n_records-1]``
      * ``"last"`` / ``"latest"`` / ``"most_recent"`` → most recent
      * ``"first"`` → oldest
      * Negative integers (``-1`` = most recent) — Python-style
      * ``None`` / missing → most recent (0 records → ``None``)

    Returns the resolved 0-based index, or ``None`` when the
    argument can't be made into a valid index.
    """
    if n_records <= 0:
        return None
    if raw_index is None:
        return n_records - 1
    if isinstance(raw_index, str):
        s = raw_index.strip().lower()
        if s in ("last", "latest", "most_recent", "newest", ""):
            return n_records - 1
        if s in ("first", "oldest"):
            return 0
        try:
            raw_index = int(s)
        except ValueError:
            return None
    if isinstance(raw_index, bool):  # bool is an int — reject it
        return None
    if not isinstance(raw_index, int):
        return None
    if raw_index < 0:
        raw_index = n_records + raw_index
    if 0 <= raw_index < n_records:
        return raw_index
    return None


# System-prompt block — appended to writer/chapter_focus prompts so
# the model knows the tool exists + the protocol.
EDIT_INSERTION_PROMPT_BLOCK = """=== EDIT-LAST-INSERTION TOOL ===
When the user asks you to revise something you just wrote ("add more tension to that scene", "rewrite the last paragraph with sharper voice", "tighten the ending of what you wrote"), DO NOT write a full new version inline. Emit this tool block:

<edit_last_insertion>{"index": 0, "instructions": "the user's edit ask, paraphrased into specific instructions"}</edit_last_insertion>

Where:
- ``index`` references the [N] label in the RECENT AI INSERTIONS block (default to the most recent if the user's wording is ambiguous; explicit "the second-to-last" maps to the appropriate N). Negative integers work Python-style (-1 = most recent). String aliases "last" / "latest" / "first" are accepted.
- ``instructions`` is the actionable rewrite ask, including the specific change the user wants — "add a beat where Marcus reaches for the door, then doesn't", "tighten the dialogue", "make the dread more visceral", "fold in the ritual from the worldbuilding".

The engine fetches the original prose by index, runs an edit pass with the user's instructions + surrounding chapter context, and replaces the range in the editor. The insertion record updates so a follow-up edit chains correctly.

When to use it:
- ANY follow-up that targets prose you previously wrote — refine, tighten, expand, change tone, add tension, restructure, swap POV.
- The user references "that", "what you wrote", "the last scene", "the part with X" → match against the RECENT INSERTIONS by content, not by literal index, and pick the right N.

When NOT to use it:
- The user asks a NEW writing task (different chapter, different beat) → use <write_chapter_full> / <append_plot_points> / <continue_from_cursor> as before.
- The user is asking a question about the prose, not asking for an edit → answer in chat normally.
- No RECENT INSERTIONS are listed → tell the user there's nothing to edit yet."""
