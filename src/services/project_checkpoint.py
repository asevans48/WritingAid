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
                      description: str = "") -> CheckpointInfo:
    """Snapshot the entire project directory into a zip checkpoint.

    The archive includes everything under ``project_dir`` except
    the ``_checkpoints/`` folder itself (preventing recursion) and
    any obvious noise files (``.DS_Store``, ``__pycache__``,
    ``.tmp`` scratch files, ``.pyc``).

    Returns a :class:`CheckpointInfo` describing the resulting
    zip. The zip contains a top-level ``_checkpoint_meta.json``
    so it stays self-describing even if separated from this
    project's ``_checkpoints/`` directory.
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
            for path in sorted(project_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(project_dir)
                if _should_skip_path(rel):
                    continue
                zf.write(path, arcname=str(rel))
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


def restore_checkpoint(project_dir: Path,
                       checkpoint: CheckpointInfo,
                       *,
                       backup_current: bool = True) -> Optional[CheckpointInfo]:
    """Restore the project to the state captured in ``checkpoint``.

    Steps (each guarded so a partial failure leaves the project
    intact):

      1. **Optional pre-restore checkpoint**: take a fresh
         "Before restore (auto)" checkpoint of the current state
         so the user can roll back if the restore was a mistake.
         On by default; pass ``backup_current=False`` to skip.
      2. **Wipe project_dir** of everything except the
         ``_checkpoints/`` directory itself (we never delete the
         user's checkpoint history).
      3. **Extract the archive** into ``project_dir``. The
         embedded ``_checkpoint_meta.json`` is also extracted —
         harmless and self-describing.

    Returns the auto-checkpoint :class:`CheckpointInfo` if one was
    created, else None. Raises on any failure during extraction
    (the caller should surface the error; the auto-checkpoint
    means the user hasn't lost data).
    """
    project_dir = Path(project_dir)
    zip_path = Path(checkpoint.zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(
            f"Checkpoint archive missing: {zip_path}")
    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project directory missing: {project_dir}")

    auto_info: Optional[CheckpointInfo] = None
    if backup_current:
        try:
            auto_info = create_checkpoint(
                project_dir,
                name=f"Before restore ({checkpoint.name})",
                description=(
                    f"Auto-created before restoring checkpoint "
                    f"'{checkpoint.name}' "
                    f"({checkpoint.created_at})"))
        except Exception as e:
            # If we can't take the safety checkpoint, refuse to
            # restore — destructive op without an undo path is
            # worse than not restoring.
            raise RuntimeError(
                f"Couldn't create safety checkpoint before "
                f"restore: {e}. Restore aborted.") from e

    # Wipe project contents EXCEPT _checkpoints/. We rebuild
    # from the zip in the next step.
    cp_dirname = CHECKPOINTS_DIRNAME
    for entry in list(project_dir.iterdir()):
        if entry.name == cp_dirname:
            continue
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except Exception:
            # Continue on best-effort — extraction below will
            # still write what it can. Worst case: leftover
            # files that the next checkpoint will tidy.
            pass

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(project_dir)

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
