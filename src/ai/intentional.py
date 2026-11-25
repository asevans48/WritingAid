"""This is intentional (piece 4.1): a quirk becomes a rule of the book.

One function, ``mark``, used everywhere the writer can say a flag is
meant: the Critique's "That's intended" (``editor_pass.set_intended``),
the editor's right-click "This is intentional" (``intentional_menu``) and
the next-fix card's "it's intentional" link. It does two things, in the
two stores that already exist (no new store):

* **Dismisses the pattern** in the project's readiness file, under
  ``"dismissed"`` (the store 3.3 uses), marked ``"as": "intended"``. Every
  report applies it in every chapter and after a restart
  (``readiness._finish``), and the editor's underlines leave it out
  (``hide_intended``, used by ``editor_flags``).
* **Adds a line to the writer's style sheet** (``project.style_sheet``,
  the Companion's Style sheet section, read by every model prompt): the
  word is allowed (spelling, a repeated word), or a note quoting the
  passage. The writer can reword or delete it there. The dismissal keeps
  the rule's id (``"rule"``), so taking one back takes back both
  (``unmark``, ``rule_removed``).

"Not a problem" (3.3) goes through the same store with ``"as": "not a
problem"`` and no style sheet line.

Older files: an entry without ``"as"`` (the Critique before 4.1) is an
intended one, as ``editor_pass.intended`` has always read it. Keys this
module adds (``"as"``, ``"rule"``) are ignored by older versions.

No Qt.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

INTENDED = "intended"
NOT_A_PROBLEM = "not a problem"
SOURCE = "intended"                 # the style sheet rule's ``source``


# ── The pattern key of an editor flag ────────────────────────────────

def flag_key(error: Any) -> str:
    """The readiness key of an editor flag (``WritingError``): the same
    key the check that counts it uses, so a dismissal applies to both."""
    from src.utils.editor_flags import ErrorType
    t = getattr(error, "error_type", None)
    word = str(getattr(error, "word", "") or "")
    if t == ErrorType.SPELLING:
        return f"spelling:{word.lower()}"
    if t == ErrorType.GRAMMAR:
        return f"grammar:{getattr(error, 'rule_id', '') or 'builtin'}:{word.lower()}"
    if t in (ErrorType.OVERUSE, ErrorType.OVERUSED_PHRASE):
        return f"repetition:{word.lower()}"
    if t == ErrorType.STYLE:
        return f"{getattr(error, 'style_kind', '')}:{word.strip().lower()[:80]}"
    return ""


def style_key(issue: Any) -> str:
    """The key of a ``StyleIssue`` (as the line checks make it)."""
    return f"{issue.kind}:{issue.text.strip().lower()[:80]}"


# ── Which keys are intended (cached by the file's stamp) ─────────────

_cache: Dict[str, Tuple[Any, Set[str]]] = {}


def _stamp(project: Any):
    from src.data import readiness_state as rs
    path = rs.read_path(project)
    try:
        st = path.stat()
        return str(path), (st.st_mtime_ns, st.st_size)
    except OSError:
        return str(path), None


def intended_keys(project: Any) -> Set[str]:
    """Pattern keys the writer said to leave: "intended" and, since the
    writer's answer of 24 November 2026, "not a problem" too, so the editor
    stops underlining a pattern however it was dismissed."""
    if project is None:
        return set()
    try:
        path, stamp = _stamp(project)
        hit = _cache.get(path)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        keys: Set[str] = set()
        if stamp is not None:
            from src.data import readiness_state as rs
            d = rs.load(project).get("dismissed")
            if isinstance(d, dict):
                keys = {k for k, v in d.items() if isinstance(v, dict)}
        if len(_cache) > 50:
            _cache.clear()
        _cache[path] = (stamp, keys)
        return keys
    except Exception:
        return set()


def hide_intended(project: Any, errors: List[Any]) -> List[Any]:
    """``errors`` without the flags whose pattern is intended."""
    keys = intended_keys(project) if errors else set()
    return [e for e in errors if flag_key(e) not in keys] if keys else errors


def hide_intended_issues(project: Any, issues: List[Any]) -> List[Any]:
    keys = intended_keys(project) if issues else set()
    return [i for i in issues if style_key(i) not in keys] if keys else issues


def _forget() -> None:
    _cache.clear()


# ── Marking and taking back ──────────────────────────────────────────

def rule_line(label: str, text: str) -> str:
    """The style sheet line for a quirk the checks have no rule kind for."""
    quote = " ".join((text or "").split())
    quote = quote if len(quote) <= 120 else quote[:119] + "…"
    return f"Intentional ({label}): “{quote}”" if label else f"Intentional: “{quote}”"


def _add_rule(project: Any, category: str, word: str, label: str, text: str):
    """The style sheet line, or None when the same one is already there
    (then nothing is linked, so taking this back leaves the writer's own)."""
    from src.ai import style_sheet as ss
    if getattr(project, "style_sheet", None) is None:
        return None
    word = (word or "").strip()
    if category in ("spelling", "overuse") and word and " " not in word:
        return ss.add(project, "", source=SOURCE, kind="allow", subject=word.lower())
    return ss.add(project, rule_line(label, text or word), source=SOURCE, kind="note")


def store(project: Any, key: str, entry: Dict[str, Any]) -> bool:
    """Write one dismissal (every other key in the file is kept)."""
    from src.data import readiness_state as rs

    def change(data):
        d = data.get("dismissed")
        if not isinstance(d, dict):
            d = data["dismissed"] = {}
        d[key] = entry
    ok = bool(rs.update(project, change))
    _forget()
    return ok


def mark(project: Any, key: str, text: str, reason: str = "", label: str = "",
         chapter: str = "", *, category: str = "", word: str = "",
         rule: bool = True) -> Tuple[bool, Any]:
    """This is intentional: dismiss the pattern ``key`` in this project and
    (``rule``) add a style sheet line. ``category``: spelling | overuse
    (the word is allowed) or anything else (a note quoting ``text``).
    Returns (saved, the rule added or None)."""
    if project is None or not key:
        return False, None
    added = _add_rule(project, category, word, label, text) if rule else None
    entry = {"text": (text or "")[:200], "reason": (reason or "")[:300], "label": label,
             "chapter": chapter, "at": time.strftime("%Y-%m-%d"), "as": INTENDED}
    if added is not None:
        entry["rule"] = added.id
    saved = store(project, key, entry)
    if not saved and added is not None:              # keep the two stores together
        from src.ai import style_sheet as ss
        ss.remove(project, added.id)
        added = None
    return saved, added


def mark_item(project: Any, item: Any, label: str, chapter: str = "",
              rule: bool = True) -> Tuple[bool, Any]:
    """``mark`` for a readiness ``Item`` (the Critique, the queue)."""
    kind = getattr(item, "kind", "") or ""
    category = ("spelling" if kind == "spelling" else
                "overuse" if kind == "word" and str(getattr(item, "key", "")).startswith(
                    "repetition:") else "")
    return mark(project, getattr(item, "key", "") or "", getattr(item, "text", "") or "",
                getattr(item, "reason", "") or "", label, chapter, category=category,
                word=getattr(item, "text", "") or "", rule=rule)


def unmark(project: Any, key: str) -> Tuple[bool, Optional[str]]:
    """Take it back: the dismissal goes, and the style sheet line it added.
    Returns (saved, the removed rule's id or None)."""
    from src.data import readiness_state as rs
    removed: List[str] = []

    def change(data):
        d = data.get("dismissed")
        if isinstance(d, dict):
            entry = d.pop(key, None)
            if isinstance(entry, dict) and entry.get("rule"):
                removed.append(str(entry["rule"]))
    saved = bool(rs.update(project, change))
    _forget()
    rule_id = removed[0] if removed else None
    if saved and rule_id and getattr(project, "style_sheet", None) is not None:
        from src.ai import style_sheet as ss
        ss.remove(project, rule_id)
    return saved, rule_id


def rule_removed(project: Any, rule_id: str) -> bool:
    """The writer deleted a style sheet line: the dismissals it made go
    too, so the quirk is flagged again. True when one went."""
    if project is None or not rule_id:
        return False
    from src.data import readiness_state as rs
    if not any(isinstance(v, dict) and v.get("rule") == rule_id
               for v in (rs.load(project).get("dismissed") or {}).values()):
        return False

    def change(data):
        d = data.get("dismissed")
        if isinstance(d, dict):
            for k in [k for k, v in d.items() if isinstance(v, dict) and v.get("rule") == rule_id]:
                d.pop(k, None)
    ok = bool(rs.update(project, change))
    _forget()
    return ok


def linked_rules(project: Any) -> Set[str]:
    """Ids of style sheet lines added by ``mark``."""
    try:
        from src.data import readiness_state as rs
        d = rs.load(project).get("dismissed")
        return {str(v["rule"]) for v in d.values() if isinstance(v, dict) and v.get("rule")} \
            if isinstance(d, dict) else set()
    except Exception:
        return set()


def reword(project: Any, rule_id: str, text: str) -> Any:
    """The writer rewords a style sheet line. A line that reads as a rule
    ("allow vethari", "keep passive voice") becomes that rule; any other
    wording is kept as written and the rule does what it did."""
    from src.ai import style_sheet as ss
    text = " ".join((text or "").split())[:300]
    if project is None or not text:
        return None
    for r in getattr(project, "style_sheet", None) or []:
        if r.id == rule_id:
            parsed = ss.parse(text)
            if parsed["kind"] != "note":
                r.kind, r.subject, r.replacement = (parsed["kind"], parsed["subject"],
                                                    parsed["replacement"])
                r.text = ss.describe(r.kind, r.subject, r.replacement)[:300]
            else:
                r.text = text
            return r
    return None
