"""Canonical tone taxonomy used across the Training Studio.

Tone is *orthogonal* to genre. Genre tells you what kind of story
("horror", "romance", "western"); tone tells you the emotional /
stylistic register ("grimdark", "light/cozy", "lyrical"). A grimdark
romance and a light romance are both romance — same genre — but the
training data the user wants for each is very different.

This module mirrors ``genres.py`` deliberately so the same UI / agent
plumbing can drive both. Each ``TONES[key]`` entry carries:

  * ``name`` — display label
  * ``aliases`` — search tokens, including common misspellings, so
    the agent's keyword scorer matches what users type
  * ``corpora`` — catalog ids (from ``corpus_catalog.CATALOG``) that
    embody the tone. A book can appear in multiple tones (e.g.
    *Wuthering Heights* is grimdark + tragic + romantic).
  * ``description`` — one-line summary the UI surfaces as a tooltip
  * ``low_pd_coverage`` — set on tones where PD-only training data is
    notably thin (e.g. noir/hardboiled), so the UI can warn before the
    user trains a tone-filtered model that won't have much to chew on

Tone filtering is **always opt-in**. ``corpora_for_tones([])`` returns
empty, and the call site is responsible for falling back to the full
genre selection when no tones are picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Dict, List, Set


# Minimum books we consider "definitive enough" to train a tone-filtered
# model on. Below this floor the filter augments rather than failing —
# nobody wants to train on 1 book and call it "tone-conditioned." Public-
# domain literary fiction is large enough that 5 books is a meaningful
# signal but small enough that very narrow (genre × tone) intersections
# can still hit it via the augment ladder.
MIN_DEFINITIVE_TONE_CORPORA = 5


TONES: Dict[str, Dict] = {
    # ── Grimdark ──
    "grimdark": {
        "name": "Grimdark",
        "description": "Bleak, brutal, morally ambiguous; cynical or "
                       "despairing register.",
        "aliases": [
            "grimdark", "grim-dark", "grim dark", "grimdrk",
            "bleak", "dark", "brutal", "nihilistic", "despairing",
            "morally grey", "morally gray", "noir-lit",
        ],
        "corpora": [
            "gutenberg-heart-of-darkness", "gutenberg-nostromo",
            "gutenberg-wuthering-heights", "gutenberg-house-borderland",
            "gutenberg-bierce-soldiers", "gutenberg-king-in-yellow",
            "gutenberg-tess", "gutenberg-house-of-mirth",
            "gutenberg-call-of-wild", "gutenberg-white-fang",
            "gutenberg-frankenstein", "gutenberg-dracula",
            "gutenberg-beetle", "gutenberg-wieland",
            "gutenberg-untamed", "gutenberg-red-badge",
        ],
    },

    # ── Light / cozy ──
    "light": {
        "name": "Light / Cozy",
        "description": "Warm, low-stakes, hopeful; gentle humor and "
                       "domestic register.",
        "aliases": [
            "light", "lite", "cozy", "cosy", "cozey",
            "gentle", "warm", "hopeful", "feel-good", "feel good",
            "low-stakes", "low stakes", "wholesome",
        ],
        "corpora": [
            "gutenberg-three-men-boat", "gutenberg-diary-nobody",
            "gutenberg-anne-green-gables", "gutenberg-emma",
            "gutenberg-pride-and-prejudice", "gutenberg-sense-sensibility",
            "gutenberg-persuasion", "gutenberg-chip-flying-u",
            "gutenberg-father-brown",
        ],
    },

    # ── Comedic / humorous ──
    "comedic": {
        "name": "Comedic",
        "description": "Active humor — jokes, vernacular wit, comic "
                       "set-pieces, comic timing.",
        "aliases": [
            "comedy", "comedic", "comic", "comedi", "comdy",
            "humor", "humour", "humorous", "humourous", "humorus",
            "funny", "witty", "farce", "farcical",
        ],
        "corpora": [
            "gutenberg-three-men-boat", "gutenberg-diary-nobody",
            "gutenberg-roughing-it", "gutenberg-emma",
            "gutenberg-pride-and-prejudice",
            "gutenberg-man-who-was-thursday",
            "gutenberg-arizona-nights",
        ],
    },

    # ── Lyrical / poetic ──
    "lyrical": {
        "name": "Lyrical",
        "description": "Poetic, musical, image-rich prose; sentence "
                       "rhythm matters as much as meaning.",
        "aliases": [
            "lyrical", "lyric", "lyrcal", "poetic", "poetc",
            "musical", "rhythmic", "lush", "atmospheric prose",
        ],
        "corpora": [
            "gutenberg-tess", "gutenberg-far-from-madding-crowd",
            "gutenberg-my-antonia",
            "gutenberg-mohicans", "gutenberg-deerslayer",
            "gutenberg-dubliners", "gutenberg-jane-eyre",
            "gutenberg-wuthering-heights",
        ],
    },

    # ── Tragic ──
    "tragic": {
        "name": "Tragic",
        "description": "Sorrowful, fated, doomed arcs; emphasis on "
                       "loss and inevitability.",
        "aliases": [
            "tragic", "tragedy", "tragdy", "tragick",
            "sad", "sorrowful", "doomed", "fated", "elegiac",
        ],
        "corpora": [
            "gutenberg-tess", "gutenberg-house-of-mirth",
            "gutenberg-wuthering-heights", "gutenberg-jane-eyre",
            "gutenberg-frankenstein", "gutenberg-wieland",
            "gutenberg-age-of-innocence",
        ],
    },

    # ── Whimsical ──
    "whimsical": {
        "name": "Whimsical",
        "description": "Playful, fantastical, magical; the tone of "
                       "fairy tales and absurdist invention.",
        "aliases": [
            "whimsical", "whimsy", "whimsicl", "whimscal",
            "playful", "fantastical", "magical", "fairy-tale",
            "fairytale", "absurd", "absurdist",
        ],
        "corpora": [
            "gutenberg-oz", "gutenberg-grimms",
            "wikisource-aesop", "gutenberg-flatland",
            "gutenberg-mysterious-island",
        ],
    },

    # ── Stark / minimalist ──
    "stark": {
        "name": "Stark / Minimalist",
        "description": "Spare, terse, hard prose; deadpan voice, "
                       "stripped-down sentences.",
        "aliases": [
            "stark", "minimalist", "minimal", "minimlst",
            "spare", "terse", "deadpan", "hard-boiled style",
        ],
        "corpora": [
            "gutenberg-call-of-wild", "gutenberg-white-fang",
            "gutenberg-bierce-soldiers", "gutenberg-red-badge",
            "gutenberg-log-of-cowboy", "gutenberg-bar-20",
        ],
    },

    # ── Romantic / sentimental ──
    "romantic": {
        "name": "Romantic / Sentimental",
        "description": "Heart-on-sleeve emotional register; explicit "
                       "feeling, swelling sentiment.",
        "aliases": [
            "romantic", "sentimental", "sentmntl", "tender",
            "emotional", "passionate", "heartfelt",
        ],
        "corpora": [
            "gutenberg-jane-eyre", "gutenberg-pride-and-prejudice",
            "gutenberg-sense-sensibility", "gutenberg-persuasion",
            "gutenberg-tenant-wildfell-hall",
            "gutenberg-age-of-innocence", "gutenberg-anne-green-gables",
            "gutenberg-far-from-madding-crowd",
        ],
    },

    # ── Ironic / satirical ──
    "ironic": {
        "name": "Ironic / Satirical",
        "description": "Cutting wit, social critique, controlled "
                       "narrator-distance; satire as register.",
        "aliases": [
            "ironic", "irony", "ironc", "ironik",
            "satirical", "satire", "satircal", "satirc",
            "sardonic", "wry", "social satire",
        ],
        "corpora": [
            "gutenberg-vanity-fair",
            "gutenberg-pride-and-prejudice", "gutenberg-emma",
            "gutenberg-house-of-mirth", "gutenberg-age-of-innocence",
            "gutenberg-twain-cooper", "gutenberg-roughing-it",
            "gutenberg-king-in-yellow",
            "gutenberg-man-who-was-thursday",
        ],
    },

    # ── Noir / hardboiled ──
    # Marked low_pd_coverage: definitive noir (Hammett 1929+, Chandler
    # 1939+) is still copyrighted. PD options here are noir-adjacent
    # rather than canonical noir, so the UI should warn.
    "noir": {
        "name": "Noir / Hardboiled",
        "description": "Cynical, world-weary, crime-tinged. PD coverage "
                       "is thin — true noir starts in the 1930s.",
        "aliases": [
            "noir", "noire", "hardboiled", "hard-boiled", "hard boiled",
            "pulp crime", "crime noir",
        ],
        "corpora": [
            "gutenberg-heart-of-darkness", "gutenberg-bierce-soldiers",
            "gutenberg-thirty-nine-steps", "gutenberg-moonstone",
            "gutenberg-nostromo", "gutenberg-untamed",
        ],
        "low_pd_coverage": True,
    },
}


def all_alias_pairs() -> List[tuple]:
    """Flat list of ``(alias, canonical_key)`` for every alias."""
    out: List[tuple] = []
    for key, info in TONES.items():
        for alias in info.get("aliases", []):
            out.append((alias, key))
    return out


def match_tones(text: str, fuzzy_cutoff: float = 0.78) -> List[str]:
    """Return canonical tone keys whose aliases appear in ``text``.

    Same two-pass strategy as ``genres.match_genres``: substring match
    for multi-word aliases, then fuzzy single-word match for typos.
    """
    if not text:
        return []
    text_lower = text.lower()
    matched: Set[str] = set()

    for alias, key in all_alias_pairs():
        if alias in text_lower:
            matched.add(key)

    single_word_aliases = [a for a, _ in all_alias_pairs() if " " not in a]
    alias_to_key = {a: k for a, k in all_alias_pairs() if " " not in a}
    for word in _tokenize(text_lower):
        if len(word) < 4:
            continue
        close = get_close_matches(
            word, single_word_aliases, n=1, cutoff=fuzzy_cutoff)
        if close:
            matched.add(alias_to_key[close[0]])

    return sorted(matched)


def _tokenize(text: str) -> List[str]:
    import re
    return [t for t in re.split(r"[^a-z0-9]+", text) if t]


def info_for(key: str) -> Dict:
    return TONES.get(key, {})


def display_name(key: str) -> str:
    return TONES.get(key, {}).get("name", key.title())


def description_for(key: str) -> str:
    return TONES.get(key, {}).get("description", "")


def is_low_coverage(key: str) -> bool:
    """True for tones where PD training data is notably thin."""
    return bool(TONES.get(key, {}).get("low_pd_coverage", False))


def corpora_for_tones(keys: List[str]) -> List[str]:
    """Union of corpus ids exemplifying any of the given tones.

    Empty list is the opt-out signal — call sites that get an empty
    result from this should fall back to the unfiltered (genre-only)
    corpus selection.
    """
    out: List[str] = []
    seen: Set[str] = set()
    for k in keys:
        for cid in TONES.get(k, {}).get("corpora", []):
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


@dataclass
class ToneFilterResult:
    """Outcome of applying a tone filter to a genre's corpora.

    The dataclass is what a caller gets back instead of a bare list so
    the UI can show *why* the resulting corpus has the books it has —
    a strict tone match, a tone-augmented set, or a full tone-only
    fallback. ``corpus_ids`` is always non-empty if the input was
    non-empty (we guarantee a definitive floor through augmentation).

    Status values:
        - ``"opted_out"`` — user picked no tones; passthrough.
        - ``"intersection"`` — direct genre × tone hit was already at
          or above ``MIN_DEFINITIVE_TONE_CORPORA``.
        - ``"augmented_with_tone_pool"`` — strict intersection was
          below the floor; we added tone-aligned books from outside
          the genre to reach it.
        - ``"augmented_with_genre_pool"`` — even after pulling in tone
          exemplars we were below the floor (rare); we relaxed the
          tone requirement and topped up with genre books.
        - ``"tone_fallback"`` — strict intersection was empty; we
          returned the tone exemplar set so the user trains on tone-
          relevant material rather than nothing.
    """
    corpus_ids: List[str]
    status: str
    intersection_count: int = 0
    added_from_tone_pool: int = 0
    added_from_genre_pool: int = 0
    tones_used: List[str] = field(default_factory=list)

    def explain(self) -> str:
        """Short human-readable line for the UI / log."""
        if self.status == "opted_out":
            return "tone filter off — using full genre selection"
        n = len(self.corpus_ids)
        ts = ", ".join(self.tones_used) or "no tones"
        if self.status == "intersection":
            return f"{n} books match {ts} directly within selected genres"
        if self.status == "augmented_with_tone_pool":
            return (f"{n} books — {self.intersection_count} match "
                    f"{ts} within genre, {self.added_from_tone_pool} "
                    f"added from broader tone pool to reach the "
                    f"definitive floor")
        if self.status == "augmented_with_genre_pool":
            return (f"{n} books — extended with {self.added_from_genre_pool} "
                    f"genre books that don't strictly match {ts} (PD "
                    f"coverage was thin)")
        if self.status == "tone_fallback":
            return (f"{n} books — no genre × tone overlap; using "
                    f"{ts} exemplars only")
        return f"{n} books"


def filter_corpora_by_tones(
        corpus_ids: List[str],
        tone_keys: List[str],
        *,
        min_definitive: int = MIN_DEFINITIVE_TONE_CORPORA,
) -> ToneFilterResult:
    """Filter ``corpus_ids`` to tone-matching books, with a definitive floor.

    The expected pattern in the training pipeline is:
        result = filter_corpora_by_tones(
            corpora_for(selected_genres), selected_tones)
        # use result.corpus_ids for training
        # show result.explain() in the UI

    Behaviour:
      1. ``tone_keys`` empty → opt-out passthrough.
      2. Strict intersection ≥ ``min_definitive`` → return it.
      3. Strict intersection < floor → augment with tone-pool books
         that aren't already in the genre selection, preserving order
         (intersection first, then tone-only books).
      4. Combined still below floor → relax tone, top up with genre
         books that don't strictly match the tone.
      5. Strict intersection was zero AND tone pool empty → final
         fallback to tone-only exemplars.

    The ladder guarantees ``corpus_ids`` is never empty when the
    inputs are non-empty, which is what callers care about: even with
    every filter ticked, training has *something* canonical to chew
    on.
    """
    if not tone_keys:
        return ToneFilterResult(
            corpus_ids=list(corpus_ids),
            status="opted_out",
            tones_used=[])

    tone_set: Set[str] = set()
    for k in tone_keys:
        for cid in TONES.get(k, {}).get("corpora", []):
            tone_set.add(cid)

    intersection = [cid for cid in corpus_ids if cid in tone_set]
    intersection_count = len(intersection)

    # Path 1: enough direct hits — done.
    if intersection_count >= min_definitive:
        return ToneFilterResult(
            corpus_ids=intersection,
            status="intersection",
            intersection_count=intersection_count,
            tones_used=list(tone_keys))

    # Path 2: augment with tone-pool books not already counted.
    seen = set(intersection)
    augmented = list(intersection)
    for cid in corpora_for_tones(tone_keys):
        if cid not in seen:
            augmented.append(cid); seen.add(cid)
        if len(augmented) >= min_definitive:
            break
    added_tone = len(augmented) - intersection_count

    if len(augmented) >= min_definitive:
        # If we didn't find ANY direct intersection, name it as
        # tone_fallback for honesty — the genre wasn't really involved.
        status = ("tone_fallback" if intersection_count == 0
                  else "augmented_with_tone_pool")
        return ToneFilterResult(
            corpus_ids=augmented,
            status=status,
            intersection_count=intersection_count,
            added_from_tone_pool=added_tone,
            tones_used=list(tone_keys))

    # Path 3: still below floor — relax tone, top up from genre books
    # that didn't strictly match. This means we'll train on books
    # whose tone is approximate, but at least the genre is right.
    for cid in corpus_ids:
        if cid not in seen:
            augmented.append(cid); seen.add(cid)
        if len(augmented) >= min_definitive:
            break
    added_genre = len(augmented) - intersection_count - added_tone

    return ToneFilterResult(
        corpus_ids=augmented,
        status="augmented_with_genre_pool",
        intersection_count=intersection_count,
        added_from_tone_pool=added_tone,
        added_from_genre_pool=added_genre,
        tones_used=list(tone_keys))


def all_keys() -> List[str]:
    return list(TONES.keys())
