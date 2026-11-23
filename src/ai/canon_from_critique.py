"""New world elements and characters found by the Critique, as records.

The Critique's Worldbuilding report lists "New elements (not in
worldbuilding)" and its Characters report lists "Speakers with no character
record". This module turns one of those lines into a draft record:

* ``parse_item`` reads the name, a likely kind, a description and an
  example from the report's line;
* ``passages`` finds where the name appears in the manuscript;
* ``build_prompt`` / ``parse_reply`` let a model draft the fields from those
  passages (the writer edits everything before it is saved);
* ``FIELDS`` lists the fields shown for each kind. The keys are the ones the
  app's existing creators read (``MainWindow._create_*_from_json``);
  ``EXTRA_FIELDS`` are model fields those creators don't set, applied
  afterwards by ``apply_extras`` only where the record is still empty.

No Qt; nothing here saves anything.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# kind → (label, project list holding it)
WORLD_KINDS: Dict[str, Tuple[str, str]] = {
    "place": ("Place", "places"),
    "faction": ("Faction", "factions"),
    "culture": ("Culture", "cultures"),
    "technology": ("Technology", "technologies"),
    "myth": ("Myth", "myths"),
    "historical_event": ("Historical event", "historical_events"),
    "flora": ("Plant", "flora"),
    "fauna": ("Creature", "fauna"),
}
CHARACTER_ROLES = ("minor", "major", "protagonist", "antagonist")

# (key, label, multi-line)
FIELDS: Dict[str, List[Tuple[str, str, bool]]] = {
    "place": [("description", "Description", True),
              ("significance", "Importance to the story", True), ("notes", "Notes", True)],
    "faction": [("description", "Description", True), ("ideology", "What they believe", True),
                ("leadership", "Who leads them", False), ("notes", "Notes", True)],
    "culture": [("description", "Description", True), ("values", "Values", True),
                ("customs", "Customs", True), ("notes", "Notes", True)],
    "technology": [("description", "Description", True),
                   ("applications", "What it's used for", True),
                   ("limitations", "Limits", True),
                   ("story_relevance", "Importance to the story", True)],
    "myth": [("description", "Description", True), ("moral_lesson", "What it teaches", True),
             ("full_text", "The tale", True)],
    "historical_event": [("date", "When", False), ("description", "Description", True),
                         ("consequences", "Consequences", True)],
    "flora": [("description", "Description", True), ("habitat", "Where it grows", False),
              ("cultural_significance", "What it means to people", True)],
    "fauna": [("description", "Description", True), ("habitat", "Where it lives", False),
              ("behavior", "Behaviour", True),
              ("cultural_significance", "What it means to people", True)],
    "character": [("personality", "Personality", True),
                  ("speaking_style", "How they speak", True),
                  ("physical_description", "Appearance", True),
                  ("motivations", "What drives them", True),
                  ("backstory", "Backstory", True), ("notes", "Notes", True)],
}
# Fields the app's creators don't set; filled in afterwards (if empty).
EXTRA_FIELDS = {"character": ("speaking_style", "motivations"),
                "place": (), "faction": (), "culture": (), "technology": (), "myth": (),
                "historical_event": (), "flora": (), "fauna": ()}

_KIND_WORDS = {
    "place": ("place", "location", "city", "town", "village", "region", "building", "land",
              "street", "district", "landmark", "realm", "planet", "harbor", "harbour"),
    "faction": ("faction", "organization", "organisation", "guild", "order", "group", "house",
                "clan", "army", "company", "government", "party", "church"),
    "culture": ("culture", "people", "nation", "tradition", "religion", "custom", "language"),
    "technology": ("technology", "device", "machine", "weapon", "tool", "ship", "vehicle",
                   "artifact", "artefact", "item", "object"),
    "myth": ("myth", "legend", "story", "prophecy", "god", "deity"),
    "historical_event": ("event", "war", "battle", "history", "historical", "treaty"),
    "flora": ("plant", "flora", "tree", "flower", "herb"),
    "fauna": ("creature", "animal", "fauna", "beast", "species", "monster"),
}


def kind_from_word(word: str) -> str:
    w = (word or "").strip().lower()
    for kind, words in _KIND_WORDS.items():
        if any(w == x or w.startswith(x) for x in words):
            return kind
    return ""


def parse_item(text: str) -> Dict[str, str]:
    """{"name", "kind", "description", "example"} from a report line:
    "Thessaly Wharf — Place — Brine-soaked market …" (a model's list) or
    "Vethari (5×) — e.g. "…"" (the scan's list)."""
    parts = [p.strip() for p in re.split(r"\s+[—–]\s+|\s+\|\s+", text or "") if p.strip()]
    name = parts[0] if parts else (text or "").strip()
    name = re.sub(r"\s*\(\d+×\)\s*$", "", name).strip().strip('"“”')
    out = {"name": name, "kind": "", "description": "", "example": ""}
    for p in parts[1:]:
        m = re.match(r'e\.g\.\s*["“](.*)["”]\s*$', p)
        if m:
            out["example"] = m.group(1)
        elif not out["kind"] and kind_from_word(p):
            out["kind"] = kind_from_word(p)
        elif not out["description"]:
            out["description"] = p
    return out


def passages(project: Any, name: str, limit: int = 6, reach: int = 400) -> List[str]:
    """Paragraphs that mention ``name``, across every manuscript, trimmed
    around the name."""
    if not name or project is None:
        return []
    rx = re.compile(r"(?<![\w'’])" + re.escape(name) + r"(?![\w'’])")
    out: List[str] = []
    try:
        chapters = [ch for _scope, ch in project.all_chapters()]
    except Exception:
        chapters = list(getattr(getattr(project, "manuscript", None), "chapters", None) or [])
    for ch in chapters:
        for para in re.split(r"\n\s*\n|\n", getattr(ch, "content", "") or ""):
            m = rx.search(para)
            if not m:
                continue
            start = max(0, m.start() - reach // 2)
            snippet = para[start:start + reach].strip()
            out.append(("…" if start else "") + snippet
                       + ("…" if start + reach < len(para) else ""))
            if len(out) >= limit:
                return out
    return out


def known_names(project: Any, kind: str, limit: int = 30) -> List[str]:
    """Names already recorded, so a model doesn't contradict them."""
    try:
        if kind == "character":
            return [c.name for c in getattr(project, "characters", None) or []][:limit]
        from src.ai.canon_index import collect_world_entities
        return [e.label for e in collect_world_entities(getattr(project, "worldbuilding", None))
                ][:limit]
    except Exception:
        return []


SYSTEM_PROMPT = (
    "You help a novelist record an element of their own story in their notes. Use only "
    "what the passages show or clearly imply. Where the passages say nothing, leave the "
    "field empty rather than invent. Plain, specific prose; no headings.")


def build_prompt(kind: str, name: str, found: List[str], genre: str = "",
                 known: Optional[List[str]] = None, hint: str = "") -> str:
    fields = FIELDS.get(kind, [])
    if kind == "character":
        what = "a character"
        first = f"ROLE: one of {', '.join(CHARACTER_ROLES)}"
    else:
        what = "an element of the story's world"
        first = "KIND: one of " + ", ".join(label for label, _ in WORLD_KINDS.values())
    lines = [f"Record {what}: {name}."]
    if genre:
        lines.append(f"Genre: {genre}.")
    if hint:
        lines.append(f"The editor's note: {hint}")
    if known:
        lines.append("Already recorded (don't contradict): " + "; ".join(known))
    lines.append("\nPASSAGES WHERE IT APPEARS:\n" + ("\n\n".join(f"- {p}" for p in found)
                                                    or "- (none found)"))
    lines.append("\nAnswer with exactly these lines, each on one line, nothing else:")
    lines.append(first)
    for key, label, _multi in fields:
        lines.append(f"{key.upper()}: <{label.lower()}>")
    return "\n".join(lines)


def parse_reply(kind: str, reply: str) -> Dict[str, str]:
    """{field key: text} from the model's lines; "kind" or
    "character_type" when it named one. For a world element, any world
    field is read: the model may decide it is another kind."""
    kinds = list(WORLD_KINDS) if kind in WORLD_KINDS else [kind]
    keys = {k.upper(): k for kd in kinds for k, _l, _m in FIELDS.get(kd, [])}
    keys.update({"KIND": "kind", "ROLE": "character_type"})
    out: Dict[str, str] = {}
    current = None
    for raw in (reply or "").splitlines():
        line = raw.strip()
        m = re.match(r"^[-•*_\s]*([A-Z_ ]+?)[*_\s]*:[*_\s]*(.*)$", line)
        if m and m.group(1).strip().replace(" ", "_") in keys:
            current = keys[m.group(1).strip().replace(" ", "_")]
            out[current] = m.group(2).strip().strip("*_").strip()
        elif current and line and current not in ("kind", "character_type"):
            out[current] = (out[current] + " " + line).strip()
    for k, v in list(out.items()):
        if v.strip().lower() in ("", "none", "n/a", "unknown", "-", "(none)", "empty"):
            out.pop(k)
        elif v.startswith("<") and v.endswith(">"):
            out.pop(k)                      # the model echoed the placeholder
    if "kind" in out:
        out["kind"] = kind_from_word(out["kind"]) or ""
        if not out["kind"]:
            out.pop("kind")
    if "character_type" in out:
        role = out["character_type"].lower().split()[0] if out["character_type"].split() else ""
        if role in CHARACTER_ROLES:
            out["character_type"] = role
        else:
            out.pop("character_type")
    return out


def find_record(project: Any, kind: str, name: str):
    """The record called ``name`` (case-insensitive), or None."""
    items = (getattr(project, "characters", None) if kind == "character"
             else getattr(getattr(project, "worldbuilding", None),
                          WORLD_KINDS.get(kind, ("", ""))[1], None)) or []
    low = (name or "").strip().lower()
    return next((x for x in items if (getattr(x, "name", "") or "").strip().lower() == low),
                None)


def apply_extras(record: Any, kind: str, data: Dict[str, str]) -> List[str]:
    """Set the fields the creators don't, where the record is still empty."""
    done = []
    for key in EXTRA_FIELDS.get(kind, ()):
        value = (data.get(key) or "").strip()
        if value and hasattr(record, key) and not (getattr(record, key, "") or "").strip():
            setattr(record, key, value)
            done.append(key)
    return done


# ── Connecting a term to something already in the World ────────────────

# How a new term relates to the element it is connected to.
RELATIONS: Dict[str, str] = {
    "alias": "Another name for",
    "part": "Part of",
    "belongs": "Belongs to or is used by",
    "related": "Related to",
}
TERM_CATEGORY = "Term"


def world_targets(project: Any) -> List[Dict[str, str]]:
    """Everything a term can be connected to: the World's elements and its
    Encyclopedia terms, as {"name", "category", "summary"}."""
    try:
        from src.ai.canon_index import collect_world_entities
        entities = collect_world_entities(getattr(project, "worldbuilding", None))
    except Exception:
        entities = []
    return [{"name": e.name, "category": e.category, "summary": e.summary} for e in entities]


def _tokens(text: str) -> set:
    stop = {"the", "of", "a", "an", "and", "in", "on", "at", "to"}
    return {t for t in re.findall(r"[a-z0-9'’]+", (text or "").lower()) if t not in stop
            and len(t) > 2}


def rank_targets(project: Any, term: str, found: List[str],
                 targets: Optional[List[Dict[str, str]]] = None) -> List[Tuple[float, Dict[str, str]]]:
    """Targets most likely meant by ``term``, best first: names that share a
    word with the term, then names that appear near it in the passages.
    No model needed."""
    from difflib import SequenceMatcher
    targets = world_targets(project) if targets is None else targets
    term_l = (term or "").lower()
    words = _tokens(term)
    text = "\n".join(found or []).lower()
    ranked = []
    for t in targets:
        name = t["name"]
        if name.lower() == term_l:
            continue
        score = 0.0
        shared = words & _tokens(name)
        score += 3.0 * len(shared)
        if name.lower() in term_l or (term_l and term_l in name.lower()):
            score += 3.0
        if text:
            score += min(text.count(name.lower()), 5) * 1.0
        score += SequenceMatcher(None, term_l, name.lower()).ratio()
        ranked.append((round(score, 2), t))
    ranked.sort(key=lambda x: (-x[0], x[1]["name"].lower()))
    return ranked


def term_entry(term: str, target: Dict[str, str], relation: str, definition: str = "",
               notes: str = "") -> Dict[str, str]:
    """An Encyclopedia entry for ``term``, connected to ``target``. Every
    value is text, as the project file stores the Encyclopedia."""
    phrase = RELATIONS.get(relation, RELATIONS["related"])
    link = f"{phrase} {target['name']} ({target.get('category', '')})."
    entry = {"title": term.strip(), "category": TERM_CATEGORY,
             "summary": (link + (" " + definition.strip() if definition.strip() else "")).strip(),
             "description": (definition or "").strip(),
             "refers_to": target["name"], "refers_to_category": target.get("category", ""),
             "relation": relation if relation in RELATIONS else "related",
             "is_custom": "true"}
    if notes.strip():
        entry["writing_tips"] = notes.strip()
    return entry


def add_term(project: Any, entry: Dict[str, str]) -> str:
    """Put a term in the World's Encyclopedia. A term already there under
    the same title keeps what it has; only its empty fields are filled.
    Returns "added", "updated" or "" (nothing to do)."""
    wb = getattr(project, "worldbuilding", None)
    if wb is None or not entry.get("title"):
        return ""
    entries = wb.custom_encyclopedia
    low = entry["title"].strip().lower()
    for existing in entries:
        if isinstance(existing, dict) and (existing.get("title") or existing.get("name") or ""
                                           ).strip().lower() == low:
            changed = False
            for k, v in entry.items():
                if v and not str(existing.get(k, "") or "").strip():
                    existing[k] = v
                    changed = True
            return "updated" if changed else ""
    entries.append(dict(entry))
    return "added"


def build_connect_prompt(term: str, found: List[str],
                         candidates: List[Dict[str, str]]) -> str:
    lines = [f"A novel uses the term “{term}”. Decide which recorded element of the story's "
             "world it refers to, and how.",
             "\nPASSAGES WHERE IT APPEARS:\n" + ("\n\n".join(f"- {p}" for p in found)
                                                 or "- (none found)"),
             "\nRECORDED ELEMENTS:"]
    lines += [f"- {c['name']} ({c['category']}): {c.get('summary', '')[:160]}" for c in candidates]
    lines.append("\nAnswer with exactly these lines, nothing else:")
    lines.append("TARGET: <the element's name exactly as listed, or NONE>")
    lines.append("RELATION: one of alias, part, belongs, related "
                 "(alias = another name for it; part = a part of it; belongs = belongs to or "
                 "is used by it)")
    lines.append("DEFINITION: <one or two sentences on what the term is, from the passages>")
    return "\n".join(lines)


def parse_connect_reply(reply: str, candidates: List[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    names = {c["name"].lower(): c["name"] for c in candidates}
    for raw in (reply or "").splitlines():
        m = re.match(r"^[-•*_\s]*(TARGET|RELATION|DEFINITION)[*_\s]*:[*_\s]*(.*)$", raw.strip(),
                     re.IGNORECASE)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip().strip("*_\"“”").strip()
        if key == "target":
            if value.lower() in names:
                out["target"] = names[value.lower()]
        elif key == "relation":
            word = value.lower().split()[0] if value.split() else ""
            if word in RELATIONS:
                out["relation"] = word
        elif value and not (value.startswith("<") and value.endswith(">")):
            out["definition"] = value
    return out


# ── Another name for a character ───────────────────────────────────────

def character_targets(project: Any) -> List[Dict[str, str]]:
    """The project's characters, as targets for a nickname."""
    out = []
    for c in getattr(project, "characters", None) or []:
        summary = (getattr(c, "personality", "") or getattr(c, "notes", "") or "")[:160]
        out.append({"name": c.name, "category": (c.character_type or "character").title(),
                    "summary": summary})
    return out


def add_nickname(project: Any, character_name: str, nickname: str) -> str:
    """Record ``nickname`` as another name for the character, on an
    "Also called:" line in its notes (visible and editable on the Characters
    tab). Returns "added", "" when it was already there, or "missing"."""
    from src.ai.canon_index import character_aliases
    character = find_record(project, "character", character_name)
    nickname = (nickname or "").strip()
    if character is None or not nickname:
        return "missing"
    if nickname.lower() in (a.lower() for a in character_aliases(character)) \
            or nickname.lower() == character.name.lower():
        return ""
    notes = character.notes or ""
    m = re.search(r"^(\s*also called\s*:\s*)(.+)$", notes, re.IGNORECASE | re.MULTILINE)
    if m:
        line = m.group(0).rstrip().rstrip(".") + f", {nickname}"
        character.notes = notes[:m.start()] + line + notes[m.end():]
    else:
        character.notes = (notes.rstrip() + "\n\n" if notes.strip() else "") + \
            f"Also called: {nickname}"
    return "added"
