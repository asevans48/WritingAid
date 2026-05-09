"""Long-form writing agent for chapter generation.

This agent powers the new long-form writing tools (``<write_chapter_full>``,
``<append_plot_points>``, ``<continue_from_cursor>``) emitted from the
Chapter Focus chat. It executes a three-phase flow:

1. **Plan** — model generates a structured ``ChapterWritingPlan`` from the
   chapter's planning data, prose profile, and the user's instructions.
   The plan enumerates plot points in order, identifies focal characters
   and subplots per beat, sets POV and voice, and surfaces clarifying
   questions for the user.

2. **Clarify** — questions surface as a chat message; the user answers.
   The agent merges the answers into the plan and proceeds.

3. **Execute** — the agent writes plot-point-by-plot-point. Each call
   feeds a small local model: the running synopsis (what's been written
   so far, condensed), the current plot point + adjacent ones, a focused
   slice of relevant context (characters, subplots, worldbuilding) via
   RAG, and the chapter's voice / POV constraints. After each point,
   the synopsis is updated so the next call still has continuity without
   the full prior text.

The agent is genre-aware via the project's ``prose_profile`` (when set)
and the chapter's planning fields (``tone``, ``voice``, ``style``,
``pacing``, ``pov_character``).

The cap on per-call context is what makes this work for small local
models — instead of sending the whole chapter back, we send a compact
summary plus the focused slice the next plot point needs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import Chapter, WriterProject


class WritingMode(Enum):
    """How long-form writing should land in the chapter."""
    FULL_CHAPTER = "full_chapter"        # rewrite/write full chapter
    APPEND_POINTS = "append_plot_points"  # append N plot points at end
    FROM_CURSOR = "from_cursor"          # write forward from cursor pos


@dataclass
class WritingPlotPoint:
    """One unit of writing — typically one StoryEvent or one beat from
    the chapter outline. The agent generates one of these at a time."""
    title: str
    description: str = ""
    stage: str = "rising"
    pov_character: str = ""
    focal_characters: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    subplots: List[str] = field(default_factory=list)
    tone_note: str = ""
    target_words: int = 350


@dataclass
class ChapterWritingPlan:
    """Full plan a long-form writing run executes against.

    Built once (during the plan phase), then carried through every
    per-point execute call so each call sees the same chapter-level
    intent. The ``running_synopsis`` field is updated after each beat
    so the next call has continuity without needing the full prior
    prose in context.
    """
    chapter_title: str
    chapter_synopsis: str = ""
    pov: str = "third_person_limited"
    pov_character: str = ""
    voice_notes: str = ""
    style_notes: str = ""
    tone_notes: str = ""
    pacing_notes: str = ""
    genre: str = ""
    plot_points: List[WritingPlotPoint] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    answers: Dict[str, str] = field(default_factory=dict)
    running_synopsis: str = ""  # rolling summary of what's been written
    user_instructions: str = ""  # the original natural-language ask


# ── Helpers ──────────────────────────────────────────────────────────


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _last_words(text: str, n_words: int) -> str:
    """Return the last ~n_words words of text. Used to give the model
    the most-recent prose for continuity without sending the whole
    chapter back."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= n_words:
        return text.strip()
    return " ".join(words[-n_words:]).strip()


def _coerce_str_list(value: Any, max_items: int = 8) -> List[str]:
    """Best-effort coercion of LLM-returned 'list' fields.

    The model sometimes returns lists, sometimes a comma-joined string,
    sometimes a list of dicts. We accept all and hand back a clean
    list of strings, capped at ``max_items``.
    """
    if not value:
        return []
    if isinstance(value, str):
        items = [s.strip() for s in re.split(r"[,;\n]", value) if s.strip()]
    elif isinstance(value, list):
        items = []
        for v in value:
            if isinstance(v, str):
                items.append(v.strip())
            elif isinstance(v, dict):
                # accept {"name": "..."} or {"text": "..."}
                for key in ("name", "text", "title"):
                    if key in v and isinstance(v[key], str):
                        items.append(v[key].strip())
                        break
    else:
        items = [str(value).strip()]
    return [s for s in items if s][:max_items]


# ── Agent ────────────────────────────────────────────────────────────


PLAN_SYSTEM_PROMPT = """You are a senior fiction editor planning a chapter rewrite for a long-form novel.

Your job: produce a structured plan the writing agent will execute beat-by-beat. The plan must:
- Enumerate plot points in order. Each point = one scene-beat the writer will draft as a unit.
- Anchor every point to specifics from this project — POV character, focal characters, locations, subplots that touch the beat. Do NOT invent characters or worldbuilding that aren't in the project.
- Honour the chapter's voice / tone / style / pacing notes when present.
- Cover ALL the chapter's planned StoryEvents unless the user's instructions explicitly narrow the scope.
- Surface 2-5 sharp clarifying questions BEFORE the writing starts — focus on choices that meaningfully change the prose: POV identity if ambiguous, which subplot threads to advance vs. defer, tone shifts inside the chapter, what to leave on the page vs. imply.

Use the PROJECT LOOKUP TOOLS (documented separately) when you need specifics — character voice notes, subplot status, ritual / architecture details for a planned location, a related plot event from elsewhere in the manuscript. Fetch BEFORE you produce the plan so the plot-point briefs are concrete instead of generic.

Output as a single JSON object inside <chapter_writing_plan>...</chapter_writing_plan>. Do not write prose."""


EXECUTE_SYSTEM_PROMPT = """You are a long-form fiction writer drafting one scene-beat of a chapter.

Your job: write the prose for THIS beat only, in the voice and POV the plan specifies, anchored in the world the project describes. The beat sits inside a larger chapter — the running synopsis tells you what's already happened in earlier beats; the next-beat hint tells you where the chapter is going. Write to land THIS beat, not the whole chapter.

CONSTRAINTS:
- POV is fixed by the plan. If "third person limited" follows ONE character, never slip into another character's interiority.
- Voice / tone / style / pacing notes are non-negotiable. Match them at sentence level.
- Focal characters in this beat speak / act in voice. Use the personality/voice notes provided.
- When worldbuilding entries are supplied, draw concrete sensory detail from them — but only what the beat earns. Don't info-dump.
- "Show don't tell" defaults: emotion through body / action / dialogue subtext, not labels.
- End the beat at a natural seam (scene break, emotional pivot, or unresolved question) so the next beat has somewhere to go.

Use the PROJECT LOOKUP TOOLS (documented separately) when the beat needs something specific you don't have — a focal character's speaking style, the actual ritual being performed, the architecture of the location, a subplot's current state. Fetch what you need BEFORE writing; the engine feeds results back so your prose can name real elements instead of generic stand-ins.

OUTPUT: prose only. No labels, no headers, no XML, no commentary. Just the scene-beat prose. Length should be roughly the target word budget the plan specifies (a buffer of ±25% is fine)."""


SYNOPSIS_UPDATE_PROMPT = """You are condensing a chapter's narrative state for an AI writer's running context.

Given:
- The running synopsis BEFORE this beat (what had happened earlier in the chapter)
- The prose JUST WRITTEN for this beat
- The plot point this beat was meant to land

Produce an UPDATED running synopsis that:
- Keeps every prior story state that still matters going forward
- Adds 1-2 specific sentences capturing what changed in this beat
- Drops setup details no longer relevant
- Stays under 200 words

Output the updated synopsis as plain text. No headers, no commentary."""


class LongFormWriterAgent:
    """Plans and executes long-form chapter writing for small local models."""

    def __init__(
        self,
        primary_llm: 'LLMClient',
        project: Optional['WriterProject'] = None,
        rag_provider: Optional[Callable[[str, list], str]] = None,
    ):
        """Initialise the agent.

        Args:
            primary_llm: LLM client used for planning + execution. Required.
            project: Optional project model for context assembly.
            rag_provider: Callable ``(query, source_types) -> str`` returning
                a formatted RAG block. Optional but strongly recommended —
                without it the per-beat context falls back to flat
                project lists which can blow small-model context windows.
        """
        if primary_llm is None:
            raise ValueError(
                "LongFormWriterAgent requires an LLM client — long-form "
                "writing has no deterministic fallback.")
        self.primary_llm = primary_llm
        self.project = project
        self.rag_provider = rag_provider

    # ── Plan phase ───────────────────────────────────────────────────

    def plan_chapter(
        self,
        chapter: 'Chapter',
        instructions: str,
        mode: WritingMode = WritingMode.FULL_CHAPTER,
        existing_text: str = "",
        target_points: int = 0,
    ) -> ChapterWritingPlan:
        """Run the plan phase: model produces a structured plan + questions.

        Args:
            chapter: The Chapter model object (carries its planning data).
            instructions: User's natural-language ask
                (e.g. "write me chapter 5 focused on the betrayal").
            mode: Which writing operation this plan will drive.
            existing_text: For append / from-cursor modes, the prose
                already on the page (so the plan knows where to pick up).
            target_points: For append / from-cursor modes, how many
                plot points to write. ``0`` = let the model decide based
                on the chapter's planned events still to cover.

        Returns:
            ChapterWritingPlan, possibly with ``questions`` populated for
            the user to answer before execute_plan runs.
        """
        plan_prompt = self._build_plan_prompt(
            chapter, instructions, mode, existing_text, target_points)
        # Pre-flight lookup loop — let the planner fetch character /
        # subplot / worldbuilding specifics before producing the plan
        # so plot-point briefs are concrete instead of generic. Falls
        # through to a plain ``generate_text`` when the model emits no
        # lookup tags.
        from src.ai.project_lookup import (
            run_with_lookups, LOOKUP_TOOLS_PROMPT_BLOCK)
        sys_prompt = (
            f"{PLAN_SYSTEM_PROMPT}\n\n{'=' * 60}\n"
            f"{LOOKUP_TOOLS_PROMPT_BLOCK}")
        response, _ = run_with_lookups(
            llm=self.primary_llm,
            prompt=plan_prompt,
            system_prompt=sys_prompt,
            project=self.project,
            rag_search=self.rag_provider,
            max_tokens=2000,
            temperature=0.4,
            max_lookup_rounds=2,
        )
        plan = self._parse_plan_response(response, chapter, instructions)
        return plan

    def _build_plan_prompt(
        self,
        chapter: 'Chapter',
        instructions: str,
        mode: WritingMode,
        existing_text: str,
        target_points: int,
    ) -> str:
        """Assemble the prompt for the plan phase.

        Includes:
        - Project-level prose profile (if set)
        - Chapter title, planning description / outline
        - Chapter's StoryEvents (treat as the seed plot points)
        - Chapter's pov_character, voice, tone, style, pacing
        - Top-level project plot context (main_plot, themes, subplots)
        - Existing prose tail (for append / from-cursor modes)
        - Mode-specific guidance
        """
        parts = [f"USER INSTRUCTIONS:\n{instructions or '(none)'}"]

        # Mode block
        mode_lines = {
            WritingMode.FULL_CHAPTER: (
                "MODE: Full chapter rewrite. The plan should cover the "
                "complete chapter from opening to close — every planned "
                "StoryEvent belongs unless the user says otherwise. "
                "Build the full Freytag arc inside the chapter."),
            WritingMode.APPEND_POINTS: (
                f"MODE: Append plot points. The plan should cover the next "
                f"{'%d' % target_points if target_points else 'few'} plot "
                "points the chapter still owes — pick up where the existing "
                "prose ends. Match its voice exactly."),
            WritingMode.FROM_CURSOR: (
                f"MODE: Write forward from cursor. The plan should cover "
                f"{'%d' % target_points if target_points else 'a few'} plot "
                "points starting from the position the user's cursor sits, "
                "continuing the chapter mid-flow. Match the voice of the "
                "prose immediately before the cursor."),
        }
        parts.append(mode_lines[mode])

        # Project-level prose profile
        if self.project and self.project.prose_profile:
            pp = self.project.prose_profile
            pp_lines = []
            if pp.genre: pp_lines.append(f"Genre: {pp.genre}")
            if pp.tone: pp_lines.append(f"Tone: {pp.tone}")
            if pp.style: pp_lines.append(f"Style: {pp.style}")
            if pp.voice: pp_lines.append(f"Voice: {pp.voice}")
            if pp.notes: pp_lines.append(f"Notes: {pp.notes}")
            if pp_lines:
                parts.append("PROJECT PROSE PROFILE:\n" + "\n".join(pp_lines))

        # Chapter
        ch_lines = [f"Chapter: {chapter.title}"]
        if hasattr(chapter, "planning") and chapter.planning:
            cp = chapter.planning
            if cp.description:
                ch_lines.append(f"Description: {cp.description}")
            if cp.outline:
                ch_lines.append(f"Outline: {_truncate(cp.outline, 800)}")
            if cp.pov_character:
                ch_lines.append(f"POV character (planned): {cp.pov_character}")
            if cp.tone: ch_lines.append(f"Chapter tone: {cp.tone}")
            if cp.voice: ch_lines.append(f"Chapter voice: {cp.voice}")
            if cp.style: ch_lines.append(f"Chapter style: {cp.style}")
            if cp.pacing: ch_lines.append(f"Chapter pacing: {cp.pacing}")
            if cp.timeline_position:
                ch_lines.append(
                    f"Timeline position: {cp.timeline_position}")
            if cp.characters_featured:
                ch_lines.append(
                    "Featured characters: "
                    + ", ".join(cp.characters_featured[:10]))
            if cp.locations:
                ch_lines.append(
                    "Locations: " + ", ".join(cp.locations[:8]))
            if cp.themes:
                ch_lines.append("Themes: " + ", ".join(cp.themes[:6]))
            if cp.scene_list:
                ch_lines.append(
                    "Scene list: " + " | ".join(
                        s for s in cp.scene_list[:10] if isinstance(s, str)))
            if cp.events:
                ev_lines = []
                for ev in cp.events:
                    title = getattr(ev, "text", "") or "(unnamed beat)"
                    desc = getattr(ev, "description", "") or ""
                    stage = getattr(ev, "stage", "")
                    line = f"  - [{stage}] {title}"
                    if desc:
                        line += f" — {_truncate(desc, 160)}"
                    ev_lines.append(line)
                ch_lines.append(
                    f"Planned StoryEvents (in order):\n"
                    + "\n".join(ev_lines))
            if cp.subplot_notes:
                sp_lines = []
                for sn in cp.subplot_notes:
                    if sn.content.strip():
                        sp_lines.append(
                            f"  - {sn.title or 'Subplot'}: "
                            f"{_truncate(sn.content, 160)}")
                if sp_lines:
                    ch_lines.append("Subplot threads in scope:\n"
                                    + "\n".join(sp_lines))
            notes_text = (cp.notes_as_text
                          if hasattr(cp, "notes_as_text") else "")
            if notes_text:
                ch_lines.append(
                    "Author notes:\n" + _truncate(notes_text, 600))
        parts.append("CHAPTER CONTEXT:\n" + "\n".join(ch_lines))

        # Project-level plot scaffold
        if self.project and self.project.story_planning:
            sp = self.project.story_planning
            sp_parts = []
            if sp.main_plot:
                sp_parts.append(f"Main plot: {_truncate(sp.main_plot, 300)}")
            if sp.themes:
                sp_parts.append("Themes: " + ", ".join(sp.themes[:6]))
            if sp.theme_details:
                td_lines = []
                for t in sp.theme_details[:4]:
                    title = getattr(t, "title", "")
                    statement = getattr(t, "statement", "") or getattr(
                        t, "description", "")
                    if title:
                        td_lines.append(
                            f"  - {title}: {_truncate(statement, 140)}")
                if td_lines:
                    sp_parts.append(
                        "Theme details:\n" + "\n".join(td_lines))
            if sp.subplots:
                sp_lines = []
                for sub in sp.subplots[:5]:
                    sp_lines.append(
                        f"  - {sub.title} ({sub.status}): "
                        f"{_truncate(sub.description, 140)}")
                sp_parts.append("Subplots:\n" + "\n".join(sp_lines))
            if sp.promises:
                pr_lines = []
                for p in sp.promises[:5]:
                    pr_lines.append(
                        f"  - {p.title}: {_truncate(p.description, 120)}")
                sp_parts.append("Story promises:\n" + "\n".join(pr_lines))
            if sp.tensions:
                t_lines = []
                for t in sp.tensions[:5]:
                    title = getattr(t, "title", "")
                    desc = getattr(t, "description", "")
                    state = getattr(t, "current_state", "")
                    t_lines.append(
                        f"  - {title} ({state}): {_truncate(desc, 120)}")
                sp_parts.append("Sustained tensions:\n" + "\n".join(t_lines))
            if sp_parts:
                parts.append("PROJECT PLOT SCAFFOLD:\n"
                             + "\n\n".join(sp_parts))

        # Existing prose tail (for non-full modes)
        if (mode != WritingMode.FULL_CHAPTER and existing_text
                and existing_text.strip()):
            parts.append(
                "EXISTING PROSE (last 400 words; match this voice):\n"
                + _last_words(existing_text, 400))

        # Output schema instruction
        parts.append(
            'OUTPUT FORMAT: a single JSON object inside '
            '<chapter_writing_plan>...</chapter_writing_plan> with this shape:\n'
            '{\n'
            '  "chapter_synopsis": "1-2 sentence statement of what this chapter\'s about",\n'
            '  "pov": "first_person | third_person_limited | third_person_omniscient | second_person",\n'
            '  "pov_character": "Name of POV character (must exist in project)",\n'
            '  "voice_notes": "specific prose voice instructions",\n'
            '  "style_notes": "sentence-level style instructions",\n'
            '  "tone_notes": "emotional register",\n'
            '  "pacing_notes": "rhythm guidance",\n'
            '  "plot_points": [\n'
            '    {\n'
            '      "title": "Short label for the beat",\n'
            '      "description": "What happens in this beat (2-3 sentences)",\n'
            '      "stage": "exposition | rising | climax | falling | resolution",\n'
            '      "pov_character": "Name (usually same as plan POV)",\n'
            '      "focal_characters": ["Names in this beat"],\n'
            '      "locations": ["Place names"],\n'
            '      "subplots": ["subplot titles touching this beat"],\n'
            '      "tone_note": "anything specific to this beat\'s mood",\n'
            '      "target_words": 350\n'
            '    }\n'
            '  ],\n'
            '  "questions": [\n'
            '    "Specific clarifying question to ask the user before writing"\n'
            '  ]\n'
            '}\n\n'
            'Return ONLY the wrapped JSON. No prose, no commentary.')

        return "\n\n".join(parts)

    def _parse_plan_response(
        self,
        response: str,
        chapter: 'Chapter',
        instructions: str,
    ) -> ChapterWritingPlan:
        """Extract the JSON plan; fall back to a minimal plan if parsing fails."""
        plan = ChapterWritingPlan(
            chapter_title=chapter.title or "Untitled Chapter",
            user_instructions=instructions,
        )
        # Find the wrapped JSON block; tolerant of missing wrapper too.
        m = re.search(
            r'<chapter_writing_plan>\s*(\{.*?\})\s*</chapter_writing_plan>',
            response, re.DOTALL)
        json_text = m.group(1) if m else response
        # Last-resort: grab the largest {...} block in the response
        if not m:
            brace_match = re.search(r'\{.*\}', json_text, re.DOTALL)
            if brace_match:
                json_text = brace_match.group(0)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            # Fall back to a minimal plan derived from chapter planning
            plan.chapter_synopsis = (
                getattr(chapter, "planning", None) and
                (chapter.planning.description
                 or chapter.planning.outline) or "")
            return self._fill_plan_from_chapter(plan, chapter)
        # Populate plan from JSON
        plan.chapter_synopsis = data.get("chapter_synopsis", "") or plan.chapter_synopsis
        plan.pov = data.get("pov", "third_person_limited")
        plan.pov_character = data.get("pov_character", "")
        plan.voice_notes = data.get("voice_notes", "")
        plan.style_notes = data.get("style_notes", "")
        plan.tone_notes = data.get("tone_notes", "")
        plan.pacing_notes = data.get("pacing_notes", "")
        plan.questions = _coerce_str_list(data.get("questions"), max_items=6)
        plan.plot_points = []
        for pp_data in data.get("plot_points", []) or []:
            plan.plot_points.append(WritingPlotPoint(
                title=pp_data.get("title", "Untitled beat") or "Untitled beat",
                description=pp_data.get("description", ""),
                stage=pp_data.get("stage", "rising"),
                pov_character=pp_data.get(
                    "pov_character", plan.pov_character),
                focal_characters=_coerce_str_list(
                    pp_data.get("focal_characters")),
                locations=_coerce_str_list(pp_data.get("locations"), 5),
                subplots=_coerce_str_list(pp_data.get("subplots"), 5),
                tone_note=pp_data.get("tone_note", ""),
                target_words=int(pp_data.get("target_words", 350) or 350),
            ))
        # Genre — pull from project prose profile if not on the plan
        if (self.project and self.project.prose_profile
                and self.project.prose_profile.genre):
            plan.genre = self.project.prose_profile.genre
        # If the model produced an empty plot_points list, derive from chapter
        if not plan.plot_points:
            plan = self._fill_plan_from_chapter(plan, chapter)
        return plan

    def _fill_plan_from_chapter(
        self,
        plan: ChapterWritingPlan,
        chapter: 'Chapter',
    ) -> ChapterWritingPlan:
        """Last-resort: build plot_points from chapter.planning.events."""
        if not (hasattr(chapter, "planning") and chapter.planning):
            return plan
        cp = chapter.planning
        if not plan.pov_character and cp.pov_character:
            plan.pov_character = cp.pov_character
        if not plan.voice_notes and cp.voice:
            plan.voice_notes = cp.voice
        if not plan.style_notes and cp.style:
            plan.style_notes = cp.style
        if not plan.tone_notes and cp.tone:
            plan.tone_notes = cp.tone
        if not plan.pacing_notes and cp.pacing:
            plan.pacing_notes = cp.pacing
        if cp.events:
            for ev in cp.events:
                plan.plot_points.append(WritingPlotPoint(
                    title=getattr(ev, "text", "Beat") or "Beat",
                    description=getattr(ev, "description", "") or "",
                    stage=getattr(ev, "stage", "rising") or "rising",
                    pov_character=plan.pov_character,
                    focal_characters=list(cp.characters_featured[:6]),
                    locations=list(cp.locations[:3]),
                    subplots=[sn.title for sn in cp.subplot_notes
                              if sn.title][:3],
                    tone_note="",
                    target_words=350,
                ))
        elif cp.scene_list:
            for s in cp.scene_list:
                if not isinstance(s, str) or not s.strip():
                    continue
                plan.plot_points.append(WritingPlotPoint(
                    title=s.strip()[:80],
                    description=s.strip(),
                    pov_character=plan.pov_character,
                    focal_characters=list(cp.characters_featured[:6]),
                ))
        return plan

    # ── Execute phase ────────────────────────────────────────────────

    def execute_plan(
        self,
        plan: ChapterWritingPlan,
        progress_cb: Optional[Callable[[str], None]] = None,
        prior_text: str = "",
        on_point_written: Optional[Callable[..., None]] = None,
    ) -> str:
        """Run all plot points in order and return the assembled prose.

        Args:
            plan: The ChapterWritingPlan to execute (with answers merged
                if any clarifying questions were posed).
            progress_cb: Per-step status callback ``(message) -> None``.
            prior_text: Prose already on the page that *precedes* what
                we're about to write (for append / from-cursor modes).
                The agent uses the tail of this to anchor voice on the
                first beat.
            on_point_written: Callback fired *after* each beat finishes,
                with ``(point_index, plot_point, prose)``. The UI uses
                this to insert each beat into the editor as it lands so
                the user sees progress instead of waiting for the whole
                chapter.

        Returns:
            The full assembled prose, with paragraph breaks between
            beats. Updates ``plan.running_synopsis`` in place after each
            beat.
        """
        if not plan.plot_points:
            return ""
        all_prose: List[str] = []
        running_text = prior_text or ""
        for i, point in enumerate(plan.plot_points):
            if progress_cb:
                progress_cb(
                    f"Writing beat {i+1}/{len(plan.plot_points)}: "
                    f"{point.title}")
            beat_prose, beat_prompt = self.execute_plot_point(
                plan=plan,
                point_index=i,
                prior_text=running_text,
                return_prompt=True,
            )
            beat_prose = beat_prose.strip()
            if beat_prose:
                all_prose.append(beat_prose)
                # Update running_text + running_synopsis for the next beat.
                running_text = (running_text + "\n\n" + beat_prose).strip()
                self._update_running_synopsis(
                    plan, point, beat_prose, progress_cb)
            if on_point_written is not None:
                try:
                    # Pass the actual prompt so callers (UI rating dialog,
                    # training-data persisters) can save the real
                    # instruction → completion pair instead of a
                    # synthesised stub.
                    on_point_written(i, point, beat_prose, beat_prompt)
                except TypeError:
                    # Backwards-compat: older 3-arg callbacks still work.
                    try:
                        on_point_written(i, point, beat_prose)
                    except Exception as e:  # pragma: no cover
                        print(f"[long_form] on_point_written failed: {e}")
                except Exception as e:  # pragma: no cover — UI side
                    print(f"[long_form] on_point_written callback failed: {e}")
        return "\n\n".join(all_prose)

    def execute_plot_point(
        self,
        plan: ChapterWritingPlan,
        point_index: int,
        prior_text: str = "",
        return_prompt: bool = False,
    ):
        """Generate prose for ONE plot point.

        Builds a tightly-scoped prompt:
        - Plan-level voice/POV/style (small, fixed)
        - The current beat + adjacent beat hints
        - Running synopsis (what's already happened — bounded summary)
        - Last ~300 words of prior prose (for sentence-level continuity)
        - RAG-fetched character / subplot / worldbuilding chunks
          relevant to THIS beat

        Returns the prose text. When ``return_prompt`` is True, returns
        ``(prose, prompt)`` instead — used by the orchestration loop
        so callers can persist (prompt, prose) as training data.
        """
        if point_index < 0 or point_index >= len(plan.plot_points):
            return ("", "") if return_prompt else ""
        point = plan.plot_points[point_index]
        prompt = self._build_execute_prompt(plan, point, point_index, prior_text)
        # Per-beat lookup loop — the writer can pull in just-in-time
        # character voice / subplot status / worldbuilding detail it
        # needs for THIS beat. The LOOKUP_TOOLS_PROMPT_BLOCK is
        # appended to the execute system prompt so the model knows
        # the tools exist + the protocol.
        from src.ai.project_lookup import (
            run_with_lookups, LOOKUP_TOOLS_PROMPT_BLOCK)
        sys_prompt = (
            f"{EXECUTE_SYSTEM_PROMPT}\n\n{'=' * 60}\n"
            f"{LOOKUP_TOOLS_PROMPT_BLOCK}")
        response, _ = run_with_lookups(
            llm=self.primary_llm,
            prompt=prompt,
            system_prompt=sys_prompt,
            project=self.project,
            rag_search=self.rag_provider,
            max_tokens=int(point.target_words * 2.2),  # ≈ 2.2× words
            temperature=0.7,
            max_lookup_rounds=2,
        )
        prose = self._strip_meta(response)
        if return_prompt:
            return prose, prompt
        return prose

    def _build_execute_prompt(
        self,
        plan: ChapterWritingPlan,
        point: WritingPlotPoint,
        point_index: int,
        prior_text: str,
    ) -> str:
        """Assemble the per-beat execution prompt."""
        parts = []

        # Chapter-level constraints (small, repeated each call so small
        # local models don't drift)
        ch_block = [
            f"Chapter: {plan.chapter_title}",
            f"Chapter intent: {plan.chapter_synopsis or '(none)'}",
            f"POV: {plan.pov}",
            f"POV character: {plan.pov_character or '(unspecified)'}",
        ]
        if plan.genre:
            ch_block.append(f"Genre: {plan.genre}")
        if plan.voice_notes:
            ch_block.append(f"Voice: {plan.voice_notes}")
        if plan.style_notes:
            ch_block.append(f"Style: {plan.style_notes}")
        if plan.tone_notes:
            ch_block.append(f"Tone: {plan.tone_notes}")
        if plan.pacing_notes:
            ch_block.append(f"Pacing: {plan.pacing_notes}")
        if plan.answers:
            ch_block.append(
                "User-supplied answers to clarifying questions:")
            for q, a in plan.answers.items():
                ch_block.append(f"  Q: {q}\n  A: {a}")
        parts.append("CHAPTER CONSTRAINTS:\n" + "\n".join(ch_block))

        # Running synopsis (grows as the chapter progresses)
        if plan.running_synopsis:
            parts.append(
                "RUNNING SYNOPSIS (what's happened in this chapter so far):\n"
                + _truncate(plan.running_synopsis, 1200))
        elif point_index > 0:
            parts.append(
                "RUNNING SYNOPSIS: (this is the second+ beat but the "
                "synopsis is empty — assume the immediately-prior beat "
                "set things up.)")

        # Adjacent beats — give the model context for where it's going
        adjacent = []
        if point_index > 0:
            prev = plan.plot_points[point_index - 1]
            adjacent.append(
                f"Previous beat: {prev.title} — "
                f"{_truncate(prev.description, 160)}")
        if point_index + 1 < len(plan.plot_points):
            nxt = plan.plot_points[point_index + 1]
            adjacent.append(
                f"Next beat: {nxt.title} — "
                f"{_truncate(nxt.description, 160)}")
        if adjacent:
            parts.append("ADJACENT BEATS:\n" + "\n".join(adjacent))

        # Current beat — the focus
        beat_block = [
            f"Title: {point.title}",
            f"Stage: {point.stage}",
            f"Description: {point.description or '(write the beat)'}",
            f"Target length: ~{point.target_words} words",
        ]
        if point.pov_character and point.pov_character != plan.pov_character:
            beat_block.append(
                f"POV character (this beat): {point.pov_character}")
        if point.focal_characters:
            beat_block.append(
                f"Focal characters: {', '.join(point.focal_characters)}")
        if point.locations:
            beat_block.append(f"Locations: {', '.join(point.locations)}")
        if point.subplots:
            beat_block.append(
                f"Subplot threads to advance: {', '.join(point.subplots)}")
        if point.tone_note:
            beat_block.append(f"Tone for this beat: {point.tone_note}")
        parts.append("THIS BEAT:\n" + "\n".join(beat_block))

        # Focused context via RAG
        ctx_block = self._build_focused_context(plan, point)
        if ctx_block:
            parts.append("RELEVANT BACKGROUND:\n" + ctx_block)

        # Last ~300 words of prior prose for voice/sentence-level continuity
        if prior_text and prior_text.strip():
            parts.append(
                "IMMEDIATELY-PRIOR PROSE (continue this voice; "
                "do not repeat content):\n"
                + _last_words(prior_text, 300))

        parts.append(
            "Now write the prose for THIS beat. Output prose only — "
            "no labels, no commentary, no XML tags.")

        return "\n\n".join(parts)

    def _build_focused_context(
        self,
        plan: ChapterWritingPlan,
        point: WritingPlotPoint,
    ) -> str:
        """Assemble per-beat context from project + RAG.

        Strategy: prefer RAG when wired (focused character / subplot /
        worldbuilding chunks). Fall back to flat project lookup for the
        focal characters when RAG isn't available.
        """
        if self.rag_provider is not None:
            # Build a query that emphasises THIS beat's specifics — what
            # characters are in it, where it happens, what subplot it
            # touches. The retriever returns the most relevant chunks.
            query_parts = [point.title, point.description or ""]
            query_parts.extend(point.focal_characters)
            query_parts.extend(point.locations)
            query_parts.extend(point.subplots)
            query = " ".join(p for p in query_parts if p)[:1200]
            if query.strip():
                try:
                    return self.rag_provider(
                        query,
                        ["character", "subplot", "place", "faction",
                         "culture", "encyclopedia"],
                    ) or ""
                except Exception as e:
                    print(f"[long_form] RAG failed: {e}")
        # Fallback: flat lookup of focal-character profiles
        if not self.project:
            return ""
        lines = []
        focal_set = {c.lower() for c in point.focal_characters}
        focal_set.add((plan.pov_character or "").lower())
        for ch in (self.project.characters or [])[:30]:
            if not ch.name:
                continue
            if ch.name.lower() not in focal_set:
                continue
            block = [f"  - {ch.name} ({getattr(ch, 'character_type', 'character')})"]
            personality = getattr(ch, "personality", "") or ""
            if personality:
                block.append(f"    Personality: {_truncate(personality, 200)}")
            voice = getattr(ch, "voice", "") or ""
            if voice:
                block.append(f"    Voice: {_truncate(voice, 200)}")
            wants = getattr(ch, "wants", "") or getattr(ch, "goals", "") or ""
            if wants:
                block.append(f"    Wants: {_truncate(wants, 200)}")
            lines.extend(block)
        return "\n".join(lines)

    def _update_running_synopsis(
        self,
        plan: ChapterWritingPlan,
        point: WritingPlotPoint,
        beat_prose: str,
        progress_cb: Optional[Callable[[str], None]],
    ) -> None:
        """Compress the just-written beat into the running synopsis.

        Called after each successful beat. We try the LLM first (1 call,
        small) and fall back to a deterministic 1-line summary if the
        call fails — better to have *some* synopsis than none.
        """
        try:
            prompt = (
                f"Running synopsis BEFORE this beat:\n"
                f"{plan.running_synopsis or '(none — this was the first beat)'}\n\n"
                f"Plot point this beat was meant to land:\n"
                f"{point.title} — {_truncate(point.description, 200)}\n\n"
                f"Prose just written for this beat:\n"
                f"{_truncate(beat_prose, 1800)}\n\n"
                "Produce the UPDATED running synopsis. Plain text, "
                "under 200 words. No headers."
            )
            response = self.primary_llm.generate_text(
                prompt,
                SYNOPSIS_UPDATE_PROMPT,
                max_tokens=400,
                temperature=0.3,
            )
            updated = (response or "").strip()
            if updated:
                plan.running_synopsis = updated
                return
        except Exception as e:
            print(f"[long_form] synopsis update failed: {e}")
        # Deterministic fallback
        line = f"{point.title}: {_truncate(point.description or beat_prose, 150)}"
        if plan.running_synopsis:
            plan.running_synopsis = (
                plan.running_synopsis + " " + line).strip()
        else:
            plan.running_synopsis = line

    @staticmethod
    def _strip_meta(response: str) -> str:
        """Strip common LLM meta-decorations from the prose output.

        Models occasionally prefix output with labels like "Prose:" or
        wrap it in code fences. Also strips model-specific channel /
        chat-format tokens (Harmony, ChatML, Llama 3, Mistral [INST],
        thinking blocks) that leak through from local models when
        their chat template doesn't match their training format.
        """
        from src.ai.output_sanitizer import strip_meta_tokens
        text = strip_meta_tokens(response or "")
        # Remove leading code fences (```text / ```)
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        # Drop common labels at the very start
        text = re.sub(
            r"^(?:Prose|Output|Beat|Scene)\s*[:\-]\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()


# ── Public utility: parse the new chat tool tags ─────────────────────


_WRITE_TOOL_RX = {
    "write_chapter_full": re.compile(
        r"<write_chapter_full>\s*(\{.*?\})\s*</write_chapter_full>",
        re.DOTALL),
    "append_plot_points": re.compile(
        r"<append_plot_points>\s*(\{.*?\})\s*</append_plot_points>",
        re.DOTALL),
    "continue_from_cursor": re.compile(
        r"<continue_from_cursor>\s*(\{.*?\})\s*</continue_from_cursor>",
        re.DOTALL),
}


def extract_write_tool_calls(response: str) -> List[Dict[str, Any]]:
    """Parse new long-form writing tool tags from a chat response.

    Returns a list of dicts shaped::

        {"tool": "<tool_name>", "params": {...}, "raw": "<full match>"}

    Parsing is tolerant of malformed JSON: a tool call with bad JSON
    still surfaces (with empty ``params``) so the caller can warn the
    user instead of silently dropping it.
    """
    found: List[Dict[str, Any]] = []
    for tool_name, rx in _WRITE_TOOL_RX.items():
        for m in rx.finditer(response):
            raw_json = m.group(1)
            try:
                params = json.loads(raw_json)
            except json.JSONDecodeError:
                params = {}
            found.append({
                "tool": tool_name,
                "params": params if isinstance(params, dict) else {},
                "raw": m.group(0),
            })
    return found


def strip_write_tool_calls(response: str) -> str:
    """Remove all long-form writing tool tags from a chat response.

    The chat UI uses this so the user-visible message doesn't show the
    raw XML; the tags are processed separately.
    """
    out = response
    for rx in _WRITE_TOOL_RX.values():
        out = rx.sub("", out)
    return out.strip()
