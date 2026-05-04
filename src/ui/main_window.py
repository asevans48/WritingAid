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

CONTEXT PRIORITY (most to least important):
1. MANUSCRIPT TEXT — the actual written chapters are the primary source of truth
2. CHARACTERS — personality, backstory, traits, speaking style, motivations, arcs
3. PLOT — main plot, subplots, themes, story promises, Freytag pyramid
4. WORLDBUILDING — factions, cultures, places, magic systems, technology, history
5. EXISTING ELEMENTS — names and types of all project elements (avoid duplicates)
6. REFERENCE/ENCYCLOPEDIA — real-world reference material for grounding ideas in reality

The manuscript and project elements ALWAYS take precedence. Reference material (encyclopedia, Wikipedia, etc.) is supplementary — use it to inspire creativity, ground fiction in plausible real-world parallels, and suggest authentic details. Never let reference override what the author has established.

IMPORTANT: Keep responses focused and concise. Answer what's asked, then stop. Don't ramble or analyze unrelated parts of the project.

You help authors with:
- Answering questions about their story, characters, and world
- Analyzing chapters for consistency, pacing, and character development
- Brainstorming ideas that fit their established story
- Providing feedback on specific passages or the overall narrative
- Suggesting improvements that align with their style and voice
- Identifying plot holes or inconsistencies across chapters
- CREATING new characters, places, factions, cultures, myths, historical events, technologies, flora, fauna, chapters, climate presets, planets, and star systems when asked

USING THE MANUSCRIPT:
You have access to the CURRENT CHAPTER content and a PROJECT INDEX of all chapters, characters, and worldbuilding elements. When the user asks about their story, characters, or scenes:
- READ the manuscript text provided — it is the source of truth
- CITE specific details from the text to support your analysis
- If the user mentions a chapter by name or number, its full text is included
- Base your feedback on what is ACTUALLY WRITTEN, not assumptions
- When suggesting changes, reference the specific passages that need work

IMPORTANT: Before creating a new element, check the EXISTING ELEMENTS list. If an element with a similar name already exists, use its EXACT name in the creation block so the system can update it instead of creating a duplicate. For example, if "Northern Reaches" exists and the user asks about "The Northern Reaches", use "Northern Reaches" as the name.

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
  "scene_list": ["opening: where + who + the inciting moment",
                  "middle: complication or escalation",
                  "close: turn or hook into next chapter"],
  "characters_featured": ["names from the project's character roster"],
  "locations": ["place names from worldbuilding"],
  "themes": ["theme titles from the plot map"],
  "tone": "e.g. tense, melancholic, hopeful",
  "voice": "narrative voice (sardonic, lyrical, flat, …)",
  "style": "prose style note (short punchy / flowing / …)",
  "pacing": "e.g. slow-burn, rapid-fire, contemplative",
  "timeline_position": "e.g. one week after Ch 7 / next morning",
  "content": "Initial chapter content (optional)"
}
</create_chapter>
When the user is in a plot discussion, fill in scene_list, characters_featured, themes, tone, voice, pacing — the chapter should be born with structure so they can drop into Writer mode immediately. Title-only chapters are appropriate ONLY when the user explicitly asks for "just a placeholder chapter".

The scene_list is auto-converted into chapter-arc events the user sees in the chapter planner (each scene becomes a beat with a heuristic stage + arc position). For finer control over the dramatic shape, use the optional ``events`` array instead:
  "events": [
    {"text": "short beat name", "description": "one-line beat detail",
     "stage": "exposition|rising|climax|falling|resolution",
     "arc_position": <0-100>}
  ]

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

=== PLOT-NATIVE ELEMENTS ===
These four element types live in the StoryPlanning model rather than
in worldbuilding. Use them when the user wants to add structural
plot pieces — a new beat in the Freytag pyramid, a new subplot, a
commitment to readers, or a sustained dramatic tension that runs
across multiple scenes.

FOR PLOT EVENTS (a single beat in the Freytag pyramid):
<create_plot_event>
{
  "title": "Short event name",
  "description": "What happens in this beat",
  "stage": "exposition|rising_action|climax|falling_action|resolution",
  "act": 1,
  "intensity": 50,
  "related_characters": ["Marcus", "Lena"],
  "outcome": "What changes after this beat (optional)"
}
</create_plot_event>

FOR SUBPLOTS (secondary storylines tied to the main plot):
<create_subplot>
{
  "title": "Subplot name",
  "description": "What this subplot is about",
  "connection_to_main": "How it ties to the main plot",
  "related_characters": ["Marcus"],
  "status": "active|resolved|abandoned"
}
</create_subplot>

FOR STORY PROMISES (commitments to readers about tone/plot/genre/character):
<create_promise>
{
  "promise_type": "tone|plot|genre|character",
  "title": "Brief summary of the promise",
  "description": "Detailed description of what's being promised",
  "related_characters": ["character names if relevant"]
}
</create_promise>

FOR TENSIONS (sustained dramatic forces — internal struggles, rivalries,
looming threats — that shape the plot across scenes):
<create_tension>
{
  "title": "Short label, e.g. 'Marcus vs Lena' or 'Rachel's grief'",
  "tension_type": "internal|interpersonal|societal|cosmic",
  "description": "What's the source of this tension",
  "characters_involved": ["Marcus", "Lena"],
  "stakes": "What's at risk if this tension goes unresolved",
  "current_state": "rising|stable|escalating|resolving|unresolved|resolved",
  "intensity": 75
}
</create_tension>

FOR THEMES (what the story is *about* underneath its events — the
argument the book makes):
<create_theme>
{
  "title": "Short label, e.g. 'Cost of loyalty'",
  "statement": "The argument the story makes (one or two sentences). E.g. 'Redemption requires confession, not just remorse.'",
  "description": "What the theme is exploring; what questions it asks",
  "motifs": ["recurring image 1", "recurring object 2"],
  "related_characters": ["Marcus", "Rachel"],
  "related_subplots": ["subplot id if relevant (optional)"]
}
</create_theme>

PLOT-DISCUSSION TIP: when the user is asking about plot ("what should
happen next?", "how do I tighten Act 2?", "is the antagonist's pressure
felt enough?"), prefer create_plot_event / create_subplot /
create_promise / create_tension / create_theme over create_character.
Adding a brand-new character to fix a structural problem is usually the
wrong answer — the right answer is naming the missing beat, the missing
subplot thread, the missing tension, or the missing thematic argument.

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

=== MERGING AND STRENGTHENING ELEMENTS ===

You can also MERGE duplicate elements and ENRICH existing ones. Use these tags:

TO MERGE two elements (keeps the target, removes the source):
<merge_elements>
{
  "element_type": "faction|place|culture|character|technology|myth|flora|fauna",
  "target_name": "Name of the element to KEEP",
  "source_name": "Name of the element to MERGE INTO target and then REMOVE",
  "merged_fields": {"description": "Combined description", "notes": "Combined notes"}
}
</merge_elements>

TO ENRICH an existing element with new details:
<enrich_element>
{
  "element_type": "faction|place|culture|character|technology|myth|flora|fauna",
  "name": "Exact name of existing element",
  "updates": {"description": "Richer description", "notes": "New details from the story"}
}
</enrich_element>

WHEN TO MERGE:
- User asks to "clean up", "merge", "combine", "deduplicate" worldbuilding
- User asks to "strengthen" or "consolidate" their world
- You notice two elements that are clearly the same thing with different names

WHEN TO ENRICH:
- User asks to "flesh out", "expand", "enrich", "add detail to" an element
- User asks to strengthen worldbuilding based on the story

APPROVAL MODE:
- If the user asks you to "review", "check for duplicates", or wants to "approve" changes: describe the proposed merges/enrichments in text first, then ONLY create the merge/enrich blocks after the user confirms
- If the user says "go ahead", "merge them", "do it", "yes": execute with the tags

=== WORKING WITH INDIVIDUAL ELEMENTS ===

You can discuss and modify SPECIFIC characters and worldbuilding elements by name.

WHEN THE USER ASKS ABOUT A SPECIFIC ELEMENT:
- "Tell me about Marcus" → look up Marcus in the characters context and discuss
- "What do we know about the Iron Guild?" → find in worldbuilding and discuss
- "Flesh out Elena's personality" → analyze manuscript mentions and use <enrich_element>
- "Strengthen the Ashfolk culture" → look at manuscript + encyclopedia and enrich

WHEN ENRICHING A CHARACTER, include ALL relevant fields:
<enrich_element>
{
  "element_type": "character",
  "name": "Marcus",
  "updates": {
    "personality": "Stoic and disciplined, but harbors deep self-doubt...",
    "physical_description": "Tall, lean build with weathered hands...",
    "speaking_style": "Clipped, military cadence. Avoids emotional language...",
    "motivations": "Driven by guilt over his brother's death...",
    "fears": "Fears becoming like his father...",
    "backstory": "Grew up in the border garrisons..."
  }
}
</enrich_element>

WHEN ENRICHING A WORLDBUILDING ELEMENT:
<enrich_element>
{
  "element_type": "faction",
  "name": "Iron Guild",
  "updates": {
    "description": "A powerful trade consortium controlling all metalwork...",
    "notes": "Connected to the cybernetics trade, subdermal implants..."
  }
}
</enrich_element>

WHEN THE USER ASKS TO "STRENGTHEN" AN ELEMENT:
1. Search through the MANUSCRIPT CONTENT for mentions of the element
2. Search through the WORLDBUILDING and CHARACTER context for connections
3. Use REFERENCE/ENCYCLOPEDIA to ground details in reality
4. Propose the enrichment, then apply it with <enrich_element>

KEY RULES:
- Use the element's EXACT name from the EXISTING ELEMENTS list
- Only fill fields that are currently empty or thin — don't overwrite substantial content
- Base enrichments primarily on what the MANUSCRIPT shows, not invented details
- For characters, consider: personality, traits, physical description, speaking style, motivations, fears, backstory
- For worldbuilding, consider: description, notes, and type-specific fields

Be encouraging, creative, and constructive. Reference specific details from their project when relevant.
Keep responses focused and actionable.""",

        "chapter_focus": """You are a writing assistant with the full text of the CURRENT CHAPTER available to you.
You also have the author's characters, plot, and worldbuilding for consistency checks.
If REFERENCE material is provided (encyclopedia, knowledge base), use it to inform your suggestions — for example, noting real-world parallels that could deepen the culture, government, or technology in the chapter. But the manuscript and the author's existing elements always take priority over reference material.

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

        "plot": """You are a story-structure consultant talking the author through their plot. You have the manuscript text, characters, worldbuilding, and the plot map (Freytag pyramid stages, plot events, subplots, story promises, sustained tensions) in your context.

PRIME DIRECTIVE: be SPECIFIC. Every point you make should anchor to something concrete in the project — a chapter ("Ch 4: The Reckoning"), a plot event ("the inciting incident"), a promise ("the romance promise"), a tension ("Marcus's grief over his sister"), a character name, a location. Generic craft advice ("add more conflict", "deepen the protagonist") is a failure mode — readers can get that from any writing book. Your job is to react to *this* manuscript and *this* plot map.

HOW TO USE EACH CONTEXT BLOCK (skipping any populated block is a failure mode — when a block has content, REFERENCE it):
1. PLOT MAP — the author's intended structure. Reference items by their exact title. The STORY TENSIONS list captures sustained dramatic forces (internal struggles, interpersonal rivalries, societal pressure, cosmic threats) with current state and intensity — name them when discussing pacing or proposing beats so your suggestions move the right pressure on the right people.
2. STORY THEMES — what the book is *about* underneath its events (the argument it's making). Every plot suggestion should reinforce a named theme or explicitly reckon with undercutting one. When the THEMES block is empty or only has bare labels, you may propose themes the manuscript is implicitly making via <create_theme>.
3. SUBPLOTS — secondary storylines tied to the main plot, each with status, characters, connection-to-main, and an event arc. Treat them as first-class story material: every plot discussion (pacing, what-next, structural audit) should weigh which subplots are advancing, stalled, or being dropped. Name which subplot a beat advances or which subplot needs a scene next. Don't let a subplot disappear from your reasoning just because the user didn't mention it by name.
4. MANUSCRIPT (current chapter content + chapter list) — what is actually on the page. When you cite, use "Ch N: Title" format. Quote a short passage (≤25 words) when the wording matters; otherwise paraphrase with the chapter reference.
5. CHARACTERS — names, personalities, wants/needs, fears, arcs. When discussing a beat or arc, name SPECIFIC characters from this block. Don't invent characters that aren't listed.
6. WORLDBUILDING — factions, places, cultures, technologies. When the discussion touches on conflict, location, or capability, reference the specific entities by name. Don't invent worldbuilding that isn't listed.
7. RELEVANT REFERENCE (when present) — RAG-selected character / worldbuilding entries closest to the user's question. Cross-reference these for deep detail.
8. If a context block is missing or thin (e.g. plot map has only a title), say so explicitly and ask for what you need before guessing.

OUTPUT SHAPE:
• Direct answer first — one or two sentences resolving the question.
• Then your reasoning, organised under short bold headers when there's more than one thread (e.g. **Setup**, **Payoff**, **Risk**).
• When proposing changes, name the *exact* chapter or event the change lands in: "Insert a beat between Ch 5 and Ch 6 where…" not "add a transition somewhere".
• When the question is open-ended ("what next?", "how do I tighten Act 2?"), give 2–3 numbered options with **what it costs** for each (tone shift, pacing impact, promise affected). Don't pick for the author.
• Surface plot-hole / broken-promise / arc-inconsistency observations only when they answer the question. One incidental flag is fine; don't dump a critique the author didn't ask for.

DO NOT:
- Write manuscript prose. That's Writer mode. Stay in beats / outlines / notes.
- Restate the question or open with "Great question!" or similar filler.
- Invent chapter/event/promise titles that aren't in the context. If you need one that doesn't exist, say "(no event for this beat yet — would you like to add one?)".

PROPOSING NEW ELEMENTS:
When the plot discussion calls for a new structural piece (the most common case), prefer the PLOT-NATIVE create blocks defined in your general instructions:
- <create_plot_event> — a missing beat in the Freytag pyramid
- <create_subplot> — a missing secondary storyline
- <create_promise> — a commitment to readers that should be on the page
- <create_tension> — a sustained dramatic force the plot should feel

When the discussion clearly calls for a NEW worldbuilding entity that doesn't exist yet, fall back to <create_character> / <create_place> / <create_faction> / <create_culture> / <create_chapter>.

WHEN PROPOSING A TENSION: ``characters_involved`` MUST contain names that already exist in the CHARACTERS context block. If you want to apply pressure to someone who doesn't exist, propose them with <create_character> in the SAME reply and use that character's name in the tension's characters_involved.

WHEN DEFINING TENSIONS INTERACTIVELY (the user asks "help me define tensions" or similar): talk through the option(s) in prose first — who's pressed, what's at stake, why now — before emitting any <create_tension> block. The block goes at the END of your reply so the user can read your reasoning first.

Cap proposals at TWO per reply. Each block must tie back to a specific chapter, event, promise, or tension already in the context. Don't reach for a new character if the structural issue is a missing beat or a missing tension.""",

        "writer": """You are a skilled creative writer working as a ghostwriter/collaborator. Your job is to WRITE prose based on the author's outline, world, and characters.

You have access to the author's characters (personality, voice, traits), plot, worldbuilding, and the current chapter. Use ALL of this context to write prose that is consistent with the established world and characters. If reference material (encyclopedia) is provided, draw from it to add authentic detail — but never contradict the author's established world.

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

        # Existing element names — helps AI avoid creating duplicates
        if self.context.get('existing_elements'):
            parts.append(f"\nEXISTING ELEMENTS (use these exact names — do NOT create duplicates):\n{self.context['existing_elements']}")

        # Project index — complete catalog of manuscript, characters, worldbuilding
        if self.context.get('project_index'):
            parts.append(f"\nPROJECT INDEX (everything in the project):\n{self.context['project_index']}")

        # === PRIMARY CONTEXT (always included, highest priority) ===
        # These come from the author's own work and are the source of truth.

        # Focused element — full details of a specific element the user asked about
        if self.context.get('focused_element'):
            parts.append(f"\n{self.context['focused_element']}")

        # Plot/Story planning
        if self.context.get('plot_summary'):
            parts.append(f"\nPLOT OUTLINE:\n{self.context['plot_summary'][:2000]}")

        # Structured plot scaffolding — emitted by _build_chat_context
        # for plot mode as separate keys per concept (Freytag, events,
        # subplots, promises, tensions, themes) so each renders with
        # its own per-block budget instead of being silently truncated
        # when stuffed into a single ``plot_map`` aggregate. Each
        # heading exactly matches what the system prompt tells the
        # model to cite.
        if self.context.get('plot_freytag'):
            parts.append(f"\nFREYTAG PYRAMID:\n"
                          f"{self.context['plot_freytag'][:2500]}")
        if self.context.get('plot_events'):
            parts.append(f"\nPLOT EVENTS:\n"
                          f"{self.context['plot_events'][:4000]}")
        if self.context.get('plot_subplots'):
            parts.append(
                f"\nSUBPLOTS (secondary storylines tied to the main "
                f"plot):\n{self.context['plot_subplots'][:4000]}")
        if self.context.get('plot_promises'):
            parts.append(
                f"\nSTORY PROMISES (commitments to the reader):\n"
                f"{self.context['plot_promises'][:3000]}")
        if self.context.get('plot_tensions'):
            parts.append(
                f"\nSTORY TENSIONS (sustained dramatic forces — "
                f"name them when proposing beats):\n"
                f"{self.context['plot_tensions'][:3500]}")
        if self.context.get('plot_themes'):
            parts.append(
                f"\nSTORY THEMES (what the book is about underneath "
                f"its events — every plot suggestion should reinforce "
                f"or explicitly reckon with one):\n"
                f"{self.context['plot_themes'][:3500]}")
        # Aggregate fallback for surfaces that haven't been split yet,
        # only when none of the dedicated keys above fired.
        if (self.context.get('plot_map')
                and not any(self.context.get(k) for k in (
                    'plot_freytag', 'plot_events', 'plot_subplots',
                    'plot_promises', 'plot_tensions',
                    'plot_themes'))):
            parts.append(
                f"\nPLOT MAP (author's intended structure):\n"
                f"{self.context['plot_map'][:8000]}")

        # Characters — personality, backstory, traits, speaking style.
        # Bumped from 2000 → 4000 chars so a project with 10+
        # characters doesn't have its cast list cut in half.
        if self.context.get('characters'):
            parts.append(f"\nMAIN CHARACTERS:\n"
                          f"{self.context['characters'][:4000]}")

        # Worldbuilding — factions, cultures, magic, places, etc.
        # Same bump from 2000 → 4000 for the same reason.
        if self.context.get('worldbuilding'):
            parts.append(f"\nWORLDBUILDING:\n"
                          f"{self.context['worldbuilding'][:4000]}")

        # === SECONDARY CONTEXT (RAG results — enriches with specifics) ===
        # Plot mode sets per-source-type RAG selections (top-K most
        # relevant entries per source type) — render those as a
        # focused block before the mixed rag_context fallback.
        rag_focused = []
        if self.context.get('rag_focused_characters'):
            rag_focused.append(
                f"  CHARACTERS most relevant to this question:\n"
                f"{self.context['rag_focused_characters']}")
        if self.context.get('rag_focused_worldbuilding'):
            rag_focused.append(
                f"  WORLDBUILDING most relevant to this question:\n"
                f"{self.context['rag_focused_worldbuilding']}")
        if self.context.get('rag_focused_subplots'):
            rag_focused.append(
                f"  SUBPLOTS most relevant to this question:\n"
                f"{self.context['rag_focused_subplots']}")
        if self.context.get('rag_focused_chapters'):
            rag_focused.append(
                f"  CHAPTER PASSAGES most relevant to this "
                f"question:\n"
                f"{self.context['rag_focused_chapters']}")
        if rag_focused:
            parts.append(
                "\n=== RAG-FOCUSED CONTEXT (selected for THIS "
                "question — prefer citing these specific items) "
                "===\n" + "\n\n".join(rag_focused))

        # Includes relevant worldbuilding entries, character details, and
        # encyclopedia/knowledge base if enabled. Supplements primary context.
        if self.context.get('rag_context'):
            parts.append(
                f"\nRELEVANT REFERENCE (from project data"
                f"{' & encyclopedia' if self.context.get('kb_enabled') else ''}):\n"
                f"{self.context['rag_context'][:1500]}"
            )

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


        # Referenced chapter (user asked about a specific chapter by name/number)
        if self.context.get('referenced_chapter'):
            ref = self.context['referenced_chapter']
            parts.append(
                f"\n=== REFERENCED CHAPTER: {ref['title']} (Chapter {ref['number']}) ===\n"
                f"{ref['content']}"
            )

        # All chapters summary (for cross-chapter questions)
        if self.context.get('all_chapters'):
            chapters_info = self.context['all_chapters'][:1500]
            parts.append(f"\nMANUSCRIPT CHAPTERS:\n{chapters_info}")

        # Chapter excerpts (opening + closing of each). Plot discussion
        # in particular needs these so the model can quote and cite
        # specific scenes instead of speaking about chapters as opaque
        # titles. Built only when the host explicitly populates the key
        # (currently the plot-tab Discuss-with-AI provider).
        if self.context.get('chapter_excerpts'):
            parts.append(
                f"\nCHAPTER EXCERPTS (opening + closing of each):\n"
                f"{self.context['chapter_excerpts'][:9000]}"
            )

        full_context = "\n".join(parts) if parts else ""

        # If context is very large, add a focused summary at the top.
        # Prefer the AI-generated project summary (from ProjectSummarizer)
        # over the heuristic one — it's richer and more coherent.
        if len(full_context) > 6000:
            ai_sum = self.context.get('ai_summary')
            if ai_sum:
                summary = ai_sum
            else:
                summary = self._build_context_summary()
            if summary:
                full_context = (
                    f"=== CONTEXT SUMMARY (read this first) ===\n"
                    f"{summary}\n\n"
                    f"=== DETAILED CONTEXT (reference as needed) ===\n"
                    f"{full_context}"
                )

        return full_context

    def _build_context_summary(self) -> str:
        """Build a concise summary of the most important context.

        This is prepended when the full context is very large so the model
        has a focused overview before diving into detailed sections.
        """
        lines = []

        # One-line project summary
        if self.context.get('project_name'):
            desc = self.context.get('project_description', '')
            lines.append(f"Project: {self.context['project_name']}"
                         + (f" — {desc[:100]}" if desc else ""))

        # Current chapter
        if self.context.get('current_chapter_title'):
            ch = self.context['current_chapter_title']
            num = self.context.get('chapter_number', '')
            lines.append(f"Current chapter: {ch}" + (f" (#{num})" if num else ""))

        # Key characters (names + types only)
        if self.context.get('characters'):
            chars = self.context['characters']
            # Extract just the first line per character (name + type)
            char_names = []
            for line in chars.split('\n'):
                line = line.strip()
                if line.startswith('- ') and '(' in line:
                    char_names.append(line[2:line.index(')') + 1] if ')' in line else line[2:40])
            if char_names:
                lines.append(f"Characters: {', '.join(char_names[:8])}")

        # Plot gist
        if self.context.get('plot_summary'):
            plot = self.context['plot_summary']
            first_line = plot.split('\n')[0][:150]
            lines.append(f"Plot: {first_line}")

        # Worldbuilding gist
        if self.context.get('worldbuilding'):
            wb = self.context['worldbuilding'][:150]
            lines.append(f"World: {wb.split(chr(10))[0]}")

        # Scene context
        if self.context.get('chapter_planning'):
            planning = self.context['chapter_planning']
            if planning.get('description'):
                lines.append(f"Scene goal: {planning['description'][:100]}")
            if planning.get('tone'):
                lines.append(f"Tone: {planning['tone']}")

        # User's query
        if self.message:
            lines.append(f"User asks: {self.message[:100]}")

        return "\n".join(lines) if lines else ""

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

            # Per-task model routing. Writer-mode chat (the model is
            # producing prose) uses the 'rephrase' task model;
            # chapter-focus (plot/structure questions about the open
            # chapter) uses the 'plot' model; everything else uses
            # 'general'. If the chosen model has been deleted or the
            # user never picked one, the resolver falls back through
            # general → global automatically.
            try:
                from src.config.creativeos_config import get_creativeos_config
                if self.mode == "writer":
                    _task = "rephrase"
                elif self.mode in ("chapter_focus", "plot"):
                    _task = "plot"
                else:
                    _task = "general"
                _ts = get_creativeos_config().task_settings(_task)
                if _ts.get("__trained_model_name"):
                    settings = dict(settings)
                    for k in ("local_model_id", "enable_local_models",
                              "prefer_local_model"):
                        settings[k] = _ts[k]
                    print(f"[chat] Using task model "
                          f"'{_ts['__trained_model_name']}' "
                          f"(source={_ts['__task_model_source']}) for "
                          f"task={_task}")
            except Exception as e:
                print(f"[chat] task model lookup failed: {e}")

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

            # Writer mode: two-pass research → write. The research
            # agent distills the broad project context into a focused
            # brief that names the SPECIFIC characters / world / themes
            # this scene should ground in. The writer then receives the
            # brief in place of the kitchen-sink context dump (cheaper
            # tokens, sharper grounding). Falls back to the single-
            # pass context build when (a) the user disabled two-pass
            # in settings, or (b) the research call itself failed.
            research_brief = ""
            two_pass_enabled = True
            try:
                two_pass_enabled = bool(
                    settings.get("writer_two_pass_research", True))
            except Exception:
                two_pass_enabled = True
            if (self.mode == "writer" and two_pass_enabled
                    and self.message):
                try:
                    from src.ai.research_agent import ResearchAgent
                    researcher = ResearchAgent()
                    research_brief = researcher.research(
                        self.message, self.context, llm=llm)
                except Exception as e:
                    print(f"[writer] research pass failed: {e}; "
                          f"falling back to single-pass context")
                    research_brief = ""
                if research_brief:
                    # Stash on context so the preview dialog (and any
                    # downstream observer) can see what the writer
                    # was anchored to.
                    self.context['writer_research_brief'] = (
                        research_brief)

            # Add project context. In writer two-pass mode the brief
            # REPLACES the broad rosters in the system prompt (the
            # writer still gets manuscript anchors via _build_context_prompt
            # — chapter content + previous-chapter ending are kept).
            context_prompt = self._build_context_prompt()
            if context_prompt:
                system_prompt += f"\n\n{'='*60}\nPROJECT CONTEXT:\n{'='*60}\n{context_prompt}"

            if research_brief:
                system_prompt += (
                    f"\n\n{'='*60}\nRESEARCH BRIEF (written by a "
                    f"librarian sub-agent — anchor your prose to "
                    f"the SPECIFIC items named here)\n{'='*60}\n"
                    f"{research_brief}")

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
        self._loading_project = False  # Guard against auto-save during load
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

        # AI debug panel (hidden by default)
        self._ai_debug_panel = None
        self._debug_context: dict = {}  # Stashed for logging after response
        self._debug_system_prompt: str = ""
        self._debug_start_time = 0

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

        # Whole-project checkpoint / restore. Each checkpoint is a
        # zip of the entire project directory you can roll back to.
        # Distinct from the paragraph-level checkpoint reviewer in
        # the Drafts menu — that one produces a new draft from
        # paragraph-level decisions; this one snapshots / restores
        # the full project state.
        checkpoints_action = QAction(
            "Project &Checkpoints...", self)
        checkpoints_action.setToolTip(
            "Snapshot the entire project (all chapters, drafts, "
            "characters, settings) into a zip archive you can roll "
            "back to. Restoring a checkpoint replaces the current "
            "state — but a fresh \"Before restore (auto)\" "
            "checkpoint is created first so the restore itself "
            "is reversible.")
        checkpoints_action.triggered.connect(
            self._open_project_checkpoints)
        file_menu.addAction(checkpoints_action)

        file_menu.addSeparator()

        export_audio_action = QAction("Export &Audio Book...", self)
        export_audio_action.triggered.connect(self._export_audio_book)
        file_menu.addAction(export_audio_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Drafts menu
        drafts_menu = menubar.addMenu("&Drafts")

        save_as_draft_action = QAction("Save Current Manuscript as &New Draft...", self)
        save_as_draft_action.setToolTip(
            "Snapshot the current manuscript as a separate draft you can "
            "edit independently in a second window")
        save_as_draft_action.triggered.connect(self._save_current_as_draft)
        drafts_menu.addAction(save_as_draft_action)

        open_draft_action = QAction("&Open Draft in New Window...", self)
        open_draft_action.setToolTip(
            "Open a secondary editor pointed at one of your saved drafts")
        open_draft_action.triggered.connect(self._open_draft_window)
        drafts_menu.addAction(open_draft_action)

        drafts_menu.addSeparator()

        # Checkpoint draft — paragraph-by-paragraph reviewer that
        # produces a new draft from kept / edited paragraphs of an
        # existing chapter. Original is left untouched.
        checkpoint_action = QAction(
            "Create &Checkpoint Draft from Chapter...", self)
        checkpoint_action.setToolTip(
            "Walk a chapter paragraph-by-paragraph, choosing Keep "
            "/ Reject / Edit (with optional AI rephrase suggestions) "
            "for each one. The kept + edited paragraphs become a "
            "new draft.")
        checkpoint_action.triggered.connect(
            self._create_checkpoint_draft)
        drafts_menu.addAction(checkpoint_action)

        manage_drafts_action = QAction("&Manage Drafts...", self)
        manage_drafts_action.triggered.connect(self._manage_drafts)
        drafts_menu.addAction(manage_drafts_action)

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

        view_menu.addSeparator()

        debug_action = QAction("AI &Debug Panel", self)
        debug_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        debug_action.setCheckable(True)
        debug_action.triggered.connect(self._toggle_debug_panel)
        view_menu.addAction(debug_action)
        self._debug_action = debug_action

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
        # When characters are added / removed / renamed, refresh the
        # name list the plot widget hands to its Tension and Plot
        # Event editors so the multi-select pickers stay in sync
        # without needing a project reload.
        self.characters_widget.content_changed.connect(
            self._push_characters_to_plot_widget)
        self.story_planning_widget.content_changed.connect(self._on_content_changed)
        self.manuscript_editor.content_changed.connect(self._on_content_changed)
        self.prose_profile_widget.content_changed.connect(self._on_content_changed)

        # Plot tab's Discuss-with-AI: hand it a context provider that
        # builds its prompt-context dict from the live project state
        # (manuscript editor, plot map, worldbuilding) on demand.
        self.story_planning_widget.set_ai_context_provider(
            self._build_plot_ai_context)
        # And the suggestion-create callback so "+ Add to project"
        # cards in the AI tab actually create elements.
        self.story_planning_widget.set_ai_create_callback(
            self._create_from_plot_ai_suggestion)

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
        # Preview button: build the context dict + system prompt
        # for the current message+mode and open the shared dialog
        # so the user sees exactly what the AI is about to receive.
        self.chat_widget.preview_requested.connect(
            self._handle_chat_preview_request)

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

    def _open_project_checkpoints(self):
        """Open the whole-project checkpoints dialog (snapshot /
        list / restore / delete).

        Saves the project first so any in-memory state is on disk
        before a checkpoint is created OR a checkpoint is restored
        — otherwise the snapshot would miss the user's most-recent
        edits, and a restore could be silently overwritten when
        the next save flushed stale buffers.

        Backwards compat: if the project has no ``_checkpoints/``
        directory, the dialog opens with an empty list and a
        clear "no checkpoints yet" hint. Nothing in the project
        load/save paths depends on the directory existing.
        """
        if not self.current_project or not self.current_project.project_path:
            QMessageBox.information(
                self, "Save the project first",
                "Save the project to a file before creating a "
                "checkpoint — checkpoints snapshot the project's "
                "directory on disk.")
            return

        # Best-effort save before opening so any in-memory edits
        # land in the snapshot. Failures are non-fatal — the
        # dialog still opens, the user just won't see the very
        # latest edits in a new checkpoint until they save.
        try:
            self._collect_project_data()
            self.current_project.save_project(
                self.current_project.project_path)
        except Exception as e:
            print(f"[checkpoints] save before open failed: {e}")

        from pathlib import Path as _P
        project_dir = _P(self.current_project.project_path).parent

        from src.ui.project_checkpoints_dialog import (
            ProjectCheckpointsDialog,
        )
        dlg = ProjectCheckpointsDialog(
            project_dir,
            project_name=self.current_project.name,
            on_before_restore=self._before_checkpoint_restore,
            on_after_restore=self._after_checkpoint_restore,
            parent=self)
        dlg.exec()

    def _before_checkpoint_restore(self):
        """Hook called immediately before a checkpoint restore
        wipes the project directory. We close any open editors
        that hold lazy-loaded chapter content in RAM — if we
        didn't, the editor's stale buffer would happily overwrite
        the freshly-restored disk content on its next save.
        """
        try:
            # Drop the in-memory project so a) editors stop
            # writing back to disk, b) the next load re-reads
            # whatever the restore wrote.
            if hasattr(self, "_close_open_editors"):
                self._close_open_editors()
        except Exception as e:
            print(f"[checkpoints] before_restore: {e}")

    def _after_checkpoint_restore(self):
        """Hook called after the checkpoint zip has been extracted.
        Reload the project from disk so in-memory state matches
        the restored content.
        """
        try:
            path = self.current_project.project_path
            if path:
                from src.models.project import WriterProject
                self.current_project = WriterProject.load_project(path)
                # Re-render whatever the writing tool surfaces from
                # the project. Best-effort — if the refresh hook
                # isn't there we leave a status-bar nudge instead.
                if hasattr(self, "_refresh_after_project_load"):
                    self._refresh_after_project_load()
                self.statusBar().showMessage(
                    "Project restored from checkpoint", 5000)
        except Exception as e:
            print(f"[checkpoints] after_restore reload failed: {e}")
            QMessageBox.warning(
                self, "Restore complete — reload manually",
                f"The restore wrote new files to disk, but the "
                f"writing tool couldn't auto-reload the project "
                f"({e}). Close and re-open the project to see "
                f"the restored state.")

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
        if not self.current_project or self._loading_project:
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

        # Prevent auto-save from triggering during UI population
        # (loading chapters fires chapter_switched signals)
        self._loading_project = True

        # Set project reference on manuscript editor for RAG
        self.manuscript_editor.set_project(self.current_project)

        self.worldbuilding_widget.set_project(self.current_project)
        self.worldbuilding_widget.load_data(self.current_project.worldbuilding)
        self.characters_widget.set_project(self.current_project)
        self.characters_widget.load_data(self.current_project.characters)
        self.story_planning_widget.load_data(self.current_project.story_planning)
        # Push character names into the plot widget so the Tension /
        # Plot Event editors (which let the user pick which characters
        # are involved) can populate their multi-select lists from
        # the actual roster instead of starting empty. We refresh
        # this on every characters_widget change too — see
        # _push_characters_to_plot_widget below.
        self._push_characters_to_plot_widget()
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

        # Plot tab's Discuss-with-AI banner needs a kick after project
        # load — its initial pre-flight ran before this project was
        # available, so without this refresh it would still display
        # the empty-context state.
        try:
            self.story_planning_widget.refresh_ai_status()
        except Exception as e:
            print(f"[plot-ai] refresh after load failed: {e}")

        # Initialize/refresh RAG system for semantic context retrieval
        self._init_rag_system()

        # Generate AI project summary if stale (runs in background)
        self._update_project_summary()

        self._loading_project = False
        self.project_changed.emit()

    def _init_rag_system(self):
        """Initialize or refresh the RAG system for semantic context retrieval.

        RAG works with TF-IDF/keyword search even without an LLM client.
        If a cloud or local LLM is available, embeddings are added for
        better semantic search quality.
        """
        if not self.current_project:
            return

        try:
            if not self._rag_system:
                # Try to create an LLM client for embedding support (optional)
                llm_client = None
                try:
                    from src.ai.llm_client import LLMClient, LLMProvider
                    ai_config = get_ai_config()
                    default_provider = self.settings.get("default_llm", "claude")
                    api_key = ai_config.get_api_key(default_provider)

                    if api_key:
                        provider_map = {
                            "claude": LLMProvider.CLAUDE,
                            "chatgpt": LLMProvider.CHATGPT,
                            "openai": LLMProvider.CHATGPT,
                            "gemini": LLMProvider.GEMINI
                        }
                        provider = provider_map.get(default_provider, LLMProvider.CLAUDE)
                        llm_client = LLMClient(
                            provider=provider, api_key=api_key,
                            model=ai_config.get_model(default_provider)
                        )
                except Exception:
                    pass  # RAG will work with TF-IDF only

                # Initialize RAG — works without LLM (TF-IDF + keyword search)
                self._rag_system = EnhancedRAGSystem(
                    project=self.current_project,
                    llm_client=llm_client
                )
            else:
                # Update project reference for existing RAG system
                self._rag_system.project = self.current_project

            # Rebuild index with current project data (including encyclopedia)
            self._rag_system.rebuild_index()
            self._rag_initialized = True
            print("RAG system initialized successfully")

        except Exception as e:
            print(f"Failed to initialize RAG system: {e}")
            self._rag_initialized = False

    def _update_project_summary(self):
        """Generate or refresh the AI project summary in the background.

        Only regenerates if the project data has changed since the last summary.
        Uses a background thread to avoid blocking the UI.
        """
        if not self.current_project:
            return

        try:
            from src.ai.project_summarizer import get_project_summarizer

            summarizer = get_project_summarizer()
            if not summarizer.needs_update(self.current_project):
                return

            # Set up the AI handler if not already done
            if not summarizer._ai_handler:
                def _handler(prompt: str) -> str:
                    # Use the same LLM as the chat
                    from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
                    ai_config = get_ai_config()
                    settings = ai_config.get_settings()

                    prefer_local = settings.get("prefer_local_model", False)
                    enable_local = settings.get("enable_local_models", False)
                    local_model_id = settings.get("local_model_id", "")

                    if prefer_local and enable_local and local_model_id:
                        is_mlx = "mlx" in local_model_id.lower()
                        hf_config = HuggingFaceConfig(
                            model_id=local_model_id, use_local=True,
                            device=settings.get("local_model_device", "auto"),
                            quantization=settings.get("local_model_quantization", "none")
                                if settings.get("local_model_quantization") != "none" else None,
                            trust_remote_code=settings.get("local_model_trust_remote_code", False)
                        )
                        provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
                        client = LLMClient(provider=provider, hf_config=hf_config)
                    else:
                        provider_name = settings.get("default_llm", "claude").lower()
                        api_key = ai_config.get_api_key(provider_name)
                        if not api_key:
                            return ""
                        provider_enum = {
                            "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                            "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
                        }.get(provider_name, LLMProvider.CLAUDE)
                        client = LLMClient(
                            provider=provider_enum, api_key=api_key,
                            model=ai_config.get_model(provider_name)
                        )

                    return client.generate_text(
                        prompt=prompt,
                        system_prompt="You are a concise summarizer. Be specific, use names and details.",
                        max_tokens=400,
                        temperature=0.3,
                        task_type="project_summary"
                    )

                summarizer.set_ai_handler(_handler)

            # Run in background thread
            class _SummaryWorker(QThread):
                def __init__(self, summarizer, project):
                    super().__init__()
                    self.summarizer = summarizer
                    self.project = project

                def run(self):
                    try:
                        self.summarizer.update_project_summary(self.project)
                    except Exception as e:
                        print(f"Project summary generation failed: {e}")

            self._summary_worker = _SummaryWorker(summarizer, self.current_project)
            self._summary_worker.start()

        except Exception as e:
            print(f"Project summary setup failed: {e}")

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

    def _rag_top_chunks_per_type(self, query: str,
                                   source_types: list,
                                   top_k: int = 6,
                                   max_chars_per_chunk: int = 600,
                                   max_total_chars: int = 3500) -> str:
        """Return a RAG-selected formatted block for given source types.

        Used by the plot-AI context builder to populate
        ``rag_focused_*`` keys with the most relevant chunks for the
        user's question — instead of dumping every character / world
        entry / subplot and hoping the truncation keeps the right
        ones. Each result renders as ``[<source_type>] <name>: <body>``
        so the model knows where the chunk came from.

        Returns ``""`` when RAG isn't initialised or no matches
        surfaced — the caller treats that as "use the full block
        instead". ``source_types`` is forwarded to the search engine
        as a filter, so an unknown type is silently dropped without
        crashing the call.
        """
        if not self._rag_initialized or not self._rag_system:
            return ""
        if not query or not source_types:
            return ""
        try:
            results = self._rag_system.search(
                query=query,
                top_k=top_k,
                source_types=source_types)
        except Exception as e:
            print(f"[rag] per-type search failed "
                  f"({source_types}): {e}")
            return ""
        if not results:
            return ""
        lines = []
        running = 0
        for r in results:
            body = (r.content or "").strip()
            if not body:
                continue
            if len(body) > max_chars_per_chunk:
                body = body[:max_chars_per_chunk].rstrip() + " …"
            head = (
                f"  - [{r.source_type}] "
                f"{r.source_name or '(unnamed)'}")
            line = f"{head}: {body}"
            if running + len(line) > max_total_chars:
                lines.append(
                    f"  …{len(results) - len(lines)} more "
                    f"matches not shown to save tokens.")
                break
            lines.append(line)
            running += len(line)
        return "\n".join(lines)

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

        # Apply STT settings
        from src.services.stt_service import STTEngine
        stt_engine = self.settings.get("stt_engine", "auto")
        try:
            stt.set_engine(STTEngine(stt_engine))
        except (ValueError, KeyError):
            stt.set_engine(STTEngine.AUTO)
        stt.set_whisper_model_size(self.settings.get("stt_model_size", "base"))

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
        """Compact conversation history when it grows too large.

        Strategy:
        - Under threshold: keep everything
        - Over threshold: use AI to summarize the oldest turns into a single
          context message, then keep only the recent turns verbatim
        - Falls back to simple truncation if AI is unavailable
        """
        max_messages = self._MAX_CHAT_TURNS * 2  # 12 turns = 24 messages

        if len(self._chat_history) <= max_messages:
            return

        # Split: old messages to summarize, recent messages to keep verbatim
        keep_recent = 8 * 2  # Keep last 8 turns verbatim
        old_messages = self._chat_history[:-keep_recent]
        recent_messages = self._chat_history[-keep_recent:]

        # Check if there's already a summary at the front
        has_summary = (old_messages and
                       old_messages[0].get("role") == "system" and
                       old_messages[0].get("content", "").startswith("[Conversation summary"))

        # Try AI-powered summarization
        summary = self._summarize_old_turns(old_messages)

        if summary:
            # Replace history with: summary + recent turns
            self._chat_history = [
                {"role": "system", "content": f"[Conversation summary of earlier messages]\n{summary}"}
            ] + recent_messages
        else:
            # Fallback: simple truncation
            self._chat_history = self._chat_history[-max_messages:]

    def _summarize_old_turns(self, messages: list) -> str:
        """Use AI to summarize old conversation turns into a concise context.

        Returns a summary string, or empty string if AI is unavailable.
        """
        if not messages:
            return ""

        # Build a text representation of the old turns
        turns_text = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system" and content.startswith("[Conversation summary"):
                # Carry forward the existing summary
                turns_text.append(f"PRIOR SUMMARY: {content}")
            elif role == "user":
                turns_text.append(f"User: {content[:300]}")
            elif role == "assistant":
                turns_text.append(f"Assistant: {content[:300]}")

        if not turns_text:
            return ""

        conversation_block = "\n".join(turns_text)

        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig

            ai_config = get_ai_config()
            settings = ai_config.get_settings()

            prefer_local = settings.get("prefer_local_model", False)
            enable_local = settings.get("enable_local_models", False)
            local_model_id = settings.get("local_model_id", "")

            if prefer_local and enable_local and local_model_id:
                is_mlx = "mlx" in local_model_id.lower()
                hf_config = HuggingFaceConfig(
                    model_id=local_model_id, use_local=True,
                    device=settings.get("local_model_device", "auto"),
                    quantization=settings.get("local_model_quantization", "none")
                        if settings.get("local_model_quantization") != "none" else None,
                    trust_remote_code=settings.get("local_model_trust_remote_code", False)
                )
                provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
                client = LLMClient(provider=provider, hf_config=hf_config)
            else:
                provider_name = settings.get("default_llm", "claude").lower()
                api_key = ai_config.get_api_key(provider_name)
                if not api_key:
                    return ""
                provider_enum = {
                    "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
                }.get(provider_name, LLMProvider.CLAUDE)
                client = LLMClient(
                    provider=provider_enum, api_key=api_key,
                    model=ai_config.get_model(provider_name)
                )

            summary = client.generate_text(
                prompt=(
                    f"Summarize this conversation between a writer and their AI assistant. "
                    f"Capture: key decisions made, elements created/modified, "
                    f"topics discussed, and any ongoing threads. Be concise (3-5 sentences).\n\n"
                    f"{conversation_block[:3000]}"
                ),
                system_prompt="You summarize conversations. Be concise and specific. Use names and details.",
                max_tokens=200,
                temperature=0.2,
                task_type="chat_compaction"
            )
            return summary.strip()

        except Exception as e:
            print(f"Chat compaction summarization failed: {e}")
            return ""

    def _handle_chat_preview_request(self, message: str,
                                       mode: str = "general") -> None:
        """Show the AI-context preview for the General Assistant chat.

        Wired to ``ChatWidget.preview_requested``. Builds the same
        context dict + system prompt the chat would actually send,
        then renders the user-block via a temporary ChatWorker so
        the preview is byte-accurate. Opens the shared
        context-preview dialog.

        ``message`` may be empty if the user clicked Preview before
        typing — we use a placeholder so the user-block still
        renders, but RAG won't fire (RAG needs a query). The dialog
        intro flags this so the user knows to type something and
        click Preview again for the focused subset.
        """
        try:
            ctx = self._build_chat_context(
                mode=mode, user_message=message)
        except Exception as e:
            print(f"[chat-preview] context build failed: {e}")
            ctx = {'mode': mode}

        # If we're in writer mode the live handler also injects POV
        # + cursor context. Mirror that here so the preview matches.
        if mode == "writer" and hasattr(self, 'chat_widget'):
            try:
                ws = self.chat_widget.get_writer_settings() or {}
                ctx['writer_character_pov'] = ws.get(
                    'character_pov', '')
                ctx['writer_narrative_pov'] = ws.get(
                    'writing_pov', '')
            except Exception:
                pass

        # Use a throwaway ChatWorker just for its _build_context_prompt
        # method — that way the preview is byte-accurate to what the
        # real send path produces.
        preview_question = message or "<your question here>"
        try:
            tmp_worker = ChatWorker(
                message=preview_question,
                context=ctx, mode=mode)
            ctx_block = tmp_worker._build_context_prompt() or ""
        except Exception as e:
            ctx_block = f"(context build failed: {e})"

        # System prompt for this mode + writer-mode chapter emphasis
        # mirrors what ChatWorker.run does before generation.
        system_prompt = ChatWorker.SYSTEM_PROMPTS.get(
            mode, ChatWorker.SYSTEM_PROMPTS.get("general", ""))
        if ctx_block:
            system_prompt = (
                f"{system_prompt}\n\n{'='*60}\n"
                f"PROJECT CONTEXT:\n{'='*60}\n{ctx_block}")
        if (mode == "writer"
                and ctx.get('current_chapter_content')):
            system_prompt += (
                "\n\nIMPORTANT: Write prose that seamlessly "
                "continues or fits with the existing chapter "
                "content above.")

        from src.ui.context_preview_dialog import (
            show_context_preview, build_rag_summary,
        )
        rag_summary = build_rag_summary(ctx)
        history = ctx.get('conversation_history') or []

        # Writer mode: pre-run the research pass so the user can see
        # what the librarian picked before paying for the actual
        # write call. We use a stub LLM-free brief here (deterministic
        # fallback) to avoid burning tokens on every Preview click —
        # the real call uses an LLM at send time. If the user wants
        # the LLM-produced brief, they can click Send.
        research_brief = ""
        if mode == "writer" and message:
            try:
                from src.ai.research_agent import (
                    ResearchAgent, _fallback_brief,
                )
                # Skip the LLM call here — Preview should be cheap.
                # The deterministic fallback gives a reasonable
                # signal of what the writer pass will see.
                research_brief = _fallback_brief(message, ctx)
            except Exception as e:
                print(f"[chat-preview] research-brief stub "
                      f"failed: {e}")

        intro = (
            "This is exactly what the AI will see when you click "
            "Send. The user-block reflects your current input — "
            "if you change the input, click Preview again to "
            "refresh."
            if message else
            "Type a message in the input box and click Preview "
            "again to see the RAG-selected context for that "
            "specific question. The preview below uses a "
            "placeholder.")
        if research_brief:
            intro += (
                "  •  Writer mode runs a research pass before "
                "writing — the brief tab shows a deterministic "
                "preview; the actual send uses an LLM-produced "
                "brief that may be richer.")

        show_context_preview(
            self,
            title=f"Chat ({mode}) — context preview",
            intro=intro,
            system_prompt=system_prompt,
            user_block=preview_question,
            rag_summary=rag_summary,
            research_brief=research_brief,
            conversation_history=history)

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

        # Stash debug info for logging when response arrives
        import time
        self._debug_context = dict(context)
        self._debug_start_time = time.time()

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

    def _get_existing_element_names(self) -> str:
        """Get a compact list of all existing worldbuilding element names.

        Used so the AI knows what already exists and can reference existing
        elements instead of creating duplicates.
        """
        if not self.current_project:
            return ""

        parts = []
        p = self.current_project
        wb = p.worldbuilding

        chars = [c.name for c in p.characters if c.name]
        if chars:
            parts.append(f"Characters: {', '.join(chars)}")

        for label, lst in [
            ("Factions", getattr(wb, 'factions', [])),
            ("Places", getattr(wb, 'places', [])),
            ("Cultures", getattr(wb, 'cultures', [])),
            ("Technologies", getattr(wb, 'technologies', [])),
            ("Magic Systems", getattr(wb, 'magic_systems', [])),
            ("Myths", getattr(wb, 'myths', [])),
            ("Flora", getattr(wb, 'flora', [])),
            ("Fauna", getattr(wb, 'fauna', [])),
        ]:
            names = [getattr(e, 'name', '') for e in (lst or []) if getattr(e, 'name', '')]
            if names:
                parts.append(f"{label}: {', '.join(names)}")

        return "\n".join(parts)

    def _find_referenced_element(self, message: str, project) -> str:
        """Check if the user's message mentions a specific element by name.

        If found, return that element's full details as a formatted string.
        """
        msg_lower = message.lower()

        # Check characters
        for char in project.characters:
            if char.name and char.name.lower() in msg_lower:
                parts = [f"FOCUSED ELEMENT — Character: {char.name}"]
                parts.append(f"Type: {getattr(char, 'character_type', '')}")
                for field in ['personality', 'backstory', 'physical_description',
                              'speaking_style', 'motivations', 'fears',
                              'emotional_baseline', 'notes']:
                    val = getattr(char, field, '')
                    if val:
                        parts.append(f"{field.replace('_', ' ').title()}: {val[:300]}")
                traits = getattr(char, 'personality_traits', [])
                if traits:
                    parts.append(f"Traits: {', '.join(traits)}")
                arc = getattr(char, 'personality_arc', [])
                if arc:
                    latest = arc[-1]
                    if getattr(latest, 'emotional_state', ''):
                        parts.append(f"Current state: {latest.emotional_state}")
                    if getattr(latest, 'growth_notes', ''):
                        parts.append(f"Growth: {latest.growth_notes[:200]}")
                return "\n".join(parts)

        # Check worldbuilding elements
        wb = project.worldbuilding
        for category, lst in [
            ("Faction", getattr(wb, 'factions', [])),
            ("Place", getattr(wb, 'places', [])),
            ("Culture", getattr(wb, 'cultures', [])),
            ("Technology", getattr(wb, 'technologies', [])),
            ("Magic System", getattr(wb, 'magic_systems', [])),
            ("Myth", getattr(wb, 'myths', [])),
            ("Flora", getattr(wb, 'flora', [])),
            ("Fauna", getattr(wb, 'fauna', [])),
        ]:
            for elem in (lst or []):
                name = getattr(elem, 'name', '')
                if name and name.lower() in msg_lower:
                    parts = [f"FOCUSED ELEMENT — {category}: {name}"]
                    for field in dir(elem):
                        if field.startswith('_') or field in ('id', 'created_at', 'updated_at'):
                            continue
                        val = getattr(elem, field, None)
                        if val and isinstance(val, str) and len(val) > 0:
                            parts.append(f"{field.replace('_', ' ').title()}: {val[:300]}")
                        elif val and isinstance(val, list) and val:
                            if all(isinstance(v, str) for v in val):
                                parts.append(f"{field.replace('_', ' ').title()}: {', '.join(val[:10])}")
                    return "\n".join(parts)

        return ""

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

        # Include existing element names so the AI can reference them
        # and avoid creating duplicates
        existing_names = self._get_existing_element_names()
        if existing_names:
            context['existing_elements'] = existing_names

        # If the user's message references a specific element by name,
        # inject that element's full details into the context
        if user_message:
            focused = self._find_referenced_element(user_message, project)
            if focused:
                context['focused_element'] = focused

        # Include AI-generated project summary if available
        if hasattr(project, 'ai_summary') and project.ai_summary and not project.ai_summary.is_empty():
            ai_sum_parts = []
            if project.ai_summary.plot_summary:
                ai_sum_parts.append(f"Plot: {project.ai_summary.plot_summary}")
            if project.ai_summary.character_summary:
                ai_sum_parts.append(f"Characters: {project.ai_summary.character_summary}")
            if project.ai_summary.worldbuilding_summary:
                ai_sum_parts.append(f"World: {project.ai_summary.worldbuilding_summary}")
            if project.ai_summary.themes_summary:
                ai_sum_parts.append(f"Themes: {project.ai_summary.themes_summary}")
            if ai_sum_parts:
                context['ai_summary'] = "\n".join(ai_sum_parts)

        # Use RAG for ALL modes to retrieve relevant project + encyclopedia context
        if user_message and self._rag_initialized:
            rag_tokens = 1500 if mode == "general" else 1000
            rag_context = self._get_rag_context(user_message, max_tokens=rag_tokens)
            if rag_context:
                context['rag_context'] = rag_context

        # Track whether knowledge base is enabled (for labeling in the prompt)
        try:
            from src.config.ai_config import get_ai_config
            context['kb_enabled'] = get_ai_config().get_settings().get("enable_knowledge_base", True)
        except Exception:
            context['kb_enabled'] = False

        # For chapter_focus, plot and writer modes, additional RAG if not already set.
        # Plot mode benefits from RAG since the user is asking structural questions
        # that may reference characters/places by name buried deep in worldbuilding.
        if mode in ("chapter_focus", "writer", "plot") and not context.get('rag_context') and user_message and self._rag_initialized:
            rag_context = self._get_rag_context(user_message, max_tokens=1200)
            if rag_context:
                context['rag_context'] = rag_context

        # Plot mode: per-source-type RAG selections. The full
        # ``characters`` / ``worldbuilding`` / ``plot_subplots`` /
        # ``chapter_excerpts`` blocks below dump the whole roster
        # capped at byte budgets — for projects with dozens of
        # entries that means the back half is silently truncated.
        # The ``rag_focused_*`` keys carry the top-K results per type
        # for THIS specific question so the model gets a tight,
        # high-signal subset alongside the broader full lists. The
        # user-block builder renders these in their own labelled
        # block at the top of the prompt.
        if (mode == "plot" and user_message
                and self._rag_initialized):
            try:
                rag_chars = self._rag_top_chunks_per_type(
                    user_message, source_types=['character'],
                    top_k=8, max_chars_per_chunk=500,
                    max_total_chars=3000)
                if rag_chars:
                    context['rag_focused_characters'] = rag_chars

                world_types = [
                    'worldbuilding', 'place', 'faction', 'culture',
                    'technology', 'historical_event', 'flora',
                    'fauna', 'myth', 'star_system', 'military',
                    'economy', 'political_system',
                ]
                rag_world = self._rag_top_chunks_per_type(
                    user_message, source_types=world_types,
                    top_k=8, max_chars_per_chunk=500,
                    max_total_chars=3500)
                if rag_world:
                    context['rag_focused_worldbuilding'] = rag_world

                rag_subplots = self._rag_top_chunks_per_type(
                    user_message, source_types=['subplot'],
                    top_k=5, max_chars_per_chunk=400,
                    max_total_chars=2000)
                if rag_subplots:
                    context['rag_focused_subplots'] = rag_subplots

                rag_chapters = self._rag_top_chunks_per_type(
                    user_message,
                    source_types=['chapter_content',
                                  'chapter_key_point'],
                    top_k=5, max_chars_per_chunk=600,
                    max_total_chars=3000)
                if rag_chapters:
                    context['rag_focused_chapters'] = rag_chapters
            except Exception as e:
                print(f"[rag] per-type focused fetch failed: {e}")

        # ``is_chapter_focused`` gates the higher-detail character /
        # worldbuilding payload. Plot mode joins it because plot
        # discussions need the full character + world picture, not the
        # name-only summary the general mode falls back to.
        is_chapter_focused = mode in ("chapter_focus", "writer", "plot")

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
                        if getattr(char, 'personality_traits', None):
                            char_info += f"\n  Traits: {', '.join(char.personality_traits)}"
                        if getattr(char, 'speaking_style', None) and char.speaking_style:
                            char_info += f"\n  Speech: {char.speaking_style[:100]}"
                        if getattr(char, 'motivations', None) and char.motivations:
                            char_info += f"\n  Motivations: {char.motivations[:100]}"
                        if getattr(char, 'fears', None) and char.fears:
                            char_info += f"\n  Fears: {char.fears[:100]}"
                        if getattr(char, 'emotional_baseline', None) and char.emotional_baseline:
                            char_info += f"\n  Baseline mood: {char.emotional_baseline}"
                        if getattr(char, 'personality_arc', None) and char.personality_arc:
                            latest = char.personality_arc[-1]
                            if latest.emotional_state:
                                char_info += f"\n  Current state (Ch{latest.chapter_number}): {latest.emotional_state}"
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

        # Plot mode: build per-chapter excerpts (opening + closing of
        # each chapter) so the AI can quote and cite scenes instead of
        # speaking about chapters as opaque titles. Excerpts are capped
        # per-chapter and across the batch so a 50-chapter manuscript
        # doesn't blow the prompt budget.
        if (mode == "plot"
                and hasattr(project, 'manuscript')
                and project.manuscript
                and project.manuscript.chapters):
            EXCERPT_HEAD = 350
            EXCERPT_TAIL = 250
            EXCERPT_BUDGET = 9000
            excerpt_blocks = []
            running = 0
            for i, ch in enumerate(project.manuscript.chapters, 1):
                if not ch.content or running >= EXCERPT_BUDGET:
                    continue
                text = ch.content.strip()
                if len(text) <= EXCERPT_HEAD + EXCERPT_TAIL + 40:
                    excerpt = text
                else:
                    excerpt = (
                        f"{text[:EXCERPT_HEAD].rstrip()}"
                        f"\n   …\n"
                        f"{text[-EXCERPT_TAIL:].lstrip()}"
                    )
                block = f"--- Ch {i}: {ch.title} ---\n{excerpt}"
                if running + len(block) > EXCERPT_BUDGET:
                    excerpt_blocks.append(
                        f"--- (… {len(project.manuscript.chapters) - i + 1} "
                        f"more chapters not excerpted to save tokens) ---")
                    break
                excerpt_blocks.append(block)
                running += len(block)
            if excerpt_blocks:
                context['chapter_excerpts'] = "\n\n".join(excerpt_blocks)

        # Plot mode: build a structured plot map (Freytag stages, events,
        # subplots, promises, tensions, themes) so the AI can discuss
        # the author's intended structure against what's actually
        # written. Each section is emitted as its OWN context key
        # (``plot_freytag``, ``plot_events``, ``plot_subplots``, …)
        # so the user-block builder can render each as a clearly
        # labelled section with its own per-block budget — instead
        # of stuffing everything into a single ``plot_map`` string
        # that gets truncated mid-list and silently drops late
        # sections (subplots, tensions, themes).
        # ``plot_map`` is still set as an aggregate fallback for
        # surfaces that read it as a single string.
        if mode == "plot" and hasattr(project, 'story_planning') and project.story_planning:
            sp = project.story_planning
            map_parts = []
            fp = sp.freytag_pyramid
            if fp:
                stage_pairs = [
                    ("Exposition", fp.exposition),
                    ("Rising Action", getattr(fp, 'rising_action', '')),
                    ("Climax", fp.climax),
                    ("Falling Action", getattr(fp, 'falling_action', '')),
                    ("Resolution", getattr(fp, 'resolution', '')),
                ]
                stage_lines = [f"  {name}: {text[:300]}"
                                for name, text in stage_pairs if text]
                if stage_lines:
                    block = "\n".join(stage_lines)
                    context['plot_freytag'] = block
                    map_parts.append("FREYTAG PYRAMID:\n" + block)
                if getattr(fp, 'events', None):
                    event_lines = [f"  - {e.title}"
                                    + (f": {e.description[:150]}"
                                        if getattr(e, 'description', '')
                                        else "")
                                    for e in fp.events[:25]]
                    if event_lines:
                        block = "\n".join(event_lines)
                        context['plot_events'] = block
                        map_parts.append("PLOT EVENTS:\n" + block)
            if sp.subplots:
                # Subplots are first-class plot infrastructure — give
                # the model enough detail to actually weave with them
                # (not just a name). Per subplot we surface: title +
                # status, the connection to the main plot, the people
                # carrying it, and up to 3 of its events so the AI
                # can see *what's happening inside* the subplot.
                sub_lines = []
                for s in sp.subplots[:10]:
                    title = getattr(s, 'title', '') or '(untitled)'
                    status = getattr(s, 'status', '') or 'active'
                    head = f"  - {title}  (status: {status})"
                    sub_lines.append(head)
                    desc = (getattr(s, 'description', '') or '').strip()
                    if desc:
                        sub_lines.append(f"      what: {desc[:240]}")
                    conn = (getattr(s, 'connection_to_main', '')
                            or '').strip()
                    if conn:
                        sub_lines.append(
                            f"      ties to main: {conn[:200]}")
                    chars = (
                        getattr(s, 'related_characters', []) or [])
                    if chars:
                        sub_lines.append(
                            f"      characters: "
                            f"{', '.join(str(c) for c in chars)}")
                    events = getattr(s, 'events', []) or []
                    if events:
                        ev_lines = []
                        for ev in events[:3]:
                            et = (getattr(ev, 'title', '')
                                  or '(untitled)')
                            estage = getattr(ev, 'stage', '') or ''
                            eact = getattr(ev, 'act', None)
                            head = f"        • {et}"
                            if eact:
                                head += f" (act {eact}"
                                if estage:
                                    head += f", {estage}"
                                head += ")"
                            elif estage:
                                head += f" ({estage})"
                            ev_lines.append(head)
                        if len(events) > 3:
                            ev_lines.append(
                                f"        … and {len(events) - 3} "
                                f"more event(s)")
                        sub_lines.append("      events:")
                        sub_lines.extend(ev_lines)
                block = "\n".join(sub_lines)
                context['plot_subplots'] = block
                map_parts.append(
                    "SUBPLOTS (secondary storylines tied to the main "
                    "plot):\n" + block)
            if getattr(sp, 'promises', None):
                promise_lines = []
                for p in sp.promises[:15]:
                    ptype = getattr(p, 'promise_type', '') or '?'
                    title = getattr(p, 'title', '') or '(untitled)'
                    desc = getattr(p, 'description', '') or ''
                    promise_lines.append(
                        f"  - [{ptype}] {title}"
                        + (f": {desc[:150]}" if desc else ""))
                if promise_lines:
                    block = "\n".join(promise_lines)
                    context['plot_promises'] = block
                    map_parts.append("STORY PROMISES:\n" + block)
            # Themes — what the story is *about* underneath its
            # events. Surfaced so the plot AI can check whether
            # proposed beats reinforce or undercut the book's
            # argument. Both rich themes (theme_details) and any
            # legacy bare-string themes are included.
            rich_themes = getattr(sp, 'theme_details', None) or []
            legacy_themes = getattr(sp, 'themes', None) or []
            if rich_themes or legacy_themes:
                theme_lines = []
                for th in rich_themes[:10]:
                    title = getattr(th, 'title', '') or '(untitled)'
                    statement = (getattr(th, 'statement', '') or '').strip()
                    desc = (getattr(th, 'description', '') or '').strip()
                    motifs = (getattr(th, 'motifs', []) or [])
                    chars = (getattr(th, 'related_characters', []) or [])
                    head = f"  - {title}"
                    if statement:
                        head += f" — “{statement[:200]}”"
                    theme_lines.append(head)
                    if desc and not statement:
                        theme_lines.append(f"      what: {desc[:200]}")
                    if motifs:
                        theme_lines.append(
                            f"      motifs: "
                            f"{', '.join(str(m) for m in motifs[:8])}")
                    if chars:
                        theme_lines.append(
                            f"      carried by: "
                            f"{', '.join(str(c) for c in chars)}")
                # Legacy bare-text themes — surface them so they're
                # not invisible to the AI, but flag them so the model
                # knows to ask for the underlying argument.
                for txt in legacy_themes[:10]:
                    if txt:
                        theme_lines.append(
                            f"  - {txt}  (bare label only — no "
                            f"statement / motifs defined yet)")
                if theme_lines:
                    block = "\n".join(theme_lines)
                    context['plot_themes'] = block
                    map_parts.append(
                        "STORY THEMES (what the book is about "
                        "underneath its events):\n" + block)
            if getattr(sp, 'tensions', None):
                # Sustained dramatic forces — name them so the AI
                # can reason about which pressures are escalating
                # vs resolving when proposing beats or auditing
                # pacing. Order: highest intensity first so the
                # most important tensions land first if we hit the
                # token cap.
                tension_lines = []
                ranked = sorted(
                    sp.tensions,
                    key=lambda t: -int(getattr(t, 'intensity', 0)))
                for t in ranked[:15]:
                    ttype = getattr(t, 'tension_type', '') or '?'
                    title = getattr(t, 'title', '') or '(untitled)'
                    state = getattr(t, 'current_state', '') or '?'
                    intensity = int(getattr(t, 'intensity', 0))
                    chars = getattr(t, 'characters_involved', []) or []
                    desc = getattr(t, 'description', '') or ''
                    stakes = getattr(t, 'stakes', '') or ''
                    head = (f"  - [{ttype}] {title}  "
                            f"(state: {state}, intensity: "
                            f"{intensity}/100"
                            + (f", involves: {', '.join(chars)}"
                                if chars else "")
                            + ")")
                    line = head
                    if desc:
                        line += f"\n      what: {desc[:200]}"
                    if stakes:
                        line += f"\n      stakes: {stakes[:200]}"
                    tension_lines.append(line)
                if tension_lines:
                    block = "\n".join(tension_lines)
                    context['plot_tensions'] = block
                    map_parts.append(
                        "STORY TENSIONS (sustained dramatic forces):\n"
                        + block)
            if map_parts:
                context['plot_map'] = "\n\n".join(map_parts)

        # Current chapter context — include for ALL modes
        if hasattr(self, 'manuscript_editor'):
            content, title = self.manuscript_editor.get_current_chapter_info()
            if title:
                context['current_chapter_title'] = title
                if is_chapter_focused:
                    # Include FULL chapter content for focused modes
                    context['current_chapter_content'] = content or ""
                else:
                    # General mode: include the full current chapter so the AI
                    # can reference the actual manuscript text
                    context['current_chapter_content'] = content or ""

                # Get chapter planning/outline for ALL modes
                if self.manuscript_editor.current_chapter_editor:
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

        # If user mentions a specific chapter by name or number, include its content
        if user_message and hasattr(project, 'manuscript') and project.manuscript.chapters:
            import re as _re
            msg_lower = user_message.lower()
            for ch in project.manuscript.chapters:
                # Match "chapter 3", "ch3", "chapter three", or the chapter title
                ch_mentioned = False
                if f"chapter {ch.number}" in msg_lower or f"ch{ch.number}" in msg_lower:
                    ch_mentioned = True
                elif ch.title and ch.title.lower() in msg_lower:
                    ch_mentioned = True

                if ch_mentioned and ch.content and ch.id != context.get('_current_ch_id', ''):
                    # Load content from disk if empty
                    if not ch.content:
                        from pathlib import Path
                        pd = Path(project.project_path).parent if project.project_path else None
                        if pd:
                            try:
                                ch.load_content_from_file(pd)
                            except Exception:
                                pass
                    if ch.content:
                        context['referenced_chapter'] = {
                            'title': ch.title,
                            'number': ch.number,
                            'content': ch.content[:8000],
                        }
                        break

        # === PROJECT INDEX — complete catalog of all elements ===
        # This gives the AI a browsable inventory of everything in the project.
        # Not full content (too large), but enough to know what exists.
        index_parts = []

        # Manuscript index: chapter titles + synopsis
        if hasattr(project, 'manuscript') and project.manuscript.chapters:
            ch_lines = []
            for ch in project.manuscript.chapters[:25]:
                wc = len(ch.content.split()) if ch.content else 0
                synopsis = ""
                if hasattr(ch, 'planning') and ch.planning and ch.planning.description:
                    synopsis = f" — {ch.planning.description[:80]}"
                ch_lines.append(f"  Ch{ch.number}. {ch.title} ({wc}w){synopsis}")
            index_parts.append("CHAPTERS:\n" + "\n".join(ch_lines))

        # Character index: name, type, key traits
        if hasattr(project, 'characters') and project.characters:
            char_lines = []
            for c in project.characters:
                parts = [f"  {c.name} ({getattr(c, 'character_type', 'minor')})"]
                traits = getattr(c, 'personality_traits', [])
                if traits:
                    parts.append(f"traits: {', '.join(traits[:4])}")
                if getattr(c, 'speaking_style', ''):
                    parts.append(f"speech: {c.speaking_style[:40]}")
                if getattr(c, 'motivations', ''):
                    parts.append(f"wants: {c.motivations[:40]}")
                char_lines.append(" | ".join(parts))
            index_parts.append("CHARACTERS:\n" + "\n".join(char_lines))

        # Worldbuilding index: all element names grouped by type
        wb = getattr(project, 'worldbuilding', None)
        if wb:
            wb_lines = []
            for label, lst in [
                ("Factions", getattr(wb, 'factions', [])),
                ("Places", getattr(wb, 'places', [])),
                ("Cultures", getattr(wb, 'cultures', [])),
                ("Technologies", getattr(wb, 'technologies', [])),
                ("Magic Systems", getattr(wb, 'magic_systems', [])),
                ("Myths", getattr(wb, 'myths', [])),
                ("Flora", getattr(wb, 'flora', [])),
                ("Fauna", getattr(wb, 'fauna', [])),
            ]:
                if lst:
                    names = []
                    for e in lst[:10]:
                        name = getattr(e, 'name', '')
                        desc = getattr(e, 'description', '')[:50]
                        if desc:
                            names.append(f"{name} ({desc})")
                        else:
                            names.append(name)
                    wb_lines.append(f"  {label}: {', '.join(names)}")
            if wb_lines:
                index_parts.append("WORLDBUILDING:\n" + "\n".join(wb_lines))

        if index_parts:
            context['project_index'] = "\n\n".join(index_parts)

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

    def _build_plot_ai_context(self, question: str = "") -> dict:
        """Return the context dict the plot-tab Discuss-with-AI needs.

        Reuses ``_build_chat_context(mode='plot', user_message=question)``
        so the plot tab's AI sees the exact same project payload as the
        General Assistant in plot mode — manuscript chapters list,
        plot map, characters, worldbuilding, currently-open chapter,
        and (if the project's RAG index is built) RAG-selected
        characters / worldbuilding entries that match the question.
        Without the question argument this would dump everything; with
        it, RAG narrows down to relevant items only — important once a
        project has dozens of characters or hundreds of worldbuilding
        entries.

        We also add the writing-tool's initialised cloud LLM client so
        the helper in plot_manager doesn't have to re-discover API
        keys when the per-task model isn't configured.
        """
        try:
            base = self._build_chat_context(
                mode="plot", user_message=question or "")
        except Exception as e:
            print(f"[plot-ai] context build failed: {e}")
            base = {}
        # _build_chat_context already provides ``chapter_excerpts`` for
        # plot mode; we just need a fuller manuscript index than the
        # 20-chapter cap the chat path uses, since the plot tab is the
        # one surface where the user is explicitly thinking about the
        # whole structure.
        try:
            project = self.current_project
            if (project and hasattr(project, 'manuscript')
                    and project.manuscript
                    and project.manuscript.chapters):
                lines = []
                for i, ch in enumerate(project.manuscript.chapters, 1):
                    wc = len(ch.content.split()) if ch.content else 0
                    lines.append(f"{i}. {ch.title} ({wc} words)")
                base['manuscript_index'] = "\n".join(lines)
        except Exception as e:
            print(f"[plot-ai] index build failed: {e}")
        # Hand over the writing tool's cloud client when one was
        # initialised — the plot-AI helper falls back to it after the
        # per-task model lookup misses.
        try:
            base['llm_client'] = getattr(
                self.manuscript_editor, '_llm_client', None)
        except Exception:
            base['llm_client'] = None
        return base

    def _push_characters_to_plot_widget(self) -> None:
        """Send the current character roster into the plot widget.

        Called after project load and on every characters_widget
        content change. Keeps the Tension and Plot Event editors'
        multi-select pickers in sync with the actual Characters tab
        — without this, the editors start empty even when the
        project has a full cast, and tensions can't reference real
        people.

        The widget normalises both data sources:
          * From characters_widget if the user has been editing in
            this session (live, includes unsaved adds).
          * From current_project.characters as a fallback.
        Either way, a deduped sorted list of names is handed to the
        plot widget.
        """
        names: list = []
        try:
            if hasattr(self, 'characters_widget'):
                live = self.characters_widget.get_data() or []
                names.extend(getattr(c, 'name', '') for c in live
                              if getattr(c, 'name', ''))
        except Exception as e:
            print(f"[plot-chars] live read failed: {e}")
        try:
            if (not names and self.current_project
                    and getattr(self.current_project,
                                  'characters', None)):
                names.extend(getattr(c, 'name', '')
                              for c in self.current_project.characters
                              if getattr(c, 'name', ''))
        except Exception:
            pass
        # Dedupe while preserving the first-seen order so the cast
        # appears roughly in the order the user added them.
        seen: set = set()
        deduped: list = []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                deduped.append(n)
        try:
            if hasattr(self, 'story_planning_widget'):
                self.story_planning_widget.set_available_characters(
                    deduped)
        except Exception as e:
            print(f"[plot-chars] push failed: {e}")

    def _create_from_plot_ai_suggestion(self, kind: str,
                                          data: dict) -> bool:
        """Create a project element from a plot-AI suggestion card.

        Wired into ``PlotManagerWidget`` via
        ``set_ai_create_callback``. Routes by ``kind`` to the same
        per-type create handlers the General Assistant chat uses for
        its ``<create_*>`` blocks; that way a character / place /
        faction / culture / chapter accepted from the plot-AI tab
        ends up in the project model, the right widget tab, AND
        triggers content_changed for autosave — all the bookkeeping
        the existing pipeline already handles. Returns True when the
        element was created (or, falling back, an existing one was
        updated by name); False on any failure so the card can show
        an error.
        """
        if not self.current_project:
            print("[plot-ai] cannot add suggestion — no project open")
            return False
        handler = {
            "character": self._create_character_from_json,
            "place": self._create_place_from_json,
            "faction": self._create_faction_from_json,
            "culture": self._create_culture_from_json,
            "chapter": self._create_chapter_from_json,
            # Plot-native kinds — added so the plot AI can propose
            # new beats / subplots / promises / tensions and the user
            # can one-click accept them into the StoryPlanning model.
            "plot_event": self._create_plot_event_from_json,
            "subplot": self._create_subplot_from_json,
            "promise": self._create_promise_from_json,
            "tension": self._create_tension_from_json,
            "theme": self._create_theme_from_json,
        }.get(kind)
        if handler is None:
            print(f"[plot-ai] unknown suggestion kind: {kind}")
            return False
        try:
            # Existing-element check mirrors the create-pipeline path
            # so accepting a plot-AI suggestion that names something
            # the user already has updates that record instead of
            # silently making a near-duplicate.
            name = (data.get('name') or data.get('title') or '').strip()
            if name:
                existing = self._find_similar_existing(name, handler)
                if existing:
                    result = self._update_existing_element(
                        existing, data)
                    if result:
                        self._on_content_changed()
                        return True
            result = handler(data)
            if result:
                # Refresh the appropriate UI tab so the user sees
                # their new element without having to reload.
                self._on_content_changed()
                return True
            return False
        except Exception as e:
            print(f"[plot-ai] create failed for {kind}: {e}")
            return False

    def _on_chat_response(self, response: str, system_prompt: str = ""):
        """Handle successful AI response.

        Args:
            response: The AI's response text (original, with tool calls)
            system_prompt: The system prompt used for this response
        """
        # Log to debug panel if visible
        import time
        if self._ai_debug_panel and self._ai_debug_panel.isVisible():
            elapsed = int((time.time() - self._debug_start_time) * 1000)
            self._ai_debug_panel.log_turn(
                mode=getattr(self, '_pending_mode', 'unknown'),
                user_message=getattr(self, '_pending_chat_message', ''),
                system_prompt=system_prompt,
                context=self._debug_context,
                response=response,
                elapsed_ms=elapsed
            )

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
            # Plot-native creators — added so the General Assistant
            # (especially in plot mode) can create new beats /
            # subplots / promises / tensions inline. Same JSON
            # shape the plot-tab AI uses for its <suggest_*> blocks
            # so the model only has to learn one schema per type.
            (r'<create_plot_event>\s*(.*?)\s*</create_plot_event>', self._create_plot_event_from_json),
            (r'<create_subplot>\s*(.*?)\s*</create_subplot>', self._create_subplot_from_json),
            (r'<create_promise>\s*(.*?)\s*</create_promise>', self._create_promise_from_json),
            (r'<create_tension>\s*(.*?)\s*</create_tension>', self._create_tension_from_json),
            (r'<create_theme>\s*(.*?)\s*</create_theme>', self._create_theme_from_json),
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

                    # Check for similar existing elements before creating
                    name = data.get('name', '').strip()
                    if name:
                        existing = self._find_similar_existing(name, handler)
                        if existing:
                            # Update the existing element instead of creating new
                            result = self._update_existing_element(existing, data)
                            if result:
                                created_elements.append(result)
                                continue

                    result = handler(data)
                    if result:
                        created_elements.append(result)
                except json.JSONDecodeError as e:
                    print(f"Failed to parse creation JSON: {e}")
                    print(f"JSON string was: {match[:200]}...")
                except Exception as e:
                    print(f"Failed to create element: {e}")

        # Handle merge blocks
        merge_pattern = r'<merge_elements>\s*(.*?)\s*</merge_elements>'
        for match in re.findall(merge_pattern, response, re.DOTALL | re.IGNORECASE):
            try:
                json_str = re.sub(r",\s*}", "}", match.strip())
                json_str = re.sub(r",\s*]", "]", json_str)
                data = json.loads(json_str)
                result = self._merge_elements_from_json(data)
                if result:
                    created_elements.append(result)
            except Exception as e:
                print(f"Failed to merge elements: {e}")

        # Handle enrich blocks
        enrich_pattern = r'<enrich_element>\s*(.*?)\s*</enrich_element>'
        for match in re.findall(enrich_pattern, response, re.DOTALL | re.IGNORECASE):
            try:
                json_str = re.sub(r",\s*}", "}", match.strip())
                json_str = re.sub(r",\s*]", "]", json_str)
                data = json.loads(json_str)
                result = self._enrich_element_from_json(data)
                if result:
                    created_elements.append(result)
            except Exception as e:
                print(f"Failed to enrich element: {e}")

        # Remove all action blocks from display response
        for pattern, _ in creation_patterns:
            display_response = re.sub(pattern, '', display_response, flags=re.DOTALL | re.IGNORECASE)
        display_response = re.sub(merge_pattern, '', display_response, flags=re.DOTALL | re.IGNORECASE)
        display_response = re.sub(enrich_pattern, '', display_response, flags=re.DOTALL | re.IGNORECASE)

        # Clean up extra whitespace
        display_response = re.sub(r'\n{3,}', '\n\n', display_response).strip()

        return display_response, created_elements

    def _merge_elements_from_json(self, data: dict) -> tuple:
        """Merge two elements: keep target, absorb source, remove source.

        data: {element_type, target_name, source_name, merged_fields}
        """
        if not self.current_project:
            return None

        element_type = data.get('element_type', '')
        target_name = data.get('target_name', '').strip()
        source_name = data.get('source_name', '').strip()
        merged_fields = data.get('merged_fields', {})

        if not target_name or not source_name:
            return None

        elements = self._get_element_list(element_type)
        if elements is None:
            return None

        target = next((e for e in elements if getattr(e, 'name', '') == target_name), None)
        source = next((e for e in elements if getattr(e, 'name', '') == source_name), None)

        if not target or not source:
            print(f"Merge failed: target='{target_name}' found={target is not None}, "
                  f"source='{source_name}' found={source is not None}")
            return None

        # Apply merged_fields to target
        for key, value in merged_fields.items():
            if key in ('id', 'name', 'created_at'):
                continue
            if value:
                try:
                    setattr(target, key, value)
                except (AttributeError, TypeError):
                    pass

        # Also fill any empty target fields from source
        for field in dir(source):
            if field.startswith('_') or field in ('id', 'name', 'created_at', 'updated_at'):
                continue
            src_val = getattr(source, field, None)
            tgt_val = getattr(target, field, None)
            if src_val and (tgt_val is None or tgt_val == "" or tgt_val == []):
                try:
                    setattr(target, field, src_val)
                except (AttributeError, TypeError):
                    pass

        # Remove source
        if source in elements:
            elements.remove(source)

        print(f"Merged {element_type}: '{source_name}' → '{target_name}'")
        return ('merged', f"{source_name} → {target_name}")

    def _enrich_element_from_json(self, data: dict) -> tuple:
        """Enrich an existing element with new field values.

        data: {element_type, name, updates: {field: value}}
        """
        if not self.current_project:
            return None

        element_type = data.get('element_type', '')
        name = data.get('name', '').strip()
        updates = data.get('updates', {})

        if not name or not updates:
            return None

        elements = self._get_element_list(element_type)
        if elements is None:
            return None

        # Find element by exact or fuzzy match
        from src.utils.fuzzy_match import find_similar_element
        element = next((e for e in elements if getattr(e, 'name', '') == name), None)
        if not element:
            element = find_similar_element(name, elements, threshold=0.7)
        if not element:
            print(f"Enrich failed: '{name}' not found in {element_type}")
            return None

        updated = []
        for key, value in updates.items():
            if key in ('id', 'name', 'created_at'):
                continue
            if not value:
                continue

            # Handle type coercion for list fields (e.g., personality_traits)
            current = getattr(element, key, None)
            if isinstance(current, list) and isinstance(value, str):
                # Convert comma-separated string to list
                value = [v.strip() for v in value.split(',') if v.strip()]
            elif isinstance(current, list) and isinstance(value, list):
                pass  # Already a list
            elif isinstance(current, str) and isinstance(value, str):
                # For string fields, only fill if current is thin
                if current and len(current) > 80:
                    continue  # Don't overwrite substantial content

            try:
                setattr(element, key, value)
                updated.append(key)
            except (AttributeError, TypeError, ValueError):
                pass

        if updated:
            print(f"Enriched {element_type} '{name}': {', '.join(updated)}")
            return ('enriched', f"{name} ({', '.join(updated)})")
        return None

    def _get_element_list(self, element_type: str) -> list:
        """Get the element list for a given type string."""
        if not self.current_project:
            return None
        wb = self.current_project.worldbuilding
        type_map = {
            'character': self.current_project.characters,
            'faction': getattr(wb, 'factions', []),
            'place': getattr(wb, 'places', []),
            'culture': getattr(wb, 'cultures', []),
            'technology': getattr(wb, 'technologies', []),
            'myth': getattr(wb, 'myths', []),
            'flora': getattr(wb, 'flora', []),
            'fauna': getattr(wb, 'fauna', []),
        }
        return type_map.get(element_type)

    def _find_similar_existing(self, name: str, handler) -> object:
        """Find an existing element with a similar name.

        Maps the creation handler to the appropriate element list and
        searches for fuzzy name matches.

        Returns:
            The matching element, or None.
        """
        from src.utils.fuzzy_match import find_similar_element

        if not self.current_project:
            return None

        # Map handlers to their element lists
        handler_to_list = {
            self._create_character_from_json: self.current_project.characters,
            self._create_place_from_json: self.current_project.worldbuilding.places,
            self._create_faction_from_json: self.current_project.worldbuilding.factions,
            self._create_culture_from_json: self.current_project.worldbuilding.cultures,
            self._create_myth_from_json: self.current_project.worldbuilding.myths,
            self._create_technology_from_json: self.current_project.worldbuilding.technologies,
            self._create_flora_from_json: self.current_project.worldbuilding.flora,
            self._create_fauna_from_json: self.current_project.worldbuilding.fauna,
        }

        elements = handler_to_list.get(handler)
        if elements is None:
            return None

        return find_similar_element(name, elements, threshold=0.7)

    def _update_existing_element(self, element, data: dict) -> tuple:
        """Update an existing element with new data from the AI.

        Only fills in fields that are currently empty on the existing
        element — never overwrites user-authored content.

        Returns:
            Tuple of (element_type, element_name) or None.
        """
        name = getattr(element, 'name', '')
        element_type = type(element).__name__.lower()
        updated_fields = []

        for key, value in data.items():
            if key in ('id', 'name'):
                continue
            if not value:
                continue

            current = getattr(element, key, None)
            # Only fill empty fields
            if current is None or current == "" or current == [] or current == 0:
                try:
                    setattr(element, key, value)
                    updated_fields.append(key)
                except (AttributeError, TypeError):
                    pass

        if updated_fields:
            print(f"Updated existing {element_type} '{name}': {', '.join(updated_fields)}")
            return (f'{element_type}_updated', name)
        else:
            print(f"Existing {element_type} '{name}' already has all fields — skipped")
            return None

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

    @staticmethod
    def _stage_for_arc_position(i: int, total: int) -> str:
        """Heuristic: which dramatic stage does scene ``i`` of ``total`` fall in?

        Mirrors the chapter-arc visualisation's bands: roughly
        15%/35%/15%/25%/10% for exposition/rising/climax/falling/
        resolution. Used when the AI gives us an ordered scene list
        but doesn't tag each scene with a stage.
        """
        if total <= 1:
            return 'rising'
        pct = i / max(1, total - 1)
        if pct <= 0.15:
            return 'exposition'
        if pct < 0.50:
            return 'rising'
        if pct < 0.65:
            return 'climax'
        if pct < 0.90:
            return 'falling'
        return 'resolution'

    @staticmethod
    def _arc_position_for_index(i: int, total: int) -> int:
        """Spread ``total`` events evenly across the 0-100 arc.

        Position 0 = chapter open, 100 = chapter end. Single-event
        chapters land at midpoint (50) so they sit naturally on the
        visual arc instead of pinned to the left edge.
        """
        if total <= 1:
            return 50
        return int(round(i / (total - 1) * 100))

    def _build_chapter_planner_events(self, explicit_events,
                                       scene_list,
                                       chapter_id: str) -> list:
        """Produce the StoryEvent list the chapter planner renders.

        Resolution order:
          1. Explicit ``events`` array in the JSON — richer, lets the
             AI pin stage / arc_position per beat.
          2. Derived from ``scene_list`` — each string becomes an
             event with auto-assigned stage + evenly-spread
             arc_position.
          3. Empty list — fine, the planner just shows no beats.

        For (2), strings shaped ``"opening: where + who"`` get split
        on the first colon: head ("opening") becomes the event title,
        body becomes the description. That matches the convention the
        plot AI is encouraged to use in its scene_list.
        """
        from src.models.project import StoryEvent

        out = []
        # Path 1: explicit events list.
        if isinstance(explicit_events, list) and explicit_events:
            n = len(explicit_events)
            for i, ev in enumerate(explicit_events):
                if isinstance(ev, str):
                    text, desc = ev.strip(), ''
                elif isinstance(ev, dict):
                    text = (ev.get('text') or ev.get('title')
                            or '').strip()
                    desc = (ev.get('description') or '').strip()
                else:
                    continue
                if not text and not desc:
                    continue
                # Stage + arc position: AI may have provided them;
                # otherwise auto-derive from order.
                stage = ''
                arc_pos = -1
                if isinstance(ev, dict):
                    stage_in = (
                        ev.get('stage') or '').strip().lower()
                    if stage_in in (
                            'exposition', 'rising', 'climax',
                            'falling', 'resolution'):
                        stage = stage_in
                    try:
                        arc_pos = max(0, min(
                            100, int(ev.get('arc_position', -1))))
                    except Exception:
                        arc_pos = -1
                if not stage:
                    stage = self._stage_for_arc_position(i, n)
                if arc_pos < 0:
                    arc_pos = self._arc_position_for_index(i, n)
                out.append(StoryEvent(
                    id=f"{chapter_id}_event_{i}",
                    text=text or "(untitled beat)",
                    description=desc,
                    stage=stage,
                    arc_position=arc_pos,
                    order=i,
                ))
            return out

        # Path 2: derived from scene_list.
        if scene_list:
            n = len(scene_list)
            for i, scene in enumerate(scene_list):
                # Split "opening: where + who" → text="opening",
                # description="where + who". Falls through cleanly
                # for scenes with no colon — whole string is text.
                if ':' in scene:
                    head, body = scene.split(':', 1)
                    text = head.strip() or "(untitled beat)"
                    description = body.strip()
                else:
                    text = scene.strip() or "(untitled beat)"
                    description = ''
                out.append(StoryEvent(
                    id=f"{chapter_id}_event_{i}",
                    text=text,
                    description=description,
                    stage=self._stage_for_arc_position(i, n),
                    arc_position=self._arc_position_for_index(i, n),
                    order=i,
                ))
        return out

    def _create_chapter_from_json(self, data: dict) -> tuple:
        """Create a chapter from JSON data.

        Captures the full ChapterPlanning model when the AI provides
        plot-plan fields (scene_list, themes, characters_featured,
        tone, voice, pacing, locations, timeline_position) — not
        just title + description. The plot AI uses this to spawn
        chapters that are born with structure during a plot
        discussion (e.g. "next we need a chapter where Marcus
        confronts Lena at the Glassworks; here's the scene-by-
        scene plan").

        Also derives ``ChapterPlanning.events`` (the structured
        StoryEvent list the chapter planner UI renders on the
        visual arc) from either:
          • an explicit ``events`` list in the JSON, or
          • the ``scene_list`` (auto-derived: each scene becomes a
            StoryEvent with a heuristic stage and an arc_position
            spread evenly 0-100 across the chapter).
        That way every AI-spawned chapter shows up in the planner
        with arc-positioned beats the user can tweak — not just a
        flat scene-list of strings.

        Args:
            data: Dictionary with chapter + chapter-planning fields.
                Accepts both ``description`` and ``synopsis`` (alias),
                lists or single strings for any list field, and
                ignores unknown keys.

        Returns:
            Tuple of (element_type, element_name) or None.
        """
        from datetime import datetime
        from src.models.project import ChapterPlanning, StoryEvent

        title = data.get('title', '').strip()
        if not title:
            return None

        # Generate unique ID and chapter number
        next_number = len(self.current_project.manuscript.chapters) + 1
        chapter_id = f"chapter_{datetime.now().strftime('%Y%m%d%H%M%S')}_{next_number}"

        # Coerce list-or-str into list[str]; drop empties.
        def _as_str_list(value):
            if value is None or value == "":
                return []
            if isinstance(value, list):
                return [str(v).strip() for v in value
                        if str(v).strip()]
            return [s.strip() for s in str(value).splitlines()
                    if s.strip()]

        # ``synopsis`` is what the plot AI emits; fall back to
        # ``description`` for the General Assistant convention. If
        # the AI also gave a ``goal`` (one-line "what the chapter
        # accomplishes"), fold it into the description so the
        # planner pane reads naturally.
        description = (data.get('description')
                       or data.get('synopsis') or '').strip()
        goal = (data.get('goal') or '').strip()
        if goal:
            description = (
                f"{description}\n\nGoal: {goal}".strip()
                if description else f"Goal: {goal}")

        # Build the event list the chapter planner displays on its
        # arc visual. Prefer explicit ``events`` (richer), fall
        # back to deriving from ``scene_list``.
        scene_list = _as_str_list(data.get('scene_list'))
        events = self._build_chapter_planner_events(
            data.get('events'), scene_list, chapter_id)

        planning = ChapterPlanning(
            description=description,
            outline=(data.get('outline') or '').strip(),
            pov_character=(data.get('pov_character') or '').strip(),
            scene_list=scene_list,
            events=events,
            characters_featured=_as_str_list(
                data.get('characters_featured')),
            locations=_as_str_list(data.get('locations')),
            themes=_as_str_list(data.get('themes')),
            tone=(data.get('tone') or '').strip(),
            voice=(data.get('voice') or '').strip(),
            style=(data.get('style') or '').strip(),
            pacing=(data.get('pacing') or '').strip(),
            timeline_position=(
                data.get('timeline_position') or '').strip(),
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
        # Surface what landed so it's clear in the console which
        # plot-plan fields the AI provided vs which were defaulted.
        filled = sum(1 for v in (
            planning.description, planning.scene_list,
            planning.themes, planning.characters_featured,
            planning.locations, planning.tone, planning.voice,
            planning.style, planning.pacing,
            planning.pov_character) if v)
        print(f"Created chapter: {title} (Chapter {next_number}) "
              f"with {filled} plan field(s) populated")

        # Refresh manuscript editor to show the new chapter
        if hasattr(self, 'manuscript_editor'):
            self.manuscript_editor.load_manuscript(self.current_project.manuscript)

        return ('chapter', f"{next_number}. {title}")

    # ── Plot-native creators ─────────────────────────────────────
    # The plot AI (and the General Assistant in plot mode) can now
    # propose new plot events / subplots / promises / tensions via
    # ``<suggest_*>`` or ``<create_*>`` blocks. Each handler appends
    # the new element to ``current_project.story_planning`` and
    # refreshes the StoryPlanningWidget so the new entry shows up
    # in the relevant sub-tab without requiring a project reload.

    def _refresh_story_planning_after_create(self) -> None:
        """Push the in-memory story_planning back into the widget so
        the user sees the new element appear immediately."""
        try:
            if hasattr(self, 'story_planning_widget'):
                self.story_planning_widget.load_data(
                    self.current_project.story_planning)
        except Exception as e:
            print(f"[creation] story_planning refresh failed: {e}")

    def _create_plot_event_from_json(self, data: dict) -> tuple:
        """Create a PlotEvent (Freytag pyramid beat) from JSON data."""
        from datetime import datetime
        from src.models.project import PlotEvent
        title = (data.get('title') or '').strip()
        if not title:
            return None
        stage = (data.get('stage') or 'rising_action').lower()
        valid_stages = (
            'exposition', 'rising_action', 'climax',
            'falling_action', 'resolution')
        if stage not in valid_stages:
            stage = 'rising_action'
        try:
            act = int(data.get('act', 1))
        except Exception:
            act = 1
        try:
            intensity = max(0, min(100, int(data.get('intensity', 50))))
        except Exception:
            intensity = 50
        related = data.get('related_characters') or []
        if not isinstance(related, list):
            related = [str(related)]
        ev = PlotEvent(
            id=f"event_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            title=title,
            description=data.get('description', '') or '',
            outcome=data.get('outcome', '') or '',
            stage=stage,
            act=act,
            intensity=intensity,
            related_characters=[str(r) for r in related],
            notes=data.get('notes', '') or '',
        )
        self.current_project.story_planning.freytag_pyramid.events.append(ev)
        print(f"Created plot event: {title} (act {act}, "
              f"stage={stage}, intensity={intensity})")
        self._refresh_story_planning_after_create()
        return ('plot_event', title)

    def _create_subplot_from_json(self, data: dict) -> tuple:
        """Create a Subplot from JSON data."""
        from datetime import datetime
        from src.models.project import Subplot
        title = (data.get('title') or '').strip()
        if not title:
            return None
        related = data.get('related_characters') or []
        if not isinstance(related, list):
            related = [str(related)]
        sp = Subplot(
            id=f"subplot_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            title=title,
            description=data.get('description', '') or '',
            connection_to_main=data.get('connection_to_main', '')
                                or '',
            related_characters=[str(r) for r in related],
            status=(data.get('status') or 'active').lower(),
        )
        self.current_project.story_planning.subplots.append(sp)
        print(f"Created subplot: {title}")
        self._refresh_story_planning_after_create()
        return ('subplot', title)

    def _create_promise_from_json(self, data: dict) -> tuple:
        """Create a StoryPromise from JSON data."""
        from datetime import datetime
        from src.models.project import StoryPromise
        title = (data.get('title') or '').strip()
        if not title:
            return None
        ptype = (data.get('promise_type') or 'plot').lower()
        if ptype not in ('tone', 'plot', 'genre', 'character'):
            ptype = 'plot'
        related = data.get('related_characters') or []
        if not isinstance(related, list):
            related = [str(related)]
        promise = StoryPromise(
            id=f"promise_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            promise_type=ptype,
            title=title,
            description=data.get('description', '') or '',
            related_characters=[str(r) for r in related],
        )
        self.current_project.story_planning.promises.append(promise)
        print(f"Created promise: [{ptype}] {title}")
        self._refresh_story_planning_after_create()
        return ('promise', title)

    def _create_tension_from_json(self, data: dict) -> tuple:
        """Create a CharacterTension from JSON data."""
        from datetime import datetime
        from src.models.project import CharacterTension
        title = (data.get('title') or '').strip()
        if not title:
            return None
        ttype = (data.get('tension_type') or 'interpersonal').lower()
        if ttype not in ('internal', 'interpersonal',
                          'societal', 'cosmic'):
            ttype = 'interpersonal'
        state = (data.get('current_state') or 'rising').lower()
        if state not in ('rising', 'stable', 'escalating',
                          'resolving', 'unresolved', 'resolved'):
            state = 'rising'
        try:
            intensity = max(0, min(100, int(data.get('intensity', 50))))
        except Exception:
            intensity = 50
        chars = data.get('characters_involved') or []
        if not isinstance(chars, list):
            chars = [str(chars)]
        t = CharacterTension(
            id=f"tension_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            title=title,
            description=data.get('description', '') or '',
            tension_type=ttype,
            characters_involved=[str(c) for c in chars],
            stakes=data.get('stakes', '') or '',
            current_state=state,
            intensity=intensity,
        )
        self.current_project.story_planning.tensions.append(t)
        print(f"Created tension: [{ttype}] {title} "
              f"(state={state}, intensity={intensity})")
        self._refresh_story_planning_after_create()
        return ('tension', title)

    def _create_theme_from_json(self, data: dict) -> tuple:
        """Create a Theme (rich, structured) from JSON data."""
        from datetime import datetime
        from src.models.project import Theme
        title = (data.get('title') or '').strip()
        if not title:
            return None
        motifs = data.get('motifs') or []
        if not isinstance(motifs, list):
            motifs = [str(motifs)]
        related_chars = data.get('related_characters') or []
        if not isinstance(related_chars, list):
            related_chars = [str(related_chars)]
        related_subs = data.get('related_subplots') or []
        if not isinstance(related_subs, list):
            related_subs = [str(related_subs)]
        th = Theme(
            id=f"theme_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            title=title,
            statement=data.get('statement', '') or '',
            description=data.get('description', '') or '',
            motifs=[str(m) for m in motifs if str(m).strip()],
            related_characters=[str(c) for c in related_chars
                                 if str(c).strip()],
            related_subplots=[str(s) for s in related_subs
                              if str(s).strip()],
        )
        self.current_project.story_planning.theme_details.append(th)
        print(f"Created theme: {title}")
        self._refresh_story_planning_after_create()
        return ('theme', title)

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

    def _export_audio_book(self):
        """Export chapters as audio files."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.information(self, "No Content", "No chapters to export.")
            return

        # Sync current editor content to the chapter model so export
        # gets the latest text (not stale from last save/load)
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            try:
                self.manuscript_editor.current_chapter_editor.save_to_model()
            except Exception:
                pass

        # Ensure every chapter has content loaded from disk
        project_dir = Path(self.current_project.project_path).parent
        for ch in self.current_project.manuscript.chapters:
            if not ch.content or not ch.content.strip():
                try:
                    ch.load_content_from_file(project_dir)
                except Exception:
                    pass

        # Determine current chapter index
        current_idx = -1
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            current_ch = self.manuscript_editor.current_chapter_editor.chapter
            for i, ch in enumerate(self.current_project.manuscript.chapters):
                if ch.id == current_ch.id:
                    current_idx = i
                    break

        from src.ui.export_audio_dialog import ExportAudioDialog
        dialog = ExportAudioDialog(
            self.current_project.manuscript.chapters,
            current_chapter_idx=current_idx,
            parent=self
        )
        dialog.exec()

    # ── Manuscript Drafts ─────────────────────────────────────────

    def _sync_editor_to_manuscript(self):
        """Push any unsaved editor content to the in-memory chapter model."""
        if hasattr(self, 'manuscript_editor') and self.manuscript_editor.current_chapter_editor:
            try:
                self.manuscript_editor.current_chapter_editor.save_to_model()
            except Exception:
                pass

    def _save_current_as_draft(self):
        """Snapshot the current manuscript into a new ManuscriptDraft."""
        if not self.current_project:
            QMessageBox.information(self, "No Project", "Open a project first.")
            return
        if not self.current_project.manuscript.chapters:
            QMessageBox.information(self, "No Chapters",
                                    "Write some chapters before saving a draft.")
            return

        # Sync any pending editor content into chapters
        self._sync_editor_to_manuscript()

        from PyQt6.QtWidgets import QInputDialog
        existing_count = len(self.current_project.drafts)
        default_name = f"Draft {existing_count + 1}"
        name, ok = QInputDialog.getText(
            self, "New Draft", "Name this draft:", text=default_name)
        if not ok or not name.strip():
            return

        draft = self.current_project.create_draft_from_current(
            name=name.strip())
        QMessageBox.information(
            self, "Draft Created",
            f"Created draft '{draft.name}' with {len(draft.chapters)} chapters.\n\n"
            f"Open it via Drafts > Open Draft in New Window...")

        # Persist immediately so the user doesn't lose the snapshot
        try:
            self.current_project.save_project(self.current_project.project_path)
        except Exception as e:
            print(f"[Drafts] Save after create_draft failed: {e}")

    def _open_draft_window(self):
        """Open a secondary editor pointed at a draft of the user's choosing."""
        if not self.current_project:
            QMessageBox.information(self, "No Project", "Open a project first.")
            return
        if not self.current_project.drafts:
            QMessageBox.information(
                self, "No Drafts",
                "There are no drafts yet. Use 'Save Current Manuscript as "
                "New Draft...' to create one first.")
            return

        # Let the user pick which draft to open
        from PyQt6.QtWidgets import QInputDialog
        names = [d.name for d in self.current_project.drafts]
        choice, ok = QInputDialog.getItem(
            self, "Open Draft", "Pick a draft to open:", names, 0, False)
        if not ok:
            return
        draft = next((d for d in self.current_project.drafts
                      if d.name == choice), None)
        if not draft:
            return

        from src.ui.draft_editor_window import DraftEditorWindow
        # Track open windows so they aren't garbage-collected
        if not hasattr(self, '_draft_windows'):
            self._draft_windows = []
        win = DraftEditorWindow(self.current_project,
                                initial_draft_id=draft.id, parent=self)
        # Persist edits when the user saves in the secondary window
        win.draft_saved.connect(lambda _id: self._on_draft_saved())
        win.destroyed.connect(lambda: self._draft_windows.remove(win)
                              if win in self._draft_windows else None)
        self._draft_windows.append(win)
        win.show()

    def _on_draft_saved(self):
        """Persist the project after a draft window saves changes."""
        if self.current_project and self.current_project.project_path:
            try:
                self.current_project.save_project(self.current_project.project_path)
            except Exception as e:
                print(f"[Drafts] Save failed: {e}")

    def _create_checkpoint_draft(self):
        """Open the paragraph-by-paragraph checkpoint reviewer for a
        chosen chapter. The dialog produces a new ManuscriptDraft
        from kept/edited paragraphs; rejected paragraphs are dropped.

        Flow:
          1. Pick which chapter to review (defaults to current).
          2. Open ``CheckpointManifestDialog`` with the chapter's
             content + a reference to the project's ``AgentSuite``
             so the per-paragraph "Ask AI" button works.
          3. On accept, deep-copy the manuscript via
             ``create_draft_from_current`` and overwrite the
             chosen chapter's content with the joined-paragraph
             output. Other chapters carry over unchanged so the
             draft stays a complete manuscript.
        """
        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open a project first.")
            return
        chapters = (self.current_project.manuscript.chapters
                    if self.current_project.manuscript else [])
        if not chapters:
            QMessageBox.information(
                self, "No Chapters",
                "This project has no chapters yet — add one before "
                "creating a checkpoint draft.")
            return

        # Pick a chapter. Default to the currently-loaded chapter
        # in the editor when there is one.
        from PyQt6.QtWidgets import QInputDialog
        labels = [
            f"Ch {ch.number}: {ch.title or '(untitled)'} "
            f"({len(ch.content or '')} chars)"
            for ch in chapters]
        # Try to default to whatever the editor is showing.
        default_idx = 0
        try:
            current = getattr(self, "current_chapter", None)
            if current is not None:
                for i, ch in enumerate(chapters):
                    if ch.id == current.id:
                        default_idx = i
                        break
        except Exception:
            pass
        choice, ok = QInputDialog.getItem(
            self, "Pick a chapter to review",
            "Walk this chapter paragraph-by-paragraph:",
            labels, default_idx, False)
        if not ok:
            return
        chapter = chapters[labels.index(choice)]
        chapter_text = chapter.content or ""
        if not chapter_text.strip():
            # Try lazy-load from disk if the chapter is folder-backed
            # but its in-memory content is empty.
            try:
                from pathlib import Path as _P
                project_dir = (_P(self.current_project.project_path).parent
                               if self.current_project.project_path
                               else None)
                if project_dir:
                    chapter.load_content_from_file(project_dir)
                    chapter_text = chapter.content or ""
            except Exception:
                pass
        if not chapter_text.strip():
            QMessageBox.information(
                self, "Empty Chapter",
                f"Chapter '{chapter.title}' has no content to "
                f"review.")
            return

        # Resolve the project's genre so the AI suggestions stay
        # in register.
        genre = ""
        try:
            genre = (getattr(self.current_project, "prose_profile", None)
                     and getattr(
                         self.current_project.prose_profile, "genre", "")
                     or "")
        except Exception:
            pass

        from src.ui.checkpoint_manifest_dialog import (
            CheckpointManifestDialog,
        )
        dlg = CheckpointManifestDialog(
            chapter_text,
            agent_suite=getattr(self, "agent_suite", None),
            source_label=f"Ch {chapter.number}: {chapter.title}",
            genre=genre,
            parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        accepted = dlg.accepted_text() or ""
        if not accepted.strip():
            return
        draft_name = dlg.draft_name() or (
            f"Checkpoint of Ch{chapter.number}")
        description = dlg.draft_description() or ""

        # Snapshot the manuscript into a new draft, then overwrite
        # the reviewed chapter's content with the kept text. Other
        # chapters in the draft carry their original content.
        try:
            draft = self.current_project.create_draft_from_current(
                name=draft_name,
                description=description)
        except Exception as e:
            QMessageBox.warning(
                self, "Draft creation failed", str(e))
            return
        # Find the cloned chapter by number (its id is fresh after
        # the deep copy).
        target = next((c for c in draft.chapters
                       if c.number == chapter.number), None)
        if target is None:
            QMessageBox.warning(
                self, "Draft creation incomplete",
                "Couldn't locate the reviewed chapter inside the "
                "new draft. The draft was created but the kept "
                "paragraphs were not applied.")
            return
        target.content = accepted
        # If the chapter has revisions, the active one's content
        # should match the chapter content too.
        try:
            for rev in target.revisions:
                if rev.revision_number == target.active_revision_number:
                    rev.content = accepted
                    break
        except Exception:
            pass

        # Persist + tell the user what landed where.
        try:
            self.current_project.save_project()
        except Exception:
            pass
        QMessageBox.information(
            self, "Checkpoint draft created",
            f"Draft <b>{draft_name}</b> created with the kept "
            f"paragraphs of Ch {chapter.number}. Open it via "
            f"Drafts → Open Draft in New Window.")

    def _manage_drafts(self):
        """Show a simple list/manage dialog for drafts (rename, delete)."""
        if not self.current_project:
            QMessageBox.information(self, "No Project", "Open a project first.")
            return
        if not self.current_project.drafts:
            QMessageBox.information(self, "No Drafts",
                                    "No drafts to manage yet.")
            return

        from PyQt6.QtWidgets import QInputDialog
        choices = [f"{d.name} ({len(d.chapters)} chapters)"
                   for d in self.current_project.drafts]
        choices.append("(cancel)")
        choice, ok = QInputDialog.getItem(
            self, "Manage Drafts",
            "Select a draft to delete (rename via Open Draft window):",
            choices, 0, False)
        if not ok or choice == "(cancel)":
            return
        idx = choices.index(choice)
        if idx >= len(self.current_project.drafts):
            return
        draft = self.current_project.drafts[idx]
        confirm = QMessageBox.question(
            self, "Delete Draft?",
            f"Delete draft '{draft.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self.current_project.delete_draft(draft.id)
            self._on_draft_saved()
            QMessageBox.information(self, "Deleted",
                                    f"Draft '{draft.name}' removed.")

    def _toggle_debug_panel(self, checked: bool):
        """Toggle the AI debug panel."""
        if checked:
            if not self._ai_debug_panel:
                from src.ui.ai_debug_panel import AIDebugPanel
                self._ai_debug_panel = AIDebugPanel(self)
                self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._ai_debug_panel)
            self._ai_debug_panel.show()
        else:
            if self._ai_debug_panel:
                self._ai_debug_panel.hide()

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.settings, self)
        # Pass current project so knowledge base can download project-specific articles
        if hasattr(dialog, 'knowledge_widget') and self.current_project:
            dialog.knowledge_widget.set_project(self.current_project)
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
            # Stop speech-to-text and unload model
            try:
                stt = get_stt_service()
                stt.shutdown()
            except Exception:
                pass

            # Stop text-to-speech
            try:
                from src.services.tts_service import get_tts_service
                tts = get_tts_service()
                tts.stop()
            except Exception:
                pass

            # Hide tray icon before closing
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
            # Close all secondary windows
            self.window_manager.close_all_secondary_windows()
            event.accept()
