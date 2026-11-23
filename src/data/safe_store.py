"""Safe reading and writing for the files the app keeps (piece 0.4).

Two rules every stored file follows:

* **Safe writes.** A file is written to a temporary file in the same folder
  and swapped in, so an interrupted save leaves the old file whole.
* **Unreadable is not empty.** ``load`` tells a *missing* file (start with
  the default, quietly) from one that *exists but cannot be read* (a drive
  hiccup, a half-written file). An unreadable file is renamed aside as
  ``<name>.unreadable-YYYYMMDD_HHMMSS``, the writer is told once, and only
  then does the app start fresh. If it cannot even be renamed, ``save``
  refuses to write over it for the rest of the session.

Every new store in the plan uses ``load`` and ``save``.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

PathLike = Union[str, Path]

_lock = threading.Lock()
_blocked: set = set()            # unreadable files we could not set aside
_told: set = set()               # files the writer has already been told about
_notifier: Optional[Callable[[str], None]] = None
_pending: List[str] = []         # notices raised before a notifier was set


# ── Writing ────────────────────────────────────────────────────────────

def write_text(path: PathLike, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` safely: temporary file, flush to disk,
    then swap in. On any failure the old file is left as it was and the
    error is raised. Keeps the old file's permissions."""
    path = Path(path)
    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass                 # some drives (exFAT) have no permissions
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_if_changed(path: PathLike, text: str, encoding: str = "utf-8") -> bool:
    """Like ``write_text``, but skips the write when the file already holds
    exactly ``text``. Returns True when it wrote."""
    path = Path(path)
    try:
        if path.read_text(encoding=encoding) == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    write_text(path, text, encoding)
    return True


# ── JSON stores ────────────────────────────────────────────────────────

def load(path: PathLike, default: Any = None, *, expect: Optional[type] = None) -> Any:
    """The JSON stored at ``path``.

    * Missing file → a copy of ``default``, quietly.
    * Unreadable file (cannot be read, not valid JSON, or not of type
      ``expect``) → the file is set aside, the writer is told once, and a
      copy of ``default`` is returned.
    """
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if expect is not None and not isinstance(data, expect):
            raise ValueError(f"expected {expect.__name__}, found {type(data).__name__}")
        _blocked.discard(_key(path))
        return data
    except Exception as e:                      # noqa: BLE001 — any failure means unreadable
        _set_aside(path, e)
        return copy.deepcopy(default)


def save(path: PathLike, data: Any, *, indent: Optional[int] = 1) -> bool:
    """Write ``data`` as JSON to ``path`` safely. Returns False (and writes
    nothing) when ``path`` is an unreadable file that could not be set aside,
    or when the write fails."""
    path = Path(path)
    if _key(path) in _blocked and path.exists():
        print(f"[safe_store] not saving over unreadable {path.name}")
        return False
    try:
        write_text(path, json.dumps(data, indent=indent))
        return True
    except Exception as e:                      # noqa: BLE001
        print(f"[safe_store] could not save {path.name}: {e}")
        return False


# ── Telling the writer ─────────────────────────────────────────────────

def set_notifier(fn: Optional[Callable[[str], None]]) -> None:
    """``fn(message)`` is called once per set-aside file. It may be called
    from a background thread. Notices raised earlier are delivered now."""
    global _notifier
    with _lock:
        _notifier = fn
        pending, _pending[:] = list(_pending), []
    for message in pending:
        _deliver(message)


def _set_aside(path: Path, error: Exception) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    aside = path.with_name(f"{path.name}.unreadable-{stamp}")
    n = 1
    while aside.exists():
        aside = path.with_name(f"{path.name}.unreadable-{stamp}-{n}")
        n += 1
    try:
        os.replace(path, aside)
        _blocked.discard(_key(path))
        message = (f"“{path.name}” could not be read ({_short(error)}). It has been kept as "
                   f"“{aside.name}” in the same folder, and the app has started a fresh one.")
    except OSError as move_error:
        _blocked.add(_key(path))
        message = (f"“{path.name}” could not be read ({_short(error)}) and could not be set "
                   f"aside ({_short(move_error)}). The app will not save over it this session.")
    print(f"[safe_store] {message}")
    with _lock:
        if _key(path) in _told:
            return
        _told.add(_key(path))
        if _notifier is None:
            _pending.append(message)
            return
    _deliver(message)


def _deliver(message: str) -> None:
    fn = _notifier
    if fn is None:
        return
    try:
        fn(message)
    except Exception as e:                      # noqa: BLE001 — telling must never break loading
        print(f"[safe_store] notifier failed: {e}")


def _key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _short(error: Exception) -> str:
    text = str(error) or type(error).__name__
    return text if len(text) <= 80 else text[:77] + "…"


def _reset_for_tests() -> None:
    global _notifier
    with _lock:
        _blocked.clear()
        _told.clear()
        _pending.clear()
        _notifier = None
