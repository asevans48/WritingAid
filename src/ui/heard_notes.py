"""Marks become notes (piece 6.2).

The sentences the writer marked while listening (6.1, ``listen_marks``)
show in the Companion twice, from the one store:

* **Notes as you write**: a note of kind ``"heard"`` (👂) on its sentence,
  with the section's own buttons. **💡 Suggest fix** opens Suggestions on
  the sentence; **Dismiss** clears the mark.
* **The next-fix queue**: a line-stage entry (``fix_queue`` ``extra``, the
  way the style flags arrive) with the sentence as its place and no quick
  fix, so the card offers ✎ edit and 💡 More options… (Suggestions), and
  with a model, rewrites in the writer's voice as for any finding.

**A mark is never lost** (rule 15): it leaves the store only when it was
fixed (a change accepted on it, from the notes or the card) or the writer
dismissed it (Dismiss, or Not a problem on the card). Skip keeps it. A
mark whose sentence has changed stays a note, "(the text has changed)",
until the writer dismisses it; it is left out of the queue, which needs
the sentence to point at.

Call lines only elsewhere: ``companion_panel`` (notes, Suggest fix,
Dismiss), ``next_fixes`` (find, accept, done_with, dismiss) and
``listen_mark`` (refresh when listening stops).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, List

from src.ai.companion import Note
from src.data import listen_marks

KIND = "heard"
ICON = "👂"
CHECK = "heard"                       # the queue entry's check name
LABEL = "Marked while listening"
REASON = "You marked this sentence while listening to the chapter."
STAGE = "line"                        # unless the writer moves the chapter on
TIER = "major"                        # the writer's own mark: first in its stage
FOCUS = ("The writer marked this sentence while hearing the chapter read aloud: "
         "something in how it sounds (rhythm, clarity, wording or flow) is off. "
         "Keep its meaning.")


@dataclass(eq=False)
class HeardNote(Note):
    """A Companion note made from a mark; ``mark_id`` clears it."""
    mark_id: str = ""
    focus: str = FOCUS

    @property
    def key(self) -> str:
        return f"{KIND}:{self.mark_id}"


def _short(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _where(cc: Any):
    project = getattr(cc, "project", None)
    chapter_id = getattr(getattr(cc, "chapter", None), "id", "") or ""
    return project, chapter_id


def notes_for(project: Any, chapter_id: str, text: str) -> List[HeardNote]:
    """The chapter's marks as notes, against its text now."""
    out = []
    for m in listen_marks.marks(project, chapter_id):
        start, _end, status = listen_marks.resolve(m, text)
        changed = status == listen_marks.CHANGED
        paragraph = (int(m.get("paragraph", 0) or 0) if changed
                     else text.count("\n", 0, start))
        line = f"{LABEL}: “{_short(m['text'])}”" + (
            f" ({listen_marks.CHANGED_LABEL})" if changed else "")
        out.append(HeardNote(KIND, line, paragraph, m["text"], None, mark_id=m.get("id", "")))
    return out


def entries_for(project: Any, chapter_id: str, text: str) -> List[Any]:
    """The chapter's marks as next-fix entries (line stage, no quick fix).
    A mark whose sentence has changed is left out (it stays a note)."""
    from src.ai import fix_queue, readiness as rd
    out = []
    for m in listen_marks.marks(project, chapter_id):
        start, end, status = listen_marks.resolve(m, text)
        if status == listen_marks.CHANGED or end <= start:
            continue
        item = rd.Item(start=start, end=end, text=text[start:end], reason=REASON, kind=KIND,
                       key=f"{KIND}:{m.get('id', '')}", suggestions=[])
        out.append(fix_queue.Entry(CHECK, LABEL, STAGE, TIER, item))
    return out


# ── The Companion (companion_panel.CompanionController) ──────────────

def notes(cc: Any) -> List[HeardNote]:
    """For ``_show_notes``: never raises (rule 7)."""
    try:
        project, chapter_id = _where(cc)
        return notes_for(project, chapter_id, cc.ce.editor.toPlainText())
    except Exception as e:                               # noqa: BLE001
        print(f"[heard notes] {e}")
        return []


def chapter_loaded(cc: Any) -> None:
    """Show the chapter's marks as soon as it opens."""
    project, chapter_id = _where(cc)
    if listen_marks.marks(project, chapter_id):
        cc._show_notes()


def note_cleared(cc: Any, note: Any) -> bool:
    """Dismiss, or a fix made from Suggest fix: clear the mark. True when
    ``note`` was a mark (the caller is done)."""
    if not isinstance(note, HeardNote):
        return False
    forget(cc, note.mark_id)
    return True


def forget(cc: Any, mark_id: str) -> None:
    """The mark is fixed or dismissed: out of the store, the notes and the
    queue."""
    project, chapter_id = _where(cc)
    if mark_id:
        listen_marks.remove(project, chapter_id, mark_id)
    queue = getattr(cc, "queue", None)
    if queue is not None:
        key = f"{KIND}:{mark_id}"
        queue.extra = [e for e in queue.extra if e.item.key != key]
        gone = [n for n, e in enumerate(queue.entries) if e.item.key == key]
        for n in reversed(gone):
            queue.fixes.pop(queue.entries.pop(n).key, None)
            if n < queue.index:
                queue.index -= 1
        if gone:
            queue.show()                      # the card moves on if it showed it
    cc._show_notes()


# ── The queue (next_fixes.Queue) ─────────────────────────────────────

def is_mark(entry: Any) -> bool:
    return entry is not None and getattr(entry, "check", "") == CHECK


def _mark_id(entry: Any) -> str:
    return entry.item.key.partition(":")[2]


def queue_extra(queue: Any) -> List[Any]:
    """For ``Queue.find``: the marks to add to ``extra``."""
    try:
        project, chapter_id = _where(queue.cc)
        return entries_for(project, chapter_id, queue.cc.ce.editor.toPlainText())
    except Exception as e:                               # noqa: BLE001
        print(f"[heard notes] {e}")
        return []


def entry_done(queue: Any, entry: Any) -> None:
    """A fix was accepted on the card or made with More options…: the mark
    goes (the caller drops the entry and shows the next)."""
    if is_mark(entry):
        mark_id = _mark_id(entry)
        project, chapter_id = _where(queue.cc)
        listen_marks.remove(project, chapter_id, mark_id)
        key = entry.item.key
        queue.extra = [e for e in queue.extra if e.item.key != key]
        queue.cc._show_notes()


def queue_dismiss(queue: Any, entry: Any) -> bool:
    """Not a problem on a mark: the mark is cleared (only this one; nothing
    is remembered against other sentences). True when handled."""
    if not is_mark(entry):
        return False
    words = entry.item.text if len(entry.item.text) <= 30 else entry.item.text[:29] + "…"
    forget(queue.cc, _mark_id(entry))
    rest = queue.card.status.text() if queue.card.fix is not None else ""
    queue.card.status.setText(f"Mark cleared from “{html.escape(words)}”."
                              + (" · " + rest if rest else ""))
    return True


# ── Listening (listen_mark) ──────────────────────────────────────────

def refresh(owner: Any) -> None:
    """Listening stopped: the notes, and the queue once it has been
    filled, show the marks made."""
    try:
        cc = getattr(owner, "companion", None)
        if cc is None:
            return
        cc._show_notes()
        queue = getattr(cc, "queue", None)
        if queue is None or queue.report is None:
            return
        queue.extra = [e for e in queue.extra if not is_mark(e)] + queue_extra(queue)
        queue.set_report(queue.report, queue.stage)
    except Exception as e:                               # noqa: BLE001 (rule 7)
        print(f"[heard notes] {e}")
