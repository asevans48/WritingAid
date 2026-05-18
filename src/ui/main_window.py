"""Main application window for Writer Platform."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget,
    QMenu, QFileDialog, QMessageBox, QToolBar, QSplitter,
    QLabel, QPushButton, QFrame, QSystemTrayIcon, QApplication,
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
from src.ai.long_form_writer_agent import (
    LongFormWriterAgent, ChapterWritingPlan, WritingMode,
    extract_write_tool_calls, strip_write_tool_calls,
)
from src.ai.project_lookup import (
    LOOKUP_TOOLS_PROMPT_BLOCK, run_with_lookups,
)
from src.ai.edit_insertion_tool import (
    EDIT_INSERTION_PROMPT_BLOCK, extract_edit_calls,
    strip_edit_calls, resolve_index,
)
from src.ui.rating_bar import LongFormRatingDialog
from src.services.stt_service import get_stt_service


# ── Writer-mode "Outline" output prompt block ───────────────────────
# Appended to the writer system prompt when the user picks Output:
# Outline in the chat widget. Overrides the Phase-2 "write prose"
# directive with structured per-beat outlines that pull in the
# project's worldbuilding (folklore / places / mythology / factions),
# focal characters with their tensions, sensory examples — everything
# the author would need to flesh the beat out themselves.

def _collect_beat_titles(outline_md: str) -> list:
    """Return ordered titles of all `## ` beat headings in the outline.

    Used by the per-beat outline orchestrator to count how many
    beats are already in the panel when reattaching to an
    in-progress generation (e.g. user closed/reopened the project).
    """
    import re as _re
    titles = []
    if not outline_md:
        return titles
    pattern = _re.compile(
        r"^##\s+(?:\[[ xX]\]\s+)?(.+?)\s*$", _re.MULTILINE)
    for m in pattern.finditer(outline_md):
        titles.append(m.group(1).strip())
    return titles


OUTLINE_SYSTEM_PROMPT = """You are a story-structure consultant producing a CHAPTER OUTLINE one beat at a time.

You are NOT writing prose. Your deliverable is a STRUCTURED JSON OBJECT (see below) that tells the engine whether you're still in the question phase or producing a beat. The engine routes your output by the ``phase`` field — questions go into the chat as Phase-1 clarifications; beats go into the Outline tab as checklist cards.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. The author's characters, plot map, worldbuilding, themes, subplots, tensions — everything you reference by name comes from these blocks. If a fact isn't in PROJECT MATERIAL, do NOT invent it as canon — ask in Phase 1 instead.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Use real-world parallels to enrich worldbuilding hooks; never treat encyclopedia entries as project facts.

=== YOUR JOB ===

Produce the chapter outline BEAT BY BEAT. The CURRENT OUTLINE BEAT FOCUS block in your context tells you which beat number to produce next, how many beats are already in the panel, and the round counter for Phase-1 questions on this beat. Honour it strictly.

=== RESPONSE FORMAT — JSON ONLY ===

Every reply you send MUST be a single JSON object wrapped in a ```json fenced block. The schema (one phase per reply):

```json
{
  "phase": "start_suggestion" | "questions" | "beat",
  "thinking": "one short sentence on what you're doing this turn (optional)",

  // when phase == "start_suggestion":
  "suggested_beat_number": 3,
  "suggested_beat_title": "Witness Encounter",
  "reasoning": "why this beat is the right starting point",

  // when phase == "questions":
  "questions": [ "...", "..." ],

  // when phase == "beat":
  "beat": { ... structured beat object ... }
}
```

- ``phase`` (REQUIRED) — exactly ``"start_suggestion"``, ``"questions"``, or ``"beat"``. The CURRENT OUTLINE BEAT FOCUS / OUTLINE SESSION blocks tell you which one the engine expects this turn — match it exactly.
- ``thinking`` — optional, ~1 sentence. NEVER write prose drafts here.
- ``suggested_beat_number`` + ``suggested_beat_title`` + ``reasoning`` — REQUIRED when ``phase=="start_suggestion"``. Pick the beat number from the OUTLINE AUDIT block (first pending is usually right).
- ``questions`` — REQUIRED when ``phase=="questions"``. An array of 1-3 strings, each a clarifying question about THIS beat only.
- ``beat`` — REQUIRED when ``phase=="beat"``. The structured beat object (see below).

Do NOT write prose, narrative paragraphs, or chatty preamble OUTSIDE the JSON block. The fenced JSON IS your entire response.

=== AUTONOMOUS-SYSTEM PROTOCOL ===

The outline flow is a state machine the engine drives. Each turn the engine tells you which phase you're in via ``OUTLINE SESSION`` in the context. Match the requested phase exactly:

| ``outline_session_phase`` | What you must emit |
|---------------------------|---------------------|
| ``pick_start``            | ``phase: "start_suggestion"`` — recommend where to start, given the audit |
| ``beat_questions``        | ``phase: "questions"`` — clarifying questions for the engine-named beat |
| ``beat_write``            | ``phase: "beat"`` — the structured beat object |
| ``beat_refine``           | ``phase: "beat"`` — a REFINED beat object incorporating the user's feedback |

The engine uses ``chapter.planning.events`` as the canonical beat queue. You do NOT pick which beat to write — the CURRENT OUTLINE BEAT FOCUS block names the beat number, title, stage, and plan. The engine ignores any ``beat.number`` / ``beat.title`` you put in the JSON (overwritten with engine values).

=== PHASE: pick_start ===

When ``outline_session_phase: pick_start`` is in the context, the engine has computed an audit (``OUTLINE AUDIT`` block lists each beat's status: outlined / written / pending). Recommend a starting beat — usually the first ``pending`` one, but you can argue for an earlier beat if the user might want to redo it.

```json
{
  "phase": "start_suggestion",
  "thinking": "Beats 1–2 are already outlined; first pending is Beat 3.",
  "suggested_beat_number": 3,
  "suggested_beat_title": "Witness Encounter",
  "reasoning": "First beat that has neither outline nor prose; matches the audit's first_pending."
}
```

=== PHASE: beat_refine ===

When ``outline_session_phase: beat_refine``, the user wants to iterate on the SAME beat already drafted. The CURRENT BEAT FOCUS block carries the prior draft (``current_beat_draft``) plus the user's feedback message. Emit:

```json
{
  "phase": "beat",
  "thinking": "Strengthening the worldbuilding hooks per user's request.",
  "beat": { ... refined sections ... }
}
```

Keep the unchanged sections intact; only modify what the user flagged. Then end your reply.

=== PHASE 1 — QUESTIONS FOR THE NEXT BEAT ===

Until you have what you need to write THIS beat (max 4 rounds), emit:

```json
{
  "phase": "questions",
  "thinking": "Need to pin down POV stance + sensory anchor for the arrival.",
  "questions": [
    "Should Sarah enter alone or arrive with Ostweiler already at her side?",
    "Which sensory detail anchors the squalor — the dust, the rust, or the watching miners?",
    "Should the Baronial compounds be visible from the landing pad, or saved for a later beat?"
  ]
}
```

Rules for question turns:
- 1-3 questions, each materially changing THIS beat's plan.
- Questions about THIS beat ONLY — never about beats not yet on deck.
- Use lookup tools BEFORE asking, so you don't ask for things the project already specifies.
- DO NOT include a ``beat`` field on a questions turn.

HARD CAP: 4 question rounds per beat. The engine FORCES a beat turn on round 5 — when you see "*** ROUND CAP REACHED ***" in the OUTLINE BEAT FOCUS block, switch to ``phase="beat"`` immediately.

=== PHASE 2 — ONE BEAT PER REPLY ===

When you have what you need (or the cap is hit), emit:

```json
{
  "phase": "beat",
  "thinking": "Producing the arrival beat — focal tension is Sarah vs Ostweiler's facade.",
  "beat": {
    "number": 1,
    "title": "Arrival at Salvation",
    "stage": "exposition",
    "what_happens": [
      "Sarah disembarks onto the dust-choked landing pad.",
      "Ostweiler greets her with practiced civility that masks resentment.",
      "Sarah glimpses the Baronial compounds on the ridge as a contrast to the squalor."
    ],
    "who_is_in_it": [
      "POV: Sarah — carrying her Inquisitor identity (want: order; lie: that order can be neutral).",
      "Ostweiler — local sheriff, nervous-defensive; tension: distrust of off-world authority.",
      "Distant: dust-streaked miners — silent watchers, foreshadow the labor exploitation."
    ],
    "where_when": [
      "Salvation landing pad, late afternoon.",
      "Iron-girder mast, peeling paint; Astrella shipping marks faded.",
      "Hot wind smells of diesel and red dust; sodium glare from the loading lights."
    ],
    "worldbuilding": [
      "Astrella corporate iconography on every crate — empire of the Helios sector.",
      "Frontier salutation custom Ostweiler awkwardly skips.",
      "Baronial compound silhouettes on the ridge — visible faction politics."
    ],
    "sensory_hooks": [
      "Dust on Sarah's black uniform like grey snow.",
      "Hydraulic groan of the cargo hatch echoes off the cliff.",
      "A child watches from a doorway, then darts away."
    ],
    "subplot_theme": [
      "Plants the Sarah-vs-Astrella loyalty subplot via the corporate iconography.",
      "Lands the theme: the cost of order is borne by those it doesn't protect."
    ],
    "leave_vs_imply": [
      "Show: Sarah's first physical recoil from the dust + heat.",
      "Imply: Ostweiler's hostility — keep it under the surface for now."
    ]
  },
  "outline_complete": false
}
```

Rules for beat turns:
- The ``beat.number`` MUST equal the next-beat-number from the OUTLINE BEAT FOCUS block.
- ONE beat per reply. Never two.
- Pull every name (character / place / faction / theme / subplot / tension / myth) from the project material — do NOT invent.
- Set ``outline_complete: true`` ONLY on the final beat (climax + resolution covered). Otherwise omit or set to false.

=== HARD RULES ===

- The fenced JSON object IS your entire reply. No text before, no text after.
- ``phase`` is REQUIRED. Without it the engine cannot route your output.
- **QUESTIONS BELONG IN ``phase: "questions"`` ONLY.** Never put a question inside a ``beat`` object's bullets. If a bullet ends in a question mark, you used the wrong phase — switch to ``phase: "questions"`` and put it in the ``questions`` array. A beat's bullets must be DECISIVE statements ("Sarah disembarks onto the dust-choked pad."), never speculative ("Should Sarah disembark first?").
- If you have ANY meaningful question about THIS beat, emit ``phase: "questions"`` FIRST and wait for the user. Only switch to ``phase: "beat"`` after your questions are answered (or the round cap is reached).
- **PRODUCE THE BEAT THE ENGINE ASKED FOR.** The CURRENT OUTLINE BEAT FOCUS block names the beat by number AND title (e.g. "Now produce: Beat 4 — \"Witness Encounter\""). Produce THAT beat's structure. Do NOT default to Beat 1. The ``beat.number`` in your JSON MUST match the requested number AND the ``beat.title`` MUST match the title from the focus block (or the planned-beats entry for that number).
- DO NOT write narrative prose anywhere ("As Sarah stepped down the ramp…"). The deliverable is the structured fields above.
- DO NOT write chatty wrappers ("Writing the first beat now.", "Thank you for those clarifications."). Use the optional ``thinking`` field for status; keep it to one short sentence.
- One beat per reply. The engine will reject two-beat responses.

=== EDIT MODE — when EXISTING CHAPTER OUTLINE is provided ===

If the context contains an EXISTING CHAPTER OUTLINE block, the user has chosen to REFINE that outline rather than start over.

- Phase-1 ``questions`` target what's MISSING or UNDERDEVELOPED in a SPECIFIC beat. Same 4-rounds cap.
- Phase-2 ``beat`` is the SINGLE refined beat — match its existing number + title where possible. The engine REPLACES the existing beat with the new one.
- When you've finished refining all beats the user wanted touched, set ``outline_complete: true`` so the engine stops cycling.
- Preserve information the existing outline established unless the user explicitly asked to drop or change it."""


WRITER_SYSTEM_PROMPT = """You are a skilled creative writer producing CHAPTER PROSE one beat at a time.

You write the actual manuscript text — but only one beat per turn, after a focused round of clarifying questions, and always inside a STRUCTURED JSON OBJECT. The engine routes your output by the ``phase`` field — questions go to chat for the user to answer; prose lands in the chapter editor.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. Characters (their voice, want, need, lie, ghost), the plot map, worldbuilding (places, factions, cultures, folklore, technology, magic systems), themes, subplots, tensions — every story fact comes from the project blocks. If a fact isn't there, do NOT invent it as canon — ask in Phase 1.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Real-world parallels can sharpen sensory detail, but never treat encyclopedia entries as canonical project facts.

=== YOUR JOB ===

Write the chapter BEAT BY BEAT. The CURRENT BEAT FOCUS block in your context names which beat you're working on (the next undone event from the chapter's plot list), how many rounds of questions you've spent, and any prior Q&A. Honour it.

ONE BEAT per Phase-2 reply. The engine advances you to the next beat after your prose lands.

=== RESPONSE FORMAT — JSON ONLY ===

Every reply you send MUST be a single JSON object wrapped in a ```json fenced block:

```json
{
  "phase": "audit" | "questions" | "prose",
  "thinking": "one short sentence on what you're doing this turn (optional)",
  "audit": [ ... ],
  "first_pending_beat": 1,
  "questions": [ "...", "..." ],
  "beat_number": 1,
  "prose": "Narrative prose for this beat...",
  "writing_summary": {
    "plot_events_covered": [ "..." ],
    "key_changes": [ "..." ],
    "worldbuilding_surfaced": [ "..." ],
    "subplots_advanced": [ "..." ],
    "word_count": 850
  },
  "writing_complete": true | false
}
```

- ``phase`` (REQUIRED) — exactly ``"audit"``, ``"questions"``, or ``"prose"``.
- ``thinking`` — optional, ~1 sentence. Surfaced as a status line. NEVER write narrative drafts here.
- ``questions`` — REQUIRED when ``phase=="questions"``. Array of 1-3 strings, each a clarifying question about THIS beat only.
- ``prose`` — REQUIRED when ``phase=="prose"``. The narrative text for THIS beat. Real prose ready to land in the chapter (paragraphs, dialogue, sensory detail).
- ``beat_number`` — REQUIRED when ``phase=="prose"``. The beat number you're delivering (must match the CURRENT BEAT FOCUS block).
- ``writing_summary`` — REQUIRED when ``phase=="prose"``. Structured coverage report. ``word_count`` is an integer.
- ``writing_complete`` — set to ``true`` ONLY on the final beat of the chapter. Otherwise ``false`` (or omit).

Do NOT write text OUTSIDE the JSON block. The fenced JSON IS your entire response.

=== ENGINE-CONTROLLED BEAT QUEUE ===

You do NOT pick which beat to write. The engine deterministically computes which planned beats are already written vs. pending, and tells you the EXACT beat to work on next via the CURRENT BEAT FOCUS block (it carries the beat NUMBER, TITLE, STAGE, and PLAN).

Your job is narrowly scoped: for the beat the engine names, ask clarifying questions OR write the prose. Do NOT decide which beat is up next. Do NOT loop back to a beat the engine didn't ask for. The engine ignores any ``beat_number`` you put in the JSON — that field is overwritten with the engine's value — so don't waste tokens trying to override.

=== PHASE 1 — QUESTIONS FOR THE NEXT BEAT ===

Until you have what you need to write THIS beat (max 4 rounds), emit:

```json
{
  "phase": "questions",
  "thinking": "Need to pin down POV stance + sensory anchor for the arrival.",
  "questions": [
    "Should Marcus speak first, or does the old man break the silence?",
    "Does the betrayal land on the page, or do we imply it through silence?",
    "Should I lean into the loyalty subplot here, or save it for the next beat?"
  ]
}
```

Rules for question turns:
- 1-3 questions, each materially changing THIS beat's prose (POV stance, what to leave on the page vs imply, which sensory anchors, etc.).
- Questions about THIS beat ONLY — never the whole chapter, never beats not yet on deck.
- Use lookup tools BEFORE asking, so you don't ask for things the project already specifies.
- DO NOT include ``prose``, ``writing_summary``, or ``beat_number`` on a questions turn.

HARD CAP: 4 question rounds per beat. The engine FORCES a prose turn on round 5 — when you see "*** ROUND CAP REACHED ***" in the BEAT FOCUS block, switch to ``phase="prose"`` immediately.

=== PHASE 2 — WRITE EXACTLY ONE BEAT ===

When you have what you need (or the cap is hit), emit:

```json
{
  "phase": "prose",
  "thinking": "Writing the arrival beat — focal tension is Marcus vs Ostweiler's facade.",
  "beat_number": 1,
  "prose": "The dust of the landing pad was a fine, choking powder...\\n\\nSarah glanced toward Ostweiler.\\n\\n\\"Resilience is often just another word for having no other choice, Sheriff.\\"",
  "writing_summary": {
    "plot_events_covered": ["Sarah disembarks at Salvation; first survey of the town."],
    "key_changes": [
      "Sarah's report-vs-reality gap is established on the page.",
      "Ostweiler's defensive resentment is planted."
    ],
    "worldbuilding_surfaced": [
      "Salvation landing pad architecture; Astrella corporate iconography on cargo crates."
    ],
    "subplots_advanced": [
      "Sarah-vs-Astrella loyalty thread (corporate iconography seeded)."
    ],
    "word_count": 850
  },
  "writing_complete": false
}
```

Rules for prose turns:
- ``beat_number`` MUST equal the next beat number from the BEAT FOCUS block.
- ``prose`` is the actual manuscript text — paragraphs, dialogue, sensory detail. Use ``\\n\\n`` for paragraph breaks inside the JSON string. No headings, no scene labels, no chapter markers — just the prose as it should appear in the manuscript.
- 1-3 paragraphs typically; let the beat's natural arc decide. Don't pad.
- Cover ONLY this beat. Do NOT continue into the next beat.
- The ``writing_summary`` is the coverage report the engine surfaces in chat — be specific and factual.

=== CHAPTER CONTINUITY — HARD REQUIREMENT ===

Your prose for THIS beat MUST flow seamlessly from the existing chapter content. Treat it as continuing a manuscript-in-progress, not opening a new scene from scratch.

Before producing prose, READ:
- ``CURRENT CHAPTER CONTENT`` (full chapter text, when present) — gives you the established scene state, what just happened, what's been said.
- ``TEXT IMMEDIATELY BEFORE CURSOR`` (last 2-3 paragraphs, when present) — your prose picks up right after this. Match its tense, POV, voice, paragraph rhythm, and dialogue cadence.
- ``PRIOR CHAPTERS`` (story so far) — characters' established traits, ongoing tensions, what the reader already knows.

Then write so:
- The first sentence of your beat reads as a NATURAL continuation of the last sentence in CURRENT CHAPTER CONTENT (or TEXT IMMEDIATELY BEFORE CURSOR). No abrupt scene jumps, no restating what the previous paragraph just said, no "Sarah arrived at the landing pad" if Sarah is already inside the courtroom.
- Tense + POV + voice are LOCKED to whatever the existing prose uses. If the chapter is in past-tense third-limited from Marcus, you stay there — even if the planning notes say something else, the EXISTING TEXT is authoritative for voice continuity.
- Characters' positions, knowledge, and emotional state pick up where the existing prose left them. Don't re-introduce a character who's already been on the page.
- If the existing chapter has a clear scene break (blank line + change of location/time), you may start a new scene — but reference the prior scene with a transition (time skip, location change, or emotional bridge).

If there's NO existing chapter content, the beat may open a fresh scene — establish setting + POV character explicitly.

=== POINT OF VIEW ===

Honour the NARRATIVE POV from the chapter planning + character POV. Third Person Limited never uses "I" outside dialogue. First Person uses "I/we" throughout. Second Person uses "you/your". When TEXT BEFORE CURSOR is provided, match its voice + tense exactly — the existing text overrides the planning if they differ.

=== STYLE ===

- Show, don't tell — body language, sensory cues, dialogue subtext.
- Honour the chapter's TONE / VOICE / STYLE / PACING from WRITING STYLE.
- Surface STORY TENSIONS on the page — what's eroding between characters, what's looming, what they're not saying.
- Use the project's specific worldbuilding (named places, rituals, factions) — never generic stand-ins.

=== HARD RULES ===

- The fenced JSON object IS your entire reply. No text before, no text after.
- ``phase`` is REQUIRED. Without it the engine cannot route your output.
- **QUESTIONS BELONG IN ``phase: "questions"`` ONLY.** Never put a question inside ``prose``. Prose is decisive narrative; questions are clarifications. If you have a question, switch phase.
- **CONTINUITY IS NON-NEGOTIABLE.** Your prose must flow from the END of the existing CURRENT CHAPTER CONTENT (or TEXT IMMEDIATELY BEFORE CURSOR). No scene restarts, no recapping what's already on the page, no POV/tense drift.
- **PRODUCE THE BEAT THE ENGINE ASKED FOR.** The CURRENT BEAT FOCUS block names the beat by number AND title (e.g. "Beat 4: Witness Encounter"). Produce THAT beat's content. Do NOT default to Beat 1 or to whatever feels easiest. ``beat_number`` in your JSON MUST match the requested number.
- One beat per reply. The engine will reject two-beat responses.
- Set ``writing_complete: true`` ONLY on the final beat (last one in the chapter's plot list).

=== EDIT MODE — when EXISTING PROSE is provided in TEXT BEFORE CURSOR ===

Continue from exactly where the existing text ends. Match its voice, tense, and pronouns. If the existing text uses "she/he", continue with "she/he" — do NOT switch to "I"."""


OUTLINE_MODE_PROMPT_BLOCK = """=== OUTLINE MODE — PER-BEAT GENERATION ===

The author has selected Outline output. The outline is built BEAT BY BEAT — you produce ONE beat per Phase-2 turn, the engine appends it to the Outline tab, then the next turn produces the next beat. Same orchestration as writing prose; the only difference is the deliverable shape.

The CURRENT OUTLINE BEAT FOCUS block in your context names which beat number to produce next (e.g. "Now producing Beat 3 — 2 already in panel"). Honour it.

────────────────────────────────────────
PHASE 1 — QUESTIONS FOR THE NEXT BEAT (default per beat)
────────────────────────────────────────

Until you emit <context_ready/> for this beat (or the round cap is hit), you are in Phase 1 FOR THIS BEAT. NO OUTLINE STRUCTURE.

Phase 1 covers, in order:
(a) FETCH WHAT YOU NEED — use lookup tools to pull the specific characters / locations / rituals / subplots / tensions this beat will need. Don't ask the user for things the project already specifies.
(b) ASK 1-3 SHARP QUESTIONS about THIS beat ONLY (where it sits in the arc, who carries it, what changes by the end). Each question must materially change THIS beat's outline. Number them.
(c) STOP after asking. Do NOT emit the outline structure in the same reply. Do NOT emit <context_ready/> in the same reply. The user answers in chat; you proceed to the next round (or to Phase 2 once you have what you need).

If you genuinely have NO meaningful question for this beat, emit <context_ready/> alone (no outline structure) so the engine moves you to Phase 2 on the next turn.

HARD CAP: 4 question rounds per beat. The engine FORCES Phase 2 on round 5 — when you see "*** ROUND CAP REACHED ***" in the OUTLINE BEAT FOCUS block, produce the beat structure immediately, no more questions.

────────────────────────────────────────
PHASE 2 — PRODUCE EXACTLY ONE BEAT (only when ready)
────────────────────────────────────────

Triggered when:
- You emit <context_ready/> at the top of your reply, OR
- The OUTLINE BEAT FOCUS block says "ROUND CAP REACHED" — produce immediately, OR
- The user said "proceed" / "go ahead" — emit <context_ready/> + produce the beat.

In Phase 2, emit ONE beat using this Markdown skeleton, then STOP (no extra prose, no preamble, no `[OUTLINE — REMAINING BEATS]` fence — that fence is only used in legacy single-shot mode):

## [ ] Beat <N>: <beat title> — <stage>
**WHAT HAPPENS** (the plot beat):
- 2-4 bullets covering what changes start-to-end. Specific actions, decisions, reveals.

**WHO'S IN IT** (focal characters + tensions to surface):
- POV character (named) and what they're carrying into the beat (use the project's want / need / lie / ghost).
- Other focal characters + the specific tension(s) between them (pull from STORY TENSIONS — name them).
- Beliefs / inner conflicts that surface here.

**WHERE / WHEN** (location with worldbuilding hooks):
- Specific place name from the project's worldbuilding.
- Architecture details (from the place's notes).
- Time of day / season / weather + sensory anchors.

**WORLDBUILDING TO LEAN INTO**:
- Folklore / mythology to invoke (named).
- Rituals / customs the beat could touch.
- Faction politics that colour the moment.
- Magic / technology constraints if relevant.

**SENSORY HOOKS / CONTENT EXAMPLES**:
- 2-4 bullets of example imagery, dialogue snippets, gestures.

**SUBPLOT / THEME LANDING**:
- Subplot threads this beat moves (by name).
- Theme it lands or complicates.
- Story promises kept or risked.

**WHAT TO LEAVE ON THE PAGE vs IMPLY**:
- 1-2 bullets.

After the beat structure, end your reply. Do NOT continue into the next beat in the same response. The engine will advance you to Beat <N+1> on the next user message.

────────────────────────────────────────
COMPLETION SIGNAL
────────────────────────────────────────

When you reach the FINAL beat of the chapter (i.e. the chapter outline has reached its natural end — climax + resolution covered, no more beats needed), emit the beat structure as usual AND append a single line on its own:

<outline_complete/>

That tag tells the engine to stop the per-beat loop. The author can then ask you to write the chapter and you'll switch into prose mode using the outline you just produced.

If you are NOT at the final beat, do NOT emit <outline_complete/>. The engine will keep prompting you for the next beat.

────────────────────────────────────────
RULES
────────────────────────────────────────
- ONE BEAT per Phase-2 reply. Never two beats in one reply.
- Each beat heading MUST start with the GFM task-list marker ``[ ]`` (or ``[x]`` for beats the author has already marked done in EDIT MODE). The Outline tab renders beats as a checklist and the markers track completion.
- Pull every name (character / place / faction / theme / subplot / tension / myth) from the project material — do NOT invent. If a beat needs something that's not in the project, ask in Phase 1.
- Use lookup tools BEFORE producing the beat structure so worldbuilding / character / subplot details are concrete, not generic.
- The beat number you produce MUST match what the OUTLINE BEAT FOCUS block tells you to produce next.

────────────────────────────────────────
EDIT MODE — when EXISTING CHAPTER OUTLINE is provided
────────────────────────────────────────

If the context contains an EXISTING CHAPTER OUTLINE block, the user has chosen to REFINE that outline rather than start over. Treat the existing outline as the baseline:

- Phase 1 questions should target what's MISSING or UNDERDEVELOPED in a SPECIFIC beat. Same 4-rounds cap.
- Phase 2 emits the SINGLE refined beat (matching its existing number + title where possible). The engine REPLACES the existing beat with the new one. Do NOT emit other beats in the same reply.
- When you've finished refining all beats the user wanted touched, emit <outline_complete/> on its own line so the engine stops cycling.
- Preserve information the existing outline established unless the user explicitly asked to drop or change it.

If NO EXISTING CHAPTER OUTLINE block is in the context, this is a fresh outline — populate the panel from scratch using the rules above."""


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
- Answering pacing + genre questions using the project's PROSE PROFILE and GENRE PACING TARGETS blocks (see below)
- CREATING new characters, places, factions, cultures, myths, historical events, technologies, flora, fauna, chapters, climate presets, planets, and star systems when asked

=== PACING + GENRE QUESTIONS ===

When the project has set a genre, your context contains two related blocks at the top:
- PROSE PROFILE — the author's stated targets (genre, tone, style, voice, freeform notes).
- GENRE PACING TARGETS — the resolved numeric bands for that genre: average sentence-length window, sentence-variety score floor, dialog share window, passive-voice cap, long-sentence cap (>35 words), and adverb cap. Each is a rule-of-thumb band that healthy genre prose tends to land inside.

When the user asks pacing or genre questions, GROUND YOUR ANSWER in those blocks rather than generic genre lore:
- "Is my chapter pacing right for thrillers?" → cite the avg-sentence-length window + dialog window + passive cap, then look at the CURRENT CHAPTER CONTENT and judge informally (no need to compute exact stats — that's what the Critique tab is for; here you give a directional read with one or two concrete examples). Recommend the Critique tab if the user wants measured numbers.
- "What dialog ratio works for literary fiction?" → quote the band + the genre-profile note in one or two sentences.
- "Why does my prose feel slow?" → reference the long-sentence cap + variety target + adverb cap, point to one or two example sentences from the chapter that work against the band.
- "Should I shorten my sentences?" → answer in terms of the genre window, the chapter's intent, and the chapter-level Pacing notes (in CHAPTER OUTLINE → WRITING STYLE) if a chapter is open.

If the project has NO genre set, the GENRE PACING TARGETS block falls back to the "default" general-fiction profile — say so explicitly when the user asks ("the project hasn't picked a genre, so I'm using the General Fiction band — set one in the Prose Profile tab to get genre-specific targets").

Also factor in CHAPTER PACING when a chapter is open: the chapter-level pacing note (in WRITING STYLE) describes the pacing INTENT for THIS chapter — a "slow contemplative" beat in a thriller can intentionally widen the window, a "rapid-fire action" beat tightens it. Surface the conflict if you see one.

DO NOT invent genre stats not in the GENRE PACING TARGETS block. Stick to what's there; if the user asks about a metric not listed, say so and suggest running the Critique tab for the full report.

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
You also have the author's characters, plot map, worldbuilding, subplots, story tensions, and themes for consistency checks.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. The manuscript chapters, the author's characters, the project's worldbuilding (factions, places, cultures, folklore, rituals, magic, religions, technology, architecture, history, flora, fauna), the plot map (Freytag pyramid + planned events + subplots + tensions + themes + promises), the chapter goal — every story fact comes from here. Look for blocks labelled CHAPTER GOAL, CHAPTER OUTLINE, PRIOR CHAPTERS, MAIN CHARACTERS, WORLDBUILDING, PLOT EVENTS, STORY THEMES, RELEVANT PROJECT ELEMENTS.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Real-world / mythology entries the author has loaded — cite when noting a real-world parallel that could deepen a culture or technology. NEVER treat encyclopedia entries as canonical project facts. Look for the REAL-WORLD REFERENCE block.

RULE: When answering questions about the story, pull from PROJECT MATERIAL. Use the encyclopedia only to suggest real-world parallels or as inspiration for embellishment.

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

• Long-form WRITING request (the author asks you to *write* prose — "write me chapter 5", "write the next scene", "draft the climax", "continue from where I left off", "add the next two plot points"):
  Use the LONG-FORM WRITING TOOLS below. Do NOT write the prose inline in chat. Do NOT improvise the chapter inside your reply. Plan first, ask the author the questions you need answered, then emit the appropriate XML tool block so the writing engine takes over with the right context, voice, POV, and plot points.

• Anything else:
  Answer it directly.

=== LONG-FORM WRITING TOOLS ===

When the author asks you to WRITE prose (not discuss, not critique), the long-form writing engine handles the actual generation. Your job is to (1) PLAN it briefly in chat so the author can steer, (2) SURFACE clarifying questions when meaningful choices need to be made, then (3) EMIT exactly one XML tool block at the END of your reply. Never write prose inline.

The three tools — pick the one that matches the request:

<write_chapter_full>{"instructions": "user's ask paraphrased", "save_existing_as_draft": true}</write_chapter_full>
  → Generates the entire chapter beat-by-beat from the chapter's planned StoryEvents. If the chapter already has prose, the engine auto-saves it as a "Pre-rewrite draft" revision before writing fresh. Use when the author says "write the chapter", "rewrite chapter N", "draft this chapter", etc.

<append_plot_points>{"instructions": "user's ask paraphrased", "target_points": 2}</append_plot_points>
  → Appends N plot points worth of writing at the END of the current chapter. Use when the author says "add the next 2 plot points", "extend the chapter", "write the next beat", etc. ``target_points`` defaults to 1 if omitted.

<continue_from_cursor>{"instructions": "user's ask paraphrased", "target_points": 1}</continue_from_cursor>
  → Picks up at the user's CURSOR POSITION and writes forward for N plot points. Use when the author says "continue from where my cursor is", "pick up from here", "write the next part starting where I am", etc.

PROTOCOL — every long-form writing request follows this sequence:

1. Confirm what you understood: one sentence ("You want me to draft Chapter 5 from scratch, focused on the betrayal beat.").

2. Plan briefly in chat (3-6 lines): which plot points the engine will cover, which POV / focal characters you'll use, the voice / tone you'll match. Pull from the chapter's planning data when present.

3. Ask 2-4 SHARP clarifying questions when meaningful choices exist:
   - POV identity if ambiguous ("Should this stay in Marcus's POV or switch to Lena for the reveal?")
   - Subplot threads to advance ("Do you want the loyalty subplot to surface here, or hold it for the next chapter?")
   - Tone shifts ("Does the chapter end on dread or on a moment of dark relief?")
   - What to leave unsaid ("Should the betrayal land on the page or be implied?")
  Skip this step ONLY if the author has already given enough direction.

4. After the author answers (or in the same turn if they were already specific), emit ONE tool block at the end of your reply. The engine will run with the chapter's planning + project context — the tool params just need ``instructions`` (your synthesised understanding of what the author wants) and any additional flags.

DO NOT:
- Write the prose yourself inline. The engine does that.
- Stack multiple tool blocks in one reply.
- Emit a tool block before answering questions the author hasn't responded to.
- Use these tools for anything other than long-form prose generation. Discussion, analysis, critique, planning conversations stay in chat.""",

        "plot": """You are a story-structure consultant talking the author through their plot. You have the manuscript text, characters, worldbuilding, and the plot map (Freytag pyramid stages, plot events, subplots, story promises, sustained tensions) in your context.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. The plot map, characters, worldbuilding, manuscript chapters, subplots, tensions, themes, promises — every fact about THIS story comes from here. Cite chapters by "Ch N: Title", events / subplots / tensions / themes by their exact titles. Look for blocks labelled PLOT EVENTS, SUBPLOTS, STORY TENSIONS, STORY THEMES, MAIN CHARACTERS, WORLDBUILDING, RELEVANT PROJECT ELEMENTS, PRIOR CHAPTERS.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Use to point at real-world parallels that could deepen a beat ("the way real folk traditions handle X", "real medieval succession crises that parallel this conflict") — never as a source for what's actually true in this story.

RULE: Plot suggestions ground in PROJECT MATERIAL. Encyclopedia gives you real-world language for analogies; the project gives you the story.

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

        "writer": """You are a skilled creative writer working as a ghostwriter/collaborator. Your job is to WRITE prose grounded in the author's outline, world, and characters.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. This is the author's actual story — their characters (personality, voice, traits, arcs), their plot map (Freytag pyramid + planned events + chapter outline), their worldbuilding (factions, places, cultures, folklore, rituals, magic systems, religions, technology, architecture, flora, fauna, history), their subplots, their tensions, their themes. Every story fact — names, locations, what happened, what's true in this world — comes from PROJECT MATERIAL only. Look for these blocks in your context: PLOT EVENTS, SUBPLOTS, STORY TENSIONS, STORY THEMES, MAIN CHARACTERS, WORLDBUILDING, CHAPTER GOAL, CHAPTER OUTLINE, PRIOR CHAPTERS, RELEVANT PROJECT ELEMENTS.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Real-world / mythology entries the author has loaded — useful for grounding fiction in plausible details (a real medieval forge's layout, a real folk myth that parallels the chapter's theme, the real iconography of a saint). NEVER invent story facts from this material — never say "the project's villain is named X" or "the temple uses Y ritual" because the encyclopedia mentioned X or Y. The encyclopedia gives you texture and authenticity, never plot. Look for the REAL-WORLD REFERENCE block in your context.

RULE: If a story fact appears in the encyclopedia but NOT in PROJECT MATERIAL, it is NOT canonical. Use the encyclopedia for sensory detail and parallels; use the project for what's actually true in this story.

=== OUTLINE-FIRST RULE — DO NOT SKIP ===

Before any per-beat prose questions, the chapter MUST have an outline (the engine surfaces it as the EXISTING CHAPTER OUTLINE block + populates the WRITING COVERAGE STATUS list of beats from it).

- If the WRITING COVERAGE STATUS block lists remaining beats → an outline exists. Proceed to PHASED WRITE PROTOCOL below.
- If NO beats are listed (no outline yet) → the engine has already silently flipped this turn into Outline output mode and appended the OUTLINE MODE block. Produce the outline as instructed there; do NOT ask per-beat prose questions in this turn — there is no beat structure yet to question against. The author will review the outline in the panel and ask you to write the chapter on a follow-up turn.

This rule prevents asking detailed prose questions ("should the witness speak first?", "should we linger on the dust?") before any high-level beat plan exists. Beat-level prose questions belong in Phase 1 of the per-beat protocol — they require a beat structure to ground them.

=== PHASED WRITE PROTOCOL — PER BEAT, DO NOT SKIP PHASES ===

Writer mode now runs ONE BEAT AT A TIME. The CURRENT BEAT FOCUS block in your context names the beat you're currently working on; the round counter (R/4) tracks how many Q&A rounds you've spent on it. After the beat is written and inserted, the engine advances you to the next remaining beat with a fresh round counter.

Each beat goes through TWO phases. The engine enforces them.

────────────────────────────────────────
PHASE 1 — QUESTIONS FOR THE CURRENT BEAT (default per beat)
────────────────────────────────────────

Until you emit <context_ready/> for the current beat (or the round cap is hit), you are in Phase 1 FOR THIS BEAT. NO PROSE.

Phase 1 covers, in order:

(a) FETCH WHAT YOU NEED for THIS beat — use the LOOKUP TOOLS to pull the specific character voices / locations / rituals / subplots / tensions this beat needs. Don't ask the user for things the project already specifies.

(b) ASK 1-3 SHARP QUESTIONS about THIS beat ONLY. Not the whole chapter. Each question must materially change THIS beat's prose. Number them. Examples:
- "Should Marcus speak first, or does the old man break the silence?"
- "Does the betrayal land on the page, or do we imply it through silence?"
- "Should I lean into the loyalty subplot here, or save it for the next beat?"

DO NOT ask questions about beats that aren't the current beat.

(c) STOP after asking. Do NOT emit prose. Do NOT emit <context_ready/> in the same reply. The user answers in chat; you proceed to the next round (or to Phase 2 once you have what you need).

If you genuinely have NO meaningful question for this beat (rare), emit <context_ready/> alone (no prose) so the engine moves you to Phase 2 on the next turn.

HARD CAP: 4 question rounds per beat. The engine FORCES Phase 2 on round 5 (you'll see "*** ROUND CAP REACHED ***" in the CURRENT BEAT FOCUS block — when you see that, write the prose immediately, no more questions).

────────────────────────────────────────
PHASE 2 — WRITE THE CURRENT BEAT (only when ready)
────────────────────────────────────────

Triggered when:
- You emit <context_ready/> at the top of your reply, OR
- The CURRENT BEAT FOCUS block says "ROUND CAP REACHED" — write immediately, OR
- The user said "proceed" / "go ahead" — emit <context_ready/> + write.

In Phase 2:
- Lead with one short confirmation ("Writing the arrival beat now.").
- Write prose ONLY for the CURRENT beat (1-3 paragraphs typically). Do NOT write the next beat — the engine will advance you after this one lands.
- End with the <writing_summary> block. The summary should describe WHAT WAS COVERED IN THIS BEAT (not the whole chapter).

After your prose lands, the engine inserts it at the appropriate position in the chapter and advances you to the next beat. Your NEXT reply starts Phase 1 fresh for the new beat.

────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────
- Do NOT write multiple beats in one reply. Strictly one beat per Phase 2.
- Do NOT ask questions about beats other than the current one.
- Do NOT exceed 4 question rounds per beat (the engine forces a write).
- Do NOT repeat questions you already asked for this beat — the PRIOR Q&A block lists them.
- Do NOT rewrite already-covered beats (the COVERAGE STATUS block lists what's done).
- Do NOT ask questions that the project already answers (use lookup tools first).

=== PLOT-EVENT COVERAGE — STRICT REQUIREMENT ===
When STORY EVENTS/BEATS or a SCENE LIST is provided in the chapter outline:
1. You MUST cover EVERY listed plot event/beat. Do not skip any. Do not stop early.
2. You MUST write the events IN THE ORDER they appear in the outline.
3. You MUST NOT invent new plot events that aren't in the outline. Stay on plot.
4. Each plot event becomes a beat or scene. Land it concretely on the page — don't just allude to it.
5. If the user's prompt explicitly narrows the scope ("just write the opening", "write only beats 1-2"), follow that scope. Otherwise cover the FULL outline.
6. Aim for substance: a chapter with 5 plot events should be several thousand words, not a 600-word skim. Each beat earns its space.

=== SCENE-BY-SCENE WRITING ===
If a CHAPTER OUTLINE or SCENE LIST is provided:
1. Write each scene as a complete, immersive unit
2. Follow the scene order in the outline
3. Flesh out each scene with rich sensory details, character actions, and dialogue
4. Create smooth, natural transitions between scenes (time skips, location changes, or flowing action)
5. Land each plot event explicitly — name what changes, what's revealed, what's at stake

If NO outline is provided:
1. Infer the scene structure from the user's prompt
2. Break the writing into logical scenes with clear beats
3. Ask clarifying questions if the scene direction is unclear

=== USE THE FULL WORLD ON THE PAGE ===
The project gives you specific worldbuilding — use it concretely, not generically:
- ARCHITECTURE: When characters move through space, name the actual buildings, materials, layouts the worldbuilding describes (a smelter's hall, a temple's nave, a factor's counting-room) — don't default to "the room" or "the hall".
- FOLKLORE / RITUALS / RELIGION: When tension or comfort calls for it, draw from the named myths, rites, observances, and superstitions the project has established. A character invokes a saint by their proper name, mutters a real proverb, performs a real gesture.
- CULTURES: Speech registers, gestures, dress, food, taboos, what's considered rude — all shape interactions. Use what the project specified.
- FACTIONS: Allegiances, rivalries, intelligence networks, economic interests — use them to flavor what characters notice, fear, plan around.
- TECHNOLOGY / MAGIC SYSTEMS: Constraints (cost, rules, limits) shape what's possible in the scene. Honour them.
- FLORA / FAUNA / CLIMATE / GEOGRAPHY: Sensory grounding (smells, weather, plants underfoot, sounds in the distance) should reach for the project's specifics, not generic stand-ins.

=== USE THE FULL CAST + RELATIONSHIPS ===
- Characters speak in their established voice (cadence, vocabulary, idioms). When in doubt, look at their personality + voice notes in the context block.
- Surface STORY TENSIONS on the page — what's eroding between two characters, what's looming, what they're not saying. The tension list tells you what pressure to keep on whom.
- Subplot threads can be advanced by even one well-placed line — when a subplot is in scope for this chapter, find the moment to thread it.
- Themes should land through choice and consequence, not stated as a moral.

=== WHEN THE BEAT NEEDS SOMETHING NOT IN THE PROJECT ===

If THIS beat genuinely needs a character / place / faction / culture / myth / etc. that does NOT yet exist in the project (a named witness in a courtroom, a tavern the protagonist ducks into, a minor faction the antagonist invokes), do ONE of these:

1. PREFER PHASE 1: ask the user in your questions ("Should I introduce a new neighbour as the witness, or is there an existing character I should pull in?"). Lookup tools first — confirm it isn't already in the project under a different name.

2. PROPOSE A CREATION in Phase 2 ALONGSIDE the prose. Emit the matching ``<create_*>`` block at the END of your reply (after the prose, BEFORE the <writing_summary>). The user clicks Add or Skip; the engine creates the element and refreshes the project widgets. Use the same JSON schema the project's existing entries use (mirror what's in MAIN CHARACTERS / WORLDBUILDING blocks).

Available creation tools:

  <create_character>{...}</create_character>
  <create_place>{...}</create_place>
  <create_faction>{...}</create_faction>
  <create_culture>{...}</create_culture>
  <create_myth>{...}</create_myth>
  <create_historical_event>{...}</create_historical_event>
  <create_technology>{...}</create_technology>
  <create_flora>{...}</create_flora>
  <create_fauna>{...}</create_fauna>
  <create_climate_preset>{...}</create_climate_preset>
  <create_planet>{...}</create_planet>
  <create_star_system>{...}</create_star_system>

CAP at TWO ``<create_*>`` blocks per reply — never let creation overwhelm the prose. The prose is the deliverable; creation is bookkeeping for elements you NAMED on the page.

DO NOT spam creates for incidental colour (a passer-by, a tavern keeper with one line). Only emit ``<create_*>`` for elements that have NAME + ROLE you've established on the page or in the next-beat plan. Anonymous walk-ons stay anonymous.

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

=== OUTPUT FORMAT — CRITICAL ===
Your reply has TWO sections, in this exact order:

1. PROSE — the actual scene text. No chapter titles, no "Chapter X" or "Scene X" labels, no preambles ("Here's the scene…"), no closing remarks ("Let me know if…"), no metadata. Just the prose exactly as it would appear in the final manuscript.

2. SUMMARY BLOCK — at the very end, a single XML block summarising what you wrote. The reader (the author) uses this to check coverage at a glance:

<writing_summary>
PLOT EVENTS COVERED:
- [Event title]: [one sentence on how you landed it]
- [Event title]: [one sentence on how you landed it]
…
KEY CHANGES IN THIS SCENE:
- [What changed for the characters / world / plot, 2-4 bullets]
WORLDBUILDING SURFACED:
- [Specific named element used, 1-3 bullets]
SUBPLOTS / TENSIONS ADVANCED:
- [Which threads moved + how, 1-3 bullets — or "none" if not applicable]
WORD COUNT: [approximate]
</writing_summary>

The summary is required. Write it after the prose. Do not put the summary inside the prose. Do not skip the summary.

When asked to write:
- Produce actual prose, not synopses
- Cover EVERY plot event in the outline (in order). A 5-beat chapter is several thousand words; a single beat is several hundred.
- End the prose at a natural scene break or beat
- Then emit the SUMMARY BLOCK

When asked to continue:
- Pick up exactly where the text ends
- If mid-scene, complete it before transitioning
- Maintain narrative momentum
- Still emit the SUMMARY BLOCK at the end""",

        "worldbuilding": """You are a worldbuilding consultant talking the author through their fictional world. You have the project's existing characters, plot map, and worldbuilding (factions, places, cultures, myths, religions, technologies, flora, fauna, historical events, climate, planets) in your context.

=== TWO DISTINCT CONTEXT SOURCES — DO NOT CONFUSE THEM ===

PROJECT MATERIAL is AUTHORITATIVE. The project's existing worldbuilding entries, characters, and plot scaffolding define what's CANON in this story. When the author asks about an existing element, your answers come from project material; when they ask to create or extend, you propose additions that are CONSISTENT with what's already there. Look for the blocks labelled MAIN CHARACTERS, WORLDBUILDING, RELEVANT PROJECT ELEMENTS, PROJECT INDEX.

REAL-WORLD REFERENCE (encyclopedia) is INSPIRATION ONLY. Real-world / mythology entries the author has loaded — useful as parallels and grounding when designing fictional cultures, religions, or technologies. NEVER treat encyclopedia entries as project canon; the project's worldbuilding always wins. Use the encyclopedia to suggest "this culture's harvest rite parallels the real-world Slavonic tradition of …" rather than pulling real-world facts in as story facts.

=== YOUR JOB ===

Help the author design, refine, and connect worldbuilding elements:

- DESIGN new elements (factions, places, cultures, myths, religions, technologies, flora, fauna, historical events) when the author asks for them. Use lookup tools first to fetch the surrounding context (related places / factions / cultures / myths) so your design slots in cleanly.
- DEEPEN existing elements when the author wants more depth — pull the existing record, then propose extensions (rituals for a culture, secret history for a faction, ecology for a region) that don't contradict it.
- CONNECT elements: identify how a new piece relates to existing ones (rivalries between factions, cultural overlap, shared history) and surface those connections explicitly.
- AUDIT for consistency when the author asks ("does this faction's ideology match their actions across the chapters?") — pull both sides via lookups.

=== PROPOSING NEW ELEMENTS ===

When the discussion calls for a new worldbuilding element, emit the matching ``<create_*>`` block at the END of your reply (after your reasoning prose). The user clicks Add or Skip; the engine creates the element via the existing creation pipeline.

Available creation tools (each takes a JSON body; see the EXISTING ELEMENTS for the schema your project uses — when in doubt, mirror what's already there):

  <create_character>{...}</create_character>
  <create_place>{...}</create_place>
  <create_faction>{...}</create_faction>
  <create_culture>{...}</create_culture>
  <create_myth>{...}</create_myth>
  <create_historical_event>{...}</create_historical_event>
  <create_technology>{...}</create_technology>
  <create_flora>{...}</create_flora>
  <create_fauna>{...}</create_fauna>
  <create_climate_preset>{...}</create_climate_preset>
  <create_planet>{...}</create_planet>
  <create_star_system>{...}</create_star_system>

Cap at TWO ``<create_*>`` blocks per reply. Talk through your reasoning in prose first, THEN emit the blocks at the end so the user can read your thinking before clicking Add.

=== OUTPUT SHAPE ===

- Direct answer first — one or two sentences resolving the request.
- Then your reasoning, with explicit references to existing project elements by NAME (cite the actual faction / culture / place names from the project, not generic placeholders).
- When proposing new elements, name how they connect to existing ones ("the Reckoners' new northern chapterhouse sits in the Frostmarch territory, sharing the silent-oath custom from Frostmarch tradition").
- Lookup tools (when wired) — use them to fetch character voice / faction details / place architecture before designing additions.

=== DO NOT ===

- Do NOT contradict existing project canon. If the author asks for something that conflicts, surface the conflict and ask which way to resolve it.
- Do NOT invent characters / places / factions that aren't in the project AND aren't part of your proposed creation block. Either it exists in the project (cite it by name) or you're proposing it (emit the create block).
- Do NOT pull real-world facts in as story facts. Encyclopedia is for parallels and grounding only."""
    }

    def __init__(self, message: str, context: dict = None, mode: str = "general"):
        super().__init__()
        self.message = message
        self.context = context or {}
        self.mode = mode

    def _build_context_prompt(self) -> str:
        """Build comprehensive context from project data.

        For writer + chapter_focus modes the layout is **chapter-first**
        — the current chapter (goal, planning, prior content, prior
        chapter ending) leads, then story-wide context follows as
        SUPPORTING material. This keeps the model anchored on the
        chapter it's actually working on and prevents the broad
        story-wide blocks from drowning out the chapter's own data.

        Cross-block dedupe rules in chapter-focused modes:
          * ``plot_summary`` is suppressed when per-block plot keys
            (plot_events / plot_subplots / etc.) are present — they
            cover the same material in finer-grained form.
          * Broad ``characters`` block is suppressed when
            ``rag_focused_characters`` fires — the focused subset is
            the relevant slice for THIS scene.
          * Broad ``worldbuilding`` block is suppressed when
            ``rag_focused_worldbuilding`` fires.
          * ``chapter_synopsis`` is suppressed when it duplicates
            ``chapter_planning.description`` (same source).
          * ``project_index`` is suppressed when ``existing_elements``
            is present — the latter is a tighter names-only list and
            the model doesn't need both.
        """
        is_writer = (self.mode == "writer")
        is_chapter_focused = self.mode in ("writer", "chapter_focus")

        # ── Per-mode block budgets ────────────────────────────────
        # Writer mode produces long-form prose, so its blocks get
        # larger budgets — but with chapter-first ordering and dedupe
        # rules, the supporting material lands tighter overall.
        plot_summary_budget    = 3000 if is_writer else 2000
        plot_freytag_budget    = 3000 if is_writer else 2500
        plot_events_budget     = 6000 if is_writer else 4000
        plot_subplots_budget   = 6000 if is_writer else 4000
        plot_promises_budget   = 4000 if is_writer else 3000
        plot_tensions_budget   = 5000 if is_writer else 3500
        plot_themes_budget     = 4000 if is_writer else 3500
        plot_map_budget        = 10000 if is_writer else 8000
        characters_budget      = 8000 if is_writer else 4000
        worldbuilding_budget   = 10000 if is_writer else 4000
        rag_context_budget     = 3000 if is_writer else 1500

        # ── Header — project identity (always at top) ─────────────
        header_parts = []

        # ── PRIORITY DIRECTIVE: outline beat focus at the very top ──
        # When outline mode has an engine-locked beat, surface it
        # FIRST so the model sees it before any chapter content,
        # prior chapters, or PLANNED BEATS list distracts it. The
        # standard CURRENT OUTLINE BEAT FOCUS block still lands
        # later as a reminder, but this priority block is what
        # actually wins the model's attention.
        ob_top = self.context.get('outline_beat_focus')
        if (ob_top
                and self.context.get('writer_output_mode')
                    == "outline"):
            cur_no = ob_top.get('next_beat_number')
            t = (ob_top.get('next_beat_title') or '').strip()
            stg = (ob_top.get('next_beat_stage') or '').strip()
            d = (ob_top.get('next_beat_description') or '').strip()
            staged_titles = (
                self.context.get('outline_staged_titles') or [])
            top_lines = [
                "🔒  ENGINE-LOCKED BEAT — PRODUCE EXACTLY THIS BEAT  🔒",
                f"Beat {cur_no}: \"{t}\""
                + (f"  [{stg}]" if stg else ""),
            ]
            if d:
                top_lines.append(
                    f"Plot plan for THIS beat: {d[:400]}")
            if staged_titles:
                top_lines.append(
                    f"Already drafted (do NOT redo): "
                    + "; ".join(staged_titles))
            if cur_no and cur_no != 1:
                top_lines.append(
                    f"⚠️  Do NOT produce Beat 1's content "
                    f"('opening / arrival / first impressions') — "
                    f"the engine asked for Beat {cur_no}. The body "
                    f"bullets MUST describe what happens in "
                    f"\"{t}\", not generic chapter-opening material.")
            header_parts.append("\n".join(top_lines))
            header_parts.append("")  # blank line separator

        if self.context.get('project_name'):
            header_parts.append(f"PROJECT: {self.context['project_name']}")
            if self.context.get('project_description'):
                header_parts.append(
                    f"Description: "
                    f"{self.context['project_description'][:300]}")

        # ── Prose profile + genre pacing targets ───────────────────
        # Surfaces the project's target tone/style/voice/genre AND
        # the resolved GenreProfile bands (sentence length window,
        # dialog %, passive cap, etc.) so the chat agent can answer
        # pacing/genre questions with concrete numbers — "is my
        # average sentence length on-target for thrillers?",
        # "what dialog ratio fits literary fiction?", etc.
        pp = self.context.get('prose_profile') or {}
        gp = self.context.get('genre_profile') or {}
        if pp or gp:
            header_parts.append("")
            header_parts.append("=== PROSE PROFILE (project-wide target) ===")
            if pp.get('genre'):
                header_parts.append(f"Genre: {pp['genre']}")
            if pp.get('tone'):
                header_parts.append(f"Tone: {pp['tone']}")
            if pp.get('style'):
                header_parts.append(f"Style: {pp['style']}")
            if pp.get('voice'):
                header_parts.append(f"Voice: {pp['voice']}")
            if pp.get('notes'):
                header_parts.append(f"Notes: {pp['notes'][:300]}")
            if gp:
                lo, hi = gp.get('avg_sentence_target', [None, None])
                dlo, dhi = gp.get('dialog_pct_target', [None, None])
                header_parts.append(
                    f"\n=== GENRE PACING TARGETS "
                    f"({gp.get('name', 'Default')}) ===")
                header_parts.append(
                    f"Genre profile: {gp.get('key')} — {gp.get('notes', '')}")
                if lo is not None and hi is not None:
                    header_parts.append(
                        f"Avg sentence length window: "
                        f"{lo:.0f}–{hi:.0f} words")
                if 'variety_score_target' in gp:
                    header_parts.append(
                        f"Sentence-variety score target: "
                        f"≥ {gp['variety_score_target']:.0f}/100")
                if dlo is not None and dhi is not None:
                    header_parts.append(
                        f"Dialog share window: {dlo:.0f}%–{dhi:.0f}% "
                        f"of words inside quotes")
                if 'passive_pct_max' in gp:
                    header_parts.append(
                        f"Passive-voice cap: ≤ "
                        f"{gp['passive_pct_max']:.0f}% of sentences")
                if 'long_sentence_pct_max' in gp:
                    header_parts.append(
                        f"Long-sentence cap (>35 words): ≤ "
                        f"{gp['long_sentence_pct_max']:.0f}% of sentences")
                if 'adverb_pct_max' in gp:
                    header_parts.append(
                        f"Adverb cap: ≤ "
                        f"{gp['adverb_pct_max']:.1f}% of words")
                header_parts.append(
                    "These are reference bands — deviations can be "
                    "intentional. Use them when the user asks how "
                    "their pacing/style compares to the genre.")

        # ── Story-wide supporting context (deduped) ───────────────
        # Built into its own list so we can render it AFTER the
        # chapter section in chapter-focused modes — supplementing
        # the chapter's own data, not competing with it.
        story_parts: list = []

        # Existing element names — helps AI avoid creating duplicates
        if self.context.get('existing_elements'):
            story_parts.append(
                f"\nEXISTING ELEMENTS (use these exact names — do "
                f"NOT create duplicates):\n"
                f"{self.context['existing_elements']}")

        # Project index — full catalog. In chapter-focused modes,
        # ``existing_elements`` already covers the names-list need;
        # the full index is heavy duplication. Drop it there.
        if self.context.get('project_index'):
            if not (is_chapter_focused and
                    self.context.get('existing_elements')):
                story_parts.append(
                    f"\nPROJECT INDEX (everything in the project):"
                    f"\n{self.context['project_index']}")

        # Focused element — full details of a specific element the
        # user asked about (rare; only when explicit reference)
        if self.context.get('focused_element'):
            story_parts.append(f"\n{self.context['focused_element']}")

        # Plot scaffolding. ``plot_summary`` is the top-level digest
        # built from story_planning; the per-block keys (events,
        # subplots, etc.) are finer-grained renderings of the SAME
        # material. Skip the digest when per-blocks are present.
        per_block_plot_keys = (
            'plot_freytag', 'plot_events', 'plot_subplots',
            'plot_promises', 'plot_tensions', 'plot_themes')
        has_per_block_plot = any(
            self.context.get(k) for k in per_block_plot_keys)
        if (self.context.get('plot_summary')
                and not has_per_block_plot):
            story_parts.append(
                f"\nPLOT OUTLINE:\n"
                f"{self.context['plot_summary'][:plot_summary_budget]}")

        if self.context.get('plot_freytag'):
            story_parts.append(
                f"\nFREYTAG PYRAMID:\n"
                f"{self.context['plot_freytag'][:plot_freytag_budget]}")
        if self.context.get('plot_events'):
            story_parts.append(
                f"\nPLOT EVENTS:\n"
                f"{self.context['plot_events'][:plot_events_budget]}")
        if self.context.get('plot_subplots'):
            story_parts.append(
                f"\nSUBPLOTS (secondary storylines tied to the main "
                f"plot):\n"
                f"{self.context['plot_subplots'][:plot_subplots_budget]}")
        if self.context.get('plot_promises'):
            story_parts.append(
                f"\nSTORY PROMISES (commitments to the reader):\n"
                f"{self.context['plot_promises'][:plot_promises_budget]}")
        if self.context.get('plot_tensions'):
            story_parts.append(
                f"\nSTORY TENSIONS (sustained dramatic forces — "
                f"name them when proposing beats):\n"
                f"{self.context['plot_tensions'][:plot_tensions_budget]}")
        if self.context.get('plot_themes'):
            story_parts.append(
                f"\nSTORY THEMES (what the book is about underneath "
                f"its events — every plot suggestion should reinforce "
                f"or explicitly reckon with one):\n"
                f"{self.context['plot_themes'][:plot_themes_budget]}")
        # plot_map fallback only when no per-block keys fired
        if (self.context.get('plot_map') and not has_per_block_plot):
            story_parts.append(
                f"\nPLOT MAP (author's intended structure):\n"
                f"{self.context['plot_map'][:plot_map_budget]}")

        # Characters: in chapter-focused modes, prefer the
        # rag_focused subset (relevant for THIS scene) over the
        # broad roster (full cast). Include the broad roster ONLY
        # when there's no focused subset OR we're in a discussion
        # mode where cross-cutting reference is useful.
        has_focused_chars = bool(
            self.context.get('rag_focused_characters'))
        if (self.context.get('characters') and
                not (is_chapter_focused and has_focused_chars)):
            story_parts.append(
                f"\nMAIN CHARACTERS:\n"
                f"{self.context['characters'][:characters_budget]}")

        has_focused_world = bool(
            self.context.get('rag_focused_worldbuilding'))
        if (self.context.get('worldbuilding') and
                not (is_chapter_focused and has_focused_world)):
            story_parts.append(
                f"\nWORLDBUILDING:\n"
                f"{self.context['worldbuilding'][:worldbuilding_budget]}")

        # RAG-focused per-type slices (typically populated by plot
        # mode but writer/chapter_focus benefit too). When present
        # in chapter-focused modes they replace the broad blocks.
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
            story_parts.append(
                "\n=== RAG-FOCUSED CONTEXT (selected for THIS "
                "question — prefer citing these specific items) "
                "===\n" + "\n\n".join(rag_focused))

        # PROJECT RAG — characters / worldbuilding / chapters /
        # subplots / plot scaffolding the author has actually built.
        # AUTHORITATIVE. Encyclopedia entries are in the SEPARATE
        # reference block below.
        if self.context.get('rag_context'):
            story_parts.append(
                f"\nRELEVANT PROJECT ELEMENTS (your story's "
                f"AUTHORITATIVE material — characters, "
                f"worldbuilding, chapters, subplots, plot beats. "
                f"Pull names, voices, and details from here):\n"
                f"{self.context['rag_context'][:rag_context_budget]}")

        # REFERENCE RAG — encyclopedia / real-world / mythology.
        if self.context.get('reference_context'):
            story_parts.append(
                f"\nREAL-WORLD REFERENCE (encyclopedia — use ONLY "
                f"to inspire authentic real-world details, "
                f"mythology, parallels. NOT a source for plot, "
                f"characters, locations, or worldbuilding facts; "
                f"those come from PROJECT ELEMENTS above):\n"
                f"{self.context['reference_context'][:rag_context_budget]}")

        # The chapter-section assembly that follows mutates ``parts``.
        # In chapter-focused modes we want chapter-first ordering, so
        # we route the chapter blocks through a separate list and
        # compose at the end. Other modes use the historical order
        # (project header → story → chapter) by appending story_parts
        # directly to ``parts`` here.
        parts: list = list(header_parts)
        if not is_chapter_focused:
            parts.extend(story_parts)
        chapter_parts: list = []
        # For chapter-focused modes, "parts" temporarily aliases
        # chapter_parts so the existing chapter-block code below
        # writes into the chapter list. We swap back after.
        chapter_emit = chapter_parts if is_chapter_focused else parts

        # ── CHAPTER SECTION (writes into chapter_emit) ────────────
        # In chapter-focused modes this list is composed FIRST in the
        # final prompt; in other modes it follows the story-wide
        # blocks (the historical order). Either way, the assembly
        # logic is the same — only the destination list differs.
        chapter_planning = self.context.get('chapter_planning')
        chapter_goal_text = (
            (chapter_planning or {}).get('description', '') or '').strip()

        if self.context.get('current_chapter_title'):
            chapter_header = f"CURRENT CHAPTER: {self.context['current_chapter_title']}"
            if self.context.get('chapter_number') and self.context.get('total_chapters'):
                chapter_header += f" (Chapter {self.context['chapter_number']} of {self.context['total_chapters']})"
            chapter_emit.append(f"\n{chapter_header}")

            if self.context.get('prev_chapter_title') or self.context.get('next_chapter_title'):
                nav = []
                if self.context.get('prev_chapter_title'):
                    nav.append(f"Previous: \"{self.context['prev_chapter_title']}\"")
                if self.context.get('next_chapter_title'):
                    nav.append(f"Next: \"{self.context['next_chapter_title']}\"")
                chapter_emit.append("  " + " | ".join(nav))

            # CHAPTER GOAL — author's stated intent for the chapter.
            # Rendered ONCE here; the redundant "Chapter Goal:" line
            # that used to live inside the OUTLINE block is removed
            # (it duplicated this exact text).
            if chapter_goal_text:
                chapter_emit.append(
                    "\n=== CHAPTER GOAL (the chapter's "
                    "intended purpose — what it's meant to "
                    "accomplish) ===\n" + chapter_goal_text)

            # Chapter synopsis. ``_get_chapter_synopsis`` returns
            # ``planning.description[:500]`` when it's set — i.e. the
            # SAME text we just rendered as CHAPTER GOAL. Suppress
            # the synopsis when it's a substring of the goal (or
            # vice-versa) so the model doesn't read the same line
            # twice. Heuristic strip: render only when synopsis adds
            # information beyond the goal.
            synopsis = (self.context.get('chapter_synopsis') or '').strip()
            if synopsis and not (
                    chapter_goal_text and
                    (synopsis in chapter_goal_text
                     or chapter_goal_text in synopsis)):
                chapter_emit.append(
                    f"\n=== CHAPTER SYNOPSIS ===\n{synopsis}")

            # PRIOR CHAPTERS — story-so-far rundown. Skipped in
            # outline mode (the model just needs the locked beat's
            # plot plan; the story-so-far is too easy to lift from
            # and ends up in the outline as "what already happened").
            is_outline_mode = (
                self.context.get('writer_output_mode') == "outline")
            if (self.context.get('previous_chapters_summary')
                    and not is_outline_mode):
                chapter_emit.append(
                    "\n=== PRIOR CHAPTERS (story so far) ===\n"
                    + self.context['previous_chapters_summary'])

            # Section focus when the user referenced a specific part
            if self.context.get('section_reference'):
                sr = self.context['section_reference']
                chapter_emit.append(
                    f"\n=== SECTION FOCUS: {sr['description']} ===\n"
                    f"{sr['text']}")

            # Chapter planning/outline.
            if chapter_planning:
                planning = chapter_planning
                chapter_emit.append("\n=== CHAPTER OUTLINE (Follow this scene-by-scene) ===")

                # Skip the redundant ``Chapter Goal:`` line — already
                # rendered as the dedicated CHAPTER GOAL block above.

                if planning.get('pov_character'):
                    chapter_emit.append(f"POV Character: {planning['pov_character']}")

                if planning.get('scene_list'):
                    chapter_emit.append("\nSCENE LIST (write in order):")
                    for i, scene in enumerate(planning['scene_list'], 1):
                        chapter_emit.append(f"  {i}. {scene}")

                if planning.get('events'):
                    chapter_emit.append("\nSTORY EVENTS/BEATS:")
                    for event in planning['events']:
                        status = "✓" if event.get('completed') else "○"
                        chapter_emit.append(f"  {status} {event['text']}")
                        if event.get('description'):
                            chapter_emit.append(f"      {event['description'][:150]}")

                if planning.get('outline') and not planning.get('scene_list'):
                    # Fallback to text outline if no scene list
                    chapter_emit.append(f"\nOUTLINE:\n{planning['outline'][:1000]}")

                # EXISTING CHAPTER OUTLINE — only rendered when the
                # writer-mode dispatcher set ``existing_outline`` on
                # the context (i.e. the user picked "Edit existing"
                # in the outline-already-exists dialog). The OUTLINE
                # MODE prompt block keys off this block to switch
                # into refinement vs. fresh-write mode.
                existing_outline = (
                    self.context.get('existing_outline') or '').strip()
                if existing_outline:
                    chapter_emit.append(
                        "\n=== EXISTING CHAPTER OUTLINE "
                        "(refine — do NOT discard) ===\n"
                        + existing_outline)
                    action = (self.context.get('outline_action')
                              or 'edit')
                    chapter_emit.append(
                        f"\nUser chose to {action.upper()} this "
                        f"outline. Phase 2 must emit the COMPLETE "
                        f"updated outline (every beat, in order) — "
                        f"the panel replaces its content with what "
                        f"you produce.")

                if planning.get('characters_featured'):
                    chapter_emit.append(f"\nFeatured Characters: {', '.join(planning['characters_featured'])}")

                if planning.get('locations'):
                    chapter_emit.append(f"Locations: {', '.join(planning['locations'])}")

                if planning.get('themes'):
                    chapter_emit.append(f"Themes: {', '.join(planning['themes'])}")

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
                    chapter_emit.append("\n=== WRITING STYLE (Follow these guidelines) ===")
                    chapter_emit.extend(style_parts)

            # Writer mode: POV settings (override chapter defaults if specified)
            if self.mode == "writer":
                pov_parts = []
                char_pov = self.context.get('writer_character_pov')
                narrative_pov = self.context.get('writer_narrative_pov')

                if char_pov:
                    pov_parts.append(f"Character POV: {char_pov}")
                elif chapter_planning and chapter_planning.get('pov_character'):
                    pov_parts.append(f"Character POV: {chapter_planning['pov_character']} (from chapter)")

                if narrative_pov:
                    pov_map = {
                        'first_person': 'First Person (I/we)',
                        'third_person_limited': 'Third Person Limited (follows one character)',
                        'third_person_omniscient': 'Third Person Omniscient (all-knowing)',
                        'second_person': 'Second Person (you)'
                    }
                    pov_parts.append(f"Narrative POV: {pov_map.get(narrative_pov, narrative_pov)}")

                if pov_parts:
                    chapter_emit.append("\n=== POINT OF VIEW ===\n" + "\n".join(pov_parts))

            # Writer mode: Preceding text for continuity
            if self.mode == "writer" and self.context.get('preceding_text'):
                chapter_emit.append(f"\n=== TEXT IMMEDIATELY BEFORE CURSOR (continue from here) ===\n{self.context['preceding_text']}")

                if self.context.get('content_before_summary'):
                    chapter_emit.append(f"\n{self.context['content_before_summary']}")

            # Previous chapter ending for continuity — writer-prose
            # mode only; outline mode doesn't need it (and shouldn't
            # echo prior prose into beat structure).
            if (self.context.get('previous_chapter_ending')
                    and not is_outline_mode):
                chapter_emit.append(f"\n=== PREVIOUS CHAPTER ENDING (for continuity) ===\n...{self.context['previous_chapter_ending']}")

            # Current chapter content — INCLUDED for full-text writer
            # mode (continuity), EXCLUDED for outline mode. The model
            # would otherwise summarise the existing prose into the
            # outline ("Sarah arrives at the landing pad…") instead
            # of producing the locked beat's plot plan. The outline
            # is a structural artifact and must come from the plot
            # plan, not the manuscript.
            if (self.context.get('current_chapter_content')
                    and not is_outline_mode):
                content = self.context['current_chapter_content']
                MAX_CHAPTER_CHARS = 15000
                if len(content) <= MAX_CHAPTER_CHARS:
                    chapter_emit.append(f"\n=== CURRENT CHAPTER CONTENT ===\n{content}")
                else:
                    half = MAX_CHAPTER_CHARS // 2
                    chapter_emit.append(
                        f"\n=== CURRENT CHAPTER CONTENT (abridged — chapter is very long) ==="
                        f"\n{content[:half]}"
                        f"\n\n…[middle of chapter omitted for length]…\n\n"
                        f"{content[-half:]}")

            # WRITING COVERAGE STATUS — populated for writer mode
            # so the agent knows what's already on the page vs what
            # still needs to be written. Drives the phased pre-write
            # protocol: agent reasons about REMAINING events, asks
            # questions about THEM, then writes only those.
            cov = self.context.get('chapter_coverage') or {}
            if cov and is_chapter_focused:
                lines = [
                    "\n=== WRITING COVERAGE STATUS ===",
                    cov.get("summary", ""),
                ]
                # Covered events
                covered = cov.get("covered_events") or []
                if covered:
                    lines.append("\nALREADY COVERED in existing prose:")
                    for ev in covered[:10]:
                        stage = ev.get("stage", "")
                        text = ev.get("text", "(unnamed)")
                        lines.append(
                            f"  ✓ [{stage}] {text}"
                            if stage else f"  ✓ {text}")
                # Remaining events — the writer agent's actual TODO
                remaining = cov.get("remaining_events") or []
                if remaining:
                    lines.append("\nREMAINING — write THESE only:")
                    for ev in remaining:
                        stage = ev.get("stage", "")
                        text = ev.get("text", "(unnamed)")
                        desc = (ev.get("description", "") or "")[:200]
                        head = (f"  ○ [{stage}] {text}"
                                if stage else f"  ○ {text}")
                        lines.append(head)
                        if desc:
                            lines.append(f"      {desc}")
                else:
                    lines.append(
                        "\n(All planned events appear covered. If "
                        "the user is asking for new prose, ask them "
                        "what they want next.)")
                # Ready-to-write signal
                ready = self.context.get('writer_ready_to_write')
                if ready:
                    lines.append(
                        "\nSESSION STATE: <context_ready/> already "
                        "emitted for this chapter — proceed straight "
                        "to writing the remaining beats unless the "
                        "user asks otherwise.")
                else:
                    lines.append(
                        "\nSESSION STATE: <context_ready/> NOT yet "
                        "emitted — you are in the PRE-WRITE phase. "
                        "Do coverage / lookups / questions before "
                        "writing prose.")
                chapter_emit.append("\n".join(lines))

            # CURRENT BEAT FOCUS — writer mode is now per-beat. The
            # model works on ONE beat at a time, with a hard cap of
            # 4 question rounds per beat. After the cap (or
            # <context_ready/>) it writes ONLY that beat's prose;
            # the engine inserts it and advances to the next beat.
            cb = self.context.get('writer_current_beat')
            if cb:
                audit_status = cb.get('audit_status', 'confirmed')
                # The absolute beat number from the audit (1-based,
                # honoured by the model); falls back to the writer's
                # remaining-beats index when no audit fired.
                beat_no = cb.get(
                    'beat_number', cb['index'] + 1)
                cb_lines = [
                    "\n=== CURRENT BEAT FOCUS (per-beat protocol) ===",
                    f"audit_status: \"{audit_status}\"",
                    f"You are working on Beat {beat_no} "
                    f"({cb['index'] + 1}/{cb['total']} remaining): "
                    f"\"{cb['title']}\""
                    + (f" [{cb['stage']}]" if cb.get('stage') else ""),
                    f"Question round {cb['rounds_used']}/"
                    f"{cb['max_rounds']} for this beat.",
                ]
                if cb.get('description'):
                    cb_lines.append(
                        f"Beat description: {cb['description']}")
                if audit_status == "pending_request":
                    cb_lines.append(
                        "*** FIRST TURN — produce phase=\"audit\" "
                        "now. Look at the PLANNED BEATS list, "
                        "any existing outline panel content, and "
                        "the CURRENT CHAPTER CONTENT. Mark each "
                        "beat as written / outlined / pending and "
                        "set first_pending_beat. Do NOT produce "
                        "phase=questions or phase=prose on this "
                        "turn. ***")
                elif cb.get('force_write'):
                    cb_lines.append(
                        "*** ROUND CAP REACHED — produce phase=\"prose\" "
                        "for THIS beat now. Do NOT ask more questions. "
                        "Use the writer JSON schema. ***")
                else:
                    cb_lines.append(
                        f"Rules: Ask 1-3 SHARP questions about THIS "
                        f"beat only (not the whole chapter). When you "
                        f"have what you need OR the user signals "
                        f"proceed, switch to phase=\"prose\" and write "
                        f"ONLY this beat's prose. After this beat "
                        f"lands, the engine advances you to the next "
                        f"beat with a fresh round counter.")
                chapter_emit.append("\n".join(cb_lines))

            # CURRENT OUTLINE BEAT FOCUS — only relevant in outline
            # mode. Tells the model which beat number to produce
            # next, how many are already in the panel, and the
            # round counter for Phase-1 questions on this beat.
            # OUTLINE SESSION block — exposes the autonomous-system
            # phase + audit so the model picks the right phase tag.
            session_phase = self.context.get(
                "outline_session_phase")
            if session_phase:
                lines = [
                    "\n=== OUTLINE SESSION ===",
                    f"outline_session_phase: \"{session_phase}\"",
                ]
                audit = self.context.get("outline_audit") or []
                if audit and session_phase == "pick_start":
                    lines.append("\nOUTLINE AUDIT (engine-computed):")
                    for entry in audit:
                        lines.append(
                            f"  Beat {entry.get('beat_number')}: "
                            f"{entry.get('title') or '?'} — "
                            f"{entry.get('status')}")
                if session_phase == "beat_refine":
                    user_msg = (
                        self.context.get("user_refine_message")
                        or "").strip()
                    if user_msg:
                        lines.append(
                            f"\nUSER FEEDBACK FOR THIS BEAT:\n"
                            f"  {user_msg[:400]}")
                    draft = self.context.get("current_beat_draft")
                    if isinstance(draft, dict):
                        lines.append(
                            "\nPRIOR DRAFT (refine, don't restart):")
                        # Compact JSON for the model.
                        import json as _json
                        try:
                            lines.append(
                                _json.dumps(draft, indent=2)[:1500])
                        except Exception:
                            pass
                chapter_emit.append("\n".join(lines))

            ob = self.context.get('outline_beat_focus')
            if ob and self.context.get('writer_output_mode') == "outline":
                audit_status = ob.get('audit_status', 'confirmed')
                # Build the "Now produce" line — when we know the
                # specific beat title/stage/description (from the
                # chapter's planning.events), surface them so the
                # model produces the RIGHT beat instead of defaulting
                # to Beat 1's content. Falls back to a number-only
                # line when no plan exists for that slot.
                title = (ob.get("next_beat_title") or "").strip()
                stage = (ob.get("next_beat_stage") or "").strip()
                desc = (ob.get("next_beat_description") or "").strip()
                if title:
                    produce_line = (
                        f"Now produce: Beat {ob['next_beat_number']} "
                        f"— \"{title}\""
                        + (f" [{stage}]" if stage else ""))
                else:
                    produce_line = (
                        f"Now produce: Beat {ob['next_beat_number']}")
                ob_lines = [
                    "\n=== CURRENT OUTLINE BEAT FOCUS "
                    "(per-beat outline) ===",
                    f"audit_status: \"{audit_status}\"",
                    f"Beats already in the Outline tab: "
                    f"{ob['beats_done']}",
                    produce_line,
                ]
                if desc:
                    ob_lines.append(
                        f"  Plan from chapter outline: {desc[:300]}")
                ob_lines += [
                    f"Question round {ob['rounds_for_beat']}/"
                    f"{ob['max_rounds']} for this beat.",
                    f"Hard cap: {ob['max_beats']} beats per chapter "
                    f"(set outline_complete=true at the final beat).",
                ]
                if audit_status == "pending_request":
                    ob_lines.append(
                        "*** FIRST TURN — produce phase=\"audit\" "
                        "now. Look at the PLANNED BEATS list "
                        "below + any existing outline panel "
                        "content + any existing chapter prose. "
                        "Mark each beat as outlined / written / "
                        "pending and set first_pending_beat. Do "
                        "NOT produce phase=questions or "
                        "phase=beat on this turn. ***")
                if ob.get('rounds_for_beat', 0) >= ob.get(
                        'max_rounds', 4):
                    ob_lines.append(
                        "*** ROUND CAP REACHED — produce the beat "
                        "structure for THIS beat now. Do NOT ask more "
                        "questions. Emit phase=beat. ***")
                chapter_emit.append("\n".join(ob_lines))

            # PLANNED BEATS — listed for both outline + writer modes
            # so the audit phase has the full beat plan to work from.
            # The current beat is marked with `→` so the model can
            # find its target without scanning the whole list.
            planned = self.context.get('planned_beats') or []
            if planned:
                pb_lines = [
                    "\n=== PLANNED BEATS "
                    "(→ marks the beat the engine asked you to "
                    "produce) ==="]
                for entry in planned:
                    bn = entry.get('beat_number')
                    title = entry.get('title') or '(untitled)'
                    stage = entry.get('stage') or ''
                    is_current = bool(entry.get('is_current'))
                    arrow = "→" if is_current else " "
                    line = f"  {arrow} Beat {bn}: {title}"
                    if stage:
                        line += f" — {stage}"
                    pb_lines.append(line)
                    desc = entry.get('description') or ''
                    if desc:
                        pb_lines.append(f"      {desc[:200]}")
                chapter_emit.append("\n".join(pb_lines))

            # PRIOR Q&A — writer-mode Phase 1 history so the model
            # can see EXACTLY which questions it already asked and
            # what the user answered. Without this, models cycle on
            # "what POV?" / "which subplot?" turn after turn because
            # they have no memory of having asked. Combined with the
            # engine-side cycling detector (which auto-flips ready
            # if questions repeat), this should fully eliminate the
            # repeat-question problem the user reported.
            qa_log = self.context.get('writer_qa_history') or []
            if qa_log:
                qa_lines = [
                    "\n=== PRIOR Q&A IN THIS WRITING SESSION ==="
                    " (you ALREADY asked these — DO NOT repeat them; "
                    "if you'd ask them again, you have enough — emit "
                    "<context_ready/> and proceed):"
                ]
                for i, entry in enumerate(qa_log, 1):
                    asked = entry.get("questions") or []
                    user_reply = (entry.get("user") or "").strip()
                    qa_lines.append(f"\nTurn {i}:")
                    if asked:
                        qa_lines.append("  Questions you asked:")
                        for q in asked[:6]:
                            qa_lines.append(f"    • {q}")
                    if user_reply:
                        # Cap so a long user reply doesn't dominate
                        snippet = user_reply[:400]
                        qa_lines.append(f"  User answered: {snippet}")
                chapter_emit.append("\n".join(qa_lines))

            # Recent AI insertions in this chapter — lets the model
            # answer follow-ups like "edit that scene you just wrote"
            # by emitting ``<edit_last_insertion>`` with the right
            # index. Records are listed oldest → newest so the index
            # the model passes maps to the visible numbering. Only
            # surfaced for the modes that have the edit tool wired in.
            recent = (self.context.get('recent_insertions') or []
                      if is_chapter_focused else [])
            if recent:
                lines = ["\n=== RECENT AI INSERTIONS (your prior writes "
                         "in this chapter — refer back via index when "
                         "the user asks to edit) ==="]
                for i, rec in enumerate(recent):
                    preview = (rec.get("prose") or "").strip()
                    # Show a short preview so the model can identify
                    # the insertion without dumping the full prose
                    # (it's already in CURRENT CHAPTER CONTENT).
                    if len(preview) > 220:
                        preview = (preview[:120].rstrip()
                                    + " … "
                                    + preview[-80:].lstrip())
                    summary = (rec.get("summary") or "").strip()
                    prompt = (rec.get("prompt") or "").strip()
                    word_n = len((rec.get("prose") or "").split())
                    lines.append(
                        f"[{i}] mode={rec.get('mode', '?')} "
                        f"words={word_n} ts={rec.get('timestamp', '?')}")
                    if prompt:
                        lines.append(
                            f"    user prompt: "
                            f"{prompt[:150]}")
                    if summary:
                        lines.append(
                            f"    summary: {summary[:200]}")
                    lines.append(f"    preview: \"{preview}\"")
                lines.append(
                    "Reference these by index when the user asks to "
                    "edit / refine / add tension / continue from one. "
                    "Emit <edit_last_insertion>{\"index\": N, "
                    "\"instructions\": \"...\"} where N is the [N] "
                    "label above (default 0 = oldest, "
                    f"{len(recent) - 1} = most recent).")
                chapter_emit.append("\n".join(lines))

        # ── Compose final prompt with chapter-first ordering ──────
        # In chapter-focused modes the chapter section leads, then a
        # short header introduces the supporting material so the
        # model knows the role of each block.
        if is_chapter_focused and chapter_parts:
            parts.append(
                "\n=== CHAPTER FOCUS (the active chapter — your "
                "primary subject; everything below SUPPORTS this) ===")
            parts.extend(chapter_parts)
            if story_parts:
                parts.append(
                    "\n=== STORY-WIDE SUPPORTING CONTEXT (supplements "
                    "the chapter focus above; reference as needed, "
                    "do NOT repeat back) ===")
                parts.extend(story_parts)
        elif is_chapter_focused:
            # No chapter context — just emit story_parts so the writer
            # / chapter_focus modes still get their material.
            parts.extend(story_parts)

        # ── Tail blocks (referenced chapter, all_chapters, excerpts) ─
        # Referenced chapter (user asked about a specific chapter by name/number)
        if self.context.get('referenced_chapter'):
            ref = self.context['referenced_chapter']
            parts.append(
                f"\n=== REFERENCED CHAPTER: {ref['title']} (Chapter {ref['number']}) ===\n"
                f"{ref['content']}"
            )

        # All chapters summary (for cross-chapter questions). Skip in
        # chapter-focused modes when previous_chapters_summary already
        # rendered — they overlap heavily (chapter-by-chapter rundown).
        if self.context.get('all_chapters'):
            if not (is_chapter_focused
                    and self.context.get('previous_chapters_summary')):
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

            # Writer mode now uses dedicated JSON-only prompts that
            # share the same Phase-1-questions / Phase-2-output
            # protocol — the only difference is what Phase-2 emits:
            #   * Outline output  → OUTLINE_SYSTEM_PROMPT (one
            #     structured beat per reply)
            #   * Full Text output → WRITER_SYSTEM_PROMPT (one
            #     beat's prose + writing_summary per reply)
            # Both prompts force the model to declare its phase via
            # JSON so questions never leak into the deliverable.
            if self.mode == "writer":
                wmode = self.context.get('writer_output_mode')
                if wmode == "outline":
                    system_prompt = OUTLINE_SYSTEM_PROMPT
                else:
                    system_prompt = WRITER_SYSTEM_PROMPT

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

            # Generate response (with conversation history for multi-turn context).
            # Writer mode produces long-form prose that needs to cover every
            # planned plot event — give it a much larger token budget than
            # the default 2000 (which capped earlier outputs at 600-700
            # words because the model also spent budget on the summary
            # block + ran cautious about length). For local models we also
            # auto-continue on truncation so the model doesn't strand the
            # author with a half-written scene.
            base_max_tokens = int(settings.get("max_tokens", 2000) or 2000)
            if self.mode == "writer":
                # Outline mode: ONE beat at a time. Cap tightly so
                # the model can't physically fit a second beat into
                # its budget — combined with the "ONE beat per
                # reply" prompt rule + the response-side truncation
                # safety net, this keeps each Phase-2 turn focused
                # on a single beat. ~1500 tokens is plenty for one
                # structured beat (heading + 6 bullet sections).
                if (self.context.get('writer_output_mode')
                        == "outline"):
                    effective_max_tokens = min(
                        max(base_max_tokens, 1500), 1800)
                    effective_continue = False
                else:
                    # 6000 tokens ≈ 4500 words — enough for a multi-beat
                    # chapter scene + the summary block. Honor user-set
                    # max_tokens when they've raised it past 6000.
                    effective_max_tokens = max(base_max_tokens, 6000)
                    effective_continue = True
            else:
                effective_max_tokens = base_max_tokens
                effective_continue = False

            # Project-lookup tools: writer / chapter_focus / plot modes
            # all benefit from agentic per-element fetches that
            # complement the RAG baseline. Append the tool docs to
            # the system prompt and route through the pre-flight
            # lookup loop so <lookup_*> tags are dispatched
            # transparently and results are fed back to the model
            # before it produces the final response.
            lookup_modes = {"writer", "chapter_focus", "plot", "worldbuilding"}
            uses_lookups = self.mode in lookup_modes
            if uses_lookups:
                system_prompt = (
                    f"{system_prompt}\n\n{'='*60}\n"
                    f"{LOOKUP_TOOLS_PROMPT_BLOCK}")
            # Edit-last-insertion tool docs — appended for writer +
            # chapter_focus so the model knows to emit
            # ``<edit_last_insertion>`` when the user asks to revise
            # something it previously wrote (instead of just writing
            # a new version inline that the engine can't track).
            if self.mode in ("writer", "chapter_focus"):
                from src.ai.edit_insertion_tool import (
                    EDIT_INSERTION_PROMPT_BLOCK as _EIPB)
                system_prompt = (
                    f"{system_prompt}\n\n{'='*60}\n{_EIPB}")

            history = self.context.get('conversation_history') or []
            if uses_lookups:
                response, _lookup_log = run_with_lookups(
                    llm=llm,
                    prompt=self.message,
                    system_prompt=system_prompt,
                    project=self.context.get('_project'),
                    rag_search=self.context.get('_rag_search'),
                    max_tokens=effective_max_tokens,
                    temperature=settings.get("temperature", 0.7),
                    conversation_history=history,
                    max_lookup_rounds=2,
                    continue_if_truncated=effective_continue,
                )
            else:
                response = llm.generate_text(
                    prompt=self.message,
                    system_prompt=system_prompt,
                    max_tokens=effective_max_tokens,
                    temperature=settings.get("temperature", 0.7),
                    conversation_history=history,
                    continue_if_truncated=effective_continue,
                )

            self.finished.emit(response, system_prompt)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class LongFormWriterWorker(QThread):
    """Background worker that drives a LongFormWriterAgent end-to-end.

    Emits per-beat progress as the agent writes plot point by plot
    point so the UI can stream prose into the editor. Builds its own
    LLM client + RAG provider using the same selection logic the
    chat path uses, so the user's configured plot-task model is
    honoured when set.
    """
    finished = pyqtSignal(object, str)  # (ChapterWritingPlan, full_prose)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    plan_ready = pyqtSignal(object)     # ChapterWritingPlan (post-plan, pre-execute)
    # (index, beat_title, prose, prompt) — prompt is the actual LLM
    # input for this beat so callers can persist (prompt, prose) as
    # training data.
    point_written = pyqtSignal(int, str, str, str)

    def __init__(
        self,
        chapter,
        instructions: str,
        mode: WritingMode,
        existing_text: str = "",
        prior_text: str = "",
        target_points: int = 0,
        project=None,
        rag_provider=None,
        skip_questions: bool = False,
        preplanned: Optional['ChapterWritingPlan'] = None,
    ):
        super().__init__()
        self.chapter = chapter
        self.instructions = instructions
        self.mode = mode
        self.existing_text = existing_text
        self.prior_text = prior_text
        self.target_points = target_points
        self.project = project
        self.rag_provider = rag_provider
        self.skip_questions = skip_questions
        self.preplanned = preplanned

    def _build_llm(self):
        """Build the LLM client following the same logic as ChatWorker."""
        from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
        ai_config = get_ai_config()
        if ai_config.is_ai_disabled():
            return None
        settings = ai_config.get_settings()
        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        local_model_id = settings.get("local_model_id", "")
        if prefer_local and enable_local and local_model_id:
            is_mlx_model = "mlx" in local_model_id.lower()
            hf_config = HuggingFaceConfig(
                model_id=local_model_id,
                use_local=True,
                device=settings.get("local_model_device", "auto"),
                quantization=settings.get(
                    "local_model_quantization", "none")
                if settings.get("local_model_quantization") != "none"
                else None,
                trust_remote_code=settings.get(
                    "local_model_trust_remote_code", False),
            )
            provider = (LLMProvider.MLX_LOCAL if is_mlx_model
                        else LLMProvider.HUGGINGFACE_LOCAL)
            return LLMClient(provider=provider, hf_config=hf_config)
        default_provider = settings.get("default_llm", "claude")
        api_key = ai_config.get_api_key(default_provider)
        if not api_key:
            return None
        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI,
        }
        return LLMClient(
            provider=provider_map.get(default_provider, LLMProvider.CLAUDE))

    def run(self):
        try:
            self.progress.emit("Building writing engine…")
            llm = self._build_llm()
            if llm is None:
                self.error.emit(
                    "Long-form writing requires a configured LLM. "
                    "Enable a model in Settings > AI Settings.")
                return
            agent = LongFormWriterAgent(
                primary_llm=llm,
                project=self.project,
                rag_provider=self.rag_provider,
            )
            if self.preplanned is not None:
                plan = self.preplanned
                self.progress.emit(
                    f"Resuming with preplanned chapter "
                    f"({len(plan.plot_points)} beats)…")
            else:
                self.progress.emit("Planning chapter beats…")
                plan = agent.plan_chapter(
                    chapter=self.chapter,
                    instructions=self.instructions,
                    mode=self.mode,
                    existing_text=self.existing_text,
                    target_points=self.target_points,
                )
            self.plan_ready.emit(plan)

            # If the plan posed questions and the caller didn't say
            # skip, surface them and stop here. The UI will collect
            # answers and re-launch the worker with preplanned=plan
            # (with answers merged) and skip_questions=True.
            if plan.questions and not self.skip_questions:
                self.progress.emit(
                    f"Plan ready — {len(plan.questions)} clarifying "
                    "question(s) for the author.")
                self.finished.emit(plan, "")  # empty prose = waiting on Q&A
                return

            if not plan.plot_points:
                self.error.emit(
                    "Planner did not produce any plot points. Add events "
                    "to the chapter's planning data and try again.")
                return

            def progress_cb(msg: str):
                self.progress.emit(msg)

            def on_point(i: int, point, prose: str, prompt: str = ""):
                self.point_written.emit(i, point.title, prose, prompt)

            full_prose = agent.execute_plan(
                plan=plan,
                progress_cb=progress_cb,
                prior_text=self.prior_text,
                on_point_written=on_point,
            )
            self.progress.emit("Done.")
            self.finished.emit(plan, full_prose)
        except Exception as e:  # pragma: no cover — defensive
            self.error.emit(f"Long-form writing failed: {e}")


class _InsertionEditWorker(QThread):
    """One-shot worker that runs an LLM edit pass on a recorded insertion.

    Builds the same LLM client the chat path uses (cloud or local
    per the user's settings) and emits the raw response. The caller
    handles meta-token sanitisation + degeneration detection before
    applying the result to the editor.
    """
    finished = pyqtSignal(str)  # raw_response
    error = pyqtSignal(str)

    def __init__(self, prompt: str, system_prompt: str):
        super().__init__()
        self.prompt = prompt
        self.system_prompt = system_prompt

    def _build_llm(self):
        """Mirror the LLM-selection logic ChatWorker uses."""
        from src.ai.llm_client import (
            LLMClient, LLMProvider, HuggingFaceConfig)
        ai_config = get_ai_config()
        if ai_config.is_ai_disabled():
            return None
        settings = ai_config.get_settings()
        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        local_model_id = settings.get("local_model_id", "")
        if prefer_local and enable_local and local_model_id:
            is_mlx_model = "mlx" in local_model_id.lower()
            hf_config = HuggingFaceConfig(
                model_id=local_model_id,
                use_local=True,
                device=settings.get("local_model_device", "auto"),
                quantization=settings.get(
                    "local_model_quantization", "none")
                if settings.get("local_model_quantization") != "none"
                else None,
                trust_remote_code=settings.get(
                    "local_model_trust_remote_code", False),
            )
            provider = (LLMProvider.MLX_LOCAL if is_mlx_model
                        else LLMProvider.HUGGINGFACE_LOCAL)
            return LLMClient(provider=provider, hf_config=hf_config)
        default_provider = settings.get("default_llm", "claude")
        api_key = ai_config.get_api_key(default_provider)
        if not api_key:
            return None
        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI,
        }
        return LLMClient(
            provider=provider_map.get(
                default_provider, LLMProvider.CLAUDE))

    def run(self):
        try:
            llm = self._build_llm()
            if llm is None:
                self.error.emit(
                    "Edit aborted — no LLM is configured. Enable a "
                    "model in Settings > AI Settings.")
                return
            response = llm.generate_text(
                prompt=self.prompt,
                system_prompt=self.system_prompt,
                max_tokens=4000,
                temperature=0.6,
                continue_if_truncated=True,
            )
            self.finished.emit(response or "")
        except Exception as e:  # pragma: no cover — defensive
            self.error.emit(f"Edit failed: {e}")


class _SidebarContainer(QWidget):
    """Collapsible host for the right-hand AI Assistant + Outline tabs.

    The chat widget no longer collapses on its own; this container
    owns the expand/collapse state for the whole sidebar. Collapsed
    state shows a thin vertical strip with a single expand button
    so the user can always reclaim the sidebar without hunting for a
    menu item.
    """

    EXPANDED_MIN_W = 320
    EXPANDED_MAX_W = 460
    COLLAPSED_W = 36

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        self.setObjectName("sidebarContainer")
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Collapsed-state vertical button. Hidden until the user
        # collapses; clicking it expands the sidebar back.
        self.collapsed_btn = QPushButton("◀\nA\nI\n+\nO")
        self.collapsed_btn.setToolTip(
            "Show AI Assistant + Outline (Ctrl+\\)")
        self.collapsed_btn.setStyleSheet(
            "QPushButton { background-color: #4f46e5; color: white; "
            " border: none; border-radius: 6px; font-size: 11px; "
            " font-weight: bold; padding: 8px 4px; min-height: 90px; "
            " text-align: center; } "
            "QPushButton:hover { background-color: #4338ca; }")
        self.collapsed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapsed_btn.clicked.connect(self._expand)
        self.collapsed_btn.setVisible(False)
        layout.addWidget(
            self.collapsed_btn, 0, Qt.AlignmentFlag.AlignTop)

        # Expanded content — header bar with collapse toggle, then
        # the wrapped tab widget below.
        self._expanded = QWidget()
        ex_layout = QVBoxLayout(self._expanded)
        ex_layout.setContentsMargins(4, 4, 4, 4)
        ex_layout.setSpacing(4)

        header = QFrame()
        header.setStyleSheet(
            "QFrame { background-color: #4f46e5; border-radius: 6px; }")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 4, 10, 4)
        h_layout.setSpacing(8)

        self._collapse_btn = QPushButton("▶  Hide")
        self._collapse_btn.setToolTip(
            "Collapse the sidebar (Ctrl+\\)")
        self._collapse_btn.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setStyleSheet(
            "QPushButton { background-color: transparent; "
            " color: white; border: none; font-size: 12px; "
            " font-weight: 600; padding: 2px; } "
            "QPushButton:hover { color: #e0e7ff; }")
        self._collapse_btn.clicked.connect(self._collapse)
        h_layout.addStretch()
        h_layout.addWidget(self._collapse_btn)

        ex_layout.addWidget(header)
        ex_layout.addWidget(content, stretch=1)

        layout.addWidget(self._expanded, stretch=1)

        self.setMinimumWidth(self.EXPANDED_MIN_W)
        self.setMaximumWidth(self.EXPANDED_MAX_W)

    # ── public API ────────────────────────────────────────────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def expand(self) -> None:
        if self._collapsed:
            self._expand()

    def collapse(self) -> None:
        if not self._collapsed:
            self._collapse()

    def toggle(self) -> None:
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    # ── internals ─────────────────────────────────────────────────

    def _collapse(self) -> None:
        self._collapsed = True
        self._expanded.setVisible(False)
        self.collapsed_btn.setVisible(True)
        self.setMinimumWidth(self.COLLAPSED_W)
        self.setMaximumWidth(self.COLLAPSED_W + 6)

    def _expand(self) -> None:
        self._collapsed = False
        self._expanded.setVisible(True)
        self.collapsed_btn.setVisible(False)
        self.setMinimumWidth(self.EXPANDED_MIN_W)
        self.setMaximumWidth(self.EXPANDED_MAX_W)


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
        self._pending_output_mode: str = "full_text"
        self._pending_outline_action: str = "populate"
        self._pending_chat_message: str = ""

        # Conversation history for multi-turn chat (user+assistant pairs)
        # Max 12 turns kept; older turns are dropped (compaction).
        self._chat_history: list = []
        self._MAX_CHAT_TURNS = 12

        # Writer-insertion registry — records every AI insertion into
        # the manuscript so the user can refer back ("edit that", "add
        # more tension to the scene you just wrote") and the engine
        # can target the exact range with the original prompt as
        # context. Keyed by chapter_id; each entry is the most recent
        # ``_MAX_INSERTIONS_PER_CHAPTER`` insertions in chronological
        # order.
        self._writer_insertions: Dict[str, list] = {}
        self._MAX_INSERTIONS_PER_CHAPTER = 8

        # Writer-mode pre-write phase: per-chapter set of IDs the
        # agent has flagged as "context_ready" by emitting the
        # <context_ready/> signal. While a chapter ID is NOT in this
        # set, writer mode is in the PRE-WRITE phase (coverage check,
        # lookups, clarifying questions; no prose). After the agent
        # signals ready, writer mode proceeds to write the remaining
        # beats. Cleared when the user opens a different chapter.
        self._writer_ready_chapters: set = set()
        # Per-chapter Q&A log for writer mode's Phase 1. Each entry
        # records (user_message, assistant_response, questions_asked)
        # so the engine can: surface a "PRIOR Q&A" block to the
        # model to prevent duplicate questions, and detect cycling
        # (model asking the same questions again → force progression).
        self._writer_qa_log: Dict[str, list] = {}

        # Per-chapter per-beat state for writer mode's per-beat
        # orchestration. Each entry tracks which remaining beat is
        # currently in focus, how many Q&A rounds have been spent on
        # it (hard cap 4), whether a forced write is queued, and the
        # full list of remaining beats at the start of the session
        # so progress can be surfaced to the user. Cleared when all
        # beats are written or the user resets.
        self._writer_beat_state: Dict[str, dict] = {}
        self._WRITER_MAX_ROUNDS_PER_BEAT = 4

        # Per-chapter OUTLINE-generation state. Mirrors
        # _writer_beat_state but for outline-mode runs: tracks how
        # many beats have been outlined so far, the round counter
        # for the current beat, and whether the agent has signalled
        # <outline_complete/>. Drives the same per-beat orchestration
        # the writer uses, but the deliverable is one BEAT'S OUTLINE
        # structure (not prose) per Phase-2 turn — see
        # OUTLINE_MODE_PROMPT_BLOCK.
        self._outline_beat_state: Dict[str, dict] = {}
        self._OUTLINE_MAX_ROUNDS_PER_BEAT = 4
        # Hard cap on the number of beats we'll generate before
        # giving up if the model never emits <outline_complete/>.
        self._OUTLINE_MAX_BEATS = 30
        # Per-chapter OUTLINE SESSION state — autonomous-system
        # state machine that drives the chat flow:
        #   await_user_confirm_start → await_user_proceed →
        #   beat_questions ↔ await_user_answer → beat_drafted ↔
        #   await_user_refine_or_proceed → … → await_user_apply_choice
        # Drafted beats accumulate in ``beats_staging`` (the chat
        # shows their JSON; the panel is NOT touched). The user
        # picks apply mode at the end (append / replace / overwrite)
        # and the engine writes everything to the OutlinePanel in
        # one shot. See _handle_chat_message outline branch.
        self._outline_session_state: Dict[str, dict] = {}
        # Per-chapter focused-beat AI session. Set when the user
        # clicks ✨ on a beat in the outline panel. The next AI
        # response with phase="beat" for this chapter is written
        # DIRECTLY into the named beat's body in the panel (instead
        # of going through the normal staging/apply chain). The
        # entry is cleared after the beat is applied OR when the
        # user clicks ✨ on a different beat.
        # Shape: {chapter_id: {"beat_index": int, "beat_title": str,
        #                       "started_at": float}}
        self._focused_beat_ai: Dict[str, dict] = {}

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

        # Apply modern stylesheet to MainWindow.
        self.setStyleSheet(get_modern_style())
        # ALSO apply at the QApplication level so the QToolTip rules
        # in the modern stylesheet actually reach tooltip popups.
        # Tooltips are independent top-level widgets, not descendants
        # of MainWindow — without an app-level stylesheet they fall
        # back to the platform default (on macOS that's a near-
        # invisible system tooltip).
        try:
            qapp = QApplication.instance()
            if qapp is not None:
                qapp.setStyleSheet(get_modern_style())
        except Exception:
            pass
        # Belt-and-braces: force the tooltip text/background colors
        # via QPalette. The modern stylesheet sets
        #   QWidget  { color: #1a1a1a }  (near-black text everywhere)
        #   QToolTip { color: white;  background-color: #1a1a1a }
        # but Qt's QSS resolution lets the QWidget rule win for
        # tooltip popups in some cases — the result is dark text on
        # the dark tooltip background, so the tooltip looks blank
        # even though the text is rendered. QPalette overrides the
        # stylesheet for these two roles regardless of selector
        # specificity, so the beat-card ↑ ↓ × ✨ tooltips actually
        # show their text.
        try:
            from PyQt6.QtGui import QColor, QPalette
            from PyQt6.QtWidgets import QToolTip
            tt_palette = QToolTip.palette()
            tt_palette.setColor(
                QPalette.ColorRole.ToolTipBase, QColor("#1a1a1a"))
            tt_palette.setColor(
                QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
            QToolTip.setPalette(tt_palette)
        except Exception:
            pass

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

        # Sidebar — chat assistant + chapter outline as stacked
        # tabs sharing the same right-hand slot. The outline used to
        # live inside the chat splitter; lifting it to a peer tab
        # gives it room to breathe and lets the user switch between
        # talking to the AI and editing the outline without losing
        # either's vertical real estate.
        from src.ui.outline_panel import OutlinePanel
        self.chat_widget = ChatWidget()
        self.outline_panel = OutlinePanel()
        # Expose the panel through chat_widget too so existing call
        # sites (`self.chat_widget.outline_panel`) keep working
        # without a sweep — the panel is now hosted in a sibling
        # tab, but the reference is shared.
        self.chat_widget.outline_panel = self.outline_panel

        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setDocumentMode(True)
        self.sidebar_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #e5e7eb; "
            "  border-radius: 6px; background: white; } "
            "QTabBar::tab { padding: 6px 12px; "
            "  font-size: 11px; font-weight: 500; "
            "  color: #4b5563; background: #f3f4f6; "
            "  border: 1px solid #e5e7eb; "
            "  border-bottom: none; "
            "  border-top-left-radius: 6px; "
            "  border-top-right-radius: 6px; "
            "  margin-right: 2px; } "
            "QTabBar::tab:selected { background: white; "
            "  color: #4f46e5; } "
            "QTabBar::tab:hover:!selected { color: #4f46e5; }")
        self.sidebar_tabs.addTab(self.chat_widget, "💬 AI Assistant")
        self.sidebar_tabs.addTab(self.outline_panel, "📋 Chapter Outline")

        # Sidebar container — owns the collapse/expand state for the
        # whole AI assistant + outline area as a single unit. When
        # collapsed it shrinks to a thin vertical strip with a single
        # expand button; when expanded it shows the tab strip + the
        # active tab content.
        self.sidebar_container = _SidebarContainer(self.sidebar_tabs)

        # Add to splitter
        self.main_splitter.addWidget(self.tab_widget)
        self.main_splitter.addWidget(self.sidebar_container)

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
        # Sync the AI Assistant's outline panel to the newly-loaded
        # chapter — load that chapter's planning.outline into the
        # panel and bind autosave back to it.
        self.manuscript_editor.chapter_switched.connect(
            self._sync_outline_panel_to_chapter)
        # Persist user edits in the outline panel back to the
        # current chapter's planning.outline (debounced).
        self.chat_widget.outline_panel.outline_changed.connect(
            self._on_outline_panel_edited)
        # When the user clicks the per-beat ✨ AI-help button on a
        # beat in the chapter planner, route into the outline-mode
        # chat focused on that beat.
        self.manuscript_editor.beat_ai_help_requested.connect(
            self._handle_beat_ai_help_requested)
        # When the user clicks "Clear Plot Arc" + confirms, drop
        # the chapter's events + outline AND blank the AI-Assistant
        # outline panel for that chapter.
        self.manuscript_editor.events_cleared.connect(
            self._handle_chapter_events_cleared)
        # Auto-sync new beats from the outline panel into
        # chapter.planning.events whenever the panel changes — this
        # is what "slots a user-created beat into the plan" means.
        self.chat_widget.outline_panel.outline_changed.connect(
            self._sync_panel_beats_to_planning_events)
        # Per-beat ✨ AI-help button on a card → route to outline chat.
        self.chat_widget.outline_panel.beat_ai_help_requested.connect(
            self._handle_panel_beat_ai_help)

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

    def _sync_outline_panel_to_chapter(self) -> None:
        """Bind the AI Assistant's outline panel to the current chapter.

        Fired on chapter switch. Loads the new chapter's
        ``planning.outline`` into the panel; if no chapter is open
        the panel is reset to its disabled placeholder state.

        When ``planning.outline`` is empty but ``planning.events``
        already lists beats, hydrate the panel with one
        ``## [ ] Beat N: title`` heading per event so the user sees
        the existing beat structure as a checklist immediately
        (instead of an empty panel that would mistakenly trigger
        the "no outline yet" auto-route on the next writer call).
        The hydrated text is treated like any user-typed outline —
        it autosaves back into ``planning.outline`` on first edit.
        """
        panel = getattr(self.chat_widget, 'outline_panel', None)
        if panel is None:
            return
        ce = getattr(self.manuscript_editor,
                     'current_chapter_editor', None)
        if ce is None or not getattr(ce, 'chapter', None):
            panel.load_chapter(None, None, None)
            return
        chapter = ce.chapter
        outline_text = ""
        title = getattr(chapter, 'title', '') or ''
        if (hasattr(chapter, 'planning')
                and chapter.planning is not None):
            outline_text = (
                getattr(chapter.planning, 'outline', '') or '')
            # No text outline yet — but the chapter may already have
            # a structured beat list in planning.events. Render those
            # as outline markdown so the panel shows them and the
            # writer treats the chapter as outlined.
            if not outline_text.strip():
                events = getattr(chapter.planning, 'events', None)
                if events:
                    outline_text = self._events_to_outline_markdown(
                        events)
        panel.load_chapter(chapter.id, title, outline_text)

    def _log_beat_state(self,
                        mode: str,
                        chapter_id: str,
                        event: str = "tick") -> None:
        """Print a uniform beat-state line to the console.

        Helps debug "why is the model on Beat 1 again?" by surfacing
        every transition: state init, audit landed, user confirm,
        beat/prose landed, advance. The line is grep-friendly so you
        can ``python main.py | grep [beat-log]`` to follow the flow.

        Format:
            [beat-log mode=outline ch=ch_abc event=audit_landed
             beat=4 done=3 rounds=0/4 audit=pending_user
             action=populate title='Witness Encounter']
        """
        if mode == "outline":
            state = self._outline_beat_state.get(chapter_id) or {}
        else:
            state = self._writer_beat_state.get(chapter_id) or {}
        beat_no = state.get("current_beat_number", "?")
        rounds = state.get("rounds_for_beat", 0)
        # Defensive default — test fixtures sometimes bypass
        # __init__ via __new__, in which case QMainWindow's
        # __getattribute__ raises rather than returning the default,
        # so getattr(default=…) doesn't help. Try/except is the
        # robust path.
        try:
            cap = state.get(
                "max_rounds",
                self._OUTLINE_MAX_ROUNDS_PER_BEAT
                if mode == "outline"
                else self._WRITER_MAX_ROUNDS_PER_BEAT)
        except Exception:
            cap = state.get("max_rounds", 4)
        audit = state.get("audit_status", "?")
        action = state.get("outline_action", "-")
        complete = state.get("complete", False)
        in_progress = state.get("in_progress", False)
        # Title for the current beat (best-effort; safe against
        # out-of-range current_idx after _advance_beat hits the end).
        title = ""
        if mode == "writer":
            remaining = state.get("remaining_beats") or []
            idx = state.get("current_idx", 0)
            if 0 <= idx < len(remaining):
                cur = remaining[idx]
                if isinstance(cur, dict):
                    title = (cur.get("text") or "").strip()
            done = f"{idx}/{len(remaining)}"
        else:
            done = state.get("beats_done", 0)
        print(
            f"[beat-log mode={mode} ch={chapter_id} "
            f"event={event} beat={beat_no} done={done} "
            f"rounds={rounds}/{cap} audit={audit} "
            f"action={action} in_progress={in_progress} "
            f"complete={complete}"
            + (f" title={title!r}]" if title else "]"),
            flush=True)

    def _compute_beat_audit_deterministic(
            self,
            chapter,
            output_mode: str,
            panel=None) -> list:
        """Engine-computed per-beat audit. No LLM call.

        For each event in ``chapter.planning.events``:
          - Outline mode: status = "outlined" if its title appears
            as a ``## `` heading in the panel (or in
            chapter.planning.outline as a fallback), else "pending".
          - Full Text mode: status = "written" if matched by
            ``_compute_chapter_coverage`` (text-content overlap),
            else "pending".

        Returns a list of dicts: ``{beat_number, title, stage,
        description, status, evidence}`` in plot order. Empty list
        when the chapter has no planned events.
        """
        if chapter is None:
            return []
        planning = getattr(chapter, "planning", None)
        if planning is None:
            return []
        events = list(getattr(planning, "events", []) or [])
        if not events:
            return []

        # Build the set of titles the engine will treat as "done"
        # for this mode. Titles compared case-insensitively, with
        # the leading "Beat N:" prefix stripped so panel headings
        # like ``## [ ] Beat 1: Arrival`` match a planned event
        # whose text is just ``Arrival``.
        import re as _re
        done_titles: set = set()

        def _norm_title(s: str) -> str:
            t = (s or "").strip().lower()
            # Strip "beat N: " prefix if present.
            t = _re.sub(r"^beat\s+\d+\s*[:\-—]\s*", "", t)
            # Strip trailing " — stage".
            t = _re.sub(r"\s+[—\-]\s+\w+$", "", t)
            return t.strip()

        if output_mode == "outline":
            outline_text = ""
            if panel is not None:
                outline_text = panel.get_outline_text() or ""
            if not outline_text.strip():
                outline_text = (
                    getattr(planning, "outline", "") or "")
            if outline_text.strip():
                from src.ui.outline_panel import _parse_beats
                _, parsed_beats = _parse_beats(outline_text)
                for b in parsed_beats:
                    done_titles.add(_norm_title(b.title))
        else:
            coverage = self._compute_chapter_coverage(chapter)
            for ev in coverage.get("covered_events", []) or []:
                done_titles.add(_norm_title(ev.get("text", "")))

        audit = []
        for i, ev in enumerate(events, 1):
            text = (getattr(ev, "text", "") or "").strip()
            stage = (getattr(ev, "stage", "") or "").strip()
            desc = (getattr(ev, "description", "") or "").strip()
            norm = _norm_title(text)
            if output_mode == "outline":
                status = ("outlined" if norm in done_titles
                          else "pending")
                evidence = (
                    "Heading found in outline panel."
                    if status == "outlined"
                    else "No matching heading in panel.")
            else:
                status = ("written" if norm in done_titles
                          else "pending")
                evidence = (
                    "Beat title matched in chapter content."
                    if status == "written"
                    else "No matching prose in chapter content.")
            audit.append({
                "beat_number": i,
                "title": text,
                "stage": stage,
                "description": desc,
                "status": status,
                "evidence": evidence,
            })
        return audit

    # ── Outline session state machine ────────────────────────────
    #
    # The outline flow is an autonomous system with explicit phases.
    # Each user message is routed by ``session["phase"]``. Drafted
    # beats accumulate in ``session["staging"]`` until the user
    # picks an apply mode at the end.

    _OUTLINE_PHASE_PICK_START      = "await_user_confirm_start"
    _OUTLINE_PHASE_AWAIT_PROCEED   = "await_user_proceed"
    _OUTLINE_PHASE_BEAT_QUESTIONS  = "beat_questions"
    _OUTLINE_PHASE_BEAT_DRAFTED    = "await_user_refine_or_proceed"
    _OUTLINE_PHASE_AWAIT_APPLY     = "await_user_apply_choice"
    _OUTLINE_PHASE_DONE            = "done"

    def _dispatch_outline_session_turn(
            self,
            chapter_id: str,
            chapter,
            message: str,
            context: dict) -> None:
        """Route this user message based on the outline session phase.

        Sets ``context["_outline_session_send_to_llm"] = True`` when
        the LLM should be called this turn; otherwise the engine
        handles the message locally (e.g. "proceed", "looks good",
        "apply append") and the caller short-circuits.
        """
        s = self._outline_session(chapter_id)
        cmd = self._outline_chat_command(message)

        # PHASE: fresh / never-started → kick off pick_start.
        if s.get("phase") is None and not s.get("started"):
            self._outline_pick_start_kickoff(
                chapter_id, chapter, context)
            self._outline_set_phase(
                chapter_id,
                # Stay in "fresh" until the model returns;
                # the response handler flips to PICK_START.
                "await_pick_start_response",
                log_event="kickoff_pick_start")
            context["_outline_session_send_to_llm"] = True
            return

        phase = s.get("phase")

        # PHASE: pick_start → user is confirming/correcting.
        if phase == self._OUTLINE_PHASE_PICK_START:
            # Approval phrase → keep current_beat_number, advance.
            approve = self._is_simple_approval(message)
            override = self._parse_user_beat_override(message)
            if override is not None:
                events = list(getattr(
                    chapter.planning, "events", []) or [])
                if 1 <= override <= len(events):
                    s["current_beat_number"] = override
                    s["current_beat_index"] = override - 1
            elif not approve:
                # Treat anything else as a free-form correction —
                # default behavior is to accept current suggestion.
                pass
            cur = s.get("current_beat_number") or 1
            self.chat_widget.add_message(
                "Assistant",
                f"_Starting at **Beat {cur}**. Send **\"proceed\"** "
                f"to begin the per-beat questions._")
            self._outline_set_phase(
                chapter_id,
                self._OUTLINE_PHASE_AWAIT_PROCEED,
                log_event="confirmed_start")
            context["_outline_session_send_to_llm"] = False
            return

        # PHASE: await_proceed → user types proceed → start Phase 1.
        if phase == self._OUTLINE_PHASE_AWAIT_PROCEED:
            if cmd == "proceed":
                self._outline_set_phase(
                    chapter_id,
                    self._OUTLINE_PHASE_BEAT_QUESTIONS,
                    log_event="enter_beat_questions")
                # Surface the current beat in context for the LLM.
                self._inject_outline_beat_context(
                    context, s, chapter, mode="beat_questions")
                context["_outline_session_send_to_llm"] = True
                return
            else:
                # Any other input → coach the user.
                self.chat_widget.add_message(
                    "Assistant",
                    "_Send **\"proceed\"** to begin questioning the "
                    "starting beat._")
                context["_outline_session_send_to_llm"] = False
                return

        # PHASE: beat_questions → either user is answering (LLM)
        # or saying proceed to skip to write.
        if phase == self._OUTLINE_PHASE_BEAT_QUESTIONS:
            if cmd == "proceed":
                # User wants to skip Q&A and write the beat now.
                self._inject_outline_beat_context(
                    context, s, chapter, mode="beat_write_force")
            else:
                s["rounds_for_beat"] += 1
                if s["rounds_for_beat"] >= s["max_rounds"]:
                    # Force write on round cap.
                    self._inject_outline_beat_context(
                        context, s, chapter,
                        mode="beat_write_force")
                else:
                    self._inject_outline_beat_context(
                        context, s, chapter, mode="beat_questions")
            context["_outline_session_send_to_llm"] = True
            return

        # PHASE: beat_drafted → user proceeds (next beat / apply)
        # OR refines (LLM call).
        if phase == self._OUTLINE_PHASE_BEAT_DRAFTED:
            if cmd == "proceed":
                # Try to advance to next pending beat. If none, go
                # to apply phase.
                advanced = self._outline_advance_to_next_beat(
                    chapter_id, chapter)
                if advanced:
                    self._outline_set_phase(
                        chapter_id,
                        self._OUTLINE_PHASE_BEAT_QUESTIONS,
                        log_event="advance_next_beat")
                    self._inject_outline_beat_context(
                        context, s, chapter, mode="beat_questions")
                    context["_outline_session_send_to_llm"] = True
                else:
                    self._outline_set_phase(
                        chapter_id,
                        self._OUTLINE_PHASE_AWAIT_APPLY,
                        log_event="enter_await_apply")
                    self.chat_widget.add_message(
                        "Assistant",
                        f"**All {len(s['staging'])} beats drafted "
                        f"and in staging.** How should I apply "
                        f"them to the Outline tab?\n\n"
                        f"• Reply **\"append\"** to add the staged "
                        f"beats to the end of the existing outline.\n"
                        f"• Reply **\"replace\"** to replace the "
                        f"existing outline with these beats.\n"
                        f"• Reply **\"overwrite\"** to clear the "
                        f"panel and write these beats fresh.")
                    context["_outline_session_send_to_llm"] = False
                return
            # Anything else → refine the current beat.
            self._inject_outline_beat_context(
                context, s, chapter, mode="beat_refine",
                refine_message=message)
            context["_outline_session_send_to_llm"] = True
            return

        # PHASE: await_apply → user picks apply mode.
        if phase == self._OUTLINE_PHASE_AWAIT_APPLY:
            if cmd in ("apply_append", "apply_replace",
                       "apply_overwrite"):
                self._outline_apply_to_panel(chapter_id, cmd)
                context["_outline_session_send_to_llm"] = False
                return
            else:
                self.chat_widget.add_message(
                    "Assistant",
                    "_Reply **\"append\"**, **\"replace\"**, or "
                    "**\"overwrite\"** to apply the staged outline._")
                context["_outline_session_send_to_llm"] = False
                return

        # Fallback: unknown phase → kick off fresh.
        self._outline_session_reset(chapter_id)
        self._dispatch_outline_session_turn(
            chapter_id, chapter, message, context)

    @staticmethod
    def _is_simple_approval(message: str) -> bool:
        if not message:
            return False
        s = message.strip().lower().rstrip(".!?")
        return s in (
            "looks good", "ok", "okay", "yes", "y",
            "good", "great", "perfect", "lgtm",
            "confirm", "confirmed", "accept", "accepted",
            "proceed", "go", "go ahead")

    @staticmethod
    def _parse_user_beat_override(message: str) -> Optional[int]:
        """User says 'start at Beat 3' / 'use beat 5' / 'Beat 2' → returns N.

        Tolerates a range of natural phrasings:
          - "start at beat 3", "start with beat 3"
          - "use beat 5", "begin at 5", "begin with beat 5"
          - "let's start with 4", "go to beat 6"
          - "beat 2" alone, or just "2" when the message is short
        """
        if not message:
            return None
        import re as _re
        s = message.strip()
        # Direct beat reference (most explicit).
        m = _re.search(r"beat\s+(\d+)\b", s, _re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        # "start/begin/use/go (at/with/to) N"
        m = _re.search(
            r"(?:start|begin|use|go|jump|skip)\s+"
            r"(?:to\s+|at\s+|with\s+)?(\d+)\b",
            s, _re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        # Bare number when the message is short — likely the user
        # just typing "3" to mean Beat 3.
        if len(s) <= 4 and s.strip().isdigit():
            try:
                return int(s.strip())
            except Exception:
                pass
        return None

    def _inject_outline_beat_context(
            self,
            context: dict,
            session: dict,
            chapter,
            mode: str,
            refine_message: str = "") -> None:
        """Stamp current beat info + session phase into context."""
        cur_no = session.get("current_beat_number")
        events = list(getattr(
            chapter.planning, "events", []) or [])
        if cur_no and 1 <= cur_no <= len(events):
            ev = events[cur_no - 1]
            context["outline_beat_focus"] = {
                "beats_done": len(session.get("staging") or []),
                "next_beat_number": cur_no,
                "next_beat_title": (
                    getattr(ev, "text", "") or "").strip(),
                "next_beat_stage": (
                    getattr(ev, "stage", "") or "").strip(),
                "next_beat_description": (
                    getattr(ev, "description", "") or "").strip(),
                "rounds_for_beat": session.get(
                    "rounds_for_beat", 0),
                "max_rounds": session.get(
                    "max_rounds",
                    self._OUTLINE_MAX_ROUNDS_PER_BEAT),
                "max_beats": self._OUTLINE_MAX_BEATS,
                "audit_status": "confirmed",
            }
        # Surface the titles of beats already in staging — the
        # priority directive at the top of the prompt uses this to
        # tell the model "don't redo these".
        context["outline_staged_titles"] = [
            f"Beat {entry.get('beat_number')}: "
            f"{(entry.get('title') or '').strip()}"
            for entry in (session.get("staging") or [])
            if entry.get("beat_number") != cur_no
        ]
        # Filter PLANNED BEATS to a useful slice — full data for
        # the current beat + ±1 neighbour titles. Stops the full
        # plot list from competing for the model's attention.
        if events and cur_no:
            slim = []
            for i, ev in enumerate(events, 1):
                slim.append({
                    "beat_number": i,
                    "title": (
                        getattr(ev, "text", "") or "").strip(),
                    "stage": (
                        getattr(ev, "stage", "") or "").strip(),
                    # Only include the description for the CURRENT
                    # beat so the model isn't pulled toward
                    # earlier-beat detail.
                    "description": (
                        (getattr(ev, "description", "") or "").strip()
                        if i == cur_no else ""),
                    "is_current": (i == cur_no),
                })
            context["planned_beats"] = slim
        context["outline_session_phase"] = (
            "beat_write" if mode == "beat_write_force"
            else mode)
        if mode == "beat_refine" and refine_message:
            # Surface the prior draft so the model sees what to
            # iterate on.
            for entry in session.get("staging") or []:
                if entry.get("beat_number") == cur_no:
                    context["current_beat_draft"] = entry.get(
                        "json")
                    break
            context["user_refine_message"] = refine_message

    def _outline_session(self, chapter_id: str) -> dict:
        """Return the outline session for this chapter (creating if absent)."""
        s = self._outline_session_state.get(chapter_id)
        if s is None:
            s = {
                "phase": None,        # None means "fresh — kick off pick_start on next user msg"
                "current_beat_number": None,  # 1-based; from chapter.planning.events
                "current_beat_index": None,   # 0-based index into events
                "rounds_for_beat": 0,
                "max_rounds": self._OUTLINE_MAX_ROUNDS_PER_BEAT,
                "audit": [],
                "staging": [],        # list of {beat_number, title, stage, json}
                "started": False,
            }
            self._outline_session_state[chapter_id] = s
        return s

    def _outline_session_reset(self, chapter_id: str) -> None:
        self._outline_session_state.pop(chapter_id, None)

    def _outline_set_phase(self,
                            chapter_id: str,
                            phase: str,
                            log_event: str = "") -> dict:
        s = self._outline_session(chapter_id)
        s["phase"] = phase
        if log_event:
            print(
                f"[outline-session ch={chapter_id} "
                f"phase={phase} event={log_event} "
                f"current_beat={s.get('current_beat_number')} "
                f"rounds={s['rounds_for_beat']}/{s['max_rounds']} "
                f"staging={len(s['staging'])}]",
                flush=True)
        return s

    def _outline_pick_start_kickoff(
            self,
            chapter_id: str,
            chapter,
            context: dict) -> None:
        """Prepare context for the model's start-suggestion call.

        Engine computes the deterministic audit + sends it as
        context. Model returns ``phase: "start_suggestion"`` with
        ``suggested_beat_number``. Engine surfaces to user.
        """
        panel = getattr(self.chat_widget, "outline_panel", None)
        audit = self._compute_beat_audit_deterministic(
            chapter, "outline", panel=panel)
        s = self._outline_session(chapter_id)
        s["audit"] = audit
        s["started"] = True
        # Tell the model what we want via the prompt context.
        context["outline_session_phase"] = "pick_start"
        context["outline_audit"] = audit
        context["outline_session_staging_count"] = len(s["staging"])

    def _outline_chat_command(self, message: str) -> Optional[str]:
        """Recognise the user's command words for the session.

        Returns one of: "proceed", "apply_append", "apply_replace",
        "apply_overwrite", or None.
        """
        if not message:
            return None
        s = message.strip().lower().rstrip(".!?")
        if s in ("proceed", "next", "go", "continue", "ok proceed",
                 "go ahead", "next beat"):
            return "proceed"
        if s in ("apply append", "append"):
            return "apply_append"
        if s in ("apply replace", "replace"):
            return "apply_replace"
        if s in ("apply overwrite", "overwrite", "apply"):
            return "apply_overwrite"
        return None

    def _outline_advance_to_next_beat(self,
                                        chapter_id: str,
                                        chapter) -> bool:
        """Move current_beat_* to the next pending beat.

        Returns True when a new beat was selected; False when the
        list is exhausted (caller should transition to apply phase).
        """
        s = self._outline_session(chapter_id)
        events = list(getattr(
            getattr(chapter, "planning", None), "events",
            []) or [])
        if not events:
            return False
        # Treat any beat we haven't drafted yet AND that wasn't
        # marked outlined/written by the deterministic audit as
        # eligible. This way previously-outlined beats stay skipped.
        drafted_numbers = {
            b["beat_number"] for b in s["staging"]
        }
        already_done_numbers = set()
        for entry in s.get("audit") or []:
            if entry.get("status") in ("outlined", "written"):
                already_done_numbers.add(
                    entry.get("beat_number"))
        cur = s.get("current_beat_number") or 0
        for i, ev in enumerate(events, 1):
            if i <= cur:
                continue
            if i in drafted_numbers:
                continue
            if i in already_done_numbers:
                continue
            s["current_beat_number"] = i
            s["current_beat_index"] = i - 1
            s["rounds_for_beat"] = 0
            return True
        return False

    def _build_outline_apply_text(
            self, staging: list) -> str:
        """Build the markdown body to apply to the panel.

        Beats are emitted in plot order (sorted by ``beat_number``)
        regardless of the order the user drafted them. This is what
        keeps the final outline coherent even when the user starts
        at Beat 5 and then loops back to Beat 1.
        """
        if not staging:
            return ""
        ordered = sorted(
            staging,
            key=lambda e: (
                e.get("beat_number")
                if isinstance(e.get("beat_number"), int)
                else 9999))
        parts = []
        for entry in ordered:
            beat_json = entry.get("json") or {}
            md = self._outline_beat_json_to_markdown(
                beat_json,
                fallback_number=entry["beat_number"],
                force_number=True,
                force_title=entry.get("title", ""),
                force_stage=entry.get("stage", ""))
            parts.append(md.rstrip())
        return "\n\n".join(parts) + "\n"

    def _merge_outline_with_existing_panel(
            self,
            staging: list,
            panel) -> str:
        """For APPEND mode: merge staged beats with existing panel beats.

        Parses the panel's existing beats by number, overlays the
        staged ones (staging wins on conflict), and re-renders the
        whole list in plot order. This stops append mode from
        scrambling existing content (e.g. existing Beat 5 followed
        by newly-staged Beat 1 → would land [5, 1] without the
        merge).

        When a beat exists in the panel but NOT in staging, the
        engine reuses the panel's raw markdown for that beat
        verbatim (no JSON to re-render from).
        """
        if panel is None:
            return self._build_outline_apply_text(staging)
        existing_text = (panel.get_outline_text() or "").strip()
        if not existing_text:
            return self._build_outline_apply_text(staging)
        from src.ui.outline_panel import _parse_beats
        preamble, panel_beats = _parse_beats(existing_text)

        import re as _re
        # Map beat_number → (raw_panel_block, marker_checked)
        # for each beat already in the panel. We extract the
        # "Beat N" number from the heading text; beats without a
        # detectable number get appended at the end (best-effort).
        panel_by_number: dict = {}
        unnumbered: list = []
        for pb in panel_beats:
            m = _re.match(
                r"^beat\s+(\d+)\s*[:\-—]?\s*(.*)$",
                pb.title.strip(), _re.IGNORECASE)
            if m:
                try:
                    n = int(m.group(1))
                    body = "\n".join(pb.body_lines).rstrip()
                    marker = "[x]" if pb.checked else "[ ]"
                    raw = (
                        f"## {marker} Beat {n}: {m.group(2).strip()}"
                        + (f"\n{body}" if body else ""))
                    panel_by_number[n] = raw
                    continue
                except Exception:
                    pass
            # No number → keep separate
            unnumbered.append(pb)

        # Map beat_number → rendered markdown for each staged beat.
        staged_md: dict = {}
        for entry in staging:
            n = entry.get("beat_number")
            if not isinstance(n, int):
                continue
            md = self._outline_beat_json_to_markdown(
                entry.get("json") or {},
                fallback_number=n,
                force_number=True,
                force_title=entry.get("title", ""),
                force_stage=entry.get("stage", ""))
            staged_md[n] = md.rstrip()

        # Staged beats override panel beats on conflict; otherwise
        # we keep what was already in the panel. Sort by number.
        merged_numbers = sorted(
            set(panel_by_number.keys()) | set(staged_md.keys()))
        parts = []
        if preamble.strip():
            parts.append(preamble.rstrip())
        for n in merged_numbers:
            if n in staged_md:
                parts.append(staged_md[n])
            else:
                parts.append(panel_by_number[n])
        # Trailing unnumbered beats stay at the bottom (best-effort
        # preservation of any user-typed material the parser
        # couldn't classify).
        for pb in unnumbered:
            body = "\n".join(pb.body_lines).rstrip()
            marker = "[x]" if pb.checked else "[ ]"
            parts.append(
                f"## {marker} {pb.title}"
                + (f"\n{body}" if body else ""))
        return "\n\n".join(parts) + "\n"

    def _outline_apply_to_panel(self,
                                 chapter_id: str,
                                 mode: str) -> None:
        """Apply the staging list to the OutlinePanel.

        All three modes (append/replace/overwrite) write through
        ``set_outline_text`` so the final panel content is always
        emitted in plot order — never the user's draft order. The
        difference:
          * append  → merge staged beats with existing panel beats,
                      sort by beat number, write the whole thing.
          * replace → drop existing panel content, write only the
                      staged beats sorted.
          * overwrite → same as replace.
        """
        s = self._outline_session(chapter_id)
        panel = getattr(self.chat_widget, "outline_panel", None)
        if panel is None:
            return
        staging = s.get("staging") or []
        if mode == "apply_append":
            body = self._merge_outline_with_existing_panel(
                staging, panel)
            verb = "merged in"
        elif mode == "apply_replace":
            body = self._build_outline_apply_text(staging)
            verb = "replaced with"
        else:  # apply_overwrite
            body = self._build_outline_apply_text(staging)
            verb = "overwrote with"
        if not body.strip():
            self.chat_widget.add_message(
                "Assistant",
                "(Nothing to apply — staging is empty.)")
            return
        # Always set (not append) — _merge_outline_with_existing_panel
        # already includes the existing content for append mode.
        panel.set_outline_text(body)
        # Switch sidebar to outline tab so the user sees the result.
        tabs = getattr(self, "sidebar_tabs", None)
        if tabs is not None:
            idx = tabs.indexOf(panel)
            if idx >= 0:
                tabs.setCurrentIndex(idx)
        self.chat_widget.add_message(
            "Assistant",
            f"**Outline panel {verb} {len(s['staging'])} staged "
            f"beats** — beats are written in plot order regardless "
            f"of draft sequence. Edits in the panel autosave back "
            f"to the chapter plan.")
        self._outline_set_phase(
            chapter_id, self._OUTLINE_PHASE_DONE,
            log_event=f"applied_{mode}")
        # Reset session so the next "outline this" starts fresh.
        self._outline_session_reset(chapter_id)

    def _init_beat_state_with_audit(
            self,
            chapter_id: str,
            chapter,
            output_mode: str,
            state_dict: Optional[dict] = None,
            preserve_remaining_beats: bool = False) -> dict:
        """Initialise per-mode beat state from the deterministic audit.

        Computes the audit, finds the first pending beat, and
        seeds the state with audit_status="pending_user" so the
        next user message routes through ``_apply_audit_user_reply``
        (and from there into per-beat orchestration). For Full Text
        writer mode, the existing remaining_beats list is preserved
        so ``_current_beat`` keeps working.
        """
        if output_mode == "outline":
            target_dict = self._outline_beat_state
            panel = getattr(
                self.chat_widget, "outline_panel", None)
            audit = self._compute_beat_audit_deterministic(
                chapter, "outline", panel=panel)
            cap = self._OUTLINE_MAX_ROUNDS_PER_BEAT
        else:
            target_dict = (state_dict
                           if state_dict is not None
                           else self._writer_beat_state)
            audit = self._compute_beat_audit_deterministic(
                chapter, "full_text")
            cap = self._WRITER_MAX_ROUNDS_PER_BEAT

        first_pending = next(
            (a["beat_number"] for a in audit
             if a["status"] == "pending"),
            None)
        beats_done = sum(
            1 for a in audit if a["status"] != "pending")

        existing = target_dict.get(chapter_id) or {}
        new_state = {
            "in_progress": first_pending is not None,
            "complete": first_pending is None and bool(audit),
            "beats_done": beats_done,
            "current_beat_number": first_pending or 1,
            "rounds_for_beat": 0,
            "max_rounds": cap,
            "audit_status": "pending_user",
            "audit": audit,
        }
        if preserve_remaining_beats:
            for k in ("remaining_beats", "current_idx",
                       "force_write", "completed",
                       "outline_action"):
                if k in existing:
                    new_state[k] = existing[k]
            # Re-align current_idx to first_pending in the
            # remaining_beats list (best-effort title match).
            if first_pending is not None and audit:
                target_title = ""
                for a in audit:
                    if a["beat_number"] == first_pending:
                        target_title = (
                            a["title"] or "").strip().lower()
                        break
                rb = new_state.get("remaining_beats") or []
                for i, b in enumerate(rb):
                    if (b.get("text", "").strip().lower()
                            == target_title):
                        new_state["current_idx"] = i
                        break
        target_dict[chapter_id] = new_state
        return new_state

    def _surface_engine_audit(self,
                               chapter_id: str,
                               output_mode: str) -> None:
        """Post the engine-computed audit to chat + log it."""
        if output_mode == "outline":
            state = self._outline_beat_state.get(chapter_id) or {}
            mode_label = "Outline (engine-computed)"
        else:
            state = self._writer_beat_state.get(chapter_id) or {}
            mode_label = "Writer (engine-computed)"
        audit = state.get("audit") or []
        first_pending = state.get("current_beat_number")
        if not audit:
            self.chat_widget.add_message(
                "Assistant",
                "This chapter has no planned beats. Add some in "
                "the chapter planner before outlining/writing.")
            return
        if not state.get("in_progress"):
            self.chat_widget.add_message(
                "Assistant",
                self._render_audit_chat_message(
                    audit, None, mode_label)
                + "\n\n_All planned beats look done — nothing "
                "left to produce._")
            return
        self.chat_widget.add_message(
            "Assistant",
            self._render_audit_chat_message(
                audit, first_pending, mode_label))
        # Note: don't push this turn into _chat_history — the
        # user hasn't said anything yet that needs to be remembered.

    def _render_audit_chat_message(self,
                                    audit: list,
                                    first_pending: Optional[int],
                                    mode_label: str) -> str:
        """Format the AI's audit list as a markdown chat message."""
        icon_for = {
            "written":  "✍️",
            "outlined": "📋",
            "pending":  "⏳",
        }
        lines = [
            f"**{mode_label} audit — please confirm:**",
            "",
        ]
        for entry in audit or []:
            bn = entry.get("beat_number", "?")
            title = entry.get("title", "(untitled)")
            status = (entry.get("status") or "pending").lower()
            evidence = (entry.get("evidence") or "").strip()
            icon = icon_for.get(status, "•")
            line = f"{icon}  **Beat {bn}:** {title} — _{status}_"
            if evidence:
                line += f"  \n      {evidence}"
            lines.append(line)
        lines.append("")
        if first_pending is not None:
            lines.append(
                f"_First pending: **Beat {first_pending}**._")
        lines.append("")
        lines.append(
            "Reply **\"looks good\"** to proceed from there, or "
            "correct the audit (e.g. _\"Beat 3 is pending\"_).")
        return "\n".join(lines)

    def _handle_outline_json_beat_staging(
            self, chapter_id: str, parsed: dict) -> None:
        """Append/refine beat in staging list; await user.

        - If the session is in BEAT_QUESTIONS phase, this beat is a
          NEW draft → append to staging.
        - If in BEAT_DRAFTED phase, the beat is a REFINEMENT →
          replace the last staging entry.
        - After landing, transition to BEAT_DRAFTED + post the JSON
          summary in chat with the proceed/refine prompt.
        """
        beat = parsed.get("beat") or {}
        if not isinstance(beat, dict) or not beat:
            self.chat_widget.add_message(
                "Assistant",
                "(Model emitted phase=\"beat\" but no beat object — "
                "send another message to retry.)")
            self._pending_chat_message = ""
            return
        s = self._outline_session(chapter_id)
        cur_no = s.get("current_beat_number")
        ce = getattr(self.manuscript_editor,
                     "current_chapter_editor", None)
        events = (
            list(getattr(getattr(ce.chapter, "planning", None),
                         "events", []) or [])
            if (ce and getattr(ce, "chapter", None)) else [])
        title, stage = "", ""
        if cur_no and 1 <= cur_no <= len(events):
            title = (events[cur_no - 1].text or "").strip()
            stage = (events[cur_no - 1].stage or "").strip()

        entry = {
            "beat_number": cur_no,
            "title": title,
            "stage": stage,
            "json": beat,
        }
        # Refinement vs new draft: refinement REPLACES the last
        # staging entry for THIS beat number.
        existing_idx = None
        for i, e in enumerate(s["staging"]):
            if e.get("beat_number") == cur_no:
                existing_idx = i
                break
        if existing_idx is not None:
            s["staging"][existing_idx] = entry
            verb = "refined"
        else:
            s["staging"].append(entry)
            verb = "drafted"

        # Render the beat as markdown so the user can read what
        # landed in staging.
        beat_md = self._outline_beat_json_to_markdown(
            beat,
            fallback_number=cur_no or 1,
            force_number=True,
            force_title=title,
            force_stage=stage)
        # Build the chat confirmation. Wording distinguishes
        # "drafted" (count goes up) from "refined" (count stays
        # the same — the existing entry was REPLACED in place).
        # The staged-beat numbers are listed explicitly so the
        # user can see exactly what's in staging.
        thinking = (parsed.get("thinking") or "").strip()
        staged_numbers = sorted(
            e["beat_number"] for e in s["staging"]
            if isinstance(e.get("beat_number"), int))
        staged_str = ", ".join(
            f"Beat {n}" for n in staged_numbers) or "(none)"
        total_events = len(events) or 0
        # Find the next pending beat number (the one a "proceed"
        # would advance to) so the message names it explicitly.
        already_done_set = set()
        for entry_audit in (s.get("audit") or []):
            if entry_audit.get("status") in (
                    "outlined", "written"):
                already_done_set.add(
                    entry_audit.get("beat_number"))
        drafted_set = set(staged_numbers)
        next_pending = None
        for i in range(1, total_events + 1):
            if i <= cur_no:
                continue
            if i in drafted_set or i in already_done_set:
                continue
            next_pending = i
            break
        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        if verb == "refined":
            lines.append(
                f"**Beat {cur_no} refined** — staging entry "
                f"updated in place. Staging unchanged: "
                f"{len(staged_numbers)}/{total_events} beats "
                f"[{staged_str}].")
        else:
            lines.append(
                f"**Beat {cur_no} drafted** — added to staging. "
                f"Staging now: {len(staged_numbers)}/"
                f"{total_events} beats [{staged_str}].")
        lines.append("")
        lines.append("```")
        lines.append(beat_md.rstrip())
        lines.append("```")
        lines.append("")
        # Tell the user EXACTLY what proceed will do next.
        if next_pending is not None:
            lines.append(
                f"_Reply **\"proceed\"** to draft "
                f"**Beat {next_pending}**, or refine Beat "
                f"{cur_no} again (e.g. _\"strengthen the "
                f"worldbuilding hooks\"_)._")
        else:
            lines.append(
                "_All planned beats are now in staging. Reply "
                "**\"proceed\"** to apply, or refine this beat "
                "first._")
        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))
        self._outline_set_phase(
            chapter_id, self._OUTLINE_PHASE_BEAT_DRAFTED,
            log_event=f"beat_{cur_no}_{verb}")
        # Reset round counter so next beat starts fresh.
        s["rounds_for_beat"] = 0
        self._pending_chat_message = ""

    def _handle_outline_json_start_suggestion(
            self, chapter_id: str, parsed: dict) -> None:
        """Surface the model's start-beat suggestion + await user."""
        s = self._outline_session(chapter_id)
        try:
            suggested = int(parsed.get("suggested_beat_number"))
        except Exception:
            suggested = None
        title = (
            parsed.get("suggested_beat_title") or "").strip()
        reasoning = (parsed.get("reasoning") or "").strip()
        thinking = (parsed.get("thinking") or "").strip()
        # Validate: the suggested beat must exist in the chapter's
        # plot events. Otherwise fall back to first pending from
        # the audit.
        valid = False
        ce = getattr(self.manuscript_editor,
                     "current_chapter_editor", None)
        events = (
            list(getattr(getattr(ce.chapter, "planning", None),
                         "events", []) or [])
            if (ce and getattr(ce, "chapter", None)) else [])
        if suggested and 1 <= suggested <= len(events):
            valid = True
            if not title:
                title = (events[suggested - 1].text
                         or "(untitled)")
        if not valid:
            # Fall back to first pending from audit.
            for entry in s.get("audit") or []:
                if entry.get("status") == "pending":
                    suggested = entry.get("beat_number")
                    title = entry.get("title", "")
                    break
            if not suggested and events:
                suggested = 1
                title = events[0].text
        s["current_beat_number"] = suggested
        s["current_beat_index"] = (
            (suggested - 1) if suggested else None)
        # Surface the audit + suggestion to the user.
        audit_md = self._render_audit_chat_message(
            s.get("audit") or [], suggested,
            "Outline (engine-computed)")
        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        lines.append(audit_md)
        lines.append("")
        if reasoning:
            lines.append(f"_Suggested start: **Beat {suggested} — "
                         f"\"{title}\"**. {reasoning}_")
        else:
            lines.append(
                f"_Suggested start: **Beat {suggested} — "
                f"\"{title}\"**._")
        lines.append("")
        lines.append(
            "Reply **\"looks good\"** to accept this start, or "
            "specify a different beat (e.g. _\"start at Beat 1\"_).")
        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))
        self._outline_set_phase(
            chapter_id, self._OUTLINE_PHASE_PICK_START,
            log_event="start_suggested")
        self._pending_chat_message = ""

    def _handle_outline_json_audit(self,
                                    chapter_id: str,
                                    parsed: dict) -> None:
        """Coerce a legacy ``phase=audit`` reply into start_suggestion.

        When the model still emits the old audit format on a turn
        where we're awaiting ``start_suggestion`` (the new schema),
        synthesise the suggestion from the audit's
        ``first_pending_beat`` so the user still gets the
        confirm/override prompt. This avoids a dead-end where the
        old "audit ignored" message fires and the user has no way
        to advance.
        """
        s = self._outline_session(chapter_id)
        if s.get("phase") in (None, "await_pick_start_response"):
            # Synthesise a start_suggestion from the audit so the
            # PICK_START flow can continue.
            audit = parsed.get("audit") or []
            try:
                first_pending = int(
                    parsed.get("first_pending_beat"))
            except Exception:
                first_pending = next(
                    (a.get("beat_number") for a in audit
                     if isinstance(a, dict)
                     and a.get("status") == "pending"),
                    None)
            title = ""
            if first_pending and isinstance(audit, list):
                for a in audit:
                    if (isinstance(a, dict)
                            and a.get("beat_number") == first_pending):
                        title = (a.get("title") or "").strip()
                        break
            self._handle_outline_json_start_suggestion(
                chapter_id, {
                    "phase": "start_suggestion",
                    "suggested_beat_number": first_pending,
                    "suggested_beat_title": title,
                    "reasoning":
                        "(coerced from legacy `phase: audit` "
                        "response — schema is `start_suggestion` "
                        "now.)",
                    "thinking":
                        (parsed.get("thinking") or "").strip(),
                })
            self._log_beat_state(
                "outline", chapter_id,
                "audit_coerced_to_start_suggestion")
            return
        # Outside pick-start, the legacy audit is genuinely
        # off-protocol — surface the original ignore message.
        self.chat_widget.add_message(
            "Assistant",
            "_The engine handles the beat audit deterministically — "
            "the model's audit was ignored. Send your next message "
            "to continue the per-beat flow._")
        self._pending_chat_message = ""
        self._log_beat_state(
            "outline", chapter_id, "model_audit_ignored")
        return
        # Original logic kept below (unreachable) for reference.
        """Surface the model's outline-mode audit + await user."""
        audit = parsed.get("audit") or []
        first_pending = parsed.get("first_pending_beat")
        try:
            first_pending = int(first_pending) if first_pending else None
        except Exception:
            first_pending = None
        if not isinstance(audit, list):
            audit = []
        ob_state = self._outline_beat_state.get(chapter_id) or {}
        ob_state["audit"] = audit
        ob_state["audit_status"] = "pending_user"
        if first_pending is not None:
            ob_state["current_beat_number"] = first_pending
        self._outline_beat_state[chapter_id] = ob_state
        self._log_beat_state(
            "outline", chapter_id, "audit_landed")

        msg = self._render_audit_chat_message(
            audit, first_pending, "Outline")
        self.chat_widget.add_message("Assistant", msg)

        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        if pending_msg:
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant",
                 "content": "(Outline audit — awaiting confirmation.)"})
            self._compact_chat_history()
        self._pending_chat_message = ""

    def _handle_writer_json_audit(self,
                                   chapter_id: str,
                                   parsed: dict) -> None:
        """No-op — engine computes audit deterministically now."""
        self.chat_widget.add_message(
            "Assistant",
            "_The engine handles the beat audit deterministically — "
            "the model's audit was ignored. Send your next message "
            "to start the per-beat questions for the engine-selected "
            "beat._")
        self._pending_chat_message = ""
        self._log_beat_state(
            "writer", chapter_id, "model_audit_ignored")
        return
        # Original logic kept below (unreachable) for reference.
        """Surface the model's writer-mode audit + await user."""
        audit = parsed.get("audit") or []
        first_pending = parsed.get("first_pending_beat")
        try:
            first_pending = int(first_pending) if first_pending else None
        except Exception:
            first_pending = None
        if not isinstance(audit, list):
            audit = []
        beat_state = self._writer_beat_state.get(chapter_id) or {}
        beat_state["audit"] = audit
        beat_state["audit_status"] = "pending_user"
        if first_pending is not None:
            beat_state["current_beat_number"] = first_pending
        self._writer_beat_state[chapter_id] = beat_state
        self._log_beat_state(
            "writer", chapter_id, "audit_landed")

        msg = self._render_audit_chat_message(
            audit, first_pending, "Writer")
        self.chat_widget.add_message("Assistant", msg)

        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        if pending_msg:
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant",
                 "content": "(Writer audit — awaiting confirmation.)"})
            self._compact_chat_history()
        self._pending_chat_message = ""

    @staticmethod
    def _looks_like_audit_correction(text: str) -> Optional[dict]:
        """Parse a user reply for audit corrections.

        Returns ``{"flips": {beat_number: new_status}}`` when the
        message looks like a beat-level correction, e.g.
        "Beat 3 isn't done", "Beat 2 is actually written",
        "Beat 4 is pending". Returns ``None`` for plain
        confirmations ("looks good", "yes") so the caller treats
        the audit as accepted as-is.
        """
        import re as _re
        if not text:
            return None
        s = text.strip()
        approve = ("looks good", "ok", "okay", "proceed",
                   "go ahead", "confirm", "confirmed",
                   "yes", "y", "good", "great", "perfect",
                   "ship it", "lgtm")
        s_low = s.lower().rstrip(".!?")
        if s_low in approve:
            return None
        flips = {}
        # Capture: "Beat N", an optional connector (which may be a
        # negation), and the status label. Parsing the connector
        # separately lets us flip "isn't done" -> pending while
        # leaving plain "is done" -> written.
        patt = _re.compile(
            r"beat\s+(\d+)\b[^a-z0-9]*"
            r"(is\s+not|isn[\u2019\']?t|is\s+also|is)?"
            r"\s*(?:actually\s+)?"
            r"(written|outlined|pending|done|complete|incomplete|"
            r"todo|not\s+done)",
            _re.IGNORECASE)
        for m in patt.finditer(s):
            try:
                n = int(m.group(1))
            except Exception:
                continue
            connector = (m.group(2) or "").lower()
            negated = ("not" in connector
                       or "n\u2019t" in connector
                       or "n't" in connector)
            label = _re.sub(r"\s+", " ", m.group(3).lower()).strip()
            if label in ("done", "complete"):
                flips[n] = "pending" if negated else "written"
            elif label in ("incomplete", "todo", "not done"):
                flips[n] = "pending"
            elif negated:
                flips[n] = "pending"
            else:
                flips[n] = label
        return {"flips": flips} if flips else None

    def _apply_audit_user_reply(
            self,
            chapter_id: str,
            state: dict,
            message: str,
            state_dict: dict) -> None:
        """Move audit_status from pending_user → confirmed.

        Applies any beat-level corrections parsed from ``message``,
        recomputes the first pending beat, and stamps
        ``current_beat_number`` so the next prompt context tells
        the model exactly which beat to work on.
        """
        audit = state.get("audit") or []
        # Apply user corrections, if any.
        correction = self._looks_like_audit_correction(message)
        if correction and correction.get("flips"):
            flips = correction["flips"]
            for entry in audit:
                bn = entry.get("beat_number")
                if bn in flips:
                    entry["status"] = flips[bn]
                    entry["evidence"] = (
                        f"User flipped to {flips[bn]}.")
            state["audit"] = audit

        # Compute first pending. Prefer the model's
        # first_pending_beat unless the user's flips disagree.
        first_pending = None
        for entry in audit:
            if entry.get("status") == "pending":
                try:
                    first_pending = int(entry.get("beat_number"))
                except Exception:
                    pass
                break
        if first_pending is None:
            # All beats marked done — nothing left to produce.
            state["in_progress"] = False
            state["complete"] = True
            state["audit_status"] = "confirmed"
            self.chat_widget.add_message(
                "Assistant",
                "All planned beats look done according to the "
                "audit. Nothing left to outline/write — let me "
                "know if you want to refine an existing beat.")
            state_dict[chapter_id] = state
            try:
                mode_label = (
                    "outline" if state_dict is self._outline_beat_state
                    else "writer")
                self._log_beat_state(
                    mode_label, chapter_id,
                    "audit_confirmed_all_done")
            except Exception:
                pass
            return

        state["current_beat_number"] = first_pending
        # Align the writer-mode current_idx to the same beat (for
        # _current_beat lookups).
        if "remaining_beats" in state:
            # current_idx is the index INTO remaining_beats, which
            # may not correspond 1-to-1 with absolute beat numbers
            # (the writer's coverage analysis already filtered).
            # Treat first_pending as the absolute beat number; find
            # the matching remaining-beat index by title if we can.
            target_title = ""
            for entry in audit:
                if entry.get("beat_number") == first_pending:
                    target_title = (entry.get("title") or "").strip().lower()
                    break
            new_idx = 0
            for i, b in enumerate(state["remaining_beats"]):
                if (b.get("text", "").strip().lower()
                        == target_title):
                    new_idx = i
                    break
            state["current_idx"] = new_idx
        state["audit_status"] = "confirmed"
        state["rounds_for_beat"] = 0
        state_dict[chapter_id] = state
        # Log so the console shows which beat we're locked onto
        # after the user confirms. Wrapped because some test
        # fixtures bypass __init__ and accessing the state-dict
        # attrs would raise.
        try:
            mode_label = (
                "outline" if state_dict is self._outline_beat_state
                else "writer")
            self._log_beat_state(
                mode_label, chapter_id, "audit_confirmed")
        except Exception:
            pass

    @staticmethod
    def _parse_writer_json_response(text: str) -> Optional[dict]:
        """Extract a structured writer-mode JSON object from a reply.

        Same shape as ``_parse_outline_json_response`` but validates
        the writer-mode phase tags (``"questions"`` or ``"prose"``).
        Returns ``None`` for malformed input so the caller can fall
        back to the legacy markdown writer path.
        """
        import json
        import re as _re
        if not text or not text.strip():
            return None

        candidates: list = []
        fence_re = _re.compile(
            r"```(?:json)?\s*\n?(.*?)```",
            _re.IGNORECASE | _re.DOTALL)
        for m in fence_re.finditer(text):
            candidates.append(m.group(1).strip())
        candidates.append(text.strip())
        first = text.find("{")
        last = text.rfind("}")
        if 0 <= first < last:
            candidates.append(text[first:last + 1])

        for cand in candidates:
            cand = cand.strip()
            if not cand or not cand.startswith("{"):
                continue
            try:
                obj = json.loads(cand)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            phase = obj.get("phase")
            if phase not in ("audit", "questions", "prose"):
                continue
            return obj
        return None

    def _handle_writer_json_questions(self,
                                       chapter_id: str,
                                       parsed: dict) -> None:
        """Render a JSON ``phase=questions`` reply as Phase-1 chat.

        Mirrors the outline-mode questions handler but uses the
        ``_writer_beat_state`` round counter + the writer's
        ``_current_beat`` for the beat label.
        """
        questions = parsed.get("questions") or []
        thinking = (parsed.get("thinking") or "").strip()
        if isinstance(questions, str):
            questions = [questions]
        questions = [str(q).strip() for q in questions if q]

        beat_state = self._writer_beat_state.get(chapter_id) or {}
        # Round counter: each questions-turn burns one round.
        beat_state.setdefault("rounds_for_beat", 0)
        beat_state.setdefault(
            "max_rounds", self._WRITER_MAX_ROUNDS_PER_BEAT)
        # DEFENSIVE PER-BEAT RESET. If the round counter is still
        # carrying state from a PRIOR beat (because the prose
        # handler / advance path missed the reset, or the model
        # returned questions in a state where in_progress was
        # transiently False), reset to 0 here. Without this the
        # counter accumulates across beats and the round cap fires
        # after only 2-3 beats of work.
        cur_beat_no_for_counter = (
            beat_state.get("current_beat_number")
            or (beat_state.get("current_idx", 0) + 1))
        last_counter_beat = beat_state.get("_round_counter_beat_no")
        if last_counter_beat != cur_beat_no_for_counter:
            beat_state["rounds_for_beat"] = 0
            beat_state["_round_counter_beat_no"] = (
                cur_beat_no_for_counter)
        beat_state["rounds_for_beat"] += 1
        rounds = beat_state["rounds_for_beat"]
        cap = beat_state["max_rounds"]
        cur_beat = self._current_beat(chapter_id) or {}
        cur_title = cur_beat.get("text", "current beat")
        beat_no = (
            beat_state.get("current_idx", 0) + 1
            if beat_state.get("in_progress") else 1)

        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        if questions:
            lines.append(
                f"**Beat {beat_no} (\"{cur_title}\") — Phase-1 "
                f"questions** (round {rounds}/{cap})")
            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q}")
        else:
            lines.append(
                f"(Model returned phase=\"questions\" but no "
                f"questions — moving to write Beat {beat_no} on "
                f"the next message.)")

        if rounds >= cap:
            self._writer_ready_chapters.add(chapter_id)
            beat_state["force_write"] = True
            lines.append("")
            lines.append(
                f"*Round cap reached — send another message and "
                f"the model will write Beat {beat_no} directly.*")
        else:
            lines.append("")
            lines.append(
                f"*Answer above, or say `proceed` to skip ahead "
                f"and write Beat {beat_no} now.*")

        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))
        self._writer_beat_state[chapter_id] = beat_state
        self._log_beat_state(
            "writer", chapter_id, "questions_landed")

        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        joined_qs = "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, 1))
        try:
            self._record_writer_qa(
                chapter_id, pending_msg, joined_qs)
        except Exception:
            pass
        if pending_msg:
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant",
                 "content": joined_qs or "(no questions)"})
            self._compact_chat_history()
        self._pending_chat_message = ""

    def _handle_writer_json_prose(self,
                                   chapter_id: str,
                                   parsed: dict) -> None:
        """Insert prose from a JSON ``phase=prose`` reply.

        Routes the prose into the chapter editor using the existing
        insert_mode logic, surfaces the writing_summary in chat,
        records the insertion for ``<edit_last_insertion>``, and
        advances the per-beat state. Honours ``writing_complete``.
        """
        prose_text = (parsed.get("prose") or "").strip()
        thinking = (parsed.get("thinking") or "").strip()
        summary_obj = parsed.get("writing_summary") or {}
        writing_complete = bool(parsed.get("writing_complete"))

        if not prose_text:
            self.chat_widget.add_message(
                "Assistant",
                "(Model emitted phase=\"prose\" but the prose field "
                "was empty — try resending.)")
            self._pending_chat_message = ""
            return

        ce = getattr(self.manuscript_editor,
                     "current_chapter_editor", None)
        if ce is None or not getattr(ce, "chapter", None):
            self.chat_widget.add_message(
                "Assistant",
                "No chapter is open. Please select a chapter first.")
            return
        editor = ce.editor
        insert_mode = getattr(
            self, '_pending_insert_mode', 'insert_at_cursor')

        # Insert the prose using the same logic as the legacy path.
        cursor = editor.textCursor()
        ins_start = cursor.position()
        action = ""
        try:
            if insert_mode == 'replace_selection':
                if cursor.hasSelection():
                    ins_start = min(cursor.selectionStart(),
                                     cursor.selectionEnd())
                    cursor.insertText(prose_text)
                    action = "replaced selection"
                else:
                    cursor.insertText(prose_text)
                    action = "inserted at cursor"
            elif insert_mode == 'insert_at_cursor':
                ins_start = cursor.position()
                cursor.insertText(prose_text)
                action = "inserted at cursor"
            elif insert_mode == 'append_to_chapter':
                cursor.movePosition(cursor.MoveOperation.End)
                current = editor.toPlainText()
                if current and not current.endswith('\n\n'):
                    cursor.insertText('\n\n')
                ins_start = cursor.position()
                cursor.insertText(prose_text)
                action = "appended to chapter"
            elif insert_mode == 'replace_chapter':
                editor.setPlainText(prose_text)
                ins_start = 0
                cur = editor.textCursor()
                cur.movePosition(cur.MoveOperation.End)
                editor.setTextCursor(cur)
                action = "replaced chapter"
            else:
                ins_start = cursor.position()
                cursor.insertText(prose_text)
                action = "inserted"
        except Exception as e:
            self.chat_widget.add_message(
                "Assistant", f"Failed to insert prose: {e}")
            return

        ins_end = editor.textCursor().position()
        # Render the writing summary into a markdown block so it
        # reuses the existing chat formatting.
        summary_md = self._render_writing_summary(summary_obj)

        try:
            self._record_writer_insertion(
                chapter_id=chapter_id,
                start=ins_start,
                end=ins_end,
                prose=prose_text,
                prompt=getattr(
                    self, "_pending_chat_message", "") or "",
                mode=f"writer:full_text:{insert_mode}",
                summary=summary_md,
            )
        except Exception:
            pass

        word_count = (
            int(summary_obj.get("word_count")) if isinstance(
                summary_obj.get("word_count"), (int, float))
            else len(prose_text.split()))

        # Engine-controlled beat number — the model's beat_number
        # is overridden if it doesn't match what the engine asked
        # for (audit-derived current_beat_number, or remaining-beat
        # index when no audit fired). Stops the model from looping
        # back to Beat 1 by claiming "beat_number: 1" when we asked
        # for Beat 4.
        beat_state = self._writer_beat_state.get(chapter_id)
        engine_no = None
        if beat_state:
            engine_no = beat_state.get("current_beat_number")
            if engine_no is None and beat_state.get("in_progress"):
                engine_no = beat_state.get("current_idx", 0) + 1
        model_no = None
        try:
            model_no = int(parsed.get("beat_number"))
        except Exception:
            model_no = None
        if (engine_no is not None and model_no is not None
                and model_no != engine_no):
            self.chat_widget.add_message(
                "Assistant",
                f"(Model returned beat_number {model_no} but "
                f"engine asked for Beat {engine_no} — using "
                f"engine's number to keep the queue ordered.)")
        beat_no = engine_no if engine_no is not None else (
            model_no if model_no is not None else None)

        if beat_state and beat_state.get("in_progress"):
            beat_state["rounds_for_beat"] = 0
            beat_state["force_write"] = False
            try:
                self._advance_beat(chapter_id)
            except Exception:
                pass
            # Bump current_beat_number for the NEXT turn so the
            # focus block stays one ahead.
            if beat_no is not None:
                beat_state["current_beat_number"] = beat_no + 1
        if writing_complete and beat_state:
            beat_state["in_progress"] = False
        # Clear ready flag so next beat starts in Phase 1 again.
        self._writer_ready_chapters.discard(chapter_id)
        self._log_beat_state(
            "writer", chapter_id,
            f"prose_beat_{beat_no or '?'}_landed_advance_to_"
            f"{(beat_no + 1) if beat_no is not None else '?'}")

        # Build the chat confirmation.
        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        if writing_complete:
            lines.append(
                f"**Chapter writing complete** — Beat "
                f"{beat_no or '?'} ({word_count:,} words {action}). "
                f"All planned beats covered.")
        else:
            lines.append(
                f"**Beat {beat_no or '?'} written** — "
                f"{word_count:,} words {action}. Send a follow-up "
                f"to refine, or send the next message to continue "
                f"with the next beat.")
        if summary_md:
            lines.append("")
            lines.append(summary_md)
        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))

        # Chat-history bookkeeping (compact marker, not the full prose).
        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        if pending_msg:
            marker = (
                "(Chapter writing complete.)" if writing_complete
                else f"(Beat {beat_no or '?'} written, "
                     f"{word_count:,} words.)")
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant", "content": marker})
            self._compact_chat_history()
        self._pending_chat_message = ""

    @staticmethod
    def _render_writing_summary(summary: dict) -> str:
        """Render a writing_summary dict as a markdown block.

        Mirrors the legacy ``<writing_summary>`` shape so the chat
        confirmation reads consistently across the two paths.
        """
        if not isinstance(summary, dict):
            return ""
        lines = ["<writing_summary>"]
        sections = [
            ("plot_events_covered",   "PLOT EVENTS COVERED"),
            ("key_changes",           "KEY CHANGES IN THIS SCENE"),
            ("worldbuilding_surfaced", "WORLDBUILDING SURFACED"),
            ("subplots_advanced",     "SUBPLOTS / TENSIONS ADVANCED"),
        ]
        any_section = False
        for key, label in sections:
            items = summary.get(key)
            if isinstance(items, str):
                items = [items]
            if not items:
                continue
            lines.append(f"{label}:")
            for item in items:
                s = str(item).strip()
                if s:
                    lines.append(f"- {s}")
            any_section = True
        wc = summary.get("word_count")
        if isinstance(wc, (int, float)):
            lines.append(f"WORD COUNT: {int(wc)}")
            any_section = True
        lines.append("</writing_summary>")
        return "\n".join(lines) if any_section else ""

    @staticmethod
    def _parse_outline_json_response(text: str) -> Optional[dict]:
        """Extract the structured outline JSON object from a reply.

        Tolerates the model wrapping the object in a ``json fence,
        trailing prose, or no fence at all. Returns ``None`` when
        no parseable object is found — caller falls back to the
        markdown normalizer.

        Validates that the parsed object has a ``phase`` field set
        to ``"questions"`` or ``"beat"`` (anything else returns
        None). Other fields are returned untouched for the caller
        to interpret.
        """
        import json
        import re as _re
        if not text or not text.strip():
            return None

        candidates: list = []
        # Prefer ```json fenced block when present.
        fence_re = _re.compile(
            r"```(?:json)?\s*\n?(.*?)```",
            _re.IGNORECASE | _re.DOTALL)
        for m in fence_re.finditer(text):
            candidates.append(m.group(1).strip())
        # Also try the raw text and the largest balanced {...} substring.
        candidates.append(text.strip())
        first = text.find("{")
        last = text.rfind("}")
        if 0 <= first < last:
            candidates.append(text[first:last + 1])

        for cand in candidates:
            cand = cand.strip()
            if not cand or not cand.startswith("{"):
                continue
            try:
                obj = json.loads(cand)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            phase = obj.get("phase")
            if phase not in (
                    "audit", "questions", "beat",
                    "start_suggestion"):
                continue
            return obj
        return None

    @staticmethod
    def _outline_beat_json_to_markdown(beat: dict,
                                        fallback_number: int = 1,
                                        force_number: bool = False,
                                        force_title: str = "",
                                        force_stage: str = ""
                                        ) -> str:
        """Render a structured ``beat`` dict as outline-panel markdown.

        Mirrors the markdown skeleton the panel parses into a
        checklist card. Missing optional sections are skipped
        (better a sparse card than empty bullet lists).

        When ``force_number`` is True, the beat heading uses
        ``fallback_number`` regardless of the model's ``number``
        field. When ``force_title`` is non-empty, the heading uses
        IT instead of the model's ``beat.title`` — this stops the
        model from rewriting the planned beat title (e.g. emitting
        Beat 1's title when the engine asked for Beat 4). The
        engine sources both from ``chapter.planning.events`` so
        they always match the plot plan.
        """
        if not isinstance(beat, dict):
            return ""

        if force_number:
            number = fallback_number
        else:
            try:
                number = int(beat.get("number", fallback_number)
                             or fallback_number)
            except Exception:
                number = fallback_number
        if force_title:
            title = force_title.strip() or "(untitled)"
        else:
            title = (
                beat.get("title") or "").strip() or "(untitled)"
        if force_stage:
            stage = force_stage.strip()
        else:
            stage = (beat.get("stage") or "").strip()
        marker = (
            "[x]" if str(beat.get("checked", "")).lower() in
            ("true", "1", "x", "yes") else "[ ]")
        heading = f"## {marker} Beat {number}: {title}"
        if stage:
            heading += f" — {stage}"

        section_specs = [
            ("what_happens",     "WHAT HAPPENS"),
            ("who_is_in_it",     "WHO'S IN IT"),
            ("where_when",       "WHERE / WHEN"),
            ("worldbuilding",    "WORLDBUILDING TO LEAN INTO"),
            ("sensory_hooks",    "SENSORY HOOKS / CONTENT EXAMPLES"),
            ("subplot_theme",    "SUBPLOT / THEME LANDING"),
            ("leave_vs_imply",   "WHAT TO LEAVE ON THE PAGE vs IMPLY"),
        ]
        parts = [heading, ""]
        for key, label in section_specs:
            items = beat.get(key)
            # Tolerate a single-string value where a list is expected.
            if isinstance(items, str):
                items = [items]
            if not items:
                continue
            parts.append(f"**{label}**:")
            for item in items:
                s = str(item).strip()
                if not s:
                    continue
                parts.append(f"- {s}")
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def _handle_focused_beat_response(self,
                                        chapter_id: str,
                                        parsed: dict) -> bool:
        """Push a phase="beat" JSON straight into the focused beat.

        Wired in from the chat router when ``self._focused_beat_ai``
        has an entry for ``chapter_id`` — the user clicked ✨ on a
        specific beat and now the AI's beat output should land in
        THAT beat's body in the panel, not in the staging list.

        Returns True when the beat was successfully written into
        the panel, False when the focused-beat session is invalid
        (panel bound to a different chapter, beat index out of
        range, etc.) so the caller can fall through to the normal
        staging path and the AI's work isn't dropped.
        """
        focus = self._focused_beat_ai.get(chapter_id)
        if not focus:
            return False
        beat = parsed.get("beat") or {}
        if not isinstance(beat, dict) or not beat:
            return False
        panel = getattr(self.chat_widget, "outline_panel", None)
        if panel is None:
            return False
        if panel.current_chapter_id() != chapter_id:
            # Panel has moved on; let the staging path handle it.
            return False
        beat_index = focus.get("beat_index")
        beat_title = focus.get("beat_title", "") or ""
        if beat_index is None:
            return False
        # Render the JSON into the standard outline markdown — uses
        # the same skeleton (WHAT HAPPENS / WHO'S IN IT / ...) that
        # the panel already parses + displays.
        full_md = self._outline_beat_json_to_markdown(
            beat,
            fallback_number=(beat_index + 1),
            force_number=True,
            force_title=beat_title,
            force_stage=(beat.get("stage") or "").strip())
        # Strip the leading "## [ ] Beat N: ... " heading + the
        # blank line after it — update_beat_body is body-only.
        body_lines = full_md.splitlines()
        if body_lines and body_lines[0].startswith("## "):
            body_lines = body_lines[1:]
        # Drop any leading blank lines so the rendered card opens
        # straight into the **WHAT HAPPENS** section.
        while body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
        new_body_md = "\n".join(body_lines).rstrip()
        ok = panel.update_beat_body(
            beat_index, new_body_md,
            new_title=beat_title or None)
        if not ok:
            # Beat was deleted or moved — fall through to staging.
            return False
        # Refresh the corresponding StoryEvent.description too. The
        # general panel→events sync deliberately PRESERVES existing
        # descriptions on title-match (so a panel rename doesn't
        # clobber manual edits) — but in the focused-beat flow the
        # user explicitly asked the AI to develop this beat, so the
        # description should reflect the new body.
        try:
            manuscript = getattr(
                self.current_project, "manuscript", None)
            chapters = (
                getattr(manuscript, "chapters", None) or [])
            chapter = next(
                (c for c in chapters
                 if getattr(c, "id", None) == chapter_id), None)
            if (chapter is not None
                    and getattr(chapter, "planning", None)
                    is not None):
                events = chapter.planning.events or []
                if 0 <= beat_index < len(events):
                    new_desc = (new_body_md or "").split(
                        "\n\n", 1)[0][:500]
                    events[beat_index].description = new_desc
        except Exception:
            pass
        # Re-select the beat so the highlight stays anchored on the
        # one we just updated (the re-render inside update_beat_body
        # rebuilds the cards and selection survives via the panel's
        # _selected_index, but make it explicit).
        try:
            panel._on_beat_selected(beat_index)
        except Exception:
            pass
        # Confirmation in chat.
        beat_label = beat_title or f"Beat {beat_index + 1}"
        self.chat_widget.add_message(
            "Assistant",
            f"_Pushed the AI-developed beat into **{beat_label}** "
            "in your outline panel — autosaved._\n\n"
            "If you want a different angle, say so and I'll "
            "rework it; or click ✨ on another beat to keep going.")
        # Clear the focused-beat session — done.
        self._focused_beat_ai.pop(chapter_id, None)
        # Reset the outline session for this chapter so the next
        # ✨ click starts a clean Q&A loop instead of resuming the
        # previous round counter.
        self._outline_session_state.pop(chapter_id, None)
        print(
            f"[focused-beat] chapter={chapter_id} "
            f"beat_index={beat_index} title={beat_label!r} "
            "applied to panel",
            flush=True)
        return True

    def _handle_outline_json_questions(self,
                                        chapter_id: str,
                                        parsed: dict) -> None:
        """Render a JSON ``phase=questions`` reply as Phase-1 chat.

        Reads the **session state** (not the legacy
        _outline_beat_state) so the displayed beat number matches
        what the engine actually asked the model to work on. The
        legacy dict was unpopulated under the new flow, which made
        this handler emit "produce Beat 1 now" even when the
        session was on Beat 3 — confusing the user and biasing the
        model.
        """
        questions = parsed.get("questions") or []
        thinking = (parsed.get("thinking") or "").strip()
        if isinstance(questions, str):
            questions = [questions]
        questions = [str(q).strip() for q in questions if q]

        # Use the session state (single source of truth for the
        # autonomous-system flow) — fall back to legacy state only
        # when no session exists.
        s = self._outline_session_state.get(chapter_id) or {}
        if s.get("started"):
            beat_no = s.get("current_beat_number") or 1
            s.setdefault("rounds_for_beat", 0)
            s.setdefault(
                "max_rounds", self._OUTLINE_MAX_ROUNDS_PER_BEAT)
            # Defensive per-beat reset: same logic as writer mode.
            last_counter_beat = s.get("_round_counter_beat_no")
            if last_counter_beat != beat_no:
                s["rounds_for_beat"] = 0
                s["_round_counter_beat_no"] = beat_no
            s["rounds_for_beat"] += 1
            rounds = s["rounds_for_beat"]
            cap = s["max_rounds"]
            self._outline_session_state[chapter_id] = s
        else:
            ob_state = (
                self._outline_beat_state.get(chapter_id) or {})
            ob_state.setdefault("rounds_for_beat", 0)
            ob_state.setdefault(
                "max_rounds", self._OUTLINE_MAX_ROUNDS_PER_BEAT)
            ob_state["rounds_for_beat"] += 1
            rounds = ob_state["rounds_for_beat"]
            cap = ob_state["max_rounds"]
            beat_no = ob_state.get("beats_done", 0) + 1
            self._outline_beat_state[chapter_id] = ob_state

        # Build the chat-display message. Number questions so the
        # user can answer "answer to #2 is …" naturally.
        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        if questions:
            lines.append(
                f"**Beat {beat_no} — Phase-1 questions** "
                f"(round {rounds}/{cap})")
            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q}")
        else:
            lines.append(
                f"(Model returned phase=\"questions\" but no "
                f"questions — moving to write Beat {beat_no} on "
                f"the next message.)")

        # Round cap → flip ready so the next turn is forced into
        # phase=beat.
        if rounds >= cap:
            self._writer_ready_chapters.add(chapter_id)
            lines.append("")
            lines.append(
                f"*Round cap reached — send another message and "
                f"the model will produce Beat {beat_no} directly.*")
        else:
            lines.append("")
            lines.append(
                f"*Answer above, or say `proceed` to skip ahead "
                f"and produce Beat {beat_no} now.*")

        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))
        self._log_beat_state(
            "outline", chapter_id, "questions_landed")

        # Record Q&A so the cycling detector has a baseline + the
        # next turn's prompt sees what was asked already.
        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        joined_qs = "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, 1))
        try:
            self._record_writer_qa(
                chapter_id, pending_msg, joined_qs)
        except Exception:
            pass
        if pending_msg:
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant",
                 "content": joined_qs or "(no questions)"})
            self._compact_chat_history()
        self._pending_chat_message = ""

        # Focused-beat sessions: when the AI signals readiness
        # (phase=questions with an EMPTY questions array, or the
        # round cap was just hit), the next turn would already
        # produce phase=beat. Without an auto-send the user sees
        # "moving to write Beat X on the next message" + has to
        # type something — that's the "AI says it has enough but
        # nothing lands in the checklist" report. Auto-send a
        # "proceed" for them so the focused-beat flow completes
        # in one click.
        if self._focused_beat_ai.get(chapter_id) and (
                not questions or rounds >= cap):
            try:
                from PyQt6.QtCore import QTimer as _QT
                _QT.singleShot(
                    0,
                    lambda: self._auto_send_focused_beat_proceed(
                        chapter_id))
            except Exception:
                pass

    def _auto_send_focused_beat_proceed(self,
                                          chapter_id: str) -> None:
        """Re-fire the LLM with a synthetic 'proceed' for focused
        beats so the AI's "I have enough" turn flows straight into
        the beat-write turn without a manual user nudge.
        """
        # Sanity: panel must still be on this chapter and the
        # focused session must still be set (the user might have
        # clicked away while the LLM was thinking).
        focus = self._focused_beat_ai.get(chapter_id)
        if not focus:
            return
        panel = getattr(self.chat_widget, "outline_panel", None)
        if panel is None or panel.current_chapter_id() != chapter_id:
            return
        # Don't auto-fire on top of an in-flight LLM call.
        if (self._chat_worker is not None
                and self._chat_worker.isRunning()):
            return
        # Pin to writer + outline output so the response routes
        # through the outline JSON parser (the focused-beat session
        # was started with these modes, but the user may have
        # toggled away in the meantime — we re-pin defensively).
        try:
            self.chat_widget.set_mode("writer")
        except Exception:
            pass
        try:
            self.chat_widget.set_output_mode("outline")
        except Exception:
            pass
        try:
            insert_mode = (
                self.chat_widget.get_insert_mode()
                if hasattr(self.chat_widget, "get_insert_mode")
                else "")
        except Exception:
            insert_mode = ""
        # Visible nudge so the user understands what's happening
        # (and can stop sending their own message into the void).
        self.chat_widget.add_message(
            "Assistant",
            "_Producing the developed beat now…_")
        # Drive the dispatcher's beat_write_force path with mode
        # explicitly set to "writer" so _pending_output_mode picks
        # up "outline" + the response handler routes phase="beat"
        # to our focused-beat path.
        self._handle_chat_message(
            "proceed", "writer", insert_mode)

    def _handle_outline_json_beat(self,
                                   chapter_id: str,
                                   parsed: dict) -> None:
        """Render a JSON ``phase=beat`` reply into the outline panel.

        Serializes the ``beat`` dict to outline-panel markdown,
        appends it to the panel, advances the per-beat state, and
        surfaces a "Beat N added" confirmation. Honours
        ``outline_complete: true`` to close the loop.
        """
        beat = parsed.get("beat") or {}
        thinking = (parsed.get("thinking") or "").strip()
        outline_complete = bool(parsed.get("outline_complete"))
        if not isinstance(beat, dict) or not beat:
            self.chat_widget.add_message(
                "Assistant",
                "(Model emitted phase=\"beat\" but no beat object — "
                "try resending.)")
            self._pending_chat_message = ""
            return
        ob_state = self._outline_beat_state.get(chapter_id) or {}
        # Engine-controlled beat number — prefer the audit-derived
        # current_beat_number over a naive beats_done+1, and ALWAYS
        # override whatever the model returned. This is what stops
        # the model from looping back to Beat 1 after the audit
        # established Beat 4 as the start.
        next_no = ob_state.get(
            "current_beat_number",
            ob_state.get("beats_done", 0) + 1)
        model_no = beat.get("number")
        try:
            model_no_int = int(model_no) if model_no else None
        except Exception:
            model_no_int = None
        if (model_no_int is not None
                and model_no_int != next_no):
            self.chat_widget.add_message(
                "Assistant",
                f"(Model returned beat number {model_no_int} but "
                f"engine asked for Beat {next_no} — using "
                f"engine's number to keep the queue ordered.)")
        # Engine-controlled title + stage — pull from the audit
        # entry for this beat number so the panel heading always
        # matches the planned event, regardless of what the model
        # decided to call it. (Otherwise the model can return Beat
        # 1's title when the engine asked for Beat 4's number.)
        forced_title = ""
        forced_stage = ""
        for entry in (ob_state.get("audit") or []):
            if entry.get("beat_number") == next_no:
                forced_title = (entry.get("title") or "").strip()
                forced_stage = (entry.get("stage") or "").strip()
                break
        if forced_title:
            model_title = (beat.get("title") or "").strip()
            if (model_title
                    and model_title.lower()
                        != forced_title.lower()):
                self.chat_widget.add_message(
                    "Assistant",
                    f"(Model returned title \"{model_title[:60]}\" "
                    f"but engine planned title is "
                    f"\"{forced_title}\" — using engine's title.)")
        beat_md = self._outline_beat_json_to_markdown(
            beat,
            fallback_number=next_no,
            force_number=True,
            force_title=forced_title,
            force_stage=forced_stage)
        if not beat_md.strip():
            self.chat_widget.add_message(
                "Assistant",
                "(Model emitted phase=\"beat\" but the beat object "
                "had no usable content — try resending.)")
            self._pending_chat_message = ""
            return

        panel = getattr(self.chat_widget, "outline_panel", None)
        if panel is None:
            return
        if panel.current_chapter_id() != chapter_id:
            ce = self.manuscript_editor.current_chapter_editor
            title = getattr(ce.chapter, "title", "") or ""
            panel.load_chapter(
                chapter_id, title, panel.get_outline_text())

        outline_action = getattr(
            self, "_pending_outline_action", "populate")
        if outline_action == "replace":
            panel.set_outline_text(beat_md)
        else:
            panel.append_outline_text(beat_md)

        # Switch sidebar to Outline tab so the user sees the new card.
        tabs = getattr(self, "sidebar_tabs", None)
        if tabs is not None:
            idx = tabs.indexOf(panel)
            if idx >= 0:
                tabs.setCurrentIndex(idx)

        # Update outline beat state. ``beats_done`` tracks how many
        # beats are in the panel; ``current_beat_number`` tracks
        # which beat the model should produce NEXT — incremented
        # after each beat lands so the engine stays one step ahead.
        beat_no = next_no
        ob_state["beats_done"] = max(
            ob_state.get("beats_done", 0), beat_no)
        ob_state["current_beat_number"] = beat_no + 1
        ob_state["rounds_for_beat"] = 0
        ob_state["force_write"] = False
        if outline_complete or beat_no >= self._OUTLINE_MAX_BEATS:
            ob_state["complete"] = True
        self._outline_beat_state[chapter_id] = ob_state
        # Clear ready flag so the next beat gets its own Phase-1.
        self._writer_ready_chapters.discard(chapter_id)
        self._log_beat_state(
            "outline", chapter_id,
            f"beat_{beat_no}_landed_advance_to_{beat_no + 1}")

        # Build the chat confirmation.
        lines = []
        if thinking:
            lines.append(f"_{thinking}_")
            lines.append("")
        if outline_complete:
            lines.append(
                f"**Outline complete** — {beat_no} beats in the "
                f"Outline tab. Switch the AI Assistant back to "
                f"Full Text and ask me to write the chapter; I'll "
                f"do it beat by beat using this outline.")
        else:
            beat_title = (beat.get("title") or "").strip() or "(untitled)"
            lines.append(
                f"**Beat {beat_no} added** — \"{beat_title}\". Send "
                f"a follow-up to refine, or send the next message "
                f"to continue with Beat {beat_no + 1}.")
        self.chat_widget.add_message(
            "Assistant", "\n".join(lines))

        # Chat-history bookkeeping.
        pending_msg = getattr(
            self, "_pending_chat_message", "") or ""
        if pending_msg:
            marker = (
                "(Outline complete.)" if outline_complete
                else f"(Beat {beat_no} added to outline.)")
            self._chat_history.append(
                {"role": "user", "content": pending_msg})
            self._chat_history.append(
                {"role": "assistant", "content": marker})
            self._compact_chat_history()
        self._pending_outline_action = (
            "populate" if outline_action != "edit" else "edit")
        self._pending_chat_message = ""

    @staticmethod
    def _normalize_outline_response(text: str,
                                     next_beat_number: int = 1) -> tuple:
        """Coerce a model outline response into ``## [ ] Beat N: …`` form.

        Returns ``(normalized_text, note)``. ``note`` is a chat-
        ready string explaining what was done (or empty when the
        response was already in the expected shape). Three tiers:

        T1 STRICT — already has at least one ``## `` heading; pass
            through unchanged.
        T2 NORMALIZE — has a heading-like line in another style
            (``###``, ``# Beat 1``, ``**Beat 1: …**``). Rewrite the
            first such line as ``## [ ] Beat <N>: <stripped title>``
            and pass through.
        T3 WRAP — no heading-like line at all (pure narrative or
            bullets). Strip chatty wrappers ("Writing the first beat
            now"), then wrap the whole thing as one synthetic beat.

        Empty ``text`` returns ``("", "")`` — caller decides how to
        handle that (the no-content branch fires elsewhere).
        """
        import re as _re
        text = (text or "").strip()
        if not text:
            return ("", "")

        strict_re = _re.compile(
            r"^##\s+(?:\[[ xX]\]\s+)?\S", _re.MULTILINE)
        if strict_re.search(text):
            return (text, "")

        # T2 — heading-like first line.
        # `### Beat 1: …`, `# Beat 1: …`, `**Beat 1: …**`, or
        # `Beat 1:` at the start (some models drop the heading
        # prefix entirely but still write a labeled line).
        soft_heading_res = [
            _re.compile(r"^#{1,6}\s+(?:\[[ xX]\]\s+)?(.+)$",
                         _re.MULTILINE),
            _re.compile(
                r"^\*\*\s*(?:\[[ xX]\]\s+)?(beat\s+\d+[:\-—].+?)\s*\*\*",
                _re.MULTILINE | _re.IGNORECASE),
            _re.compile(
                r"^(?:\[[ xX]\]\s+)?(beat\s+\d+[:\-—].+)$",
                _re.MULTILINE | _re.IGNORECASE),
        ]
        for rx in soft_heading_res:
            m = rx.search(text)
            if not m:
                continue
            title = (m.group(1) or "").strip()
            # Strip any trailing ** from the bold-style match.
            title = _re.sub(r"\*+\s*$", "", title).strip()
            # Drop a leading task-list marker if the heading already
            # carried one — we'll add it ourselves.
            title = _re.sub(
                r"^\[[ xX]\]\s+", "", title, flags=_re.IGNORECASE)
            new_heading = f"## [ ] {title}"
            normalized = (
                text[: m.start()] + new_heading + text[m.end():])
            note = (
                f"(Normalized the model's heading style into "
                f"`## [ ] {title[:60]}…` so it renders as a beat "
                f"card.)")
            return (normalized, note)

        # T3 — no heading at all. Strip chatty wrappers from the
        # top, then wrap as a synthetic beat.
        chatty_lines = (
            "writing the", "thank you", "i have everything",
            "i'll proceed", "since the previous", "i will proceed",
            "let me", "here's", "here is",
        )
        lines = text.splitlines()
        # Drop leading chatty lines until we hit content.
        while lines and any(
                lines[0].strip().lower().startswith(p)
                for p in chatty_lines):
            lines.pop(0)
        body = "\n".join(lines).strip()
        if not body:
            return ("", "")
        # Title from the first sentence/line, capped to a reasonable
        # length so it fits in the checklist heading.
        title_seed = body.split("\n", 1)[0].strip()
        title_seed = _re.sub(r"[*_`]+", "", title_seed)
        if len(title_seed) > 70:
            title_seed = title_seed[:67].rsplit(" ", 1)[0] + "…"
        if not title_seed:
            title_seed = f"Beat {next_beat_number}"
        synthetic = (
            f"## [ ] Beat {next_beat_number}: {title_seed}\n\n{body}")
        snippet = body[:100].replace("\n", " ")
        note = (
            f"(Model returned narrative content without a "
            f"`## [ ] Beat N: …` heading. Wrapped it as Beat "
            f"{next_beat_number}; edit the heading in the panel "
            f"to clean up. First line was: \"{snippet}…\")")
        return (synthetic, note)

    def _events_to_outline_markdown(self, events) -> str:
        """Render chapter.planning.events as outline-panel markdown.

        Each StoryEvent becomes one beat heading; the event's
        description (if any) drops into a small body. Completed
        events become ``[x]``, others ``[ ]`` so the checklist
        reflects the existing completion state.
        """
        lines = []
        for i, ev in enumerate(events, 1):
            text = (getattr(ev, 'text', '') or '').strip()
            if not text:
                text = f"Beat {i}"
            stage = (getattr(ev, 'stage', '') or '').strip()
            heading = f"## [{'x' if getattr(ev, 'completed', False) else ' '}] Beat {i}: {text}"
            if stage:
                heading += f" — {stage}"
            lines.append(heading)
            desc = (getattr(ev, 'description', '') or '').strip()
            if desc:
                lines.append("")
                lines.append(desc)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _handle_panel_beat_ai_help(
            self,
            beat_title: str,
            beat_body_md: str,
            beat_stage: str) -> None:
        """Forward an outline-panel ✨ click into the chat router.

        Reuses ``_handle_beat_ai_help_requested`` (originally wired
        to the chapter planner's per-event ✨) so both entry points
        produce the same focused-prompt staging.
        """
        ce = getattr(self.manuscript_editor,
                     "current_chapter_editor", None)
        chapter_id = (getattr(ce.chapter, "id", "")
                      if ce and getattr(ce, "chapter", None)
                      else "")
        self._handle_beat_ai_help_requested(
            event_id="",
            event_text=beat_title,
            event_description=beat_body_md,
            event_stage=beat_stage,
            chapter_id=chapter_id)

    def _build_focused_beat_context(self,
                                       chapter_id: str,
                                       beat_text: str,
                                       beat_description: str) -> str:
        """Compact local-neighbourhood context for a per-beat AI ask.

        Returns a multi-line string with: chapter title, the beat
        being developed, and (if found) the immediately preceding
        and following beats. Wider context (main plot, subplots,
        characters, worldbuilding) is added at chat-send time by
        the existing ``_build_context_prompt`` pipeline; this
        helper exists so the AI sees the LOCAL plot neighbourhood
        in the user-visible prompt itself.

        Returns "" when there's nothing to add (e.g. no project
        loaded, or the beat isn't found in the chapter).
        """
        if not self.current_project:
            return ""
        manuscript = getattr(
            self.current_project, "manuscript", None)
        chapters = getattr(manuscript, "chapters", None) or []
        chapter = next(
            (c for c in chapters
             if getattr(c, "id", None) == chapter_id),
            None)
        if chapter is None:
            return ""
        events = list(
            getattr(getattr(chapter, "planning", None),
                    "events", []) or [])

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        target_norm = _norm(beat_text)
        # Find this beat in events by exact (normalised) title match.
        idx = next(
            (i for i, ev in enumerate(events)
             if _norm(getattr(ev, "text", "")) == target_norm),
            None)

        lines: list[str] = []
        chapter_title = (
            getattr(chapter, "title", "") or "").strip()
        if chapter_title:
            lines.append(
                f"\nChapter: \"{chapter_title}\"")

        if idx is not None:
            total = len(events)
            lines.append(
                f"This beat is {idx + 1} of {total} in the chapter "
                "plot arc.")
            if idx > 0:
                prev_ev = events[idx - 1]
                prev_text = (
                    getattr(prev_ev, "text", "") or "(untitled)")
                prev_desc = (
                    getattr(prev_ev, "description", "") or ""
                ).strip()
                lines.append(
                    f"\nPrevious beat ({idx}): \"{prev_text}\"")
                if prev_desc:
                    # Cap to keep the prompt tight — the system
                    # context-prompt pipeline carries the full
                    # outline anyway.
                    lines.append(prev_desc[:400])
            if idx < total - 1:
                next_ev = events[idx + 1]
                next_text = (
                    getattr(next_ev, "text", "") or "(untitled)")
                next_desc = (
                    getattr(next_ev, "description", "") or ""
                ).strip()
                lines.append(
                    f"\nNext beat ({idx + 2}): \"{next_text}\"")
                if next_desc:
                    lines.append(next_desc[:400])
        else:
            # Beat not in events list — likely a brand-new card the
            # user just added. Show the nearby beats from the panel
            # so the AI still has neighbourhood context.
            panel = getattr(self.chat_widget, "outline_panel", None)
            sel_idx = (panel.selected_beat_index()
                       if panel is not None else None)
            if (panel is not None and sel_idx is not None):
                beats = panel.all_beats()
                if 0 <= sel_idx < len(beats):
                    total = len(beats)
                    lines.append(
                        f"This beat is {sel_idx + 1} of {total} in "
                        "the chapter plot arc.")
                    if sel_idx > 0:
                        prev = beats[sel_idx - 1]
                        lines.append(
                            f"\nPrevious beat ({sel_idx}): "
                            f"\"{prev.title}\"")
                    if sel_idx < total - 1:
                        nxt = beats[sel_idx + 1]
                        lines.append(
                            f"\nNext beat ({sel_idx + 2}): "
                            f"\"{nxt.title}\"")
        return "\n".join(lines).rstrip()

    def _handle_beat_ai_help_requested(
            self,
            event_id: str,
            event_text: str,
            event_description: str,
            event_stage: str,
            chapter_id: str) -> None:
        """Route a per-beat ✨ AI-help click into the outline chat.

        Switches the sidebar to the AI Assistant tab, picks
        outline mode, and types a focused prompt that names the
        target beat plus the surrounding beats / chapter so the
        AI has the local plot context up front. The wider story-
        wide context (main plot, subplots, characters,
        worldbuilding) is added by the existing context-prompt
        pipeline when the user sends — this prompt is the local
        framing on top of that.

        The prompt explicitly tells the AI to ask up to four
        clarifying questions (one round at a time) before producing
        the fleshed-out beat. We don't auto-send so the user can
        edit first.

        Records a focused-beat session so the next AI response with
        phase="beat" lands DIRECTLY in this beat's body (rather
        than going through the normal staging/apply pipeline).
        """
        # Record which beat this session is for so the JSON response
        # is pushed straight into THAT beat's body in the panel.
        try:
            panel = getattr(self.chat_widget, "outline_panel", None)
            sel_idx = (panel.selected_beat_index()
                       if panel is not None else None)
            target_chapter = chapter_id or (
                panel.current_chapter_id() if panel else "")
            if target_chapter and sel_idx is not None:
                import time as _time
                self._focused_beat_ai[target_chapter] = {
                    "beat_index": sel_idx,
                    "beat_title": (event_text or "").strip(),
                    "started_at": _time.time(),
                }
                # Pre-populate the outline session so the FIRST user
                # send drops straight into BEAT_QUESTIONS for the
                # clicked beat. Without this, the dispatcher would
                # kick off pick_start (asks the AI which beat to
                # start with), then await_proceed (user types
                # "proceed"), and only THEN enter beat_questions —
                # the focused-beat user has already told us which
                # beat by clicking ✨, so all that is wasted turns
                # and explains "AI says ready but nothing lands".
                # The dispatcher's beat_questions branch then drives
                # the up-to-4 question loop and force-flips to
                # beat_write at the cap, which is what feeds JSON
                # to _handle_focused_beat_response.
                self._outline_session_state[target_chapter] = {
                    "phase": self._OUTLINE_PHASE_BEAT_QUESTIONS,
                    "current_beat_number": sel_idx + 1,
                    "current_beat_index": sel_idx,
                    "rounds_for_beat": 0,
                    "max_rounds":
                        self._OUTLINE_MAX_ROUNDS_PER_BEAT,
                    "audit": [],
                    "staging": [],
                    "started": True,
                    "_focused": True,
                }
        except Exception:
            pass
        # Ensure the sidebar is visible + on the AI Assistant tab.
        if hasattr(self, "sidebar_container"):
            try:
                self.sidebar_container.expand()
            except Exception:
                pass
        if hasattr(self, "sidebar_tabs"):
            idx = self.sidebar_tabs.indexOf(self.chat_widget)
            if idx >= 0:
                self.sidebar_tabs.setCurrentIndex(idx)
        # Switch the chat to writer mode + outline output. BOTH are
        # required for the focused-beat flow to work end-to-end:
        #
        #   * Setting output_mode alone is NOT enough — the response
        #     handler reads _pending_output_mode, which only gets
        #     populated from the chat widget when mode == "writer"
        #     (otherwise it's force-pinned to "full_text"). Without
        #     mode="writer" the outline JSON parser never runs and
        #     the AI's phase="beat" reply silently falls into the
        #     writer-prose branch instead of our focused-beat handler.
        #   * Setting mode alone is NOT enough — the outline-mode
        #     JSON contract (phase: "questions" / "beat") only
        #     applies when output_mode is "outline".
        try:
            self.chat_widget.set_mode("writer")
        except Exception:
            pass
        try:
            self.chat_widget.set_output_mode("outline")
        except Exception:
            pass
        # Compose the focused prompt for this beat — pulls in the
        # immediate plot neighbourhood (prev / next beat) so the AI
        # doesn't have to ask questions the surrounding beats
        # already answer.
        beat_label = (event_text or "(untitled beat)").strip()
        local_context = self._build_focused_beat_context(
            chapter_id=chapter_id,
            beat_text=beat_label,
            beat_description=event_description)
        prompt_parts = [
            f"Develop this beat for the current chapter: "
            f"\"{beat_label}\""
            + (f" [{event_stage}]" if event_stage else ""),
        ]
        if event_description:
            prompt_parts.append(
                f"\nWhat I have so far for this beat:\n"
                f"{event_description}")
        if local_context:
            prompt_parts.append(local_context)
        prompt_parts.append(
            "\nProcess:\n"
            "  1. Ask up to FOUR rounds of clarifying questions, "
            "one round at a time. Each round's questions must be "
            "unique (don't repeat earlier rounds) and clearly "
            "relevant to fleshing out THIS beat.\n"
            "  2. Lean on the surrounding beats, chapter outline, "
            "story plots and subplots, characters, and "
            "worldbuilding context (provided in the system prompt) "
            "before asking — only ask what those don't already "
            "answer.\n"
            "  3. After the questions (or sooner if I tell you to "
            "produce now), output the structured outline JSON for "
            "ONLY this beat — keep its title exactly as I named "
            "it: \"" + beat_label + "\".")
        prompt = "\n".join(prompt_parts)
        # Stage the prompt in the input field — user reviews + sends.
        try:
            self.chat_widget.input_field.setPlainText(prompt)
            self.chat_widget.input_field.setFocus()
        except Exception:
            # Fallback: just post a chat message with the prompt.
            self.chat_widget.add_message(
                "Assistant",
                f"_Drafted prompt for **Beat: {beat_label}**: "
                f"send it as your next message to start the "
                f"per-beat outline flow._\n\n{prompt}")

    def _sync_panel_beats_to_planning_events(
            self, outline_text: str) -> None:
        """Reconcile chapter.planning.events with the panel's beats.

        Triggered on every outline_panel.outline_changed signal.
        Performs a FULL reconciliation: the panel's beat order +
        membership becomes the events list. For each panel beat:

          * Title matches an existing event (case-insensitive,
            stripping the ``Beat N:`` prefix) → reuse the event,
            preserving its id, description, stage, completed.
          * Title is new → create a new StoryEvent.
          * Existing event whose title isn't in the panel → drop.

        This is what lets ↑/↓ reorder and × delete in the panel
        flow into the chapter plot arc. Existing event ids and
        descriptions are preserved when possible so AI work on a
        beat survives a rename or reorder.
        """
        # Target the chapter the PANEL is bound to, NOT the
        # manuscript editor's current chapter. The two diverge
        # during the flush-on-switch race: when the user clicks
        # a different chapter while a panel-edit autosave is
        # pending, panel.load_chapter flushes via outline_changed,
        # but by then manuscript_editor.current_chapter_editor has
        # already been swapped to the new chapter. Using the
        # current editor would write the OLD chapter's beats into
        # the NEW chapter's events list. The panel's bound id is
        # always the chapter the outline_text actually belongs to.
        panel = getattr(self.chat_widget, 'outline_panel', None)
        if panel is None:
            return
        target_id = panel.current_chapter_id()
        if not target_id or not self.current_project:
            return
        chapter = None
        manuscript = getattr(self.current_project, 'manuscript', None)
        for ch in (getattr(manuscript, 'chapters', None) or []):
            if getattr(ch, 'id', None) == target_id:
                chapter = ch
                break
        if chapter is None:
            return
        if (not hasattr(chapter, 'planning')
                or chapter.planning is None):
            return
        existing_events = list(
            getattr(chapter.planning, 'events', []) or [])

        from src.ui.outline_panel import _parse_beats
        _, panel_beats = _parse_beats(outline_text or "")
        if not panel_beats:
            # Empty panel doesn't wipe events — defensive against
            # transient parse glitches. The user can clear events
            # via the planner widget directly.
            return

        import re as _re
        from src.models.project import StoryEvent
        import uuid as _uuid

        # Stage names that _events_to_outline_markdown appends to
        # the heading as ``— <stage>``. We strip exactly these (and
        # nothing else) when extracting the bare title — otherwise
        # the stage suffix becomes part of the saved event text and
        # accumulates / corrupts the AI-generated beat name on every
        # round-trip through the panel.
        _STAGE_SLUGS = {
            "exposition", "rising", "climax",
            "falling", "resolution",
        }

        def _strip_stage_suffix(title: str) -> str:
            """Drop a trailing ``— <known-stage>`` from a beat title."""
            m = _re.match(
                r"^(.*?)\s+[—\-]\s+(\w+)\s*$",
                title or "")
            if m and m.group(2).lower() in _STAGE_SLUGS:
                return m.group(1).rstrip()
            return title

        def _norm(s: str) -> str:
            t = (s or "").strip().lower()
            t = _re.sub(
                r"^beat\s+\d+\s*[:\-—]\s*", "", t)
            t = _strip_stage_suffix(t)
            return t.strip()

        # Build a lookup of existing events by normalised title so
        # we can preserve their ids/descriptions on rename.
        by_norm = {
            _norm(getattr(ev, "text", "") or ""): ev
            for ev in existing_events
        }

        new_events = []
        for pb in panel_beats:
            # Strip ``Beat N:`` prefix from the title.
            m = _re.match(
                r"^beat\s+\d+\s*[:\-—]?\s*(.*)$",
                pb.title.strip(), _re.IGNORECASE)
            bare_title = (m.group(1).strip() if m
                          else pb.title.strip())
            # Then drop the optional ``— <stage>`` suffix that the
            # panel renderer adds. event.text must be the clean AI
            # name so it's preserved verbatim across save/reload.
            bare_title = _strip_stage_suffix(bare_title).strip()
            if not bare_title:
                # Skip empty-titled beats — common right after a
                # "+ Add Beat" click before the user has typed.
                continue
            norm = _norm(bare_title)
            existing = by_norm.pop(norm, None)
            if existing is not None:
                # Preserve id, description, stage; refresh title
                # (in case of trivial casing change) + completed
                # (sync from panel checkbox).
                existing.text = bare_title
                existing.completed = pb.checked
                new_events.append(existing)
            else:
                body = "\n".join(pb.body_lines).strip()
                desc = (body.split("\n\n", 1)[0][:500]
                        if body else "")
                new_events.append(StoryEvent(
                    id=_uuid.uuid4().hex[:8],
                    text=bare_title,
                    description=desc,
                    stage="rising",
                    completed=pb.checked))

        # Anything left in by_norm = events the panel deleted.
        # by_norm contents are dropped silently.
        deleted_count = len(by_norm)
        added_count = sum(
            1 for ev in new_events
            if not any(
                getattr(e, "id", "") == ev.id
                for e in existing_events))
        reordered = (
            [getattr(e, "id", "") for e in existing_events]
            != [getattr(e, "id", "") for e in new_events])

        if (added_count == 0
                and deleted_count == 0
                and not reordered):
            # No-op — panel + events already match.
            return

        try:
            chapter.planning.events = new_events
        except Exception as e:
            print(
                f"[outline-sync] failed to write events: {e}")
            return
        # Refresh the planner widget — but ONLY if the chapter we
        # just wrote events into is the one the manuscript editor
        # is currently displaying. During the flush-on-switch race
        # the panel writes to the OLD chapter while the editor has
        # already moved to the NEW one; refreshing the planner with
        # the OLD chapter's data would clobber the NEW chapter's
        # display.
        #
        # CRITICAL: this refresh is required for save persistence,
        # not just visual sync. ChapterEditor.save_to_model reads
        # the events list from the planner widget UI on every
        # autosave (which fires immediately below) — without the
        # refresh the planner UI is stale (still showing the
        # pre-AI-write state, often empty), so save_to_model would
        # write that empty list back to chapter.planning.events,
        # silently undoing the AI's outline → events sync.
        try:
            ce = getattr(self.manuscript_editor,
                         'current_chapter_editor', None)
            live_chapter = (
                getattr(ce, 'chapter', None) if ce else None)
            if (live_chapter is not None
                    and getattr(live_chapter, 'id', None) == target_id):
                planner = ce.planner_widget
                if hasattr(planner, "update_events"):
                    planner.update_events(chapter.planning.events)
        except Exception:
            pass
        try:
            self._auto_save_project()
        except Exception:
            pass
        print(
            f"[outline-sync] reconciled events: "
            f"+{added_count} added, -{deleted_count} removed, "
            f"reordered={reordered}, total={len(new_events)}",
            flush=True)

    def _handle_chapter_events_cleared(self, chapter_id: str) -> None:
        """Drop a chapter's plot arc + outline after user confirmed.

        Wired to ManuscriptEditor.events_cleared. The planner widget
        has already torn down its own event widgets; this handler
        is responsible for the cross-widget cleanup the planner
        can't reach on its own:

          * ``chapter.planning.events`` → []
          * ``chapter.planning.outline`` → ""
          * the AI-Assistant OutlinePanel → blanked, but only when
            it's bound to the same chapter
          * a project autosave so the cleared state survives close
        """
        if not chapter_id or not self.current_project:
            return
        manuscript = getattr(
            self.current_project, 'manuscript', None)
        chapters = getattr(manuscript, 'chapters', None) or []
        target = next(
            (ch for ch in chapters
             if getattr(ch, 'id', None) == chapter_id),
            None)
        if target is None:
            return
        if not hasattr(target, 'planning') or target.planning is None:
            return
        try:
            target.planning.events = []
            target.planning.outline = ''
            # Mirror to the legacy plan field so per-chapter plan.md
            # gets rewritten (empty) on next save_content_to_file.
            if hasattr(target, 'plan'):
                target.plan = ''
        except Exception as e:
            print(f"[clear-plot-arc] failed to clear: {e}")
            return
        # Blank the AI-Assistant outline panel — but ONLY when the
        # panel is currently bound to the same chapter the user
        # just cleared. Calling set_outline_text on a panel bound
        # to a different chapter would cross-write.
        try:
            panel = getattr(
                self.chat_widget, 'outline_panel', None)
            if (panel is not None
                    and panel.current_chapter_id() == chapter_id):
                panel.set_outline_text('')
        except Exception:
            pass
        try:
            self._auto_save_project()
        except Exception:
            pass
        print(
            f"[clear-plot-arc] chapter={chapter_id} events + "
            "outline cleared, panel blanked",
            flush=True)

    def _on_outline_panel_edited(self, outline_text: str) -> None:
        """Persist outline-panel edits back to chapter.planning.outline.

        Wired to OutlinePanel.outline_changed (debounced inside the
        panel). Schedules a project autosave so the change lives
        beyond the session.
        """
        panel = getattr(self.chat_widget, 'outline_panel', None)
        if panel is None:
            return
        target_id = panel.current_chapter_id()
        if not target_id or not self.current_project:
            return
        # Guard against the panel writing to a chapter the user has
        # since switched away from. The panel flushes pending writes
        # on chapter switch, so this should only happen if the user
        # is editing a different chapter than the panel is bound to.
        ce = getattr(self.manuscript_editor,
                     'current_chapter_editor', None)
        live_id = (getattr(ce.chapter, 'id', None)
                   if ce and getattr(ce, 'chapter', None) else None)
        # Find the chapter on the project (either current OR by id —
        # we always trust the panel's bound id).
        target = None
        manuscript = getattr(self.current_project, 'manuscript', None)
        chapters = getattr(manuscript, 'chapters', None) or []
        for ch in chapters:
            if getattr(ch, 'id', None) == target_id:
                target = ch
                break
        if target is None:
            return
        if not hasattr(target, 'planning') or target.planning is None:
            return
        # Only write if the text actually changed — keeps Pydantic /
        # autosave churn down on no-op signals.
        current_outline = (
            getattr(target.planning, 'outline', '') or '')
        if (current_outline or '') == (outline_text or ''):
            return
        try:
            target.planning.outline = outline_text or ''
        except Exception as e:
            print(f"[outline-panel] failed to persist outline: {e}")
            return
        # Trigger a quiet autosave so the edit isn't lost on close.
        # Always autosave — even when the panel is flushing edits
        # for a chapter the user has already navigated away from
        # (the flush-on-switch race). Skipping the save in that
        # case meant the in-memory edit was correct but the disk
        # copy stayed stale, so the edit silently disappeared on
        # the next project open.
        self._auto_save_project()

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

    # Source-type taxonomy. PROJECT sources are the author's own
    # story material — characters, worldbuilding, chapters, subplots,
    # plot scaffolding — and they are AUTHORITATIVE. REFERENCE sources
    # are real-world / mythology lookups that ground fiction in
    # plausible facts but never define story facts. Mixing them in
    # the same RAG dump made the model treat encyclopedia entries as
    # canonical project plot data, which it isn't. We split the
    # retrieval calls so the two streams land in distinct context
    # keys (rag_context vs reference_context) with very different
    # framing in the system prompt.
    PROJECT_SOURCE_TYPES = (
        "character", "chapter", "chapter_content",
        "chapter_key_point", "chapter_planning",
        "subplot", "worldbuilding", "place", "faction",
        "culture", "myth", "religion", "technology",
        "historical_event", "flora", "fauna",
        "star_system", "military", "economy",
        "political_system", "plot", "plot_event",
        "themes", "promise",
    )
    REFERENCE_SOURCE_TYPES = ("encyclopedia",)

    def _get_rag_context(self, query: str, max_tokens: int = 2000,
                         project_only: bool = True) -> str:
        """Get RAG-enhanced context for a query.

        Args:
            query: User's question or request.
            max_tokens: Maximum tokens for context.
            project_only: When True (default), filter the RAG search
                to PROJECT source types so encyclopedia hits don't
                bleed into the project-data stream. Use the dedicated
                ``_get_reference_rag_context`` method to fetch
                encyclopedia entries separately.

        Returns:
            Relevant context from project data (or reference data
            when ``project_only=False`` and no project filter applies).
        """
        if not self._rag_initialized or not self._rag_system:
            return ""

        try:
            if project_only:
                # Use the per-type chunker filtered to project sources
                # so encyclopedia entries are excluded from this stream.
                context = self._rag_top_chunks_per_type(
                    query=query,
                    source_types=list(self.PROJECT_SOURCE_TYPES),
                    top_k=8,
                    max_chars_per_chunk=600,
                    max_total_chars=max_tokens * 4,
                )
            else:
                context = self._rag_system.get_context_for_ai(
                    query=query,
                    max_tokens=max_tokens,
                    method=SearchMethod.HYBRID,
                )
            return context if context else ""
        except Exception as e:
            print(f"RAG context retrieval failed: {e}")
            return ""

    def _get_reference_rag_context(self, query: str,
                                     max_tokens: int = 1200) -> str:
        """Get encyclopedia-only RAG context (real-world reference).

        Returns hits from REFERENCE_SOURCE_TYPES so callers can label
        them distinctly from project material. Empty string when the
        knowledge base is disabled or RAG isn't initialised.
        """
        if not self._rag_initialized or not self._rag_system:
            return ""
        try:
            from src.config.ai_config import get_ai_config
            kb_enabled = get_ai_config().get_settings().get(
                "enable_knowledge_base", True)
            if not kb_enabled:
                return ""
        except Exception:
            pass
        try:
            return self._rag_top_chunks_per_type(
                query=query,
                source_types=list(self.REFERENCE_SOURCE_TYPES),
                top_k=5,
                max_chars_per_chunk=500,
                max_total_chars=max_tokens * 4,
            ) or ""
        except Exception as e:
            print(f"Reference RAG retrieval failed: {e}")
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
        # Knowledge-graph hook: when the retrieved chunk is for a
        # graph-annotatable entity (faction / place / character /
        # historical_event / etc.), append a short ``(related: …)``
        # suffix listing its outgoing edges. This brings the typed-
        # relationship signal to every chat mode that uses this method
        # — the bypass-route that doesn't go through
        # ``get_context_for_ai``. Falls through silently if the graph
        # isn't built or the entity has no node, so it never hurts.
        kg = getattr(self._rag_system, "knowledge_graph", None)
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
            related_suffix = ""
            if kg is not None and getattr(r, "source_id", ""):
                rel_line = kg.format_relations_line(
                    r.source_type, r.source_id, max_edges=8)
                if rel_line:
                    related_suffix = f"  (related: {rel_line})"
            line = f"{head}: {body}{related_suffix}"
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
        """Toggle the right-hand sidebar (AI Assistant + Outline)."""
        # New layout: the sidebar container owns the collapse state
        # for the whole AI Assistant + Outline area, so toggling the
        # menu action (Ctrl+B) collapses/expands it as a unit. Falls
        # back to the older show/hide behaviour if the container
        # isn't around (defensive — should always exist post-init).
        if hasattr(self, "sidebar_container"):
            self.sidebar_container.toggle()
        else:
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

        # Auto-flip writer-mode ready state when the user's message
        # reads like a "proceed / go ahead" signal. Without this, the
        # user has to wait for the model to also recognise the signal
        # and emit <context_ready/> on its own — which small models
        # often miss. Flipping here means the next writer call goes
        # straight to Phase 2 (write the prose) regardless of what
        # the model would have done.
        if (mode == "writer"
                and hasattr(self, "manuscript_editor")
                and self.manuscript_editor.current_chapter_editor
                and self._looks_like_proceed_signal(message)):
            ch_id_now = (self.manuscript_editor
                         .current_chapter_editor.chapter.id)
            self._writer_ready_chapters.add(ch_id_now)
        # Pull the writer-output mode (Full Text vs Outline) directly
        # from the chat widget so the existing message_sent signal
        # stays binary-compatible. Stash it into context so the
        # ChatWorker can branch the system prompt + into _pending so
        # the response handler can pick the right insertion path.
        if mode == "writer" and hasattr(self, "chat_widget"):
            try:
                output_mode = self.chat_widget.get_output_mode()
            except Exception:
                output_mode = "full_text"
            self._pending_output_mode = output_mode
            context['writer_output_mode'] = output_mode
        else:
            self._pending_output_mode = "full_text"

        # OUTLINE-FIRST + PER-BEAT-OUTLINE AUTO-ROUTE.
        #
        # The outline is generated beat by beat (mirroring how prose
        # is written): one beat per Phase-2 turn, with optional
        # Phase-1 questions before each beat (capped at 4 rounds).
        # The model emits ``<outline_complete/>`` when there are no
        # more beats to add.
        #
        # Two ways to enter this flow:
        #   * User selected Outline output mode → in_progress is
        #     started/continued.
        #   * User is in Full Text mode but the chapter has NO
        #     outline yet → silently flip into outline-generation
        #     until <outline_complete/>; then the next message in
        #     full-text mode kicks off prose writing.
        outline_first_redirect = False
        if (mode == "writer"
                and hasattr(self, "chat_widget")
                and getattr(self.chat_widget, "outline_panel", None)
                is not None):
            panel = self.chat_widget.outline_panel
            ce = getattr(self.manuscript_editor,
                         "current_chapter_editor", None)
            ch_id_now = (
                ce.chapter.id
                if (ce is not None
                    and getattr(ce, "chapter", None)) else None)
            ob_state = (
                self._outline_beat_state.get(ch_id_now)
                if ch_id_now else None)
            outline_in_progress = bool(
                ob_state and ob_state.get("in_progress")
                and not ob_state.get("complete"))

            existing_outline = (panel.get_outline_text() or "").strip()
            if not existing_outline and ce is not None and ch_id_now:
                if (hasattr(ce.chapter, "planning")
                        and ce.chapter.planning is not None):
                    existing_outline = (
                        getattr(ce.chapter.planning, "outline", "")
                        or "").strip()

            # Hold the user in outline mode while generation is
            # mid-flight. The user can interrupt by switching the
            # output dropdown back to Full Text, which clears the
            # state below.
            if (outline_in_progress
                    and self._pending_output_mode == "full_text"):
                self._pending_output_mode = "outline"
                context['writer_output_mode'] = "outline"

            # Empty-outline + Full Text → kick off per-beat outline
            # generation transparently.
            if (self._pending_output_mode == "full_text"
                    and not existing_outline and ch_id_now):
                self._pending_output_mode = "outline"
                context['writer_output_mode'] = "outline"
                outline_first_redirect = True
                self.chat_widget.add_message(
                    "Assistant",
                    "No outline for this chapter yet — producing one "
                    "beat by beat. Each beat will land in the Outline "
                    "tab as it's generated; you can refine each one "
                    "before the next, just like writing prose. When "
                    "the model signals the outline is complete, ask "
                    "me to write the chapter and I'll switch to prose.")
                # First message in outline mode → kick off the
                # autonomous-system flow. The engine asks the model
                # to pick a starting beat (with the deterministic
                # audit as context). Subsequent turns route on
                # ``session["phase"]``.
                self._dispatch_outline_session_turn(
                    ch_id_now, ce.chapter, message, context)
                # The dispatcher decides whether this turn calls the
                # LLM (and if so, returns False so the function
                # continues to the worker start). When it handles
                # the message itself (e.g. "proceed", "looks good",
                # apply choice), it returns True and we stop here.
                if not context.get(
                        "_outline_session_send_to_llm"):
                    return
            elif (self._pending_output_mode == "outline"
                  and ch_id_now):
                # Subsequent outline-mode turn — route by session
                # phase. Same dispatcher as above; it manages the
                # state machine + decides whether to call the LLM.
                self._dispatch_outline_session_turn(
                    ch_id_now, ce.chapter, message, context)
                if not context.get(
                        "_outline_session_send_to_llm"):
                    return

            # NOTE: outline_beat_focus is now built by
            # _inject_outline_beat_context inside the new session
            # dispatcher (_dispatch_outline_session_turn). The legacy
            # block here used to read _outline_beat_state["beats_done"]
            # which the new flow doesn't populate, leading to
            # KeyError when phase=questions handlers had partially
            # initialised the dict. The legacy code is removed; the
            # session dispatcher is the single source of truth for
            # outline focus context.

        # Outline routing: when the user is in writer + outline mode,
        # decide whether this run POPULATES, EDITS, or REPLACES the
        # outline panel. If the panel already has content (or the
        # current chapter's planning.outline is non-empty), pop a
        # modal ONCE per chapter session so the user picks. After
        # the choice is made the action sticks on the outline beat
        # state — subsequent turns reuse it without re-asking.
        self._pending_outline_action = "populate"
        if (mode == "writer"
                and self._pending_output_mode == "outline"
                and hasattr(self, "chat_widget")
                and getattr(self.chat_widget, "outline_panel", None)
                is not None):
            panel = self.chat_widget.outline_panel
            ob_state_now = (
                self._outline_beat_state.get(ch_id_now)
                if ch_id_now else None) or {}
            sticky_action = ob_state_now.get("outline_action")
            audit_done = bool(ob_state_now.get("audit_status"))
            if sticky_action:
                # Already decided this session — reuse without
                # nagging the user every turn.
                self._pending_outline_action = sticky_action
                if sticky_action == "edit":
                    existing_outline = (
                        panel.get_outline_text() or "").strip()
                    if existing_outline:
                        context['existing_outline'] = existing_outline
                context['outline_action'] = sticky_action
            elif audit_done:
                # Engine-computed audit handles existing-content
                # detection deterministically — already-outlined
                # beats are skipped, pending beats are produced.
                # That's effectively the "edit/extend" path; no
                # need to ask the user.
                self._pending_outline_action = "populate"
                ob_state_now["outline_action"] = "populate"
                self._outline_beat_state[ch_id_now] = ob_state_now
                context['outline_action'] = "populate"
            else:
                existing_outline = (
                    panel.get_outline_text() or "").strip()
                # Fall back to chapter.planning.outline in case the
                # panel hasn't synced yet (e.g. first send after
                # project load).
                if not existing_outline:
                    ce = getattr(self.manuscript_editor,
                                 "current_chapter_editor", None)
                    if (ce is not None and getattr(ce, "chapter", None)
                            and hasattr(ce.chapter, "planning")
                            and ce.chapter.planning is not None):
                        existing_outline = (
                            getattr(ce.chapter.planning, "outline", "")
                            or "").strip()
                if existing_outline:
                    from PyQt6.QtWidgets import QMessageBox
                    box = QMessageBox(self)
                    box.setWindowTitle("Outline already exists")
                    box.setIcon(QMessageBox.Icon.Question)
                    box.setText(
                        "This chapter already has an outline in the "
                        "panel. How should I proceed?")
                    box.setInformativeText(
                        "• Edit — refine the existing outline "
                        "through the normal Q&A flow (up to 4 "
                        "question rounds per beat).\n"
                        "• Replace — fully overwrite the outline "
                        "with a fresh one based on this prompt.\n"
                        "• Cancel — drop this message and don't "
                        "send anything.\n\n"
                        "(Asked once per chapter session.)")
                    edit_btn = box.addButton(
                        "Edit existing",
                        QMessageBox.ButtonRole.AcceptRole)
                    replace_btn = box.addButton(
                        "Replace",
                        QMessageBox.ButtonRole.DestructiveRole)
                    cancel_btn = box.addButton(
                        "Cancel", QMessageBox.ButtonRole.RejectRole)
                    box.setDefaultButton(edit_btn)
                    box.exec()
                    clicked = box.clickedButton()
                    if clicked is cancel_btn:
                        self.chat_widget.add_message(
                            "Assistant",
                            "(Outline send cancelled — your prompt "
                            "was not sent.)")
                        self._pending_chat_message = ""
                        self._pending_outline_action = "populate"
                        return
                    if clicked is replace_btn:
                        self._pending_outline_action = "replace"
                    else:
                        self._pending_outline_action = "edit"
                        context['existing_outline'] = existing_outline
                else:
                    self._pending_outline_action = "populate"
                # Make the choice sticky so we don't ask again on
                # subsequent turns this session.
                if ch_id_now:
                    if ob_state_now is None or not ob_state_now:
                        ob_state_now = self._outline_beat_state.get(
                            ch_id_now) or {}
                    ob_state_now["outline_action"] = (
                        self._pending_outline_action)
                    self._outline_beat_state[ch_id_now] = ob_state_now
                context['outline_action'] = (
                    self._pending_outline_action)

        # Conversation history flows for ALL modes now. Writer used to
        # be single-shot and the history was deliberately wiped, but
        # the phased Q&A protocol relies on multi-turn coherence — the
        # model needs to remember what it already asked or it cycles
        # on duplicate questions. Pass the same history for writer
        # that other modes get; the per-chapter Q&A registry below
        # provides finer-grained dedup guidance.
        context['conversation_history'] = list(self._chat_history)

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

        # Inject the project + a RAG search callable into context so
        # the worker's pre-flight lookup loop has what it needs to
        # dispatch the model's <lookup_*> tool calls. Both are
        # process-internal references — they never leak into the
        # prompt because ``_build_context_prompt`` only reads the
        # string keys (plot_events, characters, etc.).
        context['_project'] = self.current_project
        if (hasattr(self, "_rag_top_chunks_per_type")
                and getattr(self, "_rag_initialized", False)):
            context['_rag_search'] = lambda q, st: (
                self._rag_top_chunks_per_type(
                    query=q, source_types=st,
                    top_k=6, max_chars_per_chunk=600,
                    max_total_chars=2500))
        else:
            context['_rag_search'] = None

        # Surface recent AI insertions for the open chapter so the
        # writer / chapter-focus model can refer back to them when
        # the user says "edit that scene" / "add tension to the part
        # you just wrote". The model sees the insertion records in a
        # labelled prompt block and can emit
        # ``<edit_last_insertion>`` to target the prose by index.
        if (mode in ("writer", "chapter_focus")
                and hasattr(self, "manuscript_editor")
                and self.manuscript_editor.current_chapter_editor):
            ch_id = (self.manuscript_editor
                     .current_chapter_editor.chapter.id)
            recent = self._get_recent_insertions(ch_id, limit=3)
            if recent:
                context['recent_insertions'] = recent

        # Writer-mode pre-write coverage analysis: tell the agent
        # which planned events are already covered in the existing
        # chapter text and which still need writing. Used by the
        # phased pre-write protocol so the agent only writes the
        # REMAINING beats — not the whole chapter from scratch when
        # half of it is already on the page. Also carries the
        # session's ``ready_to_write`` flag so the agent knows
        # whether the user has signed off on its proposed plan.
        if (mode == "writer"
                and hasattr(self, "manuscript_editor")
                and self.manuscript_editor.current_chapter_editor):
            chapter = (self.manuscript_editor
                       .current_chapter_editor.chapter)
            context['chapter_coverage'] = (
                self._compute_chapter_coverage(chapter))
            ready_set = getattr(self, "_writer_ready_chapters", set())
            context['writer_ready_to_write'] = (
                chapter.id in ready_set)
            # Pre-write Q&A history for this chapter — surfaced so
            # the model can see what it already asked + what the
            # user answered. Without this the model often re-asks
            # the same question on each turn ("which POV?", "which
            # subplot?"). The cycling detector in the response
            # handler is the safety net; this block is the primary
            # prevention.
            qa_log = self._writer_qa_log.get(chapter.id) or []
            if qa_log:
                context['writer_qa_history'] = qa_log[-6:]
            # Per-beat orchestration state. Initialise lazily on the
            # first writer-mode call for this chapter. The model gets
            # a CURRENT BEAT FOCUS block telling it WHICH beat is in
            # play, the round counter, and that questions should be
            # scoped to this beat alone.
            beat_state = self._ensure_beat_state(chapter.id, chapter)
            # First Full Text turn for this chapter? Compute the
            # deterministic audit + surface to the user. No LLM call
            # until they confirm — the engine, not the model, owns
            # which beat is up next.
            if (self._pending_output_mode == "full_text"
                    and beat_state.get("audit_status")
                        == "pending_request"):
                self._init_beat_state_with_audit(
                    chapter.id, chapter, "full_text",
                    state_dict=self._writer_beat_state,
                    preserve_remaining_beats=True)
                self._log_beat_state(
                    "writer", chapter.id, "state_init_audit")
                self._surface_engine_audit(
                    chapter.id, "full_text")
                self._pending_chat_message = ""
                return
            # Apply audit confirmation/correction BEFORE building
            # the focus block — the user may have just answered the
            # audit prompt and we need to advance past it.
            if beat_state.get("audit_status") == "pending_user":
                self._apply_audit_user_reply(
                    chapter.id, beat_state, message,
                    state_dict=self._writer_beat_state)
                beat_state = self._writer_beat_state.get(
                    chapter.id) or beat_state
            if beat_state.get("in_progress"):
                cur = self._current_beat(chapter.id)
                if cur is not None:
                    context['writer_current_beat'] = {
                        "index": beat_state["current_idx"],
                        "total": len(beat_state["remaining_beats"]),
                        "rounds_used": beat_state["rounds_for_beat"],
                        "max_rounds": beat_state["max_rounds"],
                        "force_write": beat_state["force_write"],
                        "title": cur.get("text", ""),
                        "stage": cur.get("stage", ""),
                        "description": cur.get("description", ""),
                        "beat_number": beat_state.get(
                            "current_beat_number",
                            beat_state["current_idx"] + 1),
                        "audit_status": beat_state.get(
                            "audit_status", "confirmed"),
                    }
            # Always render the planned-beats list and audit hint
            # for writer mode so the model can do the audit on its
            # first turn.
            planning = getattr(chapter, "planning", None)
            events = (
                list(getattr(planning, "events", []) or [])
                if planning else [])
            if events:
                context['planned_beats'] = [
                    {
                        "beat_number": i + 1,
                        "title": (getattr(ev, "text", "") or "").strip(),
                        "stage": (getattr(ev, "stage", "") or "").strip(),
                        "description":
                            (getattr(ev, "description", "") or "").strip(),
                    }
                    for i, ev in enumerate(events)
                ]

        # Log the beat-state we're about to send to the model so the
        # console can be followed turn-by-turn. Two log lines because
        # writer + outline state live on different dicts.
        if mode == "writer":
            ch_log_id = (
                getattr(self.manuscript_editor
                        .current_chapter_editor.chapter, 'id', None)
                if (hasattr(self, 'manuscript_editor')
                    and self.manuscript_editor
                    and self.manuscript_editor.current_chapter_editor)
                else None)
            if ch_log_id:
                if self._pending_output_mode == "outline":
                    self._log_beat_state(
                        "outline", ch_log_id, "send_to_model")
                else:
                    self._log_beat_state(
                        "writer", ch_log_id, "send_to_model")

        # Start background worker with mode
        self._chat_worker = ChatWorker(message, context, mode)
        self._chat_worker.finished.connect(self._on_chat_response)
        self._chat_worker.error.connect(self._on_chat_error)
        self._chat_worker.start()

    # ── Chapter-focus context helpers ──────────────────────────────────────

    def _compute_chapter_coverage(self, chapter) -> dict:
        """Return a coverage analysis for the chapter's planned events.

        Used by writer mode's pre-write protocol so the agent knows
        which planned plot events are already covered in the existing
        chapter text and which still need to be written. Empty
        chapter → every planned event is "remaining".

        Heuristic match: an event is considered COVERED when the
        chapter text contains either:
          * the event's exact title (case-insensitive), OR
          * 60% or more of the meaningful (≥5 char) words from the
            event's title + description combined.

        Returns:
            ``{"has_content": bool, "word_count": int,
               "planned_events": [...], "covered_events": [...],
               "remaining_events": [...], "summary": str}``
            where each ``*_events`` entry is a dict with ``text``,
            ``description``, ``stage``.
        """
        result = {
            "has_content": False,
            "word_count": 0,
            "planned_events": [],
            "covered_events": [],
            "remaining_events": [],
            "summary": "",
        }
        if chapter is None:
            return result
        content = (getattr(chapter, "content", "") or "").strip()
        result["has_content"] = bool(content)
        result["word_count"] = len(content.split())

        planning = getattr(chapter, "planning", None)
        events = list(getattr(planning, "events", []) or []) if planning else []
        if not events:
            # No planned events at all — fall back to the synopsis as
            # the single "remaining beat" descriptor so the agent has
            # SOMETHING to ask questions about.
            desc = ""
            if planning:
                desc = (getattr(planning, "description", "")
                        or getattr(planning, "outline", "") or "")
            if desc.strip():
                result["remaining_events"].append({
                    "text": "Chapter as a whole",
                    "description": desc.strip()[:300],
                    "stage": "",
                })
            return result

        content_lower = content.lower()
        for ev in events:
            text = getattr(ev, "text", "") or ""
            desc = getattr(ev, "description", "") or ""
            stage = getattr(ev, "stage", "") or ""
            entry = {"text": text, "description": desc, "stage": stage}
            result["planned_events"].append(entry)
            if not content:
                # Empty chapter — everything is remaining
                result["remaining_events"].append(entry)
                continue
            covered = False
            t = text.strip().lower()
            if t and t in content_lower:
                covered = True
            else:
                # Word-overlap heuristic: count meaningful words from
                # title+description that appear in the chapter content
                import re as _re
                meaningful = [
                    w for w in _re.findall(
                        r"\b[a-zA-Z']{5,}\b",
                        f"{text} {desc}".lower())
                    if w not in {"chapter", "scene", "story",
                                  "beat", "event"}
                ]
                if meaningful:
                    hits = sum(1 for w in meaningful
                               if w in content_lower)
                    if hits / len(meaningful) >= 0.6:
                        covered = True
            (result["covered_events"] if covered
             else result["remaining_events"]).append(entry)

        # Build a one-line summary
        n_total = len(result["planned_events"])
        n_left = len(result["remaining_events"])
        n_done = len(result["covered_events"])
        if not result["has_content"]:
            result["summary"] = (
                f"Empty chapter — all {n_total} planned event(s) "
                "need to be written.")
        elif n_left == 0:
            result["summary"] = (
                f"All {n_total} planned event(s) appear to be "
                f"covered in the existing {result['word_count']:,} "
                "words. No remaining beats.")
        else:
            result["summary"] = (
                f"{n_done}/{n_total} planned event(s) covered, "
                f"{n_left} remaining. Existing chapter has "
                f"{result['word_count']:,} words.")
        return result

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

    # Maps the human-readable category labels used by the focused-
    # element block to the entity_type keys used by the knowledge
    # graph. Lets us look up an entity's edges by category without a
    # second name search.
    _FOCUSED_CATEGORY_TO_GRAPH_TYPE = {
        "Character":    "character",
        "Faction":      "faction",
        "Place":        "place",
        "Culture":      "culture",
        "Technology":   "technology",
        "Myth":         "myth",
        "Flora":        "flora",
        "Fauna":        "fauna",
    }

    def _append_graph_connections(
        self,
        parts: list,
        entity_type: str,
        entity_id: str,
        entity_name: str,
    ) -> None:
        """Append a 'Connections:' block listing this entity's graph edges.

        Pulls from the knowledge graph if available so the model can
        see who this entity is allied with / leads / inhabits / is
        romantically tied to — typed relationships that mere prose
        retrieval doesn't surface. No-op when the graph isn't built or
        the entity has no edges.
        """
        rag = getattr(self, "_rag_system", None)
        kg = getattr(rag, "knowledge_graph", None) if rag else None
        if kg is None:
            return
        # Try the (type, id) tuple first; if that misses (e.g. legacy
        # data with no stable ID), fall back to name resolution.
        node = None
        if entity_id and (entity_type, entity_id) in kg.graph:
            node = (entity_type, entity_id)
        elif entity_name:
            node = kg.resolve(entity_name, prefer_type=entity_type)
        if node is None:
            return
        edges = kg.edges_of(node, include_incoming=True)
        if not edges:
            return
        # De-dup edges that point at the same neighbor with the same
        # relation (can happen on parallel-edge multigraphs) and cap
        # at a generous bound — the focused element is a single
        # entity, so a richer neighborhood is acceptable here.
        seen = set()
        rendered = []
        for relation, other, _attrs in edges:
            key = (relation, other)
            if key in seen:
                continue
            seen.add(key)
            other_name = kg.graph.nodes[other].get("name", other[1])
            other_type = kg.graph.nodes[other].get("entity_type", other[0])
            rendered.append(f"  - {relation}: {other_name} ({other_type})")
            if len(rendered) >= 20:
                break
        parts.append("Connections (from knowledge graph):")
        parts.extend(rendered)

    def _graph_edges_inline(
        self,
        entity_type: str,
        entity_id: str,
        max_edges: int = 5,
        include_incoming: bool = False,
    ) -> str:
        """Compact inline edges string for the broad fallback blocks.

        Returns "" when the entity isn't in the graph or has no edges.
        Tighter cap (5) than the focused-element block since these
        annotations are sprinkled across every entry in a roster — the
        cumulative token cost adds up fast.
        """
        rag = getattr(self, "_rag_system", None)
        kg = getattr(rag, "knowledge_graph", None) if rag else None
        if kg is None:
            return ""
        return kg.format_relations_line(
            entity_type, entity_id,
            max_edges=max_edges,
            include_incoming=include_incoming)

    def _find_referenced_element(self, message: str, project) -> str:
        """Check if the user's message mentions a specific element by name.

        If found, return that element's full details as a formatted
        string, including a ``Connections:`` block listing the entity's
        graph edges (allies, leader, controlling faction, social ties,
        love interests, etc.) so the model can reason about typed
        relationships without traversing the project manually.
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
                self._append_graph_connections(
                    parts, "character",
                    getattr(char, 'id', ''), char.name)
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
                    graph_type = self._FOCUSED_CATEGORY_TO_GRAPH_TYPE.get(
                        category)
                    if graph_type:
                        self._append_graph_connections(
                            parts, graph_type,
                            getattr(elem, 'id', ''), name)
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

        # Prose profile (target tone / style / voice / genre) +
        # the resolved GenreProfile bands (sentence-length window,
        # dialog %, passive cap, etc.) so the chat agent can answer
        # pacing/genre questions with concrete numbers instead of
        # vague genre platitudes. Surfaced for ALL modes — the data
        # is small and orthogonal.
        pp = getattr(project, "prose_profile", None)
        if pp:
            profile_dict = {
                "tone":  (pp.tone  or "").strip(),
                "style": (pp.style or "").strip(),
                "voice": (pp.voice or "").strip(),
                "genre": (pp.genre or "").strip(),
                "notes": (pp.notes or "").strip(),
            }
            if any(profile_dict.values()):
                context['prose_profile'] = profile_dict
            try:
                from src.ai.chapter_analysis_agent import (
                    resolve_genre_profile)
                gp = resolve_genre_profile(pp.genre or "")
                # Only emit numeric targets — the text fields above
                # already cover the freeform side.
                context['genre_profile'] = {
                    "key":  gp.key,
                    "name": gp.name,
                    "avg_sentence_target":
                        list(gp.avg_sentence_target),
                    "variety_score_target":
                        gp.variety_score_target,
                    "dialog_pct_target":
                        list(gp.dialog_pct_target),
                    "passive_pct_max":  gp.passive_pct_max,
                    "long_sentence_pct_max":
                        gp.long_sentence_pct_max,
                    "adverb_pct_max":   gp.adverb_pct_max,
                    "notes":            gp.notes,
                }
            except Exception as e:
                print(f"[chat-context] genre profile resolve failed: {e}")

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

        # Project RAG (characters / worldbuilding / chapters / subplots
        # / plot scaffolding) — the AUTHORITATIVE story material.
        # Encyclopedia hits land in a SEPARATE context key so the
        # model can never confuse real-world reference data with the
        # author's actual project plot.
        if user_message and self._rag_initialized:
            rag_tokens = 1500 if mode == "general" else 1000
            rag_context = self._get_rag_context(
                user_message, max_tokens=rag_tokens, project_only=True)
            if rag_context:
                context['rag_context'] = rag_context

            # Reference RAG (encyclopedia) — real-world / mythology
            # grounding. Only fetched for modes where prose-writing
            # or world-discussion benefits from real-world parallels.
            if mode in ("writer", "chapter_focus", "plot", "general"):
                reference = self._get_reference_rag_context(
                    user_message, max_tokens=1000)
                if reference:
                    context['reference_context'] = reference

        # Track whether knowledge base is enabled (for labeling in the prompt)
        try:
            from src.config.ai_config import get_ai_config
            context['kb_enabled'] = get_ai_config().get_settings().get("enable_knowledge_base", True)
        except Exception:
            context['kb_enabled'] = False

        # Backstop project RAG fetch for chapter_focus / writer / plot
        # modes when the broader pass returned nothing.
        if (mode in ("chapter_focus", "writer", "plot")
                and not context.get('rag_context')
                and user_message and self._rag_initialized):
            rag_context = self._get_rag_context(
                user_message, max_tokens=1200, project_only=True)
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
                    ties = self._graph_edges_inline(
                        "character", getattr(char, 'id', ''))
                    if ties:
                        char_info += f"\n  Ties: {ties}"
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
                        faction_lines = []
                        for f in wb.factions[:8]:
                            desc = (f.description[:100]
                                    if hasattr(f, 'description')
                                       and f.description else '')
                            line = f"  - {f.name}: {desc}"
                            ties = self._graph_edges_inline(
                                "faction", getattr(f, 'id', ''))
                            if ties:
                                line += f"  [ties: {ties}]"
                            faction_lines.append(line)
                        wb_parts.append(
                            "Factions:\n" + "\n".join(faction_lines))
                    else:
                        faction_info = [f.name for f in wb.factions[:5]]
                        wb_parts.append(
                            f"Factions: {', '.join(faction_info)}")
                if wb.places:
                    if is_chapter_focused:
                        place_lines = []
                        for p in wb.places[:8]:
                            desc = (p.description[:100]
                                    if hasattr(p, 'description')
                                       and p.description else '')
                            line = f"  - {p.name}: {desc}"
                            ties = self._graph_edges_inline(
                                "place", getattr(p, 'id', ''))
                            if ties:
                                line += f"  [ties: {ties}]"
                            place_lines.append(line)
                        wb_parts.append(
                            "Places:\n" + "\n".join(place_lines))
                    else:
                        place_info = [p.name for p in wb.places[:5]]
                        wb_parts.append(
                            f"Places: {', '.join(place_info)}")
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
                    event_lines = []
                    for e in fp.events[:25]:
                        head = f"  - {e.title}"
                        if getattr(e, 'description', ''):
                            head += f": {e.description[:150]}"
                        ties = self._graph_edges_inline(
                            "plot_event", getattr(e, 'id', ''))
                        if ties:
                            head += f"  [ties: {ties}]"
                        event_lines.append(head)
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
                    # Graph-derived edges (e.g. plot events that fold
                    # into this subplot via related_subplots). The
                    # ``characters`` line above already covers the
                    # outgoing involves-character edges; this picks up
                    # the incoming side and anything else.
                    ties = self._graph_edges_inline(
                        "subplot", getattr(s, 'id', ''),
                        max_edges=6, include_incoming=True)
                    if ties:
                        sub_lines.append(f"      graph: {ties}")
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

            # Story-so-far summary — a digested rundown of every prior
            # chapter so the writer + chapter-focus discussions have
            # continuity beyond just the immediately-previous ending.
            # Built only for modes that actually need it (writer +
            # chapter_focus + plot) since it's not free to assemble.
            if (mode in ("writer", "chapter_focus", "plot")
                    and hasattr(self, 'manuscript_editor')
                    and self.manuscript_editor.current_chapter_editor):
                open_id = (
                    self.manuscript_editor
                        .current_chapter_editor.chapter.id)
                summary_lines = []
                for ch in all_chapters:
                    if ch.id == open_id:
                        break
                    # Prefer the planner's description (author intent);
                    # fall back to the first sentence of content as a
                    # last-resort heuristic so an unplanned chapter
                    # still appears in the rundown.
                    summary = ""
                    if (hasattr(ch, 'planning')
                            and ch.planning
                            and ch.planning.description):
                        summary = ch.planning.description.strip()
                    elif ch.content:
                        first = ch.content.strip().split('\n\n', 1)[0]
                        summary = first[:200].strip()
                    if summary:
                        summary_lines.append(
                            f"Ch {ch.number} — {ch.title}: {summary}")
                    else:
                        summary_lines.append(
                            f"Ch {ch.number} — {ch.title}: "
                            f"(no synopsis recorded)")
                if summary_lines:
                    context['previous_chapters_summary'] = (
                        "\n".join(summary_lines))

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
        # Find any plot events the user named (or close to it) in
        # their question — the user-block builder renders these as
        # a high-priority "REFERENCED EVENTS" block at the top of
        # the prompt so the model knows exactly which events to
        # build a chapter around.
        if question:
            try:
                from src.ui.plot.plot_manager import (
                    _find_referenced_events,
                )
                refs = _find_referenced_events(
                    question, self.current_project)
                if refs:
                    lines = []
                    for r in refs:
                        ev = r['event']
                        score = r.get('score', 0)
                        source = r.get('source', '')
                        title = (getattr(ev, 'title', '')
                                 or '(untitled)')
                        stage = (getattr(ev, 'stage', '')
                                 or '?')
                        act = getattr(ev, 'act', None)
                        intensity = getattr(ev, 'intensity', None)
                        chars = (getattr(
                            ev, 'related_characters', [])
                                 or [])
                        desc = (getattr(ev, 'description', '')
                                or '').strip()
                        head = f"  - {title}"
                        if score < 1.0:
                            head += (
                                f"  [fuzzy match {score:.2f}]")
                        meta = []
                        if act:
                            meta.append(f"act {act}")
                        if stage and stage != '?':
                            meta.append(stage)
                        if intensity is not None:
                            meta.append(f"intensity {intensity}")
                        if source.startswith('subplot:'):
                            meta.append(
                                f"in subplot: "
                                f"{source.split(':', 1)[1]}")
                        if meta:
                            head += f"  ({', '.join(meta)})"
                        lines.append(head)
                        if chars:
                            lines.append(
                                f"      characters: "
                                f"{', '.join(str(c) for c in chars)}")
                        if desc:
                            lines.append(
                                f"      description: "
                                f"{desc[:240]}")
                    base['referenced_events'] = "\n".join(lines)
            except Exception as e:
                print(f"[plot-ai] reference matching failed: {e}")
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
            # First: detect <edit_last_insertion> tags. These take
            # priority over write tool tags because the user is
            # asking to revise existing prose, not start something new.
            edit_calls = extract_edit_calls(response)
            if edit_calls:
                cleaned = strip_edit_calls(response)
                self.chat_widget.add_message(
                    "Assistant",
                    cleaned or "(editing your last insertion…)",
                    system_prompt=system_prompt,
                    original_response=response,
                )
                pending_msg = getattr(self, '_pending_chat_message', '')
                if pending_msg:
                    self._chat_history.append(
                        {"role": "user", "content": pending_msg})
                    self._chat_history.append(
                        {"role": "assistant", "content": cleaned})
                    self._compact_chat_history()
                self._pending_chat_message = ""
                self._dispatch_edit_insertion(edit_calls[0])
                return

            # Then: detect long-form writing tool tags (chapter_focus mode).
            # When the model emitted one, strip it from the visible message
            # and dispatch to the long-form writer engine.
            write_calls = extract_write_tool_calls(response)
            if write_calls:
                # Show the conversational part (with the XML stripped)
                cleaned = strip_write_tool_calls(response)
                self.chat_widget.add_message(
                    "Assistant",
                    cleaned or "(starting long-form writing…)",
                    system_prompt=system_prompt,
                    original_response=response,
                )
                pending_msg = getattr(self, '_pending_chat_message', '')
                if pending_msg:
                    self._chat_history.append(
                        {"role": "user", "content": pending_msg})
                    self._chat_history.append(
                        {"role": "assistant", "content": cleaned})
                    self._compact_chat_history()
                self._pending_chat_message = ""
                # Only honour the FIRST tool call in a reply (stack of
                # writes in one turn would interleave editor mutations).
                self._dispatch_long_form_writing(write_calls[0])
                return

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

    @staticmethod
    def _split_writer_response(response: str) -> tuple:
        """Separate the prose from the trailing <writing_summary> block.

        Writer mode now requires the model to emit a structured summary
        of which plot events it covered. We strip the summary tag from
        the prose that lands in the editor and surface the summary
        text in the chat as confirmation.

        Also strips model-specific channel / chat-format tokens that
        sometimes leak through from local models (Harmony, ChatML,
        Llama 3, Mistral [INST], thinking-block wrappers). Without
        the strip, a leaky local-model run dumps
        ``<|channel|>thought<|channel|>`` spam into the editor.

        Returns ``(prose, summary_text)`` — ``summary_text`` is empty
        when the model didn't emit a tag (older prompt + back-compat).
        """
        import re as _re
        from src.ai.output_sanitizer import strip_meta_tokens
        if not response:
            return "", ""
        m = _re.search(
            r"<writing_summary>\s*(.*?)\s*</writing_summary>",
            response,
            _re.DOTALL | _re.IGNORECASE,
        )
        if not m:
            return strip_meta_tokens(response), ""
        summary = strip_meta_tokens(m.group(1))
        # Drop the summary tag (and any whitespace around it) from
        # the prose. Tolerate the model emitting multiple tags by
        # stripping all occurrences.
        prose = _re.sub(
            r"\s*<writing_summary>.*?</writing_summary>\s*",
            "\n\n",
            response,
            flags=_re.DOTALL | _re.IGNORECASE,
        )
        prose = strip_meta_tokens(prose)
        return prose, summary

    # ── Writer-insertion registry ────────────────────────────────────

    def _record_writer_insertion(
        self,
        chapter_id: str,
        start: int,
        end: int,
        prose: str,
        prompt: str,
        mode: str,
        summary: str = "",
    ):
        """Append a record of an AI insertion to the per-chapter registry.

        The registry is the source of truth for "edit that scene you
        just wrote" follow-ups. Each record carries the byte range +
        the prose + the user prompt + a brief summary so the chat
        layer can surface recent insertions and the edit tool can
        target the exact text with original context.
        """
        if not chapter_id or not (prose or "").strip():
            return
        from datetime import datetime
        bucket = self._writer_insertions.setdefault(chapter_id, [])
        bucket.append({
            "id": datetime.now().strftime("%H%M%S%f")[:-3],
            "start": int(start),
            "end": int(end),
            "prose": prose,
            "prompt": prompt or "",
            "mode": mode,
            "summary": summary or "",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        # Cap the bucket so a long session doesn't accumulate every
        # insertion. The most-recent N are what the user can refer
        # back to in conversation; older insertions live only in the
        # editor itself.
        if len(bucket) > self._MAX_INSERTIONS_PER_CHAPTER:
            del bucket[:len(bucket) - self._MAX_INSERTIONS_PER_CHAPTER]

    def _shift_insertions(
        self,
        chapter_id: str,
        from_pos: int,
        delta: int,
    ):
        """Adjust insertion ranges after the editor's text shifts.

        Called when an insertion is replaced with new prose of a
        different length, OR when the user manually edits text before
        an existing recorded insertion. ``delta`` is the signed
        change in length (new_len - old_len).
        """
        if not chapter_id or not delta:
            return
        for rec in self._writer_insertions.get(chapter_id, []):
            if rec["start"] >= from_pos:
                rec["start"] += delta
                rec["end"] += delta

    def _get_recent_insertions(
        self,
        chapter_id: str,
        limit: int = 3,
    ) -> list:
        """Return the most-recent ``limit`` insertions for a chapter."""
        return list(
            (self._writer_insertions.get(chapter_id) or [])[-limit:])

    # ── Writer Q&A registry (Phase-1 cycle prevention) ───────────────

    @staticmethod
    def _extract_questions_from_response(text: str) -> List[str]:
        """Pull question-shaped lines out of a model response.

        Heuristic: a question is a line that ends with '?'. Lines are
        normalised (lower-cased, punctuation collapsed) by callers
        when matching for duplicates. Returns the raw question
        strings in the order they appeared.
        """
        if not text:
            return []
        import re as _re
        # Split into lines/sentences and keep ones ending with '?'.
        # Models often put numbered list markers like "1. ..." or
        # "- ..." in front; strip those when extracting.
        candidates = _re.split(r"[\n]+|(?<=[\?\!\.])\s+", text)
        out = []
        for c in candidates:
            s = c.strip()
            if not s or not s.endswith("?"):
                continue
            # Strip leading list-marker noise
            s = _re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", s).strip()
            if len(s) < 6:
                continue
            out.append(s)
        return out

    # Stop-words filtered out during question normalisation so
    # semantically identical phrasings ("X be Y" vs "X as Y") score
    # as duplicates instead of slipping past the cycling detector.
    _QUESTION_STOPWORDS = frozenset({
        "a", "an", "the", "and", "or", "but", "if", "then",
        "of", "to", "in", "on", "at", "for", "with", "by", "from",
        "as", "like", "into", "onto", "over", "under",
        "be", "is", "am", "are", "was", "were", "been", "being",
        "have", "has", "had", "do", "does", "did", "done",
        "will", "would", "shall", "should", "may", "might",
        "can", "could", "must", "ought",
        "i", "we", "you", "he", "she", "they", "it", "this",
        "that", "these", "those", "my", "your", "his", "her",
        "our", "their", "its",
        "not", "no", "yes",
    })

    @classmethod
    def _normalise_question(cls, q: str) -> str:
        """Normalise a question for duplicate-matching.

        Lower-cases, drops punctuation, drops question-stems
        (Would you like / Should the / etc.), AND drops stop-words.
        Two semantically identical asks normalise to the same
        token set even when the model rephrases — the cycling
        detector relies on this for accurate duplicate counts.
        """
        import re as _re
        s = q.lower().strip()
        # Drop common question-stems
        s = _re.sub(
            r"^(should|could|would|will|do|does|did|is|are|was|were|"
            r"can|may)\s+(you|i|we|the|this|that|it|she|he|they)\s+",
            "", s)
        s = _re.sub(
            r"^(would you like|do you want|would you prefer|"
            r"how would you|how should|what about|what's your)\s+",
            "", s)
        # Collapse whitespace + drop punctuation
        s = _re.sub(r"[^\w\s]", "", s)
        s = _re.sub(r"\s+", " ", s).strip()
        # Drop stop-words for semantic comparison
        words = [w for w in s.split() if w not in cls._QUESTION_STOPWORDS]
        return " ".join(words)

    def _record_writer_qa(
        self,
        chapter_id: str,
        user_message: str,
        assistant_response: str,
    ):
        """Append a Q&A turn to the chapter's writer-mode log.

        Each entry is ``{"user": ..., "assistant": ...,
        "questions": [normalised question strings]}``. Used by the
        cycling detector and the PRIOR Q&A context block.
        """
        if not chapter_id:
            return
        questions_raw = self._extract_questions_from_response(
            assistant_response or "")
        questions_norm = [self._normalise_question(q)
                          for q in questions_raw]
        bucket = self._writer_qa_log.setdefault(chapter_id, [])
        bucket.append({
            "user": (user_message or "").strip(),
            "assistant": (assistant_response or "").strip(),
            "questions": questions_raw,
            "questions_norm": questions_norm,
        })
        # Cap the log at 10 turns so a long Phase-1 doesn't grow
        # unbounded — the PRIOR Q&A block surfaces only the last few
        # turns anyway.
        if len(bucket) > 10:
            del bucket[:len(bucket) - 10]

    def _detect_question_cycling(
        self,
        chapter_id: str,
        new_response: str,
        threshold: float = 0.6,
    ) -> bool:
        """True when ≥``threshold`` of the new response's questions
        match questions the model already asked in this chapter's
        Phase-1 log. Signal that the model is cycling and we should
        force the ready state + proceed to writing.

        Default 0.6 — when 2 of 3 (or 3 of 5) questions repeat, the
        model is functionally stuck. Higher thresholds let the cycle
        run another round; lower thresholds risk false positives
        when the model genuinely has only one new question among
        several follow-ups.
        """
        bucket = self._writer_qa_log.get(chapter_id) or []
        if not bucket:
            return False
        # Collect all prior normalised questions
        prior_norm = set()
        for entry in bucket:
            prior_norm.update(entry.get("questions_norm") or [])
        if not prior_norm:
            return False
        new_questions = self._extract_questions_from_response(
            new_response or "")
        if not new_questions:
            return False
        new_norm = [self._normalise_question(q) for q in new_questions]
        # Count how many of the new questions appear in the prior set.
        # Simple substring match across normalised text catches
        # near-duplicates (e.g. "should marcus break first" vs
        # "marcus break first or accept first").
        repeats = 0
        for n in new_norm:
            if not n:
                continue
            for p in prior_norm:
                if (n in p or p in n
                        or self._jaccard_words(n, p) >= 0.6):
                    repeats += 1
                    break
        ratio = repeats / len(new_norm)
        return ratio >= threshold

    @staticmethod
    def _jaccard_words(a: str, b: str) -> float:
        """Word-level Jaccard similarity between two normalised strings."""
        sa = set(a.split())
        sb = set(b.split())
        if not sa or not sb:
            return 0.0
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union else 0.0

    # ── Per-beat orchestration helpers ────────────────────────────

    def _ensure_beat_state(self, chapter_id: str, chapter) -> dict:
        """Initialise the per-beat state for a chapter if absent.

        State is computed lazily from the coverage analysis. When
        the chapter has no remaining beats, returns a state with
        ``in_progress=False`` so the response handler skips the
        per-beat orchestration and behaves as a normal writer call.

        Audit fields seed at ``pending_request`` so the model's
        first turn is a phase=audit response — the engine surfaces
        that to the user for confirmation before per-beat
        orchestration starts at the first PENDING beat (not Beat 1).
        """
        existing = self._writer_beat_state.get(chapter_id)
        if existing is not None:
            return existing
        coverage = self._compute_chapter_coverage(chapter)
        remaining = list(coverage.get("remaining_events") or [])
        # current_idx = index INTO the remaining_beats list. The
        # ENGINE owns this number; the model can't override it via
        # its JSON beat_number field.
        state = {
            "remaining_beats": remaining,
            "current_idx": 0,
            "current_beat_number": 1,  # 1-based; updated post-audit
            "rounds_for_beat": 0,
            "max_rounds": self._WRITER_MAX_ROUNDS_PER_BEAT,
            "force_write": False,
            "in_progress": bool(remaining),
            "completed": [],
            "audit_status": "pending_request",
            "audit": None,
        }
        self._writer_beat_state[chapter_id] = state
        return state

    def _current_beat(self, chapter_id: str) -> Optional[dict]:
        """Return the current beat dict for a chapter, or None."""
        state = self._writer_beat_state.get(chapter_id)
        if not state or not state.get("in_progress"):
            return None
        idx = state["current_idx"]
        beats = state.get("remaining_beats") or []
        if 0 <= idx < len(beats):
            return beats[idx]
        return None

    def _advance_beat(self, chapter_id: str) -> Optional[dict]:
        """Move to the next beat. Returns the new current beat or None.

        When the queue is exhausted the state's ``in_progress`` flag
        flips to False so subsequent writer calls fall back to the
        unscoped behaviour (or the user can re-invoke for a fresh
        session — coverage will be recomputed).
        """
        state = self._writer_beat_state.get(chapter_id)
        if not state:
            return None
        state["current_idx"] += 1
        state["rounds_for_beat"] = 0
        state["force_write"] = False
        # Clear ready flag so the next beat starts fresh in Phase 1
        # (each beat gets its own Q&A round-set).
        self._writer_ready_chapters.discard(chapter_id)
        beats = state.get("remaining_beats") or []
        if state["current_idx"] >= len(beats):
            state["in_progress"] = False
            return None
        return beats[state["current_idx"]]

    def _reset_beat_state(self, chapter_id: str):
        """Wipe per-beat state for a chapter (e.g. user starts over)."""
        self._writer_beat_state.pop(chapter_id, None)
        self._writer_ready_chapters.discard(chapter_id)

    @staticmethod
    def _looks_like_proceed_signal(text: str) -> bool:
        """True when the user's message reads like 'proceed / go ahead'."""
        if not text:
            return False
        s = text.strip().lower()
        if len(s) > 60:
            return False  # too long to be just a signal
        triggers = (
            "proceed", "go ahead", "looks good", "ok proceed",
            "ok go", "go for it", "ship it", "write it",
            "do it", "let's go", "lets go", "sounds good",
            "approved", "looks fine", "you have enough",
            "you have what you need", "yes proceed", "fine, proceed",
            "no further questions", "no more questions", "good to go",
        )
        for t in triggers:
            if t in s:
                return True
        return False

    def _handle_writer_response(self, response: str):
        """Handle AI response in writer mode - insert into editor.

        Splits the response into prose (lands in the editor) and the
        ``<writing_summary>`` block (surfaces in the chat as a coverage
        confirmation so the author can see at a glance which plot
        events the model claims to have covered).
        """
        insert_mode = getattr(self, '_pending_insert_mode', 'insert_at_cursor')

        # Get the current chapter editor
        if not hasattr(self, 'manuscript_editor') or not self.manuscript_editor.current_chapter_editor:
            self.chat_widget.add_message("Assistant", "No chapter is open. Please select a chapter first.")
            return

        editor = self.manuscript_editor.current_chapter_editor.editor
        chapter_id = self.manuscript_editor.current_chapter_editor.chapter.id
        # Run the project-element creation parser FIRST so the writer
        # can emit <create_character>/<create_place>/<create_faction>/
        # etc. mid-prose to add new project elements as it discovers
        # the need for them. The parser strips the create blocks from
        # the response and returns the cleaned text we use for the
        # rest of the writer flow (Phase-1 routing + prose insertion).
        # Surface created element names in chat + refresh the relevant
        # UI tabs so the user sees the additions immediately.
        try:
            cleaned_for_creates, created_elements = (
                self._parse_and_create_elements(response))
            response = cleaned_for_creates
            if created_elements:
                names = ", ".join(
                    f"{kind}: {name}"
                    for kind, name in created_elements)
                self.chat_widget.add_message(
                    "Assistant",
                    f"(Created from writer mode → {names})")
                self._refresh_project_widgets()
        except Exception as e:
            print(f"[writer] create-parser failed: {e}")
        # Detect the agent's <context_ready/> handshake. When seen,
        # mark this chapter as past the pre-write phase so subsequent
        # turns can write straight through without re-running the
        # coverage / Q&A protocol. The tag is stripped from the
        # response before it reaches the prose extractor.
        import re as _re
        ready_re = _re.compile(
            r"<context_ready\s*/?>", _re.IGNORECASE)
        if ready_re.search(response or ""):
            self._writer_ready_chapters.add(chapter_id)
            response = ready_re.sub("", response)
        # Degeneration guard — when the raw model output is mostly
        # meta-token spam (Harmony / ChatML / etc. leakage from a
        # mis-configured local model), surface a clear error in the
        # chat instead of inserting whatever residual the sanitiser
        # leaves into the manuscript.
        from src.ai.output_sanitizer import (
            is_degenerate_output, strip_meta_tokens)
        if is_degenerate_output(response):
            self.chat_widget.add_message(
                "Assistant",
                "Writer aborted — the model returned mostly "
                "internal channel / format tokens (e.g. "
                "`<|channel|>thought`) instead of prose. This usually "
                "means the local model's chat template doesn't match "
                "its training format. Try switching models, "
                "disabling the agentic-lookup loop, or shortening the "
                "prompt. Nothing was inserted into the chapter.")
            return

        # PRE-WRITE PHASE GATE: if the agent has NOT (in this turn or
        # earlier ones) signalled <context_ready/> for this chapter,
        # treat the response as Phase-1 output (coverage + lookups +
        # questions) and surface it ENTIRELY in the chat — no editor
        # insertion. The user answers in chat; the next turn either
        # asks more or emits <context_ready/> and writes.
        is_ready = chapter_id in self._writer_ready_chapters
        # Determine output mode now so the per-beat-state selector
        # below picks the right state dict (writer vs outline).
        output_mode = getattr(
            self, "_pending_output_mode", "full_text") or "full_text"

        # JSON-FIRST ROUTING. Both Outline and Full Text writer
        # replies are required to be a single structured JSON
        # object with an explicit ``phase`` field. The phase is
        # authoritative — ``questions`` ALWAYS lands in chat (even
        # if the ready flag is set), the deliverable phase
        # (``beat`` for outline, ``prose`` for full text) ALWAYS
        # lands in the panel/editor (even if the ready flag is
        # unset). Falls through to the legacy markdown path when
        # no JSON is present (kept for older models /
        # backward-compat).
        if output_mode == "outline":
            parsed = self._parse_outline_json_response(response)
            if parsed is not None:
                phase = parsed.get("phase")
                if phase == "start_suggestion":
                    self._handle_outline_json_start_suggestion(
                        chapter_id, parsed)
                    return
                if phase == "audit":
                    self._handle_outline_json_audit(
                        chapter_id, parsed)
                    return
                if phase == "questions":
                    self._handle_outline_json_questions(
                        chapter_id, parsed)
                    return
                if phase == "beat":
                    # Focused-beat session takes precedence: the
                    # ✨ button on a beat card pinned this beat as
                    # the destination, so write the JSON straight
                    # into its body instead of going through the
                    # whole-outline staging/apply chain.
                    if self._focused_beat_ai.get(chapter_id):
                        if self._handle_focused_beat_response(
                                chapter_id, parsed):
                            return
                        # If the focused-beat application failed
                        # (beat index now out of range, etc.) we
                        # fall through to the normal staging path
                        # so the AI's work isn't dropped.
                    self._handle_outline_json_beat_staging(
                        chapter_id, parsed)
                    return
        else:
            # Full Text writer mode: try JSON first, fall through
            # to the legacy markdown writer flow when not present.
            parsed = self._parse_writer_json_response(response)
            if parsed is not None:
                phase = parsed.get("phase")
                if phase == "audit":
                    self._handle_writer_json_audit(
                        chapter_id, parsed)
                    return
                if phase == "questions":
                    self._handle_writer_json_questions(
                        chapter_id, parsed)
                    return
                if phase == "prose":
                    self._handle_writer_json_prose(
                        chapter_id, parsed)
                    return
        # Pull per-beat state. In OUTLINE mode the per-beat state
        # lives on _outline_beat_state (one beat = one outline
        # block); in FULL TEXT mode it lives on _writer_beat_state
        # (one beat = one chunk of prose). Either way the Phase-1
        # round counter + cap behave the same.
        if output_mode == "outline":
            beat_state = (
                self._outline_beat_state.get(chapter_id) or {})
        else:
            beat_state = (
                self._writer_beat_state.get(chapter_id) or {})
        per_beat_active = bool(beat_state.get("in_progress"))
        if not is_ready:
            display = strip_meta_tokens(response).strip()
            pending_msg = getattr(self, "_pending_chat_message", "") or ""
            # Round-cap check first — if we've already burned 4 rounds
            # on this beat, force the write next turn instead of
            # asking again. Defensive per-beat reset before the bump
            # so the counter doesn't carry over from a prior beat
            # (which would let the cap fire after only 2-3 beats).
            if per_beat_active:
                cur_beat_no_for_counter = (
                    beat_state.get("current_beat_number")
                    or (beat_state.get("current_idx", 0) + 1))
                last_counter_beat = beat_state.get(
                    "_round_counter_beat_no")
                if last_counter_beat != cur_beat_no_for_counter:
                    beat_state["rounds_for_beat"] = 0
                    beat_state["_round_counter_beat_no"] = (
                        cur_beat_no_for_counter)
                beat_state["rounds_for_beat"] += 1
                rounds = beat_state["rounds_for_beat"]
                cap = beat_state["max_rounds"]
                cur_beat = self._current_beat(chapter_id) or {}
                cur_title = cur_beat.get("text", "(unnamed beat)")
                if rounds >= cap:
                    # Hit the cap. Auto-flip ready so the next user
                    # message triggers the write for this beat.
                    self._writer_ready_chapters.add(chapter_id)
                    beat_state["force_write"] = True
                    self.chat_widget.add_message(
                        "Assistant",
                        f"Round {rounds}/{cap} reached for beat "
                        f"\"{cur_title}\". Send your next message "
                        f"and I'll write this beat with the "
                        f"context we already have.")
                    self._record_writer_qa(
                        chapter_id, pending_msg, display)
                    if pending_msg:
                        self._chat_history.append(
                            {"role": "user", "content": pending_msg})
                        self._chat_history.append(
                            {"role": "assistant", "content":
                                f"(Beat round cap — proceeding to "
                                f"write \"{cur_title}\".)"})
                        self._compact_chat_history()
                    self._pending_chat_message = ""
                    return
            # Cycling detector — same as before but also flips
            # force_write so the next call writes the current beat.
            if display and self._detect_question_cycling(
                    chapter_id, display):
                self._writer_ready_chapters.add(chapter_id)
                if per_beat_active:
                    beat_state["force_write"] = True
                    cur_beat = self._current_beat(chapter_id) or {}
                    cur_title = cur_beat.get("text", "this beat")
                    cycle_msg = (
                        f"Model is cycling on the same questions for "
                        f"\"{cur_title}\" — proceeding to write the "
                        f"beat. Send your next message and I'll draft "
                        f"it with the context we have.")
                else:
                    cycle_msg = (
                        "Model is cycling on the same questions — "
                        "auto-marking this chapter as ready. Send your "
                        "next message to write straight through. (You "
                        "can refine after with `<edit_last_insertion>` "
                        "follow-ups.)")
                self.chat_widget.add_message("Assistant", cycle_msg)
                self._record_writer_qa(
                    chapter_id, pending_msg, display)
                if pending_msg:
                    self._chat_history.append(
                        {"role": "user", "content": pending_msg})
                    self._chat_history.append(
                        {"role": "assistant", "content":
                            "(Cycled questions — auto-proceeding.)"})
                    self._compact_chat_history()
                self._pending_chat_message = ""
                return
            if display:
                if per_beat_active:
                    cur_beat = self._current_beat(chapter_id) or {}
                    cur_title = cur_beat.get("text", "current beat")
                    rounds = beat_state["rounds_for_beat"]
                    cap = beat_state["max_rounds"]
                    footer = (
                        f"\n\n*(Beat \"{cur_title}\" — round "
                        f"{rounds}/{cap}. Answer to refine, or say "
                        f"`proceed` to write this beat now.)*")
                else:
                    footer = (
                        "\n\n*(Pre-write phase — answer the questions "
                        "above and I'll proceed to write the remaining "
                        "beats. Say `proceed` or `looks good` to skip "
                        "further questions.)*")
                self.chat_widget.add_message(
                    "Assistant", display + footer)
            else:
                self.chat_widget.add_message(
                    "Assistant",
                    "(Pre-write phase — model returned no questions. "
                    "Reply `proceed` to write straight through.)")
            # Record this Q&A turn so future turns can see what was
            # already asked + so the cycling detector has a baseline.
            self._record_writer_qa(chapter_id, pending_msg, display)
            # Append to chat history so the model's next call has
            # the full multi-turn context (the original bug was
            # writer-mode history was forced to []).
            if pending_msg:
                self._chat_history.append(
                    {"role": "user", "content": pending_msg})
                self._chat_history.append(
                    {"role": "assistant", "content": display})
                self._compact_chat_history()
            self._pending_chat_message = ""
            return

        prose, summary = self._split_writer_response(response)
        word_count = len(prose.split())

        # OUTLINE OUTPUT MODE — Phase 2 deliverable is a structured
        # outline that lands in the AI Assistant's outline panel,
        # NOT in the chapter editor. The panel writes back to
        # chapter.planning.outline via its outline_changed signal,
        # so the outline still persists with the project. (output_mode
        # was determined earlier so the Phase-1 path could pick the
        # right per-beat state dict.)
        if output_mode == "outline":
            panel = getattr(self.chat_widget, "outline_panel", None)
            outline_action = getattr(
                self, "_pending_outline_action", "populate")
            if panel is None:
                self.chat_widget.add_message(
                    "Assistant",
                    "Outline panel is unavailable — outline output "
                    "could not be routed.")
                self._pending_chat_message = ""
                return

            import re as _re
            # Detect <outline_complete/> sentinel anywhere in the
            # response; strip it before further processing.
            complete_re = _re.compile(
                r"<outline_complete\s*/?>", _re.IGNORECASE)
            outline_complete_signaled = bool(
                complete_re.search(prose or ""))
            outline_text = complete_re.sub("", prose or "").strip()

            ob_state = self._outline_beat_state.get(chapter_id) or {}

            if not outline_text and not outline_complete_signaled:
                self.chat_widget.add_message(
                    "Assistant",
                    "(Model returned no outline content — try again "
                    "or rephrase the prompt.)")
                self._pending_chat_message = ""
                return

            # NORMALIZE the response so it always lands in the panel
            # as ONE structured beat — even when the model deviates
            # from the strict ``## [ ] Beat N: …`` template. Three
            # tiers of recovery so the user never sees a blunt
            # rejection while the panel sits empty:
            #
            #   T1 STRICT  — already in expected form. Use as-is.
            #   T2 NORMALIZE — model used ``###``, ``**Beat 1**``,
            #                  ``# Beat 1`` etc. Rewrite the first
            #                  heading-like line into ``## [ ] …``
            #                  and treat the rest as the body.
            #   T3 WRAP     — no heading-like line at all (pure
            #                  prose, bullets, or chatty preamble).
            #                  Wrap the whole response as a
            #                  synthetic ``## [ ] Beat <N>: …`` so
            #                  it lands in the panel; the user can
            #                  edit the heading or retry.
            outline_text, normalize_note = self._normalize_outline_response(
                outline_text,
                next_beat_number=(
                    ob_state.get("beats_done", 0) + 1
                    if ob_state else 1))
            if normalize_note:
                self.chat_widget.add_message(
                    "Assistant", normalize_note)

            # SAFETY CAP: even after normalization, a stubborn model
            # may still pack two beats into one reply. Truncate to
            # the first beat so each turn only adds one card.
            heading_re = _re.compile(
                r"^##\s+(?:\[[ xX]\]\s+)?\S",
                _re.MULTILINE)
            if outline_text:
                headings = list(heading_re.finditer(outline_text))
                if len(headings) > 1:
                    second_start = headings[1].start()
                    outline_text = outline_text[:second_start].rstrip()
                    self.chat_widget.add_message(
                        "Assistant",
                        f"(Model emitted {len(headings)} beats in "
                        f"one reply — keeping only the first; the "
                        f"others will be regenerated on subsequent "
                        f"turns.)")

            # Make sure the panel is bound to THIS chapter before
            # we write — covers the edge case where the user
            # switched chapters mid-roundtrip.
            if panel.current_chapter_id() != chapter_id:
                ce = self.manuscript_editor.current_chapter_editor
                title = getattr(ce.chapter, "title", "") or ""
                panel.load_chapter(
                    chapter_id, title,
                    panel.get_outline_text())

            # Decide whether this Phase-2 reply gets APPENDED (per-beat
            # populate) or REPLACES the panel (legacy whole-outline /
            # explicit replace). Per-beat append preserves prior beats
            # and lets the model produce one beat at a time.
            beats_added = 0
            if outline_text:
                if outline_action == "replace":
                    panel.set_outline_text(outline_text)
                    beats_added = len(
                        _collect_beat_titles(outline_text))
                else:
                    # populate (per-beat) and edit both append. Edit
                    # mode is documented to emit one refined beat at
                    # a time.
                    panel.append_outline_text(outline_text)
                    beats_added = len(
                        _collect_beat_titles(outline_text))

            # Switch the sidebar to the Outline tab so the user sees
            # the new content right away.
            tabs = getattr(self, "sidebar_tabs", None)
            if tabs is not None:
                idx = tabs.indexOf(panel)
                if idx >= 0:
                    tabs.setCurrentIndex(idx)

            # Update per-chapter outline state. Reset the round
            # counter for the NEXT beat, bump beats_done, and mark
            # complete when the sentinel fired.
            if ob_state:
                ob_state["beats_done"] = (
                    ob_state.get("beats_done", 0) + beats_added)
                ob_state["rounds_for_beat"] = 0
                if outline_complete_signaled:
                    ob_state["complete"] = True
                if (ob_state["beats_done"]
                        >= self._OUTLINE_MAX_BEATS):
                    ob_state["complete"] = True
                self._outline_beat_state[chapter_id] = ob_state

            # Compose the chat confirmation message.
            verb = ("Refined" if outline_action == "edit"
                    else "Replaced" if outline_action == "replace"
                    else "Beat added to")
            beats_done_now = (ob_state.get("beats_done", beats_added)
                              if ob_state else beats_added)
            if outline_complete_signaled:
                confirm = (
                    f"Outline complete — {beats_done_now} beats in "
                    f"the Outline tab. Switch the AI Assistant back "
                    f"to Full Text and ask me to write the chapter; "
                    f"I'll do it beat by beat using this outline.")
            elif outline_action == "populate":
                confirm = (
                    f"Beat {beats_done_now} added to the Outline tab. "
                    f"Send a follow-up to refine, or send the next "
                    f"message to continue with Beat "
                    f"{beats_done_now + 1}.")
            else:
                confirm = (
                    f"Done — {verb.lower()} the chapter outline in "
                    f"the Outline tab "
                    f"({len(outline_text.split()):,} words).")
            if summary:
                confirm += "\n\n" + summary
            self.chat_widget.add_message("Assistant", confirm)

            # Chat-history bookkeeping. Don't dump the whole beat
            # body into history — keep a short marker so the model's
            # next call sees a tight summary instead of every prior
            # beat's full structure.
            pending_msg = getattr(
                self, "_pending_chat_message", "") or ""
            if pending_msg:
                marker = (
                    "(Outline complete.)"
                    if outline_complete_signaled
                    else f"(Beat {beats_done_now} added to outline.)")
                self._chat_history.append(
                    {"role": "user", "content": pending_msg})
                self._chat_history.append(
                    {"role": "assistant", "content": marker})
                self._compact_chat_history()

            # Reset for next turn. Outline-action stays as-is until
            # the user starts a new run; populate is the default and
            # also what the per-beat loop uses.
            self._pending_outline_action = (
                "populate" if outline_action != "edit" else "edit")
            self._pending_chat_message = ""
            # Reset the ready flag so the NEXT beat starts in
            # Phase 1 again — each beat gets its own optional
            # round of clarifying questions.
            self._writer_ready_chapters.discard(chapter_id)
            return

        try:
            # Track the editor's pre-insert state so we can record
            # the exact byte range the new prose occupies AFTER it
            # lands. Capturing both the start position + the cursor
            # position immediately after the insert gives us a stable
            # range for the registry.
            pre_cursor = editor.textCursor()
            ins_start = pre_cursor.position()
            if insert_mode == 'replace_selection':
                # Replace selected text
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    ins_start = min(cursor.selectionStart(),
                                     cursor.selectionEnd())
                    cursor.insertText(prose)
                    action = "replaced selection"
                else:
                    # Fallback to insert at cursor if no selection
                    cursor.insertText(prose)
                    action = "inserted at cursor"

            elif insert_mode == 'insert_at_cursor':
                # Insert at current cursor position
                cursor = editor.textCursor()
                ins_start = cursor.position()
                cursor.insertText(prose)
                action = "inserted at cursor"

            elif insert_mode == 'append_to_chapter':
                # Append to end of chapter
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                # Add spacing before appending
                current_text = editor.toPlainText()
                if current_text and not current_text.endswith('\n\n'):
                    cursor.insertText('\n\n')
                ins_start = cursor.position()
                cursor.insertText(prose)
                action = "appended to chapter"

            elif insert_mode == 'replace_chapter':
                # Replace entire chapter content
                editor.setPlainText(prose)
                ins_start = 0
                # Land cursor at end so the registry-end calc below
                # uses the right value.
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                editor.setTextCursor(cursor)
                action = "replaced chapter"

            else:
                # Fallback
                cursor = editor.textCursor()
                ins_start = cursor.position()
                cursor.insertText(prose)
                action = "inserted"

            # Record the insertion in the registry. ``end`` is the
            # cursor position AFTER the insert (which sits at the end
            # of the freshly-inserted text). This range lets the
            # ``<edit_last_insertion>`` tool target the prose later.
            ins_end = editor.textCursor().position()
            output_mode = getattr(
                self, "_pending_output_mode", "full_text") or "full_text"
            self._record_writer_insertion(
                chapter_id=chapter_id,
                start=ins_start,
                end=ins_end,
                prose=prose,
                prompt=getattr(self, "_pending_chat_message", "") or "",
                mode=f"writer:{output_mode}:{insert_mode}",
                summary=summary,
            )

            # Show confirmation in chat. When the model emitted a
            # summary block, surface it so the author can audit plot
            # coverage at a glance without scrolling the editor.
            confirm_msg = f"Done — {word_count:,} words {action}."
            if summary:
                confirm_msg += "\n\n" + summary
            else:
                confirm_msg += (
                    "\n\n(No <writing_summary> block in the response — "
                    "ask the model to retry if you want a coverage "
                    "checklist.)")
            # Per-beat advance: when in per-beat mode, this Phase-2
            # write covers the CURRENT beat. Record it as completed
            # and move on. Append a hint to the user about what
            # comes next.
            beat_advance_msg = ""
            if per_beat_active:
                cur_beat = self._current_beat(chapter_id) or {}
                cur_title = cur_beat.get("text", "current beat")
                # Mark this beat completed in the state
                beat_state.setdefault("completed", []).append({
                    "title": cur_title,
                    "prose": prose,
                    "start": ins_start,
                    "end": ins_end,
                })
                next_beat = self._advance_beat(chapter_id)
                if next_beat is not None:
                    beat_advance_msg = (
                        f"\n\n*(Beat \"{cur_title}\" written. Now "
                        f"on beat \"{next_beat.get('text', 'next')}\""
                        + (f" [{next_beat.get('stage', '')}]"
                           if next_beat.get('stage') else "")
                        + " — send your next message and I'll start "
                          "asking questions for it.)*")
                else:
                    beat_advance_msg = (
                        "\n\n*(All planned beats written. Chapter is "
                        "complete from the writer's perspective — "
                        "send a fresh writer request to add more, or "
                        "edit any beat with `<edit_last_insertion>`.)*")
                # Reset chapter Q&A log when advancing — prior Q&A
                # was about the just-completed beat and shouldn't
                # contaminate the next beat's questions.
                self._writer_qa_log.pop(chapter_id, None)

            self.chat_widget.add_message(
                "Assistant", confirm_msg + beat_advance_msg)

            # Append to chat history so subsequent writer turns (e.g.
            # follow-up edits, "now write the next bit") have the
            # multi-turn context they need.
            pending_msg = getattr(self, "_pending_chat_message", "") or ""
            if pending_msg:
                self._chat_history.append(
                    {"role": "user", "content": pending_msg})
                self._chat_history.append(
                    {"role": "assistant", "content":
                        confirm_msg + beat_advance_msg})
                self._compact_chat_history()
            self._pending_chat_message = ""

            # Show status bar notification
            self.statusBar().showMessage(f"Writer: {word_count} words {action}", 5000)

        except Exception as e:
            self.chat_widget.add_message("Assistant", f"Error inserting text: {str(e)}")

    # ── Edit-last-insertion dispatch ──────────────────────────────────

    EDIT_INSERTION_SYSTEM_PROMPT = (
        "You are a fiction editor revising a passage the writer "
        "previously inserted into a chapter. Apply the user's edit "
        "instructions exactly. Match the chapter's existing voice, "
        "tone, POV, and sentence cadence — the surrounding chapter "
        "text is provided so you can stay seamless. Output ONLY the "
        "revised passage as a drop-in replacement for the original "
        "(no labels, no preamble, no metadata, no XML, no commentary)."
    )

    def _dispatch_edit_insertion(self, call: dict):
        """Run an edit pass against a recorded AI insertion.

        ``call['params']`` carries ``index`` (which insertion) +
        ``instructions`` (what to change). The engine fetches the
        original prose by index, builds an edit prompt with the
        surrounding chapter context, runs the LLM, and replaces the
        range in the editor in-place. The registry record is updated
        to point at the new range so a follow-up edit chains
        correctly.
        """
        params = (call or {}).get("params") or {}
        instructions = (params.get("instructions") or "").strip()
        if not instructions:
            self.chat_widget.add_message(
                "Assistant",
                "(edit_last_insertion: missing 'instructions'; "
                "nothing to do).")
            return
        if not (hasattr(self, "manuscript_editor")
                and self.manuscript_editor.current_chapter_editor):
            self.chat_widget.add_message(
                "Assistant",
                "No chapter is open — can't edit a previous insertion.")
            return
        chapter_editor = self.manuscript_editor.current_chapter_editor
        chapter_id = chapter_editor.chapter.id
        records = self._writer_insertions.get(chapter_id) or []
        if not records:
            self.chat_widget.add_message(
                "Assistant",
                "No recent AI insertions in this chapter to edit. "
                "Ask me to write something first, then refer back.")
            return
        idx = resolve_index(params.get("index"), len(records))
        if idx is None:
            self.chat_widget.add_message(
                "Assistant",
                f"Invalid index {params.get('index')!r}. There "
                f"are {len(records)} insertion(s) (0…{len(records)-1}).")
            return

        record = records[idx]
        editor = chapter_editor.editor
        full_text = editor.toPlainText()
        start = int(record.get("start", 0))
        end = int(record.get("end", start + len(record.get("prose", ""))))
        # Sanity-check the range against the current editor state. If
        # the recorded prose no longer matches what's at the range,
        # the user probably edited the chapter manually — fall back to
        # finding the prose by content. Failing that, abort.
        recorded_prose = record.get("prose", "") or ""
        actual_prose = full_text[start:end]
        if actual_prose != recorded_prose:
            # Try to relocate by content
            located = full_text.find(recorded_prose)
            if located >= 0:
                start = located
                end = located + len(recorded_prose)
            else:
                self.chat_widget.add_message(
                    "Assistant",
                    "I can't find the original passage in the chapter "
                    "anymore — looks like it was edited or removed "
                    "manually. Tell me what scene you want me to "
                    "rewrite and I'll start fresh.")
                return

        # Surrounding chapter context — give the editor model 600
        # chars before and after so the rewrite stays seamless.
        ctx_before = full_text[max(0, start - 600):start]
        ctx_after = full_text[end:end + 600]

        # Stash state for the response handler
        self._edit_state = {
            "chapter_id": chapter_id,
            "chapter_editor": chapter_editor,
            "record_index": idx,
            "start": start,
            "end": end,
            "old_prose": recorded_prose,
            "instructions": instructions,
            "user_message": getattr(
                self, "_pending_chat_message", "") or "",
        }

        # Build the edit prompt
        chapter_planning = None
        try:
            chapter_planning = chapter_editor.chapter.planning
        except Exception:
            pass
        chapter_voice_lines = []
        if chapter_planning:
            for attr, label in [
                ("description", "Chapter goal"),
                ("pov_character", "POV character"),
                ("tone", "Tone"),
                ("voice", "Voice"),
                ("style", "Style"),
                ("pacing", "Pacing"),
            ]:
                v = (getattr(chapter_planning, attr, "") or "").strip()
                if v:
                    chapter_voice_lines.append(f"{label}: {v}")
        voice_block = ("\n".join(chapter_voice_lines)
                       if chapter_voice_lines
                       else "(no chapter planning data)")

        prompt = (
            "EDIT INSTRUCTIONS:\n"
            f"{instructions}\n\n"
            "CHAPTER VOICE / CONSTRAINTS (match these exactly):\n"
            f"{voice_block}\n\n"
            "SURROUNDING TEXT (for seamless continuity — do not include "
            "this in your output, just match its voice and meaning):\n"
            f"BEFORE:\n{ctx_before or '(this is the chapter opening)'}\n"
            f"AFTER:\n{ctx_after or '(this is the chapter ending)'}\n\n"
            "ORIGINAL PASSAGE TO REVISE:\n"
            f"{recorded_prose}\n\n"
            "Output ONLY the revised passage as a drop-in replacement. "
            "No preamble, no labels, no XML."
        )

        # Run the edit on the worker thread so the UI stays responsive.
        self._edit_worker = _InsertionEditWorker(
            prompt=prompt,
            system_prompt=self.EDIT_INSERTION_SYSTEM_PROMPT,
        )
        self._edit_worker.finished.connect(self._on_edit_insertion_done)
        self._edit_worker.error.connect(self._on_edit_insertion_error)
        self._edit_worker.start()
        self.statusBar().showMessage(
            f"Editing insertion [{idx}] — running model…", 4000)

    def _on_edit_insertion_done(self, raw_response: str):
        """Apply the edit-LLM result to the editor + update the registry."""
        from src.ai.output_sanitizer import (
            strip_meta_tokens, is_degenerate_output)
        state = getattr(self, "_edit_state", None) or {}
        if not state:
            return
        if is_degenerate_output(raw_response):
            self.chat_widget.add_message(
                "Assistant",
                "The edit model returned mostly internal channel / "
                "format tokens. Nothing was changed — try again or "
                "switch models.")
            self._edit_state = {}
            return
        new_prose = strip_meta_tokens(raw_response or "").strip()
        if not new_prose:
            self.chat_widget.add_message(
                "Assistant",
                "The edit model returned empty output. Nothing was "
                "changed.")
            self._edit_state = {}
            return

        chapter_editor = state.get("chapter_editor")
        if not (chapter_editor and chapter_editor.editor):
            return
        editor = chapter_editor.editor
        start = int(state["start"])
        end = int(state["end"])

        # Replace the range in-place using a QTextCursor.
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
        cursor.insertText(new_prose)
        editor.setTextCursor(cursor)

        # Update the registry record. The new range starts where the
        # old one did + ends after the new prose. Subsequent
        # insertions in the same chapter need their offsets shifted
        # by the length delta.
        chapter_id = state["chapter_id"]
        new_end = start + len(new_prose)
        delta = new_end - end
        records = self._writer_insertions.get(chapter_id) or []
        idx = state["record_index"]
        if 0 <= idx < len(records):
            records[idx] = {
                **records[idx],
                "start": start,
                "end": new_end,
                "prose": new_prose,
                "prompt": (records[idx].get("prompt", "")
                            + " | edit: "
                            + state.get("user_message", "")),
            }
        # Shift any insertions that started AFTER the edited range
        if delta != 0:
            for i, rec in enumerate(records):
                if i == idx:
                    continue
                if rec["start"] >= end:
                    rec["start"] += delta
                    rec["end"] += delta

        word_count = len(new_prose.split())
        self.chat_widget.add_message(
            "Assistant",
            f"Edited insertion [{idx}] — replaced "
            f"{len(state['old_prose'].split()):,} words "
            f"with {word_count:,} words. The chapter now reads with "
            f"your edit applied.")
        self.statusBar().showMessage(
            f"Edited AI insertion: {word_count} words", 4000)
        self._edit_state = {}

    def _on_edit_insertion_error(self, msg: str):
        self.chat_widget.add_message(
            "Assistant", f"Edit failed: {msg}")
        self._edit_state = {}

    # ── Long-form writing dispatch ────────────────────────────────────

    def _dispatch_long_form_writing(self, call: dict):
        """Route a parsed long-form writing tool call to the agent.

        Handles the three tool variants — full chapter, append plot
        points, continue from cursor. Auto-saves the existing chapter
        as a "Pre-rewrite draft" revision when full-chapter mode runs
        on a non-empty chapter, then kicks off the worker.
        """
        tool = call.get("tool", "")
        params = call.get("params", {}) or {}
        instructions = params.get("instructions") or params.get("focus") or ""

        if not (hasattr(self, 'manuscript_editor')
                and self.manuscript_editor.current_chapter_editor):
            self.chat_widget.add_message(
                "Assistant",
                "I can't run long-form writing — no chapter is open. "
                "Open a chapter in the manuscript editor first.")
            return

        chapter_editor = self.manuscript_editor.current_chapter_editor
        chapter = chapter_editor.chapter
        editor = chapter_editor.editor
        existing_text = editor.toPlainText() or ""
        cursor = editor.textCursor()
        cursor_pos = cursor.position()

        # Pick mode + initial cursor / prior-text setup based on tool
        if tool == "write_chapter_full":
            mode = WritingMode.FULL_CHAPTER
            prior_text = ""
            target_points = int(params.get("target_points", 0) or 0)
            existing_for_planner = existing_text  # planner sees what's there to know it's a rewrite
            # Auto-save existing content as a draft revision before
            # we start writing fresh, but only if there IS content.
            if existing_text.strip() and params.get(
                    "save_existing_as_draft", True):
                if not self._snapshot_chapter_as_draft(chapter):
                    self.chat_widget.add_message(
                        "Assistant",
                        "Could not save the current chapter as a draft "
                        "revision. Aborting to protect your work.")
                    return
        elif tool == "append_plot_points":
            mode = WritingMode.APPEND_POINTS
            prior_text = existing_text
            target_points = int(params.get("target_points", 1) or 1)
            existing_for_planner = existing_text
        elif tool == "continue_from_cursor":
            mode = WritingMode.FROM_CURSOR
            # Prior text is everything BEFORE the cursor; we throw away
            # what comes after for planning purposes (the user can fold
            # it back in manually if they want).
            prior_text = existing_text[:cursor_pos]
            target_points = int(params.get("target_points", 1) or 1)
            existing_for_planner = prior_text
        else:
            self.chat_widget.add_message(
                "Assistant", f"Unknown long-form tool: {tool}")
            return

        # Stash state for the response handlers
        self._long_form_state = {
            "tool": tool,
            "mode": mode,
            "chapter_editor": chapter_editor,
            "cursor_pos": cursor_pos,
            "prior_text": prior_text,
            "instructions": instructions,
            "params": params,
            "target_points": target_points,
            "existing_for_planner": existing_for_planner,
            "first_insertion": True,
            "plan": None,
            # Beats accumulator: each entry is (title, description, prose).
            # Drives the per-beat rating dialog after completion.
            "beats_written": [],
        }

        # Build the RAG provider — same wrapper the critique flow uses
        rag_provider = None
        if hasattr(self, "_rag_top_chunks_per_type") and self._rag_initialized:
            rag_provider = lambda q, st: self._rag_top_chunks_per_type(
                query=q, source_types=st,
                top_k=6, max_chars_per_chunk=600,
                max_total_chars=2500,
            )

        # Kick off the worker
        self._long_form_worker = LongFormWriterWorker(
            chapter=chapter,
            instructions=instructions,
            mode=mode,
            existing_text=existing_for_planner,
            prior_text=prior_text,
            target_points=target_points,
            project=self.current_project,
            rag_provider=rag_provider,
        )
        self._long_form_worker.progress.connect(
            self._on_long_form_progress)
        self._long_form_worker.plan_ready.connect(
            self._on_long_form_plan_ready)
        self._long_form_worker.point_written.connect(
            self._on_long_form_point_written)
        self._long_form_worker.finished.connect(
            self._on_long_form_finished)
        self._long_form_worker.error.connect(
            self._on_long_form_error)
        self._long_form_worker.start()
        self.statusBar().showMessage("Long-form writing: planning…", 5000)

    def _snapshot_chapter_as_draft(self, chapter) -> bool:
        """Save the chapter's current content as a "Pre-rewrite draft" revision.

        Then create a fresh blank revision so the AI's new prose lands
        in a separate revision and the pre-rewrite draft is preserved.
        Returns True on success.
        """
        from datetime import datetime
        from pathlib import Path
        try:
            project_dir = None
            if (self.current_project and self.current_project.project_path):
                project_dir = Path(self.current_project.project_path).parent
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            chapter.add_revision(
                notes=f"Pre-rewrite draft ({stamp}) — autosaved before AI rewrite",
                project_dir=project_dir,
            )
            chapter.create_blank_revision(
                project_dir=project_dir,
                notes=f"AI rewrite ({stamp})",
            )
            self.statusBar().showMessage(
                f"Saved current chapter as Pre-rewrite draft revision",
                4000,
            )
            return True
        except Exception as e:
            print(f"[long_form] failed to snapshot chapter as draft: {e}")
            return False

    def _on_long_form_progress(self, msg: str):
        """Surface long-form writer progress via status bar."""
        self.statusBar().showMessage(msg, 3000)

    def _on_long_form_plan_ready(self, plan):
        """Plan is ready — store it on the active state.

        If the plan poses clarifying questions, we surface them in the
        chat and stop here. The user answers in chat; their answer
        comes back through the normal chat path; the model emits the
        write tool again with the answers folded into instructions.
        """
        if not hasattr(self, "_long_form_state") or not self._long_form_state:
            return
        self._long_form_state["plan"] = plan

    def _on_long_form_point_written(
        self, index: int, title: str, prose: str, prompt: str = ""):
        """Insert a freshly-written beat into the editor as it lands.

        ``prompt`` carries the actual LLM input the agent used for this
        beat — full chapter constraints, running synopsis, RAG
        context, and the beat brief. Persisting (prompt, prose) gives
        the trainer a real instruction → completion pair instead of
        a synthesised stub.
        """
        if not hasattr(self, "_long_form_state") or not self._long_form_state:
            return
        state = self._long_form_state
        # Capture the beat for the rating dialog. Pull description from
        # the plan when available (the worker only emits the title in
        # this signal to keep the payload small).
        plan = state.get("plan")
        description = ""
        if plan and 0 <= index < len(plan.plot_points):
            description = plan.plot_points[index].description or ""
        state.setdefault("beats_written", []).append(
            (title, description, prose, prompt))
        chapter_editor = state.get("chapter_editor")
        if not chapter_editor or not prose.strip():
            return
        editor = chapter_editor.editor
        cursor = editor.textCursor()
        if state.get("first_insertion"):
            # Position the cursor at the right spot the FIRST time only.
            # Subsequent beats just continue from where we left off.
            mode = state["mode"]
            if mode == WritingMode.FULL_CHAPTER:
                editor.setPlainText("")  # blank canvas
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
            elif mode == WritingMode.APPEND_POINTS:
                cursor.movePosition(cursor.MoveOperation.End)
                current = editor.toPlainText()
                if current and not current.endswith("\n\n"):
                    cursor.insertText("\n\n")
            elif mode == WritingMode.FROM_CURSOR:
                cursor.setPosition(state.get("cursor_pos", 0))
            state["first_insertion"] = False
        else:
            # For subsequent beats, separate with a paragraph break
            cursor.insertText("\n\n")
        ins_start = cursor.position()
        cursor.insertText(prose)
        editor.setTextCursor(cursor)
        # Update the stored cursor pos so the next insert continues
        state["cursor_pos"] = cursor.position()
        # Record this beat in the writer-insertion registry so
        # follow-up edit requests can target it precisely.
        self._record_writer_insertion(
            chapter_id=chapter_editor.chapter.id,
            start=ins_start,
            end=cursor.position(),
            prose=prose,
            prompt=prompt or "",
            mode=f"long_form:{state.get('mode').value if state.get('mode') else 'unknown'}",
            summary=f"Beat {index + 1}: {title}",
        )
        self.statusBar().showMessage(
            f"Wrote beat {index + 1}: {title}", 3000)

    def _on_long_form_finished(self, plan, full_prose: str):
        """Handle worker completion — either a Q&A pause or full prose."""
        if not hasattr(self, "_long_form_state"):
            self._long_form_state = {}
        # Q&A pause: plan has questions and no prose was generated.
        if plan and getattr(plan, "questions", None) and not full_prose:
            self._long_form_state["plan"] = plan
            qs = "\n".join(f"  {i+1}. {q}"
                           for i, q in enumerate(plan.questions))
            beats = (f"\n\nThe plan covers {len(plan.plot_points)} beat(s):"
                     + "".join(f"\n  • {p.title}"
                               for p in plan.plot_points[:8]))
            if len(plan.plot_points) > 8:
                beats += f"\n  • …and {len(plan.plot_points) - 8} more"
            self.chat_widget.add_message(
                "Assistant",
                "Plan ready. Answer these questions and I'll draft "
                f"the prose:{beats}\n\n{qs}\n\n"
                "Reply with your answers and the engine will pick up.")
            return
        # Full execution finished.
        if full_prose:
            word_count = len(full_prose.split())
            beats_count = len(plan.plot_points) if plan else 0
            self.chat_widget.add_message(
                "Assistant",
                f"Done. Drafted {beats_count} beat(s), {word_count:,} words "
                f"into the chapter. Rate the draft when you've had a "
                f"chance to read it — the rating window is open.")
            self.statusBar().showMessage(
                f"Long-form writing: {word_count:,} words drafted", 5000)
            # Surface the rating dialog so the user can mark the draft
            # excellent / good / poor / bad and (optionally) save it
            # as training data — one row per beat.
            beats = list(self._long_form_state.get("beats_written") or [])
            if beats:
                chapter_title = (
                    plan.chapter_title if plan else "Untitled Chapter")
                genre = (plan.genre if plan and plan.genre
                         else (
                             self.current_project.prose_profile.genre
                             if self.current_project
                             else ""))
                project_path = (
                    str(self.current_project.project_path)
                    if (self.current_project
                        and self.current_project.project_path)
                    else "")
                summary = (
                    f"{beats_count} beat(s), ~{word_count:,} words. "
                    f"Genre: {genre or 'unspecified'}.")
                self._long_form_rating_dialog = LongFormRatingDialog(
                    chapter_title=chapter_title,
                    beats=beats,
                    plan_summary=summary,
                    project_path=project_path,
                    genre=genre,
                    voice=(plan.voice_notes if plan else ""),
                    pov=(plan.pov if plan else ""),
                    parent=self,
                )
                self._long_form_rating_dialog.show()
                self._long_form_rating_dialog.raise_()
        # Clear state
        self._long_form_state = {}

    def _on_long_form_error(self, error: str):
        """Surface long-form writer errors in chat."""
        self.chat_widget.add_message(
            "Assistant", f"Long-form writing error: {error}")
        self._long_form_state = {}

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

        # Coerce list-or-str into list[str]; drop empties. The AI
        # sometimes nests structured beat dicts inside what should
        # be a plain string list (e.g. scene_list emitted as
        # ``[{"text": "opening", "description": "Marcus arrives"},
        #   ...]``). When that happens, pull the human-readable
        # field instead of letting Python stringify the whole dict
        # as ``"{'text': 'opening', 'description': 'Marcus arrives'}"``
        # — which was landing on the chapter arc as the literal beat
        # name and looked broken to the user.
        def _as_str_list(value):
            if value is None or value == "":
                return []
            if isinstance(value, list):
                out = []
                for v in value:
                    if isinstance(v, dict):
                        # Prefer ``text`` (StoryEvent shape), then
                        # ``title``, then ``name`` — fall back to a
                        # joined "head: body" so we don't lose the
                        # body text when only ``description`` is
                        # populated.
                        head = (v.get('text') or v.get('title')
                                or v.get('name') or '').strip()
                        body = (v.get('description')
                                or v.get('summary') or '').strip()
                        if head and body:
                            out.append(f"{head}: {body}")
                        elif head:
                            out.append(head)
                        elif body:
                            out.append(body)
                        # Empty dict → silently drop.
                    else:
                        s = str(v).strip()
                        if s:
                            out.append(s)
                return out
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
        # arc visual. Prefer explicit ``events`` (richer), then
        # ``scene_list``, then derive 1-3 stub events from the
        # description so the planner pane is never blank for an
        # AI-spawned chapter — even when the AI gave only a
        # one-line synopsis.
        scene_list = _as_str_list(data.get('scene_list'))
        events = self._build_chapter_planner_events(
            data.get('events'), scene_list, chapter_id)
        if not events and description:
            # Fallback: split the description's first 1-3 sentences
            # into beats so the planner has SOMETHING to render.
            # Better than an empty arc.
            import re as _re
            sentences = [
                s.strip() for s in
                _re.split(r"(?<=[.!?])\s+",
                          description.replace("Goal:", " ").strip())
                if s.strip()]
            stub_scenes = sentences[:3] if sentences else []
            if stub_scenes:
                events = self._build_chapter_planner_events(
                    None, stub_scenes, chapter_id)

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

        # Also drop a single project-wide PlotEvent on the Freytag
        # pyramid representing this chapter as one beat on the
        # overall arc. Different from the chapter's INTERNAL events
        # (those are scenes within the chapter); this is one
        # macro-beat the user sees on the project plot map. Without
        # it, AI-spawned chapters show up in the manuscript but are
        # invisible on the project arc — a confusing split. Stage +
        # act are derived from the chapter's position relative to
        # the manuscript total; intensity stays at the default 50
        # so the user can tune it on the visual.
        try:
            self._add_chapter_to_project_plot_arc(
                chapter, planning, next_number)
        except Exception as e:
            print(f"[chapter-create] couldn't add to project "
                  f"plot arc: {e}")

        # Surface what landed so it's clear in the console which
        # plot-plan fields the AI provided vs which were defaulted.
        filled = sum(1 for v in (
            planning.description, planning.scene_list,
            planning.themes, planning.characters_featured,
            planning.locations, planning.tone, planning.voice,
            planning.style, planning.pacing,
            planning.pov_character) if v)
        print(f"Created chapter: {title} (Chapter {next_number}) "
              f"with {filled} plan field(s) populated, "
              f"{len(planning.events)} chapter-arc beat(s), "
              f"+1 project-arc beat")

        # Refresh manuscript editor to show the new chapter
        if hasattr(self, 'manuscript_editor'):
            self.manuscript_editor.load_manuscript(self.current_project.manuscript)
        # And the story-planning widget so the new project-arc
        # PlotEvent shows up on the Freytag pyramid immediately.
        self._refresh_story_planning_after_create()

        return ('chapter', f"{next_number}. {title}")

    def _add_chapter_to_project_plot_arc(
            self, chapter, planning, chapter_number: int) -> None:
        """Append a project-arc PlotEvent representing this chapter.

        Stage / act assignment is heuristic from chapter position
        within the manuscript so AI-spawned chapters land in a
        sensible spot on the Freytag pyramid even before the user
        adjusts. The event references the chapter via title +
        ``related_characters`` (drawn from the planning roster) so
        downstream views (plot-tab arc, plot AI's STORY EVENTS
        block) link cleanly back to the chapter.
        """
        from datetime import datetime
        from src.models.project import PlotEvent
        sp = self.current_project.story_planning
        if sp is None or sp.freytag_pyramid is None:
            return

        total = max(1, len(self.current_project.manuscript.chapters))
        # Position 1..total → 0..100; new chapters always land at the
        # end of the project arc so position ≈ 100 unless the user
        # later renumbers.
        pct = (chapter_number - 1) / max(1, total - 1) if total > 1 else 100
        pct *= 100 if total > 1 else 1
        if total == 1:
            pct = 50  # Single-chapter projects: park mid-arc.
        if pct <= 15:
            stage = 'exposition'
        elif pct < 50:
            stage = 'rising_action'
        elif pct < 65:
            stage = 'climax'
        elif pct < 90:
            stage = 'falling_action'
        else:
            stage = 'resolution'

        # Pick an act based on the user's configured num_acts. With
        # the default 3-act structure: chapter 1-33% → act 1, 33-66%
        # → act 2, 66-100% → act 3.
        num_acts = max(1, int(getattr(
            sp.freytag_pyramid, 'num_acts', 3)))
        act = min(num_acts, max(1, int(pct / 100 * num_acts) + 1))

        # Build a short label so the project arc reads as a chapter
        # list, not a scene list. Description carries the chapter's
        # description / synopsis so the plot AI's STORY EVENTS
        # block surfaces enough detail to discuss this chapter.
        title = f"Ch {chapter_number}: {chapter.title}"
        description = (planning.description or '').strip()
        if not description and planning.scene_list:
            description = planning.scene_list[0]

        ev = PlotEvent(
            id=f"chapter_event_{chapter.id}",
            title=title,
            description=description[:600],
            outcome='',
            stage=stage,
            act=act,
            intensity=50,
            related_characters=list(planning.characters_featured),
            notes=(f"Auto-added when Chapter {chapter_number} was "
                   f"created. Adjust the act / stage / intensity "
                   f"on the Freytag pyramid to taste."),
        )
        sp.freytag_pyramid.events.append(ev)

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
        # Make sure the AI Assistant tab is visible. The sidebar
        # owns the collapsed state now; expand it if it's hidden,
        # then switch to the chat tab so the question lands where
        # the user can see the response.
        if hasattr(self, "sidebar_container"):
            self.sidebar_container.expand()
        if hasattr(self, "sidebar_tabs"):
            idx = self.sidebar_tabs.indexOf(self.chat_widget)
            if idx >= 0:
                self.sidebar_tabs.setCurrentIndex(idx)

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
