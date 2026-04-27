"""Curated catalog of public-domain / permissively-licensed text corpora
that ship with CreativeOS.

**Copyright stance:** Every entry here points at material that is
verified public domain (PD), Creative Commons CC0, or otherwise
permissively licensed. We never download copyrighted material on
behalf of the user. Custom user entries go through a license
attestation prompt in the UI.

The catalog is data-only; downloaders and adapters live in
``corpus_adapters.py`` and ``corpus_downloader.py`` so this module
stays import-safe (no network/disk side effects).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# License labels recognized as safe to auto-download. Everything else
# requires explicit user attestation in the UI.
LICENSE_OK = {
    "public_domain",
    "pd-us",            # public domain in the US (Project Gutenberg most books)
    "cc0",              # Creative Commons Zero
    "cc-by",            # Creative Commons Attribution
    "cc-by-sa",         # Creative Commons Attribution-ShareAlike
    "cc-by-nc",         # Creative Commons Non-Commercial (with caveats)
    "mit",
    "apache-2.0",
    "open-government",  # e.g. UK / US government text
}


@dataclass
class CorpusEntry:
    """One downloadable corpus."""
    id: str                                  # stable id (slug)
    name: str                                # display name
    description: str                         # one-line description
    url: str                                 # primary download URL or HF dataset id
    license: str                             # one of the LICENSE_OK labels (or "user-attested")
    license_url: str = ""                    # link to the license text / source page
    format: str = "txt"                      # txt | gutenberg | markdown | epub | llm | hf_dataset
    author: str = ""
    tags: List[str] = field(default_factory=list)
    size_hint_kb: int = 0
    # Source URL is shown to the user before downloading so they can
    # verify the license themselves.
    source_page: str = ""
    # Multi-narrative classification — used by the "build my model" agent
    # and the corpus library filter UI.
    purpose: str = "voice"      # voice | plot | both
    medium: str = "books"       # books | movies | tv | short | mixed
    narratives: int = 1         # rough # of distinct narratives (1 for single book,
                                # large for multi-story corpora)
    # HF-only knobs
    hf_split: str = "train"     # which split to load
    hf_config: str = ""         # config name when the dataset has
                                # multiple configurations (PAWS,
                                # GLUE-style suites, etc.). HF requires
                                # this for any dataset that exposes
                                # ``DatasetBuilder.BUILDER_CONFIGS``.
    hf_text_field: str = ""     # which column holds the text (auto-detected if blank)
    hf_prompt_field: str = ""   # for plot datasets: prompt column
    hf_completion_field: str = ""  # for plot datasets: completion/story column
    hf_max_rows: int = 5000     # cap rows pulled to keep ingest snappy
    # Per-row genre / title columns. When present, the downloader uses
    # the per-row value (fuzzy-matched against the canonical genre
    # taxonomy) instead of the entry-level tags, so a labeled dataset
    # like FareedKhan/1k_stories_100_genre actually fills the ``genre``
    # column on each row — which then makes the training-time genre
    # filter route them correctly.
    hf_genre_field: str = ""
    hf_title_field: str = ""
    # Optional row filter: only ingest rows where ``hf_filter_field``
    # equals ``hf_filter_value``. Useful for paraphrase datasets like
    # PAWS where label=1 means "paraphrase pair" and label=0 means
    # "non-paraphrase" — we only want the label=1 rows for SFT.
    hf_filter_field: str = ""
    hf_filter_value: str = ""


# ── Built-in catalog ────────────────────────────────────────────
#
# Every URL below is the official Project Gutenberg / Standard Ebooks
# / Wikisource page for a verified public-domain work. These were
# chosen for their genre breadth so users have meaningful starting
# corpora to fine-tune on.
#
# We URL-pin to specific txt files so if a host's listing pages change
# the downloader still works.

CATALOG: List[CorpusEntry] = [
    # ── Classic fiction (Project Gutenberg, US public domain) ──
    CorpusEntry(
        id="gutenberg-frankenstein",
        name="Frankenstein — Mary Shelley (1818)",
        description="Gothic / proto-science-fiction first-person prose.",
        url="https://www.gutenberg.org/cache/epub/84/pg84.txt",
        source_page="https://www.gutenberg.org/ebooks/84",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Mary Shelley",
        tags=["fiction", "gothic", "horror", "scifi", "classic"],
        size_hint_kb=448,
    ),
    CorpusEntry(
        id="gutenberg-dracula",
        name="Dracula — Bram Stoker (1897)",
        description="Epistolary horror, multiple narrators, period voice.",
        url="https://www.gutenberg.org/cache/epub/345/pg345.txt",
        source_page="https://www.gutenberg.org/ebooks/345",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Bram Stoker",
        tags=["fiction", "horror", "epistolary", "classic"],
        size_hint_kb=864,
    ),
    CorpusEntry(
        id="gutenberg-pride-and-prejudice",
        name="Pride and Prejudice — Jane Austen (1813)",
        description="Regency social comedy / romance, free-indirect style.",
        url="https://www.gutenberg.org/cache/epub/1342/pg1342.txt",
        source_page="https://www.gutenberg.org/ebooks/1342",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jane Austen",
        tags=["fiction", "romance", "comedy-of-manners", "classic"],
        size_hint_kb=716,
    ),
    CorpusEntry(
        id="gutenberg-sherlock",
        name="The Adventures of Sherlock Holmes — A. Conan Doyle (1892)",
        description="Mystery short stories, first-person Watson narration.",
        url="https://www.gutenberg.org/cache/epub/1661/pg1661.txt",
        source_page="https://www.gutenberg.org/ebooks/1661",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Arthur Conan Doyle",
        tags=["fiction", "mystery", "short-story", "classic"],
        size_hint_kb=580,
    ),
    CorpusEntry(
        id="gutenberg-time-machine",
        name="The Time Machine — H. G. Wells (1895)",
        description="Early science fiction, first-person frame narrative.",
        url="https://www.gutenberg.org/cache/epub/35/pg35.txt",
        source_page="https://www.gutenberg.org/ebooks/35",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. G. Wells",
        tags=["fiction", "scifi", "classic"],
        size_hint_kb=204,
    ),
    CorpusEntry(
        id="gutenberg-moby-dick",
        name="Moby-Dick — Herman Melville (1851)",
        description="Maximalist 19th-century prose, mixed registers.",
        url="https://www.gutenberg.org/cache/epub/2701/pg2701.txt",
        source_page="https://www.gutenberg.org/ebooks/2701",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Herman Melville",
        tags=["fiction", "adventure", "maximalist", "classic"],
        size_hint_kb=1232,
    ),
    CorpusEntry(
        id="gutenberg-wuthering-heights",
        name="Wuthering Heights — Emily Brontë (1847)",
        description="Gothic romance / family saga, frame narration.",
        url="https://www.gutenberg.org/cache/epub/768/pg768.txt",
        source_page="https://www.gutenberg.org/ebooks/768",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Emily Brontë",
        tags=["fiction", "romance", "gothic", "classic"],
        size_hint_kb=692,
    ),
    CorpusEntry(
        id="gutenberg-grimms",
        name="Grimms' Fairy Tales — Jacob & Wilhelm Grimm",
        description="Compact narrative arcs, oral-tradition cadence.",
        url="https://www.gutenberg.org/cache/epub/2591/pg2591.txt",
        source_page="https://www.gutenberg.org/ebooks/2591",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Brothers Grimm",
        tags=["fiction", "fairy-tale", "short-story", "classic"],
        size_hint_kb=560,
    ),

    # ── Sci-fi (Project Gutenberg) ──
    CorpusEntry(
        id="gutenberg-war-of-worlds",
        name="The War of the Worlds — H. G. Wells (1898)",
        description="Foundational alien-invasion sci-fi, first-person reportage.",
        url="https://www.gutenberg.org/cache/epub/36/pg36.txt",
        source_page="https://www.gutenberg.org/ebooks/36",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. G. Wells",
        tags=["fiction", "scifi", "invasion", "classic"],
        size_hint_kb=380,
    ),
    CorpusEntry(
        id="gutenberg-invisible-man",
        name="The Invisible Man — H. G. Wells (1897)",
        description="Sci-fi thriller, third-person, paranoid descent.",
        url="https://www.gutenberg.org/cache/epub/5230/pg5230.txt",
        source_page="https://www.gutenberg.org/ebooks/5230",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. G. Wells",
        tags=["fiction", "scifi", "thriller", "classic"],
        size_hint_kb=320,
    ),
    CorpusEntry(
        id="gutenberg-20000-leagues",
        name="Twenty Thousand Leagues Under the Sea — Jules Verne (1870)",
        description="Adventure sci-fi, journal narration, descriptive prose.",
        url="https://www.gutenberg.org/cache/epub/164/pg164.txt",
        source_page="https://www.gutenberg.org/ebooks/164",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jules Verne",
        tags=["fiction", "scifi", "adventure", "classic"],
        size_hint_kb=720,
    ),
    CorpusEntry(
        id="gutenberg-princess-mars",
        name="A Princess of Mars — Edgar Rice Burroughs (1912)",
        description="Planetary romance / pulp sci-fi, first-person Barsoom.",
        url="https://www.gutenberg.org/cache/epub/62/pg62.txt",
        source_page="https://www.gutenberg.org/ebooks/62",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edgar Rice Burroughs",
        tags=["fiction", "scifi", "pulp", "adventure", "classic"],
        size_hint_kb=420,
    ),

    # ── Western (Project Gutenberg) ──
    CorpusEntry(
        id="gutenberg-virginian",
        name="The Virginian — Owen Wister (1902)",
        description="Founding-text Western; cowboy honor code, frontier romance.",
        url="https://www.gutenberg.org/cache/epub/1298/pg1298.txt",
        source_page="https://www.gutenberg.org/ebooks/1298",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Owen Wister",
        tags=["fiction", "western", "frontier", "classic"],
        size_hint_kb=720,
    ),
    CorpusEntry(
        id="gutenberg-riders-purple-sage",
        name="Riders of the Purple Sage — Zane Grey (1912)",
        description="Archetypal Western action prose, Mormon-frontier romance.",
        url="https://www.gutenberg.org/cache/epub/1300/pg1300.txt",
        source_page="https://www.gutenberg.org/ebooks/1300",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Zane Grey",
        tags=["fiction", "western", "adventure", "classic"],
        size_hint_kb=560,
    ),
    CorpusEntry(
        id="gutenberg-log-of-cowboy",
        name="The Log of a Cowboy — Andy Adams (1903)",
        description="Realistic cattle-drive Western, deadpan first-person.",
        url="https://www.gutenberg.org/cache/epub/5009/pg5009.txt",
        source_page="https://www.gutenberg.org/ebooks/5009",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Andy Adams",
        tags=["fiction", "western", "cowboy", "classic"],
        size_hint_kb=520,
    ),
    CorpusEntry(
        id="gutenberg-arizona-nights",
        name="Arizona Nights — Stewart Edward White (1907)",
        description="Frontier short stories; campfire-yarn cadence.",
        url="https://www.gutenberg.org/cache/epub/6183/pg6183.txt",
        source_page="https://www.gutenberg.org/ebooks/6183",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Stewart Edward White",
        tags=["fiction", "western", "short-story", "classic"],
        size_hint_kb=440,
    ),
    CorpusEntry(
        id="gutenberg-luck-roaring-camp",
        name="The Luck of Roaring Camp and Other Tales — Bret Harte (1870)",
        description="Founding regional Western; California gold-rush "
                    "camps, vernacular dialogue, sentimental realism.",
        url="https://www.gutenberg.org/cache/epub/6373/pg6373.txt",
        source_page="https://www.gutenberg.org/ebooks/6373",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Bret Harte",
        tags=["fiction", "western", "short-story", "classic"],
        size_hint_kb=782,
    ),
    CorpusEntry(
        id="gutenberg-chip-flying-u",
        name="Chip, of the Flying U — B. M. Bower (1906)",
        description="Ranch romance; the first major Western by a woman, "
                    "ensemble cowboy cast, gentle humor.",
        url="https://www.gutenberg.org/cache/epub/9267/pg9267.txt",
        source_page="https://www.gutenberg.org/ebooks/9267",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="B. M. Bower",
        tags=["fiction", "western", "ranch", "classic"],
        size_hint_kb=257,
    ),
    CorpusEntry(
        id="gutenberg-untamed",
        name="The Untamed — Max Brand (1919)",
        description="Pulp Western archetype; lyrical chase narrative, "
                    "the Whistling Dan Barry mythos.",
        url="https://www.gutenberg.org/cache/epub/10886/pg10886.txt",
        source_page="https://www.gutenberg.org/ebooks/10886",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Max Brand",
        tags=["fiction", "western", "pulp", "classic"],
        size_hint_kb=409,
    ),
    CorpusEntry(
        id="gutenberg-bar-20",
        name="The Man from Bar-20 — Clarence E. Mulford (1918)",
        description="Hopalong Cassidy series; foundational cowboy "
                    "ensemble Western, terse action prose.",
        url="https://www.gutenberg.org/cache/epub/56154/pg56154.txt",
        source_page="https://www.gutenberg.org/ebooks/56154",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Clarence E. Mulford",
        tags=["fiction", "western", "cowboy", "classic"],
        size_hint_kb=433,
    ),
    CorpusEntry(
        id="gutenberg-main-travelled-roads",
        name="Main-Travelled Roads — Hamlin Garland (1891)",
        description="Naturalist plains realism; Midwestern farm-life "
                    "stories, gritty agrarian Western.",
        url="https://www.gutenberg.org/cache/epub/2809/pg2809.txt",
        source_page="https://www.gutenberg.org/ebooks/2809",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Hamlin Garland",
        tags=["fiction", "western", "frontier", "literary", "classic"],
        size_hint_kb=508,
    ),

    # ── Frontier fiction (Project Gutenberg) ──
    # Broader than "western" cowboy-Old-West: colonial wilderness,
    # Klondike survival, prairie homesteading, frontier memoir.
    CorpusEntry(
        id="gutenberg-mohicans",
        name="The Last of the Mohicans — James Fenimore Cooper (1826)",
        description="Colonial-frontier wilderness adventure; founding "
                    "Leatherstocking prose, French and Indian War.",
        url="https://www.gutenberg.org/cache/epub/940/pg940.txt",
        source_page="https://www.gutenberg.org/ebooks/940",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="James Fenimore Cooper",
        tags=["fiction", "frontier", "adventure", "wilderness", "classic"],
        size_hint_kb=900,
    ),
    CorpusEntry(
        id="gutenberg-deerslayer",
        name="The Deerslayer — James Fenimore Cooper (1841)",
        description="Leatherstocking origin story; lake-country frontier, "
                    "wilderness ethics in long contemplative prose.",
        url="https://www.gutenberg.org/cache/epub/3285/pg3285.txt",
        source_page="https://www.gutenberg.org/ebooks/3285",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="James Fenimore Cooper",
        tags=["fiction", "frontier", "adventure", "wilderness", "classic"],
        size_hint_kb=1100,
    ),
    CorpusEntry(
        id="gutenberg-call-of-wild",
        name="The Call of the Wild — Jack London (1903)",
        description="Klondike survival; sparse muscular prose, frontier "
                    "naturalism from a dog's POV.",
        url="https://www.gutenberg.org/cache/epub/215/pg215.txt",
        source_page="https://www.gutenberg.org/ebooks/215",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jack London",
        tags=["fiction", "frontier", "wilderness", "adventure", "classic"],
        size_hint_kb=190,
    ),
    CorpusEntry(
        id="gutenberg-white-fang",
        name="White Fang — Jack London (1906)",
        description="Yukon wilderness from wolfdog POV; spare frontier "
                    "naturalism, survival prose.",
        url="https://www.gutenberg.org/cache/epub/910/pg910.txt",
        source_page="https://www.gutenberg.org/ebooks/910",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jack London",
        tags=["fiction", "frontier", "wilderness", "adventure", "classic"],
        size_hint_kb=380,
    ),
    CorpusEntry(
        id="gutenberg-my-antonia",
        name="My Ántonia — Willa Cather (1918)",
        description="Nebraska prairie homesteading; lyrical frontier "
                    "literary realism, immigrant pioneer life.",
        url="https://www.gutenberg.org/cache/epub/242/pg242.txt",
        source_page="https://www.gutenberg.org/ebooks/242",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Willa Cather",
        tags=["fiction", "frontier", "literary", "prairie", "classic"],
        size_hint_kb=520,
    ),
    CorpusEntry(
        id="gutenberg-roughing-it",
        name="Roughing It — Mark Twain (1872)",
        description="Frontier memoir of Nevada/California silver-rush "
                    "years; comic vernacular, tall-tale cadence.",
        url="https://www.gutenberg.org/cache/epub/3177/pg3177.txt",
        source_page="https://www.gutenberg.org/ebooks/3177",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Mark Twain",
        tags=["fiction", "frontier", "western", "memoir", "comedy", "classic"],
        size_hint_kb=900,
    ),

    # ── Horror / weird fiction (Project Gutenberg) ──
    CorpusEntry(
        id="gutenberg-poe-tales",
        name="The Works of Edgar Allan Poe — Volume 1 (1903 ed.)",
        description="Tales of mystery and horror; founding atmospheric prose.",
        url="https://www.gutenberg.org/cache/epub/2147/pg2147.txt",
        source_page="https://www.gutenberg.org/ebooks/2147",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edgar Allan Poe",
        tags=["fiction", "horror", "short-story", "classic"],
        size_hint_kb=580,
    ),
    CorpusEntry(
        id="gutenberg-king-in-yellow",
        name="The King in Yellow — Robert W. Chambers (1895)",
        description="Linked weird-fiction stories; cosmic dread, art-world horror.",
        url="https://www.gutenberg.org/cache/epub/8492/pg8492.txt",
        source_page="https://www.gutenberg.org/ebooks/8492",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Robert W. Chambers",
        tags=["fiction", "horror", "weird", "short-story", "classic"],
        size_hint_kb=360,
    ),
    CorpusEntry(
        id="gutenberg-carmilla",
        name="Carmilla — J. Sheridan Le Fanu (1872)",
        description="Vampire novella; pre-Dracula gothic, first-person memoir.",
        url="https://www.gutenberg.org/cache/epub/10007/pg10007.txt",
        source_page="https://www.gutenberg.org/ebooks/10007",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="J. Sheridan Le Fanu",
        tags=["fiction", "horror", "gothic", "vampire", "classic"],
        size_hint_kb=180,
    ),
    CorpusEntry(
        id="gutenberg-great-god-pan",
        name="The Great God Pan — Arthur Machen (1894)",
        description="Decadent horror novella; major influence on Lovecraft.",
        url="https://www.gutenberg.org/cache/epub/389/pg389.txt",
        source_page="https://www.gutenberg.org/ebooks/389",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Arthur Machen",
        tags=["fiction", "horror", "weird", "classic"],
        size_hint_kb=140,
    ),
    CorpusEntry(
        id="gutenberg-mr-james-ghost",
        name="Ghost Stories of an Antiquary — M. R. James (1904)",
        description="Restrained academic-ghost-story prose; the M. R. James voice.",
        url="https://www.gutenberg.org/cache/epub/8486/pg8486.txt",
        source_page="https://www.gutenberg.org/ebooks/8486",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="M. R. James",
        tags=["fiction", "horror", "ghost-story", "short-story", "classic"],
        size_hint_kb=320,
    ),
    CorpusEntry(
        id="gutenberg-willows",
        name="The Willows — Algernon Blackwood (1907)",
        description="Weird-fiction landmark — Lovecraft called it the "
                    "finest weird tale ever written; Danube wilderness "
                    "horror, slow atmospheric dread.",
        url="https://www.gutenberg.org/cache/epub/11438/pg11438.txt",
        source_page="https://www.gutenberg.org/ebooks/11438",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Algernon Blackwood",
        tags=["fiction", "horror", "weird", "wilderness", "classic"],
        size_hint_kb=130,
    ),
    CorpusEntry(
        id="gutenberg-house-borderland",
        name="The House on the Borderland — William Hope Hodgson (1908)",
        description="Cosmic-horror precursor; isolated house on the "
                    "edge of dimensions, a major Lovecraft influence.",
        url="https://www.gutenberg.org/cache/epub/10002/pg10002.txt",
        source_page="https://www.gutenberg.org/ebooks/10002",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="William Hope Hodgson",
        tags=["fiction", "horror", "weird", "cosmic", "classic"],
        size_hint_kb=298,
    ),
    CorpusEntry(
        id="gutenberg-hauntings",
        name="Hauntings — Vernon Lee (1890)",
        description="Aesthetic-decadent ghost stories; psychological "
                    "supernatural, lush late-Victorian prose.",
        url="https://www.gutenberg.org/cache/epub/9956/pg9956.txt",
        source_page="https://www.gutenberg.org/ebooks/9956",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Vernon Lee",
        tags=["fiction", "horror", "ghost-story", "decadent", "classic"],
        size_hint_kb=337,
    ),
    CorpusEntry(
        id="gutenberg-turn-of-screw",
        name="The Turn of the Screw — Henry James (1898)",
        description="Definitive psychological ghost story; unreliable "
                    "governess narrator, ambiguous evil.",
        url="https://www.gutenberg.org/cache/epub/209/pg209.txt",
        source_page="https://www.gutenberg.org/ebooks/209",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Henry James",
        tags=["fiction", "horror", "ghost-story", "psychological", "classic"],
        size_hint_kb=253,
    ),
    CorpusEntry(
        id="gutenberg-beetle",
        name="The Beetle — Richard Marsh (1897)",
        description="Egyptian-occult horror; multi-narrator gothic that "
                    "outsold Dracula on its release.",
        url="https://www.gutenberg.org/cache/epub/5164/pg5164.txt",
        source_page="https://www.gutenberg.org/ebooks/5164",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Richard Marsh",
        tags=["fiction", "horror", "gothic", "occult", "classic"],
        size_hint_kb=641,
    ),
    CorpusEntry(
        id="gutenberg-wieland",
        name="Wieland — Charles Brockden Brown (1798)",
        description="Founding American gothic; ventriloquism, religious "
                    "mania, frontier-house horror.",
        url="https://www.gutenberg.org/cache/epub/792/pg792.txt",
        source_page="https://www.gutenberg.org/ebooks/792",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Charles Brockden Brown",
        tags=["fiction", "horror", "gothic", "american", "classic"],
        size_hint_kb=489,
    ),

    # ── Thriller / suspense (Project Gutenberg) ──
    CorpusEntry(
        id="gutenberg-thirty-nine-steps",
        name="The Thirty-Nine Steps — John Buchan (1915)",
        description="Pioneering man-on-the-run spy thriller, first-person.",
        url="https://www.gutenberg.org/cache/epub/558/pg558.txt",
        source_page="https://www.gutenberg.org/ebooks/558",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="John Buchan",
        tags=["fiction", "thriller", "spy", "classic"],
        size_hint_kb=240,
    ),
    CorpusEntry(
        id="gutenberg-man-who-was-thursday",
        name="The Man Who Was Thursday — G. K. Chesterton (1908)",
        description="Metaphysical anarchist thriller, dialogue-driven prose.",
        url="https://www.gutenberg.org/cache/epub/1695/pg1695.txt",
        source_page="https://www.gutenberg.org/ebooks/1695",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="G. K. Chesterton",
        tags=["fiction", "thriller", "philosophical", "classic"],
        size_hint_kb=320,
    ),
    CorpusEntry(
        id="gutenberg-moonstone",
        name="The Moonstone — Wilkie Collins (1868)",
        description="Multi-narrator detective thriller; foundational sensation novel.",
        url="https://www.gutenberg.org/cache/epub/155/pg155.txt",
        source_page="https://www.gutenberg.org/ebooks/155",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Wilkie Collins",
        tags=["fiction", "thriller", "mystery", "epistolary", "classic"],
        size_hint_kb=1100,
    ),
    CorpusEntry(
        id="gutenberg-heart-of-darkness",
        name="Heart of Darkness — Joseph Conrad (1899)",
        description="Frame-narrated psychological thriller; dense atmospheric prose.",
        url="https://www.gutenberg.org/cache/epub/219/pg219.txt",
        source_page="https://www.gutenberg.org/ebooks/219",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Joseph Conrad",
        tags=["fiction", "thriller", "literary", "classic"],
        size_hint_kb=240,
    ),

    # ── Romance (additional Project Gutenberg titles) ──
    CorpusEntry(
        id="gutenberg-jane-eyre",
        name="Jane Eyre — Charlotte Brontë (1847)",
        description="First-person Bildungsroman + gothic romance.",
        url="https://www.gutenberg.org/cache/epub/1260/pg1260.txt",
        source_page="https://www.gutenberg.org/ebooks/1260",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Charlotte Brontë",
        tags=["fiction", "romance", "gothic", "classic"],
        size_hint_kb=1100,
    ),
    CorpusEntry(
        id="gutenberg-sense-sensibility",
        name="Sense and Sensibility — Jane Austen (1811)",
        description="Regency romance + family drama; free-indirect style.",
        url="https://www.gutenberg.org/cache/epub/161/pg161.txt",
        source_page="https://www.gutenberg.org/ebooks/161",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jane Austen",
        tags=["fiction", "romance", "comedy-of-manners", "classic"],
        size_hint_kb=620,
    ),
    CorpusEntry(
        id="gutenberg-persuasion",
        name="Persuasion — Jane Austen (1817)",
        description="Mature, melancholy late-Austen romance; close third-person.",
        url="https://www.gutenberg.org/cache/epub/105/pg105.txt",
        source_page="https://www.gutenberg.org/ebooks/105",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jane Austen",
        tags=["fiction", "romance", "classic"],
        size_hint_kb=480,
    ),
    CorpusEntry(
        id="gutenberg-tenant-wildfell-hall",
        name="The Tenant of Wildfell Hall — Anne Brontë (1848)",
        description="Epistolary + diary romance with social criticism.",
        url="https://www.gutenberg.org/cache/epub/969/pg969.txt",
        source_page="https://www.gutenberg.org/ebooks/969",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Anne Brontë",
        tags=["fiction", "romance", "epistolary", "classic"],
        size_hint_kb=820,
    ),
    CorpusEntry(
        id="gutenberg-far-from-madding-crowd",
        name="Far from the Madding Crowd — Thomas Hardy (1874)",
        description="Pastoral love-triangle romance; Wessex landscape, "
                    "Bathsheba Everdene, lyrical Victorian rural prose.",
        url="https://www.gutenberg.org/cache/epub/107/pg107.txt",
        source_page="https://www.gutenberg.org/ebooks/107",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Thomas Hardy",
        tags=["fiction", "romance", "literary", "pastoral", "classic"],
        size_hint_kb=810,
    ),
    CorpusEntry(
        id="gutenberg-tess",
        name="Tess of the d'Urbervilles — Thomas Hardy (1891)",
        description="Tragic romance; fated love, Victorian sexual "
                    "morality, Hardy's lyrical landscape prose.",
        url="https://www.gutenberg.org/cache/epub/110/pg110.txt",
        source_page="https://www.gutenberg.org/ebooks/110",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Thomas Hardy",
        tags=["fiction", "romance", "literary", "tragedy", "classic"],
        size_hint_kb=874,
    ),
    CorpusEntry(
        id="gutenberg-middlemarch",
        name="Middlemarch — George Eliot (1871)",
        description="Provincial-life ensemble romance; Dorothea + "
                    "Casaubon + Lydgate + Rosamond; Victorian masterwork.",
        url="https://www.gutenberg.org/cache/epub/145/pg145.txt",
        source_page="https://www.gutenberg.org/ebooks/145",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="George Eliot",
        tags=["fiction", "romance", "literary", "ensemble", "classic"],
        size_hint_kb=1821,
    ),
    CorpusEntry(
        id="gutenberg-age-of-innocence",
        name="The Age of Innocence — Edith Wharton (1920)",
        description="Gilded-Age society romance; New York elite, "
                    "doomed love, ironic precise prose. Pulitzer 1921.",
        url="https://www.gutenberg.org/cache/epub/541/pg541.txt",
        source_page="https://www.gutenberg.org/ebooks/541",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edith Wharton",
        tags=["fiction", "romance", "literary", "society", "classic"],
        size_hint_kb=595,
    ),
    CorpusEntry(
        id="gutenberg-house-of-mirth",
        name="The House of Mirth — Edith Wharton (1905)",
        description="Tragic society romance; Lily Bart's fall through "
                    "Gilded-Age New York, Wharton's social-satire prose.",
        url="https://www.gutenberg.org/cache/epub/284/pg284.txt",
        source_page="https://www.gutenberg.org/ebooks/284",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edith Wharton",
        tags=["fiction", "romance", "literary", "society", "tragedy", "classic"],
        size_hint_kb=759,
    ),
    CorpusEntry(
        id="gutenberg-emma",
        name="Emma — Jane Austen (1815)",
        description="Comic matchmaking romance; free-indirect-discourse "
                    "showpiece, Austen's most layered prose.",
        url="https://www.gutenberg.org/cache/epub/158/pg158.txt",
        source_page="https://www.gutenberg.org/ebooks/158",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jane Austen",
        tags=["fiction", "romance", "comedy", "regency", "classic"],
        size_hint_kb=911,
    ),
    CorpusEntry(
        id="gutenberg-anne-green-gables",
        name="Anne of Green Gables — L. M. Montgomery (1908)",
        description="Coming-of-age romance; Prince Edward Island farm "
                    "life, Anne and Gilbert, warm Edwardian prose.",
        url="https://www.gutenberg.org/cache/epub/45/pg45.txt",
        source_page="https://www.gutenberg.org/ebooks/45",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="L. M. Montgomery",
        tags=["fiction", "romance", "coming-of-age", "classic"],
        size_hint_kb=580,
    ),

    # ── Writing craft (informational, public domain) ──
    CorpusEntry(
        id="gutenberg-poetics",
        name="Poetics — Aristotle (trans. Butcher)",
        description="Foundational plot/structure theory.",
        url="https://www.gutenberg.org/cache/epub/1974/pg1974.txt",
        source_page="https://www.gutenberg.org/ebooks/1974",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Aristotle (trans. S. H. Butcher)",
        tags=["nonfiction", "craft", "plot", "theory"],
        size_hint_kb=200,
    ),
    CorpusEntry(
        id="gutenberg-elements-of-style",
        name="The Elements of Style — Strunk (1918)",
        description="Concise prose-style rules; the Strunk original.",
        url="https://www.gutenberg.org/cache/epub/37134/pg37134.txt",
        source_page="https://www.gutenberg.org/ebooks/37134",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="William Strunk Jr.",
        tags=["nonfiction", "craft", "style", "writing-guide"],
        size_hint_kb=80,
    ),
    CorpusEntry(
        id="gutenberg-on-art-of-writing",
        name="On the Art of Writing — A. Quiller-Couch (1916)",
        description="Cambridge lectures on prose, style, and clarity.",
        url="https://www.gutenberg.org/cache/epub/38014/pg38014.txt",
        source_page="https://www.gutenberg.org/ebooks/38014",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Arthur Quiller-Couch",
        tags=["nonfiction", "craft", "style", "writing-guide"],
        size_hint_kb=440,
    ),
    CorpusEntry(
        id="gutenberg-poe-philosophy",
        name="The Philosophy of Composition — Edgar Allan Poe (1846)",
        description="Poe's essay on writing 'The Raven'; foundational "
                    "horror/mystery craft theory.",
        url="https://www.gutenberg.org/cache/epub/55749/pg55749.txt",
        source_page="https://www.gutenberg.org/ebooks/55749",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edgar Allan Poe",
        tags=["nonfiction", "craft", "horror", "mystery", "writing-guide"],
        size_hint_kb=40,
    ),
    CorpusEntry(
        id="gutenberg-james-art-fiction",
        name="The Art of Fiction — Henry James (1884)",
        description="James on novel-writing as a serious art; literary "
                    "fiction craft.",
        url="https://www.gutenberg.org/cache/epub/40987/pg40987.txt",
        source_page="https://www.gutenberg.org/ebooks/40987",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Henry James",
        tags=["nonfiction", "craft", "literary", "writing-guide"],
        size_hint_kb=80,
    ),
    CorpusEntry(
        id="gutenberg-twain-cooper",
        name="Fenimore Cooper's Literary Offences — Mark Twain (1895)",
        description="Twain's scathing 18-rule essay on what NOT to do "
                    "in fiction. Genre-agnostic but heavily Western-flavored.",
        url="https://www.gutenberg.org/cache/epub/3172/pg3172.txt",
        source_page="https://www.gutenberg.org/ebooks/3172",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Mark Twain",
        tags=["nonfiction", "craft", "western", "writing-guide"],
        size_hint_kb=40,
    ),
    CorpusEntry(
        id="gutenberg-rls-humble-remonstrance",
        name="A Humble Remonstrance — Robert Louis Stevenson (1884)",
        description="Stevenson's reply to Henry James — argues fiction "
                    "is artifice, not realism. Adventure / romance craft.",
        url="https://www.gutenberg.org/cache/epub/30/pg30.txt",
        source_page="https://www.gutenberg.org/ebooks/30",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Robert Louis Stevenson",
        tags=["nonfiction", "craft", "adventure", "literary",
              "writing-guide"],
        size_hint_kb=200,
    ),
    CorpusEntry(
        id="gutenberg-lovecraft-horror",
        name="Supernatural Horror in Literature — H. P. Lovecraft (1927)",
        description="Lovecraft's history + theory of weird fiction; the "
                    "essential horror/weird-fiction craft text.",
        url="https://www.gutenberg.org/cache/epub/74058/pg74058.txt",
        source_page="https://www.gutenberg.org/ebooks/74058",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. P. Lovecraft",
        tags=["nonfiction", "craft", "horror", "weird", "writing-guide"],
        size_hint_kb=240,
    ),
    CorpusEntry(
        id="gutenberg-twain-howto",
        name="How to Tell a Story — Mark Twain (1897)",
        description="Twain's punchy primer on oral storytelling; the "
                    "comic / humorous-fiction craft text.",
        url="https://www.gutenberg.org/cache/epub/3250/pg3250.txt",
        source_page="https://www.gutenberg.org/ebooks/3250",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Mark Twain",
        tags=["nonfiction", "craft", "comedy", "writing-guide"],
        size_hint_kb=120,
    ),
    CorpusEntry(
        id="gutenberg-wharton-writing-fiction",
        name="The Writing of Fiction — Edith Wharton (1925)",
        description="Wharton on craft: structure, character, dialogue, "
                    "the art of the novel from a working novelist. "
                    "The romance / literary-fiction craft text.",
        url="https://www.gutenberg.org/cache/epub/72446/pg72446.txt",
        source_page="https://www.gutenberg.org/ebooks/72446",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edith Wharton",
        tags=["nonfiction", "craft", "romance", "literary", "writing-guide"],
        size_hint_kb=184,
    ),
    CorpusEntry(
        id="gutenberg-lubbock-craft",
        name="The Craft of Fiction — Percy Lubbock (1921)",
        description="Foundational POV theory; scene vs. summary, showing "
                    "vs. telling. Source for nearly every later "
                    "fiction-craft book — universal applicability.",
        url="https://www.gutenberg.org/cache/epub/18961/pg18961.txt",
        source_page="https://www.gutenberg.org/ebooks/18961",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Percy Lubbock",
        tags=["nonfiction", "craft", "pov", "structure", "writing-guide"],
        size_hint_kb=412,
    ),
    CorpusEntry(
        id="gutenberg-archer-playmaking",
        name="Play-Making: A Manual of Craftsmanship — William Archer (1912)",
        description="Plot construction, scene economy, dialogue craft, "
                    "exposition, climax. Written for drama but cited "
                    "across fiction-craft tradition for plot/structure.",
        url="https://www.gutenberg.org/cache/epub/10865/pg10865.txt",
        source_page="https://www.gutenberg.org/ebooks/10865",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="William Archer",
        tags=["nonfiction", "craft", "plot", "structure", "dialogue", "writing-guide"],
        size_hint_kb=597,
    ),
    CorpusEntry(
        id="gutenberg-hamilton-materials",
        name="Materials and Methods of Fiction — Clayton M. Hamilton (1908)",
        description="Comprehensive fiction-craft textbook; structure, "
                    "characterization, setting, plot. Survey of how "
                    "professional novelists actually build a book.",
        url="https://www.gutenberg.org/cache/epub/30776/pg30776.txt",
        source_page="https://www.gutenberg.org/ebooks/30776",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Clayton Meeker Hamilton",
        tags=["nonfiction", "craft", "structure", "character", "writing-guide"],
        size_hint_kb=443,
    ),
    CorpusEntry(
        id="gutenberg-macdonald-orts",
        name="A Dish of Orts — George MacDonald (1893)",
        description="Includes 'The Fantastic Imagination' — the founding "
                    "essay on fantasy as a literary mode, plus pieces "
                    "on imagination and the supernatural in fiction.",
        url="https://www.gutenberg.org/cache/epub/9393/pg9393.txt",
        source_page="https://www.gutenberg.org/ebooks/9393",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="George MacDonald",
        tags=["nonfiction", "craft", "fantasy", "imagination", "writing-guide"],
        size_hint_kb=517,
    ),
    CorpusEntry(
        id="gutenberg-machen-hieroglyphics",
        name="Hieroglyphics — Arthur Machen (1902)",
        description="Machen's literary philosophy of weird/ecstatic "
                    "fiction; what makes a piece of writing 'fine.' "
                    "Essential horror/weird craft companion to Lovecraft.",
        url="https://www.gutenberg.org/cache/epub/40241/pg40241.txt",
        source_page="https://www.gutenberg.org/ebooks/40241",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Arthur Machen",
        tags=["nonfiction", "craft", "horror", "weird", "literary", "writing-guide"],
        size_hint_kb=271,
    ),
    # ── Universal craft (added 2nd round) ──
    CorpusEntry(
        id="gutenberg-coleridge-biographia",
        name="Biographia Literaria — Samuel Taylor Coleridge (1817)",
        description="Origin of 'willing suspension of disbelief'; theory "
                    "of imagination as primary/secondary; foundational on "
                    "how readers enter fictional worlds.",
        url="https://www.gutenberg.org/cache/epub/6081/pg6081.txt",
        source_page="https://www.gutenberg.org/ebooks/6081",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Samuel Taylor Coleridge",
        tags=["nonfiction", "craft", "imagination", "theory", "writing-guide"],
        size_hint_kb=839,
    ),
    CorpusEntry(
        id="gutenberg-longinus-sublime",
        name="On the Sublime — Longinus (1st century, trans. Roberts)",
        description="The definitive ancient treatise on elevated style "
                    "and emotional impact; what makes prose stir the "
                    "reader. Source for every 'voice' theory since.",
        url="https://www.gutenberg.org/cache/epub/17957/pg17957.txt",
        source_page="https://www.gutenberg.org/ebooks/17957",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Longinus (trans. W. Rhys Roberts)",
        tags=["nonfiction", "craft", "style", "voice", "theory", "writing-guide"],
        size_hint_kb=197,
    ),
    CorpusEntry(
        id="gutenberg-matthews-playwrights",
        name="Playwrights on Playmaking — Brander Matthews (1923)",
        description="Working dramatists discussing scene construction, "
                    "dialogue, exposition, climax. Cited across 20th-c "
                    "fiction-craft tradition for character + dialogue.",
        url="https://www.gutenberg.org/cache/epub/72661/pg72661.txt",
        source_page="https://www.gutenberg.org/ebooks/72661",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Brander Matthews",
        tags=["nonfiction", "craft", "dialogue", "structure", "writing-guide"],
        size_hint_kb=386,
    ),
    CorpusEntry(
        id="gutenberg-besant-art-fiction",
        name="The Art of Fiction — Walter Besant (1884)",
        description="The lecture that prompted Henry James's response "
                    "of the same title; foundational pairing on the "
                    "novel as a serious art form.",
        url="https://www.gutenberg.org/cache/epub/76460/pg76460.txt",
        source_page="https://www.gutenberg.org/ebooks/76460",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Walter Besant",
        tags=["nonfiction", "craft", "novel", "theory", "writing-guide"],
        size_hint_kb=85,
    ),
    # ── Genre-specific craft / criticism ──
    CorpusEntry(
        id="gutenberg-trollope-autobiography",
        name="An Autobiography — Anthony Trollope (1883)",
        description="Trollope on his actual writing process: discipline, "
                    "word counts, character voice, plot, working "
                    "habits. The novelist's-process classic.",
        url="https://www.gutenberg.org/cache/epub/5978/pg5978.txt",
        source_page="https://www.gutenberg.org/ebooks/5978",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Anthony Trollope",
        tags=["nonfiction", "craft", "romance", "literary", "process", "writing-guide"],
        size_hint_kb=559,
    ),
    CorpusEntry(
        id="gutenberg-pater-appreciations",
        name="Appreciations, with an Essay on Style — Walter Pater (1889)",
        description="Pater's 'Style' essay — definitive on prose-as-art, "
                    "word selection, sentence shape; companion essays "
                    "on Wordsworth, Coleridge, Lamb, Browne.",
        url="https://www.gutenberg.org/cache/epub/4037/pg4037.txt",
        source_page="https://www.gutenberg.org/ebooks/4037",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Walter Pater",
        tags=["nonfiction", "craft", "style", "literary", "writing-guide"],
        size_hint_kb=390,
    ),
    CorpusEntry(
        id="gutenberg-doyle-magic-door",
        name="Through the Magic Door — Arthur Conan Doyle (1907)",
        description="Doyle on the books that shaped him as a writer; "
                    "essays on Poe, Stevenson, Macaulay, sea-tales, "
                    "historical romance. Mystery + adventure influences.",
        url="https://www.gutenberg.org/cache/epub/5317/pg5317.txt",
        source_page="https://www.gutenberg.org/ebooks/5317",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Arthur Conan Doyle",
        tags=["nonfiction", "craft", "mystery", "adventure", "writing-guide"],
        size_hint_kb=280,
    ),
    CorpusEntry(
        id="gutenberg-wells-discovery-future",
        name="The Discovery of the Future — H. G. Wells (1902)",
        description="Wells on imagining the future as a mode of inquiry; "
                    "the speculative-fiction manifesto from the most "
                    "important early-SF practitioner.",
        url="https://www.gutenberg.org/cache/epub/44867/pg44867.txt",
        source_page="https://www.gutenberg.org/ebooks/44867",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. G. Wells",
        tags=["nonfiction", "craft", "scifi", "speculative", "writing-guide"],
        size_hint_kb=73,
    ),
    CorpusEntry(
        id="gutenberg-lang-adventures-books",
        name="Adventures Among Books — Andrew Lang (1905)",
        description="Lang on adventure, romance, fairy-tale, and the "
                    "imaginative imperative; major Victorian critic on "
                    "the storytelling tradition. Fantasy + adventure.",
        url="https://www.gutenberg.org/cache/epub/1994/pg1994.txt",
        source_page="https://www.gutenberg.org/ebooks/1994",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Andrew Lang",
        tags=["nonfiction", "craft", "fantasy", "adventure", "literary", "writing-guide"],
        size_hint_kb=437,
    ),
    CorpusEntry(
        id="gutenberg-frazer-golden-bough",
        name="The Golden Bough (abridged) — James George Frazer (1922)",
        description="The comparative-mythology survey that supplied "
                    "20th-century fantasy/horror with archetypes, ritual "
                    "structure, dying-and-rising-god patterns. Large "
                    "volume — use sparingly as background, not for prose.",
        url="https://www.gutenberg.org/cache/epub/3623/pg3623.txt",
        source_page="https://www.gutenberg.org/ebooks/3623",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="James George Frazer",
        tags=["nonfiction", "craft", "fantasy", "horror", "myth", "writing-guide"],
        size_hint_kb=2276,
    ),
    CorpusEntry(
        id="gutenberg-scarborough-supernatural",
        name="The Supernatural in Modern English Fiction — Dorothy Scarborough (1917)",
        description="Columbia dissertation surveying ghost, devil, "
                    "vampire, supernatural-being, and pact tales; the "
                    "definitive horror-genre criticism in the public "
                    "domain.",
        url="https://www.gutenberg.org/cache/epub/47204/pg47204.txt",
        source_page="https://www.gutenberg.org/ebooks/47204",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Dorothy Scarborough",
        tags=["nonfiction", "craft", "horror", "gothic", "weird", "criticism", "writing-guide"],
        size_hint_kb=655,
    ),

    # ── Mystery (additional) ──
    CorpusEntry(
        id="gutenberg-father-brown",
        name="The Innocence of Father Brown — G. K. Chesterton (1911)",
        description="Twelve detective stories with paradox-driven puzzles "
                    "and a memorable amateur-sleuth voice.",
        url="https://www.gutenberg.org/cache/epub/204/pg204.txt",
        source_page="https://www.gutenberg.org/ebooks/204",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="G. K. Chesterton",
        tags=["fiction", "mystery", "detective", "short-story", "classic"],
        size_hint_kb=480,
    ),
    CorpusEntry(
        id="gutenberg-mysterious-affair-styles",
        name="The Mysterious Affair at Styles — Agatha Christie (1920)",
        description="Christie's debut and Poirot's first case; the "
                    "Golden-Age detective novel template.",
        url="https://www.gutenberg.org/cache/epub/863/pg863.txt",
        source_page="https://www.gutenberg.org/ebooks/863",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Agatha Christie",
        tags=["fiction", "mystery", "detective", "classic"],
        size_hint_kb=440,
    ),
    CorpusEntry(
        id="gutenberg-leavenworth-case",
        name="The Leavenworth Case — Anna Katharine Green (1878)",
        description="Often called the first American detective novel; "
                    "evidence-driven plotting and locked-room methods.",
        url="https://www.gutenberg.org/cache/epub/4047/pg4047.txt",
        source_page="https://www.gutenberg.org/ebooks/4047",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Anna Katharine Green",
        tags=["fiction", "mystery", "detective", "classic"],
        size_hint_kb=720,
    ),

    # ── Adventure (Project Gutenberg) ──
    CorpusEntry(
        id="gutenberg-treasure-island",
        name="Treasure Island — Robert Louis Stevenson (1883)",
        description="The archetypal adventure novel — pirates, maps, "
                    "first-person young-narrator voice, tight pacing.",
        url="https://www.gutenberg.org/cache/epub/120/pg120.txt",
        source_page="https://www.gutenberg.org/ebooks/120",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Robert Louis Stevenson",
        tags=["fiction", "adventure", "young-adult", "classic"],
        size_hint_kb=560,
    ),
    CorpusEntry(
        id="gutenberg-kidnapped",
        name="Kidnapped — Robert Louis Stevenson (1886)",
        description="Historical adventure across the Scottish Highlands; "
                    "lean, propulsive prose.",
        url="https://www.gutenberg.org/cache/epub/421/pg421.txt",
        source_page="https://www.gutenberg.org/ebooks/421",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Robert Louis Stevenson",
        tags=["fiction", "adventure", "historical", "classic"],
        size_hint_kb=600,
    ),
    CorpusEntry(
        id="gutenberg-king-solomons-mines",
        name="King Solomon's Mines — H. Rider Haggard (1885)",
        description="Lost-world adventure that defined the genre; "
                    "first-person guide narration, exotic setting.",
        url="https://www.gutenberg.org/cache/epub/2166/pg2166.txt",
        source_page="https://www.gutenberg.org/ebooks/2166",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="H. Rider Haggard",
        tags=["fiction", "adventure", "lost-world", "classic"],
        size_hint_kb=620,
    ),

    # ── Fantasy (additional) ──
    CorpusEntry(
        id="gutenberg-oz",
        name="The Wonderful Wizard of Oz — L. Frank Baum (1900)",
        description="Foundational American fantasy; clean third-person "
                    "narration, episodic structure, talking animals.",
        url="https://www.gutenberg.org/cache/epub/55/pg55.txt",
        source_page="https://www.gutenberg.org/ebooks/55",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="L. Frank Baum",
        tags=["fiction", "fantasy", "young-adult", "classic"],
        size_hint_kb=380,
    ),

    # ── Horror (additional short-story sources) ──
    CorpusEntry(
        id="gutenberg-monkeys-paw",
        name="The Monkey's Paw and other stories — W. W. Jacobs",
        description="Classic ironic-horror short story; tight cause-and-"
                    "effect dread, plus other Jacobs tales.",
        url="https://www.gutenberg.org/cache/epub/12122/pg12122.txt",
        source_page="https://www.gutenberg.org/ebooks/12122",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="W. W. Jacobs",
        tags=["fiction", "horror", "short-story", "classic"],
        size_hint_kb=200,
    ),
    CorpusEntry(
        id="gutenberg-bierce-soldiers",
        name="Tales of Soldiers and Civilians — Ambrose Bierce (1891)",
        description="War + supernatural horror short stories; spare, "
                    "sardonic prose; \"Occurrence at Owl Creek Bridge\".",
        url="https://www.gutenberg.org/cache/epub/13334/pg13334.txt",
        source_page="https://www.gutenberg.org/ebooks/13334",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Ambrose Bierce",
        tags=["fiction", "horror", "war", "short-story", "classic"],
        size_hint_kb=380,
    ),

    # ── Sci-fi (additional) ──
    CorpusEntry(
        id="gutenberg-flatland",
        name="Flatland — Edwin Abbott (1884)",
        description="Mathematical / philosophical sci-fi told by a "
                    "two-dimensional square; first-person didactic voice.",
        url="https://www.gutenberg.org/cache/epub/97/pg97.txt",
        source_page="https://www.gutenberg.org/ebooks/97",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Edwin A. Abbott",
        tags=["fiction", "scifi", "satire", "classic"],
        size_hint_kb=180,
    ),
    CorpusEntry(
        id="gutenberg-mysterious-island",
        name="The Mysterious Island — Jules Verne (1875)",
        description="Survival sci-fi adventure; methodical step-by-step "
                    "engineering prose, ensemble cast.",
        url="https://www.gutenberg.org/cache/epub/1268/pg1268.txt",
        source_page="https://www.gutenberg.org/ebooks/1268",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jules Verne",
        tags=["fiction", "scifi", "adventure", "survival", "classic"],
        size_hint_kb=1100,
    ),

    # ── Literary (additional) ──
    CorpusEntry(
        id="gutenberg-great-gatsby",
        name="The Great Gatsby — F. Scott Fitzgerald (1925)",
        description="20th-century literary touchstone; first-person "
                    "Carraway narration, lyrical compression. PD in the "
                    "US since 2021.",
        url="https://www.gutenberg.org/cache/epub/64317/pg64317.txt",
        source_page="https://www.gutenberg.org/ebooks/64317",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="F. Scott Fitzgerald",
        tags=["fiction", "literary", "modernist", "classic"],
        size_hint_kb=300,
    ),
    CorpusEntry(
        id="gutenberg-dubliners",
        name="Dubliners — James Joyce (1914)",
        description="15 modernist short stories; \"epiphany\" structure, "
                    "controlled free-indirect prose.",
        url="https://www.gutenberg.org/cache/epub/2814/pg2814.txt",
        source_page="https://www.gutenberg.org/ebooks/2814",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="James Joyce",
        tags=["fiction", "literary", "modernist", "short-story", "classic"],
        size_hint_kb=520,
    ),

    # ── Tone anchors (Project Gutenberg) ──
    # Books picked specifically for tone-corpus exemplar status. These
    # cover thin tones that the existing genre-shelf doesn't otherwise
    # supply (light/comic, grimdark, satirical) so the tone filter has
    # solid training material.
    CorpusEntry(
        id="gutenberg-three-men-boat",
        name="Three Men in a Boat — Jerome K. Jerome (1889)",
        description="Definitive light/comic Victorian prose; warm, "
                    "digressive, conversational humor. The reference "
                    "text for 'light' tone.",
        url="https://www.gutenberg.org/cache/epub/308/pg308.txt",
        source_page="https://www.gutenberg.org/ebooks/308",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Jerome K. Jerome",
        tags=["fiction", "comedy", "light", "literary", "classic"],
        size_hint_kb=384,
    ),
    CorpusEntry(
        id="gutenberg-diary-nobody",
        name="The Diary of a Nobody — George & Weedon Grossmith (1892)",
        description="Cozy Victorian comic diary; clerk's domestic life, "
                    "tonal benchmark for warm/low-stakes humor.",
        url="https://www.gutenberg.org/cache/epub/1026/pg1026.txt",
        source_page="https://www.gutenberg.org/ebooks/1026",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="George Grossmith",
        tags=["fiction", "comedy", "light", "cozy", "diary", "classic"],
        size_hint_kb=253,
    ),
    CorpusEntry(
        id="gutenberg-nostromo",
        name="Nostromo — Joseph Conrad (1904)",
        description="Grimdark political tragedy; corrupt revolutions, "
                    "moral collapse, bleak Conradian prose. Anchor for "
                    "literary 'grimdark' tone.",
        url="https://www.gutenberg.org/cache/epub/2021/pg2021.txt",
        source_page="https://www.gutenberg.org/ebooks/2021",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Joseph Conrad",
        tags=["fiction", "literary", "grimdark", "political", "classic"],
        size_hint_kb=991,
    ),
    CorpusEntry(
        id="gutenberg-red-badge",
        name="The Red Badge of Courage — Stephen Crane (1895)",
        description="Stark naturalist war novel; spare battlefield "
                    "prose, anchor for 'stark/minimalist' and dark "
                    "tones.",
        url="https://www.gutenberg.org/cache/epub/73/pg73.txt",
        source_page="https://www.gutenberg.org/ebooks/73",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="Stephen Crane",
        tags=["fiction", "literary", "war", "naturalist", "stark", "grimdark", "classic"],
        size_hint_kb=281,
    ),
    CorpusEntry(
        id="gutenberg-vanity-fair",
        name="Vanity Fair — William Makepeace Thackeray (1848)",
        description="Definitive ironic/satirical Victorian novel; "
                    "social satire, omniscient ironic narrator, the "
                    "anchor for 'ironic' tone.",
        url="https://www.gutenberg.org/cache/epub/599/pg599.txt",
        source_page="https://www.gutenberg.org/ebooks/599",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="gutenberg",
        author="William Makepeace Thackeray",
        tags=["fiction", "literary", "satire", "ironic", "society", "classic"],
        size_hint_kb=1724,
    ),

    # ── Wikisource example (no copyrighted material; user can add more) ──
    CorpusEntry(
        id="wikisource-aesop",
        name="Aesop's Fables (Townsend translation, Wikisource)",
        description="Very short narrative arcs with clear morals.",
        url="https://en.wikisource.org/wiki/Special:Export/Aesop%27s_Fables",
        source_page="https://en.wikisource.org/wiki/Aesop%27s_Fables",
        license="public_domain",
        license_url="https://en.wikisource.org/wiki/Wikisource:Copyright_policy",
        format="llm",     # MediaWiki XML — let the LLM-assisted adapter clean it
        author="Aesop (trans. George Fyler Townsend)",
        tags=["fiction", "fable", "short-story", "classic"],
        size_hint_kb=420,
        purpose="both",
        medium="short",
        narratives=200,
    ),

    # ── Multi-narrative corpora via HuggingFace datasets ──
    # NOTE on copyright: we deliberately DO NOT include Books3 — it
    # contained material from the Bibliotik shadow library and is widely
    # documented as containing copyrighted books distributed without
    # permission. Users can register it themselves under their own
    # responsibility via the Add Custom URL flow.

    CorpusEntry(
        id="hf-tinystories",
        name="TinyStories — synthetic short stories (HF dataset)",
        description="2.1M synthetic short stories suitable for training "
                    "small narrative models. MIT-licensed, no IP risk.",
        url="roneneldan/TinyStories",
        source_page="https://huggingface.co/datasets/roneneldan/TinyStories",
        license="mit",
        license_url="https://opensource.org/license/mit",
        format="hf_dataset",
        author="Eldan & Li (synthetic)",
        tags=["fiction", "short-story", "synthetic", "general"],
        size_hint_kb=2_400_000,
        purpose="both",
        medium="short",
        narratives=2_100_000,
        hf_split="train",
        hf_text_field="text",
        hf_max_rows=8000,
    ),
    # ROCStories is intentionally omitted: the dataset's HF
    # mirrors are all either (a) gated, (b) script-based and
    # broken on modern ``datasets`` versions which removed
    # script-loading support, or (c) just .txt files that
    # ``load_dataset`` can't auto-detect. Plot-structure training
    # is covered by ``hf-writingprompts`` below. If a stable
    # script-free mirror appears, re-add this entry with the new
    # url / hf_config / hf_split fields.
    CorpusEntry(
        id="hf-writingprompts",
        name="Reddit r/WritingPrompts — prompt → story",
        description="Prompt-and-response stories from r/WritingPrompts. "
                    "User-generated content; check Reddit's content policy "
                    "and attribute authors when redistributing.",
        url="euclaise/WritingPrompts_preferences",
        source_page="https://huggingface.co/datasets/euclaise/WritingPrompts_preferences",
        license="user-attested",  # User must confirm acceptable use
        license_url="https://www.redditinc.com/policies/user-agreement",
        format="hf_dataset",
        author="Reddit /r/WritingPrompts community",
        tags=["fiction", "plot", "prompt-response", "varied-genre"],
        size_hint_kb=400_000,
        purpose="plot",
        medium="short",
        narratives=300_000,
        hf_split="train",
        hf_prompt_field="prompt",
        hf_completion_field="story",
        hf_max_rows=8_000,
    ),
    CorpusEntry(
        id="hf-wikipedia-movie-plots",
        name="Wikipedia Movie Plots — 35K film synopses (genre-labeled)",
        description="Plot summaries for ~35K films across decades and "
                    "genres. Every row carries a Genre column, so the "
                    "ingester tags each row with its canonical genre — "
                    "letting a 'thriller plot generator' fine-tune pull "
                    "only thrillers without the user pre-filtering. "
                    "CC-BY-SA via Wikipedia.",
        url="vishnupriyavr/wiki-movie-plots-with-summaries",
        source_page="https://huggingface.co/datasets/vishnupriyavr/wiki-movie-plots-with-summaries",
        license="cc-by-sa",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        format="hf_dataset",
        author="Wikipedia community",
        tags=["fiction", "movies", "plot", "synopsis", "labeled"],
        size_hint_kb=80_000,
        purpose="plot",
        medium="movies",
        narratives=35_000,
        hf_split="train",
        hf_text_field="Plot",
        hf_prompt_field="Title",
        hf_completion_field="Plot",
        # NEW: feed the per-row Genre + Title columns through the
        # tagger so each ingested row carries its own metadata
        # instead of a single fixed entry-level tag.
        hf_genre_field="Genre",
        hf_title_field="Title",
        hf_max_rows=8_000,
    ),
    CorpusEntry(
        id="hf-tvstorygen",
        name="TVStoryGen — episode summaries + show guides",
        description="TV episode plot summaries paired with show metadata; "
                    "good for training serialized TV pacing and arcs.",
        url="storyengine/TVStoryGen",
        source_page="https://huggingface.co/datasets/storyengine/TVStoryGen",
        license="user-attested",  # research dataset; varies by source
        license_url="https://huggingface.co/datasets/storyengine/TVStoryGen",
        format="hf_dataset",
        author="Chen et al. (TVStoryGen)",
        tags=["fiction", "tv", "episodic", "plot"],
        size_hint_kb=120_000,
        purpose="plot",
        medium="tv",
        narratives=26_000,
        hf_split="train",
        hf_prompt_field="prompt",
        hf_completion_field="story",
        hf_max_rows=4_000,
    ),
    CorpusEntry(
        id="hf-gutenberg-multi",
        name="Project Gutenberg multi-author corpus (HF, English)",
        description="Multi-narrative pull from Project Gutenberg via "
                    "HuggingFace, spanning hundreds of public-domain "
                    "novels and authors. English subset only.",
        url="manu/project_gutenberg",
        source_page="https://huggingface.co/datasets/manu/project_gutenberg",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="hf_dataset",
        author="Project Gutenberg authors (PD)",
        tags=["fiction", "books", "varied-genre", "classic"],
        size_hint_kb=10_000_000,
        purpose="voice",
        medium="books",
        narratives=10_000,
        # This dataset uses language codes as split names rather
        # than train/test/val. Available: de, en, es, fr, it, nl,
        # pl, pt, ru, sv, zh — we pick English. Picking a different
        # language is one catalog edit away (clone the entry, swap
        # the hf_split, retag the language).
        hf_split="en",
        hf_text_field="text",
        hf_max_rows=4_000,
    ),
    CorpusEntry(
        id="hf-pg-tagged",
        name="Project Gutenberg English — bookshelf-tagged (sedthh)",
        description="The whole English-language Project Gutenberg "
                    "catalog with PG's official bookshelf taxonomy "
                    "preserved per book — Science Fiction, Gothic "
                    "Fiction, Mystery Fiction, Detective Fiction, "
                    "Adventure, Fantasy, Westerns, Frontier and "
                    "Pioneer Life, Horror & Supernatural Fiction, "
                    "and many more. Each row is a full book; the "
                    "downloader fans it into paragraph pairs and "
                    "tags every pair with the book's bookshelves "
                    "mapped through our genre taxonomy. Result: "
                    "training rows automatically get the right "
                    "``genre`` column, so a horror fine-tune only "
                    "trains on horror-tagged passages without you "
                    "hand-curating which PG entries to download.",
        url="sedthh/gutenberg_english",
        source_page="https://huggingface.co/datasets/sedthh/gutenberg_english",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="hf_dataset",
        author="Project Gutenberg authors (PD) / sedthh (mirror + tagging)",
        tags=["fiction", "books", "varied-genre", "tagged", "classic",
              "scifi", "horror", "western", "frontier", "mystery",
              "adventure", "gothic", "fantasy", "romance"],
        size_hint_kb=20_000_000,        # rough — full English PG
        purpose="voice",
        medium="books",
        narratives=28_000,
        hf_split="train",
        # Dotted paths read JSON-encoded sub-fields out of the
        # METADATA column. The fetcher and downloader both
        # understand these now.
        hf_text_field="TEXT",
        hf_genre_field="METADATA.bookshelves",
        hf_title_field="METADATA.title",
        # 2k books × ~80 paragraph pairs each = ~160K training pairs.
        hf_max_rows=2_000,
    ),
    CorpusEntry(
        id="hf-pg19",
        name="PG-19 — Project Gutenberg books (pre-1919, parquet mirror)",
        description="DeepMind's curated long-form benchmark: ~28k full-"
                    "length books published before 1919, all public "
                    "domain. The standard 'books corpus' for long-context "
                    "training. We point at emozilla's parquet mirror "
                    "rather than the original deepmind/pg19 because the "
                    "DeepMind release ships with a Python loader script "
                    "(pg19.py) that the modern `datasets` package "
                    "(3.x+) refuses to execute as a security measure. "
                    "Same data, same schema, same license — just "
                    "packaged in a format that still loads.",
        url="emozilla/pg19",
        source_page="https://huggingface.co/datasets/emozilla/pg19",
        license="pd-us",
        license_url="https://www.gutenberg.org/policy/license.html",
        format="hf_dataset",
        author="DeepMind (original) / emozilla (mirror) / "
               "Project Gutenberg authors (PD)",
        tags=["fiction", "books", "long-form", "varied-genre", "classic"],
        size_hint_kb=11_000_000,
        purpose="voice",
        medium="books",
        narratives=28_000,
        hf_split="train",
        hf_text_field="text",
        hf_max_rows=2_000,  # capped — these are full novels
    ),
    CorpusEntry(
        id="hf-booksum",
        name="BookSum — chapter & book summaries (CMU/Salesforce)",
        description="Salesforce/CMU corpus of long-form summaries paired "
                    "with full chapter / book text from PD literature. "
                    "Useful for plot-structure training: 'given setup, "
                    "produce summary' or 'given summary, produce "
                    "outline'. License is research / source-permissive; "
                    "requires attestation.",
        url="kmfoda/booksum",
        source_page="https://huggingface.co/datasets/kmfoda/booksum",
        license="user-attested",
        license_url="https://huggingface.co/datasets/kmfoda/booksum",
        format="hf_dataset",
        author="Salesforce / CMU (Kryscinski et al.)",
        tags=["fiction", "plot", "structure", "summary", "labeled"],
        size_hint_kb=400_000,
        purpose="plot",
        medium="books",
        narratives=12_000,
        hf_split="train",
        hf_text_field="summary_text",
        hf_prompt_field="chapter",         # full chapter text → prompt
        hf_completion_field="summary_text", # → summary completion
        hf_title_field="book_title",       # if present in the schema
        hf_max_rows=2_000,
    ),
    CorpusEntry(
        id="hf-paws-paraphrases",
        name="PAWS — paraphrase pairs (Google, CC-BY-SA)",
        description="~50K labeled paraphrase pairs from PAWS-Wiki. We "
                    "filter to label=1 (true paraphrases) so the model "
                    "trains on real rephrase supervision rather than "
                    "near-duplicates. Direct (sentence1 → sentence2) "
                    "pair structure — best free dataset for rephrasing "
                    "training.",
        url="paws",
        source_page="https://huggingface.co/datasets/paws",
        license="cc-by-sa",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        format="hf_dataset",
        author="Google AI Language",
        tags=["paraphrase", "rephrase", "pair", "training-ready"],
        size_hint_kb=10_000,
        purpose="both",
        medium="mixed",
        narratives=50_000,
        hf_split="train",
        # 'paws' exposes three configs — pick labeled_final, which has
        # the structured (sentence1, sentence2, label) columns we want.
        # Without this, recent versions of `datasets` raise
        # "Config name is missing" before we can fetch anything.
        hf_config="labeled_final",
        hf_prompt_field="sentence1",
        hf_completion_field="sentence2",
        hf_filter_field="label",
        hf_filter_value="1",      # only true-paraphrase pairs
        hf_max_rows=8_000,
    ),
    CorpusEntry(
        id="hf-fareedkhan-1k-stories",
        name="FareedKhan 1K stories × 100 genres (HF, labeled)",
        description="1,000 short stories spanning 100 distinct genre "
                    "labels. Every row carries genre + title + content, "
                    "so the ingester tags each row with its canonical "
                    "genre — the training-time genre filter then routes "
                    "rows to matching fine-tunes automatically. License "
                    "is user-uploaded; requires attestation before "
                    "download.",
        url="FareedKhan/1k_stories_100_genre",
        source_page="https://huggingface.co/datasets/FareedKhan/1k_stories_100_genre",
        license="user-attested",
        license_url="https://huggingface.co/datasets/FareedKhan/1k_stories_100_genre",
        format="hf_dataset",
        author="FareedKhan (HuggingFace community)",
        tags=["fiction", "short-story", "varied-genre", "labeled"],
        size_hint_kb=80_000,
        purpose="voice",
        medium="short",
        narratives=1_000,
        hf_split="train",
        hf_text_field="content",
        hf_genre_field="genre",
        hf_title_field="title",
        hf_max_rows=2_000,
    ),
    # NOTE — SF-Corpus EF entries removed. Both
    # ``SF-Corpus/EF_Chapters_and_Chunks`` and
    # ``SF-Corpus/EF_Books_and_Chapters`` publish in HathiTrust
    # Extracted Features format: each "row" is the *alphabetically
    # sorted bag of words* of a chunk, with word-frequency repeats
    # preserved. That's legal to share even for in-copyright SF
    # works, but it is fundamentally not prose — useless for
    # language-model training. Recommend Project Gutenberg SF
    # entries (gutenberg-time-machine, gutenberg-war-of-worlds,
    # gutenberg-invisible-man, gutenberg-20000-leagues,
    # gutenberg-princess-mars) and ``hf-storytracer-us-pd`` (which
    # captures pulp-era SF that lapsed into the public domain) as
    # legitimate replacements.
    CorpusEntry(
        id="hf-storytracer-us-pd",
        name="Modern PD American books — storytracer (COCA-substitute)",
        description="650k+ public-domain books from US sources, with broader "
                    "post-1923 coverage than PG (it includes works that "
                    "lapsed into the public domain via non-renewal) — the "
                    "closest free stand-in for COCA's fiction subset, since "
                    "COCA itself is paid (BYU) and not on HF. Skews 20th-"
                    "century American voice. Westerns, mysteries, romances, "
                    "and pulp era genre fiction are all represented; useful "
                    "as a modern-American-prose tutor on top of PG / "
                    "institutional-books which lean older.",
        url="storytracer/US-PD-Books",
        source_page="https://huggingface.co/datasets/storytracer/US-PD-Books",
        license="pd-us",
        license_url="https://huggingface.co/datasets/storytracer/US-PD-Books",
        format="hf_dataset",
        author="storytracer / US public-domain authors",
        tags=["fiction", "books", "varied-genre", "modern", "american",
              "western", "mystery", "romance", "pulp"],
        size_hint_kb=80_000_000,
        purpose="voice",
        medium="books",
        narratives=650_000,
        hf_split="train",
        hf_text_field="text",
        hf_max_rows=1_500,
    ),
    CorpusEntry(
        id="hf-cnn-dailymail",
        name="CNN/DailyMail — modern American news prose (Apache-2.0)",
        description="287k news articles paired with multi-sentence "
                    "highlights. Contemporary American journalistic "
                    "English at scale — different register from fiction, "
                    "but the closest free substitute for COCA's "
                    "newspaper / magazine slice. Use it to teach modern "
                    "diction, idioms, and event-reporting cadence; train "
                    "the highlights field for tight summary voice. CCWL "
                    "(Contemporary Corpus of Written Language) is paid; "
                    "this is the best free analogue for modern English.",
        url="cnn_dailymail",
        source_page="https://huggingface.co/datasets/cnn_dailymail",
        license="apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        format="hf_dataset",
        author="See, Liu, Manning (CNN/DailyMail)",
        tags=["nonfiction", "news", "modern", "american", "journalism",
              "varied-topic"],
        size_hint_kb=1_400_000,
        purpose="voice",
        medium="articles",
        narratives=287_000,
        # CNN/DM uses configs ("1.0.0", "2.0.0", "3.0.0"); 3.0.0 is
        # the canonical full split.
        hf_config="3.0.0",
        hf_split="train",
        hf_text_field="article",
        hf_max_rows=4_000,
    ),
    CorpusEntry(
        id="hf-institutional-books",
        name="Institutional Books 1.0 — Harvard + Google (PD)",
        description="The flagship open books corpus: ~983k public-domain "
                    "volumes from Harvard's Widener Library, digitised by "
                    "Google's Books Library Project, packaged for AI "
                    "training by Harvard's Institutional Data Initiative. "
                    "~380B tokens. Every volume verified PD before release "
                    "— larger and cleaner than PG-19, no Books3-style "
                    "copyright issues.",
        url="institutional/institutional-books-1.0",
        source_page="https://huggingface.co/datasets/institutional/institutional-books-1.0",
        license="pd-us",
        license_url="https://huggingface.co/datasets/institutional/institutional-books-1.0",
        format="hf_dataset",
        author="Harvard Institutional Data Initiative + Google Books",
        tags=["fiction", "nonfiction", "books", "long-form",
              "varied-genre", "classic", "academic"],
        size_hint_kb=200_000_000,        # rough ballpark; this is huge
        purpose="voice",
        medium="books",
        narratives=983_000,
        hf_split="train",
        hf_text_field="text",
        # Heavy cap — the streaming download takes one row at a time,
        # but a single book can be 100k+ tokens, so even 1000 rows is
        # a serious training set. Bump higher when you have more disk.
        hf_max_rows=1_000,
    ),
]


def find_entry(corpus_id: str) -> CorpusEntry | None:
    for c in CATALOG:
        if c.id == corpus_id:
            return c
    return None


def is_license_safe(license_label: str) -> bool:
    """True if the license is on our auto-download safelist."""
    return (license_label or "").lower() in LICENSE_OK
