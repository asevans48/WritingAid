"""Warn before saving a project into a folder that holds another project.

Each project keeps its chapter folders and side files (state file,
``<project>.ratings.json``, ``<project>.submission.json``, ...) beside its
project file. Two projects saved in one folder could mix up their chapter
folders where chapter ids match (found in piece R.7).

So when a project gets a *new* location (Save As, or the first save of a
new project) and the chosen folder already holds a different project file,
the writer is asked once:

* save into a new subfolder named after the project (recommended, default),
* save there anyway, or
* cancel.

Ordinary saves to the project's existing location never come here.

Nothing is overwritten (rule 15): the subfolder is always a new folder; if
the name is taken, a number is added.

The finding functions are pure and need no Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

PROJECT_SUFFIX = ".writerproj"
# An older project file name seen in a writer's folder.
_LEGACY_SUFFIX = "writerproj.json"

SUBFOLDER = "subfolder"
HERE = "here"
CANCEL = "cancel"


def is_project_file(path: Path) -> bool:
    """True if ``path`` looks like a project file by its name."""
    name = path.name.lower()
    return name.endswith(PROJECT_SUFFIX) or name.endswith(_LEGACY_SUFFIX)


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def other_project_files(target: str | Path) -> List[Path]:
    """Project files in ``target``'s folder other than ``target`` itself.

    Saving over the same file is not a collision. A missing or unreadable
    folder holds nothing.
    """
    target = Path(target)
    folder = target.parent
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    return [p for p in entries
            if p.is_file() and is_project_file(p)
            and not _same_file(p, target)]


def free_subfolder(folder: str | Path, name: str) -> Path:
    """A path in ``folder`` named ``name`` that does not exist yet.

    If ``name`` is taken (by a file or a folder), adds `` 2``, `` 3``, ...
    """
    folder = Path(folder)
    name = (name or "").strip().strip(".") or "Project"
    for ch in '/\\:':
        name = name.replace(ch, "_")
    candidate = folder / name
    n = 2
    while candidate.exists():
        candidate = folder / f"{name} {n}"
        n += 1
    return candidate


def _project_stem(target: Path) -> str:
    name = target.name
    if name.lower().endswith(PROJECT_SUFFIX):
        return name[: -len(PROJECT_SUFFIX)]
    return target.stem


def make_subfolder_target(target: str | Path) -> Path:
    """Create a new subfolder beside ``target`` and return the project file
    path inside it. Never reuses an existing folder."""
    target = Path(target)
    stem = _project_stem(target)
    while True:
        sub = free_subfolder(target.parent, stem)
        try:
            sub.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue  # taken between the check and now; try the next number
        return sub / target.name


def ask_where(parent, target: Path, others: List[Path],
              subfolder_name: str) -> str:
    """Ask the one question. Returns SUBFOLDER, HERE or CANCEL."""
    from PyQt6.QtWidgets import QMessageBox

    names = ", ".join(p.name for p in others[:3])
    if len(others) > 3:
        names += f" and {len(others) - 3} more"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Another project is in this folder")
    box.setText("This folder already holds another project.")
    box.setInformativeText(
        f"Found: {names}\n\n"
        "Two projects in one folder can mix up their chapter folders. "
        f"Saving into a new folder, “{subfolder_name}”, keeps "
        "them apart.")
    sub_btn = box.addButton("Save in New Folder",
                            QMessageBox.ButtonRole.AcceptRole)
    here_btn = box.addButton("Save Here Anyway",
                             QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(sub_btn)
    box.setEscapeButton(cancel_btn)
    box.exec()
    clicked = box.clickedButton()
    if clicked is sub_btn:
        return SUBFOLDER
    if clicked is here_btn:
        return HERE
    return CANCEL


def choose_save_path(parent, file_path: str,
                     ask: Optional[Callable[..., str]] = None) -> Optional[str]:
    """The path to save a project at its new location, or None to cancel.

    Asks only when the chosen folder holds a different project file.
    """
    if not file_path:
        return None
    target = Path(file_path)
    others = other_project_files(target)
    if not others:
        return file_path
    stem = _project_stem(target)
    preview = free_subfolder(target.parent, stem).name
    answer = (ask or ask_where)(parent, target, others, preview)
    if answer == HERE:
        return file_path
    if answer == SUBFOLDER:
        try:
            return str(make_subfolder_target(target))
        except OSError as e:
            try:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    parent, "Could Not Make Folder",
                    f"Could not make a new folder:\n{e}\n\nNothing was saved.")
            except Exception:
                pass
            return None
    return None
