"""CreativeOS Training Studio — fine-tune a model on rephrase data.

A multi-step wizard that walks the user through:

  1. Pick a database (default: ``~/.creativeos/rephrase_history.db``)
  2. Pick a base model (HuggingFace id or registered local model)
  3. Configure training (epochs, learning rate, batch size, LoRA params)
  4. Train (background thread, progress reporting)
  5. Test the result interactively
  6. Save to ``~/.creativeos/trained_models/<name>/`` and register it
     so the Writing Tool can pick it up.

If the user has only a small machine, they can stop at step 1 and
**Export** the dataset to JSONL — they can then run training on a
larger machine (Colab, server, etc.) and drop the resulting model
back into the registry by selecting its directory in step 2 → 6.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QMessageBox, QStackedWidget,
    QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QProgressBar,
    QPlainTextEdit, QCheckBox, QListWidget, QListWidgetItem, QDialog,
    QDialogButtonBox, QGroupBox, QAbstractItemView, QScrollArea,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
)

from src.config.creativeos_config import (
    TRAINED_MODELS_DIR, register_trained_model, load_trained_models,
)
from src.data.rephrase_database import (
    RephraseDatabase, DEFAULT_DB_PATH,
    SOURCE_REPHRASE, SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL,
    SOURCE_CORPUS, SOURCE_AGENT,
    SOURCE_WORLDBUILDING, SOURCE_CHARACTER, SOURCE_PLOT,
)


class _TrainingWorker(QThread):
    """Runs the actual fine-tuning in a background thread.

    Uses HuggingFace Transformers + PEFT (LoRA) so even modest machines
    can fine-tune small models. If transformers/peft isn't installed
    we fail gracefully and direct the user to export the dataset.
    """

    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # step, total
    finished_ok = pyqtSignal(str)  # output_path
    failed = pyqtSignal(str)

    def __init__(
        self, jsonl_path: Path, base_model: str, output_dir: Path,
        epochs: int = 1, learning_rate: float = 2e-4,
        batch_size: int = 1, max_length: int = 512,
        lora_r: int = 8, lora_alpha: Optional[int] = None,
        lora_dropout: float = 0.05,
        use_qlora: bool = False,
        adapter_path: str = "",
    ):
        super().__init__()
        self.jsonl_path = jsonl_path
        self.base_model = base_model
        self.output_dir = output_dir
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.max_length = max_length
        self.lora_r = lora_r
        # alpha = 2 * r is the QLoRA-paper convention and PEFT's
        # default at r=8. Linking alpha to r keeps the scaling
        # consistent across ranks; otherwise raising r alone weakens
        # the effective learning rate for the adapter.
        self.lora_alpha = (lora_alpha if lora_alpha is not None
                           else 2 * lora_r)
        self.lora_dropout = lora_dropout
        # When set, this is a path to a previously-trained adapter
        # directory. The worker loads the original base model + the
        # existing adapter (instead of stamping a fresh adapter onto a
        # raw base) so the user can continue training where a prior
        # run left off. Lives separately from ``base_model`` because
        # the adapter directory only contains adapter weights — the
        # base id is needed to resolve the underlying model.
        self.adapter_path = adapter_path
        # QLoRA = 4-bit-quantized base model + LoRA adapters on top.
        # The 4-bit weights are frozen; only the small LoRA layers
        # train, so memory drops ~4× vs bf16 with no accuracy loss
        # on instruction tuning. Requires bitsandbytes + CUDA — falls
        # back to standard precision with a warning on CPU/MPS.
        self.use_qlora = use_qlora

    def run(self):
        try:
            self.log.emit("Importing training libraries…")
            try:
                import torch
                from transformers import (
                    AutoTokenizer, AutoModelForCausalLM,
                    TrainingArguments, Trainer, DataCollatorForLanguageModeling,
                    TrainerCallback,
                )
                from datasets import Dataset, load_dataset
                from peft import LoraConfig, get_peft_model, TaskType
            except ImportError as e:
                self.failed.emit(
                    f"Missing dependency: {e}.\n\n"
                    "Install with:\n"
                    "  pip install transformers peft datasets accelerate\n\n"
                    "If you don't want to install training libraries on this "
                    "machine, use 'Export Dataset' on step 1 and run the "
                    "training elsewhere.")
                return

            # Memory-mapped JSONL load. ``load_dataset("json", ...)``
            # converts the file to Arrow on disk the first time it's
            # seen, then memory-maps it. RAM use is bounded by the
            # active batch (~tens of MB) regardless of file size, so
            # 100k-row literature corpora train fine on 16GB laptops.
            self.log.emit(
                f"Loading dataset from {self.jsonl_path} "
                f"(memory-mapped — RAM use bounded)…")
            try:
                file_size_mb = self.jsonl_path.stat().st_size / (1024 * 1024)
            except Exception:
                file_size_mb = 0.0
            try:
                ds_full = load_dataset(
                    "json",
                    data_files=str(self.jsonl_path),
                    split="train")
            except Exception as e:
                self.failed.emit(
                    f"Could not load dataset from {self.jsonl_path}: {e}")
                return
            n_rows = len(ds_full)
            self.log.emit(
                f"  {n_rows:,} examples · "
                f"{file_size_mb:.1f}MB on disk · "
                f"memory-mapped Arrow cache")
            if n_rows < 4:
                self.failed.emit(
                    f"Only {n_rows} examples in dataset — need at "
                    f"least 4 for a meaningful fine-tune. Collect more "
                    f"rephrases first.")
                return

            self.log.emit(f"Loading base model: {self.base_model}…")
            tokenizer = AutoTokenizer.from_pretrained(self.base_model)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            device_map = "auto"

            # QLoRA path: 4-bit-quantized weights + LoRA adapters. Cuts
            # base-model memory by ~4× so larger bases fit in laptop
            # RAM. Only fires when the user ticked the QLoRA checkbox
            # AND we have CUDA + bitsandbytes — gracefully falls back
            # to bf16/fp32 otherwise so a click on a Mac doesn't crash.
            quant_config = None
            qlora_active = False
            if self.use_qlora:
                if not torch.cuda.is_available():
                    self.log.emit(
                        "QLoRA requested but CUDA isn't available — "
                        "bitsandbytes 4-bit only runs on NVIDIA GPUs. "
                        "Falling back to standard precision.")
                else:
                    try:
                        from transformers import BitsAndBytesConfig
                        quant_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_use_double_quant=True,
                            bnb_4bit_compute_dtype=torch.bfloat16,
                        )
                        qlora_active = True
                        self.log.emit(
                            "QLoRA mode: loading base in 4-bit (NF4, "
                            "double-quant). LoRA adapters will train "
                            "in bfloat16 on top.")
                    except Exception as e:
                        self.log.emit(
                            f"QLoRA setup failed ({e}); falling back "
                            f"to standard precision.")

            model_kwargs = dict(
                torch_dtype=torch.bfloat16 if torch.cuda.is_available()
                or torch.backends.mps.is_available() else torch.float32,
                device_map=device_map,
            )
            if quant_config is not None:
                model_kwargs["quantization_config"] = quant_config
            model = AutoModelForCausalLM.from_pretrained(
                self.base_model, **model_kwargs)

            if qlora_active:
                # Prep frozen 4-bit weights for k-bit training (turns
                # on input-grad checkpointing, casts the LM head to
                # fp32, etc. — required before adding LoRA layers).
                try:
                    from peft import prepare_model_for_kbit_training
                    model = prepare_model_for_kbit_training(
                        model, use_gradient_checkpointing=True)
                except Exception as e:
                    self.log.emit(
                        f"prepare_model_for_kbit_training failed: {e}; "
                        f"continuing without it.")

            # Two paths from here on:
            #   (a) Continue training an existing adapter — apply the
            #       saved LoRA weights via PeftModel.from_pretrained,
            #       mark them trainable, and skip get_peft_model. The
            #       adapter's own r / alpha / dropout values from
            #       adapter_config.json take effect; the UI's r/alpha
            #       are irrelevant on the continuation path because
            #       changing rank mid-training is meaningless.
            #   (b) Fresh fine-tune — stamp a new LoRA adapter onto
            #       the base via get_peft_model with the user's r/alpha.
            if self.adapter_path:
                self.log.emit(
                    f"Continuing from existing adapter: "
                    f"{self.adapter_path}")
                from peft import PeftModel
                model = PeftModel.from_pretrained(
                    model, self.adapter_path, is_trainable=True)
                # Print stats: which params are trainable on the
                # continuation path (the adapter weights only).
                try:
                    model.print_trainable_parameters()
                except Exception:
                    pass
            else:
                self.log.emit(
                    "Wrapping with LoRA adapters (parameter-efficient)…"
                    + (" [QLoRA active]" if qlora_active else ""))
                peft_config = LoraConfig(
                    task_type=TaskType.CAUSAL_LM,
                    r=self.lora_r,
                    lora_alpha=self.lora_alpha,
                    lora_dropout=self.lora_dropout,
                    bias="none",
                )
                model = get_peft_model(model, peft_config)
                model.print_trainable_parameters()

            # Per-record format awareness. Each JSONL row carries a
            # ``format_type`` in its metadata (instruction | continuation
            # | chat). The trainer uses this to:
            #   * pick the right rendering — modern instruct models
            #     have a tokenizer.chat_template that matches what they
            #     were trained on; falling back to Alpaca's template
            #     wastes capacity on a format the base model doesn't
            #     recognize. We use apply_chat_template when available.
            #   * mask the prompt tokens with -100 in labels so loss
            #     only fires on the assistant's completion. Without
            #     this, the model learns to imitate prompts as well as
            #     responses, which is wasted training signal.
            #   * leave continuation rows (raw narrative) unmasked so
            #     the model imitates the whole passage's voice.
            has_chat_template = bool(getattr(tokenizer, "chat_template",
                                             None))
            self.log.emit(
                "Tokenizing… "
                f"(chat_template={'present' if has_chat_template else 'absent — using Alpaca'}; "
                f"loss masks prompt for instruction rows)")

            def _build_messages(rec):
                """Render a record as chat-template messages.

                Pulls metadata.system_prompt when set, otherwise uses a
                neutral default. The user turn folds instruction +
                input together; the assistant turn is the output.
                """
                meta = rec.get("metadata") or {}
                instr = rec.get("instruction", "") or ""
                inp = rec.get("input", "") or ""
                out = rec.get("output", "") or ""
                if "messages" in rec:
                    # Already a chat-format row (e.g. ShareGPT export)
                    return rec["messages"]
                user_msg = (f"{instr}\n\n{inp}".strip()
                            if inp else instr)
                msgs = []
                system = meta.get("system_prompt", "")
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": user_msg})
                msgs.append({"role": "assistant", "content": out})
                return msgs

            def render_full(rec):
                """Full sequence (prompt + response) — what the model
                will see during the forward pass."""
                if has_chat_template:
                    return tokenizer.apply_chat_template(
                        _build_messages(rec), tokenize=False)
                # Alpaca fallback for bases without a chat template
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
                """Just the prompt portion (no assistant content) so we
                can compute the token boundary for loss masking."""
                if has_chat_template:
                    msgs = _build_messages(rec)[:-1]  # drop assistant
                    return tokenizer.apply_chat_template(
                        msgs, tokenize=False, add_generation_prompt=True)
                instr = rec.get("instruction", "")
                inp = rec.get("input", "")
                if inp:
                    return (f"### Instruction:\n{instr}\n\n"
                            f"### Input:\n{inp}\n\n"
                            f"### Response:\n")
                return f"### Instruction:\n{instr}\n\n### Response:\n"

            def _format_type(rec) -> str:
                meta = rec.get("metadata") or {}
                return (meta.get("format_type") or "instruction").lower()

            # Streaming render + tokenize in a single .map() pass. Each
            # batch arrives as a dict-of-column-lists; we reconstruct
            # row dicts on the fly, render full/prompt strings, and
            # tokenize. Output is written to a memory-mapped Arrow
            # file — at no point is the whole dataset materialized in
            # Python objects, so memory stays bounded regardless of
            # the JSONL's size.
            def render_and_tokenize(batch):
                # Reconstruct row dicts from columnar batch.
                keys = list(batch.keys())
                n_in_batch = len(batch[keys[0]]) if keys else 0
                rows = [{k: batch[k][i] for k in keys}
                        for i in range(n_in_batch)]

                full_texts = [render_full(r) for r in rows]
                prompt_texts = [render_prompt(r) for r in rows]
                format_types = [_format_type(r) for r in rows]

                # Tokenize full sequences (prompt + assistant response)
                # and the prompt-only portion. Same special-token policy
                # so prompts form a clean prefix of full sequences.
                tokens = tokenizer(
                    full_texts, truncation=True,
                    max_length=self.max_length, padding=False)
                prompt_tokens = tokenizer(
                    prompt_texts, truncation=True,
                    max_length=self.max_length)

                labels = []
                for full_ids, prompt_ids, ftype in zip(
                        tokens["input_ids"],
                        prompt_tokens["input_ids"],
                        format_types):
                    lab = list(full_ids)
                    if ftype == "instruction":
                        # Mask prompt — model only learns to predict
                        # the assistant's response. ``min`` guards
                        # against the (rare) case where prompt
                        # tokenization truncated longer than full.
                        boundary = min(len(prompt_ids), len(lab))
                        for i in range(boundary):
                            lab[i] = -100
                    # continuation rows: no masking — model learns
                    # the whole passage to imitate voice.
                    labels.append(lab)
                tokens["labels"] = labels
                return tokens

            self.log.emit(
                "  tokenizing into memory-mapped cache "
                "(this is the streaming pass; you'll see batch logs)…")
            ds = ds_full.map(
                render_and_tokenize,
                batched=True,
                batch_size=64,
                # Drop the original JSONL columns from the cached
                # Arrow file — only the tokenized fields are needed
                # at training time. Cuts cache size and IO.
                remove_columns=ds_full.column_names,
                desc="Tokenizing")

            # Quick post-pass count of format types so the user sees
            # what mix of prompt-masked vs full-text training they
            # ended up with. Streamed via the dataset, not the
            # original Python list (which we no longer keep around).
            n_inst = 0
            n_cont = 0
            for batch in ds_full.iter(batch_size=512):
                # ``ds_full`` is the original (unprocessed) Dataset;
                # iterating it doesn't reload from disk meaningfully —
                # the metadata column is a single small string per row.
                # Cap the scan at a few thousand rows for big corpora
                # so the log line stays snappy.
                rows = [{k: batch[k][i] for k in batch.keys()}
                        for i in range(len(batch[next(iter(batch))]))]
                for r in rows:
                    ft = _format_type(r)
                    if ft == "instruction": n_inst += 1
                    elif ft == "continuation": n_cont += 1
                if (n_inst + n_cont) >= 5000:
                    break
            sample_note = (" (sampled — exact mix in cache)"
                           if (n_inst + n_cont) >= 5000 else "")
            self.log.emit(
                f"  format breakdown: {n_inst} instruction "
                f"(prompt-masked), {n_cont} continuation "
                f"(full-text learn){sample_note}")

            # Eval-split for overfitting protection. We hold out 15% of
            # the data when we have enough rows to make the split
            # meaningful — below 20 rows, the eval slice would be too
            # small to track anything useful, so we train on everything
            # and skip eval. With eval enabled, save_total_limit=2 keeps
            # the best + last checkpoints and load_best_model_at_end
            # restores the best one before saving the final model.
            eval_ds = None
            min_for_eval = 20
            if len(ds) >= min_for_eval:
                split = ds.train_test_split(test_size=0.15, seed=42)
                ds = split["train"]
                eval_ds = split["test"]
                self.log.emit(
                    f"  eval split: {len(ds)} train / {len(eval_ds)} eval "
                    f"(15% holdout for overfitting check)")
            else:
                self.log.emit(
                    f"  eval split: skipped (only {len(ds)} rows; need "
                    f"≥{min_for_eval} for a meaningful holdout)")

            self.output_dir.mkdir(parents=True, exist_ok=True)
            args_kwargs = dict(
                output_dir=str(self.output_dir / "checkpoints"),
                num_train_epochs=self.epochs,
                per_device_train_batch_size=self.batch_size,
                gradient_accumulation_steps=4,
                learning_rate=self.learning_rate,
                logging_steps=1,
                save_strategy="epoch",
                save_total_limit=2 if eval_ds is not None else 1,
                report_to=[],  # disable W&B, etc.
                bf16=torch.cuda.is_available() or torch.backends.mps.is_available(),
                remove_unused_columns=False,
            )
            if eval_ds is not None:
                # eval_strategy is the modern name; older transformers
                # used evaluation_strategy. Set both via inspect-guarded
                # passthrough so the Trainer accepts our args either way.
                import inspect as _ins
                ta_params = _ins.signature(TrainingArguments).parameters
                if "eval_strategy" in ta_params:
                    args_kwargs["eval_strategy"] = "epoch"
                else:
                    args_kwargs["evaluation_strategy"] = "epoch"
                args_kwargs["load_best_model_at_end"] = True
                args_kwargs["metric_for_best_model"] = "eval_loss"
                args_kwargs["greater_is_better"] = False
            args = TrainingArguments(**args_kwargs)

            collator = DataCollatorForLanguageModeling(
                tokenizer=tokenizer, mlm=False)

            class _Reporter:
                def __init__(self_, worker, total):
                    self_.worker = worker
                    self_.total = total
                    self_.step = 0
                def on_step(self_):
                    self_.step += 1
                    self_.worker.progress.emit(self_.step, self_.total)

            reporter = _Reporter(self,
                                 max(1, len(ds) // max(1, self.batch_size))
                                 * self.epochs)

            # Inherit from transformers' base class so we get a no-op
            # default for *every* hook the Trainer might call (including
            # ones added in future versions like on_substep_end,
            # on_optimizer_step, on_pre_optimizer_step, etc.). We only
            # override the two we actually care about.
            class _ProgressCallback(TrainerCallback):
                def on_step_end(self_, args, state, control, **kw):
                    reporter.on_step()
                def on_log(self_, args, state, control, logs=None, **kw):
                    if logs and 'loss' in logs:
                        self.log.emit(
                            f"step {state.global_step}: "
                            f"loss={logs['loss']:.4f}")

            # transformers 4.46 deprecated the ``tokenizer`` keyword and
            # renamed it to ``processing_class``; 5.0+ removed the old
            # name entirely. Use processing_class on modern installs and
            # fall back to tokenizer for older ones.
            trainer_kwargs = dict(
                model=model,
                args=args,
                train_dataset=ds,
                data_collator=collator,
                callbacks=[_ProgressCallback()],
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

            self.log.emit(f"Starting training: {self.epochs} epoch(s), "
                          f"{len(ds)} examples…")
            trainer.train()

            self.log.emit(f"Saving model to {self.output_dir}…")
            trainer.save_model(str(self.output_dir))
            tokenizer.save_pretrained(str(self.output_dir))
            self.finished_ok.emit(str(self.output_dir))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"Training failed: {e}")


class _ModalTrainingWorker(QThread):
    """Submit a fine-tune to Modal, poll for completion, download.

    Lives on its own QThread so the UI stays responsive during the
    minutes-to-hours-long run. Three phases:

      1. **Submit** — push the dataset bytes + config to Modal,
         persist the call id locally so a studio restart can
         re-attach.
      2. **Poll** — every 8s, ask Modal whether the function
         returned. While running, emit a heartbeat log line every
         minute so the user knows it's still alive.
      3. **Download** — pull the resulting LoRA adapter from
         Modal's volume into the local trained-models dir, then
         emit ``finished_ok`` so the studio can register it via
         the same code path local training uses.

    Errors at any phase emit ``failed`` with a human-readable
    message and the worker exits cleanly.
    """
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # step, total — indeterminate uses 0/0
    finished_ok = pyqtSignal(str, dict)  # output_path, result_meta
    failed = pyqtSignal(str)

    def __init__(self, *,
                 jsonl_path: Path,
                 config: dict,
                 gpu: str,
                 adapter_name: str,
                 parent=None):
        super().__init__(parent)
        self.jsonl_path = jsonl_path
        self.config = config
        self.gpu = gpu
        self.adapter_name = adapter_name

    def run(self):  # noqa: D401 — Qt slot
        try:
            from src.cloud import modal_train

            self.log.emit("[modal] Submitting job…")
            handle = modal_train.submit_training_job(
                jsonl_path=self.jsonl_path,
                config=self.config,
                gpu=self.gpu,
                adapter_name=self.adapter_name,
                on_log=lambda m: self.log.emit(f"[modal] {m}"),
            )
            self.log.emit(
                f"[modal] Submitted (call_id={handle.call_id}). "
                f"Polling for completion every 8s…")

            # Poll loop. We keep this simple — Modal's FunctionCall
            # doesn't expose granular per-step progress, so we just
            # wait for completion and emit a heartbeat every minute
            # so the user knows we're alive.
            poll_interval_s = 8
            last_heartbeat = time.time()
            heartbeat_interval_s = 60
            while True:
                state = modal_train.poll_job(handle)
                status = state.get("status")
                if status == "running":
                    if (time.time() - last_heartbeat
                            >= heartbeat_interval_s):
                        elapsed = int(time.time() - handle.submitted_at)
                        mins = elapsed // 60
                        self.log.emit(
                            f"[modal] still running "
                            f"({mins}m elapsed)…")
                        last_heartbeat = time.time()
                    self.msleep(poll_interval_s * 1000)
                    continue
                if status == "failed":
                    self.failed.emit(
                        f"Modal job failed: "
                        f"{state.get('error', 'unknown error')}")
                    return
                if status == "done":
                    result = state.get("result") or {}
                    self.log.emit(
                        f"[modal] ✓ training complete: "
                        f"{result.get('rows_trained', '?')} rows "
                        f"trained, {result.get('rows_evaluated', 0)} "
                        f"eval. Downloading adapter…")
                    break
                # Unknown — keep polling.
                self.msleep(poll_interval_s * 1000)

            # Download the adapter dir into the local registry.
            target_dir = TRAINED_MODELS_DIR / handle.adapter_name
            try:
                downloaded = modal_train.download_adapter(
                    handle.adapter_name, TRAINED_MODELS_DIR,
                    on_log=lambda m: self.log.emit(f"[modal] {m}"))
            except Exception as e:
                self.failed.emit(
                    f"Modal training succeeded but adapter download "
                    f"failed: {e}")
                return

            self.finished_ok.emit(str(downloaded), result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"Modal worker error: {e}")


class _MlxConversionWorker(QThread):
    """Run mlx_lm.fuse + mlx_lm.convert off the UI thread.

    Conversion takes minutes for small bases and tens of minutes for
    a 26B model — UI must stay responsive. We emit ``log`` per stage
    so the user can watch progress in the train log, and either
    ``finished_ok`` (with both produced paths) or ``failed``.
    """
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(str, str, str, str)
    # Args: mlx_path, fused_path, base_model, source_adapter_name.
    failed = pyqtSignal(str)

    def __init__(self, *,
                 adapter_dir: Path,
                 base_model: str,
                 adapter_name: str,
                 parent=None):
        super().__init__(parent)
        self.adapter_dir = adapter_dir
        self.base_model = base_model
        self.adapter_name = adapter_name

    def run(self):  # noqa: D401 — Qt slot
        try:
            from src.ai.mlx_conversion import convert_adapter_to_mlx
            result = convert_adapter_to_mlx(
                self.adapter_dir,
                base_model=self.base_model,
                quantize_bits=4,
                keep_fused=True,
                on_log=lambda m: self.log.emit(f"[mlx] {m}"),
            )
            self.finished_ok.emit(
                str(result.mlx_path),
                str(result.fused_path) if result.fused_path else "",
                self.base_model,
                self.adapter_name,
            )
        except Exception as e:
            self.failed.emit(str(e))


class _CorpusDashboardWidget(QWidget):
    """Step-1 at-a-glance dashboard.

    Renders the user's current corpus state — row counts, source
    breakdown, quality signals, junk-row estimate — without
    exporting JSONL. Updates instantly after upload / download /
    clean. Includes inline shortcuts to:

      * 🔍 Detailed quality check (full :class:`_CorpusQualityDialog`)
      * 🧹 Clean junk rows (existing retroactive cleaner)
      * ⟳ Refresh

    The widget is intentionally compact: 4 lines of stats + one
    action row. The full quality dialog stays the place for deep
    analysis; this is the "what does my corpus look like RIGHT
    NOW" surface that lives next to the corpus-actions buttons on
    Step 1.

    Stats come from :func:`corpus_quality.compute_db_stats`, which
    queries the DB directly — fast even on 100K-row corpora.
    """

    refresh_requested = pyqtSignal()  # for "🧹 Clean" → refresh-after

    def __init__(self, db_path: Path, parent_window=None):
        super().__init__(parent_window)
        self.db_path = db_path
        self._parent_window = parent_window
        self._build_ui()
        # Initial render uses an "unloaded" placeholder; the
        # caller calls refresh() once Step 1 is fully built.
        self._render_placeholder()

    def _build_ui(self):
        from PyQt6.QtWidgets import QFrame, QGridLayout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Frame styled as an inset panel.
        self._panel = QFrame()
        self._panel.setStyleSheet(
            "QFrame { background: #f9fafb; "
            "border: 1px solid #e5e7eb; border-radius: 6px; }")
        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header row.
        header = QHBoxLayout()
        title = QLabel("<b>📊 Corpus Dashboard</b>")
        header.addWidget(title)
        header.addStretch()
        self._refresh_btn = QPushButton("⟳ Refresh")
        self._refresh_btn.setStyleSheet(
            "QPushButton { padding: 2px 8px; font-size: 11px; "
            "background: transparent; border: 1px solid #d1d5db; "
            "border-radius: 3px; }")
        self._refresh_btn.setToolTip(
            "Re-scan the training DB. Cheap; safe to click anytime.")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Live stats — grid of label-value pairs.
        self._stats_grid = QGridLayout()
        self._stats_grid.setHorizontalSpacing(20)
        self._stats_grid.setVerticalSpacing(2)
        layout.addLayout(self._stats_grid)

        # Source breakdown bar.
        self._source_label = QLabel("")
        self._source_label.setStyleSheet(
            "color: #4b5563; font-size: 11px; padding-top: 4px;")
        self._source_label.setWordWrap(True)
        layout.addWidget(self._source_label)

        # Junk-row hint — colored to match severity.
        self._junk_hint = QLabel("")
        self._junk_hint.setWordWrap(True)
        self._junk_hint.setVisible(False)
        layout.addWidget(self._junk_hint)

        # Short-source disclosure — informational, not a warning.
        # Hidden by default; rendered when there are short-source
        # rows in the DB so users understand they're expected for
        # certain corpus types.
        self._short_source_hint = QLabel("")
        self._short_source_hint.setWordWrap(True)
        self._short_source_hint.setVisible(False)
        layout.addWidget(self._short_source_hint)

        # Action row — quick shortcuts that share existing dialogs.
        actions = QHBoxLayout()
        self._check_btn = QPushButton("🔍 Detailed quality check")
        self._check_btn.setToolTip(
            "Open the full quality dialog with intent-aware verdict, "
            "sample passages, and (when LLM is configured) AI "
            "opinion. Same dialog that fires when you click Start "
            "Training.")
        self._check_btn.clicked.connect(self._on_check_clicked)
        actions.addWidget(self._check_btn)

        self._clean_btn = QPushButton("🧹 Clean junk rows")
        self._clean_btn.setToolTip(
            "Run the corpus cleaner over the DB — drops boilerplate, "
            "tool-call JSON, page numbers, refusal templates. Backs "
            "up deleted rows. Refreshes the dashboard when done.")
        self._clean_btn.clicked.connect(self._on_clean_clicked)
        actions.addWidget(self._clean_btn)

        actions.addStretch()
        layout.addLayout(actions)

        outer.addWidget(self._panel)

    # ── Public API ────────────────────────────────────────

    def refresh(self):
        """Re-query the DB and re-render. Cheap (single SQLite scan
        plus a 5K-row sample for the junk-rate estimate)."""
        from src.ai.corpus_quality import compute_db_stats
        try:
            stats = compute_db_stats(self.db_path)
        except Exception as e:
            self._render_error(f"Could not read DB: {e}")
            return
        if stats.total_rows == 0:
            self._render_empty()
            return
        self._render_stats(stats)

    def set_db_path(self, db_path: Path):
        """The user can switch DBs in some flows; surface that
        without rebuilding the widget."""
        self.db_path = db_path
        self.refresh()

    # ── Renderers ─────────────────────────────────────────

    def _clear_grid(self):
        while self._stats_grid.count():
            item = self._stats_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_placeholder(self):
        self._clear_grid()
        self._stats_grid.addWidget(
            QLabel("<i style='color:#9ca3af'>"
                   "Click ⟳ Refresh to scan your DB</i>"),
            0, 0, 1, 4)
        self._source_label.setText("")
        self._junk_hint.setVisible(False)
        self._short_source_hint.setVisible(False)

    def _render_empty(self):
        self._clear_grid()
        self._stats_grid.addWidget(
            QLabel("<i style='color:#6b7280'>"
                   "Training DB is empty. Upload your writing, "
                   "import a project, or pick corpora from the "
                   "Library.</i>"),
            0, 0, 1, 4)
        self._source_label.setText("")
        self._junk_hint.setVisible(False)
        self._short_source_hint.setVisible(False)

    def _render_error(self, msg: str):
        self._clear_grid()
        self._stats_grid.addWidget(
            QLabel(f"<span style='color:#b91c1c'>"
                   f"{msg}</span>"),
            0, 0, 1, 4)
        self._source_label.setText("")
        self._junk_hint.setVisible(False)
        self._short_source_hint.setVisible(False)

    def _render_stats(self, stats):
        self._clear_grid()

        # The dashboard now shows ONLY the metrics that drive a
        # decision: row count (do I have enough data?), median
        # output length (is this the right length for my intent?),
        # voice-tagged % (will the model learn voice?). DB size and
        # other diagnostics moved to the footer hint below — useful
        # but not load-bearing.
        voice_pct = (stats.n_voice_tagged / stats.total_rows * 100.0
                     if stats.total_rows else 0)
        size_str = (f"{stats.db_size_kb / 1024:.1f} MB"
                    if stats.db_size_kb >= 1024
                    else f"{stats.db_size_kb} KB")

        self._stats_grid.addWidget(
            QLabel("<span style='color:#6b7280;font-size:11px;'>"
                   "Rows</span>"), 0, 0)
        self._stats_grid.addWidget(
            QLabel(f"<b style='font-size:16px;'>"
                   f"{stats.total_rows:,}</b>"
                   f" <span style='color:#9ca3af;font-size:11px;'>"
                   f"in {size_str}</span>"),
            1, 0)

        self._stats_grid.addWidget(
            QLabel("<span style='color:#6b7280;font-size:11px;'>"
                   "Median output</span>"), 0, 1)
        self._stats_grid.addWidget(
            QLabel(f"<b style='font-size:16px;'>"
                   f"{stats.median_output_chars}</b>"
                   f" <span style='color:#9ca3af;font-size:11px;'>"
                   f"chars</span>"),
            1, 1)

        self._stats_grid.addWidget(
            QLabel("<span style='color:#6b7280;font-size:11px;'>"
                   "Voice-tagged</span>"), 0, 2)
        self._stats_grid.addWidget(
            QLabel(f"<b style='font-size:16px;'>{voice_pct:.0f}%</b>"
                   f" <span style='color:#9ca3af;font-size:11px;'>"
                   f"({stats.n_voice_tagged:,} rows)</span>"),
            1, 2)

        # Source breakdown.
        if stats.by_source:
            parts = []
            for st, n in sorted(stats.by_source.items(),
                                 key=lambda kv: -kv[1]):
                pct = n / stats.total_rows * 100.0
                parts.append(f"<b>{st}</b>: "
                             f"{n:,} <span style='color:#9ca3af;'>"
                             f"({pct:.0f}%)</span>")
            self._source_label.setText(
                "Source breakdown: " + " · ".join(parts))
        else:
            self._source_label.setText("")

        # Junk-row hint with severity coloring.
        if stats.n_likely_junk > 0:
            if stats.junk_pct >= 5:
                color, bg = "#b91c1c", "#fee2e2"
                tone = ("⚠ Significant junk in your DB. "
                        "Run the cleaner before training.")
            elif stats.junk_pct >= 1:
                color, bg = "#92400e", "#fef3c7"
                tone = ("Some boilerplate / metadata-only rows "
                        "detected. Consider cleaning.")
            else:
                color, bg = "#065f46", "#ecfdf5"
                tone = ("Mostly clean — a small fraction looks "
                        "like junk.")
            self._junk_hint.setText(
                f"<span style='color:{color}'>"
                f"~{stats.n_likely_junk:,} likely-junk rows "
                f"({stats.junk_pct:.1f}% of total) — {tone}"
                f"</span>")
            self._junk_hint.setStyleSheet(
                f"background: {bg}; "
                f"border-radius: 3px; padding: 4px 8px; "
                f"font-size: 11px; margin-top: 2px;")
            self._junk_hint.setVisible(True)
        else:
            self._junk_hint.setVisible(False)

        # Short-source disclosure. Many ingestion paths legitimately
        # produce short source_text — Wikipedia movie plots use
        # title→plot pairs, sentence-level splits use a one-sentence
        # opener. Surface the count + an explanation so users don't
        # mistake it for a bug.
        if stats.n_short_source > 0:
            short_pct = stats.n_short_source / stats.total_rows * 100.0
            corpus_rows = stats.by_source.get("corpus", 0)
            short_pct_of_corpus = (
                stats.n_short_source / corpus_rows * 100.0
                if corpus_rows else 0)
            self._short_source_hint.setText(
                f"<span style='color:#374151;'>"
                f"<b>ℹ {stats.n_short_source:,}</b> corpus rows have "
                f"a short source ({short_pct_of_corpus:.0f}% of "
                f"corpus) — typical for title→plot datasets and "
                f"opener-sentence splits. The trainer wraps these "
                f"in the right prompt template at training time."
                f"</span>")
            self._short_source_hint.setStyleSheet(
                "background: #eff6ff; "
                "border-left: 3px solid #3b82f6; "
                "border-radius: 3px; padding: 4px 8px; "
                "font-size: 11px; margin-top: 2px;")
            self._short_source_hint.setVisible(True)
        else:
            self._short_source_hint.setVisible(False)

    # ── Action handlers (delegate to parent window) ───────

    def _on_check_clicked(self):
        if self._parent_window is not None and hasattr(
                self._parent_window, "_open_corpus_quality_check"):
            self._parent_window._open_corpus_quality_check()

    def _on_clean_clicked(self):
        if self._parent_window is not None and hasattr(
                self._parent_window, "_open_clean_corpus_dialog"):
            self._parent_window._open_clean_corpus_dialog()
        # Refresh after the cleaner closes — it deletes rows so the
        # dashboard's stats are stale.
        self.refresh()


class _CorpusQualityWorker(QThread):
    """Run the LLM-based quality assessment off the UI thread.

    The deterministic stats + verdict are computed synchronously
    (cheap — one pass over the JSONL); the LLM verdict can take
    10-30s on a slow API or local model, so it runs in a worker
    and the dialog appends the result when ready.
    """
    finished_ok = pyqtSignal(object)  # Verdict
    failed = pyqtSignal(str)

    def __init__(self, *,
                 stats,
                 intent: str,
                 llm_generate,
                 parent=None):
        super().__init__(parent)
        self.stats = stats
        self.intent = intent
        self.llm_generate = llm_generate

    def run(self):  # noqa: D401 — Qt slot
        try:
            from src.ai.corpus_quality import llm_verdict
            v = llm_verdict(
                self.stats,
                intent=self.intent,
                llm_generate=self.llm_generate)
            self.finished_ok.emit(v)
        except Exception as e:
            self.failed.emit(str(e))


class _CorpusQualityDialog(QDialog):
    """Pre-training corpus quality gate.

    Shown right after the dataset is exported and BEFORE the
    trainer kicks off. Renders stats, sample passages, and a
    deterministic verdict immediately; can also fetch an LLM
    opinion in the background (if a configured LLM is available).

    Returns one of:
      * ``QDialog.Accepted`` — user clicked Continue, training proceeds.
      * ``QDialog.Rejected`` — user clicked Cancel.

    Side effects:
      * Clean Now button opens the existing 🧹 retroactive cleaner.
        The dialog stays open; once the cleaner finishes, the user
        can re-run the quality scan via the Re-scan button.
    """

    # Custom return code so callers can route back to the cleaner
    # flow without re-prompting. Qt's standard accept/reject are
    # binary; we add a third "user wants to clean first" path.
    CLEAN_REQUESTED = 1000

    def __init__(self, *,
                 jsonl_path: Path,
                 intent: str,
                 selected_genres,
                 selected_tones,
                 llm_generate=None,
                 parent=None):
        super().__init__(parent)
        self.jsonl_path = jsonl_path
        self.intent = intent
        self.selected_genres = list(selected_genres or [])
        self.selected_tones = list(selected_tones or [])
        self.llm_generate = llm_generate
        self._llm_worker: Optional[_CorpusQualityWorker] = None

        self.setWindowTitle("Pre-training corpus quality check")
        self.setMinimumSize(720, 640)
        self._build_ui()
        self._run_scan()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("<b>Pre-training corpus quality check</b>")
        title_font = title.font()
        title_font.setPointSize(13)
        title.setFont(title_font)
        layout.addWidget(title)
        intro = QLabel(
            "What's about to be trained on. Address any concerns "
            "before spending GPU time — or hit 'Continue Anyway' if "
            "you know what you're doing.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280;")
        layout.addWidget(intro)

        # Tabs: overview (verdict + samples for the SELECTED corpus
        # mix) vs. By genre / By corpus (whole-DB breakdowns the
        # user can use to spot lopsided distributions). The
        # breakdowns lazy-load on first tab click — they iterate
        # the full DB so we avoid the cost when the user doesn't
        # open the tab.
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._loaded_genre_tab = False
        self._loaded_corpus_tab = False
        layout.addWidget(self.tabs, 1)

        # ── Tab 1: Overview ──
        overview = QWidget()
        ov_layout = QVBoxLayout(overview)
        ov_layout.setSpacing(8)

        self.stats_label = QLabel("Scanning…")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet(
            "background: #f3f4f6; border-radius: 4px; "
            "padding: 10px; font-family: monospace; font-size: 11px;")
        self.stats_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        ov_layout.addWidget(self.stats_label)

        self.det_label = QLabel("")
        self.det_label.setWordWrap(True)
        ov_layout.addWidget(self.det_label)

        self.llm_label = QLabel("")
        self.llm_label.setWordWrap(True)
        ov_layout.addWidget(self.llm_label)

        self.llm_btn = QPushButton("🤖 Get AI opinion")
        self.llm_btn.setToolTip(
            "Ask the configured LLM to review the corpus and give "
            "an honest assessment. Falls back gracefully if no LLM "
            "is configured.")
        self.llm_btn.clicked.connect(self._on_request_llm_opinion)
        ov_layout.addWidget(self.llm_btn)

        ov_layout.addWidget(QLabel("<b>Sample passages</b>"))
        self.samples_view = QPlainTextEdit()
        self.samples_view.setReadOnly(True)
        self.samples_view.setStyleSheet(
            "font-family: monospace; font-size: 10px; "
            "background: #f9fafb; color: #111827;")
        self.samples_view.setMaximumHeight(180)
        ov_layout.addWidget(self.samples_view)
        ov_layout.addStretch()
        self.tabs.addTab(overview, "Overview")

        # ── Tab 2: By genre ──
        self.genre_tab = self._build_breakdown_tab(
            placeholder="Click to compute per-genre metrics for "
                        "the whole DB. Iterates every row so it "
                        "may take a few seconds on a big corpus.",
            columns=["Genre", "Rows", "Median output (chars)",
                     "Voice-tagged"])
        self.tabs.addTab(self.genre_tab["widget"], "By genre")

        # ── Tab 3: By corpus ──
        self.corpus_tab = self._build_breakdown_tab(
            placeholder="Click to compute per-corpus metrics. "
                        "Identifies each ingested catalog corpus, "
                        "upload, or project import and reports row "
                        "count, median output length, and "
                        "short-source % (a leading indicator of a "
                        "bad ingest).",
            columns=["Corpus", "Kind", "Rows",
                     "Median output (chars)", "Short source %"])
        self.tabs.addTab(self.corpus_tab["widget"], "By corpus")

        # Action row.
        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.cancel_btn)

        self.clean_btn = QPushButton("🧹 Clean corpora first")
        self.clean_btn.setToolTip(
            "Run the corpus cleaner over your DB (drops boilerplate, "
            "tool-call JSON, page numbers, etc.). After cleaning, "
            "this dialog re-opens with fresh stats.")
        self.clean_btn.clicked.connect(self._on_clean_first)
        actions.addWidget(self.clean_btn)

        self.rescan_btn = QPushButton("⟳ Re-scan")
        self.rescan_btn.setToolTip(
            "Re-run the deterministic stats — useful after you've "
            "cleaned the corpus or changed something else "
            "external to this dialog.")
        self.rescan_btn.clicked.connect(self._run_scan)
        actions.addWidget(self.rescan_btn)

        actions.addStretch()

        self.continue_btn = QPushButton("▶ Continue Anyway")
        self.continue_btn.clicked.connect(self.accept)
        actions.addWidget(self.continue_btn)
        layout.addLayout(actions)

    def _build_breakdown_tab(self, *, placeholder: str,
                             columns: List[str]) -> Dict[str, Any]:
        """Build a "By genre" / "By corpus" tab — placeholder + table.

        Returns a dict with the wrapper widget, the inner table, and
        the placeholder label so the load callback can swap them.
        """
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)

        ph = QLabel(placeholder)
        ph.setWordWrap(True)
        ph.setStyleSheet(
            "color:#374151;background:#f3f4f6;border-radius:6px;"
            "padding:12px;")
        wrap_layout.addWidget(ph)

        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        table.setSortingEnabled(True)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setVisible(False)
        wrap_layout.addWidget(table, 1)

        return {"widget": wrap, "table": table, "placeholder": ph}

    def _on_tab_changed(self, idx: int):
        # Lazy-load per-genre / per-corpus metrics on first view.
        # ``compute_stats`` / quality scan run on the JSONL we
        # already exported; the breakdown helpers iterate the full
        # SQLite DB and take a second or two on a big corpus, so we
        # only pay that cost when the user opens the tab.
        text = self.tabs.tabText(idx)
        if text == "By genre" and not self._loaded_genre_tab:
            self._load_genre_tab()
            self._loaded_genre_tab = True
        elif text == "By corpus" and not self._loaded_corpus_tab:
            self._load_corpus_tab()
            self._loaded_corpus_tab = True

    def _resolve_db_path(self) -> Optional[Path]:
        """Find the parent window's DB path.

        The dialog is opened from TrainingToolWindow which exposes
        ``db_path``; we walk up the parent chain to find it. Returns
        None if unreachable (defensive — shouldn't happen in normal
        flow but the dialog can in theory be opened headless).
        """
        p = self.parent()
        while p is not None:
            if hasattr(p, "db_path"):
                return p.db_path
            p = p.parent() if hasattr(p, "parent") else None
        return None

    def _load_genre_tab(self):
        from PyQt6.QtWidgets import QApplication
        db_path = self._resolve_db_path()
        if db_path is None:
            self.genre_tab["placeholder"].setText(
                "Could not locate training DB.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            db = RephraseDatabase(db_path)
            metrics = db.per_genre_metrics()
        except Exception as e:
            self.genre_tab["placeholder"].setText(
                f"Failed: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        table = self.genre_tab["table"]
        table.setRowCount(len(metrics))
        # Sorting is enabled — we set numeric items via setData so
        # column sorts are correct rather than lexicographic.
        from PyQt6.QtCore import Qt as _Qt
        table.setSortingEnabled(False)
        for i, m in enumerate(metrics):
            table.setItem(i, 0, QTableWidgetItem(m["genre"]))
            it = QTableWidgetItem()
            it.setData(_Qt.ItemDataRole.DisplayRole, m["rows"])
            table.setItem(i, 1, it)
            it = QTableWidgetItem()
            it.setData(_Qt.ItemDataRole.DisplayRole,
                       m["median_output_chars"])
            table.setItem(i, 2, it)
            it = QTableWidgetItem()
            it.setData(_Qt.ItemDataRole.DisplayRole, m["voice_tagged"])
            table.setItem(i, 3, it)
        table.setSortingEnabled(True)
        # Sort by row count descending — the most-populated genres
        # are the most actionable.
        table.sortItems(1, _Qt.SortOrder.DescendingOrder)
        self.genre_tab["placeholder"].setVisible(False)
        table.setVisible(True)

    def _load_corpus_tab(self):
        from PyQt6.QtWidgets import QApplication
        db_path = self._resolve_db_path()
        if db_path is None:
            self.corpus_tab["placeholder"].setText(
                "Could not locate training DB.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            db = RephraseDatabase(db_path)
            metrics = db.per_corpus_metrics()
        except Exception as e:
            self.corpus_tab["placeholder"].setText(
                f"Failed: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        table = self.corpus_tab["table"]
        table.setRowCount(len(metrics))
        from PyQt6.QtCore import Qt as _Qt
        table.setSortingEnabled(False)
        for i, m in enumerate(metrics):
            table.setItem(i, 0, QTableWidgetItem(m["label"]))
            table.setItem(i, 1, QTableWidgetItem(m["kind"]))
            it = QTableWidgetItem()
            it.setData(_Qt.ItemDataRole.DisplayRole, m["rows"])
            table.setItem(i, 2, it)
            it = QTableWidgetItem()
            it.setData(_Qt.ItemDataRole.DisplayRole,
                       m["median_output_chars"])
            table.setItem(i, 3, it)
            it = QTableWidgetItem()
            # Format short-source as an int 0-100 so the column
            # sorts numerically, with the % suffix in the display.
            it.setData(_Qt.ItemDataRole.DisplayRole,
                       round(m["short_source_pct"], 1))
            table.setItem(i, 4, it)
        table.setSortingEnabled(True)
        table.sortItems(2, _Qt.SortOrder.DescendingOrder)
        self.corpus_tab["placeholder"].setVisible(False)
        table.setVisible(True)

    # ── Behaviour ────────────────────────────────────────

    def _run_scan(self):
        """Compute stats + render. Cheap — runs synchronously."""
        from src.ai.corpus_quality import (
            compute_stats, deterministic_verdict, sample_passages,
        )
        try:
            stats = compute_stats(
                self.jsonl_path,
                selected_genres=self.selected_genres,
                selected_tones=self.selected_tones,
                n_samples=5)
        except Exception as e:
            self.stats_label.setText(
                f"<span style='color:#b91c1c'>Could not scan: {e}</span>")
            return
        self._stats = stats
        self.stats_label.setText(self._render_stats(stats))
        verdict = deterministic_verdict(stats, intent=self.intent)
        self._render_verdict(verdict, target=self.det_label,
                              label="Deterministic verdict")
        # Auto-set Continue button styling based on severity.
        if verdict.severity == "fail":
            self.continue_btn.setStyleSheet(
                "QPushButton { background-color: #fee2e2; "
                "color: #991b1b; padding: 6px 14px; "
                "border-radius: 5px; }")
            self.cancel_btn.setDefault(True)
        elif verdict.severity == "warn":
            self.continue_btn.setStyleSheet(
                "QPushButton { background-color: #fef3c7; "
                "color: #92400e; padding: 6px 14px; "
                "border-radius: 5px; }")
        else:
            self.continue_btn.setStyleSheet(
                "QPushButton { background-color: #16a34a; "
                "color: white; padding: 6px 14px; "
                "border-radius: 5px; font-weight: bold; }")
            self.continue_btn.setDefault(True)

        # Render samples.
        samples = sample_passages(stats, n=5)
        if not samples:
            self.samples_view.setPlainText(
                "(no samples — corpus is empty)")
        else:
            # Render with clear, framed sections so users don't
            # mistake the prompt template ("Continue this passage…")
            # for actual corpus content. The instruction text is
            # what the trainer wraps around your data; the model's
            # target is the assistant block.
            blocks = []
            for i, s in enumerate(samples):
                blocks.append(
                    f"╔═══ Sample {i+1} of {len(samples)} ═══\n"
                    f"║ ↓ what the trainer SHOWS the model "
                    f"(prompt template + your text)\n"
                    f"╠══════════════════════════════════\n"
                    f"{s['user'][:300]}\n"
                    f"╠══ ↓ what the model LEARNS to produce "
                    f"(your prose)\n╠══════════════════════════════════\n"
                    f"{s['assistant'][:400]}\n"
                    f"╚══════════════════════════════════")
            self.samples_view.setPlainText("\n\n".join(blocks))

    def _render_stats(self, stats) -> str:
        sources = ", ".join(
            f"{k}={v}" for k, v in sorted(stats.by_source.items()))
        lines = [
            f"Rows:                {stats.n_rows}",
            f"Source breakdown:    {sources or '(none)'}",
            f"Median user chars:   {stats.median_user_len}",
            f"Median output chars: {stats.median_output_len}  "
            f"(p10={stats.p10_output_len}, p90={stats.p90_output_len})",
            f"Vocab diversity:     {stats.type_token_ratio:.3f}  "
            f"(type-token ratio)",
            f"Unique openers:      "
            f"{stats.pct_unique_openers:.1f}%  "
            f"({stats.n_unique_openers}/"
            f"{stats.n_unique_openers + stats.n_duplicate_openers})",
            f"Voice-tagged rows:   {stats.n_voice_tagged}",
        ]
        if stats.pct_too_short:
            lines.append(
                f"Too-short outputs:   {stats.pct_too_short:.1f}%")
        if stats.pct_too_long:
            lines.append(
                f"Too-long outputs:    {stats.pct_too_long:.1f}%")
        if stats.pct_matching_genres is not None:
            lines.append(
                f"Genre tag match:     "
                f"{stats.pct_matching_genres:.0f}%")
        if stats.pct_matching_tones is not None:
            lines.append(
                f"Tone tag match:      "
                f"{stats.pct_matching_tones:.0f}%")
        return "\n".join(lines)

    def _render_verdict(self, verdict, *, target, label: str):
        body = (f"<div style='border-left: 4px solid {verdict.color}; "
                f"padding: 8px 12px; background: #fafafa; "
                f"margin-top: 6px;'>"
                f"<div style='font-weight: bold; color: {verdict.color};'>"
                f"{verdict.emoji} {label}: {verdict.severity.upper()}"
                f"</div>"
                f"<div style='margin: 6px 0;'>{verdict.summary}</div>")
        if verdict.reasons:
            body += "<div><b>Reasons:</b><ul style='margin: 4px 0;'>"
            for r in verdict.reasons:
                body += f"<li>{r}</li>"
            body += "</ul></div>"
        if verdict.suggestions:
            body += "<div><b>Suggestions:</b><ul style='margin: 4px 0;'>"
            for s in verdict.suggestions:
                body += f"<li>{s}</li>"
            body += "</ul></div>"
        body += "</div>"
        target.setText(body)

    def _on_request_llm_opinion(self):
        if self.llm_generate is None:
            self.llm_label.setText(
                "<i style='color:#6b7280;'>No LLM configured — "
                "deterministic verdict only.</i>")
            return
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return
        self.llm_btn.setEnabled(False)
        self.llm_label.setText(
            "<i style='color:#6b7280;'>Asking the configured LLM "
            "for an honest review…</i>")
        self._llm_worker = _CorpusQualityWorker(
            stats=self._stats,
            intent=self.intent,
            llm_generate=self.llm_generate,
            parent=self)
        self._llm_worker.finished_ok.connect(self._on_llm_done)
        self._llm_worker.failed.connect(self._on_llm_failed)
        self._llm_worker.start()

    def _on_llm_done(self, verdict):
        self.llm_btn.setEnabled(True)
        self.llm_btn.setText("🤖 Re-ask AI")
        self._render_verdict(verdict, target=self.llm_label,
                              label="LLM verdict")

    def _on_llm_failed(self, msg: str):
        self.llm_btn.setEnabled(True)
        self.llm_label.setText(
            f"<span style='color:#b45309;'>LLM verdict failed: "
            f"{msg}</span>")

    def _on_clean_first(self):
        """User wants to clean before training. Close the dialog
        with the custom CLEAN_REQUESTED code so the caller knows
        to open the cleaner instead of just cancelling."""
        self.done(self.CLEAN_REQUESTED)


class _ModalConfirmDialog(QDialog):
    """Pre-submit confirmation for Modal training.

    Replaces the old single-line "Confirm Modal training?" message
    box. Now shows three preset profiles (Economy / Balanced /
    Performance) so the user picks the cost-vs-performance balance
    explicitly, plus any overspend warnings the heuristic flags
    for the chosen base + corpus + epochs combination.

    Returns the picked :class:`BalanceProfile` via
    :meth:`chosen_profile` after Accepted.
    """

    def __init__(self, *,
                 base_model: str,
                 base_size_b: float,
                 n_rows: int,
                 epochs: int,
                 use_qlora: bool,
                 intent: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Modal training")
        self.setMinimumSize(620, 460)
        self._base_model = base_model
        self._base_size_b = base_size_b
        self._n_rows = n_rows
        self._epochs = epochs
        self._use_qlora = use_qlora
        self._intent = intent

        from src.cloud.modal_train import (
            recommend_balance, flag_overspend,
        )
        self._profiles = recommend_balance(
            base_size_b=base_size_b,
            corpus_rows=n_rows,
            epochs=epochs,
            use_qlora=use_qlora)
        self._chosen_name = "balanced"  # default
        self._build_ui(flag_overspend(
            base_size_b=base_size_b,
            corpus_rows=n_rows,
            epochs=epochs,
            gpu=self._profiles["balanced"].gpu,
            intent=intent))

    def _build_ui(self, initial_warnings):
        from PyQt6.QtWidgets import QButtonGroup, QRadioButton
        layout = QVBoxLayout(self)

        title = QLabel("<b>Submit this training run to Modal?</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        layout.addWidget(title)

        summary = QLabel(
            f"<b>Base model:</b> {self._base_model}<br>"
            f"<b>Rows:</b> {self._n_rows} &nbsp;·&nbsp; "
            f"<b>Epochs:</b> {self._epochs} &nbsp;·&nbsp; "
            f"<b>QLoRA:</b> {'on' if self._use_qlora else 'off'}")
        summary.setStyleSheet(
            "background: #f3f4f6; border-radius: 4px; "
            "padding: 8px 10px; color: #374151;")
        layout.addWidget(summary)

        # Preset picker. Create the warnings_label FIRST so the
        # default-radio toggle signal (fired by setChecked) can find
        # it when it triggers _on_preset_picked → _render_warnings.
        layout.addWidget(QLabel(
            "<b>Cost / performance preset</b>"))
        self._radio_group = QButtonGroup(self)
        self._radios: dict = {}

        # Warnings panel placeholder — populated below; created up
        # front so the radio toggle handler doesn't crash.
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)

        for slot in ("economy", "balanced", "performance"):
            bp = self._profiles[slot]
            rb = QRadioButton(self._format_preset_label(bp))
            rb.setStyleSheet(
                "QRadioButton { padding: 6px; }"
                "QRadioButton::indicator { margin-right: 8px; }")
            rb.toggled.connect(
                lambda checked, name=slot: self._on_preset_picked(name) if checked else None)
            self._radio_group.addButton(rb)
            self._radios[slot] = rb
            layout.addWidget(rb)
        # Default = Balanced. Triggers _on_preset_picked which
        # populates the warnings panel from the right state.
        self._radios["balanced"].setChecked(True)

        # Now physically place the warnings_label below the radios.
        layout.addWidget(self._warnings_label)
        # Initial fill in case no toggle fired (shouldn't happen,
        # but keeps the dialog deterministic).
        if not self._warnings_label.text():
            self._render_warnings(initial_warnings)

        # Tail note.
        tail = QLabel(
            "<span style='color:#6b7280;font-size:11px;'>"
            "The trained LoRA adapter downloads back to your local "
            "registry automatically. Your dataset only sits on "
            "Modal's machine for the duration of the run."
            "</span>")
        tail.setWordWrap(True)
        layout.addWidget(tail)
        layout.addStretch()

        # Buttons.
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        actions.addStretch()
        submit = QPushButton("☁️ Submit to Modal")
        submit.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 6px 14px; border-radius: 5px; "
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #4f46e5; }")
        submit.clicked.connect(self.accept)
        submit.setDefault(True)
        actions.addWidget(submit)
        layout.addLayout(actions)

    def _format_preset_label(self, bp) -> str:
        """Build the radio-button text for one preset."""
        return (f"{bp.label}  —  GPU: {bp.gpu}  ·  "
                f"~${bp.cost_low:.2f}–${bp.cost_high:.2f}\n"
                f"        {bp.rationale}")

    def _on_preset_picked(self, name: str):
        self._chosen_name = name
        from src.cloud.modal_train import flag_overspend
        warnings = flag_overspend(
            base_size_b=self._base_size_b,
            corpus_rows=self._n_rows,
            epochs=self._epochs,
            gpu=self._profiles[name].gpu,
            intent=self._intent)
        self._render_warnings(warnings)

    def _render_warnings(self, warnings):
        if not warnings:
            self._warnings_label.setText(
                "<span style='color:#16a34a;'>"
                "✅ No overspend concerns flagged for this combo."
                "</span>")
            self._warnings_label.setStyleSheet(
                "background: #ecfdf5; color: #065f46; "
                "border-left: 3px solid #10b981; "
                "border-radius: 4px; padding: 8px 12px; "
                "margin-top: 4px;")
            return
        body = "<b>⚠ Cost-vs-performance concerns:</b>"
        for w in warnings:
            body += f"<br>&nbsp;&nbsp;• {w}"
        self._warnings_label.setText(body)
        self._warnings_label.setStyleSheet(
            "background: #fef3c7; color: #92400e; "
            "border-left: 3px solid #f59e0b; "
            "border-radius: 4px; padding: 8px 12px; "
            "margin-top: 4px;")

    def chosen_profile(self):
        return self._profiles[self._chosen_name]


class _ModalCredentialsDialog(QDialog):
    """Paste Modal API tokens into the OS keystore.

    The dialog keeps three things visible at once:
      * Where Modal would currently authenticate from (env / toml /
        keystore / nothing) — so the user knows whether saving
        keystore tokens will *win* or be overridden by an existing
        env var or ``~/.modal.toml``.
      * Two inputs (token id + secret), masked.
      * Save / Test / Clear buttons.

    Save writes both values to the keystore atomically. Test exports
    them into the env, calls ``check_setup``, and reports back —
    no actual Modal RPC, so it stays cheap and offline.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modal Credentials")
        self.setMinimumSize(540, 360)
        self._build_ui()
        self._refresh_status()

    def _build_ui(self):
        from PyQt6.QtWidgets import (
            QDialogButtonBox, QFrame,
        )
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Paste your Modal API tokens to store them in the "
            "OS keystore (Keychain / Credential Manager / "
            "Secret Service). The studio will inject them as "
            "environment variables before each cloud-training run.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #4b5563; padding-bottom: 6px;")
        layout.addWidget(intro)

        get_link = QLabel(
            "<a href='https://modal.com/settings/tokens'>"
            "Get tokens from modal.com/settings/tokens →</a>")
        get_link.setOpenExternalLinks(True)
        layout.addWidget(get_link)

        # Active source banner — shows which auth layer is in play.
        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet(
            "background: #f3f4f6; border-radius: 4px; "
            "padding: 8px 10px; color: #374151;")
        layout.addWidget(self.source_label)

        form = QFormLayout()
        self.token_id_edit = QLineEdit()
        self.token_id_edit.setPlaceholderText("ak-…")
        self.token_id_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Token ID:", self.token_id_edit)

        self.token_secret_edit = QLineEdit()
        self.token_secret_edit.setPlaceholderText("as-…")
        self.token_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Token secret:", self.token_secret_edit)

        # Show / hide tokens toggle for users who want to verify.
        self.show_cb = QCheckBox("Show tokens while typing")
        self.show_cb.toggled.connect(self._on_show_toggled)
        form.addRow("", self.show_cb)
        layout.addLayout(form)

        # Action buttons.
        actions = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save to Keystore")
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; "
            "padding: 6px 14px; border-radius: 5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #15803d; }")
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)

        self.test_btn = QPushButton("🔍 Test setup")
        self.test_btn.setToolTip(
            "Apply the keystore tokens to the environment and run "
            "the local Modal setup probe (no network call).")
        self.test_btn.clicked.connect(self._on_test)
        actions.addWidget(self.test_btn)

        actions.addStretch()
        self.clear_btn = QPushButton("🗑 Clear keystore")
        self.clear_btn.setStyleSheet("color: #b91c1c;")
        self.clear_btn.clicked.connect(self._on_clear)
        actions.addWidget(self.clear_btn)
        layout.addLayout(actions)

        # Status line — shows save / test / clear results.
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "color: #6b7280; padding: 4px 0;")
        layout.addWidget(self.status_label)

        layout.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

    def _on_show_toggled(self, on: bool):
        mode = (QLineEdit.EchoMode.Normal if on
                else QLineEdit.EchoMode.Password)
        self.token_id_edit.setEchoMode(mode)
        self.token_secret_edit.setEchoMode(mode)

    def _refresh_status(self):
        from src.cloud.modal_credentials import describe_active_source
        src = describe_active_source()
        labels = {
            "env": ("✅ Active source: <b>environment variables</b> "
                    "(MODAL_TOKEN_ID / MODAL_TOKEN_SECRET set in "
                    "your shell). Saving keystore values will not "
                    "override env vars while they're set."),
            "modal_toml": ("✅ Active source: <b>~/.modal.toml</b> "
                           "(written by `modal token new`). Saving "
                           "keystore values will not override the "
                           "TOML file while it exists."),
            "keystore": ("✅ Active source: <b>OS keystore</b>. "
                         "These are the tokens the studio will use "
                         "for the next Modal run."),
            "none": ("⚠️ <b>No Modal authentication configured</b> "
                     "anywhere yet. Paste a token-pair below to "
                     "store them in the keystore."),
        }
        self.source_label.setText(labels.get(src.name, ""))

    def _on_save(self):
        from src.cloud.modal_credentials import set_tokens
        tid = self.token_id_edit.text().strip()
        tsec = self.token_secret_edit.text().strip()
        if not tid or not tsec:
            self.status_label.setText(
                "⚠️ Both token ID and token secret are required.")
            return
        ok = set_tokens(tid, tsec)
        if ok:
            self.status_label.setText(
                "✅ Saved to keystore. Tokens will be injected on "
                "the next Modal run.")
            self.token_id_edit.clear()
            self.token_secret_edit.clear()
            self._refresh_status()
        else:
            self.status_label.setText(
                "⚠️ Could not write to keystore. Check OS keychain "
                "permissions and try again.")

    def _on_test(self):
        from src.cloud.modal_credentials import apply_tokens_to_env
        from src.cloud.modal_train import check_setup
        applied = apply_tokens_to_env()
        status = check_setup()
        if status.ready:
            self.status_label.setText(
                f"✅ Modal is ready (auth source applied). "
                f"{'Used keystore tokens.' if applied else ''}")
        else:
            self.status_label.setText(
                f"⚠️ Setup incomplete: {status.help_text()}")
        self._refresh_status()

    def _on_clear(self):
        from src.cloud.modal_credentials import clear_tokens
        confirm = QMessageBox.question(
            self, "Clear keystore tokens",
            "Delete the Modal token-pair from the OS keystore?\n\n"
            "Existing env vars and ~/.modal.toml are not touched. "
            "If those are set, Modal will keep working from them.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok = clear_tokens()
        self.status_label.setText(
            "✅ Keystore tokens cleared." if ok
            else "⚠️ Nothing to clear (or keystore inaccessible).")
        self._refresh_status()


class TrainingToolWindow(QMainWindow):
    """Multi-step wizard for fine-tuning on rephrase data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model Training Studio")
        # Sized for a 1366×768 laptop with room for OS chrome and the
        # CreativeOS launcher behind it. Step 1 is the densest page —
        # if its content overflows, the inner QScrollArea kicks in and
        # the header + nav stay fixed at top/bottom.
        self.resize(820, 600)
        self.setMinimumSize(640, 460)

        self.db_path: Path = DEFAULT_DB_PATH
        self.dataset_jsonl: Optional[Path] = None
        self.worker: Optional[_TrainingWorker] = None
        # Per-corpus selection for the *next* training run. ``None``
        # means "include every collection" (matches pre-feature
        # behavior); a list of keys narrows the export to just those
        # collections via the corpus filter dialog.
        self._selected_collection_keys: Optional[List[str]] = None

        self._init_ui()
        self._refresh_db_summary()
        self._refresh_preset_combo()

    @staticmethod
    def _wrap_in_scroll(page: QWidget) -> QScrollArea:
        """Wrap a step page in a scroll area so it fits small screens.

        ``setWidgetResizable(True)`` lets the page expand horizontally
        with the window while the vertical scrollbar appears only when
        the content exceeds the viewport. The frame is removed so the
        scroll edges blend with the surrounding layout.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        # Header / step indicator
        header = QLabel("Model Training Studio")
        header.setStyleSheet("font-size: 22px; font-weight: bold; color: #1f2937;")
        outer.addWidget(header)

        sub = QLabel(
            "Fine-tune a base model on your collected rephrase data so it "
            "learns your voice and style. Each step is independent — you "
            "can stop at any point and export the dataset for training "
            "elsewhere.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #6b7280; font-size: 12px;")
        outer.addWidget(sub)

        # Each step page is wrapped in its own QScrollArea so users on
        # smaller screens (laptops, side-docked windows) can scroll the
        # content without losing the header or navigation.
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self.stack.addWidget(self._wrap_in_scroll(self._build_step_dataset()))  # 0
        self.stack.addWidget(self._wrap_in_scroll(self._build_step_model()))    # 1
        self.stack.addWidget(self._wrap_in_scroll(self._build_step_train()))    # 2
        self.stack.addWidget(self._wrap_in_scroll(self._build_step_test()))     # 3

        # Footer nav (always visible — never inside the scroll area)
        nav = QHBoxLayout()
        self.back_btn = QPushButton("◀ Back")
        self.back_btn.clicked.connect(self._go_back)
        nav.addWidget(self.back_btn)
        nav.addStretch()
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(self._go_next)
        nav.addWidget(self.next_btn)
        outer.addLayout(nav)

        self._update_nav()

    # ── Step 1: dataset ──

    @staticmethod
    def _section_header(layout: QVBoxLayout, number: str, title: str,
                        description: str = "") -> None:
        """Insert a labelled section divider into the Step 1 layout.

        Step 1 is dense — preset bar, recipe description, source
        picker, corpus actions, synthesis, export — and used to be
        an unlabelled scroll of widgets. Section headers give the
        user a frame for "where am I in the flow" and a one-line
        cue for "what does this group of controls do".
        """
        header = QLabel(
            f"<div style='margin-top:14px;'>"
            f"<span style='font-size:13px;font-weight:bold;color:#1f2937;'>"
            f"{number} · {title}</span></div>")
        layout.addWidget(header)
        if description:
            sub = QLabel(description)
            sub.setWordWrap(True)
            sub.setStyleSheet(
                "color:#6b7280;font-size:11px;"
                "padding:0 0 4px 0;border-bottom:1px solid #e5e7eb;"
                "margin-bottom:6px;")
            layout.addWidget(sub)

    def _build_step_dataset(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            "<div style='font-size:15px;font-weight:bold;color:#111827;'>"
            "Step 1 — Describe &amp; assemble your dataset</div>"
            "<div style='color:#6b7280;font-size:12px;margin-top:2px;'>"
            "Tell the studio what you want to build, then bring in the "
            "writing the model will learn from. The numbered sections "
            "below walk top-to-bottom.</div>"))

        self._section_header(
            layout, "1", "Start from a preset (optional)",
            "Reload a previous recipe — last 3 training runs plus "
            "any presets you saved — or skip ahead to describe a new "
            "model below.")
        # ── Preset bar ──
        # Lets the user load a previous recipe (last 3 trainings + any
        # user-named presets) or save the current wizard state for
        # later. Selecting a preset reloads every field on Steps 1-3,
        # so a recipe round-trips cleanly.
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(280)
        self.preset_combo.setToolTip(
            "Reload a previous recipe — last 3 training runs plus any "
            "presets you saved.")
        self.preset_combo.activated.connect(self._on_preset_picked)
        preset_row.addWidget(self.preset_combo, 1)

        self.save_preset_btn = QPushButton("💾 Save as preset…")
        self.save_preset_btn.setToolTip(
            "Capture the current wizard state (sources, base model, "
            "hyperparameters) and save it under a name you choose.")
        self.save_preset_btn.clicked.connect(self._save_current_as_preset)
        preset_row.addWidget(self.save_preset_btn)

        self.manage_presets_btn = QPushButton("🗑")
        self.manage_presets_btn.setToolTip(
            "Manage saved presets — rename, delete, or reorder them.")
        self.manage_presets_btn.setFixedWidth(36)
        self.manage_presets_btn.clicked.connect(self._open_manage_presets)
        preset_row.addWidget(self.manage_presets_btn)
        layout.addLayout(preset_row)

        self._section_header(
            layout, "2", "What are you building?",
            "Describe the model in plain language and pick the genres "
            "and tones you care about. ✨ Build Training Recipe turns "
            "this into a full plan — source mix, recommended corpora, "
            "format, base model, hyperparameters — that you can apply "
            "with one click.")

        # ── Describe your model ──
        describe_label = QLabel(
            "Tell the studio what you want to build. The recommendation "
            "below will pick the right data sources and an appropriate "
            "training format for you.")
        describe_label.setWordWrap(True)
        describe_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(describe_label)

        desc_row = QHBoxLayout()
        self.describe_edit = QLineEdit()
        self.describe_edit.setPlaceholderText(
            "e.g. \"horror novelist in my voice\", "
            "\"plot generator for sci-fi short stories\", "
            "\"witty writing assistant for screenplays\"…")
        self.describe_edit.textChanged.connect(self._refresh_recommendation)
        desc_row.addWidget(self.describe_edit, 1)

        # Goal & medium pickers — let the user constrain the agent before
        # it builds the recipe.
        self.goal_combo = QComboBox()
        for label, value in (("Auto-detect goal", ""),
                             ("Voice / style imitation", "voice"),
                             ("Plot / story generation", "plot"),
                             ("Voice + plot", "both"),
                             ("Worldbuilding generator", "worldbuilding"),
                             ("Character generator", "character"),
                             ("Q&A / chat assistant", "qa")):
            self.goal_combo.addItem(label, value)
        self.goal_combo.currentIndexChanged.connect(self._refresh_recommendation)
        desc_row.addWidget(QLabel("Goal:"))
        desc_row.addWidget(self.goal_combo)

        self.medium_combo = QComboBox()
        for label, value in (("Auto-detect medium", ""),
                             ("Books / novels", "books"),
                             ("Movies / screenplays", "movies"),
                             ("TV / episodic", "tv"),
                             ("Short fiction", "short"),
                             ("Mixed", "mixed")):
            self.medium_combo.addItem(label, value)
        self.medium_combo.currentIndexChanged.connect(self._refresh_recommendation)
        desc_row.addWidget(QLabel("Medium:"))
        desc_row.addWidget(self.medium_combo)

        layout.addLayout(desc_row)

        # ── Genre picker (multi-select) ──
        # Tick any combination — the agent treats them as additive, so
        # "horror + romance" mixes both genres' corpora and authors.
        # The fuzzy matcher in src.data.genres also catches misspellings
        # in the description above ("horro", "westren", "thrler"…) so
        # the boxes auto-tick from typed text on every recommendation
        # refresh.
        from src.data import genres as _genre_taxonomy
        genre_label = QLabel(
            "<b>Genres</b> "
            "<span style='color:#6b7280;font-size:11px;'>"
            "(check any — multi-select mixes corpora &amp; authors)</span>")
        layout.addWidget(genre_label)
        genre_grid = QHBoxLayout()
        genre_grid.setSpacing(6)
        self.genre_checkboxes: dict = {}
        # Two-row flow so 11 genres fit on a laptop without horizontal scroll.
        col_a = QVBoxLayout()
        col_b = QVBoxLayout()
        for i, key in enumerate(_genre_taxonomy.all_keys()):
            cb = QCheckBox(_genre_taxonomy.display_name(key))
            cb.setToolTip(
                f"{_genre_taxonomy.display_name(key)} — corpora and "
                f"authors are pre-curated. Aliases / misspellings "
                f"include: " +
                ", ".join(_genre_taxonomy.GENRES[key]["aliases"][:6]))
            cb.toggled.connect(self._on_genre_toggled)
            self.genre_checkboxes[key] = cb
            (col_a if i % 2 == 0 else col_b).addWidget(cb)
        col_a.addStretch()
        col_b.addStretch()
        genre_grid.addLayout(col_a)
        genre_grid.addLayout(col_b)
        genre_grid.addStretch()
        layout.addLayout(genre_grid)

        # Tone selector — orthogonal to genre. Defaults to "any tone"
        # (= no filter). Users opt in to narrow the genre's corpus to
        # books matching the chosen tones (grimdark, light, ironic…).
        from src.data import tones as _tone_taxonomy
        tone_label = QLabel(
            "<b>Tone</b> "
            "<span style='color:#6b7280;font-size:11px;'>"
            "(optional — leave all unchecked for any tone)</span>")
        layout.addWidget(tone_label)
        tone_grid = QHBoxLayout()
        tone_grid.setSpacing(6)
        self.tone_checkboxes: dict = {}
        tone_col_a = QVBoxLayout()
        tone_col_b = QVBoxLayout()
        for i, key in enumerate(_tone_taxonomy.all_keys()):
            label = _tone_taxonomy.display_name(key)
            if _tone_taxonomy.is_low_coverage(key):
                label += " ⚠"
            cb = QCheckBox(label)
            tip = _tone_taxonomy.description_for(key)
            if _tone_taxonomy.is_low_coverage(key):
                tip += (" — public-domain coverage is thin for this "
                        "tone; expect a small training set.")
            cb.setToolTip(tip)
            self.tone_checkboxes[key] = cb
            (tone_col_a if i % 2 == 0 else tone_col_b).addWidget(cb)
        tone_col_a.addStretch()
        tone_col_b.addStretch()
        tone_grid.addLayout(tone_col_a)
        tone_grid.addLayout(tone_col_b)
        tone_grid.addStretch()
        layout.addLayout(tone_grid)

        # Action row: ask the agent to refine the recipe with the LLM
        action_row = QHBoxLayout()
        self.build_recipe_btn = QPushButton("✨ Build Training Recipe")
        self.build_recipe_btn.setToolTip(
            "Use the configured LLM (or offline heuristics) to turn your "
            "description into a full training recipe — source mix, "
            "corpora to download, format, base model, hyperparameters.")
        self.build_recipe_btn.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 5px 12px; border-radius: 5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4f46e5; }")
        self.build_recipe_btn.clicked.connect(self._build_recipe_clicked)
        action_row.addWidget(self.build_recipe_btn)

        self.apply_recipe_btn = QPushButton("Apply Recipe")
        self.apply_recipe_btn.setToolTip(
            "Apply every field of the recipe to the wizard — source "
            "checkboxes, recommended corpora to download, base model "
            "and hyperparameters on later steps.")
        self.apply_recipe_btn.setEnabled(False)
        self.apply_recipe_btn.clicked.connect(self._apply_recipe)
        action_row.addWidget(self.apply_recipe_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.recommendation_label = QLabel("")
        self.recommendation_label.setWordWrap(True)
        self.recommendation_label.setStyleSheet(
            "background: #ecfdf5; border: 1px solid #6ee7b7; "
            "border-radius: 6px; padding: 8px 10px; color: #065f46;")
        self.recommendation_label.setVisible(False)
        layout.addWidget(self.recommendation_label)
        self._current_recipe = None

        self._section_header(
            layout, "3", "Training data mix",
            "All your training rows live in one SQLite database "
            "(below). Tick the source types this run should pull "
            "from — different runs can use different subsets without "
            "re-ingesting anything.")

        form = QFormLayout()
        self.db_path_edit = QLineEdit(str(self.db_path))
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_db)
        row = QHBoxLayout()
        row.addWidget(self.db_path_edit, 1)
        row.addWidget(browse_btn)
        form.addRow("Database:", row)
        layout.addLayout(form)

        # ── Source-type selection ──
        sources_label = QLabel("<b>Include these data sources:</b>")
        sources_label.setStyleSheet("padding-top: 8px;")
        layout.addWidget(sources_label)

        self.src_rephrase_cb = QCheckBox("Rephrase suggestions")
        self.src_rephrase_cb.setChecked(True)
        layout.addWidget(self.src_rephrase_cb)

        self.src_chat_writing_cb = QCheckBox("Chat — writing assistance")
        self.src_chat_writing_cb.setChecked(True)
        layout.addWidget(self.src_chat_writing_cb)

        self.src_chat_general_cb = QCheckBox("Chat — general / lookups")
        self.src_chat_general_cb.setChecked(False)
        layout.addWidget(self.src_chat_general_cb)

        self.src_corpus_cb = QCheckBox("Uploaded writing corpus")
        self.src_corpus_cb.setChecked(True)
        layout.addWidget(self.src_corpus_cb)

        self.src_agent_cb = QCheckBox("Other agent outputs")
        self.src_agent_cb.setChecked(False)
        layout.addWidget(self.src_agent_cb)

        self.src_worldbuilding_cb = QCheckBox(
            "Worldbuilding generations (places, factions, lore)")
        self.src_worldbuilding_cb.setChecked(False)
        layout.addWidget(self.src_worldbuilding_cb)

        self.src_character_cb = QCheckBox("Character generations")
        self.src_character_cb.setChecked(False)
        layout.addWidget(self.src_character_cb)

        self.src_plot_cb = QCheckBox("Plot / outline generations")
        self.src_plot_cb.setChecked(False)
        layout.addWidget(self.src_plot_cb)

        # ── Voice / genre tagging for the next corpus upload ──
        # Anything uploaded after these are filled in is tagged with this
        # voice + genre so the model can later be trained selectively
        # (e.g. only `voice=jane-austen` rows). Empty = leave untagged.
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Tag uploads with —"))
        tag_row.addWidget(QLabel("Voice:"))
        self.upload_voice_edit = QLineEdit()
        self.upload_voice_edit.setPlaceholderText(
            "e.g. \"my-voice\", \"jane-austen\"")
        self.upload_voice_edit.setMaximumWidth(180)
        tag_row.addWidget(self.upload_voice_edit)
        tag_row.addWidget(QLabel("Genre:"))
        self.upload_genre_edit = QLineEdit()
        self.upload_genre_edit.setPlaceholderText("e.g. horror, romance")
        self.upload_genre_edit.setMaximumWidth(180)
        tag_row.addWidget(self.upload_genre_edit)
        tag_row.addStretch()
        layout.addLayout(tag_row)

        self._section_header(
            layout, "4", "What's in your training DB right now",
            "Live stats for the database above. Use 🔍 Detailed "
            "quality check for sample passages and a verdict; "
            "🧹 Clean junk rows for retroactive cleanup.")

        # ── Corpus dashboard ──
        # Live at-a-glance panel showing what's in the training DB:
        # row counts, source breakdown, voice-tag rate, junk-row
        # estimate. Inline shortcuts to the full quality check and
        # the cleaner. Refreshes after every corpus-modifying
        # action so the user sees the impact of what they just did.
        self.corpus_dashboard = _CorpusDashboardWidget(
            self.db_path, parent_window=self)
        layout.addWidget(self.corpus_dashboard)

        self._section_header(
            layout, "5", "Bring corpora in & maintain them",
            "Add writing the model will learn from. 📚 Upload Local / "
            "📖 Import from Project pull from your own files; 🌐 Open "
            "Library and 🎯 Smart Pick pull from curated public-domain "
            "catalogs. Other buttons here filter, clean, rebuild, or "
            "audit what's already in the DB.")

        # ── Corpus upload (local files) ──
        corpus_row = QHBoxLayout()
        self.upload_corpus_btn = QPushButton("📚 Upload Local Writing…")
        self.upload_corpus_btn.setToolTip(
            "Pick a text file (or several) of writing you admire. The "
            "studio splits it into passages and turns each into a "
            "training example so the model can imitate that voice.")
        self.upload_corpus_btn.clicked.connect(self._upload_corpus)
        corpus_row.addWidget(self.upload_corpus_btn)

        self.import_project_btn = QPushButton("📖 Import from Project…")
        self.import_project_btn.setToolTip(
            "Pull chapters from one of your Writer Tool projects. Tick "
            "the chapters you want, tag them with a voice and genre, "
            "and they're ingested as corpus rows. Genre-tagged rows are "
            "automatically included only when training a model in that "
            "genre, so a horror project doesn't pollute a romance fine-"
            "tune.")
        self.import_project_btn.clicked.connect(self._open_project_import)
        corpus_row.addWidget(self.import_project_btn)

        self.library_btn = QPushButton("🌐 Open Corpus Library…")
        self.library_btn.setToolTip(
            "Browse curated public-domain corpora to download, or "
            "register your own URLs.")
        self.library_btn.clicked.connect(self._open_corpus_library)
        corpus_row.addWidget(self.library_btn)

        # Per-run corpus picker. Lets the user fine-tune which
        # ingested collections feed *this* training run without
        # touching the underlying data. Defaults to all-checked.
        self.browse_db_btn = QPushButton("🔎 Browse rows…")
        self.browse_db_btn.setToolTip(
            "Open a searchable view of every row in the training "
            "DB. Filter by source type, genre, or corpus; type a "
            "title or phrase to find specific rows; click a row to "
            "see its full source / output / notes.")
        self.browse_db_btn.clicked.connect(self._open_corpus_browser)
        corpus_row.addWidget(self.browse_db_btn)

        self.corpus_filter_btn = QPushButton("✓ All corpora")
        self.corpus_filter_btn.setToolTip(
            "Choose which ingested corpus collections feed the next "
            "training run. Default: all included. Pick a subset to "
            "(e.g.) train only on your project chapters without "
            "re-ingesting anything.")
        self.corpus_filter_btn.clicked.connect(self._open_corpus_filter)
        corpus_row.addWidget(self.corpus_filter_btn)

        # Retro-clean button: walk the existing DB and apply the same
        # text-cleaner that all new ingestions go through. Existing
        # data ingested before the cleaner existed (legacy PG dumps,
        # scraped HF rows with stray boilerplate) gets scrubbed in
        # place. Junk rows are deleted; their stats are reported.
        self.clean_corpus_btn = QPushButton("🧹 Clean existing rows…")
        self.clean_corpus_btn.setToolTip(
            "Scan every corpus / character / worldbuilding / plot row "
            "in your training DB. Drop rows that match junk signatures "
            "(boilerplate, refusal templates, tool-call JSON, page "
            "numbers, section headings, …). Keeps a backup of every "
            "deleted row's id+text so you can undo if needed. Safe to "
            "run multiple times — already-clean rows are no-ops.")
        self.clean_corpus_btn.clicked.connect(self._open_clean_corpus_dialog)
        corpus_row.addWidget(self.clean_corpus_btn)

        # Rebuild button: drops every row that came through the catalog
        # downloader (notes match ``corpus_id=…``), preserving user
        # uploads, project imports, and character/worldbuilding/plot
        # rows. Use after a splitter/cleaner upgrade to re-ingest with
        # the new logic.
        self.rebuild_corpus_btn = QPushButton("♻ Rebuild downloads…")
        self.rebuild_corpus_btn.setToolTip(
            "Drop every row that came through the catalog downloader "
            "so you can re-download with the current splitter. Manual "
            "uploads, project imports, and character/worldbuilding/"
            "plot rows are preserved. A backup JSONL is written first.")
        self.rebuild_corpus_btn.clicked.connect(
            self._open_rebuild_corpus_dialog)
        corpus_row.addWidget(self.rebuild_corpus_btn)

        # Quality preview from Step 1 — runs the same dialog that
        # gates Start Training, but as a standalone tool so the
        # user can iterate on corpus picks before committing to
        # the recipe + training step. Same button on Step 3 next
        # to Start Training.
        self.check_quality_step1_btn = QPushButton("🔍 Check quality")
        self.check_quality_step1_btn.setToolTip(
            "Preview what the trainer would see for the current "
            "corpus selection — row counts, vocab diversity, "
            "sample passages, and a verdict. Use it to iterate "
            "on corpus / genre / tone picks before going to "
            "Step 3.")
        self.check_quality_step1_btn.clicked.connect(
            self._open_corpus_quality_check)
        corpus_row.addWidget(self.check_quality_step1_btn)

        # Variability prune — separate from junk cleaning. Detects
        # exact duplicates, repeated openers, and dominant sources
        # in the existing corpus, shows stats per category, and
        # drops only what the user approves.
        self.prune_corpus_btn = QPushButton("📊 Prune for variability…")
        self.prune_corpus_btn.setToolTip(
            "Audit the corpus for redundancy: exact duplicates, "
            "oversampled openers, dominant sources. Each category "
            "is shown with stats and approved separately. Different "
            "from Clean (which removes junk) — this removes "
            "redundancy.")
        self.prune_corpus_btn.clicked.connect(
            self._open_variability_prune_dialog)
        corpus_row.addWidget(self.prune_corpus_btn)
        corpus_row.addStretch()
        layout.addLayout(corpus_row)
        # NOTE: Smart Pick used to live here; it's now reachable
        # from inside the Corpus Library dialog (download flow)
        # since smart-picking only makes sense when you're picking
        # what to download.

        self._section_header(
            layout, "6", "Synthesize new training pairs",
            "Use a configured LLM to manufacture supervision data "
            "from what you already have. Pacing pairs teach genre-"
            "appropriate rhythm; rephrase pairs teach the model to "
            "rewrite in YOUR voice. Each rewrite is verified — only "
            "kept if it actually moved toward the target.")

        # Pacing-pair synthesis: walk corpus rows, ask the configured
        # LLM to rewrite each toward a target genre's CONLIT baseline,
        # verify the rewrite actually moved closer, and save the kept
        # ones as plot/pacing training rows. CONLIT is only a
        # statistical reference (no full text), but its baselines are
        # excellent supervision targets — that's how its data turns
        # into training data.
        pacing_row = QHBoxLayout()
        self.pacing_pairs_btn = QPushButton(
            "📊 Generate pacing training pairs (CONLIT)…")
        self.pacing_pairs_btn.setToolTip(
            "Use the configured LLM to rewrite corpus passages toward "
            "a target genre's CONLIT pacing baseline. Each rewrite is "
            "verified — only kept if its avg sentence length actually "
            "moves closer to the genre norm. Resulting rows train a "
            "model to do genre-aware pacing rewrites.")
        self.pacing_pairs_btn.clicked.connect(
            lambda _=False: self._open_pacing_pairs_dialog())
        pacing_row.addWidget(self.pacing_pairs_btn)

        # Rephrase-pair synthesis: walk corpus rows, ask the LLM to
        # paraphrase each, and verify the rewrite is "different
        # enough but same meaning" via bigram-overlap + length gates.
        # Best free way to produce voice-specific rephrase training
        # data — the model learns to rephrase IN the user's voice.
        self.rephrase_pairs_btn = QPushButton(
            "✏ Synthesize rephrase training pairs…")
        self.rephrase_pairs_btn.setToolTip(
            "Use the configured LLM to paraphrase corpus passages. "
            "Each paraphrase is verified — only kept when it's "
            "genuinely a rephrase (bigram overlap < 0.7, length "
            "within ±30%). Ideal supervision for training a "
            "rephrase model that uses YOUR voice as the rephrase "
            "target.")
        self.rephrase_pairs_btn.clicked.connect(
            lambda _=False: self._open_rephrase_pairs_dialog())
        pacing_row.addWidget(self.rephrase_pairs_btn)
        pacing_row.addStretch()
        layout.addLayout(pacing_row)

        self._section_header(
            layout, "7", "Export dataset (optional)",
            "Most users skip this and just click Start Training on "
            "Step 3 — the trainer reads from the DB directly. Export "
            "is for fine-tuning elsewhere (Axolotl, TRL, an external "
            "GPU box) and produces a JSONL file the standard "
            "HuggingFace pipelines accept.")

        self.db_summary = QLabel("")
        self.db_summary.setStyleSheet(
            "padding: 10px; background-color: #f9fafb; border-radius: 6px;")
        self.db_summary.setWordWrap(True)
        layout.addWidget(self.db_summary)

        export_row = QHBoxLayout()
        self.export_btn = QPushButton("📤 Export Dataset (JSONL)")
        self.export_btn.setToolTip(
            "Export the dataset for fine-tuning elsewhere (e.g. on a "
            "machine with a GPU). The JSONL file is the standard input "
            "for HuggingFace Trainer / Axolotl / TRL pipelines.")
        self.export_btn.clicked.connect(self._export_dataset)
        export_row.addWidget(self.export_btn)

        self.format_combo = QComboBox()
        self.format_combo.addItem("Instruction (Alpaca, positive only)", "instruction")
        self.format_combo.addItem("Chat (ShareGPT, positive only)", "chat")
        self.format_combo.addItem("DPO preference pairs (chosen/rejected)", "dpo")
        self.format_combo.addItem("Raw row dump (every row + ratings)", "raw")
        export_row.addWidget(self.format_combo)
        export_row.addStretch()
        layout.addLayout(export_row)

        self.min_rating_combo = QComboBox()
        self.min_rating_combo.addItem("Include ⭐ Excellent + 👍 Good only", "good")
        self.min_rating_combo.addItem("Include ⭐ Excellent only", "excellent")
        self.min_rating_combo.addItem("Include all ratings except 👎/✖", "neutral")
        self.min_rating_combo.setToolTip(
            "Filter rows by minimum rating. Negative ratings are NEVER "
            "included in SFT exports — they're only used to build DPO "
            "preference pairs.")
        export_row.addWidget(QLabel("Min rating:"))
        export_row.addWidget(self.min_rating_combo)

        layout.addStretch()
        return page

    def _browse_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select rephrase database",
            str(self.db_path.parent), "SQLite (*.db);;All Files (*)")
        if path:
            self.db_path_edit.setText(path)
            self.db_path = Path(path)
            self._refresh_db_summary()

    def _refresh_db_summary(self):
        try:
            db = RephraseDatabase(self.db_path)
            stats = db.stats()
            counts = db.counts_by_source()
            top_genres = ", ".join(
                f"{k} ({v})" for k, v in list(stats["by_genre"].items())[:3])
            by_rating = stats.get("by_rating", {})
            ratings_line = " &nbsp;·&nbsp; ".join(
                f"{lbl} {by_rating.get(key, 0)}"
                for key, lbl in (("excellent", "⭐"), ("good", "👍"),
                                 ("neutral", "•"), ("poor", "👎"),
                                 ("bad", "✖"))
            )
            dpo = stats.get("dpo_pairs_available", 0)
            sources_line = " &nbsp;·&nbsp; ".join(
                f"{label}: <b>{counts.get(key, 0)}</b>" for label, key in (
                    ("Rephrase", SOURCE_REPHRASE),
                    ("Chat (writing)", SOURCE_CHAT_WRITING),
                    ("Chat (general)", SOURCE_CHAT_GENERAL),
                    ("Corpus", SOURCE_CORPUS),
                    ("Agent", SOURCE_AGENT),
                    ("Worldbuilding", SOURCE_WORLDBUILDING),
                    ("Character", SOURCE_CHARACTER),
                    ("Plot", SOURCE_PLOT),
                ))
            # Corpus-aware base model recommendation. Uses the same logic
            # the Model Builder Agent applies, so what's shown here and
            # what the recipe ends up picking are consistent. Only good+
            # rows are eligible for SFT, so use that as the size signal.
            eligible = (by_rating.get("excellent", 0)
                        + by_rating.get("good", 0))
            rec_html = ""
            try:
                from src.ai.model_builder_agent import recommend_base_for_corpus
                # Best-effort intent inference from the user's free-text
                # description and goal combo — same signals the agent uses.
                intent_hint = (self.goal_combo.currentData() or "voice"
                               if hasattr(self, 'goal_combo') else "voice")
                rec_id, rec_why = recommend_base_for_corpus(
                    eligible, intent=intent_hint)
                if rec_id:
                    rec_html = (
                        f"<br>💡 <b>Recommended base:</b> "
                        f"<code>{rec_id}</code><br>"
                        f"<span style='color:#6b7280;font-size:11px;'>"
                        f"{rec_why}</span>")
            except Exception:
                pass

            self.db_summary.setText(
                f"<b>{stats['total']}</b> rows collected "
                f"({stats['accepted']} accepted, "
                f"<b>{eligible}</b> eligible for training)<br>"
                f"By source: {sources_line}<br>"
                f"Ratings: {ratings_line}<br>"
                f"DPO pairs available: <b>{dpo}</b><br>"
                f"Top genres: {top_genres or '(none yet)'}"
                f"{rec_html}<br>"
                f"<small>Path: {self.db_path}</small>")
        except Exception as e:
            self.db_summary.setText(f"Could not read database: {e}")
        # Keep the dashboard panel in sync with the (possibly
        # changed) DB. Cheap — same DB scan we just ran, plus one
        # more SQL query for junk-row sampling.
        if hasattr(self, 'corpus_dashboard'):
            try:
                self.corpus_dashboard.refresh()
            except Exception:
                pass

    def _selected_source_types(self) -> list:
        """Return the source_types corresponding to the checked boxes."""
        out = []
        if self.src_rephrase_cb.isChecked():       out.append(SOURCE_REPHRASE)
        if self.src_chat_writing_cb.isChecked():   out.append(SOURCE_CHAT_WRITING)
        if self.src_chat_general_cb.isChecked():   out.append(SOURCE_CHAT_GENERAL)
        if self.src_corpus_cb.isChecked():         out.append(SOURCE_CORPUS)
        if self.src_agent_cb.isChecked():          out.append(SOURCE_AGENT)
        if self.src_worldbuilding_cb.isChecked():  out.append(SOURCE_WORLDBUILDING)
        if self.src_character_cb.isChecked():      out.append(SOURCE_CHARACTER)
        if self.src_plot_cb.isChecked():           out.append(SOURCE_PLOT)
        return out

    # ── Preset capture / apply ──

    def _capture_current_preset(self, name: str = "",
                                is_recent: bool = False):
        """Snapshot the current wizard state into a TrainingPreset.

        Reads every Step 1-3 widget so a later ``_apply_preset`` can
        round-trip the recipe. Widgets that haven't been built yet
        (e.g. on first call before Step 2 exists) fall back to their
        dataclass defaults — capture is safe at any point.
        """
        from src.config.training_presets import TrainingPreset

        def _txt(name, default=""):
            w = getattr(self, name, None)
            return w.text().strip() if w is not None else default

        def _combo_data(name, default=""):
            w = getattr(self, name, None)
            return (w.currentData() if w is not None else default) or default

        def _combo_text(name, default=""):
            w = getattr(self, name, None)
            return (w.currentText().strip() if w is not None else default)

        def _spin(name, default):
            w = getattr(self, name, None)
            return w.value() if w is not None else default

        def _check(name, default=False):
            w = getattr(self, name, None)
            return w.isChecked() if w is not None else default

        return TrainingPreset(
            name=name,
            is_recent=is_recent,
            description=_txt("describe_edit"),
            goal=_combo_data("goal_combo", ""),
            medium=_combo_data("medium_combo", ""),
            src_rephrase=_check("src_rephrase_cb", True),
            src_chat_writing=_check("src_chat_writing_cb", True),
            src_chat_general=_check("src_chat_general_cb", False),
            src_corpus=_check("src_corpus_cb", True),
            src_agent=_check("src_agent_cb", False),
            src_worldbuilding=_check("src_worldbuilding_cb", False),
            src_character=_check("src_character_cb", False),
            src_plot=_check("src_plot_cb", False),
            upload_voice=_txt("upload_voice_edit"),
            upload_genre=_txt("upload_genre_edit"),
            export_format=_combo_data("format_combo", "instruction"),
            export_min_rating=_combo_data("min_rating_combo", "good"),
            base_model=_combo_text("base_model_combo",
                                   "google/gemma-2-2b-it"),
            continue_from=_combo_data("continue_combo", ""),
            model_name=_txt("name_edit", "my-voice-v1"),
            epochs=int(_spin("epochs_spin", 2)),
            learning_rate=float(_spin("lr_spin", 2e-4)),
            batch_size=int(_spin("batch_spin", 1)),
            lora_r=int(_spin("lora_r_spin", 8)),
            use_qlora=_check("qlora_cb", False),
            train_min_rating=_combo_data("train_min_rating", "good"),
        )

    def _apply_preset(self, preset) -> None:
        """Push every preset field back into the wizard widgets.

        Idempotent — safe to call repeatedly. Missing widgets are
        skipped silently so the helper works even before later steps
        have been built (during the constructor, etc.).
        """
        def _set_text(name, value):
            w = getattr(self, name, None)
            if w is not None:
                w.setText(value)

        def _set_combo_data(name, value):
            w = getattr(self, name, None)
            if w is None:
                return
            for i in range(w.count()):
                if w.itemData(i) == value:
                    w.setCurrentIndex(i)
                    return
            # Editable combos: fall through to typing the value
            if w.isEditable() and value:
                w.setEditText(str(value))

        def _set_combo_text(name, value):
            w = getattr(self, name, None)
            if w is None or not value:
                return
            idx = w.findText(value)
            if idx >= 0:
                w.setCurrentIndex(idx)
            elif w.isEditable():
                w.setEditText(value)

        def _set_check(name, value):
            w = getattr(self, name, None)
            if w is not None:
                w.setChecked(bool(value))

        def _set_spin(name, value):
            w = getattr(self, name, None)
            if w is not None:
                w.setValue(value)

        # Step 1
        _set_text("describe_edit", preset.description)
        _set_combo_data("goal_combo", preset.goal)
        _set_combo_data("medium_combo", preset.medium)
        _set_check("src_rephrase_cb", preset.src_rephrase)
        _set_check("src_chat_writing_cb", preset.src_chat_writing)
        _set_check("src_chat_general_cb", preset.src_chat_general)
        _set_check("src_corpus_cb", preset.src_corpus)
        _set_check("src_agent_cb", preset.src_agent)
        _set_check("src_worldbuilding_cb", preset.src_worldbuilding)
        _set_check("src_character_cb", preset.src_character)
        _set_check("src_plot_cb", preset.src_plot)
        _set_text("upload_voice_edit", preset.upload_voice)
        _set_text("upload_genre_edit", preset.upload_genre)
        _set_combo_data("format_combo", preset.export_format)
        _set_combo_data("min_rating_combo", preset.export_min_rating)
        # Step 2
        _set_combo_text("base_model_combo", preset.base_model)
        _set_combo_data("continue_combo", preset.continue_from)
        # Step 3
        _set_text("name_edit", preset.model_name)
        _set_spin("epochs_spin", int(preset.epochs))
        _set_spin("lr_spin", float(preset.learning_rate))
        _set_spin("batch_spin", int(preset.batch_size))
        _set_spin("lora_r_spin", int(preset.lora_r))
        _set_check("qlora_cb", bool(getattr(preset, "use_qlora", False)))
        _set_combo_data("train_min_rating", preset.train_min_rating)

        # Refresh derived state (recommendation banner reads everything
        # we just set, so it'd be stale otherwise).
        if hasattr(self, '_refresh_step2_recommendation'):
            self._refresh_step2_recommendation()
        if hasattr(self, '_refresh_db_summary'):
            self._refresh_db_summary()

    # ── Preset bar wiring ──

    def _refresh_preset_combo(self) -> None:
        """Rebuild the dropdown contents from the on-disk presets."""
        if not hasattr(self, 'preset_combo'):
            return
        from src.config.training_presets import (
            load_recent, load_saved, _humanize_age,
        )
        self.preset_combo.blockSignals(True)
        try:
            self.preset_combo.clear()
            self.preset_combo.addItem("— pick a preset —", None)
            recents = load_recent()
            saved = load_saved()
            if recents:
                self.preset_combo.insertSeparator(self.preset_combo.count())
                for p in recents:
                    age = _humanize_age(p.timestamp)
                    label = f"⏱ {p.name}" + (f"  ({age})" if age else "")
                    self.preset_combo.addItem(label, ("recent", p.name))
            if saved:
                self.preset_combo.insertSeparator(self.preset_combo.count())
                for p in saved:
                    self.preset_combo.addItem(f"⭐ {p.name}",
                                              ("saved", p.name))
            if not recents and not saved:
                self.preset_combo.addItem(
                    "(no presets yet — train once or save below)", None)
        finally:
            self.preset_combo.blockSignals(False)

    def _on_preset_picked(self, index: int) -> None:
        """Load whichever preset the user just selected."""
        data = self.preset_combo.itemData(index)
        if not data:
            return
        kind, name = data
        from src.config.training_presets import find_preset
        preset = find_preset(name, recent=(kind == "recent"))
        if preset is None:
            return
        self._apply_preset(preset)
        # Reset selection back to the placeholder so the same preset
        # can be re-picked later (and so the activation feels like an
        # action rather than a sticky filter).
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _save_current_as_preset(self) -> None:
        """Prompt for a name and persist the current wizard state."""
        from PyQt6.QtWidgets import QInputDialog
        from src.config.training_presets import save_named, load_saved
        existing = {p.name for p in load_saved()}
        default_name = (self.name_edit.text().strip()
                        if hasattr(self, 'name_edit')
                        else "my-preset")
        suggested = default_name or "my-preset"
        if suggested in existing:
            n = 2
            while f"{suggested}-v{n}" in existing:
                n += 1
            suggested = f"{suggested}-v{n}"
        name, ok = QInputDialog.getText(
            self, "Save preset",
            "Name this preset (you'll be able to reload it later):",
            text=suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if name in existing:
            reply = QMessageBox.question(
                self, "Overwrite?",
                f"A preset named '{name}' already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        preset = self._capture_current_preset(name=name, is_recent=False)
        save_named(preset)
        self._refresh_preset_combo()
        QMessageBox.information(
            self, "Preset saved",
            f"Saved '{name}'. Pick it from the Preset combo next time "
            f"to reload every Step 1-3 setting in one click.")

    def _open_manage_presets(self) -> None:
        """Open a small dialog to remove user-saved presets."""
        dlg = _ManagePresetsDialog(self)
        dlg.exec()
        # User may have deleted things — refresh the dropdown either way.
        self._refresh_preset_combo()

    def selected_genres(self) -> list:
        """Return the canonical genre keys currently checked on Step 1."""
        if not hasattr(self, 'genre_checkboxes'):
            return []
        return [k for k, cb in self.genre_checkboxes.items() if cb.isChecked()]

    def selected_tones(self) -> list:
        """Return the canonical tone keys checked on Step 1.

        Empty list = user opted out of tone filtering — call sites
        should pass through the unfiltered genre selection in that
        case.
        """
        if not hasattr(self, 'tone_checkboxes'):
            return []
        return [k for k, cb in self.tone_checkboxes.items() if cb.isChecked()]

    def _on_genre_toggled(self, _checked: bool) -> None:
        """When the user toggles a genre, refresh the recommendation card.

        We deliberately *don't* mutate the description text — the user's
        words are theirs. The genre tick contributes to the recipe via
        ``selected_genres()`` instead.
        """
        if hasattr(self, '_refresh_recommendation'):
            self._refresh_recommendation()
        if hasattr(self, '_refresh_step2_recommendation'):
            self._refresh_step2_recommendation()

    def _sync_genres_from_description(self, text: str) -> None:
        """Auto-tick genre checkboxes whose aliases / misspellings match
        the description. Called from ``_refresh_recommendation`` so the
        UI stays in sync as the user types.

        Uses the fuzzy matcher in src.data.genres so "horro story" or
        "westren ranch" still light up the right boxes.
        """
        if not hasattr(self, 'genre_checkboxes'):
            return
        try:
            from src.data.genres import match_genres
            detected = set(match_genres(text or ""))
        except Exception:
            detected = set()
        for key, cb in self.genre_checkboxes.items():
            if key in detected and not cb.isChecked():
                # Block signals so we don't recursively re-fire
                # _refresh_recommendation while the user is mid-type.
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)

    def _refresh_recommendation(self):
        """Read the user's free-text description and steer source-type
        checkboxes + suggest a training format. Pure offline keyword
        matching today; can be swapped with an LLM call later.
        """
        # Sync the genre checkboxes from typed text (handles
        # misspellings / aliases via the fuzzy matcher).
        self._sync_genres_from_description(self.describe_edit.text())

        text = self.describe_edit.text().lower().strip()
        if not text:
            self.recommendation_label.setVisible(False)
            return

        # Heuristics keyed on intent
        wants_voice = any(k in text for k in
                          ("my voice", "in my voice", "imitate", "style"))
        wants_chat = any(k in text for k in
                         ("chat", "assistant", "answer", "respond"))
        wants_writing = any(k in text for k in
                            ("write", "novel", "story", "prose", "fiction",
                             "poetry", "horror", "romance", "mystery",
                             "fantasy", "scifi", "thriller"))
        wants_dpo = any(k in text for k in
                        ("avoid", "don't", "do not", "preferences",
                         "preference", "dislike"))
        wants_worldbuilding = any(k in text for k in
                                  ("worldbuilding", "world building", "lore",
                                   "faction", "kingdom", "magic system",
                                   "setting"))
        wants_character = any(k in text for k in
                              ("character", "protagonist", "antagonist",
                               "love interest", "backstory", "cast"))

        # Steer checkboxes (without overriding the user's manual choice
        # too hard — only check additional sources, don't uncheck)
        if wants_voice or wants_writing:
            self.src_rephrase_cb.setChecked(True)
            self.src_corpus_cb.setChecked(True)
            self.src_chat_writing_cb.setChecked(True)
        if wants_chat:
            self.src_chat_writing_cb.setChecked(True)
            if not wants_writing:
                self.src_chat_general_cb.setChecked(True)
        if wants_worldbuilding:
            self.src_worldbuilding_cb.setChecked(True)
            self.src_agent_cb.setChecked(True)
        if wants_character:
            self.src_character_cb.setChecked(True)
            self.src_agent_cb.setChecked(True)

        # Suggest format
        if wants_dpo:
            suggested_fmt = "DPO preference pairs (chosen/rejected)"
        elif wants_chat and not wants_voice:
            suggested_fmt = "Chat (ShareGPT)"
        else:
            suggested_fmt = "Instruction (Alpaca)"

        sources_text = []
        if self.src_rephrase_cb.isChecked():       sources_text.append("rephrase")
        if self.src_chat_writing_cb.isChecked():   sources_text.append("writing-chat")
        if self.src_chat_general_cb.isChecked():   sources_text.append("general-chat")
        if self.src_corpus_cb.isChecked():         sources_text.append("uploaded corpus")
        if self.src_worldbuilding_cb.isChecked():  sources_text.append("worldbuilding")
        if self.src_character_cb.isChecked():      sources_text.append("character")
        if self.src_plot_cb.isChecked():           sources_text.append("plot")

        self.recommendation_label.setVisible(True)
        self.recommendation_label.setText(
            f"<b>Recommendation:</b> use {', '.join(sources_text) or 'no sources?'}; "
            f"export as <b>{suggested_fmt}</b>. "
            f"You can still tweak any of the checkboxes below.")

    # ── Corpus upload ──

    def _upload_corpus(self):
        """Open the upload dialog — handles single files, multi-files,
        and zip archives uniformly with metadata tagging.
        """
        # Pre-fill voice/genre from the Step 1 inline fields when set
        # (the dialog has its own copies but it's friendlier to seed
        # them from what the user already typed).
        seeded_voice = (self.upload_voice_edit.text().strip()
                        if hasattr(self, 'upload_voice_edit') else "")
        seeded_genre = (self.upload_genre_edit.text().strip()
                        if hasattr(self, 'upload_genre_edit') else "")
        dlg = _UploadCorpusDialog(self.db_path,
                                  seeded_voice=seeded_voice,
                                  seeded_genre=seeded_genre, parent=self)
        dlg.exec()
        self._refresh_db_summary()

    def _build_recipe_clicked(self):
        """Run the model-builder agent and show its recipe."""
        from src.ai.model_builder_agent import build_recipe
        desc = self.describe_edit.text().strip()
        goal = self.goal_combo.currentData() or ""
        medium = self.medium_combo.currentData() or ""
        # Explicit genre ticks — additive; the agent treats each as
        # equally weighted. If the user typed nothing but ticked some
        # boxes, that alone is a valid signal.
        ticked_genres = self.selected_genres()
        if not desc and not goal and not medium and not ticked_genres:
            QMessageBox.information(
                self, "Describe Your Model",
                "Type a short description, pick a Goal/Medium, or tick "
                "one or more Genres so the agent has something to "
                "work with.")
            return

        # Folding ticked genres into the description means the existing
        # heuristic + LLM path picks them up uniformly with typed text.
        # We keep the user's original text intact; the agent doesn't
        # need to know which path supplied each genre.
        full_desc = desc
        if ticked_genres:
            full_desc = (full_desc + " " + " ".join(ticked_genres)).strip()
        # Same trick for tones — the agent doesn't have a separate
        # tone path, so folding the tone keys (or their display names)
        # into the description lets the LLM pick them up. Empty list =
        # opt-out, no-op.
        ticked_tones = self.selected_tones()
        if ticked_tones:
            full_desc = (full_desc + " " + " ".join(ticked_tones)).strip()

        # Pass the user's eligible-row count so the agent picks a base
        # model whose size matches their data. Falls back to 0 (i.e.
        # "use default sweet spot") if the DB is unreadable.
        eligible = 0
        try:
            db = RephraseDatabase(self.db_path)
            br = db.stats().get("by_rating", {})
            eligible = br.get("excellent", 0) + br.get("good", 0)
        except Exception:
            pass

        recipe = build_recipe(full_desc, goal_hint=goal, medium_hint=medium,
                              corpus_size=eligible)
        # Apply the deterministic tone filter to the agent's output —
        # the description-folding above gives the LLM a hint, but
        # filter_corpora_by_tones is what actually narrows the
        # recommended-corpora list to tone-matching books. The filter
        # has a definitive-minimum floor so the recipe always lists
        # enough books to train on, even for thin (genre × tone)
        # combos that needed augmentation.
        if ticked_tones and getattr(recipe, "recommended_corpora", None):
            from src.data.tones import filter_corpora_by_tones
            tone_result = filter_corpora_by_tones(
                list(recipe.recommended_corpora), ticked_tones)
            recipe.recommended_corpora = tone_result.corpus_ids
            # Stash so the recipe-render step can surface the status.
            self._last_tone_filter_result = tone_result
        self._current_recipe = recipe

        # Render the recipe as a friendly card
        from src.data.corpus_catalog import CATALOG
        cat_by_id = {e.id: e for e in CATALOG}

        def _corpus_block(ids, header):
            lines = "<br>&nbsp;&nbsp;• ".join(
                f"<b>{cat_by_id[c].name}</b>"
                f" <span style='color:#6b7280'>({cat_by_id[c].license})</span>"
                for c in ids if c in cat_by_id)
            if not lines:
                return ""
            return f"{header}:<br>&nbsp;&nbsp;• {lines}<br>"

        corp_block = _corpus_block(recipe.recommended_corpora,
                                   "Recommended corpora")
        craft_block = _corpus_block(recipe.recommended_craft,
                                    "Genre writing-craft documents")

        # Authors + comps panel — comp titles are PD-only; users
        # interested in modern comps can register them through Add
        # Custom URL with attestation.
        authors_html = ""
        if recipe.recommended_authors:
            authors_html = (
                "Touchstone authors:<br>&nbsp;&nbsp;• "
                + "<br>&nbsp;&nbsp;• ".join(recipe.recommended_authors[:8])
                + "<br>")
        comps_html = ""
        if recipe.recommended_comps:
            comps_html = (
                "Comps (public-domain reference):<br>&nbsp;&nbsp;• "
                + "<br>&nbsp;&nbsp;• ".join(recipe.recommended_comps[:6])
                + "<br>")

        # CONLIT genre baselines — when a canonical genre is detected
        # AND the user has loaded the CONLIT dataset, surface Piper's
        # contemporary-literature stats for that genre as a comparison
        # point ("mystery's avg sentence length is 13.8 words; horror
        # corpora skew longer at ~16"). Empty when CONLIT isn't loaded
        # or the genre isn't in the CONLIT taxonomy.
        conlit_html = ""
        try:
            from src.data.conlit_loader import (
                get_genre_stats_cached, summary_lines,
            )
            genre_stats = get_genre_stats_cached()
            if genre_stats and recipe.detected_genres:
                # Surface the first detected genre that CONLIT covers.
                # (Mystery, scifi, romance, literary — horror, western,
                # fantasy aren't in CONLIT.)
                blocks = []
                for g in recipe.detected_genres:
                    lines = summary_lines(genre_stats, g)
                    if lines:
                        blocks.append(
                            "<br>&nbsp;&nbsp;".join(lines))
                        # Only show the first match — multi-genre recipes
                        # would otherwise produce a wall of stats.
                        break
                if blocks:
                    conlit_html = (
                        "<br>📊 <b>CONLIT genre baseline</b> "
                        "(contemporary lit reference, "
                        "Piper et al.):<br>&nbsp;&nbsp;"
                        + blocks[0] + "<br>")
        except Exception:
            pass

        genres_line = ""
        if recipe.detected_genres:
            from src.data.genres import display_name
            names = ", ".join(display_name(g) for g in recipe.detected_genres)
            genres_line = f"Genres: <b>{names}</b><br>"

        oversample_line = ""
        if recipe.user_voice_oversample > 1:
            oversample_line = (
                f"User-voice oversample: <b>{recipe.user_voice_oversample}×"
                f"</b> "
                f"<span style='color:#6b7280;font-size:11px;'>"
                f"(your rephrase rows get repeated so the trained model "
                f"learns *your* voice as the dominant one)"
                f"</span><br>")

        # Tone-filter status line — shows the user *why* the corpus
        # list looks the way it does. We only show it when a non-
        # trivial fallback fired, so the common case (no tones picked
        # OR clean intersection) stays uncluttered.
        tone_status_line = ""
        tone_result = getattr(self, '_last_tone_filter_result', None)
        if (tone_result is not None
                and tone_result.status not in ("opted_out", "intersection")):
            color = ("#b45309"
                     if tone_result.status == "augmented_with_genre_pool"
                     else "#6b7280")
            tone_status_line = (
                f"<span style='color:{color};font-size:11px;'>"
                f"Tone filter: {tone_result.explain()}"
                f"</span><br>")

        html = (
            f"<b>Recipe</b><br>"
            f"Intent: <b>{recipe.intent}</b> · "
            f"Medium: <b>{recipe.medium}</b> · "
            f"Format: <b>{recipe.export_format}</b><br>"
            f"{genres_line}"
            f"Sources: {', '.join(recipe.source_types) or '—'}<br>"
            f"Base model: <code>{recipe.base_model}</code><br>"
            f"Epochs: {recipe.epochs} · "
            f"LR: {recipe.learning_rate:g} · "
            f"LoRA r: {recipe.lora_r}<br>"
            f"{oversample_line}"
            f"{tone_status_line}"
            f"<br>{corp_block}"
            f"{craft_block}"
            f"{authors_html}"
            f"{comps_html}"
            f"{conlit_html}"
            f"<i>{recipe.summary}</i>")
        self.recommendation_label.setText(html)
        self.recommendation_label.setVisible(True)
        self.apply_recipe_btn.setEnabled(True)

    def _apply_recipe(self):
        """Push every field of the current recipe into the wizard widgets."""
        rec = self._current_recipe
        if rec is None:
            return
        # Source-type checkboxes
        self.src_rephrase_cb.setChecked(SOURCE_REPHRASE in rec.source_types)
        self.src_chat_writing_cb.setChecked(SOURCE_CHAT_WRITING in rec.source_types)
        self.src_chat_general_cb.setChecked(SOURCE_CHAT_GENERAL in rec.source_types)
        self.src_corpus_cb.setChecked(SOURCE_CORPUS in rec.source_types)
        self.src_agent_cb.setChecked(SOURCE_AGENT in rec.source_types)
        self.src_worldbuilding_cb.setChecked(SOURCE_WORLDBUILDING in rec.source_types)
        self.src_character_cb.setChecked(SOURCE_CHARACTER in rec.source_types)
        self.src_plot_cb.setChecked(SOURCE_PLOT in rec.source_types)
        # Base model + hyperparams
        self.base_model_combo.setEditText(rec.base_model)
        self.epochs_spin.setValue(int(rec.epochs))
        self.lr_spin.setValue(float(rec.learning_rate))
        self.lora_r_spin.setValue(int(rec.lora_r))
        # Format
        for i in range(self.format_combo.count()):
            if self.format_combo.itemData(i) == rec.export_format:
                self.format_combo.setCurrentIndex(i)
                break
        # Min-rating filter — leave at user default; recipe sets a floor
        for i in range(self.train_min_rating.count()):
            if self.train_min_rating.itemData(i) == rec.min_rating:
                self.train_min_rating.setCurrentIndex(i)
                break

        # The recipe just bumped the base model + intent; sync the
        # banner so what shows on Step 2 matches the recipe.
        self._refresh_step2_recommendation()

        QMessageBox.information(
            self, "Recipe Applied",
            f"Settings updated. To pull the recommended corpora, click "
            f"'🌐 Open Corpus Library' and download the {len(rec.recommended_corpora)} "
            f"items the agent suggested.")

    def _open_corpus_library(self):
        """Show the catalog/registry browser so the user can pick or add
        a corpus to download. Each download runs through the adapter
        pipeline and lands as ``corpus`` rows in the unified DB.

        Plumbs the user's current intent + genres + tones into the
        dialog so its Smart Pick button has the context it needs to
        recommend complementary entries.
        """
        intent = ""
        recipe = getattr(self, '_current_recipe', None)
        if recipe is not None:
            intent = (getattr(recipe, "intent", "") or "").lower()
        if not intent:
            try:
                intent = self._infer_intent_from_db()
            except Exception:
                intent = "general"
        ticked_genres = (self.selected_genres()
                          if hasattr(self, 'selected_genres') else [])
        ticked_tones = (self.selected_tones()
                         if hasattr(self, 'selected_tones') else [])
        dlg = _CorpusLibraryDialog(
            self.db_path, self,
            intent=intent,
            genres=ticked_genres,
            tones=ticked_tones,
            llm_generate=self._build_quality_llm_hook())
        dlg.exec()
        # Either way, refresh stats — the user may have ingested more rows
        self._refresh_db_summary()

    def _open_project_import(self):
        """Pull chapters from a Writer Tool project into the training DB.

        The dialog is self-contained: it loads the project, lets the
        user tick chapters, tag them with voice + genre(s), and ingest
        them as corpus rows. Refresh stats afterward so the new rows
        show up in the per-source breakdown.
        """
        dlg = _ProjectImportDialog(self.db_path, self)
        dlg.exec()
        self._refresh_db_summary()

    def _open_manage_trained_models(self) -> None:
        """Open the trained-models manager. Refreshes every dependent
        picker afterwards (Step 2 continue-from, Step 4 test combo)
        so a deletion is reflected immediately without a restart.
        """
        dlg = _TrainedModelsDialog(self)
        dlg.exec()
        self._refresh_trained_models()
        self._refresh_continue_combo()
        # Step 2 banner reads the trained-models list to flag whether
        # the recommendation is "already selected" — refresh it too.
        if hasattr(self, '_refresh_step2_recommendation'):
            self._refresh_step2_recommendation()

    def _open_pacing_pairs_dialog(self) -> None:
        """Generate pacing-rewrite training pairs using CONLIT baselines.

        Surfaces the dialog that drives ``synthesize_pacing_pairs``.
        Refreshes the DB summary on close so the user sees the new
        rows immediately.
        """
        dlg = _PacingPairsDialog(self.db_path,
                                 selected_collection_keys=
                                 self._selected_collection_keys,
                                 parent=self)
        dlg.exec()
        self._refresh_db_summary()

    def _open_rephrase_pairs_dialog(self) -> None:
        """Synthesize rephrase training pairs from the user's corpora."""
        dlg = _RephrasePairsDialog(
            self.db_path,
            selected_collection_keys=self._selected_collection_keys,
            parent=self)
        dlg.exec()
        self._refresh_db_summary()

    def _open_corpus_filter(self) -> None:
        """Per-corpus checklist for the next training run.

        Defaults to all-checked. The selection is stored on the
        TrainingToolWindow instance and consumed by ``_start_training``
        when it calls ``export_jsonl``.
        """
        dlg = _CorpusFilterDialog(
            self.db_path,
            current_selection=self._selected_collection_keys,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._selected_collection_keys = dlg.selected_keys()
            self._refresh_db_summary()  # update breakdown
            # Also refresh the corpus-filter button label so the user
            # can see at a glance whether they've narrowed the set.
            self._refresh_corpus_filter_button_label()

    def _open_clean_corpus_dialog(self) -> None:
        """Run the text cleaner over every existing DB row.

        Two-phase flow: a dry-run pass first that *reports* what would
        be dropped (categorised by drop reason) and lets the user
        approve before any rows are deleted. Then the actual delete
        runs only on the IDs the user confirmed. Output passages are
        what the model is taught to *generate*, so we drop a row when
        its output_text is junk; if the source is junk but the output
        is real prose, we leave the row alone (the training pipeline
        masks the prompt anyway, so source-side junk doesn't poison
        the loss).
        """
        from src.data.text_cleaner import clean_passage
        from src.data.corpus_adapters import split_text_into_pairs
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog
        from PyQt6.QtCore import Qt as _Qt

        # Dry run — gather the IDs that would be dropped, plus the
        # subset that we can RESCUE by re-chunking. The previous
        # version dropped any row whose output was >2500 chars on
        # the assumption it was junk; in practice that often
        # discards real prose. Now: re-run the splitter on those
        # rows and turn each into many paragraph-pairs.
        try:
            db = RephraseDatabase(self.db_path)
            with db._conn() as c:
                cur = c.execute(
                    "SELECT id, source_type, source_text, output_text, "
                    "voice, genre, character_name, notes, rating "
                    "FROM rephrases")
                rows = cur.fetchall()
        except Exception as e:
            QMessageBox.warning(
                self, "Could not read DB",
                f"Could not read training DB:\n{e}")
            return

        if not rows:
            QMessageBox.information(
                self, "Nothing to clean",
                "Your training database has no rows yet.")
            return

        # Pick a format hint per source_type. Corpus rows tend to come
        # from PG / scraped sources and benefit from the gutenberg
        # pass; everything else uses the plain pass.
        from src.data.rephrase_database import SOURCE_CORPUS
        progress = QProgressDialog(
            "Scanning training rows…", "Cancel", 0, len(rows), self)
        progress.setWindowModality(_Qt.WindowModality.WindowModal)
        to_drop: list = []
        # ``to_rescue`` mirrors ``to_drop`` but also carries the
        # split pairs so we can re-insert them at apply time.
        to_rescue: list = []
        rescued_pair_count = 0
        for i, row in enumerate(rows):
            if i % 50 == 0:
                progress.setValue(i)
                if progress.wasCanceled():
                    return
            fmt_hint = ("gutenberg"
                        if row["source_type"] == SOURCE_CORPUS
                        else "plain")
            # Drop the row when the OUTPUT (what the model learns to
            # generate) is junk. Source-side junk we leave alone —
            # instruction rows mask the prompt at training time so
            # prompt junk doesn't reach the loss.
            _cleaned, drop_reason = clean_passage(
                row["output_text"] or "", format_hint=fmt_hint)
            if not drop_reason:
                continue

            # Rescue path: too-long corpus rows often contain real
            # prose that just needs re-chunking. Run the splitter on
            # the output_text; if it returns ≥1 valid pair, queue
            # the rescue. Other drop_reasons (boilerplate, page
            # numbers, JSON blobs, etc.) are real junk — drop them.
            if (drop_reason == "too_long"
                    and row["source_type"] == SOURCE_CORPUS):
                pairs = split_text_into_pairs(row["output_text"] or "")
                if pairs:
                    to_rescue.append({
                        "id": row["id"],
                        "pairs": pairs,
                        "voice": row["voice"] or "",
                        "genre": row["genre"] or "",
                        "character_name": row["character_name"] or "",
                        "notes": row["notes"] or "",
                        "rating": row["rating"] or "",
                    })
                    rescued_pair_count += len(pairs)
                    continue

            to_drop.append((row["id"], drop_reason,
                            (row["output_text"] or "")[:100]))
        progress.setValue(len(rows))

        if not to_drop and not to_rescue:
            QMessageBox.information(
                self, "No junk found",
                f"Scanned {len(rows)} rows. Nothing matched the junk "
                f"signatures — your data is clean.")
            return

        # Summarise drops by reason + rescue plan for the confirm dialog.
        from collections import Counter
        reason_counts = Counter(r for _, r, _ in to_drop)
        drop_breakdown = "\n".join(
            f"  • {n:,} rows: {reason}"
            for reason, n in reason_counts.most_common())
        rescue_text = ""
        if to_rescue:
            rescue_text = (
                f"\n\n<b>Rescue plan:</b> {len(to_rescue):,} too-long "
                f"corpus rows will be split into "
                f"<b>{rescued_pair_count:,}</b> shorter paragraph "
                f"pairs (and the originals removed) instead of being "
                f"dropped wholesale. Net: "
                f"<b>+{rescued_pair_count - len(to_rescue):,}</b> rows "
                f"after this operation.")
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setWindowTitle("Confirm cleanup")
        confirm.setTextFormat(_Qt.TextFormat.RichText)
        if to_drop:
            drop_block = (
                f"<b>{len(to_drop):,}</b> rows match junk signatures "
                f"and will be deleted:<br><pre>{drop_breakdown}</pre>")
        else:
            drop_block = (
                f"<b>0</b> rows match junk signatures (besides the "
                f"rescue plan below).")
        confirm.setText(
            f"Scanned {len(rows):,} rows.<br><br>"
            f"{drop_block}{rescue_text}<br><br>"
            f"Backups go to <code>~/.creativeos/cleanup_backup/</code>.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Yes)
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Backup + delete + rescue.
        from datetime import datetime as _dt
        backup_dir = Path.home() / ".creativeos" / "cleanup_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"cleanup-{ts}.jsonl"
        import json as _json
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                for rid, reason, snippet in to_drop:
                    f.write(_json.dumps({
                        "id": rid, "reason": reason,
                        "output_snippet": snippet,
                        "action": "delete"}) + "\n")
                for r in to_rescue:
                    f.write(_json.dumps({
                        "id": r["id"], "reason": "too_long_rescued",
                        "n_pairs": len(r["pairs"]),
                        "action": "rechunk"}) + "\n")
        except Exception as e:
            QMessageBox.warning(
                self, "Backup failed",
                f"Could not write backup file ({e}). Aborting "
                f"cleanup so nothing is lost.")
            return

        # Apply rescues first (insert new pairs), then drop originals
        # + the regular junk rows. Doing rescues first means we never
        # delete a row before its replacement pairs are committed — if
        # something fails mid-flight, the user keeps the original data.
        rescued_inserted = 0
        try:
            for r in to_rescue:
                title = r["notes"]  # parsed by log_corpus_pair
                # Use log_corpus_pair so the new rows go in via the
                # same code path as a fresh ingest — keeping notes,
                # voice, genre, rating, character_name aligned.
                for opener, rest in r["pairs"]:
                    db.log_corpus_pair(
                        prompt=opener,
                        completion=rest,
                        voice=r["voice"],
                        genre=r["genre"],
                        character_name=r["character_name"],
                        notes=r["notes"],
                        rating=r["rating"] or "good",
                    )
                    rescued_inserted += 1
        except Exception as e:
            QMessageBox.warning(
                self, "Rescue partially applied",
                f"Re-chunking failed mid-flight: {e}\n\n"
                f"{rescued_inserted:,} new pairs were inserted. The "
                f"originals were NOT deleted, so nothing is lost. "
                f"Re-run when ready.")
            return

        try:
            # Delete: regular junk rows + the originals of every
            # rescued row (their replacements are already inserted).
            ids = ([rid for rid, _, _ in to_drop]
                   + [r["id"] for r in to_rescue])
            with db._conn() as c:
                # Use parameter chunks of 500 to stay under any SQLite
                # query-length limits on huge corpora.
                CHUNK = 500
                for i in range(0, len(ids), CHUNK):
                    chunk = ids[i:i + CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    c.execute(
                        f"DELETE FROM rephrases WHERE id IN ({placeholders})",
                        chunk)
        except Exception as e:
            QMessageBox.warning(
                self, "Cleanup failed",
                f"Cleanup partially failed: {e}\n\nBackup is at:\n"
                f"{backup_path}")
            return

        msg = (f"Deleted {len(to_drop):,} junk rows.")
        if to_rescue:
            msg += (f"\nRescued {len(to_rescue):,} too-long rows into "
                    f"{rescued_inserted:,} paragraph pairs "
                    f"(net +{rescued_inserted - len(to_rescue):,}).")
        msg += f"\n\nBackup saved to:\n{backup_path}\n\nRefreshing summary…"
        QMessageBox.information(self, "Cleanup complete", msg)
        self._refresh_db_summary()

    def _open_variability_prune_dialog(self) -> None:
        """Open the variability audit + prune dialog.

        Different from the junk cleaner: this looks at distribution
        (duplicates, oversampling) rather than per-row junk
        signatures. Shows stats per category and drops only what
        the user approves.
        """
        dlg = _VariabilityPruneDialog(self.db_path, parent=self)
        dlg.exec()
        # Refresh dashboard / summary since rows may have been
        # dropped.
        if hasattr(self, "corpus_dashboard"):
            self.corpus_dashboard.refresh()
        self._refresh_db_summary()

    def _open_corpus_browser(self) -> None:
        """Open the searchable DB browser. Read-only — no edits.

        Routed through :class:`_CorpusBrowserDialog` which handles
        free-text search + filters and pages through results 200 at
        a time so a 1.4M-row DB stays responsive.
        """
        dlg = _CorpusBrowserDialog(self.db_path, parent=self)
        dlg.exec()

    def _open_rebuild_corpus_dialog(self) -> None:
        """Drop every row that came from the catalog downloader so the
        user can re-run downloads with the current splitter / cleaner.

        User uploads, project imports, character / worldbuilding / plot
        rows are preserved (they don't carry a ``corpus_id=`` note).
        """
        from PyQt6.QtWidgets import QMessageBox
        try:
            db = RephraseDatabase(self.db_path)
            summary = db.catalog_rows_summary()
        except Exception as e:
            QMessageBox.warning(
                self, "Could not read DB",
                f"Could not read training DB:\n{e}")
            return

        catalog_total = summary.get("total", 0)
        if catalog_total == 0:
            QMessageBox.information(
                self, "Nothing to rebuild",
                "No catalog-downloaded rows found in your training DB. "
                "Manual uploads and project imports are not affected by "
                "this action — only rows that came through the corpus "
                "downloader.")
            return

        by_id = summary.get("by_id", {})
        top = sorted(by_id.items(), key=lambda kv: -kv[1])[:8]
        breakdown = "\n".join(
            f"  • {cid}: {n:,} rows" for cid, n in top)
        if len(by_id) > len(top):
            breakdown += f"\n  • … and {len(by_id) - len(top)} more"

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("Rebuild downloaded corpus")
        confirm.setText(
            f"Drop <b>{catalog_total:,}</b> rows that came through the "
            f"catalog downloader across <b>{len(by_id)}</b> corpora?<br><br>"
            f"<b>Preserved:</b> manual uploads, project imports, "
            f"character / worldbuilding / plot rows, and any test history."
            f"<br><br>"
            f"<b>Top corpora that will be dropped:</b><pre>{breakdown}</pre>"
            f"A backup JSONL is written to "
            f"<code>~/.creativeos/cleanup_backup/</code> first. After this "
            f"finishes you can re-download the same corpora from the "
            f"Library to pick up the splitter fix.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Yes)
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Backup before delete: dump the rows-to-be-deleted as JSONL
        # so the user can recover if they change their mind. Same
        # backup directory the cleaner uses.
        from datetime import datetime as _dt
        import json as _json
        backup_dir = Path.home() / ".creativeos" / "cleanup_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"rebuild-{ts}.jsonl"
        try:
            with db._conn() as c:
                cur = c.execute(
                    "SELECT * FROM rephrases "
                    "WHERE notes LIKE '%corpus_id=%'")
                with open(backup_path, "w", encoding="utf-8") as f:
                    for row in cur:
                        f.write(_json.dumps(dict(row),
                                            default=str) + "\n")
        except Exception as e:
            QMessageBox.warning(
                self, "Backup failed",
                f"Could not write backup file ({e}). Aborting "
                f"rebuild so nothing is lost.")
            return

        try:
            n = db.delete_catalog_rows()
        except Exception as e:
            QMessageBox.warning(
                self, "Rebuild failed",
                f"Delete failed: {e}\n\nBackup is at:\n{backup_path}")
            return

        QMessageBox.information(
            self, "Downloads cleared",
            f"Deleted {n:,} catalog-downloaded rows. Backup saved to:\n"
            f"{backup_path}\n\n"
            f"Open the Corpus Library to re-download. New rows will use "
            f"the current splitter (longer openers, balanced rest).")
        self._refresh_db_summary()
        if hasattr(self, "corpus_dashboard"):
            self.corpus_dashboard.refresh()

    def _refresh_corpus_filter_button_label(self) -> None:
        """Reflect the current per-corpus selection in the button text."""
        if not hasattr(self, 'corpus_filter_btn'):
            return
        keys = self._selected_collection_keys
        if keys is None:
            self.corpus_filter_btn.setText("✓ All corpora")
            self.corpus_filter_btn.setStyleSheet("")
        else:
            self.corpus_filter_btn.setText(
                f"✓ {len(keys)} corpus collection(s) selected")
            # Subtle highlight so the user notices they've narrowed
            # the set.
            self.corpus_filter_btn.setStyleSheet(
                "QPushButton { background-color: #fef3c7; }")

    @staticmethod
    def _ingest_corpus_text(db: RephraseDatabase, text: str,
                            title: str = "",
                            voice: str = "",
                            genre: str = "") -> int:
        """Split text into passages and store them as corpus pairs.

        Each paragraph becomes one (opener, rest) example where the
        opener is one or more leading sentences (long enough to give
        the model real context) and the rest is the continuation.
        Splitting is delegated to the same helper the downloader uses
        so manual uploads and downloaded corpora produce the same
        shape of training pair.
        """
        import re
        from src.data.corpus_downloader import _split_paragraph_for_training
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text)
                      if p.strip()]
        n = 0
        for para in paragraphs:
            if len(para) > 2500:
                continue
            if para.lstrip()[:1] in '#-*•':
                continue
            opener, rest = _split_paragraph_for_training(para)
            if opener is None:
                continue
            db.log_corpus_pair(prompt=opener, completion=rest, title=title,
                               voice=voice, genre=genre)
            n += 1
        return n

    def _export_dataset(self):
        fmt = self.format_combo.currentData()
        min_rating = self.min_rating_combo.currentData()
        sources = self._selected_source_types()
        if not sources:
            QMessageBox.warning(
                self, "Pick a Source",
                "Tick at least one data source above before exporting.")
            return
        suggested = self.db_path.with_suffix(
            ".dpo.jsonl" if fmt == "dpo" else ".jsonl")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export dataset", str(suggested), "JSONL (*.jsonl)")
        if not path:
            return
        try:
            db = RephraseDatabase(self.db_path)
            n = db.export_jsonl(Path(path), fmt=fmt, min_rating=min_rating,
                                source_types=sources)
            self.dataset_jsonl = Path(path)
            tip = ""
            if fmt == "dpo":
                tip = ("\n\nUse with HuggingFace TRL's DPOTrainer to train "
                       "the model to prefer your highly-rated outputs over "
                       "the ones you rated poor/bad.")
            else:
                tip = ("\n\nUse this file with HuggingFace Trainer or TRL's "
                       "SFTTrainer on any machine.")
            QMessageBox.information(
                self, "Exported",
                f"Wrote {n} examples to:\n{path}{tip}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ── Step 2: model ──

    def _build_step_model(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Step 2 — Choose what to train</b>"))

        intro = QLabel(
            "Pick a fresh base model OR continue training on top of one "
            "of your previously-trained models. LoRA fine-tuning runs "
            "on a single GPU or Apple Silicon with reasonable speed.\n\n"
            "Either way, training writes to a NEW output directory — "
            "your existing trained models are never overwritten.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280;")
        layout.addWidget(intro)

        form = QFormLayout()
        # Editable so the user can still type a custom HF id that's not
        # in the catalog. The dropdown is sourced from the user-curated
        # catalog (see _refresh_base_model_combo) so anything they hide
        # in the manager dialog disappears here AND from agent
        # recommendations.
        self.base_model_combo = QComboBox()
        self.base_model_combo.setEditable(True)
        self.base_model_combo.setMinimumWidth(380)
        self._refresh_base_model_combo()
        form.addRow("Base model:", self.base_model_combo)

        # Corpus-aware recommendation panel — recomputed every time the
        # user lands on Step 2. Same logic as the Step 1 stats line and
        # the Build Recipe button, so all three suggestions agree.
        rec_row = QVBoxLayout()
        rec_row.setSpacing(2)
        self.recommendation_banner = QLabel("")
        self.recommendation_banner.setWordWrap(True)
        self.recommendation_banner.setStyleSheet(
            "background: #ecfdf5; border: 1px solid #6ee7b7; "
            "border-radius: 6px; padding: 8px 10px; color: #065f46;"
            "font-size: 11px;")
        self.recommendation_banner.setVisible(False)
        rec_row.addWidget(self.recommendation_banner)

        rec_btn_row = QHBoxLayout()
        rec_btn_row.addStretch()
        self.use_recommended_btn = QPushButton("Use recommended")
        self.use_recommended_btn.setToolTip(
            "Set the base model to the one our recommender picks for "
            "your current training data and intent.")
        self.use_recommended_btn.clicked.connect(
            self._apply_recommended_base_model)
        self.use_recommended_btn.setVisible(False)
        rec_btn_row.addWidget(self.use_recommended_btn)
        rec_row.addLayout(rec_btn_row)
        form.addRow("", self._row_widget(rec_row))

        # Manage built-in models: opens a dialog of catalog checkboxes.
        # Hides/shows entries here AND in the agent's allowed-id list.
        manage_row = QHBoxLayout()
        manage_row.addStretch()
        self.manage_models_btn = QPushButton("⚙ Manage built-in models…")
        self.manage_models_btn.setToolTip(
            "Hide built-in models you don't want offered here or in the "
            "Model Builder Agent's recommendations. Useful when your "
            "machine can only run small models, or when you want to "
            "force the agent to pick a specific family.")
        self.manage_models_btn.clicked.connect(self._open_base_model_manager)
        manage_row.addWidget(self.manage_models_btn)
        form.addRow("", self._row_widget(manage_row))

        # Iterate on a previously-trained model
        self.continue_combo = QComboBox()
        self.continue_combo.addItem("(none — start from base model above)", "")
        self._refresh_continue_combo()
        self.continue_combo.setToolTip(
            "Optional: continue training on top of one of your trained "
            "models. The original model stays untouched — output goes "
            "to a new directory.")
        form.addRow("Or continue from:", self.continue_combo)
        layout.addLayout(form)
        layout.addStretch()
        return page

    @staticmethod
    def _row_widget(layout) -> QWidget:
        """Wrap a QHBoxLayout in a QWidget so a QFormLayout will host it."""
        w = QWidget()
        w.setLayout(layout)
        return w

    def _refresh_base_model_combo(self) -> None:
        """Repopulate the catalog dropdown from the user-curated list.

        Preserves the currently-typed/selected value so toggling the
        manager dialog doesn't reset the user's pick. Anything the user
        had previously selected — even if it's now hidden — stays as
        the visible text so they can still train against it (the field
        is editable on purpose).
        """
        from src.ui.model_picker_widget import get_included_training_base_models
        if not hasattr(self, 'base_model_combo'):
            return
        current = self.base_model_combo.currentText().strip()
        self.base_model_combo.blockSignals(True)
        try:
            self.base_model_combo.clear()
            included = get_included_training_base_models()
            if not included:
                # Defensive: shouldn't happen because the manager dialog
                # refuses to save an all-empty selection. Fall back to
                # one safe default so the wizard still works.
                self.base_model_combo.addItem("google/gemma-2-2b-it")
            else:
                for m in included:
                    self.base_model_combo.addItem(m.model_id)
            if current:
                self.base_model_combo.setEditText(current)
        finally:
            self.base_model_combo.blockSignals(False)

    def _open_base_model_manager(self) -> None:
        from src.ui.model_picker_widget import BaseModelManagerDialog
        dlg = BaseModelManagerDialog(self)
        # Manager changes can shift the recommendation too (a freshly
        # excluded model may have been the recommended one), so refresh
        # both the combo and the banner.
        dlg.changed.connect(self._refresh_base_model_combo)
        dlg.changed.connect(self._refresh_step2_recommendation)
        dlg.exec()

    def _current_intent_hint(self) -> str:
        """Best-effort intent inference for the recommendation engine.

        Uses the user's selection on Step 1's Goal combo when available,
        otherwise inspects the description for keywords. Falls back to
        ``voice`` — the most common training intent.
        """
        if hasattr(self, 'goal_combo'):
            v = self.goal_combo.currentData() or ""
            if v:
                return v
        if hasattr(self, 'describe_edit'):
            text = (self.describe_edit.text() or "").lower()
            if any(k in text for k in ("plot", "outline", "structure")):
                return "plot"
            if any(k in text for k in ("worldbuilding", "world building",
                                       "lore", "faction")):
                return "worldbuilding"
            if any(k in text for k in ("character", "protagonist",
                                       "love interest", "backstory")):
                return "character"
            if any(k in text for k in ("chat", "assistant", "answer")):
                return "qa"
        return "voice"

    def _eligible_corpus_size(self) -> int:
        """Return how many rated rows would be eligible for SFT export."""
        try:
            db = RephraseDatabase(self.db_path)
            br = db.stats().get("by_rating", {})
            return br.get("excellent", 0) + br.get("good", 0)
        except Exception:
            return 0

    def _refresh_step2_recommendation(self) -> None:
        """Recompute and display the corpus-aware base model suggestion.

        Called whenever the user lands on Step 2, after a recipe is
        applied, and when the manage-models dialog saves new exclusions.
        Hides itself silently when the recommender returns nothing
        (catalog empty + LLM unreachable, etc).
        """
        if not hasattr(self, 'recommendation_banner'):
            return
        try:
            from src.ai.model_builder_agent import recommend_base_for_corpus
            size = self._eligible_corpus_size()
            intent = self._current_intent_hint()
            rec_id, why = recommend_base_for_corpus(size, intent=intent)
        except Exception:
            self.recommendation_banner.setVisible(False)
            self.use_recommended_btn.setVisible(False)
            return

        if not rec_id:
            self.recommendation_banner.setVisible(False)
            self.use_recommended_btn.setVisible(False)
            return

        already_using = (
            self.base_model_combo.currentText().strip() == rec_id)
        marker = " ✓ already selected" if already_using else ""
        self.recommendation_banner.setText(
            f"💡 <b>Recommended:</b> <code>{rec_id}</code>{marker}<br>"
            f"<span style='color:#047857;'>{why}</span>"
        )
        self.recommendation_banner.setVisible(True)
        self.use_recommended_btn.setVisible(not already_using)
        self._recommended_base_id = rec_id

    def _apply_recommended_base_model(self) -> None:
        """Set the base model combo to the current recommendation."""
        rec_id = getattr(self, '_recommended_base_id', '')
        if not rec_id:
            return
        # If the recommended id is already in the dropdown, select it;
        # otherwise type it in (the combo is editable on purpose).
        idx = self.base_model_combo.findText(rec_id)
        if idx >= 0:
            self.base_model_combo.setCurrentIndex(idx)
        else:
            self.base_model_combo.setEditText(rec_id)
        self._refresh_step2_recommendation()

    def _on_simple_mode_toggled(self, advanced_visible: bool) -> None:
        """Show/hide the advanced hyperparameter rows on Step 3.

        Simple mode hides learning rate, batch size, LoRA rank
        (including its rationale), and the QLoRA toggle. The user
        keeps name + base model + epochs + train-on-rating + Start —
        the minimum that produces a usable trained model. The Suggest
        buttons populate sensible defaults for the hidden knobs.
        """
        form = getattr(self, '_train_form', None)
        if form is None:
            return
        # Widgets directly added as the field of a form row — these
        # work with QFormLayout.setRowVisible(widget, bool) which
        # handles both the label and the field.
        direct_field_attrs = ("lr_spin", "batch_spin",
                              "lora_rationale_label", "qlora_cb")
        # Wrapper widgets that group multiple controls into a single
        # form row — handled the same way.
        wrapper_attrs = ("_lora_row_wrapper",)

        for attr in direct_field_attrs + wrapper_attrs:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                form.setRowVisible(w, advanced_visible)
            except (TypeError, AttributeError):
                # Older PyQt — fall back to manual visibility on the
                # widget; the label stays put but at least the field
                # disappears.
                w.setVisible(advanced_visible)

    def _refresh_continue_combo(self):
        if not hasattr(self, 'continue_combo'):
            return
        self.continue_combo.blockSignals(True)
        try:
            current = self.continue_combo.currentData() if self.continue_combo.count() else ""
            self.continue_combo.clear()
            self.continue_combo.addItem("(none — start from base model above)", "")
            for m in load_trained_models():
                self.continue_combo.addItem(
                    f"{m.get('name','?')} (base: {m.get('base_model','?')})",
                    m.get("path", ""))
            if current:
                for i in range(self.continue_combo.count()):
                    if self.continue_combo.itemData(i) == current:
                        self.continue_combo.setCurrentIndex(i)
                        break
        finally:
            self.continue_combo.blockSignals(False)

    # ── Step 3: train ──

    def _build_step_train(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Step 3 — Configure & train</b>"))

        # Simple-mode toggle. Off by default — we show the basics
        # (name, base model, epochs, train-on-rating, start) and hide
        # the hyperparameter knobs (LR, batch, LoRA r, QLoRA). The
        # Suggest buttons set sensible defaults so simple-mode users
        # never need to think about LR / rank.
        simple_row = QHBoxLayout()
        self.simple_mode_cb = QCheckBox("Show advanced settings")
        self.simple_mode_cb.setChecked(False)
        self.simple_mode_cb.setToolTip(
            "Off (default): show only the essential fields — name, base "
            "model, epochs, training data quality, Start. Sensible "
            "defaults for everything else.\n\n"
            "On: surface learning rate, batch size, LoRA rank, and "
            "QLoRA toggle. Use this when you know what you're doing or "
            "the suggested defaults aren't working.")
        self.simple_mode_cb.toggled.connect(self._on_simple_mode_toggled)
        simple_row.addWidget(self.simple_mode_cb)
        simple_row.addStretch()
        layout.addLayout(simple_row)

        form = QFormLayout()
        # Track which form rows are "advanced" so the toggle can hide
        # them by widget reference. We use the field widget (not the
        # label) as the key for QFormLayout.setRowVisible.
        self._advanced_field_widgets: list = []
        self.name_edit = QLineEdit("my-voice-v1")
        form.addRow("Model name:", self.name_edit)
        # Stash form so the toggle handler can reach it.
        self._train_form = form

        # Epochs spin + Suggest button. The suggester picks epochs
        # based on corpus size, training intent, and the chosen LoRA
        # rank — see ``recommend_epochs`` for the rules. Users can
        # override the suggestion freely; the spin still goes to 20
        # for power users who want long runs.
        epochs_row = QHBoxLayout()
        self.epochs_spin = QSpinBox()
        self.epochs_spin.setRange(1, 20)
        self.epochs_spin.setValue(2)
        epochs_row.addWidget(self.epochs_spin)
        self.suggest_epochs_btn = QPushButton("💡 Suggest")
        self.suggest_epochs_btn.setToolTip(
            "Pick a number of epochs based on your corpus size + "
            "training intent (voice / plot / character / etc.) + the "
            "LoRA rank you've set. Small corpora get more passes; "
            "high-rank adapters get one fewer pass to avoid overfit.")
        self.suggest_epochs_btn.clicked.connect(
            lambda _=False: self._suggest_epochs())
        epochs_row.addWidget(self.suggest_epochs_btn)
        epochs_row.addStretch()
        form.addRow("Epochs:", self._row_widget(epochs_row))

        # Rationale shown after Suggest fires
        self.epochs_rationale_label = QLabel("")
        self.epochs_rationale_label.setWordWrap(True)
        self.epochs_rationale_label.setStyleSheet(
            "padding: 6px 8px; background: #ecfdf5; "
            "border-radius: 4px; color: #065f46; font-size: 11px;")
        self.epochs_rationale_label.setVisible(False)
        form.addRow("", self.epochs_rationale_label)

        self.lr_spin = QDoubleSpinBox()
        self.lr_spin.setRange(1e-6, 1e-2); self.lr_spin.setDecimals(6)
        self.lr_spin.setSingleStep(1e-5); self.lr_spin.setValue(2e-4)
        form.addRow("Learning rate:", self.lr_spin)

        self.batch_spin = QSpinBox(); self.batch_spin.setRange(1, 16); self.batch_spin.setValue(1)
        form.addRow("Batch size:", self.batch_spin)

        # LoRA rank picker + Suggest button. The button calls
        # ``recommend_lora_params`` which inspects this host's RAM/VRAM,
        # the picked base model size, the QLoRA toggle, and the
        # eligible-corpus-row count, and writes a defensible r back
        # into the spin. The worker derives alpha = 2*r automatically.
        lora_row = QHBoxLayout()
        self.lora_r_spin = QSpinBox()
        self.lora_r_spin.setRange(2, 64)
        self.lora_r_spin.setValue(8)
        lora_row.addWidget(self.lora_r_spin)
        self.suggest_lora_btn = QPushButton("💡 Suggest")
        self.suggest_lora_btn.setToolTip(
            "Detect this machine's RAM/VRAM, factor in the chosen base "
            "model size and QLoRA toggle, and pick a LoRA rank that "
            "fits without OOM. Also caps r against your corpus size to "
            "avoid overfitting on small datasets. alpha = 2×r.")
        self.suggest_lora_btn.clicked.connect(
            lambda _=False: self._suggest_lora_params())
        lora_row.addWidget(self.suggest_lora_btn)
        lora_row.addStretch()
        # Store the wrapper widget so simple-mode can hide the whole
        # row (label + spin + suggest button) atomically.
        self._lora_row_wrapper = self._row_widget(lora_row)
        form.addRow("LoRA rank (r):", self._lora_row_wrapper)

        # Rationale shown after Suggest fires so the user can see why
        # the recommendation came out the way it did.
        self.lora_rationale_label = QLabel("")
        self.lora_rationale_label.setWordWrap(True)
        self.lora_rationale_label.setStyleSheet(
            "padding: 6px 8px; background: #ecfdf5; "
            "border-radius: 4px; color: #065f46; font-size: 11px;")
        self.lora_rationale_label.setVisible(False)
        form.addRow("", self.lora_rationale_label)

        # QLoRA: 4-bit quantized base + LoRA adapters. Enables training
        # larger bases on smaller GPUs (a 7B model that needs ~28GB in
        # bf16 fits in ~7GB at 4-bit). Requires NVIDIA + bitsandbytes;
        # the worker falls back to standard precision with a warning
        # on CPU/MPS so a click on Mac doesn't crash.
        self.qlora_cb = QCheckBox("Use QLoRA (4-bit base, NVIDIA only)")
        self.qlora_cb.setToolTip(
            "QLoRA loads the base model in 4-bit (NF4) and trains LoRA "
            "adapters on top. Cuts memory by ~4× — required for fine-"
            "tuning 7B+ models on consumer GPUs. Needs CUDA + the "
            "bitsandbytes package (pip install bitsandbytes). On "
            "Apple Silicon / CPU this falls back to standard precision "
            "automatically.")
        form.addRow("Quantization:", self.qlora_cb)

        self.train_min_rating = QComboBox()
        self.train_min_rating.addItem("⭐ Excellent + 👍 Good (recommended)", "good")
        self.train_min_rating.addItem("⭐ Excellent only (strictest)", "excellent")
        self.train_min_rating.addItem("All except 👎/✖ (broadest)", "neutral")
        self.train_min_rating.setToolTip(
            "Pick which rated rows to use as training data. Negative-rated "
            "rows are NEVER included as positive examples — they go into "
            "the DPO export instead.")
        form.addRow("Train on:", self.train_min_rating)

        layout.addLayout(form)

        # Apply simple-mode default (advanced rows hidden).
        self._on_simple_mode_toggled(self.simple_mode_cb.isChecked())

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Training")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 16px; border-radius: 6px; font-weight: bold; }")
        self.start_btn.clicked.connect(self._start_training)
        btn_row.addWidget(self.start_btn)

        # Modal cloud-training button. Disabled if the local recipe
        # is too small to be worth the round-trip (anything < ~3B
        # the user can train locally faster than the cold-start),
        # but visible so users know the option exists. Tooltip shows
        # estimated cost when the recipe is set.
        self.modal_train_btn = QPushButton("☁️  Train on Modal…")
        self.modal_train_btn.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 6px 16px; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4f46e5; }")
        self.modal_train_btn.setToolTip(
            "Submit this training run to Modal's cloud GPUs (pay per "
            "second). Use this when your local machine can't fit the "
            "base model, or when you want a faster turnaround on a "
            "long run. Cost: typically $0.50-8 per run depending on "
            "base model size + epochs. Resulting LoRA adapter "
            "downloads back to your local registry automatically.")
        self.modal_train_btn.clicked.connect(self._train_on_modal)
        btn_row.addWidget(self.modal_train_btn)

        # Modal credentials button — opens a dialog where the user
        # pastes their MODAL_TOKEN_ID / MODAL_TOKEN_SECRET and they
        # land in the OS keystore (Keychain / Credential Manager /
        # Secret Service). Separate from the Train button so the
        # credentials flow is reachable even when the user isn't
        # ready to spend money yet.
        self.modal_creds_btn = QPushButton("🔑 Configure Modal…")
        self.modal_creds_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border-radius: 6px; }")
        self.modal_creds_btn.setToolTip(
            "Store your Modal API tokens in the OS keystore. "
            "Get them from https://modal.com/settings/tokens — "
            "or skip this and run `modal token new` in a terminal.")
        self.modal_creds_btn.clicked.connect(self._open_modal_credentials)
        btn_row.addWidget(self.modal_creds_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Pre-training quality preview row — same dialog the
        # Start-Training gate uses, but here it runs standalone so
        # the user can iterate on corpus / recipe choices without
        # committing to a training run. The pre-training gate
        # *also* still fires when they click Start Training; this
        # button is the discoverable surface for "let me check
        # this NOW".
        check_row = QHBoxLayout()
        self.check_quality_btn = QPushButton(
            "🔍 Check Corpus Quality")
        self.check_quality_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 5px; "
            "background-color: #fbbf24; color: #78350f; "
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #f59e0b; }")
        self.check_quality_btn.setToolTip(
            "Preview what the trainer will see — row counts, "
            "vocab diversity, sample passages, and a verdict on "
            "whether the dataset is ready. Same dialog that fires "
            "automatically when you click Start Training, but here "
            "you can iterate on corpus / recipe choices without "
            "starting a training run.")
        self.check_quality_btn.clicked.connect(
            self._open_corpus_quality_check)
        check_row.addWidget(self.check_quality_btn)
        check_row.addStretch()
        layout.addLayout(check_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background-color: #111827; color: #d1d5db;")
        layout.addWidget(self.train_log, 1)
        return page

    def _check_memory_before_training(
            self, base_model: str, *, use_qlora: bool) -> bool:
        """Warn if available RAM looks too tight for the chosen base.

        Returns True if training should proceed (memory is fine OR the
        user dismissed the warning), False if the user cancelled.

        The estimate uses parameter-count cues from the model id (e.g.
        ``-7B``, ``-13B``, ``E2B``) and bytes-per-param for the chosen
        precision. It's deliberately conservative — for ambiguous
        models we under-estimate rather than over-warn. psutil is
        imported lazily so the studio still works when it's missing.
        """
        try:
            import psutil
        except Exception:
            return True  # can't check; let it proceed

        avail_gb = psutil.virtual_memory().available / (1024 ** 3)

        # Cheap regex-free param-count guess from the model id. Hits
        # the common naming conventions: 7B, 13B, 70B, E2B, 1.5B,
        # E2-2B etc. Falls back to a 7B-class assumption when nothing
        # parses (most fine-tune-targeted bases live in that band).
        billions = 7.0
        token = base_model.upper()
        for marker in ("70B", "65B", "34B", "30B", "27B", "26B", "20B",
                       "13B", "9B", "8B", "7B", "4B", "3B", "2B", "1B"):
            if marker in token:
                billions = float(marker.replace("B", ""))
                break

        # bf16 = 2 bytes/param + ~30% overhead for grads/optimizer in
        # LoRA mode. QLoRA 4-bit = 0.5 bytes/param + same overhead.
        bytes_per_param = 0.5 if use_qlora else 2.0
        est_gb = (billions * 1e9 * bytes_per_param * 1.3) / (1024 ** 3)

        # Hard block only when impossibly tight (estimated > 95% of
        # available); otherwise warn-and-let-them-proceed.
        from PyQt6.QtWidgets import QMessageBox
        if est_gb > avail_gb * 0.95:
            mb = QMessageBox(self)
            mb.setIcon(QMessageBox.Icon.Warning)
            mb.setWindowTitle("Memory may be insufficient")
            tip_qlora = ("" if use_qlora else
                         "\n• Tick the QLoRA checkbox (4-bit base) to "
                         "cut memory ~4×.")
            mb.setText(
                f"Training {base_model} is estimated to need "
                f"~{est_gb:.1f} GB of RAM. Your machine has "
                f"~{avail_gb:.1f} GB available — the run will likely "
                f"OOM.\n\nOptions:\n"
                f"• Pick a smaller base model "
                f"(2-3 B params for a 32 GB laptop)."
                f"{tip_qlora}\n"
                f"• Close other apps to free RAM, then retry.\n\n"
                f"Continue anyway?")
            mb.setStandardButtons(
                QMessageBox.StandardButton.Cancel
                | QMessageBox.StandardButton.Yes)
            mb.setDefaultButton(QMessageBox.StandardButton.Cancel)
            return mb.exec() == QMessageBox.StandardButton.Yes

        if est_gb > avail_gb * 0.7:
            # Soft warning — proceed by default but tell the user.
            self.train_log.appendPlainText(
                f"[memory] estimated need ~{est_gb:.1f}GB, available "
                f"~{avail_gb:.1f}GB — close other apps if training "
                f"slows or stalls.")
        return True

    def _ingested_corpus_ids(self, db: 'RephraseDatabase') -> set:
        """Return the set of catalog corpus ids that have rows in the DB.

        The downloader tags every ingested row with ``corpus_id=<id>``
        somewhere in the ``notes`` column. Notes can also start with
        ``corpus_title=…`` when the ingestion path knew the row's
        title — substring-match catches both shapes.
        """
        ids = set()
        import re as _re
        try:
            with db._conn() as c:
                cur = c.execute(
                    "SELECT DISTINCT notes FROM rephrases "
                    "WHERE source_type = 'corpus' "
                    "AND notes LIKE '%corpus_id=%'")
                for row in cur:
                    notes = row["notes"] or ""
                    m = _re.search(r'corpus_id=(\S+)', notes)
                    if m:
                        ids.add(m.group(1))
        except Exception:
            pass
        return ids

    def _collect_relevant_corpus_ids(self) -> List[str]:
        """Build the *full* set of catalog corpus ids relevant to this
        training run. Three sources, deduped & in priority order:

          1. Genre-mapped corpora — every catalog id linked to a ticked
             genre via ``src.data.genres`` (corpora + craft).
          2. Recipe-recommended corpora — what the Model Builder Agent
             picked for the user's description, plus the genre-specific
             writing-craft documents it surfaced.
          3. Per-corpus filter — if the user already narrowed the corpus
             selection to specific collection keys, ONLY those keys are
             considered relevant; any other genre/recipe corpus the
             user explicitly excluded is dropped.

        This is broader than the old genre-only check, which is what
        let recipe-only or non-mapped corpora slip past the verifier.
        """
        from src.data.genres import corpora_for, craft_corpora_for
        from src.data.tones import filter_corpora_by_tones
        ids: List[str] = []
        seen = set()

        # Genre-mapped (corpora + writing-craft). If the user picked
        # any tones, narrow the genre corpora to tone-matching books —
        # the filter has a definitive floor so even thin (genre × tone)
        # cells produce a usable training set via ladder fallback.
        # Empty tone list = opt-out, passes through unchanged. Craft
        # texts are always tone-agnostic — instruction is instruction
        # regardless of register.
        tones = self.selected_tones()
        tone_result = filter_corpora_by_tones(
            corpora_for(self.selected_genres()), tones)
        # Stash for the UI to surface ladder status (which fallback
        # tier was used, if any). Read by Step 1 status panel.
        self._last_tone_filter_result = tone_result
        for cid in tone_result.corpus_ids:
            if cid not in seen:
                seen.add(cid); ids.append(cid)
        for cid in craft_corpora_for(self.selected_genres()):
            if cid not in seen:
                seen.add(cid); ids.append(cid)

        # Recipe-recommended — these may be genres-mapped already, but
        # the agent can also pick non-mapped catalog entries (e.g. PG-19
        # multi-author for "voice" intent), and those wouldn't be
        # caught by the genre map alone.
        recipe = getattr(self, '_current_recipe', None)
        if recipe is not None:
            for cid in (getattr(recipe, "recommended_corpora", []) or []):
                if cid not in seen:
                    seen.add(cid); ids.append(cid)
            for cid in (getattr(recipe, "recommended_craft", []) or []):
                if cid not in seen:
                    seen.add(cid); ids.append(cid)

        # Honor the per-corpus filter if the user narrowed the run.
        # The filter uses collection keys like "catalog:<id>"; we only
        # need to check the catalog: keys, since the relevant ids here
        # are all catalog corpora.
        sel = self._selected_collection_keys
        if sel is not None:
            allowed_catalog_ids = {
                k.split(":", 1)[1] for k in sel
                if k.startswith("catalog:")
            }
            ids = [cid for cid in ids if cid in allowed_catalog_ids]

        return ids

    def _verify_relevant_corpora_or_offer_download(self) -> bool:
        """Cross-check every relevant catalog corpus against ingested rows.

        "Relevant" = union of (genre-mapped corpora, recipe-recommended
        corpora, recipe-recommended craft documents) — minus anything
        excluded by the per-corpus filter. If any of those aren't
        already ingested, we offer a one-shot download covering
        ALL of them (no more "downloaded a subset" surprise).

        Returns True to proceed with training, False to abort.
        """
        if not self.src_corpus_cb.isChecked():
            # User explicitly excluded corpus rows — skip verification.
            return True

        from src.data.corpus_catalog import find_entry
        needed = self._collect_relevant_corpus_ids()
        if not needed:
            return True

        db = RephraseDatabase(self.db_path)
        ingested = self._ingested_corpus_ids(db)
        missing_ids = [cid for cid in needed if cid not in ingested]
        if not missing_ids:
            return True
        missing_entries = [find_entry(cid) for cid in missing_ids]
        missing_entries = [e for e in missing_entries if e is not None]
        if not missing_entries:
            return True

        # Surface every missing entry so the user sees the full set —
        # not the truncated 12-item slice the old version showed.
        bullet = "\n".join(
            f"  • {e.name}  ({e.license})" for e in missing_entries)
        body = (
            f"This training run references {len(missing_entries)} "
            f"catalog corpus/corpora that aren't downloaded yet:\n\n"
            f"{bullet}\n\n"
            f"Sources include: ticked genres, the Model Builder "
            f"Agent's recipe (if you built one), and any genre-"
            f"specific writing-craft documents.\n\n"
            f"Yes  → download ALL of them now (recommended)\n"
            f"No   → train with only what's already in the DB\n"
            f"Cancel → abort training"
        )
        reply = QMessageBox.question(
            self, "Download missing corpora?", body,
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.No:
            self.train_log.appendPlainText(
                f"[setup] Proceeding without {len(missing_entries)} "
                f"corpora; results will reflect only what's already "
                f"in the DB.")
            return True

        # Yes — synchronous ingest with progress to train_log. UI is
        # only blocked while individual files download (each PG entry
        # is small; total is usually a few MB). processEvents keeps
        # the log live.
        from src.data.corpus_downloader import ingest, CorpusLicenseError
        from PyQt6.QtWidgets import QApplication
        ok_count = 0
        skipped_license: List[str] = []
        for entry in missing_entries:
            self.train_log.appendPlainText(
                f"[corpus] downloading {entry.name}…")
            QApplication.processEvents()
            try:
                ingest(entry, db=db,
                       on_log=lambda s: (
                           self.train_log.appendPlainText(f"          {s}"),
                           QApplication.processEvents()))
                ok_count += 1
            except CorpusLicenseError as e:
                # User-attested entries can't auto-download. Surface
                # them clearly so the user knows to register them
                # manually via Add Custom URL with attestation.
                skipped_license.append(entry.name)
                self.train_log.appendPlainText(
                    f"[corpus] needs attestation, skipped: {entry.name}")
            except Exception as e:
                self.train_log.appendPlainText(
                    f"[corpus] failed for {entry.id}: {e}")
        self.train_log.appendPlainText(
            f"[setup] Ingested {ok_count}/{len(missing_entries)} "
            f"corpora.")
        if skipped_license:
            self.train_log.appendPlainText(
                f"[setup] {len(skipped_license)} corpora require "
                f"attestation — open the Corpus Library and use "
                f"'Add Custom URL' to register them: "
                f"{', '.join(skipped_license[:3])}"
                + ("…" if len(skipped_license) > 3 else ""))
        if ok_count == 0 and not skipped_license:
            QMessageBox.warning(
                self, "No corpora ingested",
                "None of the missing corpora downloaded successfully. "
                "Check the log and try again, or click 'No' next time "
                "to skip the corpus check.")
            return False
        return True

    # Keep the old name as an alias so older call sites still work
    # if anything outside this file ever referenced it.
    def _verify_genre_corpora_or_offer_download(self) -> bool:
        return self._verify_relevant_corpora_or_offer_download()

    def _free_memory_for_training_or_abort(self) -> bool:
        """Detect any local LLM weights still in RAM and ask to unload.

        Returns True when training may proceed (either nothing was
        loaded, or the user said "Yes, unload"). Returns False when the
        user cancels — caller aborts the training run.

        We don't touch the user's *configured* model id — that stays
        selected in CreativeOS settings and reloads on next chat /
        rephrase / agent call.
        """
        try:
            from src.ai.llm_client import (
                list_loaded_local_clients, unload_all_local_clients,
            )
        except Exception:
            return True  # safety: if registry import fails, just proceed

        loaded = list_loaded_local_clients()
        if not loaded:
            return True

        # Build a friendly list of model labels (deduped by id).
        seen, labels = set(), []
        for c in loaded:
            label = c.loaded_model_label() or c.model
            if label not in seen:
                seen.add(label)
                labels.append(label)

        bullet_list = "\n".join(f"  • {lbl}" for lbl in labels)
        body = (
            "Training will load a base model and dataset into RAM. "
            "To free memory, the following local model(s) currently "
            "loaded need to be dropped:\n\n"
            f"{bullet_list}\n\n"
            "Your model selection stays the same — these will reload "
            "automatically the next time the writing tools or chat "
            "use them.\n\n"
            "Continue with training?"
        )
        reply = QMessageBox.question(
            self, "Free RAM for training?", body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.train_log.appendPlainText(
                "[setup] Training cancelled — local models kept in RAM.")
            return False

        n = unload_all_local_clients()
        self.train_log.appendPlainText(
            f"[setup] Unloaded {n} local model(s) to free memory: "
            f"{', '.join(labels)}")
        return True

    def _suggest_epochs(self) -> None:
        """Run the epoch recommender and apply its suggestion.

        Uses the eligible-corpus-row count, the user's training intent
        (Step 1 Goal combo, falling back to keyword sniffing on the
        description), and the current LoRA rank. The recommender clamps
        to ``[1, 6]``; the spin still allows up to 20 for users who
        want longer runs.
        """
        try:
            from src.ai.model_builder_agent import recommend_epochs
        except Exception as e:
            self.epochs_rationale_label.setText(
                f"<i>Could not load recommender: {e}</i>")
            self.epochs_rationale_label.setVisible(True)
            return

        corpus_size = (self._eligible_corpus_size()
                       if hasattr(self, '_eligible_corpus_size') else 0)
        intent = (self._current_intent_hint()
                  if hasattr(self, '_current_intent_hint') else "voice")
        lora_r = (self.lora_r_spin.value()
                  if hasattr(self, 'lora_r_spin') else 8)

        rec = recommend_epochs(corpus_size=corpus_size,
                               intent=intent, lora_r=lora_r)
        new_epochs = max(self.epochs_spin.minimum(),
                         min(self.epochs_spin.maximum(), rec["epochs"]))
        self.epochs_spin.setValue(new_epochs)

        rationale_html = "<br>".join(
            "• " + line for line in rec["rationale"].split("\n"))
        self.epochs_rationale_label.setText(
            f"<b>Suggested epochs={new_epochs}</b><br>{rationale_html}")
        self.epochs_rationale_label.setVisible(True)

    def _suggest_lora_params(self) -> None:
        """Run the host-aware LoRA recommender and apply its suggestion.

        Pulls the current base model id (Step 2), QLoRA toggle, and
        eligible-corpus-row count, then writes the recommended ``r``
        into the spin and surfaces the rationale below it. ``alpha``
        is derived as 2*r by the worker — no separate spin needed.
        """
        try:
            from src.ai.model_builder_agent import recommend_lora_params
        except Exception as e:
            self.lora_rationale_label.setText(
                f"<i>Could not load recommender: {e}</i>")
            self.lora_rationale_label.setVisible(True)
            return

        base_model = (self.base_model_combo.currentText().strip()
                      if hasattr(self, 'base_model_combo') else "")
        use_qlora = (self.qlora_cb.isChecked()
                     if hasattr(self, 'qlora_cb') else False)
        corpus_size = self._eligible_corpus_size() \
            if hasattr(self, '_eligible_corpus_size') else 0

        rec = recommend_lora_params(
            base_model_id=base_model,
            use_qlora=use_qlora,
            corpus_size=corpus_size,
        )
        # Apply the recommendation. Clamp into the spin's range so a
        # very-low-RAM host that gets r=4 doesn't underflow the spin's
        # minimum (2 by configuration).
        new_r = max(self.lora_r_spin.minimum(),
                    min(self.lora_r_spin.maximum(), rec["r"]))
        self.lora_r_spin.setValue(new_r)

        # Convert the rationale to HTML with line breaks
        rationale_html = "<br>".join(
            "• " + line for line in rec["rationale"].split("\n"))
        self.lora_rationale_label.setText(
            f"<b>Suggested r={new_r}, alpha={rec['alpha']}</b><br>"
            f"{rationale_html}")
        self.lora_rationale_label.setVisible(True)

    def _refresh_convert_mlx_button(self):
        """Enable / disable + tooltip the convert-to-MLX button based
        on platform + mlx_lm availability. Called at build time and
        again whenever the test_model_combo selection changes (a
        non-trained-adapter selection should also disable)."""
        from src.ai.mlx_conversion import can_convert_to_mlx
        status = can_convert_to_mlx()
        if not status.available:
            self.convert_mlx_btn.setEnabled(False)
            self.convert_mlx_btn.setToolTip(status.help_text())
            return
        self.convert_mlx_btn.setEnabled(True)
        self.convert_mlx_btn.setToolTip(
            "Fuse the LoRA adapter into the base model, then "
            "quantize to MLX format for fast Apple-Silicon native "
            "inference. The original PyTorch adapter stays "
            "untouched — conversion produces a new ``-mlx`` "
            "directory beside it that the Hub picks up "
            "automatically.")

    def _convert_selected_to_mlx(self):
        """Run MLX conversion on the model currently selected in the
        Step 4 model picker. Validates: must be a trained adapter
        with a known base_model, and the platform must support
        conversion. Conversion runs in a worker thread."""
        from src.ai.mlx_conversion import can_convert_to_mlx
        status = can_convert_to_mlx()
        if not status.available:
            QMessageBox.information(
                self, "MLX conversion not available",
                status.help_text())
            return

        path = self.test_model_combo.currentData()
        if not path or not Path(path).exists():
            QMessageBox.information(
                self, "Pick a trained model",
                "Select a trained adapter from the list first. "
                "Built-in pretrained models can't be converted "
                "(there's nothing to fuse).")
            return

        # Find registry entry to get the base_model. mlx_lm.fuse
        # needs the upstream HF id — we don't know it from the
        # adapter directory alone.
        entry = next((m for m in load_trained_models()
                      if m.get("path") == path), None)
        if entry is None:
            QMessageBox.warning(
                self, "Not in registry",
                "This model isn't in the trained-models registry. "
                "Click 'Done' first to register it, then retry.")
            return
        base_model = entry.get("base_model") or ""
        if not base_model:
            QMessageBox.warning(
                self, "Missing base model",
                "The registry entry has no base_model field — "
                "can't fuse the adapter without it. Manually edit "
                "trained_models.json to add it, or re-train.")
            return

        # Confirmation dialog. Show what'll be created, with a
        # cost-of-disk note since the fused intermediate is large.
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setWindowTitle("Convert to MLX")
        confirm.setText(
            f"<b>Convert '{entry['name']}' to MLX format?</b><br><br>"
            f"<b>Base:</b> {base_model}<br>"
            f"<b>Quantization:</b> 4-bit<br><br>"
            f"This will:<br>"
            f"&nbsp;&nbsp;1. Load the base + apply the adapter, "
            f"then save the fused PyTorch model as "
            f"<code>{entry['name']}-fused/</code> "
            f"(non-quantized fallback).<br>"
            f"&nbsp;&nbsp;2. Quantize and save the MLX-native "
            f"version as <code>{entry['name']}-mlx/</code>.<br><br>"
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"The original adapter is not touched. Conversion takes "
            f"a few minutes and ~10-30 GB of disk depending on base "
            f"size.</span>")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Yes)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        self.convert_mlx_btn.setEnabled(False)
        self._mlx_worker = _MlxConversionWorker(
            adapter_dir=Path(path),
            base_model=base_model,
            adapter_name=entry["name"],
            parent=self,
        )
        # Conversion is slow — surface progress to the train_log
        # pane (which lives on Step 3 but persists across navigation)
        # AND to a transient status line on Step 4.
        self._mlx_worker.log.connect(self.train_log.appendPlainText)
        self._mlx_worker.finished_ok.connect(self._on_mlx_conversion_done)
        self._mlx_worker.failed.connect(self._on_mlx_conversion_failed)
        self._mlx_worker.start()
        self.train_log.appendPlainText(
            f"[mlx] Starting conversion of '{entry['name']}'…")

    def _on_mlx_conversion_done(self, mlx_path: str, fused_path: str,
                                 base_model: str, source_name: str):
        """MLX conversion finished — register both produced dirs.

        Two new registry entries:
          * ``<source>-fused`` — non-quantized PyTorch fallback. Tagged
            ``intent`` from the source so it routes the same way.
          * ``<source>-mlx`` — quantized MLX, tagged framework=mlx so
            the cache picks the right loader.
        """
        self.convert_mlx_btn.setEnabled(True)
        from src.config.creativeos_config import register_trained_model
        # Try to mirror metadata from the source entry.
        source_entry = next(
            (m for m in load_trained_models()
             if m.get("name") == source_name), None) or {}
        common = dict(
            base_model=base_model,
            dataset_size=source_entry.get("dataset_size", 0),
            intent=source_entry.get("intent", ""),
            genres=source_entry.get("genres") or [],
            tones=source_entry.get("tones") or [],
            continued_from=source_name,
        )
        if fused_path:
            register_trained_model(
                name=f"{source_name}-fused",
                path=fused_path,
                notes=("PyTorch fused fallback — base + adapter "
                       "merged, no quantization."),
                **common)
        register_trained_model(
            name=f"{source_name}-mlx",
            path=mlx_path,
            notes=("MLX 4-bit quantized — for Apple Silicon "
                   "native inference."),
            **common)
        self.train_log.appendPlainText(
            f"[mlx] ✓ Conversion complete. Registered "
            f"'{source_name}-mlx' and '{source_name}-fused'.")
        QMessageBox.information(
            self, "Conversion complete",
            f"MLX-format model registered as "
            f"'{source_name}-mlx'.\n\n"
            f"PyTorch fused fallback also saved as "
            f"'{source_name}-fused' in case you need to re-quantize "
            f"at a different bit-width or fall back to PyTorch.\n\n"
            f"Both are now visible in the Local Models Hub and "
            f"selectable on Step 4.")
        self._refresh_trained_models()
        self._refresh_continue_combo()

    def _on_mlx_conversion_failed(self, msg: str):
        self.convert_mlx_btn.setEnabled(True)
        self.train_log.appendPlainText(f"[mlx] ⚠ FAILED: {msg}")
        QMessageBox.warning(
            self, "MLX conversion failed",
            f"Conversion failed:\n\n{msg}\n\n"
            f"The original PyTorch adapter is unchanged. Common "
            f"causes: mlx_lm version mismatch with the base "
            f"architecture, insufficient disk for the fused dir, "
            f"or a base-model id the HF hub can't resolve.")

    def _open_modal_credentials(self):
        """Open the Modal-credentials dialog. Modal access is shared
        across runs, so we don't tie this to any single training
        session — the dialog persists tokens to the OS keystore and
        the cloud module picks them up on the next submit."""
        dlg = _ModalCredentialsDialog(parent=self)
        dlg.exec()

    def _train_on_modal(self):
        """Submit this training run to Modal's cloud GPUs.

        Flow mirrors ``_start_training`` for the prep phase (memory
        check, genre verification, dataset export, name-collision
        rename) so the cloud and local paths produce comparable
        adapters. The differences are:

          * Memory check is *informational* — Modal's GPU has its
            own RAM, the local check is just a sanity ping that the
            studio can do the LOCAL post-download work (registering
            the adapter, refreshing the picker).
          * Cost estimate dialog before submission.
          * The actual training fires in ``_ModalTrainingWorker``,
            not the local trainer thread.
        """
        from src.cloud import modal_train

        status = modal_train.check_setup()
        if not status.ready:
            QMessageBox.information(
                self, "Modal not ready",
                "Modal cloud training needs a one-time setup:\n\n"
                f"{status.help_text()}\n\n"
                "After that, click 'Train on Modal' again.")
            return

        # Reuse the existing dataset-prep pipeline. We *don't* call
        # _free_memory_for_training_or_abort — the heavy GPU work
        # happens on Modal, not locally, so we don't need to evict
        # local LLM weights.
        if not self._verify_relevant_corpora_or_offer_download():
            return

        prep = self._prepare_training_dataset()
        if prep is None:
            return  # the helper already showed a warning
        dataset_path, n_rows, ds_extra = prep

        # Same pre-training quality gate as the local path — even
        # more important here since Modal runs cost real money.
        if not self._gate_corpus_quality(dataset_path):
            return

        # Build the config dict that gets shipped to Modal. Mirrors
        # the local trainer's TrainingArguments inputs so the same
        # recipe behaves the same on both sides.
        base_model = self.base_model_combo.currentText().strip()
        if not base_model:
            QMessageBox.warning(self, "Pick a base model",
                                "Choose a base model first.")
            return

        try:
            from src.data.model_registry import _size_from_id
            base_size_b = _size_from_id(base_model) or 0.0
        except Exception:
            base_size_b = 0.0

        # Resolve the intent for overspend rules.
        recipe = getattr(self, '_current_recipe', None)
        intent = (getattr(recipe, "intent", "") or "").lower() or "general"

        # Open the preset-picker confirm dialog. User picks Economy
        # / Balanced / Performance; we read the chosen preset's GPU
        # back from the dialog before submitting.
        confirm_dlg = _ModalConfirmDialog(
            base_model=base_model,
            base_size_b=base_size_b or 7.0,
            n_rows=n_rows,
            epochs=self.epochs_spin.value(),
            use_qlora=self.qlora_cb.isChecked(),
            intent=intent,
            parent=self)
        if confirm_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = confirm_dlg.chosen_profile()
        gpu = chosen.gpu
        low = chosen.cost_low
        high = chosen.cost_high

        name = self.name_edit.text().strip() or "modal-run"
        # Match the local-path collision avoidance.
        if (TRAINED_MODELS_DIR / name).exists():
            counter = 2
            while (TRAINED_MODELS_DIR / f"{name}-v{counter}").exists():
                counter += 1
            name = f"{name}-v{counter}"
            self.name_edit.setText(name)

        config = {
            "name": name,
            "base_model": base_model,
            "epochs": self.epochs_spin.value(),
            "learning_rate": self.lr_spin.value(),
            "batch_size": self.batch_spin.value(),
            "lora_r": self.lora_r_spin.value(),
            "use_qlora": self.qlora_cb.isChecked(),
            "max_length": 512,
            "estimated_rows": n_rows,
            "base_model_size_b": base_size_b,
        }

        self.train_log.appendPlainText(
            f"[modal] Submitting '{name}' to Modal "
            f"({gpu}, est ${low:.2f}-${high:.2f})…")
        self.start_btn.setEnabled(False)
        self.modal_train_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate

        self._modal_worker = _ModalTrainingWorker(
            jsonl_path=dataset_path,
            config=config,
            gpu=gpu,
            adapter_name=name,
            parent=self,
        )
        self._modal_worker.log.connect(self.train_log.appendPlainText)
        self._modal_worker.finished_ok.connect(self._on_modal_done)
        self._modal_worker.failed.connect(self._on_modal_failed)
        self._modal_worker.start()

    def _open_smart_pick(self) -> None:
        """Open the smart-pick corpus downloader dialog.

        Resolves the user's current intent + genres + tones and
        passes them to ``_SmartDownloadDialog``, which runs the
        recommender (deterministic + optional LLM agentic
        refinement when an LLM is configured) and lets the user
        review + confirm before any downloads start.
        """
        intent = ""
        recipe = getattr(self, '_current_recipe', None)
        if recipe is not None:
            intent = (getattr(recipe, "intent", "") or "").lower()
        if not intent:
            try:
                intent = self._infer_intent_from_db()
            except Exception:
                intent = "general"

        ticked_genres = (self.selected_genres()
                          if hasattr(self, 'selected_genres') else [])
        ticked_tones = (self.selected_tones()
                         if hasattr(self, 'selected_tones') else [])

        if not ticked_genres and not ticked_tones:
            QMessageBox.information(
                self, "Pick genres or tones first",
                "The smart-pick recommender uses the genres and "
                "tones you've ticked on Step 1 to decide which "
                "corpora to suggest. Tick at least one before "
                "opening this dialog.")
            return

        dlg = _SmartDownloadDialog(
            db_path=self.db_path,
            intent=intent,
            genres=ticked_genres,
            tones=ticked_tones,
            llm_generate=self._build_quality_llm_hook(),
            parent=self)
        dlg.exec()
        # Refresh the DB summary line so any newly-ingested rows
        # show up in the count immediately.
        try:
            self._refresh_db_summary()
        except Exception:
            pass

    def _open_corpus_quality_check(self) -> None:
        """Standalone corpus quality preview.

        Same dialog as ``_gate_corpus_quality`` (which fires when
        the user clicks Start Training), but here it runs without
        committing to a training run. The dialog's Continue and
        Cancel buttons both close it without action — only the
        Clean button still triggers the cleaner.

        Discoverable from both Step 1 (corpus actions row) and
        Step 3 (above Start Training) so the user can run the
        check at whichever stage feels natural.
        """
        # Reuse the dataset-prep pipeline. Verifies the user has
        # data + valid sources just like Start Training would.
        prep = self._prepare_training_dataset()
        if prep is None:
            return  # helper already showed the warning
        dataset_path, _n_rows, _extras = prep

        # Build LLM hook the same way the gate does. Reuse the
        # gate's helper logic — there's no need to duplicate the
        # provider-resolution block, but we don't want to start
        # training on Continue. So call the gate's underlying
        # dialog directly with the right `parent` and ignore the
        # return code (other than the Clean shortcut).
        # Easiest path: a thin wrapper that mirrors the LLM-hook
        # discovery in `_gate_corpus_quality` but doesn't return
        # a "should I train?" bool.
        llm_generate = self._build_quality_llm_hook()

        intent = ""
        recipe = getattr(self, '_current_recipe', None)
        if recipe is not None:
            intent = (getattr(recipe, "intent", "") or "").lower()
        if not intent:
            try:
                intent = self._infer_intent_from_db()
            except Exception:
                intent = "general"

        ticked_genres = (self.selected_genres()
                          if hasattr(self, 'selected_genres') else [])
        ticked_tones = (self.selected_tones()
                         if hasattr(self, 'selected_tones') else [])

        dlg = _CorpusQualityDialog(
            jsonl_path=dataset_path,
            intent=intent,
            selected_genres=ticked_genres,
            selected_tones=ticked_tones,
            llm_generate=llm_generate,
            parent=self)
        # Swap the Continue button text so the user knows clicking
        # it doesn't kick off training in this standalone mode.
        try:
            dlg.continue_btn.setText("✓ Looks good")
            dlg.continue_btn.setToolTip(
                "Close the dialog. Quality check is informational "
                "only — to actually train, click Start Training "
                "or Train on Modal on Step 3.")
        except Exception:
            pass

        result = dlg.exec()
        # Clean shortcut still works the same way as the gate path.
        if result == _CorpusQualityDialog.CLEAN_REQUESTED:
            try:
                self._open_clean_corpus_dialog()
            except Exception as e:
                QMessageBox.warning(
                    self, "Cleaner unavailable",
                    f"Could not open cleaner: {e}")

    def _build_quality_llm_hook(self):
        """Return a ``(prompt, system) -> str`` callable that uses
        the configured CreativeOS LLM, or ``None`` when no LLM is
        available. Used by both the standalone quality check and
        the pre-training gate so they get identical AI-opinion
        behaviour."""
        try:
            from src.config.creativeos_config import get_creativeos_config
            cfg = get_creativeos_config()
            if cfg.get("disable_all_ai") or not cfg.has_llm_configured():
                return None
            from src.ai.llm_client import (
                LLMClient, LLMProvider, HuggingFaceConfig,
            )
            s = cfg.shared_llm_settings()
            if (s.get("prefer_local_model")
                    and s.get("enable_local_models")
                    and s.get("local_model_id")):
                is_mlx = "mlx" in s["local_model_id"].lower()
                hf_config = HuggingFaceConfig(
                    model_id=s["local_model_id"], use_local=True,
                    device=s.get("local_model_device", "auto"),
                    quantization=(
                        s.get("local_model_quantization", "none")
                        if s.get("local_model_quantization") != "none"
                        else None),
                )
                provider = (LLMProvider.MLX_LOCAL if is_mlx
                            else LLMProvider.HUGGINGFACE_LOCAL)
                llm = LLMClient(provider=provider, hf_config=hf_config)
            else:
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI,
                }
                provider_name = s.get("default_llm", "claude")
                api_key = (
                    s.get("claude_api_key")
                    if provider_name == "claude"
                    else s.get("chatgpt_api_key")
                    if provider_name in ("chatgpt", "openai")
                    else s.get("gemini_api_key"))
                if not api_key:
                    return None
                llm = LLMClient(
                    provider=provider_map.get(
                        provider_name, LLMProvider.CLAUDE),
                    api_key=api_key)
            return lambda prompt, system: llm.generate_text(
                prompt, system, max_tokens=600, temperature=0.3)
        except Exception:
            return None

    def _gate_corpus_quality(self, jsonl_path: Path) -> bool:
        """Show the corpus-quality dialog. Returns True iff the user
        clicked Continue.

        Three exit paths:
          * Continue → True, training proceeds.
          * Cancel → False, training does not proceed.
          * Clean → False AND we open the 🧹 retroactive cleaner so
            the user can fix the data and re-run training. Same
            return value as Cancel because we still abort *this*
            attempt — the user has to click Start Training again
            after cleaning.
        """
        # Build an LLM hook for the dialog if one's configured.
        # Same plumbing as the standalone quality-check button.
        llm_generate = self._build_quality_llm_hook()

        intent = ""
        recipe = getattr(self, '_current_recipe', None)
        if recipe is not None:
            intent = (getattr(recipe, "intent", "") or "").lower()
        if not intent:
            # Fall back to inferred intent if no recipe.
            try:
                intent = self._infer_intent_from_db()
            except Exception:
                intent = "general"

        ticked_genres = (self.selected_genres()
                          if hasattr(self, 'selected_genres') else [])
        ticked_tones = (self.selected_tones()
                        if hasattr(self, 'selected_tones') else [])

        dlg = _CorpusQualityDialog(
            jsonl_path=jsonl_path,
            intent=intent,
            selected_genres=ticked_genres,
            selected_tones=ticked_tones,
            llm_generate=llm_generate,
            parent=self)
        result = dlg.exec()
        if result == _CorpusQualityDialog.CLEAN_REQUESTED:
            # User wants to clean before training. Open the
            # retroactive cleaner; abort this training attempt.
            self.train_log.appendPlainText(
                "[quality] User chose to clean before training. "
                "Opening cleaner — re-click Start Training when done.")
            try:
                self._open_clean_corpus_dialog()
            except Exception as e:
                QMessageBox.warning(
                    self, "Cleaner unavailable",
                    f"Could not open cleaner: {e}")
            return False
        if result == QDialog.DialogCode.Accepted:
            return True
        # Cancelled.
        self.train_log.appendPlainText(
            "[quality] Training cancelled at quality gate.")
        return False

    def _prepare_training_dataset(self):
        """Run the shared dataset-export pipeline. Returns
        ``(jsonl_path, n_rows, extra_dict)`` or None if the user
        should not proceed.

        Extracted so ``_start_training`` (local) and
        ``_train_on_modal`` (cloud) share the same prep logic — same
        rating filter, same source-type pick, same genre/collection
        filters, same user-voice oversample. The two paths only
        diverge in *where* the trainer runs.
        """
        tmp = TRAINED_MODELS_DIR / "_tmp_dataset.jsonl"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        min_rating = self.train_min_rating.currentData()
        sources = self._selected_source_types()
        if not sources:
            QMessageBox.warning(
                self, "No Sources",
                "Pick at least one data source on Step 1 before training.")
            return None
        try:
            db = RephraseDatabase(self.db_path)
            # Per-source eligible row counts at the user's current
            # rating threshold. ``counts_by_source`` is the actual
            # API name on RephraseDatabase — an earlier extraction
            # of _prepare_training_dataset accidentally called a
            # method that didn't exist (eligible_row_count_per_source).
            breakdown = db.counts_by_source(
                min_rating=min_rating, only_accepted=True)
            per_source = [(st, breakdown.get(st, 0)) for st in sources]
            non_empty_total = sum(n for _, n in per_source)
            if non_empty_total == 0:
                QMessageBox.warning(
                    self, "No Training Data",
                    f"None of the selected sources have rows that pass "
                    f"the '{min_rating}' rating filter.")
                return None

            oversample = 1
            recipe = getattr(self, '_current_recipe', None)
            if recipe is not None:
                oversample = max(1, int(
                    getattr(recipe, "user_voice_oversample", 1)))
            ticked_genres = self.selected_genres()
            collection_keys = self._selected_collection_keys
            n = db.export_jsonl(
                tmp, fmt="instruction", min_rating=min_rating,
                source_types=sources,
                user_voice_oversample=oversample,
                genre_filter=ticked_genres or None,
                corpus_collection_keys=collection_keys)
            if n == 0:
                QMessageBox.warning(
                    self, "No Training Data",
                    "Export produced 0 examples.")
                return None
        except Exception as e:
            QMessageBox.warning(self, "Dataset Error",
                                f"Could not prepare dataset: {e}")
            return None

        return tmp, n, {"oversample": oversample,
                        "ticked_genres": ticked_genres}

    def _on_modal_done(self, output_path: str, result_meta: dict):
        """Modal training finished — register and surface."""
        self.start_btn.setEnabled(True)
        self.modal_train_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        try:
            db_count = RephraseDatabase(self.db_path).count()
        except Exception:
            db_count = 0
        intent = ""
        genres: list = []
        tones: list = []
        try:
            recipe = getattr(self, '_current_recipe', None)
            if recipe is not None:
                intent = (getattr(recipe, "intent", "") or "").lower()
                genres = list(getattr(recipe, "detected_genres", []) or [])
            if hasattr(self, 'selected_tones'):
                tones = list(self.selected_tones())
        except Exception:
            pass

        from src.config.creativeos_config import register_trained_model
        entry = register_trained_model(
            name=self.name_edit.text().strip() or "modal-run",
            path=output_path,
            base_model=self.base_model_combo.currentText().strip(),
            dataset_size=db_count,
            intent=intent,
            genres=genres,
            tones=tones,
            notes=(f"trained on Modal "
                   f"({result_meta.get('rows_trained', '?')} rows, "
                   f"{result_meta.get('rows_evaluated', 0)} eval)"),
        )
        self.train_log.appendPlainText(
            f"[modal] ✓ Saved to {output_path} as '{entry['name']}'.")
        QMessageBox.information(
            self, "Modal Training Complete",
            f"Model saved at:\n{output_path}\n\n"
            f"Registered as '{entry['name']}'. Available now in the "
            f"Local Models Hub and any per-task pickers.")
        self._refresh_continue_combo()
        self._refresh_trained_models()
        self.stack.setCurrentIndex(3)
        self._update_nav()

        # Offer MLX conversion as a follow-up if we're on Apple
        # Silicon — this is the recommended workflow when the user
        # trained on Modal (PyTorch base) but wants to run on their
        # local Mac (MLX) for inference. The original PyTorch
        # adapter stays as a non-MLX fallback so a conversion
        # failure isn't a dead-end.
        self._maybe_offer_mlx_conversion(
            adapter_dir=Path(output_path),
            base_model=self.base_model_combo.currentText().strip(),
            adapter_name=entry["name"],
            source_label="Modal training")

    def _maybe_offer_mlx_conversion(self, *,
                                     adapter_dir: Path,
                                     base_model: str,
                                     adapter_name: str,
                                     source_label: str = "training"):
        """Post-training prompt: convert the just-finished adapter
        to MLX format. No-op if conversion isn't available on this
        machine (non-Apple Silicon, or mlx_lm not installed) — the
        prompt would be misleading.
        """
        from src.ai.mlx_conversion import can_convert_to_mlx
        status = can_convert_to_mlx()
        if not status.available:
            return  # silent no-op — can't convert here

        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setWindowTitle("Convert to MLX?")
        prompt.setText(
            f"<b>Convert '{adapter_name}' to MLX format now?</b><br><br>"
            f"You're on Apple Silicon, so the {source_label} result "
            f"can be fused + quantized for native MLX inference. "
            f"The original PyTorch adapter stays as-is — conversion "
            f"adds two new entries (<code>{adapter_name}-fused</code> "
            f"and <code>{adapter_name}-mlx</code>) without touching "
            f"it.<br><br>"
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"You can also do this later from Step 4 — "
            f""
            f"this prompt is the convenient default.</span>")
        prompt.setStandardButtons(
            QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Yes)
        prompt.setDefaultButton(QMessageBox.StandardButton.Yes)
        if prompt.exec() != QMessageBox.StandardButton.Yes:
            return
        # Trigger the same worker the Step-4 button uses.
        if not (adapter_dir / "adapter_config.json").exists():
            QMessageBox.information(
                self, "Skipping conversion",
                "The just-trained model isn't in adapter format — "
                "MLX conversion only applies to LoRA adapters.")
            return
        self.convert_mlx_btn.setEnabled(False)
        self._mlx_worker = _MlxConversionWorker(
            adapter_dir=adapter_dir,
            base_model=base_model,
            adapter_name=adapter_name,
            parent=self)
        self._mlx_worker.log.connect(self.train_log.appendPlainText)
        self._mlx_worker.finished_ok.connect(self._on_mlx_conversion_done)
        self._mlx_worker.failed.connect(self._on_mlx_conversion_failed)
        self._mlx_worker.start()
        self.train_log.appendPlainText(
            f"[mlx] Starting conversion of just-trained "
            f"'{adapter_name}'…")

    def _on_modal_failed(self, msg: str):
        self.start_btn.setEnabled(True)
        self.modal_train_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.train_log.appendPlainText(f"[modal] ⚠ FAILED: {msg}")
        QMessageBox.warning(self, "Modal Training Failed", msg)

    def _start_training(self):
        # Free up RAM before training — fine-tuning loads its own copy of
        # the base model + dataset, and competing with a chat/rephrase
        # model loaded by another tool is the #1 cause of OOMs on this
        # machine. We never silently unload: the user gets a confirmation
        # dialog naming each loaded model and is told that their
        # selection (in CreativeOS settings) stays — only the in-memory
        # weights are dropped, ready to reload on next use.
        if not self._free_memory_for_training_or_abort():
            return

        # Genre verification: any genres ticked on Step 1 must have
        # their catalog corpora ingested before training, otherwise
        # the model trains on user data alone and the genre tick was
        # silently meaningless. Offer a one-shot download.
        if not self._verify_relevant_corpora_or_offer_download():
            return

        # Always re-export with the current rating filter AND the user's
        # source-type selection so the model only sees the data they
        # actually want to train on.
        tmp = TRAINED_MODELS_DIR / "_tmp_dataset.jsonl"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        min_rating = self.train_min_rating.currentData()
        sources = self._selected_source_types()
        if not sources:
            QMessageBox.warning(
                self, "No Sources",
                "Pick at least one data source on Step 1 before training.")
            return
        try:
            db = RephraseDatabase(self.db_path)

            # Surface what's *actually* eligible per source so the user
            # can spot a checkbox that's contributing nothing (e.g. they
            # ticked "Worldbuilding" but never opted into capture).
            breakdown = db.counts_by_source(
                min_rating=min_rating, only_accepted=True)
            per_source = [(st, breakdown.get(st, 0)) for st in sources]
            empty = [st for st, n in per_source if n == 0]
            non_empty_total = sum(n for _, n in per_source)

            self.train_log.appendPlainText(
                f"[setup] Eligible rows per selected source "
                f"(rating ≥ {min_rating}):"
            )
            for st, count in per_source:
                marker = " ⚠ EMPTY" if count == 0 else ""
                self.train_log.appendPlainText(
                    f"          {st:<14}  {count:>5}{marker}")
            if empty:
                self.train_log.appendPlainText(
                    f"[setup] WARNING: {len(empty)} selected source(s) "
                    f"have 0 rows on disk: {', '.join(empty)}. They will "
                    f"contribute nothing to training. Uncheck them or "
                    f"collect data first.")
            if non_empty_total == 0:
                QMessageBox.warning(
                    self, "No Training Data",
                    f"None of the selected sources have rows that pass "
                    f"the '{min_rating}' rating filter.\n\n"
                    f"Lower the rating bar, pick more sources, or "
                    f"collect more data first.")
                return

            # Pull the user-voice oversample factor from the active
            # recipe (or default to 1 if no recipe was built). Voice
            # intent recipes default to 8× so the user's rephrase rows
            # dominate over genre-corpus rows, ensuring the trained
            # model rephrases in the user's voice — not Bram Stoker's.
            oversample = 1
            recipe = getattr(self, '_current_recipe', None)
            if recipe is not None:
                oversample = max(1, int(
                    getattr(recipe, "user_voice_oversample", 1)))
            # Genre filter: if the user has ticked any genres on Step 1,
            # only include corpus rows whose genre tag overlaps. This
            # is what makes "imported a horror project, training a
            # romance model" do the right thing — the horror chapters
            # are skipped automatically.
            ticked_genres = self.selected_genres()
            collection_keys = self._selected_collection_keys
            n = db.export_jsonl(
                tmp, fmt="instruction", min_rating=min_rating,
                source_types=sources,
                user_voice_oversample=oversample,
                genre_filter=ticked_genres or None,
                corpus_collection_keys=collection_keys)
            if ticked_genres:
                self.train_log.appendPlainText(
                    f"[setup] Genre filter active: corpus rows must "
                    f"match {ticked_genres} (untagged corpus rows pass "
                    f"through as generic context).")
            if collection_keys is not None:
                self.train_log.appendPlainText(
                    f"[setup] Corpus filter: only "
                    f"{len(collection_keys)} of "
                    f"{len(db.list_corpus_collections())} ingested "
                    f"collection(s) feed this run.")
            if n == 0:
                QMessageBox.warning(
                    self, "No Training Data",
                    f"Export produced 0 examples even though source "
                    f"counts were non-zero. This usually means rows "
                    f"failed format conversion. Check the database "
                    f"for malformed entries.")
                return
            self.dataset_jsonl = tmp

            # Confirmation line — the user can verify file size matches
            # what they'd expect for the row count.
            try:
                size_kb = tmp.stat().st_size / 1024
                size_str = (f"{size_kb:.1f}KB" if size_kb < 1024
                            else f"{size_kb/1024:.1f}MB")
            except Exception:
                size_str = "?"
            extra = (f", user-voice rows ×{oversample}"
                     if oversample > 1 else "")
            self.train_log.appendPlainText(
                f"[setup] Exported {n} examples ({size_str}{extra}) to {tmp}")
        except Exception as e:
            QMessageBox.warning(self, "Dataset Error",
                                f"Could not prepare dataset: {e}")
            return

        # Pre-training quality gate. Shows stats + samples + verdict
        # before the GPU work starts. User can Continue, Cancel, or
        # Clean (which closes this flow and opens the retroactive
        # cleaner). If they cancel/clean, we don't kick off the
        # trainer.
        if not self._gate_corpus_quality(tmp):
            return

        name = self.name_edit.text().strip() or "untitled"
        # Always train into a NEW directory so a previous model with the
        # same name is never destroyed. We auto-suffix with a counter.
        out_dir = TRAINED_MODELS_DIR / name
        if out_dir.exists():
            counter = 2
            while (TRAINED_MODELS_DIR / f"{name}-v{counter}").exists():
                counter += 1
            new_name = f"{name}-v{counter}"
            QMessageBox.information(
                self, "Auto-renamed",
                f"A model named '{name}' already exists.\n"
                f"Training output will go to '{new_name}' so the "
                f"original stays intact.")
            name = new_name
            self.name_edit.setText(name)
            out_dir = TRAINED_MODELS_DIR / name

        # Continue-from path. The combo's data is the trained-model
        # *adapter* directory — but we can't load that as a base
        # model directly: it only contains adapter weights. We need
        # the original base_model id stored alongside the adapter in
        # the registry. The worker then loads base + adapter
        # separately via PeftModel.from_pretrained.
        continue_path = self.continue_combo.currentData() if hasattr(self, 'continue_combo') else ""
        adapter_path = ""
        if continue_path:
            from src.config.creativeos_config import load_trained_models
            entry = next((m for m in load_trained_models()
                          if m.get("path") == continue_path), None)
            if entry is None:
                QMessageBox.warning(
                    self, "Continue-from broken",
                    f"Couldn't find a registry entry for the chosen "
                    f"continue-from path:\n{continue_path}\n\n"
                    f"It may have been removed or never registered. "
                    f"Reverting to fresh training.")
            else:
                adapter_path = continue_path
                base_to_train = entry.get("base_model", "")
                if not base_to_train:
                    QMessageBox.warning(
                        self, "Continue-from broken",
                        f"The registry entry for '{entry.get('name')}' "
                        f"has no base_model field. Can't continue.")
                    adapter_path = ""
                else:
                    self.train_log.appendPlainText(
                        f"[setup] Continuing training of adapter "
                        f"'{entry.get('name')}' on top of base model "
                        f"{base_to_train}.")
        if not adapter_path:
            base_to_train = self.base_model_combo.currentText().strip()

        # Pre-flight memory advisory. Estimate the base model's RAM
        # footprint and compare against available memory. The estimate
        # is a rough rule-of-thumb (params * 2 bytes for bf16, or
        # params / 2 for QLoRA 4-bit). We only block when memory looks
        # *catastrophically* tight; otherwise we warn and let the user
        # decide. Skipped silently if psutil isn't installed.
        if not self._check_memory_before_training(
                base_to_train, use_qlora=self.qlora_cb.isChecked()):
            return  # user cancelled after the warning

        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.worker = _TrainingWorker(
            jsonl_path=self.dataset_jsonl,
            base_model=base_to_train,
            output_dir=out_dir,
            epochs=self.epochs_spin.value(),
            learning_rate=self.lr_spin.value(),
            batch_size=self.batch_spin.value(),
            lora_r=self.lora_r_spin.value(),
            use_qlora=self.qlora_cb.isChecked(),
            adapter_path=adapter_path,
        )
        self.worker.log.connect(self.train_log.appendPlainText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_training_done)
        self.worker.failed.connect(self._on_training_failed)
        self.worker.start()

        # Push the now-running recipe onto the recent-history ring
        # buffer so the user can come back later and re-train with a
        # single click. Capped at 3; same-name overrides the older.
        try:
            from src.config.training_presets import add_recent
            recent_preset = self._capture_current_preset(
                name=name, is_recent=True)
            add_recent(recent_preset)
            self._refresh_preset_combo()
        except Exception as e:
            # Non-fatal — training itself is not affected by preset I/O.
            print(f"[training_studio] could not push recent preset: {e}")

    def _on_progress(self, step: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(step)

    def _on_training_done(self, output_path: str):
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        try:
            db_count = RephraseDatabase(self.db_path).count()
        except Exception:
            db_count = 0
        # Capture the recipe metadata so the registry entry carries
        # intent + genre + tone tags. The test step uses these to
        # group models by task; the writing tool's task-router uses
        # intent to pick the right model for each request.
        intent = ""
        genres: list = []
        tones: list = []
        continued_from = ""
        try:
            recipe = getattr(self, '_current_recipe', None)
            if recipe is not None:
                intent = getattr(recipe, "intent", "") or ""
                genres = list(getattr(recipe, "detected_genres", []) or [])
            if hasattr(self, 'selected_tones'):
                tones = list(self.selected_tones())
            cont = (self.continue_combo.currentData()
                    if hasattr(self, 'continue_combo') else "")
            if cont:
                # Find the lineage entry by path so we can store its name.
                from src.config.creativeos_config import load_trained_models
                prior = next((m for m in load_trained_models()
                              if m.get("path") == cont), None)
                if prior:
                    continued_from = prior.get("name", "")
        except Exception:
            pass
        entry = register_trained_model(
            name=self.name_edit.text().strip() or "untitled",
            path=output_path,
            base_model=self.base_model_combo.currentText().strip(),
            dataset_size=db_count,
            intent=intent,
            genres=genres,
            tones=tones,
            continued_from=continued_from,
        )
        self.train_log.appendPlainText(
            f"[done] Saved to {output_path}. Registered as '{entry['name']}'.")
        QMessageBox.information(
            self, "Training Complete",
            f"Model saved at:\n{output_path}\n\n"
            f"It's registered under '{entry['name']}'. The Writing Tool's "
            f"Local Models tab will list it next time you open Settings.")
        # Refresh the picker so the new model is available for the next run
        self._refresh_continue_combo()
        self._refresh_trained_models()
        self.stack.setCurrentIndex(3)
        self._update_nav()

        # Offer MLX conversion when running on Apple Silicon. Same
        # flow as the Modal post-training prompt — non-Apple-Silicon
        # users see no prompt at all.
        self._maybe_offer_mlx_conversion(
            adapter_dir=Path(output_path),
            base_model=self.base_model_combo.currentText().strip(),
            adapter_name=entry["name"],
            source_label="local training")

    def _on_training_failed(self, msg: str):
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "Training Failed", msg)

    # ── Step 4: model management ──

    def _build_step_test(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Step 4 — Model Management</b>"))
        intro = QLabel(
            "Test, convert, continue-train, or delete any registered "
            "model. Trained adapters can be converted to MLX format "
            "for native Apple-Silicon inference (when available)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding-bottom: 6px;")
        layout.addWidget(intro)

        form = QFormLayout()
        self.test_model_combo = QComboBox()
        self._refresh_trained_models()
        form.addRow("Model:", self.test_model_combo)

        # Test-as-intent override. Legacy models (trained before the
        # registry started storing intent) fall back to a DB-inferred
        # default — but if the inference is wrong, the user can pick
        # the right intent here. Wrong intent at test time = wrong
        # prompt format = repetition / garbage output (the user hit
        # "Passage: Passage:" loops on a voice-trained model that was
        # being tested with a rephrase prompt).
        self.test_intent_override = QComboBox()
        self.test_intent_override.addItem("Auto (registry → DB inference)", "")
        self.test_intent_override.addItem("Voice / continuation", "voice")
        self.test_intent_override.addItem("Rephrase", "rephrase")
        self.test_intent_override.addItem("Plot / outline", "plot")
        self.test_intent_override.addItem("Worldbuilding", "worldbuilding")
        self.test_intent_override.addItem("Character", "character")
        self.test_intent_override.addItem("Chat", "chat")
        self.test_intent_override.setToolTip(
            "What kind of model is this? Auto picks from the registry "
            "(modern runs) or the dominant DB source_type (legacy "
            "runs). Override only when the auto-pick is wrong — "
            "wrong intent means wrong prompt format, which produces "
            "garbage output even on a well-trained model.")
        form.addRow("Test as:", self.test_intent_override)

        # Manage trained models — opens a dialog where the user can
        # delete models. Deletion cascades: the model directory is
        # wiped, the registry entry is removed, and any per-task
        # setting in CreativeOS pointing at that model is cleared
        # (the per-task resolver falls back through general → global
        # automatically, so a deleted task model just reverts to the
        # default — no user-visible breakage).
        manage_row = QHBoxLayout()
        manage_row.addStretch()
        self.manage_trained_btn = QPushButton(
            "🗑 Manage trained models…")
        self.manage_trained_btn.setToolTip(
            "View every locally-trained model. Deleting one removes "
            "its files and clears any tool that was pointing at it — "
            "settings revert to defaults so nothing is left in a "
            "broken state.")
        self.manage_trained_btn.clicked.connect(
            self._open_manage_trained_models)
        manage_row.addWidget(self.manage_trained_btn)
        form.addRow("", self._row_widget(manage_row))
        layout.addLayout(form)

        self.test_input = QTextEdit()
        self.test_input.setPlaceholderText(
            "Enter a passage to rephrase (the model will receive an "
            "instruction-tuned prompt under the hood)…")
        self.test_input.setMaximumHeight(120)
        layout.addWidget(self.test_input)

        run_row = QHBoxLayout()
        self.run_test_btn = QPushButton("Run on Trained Model")
        self.run_test_btn.clicked.connect(self._run_test)
        run_row.addWidget(self.run_test_btn)
        run_row.addStretch()
        layout.addLayout(run_row)

        self.test_output = QTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setPlaceholderText("Model output will appear here.")
        layout.addWidget(self.test_output, 1)

        # Rating panel — same widget as the Hub uses. Ratings
        # entered here flow into the same per-model JSON store, so
        # opening the history dialog from either surface shows
        # everything the user has rated. Disabled until a test
        # completes.
        from src.ui.test_history_widgets import TestRatingPanel
        self._test_rating_panel = TestRatingPanel()
        self._test_rating_panel.saved.connect(
            self._on_studio_test_saved)
        layout.addWidget(self._test_rating_panel)

        # Test history shortcut row.
        history_row = QHBoxLayout()
        history_row.addStretch()
        self.test_history_btn = QPushButton("📜 Test history")
        self.test_history_btn.setToolTip(
            "View every saved test for the selected model with "
            "category-level mean ratings. Re-rate, re-categorize, "
            "or delete records inline.")
        self.test_history_btn.clicked.connect(
            self._open_test_history)
        history_row.addWidget(self.test_history_btn)
        layout.addLayout(history_row)

        # Action row: continue training the selected model OR mark as
        # done. The two buttons cover the two ways the user wraps up:
        # "the model needs more work — train more" or "I'm satisfied —
        # save and exit". Done re-registers as a safety net for users
        # who somehow get here without a registry entry (e.g. trained
        # before the registry existed and re-opened the studio).
        action_row = QHBoxLayout()
        self.train_more_btn = QPushButton("▶ Train More on This Model")
        self.train_more_btn.setToolTip(
            "Pick up the selected trained model and run another training "
            "pass on top of it. New corpora, new ratings, more epochs — "
            "anything you've added since the last run will feed the next "
            "training. The original model stays untouched; the next run "
            "creates a new model with this one as its lineage parent.")
        self.train_more_btn.clicked.connect(self._train_more_on_selected)
        action_row.addWidget(self.train_more_btn)

        # Convert to MLX — fuses the adapter into the base, then
        # quantizes the result to MLX format for native Apple-
        # Silicon inference. Only active when (1) we're on Apple
        # Silicon and (2) mlx_lm is installed; otherwise the button
        # stays visible but disabled with a tooltip explaining why.
        # The original PyTorch adapter is never touched — conversion
        # produces a new ``-mlx`` directory beside it and registers
        # it as a separate model.
        self.convert_mlx_btn = QPushButton("🔄 Convert to MLX")
        self.convert_mlx_btn.clicked.connect(self._convert_selected_to_mlx)
        self._refresh_convert_mlx_button()
        action_row.addWidget(self.convert_mlx_btn)

        action_row.addStretch()

        self.done_btn = QPushButton("✓ Done — Save & Close")
        self.done_btn.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; "
            "padding: 6px 14px; border-radius: 5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #15803d; }")
        self.done_btn.setToolTip(
            "Confirm the trained model is saved to your local-models list "
            "and close the wizard. Models are auto-saved at training time, "
            "so this is a safety net for anyone who skipped that flow.")
        self.done_btn.clicked.connect(self._mark_done_and_close)
        action_row.addWidget(self.done_btn)
        layout.addLayout(action_row)

        return page

    def _refresh_trained_models(self):
        """Populate the Step 4 model picker, grouped by intent.

        QComboBox doesn't have native group headers, so we use a
        non-selectable disabled item per category to act as a visual
        separator. The user clicks past it to the model row underneath.
        Sort within each group by created_at descending so the freshest
        model surfaces first per category.
        """
        from PyQt6.QtGui import QStandardItem
        self.test_model_combo.clear()
        models = load_trained_models()
        if not models:
            self.test_model_combo.addItem(
                "(no trained models yet — train one on Step 3)", "")
            return

        # Group by intent. Empty-intent models (legacy entries from
        # before the registry stored intent) go under "Uncategorized"
        # so they're still reachable.
        groups: dict = {}
        for m in models:
            key = (m.get("intent") or "uncategorized").lower()
            groups.setdefault(key, []).append(m)

        # Display order: the canonical training intents first, then
        # whatever else exists, with uncategorized last.
        intent_order = ["voice", "rephrase", "plot",
                        "worldbuilding", "character", "chat"]
        seen = set()
        ordered_keys = []
        for k in intent_order:
            if k in groups:
                ordered_keys.append(k); seen.add(k)
        for k in groups:
            if k not in seen and k != "uncategorized":
                ordered_keys.append(k); seen.add(k)
        if "uncategorized" in groups:
            ordered_keys.append("uncategorized")

        intent_labels = {
            "voice": "✍️  Voice / style continuation",
            "rephrase": "🔀  Rephrase",
            "plot": "📐  Plot / outline",
            "worldbuilding": "🗺️  Worldbuilding",
            "character": "👥  Character",
            "chat": "💬  Chat",
            "uncategorized": "📦  Uncategorized",
        }
        for key in ordered_keys:
            entries = sorted(groups[key],
                             key=lambda m: m.get("created_at", ""),
                             reverse=True)
            # Non-selectable header row.
            label = intent_labels.get(key, f"📦  {key.title()}")
            self.test_model_combo.addItem(f"── {label} ──", "")
            idx = self.test_model_combo.count() - 1
            item = self.test_model_combo.model().item(idx)
            if item is not None:
                from PyQt6.QtCore import Qt
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable
                              & ~Qt.ItemFlag.ItemIsEnabled)
            for m in entries:
                lineage = (f" ← {m['continued_from']}"
                           if m.get("continued_from") else "")
                self.test_model_combo.addItem(
                    f"  {m['name']} (base: {m.get('base_model', '?')}){lineage}",
                    m.get("path", ""))

    def _train_more_on_selected(self):
        """Pick the selected trained model as the continue-from base and
        jump to Step 2 so the user can adjust hyperparams and re-run.

        The new run will inherit the prior model's adapter weights (no
        re-learning from scratch) and any new corpora / ratings the
        user has logged since. We pre-fill a default name with a v2
        suffix; the user can overwrite. Step 2 has a banner-style
        notification so it's obvious what's happening.
        """
        path = self.test_model_combo.currentData()
        if not path or not Path(path).exists():
            QMessageBox.information(
                self, "No Model Selected",
                "Pick a trained model from the list first. If the list "
                "is empty, train a model on Step 3.")
            return
        # Find the registry entry to read its name.
        entry = next((m for m in load_trained_models()
                      if m.get("path") == path), None)
        if entry is None:
            QMessageBox.warning(
                self, "Model Not in Registry",
                f"The selected model isn't in the registry. Use 'Done' "
                f"to register it first, then try again.")
            return

        # Wire continue_combo on Step 2 to this model. _refresh_continue_combo
        # populates it from the registry, then we select the matching path.
        self._refresh_continue_combo()
        for i in range(self.continue_combo.count()):
            if self.continue_combo.itemData(i) == path:
                self.continue_combo.setCurrentIndex(i)
                break

        # Suggest a v2 name so the user doesn't accidentally overwrite
        # the prior run. They can rename freely.
        prior = entry.get("name", "model")
        next_name = self._next_version_name(prior)
        if hasattr(self, 'name_edit'):
            self.name_edit.setText(next_name)

        # Banner on Step 2 so the user knows they're continuing.
        self._show_continue_banner(prior)

        # Jump to Step 2 (Configure).
        self.stack.setCurrentIndex(1)
        self._update_nav()

    @staticmethod
    def _next_version_name(prior: str) -> str:
        """Generate a fresh name for a continued-training run."""
        import re
        m = re.match(r'^(.*?)(?:[-_]v(\d+))?$', prior or "model")
        base = m.group(1) if m else (prior or "model")
        n = int(m.group(2)) if (m and m.group(2)) else 1
        # Bump until we find a name that isn't already in the registry.
        existing = {x.get("name", "") for x in load_trained_models()}
        while True:
            n += 1
            candidate = f"{base}-v{n}"
            if candidate not in existing:
                return candidate

    def _show_continue_banner(self, prior_name: str) -> None:
        """Show / refresh a one-line banner on Step 2 indicating that the
        next run will continue from ``prior_name``.

        The banner is created lazily on first use so older builds of
        Step 2 don't grow it until the user actually triggers a
        continue-training flow.
        """
        if not hasattr(self, '_continue_banner'):
            from PyQt6.QtWidgets import QLabel
            self._continue_banner = QLabel()
            self._continue_banner.setStyleSheet(
                "QLabel { background-color: #fef3c7; color: #92400e; "
                "padding: 6px 10px; border-left: 3px solid #f59e0b; "
                "border-radius: 3px; }")
            self._continue_banner.setWordWrap(True)
            # Insert at the top of Step 2 if we can find its layout.
            try:
                step2 = self.stack.widget(1)
                # Step 2 is wrapped in a scroll area; reach its inner
                # widget's layout to prepend the banner.
                inner = step2.widget() if hasattr(step2, 'widget') else step2
                if inner is None:
                    return
                lay = inner.layout()
                if lay is not None:
                    lay.insertWidget(0, self._continue_banner)
            except Exception:
                return
        self._continue_banner.setText(
            f"▶ Continuing training from <b>{prior_name}</b>. The new "
            f"run will inherit its adapter weights and add the latest "
            f"corpus / ratings on top — original model stays untouched.")
        self._continue_banner.show()

    def _mark_done_and_close(self):
        """Confirm the selected model is in the registry and close.

        Models are auto-registered at training completion, so this is
        usually a no-op. We still check and re-register defensively for
        users who somehow arrive here with an unregistered model (e.g.
        trained on an older build that didn't auto-register).
        """
        path = self.test_model_combo.currentData()
        if not path or not Path(path).exists():
            QMessageBox.information(
                self, "Pick a Model",
                "Select a trained model from the list before clicking Done. "
                "If you haven't trained one yet, go back to Step 3.")
            return
        models = load_trained_models()
        existing = next((m for m in models if m.get("path") == path), None)
        if existing is None:
            # Defensive re-register. Pull whatever we can from the
            # current wizard state; missing fields stay empty so the
            # registry remains schema-stable.
            from src.config.creativeos_config import register_trained_model
            name = (self.name_edit.text().strip()
                    if hasattr(self, 'name_edit') else "") or "untitled"
            base = (self.base_model_combo.currentText().strip()
                    if hasattr(self, 'base_model_combo') else "")
            register_trained_model(
                name=name, path=path,
                base_model=base, dataset_size=0,
                notes="re-registered via Done button")
            self._refresh_trained_models()
            QMessageBox.information(
                self, "Model Registered",
                f"Saved '{name}' to your trained-models list.")
        else:
            QMessageBox.information(
                self, "Already Saved",
                f"'{existing.get('name')}' is already in your trained-"
                f"models list. Closing.")
        self.close()

    def _infer_intent_from_db(self) -> str:
        """Guess training intent from the dominant source_type in the
        user's database.

        Used as a fallback for legacy registry entries that pre-date
        the ``intent`` field. The dominant source_type in the DB at
        training time was almost certainly the dominant source_type
        the model was trained on — there's no per-run snapshot of
        what data fed which run, but the DB at "now" is the closest
        proxy we have.

        Returns the canonical intent key ("voice", "rephrase", "plot",
        "worldbuilding", "character", "chat") for the dominant
        source_type, or "rephrase" if the DB is empty / unreadable.
        """
        try:
            from src.data.rephrase_database import (
                SOURCE_CORPUS, SOURCE_REPHRASE, SOURCE_PLOT,
                SOURCE_WORLDBUILDING, SOURCE_CHARACTER,
                SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL,
            )
            with RephraseDatabase(self.db_path)._conn() as c:
                cur = c.execute(
                    "SELECT source_type, COUNT(*) n FROM rephrases "
                    "GROUP BY source_type ORDER BY n DESC LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return "rephrase"
                dominant = row[0]
        except Exception:
            return "rephrase"

        # Map source_type → intent. SOURCE_CORPUS is the voice /
        # continuation training mode; the other source types map to
        # their generation tasks. Chat sources fold into "chat" since
        # they share the same prompt-as-instruction shape.
        return {
            SOURCE_CORPUS: "voice",
            SOURCE_REPHRASE: "rephrase",
            SOURCE_PLOT: "plot",
            SOURCE_WORLDBUILDING: "worldbuilding",
            SOURCE_CHARACTER: "character",
            SOURCE_CHAT_WRITING: "chat",
            SOURCE_CHAT_GENERAL: "chat",
        }.get(dominant, "rephrase")

    def _run_test(self):
        """Run the selected trained model on the test-input passage.

        Training outputs in this codebase are LoRA adapter directories
        (``adapter_config.json`` + ``adapter_model.safetensors``), not
        full models — so we have to load the registered base model
        first and apply the adapter on top via PEFT. The test prompt
        format matches what training used (chat template if the model
        has one, else Alpaca with the ``### Input:`` block) and
        per-intent instructions match ``_format_row`` in the database
        layer. Sampler params include repetition penalties so the
        small-model "the the the" / "Passage: Passage:" loops the user
        was hitting before the rewrite are eliminated.
        """
        path = self.test_model_combo.currentData()
        if not path or not Path(path).exists():
            QMessageBox.information(self, "No Model",
                                    "Train a model first.")
            return
        passage = self.test_input.toPlainText().strip()
        if not passage:
            return
        self.test_output.setPlainText(
            "(loading model — first run takes a while)…")
        try:
            import torch

            # Resolve the registry entry through the unified
            # ModelRegistry so the test runner shares loaded models
            # with the Writing Tool and the Model Hub via the
            # process-wide LRU cache. Falls back to the legacy
            # trained-models JSON read if the registry can't find the
            # entry (e.g. a path the user added by hand).
            from src.data.model_registry import (
                list_models, KIND_TRAINED,
            )
            from src.ai.model_cache import get_default_cache

            unified = next(
                (e for e in list_models(kinds=[KIND_TRAINED])
                 if e.path == path), None)
            entry_dict = next((m for m in load_trained_models()
                               if m.get("path") == path), None)
            base_model_id = ""
            registry_intent = ""
            genres: list = []
            tones: list = []
            is_adapter = False
            if unified is not None:
                base_model_id = unified.base_model or ""
                registry_intent = unified.intent or ""
                genres = unified.metadata.get("genres") or []
                tones = unified.metadata.get("tones") or []
                is_adapter = unified.is_adapter
            elif entry_dict is not None:
                base_model_id = entry_dict.get("base_model") or ""
                registry_intent = (entry_dict.get("intent") or "").lower()
                genres = entry_dict.get("genres") or []
                tones = entry_dict.get("tones") or []
                is_adapter = (
                    Path(path) / "adapter_config.json").exists()

            override = (self.test_intent_override.currentData()
                        if hasattr(self, 'test_intent_override') else "")
            if override:
                intent = override
            elif registry_intent:
                intent = registry_intent
            else:
                intent = self._infer_intent_from_db()

            if is_adapter and not base_model_id:
                self.test_output.setPlainText(
                    "Test failed: this model directory contains a "
                    "LoRA adapter but the registry entry has no "
                    "base_model field. Re-train, or open Manage "
                    "Trained Models to add the base model name.")
                return

            self.test_output.setPlainText(
                f"(loading {Path(path).name} via shared model cache — "
                f"first load takes 10-60 seconds; subsequent loads "
                f"are instant)…")
            cache = get_default_cache()
            if unified is not None:
                tok, mdl = cache.get(unified)
            else:
                # Legacy fallback: synthesize a registry entry so
                # the cache can still take ownership.
                from src.data.model_registry import ModelEntry
                synth = ModelEntry(
                    id=Path(path).name,
                    kind=KIND_TRAINED,
                    display_name=Path(path).name,
                    base_model=base_model_id,
                    path=path,
                    intent=registry_intent,
                    is_adapter=is_adapter,
                )
                tok, mdl = cache.get(synth)

            # Per-intent instruction. Mirrors _format_row in the
            # database so the model sees the same prompt shape it was
            # trained against. Mismatch here is what causes the
            # "Passage: Passage:" repetition loops the user reported —
            # the model echoes a token sequence it has never seen
            # before.
            tag_bits = []
            if genres:
                tag_bits.append(f"({', '.join(genres)} genre)")
            if tones:
                tag_bits.append(f"in a {', '.join(tones)} tone")
            tag_suffix = (" " + " ".join(tag_bits)) if tag_bits else ""

            if intent == "voice":
                instruction = (f"Continue this passage in the same "
                               f"voice and style as the author"
                               f"{tag_suffix}.")
                user_input = passage
                system = ("You write in the voice of the user's chosen "
                          "author corpus.")
            elif intent == "plot":
                instruction = (f"Generate a story outline{tag_suffix}.")
                user_input = passage
                system = ("You are a plot-structure assistant. Generate "
                          "compelling narratives with clear beats.")
            elif intent == "worldbuilding":
                instruction = (f"Generate a worldbuilding element"
                               f"{tag_suffix}.")
                user_input = passage
                system = ("You are a worldbuilding assistant. Generate "
                          "rich, internally-consistent fictional "
                          "worlds.")
            elif intent == "character":
                instruction = (f"Generate a complete character profile"
                               f"{tag_suffix}.")
                user_input = passage
                system = ("You are a character designer. Create vivid, "
                          "internally-consistent characters with depth.")
            elif intent == "chat":
                instruction = passage
                user_input = ""
                system = "You are a helpful writing assistant."
            else:  # rephrase / agent / default
                instruction = (f"Rephrase the following passage"
                               f"{tag_suffix}.")
                user_input = f"Passage:\n{passage}"
                system = ("You are a creative writing assistant who "
                          "rewrites prose while preserving voice.")

            # Match training's prompt shape exactly. If the tokenizer
            # has a chat template, training used apply_chat_template —
            # so do we. Otherwise, training used the Alpaca fallback
            # with the ``### Input:`` block when input was non-empty.
            has_chat_template = bool(
                getattr(tok, "chat_template", None))
            if has_chat_template:
                user_msg = (f"{instruction}\n\n{user_input}".strip()
                            if user_input else instruction)
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": user_msg})
                prompt = tok.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True)
            else:
                if user_input:
                    prompt = (f"### Instruction:\n{instruction}\n\n"
                              f"### Input:\n{user_input}\n\n"
                              f"### Response:\n")
                else:
                    prompt = (f"### Instruction:\n{instruction}\n\n"
                              f"### Response:\n")

            # Dispatch on framework: MLX-format models go through
            # mlx_lm.generate, transformers/PEFT go through model.generate.
            # The continuation logic is the same shape on both sides
            # (auto-continue when cut off mid-sentence) — the helpers
            # just differ in which generation API they call.
            from src.ai.model_cache import (
                generate_with_continuation,
                mlx_generate_with_continuation,
                is_mlx_model,
            )
            if is_mlx_model(mdl):
                response = mlx_generate_with_continuation(
                    tok, mdl, prompt,
                    max_new_tokens=300,
                    max_continuations=3,
                    max_total_new_tokens=1500,
                    temperature=0.7, top_p=0.9,
                )
            else:
                ids = tok(prompt, return_tensors="pt").to(mdl.device)
                # Sampler controls — without these, small under-trained
                # models lock into "the the the" or echo the prompt's
                # delimiters ("Passage: Passage:"). repetition_penalty +
                # no_repeat_ngram_size break those loops; top_p
                # restricts the sampling cone so temperature 0.7
                # doesn't wander.
                response = generate_with_continuation(
                    tok, mdl, ids,
                    max_new_tokens=300,
                    max_continuations=3,
                    max_total_new_tokens=1500,
                    gen_kwargs=dict(
                        do_sample=True, temperature=0.7, top_p=0.9,
                        repetition_penalty=1.15, no_repeat_ngram_size=4,
                    ),
                )
            self.test_output.setPlainText(response.strip())

            # Prime the rating panel so the user can save this
            # test result with a star rating + category. Same panel
            # the Model Hub uses; ratings persist to the shared
            # JSON store, so the history dialog from either surface
            # shows the same records.
            try:
                model_combo = self.test_model_combo
                idx = model_combo.currentIndex()
                model_name_label = model_combo.itemText(idx).strip()
                # Strip the leading "  " padding used for grouped
                # rows and the trailing "(base: …)" suffix the picker
                # displays.
                clean_name = model_name_label.lstrip("✓ ").strip()
                # Use intent for default category.
                default_cat = (intent or "other")
                self._test_rating_panel.set_pending_test(
                    model_name=clean_name.split(" (base:")[0].strip(),
                    model_path=path,
                    prompt=passage,
                    response=response.strip(),
                    intent_used=intent or "",
                    generation_params={"temperature": 0.7,
                                        "top_p": 0.9},
                    default_category=default_cat,
                )
            except Exception:
                pass

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.test_output.setPlainText(f"Test failed: {e}")

    def _on_studio_test_saved(self, _record):
        """Acknowledge a saved test result on Step 4."""
        # Surface in the train log so it's visible alongside
        # training output / cleaning / Modal status.
        try:
            self.train_log.appendPlainText(
                "[test] Saved test result to per-model history.")
        except Exception:
            pass

    def _open_test_history(self):
        """Open the per-model history dialog for whatever's
        selected in the Step-4 model picker."""
        path = self.test_model_combo.currentData()
        if not path:
            QMessageBox.information(
                self, "Pick a trained model",
                "Select a model from the list first.")
            return
        # Find its registry name.
        from src.config.creativeos_config import load_trained_models
        entry = next((m for m in load_trained_models()
                      if m.get("path") == path), None)
        if entry is None:
            QMessageBox.warning(
                self, "Not in registry",
                "This model isn't in the trained-models registry. "
                "Click Done first to register it, then retry.")
            return
        from src.ui.test_history_widgets import TestHistoryDialog
        dlg = TestHistoryDialog(entry["name"], parent=self)
        dlg.exec()

    # ── Navigation ──

    def _go_back(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
        self._update_nav()

    def _go_next(self):
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self.stack.setCurrentIndex(idx + 1)
        self._update_nav()

    def _update_nav(self):
        idx = self.stack.currentIndex()
        last = self.stack.count() - 1
        self.back_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < last)
        self.next_btn.setText("Next ▶" if idx < last else "Done")
        # Step 2 hosts the model selection — recompute the recommendation
        # whenever the user lands here so it reflects their current
        # corpus size and goal/intent on Step 1.
        if idx == 1:
            self._refresh_step2_recommendation()


# ── Corpus Library dialog ──────────────────────────────────────

class _CorpusDownloadWorker(QThread):
    """Runs the corpus download + adapter pipeline off the UI thread.

    The ``progress`` signal carries a ``(current, total, label)``
    triple — total is ``0`` when indeterminate (HF datasets without
    a known total, HTTP servers without ``Content-Length``). The
    label changes when the worker switches phases (downloading →
    streaming → writing) so the receiving widget can reset its
    bar's scale at phase boundaries.
    """

    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)  # current, total, label
    finished_ok = pyqtSignal(int)  # passages logged
    failed = pyqtSignal(str)

    def __init__(self, entry, db_path: Path):
        super().__init__()
        self.entry = entry
        self.db_path = db_path

    def run(self):
        try:
            from src.data.rephrase_database import RephraseDatabase
            from src.data.corpus_downloader import (
                ingest, CorpusLicenseError,
            )
            db = RephraseDatabase(self.db_path)
            result = ingest(
                self.entry, db=db,
                on_progress=lambda c, t, lbl: self.progress.emit(c, t, lbl),
                on_log=lambda s: self.log.emit(s),
            )
            self.finished_ok.emit(result.passages_logged)
        except CorpusLicenseError as e:
            self.failed.emit(str(e))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"Download/parse failed: {e}")


class _SmartDownloadDialog(QDialog):
    """Smart-pick corpus downloader.

    Runs :func:`corpus_recommender.recommend_downloads` against
    the user's current Step-1 selection (genres, tones, intent),
    excludes anything already in the DB, and shows the top N
    suggestions with per-entry rationale. The user reviews,
    optionally deselects entries, and clicks Download — the
    dialog drives a sequential batch through
    :class:`_CorpusDownloadWorker` so downloads don't all race.

    Why not auto-download everything? Because corpora vary 100×
    in size, license, and quality. The recommender narrows the
    catalog to a handful of high-value picks; the user gets the
    final say on which ones land in their DB.
    """

    def __init__(self, *,
                 db_path: Path,
                 intent: str,
                 genres: List[str],
                 tones: List[str],
                 llm_generate=None,
                 parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._intent = intent
        self._genres = genres
        self._tones = tones
        self._llm_generate = llm_generate
        self._suggestions: list = []
        self._row_widgets: list = []  # (checkbox, suggestion)
        self._download_queue: list = []
        self._current_worker: Optional[_CorpusDownloadWorker] = None
        self._completed: list = []
        self._failed: list = []

        self.setWindowTitle("Smart-pick corpora")
        self.setMinimumSize(720, 540)
        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("<b>Smart-pick corpora</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        layout.addWidget(title)

        intro = QLabel(
            f"Recommendations for the current selection "
            f"(intent: <b>{self._intent or 'general'}</b>, "
            f"genres: {self._genres or '—'}, "
            f"tones: {self._tones or '—'}). Already-ingested "
            f"corpora are skipped. Deselect any you don't want, "
            f"then click Download.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding-bottom: 6px;")
        layout.addWidget(intro)

        # Suggestions list — populated in _populate.
        from PyQt6.QtWidgets import QScrollArea, QFrame
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(6)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, 1)

        # Footer status + buttons.
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #6b7280; padding-top: 4px;")
        layout.addWidget(self._status_label)

        actions = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self._cancel_btn)
        self._refresh_btn = QPushButton("⟳ Re-recommend")
        self._refresh_btn.clicked.connect(self._populate)
        self._refresh_btn.setToolTip(
            "Re-run the recommender. Useful after you've "
            "ingested data outside this dialog and want fresh "
            "picks that account for it.")
        actions.addWidget(self._refresh_btn)
        actions.addStretch()
        self._download_btn = QPushButton("📥 Download selected")
        self._download_btn.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 6px 14px; border-radius: 5px; "
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #4f46e5; }")
        self._download_btn.clicked.connect(self._on_download_clicked)
        actions.addWidget(self._download_btn)
        layout.addLayout(actions)

    def _populate(self):
        from src.data.corpus_recommender import recommend_downloads
        # Clear existing rows.
        for w, _ in self._row_widgets:
            w.parentWidget().deleteLater()
        self._row_widgets = []

        try:
            self._suggestions = recommend_downloads(
                intent=self._intent,
                genres=self._genres,
                tones=self._tones,
                db_path=self.db_path,
                max_suggestions=5,
                llm_generate=self._llm_generate)
        except Exception as e:
            self._status_label.setText(
                f"<span style='color:#b91c1c;'>"
                f"Couldn't run recommender: {e}</span>")
            return

        if not self._suggestions:
            self._status_label.setText(
                "<i>No recommendations — either you've already "
                "ingested everything relevant to your selection, "
                "or no genres/tones are ticked. Pick some on "
                "Step 1 and re-open this dialog.</i>")
            self._download_btn.setEnabled(False)
            return

        for s in self._suggestions:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(8, 6, 8, 6)
            cb = QCheckBox()
            cb.setChecked(True)
            row.addWidget(cb)
            text = (
                f"<div><b>{s.name}</b> "
                f"<span style='color:#6b7280;'>"
                f"({s.size_kb} KB · {s.license})</span></div>"
                f"<div style='color:#374151;font-size:11px;"
                f"margin-top:2px;'>{s.reason}</div>")
            label = QLabel(text)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            row_widget.setStyleSheet(
                "QWidget { background: #f9fafb; border-radius: 4px; "
                "border-left: 3px solid #818cf8; }")
            self._list_layout.addWidget(row_widget)
            self._row_widgets.append((cb, s))

        self._status_label.setText(
            f"{len(self._suggestions)} suggestions "
            f"(deselect any you don't want).")
        self._download_btn.setEnabled(True)

    def _on_download_clicked(self):
        # Build the download queue from selected rows.
        self._download_queue = [
            s for cb, s in self._row_widgets if cb.isChecked()]
        if not self._download_queue:
            self._status_label.setText(
                "<span style='color:#b45309;'>"
                "Pick at least one entry to download.</span>")
            return
        self._completed = []
        self._failed = []
        self._cancel_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._download_btn.setEnabled(False)
        self._status_label.setText(
            f"Starting download of {len(self._download_queue)} "
            f"corpora…")
        self._dispatch_next()

    def _dispatch_next(self):
        if not self._download_queue:
            self._on_all_downloads_done()
            return
        sugg = self._download_queue.pop(0)
        self._status_label.setText(
            f"Downloading <b>{sugg.name}</b> "
            f"({len(self._completed) + 1} of "
            f"{len(self._completed) + 1 + len(self._download_queue)})…")
        worker = _CorpusDownloadWorker(
            sugg.catalog_entry, self.db_path)
        worker.finished_ok.connect(
            lambda n_passages, s=sugg: self._on_one_done(s, n_passages))
        worker.failed.connect(
            lambda msg, s=sugg: self._on_one_failed(s, msg))
        self._current_worker = worker
        worker.start()

    def _on_one_done(self, sugg, n_passages: int):
        self._completed.append((sugg, n_passages))
        self._dispatch_next()

    def _on_one_failed(self, sugg, msg: str):
        self._failed.append((sugg, msg))
        self._dispatch_next()

    def _on_all_downloads_done(self):
        self._cancel_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._download_btn.setEnabled(True)
        msg_parts = []
        if self._completed:
            total_rows = sum(n for _, n in self._completed)
            msg_parts.append(
                f"✅ Downloaded {len(self._completed)} corpora "
                f"({total_rows} rows logged).")
        if self._failed:
            msg_parts.append(
                f"⚠️ {len(self._failed)} failed.")
            for s, m in self._failed:
                msg_parts.append(f"  • {s.name}: {m[:100]}")
        self._status_label.setText("<br>".join(msg_parts))
        # Auto-close on full success after a brief pause; leave
        # open on partial failure so the user can read errors.
        if self._completed and not self._failed:
            QTimer.singleShot(1200, self.accept)


class _CorpusLibraryDialog(QDialog):
    """Browse the catalog + custom registry, tick what to download,
    bulk-ingest with one click. Already-downloaded corpora carry a
    ✓ marker so the user can see at a glance what's still missing.
    """

    def __init__(self, db_path: Path, parent=None,
                 *,
                 intent: str = "",
                 genres: Optional[List[str]] = None,
                 tones: Optional[List[str]] = None,
                 llm_generate=None):
        """Args:
            intent / genres / tones: user's current Step-1 selection.
                Powers the Smart Pick button — the recommender uses
                them to score candidates. Defaults are safe:
                ``intent=""`` plus empty lists make Smart Pick show a
                "tick a genre first" message rather than crashing.
            llm_generate: optional ``(prompt, system) -> str``. When
                provided, Smart Pick uses agentic LLM refinement on
                top of the deterministic ranker.
        """
        super().__init__(parent)
        self.db_path = db_path
        self._smart_intent = intent
        self._smart_genres = list(genres or [])
        self._smart_tones = list(tones or [])
        self._smart_llm = llm_generate
        # Persistent checked-state set. Survives across filter
        # changes — the search / kind dropdown both rebuild the
        # visible list, but a row that gets filtered out keeps its
        # check state in this set so it returns checked when the
        # filter changes back. The previous implementation read
        # check state from the visible list_widget alone, so
        # filtered-out items lost their ticks.
        self._checked_ids: set = set()
        self.setWindowTitle("Corpus Library")
        self.resize(820, 600)
        self.setMinimumSize(640, 460)
        self._init_ui()
        self._refresh_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tick the corpora you want and hit <b>⬇ Download checked</b>. "
            "Built-in entries are public-domain or permissively-licensed; "
            "custom URLs require attestation. ✓ marks corpora already in "
            "your training DB.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        # ── Filter row ──
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "search by name, author, tag, license, genre…")
        self.filter_edit.textChanged.connect(self._refresh_list)
        filter_row.addWidget(self.filter_edit, 1)

        self.kind_combo = QComboBox()
        for label, value in (("All entries", "all"),
                             ("Built-in catalog", "builtin"),
                             ("Custom (user-added)", "custom"),
                             ("Already downloaded", "downloaded"),
                             ("Not yet downloaded", "missing")):
            self.kind_combo.addItem(label, value)
        self.kind_combo.currentIndexChanged.connect(self._refresh_list)
        filter_row.addWidget(self.kind_combo)
        layout.addLayout(filter_row)

        # ── Quick actions ──
        quick = QHBoxLayout()
        for label, slot in (
            ("Check all (visible)",   self._check_all_visible),
            ("Uncheck all",           self._uncheck_all),
            ("Check missing PD only", self._check_missing_pd),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            quick.addWidget(b)
        # Smart Pick — runs the recommender against the user's
        # current intent + genres + tones and ticks the suggested
        # rows in this dialog. Distinct visual treatment so it
        # stands out as the "do the smart thing" path next to the
        # generic Check-all/Uncheck-all defaults.
        self.smart_pick_btn = QPushButton("🎯 Smart Pick")
        self.smart_pick_btn.setStyleSheet(
            "QPushButton { padding: 4px 10px; "
            "background-color: #ddd6fe; color: #5b21b6; "
            "border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #c4b5fd; }")
        self.smart_pick_btn.setToolTip(
            "Recommend a small set of catalog entries based on "
            "your current intent / genres / tones. Already-"
            "ingested rows are skipped. With an LLM configured, "
            "uses agentic refinement to choose complementary "
            "picks. Ticks them in this list — you still confirm "
            "by hitting Download.")
        self.smart_pick_btn.clicked.connect(
            self._on_smart_pick_clicked)
        quick.addWidget(self.smart_pick_btn)
        quick.addStretch()
        layout.addLayout(quick)

        # ── List ──
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        # Keep highlighting (used by the Add/Remove buttons) alongside
        # the per-row checkboxes that drive bulk download.
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        # Two slots on itemChanged:
        #   1. Mirror the visible row's check state into
        #      ``self._checked_ids`` so a subsequent filter change
        #      can restore it.
        #   2. Refresh the status line summary.
        self.list_widget.itemChanged.connect(self._on_item_check_changed)
        self.list_widget.itemChanged.connect(self._update_status)
        layout.addWidget(self.list_widget, 1)

        # ── Status footer ──
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "padding: 6px 8px; background: #f9fafb; "
            "border-radius: 4px; font-size: 11px; color: #374151;")
        layout.addWidget(self.status_label)

        # ── Progress + log ──
        # Two-tier progress: top label says which entry of N is
        # currently being processed; the QProgressBar shows the
        # *current* entry's bytes-or-rows-or-pairs progress so the
        # user gets motion even for huge HF streams that don't
        # increment the entry counter for many minutes.
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        layout.addWidget(self.progress_label)

        self.aggregate_bar = QProgressBar()
        self.aggregate_bar.setRange(0, 1)
        self.aggregate_bar.setValue(0)
        self.aggregate_bar.setFormat("%p% — %v of %m corpora")
        self.aggregate_bar.setVisible(False)
        layout.addWidget(self.aggregate_bar)

        self.entry_bar = QProgressBar()
        self.entry_bar.setRange(0, 1)
        self.entry_bar.setValue(0)
        self.entry_bar.setFormat("%p%")
        self.entry_bar.setVisible(False)
        layout.addWidget(self.entry_bar)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(110)
        self.log_box.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background-color: #111827; color: #d1d5db;")
        layout.addWidget(self.log_box)

        # ── Action buttons ──
        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("⬇ Download checked")
        self.download_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 14px; border-radius: 6px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.download_btn.setToolTip(
            "Download every checked entry that isn't already "
            "ingested. Already-downloaded entries are skipped.")
        self.download_btn.clicked.connect(self._download_checked)
        btn_row.addWidget(self.download_btn)

        # The "use for training" path closes the loop the user
        # cares about: take this curated subset, make sure
        # everything's downloaded, then set it as the active
        # training filter so the next training run uses ONLY
        # these corpora.
        self.use_for_training_btn = QPushButton(
            "🎯 Use checked for training")
        self.use_for_training_btn.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 6px 14px; border-radius: 6px; "
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #4f46e5; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.use_for_training_btn.setToolTip(
            "Build a training-ready subset from what's checked: "
            "downloads anything not yet ingested, then sets this "
            "selection as the active corpus filter so the next "
            "training run uses ONLY these corpora. Optionally "
            "runs the cleaner first.")
        self.use_for_training_btn.clicked.connect(
            self._on_use_for_training_clicked)
        btn_row.addWidget(self.use_for_training_btn)

        # Smart Pick lives inside the library — the user is here to
        # pick what to download, and Smart Pick is "do that for me
        # based on my current intent / genres." Was previously on
        # Step 1 of the training wizard but that's the wrong place
        # for it (a recommend-and-download action belongs next to
        # the catalog list, not the trainer recipe).
        self.smart_pick_btn = QPushButton("🎯 Smart Pick…")
        self.smart_pick_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border-radius: 5px; "
            "background-color: #ddd6fe; color: #5b21b6; }"
            "QPushButton:hover { background-color: #c4b5fd; }")
        self.smart_pick_btn.setToolTip(
            "Recommend a small set of catalog entries to download "
            "based on the wizard's current intent / genres / "
            "tones. Skips already-ingested corpora and (when an "
            "LLM is configured) uses agentic refinement to pick "
            "complementary picks.")
        self.smart_pick_btn.clicked.connect(self._on_smart_pick_clicked)
        btn_row.addWidget(self.smart_pick_btn)

        self.add_btn = QPushButton("➕ Add Custom URL…")
        self.add_btn.setToolTip(
            "Register your own corpus URL. Attestation required.")
        self.add_btn.clicked.connect(self._add_custom)
        btn_row.addWidget(self.add_btn)

        self.add_local_btn = QPushButton("📁 Add Local Folder / Zip…")
        self.add_local_btn.setToolTip(
            "Register a corpus you already have on disk — a folder of "
            "text files or a zip archive. Tagged with genre + voice, "
            "shows up here as a checkable row, can be re-ingested, and "
            "the genre filter routes it to matching fine-tunes.")
        self.add_local_btn.clicked.connect(self._add_local_corpus)
        btn_row.addWidget(self.add_local_btn)

        self.remove_btn = QPushButton("🗑 Remove highlighted")
        self.remove_btn.setToolTip(
            "Remove the highlighted user-added entry (built-in catalog "
            "can't be deleted). Operates on the highlighted row, not "
            "the checked rows.")
        self.remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ── List rendering ──

    def _ingested_ids(self) -> set:
        """Catalog ids that already have rows in the DB.

        Cheap query — looks at the DISTINCT notes prefix and parses
        ``corpus_id=…`` tokens out, same logic as
        ``TrainingToolWindow._ingested_corpus_ids``.
        """
        ids = set()
        try:
            db = RephraseDatabase(self.db_path)
            with db._conn() as c:
                cur = c.execute(
                    "SELECT DISTINCT notes FROM rephrases "
                    "WHERE source_type = 'corpus' AND notes LIKE 'corpus_id=%'")
                for row in cur:
                    notes = row["notes"] or ""
                    tok = notes.split(maxsplit=1)[0] if notes else ""
                    if tok.startswith("corpus_id="):
                        ids.add(tok.split("=", 1)[1])
        except Exception:
            pass
        return ids

    def _refresh_list(self):
        from src.data.corpus_registry import (
            all_entries, license_label_for, builtin_ids,
        )
        ingested = self._ingested_ids()
        builtins = builtin_ids()
        kind = self.kind_combo.currentData() or "all"
        q = (self.filter_edit.text() or "").strip().lower()

        # Preserve the user's check state across refreshes — read
        # from the persistent ``_checked_ids`` set rather than the
        # visible list, so rows filtered out by the current search
        # / kind combo keep their ticks for when the filter
        # changes back.
        previously_checked = set(self._checked_ids)

        self.list_widget.blockSignals(True)
        try:
            self.list_widget.clear()
            for e in all_entries():
                # Filter: kind
                is_builtin = e.id in builtins
                is_downloaded = e.id in ingested
                if kind == "builtin" and not is_builtin:
                    continue
                if kind == "custom" and is_builtin:
                    continue
                if kind == "downloaded" and not is_downloaded:
                    continue
                if kind == "missing" and is_downloaded:
                    continue

                # Filter: text search across name + id + tags + author +
                # license + description. Including ``id`` lets users
                # type slugs ("gutenberg-frankenstein", "hf-pg19") and
                # land on the right row instantly.
                if q:
                    haystack = " ".join((
                        e.id, e.name, e.author or "",
                        " ".join(e.tags or []),
                        e.license, e.description or "",
                    )).lower()
                    if q not in haystack:
                        continue

                # Build a compact two-line label. Downloaded entries
                # carry a ✓ prefix and turn green so the user can scan
                # the list and immediately see what's still missing.
                tags = ", ".join(e.tags[:4]) if e.tags else ""
                size_kb = getattr(e, "size_hint_kb", 0) or 0
                size_label = (f"{size_kb / 1024:.1f}MB" if size_kb >= 1024
                              else (f"{size_kb}KB" if size_kb else "—"))
                # Visual markers: ✓ = already ingested; 📁 = local
                # folder/zip on the user's disk; the kind is otherwise
                # implicit in the format field.
                check_marker = "✓ " if is_downloaded else ""
                kind_marker = ("📁 " if e.format in
                               ("local_folder", "local_zip") else "")
                line1 = (f"{check_marker}{kind_marker}{e.name}  "
                         f"·  {license_label_for(e)}  ·  ~{size_label}")
                line2 = (f"   {e.description}\n"
                         f"   format={e.format} · "
                         f"author={e.author or '—'} · "
                         f"tags={tags}")
                item = QListWidgetItem(f"{line1}\n{line2}")
                item.setData(Qt.ItemDataRole.UserRole, e.id)
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                # Preserve check state across refresh; default the rest
                # to unchecked so the user explicitly opts in.
                item.setCheckState(
                    Qt.CheckState.Checked
                    if e.id in previously_checked
                    else Qt.CheckState.Unchecked)
                if is_downloaded:
                    item.setForeground(QColor("#059669"))
                    item.setToolTip(
                        f"✓ Already in your DB.\n{e.name}\n"
                        f"id: {e.id}")
                else:
                    item.setToolTip(
                        f"{e.name}\nid: {e.id}\nlicense: {e.license}")
                self.list_widget.addItem(item)
        finally:
            self.list_widget.blockSignals(False)
        self._update_status()

    # ── Multi-check helpers ──

    def _currently_checked_ids(self) -> set:
        """Return every checked id, including ones filtered out of
        the visible list. Reads from the persistent set."""
        return set(self._checked_ids)

    def _on_item_check_changed(self, item):
        """Mirror the visible row's check state into
        ``self._checked_ids``. Fires for every itemChanged signal
        — including the ones our own _refresh_list emits — so we
        only listen to user-initiated changes (the refresh-time
        ones happen while signals are blocked)."""
        cid = item.data(Qt.ItemDataRole.UserRole)
        if not cid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_ids.add(cid)
        else:
            self._checked_ids.discard(cid)

    def _checked_entries(self) -> List:
        from src.data.corpus_registry import all_entries
        ids = self._currently_checked_ids()
        return [e for e in all_entries() if e.id in ids]

    def _set_check(self, item: QListWidgetItem, checked: bool) -> None:
        """Set the visible row's check state. The itemChanged signal
        fires and ``_on_item_check_changed`` updates the persistent
        set, so a single ``_set_check`` call keeps both the row and
        the persistent set in sync."""
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(Qt.CheckState.Checked if checked
                               else Qt.CheckState.Unchecked)

    def _set_check_by_id(self, cid: str, checked: bool) -> None:
        """Set the persistent check state for a corpus id, whether
        or not its row is currently visible. If the row IS visible
        the visible row updates too via ``_set_check``."""
        if not cid:
            return
        if checked:
            self._checked_ids.add(cid)
        else:
            self._checked_ids.discard(cid)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == cid:
                self._set_check(item, checked)
                return

    def _check_all_visible(self) -> None:
        """Tick every row currently rendered (filter-aware)."""
        for i in range(self.list_widget.count()):
            self._set_check(self.list_widget.item(i), True)

    def _uncheck_all(self) -> None:
        """Clear EVERY check, including filtered-out rows. The
        button label says "Uncheck all" without qualification, so
        users expect a clean slate — not a "clear visible only"
        action. Wipes the persistent set first, then mirrors that
        to the visible list."""
        self._checked_ids.clear()
        for i in range(self.list_widget.count()):
            self._set_check(self.list_widget.item(i), False)

    def _check_missing_pd(self) -> None:
        """Tick everything that's PD-licensed AND not yet downloaded.

        The least-friction starting point: gives the user a one-click
        path to populate their DB with the genre essentials without
        touching anything that needs attestation.
        """
        from src.data.corpus_registry import all_entries
        from src.data.corpus_catalog import is_license_safe
        ingested = self._ingested_ids()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            cid = item.data(Qt.ItemDataRole.UserRole)
            entry = next((e for e in all_entries() if e.id == cid), None)
            if entry is None:
                continue
            self._set_check(
                item,
                is_license_safe(entry.license)
                and entry.id not in ingested)

    def _on_smart_pick_clicked(self) -> None:
        """Run the recommender against the user's ENTIRE corpus pool
        (ingested + downloadable) and tick the suggested rows.

        The user's mental model: each checkbox in this list says
        "include this corpus in training". Smart Pick fills those
        checkboxes with the most-relevant entries for the active
        intent / genres / tones — whether or not they've been
        downloaded yet. The Download-checked / Use-checked-for-
        training buttons turn that selection into action.
        """
        if not self._smart_genres and not self._smart_tones:
            QMessageBox.information(
                self, "Pick genres or tones first",
                "Smart Pick uses the genres and tones you've ticked "
                "on Step 1 to choose complementary catalog entries. "
                "Tick at least one and re-open this dialog.")
            return
        from src.data.corpus_recommender import (
            recommend_downloads_with_diagnosis,
        )
        try:
            result = recommend_downloads_with_diagnosis(
                intent=self._smart_intent or "general",
                genres=self._smart_genres,
                tones=self._smart_tones,
                db_path=self.db_path,
                max_suggestions=8,
                llm_generate=self._smart_llm,
                include_ingested=True)
        except Exception as e:
            QMessageBox.warning(
                self, "Smart Pick failed",
                f"Couldn't run recommender:\n{e}")
            return

        suggs = result.suggestions
        if not suggs:
            QMessageBox.information(
                self, "Smart Pick", result.summary or
                "Couldn't find any candidates for this selection.")
            return

        target_ids = {s.corpus_id for s in suggs}

        # Tick suggested rows + clear everything else, including
        # filtered-out rows. Using the by-id variant ensures rows
        # the recommender suggests but the current search hides
        # still get ticked — useful when the adjacent-genre
        # fallback surfaces entries that don't match the current
        # filter text.
        previously = set(self._checked_ids)
        for cid in target_ids:
            self._set_check_by_id(cid, True)
        for cid in previously - target_ids:
            self._set_check_by_id(cid, False)
        ticked = len(target_ids)
        unticked = len(previously - target_ids)

        # Build the summary from the diagnostic result.
        n_to_dl = sum(1 for s in suggs if s.requires_download)
        n_in_db = sum(1 for s in suggs if not s.requires_download)
        lines = []
        for s in suggs:
            tag = ("⬇ download" if s.requires_download
                   else "✓ already in DB")
            lines.append(
                f"<b>{s.name}</b> <span style='color:#6b7280'>"
                f"({s.size_kb} KB · {tag})</span><br>"
                f"&nbsp;&nbsp;<i>{s.reason}</i>")
        notes_html = ""
        if result.notes:
            notes_html = ("<br><br>"
                          + "<br>".join(f"<i>{n}</i>"
                                         for n in result.notes))
        body = (f"Smart Pick selected {ticked} entries "
                f"({n_in_db} already in your DB, "
                f"{n_to_dl} to download):<br><br>"
                + "<br><br>".join(lines)
                + notes_html
                + "<br><br><i>Click <b>📥 Download missing &amp; "
                "use for training</b> below to download the "
                "{n_to_dl} missing entries (if any) and set this "
                "subset as the active training filter.</i>".format(
                    n_to_dl=n_to_dl))
        QMessageBox.information(self, "Smart Pick", body)

        hidden = sum(
            1 for i in range(self.list_widget.count())
            if self.list_widget.item(i).isHidden()
            and self.list_widget.item(i).data(
                Qt.ItemDataRole.UserRole) in target_ids)
        if hidden:
            self.status_label.setText(
                f"⚠ {hidden} of the picked entries are hidden by "
                f"the current filter — clear it to see them.")

    def _update_status(self, *_args) -> None:
        entries = self._checked_entries()
        if not entries:
            self.status_label.setText(
                f"<i>0 corpora checked.</i>  "
                f"List shows {self.list_widget.count()} entry(ies).")
            self.download_btn.setEnabled(False)
            return
        total_kb = sum(getattr(e, "size_hint_kb", 0) or 0 for e in entries)
        size_label = (f"{total_kb / 1024 / 1024:.1f}GB"
                      if total_kb >= 1024 * 1024
                      else (f"{total_kb / 1024:.1f}MB"
                            if total_kb >= 1024
                            else f"{total_kb}KB"))
        n_attested = sum(1 for e in entries
                         if (e.license or "").lower() == "user-attested")
        msg = (f"<b>{len(entries)}</b> corpora checked, "
               f"~{size_label} total to download.")
        if n_attested:
            msg += (f"  <span style='color:#b45309;'>"
                    f"{n_attested} require attestation</span>")
        self.status_label.setText(msg)
        self.download_btn.setEnabled(True)

    # ── Selected (highlighted) entry — used by Add/Remove ──

    def _selected_entry(self):
        from src.data.corpus_registry import all_entries
        item = self.list_widget.currentItem()
        if not item:
            return None
        cid = item.data(Qt.ItemDataRole.UserRole)
        return next((e for e in all_entries() if e.id == cid), None)

    def _on_smart_pick_clicked(self):
        """Open the smart-pick dialog. Delegates to the parent
        window because the dialog needs the wizard's current
        intent / genres / tones / LLM config to make suggestions —
        the library dialog itself doesn't know any of that.

        After Smart Pick finishes, refresh our list so any newly-
        downloaded entries show their ✓ marker.
        """
        parent = self.parent()
        if parent is None or not hasattr(parent, "_open_smart_pick"):
            QMessageBox.warning(
                self, "Smart Pick unavailable",
                "Smart Pick requires the training wizard to be "
                "open — couldn't reach it from here.")
            return
        parent._open_smart_pick()
        self._refresh_list()

    # ── Bulk download ──

    def _on_use_for_training_clicked(self):
        """Take the currently-checked corpora and set them up as
        the active training subset.

        Steps, all driven from the user's check state:
          1. Download anything checked that's not yet ingested.
          2. Set the parent window's corpus filter to the checked
             collection keys (so only those rows feed the next
             training run).
          3. Offer to run the cleaner before training.

        At the end the user is one Start-Training click from a
        run on the curated subset.
        """
        entries = self._checked_entries()
        if not entries:
            QMessageBox.information(
                self, "Nothing checked",
                "Tick the corpora you want to train on first. "
                "Smart Pick can do this automatically based on "
                "your intent / genres / tones.")
            return

        ingested = self._ingested_ids()
        to_download = [e for e in entries if e.id not in ingested]
        already_in = [e for e in entries if e.id in ingested]

        # Confirm the plan before doing anything.
        clean_question = (
            "<br><br>Run the corpus cleaner over the selected "
            "subset before training? <i>(Recommended for "
            "newly-downloaded entries; safe to skip if you've "
            "cleaned recently.)</i>")
        plan_lines = []
        if to_download:
            plan_lines.append(
                f"⬇ Download {len(to_download)} entry/entries: "
                f"{', '.join(e.name[:30] for e in to_download[:4])}"
                f"{'…' if len(to_download) > 4 else ''}")
        if already_in:
            plan_lines.append(
                f"✓ Use {len(already_in)} already-ingested "
                f"entry/entries directly")
        plan_lines.append(
            "🎯 Set the active training filter to this subset "
            "(only these corpora feed the next training run)")
        plan_html = "<br>&nbsp;&nbsp;• " + "<br>&nbsp;&nbsp;• ".join(
            plan_lines)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Use checked for training")
        msg.setText(
            f"<b>Set up training subset?</b>"
            f"<br><br>Plan:{plan_html}"
            f"{clean_question}")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Cancel |
            QMessageBox.StandardButton.No |   # No-clean
            QMessageBox.StandardButton.Yes)   # Yes-clean
        msg.button(QMessageBox.StandardButton.No).setText(
            "Skip cleaning")
        msg.button(QMessageBox.StandardButton.Yes).setText(
            "Clean then continue")
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        choice = msg.exec()
        if choice == QMessageBox.StandardButton.Cancel:
            return
        run_cleaner = choice == QMessageBox.StandardButton.Yes

        # Phase 1: download anything missing. Reuse the same
        # batched flow Download-checked uses.
        self._pending_post_download = {
            "checked_entries": entries,
            "run_cleaner": run_cleaner,
        }
        if to_download:
            # _download_checked reads the current checkbox state,
            # so we don't need to pass anything explicitly.
            self._download_checked()
            # The download worker will trigger _all_downloads_done
            # which checks _pending_post_download to continue.
        else:
            # Nothing to download — go straight to filter set.
            self._finish_use_for_training()

    def _finish_use_for_training(self):
        """Phase 2 of _on_use_for_training_clicked: set the parent
        window's corpus filter and optionally open the cleaner.
        Called after any pending downloads complete."""
        if not getattr(self, '_pending_post_download', None):
            return
        info = self._pending_post_download
        self._pending_post_download = None

        entries = info.get("checked_entries", [])
        run_cleaner = info.get("run_cleaner", False)

        # Set the parent's corpus filter to the checked collection
        # keys. The Training Studio uses _selected_collection_keys
        # to narrow which corpus rows feed export_jsonl. The keys
        # are catalog-prefixed.
        parent = self.parent()
        if parent is not None and hasattr(
                parent, '_selected_collection_keys'):
            keys = {f"catalog:{e.id}" for e in entries}
            parent._selected_collection_keys = keys
            try:
                parent._refresh_corpus_filter_button_label()
            except Exception:
                pass
            try:
                parent._refresh_db_summary()
            except Exception:
                pass

        names_html = "<br>&nbsp;&nbsp;• " + "<br>&nbsp;&nbsp;• ".join(
            f"<b>{e.name[:50]}</b>" for e in entries[:8])
        if len(entries) > 8:
            names_html += (
                f"<br>&nbsp;&nbsp;… and {len(entries) - 8} more")
        msg = (f"Training subset ready: <b>{len(entries)} "
               f"corpora</b>.<br><br>{names_html}<br><br>"
               f"The corpus filter is set on Step 1 — Start "
               f"Training will use ONLY these corpora.")
        QMessageBox.information(
            self, "Training subset set", msg)

        if run_cleaner and parent is not None and hasattr(
                parent, '_open_clean_corpus_dialog'):
            try:
                parent._open_clean_corpus_dialog()
            except Exception:
                pass

        # Close the library dialog so the user lands back on
        # Step 1 ready to train.
        self.accept()

    def _download_checked(self):
        entries = self._checked_entries()
        if not entries:
            return
        # Surface user-attested entries in one prompt rather than
        # interrupting the loop for each.
        attested = [e for e in entries
                    if (e.license or "").lower() == "user-attested"]
        if attested:
            names = "\n".join(f"  • {e.name}" for e in attested[:8])
            more = (f"\n  …and {len(attested) - 8} more"
                    if len(attested) > 8 else "")
            reply = QMessageBox.question(
                self, "Attestation required",
                f"{len(attested)} corpus/corpora require you to "
                f"attest you have the right to download and use the "
                f"source for training:\n\n{names}{more}\n\n"
                f"Click Yes to attest for all of them, No to skip "
                f"those entries (the rest will still download), "
                f"or Cancel to abort.",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.No:
                entries = [e for e in entries
                           if (e.license or "").lower() != "user-attested"]
                if not entries:
                    return

        from src.data.corpus_downloader import CorpusLicenseError
        from PyQt6.QtCore import QEventLoop
        self.log_box.clear()
        self.download_btn.setEnabled(False)
        self.use_for_training_btn.setEnabled(False)

        # Set up the aggregate bar across all entries; entry bar is
        # reset per-entry as each worker emits progress signals.
        total_entries = len(entries)
        self.aggregate_bar.setRange(0, total_entries)
        self.aggregate_bar.setValue(0)
        self.aggregate_bar.setVisible(True)
        self.entry_bar.setRange(0, 0)  # busy by default until first signal
        self.entry_bar.setValue(0)
        self.entry_bar.setVisible(True)

        ok = 0
        skipped = []
        failed = []
        try:
            for i, entry in enumerate(entries, 1):
                self.progress_label.setText(
                    f"[{i}/{total_entries}] {entry.name}")
                self.log_box.appendPlainText(
                    f"\n[{i}/{total_entries}] downloading {entry.name}…")

                # Run one worker per entry, blocking the loop on a
                # local QEventLoop. This gives us a real off-thread
                # download (the UI stays responsive during multi-
                # minute HF streams) while keeping the sequential
                # semantics the previous code had.
                worker = _CorpusDownloadWorker(entry, self.db_path)
                worker_loop = QEventLoop()

                outcome = {"status": "ok", "msg": ""}

                def _on_log(s: str):
                    self.log_box.appendPlainText(f"  {s}")

                def _on_progress(current: int, total: int, label: str):
                    if total > 0:
                        self.entry_bar.setRange(0, total)
                        self.entry_bar.setValue(current)
                        # Format hint: include label so the user
                        # can see whether we're streaming, writing,
                        # parsing, etc.
                        self.entry_bar.setFormat(f"{label} — %p%")
                    else:
                        # Indeterminate: spin the busy bar and put
                        # the label + counter in the format.
                        self.entry_bar.setRange(0, 0)
                        self.entry_bar.setFormat(
                            f"{label} — {current:,}"
                            if current else label)

                def _on_ok(_n_passages: int):
                    outcome["status"] = "ok"
                    worker_loop.quit()

                def _on_failed(msg: str):
                    outcome["status"] = "failed"
                    outcome["msg"] = msg
                    worker_loop.quit()

                worker.log.connect(_on_log)
                worker.progress.connect(_on_progress)
                worker.finished_ok.connect(_on_ok)
                worker.failed.connect(_on_failed)
                worker.start()
                worker_loop.exec()
                worker.wait()

                if outcome["status"] == "ok":
                    ok += 1
                else:
                    msg = outcome["msg"]
                    if "license" in msg.lower() or "attest" in msg.lower():
                        skipped.append(entry.name)
                        self.log_box.appendPlainText(
                            f"  needs attestation, skipped: {msg}")
                    else:
                        failed.append((entry.name, msg))
                        self.log_box.appendPlainText(
                            f"  failed: {msg}")

                self.aggregate_bar.setValue(i)
        finally:
            self.download_btn.setEnabled(True)
            self.use_for_training_btn.setEnabled(True)
            self.progress_label.setText(
                f"Done — {ok}/{total_entries} ingested")
            self.entry_bar.setVisible(False)
            # Leave the aggregate bar visible at its final value so
            # the user can see the completion state at a glance.

        # Refresh so the ✓ markers update for everything just downloaded.
        self._refresh_list()

        # Wrap-up summary
        msg_parts = [f"<b>{ok}</b> corpus/corpora ingested."]
        if skipped:
            msg_parts.append(f"<br>Skipped (attestation): "
                             f"{', '.join(skipped[:5])}"
                             + ("…" if len(skipped) > 5 else ""))
        if failed:
            msg_parts.append(
                f"<br><span style='color:#dc2626;'>{len(failed)} "
                f"failed:</span> "
                + "; ".join(f"{n} ({e[:40]})" for n, e in failed[:3])
                + ("…" if len(failed) > 3 else ""))
        QMessageBox.information(self, "Bulk download complete",
                                "".join(msg_parts))

        # If "Use checked for training" is in flight, continue
        # into phase 2 now that the downloads have settled.
        if getattr(self, '_pending_post_download', None):
            self._finish_use_for_training()

    # ── Add/Remove (act on highlighted row, not checked) ──

    def _add_local_corpus(self):
        """Register a folder or zip on disk as a first-class catalog
        entry. The dialog handles metadata (id/name/genres/etc.) and
        the registry stores ``format=local_folder`` or ``local_zip``;
        the downloader's local-path branch then handles ingest.
        """
        dlg = _AddLocalCorpusDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entry = dlg.get_entry()
            if entry is None:
                return
            from src.data.corpus_registry import add_user_entry
            if add_user_entry(entry):
                self._refresh_list()
                QMessageBox.information(
                    self, "Corpus registered",
                    f"<b>{entry.name}</b> is now in your catalog.<br><br>"
                    f"Tick its row and hit <b>⬇ Download checked</b> to "
                    f"ingest its contents into your training database.")
            else:
                QMessageBox.warning(
                    self, "Could Not Add",
                    "Couldn't save that entry — id may collide with a "
                    "built-in entry, or the id field is empty.")

    def _add_custom(self):
        dlg = _AddCorpusDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entry = dlg.get_entry()
            if entry is None:
                return
            from src.data.corpus_registry import add_user_entry
            if add_user_entry(entry):
                self._refresh_list()
            else:
                QMessageBox.warning(
                    self, "Could Not Add",
                    "Couldn't save that entry — it may collide with a "
                    "built-in id, or the id field is empty.")

    def _remove_selected(self):
        from src.data.corpus_registry import remove_user_entry, builtin_ids
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(
                self, "Pick a row",
                "Highlight a custom-added row in the list (single click) "
                "to remove it. Built-in entries can't be removed.")
            return
        if entry.id in builtin_ids():
            QMessageBox.information(
                self, "Read-only",
                "Built-in catalog entries cannot be removed.")
            return
        if QMessageBox.question(
                self, "Remove?",
                f"Remove '{entry.name}' from your registry?") != \
                QMessageBox.StandardButton.Yes:
            return
        remove_user_entry(entry.id)
        self._refresh_list()


class _AddCorpusDialog(QDialog):
    """Form for the user to register their own corpus URL."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Custom Corpus")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)

        warning = QLabel(
            "<b>Copyright reminder:</b> only add sources you have the "
            "right to use — public-domain works, your own writing, or "
            "content under a license that permits download and "
            "training. CreativeOS will refuse to download anything "
            "you can't attest to.")
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background: #fef3c7; border: 1px solid #fcd34d; "
            "padding: 8px; border-radius: 6px; color: #78350f;")
        layout.addWidget(warning)

        form = QFormLayout()
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("short-id-with-no-spaces")
        form.addRow("ID:", self.id_edit)

        self.name_edit = QLineEdit()
        form.addRow("Display name:", self.name_edit)

        self.author_edit = QLineEdit()
        form.addRow("Author:", self.author_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://…")
        form.addRow("URL:", self.url_edit)

        self.format_combo = QComboBox()
        for label, value in (("Plain text", "txt"),
                             ("Markdown", "markdown"),
                             ("Project Gutenberg .txt", "gutenberg"),
                             ("EPUB (extracted text)", "epub"),
                             ("Other (LLM-assisted parse)", "llm")):
            self.format_combo.addItem(label, value)
        form.addRow("Format:", self.format_combo)

        self.license_combo = QComboBox()
        from src.data.corpus_catalog import LICENSE_OK
        for lic in sorted(LICENSE_OK):
            self.license_combo.addItem(lic, lic)
        self.license_combo.addItem("user-attested (other)", "user-attested")
        form.addRow("License:", self.license_combo)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(
            "comma-separated tags (genre, voice…)")
        form.addRow("Tags:", self.tags_edit)

        self.desc_edit = QLineEdit()
        form.addRow("Description:", self.desc_edit)

        layout.addLayout(form)

        self.attest_cb = QCheckBox(
            "I attest that I have the right to download and use this "
            "source for training.")
        self.attest_cb.setChecked(False)
        layout.addWidget(self.attest_cb)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._entry = None

    def _on_ok(self):
        if not self.attest_cb.isChecked():
            QMessageBox.warning(
                self, "Attestation Required",
                "Please confirm that you have permission to use this source.")
            return
        if not self.id_edit.text().strip() or not self.url_edit.text().strip():
            QMessageBox.warning(self, "Missing Info",
                                "ID and URL are required.")
            return
        from src.data.corpus_catalog import CorpusEntry
        self._entry = CorpusEntry(
            id=self.id_edit.text().strip(),
            name=self.name_edit.text().strip() or self.id_edit.text().strip(),
            description=self.desc_edit.text().strip(),
            url=self.url_edit.text().strip(),
            license=self.license_combo.currentData() or "user-attested",
            format=self.format_combo.currentData() or "txt",
            author=self.author_edit.text().strip(),
            tags=[t.strip() for t in self.tags_edit.text().split(',')
                  if t.strip()],
            source_page=self.url_edit.text().strip(),
        )
        self.accept()

    def get_entry(self):
        return self._entry


# ── Manage saved presets ───────────────────────────────────────

class _ManagePresetsDialog(QDialog):
    """Browse user-saved training presets; delete the ones that aren't
    pulling their weight. Recent (auto-history) entries aren't shown
    here — they roll over automatically as new trainings start.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Training Presets")
        self.setMinimumSize(540, 420)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Saved presets you can reload from the Training Studio's "
            "Preset combo. Recent training history is automatic — only "
            "the last 3 are kept and they aren't shown here.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑 Delete selected")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh_list()

    def _refresh_list(self) -> None:
        from src.config.training_presets import load_saved
        self.list_widget.clear()
        for p in load_saved():
            label = (f"⭐ {p.name}\n"
                     f"   intent={p.goal or '?'} · "
                     f"base={p.base_model} · "
                     f"epochs={p.epochs}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            self.list_widget.addItem(item)
        if self.list_widget.count() == 0:
            empty = QListWidgetItem(
                "(no saved presets yet — use Save as preset… in Step 1)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(empty)

    def _delete_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return  # placeholder row
        reply = QMessageBox.question(
            self, "Delete preset?",
            f"Delete preset '{name}'? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        from src.config.training_presets import delete_named
        delete_named(name)
        self._refresh_list()


# ── Import chapters from a Writer Tool project ───────────────────

class _ProjectImportDialog(QDialog):
    """Pick chapters from a saved WriterProject and ingest them as
    genre-tagged corpus rows.

    The dialog is forgiving: any chapter content the project knows
    about (active revision, raw ``content``, or content reloaded from
    disk via ``load_content_from_file``) is acceptable. Chapters with
    no readable text are greyed out and can't be selected.

    Imported rows are tagged with:
      * ``source_type = "corpus"`` — same bucket as Upload Local Writing
      * ``voice`` — the user's voice tag (default = project name slug)
      * ``genre`` — comma-separated canonical genre keys the user ticks
      * ``notes`` carries ``project_source=<project name> chapter=<title>``
        so the rows are traceable and can later be filtered out.

    Genre filtering at training time: ``RephraseDatabase.export_jsonl``
    will only include corpus rows whose ``genre`` field overlaps the
    selected training genres (rows with empty ``genre`` are always
    included as generic context).
    """

    def __init__(self, db_path: Path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.setWindowTitle("Import chapters from a Writer Tool project")
        self.setMinimumSize(720, 600)

        self._project = None
        self._project_path: Optional[Path] = None

        self._init_ui()
        self._try_load_last_project()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Pick a project, choose chapters, and tag them with a voice "
            "+ genre(s). The chapters become corpus rows that train "
            "your model in your voice on the genres you select.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 4px;")
        layout.addWidget(intro)

        # ── Project picker row ──
        proj_row = QHBoxLayout()
        proj_row.addWidget(QLabel("Project file:"))
        self.project_path_edit = QLineEdit()
        self.project_path_edit.setPlaceholderText(
            "Path to .json project file (or browse below)")
        proj_row.addWidget(self.project_path_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_project)
        proj_row.addWidget(browse_btn)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._load_project)
        proj_row.addWidget(load_btn)
        layout.addLayout(proj_row)

        self.project_summary = QLabel("(no project loaded)")
        self.project_summary.setStyleSheet(
            "padding: 6px 8px; background: #f9fafb; "
            "border-radius: 4px; font-size: 11px;")
        self.project_summary.setWordWrap(True)
        layout.addWidget(self.project_summary)

        # ── Tabbed picker: Chapters / Characters / Worldbuilding ──
        # Chapters → corpus rows (voice/style training)
        # Characters → SOURCE_CHARACTER (character-generation training)
        # Worldbuilding → SOURCE_WORLDBUILDING (faction/place/lore generation)
        # The taxonomy mirrors what's in rephrase_database._format_row,
        # so each tab's rows automatically use the right prompt template
        # at training time.
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_chapters_tab(), "Chapters")
        self.tabs.addTab(self._build_characters_tab(), "Characters")
        self.tabs.addTab(self._build_worldbuilding_tab(), "Worldbuilding")
        layout.addWidget(self.tabs, 1)

        # ── Voice + genre tagging ──
        tag_form = QFormLayout()
        self.voice_edit = QLineEdit()
        self.voice_edit.setPlaceholderText(
            "e.g. \"my-voice\", \"working-title\", or your pen name")
        tag_form.addRow("Voice tag:", self.voice_edit)

        # Genre multi-select (compact, two columns)
        from src.data import genres as _genres
        genre_widget = QWidget()
        genre_layout = QHBoxLayout(genre_widget)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(4)
        col_a = QVBoxLayout()
        col_b = QVBoxLayout()
        self._genre_checkboxes: dict = {}
        for i, key in enumerate(_genres.all_keys()):
            cb = QCheckBox(_genres.display_name(key))
            cb.setProperty("genre_key", key)
            self._genre_checkboxes[key] = cb
            (col_a if i % 2 == 0 else col_b).addWidget(cb)
        col_a.addStretch()
        col_b.addStretch()
        genre_layout.addLayout(col_a)
        genre_layout.addLayout(col_b)
        genre_layout.addStretch()
        tag_form.addRow("Genres:", genre_widget)
        layout.addLayout(tag_form)

        # Status / log
        self.import_log = QLabel("")
        self.import_log.setWordWrap(True)
        self.import_log.setStyleSheet(
            "padding: 6px 8px; background: #ecfdf5; "
            "border-radius: 4px; color: #065f46; font-size: 11px;")
        self.import_log.setVisible(False)
        layout.addWidget(self.import_log)

        # Action buttons
        bb = QHBoxLayout()
        bb.addStretch()
        self.import_btn = QPushButton("📥 Import selected chapters")
        self.import_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 16px; border-radius: 6px; font-weight: bold; }")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._do_import)
        bb.addWidget(self.import_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bb.addWidget(close_btn)
        layout.addLayout(bb)

    # ── Project loading ──

    # ── Tab builders ──

    def _build_chapters_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(QLabel(
            "Chapters become <b>corpus</b> rows (voice/style training). "
            "Each chapter is split into paragraphs; sentences become "
            "prompt → completion pairs that teach the model to continue "
            "prose in your voice."))
        self.chapter_list = QListWidget()
        self.chapter_list.setMinimumHeight(180)
        v.addWidget(self.chapter_list, 1)
        btns = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(lambda: self._toggle_all(self.chapter_list, True))
        btns.addWidget(all_btn)
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(lambda: self._toggle_all(self.chapter_list, False))
        btns.addWidget(none_btn)
        btns.addStretch()
        v.addLayout(btns)
        return page

    def _build_characters_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(QLabel(
            "Characters become <b>character</b> training rows. The "
            "model learns to expand a brief like <i>'a stoic detective "
            "named Mira'</i> into the full profile you've written: "
            "personality, backstory, traits, appearance."))
        self.character_list = QListWidget()
        self.character_list.setMinimumHeight(180)
        v.addWidget(self.character_list, 1)
        btns = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(lambda: self._toggle_all(self.character_list, True))
        btns.addWidget(all_btn)
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(lambda: self._toggle_all(self.character_list, False))
        btns.addWidget(none_btn)
        btns.addStretch()
        v.addLayout(btns)
        return page

    def _build_worldbuilding_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.addWidget(QLabel(
            "Factions, places, cultures, magic systems, and "
            "technologies become <b>worldbuilding</b> training rows. "
            "Element type stays in the prompt template (\"Generate a "
            "faction…\", \"Generate a magic system…\") so a trained "
            "model can produce typed worldbuilding entries on demand."))
        self.worldbuilding_list = QListWidget()
        self.worldbuilding_list.setMinimumHeight(220)
        v.addWidget(self.worldbuilding_list, 1)
        btns = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(
            lambda: self._toggle_all(self.worldbuilding_list, True))
        btns.addWidget(all_btn)
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(
            lambda: self._toggle_all(self.worldbuilding_list, False))
        btns.addWidget(none_btn)
        btns.addStretch()
        v.addLayout(btns)
        return page

    @staticmethod
    def _toggle_all(list_widget: QListWidget, checked: bool) -> None:
        state = (Qt.CheckState.Checked if checked
                 else Qt.CheckState.Unchecked)
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _try_load_last_project(self) -> None:
        """Pre-fill the path with the last project the Writing Tool used."""
        try:
            from src.config.ai_config import get_ai_config
            last = get_ai_config().get_last_project_path() or ""
        except Exception:
            last = ""
        if last:
            self.project_path_edit.setText(last)
            # Best-effort auto-load — ignore failures and let the user
            # pick their own file via Browse.
            self._load_project()

    def _browse_project(self) -> None:
        # Default to the parent of the currently-typed path, or HOME.
        current = self.project_path_edit.text().strip()
        start = (str(Path(current).parent)
                 if current and Path(current).exists()
                 else str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a Writer Tool project file",
            start,
            "Writer Tool projects (*.json);;All Files (*)")
        if path:
            self.project_path_edit.setText(path)
            self._load_project()

    def _load_project(self) -> None:
        path = self.project_path_edit.text().strip()
        if not path:
            return
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Not found",
                                f"No file at {p}.")
            return
        try:
            from src.models.project import WriterProject
            project = WriterProject.load_project(str(p))
        except Exception as e:
            QMessageBox.warning(self, "Could not load",
                                f"Failed to read project file:\n{e}")
            return

        self._project = project
        self._project_path = p
        # Default voice tag to a slug of the project name.
        if not self.voice_edit.text().strip() and project.name:
            slug = "".join(
                ch.lower() if ch.isalnum() else "-"
                for ch in project.name).strip("-")
            self.voice_edit.setText(slug or "")

        # Try to detect the project's genre from its metadata.
        genre_meta = (getattr(project, "genre", "") or "").lower()
        if genre_meta:
            from src.data.genres import match_genres
            for key in match_genres(genre_meta):
                if key in self._genre_checkboxes:
                    self._genre_checkboxes[key].setChecked(True)

        chapters = list(project.manuscript.chapters or [])
        characters = list(getattr(project, "characters", []) or [])
        wb_entities = self._collect_worldbuilding(project)

        self.project_summary.setText(
            f"<b>{project.name or '(unnamed)'}</b><br>"
            f"{len(chapters)} chapter(s) · "
            f"{len(characters)} character(s) · "
            f"{len(wb_entities)} worldbuilding entry(ies) · "
            f"genre on file: {genre_meta or '—'}")
        self._populate_chapters(chapters)
        self._populate_characters(characters)
        self._populate_worldbuilding(wb_entities)
        self.import_btn.setEnabled(
            bool(chapters or characters or wb_entities))

    def _populate_chapters(self, chapters) -> None:
        """Render one row per chapter; greying out empty ones."""
        self.chapter_list.clear()
        project_dir = (self._project_path.parent
                       if self._project_path else None)
        for ch in chapters:
            text = self._chapter_text(ch, project_dir)
            wc = len(text.split()) if text else 0
            label = (f"Chapter {ch.number}: {ch.title or '(untitled)'}  "
                     f"— {wc:,} words")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            if not text or wc < 50:
                # Greyed-out: not enough text to be useful as corpus.
                item.setFlags(Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor("#9ca3af"))
                item.setToolTip(
                    "Skipped — chapter content empty or too short to "
                    "produce useful training passages.")
            else:
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setToolTip(
                    f"Chapter {ch.number} · {wc:,} words · will produce "
                    f"~{max(1, wc // 200)} training passage(s).")
            self.chapter_list.addItem(item)

    def _chapter_text(self, chapter, project_dir: Optional[Path]) -> str:
        """Return the best plain-text content for a chapter.

        Tries (in order): the chapter's ``content`` field, the active
        revision's content, then ``load_content_from_file`` to pull
        from disk if the project hasn't loaded it yet.
        """
        text = (chapter.content or "").strip()
        if text:
            return text
        try:
            rev = chapter._get_active_revision()
            if rev and (rev.content or "").strip():
                return rev.content.strip()
        except Exception:
            pass
        if project_dir is not None:
            try:
                if chapter.load_content_from_file(project_dir):
                    return (chapter.content or "").strip()
            except Exception:
                pass
        return ""

    def _select_all_chapters(self) -> None:
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _select_no_chapters(self) -> None:
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    # ── Characters ──

    def _populate_characters(self, characters) -> None:
        self.character_list.clear()
        for ch in characters:
            prompt, completion = self._character_to_pair(ch)
            short_role = (ch.character_type or "character").lower()
            label = (f"{ch.name or '(unnamed)'}  "
                     f"— {short_role}  "
                     f"({len(completion)} chars of detail)")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            if not completion or len(completion) < 80:
                item.setFlags(Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor("#9ca3af"))
                item.setToolTip(
                    "Skipped — character has too little detail to be "
                    "useful as training data (need personality / "
                    "backstory / appearance, etc.).")
            else:
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setToolTip(prompt + "\n\n" + completion[:300] + "…")
            self.character_list.addItem(item)

    @staticmethod
    def _character_to_pair(character) -> tuple:
        """Convert a Character into a (prompt, completion) pair.

        Prompt is a short brief in the style the character generator is
        trained to receive; completion is the full structured profile
        the model should produce. Empty fields are dropped — the model
        learns from whatever the user actually wrote.
        """
        name = (character.name or "").strip() or "an unnamed character"
        ctype = (character.character_type or "character").strip().lower()
        prompt = f"Generate a complete character profile for {name}, a {ctype}."

        parts = []
        if (character.personality or "").strip():
            parts.append(f"Personality: {character.personality.strip()}")
        if (character.backstory or "").strip():
            parts.append(f"Backstory: {character.backstory.strip()}")
        appearance = (character.physical_description or "").strip()
        if appearance:
            parts.append(f"Appearance: {appearance}")
        if (character.notes or "").strip():
            parts.append(f"Notes: {character.notes.strip()}")
        completion = "\n\n".join(parts)
        return prompt, completion

    # ── Worldbuilding ──

    def _collect_worldbuilding(self, project) -> List[dict]:
        """Pull every worldbuilding entity into a normalized list.

        Each item: ``{kind, id, name, prompt, completion}``. ``kind``
        is the element_type tag (faction / place / culture / magic /
        technology) that ends up in the row's notes — the trainer's
        prompt template uses it to generate "Generate a magic system…"
        style instructions when this row trains.
        """
        wb = getattr(project, "worldbuilding", None)
        if wb is None:
            return []

        out: List[dict] = []

        def _add(kind: str, entity):
            prompt, completion = self._worldbuilding_to_pair(kind, entity)
            if not completion or len(completion) < 60:
                return
            ent_id = getattr(entity, "id", None) or f"{kind}:{getattr(entity, 'name', '?')}"
            out.append({
                "kind": kind,
                "id": ent_id,
                "name": getattr(entity, "name", "(unnamed)"),
                "prompt": prompt,
                "completion": completion,
            })

        for f in getattr(wb, "factions", []) or []:
            _add("faction", f)
        for p in getattr(wb, "places", []) or []:
            _add("place", p)
        for c in getattr(wb, "cultures", []) or []:
            _add("culture", c)
        for m in getattr(wb, "magic_systems", []) or []:
            _add("magic_system", m)
        for t in getattr(wb, "technologies", []) or []:
            _add("technology", t)
        return out

    @staticmethod
    def _worldbuilding_to_pair(kind: str, entity) -> tuple:
        """Convert a worldbuilding entity into a (prompt, completion).

        Walks the entity's fields generically — anything that's a
        non-empty string gets included, with type-specific list /
        dict handling. Empty entities produce empty completions and
        are skipped upstream.
        """
        name = (getattr(entity, "name", "") or "").strip() or "an unnamed entry"
        type_field = ""
        for attr in ("faction_type", "place_type", "magic_type",
                     "technology_type"):
            v = getattr(entity, attr, None)
            if v is not None:
                type_field = (str(v.value) if hasattr(v, "value")
                              else str(v))
                break
        kind_label = kind.replace("_", " ")
        if type_field:
            prompt = (f"Generate a worldbuilding {kind_label} of type "
                      f"'{type_field}' named {name}.")
        else:
            prompt = f"Generate a worldbuilding {kind_label} named {name}."

        # Generic completion — every non-empty primitive/list/dict field
        # gets a labeled line. Order is stable for reproducibility.
        # ``mode='json'`` makes pydantic serialize enums as their value
        # ("military") instead of the repr ("FactionType.MILITARY"), so
        # the training data matches the user's actual content.
        SKIP_FIELDS = {"id"}
        parts: List[str] = []
        try:
            data = entity.model_dump(mode="json")
        except Exception:
            try:
                data = entity.dict()  # pydantic v1
            except Exception:
                data = {}
        for field_name, value in data.items():
            if field_name in SKIP_FIELDS or value in (None, "", [], {}):
                continue
            label = field_name.replace("_", " ").capitalize()
            if isinstance(value, list):
                if all(isinstance(v, str) for v in value):
                    parts.append(f"{label}: {', '.join(value)}")
                else:
                    # list of objects — skip; too noisy for training
                    continue
            elif isinstance(value, dict):
                if all(isinstance(v, (str, int, float)) for v in value.values()):
                    pretty = "; ".join(f"{k}: {v}" for k, v in value.items())
                    parts.append(f"{label}: {pretty}")
            else:
                parts.append(f"{label}: {value}")
        completion = "\n".join(parts)
        return prompt, completion

    def _populate_worldbuilding(self, entries: List[dict]) -> None:
        self.worldbuilding_list.clear()
        if not entries:
            placeholder = QListWidgetItem(
                "(no worldbuilding entries with usable detail)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.worldbuilding_list.addItem(placeholder)
            return
        for e in entries:
            label = (f"[{e['kind']}] {e['name']}  "
                     f"({len(e['completion'])} chars)")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, e["id"])
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(
                e["prompt"] + "\n\n" + e["completion"][:400] + "…")
            self.worldbuilding_list.addItem(item)

    # ── Ingest ──

    def _checked_ids_in(self, list_widget: QListWidget) -> List[str]:
        ids = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if (item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                    and item.checkState() == Qt.CheckState.Checked):
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid:
                    ids.append(cid)
        return ids

    def _selected_chapter_ids(self) -> List[str]:
        return self._checked_ids_in(self.chapter_list)

    def _selected_genres(self) -> List[str]:
        return [k for k, cb in self._genre_checkboxes.items()
                if cb.isChecked()]

    def _do_import(self) -> None:
        """Import every ticked item across the three tabs.

        Each tab routes to a different ``source_type`` so the trainer's
        prompt templates pick the right one:
          - Chapters → ``corpus``         (continue prose in voice)
          - Characters → ``character``    (generate full profile)
          - Worldbuilding → ``worldbuilding`` (generate typed element)
        """
        if self._project is None:
            QMessageBox.warning(self, "No project",
                                "Load a project first.")
            return

        chapter_ids = self._selected_chapter_ids()
        character_ids = self._checked_ids_in(self.character_list)
        wb_ids = self._checked_ids_in(self.worldbuilding_list)
        if not chapter_ids and not character_ids and not wb_ids:
            QMessageBox.information(
                self, "Nothing selected",
                "Tick at least one chapter, character, or worldbuilding "
                "entry across the three tabs.")
            return

        voice = self.voice_edit.text().strip()
        genres = self._selected_genres()
        genre_str = ",".join(genres)

        db = RephraseDatabase(self.db_path)
        project_dir = (self._project_path.parent
                       if self._project_path else None)
        project_label = (self._project.name or
                         (self._project_path.stem if self._project_path
                          else "project"))
        notes_base = f"project_source={project_label}"

        # 1. Chapters → corpus rows
        chapters_by_id = {ch.id: ch
                          for ch in self._project.manuscript.chapters}
        passages_done = 0
        chapters_done = 0
        for cid in chapter_ids:
            ch = chapters_by_id.get(cid)
            if ch is None:
                continue
            text = self._chapter_text(ch, project_dir)
            if not text or len(text.split()) < 50:
                continue
            title = (f"{project_label} — Ch {ch.number}: "
                     f"{ch.title or 'untitled'}")
            n = self._ingest_chapter_text(
                db, text, title=title,
                voice=voice, genre=genre_str,
                project_source=project_label)
            passages_done += n
            chapters_done += 1

        # 2. Characters → SOURCE_CHARACTER rows
        characters_by_id = {c.id: c
                            for c in (getattr(self._project, "characters", [])
                                      or [])}
        chars_done = 0
        for cid in character_ids:
            c = characters_by_id.get(cid)
            if c is None:
                continue
            prompt, completion = self._character_to_pair(c)
            if not completion or len(completion) < 80:
                continue
            db.log_character(
                prompt=prompt, completion=completion,
                character_name=c.name,
                voice=voice, genre=genre_str,
                notes=notes_base)
            chars_done += 1

        # 3. Worldbuilding → SOURCE_WORLDBUILDING rows
        wb_entries = self._collect_worldbuilding(self._project)
        wb_by_id = {e["id"]: e for e in wb_entries}
        wb_done = 0
        for wid in wb_ids:
            entry = wb_by_id.get(wid)
            if entry is None:
                continue
            db.log_worldbuilding(
                prompt=entry["prompt"],
                completion=entry["completion"],
                element_type=entry["kind"],
                voice=voice, genre=genre_str,
                notes=notes_base)
            wb_done += 1

        # Surface a per-tab summary so the user can confirm the right
        # rows landed in each source-type bucket.
        self.import_log.setVisible(True)
        lines = [f"✓ Imported from <b>{project_label}</b>:"]
        if chapters_done:
            lines.append(f"  • {chapters_done} chapter(s) → "
                         f"<b>{passages_done}</b> corpus passages")
        if chars_done:
            lines.append(f"  • {chars_done} character(s) → "
                         f"<b>{chars_done}</b> character training rows")
        if wb_done:
            lines.append(f"  • {wb_done} worldbuilding entry(ies) → "
                         f"<b>{wb_done}</b> worldbuilding training rows")
        lines.append(
            f"Tagged voice=<code>{voice or '(none)'}</code>, "
            f"genre=<code>{genre_str or '(none)'}</code>.")
        self.import_log.setText("<br>".join(lines))

    @staticmethod
    def _ingest_chapter_text(db: RephraseDatabase, text: str, *,
                             title: str,
                             voice: str = "",
                             genre: str = "",
                             project_source: str = "") -> int:
        """Split chapter text into passages and log as corpus rows.

        Runs every paragraph through the shared text_cleaner before
        logging — strips PG-style boilerplate, AI refusal templates,
        tool-call JSON, page numbers, and section headings. The
        cleaner is conservative: real prose passes through unchanged,
        and the format hint is "plain" since chapters from the
        writing tool are user-authored markdown / plain text without
        Gutenberg-specific artifacts.
        """
        import re
        from src.data.text_cleaner import clean_passages
        from src.data.corpus_downloader import _split_paragraph_for_training
        paragraphs = [p.strip()
                      for p in re.split(r'\n\s*\n+', text)
                      if p.strip()]
        # First-pass: drop the markdown structural lines (headings,
        # list items, blockquotes) before running the cleaner.
        prose_paragraphs = [p for p in paragraphs
                            if p.lstrip()[:1] not in '#-*•>']
        cleaned, _stats = clean_passages(
            prose_paragraphs, format_hint="plain")
        n = 0
        notes_extra = (f"project_source={project_source}"
                       if project_source else "")
        for para in cleaned:
            opener, rest = _split_paragraph_for_training(para)
            if opener is None:
                continue
            db.log_corpus_pair(
                prompt=opener, completion=rest, title=title,
                voice=voice, genre=genre,
                notes=notes_extra)
            n += 1
        return n


# ── Trained-models manager ────────────────────────────────────

class _TrainedModelsDialog(QDialog):
    """List and delete locally-trained models.

    Deletion goes through ``creativeos_config.delete_trained_model``,
    which:
      * removes the registry entry,
      * wipes the model directory on disk,
      * clears any per-task model setting that pointed at this name
        (so the writing tool falls back through general → global —
        nothing left in a broken state),
      * invalidates any AgentSuite's cached LLM clients.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trained Models")
        self.setMinimumSize(640, 460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Locally-trained models live in "
            "<code>~/.creativeos/trained_models/&lt;name&gt;/</code>. "
            "Deleting one wipes its files and clears every tool that "
            "was pointing at it — settings revert to defaults so "
            "nothing breaks.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list_widget, 1)

        # Show what tools/settings reference the selected model so the
        # user knows what will reset on delete.
        self.references_label = QLabel("")
        self.references_label.setWordWrap(True)
        self.references_label.setStyleSheet(
            "padding: 6px 8px; background: #fef3c7; "
            "border-radius: 4px; color: #78350f; font-size: 11px;")
        self.references_label.setVisible(False)
        layout.addWidget(self.references_label)

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑 Delete selected (with files)")
        self.delete_btn.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; "
            "padding: 5px 12px; border-radius: 5px; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.delete_btn.setEnabled(False)
        # Lambda absorbs Qt's ``checked`` bool — without this the
        # signal would pass it as a positional arg and the keyword-
        # only ``remove_files`` would explode with a TypeError, making
        # the click silently fail in the UI.
        self.delete_btn.clicked.connect(
            lambda _=False: self._delete_selected(remove_files=True))
        btn_row.addWidget(self.delete_btn)

        self.unregister_btn = QPushButton("Unregister only (keep files)")
        self.unregister_btn.setToolTip(
            "Drop the registry entry but leave the model directory on "
            "disk. Useful when you want to free up the slot but not "
            "lose the weights.")
        self.unregister_btn.setEnabled(False)
        self.unregister_btn.clicked.connect(
            lambda _=False: self._delete_selected(remove_files=False))
        btn_row.addWidget(self.unregister_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.list_widget.currentItemChanged.connect(self._on_selection)
        self._refresh_list()

    def _refresh_list(self) -> None:
        from src.config.creativeos_config import load_trained_models
        self.list_widget.clear()
        models = load_trained_models()
        if not models:
            placeholder = QListWidgetItem(
                "(no trained models yet — train one in Step 3)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
            return
        for m in models:
            ds_size = m.get("dataset_size", 0)
            label = (f"{m.get('name', '?')}\n"
                     f"   base: {m.get('base_model', '?')}  ·  "
                     f"trained on {ds_size} rows  ·  "
                     f"{m.get('created_at', '')}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, m.get("name", ""))
            item.setToolTip(f"path: {m.get('path', '')}")
            self.list_widget.addItem(item)

    def _on_selection(self, current, _previous) -> None:
        """Highlight any settings that reference the selected model."""
        if current is None:
            self.delete_btn.setEnabled(False)
            self.unregister_btn.setEnabled(False)
            self.references_label.setVisible(False)
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            self.delete_btn.setEnabled(False)
            self.unregister_btn.setEnabled(False)
            self.references_label.setVisible(False)
            return

        self.delete_btn.setEnabled(True)
        self.unregister_btn.setEnabled(True)

        # Find which per-task settings point at this model
        try:
            from src.config.creativeos_config import (
                get_creativeos_config, TASK_MODEL_KEYS, TASK_MODEL_LABELS,
            )
            cfg = get_creativeos_config()
            refs = []
            for key in TASK_MODEL_KEYS:
                if cfg.get(key) == name:
                    refs.append(TASK_MODEL_LABELS.get(key, key))
            if refs:
                self.references_label.setText(
                    f"<b>'{name}' is currently selected as the "
                    f"per-task model for:</b><br>"
                    f"  • " + "<br>  • ".join(refs) + "<br>"
                    f"<br>Deleting will clear those settings. The "
                    f"writing tool will fall back to your general / "
                    f"global model automatically.")
                self.references_label.setVisible(True)
            else:
                self.references_label.setVisible(False)
        except Exception:
            self.references_label.setVisible(False)

    def _delete_selected(self, *, remove_files: bool = True) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        action = "Delete" if remove_files else "Unregister"
        body = (f"{action} model '{name}'?")
        if remove_files:
            body += ("\n\nThis removes the model directory from disk "
                     "and clears any per-task setting pointing at it. "
                     "Cannot be undone.")
        else:
            body += ("\n\nKeeps the model files on disk; only removes "
                     "the registry entry and per-task references. You "
                     "can re-register later by editing the registry.")
        reply = QMessageBox.question(
            self, action, body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        from src.config.creativeos_config import delete_trained_model
        delete_trained_model(name, remove_files=remove_files)
        self._refresh_list()
        self.references_label.setVisible(False)
        self.delete_btn.setEnabled(False)
        self.unregister_btn.setEnabled(False)


# ── Variability prune dialog ──────────────────────────────────

class _VariabilityAuditWorker(QThread):
    """Run the audit off the UI thread.

    The SQL-only phase finishes in ~4s on a typical 800K-row DB,
    but the per-row compression + TTR pass adds another ~15s. The
    ``progress`` signal carries ``(current, total, label)`` —
    same shape as the corpus downloader — so the dialog can show
    a real progress bar instead of a spinner.
    """
    finished_ok = pyqtSignal(object)  # VariabilityReport
    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path

    def run(self):
        try:
            from src.ai.corpus_variability import audit_variability
            db = RephraseDatabase(self.db_path)
            report = audit_variability(
                db,
                on_progress=lambda c, t, lbl:
                    self.progress.emit(c, t, lbl))
            self.finished_ok.emit(report)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class _TopicAnalysisWorker(QThread):
    """Run the TF-IDF + KMeans topic clustering on demand.

    Slow (~2-3 min on 800K rows) and pulls in scikit-learn, so we
    only fire this when the user explicitly clicks "Analyze
    topics" on the corresponding card. Same progress signal shape
    as the audit worker.
    """
    finished_ok = pyqtSignal(object)  # TopicAnalysis
    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path

    def run(self):
        try:
            from src.ai.corpus_variability import (
                analyze_topic_distribution,
            )
            db = RephraseDatabase(self.db_path)
            analysis = analyze_topic_distribution(
                db,
                on_progress=lambda c, t, lbl:
                    self.progress.emit(c, t, lbl))
            self.finished_ok.emit(analysis)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class _PruneApplyWorker(QThread):
    """Run ``collect_ids_to_drop`` + ``apply_pruning`` off the UI
    thread so the dialog stays responsive during the multi-second
    delete phase. Backup-write happens inline on the worker too;
    we hand the result back to the UI for a single confirmation.
    """
    finished_ok = pyqtSignal(int, str)  # (n_deleted, backup_path)
    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)

    def __init__(self, db_path: Path, plan, *,
                 backup_path: Path):
        super().__init__()
        self.db_path = db_path
        self.plan = plan
        self.backup_path = backup_path

    def run(self):
        try:
            from src.ai.corpus_variability import (
                collect_ids_to_drop, apply_pruning,
            )
            db = RephraseDatabase(self.db_path)
            self.progress.emit(0, 0, "computing IDs to drop")
            ids = collect_ids_to_drop(db, self.plan)
            total = sum(len(v) for v in ids.values())
            if total == 0:
                self.finished_ok.emit(0, "")
                return
            # Backup phase — write rows-to-be-deleted as JSONL with
            # the category they're being dropped under.
            import json as _json
            self.progress.emit(0, total, "writing backup")
            wrote = 0
            with open(self.backup_path, "w", encoding="utf-8") as f:
                for category, id_list in ids.items():
                    if not id_list:
                        continue
                    CHUNK = 500
                    for i in range(0, len(id_list), CHUNK):
                        chunk = id_list[i:i + CHUNK]
                        placeholders = ",".join("?" * len(chunk))
                        cur = db._conn().execute(
                            f"SELECT * FROM rephrases "
                            f"WHERE id IN ({placeholders})",
                            chunk)
                        rid_to_cat = {rid: category for rid in chunk}
                        for row in cur:
                            d = dict(row)
                            d["_prune_category"] = rid_to_cat.get(
                                int(d["id"]), category)
                            f.write(_json.dumps(d, default=str) + "\n")
                            wrote += 1
                            if wrote % 1000 == 0:
                                self.progress.emit(
                                    wrote, total, "writing backup")
            self.progress.emit(total, total, "writing backup")
            # Delete phase.
            self.progress.emit(0, total, "deleting rows")
            n_deleted = apply_pruning(db, ids)
            self.progress.emit(total, total, "deleting rows")
            self.finished_ok.emit(n_deleted, str(self.backup_path))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class _VariabilityPruneDialog(QDialog):
    """Audit + prune the corpus for variability.

    Three categories the user toggles independently:

      * **Exact duplicates** — rows whose ``output_text`` is byte-
        for-byte identical to another row. Drops all but the
        oldest copy. Always safe; the model learned nothing from
        the duplicates.
      * **Repeated openers** — rows whose first 80 chars match
        another row's, capped at 5 distinct outputs per opener.
        Catches templated boilerplate that escaped exact-dedup.
      * **Source dominance** — any source with more than 40% of
        rows is randomly sampled down to 40%. Prevents one corpus
        from drowning out the others.

    Shown stats include per-category drop counts (computed as if
    each category were applied alone) and a few example groups so
    the user can sanity-check what's being removed before
    approving. Approving multiple categories applies them in order
    — exact → opener → source-dominance — with later categories
    only acting on rows the earlier ones haven't already marked.
    """

    def __init__(self, db_path: Path, *, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._report = None  # set by worker
        self._worker: Optional[_VariabilityAuditWorker] = None

        self.setWindowTitle("Prune corpus for variability")
        self.setMinimumSize(720, 600)
        self._build_ui()
        self._kick_off_audit()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("<b>Prune corpus for variability</b>")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        layout.addWidget(title)

        intro = QLabel(
            "Looks for rows that hurt corpus diversity — exact "
            "duplicates, oversampled openers, and dominant "
            "sources — and lets you approve each category before "
            "anything is dropped. Separate from <i>Clean junk "
            "rows</i>: this drops <b>redundant</b> rows, not "
            "<b>bad</b> ones.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#374151;font-size:12px;")
        layout.addWidget(intro)

        # Status / scanning indicator.
        self.status_label = QLabel("Scanning DB…")
        self.status_label.setStyleSheet(
            "background:#f3f4f6;border-radius:4px;padding:8px;"
            "font-family:monospace;font-size:11px;")
        layout.addWidget(self.status_label)

        # Progress bar shown during the per-row compression + TTR
        # pass (~15s on 800K rows). Hidden once the audit completes.
        self.audit_bar = QProgressBar()
        self.audit_bar.setRange(0, 1)
        self.audit_bar.setValue(0)
        self.audit_bar.setFormat("%p%")
        self.audit_bar.setVisible(False)
        layout.addWidget(self.audit_bar)

        # ── Per-category checkbox blocks. Built once, rendered
        # empty until the audit completes.
        # Wrapped in a QScrollArea because the five cards together
        # — each with a wrapped description, a stats line, and up
        # to six wrapped example lines — easily exceed any
        # reasonable dialog height. Without scrolling, the bottom
        # cards (and the summary + Apply button below them) get
        # pushed off-screen on a typical laptop display.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll_inner = QWidget()
        cards_layout = QVBoxLayout(scroll_inner)
        cards_layout.setContentsMargins(0, 0, 4, 0)
        cards_layout.setSpacing(8)

        self.exact_box = self._build_category_box(
            title="Exact duplicates",
            desc=("Same output_text as another row, byte-for-"
                  "byte. Always safe to drop — keeps the oldest "
                  "copy of each."),
            color_bg="#fef2f2", color_border="#fecaca",
            color_text="#991b1b")
        cards_layout.addWidget(self.exact_box["frame"])

        self.opener_box = self._build_category_box(
            title="Repeated openers",
            desc=("Different bodies but identical first 80 "
                  "characters of output. Caps each opener at 5 "
                  "rows — beyond that we're oversampling the "
                  "same starting cadence."),
            color_bg="#fefce8", color_border="#fde68a",
            color_text="#854d0e")
        cards_layout.addWidget(self.opener_box["frame"])

        self.source_box = self._build_category_box(
            title="Source dominance",
            desc=("Sources with more than 40% of total rows get "
                  "randomly sampled down to 40%. Prevents one "
                  "corpus from drowning out the others. Applied "
                  "AFTER dedup — recomputed on what survives."),
            color_bg="#eff6ff", color_border="#bfdbfe",
            color_text="#1e40af")
        cards_layout.addWidget(self.source_box["frame"])

        self.repetitive_box = self._build_category_box(
            title="Repetitive rows (compression ratio)",
            desc=("Long rows whose output_text compresses to < 25% "
                  "of its size. Catches dialogue-tag spam, list "
                  "outputs, and repeated tokens that surface-byte "
                  "dedup misses. Lower compression = more "
                  "repetitive."),
            color_bg="#fdf2f8", color_border="#fbcfe8",
            color_text="#9d174d")
        cards_layout.addWidget(self.repetitive_box["frame"])

        self.low_div_box = self._build_category_box(
            title="Low-diversity rows (type-token ratio)",
            desc=("Rows with a unique-words ratio below 0.35 over "
                  "≥50 words. Flags shallow content even when "
                  "compression looks fine — e.g. \"Alice said. "
                  "Bob said. Carol said.\" has decent compression "
                  "but very low TTR."),
            color_bg="#f0fdf4", color_border="#bbf7d0",
            color_text="#14532d")
        cards_layout.addWidget(self.low_div_box["frame"])

        self.near_dup_box = self._build_category_box(
            title="Near-duplicates (MinHash + LSH)",
            desc=("Rows whose 5-word shingles have ≥85% Jaccard "
                  "overlap with another row. Catches paraphrased "
                  "/ lightly-edited duplicates exact-dedup misses. "
                  "Drops all but the oldest in each cluster."),
            color_bg="#fff7ed", color_border="#fed7aa",
            color_text="#9a3412")
        cards_layout.addWidget(self.near_dup_box["frame"])

        self.lang_box = self._build_category_box(
            title="Non-English rows (language detection)",
            desc=("Rows whose detected language is not English. "
                  "HuggingFace datasets sometimes include "
                  "non-English content in supposedly-English "
                  "splits. Requires the `langdetect` package — "
                  "the audit notes when it's missing."),
            color_bg="#f5f3ff", color_border="#ddd6fe",
            color_text="#5b21b6")
        cards_layout.addWidget(self.lang_box["frame"])

        # Topic-clustering card has an extra "Analyze topics" button
        # because the analysis is slow (2-3 min) and pulls in
        # scikit-learn — we only run it when the user opts in. Until
        # they click, the checkbox stays disabled.
        self.topic_box = self._build_topic_card()
        cards_layout.addWidget(self.topic_box["frame"])

        # Trailing stretch keeps the cards anchored at the top of
        # the scroll viewport so empty space (when there's only
        # one populated category) appears below the cards rather
        # than expanding them.
        cards_layout.addStretch()
        scroll.setWidget(scroll_inner)
        # ``stretch=1`` makes the scroll area absorb the dialog's
        # spare vertical space; the header above and footer below
        # stay at their natural heights.
        layout.addWidget(scroll, 1)

        # Footer summary + actions.
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding:8px;background:#f9fafb;border-radius:4px;"
            "color:#111827;")
        layout.addWidget(self.summary_label)

        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.cancel_btn)
        actions.addStretch()
        self.apply_btn = QPushButton("✓ Apply approved categories")
        self.apply_btn.setStyleSheet(
            "QPushButton { background:#10b981; color:white; "
            "padding:6px 14px; border-radius:5px; font-weight:bold; } "
            "QPushButton:disabled { background:#d1d5db; }")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        actions.addWidget(self.apply_btn)
        layout.addLayout(actions)

    def _build_category_box(self, *, title: str, desc: str,
                            color_bg: str, color_border: str,
                            color_text: str) -> Dict[str, Any]:
        """Build a labelled bordered group with a checkbox + text.

        Returns the widgets the audit-render step will populate
        with concrete numbers + sample groups once the report
        comes back.
        """
        frame = QGroupBox(title)
        frame.setStyleSheet(
            f"QGroupBox {{ background:{color_bg}; "
            f"border:1px solid {color_border}; "
            f"border-radius:6px; padding-top:18px; margin-top:6px; "
            f"font-weight:bold; color:{color_text}; }}")
        v = QVBoxLayout(frame)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"color:{color_text}; font-size:11px; font-weight:normal;")
        v.addWidget(desc_lbl)

        cb = QCheckBox("Drop these rows")
        cb.setEnabled(False)
        cb.toggled.connect(self._update_summary)
        v.addWidget(cb)

        stats_lbl = QLabel("")
        stats_lbl.setWordWrap(True)
        stats_lbl.setStyleSheet(
            "color:#111827; font-size:11px; font-weight:normal;")
        v.addWidget(stats_lbl)

        examples_lbl = QLabel("")
        examples_lbl.setWordWrap(True)
        examples_lbl.setTextFormat(Qt.TextFormat.RichText)
        examples_lbl.setStyleSheet(
            "color:#374151; font-size:10px; font-weight:normal; "
            "font-family:monospace; padding-top:4px;")
        v.addWidget(examples_lbl)

        return {
            "frame": frame, "checkbox": cb,
            "stats": stats_lbl, "examples": examples_lbl,
        }

    def _build_topic_card(self) -> Dict[str, Any]:
        """Special card for the topic-clustering category.

        Differs from the standard cards because clustering is slow
        and opt-in: we don't fire it during the initial audit.
        Instead the card shows an "Analyze topics" button up front;
        the rest of the card (checkbox, stats, examples) stays
        empty until the user clicks the button and the analysis
        finishes.
        """
        frame = QGroupBox("Topic over-representation (TF-IDF + KMeans)")
        frame.setStyleSheet(
            "QGroupBox { background:#ecfeff; border:1px solid #a5f3fc; "
            "border-radius:6px; padding-top:18px; margin-top:6px; "
            "font-weight:bold; color:#155e75; }")
        v = QVBoxLayout(frame)

        desc_lbl = QLabel(
            "Clusters rows by content similarity (50 topics) and "
            "caps any cluster bigger than 5% of the corpus. Catches "
            "subject-matter over-representation that surface "
            "measures miss — e.g. lots of \"swords and dragons\" "
            "rows that all read differently. Slow (~2-3 min on a "
            "large DB) and requires <code>scikit-learn</code>, so "
            "it runs only when you click the button below.")
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            "color:#155e75; font-size:11px; font-weight:normal;")
        v.addWidget(desc_lbl)

        # The "compute" button itself + a status-on-click line.
        btn_row = QHBoxLayout()
        analyze_btn = QPushButton("🔬 Analyze topics")
        analyze_btn.setStyleSheet(
            "QPushButton { background:#0891b2; color:white; "
            "padding:5px 12px; border-radius:5px; }"
            "QPushButton:disabled { background:#cbd5e1; color:#64748b; }")
        analyze_btn.clicked.connect(self._on_analyze_topics_clicked)
        btn_row.addWidget(analyze_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        cb = QCheckBox("Drop these rows")
        cb.setEnabled(False)
        cb.toggled.connect(self._update_summary)
        v.addWidget(cb)

        stats_lbl = QLabel(
            "<i>Click <b>Analyze topics</b> to run TF-IDF + "
            "KMeans clustering. This typically takes 2-3 minutes "
            "on a large corpus.</i>")
        stats_lbl.setWordWrap(True)
        stats_lbl.setStyleSheet(
            "color:#155e75; font-size:11px; font-weight:normal;")
        v.addWidget(stats_lbl)

        examples_lbl = QLabel("")
        examples_lbl.setWordWrap(True)
        examples_lbl.setTextFormat(Qt.TextFormat.RichText)
        examples_lbl.setStyleSheet(
            "color:#374151; font-size:10px; font-weight:normal; "
            "font-family:monospace; padding-top:4px;")
        v.addWidget(examples_lbl)

        return {
            "frame": frame, "checkbox": cb,
            "stats": stats_lbl, "examples": examples_lbl,
            "analyze_btn": analyze_btn,
            "analysis": None,  # holds the TopicAnalysis once done
        }

    # ── Topic clustering — on-demand ──────────────────────

    def _on_analyze_topics_clicked(self):
        """Kick off TF-IDF + KMeans on a worker thread.

        Reuses the dialog's existing ``audit_bar`` so the user
        gets a unified progress experience whether the bar is
        showing the initial audit, the topic compute, or the
        apply-phase. Disables the Apply button while we work so
        the user can't fire two operations against the same DB.
        """
        self.topic_box["analyze_btn"].setEnabled(False)
        self.topic_box["analyze_btn"].setText("Analyzing…")
        self.audit_bar.setVisible(True)
        self.audit_bar.setRange(0, 0)
        self.audit_bar.setFormat("starting topic analysis")
        self.apply_btn.setEnabled(False)
        self._topic_worker = _TopicAnalysisWorker(self.db_path)
        self._topic_worker.progress.connect(self._on_topic_progress)
        self._topic_worker.finished_ok.connect(self._on_topics_done)
        self._topic_worker.failed.connect(self._on_topics_failed)
        self._topic_worker.start()

    def _on_topic_progress(self, current: int, total: int, label: str):
        # Same shape as ``_on_audit_progress`` but updates the
        # status line to mention k-means / TF-IDF specifically so
        # the user knows what's running.
        if total > 0:
            self.audit_bar.setRange(0, total)
            self.audit_bar.setValue(current)
            self.audit_bar.setFormat(f"{label} — %p%")
        else:
            self.audit_bar.setRange(0, 0)
            self.audit_bar.setFormat(label)
        self.status_label.setText(
            f"Topic analysis: <b>{label}</b>")

    def _on_topics_done(self, analysis):
        self.topic_box["analysis"] = analysis
        self.topic_box["analyze_btn"].setEnabled(True)
        self.topic_box["analyze_btn"].setText("🔬 Re-analyze")
        self.audit_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        if not analysis.available:
            self.topic_box["stats"].setText(
                f"<span style='color:#b91c1c;'>"
                f"{analysis.error}</span>")
            return
        if analysis.error:
            self.topic_box["stats"].setText(
                f"<span style='color:#b91c1c;'>"
                f"{analysis.error}</span>")
            return
        if analysis.total_drops == 0:
            self.topic_box["stats"].setText(
                f"Clustered {analysis.total_rows:,} rows into "
                f"{analysis.n_clusters} topics. None exceeds the "
                f"5% cap — no over-representation detected.")
            return
        cb = self.topic_box["checkbox"]
        cb.setEnabled(True)
        cb.setChecked(False)
        self.topic_box["stats"].setText(
            f"Clustered {analysis.total_rows:,} rows into "
            f"{analysis.n_clusters} topics. "
            f"<b>{len(analysis.over_cap_clusters):,}</b> "
            f"exceed the 5% cap · would drop "
            f"<b>{analysis.total_drops:,}</b> rows.")
        lines = ["<i>Largest over-cap clusters:</i><br>"]
        for c in analysis.over_cap_clusters[:6]:
            terms = ", ".join(c.top_terms[:6]) if c.top_terms else "—"
            preview = (c.sample_text[:90].replace("<", "&lt;")
                       .replace(">", "&gt;"))
            lines.append(
                f"&nbsp;&nbsp;<b>cluster {c.cluster_id}</b>: "
                f"{c.rows:,} rows ({c.pct_of_total:.1f}%) → "
                f"cap {c.target_rows:,} (drop {c.drops:,})<br>"
                f"&nbsp;&nbsp;&nbsp;&nbsp;<i>terms:</i> {terms}<br>"
                f"&nbsp;&nbsp;&nbsp;&nbsp;<i>sample:</i> "
                f"{preview}…")
        self.topic_box["examples"].setText("<br>".join(lines))
        self._update_summary()

    def _on_topics_failed(self, msg: str):
        self.topic_box["analyze_btn"].setEnabled(True)
        self.topic_box["analyze_btn"].setText("🔬 Analyze topics")
        self.audit_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.topic_box["stats"].setText(
            f"<span style='color:#b91c1c;'>"
            f"Topic analysis failed: {msg}</span>")

    # ── Audit ─────────────────────────────────────────────

    def _kick_off_audit(self):
        self.audit_bar.setVisible(True)
        self._worker = _VariabilityAuditWorker(self.db_path)
        self._worker.progress.connect(self._on_audit_progress)
        self._worker.finished_ok.connect(self._on_audit_done)
        self._worker.failed.connect(self._on_audit_failed)
        self._worker.start()

    def _on_audit_progress(self, current: int, total: int, label: str):
        if total > 0:
            self.audit_bar.setRange(0, total)
            self.audit_bar.setValue(current)
            self.audit_bar.setFormat(f"{label} — %p%")
        else:
            self.audit_bar.setRange(0, 0)
            self.audit_bar.setFormat(label)
        self.status_label.setText(
            f"{label}: {current:,} of {total:,}")

    def _on_audit_done(self, report):
        self._report = report
        self.audit_bar.setVisible(False)
        self.status_label.setText(
            f"Scanned <b>{report.total_rows:,}</b> accepted rows.")
        self._render_report(report)
        self.apply_btn.setEnabled(True)
        self._update_summary()

    def _on_audit_failed(self, msg: str):
        self.status_label.setText(
            f"<span style='color:#b91c1c'>Audit failed: {msg}</span>")

    def _render_report(self, report):
        # Exact dupes
        cb = self.exact_box["checkbox"]
        if report.exact_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(True)
            self.exact_box["stats"].setText(
                f"<b>{report.exact_groups:,}</b> duplicate groups · "
                f"would drop <b>{report.exact_drops:,}</b> rows.")
            self.exact_box["examples"].setText(
                self._examples_block(report.exact_examples,
                                     "× duplicates"))
        else:
            self.exact_box["stats"].setText(
                "No exact duplicates found.")

        # Opener dupes
        cb = self.opener_box["checkbox"]
        if report.opener_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(False)  # less aggressive default
            self.opener_box["stats"].setText(
                f"<b>{report.opener_groups:,}</b> over-cap opener "
                f"groups · would drop <b>{report.opener_drops:,}"
                f"</b> rows.")
            self.opener_box["examples"].setText(
                self._examples_block(report.opener_examples,
                                     " distinct outputs"))
        else:
            self.opener_box["stats"].setText(
                "No oversampled openers detected.")

        # Source dominance
        cb = self.source_box["checkbox"]
        if report.source_dominance:
            cb.setEnabled(True)
            cb.setChecked(False)
            self.source_box["stats"].setText(
                f"<b>{len(report.source_dominance):,}</b> source(s) "
                f"over the 40% cap · "
                f"would drop up to <b>"
                f"{report.source_dominance_drops:,}</b> rows "
                f"(recomputed against post-dedup state).")
            lines = []
            for s in report.source_dominance:
                lines.append(
                    f"&nbsp;&nbsp;{s.label}: <b>{s.rows:,}</b> rows "
                    f"({s.pct_of_total:.1f}%) → cap "
                    f"{s.target_rows:,} (drop {s.drops:,})")
            self.source_box["examples"].setText("<br>".join(lines))
        else:
            self.source_box["stats"].setText(
                "No source exceeds the 40% cap.")

        # Repetitive rows
        cb = self.repetitive_box["checkbox"]
        if report.repetitive_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(False)
            self.repetitive_box["stats"].setText(
                f"<b>{report.repetitive_drops:,}</b> rows compress "
                f"to < 25% of their size (≥200 chars).")
            lines = ["<i>Most repetitive examples (lowest "
                     "compression ratio first):</i><br>"]
            for ex in report.repetitive_examples[:6]:
                preview = (ex.sample_text[:90].replace("<", "&lt;")
                           .replace(">", "&gt;"))
                lines.append(
                    f"&nbsp;&nbsp;ratio={ex.n_dupes / 100:.2f}: "
                    f"{preview}…")
            self.repetitive_box["examples"].setText(
                "<br>".join(lines))
        else:
            self.repetitive_box["stats"].setText(
                "No highly-repetitive rows detected.")

        # Low-diversity rows
        cb = self.low_div_box["checkbox"]
        if report.low_diversity_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(False)
            self.low_div_box["stats"].setText(
                f"<b>{report.low_diversity_drops:,}</b> rows have "
                f"TTR below 0.35 (≥50 words).")
            lines = ["<i>Lowest-TTR examples first:</i><br>"]
            for ex in report.low_diversity_examples[:6]:
                preview = (ex.sample_text[:90].replace("<", "&lt;")
                           .replace(">", "&gt;"))
                lines.append(
                    f"&nbsp;&nbsp;TTR={ex.n_dupes / 100:.2f}: "
                    f"{preview}…")
            self.low_div_box["examples"].setText(
                "<br>".join(lines))
        else:
            self.low_div_box["stats"].setText(
                "No low-diversity rows detected.")

        # Near-duplicates (MinHash + LSH)
        cb = self.near_dup_box["checkbox"]
        if report.near_dup_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(False)
            self.near_dup_box["stats"].setText(
                f"<b>{report.near_dup_clusters:,}</b> near-duplicate "
                f"clusters · would drop <b>{report.near_dup_drops:,}"
                f"</b> rows (keeping the oldest in each cluster).")
            lines = ["<i>Largest clusters first:</i><br>"]
            for ex in report.near_dup_examples[:6]:
                preview = (ex.sample_text[:90].replace("<", "&lt;")
                           .replace(">", "&gt;"))
                lines.append(
                    f"&nbsp;&nbsp;{ex.n_dupes} similar rows: "
                    f"{preview}…")
            self.near_dup_box["examples"].setText(
                "<br>".join(lines))
        else:
            self.near_dup_box["stats"].setText(
                "No near-duplicate clusters detected.")

        # Language detection
        cb = self.lang_box["checkbox"]
        if not report.langdetect_available:
            cb.setEnabled(False)
            self.lang_box["stats"].setText(
                "<i>langdetect not installed — run "
                "<code>pip install langdetect</code> to enable "
                "this category.</i>")
        elif report.non_target_lang_drops > 0:
            cb.setEnabled(True)
            cb.setChecked(False)
            # Render the breakdown (top 6 by count) so the user can
            # see which languages are actually showing up.
            top_langs = sorted(
                report.lang_breakdown.items(),
                key=lambda kv: -kv[1])[:6]
            breakdown = " · ".join(
                f"<b>{lang}</b>: {n:,}" for lang, n in top_langs)
            self.lang_box["stats"].setText(
                f"<b>{report.non_target_lang_drops:,}</b> rows "
                f"detected as non-English.<br>"
                f"<span style='color:#374151;font-size:11px;'>"
                f"Detected languages: {breakdown}</span>")
            lines = ["<i>Examples:</i><br>"]
            for ex in report.non_target_lang_examples[:6]:
                preview = (ex.sample_text[:120].replace("<", "&lt;")
                           .replace(">", "&gt;"))
                lines.append(f"&nbsp;&nbsp;{preview}…")
            self.lang_box["examples"].setText(
                "<br>".join(lines))
        else:
            self.lang_box["stats"].setText(
                "All accepted rows detected as English.")

    @staticmethod
    def _examples_block(examples, count_label: str) -> str:
        if not examples:
            return ""
        lines = ["<i>Examples:</i><br>"]
        for ex in examples[:6]:
            preview = (ex.sample_text[:90].replace("<", "&lt;")
                       .replace(">", "&gt;"))
            lines.append(
                f"&nbsp;&nbsp;{ex.n_dupes}{count_label}: "
                f"{preview}…")
        return "<br>".join(lines)

    # ── Live summary ──────────────────────────────────────

    def _update_summary(self):
        if not self._report:
            return
        # Worst-case drop count (each category counted as if applied
        # alone). Actual joint apply will be lower because the
        # categories overlap; we say so in the label.
        approved = []
        upper = 0
        if self.exact_box["checkbox"].isChecked():
            approved.append("exact dupes")
            upper += self._report.exact_drops
        if self.opener_box["checkbox"].isChecked():
            approved.append("repeated openers")
            upper += self._report.opener_drops
        if self.source_box["checkbox"].isChecked():
            approved.append("source dominance")
            upper += self._report.source_dominance_drops
        if self.repetitive_box["checkbox"].isChecked():
            approved.append("repetitive rows")
            upper += self._report.repetitive_drops
        if self.low_div_box["checkbox"].isChecked():
            approved.append("low-diversity rows")
            upper += self._report.low_diversity_drops
        if self.near_dup_box["checkbox"].isChecked():
            approved.append("near-duplicates")
            upper += self._report.near_dup_drops
        if self.lang_box["checkbox"].isChecked():
            approved.append("non-English rows")
            upper += self._report.non_target_lang_drops
        analysis = self.topic_box.get("analysis")
        if (analysis is not None and analysis.available
                and self.topic_box["checkbox"].isChecked()):
            approved.append("topic over-representation")
            upper += analysis.total_drops

        if not approved:
            self.summary_label.setText(
                "<i>Nothing approved yet — pick at least one "
                "category above to enable Apply.</i>")
            return
        worst_remaining = self._report.total_rows - upper
        self.summary_label.setText(
            f"Approved: <b>{', '.join(approved)}</b>.<br>"
            f"Up to <b>{upper:,}</b> rows would be dropped — "
            f"remaining ≥ <b>{worst_remaining:,}</b> rows. "
            f"Joint apply de-duplicates overlap, so the actual "
            f"drop count is usually lower.")

    # ── Apply ─────────────────────────────────────────────

    def _on_apply_clicked(self):
        if not self._report:
            return
        from src.ai.corpus_variability import PruningPlan
        analysis = self.topic_box.get("analysis")
        plan = PruningPlan(
            apply_exact=self.exact_box["checkbox"].isChecked(),
            apply_opener=self.opener_box["checkbox"].isChecked(),
            apply_source_dominance=(
                self.source_box["checkbox"].isChecked()),
            apply_repetitive=(
                self.repetitive_box["checkbox"].isChecked()),
            apply_low_diversity=(
                self.low_div_box["checkbox"].isChecked()),
            apply_near_dup=(
                self.near_dup_box["checkbox"].isChecked()),
            apply_non_target_lang=(
                self.lang_box["checkbox"].isChecked()),
            apply_topic_clustering=(
                analysis is not None
                and analysis.available
                and self.topic_box["checkbox"].isChecked()),
            topic_ids_override=(
                analysis.ids_to_drop
                if (analysis is not None and analysis.available
                    and self.topic_box["checkbox"].isChecked())
                else None),
        )
        if not any([plan.apply_exact, plan.apply_opener,
                    plan.apply_source_dominance,
                    plan.apply_repetitive,
                    plan.apply_low_diversity,
                    plan.apply_near_dup,
                    plan.apply_non_target_lang,
                    plan.apply_topic_clustering]):
            return

        # Best-effort estimate up-front so the user can see what
        # they're about to delete *before* the apply worker
        # finalises the per-category disjoint ID list. Joint
        # apply numbers shrink because of overlap, so we surface
        # the audit's worst-case category counts in the prompt.
        upper = 0
        breakdown_lines = []
        if plan.apply_exact:
            upper += self._report.exact_drops
            breakdown_lines.append(
                f"  • exact: up to {self._report.exact_drops:,}")
        if plan.apply_opener:
            upper += self._report.opener_drops
            breakdown_lines.append(
                f"  • opener: up to {self._report.opener_drops:,}")
        if plan.apply_source_dominance:
            upper += self._report.source_dominance_drops
            breakdown_lines.append(
                f"  • source dominance: up to "
                f"{self._report.source_dominance_drops:,}")
        if plan.apply_repetitive:
            upper += self._report.repetitive_drops
            breakdown_lines.append(
                f"  • repetitive: {self._report.repetitive_drops:,}")
        if plan.apply_low_diversity:
            upper += self._report.low_diversity_drops
            breakdown_lines.append(
                f"  • low diversity: "
                f"{self._report.low_diversity_drops:,}")
        if plan.apply_near_dup:
            upper += self._report.near_dup_drops
            breakdown_lines.append(
                f"  • near-dup: {self._report.near_dup_drops:,}")
        if plan.apply_non_target_lang:
            upper += self._report.non_target_lang_drops
            breakdown_lines.append(
                f"  • non-English: "
                f"{self._report.non_target_lang_drops:,}")
        if plan.apply_topic_clustering and analysis:
            upper += analysis.total_drops
            breakdown_lines.append(
                f"  • topic over-rep: {analysis.total_drops:,}")
        breakdown = "\n".join(breakdown_lines)
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("Confirm prune")
        confirm.setText(
            f"Drop up to <b>{upper:,}</b> rows? "
            f"(Joint apply de-duplicates across categories so the "
            f"actual count will be ≤ this.)\n\n{breakdown}\n\n"
            f"Backups go to ~/.creativeos/cleanup_backup/. "
            f"Irreversible from inside the app, but you can restore "
            f"from the backup JSONL.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Yes)
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Pre-compute backup path so we can show it in the failure
        # dialog if the worker dies mid-flight.
        from datetime import datetime as _dt
        backup_dir = Path.home() / ".creativeos" / "cleanup_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"prune-{ts}.jsonl"

        # Disable the dialog buttons + show the bar. The worker
        # emits progress for ``computing IDs to drop`` (15s+),
        # ``writing backup`` (proportional to row count), and
        # ``deleting rows`` (chunked DELETEs).
        self.apply_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.audit_bar.setVisible(True)
        self.audit_bar.setRange(0, 0)
        self.audit_bar.setFormat("starting prune")
        self.status_label.setText("Applying prune…")

        self._apply_worker = _PruneApplyWorker(
            self.db_path, plan, backup_path=backup_path)
        self._apply_worker.progress.connect(self._on_apply_progress)
        self._apply_worker.finished_ok.connect(self._on_apply_done)
        self._apply_worker.failed.connect(self._on_apply_failed)
        self._apply_worker.start()

    def _on_apply_progress(self, current: int, total: int, label: str):
        if total > 0:
            self.audit_bar.setRange(0, total)
            self.audit_bar.setValue(current)
            self.audit_bar.setFormat(f"{label} — %p%")
        else:
            self.audit_bar.setRange(0, 0)
            self.audit_bar.setFormat(label)
        self.status_label.setText(f"Prune: <b>{label}</b>")

    def _on_apply_done(self, n_deleted: int, backup_path: str):
        self.audit_bar.setVisible(False)
        if n_deleted == 0:
            QMessageBox.information(
                self, "Nothing to drop",
                "After de-duplicating across categories, no rows "
                "would be removed.")
            self.apply_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            return
        QMessageBox.information(
            self, "Prune complete",
            f"Deleted {n_deleted:,} rows. Backup saved to:\n"
            f"{backup_path}")
        self.accept()

    def _on_apply_failed(self, msg: str):
        self.audit_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        QMessageBox.warning(
            self, "Prune failed",
            f"Apply failed: {msg}")


# ── Corpus browser dialog ─────────────────────────────────────

class _CorpusBrowserDialog(QDialog):
    """Search + browse rows in the training DB.

    Until this dialog existed, users could only see aggregate counts
    or a 5-row sample from the quality check. With ~377K rows in a
    real DB, that's not enough to answer "is *Frankenstein* actually
    in there?" or "what does my Aubrigale character data look like?".

    The dialog is a thin wrapper over ``RephraseDatabase.search_rows``:
    a search box, source/genre/corpus filters, a paged table of
    matches, and a detail panel showing the full source/output of
    the selected row. Results page in 200 at a time so a query that
    matches 12,000 rows doesn't blow up the UI.
    """

    PAGE_SIZE = 200

    def __init__(self, db_path: Path, *,
                 initial_query: str = "",
                 initial_corpus_id: str = "",
                 parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._offset = 0
        self._total_matches = 0
        self._rows: List[Dict[str, Any]] = []

        self.setWindowTitle("Browse training DB")
        self.setMinimumSize(1000, 640)
        self._build_ui()
        if initial_query:
            self.query_edit.setText(initial_query)
        if initial_corpus_id:
            # Set the corpus filter combo to a matching entry if it
            # exists in the populated list; otherwise type into the
            # query box. The combo is editable so a free-text fallback
            # always works.
            idx = self.corpus_combo.findData(initial_corpus_id)
            if idx >= 0:
                self.corpus_combo.setCurrentIndex(idx)
        self._refresh()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)

        # Title + intro
        outer.addWidget(QLabel(
            "<b>Browse training DB</b> "
            "<span style='color:#6b7280;font-size:11px;'>"
            "— search by title, free text, or filter by source / "
            "genre / corpus.</span>"))

        # Search row
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            "type a title, character name, phrase… "
            "matches source / output / corpus tag")
        self.query_edit.returnPressed.connect(self._on_query_changed)
        search_row.addWidget(self.query_edit, 1)
        self.search_btn = QPushButton("🔎 Search")
        self.search_btn.clicked.connect(self._on_query_changed)
        search_row.addWidget(self.search_btn)
        outer.addLayout(search_row)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItem("All", "")
        for st in ("corpus", "rephrase", "chat_writing", "chat_general",
                   "agent", "worldbuilding", "character", "plot"):
            self.source_combo.addItem(st, st)
        self.source_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.source_combo)

        filter_row.addWidget(QLabel("Genre:"))
        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("any")
        self.genre_edit.setMaximumWidth(120)
        self.genre_edit.editingFinished.connect(self._on_filter_changed)
        filter_row.addWidget(self.genre_edit)

        filter_row.addWidget(QLabel("Corpus:"))
        self.corpus_combo = QComboBox()
        self.corpus_combo.setEditable(False)
        self.corpus_combo.setMinimumWidth(280)
        self.corpus_combo.addItem("All", "")
        # Populate from list_corpus_collections so the user picks
        # from real ingested corpora rather than typing IDs by hand.
        try:
            db = RephraseDatabase(self.db_path)
            for c in db.list_corpus_collections():
                # Only catalog-style entries have a corpus_id we can
                # filter on directly. Project / upload entries get
                # a label-only display item that we'll handle by
                # forwarding to the query box instead.
                if c["kind"] == "catalog":
                    cid = c["key"].split(":", 1)[1]
                    self.corpus_combo.addItem(
                        f"{cid} ({c['row_count']:,} rows)", cid)
        except Exception:
            pass
        self.corpus_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.corpus_combo)

        filter_row.addStretch()
        outer.addLayout(filter_row)

        # Status / paging row
        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#374151;font-size:12px;")
        status_row.addWidget(self.status_label, 1)

        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.clicked.connect(self._on_prev)
        status_row.addWidget(self.prev_btn)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(self._on_next)
        status_row.addWidget(self.next_btn)
        outer.addLayout(status_row)

        # Splitter: results table on top, detail panel on bottom.
        # The user picks a row, the panel shows full source/output.
        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["id", "type", "source / title", "output (preview)",
             "genre", "rating"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 320)
        self.table.setColumnWidth(3, 380)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 70)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        # Detail panel
        detail_wrap = QWidget()
        detail_layout = QVBoxLayout(detail_wrap)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.addWidget(QLabel(
            "<b>Selected row</b> "
            "<span style='color:#6b7280;font-size:11px;'>"
            "— full source (prompt) + output (completion)"
            "</span>"))
        self.detail_meta = QLabel("Pick a row to see its full text.")
        self.detail_meta.setStyleSheet("color:#6b7280;font-size:11px;")
        detail_layout.addWidget(self.detail_meta)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background-color: #1f2937; color: #d1d5db;")
        detail_layout.addWidget(self.detail_text)
        splitter.addWidget(detail_wrap)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        # Footer
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    # ── Search / paging ───────────────────────────────────

    def _filters(self) -> Dict[str, Any]:
        sources = []
        st = self.source_combo.currentData()
        if st:
            sources = [st]
        return {
            "query": self.query_edit.text().strip(),
            "source_types": sources or None,
            "genre": self.genre_edit.text().strip(),
            "corpus_id": self.corpus_combo.currentData() or "",
        }

    def _refresh(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            db = RephraseDatabase(self.db_path)
            f = self._filters()
            self._total_matches = db.count_search_rows(**f)
            self._rows = db.search_rows(
                **f, limit=self.PAGE_SIZE, offset=self._offset)
            self._render_rows()
            self._render_status()
        except Exception as e:
            self.status_label.setText(
                f"<span style='color:#b91c1c;'>Search failed: "
                f"{e}</span>")
        finally:
            QApplication.restoreOverrideCursor()

    def _render_rows(self):
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            src = row.get("source_text", "") or ""
            out = row.get("output_text", "") or ""
            # Pull title from notes if present so the most useful
            # column shows the actual book / corpus name rather
            # than the (often short, truncated) source_text.
            title = self._extract_title(row.get("notes", "") or "")
            display_src = title or src
            self.table.setItem(i, 0, QTableWidgetItem(str(row.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(
                row.get("source_type", "") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(display_src[:200]))
            self.table.setItem(i, 3, QTableWidgetItem(out[:300]))
            self.table.setItem(i, 4, QTableWidgetItem(
                (row.get("genre", "") or "")[:60]))
            self.table.setItem(i, 5, QTableWidgetItem(
                row.get("rating", "") or ""))
        if self._rows:
            self.table.selectRow(0)
        else:
            self.detail_text.clear()
            self.detail_meta.setText(
                "No rows match these filters. "
                "Try broadening the search.")

    def _render_status(self):
        end = min(self._offset + len(self._rows), self._total_matches)
        if self._total_matches == 0:
            text = "No matches."
        else:
            text = (f"Showing rows <b>{self._offset + 1:,}–"
                    f"{end:,}</b> of <b>{self._total_matches:,}</b> "
                    f"matches.")
        self.status_label.setText(text)
        self.prev_btn.setEnabled(self._offset > 0)
        self.next_btn.setEnabled(end < self._total_matches)

    def _on_query_changed(self):
        self._offset = 0
        self._refresh()

    def _on_filter_changed(self):
        self._offset = 0
        self._refresh()

    def _on_prev(self):
        self._offset = max(0, self._offset - self.PAGE_SIZE)
        self._refresh()

    def _on_next(self):
        if self._offset + self.PAGE_SIZE < self._total_matches:
            self._offset += self.PAGE_SIZE
            self._refresh()

    def _on_row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        i = rows[0].row()
        if i < 0 or i >= len(self._rows):
            return
        row = self._rows[i]
        notes = row.get("notes", "") or ""
        title = self._extract_title(notes)
        meta_parts = [
            f"id={row.get('id', '')}",
            f"type={row.get('source_type', '')}",
        ]
        if title:
            meta_parts.append(f"title={title}")
        if row.get("genre"):
            meta_parts.append(f"genre={row['genre']}")
        if row.get("voice"):
            meta_parts.append(f"voice={row['voice']}")
        if row.get("character_name"):
            meta_parts.append(f"character={row['character_name']}")
        if row.get("rating"):
            meta_parts.append(f"rating={row['rating']}")
        self.detail_meta.setText(" · ".join(meta_parts))
        src = row.get("source_text", "") or ""
        out = row.get("output_text", "") or ""
        self.detail_text.setPlainText(
            f"── PROMPT (source_text) ───────────\n{src}\n\n"
            f"── COMPLETION (output_text) ──────\n{out}\n\n"
            f"── NOTES ──────────────────────────\n{notes}")

    @staticmethod
    def _extract_title(notes: str) -> str:
        """Pull ``corpus_title=...`` value out of a row's notes."""
        import re
        m = re.search(r'corpus_title=(.+?)(?=\s+\w+=|$)',
                      notes, flags=re.DOTALL)
        if m:
            return m.group(1).strip()
        return ""


# ── Per-corpus filter dialog ───────────────────────────────────

class _CorpusFilterDialog(QDialog):
    """Pick which ingested corpus collections feed the next training run.

    Defaults to all-checked. The TrainingToolWindow stores the resulting
    selection on its instance and threads it through ``export_jsonl``
    via the ``corpus_collection_keys`` parameter.
    """

    def __init__(self, db_path: Path, current_selection=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose corpora for this training run")
        self.setMinimumSize(640, 480)
        self._db_path = db_path

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tick the corpora you want to feed the trainer. Catalog "
            "downloads, your local uploads, and project imports each "
            "show up as a separate collection — you can include some "
            "and exclude others without re-ingesting anything.<br><br>"
            "Default: all collections checked, which matches the "
            "previous behavior of \"every corpus row goes in.\"")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 4px;")
        layout.addWidget(intro)

        # Build the checklist
        from src.data.rephrase_database import RephraseDatabase
        db = RephraseDatabase(db_path)
        self._collections = db.list_corpus_collections()

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(280)
        layout.addWidget(self.list_widget, 1)
        for c in self._collections:
            kind_emoji = {"catalog": "📚", "upload": "📁",
                          "project": "📖", "unknown": "•"}.get(c["kind"], "•")
            label = (f"{kind_emoji} {c['label']}  "
                     f"({c['row_count']:,} rows)")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c["key"])
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            # Default-checked unless an explicit current selection
            # excludes this key.
            if current_selection is None or c["key"] in current_selection:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)

        if not self._collections:
            empty = QListWidgetItem(
                "(no corpus rows yet — upload writing, import a "
                "project, or download from the corpus library first)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(empty)

        # Quick actions
        btn_row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(lambda: self._set_all(True))
        btn_row.addWidget(all_btn)
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(none_btn)
        catalog_btn = QPushButton("Catalog only")
        catalog_btn.clicked.connect(self._select_catalog_only)
        btn_row.addWidget(catalog_btn)
        my_btn = QPushButton("My writing only")
        my_btn.clicked.connect(self._select_my_writing)
        btn_row.addWidget(my_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _set_all(self, checked: bool) -> None:
        state = (Qt.CheckState.Checked if checked
                 else Qt.CheckState.Unchecked)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _select_catalog_only(self) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            key = item.data(Qt.ItemDataRole.UserRole) or ""
            item.setCheckState(
                Qt.CheckState.Checked if key.startswith("catalog:")
                else Qt.CheckState.Unchecked)

    def _select_my_writing(self) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            key = item.data(Qt.ItemDataRole.UserRole) or ""
            item.setCheckState(
                Qt.CheckState.Checked
                if key.startswith("upload:") or key.startswith("project:")
                else Qt.CheckState.Unchecked)

    def selected_keys(self):
        """Return the list of currently-checked collection keys.

        Returns ``None`` when every collection is checked — the caller
        treats that as "no filter, include everything," which matches
        the default-all-checked semantics.
        """
        all_keys = [c["key"] for c in self._collections]
        checked = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if (item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                    and item.checkState() == Qt.CheckState.Checked):
                key = item.data(Qt.ItemDataRole.UserRole)
                if key:
                    checked.append(key)
        # Treat all-checked as "no filter" so a fresh DB import flowing
        # in later doesn't get silently excluded.
        if set(checked) == set(all_keys):
            return None
        return checked


# ── Upload corpus (single file, multi-file, or zip) ────────────

class _UploadCorpusDialog(QDialog):
    """Unified upload flow for local writing corpora.

    Accepts: single text/markdown files, multiple text files, or a
    .zip archive containing texts at any depth. Tags every ingested
    row with shared metadata: voice, genre(s), purpose, free-text
    description, and a collection title.

    Purpose maps to the *source_type* the rows are stored under, so
    the trainer's prompt template treats them appropriately:

        voice/style   → SOURCE_CORPUS         (continue-passage task)
        character     → SOURCE_CHARACTER      (profile generation task)
        worldbuilding → SOURCE_WORLDBUILDING  (typed element generation)
        plot          → SOURCE_PLOT           (outline generation)

    A "western literature through the 20th century" zip with purpose
    = voice/style, genre = literary, would land as corpus rows that
    the genre filter routes to literary fine-tunes — and the per-
    corpus filter offers as a single deletable collection.
    """

    PURPOSE_OPTIONS = [
        ("Voice / style imitation",  "voice",          SOURCE_CORPUS),
        ("Character generation",     "character",      SOURCE_CHARACTER),
        ("Worldbuilding / lore",     "worldbuilding",  SOURCE_WORLDBUILDING),
        ("Plot / outline reference", "plot",           SOURCE_PLOT),
    ]

    def __init__(self, db_path: Path, *,
                 seeded_voice: str = "",
                 seeded_genre: str = "",
                 parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.setWindowTitle("Upload corpus")
        self.setMinimumSize(640, 560)
        self._picked_paths: List[Path] = []
        self._init_ui(seeded_voice, seeded_genre)

    def _init_ui(self, seeded_voice: str, seeded_genre: str) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Upload writing samples — single files, a folder of files, "
            "or a <b>.zip archive</b> containing texts. The dialog tags "
            "every row with the metadata below so the trainer routes "
            "them correctly: genre filter, source-type prompts, and "
            "the per-corpus filter all read these tags.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        # ── File picker ──
        pick_row = QHBoxLayout()
        self.pick_btn = QPushButton("📄 Pick text/markdown file(s)…")
        self.pick_btn.clicked.connect(self._pick_files)
        pick_row.addWidget(self.pick_btn)
        self.pick_zip_btn = QPushButton("🗜 Pick a .zip archive…")
        self.pick_zip_btn.clicked.connect(self._pick_zip)
        pick_row.addWidget(self.pick_zip_btn)
        pick_row.addStretch()
        layout.addLayout(pick_row)

        self.picked_label = QLabel("(no files picked yet)")
        self.picked_label.setWordWrap(True)
        self.picked_label.setStyleSheet(
            "padding: 6px 8px; background: #f9fafb; "
            "border-radius: 4px; font-size: 11px;")
        layout.addWidget(self.picked_label)

        # ── Metadata form ──
        form = QFormLayout()

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(
            "auto-derived from file/zip name; editable")
        form.addRow("Collection title:", self.title_edit)

        self.voice_edit = QLineEdit(seeded_voice)
        self.voice_edit.setPlaceholderText(
            "e.g. \"my-voice\", \"jane-austen\", or your pen name")
        form.addRow("Voice tag:", self.voice_edit)

        # Genre multi-select (matches the Step 1 + project-import dialog
        # so the user has a consistent set to pick from)
        from src.data import genres as _genres
        genre_widget = QWidget()
        genre_layout = QHBoxLayout(genre_widget)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(4)
        col_a = QVBoxLayout(); col_b = QVBoxLayout()
        self._genre_checkboxes: dict = {}
        for i, key in enumerate(_genres.all_keys()):
            cb = QCheckBox(_genres.display_name(key))
            self._genre_checkboxes[key] = cb
            (col_a if i % 2 == 0 else col_b).addWidget(cb)
            # Pre-tick anything matching the seeded genre via fuzzy match
            if seeded_genre:
                if key in _genres.match_genres(seeded_genre):
                    cb.setChecked(True)
        col_a.addStretch(); col_b.addStretch()
        genre_layout.addLayout(col_a)
        genre_layout.addLayout(col_b)
        genre_layout.addStretch()
        form.addRow("Genres:", genre_widget)

        # Purpose: how this corpus should be used at training time.
        self.purpose_combo = QComboBox()
        for label, _key, _src in self.PURPOSE_OPTIONS:
            self.purpose_combo.addItem(label)
        form.addRow("Purpose:", self.purpose_combo)

        # Description — free-text. Goes into row notes for traceability.
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText(
            "Optional: notes about the corpus, its source, time period, "
            "or how you want it used. Stored alongside each row.")
        form.addRow("Description:", self.description_edit)

        layout.addLayout(form)

        # Status / log
        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet(
            "padding: 6px 8px; background: #ecfdf5; "
            "border-radius: 4px; color: #065f46; font-size: 11px;")
        self.log_label.setVisible(False)
        layout.addWidget(self.log_label)

        # Action buttons
        bb = QHBoxLayout()
        bb.addStretch()
        self.ingest_btn = QPushButton("📥 Ingest into training DB")
        self.ingest_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 16px; border-radius: 6px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.ingest_btn.setEnabled(False)
        self.ingest_btn.clicked.connect(self._do_ingest)
        bb.addWidget(self.ingest_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bb.addWidget(close_btn)
        layout.addLayout(bb)

    # ── File picking ──

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Pick writing samples", str(Path.home()),
            "Text and Markdown (*.txt *.md);;All Files (*)")
        if not paths:
            return
        self._picked_paths = [Path(p) for p in paths]
        # Auto-derive title from first file
        if not self.title_edit.text().strip():
            self.title_edit.setText(self._picked_paths[0].stem)
        self._update_picked_label()

    def _pick_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a corpus zip", str(Path.home()),
            "Zip archives (*.zip);;All Files (*)")
        if not path:
            return
        self._picked_paths = [Path(path)]
        if not self.title_edit.text().strip():
            self.title_edit.setText(Path(path).stem)
        self._update_picked_label()

    def _update_picked_label(self) -> None:
        if not self._picked_paths:
            self.picked_label.setText("(no files picked yet)")
            self.ingest_btn.setEnabled(False)
            return
        if len(self._picked_paths) == 1 and \
                self._picked_paths[0].suffix.lower() == ".zip":
            p = self._picked_paths[0]
            try:
                size_mb = p.stat().st_size / (1024 * 1024)
            except Exception:
                size_mb = 0.0
            self.picked_label.setText(
                f"📦 <b>{p.name}</b> ({size_mb:.1f}MB) — texts inside "
                f"will be extracted and ingested.")
        else:
            n = len(self._picked_paths)
            sample = ", ".join(p.name for p in self._picked_paths[:3])
            more = f" + {n - 3} more" if n > 3 else ""
            self.picked_label.setText(
                f"📄 <b>{n}</b> file(s) picked: {sample}{more}")
        self.ingest_btn.setEnabled(True)

    # ── Ingest ──

    def _selected_genres(self) -> List[str]:
        return [k for k, cb in self._genre_checkboxes.items()
                if cb.isChecked()]

    def _selected_purpose(self) -> tuple:
        """Return ``(label, key, source_type)`` for the picked purpose."""
        idx = self.purpose_combo.currentIndex()
        return self.PURPOSE_OPTIONS[idx if idx >= 0 else 0]

    def _do_ingest(self) -> None:
        if not self._picked_paths:
            return

        title = (self.title_edit.text().strip()
                 or self._picked_paths[0].stem)
        voice = self.voice_edit.text().strip()
        genres = self._selected_genres()
        genre_str = ",".join(genres)
        purpose_label, purpose_key, source_type = self._selected_purpose()
        description = self.description_edit.toPlainText().strip()

        # Build the notes prefix the per-corpus filter will use to
        # group all of this upload's rows under one collection.
        notes_parts = [f"corpus_title={title}",
                       f"purpose={purpose_key}"]
        if description:
            # Strip newlines so the parser can read the kv pairs
            # cleanly. The parser's regex stops at the next ``key=``
            # boundary, so multi-word descriptions are safe.
            clean_desc = " ".join(description.split())
            notes_parts.append(f"description={clean_desc}")
        notes_template = " ".join(notes_parts)

        db = RephraseDatabase(self.db_path)
        total_rows = 0
        files_processed = 0
        errors = []

        # Expand zip if needed
        text_blobs = []  # list of (filename_label, text)
        for p in self._picked_paths:
            if p.suffix.lower() == ".zip":
                blobs, file_errs = self._read_zip(p)
                text_blobs.extend(blobs)
                errors.extend(file_errs)
            else:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    text_blobs.append((p.stem, text))
                except Exception as e:
                    errors.append(f"{p.name}: {e}")

        # Ingest each blob via the same passage-splitter the project-
        # import dialog uses. EVERY row uses the SAME ``title`` (the
        # collection title) so all rows from this upload group under
        # one collection key in the per-corpus filter — the user
        # thinks of "this zip" as one logical corpus, not N tiny ones.
        # Per-file labels travel in the row notes for traceability
        # but don't fragment the collection.
        for filename_label, text in text_blobs:
            if not text or len(text) < 80:
                continue
            n = self._ingest_text_for_purpose(
                db, text,
                title=title,
                voice=voice, genre=genre_str,
                source_type=source_type,
                notes=f"{notes_template} file={filename_label}")
            total_rows += n
            files_processed += 1

        # Surface results
        msg_parts = [
            f"<b>✓ Ingested</b> {total_rows} training row(s) from "
            f"{files_processed} file(s)."]
        msg_parts.append(
            f"Tagged: voice=<code>{voice or '(none)'}</code>, "
            f"genre=<code>{genre_str or '(none)'}</code>, "
            f"purpose=<code>{purpose_key}</code>, "
            f"source_type=<code>{source_type}</code>.")
        if description:
            msg_parts.append(
                f"Description: <i>\"{description[:120]}"
                f"{'…' if len(description) > 120 else ''}\"</i>")
        if errors:
            msg_parts.append(
                f"<span style='color:#dc2626;'>"
                f"{len(errors)} read error(s):</span> "
                f"{'; '.join(errors[:3])}"
                f"{'…' if len(errors) > 3 else ''}")
        self.log_label.setText("<br>".join(msg_parts))
        self.log_label.setVisible(True)

    @staticmethod
    def _read_zip(zip_path: Path) -> tuple:
        """Stream text files out of a zip archive.

        Returns ``(list_of_(label, text), list_of_errors)``. Skips
        binaries, hidden files, OS metadata files (``__MACOSX/``,
        ``.DS_Store``), and anything that fails UTF-8 / latin-1
        decoding cleanly. Recursive — files at any depth are picked up.
        """
        import zipfile
        out, errors = [], []
        # File extensions we'll attempt to decode as text
        TEXT_EXTS = {".txt", ".md", ".markdown", ".text", ".rtf",
                     ".tex", ".log"}
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if info.is_dir():
                        continue
                    # Skip OS metadata + hidden files
                    if (name.startswith("__MACOSX/")
                            or name.endswith("/.DS_Store")
                            or "/." in name
                            or name.startswith(".")):
                        continue
                    p = Path(name)
                    if p.suffix.lower() not in TEXT_EXTS:
                        continue
                    try:
                        raw = zf.read(info)
                    except Exception as e:
                        errors.append(f"{name}: read failed: {e}")
                        continue
                    text = None
                    for enc in ("utf-8", "latin-1", "utf-16"):
                        try:
                            text = raw.decode(enc)
                            break
                        except Exception:
                            continue
                    if text is None:
                        errors.append(f"{name}: not decodable text")
                        continue
                    out.append((p.stem, text))
        except zipfile.BadZipFile as e:
            errors.append(f"{zip_path.name}: not a valid zip: {e}")
        except Exception as e:
            errors.append(f"{zip_path.name}: {e}")
        return out, errors

    @staticmethod
    def _ingest_text_for_purpose(db: RephraseDatabase, text: str, *,
                                 title: str,
                                 voice: str = "",
                                 genre: str = "",
                                 source_type: str = SOURCE_CORPUS,
                                 notes: str = "") -> int:
        """Split text into passages and log under the right source_type.

        Runs every paragraph through the shared text_cleaner before
        logging. The cleaner is conservative: it preserves real prose
        while dropping obvious junk (boilerplate, tool-call JSON,
        page numbers, section headings, refusal templates). Format
        hint is "plain" since uploaded text is user-authored.
        """
        import re
        from src.data.text_cleaner import clean_passages
        from src.data.corpus_downloader import _split_paragraph_for_training
        paragraphs = [p.strip()
                      for p in re.split(r'\n\s*\n+', text)
                      if p.strip()]
        prose_paragraphs = [p for p in paragraphs
                            if p.lstrip()[:1] not in '#-*•>']
        cleaned, _stats = clean_passages(
            prose_paragraphs, format_hint="plain")
        n = 0
        for para in cleaned:
            opener, rest = _split_paragraph_for_training(para)
            if opener is None:
                continue
            # Route by purpose to the right log_* helper so the
            # source_type column gets the right value AND the
            # downstream _format_row produces the right prompt
            # template. Notes carry the title so the per-corpus
            # filter can group them into one collection.
            kw = dict(prompt=opener, completion=rest,
                      voice=voice, genre=genre, notes=notes)
            if source_type == SOURCE_CORPUS:
                db.log_corpus_pair(title=title, **kw)
            elif source_type == SOURCE_CHARACTER:
                db.log_character(character_name=title, **kw)
            elif source_type == SOURCE_WORLDBUILDING:
                db.log_worldbuilding(element_type="passage", **kw)
            elif source_type == SOURCE_PLOT:
                db.log_plot(**kw)
            else:
                db.log_corpus_pair(title=title, **kw)
            n += 1
        return n


# ── Pacing-pair synthesis dialog ────────────────────────────────

class _PacingPairsDialog(QDialog):
    """Drive ``synthesize_pacing_pairs`` from the UI.

    Lets the user pick a target genre (from CONLIT-covered options),
    cap the number of pairs, and run the synthesizer. Each pair costs
    one LLM call, so we surface the cap clearly and stream progress
    to a log box.
    """

    def __init__(self, db_path: Path,
                 *,
                 selected_collection_keys=None,
                 parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._selected_collection_keys = selected_collection_keys
        self.setWindowTitle("Generate Pacing Training Pairs")
        self.setMinimumSize(640, 540)
        self._init_ui()
        self._refresh_genres()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "<b>How this works:</b> for each corpus row, the configured "
            "LLM is asked to rewrite the passage toward the target "
            "genre's CONLIT pacing baseline. Each rewrite is "
            "automatically verified — only kept if the avg sentence "
            "length really moves closer to the genre norm. The kept "
            "rows train a model to do genre-aware pacing rewrites.<br>"
            "<br>"
            "<b>Cost reminder:</b> each pair = 1 LLM call. Set the "
            "cap below before running.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        form = QFormLayout()
        self.genre_combo = QComboBox()
        form.addRow("Target genre (from CONLIT):", self.genre_combo)

        self.max_pairs_spin = QSpinBox()
        self.max_pairs_spin.setRange(1, 200)
        self.max_pairs_spin.setValue(20)
        self.max_pairs_spin.setToolTip(
            "Cap on training pairs to write. Each = 1 LLM call.")
        form.addRow("Max pairs to generate:", self.max_pairs_spin)

        self.min_words_spin = QSpinBox()
        self.min_words_spin.setRange(20, 1000)
        self.min_words_spin.setValue(100)
        self.min_words_spin.setToolTip(
            "Skip passages shorter than this. Pacing stats on tiny "
            "snippets are too noisy to be useful supervision.")
        form.addRow("Min passage words:", self.min_words_spin)

        self.use_filter_cb = QCheckBox(
            "Limit to corpora picked in the corpus filter dialog")
        self.use_filter_cb.setChecked(self._selected_collection_keys is not None)
        self.use_filter_cb.setEnabled(self._selected_collection_keys is not None)
        if self._selected_collection_keys is None:
            self.use_filter_cb.setToolTip(
                "(disabled — no corpus filter active in the main window)")
        form.addRow("", self.use_filter_cb)

        layout.addLayout(form)

        # Baseline preview — when a genre is picked, show the CONLIT
        # numbers so the user knows what the LLM is targeting.
        self.baseline_label = QLabel("")
        self.baseline_label.setWordWrap(True)
        self.baseline_label.setStyleSheet(
            "padding: 6px 8px; background: #ecfdf5; "
            "border-radius: 4px; color: #065f46; font-size: 11px;")
        self.baseline_label.setVisible(False)
        layout.addWidget(self.baseline_label)
        self.genre_combo.currentIndexChanged.connect(self._refresh_baseline)

        # Progress log
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(180)
        self.log_box.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background-color: #111827; color: #d1d5db;")
        layout.addWidget(self.log_box, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.run_btn = QPushButton("⚙ Run synthesizer")
        self.run_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 14px; border-radius: 6px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.run_btn.clicked.connect(lambda _=False: self._run())
        btn_row.addWidget(self.run_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _refresh_genres(self) -> None:
        """Populate the dropdown with CONLIT-covered canonical genres."""
        try:
            from src.data.conlit_loader import get_genre_stats_cached
            stats = get_genre_stats_cached() or {}
        except Exception as e:
            stats = {}
        self.genre_combo.clear()
        if not stats:
            self.genre_combo.addItem(
                "(CONLIT not loaded — point at CONLIT_META.csv first)",
                None)
            self.run_btn.setEnabled(False)
            return
        for key in sorted(stats.keys()):
            label = stats[key].get("label", key.title())
            n = stats[key].get("n_books", 0)
            self.genre_combo.addItem(
                f"{label}  (n={n} CONLIT books)", key)
        self.run_btn.setEnabled(True)
        self._refresh_baseline()

    def _refresh_baseline(self) -> None:
        try:
            from src.data.conlit_loader import (
                get_genre_stats_cached, summary_lines,
            )
            stats = get_genre_stats_cached() or {}
        except Exception:
            stats = {}
        key = self.genre_combo.currentData()
        if not key or key not in stats:
            self.baseline_label.setVisible(False)
            return
        lines = summary_lines(stats, key)
        if not lines:
            self.baseline_label.setVisible(False)
            return
        self.baseline_label.setText(
            "<br>&nbsp;&nbsp;".join(lines))
        self.baseline_label.setVisible(True)

    def _run(self) -> None:
        from PyQt6.QtWidgets import QApplication
        target_genre = self.genre_combo.currentData()
        if not target_genre:
            return
        max_pairs = self.max_pairs_spin.value()
        min_words = self.min_words_spin.value()
        coll_keys = (self._selected_collection_keys
                     if self.use_filter_cb.isChecked() else None)

        # Confirm cost
        reply = QMessageBox.question(
            self, "Confirm",
            f"Generate up to {max_pairs} pacing pairs targeting "
            f"<b>{target_genre}</b>? Each pair = 1 LLM call.<br><br>"
            f"The synthesizer will skip passages already on-target "
            f"and will discard rewrites that don't actually move "
            f"closer to the baseline.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Build the LLM callable. The configured CreativeOS LLM (cloud
        # or local) handles routing — we reuse the same path the
        # writing tool uses for its plot agent.
        llm_generate = self._build_llm_callable()
        if llm_generate is None:
            QMessageBox.warning(
                self, "No LLM configured",
                "The pacing synthesizer needs a configured LLM (cloud "
                "API key or a local model). Set one up in CreativeOS "
                "settings, then try again.")
            return

        self.run_btn.setEnabled(False)
        self.log_box.clear()
        self.log_box.appendPlainText(
            f"Synthesizing up to {max_pairs} pairs for {target_genre}…")
        QApplication.processEvents()

        from src.ai.pacing_synthesizer import synthesize_pacing_pairs
        db = RephraseDatabase(self.db_path)
        try:
            result = synthesize_pacing_pairs(
                db,
                target_genre,
                llm_generate=llm_generate,
                source_collection_keys=coll_keys,
                max_pairs=max_pairs,
                min_passage_words=min_words,
                on_log=lambda s: (
                    self.log_box.appendPlainText(s),
                    QApplication.processEvents()),
            )
        except Exception as e:
            self.log_box.appendPlainText(f"\n[error] {e}")
            self.run_btn.setEnabled(True)
            return
        self.run_btn.setEnabled(True)

        # Summary
        self.log_box.appendPlainText("")
        self.log_box.appendPlainText("=" * 50)
        if "error" in result:
            self.log_box.appendPlainText(f"FAILED: {result['error']}")
            return
        self.log_box.appendPlainText(
            f"Done. Logged {result['n_logged']} pairs to the training DB "
            f"as plot/pacing rows tagged 'pacing_target={target_genre}'.")
        self.log_box.appendPlainText(
            f"  skipped already-matching: "
            f"{result['n_skipped_already_matching']}")
        self.log_box.appendPlainText(
            f"  skipped no-improvement: "
            f"{result['n_skipped_no_improvement']}")
        self.log_box.appendPlainText(
            f"  failed (LLM errors): {result['n_failed']}")
        self.log_box.appendPlainText(
            f"  baseline targeted: {result['baseline_summary']}")

    @staticmethod
    def _build_llm_callable():
        """Return ``(prompt, system) -> str`` or ``None`` if no LLM
        is configured. Routes via the CreativeOS shared LLM settings:
        prefers the local model when set up, falls back to the
        configured cloud provider.
        """
        try:
            from src.config.creativeos_config import get_creativeos_config
            from src.ai.llm_client import (
                LLMClient, LLMProvider, HuggingFaceConfig,
            )
            cfg = get_creativeos_config()
            s = cfg.shared_llm_settings()
            if cfg.get("disable_all_ai"):
                return None
            llm = None
            if (s.get("prefer_local_model") and s.get("enable_local_models")
                    and s.get("local_model_id")):
                is_mlx = "mlx" in s["local_model_id"].lower()
                hf_config = HuggingFaceConfig(
                    model_id=s["local_model_id"], use_local=True,
                    device=s.get("local_model_device", "auto"),
                    quantization=s.get("local_model_quantization", "none")
                                 if s.get("local_model_quantization") != "none"
                                 else None,
                )
                provider = (LLMProvider.MLX_LOCAL if is_mlx
                            else LLMProvider.HUGGINGFACE_LOCAL)
                llm = LLMClient(provider=provider, hf_config=hf_config)
            else:
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI,
                }
                provider_name = s.get("default_llm", "claude")
                api_key = (
                    s.get("claude_api_key")
                    if provider_name == "claude"
                    else s.get("chatgpt_api_key")
                    if provider_name in ("chatgpt", "openai")
                    else s.get("gemini_api_key"))
                if not api_key:
                    return None
                llm = LLMClient(
                    provider=provider_map.get(provider_name,
                                              LLMProvider.CLAUDE),
                    api_key=api_key)
            return lambda prompt, sys: llm.generate_text(
                prompt=prompt, system_prompt=sys,
                max_tokens=600, temperature=0.4)
        except Exception as e:
            print(f"[_PacingPairsDialog] could not build LLM callable: {e}")
            return None


# ── Add a local-folder / local-zip corpus to the registry ─────

class _AddLocalCorpusDialog(QDialog):
    """Register a corpus that lives on the user's disk.

    A folder of .txt/.md files OR a .zip archive of texts. The dialog
    captures the metadata the rest of CreativeOS needs (genres,
    voice/author tag, license attestation) and writes a registry
    entry with ``format=local_folder`` or ``local_zip``. The downloader
    then handles ingest.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Local Corpus")
        self.setMinimumSize(620, 600)
        self._picked_path: Optional[Path] = None
        self._picked_kind: str = ""    # "folder" | "zip"
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Register a corpus you have on disk. Pick a folder of text "
            "files OR a .zip archive. The contents are walked and "
            "ingested as corpus rows tagged with the metadata below — "
            "the genre filter then routes them to matching fine-tunes "
            "automatically.<br><br>"
            "<b>Copyright reminder:</b> only register sources you have "
            "the right to use. Public-domain works, your own writing, "
            "or content under a permissive license are fine.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "background: #fef3c7; border: 1px solid #fcd34d; "
            "padding: 8px; border-radius: 6px; color: #78350f;")
        layout.addWidget(intro)

        # ── File picker ──
        pick_row = QHBoxLayout()
        self.pick_folder_btn = QPushButton("📁 Pick a folder…")
        self.pick_folder_btn.clicked.connect(self._pick_folder)
        pick_row.addWidget(self.pick_folder_btn)
        self.pick_zip_btn = QPushButton("🗜 Pick a .zip archive…")
        self.pick_zip_btn.clicked.connect(self._pick_zip)
        pick_row.addWidget(self.pick_zip_btn)
        pick_row.addStretch()
        layout.addLayout(pick_row)

        self.path_label = QLabel("(no path picked yet)")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet(
            "padding: 6px 8px; background: #f9fafb; "
            "border-radius: 4px; font-size: 11px; font-family: monospace;")
        layout.addWidget(self.path_label)

        # ── Metadata form ──
        form = QFormLayout()

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText(
            "short-slug-no-spaces (auto-derived from path)")
        form.addRow("Catalog ID:", self.id_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(
            "Display name, e.g. \"Contemporary Western Literature\"")
        form.addRow("Display name:", self.name_edit)

        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText(
            "Author or curator (optional)")
        form.addRow("Author / curator:", self.author_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(70)
        self.desc_edit.setPlaceholderText(
            "What's in this corpus? Source, time period, scope.")
        form.addRow("Description:", self.desc_edit)

        # Genres (multi-select, same taxonomy as everywhere else)
        from src.data import genres as _genres
        genre_widget = QWidget()
        genre_layout = QHBoxLayout(genre_widget)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(4)
        col_a = QVBoxLayout(); col_b = QVBoxLayout()
        self._genre_checkboxes: dict = {}
        for i, key in enumerate(_genres.all_keys()):
            cb = QCheckBox(_genres.display_name(key))
            self._genre_checkboxes[key] = cb
            (col_a if i % 2 == 0 else col_b).addWidget(cb)
        col_a.addStretch(); col_b.addStretch()
        genre_layout.addLayout(col_a)
        genre_layout.addLayout(col_b)
        genre_layout.addStretch()
        form.addRow("Genres:", genre_widget)

        # License — defaults to user-attested for safety
        self.license_combo = QComboBox()
        from src.data.corpus_catalog import LICENSE_OK
        for lic in sorted(LICENSE_OK):
            self.license_combo.addItem(lic, lic)
        self.license_combo.addItem("user-attested (other / unknown)",
                                   "user-attested")
        # Default to user-attested
        for i in range(self.license_combo.count()):
            if self.license_combo.itemData(i) == "user-attested":
                self.license_combo.setCurrentIndex(i)
                break
        form.addRow("License:", self.license_combo)

        layout.addLayout(form)

        # Attestation
        self.attest_cb = QCheckBox(
            "I attest that I have the right to use these texts for "
            "training.")
        layout.addWidget(self.attest_cb)

        # Action buttons
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._entry: Optional[Any] = None

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Pick a corpus folder", str(Path.home()))
        if not path:
            return
        self._picked_path = Path(path)
        self._picked_kind = "folder"
        self._update_path_label()

    def _pick_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a corpus zip", str(Path.home()),
            "Zip archives (*.zip);;All Files (*)")
        if not path:
            return
        self._picked_path = Path(path)
        self._picked_kind = "zip"
        self._update_path_label()

    def _update_path_label(self) -> None:
        if not self._picked_path:
            self.path_label.setText("(no path picked yet)")
            return
        # Auto-derive id + name from the path stem
        stem = self._picked_path.stem
        if not self.id_edit.text().strip():
            slug = "".join(
                ch.lower() if ch.isalnum() else "-"
                for ch in stem).strip("-")
            self.id_edit.setText(f"local-{slug}" if slug else "local-corpus")
        if not self.name_edit.text().strip():
            self.name_edit.setText(stem.replace("_", " ").replace("-", " "))

        # Quick preview: count the eligible files
        try:
            n_files = self._count_eligible_files()
            kind_emoji = "📁" if self._picked_kind == "folder" else "🗜"
            self.path_label.setText(
                f"{kind_emoji} <b>{self._picked_path}</b><br>"
                f"   ~{n_files} text file(s) detected.")
        except Exception as e:
            self.path_label.setText(
                f"<b>{self._picked_path}</b><br>"
                f"   <span style='color:#dc2626;'>preview failed: {e}</span>")

    def _count_eligible_files(self) -> int:
        TEXT_EXTS = {".txt", ".md", ".markdown", ".text", ".rtf", ".tex"}
        if self._picked_kind == "folder":
            n = 0
            for p in self._picked_path.rglob("*"):
                if (p.is_file()
                        and p.suffix.lower() in TEXT_EXTS
                        and not p.name.startswith(".")):
                    n += 1
            return n
        if self._picked_kind == "zip":
            import zipfile
            with zipfile.ZipFile(self._picked_path, "r") as zf:
                return sum(
                    1 for info in zf.infolist()
                    if (not info.is_dir()
                        and Path(info.filename).suffix.lower() in TEXT_EXTS
                        and not info.filename.startswith("__MACOSX/")
                        and "/." not in info.filename
                        and not info.filename.startswith(".")))
        return 0

    def _selected_genres(self) -> List[str]:
        return [k for k, cb in self._genre_checkboxes.items()
                if cb.isChecked()]

    def _on_ok(self) -> None:
        if self._picked_path is None:
            QMessageBox.warning(self, "Pick a path",
                                "Pick a folder or zip first.")
            return
        if not self.id_edit.text().strip():
            QMessageBox.warning(self, "ID required",
                                "Catalog ID is required.")
            return
        if not self.attest_cb.isChecked():
            QMessageBox.warning(
                self, "Attestation required",
                "Please confirm you have the right to use these texts.")
            return

        from src.data.corpus_catalog import CorpusEntry
        fmt = ("local_folder" if self._picked_kind == "folder"
               else "local_zip")
        license_val = self.license_combo.currentData() or "user-attested"
        genres = self._selected_genres()
        # Genres become ``tags`` on the catalog entry — that's how the
        # genre tag flows through to log_corpus_pair at ingest time.
        tags = ["fiction", "local"] + list(genres)

        # Estimate size — use folder/zip size in KB
        size_kb = 0
        try:
            if self._picked_kind == "zip":
                size_kb = max(1, self._picked_path.stat().st_size // 1024)
            else:
                total = 0
                for p in self._picked_path.rglob("*"):
                    if p.is_file():
                        try:
                            total += p.stat().st_size
                        except Exception:
                            pass
                size_kb = max(1, total // 1024)
        except Exception:
            size_kb = 0

        self._entry = CorpusEntry(
            id=self.id_edit.text().strip(),
            name=self.name_edit.text().strip()
                 or self.id_edit.text().strip(),
            description=self.desc_edit.toPlainText().strip()
                        or "User-registered local corpus.",
            url=str(self._picked_path),  # ``url`` carries the local path
            license=license_val,
            license_url="",
            format=fmt,
            author=self.author_edit.text().strip(),
            tags=tags,
            size_hint_kb=size_kb,
            source_page=str(self._picked_path),
            purpose="voice",
            medium="books",
        )
        self.accept()

    def get_entry(self):
        return self._entry


# ── Rephrase-pair synthesis dialog ──────────────────────────────

class _RephrasePairsDialog(QDialog):
    """Drive ``rephrase_synthesizer.synthesize_rephrase_pairs`` from
    the UI. Same shape as the pacing-pair dialog but with rephrase-
    specific knobs: bigram overlap thresholds (so the user can tune
    the "different enough" filter) and a max-pair cap.
    """

    def __init__(self, db_path: Path,
                 *, selected_collection_keys=None, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._selected_collection_keys = selected_collection_keys
        self.setWindowTitle("Synthesize Rephrase Training Pairs")
        self.setMinimumSize(620, 580)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "<b>How this works:</b> for each corpus row, the configured "
            "LLM paraphrases the passage. Each rewrite is verified by "
            "two gates: <b>bigram overlap</b> with the original (must "
            "be &lt; 0.7 — not a verbatim echo, &gt; 0.15 — not "
            "hallucinated off-meaning) and <b>length similarity</b> "
            "(within ±30% of the original word count). Pairs that pass "
            "are saved as <code>SOURCE_REPHRASE</code> rows tagged "
            "with the source's voice + genre.<br><br>"
            "<b>Why this beats raw paraphrase corpora alone:</b> the "
            "rewrites inherit the source corpus's voice/genre tags, "
            "so a rephrase model trained on these learns to rephrase "
            "WITHIN the user's preferred style — not just generic "
            "English-to-English paraphrasing.<br><br>"
            "<b>Cost reminder:</b> each pair = 1 LLM call. Set the "
            "cap below before running.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        form = QFormLayout()

        self.max_pairs_spin = QSpinBox()
        self.max_pairs_spin.setRange(1, 500)
        self.max_pairs_spin.setValue(30)
        self.max_pairs_spin.setToolTip(
            "Cap on training pairs. Each = 1 LLM call.")
        form.addRow("Max pairs to generate:", self.max_pairs_spin)

        self.min_words_spin = QSpinBox()
        self.min_words_spin.setRange(10, 500)
        self.min_words_spin.setValue(40)
        self.min_words_spin.setToolTip(
            "Skip passages shorter than this. Tiny passages produce "
            "noisy paraphrase supervision.")
        form.addRow("Min passage words:", self.min_words_spin)

        self.max_words_spin = QSpinBox()
        self.max_words_spin.setRange(50, 2000)
        self.max_words_spin.setValue(400)
        self.max_words_spin.setToolTip(
            "Skip passages longer than this. Large passages blow the "
            "LLM context and produce lower-quality paraphrases.")
        form.addRow("Max passage words:", self.max_words_spin)

        # Bigram-overlap thresholds — exposed because the right values
        # depend on what kind of rephrase the user wants.
        self.max_overlap_spin = QDoubleSpinBox()
        self.max_overlap_spin.setRange(0.1, 1.0)
        self.max_overlap_spin.setSingleStep(0.05)
        self.max_overlap_spin.setDecimals(2)
        self.max_overlap_spin.setValue(0.70)
        self.max_overlap_spin.setToolTip(
            "Reject paraphrases whose bigram overlap with the "
            "original is above this threshold (verbatim echoes).")
        form.addRow("Max overlap (≤):", self.max_overlap_spin)

        self.min_overlap_spin = QDoubleSpinBox()
        self.min_overlap_spin.setRange(0.0, 0.5)
        self.min_overlap_spin.setSingleStep(0.05)
        self.min_overlap_spin.setDecimals(2)
        self.min_overlap_spin.setValue(0.15)
        self.min_overlap_spin.setToolTip(
            "Reject paraphrases whose bigram overlap is below this "
            "threshold (LLM hallucinated different content).")
        form.addRow("Min overlap (≥):", self.min_overlap_spin)

        self.use_filter_cb = QCheckBox(
            "Limit to corpora picked in the corpus filter dialog")
        self.use_filter_cb.setChecked(
            self._selected_collection_keys is not None)
        self.use_filter_cb.setEnabled(
            self._selected_collection_keys is not None)
        if self._selected_collection_keys is None:
            self.use_filter_cb.setToolTip(
                "(disabled — no corpus filter active in the main window)")
        form.addRow("", self.use_filter_cb)

        layout.addLayout(form)

        # Progress log
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(180)
        self.log_box.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background-color: #111827; color: #d1d5db;")
        layout.addWidget(self.log_box, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.run_btn = QPushButton("✏ Run synthesizer")
        self.run_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "padding: 6px 14px; border-radius: 6px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #d1d5db; }")
        self.run_btn.clicked.connect(lambda _=False: self._run())
        btn_row.addWidget(self.run_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _run(self) -> None:
        from PyQt6.QtWidgets import QApplication
        max_pairs = self.max_pairs_spin.value()
        min_words = self.min_words_spin.value()
        max_words = self.max_words_spin.value()
        max_overlap = self.max_overlap_spin.value()
        min_overlap = self.min_overlap_spin.value()
        coll_keys = (self._selected_collection_keys
                     if self.use_filter_cb.isChecked() else None)

        reply = QMessageBox.question(
            self, "Confirm",
            f"Generate up to {max_pairs} rephrase pairs by "
            f"paraphrasing corpus passages? Each = 1 LLM call.<br><br>"
            f"Quality gates: bigram overlap "
            f"{min_overlap:.2f}–{max_overlap:.2f}, length within ±30%.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Reuse the same LLM-callable builder the pacing dialog uses
        # — same routing, same fallbacks.
        llm_generate = _PacingPairsDialog._build_llm_callable()
        if llm_generate is None:
            QMessageBox.warning(
                self, "No LLM configured",
                "The rephrase synthesizer needs a configured LLM "
                "(cloud API key or a local model). Set one up in "
                "CreativeOS settings, then try again.")
            return

        self.run_btn.setEnabled(False)
        self.log_box.clear()
        self.log_box.appendPlainText(
            f"Synthesizing up to {max_pairs} rephrase pairs…")
        QApplication.processEvents()

        from src.ai.rephrase_synthesizer import synthesize_rephrase_pairs
        db = RephraseDatabase(self.db_path)
        try:
            result = synthesize_rephrase_pairs(
                db,
                llm_generate=llm_generate,
                source_collection_keys=coll_keys,
                max_pairs=max_pairs,
                min_passage_words=min_words,
                max_passage_words=max_words,
                max_overlap=max_overlap,
                min_overlap=min_overlap,
                on_log=lambda s: (
                    self.log_box.appendPlainText(s),
                    QApplication.processEvents()),
            )
        except Exception as e:
            self.log_box.appendPlainText(f"\n[error] {e}")
            self.run_btn.setEnabled(True)
            return
        self.run_btn.setEnabled(True)

        self.log_box.appendPlainText("")
        self.log_box.appendPlainText("=" * 50)
        self.log_box.appendPlainText(
            f"Done. Logged {result['n_logged']} rephrase pairs as "
            f"SOURCE_REPHRASE rows.")
        self.log_box.appendPlainText(
            f"  skipped — too short:       "
            f"{result['n_skipped_too_short']}")
        self.log_box.appendPlainText(
            f"  skipped — too long:        "
            f"{result['n_skipped_too_long']}")
        self.log_box.appendPlainText(
            f"  skipped — too similar:     "
            f"{result['n_skipped_too_similar']} (verbatim echoes)")
        self.log_box.appendPlainText(
            f"  skipped — too different:   "
            f"{result['n_skipped_too_different']} (probably hallucinated)")
        self.log_box.appendPlainText(
            f"  skipped — length mismatch: "
            f"{result['n_skipped_length']}")
        self.log_box.appendPlainText(
            f"  failed (LLM errors):       {result['n_failed']}")
