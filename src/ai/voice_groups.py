"""Voice groups without a model (piece V.2).

Sorts the voice fingerprints of ratings (V.1) into a few strong voice
groups, using the numbers only. No model, no scikit-learn; numpy only.

**The unit is the voice source**, not the single rating: one
``project_path`` + ``character_name`` (no narrator: the project alone).
Every rating follows its source. A source counts once it has
:data:`MIN_SOURCE_RATINGS` fingerprinted ratings of distinct passages (one
passage rated twice counts once); until then it is **Unsorted**, and its
ratings are used as today (the whole store). A source whose ratings fall
into two clearly different voices (2-means, each side ready, at least
:data:`SPLIT` apart) is treated as two ("<project>: voice A / B").

**Separation** between two sources (:func:`separation`) is how far apart
their mean fingerprints are, measured per measure in units of the pooled
spread of the two sources' own ratings, averaged over the measures (root
mean square) and corrected for the chance distance two finite samples
have (so a source does not drift towards its neighbours just because it
grew). It estimates the true distance between two voices, in "within-
voice spreads". Between groups it is the average over their sources.

**Thresholds** (:data:`SAME`, :data:`APART`, :data:`MIN_SOURCE_RATINGS`)
are constants measured once on published books by
``scripts/voice_thresholds.py`` (see V.2's *Outcome*). The writer's own
data never moves them, so their groups never shift because a threshold
did. At or below ``SAME``: one voice. At or above ``APART``: different
voices. Between the two, things stay as they are.

**Building** (:func:`regroup`): every ready source starts alone (or in
the group it was in last time); the closest pair of groups merges while
their average separation is at most ``SAME`` and no two sources in the
result are ``APART`` or more. Same data, same groups: no random start,
ties broken by name. The writer's own groups (anchors) and the sources
they placed by hand (pins) are never changed by the app; a change that
would touch one is stored as a proposal (V.5 shows them).

This module is pure: it takes rows and a previous state (a dict, see
:func:`empty_state`) and returns the new state. Storage and the check
at start-up are in :mod:`src.data.voice_groups_store`.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from src.ai import voice_fingerprint as vf

# ── Constants (from scripts/voice_thresholds.py; see V.2's Outcome) ──

# Measured 25 Nov 2026 on 64 downloaded books by 52 authors, 11,081
# passages of 150-300 words (default run, seed 7). Fixed: the writer's
# own data never moves them.
SAME = 0.45                # one voice: 95th percentile of one book's two halves, n = 30
APART = 0.67               # different voices: max(1.5 x SAME, 10th pct of different authors 0.47)
MIN_SOURCE_RATINGS = 30    # where that 95th percentile settles (within a tenth)
SPLIT = 1.25               # a source splits in two: above one book's 2-means p99 (1.22)
SPLIT_KEEP = 1.10          # ...and stays split while above its p95 (1.10)
MAX_AUTO_GROUPS = 8        # the most groups the app makes on its own
GROWTH_FOR_CHECK = 0.20    # ratings grown by a fifth since the last check

UNSORTED = "unsorted"
STATE_VERSION = 1

#: Floor on a measure's within-voice spread, as a share of its spread
#: over both samples, so a measure that never varies inside a source
#: (``second_person_pct`` is 0 in most books) cannot divide by zero.
_SPREAD_FLOOR = 0.1


# ── The measure of separation ────────────────────────────────────────

def _as_matrix(vectors) -> np.ndarray:
    m = np.asarray(vectors, dtype=float)
    if m.ndim == 1:
        m = m.reshape(1, -1)
    return m


def separation(a, b) -> float:
    """How far apart two samples of fingerprints are, in within-voice
    spreads (0 = alike). ``a`` and ``b`` are lists of vectors (one per
    rating or passage). Symmetric and deterministic."""
    a, b = _as_matrix(a), _as_matrix(b)
    na, nb = len(a), len(b)
    if na == 0 or nb == 0 or a.shape[1] != b.shape[1]:
        return float("nan")
    ma, mb = a.mean(axis=0), b.mean(axis=0)
    ss = ((a - ma) ** 2).sum(axis=0) + ((b - mb) ** 2).sum(axis=0)
    dof = na + nb - 2
    both = np.vstack([a, b])
    total = both.var(axis=0, ddof=1) if len(both) > 1 else np.zeros(a.shape[1])
    keep = total > 1e-12
    if not keep.any():
        return 0.0
    within = ss / dof if dof > 0 else total.copy()
    within = np.maximum(within, (_SPREAD_FLOOR ** 2) * total)
    d2 = float(((ma - mb)[keep] ** 2 / within[keep]).mean()) - (1.0 / na + 1.0 / nb)
    return math.sqrt(max(0.0, d2))


def two_means(vectors) -> Optional[np.ndarray]:
    """Split one source's ratings two ways (2-means on its own
    standardised measures, deterministic start: the rating furthest from
    the middle, then the one furthest from that). A boolean array, True
    for the side holding the first rating; None when there is nothing to
    split."""
    m = _as_matrix(vectors)
    n = len(m)
    if n < 4:
        return None
    sd = m.std(axis=0)
    keep = sd > 1e-12
    if not keep.any():
        return None
    z = (m[:, keep] - m[:, keep].mean(axis=0)) / sd[keep]
    first = int(np.argmax((z ** 2).sum(axis=1)))
    second = int(np.argmax(((z - z[first]) ** 2).sum(axis=1)))
    centres = np.vstack([z[first], z[second]])
    labels = np.zeros(n, dtype=int)
    for _ in range(100):
        d = ((z[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new = np.argmin(d, axis=1)
        if (new == 0).all() or (new == 1).all():
            return None
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        centres = np.vstack([z[labels == 0].mean(axis=0), z[labels == 1].mean(axis=0)])
    side = labels == labels[0]
    return side


# ── Sources ──────────────────────────────────────────────────────────

def source_key(project_path: str, character_name: str = "", part: str = "") -> str:
    """The id of a voice source: project, narrator and (for a source with
    two voices) the part, "A" or "B"."""
    key = f"{project_path or ''}::{(character_name or '').strip()}"
    return f"{key}#{part}" if part else key


def _parent(key: str) -> str:
    return key.split("#", 1)[0]


def source_label(project_path: str, character_name: str = "", part: str = "") -> str:
    name = Path(project_path).stem if project_path else "(no project)"
    if character_name:
        name += f" / {character_name}"
    if part:
        name += f": voice {part}"
    return name


def eligible(row: Dict[str, Any]) -> bool:
    """A rating that is sorted into groups: a whole fingerprint, a
    project, and the writer's own (not a row made from a corpus, whose
    notes carry ``synthesized=``). Other rows are used as today."""
    v = row.get("vector") or []
    if len(v) != len(vf.MEASURES) or row.get("status", "ok") != vf.STATUS_OK:
        return False
    if not (row.get("project_path") or "").strip():
        return False
    if row.get("synthesized") or "synthesized=" in (row.get("notes") or ""):
        return False
    return True


@dataclass
class Source:
    key: str
    project_path: str
    character_name: str
    part: str = ""
    ids: List[int] = field(default_factory=list)        # every rating
    rating_vectors: List[Tuple[float, ...]] = field(default_factory=list, repr=False)
    vectors: List[Tuple[float, ...]] = field(default_factory=list)   # distinct passages
    _seen: Dict[Tuple[float, ...], int] = field(default_factory=dict, repr=False)
    seed: bool = False                                   # a group's example passages

    @property
    def label(self) -> str:
        if self.seed:
            return "example passages"
        return source_label(self.project_path, self.character_name, self.part)

    @property
    def passages(self) -> int:
        return len(self.vectors)

    def add(self, rid: int, vector: Sequence[float]) -> None:
        t = tuple(round(float(x), 6) for x in vector)
        self.ids.append(int(rid))
        self.rating_vectors.append(t)
        if t not in self._seen:            # the same passage rated twice counts once
            self._seen[t] = len(self.vectors)
            self.vectors.append(t)

    def matrix(self) -> np.ndarray:
        return np.asarray(self.vectors, dtype=float)


def collect_sources(rows: Iterable[Dict[str, Any]]) -> Dict[str, Source]:
    """Eligible ratings by source, in id order."""
    out: Dict[str, Source] = {}
    for r in sorted((r for r in rows if eligible(r)), key=lambda r: int(r["id"])):
        pp, ch = r.get("project_path") or "", (r.get("character_name") or "").strip()
        key = source_key(pp, ch)
        s = out.get(key)
        if s is None:
            s = out[key] = Source(key, pp, ch)
        s.add(r["id"], r["vector"])
    return out


def _split_source(src: Source, threshold: float) -> Optional[Tuple[Source, Source, float]]:
    """The two-voice test: (part A, part B, separation) when 2-means finds
    two sides each with ``MIN_SOURCE_RATINGS`` passages and at least
    ``threshold`` apart; A holds the earliest rating."""
    if src.passages < 2 * MIN_SOURCE_RATINGS:
        return None
    m = src.matrix()
    side = two_means(m)
    if side is None or side.sum() < MIN_SOURCE_RATINGS or (~side).sum() < MIN_SOURCE_RATINGS:
        return None
    sep = separation(m[side], m[~side])
    if not sep >= threshold:
        return None
    parts = {"A": Source(source_key(src.project_path, src.character_name, "A"),
                         src.project_path, src.character_name, "A"),
             "B": Source(source_key(src.project_path, src.character_name, "B"),
                         src.project_path, src.character_name, "B")}
    where = {src.vectors[i]: ("A" if side[i] else "B") for i in range(len(side))}
    # ratings in id order; duplicates follow their passage
    for rid, vec in zip(src.ids, src.rating_vectors):
        parts[where[vec]].add(rid, vec)
    return parts["A"], parts["B"], sep


def _scale_of(m: np.ndarray) -> np.ndarray:
    sd = m.std(axis=0) if len(m) > 1 else np.ones(m.shape[1])
    return np.where(sd > 1e-9, sd, 1.0)


def nearest_part(vector: Sequence[float], split: Dict[str, Any]) -> str:
    """Which part ("A" or "B") of a two-voice source a passage belongs to,
    by its distance to each part's centre (in the source's own spreads)."""
    v = np.asarray(vector, dtype=float)
    scale = np.asarray(split.get("scale") or np.ones(len(v)), dtype=float)
    best, part = None, "A"
    for p in ("A", "B"):
        c = split.get(p)
        if c is None:
            continue
        d = float((((v - np.asarray(c, dtype=float)) / scale) ** 2).sum())
        if best is None or d < best:
            best, part = d, p
    return part


def _split_by_centres(src: Source, split: Dict[str, Any]) -> Tuple[Source, Source]:
    parts = {p: Source(source_key(src.project_path, src.character_name, p),
                       src.project_path, src.character_name, p) for p in ("A", "B")}
    for rid, vec in zip(src.ids, src.rating_vectors):
        parts[nearest_part(vec, split)].add(rid, vec)
    return parts["A"], parts["B"]


def _split_record(src: Source, a: Source, b: Source, sep: float) -> Dict[str, Any]:
    return {"separation": round(float(sep), 3),
            "A": [round(float(x), 4) for x in a.matrix().mean(axis=0)],
            "B": [round(float(x), 4) for x in b.matrix().mean(axis=0)],
            "scale": [round(float(x), 4) for x in _scale_of(src.matrix())]}


# ── State ────────────────────────────────────────────────────────────

def _now(now: Optional[str] = None) -> str:
    return now or datetime.now().isoformat(timespec="seconds")


def empty_state() -> Dict[str, Any]:
    """No groups yet: every rating is Unsorted and used as today."""
    return {
        "version": STATE_VERSION,
        "measures_version": vf.VERSION,
        "constants": {"same": SAME, "apart": APART, "min_source_ratings": MIN_SOURCE_RATINGS,
                      "split": SPLIT, "max_auto_groups": MAX_AUTO_GROUPS},
        "next_id": 1,
        "groups": {},       # id -> group (see regroup)
        "sources": {},      # source key -> where it is and why
        "pins": {},         # source key -> group id (placed by the writer)
        "splits": {},       # source key -> two-voice split (centres)
        "proposals": [],    # changes that touch the writer's groups (V.5)
        "dismissed": [],    # proposal keys the writer said no to
        "events": [],       # new / merged / split / gone, for naming (V.3)
        "checked_at": "",
        "ratings_at_check": 0,
        "ready_at_check": [],
        "evidence_at_check": [],    # sources with enough ratings at the last check
    }


def normalise_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A safe copy: missing or damaged parts get their defaults."""
    base = empty_state()
    if not isinstance(state, dict):
        return base
    out = copy.deepcopy(state)
    for k, v in base.items():
        if not isinstance(out.get(k), type(v)):
            out[k] = copy.deepcopy(v)
    out["constants"] = base["constants"]
    for gid, g in list(out["groups"].items()):
        if not isinstance(g, dict):
            del out["groups"][gid]
            continue
        g.setdefault("id", gid)
        for k, d in (("name", ""), ("named_by", ""), ("description", ""), ("anchor", False),
                     ("seed_passages", []), ("sources", []), ("ratings", 0), ("passages", 0),
                     ("strength", ""), ("widest", 0.0), ("created_at", "")):
            if not isinstance(g.get(k), type(d)):
                g[k] = copy.deepcopy(d)
    out["pins"] = {k: v for k, v in out["pins"].items()
                   if isinstance(v, str) and v in out["groups"]}
    out["dismissed"] = [k for k in out["dismissed"] if isinstance(k, str)]
    return out


def is_anchor(state: Dict[str, Any], gid: str) -> bool:
    """A group the writer made, named, or placed a source in."""
    g = state.get("groups", {}).get(gid)
    if not g:
        return False
    return bool(g.get("anchor") or g.get("named_by") == "writer"
                or gid in state.get("pins", {}).values())


def display_name(group: Dict[str, Any]) -> str:
    """The group's name, or its plain-words description until it has one."""
    return group.get("name") or group.get("description") or "Voice group"


def strength_label(widest: float) -> str:
    if widest <= SAME / 2:
        return "very alike"
    if widest <= SAME:
        return "alike"
    return "loose"


# ── Plain-words descriptions ─────────────────────────────────────────

_HIGH_LOW: Dict[str, Tuple[str, str]] = {
    "sentence_len_mean": ("long sentences", "short sentences"),
    "sentence_len_spread": ("varied sentence lengths", "even sentence lengths"),
    "short_sentences_pct": ("many short sentences", "few short sentences"),
    "long_sentences_pct": ("many long sentences", "few long sentences"),
    "sentences_per_paragraph": ("long paragraphs", "short paragraphs"),
    "word_len_mean": ("long words", "short words"),
    "dialogue_pct": ("much dialogue", "little dialogue"),
    "opens_pronoun_pct": ("often opens with a pronoun", "rarely opens with a pronoun"),
    "opens_name_pct": ("often opens with a name", "rarely opens with a name"),
    "opens_article_pct": ("often opens with an article", "rarely opens with an article"),
    "opens_conjunction_pct": ("often opens with And/But/So", "rarely opens with And/But/So"),
    "opens_ing_pct": ("often opens with an -ing word", "rarely opens with an -ing word"),
}
_ABSOLUTE = ("first_person_pct", "second_person_pct", "past_tense_pct")


def describe(mean: Sequence[float], overall: Sequence[float], spread: Sequence[float],
             traits: int = 2) -> str:
    """"Short sentences, present tense, first person": the measures where
    the group stands out from all the writer's sources, then tense and
    person (which are told plainly from their own values)."""
    mean, overall = np.asarray(mean, dtype=float), np.asarray(overall, dtype=float)
    spread = np.where(np.asarray(spread, dtype=float) > 1e-9, spread, np.inf)
    z = (mean - overall) / spread
    idx = {m: i for i, m in enumerate(vf.MEASURES)}
    ranked = sorted((i for i, m in enumerate(vf.MEASURES) if m not in _ABSOLUTE),
                    key=lambda i: (-abs(z[i]), i))
    words: List[str] = []
    for i in ranked[:traits]:
        if abs(z[i]) < 0.3 or not np.isfinite(z[i]):
            break
        m = vf.MEASURES[i]
        hi, lo = _HIGH_LOW.get(m, (f"more {vf.LABELS[m]}", f"fewer {vf.LABELS[m]}"))
        words.append(hi if z[i] > 0 else lo)
    past = mean[idx["past_tense_pct"]]
    words.append("past tense" if past >= 60 else "present tense" if past <= 40 else "mixed tense")
    first, second = mean[idx["first_person_pct"]], mean[idx["second_person_pct"]]
    words.append("first person" if first >= 50 else "second person" if second >= 30
                 else "third person")
    text = ", ".join(words)
    return text[:1].upper() + text[1:]


# ── Building and checking the groups ─────────────────────────────────

def _proposal(kind: str, *, groups=(), sources=(), separation_=None, why: str = "") -> Dict[str, Any]:
    groups, sources = sorted(set(groups)), sorted(set(sources))
    p = {"key": f"{kind}:{'+'.join(groups)}|{'+'.join(sources)}", "kind": kind,
         "groups": groups, "sources": sources, "why": why}
    if separation_ is not None:
        p["separation"] = round(float(separation_), 3)
    return p


def _previous_group(key: str, prev: Dict[str, Optional[str]]) -> Optional[str]:
    """The group a source was in last time; a new part takes its whole
    source's group, a source no longer split takes part A's."""
    if prev.get(key):
        return prev[key]
    if "#" in key:
        return prev.get(_parent(key))
    return prev.get(key + "#A") or prev.get(key + "#B")


def regroup(rows: Iterable[Dict[str, Any]], state: Optional[Dict[str, Any]] = None, *,
            now: Optional[str] = None) -> Dict[str, Any]:
    """Sort the ratings into voice groups and return the new state.

    ``rows`` are ratings with ``id, project_path, character_name, status,
    vector`` (and ``notes``), as :mod:`src.data.voice_groups_store` reads
    them. ``state`` is the last state (None: build from nothing). The
    writer's groups and placed sources are kept exactly; what would change
    them goes into ``proposals``. Same rows and state, same result."""
    state = normalise_state(state)
    now = _now(now)
    groups: Dict[str, Dict[str, Any]] = state["groups"]
    pins: Dict[str, str] = state["pins"]
    prev = {k: (v or {}).get("group") for k, v in state["sources"].items() if isinstance(v, dict)}
    anchors = {gid for gid in groups if is_anchor(state, gid)}
    proposals: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    def touched(key: str) -> bool:
        keys = (key, key + "#A", key + "#B")
        return any(k in pins or prev.get(k) in anchors for k in keys)

    # 1. Sources, and the two-voice test.
    raw = collect_sources(rows)
    sources: Dict[str, Source] = {}
    splits: Dict[str, Dict[str, Any]] = {}
    for key in sorted(raw):
        src = raw[key]
        old = state["splits"].get(key)
        if old and touched(key):                 # the writer's: keep the split as it was
            a, b = _split_by_centres(src, old)
            if a.passages and b.passages:
                sources[a.key], sources[b.key] = a, b
                splits[key] = old
                sep = separation(a.matrix(), b.matrix())
                if not sep >= SPLIT_KEEP:
                    proposals.append(_proposal("unsplit", sources=[key], separation_=sep,
                                               why="its two voices have grown alike"))
                continue
        res = _split_source(src, SPLIT_KEEP if old else SPLIT)
        if res and touched(key) and not old:
            proposals.append(_proposal("split", sources=[key], groups=[prev.get(key) or ""],
                                       separation_=res[2],
                                       why="its ratings fall into two different voices"))
            res = None
        if res:
            a, b, sep = res
            sources[a.key], sources[b.key] = a, b
            splits[key] = _split_record(src, a, b, sep)
            if not old:
                events.append({"kind": "split", "source": key, "at": now})
        else:
            sources[key] = src

    # 2. Which sources count (enough distinct passages, or placed by hand),
    #    and the example passages of the writer's own groups.
    ready = {k: s for k, s in sources.items() if s.passages >= MIN_SOURCE_RATINGS or k in pins}
    for gid in sorted(groups):
        seed = groups[gid].get("seed_passages") or []
        vecs = [v for v in seed if isinstance(v, list) and len(v) == len(vf.MEASURES)]
        if vecs:
            s = Source(f"seed:{gid}", "", "", seed=True)
            for i, v in enumerate(vecs):
                s.add(-1 - i, v)
            ready[s.key] = s
            anchors.add(gid)
    seps: Dict[Tuple[str, str], float] = {}

    def sep(x: str, y: str) -> float:
        k = (x, y) if x < y else (y, x)
        if k not in seps:
            seps[k] = separation(ready[k[0]].matrix(), ready[k[1]].matrix())
        return seps[k]

    def ratings(keys) -> int:
        return sum(len(ready[k].ids) if not ready[k].seed else 0 for k in keys)

    # 3. Start where things were: last time's groups, the writer's places.
    clusters: Dict[str, List[str]] = {gid: [] for gid in sorted(groups)}
    for key in sorted(ready):
        if key.startswith("seed:"):
            clusters[key[5:]].append(key)
            continue
        g = pins.get(key) or _previous_group(key, prev)
        if g in clusters:
            clusters[g].append(key)
        else:
            clusters["new:" + key] = [key]

    # 4. A source clearly apart from the rest of an app-made group leaves.
    #    In the writer's group it stays, and its leaving is proposed.
    moved = True
    while moved:
        moved = False
        for cid in sorted(clusters):
            mem = clusters[cid]
            if len(mem) < 2:
                continue
            bad = sorted({k for x in mem for y in mem if x < y and sep(x, y) >= APART
                          for k in (x, y)})
            movable = [k for k in bad if k not in pins and not k.startswith("seed:")]
            if not movable:
                continue
            if cid in anchors:
                for k in movable:
                    proposals.append(_proposal("leave", groups=[cid], sources=[k],
                                               why="it now reads clearly unlike the rest of the group"))
                continue
            def apartness(k):
                others = [o for o in mem if o != k]
                return (-sum(sep(k, o) for o in others) / len(others), ratings([k]), k)
            leaver = sorted(movable, key=apartness)[0]
            mem.remove(leaver)
            clusters["new:" + leaver] = [leaver]
            events.append({"kind": "left", "group": cid, "source": leaver, "at": now})
            moved = True
            break

    # 5. Merge the closest pair while it is one voice and stays strong.
    merged_from: Dict[str, List[str]] = {}
    blocked = set()
    while True:
        live = sorted(c for c, m in clusters.items() if m)
        best = None
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if (a, b) in blocked:
                    continue
                cross = [sep(x, y) for x in clusters[a] for y in clusters[b]]
                avg, worst = sum(cross) / len(cross), max(cross)
                if avg <= SAME and worst < APART and (best is None or (avg, a, b) < best):
                    best = (avg, a, b)
        if best is None:
            break
        avg, a, b = best
        if a in anchors or b in anchors:
            blocked.add((a, b))
            if a in anchors and b in anchors:
                continue                                  # the writer keeps their groups apart
            other = b if a in anchors else a
            anchor = a if a in anchors else b
            kind = "join" if other.startswith("new:") else "merge"
            proposals.append(_proposal(kind, groups=[anchor] + ([] if kind == "join" else [other]),
                                       sources=clusters[other] if kind == "join" else [],
                                       separation_=avg, why="it reads in the same voice"))
            continue
        keep, gone = (a, b) if (ratings(clusters[a]), b) >= (ratings(clusters[b]), a) else (b, a)
        clusters[keep] = clusters[keep] + clusters[gone]
        merged_from.setdefault(keep, []).extend([gone] + merged_from.pop(gone, []))
        del clusters[gone]

    # 6. At most MAX_AUTO_GROUPS made by the app: the smallest wait.
    auto = sorted((c for c, m in clusters.items() if m and c not in anchors),
                  key=lambda c: (-ratings(clusters[c]), min(clusters[c])))
    waiting = set()
    for c in auto[MAX_AUTO_GROUPS:]:
        waiting.update(clusters.pop(c))
    if waiting:
        live = auto[:MAX_AUTO_GROUPS]
        pairs = sorted((sum(sep(x, y) for x in clusters[a] for y in clusters[b])
                        / (len(clusters[a]) * len(clusters[b])), a, b)
                       for i, a in enumerate(live) for b in live[i + 1:])
        if pairs:
            proposals.append(_proposal("merge", groups=list(pairs[0][1:]), separation_=pairs[0][0],
                                       sources=sorted(waiting),
                                       why=f"more than {MAX_AUTO_GROUPS} voices: merging the "
                                           "closest two would make room for the ones waiting"))

    # 7. Identity: each old group's id and name stay with the side that
    #    holds most of its ratings.
    claims = []
    for cid, mem in clusters.items():
        if not mem or cid in anchors:
            continue
        count: Dict[str, int] = {}
        for k in mem:
            g = _previous_group(k, prev)
            if g in groups and g not in anchors:
                count[g] = count.get(g, 0) + ratings([k])
        for g, n in count.items():
            claims.append((-n, g, cid))
    final: Dict[str, str] = {}               # cluster -> group id
    used = set()
    for _n, g, cid in sorted(claims):
        if cid not in final and g not in used:
            final[cid], used = g, used | {g}
    for gid in anchors:
        final[gid] = gid
    new_groups: Dict[str, Dict[str, Any]] = {}
    next_id = int(state.get("next_id") or 1)
    for cid in sorted((c for c, m in clusters.items() if m and c not in final),
                      key=lambda c: min(clusters[c])):
        while f"g{next_id}" in groups:
            next_id += 1
        final[cid] = f"g{next_id}"
        next_id += 1
    for cid, gid in final.items():
        old = groups.get(gid)
        g = copy.deepcopy(old) if old else {
            "id": gid, "name": "", "named_by": "", "description": "", "anchor": False,
            "seed_passages": [], "created_at": now}
        g["sources"] = sorted(k for k in clusters.get(cid, []) if not k.startswith("seed:"))
        new_groups[gid] = g
        before = {c2 for k in g["sources"] for c2 in [_previous_group(k, prev)] if c2}
        if not old:
            events.append({"kind": "new", "group": gid, "from": sorted(before), "at": now})
        absorbed = sorted(x for x in before if x != gid and x in groups and x not in used
                          and x not in anchors)
        if old and absorbed:
            events.append({"kind": "merged", "group": gid, "from": absorbed, "at": now})
    for gid in sorted(groups):
        if gid not in new_groups:
            events.append({"kind": "gone", "group": gid, "at": now})

    # 8. Descriptions, sizes, strength.
    everyone = [s for s in sources.values()]
    all_vecs = np.vstack([s.matrix() for s in everyone]) if everyone else None
    if all_vecs is not None and len(everyone) >= 1:
        overall = all_vecs.mean(axis=0)
        ss = sum(((s.matrix() - s.matrix().mean(axis=0)) ** 2).sum(axis=0) for s in everyone)
        dof = max(1, len(all_vecs) - len(everyone))
        spread = np.sqrt(ss / dof)
    group_of: Dict[str, str] = {}
    for gid, g in new_groups.items():
        keys = g["sources"]
        for k in keys:
            group_of[k] = gid
        g["ratings"] = ratings([k for k in keys])
        g["passages"] = sum(ready[k].passages for k in keys)
        pair = [sep(x, y) for i, x in enumerate(keys) for y in keys[i + 1:]]
        g["widest"] = round(max(pair), 3) if pair else 0.0
        g["strength"] = strength_label(g["widest"])
        mem_vecs = [ready[k].matrix() for k in keys] + \
                   ([ready[f"seed:{gid}"].matrix()] if f"seed:{gid}" in ready else [])
        if mem_vecs and all_vecs is not None:
            g["description"] = describe(np.vstack(mem_vecs).mean(axis=0), overall, spread)

    # 9. Where every source is.
    out_sources: Dict[str, Dict[str, Any]] = {}
    for key in sorted(sources):
        s = sources[key]
        gid = group_of.get(key)
        status = "grouped" if gid else ("waiting" if key in waiting else "unsorted")
        out_sources[key] = {"project_path": s.project_path, "character_name": s.character_name,
                            "part": s.part, "label": s.label, "ratings": len(s.ids),
                            "passages": s.passages, "group": gid, "status": status,
                            "pinned": key in pins}

    seen, kept = set(), []
    dismissed = set(state["dismissed"])
    for p in proposals:
        if p["key"] not in seen and p["key"] not in dismissed:
            seen.add(p["key"])
            kept.append(p)

    state.update({
        "next_id": next_id, "groups": new_groups, "sources": out_sources, "splits": splits,
        "proposals": kept, "events": (state["events"] + events)[-200:],
        "checked_at": now, "measures_version": vf.VERSION,
        "ratings_at_check": sum(len(s.ids) for s in sources.values()),
        "ready_at_check": sorted(k for k in ready if not k.startswith("seed:")),
        "evidence_at_check": sorted(k for k, s in raw.items() if s.passages >= MIN_SOURCE_RATINGS),
    })
    return state


def needs_check(rows: Iterable[Dict[str, Any]], state: Optional[Dict[str, Any]]) -> bool:
    """A check is due when a source has become ready (or fallen below the
    evidence), the ratings grew by about a fifth since the last check, or
    the measures changed version."""
    state = state if isinstance(state, dict) else {}
    rows = list(rows)
    srcs = collect_sources(rows)
    total = sum(len(s.ids) for s in srcs.values())
    last = int(state.get("ratings_at_check") or 0)
    if state.get("measures_version", vf.VERSION) != vf.VERSION:
        return True
    ready = {k for k, s in srcs.items() if s.passages >= MIN_SOURCE_RATINGS}
    before = set(state.get("evidence_at_check") or [])
    if ready != before:
        return True
    if not state.get("checked_at"):
        return bool(ready)
    return total >= last * (1 + GROWTH_FOR_CHECK) + 1 or total < last


# ── Which group a rating is in (for V.4) ─────────────────────────────

def group_for(state: Dict[str, Any], project_path: str, character_name: str = "",
              vector: Optional[Sequence[float]] = None) -> Optional[str]:
    """The group of a passage from this project and narrator, or None
    (Unsorted: use the whole store, as today). For a source with two
    voices, ``vector`` (its fingerprint) picks the part; without one,
    part A."""
    if not (project_path or "").strip():
        return None
    key = source_key(project_path, character_name)
    split = (state.get("splits") or {}).get(key)
    if split:
        part = nearest_part(vector, split) if vector is not None and len(vector) == len(vf.MEASURES) else "A"
        key = source_key(project_path, character_name, part)
    return ((state.get("sources") or {}).get(key) or {}).get("group")


def membership(rows: Iterable[Dict[str, Any]], state: Dict[str, Any]) -> Dict[int, str]:
    """Every rating's group id, or :data:`UNSORTED`. Every rating with a
    fingerprint has one (V.2's "done when")."""
    out: Dict[int, str] = {}
    for r in rows:
        gid = None
        if eligible(r):
            gid = group_for(state, r.get("project_path") or "", r.get("character_name") or "",
                            r.get("vector"))
        out[int(r["id"])] = gid or UNSORTED
    return out


# ── The writer's hand (V.5 calls these, then regroup) ────────────────

def create_group(state: Dict[str, Any], name: str = "", *, sources: Iterable[str] = (),
                 passages: Iterable[str] = (), now: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """A group the writer starts: named, seeded with sources (projects or
    narrators, which are then pinned to it) and/or example passages. It is
    an anchor: never merged, emptied or removed by the app."""
    state = normalise_state(state)
    n = int(state["next_id"])
    while f"g{n}" in state["groups"]:
        n += 1
    gid = f"g{n}"
    state["next_id"] = n + 1
    seeds = [v for v in (vf.vector_of(p) for p in passages) if v is not None]
    state["groups"][gid] = {"id": gid, "name": (name or "").strip(),
                            "named_by": "writer" if (name or "").strip() else "",
                            "description": "", "anchor": True, "seed_passages": seeds,
                            "sources": [], "ratings": 0, "passages": 0, "strength": "",
                            "widest": 0.0, "created_at": _now(now)}
    for k in sources:
        state["pins"][k] = gid
    if not (name or "").strip():
        state["events"].append({"kind": "new", "group": gid, "from": [], "at": _now(now)})
    return state, gid


def rename_group(state: Dict[str, Any], gid: str, name: str) -> Dict[str, Any]:
    """The writer's name: kept for good (the app and V.3 never change it)."""
    state = normalise_state(state)
    if gid in state["groups"] and (name or "").strip():
        state["groups"][gid].update(name=name.strip(), named_by="writer")
    return state


def name_from_model(state: Dict[str, Any], gid: str, name: str,
                    description: str = "") -> Dict[str, Any]:
    """V.3: a name the model gave. Ignored if the writer named the group."""
    state = normalise_state(state)
    g = state["groups"].get(gid)
    if g and g.get("named_by") != "writer" and (name or "").strip():
        g.update(name=name.strip(), named_by="model")
        if description:
            g["model_description"] = description.strip()
        for e in state["events"]:
            if e.get("group") == gid:
                e["named"] = True
    return state


def needs_name(state: Dict[str, Any]) -> List[str]:
    """Groups V.3 should name: new or merged since last named, and never
    named by the writer."""
    out = []
    for gid, g in sorted((state.get("groups") or {}).items()):
        if g.get("named_by") == "writer":
            continue
        fresh = any(e.get("group") == gid and e.get("kind") in ("new", "merged")
                    and not e.get("named") for e in state.get("events") or [])
        if fresh or not g.get("name"):
            out.append(gid)
    return out


def place_source(state: Dict[str, Any], key: str, gid: str) -> Dict[str, Any]:
    """The writer puts a source in a group: pinned there; the group
    becomes the writer's (an anchor)."""
    state = normalise_state(state)
    if gid in state["groups"]:
        state["pins"][key] = gid
    return state


def unpin_source(state: Dict[str, Any], key: str) -> Dict[str, Any]:
    state = normalise_state(state)
    state["pins"].pop(key, None)
    return state


def merge_groups(state: Dict[str, Any], gids: Sequence[str], name: str = "",
                 now: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """The writer merges groups (V.5 warns when the result is loose). The
    largest keeps its id; the result keeps the writer's name if one had
    it, else is named afresh. Its sources are pinned so the merge holds.
    Keep a copy of the state before calling to undo."""
    state = normalise_state(state)
    gids = [g for g in dict.fromkeys(gids) if g in state["groups"]]
    if len(gids) < 2:
        return state, None
    groups = state["groups"]
    keep = sorted(gids, key=lambda g: (-int(groups[g].get("ratings") or 0), g))[0]
    writer_name = next((groups[g].get("name") for g in sorted(gids, key=lambda g: (g != keep, g))
                        if groups[g].get("named_by") == "writer" and groups[g].get("name")), "")
    target = groups[keep]
    for g in gids:
        for k in groups[g].get("sources") or []:
            state["pins"][k] = keep
        for k, v in list(state["pins"].items()):
            if v == g:
                state["pins"][k] = keep
        if g != keep:
            target["seed_passages"] = (target.get("seed_passages") or []) + \
                                      (groups[g].get("seed_passages") or [])
            target["sources"] = sorted(set(target.get("sources") or []) |
                                       set(groups[g].get("sources") or []))
    for g in gids:
        if g != keep:
            del groups[g]
    target["anchor"] = True
    if (name or "").strip():
        target.update(name=name.strip(), named_by="writer")
    elif writer_name:
        target.update(name=writer_name, named_by="writer")
    else:
        target.update(name="", named_by="")
        state["events"].append({"kind": "merged", "group": keep,
                                "from": sorted(g for g in gids if g != keep), "at": _now(now)})
    return state, keep


def remove_group(state: Dict[str, Any], gid: str) -> Dict[str, Any]:
    """The writer removes a group: its sources go back to being sorted."""
    state = normalise_state(state)
    state["groups"].pop(gid, None)
    state["pins"] = {k: v for k, v in state["pins"].items() if v != gid}
    for s in state["sources"].values():
        if isinstance(s, dict) and s.get("group") == gid:
            s["group"] = None
    return state


def dismiss_proposal(state: Dict[str, Any], key: str) -> Dict[str, Any]:
    state = normalise_state(state)
    state["proposals"] = [p for p in state["proposals"] if p.get("key") != key]
    if key not in state["dismissed"]:
        state["dismissed"].append(key)
    return state
