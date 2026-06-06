"""AI scene director — generate scenes from a chapter using graph RAG.

The director composes a single LLM call per generation request and
returns ``[Scene]`` ready to drop onto the studio canvas. It pulls
context from the existing GraphRAG layer so scenes are grounded in
the project's characters, worldbuilding, plot, and chapter prose
— the user explicitly asked for this.

Two entry points:
  * ``generate_scenes_for_chapter(chapter, ...)`` — make N scenes
    that walk through the chapter's beats. Used when a user picks
    "auto-fill scenes from this chapter".
  * ``rewrite_scene(scene, ...)`` — refine a single scene's
    description / prompt using the same RAG context. Used when a
    user clicks "Ask AI to improve" on a card.

Both fall back gracefully when an LLM isn't configured — they
return whatever heuristic scenes can be built from the raw text so
the studio is still usable offline.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

from src.video_studio.models import Scene, VideoStudio


# Hard cap so we never demand a 30-scene generation from the LLM —
# longer chapters get split across multiple director calls in the
# future; for now a sensible single-call budget.
_MAX_SCENES_PER_CALL = 12
_DEFAULT_SCENES_PER_CHAPTER = 6


def generate_scenes_for_chapter(
    chapter: Any,
    project: Any,
    llm: Optional[Any] = None,
    rag_system: Optional[Any] = None,
    scene_count: int = _DEFAULT_SCENES_PER_CHAPTER,
    default_duration: float = 8.0,
    prefer_planned_beats: bool = True,
) -> List[Scene]:
    """Build a list of scenes covering the chapter's beats.

    Each scene gets:
      * ``name`` — short, evocative title
      * ``description`` — 1-3 sentence beat
      * ``prompt`` — terse, image/video-prompt style
      * ``chapter_id`` / ``chapter_number`` — anchored back to source
      * ``character_refs`` — names of characters present in this beat

    When ``prefer_planned_beats=True`` (the default) and the chapter
    has scene names in ``ChapterPlanning.scene_list`` OR plot events
    in ``project.story_planning.freytag_pyramid.events`` whose
    related_characters overlap this chapter's featured cast, those
    beats are used as the source of truth — one card per beat, with
    the count coming from the plan rather than ``scene_count``. The
    LLM only enriches each beat with a visual prompt and grounded
    character refs; the writer's structural intent is preserved.

    When no planned beats are detected, falls back to the existing
    "generate ``scene_count`` scenes from the prose" path.

    When ``llm`` is None or the call fails, falls back to a
    deterministic chunking of the chapter prose so the user still
    gets a usable starting point.
    """
    scene_count = max(1, min(scene_count, _MAX_SCENES_PER_CALL))
    chapter_text = (getattr(chapter, "content", "") or "").strip()
    chapter_title = (
        getattr(chapter, "title", "") or "Untitled Chapter")
    chapter_id = getattr(chapter, "id", "")
    chapter_number = getattr(chapter, "number", 0)

    if not chapter_text:
        return []

    rag_context = _gather_rag_context(chapter_text, rag_system)
    plot_context = _summarize_plot_context(chapter, project)
    # Focus character detail on the chapter's featured cast — they get
    # full appearance / personality / voice blocks; everyone else
    # appears as a name-only entry so the model recognizes the wider
    # roster without bloating the context.
    featured_names = []
    planning = getattr(chapter, "planning", None)
    if planning is not None:
        featured_names = list(
            getattr(planning, "characters_featured", []) or [])
    char_context = _summarize_characters(
        project, focus_names=featured_names)
    # NEW: settings block. The previous director left the LLM to
    # invent locations from chapter prose alone; now we surface each
    # location named in the chapter's planning with its
    # worldbuilding entry (atmosphere, climate, key features,
    # dangers, etc.) so the text-to-video prompt has enough setting
    # detail to render a place that matches the writer's canon.
    settings_context = _summarize_settings(project, chapter)

    # NEW: planned-beats path. When the chapter has explicit scenes
    # or relevant plot events, use them as the storyboard skeleton.
    planned_beats: List[dict] = []
    if prefer_planned_beats:
        planned_beats = _collect_planned_beats(chapter, project)
    if planned_beats:
        if llm is not None:
            enriched = _llm_enrich_planned_beats(
                llm=llm,
                chapter_title=chapter_title,
                chapter_text=chapter_text,
                planned_beats=planned_beats,
                rag_context=rag_context,
                plot_context=plot_context,
                character_context=char_context,
                settings_context=settings_context,
            )
            if enriched:
                return _finalize_scenes(
                    enriched, chapter_id, chapter_number,
                    default_duration)
        # No LLM / enrichment failed — build bare scenes from the
        # plan so the writer's structure still lands on the board.
        return _bare_scenes_from_planned_beats(
            planned_beats, chapter_id, chapter_number,
            chapter_title)

    # No planned beats — fall back to the prose-driven path.
    if llm is not None:
        scenes = _llm_generate_scenes(
            llm=llm,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            scene_count=scene_count,
            rag_context=rag_context,
            plot_context=plot_context,
            character_context=char_context,
            settings_context=settings_context,
        )
        if scenes:
            return _finalize_scenes(
                scenes, chapter_id, chapter_number, default_duration)

    # No-LLM / failure path — chunk the chapter into beats by
    # paragraph clusters and synthesize a minimal description.
    return _heuristic_scenes_from_text(
        chapter_text, chapter_title, scene_count,
        chapter_id, chapter_number, default_duration)


# ---------------------------------------------------------------------
# Planned-beats discovery
# ---------------------------------------------------------------------
def detect_planned_beats_count(chapter: Any, project: Any) -> int:
    """How many planned beats can we extract for this chapter?

    Cheap to call — the AI fill dialog uses it to surface a "Found
    N planned beats" hint and pre-fill the scene-count spinner.
    """
    return len(_collect_planned_beats(chapter, project))


def _collect_planned_beats(
    chapter: Any, project: Any,
) -> List[dict]:
    """Extract a sequence of beats from the writing module.

    Returns a list of dicts shaped like
    ``{"name": str, "hint": str, "source": str}``. Sources, in order
    of priority:

      1. ``chapter.planning.events`` — the writer's chapter plot
         arc (filled in via the chapter planner's event generator).
         Strongest signal because each event already carries a
         title, description, and arc stage. ONE beat per event,
         ordered by ``order``.
      2. ``chapter.planning.scene_list`` — explicit scene names
         when the arc isn't populated.
      3. ``project.story_planning.freytag_pyramid.events`` filtered
         to events whose ``related_characters`` overlap the chapter's
         featured cast (chapter is one beat in the larger arc).

    We do NOT mix sources — if ``planning.events`` is populated, we
    trust it; falling through to scene_list and then plot events
    only when each prior signal is empty.
    """
    if chapter is None:
        return []
    planning = getattr(chapter, "planning", None)
    beats: List[dict] = []

    # Primary: chapter's own plot arc (planning.events). Each
    # StoryEvent already has title + description + stage so we get a
    # high-fidelity skeleton straight away. Sort by ``order`` so the
    # storyboard mirrors the arc the writer laid out, not the storage
    # order which can drift after edits.
    if planning is not None:
        chapter_events = list(getattr(planning, "events", []) or [])
        if chapter_events:
            chapter_events.sort(
                key=lambda e: getattr(e, "order", 0))
            for ev in chapter_events:
                title = (getattr(ev, "text", "") or "").strip()
                if not title:
                    continue
                desc = (getattr(ev, "description", "") or "").strip()
                stage = (getattr(ev, "stage", "") or "").strip()
                hint_parts: List[str] = []
                if desc:
                    hint_parts.append(desc)
                if stage:
                    hint_parts.append(f"arc stage: {stage}")
                beats.append({
                    "name": title,
                    "hint": " — ".join(hint_parts),
                    "source": "chapter_planning_event",
                })
            if beats:
                return beats

    # Secondary: explicit scene_list when the arc is empty.
    if planning is not None:
        scene_list = list(getattr(planning, "scene_list", []) or [])
        for raw in scene_list:
            name = (raw or "").strip()
            if not name:
                continue
            beats.append({
                "name": name,
                "hint": "",
                "source": "scene_list",
            })
        if beats:
            return beats

    # Tertiary: plot events from the Freytag pyramid that touch
    # this chapter's characters. Each event becomes one beat.
    if project is None:
        return beats
    featured: set = set()
    if planning is not None:
        for c in (getattr(planning, "characters_featured", []) or []):
            n = (c or "").strip().lower()
            if n:
                featured.add(n)
    sp = getattr(project, "story_planning", None)
    fp = getattr(sp, "freytag_pyramid", None) if sp else None
    events = getattr(fp, "events", []) if fp else []
    for event in events or []:
        related = [
            (r or "").strip().lower()
            for r in (
                getattr(event, "related_characters", []) or [])]
        # If the chapter has no featured cast, we can't reliably
        # match — skip event-based beats rather than dragging in
        # the whole plot.
        if not featured:
            continue
        if not any(r in featured for r in related if r):
            continue
        title = (getattr(event, "title", "") or "").strip()
        desc = (getattr(event, "description", "") or "").strip()
        outcome = (getattr(event, "outcome", "") or "").strip()
        hint_parts = []
        if desc:
            hint_parts.append(desc)
        if outcome:
            hint_parts.append(f"outcome: {outcome}")
        beats.append({
            "name": title or "Plot beat",
            "hint": " — ".join(hint_parts),
            "source": "plot_event",
        })

    return beats


def _bare_scenes_from_planned_beats(
    beats: List[dict],
    chapter_id: str, chapter_number: int,
    chapter_title: str,
) -> List[Scene]:
    """Build minimal Scene objects from beats when no LLM is
    available. Each scene gets the beat's name verbatim plus a
    placeholder prompt seeded from the hint."""
    scenes: List[Scene] = []
    for beat in beats:
        name = beat["name"]
        hint = beat.get("hint", "")
        prompt = (hint or
                  f"Cinematic frame of '{name}' in {chapter_title}.")
        scenes.append(Scene(
            name=name,
            description=hint or f"Beat: {name}",
            prompt=prompt,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
        ))
    return scenes


def _llm_enrich_planned_beats(
    llm: Any,
    chapter_title: str,
    chapter_text: str,
    planned_beats: List[dict],
    rag_context: str,
    plot_context: str,
    character_context: str,
    settings_context: str = "",
) -> List[dict]:
    """Ask the LLM to flesh out each planned beat with description,
    visual prompt, and character_refs — without inventing new beats
    or dropping any. Returns a list shaped like the existing
    _llm_generate_scenes output."""
    beats_block = "\n".join(
        f"  {i + 1}. {b['name']}"
        + (f"  ({b['hint']})" if b.get("hint") else "")
        for i, b in enumerate(planned_beats))
    system_prompt = (
        "You are a video-storyboard director. The writer has "
        "already planned the scenes for this chapter — your job is "
        "to enrich each ONE with a visual description and "
        "text-to-video prompt grounded in the chapter prose and "
        "the project's characters / worldbuilding. Output exactly "
        "ONE scene per planned beat, in the order given. Do not "
        "merge beats, do not insert beats, do not drop beats. "
        "Names must match the planned beat names verbatim unless a "
        "name is empty (in which case generate one). Character "
        "names must be exactly as they appear in CHARACTERS below. "
        "**Settings**: when a beat takes place at a named location "
        "from the SETTINGS block, your prompt MUST use the "
        "atmosphere, climate, key features, and dangers from that "
        "location's worldbuilding entry — never invent generic "
        "scenery for a place the writer has already described.")
    user_prompt = f"""
Chapter title: {chapter_title}

PLANNED BEATS (one storyboard scene per item, in this order):
{beats_block}

For each beat, produce:
  * name: the planned beat name (verbatim)
  * description: 1-2 sentences of narrative detail grounding the
                 beat in the chapter prose
  * prompt: 2-3 sentences of detailed visual prompt for a
            text-to-video model:
              - WHERE: name the location explicitly + drop in 2-3
                concrete setting details (atmosphere, climate, key
                features, time of day, materials)
              - WHO: name each character + 1-2 distinguishing
                appearance details from the CHARACTERS block
                (clothing, build, defining feature)
              - WHAT: the action, camera framing, lighting cue
            No abstract themes; concrete imagery only.
  * character_refs: list of character names present in this beat

PLOT CONTEXT:
{plot_context or "(none)"}

CHARACTERS (use these names verbatim; appearance / voice details
provided so prompts render likeness consistently):
{character_context or "(none)"}

SETTINGS (each location named in the chapter's planning, with
worldbuilding atmosphere / features / climate so prompts render
the place the writer described — not a generic stand-in):
{settings_context or "(none — invent settings only when chapter prose dictates)"}

RAG CONTEXT (graph-aware project lookup):
{rag_context or "(none)"}

CHAPTER PROSE (first 2500 words):
{" ".join(chapter_text.split()[:2500])}

Output schema (JSON):
{{
  "scenes": [
    {{
      "name": "...",
      "description": "...",
      "prompt": "...",
      "character_refs": ["...", "..."]
    }}
  ]
}}
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=2400, temperature=0.6)
    except Exception as e:
        print(f"[video_studio] beat enrichment failed: {e}")
        return []
    parsed = _safe_parse_json_object(raw)
    if not parsed:
        return []
    raw_scenes = parsed.get("scenes")
    if not isinstance(raw_scenes, list):
        return []
    cleaned: List[dict] = []
    for i, s in enumerate(raw_scenes):
        if not isinstance(s, dict):
            continue
        # If the LLM omitted a name or returned junk, fall back to
        # the planned beat name so the storyboard structure stays
        # aligned to the writer's plan.
        planned_name = (
            planned_beats[i]["name"]
            if i < len(planned_beats) else "")
        name = ((s.get("name") or "").strip()) or planned_name
        desc = (s.get("description") or "").strip()
        prompt = (s.get("prompt") or "").strip()
        refs = s.get("character_refs") or []
        if isinstance(refs, list):
            refs = [str(r).strip() for r in refs if str(r).strip()]
        else:
            refs = []
        if not (name and prompt):
            # Skip a malformed item rather than break alignment with
            # the planned-beat sequence — the rest of the list still
            # comes through.
            continue
        cleaned.append({
            "name": name,
            "description": desc,
            "prompt": prompt,
            "character_refs": refs,
        })
    # If the LLM dropped beats, top up with bare scenes from the
    # missing planned entries so we never silently lose structural
    # intent.
    if len(cleaned) < len(planned_beats):
        for i in range(len(cleaned), len(planned_beats)):
            beat = planned_beats[i]
            cleaned.append({
                "name": beat["name"],
                "description": beat.get("hint", ""),
                "prompt": (
                    beat.get("hint")
                    or f"Cinematic frame: {beat['name']}"),
                "character_refs": [],
            })
    return cleaned


def extract_actions_from_scene(
    scene: Any,
    chapter_text: str,
    project: Any,
    llm: Optional[Any],
    rag_system: Optional[Any] = None,
    max_actions: int = 8,
) -> List[dict]:
    """Break a scene into discrete actions the writer can verify.

    Each action returned is a dict shaped like::

        {
          "name": "Mara crosses the threshold",
          "description": "She steps from the rain-slick courtyard
                          into the lamp-lit ring.",
          "character_refs": ["Mara"],
          "location_refs": ["Council Chamber"],
          "scenery_details": "rain-slick stone, lamp glow, hush",
          "prose_excerpt": "Mara stepped from the rain-slick
                            courtyard into the lamp-lit ring..."
        }

    The caller turns each dict into a ``SceneAction`` via
    ``Scene.add_action`` and edits as needed. Empty list on any
    failure / no LLM so the UI can fall back to manual entry.

    Grounding prose precedence: when the scene has a saved
    ``source_prose`` (set by the user via "Pull from chapter"),
    use that as the prose grounding instead of the chapter's full
    text — it's the exact passage the writer already approved.
    """
    if llm is None:
        return []
    scene_name = (getattr(scene, "name", "") or "").strip()
    scene_desc = (getattr(scene, "description", "") or "").strip()
    scene_prompt = (getattr(scene, "prompt", "") or "").strip()
    scene_chars = list(getattr(scene, "character_refs", []) or [])
    # Prefer the user-curated prose excerpt over the chapter dump
    # when present — that's the writer's intent crystallized.
    source_prose = (getattr(scene, "source_prose", "") or "").strip()
    grounding_prose = source_prose or chapter_text or ""

    plot_context = _summarize_plot_context(
        getattr(scene, "_chapter", None), project)
    char_context = _summarize_characters(
        project, focus_names=scene_chars)
    settings_context = ""
    # Pull settings from any chapter linked to this scene.
    chapter_obj = None
    if project is not None:
        chapter_id = getattr(scene, "chapter_id", "")
        if chapter_id:
            manuscript = getattr(project, "manuscript", None)
            chapters = (getattr(manuscript, "chapters", [])
                        if manuscript else [])
            for ch in chapters or []:
                if getattr(ch, "id", "") == chapter_id:
                    chapter_obj = ch
                    break
    if chapter_obj is not None:
        settings_context = _summarize_settings(project, chapter_obj)

    # Optional RAG anchor — feeds the same retrieval the rest of the
    # director uses so action breakdowns stay grounded.
    rag_context = _gather_rag_context(scene_prompt or scene_desc,
                                       rag_system)

    system_prompt = (
        "You are a video-storyboard director breaking ONE scene "
        "into discrete actions a video model can render as separate "
        "shots. Each action is one continuous beat: a single move, "
        "reveal, or reaction. Action names are 4-8 word verb "
        "phrases (the kind that would label a storyboard panel). "
        "Descriptions are 1-2 sentences of concrete visible "
        "action — who does what, where, with what immediate "
        "consequence. Character names must be VERBATIM from the "
        "CHARACTERS block; location names must be VERBATIM from "
        "the SETTINGS block. For prose_excerpt, copy the SHORTEST "
        "verbatim span (1-3 sentences) from the PROSE block that "
        "corresponds to this action — no paraphrasing, no edits. "
        "If no prose covers the action, return an empty string. "
        "Output strictly JSON.")
    user_prompt = f"""
Scene name: {scene_name or "(unnamed)"}
Scene description: {scene_desc or "(none)"}
Scene visual prompt: {scene_prompt or "(none)"}
Scene character refs: {", ".join(scene_chars) if scene_chars else "(none)"}

Break this scene into 3-{max_actions} actions in the order they
play out. For each action emit:
  * name: 4-8 word verb phrase (storyboard label)
  * description: 1-2 sentences of concrete visible action
  * character_refs: subset of scene's characters present in THIS
                    action (use names verbatim from CHARACTERS)
  * location_refs: subset of scene's settings used (verbatim from
                   SETTINGS; empty when the scene stays in one place)
  * scenery_details: short prop / lighting / atmosphere notes
                     specific to this action
  * prose_excerpt: VERBATIM 1-3 sentence span from PROSE that
                   covers this action (empty string if none fits)

CHARACTERS:
{char_context or "(none)"}

SETTINGS:
{settings_context or "(none)"}

PLOT CONTEXT:
{plot_context or "(none)"}

RAG CONTEXT:
{rag_context or "(none)"}

PROSE (grounding — copy verbatim spans into prose_excerpt):
{" ".join((grounding_prose or "").split()[:2000])}

Output schema (JSON):
{{
  "actions": [
    {{
      "name": "...",
      "description": "...",
      "character_refs": ["..."],
      "location_refs": ["..."],
      "scenery_details": "...",
      "prose_excerpt": "..."
    }}
  ]
}}
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=1800, temperature=0.5)
    except Exception as e:
        print(f"[video_studio] extract_actions LLM call failed: {e}")
        return []
    parsed = _safe_parse_json_object(raw)
    if not parsed:
        return []
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return []
    cleaned: List[dict] = []
    for a in actions[:max_actions]:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        desc = (a.get("description") or "").strip()
        if not (name and desc):
            continue
        chars = a.get("character_refs") or []
        locs = a.get("location_refs") or []
        scen = (a.get("scenery_details") or "").strip()
        excerpt = (a.get("prose_excerpt") or "").strip()
        cleaned.append({
            "name": name,
            "description": desc,
            "character_refs": [
                str(c).strip()
                for c in (chars if isinstance(chars, list) else [])
                if str(c).strip()],
            "location_refs": [
                str(l).strip()
                for l in (locs if isinstance(locs, list) else [])
                if str(l).strip()],
            "scenery_details": scen,
            "prose_excerpt": excerpt,
        })
    return cleaned


def enrich_action_with_graphrag(
    action: Any,
    scene: Any,
    project: Any,
    llm: Optional[Any],
    rag_system: Optional[Any] = None,
) -> dict:
    """Use the project's graphRAG + structured entity data to flesh
    out one SceneAction's description and scenery details.

    The action already has user-curated name / description / refs /
    prose_excerpt. We feed all of that plus graphRAG context to the
    LLM and ask for a fuller description and scenery block grounded
    in the actual character and worldbuilding entries — so the
    writer doesn't have to retype detail that already lives in the
    encyclopedia.

    Returns a dict shaped like::

        {
          "description": "<enriched description>",
          "scenery_details": "<enriched scenery>",
          "character_refs": [...],   # may add names the prose names
          "location_refs": [...],    # may add named places
        }

    Empty dict on any failure / no LLM. Caller decides which fields
    to apply — typical UX is to overwrite description + scenery and
    merge refs.
    """
    if llm is None:
        return {}
    a_name = (getattr(action, "name", "") or "").strip()
    a_desc = (getattr(action, "description", "") or "").strip()
    a_excerpt = (
        getattr(action, "prose_excerpt", "") or "").strip()
    a_scenery = (
        getattr(action, "scenery_details", "") or "").strip()
    a_chars = list(getattr(action, "character_refs", []) or [])
    a_locs = list(getattr(action, "location_refs", []) or [])
    scene_prompt = (getattr(scene, "prompt", "") or "").strip()
    scene_chars = list(getattr(scene, "character_refs", []) or [])

    # Lookup the linked chapter for setting context.
    chapter_obj = None
    if project is not None:
        chapter_id = getattr(scene, "chapter_id", "")
        if chapter_id:
            manuscript = getattr(project, "manuscript", None)
            chapters = (getattr(manuscript, "chapters", [])
                        if manuscript else [])
            for ch in chapters or []:
                if getattr(ch, "id", "") == chapter_id:
                    chapter_obj = ch
                    break

    # Focus character summarizer on whichever refs we've got — the
    # action's own list takes priority, falling back to scene refs
    # so we always pull SOME character detail.
    focus = a_chars or scene_chars
    char_context = _summarize_characters(project, focus_names=focus)
    settings_context = _summarize_settings(project, chapter_obj)

    # GraphRAG query: blend everything we know about this beat so
    # the retriever surfaces relevant entities (characters, places,
    # items, factions, etc.) even when the names aren't in the refs
    # yet. Truncated at 600 chars internally by _gather_rag_context.
    query = " ".join([
        x for x in [a_name, a_desc, a_excerpt, scene_prompt] if x])
    rag_context = _gather_rag_context(query, rag_system)

    if not (char_context or settings_context or rag_context):
        # Nothing to enrich with — return early so we don't waste
        # an LLM call.
        return {}

    system_prompt = (
        "You are a video-storyboard director enriching ONE action's "
        "visible detail. Use the CHARACTERS, SETTINGS, and RAG "
        "blocks to fold concrete, named detail into the description "
        "and scenery — appearance, clothing, atmosphere, sensory "
        "anchors. Do NOT invent entities not present in those "
        "blocks. Keep the writer's wording when present in PROSE; "
        "expand only with details from the supplied context. Output "
        "strictly JSON.")
    user_prompt = f"""
ACTION
  name: {a_name or "(unnamed)"}
  current description: {a_desc or "(none)"}
  scenery so far: {a_scenery or "(none)"}
  characters in this action: {", ".join(a_chars) if a_chars else "(none)"}
  locations in this action: {", ".join(a_locs) if a_locs else "(none)"}
  prose excerpt (verbatim): {a_excerpt or "(none)"}

SCENE PROMPT
{scene_prompt or "(none)"}

CHARACTERS
{char_context or "(none)"}

SETTINGS
{settings_context or "(none)"}

RAG CONTEXT (graph-aware retrieval over project entities)
{rag_context or "(none)"}

Task:
Return an enriched description (1-3 sentences) and scenery details
(short block: lighting, atmosphere, props, sensory cues) that fold
the supplied entity detail into this action. ALSO list any
additional character_refs and location_refs that appear in the
prose excerpt or that the entity context makes obvious. Use names
VERBATIM from the CHARACTERS / SETTINGS blocks.

Output schema (JSON):
{{
  "description": "...",
  "scenery_details": "...",
  "character_refs": ["..."],
  "location_refs": ["..."]
}}
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=900, temperature=0.4)
    except Exception as e:
        print(f"[video_studio] enrich_action LLM call failed: {e}")
        return {}
    parsed = _safe_parse_json_object(raw)
    if not parsed:
        return {}
    out: dict = {}
    desc = (parsed.get("description") or "").strip()
    if desc:
        out["description"] = desc
    scen = (parsed.get("scenery_details") or "").strip()
    if scen:
        out["scenery_details"] = scen
    raw_chars = parsed.get("character_refs") or []
    if isinstance(raw_chars, list):
        out["character_refs"] = [
            str(c).strip() for c in raw_chars if str(c).strip()]
    raw_locs = parsed.get("location_refs") or []
    if isinstance(raw_locs, list):
        out["location_refs"] = [
            str(l).strip() for l in raw_locs if str(l).strip()]
    return out


def rewrite_scene(
    scene: Scene,
    chapter: Optional[Any],
    project: Optional[Any],
    llm: Optional[Any],
    rag_system: Optional[Any] = None,
    instruction: str = "",
) -> Scene:
    """Ask the LLM to refine a scene's description and prompt.

    Returns the SAME ``Scene`` object with description/prompt
    updated in place (and updated_at touched). When the LLM is
    absent or errors out, returns the scene unchanged so the UI can
    surface the no-op cleanly.
    """
    if llm is None:
        return scene
    chapter_text = (
        (getattr(chapter, "content", "") or "") if chapter else "")
    rag_context = _gather_rag_context(chapter_text, rag_system)
    plot_context = _summarize_plot_context(chapter, project)
    char_context = _summarize_characters(project)

    system_prompt = (
        "You refine a single scene description and video-generation "
        "prompt. Keep the scene's intent unless the instruction "
        "explicitly asks otherwise. Use the graph context to ground "
        "characters and worldbuilding. Output strictly JSON with "
        "keys: name, description, prompt, character_refs. The "
        "prompt should be terse, visual, and ready for a "
        "text-to-video model.")
    user_prompt = f"""
Current scene:
  name: {scene.name}
  description: {scene.description}
  prompt: {scene.prompt}
  character_refs: {scene.character_refs}

Instruction from author: {instruction or "(improve clarity and visual specificity)"}

CHAPTER CONTEXT (excerpt):
{(chapter_text or "(none)")[:2000]}

PLOT CONTEXT:
{plot_context or "(none)"}

CHARACTERS:
{char_context or "(none)"}

RAG CONTEXT (graph-aware project lookup):
{rag_context or "(none)"}

Return JSON only.
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=600, temperature=0.6)
    except Exception:
        return scene
    parsed = _safe_parse_json_object(raw)
    if not parsed:
        return scene
    new_name = (parsed.get("name") or scene.name).strip()
    new_desc = (parsed.get("description") or scene.description).strip()
    new_prompt = (parsed.get("prompt") or scene.prompt).strip()
    new_chars = parsed.get("character_refs") or scene.character_refs
    if isinstance(new_chars, list):
        new_chars = [str(c).strip() for c in new_chars if str(c).strip()]
    else:
        new_chars = scene.character_refs
    if new_name:
        scene.name = new_name
    if new_desc:
        scene.description = new_desc
    if new_prompt:
        scene.prompt = new_prompt
    scene.character_refs = new_chars
    from datetime import datetime
    scene.updated_at = datetime.now()
    return scene


def auto_link_scenes_into_sequence(
    studio: VideoStudio,
    scenes: List[Scene],
) -> None:
    """Connect a freshly-generated batch of scenes with hops in
    sequence order. Idempotent — won't add a duplicate hop pair.

    Called by ``generate_scenes_for_chapter`` callers after they
    add the scenes to the studio."""
    for prev, nxt in zip(scenes, scenes[1:]):
        studio.add_hop(prev.id, nxt.id, label="next")


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------
def _llm_generate_scenes(
    llm: Any,
    chapter_title: str,
    chapter_text: str,
    scene_count: int,
    rag_context: str,
    plot_context: str,
    character_context: str,
    settings_context: str = "",
) -> List[dict]:
    system_prompt = (
        "You are a video-storyboard director. Given a chapter and "
        "supporting context (plot, worldbuilding, characters from "
        "the project's knowledge graph), produce a sequence of "
        "scenes that visualizes the chapter as a short video "
        "storyboard. Each scene is one shot or one beat of "
        "continuous action — short enough to render as a clip of "
        "a few seconds. Characters must be named with exactly the "
        "names from the project context so they can be matched "
        "back to character reference data. **Settings**: when a "
        "scene takes place at a named location from the SETTINGS "
        "block, your prompt MUST use that location's atmosphere, "
        "climate, key features, and dangers from worldbuilding — "
        "never invent generic scenery for a place the writer has "
        "already described. Output strictly JSON matching the "
        "schema. Do not include commentary.")
    user_prompt = f"""
Chapter title: {chapter_title}

Produce {scene_count} scenes that walk through this chapter as a
storyboard. Each scene needs:
  * name: 3-6 words, evocative title
  * description: 1-2 sentences of narrative beat
  * prompt: 2-3 sentences of detailed visual prompt for a
            text-to-video model:
              - WHERE: name the location explicitly + drop in 2-3
                concrete setting details (atmosphere, climate, key
                features, time of day, materials)
              - WHO: name each character + 1-2 distinguishing
                appearance details from the CHARACTERS block
                (clothing, build, defining feature)
              - WHAT: the action, camera framing, lighting cue
            No abstract themes; concrete imagery only.
  * character_refs: list of character names present in this beat
                    (use names exactly as they appear in CHARACTERS
                    below so they can be reference-matched)

PLOT CONTEXT:
{plot_context or "(none)"}

CHARACTERS (use these names verbatim; appearance / voice details
provided so prompts render likeness consistently):
{character_context or "(none)"}

SETTINGS (each location named in the chapter's planning, with
worldbuilding atmosphere / features / climate so prompts render
the place the writer described — not a generic stand-in):
{settings_context or "(none — invent settings only when chapter prose dictates)"}

RAG CONTEXT (graph-aware project lookup):
{rag_context or "(none)"}

CHAPTER PROSE (first 2500 words):
{" ".join(chapter_text.split()[:2500])}

Output schema (JSON):
{{
  "scenes": [
    {{
      "name": "...",
      "description": "...",
      "prompt": "...",
      "character_refs": ["...", "..."]
    }}
  ]
}}
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=2200, temperature=0.7)
    except Exception as e:
        print(f"[video_studio] LLM scene gen failed: {e}")
        return []
    parsed = _safe_parse_json_object(raw)
    if not parsed:
        return []
    scenes = parsed.get("scenes")
    if not isinstance(scenes, list):
        return []
    cleaned: List[dict] = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        desc = (s.get("description") or "").strip()
        prompt = (s.get("prompt") or "").strip()
        refs = s.get("character_refs") or []
        if isinstance(refs, list):
            refs = [str(r).strip() for r in refs if str(r).strip()]
        else:
            refs = []
        if not (name and prompt):
            continue
        cleaned.append({
            "name": name,
            "description": desc,
            "prompt": prompt,
            "character_refs": refs,
        })
    return cleaned


def _heuristic_scenes_from_text(
    chapter_text: str,
    chapter_title: str,
    scene_count: int,
    chapter_id: str,
    chapter_number: int,
    default_duration: float,
) -> List[Scene]:
    """Build a list of scenes when no LLM is available.

    Splits the chapter into paragraph chunks (sized to roughly equal
    word counts) and produces one scene per chunk with a tiny
    description and a prompt seeded from the chunk's opening line.
    """
    paragraphs = [
        p.strip() for p in chapter_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    n = min(scene_count, len(paragraphs))
    # Even-ish distribution of paragraphs across scenes.
    bucket = max(1, len(paragraphs) // n)
    scenes: List[Scene] = []
    for i in range(n):
        start = i * bucket
        end = start + bucket if i < n - 1 else len(paragraphs)
        chunk = "\n\n".join(paragraphs[start:end])
        opener = re.split(r"[.!?]", chunk, maxsplit=1)[0].strip()
        if len(opener) > 60:
            opener = opener[:60].rstrip() + "…"
        scenes.append(Scene(
            name=f"{chapter_title} — Beat {i + 1}",
            description=opener or f"Beat {i + 1} of {chapter_title}.",
            prompt=opener or f"Cinematic frame of {chapter_title}.",
            chapter_id=chapter_id,
            chapter_number=chapter_number,
        ))
    return scenes


def _finalize_scenes(
    raw_scenes: List[dict],
    chapter_id: str,
    chapter_number: int,
    default_duration: float,
) -> List[Scene]:
    out: List[Scene] = []
    for s in raw_scenes:
        out.append(Scene(
            name=s["name"],
            description=s.get("description", ""),
            prompt=s["prompt"],
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            character_refs=s.get("character_refs", []),
        ))
    return out


def _gather_rag_context(
    query_text: str, rag_system: Optional[Any],
) -> str:
    """Pull a graph-aware context block via the EnhancedRAGSystem.

    Uses ``get_context_for_ai(expand_graph=True, expand_neighbors=True)``
    so character + worldbuilding neighbors of the retrieved entities
    show up. Returns "" on any failure — director degrades to
    no-RAG mode rather than erroring out.
    """
    if rag_system is None or not query_text:
        return ""
    try:
        return rag_system.get_context_for_ai(
            query=query_text[:600],
            max_tokens=1500,
            expand_graph=True,
            expand_neighbors=True,
            max_neighbors_per_seed=2,
        ) or ""
    except Exception:
        return ""


def _summarize_plot_context(
    chapter: Any, project: Any,
) -> str:
    """Short plot-context block: chapter planning intent + the main
    plot + the chapter's own planning beats."""
    parts: List[str] = []
    if project is not None:
        sp = getattr(project, "story_planning", None)
        if sp is not None:
            main_plot = getattr(sp, "main_plot", "") or ""
            if main_plot:
                parts.append(f"Main plot: {main_plot[:400]}")
            themes = getattr(sp, "themes", []) or []
            if themes:
                parts.append(f"Themes: {', '.join(themes[:8])}")
    if chapter is not None:
        planning = getattr(chapter, "planning", None)
        if planning is not None:
            desc = getattr(planning, "description", "") or ""
            if desc:
                parts.append(f"Chapter intent: {desc[:400]}")
            pov = getattr(planning, "pov_character", "") or ""
            if pov:
                parts.append(f"POV: {pov}")
            tone = getattr(planning, "tone", "") or ""
            if tone:
                parts.append(f"Tone: {tone}")
    return "\n".join(parts)


def _summarize_characters(
    project: Any, focus_names: Optional[List[str]] = None,
) -> str:
    """Per-character block with name + physical + personality +
    speaking style + clothing/standout details.

    The previous summarizer truncated everything to 160 chars and
    dropped voice cues, which left video prompts with characters
    that "look right" but acted out-of-character on screen. We now
    surface a multi-line block per character (when fields are set)
    so a text-to-video model has enough to render likeness AND
    behavior consistently.

    ``focus_names`` is an optional case-insensitive list of names.
    When provided, characters whose name matches the list are
    rendered with full detail; others get a single name-only line.
    Lets the director give scene-prompt-quality detail to the
    characters that actually appear in the chapter without busting
    the context budget on a 30-character roster.
    """
    if project is None:
        return ""
    chars = getattr(project, "characters", []) or []
    if not chars:
        return ""
    focus_set: set = set()
    if focus_names:
        focus_set = {(n or "").strip().lower() for n in focus_names if n}
    lines: List[str] = []
    for c in chars[:30]:
        name = (getattr(c, "name", "") or "").strip()
        if not name:
            continue
        kind = (getattr(c, "character_type", "") or "").strip()
        is_focus = (not focus_set
                    or name.lower() in focus_set)
        if not is_focus:
            # Name-only entry so the model knows the character exists
            # without spending tokens on full detail.
            lines.append(f"- {name}"
                         + (f" ({kind})" if kind else ""))
            continue
        physical = (
            getattr(c, "physical_description", "") or "").strip()
        personality = (getattr(c, "personality", "") or "").strip()
        speaking = (getattr(c, "speaking_style", "") or "").strip()
        motivations = (getattr(c, "motivations", "") or "").strip()
        fears = (getattr(c, "fears", "") or "").strip()
        emotional = (
            getattr(c, "emotional_baseline", "") or "").strip()
        block: List[str] = [
            f"- **{name}**" + (f" ({kind})" if kind else "")]
        if physical:
            block.append(f"  appearance: {physical[:280]}")
        if personality:
            block.append(f"  personality: {personality[:200]}")
        if emotional:
            block.append(f"  emotional baseline: {emotional[:160]}")
        if speaking:
            block.append(f"  voice / speech: {speaking[:160]}")
        if motivations:
            block.append(f"  motivations: {motivations[:160]}")
        if fears:
            block.append(f"  fears: {fears[:120]}")
        lines.append("\n".join(block))
    return "\n".join(lines)


def _summarize_settings(
    project: Any, chapter: Any,
) -> str:
    """Build a richly-detailed block for the places this chapter uses.

    Pulls from ``project.worldbuilding.places`` for any location
    named in:
      * ``chapter.planning.locations`` (the writer's planning list)
      * ``chapter.planning.scene_list`` (when the scene names
        include a Place name — handled implicitly via the location
        list, this isn't currently mined further)

    For each matched Place we surface description, atmosphere, key
    features, climate, cultural significance, and any dangers — the
    fields a text-to-video prompt needs to render a setting that
    matches what the writer described instead of inventing a
    generic locale. Characters / worldbuilding context still flow
    separately; this fills the "setting" half of the prompt.

    Returns "" when no places match — the prompt then falls back to
    the chapter prose for setting cues.
    """
    if project is None or chapter is None:
        return ""
    planning = getattr(chapter, "planning", None)
    if planning is None:
        return ""
    location_names = [
        (n or "").strip()
        for n in (
            getattr(planning, "locations", []) or [])
        if (n or "").strip()
    ]
    if not location_names:
        return ""
    wb = getattr(project, "worldbuilding", None)
    if wb is None:
        return ""
    places = getattr(wb, "places", []) or []
    if not places:
        return ""
    # Build a name → Place map (case-insensitive) so the lookup
    # tolerates whitespace and capitalization drift between the
    # planning panel and the worldbuilding entry.
    by_name: dict = {}
    for p in places:
        pname = (getattr(p, "name", "") or "").strip()
        if pname:
            by_name[pname.lower()] = p
    blocks: List[str] = []
    for raw_name in location_names:
        place = by_name.get(raw_name.lower())
        if place is None:
            # Fall back to a single-line stub so the model at least
            # knows the location name was named by the writer even
            # if we don't have a worldbuilding entry for it.
            blocks.append(f"- {raw_name} (no worldbuilding entry)")
            continue
        bits: List[str] = []
        bits.append(f"- **{getattr(place, 'name', raw_name)}**")
        ptype = getattr(place, "place_type", "")
        if ptype:
            try:
                ptype_str = (ptype.value if hasattr(ptype, "value")
                             else str(ptype)).strip().replace(
                                 "_", " ")
            except Exception:
                ptype_str = str(ptype)
            if ptype_str:
                bits.append(f"  type: {ptype_str}")
        desc = (getattr(place, "description", "") or "").strip()
        if desc:
            bits.append(f"  description: {desc[:400]}")
        atmosphere = (getattr(place, "atmosphere", "") or "").strip()
        if atmosphere:
            bits.append(f"  atmosphere: {atmosphere[:280]}")
        climate = (getattr(place, "climate", "") or "").strip()
        if climate:
            bits.append(f"  climate: {climate[:160]}")
        features = list(getattr(place, "key_features", []) or [])
        if features:
            bits.append(
                "  key features: "
                + ", ".join(str(f) for f in features[:8]))
        cultural = (
            getattr(place, "cultural_significance", "") or "").strip()
        if cultural:
            bits.append(
                f"  cultural significance: {cultural[:200]}")
        dangers = list(getattr(place, "dangers", []) or [])
        if dangers:
            bits.append(
                "  dangers: "
                + ", ".join(str(d) for d in dangers[:6]))
        size = (getattr(place, "size", "") or "")
        if size:
            bits.append(f"  size: {size}")
        controlling = (
            getattr(place, "controlling_faction", "") or "")
        if controlling:
            bits.append(f"  controlling faction: {controlling}")
        story_rel = (
            getattr(place, "story_relevance", "") or "").strip()
        if story_rel:
            bits.append(f"  story relevance: {story_rel[:200]}")
        blocks.append("\n".join(bits))
    return "\n".join(blocks)


# ---------------------------------------------------------------------
# JSON parsing helper — LLMs love to wrap output in code fences /
# add commentary before the actual JSON.
# ---------------------------------------------------------------------
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _safe_parse_json_object(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json ``` fences if the model wrapped its output.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    # Last-ditch: grab the first balanced-ish object via regex.
    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None
