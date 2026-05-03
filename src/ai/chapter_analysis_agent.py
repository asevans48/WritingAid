"""Chapter Analysis Agent for providing line-item edit suggestions.

This agent analyzes chapters and paragraphs to provide specific editing suggestions
without rewriting content. Uses cost-effective hybrid approach.
"""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient


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

    LINE_BY_LINE_PROMPT = """You are a professional editor preparing writing for publication. Review each line for issues that would hurt publishability.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Plot Goals for This Section: {plot_context}
- Key Characters: {character_context}
- Worldbuilding Elements: {worldbuilding_context}
- Additional Instructions: {additional_instructions}

=== WHAT TO FLAG (Publishability Issues) ===

SHOW VS TELL:
- FLAG: Emotional states told baldly ("She was angry", "He felt nervous")
- FLAG: Important reactions told instead of shown ("The news devastated her")
- DO NOT FLAG: Transitional telling ("The next morning...", "After lunch...")
- DO NOT FLAG: Quick factual statements ("She knew the way")
- RULE: Only flag telling that wastes an opportunity for impact

UNNATURAL TRANSITIONS:
- FLAG: Clunky connectors ("Meanwhile...", "Little did she know...")
- FLAG: Time jumps that confuse rather than clarify
- FLAG: Forced narrative bridges

TONE/STYLE/VOICE BREAKS:
- FLAG: Lines where the voice suddenly shifts without reason
- FLAG: Word choices that don't match the established style
- FLAG: Modern idioms in period pieces (or vice versa)
- FLAG: Character dialogue that sounds wrong for who they are

CLICHÉS AND WEAK WRITING:
- FLAG: Overused phrases ("a shiver ran down her spine", "time stood still")
- FLAG: Adverb-heavy dialogue tags ("she said softly", "he replied angrily")
- FLAG: Filter words that distance readers ("she noticed", "he saw that", "she felt")
- FLAG: Purple prose or melodrama
- FLAG: Passive voice that weakens the sentence

TECHNICAL ISSUES:
- FLAG: Head-hopping (sudden POV shift mid-paragraph)
- FLAG: Info-dump dialogue ("As you know, Bob...")
- FLAG: Sentences with no sensory grounding when needed
- FLAG: Repetitive sentence structure in sequence

=== WHAT NOT TO FLAG ===
- Lines that are already working well
- Style choices that match the author's stated intent
- Minor word preferences that are subjective
- Lines that are fine even if not perfect

YOUR TASK:
Review each numbered line. Only flag lines with genuine publishability issues. Most lines should NOT be flagged.

OUTPUT FORMAT:
For each line needing attention:

LINE [number]: "[exact line text]"
ISSUE: [Show-Don't-Tell/Transition/Voice/Cliché/Filter Words/POV/Pacing/Style]
REASONING: [Why this specific issue hurts publishability]
SUGGESTION: [What to consider - frame as "Consider..." - NOT a rewrite]
EXAMPLE: [One possible revision showing how this could be fixed - keep the author's voice]
PRIORITY: [high/medium/low]

---

Skip lines that work. Only flag genuine problems."""

    # Two-stage line analysis prompts for handling longer texts without cutoffs
    LINE_IDENTIFICATION_PROMPT = """You are a professional editor scanning text for publishability issues.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Additional Notes: {additional_instructions}

SCAN FOR THESE ISSUES:
- Show vs Tell: Emotional states told baldly, important moments summarized
- Transitions: Clunky connectors, disorienting time jumps
- Voice/Tone: Shifts that don't match intended style
- Clichés: Overused phrases, purple prose
- Filter Words: "she saw", "he felt", "she noticed"
- Adverbs: Adverb-heavy dialogue tags
- POV: Head-hopping, POV breaks
- Passive Voice: Where active would be stronger

YOUR TASK:
Scan all numbered lines. Output ONLY the line numbers that have genuine issues.
Be selective - most lines should NOT be flagged.

OUTPUT FORMAT (one line per issue):
[line_number]|[issue_type]

Example:
3|show_dont_tell
7|cliche
12|filter_words
15|passive_voice

Only output lines with issues. No explanations. No other text."""

    LINE_DETAIL_PROMPT = """You are a professional editor providing detailed feedback on specific lines.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Plot Goals: {plot_context}
- Key Characters: {character_context}
- Worldbuilding: {worldbuilding_context}
- Additional Instructions: {additional_instructions}

For each line below, provide:
1. Why this line has issues (specific to publishability)
2. What the author should consider changing
3. An example of how it could be revised (keeping author's voice)

OUTPUT FORMAT for each line:

LINE [number]:
ORIGINAL: "[the line text]"
ISSUE_TYPE: [Show-Don't-Tell/Transition/Voice/Cliché/Filter Words/POV/Adverb/Passive Voice/Style]
REASONING: [2-3 sentences explaining why this hurts publishability]
SUGGESTION: [Frame as "Consider..." - actionable advice, NOT a rewrite]
EXAMPLE: [One possible revision that addresses the issue]
PRIORITY: [high/medium/low]

---

Be thorough but constructive. Explain the "why" clearly."""

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

    def analyze_paragraph(
        self,
        paragraph: str,
        context: str = "",
        focus_areas: Optional[List[SuggestionType]] = None,
        llm_override: Optional['LLMClient'] = None,
    ) -> List[LineItemSuggestion]:
        """Analyze single paragraph for issues.

        Args:
            paragraph: The paragraph text
            context: Optional surrounding context
            focus_areas: Specific areas to focus on

        Returns:
            List of suggestions
        """
        if len(paragraph.strip()) < 20:
            return []  # Too short to analyze

        focus_text = ""
        if focus_areas:
            areas = [area.value.replace('_', ' ') for area in focus_areas]
            focus_text = f"\nFocus on: {', '.join(areas)}"

        prompt = f"""
Context: {context[:200] if context else 'None'}

Paragraph to analyze:
"{paragraph}"
{focus_text}

Provide 2-4 specific editing suggestions. For each:
1. Quote the relevant part
2. Type of issue (show/tell, pacing, dialogue, etc.)
3. Suggestion for improvement
4. Why it matters

Format:
---
Quote: "[exact text]"
Type: [issue type]
Suggestion: [what to consider]
Why: [explanation]
Priority: [high/medium/low]
"""

        if llm_override is not None:
            llm = llm_override
        else:
            llm = self.local_llm if self.local_llm and len(paragraph) < 500 else self.primary_llm

        response = llm.generate_text(
            prompt,
            self.QUICK_REVIEW_PROMPT,
            max_tokens=400,
            temperature=0.4
        )

        # Parse suggestions
        suggestions = self._parse_suggestions(response, 1)

        return suggestions

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

    def analyze_lines(
        self,
        text: str,
        critique_context: Optional[CritiqueContext] = None,
        max_lines: int = 150,
        progress_callback: Optional[callable] = None,
        manuscript_context: str = "",
        chapter_synopsis: str = "",
        llm_override: Optional['LLMClient'] = None,
    ) -> List[LineItemSuggestion]:
        """Perform two-stage line-by-line analysis of text.

        Stage 1: Quick scan to identify which lines have issues
        Stage 2: Detailed analysis of flagged lines in batches

        Args:
            text: The text to analyze
            critique_context: Author-provided context for targeted critique
            max_lines: Maximum number of lines to analyze
            progress_callback: Optional callback for progress updates

        Returns:
            List of LineItemSuggestion objects, one per flagged line
        """
        import re

        # Split text into lines (sentences)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # Limit lines for token management
        if len(sentences) > max_lines:
            sentences = sentences[:max_lines]

        if progress_callback:
            progress_callback(f"Scanning {len(sentences)} lines for issues...")

        # === STAGE 1: Identify problem lines ===
        numbered_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sentences)])

        # Build identification prompt with context
        id_prompt = self.LINE_IDENTIFICATION_PROMPT.format(
            style_context=critique_context.style if critique_context else "Not specified",
            tone_context=critique_context.tone if critique_context else "Not specified",
            voice_context=critique_context.voice if critique_context else "Not specified",
            additional_instructions=critique_context.additional_instructions if critique_context else "None"
        )

        context_preamble = ""
        if chapter_synopsis:
            context_preamble += f"Chapter Synopsis: {chapter_synopsis}\n"
        if manuscript_context:
            context_preamble += f"Manuscript Context: {manuscript_context[:400]}\n"
        if context_preamble:
            context_preamble = context_preamble.strip() + "\n\n"

        id_request = f"""{context_preamble}Scan these numbered lines and identify which ones have publishability issues.
Output ONLY line numbers with issue types (format: number|issue_type).

TEXT TO SCAN:
{numbered_text}"""

        llm = llm_override if llm_override is not None else self.primary_llm
        id_response = llm.generate_text(
            id_request,
            id_prompt,
            max_tokens=500,
            temperature=0.3
        )

        # Parse identified lines
        flagged_lines = self._parse_line_identification(id_response)

        if not flagged_lines:
            if progress_callback:
                progress_callback("No issues found!")
            return []

        if progress_callback:
            progress_callback(f"Found {len(flagged_lines)} lines to analyze...")

        # === STAGE 2: Get detailed analysis for flagged lines ===
        # Process in batches to avoid token limits
        batch_size = 10
        all_suggestions = []

        for batch_start in range(0, len(flagged_lines), batch_size):
            batch = flagged_lines[batch_start:batch_start + batch_size]

            if progress_callback:
                progress_callback(f"Analyzing lines {batch_start + 1}-{min(batch_start + batch_size, len(flagged_lines))}...")

            # Build detail prompt
            detail_prompt = self.LINE_DETAIL_PROMPT.format(
                style_context=critique_context.style if critique_context else "Not specified",
                tone_context=critique_context.tone if critique_context else "Not specified",
                voice_context=critique_context.voice if critique_context else "Not specified",
                plot_context=critique_context.plot_goals if critique_context else "Not specified",
                character_context=critique_context.characters if critique_context else "Not specified",
                worldbuilding_context=critique_context.worldbuilding if critique_context else "Not specified",
                additional_instructions=critique_context.additional_instructions if critique_context else "None"
            )

            # Build request with actual line texts
            lines_to_analyze = []
            for line_num, issue_type in batch:
                if 0 < line_num <= len(sentences):
                    lines_to_analyze.append(f"Line {line_num} (flagged as {issue_type}): \"{sentences[line_num - 1]}\"")

            if not lines_to_analyze:
                continue

            detail_request = f"""Provide detailed feedback for these specific lines:

{chr(10).join(lines_to_analyze)}

For each line, explain WHY it's a problem and HOW to fix it."""

            detail_response = llm.generate_text(
                detail_request,
                detail_prompt,
                max_tokens=1500,
                temperature=0.4
            )

            # Parse detailed suggestions
            batch_suggestions = self._parse_line_detail_response(detail_response, sentences, batch)
            all_suggestions.extend(batch_suggestions)

        if progress_callback:
            progress_callback(f"Complete! {len(all_suggestions)} suggestions.")

        return all_suggestions

    def _parse_line_identification(self, response: str) -> List[tuple]:
        """Parse the line identification response.

        Args:
            response: The LLM response with format "line_num|issue_type"

        Returns:
            List of (line_number, issue_type) tuples
        """
        import re
        flagged = []

        for line in response.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Match patterns like "3|show_dont_tell" or "3 | show_dont_tell"
            match = re.match(r'(\d+)\s*\|\s*(\w+)', line)
            if match:
                line_num = int(match.group(1))
                issue_type = match.group(2).lower()
                flagged.append((line_num, issue_type))

        return flagged

    def _parse_line_detail_response(
        self,
        response: str,
        original_sentences: List[str],
        flagged_batch: List[tuple]
    ) -> List[LineItemSuggestion]:
        """Parse detailed line analysis response.

        Args:
            response: The LLM response with detailed analysis
            original_sentences: Original sentences for reference
            flagged_batch: The batch of (line_num, issue_type) that was analyzed

        Returns:
            List of LineItemSuggestion objects
        """
        import re
        suggestions = []

        # Create a lookup of flagged lines for this batch
        flagged_lookup = {line_num: issue_type for line_num, issue_type in flagged_batch}

        # Split response into blocks by LINE marker
        blocks = re.split(r'(?=LINE\s*\d+)', response, flags=re.IGNORECASE)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Extract line number
            line_match = re.search(r'LINE\s*(\d+)', block, re.IGNORECASE)
            if not line_match:
                continue

            line_num = int(line_match.group(1))

            # Get the original text
            if 0 < line_num <= len(original_sentences):
                original_text = original_sentences[line_num - 1]
            else:
                continue

            # Extract fields
            issue_type = self._extract_field(block, 'ISSUE_TYPE') or self._extract_field(block, 'ISSUE')
            reasoning = self._extract_field(block, 'REASONING')
            suggestion = self._extract_field(block, 'SUGGESTION')
            example_fix = self._extract_field(block, 'EXAMPLE')
            priority = self._extract_field(block, 'PRIORITY').lower()

            # Normalize priority
            if priority not in ['high', 'medium', 'low']:
                priority = 'medium'

            # Map issue type to enum
            stype = self._map_issue_to_type(issue_type or flagged_lookup.get(line_num, 'style'))

            suggestions.append(LineItemSuggestion(
                line_number=line_num,
                paragraph_number=1,
                suggestion_type=stype,
                original_text=original_text,
                suggestion=suggestion or "Consider revising this line.",
                explanation=issue_type or "Style issue",
                priority=priority,
                reasoning=reasoning or "",
                example_fix=example_fix or ""
            ))

        return suggestions

    def analyze_lines_legacy(
        self,
        text: str,
        critique_context: Optional[CritiqueContext] = None,
        max_lines: int = 100,
        llm_override: Optional['LLMClient'] = None,
    ) -> List[LineItemSuggestion]:
        """Legacy single-pass line-by-line analysis (kept for comparison).

        Args:
            text: The text to analyze
            critique_context: Author-provided context for targeted critique
            max_lines: Maximum number of lines to analyze (for token limits)

        Returns:
            List of LineItemSuggestion objects, one per flagged line
        """
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) > max_lines:
            sentences = sentences[:max_lines]

        numbered_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sentences)])

        if critique_context:
            system_prompt = self.LINE_BY_LINE_PROMPT.format(
                style_context=critique_context.style or "Not specified",
                tone_context=critique_context.tone or "Not specified",
                voice_context=critique_context.voice or "Not specified",
                plot_context=critique_context.plot_goals or "Not specified",
                character_context=critique_context.characters or "Not specified",
                worldbuilding_context=critique_context.worldbuilding or "Not specified",
                additional_instructions=critique_context.additional_instructions or "None"
            )
        else:
            system_prompt = self.LINE_BY_LINE_PROMPT.format(
                style_context="Not specified",
                tone_context="Not specified",
                voice_context="Not specified",
                plot_context="Not specified",
                character_context="Not specified",
                worldbuilding_context="Not specified",
                additional_instructions="None"
            )

        prompt = f"""Please review the following numbered lines and provide feedback on lines that need improvement.
Remember: NOT every line needs feedback - only flag lines with genuine opportunities for improvement.

TEXT TO REVIEW:
{numbered_text}

Provide your line-by-line feedback now. Use the format specified in your instructions."""

        llm = llm_override if llm_override is not None else self.primary_llm
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=2500,
            temperature=0.4
        )

        suggestions = self._parse_line_by_line_response(response, sentences)

        return suggestions

    def _parse_line_by_line_response(
        self,
        response: str,
        original_sentences: List[str]
    ) -> List[LineItemSuggestion]:
        """Parse the line-by-line analysis response.

        Args:
            response: The LLM response
            original_sentences: Original sentences for reference

        Returns:
            List of LineItemSuggestion objects
        """
        import re
        suggestions = []

        # Try multiple patterns to split into blocks
        # Pattern 1: LINE [number] format
        # Pattern 2: Numbered list format (1., 2., etc.)
        # Pattern 3: Separator lines (---)

        # First try LINE format
        line_blocks = re.split(r'(?=LINE\s*\d+)', response, flags=re.IGNORECASE)

        # If that doesn't work well, try separator-based splitting
        if len(line_blocks) <= 1:
            line_blocks = re.split(r'\n---+\n|\n\n(?=\d+\.|\[)', response)

        for block in line_blocks:
            block = block.strip()
            if not block:
                continue

            # Try multiple patterns to extract line number
            line_num = None
            quoted_text = ""

            # Pattern 1: LINE [number]: "text" or LINE [number]
            line_match = re.search(r'LINE\s*(\d+)[:\s]*["\u201c]?([^"\u201d\n]*)["\u201d]?', block, re.IGNORECASE)
            if line_match:
                line_num = int(line_match.group(1))
                quoted_text = line_match.group(2).strip() if line_match.group(2) else ""

            # Pattern 2: Just a number at start (e.g., "3. ")
            if line_num is None:
                num_match = re.match(r'^(\d+)\.\s', block)
                if num_match:
                    line_num = int(num_match.group(1))

            # Pattern 3: Look for "Line X" anywhere in the block
            if line_num is None:
                line_ref = re.search(r'[Ll]ine\s+(\d+)', block)
                if line_ref:
                    line_num = int(line_ref.group(1))

            if line_num is None:
                continue

            try:
                # Parse fields using simple line-by-line extraction
                issue_type = self._extract_field(block, 'ISSUE')
                reasoning = self._extract_field(block, 'REASONING')
                suggestion = self._extract_field(block, 'SUGGESTION')
                example_fix = self._extract_field(block, 'EXAMPLE')
                priority = self._extract_field(block, 'PRIORITY').lower()

                # ALWAYS use original sentence from the array if we have a valid line number
                # This ensures we show the actual text even if LLM didn't quote it
                if 0 < line_num <= len(original_sentences):
                    original_text = original_sentences[line_num - 1]
                else:
                    original_text = quoted_text or f"[Line {line_num} - text not available]"

                # Map issue type to SuggestionType
                stype = self._map_issue_to_type(issue_type)

                # Normalize priority
                if priority not in ['high', 'medium', 'low']:
                    priority = 'medium'

                suggestions.append(LineItemSuggestion(
                    line_number=line_num,
                    paragraph_number=1,  # We're doing line-by-line, not paragraph
                    suggestion_type=stype,
                    original_text=original_text,
                    suggestion=suggestion,
                    explanation=issue_type,  # Brief issue type
                    priority=priority,
                    reasoning=reasoning,
                    example_fix=example_fix
                ))
            except (ValueError, IndexError):
                continue

        return suggestions

    def _extract_field(self, block: str, field_name: str) -> str:
        """Extract a field value from a text block.

        Args:
            block: The text block to search
            field_name: The field name to extract (e.g., 'ISSUE', 'SUGGESTION')

        Returns:
            The extracted value or empty string
        """
        import re

        # List of all field keywords (case-insensitive boundary markers)
        field_markers = ['LINE', 'ISSUE', 'REASONING', 'SUGGESTION', 'EXAMPLE', 'PRIORITY']

        # Try multiple patterns for field extraction

        # Pattern 1: Field name followed by colon, capture until next field marker
        # Using word boundary and flexible spacing
        pattern1 = rf'\b{field_name}\s*:\s*(.+?)(?=\n\s*(?:{"|".join(field_markers)})\s*:|$)'
        match = re.search(pattern1, block, re.IGNORECASE | re.DOTALL)
        if match:
            result = match.group(1).strip()
            # Clean up any trailing dashes (separator lines)
            result = re.sub(r'\n*-+\s*$', '', result).strip()
            if result:
                return result

        # Pattern 2: Field name at start of line, capture until next line starting with known field
        lines = block.split('\n')
        capturing = False
        captured_lines = []
        field_pattern = re.compile(rf'^{field_name}\s*:\s*(.*)$', re.IGNORECASE)
        end_pattern = re.compile(rf'^({"|".join(field_markers)})\s*:', re.IGNORECASE)

        for line in lines:
            if capturing:
                # Check if this line starts a new field
                if end_pattern.match(line.strip()) or line.strip().startswith('---'):
                    break
                captured_lines.append(line)
            else:
                field_match = field_pattern.match(line.strip())
                if field_match:
                    # Start capturing - include content on same line as field name
                    first_content = field_match.group(1).strip()
                    if first_content:
                        captured_lines.append(first_content)
                    capturing = True

        if captured_lines:
            return ' '.join(captured_lines).strip()

        return ""

    def _map_issue_to_type(self, issue_type: str) -> SuggestionType:
        """Map an issue type string to a SuggestionType enum.

        Args:
            issue_type: The issue type string from the LLM response

        Returns:
            The corresponding SuggestionType
        """
        issue_lower = issue_type.lower()
        if 'show' in issue_lower or 'tell' in issue_lower:
            return SuggestionType.SHOW_DONT_TELL
        elif 'clich' in issue_lower:  # cliche, cliché
            return SuggestionType.CLICHE
        elif 'filter' in issue_lower:
            return SuggestionType.FILTER_WORDS
        elif 'transition' in issue_lower:
            return SuggestionType.TRANSITION
        elif 'pov' in issue_lower or 'point of view' in issue_lower or 'head-hop' in issue_lower or 'headhop' in issue_lower:
            return SuggestionType.POV
        elif 'adverb' in issue_lower:
            return SuggestionType.ADVERB
        elif 'passive' in issue_lower:
            return SuggestionType.PASSIVE_VOICE
        elif 'info' in issue_lower and 'dump' in issue_lower:
            return SuggestionType.INFO_DUMP
        elif 'style' in issue_lower:
            return SuggestionType.STYLE
        elif 'tone' in issue_lower:
            return SuggestionType.TONE
        elif 'voice' in issue_lower:
            return SuggestionType.VOICE
        elif 'plot' in issue_lower:
            return SuggestionType.PLOT
        elif 'world' in issue_lower:
            return SuggestionType.WORLDBUILDING
        elif 'pacing' in issue_lower:
            return SuggestionType.PACING
        elif 'word' in issue_lower or 'choice' in issue_lower:
            return SuggestionType.WORD_CHOICE
        elif 'character' in issue_lower:
            return SuggestionType.CHARACTER_VOICE
        elif 'tension' in issue_lower:
            return SuggestionType.TENSION
        elif 'clarity' in issue_lower:
            return SuggestionType.CLARITY
        else:
            return SuggestionType.STYLE

        return suggestions

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

    def compare_versions(
        self,
        original: str,
        revised: str
    ) -> Dict[str, Any]:
        """Compare two versions of text to assess improvements.

        Args:
            original: Original text
            revised: Revised text

        Returns:
            Comparison analysis
        """
        prompt = f"""
Compare these two versions:

ORIGINAL:
{original[:1000]}

REVISED:
{revised[:1000]}

Analysis:
1. What improved?
2. What got worse (if anything)?
3. Overall: Is the revision an improvement?

Be brief and specific.
"""

        llm = self.local_llm if self.local_llm else self.primary_llm

        response = llm.generate_text(
            prompt,
            self.QUICK_REVIEW_PROMPT,
            max_tokens=300,
            temperature=0.3
        )

        return {
            "analysis": response,
            "recommendation": "Use revised" if "improvement" in response.lower() else "Consider original"
        }

    def _parse_suggestions(
        self,
        response: str,
        paragraph_num: int
    ) -> List[LineItemSuggestion]:
        """Parse LLM response into structured suggestions."""
        suggestions = []
        lines = response.split('\n')

        current_suggestion = {}
        for line in lines:
            line = line.strip()

            if line.startswith('Quote:'):
                if current_suggestion:
                    suggestions.append(self._create_suggestion(current_suggestion, paragraph_num))
                current_suggestion = {"quote": line.replace('Quote:', '').strip(' "')}
            elif line.startswith('Type:'):
                current_suggestion["type"] = line.replace('Type:', '').strip()
            elif line.startswith('Suggestion:'):
                current_suggestion["suggestion"] = line.replace('Suggestion:', '').strip()
            elif line.startswith('Why:'):
                current_suggestion["why"] = line.replace('Why:', '').strip()
            elif line.startswith('Priority:'):
                current_suggestion["priority"] = line.replace('Priority:', '').strip().lower()

        if current_suggestion:
            suggestions.append(self._create_suggestion(current_suggestion, paragraph_num))

        return suggestions

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
