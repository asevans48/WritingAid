"""Agentic project lookups for writer / chapter-focus / plot / long-form modes.

The model emits XML lookup tool calls before writing prose so it can
fetch the specific project elements it needs — characters, subplots,
worldbuilding entries, plot events, chapters, tensions, themes — and
then write with rich grounding instead of guessing or relying on
cosine-similarity RAG to surface the right thing.

The flow is a pre-flight planning round:

  Round 1 (model):  emits <lookup_*> tags for what it needs
  Engine:           parses, dispatches, formats results
  Round 2 (model):  receives LOOKUP RESULTS, either requests more
                    (capped at ``max_lookup_rounds``) or writes the
                    final response
  Round N+1 (engine): forces the final answer if the model is still
                    asking for lookups beyond the cap

This is a HYBRID design — the existing RAG dump still fires as the
baseline context (so the model always has something to work with),
and these tools layer on top so the model can ask for specifics.

Tool schema:

  <lookup_character>{"name": "Marcus"}</lookup_character>
  <lookup_subplot>{"title": "loyalty arc"}</lookup_subplot>
  <lookup_worldbuilding>{"category": "rituals", "query": "north temple"}</lookup_worldbuilding>
  <lookup_plot_event>{"title": "the betrayal"}</lookup_plot_event>
  <lookup_chapter>{"ref": "Ch3"}</lookup_chapter>
  <lookup_tension>{"title": "loyalty vs duty"}</lookup_tension>
  <lookup_theme>{"title": "redemption"}</lookup_theme>
  <search_project>{"query": "forge of frost", "categories": ["worldbuilding"]}</search_project>

Each tool's JSON body is parsed with ``json.loads`` after light
sanitisation so models that emit single-quoted JSON, trailing commas,
or stray prose around the block still work.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import WriterProject


# ── Tool tag schema ──────────────────────────────────────────────────


# Each tool is matched non-greedily so multiple lookups in one reply
# parse cleanly. Tags are case-insensitive on parse but emitted lowercase.
_LOOKUP_TAGS = (
    "lookup_character",
    "lookup_subplot",
    "lookup_worldbuilding",
    "lookup_plot_event",
    "lookup_chapter",
    "lookup_tension",
    "lookup_theme",
    # Project-wide semantic search across the author's own material
    # (characters / worldbuilding / chapters / subplots). NEVER hits
    # the encyclopedia — that's a separate tool below so the model
    # can't accidentally pull real-world reference data when it
    # meant project material.
    "search_project",
    # Real-world / mythology grounding. Hits the encyclopedia
    # source-type only. The model should use this when it wants
    # plausible real-world detail (e.g. "what does a real medieval
    # forge look like?") — NOT to fetch story facts.
    "lookup_encyclopedia",
)

_LOOKUP_RX = {
    name: re.compile(
        rf"<{name}>\s*(\{{.*?\}})\s*</{name}>",
        re.DOTALL | re.IGNORECASE)
    for name in _LOOKUP_TAGS
}

# Keys the model might pass in JSON. Normalised to lowercase strings.
_KEY_ALIASES = {
    "ref": ("ref", "chapter_ref", "chapter", "number", "n"),
    "name": ("name", "character", "title"),
    "title": ("title", "name"),
    "query": ("query", "q", "search", "keyword"),
    "category": ("category", "type", "kind"),
    "categories": ("categories", "types", "kinds"),
    "depth": ("depth", "detail", "level"),
    "limit": ("limit", "top_k", "k", "n"),
}


def _get_param(params: Dict[str, Any], canonical: str, default=None):
    """Pull a param by its canonical name, accepting common aliases."""
    aliases = _KEY_ALIASES.get(canonical, (canonical,))
    for alias in aliases:
        if alias in params and params[alias] not in (None, ""):
            return params[alias]
    return default


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    """Forgiving JSON parse for model-emitted tool args.

    Models occasionally emit single-quoted JSON, trailing commas, or
    JS-style ``True``/``False``/``None`` instead of lowercase. This
    helper reaches for the common parse paths in order and returns
    ``{}`` only when none work — so the dispatcher can soft-fail with
    a useful message instead of crashing.
    """
    if not raw:
        return {}
    candidates = [raw]
    # Common malformations
    candidates.append(raw.replace("'", '"'))
    candidates.append(re.sub(r",\s*([}\]])", r"\1", raw))
    candidates.append(re.sub(r"\bTrue\b", "true", raw))
    candidates.append(re.sub(r"\bFalse\b", "false", raw))
    candidates.append(re.sub(r"\bNone\b", "null", raw))
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return {}


# ── Lookup parsing ───────────────────────────────────────────────────


def extract_lookup_calls(response: str) -> List[Dict[str, Any]]:
    """Pull every lookup tag out of a model response.

    Returns a list of ``{"tool": str, "params": dict, "raw": str}``.
    Order is preserved (tools are dispatched in the order the model
    emitted them, which may matter for downstream summarisation).
    """
    calls: List[Tuple[int, Dict[str, Any]]] = []
    for tool, rx in _LOOKUP_RX.items():
        for m in rx.finditer(response):
            params = _safe_json_loads(m.group(1))
            calls.append((m.start(), {
                "tool": tool,
                "params": params,
                "raw": m.group(0),
            }))
    calls.sort(key=lambda x: x[0])
    return [c for _, c in calls]


def strip_lookup_calls(response: str) -> str:
    """Remove every lookup tag from a response (for chat display)."""
    out = response
    for rx in _LOOKUP_RX.values():
        out = rx.sub("", out)
    return out.strip()


# ── Per-tool handlers ────────────────────────────────────────────────


# WorldBuilding categories the user can target. Keys are user-facing
# strings; values are the actual ``WorldBuilding`` field name + a
# human-readable label.
_WORLDBUILDING_CATEGORIES = {
    "faction":            ("factions", "Faction"),
    "factions":           ("factions", "Faction"),
    "place":              ("places", "Place"),
    "places":             ("places", "Place"),
    "location":           ("places", "Place"),
    "locations":          ("places", "Place"),
    "architecture":       ("places", "Place / Architecture"),
    "culture":            ("cultures", "Culture"),
    "cultures":           ("cultures", "Culture"),
    "ritual":             ("cultures", "Culture (rituals)"),
    "rituals":            ("cultures", "Culture (rituals)"),
    "myth":               ("myths", "Myth"),
    "myths":              ("myths", "Myth"),
    "folklore":           ("myths", "Myth / Folklore"),
    "religion":           ("cultures", "Culture (religion)"),
    "religions":          ("cultures", "Culture (religion)"),
    "technology":         ("technologies", "Technology"),
    "technologies":       ("technologies", "Technology"),
    "magic":              ("technologies", "Technology / Magic"),
    "flora":              ("flora", "Flora"),
    "fauna":              ("fauna", "Fauna"),
    "history":            ("historical_events", "Historical event"),
    "historical":         ("historical_events", "Historical event"),
    "historical_event":   ("historical_events", "Historical event"),
    "historical_events":  ("historical_events", "Historical event"),
    "event":              ("historical_events", "Historical event"),
}


def _format_character(c) -> str:
    """Render a Character into a model-friendly profile block."""
    lines = [f"NAME: {c.name}",
             f"ROLE: {getattr(c, 'character_type', 'character')}"]
    fields = [
        ("Personality", getattr(c, "personality", "")),
        ("Personality traits", ", ".join(
            getattr(c, "personality_traits", []) or [])),
        ("Speaking style / voice", getattr(c, "speaking_style", "")),
        ("Emotional baseline", getattr(c, "emotional_baseline", "")),
        ("Want (external goal)", getattr(c, "want", "")),
        ("Need (internal truth)", getattr(c, "need", "")),
        ("Lie they believe", getattr(c, "lie_they_believe", "")),
        ("Ghost (formative wound)", getattr(c, "ghost", "")),
        ("Character arc", getattr(c, "character_arc", "")),
        ("Motivations", getattr(c, "motivations", "")),
        ("Fears", getattr(c, "fears", "")),
        ("Moral code", getattr(c, "moral_code", "")),
        ("Worldview", getattr(c, "worldview", "")),
        ("Secret", getattr(c, "secret", "")),
        ("Contradictions", getattr(c, "contradictions", "")),
        ("Defining relationship", getattr(c, "defining_relationship", "")),
        ("Quirks", getattr(c, "quirks", "")),
        ("Backstory", getattr(c, "backstory", "")),
        ("Physical description", getattr(c, "physical_description", "")),
    ]
    for label, value in fields:
        if value:
            lines.append(f"{label}: {_truncate(value, 600)}")
    # Social network — just names + relationships
    sn = getattr(c, "social_network", None) or {}
    if sn:
        rels = ", ".join(f"{k}: {v}" for k, v in list(sn.items())[:8])
        lines.append(f"Relationships: {_truncate(rels, 400)}")
    return "\n".join(lines)


def _handle_lookup_character(params: Dict[str, Any],
                              project: 'WriterProject',
                              rag_search: Optional[Callable]) -> str:
    name = (_get_param(params, "name") or "").strip()
    if not name:
        return "(lookup_character: missing 'name')"
    if not (project and project.characters):
        return f"(lookup_character: no characters defined in this project)"
    # Exact match first (case-insensitive)
    name_lower = name.lower()
    exact = [c for c in project.characters if c.name.lower() == name_lower]
    if not exact:
        # Substring / contains
        partial = [c for c in project.characters
                   if name_lower in c.name.lower()
                   or c.name.lower() in name_lower]
        if partial:
            exact = partial[:1]
    if not exact and rag_search:
        # Semantic fallback via RAG
        try:
            chunk = rag_search(name, ["character"])
            if chunk:
                return (f"(no exact character matched '{name}'; "
                        f"semantic candidates from project search:)\n"
                        f"{_truncate(chunk, 1200)}")
        except Exception:
            pass
    if not exact:
        # Show available names so the model can re-query
        avail = ", ".join(c.name for c in project.characters[:20])
        return (f"(no character named '{name}' found. "
                f"Known characters: {avail})")
    return _format_character(exact[0])


def _handle_lookup_subplot(params: Dict[str, Any],
                            project: 'WriterProject',
                            rag_search: Optional[Callable]) -> str:
    title = (_get_param(params, "title") or "").strip()
    if not title:
        return "(lookup_subplot: missing 'title')"
    sp = (project.story_planning if project else None)
    subplots = list(getattr(sp, "subplots", []) or []) if sp else []
    if not subplots:
        return "(no subplots defined in this project)"
    title_lower = title.lower()
    matches = [s for s in subplots if s.title.lower() == title_lower]
    if not matches:
        matches = [s for s in subplots
                   if title_lower in s.title.lower()
                   or s.title.lower() in title_lower]
    if not matches:
        avail = ", ".join(s.title for s in subplots[:15])
        return f"(no subplot matched '{title}'. Known: {avail})"
    sub = matches[0]
    lines = [
        f"SUBPLOT: {sub.title}",
        f"Status: {getattr(sub, 'status', 'active')}",
        f"Description: {_truncate(getattr(sub, 'description', ''), 800)}",
    ]
    conn = getattr(sub, "connection_to_main", "")
    if conn:
        lines.append(
            f"Connection to main plot: {_truncate(conn, 400)}")
    chars = getattr(sub, "related_characters", []) or []
    if chars:
        lines.append(f"Related characters: {', '.join(chars[:8])}")
    events = getattr(sub, "events", []) or []
    if events:
        lines.append(f"Subplot events ({len(events)} total):")
        for ev in events[:8]:
            t = getattr(ev, "title", "(beat)")
            d = getattr(ev, "description", "")
            stage = getattr(ev, "stage", "")
            lines.append(f"  - [{stage}] {t}: {_truncate(d, 200)}")
    return "\n".join(lines)


def _handle_lookup_worldbuilding(params: Dict[str, Any],
                                  project: 'WriterProject',
                                  rag_search: Optional[Callable]) -> str:
    raw_cat = (_get_param(params, "category") or "").strip().lower()
    query = (_get_param(params, "query") or "").strip()
    wb = project.worldbuilding if project else None
    if not wb:
        return "(no worldbuilding defined in this project)"
    if not raw_cat:
        cats = sorted(set(v[0] for v in _WORLDBUILDING_CATEGORIES.values()))
        return (f"(lookup_worldbuilding: missing 'category'. "
                f"Available: {', '.join(cats)})")
    cat_info = _WORLDBUILDING_CATEGORIES.get(raw_cat)
    if cat_info is None:
        cats = sorted(set(_WORLDBUILDING_CATEGORIES.keys()))
        return (f"(unknown worldbuilding category '{raw_cat}'. "
                f"Try one of: {', '.join(cats[:20])})")
    field_name, label = cat_info
    items = list(getattr(wb, field_name, []) or [])
    if not items:
        return f"(no {field_name} entries in worldbuilding)"
    # Filter by query when provided. Match against name/title/description.
    if query:
        ql = query.lower()
        filtered = []
        for it in items:
            haystack = " ".join(str(getattr(it, attr, "") or "")
                                for attr in ("name", "title",
                                             "description", "summary",
                                             "details", "rituals",
                                             "beliefs", "architecture"))
            if ql in haystack.lower():
                filtered.append(it)
        if not filtered and rag_search:
            # RAG fallback for fuzzy worldbuilding queries
            try:
                chunk = rag_search(query, ["worldbuilding"])
                if chunk:
                    return (f"({label} — no direct matches for "
                            f"'{query}'; semantic candidates:)\n"
                            f"{_truncate(chunk, 1200)}")
            except Exception:
                pass
        items = filtered or items[:5]  # fall back to first few
    out = [f"WORLDBUILDING — {label} ({len(items)} entries):"]
    for it in items[:6]:
        name = (getattr(it, "name", None)
                or getattr(it, "title", None)
                or "(unnamed)")
        desc = (getattr(it, "description", "")
                or getattr(it, "summary", "")
                or getattr(it, "details", ""))
        out.append(f"\n--- {name} ---")
        if desc:
            out.append(_truncate(desc, 600))
        # Pull other useful per-type fields
        extras = []
        for attr in ("type", "leader", "size", "ideology", "secret",
                     "rituals", "beliefs", "architecture",
                     "language", "customs", "taboos",
                     "principles", "limits", "cost",
                     "habitat", "behavior", "danger",
                     "atmosphere", "history", "significance"):
            v = getattr(it, attr, None)
            if v and isinstance(v, str) and v.strip():
                extras.append(f"  {attr}: {_truncate(v, 200)}")
        if extras:
            out.extend(extras[:6])
    if len(items) > 6:
        out.append(f"\n…{len(items) - 6} more {field_name} not shown.")
    return "\n".join(out)


def _handle_lookup_plot_event(params: Dict[str, Any],
                                project: 'WriterProject',
                                rag_search: Optional[Callable]) -> str:
    title = (_get_param(params, "title") or "").strip()
    sp = (project.story_planning if project else None)
    fp = getattr(sp, "freytag_pyramid", None) if sp else None
    events = list(getattr(fp, "events", []) or []) if fp else []
    if not events:
        return "(no plot events defined in this project's Freytag pyramid)"
    if not title:
        out = [f"PLOT EVENTS ({len(events)} total):"]
        for ev in events[:12]:
            out.append(f"  - [{ev.stage}] {ev.title}: "
                       f"{_truncate(ev.description, 160)}")
        return "\n".join(out)
    title_lower = title.lower()
    matches = [e for e in events if e.title.lower() == title_lower]
    if not matches:
        matches = [e for e in events
                   if title_lower in e.title.lower()
                   or e.title.lower() in title_lower]
    if not matches:
        avail = ", ".join(e.title for e in events[:12])
        return f"(no plot event matched '{title}'. Known: {avail})"
    ev = matches[0]
    lines = [
        f"PLOT EVENT: {ev.title}",
        f"Stage: {ev.stage}",
        f"Act: {ev.act}",
        f"Intensity: {ev.intensity}/100",
    ]
    if ev.description:
        lines.append(f"Description: {_truncate(ev.description, 800)}")
    if ev.outcome:
        lines.append(f"Outcome: {_truncate(ev.outcome, 400)}")
    if ev.related_characters:
        lines.append("Related characters: "
                     + ", ".join(ev.related_characters[:8]))
    if ev.related_subplots:
        lines.append("Related subplots: "
                     + ", ".join(ev.related_subplots[:5]))
    if ev.notes:
        lines.append(f"Notes: {_truncate(ev.notes, 300)}")
    return "\n".join(lines)


def _handle_lookup_chapter(params: Dict[str, Any],
                            project: 'WriterProject',
                            rag_search: Optional[Callable]) -> str:
    ref = (_get_param(params, "ref")
           or _get_param(params, "title") or "")
    ref = str(ref).strip()
    if not ref:
        return "(lookup_chapter: missing 'ref')"
    chapters = list(project.manuscript.chapters or []) if (
        project and project.manuscript) else []
    if not chapters:
        return "(no chapters in this project)"
    # Try "Ch3" / "Chapter 3" / number
    target = None
    m = re.search(r"\d+", ref)
    if m:
        n = int(m.group(0))
        for c in chapters:
            if c.number == n:
                target = c
                break
    if target is None:
        ref_lower = ref.lower()
        for c in chapters:
            if c.title.lower() == ref_lower:
                target = c
                break
        if target is None:
            for c in chapters:
                if (ref_lower in c.title.lower()
                        or c.title.lower() in ref_lower):
                    target = c
                    break
    if target is None:
        avail = ", ".join(f"Ch{c.number}: {c.title}" for c in chapters[:10])
        return f"(no chapter matched '{ref}'. Known: {avail})"
    lines = [f"CHAPTER {target.number}: {target.title}"]
    cp = getattr(target, "planning", None)
    if cp:
        if cp.description:
            lines.append(f"Description: {_truncate(cp.description, 500)}")
        elif cp.outline:
            lines.append(f"Outline: {_truncate(cp.outline, 500)}")
        if cp.pov_character:
            lines.append(f"POV: {cp.pov_character}")
        if cp.tone:
            lines.append(f"Tone: {cp.tone}")
        if cp.voice:
            lines.append(f"Voice: {cp.voice}")
        events = list(getattr(cp, "events", []) or [])
        if events:
            lines.append("Planned story events:")
            for ev in events[:8]:
                t = getattr(ev, "text", "(beat)")
                d = getattr(ev, "description", "")
                stage = getattr(ev, "stage", "")
                lines.append(f"  - [{stage}] {t}: {_truncate(d, 200)}")
    if target.content:
        # Surface the opening + closing of the chapter so the model
        # has anchor passages without dumping the whole thing.
        text = target.content.strip()
        words = text.split()
        if len(words) <= 200:
            lines.append(f"Content:\n{text}")
        else:
            opening = " ".join(words[:120])
            closing = " ".join(words[-120:])
            lines.append(f"Opening:\n{opening}")
            lines.append(f"\nClosing:\n{closing}")
    return "\n".join(lines)


def _handle_lookup_tension(params: Dict[str, Any],
                             project: 'WriterProject',
                             rag_search: Optional[Callable]) -> str:
    title = (_get_param(params, "title") or "").strip()
    sp = (project.story_planning if project else None)
    tensions = list(getattr(sp, "tensions", []) or []) if sp else []
    if not tensions:
        return "(no character tensions defined in this project)"
    if not title:
        out = [f"STORY TENSIONS ({len(tensions)} total):"]
        for t in tensions[:10]:
            out.append(f"  - [{t.tension_type}] {t.title} "
                       f"({t.current_state}, intensity {t.intensity}): "
                       f"{_truncate(t.description, 160)}")
        return "\n".join(out)
    tl = title.lower()
    matches = [t for t in tensions
               if t.title.lower() == tl
               or tl in t.title.lower()
               or t.title.lower() in tl]
    if not matches:
        avail = ", ".join(t.title for t in tensions[:10])
        return f"(no tension matched '{title}'. Known: {avail})"
    t = matches[0]
    lines = [
        f"TENSION: {t.title}",
        f"Type: {t.tension_type}",
        f"Current state: {t.current_state}",
        f"Intensity: {t.intensity}/100",
        f"Description: {_truncate(t.description, 600)}",
    ]
    if t.stakes:
        lines.append(f"Stakes: {_truncate(t.stakes, 400)}")
    if t.characters_involved:
        lines.append("Characters involved: "
                     + ", ".join(t.characters_involved[:8]))
    return "\n".join(lines)


def _handle_lookup_theme(params: Dict[str, Any],
                          project: 'WriterProject',
                          rag_search: Optional[Callable]) -> str:
    title = (_get_param(params, "title") or "").strip()
    sp = (project.story_planning if project else None)
    themes = list(getattr(sp, "theme_details", []) or []) if sp else []
    if not themes:
        # Fall back to legacy ``themes: List[str]``
        legacy = list(getattr(sp, "themes", []) or []) if sp else []
        if legacy:
            return ("Themes (legacy text labels):\n"
                    + "\n".join(f"  - {t}" for t in legacy[:10]))
        return "(no themes defined in this project)"
    if not title:
        out = [f"THEMES ({len(themes)} total):"]
        for th in themes[:8]:
            out.append(f"  - {th.title}: {_truncate(th.description, 200)}")
        return "\n".join(out)
    tl = title.lower()
    matches = [th for th in themes
               if th.title.lower() == tl
               or tl in th.title.lower()
               or th.title.lower() in tl]
    if not matches:
        avail = ", ".join(t.title for t in themes[:10])
        return f"(no theme matched '{title}'. Known: {avail})"
    th = matches[0]
    lines = [
        f"THEME: {th.title}",
        f"Description: {_truncate(th.description, 500)}",
    ]
    if th.statement:
        lines.append(f"Statement: {_truncate(th.statement, 400)}")
    if th.motifs:
        lines.append(f"Motifs: {', '.join(th.motifs[:8])}")
    if th.related_characters:
        lines.append(f"Carried by characters: "
                     + ", ".join(th.related_characters[:6]))
    return "\n".join(lines)


def _handle_search_project(params: Dict[str, Any],
                            project: 'WriterProject',
                            rag_search: Optional[Callable]) -> str:
    query = (_get_param(params, "query") or "").strip()
    cats = _get_param(params, "categories") or []
    if isinstance(cats, str):
        cats = [c.strip() for c in cats.split(",") if c.strip()]
    if not query:
        return "(search_project: missing 'query')"
    if not rag_search:
        return ("(search_project: project search index isn't "
                "available — RAG provider not wired)")
    # Map UI categories → RAG source types. ``encyclopedia`` is
    # deliberately NOT in this map — the model must use the
    # dedicated ``<lookup_encyclopedia>`` tool to fetch real-world
    # reference data, so project searches never bleed encyclopedia
    # hits into the story material.
    cat_map = {
        "character": "character",
        "characters": "character",
        "worldbuilding": "worldbuilding",
        "world": "worldbuilding",
        "subplot": "subplot",
        "subplots": "subplot",
        "chapter": "chapter",
        "chapters": "chapter",
        "place": "place",
        "places": "place",
        "faction": "faction",
        "factions": "faction",
        "culture": "culture",
        "cultures": "culture",
    }
    if cats:
        # If the caller asked for "encyclopedia", redirect them with
        # a clear soft-fail message so the next round can use the
        # right tool.
        bad = [c for c in cats if c.lower() in (
            "encyclopedia", "reference", "real-world", "real_world")]
        if bad:
            return ("(search_project: encyclopedia / real-world "
                    "reference is NOT a project category. Use "
                    "<lookup_encyclopedia> for that.)")
        source_types = list({cat_map.get(c.lower(), c.lower())
                              for c in cats})
    else:
        source_types = ["character", "worldbuilding",
                        "subplot", "chapter"]
    try:
        result = rag_search(query, source_types)
    except Exception as e:
        return f"(search_project failed: {e})"
    if not result:
        return f"(search_project: no matches for '{query}' in {source_types})"
    return _truncate(result, 2000)


def _handle_lookup_encyclopedia(params: Dict[str, Any],
                                  project: 'WriterProject',
                                  rag_search: Optional[Callable]) -> str:
    """Real-world / mythology lookup via the encyclopedia source type.

    Distinct from ``search_project`` — this is the ONLY way to fetch
    encyclopedia entries. Use when the writer wants plausible real-
    world detail (a smith's tools, a saint's iconography, the layout
    of a medieval town) as inspiration for fiction. NEVER use to
    fetch story facts; the project's own modules carry those.
    """
    query = (_get_param(params, "query") or "").strip()
    if not query:
        return "(lookup_encyclopedia: missing 'query')"
    if not rag_search:
        return ("(lookup_encyclopedia: encyclopedia search isn't "
                "available — RAG provider not wired)")
    try:
        result = rag_search(query, ["encyclopedia"])
    except Exception as e:
        return f"(lookup_encyclopedia failed: {e})"
    if not result:
        return (f"(lookup_encyclopedia: no encyclopedia entries "
                f"matched '{query}')")
    return ("ENCYCLOPEDIA — real-world reference (use to ground "
            "fiction in plausible details; NOT a source for story "
            "facts):\n" + _truncate(result, 2000))


_HANDLERS: Dict[str, Callable] = {
    "lookup_character":      _handle_lookup_character,
    "lookup_subplot":        _handle_lookup_subplot,
    "lookup_worldbuilding":  _handle_lookup_worldbuilding,
    "lookup_plot_event":     _handle_lookup_plot_event,
    "lookup_chapter":        _handle_lookup_chapter,
    "lookup_tension":        _handle_lookup_tension,
    "lookup_theme":          _handle_lookup_theme,
    "search_project":        _handle_search_project,
    "lookup_encyclopedia":   _handle_lookup_encyclopedia,
}


# ── Dispatcher ───────────────────────────────────────────────────────


def dispatch_lookups(
    calls: List[Dict[str, Any]],
    project: Optional['WriterProject'],
    rag_search: Optional[Callable[[str, List[str]], str]] = None,
) -> List[Dict[str, Any]]:
    """Run each lookup call and return the results.

    Returns a list of ``{"tool": str, "params": dict, "result": str}``
    in the same order the calls came in. Handlers never raise; they
    return a soft-fail message string instead, so the caller can
    always concatenate results into the LOOKUP RESULTS block.
    """
    out: List[Dict[str, Any]] = []
    for call in calls:
        tool = call.get("tool", "")
        params = call.get("params", {}) or {}
        handler = _HANDLERS.get(tool)
        if handler is None:
            result = f"(unknown lookup tool: {tool})"
        else:
            try:
                result = handler(params, project, rag_search) or "(empty result)"
            except Exception as e:  # pragma: no cover — defensive
                result = f"({tool} failed: {e})"
        out.append({"tool": tool, "params": params, "result": result})
    return out


def format_lookup_results_block(
    results: List[Dict[str, Any]], round_index: int = 1) -> str:
    """Render dispatched results as a single LOOKUP RESULTS block to
    feed back to the model.
    """
    if not results:
        return ""
    lines = [
        f"=== LOOKUP RESULTS (round {round_index}) ===",
        "",
    ]
    for i, r in enumerate(results, 1):
        params_repr = json.dumps(r.get("params", {}), ensure_ascii=False)
        lines.append(f"--- [{i}/{len(results)}] {r['tool']} {params_repr} ---")
        lines.append(r["result"])
        lines.append("")
    lines.append(
        "Use these results to ground your writing. If you need more "
        "lookups, emit them now (max 1 more round). Otherwise, "
        "produce the final response.")
    return "\n".join(lines)


# ── Pre-flight loop ──────────────────────────────────────────────────


# System-prompt section every wired surface gets. Documents the tools
# + the protocol (use BEFORE writing, capped rounds, then proceed).
LOOKUP_TOOLS_PROMPT_BLOCK = """=== LOOKUP TOOLS ===
You can fetch specific elements before writing. The engine intercepts these tags and feeds the results back to you.

There are TWO distinct sources, and the tools are split so you can never confuse them:

  PROJECT TOOLS — the AUTHORITATIVE story material the author has built (characters, worldbuilding, chapters, subplots, plot beats, themes, tensions). All story facts come from here.

  REFERENCE TOOL — encyclopedia / real-world / mythology lookups. Use ONLY for grounding fiction in plausible real-world details (a saint's iconography, the layout of a medieval forge, a real folk myth that parallels the chapter's theme). NEVER a source for story facts — those are always project material.

── PROJECT TOOLS ──

<lookup_character>{"name": "Marcus"}</lookup_character>
  → Full character profile: personality, voice, arc, motivations, quirks, relationships.

<lookup_subplot>{"title": "the loyalty arc"}</lookup_subplot>
  → Subplot details + status + connection to the main plot + event arc.

<lookup_worldbuilding>{"category": "rituals", "query": "north temple"}</lookup_worldbuilding>
  → Categories: factions, places (architecture), cultures (rituals, religion), myths (folklore), technologies (magic), flora, fauna, historical_events. Query is optional — omit it to list the whole category. THIS IS THE PROJECT'S OWN WORLDBUILDING — not encyclopedia entries.

<lookup_plot_event>{"title": "the betrayal"}</lookup_plot_event>
  → Plot beat from the Freytag pyramid: stage, intensity, related characters, outcome.

<lookup_chapter>{"ref": "Ch3"}</lookup_chapter>
  → Chapter synopsis + planned events + opening/closing passages. Use "Ch3", "Chapter 3", or the chapter title.

<lookup_tension>{"title": "loyalty vs duty"}</lookup_tension>
  → Sustained tension: type, current state, intensity, stakes, characters involved.

<lookup_theme>{"title": "redemption"}</lookup_theme>
  → Theme: description, statement, motifs, characters who carry it.

<search_project>{"query": "forge of frost", "categories": ["worldbuilding"]}</search_project>
  → Semantic search across PROJECT material only (no encyclopedia). Use as a fallback when the named tools don't fit. Categories: character, worldbuilding, subplot, chapter, place, faction, culture.

── REFERENCE TOOL ──

<lookup_encyclopedia>{"query": "medieval blacksmith forge layout"}</lookup_encyclopedia>
  → Real-world / mythology grounding. Returns encyclopedia entries that match the query so you can pull authentic real-world details into the prose. NEVER use to fetch story facts (use project tools for that).

PROTOCOL:
- Use lookups BEFORE you write. Reach for project tools whenever you'd otherwise guess at a name, ritual, location detail, character voice, or how a subplot is supposed to land. Reach for the encyclopedia tool when you want a real-world parallel to ground the prose.
- Emit a batch in one reply — the engine dispatches them in parallel and feeds all results back at once.
- After receiving results, either emit MORE lookups (capped at 2 rounds total) or produce your final response (the prose, the answer, etc.).
- After 2 lookup rounds the engine forces the final response. Don't stack lookup rounds when you already have what you need.
- The lookup tags themselves are stripped before display, so they don't leak into the chat or the manuscript."""


def has_lookup_calls(response: str) -> bool:
    """Cheap check — does this response contain any lookup tag?"""
    return any(rx.search(response) for rx in _LOOKUP_RX.values())


def run_with_lookups(
    llm: 'LLMClient',
    prompt: str,
    system_prompt: str,
    project: Optional['WriterProject'],
    rag_search: Optional[Callable[[str, List[str]], str]] = None,
    max_tokens: int = 6000,
    temperature: float = 0.7,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    max_lookup_rounds: int = 2,
    continue_if_truncated: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pre-flight lookup loop wrapper around ``llm.generate_text``.

    Round 1: send the prompt; the model may emit lookup tags.
    Round N: dispatch any lookups, feed results back, ask for more
    or final.
    Round max+1: force the final response (no more lookup rounds).

    Returns ``(final_response, lookup_log)`` where ``lookup_log`` is a
    list of ``{"round": int, "calls": [...], "results": [...]}`` so
    callers can audit what the model fetched.
    """
    history = list(conversation_history or [])
    lookup_log: List[Dict[str, Any]] = []
    current_prompt = prompt

    # Meta-token sanitiser keeps Harmony / ChatML / Llama 3 / Mistral
    # leakage out of the lookup-tag parser. A model that's degrading
    # (emitting ``<|channel|>thought`` instead of prose) would
    # otherwise corrupt every loop round. ``is_degenerate_output``
    # operates on the RAW response (pre-strip) so callers can
    # distinguish "model emitted only meta tokens" from "model
    # emitted clean prose with stray markers".
    from src.ai.output_sanitizer import (
        strip_meta_tokens, is_degenerate_output)

    for round_idx in range(max_lookup_rounds + 1):
        is_final_round = (round_idx == max_lookup_rounds)
        # On the forced-final round, append a directive to the prompt
        # so the model stops asking for more lookups.
        prompt_for_round = current_prompt
        if is_final_round and lookup_log:
            prompt_for_round = (
                f"{current_prompt}\n\n"
                "(LOOKUP CAP REACHED — produce the final response now. "
                "Do not emit any more <lookup_*> tags; use what you "
                "already have.)")
        if progress_cb:
            if round_idx == 0:
                progress_cb("Sending initial prompt…")
            elif is_final_round:
                progress_cb(f"Lookup cap reached — forcing final response…")
            else:
                progress_cb(f"Lookup round {round_idx} returned; checking "
                            "if model wants more…")

        raw_response = llm.generate_text(
            prompt=prompt_for_round,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            conversation_history=history,
            continue_if_truncated=continue_if_truncated,
        )
        # Degeneration check on the RAW response — a model that's
        # leaked mostly meta-tokens (Harmony / ChatML / etc.) is in
        # a broken state and won't produce useful output by retrying.
        # Return empty string + a degeneration marker in the log so
        # callers can fall back / surface a clear error to the user.
        if is_degenerate_output(raw_response or ""):
            lookup_log.append({
                "round": round_idx + 1,
                "degenerate": True,
                "raw_preview": (raw_response or "")[:200],
            })
            if progress_cb:
                progress_cb(
                    "Model output was mostly meta-token spam; "
                    "aborting lookup loop.")
            return "", lookup_log
        # Strip meta-tokens BEFORE the tag parser sees the response
        # so a corrupted model output doesn't masquerade as a
        # malformed lookup tag.
        response = strip_meta_tokens(raw_response or "")

        # If we forced final OR no lookups were requested, return.
        calls = extract_lookup_calls(response)
        if is_final_round or not calls:
            # Strip any lookup tags that snuck through on the final
            # round so they never leak into prose / chat display.
            return strip_lookup_calls(response), lookup_log

        # Dispatch and feed results back as the next user turn.
        if progress_cb:
            progress_cb(
                f"Round {round_idx + 1}: dispatching "
                f"{len(calls)} lookup(s)…")
        results = dispatch_lookups(calls, project, rag_search)
        lookup_log.append({
            "round": round_idx + 1,
            "calls": calls,
            "results": results,
        })

        # Append round to history so the model sees its own lookups
        # (assistant turn) + the engine's results (next user turn).
        history.append({"role": "user", "content": current_prompt
                        if round_idx == 0 else prompt_for_round})
        history.append({"role": "assistant", "content": response})
        results_block = format_lookup_results_block(
            results, round_index=round_idx + 1)
        # The next round's prompt is the lookup results block — the
        # model will reply with either more lookups or the final
        # response.
        current_prompt = results_block

    # Should not reach here — the loop returns on the final round.
    return response, lookup_log
