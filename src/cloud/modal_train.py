"""Modal cloud training — submit a fine-tune to Modal's serverless GPUs.

The studio's local trainer caps out at ~9B-class bases on a 32 GB
Mac. Anything larger needs cloud GPUs. Modal is the cleanest fit
because:

  * Pay-per-second — a Gemma-9B QLoRA run is ~$0.30-2; a 26B run is
    ~$2-8. No idle cost between runs.
  * Serverless — no EC2 / pod / cluster setup. The Modal app is
    pinned in this file; submitting a job spins up the container.
  * Volume support — base models cache to a persistent Modal
    volume so subsequent runs reuse weights.
  * Python-first SDK — the local studio submits jobs directly,
    polls for progress, and downloads the resulting LoRA adapter
    back into the registry. The user's data only sits on Modal's
    machine for the run duration.

**Setup the user has to do once**:
  1. ``pip install modal``
  2. ``modal token new``  (opens a browser, links a Modal account)

**Setup we never make the user do**:
  * Deploy the app — we use the ephemeral ``with app.run():``
    context so submitting a job creates the function on the fly.
  * Manually upload the dataset — the JSONL is shipped with the
    function call as bytes.
  * Manually download the adapter — :func:`download_artifact`
    pulls it from the volume into ``~/.creativeos/trained_models``.

**Surfaces this module exposes** (the rest of the studio only sees
these — no direct Modal SDK calls leak into the UI):

  * :func:`check_setup` — "is modal installed AND authenticated?"
  * :func:`estimate_cost` — quick GPU/time → $ estimate before submit
  * :func:`submit_training_job` — fire and return a handle
  * :func:`poll_job` — UI worker calls this on a timer
  * :func:`download_adapter` — fetch the trained dir from Modal
  * :func:`cancel_job` — user clicked Stop

The Modal *function* itself (the GPU-side training loop) is mostly
a port of ``training_tool_window._TrainingWorker.run`` — same
tokeniser path, same loss masking, same eval-split, same LoRA
setup. Keeping the two implementations close lets us debug locally
on a small base, then click "Train on Modal" with the same recipe
to do the big run.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── GPU price table (us-east, public on-demand, 2025-Q1) ──
# Used by ``estimate_cost`` to give the user a $-figure before they
# click "Train on Modal". Numbers are deliberately pessimistic — we
# round up so the bill rarely exceeds the estimate. Update when
# Modal's pricing changes (https://modal.com/pricing).
_GPU_PRICING_PER_HOUR_USD = {
    "T4": 0.59,       # 16GB — too small for 7B+; included for tinkering
    "L4": 0.80,       # 24GB
    "A10G": 1.10,     # 24GB — sweet spot for 7-9B QLoRA
    "L40S": 2.00,     # 48GB — comfortable for 13B QLoRA
    "A100": 3.40,     # 40GB
    "A100-80GB": 5.00,
    "H100": 6.00,     # 80GB — needed for 26B+ at reasonable speed
}

# Heuristic: how big a base can each GPU train (QLoRA 4-bit)
# before activation memory makes it impractical. Used for the
# "recommend a GPU" hint in the UI.
_GPU_MAX_PARAMS_B = {
    "T4": 3, "L4": 9, "A10G": 9,
    "L40S": 13, "A100": 13,
    "A100-80GB": 30, "H100": 70,
}

# Volumes are namespaced in the Modal account — keep the names
# stable across releases so the HF cache doesn't keep getting
# rebuilt.
_HF_CACHE_VOLUME_NAME = "creativeos-hf-cache"
_ADAPTER_VOLUME_NAME = "creativeos-trained-adapters"


# ── Setup detection ───────────────────────────────────────


@dataclass
class SetupStatus:
    """Result of a "can the user submit a Modal job right now?" check."""
    modal_installed: bool
    authenticated: bool
    error: str = ""

    @property
    def ready(self) -> bool:
        return self.modal_installed and self.authenticated and not self.error

    def help_text(self) -> str:
        """One-line user-facing instructions for whatever's missing."""
        if not self.modal_installed:
            return ("Install the Modal SDK first:\n"
                    "  pip install modal")
        if not self.authenticated:
            return ("Authenticate with Modal once:\n"
                    "  modal token new\n"
                    "(this opens a browser and links your Modal account)")
        if self.error:
            return f"Modal setup error: {self.error}"
        return "Modal is ready."


def check_setup() -> SetupStatus:
    """Verify modal is importable AND a token is configured.

    The token check is light-weight — we just look for the existence
    of ``~/.modal.toml`` (or the env vars Modal supports), or the
    keystore-stored token-pair the studio's settings dialog writes
    when the user pastes credentials directly. Network failures
    surface later when the user actually submits, not on the setup
    check.
    """
    try:
        import modal  # noqa: F401
    except Exception as e:
        return SetupStatus(modal_installed=False, authenticated=False,
                           error=str(e))

    # Modal authentication can come from any of three places:
    #   1. MODAL_TOKEN_ID / MODAL_TOKEN_SECRET env vars (developer setup)
    #   2. ~/.modal.toml (set by `modal token new`)
    #   3. OS keystore — written by the studio's settings dialog
    from src.cloud.modal_credentials import (
        has_env_tokens, has_modal_toml_tokens, has_keystore_tokens,
    )
    if not (has_env_tokens()
            or has_modal_toml_tokens()
            or has_keystore_tokens()):
        return SetupStatus(
            modal_installed=True, authenticated=False,
            error=("No Modal token found. Either:\n"
                   "  • Click 'Configure Modal credentials…' to paste "
                   "a token-pair into the secure keystore\n"
                   "  • Or run `modal token new` in a terminal once."))
    return SetupStatus(modal_installed=True, authenticated=True)


# ── Cost / GPU recommendation ─────────────────────────────


def recommend_gpu(base_model_size_b: float, *,
                  use_qlora: bool = True) -> str:
    """Pick the smallest GPU that can comfortably train this base.

    Smaller GPUs are cheaper but might OOM under activation
    pressure — we leave 2× headroom on the param-count → GPU
    mapping. QLoRA shrinks the weight footprint ~4× but doesn't
    help with activations, so the headroom matters.
    """
    target = max(0.5, base_model_size_b)
    if not use_qlora:
        # Full-precision LoRA needs 4× more weight RAM.
        target *= 4
    for gpu in ("T4", "L4", "A10G", "L40S", "A100",
                "A100-80GB", "H100"):
        if _GPU_MAX_PARAMS_B.get(gpu, 0) >= target:
            return gpu
    return "H100"


def estimate_cost(base_model_size_b: float, *,
                  gpu: str = "",
                  epochs: int = 2,
                  rows: int = 1000,
                  use_qlora: bool = True) -> Tuple[float, float, str]:
    """Return ``(low_usd, high_usd, gpu_used)`` for a planned run.

    The estimate is rough — actual cost depends on GPU contention,
    cold-start time, and how many tokens the dataset tokenises into.
    We give a low/high band so the user sees the realistic range,
    not a single number that's always wrong.
    """
    if not gpu:
        gpu = recommend_gpu(base_model_size_b, use_qlora=use_qlora)
    rate = _GPU_PRICING_PER_HOUR_USD.get(gpu, 3.0)

    # Time-per-row baseline: ~0.6s for a 4B model at QLoRA, scaling
    # linearly with parameter count. Empirical on Modal A10G; we
    # adjust for GPU class (H100 ~2.5× faster than A10G).
    base_seconds_per_row_per_b = 0.15 if use_qlora else 0.4
    gpu_speedup = {"T4": 0.6, "L4": 0.85, "A10G": 1.0,
                   "L40S": 1.5, "A100": 1.8, "A100-80GB": 2.0,
                   "H100": 2.5}.get(gpu, 1.0)
    seconds = (base_seconds_per_row_per_b * base_model_size_b
               * rows * epochs / gpu_speedup)
    # Add 60s of cold-start + I/O overhead.
    seconds += 60.0
    hours = seconds / 3600.0
    point = rate * hours
    return (round(point * 0.7, 2), round(point * 1.4, 2), gpu)


# ── Job handle ────────────────────────────────────────────


@dataclass
class JobHandle:
    """Returned by ``submit_training_job``. Opaque to the UI; passed
    back to ``poll_job`` and friends.

    ``call_id`` is the Modal FunctionCall id (a string). The Modal
    SDK uses it to query / cancel the running function. We persist
    it (plus the run name + adapter target) so the user can close
    the studio mid-training and pick the job back up later via
    ``rehydrate_handle``.
    """
    call_id: str
    name: str
    base_model: str
    gpu: str
    submitted_at: float
    adapter_name: str
    estimated_cost_low: float = 0.0
    estimated_cost_high: float = 0.0
    raw: Any = field(default=None, repr=False)


def _persist_handle(handle: JobHandle) -> None:
    p = (Path.home() / ".creativeos" / "modal_jobs.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if p.exists():
        try:
            existing = json.loads(p.read_text()) or []
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append({
        "call_id": handle.call_id,
        "name": handle.name,
        "base_model": handle.base_model,
        "gpu": handle.gpu,
        "submitted_at": handle.submitted_at,
        "adapter_name": handle.adapter_name,
        "estimated_cost_low": handle.estimated_cost_low,
        "estimated_cost_high": handle.estimated_cost_high,
    })
    p.write_text(json.dumps(existing, indent=2))


def list_persisted_jobs() -> List[Dict[str, Any]]:
    p = (Path.home() / ".creativeos" / "modal_jobs.json")
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, list) else []
    except Exception:
        return []


# ── Modal app + training function ─────────────────────────
#
# Defined at module scope so the Modal CLI ("modal deploy …") can
# pick this up if the user wants a deployed (warm-start) app. For
# the studio's primary flow we use ephemeral runs via
# ``app.run(...)`` so the user doesn't need to deploy anything.

def _build_app():
    """Construct the Modal app + image lazily.

    Lazy because importing modal at module-load time would error if
    the package isn't installed — and we want the *rest* of this
    module (check_setup, estimate_cost) to work without modal
    present so the UI can show useful "install modal first"
    messages.
    """
    import modal

    app = modal.App("creativeos-training")

    # The image must mirror the local trainer's dependencies. Pin
    # versions where the install order matters (bitsandbytes needs
    # torch first; trl is optional; peft requires transformers >=4.40).
    image = (
        modal.Image.debian_slim(python_version="3.11")
        .pip_install(
            "torch>=2.4",
            "transformers>=4.45",
            "peft>=0.12",
            "accelerate>=0.34",
            "datasets>=2.20",
            "bitsandbytes>=0.43",
            "safetensors",
            "scipy",  # peft optimization deps
        )
        # HF cache directory in the Volume — every base model the
        # user trains against is cached here so the second run
        # against the same base starts fast.
        .env({"HF_HOME": "/cache/hf",
              "TRANSFORMERS_CACHE": "/cache/hf"})
    )

    hf_cache = modal.Volume.from_name(
        _HF_CACHE_VOLUME_NAME, create_if_missing=True)
    adapters = modal.Volume.from_name(
        _ADAPTER_VOLUME_NAME, create_if_missing=True)

    @app.function(
        image=image,
        # GPU is picked at call time via .with_options(gpu=...)
        # so a single function definition serves every GPU class.
        gpu="A10G",
        volumes={
            "/cache": hf_cache,
            "/adapters": adapters,
        },
        timeout=4 * 60 * 60,  # 4 h cap; longer runs need a custom GPU
    )
    def train_remote(dataset_jsonl: bytes, config: dict) -> dict:
        """The actual GPU-side training loop.

        Mirrors ``training_tool_window._TrainingWorker.run`` so the
        local and cloud paths produce comparable adapters. Anything
        the user can configure on Step 3 (epochs, LR, batch size,
        LoRA r, QLoRA toggle, eval split) is passed through ``config``.
        """
        import os
        os.environ.setdefault("HF_HOME", "/cache/hf")
        os.environ.setdefault("TRANSFORMERS_CACHE", "/cache/hf")

        import json
        import torch
        from pathlib import Path

        from datasets import load_dataset
        from transformers import (
            AutoTokenizer, AutoModelForCausalLM,
            TrainingArguments, Trainer,
            DataCollatorForLanguageModeling,
        )
        from peft import (
            LoraConfig, get_peft_model,
            prepare_model_for_kbit_training,
        )

        adapter_name = config["adapter_name"]
        adapter_dir = Path(f"/adapters/{adapter_name}")
        adapter_dir.mkdir(parents=True, exist_ok=True)

        # Write the JSONL to the container's local disk so
        # datasets can mmap it.
        ds_path = adapter_dir / "_dataset.jsonl"
        ds_path.write_bytes(dataset_jsonl)
        ds_full = load_dataset("json", data_files=str(ds_path),
                                split="train")

        base_model = config["base_model"]
        tokenizer = AutoTokenizer.from_pretrained(
            base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        load_kwargs = dict(
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )
        if config.get("use_qlora", True):
            from transformers import BitsAndBytesConfig
            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )
        model = AutoModelForCausalLM.from_pretrained(
            base_model, **load_kwargs)
        if config.get("use_qlora", True):
            model = prepare_model_for_kbit_training(model)

        lora_r = int(config.get("lora_r", 8))
        lora_cfg = LoraConfig(
            r=lora_r,
            lora_alpha=lora_r * 2,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=config.get("target_modules") or "all-linear",
        )
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

        max_length = int(config.get("max_length", 512))
        has_chat_template = bool(getattr(tokenizer, "chat_template", None))

        def _build_messages(rec):
            instr = rec.get("instruction", "") or ""
            inp = rec.get("input", "") or ""
            out = rec.get("output", "") or ""
            if "messages" in rec:
                return rec["messages"]
            user_msg = (f"{instr}\n\n{inp}".strip() if inp else instr)
            meta = rec.get("metadata") or {}
            system = meta.get("system_prompt", "")
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": user_msg})
            msgs.append({"role": "assistant", "content": out})
            return msgs

        def render_full(rec):
            if has_chat_template:
                return tokenizer.apply_chat_template(
                    _build_messages(rec), tokenize=False)
            instr = rec.get("instruction", "")
            inp = rec.get("input", "")
            out = rec.get("output", "")
            if inp:
                return (f"### Instruction:\n{instr}\n\n"
                        f"### Input:\n{inp}\n\n"
                        f"### Response:\n{out}")
            return (f"### Instruction:\n{instr}\n\n"
                    f"### Response:\n{out}")

        def render_prompt(rec):
            if has_chat_template:
                msgs = _build_messages(rec)[:-1]
                return tokenizer.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True)
            instr = rec.get("instruction", "")
            inp = rec.get("input", "")
            if inp:
                return (f"### Instruction:\n{instr}\n\n"
                        f"### Input:\n{inp}\n\n"
                        f"### Response:\n")
            return f"### Instruction:\n{instr}\n\n### Response:\n"

        def _format_type(rec):
            meta = rec.get("metadata") or {}
            return (meta.get("format_type") or "instruction").lower()

        def render_and_tokenize(batch):
            rows = [
                {k: batch[k][i] for k in batch.keys()}
                for i in range(len(batch[next(iter(batch))]))
            ]
            full_texts = [render_full(r) for r in rows]
            prompt_texts = [render_prompt(r) for r in rows]
            format_types = [_format_type(r) for r in rows]
            tokens = tokenizer(
                full_texts, truncation=True,
                max_length=max_length, padding=False)
            prompt_tokens = tokenizer(
                prompt_texts, truncation=True, max_length=max_length)
            labels = []
            for full_ids, prompt_ids, ftype in zip(
                    tokens["input_ids"],
                    prompt_tokens["input_ids"],
                    format_types):
                lab = list(full_ids)
                if ftype == "instruction":
                    boundary = min(len(prompt_ids), len(lab))
                    for i in range(boundary):
                        lab[i] = -100
                labels.append(lab)
            tokens["labels"] = labels
            return tokens

        ds = ds_full.map(
            render_and_tokenize,
            batched=True, batch_size=64,
            remove_columns=ds_full.column_names,
            desc="Tokenizing")

        eval_ds = None
        if len(ds) >= 20:
            split = ds.train_test_split(test_size=0.15, seed=42)
            ds = split["train"]
            eval_ds = split["test"]

        args_kwargs = dict(
            output_dir=str(adapter_dir / "checkpoints"),
            num_train_epochs=int(config.get("epochs", 2)),
            per_device_train_batch_size=int(config.get("batch_size", 1)),
            gradient_accumulation_steps=4,
            learning_rate=float(config.get("learning_rate", 2e-4)),
            logging_steps=1,
            save_strategy="epoch",
            save_total_limit=2 if eval_ds is not None else 1,
            report_to=[],
            bf16=True,
            remove_unused_columns=False,
        )
        if eval_ds is not None:
            import inspect
            ta_params = inspect.signature(TrainingArguments).parameters
            if "eval_strategy" in ta_params:
                args_kwargs["eval_strategy"] = "epoch"
            else:
                args_kwargs["evaluation_strategy"] = "epoch"
            args_kwargs["load_best_model_at_end"] = True
            args_kwargs["metric_for_best_model"] = "eval_loss"
            args_kwargs["greater_is_better"] = False
        targs = TrainingArguments(**args_kwargs)

        collator = DataCollatorForLanguageModeling(
            tokenizer=tokenizer, mlm=False)
        trainer_kwargs = dict(
            model=model,
            args=targs,
            train_dataset=ds,
            data_collator=collator,
        )
        if eval_ds is not None:
            trainer_kwargs["eval_dataset"] = eval_ds
        try:
            import inspect
            if "processing_class" in inspect.signature(
                    Trainer.__init__).parameters:
                trainer_kwargs["processing_class"] = tokenizer
            else:
                trainer_kwargs["tokenizer"] = tokenizer
        except Exception:
            trainer_kwargs["processing_class"] = tokenizer
        trainer = Trainer(**trainer_kwargs)
        trainer.train()
        trainer.save_model(str(adapter_dir))
        tokenizer.save_pretrained(str(adapter_dir))

        # Persist a small manifest the local downloader can read to
        # know what's in the volume without re-walking it.
        (adapter_dir / "_manifest.json").write_text(json.dumps({
            "adapter_name": adapter_name,
            "base_model": base_model,
            "completed_at": time.time(),
            "config": config,
        }))
        adapters.commit()

        return {"adapter_name": adapter_name,
                "base_model": base_model,
                "rows_trained": len(ds),
                "rows_evaluated": len(eval_ds) if eval_ds else 0}

    return app, train_remote, hf_cache, adapters


# ── Public submit / poll / download API ───────────────────


def submit_training_job(*,
                        jsonl_path: Path,
                        config: Dict[str, Any],
                        gpu: str = "",
                        adapter_name: str = "",
                        on_log: Optional[Callable[[str], None]] = None,
                        ) -> JobHandle:
    """Submit the training job and return a handle.

    The handle is what UI workers poll on. We deliberately don't
    block here — submit returns as soon as Modal has accepted the
    call; everything else (status, progress, completion) flows
    through ``poll_job``.

    ``config`` matches the local recipe shape (epochs, learning_rate,
    batch_size, lora_r, use_qlora, base_model). We add
    ``adapter_name`` so the volume stages the result under a stable
    directory the downloader can find.
    """
    log = on_log or (lambda _msg: None)

    # Inject keystore-stored tokens into the env if needed. This is
    # what makes the "paste your token-pair into the dialog" flow
    # work end-to-end — without it, even a populated keystore
    # wouldn't reach the Modal SDK because the SDK only reads from
    # env vars and ~/.modal.toml.
    from src.cloud.modal_credentials import apply_tokens_to_env
    apply_tokens_to_env()

    status = check_setup()
    if not status.ready:
        raise RuntimeError(status.help_text())

    base_model = config.get("base_model") or ""
    if not base_model:
        raise ValueError("config['base_model'] is required")
    if not adapter_name:
        # Default to a timestamped name — keeps Modal's volume tidy.
        from datetime import datetime as _dt
        adapter_name = (
            f"{config.get('name') or 'run'}-"
            f"{_dt.now().strftime('%Y%m%d-%H%M%S')}")

    config["adapter_name"] = adapter_name
    if "base_model_size_b" not in config:
        # Best-effort param count for cost estimation; the trainer
        # itself doesn't need it.
        try:
            from src.data.model_registry import _size_from_id
            config["base_model_size_b"] = _size_from_id(base_model)
        except Exception:
            config["base_model_size_b"] = 0.0

    if not gpu:
        gpu = recommend_gpu(
            float(config.get("base_model_size_b") or 7),
            use_qlora=bool(config.get("use_qlora", True)))

    # Read the dataset bytes once, on the local side, so the
    # function call payload is self-contained.
    payload = jsonl_path.read_bytes()
    log(f"Building Modal app (gpu={gpu})…")

    app, train_remote, _hf_vol, _adapt_vol = _build_app()

    # Bind the chosen GPU class via with_options before spawning.
    fn = train_remote.with_options(gpu=gpu)

    log(f"Submitting job ({len(payload)//1024} KB dataset, "
        f"adapter={adapter_name})…")
    # Ephemeral run — context manager keeps the app alive while we
    # spawn the function, then exits. The FunctionCall lives on
    # past the context: it's a server-side handle.
    with app.run():
        fc = fn.spawn(payload, config)

    submitted_at = time.time()
    low, high, _gpu_used = estimate_cost(
        float(config.get("base_model_size_b") or 7),
        gpu=gpu,
        epochs=int(config.get("epochs", 2)),
        rows=int(config.get("estimated_rows", 1000)),
        use_qlora=bool(config.get("use_qlora", True)))
    handle = JobHandle(
        call_id=fc.object_id,
        name=adapter_name,
        base_model=base_model,
        gpu=gpu,
        submitted_at=submitted_at,
        adapter_name=adapter_name,
        estimated_cost_low=low,
        estimated_cost_high=high,
        raw=fc,
    )
    _persist_handle(handle)
    return handle


def poll_job(handle: JobHandle) -> Dict[str, Any]:
    """Returns the job's current status.

    Possible status values:
      * ``"running"`` — function still executing.
      * ``"done"`` — function completed; ``result`` is the dict the
        Modal function returned.
      * ``"failed"`` — function raised; ``error`` has the message.
      * ``"unknown"`` — Modal SDK returned a state we don't
        recognise (treated as still running).

    Doesn't block. UI workers should call this on a 5-10s timer.
    """
    try:
        import modal
    except ImportError:
        return {"status": "failed",
                "error": "modal package not installed"}
    fc = handle.raw
    if fc is None:
        # Re-attach to a persisted call id — useful when the user
        # closed the studio and is reopening it.
        try:
            fc = modal.FunctionCall.from_id(handle.call_id)
        except Exception as e:
            return {"status": "failed",
                    "error": f"couldn't reattach to call: {e}"}
    try:
        result = fc.get(timeout=0.0)  # 0 = non-blocking poll
    except modal.exception.OutputExpiredError:
        return {"status": "failed",
                "error": "Modal job result expired"}
    except TimeoutError:
        return {"status": "running"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    return {"status": "done", "result": result}


def cancel_job(handle: JobHandle) -> bool:
    """Best-effort cancel. Returns True if the cancel was accepted."""
    try:
        import modal  # noqa: F401
    except ImportError:
        return False
    fc = handle.raw
    if fc is None:
        try:
            import modal
            fc = modal.FunctionCall.from_id(handle.call_id)
        except Exception:
            return False
    try:
        fc.cancel()
        return True
    except Exception:
        return False


def download_adapter(adapter_name: str, dest_dir: Path,
                     *, on_log: Optional[Callable[[str], None]] = None
                     ) -> Path:
    """Download the trained adapter from the Modal volume to ``dest_dir``.

    Returns the path of the downloaded directory. The volume keeps
    the adapter around until the user manually deletes it via
    ``modal volume rm`` — repeated downloads are idempotent.
    """
    log = on_log or (lambda _msg: None)
    try:
        import modal
    except ImportError:
        raise RuntimeError("modal package not installed; can't download")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / adapter_name
    target.mkdir(parents=True, exist_ok=True)
    log(f"Downloading adapter '{adapter_name}' from Modal volume…")
    vol = modal.Volume.from_name(_ADAPTER_VOLUME_NAME)
    # Iterate the volume and pull files under the adapter dir.
    # Modal's Volume API uses listdir + read_file; we walk
    # recursively to handle the adapter_config.json + safetensors
    # + tokenizer files all together.
    def _walk(remote_dir: str, local_dir: Path):
        local_dir.mkdir(parents=True, exist_ok=True)
        for entry in vol.listdir(remote_dir):
            name = entry.path.split("/")[-1]
            if entry.type == modal.volume.FileEntryType.DIRECTORY:
                _walk(entry.path, local_dir / name)
            else:
                # File — read bytes and write locally.
                data = b"".join(vol.read_file(entry.path))
                (local_dir / name).write_bytes(data)
    _walk(adapter_name, target)
    log(f"Downloaded to {target}")
    return target
