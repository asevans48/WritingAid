"""Inline style checks (ProWritingAid-style) for the manuscript editor.

Every check works on one paragraph and returns issues with offsets into
that paragraph, so the editor's highlighter can draw them as you type and
the Style panel can list them for the whole chapter. Instant — no model.

Checks (``KINDS``):
  passive          — "was taken", "were given"
  adverb           — -ly adverbs (and adverb dialogue tags)
  intensifier      — very / really / quite / just … (fix: delete)
  wordy            — redundancies and hidden verbs, with replacements
                     ("in order to" → "to", "made a decision" → "decided")
  cliche           — stock phrases
  long_sentence    — 30+ words (40+ = very long)
  hard_sentence    — sentence reads above grade 14
  sticky_sentence  — 45%+ glue words
  repeated_start   — 3+ consecutive sentences opening with the same word
  echo             — the same word again within a few words
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class StyleIssue:
    kind: str
    start: int            # offset within the paragraph (or document, see analyze_document)
    end: int
    text: str
    message: str
    suggestions: List[str] = field(default_factory=list)   # "" = delete the text
    sentence_level: bool = False                            # drawn as a background tint


# kind → (label, colour, sentence_level)
KINDS: Dict[str, Tuple[str, str, bool]] = {
    "passive": ("Passive voice", "#ea580c", False),
    "adverb": ("Adverbs", "#d97706", False),
    "intensifier": ("Weak intensifiers", "#ca8a04", False),
    "wordy": ("Wordy phrases", "#16a34a", False),
    "cliche": ("Clichés", "#9333ea", False),
    "repeated_start": ("Repeated sentence starts", "#0284c7", False),
    "echo": ("Echoes", "#0d9488", False),
    "long_sentence": ("Long sentences", "#dbeafe", True),
    "hard_sentence": ("Hard-to-read sentences", "#fee2e2", True),
    "sticky_sentence": ("Sticky sentences", "#fef3c7", True),
}
DEFAULT_KINDS = set(KINDS)

GLUE = set("""the a an and or but in on at to for of with by from as is was are were been be
have has had do does did will would could should may might must shall can need it its this
that these those i you he she we they me him her us them my your his our their what which who
whom whose if then else when where why how all each every both few more most other some such
no not only own same so than too very just also now here there still already even again into
through during before after above below between under over up down out off about any am being
having doing get got getting""".split())

INTENSIFIERS = {"very", "really", "quite", "just", "actually", "basically", "literally",
                "totally", "extremely", "incredibly", "truly", "simply", "rather", "somewhat",
                "fairly", "pretty", "awfully", "terribly", "utterly", "seriously"}
# "-ly" words that aren't adverbs.
LY_NOT_ADVERBS = {"only", "family", "early", "reply", "fly", "ally", "belly", "holy", "lily",
                  "jelly", "rely", "supply", "apply", "ugly", "silly", "jolly", "daily", "likely",
                  "lonely", "lovely", "friendly", "italy", "july", "emily", "kelly", "sally",
                  "molly", "billy", "rally", "bully", "imply", "comply", "multiply", "anomaly",
                  "assembly", "butterfly", "curly", "elderly", "folly", "gully", "homely",
                  "melancholy", "monopoly", "oily", "orderly", "costly", "deadly", "lively",
                  "lowly", "manly", "smelly", "surly", "woolly", "wobbly", "bubbly", "chilly",
                  "hilly", "jelly", "prickly", "sickly", "sly", "unruly", "wily", "ghostly",
                  "kindly", "timely", "weekly", "monthly", "yearly", "hourly", "nightly",
                  "scholarly", "beastly", "cowardly", "friendly", "ugly", "worldly", "heavenly",
                  "earthly", "motherly", "fatherly", "brotherly", "sisterly", "stately", "courtly"}
SPEECH_VERBS = {"said", "asked", "replied", "whispered", "shouted", "muttered", "answered",
                "called", "cried", "snapped", "murmured", "added", "told", "yelled"}
IRREGULAR_PARTICIPLES = set("""born borne beaten become begun bent bitten blown broken brought
built burnt bought caught chosen come cut dealt done drawn driven drunk eaten fallen fed felt
fought found flown forbidden forgotten forgiven frozen given gone ground grown hung heard hidden
hit held hurt kept known laid led left lent let lain lit lost made meant met paid put quit read
ridden rung risen run said seen sought sold sent set shaken shot shown shut sung sunk sat slain
slept slid spoken spent spun split spread stood stolen stuck stung struck sworn swept swum taken
taught torn told thought thrown understood woken worn woven won wound written""".split())
NOT_PASSIVE_ADJECTIVES = {"tired", "scared", "interested", "excited", "bored", "worried",
                          "married", "used", "supposed", "dressed", "pleased", "surprised",
                          "confused", "embarrassed", "frightened", "annoyed", "relieved",
                          "determined", "exhausted", "amazed", "concerned", "ashamed",
                          "satisfied", "disappointed", "prepared", "convinced", "crowded",
                          "involved", "related", "red", "bed", "shed", "sled", "naked",
                          "wicked", "sacred", "hundred", "kindred", "rugged", "jagged"}

WORDY: Dict[str, str] = {
    "in order to": "to", "due to the fact that": "because", "owing to the fact that": "because",
    "in spite of the fact that": "although", "despite the fact that": "although",
    "at this point in time": "now", "at the present time": "now", "in the event that": "if",
    "for the purpose of": "to", "in the near future": "soon", "a large number of": "many",
    "the majority of": "most", "each and every": "every", "first and foremost": "first",
    "absolutely essential": "essential", "completely finished": "finished",
    "close proximity": "proximity", "end result": "result", "free gift": "gift",
    "past history": "history", "final outcome": "outcome", "future plans": "plans",
    "unexpected surprise": "surprise", "advance warning": "warning", "basic fundamentals":
    "fundamentals", "revert back": "revert", "return back": "return", "repeat again": "repeat",
    "join together": "join", "combine together": "combine", "merge together": "merge",
    "circle around": "circle", "stand up on his feet": "stand up", "nodded his head": "nodded",
    "nodded her head": "nodded", "shrugged his shoulders": "shrugged",
    "shrugged her shoulders": "shrugged", "blinked his eyes": "blinked",
    "blinked her eyes": "blinked", "made a decision": "decided", "make a decision": "decide",
    "came to a conclusion": "concluded", "come to a conclusion": "conclude",
    "gave a response": "responded", "took into consideration": "considered",
    "take into consideration": "consider", "has the ability to": "can", "have the ability to":
    "can", "is able to": "can", "are able to": "can", "was able to": "could",
    "were able to": "could", "made an attempt": "tried", "make an attempt": "try",
    "gave an explanation": "explained", "give an explanation": "explain",
    "conducted an investigation": "investigated", "reached an agreement": "agreed",
    "in close proximity to": "near", "with regard to": "about", "with reference to": "about",
    "in regard to": "about", "in terms of": "in", "as a matter of fact": "in fact",
    "began to": "", "started to": "",
}
WORDY_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in WORDY), key=len,
                                               reverse=True)) + r")\b", re.I)

CLICHES = [
    "at the end of the day", "in the nick of time", "all of a sudden", "in the blink of an eye",
    "better late than never", "as luck would have it", "a matter of time", "tip of the iceberg",
    "a sigh of relief", "with bated breath", "without a doubt", "at first glance", "crystal clear",
    "dead of night", "in broad daylight", "pitch black", "blood ran cold", "heart skipped a beat",
    "butterflies in her stomach", "butterflies in his stomach", "like a deer in headlights",
    "like a fish out of water", "cold as ice", "white as a sheet", "black as night",
    "clear as day", "quiet as a mouse", "sick as a dog", "fit as a fiddle", "light as a feather",
    "needle in a haystack", "easy as pie", "piece of cake", "walk in the park", "once upon a time",
    "happily ever after", "last but not least", "long story short", "time stood still",
    "time will tell", "the calm before the storm", "a chill ran down", "shiver down her spine",
    "shiver down his spine", "let out a breath she didn't know she was holding",
    "let out a breath he didn't know he was holding", "a breath she didn't know she was holding",
    "a breath he didn't know he was holding", "her heart pounded", "his heart pounded",
    "eyes widened in shock", "a single tear", "grinned from ear to ear", "smile from ear to ear",
    "out of the blue", "every fiber of her being", "every fiber of his being", "deafening silence",
    "fell on deaf ears", "only time would tell", "the writing on the wall", "in the heat of the moment",
    "head over heels", "against all odds", "love at first sight", "dark and stormy night",
    "rooted to the spot", "frozen in place", "worth its weight in gold", "scared to death",
    "bored to death", "avoid like the plague", "a perfect storm", "by the skin of her teeth",
    "by the skin of his teeth",
]
CLICHE_RX = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(CLICHES, key=len, reverse=True))
                       + r")\b", re.I)

_WORD_RX = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_SENT_RX = re.compile(r"[^.!?…]+(?:[.!?…]+[\"”’')\]]*|$)")
_PASSIVE_RX = re.compile(
    r"\b(am|is|are|was|were|be|been|being|get|gets|got|gotten)\s+(?:(?:not|never|also|then|"
    r"already|just|still|being)\s+)?([a-z]+ed|[a-z]+en|" + "|".join(sorted(IRREGULAR_PARTICIPLES))
    + r")\b(?:\s+(by)\b)?", re.I)


def _syllables(word: str) -> int:
    from src.utils.proofing import count_syllables
    return count_syllables(word)


def sentences_with_offsets(text: str) -> List[Tuple[int, int, str]]:
    out = []
    for m in _SENT_RX.finditer(text):
        s = m.group(0)
        lead = len(s) - len(s.lstrip())
        body = s.strip()
        if body and _WORD_RX.search(body):
            start = m.start() + lead
            out.append((start, start + len(body), body))
    return out


def analyze_paragraph(text: str, kinds: Optional[Iterable[str]] = None) -> List[StyleIssue]:
    """Style issues in one paragraph, offsets relative to ``text``."""
    kinds = set(kinds) if kinds is not None else DEFAULT_KINDS
    issues: List[StyleIssue] = []
    if not text or not text.strip():
        return issues
    add = issues.append
    sentences = sentences_with_offsets(text)

    if "passive" in kinds:
        for m in _PASSIVE_RX.finditer(text):
            part = m.group(2).lower()
            if part in NOT_PASSIVE_ADJECTIVES:
                continue
            if part.endswith("en") and part not in IRREGULAR_PARTICIPLES and len(part) < 6:
                continue          # "seven", "often", "garden"-like false hits
            if part.endswith("ed") and len(part) <= 3:
                continue
            by_agent = bool(m.group(3))
            add(StyleIssue("passive", m.start(), m.end(2), m.group(0)[:m.end(2) - m.start()],
                           "Passive voice" + (" — the actor follows “by”; make them the subject."
                                              if by_agent else
                                              " — consider who does the action and lead with them.")))

    if "adverb" in kinds or "intensifier" in kinds:
        for m in _WORD_RX.finditer(text):
            w = m.group(0)
            low = w.lower()
            if "intensifier" in kinds and low in INTENSIFIERS:
                nxt = text[m.end():m.end() + 1]
                add(StyleIssue("intensifier", m.start(), m.end(), w,
                               f"“{w}” rarely adds strength — cut it or use a stronger word.",
                               suggestions=[""]))
            elif ("adverb" in kinds and low.endswith("ly") and len(low) > 4
                  and low not in LY_NOT_ADVERBS and not w[0].isupper()):
                before = text[max(0, m.start() - 25):m.start()].lower()
                tag = any(re.search(rf"\b{v}\s+$", before) for v in SPEECH_VERBS)
                add(StyleIssue("adverb", m.start(), m.end(), w,
                               ("Adverb dialogue tag — let the dialogue (or an action beat) "
                                "carry the tone." if tag else
                                "Adverb — a stronger verb usually does this job better."),
                               suggestions=[""]))

    if "wordy" in kinds:
        for m in WORDY_RX.finditer(text):
            phrase = m.group(0)
            repl = WORDY[phrase.lower()]
            if repl and phrase[0].isupper():
                repl = repl[0].upper() + repl[1:]
            add(StyleIssue("wordy", m.start(), m.end(), phrase,
                           f"Wordy — “{phrase}” → “{repl}”." if repl else
                           f"“{phrase}” usually isn't needed — start with the action itself.",
                           suggestions=[repl]))

    if "cliche" in kinds:
        for m in CLICHE_RX.finditer(text):
            add(StyleIssue("cliche", m.start(), m.end(), m.group(0),
                           "Cliché — find an image specific to this character and scene."))

    for start, end, sent in sentences:
        words = _WORD_RX.findall(sent)
        n = len(words)
        if "long_sentence" in kinds and n >= 30:
            add(StyleIssue("long_sentence", start, end, sent,
                           f"{'Very long' if n >= 40 else 'Long'} sentence ({n} words) — consider "
                           f"splitting it.", sentence_level=True))
        if "hard_sentence" in kinds and n >= 15:
            syl = sum(_syllables(w) for w in words)
            grade = 0.39 * n + 11.8 * syl / n - 15.59
            if grade >= 14:
                add(StyleIssue("hard_sentence", start, end, sent,
                               f"Hard to read (grade {grade:.0f}) — shorter words and sentences "
                               f"would help.", sentence_level=True))
        if "sticky_sentence" in kinds and n >= 8:
            glue = sum(1 for w in words if w.lower() in GLUE)
            if glue / n >= 0.45 and not ("long_sentence" in kinds and n >= 30):
                add(StyleIssue("sticky_sentence", start, end, sent,
                               f"Sticky sentence ({glue / n:.0%} glue words) — build it around "
                               f"concrete nouns and verbs.", sentence_level=True))

    if "repeated_start" in kinds and len(sentences) >= 3:
        firsts = []
        for start, _end, sent in sentences:
            m = _WORD_RX.search(sent)
            firsts.append((m.group(0).lower() if m else "", start + (m.start() if m else 0),
                           m.group(0) if m else ""))
        run = 1
        for i in range(1, len(firsts)):
            run = run + 1 if firsts[i][0] and firsts[i][0] == firsts[i - 1][0] else 1
            if run >= 3:
                w, pos, orig = firsts[i]
                add(StyleIssue("repeated_start", pos, pos + len(orig), orig,
                               f"{run} sentences in a row start with “{orig}” — vary the openings."))

    if "echo" in kinds:
        words = [(m.group(0).lower(), m.start(), m.end()) for m in _WORD_RX.finditer(text)]
        last: Dict[str, int] = {}
        for i, (w, s, e) in enumerate(words):
            if len(w) < 4 or w in GLUE or w in INTENSIFIERS:
                continue
            j = last.get(w)
            if j is not None and i - j <= 12 and not text[s].isupper():
                add(StyleIssue("echo", s, e, text[s:e],
                               f"“{text[s:e]}” repeats {i - j} word{'s' if i - j != 1 else ''} after its last use."))
            last[w] = i
    return sorted(issues, key=lambda x: (x.start, -(x.end - x.start)))


def analyze_document(text: str, kinds: Optional[Iterable[str]] = None) -> List[StyleIssue]:
    """Style issues for a whole text, offsets into ``text`` (paragraph = line)."""
    out, pos = [], 0
    for line in text.split("\n"):
        for issue in analyze_paragraph(line, kinds):
            issue.start += pos
            issue.end += pos
            out.append(issue)
        pos += len(line) + 1
    return out


def summarize(issues: List[StyleIssue], words: int) -> Dict[str, object]:
    by_kind: Dict[str, int] = {}
    for i in issues:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
    return {"total": len(issues), "words": words, "by_kind": by_kind,
            "per_1000": round(1000 * len(issues) / words, 1) if words else 0.0}
