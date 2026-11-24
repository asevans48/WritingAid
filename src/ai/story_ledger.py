"""The book's style sheet: what each chapter has established.

A fiction copyeditor keeps a style sheet of characters, places and the
timeline, and checks every chapter against it (Schneider, *The Chicago
Guide to Copyediting Fiction*; see ``docs/publishing/background.md``). This
is the app's: as the model reads each chapter for the story's major issues
(``story_read``), it also lists the facts that chapter establishes, and
every later chapter is read against the facts recorded before it. So a
contradiction between chapter 3 and chapter 27 can be seen.

* **A fact is a quote.** Each fact carries the exact words that establish
  it; a fact whose words are no longer in its chapter is not used.
* **Stable.** When a chapter is read again, facts whose words are still
  there are kept as they are; only new ones are added. So editing one
  chapter does not make every later chapter look changed.
* **The writer's.** A fact can be reworded or removed (from the style
  sheet in the scorecard). A removed fact is remembered, so reading the
  chapter again doesn't bring it back; it can be put back.
* **Stored** in the project's readiness file (``readiness.json``, key
  ``"ledger"``, per manuscript, per chapter). Nothing else in the file is
  touched.
* **Costs nothing extra**: the facts come back in the same request as the
  story read.

No Qt.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

KEY = "ledger"
MAX_PER_CHAPTER = 12
MAX_SHOWN = 40               # facts given to the model for one chapter
MAX_SHOWN_COMPACT = 15       # on-device models
TIMELINE = ("timeline", "time", "date", "dates")
RECENT_TIMELINE = 6          # timeline facts always carried forward


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def is_timeline(fact: Dict[str, Any]) -> bool:
    return str(fact.get("subject", "")).strip().lower() in TIMELINE


def line(fact: Dict[str, Any]) -> str:
    """One fact as the model (and the writer) reads it."""
    return (f"[{fact.get('chapter', '')}] {fact['subject']}: {fact['fact']} — "
            f"\"{fact['quote']}\"")


class Ledger:
    """One manuscript's facts, chapter by chapter, for one run."""

    def __init__(self, project: Any, scope: Optional[str], chapters: List[Any],
                 texts: Dict[str, str]):
        self.project, self.scope = project, scope
        self.chapters, self.texts = list(chapters), texts
        self.entries: Dict[str, Dict[str, Any]] = {}
        try:
            from src.data import readiness_state as rs
            stored = rs.load(project).get(KEY, {})
            entries = stored.get(rs.scope_key(scope), {}) if isinstance(stored, dict) else {}
            self.entries = {k: v for k, v in entries.items() if isinstance(v, dict)}
        except Exception:
            pass
        self._valid: Dict[str, List[Dict[str, Any]]] = {}

    # ── Reading ──────────────────────────────────────────────────

    def facts_of(self, chapter: Any) -> List[Dict[str, Any]]:
        """The chapter's facts whose words are still in its text."""
        cid = chapter.id
        if cid not in self._valid:
            from src.ai.story_read import locate
            text = self.texts.get(cid, "")
            title = getattr(chapter, "title", "") or f"Chapter {getattr(chapter, 'number', '')}"
            out = []
            for f in (self.entries.get(cid) or {}).get("facts", []) or []:
                if (isinstance(f, dict) and f.get("quote") and f.get("subject")
                        and not f.get("removed")
                        and locate(text, f["quote"]) is not None):
                    out.append(dict(f, chapter=title, chapter_id=cid))
            self._valid[cid] = out
        return self._valid[cid]

    def all_facts(self) -> List[Dict[str, Any]]:
        return [f for ch in self.chapters for f in self.facts_of(ch)]

    def removed_facts(self) -> List[Dict[str, Any]]:
        """Facts the writer removed (they can be put back)."""
        out = []
        for ch in self.chapters:
            title = getattr(ch, "title", "") or f"Chapter {getattr(ch, 'number', '')}"
            for f in (self.entries.get(ch.id) or {}).get("facts", []) or []:
                if isinstance(f, dict) and f.get("removed") and f.get("quote"):
                    out.append(dict(f, chapter=title, chapter_id=ch.id))
        return out

    # ── The writer's changes ─────────────────────────────────────

    def _change(self, chapter_id: str, quote: str, change) -> bool:
        entry = self.entries.get(chapter_id)
        for f in (entry or {}).get("facts", []) or []:
            if isinstance(f, dict) and f.get("quote") == quote:
                change(f)
                self._valid.pop(chapter_id, None)
                return self._save(chapter_id, entry)
        return False

    def remove(self, chapter_id: str, quote: str) -> bool:
        return self._change(chapter_id, quote, lambda f: f.update(removed=True))

    def restore(self, chapter_id: str, quote: str) -> bool:
        return self._change(chapter_id, quote, lambda f: f.pop("removed", None))

    def edit(self, chapter_id: str, quote: str, subject: str, fact: str) -> bool:
        """Reword a fact (its establishing words stay). Empty parts are refused."""
        subject, fact = subject.strip()[:60], fact.strip()[:160]
        if not subject or not fact:
            return False
        return self._change(chapter_id, quote,
                            lambda f: f.update(subject=subject, fact=fact, edited=True))

    def before(self, chapter: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for ch in self.chapters:
            if ch.id == chapter.id:
                break
            out.extend(self.facts_of(ch))
        return out

    def shown(self, chapter: Any, text: str, compact: bool = False) -> List[Dict[str, Any]]:
        """The earlier facts this chapter is read against: those about
        someone or something the chapter mentions, and the latest timeline
        facts; in book order."""
        earlier = self.before(chapter)
        if not earlier:
            return []
        lower = text.lower()
        counts: Dict[str, int] = {}
        scored = []
        timeline = [i for i, f in enumerate(earlier) if is_timeline(f)][-RECENT_TIMELINE:]
        for i, f in enumerate(earlier):
            subject = str(f["subject"]).strip().lower()
            if i in timeline:
                score = 10 ** 6
            else:
                if subject not in counts:
                    counts[subject] = len(re.findall(
                        r"(?<!\w)" + re.escape(subject) + r"(?!\w)", lower)) if subject else 0
                score = counts[subject]
            if score:
                scored.append((-score, i))
        scored.sort()
        keep = sorted(i for _, i in scored[:MAX_SHOWN_COMPACT if compact else MAX_SHOWN])
        return [earlier[i] for i in keep]

    def shown_hash(self, chapter: Any, text: str) -> str:
        """Changes when the facts this chapter is read against change (part
        of the story checks' cache key). The same for every model size."""
        facts = self.shown(chapter, text)
        return _hash("\n".join(line(f) for f in facts)) if facts else ""

    def is_current(self, chapter: Any, text: str, text_hash: str) -> bool:
        """The chapter was read as it is now, against the facts as they are now."""
        entry = self.entries.get(chapter.id)
        return (isinstance(entry, dict) and entry.get("text_hash") == text_hash
                and entry.get("shown", "") == self.shown_hash(chapter, text))

    # ── Recording ────────────────────────────────────────────────

    def record(self, chapter: Any, text: str, text_hash: str,
               found: List[Dict[str, Any]]) -> bool:
        """Keep the chapter's facts: those already recorded whose words are
        still in the text stay as they are; new ones are added."""
        from src.ai.story_read import locate
        kept, spans = [], []
        for f in (self.entries.get(chapter.id) or {}).get("facts", []) or []:
            where = locate(text, f.get("quote", "")) if isinstance(f, dict) else None
            if where is not None and f.get("subject"):
                # As it is: the writer's rewording and removals included.
                kept.append({k: f[k] for k in ("subject", "fact", "quote", "removed", "edited")
                             if k in f})
                spans.append(where)
        for f in found:
            if sum(1 for k in kept if not k.get("removed")) >= MAX_PER_CHAPTER:
                break
            where = locate(text, f.get("quote", ""))
            if where is None or not str(f.get("subject", "")).strip():
                continue
            if any(where[0] < e and s < where[1] for s, e in spans):
                continue                          # the same words are already recorded
            kept.append({"subject": str(f["subject"]).strip()[:60],
                         "fact": str(f.get("fact", "")).strip()[:160],
                         "quote": text[where[0]:where[1]][:240]})
            spans.append(where)
        entry = {"text_hash": text_hash, "shown": self.shown_hash(chapter, text),
                 "facts": kept}
        self.entries[chapter.id] = entry
        self._valid.pop(chapter.id, None)
        return self._save(chapter.id, entry)

    def _save(self, chapter_id: str, entry: Dict[str, Any]) -> bool:
        try:
            from src.data import readiness_state as rs

            def change(data):                     # every other key is kept
                sheet = data.get(KEY)
                if not isinstance(sheet, dict):
                    sheet = data[KEY] = {}
                per = sheet.setdefault(rs.scope_key(self.scope), {})
                per[chapter_id] = entry
            return bool(rs.update(self.project, change))
        except Exception as e:
            print(f"[style sheet] not saved: {e}")
            return False


def for_book(book: Any) -> Ledger:
    """The run's ledger (one per ``readiness.Book``)."""
    return book.lazy("story_ledger",
                     lambda: Ledger(book.project, book.scope, book.chapters, book.texts))


def for_project(project: Any, scope: Optional[str] = None,
                texts: Optional[Dict[str, str]] = None) -> Ledger:
    from src.ai.readiness import Book
    return for_book(Book(project, scope, texts))


def grouped(facts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Facts by subject, the timeline last; for showing the style sheet."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for f in facts:
        if not is_timeline(f):
            out.setdefault(str(f["subject"]).strip(), []).append(f)
    out = dict(sorted(out.items(), key=lambda kv: kv[0].lower()))
    timeline = [f for f in facts if is_timeline(f)]
    if timeline:
        out["Timeline"] = timeline
    return out
