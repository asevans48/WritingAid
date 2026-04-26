"""Unified model registry — the one place every part of the app reads
from when it needs to know "what models are available?"

Before this module, eight separate sources answered that question
(``trained_models.json``, ``MLX_MODELS``, ``PYTORCH_MODELS``,
``TRAINING_BASE_MODELS``, the HF cache, …). Each UI surface read
whichever subset it cared about, and they drifted.

This module is a **read-only aggregator**: existing data sources stay
where they are (the Training Studio still writes ``trained_models.json``,
the model_picker_widget still owns the inference catalogs), and this
module reads them all on demand. No migration, no duplicate state.

The user-facing concept is a single list: every model the app knows
about, tagged with its kind. UI surfaces (Training Studio, Writing
Tool settings, the new Model Hub) consume ``list_models()`` and
filter by kind/tag for their use cases.

**Schema** — see :class:`ModelEntry`.

**Mutation surfaces** — only:
  * ``register_pretrained_id(hf_id)`` for ad-hoc HF ids users pin
    (e.g. ones they typed into the editable combo that aren't in any
    catalog). Persists to ``~/.creativeos/pinned_models.json``.
  * ``delete_model(entry_id, *, kind)`` propagates deletions to the
    underlying source: trained models go through
    ``creativeos_config.delete_trained_model`` (which already cascades
    to per-task settings and on-disk files); pinned pretrained ids are
    just dropped from ``pinned_models.json``; built-in catalog entries
    can't be deleted but can be excluded via the existing
    ``excluded_base_models`` list.

Everything else flows through the existing surfaces.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# Single source of truth for where the pinned-pretrained list lives.
_PINNED_REGISTRY_PATH = (
    Path.home() / ".creativeos" / "pinned_models.json")


KIND_TRAINED = "trained"          # local LoRA adapter from the Studio
KIND_PRETRAINED_BUILTIN = "pretrained_builtin"  # in MLX_/PYTORCH_/TRAINING_BASE catalogs
KIND_PRETRAINED_PINNED = "pretrained_pinned"    # ad-hoc HF id the user pinned


@dataclass
class ModelEntry:
    """Unified description of a single model the app knows about.

    The fields below are the union of what every existing surface
    needed. Where a source doesn't have a value, the field is the
    sensible default (``""`` or ``0``) — never None — so callers can
    always render the entry without null-guarding.

    ``id`` is the registry-unique key used by everything else: for
    trained models it's the registry name ("voice-v2"); for built-in
    pretrained models it's the HuggingFace id ("google/gemma-3-2b");
    for pinned pretrained ids it's also the HF id. Two entries can't
    share an id within a single registry view.
    """
    id: str
    kind: str
    display_name: str
    base_model: str = ""
    path: str = ""
    intent: str = ""
    framework: str = ""           # "mlx" | "pytorch" | ""
    family: str = ""              # "gemma" | "llama" | "qwen" | …
    size_b: float = 0.0
    quantization: str = ""
    is_adapter: bool = False
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def loadable_path(self) -> str:
        """Where to load this model from.

        For trained adapters: the on-disk directory. For pretrained
        models: the HF id (Transformers/PEFT loaders accept that
        directly and pull from the local HF cache or download).
        """
        return self.path or self.base_model or self.id


# ── Source readers ─────────────────────────────────────────

def _read_trained_models() -> List[ModelEntry]:
    """Pull every entry from ``trained_models.json`` into ModelEntry shape."""
    try:
        from src.config.creativeos_config import load_trained_models
    except Exception:
        return []
    out: List[ModelEntry] = []
    for m in load_trained_models() or []:
        path = m.get("path") or ""
        base = m.get("base_model") or ""
        is_adapter = bool(
            path and (Path(path) / "adapter_config.json").exists())
        out.append(ModelEntry(
            id=m.get("name", "") or path,
            kind=KIND_TRAINED,
            display_name=m.get("name") or "(untitled)",
            base_model=base,
            path=path,
            intent=(m.get("intent") or "").lower(),
            family=_family_from_id(base),
            size_b=_size_from_id(base),
            is_adapter=is_adapter,
            tags=["trained"] + (
                ["adapter"] if is_adapter else ["full"]),
            metadata={
                "dataset_size": m.get("dataset_size", 0),
                "genres": m.get("genres") or [],
                "tones": m.get("tones") or [],
                "continued_from": m.get("continued_from") or "",
                "created_at": m.get("created_at") or "",
                "notes": m.get("notes") or "",
            }))
    return out


def _read_builtin_pretrained() -> List[ModelEntry]:
    """Pull from MLX/PYTORCH/TRAINING_BASE catalogs.

    De-duplicates: a model in both PyTorch and Training-Base catalogs
    appears once in the unified list; the union of tags reflects all
    catalog memberships ("inference-ready", "fine-tunable", …).
    """
    try:
        from src.ui.model_picker_widget import (
            MLX_MODELS, PYTORCH_MODELS, TRAINING_BASE_MODELS,
        )
    except Exception:
        return []

    by_id: Dict[str, ModelEntry] = {}
    catalogs = [
        ("mlx", "inference", MLX_MODELS),
        ("pytorch", "inference", PYTORCH_MODELS),
        ("pytorch", "fine-tunable", TRAINING_BASE_MODELS),
    ]
    for framework, kind_tag, items in catalogs:
        for info in (items or []):
            mid = info.model_id
            existing = by_id.get(mid)
            tags = (existing.tags if existing else []) + [kind_tag]
            entry = ModelEntry(
                id=mid,
                kind=KIND_PRETRAINED_BUILTIN,
                display_name=info.display_name,
                base_model=mid,
                framework=framework,
                family=_family_from_id(mid),
                size_b=_size_from_id(mid, fallback_gb=info.size_gb),
                tags=sorted(set(tags)),
                metadata={
                    "size_gb_disk": info.size_gb,
                    "ram_required": info.ram_required,
                    "best_for": info.best_for,
                    "description": info.description,
                    "trust_remote_code": getattr(
                        info, "requires_trust_remote_code", False),
                })
            by_id[mid] = entry
    return list(by_id.values())


def _read_pinned() -> List[ModelEntry]:
    """User-pinned HF ids that aren't in any catalog."""
    if not _PINNED_REGISTRY_PATH.exists():
        return []
    try:
        with open(_PINNED_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: List[ModelEntry] = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        mid = entry["id"]
        # Infer framework so the cache picks the right loader on
        # first use. ``mlx-community/`` ids and ``-mlx-`` patterns
        # are MLX-quantised; everything else assumes pytorch.
        framework = "mlx" if _looks_like_mlx_id(mid) else ""
        out.append(ModelEntry(
            id=mid,
            kind=KIND_PRETRAINED_PINNED,
            display_name=entry.get("display_name") or mid,
            base_model=mid,
            framework=framework,
            family=_family_from_id(mid),
            size_b=float(entry.get("size_b") or _size_from_id(mid)),
            tags=["pinned"],
            metadata=entry.get("metadata") or {}))
    return out


def _looks_like_mlx_id(model_id: str) -> bool:
    """Same check as ``model_cache._looks_like_mlx_id`` — duplicated
    here so the registry doesn't import from ``ai/`` (which would
    pull in transformers transitively at registry-read time)."""
    if not model_id:
        return False
    lower = model_id.lower()
    return (lower.startswith("mlx-community/")
            or "-mlx-" in lower
            or lower.endswith("-mlx"))


# ── Helpers ────────────────────────────────────────────────

def _family_from_id(model_id: str) -> str:
    """Extract a family label from an HF id ("gemma", "llama", "qwen")."""
    if not model_id:
        return ""
    lower = model_id.lower()
    for fam in ("gemma", "llama", "mistral", "qwen", "phi",
                "deepseek", "yi", "tinyllama", "stablelm",
                "openchat", "gpt"):
        if fam in lower:
            return fam
    return ""


def _size_from_id(model_id: str, *, fallback_gb: float = 0.0) -> float:
    """Pull the parameter count in billions out of an HF id.

    Handles the common naming conventions: ``Llama-3.2-1B`` → 1.0,
    ``gemma-3-12B-it`` → 12.0, ``Qwen2.5-0.5B`` → 0.5. When the id
    has no recognisable size marker we fall back to estimating from
    the on-disk size (~2 GB per billion params for bf16).
    """
    if not model_id:
        return 0.0
    import re
    m = re.search(
        r'(\d+(?:\.\d+)?)\s*[Bb]\b',
        model_id.replace("-", " ").replace("_", " "))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    if fallback_gb > 0:
        return round(fallback_gb / 2.0, 1)
    return 0.0


# ── Public API ─────────────────────────────────────────────

def list_models(*, kinds: Optional[List[str]] = None,
                family: str = "",
                framework: str = "",
                intent: str = "",
                downloaded_only: bool = False) -> List[ModelEntry]:
    """Return every model the app knows about, filtered as requested.

    Args:
        kinds: restrict to one or more of ``KIND_TRAINED``,
            ``KIND_PRETRAINED_BUILTIN``, ``KIND_PRETRAINED_PINNED``.
            None = all kinds.
        family: only return models from a single family (gemma, llama, …).
        framework: "mlx" or "pytorch".
        intent: only trained models with this stored intent.
        downloaded_only: only return models present in the local HF
            cache (or, for trained, with an existing on-disk path).
    """
    entries = (_read_trained_models()
               + _read_builtin_pretrained()
               + _read_pinned())
    if kinds is not None:
        kinds_set = set(kinds)
        entries = [e for e in entries if e.kind in kinds_set]
    if family:
        entries = [e for e in entries if e.family == family]
    if framework:
        entries = [e for e in entries
                   if not e.framework or e.framework == framework]
    if intent:
        entries = [e for e in entries if e.intent == intent]
    if downloaded_only:
        cached = _hf_cached_ids()
        def _is_present(e: ModelEntry) -> bool:
            if e.kind == KIND_TRAINED:
                return bool(e.path) and Path(e.path).exists()
            return e.base_model in cached
        entries = [e for e in entries if _is_present(e)]
    # Stable ordering: trained first (most likely user's own work),
    # then built-in, then pinned. Within each group: family then size.
    kind_order = {KIND_TRAINED: 0,
                  KIND_PRETRAINED_BUILTIN: 1,
                  KIND_PRETRAINED_PINNED: 2}
    entries.sort(
        key=lambda e: (kind_order.get(e.kind, 99),
                       e.family, e.size_b, e.display_name))
    return entries


def find_entry(entry_id: str, *,
               kind: Optional[str] = None) -> Optional[ModelEntry]:
    """Look up an entry by id (and optionally kind for disambiguation).

    Two entries from different kinds may share an id (rare, but a
    user could pin an HF id that's also in the built-in catalog).
    Pass ``kind`` when that ambiguity matters.
    """
    for e in list_models(kinds=[kind] if kind else None):
        if e.id == entry_id:
            return e
    return None


def register_pretrained_id(hf_id: str, *,
                           display_name: str = "",
                           metadata: Optional[Dict[str, Any]] = None,
                           ) -> ModelEntry:
    """Pin a HuggingFace id the user wants to remember.

    Useful when the user types a model into an editable combo that
    isn't in the built-in catalog. The pin survives across sessions
    so the next time they open the Hub the model is visible.
    Idempotent — pinning the same id twice updates the existing
    entry's metadata.
    """
    if not hf_id or not hf_id.strip():
        raise ValueError("hf_id must be non-empty")
    hf_id = hf_id.strip()
    _PINNED_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if _PINNED_REGISTRY_PATH.exists():
        try:
            with open(_PINNED_REGISTRY_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, list):
                existing = [x for x in d
                            if isinstance(x, dict) and x.get("id") != hf_id]
        except (OSError, ValueError):
            pass
    new_entry = {
        "id": hf_id,
        "display_name": display_name or hf_id,
        "size_b": _size_from_id(hf_id),
        "metadata": metadata or {},
    }
    existing.append(new_entry)
    with open(_PINNED_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return ModelEntry(
        id=hf_id,
        kind=KIND_PRETRAINED_PINNED,
        display_name=new_entry["display_name"],
        base_model=hf_id,
        family=_family_from_id(hf_id),
        size_b=new_entry["size_b"],
        tags=["pinned"],
        metadata=new_entry["metadata"])


def delete_model(entry_id: str, *,
                 kind: str,
                 remove_files: bool = True) -> bool:
    """Delete a model and propagate the deletion everywhere.

    Behaviour by kind:
      * ``KIND_TRAINED`` — delegates to
        ``creativeos_config.delete_trained_model`` which already
        cascades: registry entry, on-disk dir, per-task settings,
        agent suite cache.
      * ``KIND_PRETRAINED_PINNED`` — drop from pinned_models.json.
      * ``KIND_PRETRAINED_BUILTIN`` — built-in catalog entries can't
        be removed (they're code constants), but we hide them by
        adding their id to ``excluded_base_models`` so they vanish
        from every UI that respects the exclusion list.

    Returns True if anything changed.
    """
    if kind == KIND_TRAINED:
        try:
            from src.config.creativeos_config import delete_trained_model
        except Exception:
            return False
        return delete_trained_model(entry_id, remove_files=remove_files)

    if kind == KIND_PRETRAINED_PINNED:
        if not _PINNED_REGISTRY_PATH.exists():
            return False
        try:
            with open(_PINNED_REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return False
            new_data = [x for x in data
                        if not (isinstance(x, dict)
                                and x.get("id") == entry_id)]
            if len(new_data) == len(data):
                return False
            with open(_PINNED_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)
            return True
        except (OSError, ValueError):
            return False

    if kind == KIND_PRETRAINED_BUILTIN:
        try:
            from src.config.creativeos_config import (
                excluded_base_models, set_excluded_base_models,
            )
        except Exception:
            return False
        cur = list(excluded_base_models() or [])
        if entry_id in cur:
            return False
        cur.append(entry_id)
        set_excluded_base_models(cur)
        return True

    return False


def _hf_cached_ids() -> set:
    """Return the set of HuggingFace ids currently in the local cache."""
    try:
        from huggingface_hub import scan_cache_dir
    except Exception:
        return set()
    try:
        info = scan_cache_dir()
    except Exception:
        return set()
    return {repo.repo_id for repo in info.repos
            if getattr(repo, "repo_type", "") == "model"}
