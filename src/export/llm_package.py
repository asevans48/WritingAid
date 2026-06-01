"""LLM round-trip export/import for project elements.

Bundles characters, worldbuilding, plot, and chapter *planning* as
per-entity JSON files in a directory tree. Designed so an external
LLM (Claude.ai, ChatGPT) can read the files in a side conversation,
suggest edits or new entities, and the result imports cleanly back
into the project — without ever touching the user's chapter prose.

Workflow:
    exporter = LLMPackageExporter(project)
    exporter.export(Path("/tmp/my_book_pkg"))

    plan = LLMPackageImporter(Path("/tmp/my_book_pkg")).build_plan(project)
    if plan.is_applyable:
        result = apply_import_plan(project, plan)

Hard invariants enforced by apply_import_plan:
  * Chapter ``content`` / ``html_content`` / ``revisions`` are NEVER
    written. The importer reads chapter planning, title, and number
    only, even if a user (or LLM) puts a ``content`` field in the
    JSON.
  * Entities present in the project but missing from the import are
    left untouched. The import is *additive* — no implicit deletes.
  * Unknown / unparseable entities surface as errors before apply;
    apply refuses to run when the plan has errors.
"""

from __future__ import annotations

import json
import re
import typing
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, ValidationError


class ImportMode(str, Enum):
    """Controls whether the importer deletes entities missing from
    the package.

    UPDATE (default, safe): additive for most entity types. Existing
    entities not present in the package are kept. The package is
    treated as a patch.

    OVERWRITE: the package is treated as canonical for non-chapter
    entity types. Anything not in the package is deleted. **Chapter
    prose is never affected** — the chapter list is never reduced,
    and existing chapter content / revisions / annotations are never
    touched regardless of mode. Overwrite only applies to character,
    worldbuilding, and plot lists.

    **Exception — plot events are always canonical when present.**
    The main manuscript plot (``FreytagPyramid.events``) represents
    a coherent arc; partial updates would scramble the structure.
    If a package contains ANY ``plot/events/*.json`` files, the
    importer treats them as the full plot — events in the project
    but missing from the package are dropped — in both UPDATE and
    OVERWRITE modes. If the package contains NO plot files, the
    project's plot is left untouched. Subplots stay additive.
    """
    UPDATE = "update"
    OVERWRITE = "overwrite"


# Entity types that are treated as canonical *whenever any file of
# that type is present in the package*, regardless of the import
# mode. The plot arc is the load-bearing example: a half-replaced
# plot is worse than no replacement at all because it scrambles the
# structural coherence the LLM was reasoning about.
_CANONICAL_KINDS_WHEN_PRESENT = frozenset({"plot_event"})

from src.models.project import (
    Character, ChapterPlanning, CharacterTension, PlotEvent,
    StoryPromise, Subplot, Theme, WriterProject,
)
from src.models.worldbuilding_objects import (
    Army, Culture, Economy, Fauna, Flora, Faction, HistoricalEvent,
    MagicSystem, Myth, Place, PoliticalSystem, StarSystem, Technology,
)


SCHEMA_VERSION = 1


# Mapping from entity type label (used in JSON ``type`` field + directory
# layout) to the Pydantic model that validates and serializes it. The
# label is also the directory name the entity lives in.
_ENTITY_MODELS: Dict[str, type] = {
    "character":         Character,
    "faction":           Faction,
    "place":             Place,
    "culture":           Culture,
    "technology":        Technology,
    "historical_event":  HistoricalEvent,
    "flora":             Flora,
    "fauna":             Fauna,
    "myth":              Myth,
    "magic_system":      MagicSystem,
    "star_system":       StarSystem,
    "army":              Army,
    "economy":           Economy,
    "political_system":  PoliticalSystem,
    "subplot":           Subplot,
    "plot_event":        PlotEvent,
    "story_promise":     StoryPromise,
    "character_tension": CharacterTension,
    "theme":             Theme,
}

# Where on the WriterProject each entity type lives. Tuple of
# (containing_attr_path, list_attr) where the path is dotted from
# project root. ``character`` lives at project.characters; everything
# in worldbuilding is at project.worldbuilding.<list>; plot pieces are
# at project.story_planning.<list> (with freytag_pyramid.events as a
# nested special case).
_ENTITY_LOCATIONS: Dict[str, Tuple[str, ...]] = {
    "character":         ("characters",),
    "faction":           ("worldbuilding", "factions"),
    "place":             ("worldbuilding", "places"),
    "culture":           ("worldbuilding", "cultures"),
    "technology":        ("worldbuilding", "technologies"),
    "historical_event":  ("worldbuilding", "historical_events"),
    "flora":             ("worldbuilding", "flora"),
    "fauna":             ("worldbuilding", "fauna"),
    "myth":              ("worldbuilding", "myths"),
    "magic_system":      ("worldbuilding", "magic_systems"),
    "star_system":       ("worldbuilding", "star_systems"),
    "army":              ("worldbuilding", "armies"),
    "economy":           ("worldbuilding", "economies"),
    "political_system":  ("worldbuilding", "political_systems"),
    "subplot":           ("story_planning", "subplots"),
    "plot_event":        ("story_planning", "freytag_pyramid", "events"),
    "story_promise":     ("story_planning", "promises"),
    "character_tension": ("story_planning", "tensions"),
    "theme":             ("story_planning", "theme_details"),
}

# Subdirectory under the package root for each entity type. Grouping
# worldbuilding/plot under shared parents keeps the file tree readable
# when an LLM scans it.
_ENTITY_DIRS: Dict[str, str] = {
    "character":         "characters",
    "faction":           "worldbuilding/factions",
    "place":             "worldbuilding/places",
    "culture":           "worldbuilding/cultures",
    "technology":        "worldbuilding/technologies",
    "historical_event":  "worldbuilding/historical_events",
    "flora":             "worldbuilding/flora",
    "fauna":             "worldbuilding/fauna",
    "myth":              "worldbuilding/myths",
    "magic_system":      "worldbuilding/magic_systems",
    "star_system":       "worldbuilding/star_systems",
    "army":              "worldbuilding/armies",
    "economy":           "worldbuilding/economies",
    "political_system":  "worldbuilding/political_systems",
    "subplot":           "plot/subplots",
    "plot_event":        "plot/events",
    "story_promise":     "plot/promises",
    "character_tension": "plot/tensions",
    "theme":             "plot/themes",
}

# Chapter export is a special case — we strip Chapter down to a
# safe-to-edit subset that excludes the prose body.
_CHAPTER_EXPORT_FIELDS = ("id", "number", "title")
# Chapter import is constrained to these fields. Even if the JSON
# contains other keys (content, revisions, etc.), they're ignored.
_CHAPTER_IMPORT_ALLOWED_FIELDS = {"id", "number", "title", "planning"}


def _slugify(text: str, fallback: str = "item") -> str:
    """Turn a name into a filesystem-safe slug (lowercase, hyphen-
    separated, ASCII-only). Used for filenames — never for IDs."""
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or fallback


# A reference longer than this — or with a sentence break, or with
# more than this many words — is almost certainly prose that landed
# in a reference list by mistake (descriptive text in ``key_figures``
# or ``allies``), not a real entity reference. We silently filter
# these out of the integrity check and just count them per file so
# the user/LLM sees one actionable hint instead of N noise lines.
_REF_PROSE_CHAR_LIMIT = 80
_REF_PROSE_WORD_LIMIT = 10
_REF_PROSE_SENTENCE_RE = re.compile(r"\.\s+[A-Z]")
# Strip parenthetical qualifiers from a reference so
# ``"Jade (militant action)"`` resolves against an entity named
# ``"Jade"``. Common LLM output pattern that produced ~10% of the
# noise in real reports.
_REF_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def _is_ref_prose_shape(s: str) -> bool:
    """True for strings that are clearly free-text descriptions, not
    entity references — too long, multi-sentence, or many-word."""
    if len(s) > _REF_PROSE_CHAR_LIMIT:
        return True
    if len(s.split()) > _REF_PROSE_WORD_LIMIT:
        return True
    if _REF_PROSE_SENTENCE_RE.search(s):
        return True
    return False


def _strip_ref_parenthetical(s: str) -> str:
    """Return ``s`` with any ``(...)`` qualifier removed and
    surrounding whitespace trimmed."""
    return _REF_PAREN_RE.sub("", s).strip()


def _is_os_metadata(path: Path, source_root: Path) -> bool:
    """True for OS-generated noise files the importer must skip.

    Catches several real failure modes we saw in production:
      * ``.DS_Store`` — macOS Finder metadata in every folder.
      * ``._<name>.json`` — macOS AppleDouble resource fork. These
        sneak through ``*.json`` globs because the suffix matches,
        but their bytes are a binary header (``\\x00\\x05\\x16\\x07``)
        that produces a confusing "Invalid JSON" error.
      * ``__MACOSX/`` — directory of resource-fork sidecars produced
        when unzipping a macOS-created zip on another platform.
      * Generic dot-files (``.gitignore``, editor scratch) — never
        the user's content, always safe to skip silently.

    Silent skip (not a warning): these files are universally
    understood as noise; reporting them every import would teach the
    user to ignore the warnings, which is the opposite of what we
    want.
    """
    if path.name.startswith("."):
        return True
    try:
        rel = path.relative_to(source_root)
    except ValueError:
        return False
    for part in rel.parts:
        if part == "__MACOSX":
            return True
    return False


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------
class LLMPackageExporter:
    """Walks a WriterProject and writes a per-entity JSON tree."""

    def __init__(self, project: WriterProject):
        self.project = project

    def export(self, dest_dir: Path) -> Path:
        """Write the full package to ``dest_dir``.

        Creates the directory (and intermediate ones) if missing.
        Overwrites any existing files inside — designed to be re-run
        after the LLM edits the package, with the user's changes
        landing on top of the previous snapshot.

        Always writes ``INSTRUCTIONS_FOR_LLM.md`` and ``SCHEMA.md``
        even for empty projects, so a brand-new export is a
        self-sufficient prompt package for project creation.

        Returns the resolved absolute path so callers can hand it to
        the user as the next step.
        """
        dest = Path(dest_dir).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        self._write_manifest(dest)
        self._write_readme(dest)
        self._write_instructions(dest)
        self._write_schema(dest)
        self._write_characters(dest)
        self._write_worldbuilding(dest)
        self._write_plot(dest)
        self._write_chapters(dest)
        return dest

    def _write_instructions(self, dest: Path) -> None:
        """Write the LLM-facing INSTRUCTIONS doc. Covers both
        workflows: editing an existing project AND creating a new
        project from scratch."""
        (dest / "INSTRUCTIONS_FOR_LLM.md").write_text(
            _render_instructions_doc())

    def _write_schema(self, dest: Path) -> None:
        """Write the auto-generated SCHEMA reference for every
        importable entity type, with one example JSON per type."""
        (dest / "SCHEMA.md").write_text(_render_schema_doc())

    def _write_manifest(self, dest: Path) -> None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "exported_by": "WritingAid",
            "project_name": self.project.name,
            "project_description": self.project.description or "",
            "instructions_for_llm": (
                "This package contains story entities you can edit. "
                "Each .json file is one entity (a character, faction, "
                "plot event, etc.). To MODIFY an entity, keep its "
                "'id' field unchanged. To ADD a new entity, create a "
                "new file in the appropriate directory and omit the "
                "'id' field (a new id will be assigned on import). "
                "Chapter content (prose) is NOT included and CANNOT "
                "be edited via this package — only chapter planning "
                "(outline, scene_list, themes, etc.). Cross-references "
                "(e.g., a faction's allies list) should use entity "
                "ids when available; names are accepted as a fallback. "
                "Do not edit this manifest file."),
        }
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False))

    def _write_readme(self, dest: Path) -> None:
        readme = (
            "# WritingAid LLM-edit package\n\n"
            f"Exported {datetime.now().isoformat(timespec='seconds')} "
            f"from project: {self.project.name}\n\n"
            "## Quick start\n\n"
            "1. Upload this folder (or zip it first) to your LLM of "
            "choice — Claude.ai, ChatGPT, etc.\n"
            "2. Tell the LLM: *\"Read INSTRUCTIONS_FOR_LLM.md and "
            "SCHEMA.md, then help me [add characters / refine my "
            "plot / build out worldbuilding].\"*\n"
            "3. The LLM should return modified `.json` files. Save "
            "them back into this folder (replacing or adding files).\n"
            "4. Import the folder back into WritingAid. Choose "
            "**Update mode** (additive, keeps anything the LLM "
            "didn't touch) or **Overwrite mode** (replace the LLM-"
            "managed element set wholesale).\n\n"
            "## Read these next\n\n"
            "* `INSTRUCTIONS_FOR_LLM.md` — full workflow for the LLM, "
            "including how to **start a project from scratch**.\n"
            "* `SCHEMA.md` — every entity type's fields, with a JSON "
            "example each.\n\n"
            "## Safety guarantee\n\n"
            "Your chapter prose (`Chapter.content`) is **never** "
            "included in this package, and the importer **never** "
            "writes it — across both update and overwrite modes. "
            "Existing chapters that aren't in the package are kept "
            "unchanged. You can experiment freely.\n\n"
            "## What's in this package\n\n"
            "* `characters/` — one file per character.\n"
            "* `worldbuilding/` — factions, places, cultures, "
            "technologies, historical events, flora, fauna, myths, "
            "magic systems, star systems, armies, economies, "
            "political systems.\n"
            "* `plot/` — subplots, plot events, promises, tensions, "
            "themes, main plot.\n"
            "* `chapters/` — chapter *planning* only (description, "
            "outline, scenes, POV, tone, themes). **No prose.**\n"
        )
        (dest / "README.md").write_text(readme)

    def _write_characters(self, dest: Path) -> None:
        out_dir = dest / _ENTITY_DIRS["character"]
        out_dir.mkdir(parents=True, exist_ok=True)
        for ch in self.project.characters:
            self._write_entity(out_dir, "character", ch)

    def _write_worldbuilding(self, dest: Path) -> None:
        wb = self.project.worldbuilding
        wb_map: List[Tuple[str, Any]] = [
            ("faction",          getattr(wb, "factions", []) or []),
            ("place",            getattr(wb, "places", []) or []),
            ("culture",          getattr(wb, "cultures", []) or []),
            ("technology",       getattr(wb, "technologies", []) or []),
            ("historical_event", getattr(wb, "historical_events", []) or []),
            ("flora",            getattr(wb, "flora", []) or []),
            ("fauna",            getattr(wb, "fauna", []) or []),
            ("myth",             getattr(wb, "myths", []) or []),
            ("magic_system",     getattr(wb, "magic_systems", []) or []),
            ("star_system",      getattr(wb, "star_systems", []) or []),
            ("army",             getattr(wb, "armies", []) or []),
            ("economy",          getattr(wb, "economies", []) or []),
            ("political_system", getattr(wb, "political_systems", []) or []),
        ]
        for kind, items in wb_map:
            if not items:
                continue
            d = dest / _ENTITY_DIRS[kind]
            d.mkdir(parents=True, exist_ok=True)
            for item in items:
                self._write_entity(d, kind, item)

    def _write_plot(self, dest: Path) -> None:
        sp = getattr(self.project, "story_planning", None)
        if sp is None:
            return
        plot_dir = dest / "plot"
        plot_dir.mkdir(parents=True, exist_ok=True)
        # Scalars and simple lists — bundle into a single file so the
        # LLM has one obvious place for the high-level plot data.
        main_block = {
            "type": "plot_main",
            "main_plot": getattr(sp, "main_plot", "") or "",
            "themes_simple": list(
                getattr(sp, "themes", []) or []),
        }
        (plot_dir / "main_plot.json").write_text(
            json.dumps(main_block, indent=2, ensure_ascii=False))

        # Per-entity files for the structured lists.
        plot_groups: List[Tuple[str, Any]] = [
            ("subplot",           getattr(sp, "subplots", []) or []),
            ("story_promise",     getattr(sp, "promises", []) or []),
            ("character_tension", getattr(sp, "tensions", []) or []),
            ("theme",             getattr(sp, "theme_details", []) or []),
        ]
        for kind, items in plot_groups:
            if not items:
                continue
            d = dest / _ENTITY_DIRS[kind]
            d.mkdir(parents=True, exist_ok=True)
            for item in items:
                self._write_entity(d, kind, item)

        # PlotEvent list lives inside FreytagPyramid.
        fp = getattr(sp, "freytag_pyramid", None)
        events = getattr(fp, "events", None) if fp else None
        if events:
            d = dest / _ENTITY_DIRS["plot_event"]
            d.mkdir(parents=True, exist_ok=True)
            for ev in events:
                self._write_entity(d, "plot_event", ev)

    def _write_chapters(self, dest: Path) -> None:
        manuscript = getattr(self.project, "manuscript", None)
        chapters = getattr(manuscript, "chapters", None) if manuscript else None
        if not chapters:
            return
        out_dir = dest / "chapters"
        out_dir.mkdir(parents=True, exist_ok=True)
        for ch in chapters:
            self._write_chapter(out_dir, ch)

    def _write_entity(self, dir_: Path, kind: str, obj: Any) -> None:
        try:
            payload = obj.model_dump(mode="json")
        except Exception:
            # Defensive: skip entities that can't serialize cleanly.
            # We'd rather export the rest than abort the whole package.
            return
        payload["type"] = kind
        ent_id = payload.get("id", "")
        name = payload.get("name") or payload.get("title") or ent_id or "item"
        slug = _slugify(str(name))
        file_id = ent_id or uuid4().hex[:8]
        filename = f"{_slugify(file_id)}-{slug}.json"
        (dir_ / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_chapter(self, dir_: Path, chapter: Any) -> None:
        try:
            full = chapter.model_dump(mode="json")
        except Exception:
            return
        slim = {k: full.get(k) for k in _CHAPTER_EXPORT_FIELDS}
        slim["type"] = "chapter_planning"
        # Always include planning, defaulting to empty so a downstream
        # LLM has a target to fill.
        planning = full.get("planning") or {}
        slim["planning"] = planning
        num = full.get("number", 0)
        title = full.get("title", "") or f"chapter_{num:03d}"
        filename = f"{int(num):03d}-{_slugify(title)}.json"
        (dir_ / filename).write_text(
            json.dumps(slim, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------
# Import: planning + validation
# ---------------------------------------------------------------------
@dataclass
class ImportEntry:
    """One pending change in an import plan."""
    entity_type: str
    action: str          # "add" | "update"
    entity_id: str
    file_path: str
    data: Dict[str, Any]


@dataclass
class ImportPlan:
    """Result of validating an export package against a project.

    ``errors`` are blocking — apply_import_plan refuses to run if any
    are present. ``warnings`` are advisory (dangling references,
    unknown fields, etc.).

    ``mode`` determines apply behavior. ``to_delete`` is only
    populated when mode == OVERWRITE: it lists ``(entity_type,
    entity_id)`` pairs that exist in the project but are absent from
    the package. **Chapter entries never appear in to_delete** — the
    chapter list is never reduced by an import.
    """
    entries: List[ImportEntry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)
    mode: ImportMode = ImportMode.UPDATE
    to_delete: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def is_applyable(self) -> bool:
        return not self.errors

    def summary(self) -> Dict[str, int]:
        """Counts useful for a pre-apply confirmation dialog."""
        adds = sum(1 for e in self.entries if e.action == "add")
        updates = sum(1 for e in self.entries if e.action == "update")
        by_type: Dict[str, int] = {}
        for e in self.entries:
            by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        deletes_by_type: Dict[str, int] = {}
        for kind, _ in self.to_delete:
            deletes_by_type[kind] = deletes_by_type.get(kind, 0) + 1
        return {
            "total": len(self.entries),
            "adds": adds,
            "updates": updates,
            "deletes": len(self.to_delete),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "by_type": by_type,
            "deletes_by_type": deletes_by_type,
            "mode": self.mode.value,
        }


class LLMPackageImporter:
    """Reads a package directory and builds an ``ImportPlan``.

    Construction is cheap; ``build_plan(project)`` does the actual
    parsing + validation work. The plan is read-only — call
    ``apply_import_plan(project, plan)`` to actually mutate.
    """

    def __init__(self, source_dir: Path):
        self.source_dir = Path(source_dir).expanduser().resolve()

    def build_plan(
        self,
        project: WriterProject,
        mode: ImportMode = ImportMode.UPDATE,
    ) -> ImportPlan:
        plan = ImportPlan(mode=mode)
        if not self.source_dir.exists() or not self.source_dir.is_dir():
            plan.errors.append(
                f"Source directory does not exist: {self.source_dir}")
            return plan

        # Parse manifest first so we can flag schema mismatches.
        manifest_path = self.source_dir / "manifest.json"
        if manifest_path.exists():
            try:
                plan.manifest = json.loads(
                    manifest_path.read_text())
                sv = plan.manifest.get("schema_version")
                if sv != SCHEMA_VERSION:
                    plan.warnings.append(
                        f"Schema version mismatch: package has {sv}, "
                        f"importer expects {SCHEMA_VERSION}. Proceeding "
                        f"with best-effort field mapping.")
            except Exception as e:
                plan.warnings.append(
                    f"Could not parse manifest.json: {e}. Proceeding "
                    f"without manifest metadata.")

        # Walk every .json file under each known directory. We use the
        # directory map (not the JSON ``type`` field) as the source of
        # truth for kind — that way a misfiled JSON is rejected with a
        # clear error.
        for kind, rel_dir in _ENTITY_DIRS.items():
            d = self.source_dir / rel_dir
            if not d.exists():
                continue
            for fp in sorted(d.glob("*.json")):
                if _is_os_metadata(fp, self.source_dir):
                    continue
                self._parse_entity(kind, fp, project, plan)

        # Chapters live in their own top-level dir with a different
        # schema shape (subset of Chapter, planning-only).
        self._parse_chapters(project, plan)

        self._check_referential_integrity(project, plan)
        self._compute_deletions(project, plan)
        return plan

    def _compute_deletions(
        self,
        project: WriterProject,
        plan: ImportPlan,
    ) -> None:
        """Build ``plan.to_delete`` according to two layered rules:

          1. In OVERWRITE mode, every non-chapter entity type is
             canonical — anything in the project but not in the
             package is deleted.

          2. Regardless of mode, kinds in
             ``_CANONICAL_KINDS_WHEN_PRESENT`` (currently just
             ``plot_event``) are canonical *if and only if at least
             one entity of that kind appears in the package*. The
             plot arc is structural: a partial replacement would
             scramble the dramatic shape, so we treat any plot
             update as a full plot replacement. If the LLM didn't
             return any plot files, the project's plot is left
             untouched.

        Chapter entries are intentionally NEVER added to to_delete
        — the chapter list is never reduced by any mode (the prose
        protection guarantee).
        """
        # Build a set of (kind, entity_id) the package will keep,
        # and remember which kinds were touched at all so we know
        # whether to enforce canonical-when-present semantics.
        keep: Dict[str, set] = {}
        kinds_in_package: set = set()
        for entry in plan.entries:
            if entry.entity_type == "chapter_planning":
                continue
            keep.setdefault(entry.entity_type, set()).add(entry.entity_id)
            kinds_in_package.add(entry.entity_type)

        for kind in _ENTITY_MODELS.keys():
            # Decide whether this kind is being treated as canonical
            # for this import:
            #   * always in OVERWRITE mode
            #   * in any mode if it's a "canonical-when-present" kind
            #     AND the package contains at least one of that kind
            is_canonical = (
                plan.mode == ImportMode.OVERWRITE
                or (kind in _CANONICAL_KINDS_WHEN_PRESENT
                    and kind in kinds_in_package))
            if not is_canonical:
                continue
            items = _get_list(project, kind) or []
            kept = keep.get(kind, set())
            for item in items:
                ent_id = getattr(item, "id", "")
                if ent_id and ent_id not in kept:
                    plan.to_delete.append((kind, ent_id))

    def _parse_entity(
        self,
        kind: str,
        fp: Path,
        project: WriterProject,
        plan: ImportPlan,
    ) -> None:
        try:
            raw = json.loads(fp.read_text())
        except Exception as e:
            plan.errors.append(
                f"{fp.relative_to(self.source_dir)}: invalid JSON ({e})")
            return
        if not isinstance(raw, dict):
            plan.errors.append(
                f"{fp.relative_to(self.source_dir)}: expected an "
                f"object at top level, got {type(raw).__name__}")
            return
        # The ``type`` field is informational only — directory location
        # determines kind. Warn on mismatch so the LLM-edited file can
        # be moved if needed.
        type_field = raw.get("type", "")
        if type_field and type_field != kind:
            plan.warnings.append(
                f"{fp.relative_to(self.source_dir)}: 'type' field "
                f"is '{type_field}' but file is in {kind} directory. "
                f"Using {kind}.")

        # Strip the meta ``type`` field before model validation.
        payload = {k: v for k, v in raw.items() if k != "type"}

        # Auto-assign an ID for new entities.
        ent_id = (payload.get("id") or "").strip()
        if not ent_id:
            ent_id = f"{kind}_{uuid4().hex[:8]}"
            payload["id"] = ent_id

        # Validate against the Pydantic model so type errors surface
        # before apply. We keep both validated form (for canonical
        # serialization) and raw dict (in case downstream needs to
        # preserve unknown fields — currently we discard them).
        model_cls = _ENTITY_MODELS.get(kind)
        if model_cls is None:
            plan.errors.append(
                f"{fp.relative_to(self.source_dir)}: no model for "
                f"kind '{kind}'")
            return
        try:
            validated = model_cls.model_validate(payload)
        except ValidationError as ve:
            plan.errors.append(
                f"{fp.relative_to(self.source_dir)}: schema validation "
                f"failed — {ve.error_count()} error(s): "
                f"{ve.errors()[0].get('msg', '?')}")
            return

        # Decide action: add vs. update.
        existing = self._find_existing(project, kind, ent_id)
        action = "update" if existing is not None else "add"

        entry = ImportEntry(
            entity_type=kind,
            action=action,
            entity_id=ent_id,
            file_path=str(fp.relative_to(self.source_dir)),
            data=validated.model_dump(mode="json"),
        )
        plan.entries.append(entry)

    def _parse_chapters(
        self,
        project: WriterProject,
        plan: ImportPlan,
    ) -> None:
        d = self.source_dir / "chapters"
        if not d.exists():
            return
        for fp in sorted(d.glob("*.json")):
            if _is_os_metadata(fp, self.source_dir):
                continue
            try:
                raw = json.loads(fp.read_text())
            except Exception as e:
                plan.errors.append(
                    f"{fp.relative_to(self.source_dir)}: invalid JSON ({e})")
                continue
            if not isinstance(raw, dict):
                plan.errors.append(
                    f"{fp.relative_to(self.source_dir)}: expected an "
                    f"object at top level")
                continue
            # Strip to the subset we accept. Even if the file contains
            # ``content`` or ``revisions``, those are NEVER imported.
            slim = {k: v for k, v in raw.items()
                    if k in _CHAPTER_IMPORT_ALLOWED_FIELDS}
            ent_id = (slim.get("id") or "").strip()
            if not ent_id:
                ent_id = f"chapter_{uuid4().hex[:8]}"
                slim["id"] = ent_id
            # Validate planning subset. We don't validate the whole
            # Chapter model because it expects content/revisions/etc.
            planning_raw = slim.get("planning") or {}
            try:
                ChapterPlanning.model_validate(planning_raw)
            except ValidationError as ve:
                plan.errors.append(
                    f"{fp.relative_to(self.source_dir)}: chapter "
                    f"planning validation failed — "
                    f"{ve.errors()[0].get('msg', '?')}")
                continue
            existing = self._find_existing_chapter(project, ent_id)
            action = "update" if existing is not None else "add"
            entry = ImportEntry(
                entity_type="chapter_planning",
                action=action,
                entity_id=ent_id,
                file_path=str(fp.relative_to(self.source_dir)),
                data=slim,
            )
            plan.entries.append(entry)

    def _find_existing(
        self,
        project: WriterProject,
        kind: str,
        ent_id: str,
    ) -> Optional[Any]:
        items = _get_list(project, kind)
        if items is None:
            return None
        for it in items:
            if getattr(it, "id", None) == ent_id:
                return it
        return None

    def _find_existing_chapter(
        self,
        project: WriterProject,
        ent_id: str,
    ) -> Optional[Any]:
        manuscript = getattr(project, "manuscript", None)
        chapters = getattr(manuscript, "chapters", None) if manuscript else None
        if not chapters:
            return None
        for ch in chapters:
            if getattr(ch, "id", None) == ent_id:
                return ch
        return None

    def _check_referential_integrity(
        self,
        project: WriterProject,
        plan: ImportPlan,
    ) -> None:
        """Warn (don't error) on references that won't resolve after
        apply. References use entity ids primarily, with names as
        fallback for legacy data.

        Output is aggregated per file: instead of N warnings per file
        (one per unresolved ref) we emit one warning per file with all
        the unresolved names grouped by target kind. That makes a
        long-tail report (61 lines for 18 files) collapse to one line
        per file. Prose-shape strings (descriptions that landed in a
        reference list by accident) are summarized as a count rather
        than reported per-ref.
        """
        # Build the projected ID set: existing entities + planned
        # adds, scoped per kind.
        projected: Dict[str, set] = {}
        for kind in _ENTITY_MODELS.keys():
            existing = _get_list(project, kind) or []
            projected[kind] = {
                getattr(it, "id", "") for it in existing
                if getattr(it, "id", "")}
        for entry in plan.entries:
            if entry.entity_type in projected:
                projected[entry.entity_type].add(entry.entity_id)

        # ctx -> {kind -> ordered list of unresolved ref strings}
        file_unresolved: Dict[str, Dict[str, List[str]]] = {}
        # ctx -> count of prose-shape entries skipped in reference lists
        file_prose: Dict[str, int] = {}

        def _check(refs: Any, target_kind: str, ctx: str) -> None:
            if not refs:
                return
            if isinstance(refs, str):
                refs = [refs]
            for ref in refs:
                ref = (ref or "").strip()
                if not ref:
                    continue
                if _is_ref_prose_shape(ref):
                    # Probably an LLM stuffing description prose into
                    # a list of ids/names. Count it for a one-line
                    # summary rather than emitting N noisy warnings.
                    file_prose[ctx] = file_prose.get(ctx, 0) + 1
                    continue
                if (ref in projected.get(target_kind, set())
                        or _name_matches(project, target_kind, ref)):
                    continue
                # Re-try with parenthetical qualifier stripped.
                # ``"Jade (militant action)"`` -> ``"Jade"``. About
                # 10% of the field reports were this single pattern.
                stripped = _strip_ref_parenthetical(ref)
                if stripped and stripped != ref and (
                        stripped in projected.get(target_kind, set())
                        or _name_matches(
                            project, target_kind, stripped)):
                    continue
                file_unresolved.setdefault(
                    ctx, {}).setdefault(
                        target_kind, []).append(ref)

        for entry in plan.entries:
            d = entry.data
            ctx = entry.file_path
            if entry.entity_type == "faction":
                _check(d.get("allies"), "faction", ctx)
                _check(d.get("enemies"), "faction", ctx)
            elif entry.entity_type == "place":
                _check(d.get("controlling_faction"), "faction", ctx)
                _check(d.get("contested_by"), "faction", ctx)
                _check(d.get("connected_places"), "place", ctx)
            elif entry.entity_type == "culture":
                _check(d.get("associated_factions"), "faction", ctx)
            elif entry.entity_type == "myth":
                _check(d.get("associated_factions"), "faction", ctx)
                _check(d.get("key_figures"), "character", ctx)
            elif entry.entity_type == "technology":
                _check(d.get("factions_with_access"), "faction", ctx)
                _check(d.get("inventor_faction"), "faction", ctx)
                _check(d.get("prerequisites"), "technology", ctx)
            elif entry.entity_type == "historical_event":
                _check(d.get("factions_involved"), "faction", ctx)
                _check(d.get("key_figures"), "character", ctx)

        # Aggregate into per-file warnings. Stable sort by file path
        # so the warning list is deterministic across runs.
        all_ctxs = sorted(
            set(file_unresolved.keys()) | set(file_prose.keys()))
        for ctx in all_ctxs:
            parts: List[str] = []
            if ctx in file_unresolved:
                for kind, refs in file_unresolved[ctx].items():
                    quoted = ", ".join(f"'{r}'" for r in refs)
                    parts.append(
                        f"{len(refs)} unresolved {kind} "
                        f"reference(s): {quoted}")
            if ctx in file_prose:
                parts.append(
                    f"{file_prose[ctx]} prose-shaped entr"
                    f"{'y' if file_prose[ctx] == 1 else 'ies'} in "
                    f"reference list(s) — looks like description "
                    f"text; move to a description field, not a "
                    f"list of ids/names")
            if parts:
                plan.warnings.append(f"{ctx}: " + "; ".join(parts))


# ---------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------
@dataclass
class ApplyResult:
    """Returned from apply_import_plan with what actually changed."""
    added: List[Tuple[str, str]] = field(default_factory=list)
    updated: List[Tuple[str, str]] = field(default_factory=list)
    deleted: List[Tuple[str, str]] = field(default_factory=list)
    skipped: List[Tuple[str, str, str]] = field(default_factory=list)
    chapters_planning_updated: int = 0
    chapters_created: int = 0
    # Existing chapters left untouched because they weren't in the
    # package. Always non-zero when a project has chapters the LLM
    # didn't echo back — this is the load-bearing chapter-safety
    # signal users see in the post-apply summary.
    chapters_preserved: int = 0


def apply_import_plan(
    project: WriterProject,
    plan: ImportPlan,
) -> ApplyResult:
    """Apply a validated ``ImportPlan`` to ``project`` in place.

    Refuses to run (raises ValueError) if the plan has any errors.
    Critical invariants:
      * Chapter ``content`` / ``html_content`` / ``revisions`` /
        ``annotations`` are never written.
      * Existing entities not in the plan are left untouched.
      * Imports are merged by id; an existing entity with matching id
        is replaced wholesale by the imported one (the LLM owns the
        full entity definition for entities it returns).
    """
    if not plan.is_applyable:
        raise ValueError(
            f"Cannot apply: plan has {len(plan.errors)} blocking errors")

    # Snapshot the set of chapter IDs the package imports so we can
    # report ``chapters_preserved`` (existing chapters left untouched
    # because they weren't in the package). Surfaces the safety
    # property in the post-apply summary.
    imported_chapter_ids = {
        e.entity_id for e in plan.entries
        if e.entity_type == "chapter_planning"
    }

    result = ApplyResult()
    for entry in plan.entries:
        try:
            if entry.entity_type == "chapter_planning":
                _apply_chapter(project, entry, result)
            else:
                _apply_entity(project, entry, result)
        except Exception as e:
            result.skipped.append(
                (entry.entity_type, entry.entity_id, str(e)))

    # Apply whatever deletions ``_compute_deletions`` decided. The
    # plan already encodes the mode-vs-canonical-kind logic, so this
    # step is uniform: walk plan.to_delete and remove each entity.
    # Chapter entries are never added to to_delete (defense in depth
    # check repeated here in case of future changes).
    for kind, ent_id in plan.to_delete:
        if kind == "chapter_planning":
            continue
        try:
            _delete_entity(project, kind, ent_id, result)
        except Exception as e:
            result.skipped.append((kind, ent_id, str(e)))

    # Count preserved chapters — those in the project but not in the
    # package. This is non-zero whenever the LLM didn't echo every
    # chapter back; the value is the "your prose is safe" receipt.
    manuscript = getattr(project, "manuscript", None)
    chapters = getattr(manuscript, "chapters", None) if manuscript else None
    if chapters:
        for ch in chapters:
            ch_id = getattr(ch, "id", "")
            if ch_id and ch_id not in imported_chapter_ids:
                result.chapters_preserved += 1

    project.updated_at = datetime.now()
    return result


def _delete_entity(
    project: WriterProject,
    kind: str,
    ent_id: str,
    result: ApplyResult,
) -> None:
    """Remove an entity by id from its project list. No-op if the
    entity doesn't exist. Used by overwrite-mode apply."""
    items = _get_list(project, kind)
    if not items:
        return
    for i, item in enumerate(items):
        if getattr(item, "id", "") == ent_id:
            items.pop(i)
            result.deleted.append((kind, ent_id))
            return


def _apply_entity(
    project: WriterProject,
    entry: ImportEntry,
    result: ApplyResult,
) -> None:
    kind = entry.entity_type
    model_cls = _ENTITY_MODELS[kind]
    items = _get_list(project, kind, create_if_missing=True)
    if items is None:
        raise RuntimeError(
            f"could not locate list for entity kind '{kind}'")
    # Drop the ``type`` field if it accidentally survived.
    payload = {k: v for k, v in entry.data.items() if k != "type"}
    obj = model_cls.model_validate(payload)
    # Replace existing by id; else append.
    for i, existing in enumerate(items):
        if getattr(existing, "id", None) == entry.entity_id:
            items[i] = obj
            result.updated.append((kind, entry.entity_id))
            return
    items.append(obj)
    result.added.append((kind, entry.entity_id))


def _apply_chapter(
    project: WriterProject,
    entry: ImportEntry,
    result: ApplyResult,
) -> None:
    """Update or create a chapter, preserving prose.

    For an existing chapter: update title, number, and planning.
    Never touch content / html_content / revisions / annotations /
    todos / story_events / feedback.

    For a new chapter: create with empty content. The user fills in
    prose later in WritingAid.
    """
    manuscript = getattr(project, "manuscript", None)
    if manuscript is None:
        # Defensive: WriterProject always has a Manuscript, but if a
        # caller passed a stripped-down model we won't crash silently.
        raise RuntimeError("project has no manuscript")
    chapters = getattr(manuscript, "chapters", None)
    if chapters is None:
        # Initialize the chapter list if it doesn't exist yet.
        manuscript.chapters = []
        chapters = manuscript.chapters

    data = entry.data
    chap_id = entry.entity_id
    new_title = (data.get("title") or "").strip()
    new_number = data.get("number")
    new_planning_raw = data.get("planning") or {}
    new_planning = ChapterPlanning.model_validate(new_planning_raw)

    for ch in chapters:
        if getattr(ch, "id", None) == chap_id:
            # PROTECTED FIELDS: do NOT touch any of these.
            # content / html_content / revisions / annotations /
            # todos / story_events / feedback / word_count / created_at.
            if new_title:
                ch.title = new_title
            if isinstance(new_number, int) and new_number > 0:
                ch.number = new_number
            ch.planning = new_planning
            ch.updated_at = datetime.now()
            result.chapters_planning_updated += 1
            return

    # No existing chapter — create a new one with empty prose. We
    # avoid importing the Chapter class directly until needed to keep
    # this module's import surface tight.
    from src.models.project import Chapter
    new_chapter = Chapter(
        id=chap_id,
        number=new_number if isinstance(new_number, int) and new_number > 0
               else (max((c.number for c in chapters), default=0) + 1),
        title=new_title or f"Chapter {len(chapters) + 1}",
        content="",
        planning=new_planning,
    )
    chapters.append(new_chapter)
    result.chapters_created += 1


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _get_list(
    project: WriterProject,
    kind: str,
    create_if_missing: bool = False,
) -> Optional[List[Any]]:
    """Resolve a kind label to the list on the project that holds it.

    Walks the dotted path in ``_ENTITY_LOCATIONS``. Returns None if
    the parent path doesn't exist (e.g., story_planning is missing
    on a stripped project).
    """
    path = _ENTITY_LOCATIONS.get(kind)
    if not path:
        return None
    obj: Any = project
    for attr in path[:-1]:
        obj = getattr(obj, attr, None)
        if obj is None:
            return None
    last = path[-1]
    lst = getattr(obj, last, None)
    if lst is None and create_if_missing:
        setattr(obj, last, [])
        lst = getattr(obj, last)
    return lst


def _name_matches(
    project: WriterProject,
    kind: str,
    name_or_id: str,
) -> bool:
    """True if any existing entity of ``kind`` has a matching id OR name."""
    items = _get_list(project, kind) or []
    norm = name_or_id.strip().lower()
    for it in items:
        if getattr(it, "id", "") == name_or_id:
            return True
        if (getattr(it, "name", "") or "").strip().lower() == norm:
            return True
    return False


# ---------------------------------------------------------------------
# Documentation generators (always written, including for empty projects)
# ---------------------------------------------------------------------
# Minimal example payloads keyed by entity kind. Kept short and
# realistic so the LLM has a clean pattern to copy when creating new
# entities. Each one validates against its Pydantic model.
_SCHEMA_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "character": {
        "type": "character",
        "name": "General Mara",
        "character_type": "protagonist",
        "personality": "Stoic, principled, haunted.",
        "motivations": "Redeem her family's name.",
        "fears": "That she is becoming her father.",
        "personality_traits": ["stoic", "loyal", "disciplined"],
        "social_network": {"Bren": "rival", "Joren": "spouse"},
    },
    "faction": {
        "type": "faction",
        "name": "Iron League",
        "faction_type": "nation",
        "description": "An industrialized federation of mountain states.",
        "leader": "General Mara",
        "territory": ["Highveld"],
        "allies": ["f_pact"],
        "enemies": ["f_shade"],
        "military_strength": 75,
        "economic_power": 60,
    },
    "place": {
        "type": "place",
        "name": "Highveld",
        "place_type": "region",
        "description": "A rolling plateau north of the river.",
        "controlling_faction": "f_iron",
        "connected_places": ["p_riverford"],
        "notable_inhabitants": ["ch_mara"],
        "strategic_value": 70,
    },
    "culture": {
        "type": "culture",
        "name": "Iron Way",
        "description": "A martial culture emphasizing duty and ancestry.",
        "associated_factions": ["f_iron"],
        "core_values": ["honor", "discipline", "service"],
    },
    "technology": {
        "type": "technology",
        "name": "Steam Engine",
        "technology_type": "manufacturing",
        "description": "Coal-fed reciprocating engine.",
        "factions_with_access": ["f_iron"],
        "prerequisites": ["t_furnace"],
        "game_changing_level": 80,
    },
    "historical_event": {
        "type": "historical_event",
        "name": "Highveld War",
        "date": "Year 102",
        "event_type": "war",
        "description": "Three-year conflict over the Highveld pass.",
        "location": "Highveld",
        "factions_involved": ["f_iron", "f_shade"],
        "key_figures": ["ch_mara"],
    },
    "flora": {
        "type": "flora",
        "name": "Mountain Moss",
        "flora_type": "moss",
        "description": "Edible bittermoss native to high altitudes.",
        "edible": True,
    },
    "fauna": {
        "type": "fauna",
        "name": "Pasture Wolf",
        "fauna_type": "predator",
        "description": "Pack hunter, territorial.",
        "danger_level": 60,
    },
    "myth": {
        "type": "myth",
        "name": "The First Forge",
        "myth_type": "creation",
        "description": "The story of how the Iron Way was bound in fire.",
        "associated_factions": ["f_iron"],
        "key_figures": ["The First Smith"],
    },
    "subplot": {
        "type": "subplot",
        "title": "The Betrayal",
        "description": "Bren's secret loyalty to the Shade Syndicate.",
        "status": "active",
        "related_characters": ["ch_bren", "ch_mara"],
        "connection_to_main": (
            "Forces Mara's allegiance test in Act II."),
    },
    "plot_event": {
        "type": "plot_event",
        "title": "Mara's Choice",
        "description": "Mara must decide whether to spare Bren.",
        "stage": "climax",
        "act": 3,
        "intensity": 90,
        "related_characters": ["ch_mara", "ch_bren"],
    },
    "story_promise": {
        "type": "story_promise",
        "promise_type": "character",
        "title": "Mara will confront her father's legacy.",
        "description": (
            "A promise that the climax addresses Mara's ghost."),
    },
    "character_tension": {
        "type": "character_tension",
        "title": "Mara and Bren's eroding trust",
        "description": "Their bond cracks as Bren's secrets surface.",
        "tension_type": "interpersonal",
        "characters_involved": ["ch_mara", "ch_bren"],
        "intensity": 70,
    },
    "theme": {
        "type": "theme",
        "title": "Cost of loyalty",
        "description": "What loyalty extracts from those who keep it.",
        "statement": (
            "Loyalty without honest reckoning becomes complicity."),
        "motifs": ["broken oaths", "iron rings"],
    },
}

# Example payload for chapter planning. The schema for chapter
# import differs from the other entities — only a subset of Chapter
# is honored (planning, title, number). This template makes that
# explicit to the LLM.
_CHAPTER_PLANNING_EXAMPLE: Dict[str, Any] = {
    "type": "chapter_planning",
    "id": "ch_new_chapter_id",
    "number": 5,
    "title": "The Border",
    "planning": {
        "description": "Mara crosses into Shade territory.",
        "outline": (
            "1. Approach at dawn.\n2. Bren's warning.\n"
            "3. The first patrol."),
        "pov_character": "Mara",
        "tone": "tense, paranoid",
        "themes": ["betrayal", "the cost of duty"],
        "scene_list": ["Border crossing", "Bren intercepts Mara"],
        "characters_featured": ["ch_mara", "ch_bren"],
    },
}


def _render_instructions_doc() -> str:
    """Build the LLM-facing INSTRUCTIONS_FOR_LLM.md content.

    Two workflows: edit an existing project, and create a project
    from scratch. The doc is deliberately concrete and includes the
    exact safety invariants the importer enforces."""
    lines = [
        "# Instructions for the LLM",
        "",
        "You are helping a writer manage their story's characters, "
        "worldbuilding, and plot. This folder contains JSON files "
        "you can read, edit, or add to. **You are not editing "
        "chapter prose** — the chapter text is not in this package "
        "and the importer will refuse to write it.",
        "",
        "## The two workflows",
        "",
        "### A) Edit an existing project",
        "",
        "1. Read the files in `characters/`, `worldbuilding/*`, "
        "`plot/*`, and `chapters/` to understand the existing state.",
        "2. The user will tell you what to change.",
        "3. Edit files in place. Keep each entity's `id` field "
        "**unchanged** when modifying it. The importer uses `id` to "
        "match the file to the existing entity.",
        "4. Add new entities by creating new files in the right "
        "subdirectory. Either include a unique `id` (so other files "
        "can reference it) or omit `id` to let the importer assign "
        "one.",
        "5. Cross-references like `Faction.allies`, "
        "`Place.controlling_faction`, `Character.love_interests[].character_id`, "
        "etc. should use entity `id` values when available. Names "
        "also resolve as a fallback.",
        "",
        "### B) Start a new project from scratch",
        "",
        "1. Look at `SCHEMA.md` for every entity type's fields and a "
        "JSON example each. Copy the structure to create new entities.",
        "2. Build the project incrementally. Suggested order:",
        "   1. A handful of central **characters** (`characters/*.json`)",
        "   2. The **factions** they belong to "
        "(`worldbuilding/factions/*.json`)",
        "   3. The **places** the story happens in "
        "(`worldbuilding/places/*.json`)",
        "   4. The **main plot** and any **subplots / themes / "
        "promises / tensions** (`plot/*`)",
        "   5. **Chapter planning** for each chapter — outline, "
        "scenes, POV, tone (`chapters/<num>-<slug>.json`). **Do not "
        "include chapter prose.**",
        "3. Assign each new entity a stable `id` (lowercase, "
        "underscored — e.g. `ch_mara`, `f_iron`, `p_highveld`). "
        "Using consistent ids lets you cross-reference them from "
        "other files.",
        "4. When the user is happy, they import the package back. "
        "The importer validates everything before applying.",
        "",
        "## Hard rules",
        "",
        "* **Never include or invent chapter prose.** The package "
        "does not contain chapter text and the importer will not "
        "write any `content` field on a chapter — it is silently "
        "stripped.",
        "* **Keep `id` stable** when editing an existing entity. "
        "Changing `id` will be treated as a brand-new entity.",
        "* **Don't edit `manifest.json`.** It's metadata for the "
        "importer.",
        "* **Don't invent new top-level keys** that aren't in "
        "`SCHEMA.md`. The importer ignores unknown fields silently, "
        "so they get lost.",
        "* **Enum values are case-sensitive lowercase** "
        "(e.g. `\"faction_type\": \"nation\"`, "
        "`\"place_type\": \"region\"`). See SCHEMA.md for the "
        "allowed values per field.",
        "",
        "## Two import modes (the user picks)",
        "",
        "* **Update mode** (default, safe): your package is treated "
        "as a patch. **Any file whose `id` doesn't match an existing "
        "entity is created** as a new entity; matching ids are "
        "updated in place; existing entities not present in your "
        "package are left alone. Use this when you've added or "
        "edited a few entities — the user keeps everything else.",
        "* **Overwrite mode**: your package is canonical for the "
        "non-chapter entity types. New files are still created and "
        "matching ids updated, but **anything the user has in their "
        "project that isn't in your package will be deleted** "
        "(except chapters — those are always preserved). Use this "
        "when the user explicitly asks you to *replace* a section, "
        "e.g. *\"redo the whole faction list.\"*",
        "",
        "## Special rule: the main plot is always canonical",
        "",
        "The main manuscript plot — files in `plot/events/` — is a "
        "coherent dramatic arc. A half-replaced plot is worse than no "
        "replacement because it scrambles the structural shape the "
        "writer (and you) reasoned about. So **plot events are "
        "treated as canonical whenever you include any of them, "
        "regardless of import mode**:",
        "",
        "* If you include ANY `plot/events/*.json` file in the "
        "package, you must include **every plot event you want kept**. "
        "Events the user has in their project that aren't in your "
        "files will be **deleted**.",
        "* If you don't include any `plot/events/*.json` file, the "
        "user's plot is left untouched. (This is the safe default "
        "when you're only editing characters or worldbuilding.)",
        "* Subplots (`plot/subplots/`) and chapter planning are NOT "
        "subject to this rule — they follow the normal additive / "
        "overwrite-mode semantics.",
        "",
        "**Practical rule**: before saving any change to "
        "`plot/events/`, re-read every event file in that folder and "
        "make sure your set is complete. If the user asks you to "
        "*\"add a midpoint reversal\"*, include every existing event "
        "alongside the new one. If the user asks you to *\"keep "
        "everything but rephrase the climax\"*, include every "
        "existing event with the climax rewritten.",
        "",
        "Either way, the user's chapter prose is safe.",
        "",
        "## When the user asks for something",
        "",
        "* If they ask for new **characters** → write "
        "`characters/<new>.json` files.",
        "* If they ask to **rebalance factions** → edit existing "
        "files under `worldbuilding/factions/`. Keep `id` stable.",
        "* If they ask to **flesh out the plot** → edit "
        "`plot/main_plot.json`, add `plot/subplots/<new>.json`, "
        "etc.",
        "* If they ask to **plan a new chapter** → write a new file "
        "in `chapters/` with the planning schema (see SCHEMA.md). "
        "Leave the user to write the prose themselves.",
        "",
        "## What you should NOT do",
        "",
        "* Don't write or modify any file outside the folders listed "
        "above.",
        "* Don't add a `content`, `html_content`, `revisions`, or "
        "`annotations` field to a chapter file. They will be stripped.",
        "* Don't change `manifest.json` or `SCHEMA.md`.",
        "* Don't suggest the user manually copy-paste prose between "
        "this package and their book — the package is for "
        "structured story data only.",
    ]
    return "\n".join(lines) + "\n"


def _render_schema_doc() -> str:
    """Auto-generate SCHEMA.md from the Pydantic models in
    ``_ENTITY_MODELS`` plus the chapter-planning schema.

    For each entity type, lists its fields (name, type, required vs.
    optional) and embeds a JSON example. The example is the
    hand-curated minimal pattern in ``_SCHEMA_EXAMPLES`` so it stays
    short and valid.
    """
    parts: List[str] = [
        "# Schema reference",
        "",
        "Every entity type WritingAid imports, listed with its "
        "fields and a JSON example you can copy. **Required** fields "
        "must be present; optional fields can be omitted (they "
        "default to empty/zero/null).",
        "",
        "Notation: `string`, `int`, `bool`, `list[X]`, `dict[K, V]`, "
        "`enum(<allowed values>)`. Enum values are case-sensitive "
        "and lowercase.",
        "",
    ]
    for kind, model_cls in _ENTITY_MODELS.items():
        parts.append(f"## `{kind}`")
        parts.append("")
        parts.append(
            f"Lives in: `{_ENTITY_DIRS[kind]}/<slug>.json`")
        parts.append("")
        parts.append("### Fields")
        parts.append("")
        for field_name, field_info in model_cls.model_fields.items():
            type_str = _type_str(field_info.annotation)
            required = field_info.is_required()
            req_marker = "**required**" if required else "optional"
            desc = field_info.description or ""
            line = f"- `{field_name}` — {type_str} ({req_marker})"
            if desc:
                line += f" — {desc}"
            parts.append(line)
        parts.append("")
        example = _SCHEMA_EXAMPLES.get(kind)
        if example is not None:
            parts.append("### Example")
            parts.append("")
            parts.append("```json")
            parts.append(json.dumps(example, indent=2, ensure_ascii=False))
            parts.append("```")
            parts.append("")
    # Chapter planning is special — different shape (subset of Chapter).
    parts.append("## `chapter_planning` (chapters/<num>-<slug>.json)")
    parts.append("")
    parts.append(
        "Chapter files contain ONLY the fields below. The importer "
        "**ignores** any other key (including `content`, "
        "`html_content`, `revisions`, `annotations`). This protects "
        "the user's prose absolutely.")
    parts.append("")
    parts.append("### Top-level fields")
    parts.append("")
    parts.append("- `id` — string, optional. Stable identifier. "
                 "Omit for a new chapter (the importer assigns one).")
    parts.append("- `number` — int, required for new chapters. The "
                 "chapter's ordinal position.")
    parts.append("- `title` — string, required for new chapters.")
    parts.append("- `planning` — object, required. See "
                 "`ChapterPlanning` fields below.")
    parts.append("")
    parts.append("### `planning` fields")
    parts.append("")
    from src.models.project import ChapterPlanning
    for field_name, field_info in ChapterPlanning.model_fields.items():
        type_str = _type_str(field_info.annotation)
        required = field_info.is_required()
        req_marker = "**required**" if required else "optional"
        desc = field_info.description or ""
        line = f"- `{field_name}` — {type_str} ({req_marker})"
        if desc:
            line += f" — {desc}"
        parts.append(line)
    parts.append("")
    parts.append("### Example")
    parts.append("")
    parts.append("```json")
    parts.append(json.dumps(
        _CHAPTER_PLANNING_EXAMPLE, indent=2, ensure_ascii=False))
    parts.append("```")
    parts.append("")
    return "\n".join(parts)


def _type_str(annotation: Any) -> str:
    """Render a Python type annotation as a short, LLM-readable
    string. Best-effort — falls back to ``repr(annotation)`` for
    unfamiliar types."""
    if annotation is None or annotation is type(None):
        return "null"
    if annotation is str:
        return "string"
    if annotation is int:
        return "int"
    if annotation is bool:
        return "bool"
    if annotation is float:
        return "float"
    # Enums: ``enum(value1|value2|...)``
    try:
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            values = "|".join(repr(m.value) for m in annotation)
            return f"enum({values})"
    except TypeError:
        pass
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is list:
        inner = _type_str(args[0]) if args else "any"
        return f"list[{inner}]"
    if origin is dict:
        if len(args) == 2:
            return f"dict[{_type_str(args[0])}, {_type_str(args[1])}]"
        return "dict"
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return f"{_type_str(non_none[0])} (nullable)"
        return " | ".join(_type_str(a) for a in non_none)
    # Pydantic submodel — give the class name.
    try:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation.__name__
    except TypeError:
        pass
    return getattr(annotation, "__name__", repr(annotation))
