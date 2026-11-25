"""Chapter stages (piece 3.1).

Each chapter is at one stage of the path to publish: structure, scene,
line, copyedit, proof (``readiness.STAGES``). **The writer moves chapters;
the app only suggests.** When every check of a chapter's stage passes, the
scorecard and the Companion suggest moving on.

* **Stored** as ``"stage"`` in the chapter's entry of the readiness file
  (``readiness.json`` → manuscripts → scope → chapters → id), which the
  readiness report already reads. Results are stored beside it without
  touching it. Every write goes through ``readiness_state.update``.
* **Not set** is a stage of its own: a chapter nobody has placed is shown
  as "No stage", and the queue (3.2) offers it everything, as before.
* **By hand or by asking.** The scorecard and the Companion set it; so does
  the assistant ("move chapters 3 to 7 to copyedit", "put the novella back
  to line"). Both go through ``set_stage``, so they are stored the same
  way, and either can be changed by the other afterwards.
* **Novellas** keep their own stages (the scope is part of the key).

No Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.ai.readiness import STAGES, STAGE_LABELS

KEY = "stage"
NONE_LABEL = "No stage"


def label(stage: str) -> str:
    return STAGE_LABELS.get(stage, NONE_LABEL) if stage else NONE_LABEL


def next_stage(stage: str) -> Optional[str]:
    if stage not in STAGES:
        return STAGES[0]
    i = STAGES.index(stage)
    return STAGES[i + 1] if i + 1 < len(STAGES) else None


# ── Reading and writing ─────────────────────────────────────────────

def stages(project: Any, scope: Optional[str]) -> Dict[str, str]:
    """{chapter id: stage} for one manuscript; chapters with none are left out."""
    from src.data import readiness_state as rs
    try:
        m = rs.load(project)["manuscripts"].get(rs.scope_key(scope), {})
        chapters = (m.get("chapters") or {}) if isinstance(m, dict) else {}
    except Exception:
        return {}
    return {cid: e[KEY] for cid, e in chapters.items()
            if isinstance(e, dict) and e.get(KEY) in STAGES}


def stage_of(project: Any, scope: Optional[str], chapter_id: str) -> str:
    return stages(project, scope).get(chapter_id, "")


def set_stage(project: Any, scope: Optional[str], chapter_ids: Iterable[str],
              stage: str, by: str = "hand") -> bool:
    """Put these chapters at ``stage`` ("" clears it). One save; the rest
    of each chapter's entry (its results) is kept."""
    from src.data import readiness_state as rs
    from src.ai.readiness import _now
    ids = [c for c in dict.fromkeys(chapter_ids) if c]
    if stage and stage not in STAGES:
        return False
    if not ids:
        return True

    def change(data):
        for cid in ids:
            entry = rs.chapter_entry(data, scope, cid)
            if stage:
                entry[KEY] = stage
                entry["stage_set"] = {"at": _now(), "by": by}
            else:
                entry.pop(KEY, None)
                entry.pop("stage_set", None)
    return bool(rs.update(project, change))


# ── The suggestion ──────────────────────────────────────────────────

def suggestion_for(stage: str, statuses: Dict[str, str]) -> Optional[str]:
    """The stage to move on to, when every counted check of ``stage`` is
    ready (and at least one was checked); else None. ``statuses``: check
    name → status."""
    from src.ai import readiness as rd
    if stage not in STAGES:
        return None
    rd._load_checks()
    verdicts = []
    for name, status in statuses.items():
        spec = rd.REGISTRY.get(name)
        if spec is None or spec.stage != stage or not spec.counts:
            continue
        if status in rd.Status.VERDICTS:
            verdicts.append(status)
    if verdicts and all(v == rd.Status.READY for v in verdicts):
        return next_stage(stage)
    return None


def suggestion(chapter_report: Any) -> Optional[str]:
    """``suggestion_for`` a chapter's report."""
    results = getattr(chapter_report, "results", None) or {}
    return suggestion_for(getattr(chapter_report, "stage", "") or "",
                          {n: r.status for n, r in results.items()})


# ── Asking the assistant ────────────────────────────────────────────

_STAGE_WORDS = {"structure": "structure", "structural": "structure", "developmental": "structure",
                "scene": "scene", "scenes": "scene", "line": "line", "line edit": "line",
                "line editing": "line", "copyedit": "copyedit", "copy edit": "copyedit",
                "copyediting": "copyedit", "copy editing": "copyedit", "copy-edit": "copyedit",
                "proof": "proof", "proofs": "proof", "proofread": "proof",
                "proofreading": "proof"}
_STAGE_RX = "|".join(sorted((re.escape(w) for w in _STAGE_WORDS), key=len, reverse=True))
_REQUEST = re.compile(
    rf"^\s*(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?(?P<verb>move|put|set|send|bump|mark|"
    rf"change|take)\s+(?P<what>.+?)\s+(?:back\s+)?(?:in)?to\s+(?:the\s+)?"
    rf"(?P<stage>{_STAGE_RX})(?:\s+stage)?\s*(?:please)?[.!]?\s*$", re.I)
_NUM = r"(\d{1,3}|[ivxlc]+)"
_RANGE = re.compile(rf"\b{_NUM}\s*(?:-|–|—|to|through|thru)\s*{_NUM}\b", re.I)
_ONE = re.compile(rf"\b{_NUM}\b", re.I)


@dataclass
class Request:
    stage: str
    numbers: List[int] = field(default_factory=list)   # chapter numbers named
    every: bool = False                                  # "all chapters", "the novella"
    current: bool = False                                # "this chapter"
    manuscript: str = ""                                 # a manuscript's name, when named


def _roman(s: str) -> Optional[int]:
    s = s.lower()
    if s.isdigit():
        return int(s)
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    if not s or any(c not in values for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = values[c]
        total += -v if i + 1 < len(s) and values[s[i + 1]] > v else v
    return total


def parse_request(message: str, manuscript_names: Iterable[str] = ()) -> Optional[Request]:
    """A request to move chapters to a stage, or None. Conservative: only a
    clear "move … to <stage>" is one."""
    m = _REQUEST.match(message or "")
    if not m:
        return None
    what = m.group("what").strip()
    low = what.lower()
    if not re.search(r"\b(?:chapters?|ch\.?|novella|manuscript|book|novel|everything|all|"
                     r"it|this|these)\b", low):
        return None
    req = Request(stage=_STAGE_WORDS[m.group("stage").lower()])
    for name in sorted((n for n in manuscript_names if n), key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", low):
            req.manuscript = name
            low = low.replace(name.lower(), " ")
            break
    nums: List[int] = []
    for a, b in _RANGE.findall(low):
        x, y = _roman(a), _roman(b)
        if x is not None and y is not None and 0 < x <= y and y - x < 500:
            nums.extend(range(x, y + 1))
    rest = _RANGE.sub(" ", low)
    if re.search(r"\bchapters?\b|\bch\.?\s*\d", rest) or nums:
        for n in _ONE.findall(rest):
            v = _roman(n)
            if v and v not in nums and (n.isdigit() or re.search(
                    rf"\bchapters?\s+(?:[\w\s,]*\s)?{re.escape(n)}\b", rest)):
                nums.append(v)
    req.numbers = sorted(set(nums))
    if not req.numbers:
        if re.search(r"\b(?:this|current)\s+chapter\b|^(?:it|this)$", low.strip()):
            req.current = True
        elif re.search(r"\b(?:all|every|everything|whole|entire)\b|\bnovella\b|\bmanuscript\b|"
                       r"\bbook\b|\bnovel\b", low) or req.manuscript:
            req.every = True
        else:
            return None
    return req


def _novella_word(project: Any) -> Optional[str]:
    subs = list(getattr(project, "subprojects", None) or [])
    return subs[0].id if len(subs) == 1 else None


def resolve(project: Any, req: Request, current: Tuple[Optional[str], str] = (None, ""),
            message: str = "") -> Tuple[Optional[str], List[Any], str]:
    """(scope, chapters, problem). ``problem`` is "" when the request can
    be done, else what to tell the writer (and nothing is changed)."""
    scope: Optional[str] = current[0]
    if req.manuscript:
        for s, _ms in project.iter_manuscripts():
            if project.scope_label(s).lower() == req.manuscript.lower():
                scope = s
                break
    elif re.search(r"\bnovella\b", message or "", re.I) and not req.current:
        only = _novella_word(project)
        if only is None:
            names = [project.scope_label(s) for s, _ in project.iter_manuscripts() if s]
            if not names:
                return None, [], "This project has no novella."
            return None, [], ("Which novella? This project has " + ", ".join(names) + ".")
        scope = only
    ms = next((m for s, m in project.iter_manuscripts() if s == scope), None)
    chapters = list(getattr(ms, "chapters", None) or [])
    name = project.scope_label(scope)
    if req.current:
        chosen = [c for c in chapters if c.id == current[1]]
        if not chosen:
            return scope, [], "Open a chapter first, or name the chapters to move."
        return scope, chosen, ""
    if req.every:
        if not chapters:
            return scope, [], f"“{name}” has no chapters yet."
        return scope, chapters, ""
    by_number = {int(getattr(c, "number", 0) or 0): c for c in chapters}
    missing = [n for n in req.numbers if n not in by_number]
    if missing:
        listed = ", ".join(str(n) for n in missing)
        have = f"1–{max(by_number)}" if by_number else "none"
        return scope, [], (f"“{name}” has no chapter {listed} (its chapters are {have}). "
                           "Nothing was moved.")
    return scope, [by_number[n] for n in req.numbers], ""


def describe(project: Any, scope: Optional[str], chapters: List[Any], stage: str) -> str:
    """"Chapters 3–7 of “Book” to Copyedit" — for the confirmation and the reply."""
    nums = sorted(int(getattr(c, "number", 0) or 0) for c in chapters)
    if len(nums) == 1:
        what = f"chapter {nums[0]}" + (f" (“{chapters[0].title}”)"
                                       if getattr(chapters[0], "title", "") else "")
    elif nums == list(range(nums[0], nums[-1] + 1)):
        what = f"chapters {nums[0]}–{nums[-1]}"
    else:
        what = "chapters " + ", ".join(str(n) for n in nums)
    return f"{what} of “{project.scope_label(scope)}” to {label(stage)}"
