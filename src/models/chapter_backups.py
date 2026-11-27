"""Which of a chapter's ``backup_*.md`` copies to keep (piece 0.4).

Kept:

* the three most recent, as before;
* the first backup of each day, for the last fourteen days;
* when the text being saved is empty, the newest backup that still holds
  text, however old, so blanking a chapter can always be undone.

Everything else is pruned. File names and folders are unchanged.

**Names (D.12).** A copy is named for the second it was made,
``backup_YYYYMMDD_HHMMSS.md``, as every copy before D.12 was. A second
copy in the same second used to take the same name and write over the
first (rule 15); now it is ``backup_YYYYMMDD_HHMMSS_2.md`` (``_3`` …,
always one more than the highest already there for that second), so no
copy is ever written over (``new_path``). ``parse_name`` reads both forms:
the Nth copy of a second is dated N − 1 microseconds after it, so copies
sort in the order they were made and each has its own time to restore.
An older version of the app lists only the first form; it leaves the
others alone (it never deletes a name it cannot read).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

KEEP_RECENT = 3
KEEP_DAYS = 14

PREFIX = "backup_"
STAMP = "%Y%m%d_%H%M%S"
_NAME = re.compile(r"backup_(\d{8}_\d{6})(?:_(\d+))?")


def parse_name(stem: str) -> Optional[datetime]:
    """The time of a copy from its file name (without ``.md``):
    ``backup_YYYYMMDD_HHMMSS`` or ``backup_YYYYMMDD_HHMMSS_N`` (N ≥ 2).
    None for any other name."""
    m = _NAME.fullmatch(stem)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), STAMP)
    except ValueError:
        return None
    n = int(m.group(2)) if m.group(2) else 1
    if m.group(2) and n < 2:
        return None
    return dt + timedelta(microseconds=n - 1) if n < 1_000_000 else None


def new_path(folder: Path, when: datetime) -> Path:
    """A name for a new copy made at ``when`` that no copy has: the
    second's own name, or ``_N`` one higher than any copy of that second
    already in ``folder``. Never an existing file."""
    stamp = when.strftime(STAMP)
    highest = 0
    for f in folder.glob(f"{PREFIX}{stamp}*.md"):
        m = _NAME.fullmatch(f.stem)
        if m and m.group(1) == stamp:
            highest = max(highest, int(m.group(2)) if m.group(2) else 1)
    n = highest + 1
    while True:
        path = folder / (f"{PREFIX}{stamp}.md" if n == 1 else f"{PREFIX}{stamp}_{n}.md")
        if not path.exists():
            return path
        n += 1


def copy_new(source: Path, folder: Path, when: datetime) -> Path:
    """Copy ``source`` into ``folder`` as a new copy made at ``when``
    (``new_path``), created exclusively: if a file appears at that name
    first, the next free name is used. Returns the copy's path."""
    import shutil
    while True:
        path = new_path(folder, when)
        try:
            with open(source, "rb") as src, open(path, "xb") as out:
                shutil.copyfileobj(src, out)
        except FileExistsError:
            continue
        try:
            shutil.copystat(source, path)
        except OSError:
            pass
        return path


def label(dt: datetime) -> str:
    """How a copy's time is shown (Revert to Saved Copy ▸): to the second,
    and "(2)", "(3)" … for later copies of the same second."""
    text = dt.strftime("%b %d, %Y  %I:%M:%S %p")
    return text + (f" ({dt.microsecond + 1})" if dt.microsecond else "")

Backup = Tuple[datetime, Path]


def to_remove(backups: Sequence[Backup], *, today: Optional[date] = None,
              saving_empty: bool = False,
              has_text: Optional[Callable[[Path], bool]] = None) -> List[Path]:
    """The backup files to delete. ``backups`` may be in any order."""
    newest_first = sorted(backups, key=lambda b: b[0], reverse=True)
    keep = {path for _, path in newest_first[:KEEP_RECENT]}

    today = today or date.today()
    oldest_day = today - timedelta(days=KEEP_DAYS - 1)
    first_of_day = {}
    for dt, path in sorted(newest_first, key=lambda b: b[0]):
        day = dt.date()
        if oldest_day <= day <= today and day not in first_of_day:
            first_of_day[day] = path
    keep.update(first_of_day.values())

    if saving_empty:
        check = has_text or _has_text
        for _, path in newest_first:
            if check(path):
                keep.add(path)
                break

    return [path for _, path in newest_first if path not in keep]


def _has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return True              # unreadable: keep it rather than guess
