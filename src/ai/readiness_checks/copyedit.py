"""Copyedit checks."""

from src.ai.readiness import CheckContext, CheckOutput, Item, Threshold, check
from src.utils.editor_flags import ErrorType


@check(name="spelling_grammar", stage="copyedit", label="Spelling and grammar left",
       threshold=Threshold(per_1000=(0.5, 2.0)), version=1, weight=90,
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
