"""Agentic tool layer for the slide-deck editor.

Small local models (Gemma 4B, 7-8B Llama/Qwen, …) can't be trusted to
call the render pipeline directly, so this module exposes the deck's
features as a SMALL set of deterministic, strongly-typed tools. The
model emits a JSON list of ``{"tool": name, "args": {...}}`` actions;
``run_agent_turn`` validates every argument against the tool spec —
coercing types, filling defaults, clamping ranges, snapping enums —
so even a sloppy model produces production-safe, deterministic output.

The tools reuse the same models + helpers the UI uses, so an agent
edit is identical to a hand edit. No Qt here — pure model logic, so it
is unit-testable and reusable from any chat surface.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.video_studio.models import (
    CHAPTER_TRANSITIONS, SlideDeckProject, SlideGroup, SlidePage,
    TitleCard,
)

_TRANSITION_KEYS = [k for k, _ in CHAPTER_TRANSITIONS]
_POSITIONS = ["center", "top", "bottom"]
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------
# Parameter validation → deterministic values
# ---------------------------------------------------------------------
def _coerce(spec: Dict[str, Any], raw: Any) -> Any:
    """Coerce ``raw`` to the spec's type, applying default / clamp /
    enum-snap. Never raises — an unusable value becomes the default."""
    t = spec["type"]
    default = spec.get("default")
    if raw is None:
        return default
    try:
        if t == "str":
            v = str(raw).strip()
            return v if v != "" else default
        if t == "color":
            v = str(raw).strip()
            if v == "":
                return default
            if not v.startswith("#"):
                v = "#" + v
            return v if _HEX_RE.match(v) else default
        if t == "int":
            v = int(round(float(raw)))
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v
        if t == "float":
            v = float(raw)
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in (
                "1", "true", "yes", "on", "y")
        if t == "enum":
            v = str(raw).strip().lower()
            return v if v in spec["choices"] else default
    except (TypeError, ValueError):
        return default
    return default


def _clean_args(tool: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate every arg against the tool's param specs, dropping
    unknowns and filling defaults."""
    args = args or {}
    out: Dict[str, Any] = {}
    for name, spec in tool["params"].items():
        out[name] = _coerce(spec, args.get(name))
    return out


# ---------------------------------------------------------------------
# Deck helpers
# ---------------------------------------------------------------------
def _page_at(deck: SlideDeckProject, one_based: int) -> Optional[SlidePage]:
    # Use the deck's group/render order so "slide #N" matches what the
    # user sees in the editor's slide list.
    from src.video_studio.slide_deck import ordered_pages
    pages = ordered_pages(deck)
    idx = int(one_based) - 1
    if 0 <= idx < len(pages):
        return pages[idx]
    return None


def _group_at(deck: SlideDeckProject, one_based: int) -> Optional[SlideGroup]:
    idx = int(one_based) - 1
    if 0 <= idx < len(deck.groups):
        return deck.groups[idx]
    return None


def _overlay_from_args(a: Dict[str, Any]) -> TitleCard:
    return TitleCard(
        role="overlay",
        title=a.get("title", "") or "",
        subtitle=a.get("subtitle", "") or "",
        title_color=a.get("title_color", "#FFFFFF"),
        subtitle_color=a.get("subtitle_color", "#DDDDDD"),
        text_position=a.get("position", "center"),
        text_fade_seconds=0.0,
        text_outline_color=(
            a.get("outline_color", "#000000")
            if a.get("outline") else ""),
        text_outline_width=3 if a.get("outline") else 0,
        text_shadow=bool(a.get("shadow")),
        text_box_color=(
            a.get("box_color", "#000000") if a.get("box") else ""),
        text_box_opacity=0.5,
    )


def _card_from_args(a: Dict[str, Any], role: str) -> TitleCard:
    return TitleCard(
        role=role,
        kind="color",
        bg_color=a.get("bg_color", "#101830"),
        title=a.get("title", "") or "",
        subtitle=a.get("subtitle", "") or "",
        title_color=a.get("title_color", "#FFFFFF"),
        subtitle_color=a.get("subtitle_color", "#DDDDDD"),
        text_position=a.get("position", "center"),
        text_fade_seconds=a.get("fade_seconds", 0.6),
    )


# ---------------------------------------------------------------------
# Tool implementations (each returns a human-readable result string)
# ---------------------------------------------------------------------
def _add_card(deck: SlideDeckProject, a: Dict[str, Any], role: str) -> str:
    is_title = role == "title"
    card = _card_from_args(a, role)
    page = SlidePage(
        label=("Title card" if is_title else "Ending card"),
        card=card,
        duration_seconds=a.get("duration_seconds", 4.0),
        start_time_seconds_in_group=0.0)
    group = SlideGroup(
        name=("Title card" if is_title else "Ending card"))
    group.inter_group_transition_in = a.get("transition", "fade")
    group.inter_group_transition_seconds = a.get(
        "transition_seconds", 0.8)
    page.group_id = group.id
    group.page_ids = [page.id]
    deck.pages.append(page)
    if is_title:
        deck.groups.insert(0, group)
    else:
        deck.groups.append(group)
    where = "front" if is_title else "back"
    return (f"Added {role} card '{card.title or '(untitled)'}' at the "
            f"{where} ({a.get('duration_seconds', 4.0):.1f}s, "
            f"{group.inter_group_transition_in} transition).")


def _tool_add_title_card(deck, a):
    return _add_card(deck, a, "title")


def _tool_add_ending_card(deck, a):
    return _add_card(deck, a, "ending")


def _tool_set_slide_text(deck, a):
    page = _page_at(deck, a["slide"])
    if page is None:
        return f"No slide #{a['slide']} (deck has {len(deck.pages)})."
    if not (a.get("title", "").strip() or a.get("subtitle", "").strip()):
        page.text_overlay = None
        return f"Cleared text overlay on slide #{a['slide']}."
    page.text_overlay = _overlay_from_args(a)
    fx = []
    if a.get("outline"):
        fx.append("outline")
    if a.get("shadow"):
        fx.append("shadow")
    if a.get("box"):
        fx.append("box")
    return (f"Set text on slide #{a['slide']}: "
            f"'{a.get('title', '')}'"
            + (f" / '{a.get('subtitle')}'" if a.get('subtitle') else "")
            + (f" [{', '.join(fx)}]" if fx else "") + ".")


def _tool_set_slide_duration(deck, a):
    page = _page_at(deck, a["slide"])
    if page is None:
        return f"No slide #{a['slide']}."
    page.duration_seconds = a["seconds"]
    return f"Slide #{a['slide']} now {a['seconds']:.2f}s."


def _tool_set_slide_transition(deck, a):
    page = _page_at(deck, a["slide"])
    if page is None:
        return f"No slide #{a['slide']}."
    page.transition_in = a["kind"]
    page.transition_seconds = a["seconds"]
    return (f"Slide #{a['slide']} transition → {a['kind']} "
            f"({a['seconds']:.2f}s).")


def _tool_set_group_transition(deck, a):
    g = _group_at(deck, a["group"])
    if g is None:
        return f"No group #{a['group']} (deck has {len(deck.groups)})."
    g.inter_group_transition_in = a["kind"]
    g.inter_group_transition_seconds = a["seconds"]
    return (f"Group #{a['group']} ('{g.name}') transition → "
            f"{a['kind']} ({a['seconds']:.2f}s).")


def _tool_set_black_gap(deck, a):
    g = _group_at(deck, a["group"])
    if g is None:
        return f"No group #{a['group']}."
    g.pre_black_seconds = a["seconds"]
    return (f"Group #{a['group']} ('{g.name}') now has a "
            f"{a['seconds']:.2f}s black gap before it.")


def _tool_set_background_volume(deck, a):
    deck.background_gain_db = a["db"]
    return f"Background bed level set to {a['db']:.1f} dB."


def _tool_set_background_mode(deck, a):
    deck.background_is_universal = a["universal"]
    return ("Background bed set to "
            + ("UNIVERSAL (under the whole deck)."
               if a["universal"]
               else "gap-fill (only where a group has no bed)."))


def _tool_set_background_finish_loop(deck, a):
    deck.background_complete_final_loop = a["enabled"]
    return ("Background will "
            + ("finish its final loop past the last slide."
               if a["enabled"] else "cut at the deck's end."))


def _tool_set_compression(deck, a):
    deck.export_target_size_mb = a["mb"]
    if a["mb"] <= 0:
        return "Compression target cleared (export at default quality)."
    return f"Export will compress to ~{a['mb']:.0f} MB (two-pass)."


def _tool_remove_slide(deck, a):
    page = _page_at(deck, a["slide"])
    if page is None:
        return f"No slide #{a['slide']} (deck has {len(deck.pages)})."
    label = page.label or "slide"
    deck.pages = [p for p in deck.pages if p.id != page.id]
    for g in deck.groups:
        g.page_ids = [pid for pid in g.page_ids if pid != page.id]
    return f"Removed slide #{a['slide']} ('{label}')."


def _tool_remove_group(deck, a):
    g = _group_at(deck, a["group"])
    if g is None:
        return f"No group #{a['group']} (deck has {len(deck.groups)})."
    members = [p for p in deck.pages if p.group_id == g.id]
    ids = {p.id for p in members}
    name = g.name or g.id
    deck.pages = [p for p in deck.pages if p.id not in ids]
    deck.groups = [gg for gg in deck.groups if gg.id != g.id]
    return (f"Removed group #{a['group']} ('{name}') and its "
            f"{len(members)} slide(s).")


def _tool_list_slides(deck, a):
    return deck_state_summary(deck)


# ---------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------
_CARD_PARAMS = {
    "title": {"type": "str", "default": ""},
    "subtitle": {"type": "str", "default": ""},
    "bg_color": {"type": "color", "default": "#101830"},
    "title_color": {"type": "color", "default": "#FFFFFF"},
    "subtitle_color": {"type": "color", "default": "#DDDDDD"},
    "position": {"type": "enum", "choices": _POSITIONS,
                 "default": "center"},
    "fade_seconds": {"type": "float", "min": 0.0, "max": 5.0,
                     "default": 0.6},
    "duration_seconds": {"type": "float", "min": 0.5, "max": 60.0,
                         "default": 4.0},
    "transition": {"type": "enum", "choices": _TRANSITION_KEYS,
                   "default": "fade"},
    "transition_seconds": {"type": "float", "min": 0.0, "max": 5.0,
                           "default": 0.8},
}

_TEXT_PARAMS = {
    "slide": {"type": "int", "min": 1, "default": 1},
    "title": {"type": "str", "default": ""},
    "subtitle": {"type": "str", "default": ""},
    "title_color": {"type": "color", "default": "#FFFFFF"},
    "subtitle_color": {"type": "color", "default": "#DDDDDD"},
    "position": {"type": "enum", "choices": _POSITIONS,
                 "default": "bottom"},
    "outline": {"type": "bool", "default": False},
    "outline_color": {"type": "color", "default": "#000000"},
    "shadow": {"type": "bool", "default": False},
    "box": {"type": "bool", "default": False},
    "box_color": {"type": "color", "default": "#000000"},
}

TOOLS: List[Dict[str, Any]] = [
    {"name": "add_title_card",
     "desc": "Add an opening title card (colored background + styled "
             "text) at the FRONT of the deck.",
     "params": _CARD_PARAMS, "fn": _tool_add_title_card},
    {"name": "add_ending_card",
     "desc": "Add a closing card at the BACK of the deck (credits / "
             "'The End').",
     "params": _CARD_PARAMS, "fn": _tool_add_ending_card},
    {"name": "set_slide_text",
     "desc": "Burn a styled text overlay (title/subtitle + color + "
             "outline/shadow/box) onto an existing image slide. Empty "
             "title AND subtitle clears it.",
     "params": _TEXT_PARAMS, "fn": _tool_set_slide_text},
    {"name": "set_slide_duration",
     "desc": "Set how long a slide holds on screen.",
     "params": {
         "slide": {"type": "int", "min": 1, "default": 1},
         "seconds": {"type": "float", "min": 0.5, "max": 120.0,
                     "default": 4.0}},
     "fn": _tool_set_slide_duration},
    {"name": "set_slide_transition",
     "desc": "Set the transition INTO a slide.",
     "params": {
         "slide": {"type": "int", "min": 1, "default": 1},
         "kind": {"type": "enum", "choices": _TRANSITION_KEYS,
                  "default": "fade"},
         "seconds": {"type": "float", "min": 0.0, "max": 5.0,
                     "default": 0.7}},
     "fn": _tool_set_slide_transition},
    {"name": "set_group_transition",
     "desc": "Set the transition into a GROUP from the previous one.",
     "params": {
         "group": {"type": "int", "min": 1, "default": 1},
         "kind": {"type": "enum", "choices": _TRANSITION_KEYS,
                  "default": "fade"},
         "seconds": {"type": "float", "min": 0.0, "max": 5.0,
                     "default": 0.7}},
     "fn": _tool_set_group_transition},
    {"name": "set_black_gap",
     "desc": "Insert N seconds of BLACK before a group as a scene "
             "break.",
     "params": {
         "group": {"type": "int", "min": 1, "default": 1},
         "seconds": {"type": "float", "min": 0.0, "max": 30.0,
                     "default": 1.0}},
     "fn": _tool_set_black_gap},
    {"name": "set_background_volume",
     "desc": "Set the deck background music level in dB (negative "
             "ducks it under the narration).",
     "params": {
         "db": {"type": "float", "min": -40.0, "max": 6.0,
                "default": -12.0}},
     "fn": _tool_set_background_volume},
    {"name": "set_background_mode",
     "desc": "Choose whether the background bed is universal (under "
             "the whole deck) or gap-fill.",
     "params": {
         "universal": {"type": "bool", "default": False}},
     "fn": _tool_set_background_mode},
    {"name": "set_background_finish_loop",
     "desc": "Whether the background's final loop finishes past the "
             "last slide.",
     "params": {
         "enabled": {"type": "bool", "default": False}},
     "fn": _tool_set_background_finish_loop},
    {"name": "set_compression",
     "desc": "Set the export target size in MB (0 = default quality).",
     "params": {
         "mb": {"type": "float", "min": 0.0, "max": 100000.0,
                "default": 0.0}},
     "fn": _tool_set_compression},
    {"name": "remove_slide",
     "desc": "Remove a single slide from the deck by its number.",
     "params": {
         "slide": {"type": "int", "min": 1, "default": 1}},
     "fn": _tool_remove_slide},
    {"name": "remove_group",
     "desc": "Remove a group AND all of its slides from the deck.",
     "params": {
         "group": {"type": "int", "min": 1, "default": 1}},
     "fn": _tool_remove_group},
    {"name": "list_slides",
     "desc": "List the current slides and groups (read-only).",
     "params": {}, "fn": _tool_list_slides},
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------------
# Prompt + parsing + execution
# ---------------------------------------------------------------------
def deck_state_summary(deck: SlideDeckProject) -> str:
    """Compact, model-friendly snapshot of the deck: numbered slides
    and groups the tools reference by index."""
    lines: List[str] = []
    lines.append(f"Deck '{deck.name or 'Untitled'}' — "
                 f"{len(deck.pages)} slide(s), "
                 f"{len(deck.groups)} group(s).")
    if deck.pages:
        from src.video_studio.slide_deck import ordered_pages
        lines.append("Slides (in deck order):")
        for i, p in enumerate(ordered_pages(deck), start=1):
            kind = ("CARD" if getattr(p, "card", None)
                    else "image")
            ov = " +text" if getattr(p, "text_overlay", None) else ""
            lines.append(
                f"  #{i} [{kind}{ov}] '{p.label or ''}' "
                f"{p.duration_seconds:.1f}s")
    if deck.groups:
        lines.append("Groups:")
        for i, g in enumerate(deck.groups, start=1):
            lines.append(
                f"  #{i} '{g.name or ''}' "
                f"transition={g.inter_group_transition_in} "
                f"black_gap={getattr(g, 'pre_black_seconds', 0.0):.1f}s")
    bg = getattr(deck, "background_group", None)
    has_bg = bool(bg and (getattr(bg, "audio_clips", None) or []))
    lines.append(
        f"Background bed: {'set' if has_bg else 'none'}, "
        f"level={getattr(deck, 'background_gain_db', -12.0):.0f}dB, "
        f"{'universal' if getattr(deck, 'background_is_universal', False) else 'gap-fill'}.")
    lines.append(
        f"Export target: "
        + (f"{deck.export_target_size_mb:.0f} MB"
           if getattr(deck, 'export_target_size_mb', 0.0) > 0
           else "default quality"))
    return "\n".join(lines)


def _tool_signature(tool: Dict[str, Any]) -> str:
    parts = []
    for name, spec in tool["params"].items():
        t = spec["type"]
        if t == "enum":
            hint = "|".join(spec["choices"][:6]) + (
                "…" if len(spec["choices"]) > 6 else "")
        elif t in ("int", "float"):
            hint = f"{t}"
            if "min" in spec or "max" in spec:
                hint += f"[{spec.get('min','')}..{spec.get('max','')}]"
        else:
            hint = t
        parts.append(f"{name}:{hint}")
    return ", ".join(parts) if parts else "(no args)"


def build_agent_system_prompt(deck: SlideDeckProject) -> str:
    """System prompt that teaches a small model the tools + the strict
    JSON action format, and gives it the current deck state."""
    lines: List[str] = [
        "You are a slide-deck editing assistant inside a video-book / "
        "audiobook tool. You help the user CREATE and EDIT slides by "
        "emitting tool calls.",
        "",
        "Respond with a short sentence for the user, then a JSON array "
        "of the actions to apply, wrapped in a ```json fenced block. "
        "Use ONLY these tools and argument names. Omit any argument to "
        "accept its default. Colors are #RRGGBB hex. Slide/group "
        "numbers are 1-based (see the deck state).",
        "",
        "TOOLS:",
    ]
    for t in TOOLS:
        lines.append(f"- {t['name']}({_tool_signature(t)}) — {t['desc']}")
    lines += [
        "",
        "Example:",
        'Sure — adding a title card and captioning slide 2.',
        "```json",
        '[{"tool":"add_title_card","args":{"title":"The Chase",'
        '"subtitle":"Chapter One","bg_color":"#101830"}},'
        '{"tool":"set_slide_text","args":{"slide":2,'
        '"title":"The alley","position":"bottom","box":true}}]',
        "```",
        "",
        "If the user only asks a question, answer WITHOUT a JSON block.",
        "",
        "CURRENT DECK STATE:",
        deck_state_summary(deck),
    ]
    return "\n".join(lines)


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Extract a list of ``{"tool":..., "args":{...}}`` from a model
    reply. Tolerates fenced ```json blocks, a bare JSON array, or loose
    ``{...}`` objects. Returns [] when there are no actions."""
    if not text:
        return []
    candidates: List[str] = []
    # 1) fenced ```json ... ``` (or plain ``` ... ```)
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", text,
                         re.DOTALL | re.IGNORECASE):
        candidates.append(m.group(1).strip())
    # 2) the whole text (in case the model returned raw JSON)
    candidates.append(text.strip())
    for cand in candidates:
        arr = _try_load_actions(cand)
        if arr:
            return arr
    # 3) last resort — collect individual {...} objects that look like
    # tool calls.
    objs: List[Dict[str, Any]] = []
    for m in re.finditer(r"\{[^{}]*\"tool\"[^{}]*\}", text, re.DOTALL):
        try:
            o = json.loads(m.group(0))
            if isinstance(o, dict) and "tool" in o:
                objs.append(o)
        except Exception:
            pass
    return objs


def _try_load_actions(s: str) -> List[Dict[str, Any]]:
    if not s:
        return []
    # Trim to the outermost [...] if present.
    lb, rb = s.find("["), s.rfind("]")
    if lb != -1 and rb != -1 and rb > lb:
        s = s[lb:rb + 1]
    try:
        data = json.loads(s)
    except Exception:
        return []
    if isinstance(data, dict) and "tool" in data:
        return [data]
    if isinstance(data, list):
        return [o for o in data
                if isinstance(o, dict) and "tool" in o]
    return []


def _remap_index(
    args: Dict[str, Any], key: str,
    snap_ids: List[str], live_ids: List[str],
) -> None:
    """Re-map a 1-based ``args[key]`` from the START-of-turn order
    (``snap_ids``) to the item's CURRENT position (``live_ids``), so
    prior add/remove calls in the same turn don't shift what a later
    index refers to. A target that was deleted maps to an
    out-of-range index (the tool then reports 'no such #')."""
    if key not in args or args[key] is None:
        return
    try:
        oi = int(args[key]) - 1
    except (TypeError, ValueError):
        return
    if not (0 <= oi < len(snap_ids)):
        return
    target_id = snap_ids[oi]
    try:
        ci = live_ids.index(target_id)
        args[key] = ci + 1
    except ValueError:
        args[key] = len(live_ids) + 1  # deleted → out of range


def execute_tool_calls(
    deck: SlideDeckProject, calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate + run each call on ``deck``. Returns a result record
    per call: ``{tool, ok, message}``. Unknown tools are reported, not
    executed."""
    from src.video_studio.slide_deck import ordered_pages
    # Snapshot the slide / group order at the START of the turn.
    # A model plans a whole batch against the state it was shown, but
    # an earlier add/remove call shifts the numbers a later call
    # references. Re-map each index to the target's CURRENT position
    # so "slide 2 / group 3" mean what the model intended.
    snap_pages = [p.id for p in ordered_pages(deck)]
    snap_groups = [g.id for g in deck.groups]
    results: List[Dict[str, Any]] = []
    for call in calls:
        name = str(call.get("tool", "")).strip()
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            results.append({
                "tool": name, "ok": False,
                "message": f"Unknown tool '{name}'."})
            continue
        args = _clean_args(tool, call.get("args") or {})
        _remap_index(args, "slide", snap_pages,
                     [p.id for p in ordered_pages(deck)])
        _remap_index(args, "group", snap_groups,
                     [g.id for g in deck.groups])
        try:
            msg = tool["fn"](deck, args)
            results.append({"tool": name, "ok": True, "message": msg})
        except Exception as exc:
            results.append({
                "tool": name, "ok": False,
                "message": f"{name} failed: {exc}"})
    return results


def run_agent_turn(
    deck: SlideDeckProject, model_output: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """Parse ``model_output`` for tool calls and apply them to ``deck``.
    Returns ``(results, summary)`` — ``summary`` is a bullet list of
    what changed (empty when the model made no tool calls)."""
    calls = parse_tool_calls(model_output)
    if not calls:
        return [], ""
    results = execute_tool_calls(deck, calls)
    applied = [r for r in results if r["ok"]]
    summary_lines = [
        ("✅ " if r["ok"] else "⚠️ ") + r["message"] for r in results]
    return results, "\n".join(summary_lines)
