"""The writing habit (piece H.1): a record of each writing day, the
streak, the daily and weekly goals, and the nudge to move on.

**The habit belongs to the writer, not to a project.** One file,
``~/.creativeos/writing_habit.json``, holds every day, split by project, so
the streak and the counts are shared across projects and either view is
possible::

    {"format_version": 1,
     "days": {"2026-11-24": {"<project key>": {
         "name": "Teller County", "path": "/…/Teller County.writerproj",
         "added": 640, "cut": 120, "moved": 0, "minutes": 35,
         "chapters": {"<chapter id>": {"title": "Chapter 3",
                                       "added": 640, "cut": 120, "moved": 0}}}}},
     "folded": {"<project key>": "2026-11-24"},
     "last": {"<project key>": {"chapter": "<chapter id>", "at": "…"}}}

* **A writing day** is a calendar day (local time, midnight to midnight)
  with any words added or cut in a chapter. Cutting and revising count;
  meeting a goal is not needed. A day with only a paste or an import
  (moved text) does not count (the writer, 24 November 2026); it is still
  recorded and shown.
* **Never trimmed.** A day is a few dozen bytes.
* **Days from before H.1** come from each project's companion ``sessions``
  (growth only, all they hold), folded in once per project the first time
  it is opened (``fold_in_sessions``). The sessions are left as they are and
  still written, so an older app still shows "words today".
* **Goals** are stored in ``creativeos_config``: ``daily_word_goal`` (the
  key the Companion already read) and ``weekly_word_goal``; ``habit_nudge``
  holds the nudge switch and the date it last asked. No goal: 0.
* **The week starts on Monday.**

Written safely through ``safe_store``; a missing or unreadable file means
an empty record (an unreadable one is set aside, never saved over). No Qt.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.data import safe_store

FILE_NAME = "writing_habit.json"
FORMAT_VERSION = 1
LARGE_PASTE_WORDS = 300          # a block this large arriving at once is moved text
NUDGE_DAYS = 7                   # writing days looked at by the nudge
NUDGE_MIN_NEW = 200              # growth below this over those days: only revising
KEY_DAILY = "daily_word_goal"
KEY_WEEKLY = "weekly_word_goal"
KEY_NUDGE = "habit_nudge"

Days = Dict[str, Dict[str, Dict[str, Any]]]     # date → project key → entry


# ── The file ───────────────────────────────────────────────────────────

def habit_path() -> Path:
    return Path.home() / ".creativeos" / FILE_NAME


def _empty() -> Dict[str, Any]:
    return {"format_version": FORMAT_VERSION, "days": {}, "folded": {}, "last": {}}


def load() -> Dict[str, Any]:
    try:
        data = safe_store.load(habit_path(), _empty(), expect=dict)
    except Exception as e:                       # noqa: BLE001
        print(f"[habit] could not load the record: {e}")
        data = _empty()
    data.setdefault("format_version", FORMAT_VERSION)
    for key in ("days", "folded", "last"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def save(data: Dict[str, Any]) -> bool:
    try:
        return safe_store.save(habit_path(), data, indent=1)
    except Exception as e:                       # noqa: BLE001
        print(f"[habit] could not save the record: {e}")
        return False


def project_key(project: Any) -> str:
    """The project's file path, or its name for a project not yet saved."""
    path = getattr(project, "project_path", "") or ""
    return str(path) if path else f"unsaved:{getattr(project, 'name', '') or 'untitled'}"


def _entry(data: Dict[str, Any], day: str, project: Any) -> Dict[str, Any]:
    entry = data["days"].setdefault(day, {}).setdefault(project_key(project), {})
    entry["name"] = getattr(project, "name", "") or entry.get("name", "")
    entry["path"] = getattr(project, "project_path", "") or entry.get("path", "")
    for k in ("added", "cut", "moved", "minutes"):
        entry.setdefault(k, 0)
    entry.setdefault("chapters", {})
    return entry


# ── Counting words ─────────────────────────────────────────────────────

_WORD = re.compile(r"\S+")


def word_changes(before: str, after: str) -> Tuple[int, int]:
    """(words added, words cut) between two versions of a chapter, from a
    diff of the word lists, so a cut paragraph and a new one don't cancel
    out. Words that only moved within the text count as cut and added."""
    a, b = _WORD.findall(before or ""), _WORD.findall(after or "")
    start = 0
    while start < len(a) and start < len(b) and a[start] == b[start]:
        start += 1
    end_a, end_b = len(a), len(b)
    while end_a > start and end_b > start and a[end_a - 1] == b[end_b - 1]:
        end_a -= 1
        end_b -= 1
    a, b = a[start:end_a], b[start:end_b]
    if not a or not b:
        return len(b), len(a)
    if len(a) * len(b) > 25_000_000:             # very large rewrites: a word count diff
        ca, cb = Counter(a), Counter(b)
        return sum((cb - ca).values()), sum((ca - cb).values())
    added = cut = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            cut += i2 - i1
        if op in ("replace", "insert"):
            added += j2 - j1
    return added, cut


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


# ── Recording ──────────────────────────────────────────────────────────

def record(project: Any, chapter_id: str, chapter_title: str, *, added: int = 0, cut: int = 0,
           moved: int = 0, minutes: Optional[Dict[str, int]] = None,
           day: Optional[date] = None) -> bool:
    """Add one save's changes to the record. ``minutes`` is {date: minutes
    typed}; when it spans more than one day, the words are shared out by the
    minutes typed on each, so writing after midnight counts on the new day.
    Returns True when something was recorded."""
    minutes = {d: m for d, m in (minutes or {}).items() if m > 0}
    if not (added or cut or moved or minutes) or project is None:
        return False
    today = (day or date.today()).isoformat()
    shares = _shares(minutes, today)
    data = load()
    for when, share in shares.items():
        entry = _entry(data, when, project)
        ch = entry["chapters"].setdefault(chapter_id or "?", {"title": "", "added": 0,
                                                               "cut": 0, "moved": 0})
        ch["title"] = chapter_title or ch.get("title", "")
        for k, n in (("added", added), ("cut", cut), ("moved", moved)):
            part = round(n * share)
            entry[k] = entry.get(k, 0) + part
            ch[k] = ch.get(k, 0) + part
    for when, m in minutes.items():
        entry = _entry(data, when, project)
        entry["minutes"] = entry.get("minutes", 0) + m
    data["last"][project_key(project)] = {"chapter": chapter_id or "",
                                          "at": datetime.now().isoformat(timespec="minutes")}
    return save(data)


def _shares(minutes: Dict[str, int], today: str) -> Dict[str, float]:
    total = sum(minutes.values())
    if total <= 0 or set(minutes) <= {today}:
        return {today: 1.0}
    return {d: m / total for d, m in minutes.items()}


def fold_in_sessions(project: Any, sessions: Dict[str, Dict[str, Any]],
                     titles: Optional[Dict[str, str]] = None) -> int:
    """Fold a project's companion ``sessions`` (growth per session) into the
    record, once per project. Returns the number of days folded in."""
    if project is None:
        return 0
    data = load()
    key = project_key(project)
    if key in data["folded"]:
        return 0
    titles = titles or {}
    days = set()
    for session_key, s in (sessions or {}).items():
        try:
            when, words = str(s.get("date", "")), int(s.get("added", 0) or 0)
            date.fromisoformat(when)
        except Exception:
            continue
        if words <= 0:
            continue
        chapter_id = str(session_key).split("@", 1)[0]
        entry = _entry(data, when, project)
        ch = entry["chapters"].setdefault(chapter_id, {"title": titles.get(chapter_id, ""),
                                                       "added": 0, "cut": 0, "moved": 0})
        entry["added"] += words
        ch["added"] = ch.get("added", 0) + words
        days.add(when)
    data["folded"][key] = date.today().isoformat()
    save(data)
    return len(days)


# ── Days, weeks, streaks (pure) ────────────────────────────────────────

def day_totals(day: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, int]:
    out = {"added": 0, "cut": 0, "moved": 0, "minutes": 0}
    for entry in (day or {}).values():
        for k in out:
            out[k] += int(entry.get(k, 0) or 0)
    return out


def is_writing_day(day: Optional[Dict[str, Dict[str, Any]]]) -> bool:
    t = day_totals(day)
    return bool(t["added"] or t["cut"])        # a paste or import alone is not writing


def writing_dates(days: Days) -> List[date]:
    out = []
    for when, day in days.items():
        try:
            d = date.fromisoformat(when)
        except ValueError:
            continue
        if is_writing_day(day):
            out.append(d)
    return sorted(out)


def streak(days: Days, today: date) -> int:
    """Consecutive calendar days with writing, ending today, or yesterday
    while today has none yet (today is not over)."""
    written = set(writing_dates(days))
    d = today if today in written else today - timedelta(days=1)
    n = 0
    while d in written:
        n += 1
        d -= timedelta(days=1)
    return n


def longest_streak(days: Days) -> int:
    best = run = 0
    prev = None
    for d in writing_dates(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def days_this_month(days: Days, today: date) -> int:
    return sum(1 for d in writing_dates(days) if (d.year, d.month) == (today.year, today.month))


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())          # Monday


def words_on(days: Days, d: date) -> int:
    return day_totals(days.get(d.isoformat()))["added"]


def week_words(days: Days, d: date) -> int:
    monday = week_start(d)
    return sum(words_on(days, monday + timedelta(days=i)) for i in range(7))


def best_week(days: Days) -> Tuple[Optional[date], int]:
    weeks: Dict[date, int] = {}
    for when, day in days.items():
        try:
            d = date.fromisoformat(when)
        except ValueError:
            continue
        weeks[week_start(d)] = weeks.get(week_start(d), 0) + day_totals(day)["added"]
    if not weeks:
        return None, 0
    monday = max(weeks, key=lambda m: (weeks[m], m))
    return monday, weeks[monday]


def goal_progress(days: Days, today: date, daily: int, weekly: int) -> Dict[str, Any]:
    """Words toward each goal, measured separately."""
    t, w = words_on(days, today), week_words(days, today)
    return {"today": t, "week": w, "daily": daily, "weekly": weekly,
            "daily_met": bool(daily) and t >= daily, "weekly_met": bool(weekly) and w >= weekly}


def progress_line(days: Days, today: date, daily: int, weekly: int) -> Tuple[str, str]:
    """(the Companion's line, the banner's short form):
    "Today: 640 of 1,000 words · this week 3,200 of 5,000 · 5 days in a row"."""
    p = goal_progress(days, today, daily, weekly)
    s = streak(days, today)
    parts = [f"Today: {p['today']:,} of {daily:,} words" if daily
             else f"Today: {p['today']:,} words",
             f"this week {p['week']:,} of {weekly:,}" if weekly else f"this week {p['week']:,}"]
    if s:
        parts.append(f"{s} day{'s' if s != 1 else ''} in a row")
    head = (f"{p['today']:,}/{daily:,} words today" if daily
            else f"{p['week']:,}/{weekly:,} words this week")
    return " · ".join(parts), head


def crossed(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """The goal-met notes for goals met by this save (not before it)."""
    notes = []
    if after["daily_met"] and not before["daily_met"]:
        notes.append(f"Daily goal met: {after['daily']:,} words")
    if after["weekly_met"] and not before["weekly_met"]:
        notes.append(f"Weekly goal met: {after['weekly']:,} words")
    return notes


def worked_on(day: Optional[Dict[str, Dict[str, Any]]]) -> List[Tuple[str, List[str]]]:
    """[(project name, [chapter titles])] for one day."""
    out = []
    for key, entry in sorted((day or {}).items(), key=lambda kv: kv[1].get("name", "")):
        name = entry.get("name") or Path(entry.get("path") or key).stem or "Untitled"
        titles = [c.get("title") or "an untitled chapter"
                  for c in (entry.get("chapters") or {}).values()
                  if c.get("added") or c.get("cut") or c.get("moved")]
        out.append((name, titles))
    return out


# ── The nudge (pure) ───────────────────────────────────────────────────

def revising_only(days: Days, project: str, since: Optional[date] = None,
                  window: int = NUDGE_DAYS, min_new: int = NUDGE_MIN_NEW) -> Optional[Dict[str, int]]:
    """Whether to ask the writer to move on: over this project's last
    ``window`` writing days (after ``since``, the day it last asked) the
    manuscript grew by fewer than ``min_new`` words. Returns the numbers for
    the wording, or None. ``project`` is a ``project_key``."""
    mine = []
    for when, day in days.items():
        entry = (day or {}).get(project)
        if not entry or not (entry.get("added") or entry.get("cut")):
            continue                               # no writing that day (a paste alone)
        try:
            d = date.fromisoformat(when)
        except ValueError:
            continue
        if since is None or d > since:
            mine.append((d, entry))
    if len(mine) < window:
        return None
    recent = [e for _d, e in sorted(mine, key=lambda x: x[0])[-window:]]
    added = sum(int(e.get("added", 0) or 0) for e in recent)
    cut = sum(int(e.get("cut", 0) or 0) for e in recent)
    if added - cut >= min_new:
        return None
    return {"days": window, "added": added, "cut": cut, "growth": added - cut}


def nudge_applies(project: Any, scope: Optional[str]) -> bool:
    """A novel or novella whose draft is not finished: the manuscript is
    the main one (a novel) or a novella sub-project (or one marked a novel),
    and no chapter of it has been given a stage (3.1), since a stage means
    it is being edited and revising is then the job. Anything else, such as
    a sub-work of another kind (a short story), is never nudged."""
    if scope is not None:
        sp = project.get_subproject(scope) if hasattr(project, "get_subproject") else None
        if sp is None or (getattr(sp, "kind", "novella") or "novella") not in ("novella", "novel"):
            return False
    try:
        from src.ai import chapter_stages
        if chapter_stages.stages(project, scope):
            return False
    except Exception:
        return False
    return True


# ── Goals and the nudge switch (creativeos_config) ─────────────────────

def _config():
    from src.config.creativeos_config import get_creativeos_config
    return get_creativeos_config()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def goals() -> Tuple[int, int]:
    """(daily, weekly) word goals; 0 is no goal."""
    try:
        cfg = _config()
        return _int(cfg.get(KEY_DAILY, 0)), _int(cfg.get(KEY_WEEKLY, 0))
    except Exception:
        return 0, 0


def set_goals(daily: int, weekly: int) -> None:
    """Store the goals. Only keys that change are written, so opening and
    closing the goal settings adds nothing to an install without goals."""
    cfg = _config()
    changes = {}
    if _int(cfg.get(KEY_DAILY, 0)) != _int(daily):
        changes[KEY_DAILY] = _int(daily)
    if _int(cfg.get(KEY_WEEKLY, 0)) != _int(weekly):
        changes[KEY_WEEKLY] = _int(weekly)
    if changes:
        cfg.update(**changes)


def nudge_state() -> Dict[str, Any]:
    try:
        raw = _config().get(KEY_NUDGE, {}) or {}
    except Exception:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {"on": bool(raw.get("on", True)), "last_asked": str(raw.get("last_asked", "") or "")}


def set_nudge(on: Optional[bool] = None, asked: Optional[date] = None) -> None:
    state = nudge_state()
    new = dict(state)
    if on is not None:
        new["on"] = bool(on)
    if asked is not None:
        new["last_asked"] = asked.isoformat()
    if new != state:
        cfg = _config()
        stored = cfg.get(KEY_NUDGE, {}) or {}
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored.update(new)                     # keys this version doesn't know are kept
        cfg.update(**{KEY_NUDGE: stored})


def last_asked() -> Optional[date]:
    try:
        return date.fromisoformat(nudge_state()["last_asked"])
    except ValueError:
        return None


def last_chapter(data: Dict[str, Any], project: Any) -> str:
    return str((data.get("last", {}).get(project_key(project)) or {}).get("chapter", ""))


def recent_dates(today: date, weeks: int = 12) -> List[date]:
    """Every date in the last ``weeks`` weeks, Monday first, ending this Sunday."""
    first = week_start(today) - timedelta(weeks=weeks - 1)
    return [first + timedelta(days=i) for i in range(weeks * 7)]


def shade_level(words: int, levels: Iterable[int] = (1, 250, 750, 1500)) -> int:
    """0 (none) to 4 for a day's words added and cut."""
    return sum(1 for t in levels if words >= t)
