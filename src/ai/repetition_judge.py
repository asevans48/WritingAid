"""Does this repetition weaken the writing? — a model decides.

A chapter is full of words used three or four times; most of those
repeats are harmless (needed, deliberate, too far apart to notice).
For the light repeats the overuse checker isn't sure about, the model
sees each word or phrase with the sentences it's in and says whether
the repetition makes the writing less powerful — a noticeable echo, a
lazy default, a pet word, monotony — or is fine. Only flagged ones are
marked. Batched (one short call per ~20 items) and cached, so it runs
once per chapter in the background and again only for what changed.
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Dict, Iterable, List, Tuple

BATCH = 20
SYSTEM = ("You are a sharp line editor judging repetition in fiction. You keep "
          "deliberate, necessary and unnoticeable repeats, and flag the ones that "
          "weaken the prose.")

_CACHE: Dict[Tuple[str, str], Tuple[bool, str]] = {}
_LOCK = threading.Lock()
_LINE_RX = re.compile(
    r"^\s*(?:\*\*)?\s*(\d+)\s*[.):]?\s*(?:\*\*)?\s*(?:[“\"'][^”\"']*[”\"']\s*[—:\-–]?\s*)?"
    r"(?:\*\*)?\s*(FLAG|FLAGGED|VARY|CHANGE|WEAK|OK|KEEP|FINE|ALLOW)\b(?:\*\*)?\s*[—:\-–]*\s*(.*)$",
    re.I | re.M)


def _fingerprint(item: Dict[str, Any]) -> str:
    raw = "\n".join(item.get("sentences") or []) + f"|{item.get('count', 0)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def cached_verdicts(items: Iterable[Dict[str, Any]]) -> Dict[str, Tuple[bool, str]]:
    with _LOCK:
        return {i["key"]: _CACHE[(i["key"], _fingerprint(i))] for i in items
                if (i["key"], _fingerprint(i)) in _CACHE}


def build_prompt(items: List[Dict[str, Any]], context: str = "") -> str:
    lines = []
    for n, item in enumerate(items, 1):
        kind = "phrase" if item["key"].startswith("p:") else "word"
        quotes = " ".join(f"«{s}»" for s in item.get("sentences") or [])
        lines.append(f"{n}. {kind} “{item['text']}” ({item['count']} times): {quotes}")
    return ((f"{context.strip()}\n\n" if context.strip() else "")
            + "Below are words and phrases a writer repeats in one chapter, each with the "
            "sentences it appears in.\n\n" + "\n".join(lines) + "\n\n"
            "For each one decide: does the repetition make the writing LESS POWERFUL — a "
            "noticeable echo, a vague or lazy default word, a pet word, a monotonous pattern "
            "— so the writer should vary it? Or is it fine — necessary (no good alternative), "
            "deliberate (a motif, rhythm, a callback), a name or a technical term, or far "
            "enough apart that no reader notices?\n\n"
            "Answer one line per item, in order, nothing else:\n"
            "1. FLAG — <why it weakens the writing, under 15 words>\n"
            "2. OK — <why it's fine, under 10 words>")


def parse(reply: str, items: List[Dict[str, Any]]) -> Dict[str, Tuple[bool, str]]:
    from src.ai.output_sanitizer import strip_meta_tokens
    out: Dict[str, Tuple[bool, str]] = {}
    for m in _LINE_RX.finditer(strip_meta_tokens(reply or "")):
        n = int(m.group(1)) - 1
        if 0 <= n < len(items) and items[n]["key"] not in out:
            flag = m.group(2).upper() in ("FLAG", "FLAGGED", "VARY", "CHANGE", "WEAK")
            reason = m.group(3).strip().strip("*_ ").rstrip(".")
            out[items[n]["key"]] = (flag, (reason + ".") if reason else "")
    return out


def judge(llm: Any, items: List[Dict[str, Any]], context: str = "") -> Dict[str, Tuple[bool, str]]:
    """Verdicts ``key → (weakens the writing, reason)`` for ``items``; items
    the model skipped are left out (the caller's fallback applies)."""
    verdicts = cached_verdicts(items)
    todo = [i for i in items if i["key"] not in verdicts]
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            reply = llm.generate_text(build_prompt(batch, context), SYSTEM,
                                      max_tokens=60 + 30 * len(batch),
                                      temperature=0.2)
        except Exception as e:
            print(f"[repetition] judge failed: {e}")
            break
        found = parse(reply, batch)
        with _LOCK:
            if len(_CACHE) > 4000:
                _CACHE.clear()
            for item in batch:
                if item["key"] in found:
                    _CACHE[(item["key"], _fingerprint(item))] = found[item["key"]]
        verdicts.update(found)
    return verdicts


def enabled() -> bool:
    """The writer can turn the model review off (``ai_repetition_review``)."""
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get("ai_repetition_review", True))
    except Exception:
        return True
