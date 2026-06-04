"""Pre-flight RAM / VRAM checks + eviction of competing models.

When the user fires ``Generate clip`` against a heavy backend (WAN
2.1 needs ~14 GB VRAM), we run two passes:

  1. ``snapshot()`` — measure free RAM + VRAM on the live system
  2. ``check(requirements)`` — compare to the backend's declared
     ``MemoryRequirements`` and report any shortfall

If the check fails, the studio offers to ``free_other_models()`` —
unloads any local LLM clients still holding weights, clears the
shared HF model cache, and asks PyTorch / MLX to release their
allocator pools. Then we re-check; only if the budget now fits do
we actually call ``backend.generate()``.

The eviction routine reuses the existing app hooks
(``unload_all_local_clients``, ``ModelCache.clear``) rather than
duplicating them — keeps a single source of truth for what's
loadable.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.video_studio.backends.base import MemoryRequirements


@dataclass
class ResourceSnapshot:
    """A point-in-time read of system memory + accelerator memory."""
    ram_total_mb: int
    ram_available_mb: int
    vram_total_mb: int
    vram_available_mb: int
    # "cuda" / "mps" / "cpu". "cpu" means no accelerator detected;
    # vram_* fields are 0 in that case and we only check RAM.
    accelerator: str
    # Per-device readout for multi-GPU machines (rare in practice
    # for end users but useful for debugging). For CUDA, indexed by
    # device id. For MPS / CPU, a single entry.
    per_device_vram_mb: Dict[int, Tuple[int, int]] = field(
        default_factory=dict)


@dataclass
class ResourceCheckResult:
    """The verdict for one (backend, snapshot) pair."""
    satisfied: bool
    requested: MemoryRequirements
    snapshot: ResourceSnapshot
    ram_shortfall_mb: int = 0
    vram_shortfall_mb: int = 0
    explanation: str = ""


def snapshot() -> ResourceSnapshot:
    """Read the live RAM + VRAM state. Cheap (psutil + torch query)."""
    ram_total, ram_avail = _read_ram_mb()
    accel = _detect_accelerator()
    vram_total, vram_avail, per_device = _read_vram_mb(accel)
    return ResourceSnapshot(
        ram_total_mb=ram_total,
        ram_available_mb=ram_avail,
        vram_total_mb=vram_total,
        vram_available_mb=vram_avail,
        accelerator=accel,
        per_device_vram_mb=per_device,
    )


def check(
    requirements: MemoryRequirements,
    snap: Optional[ResourceSnapshot] = None,
) -> ResourceCheckResult:
    """Compare requirements to the live snapshot."""
    s = snap or snapshot()
    ram_short = max(0, requirements.ram_mb - s.ram_available_mb)
    # CPU-only machines can't satisfy a VRAM ask of any size — the
    # check reports the shortfall as if the GPU had 0 VRAM. Backends
    # that support CPU should report vram_mb=0.
    if requirements.vram_mb > 0:
        vram_short = max(0, requirements.vram_mb - s.vram_available_mb)
    else:
        vram_short = 0
    if ram_short == 0 and vram_short == 0:
        return ResourceCheckResult(
            satisfied=True, requested=requirements, snapshot=s,
            explanation=(
                f"Available: {s.ram_available_mb} MB RAM, "
                f"{s.vram_available_mb} MB {s.accelerator.upper()} "
                f"VRAM."))
    parts: List[str] = []
    if ram_short:
        parts.append(
            f"need {requirements.ram_mb} MB RAM, only "
            f"{s.ram_available_mb} MB available "
            f"(short {ram_short} MB)")
    if vram_short:
        accel_label = (
            s.accelerator.upper() if s.accelerator != "cpu"
            else "no GPU")
        parts.append(
            f"need {requirements.vram_mb} MB VRAM, only "
            f"{s.vram_available_mb} MB available on {accel_label} "
            f"(short {vram_short} MB)")
    explanation = " · ".join(parts)
    if requirements.notes:
        explanation += f" — {requirements.notes}"
    return ResourceCheckResult(
        satisfied=False, requested=requirements, snapshot=s,
        ram_shortfall_mb=ram_short,
        vram_shortfall_mb=vram_short,
        explanation=explanation,
    )


@dataclass
class FreeReport:
    """What freeing actually did. Used to confirm to the user that
    eviction happened before the (potentially long) re-check."""
    llm_clients_unloaded: int = 0
    model_cache_cleared_count: int = 0
    cuda_cache_emptied: bool = False
    mps_cache_emptied: bool = False
    errors: List[str] = field(default_factory=list)


def free_other_models() -> FreeReport:
    """Evict every loaded local model and clear accelerator caches.

    Calls the existing app hooks so this stays a single source of
    truth:
      * ``unload_all_local_clients`` from ``llm_client`` —  drops
        local HF / MLX LLM weights
      * ``ModelCache.clear`` from ``model_cache`` — clears the
        shared model cache used by other agents

    Returns a report describing what changed. Safe to call when
    nothing is loaded — counts come back as zero.
    """
    report = FreeReport()
    # LLM clients holding local model weights.
    try:
        from src.ai.llm_client import unload_all_local_clients
        report.llm_clients_unloaded = unload_all_local_clients(
            clear_cuda=False, clear_mlx=False)
    except Exception as e:
        report.errors.append(f"unload_all_local_clients: {e}")
    # Shared HF model cache (managed by ``get_default_cache``).
    try:
        from src.ai.model_cache import get_default_cache
        cache = get_default_cache()
        before = len(cache.loaded_summary())
        cache.clear()
        report.model_cache_cleared_count = before
    except Exception as e:
        # Cache may not be initialized yet; failures are non-fatal —
        # we still try the GPU cache clears below.
        report.errors.append(f"model_cache.clear: {e}")
    # PyTorch CUDA cache.
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            report.cuda_cache_emptied = True
    except Exception as e:
        report.errors.append(f"cuda.empty_cache: {e}")
    # MPS cache (Apple Silicon).
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            if hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
                report.mps_cache_emptied = True
    except Exception as e:
        report.errors.append(f"mps.empty_cache: {e}")
    # MLX cache.
    try:
        import mlx.core as mx
        if hasattr(mx, "clear_cache"):
            mx.clear_cache()
        elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
            mx.metal.clear_cache()
    except Exception:
        # MLX may not be installed; that's fine on non-Apple machines.
        pass
    gc.collect()
    return report


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------
def _read_ram_mb() -> Tuple[int, int]:
    """Return (total_mb, available_mb). Falls back to (0, 0) when
    psutil isn't importable."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return (int(vm.total // (1024 * 1024)),
                int(vm.available // (1024 * 1024)))
    except Exception:
        return (0, 0)


def _detect_accelerator() -> str:
    """Pick the most powerful accelerator we can see. Order: CUDA,
    MPS, CPU. Avoids importing torch when neither is needed."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _read_vram_mb(
    accelerator: str,
) -> Tuple[int, int, Dict[int, Tuple[int, int]]]:
    """Return (total_mb, available_mb, per_device_mb)."""
    if accelerator == "cuda":
        return _read_cuda_vram_mb()
    if accelerator == "mps":
        return _read_mps_vram_mb()
    return (0, 0, {})


def _read_cuda_vram_mb() -> Tuple[int, int, Dict[int, Tuple[int, int]]]:
    try:
        import torch
        per_device: Dict[int, Tuple[int, int]] = {}
        total_total = 0
        total_avail = 0
        for i in range(torch.cuda.device_count()):
            free, total = torch.cuda.mem_get_info(i)
            free_mb = int(free // (1024 * 1024))
            total_mb = int(total // (1024 * 1024))
            per_device[i] = (free_mb, total_mb)
            total_total += total_mb
            total_avail += free_mb
        return total_total, total_avail, per_device
    except Exception:
        return (0, 0, {})


def _read_mps_vram_mb() -> Tuple[int, int, Dict[int, Tuple[int, int]]]:
    """MPS doesn't expose a free-vs-used split as cleanly as CUDA.

    Apple Silicon shares system memory between CPU and GPU
    (unified memory), so we report the system RAM as VRAM total
    and subtract what torch.mps has *already allocated* to give a
    "headroom" estimate. It's imperfect — the OS may evict caches —
    but it's the right shape for a pre-flight check.
    """
    try:
        import torch
        if not (hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()):
            return (0, 0, {})
        import psutil
        total_bytes = psutil.virtual_memory().total
        total_mb = int(total_bytes // (1024 * 1024))
        allocated_mb = 0
        try:
            allocated_mb = int(
                torch.mps.current_allocated_memory() // (1024 * 1024))
        except Exception:
            pass
        # Headroom = system available memory minus already-allocated
        # MPS heap. Caps at total so very fresh runs don't report a
        # negative or larger-than-system value.
        free_mb = max(0, min(
            total_mb - allocated_mb,
            int(psutil.virtual_memory().available // (1024 * 1024))))
        return (total_mb, free_mb, {0: (free_mb, total_mb)})
    except Exception:
        return (0, 0, {})
