"""Project model - Root level encapsulating all writer work."""

from typing import List, Dict, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from pathlib import Path
import json
import os

from src.models.worldbuilding_objects import Faction, Myth, ClimatePreset, Flora, Fauna, Technology, Star, StarSystem, Place, Culture, Army, Economy, HistoricalEvent, PowerHierarchy, PoliticalSystem, WorldMap, MagicSystem


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
    magic_systems: List['MagicSystem'] = Field(default_factory=list)  # Magic systems

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
    physical_description: str = ""  # Physical appearance for AI image generation
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
    content: str = ""  # Plain text (loaded on demand from file when folder-based)
    html_content: str = ""  # Rich text HTML snapshot for formatting preservation
    file_path: str = ""  # Relative path to revision file (e.g. "chapters/chapter_001/revision_001.md")
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: str = ""
    word_count: int = 0  # Cached word count for this revision


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


class ChapterTodo(BaseModel):
    """Todo item for chapter planning."""
    id: str
    text: str
    completed: bool = False
    priority: str = "normal"  # low, normal, high
    created_at: datetime = Field(default_factory=datetime.now)


class StoryEvent(BaseModel):
    """A story event/beat for chapter planning with arc positioning."""
    id: str
    text: str  # Brief title/name of what happens
    description: str = ""  # Detailed description of the event
    completed: bool = False  # Has this event been written?
    stage: str = "rising"  # exposition, rising, climax, falling, resolution
    arc_position: int = 50  # 0-100, position on the chapter's narrative arc
    order: int = 0  # Order in the event list


class NoteEntry(BaseModel):
    """A single note within a subject."""
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])
    title: str = ""
    content: str = ""
    collapsed: bool = False

class NoteSubject(BaseModel):
    """A subject/category grouping notes together."""
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])
    name: str = "General"
    entries: List[NoteEntry] = Field(default_factory=list)


class SubplotNote(BaseModel):
    """A subplot note tracking how a subplot manifests in a specific chapter."""
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])
    title: str = ""
    content: str = ""  # How this subplot progresses in this chapter
    subplot_id: str = ""  # Optional reference to story-level Subplot ID
    status: str = "active"  # active, resolved, dormant
    collapsed: bool = False


class FeedbackEntry(BaseModel):
    """A single piece of feedback from a source."""
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])
    title: str = ""
    content: str = ""
    source: str = ""  # e.g. "Beta reader", "Editor", "Workshop", "Self"
    collapsed: bool = False

class ChapterFeedback(BaseModel):
    """All feedback for a chapter."""
    entries: List[FeedbackEntry] = Field(default_factory=list)


class ChapterPlanning(BaseModel):
    """Planning data for a chapter - separate from content."""
    outline: str = ""  # Legacy: text-based outline (auto-generated from events)
    events: List[StoryEvent] = Field(default_factory=list)  # Story events on the arc
    description: str = ""  # Brief description/summary of what happens
    todos: List[ChapterTodo] = Field(default_factory=list)  # Writing tasks for this chapter
    notes: Union[List[NoteSubject], str] = Field(default_factory=list)  # Organized notes by subject
    subplot_notes: List[SubplotNote] = Field(default_factory=list)  # Subplot tracking for this chapter
    feedback: ChapterFeedback = Field(default_factory=ChapterFeedback)  # Reader/editor feedback

    @model_validator(mode='before')
    @classmethod
    def migrate_notes(cls, data):
        """Migrate legacy string notes to the new subject-based format."""
        if isinstance(data, dict):
            notes = data.get('notes')
            if isinstance(notes, str) and notes.strip():
                # Migrate old plain-text notes into a "General" subject
                data['notes'] = [{
                    'id': __import__('uuid').uuid4().hex[:8],
                    'name': 'General',
                    'entries': [{
                        'id': __import__('uuid').uuid4().hex[:8],
                        'title': 'Note',
                        'content': notes
                    }]
                }]
            elif isinstance(notes, str):
                data['notes'] = []
        return data
    scene_list: List[str] = Field(default_factory=list)  # List of scenes in order
    characters_featured: List[str] = Field(default_factory=list)  # Character names/IDs
    locations: List[str] = Field(default_factory=list)  # Locations used
    themes: List[str] = Field(default_factory=list)  # Themes explored
    pov_character: str = ""  # Point of view character
    timeline_position: str = ""  # When this chapter occurs in story timeline
    # Writing style metadata for AI-assisted writing
    tone: str = ""  # Emotional quality/mood (e.g., "dark and brooding", "lighthearted", "tense")
    voice: str = ""  # Narrative voice style (e.g., "sardonic", "lyrical", "matter-of-fact")
    style: str = ""  # Prose style notes (e.g., "short punchy sentences", "flowery descriptions")
    pacing: str = ""  # Pacing notes (e.g., "slow build", "rapid-fire action", "contemplative")

    @property
    def notes_as_text(self) -> str:
        """Flatten organized notes into a readable string for export/AI context."""
        if isinstance(self.notes, str):
            return self.notes
        parts = []
        for subject in self.notes:
            entry_parts = []
            for entry in subject.entries:
                if entry.content.strip():
                    if entry.title.strip():
                        entry_parts.append(f"- {entry.title}: {entry.content.strip()}")
                    else:
                        entry_parts.append(entry.content.strip())
            if entry_parts:
                if len(self.notes) > 1:
                    parts.append(f"[{subject.name}]\n" + "\n".join(entry_parts))
                else:
                    parts.append("\n".join(entry_parts))
        return "\n\n".join(parts)

    @property
    def subplots_as_text(self) -> str:
        """Flatten subplot notes into a readable string for AI context."""
        parts = []
        for sn in self.subplot_notes:
            if sn.content.strip():
                status = f" [{sn.status}]" if sn.status != "active" else ""
                title = sn.title or "Untitled subplot"
                parts.append(f"- {title}{status}: {sn.content.strip()}")
        return "\n".join(parts)


class Chapter(BaseModel):
    """Chapter unit for manuscript."""
    id: str
    number: int
    title: str
    content: str = ""  # Plain text content of active revision
    html_content: str = ""  # Rich text HTML content of active revision
    file_path: Optional[str] = None  # Legacy: flat file path (pre-folder migration)
    folder_path: Optional[str] = None  # Folder path e.g. "chapters/chapter_001"
    active_revision_number: int = 1  # Which revision is currently active
    plan: str = ""  # Legacy: Chapter plan/outline (kept for backward compatibility)
    plan_file_path: Optional[str] = None  # Legacy: path to plan file
    planning: ChapterPlanning = Field(default_factory=ChapterPlanning)
    revisions: List[ChapterRevision] = Field(default_factory=list)
    annotations: List[Annotation] = Field(default_factory=list)
    notes: str = ""  # Legacy notes field
    word_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # --- Folder management ---

    def _folder_name(self) -> str:
        """Get folder name based on chapter number."""
        return f"chapters/chapter_{self.number:03d}"

    def ensure_folder(self, project_dir: Path):
        """Create the chapter folder if it doesn't exist.

        Uses the existing folder_path if set (preserving relocations),
        falling back to generating from the current chapter number.
        """
        if not self.folder_path:
            self.folder_path = self._folder_name()
        folder = project_dir / self.folder_path
        folder.mkdir(parents=True, exist_ok=True)

    def relocate_to_number(self, new_number: int, project_dir: Path) -> bool:
        """Relocate chapter folder on disk when chapter number changes.

        Moves the physical folder and updates all internal path references
        (folder_path, revision file_paths, legacy file_path) so that the
        chapter content is not lost after reordering.

        Args:
            new_number: The new chapter number (1-based)
            project_dir: Root project directory
        Returns:
            True if relocation succeeded or was unnecessary
        """
        import shutil

        old_folder = self.folder_path
        self.number = new_number
        new_folder = self._folder_name()

        if old_folder == new_folder:
            # Number didn't change enough to affect folder name
            return True

        if not old_folder:
            # No folder to move (new chapter or legacy flat-file)
            self.folder_path = new_folder
            return True

        old_path = project_dir / old_folder
        new_path = project_dir / new_folder

        # Move the physical folder if it exists on disk
        if old_path.exists():
            # If the target already exists (e.g. two chapters swapping),
            # move to a temporary name first to avoid collisions.
            if new_path.exists():
                tmp_path = project_dir / f"chapters/_tmp_relocate_{self.id[:8]}"
                try:
                    shutil.move(str(old_path), str(tmp_path))
                except Exception:
                    return False
                # Store the temp path; the caller must finalize after all
                # chapters have been relocated (see _finalize_relocations)
                self._pending_relocate_tmp = str(tmp_path)
            else:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(old_path), str(new_path))
                except Exception:
                    return False

        # Update all path references
        self.folder_path = new_folder
        for rev in self.revisions:
            if rev.file_path and old_folder in rev.file_path:
                rev.file_path = rev.file_path.replace(old_folder, new_folder)
        if self.file_path and old_folder in self.file_path:
            self.file_path = self.file_path.replace(old_folder, new_folder)

        return True

    def finalize_relocation(self, project_dir: Path):
        """Complete a pending folder relocation (used after swap operations).

        When two chapters swap positions, both folders need to move through a
        temp directory to avoid overwriting each other. Call this after all
        chapters have been relocated to move temp folders to their final names.
        """
        import shutil
        tmp_path = getattr(self, '_pending_relocate_tmp', None)
        if tmp_path and Path(tmp_path).exists():
            final_path = project_dir / self.folder_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if final_path.exists():
                # Safety: don't overwrite — this shouldn't happen
                shutil.rmtree(str(final_path), ignore_errors=True)
            shutil.move(tmp_path, str(final_path))
            del self._pending_relocate_tmp

    def delete_folder(self, project_dir: Path) -> bool:
        """Delete the entire chapter folder from disk."""
        if not self.folder_path:
            return False
        import shutil
        folder = project_dir / self.folder_path
        try:
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
                return True
        except (FileNotFoundError, OSError):
            # Folder may not exist yet (unsaved chapter) or be on
            # an external drive with filesystem timing issues
            pass
        return False

    # --- Revision management ---

    def add_revision(self, notes: str = "", html_content: str = "",
                     content: str = "", project_dir: Path = None):
        """Create a new revision from current content (or provided content).

        Args:
            notes: Optional revision notes
            html_content: Optional HTML content
            content: Content for the revision (defaults to self.content)
            project_dir: If provided, saves revision file to disk
        """
        rev_content = content or self.content
        rev_html = html_content or self.html_content
        rev_num = len(self.revisions) + 1
        rev_file = f"{self.folder_path}/revision_{rev_num:03d}.md" if self.folder_path else ""

        revision = ChapterRevision(
            revision_number=rev_num,
            content=rev_content,
            html_content=rev_html,
            file_path=rev_file,
            notes=notes,
            word_count=len(rev_content.split()) if rev_content else 0
        )
        self.revisions.append(revision)
        self.active_revision_number = rev_num

        # Save revision file to disk
        if project_dir and rev_file:
            self.ensure_folder(project_dir)
            full_path = project_dir / rev_file
            full_path.write_text(rev_content, encoding='utf-8')

        return revision

    def create_blank_revision(self, project_dir: Path = None, notes: str = "Blank revision"):
        """Create an empty revision for starting a fresh rewrite."""
        return self.add_revision(notes=notes, content="", html_content="",
                                 project_dir=project_dir)

    def set_active_revision(self, revision_number: int, project_dir: Path = None):
        """Switch the active revision. Loads content from that revision."""
        for rev in self.revisions:
            if rev.revision_number == revision_number:
                self.active_revision_number = revision_number
                # Load content from file if available, else from in-memory
                if project_dir and rev.file_path:
                    loaded = self.load_revision_content(project_dir, revision_number)
                    if loaded is not None:
                        self.content = loaded
                        rev.content = loaded
                else:
                    self.content = rev.content
                self.html_content = rev.html_content
                self.word_count = len(self.content.split()) if self.content else 0
                return True
        return False

    def load_revision_content(self, project_dir: Path, revision_number: int) -> Optional[str]:
        """Read a specific revision file from disk."""
        for rev in self.revisions:
            if rev.revision_number == revision_number:
                if rev.file_path:
                    full_path = project_dir / rev.file_path
                    if full_path.exists():
                        return full_path.read_text(encoding='utf-8')
                return rev.content
        return None

    def save_active_revision_to_file(self, project_dir: Path) -> bool:
        """Save the active revision's content to its file."""
        # SAFETY: Never overwrite an existing revision file with empty content.
        # This guards against accidental data loss from save-during-load or
        # serialization-clearing race conditions.
        if not self.content or not self.content.strip():
            return False

        self.ensure_folder(project_dir)

        # Sync ALL revision file_paths to current folder_path.
        # After chapter reordering, the folder may have changed but only
        # the active revision's path was being updated — leaving non-active
        # revisions pointing to stale/old folders.
        for rev in self.revisions:
            rev.file_path = f"{self.folder_path}/revision_{rev.revision_number:03d}.md"

        for rev in self.revisions:
            if rev.revision_number == self.active_revision_number:
                rev.content = self.content
                rev.html_content = self.html_content
                rev.word_count = len(self.content.split()) if self.content else 0
                full_path = project_dir / rev.file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(self.content, encoding='utf-8')
                return True
        return False

    # --- File I/O (folder-based, with legacy fallback) ---

    def save_content_to_file(self, project_dir: Path) -> bool:
        """Save chapter content to folder-based revision files."""
        # Use existing folder_path if already set (preserves relocations),
        # otherwise generate from current chapter number.
        if not self.folder_path:
            self.folder_path = self._folder_name()
        self.ensure_folder(project_dir)

        # Sync all revision file_paths to current folder_path
        for rev in self.revisions:
            rev.file_path = f"{self.folder_path}/revision_{rev.revision_number:03d}.md"

        # If no revisions exist yet, create the first one from current content
        if not self.revisions:
            self.add_revision(notes="Initial", project_dir=project_dir)
        else:
            # Save active revision content to file
            self.save_active_revision_to_file(project_dir)

        # Save plan inside chapter folder
        if self.plan:
            plan_path = project_dir / self.folder_path / "plan.md"
            plan_path.write_text(self.plan, encoding='utf-8')

        # Update legacy file_path to point to active revision for compat
        active_rev = self._get_active_revision()
        if active_rev:
            self.file_path = active_rev.file_path

        return True

    def load_content_from_file(self, project_dir: Path) -> bool:
        """Load chapter content from folder-based revision files."""
        # Try folder-based loading first
        if self.folder_path:
            active_rev = self._get_active_revision()
            if active_rev and active_rev.file_path:
                full_path = project_dir / active_rev.file_path
                if full_path.exists():
                    self.content = full_path.read_text(encoding='utf-8')
                    self.word_count = len(self.content.split()) if self.content else 0
                    return True

                # Revision path may be stale after a crash during chapter move.
                # Try deriving the expected path from current folder_path.
                expected_path = project_dir / self.folder_path / f"revision_{active_rev.revision_number:03d}.md"
                if expected_path.exists():
                    self.content = expected_path.read_text(encoding='utf-8')
                    self.word_count = len(self.content.split()) if self.content else 0
                    # Fix the stale path
                    active_rev.file_path = f"{self.folder_path}/revision_{active_rev.revision_number:03d}.md"
                    return True

            # Last resort: scan the folder for any revision file
            folder = project_dir / self.folder_path
            if folder.exists():
                for rev_file in sorted(folder.glob("revision_*.md"), reverse=True):
                    content = rev_file.read_text(encoding='utf-8')
                    if content and content.strip():
                        self.content = content
                        self.word_count = len(self.content.split())
                        return True

        # Legacy fallback: flat file
        if self.file_path:
            full_path = project_dir / self.file_path
            if full_path.exists():
                self.content = full_path.read_text(encoding='utf-8')
                self.word_count = len(self.content.split()) if self.content else 0
                return True

        return False

    def load_plan_from_file(self, project_dir: Path) -> bool:
        """Load chapter plan from file."""
        # Try folder-based first
        if self.folder_path:
            plan_path = project_dir / self.folder_path / "plan.md"
            if plan_path.exists():
                self.plan = plan_path.read_text(encoding='utf-8')
                return True

        # Legacy fallback
        if self.plan_file_path:
            full_path = project_dir / self.plan_file_path
            if full_path.exists():
                self.plan = full_path.read_text(encoding='utf-8')
                return True

        return False

    def save_plan_to_file(self, project_dir: Path) -> bool:
        """Save chapter plan to file inside chapter folder."""
        if self.folder_path:
            self.ensure_folder(project_dir)
            plan_path = project_dir / self.folder_path / "plan.md"
            plan_path.write_text(self.plan, encoding='utf-8')
            return True

        # Legacy fallback
        self.plan_file_path = f"chapters/plans/chapter_{self.number:03d}_plan.md"
        full_path = project_dir / self.plan_file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(self.plan, encoding='utf-8')
        return True

    def _get_active_revision(self) -> Optional[ChapterRevision]:
        """Get the active revision object."""
        for rev in self.revisions:
            if rev.revision_number == self.active_revision_number:
                return rev
        # Fallback: return last revision
        if self.revisions:
            return self.revisions[-1]
        return None

    # --- Migration ---

    def migrate_to_folder(self, project_dir: Path):
        """Migrate from old flat-file format to folder-based format.

        Moves chapter_NNN.md → chapter_NNN/revision_001.md
        Moves plans/chapter_NNN_plan.md → chapter_NNN/plan.md
        Migrates any in-memory revisions to files.
        """
        import shutil

        self.folder_path = self._folder_name()
        self.ensure_folder(project_dir)
        folder = project_dir / self.folder_path

        # Move main content file into folder as revision_001
        if self.file_path:
            old_content_path = project_dir / self.file_path
            if old_content_path.exists():
                new_path = folder / "revision_001.md"
                if not new_path.exists():
                    shutil.move(str(old_content_path), str(new_path))
                    print(f"  Migrated {self.file_path} -> {self.folder_path}/revision_001.md")

        # Move plan file into folder
        if self.plan_file_path:
            old_plan_path = project_dir / self.plan_file_path
            if old_plan_path.exists():
                new_plan = folder / "plan.md"
                if not new_plan.exists():
                    shutil.move(str(old_plan_path), str(new_plan))
                    print(f"  Migrated {self.plan_file_path} -> {self.folder_path}/plan.md")

        # Create revision entry if none exist
        if not self.revisions:
            rev_file = f"{self.folder_path}/revision_001.md"
            wc = len(self.content.split()) if self.content else 0
            self.revisions.append(ChapterRevision(
                revision_number=1,
                content=self.content,
                html_content=self.html_content,
                file_path=rev_file,
                notes="Migrated from legacy format",
                word_count=wc
            ))
        else:
            # Migrate in-memory revisions to files
            for rev in self.revisions:
                rev_file = f"{self.folder_path}/revision_{rev.revision_number:03d}.md"
                rev.file_path = rev_file
                full_path = project_dir / rev_file
                if not full_path.exists() and rev.content:
                    full_path.write_text(rev.content, encoding='utf-8')
                rev.word_count = len(rev.content.split()) if rev.content else 0

        self.active_revision_number = max(r.revision_number for r in self.revisions)
        self.file_path = f"{self.folder_path}/revision_{self.active_revision_number:03d}.md"
        self.word_count = len(self.content.split()) if self.content else 0


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
    display_name: Optional[str] = None  # User-assigned name (overrides default display)
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


class ProjectSummary(BaseModel):
    """AI-generated condensed summaries of project data for context.

    These summaries are automatically generated and updated when project data changes.
    They provide concise context for AI assistants without overwhelming token limits.
    """
    plot_summary: str = ""  # Condensed plot outline (max ~500 words)
    character_summary: str = ""  # Key character descriptions (max ~500 words)
    worldbuilding_summary: str = ""  # Essential worldbuilding details (max ~500 words)
    themes_summary: str = ""  # Core themes and motifs (max ~200 words)

    # Metadata for tracking freshness
    last_updated: datetime = Field(default_factory=datetime.now)
    source_hash: str = ""  # Hash of source data to detect changes

    def needs_update(self, current_hash: str) -> bool:
        """Check if summary needs regeneration based on source data hash."""
        return self.source_hash != current_hash

    def is_empty(self) -> bool:
        """Check if summary has been generated."""
        return not (self.plot_summary or self.character_summary or self.worldbuilding_summary)


class ProseProfile(BaseModel):
    """Target prose profile for the project — tone, style, voice, genre."""
    tone: str = ""  # e.g. "dark, tense, foreboding"
    style: str = ""  # e.g. "minimalist, cinematic, short punchy sentences"
    voice: str = ""  # e.g. "sardonic first-person, unreliable narrator"
    genre: str = ""  # e.g. "noir thriller, southern gothic"
    notes: str = ""  # freeform additional guidance


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

    # Prose profile — target tone, style, voice, genre
    prose_profile: ProseProfile = Field(default_factory=ProseProfile)

    # AI-generated summaries for efficient context
    ai_summary: ProjectSummary = Field(default_factory=ProjectSummary)

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
            # Save all chapter content/revisions to disk
            # SAFETY: Only write chapters that actually have content to avoid
            # overwriting good files with empty content
            for chapter in self.manuscript.chapters:
                if chapter.content and chapter.content.strip():
                    chapter.save_content_to_file(project_dir)

            # Build JSON without content fields to save space.
            # Instead of mutating in-memory state (dangerous if interrupted),
            # serialize to dict first, then strip content from the dict.
            project_dict = self.model_dump(mode='json')
            for ch_dict in project_dict.get('manuscript', {}).get('chapters', []):
                ch_dict['content'] = ""
                ch_dict['html_content'] = ""
                for rev_dict in ch_dict.get('revisions', []):
                    rev_dict['content'] = ""
                    rev_dict['html_content'] = ""

            # Write to temp file first, then atomically replace
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(project_dir), suffix='.json.tmp'
            )
            try:
                with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                    json.dump(project_dict, f, indent=2, default=str)
                # Atomic rename (same filesystem)
                os.replace(tmp_path, file_path)
            except Exception:
                # Clean up temp file on failure; in-memory state is untouched
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
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

        # Load chapter content and migrate to folder-based format if needed
        project_dir = Path(file_path).parent
        needs_save = False

        for chapter in project.manuscript.chapters:
            # Check if migration to folder-based format is needed
            if not chapter.folder_path and chapter.file_path:
                print(f"  Migrating chapter {chapter.number} '{chapter.title}' to folder format...")
                # Load content first from legacy flat file
                chapter.load_content_from_file(project_dir)
                # Then migrate to folder structure
                chapter.migrate_to_folder(project_dir)
                needs_save = True
            elif chapter.folder_path:
                # Already folder-based, just load content
                chapter.load_content_from_file(project_dir)
                chapter.load_plan_from_file(project_dir)
            elif chapter.file_path:
                # Fallback: legacy flat file
                chapter.load_content_from_file(project_dir)

        # Verify chapter numbering and folder_path consistency.
        # After a crash during a move operation, chapter.number or folder_path
        # in the JSON may not match the actual folder layout on disk.
        for i, chapter in enumerate(project.manuscript.chapters, 1):
            if chapter.number != i:
                print(f"  Fixing chapter numbering: '{chapter.title}' was {chapter.number}, now {i}")
                chapter.number = i
                needs_save = True

            expected_folder = chapter._folder_name()
            if chapter.folder_path and chapter.folder_path != expected_folder:
                # folder_path doesn't match number — check which folder actually
                # exists on disk and reconcile
                old_dir = project_dir / chapter.folder_path
                new_dir = project_dir / expected_folder
                if old_dir.exists() and not new_dir.exists():
                    # The folder is at the old path; move it
                    import shutil
                    print(f"  Reconciling chapter folder: {chapter.folder_path} → {expected_folder}")
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_dir), str(new_dir))
                # Update path references
                old_folder = chapter.folder_path
                chapter.folder_path = expected_folder
                for rev in chapter.revisions:
                    if rev.file_path and old_folder in rev.file_path:
                        rev.file_path = rev.file_path.replace(old_folder, expected_folder)
                if chapter.file_path and old_folder in chapter.file_path:
                    chapter.file_path = chapter.file_path.replace(old_folder, expected_folder)
                needs_save = True

        # If we migrated or repaired, save the updated project metadata
        if needs_save:
            try:
                print("  Saving repaired project metadata...")
                project.save_project(file_path)
                print("  Repair complete.")
            except Exception as e:
                print(f"  Warning: Could not save repair: {e}")

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
            'prose_profile': {},
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
