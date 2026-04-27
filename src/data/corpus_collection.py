"""Corpus collections — first-class saved manifests over the source registry.

A *Corpus* is a named recipe that says "for the next training run, use rows
from these sources." A *source* is one of:

  * ``catalog:<corpus_id>``  — an ingested catalog corpus (e.g.
    ``catalog:hf-tinystories``). Backed by rows in ``rephrases`` whose
    ``notes`` contain ``corpus_id=hf-tinystories``.
  * ``project:<name>``       — chapters imported from a writer project.
    Backed by rows whose notes contain ``project_source=<name>``.
  * ``upload:<title>``       — a file the user uploaded directly (book,
    chapter, draft). Backed by rows whose notes contain
    ``corpus_title=<title>`` but no ``corpus_id``.

The point of this layer is to let the user keep their *raw* downloads
(ingested rows) intact and build many curated training subsets over
them without re-ingesting anything. Saving / loading / deleting a
corpus does **not** touch the underlying rows; only an explicit
"delete download" action does.

Storage: ``~/.creativeos/corpora/<id>.json``. JSON keeps corpora
diff-friendly and easy to back up alongside the rest of the user's
configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json
import re
import uuid


CORPORA_DIR = Path.home() / ".creativeos" / "corpora"


_KB = 1024
_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024
# Switch to GB once we'd be displaying ≥ 800 MB. Below that, MB
# reads better (e.g. "650 MB" vs "0.6 GB"); above it the GB scale
# is the easier mental model for "is this big".
_GB_CUTOFF = int(0.8 * _GB)


def format_bytes(n: int) -> str:
    """Pretty-print a byte count for the manager UI.

    Unit picking follows the user's chosen rules:

      * ≥ 0.8 GB → show as GB (e.g. ``"1.4 GB"``)
      * 1 MB to < 0.8 GB → show as MB (e.g. ``"650 MB"``)
      * everything below 1 MB → show as KB (so a 256-byte row
        says ``"0.3 KB"`` rather than dropping to bytes)

    1024-base — keeps numbers consistent with what ``du`` and most
    OS file dialogs report.
    """
    if n is None or n <= 0:
        return "0 KB"
    if n >= _GB_CUTOFF:
        return f"{n / _GB:.1f} GB"
    if n >= _MB:
        return f"{n / _MB:.1f} MB"
    return f"{n / _KB:.1f} KB"


@dataclass
class Corpus:
    """A user-defined training subset.

    Source keys are kept as strings rather than typed objects so an
    older corpus that points at a now-deleted catalog entry is still
    loadable — we just surface "0 rows" for the missing source in the
    manager UI instead of erroring on load.
    """

    id: str
    name: str
    description: str = ""
    source_keys: List[str] = field(default_factory=list)
    intent: str = ""                    # voice / plot / both / qa / etc.
    genres: List[str] = field(default_factory=list)
    tones: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, name: str = "Untitled corpus", **kwargs) -> "Corpus":
        now = datetime.now().isoformat(timespec="seconds")
        return cls(
            id=uuid.uuid4().hex[:12],
            name=name,
            created_at=now,
            updated_at=now,
            **kwargs,
        )

    def touch(self) -> None:
        """Bump ``updated_at`` to now. Call this from the store on save."""
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "Corpus":
        # Be liberal in what we accept — older saves may not have every
        # field. Defaults defined on the dataclass cover those gaps.
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**clean)


# ── Source registry helpers ────────────────────────────────────

def parse_source_key(key: str) -> Dict[str, str]:
    """Split ``"<kind>:<value>"`` → ``{"kind", "value"}``.

    Returns an empty dict for malformed keys so callers can treat
    "broken key" as "no rows" rather than crashing.
    """
    if not key or ":" not in key:
        return {}
    kind, value = key.split(":", 1)
    return {"kind": kind, "value": value}


def source_clause_for_key(key: str) -> Optional[str]:
    """Return the SQL substring to LIKE-match this key in ``notes``.

    The ``notes`` column carries the ingest-time markers that identify
    each source:

      * ``corpus_id=<id>`` for catalog ingests
      * ``project_source=<name>`` for project imports
      * ``corpus_title=<title>`` for plain uploads (no corpus_id)

    A ``LIKE '%marker%'`` against ``notes`` is the cheap, index-free
    way to fetch all rows belonging to one source. Returns ``None``
    if the key shape is unrecognized.
    """
    parsed = parse_source_key(key)
    if not parsed:
        return None
    kind = parsed["kind"]
    value = parsed["value"]
    if kind == "catalog":
        return f"corpus_id={value}"
    if kind == "project":
        return f"project_source={value}"
    if kind == "upload":
        return f"corpus_title={value}"
    return None


# ── Store (file-backed) ────────────────────────────────────────

class CorpusStore:
    """Disk-backed registry of saved corpora.

    Each corpus is one JSON file under ``~/.creativeos/corpora/``.
    Listing iterates the directory; loading reads one file. The
    store is intentionally stateless — it never caches in memory —
    so changes made by other processes (or by the user editing a
    JSON file) are picked up on the next call.
    """

    def __init__(self, root: Path = CORPORA_DIR):
        self.root = root

    def _ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, corpus_id: str) -> Path:
        # Sanitize id for filesystem safety. ``Corpus.new()`` produces
        # uuid hex which is already safe, but we accept user input
        # too in case future migrations rename ids.
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', corpus_id)[:64] or "unnamed"
        return self.root / f"{safe}.json"

    def list(self) -> List[Corpus]:
        """Return every saved corpus, newest first.

        Sort key: ``updated_at`` if present, else ``created_at``.
        Files that fail to parse are skipped silently — we'd rather
        keep the manager dialog functional than refuse to render.
        """
        self._ensure_dir()
        out: List[Corpus] = []
        for p in self.root.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out.append(Corpus.from_dict(data))
            except Exception:
                continue
        out.sort(key=lambda c: c.updated_at or c.created_at,
                 reverse=True)
        return out

    def load(self, corpus_id: str) -> Optional[Corpus]:
        path = self._path_for(corpus_id)
        if not path.exists():
            return None
        try:
            return Corpus.from_dict(json.loads(
                path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def save(self, corpus: Corpus) -> None:
        self._ensure_dir()
        corpus.touch()
        path = self._path_for(corpus.id)
        path.write_text(
            json.dumps(corpus.to_dict(), indent=2),
            encoding="utf-8")

    def delete(self, corpus_id: str) -> bool:
        """Delete the manifest. Returns True if a file was removed.

        Does NOT touch the underlying training rows — the source rows
        are independent data and can be reused by other corpora.
        """
        path = self._path_for(corpus_id)
        if not path.exists():
            return False
        path.unlink()
        return True


_DEFAULT_STORE: Optional[CorpusStore] = None


def get_default_store() -> CorpusStore:
    """Process-wide default store. UI code uses this; tests pass a
    custom store path to ``CorpusStore(root=...)``."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = CorpusStore()
    return _DEFAULT_STORE
