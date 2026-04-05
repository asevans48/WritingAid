"""Wikipedia article importer for the knowledge store.

Supports:
- Individual article download via the `wikipedia` Python package
- Bulk import from Wikipedia Simple English via HuggingFace datasets
- Curated worldbuilding-relevant article sets
"""

import logging
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

def _title_distance(target: str, candidate: str) -> int:
    """Simple distance metric — prefer candidates that contain the target words."""
    target_lower = target.lower()
    candidate_lower = candidate.lower()
    if target_lower == candidate_lower:
        return 0
    if target_lower in candidate_lower:
        return 1
    # Count shared words
    target_words = set(target_lower.split())
    candidate_words = set(candidate_lower.split())
    shared = len(target_words & candidate_words)
    return max(10 - shared, 2)


# Curated list of worldbuilding-relevant Wikipedia articles.
# Use exact article titles to avoid disambiguation issues.
WORLDBUILDING_CATEGORIES = [
    # Government & Politics
    "Feudalism", "Monarchy", "Theocracy", "Republic", "Oligarchy",
    "Democracy", "Anarchy (political philosophy)", "Fascism", "Communism",
    "Tribe", "City-state", "Empire", "Colonialism",
    # Military & Warfare
    "Siege", "Guerrilla warfare", "Naval warfare", "Cavalry",
    "Fortification", "Military strategy", "Mercenary",
    # Social Structures
    "Caste", "Serfdom", "Guild", "Slavery", "Nomadic peoples",
    "Matriarchy", "Patriarchy", "Social class",
    # Economy
    "Barter", "Currency (economics)", "Trade route", "Silk Road",
    "Mercantilism",
    # Religion & Mythology
    "Polytheism", "Monotheism", "Animism", "Mythology", "Creation myth",
    "Norse mythology", "Greek mythology", "Egyptian mythology",
    "Shinto", "Buddhism", "Ancestor veneration",
    # Geography & Terrain
    "Archipelago", "Tundra", "Desert", "Rainforest", "Volcano",
    "Mountain range", "River delta", "Canyon", "Glacier",
    # Technology
    "Bronze Age", "Iron Age", "Gunpowder", "Printing press",
    "Steam engine", "Alchemy", "Blacksmithing", "Navigation",
    # Culture
    "Oral tradition", "Rite of passage", "Taboo", "Honour",
    "Hospitality industry", "Cuisine", "Architecture",
    # Materials & Resources
    "Iron", "Bronze", "Steel", "Gold (element)", "Silver",
    "Spice trade", "Silk", "Timber",
    # Creatures & Nature
    "Dragon", "Griffin", "Phoenix (mythology)", "Unicorn", "Werewolf",
    "Domestication of animals", "Horse", "Falcon", "Wolf",
]


def download_article(title: str) -> Optional[dict]:
    """Download a single Wikipedia article by title.

    Returns:
        Dict with 'title', 'content', 'url', 'categories' or None on failure.
    """
    try:
        import wikipedia
        wikipedia.set_lang("en")

        # Disable auto_suggest — it mangles titles (e.g. "Democracy" → "democrat")
        try:
            page = wikipedia.page(title, auto_suggest=False)
        except wikipedia.exceptions.PageError:
            # Exact title not found — try search instead of suggest
            results = wikipedia.search(title, results=3)
            if not results:
                return None
            # Pick the result closest to the original title
            best = min(results, key=lambda r: _title_distance(title, r))
            try:
                page = wikipedia.page(best, auto_suggest=False)
            except (wikipedia.exceptions.PageError, wikipedia.exceptions.DisambiguationError):
                return None
        except wikipedia.exceptions.DisambiguationError as e:
            # Disambiguation page — pick the first option that looks right
            options = e.options[:10] if hasattr(e, 'options') else []
            if not options:
                return None
            # Prefer the option that matches the title most closely
            best = min(options, key=lambda o: _title_distance(title, o))
            try:
                page = wikipedia.page(best, auto_suggest=False)
            except Exception:
                return None

        return {
            "title": page.title,
            "content": page.content[:50000],
            "url": page.url,
            "categories": page.categories[:10] if hasattr(page, 'categories') else [],
        }
    except Exception as e:
        logger.warning(f"Failed to download '{title}': {e}")
        return None


def download_worldbuilding_articles(
    progress_callback: Optional[Callable[[str, int, int], None]] = None
) -> List[dict]:
    """Download the curated set of worldbuilding-relevant Wikipedia articles.

    Args:
        progress_callback: Optional callback(message, current, total)

    Returns:
        List of article dicts.
    """
    articles = []
    total = len(WORLDBUILDING_CATEGORIES)

    for i, title in enumerate(WORLDBUILDING_CATEGORIES):
        if progress_callback:
            progress_callback(f"Downloading: {title}", i, total)

        article = download_article(title)
        if article:
            articles.append(article)

    return articles


def download_simple_wikipedia(
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    max_articles: int = 50000
) -> List[dict]:
    """Download Simple English Wikipedia via HuggingFace datasets.

    This is ~200MB and contains ~200k articles in simplified English.

    Args:
        progress_callback: Optional callback(message, current, total)
        max_articles: Maximum number of articles to import

    Returns:
        List of article dicts.
    """
    try:
        if progress_callback:
            progress_callback("Loading Simple Wikipedia dataset...", 0, 1)

        from datasets import load_dataset
        # Official Wikimedia Foundation dataset on HuggingFace
        dataset = load_dataset(
            "wikimedia/wikipedia", "20231101.simple",
            split="train"
        )

        articles = []
        total = min(len(dataset), max_articles)

        for i in range(total):
            if progress_callback and i % 1000 == 0:
                progress_callback(f"Processing articles...", i, total)

            row = dataset[i]
            title = row.get("title", "")
            text = row.get("text", "")

            if not title or not text or len(text) < 100:
                continue

            articles.append({
                "title": title,
                "content": text[:30000],
                "url": f"https://simple.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "categories": [],
            })

        return articles

    except ImportError:
        logger.error("Install 'datasets' package: pip install datasets")
        raise
    except Exception as e:
        logger.error(f"Failed to download Simple Wikipedia: {e}")
        raise


def extract_project_search_terms(project) -> List[str]:
    """Extract Wikipedia search terms from a project's worldbuilding and characters.

    Looks at culture names, faction types, place types, magic system names,
    character backstories, technology types, fauna/flora, and more to build
    a list of real-world reference topics that would enrich the knowledge base.
    """
    terms = set()

    # Characters — extract culture/occupation/archetype hints
    if hasattr(project, 'characters'):
        for char in project.characters:
            if getattr(char, 'backstory', ''):
                # Pull key nouns from backstory (first 200 chars)
                for word in char.backstory[:200].split():
                    clean = word.strip('.,!?;:()[]"\'').lower()
                    if len(clean) > 5 and clean.isalpha():
                        terms.add(clean)
            if getattr(char, 'character_type', ''):
                terms.add(char.character_type)

    wb = getattr(project, 'worldbuilding', None)
    if not wb:
        return sorted(terms)[:50]

    # Factions — government types, faction names as cultural references
    if hasattr(wb, 'factions'):
        for f in wb.factions:
            if hasattr(f, 'government_type') and f.government_type:
                terms.add(f.government_type)
            if hasattr(f, 'faction_type') and f.faction_type:
                terms.add(str(f.faction_type).replace('_', ' '))

    # Cultures — languages, rituals, traditions
    if hasattr(wb, 'cultures'):
        for c in wb.cultures:
            if c.name:
                terms.add(c.name)
            if hasattr(c, 'description') and c.description:
                # Extract key cultural concepts
                for phrase in ["based on", "inspired by", "similar to", "like the"]:
                    if phrase in c.description.lower():
                        idx = c.description.lower().index(phrase) + len(phrase)
                        snippet = c.description[idx:idx + 40].strip()
                        first_word = snippet.split(',')[0].split('.')[0].strip()
                        if first_word and len(first_word) > 3:
                            terms.add(first_word)

    # Magic systems
    if hasattr(wb, 'magic_systems'):
        for m in wb.magic_systems:
            if hasattr(m, 'magic_type') and m.magic_type:
                terms.add(str(m.magic_type).replace('_', ' ') + " magic")
            if hasattr(m, 'source') and m.source:
                terms.add(m.source[:30].strip())

    # Technologies
    if hasattr(wb, 'technologies'):
        for t in wb.technologies:
            if t.name:
                terms.add(t.name)
            if hasattr(t, 'technology_type') and t.technology_type:
                terms.add(str(t.technology_type).replace('_', ' '))

    # Places — terrain types, climate references
    if hasattr(wb, 'places'):
        for p in wb.places:
            if hasattr(p, 'place_type') and p.place_type:
                terms.add(str(p.place_type).replace('_', ' '))

    # Flora & Fauna — species inspiration
    if hasattr(wb, 'flora'):
        for f in wb.flora:
            if hasattr(f, 'flora_type') and f.flora_type:
                terms.add(str(f.flora_type).replace('_', ' '))
    if hasattr(wb, 'fauna'):
        for f in wb.fauna:
            if hasattr(f, 'fauna_type') and f.fauna_type:
                terms.add(str(f.fauna_type).replace('_', ' '))

    # Historical events
    if hasattr(wb, 'historical_events'):
        for e in wb.historical_events:
            if hasattr(e, 'event_type') and e.event_type:
                terms.add(str(e.event_type).replace('_', ' '))

    # Legacy text fields — extract key concepts
    for field in ['mythology', 'history', 'politics', 'military', 'economy']:
        text = getattr(wb, field, '')
        if text and len(text) > 20:
            words = text[:300].split()
            for w in words:
                clean = w.strip('.,!?;:()[]"\'').lower()
                if len(clean) > 6 and clean.isalpha():
                    terms.add(clean)

    # Filter out very generic terms
    generic = {'the', 'and', 'with', 'from', 'that', 'this', 'which',
               'their', 'have', 'been', 'they', 'would', 'about', 'could',
               'other', 'there', 'these', 'those', 'after', 'before',
               'minor', 'major', 'protagonist', 'antagonist', 'supporting'}
    terms -= generic

    return sorted(terms)[:80]


def download_project_articles(
    project,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    max_per_term: int = 2
) -> List[dict]:
    """Download Wikipedia articles relevant to a project's worldbuilding and characters.

    Extracts search terms from the project's elements and downloads
    matching Wikipedia articles.

    Args:
        project: WriterProject instance
        progress_callback: Optional callback(message, current, total)
        max_per_term: Max articles to download per search term

    Returns:
        List of article dicts.
    """
    terms = extract_project_search_terms(project)
    if not terms:
        return []

    articles = []
    seen_titles = set()
    total = len(terms)

    for i, term in enumerate(terms):
        if progress_callback:
            progress_callback(f"Searching: {term}", i, total)

        results = search_and_download(term, max_results=max_per_term)
        for article in results:
            if article["title"] not in seen_titles:
                seen_titles.add(article["title"])
                articles.append(article)

    return articles


def search_and_download(query: str, max_results: int = 5) -> List[dict]:
    """Search Wikipedia and download matching articles.

    Args:
        query: Search query
        max_results: Maximum articles to download

    Returns:
        List of article dicts.
    """
    try:
        import wikipedia
        wikipedia.set_lang("en")
        titles = wikipedia.search(query, results=max_results)
        articles = []
        for title in titles:
            article = download_article(title)
            if article:
                articles.append(article)
        return articles
    except Exception as e:
        logger.error(f"Wikipedia search failed: {e}")
        return []
