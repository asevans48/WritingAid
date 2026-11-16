"""The writer's personal style sheet.

Rules come from three places:
  * the writer types them ("allow vethari", "prefer grey over gray",
    "avoid very", "keep passive", or any free-text note);
  * the companion learns them: ignoring the same kind of style flag three
    times, ignoring a word twice, or cutting the same word three times
    proposes a rule (as a suggestion, until the writer keeps it);
  * 💬 Ask: "it's deliberate — remember that" adds one.

The checks read them (allowed words aren't spelling or overuse errors,
kept style kinds aren't flagged, preferred spellings and avoided words
are), and every AI judge and rewrite prompt sees them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# Style kinds a writer can keep, by the names they'd use.
KIND_NAMES = {
    "passive": "passive", "passive voice": "passive", "passives": "passive",
    "adverb": "adverb", "adverbs": "adverb", "ly adverbs": "adverb",
    "intensifier": "intensifier", "intensifiers": "intensifier",
    "wordy": "wordy", "wordy phrases": "wordy", "cliche": "cliche", "cliches": "cliche",
    "clichés": "cliche", "long sentences": "long_sentence", "long sentence": "long_sentence",
    "hard sentences": "hard_sentence", "sticky sentences": "sticky_sentence",
    "repeated starts": "repeated_start", "repeated openings": "repeated_start",
    "echoes": "echo", "echo": "echo",
}
KIND_LABELS = {"passive": "passive voice", "adverb": "-ly adverbs", "intensifier": "intensifiers",
               "wordy": "wordy phrases", "cliche": "clichés", "long_sentence": "long sentences",
               "hard_sentence": "hard sentences", "sticky_sentence": "sticky sentences",
               "repeated_start": "repeated sentence openings", "echo": "echoes"}

# Learned-rule thresholds.
IGNORES_TO_KEEP_KIND = 3
IGNORES_TO_ALLOW_WORD = 2
FIXES_TO_AVOID_WORD = 3


def parse(text: str) -> Dict[str, str]:
    """"allow vethari" / "prefer grey over gray" / "avoid very" / "keep
    passive voice" → kind, subject, replacement; anything else is a note."""
    t = " ".join((text or "").split()).strip().rstrip(".")
    low = t.lower()
    m = re.match(r"^(?:prefer|use)\s+[\"“']?(.+?)[\"”']?\s+(?:over|instead of|not|to)\s+[\"“']?(.+?)[\"”']?$",
                 low)
    if m:
        return {"kind": "prefer", "subject": m.group(2), "replacement": m.group(1)}
    m = re.match(r"^[\"“']?(.+?)[\"”']?,?\s+not\s+[\"“']?(.+?)[\"”']?$", low)
    if m and len(m.group(1).split()) <= 3 and len(m.group(2).split()) <= 3:
        return {"kind": "prefer", "subject": m.group(2), "replacement": m.group(1)}
    m = re.match(r"^(?:allow|accept|ok|okay)\s+[\"“']?(.+?)[\"”']?$", low)
    if m:
        return {"kind": "allow", "subject": m.group(1), "replacement": ""}
    m = re.match(r"^[\"“']?(\S+?)[\"”']? is (?:a )?(?:real |valid )?word$", low)
    if m:
        return {"kind": "allow", "subject": m.group(1), "replacement": ""}
    m = re.match(r"^(?:avoid|cut|never use|always cut)\s+[\"“']?(.+?)[\"”']?$", low)
    if m:
        return {"kind": "avoid", "subject": m.group(1), "replacement": ""}
    m = re.match(r"^(?:keep|keeps|allow|i like|fine with)\s+(?:my\s+)?(.+)$", low)
    if m and m.group(1) in KIND_NAMES:
        return {"kind": "keep", "subject": KIND_NAMES[m.group(1)], "replacement": ""}
    return {"kind": "note", "subject": "", "replacement": ""}


def describe(kind: str, subject: str, replacement: str = "") -> str:
    if kind == "allow":
        return f"“{subject}” is a word — don't flag it"
    if kind == "prefer":
        return f"“{replacement}”, not “{subject}”"
    if kind == "avoid":
        return f"Avoid “{subject}”"
    if kind == "keep":
        return f"Keeps {KIND_LABELS.get(subject, subject)} on purpose — flag only clear problems"
    return subject


def rules(project: Any, *, include_suggested: bool = False) -> list:
    out = list(getattr(project, "style_sheet", None) or [])
    return out if include_suggested else [r for r in out if r.status == "active"]


def add(project: Any, text: str, *, source: str = "manual", suggested: bool = False,
        kind: str = "", subject: str = "", replacement: str = ""):
    """Add a rule (parsed from ``text`` unless ``kind`` is given); a
    duplicate is skipped (a suggested one is kept). Returns the rule or None."""
    from src.models.project import StyleRule
    if project is None or not (text or subject):
        return None
    if not kind:
        parsed = parse(text)
        kind, subject, replacement = parsed["kind"], parsed["subject"], parsed["replacement"]
    shown = describe(kind, subject, replacement) if kind != "note" else " ".join(text.split())
    for r in getattr(project, "style_sheet", None) or []:
        same = (r.kind == kind and r.subject.lower() == (subject or "").lower()
                and r.replacement.lower() == (replacement or "").lower())
        if same if kind != "note" else r.text.lower() == shown.lower():
            if not suggested and r.status == "suggested":
                r.status = "active"
                return r
            return None
    rule = StyleRule(text=shown[:300], kind=kind, subject=subject or "", replacement=replacement or "",
                     status="suggested" if suggested else "active", source=source)
    project.style_sheet.append(rule)
    return rule


def remove(project: Any, rule_id: str) -> None:
    project.style_sheet = [r for r in project.style_sheet if r.id != rule_id]


def accept(project: Any, rule_id: str) -> None:
    for r in project.style_sheet:
        if r.id == rule_id:
            r.status = "active"


# ── What the checks use ──────────────────────────────────────────────

def allowed_words(project: Any) -> Set[str]:
    return {r.subject.lower() for r in rules(project) if r.kind == "allow" and r.subject}


def kept_kinds(project: Any) -> Set[str]:
    return {r.subject for r in rules(project) if r.kind == "keep" and r.subject}


def preferences(project: Any) -> List[Tuple[str, str]]:
    """(disfavoured, preferred) pairs, plus avoided words (preferred = "")."""
    out = [(r.subject, r.replacement) for r in rules(project) if r.kind == "prefer" and r.subject]
    out += [(r.subject, "") for r in rules(project) if r.kind == "avoid" and r.subject]
    return out


def prompt_block(project: Any) -> str:
    active = rules(project)
    if not active:
        return ""
    return ("THE AUTHOR'S STYLE SHEET (their own rules — respect them):\n"
            + "\n".join(f"- {r.text}" for r in active[:20]))


def preference_issues(project: Any, paragraph: str):
    """StyleIssues (kind "preference") for disfavoured spellings and avoided
    words in ``paragraph``."""
    from src.utils.style_checks import StyleIssue
    out = []
    for old, new in preferences(project):
        rx = re.compile(rf"(?<![A-Za-z']){re.escape(old)}(?![A-Za-z'])", re.I)
        for m in rx.finditer(paragraph or ""):
            found = m.group(0)
            fix = new
            if fix and found[:1].isupper():
                fix = fix[:1].upper() + fix[1:]
            message = (f"“{new}”, not “{old}”." if new else
                       f"avoid “{old}”.")
            out.append(StyleIssue("preference", m.start(), m.end(), found, message,
                                  [fix] if new else [""]))
    return out


# ── Learning from what the writer does ───────────────────────────────

def record(project: Any, signal: str, subject: str) -> Optional[Any]:
    """Count a signal ("ignore_style", "ignore_word", "fix_word"); propose a
    rule (suggested) when it crosses its threshold. Returns that rule."""
    if project is None or not subject:
        return None
    from src.data import companion_state as cs
    data = cs.load(project)
    counts = data.setdefault("signals", {})
    k = f"{signal}:{subject.lower()}"
    counts[k] = counts.get(k, 0) + 1
    cs.save(project, data)
    n = counts[k]
    if signal == "ignore_style" and n == IGNORES_TO_KEEP_KIND and subject in KIND_LABELS:
        return add(project, "", source="learned", suggested=True, kind="keep", subject=subject)
    if signal == "ignore_word" and n == IGNORES_TO_ALLOW_WORD:
        return add(project, "", source="learned", suggested=True, kind="allow",
                   subject=subject.lower())
    if signal == "fix_word" and n == FIXES_TO_AVOID_WORD:
        return add(project, "", source="learned", suggested=True, kind="avoid",
                   subject=subject.lower())
    return None


DELIBERATE_CUES = re.compile(
    r"\b(?:deliberate(?:ly)?|intentional(?:ly)?|on purpose|i meant (?:it|that)|keep (?:it|that|this)|"
    r"leave (?:it|that|this)|that'?s (?:fine|ok|okay|my style)|it'?s my style|i like (?:it|that)|"
    r"remember (?:that|this))\b", re.I)


def rule_for_flag(project: Any, category: str, text: str, kind: str = "", message: str = ""):
    """The rule that says "this flag is deliberate": allow the word,
    keep the style kind, or a note quoting the grammar rule."""
    if category in ("spelling", "overuse"):
        return add(project, "", source="ask", kind="allow", subject=(text or "").lower())
    if category == "style" and kind in KIND_LABELS:
        return add(project, "", source="ask", kind="keep", subject=kind)
    note = f"Deliberate: {message or text}"[:200]
    return add(project, note, source="ask", kind="note")
