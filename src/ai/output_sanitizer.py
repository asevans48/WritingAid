"""Runtime sanitiser for LLM output.

When local models leak their internal channel / chat-format tokens
into the response stream, those tokens land verbatim in whatever
surface is consuming the output — the editor, the chat bubble, the
saved training row. The user sees ``<|channel|>thought<|channel|>``
spam instead of prose.

Why it happens
--------------
Modern instruction-tuned models often use special tokens that the
runtime is supposed to strip: GPT-OSS uses Harmony (``<|channel|>``
/ ``<|message|>`` / ``<|start|>`` / ``<|end|>``), ChatML uses
``<|im_start|>`` / ``<|im_end|>``, Llama 3 uses ``<|begin_of_text|>``
/ ``<|eot_id|>``, Mistral uses ``[INST]`` / ``[/INST]``. When the
loader's chat template isn't perfectly aligned with the model's
training format — common for community quantizations — the tokens
fall through as plain text. Our prompts also got more structured
(agentic lookups, pre-write discussion), which can confuse a small
model into stuttering its own role tokens.

This module is the application-level safety net. ``strip_meta_tokens``
removes the formats we've seen in the wild; ``is_degenerate_output``
flags responses that are mostly tokens / whitespace so callers can
warn the user instead of silently inserting garbage.
"""

from __future__ import annotations

import re
from typing import Tuple


# ── Patterns ─────────────────────────────────────────────────────────


# Single-token markers (with the closing ``|>`` stripped — both forms
# `<|x|>` and `<|x>` show up in the wild). Matches the well-formed
# token AND a common malformed variant where the bar is on the wrong
# side: ``<|channel>`` / ``<channel|>``.
_HARMONY_TOKEN_NAMES = (
    # GPT-OSS Harmony channels
    "channel", "message", "start", "end",
    "constrain", "developer", "system", "user", "assistant",
    "tool", "tool_calls", "function", "return",
    # ChatML
    "im_start", "im_end",
    # Llama 3
    "begin_of_text", "end_of_text", "eot_id",
    "start_header_id", "end_header_id",
    "python_tag",
    # Misc
    "endoftext", "fim_prefix", "fim_middle", "fim_suffix",
    "fim_pad", "pad",
    # Reasoning / scratchpad markers some models emit
    "reasoning", "thought", "thinking", "analysis", "scratchpad",
    "internal", "reflection",
)

_TOKEN_NAME_GROUP = "|".join(re.escape(n) for n in _HARMONY_TOKEN_NAMES)

# Match ``<|name|>``, ``<|name>``, ``<name|>`` — all three forms.
# The token name has to be in our known list so we don't accidentally
# strip legitimate prose like ``<chapter|>`` or other text the author
# might have. Followed by an optional payload (``thought``,
# ``analysis``, etc.) on the same line; we keep that payload short
# to avoid eating actual sentences.
_META_TOKEN_RE = re.compile(
    rf"<\|?({_TOKEN_NAME_GROUP})\|?>",
    re.IGNORECASE,
)

# Mistral [INST] / [/INST] markers — bracket form.
_MISTRAL_INST_RE = re.compile(r"\[/?INST\]", re.IGNORECASE)

# Bare role-name lines some models leak: ``assistant\n``, ``thought\n``
# at the start of a response. Only strip when on its OWN line as a
# leading marker — a paragraph that happens to start with "Assistant"
# in dialogue should survive.
_LEADING_ROLE_RE = re.compile(
    r"^\s*(?:assistant|user|system|developer|thought|analysis|"
    r"reasoning|reflection|thinking)\s*[:\n]",
    re.IGNORECASE,
)

# Block-form thinking / scratchpad tags that wrap multi-line content.
# We strip the tags AND their content on the assumption the model's
# meta-thinking shouldn't reach the user. Bound the match so a
# runaway tag doesn't swallow the whole response.
_THINK_BLOCK_RES = [
    re.compile(r"<think(?:ing)?\b[^>]*>(.*?)</think(?:ing)?>",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"<thought\b[^>]*>(.*?)</thought>",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"<reasoning\b[^>]*>(.*?)</reasoning>",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"<analysis\b[^>]*>(.*?)</analysis>",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"<scratchpad\b[^>]*>(.*?)</scratchpad>",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"<reflection\b[^>]*>(.*?)</reflection>",
               re.IGNORECASE | re.DOTALL),
]

# Repeated whitespace runs left behind after stripping.
_MULTIBLANK_RE = re.compile(r"\n{3,}")


# ── Public API ──────────────────────────────────────────────────────


def strip_meta_tokens(text: str) -> str:
    """Remove model-specific channel / chat-format tokens from ``text``.

    Handles Harmony, ChatML, Llama 3, Mistral [INST], and common
    thinking/reasoning block tags. Idempotent — running twice is safe
    and produces the same result.

    Returns the cleaned string with collapsed leading/trailing
    whitespace and de-duplicated blank lines.
    """
    if not text:
        return ""
    out = text

    # Strip block-form thinking tags (and their content) first so the
    # token-form pass below doesn't trip on inner ``<|x|>`` markers.
    for rx in _THINK_BLOCK_RES:
        out = rx.sub("", out)

    # Strip Harmony / ChatML / Llama / similar single tokens.
    out = _META_TOKEN_RE.sub("", out)

    # Strip Mistral instruction brackets.
    out = _MISTRAL_INST_RE.sub("", out)

    # Strip leading bare role markers ("assistant:", "thought\n", etc.)
    # — but only at the very start, not inside the body.
    out = _LEADING_ROLE_RE.sub("", out, count=1)

    # Drop lines that are ONLY a meta-name word (or a couple of
    # whitespace-separated meta-name words). These are residuals from
    # patterns like ``<|channel>thought<channel|>`` where the bracket
    # cleanup leaves the payload word ("thought") on its own line.
    # We're conservative: only matches lines whose every word is in
    # the meta-name list, so a normal sentence with the word
    # "channel" or "thought" in it survives.
    meta_name_set = {n.lower() for n in _HARMONY_TOKEN_NAMES}
    cleaned_lines = []
    for line in out.splitlines():
        stripped = line.strip().rstrip(":,;.")
        if stripped:
            words = stripped.lower().split()
            if words and all(w in meta_name_set for w in words):
                continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines)

    # Collapse whitespace runs left behind by the deletions.
    out = _MULTIBLANK_RE.sub("\n\n", out).strip()
    return out


def degeneration_score(text: str) -> float:
    """Score how 'degenerate' a model output looks (0.0 clean → 1.0 garbage).

    Counts characters that look like meta-token leakage vs. actual
    prose characters. Empty / very short input scores 0 (we can't tell).

    The score is conservative — we want to avoid false positives that
    would block legitimate prose. The thresholding into a boolean
    happens in ``is_degenerate_output``.
    """
    if not text:
        return 0.0
    # Total non-whitespace chars — what we'd compare to "real" text
    nws = len(re.sub(r"\s+", "", text))
    if nws < 20:
        return 0.0
    # Chars consumed by meta tokens (all forms summed)
    meta_chars = 0
    for rx in (_META_TOKEN_RE, _MISTRAL_INST_RE):
        for m in rx.finditer(text):
            meta_chars += len(m.group(0))
    for rx in _THINK_BLOCK_RES:
        for m in rx.finditer(text):
            meta_chars += len(m.group(0))
    if meta_chars == 0:
        return 0.0
    return min(1.0, meta_chars / nws)


def is_degenerate_output(text: str, threshold: float = 0.40) -> bool:
    """True when the response is mostly meta-token spam.

    Default threshold is 40% of non-whitespace characters being part
    of meta tokens — well above any normal prose's "stray markup"
    rate but well below the "model emitted only tokens" failure mode.
    """
    return degeneration_score(text) >= threshold


def sanitize_and_check(text: str) -> Tuple[str, bool]:
    """Convenience: strip tokens AND report degeneration of the original.

    Returns ``(cleaned_text, was_degenerate)``. The caller uses the
    cleaned text either way — when degenerate, it should ALSO surface
    a clear warning to the user instead of silently inserting it.
    """
    was_degenerate = is_degenerate_output(text)
    cleaned = strip_meta_tokens(text)
    return cleaned, was_degenerate
