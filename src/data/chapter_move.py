"""Move chapters from one manuscript to another (piece D.10).

The manuscript tree on the Write screen moves a chapter by drag and drop or
by its right-click **Move to ▸**: main → novella, novella → novella and
novella → main. Both go through ``move_chapters``; ``undo`` puts a move
back. No Qt.

**Rule 15: nothing overwritten, nothing lost.**

* **Files are moved, never copied and deleted.** A chapter's folder
  (``chapter_NNN``: every saved draft ``revision_NNN.md``, its saved copies
  ``backup_*.md``, its outline ``plan.md`` and anything else in it) is
  renamed into place with ``os.rename``. Folder names follow the chapter's
  place in its manuscript (as ↑ / ↓ keep them), so the chapters after it in
  the old manuscript, and after its new place in the new one, are renamed
  too. Every rename goes through a temporary name first, so two chapters
  can never meet at one name.
* **A taken name gets a number.** A folder already at a name the move needs
  (one no chapter uses, left behind by something else) is never written
  over: it is renamed ``chapter_NNN_2`` (``_3`` …) and kept. Undo gives it
  its name back.
* **An id clash gets a new id.** If the manuscript the chapter goes to
  already has a chapter with its id, the moved chapter gets a new one, and
  what refers to it is updated (below). Undo gives the old id back.
* **The Studio's cards follow it** (the fix after F.0). The Video Studio
  lists only the main manuscript's chapters, so a card's, chapter deck's
  or slide deck's ``chapter_id`` (and the Studio's chosen chapter) always
  means a main-manuscript chapter. After an id clash, those are pointed at
  the new id when the moved chapter came from the main manuscript; when it
  came from a novella they are left alone (they mean the chapter that
  stays). Folders on disk are not renamed: a deck keeps its own
  ``working_dir``. Undo and a failed move put the old ids back.
* **What travels in the project file** (the chapter's own entry): its
  text, title, drafts list, outline and planning (events, notes, to-dos,
  subplot notes, feedback) and annotations.
* **What travels in the state files** beside the project
  (``<project>.readiness.json``): the chapter's readiness results and
  stage, its digest, its style-sheet facts and its draft-beside-plan
  corrections (each kept per manuscript, so they are moved from the old
  manuscript's part to the new one's). The companion file
  (``<project>.companion_state.json``) keeps chapters by id alone, so its
  entry (last opened, where you stopped, heard marks) stays with the
  chapter; after an id clash it is copied to the new id. An entry already
  at the new place is never written over. A file from a newer version of
  the app is read-only and is left as it is.
* **If anything fails part-way,** every rename is undone in reverse, the
  project's chapters and the state files are put back as they were, and
  ``ChapterMoveError`` says what failed. The project file is saved only
  after everything else succeeded (atomically, by ``save_project``).
* **Undo** is the same move back to the same place, one chapter at a time in
  the order they stood. With nothing changed since, every chapter file and
  the state files come back byte for byte.
"""

from __future__ import annotations

import copy
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Every rename goes through here, so a test can make one fail part-way.
_rename = os.rename


class ChapterMoveError(RuntimeError):
    """A move that could not be made. Everything was put back."""


@dataclass
class Moved:
    chapter_id: str             # its id now
    original_id: str            # its id before the move (differs after a clash)
    from_scope: Optional[str]   # None = the main manuscript
    from_index: int             # its place there (0-based)
    title: str = ""


@dataclass
class MoveResult:
    target_scope: Optional[str]
    index: int
    moved: List[Moved] = field(default_factory=list)
    set_aside: List[Tuple[str, str]] = field(default_factory=list)   # (name, kept as), project-relative
    made_dirs: List[str] = field(default_factory=list)
    state_files: List[Tuple[str, Optional[bytes], Optional[bytes]]] = field(default_factory=list)
    refs: List[Tuple[Any, str, str, str]] = field(default_factory=list)  # (object, field, old, new)

    @property
    def renamed(self) -> List[Moved]:
        return [m for m in self.moved if m.chapter_id != m.original_id]


def _root(project: Any, scope: Optional[str]) -> str:
    from src.models.project import MAIN_CHAPTERS_ROOT
    if scope is None:
        return MAIN_CHAPTERS_ROOT
    return project.get_subproject(scope).chapters_root


def _scope_order(project: Any) -> List[Optional[str]]:
    return [s for s, _m in project.iter_manuscripts()]


def _repoint(ch: Any, old: str, new: str) -> None:
    ch.folder_path = new
    for r in ch.revisions:
        if r.file_path and r.file_path.startswith(old + "/"):
            r.file_path = new + r.file_path[len(old):]
    if ch.file_path and ch.file_path.startswith(old + "/"):
        ch.file_path = new + ch.file_path[len(old):]
    if ch.plan_file_path and ch.plan_file_path.startswith(old + "/"):
        ch.plan_file_path = new + ch.plan_file_path[len(old):]


def _numbered(path: Path) -> Path:
    """``chapter_004`` → the first free ``chapter_004_2``, ``_3`` …"""
    n = 2
    while True:
        candidate = path.with_name(f"{path.name}_{n}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        n += 1


# ── State files ────────────────────────────────────────────────────────

def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _put_bytes(path: Path, data: Optional[bytes]) -> None:
    """Put a state file back exactly (or remove it, if it was not there)."""
    if data is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def move_entries(data: Dict[str, Any], moves: Sequence[Tuple[str, str, str, str]]) -> bool:
    """Move each chapter's entries in a readiness file's ``data`` from
    ``[old manuscript][old id]`` to ``[new manuscript][new id]``: in
    ``manuscripts → … → chapters`` and in every per-manuscript, per-chapter
    part (digest, ledger, plan_matches, and any added later). An entry
    already at the new place is never written over. True if anything moved."""
    changed = False
    for key, top in list(data.items()):
        if not isinstance(top, dict):
            continue
        for fs, fid, ts, tid in moves:
            if fs == ts and fid == tid:
                continue
            if key == "manuscripts":
                src_m = top.get(fs)
                src = src_m.get("chapters") if isinstance(src_m, dict) else None
                if not isinstance(src, dict) or fid not in src:
                    continue
                dst_m = top.setdefault(ts, {})
                if not isinstance(dst_m, dict):
                    continue
                dst = dst_m.setdefault("chapters", {})
            else:
                src = top.get(fs)
                if not isinstance(src, dict) or fid not in src:
                    continue
                dst = top.setdefault(ts, {})
            if not isinstance(dst, dict) or tid in dst:
                continue
            dst[tid] = src.pop(fid)
            changed = True
    return changed


def _move_state(project: Any, moves: List[Tuple[str, str, str, str]],
                renamed: List[Tuple[str, str]], result: MoveResult) -> None:
    """Carry the chapters' per-chapter state; record each file's bytes
    before and after in ``result`` (for a rollback and for Undo)."""
    from src.data import companion_state as cs
    from src.data import readiness_state as rs
    with rs._lock:
        data = rs.load(project)
        if not rs.is_read_only(data) and move_entries(data, moves):
            path = rs.readiness_path(project)
            before = _read_bytes(path)
            result.state_files.append((str(path), before, None))
            if not rs.save(project, data):
                raise ChapterMoveError("the readiness file could not be saved")
            result.state_files[-1] = (str(path), before, _read_bytes(path))
    if renamed:
        data = cs.load(project)
        chapters = data.get("chapters")
        if isinstance(chapters, dict):
            changed = False
            for old, new in renamed:
                if old in chapters and new not in chapters:
                    chapters[new] = copy.deepcopy(chapters[old])
                    changed = True
            if changed:
                path = cs.state_path(project)
                before = _read_bytes(path)
                result.state_files.append((str(path), before, None))
                from src.data import safe_store
                if not safe_store.save(path, data, indent=1):
                    raise ChapterMoveError("the companion file could not be saved")
                result.state_files[-1] = (str(path), before, _read_bytes(path))


def _retarget_refs(project: Any, renamed: List[Tuple[str, str, str]],
                   clashing_titles: Dict[str, str]) -> List[Tuple[Any, str, str, str]]:
    """After an id clash: point what names the moved chapter at its new id.
    Only references that also carry the chapter's title (a character's
    reading of a chapter) can tell the two chapters apart; those whose title
    is the moved chapter's (and not the other one's) are updated."""
    changed = []
    for old, new, title in renamed:
        if not title or clashing_titles.get(old) == title:
            continue
        for character in getattr(project, "characters", []) or []:
            for snap in getattr(character, "personality_arc", []) or []:
                if getattr(snap, "chapter_id", None) == old and \
                        getattr(snap, "chapter_title", "") == title:
                    snap.chapter_id = new
                    changed.append((snap, "chapter_id", old, new))
    return changed


def _retarget_studio(project: Any, renamed: List[Tuple[str, str]]
                     ) -> List[Tuple[Any, str, str, str]]:
    """After an id clash: point the Studio's cards, chapter decks, slide
    decks and chosen chapter at the moved chapter's new id. ``renamed`` holds
    only chapters that left the main manuscript (see the module notes)."""
    studio = getattr(project, "video_studio", None)
    if studio is None or not renamed:
        return []
    ids = dict(renamed)
    changed = []
    for name in ("scenes", "chapter_decks", "slide_decks"):
        for obj in getattr(studio, name, []) or []:
            old = getattr(obj, "chapter_id", None)
            if old and old in ids:
                obj.chapter_id = ids[old]
                changed.append((obj, "chapter_id", old, ids[old]))
    old = getattr(studio, "active_chapter_id", "") or ""
    if old in ids:
        studio.active_chapter_id = ids[old]
        changed.append((studio, "active_chapter_id", old, ids[old]))
    return changed


# ── The move ───────────────────────────────────────────────────────────

def move_chapters(project: Any, chapters: Sequence[Tuple[Optional[str], str]],
                  target_scope: Optional[str], index: Optional[int] = None, *,
                  project_file: Optional[str] = None,
                  ids: Optional[Dict[str, str]] = None) -> Optional[MoveResult]:
    """Move ``chapters`` (``(scope, chapter id)`` pairs, scope None = main)
    into ``target_scope`` at ``index`` (its place among the chapters there;
    None = after the last). Chapters already there are left alone. ``ids``
    maps a chapter's id to the id it should take if free (Undo uses it).

    With ``project_file`` the project is saved first (so the disk matches
    what is in memory), the folders are moved, and it is saved again.
    Returns what was done (for Undo), or None when there was nothing to
    move. Raises ``ChapterMoveError`` after putting everything back."""
    target_scope = target_scope or None
    target_ms = project.get_manuscript_for(target_scope)
    if target_ms is None:
        raise ChapterMoveError("That manuscript is no longer in the project.")

    picked = []                                   # (scope, chapter, index)
    seen = set()
    for scope, cid in chapters:
        scope = scope or None
        if (scope, cid) in seen or scope == target_scope:
            continue
        seen.add((scope, cid))
        ms = project.get_manuscript_for(scope)
        found = next(((i, c) for i, c in enumerate(ms.chapters) if c.id == cid),
                     None) if ms is not None else None
        if found is None:
            raise ChapterMoveError(f"Chapter {cid!r} is no longer in that manuscript.")
        picked.append((scope, found[1], found[0]))
    if not picked:
        return None
    order = _scope_order(project)
    picked.sort(key=lambda p: (order.index(p[0]), p[2]))
    moving = [c for _s, c, _i in picked]
    moving_ids = {id(c) for c in moving}

    project_dir = Path(project_file).parent if project_file else None
    if project_file:
        try:
            project.save_project(project_file)
        except Exception as e:                    # nothing has been touched yet
            raise ChapterMoveError(f"The project could not be saved first: {e}") from e
        for ch in moving:                         # prose in memory, not only on disk
            if not ch.content and (ch.folder_path or ch.file_path):
                ch.load_content_from_file(project_dir)

    # ── The new order of every manuscript the move touches ──
    scopes = [s for s in order if s == target_scope or any(p[0] == s for p in picked)]
    old_lists = {s: list(project.get_manuscript_for(s).chapters) for s in scopes}
    new_lists = {s: [c for c in old_lists[s] if id(c) not in moving_ids] for s in scopes}
    target_old = old_lists[target_scope]
    at = len(target_old) if index is None else max(0, min(int(index), len(target_old)))
    new_lists[target_scope] = target_old[:at] + moving + target_old[at:]

    result = MoveResult(target_scope=target_scope, index=at)

    # ── Ids: a clash with the target gets a new one ──
    taken = {c.id for c in target_old}
    new_id: Dict[int, str] = {}
    for ch in moving:
        want = (ids or {}).get(ch.id, ch.id)
        cid = want if want not in taken else (ch.id if ch.id not in taken else None)
        if cid is None:
            cid = str(uuid.uuid4())
        taken.add(cid)
        new_id[id(ch)] = cid

    # ── Where each folder goes ──
    target_root = _root(project, target_scope)
    plan = []                                     # (chapter, new number, new root, old folder, new folder)
    for s in scopes:
        ms = project.get_manuscript_for(s)
        for pos, ch in enumerate(new_lists[s], 1):
            if id(ch) in moving_ids:
                root = target_root
            else:
                root = ch._chapter_root() if ch.folder_path else ms.folder_root
            old = ch.folder_path
            new = f"{root}/chapter_{pos:03d}" if old else None
            plan.append((ch, pos, root, old, new))
    renames = [(ch, old, new) for ch, _p, _r, old, new in plan
               if old and new != old and project_dir and (project_dir / old).is_dir()]
    if project_dir:
        changing = {old for _c, _p, _r, old, new in plan if old and new != old}
        staying = {ch.folder_path for _s, ms in project.iter_manuscripts() for ch in ms.chapters
                   if ch.folder_path} - changing
        for _ch, _old, new in renames:
            if new in staying:
                raise ChapterMoveError(f"The folder {new} belongs to another chapter.")

    snapshot = [(ch, ch.id, ch.number, ch.folder_path, ch.file_path, ch.plan_file_path,
                 ch.folder_root, [(r, r.file_path) for r in ch.revisions])
                for s in scopes for ch in old_lists[s]]
    totals = {s: project.get_manuscript_for(s).total_word_count for s in scopes}
    journal: List[Tuple[Path, Path]] = []

    def rollback() -> None:
        for src, dst in reversed(journal):
            try:
                os.rename(dst, src)
            except OSError as e:
                print(f"[chapter move] could not put back {dst}: {e}")
        for d in reversed(result.made_dirs):
            try:
                (project_dir / d).rmdir()
            except OSError:
                pass
        for ch, cid, num, fp, flp, pfp, fr, revs in snapshot:
            ch.id, ch.number, ch.folder_path, ch.file_path = cid, num, fp, flp
            ch.plan_file_path, ch.folder_root = pfp, fr
            for r, rfp in revs:
                r.file_path = rfp
        for s in scopes:
            ms = project.get_manuscript_for(s)
            ms.chapters = old_lists[s]
            ms.total_word_count = totals[s]
        for obj, attr, old, _new in result.refs:
            setattr(obj, attr, old)
        for path, before, _after in result.state_files:
            try:
                _put_bytes(Path(path), before)
            except Exception as e:
                print(f"[chapter move] could not put back {path}: {e}")

    try:
        # ── Disk: through temporary names, then into place ──
        if project_dir and renames:
            staged = []
            for ch, old, new in renames:
                src = project_dir / old
                tmp = src.parent / f"_moving_{uuid.uuid4().hex[:10]}"
                _rename(src, tmp)
                journal.append((src, tmp))
                staged.append((tmp, project_dir / new))
            for tmp, dst in staged:
                if dst.exists() or dst.is_symlink():   # a folder no chapter uses
                    aside = _numbered(dst)
                    _rename(dst, aside)
                    journal.append((dst, aside))
                    result.set_aside.append((str(dst.relative_to(project_dir)),
                                             str(aside.relative_to(project_dir))))
                missing = []
                parent = dst.parent
                while not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                for d in reversed(missing):
                    d.mkdir()
                    result.made_dirs.append(str(d.relative_to(project_dir)))
                _rename(tmp, dst)
                journal.append((tmp, dst))

        # ── The model ──
        for ch, pos, root, old, new in plan:
            ch.number = pos
            ch.folder_root = root
            if old and new != old:
                _repoint(ch, old, new)
        for s in scopes:
            ms = project.get_manuscript_for(s)
            ms.chapters = new_lists[s]
            ms.total_word_count = sum(c.word_count for c in ms.chapters)
        from src.data.readiness_state import scope_key
        moves, renamed, renamed_titled, from_main = [], [], [], []
        clashing = {c.id: c.title for c in target_old}
        for scope, ch, idx in picked:
            cid = new_id[id(ch)]
            result.moved.append(Moved(cid, ch.id, scope, idx, ch.title))
            moves.append((scope_key(scope), ch.id, scope_key(target_scope), cid))
            if cid != ch.id:
                renamed.append((ch.id, cid))
                renamed_titled.append((ch.id, cid, ch.title))
                if scope is None:
                    from_main.append((ch.id, cid))
                ch.id = cid
        project._normalize_manuscript_roots()
        result.refs = _retarget_refs(project, renamed_titled, clashing)
        result.refs += _retarget_studio(project, from_main)

        # ── What is kept beside the project ──
        _move_state(project, moves, renamed, result)

        if project_file:
            project.save_project(project_file)
    except Exception as e:
        rollback()
        if isinstance(e, ChapterMoveError):
            raise
        raise ChapterMoveError(str(e) or type(e).__name__) from e
    return result


def undo(project: Any, result: MoveResult, *,
         project_file: Optional[str] = None) -> List[str]:
    """Put a move back: each chapter to its old manuscript and place, with
    its old id, folders kept aside given their names back, and, when
    nothing has changed them since, the state files exactly as they were.
    Returns the ids of the chapters put back (as they are now)."""
    unchanged = all(_read_bytes(Path(p)) == after for p, _b, after in result.state_files)
    back: List[str] = []
    for m in sorted(result.moved, key=lambda m: (m.from_scope or "", m.from_index)):
        scope, ch = project.find_chapter_with_scope(m.chapter_id)
        if ch is None or project.get_manuscript_for(m.from_scope) is None:
            continue
        if (scope or None) == (m.from_scope or None):
            back.append(m.chapter_id)
            continue
        r = move_chapters(project, [(scope, m.chapter_id)], m.from_scope, m.from_index,
                          project_file=project_file, ids={m.chapter_id: m.original_id})
        if r is not None:
            back.extend(x.chapter_id for x in r.moved)
            for obj, attr, old, new in result.refs:
                if getattr(obj, attr, None) == new:
                    setattr(obj, attr, old)
    project_dir = Path(project_file).parent if project_file else None
    if project_dir:
        for name, kept in reversed(result.set_aside):
            src, dst = project_dir / kept, project_dir / name
            if src.exists() and not dst.exists():
                try:
                    os.rename(src, dst)
                except OSError as e:
                    print(f"[chapter move] could not give {kept} its name back: {e}")
        for d in reversed(result.made_dirs):
            try:
                (project_dir / d).rmdir()                 # only if empty
            except OSError:
                pass
    if unchanged:
        for path, before, _after in result.state_files:
            try:
                _put_bytes(Path(path), before)
            except Exception as e:
                print(f"[chapter move] could not put back {path}: {e}")
    if project_file and result.refs:
        project.save_project(project_file)
    return back
