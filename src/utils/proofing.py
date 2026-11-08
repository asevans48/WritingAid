"""Proofing engines for the manuscript editor: grammar + readability.

Grammar comes from two layers, merged:

  * **LanguageTool** (``language_tool_python``, needs Java). A full
    rule-based grammar checker: agreement, confused words (its/it's,
    could of), a/an, punctuation, repeated words, and thousands more.
    Started lazily on a background thread — the first start takes a
    few seconds, and the very first run downloads the LanguageTool
    server (~260 MB) into ``~/.cache/language_tool_python``. Rules that
    misfire on fiction (smart quotes, dialog spanning paragraphs) and
    its spelling rule (the editor's own speller handles spelling, with
    the project's names) are disabled.
  * **Built-in rules** — fast regex rules that always run, so grammar
    checking works without Java and catches a few things LanguageTool
    lets through ("Their going", double negatives).

Readability: Flesch-Kincaid grade level and Flesch reading ease.

No Qt here; the editor drives these from a worker thread.
"""

from __future__ import annotations

import re
import shutil
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class GrammarIssue:
    start: int
    end: int
    text: str
    message: str
    suggestions: List[str] = field(default_factory=list)
    rule_id: str = ""
    source: str = "builtin"     # builtin | languagetool

    def as_tuple(self) -> Tuple[int, int, str, str, List[str]]:
        return (self.start, self.end, self.text, self.message, self.suggestions)


# ── LanguageTool ────────────────────────────────────────────────────

# Rules that produce noise in fiction manuscripts or duplicate the
# editor's own spell checker.
LT_DISABLED_RULES = {
    "MORFOLOGIK_RULE_EN_US",        # spelling — handled by the editor (knows project names)
    "EN_QUOTES",                    # straight vs smart quotes
    "EN_UNPAIRED_QUOTES",           # multi-paragraph dialog leaves quotes open
    "EN_UNPAIRED_BRACKETS",
    "DASH_RULE",                    # em-dash style preferences
    "PUNCTUATION_PARAGRAPH_END",    # dialog fragments, headings
    "WORD_CONTAINS_UNDERSCORE",
    "EN_DIACRITICS_REPLACE",
    "ARROWS",
}


class LanguageToolEngine:
    """Process-wide LanguageTool instance (the Java server is heavy)."""

    _instance: Optional["LanguageToolEngine"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._tool = None
        self.status = "idle"        # idle | starting | ready | unavailable | failed
        self.detail = ""
        self._start_lock = threading.Lock()
        self._check_lock = threading.Lock()

    @classmethod
    def get(cls) -> "LanguageToolEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = LanguageToolEngine()
            return cls._instance

    @staticmethod
    def prerequisites() -> Tuple[bool, str]:
        try:
            import language_tool_python  # noqa: F401
        except Exception:
            return False, "language-tool-python is not installed"
        if not shutil.which("java"):
            return False, "Java is not installed (LanguageTool needs it)"
        return True, ""

    def ensure_started(self) -> bool:
        """Start the server if needed. Blocking — call from a worker thread."""
        if self.status == "ready":
            return True
        if self.status in ("unavailable", "failed"):
            return False
        with self._start_lock:
            if self.status == "ready":
                return True
            ok, why = self.prerequisites()
            if not ok:
                self.status, self.detail = "unavailable", why
                return False
            self.status = "starting"
            try:
                import language_tool_python
                tool = language_tool_python.LanguageTool("en-US")
                try:
                    tool.disabled_rules.update(LT_DISABLED_RULES)
                except Exception:
                    pass
                self._tool = tool
                self.status, self.detail = "ready", ""
                return True
            except Exception as e:
                self.status, self.detail = "failed", str(e)
                print(f"[proofing] LanguageTool failed to start: {e}")
                return False

    def check(self, text: str) -> List[GrammarIssue]:
        """Check ``text``; [] when LanguageTool isn't running."""
        if not text.strip() or not self.ensure_started():
            return []
        with self._check_lock:
            try:
                matches = self._tool.check(text)
            except Exception as e:
                print(f"[proofing] LanguageTool check failed: {e}")
                return []
        out = []
        for m in matches:
            rule = getattr(m, "rule_id", "") or getattr(m, "ruleId", "")
            if rule in LT_DISABLED_RULES:
                continue
            offset = getattr(m, "offset", 0)
            length = getattr(m, "error_length", None) or getattr(m, "errorLength", 0) or 0
            if length <= 0:
                continue
            out.append(GrammarIssue(
                offset, offset + length, text[offset:offset + length],
                getattr(m, "message", "") or "Possible grammar issue",
                list(getattr(m, "replacements", None) or [])[:5],
                rule, "languagetool"))
        return out

    def close(self) -> None:
        if self._tool is not None:
            try:
                self._tool.close()
            except Exception:
                pass
        self._tool, self.status = None, "idle"

    def describe(self) -> str:
        return {
            "idle": "LanguageTool (starts on first check)",
            "starting": "LanguageTool starting…",
            "ready": "LanguageTool",
            "unavailable": f"basic rules only — {self.detail}",
            "failed": f"basic rules only — LanguageTool failed: {self.detail}",
        }.get(self.status, self.status)


# ── Built-in rules ──────────────────────────────────────────────────

_AN_EXCEPTIONS = {"hour", "hours", "honest", "honestly", "honor", "honour", "honorable",
                  "heir", "heirs", "herb", "herbs", "hourly"}
_A_EXCEPTIONS_PREFIX = ("uni", "use", "usu", "uti", "ure", "eu", "one", "once", "ewe", "uk", "u.")
_LEGIT_REPEATS = {"had", "that", "is", "do", "very", "no", "bye", "ha", "knock", "so", "really"}
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "jr", "sr", "prof", "no"}

_CONTRACTION_FIX = {
    "dont": "don't", "doesnt": "doesn't", "didnt": "didn't", "cant": "can't",
    "isnt": "isn't", "wasnt": "wasn't", "arent": "aren't", "werent": "weren't",
    "couldnt": "couldn't", "shouldnt": "shouldn't", "wouldnt": "wouldn't",
    "havent": "haven't", "hasnt": "hasn't", "hadnt": "hadn't", "im": "I'm",
    "ive": "I've", "youre": "you're", "theyre": "they're", "thats": "that's",
}


def _issue(m: "re.Match", message: str, suggestions: List[str], rule: str,
           group: int = 0) -> GrammarIssue:
    return GrammarIssue(m.start(group), m.end(group), m.group(group), message,
                        suggestions, rule, "builtin")


def _match_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def builtin_grammar(text: str) -> List[GrammarIssue]:
    """Fast regex grammar rules. Precision over recall: each rule targets
    patterns that are almost always wrong in prose."""
    issues: List[GrammarIssue] = []
    add = issues.append

    for m in re.finditer(r"\b(\w+)\s+(\1)\b", text, re.IGNORECASE):
        if m.group(1).lower() not in _LEGIT_REPEATS:
            add(_issue(m, f"Repeated word: '{m.group(1)}'", [m.group(1)], "REPEATED_WORD"))

    for m in re.finditer(r"\b([Aa])\s+([A-Za-z][\w'-]*)", text):
        nxt = m.group(2).lower()
        if nxt in ("a", "an"):
            continue  # "a a" is a repeated word, reported separately
        vowel_sound = ((nxt[0] in "aeiou" and not nxt.startswith(_A_EXCEPTIONS_PREFIX))
                       or nxt in _AN_EXCEPTIONS)
        if vowel_sound and m.group(2) != m.group(2).upper():
            add(GrammarIssue(m.start(1), m.end(1), m.group(1),
                             "Use 'an' before a word that starts with a vowel sound",
                             [_match_case(m.group(1), "an")], "A_VS_AN"))
    for m in re.finditer(r"\b([Aa]n)\s+([A-Za-z][\w'-]*)", text):
        nxt = m.group(2).lower()
        consonant_sound = ((nxt[0] not in "aeiou" and nxt not in _AN_EXCEPTIONS
                            and not nxt.startswith("hon"))
                           or nxt.startswith(_A_EXCEPTIONS_PREFIX))
        if consonant_sound and m.group(2) != m.group(2).upper():
            add(GrammarIssue(m.start(1), m.end(1), m.group(1),
                             "Use 'a' before a word that starts with a consonant sound",
                             [_match_case(m.group(1), "a")], "AN_VS_A"))

    confused = [
        (r"\b([Tt]heir)\s+(?:going|coming|leaving|not|gonna|trying|being|here|there)\b",
         "“Their” is possessive — did you mean “they're” (they are)?", "they're", "THEIR_THEYRE"),
        (r"\b([Tt]heir)\s+(?:is|are|was|were)\b",
         "Did you mean “there” (as in “there is”)?", "there", "THEIR_THERE"),
        (r"\b([Tt]here)\s+own\b", "Did you mean the possessive “their”?", "their", "THERE_THEIR"),
        (r"\b([Yy]our)\s+(?:welcome|going|not|being|doing|gonna|kidding)\b",
         "Did you mean “you're” (you are)?", "you're", "YOUR_YOURE"),
        (r"\b([Ii]ts)\s+(?:a|an|been|not|going|raining|snowing|time|okay|true|over|getting)\b",
         "Did you mean “it's” (it is / it has)?", "it's", "ITS_ITS"),
        (r"\b([Ii]t's)\s+own\b", "Possessive “its” has no apostrophe.", "its", "ITS_OWN"),
        (r"\b(?i:more|less|better|worse|rather|other|fewer|greater|smaller)\s+(then)\b",
         "Comparisons use “than”.", "than", "THEN_THAN"),
        (r"\b([Aa]lot)\b", "“A lot” is two words.", "a lot", "ALOT"),
        (r"\b([Ii]rregardless)\b", "Use “regardless”.", "regardless", "IRREGARDLESS"),
    ]
    for rx, msg, fix, rule in confused:
        for m in re.finditer(rx, text):
            add(_issue(m, msg, [_match_case(m.group(1), fix)], rule, 1))

    for m in re.finditer(r"\b((?:[Cc]ould|[Ww]ould|[Ss]hould|[Mm]ight|[Mm]ust)\s+of)\b", text):
        modal = m.group(1).split()[0]
        add(_issue(m, f"Use “{modal.lower()} have” (or “{modal.lower()}'ve”), not “of”.",
                   [f"{modal} have", f"{modal}'ve"], "MODAL_OF", 1))

    for m in re.finditer(
            r"\b(?:don't|dont|doesn't|doesnt|didn't|didnt|won't|can't|cant|isn't|ain't|"
            r"wasn't|weren't|never|haven't|hasn't)\s+(?:\w+\s+){0,2}?"
            r"(nothing|nobody|none|nowhere|no one|no)\b", text, re.IGNORECASE):
        add(_issue(m, "Double negative — fine in dialect dialog, otherwise use "
                      "“anything / anybody / any”.", [], "DOUBLE_NEGATIVE"))

    agreement = [
        (r"\b(I)\s+(has|is|does|doesn't|was not)\b", {"has": "have", "is": "am", "does": "do",
                                                    "doesn't": "don't", "was not": "wasn't"}),
        (r"(?<!\b[Ii]f )(?<!\b[Ww]ish )(?<!\b[Aa]s if )(?<!\b[Tt]hough )"
         r"\b([Hh]e|[Ss]he|[Ii]t)\s+(have|don't|dont|are|were|do)\b",
         {"have": "has", "don't": "doesn't", "dont": "doesn't", "are": "is",
          "were": "was", "do": "does"}),
        (r"\b([Tt]hey|[Ww]e|[Yy]ou)\s+(has|is|was|doesn't|does)\b",
         {"has": "have", "is": "are", "was": "were", "doesn't": "don't", "does": "do"}),
    ]
    for rx, fixes in agreement:
        for m in re.finditer(rx, text):
            verb = m.group(2)
            # "Do he…?" questions and "he do" dialect are rare enough;
            # "it do" etc. still read as agreement errors in narration.
            add(GrammarIssue(m.start(2), m.end(2), verb,
                             f"Subject–verb agreement: “{m.group(1)} {verb}”.",
                             [fixes.get(verb.lower(), verb)], "AGREEMENT"))

    for m in re.finditer(r"\b(dont|doesnt|didnt|cant|isnt|wasnt|arent|werent|couldnt|"
                         r"shouldnt|wouldnt|havent|hasnt|hadnt|youre|theyre|thats)\b",
                         text, re.IGNORECASE):
        fix = _CONTRACTION_FIX[m.group(1).lower()]
        add(_issue(m, "Missing apostrophe in contraction.", [_match_case(m.group(1), fix)],
                   "CONTRACTION_APOSTROPHE", 1))

    for m in re.finditer(r"(?<![\w'’])(i)(?![\w'’])", text):
        add(_issue(m, "The pronoun “I” is always capitalized.", ["I"], "LOWERCASE_I", 1))
    for m in re.finditer(r"(?<![\w'’])(i)(['’](?:m|ve|ll|d))\b", text):
        add(_issue(m, "The pronoun “I” is always capitalized.", ["I" + m.group(2)],
                   "LOWERCASE_I", 0))

    for m in re.finditer(r"(\b\w+)([.!?])\s+([a-z])", text):
        if m.group(1).lower() in _ABBREVIATIONS:
            continue
        if re.search(r"\.\w\.$", text[max(0, m.start(1) - 3):m.end(2)]):
            continue  # e.g. / i.e.
        add(GrammarIssue(m.start(3), m.end(3), m.group(3),
                         "Sentence should start with a capital letter.",
                         [m.group(3).upper()], "SENTENCE_CAPITAL"))

    for m in re.finditer(r"([,;])(?=[A-Za-z])", text):
        add(_issue(m, "Add a space after the punctuation.", [m.group(1) + " "], "SPACE_AFTER_PUNCT"))
    for m in re.finditer(r"(?<=[a-z])\.(?=[A-Z][a-z])", text):
        add(_issue(m, "Add a space after the period.", [". "], "SPACE_AFTER_PERIOD"))
    for m in re.finditer(r"(?<=\S)( {2,})(?=\S)", text):
        add(_issue(m, "Extra spaces.", [" "], "DOUBLE_SPACE", 1))
    for m in re.finditer(r"\s+([,.;:!?])(?!\S*\.\w)", text):
        if m.group(1) in ".!?" and text[m.end():m.end() + 2] in ("..", ".."):
            continue
        add(_issue(m, "No space before punctuation.", [m.group(1)], "SPACE_BEFORE_PUNCT"))
    return issues


def merge_issues(*groups: List[GrammarIssue]) -> List[GrammarIssue]:
    """Merge issue lists. An issue lying entirely inside one already kept
    (earlier groups first, longer spans first) is a duplicate and dropped;
    partially overlapping issues are different problems and both kept
    ("dont" contraction + "dont know nothing" double negative)."""
    out: List[GrammarIssue] = []
    for group in groups:
        for issue in sorted(group, key=lambda i: (i.start, -(i.end - i.start))):
            if any(o.start <= issue.start and issue.end <= o.end for o in out):
                continue
            out.append(issue)
    return sorted(out, key=lambda i: (i.start, -(i.end - i.start)))


# ── Readability ─────────────────────────────────────────────────────

_WORD_RX = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_SENT_RX = re.compile(r"[.!?…]+[\"”’')\]]*(?=\s|$)")
_SYLLABLE_OVERRIDES = {
    "the": 1, "every": 2, "everything": 3, "everyone": 3, "business": 2, "people": 2,
    "different": 3, "evening": 2, "family": 3, "interesting": 4, "beautiful": 3,
    "area": 3, "idea": 3, "real": 1, "being": 2, "poem": 2, "quiet": 2, "science": 2,
    "fire": 1, "hour": 1, "our": 1, "naive": 2, "create": 2, "created": 3,
}


def count_syllables(word: str) -> int:
    """English syllable estimate (vowel groups with common corrections)."""
    w = word.lower().replace("’", "'").split("'")[0]
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    if w in _SYLLABLE_OVERRIDES:
        return _SYLLABLE_OVERRIDES[w]
    if len(w) <= 3:
        return 1
    w2 = re.sub(r"(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$", lambda m: m.group(0)[0], w)
    w2 = re.sub(r"^y", "", w2)
    groups = re.findall(r"[aeiouy]+", w2)
    n = len(groups)
    if re.search(r"(?:ia|io|ua|eo|iu)", w2) and not re.search(r"(?:tion|sion|cious|tious)", w2):
        n += len(re.findall(r"(?:ia|io|ua|eo|iu)", w2))
    return max(1, n)


@dataclass
class Readability:
    words: int
    sentences: int
    syllables: int
    fk_grade: float
    reading_ease: float

    @property
    def ease_label(self) -> str:
        e = self.reading_ease
        for cap, label in ((30, "very difficult"), (50, "difficult"), (60, "fairly difficult"),
                           (70, "standard"), (80, "fairly easy"), (90, "easy")):
            if e < cap:
                return label
        return "very easy"

    @property
    def grade_label(self) -> str:
        g = self.fk_grade
        if g < 6:
            return "elementary"
        if g < 9:
            return "middle school"
        if g < 13:
            return "high school"
        if g < 16:
            return "college"
        return "graduate"


def readability(text: str) -> Optional[Readability]:
    """Flesch-Kincaid grade level and Flesch reading ease, or None when
    there's too little text for a meaningful score."""
    words = _WORD_RX.findall(text or "")
    if len(words) < 3:
        return None
    sentences = max(1, len(_SENT_RX.findall(text)) or 1)
    # Paragraphs without terminal punctuation (headings, dialog fragments)
    # still end a sentence.
    for para in re.split(r"\n+", text):
        p = para.strip()
        if p and not re.search(r"[.!?…][\"”’')\]]*$", p) and _WORD_RX.search(p):
            sentences += 1
    syllables = sum(count_syllables(w) for w in words)
    wps = len(words) / sentences
    spw = syllables / len(words)
    grade = 0.39 * wps + 11.8 * spw - 15.59
    ease = 206.835 - 1.015 * wps - 84.6 * spw
    return Readability(len(words), sentences, syllables,
                       round(max(0.0, grade), 1), round(max(0.0, min(100.0, ease)), 1))
