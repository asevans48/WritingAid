"""Dialogue craft: how each character talks, what an exchange is about,
and the dialogue mistakes a scan can catch without a model.

Shared by Suggestions, Rephrase and the Critique tab's Dialog report:

* ``is_dialogue`` — is a passage mostly conversation (switches the tools
  to their dialogue checklist).
* ``SpeechProfile`` / ``speech_profiles`` — each character's speech,
  measured from the lines the manuscript gives them (length, contractions,
  questions, formality, favourite words) plus their profile's speaking
  style. ``line_fit`` says when a line sounds more like someone else.
* ``exchange_context`` — the speakers' relationship, shared tensions, what
  each wants and hides, and this chapter's beats: what subtext needs.
* ``dialogue_issues`` — tag habits, name-dropping, long speeches, lost
  speakers, "as you know" exposition, filler openers, heavy stage
  directions. ``rewrite_dialogue_problems`` reports the ones a rewrite
  introduces.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.ai.dialogue_speakers import Line, attribute_lines

_QUOTE_RX = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’]*")
_CONTRACTION_RX = re.compile(r"\b[A-Za-z]+(?:n['’]t|['’](?:s|re|ve|ll|d|m))\b", re.I)
_PROFANITY = {"damn", "damned", "hell", "bloody", "shit", "fuck", "fucking", "bastard",
              "bitch", "christ", "gods", "goddamn", "crap", "piss", "arse", "ass"}
_FORMAL = {"shall", "indeed", "perhaps", "certainly", "therefore", "however", "whom",
           "nevertheless", "regrettably", "kindly", "madam", "sir"}
_STOP = set("""the a an and or but of to in on at by for with from as is was were be been are it
its this that these those not no so than then into about over his her him she he they them their
there here had has have did does do would could should will just only very what when where which
who whom while all any each some you your yours me my mine we us our i i'm you're it's that's don't
can't won't didn't isn't aren't wasn't weren't get got go going come know like now one""".split())

# Neutral tags; anything else in a tag is a said-bookism.
NEUTRAL_TAGS = {"said", "says", "asked", "asks", "replied", "answered", "whispered",
                "called", "told", "added", "continued", "repeated", "went on"}
BOOKISMS = {
    "hissed", "growled", "snarled", "barked", "spat", "purred", "sneered", "chuckled",
    "chortled", "laughed", "smiled", "grinned", "smirked", "sighed", "breathed", "exclaimed",
    "ejaculated", "interjected", "retorted", "quipped", "intoned", "declared", "proclaimed",
    "opined", "mused", "queried", "inquired", "enquired", "remarked", "stated", "uttered",
    "snapped", "shot back", "roared", "bellowed", "squealed", "gasped", "groaned", "moaned",
    "huffed", "scoffed", "snorted", "giggled", "cooed", "simpered", "wheezed", "rasped",
}
_TAG_VERB_RX = re.compile(
    r'^\s*,?\s*(?:(?:he|she|they|I|we|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?P<v1>[a-z]+(?:\s+back)?)'
    r'|(?P<v2>[a-z]+)\s+(?:he|she|they|I|we|[A-Z][a-z]+))(?:\s+(?P<adv>[a-z]+ly))?\b')
_EXPOSITION_RX = re.compile(
    r"\b(?:as you (?:well )?know|as you(?:'re| are) (?:well )?aware|you remember (?:when|how|that)"
    r"|need i remind you|like i (?:told|said)(?: you)? before|as i(?:'ve| have) (?:said|told you)"
    r"|don't you remember|as we both know)\b", re.I)
_FILLER_RX = re.compile(r"^\s*(?:well|oh|so|um+|uh+|look|listen|okay|ok|hey|ah)\b[,.!]", re.I)


def _words(text: str) -> List[str]:
    return [w.lower().replace("’", "'") for w in _WORD_RX.findall(text or "")]


def _quotes(text: str) -> List[str]:
    return [m.group(1) or m.group(2) for m in _QUOTE_RX.finditer(text or "")]


def dialogue_share(text: str) -> float:
    """Share of the passage's words that are inside quotation marks."""
    total = len(_words(text))
    return sum(len(_words(q)) for q in _quotes(text)) / total if total else 0.0


def is_dialogue(text: str) -> bool:
    """Mostly conversation: two or more lines, or a third of the words."""
    quotes = _quotes(text)
    return len(quotes) >= 2 or (len(quotes) == 1 and dialogue_share(text) >= 0.33)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── Speech profiles ──────────────────────────────────────────────────

@dataclass
class SpeechProfile:
    name: str
    lines: List[str] = field(default_factory=list)
    words_per_line: float = 0.0
    contractions_per_100: float = 0.0
    question_pct: float = 0.0
    exclaim_pct: float = 0.0
    formal_per_100: float = 0.0
    profanity_per_100: float = 0.0
    favourite_words: List[str] = field(default_factory=list)
    stated: str = ""            # speaking style / quirks from their profile
    never: List[str] = field(default_factory=list)   # words they never say

    @property
    def measured(self) -> bool:
        return len(self.lines) >= 5

    def to_prompt(self) -> str:
        parts = [f"{self.name}:"]
        if self.stated:
            parts.append(f"  Profile says: {self.stated}")
        if self.measured:
            habits = [f"lines average ~{self.words_per_line:.0f} words",
                      ("uses contractions freely" if self.contractions_per_100 >= 4 else
                       "rarely uses contractions" if self.contractions_per_100 < 1 else
                       "some contractions"),
                      f"{self.question_pct:.0f}% questions"]
            if self.formal_per_100 >= 1:
                habits.append("formal register")
            if self.profanity_per_100 >= 0.5:
                habits.append("swears")
            if self.favourite_words:
                habits.append("favourite words: " + ", ".join(self.favourite_words[:6]))
            parts.append(f"  In the manuscript ({len(self.lines)} lines): " + "; ".join(habits))
        if self.lines:
            parts.append("  Sounds like: " + " / ".join(f"“{_short(l, 70)}”"
                                                      for l in self.lines[-3:]))
        return "\n".join(parts) if len(parts) > 1 else ""

    def features(self) -> Tuple[float, float, float, float]:
        return (min(self.words_per_line, 40) / 40, min(self.contractions_per_100, 10) / 10,
                self.question_pct / 100, min(self.formal_per_100, 5) / 5)


def _measure(name: str, lines: Sequence[str], stated: str = "") -> SpeechProfile:
    p = SpeechProfile(name=name, lines=list(lines), stated=stated)
    words = [w for l in lines for w in _words(l)]
    if lines and words:
        n = len(words)
        p.words_per_line = n / len(lines)
        p.contractions_per_100 = 100 * sum(len(_CONTRACTION_RX.findall(l)) for l in lines) / n
        p.question_pct = 100 * sum("?" in l for l in lines) / len(lines)
        p.exclaim_pct = 100 * sum("!" in l for l in lines) / len(lines)
        p.formal_per_100 = 100 * sum(w in _FORMAL for w in words) / n
        p.profanity_per_100 = 100 * sum(w in _PROFANITY for w in words) / n
    return p


_NEVER_RX = re.compile(r"\bnever\s+(?:says|uses|said|swears|curses)\s+[\"“']?([A-Za-z' ]{2,20}?)"
                       r"[\"”']?(?=[\s.,;]|$)", re.I)


def never_says(character: Any) -> List[str]:
    """Words the profile says this character never uses ("never says please")."""
    text = " ".join((getattr(character, a, "") or "") for a in ("speaking_style", "quirks",
                                                                 "personality", "notes"))
    out = []
    for m in _NEVER_RX.finditer(text):
        word = m.group(1).strip().lower()
        if word and word not in ("a", "the", "anything", "much", "more"):
            out.append(word)
    return out


def _stated_style(character: Any) -> str:
    bits = []
    for attr in ("speaking_style", "quirks"):
        v = (getattr(character, attr, "") or "").strip()
        if v:
            bits.append(v[:200])
    return "; ".join(bits)


_LINES_CACHE: "Dict[Tuple[int, Tuple[str, ...]], Dict[str, List[str]]]" = {}


def lines_by_speaker(text: str, names: Iterable[str]) -> Dict[str, List[str]]:
    """Speaker → their lines in ``text`` (cached per text: a manuscript
    critique asks for every chapter many times)."""
    key = (hash(text or ""), tuple(names))
    cached = _LINES_CACHE.get(key)
    if cached is not None:
        return cached
    out: Dict[str, List[str]] = {}
    for line in attribute_lines(text, key[1]):
        if line.speaker and line.certainty in ("tag", "beat", "likely"):
            out.setdefault(line.speaker, []).append(line.quote)
    if len(_LINES_CACHE) > 512:
        _LINES_CACHE.clear()
    _LINES_CACHE[key] = out
    return out


def _chapter_texts(project: Any) -> List[str]:
    try:
        return [ch.content or "" for _, ch in project.all_chapters()]
    except Exception:
        return [ch.content or "" for ch in getattr(getattr(project, "manuscript", None),
                                                    "chapters", None) or []]


def speech_profiles(project: Any, text: str = "", only: Optional[Iterable[str]] = None,
                    texts: Optional[Sequence[str]] = None) -> Dict[str, SpeechProfile]:
    """Speech profiles from ``text``, or ``texts`` (one per chapter), or by
    default every chapter of the project."""
    characters = list(getattr(project, "characters", None) or []) if project is not None else []
    names = [c.name for c in characters if getattr(c, "name", "")]
    if text:
        texts = [text]
    elif texts is None:
        texts = _chapter_texts(project) if project is not None else []
    by_speaker: Dict[str, List[str]] = {}
    for t in texts:
        if not t.strip():
            continue
        for who, said in lines_by_speaker(t, names).items():
            by_speaker.setdefault(who, []).extend(said)
    # Favourite words: frequent for this speaker, rare for the others.
    counts = {n: Counter(w for l in ls for w in _words(l) if w not in _STOP and len(w) > 2)
              for n, ls in by_speaker.items()}
    wanted = set(only) if only is not None else None
    out: Dict[str, SpeechProfile] = {}
    for c in characters:
        if wanted is not None and c.name not in wanted:
            continue
        p = _measure(c.name, by_speaker.get(c.name, []), _stated_style(c))
        p.never = never_says(c)
        mine = counts.get(c.name, Counter())
        others = Counter()
        for n, cnt in counts.items():
            if n != c.name:
                others.update(cnt)
        p.favourite_words = [w for w, k in mine.most_common(30)
                             if k >= 2 and k > 2 * others.get(w, 0)][:8]
        if p.lines or p.stated:
            out[c.name] = p
    return out


def line_fit(line: str, speaker: str, profiles: Dict[str, SpeechProfile]) -> str:
    """A note when ``line`` reads unlike ``speaker`` and more like someone
    else measured in the book; "" when it fits or we can't tell."""
    mine = profiles.get(speaker)
    if mine is None or not mine.measured or len(_words(line)) < 4:
        return ""
    probe = _measure(speaker, [line]).features()

    def distance(p: SpeechProfile) -> float:
        return sum((a - b) ** 2 for a, b in zip(probe, p.features())) ** 0.5

    others = [p for n, p in profiles.items() if n != speaker and p.measured]
    if not others:
        return ""
    nearest = min(others, key=distance)
    if distance(nearest) + 0.15 < distance(mine):
        return f"{speaker}'s line “{_short(line, 50)}” sounds more like {nearest.name}"
    return ""


# ── The exchange ─────────────────────────────────────────────────────

def exchange_context(project: Any, chapter: Any, speakers: Sequence[str]) -> str:
    """Relationships, tensions, wants and secrets of the people talking, and
    what this chapter needs to happen: the material for subtext."""
    if project is None or not speakers:
        return ""
    by_name = {c.name: c for c in getattr(project, "characters", None) or []}
    people = [by_name[s] for s in speakers if s in by_name]
    lines = []
    for c in people:
        bits = []
        for attr, label in (("want", "wants"), ("need", "needs"), ("secret", "hides"),
                            ("fears", "fears"), ("defining_relationship", "bond")):
            v = (getattr(c, attr, "") or "").strip()
            if v:
                bits.append(f"{label}: {v[:160]}")
        for other in people:
            if other is c:
                continue
            rel = (getattr(c, "social_network", None) or {}).get(other.name) \
                or (getattr(c, "social_network", None) or {}).get(other.id)
            if rel:
                bits.append(f"to {other.name}: {str(rel)[:120]}")
        if bits:
            lines.append(f"- {c.name} — " + "; ".join(bits))
    planning = getattr(project, "story_planning", None)
    names = {c.name.lower() for c in people} | {c.name.split()[0].lower() for c in people}
    for t in getattr(planning, "tensions", None) or []:
        involved = {n.lower() for n in getattr(t, "characters_involved", None) or []}
        if len(involved & names) >= min(2, len(names)) and t.current_state != "resolved":
            lines.append(f"- Tension “{t.title}” ({t.current_state}): "
                         f"{(t.description or t.stakes or '')[:180]}")
    plan = getattr(chapter, "planning", None)
    if plan is not None:
        beats = [e.text for e in getattr(plan, "events", None) or []
                 if getattr(e, "text", "") and not getattr(e, "completed", False)]
        if beats:
            lines.append("- This chapter still has to: " + "; ".join(beats[:5]))
    return "\n".join(lines)


# ── Deterministic dialogue checks ────────────────────────────────────

@dataclass
class DialogueIssue:
    kind: str          # bookism | tag_adverb | names | long_turn | lost_speaker |
                       # exposition | filler | stage_directions
    message: str
    excerpt: str = ""
    start: int = -1    # offset into the text, when known

    def __str__(self) -> str:
        return self.message


def _tags(text: str) -> List[Tuple[str, str, str, int]]:
    """(quote, tag verb, adverb, offset) for each tagged line."""
    out = []
    for m in _QUOTE_RX.finditer(text or ""):
        t = _TAG_VERB_RX.match(text[m.end():m.end() + 50])
        if t:
            verb = (t.group("v1") or t.group("v2") or "").lower()
            out.append((m.group(1) or m.group(2), verb, (t.group("adv") or "").lower(), m.start()))
    return out


def dialogue_issues(text: str, names: Iterable[str] = (), *,
                    lines: Optional[List[Line]] = None,
                    profiles: Optional[Dict[str, "SpeechProfile"]] = None) -> List[DialogueIssue]:
    """Dialogue problems a scan can be sure of."""
    names = list(names)
    lines = lines if lines is not None else attribute_lines(text, names)
    out: List[DialogueIssue] = []
    if not lines:
        return out

    for l in lines:
        profile = (profiles or {}).get(l.speaker)
        for word in (profile.never if profile else []):
            if re.search(rf"\b{re.escape(word)}\b", l.quote, re.I):
                out.append(DialogueIssue(
                    "out_of_character", f"{l.speaker} says “{word}” (“{_short(l.quote, 40)}”), "
                    f"which their profile says they never do.", l.quote, l.start))

    for quote, verb, adverb, at in _tags(text):
        if verb in BOOKISMS:
            out.append(DialogueIssue("bookism", f"Said-bookism “{verb}” on “{_short(quote, 40)}” "
                                     f"— “said” disappears; let the line carry the tone.",
                                     quote, at))
        if adverb and adverb not in ("only", "early", "family") and (
                verb in NEUTRAL_TAGS or verb in BOOKISMS):
            out.append(DialogueIssue("tag_adverb", f"Tag adverb “{verb} {adverb}” on "
                                     f"“{_short(quote, 40)}” — the line should show it.",
                                     quote, at))

    named = [l for l in lines if l.addressed]
    if len(named) >= 2 and len(named) * 3 >= len(lines):
        out.append(DialogueIssue(
            "names", f"Characters address each other by name in {len(named)} of {len(lines)} "
            f"lines (“{_short(named[0].quote, 40)}”) — people rarely do; keep it for emphasis.",
            named[0].quote, named[0].start))

    turns: Dict[Tuple[int, str], List[Line]] = {}
    for l in lines:
        turns.setdefault((l.paragraph, l.speaker), []).append(l)
    for (_p, who), said in turns.items():
        n = sum(len(_words(l.quote)) for l in said)
        if n > 70:
            out.append(DialogueIssue(
                "long_turn", f"{who or 'One speaker'} talks for {n} words without a break "
                f"(“{_short(said[0].quote, 40)}”) — interrupt it with a beat or a reply.",
                said[0].quote, said[0].start))

    run: List[Line] = []
    for l in lines + [Line("", speaker="x", certainty="tag")]:
        if not l.speaker:
            run.append(l)
            continue
        if len(run) >= 3:
            out.append(DialogueIssue(
                "lost_speaker", f"{len(run)} lines in a row with no clear speaker, starting "
                f"“{_short(run[0].quote, 40)}” — add a tag or beat so readers don't lose track.",
                run[0].quote, run[0].start))
        run = []

    for l in lines:
        m = _EXPOSITION_RX.search(l.quote)
        if m:
            out.append(DialogueIssue(
                "exposition", f"“{m.group(0)}” — characters telling each other what both "
                f"already know (“{_short(l.quote, 40)}”) is exposition in disguise.",
                l.quote, l.start))

    fillers = [l for l in lines if _FILLER_RX.match(l.quote)]
    if len(fillers) >= 2:
        out.append(DialogueIssue(
            "filler", f"{len(fillers)} lines open with filler (“{_short(fillers[0].quote, 30)}”) "
            f"— cut “Well,” / “Oh,” / “Look,” unless it characterises the speaker.",
            fillers[0].quote, fillers[0].start))

    paragraphs = (text or "").split("\n")
    for p_index in sorted({l.paragraph for l in lines}):
        para = paragraphs[p_index] if 0 <= p_index < len(paragraphs) else ""
        prose = _QUOTE_RX.sub(" ", para)
        actions = [s for s in re.split(r"(?<=[.!?…])\s+", prose) if len(_words(s)) >= 3]
        if len(actions) >= 4:
            out.append(DialogueIssue(
                "stage_directions", f"Heavy stage directions around “{_short(_quotes(para)[0], 40)}” "
                f"({len(actions)} action sentences) — keep the beats that reveal something.",
                _quotes(para)[0], text.find(para)))
    return out


def rewrite_dialogue_problems(original: str, candidate: str, names: Iterable[str],
                              profiles: Optional[Dict[str, SpeechProfile]] = None,
                              ) -> Tuple[List[str], List[str]]:
    """(serious, minor) dialogue problems in ``candidate``: a said-bookism,
    tag adverb, name-dropping or "as you know" exposition is serious — a
    rewrite should fix these, not add or keep them; a line that sounds like
    another character is minor."""
    names = list(names)
    if not _quotes(candidate):
        return [], []
    before = Counter(i.kind for i in dialogue_issues(original, names, profiles=profiles))
    after = dialogue_issues(candidate, names, profiles=profiles)
    serious = []
    labels = {"bookism": "a said-bookism", "tag_adverb": "a tag adverb",
              "names": "characters calling each other by name",
              "exposition": "“as you know” exposition",
              "out_of_character": "a word the speaker's profile says they never use"}
    for kind, label in labels.items():
        found = [i for i in after if i.kind == kind]
        if found:
            verb = "keeps" if before.get(kind) else "adds"
            serious.append(f"{verb} {label} ({_short(found[-1].excerpt, 40)})")
    if any(i.kind == "lost_speaker" for i in after) and not before.get("lost_speaker"):
        serious.append("leaves readers unsure who is speaking")

    def speech_paragraphs(text: str) -> int:
        return sum(1 for para in text.split("\n") if _QUOTE_RX.search(para))
    if speech_paragraphs(original) >= 2 and speech_paragraphs(candidate) == 1 \
            and len(_quotes(candidate)) >= 2:
        serious.append("runs several speakers' lines together in one paragraph")
    minor = []
    if profiles:
        for line in attribute_lines(candidate, names):
            if line.speaker:
                note = line_fit(line.quote, line.speaker, profiles)
                if note:
                    minor.append(note)
    return serious, minor[:2]


# ── Prompt pieces ────────────────────────────────────────────────────

DIALOGUE_CHECKLIST = (
    "This passage is mostly dialogue. Judge it as dialogue:\n"
    "- VOICE: does each speaker sound like themselves (their profile and how they talk in "
    "the manuscript, below) and unlike each other?\n"
    "- SUBTEXT: do they say exactly what they feel, or is something held back, deflected "
    "or implied, given what each wants and hides?\n"
    "- EXPOSITION: are characters telling each other things both already know?\n"
    "- TAGS AND BEATS: prefer \"said\" (or no tag) and beats that show something; no "
    "said-bookisms or tag adverbs; readers must always know who is speaking.\n"
    "- PURPOSE: does each line move the scene, reveal character or raise tension — "
    "or could it go?\n"
    "- RHYTHM: real speech is clipped and interrupted; avoid speeches, filler openers "
    "(\"Well,\" \"Oh,\") and characters addressing each other by name.\n"
    "The author's voice rules apply to narration. Inside the quotes each character speaks "
    "in their OWN voice from their profile and lines: a rambler still rambles, a terse "
    "character stays terse. Keep one speaker per paragraph and make it clear who is "
    "speaking.")


def speakers_in(text: str, names: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for l in attribute_lines(text, names):
        for who in (l.speaker, l.addressed):
            if who and who not in seen:
                seen.append(who)
    return seen


# ── Keeping paragraphs (and speakers) apart ──────────────────────────

def normalize_breaks(text: str) -> str:
    """Qt's selectedText() marks paragraph breaks with U+2029 (and soft line
    breaks with U+2028); everything downstream expects \\n."""
    return (text or "").replace("\r\n", "\n").replace("\u2029", "\n").replace("\u2028", "\n")


def paragraph_separator(*samples: str) -> str:
    """The separator the manuscript uses between paragraphs. Chapters are
    Markdown, where a single newline does NOT start a new paragraph."""
    samples = [normalize_breaks(s) for s in samples if s]
    if any("\n\n" in s for s in samples):
        return "\n\n"
    if any("\n" in s.strip() for s in samples):
        return "\n"
    return "\n\n"


def separate_speakers(paragraph: str, names: Iterable[str]) -> List[str]:
    """Split a paragraph wherever the speaker changes (one speaker per
    paragraph). A beat naming the new speaker goes with their line."""
    names = list(names)
    lines = attribute_lines(paragraph, names)
    cuts = []
    for a, b in zip(lines, lines[1:]):
        if not (a.speaker and b.speaker and a.speaker != b.speaker
                and b.certainty in ("tag", "beat")):
            continue
        cut = b.start
        prefix = paragraph[:cut]
        bounds = [m.end() for m in re.finditer(r"[.!?…][\"”’']?\s+", prefix)]
        # The beat is the last sentence before the quote: '…said. Tobin
        # missed a stroke. "Why not?"'
        starts = [x for x in bounds if x > a.start]
        if prefix[starts[-1]:].strip() == "" if starts else False:
            starts = starts[:-1]
        if starts:
            beat = prefix[starts[-1]:].strip()
            first = beat.split()[0].strip(",.") if beat else ""
            if first and first in b.speaker.split():
                cut = starts[-1]
        if cut > (cuts[-1] if cuts else 0):
            cuts.append(cut)
    pieces, last = [], 0
    for cut in cuts:
        pieces.append(paragraph[last:cut].strip())
        last = cut
    pieces.append(paragraph[last:].strip())
    return [p for p in pieces if p]


def tidy_paragraphs(original: str, rewrite: str, names: Iterable[str] = (),
                    sep: Optional[str] = None) -> str:
    """Give a rewrite the original's paragraphing: the manuscript's
    separator between paragraphs and one speaker per paragraph. A
    one-paragraph prose original stays one paragraph (the model wrapped)."""
    from src.ai.output_sanitizer import extract_marked_passage
    original = normalize_breaks(original).strip()
    text = extract_marked_passage(normalize_breaks(rewrite)).strip()
    if not text:
        return text
    sep = sep or paragraph_separator(original)
    lines = [l.strip() for l in text.split("\n")]
    if "\n" not in original and not _quotes(text):
        return " ".join(l for l in lines if l)
    paragraphs = [l for l in lines if l]
    out: List[str] = []
    for para in paragraphs:
        out += separate_speakers(para, names) if names else [para]
    return sep.join(out)
