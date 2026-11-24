"""An editor's whole-book questions, answered from the chapter digests.

A model outlines each chapter once (``chapter_digest``): its scenes, whose
point of view, what each scene changes, what is set up and paid off, and
how strongly the chapter pulls a reader on. These checks read that outline:

* per chapter: scenes that change nothing, point-of-view slips, and the
  reader's pull;
* across the book: setups never paid off (a model matches them), and
  characters who drop out of the story (counted from the text, no model).

Every finding is put as a question: the model's outline is one reader's
view, and the writer may intend what it found.
"""

import re

from src.ai.readiness import NOT_APPLICABLE, CheckContext, CheckOutput, Item, check


def _compact(llm) -> bool:
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        return bool(is_local_llm(llm))
    except Exception:
        return False


def _digest(ctx: CheckContext):
    """This chapter's digest (one request, shared by the three checks);
    None without a model."""
    if ctx.llm is None:
        return None

    def make():
        from src.ai import chapter_digest
        try:
            return chapter_digest.for_book(ctx.book).ensure(ctx.llm, ctx.chapter, ctx.text,
                                                            _compact(ctx.llm))
        except Exception as e:
            return e
    found = ctx._lazy("chapter_digest", make)
    if isinstance(found, Exception):
        raise found
    return found


NEEDS = CheckOutput(message="Needs the model to outline the chapter.")


@check(name="scene_purpose", stage="structure", label="Scenes that change nothing",
       needs_model=True, judge=False, version=1, weight=75,
       description="A scene after which nothing in the story is different: no decision, "
                   "discovery, reversal or shift between characters. A model outlines the "
                   "chapter and says what each scene changes. A quiet scene can be "
                   "deliberate, so each is put as a question.")
def scene_purpose(ctx: CheckContext) -> CheckOutput:
    d = _digest(ctx)
    if d is None:
        return NEEDS
    items = [Item(start=max(s.get("start", 0), 0), end=max(s.get("end", 0), 0),
                  text=(s.get("quote") or s.get("what", ""))[:200],
                  reason=f"In this scene: {s.get('what', '')}. The model found nothing it "
                         "changes for the story. What should be different after it?",
                  kind="scene_purpose", key=f"scene_purpose:{s.get('what', '')[:60].lower()}",
                  verdict="problem",
                  paragraph=ctx.paragraph_of(max(s.get("start", 0), 0)))
             for s in d.get("scenes", []) if not s.get("purpose")]
    n = len(d.get("scenes", []))
    return CheckOutput(items=items, measure=float(len(items)),
                       message=f"{n} scene{'s' if n != 1 else ''} outlined."
                               + ("" if items else " Each changes something."))


@check(name="pov_slips", stage="scene", label="Point-of-view slips",
       needs_model=True, judge=False, version=1, weight=70,
       description="Inside a scene told from one character's point of view, the text "
                   "jumps into another character's thoughts. Omniscient narration does "
                   "this on purpose, so each is put as a question.")
def pov_slips(ctx: CheckContext) -> CheckOutput:
    d = _digest(ctx)
    if d is None:
        return NEEDS
    items = [Item(start=s["start"], end=s["end"], text=s["quote"][:200],
                  reason=f"The point of view may slip here: {s['why']}. Is that intended?",
                  kind="pov_slip", key=f"pov_slip:{s['quote'][:60].lower()}",
                  verdict="problem", paragraph=ctx.paragraph_of(s["start"]))
             for s in d.get("slips", [])]
    return CheckOutput(items=items, measure=float(len(items)),
                       message="" if items else "The point of view holds.")


@check(name="reader_pull", stage="structure", label="Reader's pull",
       needs_model=True, judge=False, version=1, weight=65, display="measure",
       description="How strongly the chapter pulls a reader on, from 1 (a reader may put "
                   "the book down here) to 5, as one model reader judged it, with the "
                   "place it found weakest. A low pull in the first three chapters "
                   "counts for more. One reader's view, never a prediction of where real "
                   "readers stop.")
def reader_pull(ctx: CheckContext) -> CheckOutput:
    d = _digest(ctx)
    if d is None:
        return NEEDS
    r = d.get("reader")
    if not r:
        return CheckOutput(status="could_not_check",
                           message="The model gave no reading of the chapter's pull.")
    items = []
    if r["pull"] <= 2:
        items.append(Item(
            start=max(r.get("start", 0), 0), end=max(r.get("end", 0), 0),
            text=(r.get("quote") or "")[:200],
            reason=f"A reader may put the book down here: {r.get('why', '')}. What would "
                   "make them need the next page?",
            kind="reader_pull", key="reader_pull:low", verdict="problem",
            paragraph=ctx.paragraph_of(max(r.get("start", 0), 0))))
    # The first chapters weigh most: where reading data exists, readers who
    # stop mostly stop early (industry data, not research).
    early = ctx.chapter in ctx.book.chapters[:3] or ctx.is_opening
    status = ("ready" if r["pull"] >= 3
              else "needs_work" if r["pull"] == 2 and not early else "problem")
    return CheckOutput(items=items, measure=float(r["pull"]), status=status,
                       message=f"Pull {r['pull']} of 5: {r.get('why', '')}.")


# ── Across the book ────────────────────────────────────────────────────

THREADS_SYSTEM = ("You are a developmental editor checking a novel's outline for threads "
                  "left hanging. You answer only from the outline you are given.")


@check(name="loose_threads", stage="structure", label="Setups never paid off", level="book",
       needs_model=True, judge=False, version=1, weight=80,
       description="Something the story gives weight to (a threat, a question, a promise, "
                   "an object) that the rest of the book never returns to. A model matches "
                   "the setups it recorded against the whole outline. This is the kind of "
                   "whole-book judgement models are least reliable at, and a thread can be "
                   "left open on purpose (a series), so each is put as a question.")
def loose_threads(ctx: CheckContext) -> CheckOutput:
    from src.ai import chapter_digest
    digests = chapter_digest.for_book(ctx.book)
    current = digests.current()
    if not current:
        return CheckOutput(message="Needs the model to outline the chapters first.")
    if ctx.llm is None:
        return CheckOutput(message="Needs the model to match setups and payoffs.")
    setups = [(ch, s) for ch, d in current for s in d.get("setups", [])]
    last = current[-1][0].id
    setups = [(ch, s) for ch, s in setups if ch.id != last]     # the last chapter's can't be paid yet
    if not setups:
        return CheckOutput(measure=0.0, message="No setups were recorded to follow.")
    setups = setups[:40]
    listing = "\n".join(f"{n}. [{chapter_digest.title_of(ch)}] {s['what']}"
                        for n, (ch, s) in enumerate(setups, 1))
    prompt = (f"OUTLINE OF THE BOOK:\n{chapter_digest.outline(digests, 14000)}\n\n"
              f"SETUPS, with the chapter each appears in:\n{listing}\n\n"
              "Which of these setups does the rest of the outline never pay off, answer or "
              "return to? A setup that is paid off, even partly, is not listed. One line "
              "each, or the single word NONE:\n"
              "number | what a reader is left waiting for, under 20 words")
    reply = ctx.llm.generate_text(prompt, THREADS_SYSTEM, max_tokens=500, temperature=0.1) or ""
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    hits = re.findall(r"^\W*(\d+)\W*\|\s*(.+)$", reply, re.M)
    if not hits and "NONE" not in reply.upper():
        raise RuntimeError("the model's answer couldn't be read")
    items, seen = [], set()
    for number, why in hits:
        n = int(number)
        if not 1 <= n <= len(setups) or n in seen:
            continue
        seen.add(n)
        ch, s = setups[n - 1]
        items.append(Item(
            start=s["start"], end=s["end"], text=s["quote"][:200],
            reason=f"Set up in “{chapter_digest.title_of(ch)}”: {s['what']}. "
                   f"{why.strip().rstrip('.')}. Is it paid off, or left open on purpose?",
            kind="loose_thread", key=f"loose_thread:{s['what'][:60].lower()}",
            verdict="problem", chapter_id=ch.id))
    partial = "" if len(current) == len(ctx.book.chapters) else \
        f" From {len(current)} of {len(ctx.book.chapters)} chapters outlined."
    return CheckOutput(items=items, measure=float(len(items)),
                       message=f"{len(setups)} setups followed." + partial)


@check(name="character_threads", stage="scene", label="Characters who drop out",
       level="book", version=1, weight=55,
       description="A character from your records who is present early, often, and then "
                   "never appears in the last third of the book. Counted from the text, no "
                   "model. Minor characters leave stories all the time, so each is put as "
                   "a question.")
def character_threads(ctx: CheckContext) -> CheckOutput:
    chapters = [ch for ch in ctx.book.chapters if ctx.book.texts.get(ch.id, "").strip()]
    characters = list(getattr(ctx.project, "characters", None) or [])
    if len(chapters) < 6 or not characters:
        return NOT_APPLICABLE
    try:
        from src.ai.canon_index import character_name_variants, find_mentions
        variants = character_name_variants(characters)
    except Exception:
        return NOT_APPLICABLE
    counts = {}                                  # name → [mentions per chapter]
    for i, ch in enumerate(chapters):
        for name, m in find_mentions(ctx.book.texts[ch.id], variants).items():
            counts.setdefault(name, [0] * len(chapters))[i] = m["count"]
    final_third = len(chapters) - max(2, len(chapters) // 3)
    from src.ai.chapter_digest import title_of
    items = []
    for name, per in counts.items():
        present = [i for i, n in enumerate(per) if n]
        if (sum(per) >= 8 and len(present) >= 2 and present[-1] < final_third):
            last = chapters[present[-1]]
            text = ctx.book.texts[last.id]
            at = max(text.rfind(name), 0)
            items.append(Item(
                start=at, end=at + len(name), text=name,
                reason=f"{name} appears in {len(present)} chapters and is last seen in "
                       f"“{title_of(last)}” ({present[-1] + 1} of {len(chapters)}). Is "
                       "their thread closed?",
                kind="character_thread", key=f"character_thread:{name.lower()}",
                chapter_id=last.id))
    return CheckOutput(items=items, measure=float(len(items)),
                       message="" if items else "No recorded character drops out of the book.")
