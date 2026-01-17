"""Enhanced RAG system with semantic search and comprehensive worldbuilding support."""

from typing import List, Dict, Optional, Any, TYPE_CHECKING
from dataclasses import dataclass
import uuid

from src.models.project import WriterProject
from src.ai.semantic_search import (
    SemanticSearchEngine, SearchMethod, DocumentChunk, SearchResult
)

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.ai.chapter_memory import ChapterMemoryManager


@dataclass
class ContextResult:
    """A context search result with rich metadata."""
    content: str
    source_type: str
    source_name: str
    relevance_score: float
    matched_terms: List[str]
    match_type: str  # keyword, semantic, hybrid
    metadata: Dict[str, Any]


class EnhancedRAGSystem:
    """Enhanced RAG system with semantic search for all project data."""

    def __init__(
        self,
        project: WriterProject,
        llm_client: Optional['LLMClient'] = None,
        memory_manager: Optional['ChapterMemoryManager'] = None
    ):
        """Initialize enhanced RAG system.

        Args:
            project: The writer project
            llm_client: Optional LLM client for embeddings and summarization
            memory_manager: Optional chapter memory manager
        """
        self.project = project
        self.llm_client = llm_client
        self.memory_manager = memory_manager
        self.search_engine = SemanticSearchEngine()
        self._indexed = False

        # Set up embedding function if LLM client available
        if llm_client and hasattr(llm_client, 'get_embedding'):
            self.search_engine.set_embedding_function(llm_client.get_embedding)

    def set_llm_client(self, llm_client: 'LLMClient'):
        """Set LLM client for embeddings."""
        self.llm_client = llm_client
        if hasattr(llm_client, 'get_embedding'):
            self.search_engine.set_embedding_function(llm_client.get_embedding)

    def set_memory_manager(self, memory_manager: 'ChapterMemoryManager'):
        """Set memory manager for chapter data."""
        self.memory_manager = memory_manager

    def rebuild_index(self, compute_embeddings: bool = False):
        """Rebuild the search index from project data.

        Args:
            compute_embeddings: Whether to compute neural embeddings (slower but better)
        """
        self.search_engine.clear()

        # Index all worldbuilding elements
        self._index_worldbuilding_text()
        self._index_factions()
        self._index_places()
        self._index_technologies()
        self._index_cultures()
        self._index_historical_events()
        self._index_flora_fauna()
        self._index_myths()
        self._index_star_systems()
        self._index_armies()
        self._index_economies()
        self._index_political_systems()

        # Index characters
        self._index_characters()

        # Index plot elements
        self._index_plot()
        self._index_promises()

        # Index chapter content if memory manager available
        if self.memory_manager:
            self._index_chapter_data()

        self._indexed = True

    def _make_chunk(
        self,
        content: str,
        source_type: str,
        source_name: str,
        source_id: str = "",
        metadata: Dict[str, Any] = None
    ) -> DocumentChunk:
        """Create a document chunk with a unique ID."""
        chunk_id = f"{source_type}_{source_id or str(uuid.uuid4())[:8]}"
        return DocumentChunk(
            id=chunk_id,
            content=content,
            source_type=source_type,
            source_name=source_name,
            source_id=source_id,
            metadata=metadata or {}
        )

    def _index_worldbuilding_text(self):
        """Index basic worldbuilding text sections."""
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
        sections.update(wb.custom_sections)

        for name, content in sections.items():
            if content and content.strip():
                chunk = self._make_chunk(
                    content=content,
                    source_type="worldbuilding",
                    source_name=name.replace("_", " ").title(),
                    source_id=name
                )
                self.search_engine.index_document(chunk)

    def _index_factions(self):
        """Index faction data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'factions'):
            return

        for faction in wb.factions:
            content = f"""
Faction: {faction.name}
Type: {faction.faction_type}
Government: {faction.government_type or 'Unknown'}
Leader: {faction.leader or 'Unknown'}
Population: {faction.population or 'Unknown'}
Territory: {faction.territory or 'Unknown'}
Description: {faction.description}
Ideology: {faction.ideology or ''}
Military Strength: {faction.military_strength or 'Unknown'}
Economic Strength: {faction.economic_strength or 'Unknown'}
Allies: {', '.join(faction.allies) if faction.allies else 'None'}
Enemies: {', '.join(faction.enemies) if faction.enemies else 'None'}
Notable Members: {', '.join(faction.notable_members) if faction.notable_members else 'None'}
History: {faction.history or ''}
Notes: {faction.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="faction",
                source_name=faction.name,
                source_id=faction.id,
                metadata={
                    "faction_type": faction.faction_type,
                    "leader": faction.leader,
                    "allies": faction.allies,
                    "enemies": faction.enemies
                }
            )
            self.search_engine.index_document(chunk)

    def _index_places(self):
        """Index place/location data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'places'):
            return

        for place in wb.places:
            features = ", ".join(place.key_features) if place.key_features else "None"
            inhabitants = ", ".join(place.notable_inhabitants) if place.notable_inhabitants else "None"

            content = f"""
Place: {place.name}
Type: {place.place_type}
Planet: {place.planet or 'Unknown'}
Continent: {place.continent or 'Unknown'}
Region: {place.region or 'Unknown'}
Controlling Faction: {place.controlling_faction or 'None'}
Population: {place.population or 'Unknown'}
Description: {place.description}
Key Features: {features}
Atmosphere: {place.atmosphere or ''}
Cultural Significance: {place.cultural_significance or ''}
Story Relevance: {place.story_relevance or ''}
Notable Inhabitants: {inhabitants}
History: {place.history or ''}
Notes: {place.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="place",
                source_name=place.name,
                source_id=place.id,
                metadata={
                    "place_type": place.place_type,
                    "planet": place.planet,
                    "controlling_faction": place.controlling_faction
                }
            )
            self.search_engine.index_document(chunk)

    def _index_technologies(self):
        """Index technology data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'technologies'):
            return

        for tech in wb.technologies:
            factions = ", ".join(tech.factions_with_access) if tech.factions_with_access else "All"
            prerequisites = ", ".join(tech.prerequisites) if tech.prerequisites else "None"

            content = f"""
Technology: {tech.name}
Type: {tech.technology_type.value.replace('_', ' ').title() if hasattr(tech.technology_type, 'value') else tech.technology_type}
Description: {tech.description}
How It Works: {tech.how_it_works or ''}
Factions with Access: {factions}
Prerequisites: {prerequisites}
Cost to Build: {tech.cost_to_build or 'Unknown'}
Game-Changing Impact: {tech.game_changing_level}/100
Destructive Potential: {tech.destructive_level}/100
Limitations: {tech.limitations or 'None specified'}
Story Importance: {tech.story_importance or ''}
Discovery History: {tech.discovery_history or ''}
Notes: {tech.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="technology",
                source_name=tech.name,
                source_id=tech.id,
                metadata={
                    "tech_type": str(tech.technology_type),
                    "impact_level": tech.game_changing_level,
                    "factions": tech.factions_with_access
                }
            )
            self.search_engine.index_document(chunk)

    def _index_cultures(self):
        """Index culture data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'cultures'):
            return

        for culture in wb.cultures:
            # Build comprehensive culture text
            rituals = ""
            if hasattr(culture, 'rituals') and culture.rituals:
                rituals = "\n".join(f"  - {r.name}: {r.description}" for r in culture.rituals)

            languages = ""
            if hasattr(culture, 'languages') and culture.languages:
                languages = ", ".join(l.name for l in culture.languages)

            traditions = ""
            if hasattr(culture, 'traditions') and culture.traditions:
                traditions = "\n".join(f"  - {t.name}: {t.description}" for t in culture.traditions)

            content = f"""
Culture: {culture.name}
Associated Factions: {', '.join(culture.associated_factions) if culture.associated_factions else 'None'}
Description: {culture.description or ''}
Values: {culture.values or ''}
Social Structure: {culture.social_structure or ''}
Religion: {culture.religion or ''}
Languages: {languages or 'Unknown'}
Taboos: {culture.taboos or 'None specified'}
Rituals:
{rituals or '  None documented'}
Traditions:
{traditions or '  None documented'}
Clothing Style: {culture.clothing_style or ''}
Architecture Style: {culture.architecture_style or ''}
Notes: {culture.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="culture",
                source_name=culture.name,
                source_id=culture.id,
                metadata={
                    "factions": culture.associated_factions
                }
            )
            self.search_engine.index_document(chunk)

    def _index_historical_events(self):
        """Index historical events."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'historical_events'):
            return

        for event in wb.historical_events:
            participants = ", ".join(event.participants) if event.participants else "Unknown"
            factions = ", ".join(event.factions_involved) if event.factions_involved else "Unknown"

            content = f"""
Historical Event: {event.name}
Year: {event.year or 'Unknown'}
Era: {event.era or 'Unknown'}
Event Type: {event.event_type or 'Unknown'}
Location: {event.location or 'Unknown'}
Description: {event.description}
Causes: {event.causes or 'Unknown'}
Consequences: {event.consequences or 'Unknown'}
Participants: {participants}
Factions Involved: {factions}
Duration: {event.duration or 'Unknown'}
Significance: {event.significance or ''}
Sources: {event.sources or ''}
Notes: {event.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="historical_event",
                source_name=event.name,
                source_id=event.id,
                metadata={
                    "year": event.year,
                    "event_type": event.event_type,
                    "factions": event.factions_involved
                }
            )
            self.search_engine.index_document(chunk)

    def _index_flora_fauna(self):
        """Index flora and fauna."""
        wb = self.project.worldbuilding

        # Flora
        if hasattr(wb, 'flora'):
            for flora in wb.flora:
                properties = []
                if flora.edible:
                    properties.append("Edible")
                if flora.medicinal_properties:
                    properties.append(f"Medicinal: {flora.medicinal_properties}")
                if flora.toxicity:
                    properties.append(f"Toxic: {flora.toxicity}")
                if flora.magical_properties:
                    properties.append(f"Magical: {flora.magical_properties}")

                content = f"""
Flora: {flora.name}
Type: {flora.flora_type.value.replace('_', ' ').title() if hasattr(flora.flora_type, 'value') else flora.flora_type}
Native Planets: {', '.join(flora.native_planets) if flora.native_planets else 'Unknown'}
Preferred Climate: {flora.preferred_climate or 'Unknown'}
Rarity: {flora.rarity or 'Common'}
Description: {flora.description}
Properties: {', '.join(properties) if properties else 'None special'}
Uses: {flora.uses or 'None documented'}
Cultural Significance: {flora.cultural_significance or ''}
Notes: {flora.notes or ''}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="flora",
                    source_name=flora.name,
                    source_id=flora.id,
                    metadata={"flora_type": str(flora.flora_type)}
                )
                self.search_engine.index_document(chunk)

        # Fauna
        if hasattr(wb, 'fauna'):
            for fauna in wb.fauna:
                content = f"""
Fauna: {fauna.name}
Type: {fauna.fauna_type.value.replace('_', ' ').title() if hasattr(fauna.fauna_type, 'value') else fauna.fauna_type}
Native Planets: {', '.join(fauna.native_planets) if fauna.native_planets else 'Unknown'}
Preferred Habitat: {fauna.preferred_habitat or 'Unknown'}
Diet: {fauna.diet or 'Unknown'}
Danger Level: {fauna.danger_level}/100
Size Category: {fauna.size_category or 'Medium'}
Intelligence Level: {fauna.intelligence_level or 'Animal'}
Domestication Status: {fauna.domestication_status or 'Wild'}
Description: {fauna.description}
Behavior: {fauna.behavior or ''}
Abilities: {fauna.abilities or 'None special'}
Weaknesses: {fauna.weaknesses or 'None known'}
Cultural Significance: {fauna.cultural_significance or ''}
Notes: {fauna.notes or ''}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="fauna",
                    source_name=fauna.name,
                    source_id=fauna.id,
                    metadata={
                        "fauna_type": str(fauna.fauna_type),
                        "danger_level": fauna.danger_level
                    }
                )
                self.search_engine.index_document(chunk)

    def _index_myths(self):
        """Index mythology entries."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'myths'):
            return

        for myth in wb.myths:
            figures = ", ".join(myth.key_figures) if myth.key_figures else "None"
            factions = ", ".join(myth.associated_factions) if myth.associated_factions else "Universal"

            content = f"""
Myth/Legend: {myth.name}
Type: {myth.myth_type or 'Legend'}
Believed By: {factions}
Key Figures: {figures}
Description: {myth.description}
Origin Story: {myth.origin or ''}
Moral/Lesson: {myth.moral_lesson or ''}
Truth Behind It: {myth.truth_behind or 'Unknown'}
Related Locations: {', '.join(myth.related_locations) if myth.related_locations else 'None'}
Notes: {myth.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="myth",
                source_name=myth.name,
                source_id=myth.id,
                metadata={
                    "myth_type": myth.myth_type,
                    "factions": myth.associated_factions
                }
            )
            self.search_engine.index_document(chunk)

    def _index_star_systems(self):
        """Index star systems and celestial bodies."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'star_systems'):
            return

        for system in wb.star_systems:
            stars_info = ""
            if hasattr(system, 'stars') and system.stars:
                stars_info = ", ".join(f"{s.name} ({s.spectral_class})" for s in system.stars)

            planets_info = ""
            if hasattr(system, 'planets') and system.planets:
                planets_info = ", ".join(p.name for p in system.planets)

            content = f"""
Star System: {system.name}
Type: {system.system_type}
Galaxy: {system.galaxy or 'Unknown'}
Location: {system.location or 'Unknown'}
Distance from Earth: {system.distance_from_earth or 'Unknown'}
Stars: {stars_info or 'Unknown'}
Planets: {planets_info or 'None discovered'}
Habitable Zone: {system.habitable_zone_inner or '?'} - {system.habitable_zone_outer or '?'}
Description: {system.description or ''}
Key Facts: {system.key_facts or ''}
Controlling Faction: {system.controlling_faction or 'Uncontrolled'}
Notes: {system.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="star_system",
                source_name=system.name,
                source_id=system.id,
                metadata={
                    "system_type": system.system_type,
                    "controlling_faction": system.controlling_faction
                }
            )
            self.search_engine.index_document(chunk)

    def _index_armies(self):
        """Index military/army data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'armies'):
            return

        for army in wb.armies:
            branches_info = ""
            if hasattr(army, 'branches') and army.branches:
                branches_info = "\n".join(
                    f"  - {b.name}: {b.description}" for b in army.branches
                )

            content = f"""
Military Force: {army.name}
Faction: {army.faction or 'Independent'}
Total Personnel: {army.total_personnel or 'Unknown'}
Commander: {army.commander or 'Unknown'}
Description: {army.description or ''}
Doctrine: {army.doctrine or ''}
Branches:
{branches_info or '  None specified'}
Key Technologies: {', '.join(army.key_technologies) if army.key_technologies else 'Standard'}
Strengths: {army.strengths or ''}
Weaknesses: {army.weaknesses or ''}
Notable Campaigns: {army.notable_campaigns or ''}
Notes: {army.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="military",
                source_name=army.name,
                source_id=army.id,
                metadata={"faction": army.faction}
            )
            self.search_engine.index_document(chunk)

    def _index_economies(self):
        """Index economy data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'economies'):
            return

        for economy in wb.economies:
            content = f"""
Economy: {economy.name}
Type: {economy.economy_type.value if hasattr(economy.economy_type, 'value') else economy.economy_type}
Faction/Region: {economy.faction or 'Global'}
Currency: {economy.currency or 'Unknown'}
Description: {economy.description or ''}
Main Industries: {', '.join(economy.main_industries) if economy.main_industries else 'Varied'}
Trade Partners: {', '.join(economy.trade_partners) if economy.trade_partners else 'Various'}
Economic Strength: {economy.strength or 'Moderate'}
Challenges: {economy.challenges or ''}
Notes: {economy.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="economy",
                source_name=economy.name,
                source_id=economy.id,
                metadata={"economy_type": str(economy.economy_type)}
            )
            self.search_engine.index_document(chunk)

    def _index_political_systems(self):
        """Index political system data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'political_systems'):
            return

        for system in wb.political_systems:
            branches_info = ""
            if hasattr(system, 'branches') and system.branches:
                branches_info = "\n".join(
                    f"  - {b.name}: {b.powers}" for b in system.branches
                )

            content = f"""
Political System: {system.name}
Faction: {system.faction or 'Multiple'}
Government Type: {system.government_type or 'Unknown'}
Description: {system.description or ''}
Branches of Government:
{branches_info or '  Not specified'}
Voting/Selection: {system.selection_method or 'Unknown'}
Checks and Balances: {system.checks_balances or ''}
Citizen Rights: {system.citizen_rights or ''}
Notes: {system.notes or ''}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="political_system",
                source_name=system.name,
                source_id=system.id,
                metadata={"government_type": system.government_type}
            )
            self.search_engine.index_document(chunk)

    def _index_characters(self):
        """Index character data."""
        for char in self.project.characters:
            relationships = ""
            if char.social_network:
                relationships = "\n".join(
                    f"  - {name}: {rel}" for name, rel in char.social_network.items()
                )

            content = f"""
Character: {char.name}
Type: {char.character_type}
Personality: {char.personality}
Backstory: {char.backstory}
Relationships:
{relationships or '  None documented'}
Notes: {char.notes}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="character",
                source_name=char.name,
                source_id=char.id,
                metadata={"character_type": char.character_type}
            )
            self.search_engine.index_document(chunk)

    def _index_plot(self):
        """Index plot and story planning data."""
        sp = self.project.story_planning

        # Main plot
        if sp.main_plot:
            chunk = self._make_chunk(
                content=f"Main Plot:\n{sp.main_plot}",
                source_type="plot",
                source_name="Main Plot",
                source_id="main_plot"
            )
            self.search_engine.index_document(chunk)

        # Plot events
        if hasattr(sp.freytag_pyramid, 'events'):
            for event in sp.freytag_pyramid.events:
                content = f"""
Plot Event: {event.title}
Stage: {event.stage.replace('_', ' ').title()}
Act: {event.act}
Description: {event.description}
Outcome: {event.outcome}
Related Characters: {', '.join(event.related_characters) if event.related_characters else 'None'}
Notes: {event.notes}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="plot_event",
                    source_name=event.title,
                    source_id=event.id,
                    metadata={
                        "stage": event.stage,
                        "act": event.act
                    }
                )
                self.search_engine.index_document(chunk)

        # Subplots
        for subplot in sp.subplots:
            content = f"""
Subplot: {subplot.title}
Status: {subplot.status}
Description: {subplot.description}
Connection to Main Plot: {subplot.connection_to_main}
Characters Involved: {', '.join(subplot.characters_involved) if subplot.characters_involved else 'Various'}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="subplot",
                source_name=subplot.title,
                source_id=subplot.id,
                metadata={"status": subplot.status}
            )
            self.search_engine.index_document(chunk)

        # Themes
        if sp.themes:
            content = "Story Themes:\n" + "\n".join(f"- {theme}" for theme in sp.themes)
            chunk = self._make_chunk(
                content=content,
                source_type="themes",
                source_name="Story Themes",
                source_id="themes"
            )
            self.search_engine.index_document(chunk)

    def _index_promises(self):
        """Index story promises."""
        sp = self.project.story_planning
        if not hasattr(sp, 'promises'):
            return

        for promise in sp.promises:
            content = f"""
Story Promise: {promise.title}
Type: {promise.promise_type.title()}
Description: {promise.description}
Related Characters: {', '.join(promise.related_characters) if promise.related_characters else 'All'}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="promise",
                source_name=promise.title,
                source_id=promise.id,
                metadata={"promise_type": promise.promise_type}
            )
            self.search_engine.index_document(chunk)

    def _index_chapter_data(self):
        """Index chapter key points from memory manager."""
        if not self.memory_manager:
            return

        # Get all key points
        key_points = self.memory_manager.get_key_points_for_context(max_points=100)

        for kp in key_points:
            chunk = self._make_chunk(
                content=f"Chapter Key Point ({kp.point_type}): {kp.content}",
                source_type="chapter_key_point",
                source_name=f"Chapter Key Point - {kp.point_type.title()}",
                source_id=f"kp_{kp.chapter_id}_{hash(kp.content) % 10000}",
                metadata={
                    "point_type": kp.point_type,
                    "importance": kp.importance,
                    "chapter_id": kp.chapter_id
                }
            )
            self.search_engine.index_document(chunk)

    def search(
        self,
        query: str,
        method: SearchMethod = SearchMethod.HYBRID,
        top_k: int = 10,
        source_types: Optional[List[str]] = None
    ) -> List[ContextResult]:
        """Search for relevant context.

        Args:
            query: Search query
            method: Search method (KEYWORD, TFIDF, EMBEDDING, HYBRID)
            top_k: Maximum results
            source_types: Optional filter by source types

        Returns:
            List of ContextResult objects
        """
        if not self._indexed:
            self.rebuild_index()

        results = self.search_engine.search(query, method, top_k, source_types)

        return [
            ContextResult(
                content=r.chunk.content,
                source_type=r.chunk.source_type,
                source_name=r.chunk.source_name,
                relevance_score=r.score,
                matched_terms=r.matched_terms,
                match_type=r.match_type,
                metadata=r.chunk.metadata
            )
            for r in results
        ]

    def find_similar(
        self,
        text: str,
        top_k: int = 5,
        method: SearchMethod = SearchMethod.HYBRID
    ) -> List[ContextResult]:
        """Find content similar to the given text.

        Useful when user highlights text and wants to find related content.

        Args:
            text: Text to find similar content for
            top_k: Maximum results
            method: Search method

        Returns:
            List of similar content
        """
        if not self._indexed:
            self.rebuild_index()

        results = self.search_engine.find_similar(text, top_k=top_k, method=method)

        return [
            ContextResult(
                content=r.chunk.content,
                source_type=r.chunk.source_type,
                source_name=r.chunk.source_name,
                relevance_score=r.score,
                matched_terms=r.matched_terms,
                match_type=r.match_type,
                metadata=r.chunk.metadata
            )
            for r in results
        ]

    def get_context_for_ai(
        self,
        query: str,
        max_tokens: int = 2000,
        method: SearchMethod = SearchMethod.HYBRID
    ) -> str:
        """Get formatted context for AI chat.

        Args:
            query: User's query
            max_tokens: Approximate max tokens for context
            method: Search method

        Returns:
            Formatted context string for AI prompt
        """
        results = self.search(query, method, top_k=10)

        if not results:
            return ""

        context_parts = []
        current_tokens = 0
        chars_per_token = 4  # Rough estimate

        for result in results:
            content_tokens = len(result.content) // chars_per_token
            if current_tokens + content_tokens > max_tokens:
                break

            context_parts.append(
                f"[{result.source_type.upper()}: {result.source_name}]\n{result.content}\n"
            )
            current_tokens += content_tokens

        if not context_parts:
            return ""

        return "RELEVANT CONTEXT FROM PROJECT:\n\n" + "\n---\n".join(context_parts)

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return self.search_engine.get_stats()

    def get_all_source_types(self) -> List[str]:
        """Get all available source types in the index."""
        stats = self.get_stats()
        return list(stats.get("documents_by_type", {}).keys())
