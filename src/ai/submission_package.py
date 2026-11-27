"""The submission package (piece 9.3): a synopsis, a query letter, a blurb,
and who the book is for with where it sits among comparable titles.

* **Without a model** each document is a filled-in template built from what
  the writer has already set down: the plot (the plot structure's stages and
  events, the main plot, subplots, themes, tensions and their stakes), the
  characters (want, need, the lie they believe), the chapter summaries, the
  story memory, the prose profile and the publishing goal. Whatever is
  missing is left as a [bracketed] prompt, so the template is always
  complete and says what to add. This is the full, working tier.
* **With a model** (the one Rephrase uses: ``word_suggest.get_llm``) the
  same facts, the story memory and the writer's measured voice go into one
  short call per document. The model drafts; the writer edits. Calls run on
  a worker thread (the screen's job) and an on-device model is only used
  under ``mlx_utils.MLX_GENERATE_LOCK``, like every other feature.

**Comparable titles are honest.** Candidates come from the app's genre list
(``src/data/genres.py``): published, public-domain books. The writer ticks
the ones that fit; the app never claims a book is comparable, and knows
nothing about recent titles or sales. The model is given only the titles
the writer chose and told to name no others.

**Where it sits** is information only: the length beside what is typical
(``publishing_goal``), and sentence length and dialogue share beside
published books in the genre (P.3's baseline when it is built, else the
Critique's rules of thumb, labelled as such).

No Qt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

LABELS = {"synopsis": "Synopsis", "query": "Query letter", "blurb": "Blurb",
          "audience": "Readers and comps"}
DOCS = tuple(LABELS)
STAGES = ("exposition", "rising_action", "climax", "falling_action", "resolution")
COMPS_HONESTY = (
    "Candidates from the app's genre list: published, public-domain classics. Tick the "
    "ones your book shares something with; the app doesn't judge whether a book is "
    "comparable. Agents usually want titles from the last few years, which the app can't "
    "know, so add your own.")
NOT_KNOWN = ("The app knows nothing about sales, recent titles or what an agent will take; "
             "these are measures of the text only.")


# ── Facts: what the writer has already set down ─────────────────────────

def _s(x: Any) -> str:
    return " ".join(str(x or "").split()).strip()


def _sentence(text: str) -> str:
    t = _s(text)
    if not t:
        return ""
    return t if t[-1] in ".!?…\"”’)" else t + "."


def _first_sentence(text: str) -> str:
    t = _s(text)
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m else t)


def _manuscript(project: Any, scope: Optional[str]):
    try:
        ms = project.get_manuscript_for(scope)
        if ms is not None:
            return ms
    except Exception:
        pass
    return getattr(project, "manuscript", None)


def _role(c: Any) -> str:
    return _s(getattr(c, "character_type", "")).lower()


def _event_line(e: Any) -> str:
    out = _sentence(getattr(e, "description", "") or getattr(e, "title", ""))
    outcome = _sentence(getattr(e, "outcome", ""))
    return f"{out} {outcome}".strip()


def facts(project: Any, scope: Optional[str] = None,
          chosen_comps: Sequence[str] = ()) -> Dict[str, Any]:
    """Everything the templates and prompts use, read from the project.
    Never raises on a sparse project: missing parts are empty."""
    from src.data import publishing_goal as pg
    goal = pg.publishing_goal(project, scope)
    ms = _manuscript(project, scope)
    title = _s(getattr(ms, "title", ""))
    if not title or title == "Untitled Manuscript":
        title = _s(getattr(project, "name", "")) or "[Title]"
    contact: Dict[str, str] = {}
    try:
        from src.data import writer_contact as wc
        contact = wc.load()
        byline = wc.byline(getattr(ms, "author", ""), contact)
    except Exception:
        byline = _s(getattr(ms, "author", ""))
    chars = list(getattr(project, "characters", None) or [])
    hero = next((c for c in chars if _role(c) == "protagonist"), None) \
        or next((c for c in chars if _role(c) == "major"), None)
    villain = next((c for c in chars if _role(c) == "antagonist"), None)
    sp = getattr(project, "story_planning", None)
    pyramid = getattr(sp, "freytag_pyramid", None)
    stage_text = {st: _s(getattr(pyramid, st, "")) for st in STAGES}
    events: Dict[str, List[str]] = {st: [] for st in STAGES}
    order = {st: i for i, st in enumerate(STAGES)}
    for e in sorted(getattr(pyramid, "events", None) or [],
                    key=lambda e: (getattr(e, "act", 1), order.get(getattr(e, "stage", ""), 1),
                                   getattr(e, "sort_order", 0))):
        line = _event_line(e)
        if line:
            events.setdefault(getattr(e, "stage", "rising_action"), []).append(line)
    # Each theme as its short label; the argument the story makes, when given.
    themes = [_s(getattr(t, "title", "")) for t in getattr(sp, "theme_details", None) or []]
    themes += [_s(t) for t in getattr(sp, "themes", None) or []]
    themes = [t for t in dict.fromkeys(themes) if t]
    statements = [_sentence(getattr(t, "statement", ""))
                  for t in getattr(sp, "theme_details", None) or [] if _s(getattr(t, "statement", ""))]
    stakes = [_sentence(getattr(t, "stakes", "")) for t in getattr(sp, "tensions", None) or []
              if _s(getattr(t, "stakes", ""))]
    subplots = [(_s(getattr(x, "title", "")), _sentence(getattr(x, "description", "")))
                for x in getattr(sp, "subplots", None) or []
                if _s(getattr(x, "status", "active")) != "abandoned" and _s(getattr(x, "title", ""))]
    chapters = []
    for ch in getattr(ms, "chapters", None) or []:
        desc = _s(getattr(getattr(ch, "planning", None), "description", ""))
        if desc:
            chapters.append(_sentence(desc))
    memory = []
    try:
        from src.ai import story_memory
        active = story_memory.entries(project)
        memory = [_sentence(e.text) for e in sorted(active, key=lambda e: not e.pinned)][:8]
    except Exception:
        pass
    pp = getattr(project, "prose_profile", None)
    return {
        "title": title, "byline": byline, "contact": contact,
        "genre": goal.genre, "genre_label": goal.genre_label, "kind": goal.kind,
        "route": goal.route, "words": goal.words, "length_note": goal.length_note,
        "hero": _person(hero), "villain": _person(villain),
        "main_plot": _s(getattr(sp, "main_plot", "")),
        "description": _s(getattr(project, "description", "")),
        "stages": stage_text, "events": events, "themes": themes, "statements": statements, "stakes": stakes,
        "subplots": subplots, "chapters": chapters, "memory": memory,
        "tone": _s(getattr(pp, "tone", "")), "style": _s(getattr(pp, "style", "")),
        "comps": [c for c in chosen_comps if _s(c)],
    }


def _person(c: Any) -> Dict[str, str]:
    if c is None:
        return {}
    return {k: _s(getattr(c, k, "")) for k in
            ("name", "want", "need", "lie_they_believe", "ghost", "motivations", "fears",
             "personality", "character_arc")}


# ── The templates (no model) ────────────────────────────────────────────

def _words_about(n: int) -> str:
    if n >= 1000:
        return f"about {int(round(n, -3)):,} words"
    return f"{n:,} words" if n else "[word count] words"


def _genre_phrase(f: Dict[str, Any]) -> str:
    g = (f.get("genre_label") or "").lower()
    return f"{g} {f['kind']}" if g else f"[genre] {f['kind']}"


def _hero_name(f: Dict[str, Any]) -> str:
    return f["hero"].get("name") or "[Your main character]"


def _who(f: Dict[str, Any]) -> str:
    """The main character's name inside a [bracketed] prompt."""
    return f["hero"].get("name") or "your main character"


def _part(text: str, events: Sequence[str]) -> str:
    return " ".join(x for x in [_sentence(text)] + list(events) if x)


def _chapters_third(f: Dict[str, Any], which: int) -> str:
    ch = f["chapters"]
    if not ch:
        return ""
    n = len(ch)
    cuts = [0, max(1, n // 3), max(1, 2 * n // 3), n]
    return " ".join(ch[cuts[which]:cuts[which + 1]])


def synopsis(f: Dict[str, Any]) -> str:
    name = _hero_name(f)
    hero = f["hero"]
    st, ev = f["stages"], f["events"]
    plot_from_plan = any(st.values()) or any(ev.values())

    opening = []
    if f["main_plot"]:
        opening.append(_sentence(f["main_plot"]))
    if hero.get("want"):
        opening.append(f"{name} wants {hero['want'].rstrip('.')}.")
    if hero.get("lie_they_believe"):
        opening.append(f"{name} believes {hero['lie_they_believe'].rstrip('.')}.")
    setup = _part(st["exposition"], ev["exposition"]) or (
        "" if plot_from_plan else _chapters_third(f, 0))
    if setup:
        opening.append(setup)
    if not opening:
        who = _who(f)
        opening.append(f"[Who {who} is, where the story starts and what {who} wants.]")

    middle = _part(st["rising_action"], ev["rising_action"]) or (
        "" if plot_from_plan else _chapters_third(f, 1))
    middle = middle or f"[What goes wrong, and how {_who(f)} tries to put it right.]"
    for title, desc in f["subplots"][:2]:
        middle += f" Alongside runs “{title}”" + (f": {desc}" if desc else ".")

    climax = _part(st["climax"], ev["climax"]) or (
        "" if plot_from_plan else _chapters_third(f, 2))
    climax = climax or f"[The crisis: the moment {_who(f)} must choose, and the choice.]"

    ending = _part(" ".join(x for x in (st["falling_action"], st["resolution"]) if x),
                   ev["falling_action"] + ev["resolution"])
    if hero.get("need"):
        ending += f" {name} comes to see that {_lower_first(hero['need']).rstrip('.')}."
    ending = ending.strip() or (f"[How it ends, and how {_who(f)} has changed. A synopsis "
                                "gives away the ending.]")
    paras = [f"{f['title']}", f"Synopsis · {_genre_phrase(f)}, {_words_about(f['words'])}",
             " ".join(opening), middle.strip(), climax, ending]
    if f["themes"]:
        paras.append(f"At its heart, the story is about {_lower_first(f['themes'][0]).rstrip('.')}."
                     + (f" {f['statements'][0]}" if f["statements"] else ""))
    return "\n\n".join(paras)


def _lower_first(t: str) -> str:
    return t[:1].lower() + t[1:] if t and not t[:2].isupper() else t


def comps_sentence(f: Dict[str, Any]) -> str:
    comps = [c.replace(" — ", " by ") for c in f["comps"]]
    if not comps:
        return "[Two or three recent comparable titles: “It will appeal to readers of …”.]"
    joined = comps[0] if len(comps) == 1 else ", ".join(comps[:-1]) + " and " + comps[-1]
    return f"It will appeal to readers of {joined}."


def query(f: Dict[str, Any]) -> str:
    name = _hero_name(f)
    hero = f["hero"]
    hook = _first_sentence(f["main_plot"] or f["description"]) or \
        "[One or two sentences that hook: who, what they want, what stands in the way.]"
    body = []
    if hero.get("want"):
        body.append(f"{name} wants {hero['want'].rstrip('.')}.")
    villain = f["villain"].get("name")
    if villain:
        body.append(f"But {villain} stands in the way.")
    first_turn = (f["events"]["rising_action"] or [""])[0] or _sentence(f["stages"]["rising_action"])
    if first_turn:
        body.append(first_turn)
    if f["stakes"]:
        body.append(f"If {name} fails, {_lower_first(f['stakes'][0])}")
    if not body:
        body.append(f"[{_who(f)[:1].upper() + _who(f)[1:]}, what they want, what stands in the way and what they stand to lose. "
                    "Don't give away the ending.]")
    details = (f"{f['title'].upper()} is a {_genre_phrase(f)}, complete at "
               f"{_words_about(f['words'])}. {comps_sentence(f)}")
    sign = [x for x in (f["byline"] or "[Your name]",
                        (f["contact"] or {}).get("email", ""),
                        (f["contact"] or {}).get("phone", "")) if x]
    from src.ai import query_address as qa          # 9.3 addendum: the chosen agent
    agent = f.get("agent") or {}
    paras = [qa.greeting(agent), hook, " ".join(body), details,
             qa.agent_line(agent, f["title"])]
    return "\n\n".join([p for p in paras if p] + [
        "[A few lines about you: why you wrote this book, and any writing credits.]",
        "Thank you for your time and consideration.",
        "Sincerely,\n" + "\n".join(sign)])


def blurb(f: Dict[str, Any]) -> str:
    name = _hero_name(f)
    hero = f["hero"]
    lines = []
    lead = _first_sentence(f["description"] or f["main_plot"])
    if lead:
        lines.append(lead)
    setup = _first_sentence(f["stages"]["exposition"]) or (f["events"]["exposition"] or [""])[0]
    if hero.get("want"):
        lines.append(f"{name} wants {hero['want'].rstrip('.')}." + (f" {setup}" if setup else ""))
    elif setup:
        lines.append(setup)
    turn = (f["events"]["rising_action"] or [""])[0] or _first_sentence(f["stages"]["rising_action"])
    if turn:
        lines.append(turn)
    if f["stakes"]:
        lines.append(f"If {name} fails, {_lower_first(f['stakes'][0])}" if hero.get("name")
                     else f["stakes"][0])
    if len(lines) < 2:
        lines.append(f"[{_who(f)[:1].upper() + _who(f)[1:]}, their world, and the trouble "
                     "that arrives.]")
    lines.append("[The question a reader will want answered. Don't give away the ending.]")
    return "\n\n".join([f"{f['title']}"] + lines)


NO_COMPS = "- [Tick candidates in the list, or add your own recent titles.]"


def audience(f: Dict[str, Any], placement_lines: Sequence[str] = ()) -> str:
    who = "Readers who"
    if f.get("genre"):
        from src.ai.genre_baseline import plural
        who = f"Readers of {plural(f['genre'])} who"
    feel = ", ".join(x for x in (f["tone"], f["style"]) if x)
    sentence = f"{who} enjoy {feel} stories." if feel else \
        f"{who} [what they enjoy: the mood, the pace, the kind of story]."
    if f["themes"]:
        tops = [_lower_first(t).rstrip(".") for t in f["themes"][:2]]
        sentence += " Drawn to stories about " + " and ".join(tops) + "."
    comps = "\n".join(f"- {c}" for c in f["comps"]) or NO_COMPS
    where = "\n".join(f"- {x}" for x in placement_lines) or f"- {f['length_note']}"
    return (f"Who it's for\n\n{sentence} [Age group: adult, new adult or young adult.]"
            f"\n\nComparable titles\n\n{comps}\n\nWhere it sits\n\n{where}")


TEMPLATES = {"synopsis": synopsis, "query": query, "blurb": blurb}


def template(kind: str, project: Any, scope: Optional[str] = None,
             chosen_comps: Sequence[str] = (), agent: Optional[Dict[str, str]] = None) -> str:
    """The filled-in template for one document. Never needs a model.
    ``agent``: who the query letter is addressed to (9.3 addendum)."""
    f = facts(project, scope, chosen_comps)
    f["agent"] = agent or {}
    if kind == "audience":
        return audience(f, placement(project, scope, f))
    return TEMPLATES[kind](f)


# ── Comparable titles and where the book sits ───────────────────────────

MAX_CANDIDATES = 12


def comp_candidates(project: Any) -> List[str]:
    """Candidates from the genre list, as "Title — Author": the book's genre
    first, then its close neighbours, at most ``MAX_CANDIDATES``. Empty
    when the genre is unknown."""
    from src.data import publishing_goal as pg
    from src.data import genres
    key, _ = pg.genre_of(project)
    if not key:
        return []
    keys = [key] + [k for k in genres.ancillaries_for(key) if k != key]
    return genres.comps_for(keys)[:MAX_CANDIDATES]


def _manuscript_text(project: Any, scope: Optional[str], limit_words: int = 60_000) -> str:
    """The manuscript's text, sampled evenly when it is long (enough for
    the averages, without slowing a long book)."""
    ms = _manuscript(project, scope)
    texts = [getattr(ch, "content", "") or "" for ch in getattr(ms, "chapters", None) or []]
    total = sum(len(t.split()) for t in texts)
    if total <= limit_words:
        return "\n\n".join(texts)
    share = limit_words / total
    out = []
    for t in texts:
        w = t.split()
        out.append(" ".join(w[: max(200, int(len(w) * share))]))
    return "\n\n".join(out)


def placement(project: Any, scope: Optional[str] = None,
              f: Optional[Dict[str, Any]] = None) -> List[str]:
    """Where the book sits, as plain lines: information, never a verdict."""
    f = f or facts(project, scope)
    lines = [f["length_note"]]
    text = _manuscript_text(project, scope)
    if len(text.split()) < 200:
        return lines + ["Too little text yet to compare sentences and dialogue."]
    try:
        from src.utils.writing_stats import ProWritingAnalyzer
        stats = ProWritingAnalyzer().analyze(text)
        values = {"sentence_length": float(stats.avg_sentence_length),
                  "dialogue_share": float(stats.dialogue_percentage)}
    except Exception as e:
        print(f"[submission] measures: {e}")
        return lines
    genre = f.get("genre") or ""
    from src.ai import genre_baseline as gb
    for measure, value in values.items():
        said = gb.line(genre, measure, value) if genre else ""
        measured = bool(said) and "too little data" not in said
        lines.append(said if measured else _rule_of_thumb(genre, measure, value))
    lines.append(NOT_KNOWN)
    return lines


def _rule_of_thumb(genre: str, measure: str, value: float) -> str:
    from src.ai.chapter_analysis_agent import resolve_genre_profile
    p = resolve_genre_profile(genre)
    lo, hi = p.avg_sentence_target if measure == "sentence_length" else p.dialog_pct_target
    if measure == "sentence_length":
        head, unit = f"Sentences average {value:.1f} words", " words"
    else:
        head, unit = f"Dialogue {value:.0f}% of the words", "%"
    return (f"{head}; the app's rule of thumb for {p.name.lower()}: {lo:g} to {hi:g}{unit} "
            "(not measured from published books).")


# ── With a model ─────────────────────────────────────────────────────────

SYSTEM = ("You help a novelist prepare a submission package. You write only from the facts "
          "you are given: never invent events, characters, titles, sales or awards. Where a "
          "fact is missing, keep the author's [bracketed] prompt as it is.")

ASK = {
    "synopsis": ("Write a one-page synopsis (400 to 550 words). Present tense, third person, "
                 "whatever the book's narration. Tell the whole story in order, including the "
                 "ending; follow the main character's arc; only the major events and "
                 "characters (names in full the first time)."),
    "query": ("Write a query letter of 250 to 350 words to a literary agent: a hook; the main "
              "character, what they want, what stands in the way and the stakes, without the "
              "ending; then the title, genre and word count exactly as given. For comparable "
              "titles use ONLY those listed under COMPARABLE TITLES, and none if none are "
              "listed (keep the bracketed prompt). Keep \"[A few lines about you …]\" for the "
              "author's bio and sign with the name given."),
    "blurb": ("Write back-cover copy of 120 to 200 words, in the book's voice and mood. Don't "
              "give away the ending; end on the question or the stakes."),
    "audience": ("In 60 to 120 words, say who this book is for: the readers, what they enjoy "
                 "and why this book will appeal to them. Name no books or authors."),
}


def build_prompt(kind: str, f: Dict[str, Any], filled: str, voice: str = "",
                 memory: str = "", compact: bool = False) -> str:
    limit = 2500 if compact else 7000
    comps = "\n".join(f"- {c}" for c in f["comps"]) or "- none chosen"
    parts = [f"THE BOOK: {f['title']}, a {_genre_phrase(f)} of {_words_about(f['words'])}, "
             f"by {f['byline'] or '[Your name]'}.",
             "THE AUTHOR'S FILLED-IN TEMPLATE (facts from their plan; [brackets] mark what "
             "they haven't filled in):\n" + filled[:limit]]
    if f["chapters"] and kind == "synopsis":
        parts.append("CHAPTER SUMMARIES, in order:\n"
                     + "\n".join(f"- {c}" for c in f["chapters"])[: (1500 if compact else 5000)])
    if memory:
        parts.append(memory[: (600 if compact else 2000)])
    parts.append("COMPARABLE TITLES the author chose:\n" + comps)
    if voice and kind != "audience":
        parts.append(voice[: (700 if compact else 2500)]
                     + "\n(Keep the author's word choice and mood; the tense and person "
                       "asked for below come first.)")
    parts.append(ASK[kind] + "\nAnswer with the text only.")
    return "\n\n".join(parts)


def _is_local(llm: Any) -> bool:
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        return bool(is_local_llm(llm))
    except Exception:
        return False


def generate(llm: Any, prompt: str, max_tokens: int) -> str:
    """One call. An on-device model is used under ``MLX_GENERATE_LOCK``,
    waiting for any other feature that is generating with it."""
    def call():
        return llm.generate_text(prompt, SYSTEM, max_tokens=max_tokens, temperature=0.5) or ""
    if _is_local(llm):
        from src.ai.mlx_utils import MLX_GENERATE_LOCK
        with MLX_GENERATE_LOCK:
            reply = call()
    else:
        reply = call()
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip() or "the model failed")
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply)
    except Exception:
        pass
    return reply.strip()


def draft(llm: Any, kind: str, project: Any, scope: Optional[str] = None,
          chosen_comps: Sequence[str] = (), agent: Optional[Dict[str, str]] = None
          ) -> Dict[str, Any]:
    """A model draft of one document: {"text", "model", "fit"}. Raises when
    the model fails or replies with nothing (the screen keeps what it had).
    ``agent``: who a query is addressed to (its greeting is the app's)."""
    f = facts(project, scope, chosen_comps)
    f["agent"] = agent or {}
    lines = placement(project, scope, f) if kind == "audience" else []
    filled = audience(f, lines) if kind == "audience" else TEMPLATES[kind](f)
    compact = _is_local(llm)
    voice, memory = "", ""
    fit_voice = None
    try:
        from src.ai.writer_voice import project_voice
        fit_voice = project_voice(project)
        voice = fit_voice.to_prompt()
    except Exception as e:
        print(f"[submission] voice: {e}")
    try:
        from src.ai import story_memory
        memory = story_memory.prompt_block(project, filled)
    except Exception:
        pass
    prompt = build_prompt(kind, f, filled, voice, memory, compact)
    reply = generate(llm, prompt, {"synopsis": 900, "query": 600, "blurb": 400,
                                   "audience": 300}[kind])
    if len(reply.split()) < 15:
        raise RuntimeError("the model's draft was too short to use")
    if kind == "audience":            # the facts are the app's, never the model's
        comps = "\n".join(f"- {c}" for c in f["comps"]) or NO_COMPS
        where = "\n".join(f"- {x}" for x in lines)
        reply = (f"Who it's for\n\n{reply}\n\nComparable titles\n\n{comps}"
                 f"\n\nWhere it sits\n\n{where}")
    if kind == "query" and agent and agent.get("name"):
        from src.ai import query_address as qa
        reply = qa.readdress(reply, None, agent, f["title"])["text"]
    fit = None
    if kind in ("query", "blurb") and fit_voice is not None:
        try:
            fit = fit_voice.fit_score(reply)
        except Exception:
            fit = None
    return {"text": reply, "model": str(getattr(llm, "model", "") or "model"), "fit": fit}


# ── Comps the writer chose, and export ───────────────────────────────────

def chosen_comps(chosen: Sequence[str], own: str = "") -> List[str]:
    """The ticked candidates, then the writer's own (separated by ";" or
    new lines), without repeats."""
    mine = [_s(x) for x in re.split(r"[;\n]", own or "")]
    return [c for c in dict.fromkeys(list(chosen) + mine) if c]


EXPORT_FORMATS = {"docx": "Word (*.docx)", "rtf": "Rich Text (*.rtf)",
                  "odt": "OpenDocument (*.odt)", "txt": "Plain text (*.txt)"}


def export(project: Any, scope: Optional[str], texts: Dict[str, str], path: str,
           fmt: str) -> bool:
    """Write the given documents (kind → text, in ``DOCS`` order) with the
    app's existing exporter. One document: no title page; the package: a
    title page with the book's title and byline."""
    from src.export.manuscript_exporter import ManuscriptExporter
    from src.models.project import Chapter, Manuscript
    f = facts(project, scope)
    kinds = [k for k in DOCS if (texts.get(k) or "").strip()]
    if not kinds:
        return False
    chapters = [Chapter(id=k, number=i + 1, title=LABELS[k], content=texts[k])
                for i, k in enumerate(kinds)]
    ms = Manuscript(title=f["title"], author=f["byline"])
    return ManuscriptExporter(ms).export_document(path, fmt, chapters,
                                                  title_page=len(kinds) > 1)
