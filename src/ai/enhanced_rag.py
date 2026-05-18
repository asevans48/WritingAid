"""Enhanced RAG system with semantic search and comprehensive worldbuilding support."""

from typing import List, Dict, Optional, Any, Set, Tuple, TYPE_CHECKING
from dataclasses import dataclass
import uuid

from src.models.project import WriterProject
from src.ai.semantic_search import (
    SemanticSearchEngine, SearchMethod, DocumentChunk
)
from src.ai.knowledge_graph import KnowledgeGraph

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
    source_id: str = ""  # Entity ID — lets graph-aware consumers look up relations


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
        self.knowledge_graph = KnowledgeGraph()
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

        Each indexer is called independently so one failure doesn't
        prevent the rest from being indexed.
        """
        self.search_engine.clear()

        indexers = [
            self._index_worldbuilding_text,
            self._index_factions,
            self._index_places,
            self._index_technologies,
            self._index_cultures,
            self._index_historical_events,
            self._index_flora_fauna,
            self._index_myths,
            self._index_star_systems,
            self._index_armies,
            self._index_economies,
            self._index_political_systems,
            self._index_encyclopedia,
            self._index_characters,
            self._index_plot,
            self._index_promises,
            # Manuscript drafts and per-chapter planning — the
            # writer's actual prose plus their intent for each
            # chapter. Without these, RAG can answer questions about
            # the encyclopedia + worldbuilding but is blind to the
            # text the user is actually writing.
            self._index_chapter_content,
            self._index_chapter_planning,
        ]

        for indexer in indexers:
            try:
                indexer()
            except Exception as e:
                print(f"RAG indexer {indexer.__name__} failed: {e}")

        if self.memory_manager:
            try:
                self._index_chapter_data()
            except Exception as e:
                print(f"RAG chapter indexer failed: {e}")

        # Build the knowledge graph alongside the search index. Walks
        # the same Pydantic objects but extracts explicit relationships
        # (allies, controls, social_tie, etc.) so retrieved entities
        # can be annotated with their edges at query time.
        try:
            self.knowledge_graph.build_from_project(self.project)
        except Exception as e:
            print(f"RAG knowledge graph build failed: {e}")

        # Co-occurrence scoring: walks the indexed chunks and tags
        # each edge with strong/moderate/weak based on how often its
        # endpoints appear in the same text. The annotation lines
        # then read "ally_of -> Stoneforge Pact (strong)" so the LLM
        # can prioritize active relationships over dormant ones.
        try:
            docs = self.search_engine.tfidf_index.documents.values()
            self.knowledge_graph.score_cooccurrences(docs)
        except Exception as e:
            print(f"RAG cooccurrence scoring failed: {e}")

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

        sections = {}
        for field in ["mythology", "planets", "climate", "history",
                       "politics", "military", "economy", "power_hierarchy"]:
            sections[field] = getattr(wb, field, "")
        custom = getattr(wb, 'custom_sections', {}) or {}
        sections.update(custom)

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
            territory = getattr(faction, 'territory', []) or []
            allies = getattr(faction, 'allies', []) or []
            enemies = getattr(faction, 'enemies', []) or []
            content = f"""
Faction: {faction.name}
Type: {getattr(faction, 'faction_type', '')}
Government: {getattr(faction, 'government_type', '') or 'Unknown'}
Leader: {getattr(faction, 'leader', '') or 'Unknown'}
Territory: {', '.join(territory) if territory else 'Unknown'}
Description: {getattr(faction, 'description', '')}
Military Strength: {getattr(faction, 'military_strength', 0)}
Economic Power: {getattr(faction, 'economic_power', 0)}
Allies: {', '.join(allies) if allies else 'None'}
Enemies: {', '.join(enemies) if enemies else 'None'}
Capital: {getattr(faction, 'capital', '') or ''}
Notes: {getattr(faction, 'notes', '')}
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
            features = getattr(place, 'key_features', []) or []
            inhabitants = getattr(place, 'notable_inhabitants', []) or []

            content = f"""
Place: {place.name}
Type: {getattr(place, 'place_type', '')}
Planet: {getattr(place, 'planet', '') or 'Unknown'}
Continent: {getattr(place, 'continent', '') or 'Unknown'}
Region: {getattr(place, 'region', '') or 'Unknown'}
Controlling Faction: {getattr(place, 'controlling_faction', '') or 'None'}
Population: {getattr(place, 'population', '') or 'Unknown'}
Description: {getattr(place, 'description', '')}
Key Features: {', '.join(features) if features else 'None'}
Atmosphere: {getattr(place, 'atmosphere', '')}
Cultural Significance: {getattr(place, 'cultural_significance', '')}
Story Relevance: {getattr(place, 'story_relevance', '')}
Notable Inhabitants: {', '.join(inhabitants) if inhabitants else 'None'}
Notes: {getattr(place, 'notes', '')}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="place",
                source_name=place.name,
                source_id=place.id,
                metadata={
                    "place_type": str(getattr(place, 'place_type', '')),
                    "planet": getattr(place, 'planet', ''),
                    "controlling_faction": getattr(place, 'controlling_faction', '')
                }
            )
            self.search_engine.index_document(chunk)

    def _index_technologies(self):
        """Index technology data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'technologies'):
            return

        for tech in wb.technologies:
            factions = getattr(tech, 'factions_with_access', []) or []
            prerequisites = getattr(tech, 'prerequisites', []) or []
            applications = getattr(tech, 'applications', []) or []
            tt = getattr(tech, 'technology_type', '')
            type_str = tt.value.replace('_', ' ').title() if hasattr(tt, 'value') else str(tt)

            content = f"""
Technology: {tech.name}
Type: {type_str}
Description: {getattr(tech, 'description', '')}
Factions with Access: {', '.join(factions) if factions else 'All'}
Prerequisites: {', '.join(prerequisites) if prerequisites else 'None'}
Applications: {', '.join(applications) if applications else ''}
Cost to Build: {getattr(tech, 'cost_to_build', '') or 'Unknown'}
Game-Changing Impact: {getattr(tech, 'game_changing_level', 50)}/100
Destructive Potential: {getattr(tech, 'destructive_level', 50)}/100
Limitations: {getattr(tech, 'limitations', '') or 'None specified'}
Story Relevance: {getattr(tech, 'story_relevance', '')}
Notes: {getattr(tech, 'notes', '')}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="technology",
                source_name=tech.name,
                source_id=tech.id,
                metadata={
                    "tech_type": str(getattr(tech, 'technology_type', '')),
                    "impact_level": getattr(tech, 'game_changing_level', 50),
                    "factions": factions
                }
            )
            self.search_engine.index_document(chunk)

    def _index_cultures(self):
        """Index culture data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'cultures'):
            return

        for culture in wb.cultures:
            rituals = ""
            if hasattr(culture, 'rituals') and culture.rituals:
                rituals = "\n".join(
                    f"  - {getattr(r, 'name', '')}: {getattr(r, 'description', '')}"
                    for r in culture.rituals
                )

            languages = ""
            if hasattr(culture, 'languages') and culture.languages:
                languages = ", ".join(getattr(l, 'name', '') for l in culture.languages)

            traditions = ""
            if hasattr(culture, 'traditions') and culture.traditions:
                traditions = "\n".join(
                    f"  - {getattr(t, 'name', '')}: {getattr(t, 'description', '')}"
                    for t in culture.traditions
                )

            factions = getattr(culture, 'associated_factions', []) or []
            core_values = getattr(culture, 'core_values', []) or []
            taboos = getattr(culture, 'taboos', []) or []

            content = f"""
Culture: {culture.name}
Associated Factions: {', '.join(factions) if factions else 'None'}
Description: {getattr(culture, 'description', '')}
Core Values: {', '.join(core_values) if core_values else ''}
Social Structure: {getattr(culture, 'social_structure', '')}
Family Structure: {getattr(culture, 'family_structure', '')}
Coming of Age: {getattr(culture, 'coming_of_age', '')}
Languages: {languages or 'Unknown'}
Taboos: {', '.join(taboos) if taboos else 'None specified'}
Rituals:
{rituals or '  None documented'}
Traditions:
{traditions or '  None documented'}
Notes: {getattr(culture, 'notes', '')}
            """.strip()

            chunk = self._make_chunk(
                content=content,
                source_type="culture",
                source_name=culture.name,
                source_id=culture.id,
                metadata={
                    "factions": factions
                }
            )
            self.search_engine.index_document(chunk)

    def _index_historical_events(self):
        """Index historical events."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'historical_events'):
            return

        for event in wb.historical_events:
            try:
                factions = getattr(event, 'factions_involved', []) or []
                key_figures = getattr(event, 'key_figures', []) or []
                content = f"""
Historical Event: {event.name}
Date: {getattr(event, 'date', '') or getattr(event, 'year', '') or 'Unknown'}
Event Type: {getattr(event, 'event_type', '') or 'Unknown'}
Location: {getattr(event, 'location', '') or 'Unknown'}
Description: {getattr(event, 'description', '')}
Consequences: {getattr(event, 'consequences', '') or ''}
Key Figures: {', '.join(key_figures) if key_figures else 'Unknown'}
Factions Involved: {', '.join(factions) if factions else 'Unknown'}
Notes: {getattr(event, 'notes', '')}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="historical_event",
                    source_name=event.name,
                    source_id=event.id,
                    metadata={
                        "event_type": getattr(event, 'event_type', ''),
                        "factions": factions
                    }
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue  # Skip malformed events

    def _index_flora_fauna(self):
        """Index flora and fauna."""
        wb = self.project.worldbuilding

        if hasattr(wb, 'flora'):
            for flora in wb.flora:
                try:
                    properties = []
                    if getattr(flora, 'edible', False):
                        properties.append("Edible")
                    if getattr(flora, 'medicinal_properties', ''):
                        properties.append(f"Medicinal: {flora.medicinal_properties}")
                    if getattr(flora, 'toxicity', ''):
                        properties.append(f"Toxic: {flora.toxicity}")
                    if getattr(flora, 'magical_properties', ''):
                        properties.append(f"Magical: {flora.magical_properties}")

                    ft = getattr(flora, 'flora_type', '')
                    type_str = ft.value.replace('_', ' ').title() if hasattr(ft, 'value') else str(ft)
                    native = getattr(flora, 'native_planets', []) or []

                    content = f"""
Flora: {flora.name}
Type: {type_str}
Native Planets: {', '.join(native) if native else 'Unknown'}
Preferred Climate: {getattr(flora, 'preferred_climate', '') or 'Unknown'}
Description: {getattr(flora, 'description', '')}
Properties: {', '.join(properties) if properties else 'None special'}
Cultural Significance: {getattr(flora, 'cultural_significance', '')}
Story Relevance: {getattr(flora, 'story_relevance', '')}
Notes: {getattr(flora, 'notes', '')}
                    """.strip()

                    chunk = self._make_chunk(
                        content=content,
                        source_type="flora",
                        source_name=flora.name,
                        source_id=flora.id,
                        metadata={"flora_type": str(getattr(flora, 'flora_type', ''))}
                    )
                    self.search_engine.index_document(chunk)
                except Exception:
                    continue

        if hasattr(wb, 'fauna'):
            for fauna in wb.fauna:
                try:
                    ft = getattr(fauna, 'fauna_type', '')
                    type_str = ft.value.replace('_', ' ').title() if hasattr(ft, 'value') else str(ft)
                    native = getattr(fauna, 'native_planets', []) or []
                    special = getattr(fauna, 'special_abilities', []) or []

                    content = f"""
Fauna: {fauna.name}
Type: {type_str}
Native Planets: {', '.join(native) if native else 'Unknown'}
Habitat: {getattr(fauna, 'habitat', '') or getattr(fauna, 'preferred_climate', '') or 'Unknown'}
Diet: {getattr(fauna, 'diet', '') or 'Unknown'}
Danger Level: {getattr(fauna, 'danger_level', 0)}
Intelligence: {getattr(fauna, 'intelligence_level', '') or 'Animal'}
Domestication: {getattr(fauna, 'domestication_status', '') or 'Wild'}
Description: {getattr(fauna, 'description', '')}
Behavior: {getattr(fauna, 'behavior', '')}
Special Abilities: {', '.join(special) if special else 'None'}
Cultural Significance: {getattr(fauna, 'cultural_significance', '')}
Story Relevance: {getattr(fauna, 'story_relevance', '')}
Notes: {getattr(fauna, 'notes', '')}
                    """.strip()

                    chunk = self._make_chunk(
                        content=content,
                        source_type="fauna",
                        source_name=fauna.name,
                        source_id=fauna.id,
                        metadata={
                            "fauna_type": str(getattr(fauna, 'fauna_type', '')),
                            "danger_level": getattr(fauna, 'danger_level', 0)
                        }
                    )
                    self.search_engine.index_document(chunk)
                except Exception:
                    continue

    def _index_myths(self):
        """Index mythology entries."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'myths'):
            return

        for myth in wb.myths:
            try:
                figures = getattr(myth, 'key_figures', []) or []
                factions = getattr(myth, 'associated_factions', []) or []

                content = f"""
Myth/Legend: {myth.name}
Type: {getattr(myth, 'myth_type', '') or 'Legend'}
Believed By: {', '.join(factions) if factions else 'Universal'}
Key Figures: {', '.join(figures) if figures else 'None'}
Description: {getattr(myth, 'description', '')}
Moral/Lesson: {getattr(myth, 'moral_lesson', '')}
Full Text: {getattr(myth, 'full_text', '')[:500]}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="myth",
                    source_name=myth.name,
                    source_id=myth.id,
                    metadata={
                        "myth_type": getattr(myth, 'myth_type', ''),
                        "factions": factions
                    }
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_star_systems(self):
        """Index star systems and celestial bodies."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'star_systems'):
            return

        for system in wb.star_systems:
            try:
                stars_info = ""
                if hasattr(system, 'stars') and system.stars:
                    stars_info = ", ".join(
                        f"{getattr(s, 'name', '?')} ({getattr(s, 'spectral_class', '?')})"
                        for s in system.stars
                    )

                planets_info = ""
                if hasattr(system, 'planets') and system.planets:
                    planets_info = ", ".join(getattr(p, 'name', '?') for p in system.planets)

                content = f"""
Star System: {system.name}
Type: {getattr(system, 'system_type', '')}
Galaxy: {getattr(system, 'galaxy', '') or 'Unknown'}
Location: {getattr(system, 'location', '') or 'Unknown'}
Stars: {stars_info or 'Unknown'}
Planets: {planets_info or 'None discovered'}
Description: {getattr(system, 'description', '')}
Key Facts: {getattr(system, 'key_facts', '')}
Notes: {getattr(system, 'notes', '')}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="star_system",
                    source_name=system.name,
                    source_id=system.id,
                    metadata={
                        "system_type": str(getattr(system, 'system_type', '')),
                    }
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_armies(self):
        """Index military/army data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'armies'):
            return

        for army in wb.armies:
            try:
                branches_info = ""
                if hasattr(army, 'branches') and army.branches:
                    branches_info = "\n".join(
                        f"  - {getattr(b, 'name', '?')}: {getattr(b, 'description', '')}"
                        for b in army.branches
                    )

                content = f"""
Military Force: {army.name}
Faction: {getattr(army, 'faction_id', '') or getattr(army, 'faction', '') or 'Independent'}
Total Strength: {getattr(army, 'total_strength', '') or 'Unknown'}
Description: {getattr(army, 'description', '')}
Branches:
{branches_info or '  None specified'}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="military",
                    source_name=army.name,
                    source_id=army.id,
                    metadata={"faction": getattr(army, 'faction_id', '')}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_economies(self):
        """Index economy data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'economies'):
            return

        for economy in wb.economies:
            try:
                et = getattr(economy, 'economy_type', '')
                type_str = et.value if hasattr(et, 'value') else str(et)
                major_ind = getattr(economy, 'major_industries', []) or []
                trade_partners = getattr(economy, 'trade_partners', []) or []
                goods = getattr(economy, 'goods', []) or []

                content = f"""
Economy: {economy.name}
Type: {type_str}
Faction: {getattr(economy, 'faction_id', '') or getattr(economy, 'faction', '') or 'Global'}
Currency: {getattr(economy, 'currency', '') or 'Unknown'}
Description: {getattr(economy, 'description', '')}
Major Industries: {', '.join(major_ind) if major_ind else 'Varied'}
Trade Partners: {', '.join(trade_partners) if trade_partners else 'Various'}
Goods: {len(goods)} types
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="economy",
                    source_name=economy.name,
                    source_id=economy.id,
                    metadata={"economy_type": type_str}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_political_systems(self):
        """Index political system data."""
        wb = self.project.worldbuilding
        if not hasattr(wb, 'political_systems'):
            return

        for system in wb.political_systems:
            try:
                branches_info = ""
                if hasattr(system, 'branches') and system.branches:
                    branches_info = "\n".join(
                        f"  - {getattr(b, 'name', '?')}: {getattr(b, 'powers', '')}"
                        for b in system.branches
                    )

                content = f"""
Political System: {getattr(system, 'name', '')}
Faction: {getattr(system, 'faction_id', '') or getattr(system, 'faction', '') or 'Multiple'}
System Type: {getattr(system, 'system_type', '') or 'Unknown'}
Description: {getattr(system, 'description', '')}
Branches:
{branches_info or '  Not specified'}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="political_system",
                    source_name=getattr(system, 'name', ''),
                    source_id=getattr(system, 'id', ''),
                    metadata={"system_type": getattr(system, 'system_type', '')}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_encyclopedia(self):
        """Index encyclopedia entries (base + custom) for RAG search."""
        wb = self.project.worldbuilding

        # Index custom encyclopedia entries stored on the project
        custom_entries = getattr(wb, 'custom_encyclopedia', []) or []

        # Also load the base encyclopedia data
        all_entries = list(custom_entries)
        try:
            from src.ui.worldbuilding.encyclopedia_widget import _load_base_encyclopedia
            base_data = _load_base_encyclopedia()
            for cat in base_data.get("categories", []):
                cat_name = cat["name"]
                for entry in cat.get("entries", []):
                    merged = dict(entry)
                    merged["category"] = cat_name
                    all_entries.append(merged)
        except Exception:
            pass

        for entry in all_entries:
            title = entry.get("title", "")
            if not title:
                continue

            parts = [f"Encyclopedia: {title}"]
            if entry.get("category"):
                parts.append(f"Category: {entry['category']}")
            if entry.get("summary"):
                parts.append(f"Summary: {entry['summary']}")
            if entry.get("description"):
                parts.append(entry["description"])
            if entry.get("writing_tips"):
                parts.append(f"Writing tips: {entry['writing_tips']}")
            if entry.get("examples"):
                parts.append("Examples: " + ", ".join(entry["examples"]))

            content = "\n".join(parts)
            tags = entry.get("tags", [])

            chunk = self._make_chunk(
                content=content,
                source_type="encyclopedia",
                source_name=title,
                source_id=title.lower().replace(" ", "_"),
                metadata={
                    "category": entry.get("category", ""),
                    "tags": tags,
                    "is_custom": entry.get("is_custom", False),
                }
            )
            self.search_engine.index_document(chunk)

    def _index_characters(self):
        """Index character data."""
        for char in self.project.characters:
            try:
                relationships = ""
                if getattr(char, 'social_network', None):
                    relationships = "\n".join(
                        f"  - {name}: {rel}"
                        for name, rel in char.social_network.items()
                    )

                traits = getattr(char, 'personality_traits', []) or []
                content = f"""
Character: {char.name}
Type: {getattr(char, 'character_type', '')}
Personality: {getattr(char, 'personality', '')}
Traits: {', '.join(traits) if traits else ''}
Speaking Style: {getattr(char, 'speaking_style', '')}
Motivations: {getattr(char, 'motivations', '')}
Fears: {getattr(char, 'fears', '')}
Emotional Baseline: {getattr(char, 'emotional_baseline', '')}
Backstory: {getattr(char, 'backstory', '')}
Physical Description: {getattr(char, 'physical_description', '')}
Relationships:
{relationships or '  None documented'}
Notes: {getattr(char, 'notes', '')}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="character",
                    source_name=char.name,
                    source_id=char.id,
                    metadata={"character_type": getattr(char, 'character_type', '')}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

    def _index_plot(self):
        """Index plot and story planning data."""
        sp = getattr(self.project, 'story_planning', None)
        if not sp:
            return

        # Main plot
        if getattr(sp, 'main_plot', ''):
            chunk = self._make_chunk(
                content=f"Main Plot:\n{sp.main_plot}",
                source_type="plot",
                source_name="Main Plot",
                source_id="main_plot"
            )
            self.search_engine.index_document(chunk)

        # Plot events
        fp = getattr(sp, 'freytag_pyramid', None)
        if fp and hasattr(fp, 'events'):
            for event in fp.events:
                try:
                    chars = getattr(event, 'related_characters', []) or []
                    content = f"""
Plot Event: {getattr(event, 'title', '')}
Stage: {getattr(event, 'stage', '').replace('_', ' ').title()}
Act: {getattr(event, 'act', 1)}
Description: {getattr(event, 'description', '')}
Outcome: {getattr(event, 'outcome', '')}
Related Characters: {', '.join(chars) if chars else 'None'}
Notes: {getattr(event, 'notes', '')}
                    """.strip()

                    chunk = self._make_chunk(
                        content=content,
                        source_type="plot_event",
                        source_name=getattr(event, 'title', ''),
                        source_id=getattr(event, 'id', ''),
                        metadata={
                            "stage": getattr(event, 'stage', ''),
                            "act": getattr(event, 'act', 1)
                        }
                    )
                    self.search_engine.index_document(chunk)
                except Exception:
                    continue

        # Subplots
        for subplot in getattr(sp, 'subplots', []):
            try:
                chars = getattr(subplot, 'related_characters', []) or []
                content = f"""
Subplot: {getattr(subplot, 'title', '')}
Status: {getattr(subplot, 'status', 'active')}
Description: {getattr(subplot, 'description', '')}
Connection to Main Plot: {getattr(subplot, 'connection_to_main', '')}
Related Characters: {', '.join(chars) if chars else 'Various'}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="subplot",
                    source_name=getattr(subplot, 'title', ''),
                    source_id=getattr(subplot, 'id', ''),
                    metadata={"status": getattr(subplot, 'status', 'active')}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

        # Themes
        themes = getattr(sp, 'themes', []) or []
        if themes:
            content = "Story Themes:\n" + "\n".join(f"- {theme}" for theme in themes)
            chunk = self._make_chunk(
                content=content,
                source_type="themes",
                source_name="Story Themes",
                source_id="themes"
            )
            self.search_engine.index_document(chunk)

    def _index_promises(self):
        """Index story promises."""
        sp = getattr(self.project, 'story_planning', None)
        if not sp or not hasattr(sp, 'promises'):
            return

        for promise in getattr(sp, 'promises', []):
            try:
                chars = getattr(promise, 'related_characters', []) or []
                content = f"""
Story Promise: {getattr(promise, 'title', '')}
Type: {getattr(promise, 'promise_type', '').title()}
Description: {getattr(promise, 'description', '')}
Related Characters: {', '.join(chars) if chars else 'All'}
                """.strip()

                chunk = self._make_chunk(
                    content=content,
                    source_type="promise",
                    source_name=getattr(promise, 'title', ''),
                    source_id=getattr(promise, 'id', ''),
                    metadata={"promise_type": getattr(promise, 'promise_type', '')}
                )
                self.search_engine.index_document(chunk)
            except Exception:
                continue

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

    def _split_chapter_for_index(self, content: str,
                                 target_chars: int = 2400,
                                 min_chars: int = 600) -> List[str]:
        """Split a chapter's prose into paragraph-aligned chunks.

        Each chunk targets ~2400 chars (~600 tokens) so a retrieved
        chunk is small enough to fit alongside other RAG context but
        big enough to convey scene + voice. We pack whole paragraphs
        until the next one would push us over the target, which
        avoids splitting mid-paragraph and keeps the prose coherent.
        """
        if not content or not content.strip():
            return []
        import re
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', content)
                      if p.strip()]
        chunks: List[str] = []
        buf = ""
        for para in paragraphs:
            if not buf:
                buf = para
                continue
            if len(buf) + len(para) + 2 > target_chars:
                chunks.append(buf)
                buf = para
            else:
                buf += "\n\n" + para
        if buf and len(buf) >= min_chars:
            chunks.append(buf)
        elif buf and chunks:
            # Fold a too-small trailing buffer into the previous chunk
            # rather than creating a stub that won't retrieve well.
            chunks[-1] = chunks[-1] + "\n\n" + buf
        elif buf:
            chunks.append(buf)
        return chunks

    def _index_chapter_content(self):
        """Index manuscript chapter prose so RAG can retrieve actual
        draft text — not just key points — when answering questions
        about chat / characters / worldbuilding / plot.

        Each chapter's prose is split into paragraph-aligned chunks
        (~600 tokens each). Source type is ``chapter_content`` so
        downstream consumers can filter or weight differently from
        encyclopedia / planning entries if they want.
        """
        manuscript = getattr(self.project, 'manuscript', None)
        chapters = getattr(manuscript, 'chapters', None) if manuscript else None
        if not chapters:
            return

        for ch in chapters:
            content = getattr(ch, 'content', '') or ''
            if not content.strip():
                continue
            number = getattr(ch, 'number', 0)
            title = getattr(ch, 'title', '') or f"Chapter {number}"
            display = f"Ch. {number}: {title}" if number else title
            for i, chunk_text in enumerate(
                    self._split_chapter_for_index(content)):
                chunk = self._make_chunk(
                    content=f"From {display} (excerpt):\n{chunk_text}",
                    source_type="chapter_content",
                    source_name=display,
                    source_id=f"chcontent_{getattr(ch, 'id', number)}_{i}",
                    metadata={
                        "chapter_id": getattr(ch, 'id', ''),
                        "chapter_number": number,
                        "chunk_index": i,
                    }
                )
                self.search_engine.index_document(chunk)

    def _index_chapter_planning(self):
        """Index per-chapter planning blocks: description, outline,
        scenes, POV, tone, voice, style, pacing, themes, featured
        characters, locations, organized notes, and subplot notes.

        These planning blocks usually carry the writer's *intent* for
        a chapter — exactly the kind of context the character /
        worldbuilding / plot agents should see when the user asks
        about elements that appear in or near a chapter.
        """
        manuscript = getattr(self.project, 'manuscript', None)
        chapters = getattr(manuscript, 'chapters', None) if manuscript else None
        if not chapters:
            return

        for ch in chapters:
            planning = getattr(ch, 'planning', None)
            if not planning:
                continue
            number = getattr(ch, 'number', 0)
            title = getattr(ch, 'title', '') or f"Chapter {number}"
            display = f"Ch. {number}: {title}" if number else title

            parts: List[str] = [f"Chapter Planning — {display}"]

            def _add(label: str, value: str) -> None:
                if value and str(value).strip():
                    parts.append(f"{label}: {str(value).strip()}")

            _add("Description", getattr(planning, 'description', ''))
            _add("Outline", getattr(planning, 'outline', ''))
            _add("POV character", getattr(planning, 'pov_character', ''))
            _add("Timeline", getattr(planning, 'timeline_position', ''))
            _add("Tone", getattr(planning, 'tone', ''))
            _add("Voice", getattr(planning, 'voice', ''))
            _add("Style", getattr(planning, 'style', ''))
            _add("Pacing", getattr(planning, 'pacing', ''))

            scenes = getattr(planning, 'scene_list', []) or []
            if scenes:
                parts.append("Scenes:\n" + "\n".join(
                    f"  - {s}" for s in scenes))
            featured = getattr(planning, 'characters_featured', []) or []
            if featured:
                parts.append("Featured characters: " + ", ".join(featured))
            locations = getattr(planning, 'locations', []) or []
            if locations:
                parts.append("Locations: " + ", ".join(locations))
            themes = getattr(planning, 'themes', []) or []
            if themes:
                parts.append("Themes: " + ", ".join(themes))

            # ``notes_as_text`` and ``subplots_as_text`` already
            # flatten nested structures into prompt-ready prose.
            notes_text = getattr(planning, 'notes_as_text', "")
            if notes_text and notes_text.strip():
                parts.append(f"Notes:\n{notes_text.strip()}")
            subplots_text = getattr(planning, 'subplots_as_text', "")
            if subplots_text and subplots_text.strip():
                parts.append(f"Subplot threads:\n{subplots_text.strip()}")

            # If nothing beyond the header was added we skip — a
            # planning block with only the title carries no signal.
            if len(parts) <= 1:
                continue

            chunk = self._make_chunk(
                content="\n\n".join(parts),
                source_type="chapter_planning",
                source_name=f"Planning: {display}",
                source_id=f"chplan_{getattr(ch, 'id', number)}",
                metadata={
                    "chapter_id": getattr(ch, 'id', ''),
                    "chapter_number": number,
                    "pov_character": getattr(planning, 'pov_character', ''),
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
                metadata=r.chunk.metadata,
                source_id=r.chunk.source_id,
            )
            for r in results
        ]

    def search_with_neighbors(
        self,
        query: str,
        top_k: int = 10,
        method: SearchMethod = SearchMethod.HYBRID,
        source_types: Optional[List[str]] = None,
        max_neighbors_per_seed: int = 2,
        min_neighbor_score: float = 0.05,
        candidate_pool_factor: int = 5,
        hops: int = 1,
        second_hop_decay: float = 0.7,
        max_second_hop_per_intermediate: int = 1,
    ) -> List[ContextResult]:
        """Search + multi-hop graph expansion with query-relevance scoring.

        Runs the normal search to get the top-K primary results, then
        for each primary result that maps to a knowledge-graph node:

          1. Walks its outgoing graph edges to find candidate neighbors.
          2. Looks up each neighbor's query-relevance score from a
             broader candidate-pool search (top_k * candidate_pool_factor)
             — re-using existing TF-IDF/hybrid scoring instead of
             recomputing it.
          3. Multiplies that score by ``KnowledgeGraph.expansion_tier_multiplier``
             for the edge's ``cooccur_tier`` so strong edges promote
             neighbors more eagerly than weak ones.
          4. Promotes up to ``max_neighbors_per_seed`` neighbors per
             seed whose final score >= ``min_neighbor_score``.

        When ``hops >= 2``, each *promoted* 1-hop neighbor becomes a
        bridge: we walk its outgoing edges to find 2-hop candidates.
        Only neighbors that *would themselves be promoted* serve as
        bridges, so the path quality is gated end-to-end. Combined
        multiplier is ``tier(seed→N1) × tier(N1→N2) × second_hop_decay``
        so 2-hop scores decay against 1-hop scores naturally.

        Each promoted result carries provenance in its metadata:
        ``promoted_from_seed_type``, ``promoted_from_seed_id``,
        ``promoted_via_relation``, ``promoted_tier`` for 1-hop;
        additionally ``promoted_path`` (list of dicts, one per edge
        in the walk) and ``promoted_hops`` for multi-hop entries. Its
        ``match_type`` is set to ``"graph_neighbor"`` so callers can
        render it differently from direct retrieval results.

        Returns the primary results followed by the promoted neighbors,
        with no deduplication beyond skipping neighbors that are
        already in the primary set or already promoted earlier in the
        same call (a 2-hop candidate reachable via two bridges keeps
        only the best-scoring path).
        """
        primary = self.search(
            query=query, method=method, top_k=top_k,
            source_types=source_types)
        if not primary:
            return primary

        primary_keys: Set[Tuple[str, str]] = {
            (r.source_type, r.source_id)
            for r in primary if r.source_id
        }

        # Build a score map from a broader search so we get TF-IDF
        # relevance for any candidate neighbor without recomputing
        # vectors. We deliberately don't pass ``source_types`` here —
        # graph neighbors may be of a different type than the user's
        # original filter (e.g., a character connected to a faction).
        pool_size = max(top_k * candidate_pool_factor, len(primary) + 20)
        pool = self.search(
            query=query, method=method,
            top_k=pool_size, source_types=None)
        score_map: Dict[Tuple[str, str], ContextResult] = {
            (r.source_type, r.source_id): r
            for r in pool if r.source_id
        }

        # --- First-hop expansion -----------------------------------
        # Collect (seed, relation, edge_data) candidates per
        # neighbor. A neighbor reachable from multiple seeds keeps
        # the best (highest tier-multiplier) introducer; the others
        # are ignored to keep the per-seed cap fair.
        first_hop_candidates: Dict[
            Tuple[str, str],
            Tuple[Tuple[str, str], str, Dict[str, Any], float]
        ] = {}
        for r in primary:
            if not r.source_id:
                continue
            seed = (r.source_type, r.source_id)
            if seed not in self.knowledge_graph.graph:
                continue
            for relation, neighbor, edge_data in (
                    self.knowledge_graph.edges_of(
                        seed, include_incoming=False)):
                if neighbor in primary_keys:
                    continue
                if neighbor[0] not in (
                        self.knowledge_graph.ANNOTATABLE_TYPES):
                    continue
                tier = (edge_data or {}).get("cooccur_tier", "")
                mult = (self.knowledge_graph
                            .expansion_tier_multiplier(tier))
                existing = first_hop_candidates.get(neighbor)
                if existing is None or mult > existing[3]:
                    first_hop_candidates[neighbor] = (
                        seed, relation, edge_data or {}, mult)

        promoted_by_node: Dict[Tuple[str, str], ContextResult] = {}
        # Tracks (seed → bridge → final_score) so 2-hop walks can
        # combine multipliers correctly.
        first_hop_promoted_bridges: List[
            Tuple[Tuple[str, str], str, Dict[str, Any], float,
                  Tuple[str, str], float]
        ] = []  # (seed, relation, edge_data, seed_tier_mult, bridge, bridge_final_score)
        per_seed_counts: Dict[Tuple[str, str], int] = {}

        for neighbor, (seed, relation, edge_data, mult) in (
                first_hop_candidates.items()):
            scored = score_map.get(neighbor)
            if scored is None:
                continue
            final_score = scored.relevance_score * mult
            if final_score < min_neighbor_score:
                continue
            if per_seed_counts.get(seed, 0) >= max_neighbors_per_seed:
                continue
            tier = edge_data.get("cooccur_tier", "")
            new_metadata = dict(scored.metadata or {})
            new_metadata.update({
                "promoted_from_seed_type": seed[0],
                "promoted_from_seed_id":   seed[1],
                "promoted_via_relation":   relation,
                "promoted_tier":           tier,
                "promoted_base_score":     scored.relevance_score,
                "promoted_hops":           1,
            })
            promoted = ContextResult(
                content=scored.content,
                source_type=scored.source_type,
                source_name=scored.source_name,
                relevance_score=final_score,
                matched_terms=scored.matched_terms,
                match_type="graph_neighbor",
                metadata=new_metadata,
                source_id=scored.source_id,
            )
            per_seed_counts[seed] = per_seed_counts.get(seed, 0) + 1
            promoted_by_node[neighbor] = promoted
            first_hop_promoted_bridges.append(
                (seed, relation, edge_data, mult, neighbor, final_score))

        # --- Second-hop expansion ----------------------------------
        # Only walks from bridges that already cleared the 1-hop bar —
        # so an irrelevant 1-hop neighbor cannot drag in a 2-hop
        # neighbor. Combined multiplier compounds both edge tiers and
        # applies ``second_hop_decay`` to penalize the extra distance.
        if hops >= 2 and first_hop_promoted_bridges:
            per_bridge_counts: Dict[Tuple[str, str], int] = {}
            for (seed, seed_rel, seed_edge_data, seed_mult,
                 bridge, _bridge_score) in first_hop_promoted_bridges:
                if bridge not in self.knowledge_graph.graph:
                    continue
                for rel2, hop2_node, hop2_edge_data in (
                        self.knowledge_graph.edges_of(
                            bridge, include_incoming=False)):
                    if hop2_node == seed:
                        continue  # don't walk back to where we came from
                    if hop2_node in primary_keys:
                        continue
                    if hop2_node in promoted_by_node:
                        continue  # already promoted at 1-hop
                    if hop2_node[0] not in (
                            self.knowledge_graph.ANNOTATABLE_TYPES):
                        continue
                    if per_bridge_counts.get(bridge, 0) >= (
                            max_second_hop_per_intermediate):
                        continue
                    scored2 = score_map.get(hop2_node)
                    if scored2 is None:
                        continue
                    tier2 = (hop2_edge_data or {}).get(
                        "cooccur_tier", "")
                    mult2 = (self.knowledge_graph
                                 .expansion_tier_multiplier(tier2))
                    combined_mult = (
                        seed_mult * mult2 * second_hop_decay)
                    final_score2 = (
                        scored2.relevance_score * combined_mult)
                    if final_score2 < min_neighbor_score:
                        continue
                    # Path: seed --seed_rel--> bridge --rel2--> hop2_node
                    bridge_name = (
                        self.knowledge_graph.graph.nodes[bridge].get(
                            "name", bridge[1]))
                    seed_tier = seed_edge_data.get("cooccur_tier", "")
                    path = [
                        {
                            "from_type": seed[0],
                            "from_id":   seed[1],
                            "relation":  seed_rel,
                            "tier":      seed_tier,
                        },
                        {
                            "from_type": bridge[0],
                            "from_id":   bridge[1],
                            "from_name": bridge_name,
                            "relation":  rel2,
                            "tier":      tier2,
                        },
                    ]
                    new_metadata = dict(scored2.metadata or {})
                    new_metadata.update({
                        "promoted_from_seed_type": seed[0],
                        "promoted_from_seed_id":   seed[1],
                        "promoted_via_relation":   rel2,
                        "promoted_tier":           tier2,
                        "promoted_base_score":     scored2.relevance_score,
                        "promoted_hops":           2,
                        "promoted_path":           path,
                    })
                    existing = promoted_by_node.get(hop2_node)
                    if (existing is not None
                            and existing.relevance_score
                                >= final_score2):
                        # Already reached via a better path — keep it.
                        continue
                    promoted2 = ContextResult(
                        content=scored2.content,
                        source_type=scored2.source_type,
                        source_name=scored2.source_name,
                        relevance_score=final_score2,
                        matched_terms=scored2.matched_terms,
                        match_type="graph_neighbor",
                        metadata=new_metadata,
                        source_id=scored2.source_id,
                    )
                    promoted_by_node[hop2_node] = promoted2
                    per_bridge_counts[bridge] = (
                        per_bridge_counts.get(bridge, 0) + 1)

        promoted_sorted = sorted(
            promoted_by_node.values(),
            key=lambda r: -r.relevance_score)
        return list(primary) + promoted_sorted

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
                metadata=r.chunk.metadata,
                source_id=r.chunk.source_id,
            )
            for r in results
        ]

    def get_context_for_ai(
        self,
        query: str,
        max_tokens: int = 2000,
        method: SearchMethod = SearchMethod.HYBRID,
        expand_graph: bool = True,
        expand_neighbors: bool = False,
        max_neighbors_per_seed: int = 2,
    ) -> str:
        """Get formatted context for AI chat.

        Searches both the project index AND the external knowledge store
        (Wikipedia, Britannica) if articles have been downloaded.

        Two graph-aware enrichments, controllable independently:

          * ``expand_graph`` (default on, cheap) — each retrieved entity
            that exists in the knowledge graph gets a compact
            ``Relationships:`` line listing its outgoing edges with
            co-occurrence tiers.

          * ``expand_neighbors`` (default off, costs additional
            chunks) — runs ``search_with_neighbors`` so 1-hop graph
            neighbors that score well against the query are *promoted*
            into the context as additional chunks. Each promoted
            chunk is labelled with ``(via <relation> from <seed>)`` so
            the LLM understands where it came from.

        Args:
            query: User's query
            max_tokens: Approximate max tokens for context
            method: Search method
            expand_graph: Annotate retrieved entities with their graph edges
            expand_neighbors: Promote query-relevant graph neighbors into context
            max_neighbors_per_seed: Cap when expand_neighbors is on

        Returns:
            Formatted context string for AI prompt
        """
        # Search the project index — with graph expansion when asked.
        if expand_neighbors:
            results = self.search_with_neighbors(
                query=query, method=method, top_k=10,
                max_neighbors_per_seed=max_neighbors_per_seed)
        else:
            results = self.search(query, method, top_k=10)

        context_parts = []
        current_tokens = 0
        chars_per_token = 4

        for result in results:
            relations_line = ""
            if expand_graph and result.source_id:
                relations_line = self._format_relations_line(
                    result.source_type, result.source_id)
            header = f"[{result.source_type.upper()}: {result.source_name}"
            # Promoted-neighbor provenance label. The seed name comes
            # from the graph so it tracks renames automatically.
            # For 2-hop promotions we render the full path so the LLM
            # can judge how indirect the connection is.
            if result.match_type == "graph_neighbor":
                meta = result.metadata or {}
                via_label = self._format_promoted_via_label(meta)
                if via_label:
                    header += f"  ({via_label})"
            block = f"{header}]\n{result.content}\n"
            if relations_line:
                block += f"Relationships: {relations_line}\n"
            content_tokens = len(block) // chars_per_token
            if current_tokens + content_tokens > max_tokens:
                break
            context_parts.append(block)
            current_tokens += content_tokens

        # Search the external knowledge store (Wikipedia, Britannica, etc.)
        remaining_tokens = max_tokens - current_tokens
        if remaining_tokens > 200:
            kb_parts = self._search_knowledge_store(query, remaining_tokens)
            if kb_parts:
                context_parts.extend(kb_parts)

        if not context_parts:
            return ""

        return "RELEVANT CONTEXT:\n\n" + "\n---\n".join(context_parts)

    def _format_promoted_via_label(self, metadata: Dict[str, Any]) -> str:
        """Render the 'via X from Y' / 'via path' label for promoted
        graph-neighbor chunks.

        Single-hop reads like ``via ally_of from Iron League``;
        2-hop reads like ``via inhabited_by → Highveld, controlled_by
        → Iron League, 2 hops`` so the LLM sees the full bridge.
        """
        hops = metadata.get("promoted_hops", 1)
        path = metadata.get("promoted_path")
        if hops >= 2 and path:
            # Render the full chain: each step is "<relation> -> <node>".
            steps = []
            for step in path[:-1]:
                # Intermediate node — use its from_name if available
                # (set when the path was constructed).
                rel = step.get("relation", "?")
                steps.append(f"{rel}")
            last = path[-1]
            last_rel = last.get("relation", "?")
            bridge_name = last.get("from_name", "")
            if bridge_name:
                return (f"via {steps[0]} → {bridge_name}, "
                        f"{last_rel}, {hops} hops")
            return f"via {' → '.join(steps + [last_rel])}, {hops} hops"
        # 1-hop fallback
        seed_type = metadata.get("promoted_from_seed_type", "")
        seed_id = metadata.get("promoted_from_seed_id", "")
        relation = metadata.get("promoted_via_relation", "")
        if not (seed_type and seed_id and relation):
            return ""
        seed_node = (seed_type, seed_id)
        if seed_node not in self.knowledge_graph.graph:
            return ""
        seed_name = self.knowledge_graph.graph.nodes[seed_node].get(
            "name", seed_id)
        return f"via {relation} from {seed_name}"

    def _format_relations_line(self, source_type: str, source_id: str) -> str:
        """Compact one-line render of a node's edges for prompt context.

        Delegates to ``KnowledgeGraph.format_relations_line`` so chat-
        side callers in main_window share the same rendering. Returns
        "" when the entity has no graph node or no edges.
        """
        return self.knowledge_graph.format_relations_line(
            source_type, source_id,
            max_edges=12,
            include_incoming=True,
        )

    def _search_knowledge_store(self, query: str, max_tokens: int) -> list:
        """Search the external knowledge store for relevant articles.

        Respects the enable_knowledge_base setting. Returns empty if disabled.
        """
        try:
            # Check if knowledge base is enabled in settings
            from src.config.ai_config import get_ai_config
            config = get_ai_config()
            if not config.get_settings().get("enable_knowledge_base", True):
                return []

            from src.knowledge.knowledge_store import get_knowledge_store
            store = get_knowledge_store()

            if store.get_article_count() == 0:
                return []

            articles = store.search(query, max_results=5)
            if not articles:
                return []

            parts = []
            current_tokens = 0
            chars_per_token = 4

            for article in articles:
                # Truncate long articles to a useful snippet
                content = article.content[:1500]
                content_tokens = len(content) // chars_per_token
                if current_tokens + content_tokens > max_tokens:
                    break
                source_label = article.source.upper()
                parts.append(
                    f"[{source_label}: {article.title}]\n{content}\n"
                )
                current_tokens += content_tokens

            return parts
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return self.search_engine.get_stats()

    def get_all_source_types(self) -> List[str]:
        """Get all available source types in the index."""
        stats = self.get_stats()
        return list(stats.get("documents_by_type", {}).keys())
