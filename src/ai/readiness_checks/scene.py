"""Scene checks (1.6): dialogue, and continuity.

* **Dialogue fits the speaker** and **dialogue problems** need no model.
* **Continuity across novellas** gives what a scan can (possible
  resurrections, shared names with no record); conflicts need a model.
* **Continuity within the book** is a major issue, read by a model
  (``readiness_checks/story.py``).
* **Order of events** is not checked: nothing links a chapter's events to
  the plan's events, so there is nothing to compare (piece 1.6, Outcome).
"""

from src.ai.readiness import CheckContext, CheckOutput, Item, NOT_APPLICABLE, check


def _lines(ctx: CheckContext):
    from src.ai.dialogue_speakers import attribute_lines
    return ctx._lazy("lines", lambda: attribute_lines(ctx.text, ctx.names()))


def _profiles(ctx: CheckContext):
    """How each character speaks, measured over the whole manuscript once."""
    def make():
        from src.ai.dialogue_craft import speech_profiles
        return speech_profiles(ctx.project, texts=list(ctx.book.texts.values()))
    return ctx.book.lazy("speech_profiles", make)


@check(name="dialogue_fit", stage="scene", label="Dialogue fits the speaker", version=1,
       weight=55, book_wide=True,
       description="Lines that sound more like another character than the one speaking, "
                   "measured against how each character talks across the manuscript (five "
                   "or more lines needed to know a voice).")
def dialogue_fit(ctx: CheckContext) -> CheckOutput:
    from src.ai.dialogue_craft import line_fit
    if not ctx.names():
        return NOT_APPLICABLE
    profiles = _profiles(ctx)
    if sum(1 for p in profiles.values() if p.measured) < 2:
        return NOT_APPLICABLE                # not enough dialogue to know two voices
    items = []
    for line in _lines(ctx):
        if not line.speaker:
            continue
        verdict = line_fit(line.quote, line.speaker, profiles)
        if verdict:
            end = line.start + len(line.quote) + 2
            items.append(Item(start=line.start, end=end, text=line.quote[:200], reason=verdict,
                              kind="dialogue_fit", key=f"fit:{line.speaker}:{line.quote[:60]}",
                              paragraph=line.paragraph))
    return CheckOutput(items=items, measure=float(len(items)))


@check(name="dialogue_problems", stage="scene", label="Dialogue problems", version=1,
       weight=45,
       description="Said-bookisms, adverbs on dialogue tags, characters naming each other "
                   "too often, very long speeches, lost speakers, exposition in dialogue, "
                   "filler and over-stage-directed scenes.")
def dialogue_problems(ctx: CheckContext) -> CheckOutput:
    from src.ai.dialogue_craft import dialogue_issues
    if '"' not in ctx.text and "“" not in ctx.text:
        return NOT_APPLICABLE                # no dialogue in this chapter
    items = []
    for issue in dialogue_issues(ctx.text, ctx.names(), lines=_lines(ctx)):
        start = max(issue.start, 0)
        excerpt = issue.excerpt or ""
        items.append(Item(start=start, end=start + len(excerpt) if issue.start >= 0 else start,
                          text=(excerpt or issue.message)[:200], reason=issue.message,
                          kind=issue.kind, key=f"dialogue:{issue.kind}:{excerpt[:60].lower()}",
                          paragraph=ctx.paragraph_of(start)))
    return CheckOutput(items=items, measure=round(len(items) * 1000.0 / max(ctx.words, 1), 2))


@check(name="continuity_novellas", tier="major", stage="scene", label="Continuity across novellas",
       level="book", needs_model=True, version=1, weight=60, book_wide=True,
       description="The main manuscript and novellas compared: a character who dies in one "
                   "and appears in another, shared names with no record. A scan finds "
                   "candidates; a model judges conflicts.")
def continuity_novellas(ctx: CheckContext) -> CheckOutput:
    from src.ai.continuity_analysis import ContinuityAnalyzer, has_cross_manuscript_content
    if ctx.scope is not None or not has_cross_manuscript_content(ctx.project):
        return NOT_APPLICABLE                # shown once, on the main manuscript
    # With a model the analyzer also judges conflicts; without, it scans.
    section = ctx.book.lazy("continuity",
                            lambda: ContinuityAnalyzer(ctx.project, ctx.llm).run())
    items = [Item(start=0, end=0, text=m.split(" — ")[0][:200], reason=m,
                  kind="resurrection", key=f"continuity:{m[:60].lower()}")
             for m in section.major_issues]
    for name in (section.extra_lists or {}).get("Shared names with no record", []):
        items.append(Item(start=0, end=0, text=str(name)[:200],
                          reason="Named in more than one manuscript but not recorded.",
                          kind="unrecorded", key=f"continuity:name:{str(name).lower()}"))
    return CheckOutput(items=items, message=section.summary)
