"""Per-row content scrubber — mutates rows in place to remove
inline garbage that the model would otherwise learn to reproduce.

Distinct from the existing pipeline:

  * ``text_cleaner.clean_passage`` *drops* whole rows that match
    junk signatures (page numbers, JSON blobs, refusals).
  * ``corpus_variability`` *drops* redundant rows (duplicates,
    over-represented sources / clusters).
  * **This module mutates** rows that survive both — fixing
    repeated-word runs, mojibake, undecoded HTML entities, weird
    whitespace, control characters. The rows stay; their content
    gets cleaned.

Each scrub category is opt-in at apply time so the user can
preview "fix mojibake but not repeat-words" or vice versa.

Issue tags are stable strings, suitable for stats reporting and
backup-record annotations.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Issue tags ───────────────────────────────────────────────

ISSUE_WORD_REP = "word_repetition"      # "the the the the …"
ISSUE_CHAR_REP = "char_repetition"      # "Aaaaaaaaa", "!!!!!!!!"
ISSUE_HTML_ENT = "html_entity"          # "&amp;", "&#39;"
ISSUE_MOJIBAKE = "mojibake"             # "â€™", "Ã©"
ISSUE_CTRL_CHAR = "control_char"        # \x00-\x1F (except \t \n \r)
ISSUE_WHITESPACE = "whitespace"         # multiple spaces / weird WS
ISSUE_NOTICE = "copyright_notice"       # PG / copyright / license boilerplate

ALL_ISSUES: Tuple[str, ...] = (
    ISSUE_WORD_REP,
    ISSUE_CHAR_REP,
    ISSUE_HTML_ENT,
    ISSUE_MOJIBAKE,
    ISSUE_CTRL_CHAR,
    ISSUE_WHITESPACE,
    ISSUE_NOTICE,
)


# ── Detection thresholds ────────────────────────────────────
#
# Tuned to be obvious-only. We don't want to fix "Wow!!!" (3 chars,
# legitimate emphasis) — only "wow!!!!!!!!!!!" (12+) and similar
# pathological cases. Same idea for word repeats: "no, no, no" is
# valid prose but "the the the the the the" is garbage.

WORD_REP_THRESHOLD = 4   # 4+ consecutive same word → collapse
CHAR_REP_THRESHOLD = 7   # 7+ consecutive same char → cap at 3


# ── Helpers ──────────────────────────────────────────────────

# Common mojibake mappings. UTF-8 bytes round-tripped through
# Latin-1 produce these — the most frequent artifacts in scraped
# corpora. Order matters: longer keys first so we don't half-
# replace a multi-byte sequence.
_MOJIBAKE_MAP = {
    # Punctuation (most common)
    "â€™": "’",   # right single quote
    "â€œ": "“",   # left double quote
    "â€\x9d": "”", # right double quote (raw)
    "â€\xa6": "…", # ellipsis (raw)
    "â€“": "–",   # en dash
    "â€”": "—",   # em dash
    "â€¦": "…",   # ellipsis
    "â€˜": "‘",   # left single quote
    "â€¢": "•",   # bullet
    # Accented Latin
    "Ã©": "é", "Ã¨": "è", "Ãª": "ê", "Ã«": "ë",
    "Ã¡": "á", "Ã ": "à", "Ã¢": "â", "Ã¤": "ä",
    "Ã³": "ó", "Ã²": "ò", "Ã´": "ô", "Ã¶": "ö",
    "Ãº": "ú", "Ã¹": "ù", "Ã»": "û", "Ã¼": "ü",
    "Ã­": "í", "Ã¬": "ì", "Ã®": "î", "Ã¯": "ï",
    "Ã±": "ñ", "Ã§": "ç",
    "Ã‰": "É", "Ã€": "À", "Ã‚": "Â", "ÃŠ": "Ê",
    # Non-breaking space variants masquerading
    "Â ": " ",
    "Â ": " ",
    # The � replacement character: drop it, it's literally
    # "the input had bad bytes" already.
    "�": "",
}

# Copyright / license / PG-boilerplate notice patterns. Each
# regex matches notice content that should be excised from
# otherwise-good prose. Patterns are line-oriented (with the
# multiline flag) so a single PG attribution line doesn't take
# the surrounding paragraph with it. Tuned to be specific —
# these only fire on text that is unambiguously legal / metadata
# boilerplate, not real prose that happens to mention copyright.
_NOTICE_PATTERNS: List[re.Pattern] = [
    # PG marker bands — the *** START / END ... *** delimiters.
    re.compile(
        r"\*{3,}\s*(START|END)\s+OF\s+(THE\s+|THIS\s+)?"
        r"PROJECT\s+GUTENBERG[^*]*\*{3,}",
        re.IGNORECASE),
    # Standalone "Project Gutenberg-tm / License / Foundation" lines.
    re.compile(
        r"(?m)^.*Project\s*Gutenberg(-tm)?\s*"
        r"(License|Literary\s+Archive|Foundation|Trademark|"
        r"Mission|Headquarters|copyright|donations?)[^\n]*$",
        re.IGNORECASE),
    # PG license preamble — "This eBook is for the use of anyone
    # anywhere…" can run for many sentences. We anchor on the
    # opening phrase and consume to the next blank line or end.
    re.compile(
        r"This eBook is for the use of anyone anywhere"
        r"[^\n]*(\n[^\n]+)*",
        re.IGNORECASE),
    # Producer / transcriber attribution lines.
    re.compile(
        r"(?m)^\s*Produced by\b[^\n]*$",
        re.IGNORECASE),
    re.compile(
        r"(?m)^\s*E-?text\s+(prepared|transcribed)\s+by\b[^\n]*$",
        re.IGNORECASE),
    re.compile(
        r"(?m)^\s*Transcribed?\s+(from|by)\b[^\n]*$",
        re.IGNORECASE),
    # Copyright lines.
    re.compile(
        r"(?m)^\s*Copyright\s*[\(\[]?\s*[Cc©]\s*[\)\]]?\s*"
        r"\d{4}[^\n]*$",
        re.IGNORECASE),
    re.compile(
        r"(?m)^\s*©\s*\d{4}[^\n]*$"),
    # All-rights-reserved / no-reproduction tags.
    re.compile(
        r"(?m)^\s*All\s+[Rr]ights\s+[Rr]eserved\.?\s*$"),
    re.compile(
        r"(?m)^\s*No\s+(part|portion)\s+of\s+this\s+"
        r"(book|work)\s+may\s+be\s+reproduced[^\n]*$",
        re.IGNORECASE),
    # Embedded license URLs.
    re.compile(
        r"https?://(www\.)?gutenberg\.org/(license|policy|wiki/Main_Page)[^\s]*",
        re.IGNORECASE),
    # HathiTrust / Internet Archive provenance lines.
    re.compile(
        r"(?m)^.*\b(Hathi\s*Trust|Internet\s*Archive)\b[^\n]*$",
        re.IGNORECASE),
    # ISBN / Library of Congress / Dewey catalog lines (front-matter).
    re.compile(
        r"(?m)^\s*ISBN[\s\d:-]+(?:\s+\(.+?\))?\s*$"),
    re.compile(
        r"(?m)^\s*Library\s+of\s+Congress\s+(Cataloging|Catalog\s+Card)"
        r"[^\n]*$",
        re.IGNORECASE),
]


def _strip_notices(text: str) -> str:
    """Apply every notice pattern to ``text``. Cheap — most rows
    don't trigger any of these so the regex sweep returns fast."""
    if not text:
        return text
    for pat in _NOTICE_PATTERNS:
        text = pat.sub("", text)
    return text


# Pre-compiled patterns so we don't re-compile per row.
_WORD_REP_RE = re.compile(
    r"\b(\w+)(\s+\1\b){" + str(WORD_REP_THRESHOLD - 1) + r",}",
    flags=re.IGNORECASE)
_CHAR_REP_RE = re.compile(
    r"([^\s])\1{" + str(CHAR_REP_THRESHOLD - 1) + r",}")
_HTML_ENT_RE = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-fA-F]+);")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
# Unicode whitespace that should be normal space. Excludes \t\n\r.
_WEIRD_WS_RE = re.compile(r"[   -   　]")
# Control chars: keep \t \n \r, drop everything else < 0x20
# plus the C1 controls (0x80–0x9f) which are never legitimate prose.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]")


def _fix_mojibake(text: str) -> str:
    """Apply the static mojibake table. Cheap and exhaustive — the
    full 50-pair sweep takes ~5 µs per row on typical prose."""
    if not text:
        return text
    for bad, good in _MOJIBAKE_MAP.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


def _decode_html_entities(text: str) -> str:
    """Run ``html.unescape`` only when the regex says there's
    something to decode. Avoids a no-op call on every row."""
    if "&" not in text:
        return text
    if not _HTML_ENT_RE.search(text):
        return text
    return html.unescape(text)


def _strip_ctrl(text: str) -> str:
    return _CTRL_RE.sub("", text)


def _collapse_word_reps(text: str) -> str:
    """Collapse N consecutive identical words to one.

    Case-insensitive match — preserves the casing of the first
    occurrence (what the user typed) so "The The The" → "The".
    """
    return _WORD_REP_RE.sub(lambda m: m.group(1), text)


def _collapse_char_reps(text: str) -> str:
    """Cap N consecutive identical chars at 3.

    Three is the sweet spot — preserves emphasis ("ohhh", "wow!!!")
    while killing garbage ("aaaaaaaaaaaaa", "!!!!!!!!!!").
    """
    return _CHAR_REP_RE.sub(lambda m: m.group(1) * 3, text)


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/blank lines, strip weird Unicode WS."""
    text = _WEIRD_WS_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text


# ── Public API ───────────────────────────────────────────────

def scrub(text: str, *,
          fix_word_rep: bool = True,
          fix_char_rep: bool = True,
          fix_html_ent: bool = True,
          fix_mojibake: bool = True,
          fix_ctrl: bool = True,
          fix_whitespace: bool = True,
          fix_notices: bool = True) -> Tuple[str, List[str]]:
    """Clean ``text`` in place, returning ``(cleaned, issue_tags)``.

    The returned tag list is empty when no changes were made — the
    caller can use ``not issues`` as the "no-op" indicator.

    Note: removing ``copyright_notice`` content can leave the row
    fully empty (when the row WAS the notice). Callers should
    check ``cleaned.strip() == ""`` and treat that as "delete row"
    rather than "update row to empty string"; ``apply_scrub``
    handles the fork automatically.
    """
    if not text:
        return text or "", []
    issues: List[str] = []
    out = text

    if fix_html_ent:
        new = _decode_html_entities(out)
        if new != out:
            issues.append(ISSUE_HTML_ENT)
            out = new
    if fix_mojibake:
        new = _fix_mojibake(out)
        if new != out:
            issues.append(ISSUE_MOJIBAKE)
            out = new
    if fix_ctrl:
        new = _strip_ctrl(out)
        if new != out:
            issues.append(ISSUE_CTRL_CHAR)
            out = new
    # Notices run BEFORE word/char/whitespace passes so the
    # downstream normalizers see the post-strip text and can
    # collapse any extra blank lines we just introduced.
    if fix_notices:
        new = _strip_notices(out)
        if new != out:
            issues.append(ISSUE_NOTICE)
            out = new
    if fix_word_rep:
        new = _collapse_word_reps(out)
        if new != out:
            issues.append(ISSUE_WORD_REP)
            out = new
    if fix_char_rep:
        new = _collapse_char_reps(out)
        if new != out:
            issues.append(ISSUE_CHAR_REP)
            out = new
    if fix_whitespace:
        new = _normalize_whitespace(out)
        if new != out:
            issues.append(ISSUE_WHITESPACE)
            out = new
    return out, issues


# ── Audit + apply ───────────────────────────────────────────

@dataclass
class ScrubExample:
    """One sample diff for the dialog's preview."""
    row_id: int
    issue: str          # which issue this example demonstrates
    before: str         # truncated original text
    after: str          # truncated cleaned text


@dataclass
class ScrubReport:
    """Results of ``audit_scrub_candidates``.

    ``per_issue_rows`` is a count of *distinct rows* that hit each
    issue. A row that has both word-rep and mojibake counts under
    both — these are not disjoint. ``rows_changed`` is the total
    distinct rows that would be mutated by at least one issue.

    ``rows_emptied`` is a subset of ``rows_changed`` where the
    cleaned text became empty (or whitespace-only) after notice
    stripping. Those rows would be DELETED on apply rather than
    updated — the user sees the count separately so they know
    how many rows the operation will remove from the DB.
    """
    total_rows: int = 0
    rows_changed: int = 0
    rows_emptied: int = 0
    per_issue_rows: Dict[str, int] = field(default_factory=dict)
    examples: Dict[str, List[ScrubExample]] = field(default_factory=dict)
    emptied_examples: List[ScrubExample] = field(default_factory=list)


def audit_scrub_candidates(
    db,
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    examples_per_issue: int = 5,
) -> ScrubReport:
    """Scan every accepted row, tallying which would change if
    each issue category were applied.

    Doesn't mutate anything — just builds the report. Per-issue
    flags use the defaults from ``scrub`` (all enabled) so the
    audit reflects the most-aggressive case; the user opts back
    in selectively at apply time.
    """
    progress = on_progress or (lambda *_: None)
    report = ScrubReport()
    for issue in ALL_ISSUES:
        report.per_issue_rows[issue] = 0
        report.examples[issue] = []

    with db._conn() as c:
        report.total_rows = int(c.execute(
            "SELECT COUNT(*) FROM rephrases WHERE accepted = 1"
        ).fetchone()[0])
        if report.total_rows == 0:
            return report

        progress(0, report.total_rows, "scanning rows")
        cur = c.execute(
            "SELECT id, output_text FROM rephrases "
            "WHERE accepted = 1")
        i = 0
        for row in cur:
            i += 1
            if i % 5000 == 0:
                progress(i, report.total_rows, "scanning rows")
            text = row["output_text"] or ""
            cleaned, issues = scrub(text)
            if not issues:
                continue
            report.rows_changed += 1
            # Notice-stripping can leave a row fully empty when
            # the row WAS the notice. We track those separately
            # so the dialog can warn that rows will be deleted
            # (not just updated).
            if not cleaned.strip():
                report.rows_emptied += 1
                if len(report.emptied_examples) < examples_per_issue:
                    report.emptied_examples.append(ScrubExample(
                        row_id=int(row["id"]),
                        issue="emptied_after_strip",
                        before=text[:240],
                        after="",
                    ))
            for issue in issues:
                report.per_issue_rows[issue] += 1
                if len(report.examples[issue]) < examples_per_issue:
                    # Snip both sides so the dialog can render a
                    # before/after pair without overflowing.
                    report.examples[issue].append(ScrubExample(
                        row_id=int(row["id"]),
                        issue=issue,
                        before=text[:240],
                        after=cleaned[:240],
                    ))
        progress(report.total_rows, report.total_rows, "scanning rows")
    return report


@dataclass
class ScrubPlan:
    """User's per-issue approval. Applied to every row at apply
    time; rows that no longer change after the selected subset
    are skipped (the dry-run audit may have flagged them based
    on a different issue you didn't approve).
    """
    fix_word_rep: bool = False
    fix_char_rep: bool = False
    fix_html_ent: bool = False
    fix_mojibake: bool = False
    fix_ctrl: bool = False
    fix_whitespace: bool = False
    fix_notices: bool = False

    @property
    def has_any(self) -> bool:
        return any([
            self.fix_word_rep, self.fix_char_rep, self.fix_html_ent,
            self.fix_mojibake, self.fix_ctrl, self.fix_whitespace,
            self.fix_notices,
        ])


def apply_scrub(
    db,
    plan: ScrubPlan,
    *,
    backup_path: Optional[Any] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, int]:
    """Mutate every accepted row whose ``output_text`` would change
    under the approved flags. Two outcomes per row:

      * ``cleaned.strip() != ""`` — UPDATE the row with the new
        text.
      * ``cleaned.strip() == ""`` — DELETE the row. (Notice
        stripping is the usual cause: the row WAS the notice, and
        emptying it leaves nothing trainable behind.)

    Writes a JSONL backup of every affected row's *prior* state
    so the operation is reversible. The backup tags each entry
    with ``action: "update"`` or ``action: "delete"`` so a future
    restore can replay the right SQL.

    Returns ``{"rows_updated": U, "rows_deleted": D, "rows_scanned": M}``.
    """
    progress = on_progress or (lambda *_: None)
    if not plan.has_any:
        return {"rows_updated": 0, "rows_deleted": 0,
                "rows_scanned": 0}

    import json as _json

    with db._conn() as c:
        total = int(c.execute(
            "SELECT COUNT(*) FROM rephrases WHERE accepted = 1"
        ).fetchone()[0])
        progress(0, total, "applying scrub")

        backup_fh = None
        if backup_path is not None:
            backup_fh = open(backup_path, "w", encoding="utf-8")

        try:
            cur = c.execute(
                "SELECT * FROM rephrases WHERE accepted = 1")
            rows = cur.fetchall()  # materialize so the UPDATE/DELETE
                                   # cursors don't conflict.
            updates: List[Tuple[str, int]] = []
            deletes: List[int] = []
            for i, row in enumerate(rows, 1):
                if i % 2000 == 0:
                    progress(i, total, "applying scrub")
                text = row["output_text"] or ""
                cleaned, issues = scrub(
                    text,
                    fix_word_rep=plan.fix_word_rep,
                    fix_char_rep=plan.fix_char_rep,
                    fix_html_ent=plan.fix_html_ent,
                    fix_mojibake=plan.fix_mojibake,
                    fix_ctrl=plan.fix_ctrl,
                    fix_whitespace=plan.fix_whitespace,
                    fix_notices=plan.fix_notices,
                )
                if cleaned == text:
                    continue
                rid = int(row["id"])
                empty_after = not cleaned.strip()
                if backup_fh is not None:
                    record = dict(row)
                    record["_scrub_action"] = (
                        "delete" if empty_after else "update")
                    record["_scrub_issues"] = issues
                    backup_fh.write(_json.dumps(record, default=str) + "\n")
                if empty_after:
                    deletes.append(rid)
                else:
                    updates.append((cleaned, rid))

            progress(total, total, "applying scrub")
            if backup_fh is not None:
                backup_fh.close()

            # Apply UPDATEs in chunks to avoid a single mega-
            # transaction holding the DB lock for too long.
            CHUNK = 500
            if updates:
                progress(0, len(updates), "writing updates")
                for j in range(0, len(updates), CHUNK):
                    chunk = updates[j:j + CHUNK]
                    c.executemany(
                        "UPDATE rephrases SET output_text = ? "
                        "WHERE id = ?",
                        chunk)
                    progress(j + len(chunk), len(updates),
                             "writing updates")
            if deletes:
                progress(0, len(deletes), "deleting emptied rows")
                for j in range(0, len(deletes), CHUNK):
                    chunk = deletes[j:j + CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    c.execute(
                        f"DELETE FROM rephrases "
                        f"WHERE id IN ({placeholders})",
                        chunk)
                    progress(j + len(chunk), len(deletes),
                             "deleting emptied rows")
        except Exception:
            if backup_fh is not None and not backup_fh.closed:
                backup_fh.close()
            raise

    return {"rows_updated": len(updates),
            "rows_deleted": len(deletes),
            "rows_scanned": total}
