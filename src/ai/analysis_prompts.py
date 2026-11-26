"""The prompts of the editor's Analyze ▾ analyses (piece D.5).

Moved here, unchanged, from ``ChapterEditor`` in ``manuscript_editor.py``,
so the Critique's analysis reports (``analysis_reports``) and the old
result windows ("Show in a window (old)") ask the model exactly the same
thing. "Writing hints" had no prompt before D.5 (the menu entry said "will
be integrated soon"); its prompt is new, written in the same style.

Every function takes the project and the chapter (either may be ``None``)
and returns text; nothing here calls a model.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple


def chapter_sample(text: str) -> Optional[Tuple[str, str]]:
    """The chapter, sampled if very long: (sample, note), or None when empty."""
    if not (text or "").strip():
        return None
    word_count = len(text.split())
    if word_count > 3000:
        words = text.split()
        sample = ' '.join(words[:1500]) + "\n\n[...]\n\n" + ' '.join(words[-500:])
        note = f"(Analyzed sample: first 1500 + last 500 of {word_count} words)"
    else:
        sample = text
        note = f"({word_count} words)"
    return sample, note


# ── Prose: tone, style & voice ─────────────────────────────────────────

def prose_prompt(project: Any, text: str) -> str:
    sample, sample_note = chapter_sample(text) or ("", "(0 words)")

    # Build prose profile context if the project has targets set
    profile_context = ""
    profile_comparison_section = ""
    if project is not None and hasattr(project, 'prose_profile'):
        pp = project.prose_profile
        targets = []
        if pp.tone:
            targets.append(f"- **Target Tone:** {pp.tone}")
        if pp.style:
            targets.append(f"- **Target Style:** {pp.style}")
        if pp.voice:
            targets.append(f"- **Target Voice:** {pp.voice}")
        if pp.genre:
            targets.append(f"- **Target Genre:** {pp.genre}")
        if pp.notes:
            targets.append(f"- **Additional Notes:** {pp.notes}")
        if targets:
            profile_context = "\n\nPROJECT PROSE TARGETS (the author's intended direction):\n" + "\n".join(targets) + "\n"
            profile_comparison_section = """

## Alignment with Project Targets
Compare this chapter's actual prose against the author's stated targets above. For each target dimension (tone, style, voice, genre), rate the alignment as Strong Match, Partial Match, or Divergent. Explain specifically where the prose aligns and where it drifts. If there are gaps, suggest concrete adjustments the author could make to close them. Be honest — if the prose already nails a target, say so; if it misses, explain exactly how."""

    return f"""Analyze the following prose excerpt and provide a detailed assessment of THIS chapter's prose only. For every claim you make, explain your reasoning and cite short phrases from the text as evidence. Do not simply label — justify each observation. Focus exclusively on what is written in this chapter — do not reference characters, events, or content from other chapters or the broader project.
{profile_context}
PROSE {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Tone
Describe the emotional tone of the writing (e.g. dark, lighthearted, melancholic, tense, whimsical, foreboding, intimate, detached). Cite 2-3 short phrases that establish this tone and explain why each phrase produces that effect.

## Style
Describe the prose style. Consider sentence structure (short/punchy vs. flowing/complex), use of imagery, figurative language, level of detail, pacing, and paragraph rhythm. Is it minimalist, ornate, literary, conversational, cinematic? Explain what specific choices lead you to this conclusion.

## Voice
Describe the narrative voice. What personality comes through? Is it authoritative, confessional, sardonic, empathetic, clinical, poetic? How does the narrator relate to the reader? Point to specific passages that reveal the voice.

## Genre
Identify the genre and subgenre this prose belongs to. Consider the full range: literary fiction, dark fantasy, psychological thriller, magical realism, space opera, contemporary romance, horror, western, noir, dystopian, historical fiction, mystery, adventure, satire, southern gothic, cyberpunk, urban fantasy, military fiction, etc. Explain what genre signals are present — subject matter, tropes, conventions, setting cues, character archetypes, and reader expectations being set up. If the prose blends or subverts genre conventions, describe how and why that works or creates tension.
{profile_comparison_section}
## Comparable Authors
Name 2-3 published authors whose style this prose most resembles. For each, explain specifically which aspects align (e.g. sentence rhythm, imagery density, emotional register, thematic concerns, subject matter treatment) and which aspects diverge.

## Strengths
List 2-3 specific things this prose does well. For each, quote a brief example from the text and explain why it works.

## Areas to Watch
List 2-3 aspects the writer should be mindful of (not necessarily weaknesses, but tendencies that could become issues at scale). For each, explain the risk and suggest what to watch for. Be constructive."""


# ── Characters ─────────────────────────────────────────────────────────

def character_context(project: Any) -> str:
    """Character reference data from the project."""
    if project is None or not getattr(project, "characters", None):
        return ""

    parts = []
    for ch in project.characters:
        desc = [f"**{ch.name}** ({ch.character_type})"]
        if ch.personality:
            desc.append(f"  Personality: {ch.personality[:200]}")
        if ch.backstory:
            desc.append(f"  Backstory: {ch.backstory[:200]}")
        if ch.physical_description:
            desc.append(f"  Appearance: {ch.physical_description[:150]}")
        if ch.social_network:
            rels = ", ".join(f"{k}: {v}" for k, v in list(ch.social_network.items())[:5])
            desc.append(f"  Relationships: {rels}")
        if ch.notes:
            desc.append(f"  Notes: {ch.notes[:150]}")
        parts.append("\n".join(desc))

    return "\n\n".join(parts)


def character_prompt(project: Any, chapter: Any, text: str) -> Optional[str]:
    """None when the project has no characters."""
    sample, sample_note = chapter_sample(text) or ("", "(0 words)")
    char_context = character_context(project)
    if not char_context:
        return None

    # Include chapter planning characters if set
    planning_chars = ""
    planning = getattr(chapter, "planning", None)
    if planning and planning.characters_featured:
        planning_chars = f"\n\nCHARACTERS EXPECTED IN THIS CHAPTER:\n- " + "\n- ".join(
            planning.characters_featured)

    # Prose profile for voice context
    prose_context = ""
    if project is not None and hasattr(project, 'prose_profile') and project.prose_profile.voice:
        prose_context = f"\n\nPROJECT VOICE: {project.prose_profile.voice}"

    return f"""Analyze the following chapter for CHARACTER CONSISTENCY against the established character profiles below.

CRITICAL SCOPE RULE: ONLY analyze characters who actually appear, speak, or are mentioned BY NAME in the chapter text below. The character profiles are reference material — do NOT discuss characters who are absent from this chapter. Every observation MUST cite specific text from the chapter as evidence.

CHARACTER PROFILES (reference only — use these to check consistency for characters who appear):
{char_context}
{planning_chars}{prose_context}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Characters Present
List ONLY the characters who appear, speak, or are mentioned by name in this chapter. For each, note whether they have a defined profile above or are new/unnamed. Do NOT list characters from the profiles who are absent.

## Personality Consistency
For each character PRESENT IN THIS CHAPTER who has a profile, check whether their behavior, speech patterns, and actions are consistent with their defined personality. Cite dialogue or actions that align or conflict. Flag anything out of character.

## Relationship Consistency
Check whether character interactions IN THIS CHAPTER match the defined relationships (allies, enemies, family, etc.). Only assess relationships between characters who actually interact here.

## Backstory & Knowledge Consistency
Flag any moments in this chapter where a character demonstrates knowledge, skills, or references history that contradicts their backstory or established abilities.

## Physical Description Consistency
Note any physical descriptions IN THIS CHAPTER and check they match the character profiles. Flag contradictions (e.g., eye color, build, distinguishing features). Skip this section if no physical descriptions appear.

## Voice Distinctiveness
Assess whether characters who speak in this chapter have distinct voices in dialogue. Do they sound different from each other? Are speech patterns consistent with their personality and background?

## Advice
Provide 2-3 specific, actionable suggestions for improving character consistency or deepening characterization in THIS chapter. Focus only on what's written here."""


# ── Worldbuilding ──────────────────────────────────────────────────────

def world_context(project: Any) -> str:
    """Worldbuilding reference data from the project."""
    if project is None:
        return ""

    wb = project.worldbuilding
    parts = []

    # Places
    if wb.places:
        place_descs = []
        for p in wb.places[:10]:
            desc = f"- **{p.name}** ({p.place_type.value if hasattr(p.place_type, 'value') else p.place_type}): {p.description[:150]}"
            if p.climate:
                desc += f" | Climate: {p.climate}"
            if p.atmosphere:
                desc += f" | Atmosphere: {p.atmosphere[:80]}"
            place_descs.append(desc)
        parts.append("PLACES:\n" + "\n".join(place_descs))

    # Factions
    if wb.factions:
        faction_descs = []
        for f in wb.factions[:8]:
            desc = f"- **{f.name}** ({f.faction_type.value if hasattr(f.faction_type, 'value') else f.faction_type}): {f.description[:150]}"
            if f.leader:
                desc += f" | Leader: {f.leader}"
            faction_descs.append(desc)
        parts.append("FACTIONS:\n" + "\n".join(faction_descs))

    # Technologies
    if wb.technologies:
        tech_descs = [f"- **{t.name}**: {t.description[:100]}" for t in wb.technologies[:8]]
        parts.append("TECHNOLOGIES:\n" + "\n".join(tech_descs))

    # Cultures
    if wb.cultures:
        culture_descs = [f"- **{c.name}**: {c.description[:150]}" for c in wb.cultures[:6]]
        parts.append("CULTURES:\n" + "\n".join(culture_descs))

    # Historical Events
    if wb.historical_events:
        event_descs = [f"- **{e.name}** ({e.date}): {e.description[:100]}" for e in wb.historical_events[:8]]
        parts.append("HISTORICAL EVENTS:\n" + "\n".join(event_descs))

    # Planets
    if wb.star_systems or getattr(wb, 'planets_elements', None):
        planet_parts = []
        for ss in wb.star_systems[:4]:
            planet_parts.append(f"- **{ss.name}** ({ss.system_type}): {ss.description[:100]}")
            for planet in ss.planets[:3]:
                planet_parts.append(f"  - **{planet.name}** ({planet.planet_type.value if hasattr(planet.planet_type, 'value') else planet.planet_type}): {planet.description[:80]}")
        if planet_parts:
            parts.append("STAR SYSTEMS & PLANETS:\n" + "\n".join(planet_parts))

    # Flora & Fauna
    if wb.flora:
        flora_descs = [f"- **{fl.name}**: {fl.description[:80]}" for fl in wb.flora[:6]]
        parts.append("FLORA:\n" + "\n".join(flora_descs))
    if wb.fauna:
        fauna_descs = [f"- **{fa.name}**: {fa.description[:80]}" for fa in wb.fauna[:6]]
        parts.append("FAUNA:\n" + "\n".join(fauna_descs))

    # Myths
    if wb.myths:
        myth_descs = [f"- **{m.name}** ({m.myth_type}): {m.description[:100]}" for m in wb.myths[:6]]
        parts.append("MYTHS & LEGENDS:\n" + "\n".join(myth_descs))

    # Legacy text fields as fallback
    for field_name in ['mythology', 'climate', 'history', 'politics', 'military', 'economy']:
        val = getattr(wb, field_name, '')
        if val and val.strip():
            parts.append(f"{field_name.upper()}:\n{val[:300]}")

    return "\n\n".join(parts)


def world_prompt(project: Any, chapter: Any, text: str) -> Optional[str]:
    """None when the project has no worldbuilding."""
    sample, sample_note = chapter_sample(text) or ("", "(0 words)")
    world = world_context(project)
    if not world:
        return None

    # Include chapter planning locations if set
    planning_locs = ""
    planning = getattr(chapter, "planning", None)
    if planning and planning.locations:
        planning_locs = f"\n\nLOCATIONS EXPECTED IN THIS CHAPTER:\n- " + "\n- ".join(
            planning.locations)

    return f"""Analyze the following chapter for WORLDBUILDING CONSISTENCY against the established world elements below.

CRITICAL SCOPE RULE: ONLY analyze world elements that are actually referenced, described, or relevant to what happens in this chapter. The worldbuilding data is reference material — do NOT discuss places, factions, technologies, or elements that never appear in this chapter. Every observation MUST cite specific text from the chapter as evidence.

ESTABLISHED WORLDBUILDING (reference only — use these to check consistency for elements that appear):
{world}
{planning_locs}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## World Elements Present
List ONLY the places, factions, technologies, cultures, creatures, and world-specific elements that are actually mentioned or described in this chapter. Note whether each has a defined profile in the worldbuilding data. Do NOT list worldbuilding elements that are absent from this chapter.

## Geographic & Setting Consistency
For locations that appear IN THIS CHAPTER, check that descriptions match the established profiles — climate, atmosphere, features, size, population. Flag any contradictions. Skip if no established locations appear.

## Faction & Political Consistency
For factions referenced IN THIS CHAPTER, check that behaviors, alliances, enemies, and power dynamics match the established worldbuilding. Skip if no factions appear.

## Technology & Magic Consistency
For technologies or magical systems used IN THIS CHAPTER, verify consistency with established rules and tech level. Flag anachronisms. Skip if none appear.

## Cultural Consistency
For cultural elements referenced IN THIS CHAPTER, check alignment with established cultures. Skip if none appear.

## Historical Accuracy
For historical references made IN THIS CHAPTER, check against established events and dates. Skip if none appear.

## Undeveloped World Elements
Note any NEW world elements introduced in this chapter that don't have profiles in the worldbuilding data. Suggest which ones should be formally added.

## Advice
Provide 2-3 specific, actionable suggestions for improving worldbuilding in THIS chapter. Focus on what's actually written — consider immersion, sensory details, and showing the world through character interaction rather than exposition."""


# ── Plot & pacing ──────────────────────────────────────────────────────

def plot_context(project: Any) -> str:
    """Plot reference data from the project."""
    if project is None:
        return ""

    sp = project.story_planning
    parts = []

    # Main plot
    if sp.main_plot:
        parts.append(f"MAIN PLOT:\n{sp.main_plot}")

    # Themes
    if sp.themes:
        parts.append("THEMES:\n- " + "\n- ".join(sp.themes))

    # Freytag pyramid events
    fp = sp.freytag_pyramid
    if fp.events:
        event_parts = []
        for evt in fp.events:
            event_parts.append(
                f"- [{evt.stage.upper()}] **{evt.title}**: {evt.description[:120]}"
                + (f" (Outcome: {evt.outcome[:80]})" if evt.outcome else "")
            )
        parts.append("PLOT EVENTS (Freytag Pyramid):\n" + "\n".join(event_parts))
    else:
        # Legacy text fields
        for stage in ['exposition', 'rising_action', 'climax', 'falling_action', 'resolution']:
            val = getattr(fp, stage, '')
            if val and val.strip():
                parts.append(f"{stage.upper().replace('_', ' ')}:\n{val[:200]}")

    # Subplots
    if sp.subplots:
        subplot_parts = []
        for sub in sp.subplots:
            subplot_parts.append(
                f"- **{sub.title}** ({sub.status}): {sub.description[:120]}"
                + (f" | Connection: {sub.connection_to_main[:80]}" if sub.connection_to_main else "")
            )
        parts.append("SUBPLOTS:\n" + "\n".join(subplot_parts))

    # Story promises
    if sp.promises:
        promise_parts = [f"- [{p.promise_type}] **{p.title}**: {p.description[:100]}" for p in sp.promises]
        parts.append("STORY PROMISES:\n" + "\n".join(promise_parts))

    return "\n\n".join(parts)


def chapter_plan_context(chapter: Any) -> str:
    """The chapter-specific planning context."""
    cp = getattr(chapter, "planning", None)
    if not cp:
        return ""

    parts = []
    if cp.description:
        parts.append(f"CHAPTER DESCRIPTION: {cp.description}")
    if cp.events:
        event_parts = [
            f"- [{e.stage}] {e.text}: {e.description[:100]}" + (" ✓" if e.completed else "")
            for e in cp.events
        ]
        parts.append("PLANNED EVENTS:\n" + "\n".join(event_parts))
    if cp.scene_list:
        parts.append("PLANNED SCENES:\n- " + "\n- ".join(cp.scene_list))
    if cp.themes:
        parts.append("CHAPTER THEMES:\n- " + "\n- ".join(cp.themes))
    if cp.pov_character:
        parts.append(f"POV CHARACTER: {cp.pov_character}")
    if cp.timeline_position:
        parts.append(f"TIMELINE POSITION: {cp.timeline_position}")
    if cp.tone:
        parts.append(f"CHAPTER TONE: {cp.tone}")
    if cp.notes:
        parts.append(f"NOTES: {cp.notes[:300]}")

    return "\n".join(parts)


def plot_prompt(project: Any, chapter: Any, text: str) -> Optional[str]:
    """None when there is neither a story plan nor a chapter plan."""
    sample, sample_note = chapter_sample(text) or ("", "(0 words)")
    plot = plot_context(project)
    chapter_plan = chapter_plan_context(chapter)
    if not plot and not chapter_plan:
        return None

    # Prose profile for pacing context
    prose_context = ""
    if project is not None and hasattr(project, 'prose_profile'):
        pp = project.prose_profile
        ctx_parts = []
        if pp.genre:
            ctx_parts.append(f"Genre: {pp.genre}")
        if pp.tone:
            ctx_parts.append(f"Target Tone: {pp.tone}")
        if ctx_parts:
            prose_context = "\n\nPROSE PROFILE:\n" + "\n".join(ctx_parts)

    # Get chapter number for arc position context
    chapter_position = ""
    if getattr(chapter, "number", None):
        total = 0
        if project is not None and project.manuscript and project.manuscript.chapters:
            total = len(project.manuscript.chapters)
        chapter_position = f"\n\nCHAPTER POSITION: Chapter {chapter.number}" + (f" of {total}" if total else "")

    return f"""Analyze the following chapter for PLOT ADHERENCE AND PACING against the story plan below.

CRITICAL SCOPE RULE: ONLY analyze what actually happens in this chapter. The story plan is reference material for checking alignment — do NOT summarize or discuss plot events, subplots, or promises that are not touched by this chapter. Every observation MUST cite specific text from the chapter as evidence.

STORY PLAN (reference only — use to check alignment):
{plot}

CHAPTER PLAN:
{chapter_plan if chapter_plan else "(No specific chapter plan set)"}
{prose_context}{chapter_position}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your analysis in these sections:

## Plot Events in This Chapter
List which planned plot events or chapter events actually occur in this chapter. For each, note if it's fully executed, partially addressed, or just hinted at. Cite the relevant text. Only list events that are actually present.

## Plot Advancement
Assess how this chapter advances the main plot based on what's written. Does it move the story forward meaningfully, or does it stall? What story questions does it raise or answer? Cite specific moments.

## Subplot Progress
Identify which subplots (if any) are advanced in this chapter. Only discuss subplots that are actually touched here. Are connections to the main plot maintained?

## Pacing Assessment
Evaluate the pacing of this chapter as written. Is it well-balanced between action, dialogue, reflection, and description? Flag specific sections that drag or feel rushed, citing the text.

## Story Promise Fulfillment
Check whether this chapter works toward fulfilling any story promises that are relevant to its content. Only discuss promises that are actually touched here.

## Theme Integration
Assess how themes are expressed in this chapter through action and character. Only discuss themes that are actually present in the text.

## Structural Position
Evaluate whether this chapter's content is appropriate for its position in the narrative arc. Is the tension level right for where we are in the story?

## Advice
Provide 3-4 specific, actionable suggestions for improving THIS chapter's plot effectiveness. Focus on what's written — consider missing beats, pacing adjustments, tension opportunities, foreshadowing, and scene ordering. Do not suggest adding content from other parts of the story plan that don't belong in this chapter."""


# ── Writing hints (new in D.5) ─────────────────────────────────────────

def hints_prompt(project: Any, chapter: Any, text: str) -> str:
    """Practical next-draft hints for this chapter. The menu entry promised
    "AI writing hints"; this is that, in the other analyses' style."""
    sample, sample_note = chapter_sample(text) or ("", "(0 words)")
    plan = chapter_plan_context(chapter)
    targets = []
    pp = getattr(project, "prose_profile", None) if project is not None else None
    for label, attr in (("Genre", "genre"), ("Target Tone", "tone"), ("Target Voice", "voice")):
        value = (getattr(pp, attr, "") or "").strip() if pp is not None else ""
        if value:
            targets.append(f"- {label}: {value}")
    context = ""
    if plan:
        context += f"\n\nCHAPTER PLAN (the author's intent):\n{plan}"
    if targets:
        context += "\n\nPROJECT PROSE TARGETS:\n" + "\n".join(targets)

    return f"""Give the author practical writing hints for their next pass over THIS chapter. Read it as an experienced fiction editor would. Every hint MUST quote a short phrase from the chapter (in quotation marks) and say what to try there and why. Do not rewrite the passage for the author — describe the change. Do not discuss other chapters.{context}

CHAPTER TEXT {sample_note}:
---
{sample}
---

Provide your hints in these sections:

## What Is Working
2-3 things this chapter already does well that the author should keep doing. Quote an example of each.

## Hints for the Next Pass
5-8 specific hints, most useful first. Consider scene goals and stakes, openings and endings of scenes, showing versus telling, sensory detail, dialogue and subtext, sentence rhythm, and anything that slows the reader. For each: quote the passage, then the hint.

## One Thing to Try
The single change most likely to lift this chapter, in two or three sentences."""
