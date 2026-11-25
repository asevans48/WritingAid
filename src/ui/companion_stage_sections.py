"""The Companion opens what fits the chapter's stage (piece D.7, part 3).

The Companion has seven sections. With every one open there is a lot to
scroll past, and most are not about what the writer is doing at this
stage. Now:

* **Always open:** "Where you left off" and "Next fixes".
* **Opened by the chapter's stage** (``chapter_stages``); the others start
  closed, each one click away with its count in its header:

  | Stage | Also open |
  |---|---|
  | Structure, Scene | Reader's eye, Story memory, Notes as you write |
  | Line | Notes as you write, Overly descriptive |
  | Copyedit, Proof | Your style sheet |

* **No stage set:** today's defaults, exactly.
* **The writer's own choice wins.** A section opened or closed by hand
  stays that way (``companion_state.touched_sections``). A project whose
  file already held section states from before this piece counts them all
  as chosen by hand, so nothing the writer set moves.

Nothing new is stored beyond the list of sections set by hand.
"""

from __future__ import annotations

from typing import Any, Iterable, Set

ALWAYS_OPEN = {"left_off", "fixes"}
BY_STAGE = {
    "structure": {"reader", "memory", "notes"},
    "scene": {"reader", "memory", "notes"},
    "line": {"notes", "overdescribed"},
    "copyedit": {"style_sheet"},
    "proof": {"style_sheet"},
}


def stage_for(project: Any, chapter: Any) -> str:
    if project is None or chapter is None:
        return ""
    try:
        from src.ai import chapter_stages as cst
        scope, _ = project.find_chapter_with_scope(chapter.id)
        return cst.stage_of(project, scope, chapter.id)
    except Exception:
        return ""


def closed(project: Any, chapter: Any, keys: Iterable[str]) -> Set[str]:
    """The section keys to show closed."""
    from src.data import companion_state as cs
    keys = list(keys)
    stored = cs.collapsed_sections(project) if project is not None else set(cs.DEFAULT_COLLAPSED)
    stage = stage_for(project, chapter)
    if stage not in BY_STAGE:
        return stored
    touched = cs.touched_sections(project)
    if cs.ALL_TOUCHED in touched:
        return stored
    wanted = ALWAYS_OPEN | BY_STAGE[stage]
    return {k for k in keys if (k in stored if k in touched else k not in wanted)}
