"""Image files a Studio editor will delete when it closes (piece D.14).

Removing a scene action, or one of an action's images, used to delete the
image files at once, while the editor was still open. Now the editor
notes them here and they are deleted only when it closes with the change
kept (``finish(kept=True)``), and only if nothing else in the Studio still
names the file (another action, a scene's clips, a slide deck, a chapter
deck…), since the same picture can be used in more than one place. A file
the Studio still uses, or any file when the Studio cannot be read, is
kept. An editor that closes without keeping the change (``kept=False``)
deletes nothing. No Qt here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Tuple


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _strings(v)


def _same(a: str, b: str) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except (OSError, ValueError):
        return a == b


def still_used(path: str, studio: Any) -> bool:
    """Whether anything in ``studio`` (the project's ``VideoStudio``) names
    ``path``, by the same path or the same file name. True when it cannot
    tell (no Studio, or it cannot be read): keeping a file is safe."""
    if studio is None:
        return True
    try:
        data = studio.model_dump()
    except Exception:
        return True
    name = Path(path).name
    for s in _strings(data):
        if s and (s == path or (name and Path(s).name == name) or (
                ("/" in s or "\\" in s) and _same(s, path))):
            return True
    return False


class PendingRemovals:
    """The files an open editor will delete if its change is kept."""

    def __init__(self) -> None:
        self.paths: List[str] = []

    def add(self, *paths: Optional[str]) -> None:
        for p in paths:
            if p and p not in self.paths:
                self.paths.append(p)

    def add_images(self, images: Iterable[Any]) -> None:
        """An action's images (``ActionImage``): each file and its sidecar."""
        for img in images or []:
            self.add(getattr(img, "file_path", ""), getattr(img, "sidecar_path", ""))

    def finish(self, kept: bool, studio: Any) -> Tuple[List[str], List[str]]:
        """The editor closed. With the change ``kept``, delete each noted
        file nothing else uses; returns (deleted, kept on disk). Never
        raises; called once (the list is emptied)."""
        paths, self.paths = self.paths, []
        removed: List[str] = []
        left: List[str] = []
        if not kept:
            return removed, [p for p in paths if Path(p).exists()]
        for p in paths:
            try:
                f = Path(p)
                if not f.exists():
                    continue
                if still_used(p, studio):
                    left.append(p)
                    continue
                f.unlink()
                removed.append(p)
            except Exception as e:                 # a file that can't go is kept
                print(f"[video studio] could not delete {p}: {e}")
                left.append(p)
        return removed, left
