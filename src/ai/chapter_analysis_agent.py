"""Chapter Analysis Agent for providing line-item edit suggestions.

This agent analyzes chapters and paragraphs to provide specific editing suggestions
without rewriting content. Uses cost-effective hybrid approach.
"""

import re
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.ui.enhanced_text_editor import WritingStats


class SuggestionType(Enum):
    """Types of editing suggestions."""
    # Core writing craft
    SHOW_DONT_TELL = "show_dont_tell"
    PACING = "pacing"
    DIALOGUE = "dialogue"
    DESCRIPTION = "description"
    CHARACTER_VOICE = "character_voice"
    CONSISTENCY = "consistency"
    CLARITY = "clarity"
    GRAMMAR = "grammar"
    WORD_CHOICE = "word_choice"

    # Extended categories for comprehensive critique
    PLOT = "plot"
    WORLDBUILDING = "worldbuilding"
    STYLE = "style"
    TONE = "tone"
    VOICE = "voice"
    CHARACTER_DEVELOPMENT = "character_development"
    TENSION = "tension"
    THEME = "theme"

    # Publishability-specific issues
    CLICHE = "cliche"
    FILTER_WORDS = "filter_words"
    TRANSITION = "transition"
    POV = "pov"
    ADVERB = "adverb"
    PASSIVE_VOICE = "passive_voice"
    INFO_DUMP = "info_dump"


@dataclass
class CritiqueContext:
    """Context provided by author for targeted critique."""
    style: str = ""  # e.g., "literary fiction", "hard-boiled noir"
    tone: str = ""  # e.g., "dark and brooding", "hopeful"
    voice: str = ""  # e.g., "first-person unreliable narrator"
    plot_goals: str = ""  # What this section should accomplish
    characters: str = ""  # Key characters and their arcs
    worldbuilding: str = ""  # Relevant world details
    additional_instructions: str = ""  # Any other critique focus


@dataclass
class LineItemSuggestion:
    """A specific line-item suggestion for editing."""
    line_number: Optional[int]  # None if applies to paragraph/section
    paragraph_number: int
    suggestion_type: SuggestionType
    original_text: str  # The text being commented on
    suggestion: str  # What to consider changing
    explanation: str  # Why this matters (reasoning)
    priority: str  # "high", "medium", "low"
    reasoning: str = ""  # Detailed reasoning for the edit (separate from brief explanation)
    example_fix: str = ""  # Example of how the text could be revised


@dataclass
class ChapterAnalysis:
    """Complete analysis of a chapter."""
    overall_assessment: str
    strengths: List[str]
    areas_for_improvement: List[str]
    line_item_suggestions: List[LineItemSuggestion]
    pacing_notes: str
    character_consistency_notes: str
    estimated_cost: float


class ChapterAnalysisAgent:
    """Agent for analyzing chapters and providing editing suggestions."""

    ANALYSIS_PROMPT = """You are a professional editor preparing writing for publication.

    PUBLISHABILITY FOCUS:
    - Show don't tell for emotional/important moments (some telling is fine)
    - Natural transitions (no "Meanwhile...", "Little did she know...")
    - Consistent tone, style, and voice throughout
    - Avoid clichés and overused phrases
    - No filter words ("she saw", "he felt", "she noticed")
    - No adverb-heavy dialogue tags
    - No head-hopping or POV breaks

    CRITICAL RULES:
    1. Provide SUGGESTIONS, not rewrites
    2. Frame feedback as "Consider..." "You might..." "What if..."
    3. Be specific about what and where
    4. Explain WHY each issue hurts publishability
    5. Recognize what works well
    6. Focus on issues that would cause rejection

    Prioritize suggestions that most improve publishability.
    """

    ENHANCED_ANALYSIS_PROMPT = """You are a professional editor preparing writing for publication. Your goal is to identify issues that would prevent publication in quality literary markets.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Plot Goals for This Section: {plot_context}
- Key Characters: {character_context}
- Worldbuilding Elements: {worldbuilding_context}
- Additional Instructions: {additional_instructions}

=== PUBLISHABILITY STANDARDS ===

SHOW VS TELL BALANCE:
- Some telling is FINE and necessary - you cannot show everything
- FLAG: Emotional states told baldly ("She was angry", "He felt sad")
- FLAG: Important moments told instead of shown ("The meeting went badly")
- ACCEPTABLE: Transitional telling ("Three days later...", "She spent the morning...")
- ACCEPTABLE: Brief character thoughts that inform ("She knew he was lying")
- RULE: The more important the moment, the more it should be shown

TRANSITIONS:
- FLAG: Abrupt scene shifts without grounding ("Meanwhile..." "Back at...")
- FLAG: Time jumps that disorient the reader
- FLAG: Forced transitions that tell rather than flow ("Little did she know...")
- ACCEPTABLE: Clean section breaks for major shifts
- RULE: Transitions should feel invisible and natural

TONE/STYLE/VOICE CONSISTENCY:
- FLAG: Sudden shifts in narrative voice without story reason
- FLAG: Modern slang in historical settings (or vice versa)
- FLAG: Character voice that doesn't match their background
- FLAG: Prose style that shifts between literary and casual without purpose
- RULE: The author's stated tone/style/voice should be maintained throughout

TROPES AND CLICHÉS:
- FLAG: Overused phrases ("a chill ran down her spine", "his blood ran cold")
- FLAG: Predictable plot beats executed without fresh perspective
- FLAG: Stock character behaviors (wise mentor, chosen one, etc.) without nuance
- FLAG: Purple prose or melodrama
- RULE: Genre conventions are fine; lazy execution is not

OTHER PUBLISHABILITY ISSUES:
- FLAG: Head-hopping (POV shifts mid-scene without clear break)
- FLAG: Info-dumps disguised as dialogue
- FLAG: White room syndrome (scenes with no sensory grounding)
- FLAG: Dialogue tags with adverbs ("he said angrily")
- FLAG: Filter words that distance the reader ("she saw", "he heard", "she felt")
- FLAG: Passive voice where active would strengthen
- FLAG: Repetitive sentence structure

=== OUTPUT RULES ===

CRITICAL RULES:
1. Provide SUGGESTIONS, not rewrites
2. Frame feedback as "Consider..." "You might..." "What if..."
3. Be specific - quote the exact text
4. Explain WHY each issue matters for publishability
5. Recognize what works well - don't create problems where none exist
6. Prioritize issues that would most likely cause rejection
7. Respect the author's genre and style choices

For each suggestion:
- Quote the specific text
- Identify the issue type
- Explain why this hurts publishability
- Suggest an improvement approach (not a rewrite)
- Provide an example fix showing one possible revision
- Rate priority: high/medium/low
"""

    QUICK_REVIEW_PROMPT = """You are providing quick publishability feedback.
    Point out the 2-3 most important issues that would hurt publication.
    Focus on: show vs tell problems, unnatural transitions, voice/tone breaks, clichés.
    Be brief and specific."""

    QUICK_ENHANCED_PROMPT = """You are a professional editor providing quick publishability feedback.
Focus on the 3-5 most critical issues that would hurt publication:
- Telling instead of showing (for important moments)
- Unnatural or forced transitions
- Tone/style/voice inconsistency with author's intent
- Clichés, filter words, adverb-heavy dialogue tags
- POV problems or head-hopping

Be specific and constructive. Explain why each issue hurts publishability."""

    def __init__(
        self,
        primary_llm: 'LLMClient',
        local_llm: Optional['LLMClient'] = None
    ):
        """Initialize chapter analysis agent.

        Args:
            primary_llm: Primary cloud LLM for detailed analysis
            local_llm: Optional local SLM for quick reviews
        """
        self.primary_llm = primary_llm
        self.local_llm = local_llm
        self.total_cost = 0.0

    def analyze_chapter(
        self,
        chapter_text: str,
        chapter_title: str,
        manuscript_context: str = "",
        detailed: bool = True,
        critique_context: Optional[CritiqueContext] = None,
        focus_areas: Optional[List[SuggestionType]] = None,
        chapter_synopsis: str = "",
        llm_override: Optional['LLMClient'] = None,
    ) -> ChapterAnalysis:
        """Analyze entire chapter.

        Args:
            chapter_text: Full chapter text
            chapter_title: Chapter title
            manuscript_context: Context from manuscript
            detailed: If True, provides detailed line-item analysis
            critique_context: Optional author-provided context for targeted critique
            focus_areas: Optional list of specific suggestion types to focus on

        Returns:
            Complete ChapterAnalysis
        """
        # Split into paragraphs
        paragraphs = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]

        if not detailed:
            return self._quick_chapter_review(
                chapter_text, chapter_title, paragraphs,
                critique_context, llm_override=llm_override)

        # Detailed analysis
        word_count = len(chapter_text.split())

        # Build focus areas text if provided
        focus_text = ""
        if focus_areas:
            areas = [area.value.replace('_', ' ').title() for area in focus_areas]
            focus_text = f"\n\nFOCUS AREAS (prioritize these):\n{', '.join(areas)}"

        # Build system prompt with context if provided
        if critique_context:
            system_prompt = self.ENHANCED_ANALYSIS_PROMPT.format(
                style_context=critique_context.style or "Not specified",
                tone_context=critique_context.tone or "Not specified",
                voice_context=critique_context.voice or "Not specified",
                plot_context=critique_context.plot_goals or "Not specified",
                character_context=critique_context.characters or "Not specified",
                worldbuilding_context=critique_context.worldbuilding or "Not specified",
                additional_instructions=critique_context.additional_instructions or "None"
            )
        else:
            system_prompt = self.ANALYSIS_PROMPT

        synopsis_line = f"Chapter Synopsis: {chapter_synopsis}\n" if chapter_synopsis else ""
        prompt = f"""
Chapter: {chapter_title}
Word Count: {word_count}
{synopsis_line}Manuscript Context:
{manuscript_context[:600]}
{focus_text}

Chapter Text (first 3000 words):
{' '.join(chapter_text.split()[:3000])}

Provide comprehensive editing feedback organised by SECTION (scenes or logical paragraph groups).
Work through the chapter systematically — do not stop after 2-3 points.

1. OVERALL ASSESSMENT (2-3 sentences on the chapter as a whole)

2. SECTION-BY-SECTION BREAKDOWN
For each identifiable scene or section:
- Label it (e.g. "Opening scene", "Scene 2 — the confrontation", "Closing beat")
- Strengths of this section
- Specific issues with a brief quoted passage and a concrete suggestion

3. PACING NOTES
Brief comments on overall chapter pacing and scene transitions.

4. CHARACTER CONSISTENCY
Any concerns about character voices, motivations, or behaviour across the chapter.

5. TOP LINE-ITEM SUGGESTIONS (5-7 specific edits)
For each suggestion, provide:
- Paragraph # (estimate)
- Quote: "[relevant text]"
- Type: [issue type]
- Suggestion: [what to improve]
- Example: [one possible revision of the quoted text]
- Why: [explanation]
- Priority: [high/medium/low]

Keep feedback constructive and actionable.
"""

        llm = llm_override if llm_override is not None else self.primary_llm
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=1500,
            temperature=0.5
        )

        # Estimate cost
        prompt_tokens = len(prompt.split()) * 1.3
        completion_tokens = len(response.split()) * 1.3
        cost = self._estimate_cost(int(prompt_tokens), int(completion_tokens))

        # Parse response
        analysis = self._parse_chapter_analysis(response, paragraphs)
        analysis.estimated_cost = cost

        return analysis

    def _quick_chapter_review(
        self,
        chapter_text: str,
        chapter_title: str,
        paragraphs: List[str],
        critique_context: Optional[CritiqueContext] = None,
        llm_override: Optional['LLMClient'] = None,
    ) -> ChapterAnalysis:
        """Quick review of chapter for cost savings."""
        # Build context note if provided
        context_note = ""
        if critique_context:
            context_parts = []
            if critique_context.style:
                context_parts.append(f"Style: {critique_context.style}")
            if critique_context.tone:
                context_parts.append(f"Tone: {critique_context.tone}")
            if critique_context.voice:
                context_parts.append(f"Voice: {critique_context.voice}")
            if context_parts:
                context_note = f"\n\nAuthor's Intent:\n{', '.join(context_parts)}\n"

        prompt = f"""
Chapter: {chapter_title}
{context_note}
First 500 words:
{' '.join(chapter_text.split()[:500])}

Last 200 words:
{' '.join(chapter_text.split()[-200:])}

Provide brief feedback:
1. Overall impression (2 sentences)
2. Top 3 strengths
3. Top 3 areas to improve
4. 3 specific suggestions with paragraph references

Be concise.
"""

        if llm_override is not None:
            llm = llm_override
        else:
            llm = self.local_llm if self.local_llm else self.primary_llm

        # Use enhanced prompt if context provided
        system_prompt = self.QUICK_ENHANCED_PROMPT if critique_context else self.QUICK_REVIEW_PROMPT

        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=400,
            temperature=0.4
        )

        # Parse simplified response
        lines = response.split('\n')
        overall = ""
        strengths = []
        improvements = []
        suggestions = []

        current_section = None
        for line in lines:
            line = line.strip()
            if '1. overall' in line.lower() or 'impression' in line.lower():
                current_section = 'overall'
            elif 'strength' in line.lower():
                current_section = 'strengths'
            elif 'improve' in line.lower():
                current_section = 'improvements'
            elif 'suggestion' in line.lower():
                current_section = 'suggestions'
            elif line:
                if current_section == 'overall':
                    overall += line + " "
                elif current_section == 'strengths' and (line.startswith('-') or line[0].isdigit()):
                    strengths.append(line.lstrip('- 123456789.'))
                elif current_section == 'improvements' and (line.startswith('-') or line[0].isdigit()):
                    improvements.append(line.lstrip('- 123456789.'))
                elif current_section == 'suggestions':
                    suggestions.append(line)

        cost = self._estimate_cost(len(prompt.split()) * 1.3, len(response.split()) * 1.3)

        return ChapterAnalysis(
            overall_assessment=overall.strip(),
            strengths=strengths[:3],
            areas_for_improvement=improvements[:3],
            line_item_suggestions=[],
            pacing_notes="Quick review - detailed analysis available",
            character_consistency_notes="Quick review - detailed analysis available",
            estimated_cost=cost
        )

    def _create_suggestion(
        self,
        data: Dict[str, str],
        paragraph_num: int,
        paragraphs: List[str] = None
    ) -> LineItemSuggestion:
        """Create LineItemSuggestion from parsed data."""
        # Map type string to enum
        type_str = data.get("type", "").lower().replace(' ', '_')
        suggestion_type = SuggestionType.CLARITY  # Default

        for stype in SuggestionType:
            if stype.value in type_str or type_str in stype.value:
                suggestion_type = stype
                break

        # Get original text - prefer quote, fallback to paragraph text
        quote = data.get("quote", "").strip()
        if quote:
            original_text = quote[:200]
        elif paragraphs and 0 < paragraph_num <= len(paragraphs):
            # Use the actual paragraph text as fallback
            original_text = paragraphs[paragraph_num - 1][:200]
        else:
            original_text = "[Text not available]"

        return LineItemSuggestion(
            line_number=None,
            paragraph_number=paragraph_num,
            suggestion_type=suggestion_type,
            original_text=original_text,
            suggestion=data.get("suggestion", ""),
            explanation=data.get("why", ""),
            priority=data.get("priority", "medium"),
            reasoning=data.get("why", ""),  # Use same as explanation for general critique
            example_fix=data.get("example", "")
        )

    def _parse_chapter_analysis(
        self,
        response: str,
        paragraphs: List[str]
    ) -> ChapterAnalysis:
        """Parse full chapter analysis response."""
        sections = {
            "overall": "",
            "strengths": [],
            "improvements": [],
            "pacing": "",
            "character": "",
            "suggestions": []
        }

        lines = response.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            line_lower = line.lower()

            if 'overall assessment' in line_lower:
                current_section = 'overall'
            elif 'strength' in line_lower:
                current_section = 'strengths'
            elif 'improvement' in line_lower or 'areas for' in line_lower:
                current_section = 'improvements'
            elif 'pacing' in line_lower:
                current_section = 'pacing'
            elif 'character' in line_lower or 'consistency' in line_lower:
                current_section = 'character'
            elif 'line-item' in line_lower or 'suggestion' in line_lower:
                current_section = 'suggestions'
            elif line:
                if current_section == 'overall':
                    sections["overall"] += line + " "
                elif current_section in ['strengths', 'improvements']:
                    if line.startswith('-') or line[0].isdigit():
                        sections[current_section].append(line.lstrip('- 123456789.'))
                elif current_section == 'pacing':
                    sections["pacing"] += line + " "
                elif current_section == 'character':
                    sections["character"] += line + " "
                elif current_section == 'suggestions':
                    sections["suggestions"].append(line)

        # Parse suggestions from text
        line_items = []
        current_item = {}

        import re as parse_re
        for line in sections["suggestions"]:
            if 'Paragraph' in line or 'Para' in line:
                if current_item:
                    line_items.append(current_item)
                # Extract paragraph number from line like "Paragraph 3:" or "Para # 2"
                para_match = parse_re.search(r'(?:Paragraph|Para)\s*#?\s*(\d+)', line, parse_re.IGNORECASE)
                para_num = int(para_match.group(1)) if para_match else 1
                current_item = {"paragraph": para_num}
            elif 'Quote:' in line:
                current_item["quote"] = line.split('Quote:')[1].strip(' "')
            elif 'Type:' in line:
                current_item["type"] = line.split('Type:')[1].strip()
            elif 'Suggestion:' in line:
                current_item["suggestion"] = line.split('Suggestion:')[1].strip()
            elif 'Example:' in line:
                current_item["example"] = line.split('Example:')[1].strip(' "')
            elif 'Why:' in line:
                current_item["why"] = line.split('Why:')[1].strip()
            elif 'Priority:' in line:
                current_item["priority"] = line.split('Priority:')[1].strip().lower()

        if current_item:
            line_items.append(current_item)

        # Convert to LineItemSuggestion objects
        parsed_suggestions = []
        for item in line_items:
            parsed_suggestions.append(
                self._create_suggestion(item, item.get("paragraph", 1), paragraphs)
            )

        return ChapterAnalysis(
            overall_assessment=sections["overall"].strip(),
            strengths=sections["strengths"][:5],
            areas_for_improvement=sections["improvements"][:5],
            line_item_suggestions=parsed_suggestions,
            pacing_notes=sections["pacing"].strip(),
            character_consistency_notes=sections["character"].strip(),
            estimated_cost=0.0  # Set by caller
        )

    def _estimate_cost(self, prompt_tokens: float, completion_tokens: float) -> float:
        """Estimate cost of API call."""
        # Using Claude Sonnet 3.5 as reference
        cost = (prompt_tokens / 1000) * 0.003
        cost += (completion_tokens / 1000) * 0.015
        self.total_cost += cost
        return cost

    def get_total_cost(self) -> float:
        """Get total cost so far."""
        return round(self.total_cost, 4)

    def reset_cost(self):
        """Reset cost tracking."""
        self.total_cost = 0.0


@dataclass
class PromiseViolation:
    """A detected violation of a story promise."""
    promise_title: str
    promise_type: str  # tone, plot, genre, character
    violation_description: str
    quote: str  # The text that violates the promise
    severity: str  # "high", "medium", "low"
    suggestion: str  # How to fix it


@dataclass
class CharacterInconsistency:
    """A detected character inconsistency."""
    character_name: str
    inconsistency_type: str  # voice, behavior, knowledge, motivation
    description: str
    quote: str
    expected_behavior: str
    suggestion: str


@dataclass
class PromiseCheckResult:
    """Result of checking a chapter against story promises."""
    chapter_title: str
    overall_adherence: str  # "excellent", "good", "needs_attention", "problematic"
    promise_violations: List[PromiseViolation]
    character_inconsistencies: List[CharacterInconsistency]
    tone_assessment: str
    plot_alignment: str
    summary: str


class PromiseChecker:
    """Agent for checking chapters against story promises and character consistency."""

    PROMISE_CHECK_SYSTEM = """You are a continuity editor ensuring consistency in storytelling.
Your job is to check if chapter content adheres to the author's stated promises and maintains character consistency.

Be thorough but fair. Not every deviation is a violation - stories can have nuance.
Only flag genuine issues that would confuse or disappoint readers.

For each issue you find:
1. Quote the specific problematic text
2. Explain why it's an issue
3. Suggest how to address it
"""

    def __init__(self, llm_client: 'LLMClient'):
        """Initialize promise checker.

        Args:
            llm_client: LLM client for API calls
        """
        self.llm = llm_client

    def check_chapter(
        self,
        chapter_content: str,
        chapter_title: str,
        promises: List[Dict[str, Any]],
        characters: List[Dict[str, Any]],
        plot_outline: str = "",
        previous_chapters_summary: str = "",
        llm_override: Optional['LLMClient'] = None,
    ) -> PromiseCheckResult:
        """Check a chapter against story promises and character consistency.

        Args:
            chapter_content: The chapter text to check
            chapter_title: Title of the chapter
            promises: List of story promises (dicts with type, title, description)
            characters: List of characters (dicts with name, personality, backstory)
            plot_outline: Optional plot outline for context
            previous_chapters_summary: Summary of previous chapters for continuity

        Returns:
            PromiseCheckResult with violations and inconsistencies
        """
        # Format promises for the prompt
        promises_text = self._format_promises(promises)
        characters_text = self._format_characters(characters)

        prompt = f"""
STORY PROMISES TO CHECK AGAINST:
{promises_text}

CHARACTER PROFILES:
{characters_text}

{f"PLOT OUTLINE:{chr(10)}{plot_outline}{chr(10)}" if plot_outline else ""}
{f"PREVIOUS CHAPTERS SUMMARY:{chr(10)}{previous_chapters_summary}{chr(10)}" if previous_chapters_summary else ""}

CHAPTER TO ANALYZE: {chapter_title}
---
{chapter_content[:6000]}  # Truncate if too long
---

Analyze this chapter for:

1. PROMISE VIOLATIONS
Check each promise type (tone, plot, genre, character) and identify any violations.
For each violation found, provide:
- Promise: [which promise was violated]
- Type: [tone/plot/genre/character]
- Quote: "[exact text that violates]"
- Issue: [what's wrong]
- Severity: [high/medium/low]
- Suggestion: [how to fix]

2. CHARACTER INCONSISTENCIES
Check if characters behave consistently with their established profiles.
For each inconsistency found, provide:
- Character: [name]
- Type: [voice/behavior/knowledge/motivation]
- Quote: "[text showing inconsistency]"
- Expected: [what would be consistent]
- Suggestion: [how to fix]

3. OVERALL ASSESSMENT
- Tone Assessment: [Does the chapter maintain the promised tone?]
- Plot Alignment: [Does it align with the story's plot promises?]
- Overall Adherence: [excellent/good/needs_attention/problematic]
- Summary: [2-3 sentence summary of findings]

If no issues are found in a category, explicitly state "No issues found."
"""

        llm = llm_override if llm_override is not None else self.llm
        response = llm.generate_text(
            prompt,
            self.PROMISE_CHECK_SYSTEM,
            max_tokens=2000,
            temperature=0.3
        )

        return self._parse_check_result(response, chapter_title)

    def _format_promises(self, promises: List[Dict[str, Any]]) -> str:
        """Format promises for the prompt."""
        if not promises:
            return "No explicit promises defined."

        lines = []
        type_labels = {
            "tone": "🎭 TONE",
            "plot": "📖 PLOT",
            "genre": "📚 GENRE",
            "character": "👤 CHARACTER"
        }

        for p in promises:
            label = type_labels.get(p.get("promise_type", ""), "📝")
            lines.append(f"{label}: {p.get('title', 'Untitled')}")
            if p.get("description"):
                lines.append(f"   {p.get('description')}")
            if p.get("related_characters"):
                lines.append(f"   Related characters: {', '.join(p.get('related_characters', []))}")
            lines.append("")

        return "\n".join(lines)

    def _format_characters(self, characters: List[Dict[str, Any]]) -> str:
        """Format characters for the prompt."""
        if not characters:
            return "No character profiles available."

        lines = []
        for c in characters:
            lines.append(f"• {c.get('name', 'Unknown')} ({c.get('character_type', 'unknown')})")
            if c.get("personality"):
                lines.append(f"  Personality: {c.get('personality')[:200]}")
            if c.get("backstory"):
                lines.append(f"  Background: {c.get('backstory')[:200]}")
            lines.append("")

        return "\n".join(lines)

    def _parse_check_result(self, response: str, chapter_title: str) -> PromiseCheckResult:
        """Parse the LLM response into structured result."""
        violations = []
        inconsistencies = []
        tone_assessment = ""
        plot_alignment = ""
        overall_adherence = "good"
        summary = ""

        lines = response.split('\n')
        current_section = None
        current_item = {}

        for line in lines:
            line = line.strip()
            line_lower = line.lower()

            # Section headers
            if 'promise violation' in line_lower:
                current_section = 'violations'
            elif 'character inconsistenc' in line_lower:
                current_section = 'inconsistencies'
            elif 'overall assessment' in line_lower:
                current_section = 'assessment'
            elif 'no issues found' in line_lower:
                continue

            # Parse violations
            elif current_section == 'violations':
                if line.startswith('- Promise:') or line.startswith('Promise:'):
                    if current_item and 'promise' in current_item:
                        violations.append(self._create_violation(current_item))
                    current_item = {'promise': line.split(':', 1)[1].strip()}
                elif line.startswith('- Type:') or line.startswith('Type:'):
                    current_item['type'] = line.split(':', 1)[1].strip().lower()
                elif line.startswith('- Quote:') or line.startswith('Quote:'):
                    current_item['quote'] = line.split(':', 1)[1].strip().strip('"')
                elif line.startswith('- Issue:') or line.startswith('Issue:'):
                    current_item['issue'] = line.split(':', 1)[1].strip()
                elif line.startswith('- Severity:') or line.startswith('Severity:'):
                    current_item['severity'] = line.split(':', 1)[1].strip().lower()
                elif line.startswith('- Suggestion:') or line.startswith('Suggestion:'):
                    current_item['suggestion'] = line.split(':', 1)[1].strip()

            # Parse inconsistencies
            elif current_section == 'inconsistencies':
                if line.startswith('- Character:') or line.startswith('Character:'):
                    if current_item and 'character' in current_item:
                        inconsistencies.append(self._create_inconsistency(current_item))
                    current_item = {'character': line.split(':', 1)[1].strip()}
                elif line.startswith('- Type:') or line.startswith('Type:'):
                    current_item['type'] = line.split(':', 1)[1].strip().lower()
                elif line.startswith('- Quote:') or line.startswith('Quote:'):
                    current_item['quote'] = line.split(':', 1)[1].strip().strip('"')
                elif line.startswith('- Expected:') or line.startswith('Expected:'):
                    current_item['expected'] = line.split(':', 1)[1].strip()
                elif line.startswith('- Suggestion:') or line.startswith('Suggestion:'):
                    current_item['suggestion'] = line.split(':', 1)[1].strip()

            # Parse assessment
            elif current_section == 'assessment':
                if 'tone assessment' in line_lower:
                    tone_assessment = line.split(':', 1)[1].strip() if ':' in line else ""
                elif 'plot alignment' in line_lower:
                    plot_alignment = line.split(':', 1)[1].strip() if ':' in line else ""
                elif 'overall adherence' in line_lower:
                    adherence = line.split(':', 1)[1].strip().lower() if ':' in line else "good"
                    if 'excellent' in adherence:
                        overall_adherence = 'excellent'
                    elif 'problematic' in adherence:
                        overall_adherence = 'problematic'
                    elif 'needs' in adherence or 'attention' in adherence:
                        overall_adherence = 'needs_attention'
                    else:
                        overall_adherence = 'good'
                elif 'summary' in line_lower:
                    summary = line.split(':', 1)[1].strip() if ':' in line else ""

        # Add last items if present
        if current_item:
            if current_section == 'violations' and 'promise' in current_item:
                violations.append(self._create_violation(current_item))
            elif current_section == 'inconsistencies' and 'character' in current_item:
                inconsistencies.append(self._create_inconsistency(current_item))

        return PromiseCheckResult(
            chapter_title=chapter_title,
            overall_adherence=overall_adherence,
            promise_violations=violations,
            character_inconsistencies=inconsistencies,
            tone_assessment=tone_assessment or "Not assessed",
            plot_alignment=plot_alignment or "Not assessed",
            summary=summary or "Analysis complete."
        )

    def _create_violation(self, data: Dict[str, str]) -> PromiseViolation:
        """Create a PromiseViolation from parsed data."""
        return PromiseViolation(
            promise_title=data.get('promise', 'Unknown'),
            promise_type=data.get('type', 'unknown'),
            violation_description=data.get('issue', ''),
            quote=data.get('quote', '')[:200],
            severity=data.get('severity', 'medium'),
            suggestion=data.get('suggestion', '')
        )

    def _create_inconsistency(self, data: Dict[str, str]) -> CharacterInconsistency:
        """Create a CharacterInconsistency from parsed data."""
        return CharacterInconsistency(
            character_name=data.get('character', 'Unknown'),
            inconsistency_type=data.get('type', 'behavior'),
            description=data.get('issue', ''),
            quote=data.get('quote', '')[:200],
            expected_behavior=data.get('expected', ''),
            suggestion=data.get('suggestion', '')
        )


# ─────────────────────────────────────────────────────────────────────
# Report-driven critique (genre-aware, multi-analyzer, dashboard
# fallback when no LLM is configured). Powers GraderWidget's
# scope-selector + report-checkbox flow.
# ─────────────────────────────────────────────────────────────────────


class ReportType(Enum):
    """Top-level report categories the critique can produce."""
    PACING = "pacing"
    VOICE = "voice"
    TENSION = "tension"
    PLOT = "plot"
    DIALOG = "dialog"
    STYLE = "style"
    # Canon report — judges how faithfully the chapter follows the
    # project's established characters and worldbuilding, AND
    # suggests opportunities to draw on canon elements that aren't
    # being used. Distinct from VOICE (which judges *prose voice*)
    # and PLOT (which judges *structural beats*) — CANON judges
    # *entity fidelity and opportunity*.
    CANON = "canon"
    # Grammar / spelling / hard-to-read paragraphs. Catches the
    # mechanical errors and readability cliffs that the other
    # analyzers (which judge *craft*) typically don't flag.
    GRAMMAR = "grammar"
    # Per-character portrayal vs. the character's profile + arc:
    # what's on track, what drifts, and how to stay on course.
    CHARACTER = "character"
    # Worldbuilding fidelity: elements on the page that the project has
    # no record of, elements that match canon, and elements that differ.
    WORLDBUILDING = "worldbuilding"
    # Cross-manuscript continuity (main project + its novellas): shared
    # characters / world elements and the story timeline across books.
    CONTINUITY = "continuity"


@dataclass
class GenreProfile:
    """Pacing / style thresholds tuned for a specific genre.

    Numbers are rules of thumb derived from craft references and
    ProWritingAid-style genre tables. They define the *expected*
    band — a chapter outside the band gets flagged, but the LLM
    narrative is given the actual numbers + the band so it can
    judge whether the deviation is intentional.
    """
    key: str
    name: str
    avg_sentence_target: tuple   # (low, high) words/sentence
    variety_score_target: float  # 0-100 lower bound (higher = more varied)
    dialog_pct_target: tuple     # (low, high) % of words inside quotes
    passive_pct_max: float       # upper bound, % of sentences
    long_sentence_pct_max: float # upper bound, % of sentences > 35 words
    adverb_pct_max: float        # upper bound, % of words
    notes: str                   # one-line characterization


# Profiles align with src.data.genres canonical keys (literary,
# thriller, romance, mystery, fantasy, scifi, horror, gothic,
# western, frontier, adventure). Unknown / blank → "default".
GENRE_PROFILES: Dict[str, GenreProfile] = {
    "default": GenreProfile(
        "default", "General Fiction",
        avg_sentence_target=(11.0, 22.0),
        variety_score_target=40.0,
        dialog_pct_target=(15.0, 50.0),
        passive_pct_max=15.0,
        long_sentence_pct_max=12.0,
        adverb_pct_max=4.0,
        notes="Balanced prose — varied rhythm, mixed dialog and narration.",
    ),
    "literary": GenreProfile(
        "literary", "Literary Fiction",
        avg_sentence_target=(14.0, 26.0),
        variety_score_target=50.0,
        dialog_pct_target=(10.0, 40.0),
        passive_pct_max=18.0,
        long_sentence_pct_max=18.0,
        adverb_pct_max=4.5,
        notes="Longer, varied sentences; interiority over dialog; passive voice tolerated when intentional.",
    ),
    "thriller": GenreProfile(
        "thriller", "Thriller",
        avg_sentence_target=(8.0, 16.0),
        variety_score_target=45.0,
        dialog_pct_target=(20.0, 55.0),
        passive_pct_max=10.0,
        long_sentence_pct_max=8.0,
        adverb_pct_max=3.0,
        notes="Short punchy sentences; tight prose; minimal passive voice; relentless forward pressure.",
    ),
    "romance": GenreProfile(
        "romance", "Romance",
        avg_sentence_target=(11.0, 20.0),
        variety_score_target=40.0,
        dialog_pct_target=(30.0, 60.0),
        passive_pct_max=12.0,
        long_sentence_pct_max=10.0,
        adverb_pct_max=4.0,
        notes="Dialog-heavy; emotional interiority; brisk pacing during reveals, lingering beats during connection.",
    ),
    "mystery": GenreProfile(
        "mystery", "Mystery",
        avg_sentence_target=(10.0, 19.0),
        variety_score_target=42.0,
        dialog_pct_target=(25.0, 55.0),
        passive_pct_max=12.0,
        long_sentence_pct_max=10.0,
        adverb_pct_max=3.5,
        notes="Dialog and observation drive the puzzle; controlled reveals; lean prose between clues.",
    ),
    "fantasy": GenreProfile(
        "fantasy", "Fantasy",
        avg_sentence_target=(12.0, 24.0),
        variety_score_target=42.0,
        dialog_pct_target=(15.0, 45.0),
        passive_pct_max=14.0,
        long_sentence_pct_max=14.0,
        adverb_pct_max=4.0,
        notes="Worldbuilding earns longer descriptive runs; dialog mixed; watch passive in action beats.",
    ),
    "scifi": GenreProfile(
        "scifi", "Science Fiction",
        avg_sentence_target=(11.0, 22.0),
        variety_score_target=42.0,
        dialog_pct_target=(15.0, 45.0),
        passive_pct_max=12.0,
        long_sentence_pct_max=12.0,
        adverb_pct_max=4.0,
        notes="Technical clarity over flourish; concept exposition needs varied rhythm; dialog conveys voice.",
    ),
    "horror": GenreProfile(
        "horror", "Horror",
        avg_sentence_target=(9.0, 18.0),
        variety_score_target=50.0,
        dialog_pct_target=(15.0, 45.0),
        passive_pct_max=12.0,
        long_sentence_pct_max=10.0,
        adverb_pct_max=3.5,
        notes="Rhythm is dread — long-then-short pivots; sentence-level surprise; dialog used sparingly.",
    ),
    "gothic": GenreProfile(
        "gothic", "Gothic",
        avg_sentence_target=(14.0, 28.0),
        variety_score_target=45.0,
        dialog_pct_target=(10.0, 35.0),
        passive_pct_max=20.0,
        long_sentence_pct_max=20.0,
        adverb_pct_max=5.0,
        notes="Atmospheric, ornate; longer sentences and richer description; passive voice acceptable for mood.",
    ),
    "western": GenreProfile(
        "western", "Western",
        avg_sentence_target=(9.0, 17.0),
        variety_score_target=42.0,
        dialog_pct_target=(20.0, 50.0),
        passive_pct_max=10.0,
        long_sentence_pct_max=8.0,
        adverb_pct_max=3.0,
        notes="Spare, kinetic; understatement; dialog earns its space; minimal adverbs.",
    ),
    "frontier": GenreProfile(
        "frontier", "Frontier / Pioneer",
        avg_sentence_target=(10.0, 19.0),
        variety_score_target=42.0,
        dialog_pct_target=(15.0, 45.0),
        passive_pct_max=12.0,
        long_sentence_pct_max=10.0,
        adverb_pct_max=3.5,
        notes="Plain-spoken, observational; landscape gets longer beats; dialog grounded in setting.",
    ),
    "adventure": GenreProfile(
        "adventure", "Adventure",
        avg_sentence_target=(10.0, 18.0),
        variety_score_target=45.0,
        dialog_pct_target=(20.0, 50.0),
        passive_pct_max=10.0,
        long_sentence_pct_max=8.0,
        adverb_pct_max=3.0,
        notes="Forward motion; varied sentence rhythm matches action beats; minimal passive.",
    ),
}


def resolve_genre_profile(text: Optional[str]) -> GenreProfile:
    """Map free-text genre/style to a GenreProfile.

    Tries exact key match first, then keyword lookup against the
    canonical aliases in ``src.data.genres`` (so "hard-boiled noir"
    or "thriller" both map to the thriller profile). Falls back to
    the "default" profile when nothing matches — so callers can
    always rely on getting a profile back.
    """
    if not text:
        return GENRE_PROFILES["default"]
    s = text.strip().lower()
    if not s:
        return GENRE_PROFILES["default"]
    if s in GENRE_PROFILES:
        return GENRE_PROFILES[s]
    try:
        from src.data.genres import match_genres
        matches = match_genres(s)
        for key in matches:
            if key in GENRE_PROFILES:
                return GENRE_PROFILES[key]
    except Exception:
        pass
    # Keyword fallback for common synonyms not in the genres taxonomy
    for key, profile in GENRE_PROFILES.items():
        if key != "default" and key in s:
            return profile
    if "noir" in s or "suspense" in s:
        return GENRE_PROFILES["thriller"]
    if "love" in s or "romantic" in s:
        return GENRE_PROFILES["romance"]
    return GENRE_PROFILES["default"]


@dataclass
class ReportSection:
    """One report's output for one chapter."""
    report_type: ReportType
    chapter_title: str
    chapter_index: int = 0
    summary: str = ""              # 1-3 sentence rollup
    narrative: str = ""            # LLM-embellished prose (empty when no LLM)
    metrics: Dict[str, Any] = None # raw numbers for the dashboard
    findings: List[str] = None     # all bullet-point findings (kept for
                                   # backwards compat; major + minor are
                                   # the curated subsets the UI surfaces
                                   # prominently)
    suggestions: List[str] = None  # bullet-point suggestions
    # Severity-tiered subsets of findings. Items in major_issues are
    # the load-bearing problems (metrics outside the genre band,
    # missing required elements, hard errors). Items in minor_issues
    # are within-tolerance observations the writer might still want
    # to act on. ``strengths`` are positive observations — what's
    # working — surfaced so writers see them before the issue
    # backlog. ``findings`` stays as the full list so legacy
    # consumers don't break.
    major_issues: List[str] = None
    minor_issues: List[str] = None
    strengths: List[str] = None
    # Captured at execution time so a rated row can save the real
    # (prompt, narrative) pair as training data instead of a stub.
    prompt: str = ""               # user prompt the LLM saw
    system_prompt: str = ""        # system prompt the LLM saw
    # Report-specific headed lists rendered after the standard ones,
    # e.g. {"New elements": [...], "Recommendations": [...]}.
    extra_lists: Dict[str, List[str]] = None
    # Every model call that produced this section, in order — the exact
    # (system, prompt, output) triples, so rated sections, parts and
    # items can be saved as training rows that match inference 1:1.
    # Each: {"id", "label", "kind", "system", "prompt", "output"}.
    calls: List[Dict[str, str]] = None
    # Which call each list item came from (item text → call id).
    item_sources: Dict[str, str] = None

    def __post_init__(self):
        if self.extra_lists is None:
            self.extra_lists = {}
        if self.calls is None:
            self.calls = []
        if self.item_sources is None:
            self.item_sources = {}
        if self.metrics is None:
            self.metrics = {}
        if self.major_issues is None:
            self.major_issues = []
        if self.minor_issues is None:
            self.minor_issues = []
        if self.strengths is None:
            self.strengths = []
        if self.findings is None:
            self.findings = []
        if self.suggestions is None:
            self.suggestions = []


@dataclass
class ChapterReport:
    """All sections for one chapter."""
    chapter_title: str
    chapter_index: int
    word_count: int
    sections: List[ReportSection] = None
    # Counts of how many reports in this chapter cited each entity.
    # Keyed by ``(source_type, source_name)``. Lets the dashboard
    # surface the entities that came up *across* reports without
    # double-counting the same entity per report.
    entity_mentions: Dict[Tuple[str, str], int] = None

    def __post_init__(self):
        if self.sections is None:
            self.sections = []
        if self.entity_mentions is None:
            self.entity_mentions = {}


@dataclass
class CritiqueReport:
    """Top-level critique result spanning one or more chapters."""
    chapters: List[ChapterReport]
    genre: GenreProfile
    overall_summary: str = ""
    has_llm: bool = False
    estimated_cost: float = 0.0
    # The exact call behind ``overall_summary`` (for training rows).
    overall_prompt: str = ""
    overall_system: str = ""


# ── Analyzers ────────────────────────────────────────────────────────


def _safe_pct(numerator: float, denominator: float) -> float:
    """Percentage with zero-safe denominator."""
    if not denominator:
        return 0.0
    return (numerator / denominator) * 100.0


def _band_status(value: float, low: float, high: float) -> str:
    """Classify a value against a (low, high) band."""
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "in_band"


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


_LOCAL_PROVIDERS = {"mlx_local", "huggingface_local"}


def is_local_llm(llm: Any) -> bool:
    """True for on-device models (MLX, local Hugging Face).

    These are typically small (Gemma, Llama 3B/8B, Phi, Qwen) with tight
    context windows and weaker format-following, so the critique gives
    them shorter, focused prompts. A client can force either behaviour
    with a ``compact_prompts`` attribute.
    """
    forced = getattr(llm, "compact_prompts", None)
    if isinstance(forced, bool):
        return forced
    provider = getattr(llm, "provider", None)
    value = getattr(provider, "value", provider)
    return isinstance(value, str) and value.lower() in _LOCAL_PROVIDERS


class _BaseAnalyzer:
    """Common machinery for report analyzers.

    Each analyzer collects deterministic metrics first so the
    dashboard works without a model, then optionally calls the LLM
    to produce a narrative section. The metrics + findings get
    embedded in the LLM prompt so the model anchors its prose to
    the actual numbers instead of hallucinating about pacing.
    """

    # The author's measured voice (``WriterVoice``), set by the orchestrator
    # so recommendations respect deliberate style.
    writer_voice = None

    report_type: ReportType = None  # overridden by subclasses
    max_tokens: int = 900           # narrative budget; heavier reports raise it

    def __init__(
        self,
        primary_llm: Optional['LLMClient'] = None,
        story_planning: Optional[Any] = None,
        manuscript: Optional[Any] = None,
        project: Optional[Any] = None,
    ):
        self.primary_llm = primary_llm
        # Full project (characters, worldbuilding) for analyzers that
        # compare the page against canon records directly.
        self.project = project
        # Story planning + manuscript are surfaced to every analyzer
        # (not just PlotAnalyzer) so the shared context block can
        # include the dramatic arc the chapter sits in AND the
        # surrounding-chapter excerpts. Optional — if absent, the
        # context block simply omits those sub-blocks.
        self.story_planning = story_planning
        self.manuscript = manuscript
        self._stats_cache: Dict[int, 'WritingStats'] = {}

    def _get_stats(self, text: str) -> 'WritingStats':
        """Compute (and cache) ProWritingAnalyzer stats per chapter text."""
        from src.ui.enhanced_text_editor import ProWritingAnalyzer
        key = id(text)
        cached = self._stats_cache.get(key)
        if cached is not None:
            return cached
        stats = ProWritingAnalyzer().analyze(text)
        self._stats_cache[key] = stats
        return stats

    # Phrases that signal a load-bearing problem (metric outside the
    # genre band, missing required element, structural break). Used by
    # the auto-classifier when an analyzer's _compute hasn't already
    # sorted its findings into major / minor.
    _MAJOR_FINDING_MARKERS = (
        "exceed", "above cap", "above genre", "above band",
        "below band", "below genre", "outside",
        "missing", "no scene break", "broken", "violat",
        "unusually high", "unusually low",
        "risk of fatigue", "risk of",
        "above the",
    )
    # Phrases that signal "this is working" — positive observations
    # the writer should see surfaced as strengths, not silently
    # dropped or buried under the issue lists. Expanded liberally
    # since each analyzer phrases positive deterministic findings
    # in slightly different ways ("look healthy", "sit inside the
    # expected band", "no flags detected", etc.).
    _STRENGTH_FINDING_MARKERS = (
        "sit inside expected", "sit inside the expected",
        "look healthy", "look balanced", "look solid",
        "within expected", "within tolerance",
        "within the expected", "within the genre",
        "no flags detected", "no issues detected",
        "no spelling, grammar, or readability flags",
        "balanced for the chapter",
        "looks healthy for", "looks balanced for",
    )
    # Trailing fragment that an analyzer often emits when nothing
    # tripped its thresholds. Treated as a strength rather than a
    # minor issue.
    _NO_FLAGS_MARKERS = (
        "(none)",
    )

    def _auto_classify_findings(self, section: 'ReportSection') -> None:
        """Distribute existing ``findings`` into ``major_issues``,
        ``minor_issues``, and ``strengths`` by keyword pattern.

        Pragmatic v1: analyzers' deterministic findings are short
        strings with consistent phrasing ("Passive voice X% above
        genre cap...", "Sentence variety looks healthy..."), so a
        small keyword list catches most of them. Analyzers that
        want a stricter classification can populate the lists
        themselves — this hook only fires when all three lists are
        empty.
        """
        for finding in section.findings:
            lower = finding.lower()
            if any(m in lower for m in self._STRENGTH_FINDING_MARKERS):
                section.strengths.append(finding)
                continue
            if any(m in lower for m in self._NO_FLAGS_MARKERS):
                # "(none)" or similar — not an issue, not really a
                # strength either; let it fall through to neither.
                continue
            if any(m in lower for m in self._MAJOR_FINDING_MARKERS):
                section.major_issues.append(finding)
            else:
                section.minor_issues.append(finding)

    def run(
        self,
        text: str,
        chapter_title: str,
        chapter_index: int,
        genre: GenreProfile,
        manuscript_context: str,
        rag_context: str,
        critique_context: Optional[CritiqueContext],
        llm: Optional['LLMClient'],
    ) -> ReportSection:
        """Run this analyzer against a chapter and return a ReportSection.

        Subclasses override ``_compute`` (deterministic metrics +
        findings) and ``_build_prompt`` (LLM narrative). Both are
        wrapped here so progress / error handling stays in one place.
        """
        section = ReportSection(
            report_type=self.report_type,
            chapter_title=chapter_title,
            chapter_index=chapter_index,
        )
        try:
            self._compute(text, section, genre, critique_context)
        except Exception as e:  # pragma: no cover — defensive
            section.findings.append(f"(analysis error: {e})")
            return section
        # Distribute findings into major / minor / strengths buckets
        # unless the analyzer's _compute already populated them
        # itself. Keeps the UI's severity grouping working without
        # forcing every analyzer to migrate at once.
        if (not section.major_issues
                and not section.minor_issues
                and not section.strengths):
            self._auto_classify_findings(section)
        if llm is not None:
            self.compact = is_local_llm(llm)
            self._llm = llm
            self._section = section
            try:
                self._narrate(text, section, genre, manuscript_context,
                              rag_context, critique_context, llm)
            except Exception as e:  # pragma: no cover — model errors
                section.narrative = ""
                section.findings.append(f"(narrative skipped: {e})")
            else:
                try:
                    self._post_process(section)
                except Exception as e:  # pragma: no cover — defensive
                    print(f"[critique] post-process failed: {e}")
                _attribute_items(section)
        return section

    def _record_call(self, label: str, kind: str, system: str,
                     prompt: str, output: str) -> str:
        """Remember a model call on the current section; returns its id."""
        section = getattr(self, "_section", None)
        if section is None or not (output or "").strip():
            return ""
        call_id = f"c{len(section.calls) + 1}"
        section.calls.append({"id": call_id, "label": label, "kind": kind,
                              "system": system or "", "prompt": prompt,
                              "output": output})
        return call_id

    # ── LLM plumbing (shared by all analyzers) ───────────────────────

    compact: bool = False  # True for local models → smaller, focused prompts

    def _narrate(self, text, section, genre, manuscript_context,
                 rag_context, critique_context, llm) -> None:
        """Default narrative: one prompt built by ``_build_prompt``.
        Analyzers with a better strategy for small models override this."""
        prompt, system_prompt = self._build_prompt(
            text, section, genre, manuscript_context,
            rag_context, critique_context,
        )
        # Capture prompts on the section so rated rows can
        # save the real (prompt, narrative) pair for training.
        section.prompt = prompt
        section.system_prompt = system_prompt
        section.narrative = self._generate(llm, prompt, system_prompt,
                                           self.max_tokens)
        self._record_call("Full report", "report", system_prompt, prompt,
                          section.narrative)

    def _generate(self, llm, prompt: str, system_prompt: str,
                  max_tokens: int, temperature: Optional[float] = None,
                  allow_continuation: bool = True) -> str:
        """Call the model with settings suited to its size.

        Local models analyse more reliably at a lower temperature and
        often stop at their token budget mid-thought, so prose answers
        get auto-continuation. Structured line-format answers opt out
        (``allow_continuation=False``): their lines don't end in
        punctuation, so the truncation heuristic misfires and the model
        just repeats the format. ``LLMClient`` reports failures as an
        ``"Error generating text: …"`` string rather than raising; that
        is turned back into an exception so it never lands in a report
        as if it were the model's analysis.
        """
        if temperature is None:
            temperature = 0.3 if self.compact else 0.5
        try:
            response = llm.generate_text(
                prompt, system_prompt, max_tokens=max_tokens,
                temperature=temperature,
                continue_if_truncated=self.compact and allow_continuation)
        except TypeError:
            # Duck-typed clients without the continuation kwarg.
            response = llm.generate_text(
                prompt, system_prompt, max_tokens=max_tokens,
                temperature=temperature)
        response = (response or "").strip()
        if response.startswith("Error generating text:"):
            raise RuntimeError(response[len("Error generating text:"):].strip())
        return response

    def _excerpt(self, text: str, words: int = 2500) -> str:
        """Chapter excerpt sized for the model's context window."""
        limit = min(words, 1200) if self.compact else words
        tokens = text.split()
        clipped = " ".join(tokens[:limit])
        if len(tokens) > limit:
            clipped += f"\n[… excerpt ends; chapter continues for {len(tokens) - limit} more words]"
        return clipped

    def _post_process(self, section: ReportSection) -> None:
        """Hook run after the narrative arrives (e.g. parse tagged lines)."""
        return None

    def _find_chapter(self, chapter_title: str):
        """The manuscript Chapter object for this title, or None."""
        for ch in getattr(self.manuscript, "chapters", None) or []:
            if getattr(ch, "title", "") == chapter_title:
                return ch
        return None

    def _compute(
        self,
        text: str,
        section: ReportSection,
        genre: GenreProfile,
        critique_context: Optional[CritiqueContext],
    ) -> None:
        raise NotImplementedError

    def _build_prompt(
        self,
        text: str,
        section: ReportSection,
        genre: GenreProfile,
        manuscript_context: str,
        rag_context: str,
        critique_context: Optional[CritiqueContext],
    ) -> tuple:
        """Return (prompt, system_prompt). Subclasses override."""
        raise NotImplementedError

    @staticmethod
    def _format_metrics_block(metrics: Dict[str, Any]) -> str:
        """Format metrics dict as a compact text block for prompts."""
        lines = []
        for k, v in metrics.items():
            if isinstance(v, float):
                lines.append(f"- {k}: {v:.2f}")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_context_block(
        self,
        manuscript_context: str,
        rag_context: str,
        critique_context: Optional[CritiqueContext],
        chapter_title: str = "",
        chapter_index: int = 0,
    ) -> str:
        """Build the SHARED CONTEXT block consumed by every analyzer.

        Augmented with two arc-awareness blocks when the data is
        available:

          * **PLOT ANCHOR** — the dramatic-arc context the chapter
            sits inside: stage estimate from chapter position, active
            story promises, plot events near this beat. Surfaced via
            ``self.story_planning``.
          * **SURROUNDING CHAPTERS** — last ~200 words of the previous
            chapter (or its planning summary if prose is absent) and
            the next chapter's planning summary. Lets the analyzer
            judge tonal seams, dropped threads, missing setup.
            Surfaced via ``self.manuscript``.
        """
        parts = []
        if critique_context:
            ctx_lines = []
            if critique_context.style:
                ctx_lines.append(f"Style/Genre: {critique_context.style}")
            if critique_context.tone:
                ctx_lines.append(f"Tone: {critique_context.tone}")
            if critique_context.voice:
                ctx_lines.append(f"Voice: {critique_context.voice}")
            if critique_context.plot_goals:
                ctx_lines.append(f"Plot goals: {critique_context.plot_goals}")
            if critique_context.characters:
                ctx_lines.append(f"Key characters: {critique_context.characters}")
            if critique_context.worldbuilding:
                ctx_lines.append(
                    f"Worldbuilding: {critique_context.worldbuilding}")
            if critique_context.additional_instructions:
                ctx_lines.append(
                    f"Author instructions: "
                    f"{critique_context.additional_instructions}")
            if ctx_lines:
                parts.append("AUTHOR CONTEXT:\n" + "\n".join(ctx_lines))
        voice_line = (self.writer_voice.to_critique_prompt()
                      if self.writer_voice is not None else "")
        if voice_line:
            parts.append(voice_line)

        plot_block = self._format_plot_anchor_block(chapter_index)
        if plot_block:
            parts.append(plot_block)

        surround_block = self._format_surrounding_chapters_block(
            chapter_title)
        if surround_block:
            parts.append(surround_block)

        ms_cap, rag_cap = (500, 800) if self.compact else (1200, 1500)
        if manuscript_context:
            parts.append(
                "MANUSCRIPT CONTEXT:\n" + _truncate(manuscript_context, ms_cap))
        if rag_context:
            parts.append(
                "RELEVANT BACKGROUND (from RAG):\n"
                + _truncate(rag_context, rag_cap))
        return "\n\n".join(parts)

    def _format_plot_anchor_block(self, chapter_index: int) -> str:
        """Render dramatic-arc context: where this chapter sits in
        the story, active promises, plot events near this point.

        Returns "" when no story_planning is wired in. Bounded at
        ~300 tokens of output so the prompt budget stays in hand.
        """
        sp = self.story_planning
        if sp is None:
            return ""
        lines: List[str] = []

        # Stage estimate from chapter position. Crude but useful when
        # the writer hasn't tagged each chapter with an act explicitly.
        total = 0
        try:
            total = len(self.manuscript.chapters) if self.manuscript else 0
        except Exception:
            total = 0
        if total > 0:
            position = (chapter_index + 1) / total
            if position <= 0.25:
                arc_zone = "opening / exposition"
            elif position <= 0.5:
                arc_zone = "rising action toward midpoint"
            elif position <= 0.75:
                arc_zone = "post-midpoint / falling action"
            else:
                arc_zone = "climax / resolution"
            lines.append(
                f"Position: chapter {chapter_index + 1} of {total} — "
                f"{arc_zone}")

        # Main plot one-liner.
        main_plot = (getattr(sp, "main_plot", "") or "").strip()
        if main_plot:
            lines.append(f"Main plot: {_truncate(main_plot, 280)}")

        # Active story promises — what the reader is tracking. Cap at
        # 5 so a project with 20 promises doesn't dominate the block.
        promises = getattr(sp, "promises", None) or []
        if promises:
            promise_lines = []
            for p in promises[:5]:
                title = (getattr(p, "title", "") or "(untitled)").strip()
                desc = (getattr(p, "description", "") or "").strip()
                if desc:
                    promise_lines.append(
                        f"- {title}: {_truncate(desc, 120)}")
                else:
                    promise_lines.append(f"- {title}")
            if promise_lines:
                lines.append(
                    "Active promises:\n" + "\n".join(promise_lines))

        # Plot events grouped by act so the analyzer can see the beat
        # shape. Cap at 12 across the whole list to keep tokens bounded.
        fp = getattr(sp, "freytag_pyramid", None)
        events = getattr(fp, "events", None) if fp else None
        if events:
            event_lines = []
            for ev in events[:12]:
                act = getattr(ev, "act", 0)
                stage = (getattr(ev, "stage", "") or "").replace(
                    "_", " ")
                title = (getattr(ev, "title", "") or "(untitled)").strip()
                desc = (getattr(ev, "description", "") or "").strip()
                head = f"- Act {act} [{stage}] {title}"
                if desc:
                    head += f": {_truncate(desc, 80)}"
                event_lines.append(head)
            if event_lines:
                tail = (f"\n- (… {len(events) - 12} more events not shown)"
                        if len(events) > 12 else "")
                lines.append(
                    "Plot beats (full arc):\n"
                    + "\n".join(event_lines) + tail)

        if not lines:
            return ""
        return "PLOT ANCHOR:\n" + "\n".join(lines)

    def _format_surrounding_chapters_block(
        self,
        current_chapter_title: str,
    ) -> str:
        """Render previous chapter's tail + next chapter's plan so the
        analyzer can judge tonal seams and continuity at the chapter
        boundary. Returns "" when no manuscript is wired in or the
        chapter can't be located in it.
        """
        ms = self.manuscript
        chapters = getattr(ms, "chapters", None) if ms else None
        if not chapters:
            return ""
        idx = -1
        for i, ch in enumerate(chapters):
            if getattr(ch, "title", "") == current_chapter_title:
                idx = i
                break
        if idx < 0:
            return ""

        lines: List[str] = []

        if idx > 0:
            prev_ch = chapters[idx - 1]
            prev_title = (getattr(prev_ch, "title", "")
                          or f"Chapter {idx}")
            prev_content = (getattr(prev_ch, "content", "") or "").strip()
            if prev_content:
                # Last ~200 words of the previous chapter. The TAIL is
                # what the reader carries into this chapter — and what
                # this chapter's opening has to land against.
                tail_words = prev_content.split()[-200:]
                tail = " ".join(tail_words)
                lines.append(
                    f"Previous chapter — \"{prev_title}\" "
                    f"(closing ~{len(tail_words)} words):\n{tail}")
            else:
                # No prose yet — fall back to the planning description
                # so analyzers still see what was intended.
                planning = getattr(prev_ch, "planning", None)
                plan_desc = (getattr(planning, "description", "")
                             or getattr(planning, "outline", "")
                             or "").strip() if planning else ""
                if plan_desc:
                    lines.append(
                        f"Previous chapter — \"{prev_title}\" "
                        f"(planning only, no prose yet):\n"
                        f"{_truncate(plan_desc, 400)}")

        if idx < len(chapters) - 1:
            next_ch = chapters[idx + 1]
            next_title = (getattr(next_ch, "title", "")
                          or f"Chapter {idx + 2}")
            planning = getattr(next_ch, "planning", None)
            plan_desc = (getattr(planning, "description", "")
                         or getattr(planning, "outline", "")
                         or "").strip() if planning else ""
            if plan_desc:
                lines.append(
                    f"Next chapter — \"{next_title}\" "
                    f"(planning):\n{_truncate(plan_desc, 400)}")
            else:
                next_content = (getattr(next_ch, "content", "")
                                or "").strip()
                if next_content:
                    # No plan — show the opening so analyzers can spot
                    # whether this chapter sets up what the next one
                    # actually opens with.
                    head_words = next_content.split()[:120]
                    head = " ".join(head_words)
                    lines.append(
                        f"Next chapter — \"{next_title}\" "
                        f"(opening ~{len(head_words)} words):\n{head}")

        if not lines:
            return ""
        return "SURROUNDING CHAPTERS:\n" + "\n\n".join(lines)


class PacingAnalyzer(_BaseAnalyzer):
    """Genre-aware pacing analysis using sentence-length data + LLM narrative."""
    report_type = ReportType.PACING

    def _compute(self, text, section, genre, critique_context):
        stats = self._get_stats(text)
        total = max(stats.sentence_count, 1)
        long_pct = _safe_pct(
            stats.long_sentences + stats.very_long_sentences, total)
        short_pct = _safe_pct(stats.short_sentences, total)
        avg = stats.avg_sentence_length
        variety = stats.sentence_length_score
        avg_status = _band_status(avg, *genre.avg_sentence_target)
        variety_ok = variety >= genre.variety_score_target
        long_ok = long_pct <= genre.long_sentence_pct_max
        section.metrics = {
            "avg_sentence_length": round(avg, 2),
            "variety_score": round(variety, 1),
            "short_sentence_pct": round(short_pct, 1),
            "long_sentence_pct": round(long_pct, 1),
            "very_long_sentences": stats.very_long_sentences,
            "sentence_count": stats.sentence_count,
            "word_count": stats.word_count,
            "genre_target_avg": list(genre.avg_sentence_target),
            "genre_variety_target": genre.variety_score_target,
            "genre_long_pct_max": genre.long_sentence_pct_max,
        }
        # Findings — deterministic
        lo, hi = genre.avg_sentence_target
        if avg_status == "below":
            section.findings.append(
                f"Average sentence length {avg:.1f} words is below "
                f"the {genre.name} target band ({lo:.0f}–{hi:.0f}). "
                f"Risk: choppy or under-developed scenes.")
            section.suggestions.append(
                "Combine clipped sentences with subordinate clauses "
                "in moments of reflection or description.")
        elif avg_status == "above":
            section.findings.append(
                f"Average sentence length {avg:.1f} words is above "
                f"the {genre.name} target band ({lo:.0f}–{hi:.0f}). "
                f"Risk: drag, lost momentum.")
            section.suggestions.append(
                "Break long sentences in action / tension beats; "
                "keep the long ones for description and interiority.")
        else:
            section.findings.append(
                f"Average sentence length {avg:.1f} words sits inside "
                f"the {genre.name} target band ({lo:.0f}–{hi:.0f}).")
        if not variety_ok:
            section.findings.append(
                f"Sentence-length variety score {variety:.0f}/100 is "
                f"under the {genre.name} target ({genre.variety_score_target:.0f}). "
                f"Risk: monotonous rhythm.")
            section.suggestions.append(
                "Mix short impact sentences with longer textured ones "
                "to break a uniform cadence.")
        else:
            section.findings.append(
                f"Sentence variety {variety:.0f}/100 meets the "
                f"{genre.name} target.")
        if not long_ok:
            section.findings.append(
                f"{long_pct:.1f}% of sentences exceed 21 words "
                f"(genre cap {genre.long_sentence_pct_max:.0f}%). "
                f"Risk: pacing slowdowns, reader skimming.")
            section.suggestions.append(
                "Audit the longest sentences; split when they "
                "carry more than one idea.")
        if short_pct > 70:
            section.findings.append(
                f"{short_pct:.1f}% of sentences are short (<10 words). "
                "Heavy short-sentence diet can read as breathless or stilted.")
        # Summary — one-liner rollup
        flags = sum(1 for f in section.findings if "Risk:" in f)
        if flags == 0:
            section.summary = (
                f"Pacing reads well for {genre.name}: rhythm and "
                f"length distribution sit inside expected bands.")
        else:
            section.summary = (
                f"Pacing has {flags} flag{'s' if flags != 1 else ''} "
                f"against {genre.name} norms — see findings below.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a developmental editor analyzing pacing for a "
            "specific genre. Use the metrics provided as ground truth — "
            "do not invent numbers. Speak to the author in second "
            "person, be specific about where pacing succeeds and "
            "where it stalls. Reference quoted phrases (≤15 words) "
            "from the chapter when calling out a beat. Do NOT rewrite "
            "the prose; describe what to change and why. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name} — {genre.notes}
Target avg sentence length: {genre.avg_sentence_target[0]:.0f}–{genre.avg_sentence_target[1]:.0f} words
Target sentence-variety score: ≥ {genre.variety_score_target:.0f}/100
Target long-sentence cap: ≤ {genre.long_sentence_pct_max:.0f}% of sentences

PACING METRICS (computed):
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a pacing report with these sections:
1. RHYTHM SNAPSHOT — 2-3 sentences on overall cadence vs. genre.
2. SCENE-BY-SCENE PACING — call out 2-4 distinct beats; for each
   give a quoted phrase, label the cadence (sprint / cruise / drift / drag),
   and say whether it suits the moment.
3. WHERE PACING WORKS — 2-3 specific successes.
4. WHERE PACING SLIPS — 2-3 specific issues, each with a quoted
   phrase and a concrete instruction (not a rewrite).
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Does this chapter's
   cadence pick up from the previous chapter's closing without a
   jarring seam? Does its pacing set up the next chapter's planned
   beats? If the adjacent context is absent (first/last chapter,
   no planning), write "N/A — adjacent context unavailable."
6. NEXT REVISION PASS — 3-5 prioritized actions. For each item,
   give TWO lines in this exact format:
       • Passage: "<quote the passage being targeted, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — what to change and why, not a rewrite>
   Each item must point at a real quoted passage from the chapter;
   skip the item if you cannot name a specific passage. Prefix
   each item with **[MAJOR]** or **[MINOR]** indicating severity
   (MAJOR = load-bearing problem; MINOR = within tolerance,
   worth noting).
Keep it under 700 words.
"""
        return prompt.strip(), system_prompt


class VoiceAnalyzer(_BaseAnalyzer):
    """Writer's-voice / consistency analysis."""
    report_type = ReportType.VOICE

    def _compute(self, text, section, genre, critique_context):
        stats = self._get_stats(text)
        adverb_pct = stats.adverb_percentage
        passive_pct = stats.passive_percentage
        sticky_pct = _safe_pct(
            stats.sticky_sentence_count, max(stats.sentence_count, 1))
        cliche_count = stats.cliche_count
        section.metrics = {
            "adverb_pct": round(adverb_pct, 2),
            "passive_pct": round(passive_pct, 2),
            "sticky_sentence_pct": round(sticky_pct, 2),
            "echo_count": stats.echo_count,
            "cliche_count": cliche_count,
            "flesch_reading_ease": round(stats.flesch_reading_ease, 1),
            "flesch_grade_level": round(stats.flesch_grade_level, 1),
            "genre_adverb_max": genre.adverb_pct_max,
            "genre_passive_max": genre.passive_pct_max,
        }
        if adverb_pct > genre.adverb_pct_max:
            section.findings.append(
                f"Adverb usage {adverb_pct:.1f}% above genre cap "
                f"{genre.adverb_pct_max:.1f}%. Voice softens when "
                f"adverbs do the work verbs should.")
            section.suggestions.append(
                "Audit -ly adverbs; replace each with a stronger verb "
                "or cut entirely if the meaning survives.")
        if passive_pct > genre.passive_pct_max:
            section.findings.append(
                f"Passive voice {passive_pct:.1f}% exceeds genre cap "
                f"{genre.passive_pct_max:.1f}%. Reduces immediacy.")
            section.suggestions.append(
                "Promote agent-action constructions in scene moments; "
                "reserve passive for when the actor is intentionally hidden.")
        if sticky_pct > 25:
            section.findings.append(
                f"{sticky_pct:.0f}% of sentences are sticky (heavy in "
                "function words). Voice loses crispness when glue dominates.")
            section.suggestions.append(
                "Re-pattern sticky sentences around concrete nouns and verbs.")
        if cliche_count > 0:
            section.findings.append(
                f"{cliche_count} cliché phrase(s) detected — voice borrows "
                "heat from received language.")
            section.suggestions.append(
                "Replace clichés with images grounded in the POV character's "
                "specific sensory world.")
        if stats.flesch_grade_level > 0:
            grade = stats.flesch_grade_level
            section.metrics["readability_grade"] = round(grade, 1)
        if not section.findings:
            section.findings.append(
                "Voice indicators (adverbs, passive, stickiness, clichés) "
                f"sit inside expected bands for {genre.name}.")
        section.summary = (
            f"Voice diagnostics: adverbs {adverb_pct:.1f}%, passive "
            f"{passive_pct:.1f}%, clichés {cliche_count}, sticky "
            f"sentences {sticky_pct:.0f}% of total.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are an editor with a sharp ear for an author's voice. "
            "Voice is the music of *this writer's* prose — diction, "
            "rhythm, syntactic habits, what gets noticed and what gets "
            "skipped. Use the metrics provided as ground truth. When "
            "discussing voice, quote ≤15 word phrases that capture it. "
            "Do not rewrite — diagnose. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name} — {genre.notes}

VOICE METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a writer's-voice report with these sections:
1. VOICE FINGERPRINT — 2-3 sentences naming the distinctive
   habits of this prose (diction, syntax, stance, what it
   notices). Quote a phrase that captures it.
2. WHAT THE VOICE DOES WELL — 2-3 specific successes.
3. WHERE VOICE BLURS — 2-3 places the voice slips toward generic
   prose, with a quoted phrase each.
4. CONSISTENCY WITH AUTHOR INTENT — given the stated tone/voice
   in AUTHOR CONTEXT (if any), call out drift.
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Is the voice
   consistent with the prior chapter's closing voice? Does it set
   up the voice the next chapter (per planning) will inhabit?
   Write "N/A — adjacent context unavailable." if either side is
   missing.
6. PRESCRIPTIVE NEXT PASS — 3-5 prioritized actions. For each item,
   give TWO lines in this exact format:
       • Passage: "<quote the passage where voice slips or could
         sharpen, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — diction / rhythm / cadence shift to make,
         and what voice it should land closer to>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 700 words.
"""
        return prompt.strip(), system_prompt


class TensionAnalyzer(_BaseAnalyzer):
    """Tension-on-the-page analysis using lexical signals + LLM."""
    report_type = ReportType.TENSION

    # Lexical signals for narrative tension
    TENSION_WORDS = {
        "fear", "afraid", "panic", "dread", "terror", "horror", "shudder",
        "tremble", "shiver", "cold", "tight", "tense", "stiff", "rigid",
        "flinch", "wince", "blood", "knife", "gun", "blade", "wound",
        "scream", "gasp", "froze", "frozen", "danger", "threat", "warning",
        "silent", "silence", "still", "watch", "watching", "stalking",
        "edge", "pulse", "heart", "breath", "breathless", "close",
        "behind", "shadow", "darkness",
    }

    def _compute(self, text, section, genre, critique_context):
        stats = self._get_stats(text)
        words = re.findall(r"\b[a-zA-Z']+\b", text.lower())
        tension_hits = sum(1 for w in words if w in self.TENSION_WORDS)
        tension_pct = _safe_pct(tension_hits, len(words))
        # Action-vs-reflection ratio: short sentences + verbs of motion
        # vs. long sentences + interiority cues
        motion_verbs = {
            "ran", "rushed", "slammed", "shoved", "pulled", "grabbed",
            "kicked", "punched", "fled", "leapt", "jumped", "raced",
            "threw", "dropped", "fell", "rose", "spun", "turned",
        }
        reflect_cues = {
            "thought", "remembered", "wondered", "considered",
            "realized", "knew", "felt", "imagined", "recalled",
        }
        action_hits = sum(1 for w in words if w in motion_verbs)
        reflect_hits = sum(1 for w in words if w in reflect_cues)
        # Question / sentence-fragment density (signal for unease)
        question_count = text.count("?")
        section.metrics = {
            "tension_lexicon_pct": round(tension_pct, 2),
            "tension_lexicon_hits": tension_hits,
            "action_verb_hits": action_hits,
            "reflection_verb_hits": reflect_hits,
            "questions": question_count,
            "short_sentence_pct": round(
                _safe_pct(stats.short_sentences,
                          max(stats.sentence_count, 1)), 1),
            "word_count": stats.word_count,
        }
        if tension_pct < 0.4 and action_hits < 2:
            section.findings.append(
                "Low tension lexicon and few motion verbs — risks reading "
                "as expository / static. Genre fiction needs felt stakes "
                "on the page.")
            section.suggestions.append(
                "Layer in a body-level reaction (breath, pulse, posture) "
                "where the stakes are highest in the scene.")
        if reflect_hits > action_hits * 2.5 and action_hits < 3:
            section.findings.append(
                "Reflection cues outweigh action verbs by a wide margin. "
                "Interiority can flatten tension if it crowds out moment-to-moment beats.")
            section.suggestions.append(
                "Move reflection into the spaces *between* action; don't "
                "let it replace the beat.")
        if tension_pct > 1.5:
            section.findings.append(
                f"Tension lexicon density {tension_pct:.2f}% is unusually "
                "high — risk of fatigue or melodrama if every beat is at 11.")
            section.suggestions.append(
                "Vary intensity: the chapter's loudest moment lands harder "
                "if the surrounding beats breathe.")
        if not section.findings:
            section.findings.append(
                "Tension signals look balanced for the chapter — sensory "
                "and motion cues present, not over- or under-driven.")
        section.summary = (
            f"Tension density {tension_pct:.2f}%, action verbs "
            f"{action_hits}, reflection cues {reflect_hits}, "
            f"questions {question_count}.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are an editor diagnosing narrative tension on the "
            "page — moment-to-moment friction, unanswered questions, "
            "stakes the reader can feel. Distinguish *plot tension* "
            "(what hangs over the chapter) from *scene tension* (the "
            "second-by-second pull). Quote ≤15 word phrases. Do not rewrite. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name} — {genre.notes}

TENSION METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a tension report with these sections:
1. STAKES ON THE PAGE — 2-3 sentences on what the reader feels
   is at risk *in this chapter*. Quote a phrase that crystallizes it.
2. MOMENT-TO-MOMENT TENSION — call out 2-4 beats; rate each
   (slack / simmer / squeeze / spike) and explain.
3. UNANSWERED QUESTIONS — what the chapter dangles in front of
   the reader.
4. WHERE TENSION RELEASES TOO EARLY — places friction dissolves
   prematurely, with a quoted phrase.
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Does the chapter
   inherit pressure from the previous chapter's closing? Does it
   leave residual pressure that the next chapter (per planning)
   can pick up? Write "N/A — adjacent context unavailable."
   when context is missing.
6. NEXT REVISION PASS — 3-5 prioritized actions. For each item,
   give TWO lines in this exact format:
       • Passage: "<quote the passage where tension drops, plateaus,
         or could spike harder, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — tighten / release / delay / withhold, and what
         pressure to apply>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 700 words.
"""
        return prompt.strip(), system_prompt


class PlotAnalyzer(_BaseAnalyzer):
    """Plot / promise / structure analysis."""
    report_type = ReportType.PLOT

    def __init__(self, primary_llm=None, story_planning=None,
                 manuscript=None, chapter_synopsis: str = ""):
        super().__init__(primary_llm,
                         story_planning=story_planning,
                         manuscript=manuscript)
        # ``story_planning`` is now also stored on the base via the
        # super().__init__ call, but PlotAnalyzer historically read it
        # off self.story_planning; the base class assigns there too,
        # so this stays consistent.
        self.chapter_synopsis = chapter_synopsis

    def _compute(self, text, section, genre, critique_context):
        # Mostly model-driven; deterministic side computes a few
        # structural fingerprints and pulls in story planning data.
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        # Approximate scene boundaries via blank-line gaps + dialog density shifts
        scene_breaks = text.count("\n\n\n") + text.count("***") + text.count("# ")
        word_count = len(text.split())
        promise_count = 0
        promise_titles: List[str] = []
        if self.story_planning is not None:
            try:
                promises = list(self.story_planning.promises or [])
            except Exception:
                promises = []
            promise_count = len(promises)
            promise_titles = [p.title for p in promises[:8] if getattr(p, "title", None)]
        section.metrics = {
            "word_count": word_count,
            "paragraph_count": len(paragraphs),
            "scene_break_signals": scene_breaks,
            "story_promises_total": promise_count,
            "synopsis_present": bool(self.chapter_synopsis),
        }
        if not self.chapter_synopsis:
            section.findings.append(
                "No chapter synopsis is registered. Without an intent "
                "statement the plot report can only describe what's on the "
                "page, not whether it lands what the chapter was meant to land.")
            section.suggestions.append(
                "Fill in the chapter's planning description / outline "
                "so plot reports can compare execution against intent.")
        if promise_count == 0:
            section.findings.append(
                "Story Promises list is empty in the project plan. Plot "
                "drift is harder to detect without explicit reader commitments.")
            section.suggestions.append(
                "Add 2-5 Story Promises (in Story Planning) so this report "
                "can audit whether each chapter advances them.")
        else:
            section.findings.append(
                f"Project carries {promise_count} Story Promise"
                f"{'s' if promise_count != 1 else ''} — the model will "
                "audit whether this chapter advances them.")
        if scene_breaks == 0 and word_count > 1500:
            section.findings.append(
                "No scene break signals detected in a long chapter. "
                "Long unbroken runs can blur scene transitions.")
            section.suggestions.append(
                "Mark scene shifts with a blank line + transition line "
                "or a section divider (***).")
        section.summary = (
            f"Plot scaffolding: {word_count:,} words, "
            f"{len(paragraphs)} paragraphs, "
            f"{promise_count} project promise(s) in scope.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a developmental editor focused on plot mechanics: "
            "what the chapter does to advance the story, whether its "
            "beats earn their place, and whether reader promises are "
            "kept or broken. Be direct about structure problems. "
            "Quote ≤15 word phrases when calling out a beat. Do not "
            "rewrite the prose. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        promises_block = ""
        if self.story_planning and getattr(self.story_planning, "promises", None):
            lines = []
            for p in self.story_planning.promises[:8]:
                title = getattr(p, "title", "") or "(untitled)"
                desc = (getattr(p, "description", "") or "")[:160]
                lines.append(f"- {title}: {desc}")
            if lines:
                promises_block = "PROJECT STORY PROMISES:\n" + "\n".join(lines)
        synopsis_block = (
            f"CHAPTER INTENT (from planning):\n{self.chapter_synopsis}"
            if self.chapter_synopsis else "")
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name}

PLOT METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{synopsis_block}

{promises_block}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a plot report with these sections:
1. WHAT THE CHAPTER DOES — in plot mechanics terms: what changes
   from start to end? Quote a phrase from the turning point.
2. INTENT vs. EXECUTION — does the chapter execute the planned
   intent (above)? If no synopsis, describe what intent the prose
   suggests and whether it's clear.
3. PROMISE TRACKING — for each Story Promise in scope: does this
   chapter advance, complicate, fulfil, or ignore it? Be specific.
4. STRUCTURAL CONCERNS — pacing-of-plot issues: missing setup,
   skipped consequence, off-page payoff, unmotivated turn.
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Does this chapter
   follow logically from the previous chapter's closing event?
   Does it set up the next chapter's planned beats (no missing
   bridges, no skipped turns)? Call out any threads dropped
   between adjacent chapters. Write "N/A — adjacent context
   unavailable." when context is missing.
6. NEXT REVISION PASS — 3-5 prioritized plot-level actions. For
   each item, give TWO lines in this exact format:
       • Passage: "<quote the beat / pivot / promise-handoff being
         critiqued, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — add setup, redirect consequence, sharpen turn,
         move payoff onscreen — name the plot move>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 800 words.
"""
        return prompt.strip(), system_prompt


class DialogAnalyzer(_BaseAnalyzer):
    """Dialog density, tag use, and voice differentiation."""
    report_type = ReportType.DIALOG

    def _compute(self, text, section, genre, critique_context):
        stats = self._get_stats(text)
        dialog_pct = stats.dialogue_percentage
        overused = stats.overused_dialogue_tags
        # Tag adverbs (e.g. "she said angrily") — heuristic
        tag_adverb_rx = re.compile(
            r'["”]\s*,?\s*(?:he|she|they|i|we|[A-Z][a-z]+)\s+'
            r'(?:said|asked|replied|whispered|shouted|muttered)\s+'
            r'(\w+ly)\b',
            re.IGNORECASE,
        )
        tag_adverbs = tag_adverb_rx.findall(text)
        # Said-bookisms: how many tag-tokens are not 'said' / 'asked'
        bookism_tags = [
            t for t in stats.dialogue_tags
            if t not in {"said", "asked", "replied", "answered"}
        ]
        bookism_count = sum(stats.dialogue_tags.get(t, 0) for t in bookism_tags)
        section.metrics = {
            "dialogue_pct": round(dialog_pct, 2),
            "dialog_tag_total": sum(stats.dialogue_tags.values()),
            "overused_tags": overused,
            "tag_adverbs": len(tag_adverbs),
            "bookism_tag_count": bookism_count,
            "genre_dialog_target": list(genre.dialog_pct_target),
        }
        lo, hi = genre.dialog_pct_target
        if dialog_pct < lo:
            section.findings.append(
                f"Dialog density {dialog_pct:.1f}% is below the "
                f"{genre.name} band ({lo:.0f}–{hi:.0f}%). "
                "Risk: reader distance, info-dumped scenes.")
            section.suggestions.append(
                "Convert reported speech ('he told her that…') into "
                "spoken lines where character voice can land.")
        elif dialog_pct > hi:
            section.findings.append(
                f"Dialog density {dialog_pct:.1f}% is above the "
                f"{genre.name} band ({lo:.0f}–{hi:.0f}%). "
                "Risk: scenes drift talky, action and setting recede.")
            section.suggestions.append(
                "Stitch action beats and sensory anchors between "
                "exchanges so dialog stays grounded.")
        if overused:
            section.findings.append(
                f"Overused dialog tags: {', '.join(overused[:5])}. "
                "Repetition draws attention to the tag instead of the line.")
            section.suggestions.append(
                "Default to 'said' / 'asked'; let action beats carry "
                "tone instead of decorative tag verbs.")
        if len(tag_adverbs) >= 3:
            section.findings.append(
                f"Found {len(tag_adverbs)} tag adverb(s) (e.g. 'said angrily'). "
                "Tag adverbs often label the line instead of letting it land.")
            section.suggestions.append(
                "Cut tag adverbs; if the line needs the adverb, the line "
                "needs rewriting.")
        if bookism_count > max(stats.dialogue_tags.get("said", 0), 1):
            section.findings.append(
                "Said-bookisms (declared / barked / hissed) outnumber "
                "neutral 'said' tags — calls attention to the tag.")
        if not section.findings:
            section.findings.append(
                "Dialog density and tag hygiene look healthy for "
                f"{genre.name}.")
        section.summary = (
            f"Dialog at {dialog_pct:.1f}% of words "
            f"(genre {lo:.0f}–{hi:.0f}%); "
            f"{section.metrics['dialog_tag_total']} tag tokens; "
            f"{len(tag_adverbs)} tag adverbs.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are an editor focused on dialog craft: voice "
            "differentiation between speakers, tag economy, action "
            "beats, subtext. Use the metrics as ground truth. Quote "
            "≤15 word phrases. Don't rewrite — diagnose. "
            "**Every actionable suggestion must anchor to a specific "
            "line or exchange in the chapter — quote the line, then "
            "explain how that exact line could be strengthened. No "
            "generic advice. Diagnostic observations stay in the "
            "diagnostic sections (CONTINUITY included); every "
            "actionable item lives ONLY in the final actionable "
            "section. Do not mix the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name}

DIALOG METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a dialog report with these sections:
1. WHO SOUNDS LIKE WHO — voice differentiation: do speakers
   sound distinct on the page? Quote one line per speaker that
   shows their voice (or fails to).
2. TAG HYGIENE — are tags doing too much (said-bookisms, tag
   adverbs, tag verbs labeling tone)?
3. SUBTEXT vs. ON-THE-NOSE — places dialog states what should
   be implied, with a quoted phrase.
4. ACTION BEATS — do beats anchor speakers in space, or do
   conversations float?
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Are the speakers'
   voices consistent with how they sounded in the previous
   chapter? Does the dialogue close threads or open ones the next
   chapter can pick up? Write "N/A — adjacent context
   unavailable." when context is missing.
6. NEXT REVISION PASS — 3-5 prioritized dialog-level actions. For
   each item, give TWO lines in this exact format:
       • Passage: "<quote the line / tag / exchange being
         critiqued, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — cut the adverb, replace the tag, add a beat,
         redirect to subtext, sharpen voice — name the move>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 700 words.
"""
        return prompt.strip(), system_prompt


class StyleAnalyzer(_BaseAnalyzer):
    """Sentence-level style: passive, adverbs, clichés, echoes, sticky."""
    report_type = ReportType.STYLE

    def _compute(self, text, section, genre, critique_context):
        stats = self._get_stats(text)
        section.metrics = {
            "passive_pct": round(stats.passive_percentage, 2),
            "adverb_pct": round(stats.adverb_percentage, 2),
            "sticky_count": stats.sticky_sentence_count,
            "echo_count": stats.echo_count,
            "cliche_count": stats.cliche_count,
            "flesch_reading_ease": round(stats.flesch_reading_ease, 1),
            "flesch_grade_level": round(stats.flesch_grade_level, 1),
            "genre_passive_max": genre.passive_pct_max,
            "genre_adverb_max": genre.adverb_pct_max,
        }
        if stats.passive_percentage > genre.passive_pct_max:
            section.findings.append(
                f"Passive voice {stats.passive_percentage:.1f}% above "
                f"genre cap {genre.passive_pct_max:.1f}%.")
            section.suggestions.append(
                "Rewrite passive constructions in scene moments toward "
                "active subject-verb-object.")
        if stats.adverb_percentage > genre.adverb_pct_max:
            section.findings.append(
                f"Adverb usage {stats.adverb_percentage:.1f}% above "
                f"genre cap {genre.adverb_pct_max:.1f}%.")
            section.suggestions.append(
                "Replace -ly adverbs with stronger verbs.")
        if stats.echo_count > 5:
            section.findings.append(
                f"{stats.echo_count} word echoes within close proximity. "
                "Repetition draws the eye and flattens prose.")
            section.suggestions.append(
                "Vary repeated content words; reserve repetition for "
                "rhetorical emphasis.")
        if stats.sticky_sentence_count > max(stats.sentence_count, 1) * 0.25:
            section.findings.append(
                f"{stats.sticky_sentence_count} sticky sentences (heavy "
                "in glue words). Reduces sentence-level energy.")
        if stats.cliche_count > 0:
            section.findings.append(
                f"{stats.cliche_count} cliché(s) detected: "
                f"{', '.join(stats.cliches[:5])}.")
            section.suggestions.append(
                "Replace clichés with concrete, character-rooted images.")
        if stats.flesch_reading_ease and stats.flesch_grade_level:
            grade = stats.flesch_grade_level
            section.metrics["readability_grade"] = round(grade, 1)
        if not section.findings:
            section.findings.append(
                f"Style indicators sit inside expected bands for {genre.name}.")
        section.summary = (
            f"Style: passive {stats.passive_percentage:.1f}%, "
            f"adverbs {stats.adverb_percentage:.1f}%, "
            f"echoes {stats.echo_count}, clichés {stats.cliche_count}, "
            f"reading ease {stats.flesch_reading_ease:.0f}.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a line editor diagnosing sentence-level style. "
            "Use metrics as ground truth. Quote ≤15 word phrases when "
            "calling out a problem. Don't rewrite. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name} — {genre.notes}

STYLE METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a style report with these sections:
1. PROSE FINGERPRINT — 2-3 sentences naming style strengths.
   Quote a sentence that exemplifies the strongest moves.
2. REDUNDANCY & DRAG — places sentences carry filler, echoes,
   or stickiness, with quoted phrases.
3. PASSIVE / ADVERB / CLICHÉ — concrete examples to address.
4. SENTENCE-LEVEL VARIETY — does sentence shape vary, or
   default to one pattern?
5. CONTINUITY — 2-3 sentences using the SURROUNDING CHAPTERS
   context (if present). Does the sentence-level style match the
   prior chapter's closing prose? Are there sudden shifts in
   register / cadence at the chapter boundary that read as seams?
   Write "N/A — adjacent context unavailable." when context is
   missing.
6. NEXT REVISION PASS — 3-5 prioritized line-level actions. For
   each item, give TWO lines in this exact format:
       • Passage: "<quote the sentence or fragment being
         critiqued, ≤25 words>"
       • How to strengthen: <concrete instruction tied to THIS
         passage — replace adverb with verb, cut filler word, vary
         sentence shape, kill the cliché — name the move>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 700 words.
"""
        return prompt.strip(), system_prompt


class CanonAnalyzer(_BaseAnalyzer):
    """Canon (character + worldbuilding) fidelity and opportunity.

    Two-sided lens that the other analyzers don't cover:
      * **Fidelity** — when a character from the project appears in
        the chapter, do they act consistent with their established
        personality, motivations, fears, speaking style? When a
        place / faction / technology is named, does the prose
        respect what the project says about it?
      * **Opportunity** — which canon elements (visible in the RAG
        block + chapter planning's featured characters / locations)
        could enrich this chapter but aren't being drawn on?

    Relies on the RAG retrieval pulling in the relevant entities
    plus their graph-neighbor expansion (already in place for the
    critique flow); doesn't try to re-detect entity mentions itself.
    """
    report_type = ReportType.CANON

    def _compute(self, text, section, genre, critique_context):
        # Deterministic side: cross-check planning's featured set
        # against actual chapter mentions. Useful as a fingerprint
        # the LLM can comment on without re-deriving it.
        featured_characters: List[str] = []
        featured_locations: List[str] = []
        if self.manuscript:
            for ch in getattr(self.manuscript, "chapters", []) or []:
                if getattr(ch, "title", "") == section.chapter_title:
                    planning = getattr(ch, "planning", None)
                    if planning:
                        featured_characters = list(
                            getattr(planning, "characters_featured", [])
                            or [])
                        featured_locations = list(
                            getattr(planning, "locations", []) or [])
                    break
        lower = text.lower()
        mentioned_featured = [
            name for name in featured_characters
            if name and name.lower() in lower]
        missing_featured = [
            name for name in featured_characters
            if name and name.lower() not in lower]
        section.metrics = {
            "featured_characters": len(featured_characters),
            "featured_mentioned": len(mentioned_featured),
            "featured_missing": len(missing_featured),
            "featured_locations": len(featured_locations),
        }
        if missing_featured:
            section.findings.append(
                f"Planned character{'s' if len(missing_featured) > 1 else ''} "
                f"not named in chapter prose: "
                f"{', '.join(missing_featured[:5])}"
                + (f" (+{len(missing_featured) - 5} more)"
                   if len(missing_featured) > 5 else ""))
        if not featured_characters and not featured_locations:
            section.findings.append(
                "Chapter planning lists no featured characters or "
                "locations — canon fidelity relies entirely on what "
                "the prose names.")
        else:
            section.findings.append(
                f"Chapter planning intends "
                f"{len(featured_characters)} character(s) and "
                f"{len(featured_locations)} location(s) featured.")
        section.summary = (
            f"Canon: {len(mentioned_featured)}/"
            f"{len(featured_characters)} planned characters land on "
            f"the page; {len(featured_locations)} location(s) planned.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a developmental editor focused on canon fidelity "
            "and canon opportunity. **Fidelity**: when a character or "
            "world element from the project appears in the chapter, "
            "do they act / present consistent with their established "
            "personality, motivations, history, and the project's "
            "rules? **Opportunity**: what canon elements visible in "
            "the RELEVANT BACKGROUND or PLOT ANCHOR could enrich "
            "the chapter — name them and say how. "
            "Treat the RAG context and PLOT ANCHOR as the canonical "
            "source of truth; flag any conflict between prose and "
            "canon. Quote ≤15 word phrases when calling things out. "
            "Do not rewrite — diagnose. "
            "**Every actionable suggestion must anchor to a specific "
            "passage or a specific canon element — quote the passage "
            "or name the element, then explain how to fix the "
            "fidelity break or how to draw on the underused element. "
            "No generic advice. Diagnostic observations stay in the "
            "diagnostic sections (CONTINUITY included); every "
            "actionable item lives ONLY in the final actionable "
            "section. Do not mix the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name}

CANON METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS:
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a canon report with these sections:
1. CANON FIDELITY — for each project character or world element
   that appears in the chapter, judge alignment. Quote a phrase
   showing in-character (or out-of-character) behavior. Flag any
   factual conflict with project canon (e.g., faction allegiance,
   technology rules, personality drift). Be specific — name the
   character/element and the canon fact.
2. WORLD CONSISTENCY — does the chapter respect the project's
   established worldbuilding (factions, places, technologies,
   cultures)? Call out any drift between prose and canon.
3. UNDERUSED OPPORTUNITIES — what's in the RAG block / PLOT
   ANCHOR that this chapter could draw on but doesn't? Name 2-3
   specific canon elements (a character's fear, a place's
   atmosphere, a faction's pressure, a technology's limit) and
   say where in the chapter they could land.
4. PROMISES TOUCHED — for any Story Promise that intersects this
   chapter's characters or world, is it advanced / complicated /
   ignored?
5. CONTINUITY — 2-3 sentences using the PLOT ANCHOR and
   SURROUNDING CHAPTERS context (if present). Are characters
   carrying state from the previous chapter? Does the chapter
   set up canon elements the next chapter (per planning) will
   need? Write "N/A — adjacent context unavailable." when
   context is missing.
6. NEXT REVISION PASS — 3-6 prioritized canon actions. For each
   item, give TWO lines in this exact format:
       • Passage or Element: "<quote the passage being critiqued
         OR name the canon element being suggested, ≤25 words>"
       • How to strengthen: <concrete instruction — either fix
         the fidelity break (what the character/element would
         actually do/be) OR show how to draw on the underused
         element (which scene, which beat, what it contributes)>
   Mix fidelity-fix items and opportunity-add items. Skip the
   item if you cannot name a specific passage or canon element.
Keep under 800 words.
"""
        return prompt.strip(), system_prompt


class GrammarAnalyzer(_BaseAnalyzer):
    """Grammar, spelling, and hard-to-read paragraphs.

    Three deterministic dimensions the other analyzers don't cover:

      * **Spelling** via pyspellchecker — catches typos with high
        precision. Skips words already in the standard dictionary
        and a small list of common proper-noun shapes.
      * **Grammar** via language_tool_python (LanguageTool). Lazy-
        loaded inside _compute and wrapped in try/except — the engine
        needs a Java runtime, so absence gets logged once and the
        section continues with spelling + hard-paragraphs only.
      * **Hard-to-read paragraphs** — pure-Python thresholds: word
        count > 250, avg sentence length > 30 words, or > 50% of
        sentences > 25 words. Each flagged with the opening line so
        the writer can find it in their draft.

    Severity classification: spelling and grammar issues are MAJOR
    when more than a small handful surface (5 misspellings or 3
    grammar errors). Hard-to-read paragraphs are MAJOR when 3+ are
    flagged. Below those thresholds they fall to MINOR.
    """
    report_type = ReportType.GRAMMAR

    # Class-level caches so we don't reinstantiate heavy tools per
    # chapter. ``None`` means "not yet attempted", ``False`` means
    # "attempted and unavailable (don't retry)", instance means ready.
    _spellchecker = None
    _langtool = None

    @classmethod
    def _get_spellchecker(cls):
        if cls._spellchecker is False:
            return None
        if cls._spellchecker is None:
            try:
                from spellchecker import SpellChecker
                cls._spellchecker = SpellChecker()
            except Exception as e:
                print(f"[grammar] pyspellchecker unavailable: {e}")
                cls._spellchecker = False
                return None
        return cls._spellchecker

    @classmethod
    def _get_langtool(cls):
        if cls._langtool is False:
            return None
        if cls._langtool is None:
            try:
                import language_tool_python
                cls._langtool = language_tool_python.LanguageTool(
                    "en-US")
            except Exception as e:
                # No Java, no network, no jar — degrade gracefully.
                print(f"[grammar] language_tool_python unavailable: {e}")
                cls._langtool = False
                return None
        return cls._langtool

    # Tokens that look like proper nouns we shouldn't flag as typos —
    # heuristic, supplements the spellchecker dictionary.
    _CAP_WORD = re.compile(r"^[A-Z][a-zA-Z'’\-]+$")

    def _compute(self, text, section, genre, critique_context):
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        section.metrics["paragraph_count"] = len(paragraphs)

        # --- Hard-to-read paragraphs (always available) ---
        hard = self._find_hard_paragraphs(paragraphs)
        section.metrics["hard_paragraph_count"] = len(hard)
        if hard:
            opening_previews = [
                f"¶{i + 1}: \"{p['opening']}\""
                for i, p in enumerate(hard[:5])
            ]
            note = (
                f"Found {len(hard)} hard-to-read paragraph(s): "
                + "; ".join(opening_previews)
                + (f" (+{len(hard) - 5} more)"
                   if len(hard) > 5 else ""))
            if len(hard) >= 3:
                section.major_issues.append(note)
            else:
                section.minor_issues.append(note)
            section.findings.append(note)

        # --- Spelling (deterministic; degrades silently) ---
        misspelled = self._check_spelling(text)
        section.metrics["misspelled_count"] = len(misspelled)
        if misspelled:
            sample = misspelled[:8]
            note = (
                f"Possible misspellings ({len(misspelled)}): "
                + ", ".join(sample)
                + (f" (+{len(misspelled) - 8} more)"
                   if len(misspelled) > 8 else ""))
            if len(misspelled) >= 5:
                section.major_issues.append(note)
            else:
                section.minor_issues.append(note)
            section.findings.append(note)

        # --- Grammar via LanguageTool (lazy + graceful) ---
        grammar_issues = self._check_grammar(text)
        section.metrics["grammar_issue_count"] = len(grammar_issues)
        if grammar_issues:
            # Show a small sample so the writer sees what's flagged
            # without us dumping the whole list into the section.
            sample_lines = []
            for issue in grammar_issues[:6]:
                sample_lines.append(
                    f"({issue['rule']}) \"{issue['preview']}\" "
                    f"— {issue['message']}")
            note = (
                f"Found {len(grammar_issues)} grammar issue(s). "
                f"Sample:\n  "
                + "\n  ".join(sample_lines)
                + (f"\n  (+{len(grammar_issues) - 6} more)"
                   if len(grammar_issues) > 6 else ""))
            if len(grammar_issues) >= 3:
                section.major_issues.append(note)
            else:
                section.minor_issues.append(note)
            section.findings.append(note)
        elif self._get_langtool() is None and not section.findings:
            section.findings.append(
                "Grammar checker (LanguageTool) unavailable — "
                "install Java to enable grammar diagnostics. "
                "Spelling + hard-paragraph checks still ran.")

        if (not hard and not misspelled and not grammar_issues
                and self._get_langtool() is not None):
            note = "No spelling, grammar, or readability flags detected."
            section.findings.append(note)
            section.strengths.append(note)
        # Even when there ARE issues, surface a per-dimension strength
        # for any dimension that came back clean. Writers benefit from
        # knowing "your grammar is fine, only the long paragraph
        # tripped" rather than just seeing the issue list.
        if not misspelled and self._get_spellchecker() is not None:
            section.strengths.append(
                "Spelling: no likely misspellings detected.")
        if (not grammar_issues
                and self._get_langtool() is not None
                and (hard or misspelled)):
            section.strengths.append(
                "Grammar: no rule-checker issues detected.")
        if not hard and (misspelled or grammar_issues):
            section.strengths.append(
                "Readability: no hard-to-read paragraphs flagged "
                "(every paragraph under length / sentence-density "
                "thresholds).")

        section.summary = (
            f"Grammar: {section.metrics.get('grammar_issue_count', 0)} "
            f"grammar issue(s), "
            f"{section.metrics.get('misspelled_count', 0)} possible "
            f"misspelling(s), "
            f"{section.metrics.get('hard_paragraph_count', 0)} "
            f"hard-to-read paragraph(s).")

    def _find_hard_paragraphs(
        self,
        paragraphs: List[str],
    ) -> List[Dict[str, Any]]:
        """Return paragraphs flagged as hard-to-read with the reasons.

        Three independent signals; any one of them triggers a flag.
        Each result includes an ``opening`` (first ~80 chars) so the
        writer can locate the paragraph in their draft.
        """
        flagged: List[Dict[str, Any]] = []
        sentence_re = re.compile(r"[.!?]+\s+")
        for i, para in enumerate(paragraphs):
            words = para.split()
            wc = len(words)
            sentences = [s for s in sentence_re.split(para) if s.strip()]
            sc = max(len(sentences), 1)
            avg_sent_len = wc / sc
            long_sent_count = sum(
                1 for s in sentences if len(s.split()) > 25)
            long_sent_ratio = long_sent_count / sc
            reasons: List[str] = []
            if wc > 250:
                reasons.append(f"very long ({wc} words)")
            if avg_sent_len > 30:
                reasons.append(
                    f"avg sentence ~{avg_sent_len:.0f} words")
            if long_sent_ratio > 0.5 and sc >= 2:
                reasons.append(
                    f"{int(long_sent_ratio * 100)}% of sentences "
                    f">25 words")
            if reasons:
                opening = para[:80].replace("\n", " ")
                if len(para) > 80:
                    opening = opening.rstrip() + "…"
                flagged.append({
                    "index": i + 1,
                    "opening": opening,
                    "word_count": wc,
                    "avg_sentence_length": round(avg_sent_len, 1),
                    "reasons": reasons,
                })
        return flagged

    def _check_spelling(self, text: str) -> List[str]:
        """Return likely misspellings. Excludes proper-noun-shaped
        tokens to keep noise down — names of characters/places are
        flagged elsewhere via the canon report's RAG retrieval, not
        here. Returns empty list if pyspellchecker isn't available."""
        sc = self._get_spellchecker()
        if sc is None:
            return []
        # Tokenize words (preserve apostrophes for contractions).
        from src.utils.proofing import word_tokens
        words = word_tokens(text)          # contractions whole, any apostrophe
        if not words:
            return []
        # Filter out: proper-noun-shaped tokens (capitalized) and very
        # short / digits. Then run the spell checker on what remains.
        candidates = []
        seen: set = set()
        for w in words:
            if w in seen:
                continue
            seen.add(w)
            if len(w) < 4:
                continue
            if self._CAP_WORD.match(w):
                continue
            candidates.append(w.lower())
        misspelled = sc.unknown(candidates)
        # Stable order = order of first appearance.
        ordered: List[str] = []
        added: set = set()
        for w in candidates:
            if w in misspelled and w not in added:
                ordered.append(w)
                added.add(w)
        return ordered

    def _check_grammar(
        self,
        text: str,
    ) -> List[Dict[str, Any]]:
        """Run LanguageTool over the chapter. Returns one dict per
        issue with rule/preview/message. Skips capitalization-only
        rules to dodge false positives on proper nouns and stylized
        prose. Empty list if LanguageTool isn't available."""
        tool = self._get_langtool()
        if tool is None:
            return []
        try:
            matches = tool.check(text)
        except Exception as e:
            print(f"[grammar] LanguageTool check failed: {e}")
            return []
        issues: List[Dict[str, Any]] = []
        SKIP_RULES = {
            "UPPERCASE_SENTENCE_START",  # Proper-noun start flags
            "MORFOLOGIK_RULE_EN_US",     # Spelling — covered separately
            "EN_QUOTES",                 # Smart-quote nags
        }
        for m in matches[:60]:  # cap to avoid runaway output
            rule_id = getattr(m, "ruleId", "")
            if rule_id in SKIP_RULES:
                continue
            offset = getattr(m, "offset", 0)
            length = getattr(m, "errorLength", 0)
            preview = text[offset:offset + max(length, 1) + 30]
            preview = preview.replace("\n", " ")[:80]
            issues.append({
                "rule": rule_id or "Grammar",
                "preview": preview,
                "message": (getattr(m, "message", "") or "")[:200],
            })
        return issues

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a copy editor focused on mechanical correctness "
            "and readability — grammar, punctuation, spelling, and "
            "passages that are hard to read because of length or "
            "syntactic density. You receive the deterministic findings "
            "(spell checker + LanguageTool + paragraph metrics) as "
            "ground truth. Don't re-derive them; explain and prioritize. "
            "Quote ≤25 word phrases when calling out a problem. Do not "
            "rewrite the prose. "
            "**Every actionable suggestion must anchor to a specific "
            "passage in the chapter — quote the passage, then explain "
            "how that exact passage could be strengthened. No generic "
            "advice. Diagnostic observations stay in the diagnostic "
            "sections (CONTINUITY included); every actionable item "
            "lives ONLY in the final actionable section. Do not mix "
            "the two.**")
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name}

GRAMMAR METRICS:
{self._format_metrics_block(section.metrics)}

DETERMINISTIC FINDINGS (treat as ground truth):
{chr(10).join(f'- {f}' for f in section.findings) or '- (none)'}

{ctx}

CHAPTER TEXT (first 2500 words):
{self._excerpt(text, 2500)}

Write a grammar & readability report with these sections:
1. SPELLING — for the misspellings flagged above (if any), say
   which are real typos vs. project-specific terms (character /
   place / faction names, neologisms). Quote the misspelled token
   with one word of context on each side.
2. GRAMMAR — for the grammar issues flagged above (if any),
   explain which are real errors vs. intentional style choices.
   Quote the flagged passage.
3. HARD-TO-READ PARAGRAPHS — for each flagged paragraph (if any),
   explain the dominant reason (length / sentence density / long
   sentence ratio) and what makes it hard for the eye. Quote the
   opening of the paragraph.
4. PUNCTUATION & MECHANICS — call out 2-3 issues the rule-based
   checkers miss (comma splices, dialogue punctuation,
   missing/extra ellipses, em-dash drift). Quote each.
5. CONTINUITY — 2-3 sentences using the SURROUNDING CHAPTERS
   context (if present). Does the chapter's punctuation /
   formatting / dialogue conventions match the previous chapter's?
   Write "N/A — adjacent context unavailable." when context is
   missing.
6. NEXT REVISION PASS — 3-6 prioritized actions. For each item,
   give THREE lines in this exact format:
       • [MAJOR] or [MINOR] severity tag
       • Passage: "<quote the passage being targeted, ≤25 words>"
       • How to strengthen: <concrete instruction — fix the
         specific error, break the long sentence at X, split the
         paragraph after Y, etc.>
   Prefix each item with **[MAJOR]** or **[MINOR]** indicating
   severity (MAJOR = load-bearing problem, would hurt the reader's
   experience; MINOR = within tolerance, worth noting). Skip the
   item if you cannot name a specific passage.
Keep under 700 words.
"""
        return prompt.strip(), system_prompt


# ── Orchestrator ─────────────────────────────────────────────────────


# Map ReportType → analyzer factory. Orchestrator uses this so adding
# a new report type is a one-line registration.
_TAGGED_MARKER = "=== TAGGED SUMMARY ==="
_SPEECH_VERBS = (r"said|asked|replied|whispered|shouted|muttered|called|"
                 r"answered|snapped|murmured|yelled|cried|told")


def _chapter_number(chapter, chapter_index: int) -> int:
    n = getattr(chapter, "number", 0) if chapter is not None else 0
    return n or (chapter_index + 1)


def _bullets(items: List[str], empty: str = "- (none)") -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


def _md_list(label: str, items: List[str]) -> str:
    if not items:
        return ""
    return f"**{label}:**\n" + "\n".join(f"- {i}" for i in items) + "\n"


class _CanonAnalyzerMixin:
    """Shared LLM strategy for the Character and Worldbuilding reports.

    * Cloud models get one rich prompt; if they forget the tagged
      summary, a short repair call extracts it from their prose.
    * Local models (Gemma, Llama, Phi…) get several small focused
      prompts — one per character / small batch of world elements —
      each carrying only the passages that matter, a fixed answer
      format and a worked example. Small models do far better on many
      narrow questions than on one sprawling one, and the evidence
      comes from the whole chapter instead of just its opening.
    """
    TAG_FORMAT = ""        # the tagged-line spec, used by the repair pass
    EXPECTED_TAGS = ()     # at least one must be present to skip repair

    def _narrate(self, text, section, genre, manuscript_context,
                 rag_context, critique_context, llm):
        self._focused_done = False
        if self.compact:
            prompts = self._narrate_focused(text, section, llm)
            section.prompt = "\n\n---\n\n".join(prompts)
            self._focused_done = True
            return
        super()._narrate(text, section, genre, manuscript_context,
                         rag_context, critique_context, llm)
        self._repair_tags_if_missing(section, llm)

    def _repair_tags_if_missing(self, section, llm) -> None:
        from src.ai.canon_index import parse_tag_block
        tags = parse_tag_block(section.narrative, _TAGGED_MARKER)
        if not section.narrative or any(t in tags for t in self.EXPECTED_TAGS):
            return
        prompt = (
            "Below is an editor's report. Extract its findings as lines in "
            "exactly this format, one per line, nothing else:\n"
            f"{self.TAG_FORMAT}\n\nREPORT:\n{section.narrative[:6000]}")
        repair_system = ("You convert reports into structured lines. "
                         "Output only the lines.")
        try:
            fixed = self._generate(llm, prompt, repair_system,
                                   500, temperature=0.1)
        except Exception as e:
            print(f"[critique] tag repair failed: {e}")
            return
        self._record_call("Extract findings", "repair", repair_system,
                          prompt, fixed)
        section.narrative = f"{section.narrative}\n\n{_TAGGED_MARKER}\n{fixed}"

    def _ask(self, llm, prompt: str, system: str, max_tokens: int,
             failures: List[str], what: str, block_start: str = "") -> str:
        """One focused, structured call. Returns the cleaned reply."""
        try:
            reply = self._generate(llm, prompt, system, max_tokens,
                                   allow_continuation=False)
        except Exception as e:
            failures.append(f"{what}: {e}")
            return ""
        reply = _first_answer(reply, block_start)
        self._record_call(what, "focused", system, prompt, reply)
        return reply


def _attribute_items(section: "ReportSection") -> None:
    """Map each list item to the model call whose output contains it,
    so an item rating can be saved against the prompt that produced it.
    Items no call contains (deterministic findings) stay unmapped."""
    if not section.calls:
        return
    lists = [section.strengths, section.major_issues, section.minor_issues,
             section.suggestions] + list(section.extra_lists.values())
    for items in lists:
        for item in items:
            if item in section.item_sources:
                continue
            probes = [item]
            parts = re.split(r"\s+[—–]\s+", item, maxsplit=1)
            if len(parts) == 2:
                probes.append(parts[1])           # drop "Name — " prefix
            for call in section.calls:
                out = call.get("output", "")
                if any(len(p) >= 12 and p[:60] in out for p in probes):
                    section.item_sources[item] = call["id"]
                    break


_BLEED_RX = re.compile(
    r"\s+(?:ELEMENT\s+\d+\s*:|NAME\s*:|PORTRAYAL\s*:|EXAMPLE\b|PASSAGES\s*:|RECORD\s*:).*$")
_NONE_RX = re.compile(r"^(?:none|n/?a|nothing(?: notable)?|no (?:drift|issues?))\b[.!]?$",
                      re.IGNORECASE)


def _first_answer(reply: str, block_start: str = "") -> str:
    """Keep only the model's first answer.

    Small models often restate the whole format (or carry on into the
    next imaginary item) after answering; anything from a second
    ``block_start`` header onward is dropped.
    """
    reply = (reply or "").strip()
    if block_start:
        first = reply.find(block_start)
        second = reply.find(block_start, first + len(block_start)) if first >= 0 else -1
        if second > 0:
            reply = reply[:second].rstrip()
    return reply


def _clean_items(items: List[str]) -> List[str]:
    """Drop bled-in prompt fragments, "none" items and duplicates."""
    out = []
    for it in items:
        it = _BLEED_RX.sub("", it).strip()
        tail = re.split(r"\s+[—–-]\s+|:\s+", it, maxsplit=1)
        if not it or _NONE_RX.match(it) or (len(tail) == 2 and _NONE_RX.match(tail[1].strip())):
            continue
        if it not in out:
            out.append(it)
    return out


def _item_name(item: str) -> str:
    return re.split(r"\s*(?:\||[—–]|\s-\s|:)\s*", item, maxsplit=1)[0].strip().strip("*\"'")


def _keep_named(items: List[str], allowed: List[str]) -> List[str]:
    """Keep items whose leading name is one we asked about (guards
    against small models inventing extra entries)."""
    allowed_l = {a.lower() for a in allowed}
    out = []
    for it in items:
        name = _item_name(it).lower()
        if name in allowed_l or any(name.startswith(a) or a.startswith(name)
                                    for a in allowed_l if name):
            out.append(it)
    return out


class CharacterAnalyzer(_CanonAnalyzerMixin, _BaseAnalyzer):
    """Character portrayal vs. the project's character records.

    For every project character who appears in the chapter, compares
    what the page shows (actions, dialog, interiority) with their
    profile — personality, traits, speaking style, motivations, fears,
    want/need, lie, worldview — and with where their personality arc
    says they should be at this chapter. Reports what's on track, what
    drifts, and concrete recommendations to stay on course (or to
    update the profile when the drift is an intentional discovery).

    Deterministic side: who appears and how often, planned-but-absent
    characters, their actual dialog lines, thin profiles that limit
    the comparison, and named speakers with no character record.
    """
    report_type = ReportType.CHARACTER
    max_tokens = 1600
    MAX_CHARACTERS = 6
    LOCAL_MAX_CHARACTERS = 4
    EXPECTED_TAGS = ("ON TRACK", "DRIFT", "RECOMMEND")
    TAG_FORMAT = (
        "- [ON TRACK] <Name> — <what aligns with the record>\n"
        "- [DRIFT] <Name> — <record field>: <how the page differs>\n"
        "- [RECOMMEND] <Name> — <concrete action>\n"
        "- [PROFILE UPDATE] <Name> — <field>: <suggested value>")

    _FOCUSED_SYSTEM = (
        "You are a developmental editor checking one fictional character "
        "against the author's record of them. Be specific and brief. Quote "
        "the chapter. Follow the answer format exactly.")
    _FOCUSED_EXAMPLE = (
        "FORMAT EXAMPLE (made-up character, not from this book):\n"
        "PORTRAYAL: Pell Quorry hesitates before every choice and lets his sister decide.\n"
        "[ON TRACK] Fears (failure) — \"He let Ysolde decide, again.\"\n"
        "[DRIFT] Fears (heights) — climbs the bell tower without a pause; record says he dreads heights\n"
        "[DRIFT] Speaking style (formal) — swears casually at the guard; the scene doesn't set it up\n"
        "[VOICE] Mostly fits: \"I would not presume, my lady.\" matches his formal register\n"
        "[ARC] Behind: the checkpoint says he starts asserting himself by now\n"
        "[RECOMMEND] In the gate scene, let Pell overrule Ysolde once so the arc moves")

    def _narrate_focused(self, text, section, llm) -> List[str]:
        from src.ai.canon_index import (
            _name_variants, format_character_profile, passages_mentioning,
            parse_tagged_lines,
        )
        prompts, failures, blocks = [], [], []
        arc_notes: List[str] = []
        for c in self._appearing[:self.LOCAL_MAX_CHARACTERS]:
            lines = self._dialog.get(c.name) or []
            evidence = passages_mentioning(text, _name_variants(c.name), 450)
            from src.ai.canon_index import CHARACTER_PROFILE_FIELDS
            checklist = [label for attr, label in CHARACTER_PROFILE_FIELDS
                         if (getattr(c, attr, "") or "").strip()]
            if getattr(c, "personality_traits", None):
                checklist.insert(0, "Key traits")
            prompt = (
                "CHARACTER RECORD (the author's intent):\n"
                f"{format_character_profile(c, self._chapter_number, max_field=160)}\n\n"
                + ("HOW THEY TALK IN THIS CHAPTER:\n"
                   + "\n".join(f'» "{l}"' for l in lines) + "\n\n" if lines else "")
                + f"PASSAGES FROM THE CHAPTER WHERE {c.name.upper()} APPEARS:\n{evidence}\n\n"
                f"Compare the passages with the record. Reply with ONLY these lines, in this order:\n"
                f"PORTRAYAL: <2-3 sentences: what the chapter shows of {c.name}>\n"
                "[ON TRACK] <record item> — <short quote showing it>\n"
                "[DRIFT] <record field> — <what the page does instead; say if it is earned growth>\n"
                "[VOICE] <does their dialog fit their speaking style? quote a line>\n"
                "[ARC] <on course / ahead / behind the arc checkpoint, and why>\n"
                "[RECOMMEND] <one concrete change to a named passage, or a record field to update>\n"
                "Repeat [ON TRACK], [DRIFT] and [RECOMMEND] lines as needed. "
                "Write \"[DRIFT] none\" if nothing drifts.\n\n"
                f"{self._FOCUSED_EXAMPLE}\n\n"
                + (f"Check EACH of these record fields against what {c.name} does and says: "
                   + ", ".join(checklist) + ". An action that goes against a listed fear, "
                   "want or moral code is a [DRIFT] unless the passage shows why.\n"
                   if checklist else "")
                + f"Now answer for {c.name} only:")
            prompts.append(prompt)
            reply = self._ask(llm, prompt, self._FOCUSED_SYSTEM, 550,
                              failures, c.name, block_start="PORTRAYAL:")
            if not reply:
                continue
            tags = {k: _clean_items(v) for k, v in parse_tagged_lines(reply).items()}
            tags = {k: (v[:1] if k in ("PORTRAYAL", "VOICE", "ARC") else v)
                    for k, v in tags.items() if v}
            if not tags:
                blocks.append(f"## {c.name}\n{reply}\n")
                continue
            section.strengths.extend(f"{c.name} — {x}" for x in tags.get("ON TRACK", []))
            section.major_issues.extend(f"{c.name} — {x}" for x in tags.get("DRIFT", []))
            section.suggestions.extend(f"{c.name} — {x}" for x in tags.get("RECOMMEND", []))
            arc_notes.extend(f"{c.name}: {x}" for x in tags.get("ARC", []))
            blocks.append("\n".join(b for b in (
                f"## {c.name}",
                " ".join(tags.get("PORTRAYAL", [])),
                _md_list("On track", tags.get("ON TRACK", [])),
                _md_list("Drift", tags.get("DRIFT", [])),
                _md_list("Voice", tags.get("VOICE", [])),
                _md_list("Arc position", tags.get("ARC", [])),
                _md_list("Recommendations", tags.get("RECOMMEND", [])),
            ) if b))
        if arc_notes:
            section.extra_lists["Arc position"] = arc_notes

        # Unprofiled speakers: who are they, and do they need a record?
        if self._unprofiled:
            items = []
            for name, _, _ in self._unprofiled[:5]:
                ev = passages_mentioning(text, [name], 120)
                items.append(f"NAME: {name}\nPASSAGES:\n{ev}")
            prompt = (
                "These people speak in the chapter but have no character record.\n"
                "For each, reply with ONLY one line:\n"
                "[NEW CHARACTER] <Name> — <who they are and their role here, 1 sentence>; "
                "<needs a record: yes/no>\n\n"
                "FORMAT EXAMPLE (made-up name, not from this book):\n"
                "[NEW CHARACTER] Old Vashti Brom — ferrywoman who warns the heroes off "
                "the river; needs a record: yes\n\n" + "\n\n".join(items)
                + "\n\nAnswer for these names only: "
                + ", ".join(n for n, _, _ in self._unprofiled[:5]))
            prompts.append(prompt)
            reply = self._ask(llm, prompt, self._FOCUSED_SYSTEM, 300,
                              failures, "unprofiled speakers")
            new_chars = _keep_named(
                _clean_items(parse_tagged_lines(reply).get("NEW CHARACTER", [])),
                [n for n, _, _ in self._unprofiled[:5]])
            if new_chars:
                section.extra_lists["Profile updates to consider"] = [
                    f"New character: {x}" for x in new_chars]
                blocks.append(_md_list("New or unprofiled characters", new_chars))

        skipped = self._appearing[self.LOCAL_MAX_CHARACTERS:]
        if skipped:
            section.minor_issues.append(
                "Local-model mode analysed the "
                f"{self.LOCAL_MAX_CHARACTERS} most-present characters; not covered: "
                + ", ".join(c.name for c in skipped) + ".")
        for f in failures:
            section.findings.append(f"(model call failed — {f})")
        section.narrative = "\n\n".join(blocks)
        return prompts

    def _compute(self, text, section, genre, critique_context):
        from src.ai.canon_index import (
            CHARACTER_PROFILE_FIELDS, arc_checkpoint, character_name_variants,
            collect_world_entities, find_mentions, find_unknown_proper_nouns,
        )
        from src.ai.writer_voice import character_dialog_samples

        characters = list(getattr(self.project, "characters", None) or [])
        chapter = self._find_chapter(section.chapter_title)
        self._chapter_number = _chapter_number(chapter, section.chapter_index)
        mentions = find_mentions(text, character_name_variants(characters))
        by_name = {c.name: c for c in characters}
        appearing = sorted(mentions, key=lambda n: -mentions[n]["count"])
        self._appearing = [by_name[n] for n in appearing[:self.MAX_CHARACTERS]]
        self._mentions = mentions
        all_names = [c.name for c in characters]
        self._dialog = {
            c.name: character_dialog_samples(text, c.name, max_lines=5,
                                             other_names=all_names)
            for c in self._appearing}

        planned_raw = list(getattr(getattr(chapter, "planning", None),
                                   "characters_featured", None) or [])
        by_id = {getattr(c, "id", ""): c.name for c in characters}
        planned = [by_id.get(p, p) for p in planned_raw if p]
        missing_planned = [p for p in planned if p not in mentions]

        thin = []
        for c in self._appearing:
            filled = sum(bool((getattr(c, a, "") or "").strip())
                         for a, _ in CHARACTER_PROFILE_FIELDS)
            filled += bool(getattr(c, "personality_traits", None))
            if filled < 3:
                thin.append((c.name, filled))
        with_arc = [c.name for c in self._appearing
                    if any(arc_checkpoint(c, self._chapter_number))]

        world_names = [e.name for e in collect_world_entities(
            getattr(self.project, "worldbuilding", None))]
        unknown = find_unknown_proper_nouns(text, all_names + world_names)
        speech_rx = lambda n: re.compile(
            rf"(\b{re.escape(n)}\s+(?:{_SPEECH_VERBS})\b)|"
            rf"(\b(?:{_SPEECH_VERBS})\s+{re.escape(n)}\b)")
        self._unprofiled = [(n, k, ex) for n, k, ex in unknown
                            if speech_rx(n).search(text)]

        section.metrics = {
            "characters_in_project": len(characters),
            "characters_appearing": len(mentions),
            "analyzed": len(self._appearing),
            "planned_featured": len(planned),
            "planned_missing": len(missing_planned),
            "with_arc_checkpoint": len(with_arc),
            "unprofiled_speakers": len(self._unprofiled),
        }

        if not characters:
            section.major_issues.append(
                "The project has no character records, so portrayal can't be "
                "checked against profiles. Add characters to enable this report.")
        elif not mentions:
            section.minor_issues.append(
                "No project character is named in this chapter.")
        if self._appearing:
            section.strengths.append(
                "Appearing: " + ", ".join(
                    f"{c.name} ({mentions[c.name]['count']}×, "
                    f"{len(self._dialog[c.name])} line(s) of dialog)"
                    for c in self._appearing))
        landed = [p for p in planned if p in mentions]
        if landed:
            section.strengths.append(
                f"Planned characters on the page: {', '.join(landed)}.")
        if missing_planned:
            section.major_issues.append(
                "Planned for this chapter but missing from the prose: "
                + ", ".join(missing_planned) + ".")
        for name, filled in thin:
            section.minor_issues.append(
                f"{name}'s profile is thin ({filled} voice/trait field(s) filled) — "
                "the comparison can only be as specific as the profile.")
        if self._unprofiled:
            section.extra_lists["Speakers with no character record"] = [
                f"{n} ({k}×) — e.g. \"{ex}\"" for n, k, ex in self._unprofiled]
        section.findings = (section.strengths + section.major_issues
                            + section.minor_issues)
        section.summary = (
            f"Characters: {len(mentions)} of {len(characters)} project characters "
            f"appear; {len(missing_planned)} planned character(s) missing; "
            f"{len(self._unprofiled)} speaker(s) without a profile.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        from src.ai.canon_index import format_character_profile
        system_prompt = (
            "You are a developmental editor who tracks characters across a "
            "novel. Compare how each character is portrayed ON THE PAGE with "
            "their CHARACTER RECORD (profile + arc checkpoints). The record is "
            "the author's stated intent. Judge alignment trait by trait, "
            "quote ≤20-word passages as evidence, and distinguish a real "
            "drift (character acts against their record without the story "
            "earning it) from earned growth (the change is motivated on the "
            "page and fits the arc). Recommendations must be concrete: name "
            "the passage and what to change, or name the profile field the "
            "author should update if the drift is a deliberate discovery. "
            "Do not rewrite the chapter.")
        profiles = []
        for c in self._appearing:
            block = format_character_profile(c, self._chapter_number)
            lines = self._dialog.get(c.name) or []
            if lines:
                block += "\nLines they speak in this chapter:\n" + "\n".join(
                    f'  » "{l}"' for l in lines)
            ex = self._mentions[c.name]["examples"]
            if ex:
                block += "\nWhere they appear (examples):\n" + "\n".join(
                    f"  · {e}" for e in ex)
            profiles.append(block)
        unprofiled = section.extra_lists.get("Speakers with no character record", [])
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title} (chapter {self._chapter_number})
Genre: {genre.name}

DETERMINISTIC FINDINGS:
{_bullets(section.findings)}

CHARACTER RECORDS (author's intent) for characters appearing in this chapter:
{chr(10).join(profiles) if profiles else '(no project characters appear)'}

SPEAKERS WITH NO CHARACTER RECORD:
{_bullets(unprofiled)}

{ctx}

CHAPTER TEXT (first 3000 words):
{self._excerpt(text, 3000)}

Write a character report:

For EACH character in CHARACTER RECORDS, a "## <Name>" section with:
  - Portrayal: what the chapter shows of them (action, choice, interiority), with a quote.
  - On track: which record items are visibly honoured (trait, fear, want, worldview…), with evidence.
  - Drift: anything that contradicts the record or arc checkpoint. Quote the passage, name the
    record field it conflicts with, and say whether it reads as drift or as earned growth.
  - Voice: does their dialog match their speaking style and quirks? Quote a line.
  - Arc position: given the arc checkpoint (and the next planned one, if any), are they where the
    story needs them? Too far ahead, behind, or on course?

Then:
## Ensemble
  How the characters play off each other here; is anyone flattened or redundant?
## New or unprofiled characters
  For each speaker with no record (and any other new named person), what the chapter
  establishes about them and whether they deserve a character record.
## Recommendations to stay on track
  3-6 prioritized items. Each names the character, the passage or beat, and the change — or
  the profile field to update if the page has outgrown the record.

Finish with this machine-readable block, one item per line, no other text after it:
{_TAGGED_MARKER}
- [ON TRACK] <Name> — <what aligns with the record>
- [DRIFT] <Name> — <record field>: <how the page differs, ≤30 words>
- [RECOMMEND] <Name> — <concrete action>
- [PROFILE UPDATE] <Name> — <field>: <suggested value the record should gain>
"""
        return prompt.strip(), system_prompt

    def _post_process(self, section):
        from src.ai.canon_index import parse_tag_block, strip_tagged_block
        if getattr(self, "_focused_done", False):
            return
        tags = parse_tag_block(section.narrative, _TAGGED_MARKER)
        section.strengths.extend(tags.get("ON TRACK", []))
        section.major_issues.extend(tags.get("DRIFT", []))
        section.suggestions.extend(tags.get("RECOMMEND", []))
        if tags.get("PROFILE UPDATE"):
            section.extra_lists["Profile updates to consider"] = tags["PROFILE UPDATE"]
        section.narrative = strip_tagged_block(section.narrative, _TAGGED_MARKER)


class WorldbuildingAnalyzer(_CanonAnalyzerMixin, _BaseAnalyzer):
    """Worldbuilding fidelity against the project's world records.

    Three outputs:
      * **New elements** — names (places, factions, technologies,
        customs, creatures…) the chapter introduces that have no entry
        in the Worldbuilding section, with a suggested category and a
        draft entry so the author can add them.
      * **On track** — established elements the chapter uses in line
        with their records.
      * **Differences** — places where the prose contradicts what the
        records say (a faction's allegiance, a technology's limits, a
        place's geography), with which side probably needs to change.

    Deterministic side: which world elements are referenced (by
    category), planned locations missing from the prose, and unknown
    proper nouns that are candidates for new elements.
    """
    report_type = ReportType.WORLDBUILDING
    max_tokens = 1600
    MAX_REFERENCED = 14
    LOCAL_MAX_REFERENCED = 9     # three batches of three
    LOCAL_MAX_CANDIDATES = 10    # two batches of five
    EXPECTED_TAGS = ("NEW", "ON TRACK", "DIFFERS", "RECOMMEND")
    TAG_FORMAT = (
        "- [NEW] <Name> | <category> | <draft entry>\n"
        "- [ON TRACK] <Element> — <how the page honours the record>\n"
        "- [DIFFERS] <Element> — page: <what the prose says>; record: <what canon says>\n"
        "- [RECOMMEND] <concrete action>")
    _CATEGORIES = ("Place, Faction, Culture, Technology, Magic system, Creature, "
                   "Plant, Historical event, Myth, Institution, Custom, Object, Other")
    _FOCUSED_SYSTEM = (
        "You are a continuity editor for a novel's invented world. The author's "
        "records are canon. Be specific and brief. Follow the answer format exactly.")

    def _narrate_focused(self, text, section, llm) -> List[str]:
        from src.ai.canon_index import passages_mentioning, parse_tagged_lines
        prompts, failures = [], []
        on_track, differs, new_items = [], [], []

        refs = self._referenced[:self.LOCAL_MAX_REFERENCED]
        for i in range(0, len(refs), 3):
            batch = refs[i:i + 3]
            parts = []
            for n, e in enumerate(batch, 1):
                ev = passages_mentioning(text, [e.name], 180)
                parts.append(f"ELEMENT {n}: {e.label}\n"
                             f"RECORD: {e.summary or '(no description)'}\n"
                             f"CHAPTER PASSAGES:\n{ev}")
            prompt = (
                "For each world element below, compare what the chapter says with "
                "the author's record. Reply with ONLY one line per element:\n"
                "[ON TRACK] <Element> — <how the chapter matches the record, with a short quote>\n"
                "or\n"
                "[DIFFERS] <Element> — page: <what the chapter says>; record: <what the "
                "record says>; <minor stretch / real contradiction>\n\n"
                "FORMAT EXAMPLE (made-up elements, not from this book):\n"
                "[ON TRACK] Quillon Compact — taxes the docks (\"the Compact's tithe-men\"), as the record's \"controls trade\" says\n"
                "[DIFFERS] Vorrel Span — page: \"collapsed years ago\"; record: still standing and guarded; real contradiction\n\n"
                + "\n\n".join(parts)
                + "\n\nAnswer for these elements only: "
                + ", ".join(e.name for e in batch))
            prompts.append(prompt)
            tags = parse_tagged_lines(self._ask(
                llm, prompt, self._FOCUSED_SYSTEM, 400, failures,
                "elements " + ", ".join(e.name for e in batch)))
            names = [e.name for e in batch]
            on_track += _keep_named(_clean_items(tags.get("ON TRACK", [])), names)
            differs += _keep_named(_clean_items(tags.get("DIFFERS", [])), names)

        cands = self._new_candidates[:self.LOCAL_MAX_CANDIDATES]
        for i in range(0, len(cands), 5):
            batch = cands[i:i + 5]
            parts = [f"NAME: {name}\nPASSAGES:\n{passages_mentioning(text, [name], 120)}"
                     for name, _, _ in batch]
            prompt = (
                "These names appear in the chapter but have no worldbuilding record. "
                "For each, reply with ONLY one line:\n"
                "[NEW] <Name> | <category> | <draft entry from what the chapter "
                "establishes, ≤25 words>\n"
                "or\n"
                "[SKIP] <Name> — <why: ordinary word, a person (belongs in Characters), or too vague>\n"
                f"Categories: {self._CATEGORIES}.\n\n"
                "FORMAT EXAMPLE (made-up names, not from this book):\n"
                "[NEW] Thessaly Wharf | Place | Brine-soaked market quarter by the harbor where "
                "smugglers trade after dark\n"
                "[SKIP] Tuesday — ordinary word\n\n" + "\n\n".join(parts)
                + "\n\nAnswer for these names only, one line each: "
                + ", ".join(n for n, _, _ in batch))
            prompts.append(prompt)
            tags = parse_tagged_lines(self._ask(
                llm, prompt, self._FOCUSED_SYSTEM, 400, failures, "new elements"))
            for item in _keep_named(_clean_items(tags.get("NEW", [])),
                                    [n for n, _, _ in batch]):
                bits = [b.strip() for b in item.split("|")]
                # People belong to the Character report.
                if len(bits) >= 2 and bits[1].lower() in {"character", "person", "people"}:
                    continue
                new_items.append(item)

        if new_items:
            section.extra_lists["New elements (not in worldbuilding)"] = [
                " — ".join(p.strip() for p in x.split("|") if p.strip())
                for x in new_items]
        section.strengths.extend(on_track)
        section.major_issues.extend(differs)
        # Recommendations follow directly from the findings — reliable
        # without asking a small model to synthesise them.
        for d in differs:
            element = re.split(r"\s+[—–-]\s+", d, maxsplit=1)[0]
            section.suggestions.append(
                f"Reconcile {element}: change the passage or update its record ({d}).")
        for x in new_items:
            bits = [p.strip() for p in x.split("|")]
            if len(bits) >= 2:
                section.suggestions.append(
                    f"Add {bits[0]} to Worldbuilding ({bits[1]}).")
        skipped = (len(self._referenced) - len(refs), len(self._new_candidates) - len(cands))
        if any(skipped):
            section.minor_issues.append(
                f"Local-model mode checked the {len(refs)} most-referenced elements and "
                f"{len(cands)} most frequent new names; {skipped[0]} element(s) and "
                f"{skipped[1]} name(s) not checked.")
        for f in failures:
            section.findings.append(f"(model call failed — {f})")
        section.narrative = "\n".join(b for b in (
            _md_list("New elements", section.extra_lists.get(
                "New elements (not in worldbuilding)", [])),
            _md_list("On track", on_track),
            _md_list("Differences", differs),
            _md_list("Recommendations", section.suggestions),
        ) if b)
        return prompts

    def _compute(self, text, section, genre, critique_context):
        from src.ai.canon_index import (
            collect_world_entities, find_mentions, find_unknown_proper_nouns,
            world_name_variants,
        )
        entities = collect_world_entities(getattr(self.project, "worldbuilding", None))
        characters = list(getattr(self.project, "characters", None) or [])
        mentions = find_mentions(text, world_name_variants(entities))
        by_name: Dict[str, Any] = {}
        for e in entities:
            by_name.setdefault(e.name, e)
        referenced = sorted(mentions, key=lambda n: -mentions[n]["count"])
        self._referenced = [by_name[n] for n in referenced[:self.MAX_REFERENCED]]
        self._mentions = mentions

        known = [e.name for e in entities] + [c.name for c in characters]
        unknown = find_unknown_proper_nouns(text, known, limit=15)
        speech_rx = re.compile(rf"\b(?:{_SPEECH_VERBS})\b")
        # Names that only ever act as speakers are people — those belong
        # to the Character report, not here.
        self._new_candidates = []
        for name, n, ex in unknown:
            if re.search(rf"\b{re.escape(name)}\s+(?:{_SPEECH_VERBS})\b", text) \
                    or re.search(rf"\b(?:{_SPEECH_VERBS})\s+{re.escape(name)}\b", text):
                continue
            self._new_candidates.append((name, n, ex))

        chapter = self._find_chapter(section.chapter_title)
        planned_locs = list(getattr(getattr(chapter, "planning", None),
                                    "locations", None) or [])
        lower = text.lower()
        missing_locs = [l for l in planned_locs if l and l.lower() not in lower]

        cats = Counter(by_name[n].category for n in mentions)
        section.metrics = {
            "world_elements_in_project": len(entities),
            "elements_referenced": len(mentions),
            "categories_referenced": ", ".join(f"{k} ({v})" for k, v in cats.most_common()),
            "new_element_candidates": len(self._new_candidates),
            "planned_locations_missing": len(missing_locs),
        }

        if not entities:
            section.major_issues.append(
                "The Worldbuilding section is empty, so the chapter can't be "
                "checked against world records — every named element is new.")
        if self._referenced:
            section.strengths.append(
                "Draws on established worldbuilding: " + ", ".join(
                    f"{e.name} [{e.category}]" for e in self._referenced[:8])
                + (f" (+{len(mentions) - 8} more)" if len(mentions) > 8 else "") + ".")
        elif entities:
            section.minor_issues.append(
                "No established world element is named in this chapter.")
        if missing_locs:
            section.major_issues.append(
                "Planned location(s) not on the page: " + ", ".join(missing_locs) + ".")
        if self._new_candidates:
            section.extra_lists["New elements (not in worldbuilding)"] = [
                f"{n} ({k}×) — e.g. \"{ex}\"" for n, k, ex in self._new_candidates]
        section.findings = (section.strengths + section.major_issues
                            + section.minor_issues)
        section.summary = (
            f"Worldbuilding: {len(mentions)} established element(s) referenced; "
            f"{len(self._new_candidates)} candidate new element(s) not in the "
            f"Worldbuilding section.")

    def _build_prompt(self, text, section, genre, manuscript_context,
                      rag_context, critique_context):
        system_prompt = (
            "You are a continuity editor for a novel's world. The WORLD RECORDS "
            "are the author's canon. Compare the chapter against them: identify "
            "elements the chapter introduces that have no record, confirm where "
            "the chapter honours the records, and flag where it contradicts them. "
            "Quote ≤20-word passages from the chapter and cite the record you are "
            "comparing against. When prose and record disagree, say which one "
            "likely needs to change and why. Do not rewrite the chapter.")
        records = []
        for e in self._referenced:
            ex = self._mentions[e.name]["examples"][:2]
            line = f"- {e.label}: {e.summary or '(no description in record)'}"
            if ex:
                line += "\n    on the page: " + " / ".join(f'"{x}"' for x in ex)
            records.append(line)
        candidates = section.extra_lists.get("New elements (not in worldbuilding)", [])
        ctx = self._format_context_block(
            manuscript_context, rag_context, critique_context,
            chapter_title=section.chapter_title,
            chapter_index=section.chapter_index)
        prompt = f"""
Chapter: {section.chapter_title}
Genre: {genre.name}

DETERMINISTIC FINDINGS:
{_bullets(section.findings)}

WORLD RECORDS for elements this chapter references:
{chr(10).join(records) if records else '(none referenced)'}

CANDIDATE NEW ELEMENTS (proper nouns with no world or character record):
{_bullets(candidates)}

{ctx}

CHAPTER TEXT (first 3000 words):
{self._excerpt(text, 3000)}

Write a worldbuilding report:

## New elements
Everything the chapter introduces that the Worldbuilding section doesn't record — the
candidates above (drop any that are clearly ordinary words or people) plus unnamed but
specific additions (a new custom, rule of magic/technology, creature, landmark, institution).
For each: what it appears to be, the category it belongs in, a one-or-two-sentence draft
entry from what the page establishes, and whether it fits or strains existing canon.

## On track
Established elements the chapter uses consistently with their records. Quote the passage.

## Differences
Where the prose contradicts or stretches a record (geography, allegiance, history, rules,
capabilities, culture). Quote the passage, cite the record, rate it (minor stretch / real
contradiction), and say whether the prose or the record should change.

## Underused canon
1-3 established elements relevant to this chapter's events that could add texture, and where.

## Recommendations
3-6 prioritized actions: fix a contradiction, add a record, or deepen an element.

Finish with this machine-readable block, one item per line, no other text after it:
{_TAGGED_MARKER}
- [NEW] <Name> | <category> | <draft entry, ≤30 words>
- [ON TRACK] <Element> — <how the page honours the record>
- [DIFFERS] <Element> — page: <what the prose says>; record: <what canon says>
- [RECOMMEND] <concrete action>
"""
        return prompt.strip(), system_prompt

    def _post_process(self, section):
        from src.ai.canon_index import parse_tag_block, strip_tagged_block
        if getattr(self, "_focused_done", False):
            return
        tags = parse_tag_block(section.narrative, _TAGGED_MARKER)
        new = tags.get("NEW", [])
        if new:
            # The model's list is classified and drafted — prefer it over
            # the raw proper-noun candidates.
            section.extra_lists["New elements (not in worldbuilding)"] = [
                " — ".join(p.strip() for p in item.split("|") if p.strip())
                for item in new]
        section.strengths.extend(tags.get("ON TRACK", []))
        section.major_issues.extend(tags.get("DIFFERS", []))
        section.suggestions.extend(tags.get("RECOMMEND", []))
        section.narrative = strip_tagged_block(section.narrative, _TAGGED_MARKER)


_ANALYZER_REGISTRY: Dict[ReportType, Any] = {
    ReportType.PACING: PacingAnalyzer,
    ReportType.VOICE: VoiceAnalyzer,
    ReportType.TENSION: TensionAnalyzer,
    ReportType.PLOT: PlotAnalyzer,
    ReportType.DIALOG: DialogAnalyzer,
    ReportType.STYLE: StyleAnalyzer,
    ReportType.CANON: CanonAnalyzer,
    ReportType.GRAMMAR: GrammarAnalyzer,
    ReportType.CHARACTER: CharacterAnalyzer,
    ReportType.WORLDBUILDING: WorldbuildingAnalyzer,
}


class CritiqueOrchestrator:
    """Runs selected report analyzers across a chapter set.

    The orchestrator is the seam between the UI worker and the
    analyzer classes. It owns:
      * the LLM client (None → dashboard mode),
      * the genre profile,
      * RAG-context retrieval (optional callable),
      * the chapter-by-chapter loop,
      * progress callbacks,
      * cross-chapter overall summary (LLM only).
    """

    def __init__(
        self,
        primary_llm: Optional['LLMClient'] = None,
        project: Optional[Any] = None,
        rag_provider: Optional[Any] = None,
        chapter_synopses: Optional[Dict[str, str]] = None,
    ):
        self.primary_llm = primary_llm
        self.project = project
        # rag_provider(query: str, source_types: list, hops=1) -> str
        self.rag_provider = rag_provider
        self.chapter_synopses = chapter_synopses or {}
        # Manuscript the chapters belong to, when it isn't the project's
        # active one (critiquing a novella from another tab).
        self.manuscript_override = None
        # The author's measured voice, shared with every report.
        self.writer_voice = None
        self.total_cost = 0.0
        # RAG memoization within a single critique run. Two reports
        # that resolve to identical (query, source_types, hops) hit
        # the cache instead of re-running TF-IDF + graph expansion.
        # Cleared at the start of ``run()`` so a second invocation
        # of the orchestrator picks up fresh data.
        self._rag_cache: Dict[Tuple[Any, ...], str] = {}
        self._rag_cache_hits = 0
        self._rag_cache_misses = 0

    # Format produced by ``main_window._rag_top_chunks_per_type``:
    #   "  - [<source_type>] <source_name>: <body>"
    # The pattern captures source_type and source_name so we can
    # build entity-mention tallies across reports.
    _ENTITY_REF_RE = re.compile(
        r"^\s*-\s*\[(?P<source_type>[a-z_]+)\]\s+"
        r"(?P<source_name>.+?):",
        re.MULTILINE,
    )

    @classmethod
    def _extract_entity_refs(
        cls, rag_context: str
    ) -> List[Tuple[str, str]]:
        """Pull ``(source_type, source_name)`` references out of a
        rag_context string. Used to aggregate entity mentions across
        reports for cross-report dedup.

        Non-greedy on the name so trailing `(via ...)` / `(related: ...)`
        annotations don't bleed into the captured name. Returns an
        empty list for empty input or content that doesn't match the
        expected ``[type] name:`` shape.
        """
        if not rag_context:
            return []
        refs: List[Tuple[str, str]] = []
        for m in cls._ENTITY_REF_RE.finditer(rag_context):
            stype = m.group("source_type").strip()
            sname = m.group("source_name").strip()
            # Drop any trailing parenthetical annotations on the name
            # (e.g., "General Mara  (via led_by from Iron League)") —
            # the chunk header may wear those when expansion fires.
            paren_idx = sname.find("  (")
            if paren_idx > 0:
                sname = sname[:paren_idx].strip()
            if stype and sname:
                refs.append((stype, sname))
        return refs

    def _build_analyzer(
        self,
        report_type: ReportType,
        chapter_title: str,
    ) -> _BaseAnalyzer:
        cls = _ANALYZER_REGISTRY[report_type]
        # Surface story_planning + manuscript to every analyzer (not
        # just PlotAnalyzer) so the shared context block can include
        # the PLOT ANCHOR and SURROUNDING CHAPTERS sub-blocks. Both
        # are optional — analyzers gracefully omit them when missing.
        sp = (getattr(self.project, "story_planning", None)
              if self.project else None)
        ms = self.manuscript_override or (getattr(self.project, "manuscript", None)
                                          if self.project else None)
        if cls is PlotAnalyzer:
            synopsis = self.chapter_synopses.get(chapter_title, "")
            analyzer = cls(
                primary_llm=self.primary_llm,
                story_planning=sp,
                manuscript=ms,
                chapter_synopsis=synopsis,
            )
        else:
            analyzer = cls(
                primary_llm=self.primary_llm,
                story_planning=sp,
                manuscript=ms,
                project=self.project,
            )
        analyzer.writer_voice = self.writer_voice
        return analyzer

    def _gather_rag(
        self,
        chapter_text: str,
        report_type: ReportType,
    ) -> str:
        """Pull report-relevant RAG chunks if a provider is wired in."""
        if self.rag_provider is None or not chapter_text:
            return ""
        # Source-type focus per report — we want the model to see
        # what's relevant to this analysis, not every project chunk.
        # Graph-expansion ``hops`` per report: PLOT and TENSION benefit
        # most from indirect connections (an ally faction's territory,
        # an antagonist's lieutenant), so we walk 2 hops there. Others
        # stay at 1 hop — expansion still surfaces direct cross-type
        # neighbors (a character's faction, a subplot's location) but
        # doesn't chase indirect chains that might drift off-topic.
        source_types_by_report: Dict[ReportType, list] = {
            ReportType.PACING: ["chapter", "subplot"],
            ReportType.VOICE: ["character", "chapter"],
            ReportType.TENSION: ["subplot", "chapter", "character"],
            ReportType.PLOT: ["chapter", "subplot", "character"],
            ReportType.DIALOG: ["character"],
            ReportType.STYLE: ["chapter"],
            # Canon report fetches the broadest entity slice — it
            # needs to judge BOTH characters and worldbuilding (factions,
            # places, cultures, technologies, historical events, myths)
            # against what's on the page. Graph expansion (hops=2) pulls
            # in connected entities so a faction's leader / ally / capital
            # surfaces alongside the faction itself.
            ReportType.CANON: [
                "character", "faction", "place", "culture",
                "technology", "historical_event", "myth", "subplot",
                "chapter",
            ],
            # Grammar is mechanical — chapter prose is all it needs
            # for spelling/grammar checks. Surrounding-chapter context
            # is wired separately via _format_surrounding_chapters_block
            # for the CONTINUITY section.
            ReportType.GRAMMAR: ["chapter"],
            ReportType.CHARACTER: ["character", "chapter_content", "subplot"],
            ReportType.WORLDBUILDING: [
                "faction", "place", "culture", "technology",
                "historical_event", "myth", "flora", "fauna", "star_system",
                "military", "economy", "political_system", "encyclopedia",
                "worldbuilding",
            ],
        }
        hops_by_report: Dict[ReportType, int] = {
            ReportType.PLOT:    2,
            ReportType.TENSION: 2,
            ReportType.CANON:   2,
            ReportType.WORLDBUILDING: 2,
        }
        source_types = source_types_by_report.get(
            report_type, ["chapter", "character", "subplot"])
        hops = hops_by_report.get(report_type, 1)
        # Use the chapter's first 800 words as the query so RAG returns
        # context relevant to *this* chapter rather than the project as a whole.
        query = " ".join(chapter_text.split()[:800])
        # Memoize within a critique run. Two reports with the same
        # (query, source_types, hops) — for example PLOT and TENSION
        # share the same source_types but differ in hops — hit the
        # cache only on exact matches. Sorted tuple of source_types
        # keeps the key stable regardless of list ordering.
        cache_key = (query, tuple(sorted(source_types)), hops)
        if cache_key in self._rag_cache:
            self._rag_cache_hits += 1
            return self._rag_cache[cache_key]
        self._rag_cache_misses += 1
        try:
            # Support both new providers (hops kwarg) and legacy
            # providers that only take (query, source_types). The
            # signature is duck-typed; we fall back on TypeError.
            try:
                result = self.rag_provider(
                    query, source_types, hops=hops)
            except TypeError:
                result = self.rag_provider(query, source_types)
        except Exception as e:
            print(f"[critique] RAG fetch failed: {e}")
            result = ""
        self._rag_cache[cache_key] = result
        return result

    def run_chapter(
        self,
        chapter_text: str,
        chapter_title: str,
        chapter_index: int,
        report_types: List[ReportType],
        genre: GenreProfile,
        manuscript_context: str,
        critique_context: Optional[CritiqueContext],
        progress_cb: Optional[callable] = None,
    ) -> ChapterReport:
        """Run all selected reports against one chapter."""
        word_count = len(chapter_text.split()) if chapter_text else 0
        chapter_report = ChapterReport(
            chapter_title=chapter_title,
            chapter_index=chapter_index,
            word_count=word_count,
        )
        if not chapter_text or not chapter_text.strip():
            return chapter_report
        # Track which entities (source_type, source_name) each
        # report referenced; aggregate at the chapter level so the
        # dashboard sees the *deduped* set with how many reports
        # cited each one.
        per_report_entities: List[set] = []
        for rt in report_types:
            if progress_cb:
                progress_cb(
                    f"  {chapter_title}: running {rt.value} report…")
            analyzer = self._build_analyzer(rt, chapter_title)
            rag_context = self._gather_rag(chapter_text, rt)
            # Dedup *within* a single report's context first — the
            # same entity may appear multiple times if expansion
            # promoted it via several paths. Then increment the
            # per-chapter counter by one for each unique entity in
            # this report.
            this_report_entities = set(
                self._extract_entity_refs(rag_context))
            per_report_entities.append(this_report_entities)
            for key in this_report_entities:
                chapter_report.entity_mentions[key] = (
                    chapter_report.entity_mentions.get(key, 0) + 1)
            section = analyzer.run(
                text=chapter_text,
                chapter_title=chapter_title,
                chapter_index=chapter_index,
                genre=genre,
                manuscript_context=manuscript_context,
                rag_context=rag_context,
                critique_context=critique_context,
                llm=self.primary_llm,
            )
            chapter_report.sections.append(section)
        return chapter_report

    def run(
        self,
        chapters: List[Dict[str, Any]],
        report_types: List[ReportType],
        genre_key_or_text: str,
        manuscript_context: str,
        critique_context: Optional[CritiqueContext] = None,
        progress_cb: Optional[callable] = None,
    ) -> CritiqueReport:
        """Run the selected reports across the supplied chapter set.

        ``chapters`` is a list of dicts with keys ``title``, ``text``,
        ``index`` (0-based). The orchestrator handles its own loop so
        the UI worker can stay simple.
        """
        genre = resolve_genre_profile(genre_key_or_text)
        # Fresh RAG cache per critique run — previous run's cache is
        # stale because project state may have changed (the lazy
        # rebuild on the main window only triggers via chat retrieval
        # paths; critique runs through its own provider lambda).
        self._rag_cache.clear()
        self._rag_cache_hits = 0
        self._rag_cache_misses = 0
        report = CritiqueReport(
            chapters=[],
            genre=genre,
            has_llm=self.primary_llm is not None,
        )
        for ch in chapters:
            title = ch.get("title", "Untitled")
            if progress_cb:
                progress_cb(f"Analyzing chapter: {title}")
            chapter_report = self.run_chapter(
                chapter_text=ch.get("text", ""),
                chapter_title=title,
                chapter_index=ch.get("index", 0),
                report_types=report_types,
                genre=genre,
                manuscript_context=manuscript_context,
                critique_context=critique_context,
                progress_cb=progress_cb,
            )
            report.chapters.append(chapter_report)
        if self.primary_llm is not None and len(chapters) > 0:
            if progress_cb:
                progress_cb("Composing overall summary…")
            report.overall_summary = self._build_overall_summary(report)
            report.overall_prompt = getattr(self, "_overall_prompt", "")
            report.overall_system = getattr(self, "_overall_system", "")
        else:
            report.overall_summary = self._dashboard_summary(report)
        return report

    def _dashboard_summary(self, report: CritiqueReport) -> str:
        """Plain-text rollup used when no LLM is configured."""
        if not report.chapters:
            return "No chapters analyzed."
        total_words = sum(c.word_count for c in report.chapters)
        chapter_count = len(report.chapters)
        lines = [
            f"Critique covered {chapter_count} chapter"
            f"{'s' if chapter_count != 1 else ''} "
            f"({total_words:,} words) using the {report.genre.name} profile.",
            "",
        ]
        # Aggregate a few headline metrics across chapters
        for rt in [
            ReportType.PACING, ReportType.VOICE, ReportType.TENSION,
            ReportType.PLOT, ReportType.DIALOG, ReportType.STYLE,
            ReportType.CANON, ReportType.CHARACTER, ReportType.WORLDBUILDING,
            ReportType.GRAMMAR,
        ]:
            sections = [
                s for c in report.chapters for s in c.sections
                if s.report_type == rt
            ]
            if not sections:
                continue
            findings = sum(len(s.findings) for s in sections)
            lines.append(
                f"- {rt.value.title()}: {len(sections)} chapter section(s), "
                f"{findings} finding(s).")
        return "\n".join(lines)

    def _build_overall_summary(self, report: CritiqueReport) -> str:
        """LLM-narrative rollup across all analyzed chapters."""
        chapter_blocks = []
        for c in report.chapters[:8]:  # cap to keep prompt bounded
            sec_lines = []
            for s in c.sections:
                summary = (s.summary or "").strip()
                if summary:
                    sec_lines.append(
                        f"  - [{s.report_type.value}] {summary}")
                for issue in (s.major_issues or [])[:2]:
                    sec_lines.append(f"      ! {_truncate(issue, 160)}")
            chapter_blocks.append(
                f"Chapter: {c.chapter_title} ({c.word_count:,} words)\n"
                + ("\n".join(sec_lines) if sec_lines else "  (no sections)"))
        body = "\n\n".join(chapter_blocks)
        prompt = f"""
A multi-chapter critique was run with these per-section summaries.
Genre profile: {report.genre.name} — {report.genre.notes}

{body}

Write a single overall summary (3-5 short paragraphs) that:
- Names the manuscript-level pattern across these chapters.
- Calls out cross-chapter strengths.
- Flags cross-chapter risks (recurring weaknesses, drift).
- Recommends a prioritized revision pass.
Be specific; do not generalize beyond the data above.
""".strip()
        system = ("You are a senior developmental editor producing a "
                  "manuscript-level rollup of per-chapter critiques.")
        self._overall_prompt, self._overall_system = prompt, system
        try:
            summary = self.primary_llm.generate_text(
                prompt,
                system,
                max_tokens=900,
                temperature=0.3 if is_local_llm(self.primary_llm) else 0.5,
            ).strip()
            if summary.startswith("Error generating text:"):
                raise RuntimeError(summary[len("Error generating text:"):].strip())
            return summary
        except Exception as e:
            return f"(overall summary unavailable: {e})"
