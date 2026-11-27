"""Is a LanguageTool result that arrives late still safe to apply?

The grammar worker runs on its own thread and hands its results back
through a queued signal, so they can arrive after the editor is gone or
half torn down. Applying them re-highlights paragraphs, and Qt then tells
the editor its text changed, so the editor's own slot runs. If the
editor's Python side has already been cleared (its QTimer and other
helpers deleted while the widget itself is still waiting to be deleted),
that slot raises, and an exception escaping a PyQt6 slot aborts the app.

``stale_reason`` names why a result must be dropped, or returns None when
it can be applied as usual.
"""

from typing import Optional

from PyQt6 import sip
from PyQt6.QtCore import QObject


def _dead(obj) -> bool:
    try:
        return obj is None or sip.isdeleted(obj)
    except TypeError:          # not a sip-wrapped object
        return False


def _has_dead_parts(obj) -> bool:
    """True when a Qt helper kept on ``obj`` (a timer, the highlighter)
    has been deleted while ``obj`` itself is still alive."""
    try:
        parts = vars(obj).values()
    except TypeError:
        return False
    return any(isinstance(v, QObject) and _dead(v) for v in parts)


def stale_reason(highlighter) -> Optional[str]:
    """Why a grammar result for ``highlighter`` can't be applied, or None."""
    if _dead(highlighter):
        return "highlighter deleted"
    doc = highlighter.document()
    if _dead(doc):
        return "document deleted"
    # The editor owning the document sits a level or two above it
    # (document -> text control -> editor).
    for obj in (highlighter, doc):
        if _has_dead_parts(obj):
            return "editor torn down"
    owner = doc.parent()
    for _ in range(3):
        if owner is None:
            break
        if _dead(owner):
            return "editor deleted"
        if _has_dead_parts(owner):
            return "editor torn down"
        owner = owner.parent()
    return None


def drop_if_stale(highlighter) -> bool:
    """True (and a short note) when this late result should be dropped."""
    try:
        reason = stale_reason(highlighter)
    except RuntimeError:       # a wrapper died while we looked
        reason = "editor deleted"
    if reason:
        print(f"[grammar] late result dropped: {reason}")
        return True
    return False
