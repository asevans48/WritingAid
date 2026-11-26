"""More style checks (piece P.2b): homonyms, sensory detail, sentence
structure and vague words.

Like P.2a's (``style_reports``), each is a kind in ``style_checks.KINDS``,
so it shows in the editor's highlights, ✓ Checks ▾ ▸ Style checks (with its
count), the Companion's list of style issues and the next-fix queue. All
four are **off until the writer ticks them** (``MORE_KINDS`` is left out of
``style_checks.DEFAULT_KINDS``). Plain word scans, no model.

  homonym             — a sound-alike where the sentence wants its twin
                        ("sneak peak", "free reign"); see ``homonyms``
  sensory             — a long stretch of narration with nothing to see,
                        hear, smell, taste or touch (telling, not showing;
                        the overly descriptive check is its opposite).
                        ``sense_balance(text)`` gives the chapter's mix of
                        senses for the Style checks summary.
  sentence_structure  — sentences built the same way, beyond repeated
                        first words: four or more of about the same length
                        in a row, or three in a row that open the same way
                        (with an -ing phrase, a "when/as" clause, a
                        preposition or an -ly word)
  vague               — diction: vague and abstract words in narration
                        ("stuff", "kind of", "or something", "aspect")

Only homonyms carry a suggestion (the twin), and "Fix all" is never offered
for them (decision 9, ``fix_all.is_confusable``). The other three are for
the writer to judge.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

MORE_KINDS = ("homonym", "sensory", "sentence_structure", "vague")


def _quoted(text: str, pos: int) -> bool:
    from src.utils.style_reports import _in_dialogue
    return _in_dialogue(text, pos)


def _narration(text: str) -> str:
    """``text`` with quoted speech blanked out (same length, so offsets hold)."""
    out, inside, curly = [], False, ("“" in text or "”" in text)
    for ch in text:
        if curly and ch in "“”":
            inside = ch == "“"
            out.append(" ")
        elif not curly and ch == '"':
            inside = not inside
            out.append(" ")
        else:
            out.append(" " if inside and ch != "\n" else ch)
    return "".join(out)


# ── Sensory detail ──────────────────────────────────────────────────────

SENSES: Dict[str, frozenset] = {
    "sight": frozenset("""
see saw seen sees seeing look looked looking looks watch watched watching glance glanced
stare stared staring gaze gazed gazing glimpse glimpsed peer peered peering squint squinted
blink blinked red blue green yellow orange purple pink brown grey gray black white golden
silver scarlet crimson pale dark darkness darkened bright brightly brightness light lit
shadow shadows shadowed shade glow glowed glowing glint glinted gleam gleamed gleaming
glitter glittered shimmer shimmered sparkle sparkled flash flashed flicker flickered
flickering dim dimly shone shine shining shiny sunlight moonlight lamplight candlelight
firelight starlight colour colours color colors blur blurred silhouette glare glared
""".split()),
    "sound": frozenset("""
hear heard hears hearing listen listened listening sound sounds sounded noise noises noisy
voice voices whisper whispered whispering murmur murmured hum hummed humming buzz buzzed
buzzing ring rang ringing roar roared roaring crash crashed bang banged thud thudded creak
creaked creaking rustle rustled rustling hiss hissed click clicked silence silent quiet
quietly loud loudly echo echoed echoing shout shouted shouting scream screamed screaming
yell yelled sang sing singing song songs music knock knocked knocking rattle rattled
clatter clattered chime chimed bell bells howl howled bark barked whine whined purr purred
tick ticked ticking drip dripped splash splashed snap snapped thunder rumble rumbled groan
groaned squeak squeaked shriek shrieked thump thumped clang clanged jingle jingled crunch
crunched footsteps hush hushed muffled deafening sob sobbed laugh laughed laughter
""".split()),
    "smell": frozenset("""
smell smelled smelt smells smelling scent scented odour odor odours odors stink stank
stench reek reeked reeking whiff fragrance fragrant perfume perfumed aroma musty sniff
sniffed acrid pungent musk rancid
""".split()),
    "taste": frozenset("""
taste tasted tastes tasting flavour flavor flavours flavors sweet sweetness sour bitter
salty salt savoury savory bland tongue sip sipped swallow swallowed chew chewed spicy
tangy delicious mouthful sugary
""".split()),
    "touch": frozenset("""
touch touched touching warm warmth cold coldness cool hot heat rough smooth soft softly
wet damp sticky prickly prickle itch itched sting stung ache ached aching texture grip
gripped brushed stroked pressed slick silky gritty numb shiver shivered shivering chill
chilled freezing icy breeze tingle tingled clammy sweat sweaty soaked velvet coarse tickle
pinch squeeze squeezed caress caressed
""".split()),
}
_SENSE_OF = {w: s for s, words in SENSES.items() for w in words}
SENSE_ORDER = ("sight", "sound", "touch", "smell", "taste")
SENSORY_MIN_WORDS = 90         # narration this long with no sense at all is flagged
SENSORY_MIN_SENTENCES = 4


def senses_in(text: str) -> Dict[str, int]:
    """How many sense words of each kind ``text`` uses (dialogue included)."""
    from src.utils.style_checks import _WORD_RX
    out = {s: 0 for s in SENSE_ORDER}
    for w in _WORD_RX.findall(text or ""):
        s = _SENSE_OF.get(w.lower())
        if s:
            out[s] += 1
    return out


def sense_balance(text: str) -> str:
    """The chapter's mix of senses, for the Style checks summary:
    "sight 62%, sound 21%, touch 12%, smell 3%, taste 2%" ("" with none)."""
    counts = senses_in(text)
    total = sum(counts.values())
    if not total:
        return ""
    return ", ".join(f"{s} {round(100 * counts[s] / total)}%" for s in SENSE_ORDER)


def _sensory(text: str, sentences, add) -> None:
    from src.utils.style_checks import StyleIssue, _WORD_RX
    narration = _narration(text)
    words = _WORD_RX.findall(narration)
    if len(words) < SENSORY_MIN_WORDS or len(sentences) < SENSORY_MIN_SENTENCES:
        return
    if len(words) < 0.6 * len(_WORD_RX.findall(text)):
        return                                    # mostly dialogue
    if any(_SENSE_OF.get(w.lower()) for w in _WORD_RX.findall(text)):
        return
    start, end = sentences[0][0], sentences[-1][1]
    add(StyleIssue("sensory", start, end, text[start:end],
                   f"No sensory detail in {len(sentences)} sentences — nothing to see, hear, "
                   f"smell, taste or touch. Fine for a summary; in a scene, one concrete "
                   f"detail lets the reader be there.", sentence_level=True))


# ── Sentence structure ──────────────────────────────────────────────────

SAME_LENGTH_RUN = 4            # sentences in a row of about the same length
SAME_LENGTH_SPREAD = 2         # "about the same": within this many words
SAME_LENGTH_MIN, SAME_LENGTH_MAX = 6, 20
SAME_OPENING_RUN = 3           # sentences in a row that open the same way

_SUBORDINATE = frozenset("as when while after before because if although though since once "
                         "until whenever wherever unless".split())
_PREPOSITIONS = frozenset("in on at with by from under over through into across behind beneath "
                          "beside during without inside outside above below along around near "
                          "against among toward towards beyond within upon".split())
_NOT_PARTICIPLES = frozenset("nothing something anything everything morning evening king thing "
                             "things ring spring string wing sing bring during ceiling darling "
                             "being".split())
_OPENING_NAMES = {"ing": "an -ing phrase", "clause": "a “when / as …” clause",
                  "prep": "a preposition", "ly": "an -ly word"}


def opening_kind(sentence: str) -> str:
    """How a sentence opens: "ing" ("Turning, she …"), "clause" ("When he
    …"), "prep" ("In the hall …"), "ly" ("Slowly, …") or "" (anything else,
    most often the subject)."""
    from src.utils.style_checks import LY_NOT_ADVERBS, _WORD_RX
    words = _WORD_RX.findall(sentence)
    if not words:
        return ""
    first = words[0].lower()
    head = sentence[:80]
    if first.endswith("ing") and len(first) > 4 and first not in _NOT_PARTICIPLES \
            and "," in head and len(_WORD_RX.findall(head.split(",")[0])) <= 7:
        return "ing"
    if first in _SUBORDINATE and "," in sentence:
        return "clause"
    if first in _PREPOSITIONS and "," in head:
        return "prep"
    if first.endswith("ly") and len(first) > 4 and first not in LY_NOT_ADVERBS:
        return "ly"
    return ""


def _structure(text: str, sentences, kinds, add) -> None:
    from src.utils.style_checks import StyleIssue, _WORD_RX
    spoken = [_quoted(text, s) or sent[:1] in "\"“" for s, _e, sent in sentences]
    # (a) a run of sentences of about the same length
    lengths = [len(_WORD_RX.findall(sent)) for _s, _e, sent in sentences]

    def even(idx: List[int]) -> bool:
        ns = [lengths[j] for j in idx]
        return max(ns) - min(ns) <= SAME_LENGTH_SPREAD

    def flush_length(idx: List[int]) -> bool:
        if len(idx) < SAME_LENGTH_RUN:
            return False
        a, b = sentences[idx[0]][0], sentences[idx[-1]][1]
        ns = [lengths[j] for j in idx]
        add(StyleIssue("sentence_structure", a, b, text[a:b],
                       f"{len(idx)} sentences in a row of about the same length "
                       f"({min(ns)}–{max(ns)} words) — a short one or a long one would "
                       f"break the rhythm.", sentence_level=True))
        return True

    run: List[int] = []
    for i in range(len(sentences)):
        if spoken[i] or not SAME_LENGTH_MIN <= lengths[i] <= SAME_LENGTH_MAX:
            flush_length(run)
            run = []
        elif even(run + [i]):
            run.append(i)
        else:
            new = [i]
            if not flush_length(run):            # keep the tail that still fits
                for j in reversed(run):
                    if not even([j] + new):
                        break
                    new.insert(0, j)
            run = new
    flush_length(run)

    # (b) a run of sentences that open the same (non-subject) way
    run, kind = [], ""
    for i, (_s, _e, sent) in enumerate(sentences + [(0, 0, "")]):
        k = "" if i >= len(sentences) or spoken[i] else opening_kind(sent)
        if k and k == kind:
            run.append(i)
            continue
        if len(run) >= SAME_OPENING_RUN:
            firsts = {_WORD_RX.findall(sentences[j][2])[0].lower() for j in run}
            if not ("repeated_start" in kinds and len(firsts) == 1):
                a, b = sentences[run[0]][0], sentences[run[-1]][1]
                add(StyleIssue("sentence_structure", a, b, text[a:b],
                               f"{len(run)} sentences in a row open with {_OPENING_NAMES[kind]} "
                               f"— start one with its subject.", sentence_level=True))
        run, kind = ([i], k) if k else ([], "")


# ── Diction: vague words ────────────────────────────────────────────────

_HEDGE_BEFORE = frozenset("""was were is are 's 'm am be been being felt feel feels looked look
looks seemed seems sounded sound sounds i he she they we you it just only got get had have has
did do does still also then almost""".split())
VAGUE_PATTERNS: List[Tuple[str, str]] = [
    (r"\b(?:the|some|this|that|all|other|such|of|and|my|his|her|their|your|our|any|more|much|"
     r"old|weird|strange|same|good|bad|was|were|is|are|with) (?P<w>stuff)\b(?! (?:it|him|her|them|the|a|his|her)\b)",
     "“stuff” is vague — name the things."),
    (r"\b(?P<w>stuff) like that\b", "“stuff” is vague — name the things."),
    (r"\b(?P<w>(?:all (?:sorts|kinds|manner) of|lots of|a lot of|loads of|plenty of|various|"
     r"certain|a few|several|many) things)\b",
     "“things” is vague — which things? One specific one says more."),
    (r"\b(?P<w>(?:or|and) (?:something|whatever|stuff|things|so on|so forth)(?: like that)?)"
     r"(?=\s*[.,;!?—]|$)", "A vague tail — say what, or end the sentence before it."),
    (r"\b(?P<w>kind of|sort of|kinda|sorta)\b(?! (?:you|him|her|them|me|us|thing|things|"
     r"person|man|woman|place|way)\b)", "A hedge — commit to the word, or find the exact one."),
    (r"\b(?P<w>nice|amazing|awesome|interesting)\b",
     "“{w}” tells the reader to like it — show what makes it so."),
    (r"\b(?P<w>aspects?|factors?)\b", "“{w}” is abstract — name the thing itself."),
    (r"\b(?P<w>in a way|in some ways?|on some level|to some extent|to a certain extent)\b",
     "A hedge — say in what way, or cut it."),
]
_VAGUE_RX = [(re.compile(rx, re.I), msg) for rx, msg in VAGUE_PATTERNS]


def _vague(text: str, add) -> None:
    from src.utils.style_checks import StyleIssue
    narration = _narration(text)
    seen = set()
    for rx, msg in _VAGUE_RX:
        for m in rx.finditer(narration):
            s, e = m.span("w")
            if (s, e) in seen:
                continue
            word = text[s:e]
            low = word.lower()
            if low in ("kind of", "sort of", "kinda", "sorta"):
                before = re.findall(r"[A-Za-z']+", narration[max(0, s - 20):s])
                if not before or before[-1].lower() not in _HEDGE_BEFORE:
                    continue                      # "a kind of …", "what sort of …"
            if word[:1].isupper() and narration[:s].rstrip(" “\"")[-1:] not in ("", ".", "!", "?"):
                continue                          # a name ("Nice", "Kinda Road")
            seen.add((s, e))
            add(StyleIssue("vague", s, e, word, msg.replace("{w}", word)))


# ── Entry point (called by style_checks._analyze) ────────────────────────

def analyze(text: str, sentences, kinds, add, document: Optional[str] = None) -> None:
    if "homonym" in kinds:
        from src.utils import homonyms
        homonyms.analyze(text, add)
    if "sensory" in kinds:
        _sensory(text, sentences, add)
    if "sentence_structure" in kinds:
        _structure(text, sentences, kinds, add)
    if "vague" in kinds:
        _vague(text, add)
