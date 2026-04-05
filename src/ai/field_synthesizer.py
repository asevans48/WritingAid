"""Synthesize proper prose descriptions from manuscript evidence + encyclopedia.

Instead of dumping raw sentences into fields, uses the LLM to distill
manuscript evidence into coherent, authored-quality descriptions.
Falls back to structured summaries when no LLM is available.

Key design: synthesize_character_profile does ALL fields in ONE LLM call
to avoid GPU memory pressure from sequential calls with large models.
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def _generate_with_cached_mlx(prompt: str, system_prompt: str,
                              max_tokens: int = 500, temperature: float = 0.4) -> str:
    """Generate text using the already-loaded MLX model from the global cache.

    This avoids creating a new LLMClient (which re-initializes Metal),
    and instead talks directly to the cached model.
    """
    try:
        from src.ai.mlx_utils import get_mlx_cache
        cache = get_mlx_cache()
        if not cache.is_loaded():
            return ""

        model, tokenizer = cache.get_model(cache._model_id)
        if model is None:
            return ""

        # Build prompt with chat template
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        if hasattr(tokenizer, 'apply_chat_template'):
            full_prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            full_prompt = f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:"

        # Generate — try mlx_lm first, then mlx_vlm
        try:
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler
            sampler = make_sampler(temp=temperature)
            response = generate(
                model, tokenizer, prompt=full_prompt,
                max_tokens=max_tokens, sampler=sampler, verbose=False
            )
        except Exception:
            from mlx_vlm import generate as vlm_generate
            response = vlm_generate(
                model, tokenizer, full_prompt,
                max_tokens=max_tokens, temp=temperature, verbose=False
            )

        if not isinstance(response, str):
            response = getattr(response, 'text', '') or str(response)

        return response.strip()
    except Exception as e:
        logger.debug(f"Cached MLX generation failed: {e}")
        return ""


def get_llm_client():
    """Get an LLM client using the app's configured model.

    For cloud providers, creates a lightweight client.
    For local MLX, returns None — callers should use _generate_with_cached_mlx instead.
    """
    try:
        from src.config.ai_config import get_ai_config
        from src.ai.llm_client import LLMClient, LLMProvider

        config = get_ai_config()
        settings = config.get_settings()

        # For local models, DON'T create a new LLMClient — it re-initializes Metal.
        # The synthesize functions will use _generate_with_cached_mlx directly.
        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        if prefer_local and enable_local:
            return None  # Signal to use cached MLX

        provider_name = settings.get("default_llm", "claude").lower()
        api_key = config.get_api_key(provider_name)
        if api_key:
            provider_enum = {
                "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
            }.get(provider_name, LLMProvider.CLAUDE)
            return LLMClient(
                provider=provider_enum, api_key=api_key,
                model=config.get_model(provider_name)
            )
    except Exception as e:
        logger.debug(f"Could not create LLM client: {e}")
    return None


def synthesize_character_profile(
    name: str,
    manuscript_sentences: list,
    encyclopedia_reference: str = "",
    existing_fields: dict = None,
    llm_client=None
) -> Dict[str, str]:
    """Synthesize a full character profile in ONE LLM call.

    This avoids multiple sequential LLM calls that cause GPU memory pressure
    on large models (26B+). All fields are generated in a single pass.

    Args:
        name: Character name
        manuscript_sentences: List of (chapter_title, sentence) tuples
        encyclopedia_reference: Optional encyclopedia context
        existing_fields: Dict of {field: current_value} for fields that already have content
        llm_client: LLM client (if None, attempts to create one)

    Returns:
        Dict of {field_name: synthesized_content} for all character fields
    """
    if not manuscript_sentences:
        return {}

    if llm_client is None:
        llm_client = get_llm_client()

    existing = existing_fields or {}

    # Build evidence organized by what it reveals
    all_evidence = " ... ".join(s for _, s in manuscript_sentences[:10])[:1200]

    # Build the prompt asking for all fields at once
    system = (
        f"You are analyzing the character \"{name}\" from a manuscript.\n\n"
        "CRITICAL RULES:\n"
        "- ANALYZE, do not copy. Summarize what the text SHOWS about this character.\n"
        "- NEVER quote or copy sentences from the manuscript.\n"
        "- NEVER paste story text into the profile.\n"
        "- Write YOUR OWN analysis based on the evidence.\n"
        "- If no evidence exists for a field, write NONE.\n\n"
        "Respond in EXACTLY this format. Follow the length rules strictly:\n\n"
        "PERSONALITY: [2-3 sentences analyzing their behavior, temperament, how they treat others]\n"
        "PHYSICAL: [2-3 sentences describing their appearance based on details in the text]\n"
        "SPEECH: [SHORT comma-separated list: e.g. 'clipped and direct, avoids emotion, dry humor']\n"
        "BACKSTORY: [2-3 sentences about their history, background, what shaped them]\n"
        "MOTIVATIONS: [SHORT comma-separated list: e.g. 'protect his family, redeem past failures']\n"
        "FEARS: [SHORT comma-separated list: e.g. 'losing control, becoming like his father']\n"
        "BASELINE: [ONE or TWO words for default mood: e.g. 'guarded' or 'weary, determined']"
    )

    prompt_parts = [f"Write a character profile for {name}."]

    # Include existing content so the LLM can build on it
    existing_block = []
    for field, val in existing.items():
        if val and len(val) > 10 and len(val) < 200:
            existing_block.append(f"{field}: {val[:150]}")
    if existing_block:
        prompt_parts.append("Existing notes:\n" + "\n".join(existing_block))

    prompt_parts.append(f"MANUSCRIPT EVIDENCE:\n{all_evidence}")

    if encyclopedia_reference:
        prompt_parts.append(
            f"ENCYCLOPEDIA (for grounding only):\n{encyclopedia_reference[:400]}"
        )

    result = {}
    prompt = "\n\n".join(prompt_parts)

    # Try cloud client first, then cached MLX
    response = None
    if llm_client:
        try:
            response = llm_client.generate_text(
                prompt=prompt,
                system_prompt=system,
                max_tokens=500,
                temperature=0.4,
                task_type="character_profile"
            )
            if response:
                print(f"[Synthesizer] Raw LLM response for '{name}' "
                      f"({len(response)} chars):\n{response[:500]}")
            else:
                print(f"[Synthesizer] LLM returned empty response for '{name}'")

        except Exception as e:
            print(f"[Synthesizer] LLM call failed for '{name}': {e}")
            logger.warning(f"Character profile synthesis failed for {name}: {e}")

    # If no cloud client, try cached MLX model directly
    if not response and not llm_client:
        response = _generate_with_cached_mlx(prompt, system, max_tokens=500, temperature=0.4)

    # Parse structured response — flexible matching for various LLM output formats
    if response and not result:
        import re as _re

        # Map full field labels to field names.
        # Use full words (not stems) to avoid partial prefix matches
        # like "fear" matching "FEARS:" and leaving "S:" as content.
        field_keywords = {
            "personality": "personality",
            "physical": "physical_description",
            "speech": "speaking_style",
            "speaking style": "speaking_style",
            "backstory": "backstory",
            "motivations": "motivations",
            "motivation": "motivations",
            "fears": "fears",
            "baseline": "emotional_baseline",
            "emotional baseline": "emotional_baseline",
        }

        current_field = None
        current_lines = []

        for line in response.strip().split('\n'):
            raw_line = line.strip()
            if not raw_line:
                continue

            # Strip markdown bold, numbering, bullets
            clean = _re.sub(r'^\d+[\.\)]\s*', '', raw_line)  # "1. " or "1) "
            clean = _re.sub(r'^\*+\s*', '', clean)  # "* " or "** "
            clean = _re.sub(r'\*+', '', clean)  # remove all remaining asterisks
            clean = _re.sub(r'^[-•]\s*', '', clean)  # "- " or "• "
            clean = clean.strip()

            # Check if this line starts a new field
            # Sort keywords longest-first so "speaking style" matches before "speech"
            matched = False
            clean_upper = clean.upper()
            for keyword in sorted(field_keywords.keys(), key=len, reverse=True):
                if clean_upper.startswith(keyword.upper()):
                    field = field_keywords[keyword]
                    # Find where the label ends and content begins
                    rest = clean[len(keyword):].lstrip(" :-–—")
                    if current_field and current_lines:
                        content = " ".join(current_lines).strip()
                        if content.upper() != "NONE" and len(content) > 5:
                            result[current_field] = content
                    current_field = field
                    current_lines = [rest.strip()] if rest.strip() else []
                    matched = True
                    break

            if not matched and current_field:
                current_lines.append(raw_line)

        # Save last field
        if current_field and current_lines:
            content = " ".join(current_lines).strip()
            # Clean any remaining markdown artifacts
            content = _re.sub(r'\*+', '', content).strip()
            if content.upper() != "NONE" and len(content) > 5:
                result[current_field] = content

    # Post-process: enforce field format rules
    # Single-line fields (QLineEdit) must be short comma-separated items
    single_line_fields = {"speaking_style", "motivations", "fears", "emotional_baseline"}
    # Multi-line fields (QTextEdit) get longer analysis but no story quotes
    multi_line_fields = {"personality", "physical_description", "backstory"}

    for field, content in list(result.items()):
        if not content:
            continue

        # Strip any quoted manuscript text (text in quotes longer than 30 chars)
        content = _re.sub(r'"[^"]{30,}"', '', content)
        content = _re.sub(r'"[^"]{30,}"', '', content)  # smart quotes
        content = _re.sub(r'\s+', ' ', content).strip()

        if field in single_line_fields:
            # Keep only the first 120 chars, ensure it's comma-list format
            content = content[:120].rstrip('.')
            # If it's a full sentence, try to extract just the key phrases
            if len(content) > 80 and ',' not in content:
                # Too long with no commas — it's a sentence, not a list
                # Truncate to first phrase
                content = content[:60].rsplit(' ', 1)[0]
        elif field in multi_line_fields:
            # Cap at 300 chars for descriptions
            content = content[:300]

        result[field] = content.strip()

    logger.debug(f"synthesize_character_profile for '{name}': "
                 f"response={len(response) if response else 0} chars, "
                 f"parsed {len(result)} fields: {list(result.keys())}")

    # Fallback: if all LLM paths failed, use best manuscript sentences
    if not result and manuscript_sentences:
        best = " ... ".join(s for _, s in manuscript_sentences[:3])[:400]
        result["personality"] = f"Based on manuscript: {best}"

    return result


def synthesize_field(
    element_name: str,
    element_type: str,
    field_name: str,
    manuscript_evidence: str,
    encyclopedia_reference: str = "",
    existing_content: str = "",
    llm_client=None
) -> str:
    """Synthesize a proper prose description for an element field.

    Args:
        element_name: Name of the element (e.g., "Marcus", "Iron Guild")
        element_type: Type (e.g., "character", "faction")
        field_name: Field being written (e.g., "personality", "description")
        manuscript_evidence: Raw sentences from the manuscript mentioning this element
        encyclopedia_reference: Optional encyclopedia/RAG context for grounding
        existing_content: Current field content (preserved if substantial)
        llm_client: LLM client (if None, attempts to create one)

    Returns:
        Synthesized description string
    """
    if not manuscript_evidence and not encyclopedia_reference:
        return existing_content

    # Try cloud LLM first
    if llm_client is None:
        llm_client = get_llm_client()

    if llm_client:
        return _synthesize_with_llm(
            element_name, element_type, field_name,
            manuscript_evidence, encyclopedia_reference,
            existing_content, llm_client
        )

    # Try cached MLX model (no new client creation)
    result = _synthesize_with_cached_mlx(
        element_name, element_type, field_name,
        manuscript_evidence, encyclopedia_reference,
        existing_content
    )
    if result:
        return result

    # Fallback: structured summary without LLM
    return _synthesize_without_llm(
        element_name, field_name,
        manuscript_evidence, encyclopedia_reference,
        existing_content
    )


def _synthesize_with_cached_mlx(
    element_name, element_type, field_name,
    manuscript_evidence, encyclopedia_reference,
    existing_content
) -> str:
    """Use the cached MLX model directly for field synthesis."""
    field_instruction = _FIELD_INSTRUCTIONS.get(field_name, (
        "Describe {name} based on the manuscript evidence. "
        "Be concrete and factual."
    )).format(name=element_name)

    system = (
        f"You are filling in the '{field_name.replace('_', ' ')}' field for "
        f"{element_type} \"{element_name}\".\n\n"
        f"{field_instruction}\n\n"
        "Rules: Base on FACTS from evidence. Don't invent. Don't quote directly. "
        "Be specific. 2-4 sentences. Output ONLY the content."
    )

    prompt_parts = [f"Fill in {field_name.replace('_', ' ')} for {element_name}."]
    if existing_content and len(existing_content) > 10:
        prompt_parts.append(f"Existing: {existing_content[:200]}")
    if manuscript_evidence:
        prompt_parts.append(f"MANUSCRIPT:\n{manuscript_evidence[:800]}")
    if encyclopedia_reference:
        prompt_parts.append(f"REFERENCE:\n{encyclopedia_reference[:300]}")

    response = _generate_with_cached_mlx(
        "\n\n".join(prompt_parts), system, max_tokens=200, temperature=0.5
    )
    return response if response else ""


# Field-specific instructions that tell the LLM exactly what to extract
_FIELD_INSTRUCTIONS = {
    # Character fields — factual, concrete, manuscript-grounded
    "personality": (
        "Summarize {name}'s personality based on the manuscript evidence. "
        "Focus on CONCRETE behaviors and patterns: How do they treat others? "
        "How do they react under pressure? What are their habits? What contradictions "
        "do they show? Write factual character notes, not poetry. "
        "Example: 'Outwardly disciplined and controlled, but privately struggles with '..."
    ),
    "physical_description": (
        "Describe {name}'s physical appearance based on the manuscript. "
        "Include SPECIFIC details mentioned: height, build, hair, eyes, scars, "
        "clothing, distinguishing features, how they carry themselves. "
        "Only include details actually present in the evidence. "
        "Example: 'Tall and lean, with close-cropped dark hair and a scar along the left jaw...'"
    ),
    "speaking_style": (
        "Describe how {name} speaks based on the manuscript. "
        "Include: sentence length (short/long), vocabulary level (simple/educated), "
        "verbal habits or catchphrases, accent or dialect hints, tone (formal/casual), "
        "what they avoid saying. "
        "Example: 'Speaks in clipped, military-style sentences. Avoids emotional language...'"
    ),
    "backstory": (
        "Summarize {name}'s background and history based on what the manuscript reveals. "
        "Include: where they come from, their family, significant past events mentioned, "
        "their occupation or role, key relationships, what shaped them. "
        "Stick to FACTS from the text — things that happened, places they've been, "
        "people they knew. Don't invent details not in the evidence. "
        "Example: 'Former border garrison soldier. Lost a brother during the siege of Thornwall...'"
    ),
    "motivations": (
        "What drives {name} based on the manuscript evidence? "
        "What do they want? What are they working toward? What promises have they made? "
        "What obligations weigh on them? Be concrete and specific. "
        "Example: 'Seeks to redeem himself after abandoning his post. Promised his dying brother...'"
    ),
    "fears": (
        "What does {name} fear based on the manuscript? "
        "What do they avoid, dread, or have nightmares about? What makes them hesitate? "
        "Example: 'Fears becoming like his father — cold and unable to connect...'"
    ),
    "emotional_baseline": (
        "What is {name}'s default emotional state based on the manuscript? "
        "How do they come across to others most of the time? "
        "Example: 'Guarded and watchful, with a dry humor that surfaces in safe company.'"
    ),
    # Worldbuilding fields — factual and informative
    "description": (
        "Describe {name} based on the manuscript evidence. "
        "Include concrete details: what it is, what it looks like or consists of, "
        "what role it plays in the story, who is involved with it. "
        "Write informative notes, not poetry."
    ),
    "atmosphere": (
        "Describe the atmosphere/feel of {name} based on the manuscript. "
        "What sensory details are mentioned? How does it feel to be there? "
        "Stick to details from the text."
    ),
    "rules": (
        "Describe the rules and mechanics of {name} based on the manuscript. "
        "How does it work? What are the constraints? What can and can't it do?"
    ),
    "limitations": (
        "What are the limitations of {name} based on the manuscript? "
        "What can't it do? What are the costs, risks, or restrictions?"
    ),
}


def _synthesize_with_llm(
    element_name, element_type, field_name,
    manuscript_evidence, encyclopedia_reference,
    existing_content, llm_client
) -> str:
    """Use the LLM to write a proper description from evidence."""
    # Get field-specific instruction, or use a generic one
    field_instruction = _FIELD_INSTRUCTIONS.get(field_name, (
        "Describe {name} based on the manuscript evidence. "
        "Be concrete and factual. Include specific details from the text. "
        "Write informative notes, not poetry."
    )).format(name=element_name)

    system = (
        f"You are filling in the '{field_name.replace('_', ' ')}' field for "
        f"{element_type} \"{element_name}\" in a creative writing project.\n\n"
        f"{field_instruction}\n\n"
        "Rules:\n"
        "- Base your content on FACTS from the manuscript evidence\n"
        "- Do NOT invent details not supported by the evidence\n"
        "- Do NOT quote the manuscript directly — summarize and synthesize\n"
        "- If encyclopedia reference is provided, use it to add context "
        "but never override manuscript facts\n"
        "- Write in present tense, third person\n"
        "- Be SPECIFIC — names, places, events, concrete details\n"
        "- 2-4 sentences. Output ONLY the content, nothing else"
    )

    prompt_parts = [f"Fill in the {field_name.replace('_', ' ')} for {element_name}."]

    if existing_content and len(existing_content) > 10:
        prompt_parts.append(f"Existing content (incorporate):\n{existing_content[:300]}")

    if manuscript_evidence:
        prompt_parts.append(f"MANUSCRIPT EVIDENCE:\n{manuscript_evidence[:1000]}")

    if encyclopedia_reference:
        prompt_parts.append(
            f"ENCYCLOPEDIA REFERENCE (for grounding, not overriding):\n"
            f"{encyclopedia_reference[:500]}"
        )

    try:
        result = llm_client.generate_text(
            prompt="\n\n".join(prompt_parts),
            system_prompt=system,
            max_tokens=200,
            temperature=0.5,
            task_type="field_synthesis"
        )
        return result.strip()
    except Exception as e:
        logger.warning(f"LLM synthesis failed for {element_name}.{field_name}: {e}")
        return _synthesize_without_llm(
            element_name, field_name,
            manuscript_evidence, encyclopedia_reference,
            existing_content
        )


def _synthesize_without_llm(
    element_name, field_name,
    manuscript_evidence, encyclopedia_reference,
    existing_content
) -> str:
    """Structured fallback when no LLM is available."""
    parts = []
    if existing_content:
        parts.append(existing_content)
    if manuscript_evidence:
        # Extract the most substantive sentence
        sents = [s.strip() for s in manuscript_evidence.split(" ... ") if len(s.strip()) > 30]
        if sents:
            parts.append(f"From the manuscript: {sents[0]}")
    if encyclopedia_reference:
        ref_lines = [l.strip() for l in encyclopedia_reference.split('\n') if l.strip() and len(l.strip()) > 20]
        if ref_lines:
            parts.append(f"Reference: {ref_lines[0][:200]}")
    return "\n\n".join(parts) if parts else existing_content
