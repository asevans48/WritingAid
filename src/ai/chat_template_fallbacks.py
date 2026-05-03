"""Chat-template fallbacks for tokenizers that ship without one.

Some HF / MLX repos publish a tokenizer that has the
``apply_chat_template`` method (every modern tokenizer does) but
*don't* set ``tokenizer.chat_template`` — e.g.
``mlx-community/Cydonia-24B-v3.1-4bit``. Calling
``apply_chat_template`` on those raises:

    Cannot use chat template functions because tokenizer.chat_template
    is not set and no template argument was passed!

This module wraps the call so:

  1. If the tokenizer DOES have a usable chat_template, we use it
     verbatim — no behaviour change for well-configured models.
  2. If it doesn't, we look up a Jinja template by model-id family
     (Mistral / Llama / Qwen / Gemma / Phi) and pass it via the
     ``chat_template`` argument so the call succeeds with a
     correctly-formatted prompt for that family.
  3. If we can't even guess a family, fall through to a plain
     ``System: …\\nUser: …\\nAssistant:`` string. The model still
     produces output; it just doesn't get the family-native
     special tokens.

The first two paths are the important ones. Cydonia is the Mistral
case — fixing that fixes the immediate error the user hit.
"""

from __future__ import annotations

from typing import Any, List, Dict, Optional


# ── Jinja chat templates per model family ───────────────────
#
# These match the official templates published by each family's
# tokenizer config when the upstream repo includes one. We embed
# them here so any HF/MLX checkpoint missing the field still ends
# up with a correctly-formatted prompt.

# Mistral instruction format. Used by Mistral 7B/Small/Medium and
# their fine-tunes (Cydonia, Hermes-Mistral, Mixtral, etc.).
# Single concatenated turn after a system preamble; multi-turn
# loops the [INST]...[/INST] pair.
_MISTRAL_TEMPLATE = """{{ bos_token }}{% for message in messages %}{% if message['role'] == 'system' %}{% if loop.first %}[INST] {{ message['content'] }}\n{% endif %}{% elif message['role'] == 'user' %}{% if not loop.first or messages[0]['role'] != 'system' %}[INST] {% endif %}{{ message['content'] }} [/INST]{% elif message['role'] == 'assistant' %} {{ message['content'] }}{{ eos_token }}{% endif %}{% endfor %}"""

# Llama 3 chat format — ChatML-derived but with Meta's special
# token ids. Llama 2 used a different format; we don't include
# that here because Llama 3+ is the dominant lineage now.
_LLAMA3_TEMPLATE = """{% for message in messages %}<|start_header_id|>{{ message['role'] }}<|end_header_id|>\n\n{{ message['content'] }}<|eot_id|>{% endfor %}{% if add_generation_prompt %}<|start_header_id|>assistant<|end_header_id|>\n\n{% endif %}"""

# Qwen ChatML format — same as OpenAI ChatML with <|im_start|> /
# <|im_end|> token boundaries. Used by Qwen 2/3/3.6 and most
# Qwen-finetune variants.
_QWEN_CHATML_TEMPLATE = """{% for message in messages %}<|im_start|>{{ message['role'] }}\n{{ message['content'] }}<|im_end|>\n{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"""

# Gemma instruction format. Gemma supports user/model turns only
# (no system role) — when a system message is present we prepend
# its content to the first user turn so the instruction reaches
# the model.
_GEMMA_TEMPLATE = """{% if messages[0]['role'] == 'system' %}{% set sys = messages[0]['content'] %}{% set msgs = messages[1:] %}{% else %}{% set sys = '' %}{% set msgs = messages %}{% endif %}{% for message in msgs %}<start_of_turn>{% if message['role'] == 'user' %}user\n{% if loop.first and sys %}{{ sys }}\n\n{% endif %}{{ message['content'] }}{% else %}model\n{{ message['content'] }}{% endif %}<end_of_turn>\n{% endfor %}{% if add_generation_prompt %}<start_of_turn>model\n{% endif %}"""

# Phi-3 chat format. Microsoft's family with explicit |system|
# |user| |assistant| markers. Used by Phi-3 mini / small / medium
# and their MLX equivalents.
_PHI3_TEMPLATE = """{% for message in messages %}<|{{ message['role'] }}|>\n{{ message['content'] }}<|end|>\n{% endfor %}{% if add_generation_prompt %}<|assistant|>\n{% endif %}"""


# ── Family detection ────────────────────────────────────────
#
# Heuristic match on the model id. Order matters where one
# family's name is a substring of another (e.g. "mistral" inside
# "mistral-llama" — we'd want to disambiguate; not currently a
# real case but the order below is safe-by-construction).

def _detect_family(model_id: str) -> str:
    """Return one of ``mistral`` / ``llama`` / ``qwen`` / ``gemma``
    / ``phi`` / ``""``. Empty string means "no fallback known"."""
    if not model_id:
        return ""
    lower = model_id.lower()
    # Cydonia is a Mistral fine-tune; explicitly handle it ahead of
    # generic substrings so we don't mistake it for anything else.
    if "cydonia" in lower or "mistral" in lower or "mixtral" in lower:
        return "mistral"
    if "qwen" in lower:
        return "qwen"
    if "llama" in lower or "llama-3" in lower or "llama3" in lower:
        return "llama"
    if "gemma" in lower:
        return "gemma"
    if "phi-3" in lower or "phi3" in lower or "phi-mini" in lower:
        return "phi"
    return ""


_FALLBACK_TEMPLATES = {
    "mistral": _MISTRAL_TEMPLATE,
    "llama":   _LLAMA3_TEMPLATE,
    "qwen":    _QWEN_CHATML_TEMPLATE,
    "gemma":   _GEMMA_TEMPLATE,
    "phi":     _PHI3_TEMPLATE,
}


# ── Public API ──────────────────────────────────────────────


def apply_chat_template_safe(tokenizer: Any,
                             messages: List[Dict[str, str]],
                             *,
                             model_id: str = "",
                             add_generation_prompt: bool = True
                             ) -> str:
    """Apply a chat template to ``messages``, falling back when
    needed.

    Resolution order:

      1. Tokenizer has a non-empty ``chat_template`` field → use it
         verbatim. Standard path; no behavioural change for
         well-configured tokenizers.
      2. Tokenizer is missing the field but we can guess the
         family from ``model_id`` → pass the family's official
         Jinja template via the ``chat_template=`` keyword argument
         to ``apply_chat_template``. The tokenizer's special tokens
         (``bos_token`` / ``eos_token`` / etc.) get substituted in.
      3. Neither works → return a plain ``System: …\\nUser:
         …\\nAssistant:`` string. The model still produces output;
         just without family-native special tokens.

    Always returns a string ready to feed to the model.
    """
    # Path 1: tokenizer already configured.
    existing = getattr(tokenizer, "chat_template", None)
    if existing:
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=add_generation_prompt)
        except Exception:
            # Fall through to family fallback if the template is
            # somehow broken.
            pass

    # Path 2: family-specific fallback.
    family = _detect_family(model_id)
    template = _FALLBACK_TEMPLATES.get(family)
    if template:
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=add_generation_prompt,
                chat_template=template)
        except Exception:
            # Some tokenizers reject an explicit template arg
            # (older transformers). Drop to the plain-text path.
            pass

    # Path 3: plain-text fallback. Concatenate roles in a
    # human-readable form. The model recognises this convention
    # well enough to produce sensible output — it just won't
    # benefit from family-native special tokens.
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            lines.append(content)
        elif role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"{role}: {content}")
    if add_generation_prompt:
        lines.append("Assistant:")
    return "\n\n".join(lines)
