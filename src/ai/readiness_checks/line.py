"""Line checks (1.2b, 1.3).

Each counts what the editor shows with that check on (``ctx.style_flags``
and ``ctx.editor_flags`` use the editor's own rules), so a chapter's cell
matches its underlines. Thresholds are in ``readiness.THRESHOLDS``.
"""

from src.ai.readiness import CheckContext, CheckOutput, Item, NOT_APPLICABLE, check
from src.utils.editor_flags import ErrorType


@check(name="overdescribed", stage="line", label="Overly descriptive",
       needs_model=True,      # the scan alone flags published prose (8 per 1,000 words)
       version=1, weight=45,
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
    return CheckOutput(items=items, measure=_rate(len(items), ctx.words))


def _rate(n: int, words: int) -> float:
    return round(n * 1000.0 / max(words, 1), 2)


def _style(ctx: CheckContext, kinds) -> CheckOutput:
    """Items for the editor's style flags of ``kinds``."""
    items = []
    for start, issue in ctx.style_flags():
        if issue.kind not in kinds:
            continue
        items.append(Item(start=start, end=start + (issue.end - issue.start),
                          text=issue.text[:200], reason=issue.message or issue.kind,
                          kind=issue.kind, key=f"{issue.kind}:{issue.text.strip().lower()[:80]}",
                          suggestions=[s for s in issue.suggestions if s][:3],
                          paragraph=ctx.paragraph_of(start)))
    return CheckOutput(items=items, measure=_rate(len(items), ctx.words))


@check(name="repetition", stage="line", label="Repeated words and phrases", version=1,
       weight=40, needs_model=True,     # published chapters show ~130 per 1,000 as a scan
       description="Words and phrases used so often they draw attention, as the editor "
                   "marks them (names and the story's own words are left out). Most repeats "
                   "are fine; a model judges which weaken the writing, so without one this "
                   "check is shown but left out of the figure.")
def repetition(ctx: CheckContext) -> CheckOutput:
    items = []
    for start, e in ctx.editor_flags():
        if e.error_type not in (ErrorType.OVERUSE, ErrorType.OVERUSED_PHRASE):
            continue
        kind = "phrase" if e.error_type == ErrorType.OVERUSED_PHRASE else "word"
        items.append(Item(start=start, end=start + (e.end - e.start), text=e.word[:200],
                          reason=e.reason, kind=kind, key=f"repetition:{e.word.lower()}",
                          paragraph=ctx.paragraph_of(start)))
    return CheckOutput(items=items, measure=_rate(len(items), ctx.words))


@check(name="echoes", stage="line", label="Echoes", version=1, weight=25,
       description="The same word again within a few lines.")
def echoes(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"echo"})


@check(name="filler", stage="line", label="Filler and weak intensifiers", version=1,
       weight=35, description="Words that add little (just, really, very, actually …) and "
                              "wordy phrases with a shorter form.")
def filler(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"intensifier", "wordy"})


@check(name="sentence_variety", stage="line", label="Sentence variety", version=1, weight=20,
       display="measure",
       description="How much sentence lengths vary (0–100), against the genre's usual "
                   "figure. Prose whose sentences are all one length reads flat.")
def sentence_variety(ctx: CheckContext) -> CheckOutput:
    from src.ai.chapter_analysis_agent import resolve_genre_profile
    stats = ctx.stats()
    if stats.sentence_count < 8:
        return NOT_APPLICABLE                    # too short to judge rhythm
    target = resolve_genre_profile(ctx.genre or "").variety_score_target
    score = round(stats.sentence_length_score, 1)
    if score >= target:
        status, msg = "ready", f"Variety {score:g} of 100 meets the genre's {target:g}."
    elif score >= target * 0.75:
        status, msg = "needs_work", (f"Variety {score:g} of 100, a little under the genre's "
                                     f"{target:g}: vary sentence length more.")
    else:
        status, msg = "problem", (f"Variety {score:g} of 100, well under the genre's "
                                  f"{target:g}: most sentences run the same length.")
    return CheckOutput(measure=score, status=status, message=msg)


@check(name="passive", stage="line", label="Passive voice", version=1, weight=30,
       description="Sentences where the doer is hidden or comes last (was thrown, had "
                   "been taken).")
def passive(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"passive"})


@check(name="adverbs", stage="line", label="Adverbs", version=1, weight=25,
       description="-ly adverbs, often a sign a stronger verb would do the work.")
def adverbs(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"adverb"})


@check(name="cliches", stage="line", label="Clichés", version=1, weight=50,
       description="Stock phrases readers have seen many times.")
def cliches(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"cliche"})


@check(name="sticky", stage="line", label="Sticky sentences", version=1, weight=15,
       description="Sentences heavy with glue words (of, the, that, it …). The noisiest "
                   "check (see the check scores), so its bar is set high.")
def sticky(ctx: CheckContext) -> CheckOutput:
    return _style(ctx, {"sticky_sentence"})
