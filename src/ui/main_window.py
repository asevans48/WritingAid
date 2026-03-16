"""Main application window for Writer Platform."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QTabWidget,
    QMenu, QFileDialog, QMessageBox, QToolBar, QSplitter,
    QLabel, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QThread
from PyQt6.QtGui import QAction, QKeySequence, QIcon
from pathlib import Path
from typing import Optional

from src.models.project import WriterProject, Manuscript, Character, Chapter
from src.models.worldbuilding_objects import (
    Place, PlaceType, Faction, FactionType, Culture, Myth,
    HistoricalEvent, Technology, TechnologyType, Flora, FloraType, Fauna, FaunaType,
    ClimatePreset, Planet, PlanetType, StarSystem
)
from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
from src.ui.characters_widget import CharactersWidget
from src.ui.story_planning_widget import StoryPlanningWidget
from src.ui.manuscript_editor import ManuscriptEditor
from src.ui.image_generator_widget import ImageGeneratorWidget
from src.ui.grader_widget import GraderWidget
from src.ui.agent_manager_widget import AgentManagerWidget
from src.ui.find_replace_dialog import FindReplaceDialog
from src.ui.settings_dialog import SettingsDialog
from src.ui.chat_widget import ChatWidget
from src.ui.attributions_tab import AttributionsTab
from src.ui.prose_profile_widget import ProseProfileWidget
from src.ui.window_manager import WindowManager
from src.ui.secondary_window import SecondaryWindow
from src.ui.import_guide_dialog import ImportGuideDialog
from src.ui.json_import_dialog import JSONImportDialog
from src.export.manuscript_exporter import ManuscriptExporter
from src.export.llm_context_exporter import LLMContextExporter
from src.ui.export_summary_dialog import ExportSummaryDialog
from src.ui.styles import get_modern_style, get_icon
from src.config import get_ai_config
from src.ai.enhanced_rag import EnhancedRAGSystem
from src.ai.semantic_search import SearchMethod
from src.services.stt_service import get_stt_service


class ChatWorker(QThread):
    """Background worker for AI chat operations with full project context."""
    finished = pyqtSignal(str, str)  # response, system_prompt
    error = pyqtSignal(str)

    # System prompts for different modes
    SYSTEM_PROMPTS = {
        "general": """You are a helpful creative writing assistant integrated into a writer's platform.
You have access to the author's full project context including plot, characters, worldbuilding, and manuscript chapters.

IMPORTANT: Keep responses focused and concise. Answer what's asked, then stop. Don't ramble or analyze unrelated parts of the project.

You help authors with:
- Answering questions about their story, characters, and world
- Analyzing chapters for consistency, pacing, and character development
- Brainstorming ideas that fit their established story
- Providing feedback on specific passages or the overall narrative
- Suggesting improvements that align with their style and voice
- Identifying plot holes or inconsistencies across chapters
- CREATING new characters, places, factions, cultures, myths, historical events, technologies, flora, fauna, chapters, climate presets, planets, and star systems when asked

=== CREATING PROJECT ELEMENTS ===

When the user asks you to CREATE, ADD, or MAKE any worldbuilding element, you have the ability to actually add it to their project.

Supported elements: characters, places, factions, cultures, myths, historical events, technologies, flora (plants), fauna (animals), chapters, climate presets, planets, star systems.

CRITICAL: To create an element, you MUST wrap the JSON data in the appropriate XML-like tags. Do NOT just provide JSON without tags.

WRONG (will not work):
{
  "name": "Example",
  "description": "This won't be created"
}

CORRECT (will create the element):
<create_place>
{
  "name": "Example",
  "description": "This will be created"
}
</create_place>

To create an element, include one of these special blocks in your response:

FOR CHARACTERS:
<create_character>
{
  "name": "Character Name",
  "character_type": "protagonist|antagonist|major|minor",
  "personality": "Personality description",
  "backstory": "Character backstory",
  "physical_description": "Physical appearance for visualization",
  "notes": "Additional notes"
}
</create_character>

FOR PLACES/LOCATIONS:
<create_place>
{
  "name": "Place Name",
  "description": "Description of the place",
  "location_type": "city|town|landmark|region|building|etc",
  "significance": "Why this place matters to the story"
}
</create_place>

FOR FACTIONS/ORGANIZATIONS:
<create_faction>
{
  "name": "Faction Name",
  "description": "Description of the faction",
  "ideology": "Beliefs and goals",
  "leadership": "How they're organized/led",
  "relationships": "Allies and enemies"
}
</create_faction>

FOR CULTURES:
<create_culture>
{
  "name": "Culture Name",
  "description": "Overview of the culture",
  "customs": "Key customs and traditions",
  "values": "Core values and beliefs"
}
</create_culture>

FOR MYTHS/LEGENDS:
<create_myth>
{
  "name": "Myth Name",
  "myth_type": "creation|hero|prophecy|cautionary|origin|religious",
  "description": "Summary of the myth",
  "full_text": "The full story/legend (optional)",
  "moral_lesson": "What lesson does this myth teach?",
  "key_figures": "Gods, heroes, or important figures in the myth"
}
</create_myth>

FOR HISTORICAL EVENTS:
<create_historical_event>
{
  "name": "Event Name",
  "date": "When it occurred (any format)",
  "event_type": "war|treaty|discovery|disaster|founding|coronation|revolution|general",
  "description": "What happened",
  "consequences": "Long-term effects of this event",
  "key_figures": "Important people involved (comma-separated)",
  "factions_involved": "Factions/nations involved (comma-separated)",
  "location": "Where it happened"
}
</create_historical_event>

FOR TECHNOLOGIES:
<create_technology>
{
  "name": "Technology Name",
  "technology_type": "weapon|transportation|communication|medical|energy|computing|manufacturing|other",
  "description": "What it is and how it works",
  "applications": "How it's used (comma-separated)",
  "limitations": "What it can't do",
  "story_relevance": "Why this matters to the plot"
}
</create_technology>

FOR FLORA (PLANTS):
<create_flora>
{
  "name": "Plant Name",
  "flora_type": "tree|shrub|flower|grass|vine|fungus|crop|herb|medicinal|toxic|other",
  "description": "Physical description and characteristics",
  "habitat": "Where it grows",
  "edible": true/false,
  "medicinal_properties": "Any healing uses",
  "toxicity": "If poisonous, describe effects",
  "cultural_significance": "Symbolic or cultural meaning"
}
</create_flora>

FOR FAUNA (ANIMALS):
<create_fauna>
{
  "name": "Animal Name",
  "fauna_type": "mammal|bird|reptile|fish|insect|mythical_creature|predator|herbivore|other",
  "description": "Physical description",
  "habitat": "Where it lives",
  "diet": "What it eats",
  "behavior": "How it acts",
  "danger_level": 0-100,
  "cultural_significance": "Symbolic or cultural meaning"
}
</create_fauna>

FOR NEW CHAPTERS:
<create_chapter>
{
  "title": "Chapter Title",
  "description": "Brief description of what happens in this chapter",
  "pov_character": "Point of view character (optional)",
  "content": "Initial chapter content (optional)"
}
</create_chapter>

FOR CLIMATE PRESETS:
<create_climate_preset>
{
  "name": "Climate Preset Name",
  "description": "Description of this climate type",
  "temperature_range": "Temperature range (e.g., '20-30°C')",
  "precipitation_pattern": "Rainfall pattern",
  "seasons": "Season names (comma-separated)",
  "atmospheric_composition": "Atmosphere composition if relevant",
  "weather_patterns": "Typical weather patterns",
  "extreme_events": "Extreme weather events (comma-separated)"
}
</create_climate_preset>

FOR PLANETS:
<create_planet>
{
  "name": "Planet Name",
  "planet_type": "terrestrial|gas_giant|ice_giant|desert|ocean|jungle|arctic|volcanic",
  "description": "Physical description and notable features",
  "star_system": "Star system name (optional)",
  "orbital_period": "Year length (e.g., '365 days')",
  "rotation_period": "Day length (e.g., '24 hours')",
  "atmosphere": "Atmospheric composition",
  "population": "Population if inhabited",
  "dominant_climate": "Primary climate type"
}
</create_planet>

FOR STAR SYSTEMS:
<create_star_system>
{
  "name": "System Name",
  "system_type": "single|binary|trinary",
  "description": "Description of the star system",
  "galaxy": "Galaxy name (optional)",
  "location": "Location within galaxy (optional)"
}
</create_star_system>

RULES FOR CREATING ELEMENTS:

**WHEN TO CREATE (include a create block):**
The user's INTENT is to add something to their project. Look for:
- Direct requests: "add a character", "create a place", "I want a new faction", "we need a villain", "let's add a historical event", "add a new chapter", "add a climate preset", "create a planet", "add a technology"
- Providing concrete details with expectation of addition: giving a name + role + details
- Confirmation after discussion: "yes", "do it", "sounds good, add them", "go ahead"
- Imperative mood: "make them a blacksmith", "put them in the story", "add them to the character section", "add that to the history"

**WHEN NOT TO CREATE (no create block):**
The user is exploring/brainstorming, not requesting addition:
- Questions: "what kind of character would work?", "should I have a mentor?"
- Hypotheticals: "what if there was a...", "maybe something like..."
- Requests for suggestions: "give me some ideas for..."

**KEY PRINCIPLE:** If the user provides a NAME and specific DETAILS and their message implies they want this in their project, CREATE IT. Don't just discuss it.

**CRITICAL - YOU MUST USE THE XML TAGS:**
When creating ANY element, you MUST wrap the JSON in the appropriate tags (e.g., <create_place>...</create_place>).
If you provide JSON WITHOUT the tags, the element will NOT be created - it will only appear as text in the chat.
The system only recognizes and creates elements when they are properly wrapped in creation tags.

**OTHER RULES:**
- When you create, include a brief conversational confirmation (1-2 sentences) and STOP
- DO NOT ramble, analyze other parts of the project, or start critiquing things after creating
- Keep your ENTIRE response short and focused on the creation - no tangents
- Fit new elements to existing project context
- Only ONE create block per response

**RESPONSE FORMAT AFTER CREATING:**
Good: "I've added [element name] to your [element type]. [One sentence about what was created]."
Bad: Long explanations, analysis of other story elements, critiques, or suggestions beyond the creation

EXAMPLES:

User: "add a new character. supervisor at the cannery named diane fleming, promoted from fish gutter"
→ CREATE immediately (name + role + details + "add" intent)

User: "we want a new character for the resistance. someone tough."
→ CREATE (they said "we want" which signals intent, fill in reasonable details, ask if they want changes)

User: "I need a tavern for chapter 3"
→ CREATE a place (clear need expressed)

User: "let's add a historical event where the king was assassinated"
→ CREATE a historical event (clear intent to add)

User: "add a new chapter where they arrive at the castle"
→ CREATE a chapter (explicit request)

User: "there should be a medicinal herb that cures the plague"
→ CREATE flora (they're describing something they want in the world)

User: "what kind of villain would work here?"
→ DON'T CREATE (asking for suggestions, not requesting addition)

User: "maybe a corrupt merchant?"
→ DON'T CREATE yet (hypothetical, ask if they want to add it)

User: "yes, add them"
→ CREATE (confirmation of previous discussion)

**EXAMPLE RESPONSES (Good vs Bad):**

GOOD - Character creation with tags:
User: "add a character named John, a blacksmith"
Assistant: "I've added John the blacksmith to your characters.
<create_character>
{
  "name": "John",
  "character_type": "minor",
  "personality": "Skilled craftsman with a gruff exterior",
  "backstory": "Village blacksmith",
  "physical_description": "Muscular build, calloused hands, soot-stained apron"
}
</create_character>"

GOOD - Climate preset with tags:
User: "add a climate preset for a hot, humid coastal climate"
Assistant: "I've added the coastal climate preset to your worldbuilding.
<create_climate_preset>
{
  "name": "Tropical Coastal",
  "description": "Hot, humid equatorial coastal climate",
  "temperature_range": "28-35°C",
  "precipitation_pattern": "Heavy seasonal rainfall",
  "weather_patterns": "Frequent storms and high humidity"
}
</create_climate_preset>"

BAD - No tags (ELEMENT WILL NOT BE CREATED):
User: "add a climate preset for a hot, humid coastal climate"
Assistant: "Here's your climate preset: { \"name\": \"Tropical Coastal\", \"description\": \"Hot and humid\" }"
[This will NOT create anything - tags are required!]

BAD - Rambling and unfocused:
User: "add a character named John, a blacksmith"
Assistant: "I've added John the blacksmith. <create_character>...</create_character> This is interesting because blacksmiths play an important role in medieval societies. Looking at your Act 1, I notice the pacing could be improved. Also, the character development in Chapter 3 needs work, and your villain's motivation isn't clear..."

REMEMBER: After creating an element, confirm briefly and STOP. Don't analyze, critique, or discuss other parts of the project unless specifically asked.

Be encouraging, creative, and constructive. Reference specific details from their project when relevant.
Keep responses focused and actionable.""",

        "chapter_focus": """You are a writing assistant with the full text of the CURRENT CHAPTER available to you.

YOUR ONE JOB: Answer exactly what the author asked. Nothing else.

Do NOT volunteer a critique, a summary, or a list of issues unless the author specifically asked for one.
Do NOT open with a preamble, restatement of the question, or description of what you are about to do.
Start your response with the answer itself.

QUESTION TYPES AND HOW TO HANDLE THEM:

• Direct question about the chapter ("what happens when…", "does X occur", "which character…", "why does…"):
  Answer it directly from the chapter text. Quote the relevant passage if helpful.

• Request for a summary or synopsis:
  Give a concise summary of what happens, who is involved, what changes, and what it sets up.

• Section-specific question ("look at paragraph N", "the scene where…", "the dialogue between…", "the beginning/end"):
  If a SECTION FOCUS block appears in the context, start there. Analyse only that passage.

• Improvement or critique request (only when the author uses words like "critique", "give me feedback", "what needs work", "improve this", "what's wrong with"):
  Work through the chapter section by section. For each section: quote the passage, name the issue, explain why it matters, suggest a concrete fix. Cover the full chapter.

• Anything else:
  Answer it directly.""",

        "writer": """You are a skilled creative writer working as a ghostwriter/collaborator. Your job is to WRITE prose based on the author's outline, world, and characters.

=== SCENE-BY-SCENE WRITING ===
If a CHAPTER OUTLINE or SCENE LIST is provided:
1. Write each scene as a complete, immersive unit
2. Follow the scene order in the outline
3. Flesh out each scene with rich sensory details, character actions, and dialogue
4. Create smooth, natural transitions between scenes (time skips, location changes, or flowing action)
5. Mark your progress: mention which scene you're writing if continuing later

If NO outline is provided:
1. Infer the scene structure from the user's prompt
2. Break the writing into logical scenes with clear beats
3. Ask clarifying questions if the scene direction is unclear

=== POINT OF VIEW - STRICT REQUIREMENT ===
You MUST follow the specified NARRATIVE POV exactly. This is non-negotiable.

NARRATIVE POV RULES:
- FIRST PERSON: Use "I/we/my/me". The POV character narrates their own story.
- THIRD PERSON LIMITED: Use "he/she/they/his/her/their" for the POV character. NEVER use "I" or "my" except in dialogue. Write their thoughts as: "She wondered if..." NOT "I wonder if..."
- THIRD PERSON OMNISCIENT: Use "he/she/they". Can access multiple characters' thoughts.
- SECOND PERSON: Use "you/your". The reader is the protagonist.

CRITICAL: If Third Person is specified, NEVER write "I thought" or "I felt" or "I saw" outside of dialogue. Use the character's name or pronouns: "Marcus thought", "She felt", "He saw".

CHARACTER POV: Write from this character's perspective only. The reader experiences the story through their senses and thoughts (but in the correct narrative voice).

If TEXT BEFORE CURSOR is provided:
- Match the existing narrative voice and pronouns exactly
- Continue mid-sentence or mid-paragraph if that's where it ends
- Maintain the same tense (past/present) as the existing text
- If the existing text uses "she/he", continue using "she/he" - do NOT switch to "I"

=== SHOW DON'T TELL - CRITICAL ===
NEVER write: "She felt angry" or "He was nervous"
INSTEAD write: "Her jaw tightened, fingers curling into fists" or "He drummed his fingers on the table, eyes darting to the door"

Apply this to:
- Emotions: Show through body language, actions, dialogue subtext, physiological responses
- Character traits: Reveal through choices, reactions, and speech patterns
- Atmosphere: Build through sensory details (what they see, hear, smell, feel, taste)
- Backstory: Weave in through natural conversation, memories triggered by present events
- Relationships: Demonstrate through interactions, not exposition

=== WRITING STYLE (from chapter planning) ===
If WRITING STYLE metadata is provided in the context (Tone, Voice, Style, Pacing), follow it exactly:
- TONE: The emotional quality/mood to convey (e.g., "dark and brooding", "lighthearted", "tense")
- VOICE: The narrative personality (e.g., "sardonic", "lyrical", "matter-of-fact")
- STYLE: Prose approach (e.g., "short punchy sentences", "flowery descriptions", "sparse")
- PACING: How fast scenes should move (e.g., "slow contemplative", "rapid-fire action")

If no style metadata is provided, analyze the existing chapter content to match the author's established style.

=== PROSE GUIDELINES ===
1. Follow the specified Tone, Voice, Style, and Pacing from WRITING STYLE above
2. Stay consistent with characters - their voice, speech patterns, motivations, quirks
3. Incorporate worldbuilding naturally through character interaction with the environment
4. Write natural, character-appropriate dialogue with distinct voices
5. Maintain POV consistency throughout

=== SCENE STRUCTURE ===
Each scene should have:
- A clear goal or purpose (what changes by the end?)
- Grounding in setting (where are we? what's the atmosphere?)
- Character action and reaction
- Tension or forward momentum
- A hook or pivot point leading to the next beat

=== TRANSITIONS ===
Between scenes, use:
- Time transitions: "Three days later..." or "By the time the sun set..."
- Space transitions: Describe arrival at new location through character senses
- Emotional bridges: End one scene with an emotion, begin next with its consequence
- Action continuity: End mid-action, resume with result

=== OUTPUT FORMAT - CRITICAL ===
Output ONLY the prose content. Do NOT include:
- Chapter titles, headers, or "Chapter X" labels
- Scene numbers, scene headings, or "Scene X" labels
- The prompts or instructions you were given
- Metadata, notes, or author commentary
- Preambles like "Here's the scene..." or "I'll write..."
- Closing remarks like "Let me know if you want more..."

Just write the prose exactly as it would appear in the final manuscript.

When asked to write:
- Produce actual prose, not summaries
- Write at least several paragraphs per scene
- End at a natural scene break or beat

When asked to continue:
- Pick up exactly where the text ends
- If mid-scene, complete it before transitioning
- Maintain narrative momentum"""
    }

    def __init__(self, message: str, context: dict = None, mode: str = "general"):
        super().__init__()
        self.message = message
        self.context = context or {}
        self.mode = mode

    def _build_context_prompt(self) -> str:
        """Build comprehensive context from project data."""
        parts = []

        # Project info
        if self.context.get('project_name'):
            parts.append(f"PROJECT: {self.context['project_name']}")
            if self.context.get('project_description'):
                parts.append(f"Description: {self.context['project_description'][:300]}")

        # For GENERAL mode: Use RAG-enhanced semantic context if available
        # This provides BOTH creation and discussion capabilities with relevant context
        if self.mode == "general" and self.context.get('rag_context'):
            parts.append(f"\n{'='*60}")
            parts.append("RELEVANT PROJECT CONTEXT (Semantic Search):")
            parts.append(f"{'='*60}")
            parts.append(self.context['rag_context'])

            # Add plot summary if available for broader context
            if self.context.get('plot_summary'):
                parts.append(f"\nPLOT OVERVIEW:\n{self.context['plot_summary']}")

            # Return early - RAG context has all relevant details
            return "\n".join(parts) if parts else ""

        # For other modes: Continue with standard comprehensive context

        # Plot/Story planning
        if self.context.get('plot_summary'):
            parts.append(f"\nPLOT OUTLINE:\n{self.context['plot_summary'][:2000]}")

        # Characters
        if self.context.get('characters'):
            chars = self.context['characters'][:1500]
            parts.append(f"\nMAIN CHARACTERS:\n{chars}")

        # Worldbuilding
        if self.context.get('worldbuilding'):
            wb = self.context['worldbuilding'][:1500]
            parts.append(f"\nWORLDBUILDING:\n{wb}")

        # Current chapter context
        if self.context.get('current_chapter_title'):
            chapter_header = f"CURRENT CHAPTER: {self.context['current_chapter_title']}"
            if self.context.get('chapter_number') and self.context.get('total_chapters'):
                chapter_header += f" (Chapter {self.context['chapter_number']} of {self.context['total_chapters']})"
            parts.append(f"\n{chapter_header}")

            if self.context.get('prev_chapter_title') or self.context.get('next_chapter_title'):
                nav = []
                if self.context.get('prev_chapter_title'):
                    nav.append(f"Previous: \"{self.context['prev_chapter_title']}\"")
                if self.context.get('next_chapter_title'):
                    nav.append(f"Next: \"{self.context['next_chapter_title']}\"")
                parts.append("  " + " | ".join(nav))

            # Chapter synopsis (from planning data or heuristic)
            if self.context.get('chapter_synopsis'):
                parts.append(f"\n=== CHAPTER SYNOPSIS ===\n{self.context['chapter_synopsis']}")

            # Highlighted section when the user referenced a specific part
            if self.context.get('section_reference'):
                sr = self.context['section_reference']
                parts.append(
                    f"\n=== SECTION FOCUS: {sr['description']} ===\n{sr['text']}"
                )

            # Chapter planning/outline (critical for writer mode)
            if self.context.get('chapter_planning'):
                planning = self.context['chapter_planning']
                parts.append("\n=== CHAPTER OUTLINE (Follow this scene-by-scene) ===")

                if planning.get('description'):
                    parts.append(f"Chapter Goal: {planning['description']}")

                if planning.get('pov_character'):
                    parts.append(f"POV Character: {planning['pov_character']}")

                if planning.get('scene_list'):
                    parts.append("\nSCENE LIST (write in order):")
                    for i, scene in enumerate(planning['scene_list'], 1):
                        parts.append(f"  {i}. {scene}")

                if planning.get('events'):
                    parts.append("\nSTORY EVENTS/BEATS:")
                    for event in planning['events']:
                        status = "✓" if event.get('completed') else "○"
                        parts.append(f"  {status} {event['text']}")
                        if event.get('description'):
                            parts.append(f"      {event['description'][:150]}")

                if planning.get('outline') and not planning.get('scene_list'):
                    # Fallback to text outline if no scene list
                    parts.append(f"\nOUTLINE:\n{planning['outline'][:1000]}")

                if planning.get('characters_featured'):
                    parts.append(f"\nFeatured Characters: {', '.join(planning['characters_featured'])}")

                if planning.get('locations'):
                    parts.append(f"Locations: {', '.join(planning['locations'])}")

                if planning.get('themes'):
                    parts.append(f"Themes: {', '.join(planning['themes'])}")

                # Writing style metadata (critical for writer mode)
                style_parts = []
                if planning.get('tone'):
                    style_parts.append(f"Tone: {planning['tone']}")
                if planning.get('voice'):
                    style_parts.append(f"Voice: {planning['voice']}")
                if planning.get('style'):
                    style_parts.append(f"Style: {planning['style']}")
                if planning.get('pacing'):
                    style_parts.append(f"Pacing: {planning['pacing']}")

                if style_parts:
                    parts.append("\n=== WRITING STYLE (Follow these guidelines) ===")
                    parts.extend(style_parts)

            # Writer mode: POV settings (override chapter defaults if specified)
            if self.mode == "writer":
                pov_parts = []
                char_pov = self.context.get('writer_character_pov')
                narrative_pov = self.context.get('writer_narrative_pov')

                if char_pov:
                    pov_parts.append(f"Character POV: {char_pov}")
                elif planning and planning.get('pov_character'):
                    pov_parts.append(f"Character POV: {planning['pov_character']} (from chapter)")

                if narrative_pov:
                    pov_map = {
                        'first_person': 'First Person (I/we)',
                        'third_person_limited': 'Third Person Limited (follows one character)',
                        'third_person_omniscient': 'Third Person Omniscient (all-knowing)',
                        'second_person': 'Second Person (you)'
                    }
                    pov_parts.append(f"Narrative POV: {pov_map.get(narrative_pov, narrative_pov)}")

                if pov_parts:
                    parts.append("\n=== POINT OF VIEW ===\n" + "\n".join(pov_parts))

            # Writer mode: Preceding text for continuity
            if self.mode == "writer" and self.context.get('preceding_text'):
                parts.append(f"\n=== TEXT IMMEDIATELY BEFORE CURSOR (continue from here) ===\n{self.context['preceding_text']}")

                if self.context.get('content_before_summary'):
                    parts.append(f"\n{self.context['content_before_summary']}")

            # Previous chapter ending for continuity
            if self.context.get('previous_chapter_ending'):
                parts.append(f"\n=== PREVIOUS CHAPTER ENDING (for continuity) ===\n...{self.context['previous_chapter_ending']}")

            # Current chapter content
            if self.context.get('current_chapter_content'):
                content = self.context['current_chapter_content']
                # For chapter_focus mode, include as much of the chapter as possible.
                # If a section was already highlighted above, still show the full chapter
                # so the AI can reference surrounding context.
                MAX_CHAPTER_CHARS = 15000  # ~3 000 words — covers most chapters
                if len(content) <= MAX_CHAPTER_CHARS:
                    parts.append(f"\n=== CURRENT CHAPTER CONTENT ===\n{content}")
                else:
                    # Very long chapter: show beginning and end; the SECTION FOCUS block
                    # above already contains the highlighted portion.
                    half = MAX_CHAPTER_CHARS // 2
                    parts.append(
                        f"\n=== CURRENT CHAPTER CONTENT (abridged — chapter is very long) ==="
                        f"\n{content[:half]}"
                        f"\n\n…[middle of chapter omitted for length]…\n\n"
                        f"{content[-half:]}"
                    )


        # All chapters summary (for cross-chapter questions)
        if self.context.get('all_chapters'):
            chapters_info = self.context['all_chapters'][:1500]
            parts.append(f"\nMANUSCRIPT CHAPTERS:\n{chapters_info}")

        return "\n".join(parts) if parts else ""

    def run(self):
        """Process the chat message with AI."""
        try:
            from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig

            ai_config = get_ai_config()
            settings = ai_config.get_settings()

            # Check if AI is disabled
            if ai_config.is_ai_disabled():
                self.error.emit("AI features are disabled. Enable them in Settings > AI Settings.")
                return

            # Check if local models are preferred and configured
            prefer_local = settings.get("prefer_local_model", False)
            enable_local = settings.get("enable_local_models", False)
            local_model_id = settings.get("local_model_id", "")

            if prefer_local and enable_local and local_model_id:
                # Use local model - detect if it's an MLX model
                is_mlx_model = "mlx" in local_model_id.lower()

                hf_config = HuggingFaceConfig(
                    model_id=local_model_id,
                    use_local=True,
                    device=settings.get("local_model_device", "auto"),
                    quantization=settings.get("local_model_quantization", "none") if settings.get("local_model_quantization") != "none" else None,
                    trust_remote_code=settings.get("local_model_trust_remote_code", False)
                )

                # Use MLX provider for MLX models, HuggingFace for others
                provider = LLMProvider.MLX_LOCAL if is_mlx_model else LLMProvider.HUGGINGFACE_LOCAL
                llm = LLMClient(
                    provider=provider,
                    hf_config=hf_config
                )
            else:
                # Use cloud provider
                default_provider = settings.get("default_llm", "claude")
                api_key = ai_config.get_api_key(default_provider)

                if not api_key:
                    self.error.emit(f"No API key configured for {default_provider}. Please add your API key in Settings > AI Settings, or enable local models.")
                    return

                # Map provider name to enum
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }
                provider = provider_map.get(default_provider, LLMProvider.CLAUDE)

                llm = LLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=ai_config.get_model(default_provider)
                )

            # Build system prompt based on mode
            system_prompt = self.SYSTEM_PROMPTS.get(self.mode, self.SYSTEM_PROMPTS["general"])

            # Add project context
            context_prompt = self._build_context_prompt()
            if context_prompt:
                system_prompt += f"\n\n{'='*60}\nPROJECT CONTEXT:\n{'='*60}\n{context_prompt}"

            # For writer mode, add extra emphasis on current chapter
            if self.mode == "writer" and self.context.get('current_chapter_content'):
                system_prompt += "\n\nIMPORTANT: Write prose that seamlessly continues or fits with the existing chapter content above."

            # Generate response (with conversation history for multi-turn context)
            response = llm.generate_text(
                prompt=self.message,
                system_prompt=system_prompt,
                max_tokens=settings.get("max_tokens", 2000),
                temperature=settings.get("temperature", 0.7),
                conversation_history=self.context.get('conversation_history') or []
            )

            self.finished.emit(response, system_prompt)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class MainWindow(QMainWindow):
    """Main application window with all features."""

    project_changed = pyqtSignal()

    def __init__(self):
        """Initialize main window."""
        super().__init__()

        self.current_project: Optional[WriterProject] = None
        self.ai_config = get_ai_config()
        self.settings = self.ai_config.get_settings()

        # Find/Replace dialogs
        self.find_dialog: Optional[FindReplaceDialog] = None
        self.replace_dialog: Optional[FindReplaceDialog] = None

        # Chat worker for AI assistant
        self._chat_worker: Optional[ChatWorker] = None
        self._pending_mode: str = ""
        self._pending_insert_mode: str = ""
        self._pending_chat_message: str = ""

        # Conversation history for multi-turn chat (user+assistant pairs)
        # Max 12 turns kept; older turns are dropped (compaction).
        self._chat_history: list = []
        self._MAX_CHAT_TURNS = 12

        # RAG system for semantic context retrieval
        self._rag_system: Optional[EnhancedRAGSystem] = None
        self._rag_initialized = False

        # Register with window manager
        self.window_manager = WindowManager()
        self.window_manager.set_main_window(self)

        # Apply modern stylesheet
        self.setStyleSheet(get_modern_style())

        self._init_ui()
        self._create_menus()
        self._create_minimal_toolbar()
        self._create_status_bar()
        self._setup_system_tray()

        # Try to load last project, or prompt for new one
        self._startup_load_project()

    def _init_ui(self):
        """Initialize user interface."""
        self.setWindowTitle("Writer Platform")
        self.setMinimumSize(800, 600)  # Reduced from 1200x800 for laptop compatibility

        # Create central widget with splitter for chat
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter for main content and chat
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create tab widget for main sections with modern styling
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)  # Cleaner look
        self.tab_widget.setMovable(True)  # Allow tab reordering

        # Enable context menu on tab bar for multi-window support
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        # Initialize section widgets
        self.worldbuilding_widget = ComprehensiveWorldBuildingWidget()
        self.characters_widget = CharactersWidget()
        self.story_planning_widget = StoryPlanningWidget()
        self.manuscript_editor = ManuscriptEditor()
        self.image_generator = ImageGeneratorWidget()
        self.grader_widget = GraderWidget()
        self.agent_manager = AgentManagerWidget()
        self.attributions_tab = AttributionsTab()
        self.prose_profile_widget = ProseProfileWidget()

        # Connect grader widget signals
        self.grader_widget.go_to_line_requested.connect(self._go_to_critique_line)
        self.grader_widget.ask_about_suggestion.connect(self._ask_about_critique_suggestion)

        # Connect attributions tab jump signal
        self.attributions_tab.jump_to_annotation.connect(self._jump_to_annotation)

        # Add tabs with icons for visual appeal
        self.tab_widget.addTab(self.manuscript_editor, f"{get_icon('manuscript')} Write")
        self.tab_widget.addTab(self.story_planning_widget, f"{get_icon('story')} Plot")
        self.tab_widget.addTab(self.characters_widget, f"{get_icon('characters')} Characters")
        self.tab_widget.addTab(self.worldbuilding_widget, f"{get_icon('worldbuilding')} World")
        self.tab_widget.addTab(self.attributions_tab, "📚 Attributions")
        self.tab_widget.addTab(self.image_generator, f"{get_icon('images')} Visuals")
        self.tab_widget.addTab(self.prose_profile_widget, "🎯 Prose Profile")
        self.tab_widget.addTab(self.grader_widget, f"{get_icon('grader')} Critique")
        self.tab_widget.addTab(self.agent_manager, f"{get_icon('agents')} Publishing")

        # Create collapsible chat widget
        self.chat_widget = ChatWidget()
        self.chat_widget.setMaximumWidth(400)
        self.chat_widget.setMinimumWidth(300)

        # Add to splitter
        self.main_splitter.addWidget(self.tab_widget)
        self.main_splitter.addWidget(self.chat_widget)

        # Set initial splitter sizes (3:1 ratio)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.main_splitter)

        # Connect signals
        self._connect_signals()

    def _create_menus(self):
        """Create application menus."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save Project &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        find_action = QAction("&Find...", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self._show_find_dialog)
        edit_menu.addAction(find_action)

        replace_action = QAction("Find and &Replace...", self)
        replace_action.setShortcut(QKeySequence.StandardKey.Replace)
        replace_action.triggered.connect(self._show_replace_dialog)
        edit_menu.addAction(replace_action)

        edit_menu.addSeparator()

        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._show_settings)
        edit_menu.addAction(settings_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        toggle_chat_action = QAction("Toggle &Chat", self)
        toggle_chat_action.setShortcut(QKeySequence("Ctrl+B"))
        toggle_chat_action.triggered.connect(self._toggle_chat)
        view_menu.addAction(toggle_chat_action)

        stt_action = QAction("&Voice Input", self)
        stt_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        stt_action.triggered.connect(self._toggle_voice_input)
        view_menu.addAction(stt_action)

        view_menu.addSeparator()

        # Multi-window mode toggle
        self.multi_window_action = QAction("&Multi-Window Mode", self)
        self.multi_window_action.setCheckable(True)
        self.multi_window_action.setChecked(False)
        self.multi_window_action.setToolTip("Enable to detach tabs into separate windows")
        self.multi_window_action.triggered.connect(self._toggle_multi_window_mode)
        view_menu.addAction(self.multi_window_action)

        # Export menu
        export_menu = menubar.addMenu("E&xport")

        export_kindle_action = QAction("Export for &Kindle", self)
        export_kindle_action.triggered.connect(lambda: self._export_manuscript("kindle"))
        export_menu.addAction(export_kindle_action)

        export_bn_action = QAction("Export for &Barnes && Noble", self)
        export_bn_action.triggered.connect(lambda: self._export_manuscript("barnes_noble"))
        export_menu.addAction(export_bn_action)

        export_publisher_action = QAction("Export &Publisher Ready", self)
        export_publisher_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        export_menu.addAction(export_publisher_action)

        export_docx_action = QAction("Export as &Word Document", self)
        export_docx_action.triggered.connect(lambda: self._export_manuscript("docx"))
        export_menu.addAction(export_docx_action)

        export_menu.addSeparator()

        export_outline_action = QAction("Export Book &Outline (Chapter Plans)", self)
        export_outline_action.setToolTip("Export all chapter plans as a book outline document")
        export_outline_action.triggered.connect(self._export_book_outline)
        export_menu.addAction(export_outline_action)

        export_menu.addSeparator()

        export_llm_action = QAction("Export for &LLM Context (Markdown)", self)
        export_llm_action.setToolTip("Export worldbuilding, plot, and characters as markdown for AI context")
        export_llm_action.triggered.connect(self._export_llm_context)
        export_menu.addAction(export_llm_action)

        export_summary_action = QAction("Export Project &Summary...", self)
        export_summary_action.setToolTip("Export comprehensive project summary with optional AI/ML summarization")
        export_summary_action.triggered.connect(self._export_project_summary)
        export_menu.addAction(export_summary_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        import_guide_action = QAction("&Import Guide (AI Prompts)", self)
        import_guide_action.setToolTip("Prompts to help build your project with ChatGPT, Claude, or other AI assistants")
        import_guide_action.triggered.connect(self._show_import_guide)
        help_menu.addAction(import_guide_action)

        import_json_action = QAction("Import &JSON Data...", self)
        import_json_action.setToolTip("Import AI-generated JSON data into your project")
        import_json_action.triggered.connect(self._show_json_import)
        help_menu.addAction(import_json_action)

        help_menu.addSeparator()

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_minimal_toolbar(self):
        """Create minimal, modern toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(toolbar.iconSize() * 0.9)  # Slightly smaller icons
        self.addToolBar(toolbar)

        # Project name label (editable feel)
        self.project_name_label = QLabel("Untitled Project")
        self.project_name_label.setProperty("heading", True)
        self.project_name_label.setStyleSheet("padding: 4px 12px; font-size: 18px; font-weight: 600;")
        toolbar.addWidget(self.project_name_label)

        toolbar.addSeparator()

        # Minimal action buttons with icons
        save_action = QAction(f"{get_icon('save')} Save", self)
        save_action.setToolTip("Save Project (Ctrl+S)")
        save_action.triggered.connect(self._save_project)
        toolbar.addAction(save_action)

        export_action = QAction(f"{get_icon('export')} Export", self)
        export_action.setToolTip("Export manuscript")
        export_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        toolbar.addAction(export_action)

        toolbar.addSeparator()

        # AI toggle
        ai_action = QAction(f"{get_icon('ai')} AI", self)
        ai_action.setToolTip("Toggle AI Assistant (Ctrl+B)")
        ai_action.triggered.connect(self._toggle_chat)
        toolbar.addAction(ai_action)

        toolbar.addSeparator()

        # Settings
        settings_action = QAction(f"{get_icon('settings')} Settings", self)
        settings_action.setToolTip("Settings & Configuration (Ctrl+,)")
        settings_action.triggered.connect(self._show_settings)
        toolbar.addAction(settings_action)

    def _create_status_bar(self):
        """Create status bar."""
        self.statusBar().showMessage("Ready")

    def _setup_system_tray(self):
        """Set up the system tray icon and menu."""
        # Check if system tray is available
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("System tray is not available")
            return

        # Load icon - try PNG first (better compatibility), then ICO
        assets_dir = Path(__file__).parent.parent.parent / "assets"
        icon_path = assets_dir / "icon.png"
        if not icon_path.exists():
            icon_path = assets_dir / "icon.ico"

        if icon_path.exists():
            icon = QIcon(str(icon_path))
        else:
            # Fallback to application icon
            icon = self.windowIcon()
            print(f"Icon not found at {icon_path}, using window icon")

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("Writer Platform")

        # Create tray menu
        tray_menu = QMenu()

        # Show/Hide action
        show_action = QAction("Show/Hide", self)
        show_action.triggered.connect(self._toggle_window_visibility)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        # Quick actions
        save_action = QAction("Save Project", self)
        save_action.triggered.connect(self._save_project)
        tray_menu.addAction(save_action)

        tray_menu.addSeparator()

        # Exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)

        # Double-click to show/hide
        self.tray_icon.activated.connect(self._on_tray_activated)

        # Show the tray icon
        self.tray_icon.show()

    def _toggle_window_visibility(self):
        """Toggle main window visibility."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window_visibility()

    def _quit_application(self):
        """Quit the application properly."""
        # Check for unsaved changes
        if self.current_project and not self._confirm_unsaved_changes():
            return

        # Hide tray icon
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()

        # Close the application
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _connect_signals(self):
        """Connect signals between widgets."""
        # Connect project changes
        self.worldbuilding_widget.content_changed.connect(self._on_content_changed)
        self.characters_widget.content_changed.connect(self._on_content_changed)
        self.story_planning_widget.content_changed.connect(self._on_content_changed)
        self.manuscript_editor.content_changed.connect(self._on_content_changed)
        self.prose_profile_widget.content_changed.connect(self._on_content_changed)

        # Connect annotation changes to update attributions tab
        self.manuscript_editor.annotations_changed.connect(self._on_annotations_changed)

        # Auto-save when switching chapters
        self.manuscript_editor.chapter_switched.connect(self._auto_save_project)

        # Update grader widget when switching to Critique tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Connect chat to AI assistance
        self.chat_widget.message_sent.connect(self._handle_chat_message)
        self.chat_widget.clear_requested.connect(self._clear_chat_history)
        self.chat_widget.mode_changed.connect(lambda _: self._clear_chat_history())

        # Connect mic button to voice input
        self.chat_widget.mic_button.clicked.connect(self._toggle_voice_input)

        # Connect manuscript editor selection changes to chat widget
        self._setup_editor_selection_tracking()

    def _setup_editor_selection_tracking(self):
        """Set up tracking of editor selection state for Writer mode."""
        # This will be called again when chapter changes
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            editor = self.manuscript_editor.current_chapter_editor.editor
            editor.selectionChanged.connect(self._on_editor_selection_changed)

    def _on_editor_selection_changed(self):
        """Handle editor selection change - update chat widget."""
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            editor = self.manuscript_editor.current_chapter_editor.editor
            has_selection = editor.textCursor().hasSelection()
            self.chat_widget.update_selection_state(has_selection)

    def _startup_load_project(self):
        """Load last project on startup, or prompt for new one."""
        from pathlib import Path

        last_path = self.ai_config.get_last_project_path()

        if last_path and Path(last_path).exists():
            try:
                self.current_project = WriterProject.load_project(last_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Loaded: {last_path}")
                return
            except Exception as e:
                # Failed to load, will prompt for new project
                QMessageBox.warning(
                    self,
                    "Could Not Load Project",
                    f"Failed to load last project:\n{last_path}\n\nError: {str(e)}\n\nPlease create a new project."
                )

        # No last project or failed to load - prompt for new one
        self._new_project()

    def _new_project(self):
        """Create new project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        from PyQt6.QtWidgets import QInputDialog

        project_name, ok = QInputDialog.getText(
            self, "New Project", "Enter project name:"
        )

        if ok and project_name:
            self.current_project = WriterProject(
                name=project_name,
                manuscript=Manuscript(title=project_name)
            )
            self._load_project_into_ui()
            self.project_name_label.setText(project_name)
            self.statusBar().showMessage(f"Created new project: {project_name}")

    def _open_project(self):
        """Open existing project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            try:
                self.current_project = WriterProject.load_project(file_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Opened: {file_path}")
                # Remember this project for next startup
                self.ai_config.set_last_project_path(file_path)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error Opening Project",
                    f"Failed to open project:\n{str(e)}"
                )

    def _save_project(self):
        """Save current project."""
        if not self.current_project:
            return

        if self.current_project.project_path:
            self._save_to_path(self.current_project.project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        """Save project to new location."""
        if not self.current_project:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            f"{self.current_project.name}.writerproj",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            self._save_to_path(file_path)

    def _save_to_path(self, file_path: str):
        """Save project to specified path."""
        try:
            self._collect_project_data()
            self.current_project.save_project(file_path)
            self.statusBar().showMessage(f"Saved: {file_path}")
            # Remember this project for next startup
            self.ai_config.set_last_project_path(file_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Project",
                f"Failed to save project:\n{str(e)}"
            )

    def _auto_save_project(self):
        """Auto-save project (e.g., when switching chapters).

        Silently saves without showing status messages to avoid interrupting workflow.
        """
        if not self.current_project:
            return

        if self.current_project.project_path:
            try:
                self._collect_project_data()
                self.current_project.save_project(self.current_project.project_path)
                # Update window title to remove unsaved indicator
                self.setWindowTitle(f"Writer Platform - {self.current_project.name}")
            except Exception as e:
                # Log error but don't interrupt user
                print(f"Auto-save failed: {e}")

    def _load_project_into_ui(self):
        """Load current project data into UI widgets."""
        if not self.current_project:
            return

        # Set project reference on manuscript editor for RAG
        self.manuscript_editor.set_project(self.current_project)

        self.worldbuilding_widget.load_data(self.current_project.worldbuilding)
        self.characters_widget.set_project(self.current_project)
        self.characters_widget.load_data(self.current_project.characters)
        self.story_planning_widget.load_data(self.current_project.story_planning)
        self.manuscript_editor.load_manuscript(self.current_project.manuscript)
        self.image_generator.load_data(self.current_project.generated_images)
        # Update characters for image generation
        self.image_generator.set_characters(self.current_project.characters)
        self.agent_manager.load_data(self.current_project.agent_contacts)
        self.prose_profile_widget.load_data(self.current_project.prose_profile)
        self.attributions_tab.set_manuscript(self.current_project.manuscript)

        # Set up grader widget with project reference and content provider
        self.grader_widget.set_project(self.current_project)
        self.grader_widget.set_content_provider(self.manuscript_editor.get_current_chapter_info)

        # Update chat widget with characters for POV selection
        if self.current_project.characters:
            self.chat_widget.set_characters(self.current_project.characters)

        # Set project name for training data metadata
        self.chat_widget.set_project_name(self.current_project.name)

        # Initialize/refresh RAG system for semantic context retrieval
        self._init_rag_system()

        self.project_changed.emit()

    def _init_rag_system(self):
        """Initialize or refresh the RAG system for semantic context retrieval."""
        if not self.current_project:
            return

        try:
            # Initialize RAG system with current project
            if not self._rag_system:
                from src.ai.llm_client import LLMClient, LLMProvider

                # Create a simple LLM client for RAG embeddings
                ai_config = get_ai_config()
                default_provider = self.settings.get("default_llm", "claude")
                api_key = ai_config.get_api_key(default_provider)

                if not api_key:
                    print("No API key for RAG initialization - RAG will be disabled")
                    return

                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI
                }
                provider = provider_map.get(default_provider, LLMProvider.CLAUDE)

                llm_client = LLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=ai_config.get_model(default_provider)
                )

                self._rag_system = EnhancedRAGSystem(
                    project=self.current_project,
                    llm_client=llm_client
                )

            # Rebuild index with current project data
            self._rag_system.rebuild_index()
            self._rag_initialized = True
            print("RAG system initialized successfully")

        except Exception as e:
            print(f"Failed to initialize RAG system: {e}")
            self._rag_initialized = False

    def _get_rag_context(self, query: str, max_tokens: int = 2000) -> str:
        """Get RAG-enhanced context for a query.

        Args:
            query: User's question or request
            max_tokens: Maximum tokens for context

        Returns:
            Relevant context from project data
        """
        if not self._rag_initialized or not self._rag_system:
            return ""

        try:
            context = self._rag_system.get_context_for_ai(
                query=query,
                max_tokens=max_tokens,
                method=SearchMethod.HYBRID
            )
            return context if context else ""
        except Exception as e:
            print(f"RAG context retrieval failed: {e}")
            return ""

    def _collect_project_data(self):
        """Collect data from UI widgets into project model."""
        if not self.current_project:
            return

        self.current_project.worldbuilding = self.worldbuilding_widget.get_data()
        self.current_project.characters = self.characters_widget.get_data()
        self.current_project.story_planning = self.story_planning_widget.get_data()
        self.current_project.manuscript = self.manuscript_editor.get_manuscript()
        self.current_project.generated_images = self.image_generator.get_data()
        self.current_project.agent_contacts = self.agent_manager.get_data()
        self.current_project.prose_profile = self.prose_profile_widget.get_data()

    def _confirm_unsaved_changes(self) -> bool:
        """Ask user to confirm discarding unsaved changes."""
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Do you want to save changes to the current project?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Save:
            self._save_project()
            return True
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    def _on_content_changed(self):
        """Handle content changes in any widget."""
        # Mark project as modified
        if self.current_project:
            window_title = f"Writer Platform - {self.current_project.name}*"
            self.setWindowTitle(window_title)

            # Update characters in image generator when characters change
            characters = self.characters_widget.get_data()
            self.image_generator.set_characters(characters)

    def _on_annotations_changed(self):
        """Handle annotation changes - update attributions tab."""
        if self.current_project:
            self.attributions_tab.set_manuscript(self.current_project.manuscript)
            self._on_content_changed()

    def _on_tab_changed(self, index: int):
        """Handle tab change - update grader widget with current chapter when Critique tab selected."""
        # Check if this is the Critique tab (index 6 based on tab order)
        current_widget = self.tab_widget.widget(index)
        if current_widget == self.grader_widget:
            # Update grader widget with current chapter content
            content, title = self.manuscript_editor.get_current_chapter_info()
            self.grader_widget.set_current_chapter(content, title)

        # Update editor selection tracking when manuscript tab is active
        if index == 0:  # Manuscript tab
            self._setup_editor_selection_tracking()

    def _toggle_chat(self):
        """Toggle chat widget visibility."""
        if self.chat_widget.isVisible():
            self.chat_widget.hide()
        else:
            self.chat_widget.show()

    def _toggle_voice_input(self):
        """Toggle speech-to-text input."""
        stt = get_stt_service()
        if stt.is_listening():
            stt.stop()
            return

        if not stt.is_available():
            QMessageBox.warning(
                self, "Voice Input",
                "Speech recognition not available.\nInstall with: pip install SpeechRecognition pyaudio"
            )
            return

        from PyQt6.QtCore import QTimer

        def on_result(text: str):
            QTimer.singleShot(0, lambda: self._handle_voice_result(text))

        def on_error(msg: str):
            QTimer.singleShot(0, lambda: self._on_voice_error(msg))

        def on_listening(active: bool):
            QTimer.singleShot(0, lambda: self._update_mic_state(active))

        stt.on_result = on_result
        stt.on_error = on_error
        stt.on_listening = on_listening
        stt.start()

    def _handle_voice_result(self, text: str):
        """Route transcribed speech to editor or chat."""
        stripped = text.strip()
        lower = stripped.lower()

        # "write ..." → insert into text editor
        if lower.startswith("write "):
            content = stripped[6:].strip()
            if content and hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
                editor = self.manuscript_editor.current_chapter_editor.editor
                cursor = editor.textCursor()
                cursor.insertText(content)
                editor.setTextCursor(cursor)
                self.statusBar().showMessage("Voice: text inserted", 3000)
            else:
                self.statusBar().showMessage("Voice: no active chapter to write to", 3000)
        else:
            # Send to chat
            if not self.chat_widget.isVisible():
                self.chat_widget.show()
            self.chat_widget.input_field.setText(stripped)
            self.chat_widget._send_message()

    def _on_voice_error(self, msg: str):
        """Show voice input error."""
        self.statusBar().showMessage(f"Voice: {msg}", 4000)

    def _update_mic_state(self, active: bool):
        """Update mic button appearance based on listening state."""
        if hasattr(self.chat_widget, 'mic_button'):
            if active:
                self.chat_widget.mic_button.setStyleSheet("""
                    QPushButton {
                        background-color: #ef4444;
                        border: none;
                        border-radius: 8px;
                        font-size: 16px;
                    }
                    QPushButton:hover { background-color: #dc2626; }
                """)
                self.chat_widget.mic_button.setToolTip("Listening... click to cancel")
            else:
                self.chat_widget.mic_button.setStyleSheet("""
                    QPushButton {
                        background-color: #f3f4f6;
                        border: 1px solid #e5e7eb;
                        border-radius: 8px;
                        font-size: 16px;
                    }
                    QPushButton:hover { background-color: #e5e7eb; }
                """)
                self.chat_widget.mic_button.setToolTip("Voice input (Ctrl+Shift+V)")

    def _clear_chat_history(self):
        """Clear the conversation history (triggered by Clear button)."""
        self._chat_history = []

    def _compact_chat_history(self):
        """Keep at most _MAX_CHAT_TURNS turns; drop oldest pairs when over limit."""
        # Each turn = one user message + one assistant message = 2 items
        max_messages = self._MAX_CHAT_TURNS * 2
        if len(self._chat_history) > max_messages:
            self._chat_history = self._chat_history[-max_messages:]

    def _handle_chat_message(self, message: str, mode: str = "general", insert_mode: str = ""):
        """Handle chat message from user.

        Args:
            message: The user's message
            mode: The chat mode (general, chapter_focus, writer)
            insert_mode: For writer mode, how to insert text (replace_selection, insert_at_cursor, append_to_chapter, replace_chapter)
        """
        # Check if already processing
        if self._chat_worker and self._chat_worker.isRunning():
            self.chat_widget.add_message("Assistant", "Please wait, I'm still thinking...")
            return

        # Build comprehensive project context based on mode
        # Pass the user message so RAG can retrieve relevant context
        context = self._build_chat_context(mode, user_message=message)

        # For writer mode, add POV settings and cursor context
        if mode == "writer":
            writer_settings = self.chat_widget.get_writer_settings()
            context['writer_character_pov'] = writer_settings.get('character_pov', '')
            context['writer_narrative_pov'] = writer_settings.get('writing_pov', '')

            # Get text before and after cursor for continuity
            if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
                editor = self.manuscript_editor.current_chapter_editor.editor
                cursor = editor.textCursor()
                full_text = editor.toPlainText()

                cursor_pos = cursor.position()
                text_before = full_text[:cursor_pos]
                text_after = full_text[cursor_pos:]

                # Get last 2-3 paragraphs before cursor for continuity
                paragraphs_before = text_before.split('\n\n')
                if paragraphs_before:
                    context['preceding_text'] = '\n\n'.join(paragraphs_before[-3:])[-1500:]

                # Summary of what's written so far
                if text_before:
                    word_count = len(text_before.split())
                    context['content_before_summary'] = f"[{word_count} words written before cursor]"

                # Store cursor position for context
                context['cursor_position'] = cursor_pos
                context['has_content_after'] = bool(text_after.strip())

        # Store insert mode for writer responses
        self._pending_insert_mode = insert_mode if mode == "writer" else ""
        self._pending_mode = mode
        self._pending_chat_message = message

        # Pass conversation history only for general/chapter_focus modes (not writer)
        if mode != "writer":
            context['conversation_history'] = list(self._chat_history)
        else:
            context['conversation_history'] = []

        # Set chapter context for training data metadata (style/voice/tone)
        # This captures the author's intended style for this specific work
        if mode in ("chapter_focus", "writer") and hasattr(self, 'manuscript_editor'):
            chapter_planning = None
            chapter_title = None
            chapter_number = None

            if self.manuscript_editor.current_chapter_editor:
                chapter = self.manuscript_editor.current_chapter_editor.chapter
                if hasattr(chapter, 'planning') and chapter.planning:
                    chapter_planning = chapter.planning
                if hasattr(chapter, 'title'):
                    chapter_title = chapter.title
                if hasattr(chapter, 'number'):
                    chapter_number = chapter.number

            self.chat_widget.set_chapter_context(
                chapter_planning=chapter_planning,
                chapter_title=chapter_title,
                chapter_number=chapter_number
            )
        else:
            # Clear chapter context for general mode
            self.chat_widget.set_chapter_context()

        # Show thinking indicator based on mode
        if mode == "writer":
            self.chat_widget.add_message("Assistant", "Writing...")
        elif mode == "chapter_focus":
            self.chat_widget.add_message("Assistant", "Analyzing chapter...")
        else:
            self.chat_widget.add_message("Assistant", "Thinking...")

        # Start background worker with mode
        self._chat_worker = ChatWorker(message, context, mode)
        self._chat_worker.finished.connect(self._on_chat_response)
        self._chat_worker.error.connect(self._on_chat_error)
        self._chat_worker.start()

    # ── Chapter-focus context helpers ──────────────────────────────────────

    def _get_chapter_synopsis(self, chapter, chapter_text: str) -> str:
        """Return a short synopsis for a chapter.

        Priority:
        1. chapter.planning.description (author wrote it)
        2. chapter.planning.outline (first 400 chars)
        3. Heuristic extraction: opening paragraph + a key-event sentence + closing paragraph
        """
        if hasattr(chapter, 'planning') and chapter.planning:
            if chapter.planning.description:
                return chapter.planning.description[:500]
            if chapter.planning.outline:
                return chapter.planning.outline[:400]

        if not chapter_text:
            return ""

        paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
        if not paragraphs:
            return ""

        parts = [paragraphs[0][:250]]

        # Look for a key-event paragraph in the first half
        event_keywords = [
            'realized', 'discovered', 'revealed', 'decided', 'fled', 'attacked',
            'escaped', 'died', 'arrived', 'confronted', 'finally', 'suddenly',
            'but then', 'at last', 'turned out', 'betrayed', 'whispered', 'shouted'
        ]
        mid = max(1, len(paragraphs) // 2)
        for para in paragraphs[1:mid]:
            if any(kw in para.lower() for kw in event_keywords):
                parts.append(para[:200])
                break

        if len(paragraphs) > 1:
            parts.append(f"…{paragraphs[-1][:200]}")

        return ' '.join(parts)[:600]

    def _detect_section_reference(self, chapter_text: str, message: str) -> dict:
        """Detect whether the user is asking about a specific section and extract it.

        Returns a dict with 'text' and 'description' keys, or an empty dict when
        no specific section can be identified.
        """
        import re
        if not chapter_text:
            return {}

        message_lower = message.lower()
        paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
        if not paragraphs:
            return {}

        # Paragraph-number reference: "paragraph 3", "para 5"
        para_match = re.search(r'\bparagraph[s]?\s*(\d+)\b|\bpara\s*(\d+)\b', message_lower)
        if para_match:
            para_num = int(next(g for g in para_match.groups() if g is not None))
            if 0 < para_num <= len(paragraphs):
                idx = para_num - 1
                start = max(0, idx - 1)
                end = min(len(paragraphs), idx + 2)
                return {
                    'text': '\n\n'.join(paragraphs[start:end]),
                    'description': f'Paragraph {para_num} with surrounding context'
                }

        # Position keywords: beginning / middle / end / climax …
        position_map = {
            'beginning': (0, 0.25), 'opening': (0, 0.25), 'start': (0, 0.25),
            'middle': (0.3, 0.70),
            'climax': (0.6, 0.88),
            'ending': (0.75, 1.0), 'end': (0.75, 1.0), 'conclusion': (0.75, 1.0),
        }
        total = len(paragraphs)
        for keyword, (s_pct, e_pct) in position_map.items():
            if re.search(rf'\b{keyword}\b', message_lower):
                s_idx = int(total * s_pct)
                e_idx = min(total, int(total * e_pct) + 1)
                return {
                    'text': '\n\n'.join(paragraphs[s_idx:e_idx])[:3000],
                    'description': f'The {keyword} of the chapter'
                }

        # Scene / content keyword patterns
        scene_patterns = [
            r'scene where (.{5,60})',
            r'part where (.{5,60})',
            r'part about (.{5,60})',
            r'dialogue (?:where|when|between|with) (.{5,50})',
            r'moment when (.{5,50})',
            r'when (.{5,50}) (?:happens?|occurs?|says?|asks?|tells?|reveals?)',
        ]
        for pattern in scene_patterns:
            m = re.search(pattern, message_lower)
            if m:
                keyword = m.group(m.lastindex).strip()
                # Search the chapter for the most significant word in the keyword
                for word in keyword.split()[:5]:
                    if len(word) > 4:
                        pos = chapter_text.lower().find(word)
                        if pos >= 0:
                            # Find the paragraph that contains this position
                            char_pos = 0
                            for i, para in enumerate(paragraphs):
                                if char_pos <= pos < char_pos + len(para) + 2:
                                    start = max(0, i - 1)
                                    end = min(len(paragraphs), i + 2)
                                    return {
                                        'text': '\n\n'.join(paragraphs[start:end])[:3000],
                                        'description': f'The section containing "{keyword}"'
                                    }
                                char_pos += len(para) + 2

        return {}

    # ── End chapter-focus context helpers ─────────────────────────────────

    def _build_chat_context(self, mode: str = "general", user_message: str = "") -> dict:
        """Build comprehensive context dict for AI chat, similar to chapter planner.

        Args:
            mode: The chat mode (general, chapter_focus, writer)
            user_message: The user's message for RAG-based context retrieval
        """
        context = {}
        context['mode'] = mode

        if not self.current_project:
            return context

        project = self.current_project

        # Basic project info
        context['project_name'] = project.name
        context['project_description'] = project.description or ""

        # For GENERAL mode, use RAG for semantic context retrieval
        # This allows both element creation AND discussion based on relevant context
        if mode == "general" and user_message and self._rag_initialized:
            rag_context = self._get_rag_context(user_message, max_tokens=2000)
            if rag_context:
                context['rag_context'] = rag_context
                # Also add a summary for discussion
                context['semantic_context'] = rag_context
                # Return early with RAG context - it already has relevant info
                # But still add basic summaries if available
                if hasattr(project, 'ai_summary') and project.ai_summary and not project.ai_summary.is_empty():
                    context['plot_summary'] = project.ai_summary.plot_summary[:500] if project.ai_summary.plot_summary else ""
                return context

        # For chapter_focus and writer modes, we want MORE context about the current chapter
        is_chapter_focused = mode in ("chapter_focus", "writer")

        # Try to use AI-generated summaries if available (more efficient)
        use_ai_summary = (hasattr(project, 'ai_summary') and
                         project.ai_summary and
                         not project.ai_summary.is_empty())

        if use_ai_summary:
            summary = project.ai_summary
            context['plot_summary'] = summary.plot_summary or ""
            context['worldbuilding'] = summary.worldbuilding_summary or ""
            context['characters'] = summary.character_summary or ""
        else:
            # Fallback: extract from story planning and worldbuilding
            # Plot from story planning
            if hasattr(project, 'story_planning') and project.story_planning:
                plot_parts = []
                sp = project.story_planning
                if sp.main_plot:
                    plot_parts.append(f"Main Plot: {sp.main_plot}")
                if sp.themes:
                    plot_parts.append(f"Themes: {', '.join(sp.themes)}")
                if sp.subplots:
                    subplots = [f"- {s.title}: {s.description}" for s in sp.subplots[:5]]
                    plot_parts.append("Subplots:\n" + "\n".join(subplots))
                if sp.freytag_pyramid:
                    fp = sp.freytag_pyramid
                    if fp.exposition:
                        plot_parts.append(f"Exposition: {fp.exposition[:200]}")
                    if fp.climax:
                        plot_parts.append(f"Climax: {fp.climax[:200]}")
                context['plot_summary'] = "\n\n".join(plot_parts)

            # Characters - include more detail for writer mode
            if hasattr(project, 'characters') and project.characters:
                char_summaries = []
                char_limit = 15 if is_chapter_focused else 10
                for char in project.characters[:char_limit]:
                    if is_chapter_focused:
                        # Include more character detail for writing
                        char_info = f"- {char.name} ({char.character_type})"
                        if char.personality:
                            char_info += f"\n  Personality: {char.personality[:200]}"
                        if hasattr(char, 'speaking_style') and char.speaking_style:
                            char_info += f"\n  Speech: {char.speaking_style[:100]}"
                        if hasattr(char, 'motivations') and char.motivations:
                            char_info += f"\n  Motivations: {char.motivations[:100]}"
                    else:
                        char_info = f"- {char.name} ({char.character_type})"
                        if char.personality:
                            char_info += f": {char.personality[:100]}"
                    char_summaries.append(char_info)
                context['characters'] = "\n".join(char_summaries)

            # Worldbuilding - include more detail for writer mode
            if hasattr(project, 'worldbuilding') and project.worldbuilding:
                wb = project.worldbuilding
                wb_parts = []
                detail_limit = 500 if is_chapter_focused else 300
                if wb.mythology:
                    wb_parts.append(f"Mythology: {wb.mythology[:detail_limit]}")
                if wb.history:
                    wb_parts.append(f"History: {wb.history[:detail_limit]}")
                if wb.politics:
                    wb_parts.append(f"Politics: {wb.politics[:detail_limit]}")
                if wb.factions:
                    if is_chapter_focused:
                        faction_info = [f"{f.name}: {f.description[:100] if hasattr(f, 'description') and f.description else ''}" for f in wb.factions[:8]]
                    else:
                        faction_info = [f.name for f in wb.factions[:5]]
                    wb_parts.append(f"Factions: {', '.join(faction_info)}")
                if wb.places:
                    if is_chapter_focused:
                        place_info = [f"{p.name}: {p.description[:100] if hasattr(p, 'description') and p.description else ''}" for p in wb.places[:8]]
                    else:
                        place_info = [p.name for p in wb.places[:5]]
                    wb_parts.append(f"Places: {', '.join(place_info)}")
                context['worldbuilding'] = "\n".join(wb_parts)

        # Current chapter context - include MORE for chapter_focus and writer modes
        if hasattr(self, 'manuscript_editor'):
            content, title = self.manuscript_editor.get_current_chapter_info()
            if title:
                context['current_chapter_title'] = title
                if is_chapter_focused:
                    # Include FULL chapter content for focused modes
                    context['current_chapter_content'] = content or ""
                else:
                    # General mode: just include excerpt
                    context['current_chapter_content'] = content[:2000] if content else ""

                # Get chapter planning/outline if available (especially for writer mode)
                if is_chapter_focused and self.manuscript_editor.current_chapter_editor:
                    chapter = self.manuscript_editor.current_chapter_editor.chapter
                    if hasattr(chapter, 'planning') and chapter.planning:
                        planning = chapter.planning
                        context['chapter_planning'] = {
                            'outline': planning.outline,
                            'description': planning.description,
                            'pov_character': planning.pov_character,
                            'scene_list': planning.scene_list,
                            'events': [
                                {
                                    'id': e.id,
                                    'text': e.text,
                                    'description': e.description,
                                    'completed': e.completed,
                                    'stage': e.stage
                                }
                                for e in planning.events
                            ] if planning.events else [],
                            'characters_featured': planning.characters_featured,
                            'locations': planning.locations,
                            'themes': planning.themes,
                            'timeline_position': planning.timeline_position,
                            'notes': planning.notes_as_text,
                            # Writing style metadata
                            'tone': getattr(planning, 'tone', ''),
                            'voice': getattr(planning, 'voice', ''),
                            'style': getattr(planning, 'style', ''),
                            'pacing': getattr(planning, 'pacing', '')
                        }

                    # Chapter synopsis — planning data first, then heuristic from text
                    synopsis = self._get_chapter_synopsis(chapter, content or "")
                    if synopsis:
                        context['chapter_synopsis'] = synopsis

                    # Detect if the user is asking about a specific section
                    if user_message and content:
                        section_ref = self._detect_section_reference(content, user_message)
                        if section_ref:
                            context['section_reference'] = section_ref

                    # Detect explicit critique/improvement requests
                    if user_message:
                        improvement_kws = [
                            'critique', "what's wrong", 'give me feedback', 'needs work',
                            'what needs work', 'improve this', 'what are the issues',
                            'what are the problems', 'give feedback'
                        ]
                        if any(kw in user_message.lower() for kw in improvement_kws):
                            context['is_improvement_question'] = True

        # All chapters list (for cross-chapter questions) + chapter position metadata
        if hasattr(project, 'manuscript') and project.manuscript and project.manuscript.chapters:
            all_chapters = project.manuscript.chapters
            chapter_list = []
            for i, ch in enumerate(all_chapters[:20]):  # Limit to 20
                word_count = len(ch.content.split()) if ch.content else 0
                chapter_list.append(f"{i+1}. {ch.title} ({word_count} words)")
            context['all_chapters'] = "\n".join(chapter_list)
            context['total_chapters'] = len(all_chapters)

            # Chapter position for chapter_focus mode (find which chapter is open)
            if is_chapter_focused and hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
                open_chapter = self.manuscript_editor.current_chapter_editor.chapter
                for i, ch in enumerate(all_chapters):
                    if ch.id == open_chapter.id:
                        context['chapter_number'] = i + 1
                        if i > 0:
                            context['prev_chapter_title'] = all_chapters[i - 1].title
                        if i < len(all_chapters) - 1:
                            context['next_chapter_title'] = all_chapters[i + 1].title
                        break

            # For writer mode, include previous chapter ending for continuity
            if mode == "writer" and hasattr(self, 'manuscript_editor'):
                # Get current chapter index from the chapter list widget
                if hasattr(self.manuscript_editor, 'chapter_list'):
                    current_idx = self.manuscript_editor.chapter_list.currentRow()
                    if current_idx > 0:
                        prev_ch = project.manuscript.chapters[current_idx - 1]
                        if prev_ch.content:
                            # Last 500 chars of previous chapter
                            context['previous_chapter_ending'] = prev_ch.content[-500:]

        return context

    def _on_chat_response(self, response: str, system_prompt: str = ""):
        """Handle successful AI response.

        Args:
            response: The AI's response text (original, with tool calls)
            system_prompt: The system prompt used for this response
        """
        # Check if this was a writer mode request
        if getattr(self, '_pending_mode', '') == 'writer' and hasattr(self, '_pending_insert_mode'):
            self._handle_writer_response(response)
        else:
            # Check for and handle element creation blocks in general mode
            display_response, created_elements = self._parse_and_create_elements(response)

            # Show the conversational part of the response
            # IMPORTANT: Pass BOTH display_response (for UI) AND original response (for training with tool calls)
            self.chat_widget.add_message(
                "Assistant",
                display_response,
                system_prompt=system_prompt,
                original_response=response  # Preserve tool calls for training data
            )

            # Append this turn to conversation history, then compact if needed
            pending_msg = getattr(self, '_pending_chat_message', '')
            if pending_msg and getattr(self, '_pending_mode', '') != 'writer':
                self._chat_history.append({"role": "user", "content": pending_msg})
                self._chat_history.append({"role": "assistant", "content": display_response})
                self._compact_chat_history()
            self._pending_chat_message = ""

            # If elements were created, show confirmation and refresh UI
            if created_elements:
                for element_type, element_name in created_elements:
                    self.statusBar().showMessage(
                        f"Created {element_type}: {element_name}", 5000
                    )
                # Refresh relevant UI widgets
                self._refresh_project_widgets()

    def _handle_writer_response(self, response: str):
        """Handle AI response in writer mode - insert into editor.

        Args:
            response: The AI-generated text to insert
        """
        insert_mode = getattr(self, '_pending_insert_mode', 'insert_at_cursor')

        # Get the current chapter editor
        if not hasattr(self, 'manuscript_editor') or not self.manuscript_editor.current_chapter_editor:
            self.chat_widget.add_message("Assistant", "No chapter is open. Please select a chapter first.")
            return

        editor = self.manuscript_editor.current_chapter_editor.editor
        word_count = len(response.split())

        try:
            if insert_mode == 'replace_selection':
                # Replace selected text
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    cursor.insertText(response)
                    action = "replaced selection"
                else:
                    # Fallback to insert at cursor if no selection
                    cursor.insertText(response)
                    action = "inserted at cursor"

            elif insert_mode == 'insert_at_cursor':
                # Insert at current cursor position
                cursor = editor.textCursor()
                cursor.insertText(response)
                action = "inserted at cursor"

            elif insert_mode == 'append_to_chapter':
                # Append to end of chapter
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                # Add spacing before appending
                current_text = editor.toPlainText()
                if current_text and not current_text.endswith('\n\n'):
                    cursor.insertText('\n\n')
                cursor.insertText(response)
                action = "appended to chapter"

            elif insert_mode == 'replace_chapter':
                # Replace entire chapter content
                editor.setPlainText(response)
                action = "replaced chapter"

            else:
                # Fallback
                cursor = editor.textCursor()
                cursor.insertText(response)
                action = "inserted"

            # Show confirmation in chat (not the full text)
            self.chat_widget.add_message(
                "Assistant",
                f"Done! {word_count} words {action}."
            )

            # Show status bar notification
            self.statusBar().showMessage(f"Writer: {word_count} words {action}", 5000)

        except Exception as e:
            self.chat_widget.add_message("Assistant", f"Error inserting text: {str(e)}")

    def _on_chat_error(self, error: str):
        """Handle AI chat error."""
        self.chat_widget.add_message("Assistant", f"Sorry, I encountered an issue: {error}")

    def _parse_and_create_elements(self, response: str) -> tuple:
        """Parse AI response for element creation blocks and create elements.

        Args:
            response: The AI response text

        Returns:
            Tuple of (display_response, created_elements)
            - display_response: Response with creation blocks removed for display
            - created_elements: List of (element_type, element_name) tuples
        """
        import re
        import json
        from datetime import datetime

        if not self.current_project:
            return response, []

        created_elements = []
        display_response = response

        # Define creation patterns and handlers
        creation_patterns = [
            (r'<create_character>\s*(.*?)\s*</create_character>', self._create_character_from_json),
            (r'<create_place>\s*(.*?)\s*</create_place>', self._create_place_from_json),
            (r'<create_faction>\s*(.*?)\s*</create_faction>', self._create_faction_from_json),
            (r'<create_culture>\s*(.*?)\s*</create_culture>', self._create_culture_from_json),
            (r'<create_myth>\s*(.*?)\s*</create_myth>', self._create_myth_from_json),
            (r'<create_historical_event>\s*(.*?)\s*</create_historical_event>', self._create_historical_event_from_json),
            (r'<create_technology>\s*(.*?)\s*</create_technology>', self._create_technology_from_json),
            (r'<create_flora>\s*(.*?)\s*</create_flora>', self._create_flora_from_json),
            (r'<create_fauna>\s*(.*?)\s*</create_fauna>', self._create_fauna_from_json),
            (r'<create_chapter>\s*(.*?)\s*</create_chapter>', self._create_chapter_from_json),
            (r'<create_climate_preset>\s*(.*?)\s*</create_climate_preset>', self._create_climate_preset_from_json),
            (r'<create_planet>\s*(.*?)\s*</create_planet>', self._create_planet_from_json),
            (r'<create_star_system>\s*(.*?)\s*</create_star_system>', self._create_star_system_from_json),
        ]

        for pattern, handler in creation_patterns:
            matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
            for match in matches:
                try:
                    # Try to parse JSON from the match
                    json_str = match.strip()
                    # Handle potential JSON issues (single quotes, trailing commas)
                    json_str = re.sub(r",\s*}", "}", json_str)
                    json_str = re.sub(r",\s*]", "]", json_str)

                    data = json.loads(json_str)
                    result = handler(data)
                    if result:
                        created_elements.append(result)
                except json.JSONDecodeError as e:
                    print(f"Failed to parse creation JSON: {e}")
                    print(f"JSON string was: {match[:200]}...")
                except Exception as e:
                    print(f"Failed to create element: {e}")

        # Remove creation blocks from display response
        for pattern, _ in creation_patterns:
            display_response = re.sub(pattern, '', display_response, flags=re.DOTALL | re.IGNORECASE)

        # Clean up extra whitespace
        display_response = re.sub(r'\n{3,}', '\n\n', display_response).strip()

        return display_response, created_elements

    def _create_character_from_json(self, data: dict) -> tuple:
        """Create a character from JSON data.

        Args:
            data: Dictionary with character fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        char_id = f"char_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.characters)}"

        # Map character_type to valid values
        char_type = data.get('character_type', 'minor').lower()
        if char_type not in ['protagonist', 'antagonist', 'major', 'minor']:
            char_type = 'minor'

        character = Character(
            id=char_id,
            name=name,
            character_type=char_type,
            personality=data.get('personality', ''),
            backstory=data.get('backstory', ''),
            physical_description=data.get('physical_description', ''),
            notes=data.get('notes', ''),
        )

        self.current_project.characters.append(character)
        print(f"Created character: {name} ({char_type})")
        return ('character', name)

    def _create_place_from_json(self, data: dict) -> tuple:
        """Create a place from JSON data.

        Args:
            data: Dictionary with place fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        place_id = f"place_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.places)}"

        # Map location_type to PlaceType enum
        loc_type = data.get('location_type', 'other').lower().replace(' ', '_')
        try:
            place_type = PlaceType(loc_type)
        except ValueError:
            place_type = PlaceType.OTHER

        place = Place(
            id=place_id,
            name=name,
            place_type=place_type,
            description=data.get('description', ''),
            story_relevance=data.get('significance', ''),
            notes=data.get('notes', ''),
        )

        self.current_project.worldbuilding.places.append(place)
        print(f"Created place: {name} ({place_type.value})")
        return ('place', name)

    def _create_faction_from_json(self, data: dict) -> tuple:
        """Create a faction from JSON data.

        Args:
            data: Dictionary with faction fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        faction_id = f"faction_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.factions)}"

        # Default to organization type
        faction_type = FactionType.ORGANIZATION

        # Build description from provided fields
        description_parts = []
        if data.get('description'):
            description_parts.append(data['description'])
        if data.get('ideology'):
            description_parts.append(f"Ideology: {data['ideology']}")
        if data.get('leadership'):
            description_parts.append(f"Leadership: {data['leadership']}")
        if data.get('relationships'):
            description_parts.append(f"Relationships: {data['relationships']}")

        faction = Faction(
            id=faction_id,
            name=name,
            faction_type=faction_type,
            description='\n\n'.join(description_parts),
            notes=data.get('notes', ''),
        )

        self.current_project.worldbuilding.factions.append(faction)
        print(f"Created faction: {name}")
        return ('faction', name)

    def _create_culture_from_json(self, data: dict) -> tuple:
        """Create a culture from JSON data.

        Args:
            data: Dictionary with culture fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        culture_id = f"culture_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.cultures)}"

        # Build description from provided fields
        description_parts = []
        if data.get('description'):
            description_parts.append(data['description'])
        if data.get('customs'):
            description_parts.append(f"Customs: {data['customs']}")
        if data.get('values'):
            description_parts.append(f"Values: {data['values']}")

        # Extract core values as list
        core_values = []
        if data.get('values'):
            # Try to parse comma-separated values
            core_values = [v.strip() for v in data['values'].split(',') if v.strip()]

        culture = Culture(
            id=culture_id,
            name=name,
            description='\n\n'.join(description_parts),
            core_values=core_values,
            notes=data.get('notes', ''),
        )

        self.current_project.worldbuilding.cultures.append(culture)
        print(f"Created culture: {name}")
        return ('culture', name)

    def _create_myth_from_json(self, data: dict) -> tuple:
        """Create a myth from JSON data.

        Args:
            data: Dictionary with myth fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        myth_id = f"myth_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.myths)}"

        # Parse key_figures - could be string or list
        key_figures = data.get('key_figures', [])
        if isinstance(key_figures, str):
            key_figures = [f.strip() for f in key_figures.split(',') if f.strip()]

        myth = Myth(
            id=myth_id,
            name=name,
            myth_type=data.get('myth_type', 'origin'),
            description=data.get('description', ''),
            full_text=data.get('full_text', ''),
            moral_lesson=data.get('moral_lesson', ''),
            key_figures=key_figures,
        )

        self.current_project.worldbuilding.myths.append(myth)
        print(f"Created myth: {name}")
        return ('myth', name)

    def _create_historical_event_from_json(self, data: dict) -> tuple:
        """Create a historical event from JSON data.

        Args:
            data: Dictionary with historical event fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        event_id = f"event_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.historical_events)}"

        # Parse key_figures - could be string or list
        key_figures = data.get('key_figures', [])
        if isinstance(key_figures, str):
            key_figures = [f.strip() for f in key_figures.split(',') if f.strip()]

        # Parse factions_involved - could be string or list
        factions_involved = data.get('factions_involved', [])
        if isinstance(factions_involved, str):
            factions_involved = [f.strip() for f in factions_involved.split(',') if f.strip()]

        event = HistoricalEvent(
            id=event_id,
            name=name,
            date=data.get('date', ''),
            event_type=data.get('event_type', 'general'),
            description=data.get('description', ''),
            consequences=data.get('consequences', ''),
            key_figures=key_figures,
            factions_involved=factions_involved,
            location=data.get('location', None),
        )

        self.current_project.worldbuilding.historical_events.append(event)
        print(f"Created historical event: {name}")
        return ('historical_event', name)

    def _create_technology_from_json(self, data: dict) -> tuple:
        """Create a technology from JSON data.

        Args:
            data: Dictionary with technology fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        tech_id = f"tech_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.technologies)}"

        # Map technology_type to TechnologyType enum
        tech_type = data.get('technology_type', 'other').lower().replace(' ', '_')
        try:
            technology_type = TechnologyType(tech_type)
        except ValueError:
            technology_type = TechnologyType.OTHER

        # Parse applications - could be string or list
        applications = data.get('applications', [])
        if isinstance(applications, str):
            applications = [a.strip() for a in applications.split(',') if a.strip()]

        technology = Technology(
            id=tech_id,
            name=name,
            technology_type=technology_type,
            description=data.get('description', ''),
            applications=applications,
            limitations=data.get('limitations', ''),
            story_relevance=data.get('story_relevance', ''),
        )

        self.current_project.worldbuilding.technologies.append(technology)
        print(f"Created technology: {name}")
        return ('technology', name)

    def _create_flora_from_json(self, data: dict) -> tuple:
        """Create a flora (plant) from JSON data.

        Args:
            data: Dictionary with flora fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        flora_id = f"flora_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.flora)}"

        # Map flora_type to FloraType enum
        flora_type_str = data.get('flora_type', 'other').lower().replace(' ', '_')
        try:
            flora_type = FloraType(flora_type_str)
        except ValueError:
            flora_type = FloraType.OTHER

        flora = Flora(
            id=flora_id,
            name=name,
            flora_type=flora_type,
            description=data.get('description', ''),
            habitat=data.get('habitat', ''),
            edible=data.get('edible', False),
            medicinal_properties=data.get('medicinal_properties', ''),
            toxicity=data.get('toxicity', ''),
            cultural_significance=data.get('cultural_significance', ''),
        )

        self.current_project.worldbuilding.flora.append(flora)
        print(f"Created flora: {name}")
        return ('flora', name)

    def _create_fauna_from_json(self, data: dict) -> tuple:
        """Create a fauna (animal) from JSON data.

        Args:
            data: Dictionary with fauna fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        fauna_id = f"fauna_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.fauna)}"

        # Map fauna_type to FaunaType enum
        fauna_type_str = data.get('fauna_type', 'other').lower().replace(' ', '_')
        try:
            fauna_type = FaunaType(fauna_type_str)
        except ValueError:
            fauna_type = FaunaType.OTHER

        fauna = Fauna(
            id=fauna_id,
            name=name,
            fauna_type=fauna_type,
            description=data.get('description', ''),
            habitat=data.get('habitat', ''),
            diet=data.get('diet', ''),
            behavior=data.get('behavior', ''),
            danger_level=data.get('danger_level', 0),
            cultural_significance=data.get('cultural_significance', ''),
        )

        self.current_project.worldbuilding.fauna.append(fauna)
        print(f"Created fauna: {name}")
        return ('fauna', name)

    def _create_chapter_from_json(self, data: dict) -> tuple:
        """Create a chapter from JSON data.

        Args:
            data: Dictionary with chapter fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime
        from src.models.project import ChapterPlanning

        title = data.get('title', '').strip()
        if not title:
            return None

        # Generate unique ID and chapter number
        next_number = len(self.current_project.manuscript.chapters) + 1
        chapter_id = f"chapter_{datetime.now().strftime('%Y%m%d%H%M%S')}_{next_number}"

        # Create chapter planning
        planning = ChapterPlanning(
            description=data.get('description', ''),
            pov_character=data.get('pov_character', ''),
        )

        chapter = Chapter(
            id=chapter_id,
            number=next_number,
            title=title,
            content=data.get('content', ''),
            html_content=data.get('content', ''),  # Set same as content initially
            planning=planning,
        )

        self.current_project.manuscript.chapters.append(chapter)
        print(f"Created chapter: {title} (Chapter {next_number})")

        # Refresh manuscript editor to show the new chapter
        if hasattr(self, 'manuscript_editor'):
            self.manuscript_editor.load_manuscript(self.current_project.manuscript)

        return ('chapter', f"{next_number}. {title}")

    def _create_climate_preset_from_json(self, data: dict) -> tuple:
        """Create a climate preset from JSON data.

        Args:
            data: Dictionary with climate preset fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        preset_id = f"climate_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.climate_presets)}"

        # Parse seasons - could be string or list
        seasons = data.get('seasons', [])
        if isinstance(seasons, str):
            seasons = [s.strip() for s in seasons.split(',') if s.strip()]

        # Parse extreme_events - could be string or list
        extreme_events = data.get('extreme_events', [])
        if isinstance(extreme_events, str):
            extreme_events = [e.strip() for e in extreme_events.split(',') if e.strip()]

        climate_preset = ClimatePreset(
            id=preset_id,
            name=name,
            description=data.get('description', ''),
            temperature_range=data.get('temperature_range', None),
            precipitation_pattern=data.get('precipitation_pattern', None),
            seasons=seasons,
            atmospheric_composition=data.get('atmospheric_composition', None),
            weather_patterns=data.get('weather_patterns', ''),
            extreme_events=extreme_events,
        )

        self.current_project.worldbuilding.climate_presets.append(climate_preset)
        print(f"Created climate preset: {name}")
        return ('climate_preset', name)

    def _create_planet_from_json(self, data: dict) -> tuple:
        """Create a planet from JSON data.

        Args:
            data: Dictionary with planet fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        planet_id = f"planet_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.planets)}"

        # Map planet_type to PlanetType enum
        planet_type_str = data.get('planet_type', 'terrestrial').lower().replace(' ', '_')
        try:
            planet_type = PlanetType(planet_type_str)
        except ValueError:
            planet_type = PlanetType.TERRESTRIAL

        planet = Planet(
            id=planet_id,
            name=name,
            planet_type=planet_type,
            description=data.get('description', ''),
            star_system=data.get('star_system', None),
            orbital_period=data.get('orbital_period', None),
            rotation_period=data.get('rotation_period', None),
            atmosphere=data.get('atmosphere', ''),
            population=data.get('population', None),
            dominant_climate=data.get('dominant_climate', None),
        )

        self.current_project.worldbuilding.planets.append(planet)
        print(f"Created planet: {name}")
        return ('planet', name)

    def _create_star_system_from_json(self, data: dict) -> tuple:
        """Create a star system from JSON data.

        Args:
            data: Dictionary with star system fields

        Returns:
            Tuple of (element_type, element_name) or None
        """
        from datetime import datetime

        name = data.get('name', '').strip()
        if not name:
            return None

        # Generate unique ID
        system_id = f"system_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.current_project.worldbuilding.star_systems)}"

        star_system = StarSystem(
            id=system_id,
            name=name,
            system_type=data.get('system_type', 'single'),
            description=data.get('description', ''),
            galaxy=data.get('galaxy', None),
            location=data.get('location', None),
        )

        self.current_project.worldbuilding.star_systems.append(star_system)
        print(f"Created star system: {name}")
        return ('star_system', name)

    def _refresh_project_widgets(self):
        """Refresh UI widgets after creating project elements."""
        if not self.current_project:
            return

        # Refresh characters widget
        self.characters_widget.load_data(self.current_project.characters)

        # Refresh worldbuilding widget
        self.worldbuilding_widget.load_data(self.current_project.worldbuilding)

        # Update characters in image generator
        self.image_generator.set_characters(self.current_project.characters)

        # Update characters in chat widget for POV selection
        self.chat_widget.set_characters(self.current_project.characters)

        # Refresh RAG index with new/updated elements
        if self._rag_initialized and self._rag_system:
            try:
                self._rag_system.rebuild_index()
                print("RAG index refreshed after element creation")
            except Exception as e:
                print(f"Failed to refresh RAG index: {e}")

        # Mark project as modified
        self._on_content_changed()

    def _show_find_dialog(self):
        """Show Find dialog."""
        # Only work when on manuscript tab
        if self.tab_widget.currentIndex() != 0:
            self.statusBar().showMessage("Find is only available in the Manuscript tab", 3000)
            return

        if not self.find_dialog:
            self.find_dialog = FindReplaceDialog(self, replace_mode=False)
            self.find_dialog.find_next.connect(self._on_find_next)

        # Pre-populate with selected text
        selected = self.manuscript_editor.get_selected_text()
        if selected:
            self.find_dialog.set_find_text(selected)

        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()

    def _show_replace_dialog(self):
        """Show Find and Replace dialog."""
        # Only work when on manuscript tab
        if self.tab_widget.currentIndex() != 0:
            self.statusBar().showMessage("Find/Replace is only available in the Manuscript tab", 3000)
            return

        if not self.replace_dialog:
            self.replace_dialog = FindReplaceDialog(self, replace_mode=True)
            self.replace_dialog.find_next.connect(self._on_find_next)
            self.replace_dialog.replace_next.connect(self._on_replace_next)
            self.replace_dialog.replace_all.connect(self._on_replace_all)

        # Pre-populate with selected text
        selected = self.manuscript_editor.get_selected_text()
        if selected:
            self.replace_dialog.set_find_text(selected)

        self.replace_dialog.show()
        self.replace_dialog.raise_()
        self.replace_dialog.activateWindow()

    def _on_find_next(self, text: str, case_sensitive: bool, whole_word: bool):
        """Handle find next from dialog."""
        found = self.manuscript_editor.find_text(text, case_sensitive, whole_word)
        dialog = self.find_dialog or self.replace_dialog
        if dialog:
            if found:
                dialog.set_status("")
            else:
                dialog.set_status(f"'{text}' not found")

    def _on_replace_next(self, find_text: str, replace_text: str,
                         case_sensitive: bool, whole_word: bool):
        """Handle replace from dialog."""
        found = self.manuscript_editor.replace_text(find_text, replace_text, case_sensitive, whole_word)
        if self.replace_dialog:
            if not found:
                self.replace_dialog.set_status(f"'{find_text}' not found")
            else:
                self.replace_dialog.set_status("")

    def _on_replace_all(self, find_text: str, replace_text: str,
                        case_sensitive: bool, whole_word: bool):
        """Handle replace all from dialog."""
        count = self.manuscript_editor.replace_all_text(find_text, replace_text, case_sensitive, whole_word)
        if self.replace_dialog:
            if count == 0:
                self.replace_dialog.set_status(f"'{find_text}' not found")
            else:
                self.replace_dialog.set_status(f"Replaced {count} occurrence(s)")

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            # Save settings persistently
            if self.ai_config.save_settings(self.settings):
                self.statusBar().showMessage("AI settings saved successfully", 3000)
            else:
                QMessageBox.warning(
                    self,
                    "Save Error",
                    "Failed to save AI settings. Check permissions."
                )

    def _export_book_outline(self):
        """Export all chapter plans as a book outline document."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.warning(
                self,
                "No Chapters",
                "No chapters available to export outline."
            )
            return

        # Collect current manuscript data (includes saving current chapter plans)
        self._collect_project_data()

        # Check if there are any chapter plans
        chapters_with_plans = sum(
            1 for ch in self.current_project.manuscript.chapters
            if ch.plan and ch.plan.strip()
        )

        if chapters_with_plans == 0:
            result = QMessageBox.question(
                self,
                "No Chapter Plans",
                "No chapter plans have been written yet.\n\n"
                "Would you like to export an outline template with chapter titles only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        # Get output file path
        default_name = f"{self.current_project.manuscript.title}_Outline.docx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Book Outline",
            default_name,
            "Word Documents (*.docx)"
        )

        if not file_path:
            return

        # Export outline
        exporter = ManuscriptExporter(self.current_project.manuscript)

        try:
            success = exporter.export_outline_to_docx(file_path, include_notes=True)

            if success:
                total_chapters = len(self.current_project.manuscript.chapters)
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Book outline exported successfully!\n\n"
                    f"File: {file_path}\n"
                    f"Total Chapters: {total_chapters}\n"
                    f"Chapters with Plans: {chapters_with_plans}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export outline. Check the console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )

    def _export_manuscript(self, format_type: str):
        """Export manuscript in specified format."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.warning(
                self,
                "No Content",
                "No manuscript content to export."
            )
            return

        # Collect current manuscript data
        self._collect_project_data()

        # Determine file extension and filter
        extensions = {
            "kindle": ("epub", "EPUB Files (*.epub)"),
            "barnes_noble": ("epub", "EPUB Files (*.epub)"),
            "publisher": ("docx", "Word Documents (*.docx)"),
            "docx": ("docx", "Word Documents (*.docx)")
        }

        ext, file_filter = extensions.get(format_type, ("docx", "Word Documents (*.docx)"))

        # Get output file path
        default_name = f"{self.current_project.manuscript.title}.{ext}"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export Manuscript - {format_type.replace('_', ' ').title()}",
            default_name,
            file_filter
        )

        if not file_path:
            return

        # Export manuscript
        exporter = ManuscriptExporter(self.current_project.manuscript)

        try:
            success = False
            if format_type == "kindle":
                success = exporter.export_for_kindle(file_path)
            elif format_type == "barnes_noble":
                success = exporter.export_for_barnes_noble(file_path)
            elif format_type == "publisher":
                success = exporter.export_publisher_ready(file_path)
            elif format_type == "docx":
                success = exporter.export_to_docx(file_path)

            if success:
                stats = exporter.get_manuscript_statistics()
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Manuscript exported successfully!\n\n"
                    f"File: {file_path}\n"
                    f"Chapters: {stats['total_chapters']}\n"
                    f"Words: {stats['total_words']:,}\n"
                    f"Estimated Pages: {stats['estimated_pages']}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export manuscript. Check the console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )

    def _export_llm_context(self):
        """Export worldbuilding, plot, and characters to markdown for LLM context."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Collect current data from all widgets
        self._collect_project_data()

        # Get output file path
        default_name = f"{self.current_project.name}_LLM_Context.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export LLM Context",
            default_name,
            "Markdown Files (*.md);;All Files (*)"
        )

        if file_path:
            try:
                # Export to markdown
                markdown_content = LLMContextExporter.export_to_markdown(
                    self.current_project,
                    file_path
                )

                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"LLM context exported successfully to:\n{file_path}\n\n"
                    f"You can now use this markdown file to provide context to LLMs."
                )
                self.statusBar().showMessage(f"Exported LLM context to {file_path}")

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"An error occurred during export:\n{str(e)}"
                )

    def _export_project_summary(self):
        """Export project as a comprehensive summary with optional AI/ML summarization."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Show export dialog
        dialog = ExportSummaryDialog(self.current_project, self)
        dialog.exec()

    def _show_import_guide(self):
        """Show the import guide dialog with AI prompts."""
        dialog = ImportGuideDialog(self)
        dialog.exec()

    def _show_json_import(self):
        """Show the JSON import dialog."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "Please create or open a project before importing data."
            )
            return

        dialog = JSONImportDialog(self, self.current_project)
        dialog.data_imported.connect(self._on_json_imported)
        dialog.exec()

    def _on_json_imported(self, imported_data: dict):
        """Handle successful JSON import."""
        # Refresh all widgets to show imported data
        self._load_project_into_ui()
        self.statusBar().showMessage("Data imported successfully", 5000)

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Writer Platform",
            "Writer Platform v1.0\n\n"
            "A comprehensive platform for writers to organize books, "
            "short stories, and media.\n\n"
            "Features worldbuilding, character development, story planning, "
            "manuscript editing, AI assistance, and more."
        )

    def _jump_to_annotation(self, chapter_id: str, annotation_id: str):
        """Jump to specific annotation in manuscript editor."""
        # Switch to Write tab
        self.tab_widget.setCurrentWidget(self.manuscript_editor)

        # Find and select the chapter in manuscript editor
        for i in range(self.manuscript_editor.chapter_list.count()):
            item = self.manuscript_editor.chapter_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == chapter_id:
                self.manuscript_editor.chapter_list.setCurrentItem(item)

                # Wait for chapter to load, then jump to annotation
                if self.manuscript_editor.current_chapter_editor:
                    # Find the annotation to get its line number
                    annotation = next(
                        (a for a in self.manuscript_editor.current_chapter_editor.chapter.annotations
                         if a.id == annotation_id),
                        None
                    )
                    if annotation:
                        self.manuscript_editor.current_chapter_editor._jump_to_line(annotation.line_number)
                break

    def _go_to_critique_line(self, number: int):
        """Navigate to a specific sentence or paragraph from critique feedback.

        Args:
            number: The sentence number (positive, 1-indexed) or
                   paragraph number (negative, 1-indexed as -N) from the critique
        """
        import re

        # Switch to Write tab
        self.tab_widget.setCurrentWidget(self.manuscript_editor)

        # Get current chapter editor
        if not self.manuscript_editor.current_chapter_editor:
            return

        editor = self.manuscript_editor.current_chapter_editor.editor
        if not editor:
            return

        # Get the chapter text
        text = editor.toPlainText()
        if not text:
            return

        # Determine mode: positive = sentence, negative = paragraph
        is_paragraph_mode = number < 0
        target_number = abs(number)

        if is_paragraph_mode:
            # Paragraph navigation
            paragraphs = text.split('\n\n')
            paragraphs = [p.strip() for p in paragraphs if p.strip()]

            if target_number < 1 or target_number > len(paragraphs):
                return

            target_text = paragraphs[target_number - 1]

            # Find position of the paragraph
            position = 0
            for i in range(target_number - 1):
                if i < len(paragraphs):
                    found = text.find(paragraphs[i], position)
                    if found >= 0:
                        position = found + len(paragraphs[i])

            position = text.find(target_text, position)
            if position < 0:
                position = 0

            # Select the paragraph
            end_pos = position + len(target_text)
            status_msg = f"Navigated to paragraph {target_number}"
        else:
            # Sentence navigation (original behavior)
            sentences = re.split(r'(?<=[.!?])\s+', text)
            sentences = [s.strip() for s in sentences if s.strip()]

            if target_number < 1 or target_number > len(sentences):
                return

            target_text = sentences[target_number - 1]

            # Find the position of this sentence in the text
            position = 0
            current_sentence = 0
            for match in re.finditer(r'[^.!?]*[.!?]', text):
                sentence_text = match.group().strip()
                if sentence_text:
                    current_sentence += 1
                    if current_sentence == target_number:
                        position = match.start()
                        break

            # If regex approach didn't work, try direct search
            if position == 0 and target_number > 1:
                pos = 0
                for i in range(target_number - 1):
                    if i < len(sentences):
                        found = text.find(sentences[i], pos)
                        if found >= 0:
                            pos = found + len(sentences[i])
                position = text.find(target_text, pos)

            end_pos = position + len(target_text)
            status_msg = f"Navigated to sentence {target_number}"

        # Move cursor and select the text
        cursor = editor.textCursor()
        cursor.setPosition(position)

        if end_pos <= len(text):
            cursor.setPosition(position)
            cursor.setPosition(end_pos, cursor.MoveMode.KeepAnchor)
        else:
            cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)

        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        editor.setFocus()

        # Show a brief status message
        self.statusBar().showMessage(status_msg, 3000)

    def _ask_about_critique_suggestion(self, suggestion_type: str, original_text: str,
                                        suggestion: str, explanation: str):
        """Handle 'Ask About This' from critique — send to Chapter Focus chat."""
        # Make chat visible if hidden/collapsed
        if not self.chat_widget.isVisible():
            self.chat_widget.show()
        if self.chat_widget._collapsed:
            self.chat_widget._toggle_collapse()

        # Switch to Chapter Focus mode
        self.chat_widget.set_mode("chapter_focus")

        # Build a question that asks for deeper understanding + practice
        type_display = suggestion_type.replace('_', ' ').title()
        question = (
            f"The critique flagged this text for a \"{type_display}\" issue:\n\n"
            f"\"{original_text}\"\n\n"
            f"The suggestion was: {suggestion}\n\n"
            f"Can you explain why this is a problem in more depth, show me how "
            f"to fix this specific passage, and give me a short exercise to "
            f"practice this skill?"
        )

        # Inject into input and send
        self.chat_widget.input_field.setText(question)
        self.chat_widget._send_message()

    def _toggle_multi_window_mode(self, checked: bool):
        """Toggle multi-window mode on/off."""
        self.window_manager.set_multi_window_mode(checked)

        if not checked:
            # Merge all tabs back to main window
            self._merge_all_secondary_windows()
            self.statusBar().showMessage("Multi-window mode disabled", 3000)
        else:
            self.statusBar().showMessage(
                "Multi-window mode enabled - Right-click tabs to create new windows",
                5000
            )

    def _merge_all_secondary_windows(self):
        """Merge all secondary windows back to main window."""
        for window in self.window_manager.get_secondary_windows():
            window.close()  # closeEvent will merge tabs back

    def _show_tab_context_menu(self, pos: QPoint):
        """Show context menu for tab operations."""
        tab_bar = self.tab_widget.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index == -1:
            return

        menu = QMenu(self)

        # Only show Create New Window if multi-window mode is enabled
        if self.window_manager.is_multi_window_mode():
            # Don't allow detaching the last tab
            if self.tab_widget.count() > 1:
                detach_action = menu.addAction("Create New Window")
                detach_action.triggered.connect(lambda: self._detach_tab_to_new_window(tab_index))

        if not menu.isEmpty():
            menu.exec(tab_bar.mapToGlobal(pos))

    def _detach_tab_to_new_window(self, tab_index: int):
        """Detach a tab to a new secondary window."""
        if tab_index < 0 or tab_index >= self.tab_widget.count():
            return

        # Don't allow detaching the last tab
        if self.tab_widget.count() <= 1:
            QMessageBox.warning(
                self,
                "Cannot Detach",
                "Cannot detach the last tab from the main window."
            )
            return

        # Get widget and label
        widget = self.tab_widget.widget(tab_index)
        label = self.tab_widget.tabText(tab_index)

        # Remove from main window
        widget.setParent(None)
        self.tab_widget.removeTab(tab_index)

        # Create new secondary window
        project_name = self.current_project.name if self.current_project else "Writer Platform"
        new_window = SecondaryWindow(project_name, self)
        new_window.add_tab(widget, label)
        new_window.tab_merge_requested.connect(self._handle_tab_merge)
        new_window.show()

        self.statusBar().showMessage(f"Created new window with '{label}' tab", 3000)

    def _handle_tab_merge(self, widget: QWidget, label: str):
        """Handle merging a tab back from a secondary window."""
        self.tab_widget.addTab(widget, label)
        self.statusBar().showMessage(f"Merged '{label}' tab back to main window", 3000)

    def closeEvent(self, event):
        """Handle window close event."""
        if self.current_project and not self._confirm_unsaved_changes():
            event.ignore()
        else:
            # Hide tray icon before closing
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
            # Close all secondary windows
            self.window_manager.close_all_secondary_windows()
            event.accept()
