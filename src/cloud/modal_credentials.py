"""Modal API credentials — store securely, retrieve, apply to environment.

The Modal SDK authenticates via two values: ``MODAL_TOKEN_ID`` and
``MODAL_TOKEN_SECRET``. The CLI's ``modal token new`` writes them to
``~/.modal.toml`` after a browser-based handshake. That works fine
for users who can run ``modal token new`` themselves — but we want
the studio to also let users paste a pre-issued token-pair and have
it stored in the OS keystore (Keychain on macOS, Credential Manager
on Windows, Secret Service on Linux), the same way the rest of the
app stores Claude / OpenAI / HF keys.

**Storage** — :class:`CredentialManager` (the same one that handles
every other API key in this app) under the ``modal_token_id`` and
``modal_token_secret`` keys. Two keys, not one combined string, so
the user can rotate one without re-pasting the other.

**Retrieval** — :func:`get_tokens` returns ``(id, secret)`` or
``(None, None)``. Used by the cloud trainer's pre-submit hook.

**Application to the Modal SDK** — :func:`apply_tokens_to_env`
exports the keystore values into ``os.environ`` if (and only if)
they're not already set there or in ``~/.modal.toml``. This lets us
support all three sources cleanly: existing env vars win
(developer setup), then ``~/.modal.toml`` (CLI auth), then the
keystore (paste-into-UI auth). The studio's setup check reflects
the same priority so the UI never lies about which source is active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.config.credential_manager import CredentialManager


@dataclass
class CredentialSource:
    """Where the active Modal token-pair came from. Returned by
    :func:`describe_active_source` so the UI can show the user
    which authentication source is currently in play (and warn them
    if it's not the one they just edited)."""
    name: str          # "env", "modal_toml", "keystore", or "none"
    has_id: bool
    has_secret: bool

    @property
    def authenticated(self) -> bool:
        return self.has_id and self.has_secret


def set_tokens(token_id: str, token_secret: str) -> bool:
    """Store both tokens in the OS keystore. Returns True on success.

    Empty strings are treated as a delete request — pass ``"", ""``
    to clear. The keystore deletes the key entirely so a subsequent
    ``get_tokens`` returns ``(None, None)`` and Modal falls back to
    its other authentication paths.
    """
    cm = CredentialManager()
    ok_id = cm.store_credential(CredentialManager.MODAL_TOKEN_ID,
                                 token_id or "")
    ok_secret = cm.store_credential(CredentialManager.MODAL_TOKEN_SECRET,
                                     token_secret or "")
    return ok_id and ok_secret


def get_tokens() -> Tuple[Optional[str], Optional[str]]:
    """Read both tokens from the keystore. Returns ``(None, None)``
    if either is missing — Modal needs both to authenticate."""
    cm = CredentialManager()
    tid = cm.get_credential(CredentialManager.MODAL_TOKEN_ID)
    tsec = cm.get_credential(CredentialManager.MODAL_TOKEN_SECRET)
    if not tid or not tsec:
        return (None, None)
    return (tid, tsec)


def clear_tokens() -> bool:
    """Remove both tokens from the keystore. Returns True if at
    least one was deleted (or both were already absent)."""
    cm = CredentialManager()
    ok_id = cm.delete_credential(CredentialManager.MODAL_TOKEN_ID)
    ok_secret = cm.delete_credential(CredentialManager.MODAL_TOKEN_SECRET)
    return ok_id and ok_secret


def has_keystore_tokens() -> bool:
    """Cheap "do we have something to apply?" probe."""
    tid, tsec = get_tokens()
    return bool(tid and tsec)


def has_env_tokens() -> bool:
    return bool(os.environ.get("MODAL_TOKEN_ID")
                and os.environ.get("MODAL_TOKEN_SECRET"))


def has_modal_toml_tokens() -> bool:
    return (Path.home() / ".modal.toml").exists()


def describe_active_source() -> CredentialSource:
    """Tell the UI where Modal's auth would come from right now.

    Priority matches what ``apply_tokens_to_env`` enforces: env vars
    win, then ~/.modal.toml, then keystore. The active source is the
    *first* layer with both halves of the token-pair available.
    """
    if has_env_tokens():
        return CredentialSource(
            name="env",
            has_id=bool(os.environ.get("MODAL_TOKEN_ID")),
            has_secret=bool(os.environ.get("MODAL_TOKEN_SECRET")))
    if has_modal_toml_tokens():
        return CredentialSource(
            name="modal_toml", has_id=True, has_secret=True)
    if has_keystore_tokens():
        return CredentialSource(
            name="keystore", has_id=True, has_secret=True)
    return CredentialSource(name="none", has_id=False, has_secret=False)


def apply_tokens_to_env() -> bool:
    """Inject the keystore-stored tokens into ``os.environ`` so the
    Modal SDK picks them up.

    Behaviour:
      * If env vars are already set, do nothing — developer setup wins.
      * If ``~/.modal.toml`` exists, do nothing — Modal CLI auth wins.
      * Otherwise, copy keystore values into the env vars.

    Idempotent — safe to call before every Modal API touch.
    Returns True if env now has authentication available (from any
    source), False if nothing's configured anywhere.
    """
    if has_env_tokens():
        return True
    if has_modal_toml_tokens():
        return True
    tid, tsec = get_tokens()
    if not (tid and tsec):
        return False
    os.environ["MODAL_TOKEN_ID"] = tid
    os.environ["MODAL_TOKEN_SECRET"] = tsec
    return True
