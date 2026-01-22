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

    ANALYSIS_PROMPT = """You are a professional editor providing constructive feedback.

    CRITICAL RULES:
    1. Provide SUGGESTIONS, not rewrites
    2. Frame feedback as "Consider..." "You might..." "What if..."
    3. Be specific about what and where
    4. Explain WHY each suggestion matters
    5. Recognize what works well
    6. Focus on high-impact improvements

    Prioritize suggestions that most improve the writing.
    """

    ENHANCED_ANALYSIS_PROMPT = """You are a professional editor providing constructive feedback on creative writing.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Plot Goals for This Section: {plot_context}
- Key Characters: {character_context}
- Worldbuilding Elements: {worldbuilding_context}
- Additional Instructions: {additional_instructions}

CRITICAL RULES:
1. Provide SUGGESTIONS, not rewrites
2. Frame feedback as "Consider..." "You might..." "What if..."
3. Be specific about what and where
4. Explain WHY each suggestion matters
5. Recognize what works well
6. Prioritize suggestions that most improve the writing
7. Consider the author's stated intentions when giving feedback
8. Respect the genre conventions and style choices

ANALYSIS AREAS:
1. Style & Voice: Does the writing maintain consistent style? Is the narrative voice distinct and appropriate for the genre?
2. Tone: Does the emotional quality match the author's stated intent? Are tonal shifts effective or jarring?
3. Plot: Does this section advance the plot appropriately? Are there pacing issues or unclear motivations?
4. Character: Are characters consistent with their established voices and motivations? Do they feel authentic?
5. Worldbuilding: Are world details consistent and well-integrated? Does exposition feel natural?
6. Show Don't Tell: Are emotions and descriptions shown through action rather than stated?
7. Dialogue: Is dialogue natural and distinctive per character? Does it serve the scene?
8. Pacing: Does the scene flow well? Are there sections that drag or rush?
9. Tension: Is there appropriate conflict or tension for this point in the story?
10. Clarity: Are sentences clear? Is meaning unambiguous?
11. Grammar & Word Choice: Are there technical issues or weak word choices?

For each suggestion:
- Quote the specific text
- Identify the issue type
- Explain the problem clearly
- Suggest an improvement approach (not a rewrite)
- Rate priority: high/medium/low
"""

    QUICK_REVIEW_PROMPT = """You are providing quick feedback on writing.
    Point out the 2-3 most important issues only.
    Be brief and specific."""

    QUICK_ENHANCED_PROMPT = """You are a professional editor providing quick feedback on writing.
Focus on the 3-5 most impactful improvements considering:
- Author's stated style/tone/voice intentions
- Plot and character consistency
- Worldbuilding coherence
- The most pressing technical issues

Be specific and constructive. Explain why each issue matters."""

    LINE_BY_LINE_PROMPT = """You are a professional editor providing LINE-BY-LINE feedback on creative writing.

CONTEXT PROVIDED BY AUTHOR:
- Genre/Style: {style_context}
- Intended Tone: {tone_context}
- Narrative Voice: {voice_context}
- Plot Goals for This Section: {plot_context}
- Key Characters: {character_context}
- Worldbuilding Elements: {worldbuilding_context}
- Additional Instructions: {additional_instructions}

YOUR TASK:
Review each line (sentence) and identify lines that would benefit from revision. NOT every line needs feedback - only flag lines that have clear opportunities for improvement.

FOCUS ON LINES THAT:
1. Could better match the author's stated style, tone, or voice
2. Tell rather than show (emotions stated rather than demonstrated through action/body language)
3. Could be enriched with plot-relevant details or worldbuilding elements
4. Have weak or generic word choices that don't fit the genre
5. Break character voice consistency
6. Could build more tension or emotional impact
7. Have pacing issues (too rushed or too slow for the moment)

IMPORTANT GUIDELINES:
- Some telling is perfectly fine - only flag egregious cases
- Respect the author's style choices
- Don't suggest changes just for the sake of change
- Prioritize suggestions that serve the story
- Be specific about WHY a change would improve the line

OUTPUT FORMAT:
For each line needing attention, provide:

LINE [number]: "[exact line text]"
ISSUE: [Style/Tone/Voice/Show-Don't-Tell/Plot/Worldbuilding/Pacing/Word Choice]
REASONING: [Why this line could be improved - what's the specific problem?]
SUGGESTION: [What to consider - frame as "Consider..." or "You might..." - NOT a rewrite]
PRIORITY: [high/medium/low]

---

If a line is working well, skip it. Only include lines that genuinely need attention."""

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
        focus_areas: Optional[List[SuggestionType]] = None
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

        # Use local model for single paragraph if available
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
        focus_areas: Optional[List[SuggestionType]] = None
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
            return self._quick_chapter_review(chapter_text, chapter_title, paragraphs, critique_context)

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

        prompt = f"""
Chapter: {chapter_title}
Word Count: {word_count}
Manuscript Context: {manuscript_context[:300]}
{focus_text}

Chapter Text (first 2000 words):
{' '.join(chapter_text.split()[:2000])}

Provide comprehensive editing feedback:

1. OVERALL ASSESSMENT (2-3 sentences)

2. STRENGTHS (3-5 bullet points)
List what works well.

3. AREAS FOR IMPROVEMENT (3-5 bullet points)
List what needs work.

4. PACING NOTES
Brief comments on chapter pacing.

5. CHARACTER CONSISTENCY
Any concerns about character voices or behavior.

6. TOP LINE-ITEM SUGGESTIONS (5-7 specific edits)
For each suggestion, provide:
- Paragraph # (estimate)
- Quote: "[relevant text]"
- Type: [issue type]
- Suggestion: [what to improve]
- Why: [explanation]
- Priority: [high/medium/low]

Keep feedback constructive and actionable.
"""

        response = self.primary_llm.generate_text(
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
        max_lines: int = 100
    ) -> List[LineItemSuggestion]:
        """Perform line-by-line analysis of text.

        Args:
            text: The text to analyze
            critique_context: Author-provided context for targeted critique
            max_lines: Maximum number of lines to analyze (for token limits)

        Returns:
            List of LineItemSuggestion objects, one per flagged line
        """
        # Split text into lines (sentences)
        import re
        # Split on sentence-ending punctuation while keeping the punctuation
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # Limit lines for token management
        if len(sentences) > max_lines:
            sentences = sentences[:max_lines]

        # Number the lines
        numbered_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(sentences)])

        # Build system prompt with context
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

        response = self.primary_llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=2500,
            temperature=0.4
        )

        # Parse line-by-line suggestions
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

        # Split by line entries (LINE [number])
        # Pattern matches "LINE 1:", "LINE 23:", etc.
        line_pattern = re.compile(
            r'LINE\s*(\d+)[:\s]*["\u201c]?([^"\u201d\n]+)["\u201d]?\s*'
            r'(?:ISSUE[:\s]*([^\n]+))?\s*'
            r'(?:REASONING[:\s]*([^\n]+(?:\n(?!LINE|ISSUE|SUGGESTION|PRIORITY)[^\n]+)*))?\s*'
            r'(?:SUGGESTION[:\s]*([^\n]+(?:\n(?!LINE|ISSUE|REASONING|PRIORITY)[^\n]+)*))?\s*'
            r'(?:PRIORITY[:\s]*(\w+))?',
            re.IGNORECASE | re.MULTILINE
        )

        for match in line_pattern.finditer(response):
            try:
                line_num = int(match.group(1))
                quoted_text = match.group(2).strip() if match.group(2) else ""
                issue_type = match.group(3).strip() if match.group(3) else "General"
                reasoning = match.group(4).strip() if match.group(4) else ""
                suggestion = match.group(5).strip() if match.group(5) else ""
                priority = match.group(6).strip().lower() if match.group(6) else "medium"

                # Get original text if we have it
                original_text = quoted_text
                if 0 < line_num <= len(original_sentences):
                    original_text = original_sentences[line_num - 1]

                # Map issue type to SuggestionType
                issue_lower = issue_type.lower()
                if 'show' in issue_lower or 'tell' in issue_lower:
                    stype = SuggestionType.SHOW_DONT_TELL
                elif 'style' in issue_lower:
                    stype = SuggestionType.STYLE
                elif 'tone' in issue_lower:
                    stype = SuggestionType.TONE
                elif 'voice' in issue_lower:
                    stype = SuggestionType.VOICE
                elif 'plot' in issue_lower:
                    stype = SuggestionType.PLOT
                elif 'world' in issue_lower:
                    stype = SuggestionType.WORLDBUILDING
                elif 'pacing' in issue_lower:
                    stype = SuggestionType.PACING
                elif 'word' in issue_lower or 'choice' in issue_lower:
                    stype = SuggestionType.WORD_CHOICE
                elif 'character' in issue_lower:
                    stype = SuggestionType.CHARACTER_VOICE
                elif 'tension' in issue_lower:
                    stype = SuggestionType.TENSION
                elif 'clarity' in issue_lower:
                    stype = SuggestionType.CLARITY
                else:
                    stype = SuggestionType.STYLE

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
                    reasoning=reasoning  # Detailed reasoning
                ))
            except (ValueError, IndexError):
                continue

        return suggestions

    def _quick_chapter_review(
        self,
        chapter_text: str,
        chapter_title: str,
        paragraphs: List[str],
        critique_context: Optional[CritiqueContext] = None
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
        paragraph_num: int
    ) -> LineItemSuggestion:
        """Create LineItemSuggestion from parsed data."""
        # Map type string to enum
        type_str = data.get("type", "").lower().replace(' ', '_')
        suggestion_type = SuggestionType.CLARITY  # Default

        for stype in SuggestionType:
            if stype.value in type_str or type_str in stype.value:
                suggestion_type = stype
                break

        return LineItemSuggestion(
            line_number=None,
            paragraph_number=paragraph_num,
            suggestion_type=suggestion_type,
            original_text=data.get("quote", "")[:200],
            suggestion=data.get("suggestion", ""),
            explanation=data.get("why", ""),
            priority=data.get("priority", "medium")
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

        for line in sections["suggestions"]:
            if 'Paragraph' in line or 'Para' in line:
                if current_item:
                    line_items.append(current_item)
                current_item = {"paragraph": 1}  # Extract number if possible
            elif 'Quote:' in line:
                current_item["quote"] = line.split('Quote:')[1].strip(' "')
            elif 'Type:' in line:
                current_item["type"] = line.split('Type:')[1].strip()
            elif 'Suggestion:' in line:
                current_item["suggestion"] = line.split('Suggestion:')[1].strip()
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
                self._create_suggestion(item, item.get("paragraph", 1))
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
        previous_chapters_summary: str = ""
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

        response = self.llm.generate_text(
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
