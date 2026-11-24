"""Opening pages (1.8): the first ~2,500 words, read as an agent reads them.

Shown as the **Opening pages** row at the top of the scorecard. The first
chapter's own line and copyedit checks are also held to a tighter bar
(``CheckContext.threshold``), tighter still on the agent route.

* **Words before something happens** and **backstory up front** need no
  model: they find the first dialogue or action, and the sentences that look
  back (past perfect, "years ago") before it. Both are scans and say so.
* **First plot event** looks for the plan's first event in the text by its
  distinctive words: a scan, labelled as one, since nothing links the plan to
  the prose.
* **Hook and inciting incident** needs a model, which reads the opening once.
"""

from __future__ import annotations

import re
from collections import Counter

from src.ai.readiness import (
    NOT_APPLICABLE, CheckContext, CheckOutput, Item, Status, _status_from, check,
)

_SENT = re.compile(r"[^.!?…]+[.!?…]+[\"”’)]*|[^.!?…]+$")
_QUOTE = re.compile(r"[\"“]")
_SUBJECT = r"(?:I|he|she|they|we|you|[A-Z][a-z]{2,})"
_STATE = {"was", "were", "had", "has", "have", "is", "are", "seemed", "felt", "thought",
          "knew", "remembered", "wondered", "loved", "liked", "wanted", "hoped", "believed",
          "lived", "used", "owned", "looked", "sounded", "appeared", "realized", "realised",
          "imagined", "supposed", "considered", "preferred", "needed", "belonged", "seems",
          "feels", "thinks", "knows", "remembers", "lives", "would", "could", "should",
          "might", "must", "did", "does", "do", "became", "become", "being", "been"}
_ACTION = re.compile(rf"\b{_SUBJECT}\s+(?:\w+ly\s+)?([a-z]+(?:ed|ew|ung|ook|ode|ove|an|it|ot|"
                     rf"ept|eld|ought|ang|um|ust|ut|ipped|opped|bbed|gged|shed|ched))\b")
_LOOKING_BACK = re.compile(
    r"\bhad\s+(?:been|never|always|once|\w+ed|gone|come|done|seen|known|taken|given|made|"
    r"grown|lived|left|run|written|told|said|met|lost|found|thought|felt|heard|built|"
    r"spent|kept)\b|\bused to\b|\b(?:years|months|decades|long|ages)\s+(?:ago|before|earlier)\b|"
    r"\bwhen (?:I|he|she|they|we) (?:was|were) (?:a|young|little|small)\b|\bback then\b|"
    r"\bas a (?:child|girl|boy)\b|\bin those days\b", re.I)
_STOP = set("""the and that with from this they them their there were have been into over
under about after before when what which while would could should your said then than
only just like some more most such very also back down just even still upon onto""".split())


def _sentences(text: str):
    for m in _SENT.finditer(text):
        if m.group(0).strip():
            yield m.start(), m.end(), m.group(0)


def _first_happening(text: str):
    """(offset, sentence span, why) of the first dialogue or action."""
    q = _QUOTE.search(text)
    first_q = q.start() if q else None
    for start, end, sent in _sentences(text):
        if first_q is not None and first_q < end:
            return first_q, (start, end), "the first line of dialogue"
        m = _ACTION.search(sent)
        if m and m.group(1).lower() not in _STATE:
            return start, (start, end), "the first action"
    return None, None, ""


def _item(ctx, start: int, end: int, text: str, reason: str, kind: str) -> Item:
    cid, local = ctx.locate(start)
    return Item(start=local, end=local + (end - start), text=" ".join(text.split())[:200],
                reason=reason, kind=kind, key=f"opening:{kind}:{text.strip()[:40].lower()}",
                chapter_id=cid)


@check(name="first_action", stage="scene", label="Words before something happens",
       level="opening", version=1, weight=65, display="measure", judge=False,
       description="How far the opening runs before the first line of dialogue or the "
                   "first action (a scan of the first pages). Agents read only a few pages; "
                   "the bar is lower for agent submission.")
def first_action(ctx: CheckContext) -> CheckOutput:
    pos, span, what = _first_happening(ctx.text)
    if pos is None:
        words = ctx.words
        return CheckOutput(items=[], measure=float(words), status=Status.PROBLEM,
                           message=f"No dialogue or action found in the first {words:,} words.")
    words = len(ctx.text[:pos].split())
    status = _status_from(ctx.threshold("first_action"), words, 1)
    item = _item(ctx, span[0], span[1], ctx.text[span[0]:span[1]],
                 f"Something first happens here: {what}, {words:,} words in.", "first_action")
    return CheckOutput(items=[item] if status != Status.READY else [item], measure=float(words),
                       status=status, message=f"{what.capitalize()} comes {words:,} words in.")


@check(name="backstory", stage="scene", label="Backstory up front", level="opening",
       version=1, weight=55, display="measure",
       description="The share of the opening, before anything happens, that looks back "
                   "(had been, years ago, used to). A little sets the scene; a lot keeps "
                   "the story waiting. The figure is a percentage.")
def backstory(ctx: CheckContext) -> CheckOutput:
    pos, _span, _what = _first_happening(ctx.text)
    stop = pos if pos is not None else len(ctx.text)
    stop = max(stop, min(len(ctx.text), 1200))      # at least the first page or so
    sents = [(s, e, t) for s, e, t in _sentences(ctx.text[:stop]) if len(t.split()) >= 3]
    if len(sents) < 3:
        return NOT_APPLICABLE
    back = [(s, e, t) for s, e, t in sents if _LOOKING_BACK.search(t)]
    share = len(back) / len(sents)
    # The threshold is per 1,000 sentences: the share, as a rate.
    status = _status_from(ctx.threshold("backstory"), round(share * 1000), 1000)
    items = [_item(ctx, s, e, t, "Looks back before the story has started.", "backstory")
             for s, e, t in back]
    return CheckOutput(items=items, measure=round(share * 100), status=status,
                       message=f"{len(back)} of the {len(sents)} sentences before anything "
                               f"happens look back ({share:.0%}).")


def _first_plan_event(project):
    order = {"exposition": 0, "rising_action": 1, "climax": 2, "falling_action": 3,
             "resolution": 4}
    events = list(getattr(getattr(getattr(project, "story_planning", None),
                                  "freytag_pyramid", None), "events", None) or [])
    if not events:
        return None
    return sorted(events, key=lambda e: (getattr(e, "act", 1) or 1,
                                         order.get(getattr(e, "stage", ""), 9),
                                         getattr(e, "sort_order", 0) or 0))[0]


@check(name="first_plot_event", stage="structure", label="First plot event",
       level="opening", version=1, weight=50, display="measure", judge=False,
       description="How far into the manuscript the first event in your plan shows up, "
                   "found by its distinctive words (a scan: nothing links the plan to the "
                   "text). The figure is words in.")
def first_plot_event(ctx: CheckContext) -> CheckOutput:
    event = _first_plan_event(ctx.project)
    if event is None:
        return NOT_APPLICABLE
    book = ctx.book
    whole = "\n".join(book.texts.get(ch.id, "") for ch in book.chapters).lower()
    counts = Counter(re.findall(r"[a-z']{4,}", whole))
    words = [w for w in re.findall(r"[a-z']{4,}", f"{event.title} {event.description}".lower())
             if w not in _STOP and counts.get(w)]
    keys = sorted(set(words), key=lambda w: counts[w])[:3]       # the rarest that occur
    title = getattr(event, "title", "") or "the first event"
    if not keys:
        return CheckOutput(status=Status.INFO, message=f"The plan's first event (“{title}”) "
                           "uses no word found in the text, so it can't be placed.")
    need = 2 if len(keys) >= 2 else 1
    words_before = 0
    for ch in book.chapters:
        text = book.texts.get(ch.id, "")
        for start, end, sent in _sentences(text):
            low = sent.lower()
            if sum(1 for k in keys if k in low) >= need:
                where = words_before + len(text[:start].split())
                status = _status_from(ctx.threshold("first_plot_event"), where, 1)
                item = Item(start=start, end=end, text=" ".join(sent.split())[:200],
                            reason=f"Looks like the plan's first event, “{title}” "
                                   f"({where:,} words in).", kind="first_plot_event",
                            key=f"opening:event:{event.id}", chapter_id=ch.id)
                return CheckOutput(items=[item], measure=float(where), status=status,
                                   message=f"“{title}” seems to arrive {where:,} words in "
                                           f"(found by its words: {', '.join(keys)}).")
        words_before += len(text.split())
    return CheckOutput(status=Status.INFO, message=f"The plan's first event (“{title}”) wasn't "
                       f"found by its words ({', '.join(keys)}).")


HOOK_SYSTEM = ("You are a literary agent reading the opening pages of a submission. You are "
               "honest and specific.")


@check(name="hook", stage="structure", label="Hook and inciting incident", level="opening",
       needs_model=True, version=1, weight=70, judge=False,
       description="Whether the opening raises a question the reader wants answered, and "
                   "whether the event that sets the story going happens in these pages. A "
                   "model reads the opening to judge it.")
def hook(ctx: CheckContext) -> CheckOutput:
    if ctx.llm is None:
        return CheckOutput(message="Needs a model to read the opening.")
    compact = False
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        compact = bool(is_local_llm(ctx.llm))
    except Exception:
        pass
    words = ctx.text.split()
    excerpt = " ".join(words[:1200 if compact else 2500])
    prompt = (f"OPENING PAGES:\n{excerpt}\n\nAnswer exactly these lines, nothing else:\n"
              "HOOK: YES or NO — <does it raise a question the reader wants answered? "
              "under 20 words>\n"
              "INCIDENT: YES or NO — <does the event that sets the story going happen here?>\n"
              "QUOTE: <the sentence where the story turns, copied exactly, or NONE>")
    reply = ctx.llm.generate_text(prompt, HOOK_SYSTEM, max_tokens=160, temperature=0.2) or ""
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    found = {k.upper(): (v.strip()) for k, v in re.findall(
        r"^\s*\**\s*(HOOK|INCIDENT|QUOTE)\**\s*:\s*(.+)$", reply, re.I | re.M)}
    if "HOOK" not in found or "INCIDENT" not in found:
        raise RuntimeError("the model's answer couldn't be read")
    yes = lambda v: v.upper().startswith("YES")
    hook_ok, incident_ok = yes(found["HOOK"]), yes(found["INCIDENT"])
    status = (Status.READY if hook_ok and incident_ok else
              Status.NEEDS_WORK if hook_ok or incident_ok else Status.PROBLEM)
    why = lambda v: re.sub(r"^(YES|NO)\W*", "", v, flags=re.I).strip()
    items = []
    if not hook_ok:
        items.append(Item(start=0, end=0, text="The hook", reason=why(found["HOOK"]) or "No hook.",
                          kind="hook", key="opening:hook", verdict="problem"))
    if not incident_ok:
        items.append(Item(start=0, end=0, text="The inciting incident",
                          reason=why(found["INCIDENT"]) or "Not in the opening pages.",
                          kind="incident", key="opening:incident", verdict="problem"))
    quote = found.get("QUOTE", "").strip().strip('"“”')
    if quote and quote.upper() != "NONE":
        at = ctx.text.find(quote[:60])
        if at >= 0:
            items.append(_item(ctx, at, at + len(quote), quote, "Where the story turns.",
                               "turn"))
    return CheckOutput(items=items, status=status,
                       message=f"Hook: {found['HOOK']}. Inciting incident: {found['INCIDENT']}.")
