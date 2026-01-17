"""Project model - Root level encapsulating all writer work."""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from pathlib import Path
import json

from src.models.worldbuilding_objects import Faction, Myth, ClimatePreset, Flora, Fauna, Technology, Star, StarSystem, Place, Culture, Army, Economy, HistoricalEvent, PowerHierarchy, PoliticalSystem, WorldMap


class WorldBuilding(BaseModel):
    """Worldbuilding section with subsections and individual elements."""
    # Legacy single-text fields (for backwards compatibility)
    mythology: str = ""
    planets: str = ""
    climate: str = ""
    history: str = ""
    politics: str = ""
    military: str = ""
    economy: str = ""
    power_hierarchy: str = ""
    custom_sections: Dict[str, str] = Field(default_factory=dict)

    # Individual elements per category (legacy format for backwards compatibility)
    # Format: {category: {element_name: element_description}}
    mythology_elements: Dict[str, str] = Field(default_factory=dict)
    planets_elements: Dict[str, str] = Field(default_factory=dict)
    climate_elements: Dict[str, str] = Field(default_factory=dict)
    history_elements: Dict[str, str] = Field(default_factory=dict)
    politics_elements: Dict[str, str] = Field(default_factory=dict)
    military_elements: Dict[str, str] = Field(default_factory=dict)
    economy_elements: Dict[str, str] = Field(default_factory=dict)
    power_hierarchy_elements: Dict[str, str] = Field(default_factory=dict)

    # New: Structured worldbuilding objects
    factions: List[Faction] = Field(default_factory=list)
    myths: List[Myth] = Field(default_factory=list)
    places: List[Place] = Field(default_factory=list)  # Places and landmarks
    climate_presets: List[ClimatePreset] = Field(default_factory=list)
    technologies: List[Technology] = Field(default_factory=list)
    flora: List[Flora] = Field(default_factory=list)
    fauna: List[Fauna] = Field(default_factory=list)
    stars: List[Star] = Field(default_factory=list)
    star_systems: List[StarSystem] = Field(default_factory=list)
    cultures: List[Culture] = Field(default_factory=list)  # Cultural systems
    armies: List['Army'] = Field(default_factory=list)  # Military forces linked to factions
    economies: List[Economy] = Field(default_factory=list)  # Economic systems for factions
    maps: List['WorldMap'] = Field(default_factory=list)  # Interactive maps
    historical_events: List[HistoricalEvent] = Field(default_factory=list)  # Timeline events
    hierarchies: List[PowerHierarchy] = Field(default_factory=list)  # Power hierarchies
    political_systems: List[PoliticalSystem] = Field(default_factory=list)  # Political systems

    @field_validator('maps', mode='before')
    @classmethod
    def convert_none_to_empty_list(cls, v):
        """Convert None to empty list for backward compatibility."""
        return v if v is not None else []


class Character(BaseModel):
    """Character with full details including image, personality, backstory."""
    id: str
    name: str
    character_type: str  # antagonist, protagonist, major, minor
    image_path: Optional[str] = None
    personality: str = ""
    backstory: str = ""
    social_network: Dict[str, str] = Field(default_factory=dict)  # relationship mapping
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class StoryPromise(BaseModel):
    """A promise/commitment made to readers about the story."""
    id: str
    promise_type: str  # tone, plot, genre, character
    title: str  # Brief summary of the promise
    description: str = ""  # Detailed description
    related_characters: List[str] = Field(default_factory=list)  # For character promises
    created_at: datetime = Field(default_factory=datetime.now)


class PlotEvent(BaseModel):
    """Individual event in the plot structure."""
    id: str
    title: str
    description: str = ""
    outcome: str = ""  # What happens as a result
    stage: str = "rising_action"  # exposition, rising_action, climax, falling_action, resolution
    act: int = 1  # Act number (1-based)
    intensity: int = 50  # 0-100, determines vertical position in pyramid
    sort_order: int = 0  # Order within the stage
    related_characters: List[str] = Field(default_factory=list)
    related_subplots: List[str] = Field(default_factory=list)  # Subplot IDs
    notes: str = ""


class FreytagPyramid(BaseModel):
    """Freytag's dramatic structure for story planning with detailed events."""
    # Legacy text fields (for backwards compatibility)
    exposition: str = ""
    rising_action: str = ""
    climax: str = ""
    falling_action: str = ""
    resolution: str = ""

    # Act configuration
    num_acts: int = 3  # Default to 3-act structure
    act_names: List[str] = Field(default_factory=lambda: ["Act I", "Act II", "Act III"])

    # Detailed events with intensity tracking
    events: List[PlotEvent] = Field(default_factory=list)


class Subplot(BaseModel):
    """Subplot connected to main plot with its own event arc."""
    id: str
    title: str
    description: str
    connection_to_main: str = ""
    related_characters: List[str] = Field(default_factory=list)

    # Subplot events (mirrors main plot structure)
    events: List[PlotEvent] = Field(default_factory=list)
    status: str = "active"  # active, resolved, abandoned


class StoryPlanning(BaseModel):
    """Story planning with Freytag pyramid and plot structure."""
    freytag_pyramid: FreytagPyramid = Field(default_factory=FreytagPyramid)
    main_plot: str = ""
    subplots: List[Subplot] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    promises: List[StoryPromise] = Field(default_factory=list)  # Commitments to readers


class ChapterRevision(BaseModel):
    """Revision history for a chapter."""
    revision_number: int
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: str = ""


class Annotation(BaseModel):
    """Annotation/note attached to a specific line in a chapter."""
    id: str
    line_number: int
    annotation_type: str = "note"  # note, attribution, recommendation
    content: str = ""

    # For attributions - references to other elements
    referenced_type: Optional[str] = None  # character, chapter, myth, worldbuilding, etc.
    referenced_id: Optional[str] = None
    referenced_name: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Chapter(BaseModel):
    """Chapter unit for manuscript."""
    id: str
    number: int
    title: str
    content: str = ""  # Plain text content (for word count, search, AI analysis)
    html_content: str = ""  # Rich text HTML content (for formatting preservation)
    file_path: Optional[str] = None  # Relative path to chapter file within project
    revisions: List[ChapterRevision] = Field(default_factory=list)
    annotations: List[Annotation] = Field(default_factory=list)  # Line-specific notes and attributions
    notes: str = ""
    word_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_revision(self, notes: str = ""):
        """Save current content as a revision."""
        revision = ChapterRevision(
            revision_number=len(self.revisions) + 1,
            content=self.content,
            notes=notes
        )
        self.revisions.append(revision)

    def load_content_from_file(self, project_dir: Path) -> bool:
        """Load chapter content from external file."""
        if not self.file_path:
            return False

        full_path = project_dir / self.file_path
        if full_path.exists():
            self.content = full_path.read_text(encoding='utf-8')
            return True
        return False

    def save_content_to_file(self, project_dir: Path) -> bool:
        """Save chapter content to external file."""
        # Always regenerate file path based on current chapter number
        # This ensures reordered chapters save to the correct files
        self.file_path = f"chapters/chapter_{self.number:03d}.md"

        full_path = project_dir / self.file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(self.content, encoding='utf-8')
        return True


class Manuscript(BaseModel):
    """Manuscript containing chapters."""
    title: str = "Untitled Manuscript"
    author: str = ""
    chapters: List[Chapter] = Field(default_factory=list)
    total_word_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class GeneratedImage(BaseModel):
    """Generated image for cover art or scene visualization."""
    id: str
    image_path: str
    prompt: str
    image_type: str  # cover, character, scene
    associated_id: Optional[str] = None  # character ID or chapter ID
    created_at: datetime = Field(default_factory=datetime.now)


class AgentContact(BaseModel):
    """Literary agent or publisher contact."""
    id: str
    name: str
    agency: str = ""
    email: str = ""
    phone: str = ""
    notes: str = ""
    submissions: List[Dict] = Field(default_factory=list)  # submission history


class ProjectDictionary(BaseModel):
    """Custom dictionary for project-specific terms."""
    words: List[str] = Field(default_factory=list)
    definitions: Dict[str, str] = Field(default_factory=dict)


class WriterProject(BaseModel):
    """Root project model encapsulating all writer work."""
    name: str
    description: str = ""
    project_path: Optional[str] = None

    # Core sections
    worldbuilding: WorldBuilding = Field(default_factory=WorldBuilding)
    characters: List[Character] = Field(default_factory=list)
    story_planning: StoryPlanning = Field(default_factory=StoryPlanning)
    manuscript: Manuscript = Field(default_factory=Manuscript)
    generated_images: List[GeneratedImage] = Field(default_factory=list)
    agent_contacts: List[AgentContact] = Field(default_factory=list)
    dictionary: ProjectDictionary = Field(default_factory=ProjectDictionary)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def save_project(self, file_path: str, save_chapters_separately: bool = True):
        """Save project to JSON file.

        Args:
            file_path: Path to save the project.json file
            save_chapters_separately: If True, save chapters as separate files
        """
        self.updated_at = datetime.now()
        project_dir = Path(file_path).parent

        # Save chapters to separate files if enabled
        if save_chapters_separately:
            for chapter in self.manuscript.chapters:
                chapter.save_content_to_file(project_dir)
                # Clear content from JSON to save space
                original_content = chapter.content
                chapter.content = ""  # Will be loaded from file

            # Save project config
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.model_dump(mode='json'), f, indent=2, default=str)

            # Restore content in memory
            for chapter in self.manuscript.chapters:
                full_path = project_dir / chapter.file_path
                if full_path.exists():
                    chapter.content = full_path.read_text(encoding='utf-8')
        else:
            # Legacy: save everything in one file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.model_dump(mode='json'), f, indent=2, default=str)

        self.project_path = file_path

    @classmethod
    def load_project(cls, file_path: str) -> 'WriterProject':
        """Load project from JSON file with backwards compatibility and repair."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Repair and migrate data before loading
        data = cls._repair_project_data(data, file_path)

        try:
            project = cls(**data)
        except Exception as e:
            # If standard loading fails, try field-by-field recovery
            project = cls._recover_project_fields(data, file_path, e)

        project.project_path = file_path

        # Load chapter content from separate files if they exist
        project_dir = Path(file_path).parent
        for chapter in project.manuscript.chapters:
            if chapter.file_path:
                chapter.load_content_from_file(project_dir)

        return project

    @classmethod
    def _repair_project_data(cls, data: dict, file_path: str) -> dict:
        """Repair and migrate project data for backwards compatibility.

        This handles:
        - Missing required fields
        - Old field formats that need migration
        - Corrupted nested data
        """
        # Ensure required top-level fields exist
        if 'name' not in data or not data['name']:
            # Try to get name from file path
            data['name'] = Path(file_path).stem.replace('.writerproj', '') or 'Recovered Project'

        # Ensure all main sections exist with defaults
        section_defaults = {
            'worldbuilding': {},
            'characters': [],
            'story_planning': {},
            'manuscript': {},
            'generated_images': [],
            'agent_contacts': [],
            'dictionary': {},
        }

        for section, default in section_defaults.items():
            if section not in data:
                data[section] = default

        # Repair worldbuilding section
        data['worldbuilding'] = cls._repair_worldbuilding(data.get('worldbuilding', {}))

        # Repair characters list
        data['characters'] = cls._repair_characters(data.get('characters', []))

        # Repair story planning
        data['story_planning'] = cls._repair_story_planning(data.get('story_planning', {}))

        # Repair manuscript
        data['manuscript'] = cls._repair_manuscript(data.get('manuscript', {}))

        # Repair generated images
        data['generated_images'] = cls._repair_generated_images(data.get('generated_images', []))

        # Repair agent contacts
        data['agent_contacts'] = cls._repair_agent_contacts(data.get('agent_contacts', []))

        return data

    @classmethod
    def _repair_worldbuilding(cls, wb_data: dict) -> dict:
        """Repair worldbuilding data."""
        if not isinstance(wb_data, dict):
            return {}

        # Ensure all text fields are strings
        text_fields = ['mythology', 'planets', 'climate', 'history', 'politics',
                       'military', 'economy', 'power_hierarchy']
        for field in text_fields:
            if field not in wb_data or not isinstance(wb_data.get(field), str):
                wb_data[field] = wb_data.get(field, '') if isinstance(wb_data.get(field), str) else ''

        # Ensure element dicts exist
        element_fields = ['mythology_elements', 'planets_elements', 'climate_elements',
                          'history_elements', 'politics_elements', 'military_elements',
                          'economy_elements', 'power_hierarchy_elements', 'custom_sections']
        for field in element_fields:
            if field not in wb_data or not isinstance(wb_data.get(field), dict):
                wb_data[field] = {}

        # Ensure list fields exist
        list_fields = ['factions', 'myths', 'places', 'climate_presets', 'technologies',
                       'flora', 'fauna', 'stars', 'star_systems', 'cultures']
        for field in list_fields:
            if field not in wb_data or not isinstance(wb_data.get(field), list):
                wb_data[field] = []

        return wb_data

    @classmethod
    def _repair_characters(cls, chars_data: list) -> list:
        """Repair characters list."""
        if not isinstance(chars_data, list):
            return []

        repaired = []
        for i, char in enumerate(chars_data):
            if not isinstance(char, dict):
                continue

            # Ensure required fields
            if 'id' not in char or not char['id']:
                char['id'] = f"char_{i}_{datetime.now().timestamp()}"
            if 'name' not in char or not char['name']:
                char['name'] = f"Unknown Character {i+1}"
            if 'character_type' not in char:
                char['character_type'] = 'minor'

            # Ensure optional fields have correct types
            if not isinstance(char.get('social_network'), dict):
                char['social_network'] = {}

            repaired.append(char)

        return repaired

    @classmethod
    def _repair_story_planning(cls, sp_data: dict) -> dict:
        """Repair story planning data."""
        if not isinstance(sp_data, dict):
            return {}

        # Ensure freytag_pyramid exists
        if 'freytag_pyramid' not in sp_data or not isinstance(sp_data.get('freytag_pyramid'), dict):
            sp_data['freytag_pyramid'] = {}

        # Repair freytag pyramid fields
        fp = sp_data['freytag_pyramid']
        for field in ['exposition', 'rising_action', 'climax', 'falling_action', 'resolution']:
            if not isinstance(fp.get(field), str):
                fp[field] = ''
        if not isinstance(fp.get('events'), list):
            fp['events'] = []

        # Ensure other fields
        if not isinstance(sp_data.get('main_plot'), str):
            sp_data['main_plot'] = ''
        if not isinstance(sp_data.get('subplots'), list):
            sp_data['subplots'] = []
        if not isinstance(sp_data.get('themes'), list):
            sp_data['themes'] = []

        return sp_data

    @classmethod
    def _repair_manuscript(cls, ms_data: dict) -> dict:
        """Repair manuscript data."""
        if not isinstance(ms_data, dict):
            return {}

        # Ensure required fields
        if not isinstance(ms_data.get('title'), str):
            ms_data['title'] = 'Untitled Manuscript'
        if not isinstance(ms_data.get('author'), str):
            ms_data['author'] = ''
        if not isinstance(ms_data.get('chapters'), list):
            ms_data['chapters'] = []

        # Repair each chapter
        repaired_chapters = []
        for i, chapter in enumerate(ms_data.get('chapters', [])):
            if not isinstance(chapter, dict):
                continue

            # Ensure required chapter fields
            if 'id' not in chapter or not chapter['id']:
                chapter['id'] = f"chapter_{i}_{datetime.now().timestamp()}"
            if 'number' not in chapter:
                chapter['number'] = i + 1
            if 'title' not in chapter or not chapter['title']:
                chapter['title'] = f"Chapter {chapter['number']}"
            if not isinstance(chapter.get('content'), str):
                chapter['content'] = ''
            if not isinstance(chapter.get('revisions'), list):
                chapter['revisions'] = []
            if not isinstance(chapter.get('annotations'), list):
                chapter['annotations'] = []

            repaired_chapters.append(chapter)

        ms_data['chapters'] = repaired_chapters
        return ms_data

    @classmethod
    def _repair_generated_images(cls, images_data: list) -> list:
        """Repair generated images list."""
        if not isinstance(images_data, list):
            return []

        repaired = []
        for i, img in enumerate(images_data):
            if not isinstance(img, dict):
                continue

            # Ensure required fields
            if 'id' not in img or not img['id']:
                img['id'] = f"img_{i}_{datetime.now().timestamp()}"
            if 'image_path' not in img:
                continue  # Skip images without paths
            if 'prompt' not in img:
                img['prompt'] = ''
            if 'image_type' not in img:
                img['image_type'] = 'scene'

            repaired.append(img)

        return repaired

    @classmethod
    def _repair_agent_contacts(cls, agents_data: list) -> list:
        """Repair agent contacts list."""
        if not isinstance(agents_data, list):
            return []

        repaired = []
        for i, agent in enumerate(agents_data):
            if not isinstance(agent, dict):
                continue

            # Ensure required fields
            if 'id' not in agent or not agent['id']:
                agent['id'] = f"agent_{i}_{datetime.now().timestamp()}"
            if 'name' not in agent or not agent['name']:
                agent['name'] = f"Unknown Agent {i+1}"

            # Ensure optional fields
            for field in ['agency', 'email', 'phone', 'notes']:
                if not isinstance(agent.get(field), str):
                    agent[field] = ''
            if not isinstance(agent.get('submissions'), list):
                agent['submissions'] = []

            repaired.append(agent)

        return repaired

    @classmethod
    def _recover_project_fields(cls, data: dict, file_path: str, original_error: Exception) -> 'WriterProject':
        """Last-resort recovery: create project with whatever data we can salvage."""
        print(f"Warning: Project file had errors, attempting recovery. Original error: {original_error}")

        # Create minimal project
        project = cls(
            name=data.get('name', Path(file_path).stem or 'Recovered Project'),
            description=data.get('description', f'Recovered from corrupted file. Original error: {original_error}')
        )

        # Try to recover each section independently
        try:
            project.worldbuilding = WorldBuilding(**cls._repair_worldbuilding(data.get('worldbuilding', {})))
        except Exception as e:
            print(f"Could not recover worldbuilding: {e}")

        try:
            chars = cls._repair_characters(data.get('characters', []))
            project.characters = [Character(**c) for c in chars]
        except Exception as e:
            print(f"Could not recover characters: {e}")

        try:
            project.story_planning = StoryPlanning(**cls._repair_story_planning(data.get('story_planning', {})))
        except Exception as e:
            print(f"Could not recover story planning: {e}")

        try:
            project.manuscript = Manuscript(**cls._repair_manuscript(data.get('manuscript', {})))
        except Exception as e:
            print(f"Could not recover manuscript: {e}")

        try:
            imgs = cls._repair_generated_images(data.get('generated_images', []))
            project.generated_images = [GeneratedImage(**img) for img in imgs]
        except Exception as e:
            print(f"Could not recover generated images: {e}")

        try:
            agents = cls._repair_agent_contacts(data.get('agent_contacts', []))
            project.agent_contacts = [AgentContact(**a) for a in agents]
        except Exception as e:
            print(f"Could not recover agent contacts: {e}")

        return project
