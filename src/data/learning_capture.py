"""Tiny helpers that capture AI generations into the unified learning DB.

Every helper:
  * Checks the matching opt-in flag in CreativeOS settings.
  * Swallows any exception (logging is opt-in *and* best-effort — we
    must never break a generation because logging failed).
  * Forwards to the source-type-specific ``log_*`` methods on the
    rephrase database.

Agents call these instead of importing the DB directly so the gating
logic lives in exactly one place.
"""

from __future__ import annotations

from typing import Optional


def _enabled(flag: str) -> bool:
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get(flag, False))
    except Exception:
        return False


def _db():
    from src.data.rephrase_database import get_rephrase_database
    return get_rephrase_database()


def capture_worldbuilding(prompt: str, completion: str,
                          element_type: str = "element") -> None:
    """Log a worldbuilding generation if the user opted in."""
    if not prompt or not completion:
        return
    if not _enabled("enable_worldbuilding_data_collection"):
        return
    try:
        _db().log_worldbuilding(prompt=prompt, completion=completion,
                                element_type=element_type)
    except Exception as e:
        print(f"[learning_capture] worldbuilding log failed: {e}")


def capture_character(prompt: str, completion: str,
                      character_name: Optional[str] = None) -> None:
    """Log a character-generation pair if the user opted in."""
    if not prompt or not completion:
        return
    if not _enabled("enable_character_data_collection"):
        return
    try:
        _db().log_character(prompt=prompt, completion=completion,
                            character_name=character_name or "")
    except Exception as e:
        print(f"[learning_capture] character log failed: {e}")


def capture_plot(prompt: str, completion: str) -> None:
    """Log a plot/outline generation pair if the user opted in."""
    if not prompt or not completion:
        return
    if not _enabled("enable_plot_data_collection"):
        return
    try:
        _db().log_plot(prompt=prompt, completion=completion)
    except Exception as e:
        print(f"[learning_capture] plot log failed: {e}")
