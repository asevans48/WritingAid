"""Whole-project checkpoint / restore.

A *project checkpoint* is a single zip archive containing every
file under the project directory at a moment in time — chapters,
revisions, the project JSON, character / worldbuilding sidecars,
everything. The user can list past checkpoints, restore one
(rolling the project back to that exact state), or delete them
to reclaim disk space.

Distinct from the **paragraph-checkpoint** dialog (the
``CheckpointManifestDialog`` in ``src/ui/checkpoint_manifest_dialog.py``),
which is a paragraph-by-paragraph reviewer that produces a new
draft. Both share the word "checkpoint" because both are
"snapshots the user can come back to" — just at very different
granularities.

Storage layout::

    <project_dir>/
        project.json
        chapters/
            chapter_001/
                revision_001.md
                ...
        characters.json
        ...
        _checkpoints/                   ← created on first checkpoint
            20260502_173000_Pre-edit.zip
            20260502_180412_After-rewrite.zip
            _meta_<id>.json             ← per-checkpoint metadata
            ...

Each archive embeds its own ``_checkpoint_meta.json`` at the
archive root so even if the sidecar metadata file is lost the zip
is still self-describing.

Backwards compatibility — projects that have never used the
checkpoint feature won't have a ``_checkpoints/`` directory.
:func:`list_checkpoints` returns an empty list in that case
without creating the directory; nothing else in the project
load/save path depends on the directory existing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


CHECKPOINTS_DIRNAME = "_checkpoints"
META_FILENAME_IN_ZIP = "_checkpoint_meta.json"

# Files / directories at the project root we always exclude from a
# checkpoint zip:
#   * ``_checkpoints/`` — would create infinite recursion (the
#     archive of a checkpoint zipping all previous checkpoints).
#   * ``.DS_Store`` — macOS noise.
#   * ``*.tmp`` / ``*.json.tmp`` — atomic-write scratch files
#     (project.save_project leaves these mid-rename if interrupted).
_EXCLUDED_DIRS = {CHECKPOINTS_DIRNAME, "__pycache__", ".git"}
_EXCLUDED_FILE_SUFFIXES = (".tmp", ".json.tmp", ".pyc")
_EXCLUDED_FILE_NAMES = {".DS_Store"}

# Already-compressed media: stored as-is. Compressing it again costs minutes
# on a large Video Studio folder and saves almost nothing. The archive's
# contents are the same either way.
_STORED_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mov",
                    ".m4v", ".webm", ".mkv", ".avi", ".png", ".jpg", ".jpeg", ".gif",
                    ".webp", ".heic", ".zip", ".gz", ".docx", ".epub", ".pdf",
                    ".safetensors", ".bin", ".gguf", ".npz")


# Video Studio media lives in "<project name>_video_studio" folders at the top
# of the project folder. A checkpoint can leave them out ("writing only"); a
# restore leaves them alone when the checkpoint does not contain them.
VIDEO_STUDIO_SUFFIX = "_video_studio"


def _is_video_studio(rel_path: Path) -> bool:
    parts = rel_path.parts
    return len(parts) > 1 and parts[0].endswith(VIDEO_STUDIO_SUFFIX)


def video_studio_dirs(project_dir: Path) -> List[Path]:
    """The Video Studio folders inside ``project_dir``."""
    project_dir = Path(project_dir)
    try:
        return [d for d in project_dir.iterdir()
                if d.is_dir() and d.name.endswith(VIDEO_STUDIO_SUFFIX)]
    except OSError:
        return []


def video_studio_size(project_dir: Path) -> int:
    """Bytes in the project's Video Studio folders (0 when there are none)."""
    total = 0
    for d in video_studio_dirs(project_dir):
        for f in d.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    return total


def contains_video_studio(checkpoint: "CheckpointInfo") -> bool:
    """Whether the checkpoint's archive holds any Video Studio files.
    Read from the archive itself, so it is right for old checkpoints too."""
    try:
        with zipfile.ZipFile(checkpoint.zip_path, "r") as zf:
            return any(n.split("/", 1)[0].endswith(VIDEO_STUDIO_SUFFIX) and "/" in n
                       for n in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


class CheckpointCancelled(Exception):
    """The writer cancelled a checkpoint before it finished; nothing was kept."""


def _report(progress, done: int, total: int, label: str = "") -> None:
    if progress is not None:
        try:
            progress(done, total, label)
        except Exception:
            pass


@dataclass
class CheckpointInfo:
    """Metadata for a single project checkpoint zip.

    Populated from the embedded ``_checkpoint_meta.json`` (when
    present) or inferred from the zip filename (legacy / external
    archives). The dialog renders one row per ``CheckpointInfo``
    with these fields directly.
    """
    id: str
    name: str
    description: str
    created_at: str          # ISO-8601 UTC
    zip_path: str            # absolute path to the .zip on disk
    size_bytes: int
    project_basename: str = ""  # original project_dir name at snapshot time
    raw: dict = field(default_factory=dict)


# ── Helpers ─────────────────────────────────────────────────


def _checkpoints_dir(project_dir: Path, *, create: bool = False) -> Path:
    p = Path(project_dir) / CHECKPOINTS_DIRNAME
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_filename_chunk(name: str, *, max_len: int = 40) -> str:
    """Sanitise the user's checkpoint name so it's safe to embed
    in a filename. Strips path separators, control chars, and
    anything beyond a small safe character set so the resulting
    file is portable across macOS / Windows / Linux."""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "-", (name or "").strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = "checkpoint"
    return cleaned[:max_len]


def _should_skip_path(rel_path: Path) -> bool:
    """Whether the relative path within ``project_dir`` should be
    omitted from the checkpoint zip."""
    parts = rel_path.parts
    if not parts:
        return True
    if parts[0] in _EXCLUDED_DIRS:
        return True
    name = rel_path.name
    if name in _EXCLUDED_FILE_NAMES:
        return True
    if any(name.endswith(s) for s in _EXCLUDED_FILE_SUFFIXES):
        return True
    return False


# ── Public API ──────────────────────────────────────────────


def create_checkpoint(project_dir: Path,
                      name: str,
                      *,
                      description: str = "",
                      progress=None,
                      cancelled=None,
                      include_video_studio: bool = True) -> CheckpointInfo:
    """Snapshot the entire project directory into a zip checkpoint.

    The archive includes everything under ``project_dir`` except
    the ``_checkpoints/`` folder itself (preventing recursion) and
    any obvious noise files (``.DS_Store``, ``__pycache__``,
    ``.tmp`` scratch files, ``.pyc``).

    Returns a :class:`CheckpointInfo` describing the resulting
    zip. The zip contains a top-level ``_checkpoint_meta.json``
    so it stays self-describing even if separated from this
    project's ``_checkpoints/`` directory.

    Optional ``progress(done_bytes, total_bytes, label)`` is called as
    files are added, and ``cancelled()`` is checked between files; when
    it returns True the half-built archive is removed and
    :class:`CheckpointCancelled` is raised. Both may run on a worker
    thread.

    ``include_video_studio=False`` makes a *writing only* checkpoint: the
    Video Studio folders (audio and video, often gigabytes) are left out.
    Restoring it leaves the current Video Studio folders as they are.
    """
    project_dir = Path(project_dir)
    if not project_dir.exists() or not project_dir.is_dir():
        raise ValueError(
            f"Project directory does not exist: {project_dir}")
    cp_dir = _checkpoints_dir(project_dir, create=True)

    cp_id = uuid.uuid4().hex[:12]
    created_at = datetime.now().isoformat(timespec="seconds")
    safe = _safe_filename_chunk(name)
    fname = (f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
             f"_{safe}.zip")
    zip_path = cp_dir / fname

    meta = {
        "id": cp_id,
        "name": name.strip() or safe,
        "description": (description or "").strip(),
        "created_at": created_at,
        "project_basename": project_dir.name,
        "format_version": 1,
        "includes_video_studio": bool(include_video_studio),
    }

    # Build the archive in a tempfile then atomic-rename in so the
    # checkpoint either fully exists or doesn't — never half-written.
    tmp_zip = zip_path.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(
                tmp_zip, "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6) as zf:
            zf.writestr(META_FILENAME_IN_ZIP,
                        json.dumps(meta, indent=2))
            files = []
            for path in sorted(project_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(project_dir)
                if _should_skip_path(rel):
                    continue
                if not include_video_studio and _is_video_studio(rel):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                files.append((path, rel, size))
            total = sum(size for _, _, size in files) or 1
            done = 0
            _report(progress, 0, total, "")
            for path, rel, size in files:
                if cancelled is not None and cancelled():
                    raise CheckpointCancelled()
                stored = path.suffix.lower() in _STORED_SUFFIXES
                zf.write(path, arcname=str(rel),
                         compress_type=(zipfile.ZIP_STORED if stored
                                        else zipfile.ZIP_DEFLATED))
                done += size
                _report(progress, done, total, str(rel))
        tmp_zip.replace(zip_path)
    except Exception:
        try:
            tmp_zip.unlink()
        except OSError:
            pass
        raise

    # Also drop a sidecar metadata file alongside the zip — makes
    # ``list_checkpoints`` cheap (no need to crack open every zip
    # to read its embedded meta).
    sidecar = cp_dir / f"_meta_{cp_id}.json"
    sidecar_payload = dict(meta)
    sidecar_payload["zip_filename"] = fname
    sidecar.write_text(json.dumps(sidecar_payload, indent=2))

    return CheckpointInfo(
        id=cp_id,
        name=meta["name"],
        description=meta["description"],
        created_at=created_at,
        zip_path=str(zip_path),
        size_bytes=zip_path.stat().st_size,
        project_basename=project_dir.name,
        raw=meta)


def list_checkpoints(project_dir: Path) -> List[CheckpointInfo]:
    """Return every checkpoint in the project, newest first.

    Reads sidecar metadata files when present; falls back to
    cracking open the zip for its embedded meta when a sidecar is
    missing (zips imported from another machine, or where the
    sidecar was deleted). Returns ``[]`` for projects that have
    never used the checkpoint feature — no directory is created
    just for listing.
    """
    project_dir = Path(project_dir)
    cp_dir = _checkpoints_dir(project_dir, create=False)
    if not cp_dir.exists():
        return []
    out: List[CheckpointInfo] = []
    seen_zips = set()
    # Pass 1 — sidecar metadata (cheap, no zip cracking).
    for sidecar in cp_dir.glob("_meta_*.json"):
        try:
            meta = json.loads(sidecar.read_text())
            zip_name = meta.get("zip_filename")
            if not zip_name:
                continue
            zp = cp_dir / zip_name
            if not zp.exists():
                continue
            seen_zips.add(zp.name)
            out.append(CheckpointInfo(
                id=meta.get("id", sidecar.stem.replace("_meta_", "")),
                name=meta.get("name", zp.stem),
                description=meta.get("description", ""),
                created_at=meta.get("created_at", ""),
                zip_path=str(zp),
                size_bytes=zp.stat().st_size,
                project_basename=meta.get("project_basename", ""),
                raw=meta))
        except Exception:
            continue
    # Pass 2 — zips without a sidecar. Crack open and read embedded
    # meta. Slower but covers imports / sidecar loss.
    for zp in cp_dir.glob("*.zip"):
        if zp.name in seen_zips:
            continue
        info = _read_checkpoint_meta_from_zip(zp)
        if info is not None:
            out.append(info)
    out.sort(key=lambda c: c.created_at, reverse=True)
    return out


def _read_checkpoint_meta_from_zip(
        zp: Path) -> Optional[CheckpointInfo]:
    """Pull metadata out of a checkpoint zip's embedded
    ``_checkpoint_meta.json``. Falls back to filename-derived
    fields when the meta file is missing (legacy archives or
    plain zips imported from elsewhere)."""
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            try:
                with zf.open(META_FILENAME_IN_ZIP) as f:
                    meta = json.loads(f.read().decode("utf-8"))
            except KeyError:
                meta = {}
    except (zipfile.BadZipFile, OSError):
        return None
    created = meta.get("created_at") or datetime.fromtimestamp(
        zp.stat().st_mtime).isoformat(timespec="seconds")
    return CheckpointInfo(
        id=meta.get("id", zp.stem),
        name=meta.get("name", zp.stem),
        description=meta.get("description", ""),
        created_at=created,
        zip_path=str(zp),
        size_bytes=zp.stat().st_size,
        project_basename=meta.get("project_basename", ""),
        raw=meta)


class RestoreIncomplete(RuntimeError):
    """A restore failed and putting the project back failed too. The
    message says what is where; ``unchanged`` is False. (Every other
    failure of ``restore_checkpoint`` leaves the project unchanged.)"""
    unchanged = False


_STAGE_PREFIX = ".restore-"
_ASIDE_PREFIX = ".before-restore-"


def _swap_in(project_dir: Path, zip_path: Path, keep_video_studio: bool,
             progress=None) -> None:
    """Unpack ``zip_path`` beside ``project_dir``, then swap it in (D.14)."""
    cp_dir = _checkpoints_dir(project_dir, create=True)
    tag = uuid.uuid4().hex[:8]
    stage = cp_dir / f"{_STAGE_PREFIX}{tag}"
    aside = cp_dir / f"{_ASIDE_PREFIX}{tag}"
    stage.mkdir()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total = sum(m.file_size for m in members) or 1
            done = 0
            _report(progress, 0, total, "Restoring")
            for member in members:
                zf.extract(member, stage)
                done += member.file_size
                _report(progress, done, total, f"Restoring: {member.filename}")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)  # only what was unpacked
        raise

    def keeps(entry: Path) -> bool:
        return entry.name == CHECKPOINTS_DIRNAME or (
            keep_video_studio and entry.is_dir()
            and entry.name.endswith(VIDEO_STUDIO_SUFFIX))

    current = [e for e in project_dir.iterdir() if not keeps(e)]
    incoming = [e for e in stage.iterdir() if e.name != CHECKPOINTS_DIRNAME]
    moved_aside: List[Path] = []
    moved_in: List[str] = []
    try:
        aside.mkdir()
        for e in current:
            _rename(e, aside / e.name)
            moved_aside.append(e)
        for e in incoming:
            if (project_dir / e.name).exists():       # a kept Video Studio folder: never written over
                continue
            _rename(e, project_dir / e.name)
            moved_in.append(e.name)
    except BaseException as first:
        problems = []
        for name in reversed(moved_in):               # take the unpacked entries out again
            try:
                _rename(project_dir / name, stage / name)
            except OSError as e:
                problems.append(f"{project_dir / name} (from the checkpoint): {e}")
        for e in reversed(moved_aside):               # and put the project's own back
            try:
                _rename(aside / e.name, e)
            except OSError as err:
                problems.append(f"{e.name} is still in {aside}: {err}")
        if problems:
            raise RestoreIncomplete(
                f"The restore failed ({first}) and part of the project could not be put "
                f"back. The project's own files that were not put back are in {aside}; "
                f"the unpacked checkpoint is in {stage}. Details: " + "; ".join(problems)
            ) from first
        shutil.rmtree(stage, ignore_errors=True)
        try:
            aside.rmdir()
        except OSError:
            pass
        raise
    # Restored. The old state is in the "Before restore" checkpoint (when
    # one was made); the set-aside copy goes, as the old wipe did.
    shutil.rmtree(aside, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)


# Every rename in a restore's swap goes through here, so a test can make
# one fail part-way.
_rename = os.rename


def restore_checkpoint(project_dir: Path,
                       checkpoint: CheckpointInfo,
                       *,
                       backup_current: bool = True,
                       progress=None) -> Optional[CheckpointInfo]:
    """Restore the project to the state captured in ``checkpoint``.

    Steps (each guarded so a partial failure leaves the project
    intact):

      1. **Optional pre-restore checkpoint**: take a fresh
         "Before restore (auto)" checkpoint of the current state
         so the user can roll back if the restore was a mistake.
         On by default; pass ``backup_current=False`` to skip.
      2. **Unpack the archive beside the project** (into a hidden
         folder inside ``_checkpoints/``, so on the same disk). If
         that fails (a damaged archive, a full disk) the project has
         not been touched (D.14; it used to be emptied first).
      3. **Swap**: the project's current entries (everything except
         ``_checkpoints/``, and a Video Studio folder the checkpoint
         does not hold) are renamed aside, the unpacked ones renamed
         in. If a rename fails, every entry is put back and the
         project is as it was. Only then is the set-aside copy
         removed. The embedded ``_checkpoint_meta.json`` is restored
         too — harmless and self-describing.

    Returns the auto-checkpoint :class:`CheckpointInfo` if one was
    created, else None. Raises on any failure; the project is then
    unchanged, except in the one case :class:`RestoreIncomplete`
    describes (putting an entry back failed too), whose message says
    exactly where each part is.

    Optional ``progress(done, total, label)`` reports the safety
    checkpoint and then the extraction. A restore cannot be cancelled:
    stopping halfway would leave the project half-restored.

    The project becomes an exact copy of the checkpoint, with one
    exception: when the checkpoint holds no Video Studio files (a
    *writing only* checkpoint, or one made before the Video Studio
    existed), the current Video Studio folders are left untouched, and
    the safety checkpoint leaves them out too.
    """
    project_dir = Path(project_dir)
    zip_path = Path(checkpoint.zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(
            f"Checkpoint archive missing: {zip_path}")
    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project directory missing: {project_dir}")

    keep_video_studio = not contains_video_studio(checkpoint)

    auto_info: Optional[CheckpointInfo] = None
    if backup_current:
        try:
            auto_info = create_checkpoint(
                project_dir,
                name=f"Before restore ({checkpoint.name})",
                description=(
                    f"Auto-created before restoring checkpoint "
                    f"'{checkpoint.name}' "
                    f"({checkpoint.created_at})"),
                include_video_studio=not keep_video_studio,
                progress=(None if progress is None else
                          lambda d, t, label: progress(
                              d, t, f"Saving the current state first: {label}")))
        except Exception as e:
            # If we can't take the safety checkpoint, refuse to
            # restore — destructive op without an undo path is
            # worse than not restoring.
            raise RuntimeError(
                f"Couldn't create safety checkpoint before "
                f"restore: {e}. Restore aborted.") from e

    # D.14: unpack beside the project first, then swap. A failure while
    # unpacking leaves the project exactly as it was; a failure during the
    # swap puts every entry back where it was (``_swap_in``).
    _swap_in(project_dir, zip_path, keep_video_studio, progress)
    return auto_info


def delete_checkpoint(checkpoint: CheckpointInfo) -> bool:
    """Delete a checkpoint zip + its sidecar metadata file.

    Returns True if at least the zip was removed. Sidecar removal
    is best-effort (it's a tiny json file; orphaned ones are
    harmless and ignored on the next ``list_checkpoints`` pass).
    """
    zp = Path(checkpoint.zip_path)
    cp_dir = zp.parent
    sidecar = cp_dir / f"_meta_{checkpoint.id}.json"
    removed = False
    try:
        zp.unlink()
        removed = True
    except FileNotFoundError:
        removed = True  # already gone
    except Exception:
        return False
    try:
        sidecar.unlink(missing_ok=True)
    except Exception:
        pass
    return removed
