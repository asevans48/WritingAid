"""More style checks (piece P.2a): transitions, pronouns, alliteration, acronyms.

ProWritingAid has a report for each; here each is a kind in
``style_checks.KINDS``, so it shows in the editor's highlights, the Style
tab, the Checks menu's Style checks submenu and the next-fix queue like the
others. All four are **off until the writer ticks them** (``NEW_KINDS`` is
left out of ``style_checks.DEFAULT_KINDS``). Plain word scans, no model.

  transition    — a paragraph of six or more sentences with no linking
                  word at all (but, then, when, because, however …)
  pronoun       — four or more sentences in a row that open with a
                  pronoun (He … She … He … They …), or one sentence that
                  leans on the same he/she/they many times
  alliteration  — three or more words close together with the same
                  opening sound ("silver sea sang softly")
  acronym       — an acronym written two ways (F.B.I. and FBI), used
                  before it is spelled out, or never spelled out in the
                  chapter (well-known ones like TV or FBI are left alone)

Only the acronym check has a suggestion (the form used most), because it is
the only one with one right replacement; the others are for the writer to
judge, so "Fix all N" is not offered for them.

``transition_share(text)`` gives the chapter's share of sentences that use
a transition, for the Style tab's summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# Kinds added in P.2a. Off by default (rule 11).
NEW_KINDS = ("transition", "pronoun", "alliteration", "acronym")

# ── Transitions ─────────────────────────────────────────────────────────

TRANSITION_WORDS = frozenset("""
however therefore thus hence meanwhile then later afterward afterwards finally first firstly
second secondly third next also but yet so because although though instead still besides
moreover furthermore nevertheless nonetheless otherwise consequently accordingly likewise
similarly eventually soon until unless while whereas since after before once when whenever
now again anyway indeed or nor
""".split())
TRANSITION_PHRASES = (
    "in fact", "for example", "for instance", "as a result", "on the other hand",
    "at the same time", "even so", "by then", "at last", "after that", "in the end",
    "of course", "in other words", "at first", "in addition", "as well", "even though",
    "so that", "as soon as", "in the meantime", "after all", "all the same", "by the time",
)
_PHRASE_RX = re.compile(r"\b(" + "|".join(re.escape(p) for p in TRANSITION_PHRASES) + r")\b", re.I)
MIN_SENTENCES_WITHOUT = 6      # a paragraph this long with no transition is flagged
MIN_SENTENCE_WORDS = 4         # shorter sentences (fragments, "No.") are not counted


def uses_transition(sentence: str) -> bool:
    from src.utils.style_checks import _WORD_RX
    if any(w.lower() in TRANSITION_WORDS for w in _WORD_RX.findall(sentence)):
        return True
    return bool(_PHRASE_RX.search(sentence))


def transition_share(text: str) -> Tuple[int, int]:
    """(sentences that use a transition, sentences) in ``text``."""
    from src.utils.style_checks import sentences_with_offsets
    used = total = 0
    for line in (text or "").split("\n"):
        for _s, _e, sent in sentences_with_offsets(line):
            total += 1
            used += uses_transition(sent)
    return used, total


def _transitions(text: str, sentences, add) -> None:
    from src.utils.style_checks import StyleIssue, _WORD_RX
    counted = [s for s in sentences if len(_WORD_RX.findall(s[2])) >= MIN_SENTENCE_WORDS]
    if len(counted) < MIN_SENTENCES_WITHOUT:
        return
    if any(uses_transition(s[2]) for s in sentences):
        return
    start, end = sentences[0][0], sentences[-1][1]
    add(StyleIssue("transition", start, end, text[start:end],
                   f"No transitions in {len(sentences)} sentences — a linking word here and "
                   f"there (but, then, because, still …) helps the reader follow.",
                   sentence_level=True))


# ── Pronouns ────────────────────────────────────────────────────────────

SUBJECT_PRONOUNS = frozenset({"i", "you", "he", "she", "it", "we", "they"})
PRONOUN_FAMILIES = {
    "he": {"he", "him", "his", "himself"},
    "she": {"she", "her", "hers", "herself"},
    "they": {"they", "them", "their", "theirs", "themselves"},
}
_FAMILY_OF = {w: fam for fam, words in PRONOUN_FAMILIES.items() for w in words}
PRONOUN_RUN = 4            # sentences in a row opening with a pronoun
SAME_PRONOUN_IN_SENTENCE = 5
_OPEN_QUOTES = "\"“"


def _in_dialogue(text: str, pos: int) -> bool:
    """Is ``pos`` inside a quotation (counting quote marks before it)?"""
    before = text[:pos]
    curly_open, curly_close = before.count("“"), before.count("”")
    if curly_open or curly_close:
        return curly_open > curly_close
    return before.count('"') % 2 == 1


def _pronoun_run(run, kinds, add) -> None:
    """One flag for a run of pronoun openings, on its fourth sentence."""
    from src.utils.style_checks import StyleIssue
    if len(run) < PRONOUN_RUN:
        return
    if "repeated_start" in kinds and len({r[0] for r in run}) == 1:
        return                                   # "He … He … He …" is repeated_start's flag
    _b, pos, orig = run[PRONOUN_RUN - 1]
    add(StyleIssue("pronoun", pos, pos + len(orig), orig,
                   f"{len(run)} sentences in a row open with a pronoun — start one with a "
                   f"name, an action or a detail."))


def _pronouns(text: str, sentences, kinds, add) -> None:
    from src.utils.style_checks import StyleIssue, _WORD_RX
    run: List[Tuple[str, int, str]] = []       # (lower word, position, word) of the run
    for start, end, sent in sentences:
        m = _WORD_RX.search(sent)
        lead = sent[:m.start()] if m else ""
        word = m.group(0) if m else ""
        base = word.split("'")[0].lower()
        quoted = any(c in lead for c in _OPEN_QUOTES) or _in_dialogue(text, start)
        if m and base in SUBJECT_PRONOUNS and not quoted:
            run.append((base, start + m.start(), word))
        else:
            _pronoun_run(run, kinds, add)
            run = []
        # One sentence that leans on the same pronoun (who is "he" now?).
        if _in_dialogue(text, start) or any(c in lead for c in _OPEN_QUOTES):
            continue
        spots: Dict[str, List[Tuple[int, int]]] = {}
        for w in _WORD_RX.finditer(sent):
            fam = _FAMILY_OF.get(w.group(0).lower())
            if fam:
                spots.setdefault(fam, []).append((start + w.start(), start + w.end()))
        for fam, where in spots.items():
            if len(where) >= SAME_PRONOUN_IN_SENTENCE:
                s, e = where[0][0], where[-1][1]
                add(StyleIssue("pronoun", s, e, text[s:e],
                               f"“{fam}” and its forms {len(where)} times in one sentence — the "
                               f"reader may lose track of who is who; name someone."))
    _pronoun_run(run, kinds, add)


# ── Alliteration ────────────────────────────────────────────────────────

ALLITERATION_RUN = 3        # words with the same opening sound
MAX_GAP = 1                 # small words allowed between two of them


def opening_sound(word: str) -> str:
    """A rough opening sound: "ph" → f, "kn" → n, soft "c" → s, hard "c" → k.
    "" for a vowel (vowel runs are not counted)."""
    w = word.lower()
    for prefix, sound in (("ph", "f"), ("kn", "n"), ("wr", "r"), ("gn", "n"), ("ps", "s"),
                          ("wh", "w"), ("ch", "ch"), ("sh", "sh"), ("th", "th")):
        if w.startswith(prefix):
            return sound
    if not w or w[0] in "aeiouy":
        return ""
    if w[0] == "c":
        return "s" if w[1:2] in ("e", "i", "y") else "k"
    if w[0] == "q":
        return "k"
    return w[0]


def _alliteration(text: str, sentences, add) -> None:
    from src.utils.style_checks import GLUE, StyleIssue, _WORD_RX
    for start, _end, sent in sentences:
        words = [(m.group(0), start + m.start(), start + m.end()) for m in _WORD_RX.finditer(sent)]
        run: List[Tuple[str, int, int]] = []
        gap = 0
        sound = ""
        for w, s, e in words:
            low = w.lower()
            if low in GLUE or len(low) < 3:
                gap += 1
                if gap > MAX_GAP:
                    _flush(text, run, add)
                    run, sound = [], ""
                continue
            snd = opening_sound(low)
            if snd and snd == sound:
                run.append((w, s, e))
            else:
                _flush(text, run, add)
                run, sound = ([(w, s, e)], snd) if snd else ([], "")
            gap = 0
        _flush(text, run, add)


def _flush(text: str, run, add) -> None:
    from src.utils.style_checks import StyleIssue
    if len(run) < ALLITERATION_RUN:
        return
    if len({w.lower() for w, _s, _e in run}) < len(run):
        return                                 # a repeated word is an echo, not alliteration
    s, e = run[0][1], run[-1][2]
    add(StyleIssue("alliteration", s, e, text[s:e],
                   f"{len(run)} words in a row start with the same sound — fine if you meant "
                   f"it; otherwise it can read as a tongue-twister."))


# ── Acronyms ────────────────────────────────────────────────────────────

# Known to every reader: never asked to be spelled out.
WELL_KNOWN = frozenset("""
OK AM PM TV ID FBI CIA NSA NASA USA US UK EU UN DNA CEO CPR ICU ER GPS ATM PC IQ UFO VIP HQ
DIY FAQ BBC CNN NBA NFL MRI CT RV SUV IRS NYPD LAPD MIT UCLA NATO AIDS HIV LSD DVD CD PIN
RSVP ASAP IOU SOS AWOL MIA POW USB URL PDF NYC LA DC BC AD BCE CE ETA KGB DA ATV EMT GP NHS
MP RAF USSR TNT SAT GPA ESP AC DJ PR HR IT AI PS PTSD ADHD OCD BMW ATF DEA DMV LED LCD CCTV
SWAT SIM CPU RAM ROM VR AR TB RIP AKA BS OMG LOL MC EMS IV OR ED MD RN PE GI NCO CO XO MI
DOJ DOD DHS CDC WHO IED MBA BA MA BSC SMS PA PTA ICBM WMD AWACS JFK LBJ FDR MLK NYU USC UCL LSE
""".split())
# Chapter and king numbers (XII, VIII, XLV); "CD" and "MI" stay acronyms.
_ROMAN_RX = re.compile(r"^(?=[IVXL])(XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ACRONYM_RX = re.compile(r"(?<![A-Za-z.])(?:(?:[A-Z]\.){2,6}|[A-Z]{2,6}(?:['’]?s)?)(?![A-Za-z])")
_SMALL = frozenset({"of", "the", "and", "for", "a", "an", "in", "on", "at", "to", "&"})


@dataclass(frozen=True)
class AcronymFacts:
    """What the acronym check knows about a whole document."""
    first_use: Dict[str, int]          # letters → offset of first use
    spelled_at: Dict[str, int]         # letters → offset where it is spelled out
    forms: Dict[str, Dict[str, int]]   # letters → {form as written: times}

    @property
    def signature(self) -> tuple:
        return (tuple(sorted(self.first_use.items())), tuple(sorted(self.spelled_at.items())),
                tuple(sorted((k, tuple(sorted(v.items()))) for k, v in self.forms.items())))


def _letters(token: str) -> str:
    return re.sub(r"['’]?s$", "", token).replace(".", "")


def _form(token: str) -> str:
    """The token as written, without a plural ending ("CDs" → "CD")."""
    return token if token.endswith(".") else re.sub(r"['’]?s$", "", token)


def _candidates(text: str):
    """(letters, form, start, end) for each acronym-like token in ``text``."""
    from src.utils.style_checks import GLUE
    lower_words = None
    for m in _ACRONYM_RX.finditer(text):
        token = m.group(0)
        letters = _letters(token)
        if len(letters) < 2 or _ROMAN_RX.match(letters):
            continue
        if letters.lower() in GLUE:
            continue                                    # "NOT", "SO": emphasis
        if text[m.end():m.end() + 1] == "!":
            continue                                    # shouting
        around = text[max(0, m.start() - 12):m.end() + 12]
        if "." not in token and len(re.findall(r"\b[A-Z]{2,}\b", around)) >= 2:
            continue                                    # a run of capitals: shouting or a heading
        if lower_words is None:
            lower_words = set(re.findall(r"\b[a-z]+\b", text))
        if letters.lower() in lower_words:
            continue                                    # "STOP" when "stop" is a word here
        yield letters, _form(token), m.start(), m.end()


def _spelled_out(text: str, letters: str) -> Optional[int]:
    """Where words whose first letters spell ``letters`` appear (capitalised,
    as a name is, or in any case when the acronym follows in brackets), or
    None. Small words (of, the, and …) may sit between them."""
    n = len(letters)
    words = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[A-Za-z&]+", text)]
    for i, (w0, s0, _e0) in enumerate(words):
        if w0[0].upper() != letters[0] or (w0.isupper() and len(w0) > 1):
            continue
        k, j, caps = 0, i, True
        while j < len(words) and k < n:
            w = words[j][0]
            if w.isupper() and len(w) > 1:
                break
            if w[0].upper() == letters[k]:
                k += 1
                caps = caps and (w[0].isupper() or w.lower() in _SMALL)
            elif k == 0 or w.lower() not in _SMALL:
                break
            j += 1
        if k < n:
            continue
        end = words[j - 1][2]
        if caps and w0[0].isupper():
            return s0
        if re.match(r"\s*[(,]\s*(?:or\s+)?" + re.escape(letters), text[end:end + 12]):
            return s0
    return None


@lru_cache(maxsize=8)
def acronym_facts(document: str) -> AcronymFacts:
    first: Dict[str, int] = {}
    forms: Dict[str, Dict[str, int]] = {}
    for letters, form, s, _e in _candidates(document or ""):
        first.setdefault(letters, s)
        f = forms.setdefault(letters, {})
        f[form] = f.get(form, 0) + 1
    spelled = {}
    for letters in first:
        at = _spelled_out(document, letters)
        if at is not None:
            spelled[letters] = at
    return AcronymFacts(first, spelled, forms)


@lru_cache(maxsize=4)
def _normalized(document: str) -> str:
    from src.utils.proofing import normalize_apostrophes
    return normalize_apostrophes(document)


def acronym_signature(document: Optional[str]) -> Optional[tuple]:
    """What the acronym flags of any paragraph depend on (for caches)."""
    return acronym_facts(_normalized(document)).signature if document else None


def _is_word(letters: str) -> bool:
    """An ordinary English word in capitals? (the editor's dictionary)"""
    try:
        from src.utils import spell_checker as sp
        shared = getattr(sp, "_SHARED_PYSPELL", None)
        if shared is not None:
            return bool(shared.known([letters.lower()]))
        from src.ai.rewrite_quality import _known_word
        return _known_word(letters)
    except Exception:
        return False


def _line_at(document: str, pos: int) -> str:
    a = document.rfind("\n", 0, pos) + 1
    b = document.find("\n", pos)
    return document[a:b if b >= 0 else len(document)]


def _acronyms(text: str, document: Optional[str], add) -> None:
    from src.utils.style_checks import StyleIssue
    doc = _normalized(document) if document else text
    facts = acronym_facts(doc)
    seen = set()
    for letters, form, s, e in _candidates(text):
        forms = facts.forms.get(letters, {})
        if len(forms) > 1:
            best = max(forms.items(), key=lambda kv: (kv[1], "." not in kv[0]))[0]
            if form != best:
                add(StyleIssue("acronym", s, s + len(form), text[s:s + len(form)],
                               f"Written “{best}” elsewhere in this chapter — use one form.",
                               suggestions=[best]))
                continue
        if letters in seen or letters in WELL_KNOWN:
            continue
        seen.add(letters)
        if "." not in form and _is_word(letters):
            continue                                    # "BACK", "HUGE": emphasis, not an acronym
        first = facts.first_use.get(letters)
        if first is None or _line_at(doc, first) != text:
            continue                                    # only its first use is flagged
        spelled = facts.spelled_at.get(letters)
        if spelled is None:
            add(StyleIssue("acronym", s, e, text[s:e],
                           f"“{letters}” isn't spelled out in this chapter — give the full name "
                           f"the first time, unless every reader knows it."))
        elif spelled > first + 60:
            add(StyleIssue("acronym", s, e, text[s:e],
                           f"“{letters}” is used before it is spelled out — give the full name "
                           f"here, at its first use."))


# ── Entry point (called by style_checks._analyze) ────────────────────────

def analyze(text: str, sentences, kinds, add, document: Optional[str] = None) -> None:
    if "transition" in kinds:
        _transitions(text, sentences, add)
    if "pronoun" in kinds:
        _pronouns(text, sentences, kinds, add)
    if "alliteration" in kinds:
        _alliteration(text, sentences, add)
    if "acronym" in kinds:
        _acronyms(text, document, add)
