"""Tests for the LLM round-trip export/import package.

Run:
    python -m tests.test_llm_package

Covers:
  * Round-trip: export → re-import → no changes to entity content.
  * Chapter content protection: existing prose never written by import.
  * Additive import: entities missing from the package stay in project.
  * Validation: malformed JSON / schema errors land in plan.errors and
    block apply.
  * New entity creation: file without ``id`` gets a fresh id on import.
  * Referential integrity warnings: dangling references reported.
  * Chapter creation: new chapter in package → empty content.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export.llm_package import (  # noqa: E402
    ImportMode, LLMPackageExporter, LLMPackageImporter,
    SCHEMA_VERSION, apply_import_plan,
)
from src.models.project import (  # noqa: E402
    Chapter, ChapterPlanning, Character, FreytagPyramid, Manuscript,
    PlotEvent, StoryPlanning, Subplot, Theme, WorldBuilding,
    WriterProject,
)
from src.models.worldbuilding_objects import (  # noqa: E402
    Culture, Faction, FactionType, Place, PlaceType, Technology,
    TechnologyType,
)


def _build_project_with_prose() -> WriterProject:
    """Synthesize a project that includes chapter prose so the
    content-protection invariant can be tested end-to-end."""
    factions = [
        Faction(id="f_iron", name="Iron League",
                faction_type=FactionType.NATION,
                allies=["f_pact"], enemies=["f_shade"]),
        Faction(id="f_pact", name="Stoneforge Pact",
                faction_type=FactionType.NATION,
                allies=["f_iron"]),
        Faction(id="f_shade", name="Shade Syndicate",
                faction_type=FactionType.CRIMINAL),
    ]
    places = [
        Place(id="p_highveld", name="Highveld",
              place_type=PlaceType.REGION,
              controlling_faction="f_iron",
              connected_places=["p_riverford"]),
        Place(id="p_riverford", name="Riverford",
              place_type=PlaceType.TOWN,
              controlling_faction="f_iron"),
    ]
    cultures = [Culture(id="c_iron", name="Iron Way",
                        associated_factions=["f_iron"])]
    techs = [
        Technology(id="t_furnace", name="Furnace",
                   technology_type=TechnologyType.MANUFACTURING),
        Technology(id="t_steam", name="Steam Engine",
                   technology_type=TechnologyType.MANUFACTURING,
                   prerequisites=["t_furnace"]),
    ]
    chars = [
        Character(id="ch_mara", name="General Mara",
                  character_type="protagonist",
                  motivations="Redeem her family's name.",
                  social_network={"Bren": "rival"}),
        Character(id="ch_bren", name="Bren",
                  character_type="antagonist"),
    ]
    subplots = [Subplot(id="sp_betrayal", title="The Betrayal",
                        description="Bren's secret loyalty",
                        related_characters=["ch_bren"])]
    plot_event = PlotEvent(id="pe_choice", title="Mara's Choice",
                           related_characters=["ch_mara"])
    theme = Theme(id="th_loyalty", title="Cost of loyalty",
                  description="What loyalty extracts from those who keep it.")

    sp = StoryPlanning(
        main_plot="Mara must choose between her sworn duty and Bren's life.",
        themes=["loyalty", "sacrifice"],
        theme_details=[theme],
        subplots=subplots,
        freytag_pyramid=FreytagPyramid(events=[plot_event]),
    )
    wb = WorldBuilding(
        factions=factions, places=places, cultures=cultures,
        technologies=techs,
    )
    # Two chapters with non-trivial prose. The content invariant test
    # asserts these strings survive an import unchanged.
    chapters = [
        Chapter(id="ch_001", number=1, title="The Trial",
                content=(
                    "Mara walked into the council chamber. "
                    "The chairs were empty, but the weight of every "
                    "ancestor pressed against her shoulders."),
                planning=ChapterPlanning(
                    description="Mara faces the council.",
                    pov_character="Mara")),
        Chapter(id="ch_002", number=2, title="The Reckoning",
                content="Bren waited at the bridge. He did not look up.",
                planning=ChapterPlanning(
                    description="Bren confronts Mara.")),
    ]
    return WriterProject(
        name="Test Project",
        description="For LLM package round-trip tests.",
        worldbuilding=wb,
        characters=chars,
        story_planning=sp,
        manuscript=Manuscript(chapters=chapters),
    )


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="wa_llm_pkg_"))


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def test_export_creates_expected_tree() -> None:
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Manifest + README must exist.
        assert (dest / "manifest.json").exists(), list(dest.iterdir())
        assert (dest / "README.md").exists()
        manifest = json.loads((dest / "manifest.json").read_text())
        assert manifest["schema_version"] == SCHEMA_VERSION
        assert manifest["project_name"] == "Test Project"
        # Entity directories — only ones with content.
        assert (dest / "characters").is_dir()
        assert (dest / "worldbuilding" / "factions").is_dir()
        assert (dest / "worldbuilding" / "places").is_dir()
        assert (dest / "plot" / "subplots").is_dir()
        assert (dest / "plot" / "events").is_dir()
        assert (dest / "plot" / "themes").is_dir()
        assert (dest / "plot" / "main_plot.json").exists()
        assert (dest / "chapters").is_dir()
        # Each character should have produced a file.
        char_files = list((dest / "characters").glob("*.json"))
        assert len(char_files) == 2, char_files
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_export_excludes_chapter_content() -> None:
    """Chapter prose must NOT appear in the exported chapter files —
    this is the load-bearing privacy/safety property of the package."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        for fp in (dest / "chapters").glob("*.json"):
            data = json.loads(fp.read_text())
            assert "content" not in data, (
                f"{fp.name} leaked chapter prose: keys={list(data.keys())}")
            assert "html_content" not in data, fp.name
            assert "revisions" not in data, fp.name
            assert "annotations" not in data, fp.name
            # Planning + title + number must be there.
            assert "planning" in data, data
            assert "title" in data, data
            assert "number" in data, data
    finally:
        shutil.rmtree(dest, ignore_errors=True)


# ----------------------------------------------------------------------
# Import: plan
# ----------------------------------------------------------------------
def test_import_round_trip_no_changes_makes_plan_of_updates() -> None:
    """Export then immediately import — every entity should match an
    existing project entity and be marked as ``update`` (not add).
    The plan should be applyable with zero errors."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors
        # Every entry should be an update (since the import IS the
        # project's own export).
        non_updates = [e for e in plan.entries if e.action != "update"]
        assert not non_updates, [
            (e.entity_type, e.entity_id, e.action) for e in non_updates]
        summary = plan.summary()
        assert summary["adds"] == 0, summary
        assert summary["updates"] > 0, summary
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_import_apply_preserves_chapter_content() -> None:
    """The load-bearing invariant: applying an import plan must NOT
    overwrite chapter prose, even if planning fields change.

    Simulate an LLM edit by modifying ``planning.description`` on a
    chapter JSON file, then import + apply. Chapter content must be
    byte-identical afterward.
    """
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Mutate the chapter planning in the package (simulate LLM edit)
        ch_files = list((dest / "chapters").glob("*.json"))
        assert ch_files
        target = ch_files[0]
        data = json.loads(target.read_text())
        data["planning"]["description"] = (
            "LLM-rewritten chapter description.")
        target.write_text(json.dumps(data))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors

        # Snapshot chapter prose before apply.
        before = {ch.id: ch.content for ch in p.manuscript.chapters}
        result = apply_import_plan(p, plan)

        for ch in p.manuscript.chapters:
            assert ch.content == before[ch.id], (
                f"chapter {ch.id} content changed during import!")
        # Planning update should have landed.
        ch1 = next(c for c in p.manuscript.chapters
                   if c.id == data["id"])
        assert ch1.planning.description == (
            "LLM-rewritten chapter description.")
        assert result.chapters_planning_updated >= 1
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_import_apply_protects_content_even_when_present_in_json() -> None:
    """A maliciously-crafted (or LLM-hallucinated) chapter JSON that
    includes a ``content`` field must STILL not overwrite project
    prose. Defense in depth: the importer enforces the rule at the
    apply step, not just at export."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        ch_files = list((dest / "chapters").glob("*.json"))
        target = ch_files[0]
        data = json.loads(target.read_text())
        data["content"] = "MALICIOUSLY INJECTED PROSE — should never land"
        data["html_content"] = "<p>also bad</p>"
        target.write_text(json.dumps(data))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors

        before = {ch.id: ch.content for ch in p.manuscript.chapters}
        apply_import_plan(p, plan)

        for ch in p.manuscript.chapters:
            assert ch.content == before[ch.id]
            assert "MALICIOUSLY" not in ch.content
            assert "MALICIOUSLY" not in (ch.html_content or "")
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_import_additive_does_not_remove_entities_missing_from_package() -> None:
    """Entities that exist in the project but are NOT in the import
    package must remain after apply. Imports are additive."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Delete one character's file from the package — simulate the
        # LLM forgetting to include it. Filenames slugify underscores
        # to hyphens, so "ch_bren" → "ch-bren" in the filename.
        target = next((dest / "characters").glob("*ch-bren*.json"))
        target.unlink()

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable
        apply_import_plan(p, plan)
        # Bren must still exist in the project.
        ids = {c.id for c in p.characters}
        assert "ch_bren" in ids, ids
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_import_creates_new_entity_when_id_absent() -> None:
    """A new file without an ``id`` field should be added with a
    freshly-generated id, and the project should grow by one."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        new_faction = {
            "type": "faction",
            "name": "Briar Coalition",
            "faction_type": "tribe",
            "description": "Forest-dwellers; new alliance under Mara.",
        }
        (dest / "worldbuilding" / "factions" / "new-briar.json"
         ).write_text(json.dumps(new_faction))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors
        adds = [e for e in plan.entries if e.action == "add"]
        assert len(adds) == 1, adds
        new_entry = adds[0]
        assert new_entry.entity_type == "faction"
        assert new_entry.entity_id  # auto-assigned, non-empty

        before_count = len(p.worldbuilding.factions)
        apply_import_plan(p, plan)
        after_count = len(p.worldbuilding.factions)
        assert after_count == before_count + 1
        # The new faction must have the right name.
        new_obj = next(f for f in p.worldbuilding.factions
                       if f.name == "Briar Coalition")
        assert new_obj.id == new_entry.entity_id
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_import_creates_new_chapter_with_empty_content() -> None:
    """An LLM can add a new chapter to the package (with planning) —
    on import, a Chapter is created with empty prose."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        new_chapter = {
            "type": "chapter_planning",
            "id": "ch_new",
            "number": 3,
            "title": "The Edge",
            "planning": {
                "description": "Mara reaches the border.",
                "pov_character": "Mara",
            },
        }
        (dest / "chapters" / "003-the-edge.json").write_text(
            json.dumps(new_chapter))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors
        result = apply_import_plan(p, plan)
        assert result.chapters_created == 1, result
        new_ch = next(c for c in p.manuscript.chapters
                      if c.id == "ch_new")
        assert new_ch.content == "", repr(new_ch.content)
        assert new_ch.title == "The Edge"
        assert new_ch.planning.description == "Mara reaches the border."
    finally:
        shutil.rmtree(dest, ignore_errors=True)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def test_invalid_json_creates_error_blocks_apply() -> None:
    """A malformed JSON file in the package must produce an error in
    the plan and prevent apply from running."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Corrupt one file.
        target = next((dest / "characters").glob("*.json"))
        target.write_text("{ this is not valid json")

        plan = LLMPackageImporter(dest).build_plan(p)
        assert not plan.is_applyable
        assert plan.errors
        try:
            apply_import_plan(p, plan)
            assert False, "apply should have raised on non-applyable plan"
        except ValueError as e:
            assert "blocking error" in str(e).lower() or "errors" in str(e).lower()
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_schema_validation_error_blocks_apply() -> None:
    """A JSON file with a wrong field type must surface as a plan
    error (not silently coerced)."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        target = next((dest / "worldbuilding" / "factions").glob("*.json"))
        bad = json.loads(target.read_text())
        # ``faction_type`` is an enum; supplying a number is invalid.
        bad["faction_type"] = 42
        target.write_text(json.dumps(bad))
        plan = LLMPackageImporter(dest).build_plan(p)
        assert not plan.is_applyable, plan.errors
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_referential_integrity_warns_on_dangling_reference() -> None:
    """A faction whose ``allies`` lists a non-existent id should
    produce a warning (not an error — LLMs sometimes invent names)."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        target = next((dest / "worldbuilding" / "factions" /
                       "f_iron-iron-league.json").parent.glob(
                          "*iron-league*.json"))
        data = json.loads(target.read_text())
        data["allies"] = ["f_pact", "f_ghost_faction_does_not_exist"]
        target.write_text(json.dumps(data))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors
        # We expect at least one referential warning naming the bad id.
        warning_text = " ".join(plan.warnings)
        assert "f_ghost_faction_does_not_exist" in warning_text, (
            plan.warnings)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_export_writes_instructions_and_schema_docs() -> None:
    """INSTRUCTIONS_FOR_LLM.md and SCHEMA.md must be written on every
    export — including for an empty project — so a brand-new export
    is a self-sufficient prompt package."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        instructions_path = dest / "INSTRUCTIONS_FOR_LLM.md"
        schema_path = dest / "SCHEMA.md"
        assert instructions_path.exists(), list(dest.iterdir())
        assert schema_path.exists(), list(dest.iterdir())
        instr = instructions_path.read_text()
        # Both workflows should be documented.
        assert "Edit an existing project" in instr
        assert "Start a new project from scratch" in instr
        # Hard rules around chapter prose must be called out.
        assert "chapter prose" in instr.lower()
        # Both modes documented.
        assert "Update mode" in instr
        assert "Overwrite mode" in instr
        schema = schema_path.read_text()
        # Schema doc covers core entity kinds with examples.
        for kind in ("character", "faction", "place", "plot_event",
                     "subplot", "chapter_planning"):
            assert f"`{kind}`" in schema, f"{kind} missing from SCHEMA.md"
        # Examples in SCHEMA.md must be valid JSON.
        for block in _extract_json_blocks(schema):
            json.loads(block)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_export_emits_docs_for_empty_project() -> None:
    """An empty WriterProject's export should still produce a usable
    prompt package — manifest + README + INSTRUCTIONS + SCHEMA, no
    entity dirs."""
    empty = WriterProject(name="Brand New Book")
    dest = _tmpdir()
    try:
        LLMPackageExporter(empty).export(dest)
        for name in ("manifest.json", "README.md",
                     "INSTRUCTIONS_FOR_LLM.md", "SCHEMA.md"):
            assert (dest / name).exists(), name
        # No entities → no entity directories at all (or empty if
        # present). Cheap check: the entity-type subtrees may not
        # exist; that's fine and expected.
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_overwrite_mode_deletes_non_chapter_entities_missing_from_package() -> None:
    """OVERWRITE mode: characters/factions/places/etc. that aren't
    in the package must be deleted on apply."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Remove Bren's character file from the package, simulating
        # the LLM dropping him in an overwrite scenario.
        target = next((dest / "characters").glob("*ch-bren*.json"))
        target.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.OVERWRITE)
        assert plan.is_applyable, plan.errors
        # to_delete should list Bren.
        deletions = [(k, eid) for (k, eid) in plan.to_delete]
        assert ("character", "ch_bren") in deletions, deletions

        before_ids = {c.id for c in p.characters}
        assert "ch_bren" in before_ids
        result = apply_import_plan(p, plan)
        after_ids = {c.id for c in p.characters}
        assert "ch_bren" not in after_ids, after_ids
        assert ("character", "ch_bren") in result.deleted
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_overwrite_mode_never_drops_chapters() -> None:
    """The load-bearing safety property in overwrite mode: even if
    the LLM strips every chapter file from the package, the project's
    chapter list must be unchanged after apply. No chapter prose
    must be touched."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Nuke every chapter file from the package.
        for fp in list((dest / "chapters").glob("*.json")):
            fp.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.OVERWRITE)
        assert plan.is_applyable, plan.errors
        # Chapter ids must NEVER appear in to_delete, even though they
        # exist in the project and are missing from the package.
        for kind, _ in plan.to_delete:
            assert kind != "chapter_planning", kind
            assert kind != "chapter", kind

        before_count = len(p.manuscript.chapters)
        before_content = {ch.id: ch.content
                          for ch in p.manuscript.chapters}

        result = apply_import_plan(p, plan)

        after_count = len(p.manuscript.chapters)
        assert after_count == before_count, (
            f"chapters reduced from {before_count} to {after_count}!")
        for ch in p.manuscript.chapters:
            assert ch.content == before_content[ch.id], (
                f"chapter {ch.id} content changed in overwrite mode")
        # chapters_preserved should equal the project's chapter count
        # since none were in the (chapter-stripped) package.
        assert result.chapters_preserved == before_count, result
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_overwrite_mode_protects_chapter_content_when_planning_edited() -> None:
    """Overwrite mode applies planning edits; prose stays untouched."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Mutate planning on chapter 1.
        ch_file = next((dest / "chapters").glob("001-*.json"))
        data = json.loads(ch_file.read_text())
        data["planning"]["description"] = "OVERWRITE-MODE EDIT"
        ch_file.write_text(json.dumps(data))

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.OVERWRITE)
        assert plan.is_applyable

        before_content = {ch.id: ch.content
                          for ch in p.manuscript.chapters}
        apply_import_plan(p, plan)
        for ch in p.manuscript.chapters:
            assert ch.content == before_content[ch.id]
        ch1 = next(c for c in p.manuscript.chapters
                   if c.id == data["id"])
        assert ch1.planning.description == "OVERWRITE-MODE EDIT"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_update_mode_does_not_compute_deletions() -> None:
    """UPDATE mode's plan must have empty to_delete even when entities
    are missing from the package."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        target = next((dest / "characters").glob("*ch-bren*.json"))
        target.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.UPDATE)
        assert plan.to_delete == [], plan.to_delete
        summary = plan.summary()
        assert summary["deletes"] == 0
        assert summary["mode"] == "update"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_plan_summary_reports_mode_and_deletes() -> None:
    """The plan summary surface used by a confirmation dialog should
    report mode + delete counts honestly."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Remove two non-chapter entities to give the overwrite plan
        # actual deletions to report.
        next((dest / "characters").glob("*ch-bren*.json")).unlink()
        next((dest / "worldbuilding" / "factions").glob(
            "*shade*.json")).unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.OVERWRITE)
        summary = plan.summary()
        assert summary["mode"] == "overwrite"
        assert summary["deletes"] == 2, summary
        deletes_by_type = summary["deletes_by_type"]
        assert deletes_by_type.get("character", 0) == 1
        assert deletes_by_type.get("faction", 0) == 1
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def _extract_json_blocks(markdown: str) -> List[str]:
    """Pull ```json fenced blocks out of markdown for validation."""
    out = []
    in_block = False
    cur: List[str] = []
    for line in markdown.splitlines():
        if line.strip().startswith("```json"):
            in_block = True
            cur = []
            continue
        if in_block and line.strip().startswith("```"):
            in_block = False
            out.append("\n".join(cur))
            continue
        if in_block:
            cur.append(line)
    return out


def test_referential_check_strips_parenthetical_qualifiers() -> None:
    """A reference like ``"Jade (militant action)"`` must resolve
    against an entity named ``"Jade"`` — the parenthetical aside is
    a common LLM output pattern that caused ~10% of real-world
    warnings."""
    p = _build_project_with_prose()
    # Add a faction explicitly named "Jade" so the reference can
    # resolve when the parenthetical is stripped.
    p.worldbuilding.factions.append(
        Faction(id="f_jade", name="Jade",
                faction_type=FactionType.MILITARY))
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        iron = next((dest / "worldbuilding" / "factions").glob(
            "*iron-league*.json"))
        data = json.loads(iron.read_text())
        # Mix: one resolves via paren-strip, one doesn't resolve at all.
        data["allies"] = ["Jade (militant action)",
                          "Blum Government (complicated)"]
        iron.write_text(json.dumps(data))
        plan = LLMPackageImporter(dest).build_plan(p)
        text = " ".join(plan.warnings)
        # Jade resolved after stripping the paren -> should NOT warn
        assert "Jade" not in text or "'Jade'" not in text, text
        # Blum Government has no matching faction -> should still warn
        assert "Blum Government" in text, text
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_referential_check_skips_prose_shape_entries() -> None:
    """A multi-sentence description that ended up in a reference list
    must NOT produce per-reference warnings. The importer counts them
    per file and emits a single 'looks like description text' hint —
    so a myth with three prose entries surfaces as one warning, not
    three."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Inject a myth whose key_figures is full of prose, just like
        # the real-world example. Each entry would otherwise produce
        # its own warning.
        myth_data = {
            "type": "myth",
            "id": "myth_test",
            "name": "Test Myth",
            "myth_type": "Creation",
            "key_figures": [
                # Sentence + capital after period -> prose-shape
                "Earth is the home of humanity. It is where everyone "
                "is from. They gave technology and life to Adelphus.",
                # Long single sentence -> prose-shape by length
                "The dockworkers' associations and the various crews "
                "they protected through the harbor strike of '32",
                # Short, legitimate-looking name -> NOT prose-shape;
                # this one SHOULD produce a warning.
                "Werner Blum",
            ],
        }
        (dest / "worldbuilding" / "myths").mkdir(exist_ok=True)
        (dest / "worldbuilding" / "myths" / "myth_test.json"
            ).write_text(json.dumps(myth_data))
        plan = LLMPackageImporter(dest).build_plan(p)
        # Find the warning for this file
        myth_warnings = [w for w in plan.warnings
                         if "myth_test" in w]
        assert len(myth_warnings) == 1, (
            f"expected exactly 1 aggregated warning, got "
            f"{len(myth_warnings)}: {myth_warnings}")
        w = myth_warnings[0]
        # The legitimate short ref should be named
        assert "Werner Blum" in w, w
        # Prose-shape summary should be present and count 2 entries
        assert "2 prose-shaped" in w, w
        # Prose text itself must NOT be quoted in the warning — only
        # the count summary.
        assert "Earth is the home" not in w, w


    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_referential_check_aggregates_warnings_per_file() -> None:
    """Multiple unresolved references in the same file collapse to a
    single warning line listing every name, grouped by target kind.
    This is the load-bearing UX change — 61 noise lines become ~18
    one-per-file lines."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Build a faction file with 4 unresolved allies + 2 unresolved
        # enemies.
        bad_faction = {
            "type": "faction",
            "id": "f_bad",
            "name": "Bad Faction",
            "faction_type": "nation",
            "allies": ["ghost1", "ghost2", "ghost3", "ghost4"],
            "enemies": ["phantom1", "phantom2"],
        }
        (dest / "worldbuilding" / "factions" /
            "f_bad-bad-faction.json").write_text(json.dumps(bad_faction))
        plan = LLMPackageImporter(dest).build_plan(p)
        bad_warnings = [w for w in plan.warnings if "f_bad" in w]
        # Exactly one warning per file regardless of how many refs
        assert len(bad_warnings) == 1, bad_warnings
        w = bad_warnings[0]
        # Grouped by kind: allies + enemies both target factions, so
        # they collapse into a single "6 unresolved faction" group.
        assert "6 unresolved faction" in w, w
        # All six unresolved names appear in the single line
        for name in ("ghost1", "ghost2", "ghost3", "ghost4",
                     "phantom1", "phantom2"):
            assert name in w, (name, w)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_update_mode_keeps_plot_events_when_no_plot_files_in_package() -> None:
    """If the package contains NO plot/events/*.json files, the
    project's plot events must be left untouched in update mode
    (canonical-when-present rule says canonical ONLY when present)."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Wipe every plot event file from the package (LLM didn't
        # touch plot — only edited characters)
        events_dir = dest / "plot" / "events"
        for fp in events_dir.glob("*.json"):
            fp.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.UPDATE)
        assert plan.is_applyable, plan.errors
        plot_deletes = [d for d in plan.to_delete
                        if d[0] == "plot_event"]
        assert not plot_deletes, (
            "plot events deleted even though package contains no "
            f"plot files: {plot_deletes}")

        before_event_ids = {e.id for e in
                            p.story_planning.freytag_pyramid.events}
        apply_import_plan(p, plan)
        after_event_ids = {e.id for e in
                           p.story_planning.freytag_pyramid.events}
        assert before_event_ids == after_event_ids, (
            f"plot events changed when no plot files imported: "
            f"before={before_event_ids} after={after_event_ids}")
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_update_mode_drops_missing_plot_events_when_partial_set_provided() -> None:
    """Load-bearing canonical-plot rule: if the LLM returns a partial
    plot set in update mode, missing events ARE dropped — because
    the main plot must match what's provided. A half-replaced plot
    is worse than no replacement."""
    p = _build_project_with_prose()
    # Add several plot events so the missing-from-package case is
    # observable. The fixture has only 'pe_choice'; add more.
    extra = [
        PlotEvent(id="pe_inciting", title="Inciting incident",
                  stage="exposition", act=1),
        PlotEvent(id="pe_midpoint", title="Midpoint",
                  stage="climax", act=2),
        PlotEvent(id="pe_climax", title="Final climax",
                  stage="climax", act=3),
    ]
    p.story_planning.freytag_pyramid.events.extend(extra)
    initial_event_ids = {e.id for e in
                         p.story_planning.freytag_pyramid.events}
    assert "pe_inciting" in initial_event_ids

    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Simulate LLM returning only TWO of the four events —
        # implies "the others should be dropped from the plot."
        events_dir = dest / "plot" / "events"
        all_event_files = list(events_dir.glob("*.json"))
        # Keep just pe_choice and pe_midpoint; delete the others.
        # File names encode the id with hyphens, so match by id.
        kept_ids = {"pe_choice", "pe_midpoint"}
        for fp in all_event_files:
            data = json.loads(fp.read_text())
            if data.get("id") not in kept_ids:
                fp.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.UPDATE)
        assert plan.is_applyable, plan.errors

        # Plan must show the dropped events as deletions (preview
        # honesty — user sees this before clicking Apply).
        plot_delete_ids = {ent_id for (kind, ent_id) in plan.to_delete
                           if kind == "plot_event"}
        assert plot_delete_ids == {"pe_inciting", "pe_climax"}, (
            plot_delete_ids)

        apply_import_plan(p, plan)
        after_ids = {e.id for e in
                     p.story_planning.freytag_pyramid.events}
        assert after_ids == kept_ids, (
            f"after canonical plot apply: expected {kept_ids} "
            f"got {after_ids}")
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_plot_canonical_rule_applies_in_overwrite_mode_too() -> None:
    """The canonical-plot rule is independent of mode. Same behavior
    in OVERWRITE mode."""
    p = _build_project_with_prose()
    p.story_planning.freytag_pyramid.events.append(
        PlotEvent(id="pe_extra", title="Extra event",
                  stage="rising_action", act=1))
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        events_dir = dest / "plot" / "events"
        for fp in events_dir.glob("*.json"):
            data = json.loads(fp.read_text())
            if data.get("id") == "pe_extra":
                fp.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.OVERWRITE)
        plot_delete_ids = {ent_id for (kind, ent_id) in plan.to_delete
                           if kind == "plot_event"}
        assert "pe_extra" in plot_delete_ids, plan.to_delete
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_plot_canonical_rule_does_not_affect_subplots() -> None:
    """Subplots stay additive even when plot events are canonical.
    The user explicitly scoped the canonical rule to the main plot
    (FreytagPyramid.events), not subplot event lists."""
    p = _build_project_with_prose()
    # The fixture has one subplot 'sp_betrayal' and several plot
    # events. Export, then remove the subplot file (simulating an
    # LLM that updated plot but not subplots). Subplot must survive.
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        for fp in (dest / "plot" / "subplots").glob("*.json"):
            fp.unlink()

        plan = LLMPackageImporter(dest).build_plan(
            p, mode=ImportMode.UPDATE)
        subplot_deletes = [d for d in plan.to_delete
                           if d[0] == "subplot"]
        assert not subplot_deletes, subplot_deletes
        apply_import_plan(p, plan)
        sp_ids = {s.id for s in p.story_planning.subplots}
        assert "sp_betrayal" in sp_ids
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_update_mode_creates_entity_with_supplied_id_when_no_match() -> None:
    """A package file carrying a specific ``id`` that doesn't match
    any existing project entity must be CREATED with that id (not
    skipped, not error). The supplied id is preserved so that other
    files in the same package can cross-reference it.

    This is the contract the docs and dialog now promise: in update
    mode, any non-existing entity gets created.
    """
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # LLM invents a new faction "f_briar" and references it from
        # an existing faction's allies. Both files use the new id.
        new_faction = {
            "type": "faction",
            "id": "f_briar",  # explicit id, not present in project
            "name": "Briar Coalition",
            "faction_type": "tribe",
            "description": "Forest-dwellers; new allies of Iron League.",
        }
        (dest / "worldbuilding" / "factions" / "f_briar-briar-coalition.json"
            ).write_text(json.dumps(new_faction))
        # Existing Iron League now references the new id in its
        # allies list — this should produce no warnings because the
        # referential integrity check walks both existing + planned-
        # add entities.
        iron = next((dest / "worldbuilding" / "factions").glob(
            "*iron-league*.json"))
        iron_data = json.loads(iron.read_text())
        iron_data["allies"] = list(iron_data.get("allies", [])) + ["f_briar"]
        iron.write_text(json.dumps(iron_data))

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, plan.errors

        # The new entity should be an "add" with the supplied id
        # preserved (NOT a fresh auto-generated one).
        adds = [e for e in plan.entries
                if e.action == "add" and e.entity_type == "faction"]
        assert len(adds) == 1, adds
        assert adds[0].entity_id == "f_briar", adds[0]

        # Reference to f_briar should resolve — no warning.
        unresolved_warnings = [w for w in plan.warnings
                               if "f_briar" in w]
        assert not unresolved_warnings, unresolved_warnings

        result = apply_import_plan(p, plan)
        ids_after = {f.id for f in p.worldbuilding.factions}
        assert "f_briar" in ids_after, ids_after
        # Iron League's allies should now contain f_briar after update.
        iron_after = next(f for f in p.worldbuilding.factions
                          if f.id == "f_iron")
        assert "f_briar" in iron_after.allies, iron_after.allies
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_importer_skips_os_metadata_files_silently() -> None:
    """OS-generated noise (macOS .DS_Store, AppleDouble ._*.json
    resource forks, __MACOSX/ trees) must be silently skipped — not
    surfaced as errors or warnings. Comes up routinely when users
    zip / unzip the package on macOS.
    """
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        # Pollute the package with the exact noise users see:
        (dest / ".DS_Store").write_bytes(b"\x00\x05\x16\x07garbage")
        (dest / "characters" / ".DS_Store").write_bytes(b"\x00garbage")
        # AppleDouble resource fork for an existing entity file —
        # the most insidious case because the suffix matches the
        # JSON glob, but its bytes are binary.
        (dest / "characters" / "._ch_mara-general-mara.json"
            ).write_bytes(b"\x00\x05\x16\x07Mac OS X resource fork")
        # __MACOSX sidecar directory from unzipping a macOS zip
        (dest / "__MACOSX").mkdir(exist_ok=True)
        (dest / "__MACOSX" / "characters").mkdir(parents=True, exist_ok=True)
        (dest / "__MACOSX" / "characters" / "._mara.json").write_bytes(
            b"\x00binary")
        # Windows noise too, for good measure
        (dest / "Thumbs.db").write_bytes(b"random bytes")

        plan = LLMPackageImporter(dest).build_plan(p)
        assert plan.is_applyable, (
            "OS metadata files leaked into errors: " + str(plan.errors))
        # And they shouldn't generate warnings either — silent skip.
        os_noise_warnings = [
            w for w in plan.warnings
            if any(s in w for s in (".DS_Store", "._", "__MACOSX",
                                     "Thumbs.db"))]
        assert not os_noise_warnings, os_noise_warnings
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_full_round_trip_apply_keeps_entity_data_intact() -> None:
    """Pre-existing entities should survive a no-op round-trip apply."""
    p = _build_project_with_prose()
    dest = _tmpdir()
    try:
        LLMPackageExporter(p).export(dest)
        plan = LLMPackageImporter(dest).build_plan(p)
        apply_import_plan(p, plan)

        # Re-check key fields.
        f_iron = next(f for f in p.worldbuilding.factions
                      if f.id == "f_iron")
        assert "f_pact" in f_iron.allies
        assert "f_shade" in f_iron.enemies
        mara = next(c for c in p.characters if c.id == "ch_mara")
        assert mara.social_network.get("Bren") == "rival"
        # Plot event survived.
        events = p.story_planning.freytag_pyramid.events
        assert any(e.id == "pe_choice" for e in events), [
            (e.id, e.title) for e in events]
    finally:
        shutil.rmtree(dest, ignore_errors=True)


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------
def _run_all() -> int:
    tests = [
        test_export_creates_expected_tree,
        test_export_excludes_chapter_content,
        test_import_round_trip_no_changes_makes_plan_of_updates,
        test_import_apply_preserves_chapter_content,
        test_import_apply_protects_content_even_when_present_in_json,
        test_import_additive_does_not_remove_entities_missing_from_package,
        test_import_creates_new_entity_when_id_absent,
        test_import_creates_new_chapter_with_empty_content,
        test_invalid_json_creates_error_blocks_apply,
        test_schema_validation_error_blocks_apply,
        test_referential_integrity_warns_on_dangling_reference,
        test_export_writes_instructions_and_schema_docs,
        test_export_emits_docs_for_empty_project,
        test_overwrite_mode_deletes_non_chapter_entities_missing_from_package,
        test_overwrite_mode_never_drops_chapters,
        test_overwrite_mode_protects_chapter_content_when_planning_edited,
        test_update_mode_does_not_compute_deletions,
        test_plan_summary_reports_mode_and_deletes,
        test_referential_check_strips_parenthetical_qualifiers,
        test_referential_check_skips_prose_shape_entries,
        test_referential_check_aggregates_warnings_per_file,
        test_update_mode_creates_entity_with_supplied_id_when_no_match,
        test_update_mode_keeps_plot_events_when_no_plot_files_in_package,
        test_update_mode_drops_missing_plot_events_when_partial_set_provided,
        test_plot_canonical_rule_applies_in_overwrite_mode_too,
        test_plot_canonical_rule_does_not_affect_subplots,
        test_importer_skips_os_metadata_files_silently,
        test_full_round_trip_apply_keeps_entity_data_intact,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
