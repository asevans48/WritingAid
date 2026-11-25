"""The writer's contact details for the title page (9.2 addendum, 24 Nov 2026).

Name, phone, email and postal address belong to the writer, not to a
book, so they are kept once for the whole app: under the new key
``writer_contact`` in the CreativeOS settings (``~/.creativeos/config.json``),
written safely by ``CreativeOSConfig.save``. Every other key in that file
is left as it is, and keys inside ``writer_contact`` this module does not
know are kept too.

The byline (pen name) is the book's: it is the manuscript's existing
``author`` field, which the title page has always used. So:

* **top left of the title page:** the real name (``name`` here, or the
  manuscript's author when no name is set, as before), then the address
  lines, phone and email (Shunn's format);
* **byline** ("A Novel by …") and the running header's surname: the
  manuscript's author (the pen name) when set, else the name.

Empty fields are left out, so with nothing filled in the title page is
exactly what it was.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

KEY = "writer_contact"
FIELDS = ("name", "phone", "email", "address")


def _config(config: Any = None) -> Any:
    if config is not None:
        return config
    from src.config.creativeos_config import get_creativeos_config
    return get_creativeos_config()


def load(config: Any = None) -> Dict[str, str]:
    """The stored details, every field a string ("" when unset or unreadable)."""
    try:
        stored = _config(config).get(KEY) or {}
    except Exception as e:                  # missing or damaged settings mean defaults
        print(f"[writer-contact] {e}")
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {f: stored.get(f) if isinstance(stored.get(f), str) else "" for f in FIELDS}


def set_field(field: str, value: str, config: Any = None) -> bool:
    """Store one field. The other fields, and unknown keys, are kept."""
    if field not in FIELDS:
        raise ValueError(f"unknown contact field {field!r}")
    cfg = _config(config)
    stored = cfg.get(KEY)
    data = dict(stored) if isinstance(stored, dict) else {}
    data[field] = value or ""
    cfg.set(KEY, data)
    return True


def byline(author: str, contact: Optional[Dict[str, str]] = None) -> str:
    """The name the book goes out under: the pen name, else the real name."""
    return (author or "").strip() or ((contact or {}).get("name") or "").strip()


def contact_block(author: str, contact: Optional[Dict[str, str]] = None) -> List[str]:
    """The title page's top-left lines: real name, address lines, phone, email.
    Empty fields are left out."""
    c = contact or {}
    lines = [((c.get("name") or "").strip() or (author or "").strip())]
    lines += [ln.strip() for ln in (c.get("address") or "").splitlines()]
    lines += [(c.get("phone") or "").strip(), (c.get("email") or "").strip()]
    return [ln for ln in lines if ln]


def set_pen_name(project: Any, pen_name: str) -> None:
    """Set the byline on the project's main manuscript, and on each novella
    that still carries the main manuscript's byline (they copy it when made)."""
    pen_name = (pen_name or "").strip()
    try:
        main = project.get_main_manuscript()
    except Exception:
        main = getattr(project, "manuscript", None)
    if main is None:
        return
    old = main.author or ""
    main.author = pen_name
    for sp in getattr(project, "subprojects", None) or []:
        ms = getattr(sp, "manuscript", None)
        if ms is not None and (ms.author or "") in (old, ""):
            ms.author = pen_name


def pen_name(project: Any) -> str:
    try:
        return project.get_main_manuscript().author or ""
    except Exception:
        return getattr(getattr(project, "manuscript", None), "author", "") or ""
