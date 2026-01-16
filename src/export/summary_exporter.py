"""Export project as a comprehensive summary with optional AI summarization."""

from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from src.models.project import WriterProject, StoryPlanning, Character


class SummarizationMethod(Enum):
    """Available summarization methods."""
    NONE = "none"  # No summarization, raw data export
    AI_CLOUD = "ai_cloud"  # Use cloud LLM API
    ML_LOCAL = "ml_local"  # Use local ML model


@dataclass
class SummarySection:
    """A section of the exported summary."""
    title: str
    content: str
    word_count: int
    summarized: bool = False
    original_word_count: int = 0


@dataclass
class ExportResult:
    """Result of the export operation."""
    success: bool
    file_path: Optional[str]
    total_words: int
    sections: List[SummarySection]
    summarization_method: SummarizationMethod
    error_message: Optional[str] = None


class ProjectSummarizer:
    """Summarizes project content using various methods."""

    def __init__(self, method: SummarizationMethod = SummarizationMethod.NONE):
        """Initialize summarizer.

        Args:
            method: The summarization method to use
        """
        self.method = method
        self._llm_client = None
        self._ml_model = None

    def set_llm_client(self, llm_client):
        """Set the LLM client for AI summarization."""
        self._llm_client = llm_client

    def summarize(self, text: str, max_length: int = 500, context: str = "") -> str:
        """Summarize text using the configured method.

        Args:
            text: Text to summarize
            max_length: Target max length for summary
            context: Additional context about what the text represents

        Returns:
            Summarized text, or original if summarization not available
        """
        if not text or len(text.split()) < 50:
            return text  # Too short to summarize

        if self.method == SummarizationMethod.NONE:
            return text

        if self.method == SummarizationMethod.AI_CLOUD:
            return self._summarize_with_ai(text, max_length, context)

        if self.method == SummarizationMethod.ML_LOCAL:
            return self._summarize_with_ml(text, max_length)

        return text

    def _summarize_with_ai(self, text: str, max_length: int, context: str) -> str:
        """Summarize using cloud AI."""
        if not self._llm_client:
            return text

        try:
            prompt = f"""Summarize the following {context} concisely in about {max_length} words.
Keep the most important details and maintain the essence of the content.

TEXT TO SUMMARIZE:
{text[:4000]}

SUMMARY:"""

            response = self._llm_client.generate_text(
                prompt,
                "You are a skilled editor who creates concise, informative summaries.",
                max_tokens=max_length * 2,
                temperature=0.3
            )
            return response.strip()
        except Exception as e:
            print(f"AI summarization failed: {e}")
            return text

    def _summarize_with_ml(self, text: str, max_length: int) -> str:
        """Summarize using local ML model."""
        try:
            # Try to use transformers if available
            if self._ml_model is None:
                self._load_ml_model()

            if self._ml_model is None:
                return text

            # Use the summarization pipeline
            summary = self._ml_model(
                text[:1024],  # Model input limit
                max_length=max_length,
                min_length=30,
                do_sample=False
            )
            return summary[0]['summary_text']
        except Exception as e:
            print(f"ML summarization failed: {e}")
            return text

    def _load_ml_model(self):
        """Load the local ML summarization model."""
        try:
            from transformers import pipeline
            # Use a small, fast summarization model
            self._ml_model = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",
                device=-1  # CPU
            )
        except ImportError:
            print("transformers library not available for ML summarization")
            self._ml_model = None
        except Exception as e:
            print(f"Failed to load ML model: {e}")
            self._ml_model = None


class SummaryExporter:
    """Export project data as a comprehensive summary."""

    def __init__(
        self,
        project: WriterProject,
        summarizer: Optional[ProjectSummarizer] = None
    ):
        """Initialize summary exporter.

        Args:
            project: The project to export
            summarizer: Optional summarizer for AI/ML summarization
        """
        self.project = project
        self.summarizer = summarizer or ProjectSummarizer(SummarizationMethod.NONE)
        self.sections: List[SummarySection] = []

    def export(
        self,
        output_path: Optional[str] = None,
        include_manuscript: bool = True,
        include_worldbuilding: bool = True,
        include_characters: bool = True,
        include_plot: bool = True,
        include_promises: bool = True,
        summarize_chapters: bool = False,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> ExportResult:
        """Export the project as a summary.

        Args:
            output_path: Path to save the summary file
            include_manuscript: Include manuscript content
            include_worldbuilding: Include worldbuilding data
            include_characters: Include character profiles
            include_plot: Include plot structure
            include_promises: Include story promises
            summarize_chapters: If True, summarize chapter content
            progress_callback: Optional callback for progress updates (message, percent)

        Returns:
            ExportResult with export details
        """
        self.sections = []
        content_parts = []

        try:
            # Header
            content_parts.append(self._create_header())

            if progress_callback:
                progress_callback("Generating table of contents...", 5)

            # Table of contents
            content_parts.append(self._create_toc(
                include_manuscript, include_worldbuilding,
                include_characters, include_plot, include_promises
            ))

            # Project Overview
            if progress_callback:
                progress_callback("Creating project overview...", 10)
            content_parts.append(self._export_overview())

            # Story Promises
            if include_promises:
                if progress_callback:
                    progress_callback("Exporting story promises...", 15)
                content_parts.append(self._export_promises())

            # Plot Structure
            if include_plot:
                if progress_callback:
                    progress_callback("Exporting plot structure...", 25)
                content_parts.append(self._export_plot())

            # Characters
            if include_characters:
                if progress_callback:
                    progress_callback("Exporting characters...", 40)
                content_parts.append(self._export_characters())

            # Worldbuilding
            if include_worldbuilding:
                if progress_callback:
                    progress_callback("Exporting worldbuilding...", 55)
                content_parts.append(self._export_worldbuilding())

            # Manuscript
            if include_manuscript:
                if progress_callback:
                    progress_callback("Exporting manuscript...", 70)
                content_parts.append(self._export_manuscript(summarize_chapters))

            # Statistics
            if progress_callback:
                progress_callback("Calculating statistics...", 90)
            content_parts.append(self._export_statistics())

            # Combine all content
            full_content = "\n".join(filter(None, content_parts))
            total_words = len(full_content.split())

            # Save to file
            if output_path:
                if progress_callback:
                    progress_callback("Saving file...", 95)
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(full_content, encoding='utf-8')

            if progress_callback:
                progress_callback("Export complete!", 100)

            return ExportResult(
                success=True,
                file_path=output_path,
                total_words=total_words,
                sections=self.sections,
                summarization_method=self.summarizer.method
            )

        except Exception as e:
            return ExportResult(
                success=False,
                file_path=None,
                total_words=0,
                sections=[],
                summarization_method=self.summarizer.method,
                error_message=str(e)
            )

    def _create_header(self) -> str:
        """Create the document header."""
        lines = [
            f"# {self.project.name} - Project Summary",
            f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            f"*Summarization: {self.summarizer.method.value}*\n"
        ]
        if self.project.description:
            lines.append(f"> {self.project.description}\n")
        return "\n".join(lines)

    def _create_toc(self, manuscript: bool, worldbuilding: bool,
                    characters: bool, plot: bool, promises: bool) -> str:
        """Create table of contents."""
        lines = ["## Table of Contents\n"]
        lines.append("1. [Project Overview](#project-overview)")
        if promises:
            lines.append("2. [Story Promises](#story-promises)")
        if plot:
            lines.append("3. [Plot Structure](#plot-structure)")
        if characters:
            lines.append("4. [Characters](#characters)")
        if worldbuilding:
            lines.append("5. [Worldbuilding](#worldbuilding)")
        if manuscript:
            lines.append("6. [Manuscript Summary](#manuscript-summary)")
        lines.append("7. [Statistics](#statistics)")
        lines.append("")
        return "\n".join(lines)

    def _export_overview(self) -> str:
        """Export project overview."""
        lines = ["\n---\n", "# Project Overview\n"]

        # Basic info
        lines.append(f"**Project Name**: {self.project.name}")
        if self.project.description:
            lines.append(f"\n**Description**: {self.project.description}")

        # Manuscript info
        if self.project.manuscript:
            ms = self.project.manuscript
            lines.append(f"\n**Manuscript Title**: {ms.title}")
            if ms.author:
                lines.append(f"**Author**: {ms.author}")
            lines.append(f"**Chapters**: {len(ms.chapters)}")
            lines.append(f"**Total Words**: {ms.total_word_count:,}")

        # Quick stats
        lines.append("\n### Quick Stats")
        lines.append(f"- Characters: {len(self.project.characters)}")
        lines.append(f"- Subplots: {len(self.project.story_planning.subplots)}")
        if hasattr(self.project.story_planning, 'promises'):
            lines.append(f"- Story Promises: {len(self.project.story_planning.promises)}")

        # Worldbuilding counts
        wb = self.project.worldbuilding
        wb_counts = []
        if hasattr(wb, 'factions') and wb.factions:
            wb_counts.append(f"{len(wb.factions)} factions")
        if hasattr(wb, 'places') and wb.places:
            wb_counts.append(f"{len(wb.places)} places")
        if hasattr(wb, 'cultures') and wb.cultures:
            wb_counts.append(f"{len(wb.cultures)} cultures")
        if wb_counts:
            lines.append(f"- Worldbuilding: {', '.join(wb_counts)}")

        lines.append("")

        section = SummarySection(
            title="Project Overview",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content

    def _export_promises(self) -> str:
        """Export story promises."""
        if not hasattr(self.project.story_planning, 'promises') or not self.project.story_planning.promises:
            return ""

        lines = ["\n---\n", "# Story Promises\n"]
        lines.append("*These are commitments to the reader about tone, plot, genre, and characters.*\n")

        # Group by type
        promises_by_type: Dict[str, List] = {
            'tone': [],
            'plot': [],
            'genre': [],
            'character': []
        }

        for promise in self.project.story_planning.promises:
            ptype = promise.promise_type
            if ptype in promises_by_type:
                promises_by_type[ptype].append(promise)

        type_icons = {
            'tone': '🎭',
            'plot': '📖',
            'genre': '📚',
            'character': '👤'
        }

        for ptype, type_promises in promises_by_type.items():
            if type_promises:
                icon = type_icons.get(ptype, '📝')
                lines.append(f"## {icon} {ptype.title()} Promises\n")
                for p in type_promises:
                    lines.append(f"### {p.title}")
                    if p.description:
                        lines.append(p.description)
                    if p.related_characters:
                        lines.append(f"\n*Related Characters: {', '.join(p.related_characters)}*")
                    lines.append("")

        section = SummarySection(
            title="Story Promises",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content

    def _export_plot(self) -> str:
        """Export plot structure."""
        lines = ["\n---\n", "# Plot Structure\n"]
        sp = self.project.story_planning

        # Main plot
        if sp.main_plot:
            lines.append("## Main Plot\n")
            plot_text = sp.main_plot
            if self.summarizer.method != SummarizationMethod.NONE:
                plot_text = self.summarizer.summarize(plot_text, 200, "main plot description")
            lines.append(plot_text)
            lines.append("")

        # Freytag's Pyramid events
        pyramid = sp.freytag_pyramid
        if hasattr(pyramid, 'events') and pyramid.events:
            lines.append("## Story Arc Events\n")

            # Group by act
            acts: Dict[int, List] = {}
            for event in pyramid.events:
                act = event.act
                if act not in acts:
                    acts[act] = []
                acts[act].append(event)

            act_names = pyramid.act_names if hasattr(pyramid, 'act_names') else []

            for act_num in sorted(acts.keys()):
                act_name = act_names[act_num - 1] if act_num <= len(act_names) else f"Act {act_num}"
                lines.append(f"### {act_name}\n")

                events = sorted(acts[act_num], key=lambda e: (e.stage, e.sort_order))
                for event in events:
                    stage_display = event.stage.replace('_', ' ').title()
                    lines.append(f"**{event.title}** ({stage_display})")
                    if event.description:
                        desc = event.description
                        if self.summarizer.method != SummarizationMethod.NONE and len(desc) > 200:
                            desc = self.summarizer.summarize(desc, 100, "plot event")
                        lines.append(f"  {desc}")
                    if event.outcome:
                        lines.append(f"  *Outcome: {event.outcome}*")
                    lines.append("")

        # Subplots
        if sp.subplots:
            lines.append("## Subplots\n")
            for subplot in sp.subplots:
                status_icon = {'active': '🔄', 'resolved': '✅', 'abandoned': '❌'}.get(subplot.status, '📌')
                lines.append(f"### {status_icon} {subplot.title}\n")
                if subplot.description:
                    desc = subplot.description
                    if self.summarizer.method != SummarizationMethod.NONE:
                        desc = self.summarizer.summarize(desc, 150, "subplot")
                    lines.append(desc)
                if subplot.connection_to_main:
                    lines.append(f"\n*Connection: {subplot.connection_to_main}*")
                lines.append("")

        # Themes
        if sp.themes:
            lines.append("## Themes\n")
            for theme in sp.themes:
                lines.append(f"- {theme}")
            lines.append("")

        section = SummarySection(
            title="Plot Structure",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content

    def _export_characters(self) -> str:
        """Export character profiles."""
        if not self.project.characters:
            return ""

        lines = ["\n---\n", "# Characters\n"]

        # Group by type
        char_types: Dict[str, List] = {
            'protagonist': [],
            'antagonist': [],
            'major': [],
            'minor': []
        }

        for char in self.project.characters:
            ctype = char.character_type.lower() if char.character_type else 'minor'
            if ctype in char_types:
                char_types[ctype].append(char)
            else:
                char_types['minor'].append(char)

        type_labels = {
            'protagonist': '🦸 Protagonists',
            'antagonist': '🦹 Antagonists',
            'major': '⭐ Major Characters',
            'minor': '👥 Minor Characters'
        }

        for ctype, label in type_labels.items():
            chars = char_types[ctype]
            if chars:
                lines.append(f"## {label}\n")
                for char in chars:
                    lines.append(f"### {char.name}\n")

                    if char.personality:
                        personality = char.personality
                        if self.summarizer.method != SummarizationMethod.NONE and len(personality) > 200:
                            personality = self.summarizer.summarize(personality, 100, "character personality")
                        lines.append(f"**Personality**: {personality}\n")

                    if char.backstory:
                        backstory = char.backstory
                        if self.summarizer.method != SummarizationMethod.NONE and len(backstory) > 300:
                            backstory = self.summarizer.summarize(backstory, 150, "character backstory")
                        lines.append(f"**Background**: {backstory}\n")

                    if char.social_network:
                        lines.append("**Relationships**:")
                        for rel_name, rel_desc in list(char.social_network.items())[:5]:
                            lines.append(f"  - {rel_name}: {rel_desc}")
                        lines.append("")

                    if char.notes:
                        lines.append(f"*Notes: {char.notes[:200]}*")

                    lines.append("")

        section = SummarySection(
            title="Characters",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content

    def _export_worldbuilding(self) -> str:
        """Export worldbuilding summary."""
        wb = self.project.worldbuilding
        lines = ["\n---\n", "# Worldbuilding\n"]

        # Places
        if hasattr(wb, 'places') and wb.places:
            lines.append("## 🗺️ Places\n")
            for place in wb.places[:10]:  # Limit to avoid huge exports
                lines.append(f"### {place.name}")
                if hasattr(place, 'place_type'):
                    lines.append(f"*Type: {place.place_type}*")
                if place.description:
                    desc = place.description
                    if self.summarizer.method != SummarizationMethod.NONE:
                        desc = self.summarizer.summarize(desc, 100, "place description")
                    lines.append(desc)
                lines.append("")

        # Factions
        if hasattr(wb, 'factions') and wb.factions:
            lines.append("## ⚔️ Factions\n")
            for faction in wb.factions[:10]:
                lines.append(f"### {faction.name}")
                if faction.faction_type:
                    lines.append(f"*Type: {faction.faction_type}*")
                if faction.leader:
                    lines.append(f"*Leader: {faction.leader}*")
                if faction.description:
                    desc = faction.description
                    if self.summarizer.method != SummarizationMethod.NONE:
                        desc = self.summarizer.summarize(desc, 100, "faction description")
                    lines.append(desc)
                lines.append("")

        # Cultures
        if hasattr(wb, 'cultures') and wb.cultures:
            lines.append("## 🎭 Cultures\n")
            for culture in wb.cultures[:10]:
                lines.append(f"### {culture.name}")
                if hasattr(culture, 'description') and culture.description:
                    desc = culture.description
                    if self.summarizer.method != SummarizationMethod.NONE:
                        desc = self.summarizer.summarize(desc, 100, "culture description")
                    lines.append(desc)
                lines.append("")

        # Historical Events
        if hasattr(wb, 'historical_events') and wb.historical_events:
            lines.append("## 📜 Key Historical Events\n")
            events = sorted(wb.historical_events, key=lambda e: e.year if hasattr(e, 'year') else 0)
            for event in events[:10]:
                year_str = f"[{event.year}] " if hasattr(event, 'year') and event.year else ""
                lines.append(f"- **{year_str}{event.name}**")
                if event.description:
                    desc = event.description[:150] + "..." if len(event.description) > 150 else event.description
                    lines.append(f"  {desc}")
            lines.append("")

        # Technologies
        if hasattr(wb, 'technologies') and wb.technologies:
            lines.append("## 🔬 Technologies\n")
            for tech in wb.technologies[:10]:
                lines.append(f"- **{tech.name}**")
                if hasattr(tech, 'technology_type'):
                    lines.append(f"  Type: {tech.technology_type.value.replace('_', ' ').title()}")
            lines.append("")

        section = SummarySection(
            title="Worldbuilding",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content

    def _export_manuscript(self, summarize_chapters: bool) -> str:
        """Export manuscript summary."""
        if not self.project.manuscript or not self.project.manuscript.chapters:
            return ""

        lines = ["\n---\n", "# Manuscript Summary\n"]
        ms = self.project.manuscript

        lines.append(f"**Title**: {ms.title}")
        if ms.author:
            lines.append(f"**Author**: {ms.author}")
        lines.append(f"**Total Chapters**: {len(ms.chapters)}")
        lines.append(f"**Total Words**: {ms.total_word_count:,}")
        lines.append("")

        lines.append("## Chapter Overview\n")

        for chapter in ms.chapters:
            lines.append(f"### Chapter {chapter.number}: {chapter.title}")
            lines.append(f"*Words: {chapter.word_count:,}*\n")

            if chapter.content:
                if summarize_chapters and self.summarizer.method != SummarizationMethod.NONE:
                    # Summarize the chapter
                    summary = self.summarizer.summarize(
                        chapter.content,
                        200,
                        f"chapter {chapter.number}"
                    )
                    lines.append(f"**Summary**: {summary}\n")
                else:
                    # Just show first paragraph or excerpt
                    paragraphs = chapter.content.strip().split('\n\n')
                    if paragraphs:
                        excerpt = paragraphs[0][:300]
                        if len(paragraphs[0]) > 300:
                            excerpt += "..."
                        lines.append(f"*Excerpt*: {excerpt}\n")

            if chapter.notes:
                lines.append(f"*Notes*: {chapter.notes[:200]}\n")

            lines.append("")

        section = SummarySection(
            title="Manuscript Summary",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split()),
            summarized=summarize_chapters and self.summarizer.method != SummarizationMethod.NONE
        )
        self.sections.append(section)
        return section.content

    def _export_statistics(self) -> str:
        """Export project statistics."""
        lines = ["\n---\n", "# Statistics\n"]

        # Manuscript stats
        if self.project.manuscript:
            ms = self.project.manuscript
            lines.append("## Manuscript Statistics\n")
            lines.append(f"- Total Chapters: {len(ms.chapters)}")
            lines.append(f"- Total Words: {ms.total_word_count:,}")

            if ms.chapters:
                avg_words = ms.total_word_count // len(ms.chapters)
                lines.append(f"- Average Words per Chapter: {avg_words:,}")

                word_counts = [c.word_count for c in ms.chapters]
                lines.append(f"- Longest Chapter: {max(word_counts):,} words")
                lines.append(f"- Shortest Chapter: {min(word_counts):,} words")
            lines.append("")

        # Character stats
        if self.project.characters:
            lines.append("## Character Statistics\n")
            lines.append(f"- Total Characters: {len(self.project.characters)}")

            type_counts: Dict[str, int] = {}
            for char in self.project.characters:
                ctype = char.character_type or 'unspecified'
                type_counts[ctype] = type_counts.get(ctype, 0) + 1

            for ctype, count in sorted(type_counts.items()):
                lines.append(f"- {ctype.title()}: {count}")
            lines.append("")

        # Worldbuilding stats
        wb = self.project.worldbuilding
        wb_items = []
        if hasattr(wb, 'factions') and wb.factions:
            wb_items.append(f"Factions: {len(wb.factions)}")
        if hasattr(wb, 'places') and wb.places:
            wb_items.append(f"Places: {len(wb.places)}")
        if hasattr(wb, 'cultures') and wb.cultures:
            wb_items.append(f"Cultures: {len(wb.cultures)}")
        if hasattr(wb, 'technologies') and wb.technologies:
            wb_items.append(f"Technologies: {len(wb.technologies)}")
        if hasattr(wb, 'historical_events') and wb.historical_events:
            wb_items.append(f"Historical Events: {len(wb.historical_events)}")

        if wb_items:
            lines.append("## Worldbuilding Statistics\n")
            for item in wb_items:
                lines.append(f"- {item}")
            lines.append("")

        # Plot stats
        sp = self.project.story_planning
        lines.append("## Plot Statistics\n")
        if hasattr(sp.freytag_pyramid, 'events'):
            lines.append(f"- Plot Events: {len(sp.freytag_pyramid.events)}")
        lines.append(f"- Subplots: {len(sp.subplots)}")
        if hasattr(sp, 'promises'):
            lines.append(f"- Story Promises: {len(sp.promises)}")
        if sp.themes:
            lines.append(f"- Themes: {len(sp.themes)}")
        lines.append("")

        section = SummarySection(
            title="Statistics",
            content="\n".join(lines),
            word_count=len("\n".join(lines).split())
        )
        self.sections.append(section)
        return section.content
