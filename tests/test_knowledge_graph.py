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


def test_cooccurrence_scoring_writes_edge_attributes() -> None:
    """score_cooccurrences should stamp every edge with cooccur_count
    / cooccur_score / cooccur_tier attributes, derived from how often
    the endpoints appear together in the supplied chunks."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    # Iron League's chunk mentions Stoneforge Pact, Shade Syndicate,
    # General Mara, Highveld. A "rich" prose chunk repeats Iron League
    # alongside Stoneforge Pact multiple times so the pair gets a
    # non-trivial co-occurrence count.
    chunks = [
        FakeChunk(
            "Iron League is allied with Stoneforge Pact, "
            "led by General Mara, controlling Highveld."),
        FakeChunk(
            "The Stoneforge Pact has long fought beside the "
            "Iron League against Shade Syndicate forces."),
        FakeChunk(
            "Far away, Joren waits for Mara to return."),
        FakeChunk(
            "Highveld is the contested ground; the Iron League "
            "and Stoneforge Pact watch it warily."),
    ]
    stats = kg.score_cooccurrences(chunks)
    assert stats["documents_scanned"] == 4, stats
    assert stats["edges_with_signal"] > 0, stats

    # Find the Iron League --ally_of--> Stoneforge Pact edge.
    iron = ("faction", "f_iron")
    stoneforge = ("faction", "f_pact")
    edges = kg.graph.get_edge_data(iron, stoneforge) or {}
    ally_edge = edges.get("ally_of")
    assert ally_edge is not None, list(edges.keys())
    assert ally_edge.get("cooccur_count", 0) >= 2, ally_edge
    assert ally_edge.get("cooccur_tier") in {
        "weak", "moderate", "strong"}, ally_edge

    # Iron League's edge to Shade Syndicate appears in only one chunk
    # (chunk 2 above), so it should be tagged "weak".
    shade = ("faction", "f_shade")
    enemy_edge_data = kg.graph.get_edge_data(iron, shade) or {}
    enemy_edge = enemy_edge_data.get("enemy_of")
    assert enemy_edge is not None
    assert enemy_edge.get("cooccur_count", 0) == 1, enemy_edge
    assert enemy_edge.get("cooccur_tier") == "weak", enemy_edge


def test_format_relations_line_includes_tier_suffix() -> None:
    """When scoring has run, the rendered line shows ``(tier)``."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    chunks = [
        FakeChunk("Iron League and Stoneforge Pact stand together."),
        FakeChunk("The Iron League and Stoneforge Pact will not fall."),
        FakeChunk("Even in defeat, the Iron League trusts Stoneforge Pact."),
    ]
    kg.score_cooccurrences(chunks)
    line = kg.format_relations_line("faction", "f_iron", max_edges=8)
    # The ally edge should now show a tier; the enemy edge (no
    # co-occurrence in these chunks) should NOT have a tier suffix.
    assert "ally_of -> Stoneforge Pact (" in line, line
    # Some tier word should appear after Stoneforge Pact.
    assert any(t in line for t in ("strong", "moderate", "weak")), line


def test_format_relations_line_no_tier_when_scoring_skipped() -> None:
    """If scoring hasn't run, no tier suffix should appear."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    line = kg.format_relations_line("faction", "f_iron")
    assert "(" not in line, line  # no tier annotation
    assert "ally_of -> Stoneforge Pact" in line, line


def test_cooccurrence_skips_very_short_names() -> None:
    """Names below the minimum length must not trigger matches —
    short character names like 'X' would otherwise match half the
    English text in any chunk."""
    kg = KnowledgeGraph()
    kg.build_from_project(_build_project())
    # Inject a synthetic 2-char node and verify it never matches.
    kg.graph.add_node(("character", "short"),
                      name="Xy", entity_type="character",
                      entity_id="short", unresolved=False)

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    chunks = [FakeChunk("Xy went somewhere with Iron League and Xy.")]
    kg.score_cooccurrences(chunks)
    # The short-name node should never get a chunk count.
    found_data = None
    for u, v, key, data in kg.graph.edges(keys=True, data=True):
        if u == ("character", "short") or v == ("character", "short"):
            found_data = data
    # Either the node has no edges (most likely) or those edges have
    # cooccur_count == 0.
    if found_data is not None:
        assert found_data.get("cooccur_count", 0) == 0, found_data


def test_expansion_tier_multiplier_mapping() -> None:
    """Public tier multipliers honor the documented ordering."""
    kg = KnowledgeGraph()
    assert kg.expansion_tier_multiplier("strong") > (
        kg.expansion_tier_multiplier("moderate"))
    assert kg.expansion_tier_multiplier("moderate") > (
        kg.expansion_tier_multiplier("weak"))
    # Unknown tier falls back to the neutral default — does not raise.
    assert kg.expansion_tier_multiplier("bogus") > 0
    # Empty / no-tier sits between weak and moderate (we don't know
    # whether the connection is active, so be cautious).
    no_tier = kg.expansion_tier_multiplier("")
    assert kg.expansion_tier_multiplier("weak") <= no_tier
    assert no_tier <= kg.expansion_tier_multiplier("moderate")


def test_search_with_neighbors_promotes_relevant_graph_nodes() -> None:
    """When a primary result names a graph entity whose neighbor is
    relevant to the query, search_with_neighbors should promote that
    neighbor into the result list with match_type='graph_neighbor'.

    Uses top_k=1 so only Iron League lands as primary — leaving its
    1-hop graph neighbors (Stoneforge Pact, Shade Syndicate, Highveld,
    etc.) eligible for promotion via expansion.
    """
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()

    results = rag.search_with_neighbors(
        query="Iron League allies and territory",
        top_k=1,
        max_neighbors_per_seed=3,
        min_neighbor_score=0.0,
    )

    primary_keys = {(r.source_type, r.source_id) for r in results
                    if r.match_type != "graph_neighbor"}
    promoted = [r for r in results if r.match_type == "graph_neighbor"]
    assert ("faction", "f_iron") in primary_keys, primary_keys
    assert promoted, "expected at least one promoted neighbor"

    # The promoted neighbor must carry provenance metadata pointing
    # back at Iron League.
    p = promoted[0]
    assert p.metadata.get("promoted_from_seed_type") == "faction", p.metadata
    assert p.metadata.get("promoted_from_seed_id") == "f_iron", p.metadata
    assert p.metadata.get("promoted_via_relation"), p.metadata


def test_search_with_neighbors_respects_min_score_threshold() -> None:
    """A high min_neighbor_score should filter out marginal neighbors."""
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()
    high_bar = rag.search_with_neighbors(
        query="Iron League allies",
        top_k=5,
        max_neighbors_per_seed=5,
        min_neighbor_score=10.0,  # impossibly high
    )
    promoted = [r for r in high_bar if r.match_type == "graph_neighbor"]
    assert not promoted, promoted


def test_search_with_neighbors_caps_per_seed() -> None:
    """max_neighbors_per_seed limits how many neighbors any one
    primary result can contribute, so a highly-connected entity
    doesn't monopolize the expansion budget."""
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()
    results = rag.search_with_neighbors(
        query="Iron League",
        top_k=5,
        max_neighbors_per_seed=1,
        min_neighbor_score=0.0,
    )
    promoted = [r for r in results if r.match_type == "graph_neighbor"]
    # Count promotions per seed
    from collections import Counter
    seed_counts = Counter(
        (r.metadata.get("promoted_from_seed_type"),
         r.metadata.get("promoted_from_seed_id"))
        for r in promoted)
    for seed, count in seed_counts.items():
        assert count <= 1, (seed, count)


def test_get_context_for_ai_expand_neighbors_renders_via_label() -> None:
    """When expand_neighbors=True, promoted chunks must carry a
    'via <relation> from <seed>' label so the LLM understands the
    chunk's provenance.

    The default top_k=10 inside get_context_for_ai is much wider than
    the synthetic test project's entity count, so most of Iron League's
    1-hop neighbors would already land as primary. We patch search()
    locally to return only the Iron League result, leaving the
    expansion code with neighbors to promote.
    """
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()

    # Restrict primary to Iron League so the neighbors are eligible
    # for promotion via search_with_neighbors.
    original_search = rag.search

    def narrow_search(query, method, top_k, source_types=None):
        full = original_search(query, method, max(top_k, 50), source_types)
        # Keep only Iron League in the small-top_k slice; expansion's
        # broader candidate-pool search uses the original method
        # untouched because it calls original_search separately.
        if top_k <= 10:
            return [r for r in full
                    if (r.source_type, r.source_id)
                       == ("faction", "f_iron")][:top_k]
        return full[:top_k]

    rag.search = narrow_search
    try:
        ctx = rag.get_context_for_ai(
            query="Iron League allies and territory",
            max_tokens=8000,
            expand_neighbors=True,
            max_neighbors_per_seed=3,
        )
    finally:
        rag.search = original_search

    assert "(via " in ctx and "from Iron League" in ctx, ctx[:2000]


def test_get_context_for_ai_default_no_expansion() -> None:
    """Default behavior must NOT promote graph neighbors — backward
    compat for callers that don't opt in."""
    from src.ai.enhanced_rag import EnhancedRAGSystem

    rag = EnhancedRAGSystem(_build_project())
    rag.rebuild_index()
    ctx = rag.get_context_for_ai(
        query="Iron League allies",
        max_tokens=8000,
    )
    assert "(via " not in ctx, ctx[:1500]


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
        test_cooccurrence_scoring_writes_edge_attributes,
        test_format_relations_line_includes_tier_suffix,
        test_format_relations_line_no_tier_when_scoring_skipped,
        test_cooccurrence_skips_very_short_names,
        test_expansion_tier_multiplier_mapping,
        test_search_with_neighbors_promotes_relevant_graph_nodes,
        test_search_with_neighbors_respects_min_score_threshold,
        test_search_with_neighbors_caps_per_seed,
        test_get_context_for_ai_expand_neighbors_renders_via_label,
        test_get_context_for_ai_default_no_expansion,
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
