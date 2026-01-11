"""Project model - Root level encapsulating all writer work."""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from pathlib import Path
import json

from src.models.worldbuilding_objects import Faction, Myth, ClimatePreset, Flora, Fauna, Technology, Star, StarSystem


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
    climate_presets: List[ClimatePreset] = Field(default_factory=list)
    technologies: List[Technology] = Field(default_factory=list)
    flora: List[Flora] = Field(default_factory=list)
    fauna: List[Fauna] = Field(default_factory=list)
    stars: List[Star] = Field(default_factory=list)
    star_systems: List[StarSystem] = Field(default_factory=list)


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


class PlotEvent(BaseModel):
    """Individual event in the plot structure."""
    id: str
    title: str
    description: str = ""
    outcome: str = ""  # What happens as a result
    stage: str = "rising_action"  # exposition, rising_action, climax, falling_action, resolution
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

    # New: Detailed events with intensity tracking
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


class ChapterRevision(BaseModel):
    """Revision history for a chapter."""
    revision_number: int
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: str = ""


class Chapter(BaseModel):
    """Chapter unit for manuscript."""
    id: str
    number: int
    title: str
    content: str = ""  # Content stored inline (legacy) or loaded from file_path
    file_path: Optional[str] = None  # Relative path to chapter file within project
    revisions: List[ChapterRevision] = Field(default_factory=list)
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
        if not self.file_path:
            # Auto-generate file path
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
        """Load project from JSON file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        project = cls(**data)
        project.project_path = file_path

        # Load chapter content from separate files if they exist
        project_dir = Path(file_path).parent
        for chapter in project.manuscript.chapters:
            if chapter.file_path:
                chapter.load_content_from_file(project_dir)

        return project
