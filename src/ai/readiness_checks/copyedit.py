"""Copyedit checks."""

from src.ai.readiness import NOT_APPLICABLE, CheckContext, CheckOutput, Item, check
from src.utils.editor_flags import ErrorType


@check(name="spelling_grammar", stage="copyedit", label="Spelling and grammar left",
       version=1, weight=90,
       description="Spelling and grammar flags still showing in the chapter: the same "
                   "ones the editor underlines, after your names, dictionary and allowed "
                   "words. Fix each, or add a word to the dictionary.")
def spelling_grammar(ctx: CheckContext) -> CheckOutput:
    items = []
    for start, e in ctx.editor_flags():
        if e.error_type == ErrorType.SPELLING:
            kind, key = "spelling", f"spelling:{e.word.lower()}"
        elif e.error_type == ErrorType.GRAMMAR:
            rule = getattr(e, "rule_id", "") or "builtin"
            kind, key = "grammar", f"grammar:{rule}:{e.word.lower()}"
        else:
            continue
        items.append(Item(start=start, end=start + (e.end - e.start), text=e.word[:200],
                          reason=e.reason or kind.title(), kind=kind, key=key,
                          suggestions=list(e.suggestions or [])[:5],
                          paragraph=ctx.paragraph_of(start)))
    rate = len(items) * 1000.0 / max(ctx.words, 1)
    return CheckOutput(items=items, measure=round(rate, 2))


def _consistency_groups(ctx: CheckContext):
    """Every consistency group of the manuscript, computed once per run
    (the same checker as Edit → Consistency, with the same names)."""
    def make():
        from src.ai.canon_index import character_alias_names, collect_world_entities
        from src.utils.consistency_checks import ConsistencyChecker
        project = ctx.project
        names = [c.name for c in getattr(project, "characters", None) or []]
        names += character_alias_names(getattr(project, "characters", None) or [])
        try:
            names += [e.name for e in collect_world_entities(getattr(project, "worldbuilding", None))]
        except Exception:
            pass
        names += list(getattr(getattr(project, "dictionary", None), "words", None) or [])
        book = ctx.book
        chapters = [(ch.id, ch.title or f"Chapter {ch.number}", book.texts.get(ch.id, ""))
                    for ch in book.chapters]
        return ConsistencyChecker(chapters, names).run()
    return ctx.book.lazy("consistency", make)


@check(name="consistency", stage="copyedit", label="Consistency", version=1, weight=70,
       book_wide=True,
       description="Names, spellings (grey/gray), hyphenation, numbers and punctuation "
                   "written more than one way across the manuscript, as Edit → Consistency "
                   "finds them. Counts the places in this chapter that differ from the "
                   "usual form.")
def consistency(ctx: CheckContext) -> CheckOutput:
    """One item per inconsistency found in this chapter (the first place it
    differs; the reason says how many)."""
    items = []
    for group in _consistency_groups(ctx):
        if group.review:                      # capitalization: a judgement, not a slip
            continue
        here = [o for o in group.changes() if o.chapter_id == ctx.chapter.id]
        if not here:
            continue
        occ = here[0]
        fix = group.replacement_for(occ, group.preferred)
        times = f" ({len(here)} places in this chapter)" if len(here) > 1 else ""
        items.append(Item(start=occ.start, end=occ.end, text=occ.text[:200],
                          reason=f"{group.title}: {group.message}{times}", kind=group.kind,
                          key=f"consistency:{group.key}",
                          suggestions=[fix] if fix and fix != occ.text else [],
                          paragraph=ctx.paragraph_of(occ.start)))
    return CheckOutput(items=items, measure=float(len(items)))


@check(name="style_sheet", stage="copyedit", label="Style sheet breaks", version=1, weight=70,
       description="Places that break your own style sheet: a word you prefer written "
                   "another way, or one you avoid.")
def style_sheet(ctx: CheckContext) -> CheckOutput:
    from src.ai.style_sheet import rules
    if not any(getattr(r, "kind", "") in ("prefer", "avoid") for r in rules(ctx.project)):
        return NOT_APPLICABLE                 # no prefer/avoid rules yet
    items = []
    for start, issue in ctx.style_flags():
        if issue.kind != "preference":
            continue
        items.append(Item(start=start, end=start + (issue.end - issue.start),
                          text=issue.text[:200], reason=issue.message, kind="preference",
                          key=f"preference:{issue.text.strip().lower()}",
                          suggestions=[s for s in issue.suggestions if s][:2],
                          paragraph=ctx.paragraph_of(start)))
    return CheckOutput(items=items, measure=float(len(items)))
