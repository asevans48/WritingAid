"""MLX utilities for Apple Silicon optimized inference.

Also home to the shared local-model plumbing every loader uses:

  * ``ensure_torchvision_usable`` — a torchvision built for a different
    torch raises at import and takes transformers' Gemma 4 support with
    it; the tool marks it unavailable and carries on.
  * ``load_mlx_model`` — the one MLX load path (LLMClient, RephrasingAgent
    and the model cache all use it): one load at a time, no duplicate
    copies of a model already in memory, the old model released BEFORE a
    new one loads, ``mlx_vlm`` fallback, and a size check.
  * ``MLX_GENERATE_LOCK`` — MLX generation isn't thread-safe; concurrent
    callers (chat, critique, summariser) take turns.
"""

import gc
import importlib.metadata
import platform
import re
import sys
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def is_apple_silicon():
    """Check if running on Apple Silicon (M-series chips)."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def can_use_mlx():
    """Check if MLX is available and should be used."""
    if not is_apple_silicon():
        return False

    try:
        return True
    except ImportError:
        return False


def get_mlx_info():
    """Get MLX availability information."""
    info = {
        "platform": platform.system(),
        "machine": platform.machine(),
        "is_apple_silicon": is_apple_silicon(),
        "mlx_available": False,
        "mlx_version": None,
    }

    if can_use_mlx():
        try:
            info["mlx_available"] = True
            # MLX doesn't have __version__, just confirm it's importable
            info["mlx_version"] = "installed"
        except (ImportError, AttributeError):
            pass

    return info


def print_mlx_info():
    """Print MLX information for debugging."""
    info = get_mlx_info()

    print("=" * 60)
    print("MLX (Apple ML Framework) Information")
    print("=" * 60)
    print(f"Platform: {info['platform']}")
    print(f"Machine: {info['machine']}")
    print(f"Apple Silicon: {info['is_apple_silicon']}")
    print(f"MLX Available: {info['mlx_available']}")

    if info['mlx_available']:
        print(f"MLX Version: {info['mlx_version']}")
        print("\n✓ MLX is available - using optimized Apple Silicon inference")
    else:
        print("\n✗ MLX not available - falling back to PyTorch")

    print("=" * 60)


# ── torchvision guard ───────────────────────────────────────────────

_torchvision_checked = False


def ensure_torchvision_usable() -> bool:
    """Make sure a broken torchvision can't take transformers down.

    A torchvision built for another torch raises ``RuntimeError: operator
    torchvision::nms does not exist`` at import. Transformers then fails
    to expose Gemma 4 (and AutoProcessor). Text models don't need
    torchvision, so when it can't import it's marked absent for this
    process. Returns True if torchvision is usable.
    """
    global _torchvision_checked
    if _torchvision_checked:
        return sys.modules.get("torchvision", True) is not None
    _torchvision_checked = True
    try:
        import torchvision  # noqa: F401
        return True
    except ImportError:
        return False            # simply not installed — nothing to guard
    except Exception as e:
        for name in [m for m in sys.modules
                     if m == "torchvision" or m.startswith("torchvision.")]:
            del sys.modules[name]
        sys.modules["torchvision"] = None     # find_spec → None, import → ImportError
        print(f"[models] torchvision doesn't match this torch ({e}); continuing "
              f"without it. Text models are unaffected. To repair: "
              f"pip install --no-deps torchvision==<version matching your torch>")
        return False


def torch_torchvision_mismatch() -> bool:
    """Cheap (no imports) check: do installed torch / torchvision versions
    disagree? torchvision 0.N pairs with torch 2.(N-15)."""
    try:
        tv = importlib.metadata.version("torchvision").split(".")
        th = importlib.metadata.version("torch").split(".")
        return int(tv[1]) - 15 != int(th[1]) or th[0] != "2"
    except Exception:
        return False


def guard_torchvision_if_mismatched() -> None:
    """Mark a mismatched torchvision absent without importing it (importing
    it would load torch at startup, about 170 MB, for text-only models)."""
    if "torchvision" not in sys.modules and torch_torchvision_mismatch():
        sys.modules["torchvision"] = None
        print("[models] torchvision doesn't match this torch; continuing without "
              "it. Text models are unaffected. To repair: pip install --no-deps "
              "torchvision==<version matching your torch>")


# ── sizing ──────────────────────────────────────────────────────────

# GB of weights per billion parameters, by storage format.
_GB_PER_BILLION = {"4bit": 0.60, "8bit": 1.09, "6bit": 0.84, "bf16": 2.0, "fp16": 2.0}


def _cached_weights_gb(model_id: str) -> float:
    """Size of the weights if this model is already downloaded."""
    try:
        repo = "models--" + model_id.replace("/", "--")
        snapshots = Path.home() / ".cache" / "huggingface" / "hub" / repo / "snapshots"
        if not snapshots.is_dir():
            local = Path(model_id)
            files = list(local.glob("*.safetensors")) if local.is_dir() else []
        else:
            newest = max(snapshots.iterdir(), key=lambda p: p.stat().st_mtime)
            files = list(newest.glob("*.safetensors"))
        return sum(f.stat().st_size for f in files) / 1e9
    except Exception:
        return 0.0


def quantization_of(model_id: str) -> str:
    """"4bit" / "8bit" / … from a model id, or "" when unquantized."""
    m = re.search(r"(?<![a-z0-9])(\d{1,2})[-_]?bit\b", (model_id or "").lower())
    return f"{m.group(1)}bit" if m else ""


def parameter_billions(model_id: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b",
                  (model_id or "").lower().replace("-", " ").replace("_", " "))
    return float(m.group(1)) if m else 0.0


def estimate_weights_gb(model_id: str) -> float:
    """Weights size in GB — real size if downloaded, else from the name."""
    real = _cached_weights_gb(model_id)
    if real > 0:
        return round(real, 1)
    billions = parameter_billions(model_id)
    quant = quantization_of(model_id) or "bf16"
    return round(billions * _GB_PER_BILLION.get(quant, 2.0), 1)


def total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1e9 * 0.9313  # GiB, as Macs are sold
    except Exception:
        return 0.0


class ModelTooLargeError(RuntimeError):
    """The model's weights alone can't fit in this machine's memory."""


def allow_oversized_models() -> bool:
    try:
        from src.config.creativeos_config import get_creativeos_config
        return bool(get_creativeos_config().get("allow_oversized_local_models", False))
    except Exception:
        return False


def check_model_fits(model_id: str) -> str:
    """Raise ``ModelTooLargeError`` if the weights exceed physical memory
    (unless ``allow_oversized_local_models`` is set); return a warning
    when it fits but will be tight, else ""."""
    need, ram = estimate_weights_gb(model_id), total_ram_gb()
    if need <= 0 or ram <= 0:
        return ""
    if need >= ram:
        if not allow_oversized_models():
            alt = (re.sub(r"8[-_]?bit", "4bit", model_id, flags=re.I)
                   if quantization_of(model_id) == "8bit" else "")
            raise ModelTooLargeError(
                f"{model_id} needs about {need:.0f} GB for its weights, but this "
                f"computer has {ram:.0f} GB of memory."
                + (f" Use the 4-bit version instead ({alt})." if alt else
                   " Pick a smaller or more heavily quantized model.")
                + " To try anyway, set allow_oversized_local_models in the "
                  "CreativeOS settings.")
    if need >= ram * 0.75:
        return (f"{model_id} needs about {need:.0f} GB of this computer's {ram:.0f} GB "
                f"of memory; close other apps — it may be slow if macOS starts swapping.")
    return ""


# ── shared load + generate ──────────────────────────────────────────

# Serialises loads so two features can't load the same 20 GB twice.
_LOAD_LOCK = threading.RLock()
# MLX generation isn't thread-safe.
MLX_GENERATE_LOCK = threading.RLock()
# Models still alive anywhere in the process (model_id → (ref, tokenizer)).
_live_models: Dict[str, Tuple[Any, Any]] = {}
# Keep at most this share of RAM in model weights; Metal aborts the whole
# process, uncatchably, when a generation runs out of memory.
_RESIDENT_RAM_SHARE = 0.75
# Called with the id()s of models to drop, by everything that caches one.
_release_hooks: list = []


def register_model_release_hook(hook) -> None:
    """``hook(model_object_ids)`` must drop its references to those models."""
    if hook not in _release_hooks:
        _release_hooks.append(hook)


def release_mlx_memory() -> None:
    """Return freed model memory to the OS."""
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:
        pass


def _load_with_fallback(model_id: str) -> Tuple[Any, Any]:
    """(model, tokenizer) via mlx_lm, falling back to mlx_vlm for
    architectures or environments mlx_lm can't handle."""
    guard_torchvision_if_mismatched()
    ensure_torchvision_usable()
    try:
        from mlx_lm import load as mlx_load
    except ImportError:
        raise RuntimeError(
            f"MLX model {model_id!r} requested but the 'mlx-lm' package isn't "
            f"installed. Install with:\n  pip install mlx-lm\n"
            f"On Apple Silicon, also: pip install mlx-vlm")
    try:
        return mlx_load(model_id)
    except Exception as e:
        msg = str(e).lower()
        if "'list' object has no attribute 'keys'" in msg:
            raise RuntimeError(
                f"Failed to load '{model_id}': tokenizer config incompatibility.\n\n"
                f"Run: pip install --upgrade mlx mlx-lm mlx-vlm transformers")
        if not any(n in msg for n in ("model type", "not supported", "quant_model unknown",
                                      "quantization", "could not import module")):
            raise RuntimeError(f"Failed to load '{model_id}': {e}\n\n"
                               f"Try: pip install --upgrade mlx mlx-lm")
        print(f"[models] mlx_lm can't load {model_id} ({e}); trying mlx_vlm")
        try:
            from mlx_vlm import load as vlm_load
        except ImportError:
            raise RuntimeError(
                f"Model type not supported by mlx_lm. Install mlx_vlm:\n"
                f"  pip install --upgrade mlx mlx-lm mlx-vlm")
        return vlm_load(model_id)


def _reuse_loaded(model_id: str, use_slot: bool) -> Optional[Tuple[Any, Any]]:
    cache = get_mlx_cache()
    model, tokenizer = cache.get_model(model_id)
    if model is not None:
        return model, tokenizer
    live = _live_models.get(model_id)
    if live is None:
        return None
    alive = live[0]()
    if alive is None:
        del _live_models[model_id]
        return None
    if use_slot:
        cache.set_model(model_id, alive, live[1])
    return alive, live[1]


def _other_live_models(model_id: str) -> Dict[str, int]:
    """model id → object id of every other model still in memory."""
    others = {}
    for other, (ref, _tokenizer) in _live_models.items():
        alive = ref()
        if other != model_id and alive is not None:
            others[other] = id(alive)
    return others


def _resident_gb(model_id: str, others) -> float:
    return estimate_weights_gb(model_id) + sum(estimate_weights_gb(m) for m in others)


def _make_room_for(model_id: str) -> None:
    """Release other models when they and this one wouldn't fit together."""
    others = _other_live_models(model_id)
    ram = total_ram_gb()
    if not others or _resident_gb(model_id, others) <= ram * _RESIDENT_RAM_SHARE:
        return
    names = ", ".join(sorted(others))
    print(f"[models] releasing {names} to make room for {model_id}")
    cache = get_mlx_cache()
    victims = set(others.values())
    if id(cache._model) in victims:
        cache.unload()
    for hook in list(_release_hooks):
        try:
            hook(victims)
        except Exception as e:
            print(f"[models] release hook failed: {e}")
    release_mlx_memory()
    stuck = _other_live_models(model_id)
    if stuck and _resident_gb(model_id, stuck) >= ram * 0.9 and not allow_oversized_models():
        raise ModelTooLargeError(
            f"Can't load {model_id}: {', '.join(sorted(stuck))} is still in use and "
            f"both won't fit in {ram:.0f} GB of memory. Wait for it to finish, then try again.")


def load_mlx_model(model_id: str, *, use_slot: bool = True) -> Tuple[Any, Any]:
    """Return ``(model, tokenizer)``, loading only if nothing holds it.

    ``use_slot=True`` makes it the shared current model: a different model
    occupying the slot is released *before* loading, so switching between
    20B+ models never needs both in memory at once. Other holders are
    asked to let go when the models wouldn't fit together.
    """
    with _LOAD_LOCK:
        loaded = _reuse_loaded(model_id, use_slot)
    if loaded is not None:
        return loaded
    # Lock order is generate → load. Waiting here also keeps weights from
    # being released under a generation that is still running.
    with MLX_GENERATE_LOCK, _LOAD_LOCK:
        loaded = _reuse_loaded(model_id, use_slot)
        if loaded is not None:
            return loaded
        cache = get_mlx_cache()
        warning = check_model_fits(model_id)
        if warning:
            print(f"[models] {warning}")
        if use_slot and cache.is_loaded():
            cache.unload()              # free the old model first
        _make_room_for(model_id)
        model, tokenizer = _load_with_fallback(model_id)
        try:
            _live_models[model_id] = (weakref.ref(model), tokenizer)
        except TypeError:
            pass
        if use_slot:
            cache.set_model(model_id, model, tokenizer)
        return model, tokenizer


class MLXModelCache:
    """Singleton cache for MLX models."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._tokenizer = None
            cls._instance._model_id = None
        return cls._instance

    def get_model(self, model_id: str):
        """Get cached MLX model if it matches the requested model_id."""
        if self._model is not None and self._model_id == model_id:
            return self._model, self._tokenizer
        return None, None

    def set_model(self, model_id: str, model, tokenizer):
        """Cache a loaded MLX model."""
        # Unload previous model if different
        if self._model is not None and self._model_id != model_id:
            self._unload_model()

        self._model = model
        self._tokenizer = tokenizer
        self._model_id = model_id
        print(f"MLX model cached: {model_id}")

    def _unload_model(self):
        """Unload the current MLX model from memory."""
        if self._model is not None:
            print(f"Unloading previous MLX model: {self._model_id}")
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            self._model_id = None
            release_mlx_memory()

    def unload(self):
        """Explicitly drop the current model and free its memory."""
        self._unload_model()

    def is_loaded(self, model_id: str = None) -> bool:
        """Check if a model is loaded."""
        if model_id is None:
            return self._model is not None
        return self._model is not None and self._model_id == model_id


# Global MLX model cache
_mlx_cache = MLXModelCache()


def get_mlx_cache() -> MLXModelCache:
    """Get the global MLX model cache instance."""
    return _mlx_cache
