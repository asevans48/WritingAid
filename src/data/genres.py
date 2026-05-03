"""Canonical genre taxonomy used across the Training Studio.

Every other module that maps user-typed text → corpora → authors goes
through this file. One source of truth means a misspelling fix here
fixes recipe builder, the Step 1 genre picker, the UI suggestions,
and the recipe display all at once.

Each ``GENRES[key]`` entry carries:
  * ``name`` — display label
  * ``aliases`` — search tokens, including common misspellings (e.g.
    "horro", "westren", "thrler") so the agent's keyword scorer
    matches what users actually type
  * ``corpora`` — catalog ids (from ``corpus_catalog.CATALOG``) that
    embody the genre
  * ``authors`` — the touchstone authors users should consider when
    expanding their training set
  * ``comps`` — comparable titles (PD only — every comp listed has a
    matching entry in our catalog or a public-domain source the user
    can register through the Add Custom URL flow)
  * ``craft`` — writing-instruction documents focused on this genre
    (subset of catalog ids)
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Dict, List, Set


GENRES: Dict[str, Dict] = {
    # ── Horror ──
    "horror": {
        "name": "Horror",
        "aliases": [
            "horror", "horro", "horrr", "horor", "hror", "hroror",
            "scary", "spooky", "macabre", "supernatural",
            "weird-fiction", "weird fiction", "weirdfiction", "eerie",
            "creepy", "ghost story", "ghost-story", "ghoststory",
        ],
        # Sibling sub-genre — gothic shares atmosphere, dread, and
        # most of the foundational corpus (Frankenstein, Dracula,
        # Carmilla all live in both). A horror training run picks
        # up gothic rows automatically and vice versa.
        "ancillary": ["gothic"],
        "corpora": [
            "gutenberg-frankenstein", "gutenberg-dracula",
            "gutenberg-poe-tales", "gutenberg-king-in-yellow",
            "gutenberg-mr-james-ghost", "gutenberg-carmilla",
            "gutenberg-great-god-pan",
            "gutenberg-monkeys-paw", "gutenberg-bierce-soldiers",
            "gutenberg-willows", "gutenberg-house-borderland",
            "gutenberg-hauntings", "gutenberg-turn-of-screw",
            "gutenberg-beetle", "gutenberg-wieland",
            # Whole PG with bookshelf-tagged horror entries.
            "hf-pg-tagged",
        ],
        "authors": [
            "Edgar Allan Poe", "Mary Shelley", "Bram Stoker",
            "M. R. James", "Sheridan Le Fanu", "Arthur Machen",
            "Robert W. Chambers", "H. P. Lovecraft", "Ambrose Bierce",
            "Algernon Blackwood", "W. W. Jacobs",
            "William Hope Hodgson", "Vernon Lee", "Henry James",
            "Richard Marsh", "Charles Brockden Brown",
        ],
        "comps": [
            "Frankenstein — Mary Shelley",
            "Dracula — Bram Stoker",
            "The King in Yellow — Robert W. Chambers",
            "Carmilla — J. Sheridan Le Fanu",
            "Ghost Stories of an Antiquary — M. R. James",
            "The Great God Pan — Arthur Machen",
            "The Monkey's Paw — W. W. Jacobs",
            "Tales of Soldiers and Civilians — Ambrose Bierce",
            "The Willows — Algernon Blackwood",
            "The House on the Borderland — William Hope Hodgson",
            "Hauntings — Vernon Lee",
            "The Turn of the Screw — Henry James",
            "The Beetle — Richard Marsh",
            "Wieland — Charles Brockden Brown",
        ],
        "craft": [
            "gutenberg-poe-philosophy",          # Poe — Philosophy of Composition
            "gutenberg-lovecraft-horror",        # Lovecraft — Supernatural Horror
            "gutenberg-machen-hieroglyphics",    # Machen — weird-fiction philosophy
            "gutenberg-scarborough-supernatural", # Scarborough — definitive horror crit
            "gutenberg-frazer-golden-bough",     # mythic / ritual archetypes
            "gutenberg-longinus-sublime",        # elevated / awful style
            "gutenberg-poetics",                 # Aristotle — plot theory
            "gutenberg-lubbock-craft",           # POV / scene
            "gutenberg-hamilton-materials",      # comprehensive craft
        ],
    },

    # ── Gothic (overlaps with horror but distinct in style) ──
    "gothic": {
        "name": "Gothic",
        "aliases": ["gothic", "gothick", "gohtic", "gothic horror"],
        # Sibling sub-genre — see horror entry for the rationale.
        "ancillary": ["horror"],
        "corpora": [
            "gutenberg-frankenstein", "gutenberg-dracula",
            "gutenberg-wuthering-heights", "gutenberg-carmilla",
            "gutenberg-jane-eyre",
            # Whole PG English — bookshelf-tagged Gothic Fiction.
            "hf-pg-tagged",
        ],
        "authors": [
            "Mary Shelley", "Bram Stoker", "Charlotte Brontë",
            "Emily Brontë", "Sheridan Le Fanu", "Ann Radcliffe",
            "Horace Walpole",
        ],
        "comps": [
            "Frankenstein — Mary Shelley",
            "Wuthering Heights — Emily Brontë",
            "Jane Eyre — Charlotte Brontë",
            "Carmilla — J. Sheridan Le Fanu",
        ],
        "craft": [
            "gutenberg-lovecraft-horror",        # weird-fiction theory
            "gutenberg-machen-hieroglyphics",    # ecstatic / numinous prose
            "gutenberg-scarborough-supernatural", # gothic + supernatural survey
            "gutenberg-pater-appreciations",     # decadent style / aesthetics
            "gutenberg-coleridge-biographia",    # imagination theory
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-poetics",                 # plot theory
        ],
    },

    # ── Romance ──
    "romance": {
        "name": "Romance",
        "aliases": [
            "romance", "ramance", "romnce", "romanc", "romantic",
            "love story", "love-story", "lovestory", "courtship",
            "regency", "comedy of manners", "comedy-of-manners",
        ],
        "corpora": [
            "gutenberg-pride-and-prejudice",
            "gutenberg-wuthering-heights", "gutenberg-jane-eyre",
            "gutenberg-sense-sensibility", "gutenberg-persuasion",
            "gutenberg-tenant-wildfell-hall",
            "gutenberg-far-from-madding-crowd", "gutenberg-tess",
            "gutenberg-middlemarch",
            "gutenberg-age-of-innocence", "gutenberg-house-of-mirth",
            "gutenberg-emma", "gutenberg-anne-green-gables",
            # Whole PG English with bookshelf-tagged romance entries.
            "hf-pg-tagged",
            # Pulp-era romance fills the gap between Austen / Brontë
            # 1800s and modern still-copyrighted romance.
            "hf-storytracer-us-pd",
        ],
        "authors": [
            "Jane Austen", "Charlotte Brontë", "Emily Brontë",
            "Anne Brontë", "George Eliot", "Elizabeth Gaskell",
            "Edith Wharton", "Henry James",
            "Thomas Hardy", "L. M. Montgomery",
        ],
        "comps": [
            "Pride and Prejudice — Jane Austen",
            "Sense and Sensibility — Jane Austen",
            "Persuasion — Jane Austen",
            "Emma — Jane Austen",
            "Jane Eyre — Charlotte Brontë",
            "Wuthering Heights — Emily Brontë",
            "The Tenant of Wildfell Hall — Anne Brontë",
            "Far from the Madding Crowd — Thomas Hardy",
            "Tess of the d'Urbervilles — Thomas Hardy",
            "Middlemarch — George Eliot",
            "The Age of Innocence — Edith Wharton",
            "The House of Mirth — Edith Wharton",
            "Anne of Green Gables — L. M. Montgomery",
        ],
        "craft": [
            "gutenberg-wharton-writing-fiction",   # primary romance craft
            "gutenberg-james-art-fiction",         # character / consciousness
            "gutenberg-besant-art-fiction",        # the lecture James was answering
            "gutenberg-trollope-autobiography",    # Trollope on novel-writing process
            "gutenberg-on-art-of-writing",         # Quiller-Couch lectures
            "gutenberg-pater-appreciations",       # style / aesthetics
            "gutenberg-matthews-playwrights",      # dialogue + scene craft
            "gutenberg-lubbock-craft",             # POV / scene
            "gutenberg-hamilton-materials",        # comprehensive
            "gutenberg-poetics",                   # plot theory
        ],
    },

    # ── Mystery (cozy / detective) ──
    "mystery": {
        "name": "Mystery",
        "aliases": [
            "mystery", "mistery", "mystry", "mysery",
            "detective", "detectiv", "whodunit", "whodunnit",
            "cozy mystery", "sleuth",
        ],
        "corpora": [
            "gutenberg-sherlock", "gutenberg-moonstone",
            "gutenberg-father-brown",
            "gutenberg-mysterious-affair-styles",
            "gutenberg-leavenworth-case",
            # Whole PG English — bookshelf-tagged Mystery + Detective.
            "hf-pg-tagged",
            # Pulp-era detective novels (1923-1965ish) that
            # dominated mid-century American mystery.
            "hf-storytracer-us-pd",
        ],
        "authors": [
            "Arthur Conan Doyle", "Wilkie Collins", "Edgar Allan Poe",
            "G. K. Chesterton", "Anna Katharine Green",
            "Agatha Christie", "Mary Roberts Rinehart",
        ],
        "comps": [
            "The Adventures of Sherlock Holmes — Arthur Conan Doyle",
            "The Moonstone — Wilkie Collins",
            "The Innocence of Father Brown — G. K. Chesterton",
            "The Mysterious Affair at Styles — Agatha Christie",
            "The Leavenworth Case — Anna Katharine Green",
        ],
        "craft": [
            "gutenberg-poe-philosophy",          # ratiocinative method
            "gutenberg-doyle-magic-door",        # Doyle on mystery influences
            "gutenberg-archer-playmaking",       # plot construction
            "gutenberg-matthews-playwrights",    # scene + reveal
            "gutenberg-lubbock-craft",           # POV / clue placement
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot theory
        ],
    },

    # ── Thriller / suspense / spy ──
    "thriller": {
        "name": "Thriller / Suspense",
        "aliases": [
            "thriller", "thrler", "thrller", "trhiller", "thrille",
            "suspense", "supsense", "suspence",
            "spy", "espionage", "psychological thriller",
            "psychologicalthriller",
        ],
        "corpora": [
            "gutenberg-thirty-nine-steps",
            "gutenberg-man-who-was-thursday",
            "gutenberg-moonstone", "gutenberg-heart-of-darkness",
            "gutenberg-invisible-man",
            # Whole PG English — bookshelf-tagged thriller-adjacent.
            "hf-pg-tagged",
            # Pulp-era thriller / spy fiction.
            "hf-storytracer-us-pd",
        ],
        "authors": [
            "John Buchan", "Wilkie Collins", "G. K. Chesterton",
            "Joseph Conrad", "Erskine Childers", "E. W. Hornung",
        ],
        "comps": [
            "The Thirty-Nine Steps — John Buchan",
            "The Man Who Was Thursday — G. K. Chesterton",
            "The Moonstone — Wilkie Collins",
            "Heart of Darkness — Joseph Conrad",
        ],
        "craft": [
            "gutenberg-rls-humble-remonstrance", # Stevenson on adventure form
            "gutenberg-doyle-magic-door",        # Doyle on suspense / influence
            "gutenberg-archer-playmaking",       # pacing / climax
            "gutenberg-matthews-playwrights",    # tension + reveal
            "gutenberg-longinus-sublime",        # emotional impact
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot theory
        ],
    },

    # ── Science fiction ──
    "scifi": {
        "name": "Science Fiction",
        "aliases": [
            "scifi", "sci-fi", "sci fi", "science fiction",
            "sciencefiction", "scince fiction", "scifi novel",
            "speculative fiction", "speculative-fiction", "specfic",
            "space opera", "planetary romance",
        ],
        "corpora": [
            "gutenberg-time-machine", "gutenberg-war-of-worlds",
            "gutenberg-invisible-man", "gutenberg-20000-leagues",
            "gutenberg-princess-mars", "gutenberg-frankenstein",
            "gutenberg-flatland", "gutenberg-mysterious-island",
            # storytracer captures pulp-era SF (1923-1965ish) that
            # lapsed into PD via copyright non-renewal — fills the
            # gap between PG (pre-1929) and modern still-copyrighted
            # SF. Replaces the SF-Corpus EF entries which were
            # removed (HathiTrust Extracted Features ≠ prose).
            "hf-storytracer-us-pd",
            # Whole PG English — bookshelf-tagged Science Fiction.
            "hf-pg-tagged",
        ],
        "authors": [
            "H. G. Wells", "Jules Verne", "Edgar Rice Burroughs",
            "Mary Shelley", "Edwin Abbott", "Olaf Stapledon",
        ],
        "comps": [
            "The Time Machine — H. G. Wells",
            "The War of the Worlds — H. G. Wells",
            "20,000 Leagues Under the Sea — Jules Verne",
            "A Princess of Mars — Edgar Rice Burroughs",
            "Flatland — Edwin Abbott",
            "The Mysterious Island — Jules Verne",
        ],
        "craft": [
            # The closest thing to an SF-craft manifesto in PD is Wells's
            # 'Discovery of the Future' — Wells theorizing speculative
            # imagination at the height of his SF career.
            "gutenberg-wells-discovery-future",  # Wells on speculative inquiry
            "gutenberg-lovecraft-horror",        # scientific-romance tradition
            "gutenberg-coleridge-biographia",    # imagination theory
            "gutenberg-archer-playmaking",       # plot / pacing
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-on-art-of-writing",       # Quiller-Couch
            "gutenberg-poetics",                 # plot theory
        ],
    },

    # ── Western ──
    # Cowboy / Old-West specifically. Broader frontier prose
    # (colonial wilderness, Klondike survival, prairie homesteading)
    # lives under "frontier" below.
    "western": {
        "name": "Western",
        "aliases": [
            "western", "westren", "westrn", "weston", "wstern",
            "cowboy", "cowboi", "cowoy",
            "ranch", "outlaw", "old west",
        ],
        # Sibling sub-genres — when the user filters for western,
        # these come along for the ride. Frontier shares enough
        # setting / vocabulary / craft DNA that a western training
        # run benefits from frontier corpora and vice versa.
        "ancillary": ["frontier"],
        "corpora": [
            "gutenberg-virginian", "gutenberg-riders-purple-sage",
            "gutenberg-log-of-cowboy", "gutenberg-arizona-nights",
            "gutenberg-luck-roaring-camp", "gutenberg-chip-flying-u",
            "gutenberg-untamed", "gutenberg-bar-20",
            "gutenberg-main-travelled-roads",
            # Whole PG English — bookshelf-tagged Westerns.
            "hf-pg-tagged",
            # Pulp-era westerns (Max Brand and successors had a
            # productive 1923-1965 run that lapsed into PD).
            "hf-storytracer-us-pd",
        ],
        "authors": [
            "Owen Wister", "Zane Grey", "Andy Adams",
            "Stewart Edward White", "Bret Harte", "Max Brand",
            "B. M. Bower", "Clarence E. Mulford", "Hamlin Garland",
        ],
        "comps": [
            "The Virginian — Owen Wister",
            "Riders of the Purple Sage — Zane Grey",
            "The Log of a Cowboy — Andy Adams",
            "Arizona Nights — Stewart Edward White",
            "The Luck of Roaring Camp — Bret Harte",
            "Chip, of the Flying U — B. M. Bower",
            "The Untamed — Max Brand",
            "The Man from Bar-20 — Clarence E. Mulford",
            "Main-Travelled Roads — Hamlin Garland",
        ],
        "craft": [
            "gutenberg-twain-cooper",            # Twain's 19 rules of romantic
                                                 # fiction — explicit Western
                                                 # craft critique
            "gutenberg-twain-howto",             # vernacular oral storytelling
            "gutenberg-rls-humble-remonstrance", # adventure form
            "gutenberg-doyle-magic-door",        # Doyle on heroic narrative
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot
        ],
    },

    # ── Frontier fiction ──
    # Distinct from cowboy "western": colonial-era wilderness
    # (Cooper), Klondike survival (London), prairie homesteading
    # (Cather), frontier memoir (Twain). Twain's Roughing It is
    # also tagged western since it bridges both.
    "frontier": {
        "name": "Frontier",
        "aliases": [
            "frontier", "fronter", "frontear",
            "pioneer", "pionear", "pioneer fiction",
            "wilderness", "wildness", "wildernes",
            "settler", "homestead", "homesteading",
            "captivity", "leatherstocking",
            "klondike", "yukon", "prairie",
        ],
        # Sibling sub-genre — see western entry for the rationale.
        "ancillary": ["western"],
        "corpora": [
            "gutenberg-mohicans", "gutenberg-deerslayer",
            "gutenberg-call-of-wild", "gutenberg-white-fang",
            "gutenberg-my-antonia", "gutenberg-roughing-it",
            # Whole PG English — bookshelf-tagged "Frontier and
            # Pioneer Life" entries.
            "hf-pg-tagged",
        ],
        "authors": [
            "James Fenimore Cooper", "Jack London",
            "Willa Cather", "Mark Twain",
        ],
        "comps": [
            "The Last of the Mohicans — James Fenimore Cooper",
            "The Deerslayer — James Fenimore Cooper",
            "The Call of the Wild — Jack London",
            "White Fang — Jack London",
            "My Ántonia — Willa Cather",
            "Roughing It — Mark Twain",
        ],
        "craft": [
            "gutenberg-twain-cooper",            # Twain's craft attack on
                                                 # Cooper — directly germane
                                                 # to frontier prose
            "gutenberg-twain-howto",             # vernacular voice
            "gutenberg-rls-humble-remonstrance", # adventure form
            "gutenberg-lang-adventures-books",   # Lang on heroic / frontier
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot
        ],
    },

    # ── Fantasy ──
    "fantasy": {
        "name": "Fantasy",
        "aliases": [
            "fantasy", "fantasi", "fantsy", "fanasy", "fntasy",
            "magic", "wizards", "fairy tale", "fairy-tale", "fairytale",
            "fairy", "fable", "myth", "mythology",
        ],
        "corpora": [
            "gutenberg-grimms", "wikisource-aesop",
            "gutenberg-princess-mars", "gutenberg-oz",
            # Whole PG English — bookshelf-tagged Fantasy.
            "hf-pg-tagged",
        ],
        "authors": [
            "Brothers Grimm", "Aesop", "Lord Dunsany",
            "George MacDonald", "William Morris", "L. Frank Baum",
        ],
        "comps": [
            "Grimms' Fairy Tales",
            "Aesop's Fables",
            "The Wonderful Wizard of Oz — L. Frank Baum",
        ],
        "craft": [
            "gutenberg-macdonald-orts",          # MacDonald — The Fantastic
                                                 # Imagination, founding essay
            "gutenberg-lang-adventures-books",   # Lang on fairy-tale + romance
            "gutenberg-frazer-golden-bough",     # archetype / myth structure
            "gutenberg-coleridge-biographia",    # imagination + suspension
                                                 # of disbelief
            "gutenberg-james-art-fiction",       # consciousness / character
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot / mythos
        ],
    },

    # ── Adventure ──
    "adventure": {
        "name": "Adventure",
        "aliases": [
            "adventure", "advneture", "adveture", "advanture",
            "swashbuckling", "quest",
        ],
        "corpora": [
            "gutenberg-20000-leagues", "gutenberg-princess-mars",
            "gutenberg-moby-dick", "gutenberg-riders-purple-sage",
            "gutenberg-treasure-island", "gutenberg-kidnapped",
            "gutenberg-king-solomons-mines",
            "gutenberg-mysterious-island",
            # Whole PG English — bookshelf-tagged Adventure.
            "hf-pg-tagged",
            # Pulp-era adventure (Burroughs, Haggard imitators)
            # well-represented in 1923-1965 PD American books.
            "hf-storytracer-us-pd",
        ],
        "authors": [
            "Robert Louis Stevenson", "Jules Verne",
            "Edgar Rice Burroughs", "Herman Melville",
            "H. Rider Haggard", "Alexandre Dumas",
        ],
        "comps": [
            "Treasure Island — Robert Louis Stevenson",
            "Kidnapped — Robert Louis Stevenson",
            "King Solomon's Mines — H. Rider Haggard",
            "20,000 Leagues Under the Sea — Jules Verne",
            "The Mysterious Island — Jules Verne",
            "A Princess of Mars — Edgar Rice Burroughs",
            "Moby-Dick — Herman Melville",
        ],
        "craft": [
            "gutenberg-rls-humble-remonstrance", # Stevenson on adventure
            "gutenberg-doyle-magic-door",        # Doyle on adventure influences
            "gutenberg-lang-adventures-books",   # Lang on heroic / quest
            "gutenberg-archer-playmaking",       # plot / pacing / climax
            "gutenberg-matthews-playwrights",    # tension + reveal
            "gutenberg-lubbock-craft",           # POV
            "gutenberg-hamilton-materials",      # comprehensive
            "gutenberg-poetics",                 # plot theory
        ],
    },

    # ── Literary ──
    "literary": {
        "name": "Literary Fiction",
        "aliases": [
            "literary", "litterary", "literery", "literay",
            "literary fiction", "litfic",
        ],
        "corpora": [
            "gutenberg-wuthering-heights", "gutenberg-moby-dick",
            "gutenberg-heart-of-darkness", "gutenberg-jane-eyre",
            "gutenberg-great-gatsby", "gutenberg-dubliners",
        ],
        "authors": [
            "Henry James", "Joseph Conrad", "Virginia Woolf",
            "Edith Wharton", "George Eliot", "Charles Dickens",
            "F. Scott Fitzgerald", "James Joyce",
        ],
        "comps": [
            "Heart of Darkness — Joseph Conrad",
            "Wuthering Heights — Emily Brontë",
            "Moby-Dick — Herman Melville",
            "The Great Gatsby — F. Scott Fitzgerald",
            "Dubliners — James Joyce",
        ],
        "craft": [
            "gutenberg-james-art-fiction",
            "gutenberg-besant-art-fiction",       # the lecture James answered
            "gutenberg-rls-humble-remonstrance",
            "gutenberg-twain-howto",
            "gutenberg-wharton-writing-fiction",  # Wharton on craft
            "gutenberg-trollope-autobiography",   # novelist's process
            "gutenberg-pater-appreciations",      # style / aesthetics
            "gutenberg-coleridge-biographia",     # imagination
            "gutenberg-longinus-sublime",         # elevated style
            "gutenberg-matthews-playwrights",     # dialogue / scene
            "gutenberg-lubbock-craft",            # POV / scene
            "gutenberg-on-art-of-writing",        # Quiller-Couch
            "gutenberg-hamilton-materials",       # comprehensive
            "gutenberg-poetics",                  # plot theory
            "gutenberg-elements-of-style",        # style
        ],
    },
}


def all_alias_pairs() -> List[tuple]:
    """Flat list of (alias, canonical_key) for fuzzy matching."""
    out = []
    for key, info in GENRES.items():
        for alias in info["aliases"]:
            out.append((alias, key))
    return out


def match_genres(text: str, fuzzy_cutoff: float = 0.78) -> List[str]:
    """Return canonical genre keys whose aliases appear in ``text``.

    Two passes:
        1. Substring match on multi-word and multi-character aliases —
           catches "science fiction", "ghost-story", "comedy of manners".
        2. Per-word fuzzy match against single-word aliases — catches
           misspellings like "horro", "westren", "thrler".

    The fuzzy cutoff is calibrated against ``difflib.SequenceMatcher``
    ratios — 0.78 catches one or two character typos on short words
    without producing nonsense matches (e.g. "happy" → "fantasy" stays
    below threshold).
    """
    if not text:
        return []
    text_lower = text.lower()
    matched: Set[str] = set()

    # Pass 1: substring containment
    for alias, key in all_alias_pairs():
        if alias in text_lower:
            matched.add(key)

    # Pass 2: fuzzy single-word matching for misspellings
    single_word_aliases = [a for a, _ in all_alias_pairs() if " " not in a]
    alias_to_key = {a: k for a, k in all_alias_pairs() if " " not in a}
    for word in _tokenize(text_lower):
        if len(word) < 4:
            continue  # too short to fuzzy-match meaningfully
        close = get_close_matches(
            word, single_word_aliases, n=1, cutoff=fuzzy_cutoff)
        if close:
            matched.add(alias_to_key[close[0]])

    return sorted(matched)


def _tokenize(text: str) -> List[str]:
    """Split on non-alphanum so "sci-fi" becomes ["sci", "fi"]."""
    import re
    return [t for t in re.split(r"[^a-z0-9]+", text) if t]


# ── Auto-derived ancillary genres (taxonomy overlap) ────────
#
# In addition to the per-entry ``ancillary`` field (explicit
# declarations the curator has made), the module derives ancillary
# pairs automatically by looking for overlap in the existing
# taxonomy fields. Two genres are considered ancillary when they
# share enough specific (non-catch-all) items in any of:
#
#   * authors  (>= 2 shared specific names)
#   * corpora  (>= 2 shared specific catalog ids)
#   * craft    (>= 3 shared specific craft texts)
#
# Specific = not in the catch-all sets below. ``hf-pg-tagged`` and
# ``hf-storytracer-us-pd`` are whole-shelf corpora cited under most
# genres; counting them would make every pair ancillary. Aristotle's
# Poetics + Lubbock + Hamilton are universal craft references for
# the same reason.
#
# Auto-derivation runs once at module load (``GENRES`` is static),
# stored in ``_DERIVED_ANCILLARIES``. Callers see the union of
# explicit + derived through :func:`ancillaries_for`.

_CATCHALL_CORPORA: Set[str] = {
    "hf-pg-tagged",          # whole Project Gutenberg English shelf
    "hf-storytracer-us-pd",  # whole 1923-1965 US PD pulp shelf
}

_CATCHALL_CRAFT: Set[str] = {
    # Cited under 10-11 of 11 genres — universal craft references.
    "gutenberg-poetics",            # Aristotle
    "gutenberg-lubbock-craft",      # Lubbock POV
    "gutenberg-hamilton-materials", # Hamilton's general survey
    # Cited under 5+ genres — broad-relevance dramaturgy /
    # narrative-defense essays, not genre-specific.
    "gutenberg-matthews-playwrights",
    "gutenberg-rls-humble-remonstrance",
}

_ANCILLARY_MIN_AUTHORS = 2
_ANCILLARY_MIN_CORPORA = 2
# Craft threshold is one higher than authors/corpora — craft texts
# tend to be cited more broadly (insightful essays travel across
# genre lines), so we want a stronger signal before declaring two
# genres ancillary purely on shared craft references. Authors and
# specific corpora are genre-bound, so a 2-item floor there is
# enough.
_ANCILLARY_MIN_CRAFT = 4


def _ancillary_evidence(a_key: str, b_key: str) -> Dict[str, List[str]]:
    """Return the shared specific items between two genres per field.

    Used both by the threshold check and by the UI to explain *why*
    two genres are considered ancillary ("share Frankenstein,
    Dracula, and Mary Shelley"). Catch-all corpora and universal
    craft references are stripped so the evidence is informative.
    """
    a = GENRES.get(a_key, {})
    b = GENRES.get(b_key, {})
    return {
        "authors": sorted(set(a.get("authors", []))
                          & set(b.get("authors", []))),
        "corpora": sorted((set(a.get("corpora", []))
                           & set(b.get("corpora", [])))
                          - _CATCHALL_CORPORA),
        "craft":   sorted((set(a.get("craft", []))
                           & set(b.get("craft", [])))
                          - _CATCHALL_CRAFT),
    }


def _meets_ancillary_threshold(evidence: Dict[str, List[str]]) -> bool:
    """ANY of the three signal counts crossing its threshold is
    enough — sibling genres often share strongly along one axis but
    not all (western/frontier share craft texts heavily but no
    authors; horror/gothic share authors and corpora but few craft
    references). Requiring all three would miss real siblings."""
    return (len(evidence.get("authors", [])) >= _ANCILLARY_MIN_AUTHORS
            or len(evidence.get("corpora", [])) >= _ANCILLARY_MIN_CORPORA
            or len(evidence.get("craft", []))   >= _ANCILLARY_MIN_CRAFT)


def _build_derived_ancillaries(
        ) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """Compute ``{key: {other_key: evidence}}`` for every pair of
    genres that meets the threshold. Symmetric — both sides of a
    pair record the same evidence. Run once at module load.
    """
    keys = list(GENRES.keys())
    derived: Dict[str, Dict[str, Dict[str, List[str]]]] = {
        k: {} for k in keys}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ev = _ancillary_evidence(a, b)
            if _meets_ancillary_threshold(ev):
                derived[a][b] = ev
                derived[b][a] = ev
    return derived


_DERIVED_ANCILLARIES = _build_derived_ancillaries()


def derived_ancillaries_for(key: str
                             ) -> Dict[str, Dict[str, List[str]]]:
    """Auto-derived sibling genres for ``key`` mapped to the shared-
    item evidence that earned them ancillary status.

    Returned as ``{other_key: {"authors": [...], "corpora": [...],
    "craft": [...]}}``. Empty for genres with no auto-derived
    siblings. The UI uses this to explain *why* a sibling appears
    in expansions ("frontier was added because western shares 3
    craft texts with it").
    """
    return dict(_DERIVED_ANCILLARIES.get(key, {}))


def genres_overlap(row_genre_str: str,
                   wanted_keys,
                   *,
                   fuzzy_cutoff: float = 0.85) -> bool:
    """Decide whether a row's genre tag overlaps the wanted set.

    The naive ``set(row.split(",")) & wanted`` check misses cases
    that are obviously the same genre to a human:

      * Composite tags — ``"gothic horror"`` should match a wanted
        ``"horror"`` (and ``"gothic"``); ``"psychological thriller"``
        should match ``"thriller"``.
      * Hyphenated variants — ``"sci-fi"`` should match ``"scifi"``.
      * Typos — ``"horor"`` should match ``"horror"``.

    Three strategies tried in order; first hit wins:

      1. **Token-set intersection** — split the row genre on
         ``,;/+`` separators, lowercase, compare against ``wanted``.
         Catches the canonical "horror, romance" case.
      2. **Substring contains** — for each wanted ≥4 chars, check
         if it appears inside any row token (or vice versa). The
         length floor blocks accidental matches like "sf" inside
         "stuff". Catches "gothic horror" → "horror".
      3. **Fuzzy ratio** — per-word ``SequenceMatcher`` ratio
         against the row tokens (and their hyphen-split sub-words)
         with cutoff ``fuzzy_cutoff`` (default 0.85). Catches
         "horor" → "horror" and "sci-fi" → "scifi".

    Returns False on empty inputs. Used by the export pipeline,
    the prompt-fit audit, and the genre-scope apply filter so all
    three see the same matching semantics.
    """
    if not row_genre_str or not wanted_keys:
        return False
    import re
    from difflib import SequenceMatcher

    row_lower = row_genre_str.lower()
    wanted_lower = {str(w).lower().strip()
                    for w in wanted_keys if str(w).strip()}
    if not wanted_lower:
        return False

    # Strategy 1: split on common separators, exact set intersection.
    row_tokens = {t.strip() for t in re.split(r"[,;/+]", row_lower)
                  if t.strip()}
    if row_tokens & wanted_lower:
        return True

    # Strategy 2: substring contains in either direction. Only fire
    # when the wanted key is long enough to avoid false positives
    # ("sf" inside "stuff"). All canonical genre keys are ≥5 chars
    # today; the floor of 4 is defensive.
    for w in wanted_lower:
        if len(w) < 4:
            continue
        for r in row_tokens:
            if w in r or r in w:
                return True

    # Strategy 3: per-word fuzzy ratio. Tokenise each row token
    # further on whitespace AND hyphens / underscores so a
    # "sci-fi adventure" → ["sci", "fi", "adventure"] worth of
    # candidates; "scifi" fuzzy-matches "sci" alone weakly but
    # matches the joined "sci-fi" cleanly via the no-split path
    # below.
    for r in row_tokens:
        candidates = {r}
        candidates.update(r.split())
        candidates.update(re.split(r"[-_]", r))
        for cand in candidates:
            if not cand:
                continue
            for w in wanted_lower:
                if (SequenceMatcher(None, w, cand).ratio()
                        >= fuzzy_cutoff):
                    return True
    return False


def ancillaries_for(key: str) -> List[str]:
    """Return sibling/ancillary genre keys for ``key``.

    Sibling genres share enough setting / vocabulary / craft DNA
    that filtering for one without the other loses signal. Sources
    in priority order (both contribute, deduplicated):

      * **Explicit** — entries' hand-coded ``ancillary`` field.
        Survives data changes; lets the curator declare a sibling
        even when the taxonomy doesn't yet have shared items.
      * **Derived** — pairs auto-discovered by overlap in shared
        authors / specific corpora / specific craft texts. See
        :func:`derived_ancillaries_for` for the evidence behind
        each derived pair.

    Returns the union as a sorted list. Empty when neither source
    has anything for the given key.
    """
    explicit = set(GENRES.get(key, {}).get("ancillary", []) or [])
    derived = set(_DERIVED_ANCILLARIES.get(key, {}).keys())
    return sorted(explicit | derived)


def expand_with_ancillaries(keys) -> Set[str]:
    """Return ``set(keys) ∪ ancillaries_for(every key)``.

    Used by the export pipeline's genre filter and the Fix Data
    tools' genre scope picker so a user who ticks "western" gets
    both western and frontier rows. Idempotent — running it on an
    already-expanded set is a no-op since the ancillary edges are
    declared symmetrically in the taxonomy.
    """
    out: Set[str] = set()
    for k in keys or []:
        out.add(k)
        out.update(ancillaries_for(k))
    return out


def info_for(key: str) -> Dict:
    """Return the full taxonomy entry for a canonical key, or empty dict."""
    return GENRES.get(key, {})


def display_name(key: str) -> str:
    return GENRES.get(key, {}).get("name", key.title())


def corpora_for(keys: List[str]) -> List[str]:
    """Union of corpus ids that match any of the given genre keys."""
    out: List[str] = []
    seen: Set[str] = set()
    for k in keys:
        for cid in GENRES.get(k, {}).get("corpora", []):
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def craft_corpora_for(keys: List[str]) -> List[str]:
    """Genre-specific writing-craft corpus ids for the given genres."""
    out: List[str] = []
    seen: Set[str] = set()
    for k in keys:
        for cid in GENRES.get(k, {}).get("craft", []):
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def authors_for(keys: List[str]) -> List[str]:
    """Union of touchstone authors for the given genres."""
    out: List[str] = []
    seen: Set[str] = set()
    for k in keys:
        for a in GENRES.get(k, {}).get("authors", []):
            if a not in seen:
                seen.add(a)
                out.append(a)
    return out


def comps_for(keys: List[str]) -> List[str]:
    """Union of comparable-title strings for the given genres."""
    out: List[str] = []
    seen: Set[str] = set()
    for k in keys:
        for c in GENRES.get(k, {}).get("comps", []):
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def all_keys() -> List[str]:
    """Canonical genre keys in display order."""
    return list(GENRES.keys())
