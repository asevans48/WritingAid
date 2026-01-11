"""Export worldbuilding, plot, and characters to markdown for LLM context."""

from pathlib import Path
from typing import Optional
from datetime import datetime

from src.models.project import WriterProject


class LLMContextExporter:
    """Export project data to markdown format for LLM context."""

    @staticmethod
    def export_to_markdown(project: WriterProject, output_path: Optional[str] = None) -> str:
        """
        Export worldbuilding, plot, and characters to markdown.

        Args:
            project: The writer project to export
            output_path: Optional path to save the markdown file

        Returns:
            The markdown content as a string
        """
        md_content = []

        # Header
        md_content.append(f"# {project.name}")
        md_content.append(f"\n*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        if project.description:
            md_content.append(f"\n{project.description}\n")

        # Table of Contents
        md_content.append("\n## Table of Contents\n")
        md_content.append("- [Worldbuilding](#worldbuilding)")
        md_content.append("- [Plot](#plot)")
        md_content.append("- [Characters](#characters)")
        md_content.append("")

        # Worldbuilding Section
        md_content.append("\n---\n")
        md_content.append("# Worldbuilding\n")
        md_content.extend(LLMContextExporter._export_worldbuilding(project.worldbuilding))

        # Plot Section
        md_content.append("\n---\n")
        md_content.append("# Plot\n")
        md_content.extend(LLMContextExporter._export_plot(project.story_planning))

        # Characters Section
        md_content.append("\n---\n")
        md_content.append("# Characters\n")
        md_content.extend(LLMContextExporter._export_characters(project.characters))

        # Join all content
        markdown = "\n".join(md_content)

        # Save to file if path provided
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(markdown, encoding='utf-8')

        return markdown

    @staticmethod
    def _export_worldbuilding(worldbuilding) -> list:
        """Export worldbuilding data."""
        content = []

        # Star Systems
        if hasattr(worldbuilding, 'star_systems') and worldbuilding.star_systems:
            content.append("## ⭐ Star Systems\n")
            for system in worldbuilding.star_systems:
                content.append(f"### {system.name}")
                content.append(f"- **Type**: {system.system_type.title()}")
                if system.galaxy:
                    content.append(f"- **Galaxy**: {system.galaxy}")
                if system.location:
                    content.append(f"- **Location**: {system.location}")
                if system.distance_from_earth:
                    content.append(f"- **Distance from Earth**: {system.distance_from_earth}")
                if system.habitable_zone_inner or system.habitable_zone_outer:
                    content.append(f"- **Habitable Zone**: {system.habitable_zone_inner or '?'} - {system.habitable_zone_outer or '?'}")
                if system.description:
                    content.append(f"\n{system.description}")
                if system.notes:
                    content.append(f"\n**Notes**: {system.notes}")
                content.append("")

        # Factions
        if hasattr(worldbuilding, 'factions') and worldbuilding.factions:
            content.append("## ⚔️ Factions\n")
            for faction in worldbuilding.factions:
                content.append(f"### {faction.name}")
                if faction.faction_type:
                    content.append(f"- **Type**: {faction.faction_type}")
                if faction.government_type:
                    content.append(f"- **Government**: {faction.government_type}")
                if faction.leader:
                    content.append(f"- **Leader**: {faction.leader}")
                if faction.population:
                    content.append(f"- **Population**: {faction.population:,}")
                if faction.territory:
                    content.append(f"- **Territory**: {faction.territory}")
                if faction.description:
                    content.append(f"\n{faction.description}")

                # Relationships
                if faction.allies or faction.enemies:
                    content.append("\n**Relationships**:")
                    if faction.allies:
                        content.append(f"- Allies: {', '.join(faction.allies)}")
                    if faction.enemies:
                        content.append(f"- Enemies: {', '.join(faction.enemies)}")

                content.append("")

        # Technologies
        if hasattr(worldbuilding, 'technologies') and worldbuilding.technologies:
            content.append("## 🔬 Technologies\n")
            for tech in worldbuilding.technologies:
                content.append(f"### {tech.name}")
                content.append(f"- **Type**: {tech.technology_type.value.replace('_', ' ').title()}")
                content.append(f"- **Impact Level**: {tech.game_changing_level}/100")
                content.append(f"- **Destructive Level**: {tech.destructive_level}/100")
                if tech.cost_to_build:
                    content.append(f"- **Cost**: {tech.cost_to_build}")
                if tech.factions_with_access:
                    content.append(f"- **Factions with Access**: {', '.join(tech.factions_with_access)}")
                if tech.description:
                    content.append(f"\n{tech.description}")
                content.append("")

        # Flora
        if hasattr(worldbuilding, 'flora') and worldbuilding.flora:
            content.append("## 🌿 Flora\n")
            for flora in worldbuilding.flora:
                content.append(f"### {flora.name}")
                content.append(f"- **Type**: {flora.flora_type.value.replace('_', ' ').title()}")
                if flora.native_planets:
                    content.append(f"- **Native Planets**: {', '.join(flora.native_planets)}")
                if flora.preferred_climate:
                    content.append(f"- **Climate**: {flora.preferred_climate}")
                properties = []
                if flora.edible:
                    properties.append("Edible")
                if flora.medicinal_properties:
                    properties.append("Medicinal")
                if flora.toxicity:
                    properties.append("Toxic")
                if flora.magical_properties:
                    properties.append("Magical")
                if properties:
                    content.append(f"- **Properties**: {', '.join(properties)}")
                if flora.description:
                    content.append(f"\n{flora.description}")
                content.append("")

        # Fauna
        if hasattr(worldbuilding, 'fauna') and worldbuilding.fauna:
            content.append("## 🦁 Fauna\n")
            for fauna in worldbuilding.fauna:
                content.append(f"### {fauna.name}")
                content.append(f"- **Type**: {fauna.fauna_type.value.replace('_', ' ').title()}")
                if fauna.native_planets:
                    content.append(f"- **Native Planets**: {', '.join(fauna.native_planets)}")
                if fauna.danger_level is not None:
                    danger = "Harmless" if fauna.danger_level < 30 else "Moderate" if fauna.danger_level < 70 else "Dangerous"
                    content.append(f"- **Danger Level**: {danger} ({fauna.danger_level}/100)")
                if fauna.diet:
                    content.append(f"- **Diet**: {fauna.diet}")
                if fauna.domestication_status:
                    content.append(f"- **Domestication**: {fauna.domestication_status}")
                if fauna.description:
                    content.append(f"\n{fauna.description}")
                content.append("")

        # Mythology
        if hasattr(worldbuilding, 'myths') and worldbuilding.myths:
            content.append("## 📖 Mythology\n")
            for myth in worldbuilding.myths:
                content.append(f"### {myth.name}")
                if myth.myth_type:
                    content.append(f"- **Type**: {myth.myth_type}")
                if myth.associated_factions:
                    content.append(f"- **Believed by**: {', '.join(myth.associated_factions)}")
                if myth.key_figures:
                    content.append(f"- **Key Figures**: {', '.join(myth.key_figures)}")
                if myth.description:
                    content.append(f"\n{myth.description}")
                if myth.moral_lesson:
                    content.append(f"\n**Moral**: {myth.moral_lesson}")
                content.append("")

        # Climate Presets
        if hasattr(worldbuilding, 'climate_presets') and worldbuilding.climate_presets:
            content.append("## 🌤️ Climate Presets\n")
            for preset in worldbuilding.climate_presets:
                content.append(f"### {preset.name}")
                if preset.climate_zones:
                    content.append("\n**Zones**:")
                    for zone in preset.climate_zones:
                        content.append(f"- {zone}")
                if preset.description:
                    content.append(f"\n{preset.description}")
                content.append("")

        return content

    @staticmethod
    def _export_plot(story_planning) -> list:
        """Export plot data."""
        content = []

        # Main Plot
        if story_planning.main_plot:
            content.append("## Main Plot\n")
            content.append(story_planning.main_plot)
            content.append("")

        # Freytag's Pyramid
        content.append("## Story Structure (Freytag's Pyramid)\n")

        pyramid = story_planning.freytag_pyramid

        if hasattr(pyramid, 'events') and pyramid.events:
            # Group events by stage
            stages = {
                'exposition': [],
                'rising_action': [],
                'climax': [],
                'falling_action': [],
                'resolution': []
            }

            for event in pyramid.events:
                if event.stage in stages:
                    stages[event.stage].append(event)

            # Export each stage
            stage_names = {
                'exposition': 'Exposition',
                'rising_action': 'Rising Action',
                'climax': 'Climax',
                'falling_action': 'Falling Action',
                'resolution': 'Resolution'
            }

            for stage_key, stage_name in stage_names.items():
                content.append(f"### {stage_name}\n")
                events = sorted(stages[stage_key], key=lambda e: e.sort_order)

                if events:
                    for event in events:
                        intensity_bar = "🔥" * (event.intensity // 20) if event.intensity else ""
                        content.append(f"**{event.title}** {intensity_bar}")
                        if event.description:
                            content.append(f"{event.description}")
                        if event.outcome:
                            content.append(f"*Outcome: {event.outcome}*")
                        content.append("")
                else:
                    # Fallback to old text-based descriptions
                    old_text = getattr(pyramid, stage_key, "")
                    if old_text:
                        content.append(old_text)
                        content.append("")
        else:
            # Use old text-based structure
            if pyramid.exposition:
                content.append("### Exposition\n")
                content.append(pyramid.exposition)
                content.append("")

            if pyramid.rising_action:
                content.append("### Rising Action\n")
                content.append(pyramid.rising_action)
                content.append("")

            if pyramid.climax:
                content.append("### Climax\n")
                content.append(pyramid.climax)
                content.append("")

            if pyramid.falling_action:
                content.append("### Falling Action\n")
                content.append(pyramid.falling_action)
                content.append("")

            if pyramid.resolution:
                content.append("### Resolution\n")
                content.append(pyramid.resolution)
                content.append("")

        # Subplots
        if hasattr(story_planning, 'subplots') and story_planning.subplots:
            content.append("## Subplots\n")
            for subplot in story_planning.subplots:
                content.append(f"### {subplot.title}")
                if subplot.status:
                    content.append(f"*Status: {subplot.status}*")
                if subplot.connection_to_main_plot:
                    content.append(f"\n**Connection to Main Plot**: {subplot.connection_to_main_plot}")
                if subplot.description:
                    content.append(f"\n{subplot.description}")
                content.append("")

        return content

    @staticmethod
    def _export_characters(characters) -> list:
        """Export character data."""
        content = []

        for character in characters:
            content.append(f"## {character.name}\n")

            # Basic info
            if character.role:
                content.append(f"**Role**: {character.role}")
            if character.age:
                content.append(f"**Age**: {character.age}")
            if character.gender:
                content.append(f"**Gender**: {character.gender}")
            if character.species:
                content.append(f"**Species**: {character.species}")

            # Physical description
            if character.physical_description:
                content.append(f"\n### Physical Description\n")
                content.append(character.physical_description)

            # Personality
            if character.personality:
                content.append(f"\n### Personality\n")
                content.append(character.personality)

            # Backstory
            if character.backstory:
                content.append(f"\n### Backstory\n")
                content.append(character.backstory)

            # Goals and motivations
            if character.goals:
                content.append(f"\n### Goals\n")
                content.append(character.goals)

            if character.motivations:
                content.append(f"\n### Motivations\n")
                content.append(character.motivations)

            # Fears and flaws
            if character.fears:
                content.append(f"\n### Fears\n")
                content.append(character.fears)

            if character.flaws:
                content.append(f"\n### Flaws\n")
                content.append(character.flaws)

            # Relationships
            if character.relationships:
                content.append(f"\n### Relationships\n")
                for rel_name, rel_desc in character.relationships.items():
                    content.append(f"- **{rel_name}**: {rel_desc}")

            # Skills and abilities
            if character.skills:
                content.append(f"\n### Skills\n")
                content.append(", ".join(character.skills))

            # Character arc
            if character.character_arc:
                content.append(f"\n### Character Arc\n")
                content.append(character.character_arc)

            content.append("\n---\n")

        return content
