"""The one list of cloud model providers, by the name stored in settings.

Settings store the provider as a word (``default_llm`` = "claude",
"chatgpt", "openai", "gemini" or "server"). Every place that builds a cloud
``LLMClient`` from that word uses :func:`provider_for_name`, so adding a
provider is one edit here.

The lookup is exact: callers that lowercase or strip the name do so before
calling, as they did before this list existed.
"""

from typing import Optional

from src.ai.llm_client import LLMProvider

# Stored name -> provider. These names are written in users' settings files;
# never rename or remove one.
PROVIDERS_BY_NAME = {
    "claude": LLMProvider.CLAUDE,
    "chatgpt": LLMProvider.CHATGPT,
    "openai": LLMProvider.CHATGPT,
    "gemini": LLMProvider.GEMINI,
    "server": LLMProvider.SERVER,
}

_CLAUDE = LLMProvider.CLAUDE


def provider_for_name(name, default: Optional[LLMProvider] = _CLAUDE
                      ) -> Optional[LLMProvider]:
    """Return the ``LLMProvider`` for a stored provider name.

    An unknown name gives ``default``: Claude unless the caller passes
    another value (``None`` to treat an unknown name as "no provider").
    """
    return PROVIDERS_BY_NAME.get(name, default)
