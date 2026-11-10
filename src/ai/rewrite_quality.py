"""Quality checks and learned examples for AI rewrites.

Shared by Suggestions and Rephrase:

* ``check_rewrite`` — deterministic checks a model (local ones especially)
  often fails: misspelled or invented names, a switch of point of view or
  tense, a wildly different length, text copied from around the passage,
  new clichés / adverbs / passive voice, and drift from the author's
  measured voice. "Serious" problems mean the rewrite should be replaced.
* ``examples_prompt`` — the writer's own best-rated past rewrites (and
  ones they rejected), as examples for the next prompt.
* ``diff_html`` — word-level changes between the original and a rewrite.
"""

from __future__ import annotations

import difflib
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence, Tuple

_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_NAME_RX = re.compile(r"(?<![A-Za-z'’])([A-Z][a-z]+(?:[-'’][A-Za-z]+)*)")
_QUOTE_RX = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_FIRST = {"i", "me", "my", "mine", "myself"}
_FIRST_PLURAL = {"we", "us", "our", "ours", "ourselves"}
_THIRD = {"he", "she", "him", "her", "his", "hers", "himself", "herself",
          "they", "them", "their", "themselves"}
_PAST = {"was", "were", "had", "did", "said", "went", "came", "saw", "knew", "thought",
         "felt", "looked", "turned", "ran", "took", "made", "stood", "sat"}
_PRESENT = {"is", "are", "has", "does", "says", "goes", "comes", "sees", "knows", "thinks",
            "feels", "looks", "turns", "am", "runs", "takes", "makes", "stands", "sits"}
_LENGTH_WORDS = ("short", "long", "length", "expand", "cut", "trim", "condense", "brief",
                 "concise", "elaborate", "more detail", "fewer words")
_STYLE_KINDS = {"cliche": "a cliché", "adverb": "-ly adverbs", "passive": "passive voice",
                "intensifier": "weak intensifiers", "wordy": "wordy phrasing"}
_COMMON_CAPS = {"I", "God", "Mr", "Mrs", "Ms", "Dr", "Sir", "Lady", "Lord", "Captain",
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                "January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December", "English", "OK"}
_dictionary = None


def _known_word(word: str) -> bool:
    """Is ``word`` ordinary English (so a capital is just emphasis)?"""
    global _dictionary
    if _dictionary is None:
        try:
            from spellchecker import SpellChecker
            _dictionary = SpellChecker()
        except Exception:
            _dictionary = False
    return bool(_dictionary) and bool(_dictionary.known([word.lower()]))


def _narration(text: str) -> str:
    return _QUOTE_RX.sub(" ", text or "")


def _words(text: str) -> List[str]:
    return [w.lower().replace("’", "'") for w in _WORD_RX.findall(text or "")]


def person_and_tense(text: str) -> Tuple[str, str]:
    """('first'|'third'|'', 'past'|'present'|'') of the narration, or ''
    when there's too little signal to say."""
    counts = Counter(_words(_narration(text)))
    first = sum(counts[w] for w in _FIRST)
    third = sum(counts[w] for w in _THIRD)
    person = ("first" if first >= 2 and first > third * 0.5 else
              "third" if third >= 2 and first == 0 else "")
    past = sum(counts[w] for w in _PAST) + sum(n for w, n in counts.items()
                                                if w.endswith("ed") and len(w) > 4)
    present = sum(counts[w] for w in _PRESENT)
    tense = ("past" if past >= 2 and past > present * 2 else
             "present" if present >= 2 and present > past * 2 else "")
    return person, tense


@dataclass
class RewriteCheck:
    serious: List[str] = field(default_factory=list)   # replace the rewrite
    minor: List[str] = field(default_factory=list)     # show as a note
    voice_fit: Optional[float] = None

    @property
    def ok(self) -> bool:
        return not self.serious

    @property
    def notes(self) -> List[str]:
        return self.serious + self.minor

    def rank(self) -> Tuple[int, int, float]:
        return (len(self.serious), len(self.minor), -(self.voice_fit or 0.0))


def _name_problems(candidate: str, context: str, known_names: Iterable[str]) -> List[str]:
    def bare(word: str) -> str:            # "Mara's" → "Mara"
        return re.sub(r"[’']s?$", "", word)

    known_tokens = {bare(t) for n in known_names for t in re.findall(r"[A-Za-z][A-Za-z'’\-]+", n)}
    in_context = {bare(w) for w in _NAME_RX.findall(context)}
    out, seen = [], set()
    for m in _NAME_RX.finditer(candidate):
        word = bare(m.group(1))
        if word in seen or word in known_tokens or word in in_context or word in _COMMON_CAPS:
            continue
        seen.add(word)
        before = candidate[:m.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?…\"“”'’:—\n"
        ordinary = _known_word(word)
        close = difflib.get_close_matches(word, known_tokens, n=1, cutoff=0.8)
        if close and not (ordinary and sentence_start):
            out.append(f"spells “{word}” — your notes have “{close[0]}”")
            continue
        if not sentence_start and not ordinary:
            out.append(f"introduces “{word}”, which isn't in the passage or your notes")
    return out


def _copied_context(candidate: str, original: str, around: str, n: int = 8) -> bool:
    def grams(text):
        w = _words(text)
        return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    return bool((grams(candidate) & grams(around)) - grams(original))


def _style_counts(text: str) -> Counter:
    from src.utils.style_checks import analyze_document
    return Counter(i.kind for i in analyze_document(text, kinds=set(_STYLE_KINDS)))


def check_rewrite(original: str, candidate: str, *, voice: Any = None,
                  known_names: Iterable[str] = (), before: str = "", after: str = "",
                  focus: str = "") -> RewriteCheck:
    """Problems with ``candidate`` as a replacement for ``original``."""
    check = RewriteCheck()
    if not (candidate or "").strip():
        check.serious.append("is empty")
        return check
    names = list(known_names)
    check.serious += _name_problems(candidate, f"{before}\n{original}\n{after}", names)

    context = f"{before[-1500:]}\n{original}"
    want_person, want_tense = person_and_tense(context)
    context_words = _words(_narration(context))
    if (not want_person and len(context_words) >= 12
            and not any(w in _FIRST for w in context_words)):
        want_person = "third"              # no "I" anywhere around it
    want_person = getattr(voice, "person", "") or want_person
    want_tense = getattr(voice, "tense", "") or want_tense
    got_person, got_tense = person_and_tense(candidate)
    if want_person in ("first", "third") and got_person and got_person != want_person:
        check.serious.append(f"switches the narration to {got_person} person")
    if want_tense and got_tense and got_tense != want_tense:
        check.serious.append(f"switches to {got_tense} tense")

    n_orig, n_new = len(_words(original)), len(_words(candidate))
    length_asked = any(w in (focus or "").lower() for w in _LENGTH_WORDS)
    if n_orig >= 8 and not length_asked and not 0.4 <= n_new / n_orig <= 2.5:
        check.serious.append(f"is {'much shorter' if n_new < n_orig else 'much longer'} "
                             f"({n_new} words vs {n_orig})")
    if _copied_context(candidate, original, f"{before[-2000:]}\n{after[:2000]}"):
        check.serious.append("repeats text from before or after the passage")

    try:
        was, now = _style_counts(original), _style_counts(candidate)
        for kind, label in _STYLE_KINDS.items():
            added = now[kind] - was[kind]
            if added >= (1 if kind == "cliche" else 2):
                check.minor.append(f"adds {label}")
    except Exception as e:
        print(f"[rewrite-check] style check failed: {e}")

    if voice is not None and hasattr(voice, "fit_score"):
        check.voice_fit = voice.fit_score(candidate)
        if check.voice_fit is not None and check.voice_fit < 0.55:
            check.minor.append(f"is a weak match for your voice ({check.voice_fit:.0%})")
    return check


def known_names_for(project: Any) -> List[str]:
    """Character and world element names, for spelling checks."""
    if project is None:
        return []
    names = [c.name for c in getattr(project, "characters", None) or [] if c.name]
    try:
        from src.ai.canon_index import collect_world_entities
        for e in collect_world_entities(getattr(project, "worldbuilding", None)):
            names.append(e.name)
            names.extend(e.aliases)
    except Exception:
        pass
    return names


# ── Learned examples ─────────────────────────────────────────────────

def _overlap(a: str, b: str) -> float:
    wa, wb = set(_words(a)), set(_words(b))
    return len(wa & wb) / (len(wa | wb) or 1)


def examples_prompt(passage: str, project_path: str = "", *, chosen: int = 2,
                    rejected: int = 1, max_chars: int = 500, db: Any = None) -> str:
    """The writer's best-rated past rewrites (and rejected ones) closest to
    ``passage``, as a prompt block. "" when there's nothing rated yet."""
    try:
        if db is None:
            from src.data.rephrase_database import get_rephrase_database
            db = get_rephrase_database()
        rows = db.rated_examples(project_path=project_path)
    except Exception as e:
        print(f"[examples] rated rewrites unavailable: {e}")
        return ""

    def pick(items, n):
        usable = [r for r in items if r.get("source_text") and r.get("output_text")
                  and len(r["source_text"]) <= max_chars and len(r["output_text"]) <= max_chars]
        usable.sort(key=lambda r: (-(r.get("rating") == "excellent")
                                   - (r.get("project_path") == project_path) * 0.5
                                   - _overlap(passage, r["source_text"])))
        return usable[:n]

    good, bad = pick(rows.get("chosen", []), chosen), pick(rows.get("rejected", []), rejected)
    if not good and not bad:
        return ""
    lines = ["REWRITES THIS AUTHOR RATED (learn their taste; don't reuse the content):"]
    for r in good:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They chose: \"{r['output_text']}\"")
    for r in bad:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They rejected: \"{r['output_text']}\"")
    return "\n".join(lines)


def log_rated_rewrite(source: str, output: str, rating: str, *, accepted: bool,
                      project_path: str = "", style: str = "suggestion",
                      before: str = "", after: str = "", genre: str = "") -> bool:
    """Save a rated rewrite for training and future examples (only when
    the writer has turned on data collection)."""
    try:
        from src.data.rephrase_database import get_rephrase_database, is_collection_enabled
        if not is_collection_enabled():
            return False
        if not source.strip() or not output.strip() or source.strip() == output.strip():
            return False
        get_rephrase_database().log_rephrase(
            source_text=source.strip(), output_text=output.strip(), style=style,
            surrounding_before=before, surrounding_after=after, genre=genre,
            accepted=accepted, rating=rating, project_path=project_path)
        return True
    except Exception as e:
        print(f"[examples] could not save rating: {e}")
        return False


# ── Showing changes ──────────────────────────────────────────────────

def diff_html(original: str, rewrite: str) -> str:
    """Word-level diff: removed words struck through red, added green."""
    a = re.findall(r"\S+|\s+", original or "")
    b = re.findall(r"\S+|\s+", rewrite or "")
    out: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(html.escape("".join(a[i1:i2])))
            continue
        if tag in ("delete", "replace") and "".join(a[i1:i2]).strip():
            out.append("<span style='color:#b91c1c;text-decoration:line-through'>"
                       f"{html.escape(''.join(a[i1:i2]))}</span>")
        if tag in ("insert", "replace") and "".join(b[j1:j2]).strip():
            out.append("<span style='color:#15803d;font-weight:600'>"
                       f"{html.escape(''.join(b[j1:j2]))}</span>")
    return "".join(out).replace("\n", "<br>")


def best_first(items: Sequence[Any], checks: Sequence[RewriteCheck]) -> List[int]:
    """Indices ordered best first (fewest problems, then voice fit); stable."""
    return sorted(range(len(items)), key=lambda i: (checks[i].rank(), i))
