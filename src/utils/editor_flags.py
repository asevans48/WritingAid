"""Which flags the editor shows, decided without Qt (piece R.6).

The editor's highlighter used to decide *and* draw in one 241-line method.
The deciding now lives here, so anything can ask "what would the editor
underline in this paragraph?" with no window and from any thread: the
readiness engine (1.2b) counts exactly what the writer sees.

* ``FlagRules`` holds the rules: spelling (names, intended words, the word
  being typed), grammar (built-in rules plus cached LanguageTool results,
  quick rules for dialogue), overuse and repeated phrases, the style checks
  (ignored, kept and preferred kinds), the drafting phase and Focus.
  ``WritingHighlighter`` inherits it and only draws what it returns.
* ``FlagState`` is the same rules with plain settings, for code with no
  editor: ``FlagState(spell_checker, ...)``, then ``flags_for_text(text)``.

``CheckMode``, ``ErrorType``, ``WritingError`` and ``issue_weight`` moved here
from ``src.ui.enhanced_text_editor``, which still imports them, so every
existing import keeps working and the objects are the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from src.utils.spell_checker import _apos


class CheckMode(Enum):
    """Modes for writing checks."""
    ON_DEMAND = "on_demand"  # Only runs on recheck button click (green)
    REALTIME = "realtime"    # Runs automatically as you type (blue)
    OFF = "off"              # Disabled (white/default)


class ErrorType(Enum):
    """Types of writing errors."""
    SPELLING = "spelling"
    GRAMMAR = "grammar"
    OVERUSE = "overuse"
    OVERUSED_PHRASE = "overused_phrase"
    STYLE = "style"


@dataclass
class WritingError:
    """Represents a writing error with details."""
    error_type: ErrorType
    word: str
    start: int
    end: int
    reason: str
    suggestions: Optional[List[str]]   # None → computed on demand
    # Span the suggestions replace, when it's wider than the word (the
    # whole set phrase "mobile home" for an overused "home").
    replace_span: Optional[Tuple[int, int]] = None


# How much fixing an issue tends to improve the page (Focus view, and the
# fallback for "Today's three fixes").
_STYLE_WEIGHTS = {"preference": 70, "cliche": 50, "wordy": 35, "passive": 30, "intensifier": 30,
                  "adverb": 25, "echo": 25, "repeated_start": 20, "long_sentence": 20,
                  "hard_sentence": 20, "sticky_sentence": 15}


def issue_weight(error, paragraph: str = "") -> float:
    if error.error_type == ErrorType.SPELLING:
        w = 100
    elif error.error_type == ErrorType.GRAMMAR:
        w = 80
    elif error.error_type == ErrorType.OVERUSE:
        w = 45
    elif error.error_type == ErrorType.OVERUSED_PHRASE:
        w = 40
    else:
        w = _STYLE_WEIGHTS.get(getattr(error, "style_kind", ""), 20)
    try:
        from src.ai import flag_judge as fj
        from src.ai.word_suggest import sentence_around
        category = {ErrorType.STYLE: "style", ErrorType.GRAMMAR: "grammar",
                    ErrorType.SPELLING: "spelling"}.get(error.error_type)
        if category:
            kind = getattr(error, "style_kind", "") if category == "style" else ""
            v = fj.verdict(category, error.word,
                           sentence_around(paragraph, error.start, error.end).text if paragraph else "",
                           kind)
            if v is not None and v[0]:
                w += 10                       # a model confirmed it matters
    except Exception:
        pass
    return w


class FlagRules:
    """The editor's rules for what to flag. Needs these attributes (the
    highlighter and ``FlagState`` both have them): ``spell_checker``,
    ``grammar_checker``, ``overuse_detector``, ``project``, ``phase``,
    ``focus``, ``focus_per_paragraph``, ``_spell_mode``, ``_grammar_mode``,
    ``_overuse_mode``, ``_style_mode``, ``_style_kinds``, ``_style_ignored``,
    ``_style_cache``, ``_ignored_words``, ``_full_text``, ``_full_text_fresh``,
    ``_typing``, and a method ``_lt_issues_for_block(text)``."""

    _SENTENCE_END_RX = re.compile(r"[.!?…:]\s*$|^\s*$")

    _BEFORE_SENTENCE_CHARS = frozenset("\"“”‘'([-—–*_")

    def _should_check(self, mode: CheckMode) -> bool:
        """A check draws its underlines whenever it is on. (ON_DEMAND vs
        REALTIME only changes when the heavy LanguageTool pass and the
        overuse statistics refresh.)"""
        return mode != CheckMode.OFF

    def is_word_ignored(self, word: str, error_type: ErrorType) -> bool:
        """Check if a word is ignored for a specific error type."""
        word_lower = word.lower()
        if word_lower in self._ignored_words:
            return error_type in self._ignored_words[word_lower]
        return False

    def style_issues_for(self, text: str) -> list:
        """Style issues for one paragraph (cached, minus ignored ones)."""
        from src.utils.style_checks import analyze_paragraph
        key = (text, frozenset(self._style_kinds))
        issues = self._style_cache.get(key)
        if issues is None:
            issues = analyze_paragraph(text, self._style_kinds)
            if len(self._style_cache) > 4000:
                self._style_cache.clear()
            self._style_cache[key] = issues
        from src.ai import flag_judge as fj
        from src.ai import style_sheet as ss
        from src.ai.word_suggest import sentence_around
        project = self.project
        kept_kinds = ss.kept_kinds(project) if project is not None else set()
        allowed = ss.allowed_words(project) if project is not None else set()
        kept = []
        for i in issues:
            if (i.kind, _apos(i.text.strip().lower())) in self._style_ignored:
                continue
            if i.kind == "echo" and i.text.strip().lower() in allowed:
                continue                     # a word of the story's world, like a name
            if fj.quick_style_ok(i.kind, text, i.start, i.end):
                continue                     # dialogue: the character's voice
            sentence = sentence_around(text, i.start, i.end).text
            if fj.dropped("style", i.text, sentence, i.kind):
                continue                     # the model judged it a false alarm
            if i.kind in kept_kinds:
                # The writer keeps these on purpose: only a model-confirmed problem shows.
                v = fj.verdict("style", i.text, sentence, i.kind)
                if v is None or not v[0]:
                    continue
            kept.append(i)
        if project is not None:
            kept += [i for i in ss.preference_issues(project, text)
                     if (i.kind, _apos(i.text.strip().lower())) not in self._style_ignored]
        return kept

    def _word_intended(self, word: str) -> bool:
        """In the style sheet's allowed words; or a capitalised word (a name)
        the model judged intentional, or (quick rule) used three or more
        times and not one slip from a common word. A lowercase misspelling
        is always marked — the writer can allow it."""
        from src.ai import flag_judge as fj
        if self.project is not None:
            from src.ai.style_sheet import allowed_words
            if _apos(word.lower()) in allowed_words(self.project):
                return True
        if not word[:1].isupper():
            return False
        if fj.dropped("spelling", word):
            return True
        cache = self.__dict__.setdefault("_intended_cache", {})
        k = (word, len(self._full_text or ""))
        if k not in cache:
            if len(cache) > 5000:
                cache.clear()
            cache[k] = fj.quick_word_intended(word, self._full_text or "", self.spell_checker)
        return cache[k]

    def _probably_a_name(self, word: str) -> bool:
        """Is a capitalised, sentence-initial unknown word a proper noun?

        Evidence from the document first: capitalised mid-sentence
        elsewhere → a name; written lowercase elsewhere → an ordinary
        word (so check it). Otherwise it's a name unless its best
        correction is a common English word ("Tommorow" → tomorrow).
        """
        cache = self.__dict__.setdefault("_name_cache", {})
        key = (word, len(self._full_text))
        if key in cache:
            return cache[key]
        text = self._full_text or ""
        esc = re.escape(word)
        if re.search(rf"[a-z,;]\s+{esc}\b", text):
            result = True
        elif re.search(rf"(?<![A-Za-z']){re.escape(word.lower())}(?![A-Za-z'])", text):
            result = False
        else:
            result = not self.spell_checker.looks_like_common_word_typo(word)
        if len(cache) > 5000:
            cache.clear()
        cache[key] = result
        return result

    @classmethod
    def _starts_sentence(cls, text: str, pos: int) -> bool:
        i = pos
        while i > 0 and (text[i - 1] in cls._BEFORE_SENTENCE_CHARS or text[i - 1].isspace()):
            i -= 1
        return i == 0 or text[i - 1] in ".!?…:"

    # ── The decision for one paragraph ───────────────────────────

    def paragraph_flags(self, text: str, block_number: int = 0, block_position: int = 0
                        ) -> Tuple[List[WritingError], Optional[List[WritingError]]]:
        """Every flag for one paragraph, in drawing order, and — when Focus
        trimmed them — the ones kept, in the order Focus ranks them (else
        None). ``block_position`` is the paragraph's offset in the full
        text (for repeated phrases). A grammar flag that overlaps earlier
        flags carries ``draw_segments``: the parts to underline."""
        errors: List[WritingError] = []
        drafting = self.phase == "drafting"

        # Style checks — first, so the error underlines layer on top.
        if self._should_check(self._style_mode) and not drafting:
            from src.utils.style_checks import KINDS
            for issue in self.style_issues_for(text):
                if issue.kind not in KINDS or issue.end <= issue.start:
                    continue
                err = WritingError(
                    error_type=ErrorType.STYLE,
                    word=issue.text,
                    start=issue.start,
                    end=issue.end,
                    reason=f"{KINDS[issue.kind][0]}: {issue.message}",
                    suggestions=list(issue.suggestions),
                )
                err.style_kind = issue.kind
                errors.append(err)

        # Spelling
        if self._should_check(self._spell_mode):
            typing_end = (self._typing[1] if self._typing and self._typing[0] == block_number
                          else -1)
            from src.utils.proofing import SPELL_TOKEN_RX, normalize_apostrophes
            for match in SPELL_TOKEN_RX.finditer(normalize_apostrophes(text)):
                word = text[match.start():match.end()]   # as typed (any apostrophe)
                if match.end() == typing_end:
                    continue  # still being typed
                if self.is_word_ignored(word, ErrorType.SPELLING):
                    continue
                sentence_start = self._starts_sentence(text, match.start())
                is_correct, reason = self.spell_checker.check_word(
                    word, sentence_start=sentence_start)
                if (not is_correct and sentence_start and word[:1].isupper()
                        and self._probably_a_name(word)):
                    is_correct = True
                if not is_correct and self._word_intended(word):
                    is_correct = True        # a name or a word of the story's world
                if not is_correct:
                    errors.append(WritingError(
                        error_type=ErrorType.SPELLING,
                        word=word,
                        start=match.start(),
                        end=match.end(),
                        reason=reason,
                        suggestions=None,   # computed on demand (get_error_at)
                    ))

        # Grammar: built-in rules (live) + cached LanguageTool results.
        if self._should_check(self._grammar_mode) and self.grammar_checker:
            from src.utils.proofing import builtin_grammar, merge_issues
            from src.utils.proof_store import issues_for as model_issues
            issues = merge_issues(self._lt_issues_for_block(text), builtin_grammar(text),
                                  model_issues(text))    # a model's corrections (P.4)
            from src.ai import flag_judge as fj
            from src.ai.word_suggest import sentence_around
            for issue in issues:
                start, end, error_text, message, suggestions = issue.as_tuple()
                if start < 0 or end > len(text) or end <= start:
                    continue
                if self.is_word_ignored(error_text, ErrorType.GRAMMAR):
                    continue
                if fj.quick_grammar_ok(message, text, start, end):
                    continue                 # a fragment in dialogue is the character's voice
                # Grammar always shows; a model that thinks it's fine says so on the card.
                v = fj.verdict("grammar", error_text, sentence_around(text, start, end).text)
                if v is not None and not v[0] and v[1]:
                    message = f"{message} (Editor's view: may be fine — {v[1].rstrip('.')}.)"
                # A span already flagged as a spelling error isn't
                # re-flagged; a longer grammar issue that merely overlaps
                # one (e.g. a double negative starting with "dont") is
                # underlined on the parts the spelling error doesn't cover.
                taken = sorted((e.start, e.end) for e in errors
                               if start < e.end and e.start < end
                               and e.error_type != ErrorType.STYLE)
                if any(s0 <= start and end <= e0 for s0, e0 in taken):
                    continue
                segments, cur = [], start
                for s0, e0 in taken:
                    if s0 > cur:
                        segments.append((cur, s0))
                    cur = max(cur, e0)
                if cur < end:
                    segments.append((cur, end))
                err = WritingError(
                    error_type=ErrorType.GRAMMAR,
                    word=error_text,
                    start=start,
                    end=end,
                    reason=message,
                    suggestions=suggestions,
                )
                err.draw_segments = segments
                err.rule_id = getattr(issue, "rule_id", "") or ""
                errors.append(err)

        # Overused words and repeated phrases.
        if (self._should_check(self._overuse_mode) and self._full_text and self.overuse_detector
                and not drafting):
            from src.utils.proofing import COMPOUND_TOKEN_RX, normalize_apostrophes
            flagged_spans = {(e.start, e.end) for e in errors}
            for match in COMPOUND_TOKEN_RX.finditer(normalize_apostrophes(text)):
                word = text[match.start():match.end()]   # as typed (whole compound)
                if self.is_word_ignored(word, ErrorType.OVERUSE):
                    continue
                is_overused, count = self.overuse_detector.is_overused(word, self._full_text)
                if is_overused and match.span() not in flagged_spans:
                    flagged_spans.add(match.span())
                    errors.append(WritingError(
                        error_type=ErrorType.OVERUSE,
                        word=word,
                        start=match.start(),
                        end=match.end(),
                        reason=(f"Word '{word}' appears {count} times. "
                                + (self.overuse_detector.verdict_reason(
                                    "w:" + (self.overuse_detector._count_key(word.lower()) or ""))
                                   or "Consider varying your word choice.")),
                        suggestions=None,   # computed on demand (get_error_at)
                    ))

            # Overused phrases (2–5 words) overlapping this paragraph.
            block_end = block_position + len(text)
            phrase_occurrences = (self.overuse_detector.get_overused_phrases_in_range(
                self._full_text, block_position, block_end
            ) if self._full_text_fresh else [])
            for phrase, phrase_start, phrase_end, count in phrase_occurrences:
                local_start = max(0, phrase_start - block_position)
                local_end = min(len(text), phrase_end - block_position)
                if local_start >= len(text) or local_end <= 0:
                    continue
                if self.is_word_ignored(phrase, ErrorType.OVERUSED_PHRASE):
                    continue
                if (local_start, local_end) not in flagged_spans:
                    flagged_spans.add((local_start, local_end))
                    word_count = len(phrase.split())
                    errors.append(WritingError(
                        error_type=ErrorType.OVERUSED_PHRASE,
                        word=text[local_start:local_end],   # as typed
                        start=local_start,
                        end=local_end,
                        reason=(f"Phrase '{phrase}' ({word_count} words) appears {count} times. "
                                + (self.overuse_detector.verdict_reason(f"p:{phrase}")
                                   or "Consider rephrasing.")),
                        suggestions=None,   # computed on demand (get_error_at)
                    ))

        # Focus: only this paragraph's most important issues stay marked.
        must = [e for e in errors if e.error_type in (ErrorType.SPELLING, ErrorType.GRAMMAR)]
        others = [e for e in errors if e not in must]
        if self.focus and not drafting and len(others) > max(0, self.focus_per_paragraph - len(must)):
            # Spelling and grammar always stay; the rest compete for what's left.
            ranked = sorted(others, key=lambda e: -issue_weight(e, text))
            keep = must + ranked[:max(0, self.focus_per_paragraph - len(must))]
            return [e for e in errors if e in keep], keep
        return errors, None


class FlagState(FlagRules):
    """The editor's rules with plain settings, for code with no editor (the
    readiness engine). Defaults match a fresh editor with every check on;
    ``from_highlighter`` copies a live editor's settings (GUI thread)."""

    def __init__(self, spell_checker, grammar_checker=None, overuse_detector=None,
                 project=None):
        from src.utils.style_checks import DEFAULT_KINDS
        self.spell_checker = spell_checker
        if grammar_checker is None:
            from src.utils.grammar_checker import GrammarChecker
            grammar_checker = GrammarChecker()
        self.grammar_checker = grammar_checker
        self.overuse_detector = overuse_detector
        self.project = project
        self.phase = "revising"
        self.focus = False
        self.focus_per_paragraph = 2
        self._spell_mode = CheckMode.ON_DEMAND
        self._grammar_mode = CheckMode.ON_DEMAND
        self._overuse_mode = CheckMode.ON_DEMAND
        self._style_mode = CheckMode.OFF
        self._style_kinds: Set[str] = set(DEFAULT_KINDS)
        self._style_ignored: Set[Tuple[str, str]] = set()
        self._style_cache: Dict[Tuple[str, frozenset], list] = {}
        self._ignored_words: Dict[str, Set[ErrorType]] = {}
        self._full_text = ""
        self._full_text_fresh = False
        self._typing = None
        self._lt_cache: Dict[str, list] = {}       # LanguageTool results by paragraph text

    _SETTINGS = ("phase", "focus", "focus_per_paragraph", "_spell_mode", "_grammar_mode",
                 "_overuse_mode", "_style_mode")

    @classmethod
    def from_highlighter(cls, hl) -> "FlagState":
        """A copy of a live editor's rules and settings (call on the GUI
        thread; the copy can then be used anywhere)."""
        state = cls(hl.spell_checker, hl.grammar_checker, hl.overuse_detector,
                    getattr(hl, "project", None))
        for name in cls._SETTINGS:
            setattr(state, name, getattr(hl, name))
        state._style_kinds = set(hl._style_kinds)
        state._style_ignored = set(hl._style_ignored)
        state._ignored_words = {k: set(v) for k, v in hl._ignored_words.items()}
        state._lt_cache = dict(hl._lt_cache)
        return state

    def _lt_issues_for_block(self, text: str) -> list:
        return list(self._lt_cache.get(text, []))

    def update_full_text(self, text: str) -> None:
        self._full_text = text
        self._full_text_fresh = True

    def flags_for_text(self, text: str) -> List[Tuple[int, WritingError]]:
        """Every flag in a whole text, as (paragraph offset, flag); a flag's
        start and end are within its paragraph. Paragraphs are lines, as
        the editor's blocks are."""
        if self._full_text != text:
            self.update_full_text(text)
        out: List[Tuple[int, WritingError]] = []
        pos = 0
        for n, para in enumerate(text.split("\n")):
            errors, _keep = self.paragraph_flags(para, n, pos)
            out.extend((pos, e) for e in errors)
            pos += len(para) + 1
        return out


# ── Shared set-up (the editor and the engine use the same) ─────────────

def new_checkers():
    """(spell checker, grammar checker, overuse detector), set up as the
    editor sets them up."""
    from src.utils.grammar_checker import GrammarChecker
    from src.utils.overuse import OveruseDetector
    from src.utils.spell_checker import SpellChecker
    overuse = OveruseDetector()
    overuse.review_low_counts = True        # light repeats only when they weaken the writing
    return SpellChecker(), GrammarChecker(), overuse


def project_vocabulary(project) -> Tuple[List[str], List[str]]:
    """(words the spell checker accepts, names the overuse check skips):
    characters, world elements and the project dictionary; names are
    characters and world elements (the style sheet's allowed words are
    added by the caller)."""
    words: List[str] = []
    try:
        words += [c.name for c in getattr(project, "characters", None) or []]
        from src.ai.canon_index import character_alias_names
        words += character_alias_names(getattr(project, "characters", None) or [])
        from src.ai.canon_index import collect_world_entities
        words += [e.name for e in collect_world_entities(
            getattr(project, "worldbuilding", None))]
        words += list(getattr(getattr(project, "dictionary", None), "words", None) or [])
    except Exception as e:
        print(f"[spell] project vocabulary unavailable: {e}")
    # Names repeat because stories are about people and places.
    names = [c.name for c in getattr(project, "characters", None) or []]
    try:
        from src.ai.canon_index import character_alias_names, collect_world_entities
        names += character_alias_names(getattr(project, "characters", None) or [])
        names += [e.name for e in collect_world_entities(getattr(project, "worldbuilding", None))]
    except Exception:
        pass
    return words, names


def allowed_words(project) -> List[str]:
    if project is None:
        return []
    from src.ai.style_sheet import allowed_words as _allowed
    return sorted(_allowed(project))


def state_for_project(project, base: Optional[FlagRules] = None) -> "FlagState":
    """A ``FlagState`` that knows the project's names, dictionary and style
    sheet, as an open editor does. ``base`` (a highlighter or state) lends
    its ignored words and LanguageTool results."""
    spell, grammar, overuse = new_checkers()
    words, names = project_vocabulary(project)
    spell.set_project_words(words)
    overuse.set_names(names + allowed_words(project))
    state = FlagState(spell, grammar, overuse, project)
    state._spell_mode = state._grammar_mode = state._overuse_mode = CheckMode.ON_DEMAND
    if base is not None:
        state._ignored_words = {k: set(v) for k, v in getattr(base, "_ignored_words", {}).items()}
        state._style_ignored = set(getattr(base, "_style_ignored", set()))
        state._lt_cache = dict(getattr(base, "_lt_cache", {}))
    return state


def languagetool_issues(paragraphs: List[str], engine, chunk_chars: int = 20000
                        ) -> Dict[str, list]:
    """LanguageTool issues per paragraph, offsets within each paragraph.
    Paragraphs are joined into a few large requests (one round trip each
    to the local server). ``engine`` must be started."""
    results: Dict[str, list] = {p: [] for p in paragraphs}
    batch: List[str] = []
    size = 0

    def flush():
        if not batch:
            return
        joined = "\n".join(batch)
        starts, pos = [], 0
        for p in batch:
            starts.append(pos)
            pos += len(p) + 1
        for issue in engine.check(joined):
            for p, st in zip(batch, starts):
                if st <= issue.start < st + len(p):
                    if issue.end <= st + len(p):
                        issue.start -= st
                        issue.end -= st
                        results[p].append(issue)
                    break
        batch.clear()

    for p in paragraphs:
        if size + len(p) > chunk_chars:
            flush()
            size = 0
        batch.append(p)
        size += len(p) + 1
    flush()
    return results


def flags_for_paragraph(text: str, state: FlagRules, block_number: int = 0,
                        block_position: int = 0) -> List[WritingError]:
    """What the editor would flag in one paragraph, given its rules and
    settings (a ``FlagState`` or the highlighter itself)."""
    return state.paragraph_flags(text, block_number, block_position)[0]
