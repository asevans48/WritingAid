"""Critique of a highlighted passage, with three rewrites.

The writer highlights some text and asks for suggestions. The selection
is widened to whole sentences (a highlight that starts or ends mid-
sentence is a fragment the model can't judge), then the model reads it
against the project's characters, worldbuilding, plot and story outline
and the surrounding chapter. It returns what works, what doesn't, and
three replacement passages.

Everything except the model call is deterministic, so it is tested
without a model; the output parser is lenient because small local
models (Gemma and similar) rarely follow a format exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

NUM_SUGGESTIONS = 3

# ── Selection → whole sentences ──────────────────────────────────────

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "capt", "col", "gen", "lt",
    "sgt", "rev", "vs", "etc", "e.g", "i.e", "no", "mt", "ft", "fig", "approx",
}
# Terminal punctuation, then any closing quotes/brackets/markdown, then space.
_BOUNDARY_RX = re.compile(r"[.!?…]+[\"'”’)\]*_]*(?=\s)")


def _is_abbreviation(paragraph: str, punct_at: int) -> bool:
    if paragraph[punct_at] != ".":
        return False
    m = re.search(r"([A-Za-z][A-Za-z.]*)$", paragraph[:punct_at])
    if not m:
        return False
    word = m.group(1).lower()
    return word in _ABBREVIATIONS or (len(word) == 1 and paragraph[m.start()].isupper())


def _sentence_spans(paragraph: str) -> List[Tuple[int, int]]:
    """(start, end) of each sentence in one paragraph, whitespace excluded."""
    spans, start = [], 0
    for m in _BOUNDARY_RX.finditer(paragraph):
        if _is_abbreviation(paragraph, m.start()):
            continue
        rest = paragraph[m.end():].lstrip()
        if rest[:1].islower():          # '"Run!" she cried.' is one sentence
            continue
        spans.append((start, m.end()))
        start = m.end()
    spans.append((start, len(paragraph)))
    out = []
    for s, e in spans:
        while s < e and paragraph[s].isspace():
            s += 1
        while e > s and paragraph[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def expand_to_sentences(text: str, start: int, end: int) -> Tuple[int, int]:
    """Widen ``text[start:end]`` to the whole sentences it touches.

    Never crosses a paragraph break it wasn't already spanning; a
    selection of whitespace alone is returned unchanged.
    """
    start, end = max(0, min(start, len(text))), max(0, min(end, len(text)))
    if start > end:
        start, end = end, start
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return start, end

    def paragraph_at(i: int) -> Tuple[int, int]:
        s = text.rfind("\n", 0, i) + 1
        e = text.find("\n", i)
        return s, (len(text) if e < 0 else e)

    first_s, first_e = paragraph_at(start)
    for s, e in _sentence_spans(text[first_s:first_e]):
        if first_s + e > start:
            start = min(start, first_s + s)
            break
    last_s, last_e = paragraph_at(end - 1)
    for s, e in _sentence_spans(text[last_s:last_e]):
        if last_s + e >= end:
            end = max(end, last_s + e)
            break
    return start, end


def qt_to_py_index(text: str, position: int) -> int:
    """QTextDocument position (UTF-16 units) → index into a Python str."""
    data = text.encode("utf-16-le")[:2 * max(0, position)]
    return len(data.decode("utf-16-le", errors="ignore"))


def py_to_qt_index(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


# ── Context from the project ─────────────────────────────────────────

@dataclass
class PassageContext:
    passage: str
    before: str = ""
    after: str = ""
    chapter: str = ""
    characters: str = ""
    world: str = ""
    plot: str = ""
    story_outline: str = ""
    related: str = ""           # project search results (RAG)
    earlier: str = ""           # summaries of the chapters before this one
    voice: str = ""             # the author's measured voice
    examples: str = ""          # rewrites the author rated before
    known_names: List[str] = field(default_factory=list)   # for spelling checks
    observations: List[str] = field(default_factory=list)  # found without the model
    speakers: str = ""          # who says each line of dialogue in the passage

    def notes_text(self) -> str:
        """Everything from the story bible the model was shown."""
        return "\n".join((self.story_outline, self.plot, self.earlier, self.chapter,
                          self.characters, self.world, self.related))

    def sections(self) -> List[Tuple[str, str]]:
        return [("STORY OUTLINE", self.story_outline), ("PLOT", self.plot),
                ("EARLIER CHAPTERS", self.earlier),
                ("THIS CHAPTER", self.chapter), ("CHARACTERS IN THIS PASSAGE", self.characters),
                ("WORLDBUILDING IN THIS PASSAGE", self.world),
                ("OTHER RELATED PROJECT NOTES", self.related),
                ("THE AUTHOR'S VOICE", self.voice),
                ("THE AUTHOR'S TASTE", self.examples)]

    def sentences(self) -> List[str]:
        from src.ai.rewrite_quality import split_sentences
        return split_sentences(self.passage)

    def scene(self, before_chars: int = 0) -> str:
        """The surrounding text with the passage marked in place, so the
        model sees exactly where it sits and what is already written."""
        before = self.before[-before_chars:] if before_chars else self.before
        return (f"{before}\n⟦PASSAGE START⟧ {self.passage.strip()} ⟦PASSAGE END⟧\n"
                f"{self.after}").strip()

    def numbered_passage(self) -> str:
        sents = self.sentences()
        if len(sents) < 2:
            return self.passage.strip()
        return "\n".join(f"[{i}] {s}" for i, s in enumerate(sents, 1))


def _clip(text: str, limit: int, *, from_end: bool = False) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    if from_end:
        cut = text[-limit:]
        nl = cut.find("\n")
        return "…" + (cut[nl + 1:] if 0 <= nl < limit // 3 else cut)
    cut = text[:limit]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > limit * 2 // 3 else cut) + "…"


def _story_outline(planning: Any, limit: int) -> str:
    if planning is None:
        return ""
    lines = []
    pyramid = getattr(planning, "freytag_pyramid", None)
    for attr, label in (("exposition", "Exposition"), ("rising_action", "Rising action"),
                        ("climax", "Climax"), ("falling_action", "Falling action"),
                        ("resolution", "Resolution")):
        value = (getattr(pyramid, attr, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    events = sorted(getattr(pyramid, "events", None) or [],
                    key=lambda e: (getattr(e, "act", 1), getattr(e, "sort_order", 0)))
    if events:
        lines.append("Key events: " + "; ".join(e.title for e in events[:12] if e.title))
    return _clip("\n".join(lines), limit)


def _plot(planning: Any, limit: int) -> str:
    if planning is None:
        return ""
    lines = []
    if (getattr(planning, "main_plot", "") or "").strip():
        lines.append(f"Main plot: {planning.main_plot.strip()}")
    for sp in (getattr(planning, "subplots", None) or [])[:5]:
        if getattr(sp, "status", "active") == "abandoned":
            continue
        lines.append(f"Subplot — {sp.title}: {(sp.description or '')[:200]}")
    for p in (getattr(planning, "promises", None) or [])[:6]:
        lines.append(f"Promise to the reader ({p.promise_type}): {p.title}"
                     + (f" — {p.description[:150]}" if p.description else ""))
    themes = [t.title for t in getattr(planning, "theme_details", None) or [] if t.title]
    themes += [t for t in getattr(planning, "themes", None) or [] if t and t not in themes]
    if themes:
        lines.append("Themes: " + ", ".join(themes[:6]))
    return _clip("\n".join(lines), limit)


def _chapter_notes(chapter: Any, limit: int) -> str:
    if chapter is None:
        return ""
    plan = getattr(chapter, "planning", None)
    lines = [f"Chapter {getattr(chapter, 'number', '')}: {getattr(chapter, 'title', '')}".strip()]
    if plan is not None:
        for attr, label in (("description", "Summary"), ("outline", "Chapter outline")):
            value = (getattr(plan, attr, "") or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        if getattr(plan, "pov_character", ""):
            lines.append(f"Point of view: {plan.pov_character}")
        events = getattr(plan, "events", None) or []
        if events:
            lines.append("Planned beats: " + "; ".join(
                f"{e.text}{' (done)' if getattr(e, 'completed', False) else ''}"
                for e in events[:10] if getattr(e, "text", "")))
        if getattr(plan, "locations", None):
            lines.append("Locations: " + ", ".join(plan.locations[:6]))
    return _clip("\n".join(lines), limit)


def _earlier_chapters(project: Any, chapter: Any, limit: int, count: int = 3) -> str:
    """What happened before: summaries of the previous few chapters."""
    if project is None or chapter is None or not hasattr(project, "find_chapter_with_scope"):
        return ""
    try:
        scope, found = project.find_chapter_with_scope(chapter.id)
        manuscript = project.get_manuscript_for(scope) if found is not None else None
        chapters = list(manuscript.chapters) if manuscript is not None else []
        index = next(i for i, c in enumerate(chapters) if c.id == chapter.id)
    except Exception:
        return ""
    lines = []
    for ch in chapters[max(0, index - count):index]:
        plan = getattr(ch, "planning", None)
        summary = ((getattr(plan, "description", "") or getattr(plan, "outline", "") or "")
                   if plan is not None else "").strip()
        if summary:
            lines.append(f"Chapter {ch.number} — {ch.title}: {summary[:400]}")
    return _clip("\n".join(lines), limit)


def _characters(project: Any, chapter: Any, window: str, passage: str, limit: int) -> str:
    from src.ai.canon_index import character_name_variants, find_mentions, format_character_profile
    people = list(getattr(project, "characters", None) or [])
    if not people:
        return ""
    in_passage = find_mentions(passage, character_name_variants(people))
    nearby = find_mentions(window, character_name_variants(people))
    plan = getattr(chapter, "planning", None)
    pov = (getattr(plan, "pov_character", "") or "").strip().lower()
    featured = {n.strip().lower() for n in getattr(plan, "characters_featured", None) or []}

    def rank(c):
        name = c.name.lower()
        return (c.name not in in_passage, name != pov, c.name not in nearby,
                name not in featured and c.id.lower() not in featured)

    chosen = [c for c in sorted(people, key=rank)
              if c.name in in_passage or c.name in nearby or c.name.lower() == pov][:4]
    number = getattr(chapter, "number", 0) or 0
    blocks, used = [], 0
    for c in chosen:
        block = format_character_profile(c, number, max_field=200)
        if c.name.lower() == pov:
            block = block.replace("\n", " (point-of-view character)\n", 1)
        if used + len(block) > limit:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _world(project: Any, window: str, passage: str, limit: int) -> str:
    from src.ai.canon_index import collect_world_entities, find_mentions, world_name_variants
    entities = collect_world_entities(getattr(project, "worldbuilding", None))
    if not entities:
        return ""
    in_passage = find_mentions(passage, world_name_variants(entities))
    nearby = find_mentions(window, world_name_variants(entities))
    hits = sorted((e for e in entities if e.name in in_passage or e.name in nearby),
                  key=lambda e: e.name not in in_passage)
    lines, used = [], 0
    for e in hits[:10]:
        line = f"- {e.label}: {e.summary}" if e.summary else f"- {e.label}"
        if used + len(line) > limit:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def build_context(project: Any, chapter: Any, text: str, start: int, end: int, *,
                  compact: bool = False,
                  related: Optional[Callable[[str], str]] = None,
                  voice: Any = None, examples: str = "") -> PassageContext:
    """Everything the model needs to judge ``text[start:end]``.

    ``compact`` trims each section for local models with small context
    windows; ``related(query)`` adds project search results; ``voice`` is
    the author's measured ``WriterVoice``; ``examples`` their rated rewrites.
    """
    scale = 0.55 if compact else 1.0
    size = lambda n: int(n * scale)
    passage = text[start:end]
    before, after = text[:start], text[end:]
    window = before[-1500:] + "\n" + passage + "\n" + after[:800]
    ctx = PassageContext(
        passage=passage,
        before=_clip(before, size(3000), from_end=True),
        after=_clip(after, size(1200)),
        chapter=_chapter_notes(chapter, size(1200)),
    )
    if project is not None:
        planning = getattr(project, "story_planning", None)
        ctx.story_outline = _story_outline(planning, size(1500))
        ctx.plot = _plot(planning, size(1500))
        ctx.characters = _characters(project, chapter, window, passage, size(2400))
        ctx.world = _world(project, window, passage, size(1400))
        ctx.earlier = _earlier_chapters(project, chapter, size(1200))
        from src.ai.rewrite_quality import known_names_for
        ctx.known_names = known_names_for(project)
    if voice is not None and not getattr(voice, "is_empty", True):
        ctx.voice = voice.to_prompt()
    ctx.examples = _clip(examples, size(1500))
    if related is not None:
        try:
            ctx.related = _clip(related(window[-1200:]), size(1500))
        except Exception as e:
            print(f"[suggestions] project search unavailable: {e}")
    ctx.observations = _observations(ctx, before)
    if '"' in passage or "“" in passage:
        from src.ai.dialogue_speakers import attribute_lines
        people = [c.name for c in getattr(project, "characters", None) or []]
        # Read from the paragraph start so beats and earlier tags count.
        para_start = text.rfind("\n", 0, start) + 1
        lines = attribute_lines(text[para_start:end], people)
        skip = len(attribute_lines(text[para_start:start], people))
        ctx.speakers = "\n".join(f"- {l.label()}" for l in lines[skip:][:12])
    return ctx


def _observations(ctx: PassageContext, before: str) -> List[str]:
    """Things a quick scan can see for sure: sentences of the passage that
    retell what the chapter already said."""
    from src.ai.rewrite_quality import restated_sentences, split_sentences
    sents = split_sentences(ctx.passage)
    out = []
    for sent, earlier in restated_sentences(ctx.passage, before[-2500:]):
        n = sents.index(sent) + 1 if sent in sents else 0
        out.append(f"Sentence [{n}] largely restates something already written just before "
                   f"the passage: “{earlier.strip()}”")
    return out


# ── Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an experienced fiction editor. You judge a passage against the author's "
    "own story bible — characters, world, plot and outline — and the chapter around it, "
    "then rewrite it. You are specific and honest, quote the passage when you point at "
    "something, and never pad. Each rewrite keeps the author's point of view, tense and "
    "voice and stays consistent with the story bible. You only ever rewrite the marked "
    "passage: the text around it is already written and stays exactly as it is.")

# One approach per suggestion: small models follow a named angle far more
# reliably than "make them different".
ANGLES = [
    ("tightened", "the same content, every word earning its place"),
    ("restructured", "rebuilt sentence by sentence: new structure and rhythm, a different "
                     "opening, combined or split sentences"),
    ("new focus", "the moment told through a character's perception or one concrete "
                  "sensory detail, with a different opening"),
    ("expanded", "slowed down with one or two vivid beats of action or detail from the scene"),
]

_REWRITE_RULES = (
    "Rules for the rewrites:\n"
    "- Each suggestion follows its own approach (named in its heading), so the three read "
    "clearly differently. Don't just swap synonyms. Fixing the order comes first, even if "
    "that means two suggestions start with the same event.\n"
    "- Add no new facts: no objects, weapons, injuries, people, places or events that "
    "aren't in the passage, the scene or the notes. You may cut, reorder and sharpen what "
    "is there, and add sensory detail that fits the scene.\n"
    "- Keep each line of dialogue with the speaker given above.\n")

_SCOPE_RULES = (
    "Your rewrites REPLACE ONLY the text between ⟦PASSAGE START⟧ and ⟦PASSAGE END⟧. "
    "They must pick up exactly where the text before the passage leaves off and lead into "
    "the text after it. Never retell, summarise or rephrase anything that is already "
    "written before the passage (it stays on the page), and don't jump ahead to what "
    "happens after it.")


def build_prompt(ctx: PassageContext, focus: str = "") -> str:
    parts = []
    for title, body in ctx.sections():
        if body.strip():
            parts.append(f"=== {title} ===\n{body.strip()}")
    parts.append("=== THE SCENE (already written — the passage to critique is marked) ===\n"
                 + ctx.scene())
    parts.append("=== PASSAGE TO CRITIQUE, SENTENCE BY SENTENCE ===\n" + ctx.numbered_passage())
    if ctx.speakers:
        parts.append("=== WHO SPEAKS EACH LINE (from the dialogue tags — trust this; a name "
                     "inside the quotes is who is being spoken to) ===\n" + ctx.speakers)
    if ctx.observations:
        parts.append("=== ALREADY NOTICED (confirm and include these) ===\n"
                     + "\n".join(f"- {o}" for o in ctx.observations))
    if focus.strip():
        parts.append(f"=== THE AUTHOR WANTS YOU TO FOCUS ON ===\n{focus.strip()}")
    parts.append(
        "Critique ONLY the passage. Judge it on:\n"
        "- ORDER AND FLOW: is everything in the right sequence? Check that causes come "
        "before effects, that a character reacts after (not before) what they react to, "
        "that actions happen in a physically possible order, that information isn't used "
        "before it is revealed, that nothing repeats what the text before already said, "
        "and that the passage connects to the text before and after it. Refer to "
        "sentences by number, e.g. \"[3] should come before [2]\".\n"
        "- Consistency with the characters (personality, voice, motivation, arc), the "
        "worldbuilding, the plot and the story outline.\n"
        "- The prose: clarity, rhythm, showing vs telling, tension. The author's measured "
        "voice gives ranges, not rules — don't fault a sentence only for its length.\n\n"
        + _SCOPE_RULES + "\n\n" + _REWRITE_RULES + "- " + _avoid_line() + "\n\n"
        "Answer in exactly this format:\n\n"
        "WHAT WORKS:\n- <a specific strength>\n- <another>\n\n"
        "WHAT DOESN'T WORK:\n- <a specific problem and why>\n- <another>\n\n"
        "ORDER AND FLOW:\n- <what's out of order, repeated or disconnected, by sentence "
        "number — or \"In order.\" if the sequence is right>\n\n"
        + "".join(f"SUGGESTION {i} ({name}):\n<a complete rewrite — {how}>\n"
                  f"WHY: <one sentence>\n\n"
                  for i, (name, how) in enumerate(ANGLES[:NUM_SUGGESTIONS], 1)) +
        "Each suggestion replaces the whole passage, so write it in full, about the same "
        "length unless length is the problem (the expanded one may run a little longer). If "
        "anything is out of order, every suggestion must fix the order.")
    return "\n\n".join(parts)


def _avoid_line() -> str:
    from src.ai.rewrite_quality import avoid_phrases, avoid_prompt
    return (avoid_prompt(avoid_phrases()) + " (This list is for your rewrites — only "
            "criticise the passage for a phrase that really is a cliché.)")


def _angles_for(count: int, used: List[str]) -> List[Tuple[str, str]]:
    fresh = [a for a in ANGLES if a[0] not in used]
    return (fresh + ANGLES)[:count]


def build_more_prompt(ctx: PassageContext, have: List["Suggestion"], wanted: int) -> str:
    seen = "\n\n".join(f"(already suggested)\n{s.text}" for s in have)
    return ("=== THE SCENE (the passage is marked) ===\n" + ctx.scene(1500) + "\n\n"
            + (f"=== EXISTING REWRITES ===\n{seen}\n\n" if seen else "")
            + f"{_SCOPE_RULES}\n\n{_REWRITE_RULES}- {_avoid_line()}\n\n"
              f"Write {wanted} more rewrite(s) of the marked passage, "
              f"each different from the existing ones, keeping the same point of view, tense "
              f"and voice. Format:\n\n"
            + "\n\n".join(f"SUGGESTION {i + 1} ({name}):\n<the rewrite — {how}>\n"
                            f"WHY: <one sentence>"
                            for i, (name, how) in enumerate(
                                _angles_for(wanted, [s.angle for s in have]))))


# ── Output parsing ───────────────────────────────────────────────────

@dataclass
class Suggestion:
    text: str
    why: str = ""
    notes: List[str] = field(default_factory=list)     # problems the checks found
    voice_fit: Optional[float] = None
    angle: str = ""                                    # e.g. "tightened"


@dataclass
class PassageCritique:
    works: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    order: List[str] = field(default_factory=list)      # sequence / repetition / flow
    suggestions: List[Suggestion] = field(default_factory=list)
    raw: str = ""

    @property
    def empty(self) -> bool:
        return not (self.works or self.issues or self.order or self.suggestions)


_HEAD = r"^\s*(?:#+\s*)?(?:\*\*|__)?\s*"
_HEAD_TAIL = r"(?:\s*\([^)\n]*\))?\s*(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*$"
_WORKS_RX = re.compile(_HEAD + r"(?:what\s+works|works|strengths?)" + _HEAD_TAIL, re.I | re.M)
_ISSUES_RX = re.compile(
    _HEAD + r"(?:what\s+(?:doesn['’]?t|does\s+not|isn['’]?t)\s+work(?:ing)?|doesn['’]?t\s+work"
    r"|weaknesses|issues|problems)" + _HEAD_TAIL, re.I | re.M)
_ORDER_RX = re.compile(
    _HEAD + r"(?:order(?:\s*(?:and|&|/)\s*flow)?|sequence|flow(?:\s*(?:and|&|/)\s*order)?"
    r"|order\s+of\s+events)" + _HEAD_TAIL, re.I | re.M)
_SUGGESTION_RX = re.compile(
    _HEAD + r"(?:suggestion|option|version|rewrite|alternative)\s*#?\s*(\d)\b\s*(?:\*\*|__)?"
    r"\s*(?:\((?P<angle>[^)\n]{0,60})\))?\s*(?:\*\*|__)?\s*(?:[:.)\-–—]|$)"
    r"\s*(?:\*\*|__)?\s*(?P<rest>[^\n]*)$",
    re.I | re.M)
_WHY_RX = re.compile(r"^\s*(?:\*\*|__)?\s*(?:why|rationale|reason|why it works)\b[^:\n]*:\s*"
                     r"(?:\*\*|__)?\s*", re.I | re.M)
_BULLET_RX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _bullets(block: str) -> List[str]:
    items, current = [], None
    for line in block.splitlines():
        if not line.strip():
            current = None
            continue
        if _BULLET_RX.match(line) or current is None:
            current = _BULLET_RX.sub("", line).strip().strip("*_").strip()
            if current:
                items.append(current)
            else:
                current = None
        else:
            items[-1] += " " + line.strip()
    return [i for i in items if i.lower() not in ("none", "n/a", "nothing")]


def _clean_rewrite(text: str) -> str:
    text = text.strip().strip("`").strip()
    lines = [l for l in text.splitlines() if l.strip() not in ("---", "***")]
    text = "\n".join(lines).strip()
    if len(text) > 1 and text[0] in "\"“" and text[-1] in "\"”" and text.count(text[0]) == 2:
        text = text[1:-1].strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_critique(raw: str) -> PassageCritique:
    from src.ai.output_sanitizer import strip_meta_tokens
    text = strip_meta_tokens(raw or "")
    out = PassageCritique(raw=text)
    marks = sorted(
        [(m.start(), m.end(), "works", None) for m in _WORKS_RX.finditer(text)]
        + [(m.start(), m.end(), "issues", None) for m in _ISSUES_RX.finditer(text)]
        + [(m.start(), m.end(), "order", None) for m in _ORDER_RX.finditer(text)]
        + [(m.start(), m.end(), "suggestion", m) for m in _SUGGESTION_RX.finditer(text)],
        key=lambda x: x[0])
    for i, (s, e, kind, m) in enumerate(marks):
        body = text[e:marks[i + 1][0] if i + 1 < len(marks) else len(text)]
        if kind == "works":
            out.works += _bullets(body)
        elif kind == "issues":
            out.issues += _bullets(body)
        elif kind == "order":
            out.order += _bullets(body)
        else:
            rest = (m.group("rest") or "").strip()
            body = rest + body
            why = ""
            w = _WHY_RX.search(body)
            if w:
                why = " ".join(body[w.end():].split())
                body = body[:w.start()]
            rewrite = _clean_rewrite(body)
            if rewrite:
                angle = (m.group("angle") or "").strip().lower()
                out.suggestions.append(Suggestion(rewrite, why.strip("*_ "), angle=angle))
    return out


# ── Running it ───────────────────────────────────────────────────────

def build_fix_prompt(ctx: PassageContext, failed: List[Tuple["Suggestion", List[str]]],
                     keep: Optional[List["Suggestion"]] = None,
                     slots: Optional[List[int]] = None) -> str:
    """``slots``: the suggestion numbers (0-based) being replaced, so each
    replacement keeps that slot's approach."""
    problems = "\n".join(f"- A rewrite that {'; '.join(p)}" for _, p in failed)
    kept = "\n\n".join(s.text for s in keep or [])
    angles = ([ANGLES[i % len(ANGLES)] for i in slots] if slots
              else _angles_for(len(failed), [s.angle for s in keep or []]))
    return ("=== THE SCENE (the passage is marked) ===\n" + ctx.scene(1500) + "\n\n"
            + (f"=== WHO SPEAKS EACH LINE ===\n{ctx.speakers}\n\n" if ctx.speakers else "")
            + (f"=== REWRITES ALREADY KEPT (yours must differ from these in opening and "
               f"approach) ===\n{kept}\n\n" if kept else "")
            + f"{_SCOPE_RULES}\n\n{_REWRITE_RULES}- {_avoid_line()}\n\n"
            + (f"=== {ctx.voice}\n\n" if ctx.voice else "")
            + (f"=== NAMES IN THE STORY ===\n{', '.join(ctx.known_names[:40])}\n\n"
               if ctx.known_names else "")
            + f"Earlier rewrites were rejected because of these problems:\n{problems}\n\n"
              f"Write {len(failed)} new rewrite(s) of the passage that avoid them: same point "
              f"of view and tense, names spelled as in the story, similar length, and nothing "
              f"retold from the surrounding text. Format:\n\n"
            + "\n\n".join(f"SUGGESTION {i + 1} ({name}):\n<the rewrite — {how}>\n"
                            f"WHY: <one sentence>" for i, (name, how) in enumerate(angles)))


def _check_all(ctx: PassageContext, suggestions: List["Suggestion"], voice: Any, focus: str):
    from src.ai.rewrite_quality import check_rewrite
    checks = [check_rewrite(ctx.passage, s.text, voice=voice, known_names=ctx.known_names,
                            before=ctx.before, after=ctx.after, focus=focus,
                            notes=ctx.notes_text())
              for s in suggestions]
    _mark_twins(suggestions, checks)
    return checks


def _mark_twins(suggestions: List["Suggestion"], checks) -> None:
    """Near-identical narration needs replacing; a shared opening is a note."""
    from src.ai.rewrite_quality import (SAME_OPENING_PREFIX, TWIN_PREFIX, same_openings,
                                        twin_problems)
    texts = [s.text for s in suggestions]
    for check in checks:
        check.serious = [p for p in check.serious if not p.startswith(TWIN_PREFIX)]
        check.minor = [p for p in check.minor if not p.startswith(SAME_OPENING_PREFIX)]
    for i, problem in twin_problems(texts).items():
        checks[i].serious.append(problem)
    for i, note in same_openings(texts).items():
        if checks[i].ok:
            checks[i].minor.append(note)


def critique_passage(llm: Any, ctx: PassageContext, focus: str = "",
                     progress: Optional[Callable[[str], None]] = None,
                     voice: Any = None) -> PassageCritique:
    """Ask the model for the critique; top up if it gave fewer than three
    rewrites (common with small local models); replace rewrites that fail
    the quality checks once; best rewrite first."""
    say = progress or (lambda _msg: None)
    say("Reading the passage against your story notes…")
    raw = llm.generate_text(build_prompt(ctx, focus), SYSTEM_PROMPT,
                            max_tokens=1800, temperature=0.7)
    result = parse_critique(raw)
    wanted = NUM_SUGGESTIONS - len(result.suggestions)
    if wanted > 0 and not result.empty:
        say("Writing more suggestions…")
        extra = parse_critique(llm.generate_text(
            build_more_prompt(ctx, result.suggestions, wanted), SYSTEM_PROMPT,
            max_tokens=1200, temperature=0.8))
        result.suggestions += extra.suggestions[:wanted]
    passage = " ".join(ctx.passage.split())
    result.suggestions = [s for s in result.suggestions
                          if " ".join(s.text.split()) != passage][:NUM_SUGGESTIONS]
    # What the scan found is reported even if the model skipped it.
    for note in ctx.observations:
        if not any(note[:14] in o or "restat" in o.lower() or "repeat" in o.lower()
                   for o in result.order):
            result.order.append(note)
    if not result.suggestions:
        return result

    checks = _check_all(ctx, result.suggestions, voice, focus)
    failed = [(s, c.serious) for s, c in zip(result.suggestions, checks) if not c.ok]
    if failed:
        say("Replacing weak suggestions…")
        try:
            keep = [s for s, c in zip(result.suggestions, checks) if c.ok]
            slots = [i for i, c in enumerate(checks) if not c.ok]
            fresh = parse_critique(llm.generate_text(
                build_fix_prompt(ctx, failed, keep, slots), SYSTEM_PROMPT,
                max_tokens=1200, temperature=0.8))
            fresh_checks = _check_all(ctx, fresh.suggestions, voice, focus)
            spare = sorted(zip(fresh.suggestions, fresh_checks), key=lambda sc: sc[1].rank())
            for i, check in enumerate(checks):
                if not check.ok and spare and spare[0][1].rank() < check.rank():
                    result.suggestions[i], checks[i] = spare.pop(0)
            # Replacements must not twin the suggestions kept alongside them.
            _mark_twins(result.suggestions, checks)
        except Exception as e:
            print(f"[suggestions] could not replace weak rewrites: {e}")

    for s, c in zip(result.suggestions, checks):
        s.notes, s.voice_fit = c.notes, c.voice_fit
    from src.ai.rewrite_quality import best_first
    result.suggestions = [result.suggestions[i] for i in best_first(result.suggestions, checks)]
    return result
