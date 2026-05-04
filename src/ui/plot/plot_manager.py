"""Plot manager with Freytag pyramid, events, and subplots."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QTabWidget, QListWidgetItem, QTextEdit, QGroupBox,
    QDialog, QDialogButtonBox, QLineEdit, QFormLayout, QScrollArea, QFrame,
    QToolButton, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

from src.models.project import (
    FreytagPyramid, PlotEvent, Subplot, StoryPromise, CharacterTension,
    Theme,
)
from src.ui.plot.freytag_pyramid_visual import FreytagPyramidVisual
from src.ui.plot.plot_event_editor import PlotEventEditor


# Plot-AI system prompt. Lives at module scope so the worker thread
# doesn't capture ``self`` indirectly through a method reference.
# Mirrors the chat plot-mode prompt in main_window.SYSTEM_PROMPTS["plot"]
# so the same model produces consistent output regardless of which
# surface the user reaches it from.
_PLOT_AI_SYSTEM = (
    "You are a story-structure consultant. The author is asking "
    "about plot, structure, pacing, character arcs, story promises, "
    "or sustained tensions. You have the manuscript text, the plot "
    "map (Freytag pyramid + events + subplots + promises + "
    "tensions), worldbuilding, and characters in context.\n\n"
    "PRIME DIRECTIVE: be SPECIFIC. Every point you make should "
    "anchor to something concrete in this project — a chapter "
    "('Ch 4: The Reckoning'), a plot event by its title, a promise "
    "by its title, a tension by its title, a character or "
    "worldbuilding entity by name. Generic craft advice ('add more "
    "conflict', 'deepen the protagonist') is a failure mode. Your "
    "job is to react to THIS manuscript and THIS plot map.\n\n"
    "USE EACH CONTEXT BLOCK (skipping any of these blocks is a "
    "failure mode — if they're populated, REFERENCE them):\n"
    "1. PLOT MAP — the author's intended structure. Reference items "
    "by exact title. The STORY TENSIONS block lists sustained "
    "dramatic forces (internal struggle, interpersonal conflict, "
    "societal pressure, cosmic threat) with current state and "
    "intensity — name them when discussing pacing or proposing "
    "beats so your suggestions move the right pressure on the "
    "right people.\n"
    "2. STORY THEMES — what the book is *about* underneath its "
    "events (the argument it's making). Every plot suggestion "
    "should reinforce a named theme or explicitly reckon with "
    "undercutting one. When asked about plot, weigh whether the "
    "proposed beat lands the theme. When the THEMES block is "
    "empty or only has bare labels, you may PROPOSE themes the "
    "manuscript is implicitly making (use <suggest_theme>).\n"
    "3. SUBPLOTS — secondary storylines tied to the main plot, each "
    "with its own status, characters, and event arc. Treat them as "
    "first-class story material: every plot discussion (pacing, "
    "what-next, structural audit) should weigh which subplots are "
    "advancing, stalled, or being dropped. When proposing beats, "
    "name which subplot the beat advances or which subplot needs a "
    "scene next. Don't let a subplot disappear from the discussion "
    "just because the user didn't mention it by name.\n"
    "4. MANUSCRIPT — what is actually on the page. Cite as 'Ch N: "
    "Title'. Quote ≤25-word passages when wording matters.\n"
    "5. CHARACTERS — names, personalities, wants/needs, fears, "
    "arcs. Check that the people in your proposed beats match "
    "their established profile (a quiet character doesn't "
    "suddenly give a speech without justification). When asked "
    "about character arcs, name SPECIFIC characters from this "
    "block and the chapter their state shows up in.\n"
    "6. WORLDBUILDING — factions, places, cultures, magic, tech. "
    "Check that proposed beats are plausible in the world. When "
    "the discussion touches on faction conflict or location, "
    "reference the SPECIFIC entities in this block by name.\n"
    "7. RELEVANT PROJECT DETAIL (if present) — RAG-selected "
    "characters and worldbuilding entries closest to the user's "
    "question. These are your deep-detail source; cross-reference "
    "them when they're relevant.\n"
    "8. If a context block is empty or thin, SAY SO and ask for "
    "what you need. Don't fabricate. Don't invent characters, "
    "subplots, tensions, themes, or worldbuilding entities that "
    "aren't listed.\n\n"
    "OUTPUT SHAPE:\n"
    "• Direct answer first (1-2 sentences).\n"
    "• Then reasoning under short bold headers when there's more "
    "than one thread (e.g. **Setup**, **Payoff**, **Risk**).\n"
    "• Proposed changes name the exact chapter or event they land "
    "in.\n"
    "• Open-ended questions ('what next?', 'how do I tighten Act "
    "2?') get 2-3 numbered options, each with **what it costs** "
    "(tone shift, pacing impact, promise affected). Don't pick.\n"
    "• Flag plot holes / broken promises only when they answer the "
    "question. One incidental flag is fine; don't dump a critique "
    "the author didn't ask for.\n\n"
    "DO NOT write manuscript prose — that's Writer mode. DO NOT "
    "restate the question or open with filler ('Great question!'). "
    "DO NOT invent chapter/event/promise titles that aren't in the "
    "context — if a beat needs a name that doesn't exist, say "
    "'(no event for this yet — want me to add one?)'.\n\n"
    "PROPOSING NEW PROJECT ELEMENTS:\n"
    "When the discussion makes it clear the project would benefit "
    "from a new element, you may propose it inline by emitting an "
    "XML-style block right after the discussion text. The user "
    "reviews each suggestion and clicks Add or Skip — you are NOT "
    "auto-creating anything. Use these exact tag names (lowercase, "
    "no spaces) and put a single JSON object inside.\n\n"
    "PLOT-NATIVE SUGGESTIONS (prefer these during plot "
    "discussion):\n\n"
    "  <suggest_plot_event>{\"title\":\"…\",\"description\":\"…\","
    "\"stage\":\"exposition|rising_action|climax|falling_action|"
    "resolution\",\"act\":<int 1-7>,\"intensity\":<int 0-100>,"
    "\"related_characters\":[\"name1\",\"name2\"],\"why\":\"one "
    "line: how this beat serves the plot\"}"
    "</suggest_plot_event>\n\n"
    "  <suggest_subplot>{\"title\":\"…\",\"description\":\"…\","
    "\"connection_to_main\":\"how it ties to the main plot\","
    "\"related_characters\":[\"name1\"],\"why\":\"…\"}"
    "</suggest_subplot>\n\n"
    "  <suggest_promise>{\"promise_type\":\"tone|plot|genre|"
    "character\",\"title\":\"brief summary\",\"description\":\"the "
    "commitment to readers\",\"related_characters\":[\"name1\"],"
    "\"why\":\"why this promise needs to be on the page\"}"
    "</suggest_promise>\n\n"
    "  <suggest_tension>{\"title\":\"short label\","
    "\"tension_type\":\"internal|interpersonal|societal|cosmic\","
    "\"description\":\"what's the source\",\"characters_involved\":"
    "[\"name1\",\"name2\"],\"stakes\":\"what's at risk\","
    "\"current_state\":\"rising|stable|escalating|resolving|"
    "unresolved|resolved\",\"intensity\":<int 0-100>,\"why\":\"why "
    "this tension matters now\"}</suggest_tension>\n"
    "    NOTE: ``characters_involved`` MUST contain names that "
    "appear in the CHARACTERS context block. If you want to put "
    "pressure on a character that doesn't exist yet, propose the "
    "character with <suggest_character> in the SAME reply, and "
    "use that character's name in the tension's "
    "characters_involved.\n"
    "    DEFINING TENSIONS INTERACTIVELY: when the user asks to "
    "discuss / define / brainstorm tensions, prefer to talk "
    "through the option(s) in prose first (who's pressed, what's "
    "at stake, why now) before emitting the suggest_tension "
    "block. The block goes at the END of your reply so the user "
    "can read your reasoning before clicking Add.\n\n"
    "  <suggest_theme>{\"title\":\"short label\",\"statement\":"
    "\"the argument the story makes — one or two sentences\","
    "\"description\":\"what the theme is exploring\","
    "\"motifs\":[\"recurring image 1\",\"recurring object 2\"],"
    "\"related_characters\":[\"name1\"],\"why\":\"why this theme "
    "is implied by the manuscript and worth naming explicitly\"}"
    "</suggest_theme>\n"
    "    NOTE: ``related_characters`` MUST contain names from the "
    "CHARACTERS context block. Themes are about the meaning layer "
    "(what the book is *about*), not the plot layer (what "
    "happens) — propose them when the discussion reveals an "
    "argument the manuscript is making but hasn't formalised, or "
    "when proposed beats would only land if a particular theme "
    "were already named.\n\n"
    "WORLDBUILDING / CHARACTER SUGGESTIONS (only when the plot "
    "discussion calls for a NEW entity that doesn't yet exist):\n\n"
    "  <suggest_character>{\"name\":\"…\",\"character_type\":"
    "\"protagonist|antagonist|major|minor\",\"personality\":\"…\","
    "\"backstory\":\"…\",\"why\":\"…\"}</suggest_character>\n\n"
    "  <suggest_place>{\"name\":\"…\",\"location_type\":\"city|"
    "town|landmark|region|building|other\",\"description\":\"…\","
    "\"significance\":\"…\",\"why\":\"…\"}</suggest_place>\n\n"
    "  <suggest_faction>{\"name\":\"…\",\"description\":\"…\","
    "\"goals\":\"…\",\"why\":\"…\"}</suggest_faction>\n\n"
    "  <suggest_culture>{\"name\":\"…\",\"description\":\"…\","
    "\"customs\":\"…\",\"values\":\"…\",\"why\":\"…\"}"
    "</suggest_culture>\n\n"
    "  <suggest_chapter>{\"title\":\"…\","
    "\"synopsis\":\"one-paragraph what-happens summary\","
    "\"goal\":\"what this chapter accomplishes for the plot\","
    "\"pov_character\":\"name from CHARACTERS context\","
    "\"scene_list\":[\"opening: where + who + the inciting "
    "moment\",\"middle: complication or escalation\","
    "\"close: turn or hook into next chapter\"],"
    "\"characters_featured\":[\"name1\",\"name2\"],"
    "\"locations\":[\"place name from WORLDBUILDING context\"],"
    "\"themes\":[\"theme title from STORY THEMES context\"],"
    "\"tone\":\"e.g. tense, melancholic, hopeful\","
    "\"voice\":\"narrative voice (sardonic, lyrical, flat, …)\","
    "\"style\":\"prose style note (short punchy / flowing / …)\","
    "\"pacing\":\"e.g. slow-burn, rapid-fire, contemplative\","
    "\"timeline_position\":\"e.g. one week after Ch 7 / next "
    "morning / 5 years later\","
    "\"why\":\"why this chapter belongs here in the plot\"}"
    "</suggest_chapter>\n"
    "    NOTE: when proposing a chapter during plot discussion, "
    "fill in the plot plan — at minimum the scene_list (3-5 "
    "scenes), characters_featured (names from the CHARACTERS "
    "context), and themes (titles from STORY THEMES). The "
    "chapter should be born with structure so the user can drop "
    "into Writer mode immediately. Don't propose a chapter that "
    "is just a title + synopsis when the discussion has been "
    "specific about who and what should be in it.\n"
    "    The scene_list is auto-converted into chapter-arc "
    "events the user sees in the chapter planner — each scene "
    "becomes a beat with a heuristic stage and arc position. "
    "If you want finer control, you may instead provide an "
    "``events`` array of objects:\n"
    "      \"events\": [{\"text\":\"short beat name\","
    "\"description\":\"one-line beat detail\","
    "\"stage\":\"exposition|rising|climax|falling|resolution\","
    "\"arc_position\": <0-100>}, …]\n"
    "    Use the ``events`` form when the chapter's dramatic "
    "shape is non-uniform (e.g. early climax with a long falling "
    "action). Otherwise scene_list is enough.\n\n"
    "RULES FOR SUGGESTIONS:\n"
    "• Only suggest when the discussion genuinely calls for it — "
    "don't pad replies with suggestions just to look productive.\n"
    "• At most TWO suggestions per response.\n"
    "• Each suggestion must have a ``why`` field tying it back to a "
    "specific chapter, plot event, promise, or tension from the "
    "context.\n"
    "• Plot-native suggestions (event / subplot / promise / "
    "tension) are usually the right answer when the discussion is "
    "about plot. Don't reach for a new character if the structural "
    "issue is missing tension or a missing beat.\n"
    "• Pick names + characters that fit existing world / cultures. "
    "For event / promise / tension blocks, list character names "
    "verbatim from the CHARACTERS context — don't invent characters "
    "to put inside a tension or event.\n"
    "• Don't suggest something that's already in the project — check "
    "the PLOT MAP / CHARACTERS / WORLDBUILDING / MANUSCRIPT "
    "CHAPTERS blocks first.\n"
    "• The block goes inline in your reply; the rest of your reply "
    "stays in normal prose so the user can read your reasoning."
)


# Tags the plot AI emits when it wants to propose a new element.
# Order matters: ``<suggest_character>`` and friends are stripped from
# the displayed reply and rendered as cards instead. Map values are
# the (display label, kind) used by the host's create-callback.
# Plot-native kinds (event/subplot/promise/tension) are first because
# they're the most common things to propose during plot discussion;
# worldbuilding kinds (character/place/faction/culture/chapter)
# follow.
_SUGGEST_TAG_RX = {
    "suggest_plot_event": ("Plot Event", "plot_event"),
    "suggest_subplot": ("Subplot", "subplot"),
    "suggest_promise": ("Story Promise", "promise"),
    "suggest_tension": ("Tension", "tension"),
    "suggest_theme": ("Theme", "theme"),
    "suggest_character": ("Character", "character"),
    "suggest_place": ("Place", "place"),
    "suggest_faction": ("Faction", "faction"),
    "suggest_culture": ("Culture", "culture"),
    "suggest_chapter": ("Chapter", "chapter"),
}


def _extract_suggestions(reply: str):
    """Pull <suggest_*> blocks from a model reply.

    Returns ``(cleaned_reply, [{"kind", "label", "data", "raw"}])``
    where ``cleaned_reply`` has the blocks removed (so we can render
    them as cards alongside the prose), and ``data`` is the parsed
    JSON dict for each suggestion. Bad JSON inside a block is
    surfaced as a card with ``data=None`` and ``raw`` populated so
    the user at least sees what the AI tried to propose.
    """
    import re
    import json
    cleaned = reply
    suggestions = []
    for tag, (label, kind) in _SUGGEST_TAG_RX.items():
        pattern = re.compile(
            rf"<{tag}>\s*(.*?)\s*</{tag}>",
            re.DOTALL | re.IGNORECASE)
        for m in pattern.finditer(reply):
            raw = m.group(1).strip()
            data = None
            try:
                # Tolerate the same JSON quirks main_window's
                # create-pipeline tolerates: trailing commas, ’ smart
                # quotes around the outside, etc.
                normalized = re.sub(r",\s*}", "}", raw)
                normalized = re.sub(r",\s*]", "]", normalized)
                data = json.loads(normalized)
            except Exception:
                data = None
            suggestions.append({
                "kind": kind,
                "label": label,
                "data": data,
                "raw": raw,
            })
        cleaned = pattern.sub("", cleaned)
    # Squeeze multiple blank lines that the strip leaves behind so
    # the displayed reply stays tidy.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, suggestions


def _build_plot_ai_user_block(question: str, ctx: dict) -> str:
    """Assemble the user-prompt block sent to the plot LLM.

    Each major project concept gets its OWN labelled block with
    its OWN per-block char budget — themes, subplots, promises,
    tensions, characters, worldbuilding all render independently
    so a busy project can't silently drop the back half of any
    one section the way the old single-aggregate ``plot_map``
    string did. The system prompt references each block by the
    exact heading shown here.

    Order matters: structural plot scaffolding (Freytag → events →
    subplots → promises → tensions → themes) comes first because
    the system prompt tells the model to anchor every claim to
    those. Manuscript anchors next, then characters and
    worldbuilding (the tactile detail that makes beats land),
    then RAG-selected entries, then conversation history, then
    the author's question.
    """
    parts = []
    if ctx.get('project_name'):
        parts.append(f"PROJECT: {ctx['project_name']}")

    # ── Structural plot scaffolding ──────────────────────────
    # Each block is a separate context key now (see
    # _build_chat_context). They come labelled so the model can
    # cite by section name. Caps are deliberately generous — a
    # rich project might have 8-10k chars of plot scaffolding
    # alone and we'd rather pay the tokens than silently drop
    # subplots / themes / tensions like the old aggregate did.
    if ctx.get('plot_freytag'):
        parts.append(f"\nFREYTAG PYRAMID:\n"
                      f"{ctx['plot_freytag'][:2500]}")
    if ctx.get('plot_events'):
        parts.append(f"\nPLOT EVENTS:\n"
                      f"{ctx['plot_events'][:4000]}")
    if ctx.get('plot_subplots'):
        parts.append(
            f"\nSUBPLOTS (secondary storylines tied to the main "
            f"plot):\n{ctx['plot_subplots'][:4000]}")
    if ctx.get('plot_promises'):
        parts.append(
            f"\nSTORY PROMISES (commitments to the reader):\n"
            f"{ctx['plot_promises'][:3000]}")
    if ctx.get('plot_tensions'):
        parts.append(
            f"\nSTORY TENSIONS (sustained dramatic forces — "
            f"name them when proposing beats):\n"
            f"{ctx['plot_tensions'][:3500]}")
    if ctx.get('plot_themes'):
        parts.append(
            f"\nSTORY THEMES (what the book is about underneath "
            f"its events — every plot suggestion should reinforce "
            f"or explicitly reckon with one):\n"
            f"{ctx['plot_themes'][:3500]}")
    # Free-form fallback when none of the structured keys were set
    # (e.g. the legacy plot_map aggregate is the only source). Only
    # used when we don't have any of the dedicated keys above.
    if (not any(ctx.get(k) for k in (
            'plot_freytag', 'plot_events', 'plot_subplots',
            'plot_promises', 'plot_tensions', 'plot_themes'))
            and ctx.get('plot_map')):
        parts.append(f"\nPLOT MAP (intended structure):\n"
                      f"{ctx['plot_map'][:8000]}")
    elif (not any(ctx.get(k) for k in (
            'plot_freytag', 'plot_events', 'plot_subplots'))
            and ctx.get('plot_summary')):
        parts.append(
            f"\nPLOT OUTLINE:\n{ctx['plot_summary'][:2000]}")

    # ── Manuscript anchors ───────────────────────────────────
    if ctx.get('manuscript_index'):
        parts.append(f"\nMANUSCRIPT CHAPTERS (in order):\n"
                      f"{ctx['manuscript_index'][:2500]}")
    if ctx.get('chapter_excerpts'):
        # First+last few hundred words of every chapter — gives the
        # model enough to recognise/cite without exploding the prompt.
        parts.append(f"\nCHAPTER EXCERPTS (opening + closing of each):\n"
                      f"{ctx['chapter_excerpts'][:9000]}")
    if ctx.get('current_chapter_title'):
        parts.append(f"\nCURRENTLY OPEN CHAPTER: "
                      f"{ctx['current_chapter_title']}")
        if ctx.get('current_chapter_content'):
            content = ctx['current_chapter_content'][:6000]
            parts.append(
                f"\n--- full text of currently open chapter ---\n"
                f"{content}")

    # ── RAG-FOCUSED BLOCKS (top-K most relevant per type) ──
    # Populated by main_window's _rag_top_chunks_per_type helper for
    # plot mode. These are the high-signal subset for THIS question
    # — placed BEFORE the broad CHARACTERS / WORLDBUILDING lists so
    # the model forms its initial reasoning around the most-relevant
    # items, then has the full roster behind it for context. Each
    # block is already capped on the producing side.
    rag_blocks = []
    if ctx.get('rag_focused_characters'):
        rag_blocks.append(
            f"  CHARACTERS most relevant to this question:\n"
            f"{ctx['rag_focused_characters']}")
    if ctx.get('rag_focused_worldbuilding'):
        rag_blocks.append(
            f"  WORLDBUILDING most relevant to this question:\n"
            f"{ctx['rag_focused_worldbuilding']}")
    if ctx.get('rag_focused_subplots'):
        rag_blocks.append(
            f"  SUBPLOTS most relevant to this question:\n"
            f"{ctx['rag_focused_subplots']}")
    if ctx.get('rag_focused_chapters'):
        rag_blocks.append(
            f"  CHAPTER PASSAGES most relevant to this question:\n"
            f"{ctx['rag_focused_chapters']}")
    if rag_blocks:
        parts.append(
            "\n=== RAG-FOCUSED CONTEXT (selected for THIS "
            "question — prefer citing these specific items) ===\n"
            + "\n\n".join(rag_blocks))

    # ── Tactile detail (people + world) — full roster ───────
    # Comes AFTER the RAG-focused subset so the model has both the
    # relevant items at the top of its short-term memory AND the
    # full roster as fallback context.
    if ctx.get('characters'):
        # Bumped from 1500 → 4000 so a project with 10+ characters
        # doesn't get the cast list cut in half.
        parts.append(f"\nCHARACTERS (full roster):\n"
                      f"{ctx['characters'][:4000]}")
    if ctx.get('worldbuilding'):
        parts.append(
            f"\nWORLDBUILDING (full set):\n"
            f"{ctx['worldbuilding'][:4000]}")

    # Generic mixed RAG (cross-source-type) — kept as a fallback for
    # surfaces that don't populate the rag_focused_* keys above.
    if ctx.get('rag_context'):
        parts.append(
            f"\nRELEVANT PROJECT DETAIL (mixed RAG):\n"
            f"{ctx['rag_context'][:3500]}")
    if ctx.get('history_summary'):
        parts.append(
            f"\nEARLIER IN THIS CONVERSATION (compacted):\n"
            f"{ctx['history_summary']}")
    parts.append(f"\n=== AUTHOR'S QUESTION ===\n{question}")
    return "\n".join(parts)


def _ask_plot_ai(question: str, history: list, ctx: dict) -> str:
    """Build the prompt + send to the right LLM, return text.

    Resolution order for the LLM:
        1. Per-task plot model (``model_for_plot`` in CreativeOS
           settings) via ``build_task_llm_override("plot")``
        2. Host-supplied cloud LLM (``ctx['llm_client']``) — main_window
           passes its initialized cloud client here so we don't have
           to re-discover keys/providers from this widget
        3. Construct from settings (last-resort fallback) — uses the
           default provider from ``ai_config``
    """
    full_prompt = _build_plot_ai_user_block(question, ctx)

    # 1. Per-task plot model
    llm = None
    try:
        from src.ai.task_llm import build_task_llm_override
        llm = build_task_llm_override("plot")
    except Exception as e:
        print(f"[plot-ai] task LLM lookup failed: {e}")

    # 2. Host-supplied cloud LLM
    if llm is None and ctx.get('llm_client') is not None:
        llm = ctx['llm_client']

    # 3. Build from settings as last resort
    if llm is None:
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider
            cfg = get_ai_config()
            settings = cfg.get_settings()
            provider_name = settings.get("default_llm", "claude")
            api_key = cfg.get_api_key(provider_name)
            if not api_key:
                return ("⚠️ No AI is configured. Add an API key in "
                        "Settings → AI, or pick a plot-task trained "
                        "model in Settings → CreativeOS.")
            provider = {
                "claude": LLMProvider.CLAUDE,
                "chatgpt": LLMProvider.CHATGPT,
                "openai": LLMProvider.CHATGPT,
                "gemini": LLMProvider.GEMINI,
            }.get(provider_name.lower(), LLMProvider.CLAUDE)
            llm = LLMClient(provider=provider, api_key=api_key,
                            model=cfg.get_model(provider_name))
        except Exception as e:
            return f"Couldn't initialise an AI client: {e}"

    return llm.generate_text(
        full_prompt,
        _PLOT_AI_SYSTEM,
        max_tokens=1500,
        temperature=0.5,
        conversation_history=history,
    )


class CollapsibleSection(QWidget):
    """A collapsible section widget with a toggle button."""

    def __init__(self, title: str = "", parent=None):
        """Initialize collapsible section."""
        super().__init__(parent)
        self.is_collapsed = False

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header with toggle button
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }
            QFrame:hover {
                background-color: #e5e7eb;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 4, 8, 4)

        # Toggle button
        self.toggle_btn = QToolButton()
        self.toggle_btn.setStyleSheet("QToolButton { border: none; background: transparent; }")
        self.toggle_btn.setText("▼")
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle)
        header_layout.addWidget(self.toggle_btn)

        # Title label
        self.title_label = QLabel(title)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self.title_label.setFont(font)
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        main_layout.addWidget(header_frame)

        # Content area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 8, 0, 8)

        main_layout.addWidget(self.content_widget)

    def toggle(self):
        """Toggle the collapsed state."""
        self.is_collapsed = not self.is_collapsed

        if self.is_collapsed:
            self.toggle_btn.setText("▶")
            self.content_widget.hide()
        else:
            self.toggle_btn.setText("▼")
            self.content_widget.show()

    def set_title(self, title: str):
        """Set the section title."""
        self.title_label.setText(title)

    def add_widget(self, widget: QWidget):
        """Add a widget to the content area."""
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        """Add a layout to the content area."""
        self.content_layout.addLayout(layout)


class SubplotEditor(QDialog):
    """Dialog for editing a subplot."""

    def __init__(self, subplot: Subplot = None, parent=None):
        """Initialize subplot editor."""
        super().__init__(parent)
        self.subplot = subplot or Subplot(
            id="",
            title="",
            description="",
            connection_to_main="",
            related_characters=[],
            events=[],
            status="active"
        )
        self._init_ui()
        if subplot:
            self._load_subplot()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Subplot Editor")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        main_layout = QVBoxLayout(self)

        # Create scroll area for form content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Subplot title")
        form_layout.addRow("Title:*", self.title_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Describe this subplot...")
        self.description_edit.setMaximumHeight(100)
        form_layout.addRow("Description:", self.description_edit)

        self.connection_edit = QTextEdit()
        self.connection_edit.setPlaceholderText("How does this subplot connect to the main plot?")
        self.connection_edit.setMaximumHeight(80)
        form_layout.addRow("Connection to Main Plot:", self.connection_edit)

        self.characters_edit = QTextEdit()
        self.characters_edit.setPlaceholderText("Character names (one per line)")
        self.characters_edit.setMaximumHeight(80)
        form_layout.addRow("Related Characters:", self.characters_edit)

        # Set form widget to scroll area
        scroll_area.setWidget(form_widget)
        main_layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _load_subplot(self):
        """Load subplot data."""
        self.title_edit.setText(self.subplot.title)
        self.description_edit.setPlainText(self.subplot.description)
        self.connection_edit.setPlainText(self.subplot.connection_to_main)

        if self.subplot.related_characters:
            self.characters_edit.setPlainText("\n".join(self.subplot.related_characters))

    def _save(self):
        """Save subplot."""
        title = self.title_edit.text().strip()
        if not title:
            return

        if not self.subplot.id:
            import uuid
            self.subplot.id = str(uuid.uuid4())

        self.subplot.title = title
        self.subplot.description = self.description_edit.toPlainText().strip()
        self.subplot.connection_to_main = self.connection_edit.toPlainText().strip()

        char_text = self.characters_edit.toPlainText().strip()
        self.subplot.related_characters = [c.strip() for c in char_text.split("\n") if c.strip()]

        self.accept()

    def get_subplot(self) -> Subplot:
        """Get the edited subplot."""
        return self.subplot


class PlotManagerWidget(QWidget):
    """Widget for managing plot structure with events and subplots."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize plot manager."""
        super().__init__()
        self.freytag_pyramid = FreytagPyramid()
        self.subplots: List[Subplot] = []
        self.promises: List[StoryPromise] = []
        self.tensions: List[CharacterTension] = []
        self.themes: List[Theme] = []   # rich themes (theme_details)
        self.legacy_themes: List[str] = []  # bare-string themes for
                                           # backwards compat with
                                           # older projects
        self.available_characters: List[str] = []
        # Discuss-with-AI tab. ``_ai_context_provider`` is a callable
        # injected by main_window that returns a dict with manuscript
        # and worldbuilding context the AI needs for plot discussion;
        # ``None`` means the host hasn't wired it yet, in which case
        # the tab still renders but warns the user before asking.
        self._ai_context_provider = None
        # ``_ai_create_callback`` is a host-supplied callable taking
        # (kind: str, data: dict) -> bool that creates a project
        # element when the user clicks "Add" on a suggestion card.
        # Falls back to a no-op when the host hasn't wired it.
        self._ai_create_callback = None
        self._ai_history: List[dict] = []  # [{role, content, ?suggestions}]
        # Compacted summary of older turns dropped from _ai_history
        # by the sliding-window trimmer. Folded into the prompt as
        # the ``history_summary`` field so the model can still refer
        # back to early discussion without re-sending every turn.
        self._ai_history_summary: str = ""
        # Transient transcript widgets — Thinking… / error notes that
        # live below the rendered turns until the next refresh.
        self._ai_transient_widgets: List[QWidget] = []
        self._ai_busy = False
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Content widget inside scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Visual pyramid at top - collapsible
        pyramid_section = CollapsibleSection("📊 Freytag's Pyramid")

        # Act configuration controls
        act_config_layout = QHBoxLayout()
        act_config_layout.addWidget(QLabel("Acts:"))

        self.num_acts_spin = QSpinBox()
        self.num_acts_spin.setMinimum(1)
        self.num_acts_spin.setMaximum(7)
        self.num_acts_spin.setValue(3)
        self.num_acts_spin.setToolTip("Number of acts in your story structure")
        self.num_acts_spin.valueChanged.connect(self._on_num_acts_changed)
        act_config_layout.addWidget(self.num_acts_spin)

        act_config_layout.addSpacing(20)

        edit_acts_btn = QPushButton("✏️ Edit Act Names")
        edit_acts_btn.clicked.connect(self._edit_act_names)
        act_config_layout.addWidget(edit_acts_btn)

        act_config_layout.addStretch()

        act_config_widget = QWidget()
        act_config_widget.setLayout(act_config_layout)
        pyramid_section.add_widget(act_config_widget)

        self.pyramid_visual = FreytagPyramidVisual()
        self.pyramid_visual.event_clicked.connect(self._on_pyramid_event_clicked)
        pyramid_section.add_widget(self.pyramid_visual)

        layout.addWidget(pyramid_section)

        # Tabs for events and subplots
        tabs = QTabWidget()

        # Events tab
        events_tab = self._create_events_tab()
        tabs.addTab(events_tab, "📍 Plot Events")

        # Subplots tab
        subplots_tab = self._create_subplots_tab()
        tabs.addTab(subplots_tab, "🔀 Subplots")

        # Promises tab
        promises_tab = self._create_promises_tab()
        tabs.addTab(promises_tab, "🤝 Promises")

        # Tensions tab — sustained dramatic forces shaping the plot.
        # Surfaces in the AI context so plot discussion / next-beat
        # suggestions weigh which pressures are escalating.
        tensions_tab = self._create_tensions_tab()
        tabs.addTab(tensions_tab, "⚡ Tensions")

        # Themes tab — what the story is *about* underneath its
        # events. Surfaces in the AI context so plot discussion can
        # check whether beats reinforce or undercut the themes.
        themes_tab = self._create_themes_tab()
        tabs.addTab(themes_tab, "🎯 Themes")

        # Discuss-with-AI tab — pulls manuscript + worldbuilding from
        # the host (main_window) and routes through the per-task
        # ``model_for_plot`` LLM.
        ai_tab = self._create_ai_tab()
        self._ai_tab_index = tabs.addTab(ai_tab, "💬 Discuss with AI")
        # Refresh the context-status banner every time the user opens
        # the AI tab. The initial pre-flight at construction-time runs
        # before any project is loaded, so without this hook the
        # banner would stay stuck on "empty" until the user manually
        # clicked Refresh.
        self._ai_tabs_widget = tabs
        tabs.currentChanged.connect(self._on_plot_tab_changed)

        layout.addWidget(tabs)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _create_events_tab(self) -> QWidget:
        """Create events management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Plot Events")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Manage key events in your story's dramatic structure")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_btn = QPushButton("➕ Add Event")
        add_btn.clicked.connect(self._add_event)
        toolbar.addWidget(add_btn)

        self.edit_event_btn = QPushButton("✏️ Edit")
        self.edit_event_btn.clicked.connect(self._edit_event)
        self.edit_event_btn.setEnabled(False)
        toolbar.addWidget(self.edit_event_btn)

        self.remove_event_btn = QPushButton("🗑️ Remove")
        self.remove_event_btn.clicked.connect(self._remove_event)
        self.remove_event_btn.setEnabled(False)
        toolbar.addWidget(self.remove_event_btn)

        toolbar.addSeparator = QFrame()
        toolbar.addSeparator.setFrameShape(QFrame.Shape.VLine)
        toolbar.addWidget(toolbar.addSeparator)

        self.move_event_up_btn = QPushButton("⬆ Move Up")
        self.move_event_up_btn.clicked.connect(self._move_event_up)
        self.move_event_up_btn.setEnabled(False)
        toolbar.addWidget(self.move_event_up_btn)

        self.move_event_down_btn = QPushButton("⬇ Move Down")
        self.move_event_down_btn.clicked.connect(self._move_event_down)
        self.move_event_down_btn.setEnabled(False)
        toolbar.addWidget(self.move_event_down_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Event list
        self.event_list = QListWidget()
        self.event_list.itemSelectionChanged.connect(self._on_event_selection_changed)
        self.event_list.itemDoubleClicked.connect(self._on_event_list_double_clicked)
        layout.addWidget(self.event_list)

        return widget

    def _create_subplots_tab(self) -> QWidget:
        """Create subplots management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Subplots")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Secondary storylines tied to the main plot")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_subplot_btn = QPushButton("➕ Add Subplot")
        add_subplot_btn.clicked.connect(self._add_subplot)
        toolbar.addWidget(add_subplot_btn)

        self.edit_subplot_btn = QPushButton("✏️ Edit")
        self.edit_subplot_btn.clicked.connect(self._edit_subplot)
        self.edit_subplot_btn.setEnabled(False)
        toolbar.addWidget(self.edit_subplot_btn)

        self.remove_subplot_btn = QPushButton("🗑️ Remove")
        self.remove_subplot_btn.clicked.connect(self._remove_subplot)
        self.remove_subplot_btn.setEnabled(False)
        toolbar.addWidget(self.remove_subplot_btn)

        toolbar_separator = QFrame()
        toolbar_separator.setFrameShape(QFrame.Shape.VLine)
        toolbar.addWidget(toolbar_separator)

        self.move_subplot_up_btn = QPushButton("⬆ Move Up")
        self.move_subplot_up_btn.clicked.connect(self._move_subplot_up)
        self.move_subplot_up_btn.setEnabled(False)
        toolbar.addWidget(self.move_subplot_up_btn)

        self.move_subplot_down_btn = QPushButton("⬇ Move Down")
        self.move_subplot_down_btn.clicked.connect(self._move_subplot_down)
        self.move_subplot_down_btn.setEnabled(False)
        toolbar.addWidget(self.move_subplot_down_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Subplot list
        self.subplot_list = QListWidget()
        self.subplot_list.itemSelectionChanged.connect(self._on_subplot_selection_changed)
        self.subplot_list.itemDoubleClicked.connect(self._edit_subplot)
        layout.addWidget(self.subplot_list)

        return widget

    def _create_promises_tab(self) -> QWidget:
        """Create promises management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Header
        header = QHBoxLayout()
        title = QLabel("Story Promises")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        help_text = QLabel("Commitments to readers about tone, plot, genre, and characters")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        add_promise_btn = QPushButton("➕ Add Promise")
        add_promise_btn.clicked.connect(self._add_promise)
        toolbar.addWidget(add_promise_btn)

        self.edit_promise_btn = QPushButton("✏️ Edit")
        self.edit_promise_btn.clicked.connect(self._edit_promise)
        self.edit_promise_btn.setEnabled(False)
        toolbar.addWidget(self.edit_promise_btn)

        self.remove_promise_btn = QPushButton("🗑️ Remove")
        self.remove_promise_btn.clicked.connect(self._remove_promise)
        self.remove_promise_btn.setEnabled(False)
        toolbar.addWidget(self.remove_promise_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Promise type sections
        promise_sections_widget = QWidget()
        promise_sections_layout = QVBoxLayout(promise_sections_widget)
        promise_sections_layout.setContentsMargins(0, 0, 0, 0)

        # Info labels about each type
        type_info = QLabel(
            "<b>Types of promises:</b><br/>"
            "• <b>Tone</b> - Emotional atmosphere (dark, humorous, hopeful)<br/>"
            "• <b>Plot</b> - Story structure expectations (mystery solved, hero wins)<br/>"
            "• <b>Genre</b> - Genre conventions (romance will bloom, justice served)<br/>"
            "• <b>Character</b> - Character arcs and consistency (growth, motivations)"
        )
        type_info.setWordWrap(True)
        type_info.setStyleSheet("background-color: #f3f4f6; padding: 10px; border-radius: 6px; font-size: 11px;")
        promise_sections_layout.addWidget(type_info)

        layout.addWidget(promise_sections_widget)

        # Promise list
        self.promise_list = QListWidget()
        self.promise_list.itemSelectionChanged.connect(self._on_promise_selection_changed)
        self.promise_list.itemDoubleClicked.connect(self._edit_promise)
        layout.addWidget(self.promise_list)

        return widget

    def _create_ai_tab(self) -> QWidget:
        """Create the Discuss-with-AI tab.

        Compact layout for laptop-class screens:
          1. One-line top strip — title + context status + the
             Help / Refresh / Preview buttons all on a single row.
          2. Splitter holding the transcript (top, larger by default)
             and the input area + send buttons (bottom). The user
             can drag to give either side more room.
          3. Quick prompts collapsed into one menu button so a row
             of five buttons doesn't burn vertical space.

        Live context (manuscript, worldbuilding, plot map) is fetched
        lazily from ``self._ai_context_provider`` at ask-time so the
        AI always sees the latest state regardless of which tab the
        user has been editing in.
        """
        from PyQt6.QtWidgets import QMenu, QSplitter
        from PyQt6.QtGui import QAction

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Compact top strip ─────────────────────────────────
        # Title + context status share a row so on a laptop the
        # transcript starts ~40px earlier than it used to.
        top_strip = QHBoxLayout()
        top_strip.setSpacing(8)
        title = QLabel("💬 Plot AI")
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        top_strip.addWidget(title)
        # Right-side: prompts menu, context preview, refresh, help
        top_strip.addStretch()

        # All four chrome buttons share one short style so they line
        # up visually. We use plain QPushButtons (not QToolButton)
        # because QToolButton in InstantPopup mode auto-draws a
        # menu-indicator arrow that ends up looking like a separate
        # empty button next to our label — replacing it with a
        # QPushButton + manually-opened menu avoids that.
        # ``color`` MUST be set in the default state, not just :hover —
        # otherwise the text inherits the system theme colour, which
        # on dark themes ends up white-on-our-white-background and the
        # label looks invisible until the user hovers.
        small_btn_style = (
            "QPushButton { padding: 3px 10px; font-size: 11px; "
            "  border: 1px solid #d1d5db; border-radius: 4px; "
            "  background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6366f1; "
            "  color: #6366f1; }")

        prompts_menu_btn = QPushButton("Quick prompts ▼")
        prompts_menu_btn.setStyleSheet(small_btn_style)
        prompts_menu_btn.setToolTip(
            "Open a menu of pre-written plot prompts (plot-hole "
            "audit, pacing check, what-next options, promise audit, "
            "arc check). Picks drop into the input box for editing "
            "before you hit Ask.")
        prompts_menu = QMenu(prompts_menu_btn)
        for label, prompt in self._ai_quick_prompt_defs():
            act = QAction(label, prompts_menu)
            act.triggered.connect(
                lambda _checked=False, p=prompt:
                    self._ai_input.setPlainText(p))
            prompts_menu.addAction(act)
        # Manual popup — opens the menu immediately under the button
        # so behaviour matches the dropdown affordance the ▼ glyph
        # implies.
        prompts_menu_btn.clicked.connect(
            lambda: prompts_menu.exec(
                prompts_menu_btn.mapToGlobal(
                    prompts_menu_btn.rect().bottomLeft())))
        top_strip.addWidget(prompts_menu_btn)

        # ``Preview`` was previously prefixed with the eye emoji
        # (U+1F441) which renders as a tofu box on systems without
        # a colour-emoji font. Plain text is more reliable; the
        # tooltip says exactly what it does.
        preview_ctx_btn = QPushButton("Preview context")
        preview_ctx_btn.setStyleSheet(small_btn_style)
        preview_ctx_btn.setToolTip(
            "Open a popup showing the exact context the AI will "
            "receive on your next ask — manuscript excerpts, plot "
            "map, characters, worldbuilding. Useful for sanity-"
            "checking what the model can actually see.")
        preview_ctx_btn.clicked.connect(self._show_ai_context_preview)
        top_strip.addWidget(preview_ctx_btn)

        # ``Refresh`` was previously bare ⟳ which can fail to render
        # on systems missing the right Symbol font. Use a label that
        # always renders.
        refresh_ctx_btn = QPushButton("Refresh")
        refresh_ctx_btn.setStyleSheet(small_btn_style)
        refresh_ctx_btn.setToolTip(
            "Re-check the project state and update the context "
            "summary. Use this after you've added chapters, plot "
            "events, or characters in another tab so the AI sees "
            "the latest version.")
        refresh_ctx_btn.clicked.connect(
            self._refresh_ai_context_status)
        top_strip.addWidget(refresh_ctx_btn)

        help_btn = QPushButton("Help")
        help_btn.setStyleSheet(small_btn_style)
        help_btn.setToolTip(
            "Plot AI scope:\n"
            "• Discusses plot beats, pacing, story promises, "
            "character arcs.\n"
            "• Sees the current chapter, plot map, characters, "
            "worldbuilding.\n"
            "• Routes through your plot-task model "
            "(Settings → CreativeOS → Plot).\n\n"
            "Doesn't write manuscript prose — that's Writer mode.")
        top_strip.addWidget(help_btn)
        layout.addLayout(top_strip)

        # ── Context status (one line) ─────────────────────────
        # Stays separate from the title strip because its text is
        # dynamic and can grow longer ("Context: ready — 12
        # chapters · 8k chars excerpts · plot map ✓ · …").
        self._ai_ctx_label = QLabel("Context: not yet checked.")
        self._ai_ctx_label.setStyleSheet(
            "color:#6b7280;font-size:11px;"
            "padding:2px 4px;")
        self._ai_ctx_label.setWordWrap(True)
        layout.addWidget(self._ai_ctx_label)

        # ── Splitter: transcript (top) + input (bottom) ──────
        # User can drag the handle to give either side more room
        # — important on laptops where the default split might
        # leave too little room for whichever section the user is
        # focused on.
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        # Transcript — scrollable column of turn widgets so we can
        # embed clickable suggestion cards alongside plain text bubbles.
        self._ai_transcript_scroll = QScrollArea()
        self._ai_transcript_scroll.setWidgetResizable(True)
        self._ai_transcript_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #e5e7eb; "
            "background-color: #fafafa; border-radius: 6px; }")
        self._ai_transcript_inner = QWidget()
        self._ai_transcript_layout = QVBoxLayout(
            self._ai_transcript_inner)
        self._ai_transcript_layout.setContentsMargins(8, 8, 8, 8)
        self._ai_transcript_layout.setSpacing(6)
        self._ai_transcript_layout.addStretch(1)
        self._ai_transcript_placeholder = QLabel(
            "Conversation will appear here.")
        self._ai_transcript_placeholder.setStyleSheet(
            "color: #9ca3af; font-style: italic; padding: 12px;")
        self._ai_transcript_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._ai_transcript_layout.insertWidget(
            0, self._ai_transcript_placeholder)
        self._ai_transcript_scroll.setWidget(
            self._ai_transcript_inner)
        splitter.addWidget(self._ai_transcript_scroll)

        # Input area — text box on top, button row underneath.
        # Stacking buttons under the input (not beside it) gives
        # the input full width even when the panel is narrow.
        # The whole block is wrapped so it can be hidden via the
        # chat-collapse toggle; when hidden, the transcript takes
        # the full splitter height.
        self._ai_input_block = QWidget()
        input_v = QVBoxLayout(self._ai_input_block)
        input_v.setContentsMargins(0, 0, 0, 0)
        input_v.setSpacing(4)

        # Slim header strip at the top of the input block — gives
        # the user a discoverable "hide chat input" toggle distinct
        # from dragging the splitter handle (which feels accidental
        # to users who don't know splitters can resize).
        chat_strip = QHBoxLayout()
        chat_strip.setContentsMargins(0, 0, 0, 0)
        chat_strip.setSpacing(4)
        self._ai_chat_toggle_btn = QPushButton("▼  Chat input")
        self._ai_chat_toggle_btn.setStyleSheet(
            "QPushButton { padding: 1px 8px; font-size: 10px; "
            " color: #6b7280; border: none; "
            " background: transparent; text-align: left; }"
            "QPushButton:hover { color: #2563eb; }")
        self._ai_chat_toggle_btn.setToolTip(
            "Collapse the chat input area to give the transcript "
            "more room. Click again to bring it back.")
        self._ai_chat_toggle_btn.clicked.connect(
            self._toggle_ai_chat_input)
        chat_strip.addWidget(self._ai_chat_toggle_btn)
        chat_strip.addStretch()
        input_v.addLayout(chat_strip)

        # Inner panel that actually gets hidden — keeping the
        # toggle button always visible so the user can re-expand.
        self._ai_input_inner = QWidget()
        inner_v = QVBoxLayout(self._ai_input_inner)
        inner_v.setContentsMargins(0, 0, 0, 0)
        inner_v.setSpacing(4)

        self._ai_input = QTextEdit()
        self._ai_input.setMinimumHeight(60)
        self._ai_input.setPlaceholderText(
            "Ask about plot, structure, pacing, promises…")
        inner_v.addWidget(self._ai_input, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch()
        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setStyleSheet(
            "QPushButton { padding: 4px 14px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; "
            " color: #1f2937; }")
        clear_btn.setToolTip("Clear the conversation transcript and history.")
        clear_btn.clicked.connect(self._on_ai_clear)
        btn_row.addWidget(clear_btn)

        self._ai_ask_btn = QPushButton("💬 Ask  ⏎")
        self._ai_ask_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            " padding: 5px 18px; border-radius: 4px; "
            " font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:disabled { background-color: #93c5fd; }")
        self._ai_ask_btn.setDefault(True)
        self._ai_ask_btn.clicked.connect(self._on_ai_ask)
        btn_row.addWidget(self._ai_ask_btn)
        inner_v.addLayout(btn_row)
        input_v.addWidget(self._ai_input_inner, stretch=1)

        splitter.addWidget(self._ai_input_block)
        # Default split: 75% transcript, 25% input. Splitter
        # respects the relative sizes via setSizes after show.
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 100])
        self._ai_splitter = splitter
        layout.addWidget(splitter, stretch=1)

        # Restore prior chat-input collapse state. Default: expanded.
        self._ai_collapse_settings = QSettings(
            "WritingAid", "PlotAITab")
        if self._ai_collapse_settings.value(
                "chatInputCollapsed", False, type=bool):
            self._toggle_ai_chat_input()

        return widget

    def _toggle_ai_chat_input(self):
        """Hide / show the chat input area while keeping the
        toggle button visible so the user can re-expand.

        Tracks state in ``_ai_chat_input_collapsed`` rather than via
        ``isVisible()`` because Qt's visibility check is contingent
        on the widget being shown — at construction time (when we
        restore the collapsed state from QSettings) the widget tree
        hasn't been mapped yet and ``isVisible()`` always returns
        False, which would make the toggle a no-op.
        """
        if not hasattr(self, '_ai_input_inner'):
            return
        new_collapsed = not getattr(
            self, '_ai_chat_input_collapsed', False)
        self._ai_chat_input_collapsed = new_collapsed
        self._ai_input_inner.setVisible(not new_collapsed)
        if new_collapsed:
            self._ai_chat_toggle_btn.setText(
                "▶  Chat input  (hidden)")
            if hasattr(self, '_ai_splitter'):
                sizes = self._ai_splitter.sizes()
                total = sum(sizes) or 400
                self._ai_splitter.setSizes([total - 30, 30])
        else:
            self._ai_chat_toggle_btn.setText("▼  Chat input")
            if hasattr(self, '_ai_splitter'):
                total = sum(self._ai_splitter.sizes()) or 400
                self._ai_splitter.setSizes(
                    [int(total * 0.75), int(total * 0.25)])
        if hasattr(self, '_ai_collapse_settings'):
            try:
                self._ai_collapse_settings.setValue(
                    "chatInputCollapsed", new_collapsed)
            except Exception:
                pass

    @staticmethod
    def _ai_quick_prompt_defs():
        """Return the (label, full_prompt) tuples for the quick-prompt
        menu. Defined once so the menu builder + any future surface
        (e.g. the General Assistant) can reuse them."""
        return (
            ("Spot plot holes",
             "Audit the existing manuscript against the plot map for "
             "structural problems. Cite each issue as 'Ch N: Title — "
             "<one-line problem>' and give a one-line fix. Group as: "
             "**Plot holes** (events that don't follow), **Broken "
             "promises** (setups never paid off), **Arc breaks** "
             "(character behaviour that contradicts profile/prior "
             "scenes). If a category is clean, say so in one line — "
             "don't invent issues."),
            ("Pacing check",
             "Build a pacing read of the manuscript. For each existing "
             "chapter, output one line: 'Ch N: Title — <fast | "
             "steady | slow | drags | rushes> — <one-sentence "
             "reason citing what's on the page>'. Then end with: "
             "**Where to cut**, **Where to expand**, **Smooth move**: "
             "each one chapter and one sentence. Refuse to comment on "
             "chapters not in the manuscript."),
            ("What should happen next?",
             "Based on what's been written and the plot map's intended "
             "structure, give me 3 numbered options for the next beat "
             "or chapter. Each option must have: a one-line summary, "
             "the chapter or act it lands in, which plot event/promise "
             "it advances or pays off, and **What it costs** (tone "
             "shift, pacing impact, promise affected). Don't pick — "
             "I will."),
            ("Promise audit",
             "For EACH story promise in the plot map, output: "
             "'**[type] Title** — Setup: <Ch N where introduced or "
             "‘not set up yet’> — Payoff: <Ch N where resolved or "
             "‘unresolved’> — Status: <on track | at risk | broken "
             "| paid>'. After the list, give one paragraph on the "
             "biggest risk and what to do about it. If there are no "
             "promises in the map, say so and recommend 2-3 the "
             "manuscript already implies."),
            ("Character arc check",
             "For each major character (look at CHARACTERS context), "
             "output: '**Name** — Starting state: <Ch N> — Current "
             "state: <Ch N> — Trajectory: <progressing | stalled | "
             "regressing | unclear> — Next beat needed: <one line>'. "
             "Skip minor characters. Cite the chapters where the "
             "state shows up; don't invent."),
            ("Subplot weave",
             "Audit how each subplot in the SUBPLOTS context block is "
             "woven into the main plot. For EACH subplot output: "
             "'**Title** (status) — Last appearance: <Ch N or ‘not "
             "yet on the page’> — Connection to main: <one line> — "
             "Weave health: <strong | thin | dropped | tangled> — "
             "What it needs next: <one line>'. End with one line on "
             "which subplot is most at risk of being forgotten and "
             "the chapter where it should re-surface. If there are no "
             "subplots in the map, suggest 2-3 the manuscript already "
             "implies."),
            ("Tension pressure read",
             "Walk through each tension in the STORY TENSIONS block "
             "and rate how present it FEELS in the manuscript right "
             "now. For EACH tension output: '**Title** [type] — "
             "Stated state: <from plot map> — Felt pressure: <high | "
             "medium | low | absent> — Last scene that put weight on "
             "it: <Ch N or ‘never on the page’> — One-line fix to "
             "raise pressure'. End with which tension is most "
             "underweight and the chapter to fix it in. If there are "
             "no tensions in the map, name 2-3 the manuscript "
             "implies."),
            ("Propose next chapter",
             "Look at the manuscript chapters list, the plot map, "
             "and any open tensions / promises / subplots. Propose "
             "the NEXT chapter that should be written. In prose, "
             "first explain: which subplot or plot beat it advances, "
             "which tensions it puts pressure on, which promise (if "
             "any) it sets up or pays off, who carries the POV and "
             "why, and how it should END to hook the chapter after "
             "it. Then emit a <suggest_chapter> block with the full "
             "plot plan filled in (synopsis, goal, pov_character, "
             "scene_list with 3-5 scenes, characters_featured, "
             "locations, themes, tone, voice, style, pacing, "
             "timeline_position) so I can add it with one click "
             "and drop into Writer mode."),
            ("Define tensions with me",
             "Look at the CHARACTERS context block and the manuscript "
             "excerpts. Propose 2-3 sustained tensions this story "
             "should be running, each tied to specific characters "
             "from the CHARACTERS list (use their actual names — do "
             "not invent characters). For EACH tension propose, "
             "describe in prose what the tension is, who it presses "
             "on, what's at stake, and which chapter / scene first "
             "puts it on the page. Then emit a <suggest_tension> "
             "block with the JSON so I can add it with one click. "
             "Cap at TWO suggest_tension blocks per reply; the "
             "third tension goes in prose only so I can refine it "
             "before you formalise it."),
            ("Themes pulse",
             "For EACH theme in the STORY THEMES context block, "
             "output: '**Title** — Statement: <from the plot map> "
             "— Where it's landing: <Ch N: ‘scene that proves it’> "
             "— Where it's drifting: <Ch N: ‘scene that contradicts "
             "it’ or ‘never on the page’> — One-line beat to "
             "reinforce it'. End with which theme is most "
             "underweight in the manuscript and the chapter to fix "
             "it in. If there are no themes (or only legacy bare "
             "labels), use the manuscript + characters to PROPOSE "
             "2-3 themes the book is implicitly making — emit a "
             "<suggest_theme> block for the first one so I can "
             "formalise it."),
        )

    def set_ai_context_provider(self, provider):
        """Plug in a host-supplied callback that returns AI context.

        The host (main_window) calls this once with a callable that
        takes no args and returns a dict with at minimum:
        ``manuscript_summary`` (str), ``current_chapter`` (str|None),
        ``worldbuilding`` (str), ``characters`` (str), ``project_name``
        (str). Used so the plot tab doesn't need a back-reference to
        the project / manuscript editor — the host owns those.
        """
        self._ai_context_provider = provider
        # First read so the user sees status without having to click
        # Refresh. Safe even when a project hasn't loaded yet — the
        # provider just returns an empty-ish dict.
        try:
            self._refresh_ai_context_status()
        except Exception:
            pass

    def set_ai_create_callback(self, callback):
        """Plug in a host-supplied creator for AI suggestions.

        Signature: ``callback(kind: str, data: dict) -> bool``. Called
        when the user clicks "Add to project" on a suggestion card.
        ``kind`` is one of ``character`` / ``place`` / ``faction`` /
        ``culture`` / ``chapter`` (matches the suggest tag names).
        ``data`` is the JSON object the AI emitted. Return True on
        success so the card can flip to "✓ Added".

        The host (main_window) typically routes each kind to the same
        create handler the General Assistant chat uses for its own
        ``<create_*>`` blocks.
        """
        self._ai_create_callback = callback

    def refresh_ai_status(self):
        """Public hook the host (main_window) calls after a project
        loads / reloads / restores. Without this the AI tab's
        context-status banner would stay stuck on whatever it showed
        at construction time (typically 'empty', because the chat
        widget is built before any project is open)."""
        try:
            self._refresh_ai_context_status()
        except Exception as e:
            print(f"[plot-ai] refresh_ai_status raised: {e}")

    def _on_plot_tab_changed(self, idx: int):
        """Refresh AI context when the user opens the AI sub-tab."""
        if (hasattr(self, '_ai_tab_index')
                and idx == self._ai_tab_index):
            try:
                self._refresh_ai_context_status()
            except Exception as e:
                print(f"[plot-ai] tab-change refresh raised: {e}")

    def _gather_ai_context(self, question: str = "") -> dict:
        """Pull the current context dict from the host provider.

        ``question`` is forwarded to the provider so the host's RAG
        layer can pick the most relevant characters / worldbuilding /
        chapter excerpts for THIS question, instead of dumping
        everything. Providers that don't accept the kwarg fall back
        to a no-arg call so older wiring keeps working.
        """
        if self._ai_context_provider is None:
            return {}
        try:
            try:
                return self._ai_context_provider(question=question) or {}
            except TypeError:
                # Older provider signature: no kwargs.
                return self._ai_context_provider() or {}
        except Exception as e:
            print(f"[plot-ai] context provider raised: {e}")
            return {}

    def _summarise_ai_context(self, ctx: dict) -> tuple:
        """Return ``(label_html, ok_to_send)`` describing the context.

        ``ok_to_send`` is False when the context is so thin the AI has
        nothing to work with — in that case the Ask button is disabled
        and the label nudges the user.
        """
        if self._ai_context_provider is None:
            return ("Context: <i>no project loaded</i>.", False)
        # Count what's actually present.
        chapters_n = len(
            (ctx.get('manuscript_index') or '').strip().splitlines())
        plot_map_n = len((ctx.get('plot_map') or '').strip())
        chars_n = len((ctx.get('characters') or '').strip())
        wb_n = len((ctx.get('worldbuilding') or '').strip())
        plot_summary_n = len((ctx.get('plot_summary') or '').strip())
        current_ch = ctx.get('current_chapter_title')
        excerpts_n = len(
            (ctx.get('chapter_excerpts') or '').strip())

        bits = []
        if chapters_n:
            bits.append(f"{chapters_n} chapter"
                        f"{'s' if chapters_n != 1 else ''}")
        if excerpts_n >= 1000:
            bits.append(f"~{excerpts_n // 1000}k chars excerpts")
        elif excerpts_n:
            bits.append(f"{excerpts_n} chars excerpts")
        if plot_map_n:
            bits.append("plot map ✓")
        if plot_summary_n and not plot_map_n:
            bits.append("plot summary only")
        if chars_n:
            bits.append("characters ✓")
        if wb_n:
            bits.append("world ✓")
        if current_ch:
            bits.append(f"open: {current_ch[:30]}")

        # Pre-flight: if neither the manuscript nor any plot map is
        # present, the AI literally has nothing of THIS project to
        # cite. Better to nudge the user than let it hallucinate.
        ok = (chapters_n > 0 or plot_map_n > 0
              or plot_summary_n > 0 or chars_n > 0)
        if not bits:
            return (
                "Context: <span style='color:#b91c1c;'>empty</span> — "
                "add a plot event, write a chapter, or fill in the "
                "Freytag pyramid first.",
                False,
            )
        prefix = ("Context: <span style='color:#15803d;'>ready</span>"
                  if ok
                  else "Context: <span style='color:#b91c1c;'>thin"
                       "</span>")
        return (f"{prefix} — " + " · ".join(bits), ok)

    def _refresh_ai_context_status(self, *_):
        """Update the status label.

        Note: this no longer hard-disables the Ask button when the
        pre-flight says context is empty. Pre-flight ran on cached
        provider state and may be stale (e.g. the user just loaded a
        project). The Ask click path re-checks before sending, so
        stale empty-status no longer blocks valid asks. We only
        disable while a request is in flight, which is the only true
        'cannot ask now' state.
        """
        ctx = self._gather_ai_context()
        label_html, _ok = self._summarise_ai_context(ctx)
        self._ai_ctx_label.setText(label_html)
        if hasattr(self, '_ai_ask_btn'):
            self._ai_ask_btn.setEnabled(not self._ai_busy)

    def _show_ai_context_preview(self):
        """Pop up the full assembled context the AI will see.

        Honours the current input — if the user has typed a
        question, we pass it as the RAG query so the preview shows
        the actual focused-per-question context (not the empty-
        question fallback). The preview is a tabbed dialog: User
        block / System prompt / RAG breakdown / History.
        """
        question = ""
        if hasattr(self, '_ai_input'):
            question = self._ai_input.toPlainText().strip()
        # Use the typed question (if any) so RAG fires and the
        # rag_focused_* keys actually populate. Without a question
        # the provider returns no RAG output and the preview is
        # misleading.
        ctx = self._gather_ai_context(question)
        if not ctx:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Plot AI context",
                "No context available. Open a project first.")
            return
        # Build the user-block exactly as _ask_plot_ai does — same
        # question (or a placeholder when the input is empty), same
        # context, same per-section budgets — so the preview is
        # byte-accurate.
        preview_question = question or "<your question here>"
        try:
            user_block = _build_plot_ai_user_block(
                preview_question, ctx)
        except Exception as e:
            user_block = f"(could not assemble preview: {e})"
        # Inject any history summary captured by compaction so the
        # preview reflects what the worker would actually send.
        history = list(getattr(self, '_ai_history', []) or [])
        # Pull the RAG breakdown out of the context dict for its
        # own dialog tab.
        from src.ui.context_preview_dialog import (
            show_context_preview, build_rag_summary,
        )
        rag_summary = build_rag_summary(ctx)
        intro = (
            "This is exactly what the AI will see when you click "
            "Ask. The user-block reflects your current input — if "
            "you change the input, click Preview again to refresh."
            if question else
            "Type a question in the input box and click Preview "
            "again to see RAG-selected context for that specific "
            "question. The preview below uses a placeholder.")
        show_context_preview(
            self,
            title="Plot AI — context preview",
            intro=intro,
            system_prompt=_PLOT_AI_SYSTEM,
            user_block=user_block,
            rag_summary=rag_summary,
            conversation_history=history)

    def _on_ai_clear(self):
        """Reset the transcript + history."""
        self._ai_history = []
        self._ai_history_summary = ""
        self._ai_render_history()

    # ── Training-data capture ────────────────────────────────
    # When the user signals a turn was useful (clicked Add on a
    # suggestion, or rated Excellent / Good) we log the
    # input/output pair into the rephrase DB under the plot
    # source-type so the Training Studio picks it up next round.
    # Gated by ``enable_plot_data_collection`` in CreativeOS settings.

    def _capture_plot_turn(self, history_entry: dict,
                            rating: str = "good") -> None:
        """Persist this turn as plot training data at ``rating``.

        First positive signal logs a fresh row and stamps
        ``_db_row_id`` on the entry; later signals call
        ``update_rating`` instead so a single turn never produces
        duplicate training rows. The function is best-effort — any
        DB failure is swallowed so a logging hiccup never breaks
        the chat flow.
        """
        if rating not in ("excellent", "good"):
            # We deliberately don't capture neutral / poor / bad —
            # the user asked for "good and excellent ratings" only.
            return
        prompt = (history_entry.get("prompt") or "").strip()
        completion = (history_entry.get("content") or "").strip()
        if not prompt or not completion:
            return
        # Opt-in gate. If the user hasn't enabled plot data
        # collection, nothing leaves this method.
        try:
            from src.config.creativeos_config import get_creativeos_config
            if not get_creativeos_config().get(
                    "enable_plot_data_collection", False):
                return
        except Exception:
            return
        try:
            from src.data.rephrase_database import get_rephrase_database
            db = get_rephrase_database()
            row_id = history_entry.get("_db_row_id")
            if row_id:
                # Already logged — just update the rating to the
                # latest signal (e.g. user first clicked Good then
                # upgraded to Excellent).
                db.update_rating(row_id, rating)
            else:
                row_id = db.log_plot(
                    prompt=prompt, completion=completion,
                    rating=rating)
                history_entry["_db_row_id"] = row_id
        except Exception as e:
            print(f"[plot-ai] capture failed: {e}")

    # ── Conversation compaction ───────────────────────────────────
    # The AI tab keeps full turns in ``_ai_history`` (verbatim, sent
    # as the model's conversation_history). Long sessions blow the
    # context window; compaction folds older turns into a concise
    # summary stored in ``_ai_history_summary``, which the user-block
    # builder injects as a separate context block. Recent turns stay
    # verbatim so the immediate back-and-forth keeps full nuance.

    _COMPACT_KEEP_RECENT_TURNS = 6  # 3 user + 3 assistant pairs
    _COMPACT_TRIGGER_TURNS = 12     # start compacting beyond this
    _COMPACT_MAX_CHARS = 16000      # also trigger by raw char count

    def _maybe_compact_history(self):
        """Trim ``_ai_history`` if it's grown past the budget.

        Strategy: when the trimmed-out chunk exists, summarise it
        cheaply (questions verbatim, AI replies headline-only) and
        prepend to ``_ai_history_summary``. This keeps the recent
        window of ``_COMPACT_KEEP_RECENT_TURNS`` turns intact while
        the older context is collapsed into a short readable block.
        """
        n = len(self._ai_history)
        total_chars = sum(
            len(t.get('content') or '') for t in self._ai_history)
        if (n <= self._COMPACT_TRIGGER_TURNS
                and total_chars <= self._COMPACT_MAX_CHARS):
            return
        # Pop turns from the front in pairs (user → assistant) until
        # we're inside the recent-window cap.
        cutoff = max(0, n - self._COMPACT_KEEP_RECENT_TURNS)
        if cutoff <= 0:
            return
        old_turns = self._ai_history[:cutoff]
        self._ai_history = self._ai_history[cutoff:]

        # Build a cheap textual summary. Heuristic, not LLM-based —
        # we want compaction to be free and instant. The model still
        # sees recent turns verbatim, so loss of nuance in the older
        # window is acceptable.
        summary_lines = []
        for turn in old_turns:
            role = turn.get('role', '?')
            content = (turn.get('content') or '').strip()
            if not content:
                continue
            if role == 'user':
                # Questions are short and load-bearing; keep verbatim
                # (capped) so the model can still reason about what
                # the author originally asked.
                summary_lines.append(
                    f"Q: {content[:240]}"
                    + ("…" if len(content) > 240 else ""))
            else:
                # Replies get squeezed to first ~200 + last ~100 so
                # both the answer's framing and its conclusion
                # survive.
                if len(content) <= 320:
                    body = content
                else:
                    body = (f"{content[:200].rstrip()} "
                            f"… {content[-100:].lstrip()}")
                summary_lines.append(f"A: {body}")
        if summary_lines:
            new_chunk = "\n".join(summary_lines)
            if self._ai_history_summary:
                self._ai_history_summary = (
                    f"{self._ai_history_summary}\n{new_chunk}")
            else:
                self._ai_history_summary = new_chunk
            # Cap the cumulative summary so it doesn't grow
            # unbounded across many compactions; keep the tail (most
            # recent older context) since it's most likely to be
            # referenced.
            if len(self._ai_history_summary) > 4000:
                self._ai_history_summary = (
                    "…[older context trimmed]…\n"
                    + self._ai_history_summary[-4000:])
            print(f"[plot-ai] compacted {len(old_turns)} older turns "
                  f"({len(new_chunk)} chars summary, "
                  f"{len(self._ai_history)} turns retained)")

    def _on_ai_ask(self):
        """Send the input box to the plot AI."""
        if self._ai_busy:
            return
        question = self._ai_input.toPlainText().strip()
        if not question:
            return
        if self._ai_context_provider is None:
            self._ai_append_transient(
                "Plot AI isn't wired up yet (no project context "
                "available). Open a project first.",
                color="#b91c1c")
            return

        # Re-check context fresh at click time. The pre-flight banner
        # can be stale (project loaded after the AI tab was first
        # rendered, or the user opened/closed projects). Refreshing
        # here means the status banner always matches reality before
        # we either send or refuse.
        self._refresh_ai_context_status()
        live_ctx = self._gather_ai_context(question)
        _label, ok = self._summarise_ai_context(live_ctx)
        if not ok:
            self._ai_append_transient(
                "Can't ask yet — there's nothing in this project for "
                "the AI to discuss (no plot map, no chapters, no "
                "characters, no worldbuilding). Add at least one of "
                "those, then try again.",
                color="#b91c1c")
            return

        self._ai_input.clear()
        # Append the user turn to history immediately so it shows up
        # in the transcript while the model is thinking. The worker
        # gets a snapshot taken AFTER this append, so the model sees
        # the question in two places: as the freshly-appended history
        # turn AND as the user-block question. That's redundant but
        # harmless and keeps the rendering path simple.
        self._ai_history.append({"role": "user", "content": question})
        self._ai_render_history()
        self._ai_append_transient("Thinking…", color="#6b7280")
        self._ai_busy = True
        self._ai_ask_btn.setEnabled(False)

        # Compact older turns before sending so a long session
        # doesn't blow the model's context window. The compactor is
        # a no-op until history grows past the trigger thresholds.
        self._maybe_compact_history()
        history_summary = self._ai_history_summary

        from PyQt6.QtCore import QThread, pyqtSignal

        class _Worker(QThread):
            done = pyqtSignal(str)
            failed = pyqtSignal(str)

            def __init__(self, question, history, ctx_provider,
                         history_summary):
                super().__init__()
                self.question = question
                self.history = history
                self.ctx_provider = ctx_provider
                self.history_summary = history_summary

            def run(self):
                # Forward the question to the provider so its RAG
                # layer can pick the most relevant items instead of
                # dumping the whole project. Falls back to no-arg
                # call for older providers.
                try:
                    try:
                        ctx = self.ctx_provider(
                            question=self.question) or {}
                    except TypeError:
                        ctx = self.ctx_provider() or {}
                except Exception as e:
                    self.failed.emit(f"Couldn't gather context: {e}")
                    return
                # Inject the locally-tracked history summary so the
                # user-block builder can fold it into the prompt
                # alongside RAG / plot-map / etc. Don't overwrite a
                # value the provider already supplied.
                if self.history_summary and not ctx.get(
                        'history_summary'):
                    ctx['history_summary'] = self.history_summary
                try:
                    response = _ask_plot_ai(
                        self.question, self.history, ctx)
                except Exception as e:
                    self.failed.emit(str(e))
                    return
                self.done.emit(response or "(empty response)")

        self._ai_worker = _Worker(
            question, list(self._ai_history),
            self._ai_context_provider,
            history_summary)
        self._ai_worker.done.connect(
            lambda resp, q=question: self._ai_on_done(q, resp))
        self._ai_worker.failed.connect(self._ai_on_failed)
        self._ai_worker.start()

    def _ai_on_done(self, question: str, response: str):
        """Handle a successful AI response.

        ``question`` is the prompt the user sent; we stash it on the
        assistant entry alongside the cleaned reply so later capture
        events (Add suggestion, Excellent rating, Good rating) have
        the input/output pair without needing to walk back through
        the history list.
        """
        # Strip <suggest_*> blocks from the assistant text so they
        # render as interactive cards instead of inline XML noise.
        # The history entry stores both the cleaned reply (what's
        # shown / what gets sent back to the model in future turns)
        # and the original suggestion list so the user can review
        # each one and click Add or Skip.
        cleaned, suggestions = _extract_suggestions(response)
        self._ai_history.append({
            "role": "assistant",
            "content": cleaned,
            "suggestions": suggestions,
            # Capture-time bookkeeping: ``prompt`` is the user
            # question this turn was a reply to (so the input/output
            # pair is self-contained); ``_db_row_id`` starts at None
            # and gets stamped the first time the user signals
            # quality (Add / Excellent / Good) so subsequent rating
            # clicks update the existing row instead of inserting
            # duplicates.
            "prompt": question,
            "_db_row_id": None,
        })
        # Drop the "Thinking…" transient + render fresh.
        self._ai_transient_widgets = []
        self._ai_render_history()
        self._ai_busy = False
        self._ai_ask_btn.setEnabled(True)

    def _ai_on_failed(self, error: str):
        """Render an inline failure note."""
        self._ai_transient_widgets = []
        self._ai_render_history()
        self._ai_append_transient(
            f"<b>Plot AI failed:</b> {self._ai_text_to_html(error)}",
            color="#b91c1c")
        self._ai_busy = False
        self._ai_ask_btn.setEnabled(True)

    # ── Transcript rendering (widget-based) ───────────────────────
    # The transcript is a column of frames inside a QScrollArea so
    # assistant turns can carry interactive suggestion cards. Each
    # render rebuilds the column from scratch from ``_ai_history``;
    # it's cheap because turns are small and there are typically
    # fewer than a couple dozen at any time (compaction trims older
    # ones to a single summary block surfaced in the prompt).

    def _ai_render_history(self):
        """Rebuild the transcript widgets from ``self._ai_history``."""
        # Clear everything except the trailing stretch; we re-add
        # widgets above it so the column hugs the top.
        self._ai_clear_transcript_widgets()
        if not self._ai_history:
            self._ai_transcript_layout.insertWidget(
                self._ai_transcript_layout.count() - 1,
                self._ai_transcript_placeholder)
            self._ai_transcript_placeholder.show()
            return
        self._ai_transcript_placeholder.hide()
        for turn in self._ai_history:
            self._ai_transcript_layout.insertWidget(
                self._ai_transcript_layout.count() - 1,
                self._ai_build_turn_widget(turn))
        # Render any "transient" widgets (Thinking…, error notes)
        # that were appended after the last full render.
        for w in getattr(self, '_ai_transient_widgets', []):
            self._ai_transcript_layout.insertWidget(
                self._ai_transcript_layout.count() - 1, w)
        self._ai_scroll_to_bottom()

    def _ai_clear_transcript_widgets(self):
        """Drop every widget in the transcript column except the
        trailing stretch item."""
        # Walk backwards so item indices remain valid as we remove.
        for i in range(self._ai_transcript_layout.count() - 1, -1, -1):
            item = self._ai_transcript_layout.itemAt(i)
            w = item.widget() if item else None
            if w is None:
                continue
            self._ai_transcript_layout.removeWidget(w)
            # Keep the persistent placeholder around so we can
            # re-show it without rebuilding.
            if w is self._ai_transcript_placeholder:
                w.hide()
                w.setParent(None)
            else:
                w.setParent(None)
                w.deleteLater()

    def _ai_build_turn_widget(self, turn: dict) -> QWidget:
        """Build a frame for one turn (user or assistant)."""
        is_user = turn.get('role') == 'user'
        frame = QFrame()
        if is_user:
            frame.setStyleSheet(
                "QFrame { background-color: #6366f1; "
                "color: white; border-radius: 8px; "
                "padding: 6px 10px; }"
                "QLabel { color: white; }")
        else:
            frame.setStyleSheet(
                "QFrame { background-color: white; "
                "border: 1px solid #e5e7eb; border-radius: 8px; "
                "padding: 6px 10px; }")
        v = QVBoxLayout(frame)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(4)
        prefix = "You" if is_user else "AI"
        body = QLabel(
            f"<b>{prefix}:</b> "
            f"{self._ai_text_to_html(turn.get('content') or '')}")
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(body)
        # Attach any suggestion cards parsed from this assistant turn.
        # Pass ``turn`` through so the card's Add handler can capture
        # the (prompt, response) pair as plot training data.
        if not is_user:
            for s in turn.get('suggestions') or []:
                v.addWidget(self._ai_build_suggestion_card(s, frame, turn))
            # Add a small rating row so the user can mark a turn as
            # Good or Excellent — both signals capture training data
            # (gated by enable_plot_data_collection).
            v.addWidget(self._ai_build_rating_row(turn))
        return frame

    def _ai_build_rating_row(self, turn: dict) -> QWidget:
        """A thin row of two rating buttons under each AI turn.

        ``⭐ Excellent`` / ``👍 Good`` capture this turn into the
        plot training data; the row replaces itself with a status
        banner once the user clicks. The setting that gates the
        capture (``enable_plot_data_collection``) is mentioned in
        the tooltip so the user knows where to flip it on if their
        ratings aren't going anywhere yet.
        """
        row_w = QWidget()
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 2, 0, 0)
        h.setSpacing(6)
        prompt_label = QLabel(
            "<span style='color:#9ca3af;font-size:10px;'>"
            "Was this useful?</span>")
        h.addWidget(prompt_label)

        rating_btn_style = (
            "QPushButton { padding: 2px 10px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #15803d; "
            " color: #15803d; }")
        excellent_btn = QPushButton("⭐ Excellent")
        excellent_btn.setStyleSheet(rating_btn_style)
        excellent_btn.setToolTip(
            "Capture as 'excellent' plot training data. "
            "Requires Settings → CreativeOS → "
            "‘Plot data collection’ to be enabled.")
        h.addWidget(excellent_btn)

        good_btn = QPushButton("👍 Good")
        good_btn.setStyleSheet(rating_btn_style)
        good_btn.setToolTip(
            "Capture as 'good' plot training data. Requires "
            "Settings → CreativeOS → ‘Plot data collection’ to be "
            "enabled.")
        h.addWidget(good_btn)
        h.addStretch()

        def on_rate(rating: str):
            self._capture_plot_turn(turn, rating)
            try:
                from src.config.creativeos_config import get_creativeos_config
                enabled = bool(get_creativeos_config().get(
                    "enable_plot_data_collection", False))
            except Exception:
                enabled = False
            if enabled:
                msg = (f"<span style='color:#15803d;font-size:11px;'>"
                       f"✓ Saved as <b>{rating}</b> plot training "
                       f"data.</span>")
            else:
                msg = (
                    "<span style='color:#92400e;font-size:11px;'>"
                    "⚠ Rating noted, but plot data collection is "
                    "<b>off</b> — flip it on in Settings → "
                    "CreativeOS to capture future ratings."
                    "</span>")
            banner = QLabel(msg)
            banner.setWordWrap(True)
            # Replace the rating row in its parent layout so the
            # turn frame stays compact after the user has rated.
            parent_layout = row_w.parentWidget().layout()
            parent_layout.replaceWidget(row_w, banner)
            row_w.hide()
            row_w.deleteLater()

        excellent_btn.clicked.connect(lambda: on_rate("excellent"))
        good_btn.clicked.connect(lambda: on_rate("good"))
        return row_w

    def _ai_build_suggestion_card(self, suggestion: dict,
                                    parent_frame: QFrame,
                                    turn: Optional[dict] = None) -> QWidget:
        """Build the Add / Skip card for a single AI suggestion.

        ``turn`` is the assistant history entry this suggestion came
        from. When the user clicks Add we use it to capture the
        (prompt, response) pair as plot training data — accepting a
        suggestion is a strong signal of quality. Optional only so
        legacy callers without a turn reference don't break.

        Layout (kept tight so multiple cards fit on small screens):
          [ + Character ]            ← kind chip on its own line
          **Name** — why-line          ← bold name + dim why
          [ + Add to project ] [ Skip ]    ← action row, right-aligned

        After the user clicks Add or Skip, the action row is replaced
        by a single status banner ("✓ Added — Lena Voss" / "Skipped"
        / "Couldn't add — …"). No always-empty status label hangs
        around taking visual space when nothing has happened.
        """
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #f0f9ff; "
            " border: 1px solid #bfdbfe; border-radius: 6px; }")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        kind_label = QLabel(
            f"<span style='background:#dbeafe;color:#1d4ed8;"
            f"padding:1px 6px;border-radius:3px;font-size:10px;"
            f"font-weight:600;'>"
            f"+ {suggestion.get('label', 'Element').upper()}"
            f"</span>")
        kind_label.setStyleSheet("font-size: 11px;")
        v.addWidget(kind_label)

        data = suggestion.get('data') or {}
        name = ""
        if data:
            # Pull a name + the why-line if present so the card
            # answers "what" and "why" at a glance.
            name = (data.get('name') or data.get('title')
                    or '(no name)')
            why = data.get('why') or data.get('significance') or ''
            summary_html = (
                f"<span style='font-size:13px;'>"
                f"<b>{self._ai_text_to_html(name)}</b>"
                f"</span>")
            if why:
                summary_html += (
                    f"<br/><span style='color:#475569;font-size:11px;'>"
                    f"{self._ai_text_to_html(why)}</span>")
            summary = QLabel(summary_html)
            summary.setWordWrap(True)
            summary.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            v.addWidget(summary)
        else:
            err = QLabel(
                "<i>(couldn't parse the AI's suggestion JSON; "
                "raw text below)</i>")
            err.setStyleSheet("color: #b91c1c; font-size: 11px;")
            err.setWordWrap(True)
            v.addWidget(err)
            raw_box = QLabel(
                f"<pre style='font-size:10px;color:#374151;"
                f"white-space:pre-wrap;'>"
                f"{self._ai_text_to_html(suggestion.get('raw', ''))}"
                f"</pre>")
            raw_box.setWordWrap(True)
            v.addWidget(raw_box)

        # Action row — right-aligned so the buttons sit naturally
        # at the trailing edge of the card. Wrapped in its own
        # widget so we can swap the whole row for a status banner
        # post-click without disturbing the rest of the card.
        action_row_w = QWidget()
        action_row = QHBoxLayout(action_row_w)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addStretch()

        skip_btn = QPushButton("✕ Skip")
        skip_btn.setStyleSheet(
            "QPushButton { padding: 4px 14px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6b7280; }")
        skip_btn.setToolTip("Dismiss this suggestion without adding it.")
        action_row.addWidget(skip_btn)

        add_btn = QPushButton("➕ Add to project")
        add_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            " padding: 4px 14px; border-radius: 4px; font-size: 11px;"
            " font-weight: 600; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:disabled { background-color: #93c5fd; }")
        add_btn.setEnabled(bool(data))
        if not data:
            add_btn.setToolTip(
                "Can't add — the AI's JSON didn't parse.")
        action_row.addWidget(add_btn)
        v.addWidget(action_row_w)

        def _replace_with_banner(html: str, color: str):
            """Swap the action row for a one-line status banner.

            We hide the buttons immediately (so the user gets
            instant feedback) and then deleteLater for proper
            cleanup. Just deleteLater alone leaves the buttons
            interactive until the next event-loop tick.
            """
            banner = QLabel(html)
            banner.setStyleSheet(
                f"color: {color}; font-size: 11px; "
                f"padding: 2px 0;")
            banner.setWordWrap(True)
            v.replaceWidget(action_row_w, banner)
            add_btn.setEnabled(False)
            skip_btn.setEnabled(False)
            action_row_w.hide()
            action_row_w.deleteLater()

        def on_add():
            kind = suggestion.get('kind') or ''
            ok = self._on_ai_suggestion_add(kind, data)
            if ok:
                label = self._ai_text_to_html(name) if name else ""
                _replace_with_banner(
                    f"✓ <b>Added</b>"
                    + (f" — {label}" if label else ""),
                    "#15803d")
                # An accepted suggestion is a strong implicit signal
                # the AI's response was useful — capture the
                # (prompt, response) pair as plot training data
                # (gated by enable_plot_data_collection).
                if turn is not None:
                    self._capture_plot_turn(turn, rating="good")
            else:
                _replace_with_banner(
                    "✗ Couldn't add — see console for details.",
                    "#b91c1c")

        def on_skip():
            _replace_with_banner("— Skipped —", "#6b7280")

        add_btn.clicked.connect(on_add)
        skip_btn.clicked.connect(on_skip)
        return card

    def _on_ai_suggestion_add(self, kind: str, data: dict) -> bool:
        """Forward an Add click to the host's create-callback."""
        if self._ai_create_callback is None:
            print("[plot-ai] no create callback wired; "
                  "suggestion ignored")
            return False
        try:
            return bool(self._ai_create_callback(kind, data))
        except Exception as e:
            print(f"[plot-ai] create callback raised: {e}")
            return False

    def _ai_append_transient(self, html: str, color: str = "#6b7280"):
        """Show a one-shot status row (Thinking…, error) below the
        rendered turns. Cleared on the next render."""
        if not hasattr(self, '_ai_transient_widgets'):
            self._ai_transient_widgets = []
        label = QLabel(html)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {color}; font-style: italic; "
            f"padding: 4px 8px;")
        self._ai_transcript_layout.insertWidget(
            self._ai_transcript_layout.count() - 1, label)
        self._ai_transient_widgets.append(label)
        self._ai_scroll_to_bottom()

    def _ai_scroll_to_bottom(self):
        sb = self._ai_transcript_scroll.verticalScrollBar()
        # Defer the scroll so layout has a chance to settle first.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    @staticmethod
    def _ai_text_to_html(text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\n", "<br/>"))

    def _add_promise(self):
        """Add new story promise."""
        dialog = PromiseEditor(
            available_characters=self.available_characters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            promise = dialog.get_promise()
            self.promises.append(promise)
            self._update_promise_list()
            self.content_changed.emit()

    def _edit_promise(self):
        """Edit selected promise."""
        items = self.promise_list.selectedItems()
        if not items:
            return

        promise_id = items[0].data(Qt.ItemDataRole.UserRole)
        promise = next((p for p in self.promises if p.id == promise_id), None)
        if not promise:
            return

        dialog = PromiseEditor(
            promise=promise,
            available_characters=self.available_characters,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_promise_list()
            self.content_changed.emit()

    def _remove_promise(self):
        """Remove selected promise."""
        items = self.promise_list.selectedItems()
        if not items:
            return

        promise_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.promises = [p for p in self.promises if p.id != promise_id]
        self._update_promise_list()
        self.content_changed.emit()

    def _on_promise_selection_changed(self):
        """Handle promise selection change."""
        has_selection = bool(self.promise_list.selectedItems())
        self.edit_promise_btn.setEnabled(has_selection)
        self.remove_promise_btn.setEnabled(has_selection)

    def _update_promise_list(self):
        """Update the promise list widget."""
        self.promise_list.clear()

        # Group promises by type
        type_icons = {
            "tone": "🎭",
            "plot": "📖",
            "genre": "📚",
            "character": "👤"
        }

        for promise in self.promises:
            icon = type_icons.get(promise.promise_type, "📝")
            item = QListWidgetItem(f"{icon} [{promise.promise_type.title()}] {promise.title}")
            item.setData(Qt.ItemDataRole.UserRole, promise.id)
            if promise.description:
                item.setToolTip(promise.description)
            self.promise_list.addItem(item)

    # ── Tensions ──────────────────────────────────────────────
    # Sustained dramatic forces that shape the plot. Each one
    # appears as a list item with type / title / state, and gets
    # surfaced in the AI context block so plot suggestions can
    # weigh which tensions are escalating vs resolving.

    def _create_tensions_tab(self) -> QWidget:
        """Create the Tensions sub-tab — list + add/edit/remove."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QHBoxLayout()
        title = QLabel("Story Tensions")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        help_text = QLabel(
            "Sustained dramatic forces (internal struggles, "
            "rivalries, threats) the AI weighs when discussing plot")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)
        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("➕ Add Tension")
        add_btn.clicked.connect(self._add_tension)
        toolbar.addWidget(add_btn)

        self.edit_tension_btn = QPushButton("✏️ Edit")
        self.edit_tension_btn.setEnabled(False)
        self.edit_tension_btn.clicked.connect(self._edit_tension)
        toolbar.addWidget(self.edit_tension_btn)

        self.remove_tension_btn = QPushButton("🗑️ Remove")
        self.remove_tension_btn.setEnabled(False)
        self.remove_tension_btn.clicked.connect(self._remove_tension)
        toolbar.addWidget(self.remove_tension_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Type-info banner so users know what each tension type means.
        info = QLabel(
            "<b>Tension types:</b><br/>"
            "• <b>Internal</b> — struggle inside one character "
            "(grief, doubt, addiction)<br/>"
            "• <b>Interpersonal</b> — pressure between characters "
            "(rivalry, eroding trust)<br/>"
            "• <b>Societal</b> — group pressure on a character "
            "(suspicion, stigma, oppression)<br/>"
            "• <b>Cosmic</b> — external threat looming over all "
            "(war, plague, the encroaching frost)")
        info.setWordWrap(True)
        info.setStyleSheet(
            "background-color: #f3f4f6; padding: 8px; "
            "border-radius: 4px; font-size: 11px;")
        layout.addWidget(info)

        self._tension_list = QListWidget()
        self._tension_list.itemSelectionChanged.connect(
            self._on_tension_selection_changed)
        self._tension_list.itemDoubleClicked.connect(
            self._edit_tension)
        layout.addWidget(self._tension_list, stretch=1)
        return widget

    def _add_tension(self):
        dialog = TensionEditor(
            available_characters=self.available_characters,
            parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            tension = dialog.get_tension()
            self.tensions.append(tension)
            self._update_tension_list()
            self.content_changed.emit()

    def _edit_tension(self):
        items = self._tension_list.selectedItems()
        if not items:
            return
        tension_id = items[0].data(Qt.ItemDataRole.UserRole)
        tension = next((t for t in self.tensions
                        if t.id == tension_id), None)
        if not tension:
            return
        dialog = TensionEditor(
            tension=tension,
            available_characters=self.available_characters,
            parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_tension()
            for i, t in enumerate(self.tensions):
                if t.id == tension_id:
                    self.tensions[i] = updated
                    break
            self._update_tension_list()
            self.content_changed.emit()

    def _remove_tension(self):
        items = self._tension_list.selectedItems()
        if not items:
            return
        tension_id = items[0].data(Qt.ItemDataRole.UserRole)
        from PyQt6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self, "Remove tension?",
            "Remove this tension from the plot? You can re-add it "
            "later if you change your mind.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.tensions = [t for t in self.tensions
                         if t.id != tension_id]
        self._update_tension_list()
        self.content_changed.emit()

    def _on_tension_selection_changed(self):
        has = bool(self._tension_list.selectedItems())
        self.edit_tension_btn.setEnabled(has)
        self.remove_tension_btn.setEnabled(has)

    def _update_tension_list(self):
        if not hasattr(self, '_tension_list'):
            return
        self._tension_list.clear()
        type_icons = {
            "internal": "🧠",
            "interpersonal": "⚔️",
            "societal": "🏛️",
            "cosmic": "🌑",
        }
        state_glyphs = {
            "rising": "↗",
            "stable": "→",
            "escalating": "🔥",
            "resolving": "↘",
            "unresolved": "⏸",
            "resolved": "✓",
        }
        for t in self.tensions:
            icon = type_icons.get(t.tension_type, "⚡")
            state = state_glyphs.get(t.current_state, "")
            who = (f" — {', '.join(t.characters_involved[:3])}"
                   if t.characters_involved else "")
            item = QListWidgetItem(
                f"{icon}  [{t.tension_type.title()}]  "
                f"{t.title}  {state}{who}")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            tip_parts = []
            if t.description:
                tip_parts.append(t.description)
            if t.stakes:
                tip_parts.append(f"Stakes: {t.stakes}")
            if tip_parts:
                item.setToolTip("\n\n".join(tip_parts))
            self._tension_list.addItem(item)

    # ── Themes ────────────────────────────────────────────────
    # What the story is *about* underneath its events. Each theme
    # surfaces in the plot AI context so suggestions can reinforce
    # rather than dilute the book's argument. Legacy projects with
    # bare-string themes display them in a separate row at the top
    # of the list — the user can promote them to rich themes by
    # clicking ✏️ Edit on the row.

    def _create_themes_tab(self) -> QWidget:
        """Create the Themes sub-tab — list + add/edit/remove."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QHBoxLayout()
        title = QLabel("Story Themes")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        help_text = QLabel(
            "What the story is about underneath its events — the "
            "argument the book makes")
        help_text.setStyleSheet("font-size: 11px; color: #6b7280;")
        header.addWidget(help_text)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("➕ Add Theme")
        add_btn.clicked.connect(self._add_theme)
        toolbar.addWidget(add_btn)

        self.edit_theme_btn = QPushButton("✏️ Edit")
        self.edit_theme_btn.setEnabled(False)
        self.edit_theme_btn.clicked.connect(self._edit_theme)
        toolbar.addWidget(self.edit_theme_btn)

        self.remove_theme_btn = QPushButton("🗑️ Remove")
        self.remove_theme_btn.setEnabled(False)
        self.remove_theme_btn.clicked.connect(self._remove_theme)
        toolbar.addWidget(self.remove_theme_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        info = QLabel(
            "<b>A good theme has:</b><br/>"
            "• A short title — the label you'll reference<br/>"
            "• A statement — the argument your story makes "
            "(e.g. \"Redemption requires confession, not just "
            "remorse\")<br/>"
            "• Motifs — recurring images / objects / phrases that "
            "signal it (e.g. \"broken mirrors\", \"the frost\")<br/>"
            "• Related characters — whose arc carries it")
        info.setWordWrap(True)
        info.setStyleSheet(
            "background-color: #f3f4f6; padding: 8px; "
            "border-radius: 4px; font-size: 11px;")
        layout.addWidget(info)

        self._theme_list = QListWidget()
        self._theme_list.itemSelectionChanged.connect(
            self._on_theme_selection_changed)
        self._theme_list.itemDoubleClicked.connect(self._edit_theme)
        layout.addWidget(self._theme_list, stretch=1)
        return widget

    def _add_theme(self):
        dialog = ThemeEditor(
            available_characters=self.available_characters,
            parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            theme = dialog.get_theme()
            self.themes.append(theme)
            self._update_theme_list()
            self.content_changed.emit()

    def _edit_theme(self):
        items = self._theme_list.selectedItems()
        if not items:
            return
        item = items[0]
        # Legacy bare-string themes get promoted to rich Theme on edit.
        legacy_index = item.data(Qt.ItemDataRole.UserRole + 1)
        if legacy_index is not None:
            legacy_text = self.legacy_themes[legacy_index]
            import uuid
            stub = Theme(id=str(uuid.uuid4()), title=legacy_text)
            dialog = ThemeEditor(
                theme=stub,
                available_characters=self.available_characters,
                parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.themes.append(dialog.get_theme())
                # Drop the legacy entry now that it's been promoted.
                self.legacy_themes.pop(legacy_index)
                self._update_theme_list()
                self.content_changed.emit()
            return
        theme_id = item.data(Qt.ItemDataRole.UserRole)
        theme = next((t for t in self.themes if t.id == theme_id),
                     None)
        if not theme:
            return
        dialog = ThemeEditor(
            theme=theme,
            available_characters=self.available_characters,
            parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_theme()
            for i, t in enumerate(self.themes):
                if t.id == theme_id:
                    self.themes[i] = updated
                    break
            self._update_theme_list()
            self.content_changed.emit()

    def _remove_theme(self):
        items = self._theme_list.selectedItems()
        if not items:
            return
        item = items[0]
        legacy_index = item.data(Qt.ItemDataRole.UserRole + 1)
        from PyQt6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self, "Remove theme?",
            "Remove this theme? You can re-add it later.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if legacy_index is not None:
            self.legacy_themes.pop(legacy_index)
        else:
            theme_id = item.data(Qt.ItemDataRole.UserRole)
            self.themes = [t for t in self.themes if t.id != theme_id]
        self._update_theme_list()
        self.content_changed.emit()

    def _on_theme_selection_changed(self):
        has = bool(self._theme_list.selectedItems())
        self.edit_theme_btn.setEnabled(has)
        self.remove_theme_btn.setEnabled(has)

    def _update_theme_list(self):
        if not hasattr(self, '_theme_list'):
            return
        self._theme_list.clear()
        # Rich themes first.
        for t in self.themes:
            label = f"🎯  {t.title}"
            if t.statement:
                label += f"  —  {t.statement[:80]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            tip_parts = []
            if t.description:
                tip_parts.append(t.description)
            if t.statement:
                tip_parts.append(f"Statement: {t.statement}")
            if t.motifs:
                tip_parts.append(f"Motifs: {', '.join(t.motifs)}")
            if t.related_characters:
                tip_parts.append(
                    f"Carried by: "
                    f"{', '.join(t.related_characters)}")
            if tip_parts:
                item.setToolTip("\n\n".join(tip_parts))
            self._theme_list.addItem(item)
        # Legacy bare-string themes — promotable via Edit.
        for i, txt in enumerate(self.legacy_themes):
            item = QListWidgetItem(
                f"📝  {txt}  (legacy — click Edit to flesh out)")
            # We use UserRole+1 to mark the legacy index so _edit/_remove
            # can route correctly.
            item.setData(Qt.ItemDataRole.UserRole + 1, i)
            item.setToolTip(
                "Bare-text theme from an older save. Click Edit to "
                "add a description, statement, motifs, and related "
                "characters — it'll become a rich theme that the "
                "plot AI can reason about more deeply.")
            self._theme_list.addItem(item)

    def _add_event(self):
        """Add new plot event."""
        editor = PlotEventEditor(
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            event = editor.get_event()

            # Set sort_order to next available value for this act/stage if not explicitly set
            # (default from editor is 0, so we check if there are other events with sort_order >= 0)
            same_group_events = [
                e for e in self.freytag_pyramid.events
                if e.act == event.act and e.stage == event.stage
            ]
            if same_group_events:
                max_sort_order = max(e.sort_order for e in same_group_events)
                # Only auto-increment if the user left it at default (0) and there are existing events
                if event.sort_order == 0:
                    event.sort_order = max_sort_order + 1

            self.freytag_pyramid.events.append(event)
            self._update_event_list()
            self.content_changed.emit()

    def _edit_event(self):
        """Edit selected event."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        editor = PlotEventEditor(
            event=event,
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_event_list()
            self.content_changed.emit()

    def _remove_event(self):
        """Remove selected event."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.freytag_pyramid.events = [e for e in self.freytag_pyramid.events if e.id != event_id]
        self._update_event_list()
        self.content_changed.emit()

    def _move_event_up(self):
        """Move selected event up in sort order (within same act and stage)."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        # Find events in the same act AND stage
        same_group_events = [
            e for e in self.freytag_pyramid.events
            if e.act == event.act and e.stage == event.stage
        ]
        same_group_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_group_events) if e.id == event_id), None)
        if current_index is None or current_index == 0:
            return

        # Swap sort orders with the previous event
        prev_event = same_group_events[current_index - 1]
        event.sort_order, prev_event.sort_order = prev_event.sort_order, event.sort_order

        # If they ended up with the same sort_order (both were 0), fix it
        if event.sort_order == prev_event.sort_order:
            prev_event.sort_order = event.sort_order + 1

        self._update_event_list()
        self.content_changed.emit()

        # Re-select the event
        for i in range(self.event_list.count()):
            item = self.event_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event_id:
                self.event_list.setCurrentItem(item)
                break

    def _move_event_down(self):
        """Move selected event down in sort order (within same act and stage)."""
        items = self.event_list.selectedItems()
        if not items:
            return

        event_id = items[0].data(Qt.ItemDataRole.UserRole)
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        # Find events in the same act AND stage
        same_group_events = [
            e for e in self.freytag_pyramid.events
            if e.act == event.act and e.stage == event.stage
        ]
        same_group_events.sort(key=lambda e: e.sort_order)

        # Find current position
        current_index = next((i for i, e in enumerate(same_group_events) if e.id == event_id), None)
        if current_index is None or current_index >= len(same_group_events) - 1:
            return

        # Swap sort orders with the next event
        next_event = same_group_events[current_index + 1]
        event.sort_order, next_event.sort_order = next_event.sort_order, event.sort_order

        # If they ended up with the same sort_order (both were 0), fix it
        if event.sort_order == next_event.sort_order:
            event.sort_order = next_event.sort_order + 1

        self._update_event_list()
        self.content_changed.emit()

        # Re-select the event
        for i in range(self.event_list.count()):
            item = self.event_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event_id:
                self.event_list.setCurrentItem(item)
                break

    def _add_subplot(self):
        """Add new subplot."""
        editor = SubplotEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            subplot = editor.get_subplot()
            self.subplots.append(subplot)
            self._update_subplot_list()
            self.content_changed.emit()

    def _edit_subplot(self):
        """Edit selected subplot."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)
        subplot = next((s for s in self.subplots if s.id == subplot_id), None)
        if not subplot:
            return

        editor = SubplotEditor(subplot=subplot, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_subplot_list()
            self.content_changed.emit()

    def _remove_subplot(self):
        """Remove selected subplot."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.subplots = [s for s in self.subplots if s.id != subplot_id]
        self._update_subplot_list()
        self.content_changed.emit()

    def _move_subplot_up(self):
        """Move selected subplot up in the list."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)

        # Find current index
        current_index = next((i for i, s in enumerate(self.subplots) if s.id == subplot_id), None)
        if current_index is None or current_index == 0:
            return

        # Swap with previous subplot
        self.subplots[current_index], self.subplots[current_index - 1] = \
            self.subplots[current_index - 1], self.subplots[current_index]

        self._update_subplot_list()
        self.content_changed.emit()

        # Re-select the subplot
        for i in range(self.subplot_list.count()):
            item = self.subplot_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subplot_id:
                self.subplot_list.setCurrentItem(item)
                break

    def _move_subplot_down(self):
        """Move selected subplot down in the list."""
        items = self.subplot_list.selectedItems()
        if not items:
            return

        subplot_id = items[0].data(Qt.ItemDataRole.UserRole)

        # Find current index
        current_index = next((i for i, s in enumerate(self.subplots) if s.id == subplot_id), None)
        if current_index is None or current_index >= len(self.subplots) - 1:
            return

        # Swap with next subplot
        self.subplots[current_index], self.subplots[current_index + 1] = \
            self.subplots[current_index + 1], self.subplots[current_index]

        self._update_subplot_list()
        self.content_changed.emit()

        # Re-select the subplot
        for i in range(self.subplot_list.count()):
            item = self.subplot_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subplot_id:
                self.subplot_list.setCurrentItem(item)
                break

    def _update_event_list(self, update_pyramid: bool = True):
        """Update event list display.

        Args:
            update_pyramid: If True, also update the visual pyramid (default True)
        """
        self.event_list.clear()

        # Sort events by act, then stage, then sort_order
        stage_order = {"exposition": 0, "rising_action": 1, "climax": 2, "falling_action": 3, "resolution": 4}
        sorted_events = sorted(
            self.freytag_pyramid.events,
            key=lambda e: (e.act, stage_order.get(e.stage, 1), e.sort_order)
        )

        for event in sorted_events:
            stage_names = {
                "exposition": "Exposition",
                "rising_action": "Rising Action",
                "climax": "Climax",
                "falling_action": "Falling Action",
                "resolution": "Resolution"
            }
            stage_display = stage_names.get(event.stage, event.stage)

            # Get act name
            act_name = (self.freytag_pyramid.act_names[event.act - 1]
                       if event.act <= len(self.freytag_pyramid.act_names)
                       else f"Act {event.act}")

            item_text = f"[{act_name}] {event.title} ({stage_display}, Intensity: {event.intensity})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            self.event_list.addItem(item)

        # Also update the visual pyramid to stay in sync
        if update_pyramid:
            self._update_pyramid()

    def _update_subplot_list(self):
        """Update subplot list display."""
        self.subplot_list.clear()

        for subplot in self.subplots:
            status_emoji = "✅" if subplot.status == "resolved" else "🔄" if subplot.status == "active" else "❌"
            item_text = f"{status_emoji} {subplot.title}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, subplot.id)
            self.subplot_list.addItem(item)

    def _update_pyramid(self):
        """Update visual pyramid with events."""
        self.pyramid_visual.set_events(self.freytag_pyramid.events)

    def _on_event_selection_changed(self):
        """Handle event selection change."""
        has_selection = bool(self.event_list.selectedItems())
        self.edit_event_btn.setEnabled(has_selection)
        self.remove_event_btn.setEnabled(has_selection)
        self.move_event_up_btn.setEnabled(has_selection)
        self.move_event_down_btn.setEnabled(has_selection)

    def _on_subplot_selection_changed(self):
        """Handle subplot selection change."""
        has_selection = bool(self.subplot_list.selectedItems())
        self.edit_subplot_btn.setEnabled(has_selection)
        self.remove_subplot_btn.setEnabled(has_selection)
        self.move_subplot_up_btn.setEnabled(has_selection)
        self.move_subplot_down_btn.setEnabled(has_selection)

    def load_plot_data(
        self,
        freytag_pyramid: FreytagPyramid,
        subplots: List[Subplot],
        promises: List[StoryPromise] = None,
        tensions: List = None,
        themes: List = None,
        legacy_themes: List[str] = None,
    ):
        """Load plot data.

        Args:
            freytag_pyramid: FreytagPyramid object with events
            subplots: List of Subplot objects
            promises: List of StoryPromise objects
            tensions: List of CharacterTension objects (sustained
                dramatic forces shaping the plot — surfaced in the
                plot AI context so suggestions weigh them)
            themes: List of Theme objects (rich themes with
                description, statement, motifs)
            legacy_themes: List of plain-string themes from older
                projects — surfaced in the AI context as a fallback
                when themes is empty
        """
        self.freytag_pyramid = freytag_pyramid
        self.subplots = subplots
        self.promises = promises or []
        self.tensions = tensions or []
        self.themes = themes or []
        self.legacy_themes = list(legacy_themes or [])

        # Sync act configuration UI
        self.num_acts_spin.blockSignals(True)
        self.num_acts_spin.setValue(freytag_pyramid.num_acts)
        self.num_acts_spin.blockSignals(False)

        # Update pyramid with acts
        self.pyramid_visual.set_acts(freytag_pyramid.num_acts, freytag_pyramid.act_names)

        self._update_event_list()
        self._update_subplot_list()
        self._update_promise_list()
        if hasattr(self, '_tension_list'):
            self._update_tension_list()
        if hasattr(self, '_theme_list'):
            self._update_theme_list()

    def get_plot_data(self):
        """Get plot data.

        Returns:
            Tuple of (FreytagPyramid, List[Subplot], List[StoryPromise],
                      List[CharacterTension], List[Theme],
                      List[str] legacy_themes)
        """
        return (self.freytag_pyramid, self.subplots, self.promises,
                self.tensions, self.themes, self.legacy_themes)

    def set_available_characters(self, characters: List[str]):
        """Set available characters for event association.

        Args:
            characters: List of character names
        """
        self.available_characters = characters

    def _on_num_acts_changed(self, value: int):
        """Handle number of acts change."""
        self.freytag_pyramid.num_acts = value

        # Ensure act_names list has the right length
        while len(self.freytag_pyramid.act_names) < value:
            self.freytag_pyramid.act_names.append(f"Act {len(self.freytag_pyramid.act_names) + 1}")
        self.freytag_pyramid.act_names = self.freytag_pyramid.act_names[:value]

        # Update visual
        self.pyramid_visual.set_acts(value, self.freytag_pyramid.act_names)
        self.content_changed.emit()

    def _edit_act_names(self):
        """Open dialog to edit act names."""
        dialog = ActNamesDialog(
            self.freytag_pyramid.num_acts,
            self.freytag_pyramid.act_names,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.freytag_pyramid.act_names = dialog.get_act_names()
            self.pyramid_visual.set_acts(
                self.freytag_pyramid.num_acts,
                self.freytag_pyramid.act_names
            )
            self.content_changed.emit()

    def _on_event_list_double_clicked(self, item: QListWidgetItem):
        """Handle double-click on event list item."""
        event_id = item.data(Qt.ItemDataRole.UserRole)
        if event_id:
            self._show_event_popup(event_id)

    def _on_pyramid_event_clicked(self, event_id: str):
        """Handle click on event in pyramid visual."""
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        self._show_event_popup(event_id)

    def _show_event_popup(self, event_id: str):
        """Show the event description popup.

        Args:
            event_id: ID of the event to show
        """
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        popup = EventDescriptionPopup(event, parent=self)
        result = popup.exec()

        if result == QDialog.DialogCode.Accepted:
            # Description was saved
            self._update_pyramid()
            self.content_changed.emit()
        elif result == 2:  # Custom code for "open full editor"
            # Open the full event editor
            self._edit_event_by_id(event_id)

    def _edit_event_by_id(self, event_id: str):
        """Edit an event by its ID.

        Args:
            event_id: ID of the event to edit
        """
        event = next((e for e in self.freytag_pyramid.events if e.id == event_id), None)
        if not event:
            return

        editor = PlotEventEditor(
            event=event,
            available_characters=self.available_characters,
            available_subplots=self.subplots,
            num_acts=self.freytag_pyramid.num_acts,
            act_names=self.freytag_pyramid.act_names,
            parent=self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_event_list()
            self.content_changed.emit()


class ActNamesDialog(QDialog):
    """Dialog for editing act names."""

    def __init__(self, num_acts: int, act_names: List[str], parent=None):
        """Initialize act names dialog."""
        super().__init__(parent)
        self.num_acts = num_acts
        self.act_names = act_names.copy() if act_names else []
        self.name_edits = []
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Edit Act Names")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        label = QLabel("Customize the names for each act:")
        layout.addWidget(label)

        # Create input fields for each act
        form_layout = QFormLayout()
        for i in range(self.num_acts):
            edit = QLineEdit()
            default_name = self.act_names[i] if i < len(self.act_names) else f"Act {i+1}"
            edit.setText(default_name)
            edit.setPlaceholderText(f"Act {i+1}")
            form_layout.addRow(f"Act {i+1}:", edit)
            self.name_edits.append(edit)

        layout.addLayout(form_layout)

        # Preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Presets:"))

        three_act_btn = QPushButton("🎭 3-Act Classic")
        three_act_btn.clicked.connect(lambda: self._apply_preset([
            "Act I: Setup", "Act II: Confrontation", "Act III: Resolution"
        ]))
        preset_layout.addWidget(three_act_btn)

        five_act_btn = QPushButton("🎬 5-Act Drama")
        five_act_btn.clicked.connect(lambda: self._apply_preset([
            "Act I: Exposition", "Act II: Rising Action", "Act III: Climax",
            "Act IV: Falling Action", "Act V: Denouement"
        ]))
        preset_layout.addWidget(five_act_btn)

        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        layout.addStretch()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_preset(self, names: List[str]):
        """Apply preset act names."""
        for i, edit in enumerate(self.name_edits):
            if i < len(names):
                edit.setText(names[i])

    def get_act_names(self) -> List[str]:
        """Get the edited act names."""
        return [edit.text().strip() or f"Act {i+1}" for i, edit in enumerate(self.name_edits)]


class EventDescriptionPopup(QDialog):
    """Popup dialog for viewing and editing event description."""

    description_changed = pyqtSignal()

    def __init__(self, event: PlotEvent, parent=None):
        """Initialize event description popup.

        Args:
            event: PlotEvent to display/edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.event = event
        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle(f"Event: {self.event.title}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Event info header
        info_layout = QFormLayout()

        # Title (read-only display)
        title_label = QLabel(self.event.title)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addRow("Title:", title_label)

        # Stage and Act
        stage_names = {
            "exposition": "Exposition",
            "rising_action": "Rising Action",
            "climax": "Climax",
            "falling_action": "Falling Action",
            "resolution": "Resolution"
        }
        stage_display = stage_names.get(self.event.stage, self.event.stage)
        info_layout.addRow("Stage:", QLabel(stage_display))
        info_layout.addRow("Act:", QLabel(f"Act {self.event.act}"))
        info_layout.addRow("Intensity:", QLabel(f"{self.event.intensity}%"))

        layout.addLayout(info_layout)

        # Description editor
        desc_group = QGroupBox("Description")
        desc_layout = QVBoxLayout(desc_group)
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(self.event.description)
        self.description_edit.setPlaceholderText("What happens in this event...")
        desc_layout.addWidget(self.description_edit)
        layout.addWidget(desc_group)

        # Outcome editor
        outcome_group = QGroupBox("Outcome")
        outcome_layout = QVBoxLayout(outcome_group)
        self.outcome_edit = QTextEdit()
        self.outcome_edit.setPlainText(self.event.outcome)
        self.outcome_edit.setPlaceholderText("What changes as a result...")
        self.outcome_edit.setMaximumHeight(100)
        outcome_layout.addWidget(self.outcome_edit)
        layout.addWidget(outcome_group)

        # Characters involved
        if self.event.related_characters:
            chars_label = QLabel(f"Characters: {', '.join(self.event.related_characters)}")
            chars_label.setWordWrap(True)
            chars_label.setStyleSheet("color: #6b7280; font-size: 11px;")
            layout.addWidget(chars_label)

        # Buttons
        button_layout = QHBoxLayout()

        edit_full_btn = QPushButton("✏️ Edit Full Event…")
        edit_full_btn.clicked.connect(self._open_full_editor)
        button_layout.addWidget(edit_full_btn)

        button_layout.addStretch()

        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self._save_and_close)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("✕ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _save_and_close(self):
        """Save description changes and close."""
        self.event.description = self.description_edit.toPlainText().strip()
        self.event.outcome = self.outcome_edit.toPlainText().strip()
        self.description_changed.emit()
        self.accept()

    def _open_full_editor(self):
        """Signal that full editor should be opened."""
        # Save any changes first
        self.event.description = self.description_edit.toPlainText().strip()
        self.event.outcome = self.outcome_edit.toPlainText().strip()
        self.done(2)  # Custom return code for "open full editor"


class PromiseEditor(QDialog):
    """Dialog for editing a story promise."""

    PROMISE_TYPES = [
        ("tone", "Tone", "Emotional atmosphere and mood"),
        ("plot", "Plot", "Story structure and events"),
        ("genre", "Genre", "Genre conventions and expectations"),
        ("character", "Character", "Character arcs and consistency"),
    ]

    def __init__(
        self,
        promise: StoryPromise = None,
        available_characters: List[str] = None,
        parent=None
    ):
        """Initialize promise editor.

        Args:
            promise: Existing promise to edit, or None for new promise
            available_characters: List of character names for character promises
            parent: Parent widget
        """
        super().__init__(parent)
        self.promise = promise
        self.available_characters = available_characters or []
        self.is_new = promise is None
        self._init_ui()
        if not self.is_new:
            self._load_promise()

    def _init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Edit Promise" if not self.is_new else "New Story Promise")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        # Promise type selector
        self.type_combo = QListWidget()
        self.type_combo.setMaximumHeight(100)
        for type_id, type_name, type_desc in self.PROMISE_TYPES:
            item = QListWidgetItem(f"{type_name} - {type_desc}")
            item.setData(Qt.ItemDataRole.UserRole, type_id)
            self.type_combo.addItem(item)
        self.type_combo.setCurrentRow(0)
        self.type_combo.currentItemChanged.connect(self._on_type_changed)
        form_layout.addRow("Type:*", self.type_combo)

        # Title
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Brief summary of the promise")
        form_layout.addRow("Title:*", self.title_edit)

        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Detailed description of what you're committing to...\n\n"
            "Examples:\n"
            "• Tone: The story will maintain a hopeful undertone despite dark themes\n"
            "• Plot: The central mystery will be fully resolved by the end\n"
            "• Genre: Romance will develop gradually with satisfying payoff\n"
            "• Character: Sarah will complete her arc from self-doubt to confidence"
        )
        self.description_edit.setMaximumHeight(150)
        form_layout.addRow("Description:", self.description_edit)

        # Related characters (for character promises)
        self.characters_group = QGroupBox("Related Characters")
        chars_layout = QVBoxLayout(self.characters_group)

        self.characters_list = QListWidget()
        self.characters_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.characters_list.setMaximumHeight(100)
        for char in self.available_characters:
            self.characters_list.addItem(char)
        chars_layout.addWidget(self.characters_list)

        form_layout.addRow(self.characters_group)
        self._update_characters_visibility()

        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_type_changed(self, current, previous):
        """Handle promise type change."""
        self._update_characters_visibility()

    def _update_characters_visibility(self):
        """Show/hide characters group based on promise type."""
        current = self.type_combo.currentItem()
        if current:
            promise_type = current.data(Qt.ItemDataRole.UserRole)
            self.characters_group.setVisible(promise_type == "character")

    def _load_promise(self):
        """Load existing promise data into form."""
        if not self.promise:
            return

        # Set type
        for i in range(self.type_combo.count()):
            item = self.type_combo.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self.promise.promise_type:
                self.type_combo.setCurrentRow(i)
                break

        self.title_edit.setText(self.promise.title)
        self.description_edit.setPlainText(self.promise.description)

        # Select related characters
        for i in range(self.characters_list.count()):
            item = self.characters_list.item(i)
            if item.text() in self.promise.related_characters:
                item.setSelected(True)

    def _save_and_close(self):
        """Validate and save the promise."""
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            return

        current_type_item = self.type_combo.currentItem()
        if not current_type_item:
            return

        promise_type = current_type_item.data(Qt.ItemDataRole.UserRole)

        # Get selected characters
        related_characters = [
            item.text() for item in self.characters_list.selectedItems()
        ]

        if self.is_new:
            import uuid
            self.promise = StoryPromise(
                id=str(uuid.uuid4()),
                promise_type=promise_type,
                title=title,
                description=self.description_edit.toPlainText().strip(),
                related_characters=related_characters
            )
        else:
            self.promise.promise_type = promise_type
            self.promise.title = title
            self.promise.description = self.description_edit.toPlainText().strip()
            self.promise.related_characters = related_characters

        self.accept()

    def get_promise(self) -> StoryPromise:
        """Get the edited promise."""
        return self.promise


class TensionEditor(QDialog):
    """Dialog for adding / editing a CharacterTension.

    Same shape as PromiseEditor: type picker, title, description,
    plus tension-specific fields (stakes, current state, intensity,
    characters involved). Returns a fully-populated CharacterTension
    via :meth:`get_tension`.
    """

    TENSION_TYPES = [
        ("internal",
         "🧠 Internal — struggle inside one character"),
        ("interpersonal",
         "⚔️ Interpersonal — pressure between characters"),
        ("societal",
         "🏛️ Societal — group pressure on a character"),
        ("cosmic",
         "🌑 Cosmic — external threat looming over all"),
    ]
    STATE_OPTIONS = [
        ("rising", "↗ Rising — building pressure"),
        ("stable", "→ Stable — steady simmer"),
        ("escalating", "🔥 Escalating — about to break"),
        ("resolving", "↘ Resolving — pressure releasing"),
        ("unresolved", "⏸ Unresolved — paused mid-arc"),
        ("resolved", "✓ Resolved — paid off"),
    ]

    def __init__(self,
                 tension: 'CharacterTension' = None,
                 available_characters: List[str] = None,
                 parent=None):
        super().__init__(parent)
        self.tension = tension
        self.available_characters = available_characters or []
        self.is_new = tension is None
        self._init_ui()
        if not self.is_new:
            self._load_tension()

    def _init_ui(self):
        self.setWindowTitle(
            "Edit Tension" if not self.is_new else "New Story Tension")
        self.setMinimumWidth(540)
        self.setMinimumHeight(520)

        layout = QVBoxLayout(self)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        # Type
        self.type_combo = QListWidget()
        self.type_combo.setMaximumHeight(120)
        for type_id, label in self.TENSION_TYPES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, type_id)
            self.type_combo.addItem(item)
        self.type_combo.setCurrentRow(1)  # interpersonal default
        form_layout.addRow("Type:*", self.type_combo)

        # Title
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(
            "Short label, e.g. 'Marcus vs Lena' or 'Rachel's grief'")
        form_layout.addRow("Title:*", self.title_edit)

        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "What's the source of this tension? What keeps it "
            "alive across multiple scenes?")
        self.description_edit.setMaximumHeight(110)
        form_layout.addRow("Description:", self.description_edit)

        # Stakes
        self.stakes_edit = QTextEdit()
        self.stakes_edit.setPlaceholderText(
            "What happens if this tension goes unresolved? Who "
            "or what is at risk?")
        self.stakes_edit.setMaximumHeight(80)
        form_layout.addRow("Stakes:", self.stakes_edit)

        # Current state
        self.state_combo = QListWidget()
        self.state_combo.setMaximumHeight(150)
        for state_id, label in self.STATE_OPTIONS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, state_id)
            self.state_combo.addItem(item)
        self.state_combo.setCurrentRow(0)
        form_layout.addRow("Current state:", self.state_combo)

        # Intensity slider
        from PyQt6.QtWidgets import QSlider
        intensity_row = QHBoxLayout()
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setMinimum(0)
        self.intensity_slider.setMaximum(100)
        self.intensity_slider.setValue(50)
        self._intensity_value_label = QLabel("50")
        self._intensity_value_label.setFixedWidth(28)
        self.intensity_slider.valueChanged.connect(
            lambda v: self._intensity_value_label.setText(str(v)))
        intensity_row.addWidget(self.intensity_slider, stretch=1)
        intensity_row.addWidget(self._intensity_value_label)
        intensity_w = QWidget()
        intensity_w.setLayout(intensity_row)
        form_layout.addRow("Intensity (0-100):", intensity_w)

        # Characters involved
        char_group = QGroupBox("Characters involved")
        char_layout = QVBoxLayout(char_group)
        self.characters_list = QListWidget()
        self.characters_list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection)
        self.characters_list.setMaximumHeight(120)
        for name in self.available_characters:
            self.characters_list.addItem(name)
        char_layout.addWidget(self.characters_list)
        if not self.available_characters:
            no_chars = QLabel(
                "(No characters defined yet — add them in the "
                "Characters tab and they'll show up here.)")
            no_chars.setStyleSheet("color: #6b7280; font-size: 11px;")
            char_layout.addWidget(no_chars)
        form_layout.addRow(char_group)

        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("💾 Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        button_layout.addWidget(save_btn)
        cancel_btn = QPushButton("✕ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _load_tension(self):
        t = self.tension
        # Type
        for i in range(self.type_combo.count()):
            if self.type_combo.item(i).data(
                    Qt.ItemDataRole.UserRole) == t.tension_type:
                self.type_combo.setCurrentRow(i)
                break
        self.title_edit.setText(t.title)
        self.description_edit.setPlainText(t.description)
        self.stakes_edit.setPlainText(t.stakes)
        for i in range(self.state_combo.count()):
            if self.state_combo.item(i).data(
                    Qt.ItemDataRole.UserRole) == t.current_state:
                self.state_combo.setCurrentRow(i)
                break
        self.intensity_slider.setValue(int(t.intensity))
        for i in range(self.characters_list.count()):
            it = self.characters_list.item(i)
            if it.text() in t.characters_involved:
                it.setSelected(True)

    def _save(self):
        from PyQt6.QtWidgets import QMessageBox
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing title",
                                "Please give this tension a title.")
            return
        type_item = self.type_combo.currentItem()
        state_item = self.state_combo.currentItem()
        if not type_item or not state_item:
            return
        chars = [self.characters_list.item(i).text()
                 for i in range(self.characters_list.count())
                 if self.characters_list.item(i).isSelected()]
        if self.is_new:
            import uuid
            self.tension = CharacterTension(
                id=str(uuid.uuid4()),
                title=title,
                description=self.description_edit.toPlainText().strip(),
                tension_type=type_item.data(Qt.ItemDataRole.UserRole),
                characters_involved=chars,
                stakes=self.stakes_edit.toPlainText().strip(),
                current_state=state_item.data(
                    Qt.ItemDataRole.UserRole),
                intensity=int(self.intensity_slider.value()),
            )
        else:
            self.tension.title = title
            self.tension.description = (
                self.description_edit.toPlainText().strip())
            self.tension.tension_type = type_item.data(
                Qt.ItemDataRole.UserRole)
            self.tension.characters_involved = chars
            self.tension.stakes = (
                self.stakes_edit.toPlainText().strip())
            self.tension.current_state = state_item.data(
                Qt.ItemDataRole.UserRole)
            self.tension.intensity = int(
                self.intensity_slider.value())
        self.accept()

    def get_tension(self) -> 'CharacterTension':
        return self.tension


class ThemeEditor(QDialog):
    """Dialog for adding / editing a Theme.

    Same shape as TensionEditor / PromiseEditor: title + description
    + statement + motifs (one per line) + related characters
    multi-select. Returns a fully-populated Theme via
    :meth:`get_theme`.
    """

    def __init__(self, theme: 'Theme' = None,
                 available_characters: List[str] = None,
                 parent=None):
        super().__init__(parent)
        self.theme = theme
        self.available_characters = available_characters or []
        self.is_new = theme is None
        self._init_ui()
        if not self.is_new:
            self._load_theme()

    def _init_ui(self):
        self.setWindowTitle(
            "Edit Theme" if not self.is_new else "New Story Theme")
        self.setMinimumWidth(540)
        self.setMinimumHeight(540)

        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(
            "Short label, e.g. 'Cost of loyalty' or "
            "'Identity survives memory loss'")
        form_layout.addRow("Title:*", self.title_edit)

        self.statement_edit = QTextEdit()
        self.statement_edit.setPlaceholderText(
            "The argument the story makes (one or two sentences). "
            "E.g. \"Redemption requires confession, not just remorse — "
            "Marcus must speak the wrong he did before he can outrun "
            "it.\"")
        self.statement_edit.setMaximumHeight(80)
        form_layout.addRow("Statement:", self.statement_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "What the theme is exploring. What questions does it "
            "ask? What experience are you trying to give the reader?")
        self.description_edit.setMaximumHeight(100)
        form_layout.addRow("Description:", self.description_edit)

        self.motifs_edit = QTextEdit()
        self.motifs_edit.setPlaceholderText(
            "Recurring images / objects / phrases that signal this "
            "theme. One per line.\n"
            "E.g.:\n"
            "broken mirrors\n"
            "the encroaching frost\n"
            "Marcus's father's pocket watch")
        self.motifs_edit.setMaximumHeight(110)
        form_layout.addRow("Motifs (one per line):",
                           self.motifs_edit)

        char_group = QGroupBox("Related characters (whose arc carries this theme)")
        char_layout = QVBoxLayout(char_group)
        self.characters_list = QListWidget()
        self.characters_list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection)
        self.characters_list.setMaximumHeight(120)
        for name in self.available_characters:
            self.characters_list.addItem(name)
        char_layout.addWidget(self.characters_list)
        if not self.available_characters:
            no_chars = QLabel(
                "(No characters defined yet — add them in the "
                "Characters tab and they'll show up here.)")
            no_chars.setStyleSheet(
                "color: #6b7280; font-size: 11px;")
            char_layout.addWidget(no_chars)
        form_layout.addRow(char_group)

        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("💾 Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        button_layout.addWidget(save_btn)
        cancel_btn = QPushButton("✕ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _load_theme(self):
        t = self.theme
        self.title_edit.setText(t.title)
        self.statement_edit.setPlainText(t.statement)
        self.description_edit.setPlainText(t.description)
        self.motifs_edit.setPlainText("\n".join(t.motifs or []))
        for i in range(self.characters_list.count()):
            it = self.characters_list.item(i)
            if it.text() in t.related_characters:
                it.setSelected(True)

    def _save(self):
        from PyQt6.QtWidgets import QMessageBox
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing title",
                                "Please give this theme a title.")
            return
        motifs = [
            line.strip() for line in
            self.motifs_edit.toPlainText().splitlines()
            if line.strip()]
        chars = [self.characters_list.item(i).text()
                 for i in range(self.characters_list.count())
                 if self.characters_list.item(i).isSelected()]
        if self.is_new:
            import uuid
            self.theme = Theme(
                id=str(uuid.uuid4()),
                title=title,
                statement=self.statement_edit.toPlainText().strip(),
                description=(
                    self.description_edit.toPlainText().strip()),
                motifs=motifs,
                related_characters=chars,
            )
        else:
            self.theme.title = title
            self.theme.statement = (
                self.statement_edit.toPlainText().strip())
            self.theme.description = (
                self.description_edit.toPlainText().strip())
            self.theme.motifs = motifs
            self.theme.related_characters = chars
        self.accept()

    def get_theme(self) -> 'Theme':
        return self.theme
