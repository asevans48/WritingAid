"""Pre-write research pass for the writer agent.

Given a writing request and the project context dict, distills the
sprawling cast / world / plot scaffolding into a tight structured
brief that the writer agent embeds in place of the kitchen-sink
context dump. The brief names the specific characters, places, and
beats the writer should ground in.

Why this exists
---------------
The writer agent's prompt was getting flooded with the full character
roster, full worldbuilding set, and the whole plot map for every
write. Most of that is irrelevant to any single scene — the writer
ends up paying tokens to look up "is this character in the cast?"
before they can write a line. The research pass uses the LLM (or a
cheaper model routed through CreativeOS per-task settings) to pre-
chew the project into "WHO is in this scene, WHERE is it set, WHAT
just happened, what CONTINUITY constraints apply, what THEMES should
land". The writer call then only needs the manuscript anchors
(literal chapter text + previous-chapter ending) plus this brief.

Architectural shape
-------------------
This is the shape we expect to add for any "retrieve then act"
workflow (e.g. a future encyclopedia-research → write pipeline).
The research agent never writes prose; the writer agent never reaches
back into the project. Their interface is the brief.

The agent tolerates missing context blocks gracefully — it just
omits them from the brief. If the LLM call itself fails it falls
back to a deterministic skeleton brief built from the context
fields, so writer mode never silently degrades to no-context prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient


_RESEARCH_SYSTEM = (
    "You are a research librarian for a fiction writer. The writer "
    "is about to draft a scene; you produce a CONCISE structured "
    "brief naming the specific characters, places, beats, and "
    "constraints they should ground their prose in.\n\n"
    "OUTPUT FORMAT — emit EXACTLY this structure, nothing else "
    "(no preamble, no postamble, no apologies):\n\n"
    "WHO (characters present or pressing on the scene):\n"
    "- <Name>: <one-line trait + emotional state going INTO this "
    "scene + 'last seen in Ch N' if known>\n\n"
    "WHERE (locations / world details that anchor the scene):\n"
    "- <Name>: <one-line description + 1-2 sensory hooks "
    "(sight / sound / smell / touch) the writer can lean on>\n\n"
    "WHAT JUST HAPPENED (recent scene context):\n"
    "- Ch N: <one-sentence summary of the immediately preceding "
    "scene the writer will continue from, or 'opening scene — no "
    "prior continuity' if this is chapter 1>\n\n"
    "CONTINUITY (constraints the writer MUST respect):\n"
    "- POV: <first / third limited / etc., naming the POV "
    "character>\n"
    "- Tense: <past / present>\n"
    "- Open threads in play: <subplot / tension titles the scene "
    "should touch or honour>\n"
    "- Promises in play: <story-promise titles the scene should "
    "advance or not undermine>\n\n"
    "THEMES TO LAND:\n"
    "- <Theme title>: <one-line how the scene can echo it>\n\n"
    "RULES:\n"
    "• Pull names from the context blocks; do NOT invent characters, "
    "places, or themes that aren't listed.\n"
    "• If a section is empty (no relevant items), write '- (none "
    "applicable)' under that heading rather than omitting the "
    "heading.\n"
    "• Keep the entire brief under 600 words. Be specific over "
    "exhaustive.\n"
    "• DO NOT write any prose. The writer agent does that. You "
    "produce the brief and stop."
)


def _fallback_brief(writing_request: str, ctx: dict) -> str:
    """Deterministic brief built from raw context fields.

    Used when the LLM call fails so writer mode never silently
    drops to no-context prose. Less polished than the model-
    produced brief but always grounded in actual project data.
    """
    lines = ["WHO:"]
    chars = (ctx.get('characters') or '').strip()
    if chars:
        # Take the first ~6 lines of the characters block.
        for line in chars.splitlines()[:8]:
            line = line.strip()
            if line:
                lines.append(f"- {line.lstrip('- ')}")
    else:
        lines.append("- (none applicable)")

    lines.append("\nWHERE:")
    wb = (ctx.get('worldbuilding') or '').strip()
    if wb:
        for line in wb.splitlines()[:6]:
            line = line.strip()
            if line:
                lines.append(f"- {line.lstrip('- ')}")
    else:
        lines.append("- (none applicable)")

    lines.append("\nWHAT JUST HAPPENED:")
    if ctx.get('previous_chapter_ending'):
        snippet = ctx['previous_chapter_ending'][:200]
        lines.append(f"- prev chapter ended: {snippet}")
    elif ctx.get('current_chapter_title'):
        lines.append(
            f"- continuing within: {ctx['current_chapter_title']}")
    else:
        lines.append("- (no prior context recorded)")

    lines.append("\nCONTINUITY:")
    if ctx.get('writer_narrative_pov'):
        lines.append(f"- POV: {ctx['writer_narrative_pov']}")
    if ctx.get('writer_character_pov'):
        lines.append(
            f"- POV character: {ctx['writer_character_pov']}")
    if ctx.get('plot_tensions'):
        lines.append(
            "- Open tensions in play: see STORY TENSIONS context")

    lines.append("\nTHEMES TO LAND:")
    if ctx.get('plot_themes'):
        themes = ctx['plot_themes'][:300]
        lines.append(f"- {themes}")
    else:
        lines.append("- (none applicable)")

    return "\n".join(lines)


def _assemble_research_user_block(writing_request: str,
                                    ctx: dict) -> str:
    """Build the user-block sent to the research LLM.

    Includes everything the librarian needs to name the right items —
    characters, worldbuilding, plot scaffolding, RAG-focused
    selections — but caps each section so the brief-producing call
    stays cheap. The writer agent gets the FULL anchors (chapter
    text, previous ending) separately; the research pass just needs
    enough to pick names.
    """
    parts = [f"WRITING REQUEST:\n{writing_request}"]

    if ctx.get('current_chapter_title'):
        parts.append(
            f"\nCURRENT CHAPTER: {ctx['current_chapter_title']}")
    if ctx.get('previous_chapter_ending'):
        parts.append(
            f"\nPREVIOUS CHAPTER ENDING (last lines):\n"
            f"{ctx['previous_chapter_ending'][:1200]}")

    # Plot scaffolding (small, always relevant)
    for key, label in (
        ('plot_freytag', 'FREYTAG STAGES'),
        ('plot_themes', 'STORY THEMES'),
        ('plot_promises', 'STORY PROMISES'),
        ('plot_tensions', 'STORY TENSIONS'),
        ('plot_subplots', 'SUBPLOTS'),
    ):
        if ctx.get(key):
            parts.append(f"\n{label}:\n{ctx[key][:1500]}")

    # Use RAG-focused chars/world if available — they're already
    # narrowed for this question. Fall back to the broad lists.
    if ctx.get('rag_focused_characters'):
        parts.append(
            f"\nCHARACTERS (RAG-focused for this scene):\n"
            f"{ctx['rag_focused_characters'][:2500]}")
    elif ctx.get('characters'):
        parts.append(f"\nCHARACTERS:\n{ctx['characters'][:2500]}")

    if ctx.get('rag_focused_worldbuilding'):
        parts.append(
            f"\nWORLDBUILDING (RAG-focused for this scene):\n"
            f"{ctx['rag_focused_worldbuilding'][:2500]}")
    elif ctx.get('worldbuilding'):
        parts.append(
            f"\nWORLDBUILDING:\n{ctx['worldbuilding'][:2500]}")

    # POV settings the writer must respect.
    pov_bits = []
    if ctx.get('writer_character_pov'):
        pov_bits.append(
            f"Character POV: {ctx['writer_character_pov']}")
    if ctx.get('writer_narrative_pov'):
        pov_bits.append(
            f"Narrative POV: {ctx['writer_narrative_pov']}")
    if pov_bits:
        parts.append("\nPOV REQUIREMENTS:\n" + "\n".join(pov_bits))

    parts.append(
        "\nProduce the structured brief now using the format in "
        "your instructions.")
    return "\n".join(parts)


class ResearchAgent:
    """Pre-write research pass — distills context into a writer brief."""

    def __init__(self, llm: Optional["LLMClient"] = None):
        """``llm`` is optional at construction; ``research`` accepts
        a per-call override so the caller can route to a cheaper
        model (e.g. via ``creativeos_config.task_settings('general')``)
        without rebuilding the agent."""
        self.llm = llm

    def research(self, writing_request: str, ctx: dict,
                 llm: Optional["LLMClient"] = None,
                 *,
                 max_tokens: int = 700,
                 temperature: float = 0.3) -> str:
        """Produce the research brief.

        Args:
            writing_request: The user's write prompt verbatim.
            ctx: The context dict main_window.ChatWorker would have
                used. We don't mutate it.
            llm: Optional per-call LLM override. Falls back to the
                instance ``self.llm``.
            max_tokens: Cap on the brief — 600 words ≈ 700 tokens
                including format scaffolding.
            temperature: Low, since we want deterministic structured
                output, not creative variation.

        Returns:
            The brief as a string. Empty string only when there is
            literally nothing to brief on (no LLM AND no context to
            fall back on).
        """
        client = llm or self.llm
        user_block = _assemble_research_user_block(
            writing_request, ctx)
        if client is None:
            return _fallback_brief(writing_request, ctx)
        try:
            brief = client.generate_text(
                prompt=user_block,
                system_prompt=_RESEARCH_SYSTEM,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            print(f"[research] LLM call failed: {e}; "
                  f"using deterministic fallback brief")
            return _fallback_brief(writing_request, ctx)
        cleaned = (brief or "").strip()
        if not cleaned:
            return _fallback_brief(writing_request, ctx)
        return cleaned
