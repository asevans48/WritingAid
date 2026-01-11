"""Chapter Memory System - Manages memory for chapters with key points, plot points, and caching."""

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path


@dataclass
class KeyPoint:
    """A key point extracted from chapter content."""
    id: str
    content: str
    point_type: str  # "character", "plot", "setting", "conflict", "theme", "foreshadowing"
    importance: int  # 1-5, higher = more important
    characters_involved: List[str] = field(default_factory=list)
    line_range: Tuple[int, int] = (0, 0)  # Start and end line numbers
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "point_type": self.point_type,
            "importance": self.importance,
            "characters_involved": self.characters_involved,
            "line_range": list(self.line_range),
            "created_at": self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'KeyPoint':
        """Create from dictionary."""
        return cls(
            id=data["id"],
            content=data["content"],
            point_type=data["point_type"],
            importance=data["importance"],
            characters_involved=data.get("characters_involved", []),
            line_range=tuple(data.get("line_range", (0, 0))),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        )


@dataclass
class ChapterSummary:
    """Summary of a chapter for quick reference without loading full content."""
    chapter_id: str
    chapter_number: int
    title: str
    word_count: int
    key_points: List[KeyPoint] = field(default_factory=list)
    characters_mentioned: Set[str] = field(default_factory=set)
    locations_mentioned: Set[str] = field(default_factory=set)
    plot_events: List[str] = field(default_factory=list)
    content_hash: str = ""  # Hash of content to detect changes
    last_analyzed: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "chapter_id": self.chapter_id,
            "chapter_number": self.chapter_number,
            "title": self.title,
            "word_count": self.word_count,
            "key_points": [kp.to_dict() for kp in self.key_points],
            "characters_mentioned": list(self.characters_mentioned),
            "locations_mentioned": list(self.locations_mentioned),
            "plot_events": self.plot_events,
            "content_hash": self.content_hash,
            "last_analyzed": self.last_analyzed.isoformat() if self.last_analyzed else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ChapterSummary':
        """Create from dictionary."""
        return cls(
            chapter_id=data["chapter_id"],
            chapter_number=data["chapter_number"],
            title=data["title"],
            word_count=data["word_count"],
            key_points=[KeyPoint.from_dict(kp) for kp in data.get("key_points", [])],
            characters_mentioned=set(data.get("characters_mentioned", [])),
            locations_mentioned=set(data.get("locations_mentioned", [])),
            plot_events=data.get("plot_events", []),
            content_hash=data.get("content_hash", ""),
            last_analyzed=datetime.fromisoformat(data["last_analyzed"]) if data.get("last_analyzed") else None
        )


class ChapterCache:
    """LRU cache for chapter content with configurable size limits."""

    def __init__(self, max_chapters: int = 5, max_memory_mb: float = 50.0):
        """Initialize cache with limits.

        Args:
            max_chapters: Maximum number of chapters to keep in cache
            max_memory_mb: Approximate maximum memory usage in megabytes
        """
        self.max_chapters = max_chapters
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self._cache: OrderedDict[str, Tuple[str, int]] = OrderedDict()  # chapter_id -> (content, size_bytes)
        self._current_size = 0
        self._hits = 0
        self._misses = 0

    def get(self, chapter_id: str) -> Optional[str]:
        """Get chapter content from cache.

        Args:
            chapter_id: The chapter ID to look up

        Returns:
            Chapter content if cached, None otherwise
        """
        if chapter_id in self._cache:
            self._hits += 1
            # Move to end (most recently used)
            self._cache.move_to_end(chapter_id)
            return self._cache[chapter_id][0]
        self._misses += 1
        return None

    def put(self, chapter_id: str, content: str) -> None:
        """Add or update chapter content in cache.

        Args:
            chapter_id: The chapter ID
            content: The chapter content
        """
        content_size = len(content.encode('utf-8'))

        # If chapter already in cache, remove old size
        if chapter_id in self._cache:
            old_size = self._cache[chapter_id][1]
            self._current_size -= old_size
            del self._cache[chapter_id]

        # Evict entries if needed
        while (len(self._cache) >= self.max_chapters or
               self._current_size + content_size > self.max_memory_bytes) and self._cache:
            oldest_id, (_, oldest_size) = self._cache.popitem(last=False)
            self._current_size -= oldest_size

        # Add new entry
        self._cache[chapter_id] = (content, content_size)
        self._current_size += content_size

    def remove(self, chapter_id: str) -> None:
        """Remove a specific chapter from cache.

        Args:
            chapter_id: The chapter ID to remove
        """
        if chapter_id in self._cache:
            _, size = self._cache.pop(chapter_id)
            self._current_size -= size

    def clear(self) -> None:
        """Clear all cached content."""
        self._cache.clear()
        self._current_size = 0

    def contains(self, chapter_id: str) -> bool:
        """Check if chapter is in cache without affecting LRU order."""
        return chapter_id in self._cache

    @property
    def stats(self) -> dict:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
        return {
            "cached_chapters": len(self._cache),
            "max_chapters": self.max_chapters,
            "current_size_mb": self._current_size / (1024 * 1024),
            "max_size_mb": self.max_memory_bytes / (1024 * 1024),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate
        }


class ChapterMemoryManager:
    """Manages chapter summaries, key points, and content caching."""

    def __init__(self, project=None, cache_size: int = 5, cache_memory_mb: float = 50.0):
        """Initialize memory manager.

        Args:
            project: The WriterProject instance
            cache_size: Number of chapters to cache
            cache_memory_mb: Maximum cache memory in MB
        """
        self.project = project
        self.cache = ChapterCache(max_chapters=cache_size, max_memory_mb=cache_memory_mb)
        self._summaries: Dict[str, ChapterSummary] = {}  # chapter_id -> summary
        self._dirty_chapters: Set[str] = set()  # Chapters that need re-analysis
        self._current_chapter_id: Optional[str] = None

    def set_project(self, project) -> None:
        """Set or update the project reference."""
        self.project = project
        # Clear cache when project changes
        self.cache.clear()
        self._summaries.clear()
        self._dirty_chapters.clear()
        self._current_chapter_id = None

    def get_chapter_content(self, chapter_id: str) -> Optional[str]:
        """Get chapter content, using cache if available.

        Args:
            chapter_id: The chapter ID

        Returns:
            Chapter content or None if not found
        """
        # Check cache first
        cached = self.cache.get(chapter_id)
        if cached is not None:
            return cached

        # Load from project
        if self.project:
            chapter = self._find_chapter(chapter_id)
            if chapter:
                content = chapter.content
                # Add to cache
                self.cache.put(chapter_id, content)
                return content

        return None

    def on_chapter_enter(self, chapter_id: str) -> None:
        """Called when user enters/selects a chapter.

        Loads content into cache and prepares memory.
        """
        self._current_chapter_id = chapter_id

        # Pre-load content into cache
        self.get_chapter_content(chapter_id)

        # Generate summary if needed
        if chapter_id not in self._summaries or chapter_id in self._dirty_chapters:
            self._analyze_chapter(chapter_id)
            self._dirty_chapters.discard(chapter_id)

    def on_chapter_exit(self, chapter_id: str, save_content: bool = True) -> None:
        """Called when user leaves a chapter.

        Saves content and marks for potential re-analysis.

        Args:
            chapter_id: The chapter being exited
            save_content: Whether to save content to model
        """
        if chapter_id == self._current_chapter_id:
            self._current_chapter_id = None

        # Mark as potentially dirty (content may have changed)
        # Actual dirty check happens on next enter
        chapter = self._find_chapter(chapter_id)
        if chapter:
            current_hash = self._compute_content_hash(chapter.content)
            summary = self._summaries.get(chapter_id)
            if summary and summary.content_hash != current_hash:
                self._dirty_chapters.add(chapter_id)

    def on_content_changed(self, chapter_id: str, new_content: str) -> None:
        """Called when chapter content changes.

        Updates cache and marks for re-analysis.
        """
        # Update cache with new content
        self.cache.put(chapter_id, new_content)

        # Mark as dirty for re-analysis
        self._dirty_chapters.add(chapter_id)

    def get_summary(self, chapter_id: str) -> Optional[ChapterSummary]:
        """Get chapter summary (key points, characters, etc.).

        Args:
            chapter_id: The chapter ID

        Returns:
            ChapterSummary or None
        """
        # Analyze if needed
        if chapter_id not in self._summaries or chapter_id in self._dirty_chapters:
            self._analyze_chapter(chapter_id)
            self._dirty_chapters.discard(chapter_id)

        return self._summaries.get(chapter_id)

    def get_all_summaries(self) -> List[ChapterSummary]:
        """Get summaries for all chapters."""
        if not self.project:
            return []

        summaries = []
        for chapter in self.project.manuscript.chapters:
            summary = self.get_summary(chapter.id)
            if summary:
                summaries.append(summary)

        return summaries

    def get_key_points_for_context(self, max_points: int = 20) -> List[KeyPoint]:
        """Get most important key points across all chapters for context.

        Args:
            max_points: Maximum number of points to return

        Returns:
            List of key points sorted by importance
        """
        all_points = []
        for summary in self._summaries.values():
            all_points.extend(summary.key_points)

        # Sort by importance (descending), then by chapter number
        all_points.sort(key=lambda p: (-p.importance, p.id))
        return all_points[:max_points]

    def get_characters_by_chapter(self) -> Dict[str, Set[str]]:
        """Get characters mentioned in each chapter.

        Returns:
            Dict mapping chapter_id to set of character names
        """
        return {
            chapter_id: summary.characters_mentioned
            for chapter_id, summary in self._summaries.items()
        }

    def search_key_points(self, query: str, point_types: Optional[List[str]] = None) -> List[KeyPoint]:
        """Search key points by query and optionally by type.

        Args:
            query: Search query
            point_types: Optional list of types to filter by

        Returns:
            Matching key points
        """
        query_lower = query.lower()
        results = []

        for summary in self._summaries.values():
            for kp in summary.key_points:
                # Filter by type if specified
                if point_types and kp.point_type not in point_types:
                    continue

                # Simple text matching
                if query_lower in kp.content.lower():
                    results.append(kp)

        # Sort by importance
        results.sort(key=lambda p: -p.importance)
        return results

    def preload_chapters(self, chapter_ids: List[str]) -> None:
        """Preload multiple chapters into cache.

        Useful for preloading adjacent chapters.
        """
        for chapter_id in chapter_ids:
            self.get_chapter_content(chapter_id)

    def preload_adjacent(self, current_chapter_id: str, count: int = 1) -> None:
        """Preload adjacent chapters (before and after current).

        Args:
            current_chapter_id: Current chapter ID
            count: Number of chapters to preload in each direction
        """
        if not self.project:
            return

        chapters = self.project.manuscript.chapters
        current_idx = next(
            (i for i, c in enumerate(chapters) if c.id == current_chapter_id),
            None
        )

        if current_idx is None:
            return

        # Collect adjacent chapter IDs
        adjacent_ids = []
        for offset in range(1, count + 1):
            # Before
            if current_idx - offset >= 0:
                adjacent_ids.append(chapters[current_idx - offset].id)
            # After
            if current_idx + offset < len(chapters):
                adjacent_ids.append(chapters[current_idx + offset].id)

        self.preload_chapters(adjacent_ids)

    def _find_chapter(self, chapter_id: str):
        """Find chapter by ID in project."""
        if not self.project:
            return None
        return next(
            (c for c in self.project.manuscript.chapters if c.id == chapter_id),
            None
        )

    def _compute_content_hash(self, content: str) -> str:
        """Compute hash of content for change detection."""
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def _analyze_chapter(self, chapter_id: str) -> None:
        """Analyze chapter and create/update summary.

        This extracts key points, characters, locations, etc.
        """
        chapter = self._find_chapter(chapter_id)
        if not chapter:
            return

        content = chapter.content
        content_hash = self._compute_content_hash(content)

        # Extract information
        key_points = self._extract_key_points(content, chapter_id)
        characters = self._extract_characters_mentioned(content)
        locations = self._extract_locations_mentioned(content)
        plot_events = self._extract_plot_events(content)

        # Create or update summary
        self._summaries[chapter_id] = ChapterSummary(
            chapter_id=chapter_id,
            chapter_number=chapter.number,
            title=chapter.title,
            word_count=chapter.word_count,
            key_points=key_points,
            characters_mentioned=characters,
            locations_mentioned=locations,
            plot_events=plot_events,
            content_hash=content_hash,
            last_analyzed=datetime.now()
        )

    def _extract_key_points(self, content: str, chapter_id: str) -> List[KeyPoint]:
        """Extract key points from chapter content.

        This is a simple heuristic-based extraction. For better results,
        this could be enhanced with LLM-based analysis.
        """
        key_points = []
        lines = content.split('\n')

        # Keywords that indicate important points
        plot_keywords = ['but then', 'suddenly', 'realized', 'discovered', 'revealed', 'decided']
        conflict_keywords = ['fought', 'argued', 'conflict', 'battle', 'struggled', 'enemy']
        character_keywords = ['said', 'replied', 'thought', 'felt', 'believed']

        point_id = 0
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            if not line_lower:
                continue

            # Check for plot keywords
            for keyword in plot_keywords:
                if keyword in line_lower and len(line_lower) > 20:
                    key_points.append(KeyPoint(
                        id=f"{chapter_id}_kp_{point_id}",
                        content=line.strip()[:200],
                        point_type="plot",
                        importance=3,
                        line_range=(i + 1, i + 1)
                    ))
                    point_id += 1
                    break

            # Check for conflict keywords
            for keyword in conflict_keywords:
                if keyword in line_lower and len(line_lower) > 20:
                    key_points.append(KeyPoint(
                        id=f"{chapter_id}_kp_{point_id}",
                        content=line.strip()[:200],
                        point_type="conflict",
                        importance=4,
                        line_range=(i + 1, i + 1)
                    ))
                    point_id += 1
                    break

        # Limit to most important points
        key_points.sort(key=lambda p: -p.importance)
        return key_points[:10]

    def _extract_characters_mentioned(self, content: str) -> Set[str]:
        """Extract character names mentioned in content.

        Uses project's character list for matching.
        """
        characters = set()
        if not self.project:
            return characters

        content_lower = content.lower()
        for char in self.project.characters:
            if char.name.lower() in content_lower:
                characters.add(char.name)

        return characters

    def _extract_locations_mentioned(self, content: str) -> Set[str]:
        """Extract locations mentioned in content.

        This is a simple implementation that looks for capitalized words
        after location indicators.
        """
        locations = set()
        location_indicators = ['in ', 'at ', 'to ', 'from ', 'near ', 'towards ']
        words = content.split()

        for i, word in enumerate(words):
            if word.lower() in location_indicators and i + 1 < len(words):
                next_word = words[i + 1]
                # Check if next word is capitalized (potential location)
                if next_word and next_word[0].isupper() and len(next_word) > 2:
                    locations.add(next_word.strip('.,!?";\''))

        return locations

    def _extract_plot_events(self, content: str) -> List[str]:
        """Extract plot events from content.

        Returns short descriptions of significant events.
        """
        events = []
        sentences = content.replace('\n', ' ').split('.')

        # Look for sentences with action verbs
        action_verbs = ['attacked', 'escaped', 'found', 'lost', 'died', 'married',
                        'betrayed', 'saved', 'killed', 'revealed', 'transformed']

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 20:
                continue

            sentence_lower = sentence.lower()
            for verb in action_verbs:
                if verb in sentence_lower:
                    events.append(sentence[:150])
                    break

        return events[:5]  # Limit to 5 events per chapter

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return self.cache.stats

    def export_summaries(self) -> dict:
        """Export all summaries for serialization."""
        return {
            chapter_id: summary.to_dict()
            for chapter_id, summary in self._summaries.items()
        }

    def import_summaries(self, data: dict) -> None:
        """Import summaries from serialized data."""
        self._summaries = {
            chapter_id: ChapterSummary.from_dict(summary_data)
            for chapter_id, summary_data in data.items()
        }
