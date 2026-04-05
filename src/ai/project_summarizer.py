"""Project summarization agent for creating condensed context summaries.

Automatically generates concise summaries of plot, characters, worldbuilding, and themes
to provide efficient context for AI assistants without overwhelming token limits.
"""

import hashlib
import json
from datetime import datetime


class ProjectSummarizer:
    """Creates and maintains condensed summaries of project data."""

    def __init__(self):
        """Initialize the summarizer."""
        self._ai_handler = None

    def set_ai_handler(self, handler):
        """Set the AI handler for generating summaries.

        Args:
            handler: Callable that takes (prompt: str) -> str
        """
        self._ai_handler = handler

    def compute_source_hash(self, project) -> str:
        """Compute hash of source data to detect changes.

        Args:
            project: WriterProject instance

        Returns:
            SHA256 hash of serialized project data
        """
        # Serialize relevant project data
        data_dict = {
            'plot': getattr(project.story_planning, 'main_plot', ''),
            'themes': getattr(project.story_planning, 'themes', []),
            'subplots': [sp.title for sp in getattr(project.story_planning, 'subplots', [])],
            'characters': [
                {'name': char.name, 'type': getattr(char, 'character_type', ''),
                 'personality': getattr(char, 'personality', '')[:100]}
                for char in project.characters[:20]
            ],
            'worldbuilding': {
                'mythology': getattr(project.worldbuilding, 'mythology', '')[:500],
                'history': getattr(project.worldbuilding, 'history', '')[:500],
                'politics': getattr(project.worldbuilding, 'politics', '')[:500],
                'factions': len(getattr(project.worldbuilding, 'factions', [])),
                'cultures': len(getattr(project.worldbuilding, 'cultures', [])),
                'places': len(getattr(project.worldbuilding, 'places', [])),
            },
            'chapters': len(getattr(project.manuscript, 'chapters', [])),
        }

        # Create hash
        serialized = json.dumps(data_dict, sort_keys=True)
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def needs_update(self, project) -> bool:
        """Check if project summary needs regeneration.

        Args:
            project: WriterProject instance

        Returns:
            True if summary should be regenerated
        """
        if project.ai_summary.is_empty():
            return True

        current_hash = self.compute_source_hash(project)
        return project.ai_summary.needs_update(current_hash)

    async def generate_summary_async(self, project) -> dict:
        """Generate condensed summaries of project data (async version).

        Args:
            project: WriterProject instance

        Returns:
            Dictionary with summary fields
        """
        # For now, delegate to sync version
        return self.generate_summary(project)

    def generate_summary(self, project) -> dict:
        """Generate condensed summaries of project data.

        Args:
            project: WriterProject instance

        Returns:
            Dictionary with summary fields: {
                'plot_summary': str,
                'character_summary': str,
                'worldbuilding_summary': str,
                'themes_summary': str,
                'source_hash': str
            }
        """
        if not self._ai_handler:
            # Return empty summaries if no AI handler
            return {
                'plot_summary': '',
                'character_summary': '',
                'worldbuilding_summary': '',
                'themes_summary': '',
                'source_hash': ''
            }

        summaries = {}

        # 1. Summarize plot and story planning
        summaries['plot_summary'] = self._summarize_plot(project)

        # 2. Summarize characters
        summaries['character_summary'] = self._summarize_characters(project)

        # 3. Summarize worldbuilding
        summaries['worldbuilding_summary'] = self._summarize_worldbuilding(project)

        # 4. Summarize themes
        summaries['themes_summary'] = self._summarize_themes(project)

        # 5. Compute source hash
        summaries['source_hash'] = self.compute_source_hash(project)

        return summaries

    def _summarize_plot(self, project) -> str:
        """Generate condensed plot summary.

        Args:
            project: WriterProject instance

        Returns:
            Concise plot summary (max ~500 words)
        """
        # Gather plot data
        main_plot = project.story_planning.main_plot
        subplots = [sp.title + ": " + sp.description for sp in project.story_planning.subplots[:5]]

        if not main_plot and not subplots:
            return ""

        # Build prompt for summarization
        subplot_text = "\n".join(f"- {sp}" for sp in subplots) if subplots else ""

        prompt = f"""Condense the following story plot into a concise summary (max 300 words).

MAIN PLOT:
{main_plot}

{"SUBPLOTS:" if subplot_text else ""}
{subplot_text}

Create a clear, concise summary that captures:
- Core story premise
- Main conflict/goal
- Key plot points
- Major subplots

Keep it under 300 words. Be specific and concrete."""

        try:
            return self._ai_handler(prompt).strip()
        except Exception as e:
            print(f"Error generating plot summary: {e}")
            # Fallback to truncated original
            return main_plot[:500] + "..." if len(main_plot) > 500 else main_plot

    def _summarize_characters(self, project) -> str:
        """Generate condensed character summary.

        Args:
            project: WriterProject instance

        Returns:
            Concise character summary (max ~500 words)
        """
        if not project.characters:
            return ""

        # Gather top characters (limit to 10)
        char_data = []
        for char in project.characters[:10]:
            char_info = f"**{char.name}** ({getattr(char, 'character_type', 'minor')})"
            if getattr(char, 'personality', ''):
                char_info += f": {char.personality[:150]}"
            if getattr(char, 'personality_traits', None):
                char_info += f" | Traits: {', '.join(char.personality_traits)}"
            if getattr(char, 'speaking_style', ''):
                char_info += f" | Voice: {char.speaking_style[:80]}"
            if getattr(char, 'backstory', ''):
                char_info += f" | Background: {char.backstory[:100]}"
            char_data.append(char_info)

        if not char_data:
            return ""

        prompt = f"""Condense the following character descriptions into a concise summary (max 300 words).

CHARACTERS:
{chr(10).join(char_data)}

Create a brief overview that captures:
- Main characters and their roles
- Key relationships
- Essential traits/motivations

Keep it under 300 words. Focus on what's most relevant for understanding the story."""

        try:
            return self._ai_handler(prompt).strip()
        except Exception as e:
            print(f"Error generating character summary: {e}")
            # Fallback to simple list
            return "\n".join(char_data[:5])

    def _summarize_worldbuilding(self, project) -> str:
        """Generate condensed worldbuilding summary.

        Args:
            project: WriterProject instance

        Returns:
            Concise worldbuilding summary (max ~500 words)
        """
        wb = project.worldbuilding

        # Gather worldbuilding data
        wb_sections = []
        if getattr(wb, 'mythology', ''):
            wb_sections.append(f"Mythology: {wb.mythology[:400]}")
        if getattr(wb, 'history', ''):
            wb_sections.append(f"History: {wb.history[:400]}")
        if getattr(wb, 'politics', ''):
            wb_sections.append(f"Politics: {wb.politics[:300]}")
        if getattr(wb, 'factions', []):
            factions = [f"{f.name}: {getattr(f, 'description', '')[:80]}" for f in wb.factions[:5]]
            wb_sections.append(f"Factions: {'; '.join(factions)}")
        if getattr(wb, 'cultures', []):
            cultures = [f"{c.name}: {getattr(c, 'description', '')[:80]}" for c in wb.cultures[:4]]
            wb_sections.append(f"Cultures: {'; '.join(cultures)}")
        if getattr(wb, 'places', []):
            places = [p.name for p in wb.places[:6]]
            wb_sections.append(f"Key Places: {', '.join(places)}")
        if getattr(wb, 'magic_systems', []):
            magic = [f"{m.name}: {getattr(m, 'description', '')[:80]}" for m in wb.magic_systems[:3]]
            wb_sections.append(f"Magic Systems: {'; '.join(magic)}")
        if getattr(wb, 'technologies', []):
            tech = [t.name for t in wb.technologies[:5]]
            wb_sections.append(f"Technologies: {', '.join(tech)}")

        if not wb_sections:
            return ""

        prompt = f"""Condense the following worldbuilding details into a concise summary (max 300 words).

{chr(10).join(wb_sections)}

Create a brief overview that captures:
- Setting and world type
- Key historical/political context
- Important locations
- Unique world features (magic, technology, etc.)

Keep it under 300 words. Focus on essentials that inform the story."""

        try:
            return self._ai_handler(prompt).strip()
        except Exception as e:
            print(f"Error generating worldbuilding summary: {e}")
            # Fallback to truncated sections
            return "\n\n".join(wb_sections[:3])

    def _summarize_themes(self, project) -> str:
        """Generate condensed themes summary.

        Args:
            project: WriterProject instance

        Returns:
            Concise themes summary (max ~200 words)
        """
        themes = project.story_planning.themes

        if not themes:
            return ""

        # Simple concatenation for themes
        theme_text = ", ".join(themes)

        prompt = f"""Briefly describe these story themes in 1-2 sentences (max 100 words):

{theme_text}

Explain how these themes might manifest in the story."""

        try:
            return self._ai_handler(prompt).strip()
        except Exception as e:
            print(f"Error generating themes summary: {e}")
            # Fallback to simple list
            return f"Themes: {theme_text}"

    def update_project_summary(self, project) -> bool:
        """Update project's AI summary if needed.

        Args:
            project: WriterProject instance

        Returns:
            True if summary was updated, False if unchanged
        """
        if not self.needs_update(project):
            print("Project summary is up to date")
            return False

        print("Generating project summary...")
        summaries = self.generate_summary(project)

        if summaries['source_hash']:
            # Update the project summary
            project.ai_summary.plot_summary = summaries['plot_summary']
            project.ai_summary.character_summary = summaries['character_summary']
            project.ai_summary.worldbuilding_summary = summaries['worldbuilding_summary']
            project.ai_summary.themes_summary = summaries['themes_summary']
            project.ai_summary.source_hash = summaries['source_hash']
            project.ai_summary.last_updated = datetime.now()

            print("Project summary updated successfully")
            return True

        return False


# Global instance
_summarizer_instance = None


def get_project_summarizer() -> ProjectSummarizer:
    """Get or create the global project summarizer instance.

    Returns:
        ProjectSummarizer instance
    """
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = ProjectSummarizer()
    return _summarizer_instance
