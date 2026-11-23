"""Line checks."""

from src.ai.readiness import CheckContext, CheckOutput, Item, Threshold, check


@check(name="overdescribed", stage="line", label="Overly descriptive",
       needs_model=True,      # the scan alone flags published prose (8 per 1,000 words)
       threshold=Threshold(per_1000=(2.0, 5.0)), version=1, weight=45,
       description="Sentences that tell the reader how something is instead of showing "
                   "it. The scan finds candidates; a model decides which count, so without "
                   "a model this check is shown but left out of the figure.")
def overdescribed(ctx: CheckContext) -> CheckOutput:
    items = []
    for f in ctx.overdescribed():
        items.append(Item(start=f.start, end=f.end, text=f.text[:200],
                          reason=f.reason or "Tells instead of showing.", kind="overdescribed",
                          key=f"overdescribed:{f.text.strip().lower()[:80]}",
                          suggestions=[x.text for x in f.expansions if not x.by_ai][:3],
                          verdict={"over": "problem", "fine": "cleared"}.get(f.verdict, ""),
                          paragraph=ctx.paragraph_of(f.start)))
    rate = len(items) * 1000.0 / max(ctx.words, 1)
    return CheckOutput(items=items, measure=round(rate, 2))
