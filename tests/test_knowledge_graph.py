"""Tests for the knowledge graph layer.

Builds a small synthetic WriterProject in-memory and verifies:
  - nodes are created for every entity type with edges defined
  - explicit edges (allies, controls, social_tie, romantic_with,
    prerequisites, species interactions) land on the right targets
  - name-vs-ID mixing is resolved (place.controlling_faction can hold
    either a faction ID or a faction name)
  - format_edges_for_context produces a non-empty line for a connected
    seed
  - EnhancedRAGSystem builds a graph during rebuild_index and
    annotates retrieved entities with their relationships

Run:
    python -m tests.test_knowledge_graph
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Make the repo importable when run directly: `python tests/test_knowledge_graph.py`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.knowledge_graph import KnowledgeGraph  # noqa: E402
from src.models.project import (  # noqa: E402
    Character, LoveInterest, PlotEvent, StoryPlanning, FreytagPyramid,
    Subplot, WorldBuilding, WriterProject,
)
from src.models.worldbuilding_objects import (  # noqa: E402
    Culture, Fauna, FaunaType, Flora, FloraType, Faction, FactionType,
    HistoricalEvent, Myth, Place, PlaceType, SpeciesInteraction,
    Technology, TechnologyType,
)


def _build_project() -> WriterProject:
    """Synthesize a small, fully-linked project for the test.

    Choices below exercise specific edges:
      - Iron League and Stoneforge Pact have a mutual ally edge.
      - Iron League's leader is "General Mara" — a character name, not
        an ID — to verify name resolution.
      - Highveld's controlling_faction is the *name* "Iron League"
        (the field doc says either ID or name is acceptable).
      - Steam Engine requires Furnace (tech prerequisite).
      - Fox preys on Rabbit via SpeciesInteraction.
      - Mara loves Joren (love_interests) and has a social_tie to Bren.
      - Plot event "Mara's Choice" involves Mara.
    """
    faction_a = Faction(
        id="f_iron",
        name="Iron League",
        faction_type=FactionType.NATION,
        leader="General Mara",  # name, not ID
        territory=["Highveld"],
        allies=["f_pact"],
        enemies=["f_shade"],
    )
    faction_b = Faction(
        id="f_pact",
        name="Stoneforge Pact",
        faction_type=FactionType.NATION,
        allies=["f_iron"],
    )
    faction_c = Faction(
        id="f_shade",
        name="Shade Syndicate",
        faction_type=FactionType.CRIMINAL,
    )

    place_a = Place(
        id="p_highveld",
        name="Highveld",
        place_type=PlaceType.REGION,
        controlling_faction="Iron League",  # by name
        notable_inhabitants=["General Mara"],
        connected_places=["p_riverford"],
    )
    place_b = Place(
        id="p_riverford",
        name="Riverford",
        place_type=PlaceType.TOWN,
        controlling_faction="f_iron",  # by ID
    )

    tech_furnace = Technology(
        id="t_furnace",
        name="Furnace",
        technology_type=TechnologyType.MANUFACTURING,
        factions_with_access=["f_iron"],
    )
    tech_steam = Technology(
        id="t_steam",
        name="Steam Engine",
        technology_type=TechnologyType.MANUFACTURING,
        prerequisites=["t_furnace"],
        inventor_faction="Stoneforge Pact",  # by name
    )

    culture = Culture(
        id="c_iron",
        name="Iron Way",
        associated_factions=["f_iron"],
    )

    myth = Myth(
        id="m_forge",
        name="The First Forge",
        myth_type="creation",
        associated_factions=["f_iron"],
        key_figures=["General Mara"],
    )

    event = HistoricalEvent(
        id="h_war",
        name="Highveld War",
        date="Year 102",
        key_figures=["General Mara"],
        factions_involved=["f_iron", "f_shade"],
        location="Highveld",
    )

    rabbit = Fauna(
        id="fa_rabbit",
        name="Rabbit",
        fauna_type=FaunaType.MAMMAL,
    )
    fox = Fauna(
        id="fa_fox",
        name="Fox",
        fauna_type=FaunaType.MAMMAL,
        interactions=[SpeciesInteraction(
            species_id="fa_rabbit",
            species_name="Rabbit",
            interaction_type="preys on",
        )],
    )
    moss = Flora(
        id="fl_moss",
        name="Mountain Moss",
        flora_type=FloraType.MOSS,
    )

    mara = Character(
        id="ch_mara",
        name="General Mara",
        character_type="protagonist",
        social_network={"Bren": "rival"},
        love_interests=[LoveInterest(
            character_id="ch_joren",
            relationship_type="spouse",
            status="active",
        )],
    )
    joren = Character(
        id="ch_joren",
        name="Joren",
        character_type="major",
    )
    bren = Character(
        id="ch_bren",
        name="Bren",
        character_type="major",
    )

    plot_event = PlotEvent(
        id="pe_choice",
        title="Mara's Choice",
        related_characters=["General Mara"],
        related_subplots=["sp_betrayal"],
    )
    subplot = Subplot(
        id="sp_betrayal",
        title="The Betrayal",
        description="Bren's secret loyalty",
        related_characters=["Bren"],
    )

    wb = WorldBuilding(
        factions=[faction_a, faction_b, faction_c],
        places=[place_a, place_b],
        technologies=[tech_furnace, tech_steam],
        cultures=[culture],
        myths=[myth],
        historical_events=[event],
        flora=[moss],
        fauna=[rabbit, fox],
    )
    sp = StoryPlanning(
        freytag_pyramid=FreytagPyramid(events=[plot_event]),
        subplots=[subplot],
    )
    return WriterProject(
        name="Test",
        worldbuilding=wb,
        characters=[mara, joren, bren],
        story_planning=sp,
    )


# ----------------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------------
def test_graph_builds_nodes_for_every_seeded_type() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    stats = kg.stats()
    for t in ("faction", "place", "technology", "culture", "myth",
              "historical_event", "flora", "fauna", "character",
              "plot_event", "subplot"):
        assert stats["nodes_by_type"].get(t, 0) > 0, (
            f"no nodes for type {t!r}; stats={stats}")
    assert stats["unresolved_nodes"] == 0, (
        f"unexpected unresolved placeholder nodes: {stats}")


def test_faction_ally_and_enemy_edges() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    relations = {(r, t) for r, t, _ in kg.edges_of(
        ("faction", "f_iron"), include_incoming=False)}
    assert (("ally_of"), ("faction", "f_pact")) in relations, relations
    assert (("enemy_of"), ("faction", "f_shade")) in relations, relations


def test_leader_resolved_by_character_name() -> None:
    """General Mara is referenced by *name* on the faction; the graph
    should resolve that to the character node, not a placeholder."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    edges = kg.edges_of(("faction", "f_iron"), include_incoming=False)
    led_by = [t for r, t, _ in edges if r == "led_by"]
    assert ("character", "ch_mara") in led_by, edges


def test_place_controlling_faction_resolves_by_name_and_id() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    # Highveld points at "Iron League" (name)
    e_highveld = kg.edges_of(("place", "p_highveld"), include_incoming=False)
    targets = [t for r, t, _ in e_highveld if r == "controlled_by"]
    assert ("faction", "f_iron") in targets, e_highveld
    # Riverford points at "f_iron" (ID)
    e_riverford = kg.edges_of(("place", "p_riverford"), include_incoming=False)
    targets = [t for r, t, _ in e_riverford if r == "controlled_by"]
    assert ("faction", "f_iron") in targets, e_riverford


def test_tech_prerequisite_edge() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    edges = kg.edges_of(("technology", "t_steam"), include_incoming=False)
    assert any(r == "requires" and t == ("technology", "t_furnace")
               for r, t, _ in edges), edges


def test_species_interaction_uses_interaction_type_as_relation() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    edges = kg.edges_of(("fauna", "fa_fox"), include_incoming=False)
    rels = {r for r, _, _ in edges}
    # "preys on" should be normalized to "preys_on"
    assert "preys_on" in rels, rels


def test_character_social_and_romantic_edges() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    edges = kg.edges_of(("character", "ch_mara"), include_incoming=False)
    rels_to = {(r, t) for r, t, _ in edges}
    assert ("social_tie", ("character", "ch_bren")) in rels_to, edges
    assert ("romantic_with", ("character", "ch_joren")) in rels_to, edges
    # Romantic edge should carry the relationship_type as a property
    rom = [d for r, t, d in edges
           if r == "romantic_with" and t == ("character", "ch_joren")]
    assert rom and rom[0].get("kind") == "spouse", rom


def test_plot_event_involves_character_by_name() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    edges = kg.edges_of(("plot_event", "pe_choice"), include_incoming=False)
    targets = [t for r, t, _ in edges if r == "involves"]
    assert ("character", "ch_mara") in targets, edges


def test_format_edges_for_context_is_non_empty() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    lines = kg.format_edges_for_context([("faction", "f_iron")])
    assert lines, "format_edges_for_context returned no lines"
    assert "Iron League" in lines[0], lines


def test_neighbors_two_hops() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    # 1 hop: f_iron -> f_pact (ally). 2 hops: f_pact -> f_iron back
    # (mutual ally), plus other reachable from f_iron.
    nbrs = kg.neighbors(("faction", "f_iron"), hops=2)
    keys = {n for n, _ in nbrs}
    assert ("faction", "f_pact") in keys
    assert ("place", "p_highveld") in keys


def test_format_relations_line_public_method() -> None:
    """Public format_relations_line on KnowledgeGraph is the shared
    rendering primitive used by both EnhancedRAGSystem and the chat
    per-type retrieval path."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    line = kg.format_relations_line("faction", "f_iron", max_edges=8)
    assert line, "expected a non-empty relations line for Iron League"
    assert "ally_of -> Stoneforge Pact" in line, line
    # Non-graph types or unknown IDs return empty string, not None.
    assert kg.format_relations_line("encyclopedia", "x") == ""
    assert kg.format_relations_line("faction", "does_not_exist") == ""
    # max_edges cap is respected.
    short = kg.format_relations_line("faction", "f_iron", max_edges=1)
    assert short.count(";") == 0, short


def test_format_relations_line_with_incoming() -> None:
    """Subplots are the main case for include_incoming=True — plot
    events feed into a subplot via plot_event --in_subplot--> subplot,
    which only shows up if we ask for incoming edges."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    out_only = kg.format_relations_line(
        "subplot", "sp_betrayal", include_incoming=False)
    full = kg.format_relations_line(
        "subplot", "sp_betrayal", include_incoming=True)
    assert full != out_only, (out_only, full)
    # Incoming edge is rendered with a "<-" prefix.
    assert "<-in_subplot" in full, full
    # And the plot event name is present.
    assert "Mara's Choice" in full, full


def test_plot_event_outgoing_includes_subplot_and_character() -> None:
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    line = kg.format_relations_line(
        "plot_event", "pe_choice", max_edges=8)
    assert "involves -> General Mara" in line, line
    assert "in_subplot -> The Betrayal" in line, line


def test_rag_top_chunks_per_type_appends_related_suffix() -> None:
    """The chat-path retrieval (which bypasses get_context_for_ai) now
    annotates each retrieved entity chunk with its graph edges via the
    `(related: ...)` suffix. This test exercises the same code path
    the chat widget uses."""
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()
    results = rag.search(
        query="Iron League allies", top_k=5, source_types=["faction"])
    iron = next((r for r in results if r.source_id == "f_iron"), None)
    assert iron is not None, results
    # The chat path uses kg.format_relations_line directly. Verify it
    # produces the expected suffix content for this result.
    suffix = rag.knowledge_graph.format_relations_line(
        iron.source_type, iron.source_id, max_edges=8)
    assert "ally_of -> Stoneforge Pact" in suffix, suffix


def test_enhanced_rag_annotates_relationships_in_context() -> None:
    """End-to-end: the RAG context for a faction query should include
    a 'Relationships:' line listing the faction's edges."""
    from src.ai.enhanced_rag import EnhancedRAGSystem
    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()
    # The graph should have built alongside the index.
    stats = rag.knowledge_graph.stats()
    assert stats["total_edges"] > 0, stats
    ctx = rag.get_context_for_ai("Iron League allies and territory",
                                 max_tokens=4000)
    assert "[FACTION: Iron League]" in ctx, ctx
    assert "Relationships:" in ctx, ctx
    # Specific edges should appear in the relationships line.
    assert "ally_of -> Stoneforge Pact" in ctx, ctx


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------
def _run_all() -> int:
    tests = [
        test_graph_builds_nodes_for_every_seeded_type,
        test_faction_ally_and_enemy_edges,
        test_leader_resolved_by_character_name,
        test_place_controlling_faction_resolves_by_name_and_id,
        test_tech_prerequisite_edge,
        test_species_interaction_uses_interaction_type_as_relation,
        test_character_social_and_romantic_edges,
        test_plot_event_involves_character_by_name,
        test_format_edges_for_context_is_non_empty,
        test_neighbors_two_hops,
        test_format_relations_line_public_method,
        test_format_relations_line_with_incoming,
        test_plot_event_outgoing_includes_subplot_and_character,
        test_rag_top_chunks_per_type_appends_related_suffix,
        test_enhanced_rag_annotates_relationships_in_context,
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
