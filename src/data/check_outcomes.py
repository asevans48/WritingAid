"""Checks earn their place (piece 4.3): how often each check's fixes are taken.

Counted per check, per project, in the project's readiness file under a new
top-level key (only added; an older app ignores it, a file without it means
zeros)::

    "outcomes": {
      "filler": {"accepted": 12, "skipped": 3, "not_a_problem": 9,
                 "intended": 1,
                 "restored": {"accepted": 2, "rejected": 18}},   # Bring it back
      "style:transition": {...}
    }

* **accepted**: the next-fix card's Accept, and "Fix all N like this" (N).
* **skipped**: Skip on the card. Skip is for the session only, so it is
  counted but never read as a rejection.
* **not_a_problem** / **intended**: every "leave it" goes through
  ``intentional.store`` (the one writer of a dismissal), which counts it
  here when the pattern was not already dismissed. The card's Not a
  problem for a style flag (a session ignore, not stored) is counted by the
  card. Both count as a rejection.

A check is **toned down** when, since it was last brought back, the writer
has answered at least ``MIN_ANSWERS`` of its fixes and accepted fewer than
``TONE_BELOW`` of them. Toned down means lower in the next-fix queue and
drawn fainter in the Critique, with the reason. It is never hidden and never
switched off: switching off is only ever offered, and the writer confirms it.
**Bring it back** stores the counts as they are now under ``"restored"``;
the check is judged again on the answers after that. The counts themselves
are never cleared.

Works whether or not training-data collection is on. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

KEY = "outcomes"
ACCEPTED, SKIPPED = "accepted", "skipped"
NOT_A_PROBLEM, INTENDED = "not_a_problem", "intended"
COUNTS = (ACCEPTED, SKIPPED, NOT_A_PROBLEM, INTENDED)
RESTORED = "restored"

MIN_ANSWERS = 20            # no check is judged on fewer answers than this
TONE_BELOW = 0.4            # accepted share under this: "mostly rejected"

# The style kinds a readiness check reports (``readiness_checks/line.py``,
# ``copyedit.py``); any other kind reaches the queue as "style:<kind>".
KIND_CHECK = {"echo": "echoes", "intensifier": "filler", "wordy": "filler",
              "passive": "passive", "adverb": "adverbs", "cliche": "cliches",
              "sticky_sentence": "sticky", "preference": "style_sheet"}
# Decision 3: spelling and overused words stay on; never offered to switch off.
STAYS_ON = frozenset({"spelling_grammar", "repetition"})


# ── Which check ──────────────────────────────────────────────────────

def check_for_kind(kind: str) -> str:
    """The check a style kind is counted under."""
    return KIND_CHECK.get(kind, f"style:{kind}")


def kinds_of(check: str) -> Set[str]:
    """The ✓ Checks ▾ style kinds that make up ``check`` (empty for a check
    with no switch of its own)."""
    if check.startswith("style:"):
        return {check[6:]}
    return {k for k, c in KIND_CHECK.items() if c == check}


def check_for_key(key: str, label: str = "") -> str:
    """The check a dismissal's pattern key belongs to, when the caller did
    not say: the editor's own flags by their key, otherwise by the label."""
    head = (key or "").split(":", 1)[0]
    if head in ("spelling", "grammar"):
        return "spelling_grammar"
    if head == "repetition":
        return "repetition"
    try:
        from src.utils.style_checks import KINDS
        if head in KINDS:
            return check_for_kind(head)
    except Exception:
        pass
    if label:
        try:
            from src.ai import readiness as rd
            rd._load_checks()
            for name, spec in rd.REGISTRY.items():
                if spec.label == label:
                    return name
        except Exception:
            pass
    return head


def check_for_error(error: Any) -> str:
    """The check an editor flag (``WritingError``) is counted under."""
    from src.ai import intentional
    return check_for_key(intentional.flag_key(error))


# ── Reading (cached on the file's stamp) ─────────────────────────────

_cache: Dict[str, Tuple[Any, Dict[str, Dict[str, Any]]]] = {}


def _clean(entry: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    entry = entry if isinstance(entry, dict) else {}
    for k in COUNTS:
        try:
            out[k] = max(0, int(entry.get(k, 0) or 0))
        except (TypeError, ValueError):
            out[k] = 0
    r = entry.get(RESTORED)
    if isinstance(r, dict):
        out[RESTORED] = {k: _int(r.get(k)) for k in ("accepted", "rejected")}
    return out


def _int(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def counts(project: Any) -> Dict[str, Dict[str, Any]]:
    """Every check's counts in this project ({} until one is answered)."""
    if project is None:
        return {}
    try:
        from src.data import readiness_state as rs
        path = rs.read_path(project)
        try:
            st = path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            return {}
        hit = _cache.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        raw = rs.load(project).get(KEY)
        data = ({str(k): _clean(v) for k, v in raw.items()} if isinstance(raw, dict) else {})
        if len(_cache) > 50:
            _cache.clear()
        _cache[str(path)] = (stamp, data)
        return data
    except Exception:
        return {}


@dataclass
class Outcome:
    check: str
    accepted: int = 0
    skipped: int = 0
    not_a_problem: int = 0
    intended: int = 0
    since_accepted: int = 0      # since it was last brought back
    since_rejected: int = 0

    @property
    def rejected(self) -> int:
        return self.not_a_problem + self.intended

    @property
    def answers(self) -> int:
        return self.accepted + self.rejected

    @property
    def toned_down(self) -> bool:
        judged = self.since_accepted + self.since_rejected
        return judged >= MIN_ANSWERS and self.since_accepted < TONE_BELOW * judged

    def rate_line(self) -> str:
        """For a tooltip: how often its fixes are taken here."""
        if not self.answers and not self.skipped:
            return "No fixes answered yet in this project."
        line = (f"Fixes accepted here: {self.accepted} of {self.answers} "
                f"({round(100 * self.accepted / self.answers)}%)" if self.answers
                else "No fixes accepted or turned down yet")
        extra = []
        if self.rejected:
            extra.append(f"{self.rejected} not a problem or intended")
        if self.skipped:
            extra.append(f"{self.skipped} skipped")
        return line + (f"; {', '.join(extra)}." if extra else ".")

    def toned_line(self) -> str:
        """Why it is toned down."""
        judged = self.since_accepted + self.since_rejected
        return (f"Toned down for this book: you turned down {self.since_rejected} of its "
                f"last {judged} fixes. It's lower in the next-fix list and fainter here; "
                "it still runs.")


def outcome(project: Any, check: str) -> Outcome:
    entry = counts(project).get(check) or _clean({})
    o = Outcome(check, *(entry[k] for k in COUNTS))
    r = entry.get(RESTORED) or {"accepted": 0, "rejected": 0}
    o.since_accepted = max(0, o.accepted - r["accepted"])
    o.since_rejected = max(0, o.rejected - r["rejected"])
    return o


def toned_down(project: Any) -> Set[str]:
    """The checks toned down in this project."""
    return {c for c in counts(project) if outcome(project, c).toned_down}


# ── Writing ──────────────────────────────────────────────────────────

def _entry(data: Dict[str, Any], check: str) -> Dict[str, Any]:
    table = data.get(KEY)
    if not isinstance(table, dict):
        table = data[KEY] = {}
    entry = table.get(check)
    if not isinstance(entry, dict):
        entry = table[check] = {}
    return entry


def count_into(data: Dict[str, Any], check: str, what: str, n: int = 1) -> None:
    """Add to a count inside a readiness file being changed (for
    ``intentional.store``, so the dismissal and its count are one save)."""
    if not check or what not in COUNTS or not n:
        return
    entry = _entry(data, check)
    entry[what] = max(0, _int(entry.get(what)) + n)


def record(project: Any, check: str, what: str, n: int = 1) -> bool:
    """Count ``n`` answers of kind ``what`` for ``check`` (negative to take
    back a misclick that was undone). Never raises."""
    if project is None or not check or what not in COUNTS or not n:
        return False
    try:
        from src.data import readiness_state as rs
        return bool(rs.update(project, lambda data: count_into(data, check, what, n)))
    except Exception as e:                       # noqa: BLE001
        print(f"[check_outcomes] could not count: {e}")
        return False


def bring_back(project: Any, check: str) -> bool:
    """Clear the toning (not the counts): judge it again from now on."""
    if project is None or not check:
        return False
    o = outcome(project, check)

    def change(data):
        _entry(data, check)[RESTORED] = {"accepted": o.accepted, "rejected": o.rejected}
    try:
        from src.data import readiness_state as rs
        return bool(rs.update(project, change))
    except Exception as e:                       # noqa: BLE001
        print(f"[check_outcomes] could not bring it back: {e}")
        return False


def label_of(check: str) -> str:
    """A check's name as the writer sees it."""
    if check.startswith("style:"):
        from src.utils.style_checks import KINDS
        kind = check[6:]
        return KINDS[kind][0] if kind in KINDS else kind
    try:
        from src.ai import readiness as rd
        rd._load_checks()
        spec = rd.REGISTRY.get(check)
        return spec.label if spec else check
    except Exception:
        return check


def can_switch_off(check: str, ticked: Optional[Set[str]] = None) -> Set[str]:
    """The ✓ Checks ▾ style kinds that would switch ``check`` off (those
    still ticked); empty for spelling and overused words, which stay on."""
    if check in STAYS_ON:
        return set()
    kinds = kinds_of(check)
    return kinds & ticked if ticked is not None else kinds
