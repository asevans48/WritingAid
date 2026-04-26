"""User-extensible corpus registry.

Stores corpus entries the user added themselves (custom URLs, local
files) at ``~/.creativeos/corpus_registry.json``. Combined with the
built-in :mod:`corpus_catalog` to produce the full list shown in the
Training Studio.

User-added entries that aren't on the license safelist must be marked
``user-attested`` — meaning the user has confirmed they have the
right to use the source. The registry never auto-downloads anything
without an explicit user click in the UI.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from src.data.corpus_catalog import CATALOG, CorpusEntry, is_license_safe


REGISTRY_PATH = Path.home() / ".creativeos" / "corpus_registry.json"


def _load_user_entries() -> List[CorpusEntry]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[corpus_registry] could not read {REGISTRY_PATH}: {e}")
        return []
    out: List[CorpusEntry] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(CorpusEntry(
                id=item.get("id", ""),
                name=item.get("name", ""),
                description=item.get("description", ""),
                url=item.get("url", ""),
                license=item.get("license", "user-attested"),
                license_url=item.get("license_url", ""),
                format=item.get("format", "txt"),
                author=item.get("author", ""),
                tags=list(item.get("tags", []) or []),
                size_hint_kb=int(item.get("size_hint_kb", 0)),
                source_page=item.get("source_page", ""),
            ))
        except Exception:
            continue
    return out


def _save_user_entries(entries: List[CorpusEntry]) -> bool:
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_PATH, 'w', encoding='utf-8') as f:
            json.dump([asdict(e) for e in entries], f,
                      indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[corpus_registry] could not save: {e}")
        return False


def all_entries() -> List[CorpusEntry]:
    """Built-in catalog followed by user-added entries (deduped by id)."""
    seen = set()
    result: List[CorpusEntry] = []
    for e in list(CATALOG) + _load_user_entries():
        if e.id in seen:
            continue
        seen.add(e.id)
        result.append(e)
    return result


def builtin_ids() -> set:
    return {c.id for c in CATALOG}


def add_user_entry(entry: CorpusEntry) -> bool:
    """Append (or replace by id) a user entry. Returns False if id is
    blank or collides with a built-in id (built-ins are read-only).
    """
    if not entry.id:
        return False
    if entry.id in builtin_ids():
        return False
    users = _load_user_entries()
    users = [u for u in users if u.id != entry.id]
    users.append(entry)
    return _save_user_entries(users)


def remove_user_entry(corpus_id: str) -> bool:
    if corpus_id in builtin_ids():
        return False  # built-ins can't be deleted
    users = _load_user_entries()
    new = [u for u in users if u.id != corpus_id]
    if len(new) == len(users):
        return False
    return _save_user_entries(new)


def license_label_for(entry: CorpusEntry) -> str:
    """Return a UI label describing the license risk level."""
    if is_license_safe(entry.license):
        return f"✓ {entry.license}"
    if entry.license == "user-attested":
        return "⚠ user-attested"
    return f"⚠ {entry.license or 'unknown'}"
