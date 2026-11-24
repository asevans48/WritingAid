"""Proofreading with a model (piece P.4): corrections only, and only small ones.

A capable model reads for errors better than rules do, but it also rewrites
things it should leave alone. So the model is asked for corrections only,
and a correction is kept only if:

* its words are in the text, exactly;
* it is a small change: at most three words differ, the rest of the
  sentence is untouched;
* it isn't just a different style of quote mark or dash;
* it doesn't change a name or a word from the project (characters, places,
  the dictionary, allowed words);
* inside dialogue, it corrects a misspelling or a doubled word and nothing
  else, so speech quirks and dialect are left to the writer.

Kept corrections go to ``proof_store``; the editor's grammar check reads
them, so they show as ordinary grammar flags with the model named as the
source, and the readiness check "Spelling and grammar left" counts them.

A paragraph is proofread once and remembered by its exact words; only new
or changed paragraphs are sent again. Cloud models read about 1,200 words a
request, on-device models about 350.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.utils import proof_store

CHUNK_WORDS = 1200
CHUNK_WORDS_COMPACT = 350
MAX_QUOTED_WORDS = 8
MAX_CHANGED_WORDS = 3

SYSTEM = ("You are a proofreader for a novel. You correct only definite errors and change "
          "as little as possible. You never improve style or word choice.")

_LINE = re.compile(r"^\W*[\"“](.+?)[\"”]\s*(?:->|→|=>|-->)\s*[\"“](.*?)[\"”]\s*(?:\|\s*(.*))?$",
                   re.M)
_QUOTE_RX = re.compile(r"[\"“][^\"“”]*[\"”]")


def build_prompt(chunk: str, names: List[str]) -> str:
    known = ("These names and words are correct, never change them: "
             + ", ".join(names[:60]) + "\n\n") if names else ""
    return (
        "Proofread the text below. List only definite errors: a misspelling, a wrong word "
        "(their/there, then/than, its/it's, could of), a missing or doubled word, "
        "subject–verb agreement, a tense slip, a missing apostrophe, wrong punctuation or "
        "a missing capital.\n"
        "Leave alone: style, word choice, sentence fragments, dialect and speech quirks "
        "inside quotation marks, names and invented words, British or older spellings, "
        "and anything that could be the author's choice.\n\n" + known +
        "One line per error. Copy the wrong words exactly as they stand (2 to 6 words, "
        "with a neighbouring word so the place is clear), then the same words corrected:\n"
        "\"wrong words\" -> \"corrected words\" | what is wrong, under 8 words\n"
        "If there are no errors, answer NONE.\n\nTEXT:\n" + chunk)


def _plain(s: str) -> str:
    """For comparing: quote and dash styles don't count as a change."""
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), ("—", "-"), ("–", "-"),
                 ("--", "-"), ("…", "...")):
        s = s.replace(a, b)
    return " ".join(s.split())


def _word(token: str) -> str:
    return re.sub(r"^[^\w']+|[^\w']+$", "", token).lower().replace("’", "'")


def narrow(original: str, corrected: str) -> Optional[Tuple[int, int, str]]:
    """(start, end, replacement) of the words that differ, within
    ``original``; None when the change isn't a small correction."""
    if _plain(original) == _plain(corrected):
        return None                                   # only quote or dash style
    o = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+", original)]
    r = corrected.split()
    if not o or len(o) > MAX_QUOTED_WORDS or len(r) > MAX_QUOTED_WORDS + 2:
        return None
    pre = 0
    while pre < len(o) and pre < len(r) and o[pre][2] == r[pre]:
        pre += 1
    post = 0
    while (post < len(o) - pre and post < len(r) - pre
           and o[len(o) - 1 - post][2] == r[len(r) - 1 - post]):
        post += 1
    a, b = pre, len(o) - post                         # the differing words of the original
    ra, rb = pre, len(r) - post
    if max(b - a, rb - ra) > MAX_CHANGED_WORDS:
        return None                                   # a rewrite, not a correction
    if a == b or ra == rb:
        # A missing word, or a word to remove (a doubled word): take a
        # neighbour in, so there are words to flag and words to suggest.
        if a > 0 and ra > 0:
            a, ra = a - 1, ra - 1
        elif b < len(o) and rb < len(r):
            b, rb = b + 1, rb + 1
        else:
            return None
    replacement = " ".join(r[ra:rb])
    if not replacement.strip():
        return None
    return o[a][0], o[b - 1][1], replacement


def keep(paragraph: str, start: int, end: int, replacement: str,
         is_known: Callable[[str], bool], protected: Set[str]) -> bool:
    """Whether a narrowed correction may be shown (see the module notes)."""
    words = [_word(t) for t in paragraph[start:end].split()]
    words = [w for w in words if w]
    new = [_word(t) for t in replacement.split()]
    changed = [w for w in words if w not in new]
    if any(w in protected or w.rstrip("s").rstrip("'") in protected for w in changed):
        return False                                  # a name or a word of the project
    in_speech = any(m.start() <= start and end <= m.end()
                    for m in _QUOTE_RX.finditer(paragraph))
    if in_speech:
        doubled = any(x == y for x, y in zip(words, words[1:]))
        misspelt = any(w.isalpha() and not is_known(w) for w in changed)
        if not (doubled or misspelt):
            return False                              # speech is the character's
    return True


def parse(reply: str, paragraphs: List[str], is_known: Callable[[str], bool],
          protected: Set[str]) -> Dict[int, List[Dict[str, Any]]]:
    """{paragraph index: [{"s", "e", "t", "r", "w"}]} for the corrections kept."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    for m in _LINE.finditer(reply or ""):
        original, corrected, why = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "")
        for n, para in enumerate(paragraphs):
            at = para.find(original)
            if at < 0:
                continue
            core = narrow(original, corrected)
            if core is None:
                break
            s, e, repl = at + core[0], at + core[1], core[2]
            if not keep(para, s, e, repl, is_known, protected):
                break
            taken = out.setdefault(n, [])
            if not any(c["s"] < e and s < c["e"] for c in taken):
                taken.append({"s": s, "e": e, "t": para[s:e], "r": repl,
                              "w": why.strip().rstrip(".")[:80]})
            break
    return out


def _chunks(paragraphs: List[str], cap: int) -> List[List[str]]:
    out, cur, size = [], [], 0
    for p in paragraphs:
        n = len(p.split())
        if cur and size + n > cap:
            out.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        out.append(cur)
    return out


def requests_needed(text: str, compact: bool = False) -> int:
    todo = [p for p in dict.fromkeys(text.split("\n")) if p.strip() and not proof_store.has(p)]
    return len(_chunks(todo, CHUNK_WORDS_COMPACT if compact else CHUNK_WORDS))


def proofread_text(llm: Any, text: str, *, compact: bool = False,
                   is_known: Callable[[str], bool] = lambda w: True,
                   protected: Optional[Set[str]] = None, names: Optional[List[str]] = None,
                   project: Any = None, stop: Optional[Callable[[], bool]] = None) -> int:
    """Proofread the paragraphs not yet read; returns how many requests
    were made. Raises when the model fails (what was read stays stored)."""
    protected = protected or set()
    todo = [p for p in dict.fromkeys(text.split("\n")) if p.strip() and not proof_store.has(p)]
    model = str(getattr(llm, "model", "") or "")
    made, done = 0, []
    try:
        for chunk in _chunks(todo, CHUNK_WORDS_COMPACT if compact else CHUNK_WORDS):
            if stop is not None and stop():
                break
            reply = llm.generate_text(build_prompt("\n\n".join(chunk), names or []), SYSTEM,
                                      max_tokens=700, temperature=0.0) or ""
            made += 1
            if reply.startswith("Error generating text:"):
                raise RuntimeError(reply.split(":", 1)[1].strip())
            try:
                from src.ai.output_sanitizer import strip_meta_tokens
                reply = strip_meta_tokens(reply)
            except Exception:
                pass
            found = parse(reply, chunk, is_known, protected)
            if not found and not _LINE.search(reply) and "NONE" not in reply.upper():
                raise RuntimeError("the model's answer couldn't be read")
            for n, para in enumerate(chunk):
                proof_store.put(para, found.get(n, []), model)
            done.extend(chunk)
    finally:
        if project is not None and done:
            proof_store.save(project, done)
    return made


def add_findings(result: Any, llm: Any, text: str, ctx: Any, compact: bool = False) -> int:
    """Proofread the chapter and add what was kept to the "Spelling and
    grammar left" result (``readiness.CheckResult``); returns how many were
    added. Called while the model judges the chapter."""
    from src.ai.readiness import Item
    from src.utils.editor_flags import allowed_words, project_vocabulary
    scanner = getattr(ctx, "_scanner", None)
    spell = getattr(getattr(scanner, "state", None), "spell_checker", None)
    is_known = (lambda w: bool(spell._is_known(w))) if spell is not None else (lambda w: True)
    words, names = project_vocabulary(ctx.project)
    protected = set()
    for w in list(words) + list(names) + list(allowed_words(ctx.project)):
        protected.update(part.lower() for part in re.findall(r"[^\W\d_]+", str(w)))
    proof_store.load(ctx.project)
    proofread_text(llm, text, compact=compact, is_known=is_known, protected=protected,
                   names=sorted({str(n) for n in names})[:60], project=ctx.project)
    added, pos = 0, 0
    for para in text.split("\n"):
        for c in proof_store.corrections(para) if para.strip() else ():
            s, e = pos + c["s"], pos + c["e"]
            if text[s:e] != c["t"] or any(i.start < e and s < i.end for i in result.items):
                continue                               # a rule already flags these words
            result.items.append(Item(
                start=s, end=e, text=c["t"][:200],
                reason=(c.get("w") or "Possible error") + " (found by the model)",
                kind="grammar", key=f"grammar:{proof_store.RULE_ID}:{c['t'].lower()}",
                suggestions=[c["r"]], verdict="problem", paragraph=ctx.paragraph_of(s)))
            added += 1
        pos += len(para) + 1
    result.count += added
    return added
