"""RAG (Retrieval-Augmented Generation) system for context lookup."""

from typing import List, Dict, Optional, TYPE_CHECKING
from dataclasses import dataclass
from src.models.project import WriterProject
from src.ai.llm_client import LLMClient

if TYPE_CHECKING:
    from src.ai.chapter_memory import ChapterMemoryManager


@dataclass
class ContextChunk:
    """A chunk of context with metadata."""
    content: str
    source_type: str  # worldbuilding, character, plot, subplot, chapter_key_point
    source_name: str
    relevance_score: float = 0.0


class RAGSystem:
    """RAG system for retrieving relevant context from project data."""

    def __init__(self, project: WriterProject, llm_client: Optional[LLMClient] = None,
                 memory_manager: Optional['ChapterMemoryManager'] = None):
        """Initialize RAG system with project data.

        Args:
            project: The WriterProject instance
            llm_client: Optional LLM client for summarization
            memory_manager: Optional ChapterMemoryManager for cached chapter data
        """
        self.project = project
        self.llm_client = llm_client
        self.memory_manager = memory_manager
        self._context_cache: Dict[str, List[ContextChunk]] = {}
        self._cache_ttl = 300  # Cache results for 5 minutes
        self._cache_timestamps: Dict[str, float] = {}

    def set_memory_manager(self, memory_manager: 'ChapterMemoryManager') -> None:
        """Set or update the memory manager reference."""
        self.memory_manager = memory_manager
        # Clear cache when memory manager changes
        self._context_cache.clear()
        self._cache_timestamps.clear()

    def search_worldbuilding(self, query: str) -> List[ContextChunk]:
        """Search worldbuilding sections for relevant content."""
        chunks = []

        wb = self.project.worldbuilding

        # Search all worldbuilding sections
        sections = {
            "Mythology": wb.mythology,
            "Planets": wb.planets,
            "Climate": wb.climate,
            "History": wb.history,
            "Politics": wb.politics,
            "Military": wb.military,
            "Economy": wb.economy,
            "Power Hierarchy": wb.power_hierarchy
        }

        # Add custom sections
        sections.update(wb.custom_sections)

        # Simple keyword matching (can be enhanced with embeddings)
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for section_name, content in sections.items():
            if not content:
                continue

            content_lower = content.lower()

            # Check for exact phrase match
            if query_lower in content_lower:
                relevance = 0.9
            else:
                # Check word overlap
                content_words = set(content_lower.split())
                overlap = query_words & content_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:  # Threshold
                chunks.append(ContextChunk(
                    content=content,
                    source_type="worldbuilding",
                    source_name=section_name,
                    relevance_score=relevance
                ))

        # Search places/landmarks
        for place in wb.places:
            place_text = f"""
Place: {place.name}
Type: {place.place_type}
Planet: {place.planet or 'Unknown'}
Region: {place.region or 'Unknown'}
Controlling Faction: {place.controlling_faction or 'None'}
Description: {place.description}
Key Features: {', '.join(place.key_features) if place.key_features else 'None'}
Atmosphere: {place.atmosphere}
Story Relevance: {place.story_relevance}
            """.strip()

            place_lower = place_text.lower()

            # Check for name match (highest relevance)
            if place.name.lower() in query_lower:
                relevance = 1.0
            elif query_lower in place_lower:
                relevance = 0.85
            else:
                place_words = set(place_lower.split())
                overlap = query_words & place_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=place_text,
                    source_type="place",
                    source_name=place.name,
                    relevance_score=relevance
                ))

        # Sort by relevance
        chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return chunks

    def search_places(self, query: str) -> List[ContextChunk]:
        """Search places and landmarks for relevant content."""
        chunks = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        wb = self.project.worldbuilding

        for place in wb.places:
            # Build comprehensive place text for searching
            place_text = f"""
**{place.name}** ({place.place_type})

**Location:**
- Planet: {place.planet or 'Unknown'}
- Continent: {place.continent or 'Unknown'}
- Region: {place.region or 'Unknown'}

**Control:**
- Controlling Faction: {place.controlling_faction or 'None'}
- Contested By: {', '.join(place.contested_by) if place.contested_by else 'None'}

**Description:**
{place.description}

**Key Features:**
{chr(10).join('- ' + f for f in place.key_features) if place.key_features else 'None listed'}

**Atmosphere:**
{place.atmosphere}

**Cultural Significance:**
{place.cultural_significance}

**Story Relevance:**
{place.story_relevance}

**Notable Inhabitants:**
{', '.join(place.notable_inhabitants) if place.notable_inhabitants else 'None listed'}

**Notes:**
{place.notes}
            """.strip()

            place_lower = place_text.lower()

            # Check for name match (highest relevance)
            if place.name.lower() in query_lower:
                relevance = 1.0
            elif query_lower in place_lower:
                relevance = 0.85
            else:
                place_words = set(place_lower.split())
                overlap = query_words & place_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=place_text,
                    source_type="place",
                    source_name=place.name,
                    relevance_score=relevance
                ))

        chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return chunks

    def search_characters(self, query: str) -> List[ContextChunk]:
        """Search characters for relevant content."""
        chunks = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for character in self.project.characters:
            # Combine all character text
            char_text = f"""
            Name: {character.name}
            Type: {character.character_type}
            Personality: {character.personality}
            Backstory: {character.backstory}
            Notes: {character.notes}
            """

            char_lower = char_text.lower()

            # Check for name match
            if character.name.lower() in query_lower:
                relevance = 1.0
            elif query_lower in char_lower:
                relevance = 0.8
            else:
                # Word overlap
                char_words = set(char_lower.split())
                overlap = query_words & char_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=char_text.strip(),
                    source_type="character",
                    source_name=character.name,
                    relevance_score=relevance
                ))

        chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return chunks

    def search_plot(self, query: str) -> List[ContextChunk]:
        """Search plot and story planning for relevant content."""
        chunks = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        sp = self.project.story_planning

        # Main plot
        if sp.main_plot:
            plot_lower = sp.main_plot.lower()
            if query_lower in plot_lower:
                relevance = 0.9
            else:
                plot_words = set(plot_lower.split())
                overlap = query_words & plot_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=sp.main_plot,
                    source_type="plot",
                    source_name="Main Plot",
                    relevance_score=relevance
                ))

        # Freytag pyramid
        pyramid_sections = {
            "Exposition": sp.freytag_pyramid.exposition,
            "Rising Action": sp.freytag_pyramid.rising_action,
            "Climax": sp.freytag_pyramid.climax,
            "Falling Action": sp.freytag_pyramid.falling_action,
            "Resolution": sp.freytag_pyramid.resolution
        }

        for section_name, content in pyramid_sections.items():
            if not content:
                continue

            content_lower = content.lower()
            if query_lower in content_lower:
                relevance = 0.8
            else:
                content_words = set(content_lower.split())
                overlap = query_words & content_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=content,
                    source_type="plot",
                    source_name=section_name,
                    relevance_score=relevance
                ))

        # Subplots
        for subplot in sp.subplots:
            subplot_text = f"""
            Title: {subplot.title}
            Description: {subplot.description}
            Connection to Main Plot: {subplot.connection_to_main}
            """

            subplot_lower = subplot_text.lower()
            if query_lower in subplot_lower:
                relevance = 0.7
            else:
                subplot_words = set(subplot_lower.split())
                overlap = query_words & subplot_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                chunks.append(ContextChunk(
                    content=subplot_text.strip(),
                    source_type="subplot",
                    source_name=subplot.title,
                    relevance_score=relevance
                ))

        chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return chunks

    def search_chapter_key_points(self, query: str) -> List[ContextChunk]:
        """Search chapter key points from memory manager.

        Uses the cached chapter summaries for fast lookup without
        loading full chapter content.
        """
        chunks = []

        if not self.memory_manager:
            return chunks

        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Search through key points from all chapter summaries
        key_points = self.memory_manager.search_key_points(query)

        for kp in key_points:
            # Calculate relevance based on content match
            kp_lower = kp.content.lower()

            if query_lower in kp_lower:
                relevance = 0.9
            else:
                kp_words = set(kp_lower.split())
                overlap = query_words & kp_words
                relevance = len(overlap) / len(query_words) if query_words else 0

            if relevance > 0.1:
                # Include importance in relevance score
                adjusted_relevance = relevance * (0.5 + kp.importance * 0.1)

                chunks.append(ContextChunk(
                    content=kp.content,
                    source_type="chapter_key_point",
                    source_name=f"{kp.point_type.title()} (Chapter Key Point)",
                    relevance_score=adjusted_relevance
                ))

        chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return chunks[:10]  # Limit to top 10 key points

    def search_chapter_characters(self, query: str) -> List[ContextChunk]:
        """Search for characters mentioned in chapters.

        Uses cached chapter summaries for fast lookup.
        """
        chunks = []

        if not self.memory_manager:
            return chunks

        query_lower = query.lower()
        characters_by_chapter = self.memory_manager.get_characters_by_chapter()

        for chapter_id, characters in characters_by_chapter.items():
            for char_name in characters:
                if query_lower in char_name.lower():
                    # Get chapter info
                    summary = self.memory_manager.get_summary(chapter_id)
                    if summary:
                        chunks.append(ContextChunk(
                            content=f"{char_name} appears in Chapter {summary.chapter_number}: {summary.title}",
                            source_type="chapter_character",
                            source_name=f"Chapter {summary.chapter_number}",
                            relevance_score=0.7
                        ))

        return chunks

    def get_relevant_context(
        self,
        query: str,
        max_results: int = 5,
        include_worldbuilding: bool = True,
        include_characters: bool = True,
        include_plot: bool = True,
        include_places: bool = True,
        include_chapter_memory: bool = True
    ) -> List[ContextChunk]:
        """Get all relevant context for a query.

        Args:
            query: Search query
            max_results: Maximum number of results to return
            include_worldbuilding: Include worldbuilding sections
            include_characters: Include character data
            include_plot: Include plot/story planning
            include_places: Include places and landmarks
            include_chapter_memory: Include key points from chapter memory

        Returns:
            List of relevant context chunks sorted by relevance
        """
        import time

        # Check cache first
        cache_key = f"{query}_{include_worldbuilding}_{include_characters}_{include_plot}_{include_places}_{include_chapter_memory}"
        if cache_key in self._context_cache:
            cached_time = self._cache_timestamps.get(cache_key, 0)
            if time.time() - cached_time < self._cache_ttl:
                return self._context_cache[cache_key][:max_results]

        all_chunks = []

        if include_worldbuilding:
            all_chunks.extend(self.search_worldbuilding(query))

        if include_characters:
            all_chunks.extend(self.search_characters(query))

        if include_plot:
            all_chunks.extend(self.search_plot(query))

        if include_places:
            all_chunks.extend(self.search_places(query))

        if include_chapter_memory:
            all_chunks.extend(self.search_chapter_key_points(query))
            all_chunks.extend(self.search_chapter_characters(query))

        # Sort by relevance and cache results
        all_chunks.sort(key=lambda x: x.relevance_score, reverse=True)

        # Cache the results
        self._context_cache[cache_key] = all_chunks
        self._cache_timestamps[cache_key] = time.time()

        return all_chunks[:max_results]

    def clear_cache(self) -> None:
        """Clear the context cache."""
        self._context_cache.clear()
        self._cache_timestamps.clear()

    def summarize_context(self, query: str, max_results: int = 5) -> str:
        """Get relevant context and summarize it using LLM."""
        chunks = self.get_relevant_context(query, max_results)

        if not chunks:
            return "No relevant context found in your project."

        # Build context summary
        context_text = f"Query: {query}\n\nRelevant Context:\n\n"

        for i, chunk in enumerate(chunks, 1):
            context_text += f"{i}. [{chunk.source_type.upper()}: {chunk.source_name}]\n"
            context_text += f"{chunk.content}\n\n"

        # If LLM client available, summarize
        if self.llm_client:
            system_prompt = """You are helping a writer by summarizing relevant context from their project.
            Provide a concise, useful summary that highlights the most important details the writer should remember.
            Focus on information that would be helpful while writing a specific scene or chapter."""

            prompt = f"""
            The writer is looking up information about: "{query}"

            Here is the relevant context from their project:

            {context_text}

            Provide a concise summary of the most relevant information the writer should keep in mind.
            """

            try:
                summary = self.llm_client.generate_text(
                    prompt,
                    system_prompt,
                    max_tokens=500,
                    temperature=0.3
                )
                return f"**Context Summary for: {query}**\n\n{summary}\n\n---\n\nRaw Context:\n\n{context_text}"
            except:
                return context_text
        else:
            return context_text

    def get_quick_reference(self, context_type: str, name: str) -> Optional[str]:
        """Get quick reference for specific item by name."""
        if context_type == "character":
            char = next((c for c in self.project.characters if c.name.lower() == name.lower()), None)
            if char:
                return f"""
**{char.name}** ({char.character_type})

**Personality:**
{char.personality}

**Backstory:**
{char.backstory}

**Notes:**
{char.notes}
                """.strip()

        elif context_type == "worldbuilding":
            wb = self.project.worldbuilding
            sections = {
                "mythology": wb.mythology,
                "planets": wb.planets,
                "climate": wb.climate,
                "history": wb.history,
                "politics": wb.politics,
                "military": wb.military,
                "economy": wb.economy,
                "power_hierarchy": wb.power_hierarchy
            }
            sections.update({k.lower(): v for k, v in wb.custom_sections.items()})

            content = sections.get(name.lower())
            if content:
                return f"**{name.title()}**\n\n{content}"

        elif context_type == "subplot":
            subplot = next((s for s in self.project.story_planning.subplots if s.title.lower() == name.lower()), None)
            if subplot:
                return f"""
**{subplot.title}**

**Description:**
{subplot.description}

**Connection to Main Plot:**
{subplot.connection_to_main}
                """.strip()

        elif context_type == "place":
            place = next((p for p in self.project.worldbuilding.places if p.name.lower() == name.lower()), None)
            if place:
                features_text = "\n".join(f"- {f}" for f in place.key_features) if place.key_features else "None listed"
                return f"""
**{place.name}** ({place.place_type})

**Location:**
- Planet: {place.planet or 'Unknown'}
- Region: {place.region or 'Unknown'}
- Controlling Faction: {place.controlling_faction or 'None'}

**Description:**
{place.description}

**Key Features:**
{features_text}

**Atmosphere:**
{place.atmosphere}

**Cultural Significance:**
{place.cultural_significance}

**Story Relevance:**
{place.story_relevance}

**Notes:**
{place.notes}
                """.strip()

        return None

    def get_place_list(self) -> List[str]:
        """Get list of all place names for quick reference lookups."""
        return [p.name for p in self.project.worldbuilding.places]

    def get_places_by_faction(self, faction_name: str) -> List[str]:
        """Get all places controlled by a specific faction."""
        return [
            p.name for p in self.project.worldbuilding.places
            if p.controlling_faction and p.controlling_faction.lower() == faction_name.lower()
        ]

    def get_places_on_planet(self, planet_name: str) -> List[str]:
        """Get all places on a specific planet."""
        return [
            p.name for p in self.project.worldbuilding.places
            if p.planet and p.planet.lower() == planet_name.lower()
        ]
