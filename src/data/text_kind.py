"""Classify a passage as narrative prose vs craft/criticism text.

The training data lands in two physically-distinct content shapes
that need different handling:

  * **narrative** — story prose. Characters do things in scenes;
    third-person past or present tense; dialogue; descriptions of
    place and action. The right shape for *voice* training.

  * **craft** — essays / criticism / introductions / how-to about
    writing. Talks ABOUT writers, characters, plot, structure,
    rather than DOING those things. The right shape for *plot*,
    *character*, and *worldbuilding* training (it teaches the user
    to think about story moves explicitly), but the wrong shape
    for voice (it's expository, not voice-bearing prose).

Without distinguishing the two, a "How to Write a Thriller" passage
ingested as a corpus row teaches the model to imitate craft-essay
voice when the user wants thriller prose voice. The classifier here
gives the export pipeline a hint so corpus/voice training can drop
craft rows while plot/character/worldbuilding training keeps them.

The signal is purely heuristic — meta-writing vocabulary density,
narrative-pronoun patterns, and dialogue density. Tuned to be:

  * **conservative on "craft"** — we'd rather miss a craft text
    than mis-label a fiction passage as one (a wrongly-labelled
    fiction passage is the worse failure mode, since dropping it
    from voice training loses signal).
  * **decisive on "narrative"** — a passage with clear dialogue
    or strong narrative pronouns is narrative even if it includes
    some meta vocabulary (a fiction passage about a writer
    character would otherwise trip the craft heuristic).
  * **agnostic when unclear** — returns "unknown" so the export
    filter can fall back to a default policy rather than make a
    bad guess.
"""

from __future__ import annotations

import re
from typing import Tuple


# ── Vocabularies ────────────────────────────────────────────
#
# Words / phrases that betray "writing about writing" content.
# Density is computed per 100 word tokens; thresholds tuned on
# small samples of essays vs fiction.

_META_WRITING_TERMS = {
    # People / roles
    "author", "authors", "writer", "writers", "novelist", "novelists",
    "essayist", "playwright", "screenwriter", "poet", "critic",
    "reader", "readers", "audience",
    "protagonist", "protagonists", "antagonist", "antagonists",
    "narrator", "narrators",
    # Forms / formats
    "novel", "novels", "novella", "novellas", "fiction", "non-fiction",
    "nonfiction", "memoir", "essay", "essays", "story", "stories",
    "narrative", "narratives", "prose", "verse", "poetry",
    "screenplay", "screenplays", "manuscript", "manuscripts",
    "chapter", "chapters", "scene", "scenes", "passage", "passages",
    # Craft vocabulary
    "characterisation", "characterization", "plotting", "pacing",
    "exposition", "subplot", "subplots", "foreshadowing",
    "voice", "tone", "diction", "syntax", "vocabulary",
    "imagery", "metaphor", "simile", "symbolism",
    "structure", "form", "genre", "genres", "trope", "tropes",
    "archetype", "archetypes", "motif", "motifs", "theme", "themes",
    "denouement", "climax", "rising-action", "falling-action",
    "first-person", "third-person", "second-person", "pov",
    "flashback", "flashbacks", "framing", "frame-story",
    "show", "tell", "telling", "showing",
    "draft", "drafting", "revising", "revision", "editing",
}


# Verbs typical of narrative prose (someone DOING something), as
# distinct from craft prose (someone EXPLAINING something).
_NARRATIVE_PRONOUN_VERBS = re.compile(
    r"\b(?:he|she|they|it|i)\s+"
    r"(?:said|asked|whispered|shouted|laughed|smiled|nodded|"
    r"shrugged|sighed|frowned|stared|glanced|looked|watched|"
    r"walked|ran|stood|sat|leaned|turned|moved|reached|"
    r"thought|wondered|remembered|felt|saw|heard|knew)\b",
    re.I)

# Dialogue cues — quoted speech is a near-perfect narrative tell.
# We count both straight and curly quotes paired with quoting verbs.
_DIALOGUE_LINES = re.compile(
    r"[\"“‘]"            # opening quote
    r"[^\"“”‘’]{6,}"  # speech body
    r"[\"”’]",
    re.S)

# "The author of X" / "the writer's Y" — strong craft tells that
# directly invoke an external creator's perspective. Caught even
# when other meta vocab is sparse.
_AUTHORIAL_REFERENCE = re.compile(
    r"\bthe\s+(?:author|writer|novelist|playwright|poet)"
    r"(?:'s|\s+of)\b",
    re.I)

# "In this novel/chapter/passage/story" — the most reliable craft
# tell. Only critics talk about a piece of fiction this way.
_META_REFERENCE = re.compile(
    r"\bin\s+this\s+(?:novel|story|chapter|scene|passage|"
    r"book|essay|excerpt|piece|work)\b",
    re.I)


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _tokenize(text: str):
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _meta_density(tokens) -> float:
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in _META_WRITING_TERMS)
    return hits / max(1, len(tokens))


def _narrative_density(tokens, raw_text: str) -> Tuple[float, int, int]:
    """Returns (per-100 narrative-verb density, dialogue line count,
    explicit-meta-reference count)."""
    n_pronoun_verbs = len(_NARRATIVE_PRONOUN_VERBS.findall(raw_text))
    n_dialogue = len(_DIALOGUE_LINES.findall(raw_text))
    n_meta_ref = (len(_AUTHORIAL_REFERENCE.findall(raw_text))
                  + len(_META_REFERENCE.findall(raw_text)))
    density = n_pronoun_verbs / max(1, len(tokens) / 100)
    return density, n_dialogue, n_meta_ref


def classify_kind(*texts: str) -> str:
    """Return one of ``"narrative"``, ``"craft"``, or ``"unknown"``.

    Pass the source AND output texts (or just one) — the classifier
    pools them so the heuristics run on more signal. Designed to be
    cheap (regex + counter) so it's fine to call per-row at export
    time.

    Decision rules (in order):

      1. Strong narrative tell (dialogue lines + narrative-pronoun
         verbs above floor) → ``"narrative"`` regardless of meta
         vocabulary density. A fiction passage about a writer
         character looks "crafty" by vocab but reads as narrative
         because of dialogue and 3rd-person verbs.
      2. Strong craft tell ("In this novel…", "the author of…"
         appearing more than once, or meta-vocab density above 3%)
         and weak narrative tell → ``"craft"``.
      3. Otherwise → ``"unknown"`` — defer to caller's default.
    """
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return "unknown"
    tokens = _tokenize(blob)
    if len(tokens) < 30:
        # Too short to classify reliably.
        return "unknown"

    meta_dens = _meta_density(tokens)  # fraction
    narr_dens, n_dialogue, n_meta_ref = _narrative_density(
        tokens, blob)

    # Rule 1: clear narrative tell.
    if n_dialogue >= 2 or narr_dens >= 1.5:
        return "narrative"

    # Rule 2: clear craft tell.
    # ``meta_dens >= 0.03`` = 3% of tokens are meta-writing vocab —
    # a strong signal a passage is about writing rather than doing
    # writing. Plus the explicit reference patterns reinforce.
    if (n_meta_ref >= 2
            or (meta_dens >= 0.03 and narr_dens < 0.5)):
        return "craft"

    return "unknown"
