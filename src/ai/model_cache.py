"""LRU cache for loaded local models.

Loading a 4B-7B model takes 10-60 seconds and 8-14 GB of RAM. Doing
that on every inference call is unworkable. Doing it once and never
unloading is also unworkable: a user with 32 GB of RAM who loads
three 7B models OOMs.

This module sits between the registry (which knows what's available)
and the inference callers (Training Studio test runner, Writing Tool
agent suite, the new Model Hub). Callers ask for a model by id; the
cache loads it on demand, marks it as most-recently-used, and evicts
older models when the cache is full.

**Cache policy** — two bounds, whichever is hit first:

  * ``max_models`` — hard limit on simultaneous loaded models. Default
    2 — even on a 64 GB machine, three models in RAM at once is
    diminishing returns; you typically want a single primary plus
    one swap-in for comparisons.
  * ``max_ram_gb`` — soft limit measured against the *estimated* RAM
    a model occupies (see ``_estimated_ram_gb``). Default: 60% of
    available RAM at process start. We over-estimate rather than
    under-estimate so eviction kicks in before the OS pages or kills
    us.

Both are tunable via the constructor and via the OS-level
``creativeos_config`` if a future setting wants to expose them.

**Thread safety** — a single Lock guards the cache so the writing
tool's worker thread and the Hub's UI thread don't double-load the
same model. Inference calls don't hold the lock.

**Loading paths** — picked from the registry entry's metadata:
  * Trained adapter (``is_adapter=True``): load base via
    ``AutoModelForCausalLM.from_pretrained`` then attach via
    ``PeftModel.from_pretrained``.
  * Trained full model: ``AutoModelForCausalLM.from_pretrained(path)``.
  * Pretrained (built-in or pinned): straight HF id load. Honours
    ``trust_remote_code`` from the registry metadata.

The cache hands callers ``(tokenizer, model)``. It does not generate
text — that's the caller's job — so the cache stays format-agnostic.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class _CacheEntry:
    """Internal — what the cache stores per loaded model."""
    tokenizer: Any
    model: Any
    loaded_at: float
    last_used: float
    estimated_ram_gb: float
    entry_id: str
    kind: str


def _available_ram_gb() -> float:
    """Best-effort available RAM in GB. Returns 0 if psutil is missing."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        return 0.0


def _estimated_ram_gb(registry_entry) -> float:
    """How much RAM loading this model is expected to take.

    Trained adapters: base model footprint + adapter overhead (~5%).
    Pretrained: base model footprint at bf16 (~2 bytes/param, plus
    20% for KV cache and activations).

    The estimate is intentionally conservative (over-estimating) so
    the cache evicts before we hit OS-level memory pressure.
    """
    size_b = float(getattr(registry_entry, "size_b", 0.0) or 0.0)
    if size_b <= 0:
        # Unknown size — assume mid-band so we don't accidentally
        # let many large models stack.
        size_b = 4.0
    bf16_bytes_per_param = 2.0
    overhead = 1.2  # KV cache + activations
    base_gb = size_b * 1e9 * bf16_bytes_per_param * overhead / (1024 ** 3)
    if getattr(registry_entry, "is_adapter", False):
        # Adapter weights are small (~100 MB for r=8) but we still
        # have to load the base — same total RAM footprint.
        base_gb *= 1.05
    return round(base_gb, 1)


class LoadedModelCache:
    """Thread-safe LRU cache of loaded ``(tokenizer, model)`` pairs."""

    def __init__(self, *,
                 max_models: int = 2,
                 max_ram_gb: Optional[float] = None,
                 on_log: Optional[Callable[[str], None]] = None):
        self._max_models = max(1, int(max_models))
        if max_ram_gb is None:
            avail = _available_ram_gb()
            self._max_ram_gb = round(avail * 0.6, 1) if avail > 0 else 16.0
        else:
            self._max_ram_gb = float(max_ram_gb)
        self._cache: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._lock = threading.RLock()
        self._log = on_log or (lambda _msg: None)

    # ── Public API ────────────────────────────────────────

    def get(self, registry_entry) -> Tuple[Any, Any]:
        """Return ``(tokenizer, model)`` for the registry entry.

        Loads on cache miss, marks as MRU on hit. Evicts LRU entries
        if either ``max_models`` or ``max_ram_gb`` would be exceeded
        by the load. Raises whatever the underlying loader raises if
        the load fails — the cache itself never swallows errors.
        """
        cache_key = self._key(registry_entry)
        with self._lock:
            existing = self._cache.get(cache_key)
            if existing is not None:
                # Hit — bump recency.
                existing.last_used = time.time()
                self._cache.move_to_end(cache_key)
                self._log(
                    f"[model-cache] hit: {registry_entry.display_name}")
                return existing.tokenizer, existing.model

        # Miss — load outside the lock. Loading is slow (10-60s); we
        # don't want to block other cache reads while it runs. The
        # tradeoff: two parallel callers asking for the SAME model
        # could both load it. That's wasteful but not incorrect — the
        # second one will overwrite the first in the cache.
        est_gb = _estimated_ram_gb(registry_entry)
        self._log(
            f"[model-cache] miss: {registry_entry.display_name}  "
            f"loading (est ~{est_gb}GB)…")
        tokenizer, model = self._load(registry_entry)

        with self._lock:
            self._evict_if_needed(incoming_gb=est_gb)
            entry = _CacheEntry(
                tokenizer=tokenizer,
                model=model,
                loaded_at=time.time(),
                last_used=time.time(),
                estimated_ram_gb=est_gb,
                entry_id=registry_entry.id,
                kind=registry_entry.kind,
            )
            self._cache[cache_key] = entry
            self._log(
                f"[model-cache] loaded {registry_entry.display_name}  "
                f"({len(self._cache)} models in cache, "
                f"~{self.current_ram_gb():.1f}GB)")
            return tokenizer, model

    def evict(self, registry_entry) -> bool:
        """Force-evict a specific model from the cache (e.g. before
        deleting it from disk). Returns True if anything was removed."""
        with self._lock:
            return self._evict_one(self._key(registry_entry))

    def clear(self) -> None:
        """Drop every loaded model. Used when the user changes
        critical settings (e.g. switching from MLX → PyTorch backend)
        or when the launcher quits."""
        with self._lock:
            for key in list(self._cache.keys()):
                self._evict_one(key)

    def loaded_summary(self) -> List[Dict[str, Any]]:
        """Snapshot of what's currently loaded — for the Hub UI."""
        with self._lock:
            return [{
                "id": e.entry_id,
                "kind": e.kind,
                "loaded_at": e.loaded_at,
                "last_used": e.last_used,
                "ram_gb": e.estimated_ram_gb,
            } for e in self._cache.values()]

    def current_ram_gb(self) -> float:
        with self._lock:
            return sum(e.estimated_ram_gb for e in self._cache.values())

    def is_loaded(self, registry_entry) -> bool:
        with self._lock:
            return self._key(registry_entry) in self._cache

    # ── Internals ─────────────────────────────────────────

    @staticmethod
    def _key(registry_entry) -> str:
        # Two trained models with the same name in different on-disk
        # locations would collide on id alone — include the path.
        return f"{registry_entry.kind}:{registry_entry.id}:{registry_entry.path}"

    def _evict_if_needed(self, *, incoming_gb: float) -> None:
        """Evict the LRU entry until both bounds are satisfied.

        Lock must be held.
        """
        # Hard count limit.
        while len(self._cache) >= self._max_models and self._cache:
            oldest_key = next(iter(self._cache))
            self._evict_one(oldest_key)
        # Soft RAM limit.
        while (self.current_ram_gb_locked() + incoming_gb
               > self._max_ram_gb and self._cache):
            oldest_key = next(iter(self._cache))
            self._evict_one(oldest_key)

    def current_ram_gb_locked(self) -> float:
        return sum(e.estimated_ram_gb for e in self._cache.values())

    def _evict_one(self, key: str) -> bool:
        entry = self._cache.pop(key, None)
        if entry is None:
            return False
        # Best-effort cleanup — we want torch / MLX to release the
        # GPU memory, not just drop the Python references. The
        # collector handles regular RAM; for CUDA/MPS we explicitly
        # empty the cache.
        self._log(
            f"[model-cache] evicting {entry.entry_id} "
            f"(~{entry.estimated_ram_gb}GB freed)")
        try:
            del entry.model
            del entry.tokenizer
        except Exception:
            pass
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif (hasattr(torch.backends, "mps")
                  and torch.backends.mps.is_available()):
                if hasattr(torch.mps, "empty_cache"):
                    torch.mps.empty_cache()
        except Exception:
            pass
        return True

    def _load(self, registry_entry) -> Tuple[Any, Any]:
        """Resolve the right loader path for this kind of registry entry.

        Three loader paths:
          1. **MLX format** (Apple Silicon quantised weights, e.g.
             ``mlx-community/gemma-4-26B-it-4bit``) — load via
             ``mlx_lm.load`` with ``mlx_vlm.load`` as a fallback for
             newer architectures (gemma4, etc.) that mlx_lm hasn't
             caught up with. Transformers can't read MLX-quantised
             weights and produces a "quant_model unknown" error if
             we feed an MLX id to ``AutoModelForCausalLM``.
          2. **Trained LoRA adapter** — load base via transformers
             then attach the adapter via PEFT.
          3. **Plain pretrained / trained-full** — straight
             ``AutoModelForCausalLM.from_pretrained``.
        """
        path = registry_entry.path
        base = registry_entry.base_model
        framework = (registry_entry.framework or "").lower()
        trust_remote_code = bool(
            registry_entry.metadata.get("trust_remote_code", False))

        # ── MLX path ──────────────────────────────────────
        if framework == "mlx" or _looks_like_mlx_id(
                path or base or registry_entry.id):
            return _load_mlx(
                path or base or registry_entry.id,
                trust_remote_code=trust_remote_code)

        # ── Transformers / PEFT paths ─────────────────────
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch

        # Pick a sensible dtype. bf16 for accelerators that support it
        # (CUDA, MPS); fp32 on plain CPU. Dtype matters for the RAM
        # estimate to be accurate.
        if (torch.cuda.is_available()
                or (hasattr(torch.backends, "mps")
                    and torch.backends.mps.is_available())):
            dtype = torch.bfloat16
        else:
            dtype = torch.float32

        # Trained adapter — load base then attach.
        if registry_entry.is_adapter and path:
            from peft import PeftModel
            if not base:
                raise ValueError(
                    f"Trained adapter {registry_entry.id!r} has no "
                    f"base_model recorded in the registry; cannot load.")
            tokenizer = AutoTokenizer.from_pretrained(
                path,
                trust_remote_code=trust_remote_code)
            base_model = AutoModelForCausalLM.from_pretrained(
                base,
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=trust_remote_code)
            model = PeftModel.from_pretrained(base_model, path)
            model.eval()
            return tokenizer, model

        # Trained full model OR pretrained (built-in or pinned).
        load_id = path if path else base or registry_entry.id
        tokenizer = AutoTokenizer.from_pretrained(
            load_id,
            trust_remote_code=trust_remote_code)
        model = AutoModelForCausalLM.from_pretrained(
            load_id,
            torch_dtype=dtype,
            device_map="auto",
            trust_remote_code=trust_remote_code)
        model.eval()
        return tokenizer, model


# ── Module-level singleton ────────────────────────────────
# Process-wide cache so the writing tool, training studio, and model
# hub all share the same loaded models. Lazy-init so importing this
# module is cheap.

_DEFAULT_CACHE: Optional[LoadedModelCache] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_cache() -> LoadedModelCache:
    """Return the process-wide default cache instance."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = LoadedModelCache()
    return _DEFAULT_CACHE


def reset_default_cache() -> None:
    """Drop and rebuild the default cache. Used by tests; also
    callable from the Hub's "Unload All" action."""
    global _DEFAULT_CACHE
    with _DEFAULT_LOCK:
        if _DEFAULT_CACHE is not None:
            _DEFAULT_CACHE.clear()
        _DEFAULT_CACHE = None


# ── Continuation helpers ─────────────────────────────────
#
# Models routinely run out of ``max_new_tokens`` mid-sentence — the
# user sees a truncated reply and has to ask "continue?" themselves.
# These helpers automate that: if the generation didn't emit EOS and
# doesn't end on sentence-final punctuation, we feed the partial
# response back as context and generate more, repeating until either
# EOS, a natural stop, or a hard ceiling.

_SENTENCE_END_CHARS = '.!?"\'"”’)。！？'


# ── MLX detection / loader / generator ─────────────────────
#
# MLX-format models live alongside HuggingFace ids but use Apple's
# native quantisation (mlx_lm) which transformers can't decode. The
# tell-tales are either a leading ``mlx-community/`` namespace or
# a ``-mlx-`` segment in the id; we detect both, plus the explicit
# ``framework="mlx"`` tag the registry sets for built-in MLX
# catalog entries.

def _looks_like_mlx_id(model_id: str) -> bool:
    """Heuristic: does this HF id point at an MLX-quantised repo?"""
    if not model_id:
        return False
    lower = model_id.lower()
    if lower.startswith("mlx-community/"):
        return True
    if "-mlx-" in lower or lower.endswith("-mlx"):
        return True
    return False


def _load_mlx(model_id: str, *, trust_remote_code: bool = False):
    """Load an MLX model + tokenizer with mlx_vlm fallback.

    The fallback is required for newer architectures (gemma4, llama4)
    that mlx_lm hasn't shipped support for yet; mlx_vlm covers them.
    Returns ``(tokenizer, model)`` to match the transformers shape so
    the cache's storage layer treats every entry uniformly.
    """
    try:
        from mlx_lm import load as mlx_load
    except ImportError:
        raise RuntimeError(
            f"MLX model {model_id!r} requested but the 'mlx-lm' "
            f"package isn't installed. Install with:\n"
            f"  pip install mlx-lm\n"
            f"On Apple Silicon, also: pip install mlx-vlm")
    try:
        model, tokenizer = mlx_load(model_id)
    except Exception as e:
        msg = str(e).lower()
        # mlx_lm raises various error shapes when it doesn't know an
        # arch — "model type", "not supported", "quant_model unknown",
        # etc. All map to "try mlx_vlm instead".
        if any(needle in msg for needle in (
                "model type", "not supported",
                "quant_model unknown", "quantization")):
            try:
                from mlx_vlm import load as vlm_load
            except ImportError:
                raise RuntimeError(
                    f"MLX model {model_id!r} uses an architecture "
                    f"mlx_lm doesn't recognise yet ({e}). Install "
                    f"mlx-vlm for fallback support:\n"
                    f"  pip install --upgrade mlx mlx-lm mlx-vlm")
            model, tokenizer = vlm_load(model_id)
        else:
            raise RuntimeError(
                f"MLX load failed for {model_id!r}: {e}\n"
                f"Try: pip install --upgrade mlx mlx-lm")
    return tokenizer, model


def is_mlx_model(model) -> bool:
    """True if a model object came back from the MLX loaders."""
    cls = type(model).__module__
    return cls.startswith("mlx") or "mlx_" in cls


def mlx_generate(tokenizer, model, prompt: str, *,
                 max_tokens: int = 300,
                 temperature: float = 0.7,
                 top_p: float = 0.9,
                 ) -> str:
    """Generate text from an MLX-loaded model. Mirrors LLMClient's
    ``_generate_mlx_local`` but takes prompt as a plain string so the
    caller has full control over chat-template formatting."""
    try:
        from mlx_lm import generate as _mlx_generate
        from mlx_lm.sample_utils import make_sampler
        sampler = make_sampler(temp=temperature, top_p=top_p)
        text = _mlx_generate(
            model, tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False)
    except Exception:
        # mlx_vlm path — different signature.
        from mlx_vlm import generate as _vlm_generate
        text = _vlm_generate(
            model, tokenizer, prompt,
            max_tokens=max_tokens,
            temp=temperature,
            verbose=False)
    if not isinstance(text, str):
        text = getattr(text, "text", "") or str(text)
    return text


def mlx_generate_with_continuation(tokenizer, model, prompt: str, *,
                                    max_new_tokens: int = 300,
                                    max_continuations: int = 3,
                                    max_total_new_tokens: int = 1500,
                                    temperature: float = 0.7,
                                    top_p: float = 0.9,
                                    on_progress=None) -> str:
    """MLX equivalent of ``generate_with_continuation``.

    Same stop conditions: EOS-equivalent (no new content), sentence-
    final punctuation with budget to spare, max_continuations, hard
    ceiling on cumulative tokens. Each round feeds the previous
    response back as part of the prompt so the model continues its
    own thread.
    """
    full_response = ""
    cumulative_tokens = 0
    # MLX tokenizers behave like HF ones for chat templates — let the
    # caller pass an already-templated prompt and we just append the
    # running response between rounds.
    for round_idx in range(max_continuations + 1):
        budget = max(1, max_total_new_tokens - cumulative_tokens)
        chunk_max = min(max_new_tokens, budget)
        chunk = mlx_generate(
            tokenizer, model,
            prompt + full_response,
            max_tokens=chunk_max,
            temperature=temperature, top_p=top_p)
        chunk = (chunk or "").rstrip()
        if not chunk:
            break
        full_response = (full_response + chunk).strip()
        # Estimate token count (no direct API on MLX side without
        # re-tokenising; word-count is good enough for cap accounting).
        cumulative_tokens += max(1, len(chunk) // 4)
        if on_progress is not None:
            on_progress(round_idx + 1, cumulative_tokens)

        # Stop conditions. We don't have explicit EOS here (mlx_lm
        # already stops on EOS internally), but if the last chunk was
        # well under its budget we can assume EOS fired.
        if len(chunk) < chunk_max * 2:  # chars are ~2-4 per token
            if _looks_complete(full_response):
                break
        if cumulative_tokens >= max_total_new_tokens:
            break
    return full_response


def _looks_complete(text: str) -> bool:
    """Heuristic: does this output end on a stable, sentence-final note?

    Used as the "no need to continue" signal when the model didn't
    explicitly emit an EOS token but cleanly finished a sentence.
    """
    stripped = (text or "").rstrip()
    if not stripped:
        return False
    return stripped[-1] in _SENTENCE_END_CHARS


def generate_with_continuation(tokenizer, model, prompt_input_ids, *,
                                max_new_tokens: int = 300,
                                max_continuations: int = 3,
                                max_total_new_tokens: int = 1500,
                                gen_kwargs: Optional[dict] = None,
                                on_progress: Optional[Callable[[int, int], None]] = None,
                                ) -> str:
    """Generate, auto-continuing if the model was cut off.

    Args:
        tokenizer: HF tokenizer used to encode/decode and check EOS.
        model: HF causal LM with ``.generate()``.
        prompt_input_ids: dict from ``tokenizer(prompt, return_tensors='pt').to(device)``.
        max_new_tokens: tokens per generation pass.
        max_continuations: how many extra passes are allowed AFTER the
            first one. 0 = no continuation, behave like a normal call.
        max_total_new_tokens: hard ceiling across all passes; we stop
            once cumulative new tokens exceed this even if the model
            wants to continue.
        gen_kwargs: anything else to pass through to ``generate``
            (temperature, top_p, repetition_penalty, …).
        on_progress: ``(round_idx, tokens_so_far)`` called after each
            pass — for UI status updates.

    Returns the decoded response (everything generated AFTER the
    initial prompt, with special tokens skipped).

    Stop conditions, in order of priority:
      1. EOS token emitted in the latest pass.
      2. Decoded text ends on sentence-final punctuation AND we've
         run at least one full pass (avoids stopping too early on
         "Mr." or "etc." mid-sentence in the very first chunk).
      3. ``max_continuations`` exhausted.
      4. ``max_total_new_tokens`` exceeded.
      5. The latest pass produced zero or whitespace-only new tokens.
    """
    import torch

    gen_kwargs = dict(gen_kwargs or {})
    gen_kwargs.setdefault(
        "pad_token_id",
        tokenizer.pad_token_id or tokenizer.eos_token_id)
    gen_kwargs.setdefault("eos_token_id", tokenizer.eos_token_id)

    # Track the running prompt tensor; each round we feed back the
    # full sequence (prompt + everything generated so far) so the
    # model continues from its own output.
    current_ids = prompt_input_ids["input_ids"]
    attention_mask = prompt_input_ids.get("attention_mask")
    device = current_ids.device
    initial_prompt_len = current_ids.shape[1]
    cumulative_new_tokens = 0

    full_decoded = ""
    for round_idx in range(max_continuations + 1):
        # Build the kwargs for this pass.
        pass_kwargs = dict(gen_kwargs)
        pass_kwargs["max_new_tokens"] = min(
            max_new_tokens,
            max(1, max_total_new_tokens - cumulative_new_tokens))

        with torch.no_grad():
            inputs = {"input_ids": current_ids}
            if attention_mask is not None:
                inputs["attention_mask"] = attention_mask
            out = model.generate(**inputs, **pass_kwargs)

        # Tokens added in this pass = everything beyond the input we fed.
        new_segment = out[0][current_ids.shape[1]:]
        n_new = int(new_segment.shape[0])
        if n_new == 0:
            break
        cumulative_new_tokens += n_new

        # Decode all new tokens since the ORIGINAL prompt ended.
        full_decoded = tokenizer.decode(
            out[0][initial_prompt_len:],
            skip_special_tokens=True).strip()

        if on_progress is not None:
            on_progress(round_idx + 1, cumulative_new_tokens)

        # Stop condition 1: EOS in this segment.
        eos_id = tokenizer.eos_token_id
        if eos_id is not None and eos_id in new_segment.tolist():
            break

        # Stop condition 2: text ends on sentence-final punctuation.
        # Skip on the very first round if it's exactly at max_new_tokens
        # (that strongly suggests we ran out of budget mid-thought).
        likely_truncated = n_new >= pass_kwargs["max_new_tokens"]
        if not likely_truncated and _looks_complete(full_decoded):
            break

        # Stop condition 4: hit hard ceiling.
        if cumulative_new_tokens >= max_total_new_tokens:
            break

        # Set up next round: continue from what the model just produced.
        current_ids = out
        if attention_mask is not None:
            extension = torch.ones(
                (1, n_new), dtype=attention_mask.dtype, device=device)
            attention_mask = torch.cat([attention_mask, extension], dim=1)

    return full_decoded
