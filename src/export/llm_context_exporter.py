"""Export worldbuilding, plot, characters + chapters to markdown
for LLM context.

Rewritten against the current models — the previous version was
referencing fields that no longer exist (e.g. ``Faction.population``,
``Character.role``, ``Subplot.connection_to_main_plot``,
``ClimatePreset.climate_zones``), so the export crashed with
``AttributeError`` partway through.

This version:
  * Reads only fields the current Pydantic models declare. Every
    optional/legacy access goes through ``getattr(..., default)``
    so future schema drift doesn't crash the whole export.
  * Resolves Faction-ID lists (allies / enemies / faction-owned
    territories) to faction names so the LLM gets human-readable
    relationships, not opaque hex ids.
  * Coerces enum fields to their string ``value`` (so a
    ``FactionType.NATION`` doesn't render as the ugly Python repr).
  * Adds sections that the previous exporter was missing:
      - StoryPlanning: themes, structured theme_details, story
        promises, sustained tensions.
      - Worldbuilding: places, cultures, magic systems, historical
        events, political systems, power hierarchies, armies,
        economies.
      - Character: want / need / lie / ghost / arc / moral code /
        worldview / secret / quirks / speaking style / love
        interests / personality traits — i.e. the modern arc-engine
        fields.
      - Chapters: title + planning outline + per-chapter pov /
        characters / locations / description, so the LLM sees the
        actual story shape.
"""

from pathlib import Path
from typing import Optional, Iterable, Any
from datetime import datetime

from src.models.project import WriterProject


def _val(obj: Any, attr: str, default: Any = None) -> Any:
    """Defensive attribute read — returns ``default`` if missing.

    Lets the exporter survive minor model drift (a renamed field
    on one model won't blow up the whole export). Pydantic raises
    AttributeError on undeclared fields, so a plain ``obj.attr``
    is fragile.
    """
    return getattr(obj, attr, default)


def _enum_value(v: Any) -> str:
    """Coerce an enum / arbitrary value to its display string."""
    if v is None:
        return ""
    inner = getattr(v, "value", v)
    return str(inner)


def _str_or_join(v: Any, sep: str = ", ") -> str:
    """Coerce a model field to a display string.

    Handles the three shapes our pydantic models throw at us:
      * ``None`` → ``""``
      * ``str`` → trimmed
      * ``list`` of items → ``sep``-joined string of stringified items

    Used so the exporter doesn't crash with ``AttributeError: 'list'
    object has no attribute 'strip'`` when a field that USED to be a
    str on an old schema is now a List on the current model (e.g.
    Culture.core_values, Economy.major_industries).
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        parts = [str(x).strip() for x in v if x not in (None, "")]
        return sep.join(p for p in parts if p)
    # Fallback for ints / enums / other scalars.
    return str(v).strip()


def _faction_name_lookup(worldbuilding) -> dict:
    """Build {faction_id: name} so allies/enemies render as names."""
    out: dict = {}
    for f in (_val(worldbuilding, "factions", []) or []):
        fid = _val(f, "id", "") or ""
        name = _str_or_join(_val(f, "name", ""))
        if fid and name:
            out[fid] = name
    return out


def _resolve_faction_ids(ids: Iterable[str], lookup: dict) -> list:
    """Map faction IDs → names, falling back to the raw id."""
    return [lookup.get(i, i) for i in (ids or [])]


class LLMContextExporter:
    """Export project data to markdown format for LLM context."""

    @staticmethod
    def export_to_markdown(
            project: WriterProject,
            output_path: Optional[str] = None) -> str:
        """Export the project as a single LLM-ready markdown bundle."""
        md: list = []

        # Header
        md.append(f"# {_val(project, 'name', '(untitled project)')}")
        md.append(
            f"\n*Exported: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        description = _val(project, "description", "") or ""
        if description:
            md.append(f"\n{description}\n")

        # Brief prose profile (voice / register) so the LLM keeps
        # author voice when generating.
        md.extend(LLMContextExporter._export_prose_profile(
            _val(project, "prose_profile", None)))

        # TOC
        md.append("\n## Table of Contents\n")
        md.append("- [Worldbuilding](#worldbuilding)")
        md.append("- [Plot](#plot)")
        md.append("- [Characters](#characters)")
        md.append("- [Chapters](#chapters)")
        md.append("")

        md.append("\n---\n")
        md.append("# Worldbuilding\n")
        md.extend(LLMContextExporter._export_worldbuilding(
            _val(project, "worldbuilding", None)))

        md.append("\n---\n")
        md.append("# Plot\n")
        md.extend(LLMContextExporter._export_plot(
            _val(project, "story_planning", None)))

        md.append("\n---\n")
        md.append("# Characters\n")
        md.extend(LLMContextExporter._export_characters(
            _val(project, "characters", []) or []))

        md.append("\n---\n")
        md.append("# Chapters\n")
        md.extend(LLMContextExporter._export_chapters(
            _val(project, "manuscript", None)))

        markdown = "\n".join(md)
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(markdown, encoding="utf-8")
        return markdown

    # ── Prose profile ─────────────────────────────────────────

    @staticmethod
    def _export_prose_profile(profile) -> list:
        if profile is None:
            return []
        # Profile is a Pydantic model; surface only the fields the
        # LLM benefits from for voice consistency.
        out: list = []
        keys = [
            ("voice", "Voice"),
            ("tone", "Tone"),
            ("register", "Register"),
            ("pacing", "Pacing"),
            ("sentence_style", "Sentence style"),
            ("vocabulary", "Vocabulary"),
            ("perspective", "Perspective"),
        ]
        captured = []
        for key, label in keys:
            v = (_val(profile, key, "") or "").strip()
            if v:
                captured.append(f"- **{label}**: {v}")
        if not captured:
            return []
        out.append("\n## Prose Profile\n")
        out.extend(captured)
        return out

    # ── Worldbuilding ─────────────────────────────────────────

    @staticmethod
    def _export_worldbuilding(worldbuilding) -> list:
        if worldbuilding is None:
            return ["*(no worldbuilding data)*\n"]
        content: list = []
        flookup = _faction_name_lookup(worldbuilding)

        content.extend(LLMContextExporter._export_star_systems(
            worldbuilding))
        content.extend(LLMContextExporter._export_factions(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_cultures(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_political_systems(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_power_hierarchies(
            worldbuilding))
        content.extend(LLMContextExporter._export_armies(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_economies(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_places(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_technologies(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_magic_systems(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_flora(
            worldbuilding))
        content.extend(LLMContextExporter._export_fauna(
            worldbuilding))
        content.extend(LLMContextExporter._export_myths(
            worldbuilding, flookup))
        content.extend(LLMContextExporter._export_climate_presets(
            worldbuilding))
        content.extend(LLMContextExporter._export_history(
            worldbuilding, flookup))
        content.extend(
            LLMContextExporter._export_legacy_text_sections(
                worldbuilding))
        return content

    @staticmethod
    def _export_star_systems(worldbuilding) -> list:
        systems = _val(worldbuilding, "star_systems", []) or []
        if not systems:
            return []
        out = ["## ⭐ Star Systems\n"]
        for system in systems:
            out.append(f"### {_val(system, 'name', '(unnamed)')}")
            out.append(f"- **Type**: "
                       f"{(_val(system, 'system_type', '') or '').title()}")
            for key, label in [
                ("galaxy", "Galaxy"),
                ("location", "Location"),
                ("distance_from_earth", "Distance from Earth"),
            ]:
                v = _val(system, key, "")
                if v:
                    out.append(f"- **{label}**: {v}")
            inner = _val(system, "habitable_zone_inner", "")
            outer = _val(system, "habitable_zone_outer", "")
            if inner or outer:
                out.append(
                    f"- **Habitable Zone**: "
                    f"{inner or '?'} – {outer or '?'}")
            stars = _val(system, "stars", []) or []
            if stars:
                out.append(f"\n**Stars**: {len(stars)}")
                for star in stars:
                    spec = _val(star, "spectral_class", "Unknown")
                    out.append(
                        f"  - {_val(star, 'name', '(unnamed)')} "
                        f"({spec})")
            planets = _val(system, "planets", []) or []
            if planets:
                out.append(f"\n**Planets**: {len(planets)}")
                for planet in planets:
                    pt = _enum_value(
                        _val(planet, "planet_type", None)
                    ).replace("_", " ").title() or "Unknown"
                    out.append(
                        f"  - **{_val(planet, 'name', '(unnamed)')}** "
                        f"({pt})")
                    desc = _str_or_join(_val(planet, "description", ""))
                    if desc:
                        out.append(f"    - Description: {desc}")
                    pop = _val(planet, "population", None)
                    if pop is not None:
                        try:
                            out.append(
                                f"    - Population: {int(pop):,}")
                        except (TypeError, ValueError):
                            out.append(f"    - Population: {pop}")
                    zones = _val(planet, "climate_zones", []) or []
                    if zones:
                        names = [
                            _val(z, "zone_name", "") or _val(z, "name", "")
                            for z in zones
                        ]
                        out.append(
                            f"    - Climate Zones: "
                            f"{', '.join(filter(None, names))}")
                    flora_n = len(_val(planet, "flora_species", []) or [])
                    fauna_n = len(_val(planet, "fauna_species", []) or [])
                    if flora_n:
                        out.append(f"    - Flora Species: {flora_n} species")
                    if fauna_n:
                        out.append(f"    - Fauna Species: {fauna_n} species")
            kf = _str_or_join(_val(system, "key_facts", ""))
            if kf:
                out.append(f"\n**Key Facts**:\n{kf}")
            sd = _str_or_join(_val(system, "description", ""))
            if sd:
                out.append(f"\n{sd}")
            sn = _str_or_join(_val(system, "notes", ""))
            if sn:
                out.append(f"\n**Notes**: {sn}")
            out.append("")
        return out

    @staticmethod
    def _export_factions(worldbuilding, flookup: dict) -> list:
        factions = _val(worldbuilding, "factions", []) or []
        if not factions:
            return []
        out = ["## ⚔️ Factions\n"]
        for f in factions:
            out.append(f"### {_val(f, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(f, 'faction_type', None))}")
            for key, label in [
                ("government_type", "Government"),
                ("leader", "Leader"),
                ("capital", "Capital"),
                ("founded_date", "Founded"),
            ]:
                v = _val(f, key, "")
                if v:
                    out.append(f"- **{label}**: {v}")
            territory = _val(f, "territory", []) or []
            if territory:
                out.append(
                    f"- **Territory**: {', '.join(territory)}")
            ms = _val(f, "military_strength", 0) or 0
            ep = _val(f, "economic_power", 0) or 0
            if ms or ep:
                out.append(
                    f"- **Power**: military {ms}/100, economic "
                    f"{ep}/100")
            resources = _val(f, "resources", {}) or {}
            if resources:
                rs = ", ".join(f"{k}: {v}"
                                for k, v in resources.items())
                out.append(f"- **Resources**: {rs}")
            desc = _str_or_join(_val(f, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            allies = _resolve_faction_ids(
                _val(f, "allies", []) or [], flookup)
            enemies = _resolve_faction_ids(
                _val(f, "enemies", []) or [], flookup)
            if allies or enemies:
                out.append("\n**Relationships**:")
                if allies:
                    out.append(
                        f"- Allies: {', '.join(allies)}")
                if enemies:
                    out.append(
                        f"- Enemies: {', '.join(enemies)}")
            notes = _str_or_join(_val(f, "notes", ""))
            if notes:
                out.append(f"\n**Notes**: {notes}")
            out.append("")
        return out

    @staticmethod
    def _export_cultures(worldbuilding, flookup: dict) -> list:
        cultures = _val(worldbuilding, "cultures", []) or []
        if not cultures:
            return []
        out = ["## 🎭 Cultures\n"]
        for c in cultures:
            out.append(f"### {_val(c, 'name', '(unnamed)')}")
            # Free-text scalar fields.
            for key, label in [
                ("social_structure", "Social structure"),
                ("family_structure", "Family structure"),
                ("gender_roles", "Gender roles"),
                ("coming_of_age", "Coming of age"),
                ("historical_influences",
                 "Historical influences"),
            ]:
                v = _str_or_join(_val(c, key, ""))
                if v:
                    out.append(f"- **{label}**: {v}")
            # List[str] fields — flat join.
            for key, label in [
                ("core_values", "Core values"),
                ("taboos", "Taboos"),
            ]:
                v = _str_or_join(_val(c, key, []))
                if v:
                    out.append(f"- **{label}**: {v}")
            # List-of-objects: just surface count + names.
            for key, label in [
                ("rituals", "Rituals"),
                ("languages", "Languages"),
                ("music_styles", "Music styles"),
                ("art_forms", "Art forms"),
                ("traditions", "Traditions"),
                ("cuisines", "Cuisines"),
            ]:
                items = _val(c, key, []) or []
                if not items:
                    continue
                names = [
                    _str_or_join(_val(it, "name", ""))
                    for it in items
                ]
                names = [n for n in names if n]
                if names:
                    out.append(
                        f"- **{label}** ({len(items)}): "
                        f"{', '.join(names)}")
                else:
                    out.append(f"- **{label}**: {len(items)}")
            # Faction/planet/culture associations — resolve where
            # we can, otherwise pass the id through.
            af = _resolve_faction_ids(
                _val(c, "associated_factions", []) or [], flookup)
            if af:
                out.append(
                    f"- **Associated factions**: {', '.join(af)}")
            ap = _val(c, "associated_planets", []) or []
            if ap:
                out.append(
                    f"- **Associated planets**: {', '.join(ap)}")
            origin = _val(c, "origin_location", "")
            if origin:
                out.append(f"- **Origin**: {origin}")
            nc = _val(c, "neighboring_cultures", []) or []
            if nc:
                out.append(
                    f"- **Neighboring cultures**: "
                    f"{', '.join(nc)}")
            desc = _str_or_join(_val(c, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            notes = _str_or_join(_val(c, "notes", ""))
            if notes:
                out.append(f"\n**Notes**: {notes}")
            out.append("")
        return out

    @staticmethod
    def _export_political_systems(
            worldbuilding, flookup: dict) -> list:
        items = _val(worldbuilding, "political_systems", []) or []
        if not items:
            return []
        out = ["## 🏛️ Political Systems\n"]
        for p in items:
            # PoliticalSystem uses ``id`` AS the display name
            # (the model's id field is "Name of the political
            # system, e.g. 'The Republic of Valoria'").
            display_name = (
                _val(p, "name", "")
                or _val(p, "id", "")
                or "(unnamed)")
            out.append(f"### {display_name}")
            fid = _val(p, "faction_id", "") or ""
            if fid:
                out.append(
                    f"- **Faction**: {flookup.get(fid, fid)}")
            stype = _str_or_join(_val(p, "system_type", ""))
            if stype:
                out.append(f"- **Type**: {stype}")
            ruling = _str_or_join(_val(p, "ruling_party", ""))
            if ruling:
                out.append(f"- **Ruling party**: {ruling}")
            opp = _str_or_join(
                _val(p, "opposition_parties", []))
            if opp:
                out.append(f"- **Opposition**: {opp}")
            constitution = _str_or_join(
                _val(p, "constitution", ""))
            if constitution:
                out.append(
                    f"- **Constitution**: {constitution}")
            branches = _val(p, "branches", []) or []
            if branches:
                names = [
                    f"{_val(b, 'name', '(unnamed)')}"
                    f" ({_val(b, 'branch_type', '')})".rstrip(" ()")
                    for b in branches
                ]
                out.append(
                    f"- **Branches** ({len(branches)}): "
                    f"{', '.join(names)}")
            desc = _str_or_join(_val(p, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_power_hierarchies(worldbuilding) -> list:
        items = _val(worldbuilding, "hierarchies", []) or []
        if not items:
            return []
        out = ["## 👑 Power Hierarchies\n"]
        for h in items:
            out.append(f"### {_val(h, 'name', '(unnamed)')}")
            desc = _str_or_join(_val(h, "description", ""))
            if desc:
                out.append(desc)
            out.append("")
        return out

    @staticmethod
    def _export_armies(worldbuilding, flookup: dict) -> list:
        items = _val(worldbuilding, "armies", []) or []
        if not items:
            return []
        out = ["## ⚔️ Armies\n"]
        for a in items:
            out.append(f"### {_val(a, 'name', '(unnamed)')}")
            fid = _val(a, "faction_id", "") or ""
            if fid:
                out.append(
                    f"- **Faction**: {flookup.get(fid, fid)}")
            ts = _val(a, "total_strength", None)
            if ts is not None:
                try:
                    out.append(
                        f"- **Total strength**: {int(ts):,}")
                except (TypeError, ValueError):
                    out.append(f"- **Total strength**: {ts}")
            branches = _val(a, "branches", []) or []
            if branches:
                names = [
                    _str_or_join(_val(b, "name", ""))
                    for b in branches
                ]
                names = [n for n in names if n]
                if names:
                    out.append(
                        f"- **Branches** ({len(branches)}): "
                        f"{', '.join(names)}")
                else:
                    out.append(
                        f"- **Branches**: {len(branches)}")
            allies = _resolve_faction_ids(
                _val(a, "allies", []) or [], flookup)
            if allies:
                out.append(
                    f"- **Allies**: {', '.join(allies)}")
            enemies = _resolve_faction_ids(
                _val(a, "enemies", []) or [], flookup)
            if enemies:
                out.append(
                    f"- **Enemies**: {', '.join(enemies)}")
            for key, label in [
                ("active_conflicts", "Active conflicts"),
                ("victories", "Notable victories"),
                ("defeats", "Notable defeats"),
            ]:
                v = _str_or_join(_val(a, key, []))
                if v:
                    out.append(f"- **{label}**: {v}")
            desc = _str_or_join(_val(a, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_economies(worldbuilding, flookup: dict) -> list:
        items = _val(worldbuilding, "economies", []) or []
        if not items:
            return []
        out = ["## 💰 Economies\n"]
        for e in items:
            out.append(f"### {_val(e, 'name', '(unnamed)')}")
            fid = _val(e, "faction_id", "") or ""
            if fid:
                out.append(
                    f"- **Faction**: {flookup.get(fid, fid)}")
            etype = _enum_value(_val(e, "economy_type", ""))
            if etype:
                out.append(
                    f"- **Type**: "
                    f"{etype.replace('_', ' ').title()}")
            currency = _str_or_join(_val(e, "currency", ""))
            if currency:
                out.append(f"- **Currency**: {currency}")
            gdp = _val(e, "gdp", None)
            if gdp is not None:
                try:
                    out.append(f"- **GDP**: {float(gdp):,.0f}")
                except (TypeError, ValueError):
                    out.append(f"- **GDP**: {gdp}")
            # Real field is ``major_industries`` (the previous
            # exporter referenced ``primary_industries``).
            mi = _str_or_join(_val(e, "major_industries", []))
            if mi:
                out.append(f"- **Major industries**: {mi}")
            tp = _resolve_faction_ids(
                _val(e, "trade_partners", []) or [], flookup)
            if tp:
                out.append(
                    f"- **Trade partners**: {', '.join(tp)}")
            emb = _resolve_faction_ids(
                _val(e, "embargoes", []) or [], flookup)
            if emb:
                out.append(
                    f"- **Embargoes against**: {', '.join(emb)}")
            goods = _val(e, "goods", []) or []
            if goods:
                names = [
                    _str_or_join(_val(g, "name", ""))
                    for g in goods
                ]
                names = [n for n in names if n]
                if names:
                    out.append(
                        f"- **Notable goods** ({len(goods)}): "
                        f"{', '.join(names[:10])}"
                        f"{'…' if len(names) > 10 else ''}")
                else:
                    out.append(f"- **Notable goods**: {len(goods)}")
            routes = _val(e, "trade_routes", []) or []
            if routes:
                out.append(
                    f"- **Trade routes**: {len(routes)}")
            desc = _str_or_join(_val(e, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_places(worldbuilding, flookup: dict) -> list:
        places = _val(worldbuilding, "places", []) or []
        if not places:
            return []
        out = ["## 📍 Places & Landmarks\n"]
        for p in places:
            out.append(f"### {_val(p, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(p, 'place_type', '')).replace('_', ' ').title()}")
            for key, label in [
                ("planet", "Planet"),
                ("continent", "Continent"),
                ("region", "Region"),
                ("size", "Size"),
            ]:
                v = _val(p, key, "")
                if v:
                    out.append(f"- **{label}**: {v}")
            cf_id = _val(p, "controlling_faction", "") or ""
            if cf_id:
                out.append(
                    f"- **Controlled by**: "
                    f"{flookup.get(cf_id, cf_id)}")
            contested = _resolve_faction_ids(
                _val(p, "contested_by", []) or [], flookup)
            if contested:
                out.append(
                    f"- **Contested by**: {', '.join(contested)}")
            kf = _val(p, "key_features", []) or []
            if kf:
                out.append(
                    f"- **Key features**: {', '.join(kf)}")
            pop = _val(p, "population", None)
            if pop is not None:
                try:
                    out.append(f"- **Population**: {int(pop):,}")
                except (TypeError, ValueError):
                    out.append(f"- **Population**: {pop}")
            desc = _str_or_join(_val(p, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_technologies(worldbuilding, flookup: dict) -> list:
        techs = _val(worldbuilding, "technologies", []) or []
        if not techs:
            return []
        out = ["## 🔬 Technologies\n"]
        for t in techs:
            out.append(f"### {_val(t, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(t, 'technology_type', '')).replace('_', ' ').title()}")
            tech_level = _val(t, "tech_level", "")
            if tech_level:
                out.append(f"- **Level**: {tech_level}")
            gc = _val(t, "game_changing_level", 0) or 0
            ds = _val(t, "destructive_level", 0) or 0
            out.append(f"- **Impact**: {gc}/100 game-changing, "
                       f"{ds}/100 destructive")
            cost = _str_or_join(_val(t, "cost_to_build", ""))
            if cost:
                out.append(f"- **Cost to build**: {cost}")
            access = _resolve_faction_ids(
                _val(t, "factions_with_access", []) or [], flookup)
            if access:
                out.append(
                    f"- **Factions with access**: "
                    f"{', '.join(access)}")
            inv = _val(t, "inventor_faction", "") or ""
            if inv:
                out.append(
                    f"- **Inventor faction**: "
                    f"{flookup.get(inv, inv)}")
            desc = _str_or_join(_val(t, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            limits = _str_or_join(_val(t, "limitations", ""))
            if limits:
                out.append(f"\n**Limitations**: {limits}")
            sr = _str_or_join(_val(t, "story_relevance", ""))
            if sr:
                out.append(f"\n**Story relevance**: {sr}")
            out.append("")
        return out

    @staticmethod
    def _export_magic_systems(worldbuilding, flookup: dict) -> list:
        systems = _val(worldbuilding, "magic_systems", []) or []
        if not systems:
            return []
        out = ["## ✨ Magic Systems\n"]
        for s in systems:
            out.append(f"### {_val(s, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(s, 'magic_type', ''))}")
            for key, label in [
                ("source", "Source"),
                ("rules", "Rules"),
                ("limitations", "Limitations"),
                ("costs", "Costs"),
                ("who_can_use", "Who can use"),
                ("training", "Training"),
                ("power_levels", "Power levels"),
                ("cultural_perception", "Cultural perception"),
            ]:
                v = (_val(s, key, "") or "").strip()
                if v:
                    out.append(f"- **{label}**: {v}")
            desc = _str_or_join(_val(s, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            sr = _str_or_join(_val(s, "story_relevance", ""))
            if sr:
                out.append(f"\n**Story relevance**: {sr}")
            out.append("")
        return out

    @staticmethod
    def _export_flora(worldbuilding) -> list:
        flora_list = _val(worldbuilding, "flora", []) or []
        if not flora_list:
            return []
        out = ["## 🌿 Flora\n"]
        for f in flora_list:
            out.append(f"### {_val(f, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(f, 'flora_type', '')).replace('_', ' ').title()}")
            np = _val(f, "native_planets", []) or []
            if np:
                out.append(
                    f"- **Native planets**: {', '.join(np)}")
            climate = _str_or_join(_val(f, "preferred_climate", ""))
            if climate:
                out.append(f"- **Climate**: {climate}")
            properties: list = []
            if _val(f, "edible", False):
                properties.append("Edible")
            if _str_or_join(_val(f, "medicinal_properties", "")):
                properties.append("Medicinal")
            if _str_or_join(_val(f, "toxicity", "")):
                properties.append("Toxic")
            if _str_or_join(_val(f, "magical_properties", "")):
                properties.append("Magical")
            if properties:
                out.append(
                    f"- **Properties**: {', '.join(properties)}")
            desc = _str_or_join(_val(f, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_fauna(worldbuilding) -> list:
        fauna_list = _val(worldbuilding, "fauna", []) or []
        if not fauna_list:
            return []
        out = ["## 🦁 Fauna\n"]
        for fa in fauna_list:
            out.append(f"### {_val(fa, 'name', '(unnamed)')}")
            out.append(
                f"- **Type**: "
                f"{_enum_value(_val(fa, 'fauna_type', '')).replace('_', ' ').title()}")
            np = _val(fa, "native_planets", []) or []
            if np:
                out.append(
                    f"- **Native planets**: {', '.join(np)}")
            danger = _val(fa, "danger_level", None)
            if danger is not None:
                try:
                    d = int(danger)
                    label = ("Harmless" if d < 30
                             else "Moderate" if d < 70
                             else "Dangerous")
                    out.append(
                        f"- **Danger level**: {label} ({d}/100)")
                except (TypeError, ValueError):
                    pass
            for key, label in [
                ("diet", "Diet"),
                ("behavior", "Behavior"),
                ("social_structure", "Social structure"),
                ("intelligence_level", "Intelligence"),
                ("domestication_status", "Domestication"),
            ]:
                v = (_val(fa, key, "") or "").strip()
                if v:
                    out.append(f"- **{label}**: {v}")
            desc = _str_or_join(_val(fa, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_myths(worldbuilding, flookup: dict) -> list:
        myths = _val(worldbuilding, "myths", []) or []
        if not myths:
            return []
        out = ["## 📖 Mythology\n"]
        for m in myths:
            out.append(f"### {_val(m, 'name', '(unnamed)')}")
            mt = _val(m, "myth_type", "")
            if mt:
                out.append(f"- **Type**: {mt}")
            af_ids = _val(m, "associated_factions", []) or []
            af_names = _resolve_faction_ids(af_ids, flookup)
            if af_names:
                out.append(
                    f"- **Believed by**: {', '.join(af_names)}")
            kf = _val(m, "key_figures", []) or []
            if kf:
                out.append(
                    f"- **Key figures**: {', '.join(kf)}")
            tp = _str_or_join(_val(m, "time_period", ""))
            if tp:
                out.append(f"- **Time period**: {tp}")
            desc = _str_or_join(_val(m, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            moral = _str_or_join(_val(m, "moral_lesson", ""))
            if moral:
                out.append(f"\n**Moral**: {moral}")
            out.append("")
        return out

    @staticmethod
    def _export_climate_presets(worldbuilding) -> list:
        presets = _val(worldbuilding, "climate_presets", []) or []
        if not presets:
            return []
        out = ["## 🌤️ Climate Presets\n"]
        for p in presets:
            out.append(f"### {_val(p, 'name', '(unnamed)')}")
            # The model field is ``default_zones`` (the previous
            # exporter referenced ``climate_zones``, which doesn't
            # exist on ClimatePreset and would have crashed).
            zones = _val(p, "default_zones", []) or []
            if zones:
                out.append("\n**Default zones**:")
                for z in zones:
                    out.append(f"- {z}")
            tr = _val(p, "temperature_range", "")
            if tr:
                out.append(f"- **Temperature**: {tr}")
            ac = _val(p, "atmospheric_composition", "")
            if ac:
                out.append(f"- **Atmosphere**: {ac}")
            wp = _str_or_join(_val(p, "weather_patterns", ""))
            if wp:
                out.append(f"- **Weather**: {wp}")
            desc = _str_or_join(_val(p, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            out.append("")
        return out

    @staticmethod
    def _export_history(worldbuilding, flookup: dict) -> list:
        events = _val(worldbuilding, "historical_events", []) or []
        if not events:
            return []
        out = ["## 📜 Historical Timeline\n"]
        for e in events:
            out.append(
                f"### {_val(e, 'name', '(unnamed)')} "
                f"({_val(e, 'date', '')})")
            et = _val(e, "event_type", "")
            if et:
                out.append(f"- **Type**: {et}")
            kf = _val(e, "key_figures", []) or []
            if kf:
                out.append(
                    f"- **Key figures**: {', '.join(kf)}")
            fi_ids = _val(e, "factions_involved", []) or []
            fi_names = _resolve_faction_ids(fi_ids, flookup)
            if fi_names:
                out.append(
                    f"- **Factions involved**: "
                    f"{', '.join(fi_names)}")
            loc = _val(e, "location", "")
            if loc:
                out.append(f"- **Location**: {loc}")
            desc = _str_or_join(_val(e, "description", ""))
            if desc:
                out.append(f"\n{desc}")
            cons = _str_or_join(_val(e, "consequences", ""))
            if cons:
                out.append(f"\n**Consequences**: {cons}")
            out.append("")
        return out

    @staticmethod
    def _export_legacy_text_sections(worldbuilding) -> list:
        """Surface legacy free-text worldbuilding fields if filled.

        Old projects stored worldbuilding as long-form text in
        ``mythology`` / ``politics`` / ``history`` / etc. before the
        structured objects landed. We surface them here so legacy
        content isn't silently dropped from the export.
        """
        legacy_keys = [
            ("mythology", "Mythology (legacy notes)"),
            ("planets", "Planets (legacy notes)"),
            ("climate", "Climate (legacy notes)"),
            ("history", "History (legacy notes)"),
            ("politics", "Politics (legacy notes)"),
            ("military", "Military (legacy notes)"),
            ("economy", "Economy (legacy notes)"),
            ("power_hierarchy", "Power hierarchy (legacy notes)"),
        ]
        present = [(k, label) for k, label in legacy_keys
                   if (_val(worldbuilding, k, "") or "").strip()]
        if not present:
            return []
        out = ["## 📝 Legacy Notes\n"]
        for key, label in present:
            out.append(f"### {label}")
            out.append((_val(worldbuilding, key, "") or "").strip())
            out.append("")
        # Custom user sections
        custom = _val(worldbuilding, "custom_sections", {}) or {}
        for name, body in custom.items():
            body = (body or "").strip()
            if not body:
                continue
            out.append(f"### {name} (custom)")
            out.append(body)
            out.append("")
        return out

    # ── Plot ──────────────────────────────────────────────────

    @staticmethod
    def _export_plot(story_planning) -> list:
        if story_planning is None:
            return ["*(no story planning)*\n"]
        content: list = []

        # Main plot
        mp = _str_or_join(_val(story_planning, "main_plot", ""))
        if mp:
            content.append("## Main Plot\n")
            content.append(mp)
            content.append("")

        # Themes (legacy List[str])
        themes = _val(story_planning, "themes", []) or []
        themes = [t for t in themes if (t or "").strip()]
        if themes:
            content.append("## Themes\n")
            for t in themes:
                content.append(f"- {t}")
            content.append("")

        # Theme details (rich)
        theme_details = _val(
            story_planning, "theme_details", []) or []
        if theme_details:
            content.append("## Thematic Threads\n")
            for td in theme_details:
                title = _val(td, "title", "") or _val(td, "name", "")
                content.append(f"### {title or '(untitled theme)'}")
                stmt = _str_or_join(_val(td, "statement", ""))
                if stmt:
                    content.append(f"*Statement*: {stmt}")
                desc = _str_or_join(_val(td, "description", ""))
                if desc:
                    content.append(desc)
                motifs = _val(td, "motifs", []) or []
                if motifs:
                    content.append(
                        f"- **Motifs**: {', '.join(motifs)}")
                content.append("")

        # Promises to readers
        promises = _val(story_planning, "promises", []) or []
        if promises:
            content.append("## Reader Promises\n")
            for p in promises:
                title = _val(p, "title", "") or "(untitled)"
                ptype = _val(p, "promise_type", "")
                line = (f"- **{title}** ({ptype})"
                        if ptype else f"- **{title}**")
                content.append(line)
                desc = _str_or_join(_val(p, "description", ""))
                if desc:
                    content.append(f"  - {desc}")
            content.append("")

        # Sustained tensions
        tensions = _val(story_planning, "tensions", []) or []
        if tensions:
            content.append("## Sustained Tensions\n")
            for t in tensions:
                title = _val(t, "title", "") or _val(t, "name", "")
                content.append(f"### {title or '(untitled)'}")
                forces = _val(t, "forces", []) or []
                if forces:
                    content.append(
                        f"- **Forces**: {', '.join(forces)}")
                desc = _str_or_join(_val(t, "description", ""))
                if desc:
                    content.append(desc)
                content.append("")

        # Freytag pyramid
        pyramid = _val(story_planning, "freytag_pyramid", None)
        if pyramid is not None:
            content.append("## Story Structure (Freytag's Pyramid)\n")
            events = _val(pyramid, "events", []) or []
            if events:
                stages = {
                    "exposition": [],
                    "rising_action": [],
                    "climax": [],
                    "falling_action": [],
                    "resolution": [],
                }
                for ev in events:
                    s = _val(ev, "stage", "")
                    if s in stages:
                        stages[s].append(ev)
                stage_names = {
                    "exposition": "Exposition",
                    "rising_action": "Rising Action",
                    "climax": "Climax",
                    "falling_action": "Falling Action",
                    "resolution": "Resolution",
                }
                for stage_key, stage_name in stage_names.items():
                    content.append(f"### {stage_name}\n")
                    bucket = sorted(
                        stages[stage_key],
                        key=lambda e: _val(e, "sort_order", 0))
                    if bucket:
                        for ev in bucket:
                            intensity = (
                                _val(ev, "intensity", 0) or 0)
                            bar = "🔥" * (intensity // 20)
                            content.append(
                                f"**{_val(ev, 'title', '(untitled)')}** "
                                f"{bar}".rstrip())
                            d = _str_or_join(_val(ev, "description", ""))
                            if d:
                                content.append(d)
                            outcome = _str_or_join(_val(ev, "outcome", ""))
                            if outcome:
                                content.append(f"*Outcome: {outcome}*")
                            content.append("")
                    else:
                        legacy = (_val(pyramid, stage_key, "") or "").strip()
                        if legacy:
                            content.append(legacy)
                            content.append("")
            else:
                # No structured events — use legacy text fields.
                for stage_key, stage_name in [
                    ("exposition", "Exposition"),
                    ("rising_action", "Rising Action"),
                    ("climax", "Climax"),
                    ("falling_action", "Falling Action"),
                    ("resolution", "Resolution"),
                ]:
                    legacy = (_val(pyramid, stage_key, "") or "").strip()
                    if legacy:
                        content.append(f"### {stage_name}\n")
                        content.append(legacy)
                        content.append("")

        # Subplots — model field is ``connection_to_main``, not
        # ``connection_to_main_plot`` (the previous exporter
        # referenced the latter and silently rendered nothing).
        subplots = _val(story_planning, "subplots", []) or []
        if subplots:
            content.append("## Subplots\n")
            for sp in subplots:
                content.append(f"### {_val(sp, 'title', '(untitled)')}")
                status = _val(sp, "status", "")
                if status:
                    content.append(f"*Status: {status}*")
                conn = _str_or_join(_val(sp, "connection_to_main", ""))
                if conn:
                    content.append(
                        f"\n**Connection to main plot**: {conn}")
                desc = _str_or_join(_val(sp, "description", ""))
                if desc:
                    content.append(f"\n{desc}")
                rc = _val(sp, "related_characters", []) or []
                if rc:
                    content.append(
                        f"\n**Related characters**: {', '.join(rc)}")
                events = _val(sp, "events", []) or []
                if events:
                    content.append(f"\n**Events** ({len(events)}):")
                    for ev in events:
                        content.append(
                            f"- {_val(ev, 'title', '(untitled)')}")
                content.append("")

        return content

    # ── Characters ────────────────────────────────────────────

    @staticmethod
    def _export_characters(characters) -> list:
        if not characters:
            return ["*(no characters defined)*\n"]
        content: list = []
        # Build name lookup so love-interest character_ids resolve
        # to readable names instead of opaque hex.
        name_lookup = {
            _val(c, "id", ""): _val(c, "name", "")
            for c in characters
        }
        for c in characters:
            content.append(f"## {_val(c, 'name', '(unnamed)')}\n")
            ctype = _str_or_join(_val(c, "character_type", ""))
            if ctype:
                content.append(f"**Role**: {ctype.title()}")

            # Core arc-engine fields (the modern character schema).
            for key, label in [
                ("want", "Want (external goal)"),
                ("need", "Need (internal truth)"),
                ("lie_they_believe", "Lie they believe"),
                ("ghost", "Ghost (formative wound)"),
                ("character_arc", "Arc"),
                ("moral_code", "Moral code"),
                ("worldview", "Worldview"),
                ("secret", "Secret"),
                ("contradictions", "Contradictions"),
                ("defining_relationship", "Defining relationship"),
                ("quirks", "Quirks"),
                ("speaking_style", "Speaking style"),
                ("emotional_baseline", "Emotional baseline"),
                ("motivations", "Motivations"),
                ("fears", "Fears"),
            ]:
                v = (_val(c, key, "") or "").strip()
                if v:
                    content.append(f"\n**{label}**: {v}")

            traits = _val(c, "personality_traits", []) or []
            if traits:
                content.append(
                    f"\n**Personality traits**: {', '.join(traits)}")

            # Free-text blocks
            for key, header in [
                ("physical_description", "Physical Description"),
                ("personality", "Personality (notes)"),
                ("backstory", "Backstory"),
                ("notes", "Notes"),
            ]:
                v = (_val(c, key, "") or "").strip()
                if v:
                    content.append(f"\n### {header}\n")
                    content.append(v)

            # Social network — modern field is ``social_network``
            # (Dict[str, str]). The previous exporter referenced
            # ``relationships`` which doesn't exist on Character.
            sn = _val(c, "social_network", {}) or {}
            if sn:
                content.append("\n### Social Network\n")
                for who, how in sn.items():
                    content.append(f"- **{who}**: {how}")

            # Love interests — list of LoveInterest, refer to
            # other characters by id.
            love = _val(c, "love_interests", []) or []
            if love:
                content.append("\n### Love Interests\n")
                for li in love:
                    other_id = _val(li, "character_id", "") or ""
                    other = (
                        name_lookup.get(other_id) or other_id
                        or "(unspecified)")
                    rel = _val(li, "relationship_type", "") or ""
                    status = _val(li, "status", "") or ""
                    head = (
                        f"- **{other}** "
                        f"({rel}{', ' + status if status else ''})")
                    content.append(head.strip())
                    desc = _str_or_join(_val(li, "description", ""))
                    if desc:
                        content.append(f"  - {desc}")
                    tension = _str_or_join(_val(li, "tension", ""))
                    if tension:
                        content.append(f"  - *Tension*: {tension}")

            content.append("\n---\n")
        return content

    # ── Chapters ──────────────────────────────────────────────

    @staticmethod
    def _export_chapters(manuscript) -> list:
        chapters = _val(manuscript, "chapters", []) or []
        if not chapters:
            return ["*(no chapters yet)*\n"]
        content: list = []
        for ch in chapters:
            num = _val(ch, "number", 0) or 0
            title = _str_or_join(_val(ch, "title", "")) \
                or "(untitled)"
            content.append(f"## Chapter {num}: {title}\n")
            wc = _val(ch, "word_count", 0) or 0
            if wc:
                content.append(f"*Word count*: {wc:,}\n")
            planning = _val(ch, "planning", None)
            if planning is not None:
                pov = _str_or_join(_val(planning, "pov_character", ""))
                if pov:
                    content.append(f"- **POV**: {pov}")
                feat = _val(
                    planning, "characters_featured", []) or []
                if feat:
                    content.append(
                        f"- **Featured characters**: "
                        f"{', '.join(feat)}")
                locs = _val(planning, "locations", []) or []
                if locs:
                    content.append(
                        f"- **Locations**: {', '.join(locs)}")
                tp = _str_or_join(_val(planning, "timeline_position", ""))
                if tp:
                    content.append(f"- **Timeline**: {tp}")
                pdesc = _str_or_join(_val(planning, "description", ""))
                if pdesc:
                    content.append(f"\n**Summary**: {pdesc}")
                outline = _str_or_join(_val(planning, "outline", ""))
                if outline:
                    content.append("\n**Outline**:\n")
                    content.append(outline)
            content.append("\n---\n")
        return content
