"""Knowledge graph layer over WriterProject entities.

Wraps the existing Pydantic worldbuilding/character/plot objects as a
``networkx.MultiDiGraph`` so retrieval can be enriched with explicit
relationships (allies, controls, inhabits, social_tie, prerequisite_of,
etc.) without changing the underlying data model.

The graph is rebuilt from project state on demand — it is not persisted.
That keeps it cheap and avoids staleness bugs when the user edits an
entity.

Public surface:
    kg = KnowledgeGraph()
    kg.build_from_project(project)
    kg.neighbors(("faction", faction_id), hops=1)
    kg.format_edges_for_context([("faction", faction_id)])
    kg.resolve(name_or_id) -> Optional[(type, id)]
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx


# A node is identified by (entity_type, entity_id). Keeping the tuple
# stable means edges remain valid even if two entity types happen to
# share an ID string.
NodeKey = Tuple[str, str]


class KnowledgeGraph:
    """A typed multi-edge graph of project entities and their relations."""

    def __init__(self) -> None:
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        # Name -> NodeKey, lowercased + stripped. Used to resolve the
        # many string fields in the model that store *either* an ID
        # *or* a display name (e.g. Place.controlling_faction).
        self._name_index: Dict[str, NodeKey] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def build_from_project(self, project: Any) -> None:
        """Walk the project and populate nodes + edges.

        Each builder step is wrapped so one malformed entity cannot
        prevent the rest of the graph from being built.
        """
        self.graph.clear()
        self._name_index.clear()

        # Two passes: first register every entity as a node so the name
        # index is complete, then add edges. Otherwise edge endpoints
        # added before their owning entity would be marked unresolved.
        self._add_all_nodes(project)
        self._add_all_edges(project)

    def _add_all_nodes(self, project: Any) -> None:
        wb = getattr(project, "worldbuilding", None)

        node_sources: List[Tuple[str, Iterable[Any]]] = []
        if wb is not None:
            node_sources.extend([
                ("faction", getattr(wb, "factions", []) or []),
                ("place", getattr(wb, "places", []) or []),
                ("technology", getattr(wb, "technologies", []) or []),
                ("culture", getattr(wb, "cultures", []) or []),
                ("myth", getattr(wb, "myths", []) or []),
                ("historical_event",
                 getattr(wb, "historical_events", []) or []),
                ("flora", getattr(wb, "flora", []) or []),
                ("fauna", getattr(wb, "fauna", []) or []),
                ("star_system", getattr(wb, "star_systems", []) or []),
                ("army", getattr(wb, "armies", []) or []),
                ("economy", getattr(wb, "economies", []) or []),
                ("political_system",
                 getattr(wb, "political_systems", []) or []),
            ])

        node_sources.append(
            ("character", getattr(project, "characters", []) or []))

        sp = getattr(project, "story_planning", None)
        if sp is not None:
            fp = getattr(sp, "freytag_pyramid", None)
            if fp is not None:
                node_sources.append(
                    ("plot_event", getattr(fp, "events", []) or []))
            node_sources.append(
                ("subplot", getattr(sp, "subplots", []) or []))

        for ntype, items in node_sources:
            for item in items:
                try:
                    self._add_node_from_obj(ntype, item)
                except Exception:
                    continue

    def _add_node_from_obj(self, ntype: str, obj: Any) -> Optional[NodeKey]:
        ent_id = getattr(obj, "id", None)
        if not ent_id:
            # plot_event / subplot use title; some have id but the name
            # field is "title" not "name". We still need *something*
            # stable for the node key.
            ent_id = getattr(obj, "title", None) or getattr(obj, "name", None)
        if not ent_id:
            return None
        name = getattr(obj, "name", None) or getattr(obj, "title", None) or ent_id
        key: NodeKey = (ntype, str(ent_id))
        self.graph.add_node(
            key,
            name=name,
            entity_type=ntype,
            entity_id=str(ent_id),
            unresolved=False,
        )
        self._register_name(name, key)
        self._register_name(str(ent_id), key)
        return key

    def _register_name(self, name: Any, key: NodeKey) -> None:
        if not name:
            return
        norm = str(name).strip().lower()
        if norm and norm not in self._name_index:
            self._name_index[norm] = key

    # ------------------------------------------------------------------
    # Edge construction
    # ------------------------------------------------------------------
    def _add_all_edges(self, project: Any) -> None:
        wb = getattr(project, "worldbuilding", None)
        builders = [
            lambda: self._edges_factions(wb),
            lambda: self._edges_places(wb),
            lambda: self._edges_technologies(wb),
            lambda: self._edges_cultures(wb),
            lambda: self._edges_myths(wb),
            lambda: self._edges_historical_events(wb),
            lambda: self._edges_species(wb),
            lambda: self._edges_characters(project),
            lambda: self._edges_plot(project),
        ]
        for builder in builders:
            try:
                builder()
            except Exception:
                # Individual builder failures are logged via print to
                # match the rebuild_index() pattern in enhanced_rag.py.
                continue

    def _edges_factions(self, wb: Any) -> None:
        if wb is None:
            return
        for faction in getattr(wb, "factions", []) or []:
            src = ("faction", faction.id)
            for ally in getattr(faction, "allies", []) or []:
                self._add_edge(src, ally, "ally_of", target_type="faction")
            for enemy in getattr(faction, "enemies", []) or []:
                self._add_edge(src, enemy, "enemy_of", target_type="faction")
            leader = getattr(faction, "leader", None)
            if leader:
                self._add_edge(src, leader, "led_by", target_type="character")
            for territory in getattr(faction, "territory", []) or []:
                self._add_edge(src, territory, "controls",
                               target_type="place")
            capital = getattr(faction, "capital", None)
            if capital:
                self._add_edge(src, capital, "capital_at",
                               target_type="place")

    def _edges_places(self, wb: Any) -> None:
        if wb is None:
            return
        for place in getattr(wb, "places", []) or []:
            src = ("place", place.id)
            cf = getattr(place, "controlling_faction", None)
            if cf:
                self._add_edge(src, cf, "controlled_by",
                               target_type="faction")
            for contested in getattr(place, "contested_by", []) or []:
                self._add_edge(src, contested, "contested_by",
                               target_type="faction")
            for owner in getattr(place, "historical_owners", []) or []:
                self._add_edge(src, owner, "historical_owner",
                               target_type="faction")
            for connected in getattr(place, "connected_places", []) or []:
                self._add_edge(src, connected, "connects_to",
                               target_type="place")
            for inhabitant in (
                    getattr(place, "notable_inhabitants", []) or []):
                self._add_edge(src, inhabitant, "inhabited_by",
                               target_type="character")
            for species in getattr(place, "species_present", []) or []:
                # Could be flora or fauna — try fauna first, then flora.
                resolved = self._resolve_with_fallback(
                    species, ["fauna", "flora"])
                if resolved is not None:
                    self.graph.add_edge(
                        src, resolved, key="hosts_species",
                        relation="hosts_species")
                else:
                    self._add_edge(src, species, "hosts_species",
                                   target_type="fauna")
            for event_id in getattr(place, "historical_events", []) or []:
                self._add_edge(src, event_id, "site_of",
                               target_type="historical_event")

    def _edges_technologies(self, wb: Any) -> None:
        if wb is None:
            return
        for tech in getattr(wb, "technologies", []) or []:
            src = ("technology", tech.id)
            for faction in getattr(tech, "factions_with_access", []) or []:
                self._add_edge(src, faction, "available_to",
                               target_type="faction")
            inventor = getattr(tech, "inventor_faction", None)
            if inventor:
                self._add_edge(src, inventor, "invented_by",
                               target_type="faction")
            for prereq in getattr(tech, "prerequisites", []) or []:
                self._add_edge(src, prereq, "requires",
                               target_type="technology")

    def _edges_cultures(self, wb: Any) -> None:
        if wb is None:
            return
        for culture in getattr(wb, "cultures", []) or []:
            src = ("culture", culture.id)
            for faction in (
                    getattr(culture, "associated_factions", []) or []):
                self._add_edge(src, faction, "practiced_by",
                               target_type="faction")
            for neighbor in (
                    getattr(culture, "neighboring_cultures", []) or []):
                self._add_edge(src, neighbor, "neighbor_of",
                               target_type="culture")

    def _edges_myths(self, wb: Any) -> None:
        if wb is None:
            return
        for myth in getattr(wb, "myths", []) or []:
            src = ("myth", myth.id)
            for faction in (
                    getattr(myth, "associated_factions", []) or []):
                self._add_edge(src, faction, "believed_by",
                               target_type="faction")
            for figure in getattr(myth, "key_figures", []) or []:
                self._add_edge(src, figure, "features",
                               target_type="character")

    def _edges_historical_events(self, wb: Any) -> None:
        if wb is None:
            return
        for event in getattr(wb, "historical_events", []) or []:
            src = ("historical_event", event.id)
            for figure in getattr(event, "key_figures", []) or []:
                self._add_edge(src, figure, "involves",
                               target_type="character")
            for faction in (
                    getattr(event, "factions_involved", []) or []):
                self._add_edge(src, faction, "involves",
                               target_type="faction")
            location = getattr(event, "location", None)
            if location:
                self._add_edge(src, location, "occurred_at",
                               target_type="place")
            for related in getattr(event, "related_events", []) or []:
                self._add_edge(src, related, "related_to",
                               target_type="historical_event")

    def _edges_species(self, wb: Any) -> None:
        if wb is None:
            return
        for flora in getattr(wb, "flora", []) or []:
            src = ("flora", flora.id)
            for interaction in getattr(flora, "interactions", []) or []:
                target_id = getattr(interaction, "species_id", None) \
                    or getattr(interaction, "species_name", None)
                if not target_id:
                    continue
                rel = (getattr(interaction, "interaction_type", "")
                       or "interacts_with").strip().lower().replace(" ", "_")
                resolved = self._resolve_with_fallback(
                    target_id, ["flora", "fauna"])
                if resolved is not None:
                    self.graph.add_edge(src, resolved, key=rel, relation=rel)
                else:
                    self._add_edge(src, target_id, rel, target_type="fauna")
        for fauna in getattr(wb, "fauna", []) or []:
            src = ("fauna", fauna.id)
            for interaction in getattr(fauna, "interactions", []) or []:
                target_id = getattr(interaction, "species_id", None) \
                    or getattr(interaction, "species_name", None)
                if not target_id:
                    continue
                rel = (getattr(interaction, "interaction_type", "")
                       or "interacts_with").strip().lower().replace(" ", "_")
                resolved = self._resolve_with_fallback(
                    target_id, ["fauna", "flora"])
                if resolved is not None:
                    self.graph.add_edge(src, resolved, key=rel, relation=rel)
                else:
                    self._add_edge(src, target_id, rel, target_type="fauna")

    def _edges_characters(self, project: Any) -> None:
        for char in getattr(project, "characters", []) or []:
            src = ("character", char.id)
            # social_network is a {name: relationship_type} dict
            social = getattr(char, "social_network", None) or {}
            if isinstance(social, dict):
                for other_name, rel_type in social.items():
                    rel = (str(rel_type) if rel_type
                           else "social_tie").strip().lower()
                    self._add_edge(
                        src, other_name, "social_tie",
                        target_type="character",
                        properties={"kind": rel},
                    )
            # love_interests carry character_id explicitly
            for love in getattr(char, "love_interests", []) or []:
                target_id = getattr(love, "character_id", None)
                if not target_id:
                    continue
                self._add_edge(
                    src, target_id, "romantic_with",
                    target_type="character",
                    properties={
                        "kind": getattr(love, "relationship_type", ""),
                        "status": getattr(love, "status", ""),
                    },
                )

    def _edges_plot(self, project: Any) -> None:
        sp = getattr(project, "story_planning", None)
        if sp is None:
            return
        fp = getattr(sp, "freytag_pyramid", None)
        if fp is not None:
            for event in getattr(fp, "events", []) or []:
                ent_id = getattr(event, "id", None) \
                    or getattr(event, "title", None)
                if not ent_id:
                    continue
                src = ("plot_event", str(ent_id))
                for char in (
                        getattr(event, "related_characters", []) or []):
                    self._add_edge(src, char, "involves",
                                   target_type="character")
                for sub in getattr(event, "related_subplots", []) or []:
                    self._add_edge(src, sub, "in_subplot",
                                   target_type="subplot")
        for subplot in getattr(sp, "subplots", []) or []:
            ent_id = getattr(subplot, "id", None) \
                or getattr(subplot, "title", None)
            if not ent_id:
                continue
            src = ("subplot", str(ent_id))
            for char in (
                    getattr(subplot, "related_characters", []) or []):
                self._add_edge(src, char, "involves",
                               target_type="character")

    # ------------------------------------------------------------------
    # Edge / node helpers
    # ------------------------------------------------------------------
    def _add_edge(
        self,
        src: NodeKey,
        target_id_or_name: str,
        relation: str,
        target_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an edge, resolving target by name or ID.

        If the target cannot be resolved against any existing entity,
        a placeholder node is created with ``unresolved=True`` and the
        ``target_type`` guess so that downstream consumers can still
        surface the relationship to the LLM (just without rich
        metadata).
        """
        if not target_id_or_name:
            return
        target = self.resolve(target_id_or_name, prefer_type=target_type)
        if target is None:
            target = (target_type, f"unresolved::{str(target_id_or_name)}")
            if target not in self.graph:
                self.graph.add_node(
                    target,
                    name=str(target_id_or_name),
                    entity_type=target_type,
                    entity_id=str(target_id_or_name),
                    unresolved=True,
                )
                self._register_name(target_id_or_name, target)
        attrs = {"relation": relation}
        if properties:
            attrs.update(properties)
        # MultiDiGraph: keying edges by relation lets us keep parallel
        # relations between the same two nodes (e.g., A is both ally_of
        # and trades_with B) without collision.
        self.graph.add_edge(src, target, key=relation, **attrs)

    def resolve(
        self,
        name_or_id: str,
        prefer_type: Optional[str] = None,
    ) -> Optional[NodeKey]:
        """Find a node by ID or display name.

        ``prefer_type`` is checked first: if ``(prefer_type, name_or_id)``
        is in the graph, that wins. Otherwise we look up via the
        lowercased name index. Returns ``None`` if nothing matches.
        """
        if not name_or_id:
            return None
        s = str(name_or_id).strip()
        if not s:
            return None
        if prefer_type:
            candidate: NodeKey = (prefer_type, s)
            if candidate in self.graph:
                return candidate
        norm = s.lower()
        return self._name_index.get(norm)

    def _resolve_with_fallback(
        self,
        name_or_id: str,
        type_order: List[str],
    ) -> Optional[NodeKey]:
        for t in type_order:
            r = self.resolve(name_or_id, prefer_type=t)
            if r is not None:
                return r
        return self.resolve(name_or_id)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------
    def neighbors(
        self,
        node: NodeKey,
        hops: int = 1,
        relations: Optional[Iterable[str]] = None,
        types: Optional[Iterable[str]] = None,
        include_incoming: bool = True,
    ) -> List[Tuple[NodeKey, List[Tuple[NodeKey, str]]]]:
        """Return nodes within ``hops`` of ``node`` with their edge path.

        Each result is ``(neighbor, [(intermediate, relation), ...])``.
        The seed node itself is excluded. Relation/type filters apply
        to *each step* of the path.
        """
        if node not in self.graph:
            return []
        rel_set = set(relations) if relations else None
        type_set = set(types) if types else None

        results: Dict[NodeKey, List[Tuple[NodeKey, str]]] = {}
        # BFS up to `hops` steps. We track the path so callers can
        # render "A --r1--> B --r2--> C" if they want.
        frontier: List[Tuple[NodeKey, List[Tuple[NodeKey, str]]]] = [
            (node, [])]
        seen: Set[NodeKey] = {node}
        for _ in range(max(1, hops)):
            next_frontier: List[
                Tuple[NodeKey, List[Tuple[NodeKey, str]]]] = []
            for current, path in frontier:
                # Outgoing edges
                for _, target, key, data in self.graph.out_edges(
                        current, keys=True, data=True):
                    relation = data.get("relation", key)
                    if rel_set and relation not in rel_set:
                        continue
                    if type_set and target[0] not in type_set:
                        continue
                    new_path = path + [(target, relation)]
                    if target not in seen:
                        seen.add(target)
                        results[target] = new_path
                        next_frontier.append((target, new_path))
                if include_incoming:
                    for source, _, key, data in self.graph.in_edges(
                            current, keys=True, data=True):
                        relation = data.get("relation", key)
                        if rel_set and relation not in rel_set:
                            continue
                        if type_set and source[0] not in type_set:
                            continue
                        # Prefix "<-" so the caller can see direction.
                        new_path = path + [(source, f"<-{relation}")]
                        if source not in seen:
                            seen.add(source)
                            results[source] = new_path
                            next_frontier.append((source, new_path))
            frontier = next_frontier
            if not frontier:
                break
        return [(n, p) for n, p in results.items()]

    def edges_of(
        self,
        node: NodeKey,
        include_incoming: bool = True,
    ) -> List[Tuple[str, NodeKey, Dict[str, Any]]]:
        """All edges touching ``node`` as ``(relation, other, attrs)``.

        Outgoing edges return the target as ``other``; incoming edges
        return the source as ``other`` and prefix the relation with
        ``"<-"``.
        """
        if node not in self.graph:
            return []
        out: List[Tuple[str, NodeKey, Dict[str, Any]]] = []
        for _, target, key, data in self.graph.out_edges(
                node, keys=True, data=True):
            relation = data.get("relation", key)
            out.append((relation, target, dict(data)))
        if include_incoming:
            for source, _, key, data in self.graph.in_edges(
                    node, keys=True, data=True):
                relation = data.get("relation", key)
                out.append((f"<-{relation}", source, dict(data)))
        return out

    # Source types we know how to graph-annotate. Useful for callers
    # that want to early-skip lookup on passage-like types (encyclopedia
    # chunks, chapter prose, themes) where there is no single entity.
    ANNOTATABLE_TYPES = frozenset({
        "faction", "place", "technology", "culture", "myth",
        "historical_event", "flora", "fauna", "star_system",
        "economy", "political_system", "character", "plot_event",
        "subplot",
    })

    def format_relations_line(
        self,
        entity_type: str,
        entity_id: str,
        max_edges: int = 8,
        include_incoming: bool = False,
    ) -> str:
        """Compact one-line render of a node's edges.

        Returns "" when the entity isn't in the graph (e.g. a passage
        chunk, or an entity whose source_type isn't graph-annotatable)
        or has no edges. Format: "rel -> Name; rel -> Name; ..."
        """
        if not entity_type or not entity_id:
            return ""
        if entity_type not in self.ANNOTATABLE_TYPES:
            return ""
        node = (entity_type, entity_id)
        if node not in self.graph:
            return ""
        edges = self.edges_of(node, include_incoming=include_incoming)
        if not edges:
            return ""
        fragments = []
        for relation, other, _attrs in edges[:max_edges]:
            other_name = self.graph.nodes[other].get("name", other[1])
            fragments.append(f"{relation} -> {other_name}")
        return "; ".join(fragments)

    def format_edges_for_context(
        self,
        seeds: Iterable[NodeKey],
        hops: int = 1,
        max_edges_per_seed: int = 12,
    ) -> List[str]:
        """Render relationships for a set of seed nodes as prompt lines.

        Produces compact, LLM-readable lines per seed:
            "Iron League: ally_of -> Stoneforge Pact; controls -> Highveld;
             led_by -> General Mara; <-believed_by -> Iron Faith"

        The cap (``max_edges_per_seed``) keeps the prompt from blowing
        up when an entity has many connections.
        """
        lines: List[str] = []
        for seed in seeds:
            if seed not in self.graph:
                continue
            seed_name = self.graph.nodes[seed].get("name", seed[1])
            if hops <= 1:
                edges = self.edges_of(seed)
                fragments = []
                for relation, other, _attrs in edges[:max_edges_per_seed]:
                    other_name = self.graph.nodes[other].get(
                        "name", other[1])
                    fragments.append(f"{relation} -> {other_name}")
                if fragments:
                    lines.append(f"{seed_name}: " + "; ".join(fragments))
            else:
                neighbors = self.neighbors(seed, hops=hops)
                fragments = []
                for neighbor, path in neighbors[:max_edges_per_seed]:
                    rendered = []
                    for step_node, step_rel in path:
                        step_name = self.graph.nodes[step_node].get(
                            "name", step_node[1])
                        rendered.append(f"{step_rel} -> {step_name}")
                    fragments.append(" => ".join(rendered))
                if fragments:
                    lines.append(f"{seed_name}: " + "; ".join(fragments))
        return lines

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """Counts useful for sanity-checking the build."""
        nodes_by_type: Dict[str, int] = {}
        unresolved = 0
        for _, data in self.graph.nodes(data=True):
            t = data.get("entity_type", "unknown")
            nodes_by_type[t] = nodes_by_type.get(t, 0) + 1
            if data.get("unresolved"):
                unresolved += 1
        edges_by_relation: Dict[str, int] = {}
        for _, _, data in self.graph.edges(data=True):
            r = data.get("relation", "unknown")
            edges_by_relation[r] = edges_by_relation.get(r, 0) + 1
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "nodes_by_type": nodes_by_type,
            "edges_by_relation": edges_by_relation,
            "unresolved_nodes": unresolved,
        }
