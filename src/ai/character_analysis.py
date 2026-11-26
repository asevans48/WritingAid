"""Character analysis across the book (piece P.8).

For each character in the writer's records, from the text and without a
model:

* **Presence**: which chapters they appear in, and the stretches where they
  are away (``GAP`` chapters or more between two appearances). A character
  the readiness check *Characters who drop out* (``character_threads``)
  flags is shown with that check's own words; this module does not detect
  drop-outs a second way.
* **Speech share**: the lines of dialogue attributed to them
  (``dialogue_craft.lines_by_speaker``, which uses ``dialogue_speakers``),
  their share of all attributed lines, and their rank.
* **Speech consistency**: each chapter where they speak enough is measured
  as ``dialogue_craft`` measures a speaker (``speech_profiles``: words per
  line, contractions, formality, swearing) and compared with the rest of
  the book. A sharp change is put as a question: the scan cannot know
  whether the story causes it.

**The arc** (how they change across the book) needs a model:
``describe_arc`` says so without one, and with one asks it once, from the
record, the Personality Arc snapshots (``personality_assessor``) and the
passages where the character appears early, midway and late.

Everything is a scan: clues, not proof (rule 4). Results are cached by
each chapter's text hash, so opening a character again does not re-read
the book. Nothing is stored in the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

GAP = 3                  # chapters away that count as an absence worth showing
MIN_LINES = 5            # lines in a chapter before its speech is compared
MIN_ELSEWHERE = 8        # lines in the rest of the book to compare it with
NEEDS_MODEL = ("How {name} changes across the book needs a model. Add one under "
               "Settings › AI Configuration or Local Models.")


@dataclass
class Appearance:
    chapter_id: str
    title: str
    index: int                       # 0-based position in its manuscript
    mentions: int = 0
    lines: int = 0
    first: str = ""                  # the first sentence that names them (a link target)


@dataclass
class SpeechShift:
    chapter_id: str
    title: str
    index: int
    changes: List[str] = field(default_factory=list)   # "lines average 4 words here, 14 elsewhere"
    sample: str = ""                                    # a line from that chapter (a link target)

    def describe(self, name: str) -> str:
        return f"In “{self.title}”, {name}'s speech changes: " + "; ".join(self.changes) + "."


@dataclass
class Gap:
    after: Appearance               # last chapter before the absence
    back: Appearance                # the chapter they return in
    chapters: int                   # chapters away

    def describe(self, name: str, total: int = 0) -> str:
        return (f"{name} is away for {self.chapters} chapters, from after "
                f"“{self.after.title}” until “{self.back.title}”.")


@dataclass
class BookPresence:
    """One character in one manuscript."""
    scope: Optional[str]
    book: str                        # the manuscript's name
    total: int                       # chapters with text
    appearances: List[Appearance] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    dropped: str = ""                # the character_threads check's words, if it flags them
    dropped_chapter: str = ""


@dataclass
class CharacterAnalysis:
    name: str
    books: List[BookPresence] = field(default_factory=list)
    lines: int = 0
    words: int = 0
    share: float = 0.0               # of every attributed line in the project
    rank: int = 0                    # 1 = speaks most (0: never speaks)
    speakers: int = 0                # characters who speak at all
    measured_chapters: int = 0       # chapters with enough lines to compare
    shifts: List[SpeechShift] = field(default_factory=list)
    habits: str = ""                 # their usual speech, in words

    @property
    def chapters_present(self) -> int:
        return sum(len(b.appearances) for b in self.books)

    def consistency(self) -> str:
        """One line on whether their way of speaking holds."""
        if self.lines < MIN_LINES:
            return (f"Too few lines to judge how {self.name} speaks "
                    f"({self.lines}; needs {MIN_LINES} in a chapter).")
        if not self.measured_chapters:
            return (f"No chapter gives {self.name} {MIN_LINES} lines or more, so their "
                    "speech can't be compared chapter by chapter.")
        if not self.shifts:
            return (f"{self.name}'s speech holds across the {self.measured_chapters} "
                    f"chapter{'s' if self.measured_chapters != 1 else ''} with enough lines"
                    + (f" ({self.habits})." if self.habits else "."))
        n = len(self.shifts)
        return (f"{self.name}'s speech changes sharply in {n} chapter{'s' if n != 1 else ''}. "
                "If the story causes it, it is working; if not, it may read as a slip.")


# ── Reading the book ───────────────────────────────────────────────────

_SCAN_CACHE: Dict[Tuple[str, Tuple], Dict[str, Any]] = {}
_RESULT_CACHE: Dict[str, Dict[str, CharacterAnalysis]] = {}


def _hash(text: str) -> str:
    from src.ai.readiness import text_hash
    return text_hash(text)


def _texts(project: Any, overrides: Optional[Dict[str, str]] = None):
    """[(scope, book name, [(chapter, text)])] with each chapter's text
    (loaded from disk when it is not in memory)."""
    from pathlib import Path
    overrides = overrides or {}
    project_dir = None
    if getattr(project, "project_path", None):
        project_dir = Path(project.project_path).parent
    try:
        from src.data.publishing_goal import manuscripts
        books = manuscripts(project)
    except Exception:
        books = []
    out = []
    for scope, name, ms in books:
        chapters = []
        for ch in getattr(ms, "chapters", None) or []:
            text = overrides.get(getattr(ch, "id", ""))
            if text is None:
                if not (ch.content or "") and project_dir is not None and \
                        (getattr(ch, "folder_path", None) or getattr(ch, "file_path", None)):
                    try:
                        ch.load_content_from_file(project_dir)
                    except Exception:
                        pass
                text = ch.content or ""
            chapters.append((ch, text.replace("\r\n", "\n")))
        out.append((scope, name, chapters))
    return out


def _scan(text: str, variants: Dict[str, List[str]], names: Tuple[str, ...]) -> Dict[str, Any]:
    """Mentions and attributed lines for one chapter, cached on its text."""
    key = (_hash(text), tuple(sorted((k, tuple(v)) for k, v in variants.items())))
    cached = _SCAN_CACHE.get(key)
    if cached is not None:
        return cached
    from src.ai.canon_index import find_mentions
    from src.ai.dialogue_craft import lines_by_speaker
    mentions = {n: (m["count"], (m.get("examples") or [""])[0])
                for n, m in find_mentions(text, variants).items()}
    lines = lines_by_speaker(text, names) if text.strip() else {}
    found = {"mentions": mentions, "lines": {k: list(v) for k, v in lines.items()}}
    if len(_SCAN_CACHE) > 2048:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[key] = found
    return found


def _dropouts(project: Any, scope: Optional[str], chapters) -> Dict[str, Tuple[str, str]]:
    """The readiness check *Characters who drop out*, run on this
    manuscript: name → (its reason, the chapter id it names)."""
    try:
        from src.ai.readiness import NOT_APPLICABLE, Book, BookContext
        from src.ai.readiness_checks.editor import character_threads
        book = Book(project, scope, {ch.id: text for ch, text in chapters})
        out = character_threads(BookContext(project, scope, book, [], route="", genre=""))
    except Exception as e:                               # pragma: no cover — defensive
        print(f"[character analysis] drop-out check failed: {e}")
        return {}
    if out is NOT_APPLICABLE or out is None:
        return {}
    return {it.text: (it.reason, it.chapter_id or "") for it in out.items}


def analyse(project: Any, texts: Optional[Dict[str, str]] = None) -> Dict[str, CharacterAnalysis]:
    """Every recorded character's presence, speech share and speech
    consistency, keyed by name. ``texts`` overrides chapter texts by id
    (an editor's live text)."""
    characters = [c for c in (getattr(project, "characters", None) or [])
                  if (getattr(c, "name", "") or "").strip()]
    if not characters:
        return {}
    from src.ai.canon_index import character_name_variants
    variants = character_name_variants(characters)
    names = tuple(c.name for c in characters)
    books = _texts(project, texts)
    key = _hash("|".join(
        [repr(sorted((k, tuple(v)) for k, v in variants.items()))]
        + [f"{scope}:{ch.id}:{getattr(ch, 'title', '')}:{_hash(t)}"
           for scope, _n, chs in books for ch, t in chs]))
    if key in _RESULT_CACHE:
        return _RESULT_CACHE[key]

    result = {n: CharacterAnalysis(name=n) for n in names}
    label = getattr(project, "chapter_label", None)
    all_lines: Dict[str, List[Tuple[int, Any, int, str]]] = {n: [] for n in names}
    multi = len(books) > 1
    for scope, book_name, chapters in books:
        chapters = [(ch, t) for ch, t in chapters if t.strip()]
        if not chapters:
            continue
        drops = _dropouts(project, scope, chapters)
        per: Dict[str, BookPresence] = {n: BookPresence(scope, book_name, len(chapters))
                                        for n in names}
        for i, (ch, text) in enumerate(chapters):
            title = ch.title or f"Chapter {ch.number}"
            if multi and callable(label):
                try:
                    title = label(scope, ch)
                except Exception:
                    pass
            scan = _scan(text, variants, names)
            for n in names:
                count, first = scan["mentions"].get(n, (0, ""))
                said = scan["lines"].get(n, [])
                if not count and not said:
                    continue
                per[n].appearances.append(Appearance(ch.id, title, i, count, len(said), first))
                for line in said:
                    all_lines[n].append((i, ch, len(per[n].appearances) - 1, line))
        for n, bp in per.items():
            if not bp.appearances:
                continue
            for a, b in zip(bp.appearances, bp.appearances[1:]):
                if b.index - a.index - 1 >= GAP:
                    bp.gaps.append(Gap(a, b, b.index - a.index - 1))
            if n in drops:
                bp.dropped, bp.dropped_chapter = drops[n]
            result[n].books.append(bp)

    _speech(result, all_lines, characters)
    if len(_RESULT_CACHE) > 16:
        _RESULT_CACHE.clear()
    _RESULT_CACHE[key] = result
    return result


def _speech(result: Dict[str, CharacterAnalysis], all_lines, characters) -> None:
    """Speech share and consistency, measured as ``dialogue_craft`` measures
    a speaker for ``speech_profiles``."""
    from src.ai.dialogue_craft import _words

    total = sum(len(v) for v in all_lines.values())
    order = sorted((n for n in all_lines if all_lines[n]), key=lambda n: -len(all_lines[n]))
    for n, lines in all_lines.items():
        a = result[n]
        said_all = [line for _i, _ch, _k, line in lines]
        a.lines = len(said_all)
        a.words = sum(len(_words(l)) for l in said_all)
        a.share = a.lines / total if total else 0.0
        a.rank = order.index(n) + 1 if n in order else 0
        a.speakers = len(order)
        if a.lines < MIN_LINES:
            continue
        a.habits = _habits(_measure(n, said_all))
        by_chapter: Dict[str, List[str]] = {}
        for _i, ch, _k, line in lines:
            by_chapter.setdefault(ch.id, []).append(line)
        for cid, said in by_chapter.items():
            if len(said) < MIN_LINES:
                continue
            a.measured_chapters += 1
            rest = [line for _i, ch, _k, line in lines if ch.id != cid]
            if len(rest) < MIN_ELSEWHERE:
                continue
            there = _measure(n, rest)
            changes = compare(_measure(n, said), there)
            if not changes:
                continue
            ap = next((x for b in a.books for x in b.appearances if x.chapter_id == cid), None)
            sample = max(said, key=lambda l: abs(len(_words(l)) - there.words_per_line))
            a.shifts.append(SpeechShift(cid, ap.title if ap else "", ap.index if ap else 0,
                                        changes, sample))
        a.shifts.sort(key=lambda s: s.index)


def _measure(name: str, lines: Sequence[str]):
    from src.ai.dialogue_craft import _measure as measure
    return measure(name, lines)


def _habits(p) -> str:
    bits = [f"lines average about {p.words_per_line:.0f} words",
            ("contractions freely" if p.contractions_per_100 >= 4 else
             "rarely a contraction" if p.contractions_per_100 < 1 else "some contractions")]
    if p.formal_per_100 >= 1:
        bits.append("a formal register")
    if p.profanity_per_100 >= 0.5:
        bits.append("swears")
    return ", ".join(bits)


def compare(here, there) -> List[str]:
    """How a chapter's speech (``here``) differs sharply from the rest of
    the book (``there``); [] when it holds."""
    out = []
    a, b = here.words_per_line, there.words_per_line
    if min(a, b) > 0 and max(a, b) / min(a, b) >= 2 and abs(a - b) >= 5:
        out.append(f"lines average {a:.0f} words here and {b:.0f} elsewhere")
    ca, cb = here.contractions_per_100, there.contractions_per_100
    if cb >= 3 and ca < 1:
        out.append(f"almost no contractions here, {cb:.0f} per 100 words elsewhere")
    elif cb < 1 and ca >= 3:
        out.append(f"{ca:.0f} contractions per 100 words here, almost none elsewhere")
    fa, fb = here.formal_per_100, there.formal_per_100
    if fa >= 2 and fb < 0.5:
        out.append("formal here, plain elsewhere")
    elif fb >= 2 and fa < 0.5:
        out.append("plain here, formal elsewhere")
    pa, pb = here.profanity_per_100, there.profanity_per_100
    if pa >= 1 and pb == 0:
        out.append("swears here and nowhere else")
    elif pb >= 1 and pa == 0:
        out.append("never swears here, often elsewhere")
    return out


def for_character(project: Any, name: str,
                  texts: Optional[Dict[str, str]] = None) -> Optional[CharacterAnalysis]:
    return analyse(project, texts).get(name)


def summary_lines(a: CharacterAnalysis) -> List[str]:
    """Plain lines for a character (the Critique's scan and tests)."""
    out = []
    for b in a.books:
        where = f" of {b.book}" if len(a.books) > 1 else ""
        out.append(f"In {len(b.appearances)} of {b.total} chapters{where}.")
        out.extend(g.describe(a.name, b.total) for g in b.gaps)
        if b.dropped:
            out.append(b.dropped)
    if not a.books:
        out.append(f"{a.name} is not named in any chapter.")
    if a.lines:
        out.append(f"Speaks {a.lines} line{'s' if a.lines != 1 else ''} ({a.share:.0%} of the "
                   f"attributed dialogue; {_ordinal(a.rank)} of {a.speakers} speakers).")
    else:
        out.append(f"No line of dialogue is attributed to {a.name}.")
    out.append(a.consistency())
    out.extend(s.describe(a.name) for s in a.shifts)
    return out


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# ── The arc (needs a model) ────────────────────────────────────────────

ARC_SYSTEM = ("You are a developmental editor describing how one character changes across "
              "a novel. Answer only from the record and passages you are given, and quote "
              "them exactly when you cite them.")


def arc_prompt(project: Any, character: Any, analysis: Optional[CharacterAnalysis] = None,
               compact: bool = False, texts: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The arc request: the record, the Personality Arc snapshots and the
    passages where the character appears early, midway and late. None when
    they appear in no chapter."""
    from src.ai.canon_index import (_name_variants, format_character_profile,
                                    passages_mentioning)
    analysis = analysis or for_character(project, character.name, texts)
    if analysis is None or not analysis.books:
        return None
    by_id = {ch.id: t for _s, _n, chs in _texts(project, texts) for ch, t in chs}
    seen = [ap for b in analysis.books for ap in b.appearances]
    picks = [seen[0], seen[len(seen) // 2], seen[-1]] if len(seen) >= 3 else seen
    budget = 220 if compact else 450
    parts, used = [], set()
    for p in picks:
        if p.chapter_id in used:
            continue
        used.add(p.chapter_id)
        ev = passages_mentioning(by_id.get(p.chapter_id, ""), _name_variants(character.name),
                                 budget)
        if ev:
            parts.append(f"[{p.title}]\n{ev}")
    snaps = [f"- {s.chapter_title or s.chapter_number}: "
             + "; ".join(x for x in (s.emotional_state, s.growth_notes) if x)
             for s in (getattr(character, "personality_arc", None) or [])
             if (s.emotional_state or s.growth_notes)]
    try:
        record = format_character_profile(character, seen[-1].index + 1,
                                          max_field=120 if compact else 200)
    except Exception:
        record = f"{character.name}: {getattr(character, 'personality', '')}"
    return (f"CHARACTER RECORD (the author's intent):\n{record}\n\n"
            + ("PERSONALITY SNAPSHOTS BY CHAPTER:\n" + "\n".join(snaps[-8:]) + "\n\n"
               if snaps else "")
            + f"{character.name.upper()} IN THE BOOK (early, midway, late):\n"
            + "\n\n".join(parts) + "\n\n"
            "Describe how this character changes across the book. Reply with ONLY these "
            "lines:\n"
            "START: <who they are at the start, one sentence>\n"
            "TURNS: <the moments that change them, with a short quote each; or 'none'>\n"
            "END: <who they are by the last passage, one sentence>\n"
            "EARNED: <is the change shown on the page, or does it jump? one sentence>")


def describe_arc(project: Any, character: Any, llm: Any,
                 texts: Optional[Dict[str, str]] = None) -> str:
    """How the character changes across the book: one model request; a
    one-line "needs a model" without one."""
    name = getattr(character, "name", "") or "This character"
    if llm is None:
        return NEEDS_MODEL.format(name=name)
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        compact = bool(is_local_llm(llm))
    except Exception:
        compact = False
    prompt = arc_prompt(project, character, compact=compact, texts=texts)
    if prompt is None:
        return f"{name} is not named in any chapter yet, so there is no arc to describe."
    reply = llm.generate_text(prompt, ARC_SYSTEM, max_tokens=500, temperature=0.3) or ""
    if not isinstance(reply, str):
        reply = str(reply)
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply)
    except Exception:
        pass
    return reply.strip()


def arc_llm():
    """The model for the arc, resolved as critique work is (rule 2): the
    Critique's model, then the default. Built only when the writer asks."""
    from src.ai import task_llm
    return task_llm.build_critique_llm() or task_llm.build_default_llm()


# ── The Critique's Character check (a scan for the chapter's characters) ──

def chapter_block(project: Any, chapter: Any, text: str,
                  names: Optional[Iterable[str]] = None, limit: int = 6) -> str:
    """Markdown for the Character check: how each character in this chapter
    (most named first) appears and speaks across the book, with links to
    the passages. "" when no recorded character is in the chapter."""
    from src.ai.text_links import make_link
    cid = getattr(chapter, "id", "") or ""
    if not cid:
        return ""
    found = analyse(project, {cid: text})
    here_of = {n: ap for n, a in found.items() for b in a.books for ap in b.appearances
               if ap.chapter_id == cid}
    wanted = list(names) if names is not None else list(found)
    wanted = sorted((n for n in wanted if n in here_of),
                    key=lambda n: -(here_of[n].mentions + here_of[n].lines))
    rows = []
    for n in wanted[:limit]:
        a, here = found[n], here_of[n]
        bits = []
        for b in a.books:
            if here not in b.appearances:
                continue
            where = f" of {b.book}" if len(a.books) > 1 else ""
            bits.append(f"in {len(b.appearances)} of {b.total} chapters{where}")
            back = next((g for g in b.gaps if g.back is here), None)
            if back is not None:
                bits.append(f"back after {back.chapters} chapters away (last seen in "
                            f"“{back.after.title}” "
                            f"{make_link(back.after.chapter_id, back.after.first, '↗')})")
            if b.dropped and b.dropped_chapter == cid:
                bits.append("last seen here. " + b.dropped)
        if a.lines:
            bits.append(f"{here.lines} line{'s' if here.lines != 1 else ''} here, {a.lines} in "
                        f"the book ({a.share:.0%} of its dialogue)")
        shift = next((s for s in a.shifts if s.chapter_id == cid), None)
        if shift is not None:
            bits.append("their speech changes: " + "; ".join(shift.changes) + ". Is the change "
                        f"intended? “{_short(shift.sample)}” {make_link(cid, shift.sample, '↗')}")
        rows.append(f"- **{n}**: " + "; ".join(bits))
    if not rows:
        return ""
    return ("#### Across the book (a scan)\n" + "\n".join(rows)
            + "\n\nCounted from the text, no model. Story ▸ Characters shows each "
              "character's chapters in full.")


def _short(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split()).rstrip(",;: ")
    return text if len(text) <= n else text[:n - 1] + "…"
