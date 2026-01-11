"""RAG (Retrieval-Augmented Generation) system for context lookup."""

from typing import List, Dict, Optional
from dataclasses import dataclass
from src.models.project import WriterProject, Character, Subplot
from src.ai.llm_client import LLMClient


@dataclass
class ContextChunk:
    """A chunk of context with metadata."""
    content: str
    source_type: str  # worldbuilding, character, plot, subplot
    source_name: str
    relevance_score: float = 0.0


class RAGSystem:
    """RAG system for retrieving relevant context from project data."""

    def __init__(self, project: WriterProject, llm_client: Optional[LLMClient] = None):
        """Initialize RAG system with project data."""
        self.project = project
        self.llm_client = llm_client

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

        # Sort by relevance
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

    def get_relevant_context(
        self,
        query: str,
        max_results: int = 5,
        include_worldbuilding: bool = True,
        include_characters: bool = True,
        include_plot: bool = True
    ) -> List[ContextChunk]:
        """Get all relevant context for a query."""
        all_chunks = []

        if include_worldbuilding:
            all_chunks.extend(self.search_worldbuilding(query))

        if include_characters:
            all_chunks.extend(self.search_characters(query))

        if include_plot:
            all_chunks.extend(self.search_plot(query))

        # Sort by relevance and limit results
        all_chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return all_chunks[:max_results]

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

        return None
