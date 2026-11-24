"""A model reads a chapter for the story's major issues.

One request per chapter looks for three things a reader stumbles on, the
way an editor reads for them:

* **Character disconnects**: an action, a line or a piece of knowledge that
  contradicts what the text or the character's record has established, with
  no reason shown.
* **Plot jumps**: a break in time, place or cause-and-effect that the text
  doesn't bridge, so the reader can't tell how the story got here.
* **Continuity breaks**: a fact that contradicts an earlier one (an object,
  an injury, a name, a date, the time of day, who is present, who knows
  what).

Why these, and how they are defined (sources and their strength are in
``docs/publishing/background.md``):

* Readers build expectations from a character's **specific** traits and
  slow down when an action contradicts one (Rapp, Gerrig & Prentice 2001).
  So a disconnect is a conflict between **two passages**, never a general
  impression, and both are quoted.
* Shifts in time, protagonist and causation raise reading load (Zwaan,
  Magliano & Graesser 1995; Rinck & Weber 2003); the effect of a change of
  place alone is weak. So a jump names what broke, and a change of place
  alone is not counted.
* An ellipsis is a normal, often deliberate device (Genette; Sternberg):
  only a discontinuity the text gives no way to bridge is a jump.
* Copyediting standards say "correct or query" (Editors Canada, D3), and a
  fiction style sheet tracks characters, places and timeline (Schneider
  2023). So a finding is put as a **query**: it shows the two passages and
  does not rule on which is right.

**Evidence, always.** Each finding must quote the chapter, and a character
or continuity finding must also quote what it contradicts (from the
chapter, the previous chapter's ending, a character record or a story
decision). A finding whose quotes can't be found is dropped, so nothing
invented is shown.

**What it reads against:** the chapter itself, the end of the previous
chapter, the records of the characters who appear, the story decisions the
writer has settled, and the book's style sheet (``story_ledger``): the
facts recorded from every earlier chapter about the people and things this
chapter mentions. In the same request the model lists the facts this
chapter establishes, which later chapters are then read against.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

KINDS = ("character", "jump", "continuity")
MAX_WORDS = 3500             # of the chapter, for cloud models
MAX_WORDS_COMPACT = 1500     # for on-device models
MAX_FINDINGS = 10
MAX_FACTS = 8

SYSTEM = ("You are an experienced fiction editor reading one chapter of a novel for "
          "problems that would stop a reader: characters acting against what has been "
          "established, jumps the text doesn't bridge, and facts that contradict each "
          "other. You quote the text exactly, you are specific, and you report nothing "
          "you cannot point to.")

RUBRIC = (
    "Look for three kinds of problem:\n"
    "CHARACTER — a character does, says or knows something that contradicts a SPECIFIC "
    "thing this text or their record established (a trait, a skill, a fear, a fact they "
    "know or don't), and no reason is shown. A general impression that it is 'out of "
    "character' is not enough: you must be able to quote what it contradicts.\n"
    "JUMP — a break in TIME, in CAUSE and effect, or in which CHARACTER we follow, that the "
    "text gives the reader no way to bridge: no marker (\"an hour later\"), no scene "
    "break, nothing to infer it from. A change of place alone is not a jump.\n"
    "CONTINUITY — a fact that contradicts an earlier one: an object, an injury, a name, a "
    "date, the time of day, who is present, who knows what.\n"
    "These are NOT problems: a scene break marked by a blank line or #; a gap the reader "
    "can fill; a mystery or information the author is clearly holding back on purpose; a "
    "character changing for a reason the text shows.")

_LINE = re.compile(r"^\W*(CHARACTER|JUMP|CONTINUITY)\W*\|(.+)$", re.I | re.M)
_FACT = re.compile(r"^\W*FACT\W*\|(.+)$", re.I | re.M)

FACTS_ASK = (
    f"Then, on separate lines, list up to {MAX_FACTS} facts THIS chapter establishes that a "
    "later chapter could contradict: a character's looks, age, skills, fears, injuries, "
    "possessions, relationships and what they know; where places are and what they are "
    "like; dates, ages and how much time passes (use TIMELINE as the name). Only what the "
    "text states, in this form:\n"
    "FACT | name | the fact, under 15 words | \"the exact words from the chapter that "
    "establish it\"")

# Where the words a finding contradicts were found.
HERE, PREVIOUS, RECORDS = "Earlier", "At the end of the previous chapter", "In your records"
JUMP_KINDS = {"TIME": "time", "CAUSE": "cause and effect", "CHARACTER": "whom we follow",
              "PLACE": "place"}


def _previous_ending(book: Any, chapter: Any, words: int = 150) -> str:
    chapters = list(getattr(book, "chapters", None) or [])
    for i, ch in enumerate(chapters):
        if getattr(ch, "id", None) == getattr(chapter, "id", None) and i > 0:
            prev = book.texts.get(chapters[i - 1].id, "")
            return " ".join(prev.split()[-words:])
    return ""


def _profiles(project: Any, text: str, limit: int) -> str:
    try:
        from src.ai.canon_index import (character_name_variants, find_mentions,
                                        format_character_profile)
        chars = list(getattr(project, "characters", None) or [])
        mentions = find_mentions(text, character_name_variants(chars))
        by_name = {c.name: c for c in chars}
        top = sorted(mentions, key=lambda n: -mentions[n]["count"])[:limit]
        return "\n\n".join(format_character_profile(by_name[n], max_field=160) for n in top)
    except Exception:
        return ""


def sections(project: Any, chapter: Any, text: str, book: Any = None,
             compact: bool = False, ledger: Optional[List[Dict[str, Any]]] = None
             ) -> List[tuple]:
    """The prompt's parts as (where it comes from, text). ``ledger`` is the
    style sheet's facts from earlier chapters (``story_ledger.shown``)."""
    words = text.split()
    cap = MAX_WORDS_COMPACT if compact else MAX_WORDS
    excerpt = " ".join(words[:cap]) if len(words) > cap else text
    parts: List[tuple] = []
    profiles = _profiles(project, text, 3 if compact else 6)
    if profiles:
        parts.append((RECORDS, "CHARACTER RECORDS (what the author has established):\n"
                      + profiles))
    try:
        from src.ai.story_memory import prompt_block
        memory = prompt_block(project, text[:2000], limit=4 if compact else 8)
        if memory:
            parts.append((RECORDS, memory))
    except Exception:
        pass
    if ledger:
        from src.ai.story_ledger import line
        parts.append(("ledger", "STYLE SHEET (facts established in earlier chapters; if this "
                      "chapter contradicts one, quote its words):\n"
                      + "\n".join("- " + line(f) for f in ledger)))
    ending = _previous_ending(book, chapter) if book is not None else ""
    if ending:
        parts.append((PREVIOUS, "HOW THE PREVIOUS CHAPTER ENDED:\n…" + ending))
    title = getattr(chapter, "title", "") or "this chapter"
    parts.append((HERE, f"CHAPTER ({title}):\n{excerpt}"))
    parts.append(("", RUBRIC))
    parts.append(("",
        f"Answer with at most {MAX_FINDINGS} lines, one per problem, in exactly these forms, "
        "or the single word NONE. Copy quoted words exactly from the text above.\n"
        "CHARACTER | \"the words in the chapter, 5 to 25 of them\" | \"the earlier words, "
        "or the words of the record, that they contradict\" | what differs, under 20 words\n"
        "JUMP | TIME or CAUSE or CHARACTER | \"the words where the jump lands\" | what the "
        "text does not bridge, under 20 words\n"
        "CONTINUITY | \"the words in the chapter\" | \"the earlier words they "
        "contradict\" | what differs, under 20 words"))
    parts.append(("", FACTS_ASK))
    return parts


def build_prompt(project: Any, chapter: Any, text: str, book: Any = None,
                 compact: bool = False, ledger: Optional[List[Dict[str, Any]]] = None) -> str:
    return "\n\n".join(t for _, t in sections(project, chapter, text, book, compact, ledger))


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(s.split()).lower()


def locate(text: str, quote: str) -> Optional[tuple]:
    """(start, end) of ``quote`` in ``text``, tolerant of quote marks, case
    and spacing; None when it isn't there."""
    quote = quote.strip().strip('"“”').strip()
    if len(quote) < 8:
        return None
    at = text.find(quote)
    if at >= 0:
        return at, at + len(quote)
    # Tolerant match: build a pattern from the words.
    words = re.findall(r"[A-Za-z0-9]+", quote)
    if len(words) < 3:
        return None
    pattern = r"\W+".join(re.escape(w) for w in words)
    m = re.search(pattern, text, re.I)
    return (m.start(), m.end()) if m else None


def parse(reply: str, text: str, context: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """{"character" | "jump" | "continuity": [{"quote", "why", "earlier", "start",
    "end"}]}. Dropped (and counted in "_dropped"): a finding whose quote isn't
    in ``text``; a character or continuity finding whose "earlier" words aren't
    in ``context`` (the chapter plus everything else the model was shown); a
    jump of place alone."""
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KINDS}
    dropped = 0
    seen = set()
    context = context or text
    for m in _LINE.finditer(reply or ""):
        kind = m.group(1).lower()
        fields = [f.strip().strip("*_ ") for f in m.group(2).split("|")]
        earlier, dimension = "", ""
        if kind == "jump":
            if len(fields) < 3:
                dropped += 1
                continue
            dimension, quote, why = fields[0].upper(), fields[1], fields[2]
            if dimension not in JUMP_KINDS or dimension == "PLACE":
                dropped += 1                         # place alone: the evidence is weak
                continue
        else:
            if len(fields) < 3:
                dropped += 1                         # nothing quoted that it contradicts
                continue
            quote, earlier, why = fields[0], fields[1], fields[2]
            found_earlier = locate(context, earlier)
            if found_earlier is None:
                dropped += 1
                continue
            earlier = context[found_earlier[0]:found_earlier[1]]
        where = locate(text, quote)
        if where is None:
            dropped += 1
            continue
        if earlier and _norm(earlier) == _norm(text[where[0]:where[1]]):
            dropped += 1                             # the same words can't contradict themselves
            continue
        key = (kind, where[0])
        if key in seen:
            continue
        seen.add(key)
        out[kind].append({"quote": text[where[0]:where[1]], "why": why, "earlier": earlier,
                          "dimension": JUMP_KINDS.get(dimension, ""),
                          "start": where[0], "end": where[1]})
    out["_dropped"] = dropped
    out["facts"] = parse_facts(reply, text)
    return out


def parse_facts(reply: str, text: str) -> List[Dict[str, Any]]:
    """[{"subject", "fact", "quote"}] the chapter establishes; a fact whose
    words aren't in the chapter is dropped."""
    out, seen = [], set()
    for m in _FACT.finditer(reply or ""):
        fields = [f.strip().strip("*_ ") for f in m.group(1).split("|")]
        if len(fields) < 3 or not fields[0] or not fields[1]:
            continue
        where = locate(text, fields[2])
        if where is None or where[0] in seen:
            continue
        seen.add(where[0])
        out.append({"subject": fields[0].strip('"“”'), "fact": fields[1].rstrip("."),
                    "quote": text[where[0]:where[1]]})
        if len(out) >= MAX_FACTS:
            break
    return out


def _where(earlier: str, parts: List[tuple], ledger: Optional[List[Dict[str, Any]]]) -> str:
    """Where the contradicted words come from, for the query."""
    want = _norm(earlier)
    for f in ledger or []:
        if want and want in _norm(f"{f['subject']}: {f['fact']} — {f['quote']}"):
            return f"In “{f.get('chapter', 'an earlier chapter')}”"
    for label in (HERE, PREVIOUS, RECORDS):
        if any(src == label and want in _norm(t) for src, t in parts):
            return label
    return HERE


def as_query(kind: str, finding: Dict[str, Any]) -> str:
    """The finding put as an editor's query: the two passages, what
    differs, and a question; it doesn't rule on which is right."""
    why = finding["why"].rstrip(".")
    if kind == "jump":
        return (f"A break in {finding['dimension']} the text doesn't bridge: {why}. "
                "Is the gap intended?")
    return (f"{finding.get('where') or HERE}: “{finding['earlier']}”. {why}. "
            "Which is intended?")


def read_chapter(llm: Any, project: Any, chapter: Any, text: str, book: Any = None,
                 compact: bool = False, ledger: Optional[List[Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    """The model's findings for one chapter, and the facts it establishes
    (``"facts"``). Raises when the model fails or its answer can't be read
    (the caller reports "could not check")."""
    parts = sections(project, chapter, text, book, compact, ledger)
    prompt = "\n\n".join(t for _, t in parts)
    reply = llm.generate_text(prompt, SYSTEM, max_tokens=1100, temperature=0.2) or ""
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply)
    except Exception:
        pass
    found = parse(reply, text, context=prompt)
    for kind in ("character", "continuity"):
        for f in found[kind]:
            f["where"] = _where(f["earlier"], parts, ledger)
    total = sum(len(found[k]) for k in KINDS)
    if (not total and not found["_dropped"] and not found["facts"]
            and "NONE" not in reply.upper()):
        raise RuntimeError("the model's answer couldn't be read")
    cap = MAX_WORDS_COMPACT if compact else MAX_WORDS
    found["_read_words"] = min(len(text.split()), cap)
    found["_total_words"] = len(text.split())
    return found
