"""Hugging Face token plumbing for video-studio backends.

Single source of truth for "where does the HF token come from" so
backend code doesn't reinvent it. The token is stored by the app's
``CredentialManager`` (settings → Hugging Face token); we lift it
from there and surface it in two forms:

  * ``env_overrides_with_token()`` — a small dict an InstallStep can
    pass via ``env_overrides`` so ``hf download`` / ``snapshot_download``
    pick it up automatically (huggingface_hub honors both ``HF_TOKEN``
    and ``HUGGING_FACE_HUB_TOKEN``).
  * ``get_token()`` — the raw string, used at generate time when we
    pass ``token=...`` directly to ``diffusers.from_pretrained``.

Returns None / empty dict when no token is configured — callers can
proceed without auth (works for public models) and only see auth
errors when a gated model actually refuses anonymous downloads.
"""

from __future__ import annotations

from typing import Dict, Optional


def get_token() -> Optional[str]:
    """Return the configured Hugging Face token, or None if unset.

    Wrapped in a defensive try/except: this is called from backend
    code that should never explode just because settings can't be
    read.
    """
    try:
        from src.config.credential_manager import (
            get_credential_manager,
        )
        token = get_credential_manager().get_huggingface_token()
        return token.strip() if isinstance(token, str) and token.strip() else None
    except Exception:
        return None


def env_overrides_with_token() -> Dict[str, str]:
    """Env dict to merge into an InstallStep's subprocess env.

    Sets both ``HF_TOKEN`` and ``HUGGING_FACE_HUB_TOKEN`` because
    different versions of the huggingface_hub library and CLI
    historically picked up different names — covering both keeps
    download steps working across installs.
    """
    token = get_token()
    if not token:
        return {}
    return {
        "HF_TOKEN": token,
        "HUGGING_FACE_HUB_TOKEN": token,
    }


def has_token() -> bool:
    return get_token() is not None
