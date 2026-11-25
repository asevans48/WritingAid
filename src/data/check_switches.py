"""The ✓ Checks ▾ switches a project remembers (P.2a, decided 24 Nov 2026).

Remembered per project, in the project's ``<stem>.companion_state.json``
(R.7) under the key ``"checks"``::

    "checks": {
      "style_kinds": ["adverb", "cliche", ...],   # Style checks ▸ ticked kinds
      "on": {"spell": true, "grammar": true,     # Spelling / Grammar /
             "overuse": true, "style": false},    # Overused words / Style
      "project_created": "2026-11-25T09:12:03"    # for an unsaved project
    }

Not remembered (they are about how and when checks run, not which ones a
book uses): Show highlights (a quick hide, Ctrl+Shift+H), Re-check as I
type, Mode and Focus.

Defaults while a project has nothing stored:

* a project created before this change keeps exactly what it had
  (``DEFAULT_KINDS``, Style highlighting off);
* a **new** project, created after it, also has Pronouns and Acronyms
  ticked. "New" is read from the project's own ``created_at``, which every
  project file has carried since the first version, so it survives saving,
  reopening and copying the file. A saved project whose ``created_at`` is
  later than its file's last change cannot be genuine (the date was filled
  in at load), so it counts as existing.

Only keys are added; kinds a newer app stored that this one does not know
are kept on save. Opening a project never writes. No Qt.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Set, Tuple

from src.data import companion_state
from src.utils.style_checks import DEFAULT_KINDS, KINDS

KEY = "checks"
SWITCHES = ("spell", "grammar", "overuse", "style")
DEFAULT_ON: Dict[str, bool] = {"spell": True, "grammar": True, "overuse": True,
                               "style": False}
NEW_PROJECT_KINDS = frozenset({"pronoun", "acronym"})
# When this change went in: projects created from now on are "new".
CUTOFF = datetime(2026, 11, 24, 22, 55)


def _created(project: Any) -> datetime | None:
    created = getattr(project, "created_at", None)
    if not isinstance(created, datetime):
        return None
    if created.tzinfo is not None:
        created = created.astimezone().replace(tzinfo=None)
    return created


def is_new_project(project: Any) -> bool:
    """Created after this change (see the module note)."""
    created = _created(project)
    if created is None or created < CUTOFF:
        return False
    path = getattr(project, "project_path", "") or ""
    if path:
        try:
            if created.timestamp() > Path(path).stat().st_mtime + 2:
                return False                      # date filled in at load
        except OSError:
            pass
    return True


# Decision 3 (the writer, 24 November 2026): "style checks should meet 4/5;
# spelling and overused should stay on." A new project ticks only the style
# checks that meet four in five on the benchmark (check_scores.md, 23 Nov;
# Pronouns and Acronyms from P.2a's marked set), plus the writer's own style
# sheet, which is not a guess. Spelling, Grammar and Overused words stay on
# (``DEFAULT_ON``). Rerun scripts/score_checks.py and update this set when a
# check improves (P.5). Existing projects keep today's ticks (rule 11).
MEETS_TARGET = frozenset({"intensifier", "wordy", "hard_sentence", "pronoun", "acronym",
                          "preference"})


def default_kinds(project: Any) -> Set[str]:
    if is_new_project(project):
        return set(MEETS_TARGET)
    return set(DEFAULT_KINDS)


def _stored(project: Any) -> Dict[str, Any]:
    if project is None:
        return {}
    entry = companion_state.load(project).get(KEY)
    if isinstance(entry, dict) and entry:
        return entry
    # Ticked before the first save: kept under the unsaved project's file.
    if getattr(project, "project_path", "") and is_new_project(project):
        unsaved = SimpleNamespace(name=getattr(project, "name", ""), project_path="")
        entry = companion_state.load(unsaved).get(KEY)
        created = _created(project)
        if (isinstance(entry, dict) and created is not None
                and entry.get("project_created") == created.isoformat(timespec="seconds")):
            return entry
    return {}


def resolve(project: Any) -> Tuple[Set[str], Dict[str, bool]]:
    """The ticked style kinds and the four check switches for ``project``."""
    entry = _stored(project)
    kinds = default_kinds(project)
    stored_kinds = entry.get("style_kinds")
    if isinstance(stored_kinds, list):
        kinds = {k for k in stored_kinds if k in KINDS}
    on = dict(DEFAULT_ON)
    stored_on = entry.get("on")
    if isinstance(stored_on, dict):
        on.update({k: bool(v) for k, v in stored_on.items() if k in DEFAULT_ON})
    return kinds, on


def remember(project: Any, kinds: Set[str], on: Dict[str, bool]) -> None:
    """Store the switches as they are now (called on every change)."""
    if project is None:
        return
    data = companion_state.load(project)
    entry = data.get(KEY, {})
    if not isinstance(entry, dict):
        return                       # not ours to overwrite (a newer app's)
    old_kinds = entry.get("style_kinds")
    unknown = {k for k in old_kinds if k not in KINDS} if isinstance(old_kinds, list) else set()
    entry["style_kinds"] = sorted({k for k in kinds if k in KINDS} | unknown)
    old_on = entry.get("on") if isinstance(entry.get("on"), dict) else {}
    entry["on"] = {**old_on, **{k: bool(v) for k, v in on.items() if k in DEFAULT_ON}}
    created = _created(project)
    if created is not None:
        entry["project_created"] = created.isoformat(timespec="seconds")
    data[KEY] = entry
    companion_state.save(project, data)
