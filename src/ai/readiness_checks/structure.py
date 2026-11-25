"""Structure checks (1.5): pacing against the genre, the plan's subplots
and promises, and length (information, never a verdict)."""

from src.ai import genre_baseline
from src.ai.readiness import CheckContext, CheckOutput, Item, NOT_APPLICABLE, Status, check

TYPICAL_CHAPTER = (2_000, 5_000)        # words; a common guide, not a rule


def _genre(ctx: CheckContext):
    from src.ai.chapter_analysis_agent import resolve_genre_profile
    text = getattr(getattr(ctx.project, "prose_profile", None), "genre", "") or ctx.genre or ""
    return resolve_genre_profile(text), bool(text.strip())


@check(name="pacing", stage="structure", label="Pacing for the genre", version=2, weight=55,
       judge=False, depends=genre_baseline.depends,
       description="Sentence rhythm against the genre's usual ranges: average sentence "
                   "length, variety, and the share of long sentences (the Critique's Pacing "
                   "measures, no model needed). Most published chapters stray on one of "
                   "these, so one is fine; two need work. Where the app has figures from "
                   "published books in the genre, the ranges are theirs, and dialogue and "
                   "readability are shown beside them too.")
def pacing(ctx: CheckContext) -> CheckOutput:
    from src.ai.chapter_analysis_agent import PacingAnalyzer, ReportSection, ReportType
    if ctx.stats().sentence_count < 8:
        return NOT_APPLICABLE
    genre, stated = _genre(ctx)
    genre = _published_bands(ctx, genre)
    section = ReportSection(report_type=ReportType.PACING,
                            chapter_title=getattr(ctx.chapter, "title", "") or "")
    PacingAnalyzer()._compute(ctx.text, section, genre, None)
    risks = [f for f in section.findings if "Risk:" in f]
    items = [Item(start=0, end=0, text=f.split(".")[0][:200], reason=f, kind="pacing",
                  key=f"pacing:{f.split(' ')[0].lower()}") for f in risks]
    if genre.key != "default":
        where = f"Measured against {genre.name}."
    elif stated:
        where = (f"Measured against {genre.name}: the Prose Profile's genre isn't one the app "
                 "has figures for.")
    else:
        where = f"Measured against {genre.name}: no genre is set in the Prose Profile."
    stats = ctx.stats()
    beside = [genre_baseline.line(ctx.genre or "", m, v) for m, v in (
        ("sentence_length", section.metrics.get("avg_sentence_length")),
        ("dialogue_share", stats.dialogue_percentage),
        ("readability", stats.flesch_reading_ease))]
    where = " ".join([where] + list(dict.fromkeys(b for b in beside if b)))
    return CheckOutput(items=items, measure=section.metrics.get("avg_sentence_length"),
                       message=where)


def _published_bands(ctx: CheckContext, genre):
    """The genre profile with its sentence-length band and variety floor
    taken from published books in the genre, where the app has them (P.3)."""
    import dataclasses
    length = genre_baseline.usable(ctx.genre or "", "sentence_length")
    variety = genre_baseline.usable(ctx.genre or "", "sentence_variety")
    if length is None and variety is None:
        return genre
    return dataclasses.replace(
        genre,
        avg_sentence_target=((round(length.low, 1), round(length.high, 1)) if length
                             else genre.avg_sentence_target),
        variety_score_target=round(variety.low, 1) if variety else genre.variety_score_target)


@check(name="chapter_length", stage="structure", label="Chapter length", counts=False, judge=False,
       version=2, weight=0, depends=genre_baseline.depends,
       description="The chapter's length beside what is common (in published books of the "
                   "genre, when the app has figures for it). Information only: never a pass "
                   "or a fail.")
def chapter_length(ctx: CheckContext) -> CheckOutput:
    published = genre_baseline.usable(ctx.genre or "", "chapter_length")
    low, high = ((int(round(published.low, -1)), int(round(published.high, -1))) if published
                 else TYPICAL_CHAPTER)
    note = ("shorter than most" if ctx.words < low else
            "longer than most" if ctx.words > high else "within the usual range")
    if published:
        message = (f"{ctx.words:,} words: {note} (chapters of published "
                   f"{genre_baseline.plural(ctx.genre)} commonly run {low:,}–{high:,}; "
                   f"{published.books} books).")
    else:
        message = (f"{ctx.words:,} words: {note} (chapters commonly run "
                   f"{low:,}–{high:,}; a rough guide).")
        thin = genre_baseline.line(ctx.genre or "", "chapter_length")
        message += f" {thin}" if thin else ""
    return CheckOutput(status=Status.INFO, measure=float(ctx.words), message=message)


@check(name="manuscript_length", stage="structure", label="Manuscript length", level="book",
       counts=False, version=1, weight=0,
       description="The manuscript's length beside what is typical for its genre and "
                   "publishing route. Information only.")
def manuscript_length(ctx: CheckContext) -> CheckOutput:
    from src.data.publishing_goal import publishing_goal
    goal = publishing_goal(ctx.project, ctx.scope)
    return CheckOutput(status=Status.INFO, measure=float(ctx.book.words()),
                       message=goal.length_note.replace(f"{goal.words:,}", f"{ctx.book.words():,}"))


@check(name="subplots", stage="structure", label="Subplots touched", level="book", version=1,
       weight=60,
       description="Subplots in your plan that no chapter's planning links to. Link a "
                   "chapter's subplot notes to the subplot in the Planner.")
def subplots(ctx: CheckContext) -> CheckOutput:
    planned = [sp for sp in (getattr(ctx.planning, "subplots", None) or [])
               if getattr(sp, "status", "active") != "abandoned"]
    if not planned:
        return NOT_APPLICABLE
    touched = {}
    for ch in ctx.book.chapters:
        for note in getattr(getattr(ch, "planning", None), "subplot_notes", None) or []:
            sid = getattr(note, "subplot_id", "") or ""
            if sid:
                touched.setdefault(sid, []).append(ch.id)
    if not touched:
        return CheckOutput(status=Status.INFO, measure=float(len(planned)),
                           message="No chapter's planning links a subplot yet, so this can't "
                                   "be checked. Link subplot notes to subplots in the Planner.")
    items = [Item(start=0, end=0, text=sp.title or "Untitled subplot",
                  reason="No chapter touches this subplot"
                         + (" (resolved)" if sp.status == "resolved" else "") + ".",
                  kind="subplot", key=f"subplot:{sp.id}")
             for sp in planned if sp.id not in touched and sp.status != "resolved"]
    return CheckOutput(items=items, measure=float(len(items)),
                       message=f"{len(planned) - len(items)} of {len(planned)} subplots "
                               "are touched by at least one chapter.")


@check(name="promises", stage="structure", label="Promises kept", level="book",
       needs_model=True, model_ready=False, version=1, weight=60,
       description="Whether the chapters deliver on the promises in your plan. Nothing in "
                   "the plan links a chapter to a promise, so a model reads the chapters to "
                   "judge it (from piece 1.7).")
def promises(ctx: CheckContext) -> CheckOutput:
    found = getattr(ctx.planning, "promises", None) or []
    if not found:
        return NOT_APPLICABLE
    return CheckOutput(message=f"{len(found)} promise(s) in the plan. Not counted yet: run the "
                               "Critique's Plot & Promises report (with a model) to see whether "
                               "the chapters keep them.")
