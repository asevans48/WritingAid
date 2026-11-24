"""A reverse outline of the draft: what each chapter does, scene by scene.

A developmental editor starts by outlining what the manuscript actually
contains. With a model, each chapter gets one request that records:

* **Scenes**: whose point of view, what happens, and what the scene changes
  for the story (or that it changes nothing).
* **Point-of-view slips**: where the text jumps into another character's
  head inside a scene.
* **Setups and payoffs**: what a reader will expect to matter later, and
  what earlier setup the chapter pays off.
* **Changes**: how a character differs at the chapter's end.
* **The reader's pull** (1 to 5): how strongly the chapter pulls a reader
  on, and where they might put the book down.

The digests are what the whole-book checks and the editorial letter are
written from, so the whole book fits any model. Why these, and what they
can't show: ``docs/publishing/background.md``.

**Evidence.** Every quote must be in the chapter, or the line is dropped.
**Stored** in ``readiness.json`` under ``"digest"``, per manuscript and
chapter, with the text's hash: a chapter is digested again only when it
changes. No Qt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

KEY = "digest"
VERSION = 1
MAX_WORDS = 3500
MAX_WORDS_COMPACT = 1500

SYSTEM = ("You are a developmental editor making a reverse outline of a novel, one chapter "
          "at a time. You record what the text does; you do not praise, judge the writer or "
          "rewrite. You copy quoted words exactly from the chapter.")

ASK = (
    "Outline this chapter in the lines below, in this order. Copy quoted words exactly.\n"
    "One SCENE line per scene (a new scene starts at a break, or a change of time or place):\n"
    "SCENE | point-of-view character | what happens, under 25 words | what the scene changes "
    "for the story, under 15 words, or NONE if it changes nothing | \"the scene's first "
    "5 to 10 words\"\n"
    "Only if the point of view jumps into another character's thoughts inside a scene:\n"
    "SLIP | \"the words where it jumps\" | whose head we were in, and whose we jump into\n"
    "Up to 3, for things set up that a reader will expect to matter later (a threat, a "
    "question, a promise, an object given weight):\n"
    "SETUP | what is set up, under 15 words | \"the words\"\n"
    "Up to 3, for an earlier setup this chapter pays off or answers:\n"
    "PAYOFF | what it pays off, under 15 words | \"the words\"\n"
    "For a character who is different at the chapter's end (a belief, a goal, a "
    "relationship, what they know):\n"
    "CHANGE | character | how they differ, under 15 words\n"
    "Exactly one, for how strongly the chapter pulls a reader on (1 a reader may stop here, "
    "3 fine, 5 can't stop):\n"
    "READER | 1 to 5 | why, under 20 words | \"the words where a reader might put the book "
    "down\" or NONE")

_LINE = re.compile(r"^\W*(SCENE|SLIP|SETUP|PAYOFF|CHANGE|READER)\W*\|(.+)$", re.I | re.M)


def build_prompt(chapter: Any, text: str, compact: bool = False) -> str:
    words = text.split()
    cap = MAX_WORDS_COMPACT if compact else MAX_WORDS
    excerpt = " ".join(words[:cap]) if len(words) > cap else text
    title = getattr(chapter, "title", "") or "this chapter"
    return f"CHAPTER ({title}):\n{excerpt}\n\n{ASK}"


def _none(s: str) -> bool:
    return s.strip().strip('".').upper() in ("NONE", "N/A", "")


def parse(reply: str, text: str) -> Dict[str, Any]:
    from src.ai.story_read import locate
    out: Dict[str, Any] = {"scenes": [], "slips": [], "setups": [], "payoffs": [],
                           "changes": [], "reader": None}
    for m in _LINE.finditer(reply or ""):
        kind = m.group(1).upper()
        f = [x.strip().strip("*_ ") for x in m.group(2).split("|")]

        def place(quote: str):
            where = None if _none(quote) else locate(text, quote)
            return ({"quote": text[where[0]:where[1]], "start": where[0], "end": where[1]}
                    if where else None)
        if kind == "SCENE" and len(f) >= 3:
            where = place(f[3]) if len(f) > 3 else None
            purpose = "" if _none(f[2]) else f[2].rstrip(".")
            out["scenes"].append(dict(where or {"quote": "", "start": -1, "end": -1},
                                      pov=f[0][:60], what=f[1].rstrip(".")[:240],
                                      purpose=purpose[:160]))
        elif kind == "SLIP" and len(f) >= 2:
            where = place(f[0])
            if where:
                out["slips"].append(dict(where, why=f[1].rstrip(".")[:160]))
        elif kind in ("SETUP", "PAYOFF") and len(f) >= 2:
            where = place(f[1])
            if where and not _none(f[0]):
                out["setups" if kind == "SETUP" else "payoffs"].append(
                    dict(where, what=f[0].rstrip(".")[:160]))
        elif kind == "CHANGE" and len(f) >= 2 and not _none(f[0]) and not _none(f[1]):
            out["changes"].append({"who": f[0][:60], "how": f[1].rstrip(".")[:160]})
        elif kind == "READER" and f and out["reader"] is None:
            digit = re.search(r"[1-5]", f[0])
            if digit:
                where = place(f[2]) if len(f) > 2 else None
                out["reader"] = dict(where or {"quote": "", "start": -1, "end": -1},
                                     pull=int(digit.group(0)),
                                     why=(f[1].rstrip(".")[:200] if len(f) > 1 else ""))
    for key in ("setups", "payoffs"):
        out[key] = out[key][:3]
    return out


def read_chapter(llm: Any, chapter: Any, text: str, compact: bool = False) -> Dict[str, Any]:
    """The chapter's digest. Raises when the model fails or gives no scene."""
    reply = llm.generate_text(build_prompt(chapter, text, compact), SYSTEM,
                              max_tokens=900, temperature=0.2) or ""
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply)
    except Exception:
        pass
    found = parse(reply, text)
    if not found["scenes"]:
        raise RuntimeError("the model's outline couldn't be read")
    found["model"] = str(getattr(llm, "model", "") or "")
    return found


class Digests:
    """One manuscript's chapter digests for one run."""

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

    def get(self, chapter: Any, text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The chapter's digest if it was made from the text as it is now."""
        from src.ai.readiness import text_hash
        text = self.texts.get(chapter.id, "") if text is None else text
        entry = self.entries.get(chapter.id)
        if entry and entry.get("text_hash") == text_hash(text) and entry.get("v") == VERSION:
            return entry
        return None

    def ensure(self, llm: Any, chapter: Any, text: str, compact: bool = False) -> Dict[str, Any]:
        entry = self.get(chapter, text)
        if entry is None:
            from src.ai.readiness import text_hash
            entry = dict(read_chapter(llm, chapter, text, compact),
                         text_hash=text_hash(text), v=VERSION)
            self.entries[chapter.id] = entry
            self._save(chapter.id, entry)
        return entry

    def current(self) -> List[tuple]:
        """[(chapter, digest)] for the chapters digested as they are now, in order."""
        return [(ch, d) for ch in self.chapters for d in [self.get(ch)] if d]

    def _save(self, chapter_id: str, entry: Dict[str, Any]) -> bool:
        try:
            from src.data import readiness_state as rs

            def change(data):                     # every other key is kept
                store = data.get(KEY)
                if not isinstance(store, dict):
                    store = data[KEY] = {}
                store.setdefault(rs.scope_key(self.scope), {})[chapter_id] = entry
            return bool(rs.update(self.project, change))
        except Exception as e:
            print(f"[digest] not saved: {e}")
            return False


def for_book(book: Any) -> Digests:
    return book.lazy("chapter_digests",
                     lambda: Digests(book.project, book.scope, book.chapters, book.texts))


def for_project(project: Any, scope: Optional[str] = None,
                texts: Optional[Dict[str, str]] = None) -> Digests:
    from src.ai.readiness import Book
    return for_book(Book(project, scope, texts))


def title_of(chapter: Any) -> str:
    return getattr(chapter, "title", "") or f"Chapter {getattr(chapter, 'number', '')}"


def outline(digests: Digests, max_chars: int = 24000) -> str:
    """The book's reverse outline as text, for a model (and the letter):
    each chapter's scenes, changes, setups, payoffs and pull."""
    blocks = []
    for ch, d in digests.current():
        lines = [f"## {title_of(ch)} (reader's pull "
                 f"{(d.get('reader') or {}).get('pull', '?')}/5)"]
        for s in d.get("scenes", []):
            lines.append(f"- [{s.get('pov') or '?'}] {s.get('what', '')}"
                         + (f" → {s['purpose']}" if s.get("purpose")
                            else " → (changes nothing)"))
        for c in d.get("changes", []):
            lines.append(f"  change: {c['who']}: {c['how']}")
        for s in d.get("setups", []):
            lines.append(f"  setup: {s['what']}")
        for s in d.get("payoffs", []):
            lines.append(f"  payoff: {s['what']}")
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if len(text) > max_chars:                    # a long book: scenes only, then cut
        blocks = [b for b in ("\n".join(l for l in blk.split("\n") if not l.startswith("  "))
                              for blk in blocks)]
        text = "\n\n".join(blocks)[:max_chars]
    return text
