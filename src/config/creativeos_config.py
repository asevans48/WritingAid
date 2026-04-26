"""CreativeOS configuration — shared LLM settings + tool registry.

CreativeOS is the launcher shell that hosts individual tools (Writing Tool
today, Business Agents and Online Platform tomorrow). This module owns:

  * The shared LLM/model preferences applied across every tool by default
  * The tool registry (id, name, description, icon, launcher callback,
    availability flag)
  * Persistence to ``~/.creativeos/config.json``
  * Backwards-compat migration from the old ``~/.writer_platform`` dir

Per-tool configs live in their own files (e.g. the Writing Tool keeps
``~/.writer_platform/ai_config.json``). When a tool launches, it reads
the shared LLM defaults from this module and merges them with its own
overrides, so a user can change the model in one place and have every
tool pick it up — while still letting any tool deviate when it needs to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# Where the shared OS config lives. Per-tool dirs sit alongside.
CREATIVEOS_DIR = Path.home() / ".creativeos"
CREATIVEOS_CONFIG_FILE = CREATIVEOS_DIR / "config.json"

# Legacy Writing Tool config we migrate from on first launch
LEGACY_WRITER_DIR = Path.home() / ".writer_platform"
LEGACY_WRITER_CONFIG = LEGACY_WRITER_DIR / "ai_config.json"


# ── Shared LLM defaults ──────────────────────────────────────

# These are the keys the OS owns. Any tool can override any of them by
# writing to its own config file, but if the tool has no opinion it
# falls back to these.
SHARED_LLM_DEFAULTS: Dict[str, Any] = {
    # Cloud provider keys (also stored in OS keychain when possible)
    "claude_api_key": "",
    "chatgpt_api_key": "",
    "gemini_api_key": "",
    "huggingface_token": "",

    # Provider preference
    "default_llm": "claude",  # claude | chatgpt | gemini
    "claude_model": "claude-opus-4-7",
    "openai_model": "gpt-4-turbo-preview",
    "gemini_model": "gemini-pro",

    # Local model preferences
    "prefer_local_model": False,
    "enable_local_models": False,
    "local_model_id": "",
    "local_model_device": "auto",
    "local_model_quantization": "none",
    "local_model_trust_remote_code": False,

    # Master switch
    "disable_all_ai": False,

    # Per-task model overrides. Each is the *name* of a registered trained
    # model (see ``trained_models.json``) or empty string to fall back to
    # the global ``local_model_id`` / cloud default. The Writing Tool reads
    # these via ``resolve_task_model()``.
    #
    # Tasks:
    #   * rephrase     — sentence-level rewriting in the manuscript editor
    #   * plot         — outline / plot generation
    #   * worldbuilding — generate world elements (locations, factions, lore)
    #   * character    — character profiles, backstories, voice
    #   * general      — fallback for chat / lookup
    "model_for_rephrase": "",
    "model_for_plot": "",
    "model_for_worldbuilding": "",
    "model_for_character": "",
    "model_for_general": "",

    # Transfer-learning data collection (opt-in). Each flag gates one
    # source-type pipeline in the unified learning DB.
    "enable_rephrase_data_collection": False,
    "enable_chat_data_collection": False,  # already used by chat history
    "enable_worldbuilding_data_collection": False,
    "enable_character_data_collection": False,
    "enable_plot_data_collection": False,

    # Built-in base models the user has hidden from the Training Studio's
    # picker. List of HuggingFace ids from MLX_MODELS / PYTORCH_MODELS.
    # Empty list = show every catalog entry.
    "excluded_base_models": [],
}


# Tasks that the writing tool can route to a dedicated trained model.
# Order is the order shown in the settings UI.
TASK_MODEL_KEYS: List[str] = [
    "model_for_rephrase",
    "model_for_plot",
    "model_for_worldbuilding",
    "model_for_character",
    "model_for_general",
]

TASK_MODEL_LABELS: Dict[str, str] = {
    "model_for_rephrase": "Writing & rephrasing",
    "model_for_plot": "Plot / outline generation",
    "model_for_worldbuilding": "Worldbuilding",
    "model_for_character": "Character generation",
    "model_for_general": "General chat / lookup",
}


# Where the registry of locally-trained models lives.
TRAINED_MODELS_REGISTRY = CREATIVEOS_DIR / "trained_models.json"
TRAINED_MODELS_DIR = CREATIVEOS_DIR / "trained_models"


# ── Tool registry ────────────────────────────────────────────

@dataclass
class CreativeOSTool:
    """One tool that can be launched from the CreativeOS launcher."""
    id: str                  # short stable id (e.g. "writing")
    name: str                # display name
    description: str         # one-line tagline
    icon: str = "🛠"         # emoji / unicode glyph for the launcher tile
    available: bool = True   # False -> rendered as "Coming soon"
    config_subdir: Optional[str] = None  # tool-specific config dir name
    launcher: Optional[Callable[[], Any]] = field(default=None, repr=False)
    keywords: List[str] = field(default_factory=list)  # for "Ask AI what to do"


def default_tools() -> List[CreativeOSTool]:
    """The built-in tool list. Launcher callbacks are wired separately
    so this module stays import-safe (no circular deps with UI code).
    """
    return [
        CreativeOSTool(
            id="writing",
            name="Writing Tool",
            description="Long-form writing with worldbuilding, drafts, and AI.",
            icon="✍️",
            available=True,
            config_subdir="writer_platform",
            keywords=["write", "novel", "story", "manuscript", "chapter",
                      "draft", "worldbuilding", "character"],
        ),
        CreativeOSTool(
            id="training",
            name="Model Training Studio",
            description="Fine-tune a model on your collected rephrase data.",
            icon="🎓",
            available=True,
            keywords=["train", "training", "fine-tune", "finetune", "lora",
                      "transfer", "learning", "model", "custom"],
        ),
        CreativeOSTool(
            id="model_hub",
            name="Local Models Hub",
            description=("Browse, load, test, and delete every local "
                         "model — trained or pretrained. Single source "
                         "of truth across CreativeOS."),
            icon="🧠",
            available=True,
            keywords=["model", "models", "hub", "load", "unload", "delete",
                      "local", "registered", "trained", "pretrained",
                      "cache", "ram", "gpu", "loaded", "registry",
                      "test", "evaluate", "swap"],
        ),
        CreativeOSTool(
            id="business_agents",
            name="Business Agents",
            description="Marketing copy, emails, briefs — coming soon.",
            icon="💼",
            available=False,
            keywords=["email", "marketing", "copy", "brief", "business"],
        ),
        CreativeOSTool(
            id="online_platform",
            name="Online Platform",
            description="Connect to your CreativeOS account — coming soon.",
            icon="☁️",
            available=False,
            keywords=["online", "cloud", "sync", "account", "share"],
        ),
    ]


# ── Trained-model registry (locally fine-tuned models) ──────

def load_trained_models() -> List[Dict[str, Any]]:
    """Read the locally-trained models registry, returning [] if missing."""
    if not TRAINED_MODELS_REGISTRY.exists():
        return []
    try:
        with open(TRAINED_MODELS_REGISTRY, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[CreativeOS] Could not read trained models registry: {e}")
        return []


def save_trained_models(models: List[Dict[str, Any]]) -> bool:
    """Persist the registry."""
    try:
        TRAINED_MODELS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAINED_MODELS_REGISTRY, 'w', encoding='utf-8') as f:
            json.dump(models, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[CreativeOS] Could not save trained models registry: {e}")
        return False


def find_trained_model(name: str) -> Optional[Dict[str, Any]]:
    """Look up a trained-model registry entry by name."""
    for m in load_trained_models():
        if m.get("name") == name:
            return m
    return None


def delete_trained_model(name: str, *, remove_files: bool = True) -> bool:
    """Remove a trained model and propagate the deletion everywhere.

    Steps:
      1. Drop the entry from ``trained_models.json``.
      2. Optionally wipe the model directory on disk.
      3. Clear any per-task model setting (``model_for_rephrase``,
         ``model_for_general``, etc.) that still points at this name —
         the writing tool falls back through general → global cleanly,
         so a deleted task model just reverts to the default.
      4. Best-effort: invalidate any in-process AgentSuite's cached
         LLM clients so a stale handle to the now-deleted model isn't
         used on the next dispatch.

    Returns True if anything was removed from the registry.
    """
    import shutil

    models = load_trained_models()
    target = next((m for m in models if m.get("name") == name), None)
    if target is None:
        return False

    # 1. Drop from registry
    new_models = [m for m in models if m.get("name") != name]
    save_trained_models(new_models)

    # 2. Wipe the model directory (best-effort)
    if remove_files:
        path = target.get("path", "")
        if path:
            try:
                p = Path(path)
                if p.exists() and p.is_dir():
                    shutil.rmtree(p)
            except Exception as e:
                print(f"[CreativeOS] Could not remove model dir {path}: {e}")

    # 3. Reset any per-task settings pointing at this name. The
    # resolver in CreativeOSConfig.resolve_task_model already cascades
    # task → general → global, so clearing is the right behavior:
    # a deleted task model silently reverts to the default.
    cfg = get_creativeos_config()
    changed = False
    for key in TASK_MODEL_KEYS:
        if cfg.settings.get(key) == name:
            cfg.settings[key] = ""
            changed = True
    if changed:
        cfg.save()

    # 4. Invalidate any live AgentSuite caches. We don't hold a
    # reference to suites from here, so this is best-effort via the
    # gc — most apps have a single AgentSuite instance.
    try:
        import gc
        from src.ai.agent_suite import AgentSuite
        for obj in gc.get_objects():
            if isinstance(obj, AgentSuite):
                try:
                    obj.reset_task_llm_cache()
                except Exception:
                    pass
    except Exception:
        # Agent suite not loaded in this process — fine.
        pass

    # 5. Evict from the process-wide LoadedModelCache so the Model
    # Hub / Training Studio test runner / Writing Tool agent suite
    # can't return a tokenizer+model pair that no longer corresponds
    # to a registry entry. Without this, deleting a model via the
    # Training Studio's Manage Trained Models dialog leaves stale
    # weights in cache memory; subsequent test runs on OTHER models
    # can fail because the cache key for the deleted entry is still
    # present, occupying RAM budget that isn't actually free.
    try:
        from src.ai.model_cache import get_default_cache
        # Build a synthetic registry-style entry just to compute the
        # cache key. The cache uses (kind, id, path) as its key, so
        # we only need those three fields; the model class doesn't
        # matter here.
        from src.data.model_registry import KIND_TRAINED, ModelEntry
        synthetic = ModelEntry(
            id=name,
            kind=KIND_TRAINED,
            display_name=name,
            path=str(target.get("path") or ""),
        )
        get_default_cache().evict(synthetic)
    except Exception:
        # Cache module not loaded yet, or eviction raced with another
        # caller — either way the worst case is a stale entry that
        # the LRU policy will evict on its own.
        pass

    return True


def register_trained_model(name: str, path: str, base_model: str,
                           dataset_size: int, notes: str = "",
                           *,
                           intent: str = "",
                           genres: Optional[List[str]] = None,
                           tones: Optional[List[str]] = None,
                           continued_from: str = "") -> Dict[str, Any]:
    """Add a newly-trained model to the registry (or update by name).

    Args:
        intent: training intent ("voice", "rephrase", "plot",
            "worldbuilding", "character", "chat") so the test-step
            picker can group models by task. Empty string for legacy /
            unknown entries — they'll show under "Uncategorized".
        genres: canonical genre keys the model was trained on.
        tones: canonical tone keys (if the user opted in).
        continued_from: name of the prior trained model this one was
            fine-tuned on top of, or empty for from-base runs. Lets the
            UI surface a training lineage (Model B ← Model A ← base).
    """
    from datetime import datetime as _dt
    models = load_trained_models()
    entry = {
        "name": name,
        "path": str(path),
        "base_model": base_model,
        "dataset_size": dataset_size,
        "created_at": _dt.now().isoformat(timespec='seconds'),
        "notes": notes,
        "intent": intent or "",
        "genres": list(genres) if genres else [],
        "tones": list(tones) if tones else [],
        "continued_from": continued_from or "",
    }
    # Replace any existing entry with the same name
    models = [m for m in models if m.get("name") != name]
    models.append(entry)
    save_trained_models(models)
    return entry


# ── Config object ────────────────────────────────────────────

class CreativeOSConfig:
    """Loads / saves CreativeOS-level config and brokers it to tools."""

    def __init__(self):
        self.config_dir = CREATIVEOS_DIR
        self.config_file = CREATIVEOS_CONFIG_FILE
        self.settings: Dict[str, Any] = SHARED_LLM_DEFAULTS.copy()
        self._load()

    # ── persistence ──

    def _load(self) -> None:
        """Read the OS config from disk; migrate from the legacy Writing
        Tool config if no OS config exists yet so existing users don't
        have to reconfigure their LLM.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)

        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                merged = SHARED_LLM_DEFAULTS.copy()
                merged.update(loaded)
                self.settings = merged
                return
            except Exception as e:
                print(f"[CreativeOS] Could not read {self.config_file}: {e}")
                # fall through to defaults

        # First launch — try to inherit from the Writing Tool config
        if LEGACY_WRITER_CONFIG.exists():
            try:
                with open(LEGACY_WRITER_CONFIG, 'r', encoding='utf-8') as f:
                    legacy = json.load(f)
                migrated = SHARED_LLM_DEFAULTS.copy()
                # Only carry over keys we own
                for k in SHARED_LLM_DEFAULTS:
                    if k in legacy:
                        migrated[k] = legacy[k]
                self.settings = migrated
                self.save()
                print(f"[CreativeOS] Migrated LLM settings from "
                      f"{LEGACY_WRITER_CONFIG}")
            except Exception as e:
                print(f"[CreativeOS] Migration from legacy config failed: {e}")

    def save(self) -> bool:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[CreativeOS] Could not save config: {e}")
            return False

    # ── accessors ──

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save()

    def update(self, **kwargs) -> None:
        self.settings.update(kwargs)
        self.save()

    def has_llm_configured(self) -> bool:
        """Return True iff the user has set up *some* LLM access path."""
        if self.settings.get("disable_all_ai"):
            return False
        if any(self.settings.get(k) for k in (
                "claude_api_key", "chatgpt_api_key", "gemini_api_key")):
            return True
        if self.settings.get("enable_local_models") and \
                self.settings.get("local_model_id"):
            return True
        return False

    def shared_llm_settings(self) -> Dict[str, Any]:
        """Return a copy of the shared LLM defaults the OS holds."""
        return {k: self.settings.get(k, v)
                for k, v in SHARED_LLM_DEFAULTS.items()}

    def resolve_task_model(self, task: str) -> Dict[str, Any]:
        """Resolve which model the writing tool should use for a given task.

        Resolution chain (first match wins):
          1. The task-specific override, if set AND the trained model
             still exists on disk.
          2. The ``model_for_general`` override, same check.
          3. None — caller falls back to the global ``local_model_id``
             or its cloud provider.

        The on-disk check means that if the user deletes a trained model
        directory we silently fall back to general → global rather than
        crashing later when the path is loaded.

        Returns:
            ``{"trained_model": <entry|None>, "source": "task"|"general"|"fallback",
              "fallback_local_model_id": <global local_model_id>}``
        """
        key = f"model_for_{task}" if not task.startswith("model_for_") else task
        registry = load_trained_models()
        by_name = {e.get("name", ""): e for e in registry}

        def _pick(name: str):
            if not name:
                return None
            entry = by_name.get(name)
            if not entry:
                return None
            path = entry.get("path", "")
            if path and not Path(path).exists():
                # Model was registered but its directory has been removed.
                # Fall back gracefully — don't return a broken pointer.
                return None
            return entry

        source = "fallback"
        trained = None
        if key in TASK_MODEL_KEYS:
            trained = _pick((self.settings.get(key) or "").strip())
            if trained is not None:
                source = "task"
        if trained is None:
            trained = _pick((self.settings.get("model_for_general") or "").strip())
            if trained is not None and source == "fallback":
                source = "general"

        return {
            "trained_model": trained,
            "source": source,
            "fallback_local_model_id": self.settings.get("local_model_id", ""),
        }

    def task_local_model_id(self, task: str) -> str:
        """Return the local model id (or trained-model path) to use for ``task``.

        This is the single string the rest of the app needs to override
        the global ``local_model_id`` for one task. Returns the trained
        model's path if any (after the resolution chain in
        ``resolve_task_model``) — otherwise the global ``local_model_id``.
        """
        res = self.resolve_task_model(task)
        trained = res.get("trained_model")
        if trained and trained.get("path"):
            return trained["path"]
        return res.get("fallback_local_model_id", "") or ""

    def excluded_base_models(self) -> List[str]:
        """Return the HF ids the user has hidden from the training picker."""
        v = self.settings.get("excluded_base_models", [])
        return list(v) if isinstance(v, (list, tuple)) else []

    def set_excluded_base_models(self, ids: List[str]) -> None:
        """Persist the set of catalog ids the user wants to hide.

        Called by the "Manage built-in models" dialog after the user
        toggles checkboxes. Deduplicates and sorts for stability.
        """
        clean = sorted({str(i).strip() for i in ids if str(i).strip()})
        self.set("excluded_base_models", clean)

    def is_base_model_excluded(self, model_id: str) -> bool:
        """Convenience check used by pickers and the Model Builder Agent."""
        return model_id in self.excluded_base_models()

    def task_settings(self, task: str) -> Dict[str, Any]:
        """Return shared LLM settings overridden for one task.

        If the user picked a trained model for this task (or the general
        fallback), the returned dict has:
          * ``local_model_id`` — the trained model's path
          * ``enable_local_models`` — True
          * ``prefer_local_model`` — True (so callers that branch on
            this flag actually pick the override)
          * ``__task_model_source`` — "task" / "general" / "fallback"
            (a private hint so callers can log which override fired)

        When no trained model is picked, returns a copy of the shared
        defaults unchanged.
        """
        s = self.shared_llm_settings()
        res = self.resolve_task_model(task)
        s["__task_model_source"] = res.get("source", "fallback")
        trained = res.get("trained_model")
        if trained and trained.get("path"):
            s["local_model_id"] = trained["path"]
            s["enable_local_models"] = True
            s["prefer_local_model"] = True
            s["__trained_model_name"] = trained.get("name", "")
        return s


# ── Singleton ────────────────────────────────────────────────

_instance: Optional[CreativeOSConfig] = None


def get_creativeos_config() -> CreativeOSConfig:
    global _instance
    if _instance is None:
        _instance = CreativeOSConfig()
    return _instance


# ── Tool config helpers ──────────────────────────────────────

def apply_shared_llm_to_tool_settings(tool_settings: Dict[str, Any],
                                      shared: Optional[Dict[str, Any]] = None,
                                      override: bool = False) -> Dict[str, Any]:
    """Merge shared LLM defaults into a tool's settings dict.

    By default the tool's existing values WIN (the tool can deviate).
    Pass ``override=True`` to push the shared values down even if the
    tool already had its own — useful when the user explicitly clicks
    "apply OS settings to this tool" in the future.
    """
    if shared is None:
        shared = get_creativeos_config().shared_llm_settings()
    out = dict(tool_settings or {})
    for k, v in shared.items():
        if override or k not in out or out[k] in ("", None):
            out[k] = v
    return out
