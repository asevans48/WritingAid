"""The publishing goal: genre, route, and the length that is typical
(piece 1.1).

The goal is always a publishable manuscript. The one thing the writer sets is
the **route**, per manuscript (the main manuscript and each novella):

* ``"agent"``: submission to literary agents (the default);
* ``"self"``: self-publishing.

The route decides how strict the opening-pages check is (1.8), which export
is offered first (9.2) and what the submission package holds (9.3). Length is
**information only**: the manuscript's word count beside what is typical for
its genre, route and kind (novel or novella). It never passes or fails and
never counts toward readiness.

**Where the route is stored:** the project's readiness file,
``readiness.json`` beside the project file (``~/.creativeos/readiness/`` for
a project not yet saved), written safely through ``safe_store``. It is not
stored in the prose profile: an older version of the app would drop a field
added there. With no file, every manuscript uses the default route. Piece
1.2a adds the readiness results to the same file; keys this module does not
know are kept as they are.

Layout (``format_version`` 1)::

    {"format_version": 1,
     "manuscripts": {"main": {"route": "agent"},
                     "<novella id>": {"route": "self"}}}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.data import readiness_state

FORMAT_VERSION = 1
ROUTES: Dict[str, str] = {"agent": "Agent submission", "self": "Self-publishing"}
DEFAULT_ROUTE = "agent"
MAIN = readiness_state.MAIN

# Typical length in words: a rough guide drawn from commonly cited agent and
# self-publishing guidance. Publishers and markets vary; never a target.
TYPICAL_NOVEL: Dict[str, Dict[str, Tuple[int, int]]] = {
    "agent": {
        "literary": (70_000, 100_000), "mystery": (70_000, 90_000),
        "thriller": (80_000, 100_000), "romance": (70_000, 100_000),
        "fantasy": (90_000, 120_000), "scifi": (90_000, 120_000),
        "horror": (80_000, 100_000), "gothic": (80_000, 100_000),
        "western": (60_000, 90_000), "frontier": (60_000, 90_000),
        "adventure": (80_000, 100_000),
    },
    "self": {
        "literary": (60_000, 100_000), "mystery": (60_000, 80_000),
        "thriller": (70_000, 90_000), "romance": (50_000, 80_000),
        "fantasy": (80_000, 120_000), "scifi": (70_000, 100_000),
        "horror": (60_000, 90_000), "gothic": (60_000, 90_000),
        "western": (50_000, 80_000), "frontier": (50_000, 80_000),
        "adventure": (60_000, 90_000),
    },
}
DEFAULT_NOVEL = {"agent": (70_000, 100_000), "self": (60_000, 90_000)}
TYPICAL_NOVELLA = (17_500, 40_000)          # the usual definition of a novella


# ── The readiness file (owned by readiness_state since 1.2b) ───────────

def readiness_path(project: Any) -> Path:
    return readiness_state.readiness_path(project)


def load(project: Any) -> Dict[str, Any]:
    """The readiness file, or an empty one. Missing → empty, quietly;
    unreadable → set aside, the writer told, then empty (safe_store)."""
    return readiness_state.load(project)


def save(project: Any, data: Dict[str, Any]) -> bool:
    return readiness_state.save(project, data)


def scope_key(scope: Optional[str]) -> str:
    """The file's key for a manuscript: "main", or the novella's id."""
    return readiness_state.scope_key(scope)


# ── Route ──────────────────────────────────────────────────────────────

def route_for(project: Any, scope: Optional[str] = None) -> str:
    entry = load(project)["manuscripts"].get(scope_key(scope), {})
    route = entry.get("route") if isinstance(entry, dict) else None
    return route if route in ROUTES else DEFAULT_ROUTE


def set_route(project: Any, scope: Optional[str], route: str) -> bool:
    """Set a manuscript's route. Everything else in the file is kept."""
    if route not in ROUTES:
        raise ValueError(f"unknown route {route!r}")
    return readiness_state.update(
        project, lambda data: readiness_state.manuscript_entry(data, scope).__setitem__("route", route))


# ── The goal ───────────────────────────────────────────────────────────

@dataclass
class PublishingGoal:
    scope: Optional[str]
    manuscript: str                 # its name
    kind: str                       # "novel" or "novella"
    route: str
    route_label: str
    genre: str                      # canonical key, "" when none is known
    genre_label: str
    words: int
    typical: Tuple[int, int]

    @property
    def length_note(self) -> str:
        """One line of information, never a verdict."""
        low, high = self.typical
        what = f"a {self.genre_label.lower()} {self.kind}" if self.genre else f"a {self.kind}"
        route = "sent to agents" if self.route == "agent" else "self-published"
        return (f"{self.words:,} words. Typical for {what} {route}: "
                f"{low:,}–{high:,} (a rough guide).")


def typical_length(genre: str, route: str, kind: str = "novel") -> Tuple[int, int]:
    if kind == "novella":
        return TYPICAL_NOVELLA
    route = route if route in ROUTES else DEFAULT_ROUTE
    return TYPICAL_NOVEL[route].get(genre, DEFAULT_NOVEL[route])


def genre_of(project: Any) -> Tuple[str, str]:
    """(canonical key, display name) from the prose profile's genre, or
    ("", "") when it names no known genre."""
    text = getattr(getattr(project, "prose_profile", None), "genre", "") or ""
    try:
        from src.data.genres import display_name, match_genres
        keys = match_genres(text)
        if keys:
            return keys[0], display_name(keys[0])
    except Exception:
        pass
    return "", ""


def manuscripts(project: Any) -> List[Tuple[Optional[str], str, Any]]:
    """[(scope, name, manuscript)]: the main manuscript first, then each novella."""
    out = []
    try:
        for scope, ms in project.iter_manuscripts():
            out.append((scope, project.scope_label(scope), ms))
    except Exception:
        ms = getattr(project, "manuscript", None)
        if ms is not None:
            out.append((None, getattr(ms, "title", "") or "Main manuscript", ms))
    return out


def publishing_goal(project: Any, scope: Optional[str] = None) -> PublishingGoal:
    """Genre, route and typical length for one manuscript, with defaults
    when nothing is set."""
    name, ms = "Main manuscript", None
    for s, label, m in manuscripts(project):
        if s == scope:
            name, ms = label, m
            break
    kind = "novel"
    if scope is not None:
        sp = project.get_subproject(scope) if hasattr(project, "get_subproject") else None
        kind = "novella" if (getattr(sp, "kind", "novella") or "novella") == "novella" else "novel"
    words = sum(len((getattr(ch, "content", "") or "").split())
                for ch in (getattr(ms, "chapters", None) or []))
    route = route_for(project, scope)
    genre, genre_label = genre_of(project)
    return PublishingGoal(scope=scope, manuscript=name, kind=kind, route=route,
                          route_label=ROUTES[route], genre=genre, genre_label=genre_label,
                          words=words, typical=typical_length(genre, route, kind))
