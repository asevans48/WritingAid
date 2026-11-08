"""Canon index for critique reports.

Flattens the project's characters and worldbuilding into a searchable
list of named entities, finds which ones a chapter mentions, and spots
proper-noun phrases in the chapter that the project has no record of
(candidate *new* characters, places, factions, technologies…).

Pure Python and deterministic, so the Character and Worldbuilding
reports produce useful findings even in dashboard mode; the LLM then
judges alignment and classifies the new candidates.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Worldbuilding list fields → human category label.
_WORLD_CATEGORIES: Dict[str, str] = {
    "factions": "Faction",
    "myths": "Myth",
    "places": "Place",
    "climate_presets": "Climate",
    "technologies": "Technology",
    "flora": "Flora",
    "fauna": "Fauna",
    "stars": "Star",
    "star_systems": "Star system",
    "cultures": "Culture",
    "armies": "Army",
    "economies": "Economy",
    "historical_events": "Historical event",
    "hierarchies": "Power hierarchy",
    "political_systems": "Political system",
    "government_systems": "Government",
    "justice_systems": "Justice system",
    "service_systems": "Public service",
    "magic_systems": "Magic system",
}
_LEGACY_ELEMENT_FIELDS: Dict[str, str] = {
    "mythology_elements": "Mythology",
    "planets_elements": "Planet",
    "climate_elements": "Climate",
    "history_elements": "History",
    "politics_elements": "Politics",
    "military_elements": "Military",
    "economy_elements": "Economy",
    "power_hierarchy_elements": "Power hierarchy",
}
# Text fields worth surfacing in a canon summary, in priority order.
_SUMMARY_FIELDS = (
    "faction_type", "place_type", "technology_type", "description",
    "controlling_faction", "capital", "leader", "territory", "key_features", "summary", "purpose", "rules", "limitations", "cost",
    "beliefs", "values", "ideology", "goals", "leader", "leadership",
    "government", "capital", "climate", "atmosphere", "significance",
    "history", "notes",
)
_MAX_DEPTH = 3


@dataclass
class CanonEntity:
    name: str
    category: str
    summary: str = ""
    parent: str = ""            # e.g. the planet a city belongs to
    aliases: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        where = f" (in {self.parent})" if self.parent else ""
        return f"{self.category}: {self.name}{where}"


def _entity_name(obj: Any) -> str:
    for attr in ("name", "title"):
        v = getattr(obj, attr, None)
        if hasattr(v, "value") and isinstance(getattr(v, "value"), str):
            v = v.value  # str-Enum (e.g. FactionType.GUILD → "guild")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _summarize(obj: Any, max_chars: int = 350) -> str:
    bits = []
    for attr in _SUMMARY_FIELDS:
        v = getattr(obj, attr, None)
        if hasattr(v, "value") and isinstance(getattr(v, "value"), str):
            v = v.value  # str-Enum (e.g. FactionType.GUILD → "guild")
        if isinstance(v, str) and v.strip():
            label = "" if attr == "description" else f"{attr.replace('_', ' ')}: "
            bits.append(label + v.strip())
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            bits.append(f"{attr.replace('_', ' ')}: {', '.join(v[:6])}")
        if sum(len(b) for b in bits) > max_chars:
            break
    text = " | ".join(bits)
    return text[:max_chars].rstrip() + ("…" if len(text) > max_chars else "")


def _walk(obj: Any, category: str, parent: str, depth: int,
          out: List[CanonEntity]) -> None:
    """Record ``obj`` and any named sub-objects (cities on a planet,
    rituals in a culture, branches of an army…)."""
    name = _entity_name(obj)
    if name:
        out.append(CanonEntity(name=name, category=category,
                               summary=_summarize(obj), parent=parent))
    if depth >= _MAX_DEPTH:
        return
    fields = getattr(type(obj), "model_fields", None) or {}
    for fname in fields:
        val = getattr(obj, fname, None)
        if not isinstance(val, list) or not val:
            continue
        if not hasattr(type(val[0]), "model_fields"):
            continue
        sub_cat = fname.rstrip("s").replace("_", " ").capitalize() or category
        for item in val:
            _walk(item, sub_cat, name or parent, depth + 1, out)


def collect_world_entities(worldbuilding: Any) -> List[CanonEntity]:
    """Every named element in the project's worldbuilding."""
    out: List[CanonEntity] = []
    if worldbuilding is None:
        return out
    for fname, cat in _WORLD_CATEGORIES.items():
        for item in getattr(worldbuilding, fname, None) or []:
            _walk(item, cat, "", 1, out)
    for fname, cat in _LEGACY_ELEMENT_FIELDS.items():
        for name, desc in (getattr(worldbuilding, fname, None) or {}).items():
            if name and str(name).strip():
                out.append(CanonEntity(name=str(name).strip(), category=cat,
                                       summary=str(desc or "")[:350]))
    for entry in getattr(worldbuilding, "custom_encyclopedia", None) or []:
        if isinstance(entry, dict):
            name = (entry.get("name") or entry.get("title") or "").strip()
            if name:
                out.append(CanonEntity(
                    name=name, category=entry.get("category") or "Encyclopedia",
                    summary=(entry.get("summary") or entry.get("description")
                             or entry.get("content") or "")[:350]))
    # De-duplicate by (name, category).
    seen, unique = set(), []
    for e in out:
        key = (e.name.lower(), e.category)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _name_variants(name: str) -> List[str]:
    """The full name plus a distinctive first/last token for people and
    multi-word places ("Captain Mara Vell" → "Mara", "Vell")."""
    name = name.strip()
    variants = [name]
    tokens = [t for t in re.split(r"\s+", name) if t]
    honorifics = {"the", "of", "captain", "lord", "lady", "sir", "king", "queen",
                  "general", "doctor", "dr", "mr", "mrs", "ms", "master", "saint"}
    if len(tokens) > 1:
        for t in (tokens[0], tokens[-1]):
            t = t.strip(",.")
            if len(t) >= 4 and t.lower() not in honorifics and t not in variants:
                variants.append(t)
    return variants


def _mention_regex(variants: Iterable[str]) -> re.Pattern:
    alts = sorted({re.escape(v) for v in variants if v}, key=len, reverse=True)
    return re.compile(r"(?<![\w'])(" + "|".join(alts) + r")(?![\w])")


def find_mentions(text: str, names: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    """Count mentions of each named thing and keep a couple of example
    sentences. ``names`` maps canonical name → variants."""
    result: Dict[str, Dict[str, Any]] = {}
    if not text:
        return result
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for canonical, variants in names.items():
        if not variants:
            continue
        rx = _mention_regex(variants)
        count = len(rx.findall(text))
        if not count:
            continue
        examples = []
        for s in sentences:
            if rx.search(s):
                examples.append(s.strip()[:220])
                if len(examples) >= 3:
                    break
        result[canonical] = {"count": count, "examples": examples}
    return result


# Capitalized words that are never new canon on their own.
_COMMON_CAPS = set("""
I I'm I'd I'll I've The A An And But Or So Yet For Nor If Then When While Where What Who Why How
He She They We You It His Her Their Our Your Its Him Them Us Me My Mine This That These Those
There Here Now Not No Yes Oh Ah Well Okay OK Just Still Even Only After Before Because Though
Although Once Until Since As At By From In Into On Onto Of Off Out Over Under Up Down To With
Without Within Through Around Behind Beside Between Beyond Above Below Near Across Against Along
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June
July August September October November December Mr Mrs Ms Dr Sir Madam Lord Lady God Chapter
Mother Father Mom Dad Mum Grandma Grandpa Aunt Uncle Captain King Queen Prince Princess
Everyone Someone Nobody Nothing Something Everything Anyone Anything Each Every All Some Any
Maybe Perhaps Again Too Very Much Many More Most Other Another Such One Two Three First Last Next
Did Do Does Was Were Is Are Had Has Have Will Would Could Should Can Can't Don't Didn't Won't
Let Let's Come Go Get Look See Please Thank Thanks Hey Hello Goodbye Sorry Wait Stop Right Left
""".split())
# Capitalized word runs, allowing name connectors ("Order of Ash",
# "Isle of the Dead", "van Holt"). Plain "the" is NOT a connector, or
# "Past the Saltmarket" would read as one name.
_PROPER_RX = re.compile(
    r"\b([A-Z][a-z'’]+(?:(?:[ -]|\s(?:of(?:\sthe)?|de|van|von|al)\s)[A-Z][a-z'’]+){0,3})\b")
_SPEECH_AFTER = re.compile(
    r"^\W*(said|asked|replied|whispered|shouted|muttered|called|answered|"
    r"snapped|murmured|yelled|cried|told|nodded|smiled|frowned)\b")
_CONTRACTION_TAIL = re.compile(r"['’](s|re|ve|ll|d|m|t)$", re.IGNORECASE)


def find_unknown_proper_nouns(
    text: str,
    known_names: Iterable[str],
    min_count: int = 2,
    limit: int = 15,
) -> List[Tuple[str, int, str]]:
    """Proper-noun phrases the project doesn't know about.

    A phrase qualifies when it appears capitalized mid-sentence (so not
    just a sentence-opening word) and is not a known character, world
    element, or common capitalized word. Returns ``(phrase, count,
    example_sentence)`` sorted by frequency.
    """
    if not text:
        return []
    known_tokens = set()
    for n in known_names:
        for v in _name_variants(n):
            known_tokens.add(v.lower())
            for t in v.split():
                if len(t) >= 4:
                    known_tokens.add(t.lower())

    counts: Counter = Counter()
    mid_sentence: Counter = Counter()
    example: Dict[str, str] = {}
    for sent in re.split(r"(?<=[.!?…])[\"”’)]*\s+|\n+", text):
        sent_stripped = sent.lstrip(" \"“‘'(-—")
        for m in _PROPER_RX.finditer(sent_stripped):
            phrase = m.group(1).strip()
            # "Mara's" → "Mara"; "You're" / "Don't" → drop.
            tail = _CONTRACTION_TAIL.search(phrase)
            if tail:
                base = phrase[:tail.start()]
                if tail.group(1).lower() != "s" or base in _COMMON_CAPS:
                    continue
                phrase = base
            # Peel common leading words ("The Iron League" → "Iron League").
            words = phrase.split()
            while words and words[0] in _COMMON_CAPS:
                words = words[1:]
            if not words:
                continue
            phrase = " ".join(words)
            if phrase in _COMMON_CAPS or len(phrase) < 3:
                continue
            if phrase.lower() in known_tokens or all(
                    w.lower() in known_tokens for w in words):
                continue
            counts[phrase] += 1
            # Mid-sentence capitals, or a sentence-opening name followed
            # by a speech/gesture verb ("Kessa said…"), are strong signals.
            if m.start() > 0 or _SPEECH_AFTER.search(sent_stripped[m.end():]):
                mid_sentence[phrase] += 1
            example.setdefault(phrase, sent.strip()[:220])

    out = []
    for phrase, n in counts.most_common():
        # Seen once and only at a sentence start — too weak a signal.
        if n < min_count and mid_sentence[phrase] == 0:
            continue
        # Ordinary words capitalized at a sentence start also appear in
        # lowercase elsewhere; real names don't.
        if len(phrase.split()) == 1 and re.search(
                r"(?<![A-Za-z'])" + re.escape(phrase.lower()) + r"(?![A-Za-z])", text):
            continue
        out.append((phrase, n, example[phrase]))
        if len(out) >= limit:
            break
    return out


def character_name_variants(characters: Iterable[Any]) -> Dict[str, List[str]]:
    return {c.name: _name_variants(c.name) for c in characters
            if getattr(c, "name", "").strip()}


def world_name_variants(entities: Iterable[CanonEntity]) -> Dict[str, List[str]]:
    """Variants for world elements. Only the full name (plus explicit
    aliases) — single tokens of place names are too ambiguous."""
    out: Dict[str, List[str]] = {}
    for e in entities:
        out.setdefault(e.name, [e.name] + list(e.aliases))
    return out


# ── Character profile helpers ───────────────────────────────────────

CHARACTER_PROFILE_FIELDS = (
    ("personality", "Personality"),
    ("speaking_style", "Speaking style"),
    ("quirks", "Quirks"),
    ("motivations", "Motivations"),
    ("fears", "Fears"),
    ("emotional_baseline", "Emotional baseline"),
    ("want", "Want"),
    ("need", "Need"),
    ("lie_they_believe", "Lie they believe"),
    ("ghost", "Ghost"),
    ("character_arc", "Arc type"),
    ("moral_code", "Moral code"),
    ("worldview", "Worldview"),
    ("secret", "Secret"),
    ("contradictions", "Contradictions"),
    ("defining_relationship", "Defining relationship"),
)


def arc_checkpoint(character: Any, chapter_number: int) -> Tuple[Optional[Any], Optional[Any]]:
    """The character's latest arc snapshot at or before this chapter, and
    the next one after it (where they're headed)."""
    snaps = sorted((s for s in getattr(character, "personality_arc", None) or []
                    if getattr(s, "chapter_number", 0)),
                   key=lambda s: s.chapter_number)
    before = [s for s in snaps if s.chapter_number <= chapter_number]
    after = [s for s in snaps if s.chapter_number > chapter_number]
    return (before[-1] if before else None, after[0] if after else None)


def format_character_profile(character: Any, chapter_number: int = 0,
                             max_field: int = 260) -> str:
    lines = [f"### {character.name} ({getattr(character, 'character_type', '') or 'character'})"]
    traits = getattr(character, "personality_traits", None) or []
    if traits:
        lines.append(f"Key traits: {', '.join(traits)}")
    for attr, label in CHARACTER_PROFILE_FIELDS:
        v = (getattr(character, attr, "") or "").strip()
        if v:
            lines.append(f"{label}: {v[:max_field]}")
    if chapter_number:
        cur, nxt = arc_checkpoint(character, chapter_number)
        if cur is not None:
            bits = [b for b in (
                f"emotional state '{cur.emotional_state}'" if cur.emotional_state else "",
                f"active traits {', '.join(cur.traits_active)}" if cur.traits_active else "",
                cur.growth_notes[:160] if cur.growth_notes else "") if b]
            lines.append(f"Arc checkpoint (ch. {cur.chapter_number}): " + "; ".join(bits))
        if nxt is not None:
            bits = [b for b in (
                f"emotional state '{nxt.emotional_state}'" if nxt.emotional_state else "",
                nxt.growth_notes[:160] if nxt.growth_notes else "") if b]
            lines.append(f"Next planned checkpoint (ch. {nxt.chapter_number}): " + "; ".join(bits))
    return "\n".join(lines)


# ── Tagged-line parsing for LLM output ──────────────────────────────
#
# Small local models (Gemma, Llama 3B, Phi…) rarely reproduce a format
# exactly: they bold the tag, drop the brackets, number the list, or
# rename the tag. The parser accepts all of these.

_TAG_SYNONYMS = {
    "ON TRACK": "ON TRACK", "ONTRACK": "ON TRACK", "ON-TRACK": "ON TRACK",
    "ALIGNED": "ON TRACK", "ALIGNS": "ON TRACK", "CONSISTENT": "ON TRACK",
    "MATCH": "ON TRACK", "MATCHES": "ON TRACK", "STRENGTH": "ON TRACK",
    "DRIFT": "DRIFT", "DRIFTS": "DRIFT", "OFF TRACK": "DRIFT", "INCONSISTENT": "DRIFT",
    "INCONSISTENCY": "DRIFT", "OUT OF CHARACTER": "DRIFT",
    "DIFFERS": "DIFFERS", "DIFFER": "DIFFERS", "DIFFERENCE": "DIFFERS",
    "DIFFERENCES": "DIFFERS", "CONFLICT": "DIFFERS", "CONTRADICTION": "DIFFERS",
    "CONTRADICTS": "DIFFERS",
    "RECOMMEND": "RECOMMEND", "RECOMMENDATION": "RECOMMEND", "RECOMMENDS": "RECOMMEND",
    "SUGGESTION": "RECOMMEND", "SUGGEST": "RECOMMEND", "FIX": "RECOMMEND",
    "PROFILE UPDATE": "PROFILE UPDATE", "UPDATE PROFILE": "PROFILE UPDATE",
    "NEW": "NEW", "NEW ELEMENT": "NEW",
    "SKIP": "SKIP", "NOT NEW": "SKIP", "IGNORE": "SKIP",
    "VOICE": "VOICE", "ARC": "ARC", "PORTRAYAL": "PORTRAYAL",
    "NEW CHARACTER": "NEW CHARACTER",
}
_TAG_ALTS = "|".join(sorted((re.escape(t) for t in _TAG_SYNONYMS), key=len, reverse=True))
_TAG_RX = re.compile(
    r"^\s*(?:[-*•]|\d+[.)])?\s*(?:\*\*|__)?\s*"
    r"(?:\[\s*(?P<btag>[A-Za-z][A-Za-z \-]+?)\s*\]|(?P<ctag>" + _TAG_ALTS + r")\s*:)"
    r"\s*(?:\*\*|__)?\s*[:\-–—]?\s*(?P<body>.*?)\s*$",
    re.IGNORECASE)
_EMPTY_BODIES = {"", "none", "n/a", "na", "nothing", "-", "—", "none.", "n/a."}


def _canonical_tag(raw: str) -> Optional[str]:
    key = re.sub(r"\s+", " ", raw.strip().upper())
    return _TAG_SYNONYMS.get(key, key if key else None)


def parse_tagged_lines(narrative: str) -> Dict[str, List[str]]:
    """Pull tagged lines (``- [TAG] text``, ``**TAG:** text``, …) out of
    an LLM narrative, normalising tag names. Empty / "none" items are
    dropped."""
    out: Dict[str, List[str]] = {}
    for line in (narrative or "").splitlines():
        m = _TAG_RX.match(line)
        if not m:
            continue
        tag = _canonical_tag(m.group("btag") or m.group("ctag") or "")
        body = (m.group("body") or "").strip().strip("*_ ").strip()
        if not tag or body.lower().rstrip(".") in _EMPTY_BODIES:
            continue
        out.setdefault(tag, []).append(body)
    return out


def parse_tag_block(narrative: str, marker: str) -> Dict[str, List[str]]:
    """Tags from the block after ``marker`` when the model emitted it,
    else from anywhere in the narrative (small models often skip the
    marker but still tag their lines)."""
    text = narrative or ""
    idx = text.find(marker)
    return parse_tagged_lines(text[idx + len(marker):] if idx >= 0 else text)


def strip_tagged_block(narrative: str, marker: str) -> str:
    """Drop the machine-readable part so the narrative shows prose only.

    Cuts at ``marker`` when present; otherwise (small models often omit
    the marker) removes the individual tagged lines.
    """
    text = narrative or ""
    idx = text.find(marker)
    if idx >= 0:
        return text[:idx].rstrip()
    kept = [l for l in text.splitlines()
            if not (_TAG_RX.match(l) and _canonical_tag(
                (_TAG_RX.match(l).group("btag") or _TAG_RX.match(l).group("ctag") or ""))
                in {"ON TRACK", "DRIFT", "DIFFERS", "RECOMMEND", "PROFILE UPDATE", "NEW", "SKIP"})]
    return "\n".join(kept).rstrip()


def passages_mentioning(text: str, variants: Iterable[str], max_words: int = 450) -> str:
    """Paragraphs that mention any of ``variants`` (with the paragraph
    after each, which usually carries the reaction), up to a word budget.
    Lets a focused prompt see the evidence from the whole chapter rather
    than just its opening."""
    variants = [v for v in variants if v]
    if not text or not variants:
        return ""
    rx = _mention_regex(variants)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    picked: List[int] = []
    for i, p in enumerate(paras):
        if rx.search(p):
            for j in (i, i + 1):
                if j < len(paras) and j not in picked:
                    picked.append(j)
    out, used = [], 0
    for j in sorted(picked):
        n = len(paras[j].split())
        if used + n > max_words and out:
            break
        out.append(paras[j])
        used += n
    return "\n\n".join(out)
