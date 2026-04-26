"""Convert a trained PyTorch LoRA adapter to MLX format.

The user trains a LoRA adapter against a PyTorch base — either
locally on their Mac (capped at ~9B-class) or remotely on Modal
(any size). The result is a HuggingFace-format adapter directory
that PyTorch / PEFT can load. To use it in MLX-native pipelines on
Apple Silicon (faster on-device inference, lower RAM footprint),
the adapter has to be:

  1. **Fused** into the base model — LoRA's low-rank update is
     baked back into the dense weight matrices, producing a
     standalone HF model with no adapter dependency.
  2. **Converted** to MLX format — typically with 4-bit
     quantization for the size win.

Both steps are mlx_lm responsibilities. We shell out to the
``mlx_lm.fuse`` and ``mlx_lm.convert`` modules rather than
importing them directly, because their module-level state is heavy
(loads MLX runtime which only initializes cleanly on Apple Silicon)
and we want this module to import cleanly even on Linux/Windows
where the conversion is impossible — so the UI can detect that
fact and disable the button without crashing.

**Non-destructive guarantee** — the original PyTorch adapter is
*never* touched. Conversion produces a new directory beside it
(e.g. ``my-voice-v1-mlx/``); if MLX conversion fails halfway,
the original is intact and the user can retry or fall back.

**What lands on disk** (when conversion succeeds):

  ``<adapter_dir>-fused/``   — fused HF model, intermediate
  ``<adapter_dir>-mlx/``     — final MLX-quantized package

The intermediate fused dir is large (full base + adapter weights
merged) but worth keeping by default: it's a useful non-quantized
fallback if the user later wants to re-quantize at a different
bit-width. We expose ``keep_fused`` so callers can opt out.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional


@dataclass
class ConversionStatus:
    """What ``can_convert_to_mlx`` returns. Tells the UI whether to
    show the convert button and what to put in its tooltip if not."""
    available: bool
    apple_silicon: bool
    mlx_lm_installed: bool
    error: str = ""

    def help_text(self) -> str:
        """Why isn't conversion available right now?"""
        if not self.apple_silicon:
            return (
                "MLX conversion only works on Apple Silicon (M1/M2/M3/"
                "M4/M5). MLX is Apple's framework — Linux/Windows can "
                "still TRAIN the adapter but can't convert it to "
                "MLX-native format.")
        if not self.mlx_lm_installed:
            return ("Install mlx-lm first:\n  pip install mlx-lm\n"
                    "(Apple Silicon only.) After install, conversion "
                    "becomes available without restarting the studio.")
        if self.error:
            return self.error
        return "MLX conversion is available."


def can_convert_to_mlx() -> ConversionStatus:
    """Detect whether the current machine can run MLX conversion.

    Two requirements:
      1. Apple Silicon (Darwin + arm64). MLX won't initialize on
         Linux, Windows, or x86_64 Macs.
      2. ``mlx_lm`` package importable. We do the import inside a
         subprocess so a failed import doesn't taint our own
         process — some MLX import failures (CUDA conflicts, broken
         install) leak globals.
    """
    is_darwin = platform.system() == "Darwin"
    is_arm = platform.machine() in ("arm64", "aarch64")
    apple_silicon = is_darwin and is_arm
    if not apple_silicon:
        return ConversionStatus(
            available=False,
            apple_silicon=False,
            mlx_lm_installed=False)

    # Cheap probe: try ``python -c "import mlx_lm"`` in a subprocess.
    # On a working install this is ~200ms; on a broken install it
    # raises but doesn't crash us.
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import mlx_lm"],
            capture_output=True, timeout=10)
        installed = result.returncode == 0
        err = (result.stderr.decode("utf-8", errors="ignore").strip()
               if not installed else "")
    except Exception as e:
        installed = False
        err = str(e)

    return ConversionStatus(
        available=installed,
        apple_silicon=True,
        mlx_lm_installed=installed,
        error=err)


# ── Conversion ────────────────────────────────────────────


@dataclass
class ConversionResult:
    """What the conversion produced. The UI registers each path that
    was created with the model registry so they're individually
    pickable later."""
    fused_path: Optional[Path]   # may be None if keep_fused=False
    mlx_path: Path
    base_model: str


def convert_adapter_to_mlx(
        adapter_dir: Path,
        *,
        base_model: str,
        output_root: Optional[Path] = None,
        quantize_bits: int = 4,
        keep_fused: bool = True,
        on_log: Optional[Callable[[str], None]] = None,
) -> ConversionResult:
    """Fuse the LoRA adapter into the base, then convert to MLX.

    Args:
        adapter_dir: Path to the trained-adapter directory
            (contains ``adapter_config.json`` + ``adapter_model.safetensors``).
        base_model: HF repo id of the base, e.g. ``google/gemma-3-2b``.
            mlx_lm.fuse needs this so it can load the base weights to
            merge the adapter into. Required — adapters don't store
            the base ref themselves.
        output_root: Parent dir for the produced ``-fused/`` and
            ``-mlx/`` directories. Defaults to adapter_dir's parent
            (the trained-models registry root).
        quantize_bits: 4 (default), 8, or 0 (no quantization). 4 is
            the sweet spot for most consumer workflows.
        keep_fused: Save the intermediate non-quantized fused model
            next to the MLX output. Disk cost: roughly the size of
            the base in fp16. Default True so the user has a
            non-quantized fallback in case the MLX conversion fails
            or they want to re-quantize at a different bit-width
            later.
        on_log: optional log sink for progress lines.

    Returns the paths the conversion wrote.
    Raises ``RuntimeError`` if mlx_lm isn't installed, the platform
    isn't Apple Silicon, or either conversion step fails. The
    original adapter is never touched.
    """
    log = on_log or (lambda _msg: None)
    status = can_convert_to_mlx()
    if not status.available:
        raise RuntimeError(status.help_text())

    adapter_dir = Path(adapter_dir).resolve()
    if not adapter_dir.exists():
        raise RuntimeError(f"Adapter dir not found: {adapter_dir}")
    if not (adapter_dir / "adapter_config.json").exists():
        raise RuntimeError(
            f"{adapter_dir} doesn't look like a LoRA adapter — "
            f"adapter_config.json is missing.")
    if not base_model:
        raise RuntimeError(
            "base_model is required (the HF repo id of the base "
            "model the adapter was trained against).")

    output_root = Path(output_root or adapter_dir.parent).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = adapter_dir.name
    fused_path = output_root / f"{name}-fused"
    mlx_path = output_root / f"{name}-mlx"

    # ── Step 1: Fuse ──────────────────────────────────
    # Run as a subprocess so any MLX-side memory allocations get
    # cleaned up cleanly when the process exits, regardless of
    # what happened during conversion.
    log(f"Fusing adapter into base ({base_model})…")
    fuse_cmd = [
        sys.executable, "-m", "mlx_lm.fuse",
        "--model", base_model,
        "--adapter-path", str(adapter_dir),
        "--save-path", str(fused_path),
    ]
    log(f"  $ {' '.join(fuse_cmd)}")
    res = subprocess.run(fuse_cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"mlx_lm.fuse failed (exit={res.returncode}):\n"
            f"{res.stderr.decode('utf-8', errors='ignore')}")
    if not fused_path.exists() or not any(fused_path.iterdir()):
        raise RuntimeError(
            f"mlx_lm.fuse exited 0 but produced no files at {fused_path}")
    log(f"  Fused → {fused_path}")

    # ── Step 2: Convert + quantize ────────────────────
    log(f"Converting fused model to MLX format "
        f"({'q' + str(quantize_bits) if quantize_bits else 'fp16'})…")
    convert_cmd = [
        sys.executable, "-m", "mlx_lm.convert",
        "--hf-path", str(fused_path),
        "--mlx-path", str(mlx_path),
    ]
    if quantize_bits in (4, 8):
        convert_cmd += ["-q", "--q-bits", str(quantize_bits)]
    log(f"  $ {' '.join(convert_cmd)}")
    res = subprocess.run(convert_cmd, capture_output=True)
    if res.returncode != 0:
        # Conversion failed — clean up the partial mlx_path so the
        # user doesn't end up with a broken half-converted dir, but
        # leave fused_path alone so they have a fallback. Then
        # re-raise.
        if mlx_path.exists():
            try:
                shutil.rmtree(mlx_path)
            except Exception:
                pass
        raise RuntimeError(
            f"mlx_lm.convert failed (exit={res.returncode}):\n"
            f"{res.stderr.decode('utf-8', errors='ignore')}")
    if not mlx_path.exists() or not any(mlx_path.iterdir()):
        raise RuntimeError(
            f"mlx_lm.convert exited 0 but produced no files at {mlx_path}")
    log(f"  Converted → {mlx_path}")

    # Optionally drop the intermediate fused dir to save disk.
    if not keep_fused:
        try:
            shutil.rmtree(fused_path)
            fused_path = None
            log(f"  Removed intermediate fused dir (keep_fused=False)")
        except Exception as e:
            log(f"  Could not remove fused dir: {e}")

    return ConversionResult(
        fused_path=fused_path if keep_fused else None,
        mlx_path=mlx_path,
        base_model=base_model,
    )
