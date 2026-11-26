"""Overly descriptive statements, and ways to expand them.

An overly descriptive statement tells the reader how something is
instead of letting a detail, action or consequence show it ("The room
was almost too dark", "She felt very angry"). Qualifiers and
intensifiers like *too*, *almost*, *very* or *seemed* are clues, but
they don't prove anything: "she almost fell" is an action, and "too"
can mean "also".

Two layers, so the feature works the way each tool is already set up:

* ``scan`` needs no model. It finds candidate sentences from their cue
  words, explains each, and offers a trimmed version and questions that
  help the writer expand the statement.
* ``review_passage`` and ``review_chapter`` take whichever model the
  calling tool already resolved (local or cloud). The model confirms or
  clears each candidate, finds statements the scan can't see, and
  writes expansions in the author's voice. If the model is missing or
  its call fails, the scan results are returned unchanged.

Everything except the model call is deterministic and tested without a
model. The parser is lenient because small local models rarely follow
a format exactly.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ── Data ─────────────────────────────────────────────────────────────


@dataclass
class Cue:
    """A word or phrase that hints a sentence describes instead of showing."""
    phrase: str           # as written, e.g. "too dark"
    category: str         # degree | hedge | impression | telling | stacked | adverbs
    start: int            # offsets within the sentence
    end: int
    weight: float = 0.5   # how strongly it suggests over-description


@dataclass
class Expansion:
    text: str                       # replaces the whole statement
    approach: str = ""              # e.g. "show the effect"
    why: str = ""
    notes: List[str] = field(default_factory=list)   # problems the checks found
    voice_fit: Optional[float] = None
    by_ai: bool = True


@dataclass
class Flag:
    """One overly descriptive statement (a whole sentence)."""
    start: int                      # offsets into the text that was scanned
    end: int
    text: str
    cues: List[Cue] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""
    hints: List[str] = field(default_factory=list)   # ways to expand (questions)
    expansions: List[Expansion] = field(default_factory=list)
    source: str = "scan"            # scan | ai | both
    verdict: str = ""               # "" (not judged) | "over" | "fine"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Flag":
        data = dict(data)
        data["cues"] = [Cue(**c) for c in data.get("cues", [])]
        data["expansions"] = [Expansion(**x) for x in data.get("expansions", [])]
        return cls(**data)


@dataclass
class Review:
    flags: List[Flag] = field(default_factory=list)     # shown to the writer
    cleared: List[Flag] = field(default_factory=list)   # scan hits the model judged fine
    used_ai: bool = False
    error: str = ""                                     # why the model wasn't used


# ── Cues ─────────────────────────────────────────────────────────────

# Words after "too" that make it mean "also" or start a clause.
_TOO_NOT = {"and", "but", "or", "so", "for", "then", "as", "if", "when", "while", "because",
            "until", "though", "although", "before", "after", "since", "at", "in", "on", "with"}
_EMOTIONS = ("angry|furious|sad|happy|scared|afraid|frightened|terrified|nervous|anxious|"
             "worried|excited|tired|exhausted|lonely|guilty|ashamed|embarrassed|jealous|"
             "hopeful|hopeless|relieved|confused|overwhelmed|upset|miserable|annoyed|"
             "frustrated|elated|desperate|uneasy|uncomfortable|calm|content|grateful")
_ADJECTIVES = set("""dark bright cold hot warm cool damp wet dry old young ancient new big small
huge tiny vast narrow wide long short tall low high heavy light thick thin soft hard rough smooth
sharp dull quiet loud silent still empty full dirty clean filthy pale grey gray black white red
blue green golden silver bitter sweet sour sticky slick slimy rotten rusty dusty musty moldy
gloomy dim shadowy shimmering glittering gleaming beautiful ugly strange eerie cramped crowded
endless hollow cracked broken ragged worn faded crumbling icy frozen burning blazing misty foggy
murky stale fresh fragile delicate gentle fierce wild savage cruel grim bleak dreary lonely
desolate barren lush thin gaunt""".split())
_LOOKED_NOT = {"at", "up", "down", "away", "back", "around", "round", "over", "out", "in", "for",
               "to", "into", "through", "after", "on", "toward", "towards", "across", "past",
               "about", "like", "as", "of"}

# (regex, category, weight, words that may not follow). Matched
# case-insensitively against narration; group 1 (when present) is the
# word checked against the exclusions.
_CUE_PATTERNS: List[Tuple["re.Pattern", str, float, frozenset]] = [
    (re.compile(r"\b(?:felt|feel|feels|feeling)\s+(?:so\s+|very\s+|really\s+|a\s+bit\s+)?"
                r"(?:" + _EMOTIONS + r")\b", re.I), "telling", 0.8, frozenset()),
    (re.compile(r"\b(?:was|were|is|are|grew|became|got)\s+(?:so\s+|very\s+|really\s+)?"
                r"(?:" + _EMOTIONS + r")\b", re.I), "telling", 0.6, frozenset()),
    (re.compile(r"\btoo\s+(\w+)", re.I), "degree", 1.0, frozenset(_TOO_NOT)),
    (re.compile(r"\balmost\b", re.I), "hedge", 1.0, frozenset()),
    (re.compile(r"\bnearly\b", re.I), "hedge", 0.8, frozenset()),
    (re.compile(r"\bso\s+\w+\s+that\b", re.I), "degree", 0.7, frozenset()),
    (re.compile(r"\b(?:very|extremely|incredibly|utterly|terribly|awfully|impossibly|"
                r"unbelievably|so\s+very)\s+\w+", re.I), "degree", 0.6, frozenset()),
    (re.compile(r"\b(?:somewhat|slightly|a\s+bit|kind\s+of|sort\s+of|fairly|quite|"
                r"barely|practically|virtually|just\s+about|more\s+or\s+less)\b", re.I),
     "hedge", 0.6, frozenset()),
    (re.compile(r"\brather\b(?!\s+than)", re.I), "hedge", 0.6, frozenset()),
    (re.compile(r"\ba\s+little\b(?=\s+(?:too|more|less|\w+er\b|\w+ly\b))", re.I), "hedge", 0.6,
     frozenset()),
    (re.compile(r"\b(?:seemed|seems|seem|appeared|appears)\s+(?:to|like|as)\b", re.I),
     "impression", 0.7, frozenset()),
    (re.compile(r"\bas\s+(?:if|though)\b", re.I), "impression", 0.4, frozenset()),
    (re.compile(r"\b(?:looked|looks|sounded|sounds|smelled|smelt|smells|tasted|tastes)"
                r"\s+(\w+)", re.I), "impression", 0.6, frozenset(_LOOKED_NOT)),
]
_STACKED_WEIGHT = 0.8
_ADVERB_WEIGHT = 0.25           # each, when a sentence has two or more
_ADVERB_RX = re.compile(r"\b[a-z]{3,}ly\b", re.I)
_WORD_RX = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_QUOTE_RX = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")

CATEGORY_LABELS = {
    "degree": "tells how much", "hedge": "hedges", "impression": "gives an impression",
    "telling": "names a feeling", "stacked": "stacks adjectives", "adverbs": "piles up adverbs",
    "ai": "spotted by the AI",
}
THRESHOLD = 0.6


def _narration_mask(sentence: str) -> str:
    """The sentence with quoted speech blanked out (offsets kept):
    characters may talk however they like."""
    return _QUOTE_RX.sub(lambda m: " " * len(m.group(0)), sentence)


def _stacked(narration: str) -> List[Tuple[int, int]]:
    """Runs of two or more descriptive adjectives: "the cold, dark, damp room"."""
    out = []
    words = [(m.group(0).lower(), m.start(), m.end()) for m in _WORD_RX.finditer(narration)]
    i = 0
    while i < len(words):
        if words[i][0] not in _ADJECTIVES:
            i += 1
            continue
        j = i
        while j + 1 < len(words):
            gap = narration[words[j][2]:words[j + 1][1]]
            nxt = words[j + 1][0]
            if nxt in _ADJECTIVES and gap.strip() in (",", ""):
                j += 1
            elif (nxt == "and" and j + 2 < len(words) and words[j + 2][0] in _ADJECTIVES
                  and gap.strip() in (",", "")):
                j += 2
            else:
                break
        count = sum(1 for w in words[i:j + 1] if w[0] in _ADJECTIVES)
        if count >= 3 or (count == 2 and "," in narration[words[i][1]:words[j][2]]):
            out.append((words[i][1], words[j][2]))
        i = j + 1
    return out


def find_cues(sentence: str) -> List[Cue]:
    """Cue words in the narration of one sentence."""
    from src.utils.style_checks import LY_NOT_ADVERBS
    narr = _narration_mask(sentence)
    cues: List[Cue] = []
    taken: List[Tuple[int, int]] = []

    def add(s, e, category, weight):
        if any(s < te and ts < e for ts, te in taken):
            return
        taken.append((s, e))
        cues.append(Cue(sentence[s:e], category, s, e, weight))

    for rx, category, weight, not_after in _CUE_PATTERNS:
        for m in rx.finditer(narr):
            if rx.groups and not_after:
                follower = (m.group(1) or "").lower()
                if follower in not_after or (category == "impression"
                                             and follower.endswith("ing")):
                    continue
            add(m.start(), m.end(), category, weight)
    for s, e in _stacked(narr):
        add(s, e, "stacked", _STACKED_WEIGHT)
    adverbs = [m for m in _ADVERB_RX.finditer(narr) if m.group(0).lower() not in LY_NOT_ADVERBS]
    if len(adverbs) >= 2:
        for m in adverbs:
            add(m.start(), m.end(), "adverbs", _ADVERB_WEIGHT)
    cues.sort(key=lambda c: c.start)
    return cues


def _score(cues: Sequence[Cue]) -> float:
    return round(sum(c.weight for c in cues), 2)


# ── Sentences ────────────────────────────────────────────────────────

def sentence_spans(text: str) -> List[Tuple[int, int]]:
    """(start, end) of every sentence in ``text``, across paragraphs."""
    from src.ai.passage_critique import _sentence_spans
    out, pos = [], 0
    for para in (text or "").split("\n"):
        out += [(pos + s, pos + e) for s, e in _sentence_spans(para)]
        pos += len(para) + 1
    return out


# ── Without a model ──────────────────────────────────────────────────

_TRIM_WORD = (
    r"(?:almost|nearly|very|extremely|incredibly|utterly|terribly|awfully|impossibly|"
    r"unbelievably|somewhat|slightly|a\s+bit|kind\s+of|sort\s+of|rather(?!\s+than)|fairly|quite|"
    r"practically|virtually|just\s+about|more\s+or\s+less|a\s+little|really)")
# A run counts as one ("very, very cold" → "cold", not "very, cold").
_TRIM_WORDS = re.compile(rf"\b{_TRIM_WORD}(?:\s*,\s*{_TRIM_WORD})*\s+", re.I)


def _describing(rest: str) -> bool:
    m = re.match(r"[A-Za-z]+", rest)
    word = m.group(0).lower() if m else ""
    return (word in _ADJECTIVES or word in ("too", "as", "so", "very")
            or word.endswith(("y", "ous", "ful", "less", "ic", "ive", "ish", "ent", "ant")))


def trimmed(sentence: str) -> str:
    """The sentence with its qualifiers cut ("almost too dark" → "too
    dark" → "dark"). "too" stays when a clause hangs on it ("too dark
    to see"). Quoted speech is left alone."""
    narr = _narration_mask(sentence)
    # "almost fell" is an action, not a description: "almost" and
    # "nearly" are only cut before a describing word ("almost too dark").
    cut: List[Tuple[int, int]] = [
        (m.start(), m.end()) for m in _TRIM_WORDS.finditer(narr)
        if not m.group(0).lower().startswith(("almost", "nearly"))
        or _describing(narr[m.end():])]
    for m in re.finditer(r"\btoo\s+(\w+)", narr, re.I):
        if m.group(1).lower() in _TOO_NOT:
            continue
        rest = narr[m.end():m.end() + 40]
        if re.match(r"(?:\s+\w+){0,3}?\s+(?:to|for)\b", rest, re.I):
            continue                    # "too dark to see" needs its "too"
        cut.append((m.start(), m.start(1)))
    if not cut:
        return sentence
    out, last = [], 0
    for s, e in sorted(cut):
        if s < last:
            continue
        out.append(sentence[last:s])
        last = e
        # "a very old" → "an old": fix the article the cut left behind.
        m = re.search(r"\b([Aa]n?) $", out[-1])
        nxt = re.match(r"[A-Za-z]+", sentence[e:])
        if m and nxt:
            word = nxt.group(0).lower()
            an = word[:1] in "aeiou" and not word.startswith(("uni", "use", "eu", "one"))
            out[-1] = out[-1][:m.start()] + m.group(1)[0] + ("n" if an else "") + " "
    out.append(sentence[last:])
    text = "".join(out)
    text = re.sub(r"[ \t]{2,}", " ", text).replace(" ,", ",").replace(" .", ".")
    if text and sentence[:1].isupper() and text[:1].islower():
        text = text[0].upper() + text[1:]
    return text.strip()


_HINTS = {
    "degree": "“{p}” tells the reader how much. Show it instead: what can't they do, see or "
              "bear because of it?",
    "hedge": "“{p}” hedges. Either commit to it, or slow down and show the near miss — the "
             "instant before it would have happened.",
    "impression": "“{p}” reports an impression. Give the evidence behind it: the one detail "
                  "that makes it seem that way.",
    "telling": "“{p}” names the feeling. Show it through the body or an action: hands, breath, "
               "voice, what they do next.",
    "stacked": "“{p}” stacks adjectives. Keep the strongest one and turn the others into "
               "something the character notices or does.",
    "adverbs": "The adverbs (“{p}”…) carry the manner. Let stronger verbs or a concrete beat "
               "do that work.",
}


def hints_for(cues: Sequence[Cue]) -> List[str]:
    out, seen = [], set()
    for c in cues:
        if c.category in seen or c.category not in _HINTS:
            continue
        seen.add(c.category)
        out.append(_HINTS[c.category].format(p=c.phrase.strip()))
    return out


def _reason(cues: Sequence[Cue]) -> str:
    if not cues:
        return ""
    phrases = ", ".join(f"“{c.phrase.strip()}”" for c in cues[:3])
    kinds = []
    for c in cues:
        label = CATEGORY_LABELS.get(c.category, "")
        if label and label not in kinds:
            kinds.append(label)
    return f"Leans on {phrases} — it {' and '.join(kinds[:2])} instead of showing."


def _offline_expansions(sentence: str) -> List[Expansion]:
    cut = trimmed(sentence)
    if cut and " ".join(cut.split()) != " ".join(sentence.split()):
        return [Expansion(cut, "cut the qualifiers", "Commits to the description; expand it "
                          "with one of the ideas above if it now feels thin.", by_ai=False)]
    return []


def scan(text: str, start: int = 0, end: Optional[int] = None, *,
         threshold: float = THRESHOLD) -> List[Flag]:
    """Candidate overly descriptive sentences in ``text[start:end]``,
    offsets into ``text``. No model needed."""
    end = len(text) if end is None else end
    flags = []
    for s, e in sentence_spans(text[start:end]):
        sentence = text[start + s:start + e]
        cues = find_cues(sentence)
        score = _score(cues)
        if score < threshold:
            continue
        flags.append(Flag(start + s, start + e, sentence, cues, score, _reason(cues),
                          hints_for(cues), _offline_expansions(sentence)))
    return flags


# ── With a model ─────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a fiction line editor who spots statements that tell the reader how something "
    "is instead of showing it, and rewrites them in the author's own voice. You quote the "
    "text exactly, are specific, and never pad.")

DEFINITION = (
    "An overly descriptive statement tells the reader how something is — how dark, how "
    "afraid, how big — instead of letting a concrete detail, action or consequence show it. "
    "It often leans on qualifiers and intensifiers (too, almost, nearly, very, so, rather, "
    "seemed, felt), stacked adjectives or named feelings. Those words are clues, not proof: "
    "\"she almost fell\" is an action, \"too\" can mean \"also\", and a plain, quick "
    "description is sometimes exactly right. Dialogue may talk however the character talks.")

APPROACHES = [
    ("show the effect", "what the quality makes someone do, fail to do, or notice"),
    ("sensory detail", "one or two concrete details from the scene that carry the description"),
]


def _numbered(sentences: Sequence[str]) -> str:
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))


def build_passage_prompt(ctx: Any, sentences: Sequence[str], flags: Sequence[Flag],
                         index_of: Dict[int, int], *, compact: bool = False) -> str:
    """``index_of`` maps a flag's position in ``flags`` to its sentence number."""
    parts = []
    for title, body in (("THE AUTHOR'S VOICE", getattr(ctx, "voice", "")),
                        ("STYLE SHEET", getattr(ctx, "style_sheet", "")),
                        ("THE AUTHOR'S TASTE", "" if compact else getattr(ctx, "examples", "")),
                        ("CHARACTERS IN THIS PASSAGE",
                         "" if compact else getattr(ctx, "characters", ""))):
        if (body or "").strip():
            parts.append(f"=== {title} ===\n{body.strip()}")
    scene = ctx.scene(800 if compact else 1500) if hasattr(ctx, "scene") else ""
    if scene:
        parts.append("=== THE SCENE (already written — the passage is marked) ===\n" + scene)
    parts.append("=== THE PASSAGE, SENTENCE BY SENTENCE ===\n" + _numbered(sentences))
    if flags:
        parts.append("=== POSSIBLY OVERLY DESCRIPTIVE (a word scan found these clues; not "
                     "every one is a problem) ===\n"
                     + "\n".join(f"[{index_of[i]}] clues: "
                                 + ", ".join(f"“{c.phrase.strip()}”" for c in f.cues)
                                 for i, f in enumerate(flags)))
    approaches = "\n".join(f"EXPANSION {i} ({name}): <replacement for that sentence — {how}>"
                           for i, (name, how) in enumerate(APPROACHES, 1))
    parts.append(
        DEFINITION + "\n\n"
        "Judge each sentence listed above, and also name any other sentence of the passage "
        "that is overly descriptive without those words. Leave alone sentences that already "
        "work.\n\n"
        "For each statement that IS overly descriptive, write two expansions. Each replaces "
        "only that one sentence (it may become up to three sentences) and shows what the "
        "statement tells. Write them in the author's voice: same point of view, tense, "
        "rhythm and vocabulary. Add no new objects, people, places or events that aren't in "
        "the scene or the notes; sensory detail that fits the scene is fine. Keep any "
        "dialogue word for word.\n\n"
        "Answer in exactly this format, one block per sentence you judge:\n\n"
        "STATEMENT [<number>]: <the sentence, quoted exactly>\n"
        "VERDICT: overly descriptive | fine\n"
        "WHY: <one sentence>\n" + approaches + "\n\n"
        "Write the EXPANSION lines only when the verdict is overly descriptive.")
    return "\n\n".join(parts)


def build_chapter_prompt(sentences: Sequence[str], numbers: Sequence[int], voice: str = "",
                         excerpt: str = "") -> str:
    """Judge the scan's candidates in a whole chapter; ``numbers`` are the
    candidates' sentence numbers in ``sentences``."""
    parts = []
    if voice.strip():
        parts.append(f"=== THE AUTHOR'S VOICE ===\n{voice.strip()}")
    if excerpt.strip():
        parts.append("=== THE CHAPTER (look here for other statements too) ===\n"
                     + excerpt.strip())
    parts.append("=== CANDIDATES (a word scan found clues in these) ===\n"
                 + "\n".join(f"[{n}] {sentences[n - 1]}" for n in numbers))
    parts.append(
        DEFINITION + "\n\n"
        "Judge each candidate." + (" Then add up to three other sentences from the chapter "
                                   "that are overly descriptive without those words, quoted "
                                   "exactly, numbered [+]." if excerpt.strip() else "") +
        "\n\nAnswer in exactly this format, one block per sentence:\n\n"
        "STATEMENT [<number>]: <the sentence, quoted exactly>\n"
        "VERDICT: overly descriptive | fine\n"
        "WHY: <one sentence>")
    return "\n\n".join(parts)


# ── Parsing ──────────────────────────────────────────────────────────

_STATEMENT_RX = re.compile(
    r"^\s*(?:#+\s*)?(?:\*\*|__)?\s*(?:statement|sentence)\s*#?\s*\[?\s*(\d+|\+|new|other)?\s*\]?"
    r"\s*(?:\*\*|__)?\s*[:.\-–—)]?\s*(?:\*\*|__)?\s*(?P<rest>[^\n]*)$", re.I | re.M)
_FIELD_RX = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*|__)?\s*(?P<name>verdict|why|reason|expansion\s*#?\s*\d*"
    r"|option\s*#?\s*\d*|version\s*#?\s*\d*)\s*(?:\((?P<angle>[^)\n]{0,60})\))?\s*(?:\*\*|__)?"
    r"\s*[:.\-–—]\s*(?:\*\*|__)?\s*(?P<rest>[^\n]*)$", re.I | re.M)


@dataclass
class Judgement:
    number: Optional[int]           # sentence number, None for "[+]"
    quote: str
    verdict: str                    # over | fine
    why: str = ""
    expansions: List[Expansion] = field(default_factory=list)


def _unquote(text: str) -> str:
    text = " ".join((text or "").split()).strip().strip("*_").strip()
    if len(text) > 1 and text[0] in "\"“'" and text[-1] in "\"”'":
        inner = text[1:-1]
        if inner.count('"') % 2 == 0:
            text = inner.strip()
    return text


def parse_judgements(raw: str) -> List[Judgement]:
    from src.ai.output_sanitizer import strip_meta_tokens, strip_passage_markers
    text = strip_passage_markers(strip_meta_tokens(raw or ""))
    heads = list(_STATEMENT_RX.finditer(text))
    out = []
    for i, m in enumerate(heads):
        block = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        num = m.group(1) or ""
        number = int(num) if num.isdigit() else None
        quote = _unquote(m.group("rest"))
        fields = list(_FIELD_RX.finditer(block))
        verdict, why, expansions = "", "", []
        for j, f in enumerate(fields):
            body = (f.group("rest") + block[f.end():fields[j + 1].start()
                                              if j + 1 < len(fields) else len(block)])
            name = f.group("name").lower()
            if name.startswith("verdict"):
                low = body.lower()
                fine = ("not overly" in low or "isn't overly" in low
                        or (re.search(r"\b(?:fine|works|keep|ok|okay|no)\b", low)
                            and "overly descriptive" not in low))
                verdict = "fine" if fine else "over"
            elif name.startswith(("why", "reason")):
                why = " ".join(body.split()).strip("*_ ")
            else:
                rewrite = _unquote(body)
                if rewrite and rewrite.lower() not in ("none", "n/a"):
                    expansions.append(Expansion(rewrite, (f.group("angle") or "").strip().lower()))
        if not verdict:
            verdict = "over" if expansions else ""
        if verdict:
            out.append(Judgement(number, quote, verdict, why, expansions))
    return out


def _locate(j: Judgement, sentences: Sequence[str]) -> Optional[int]:
    """0-based index of the sentence a judgement is about."""
    from src.ai.rewrite_quality import similarity
    quote = " ".join(j.quote.split()).lower()
    norm = [" ".join(s.split()).lower() for s in sentences]
    if j.number is not None and 1 <= j.number <= len(sentences):
        n = j.number - 1
        if not quote or quote[:25] in norm[n] or norm[n][:25] in quote \
                or similarity(quote, norm[n]) >= 0.5:
            return n
    if quote:
        for i, s in enumerate(norm):
            if quote in s or (len(s) > 20 and s in quote):
                return i
        best = max(range(len(sentences)), key=lambda i: similarity(quote, norm[i]), default=None)
        if best is not None and similarity(quote, norm[best]) >= 0.6:
            return best
    return None


def _merge(flags_by_index: Dict[int, Flag], judgements: Sequence[Judgement],
           spans: Sequence[Tuple[int, int]], text: str, offset: int = 0
           ) -> Tuple[List[Flag], List[Flag]]:
    """Apply the model's verdicts to the scan's flags (keyed by sentence
    index). Returns (flags to show, flags the model cleared)."""
    sentences = [text[s:e] for s, e in spans]
    cleared: Dict[int, Flag] = {}
    for j in judgements:
        i = _locate(j, sentences)
        if i is None:
            continue
        flag = flags_by_index.get(i)
        if j.verdict == "fine":
            if flag is not None:
                flag.verdict = "fine"
                cleared[i] = flags_by_index.pop(i)
            continue
        if flag is None:
            s, e = spans[i]
            sentence = sentences[i]
            cues = find_cues(sentence)
            flag = Flag(offset + s, offset + e, sentence, cues, _score(cues),
                        hints=hints_for(cues), expansions=_offline_expansions(sentence),
                        source="ai")
            flags_by_index[i] = flag
            cleared.pop(i, None)
        elif flag.source == "scan":
            flag.source = "both"
        flag.verdict = "over"
        if j.why:
            flag.reason = j.why
        ai = [x for x in j.expansions
              if " ".join(x.text.split()) != " ".join(flag.text.split())]
        if ai:
            flag.expansions = ai + [x for x in flag.expansions if not x.by_ai]
    shown = [flags_by_index[i] for i in sorted(flags_by_index)]
    return shown, [cleared[i] for i in sorted(cleared)]


def _check_expansions(flag: Flag, *, voice: Any, known_names: Sequence[str], before: str,
                      after: str, notes: str) -> None:
    """Run the rewrite checks on the AI expansions; drop failing ones
    when a passing one remains; best first."""
    from src.ai.rewrite_quality import best_first, check_rewrite
    ai = [x for x in flag.expansions if x.by_ai]
    if not ai:
        return
    checks = []
    for x in ai:
        c = check_rewrite(flag.text, x.text, voice=voice, known_names=known_names,
                          before=before, after=after, focus="expand", notes=notes)
        x.notes, x.voice_fit = c.notes, c.voice_fit
        checks.append(c)
    order = best_first(ai, checks)
    kept = [ai[i] for i in order if checks[i].ok] or [ai[i] for i in order]
    flag.expansions = kept + [x for x in flag.expansions if not x.by_ai]


def review_passage(llm: Any, ctx: Any, voice: Any = None, *,
                   progress: Optional[Callable[[str], None]] = None,
                   compact: Optional[bool] = None) -> Review:
    """Overly descriptive statements in ``ctx.passage`` (a
    ``passage_critique.PassageContext``), with expansions.

    ``llm`` is whatever model the calling tool resolved; ``None`` gives
    the scan alone. Offsets are into ``ctx.passage``.
    """
    say = progress or (lambda _m: None)
    passage = ctx.passage
    spans = sentence_spans(passage)
    scanned = scan(passage)
    if llm is None:
        return Review(scanned, error="no model")
    if compact is None:
        from src.ai.chapter_analysis_agent import is_local_llm
        compact = is_local_llm(llm)
    index_of_span = {span: i for i, span in enumerate(spans)}
    by_index = {index_of_span[(f.start, f.end)]: f for f in scanned
                if (f.start, f.end) in index_of_span}
    sentences = [passage[s:e] for s, e in spans]
    if not sentences:
        return Review(scanned, used_ai=False)
    flags = [by_index[i] for i in sorted(by_index)]
    numbers = {k: i + 1 for k, i in enumerate(sorted(by_index))}
    say("Looking for overly descriptive statements…")
    try:
        raw = llm.generate_text(build_passage_prompt(ctx, sentences, flags, numbers,
                                                     compact=compact),
                                SYSTEM_PROMPT, max_tokens=1400, temperature=0.7)
        judgements = parse_judgements(raw)
    except Exception as e:
        print(f"[overdescription] model review failed: {e}")
        return Review(scanned, error=str(e))
    if not judgements:
        return Review(scanned, error="the model's reply couldn't be read")
    shown, cleared = _merge(by_index, judgements, spans, passage)
    names = list(getattr(ctx, "known_names", []) or [])
    notes = ctx.notes_text() if hasattr(ctx, "notes_text") else ""
    for f in shown:
        _check_expansions(f, voice=voice, known_names=names,
                          before=getattr(ctx, "before", "") + passage[:f.start],
                          after=passage[f.end:] + getattr(ctx, "after", ""), notes=notes)
    return Review(shown, cleared, used_ai=True)


def expand_more(llm: Any, ctx: Any, flag: Flag, voice: Any = None, note: str = "") -> List[Expansion]:
    """More expansions for one statement (the writer can give direction)."""
    sentences = [flag.text]
    prompt = build_passage_prompt(ctx, sentences, [flag], {0: 1},
                                  compact=_is_local(llm))
    have = [x.text for x in flag.expansions if x.by_ai]
    if have:
        prompt += "\n\nAlready suggested (write different ones):\n" + "\n".join(
            f"- {t}" for t in have)
    if note.strip():
        prompt += f"\n\nThe author asks: {note.strip()}"
    raw = llm.generate_text(prompt, SYSTEM_PROMPT, max_tokens=700, temperature=0.85)
    found = [x for j in parse_judgements(raw) for x in j.expansions]
    tmp = Flag(flag.start, flag.end, flag.text, expansions=found)
    passage = getattr(ctx, "passage", "")
    _check_expansions(tmp, voice=voice, known_names=getattr(ctx, "known_names", []) or [],
                      before=getattr(ctx, "before", "") + passage[:flag.start],
                      after=passage[flag.end:] + getattr(ctx, "after", ""),
                      notes=ctx.notes_text() if hasattr(ctx, "notes_text") else "")
    return [x for x in tmp.expansions if x.text not in have]


def _is_local(llm: Any) -> bool:
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        return is_local_llm(llm)
    except Exception:
        return False


MAX_CHAPTER_CANDIDATES = 15


def review_chapter(text: str, llm: Any = None, voice: Any = None, *,
                   compact: Optional[bool] = None, limit: int = 25) -> Review:
    """Overly descriptive statements across a chapter, strongest first.

    The model (when given) judges the scan's strongest candidates and,
    for cloud models, adds statements without cue words. Expansions are
    written later, per statement, when the writer opens one.
    """
    spans = sentence_spans(text)
    scanned = scan(text)
    if llm is None:
        return Review(_strongest(scanned, limit), error="no model")
    if compact is None:
        compact = _is_local(llm)
    index_of_span = {span: i for i, span in enumerate(spans)}
    by_index = {index_of_span[(f.start, f.end)]: f for f in scanned
                if (f.start, f.end) in index_of_span}
    top = sorted(by_index, key=lambda i: -by_index[i].score)[:MAX_CHAPTER_CANDIDATES]
    judged = {i: by_index[i] for i in top}
    sentences = [text[s:e] for s, e in spans]
    voice_text = voice.to_critique_prompt() if voice is not None and hasattr(
        voice, "to_critique_prompt") else ""
    excerpt = "" if compact else text[:12000]
    if not judged and not excerpt:
        return Review([], used_ai=True)
    try:
        raw = llm.generate_text(build_chapter_prompt(sentences, [i + 1 for i in sorted(judged)],
                                                     voice_text, excerpt),
                                SYSTEM_PROMPT, max_tokens=1200, temperature=0.3)
        judgements = parse_judgements(raw)
    except Exception as e:
        print(f"[overdescription] chapter review failed: {e}")
        return Review(_strongest(scanned, limit), error=str(e))
    if not judgements:
        return Review(_strongest(scanned, limit), error="the model's reply couldn't be read")
    shown, cleared = _merge(judged, judgements, spans, text)
    rest = [f for i, f in by_index.items() if i not in set(top)]
    ordered = sorted(shown, key=lambda f: (f.verdict != "over", -f.score)) + _strongest(rest, limit)
    return Review(ordered[:limit], cleared, used_ai=True)


def _strongest(flags: Sequence[Flag], limit: int) -> List[Flag]:
    return sorted(flags, key=lambda f: -f.score)[:limit]


# ── Applying an accepted expansion ───────────────────────────────────

def apply_expansion(text: str, original: str, replacement: str, near: int = 0) -> Optional[str]:
    """``text`` with ``original`` (the occurrence nearest ``near``)
    replaced, or None when it's no longer there."""
    if not original:
        return None
    hits = [m.start() for m in re.finditer(re.escape(original), text)]
    if not hits:
        return None
    at = min(hits, key=lambda i: abs(i - near))
    return text[:at] + replacement + text[at + len(original):]
