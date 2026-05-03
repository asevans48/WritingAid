"""Shared helpers for splitting / joining prose into paragraphs.

The codebase had ad-hoc ``text.split('\\n\\n')`` calls in several
places (exporter, TTS pause logic, enhanced editor) — each with
slightly different normalisation. This module centralises the
behaviour so the new checkpoint-manifest UI and any future caller
treat paragraphs the same way.

Conventions handled:

  * **Markdown / file-on-disk** — paragraphs separated by blank
    lines (``\\n\\n``). Standard for static text.
  * **Qt editor** — ``QTextEdit.toPlainText()`` and the cursor-
    selection text both produce paragraphs separated by *single*
    ``\\n`` because Qt collapses its internal ``\\u2029``
    paragraph separator down to one newline. Both U+2029 (paragraph
    separator) and U+2028 (line separator) are normalised to LF
    before splitting so callers passing raw selection text still
    get correct results.

Splitting on ``\\n+`` covers both: any run of one-or-more
consecutive newlines is a paragraph break. The downside (over-
splitting prose with intentional soft line-wraps inside a
paragraph) is rare in modern writing tools — they word-wrap
visually rather than inserting hard ``\\n``.
"""

from __future__ import annotations

import re
from typing import List


_PARA_SEP = chr(0x2029)
_LINE_SEP = chr(0x2028)


def split_paragraphs(text: str) -> List[str]:
    """Split ``text`` into paragraph chunks.

    Returns a list of trimmed paragraphs (whitespace-only chunks
    dropped). Empty input returns ``[]``. Single-paragraph input
    returns a 1-element list with the text trimmed. Order is
    preserved — index N in the returned list corresponds to the
    Nth paragraph in source order, which is what the checkpoint
    UI keys off.
    """
    if not text:
        return []
    normalised = (text
                  .replace("\r\n", "\n")
                  .replace("\r", "\n")
                  .replace(_PARA_SEP, "\n")
                  .replace(_LINE_SEP, "\n"))
    return [c.strip() for c in re.split(r"\n+", normalised) if c.strip()]


def join_paragraphs(paragraphs: List[str], *,
                    separator: str = "\n\n") -> str:
    """Join paragraphs back into a single text string.

    Default separator is the markdown blank-line convention so the
    output renders correctly in any consumer that expects either
    convention (Qt editor, exporter, file-on-disk markdown). Empty
    paragraphs are dropped — a checkpoint that "rejects" a paragraph
    by passing an empty string for it doesn't leave a doubled
    blank-line gap in the output.
    """
    if not paragraphs:
        return ""
    return separator.join(p for p in paragraphs if p and p.strip())
