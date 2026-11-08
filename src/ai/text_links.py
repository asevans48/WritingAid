"""Links from chat findings to the manuscript text they're about.

Critique findings and chat replies quote (or closely paraphrase) the
passage that needs work. This module finds that passage in the chapter
text and builds a ``wa-goto:`` link the chat turns into a click target;
clicking opens the chapter and selects the passage.

Matching is tolerant of what models do to quotes: curly vs straight
quotes, collapsed whitespace, case, trailing punctuation, "…" elisions,
and small paraphrases (falls back to the longest run of consecutive
words the snippet shares with the text).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote as _urlquote, unquote as _urlunquote

SCHEME = "wa-goto"
MIN_RUN_WORDS = 5          # fuzzy fallback: shared run of at least this many words
_QUOTE_RX = re.compile(r"[\"“]([^\"“”\n]{8,300})[\"”]")
_STOP = set("""a an the and or but so of to in on at by for with from into onto as is was were
be been are it its it's he she they them his her their we you i me my our your this that
these those there here then than not no up out over off just very all any some""".split())
_TRANSLATE = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-"})

Chapter = Tuple[str, str, str]   # (chapter_id, title, text)


def make_link(chapter_id: str, passage: str, label: str = "↗ go to text") -> str:
    """Markdown link the chat renders as a clickable jump."""
    return f"[{label}]({SCHEME}:{_urlquote(chapter_id, safe='')}?q={_urlquote(passage[:300], safe='')})"


def parse_link(url: str) -> Optional[Tuple[str, str]]:
    """``wa-goto:<id>?q=<passage>`` → (chapter_id, passage)."""
    if not url or not url.startswith(SCHEME + ":"):
        return None
    body = url[len(SCHEME) + 1:]
    cid, _, query = body.partition("?")
    passage = ""
    for part in query.split("&"):
        if part.startswith("q="):
            passage = _urlunquote(part[2:])
    return _urlunquote(cid), passage


def _normalize(text: str) -> Tuple[str, List[int]]:
    """Lower-cased, quote-normalised, whitespace-collapsed copy of
    ``text`` plus a map from each normalised index to the original."""
    out, index = [], []
    prev_space = True
    for i, ch in enumerate(text.translate(_TRANSLATE)):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                index.append(i)
            prev_space = True
            continue
        out.append(ch.lower())
        index.append(i)
        prev_space = False
    return "".join(out), index


def _words_with_spans(norm: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0).strip("'"), m.start(), m.end())
            for m in re.finditer(r"[a-z0-9']+", norm)]


def locate(text: str, snippet: str) -> Optional[Tuple[int, int]]:
    """Find ``snippet`` in ``text``; returns (start, end) in ``text``."""
    if not text or not snippet or len(snippet.strip()) < 4:
        return None
    norm_text, idx = _normalize(text)
    norm_snip, _ = _normalize(snippet.strip().strip("\"'“”‘’ "))
    norm_snip = norm_snip.strip(" .,;:!?")
    if not norm_snip:
        return None

    def span(a: int, b: int) -> Tuple[int, int]:
        return idx[a], idx[b - 1] + 1

    pos = norm_text.find(norm_snip)
    if pos >= 0:
        return span(pos, pos + len(norm_snip))
    # Elided quotes ("she walked … the pier"): match the longest piece.
    pieces = sorted((p.strip(" .,;:!?") for p in re.split(r"\.\.\.|…", norm_snip)),
                    key=len, reverse=True)
    for piece in pieces:
        if len(piece.split()) >= 3:
            pos = norm_text.find(piece)
            if pos >= 0:
                return span(pos, pos + len(piece))
    # Paraphrase: longest run of consecutive words shared with the text.
    snip_words = [w for w, _, _ in _words_with_spans(norm_snip)]
    if len(snip_words) < MIN_RUN_WORDS:
        return None
    text_words = _words_with_spans(norm_text)
    positions = {}
    for i, (w, _, _) in enumerate(text_words):
        positions.setdefault(w, []).append(i)
    best = (0, 0, 0)  # (length, text_start_word, text_end_word)
    for si, w in enumerate(snip_words):
        for ti in positions.get(w, ()):
            n = 0
            while (si + n < len(snip_words) and ti + n < len(text_words)
                   and text_words[ti + n][0] == snip_words[si + n]):
                n += 1
            if n > best[0]:
                best = (n, ti, ti + n - 1)
    if best[0] >= MIN_RUN_WORDS:
        run = [text_words[i][0] for i in range(best[1], best[2] + 1)]
        # A run of filler ("at the end of the") isn't evidence.
        if sum(1 for w in run if len(w) >= 4 and w not in _STOP) >= 2:
            return span(text_words[best[1]][1], text_words[best[2]][2])
    return None


def find_in_chapters(snippet: str, chapters: Sequence[Chapter],
                     prefer_id: str = "") -> Optional[Tuple[str, str]]:
    """First chapter containing ``snippet`` (preferred chapter first).
    Returns (chapter_id, the exact text found)."""
    ordered = sorted(chapters, key=lambda c: c[0] != prefer_id)
    for cid, _title, text in ordered:
        hit = locate(text, snippet)
        if hit:
            return cid, text[hit[0]:hit[1]]
    return None


def candidate_snippets(item: str) -> List[str]:
    """Passages an issue/suggestion line might point at: quoted text
    first, then the line's body (after "Name — field —" prefixes)."""
    cands = [m.group(1) for m in _QUOTE_RX.finditer(item or "")]
    body = re.split(r"\s+[—–]\s+|:\s+", item or "")
    if body:
        cands.append(body[-1])
    cands.append(item or "")
    seen, out = set(), []
    for c in cands:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def link_for_item(item: str, chapters: Sequence[Chapter], prefer_id: str = "",
                  label: str = "↗ go to text") -> str:
    """A " [↗ go to text](…)" suffix for ``item``, or "" if it can't be placed."""
    for snip in candidate_snippets(item):
        hit = find_in_chapters(snip, chapters, prefer_id)
        if hit:
            return " " + make_link(hit[0], hit[1], label)
    return ""


def add_passage_links(reply: str, chapters: Sequence[Chapter], prefer_id: str = "",
                      min_words: int = 4) -> str:
    """Put a "↗" link after every quote in ``reply`` that comes from the
    manuscript (skips code blocks and quotes already followed by a link)."""
    if not reply or not chapters:
        return reply
    parts = re.split(r"(```.*?```)", reply, flags=re.S)
    for i, part in enumerate(parts):
        if part.startswith("```"):
            continue

        def repl(m: "re.Match") -> str:
            inner = m.group(1)
            following = part[m.end():m.end() + 3]
            if len(inner.split()) < min_words or following.startswith(" [↗") or following.startswith("[↗"):
                return m.group(0)
            hit = find_in_chapters(inner, chapters, prefer_id)
            if not hit:
                return m.group(0)
            return m.group(0) + " " + make_link(hit[0], hit[1], "↗")
        parts[i] = _QUOTE_RX.sub(repl, part)
    return "".join(parts)
