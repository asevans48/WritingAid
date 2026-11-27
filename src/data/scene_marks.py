"""Scene markers, kept beside the text (piece 7.4).

A marker says "a new scene starts at this paragraph". It is stored beside
the chapter, **never in its text**: nothing here writes a chapter, its
saved drafts (``revision_*.md``) or its copies (``backup_*.md``).

**What a paragraph is.** A line of the chapter that is not blank (the
editor's paragraphs; prose separated by blank lines has one per line).

**Anchoring.** A marker keeps the paragraph's place (``p``, its index
among the paragraphs) and its opening words (``w``, about 40 characters).
It is found again by those words, the nearest to its place when several
paragraphs open alike; if the opening was edited a little, the closest
opening near its place still finds it. So it follows its paragraph when
text is added or cut above it. A marker whose paragraph is gone is
**left out** (``resolve(...).lost``; the outline says so in one line) but
kept, so it comes back if the paragraph does (Undo, a paste); the writer
can forget it there.

**Where it is kept.** In the readiness file beside the project
(``<project>.readiness.json``), under a new top-level key:

    "scene_marks": {scope: {chapter id: {"v": 1, "marks": [{"p": 4, "w": "…"}]}}}

Written only when the writer adds a marker, so a project without markers
is unchanged byte for byte. An older file reads as no markers; an older
app keeps the key untouched (it keeps unknown keys). Per manuscript and
chapter, like the other per-chapter parts, so D.10's move carries it
(``chapter_move.move_entries``, including the id-clash path) and its Undo
brings it back. Written through ``readiness_state.update`` (safe write,
one lock, other keys kept, read-only for a newer file).

**Who reads it.** ``reverse_outline.split_scenes(text, marks=offsets(...))``
and so the outline (7.1), the model's reading (7.2), the chart (7.3) and
the plan matching. The export copy can carry the standard "#"
(``with_breaks``). Undo: ``undo_last``. No Qt.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

KEY = "scene_marks"
VERSION = 1
OPENING = 40                 # characters of a paragraph's opening kept as its anchor
CLOSE_ENOUGH = 0.75          # an edited opening still finds its paragraph above this
BREAK = "#"                  # the standard manuscript scene break, for exports
ANY = object()               # "find the chapter's manuscript"


# ── Paragraphs ────────────────────────────────────────────────────────

def paragraphs(text: str) -> List[Tuple[int, int, str]]:
    """(line number, offset, line) of each paragraph: each line that is not blank."""
    out = []
    pos = 0
    for n, line in enumerate((text or "").split("\n")):
        if line.strip():
            out.append((n, pos, line))
        pos += len(line) + 1
    return out


def opening(line: str) -> str:
    """A paragraph's anchor: its first words, spaces evened out."""
    return " ".join((line or "").split())[:OPENING]


@dataclass
class Found:
    mark: Dict[str, Any]
    para: int                 # its paragraph's index now
    line: int                 # that paragraph's line number (the editor's block)
    offset: int               # where it starts in the text


@dataclass
class Resolved:
    found: List[Found] = field(default_factory=list)       # in text order
    lost: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def offsets(self) -> List[int]:
        return [f.offset for f in self.found if f.para > 0]


def resolve(marks: Sequence[Dict[str, Any]], text: str) -> Resolved:
    """Where each marker's paragraph is in ``text`` now."""
    paras = paragraphs(text)
    keys = [opening(line) for _n, _o, line in paras]
    taken: set = set()
    out = Resolved()
    for m in marks or []:
        if not isinstance(m, dict):
            continue
        want = opening(str(m.get("w", "")))
        try:
            place = int(m.get("p", 0))
        except (TypeError, ValueError):
            place = 0
        if not want:
            out.lost.append(m)
            continue
        exact = [i for i, k in enumerate(keys) if k == want and i not in taken]
        if exact:
            i = min(exact, key=lambda i: (abs(i - place), i))
        else:
            near = []
            for i, k in enumerate(keys):
                if i in taken or not k:
                    continue
                r = difflib.SequenceMatcher(None, k, want).ratio()
                if r >= CLOSE_ENOUGH:
                    near.append((-r, abs(i - place), i))
            if not near:
                out.lost.append(m)
                continue
            i = min(near)[2]
        taken.add(i)
        n, off, _line = paras[i]
        out.found.append(Found(m, i, n, off))
    out.found.sort(key=lambda f: f.para)
    return out


# ── The store ─────────────────────────────────────────────────────────

_cache: Dict[str, Tuple[Tuple[int, int], Dict[str, Any]]] = {}
_UNDO: List[Dict[str, Any]] = []
UNDO_DEPTH = 50


def _path_key(project: Any) -> str:
    from src.data import readiness_state as rs
    return str(rs.readiness_path(project))


def _all(project: Any) -> Dict[str, Any]:
    """{scope key: {chapter id: entry}}; {} on any error. Cached by the
    file's size and time, so drawing the editor does not read the file."""
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
        store = rs.load(project).get(KEY, {})
        store = store if isinstance(store, dict) else {}
        _cache[str(path)] = (stamp, store)
        return store
    except Exception as e:
        print(f"[scene marks] unavailable: {e}")
        return {}


def scope_of(project: Any, chapter_id: str, chapter: Any = None) -> Optional[str]:
    """The manuscript (None = main) holding the chapter: by the object when
    given (ids can clash across manuscripts), else by id."""
    try:
        if chapter is not None:
            for scope, ms in project.iter_manuscripts():
                if any(c is chapter for c in ms.chapters):
                    return scope
        return project.find_chapter_with_scope(chapter_id)[0]
    except Exception:
        return None


def _scope(project: Any, chapter_id: str, scope: Any) -> str:
    from src.data import readiness_state as rs
    return rs.scope_key(scope_of(project, chapter_id) if scope is ANY else scope)


def stored(project: Any, chapter_id: str, scope: Any = ANY) -> List[Dict[str, Any]]:
    """The chapter's markers as stored (copies); [] when none."""
    entry = (_all(project).get(_scope(project, chapter_id, scope)) or {})
    entry = entry.get(chapter_id) if isinstance(entry, dict) else None
    marks = entry.get("marks") if isinstance(entry, dict) else None
    return [dict(m) for m in marks if isinstance(m, dict)] if isinstance(marks, list) else []


def any_marks(project: Any) -> bool:
    return any(isinstance(e, dict) and e.get("marks")
               for chapters in _all(project).values() if isinstance(chapters, dict)
               for e in chapters.values())


def for_text(project: Any, chapter_id: str, text: str, scope: Any = ANY) -> Resolved:
    return resolve(stored(project, chapter_id, scope), text)


def offsets(project: Any, chapter_id: str, text: str, scope: Any = ANY) -> List[int]:
    """Where the chapter's marked scenes start in ``text`` (for
    ``split_scenes``); [] when it has none. Never raises."""
    try:
        if project is None or not (text or "").strip():
            return []
        marks = stored(project, chapter_id, scope)
        return resolve(marks, text).offsets if marks else []
    except Exception as e:
        print(f"[scene marks] {e}")
        return []


def _write(project: Any, chapter_id: str, scope_key: str, marks: List[Dict[str, Any]]) -> bool:
    from src.data import readiness_state as rs

    def change(data):                              # every other key is kept
        store = data.get(KEY)
        if not isinstance(store, dict):
            store = data[KEY] = {}
        chapters = store.get(scope_key)
        if not isinstance(chapters, dict):
            chapters = store[scope_key] = {}
        if marks:
            chapters[chapter_id] = {"v": VERSION, "marks": marks}
        else:
            chapters.pop(chapter_id, None)
            if not chapters:
                store.pop(scope_key, None)
            if not store:
                data.pop(KEY, None)
    try:
        return bool(rs.update(project, change))
    except Exception as e:
        print(f"[scene marks] not saved: {e}")
        return False
    finally:
        _cache.clear()


def set_marks(project: Any, chapter_id: str, marks: List[Dict[str, Any]],
              scope: Any = ANY, label: str = "", undoable: bool = True) -> bool:
    """Store the chapter's markers (in paragraph order); records Undo."""
    sk = _scope(project, chapter_id, scope)
    before = stored(project, chapter_id, sk)
    marks = sorted((dict(m) for m in marks), key=lambda m: int(m.get("p", 0)))
    if marks == before:
        return True
    ok = _write(project, chapter_id, sk, marks)
    if ok and undoable:
        _UNDO.append({"path": _path_key(project), "scope": sk, "chapter_id": chapter_id,
                      "before": before, "after": marks, "label": label})
        del _UNDO[:-UNDO_DEPTH]
    return ok


def _mark_for(text: str, para: int) -> Optional[Dict[str, Any]]:
    paras = paragraphs(text)
    if not 0 < para < len(paras):
        return None
    return {"p": para, "w": opening(paras[para][2])}


def para_at_line(text: str, line: int) -> Optional[int]:
    """The paragraph at ``line`` (or the first one after it when the line is blank)."""
    for i, (n, _o, _l) in enumerate(paragraphs(text)):
        if n >= line:
            return i
    return None


def marked_at(project: Any, chapter_id: str, text: str, para: int,
              scope: Any = ANY) -> Optional[Dict[str, Any]]:
    """The stored marker at paragraph ``para`` now, or None."""
    for f in for_text(project, chapter_id, text, scope).found:
        if f.para == para:
            return f.mark
    return None


def _current(project: Any, chapter_id: str, text: str, scope: Any) -> List[Dict[str, Any]]:
    """The stored markers with their anchors brought up to date (lost ones kept)."""
    r = for_text(project, chapter_id, text, scope)
    paras = paragraphs(text)
    marks = [dict(f.mark, p=f.para, w=opening(paras[f.para][2])) for f in r.found]
    return marks + [dict(m) for m in r.lost]


def add(project: Any, chapter_id: str, text: str, paras: Sequence[int],
        scope: Any = ANY, label: str = "") -> int:
    """Mark a scene start at each paragraph index; returns how many were added."""
    marks = _current(project, chapter_id, text, scope)
    found_at = {f.para for f in for_text(project, chapter_id, text, scope).found}
    added = 0
    for para in paras:
        m = _mark_for(text, para)
        if m is None or para in found_at:
            continue
        marks.append(m)
        found_at.add(para)
        added += 1
    if added and not set_marks(project, chapter_id, marks, scope,
                               label or ("Scene break marked" if added == 1
                                         else f"{added} scene breaks marked")):
        return 0
    return added


def remove(project: Any, chapter_id: str, text: str, para: int, scope: Any = ANY) -> bool:
    """Take away the marker at paragraph ``para``."""
    r = for_text(project, chapter_id, text, scope)
    hit = next((f for f in r.found if f.para == para), None)
    if hit is None:
        return False
    marks = [dict(f.mark, p=f.para) for f in r.found if f is not hit] + [dict(m) for m in r.lost]
    return set_marks(project, chapter_id, marks, scope, "Scene break removed")


def forget_lost(project: Any, chapter_id: str, text: str, scope: Any = ANY) -> bool:
    """Forget the markers whose paragraph is gone."""
    r = for_text(project, chapter_id, text, scope)
    if not r.lost:
        return False
    return set_marks(project, chapter_id, [dict(f.mark, p=f.para) for f in r.found], scope,
                     "Lost scene markers forgotten")


def refresh(project: Any, chapter_id: str, text: str, scope: Any = ANY) -> bool:
    """Bring the anchors up to date with the text (after edits): each
    found marker's place and opening words. Lost ones are kept. Writes
    only when something moved; not an Undo step."""
    marks = stored(project, chapter_id, scope)
    if not marks or not (text or "").strip():
        return False
    now = _current(project, chapter_id, text, scope)
    if sorted(now, key=lambda m: int(m.get("p", 0))) == marks:
        return False
    return set_marks(project, chapter_id, now, scope, undoable=False)


# ── Undo ──────────────────────────────────────────────────────────────

def last_change(project: Any) -> Optional[Dict[str, Any]]:
    if project is None:
        return None
    key = _path_key(project)
    return next((c for c in reversed(_UNDO) if c["path"] == key), None)


def undo_last(project: Any) -> Optional[str]:
    """Put the last marker change in this project back; returns its label
    ("" when unnamed) or None when there was nothing to undo."""
    change = last_change(project)
    if change is None:
        return None
    _UNDO.remove(change)
    if not _write(project, change["chapter_id"], change["scope"], change["before"]):
        return None
    return change.get("label") or ""


# ── The model's scenes (7.2) ──────────────────────────────────────────

def from_model(project: Any, chapter_id: str, text: str,
               scope: Any = ANY) -> List[Tuple[int, str]]:
    """Paragraphs the model's reading of the chapter starts a scene at that
    are not scene starts yet: [(paragraph index, its opening)]. Stored
    readings only, of this very text; [] when there is none."""
    from src.ai import chapter_digest, scene_reading
    from src.ai.reverse_outline import split_scenes
    entry = scene_reading.digest_entry(project, chapter_id, text)
    if not entry:
        return []
    paras = paragraphs(text)
    starts = {s for s, _e in split_scenes(text, offsets(project, chapter_id, text, scope))}
    out, seen = [], set()
    for s in entry.get("scenes", []) or []:
        if not isinstance(s, dict) or chapter_digest.is_template_echo(
                s.get("pov") or "", s.get("what") or ""):
            continue
        start = s.get("start", -1)
        if not isinstance(start, int) or start < 0:
            continue
        i = max((k for k, (_n, off, _l) in enumerate(paras) if off <= start), default=None)
        if not i or i in seen:
            continue
        off, line = paras[i][1], paras[i][2]
        lead = len(line) - len(line.lstrip())
        if any(off <= st <= off + lead for st in starts):
            continue                               # already a scene's start
        seen.add(i)
        out.append((i, opening(line)))
    return sorted(out)


# ── Export ────────────────────────────────────────────────────────────

def insert_breaks(text: str, at: Sequence[int]) -> str:
    """``text`` with the standard "#" break before each offset (a
    paragraph start), separated as the text separates its paragraphs."""
    if not at:
        return text
    blocks = [b for b in (text or "").replace("\r\n", "\n").split("\n\n") if b.strip()]
    sep = "\n\n" if len(blocks) > 1 else "\n"
    out, last = [], 0
    for off in sorted(set(at)):
        out.append(text[last:off])
        out.append(BREAK + sep)
        last = off
    out.append(text[last:])
    return "".join(out)


def with_breaks(project: Any, chapters: Sequence[Any]) -> List[Any]:
    """Copies of ``chapters`` with a "#" at each marked scene, for an export
    only; a chapter without markers is passed as it is. The chapters
    themselves are never changed."""
    out = []
    for ch in chapters:
        text = getattr(ch, "content", "") or ""
        at = offsets(project, getattr(ch, "id", ""), text,
                     scope_of(project, getattr(ch, "id", ""), ch))
        if not at:
            out.append(ch)
            continue
        new = insert_breaks(text, at)
        try:
            out.append(ch.model_copy(update={"content": new}))
        except Exception:
            dup = copy.copy(ch)
            dup.content = new
            out.append(dup)
    return out
