"""Chapter Analysis Agent for providing line-item edit suggestions.

This agent analyzes chapters and paragraphs to provide specific editing suggestions
without rewriting content. Uses cost-effective hybrid approach.
"""

import re
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

    def __post_init__(self):
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


class _BaseAnalyzer:
    """Common machinery for report analyzers.

    Each analyzer collects deterministic metrics first so the
    dashboard works without a model, then optionally calls the LLM
    to produce a narrative section. The metrics + findings get
    embedded in the LLM prompt so the model anchors its prose to
    the actual numbers instead of hallucinating about pacing.
    """

    report_type: ReportType = None  # overridden by subclasses

    def __init__(
        self,
        primary_llm: Optional['LLMClient'] = None,
        story_planning: Optional[Any] = None,
        manuscript: Optional[Any] = None,
    ):
        self.primary_llm = primary_llm
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
            try:
                prompt, system_prompt = self._build_prompt(
                    text, section, genre, manuscript_context,
                    rag_context, critique_context,
                )
                # Capture prompts on the section so rated rows can
                # save the real (prompt, narrative) pair for training.
                section.prompt = prompt
                section.system_prompt = system_prompt
                response = llm.generate_text(
                    prompt,
                    system_prompt,
                    max_tokens=900,
                    temperature=0.5,
                )
                section.narrative = (response or "").strip()
            except Exception as e:  # pragma: no cover — model errors
                section.narrative = ""
                section.findings.append(f"(narrative skipped: {e})")
        return section

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

        plot_block = self._format_plot_anchor_block(chapter_index)
        if plot_block:
            parts.append(plot_block)

        surround_block = self._format_surrounding_chapters_block(
            chapter_title)
        if surround_block:
            parts.append(surround_block)

        if manuscript_context:
            parts.append(
                "MANUSCRIPT CONTEXT:\n" + _truncate(manuscript_context, 1200))
        if rag_context:
            parts.append(
                "RELEVANT BACKGROUND (from RAG):\n"
                + _truncate(rag_context, 1500))
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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
{' '.join(text.split()[:2500])}

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
        words = re.findall(r"[A-Za-z][A-Za-z'’]*", text)
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
{' '.join(text.split()[:2500])}

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
_ANALYZER_REGISTRY: Dict[ReportType, Any] = {
    ReportType.PACING: PacingAnalyzer,
    ReportType.VOICE: VoiceAnalyzer,
    ReportType.TENSION: TensionAnalyzer,
    ReportType.PLOT: PlotAnalyzer,
    ReportType.DIALOG: DialogAnalyzer,
    ReportType.STYLE: StyleAnalyzer,
    ReportType.CANON: CanonAnalyzer,
    ReportType.GRAMMAR: GrammarAnalyzer,
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
        ms = (getattr(self.project, "manuscript", None)
              if self.project else None)
        if cls is PlotAnalyzer:
            synopsis = self.chapter_synopses.get(chapter_title, "")
            return cls(
                primary_llm=self.primary_llm,
                story_planning=sp,
                manuscript=ms,
                chapter_synopsis=synopsis,
            )
        return cls(
            primary_llm=self.primary_llm,
            story_planning=sp,
            manuscript=ms,
        )

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
        }
        hops_by_report: Dict[ReportType, int] = {
            ReportType.PLOT:    2,
            ReportType.TENSION: 2,
            ReportType.CANON:   2,
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
        try:
            return self.primary_llm.generate_text(
                prompt,
                "You are a senior developmental editor producing a "
                "manuscript-level rollup of per-chapter critiques.",
                max_tokens=900,
                temperature=0.5,
            ).strip()
        except Exception as e:
            return f"(overall summary unavailable: {e})"
