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

    def sections(self) -> List[Tuple[str, str]]:
        return [("STORY OUTLINE", self.story_outline), ("PLOT", self.plot),
                ("EARLIER CHAPTERS", self.earlier),
                ("THIS CHAPTER", self.chapter), ("CHARACTERS IN THIS PASSAGE", self.characters),
                ("WORLDBUILDING IN THIS PASSAGE", self.world),
                ("OTHER RELATED PROJECT NOTES", self.related),
                ("CHAPTER TEXT BEFORE THE PASSAGE", self.before),
                ("CHAPTER TEXT AFTER THE PASSAGE", self.after),
                ("THE AUTHOR'S VOICE", self.voice),
                ("THE AUTHOR'S TASTE", self.examples)]


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
    return ctx


# ── Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an experienced fiction editor. You judge a passage against the author's "
    "own story bible — characters, world, plot and outline — and the chapter around it, "
    "then rewrite it. You are specific and honest, quote the passage when you point at "
    "something, and never pad. Each rewrite keeps the author's point of view, tense and "
    "voice and stays consistent with the story bible.")


def build_prompt(ctx: PassageContext, focus: str = "") -> str:
    parts = []
    for title, body in ctx.sections():
        if body.strip():
            parts.append(f"=== {title} ===\n{body.strip()}")
    parts.append(f"=== PASSAGE TO CRITIQUE ===\n{ctx.passage.strip()}")
    if focus.strip():
        parts.append(f"=== THE AUTHOR WANTS YOU TO FOCUS ON ===\n{focus.strip()}")
    parts.append(
        "Critique ONLY the passage. Judge it on: consistency with the characters "
        "(personality, voice, motivation, where they are in their arc), the worldbuilding, "
        "the plot and story outline, and how well it flows from the text before it into "
        "the text after it — plus the prose itself (clarity, rhythm, showing vs telling, "
        "tension).\n\n"
        "Answer in exactly this format:\n\n"
        "WHAT WORKS:\n- <a specific strength>\n- <another>\n\n"
        "WHAT DOESN'T WORK:\n- <a specific problem and why>\n- <another>\n\n"
        "SUGGESTION 1:\n<a complete rewrite of the passage>\nWHY: <one sentence>\n\n"
        "SUGGESTION 2:\n<a different rewrite>\nWHY: <one sentence>\n\n"
        "SUGGESTION 3:\n<a third, different approach>\nWHY: <one sentence>\n\n"
        "Each suggestion replaces the whole passage, so write it in full, about the same "
        "length unless length is the problem. Do not repeat the text before or after it. "
        "Make the three suggestions genuinely different approaches.")
    return "\n\n".join(parts)


def build_more_prompt(ctx: PassageContext, have: List["Suggestion"], wanted: int) -> str:
    seen = "\n\n".join(f"(already suggested)\n{s.text}" for s in have)
    return (f"=== PASSAGE ===\n{ctx.passage.strip()}\n\n"
            + (f"=== EXISTING REWRITES ===\n{seen}\n\n" if seen else "")
            + (f"=== CHAPTER TEXT BEFORE ===\n{ctx.before[-1200:]}\n\n" if ctx.before else "")
            + f"Write {wanted} more rewrite(s) of the passage, each different from the "
              f"existing ones, keeping the same point of view, tense and voice. Format:\n\n"
            + "\n\n".join(f"SUGGESTION {i + 1}:\n<the rewrite>\nWHY: <one sentence>"
                          for i in range(wanted)))


# ── Output parsing ───────────────────────────────────────────────────

@dataclass
class Suggestion:
    text: str
    why: str = ""
    notes: List[str] = field(default_factory=list)     # problems the checks found
    voice_fit: Optional[float] = None


@dataclass
class PassageCritique:
    works: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    suggestions: List[Suggestion] = field(default_factory=list)
    raw: str = ""

    @property
    def empty(self) -> bool:
        return not (self.works or self.issues or self.suggestions)


_HEAD = r"^\s*(?:#+\s*)?(?:\*\*|__)?\s*"
_HEAD_TAIL = r"(?:\s*\([^)\n]*\))?\s*(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*$"
_WORKS_RX = re.compile(_HEAD + r"(?:what\s+works|works|strengths?)" + _HEAD_TAIL, re.I | re.M)
_ISSUES_RX = re.compile(
    _HEAD + r"(?:what\s+(?:doesn['’]?t|does\s+not|isn['’]?t)\s+work(?:ing)?|doesn['’]?t\s+work"
    r"|weaknesses|issues|problems)" + _HEAD_TAIL, re.I | re.M)
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
        + [(m.start(), m.end(), "suggestion", m) for m in _SUGGESTION_RX.finditer(text)],
        key=lambda x: x[0])
    for i, (s, e, kind, m) in enumerate(marks):
        body = text[e:marks[i + 1][0] if i + 1 < len(marks) else len(text)]
        if kind == "works":
            out.works += _bullets(body)
        elif kind == "issues":
            out.issues += _bullets(body)
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
                out.suggestions.append(Suggestion(rewrite, why.strip("*_ ")))
    return out


# ── Running it ───────────────────────────────────────────────────────

def build_fix_prompt(ctx: PassageContext, failed: List[Tuple["Suggestion", List[str]]]) -> str:
    problems = "\n".join(f"- A rewrite that {'; '.join(p)}" for _, p in failed)
    return (f"=== PASSAGE ===\n{ctx.passage.strip()}\n\n"
            + (f"=== CHAPTER TEXT BEFORE ===\n{ctx.before[-1200:]}\n\n" if ctx.before else "")
            + (f"=== {ctx.voice}\n\n" if ctx.voice else "")
            + (f"=== NAMES IN THE STORY ===\n{', '.join(ctx.known_names[:40])}\n\n"
               if ctx.known_names else "")
            + f"Earlier rewrites were rejected because of these problems:\n{problems}\n\n"
              f"Write {len(failed)} new rewrite(s) of the passage that avoid them: same point "
              f"of view and tense, names spelled as in the story, similar length, and nothing "
              f"copied from the surrounding text. Format:\n\n"
            + "\n\n".join(f"SUGGESTION {i + 1}:\n<the rewrite>\nWHY: <one sentence>"
                            for i in range(len(failed))))


def _check_all(ctx: PassageContext, suggestions: List["Suggestion"], voice: Any, focus: str):
    from src.ai.rewrite_quality import check_rewrite
    return [check_rewrite(ctx.passage, s.text, voice=voice, known_names=ctx.known_names,
                          before=ctx.before, after=ctx.after, focus=focus)
            for s in suggestions]


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
    if not result.suggestions:
        return result

    checks = _check_all(ctx, result.suggestions, voice, focus)
    failed = [(s, c.serious) for s, c in zip(result.suggestions, checks) if not c.ok]
    if failed:
        say("Replacing weak suggestions…")
        try:
            fresh = parse_critique(llm.generate_text(
                build_fix_prompt(ctx, failed), SYSTEM_PROMPT, max_tokens=1200, temperature=0.7))
            fresh_checks = _check_all(ctx, fresh.suggestions, voice, focus)
            spare = sorted(zip(fresh.suggestions, fresh_checks), key=lambda sc: sc[1].rank())
            for i, check in enumerate(checks):
                if not check.ok and spare and spare[0][1].rank() < check.rank():
                    result.suggestions[i], checks[i] = spare.pop(0)
        except Exception as e:
            print(f"[suggestions] could not replace weak rewrites: {e}")

    for s, c in zip(result.suggestions, checks):
        s.notes, s.voice_fit = c.notes, c.voice_fit
    from src.ai.rewrite_quality import best_first
    result.suggestions = [result.suggestions[i] for i in best_first(result.suggestions, checks)]
    return result
