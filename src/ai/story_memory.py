"""Story memory — the decisions a writer has settled.

"Tobin doesn't know about the schedule", "the pier burns in chapter 9",
"Mara never apologises". Captured from the AI chat, the Suggestions and
Rephrase conversations, or typed in; every AI tool reads them so the
companion stops forgetting what was decided. Pinned entries always go
into prompts; others when they're relevant to the text at hand.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

MAX_IN_PROMPT = 8
# Phrases that mark a writer settling something, worth offering to remember.
DECISION_CUES = re.compile(
    r"\b(?:let'?s|we(?:'ll| will) (?:go with|make|keep|have)|decided?|from now on|going forward|"
    r"(?:should|must|will) (?:never|always)|never (?:let|have|make)|always (?:have|make|keep)|"
    r"(?:is|was) actually|canon(?:ically)?|make (?:it|him|her|them) so|keep (?:it|him|her|them)|"
    r"doesn'?t know|don'?t want|I want (?:him|her|them|it|the)|remember that|"
    r"should (?:be|have|stay|remain)|(?:is|are|was|were) (?:named|called)|"
    r"(?:his|her|their|its) name is|name (?:him|her|it|them)|will be|is going to be|"
    r"turns out|in fact)\b", re.I)

_STOP = set("""the a an and or but of to in on at by for with from as is was were be been are it its
this that these those not no so than then into about over his her him she he they them their
there here had has have did does do would could should will just only very what when where
which who whom while all any each some never always""".split())


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def entries(project: Any, *, include_suggested: bool = False) -> list:
    out = list(getattr(project, "story_memory", None) or [])
    return out if include_suggested else [e for e in out if e.status == "active"]


def relevant(project: Any, text: str = "", limit: int = MAX_IN_PROMPT) -> list:
    """Pinned entries, then the active ones that share words with ``text``,
    then the newest — up to ``limit``."""
    active = entries(project)
    pinned = [e for e in active if e.pinned]
    rest = [e for e in active if not e.pinned]
    probe = _words(text)
    names = {w.lower() for c in getattr(project, "characters", None) or []
             for w in (c.name or "").split()}
    scored = sorted(rest, key=lambda e: (-len(_words(e.text) & probe)
                                         - 2 * len(_words(e.text) & probe & names),
                                         -e.created_at.timestamp()))
    chosen = pinned + [e for e in scored if not probe or _words(e.text) & probe]
    if len(chosen) < limit:
        chosen += [e for e in scored if e not in chosen]
    return chosen[:limit]


def prompt_block(project: Any, text: str = "", limit: int = MAX_IN_PROMPT) -> str:
    chosen = relevant(project, text, limit) if project is not None else []
    if not chosen:
        return ""
    return ("STORY DECISIONS the author has settled (always respect these):\n"
            + "\n".join(f"- {e.text}" for e in chosen))


def add(project: Any, text: str, *, source: str = "manual", pinned: bool = False,
        suggested: bool = False):
    """Add an entry (skipping a near-duplicate). Returns it, or None."""
    from src.models.project import StoryMemoryEntry
    text = " ".join((text or "").split()).strip()
    if len(text) < 4 or project is None:
        return None
    mine = _words(text)
    for e in getattr(project, "story_memory", None) or []:
        theirs = _words(e.text)
        if e.text.lower() == text.lower() or (mine and theirs
                                              and len(mine & theirs) / len(mine | theirs) > 0.8):
            return None
    entry = StoryMemoryEntry(text=text[:400], pinned=pinned, source=source,
                             status="suggested" if suggested else "active")
    project.story_memory.append(entry)
    return entry


def remove(project: Any, entry_id: str) -> None:
    project.story_memory = [e for e in project.story_memory if e.id != entry_id]


def accept(project: Any, entry_id: str) -> None:
    for e in project.story_memory:
        if e.id == entry_id:
            e.status = "active"


def has_decision(message: str) -> bool:
    return bool(DECISION_CUES.search(message or ""))


EXTRACT_SYSTEM = ("You keep a fiction writer's story bible. You extract only decisions the "
                  "writer has clearly settled — facts, rules, character truths, plot "
                  "commitments — never opinions, questions or passing ideas.")


def extract_decisions(llm: Any, message: str, reply: str = "") -> List[str]:
    """Decisions in the writer's message (the reply gives context). [] when
    there aren't any."""
    if llm is None or not has_decision(message):
        return []
    prompt = (f"THE WRITER SAID:\n{message.strip()}\n\n"
              + (f"THE ASSISTANT REPLIED (context only):\n{reply.strip()[:800]}\n\n" if reply else "")
              + "List each story decision the WRITER settled in their message, one per line, "
                "as a short standalone fact (e.g. \"Tobin doesn't know about the schedule.\"). "
                "Use names, not pronouns. If they settled nothing, answer NONE.\n"
                "DECISION: …")
    try:
        raw = llm.generate_text(prompt, EXTRACT_SYSTEM, max_tokens=160, temperature=0.2)
    except Exception as e:
        print(f"[memory] extraction failed: {e}")
        return []
    from src.ai.output_sanitizer import strip_meta_tokens
    out = []
    for line in strip_meta_tokens(raw).splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])?\s*(?:\*\*)?(?:decision)?(?:\*\*)?\s*:?\s*", "",
                      line, flags=re.I).strip().strip("\"“”")
        if line and line.upper() != "NONE" and len(line) >= 8 and not line.endswith("?"):
            out.append(line)
    return out[:3]
