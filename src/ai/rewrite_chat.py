"""A conversation about a passage and its rewrites.

Suggestions and Rephrase start as before — a first set of rewrites (and,
for Suggestions, a critique). After that the writer talks: asks why
("why is [2] out of order?"), gives direction ("darker, and keep Tobin
rambling"), or asks for edits ("combine 1 and 3"). Each turn the model
answers briefly and, only when the writer asked for changes, writes new
versions. New versions go through the same quality checks as the first
ones (one retry for serious problems) before the writer sees them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

MAX_TURNS = 8               # earlier turns kept in the prompt
MAX_TURN_CHARS = 700
MAX_VERSIONS_SHOWN = 6
MAX_NEW_VERSIONS = 3


@dataclass
class ChatTurn:
    role: str               # "author" | "editor"
    text: str


@dataclass
class ChatResult:
    reply: str
    versions: List[Any] = field(default_factory=list)    # passage_critique.Suggestion


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n - 1] + "…"


def build_chat_prompt(context: Sequence[Tuple[str, str]], passage: str,
                      versions: Sequence[Tuple[str, str]], turns: Sequence[ChatTurn],
                      message: str, rules: str = "") -> str:
    parts = [f"=== {title} ===\n{body.strip()}" for title, body in context if body and body.strip()]
    parts.append(f"=== THE AUTHOR'S PASSAGE ===\n{passage.strip()}")
    if versions:
        shown = list(versions)[:MAX_VERSIONS_SHOWN]
        parts.append("=== VERSIONS ON THE TABLE (the author refers to these by number) ===\n"
                     + "\n\n".join(f"[{i}]{f' ({label})' if label else ''} {text.strip()}"
                                   for i, (label, text) in enumerate(shown, 1)))
    if turns:
        recent = list(turns)[-MAX_TURNS:]
        parts.append("=== THE CONVERSATION SO FAR ===\n" + "\n".join(
            f"{'AUTHOR' if t.role == 'author' else 'EDITOR'}: {_clip(t.text, MAX_TURN_CHARS)}"
            for t in recent))
    parts.append(f"=== THE AUTHOR NOW SAYS ===\n{message.strip()}")
    parts.append(
        "Reply as the editor, conversationally, in two to five sentences that answer exactly "
        "what the author said. Refer to versions by their number. If the author asks for a "
        "change, new wording or another option — or a new version is the clearest answer — "
        "add one to three COMPLETE versions of the passage after your reply, each as:\n\n"
        "VERSION 1 (a few words on the approach):\n<the whole rewritten passage>\n"
        "WHY: <one sentence>\n\n"
        "If they only asked a question or wanted your opinion, just answer — no versions. "
        "Build on what the author has said throughout the conversation."
        + (f"\n\n{rules.strip()}" if rules.strip() else ""))
    return "\n\n".join(parts)


def parse_chat_reply(raw: str) -> ChatResult:
    """The editor's words, and any versions after them."""
    from src.ai.output_sanitizer import strip_meta_tokens, strip_passage_markers
    from src.ai.passage_critique import _SUGGESTION_RX, parse_critique
    text = strip_meta_tokens(raw or "")
    first = _SUGGESTION_RX.search(text)
    reply = text[:first.start()] if first else text
    reply = re.sub(r"^\s*(?:\*\*)?(?:editor|assistant|reply)(?:\*\*)?\s*:\s*", "", reply.strip(),
                   flags=re.I)
    reply = strip_passage_markers(reply).strip()
    versions = parse_critique(text[first.start():]).suggestions if first else []
    return ChatResult(reply=reply, versions=versions[:MAX_NEW_VERSIONS])


def chat_turn(llm: Any, *, system: str, context: Sequence[Tuple[str, str]], passage: str,
              versions: Sequence[Tuple[str, str]], turns: Sequence[ChatTurn], message: str,
              check: Optional[Callable[[List[Any]], List[Any]]] = None,
              rules: str = "") -> ChatResult:
    """One exchange. ``check(versions)`` returns a ``RewriteCheck`` per
    version (and may tidy them in place); versions with serious problems
    get one retry, and each keeps its notes."""
    prompt = build_chat_prompt(context, passage, versions, turns, message, rules)
    result = parse_chat_reply(llm.generate_text(prompt, system, max_tokens=1500,
                                                temperature=0.7))
    if not result.versions or check is None:
        if not result.reply and not result.versions:
            result.reply = "(The model didn't reply — try rephrasing your message.)"
        return result
    checks = check(result.versions)
    failed = [(v, c) for v, c in zip(result.versions, checks) if not c.ok]
    if failed:
        problems = "\n".join(f"- Your version {result.versions.index(v) + 1} "
                             f"{'; '.join(c.serious)}" for v, c in failed)
        retry = (prompt + "\n\nSOME OF YOUR VERSIONS WERE REJECTED:\n" + problems
                 + f"\nWrite {len(failed)} replacement version(s) that fix this, in the same "
                   "format (VERSION n (approach): … WHY: …), with no other text.")
        try:
            fresh = parse_chat_reply(llm.generate_text(retry, system, max_tokens=1200,
                                                       temperature=0.7)).versions
            fresh_checks = check(fresh) if fresh else []
            spare = sorted(zip(fresh, fresh_checks), key=lambda vc: vc[1].rank())
            for i, c in enumerate(checks):
                if not c.ok and spare and spare[0][1].rank() < c.rank():
                    result.versions[i], checks[i] = spare.pop(0)
        except Exception as e:
            print(f"[chat] retry failed: {e}")
    for v, c in zip(result.versions, checks):
        v.notes, v.voice_fit = c.notes, c.voice_fit
    from src.ai.rewrite_quality import best_first
    result.versions = [result.versions[i] for i in best_first(result.versions, checks)]
    if not result.reply:
        result.reply = f"Here {'is a new version' if len(result.versions) == 1 else 'are new versions'}."
    return result
