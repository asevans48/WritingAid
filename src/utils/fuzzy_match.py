"""Fuzzy name matching for worldbuilding elements.

Finds existing elements whose names are similar enough to be the same
thing with a slight variation (e.g. "The Northern Reaches" vs "Northern Reaches",
"Kael'thar" vs "Kaelthar", "Kingdom of Ardan" vs "Ardan Kingdom").
"""

from typing import Optional, List, Tuple


def _normalize(name: str) -> str:
    """Normalize a name for comparison."""
    s = name.lower().strip()
    # Remove common prefixes/suffixes
    for prefix in ("the ", "a ", "an "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    # Remove common title patterns
    for pattern in ("kingdom of ", "city of ", "order of ", "clan of ",
                    "house of ", "guild of ", "temple of ", "church of "):
        if s.startswith(pattern):
            s = s[len(pattern):]
    # Remove punctuation that varies between spellings
    s = s.replace("'", "").replace("-", "").replace(".", "").replace(",", "")
    # Collapse whitespace
    s = " ".join(s.split())
    return s


def _similarity(a: str, b: str) -> float:
    """Compute similarity between two normalized names (0.0-1.0)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    # Check containment (one is a substring of the other)
    if a in b or b in a:
        return 0.85

    # Bigram similarity (Dice coefficient)
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1))

    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a or not bg_b:
        return 0.0

    overlap = len(bg_a & bg_b)
    return (2.0 * overlap) / (len(bg_a) + len(bg_b))


def find_similar(name: str, existing_names: List[str],
                 threshold: float = 0.7) -> Optional[str]:
    """Find the most similar existing name above the threshold.

    Args:
        name: The new name to check
        existing_names: List of existing element names
        threshold: Minimum similarity to consider a match (0.0-1.0)

    Returns:
        The best matching existing name, or None if no good match.
    """
    norm_name = _normalize(name)
    if not norm_name:
        return None

    best_match = None
    best_score = 0.0

    for existing in existing_names:
        norm_existing = _normalize(existing)
        score = _similarity(norm_name, norm_existing)
        if score > best_score:
            best_score = score
            best_match = existing

    if best_score >= threshold:
        return best_match
    return None


def find_similar_element(name: str, elements: list,
                         threshold: float = 0.7) -> Optional[object]:
    """Find a similar element from a list of objects with a 'name' attribute.

    Args:
        name: The new name to check
        elements: List of objects with .name attribute
        threshold: Minimum similarity

    Returns:
        The matching element object, or None.
    """
    existing_names = [getattr(e, 'name', '') for e in elements]
    match_name = find_similar(name, existing_names, threshold)
    if match_name is None:
        return None
    return next((e for e in elements if getattr(e, 'name', '') == match_name), None)
