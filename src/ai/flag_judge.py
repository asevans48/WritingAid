"""A model decides which style, grammar and spelling flags are worth showing.

The checkers are deliberately eager: every passive, every adverb, every
LanguageTool rule, every word the dictionary doesn't know. Many of those
are fine — a passive that's the right choice, a fragment in dialogue, a
name or a word invented for the story's world. With a model configured
(local or cloud), the editor sends the flags near where you're working,
each with its sentence, and hides the ones the model judges false alarms.
Verdicts are cached, so each flag is judged once.

Without a model the quick rules apply instead: no adverb/passive/wordiness
flags inside dialogue (that's the character talking), no LanguageTool
"fragment / informal" flags inside dialogue, and an unknown word that you
use three or more times, and that isn't one letter off a common word, is
taken as intentional.
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

BATCH = 16
CATEGORIES = ("style", "grammar", "spelling")
LIMITS = {"style": 24, "grammar": 16, "spelling": 16}

SYSTEM = ("You are an experienced fiction editor reviewing an automatic checker's flags. "
          "You keep real problems and drop false alarms — dialogue, dialect, deliberate "
          "style, names and invented words are not errors.")

_QUESTIONS = {
    "style": ("Each item is a STYLE flag from an automatic checker (passive voice, adverb, "
              "long sentence, cliché, wordiness…) with its sentence. Would a skilled line "
              "editor change it? KEEP the flag if a rewrite would make the sentence sharper — "
              "this is the usual case: 'very' and similar intensifiers, an adverb propping up "
              "a weak verb ('walked slowly' → 'trudged'), a passive that hides who acted, "
              "padding. DROP it only when the original is clearly the better choice: a "
              "passive that rightly keeps the focus on the thing acted on, an adverb no verb "
              "could replace, a long sentence whose length serves the moment.",
              "KEEP", "DROP"),
    "grammar": ("Each item is a GRAMMAR flag with its sentence. KEEP it if it is a real error "
                "the author would want fixed; DROP it if it's a false alarm — dialogue, "
                "dialect, a deliberate fragment, a name, or a stylistic choice.",
                "KEEP", "DROP"),
    "spelling": ("Each item is a word the spellchecker doesn't know, with sentences it appears "
                 "in. Answer TYPO if it's a misspelling of a real word, or INTENDED if it's a "
                 "name, a word invented for this story's world, dialect, or a deliberate "
                 "spelling.",
                 "TYPO", "INTENDED"),
}

_CACHE: Dict[str, Tuple[bool, str]] = {}      # key → (keep the flag, reason)
_LOCK = threading.Lock()
_LINE_RX = re.compile(r"^\s*\**\s*(\d+)\s*[.):]?\s*\**\s*(?:[“\"'][^”\"'\n]*[”\"']\s*[—:\-–]?\s*)?"
                      r"\**\s*(KEEP|DROP|TYPO|INTENDED|REAL|FALSE ALARM|FINE)\b\**\s*[—:\-–]*\s*(.*)$",
                      re.I | re.M)
_QUOTE_RX = re.compile(r'"[^"\n]*"|“[^”\n]*”')


def key(category: str, text: str, sentence: str = "", kind: str = "") -> str:
    if category == "spelling":               # a word judged intentional is so everywhere
        raw = f"spelling|{(text or '').lower()}"
    else:
        raw = f"{category}|{kind}|{(text or '').lower()}|{' '.join((sentence or '').split())}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def verdict(category: str, text: str, sentence: str = "", kind: str = "") -> Optional[Tuple[bool, str]]:
    with _LOCK:
        return _CACHE.get(key(category, text, sentence, kind))


def dropped(category: str, text: str, sentence: str = "", kind: str = "") -> bool:
    """True when the model judged this flag a false alarm."""
    v = verdict(category, text, sentence, kind)
    return v is not None and not v[0]


def remember(found: Dict[str, Tuple[bool, str]]) -> None:
    with _LOCK:
        if len(_CACHE) > 20000:
            _CACHE.clear()
        _CACHE.update(found)


def build_prompt(category: str, items: List[Dict[str, Any]], context: str = "") -> str:
    question, yes, no = _QUESTIONS[category]
    lines = []
    for n, item in enumerate(items, 1):
        detail = f" — {item['detail']}" if item.get("detail") else ""
        sentences = item.get("sentences") or [item.get("sentence", "")]
        quotes = " ".join(f"«{s}»" for s in sentences if s)
        lines.append(f"{n}. “{item['text']}”{detail}: {quotes}")
    return ((f"{context.strip()}\n\n" if context.strip() else "")
            + question + "\n\n" + "\n".join(lines) + "\n\n"
            + f"Answer one line per item, in order, nothing else:\n1. {yes} — <why, under 12 words>"
              f"\n2. {no} — <why, under 12 words>")


def parse(category: str, reply: str, items: List[Dict[str, Any]]) -> Dict[str, Tuple[bool, str]]:
    from src.ai.output_sanitizer import strip_meta_tokens
    out: Dict[str, Tuple[bool, str]] = {}
    for m in _LINE_RX.finditer(strip_meta_tokens(reply or "")):
        n = int(m.group(1)) - 1
        if 0 <= n < len(items) and items[n]["key"] not in out:
            word = m.group(2).upper()
            keep = word in ("KEEP", "TYPO", "REAL")
            out[items[n]["key"]] = (keep, m.group(3).strip().strip("*_ "))
    return out


def judge(llm: Any, category: str, items: List[Dict[str, Any]], context: str = "") -> Dict[str, Tuple[bool, str]]:
    """Verdicts for ``items`` (cached ones included); items the model skipped
    stay unjudged and keep showing."""
    with _LOCK:
        found = {i["key"]: _CACHE[i["key"]] for i in items if i["key"] in _CACHE}
    todo = [i for i in items if i["key"] not in found]
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            reply = llm.generate_text(build_prompt(category, batch, context), SYSTEM,
                                      max_tokens=40 + 26 * len(batch), temperature=0.2)
        except Exception as e:
            print(f"[flags] {category} review failed: {e}")
            break
        got = parse(category, reply, batch)
        drops = sum(1 for keep, _ in got.values() if not keep)
        if category == "style" and got and drops > MAX_STYLE_DROP_SHARE * len(got):
            print(f"[flags] model dropped {drops}/{len(got)} style flags — keeping them all")
            got = {k: (True, "") for k in got}
        remember(got)
        found.update(got)
    return found


def enabled() -> bool:
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get("ai_flag_review", True))
    except Exception:
        return True


# ── Quick rules (no model) ───────────────────────────────────────────

DIALOGUE_STYLE_KINDS = {"adverb", "passive", "intensifier", "wordy", "repeated_start"}
# Only "this isn't a full sentence / formal enough" — real slips (commas,
# capitals, agreement) are still marked inside dialogue.
_DIALOGUE_GRAMMAR_HINTS = ("fragment", "informal", "colloquial", "incomplete", "missing verb")
# A model that calls most of a batch of style flags false alarms is being
# lenient, not discerning: its drops are ignored for that batch.
MAX_STYLE_DROP_SHARE = 0.5


def in_dialogue(paragraph: str, start: int, end: int) -> bool:
    return any(m.start() <= start and end <= m.end() for m in _QUOTE_RX.finditer(paragraph or ""))


def quick_style_ok(kind: str, paragraph: str, start: int, end: int) -> bool:
    """A style flag inside dialogue is the character's voice."""
    return kind in DIALOGUE_STYLE_KINDS and in_dialogue(paragraph, start, end)


def quick_grammar_ok(message: str, paragraph: str, start: int, end: int) -> bool:
    low = (message or "").lower()
    return in_dialogue(paragraph, start, end) and any(h in low for h in _DIALOGUE_GRAMMAR_HINTS)


def quick_word_intended(word: str, full_text: str, spell_checker: Any) -> bool:
    """Used three or more times, and not one slip from a common word."""
    if len(re.findall(rf"(?<![A-Za-z']){re.escape(word)}(?![A-Za-z'])", full_text or "")) < 3:
        return False
    try:
        return not spell_checker.looks_like_common_word_typo(word)
    except Exception:
        return False


# ── Collecting the flags to review ───────────────────────────────────

def collect(highlighter: Any, document: Any, around_block: int = 0) -> Dict[str, List[Dict[str, Any]]]:
    """Unjudged flags from the highlighter, nearest the writer first."""
    from src.ai.word_suggest import sentence_around
    from src.ui.enhanced_text_editor import ErrorType
    kinds = {ErrorType.STYLE: "style", ErrorType.GRAMMAR: "grammar",
             ErrorType.SPELLING: "spelling"}
    blocks = sorted(highlighter._errors.items(), key=lambda kv: abs(kv[0] - around_block))
    out: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    seen = set()
    for number, errors in blocks:
        block = document.findBlockByNumber(number)
        if not block.isValid():
            continue
        paragraph = block.text()
        for e in errors:
            category = kinds.get(e.error_type)
            if category is None or len(out[category]) >= LIMITS[category]:
                continue
            if category == "spelling" and not e.word[:1].isupper():
                continue                    # lowercase misspellings always show
            sentence = sentence_around(paragraph, e.start, e.end).text
            kind = getattr(e, "style_kind", "") if category == "style" else ""
            k = key(category, e.word, sentence, kind)
            if k in seen or verdict(category, e.word, sentence, kind) is not None:
                continue
            seen.add(k)
            item = {"key": k, "category": category, "text": e.word,
                    "detail": "" if category == "spelling" else (e.reason or "")[:120],
                    "sentence": sentence}
            if category == "spelling":
                item["sentences"] = [sentence]
            out[category].append(item)
    return {c: items for c, items in out.items() if items}


def spelling_context(project: Any) -> str:
    """Names in the story, so the model recognises its world's words."""
    if project is None:
        return ""
    names = [c.name for c in getattr(project, "characters", None) or [] if c.name]
    try:
        from src.ai.canon_index import collect_world_entities
        names += [e.name for e in collect_world_entities(getattr(project, "worldbuilding", None))]
    except Exception:
        pass
    return ("Names and terms in this story: " + ", ".join(names[:60]) + ".") if names else ""
