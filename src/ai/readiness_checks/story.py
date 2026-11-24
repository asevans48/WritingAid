"""The story's major issues: character disconnects, plot jumps, continuity.

A model reads each chapter once for all three (``story_read``); every
finding quotes the chapter. Each chapter is read against the book's style
sheet (``story_ledger``): the facts recorded from the chapters before it.
Without a model they are "needs a model": no scan can honestly stand in
for reading the story.
"""

from src.ai.readiness import CheckContext, CheckOutput, Item, check


def _read(ctx: CheckContext):
    """The model's findings for this chapter (one request, shared by the
    three checks); None without a model."""
    if ctx.llm is None:
        return None

    def make():
        from src.ai import story_read
        compact = False
        try:
            from src.ai.chapter_analysis_agent import is_local_llm
            compact = bool(is_local_llm(ctx.llm))
        except Exception:
            pass
        try:
            from src.ai import story_ledger
            from src.ai.readiness import text_hash
            ledger = story_ledger.for_book(ctx.book)
            shown = ledger.shown(ctx.chapter, ctx.text, compact)
            found = story_read.read_chapter(ctx.llm, ctx.project, ctx.chapter, ctx.text,
                                            ctx.book, compact, ledger=shown)
            found["_sheet"] = len(shown)
            ledger.record(ctx.chapter, ctx.text, text_hash(ctx.text), found.get("facts", []))
            return found
        except Exception as e:                    # the same failure for all three checks
            return e
    found = ctx._lazy("story_read", make)
    if isinstance(found, Exception):
        raise found
    return found


def _sheet_key(ctx: CheckContext) -> str:
    """Part of the cache key: the earlier facts this chapter is read against."""
    try:
        from src.ai import story_ledger
        return story_ledger.for_book(ctx.book).shown_hash(ctx.chapter, ctx.text)
    except Exception:
        return ""


def _output(ctx: CheckContext, kind: str, nothing: str) -> CheckOutput:
    found = _read(ctx)
    if found is None:
        return CheckOutput(message="Needs the model to read the chapter.")
    from src.ai.story_read import as_query
    items = [Item(start=f["start"], end=f["end"], text=f["quote"][:200],
                  reason=as_query(kind, f),
                  kind=kind, key=f"{kind}:{f['quote'][:60].lower()}", verdict="problem",
                  paragraph=ctx.paragraph_of(f["start"]))
             for f in found[kind]]
    note = ""
    if found.get("_read_words", 0) < found.get("_total_words", 0):
        note = (f" The model read the first {found['_read_words']:,} of "
                f"{found['_total_words']:,} words.")
    if kind == "continuity" and found.get("_sheet"):
        note += f" Read against {found['_sheet']} facts recorded from earlier chapters."
    return CheckOutput(items=items, measure=float(len(items)),
                       message=(nothing if not items else "") + note)


@check(name="character_disconnects", stage="scene", label="Character disconnects",
       tier="major", needs_model=True, judge=False, version=2, weight=95, depends=_sheet_key,
       description="A character does, says or knows something that contradicts what the "
                   "specific thing the text or their record established, with no reason "
                   "shown. A model reads the chapter against your character records; each "
                   "finding quotes both passages and asks which you intend.")
def character_disconnects(ctx: CheckContext) -> CheckOutput:
    return _output(ctx, "character", "No character acts against what's been established.")


@check(name="plot_jumps", stage="structure", label="Plot jumps", tier="major",
       needs_model=True, judge=False, version=2, weight=95, depends=_sheet_key,
       description="A break in time, in cause and effect, or in whom we follow, that the "
                   "text gives no way to bridge. A marked scene break, a gap the reader can "
                   "fill, or a change of place alone is not a jump.")
def plot_jumps(ctx: CheckContext) -> CheckOutput:
    return _output(ctx, "jump", "No unbridged jumps.")


@check(name="continuity", stage="scene", label="Continuity", tier="major",
       needs_model=True, judge=False, version=2, weight=95, depends=_sheet_key,
       description="A fact that contradicts an earlier one: an object, an injury, a name, a "
                   "date, the time of day, who is present, who knows what. Read against "
                   "the chapter, the previous chapter's ending, your character records, "
                   "your story decisions, and the style sheet: the facts recorded from "
                   "every earlier chapter.")
def continuity(ctx: CheckContext) -> CheckOutput:
    return _output(ctx, "continuity", "No contradictions found.")
