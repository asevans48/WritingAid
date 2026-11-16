"""In-context replacements for an overused word — one quick model call.

The synonym list can't tell "she looked exhausted" from "she looked at
him". Given the word's sentence (and the one before it), the model
offers replacements that fit this sense and form, and a couple of
rewrites of the sentence that avoid the word altogether — often the
better fix for overuse. Small prompt, short answer, cached per sentence.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SYSTEM = ("You are a precise line editor. You suggest words that fit a sentence exactly "
          "— same meaning, same grammatical form, same tone — and nothing else.")
MAX_WORDS = 6
MAX_REWRITES = 2


@dataclass
class Sentence:
    text: str
    start: int            # offsets in the paragraph
    end: int
    previous: str = ""


@dataclass
class WordSuggestions:
    words: List[str] = field(default_factory=list)
    rewrites: List[str] = field(default_factory=list)


def sentence_around(paragraph: str, start: int, end: int) -> Sentence:
    """The sentence holding ``paragraph[start:end]`` and the one before it."""
    from src.ai.passage_critique import _sentence_spans
    spans = _sentence_spans(paragraph or "")
    for i, (s, e) in enumerate(spans):
        if s <= start < e or (s < end <= e):
            prev = paragraph[spans[i - 1][0]:spans[i - 1][1]] if i else ""
            return Sentence(paragraph[s:max(e, end)], s, max(e, end), prev)
    return Sentence(paragraph, 0, len(paragraph))


_CACHE: Dict[Tuple[str, str], WordSuggestions] = {}
_LOCK = threading.Lock()
_LLM: Dict[str, Any] = {}


def cached(word: str, sentence: str) -> Optional[WordSuggestions]:
    with _LOCK:
        return _CACHE.get((word.lower(), sentence))


# ── Set phrases ("mobile home", "home run") ──────────────────────────

@dataclass
class Compound:
    phrase: str
    start: int            # offsets in the paragraph
    end: int
    synonyms: List[str] = field(default_factory=list)   # for the whole phrase


_TOKEN_RX = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")


def compound_around(paragraph: str, start: int, end: int) -> Optional[Compound]:
    """The set phrase (WordNet compound) the word at ``start:end`` belongs to,
    e.g. "home" in "a mobile home park" → "mobile home"."""
    try:
        from src.utils.thesaurus import _ensure_wordnet
        if not _ensure_wordnet():
            return None
        from nltk.corpus import wordnet as wn
    except Exception:
        return None
    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RX.finditer(paragraph or "")]
    idx = next((i for i, (_, s, e) in enumerate(tokens) if s <= start < e), None)
    if idx is None:
        return None
    # Longest first: three words, then two; the phrase must contain the word.
    for size in (3, 2):
        for first in range(idx - size + 1, idx + 1):
            if first < 0 or first + size > len(tokens):
                continue
            span = tokens[first:first + size]
            # Words separated by more than a space (", ") aren't a compound.
            if any(paragraph[a[2]:b[1]] not in (" ", "-") for a, b in zip(span, span[1:])):
                continue
            key = "_".join(t[0].lower() for t in span)
            synsets = wn.synsets(key)
            if not synsets:
                continue
            phrase = paragraph[span[0][1]:span[-1][2]]
            others = []
            for syn in synsets[:1]:                  # the phrase's main meaning
                for lemma in syn.lemmas():
                    name = lemma.name().replace("_", " ")
                    if name.lower() != phrase.lower() and name not in others:
                        others.append(name)
            return Compound(phrase, span[0][1], span[-1][2], others[:6])
    return None


def get_llm():
    """The writing model (the Rephrase task model, else the default), built
    once — a local model's weights are shared with the other tools."""
    with _LOCK:
        if "llm" in _LLM:
            return _LLM["llm"]
    from src.ai.task_llm import build_default_llm, build_task_llm_override
    llm = build_task_llm_override("rephrase") or build_default_llm()
    with _LOCK:
        if llm is not None:
            _LLM["llm"] = llm
    return llm


def build_prompt(word: str, sentence: Sentence, count: int = 0) -> str:
    often = f" It appears {count} times in this chapter, so the writer wants variety." \
        if count > 1 else ""
    phrase_note = (f" If “{word}” is part of a name or set phrase in this sentence, a "
                   f"replacement must fit the whole phrase — never swap one word of it on "
                   f"its own.")
    prev = f"Sentence before: {sentence.previous.strip()}\n" if sentence.previous.strip() else ""
    return (f"{prev}Sentence: {sentence.text.strip()}\n\n"
            f"The word “{word}” is overused.{often}{phrase_note}\n"
            f"1. Give up to {MAX_WORDS - 1} single words or short phrases that could replace "
            f"“{word}” in THIS sentence: the same meaning here, the same grammatical form "
            f"(tense, number), fitting the tone. No near-misses. The rest of the sentence must "
            f"still read correctly with the replacement in place."
            + (f" “{word}” is one phrase: each replacement takes the place of ALL of it and "
               f"must read correctly there on its own (a whole noun phrase, not one modifier)."
               if " " in word.strip() else "") + "\n"
            f"2. Give {MAX_REWRITES} rewrites of the whole sentence that avoid “{word}” "
            f"(and its other forms) while keeping its meaning, point of view and tense — "
            f"complete, grammatical sentences.\n\n"
            "Answer exactly like this:\nWORDS: first; second; third\nREWRITE: …\nREWRITE: …")


def _forms(word: str) -> List[str]:
    from src.utils.word_forms import base_of, inflect
    base = base_of(word)
    return list({word.lower(), base, inflect(base, "past"), inflect(base, "ing"),
                 inflect(base, "s")})


def _following_word(word: str, sentence: str) -> str:
    m = re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])\s+([A-Za-z'’-]+)", sentence or "",
                  re.I)
    return m.group(1).lower() if m else ""


def _spelled_ok(candidate: str, sentence: str) -> bool:
    """Every word of the candidate is real (or appears in the sentence)."""
    from src.ai.rewrite_quality import _known_word
    in_sentence = {w.lower() for w in re.findall(r"[A-Za-z]+", sentence or "")}
    for token in re.findall(r"[A-Za-z]+", candidate):
        low = token.lower()
        if low in in_sentence or token[:1].isupper() and token != candidate.split()[0]:
            continue
        if not _known_word(low):
            return False
    return True


def parse(reply: str, word: str, sentence: str) -> WordSuggestions:
    from src.ai.output_sanitizer import strip_meta_tokens
    text = strip_meta_tokens(reply or "")
    out = WordSuggestions()
    banned = _forms(word)
    has_word = re.compile(r"\b(?:" + "|".join(re.escape(f) for f in banned) + r")\b", re.I)
    following = _following_word(word, sentence)
    m = re.search(r"WORDS?\s*:\s*(.+)", text, re.I)
    if m:
        for raw in re.split(r"[;,|/]", m.group(1)):
            w = raw.strip().strip("*_\"“”'.").strip()
            # "trailer park" for "mobile home" in "mobile home park": the model
            # replaced a wider span; keep what replaces our span ("trailer").
            parts = w.split()
            if following and parts and parts[-1].lower() == following:
                w = " ".join(parts[:-1])
            if (w and len(w.split()) <= 3 and not has_word.search(w) and _spelled_ok(w, sentence)
                    and w.lower() not in (x.lower() for x in out.words)):
                if word[:1].isupper():
                    w = w[:1].upper() + w[1:]
                out.words.append(w)
    n_words = len(sentence.split())
    for m in re.finditer(r"REWRITE\s*\d*\s*:\s*(.+)", text, re.I):
        r = m.group(1).strip().strip("*_").strip()
        if len(r) > 1 and r[0] in "\"“" and r[-1] in "\"”" and r.count(r[0]) == 2:
            r = r[1:-1].strip()
        if (r and not has_word.search(r) and r != sentence.strip()
                and 0.5 <= len(r.split()) / max(n_words, 1) <= 1.8):
            out.rewrites.append(r)
    out.words = out.words[:MAX_WORDS]
    out.rewrites = out.rewrites[:MAX_REWRITES]
    return out


def suggest(llm: Any, word: str, sentence: Sentence, count: int = 0) -> WordSuggestions:
    key = (word.lower(), sentence.text)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    reply = llm.generate_text(build_prompt(word, sentence, count), SYSTEM,
                              max_tokens=160, temperature=0.4)
    result = parse(reply, word, sentence.text)
    if result.words or result.rewrites:
        with _LOCK:
            if len(_CACHE) > 500:
                _CACHE.clear()
            _CACHE[key] = result
    return result
