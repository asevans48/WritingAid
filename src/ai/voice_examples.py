"""Which rated rewrites a new rewrite learns from (piece V.4).

Suggestions, Rephrase, Expand, the Companion's fixes and the next-fix
queue all ask :func:`rewrite_quality.examples_prompt` for the writer's
rated rewrites; this module chooses them.

**Today's choice** (kept exactly when there is nothing to tell voices
apart): the 40 most recent rated rewrites of each kind, this project's
first; then "excellent" first, this project next, closest wording next.

**By voice** (README decision 5, strong groups). When there are two or
more voice groups (V.2) and the passage's source (project + narrator) is
in one:

1. Examples from the passage's group: "excellent" and this project's
   first, as today; within those, closest to the passage's voice
   fingerprint (V.1) first; then closest wording. One example per rated
   passage. (Pure closest-first scored a little lower on voice fit in the
   comparison, so today's two tiers stay in front: :data:`WITHIN_GROUP`.)
2. If the group has fewer than asked for (``chosen``, ``rejected``
   counted separately), the nearest group fills in, then the next.
3. Still short: today's choice fills the rest.

A passage whose source is Unsorted (too few ratings yet), and any passage
when there are fewer than two groups, learns as today from the whole
store.

**Kept to itself** (``ratings_privacy``): a project whose switch is on
never lends its ratings to another project; it still learns from its own
and from everyone else's. Applied in every case above.

Read only: nothing is written to the ratings database or the groups file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

KINDS = (("chosen", "rating IN ('excellent','good') AND accepted = 1"),
         ("rejected", "rating IN ('poor','bad')"))
MIN_GROUPS = 2          # with fewer, the examples are exactly today's
FROM_ALL = "from all your ratings"
# The order inside the passage's group: "tiers" (excellent and this
# project first, as today, then closest to the passage's voice, then
# wording), "closest" (voice first) or "today". "tiers" won the comparison
# (docs/publishing/voice_examples.md).
WITHIN_GROUP = "tiers"


@dataclass
class ExampleChoice:
    chosen: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    group_id: Optional[str] = None
    group_name: str = ""
    filled: bool = False        # the group had too few; others filled in

    @property
    def label(self) -> str:
        """Plain words for the writer: where the examples came from."""
        if not self.group_id:
            return FROM_ALL
        text = f"from your voice group “{self.group_name}”"
        return text + (", with the nearest group filling in" if self.filled else "")


# ── Today's ordering ─────────────────────────────────────────────────

def _usable(rows: Iterable[Dict[str, Any]], max_chars: int) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("source_text") and r.get("output_text")
            and len(r["source_text"]) <= max_chars and len(r["output_text"]) <= max_chars]


def today_key(passage: str, project_path: str) -> Callable[[Dict[str, Any]], float]:
    from src.ai.rewrite_quality import _overlap
    return lambda r: (-(r.get("rating") == "excellent")
                      - (r.get("project_path") == project_path) * 0.5
                      - _overlap(passage, r["source_text"]))


def today_pick(items, n: int, passage: str, project_path: str, max_chars: int):
    usable = _usable(items, max_chars)
    usable.sort(key=today_key(passage, project_path))
    return usable[:n]


# ── Kept to itself ───────────────────────────────────────────────────

def lent_filter(project_path: str) -> Callable[[Dict[str, Any]], bool]:
    """True for a rating this project may learn from."""
    from src.data import ratings_privacy
    seen: Dict[str, bool] = {}

    def ok(row: Dict[str, Any]) -> bool:
        pp = row.get("project_path") or ""
        if not pp or pp == (project_path or ""):
            return True
        if pp not in seen:
            seen[pp] = ratings_privacy.is_private(pp)
        return not seen[pp]
    return ok


# ── The choice ───────────────────────────────────────────────────────

def choose(passage: str, project_path: str = "", *, chosen: int = 2, rejected: int = 1,
           max_chars: int = 500, db: Any = None, before: str = "", after: str = "",
           character_name: str = "", state: Optional[Dict[str, Any]] = None) -> ExampleChoice:
    """The rated rewrites to show the model for ``passage``."""
    if db is None:
        from src.data.rephrase_database import get_rephrase_database
        db = get_rephrase_database()
    rows = db.rated_examples(project_path=project_path)
    ok = lent_filter(project_path)
    pool = {k: [r for r in rows.get(k, []) if ok(r)] for k, _ in KINDS}
    want = {"chosen": chosen, "rejected": rejected}
    out = ExampleChoice(**{k: today_pick(pool[k], want[k], passage, project_path, max_chars)
                           for k, _ in KINDS})
    try:
        by_voice = _by_voice(passage, project_path, want, pool, ok, db, max_chars,
                             before, after, character_name, state)
    except Exception as e:                       # noqa: BLE001 — never lose today's examples
        print(f"[examples] voice groups unavailable, using all ratings: {e}")
        by_voice = None
    return by_voice or out


def _by_voice(passage, project_path, want, pool, ok, db, max_chars, before, after,
              character_name, state) -> Optional[ExampleChoice]:
    from src.ai import voice_fingerprint as vf
    from src.ai import voice_groups as vg
    from src.data import voice_groups_store as vgs

    state = vg.normalise_state(state if state is not None else vgs.load_state())
    groups = state.get("groups") or {}
    if len(groups) < MIN_GROUPS:
        return None
    vector = vf.vector_of(vf.rating_text(before, passage, after))
    gid = vg.group_for(state, project_path, character_name, vector)
    if not gid or gid not in groups:
        return None

    fp_rows = vgs.read_rows(db)
    member = vg.membership(fp_rows, state)
    vectors = {int(r["id"]): r["vector"] for r in fp_rows
               if len(r.get("vector") or []) == len(vf.MEASURES)}
    scale = _scale(list(vectors.values()))
    here = np.asarray(vector, dtype=float) if vector is not None else None
    centres = _centres(member, vectors)
    anchor = here if here is not None else centres.get(gid)
    order = [gid] + sorted((g for g in centres if g != gid and g in groups),
                           key=lambda g: (_dist(anchor, centres[g], scale), g))

    ids = [i for i, g in member.items() if g in groups]
    rated = _rated_rows(db, ids)
    key = today_key(passage, project_path)

    def ranked(rows):
        rows = [r for r in _usable(rows, max_chars) if ok(r)]
        if WITHIN_GROUP == "closest":
            rows.sort(key=lambda r: (_dist(here, vectors.get(int(r["id"])), scale), key(r),
                                     -int(r["id"])))
        elif WITHIN_GROUP == "tiers":            # excellent / this project, then closest
            rows.sort(key=lambda r: (-(r.get("rating") == "excellent")
                                     - (r.get("project_path") == project_path) * 0.5,
                                     _dist(here, vectors.get(int(r["id"])), scale), key(r),
                                     -int(r["id"])))
        else:                                    # today's order inside the group
            rows.sort(key=lambda r: (key(r), -int(r["id"])))
        seen, kept = set(), []
        for r in rows:                           # one example per rated passage
            s = " ".join(r["source_text"].split())
            if s not in seen:
                seen.add(s)
                kept.append(r)
        return kept

    out = ExampleChoice(group_id=gid, group_name=vg.display_name(groups[gid]))
    for kind, _ in KINDS:
        n, picked, taken = want[kind], [], set()
        for g in order:
            if len(picked) >= n:
                break
            for r in ranked([r for r in rated[kind] if member.get(int(r["id"])) == g]):
                if len(picked) >= n:
                    break
                picked.append(r)
                taken.add(int(r["id"]))
        if len(picked) < n:                      # still short: today's choice fills in
            rest = [r for r in pool[kind] if int(r.get("id", -1)) not in taken]
            picked += today_pick(rest, n - len(picked), passage, project_path, max_chars)
        setattr(out, kind, picked)
    out.filled = any(member.get(int(r.get("id", -1))) != gid for r in out.chosen + out.rejected)
    return out


def _rated_rows(db, ids: Sequence[int]) -> Dict[str, List[Dict[str, Any]]]:
    """The grouped ratings of each kind, read only."""
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k, _ in KINDS}
    if not ids:
        return out
    conn = db._conn()
    ids = list(ids)
    for kind, where in KINDS:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"SELECT * FROM rephrases WHERE id IN ({marks}) AND source_type = 'rephrase' "
                f"AND {where}", chunk)
            out[kind] += [dict(r) for r in cur.fetchall()]
    return out


def _scale(vectors: List[Sequence[float]]) -> Optional[np.ndarray]:
    if len(vectors) < 2:
        return None
    s = np.asarray(vectors, dtype=float).std(axis=0)
    return np.where(s > 1e-9, s, np.inf)        # a measure that never varies is skipped


def _centres(member: Dict[int, str], vectors: Dict[int, Sequence[float]]) -> Dict[str, np.ndarray]:
    by: Dict[str, List[Sequence[float]]] = {}
    for i, g in member.items():
        if i in vectors and g != "unsorted":
            by.setdefault(g, []).append(vectors[i])
    return {g: np.asarray(v, dtype=float).mean(axis=0) for g, v in by.items()}


def _dist(a, b, scale) -> float:
    """Distance in units of each measure's spread; unknown is furthest."""
    if a is None or b is None or scale is None:
        return 0.0 if a is None else float("inf")
    d = (np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) / scale
    return float(np.sqrt((d ** 2).sum()))
