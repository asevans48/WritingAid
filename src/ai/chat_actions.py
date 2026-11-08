"""Conversation-driven project actions for the AI chat.

Lets the chat do more than talk:

  * **Overall critique** — when the writer asks for one, run every
    critique report (pacing, voice, tension, plot, dialog, style, canon,
    grammar, characters, worldbuilding) plus the promise / character
    consistency check, and summarise the result in the conversation.
  * **Redo the chapter outline** — rebuild the current chapter's beat
    outline (from its text when there is prose), replacing the old one.
  * **Edit the story outline** — change the main plot, the Freytag stage
    notes, and existing plot events / subplots (create blocks already
    cover adding new ones).
  * **Edit worldbuilding** — update or rename existing worldbuilding
    entries (and characters) through conversation.

Two triggers: explicit requests are recognised in the writer's message
(``detect_intent``) so they work with any model, and the model can emit
action tags (``ACTIONS_PROMPT_BLOCK``) that ``extract_actions`` parses.
Pure Python — the main window applies the results.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# ── Intent detection ────────────────────────────────────────────────

_CRITIQUE_RX = [
    re.compile(r"\b(?:overall|full|complete|comprehensive|whole|general)\s+"
               r"(?:critique|review|feedback|assessment|evaluation|analysis|check)\b", re.I),
    re.compile(r"\b(?:critique|review|assess|evaluate|grade|analy[sz]e|check)\s+"
               r"(?:this|the|my|our)\s+(?:current\s+)?(?:chapter|manuscript|book|novel|draft|"
               r"story|whole\s+(?:book|thing|manuscript))\b", re.I),
    re.compile(r"\b(?:run|do|give\s+me|can\s+(?:you|i)\s+(?:get|have)|i(?:'d)?\s+(?:like|want))\s+"
               r"(?:a|an|the)\s+(?:\w+\s+)?critique\b", re.I),
    re.compile(r"^\s*critique\b", re.I),
]
_MANUSCRIPT_RX = re.compile(
    r"\b(?:manuscript|whole\s+book|entire\s+book|the\s+book|novel|all\s+(?:the\s+)?chapters|"
    r"every\s+chapter|whole\s+story|entire\s+story)\b", re.I)
_CHAPTER_OUTLINE_RX = [
    re.compile(r"\b(?:re-?do|re-?generate|re-?build|re-?create|re-?make|refresh|re-?write|"
               r"replace|rework|start\s+over\s+on)\s+(?:the\s+|this\s+|my\s+)?(?:current\s+)?"
               r"(?:chapter(?:'s)?\s+)?(?:outline|beats|beat\s+list|plot\s+arc)\b", re.I),
    re.compile(r"\b(?:outline|populate\s+the\s+(?:chapter\s+)?outline)\s+(?:for\s+)?"
               r"(?:this|the\s+current|the)\s+chapter\s+(?:from|using|based\s+on)\b", re.I),
    re.compile(r"\b(?:new|fresh)\s+(?:chapter\s+)?outline\s+(?:for\s+)?(?:this|the)\s+chapter\b", re.I),
]
_CONTINUITY_RX = re.compile(
    r"\bcontinuity\b.{0,60}\b(?:novellas?|series|books|across|between|manuscripts|"
    r"sequels?|volumes?)\b|\b(?:novellas?|books|series)\b.{0,40}\bcontinuity\b", re.I)
_STORY_OUTLINE_RX = re.compile(r"\b(?:story|plot|book|novel)\s+outline\b", re.I)
# "Change the main plot to: …" / "set the climax to …" — applied verbatim.
_SET_STORY_FIELD_RX = re.compile(
    r"^\s*(?:please\s+)?(?:change|set|update|make|replace|rewrite)\s+(?:the\s+|my\s+)?"
    r"(?P<field>main\s+plot|story\s+premise|premise|exposition|rising\s+action|climax|"
    r"falling\s+action|resolution)(?:\s+section)?\s*(?:to|with|so\s+it\s+says|as)\s*[:\-–—]?\s*"
    r"(?P<value>.+?)\s*$", re.I | re.S)
_FIELD_KEYS = {"main plot": "main_plot", "story premise": "main_plot", "premise": "main_plot",
               "exposition": "exposition", "rising action": "rising_action", "climax": "climax",
               "falling action": "falling_action", "resolution": "resolution"}
_FROM_PLAN_RX = re.compile(r"\bfrom\s+(?:the\s+)?(?:plan|planning|description|notes|context)\b", re.I)


def detect_intent(message: str) -> Optional[Dict[str, str]]:
    """Recognise explicit action requests in the writer's message.

    Returns ``{"kind": "critique", "scope": "chapter"|"manuscript"}``,
    ``{"kind": "chapter_outline", "source": "text"|"plan"}``,
    ``{"kind": "story_outline", "data": {field: value}}`` (a dictated
    main-plot / Freytag-stage change, applied verbatim) or None.
    Deliberately conservative: only clear requests trigger an action;
    everything else stays a normal conversation turn.
    """
    text = (message or "").strip()
    if not text:
        return None
    m = _SET_STORY_FIELD_RX.match(text)
    if m and len(m.group("value")) >= 8:
        key = _FIELD_KEYS[re.sub(r"\s+", " ", m.group("field").lower())]
        value = m.group("value").strip().strip('"“”')
        return {"kind": "story_outline", "data": {key: value}}
    if len(text) > 600:
        return None
    if any(rx.search(text) for rx in _CHAPTER_OUTLINE_RX) and not _STORY_OUTLINE_RX.search(text):
        return {"kind": "chapter_outline",
                "source": "plan" if _FROM_PLAN_RX.search(text) else "text"}
    if _CONTINUITY_RX.search(text):
        return {"kind": "critique", "scope": "continuity"}
    if any(rx.search(text) for rx in _CRITIQUE_RX):
        return {"kind": "critique",
                "scope": "manuscript" if _MANUSCRIPT_RX.search(text) else "chapter"}
    return None


# ── Action tags the model may emit ──────────────────────────────────

ACTIONS_PROMPT_BLOCK = """=== PROJECT ACTIONS (edit the story through conversation) ===

Besides the <create_*> blocks, you can change EXISTING project material.
Emit a block at the END of your reply, after explaining the change in
prose. Only emit one when the author has asked for the change (or agreed
to your proposal) — never as a surprise. JSON bodies, exact names/titles
from the project context. When the author dictates the new wording, put
THEIR wording in the block verbatim — suggest improvements in prose
instead of silently rewriting it.

Overall critique (when the author asks for an overall / full critique):
  <run_critique>{"scope": "chapter"}</run_critique>      ("manuscript" for the whole book;
  "continuity" to check continuity across the project's novellas)

Redo the current chapter's beat outline (replaces the old outline):
  <regenerate_chapter_outline>{"source": "text"}</regenerate_chapter_outline>
  ("text" = build it from the chapter prose; "plan" = from the chapter description / plan)

Edit the story outline:
  <update_story_outline>{"main_plot": "...", "exposition": "...", "rising_action": "...",
     "climax": "...", "falling_action": "...", "resolution": "..."}</update_story_outline>
     (include only the fields that change)
  <update_plot_event>{"title": "<existing event title>", "updates": {"title": "...",
     "description": "...", "outcome": "...", "stage": "rising_action", "act": 2,
     "intensity": 70}}</update_plot_event>
  <delete_plot_event>{"title": "<existing event title>"}</delete_plot_event>
  <update_subplot>{"title": "<existing subplot title>", "updates": {"description": "...",
     "status": "..."}}</update_subplot>

Edit worldbuilding (or a character) — overwrites the named fields:
  <update_element>{"element_type": "faction", "name": "<existing name>",
     "set": {"description": "...", "leader": "..."},
     "append": {"description": "One more sentence to add."},
     "rename": "<optional new name>"}</update_element>
  element_type: character, faction, place, culture, technology, myth, flora, fauna,
  historical_event, star_system, economy, army, political_system, magic_system.
  Use "set" to replace a detail, "append" to add to it. Use field names that exist on
  the element in the context. Ask before overwriting something substantial.
"""

ACTION_TAGS = (
    "run_critique", "regenerate_chapter_outline", "update_story_outline",
    "update_plot_event", "delete_plot_event", "update_subplot", "update_element",
)
_TAG_RX = re.compile(
    r"<(?P<tag>" + "|".join(ACTION_TAGS) + r")>\s*(?P<body>.*?)\s*</(?P=tag)>",
    re.S | re.I)
_SELF_CLOSING_RX = re.compile(
    r"<(?P<tag>" + "|".join(ACTION_TAGS) + r")(?P<attrs>(?:\s+\w+=\"[^\"]*\")*)\s*/>", re.I)


def _loads(body: str) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        return {}
    body = re.sub(r"^```(?:json)?|```$", "", body.strip()).strip()
    body = re.sub(r",\s*([}\]])", r"\1", body)
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def extract_actions(response: str) -> Tuple[List[Tuple[str, Dict[str, Any]]], str]:
    """Pull action blocks out of a model reply.

    Returns ``([(tag, data), ...], cleaned_response)``.
    """
    actions: List[Tuple[str, Dict[str, Any]]] = []
    for m in _TAG_RX.finditer(response or ""):
        actions.append((m.group("tag").lower(), _loads(m.group("body"))))
    for m in _SELF_CLOSING_RX.finditer(response or ""):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group("attrs") or ""))
        actions.append((m.group("tag").lower(), attrs))
    cleaned = _SELF_CLOSING_RX.sub("", _TAG_RX.sub("", response or ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return actions, cleaned


# ── Applying story-outline edits ────────────────────────────────────

_STAGES = ("exposition", "rising_action", "climax", "falling_action", "resolution")
_STAGE_ALIASES = {"rising": "rising_action", "falling": "falling_action",
                  "denouement": "resolution", "inciting_incident": "rising_action"}


def _find_by_title(items, title: str, attr: str = "title"):
    if not title:
        return None
    exact = next((i for i in items if (getattr(i, attr, "") or "").strip().lower()
                  == title.strip().lower()), None)
    if exact is not None:
        return exact
    try:
        from src.utils.fuzzy_match import find_similar_element
        # fuzzy helper keys off .name; wrap for title-based models
        class _N:
            def __init__(self, obj):
                self.obj, self.name = obj, getattr(obj, attr, "")
        hit = find_similar_element(title, [_N(i) for i in items], threshold=0.75)
        return hit.obj if hit is not None else None
    except Exception:
        return None


def apply_story_outline_update(story_planning: Any, data: Dict[str, Any]) -> List[str]:
    """Main plot + Freytag stage notes. Returns the fields changed."""
    changed = []
    if isinstance(data.get("main_plot"), str) and data["main_plot"].strip():
        story_planning.main_plot = data["main_plot"].strip()
        changed.append("main plot")
    fp = getattr(story_planning, "freytag_pyramid", None)
    for key, value in data.items():
        stage = _STAGE_ALIASES.get(key, key)
        if fp is not None and stage in _STAGES and isinstance(value, str) and value.strip():
            setattr(fp, stage, value.strip())
            changed.append(stage.replace("_", " "))
    return changed


def update_plot_event(story_planning: Any, data: Dict[str, Any]) -> Optional[str]:
    events = story_planning.freytag_pyramid.events
    ev = _find_by_title(events, data.get("title", ""))
    updates = data.get("updates") or {}
    if ev is None or not updates:
        return None
    changed = []
    for key, value in updates.items():
        if key in ("id",) or value in (None, ""):
            continue
        if key == "stage":
            value = _STAGE_ALIASES.get(str(value).lower(), str(value).lower())
            if value not in _STAGES:
                continue
        if key in ("act", "intensity", "sort_order"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if key == "intensity":
                value = max(0, min(100, value))
        if key == "related_characters" and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        if hasattr(ev, key):
            try:
                setattr(ev, key, value)
                changed.append(key)
            except (TypeError, ValueError):
                pass
    return f"{ev.title} ({', '.join(changed)})" if changed else None


def delete_plot_event(story_planning: Any, data: Dict[str, Any]) -> Optional[str]:
    events = story_planning.freytag_pyramid.events
    ev = _find_by_title(events, data.get("title", ""))
    if ev is None:
        return None
    events.remove(ev)
    return ev.title


def update_subplot(story_planning: Any, data: Dict[str, Any]) -> Optional[str]:
    subplots = story_planning.subplots
    sp = (_find_by_title(subplots, data.get("title", ""), "title")
          or _find_by_title(subplots, data.get("title", ""), "name"))
    updates = data.get("updates") or {}
    if sp is None or not updates:
        return None
    changed = []
    for key, value in updates.items():
        if key == "id" or value in (None, "") or not hasattr(sp, key):
            continue
        current = getattr(sp, key)
        if isinstance(current, list) and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        try:
            setattr(sp, key, value)
            changed.append(key)
        except (TypeError, ValueError):
            pass
    label = getattr(sp, "title", None) or getattr(sp, "name", "subplot")
    return f"{label} ({', '.join(changed)})" if changed else None


# ── Applying worldbuilding / character edits ────────────────────────

def element_lists(project: Any) -> Dict[str, list]:
    wb = project.worldbuilding
    return {
        "character": project.characters,
        "faction": wb.factions, "place": wb.places, "culture": wb.cultures,
        "technology": wb.technologies, "myth": wb.myths, "flora": wb.flora,
        "fauna": wb.fauna, "historical_event": wb.historical_events,
        "star_system": wb.star_systems, "economy": wb.economies, "army": wb.armies,
        "political_system": wb.political_systems, "magic_system": wb.magic_systems,
        "climate_preset": wb.climate_presets,
    }


def update_element(project: Any, data: Dict[str, Any]) -> Optional[str]:
    """Set / append / rename fields on an existing element. Unlike the
    create pipeline's enrich, this overwrites — it's the writer asking
    for a change."""
    etype = (data.get("element_type") or "").strip().lower().replace(" ", "_")
    lists = element_lists(project)
    candidates = lists.get(etype)
    if candidates is None:
        # Unknown type: search every list by name.
        candidates = [e for items in lists.values() for e in items]
    name = (data.get("name") or "").strip()
    el = _find_by_title(candidates, name, "name")
    if el is None:
        return None
    fields = type(el).model_fields if hasattr(type(el), "model_fields") else {}
    changed = []

    def coerce(key, value, current):
        if isinstance(current, list) and isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(current, bool):
            return bool(value)
        if isinstance(current, int) and not isinstance(current, bool):
            return int(value)
        if isinstance(current, float):
            return float(value)
        return value

    for key, value in (data.get("set") or {}).items():
        if key in ("id", "name", "created_at") or key not in fields:
            continue
        try:
            setattr(el, key, coerce(key, value, getattr(el, key, None)))
            changed.append(key)
        except (TypeError, ValueError):
            pass
    for key, value in (data.get("append") or {}).items():
        if key in ("id", "name", "created_at") or key not in fields or value in (None, ""):
            continue
        current = getattr(el, key, None)
        try:
            if isinstance(current, list):
                extra = value if isinstance(value, list) else [v.strip() for v in str(value).split(",")]
                setattr(el, key, current + [v for v in extra if v and v not in current])
            elif isinstance(current, str) or current is None:
                joined = f"{current.rstrip()} {str(value).strip()}" if current else str(value).strip()
                setattr(el, key, joined)
            else:
                continue
            changed.append(f"+{key}")
        except (TypeError, ValueError):
            pass
    new_name = (data.get("rename") or "").strip()
    if new_name and new_name != el.name:
        old = el.name
        el.name = new_name
        changed.append(f"renamed from {old}")
    if hasattr(el, "updated_at"):
        try:
            from datetime import datetime
            el.updated_at = datetime.now()
        except Exception:
            pass
    return f"{el.name} ({', '.join(changed)})" if changed else None


# ── Critique → chat ─────────────────────────────────────────────────

REPORT_LABELS = {
    "pacing": "Pacing", "voice": "Writer's voice", "tension": "Tension & stakes",
    "plot": "Plot & promises", "dialog": "Dialog", "style": "Sentence style",
    "canon": "Canon", "grammar": "Grammar & readability", "character": "Characters",
    "worldbuilding": "Worldbuilding",
}


def promise_check_inputs(project: Any) -> Tuple[List[dict], List[dict], str]:
    """(promises, characters, plot_outline) in PromiseChecker's shape."""
    sp = getattr(project, "story_planning", None)
    promises = [{"promise_type": p.promise_type, "title": p.title,
                 "description": p.description, "related_characters": p.related_characters}
                for p in (getattr(sp, "promises", None) or [])]
    characters = [{"name": c.name, "character_type": c.character_type,
                   "personality": c.personality, "backstory": c.backstory}
                  for c in (getattr(project, "characters", None) or [])]
    return promises, characters, (getattr(sp, "main_plot", "") or "")


def _short(text: str, n: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def format_critique_for_chat(report: Any, promise_results: Optional[list] = None,
                             issues_per_report: int = 2,
                             chapters: Optional[list] = None) -> str:
    """Markdown summary of a CritiqueReport (+ promise checks) for the chat.

    ``chapters`` — ``[(chapter_id, title, text)]`` — lets each finding that
    quotes or paraphrases the manuscript carry a "↗ go to text" link.
    """
    from src.ai.text_links import link_for_item, make_link, find_in_chapters
    chapters = chapters or []
    by_title = {title: cid for cid, title, _ in chapters}

    def link(item: str, chapter_title: str) -> str:
        if not chapters:
            return ""
        return link_for_item(item, chapters, by_title.get(chapter_title, ""))

    def quote_link(quote: str, chapter_title: str) -> str:
        if not chapters or not (quote or "").strip():
            return ""
        hit = find_in_chapters(quote, chapters, by_title.get(chapter_title, ""))
        return (" " + make_link(hit[0], hit[1])) if hit else ""

    lines = ["**Overall critique**", ""]
    if getattr(report, "overall_summary", ""):
        lines += [report.overall_summary.strip(), ""]
    for ch in getattr(report, "chapters", []) or []:
        lines.append(f"### {ch.chapter_title} ({ch.word_count:,} words)")
        for s in ch.sections:
            label = REPORT_LABELS.get(s.report_type.value, s.report_type.value.title())
            head = f"- **{label}:** {_short(s.summary, 200)}" if s.summary else f"- **{label}**"
            lines.append(head)
            for issue in (s.major_issues or [])[:issues_per_report]:
                lines.append(f"    - ⚠️ {_short(issue)}{link(issue, ch.chapter_title)}")
            if s.suggestions:
                lines.append(f"    - ➜ {_short(s.suggestions[0])}"
                             f"{link(s.suggestions[0], ch.chapter_title)}")
            for key in ("New elements (not in worldbuilding)", "Speakers with no character record"):
                items = (s.extra_lists or {}).get(key) or []
                if items:
                    lines.append(f"    - {key}: " + "; ".join(
                        _short(i, 60) + link(i, ch.chapter_title) for i in items[:4]))
        lines.append("")
    for res in promise_results or []:
        lines.append(f"### Promise & consistency check — {res.chapter_title}")
        lines.append(f"- Adherence: **{res.overall_adherence.replace('_', ' ')}**"
                     + (f" — {_short(res.summary, 200)}" if res.summary else ""))
        for v in res.promise_violations[:3]:
            lines.append(f"    - ⚠️ {v.promise_title} ({v.severity}): {_short(v.violation_description, 160)}"
                         + (f" ➜ {_short(v.suggestion, 120)}" if v.suggestion else "")
                         + quote_link(v.quote, res.chapter_title))
        for c in res.character_inconsistencies[:3]:
            lines.append(f"    - ⚠️ {c.character_name} — {_short(c.description, 160)}"
                         + (f" ➜ {_short(c.suggestion, 120)}" if c.suggestion else "")
                         + quote_link(c.quote, res.chapter_title))
        lines.append("")
    try:
        from src.data.critique_history import format_progress_markdown
        progress_md = format_progress_markdown(getattr(report, "progress", None), max_items=3)
        if progress_md:
            lines += [progress_md, ""]
    except Exception:
        pass
    lines.append("_The full reports — with per-finding ratings for training — are in the "
                 "**Critique** tab. Ask me about any point to dig in or fix it._")
    return "\n".join(lines).strip()


def critique_digest(report: Any, promise_results: Optional[list] = None,
                    max_chars: int = 3500) -> str:
    """Compact plain-text version for the conversation history, so
    follow-up questions ("how do I fix the Mara drift?") have the
    findings in context."""
    parts = ["[Overall critique results]"]
    if getattr(report, "overall_summary", ""):
        parts.append(_short(report.overall_summary, 800))
    for ch in getattr(report, "chapters", []) or []:
        parts.append(f"Chapter: {ch.chapter_title}")
        for s in ch.sections:
            label = REPORT_LABELS.get(s.report_type.value, s.report_type.value)
            bits = [_short(s.summary, 160)] + [_short(i, 160) for i in (s.major_issues or [])[:3]]
            if s.suggestions:
                bits.append("fix: " + _short(s.suggestions[0], 140))
            parts.append(f"- {label}: " + " | ".join(b for b in bits if b))
    for res in promise_results or []:
        parts.append(f"Promise check ({res.chapter_title}): {res.overall_adherence}. "
                     + "; ".join(_short(v.violation_description, 120) for v in res.promise_violations[:3]))
    text = "\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"
