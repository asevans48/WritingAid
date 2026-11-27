"""The draft beside the plan, without a model (piece 7.3, no-model tier).

Matches a chapter's planned events (``chapter.planning.events``) to the
scenes of its draft (``reverse_outline``), so the writer sees which
planned events have no scene yet and which scenes are not in the plan.

**How it matches.** By the names and distinctive words a planned event
shares with a scene. A word counts for more the fewer of the chapter's
scenes use it; a name (capitalised in the plan, or a character's name)
counts double. An event goes to the scene that shares the largest part
of its weight, if that part is at least ``THRESHOLD`` and at least one
shared word is not in every scene and is more than a character's name
(characters recur, so a name alone proves little). A scene may hold several events. Ties
lean towards the scene in the same place in the order as the event in
the plan. It is a suggestion: the writer corrects it, and corrections
(``plan_matches`` store) win over it.

**Pacing for the chart.** ``book_pacing`` gives every scene of the
manuscript its words and dialogue share. That is what the chart shows
without a model.

**Hook for 7.2 (tension).** ``set_tension_source(fn)`` registers a
function ``fn(chapter_id, text, spans) -> list of 0..1 or None`` that
gives each scene's tension (from the model's scene reading). When it
returns values, ``book_pacing`` fills ``ScenePoint.tension`` and the
chart draws tension instead of pacing. Until then it is ``None``.

**Scene markers (7.4).** ``set_marks_source(fn)`` registers
``fn(chapter_id, text) -> offsets`` (the writer's markers, kept beside
the text); ``book_pacing`` splits each chapter at them as well.

No Qt. Writes nothing.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

THRESHOLD = 0.3          # share of an event's word weight a scene must hold
NAME_WEIGHT = 2.0
ORDER_LEAN = 0.08        # how much the place in the order tips a close call

_WORD = re.compile(r"[A-Za-z][A-Za-z’'\-]*")
_BEAT_PREFIX = re.compile(r"^\s*(?:beat|scene|event|step)\s*\d+\s*[:.\-–—]\s*", re.I)
_STOP = set("""a about above after again against all also am an and any are as at be because
been before being below between both but by can could did do does doing down during each few
for from further had has have having he her here hers herself him himself his how i if in into
is it its itself just me more most my myself no nor not now of off on once only or other our
ours out over own same she should so some such than that the their theirs them then there these
they this those through to too under until up very was we were what when where which while who
whom why will with would you your yours yourself one two three first last next finally then
again still back away get gets got goes went go come comes came make makes made take takes took
beat scene chapter part act moment introduce introduces introduced show shows shown establish
establishes reveal reveals revealed learn learns learned realize realizes decide decides tries
try finds find found begins begin starts start ends end something someone thing things way""".split())


def _key(word: str) -> str:
    """A rough stem, so "arrives", "arrived" and "arrival" meet."""
    w = word.lower().replace("’", "'").strip("'-")
    if w.endswith("'s"):
        w = w[:-2]
    for suf in ("ings", "ing", "edly", "ed", "es", "s", "al", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[:-len(suf)]
            break
    return w[:5] if len(w) > 5 else w


def _keys(text: str) -> set:
    return {_key(w) for w in _WORD.findall(text or "")
            if len(w) >= 3 and w.lower().replace("’", "'") not in _STOP}


def _event_terms(text: str, names: Iterable[str]) -> Dict[str, float]:
    """Each distinctive word of a planned event, with 1 or NAME_WEIGHT."""
    text = _BEAT_PREFIX.sub("", text or "")
    name_keys = {_key(p) for n in names for p in _WORD.findall(n or "") if len(p) >= 3}
    terms: Dict[str, float] = {}
    for sentence in re.split(r"(?<=[.!?:;])\s+|\n+", text):
        for i, w in enumerate(_WORD.findall(sentence)):
            low = w.lower().replace("’", "'")
            if len(w) < 3 or low in _STOP:
                continue
            k = _key(w)
            is_name = k in name_keys or (w[0].isupper() and i > 0)
            terms[k] = max(terms.get(k, 0.0), NAME_WEIGHT if is_name else 1.0)
    return terms


# ── The plan ─────────────────────────────────────────────────────────

@dataclass
class PlannedEvent:
    id: str
    text: str
    description: str = ""

    @property
    def label(self) -> str:
        return _BEAT_PREFIX.sub("", self.text or "").strip() or self.text


def planned_events(chapter: Any) -> List[PlannedEvent]:
    """The chapter's planned events, in plan order ([] when none)."""
    events = list(getattr(getattr(chapter, "planning", None), "events", None) or [])
    events.sort(key=lambda e: getattr(e, "order", 0))
    out = []
    for e in events:
        text = (getattr(e, "text", "") or "").strip()
        if text or (getattr(e, "description", "") or "").strip():
            out.append(PlannedEvent(id=str(getattr(e, "id", "") or text),
                                    text=text, description=getattr(e, "description", "") or ""))
    return out


# ── Matching ─────────────────────────────────────────────────────────

@dataclass
class SceneMatch:
    number: int                       # the scene's number (1-based)
    key: str                          # its opening, as corrections store it
    event_ids: List[str] = field(default_factory=list)
    source: str = "suggested"         # "suggested" | "yours"
    score: float = 0.0                # the best suggested event's share


@dataclass
class Comparison:
    events: List[PlannedEvent]
    scenes: List[SceneMatch]

    @property
    def matched_ids(self) -> set:
        return {i for s in self.scenes for i in s.event_ids}

    @property
    def missing(self) -> List[PlannedEvent]:
        """Planned events with no scene."""
        got = self.matched_ids
        return [e for e in self.events if e.id not in got]

    @property
    def unplanned(self) -> List[SceneMatch]:
        """Scenes with no planned event."""
        return [s for s in self.scenes if not s.event_ids]

    def event(self, event_id: str) -> Optional[PlannedEvent]:
        return next((e for e in self.events if e.id == event_id), None)


def scene_key(opening: str) -> str:
    """How a scene is known in stored corrections: its first words,
    lower-cased. A scene keeps its corrections while its opening stays."""
    return " ".join(re.sub(r"[^\w’']+", " ", (opening or "").lower()).split()[:8])


def scores(scene_texts: Sequence[str], events: Sequence[PlannedEvent],
           names: Iterable[str] = ()) -> List[List[Tuple[float, bool]]]:
    """[event][scene] → (share of the event's weight the scene holds,
    whether a shared word is distinctive: not in every scene, and not just
    a character's name, unless the event names nothing else)."""
    names = list(names)
    scene_keys = [_keys(t) for t in scene_texts]
    n = len(scene_keys)
    df: Dict[str, int] = {}
    for ks in scene_keys:
        for k in ks:
            df[k] = df.get(k, 0) + 1
    cast = {_key(p) for nm in names for p in _WORD.findall(nm or "") if len(p) >= 3}
    table = []
    for e in events:
        terms = _event_terms(f"{e.text}\n{e.description}", names)
        only_cast = bool(terms) and all(k in cast for k in terms)
        weight = {k: w * math.log(1 + n / df[k] if df.get(k) else 1 + n)
                  for k, w in terms.items()}
        total = sum(weight.values()) or 1.0
        row = []
        for ks in scene_keys:
            shared = [k for k in weight if k in ks]
            # A character's name alone is not enough: characters recur.
            row.append((sum(weight[k] for k in shared) / total,
                        any((n == 1 or df[k] < n) and (only_cast or k not in cast)
                            for k in shared)))
        table.append(row)
    return table


def compare(scenes: Sequence[Any], text: str, events: Sequence[PlannedEvent],
            names: Iterable[str] = (),
            corrections: Optional[Dict[str, List[str]]] = None) -> Comparison:
    """Each scene with the planned events it holds. ``scenes`` are
    ``reverse_outline.Scene``s of ``text``; ``corrections`` map a
    ``scene_key`` to the event ids the writer chose ([] = not in the plan)."""
    corrections = corrections or {}
    known = {e.id for e in events}
    out = [SceneMatch(number=s.number, key=scene_key(s.opening)) for s in scenes]
    taken: set = set()
    for m in out:
        if m.key in corrections:
            m.event_ids = [i for i in corrections[m.key] if i in known]
            m.source = "yours"
            taken.update(m.event_ids)
    open_scenes = [i for i, m in enumerate(out) if m.source != "yours"]
    pool = [e for e in events if e.id not in taken]
    if open_scenes and pool:
        table = scores([text[s.start:s.end] for s in scenes], pool, names)
        n_ev, n_sc = len(events), len(scenes)
        place = {e.id: i for i, e in enumerate(events)}
        for e, row in zip(pool, table):
            want = (place[e.id] + 0.5) / n_ev * n_sc        # where the plan puts it
            best, best_rank = None, -1.0
            for i in open_scenes:
                share, distinctive = row[i]
                if share < THRESHOLD or not distinctive:
                    continue
                rank = share + ORDER_LEAN * (1 - min(1.0, abs(i + 0.5 - want) / max(1, n_sc)))
                if rank > best_rank:
                    best, best_rank = i, rank
            if best is not None:
                out[best].event_ids.append(e.id)
                out[best].score = max(out[best].score, row[best][0])
        for m in out:
            if m.source != "yours":
                m.event_ids.sort(key=lambda i: place.get(i, 0))
    return Comparison(events=list(events), scenes=out)


# ── Pacing across the book (the chart) ───────────────────────────────

@dataclass
class ScenePoint:
    chapter_id: str
    number: int
    words: int
    dialogue_share: float
    tension: Optional[float] = None    # 0..1, from 7.2's model reading; None without


_tension_source: Optional[Callable[[str, str, List[Tuple[int, int]]], Optional[List[float]]]] = None
_PACE_CACHE: Dict[str, List[Tuple[int, float]]] = {}


def set_tension_source(fn: Optional[Callable[[str, str, List[Tuple[int, int]]],
                                             Optional[List[float]]]]) -> None:
    """7.2's hook: ``fn(chapter_id, text, spans)`` → one tension (0..1) per
    span, or None when the model has not read that chapter."""
    global _tension_source
    _tension_source = fn


_marks_source: Optional[Callable[[str, str], List[int]]] = None


def set_marks_source(fn: Optional[Callable[[str, str], List[int]]]) -> None:
    """7.4's hook: ``fn(chapter_id, text)`` → the offsets of the chapter's
    scene markers ([] when none)."""
    global _marks_source
    _marks_source = fn


def _marks(cid: str, text: str) -> List[int]:
    if _marks_source is None:
        return []
    try:
        return sorted(_marks_source(cid, text) or [])
    except Exception as e:                         # a hook never breaks the chart
        print(f"[plan_match] scene markers unavailable: {e}")
        return []


def _pace(text: str, marks: Sequence[int] = ()) -> List[Tuple[int, float]]:
    from src.ai import reverse_outline as ro
    key = hashlib.sha1(((text or "") + "\x00" + ",".join(map(str, marks))).encode("utf-8")
                       ).hexdigest()
    if key not in _PACE_CACHE:
        rows = []
        for s, e in ro.split_scenes(text, marks):
            part = text[s:e]
            words = ro._words(part)
            talk = sum(ro._words(m.group(0)) for m in ro._QUOTED.finditer(part))
            rows.append((words, talk / words if words else 0.0))
        if len(_PACE_CACHE) > 256:
            _PACE_CACHE.clear()
        _PACE_CACHE[key] = rows
    return _PACE_CACHE[key]


def book_pacing(chapters: Sequence[Tuple[str, str]]) -> List[ScenePoint]:
    """Every scene of the manuscript, in order: (chapter id, text) pairs in."""
    from src.ai import reverse_outline as ro
    points: List[ScenePoint] = []
    for cid, text in chapters:
        if not (text or "").strip():
            continue
        marks = _marks(cid, text)
        rows = _pace(text, marks)
        tension = None
        if _tension_source is not None:
            try:
                tension = _tension_source(cid, text, ro.split_scenes(text, marks))
            except Exception as e:                     # a hook never breaks the chart
                print(f"[plan_match] tension source failed: {e}")
                tension = None
        for n, (words, share) in enumerate(rows, 1):
            t = tension[n - 1] if tension and len(tension) >= n else None
            points.append(ScenePoint(cid, n, words, share, t))
    return points
