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
) -> List[Scene]:
    """Build a list of scenes covering the chapter's beats.

    Each scene gets:
      * ``name`` — short, evocative title
      * ``description`` — 1-3 sentence beat
      * ``prompt`` — terse, image/video-prompt style
      * ``chapter_id`` / ``chapter_number`` — anchored back to source
      * ``character_refs`` — names of characters present in this beat

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
    char_context = _summarize_characters(project)

    if llm is not None:
        scenes = _llm_generate_scenes(
            llm=llm,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            scene_count=scene_count,
            rag_context=rag_context,
            plot_context=plot_context,
            character_context=char_context,
        )
        if scenes:
            return _finalize_scenes(
                scenes, chapter_id, chapter_number, default_duration)

    # No-LLM / failure path — chunk the chapter into beats by
    # paragraph clusters and synthesize a minimal description.
    return _heuristic_scenes_from_text(
        chapter_text, chapter_title, scene_count,
        chapter_id, chapter_number, default_duration)


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
        "back to character reference data. Output strictly JSON "
        "matching the schema. Do not include commentary.")
    user_prompt = f"""
Chapter title: {chapter_title}

Produce {scene_count} scenes that walk through this chapter as a
storyboard. Each scene needs:
  * name: 3-6 words, evocative title
  * description: 1-2 sentences of narrative beat
  * prompt: 1-2 sentences of terse visual prompt for a
            text-to-video model — concrete imagery, lighting,
            camera, characters by name, no abstract themes
  * character_refs: list of character names present in this beat
                    (use names exactly as they appear in CHARACTERS
                    below so they can be reference-matched)

PLOT CONTEXT:
{plot_context or "(none)"}

CHARACTERS (use these names verbatim):
{character_context or "(none)"}

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


def _summarize_characters(project: Any) -> str:
    """One line per character with their name + a short trait."""
    if project is None:
        return ""
    chars = getattr(project, "characters", []) or []
    if not chars:
        return ""
    lines: List[str] = []
    for c in chars[:25]:
        name = getattr(c, "name", "") or ""
        if not name:
            continue
        kind = getattr(c, "character_type", "") or ""
        physical = getattr(c, "physical_description", "") or ""
        snippet = (physical or
                   getattr(c, "personality", "") or "")[:160]
        lines.append(f"- {name}"
                     + (f" ({kind})" if kind else "")
                     + (f": {snippet}" if snippet else ""))
    return "\n".join(lines)


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
