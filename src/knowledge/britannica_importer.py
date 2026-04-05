"""Britannica API integration for the knowledge store.

Uses the free Encyclopaedia Britannica API (non-commercial, 1000 queries/day).
Users provide their own API key from encyclopaediaapi.com.
"""

import logging
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

BRITANNICA_API_BASE = "https://syndication.api.eb.com/production/articles"


def search_britannica(
    query: str, api_key: str, max_results: int = 5
) -> List[dict]:
    """Search Britannica and return article summaries.

    Args:
        query: Search query
        api_key: Britannica API key
        max_results: Maximum results

    Returns:
        List of article dicts with 'title', 'content', 'url'.
    """
    try:
        import requests

        response = requests.get(
            BRITANNICA_API_BASE,
            params={"query": query, "page": 1, "perPage": max_results},
            headers={"x-api-key": api_key},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        articles = []
        for item in data.get("articles", data) if isinstance(data, dict) else data:
            if isinstance(item, dict):
                title = item.get("title", "")
                # Content may be in 'description', 'abstract', or 'body'
                content = (
                    item.get("body", "")
                    or item.get("description", "")
                    or item.get("abstract", "")
                )
                url = item.get("url", "")
                if title and content:
                    articles.append({
                        "title": title,
                        "content": content[:30000],
                        "url": url,
                        "categories": [],
                    })

        return articles

    except ImportError:
        logger.error("Install 'requests' package: pip install requests")
        return []
    except Exception as e:
        logger.error(f"Britannica API error: {e}")
        return []


def download_britannica_articles(
    topics: List[str], api_key: str,
    progress_callback: Optional[Callable[[str, int, int], None]] = None
) -> List[dict]:
    """Download Britannica articles for a list of topics.

    Args:
        topics: List of search topics
        api_key: Britannica API key
        progress_callback: Optional callback(message, current, total)

    Returns:
        List of article dicts.
    """
    all_articles = []
    seen_titles = set()
    total = len(topics)

    for i, topic in enumerate(topics):
        if progress_callback:
            progress_callback(f"Fetching: {topic}", i, total)

        articles = search_britannica(topic, api_key, max_results=2)
        for article in articles:
            if article["title"] not in seen_titles:
                seen_titles.add(article["title"])
                all_articles.append(article)

    return all_articles
