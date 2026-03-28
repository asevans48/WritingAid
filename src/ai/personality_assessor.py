"""AI-powered personality assessment for characters.

Analyzes chapter text to assess how a character's personality manifests,
tracks changes across chapters, and provides structured snapshots.
"""

import logging
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


def assess_personality(
    character,
    chapter_content: str,
    chapter_id: str,
    chapter_number: int,
    chapter_title: str,
    llm_client,
    all_chapters_summaries: Optional[List[dict]] = None,
):
    """Analyze a character's personality in a specific chapter.

    Args:
        character: Character model object
        chapter_content: Full text of the chapter
        chapter_id: ID of the chapter
        chapter_number: Chapter number
        chapter_title: Chapter title
        llm_client: LLM client for generation
        all_chapters_summaries: Optional list of prior arc snapshots for context

    Returns:
        PersonalitySnapshot with the assessment
    """
    from src.models.project import PersonalitySnapshot

    # Build the system prompt
    system_prompt = (
        "You are a literary character analyst. Analyze how a character's personality "
        "manifests in the given chapter text. Be specific and cite brief examples from "
        "the text (quote short phrases).\n\n"
        "Provide your analysis in this exact format:\n"
        "TRAITS ACTIVE: comma-separated list of personality traits visible in this chapter\n"
        "EMOTIONAL STATE: their dominant emotional state in this chapter\n"
        "BEHAVIOR EXAMPLES: 2-3 specific examples of how their personality shows "
        "(quote brief text snippets)\n"
        "GROWTH NOTES: any changes from their baseline personality, or 'No significant change' "
        "if they remain consistent\n"
        "FULL ASSESSMENT: a 2-3 paragraph analysis of the character in this chapter"
    )

    # Build the user prompt with character context
    prompt_parts = [f'Analyze the character "{character.name}" in this chapter.']

    # Include known personality info
    char_info = []
    if character.personality:
        char_info.append(f"General personality: {character.personality[:500]}")
    if character.personality_traits:
        char_info.append(f"Known traits: {', '.join(character.personality_traits)}")
    if character.motivations:
        char_info.append(f"Motivations: {character.motivations[:300]}")
    if character.fears:
        char_info.append(f"Fears: {character.fears[:200]}")
    if character.speaking_style:
        char_info.append(f"Speaking style: {character.speaking_style[:200]}")
    if character.emotional_baseline:
        char_info.append(f"Emotional baseline: {character.emotional_baseline[:200]}")

    if char_info:
        prompt_parts.append("KNOWN CHARACTER INFO:\n" + "\n".join(char_info))

    # Include prior arc snapshots for evolution tracking
    if all_chapters_summaries:
        arc_parts = []
        for s in all_chapters_summaries[-3:]:  # Last 3 snapshots
            arc_parts.append(
                f"Ch{s.get('number', '?')} ({s.get('title', '')}): "
                f"state={s.get('emotional_state', 'unknown')}, "
                f"growth={s.get('growth_notes', 'none')}"
            )
        if arc_parts:
            prompt_parts.append("PERSONALITY IN PRIOR CHAPTERS:\n" + "\n".join(arc_parts))

    # Include the chapter text (truncated for token budget)
    max_text = 4000
    if len(chapter_content) > max_text:
        # Take beginning, middle, and end
        third = max_text // 3
        text_sample = (
            chapter_content[:third]
            + "\n\n[...middle of chapter...]\n\n"
            + chapter_content[len(chapter_content) // 2 - third // 2:
                              len(chapter_content) // 2 + third // 2]
            + "\n\n[...end of chapter...]\n\n"
            + chapter_content[-third:]
        )
    else:
        text_sample = chapter_content

    prompt_parts.append(f"CHAPTER {chapter_number}: {chapter_title}\n\n{text_sample}")

    prompt = "\n\n".join(prompt_parts)

    try:
        response = llm_client.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=1500,
            temperature=0.5,
            task_type="personality_assessment"
        )

        # Parse the response
        snapshot = _parse_assessment(response, chapter_id, chapter_number, chapter_title)
        return snapshot

    except Exception as e:
        logger.error(f"Personality assessment failed: {e}")
        return PersonalitySnapshot(
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            ai_assessment=f"Assessment failed: {e}",
            is_ai_generated=True
        )


def _parse_assessment(
    response: str, chapter_id: str, chapter_number: int, chapter_title: str
):
    """Parse the LLM response into a PersonalitySnapshot."""
    from src.models.project import PersonalitySnapshot

    traits = []
    emotional_state = ""
    behavior_examples = ""
    growth_notes = ""
    full_assessment = ""

    lines = response.strip().split('\n')
    current_section = None

    for line in lines:
        line_stripped = line.strip()
        upper = line_stripped.upper()

        if upper.startswith("TRAITS ACTIVE:"):
            current_section = "traits"
            value = line_stripped[len("TRAITS ACTIVE:"):].strip()
            traits = [t.strip() for t in value.split(',') if t.strip()]
        elif upper.startswith("EMOTIONAL STATE:"):
            current_section = "emotional"
            emotional_state = line_stripped[len("EMOTIONAL STATE:"):].strip()
        elif upper.startswith("BEHAVIOR EXAMPLES:"):
            current_section = "behavior"
            value = line_stripped[len("BEHAVIOR EXAMPLES:"):].strip()
            behavior_examples = value
        elif upper.startswith("GROWTH NOTES:"):
            current_section = "growth"
            growth_notes = line_stripped[len("GROWTH NOTES:"):].strip()
        elif upper.startswith("FULL ASSESSMENT:"):
            current_section = "assessment"
            value = line_stripped[len("FULL ASSESSMENT:"):].strip()
            full_assessment = value
        elif current_section == "behavior" and line_stripped:
            behavior_examples += "\n" + line_stripped
        elif current_section == "growth" and line_stripped:
            growth_notes += " " + line_stripped
        elif current_section == "assessment" and line_stripped:
            full_assessment += "\n" + line_stripped

    return PersonalitySnapshot(
        chapter_id=chapter_id,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        traits_active=traits,
        emotional_state=emotional_state,
        behavior_examples=behavior_examples.strip(),
        growth_notes=growth_notes.strip(),
        ai_assessment=full_assessment.strip() or response.strip(),
        is_ai_generated=True
    )
