"""Which of a chapter's ``backup_*.md`` copies to keep (piece 0.4).

Kept:

* the three most recent, as before;
* the first backup of each day, for the last fourteen days;
* when the text being saved is empty, the newest backup that still holds
  text, however old, so blanking a chapter can always be undone.

Everything else is pruned. File names and folders are unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

KEEP_RECENT = 3
KEEP_DAYS = 14

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
