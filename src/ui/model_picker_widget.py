"""Reusable local-model picker — catalog, downloader, and UI widget.

The Writing Tool's settings dialog used to own all of this. We pulled
it out so the CreativeOS settings dialog (and any future tool) can
drop in the same picker without copy-pasting hundreds of lines.

Public surface:
  * ``LocalModelInfo`` — dataclass describing one downloadable model
  * ``MLX_MODELS`` / ``PYTORCH_MODELS`` — platform-specific catalogs
  * ``get_available_models()`` — picks the right catalog for the host
  * ``ModelDownloadWorker`` — QThread that calls ``snapshot_download``
  * ``ModelPickerWidget`` — self-contained QGroupBox with list, details,
    progress, and a ``model_selected(model_id)`` signal callers consume

The catalogs are MLX-first on Apple Silicon (pre-quantized 4-bit) and
fall back to PyTorch wheels everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QMessageBox,
    QDialog, QDialogButtonBox, QCheckBox, QWidget, QScrollArea,
)

from src.ai.mlx_utils import can_use_mlx


@dataclass
class LocalModelInfo:
    """Information about a local model available for download."""
    model_id: str
    display_name: str
    size_gb: float
    description: str
    ram_required: str
    best_for: str
    requires_trust_remote_code: bool = False


# MLX Models for Apple Silicon (M1/M2/M3/M4/M5)
MLX_MODELS: List[LocalModelInfo] = [
    # === Small (8GB RAM) — Gemma, Qwen, Phi ===
    LocalModelInfo(
        model_id="mlx-community/gemma-4-E2B-it-4bit",
        display_name="Gemma 4 E2B - MLX",
        size_gb=1.4,
        description="Smallest Gemma 4 — efficient mode, multimodal",
        ram_required="6GB+",
        best_for="Fastest Gemma 4, drafts and quick rephrasing",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="unsloth/gemma-4-E4B-it-UD-MLX-4bit",
        display_name="Gemma 4 E4B - MLX",
        size_gb=2.5,
        description="Google Gemma 4, multimodal, very fast",
        ram_required="8GB+",
        best_for="General writing, creative tasks, fast inference",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-4b-it-4bit",
        display_name="Gemma 3 (4B) - MLX",
        size_gb=2.0,
        description="Google's solid 4B model, great on MLX",
        ram_required="8GB+",
        best_for="Creative writing, dialogue",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-4B-4bit",
        display_name="Qwen 3 (4B) - MLX",
        size_gb=2.0,
        description="Latest Qwen, fast and capable",
        ram_required="8GB+",
        best_for="General writing, latest features",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/Phi-3-mini-4k-instruct-4bit",
        display_name="Phi-3 Mini (3.8B) - MLX",
        size_gb=2.0,
        description="Microsoft's efficient model",
        ram_required="8GB+",
        best_for="General writing, rephrasing, fast",
        requires_trust_remote_code=False,
    ),
    # === Medium (16GB RAM) ===
    LocalModelInfo(
        model_id="mlx-community/Qwen3-8B-4bit",
        display_name="Qwen 3 (8B) - MLX [Recommended]",
        size_gb=4.0,
        description="Excellent all-around model",
        ram_required="8GB+",
        best_for="All-around best choice for most tasks",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-12b-it-4bit",
        display_name="Gemma 3 (12B) - MLX",
        size_gb=6.0,
        description="Google's high-quality 12B model",
        ram_required="16GB+",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-14B-4bit",
        display_name="Qwen 3 (14B) - MLX",
        size_gb=7.0,
        description="High-quality, 128K context",
        ram_required="16GB+",
        best_for="Storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=False,
    ),
    # === Large (32GB RAM) ===
    LocalModelInfo(
        model_id="mlx-community/gemma-4-26b-a4b-it-4bit",
        display_name="Gemma 4 26B-A4B - MLX [MoE, Fast]",
        size_gb=14.0,
        description="Gemma 4 MoE — only 4B params active, fast for its size",
        ram_required="24GB+",
        best_for="High quality with fast inference",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-27b-it-4bit",
        display_name="Gemma 3 (27B) - MLX",
        size_gb=14.0,
        description="Google's top-tier Gemma 3",
        ram_required="32GB+",
        best_for="Maximum quality creative writing",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-30B-A3B-4bit",
        display_name="Qwen 3 (30B) - MLX",
        size_gb=15.0,
        description="Qwen MoE with exceptional quality",
        ram_required="32GB+",
        best_for="Highest quality, latest features",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-4-31b-it-4bit",
        display_name="Gemma 4 31B - MLX [Frontier]",
        size_gb=17.0,
        description="Gemma 4 31B — frontier quality, 256K context",
        ram_required="32GB+",
        best_for="Maximum quality, nuanced dialogue, worldbuilding",
        requires_trust_remote_code=False,
    ),
]


# PyTorch Models for Windows/Linux/Intel Macs
PYTORCH_MODELS: List[LocalModelInfo] = [
    LocalModelInfo(
        model_id="google/gemma-4-E2B-it",
        display_name="Gemma 4 E2B",
        size_gb=4.0,
        description="Smallest Gemma 4 — efficient mode, multimodal",
        ram_required="8GB+",
        best_for="Fast Gemma 4 inference on smaller machines",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-E4B-it",
        display_name="Gemma 4 E4B",
        size_gb=8.0,
        description="Google Gemma 4, multimodal, efficient",
        ram_required="8GB+",
        best_for="General writing, fast inference",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-4b-it",
        display_name="Gemma 3 (4B)",
        size_gb=8.0,
        description="Google's solid 4B model",
        ram_required="8GB+",
        best_for="Creative writing, dialogue",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-3B-Instruct",
        display_name="Qwen 2.5 (3B)",
        size_gb=6.0,
        description="Fast and capable",
        ram_required="6GB+",
        best_for="Instructions, rephrasing, multilingual",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="microsoft/Phi-4-mini-instruct",
        display_name="Phi-4 Mini (3.8B)",
        size_gb=7.6,
        description="Microsoft's efficient model",
        ram_required="8GB+",
        best_for="General writing, rephrasing",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="Qwen 2.5 (7B) [Recommended]",
        size_gb=14.0,
        description="Excellent all-around, 128K context",
        ram_required="16GB+",
        best_for="Long chapters, worldbuilding, all tasks",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-12b-it",
        display_name="Gemma 3 (12B)",
        size_gb=24.0,
        description="Google's high-quality 12B model",
        ram_required="24GB+",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-14B",
        display_name="Qwen 3 (14B)",
        size_gb=28.0,
        description="Latest Qwen 3, 128K context",
        ram_required="32GB+",
        best_for="Storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-26b-a4b-it",
        display_name="Gemma 4 26B-A4B (MoE)",
        size_gb=26.0,
        description="Gemma 4 MoE — 4B active, fast for its size",
        ram_required="24GB+",
        best_for="High quality with fast inference",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-27b-it",
        display_name="Gemma 3 (27B)",
        size_gb=54.0,
        description="Google's top-tier Gemma 3",
        ram_required="32GB+",
        best_for="Advanced creative writing, multilingual",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-30B-A3B",
        display_name="Qwen 3 (30B-A3B)",
        size_gb=60.0,
        description="Qwen MoE with exceptional quality",
        ram_required="32GB+",
        best_for="Highest quality, professional writing",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-31b-it",
        display_name="Gemma 4 31B",
        size_gb=62.0,
        description="Google Gemma 4 31B — frontier-quality, 256K context",
        ram_required="32GB+",
        best_for="Maximum quality writing, nuanced dialogue",
        requires_trust_remote_code=False,
    ),
]


def get_available_models() -> List[LocalModelInfo]:
    """Return the *running* catalog appropriate for this host.

    MLX models on Apple Silicon, PyTorch models everywhere else. This
    is the catalog the Local Models picker uses — large 4B+ instruct
    models tuned for inference. The Training Studio uses a separate
    catalog (``TRAINING_BASE_MODELS``) of smaller fine-tunable bases.
    """
    if can_use_mlx():
        return MLX_MODELS
    return PYTORCH_MODELS


# ── Training base models ─────────────────────────────────────
# PyTorch-format instruct bases the Training Studio fine-tunes against
# via HuggingFace Trainer + PEFT (LoRA). Same families as the running
# catalog — Gemma 2/3/4, Qwen 2.5/3, Llama 3.2, Phi-3/4 — but always
# in the original PyTorch repo so AutoModelForCausalLM can load them.
# (MLX-format ids in MLX_MODELS aren't usable here; they're inference-
# only.) The user picks which entries are visible via the
# BaseModelManagerDialog — anything they can't run is one click away.
TRAINING_BASE_MODELS: List[LocalModelInfo] = [
    # ── Tiny / fastest training loop ──
    LocalModelInfo(
        model_id="meta-llama/Llama-3.2-1B-Instruct",
        display_name="Llama 3.2 (1B Instruct)",
        size_gb=2.5,
        description="Smallest fine-tune-friendly Llama",
        ram_required="6GB+",
        best_for="Fastest training loop, prototyping",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-1.5B-Instruct",
        display_name="Qwen 2.5 (1.5B Instruct)",
        size_gb=3.0,
        description="Compact, multilingual, 32K context",
        ram_required="6GB+",
        best_for="Fast iteration, structured generation",
        requires_trust_remote_code=True,
    ),

    # ── Small (2-4B) ──
    LocalModelInfo(
        model_id="google/gemma-2-2b-it",
        display_name="Gemma 2 (2B Instruct)",
        size_gb=5.0,
        description="Small, fast, fine-tunes well with LoRA",
        ram_required="8GB+",
        best_for="Voice/style imitation, instruction tuning",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-3B-Instruct",
        display_name="Qwen 2.5 (3B Instruct)",
        size_gb=6.0,
        description="Capable mid-size base, good for voice training",
        ram_required="8GB+",
        best_for="Voice training, longer contexts",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-4B",
        display_name="Qwen 3 (4B Instruct)",
        size_gb=8.0,
        description="Latest Qwen, fast and capable",
        ram_required="12GB+",
        best_for="General writing, latest features",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="meta-llama/Llama-3.2-3B-Instruct",
        display_name="Llama 3.2 (3B Instruct)",
        size_gb=6.0,
        description="Solid mid-size Llama, popular for fine-tunes",
        ram_required="8GB+",
        best_for="Voice/style, balanced speed and quality",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="microsoft/Phi-3-mini-4k-instruct",
        display_name="Phi-3 Mini (3.8B Instruct)",
        size_gb=7.0,
        description="Microsoft's reasoning-focused small base",
        ram_required="8GB+",
        best_for="Q&A, structured tasks, plot generation",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="microsoft/Phi-4-mini-instruct",
        display_name="Phi-4 Mini (3.8B Instruct)",
        size_gb=7.6,
        description="Latest Phi mini, improved reasoning",
        ram_required="8GB+",
        best_for="Q&A, plot/outline tasks",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-4b-it",
        display_name="Gemma 3 (4B Instruct)",
        size_gb=8.0,
        description="Google's solid 4B base for fine-tuning",
        ram_required="12GB+",
        best_for="Higher-quality voice and creative training",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-E2B-it",
        display_name="Gemma 4 E2B (Instruct)",
        size_gb=4.0,
        description="Smallest Gemma 4 — efficient mode, multimodal",
        ram_required="8GB+",
        best_for="Fastest Gemma 4 fine-tunes, voice training",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-E4B-it",
        display_name="Gemma 4 E4B (Instruct)",
        size_gb=8.0,
        description="Google's efficient Gemma 4, multimodal",
        ram_required="12GB+",
        best_for="General writing, fast inference, latest Gemma",
        requires_trust_remote_code=False,
    ),

    # ── Medium (7-14B) — needs a beefy GPU or 32GB+ RAM ──
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="Qwen 2.5 (7B Instruct) [Recommended]",
        size_gb=14.0,
        description="Excellent all-around base, 128K context",
        ram_required="16GB+",
        best_for="Long chapters, worldbuilding, all tasks",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-8B",
        display_name="Qwen 3 (8B Instruct)",
        size_gb=16.0,
        description="Latest Qwen 3, strong all-rounder",
        ram_required="16GB+",
        best_for="High-quality voice training",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-12b-it",
        display_name="Gemma 3 (12B Instruct)",
        size_gb=24.0,
        description="Google's high-quality 12B base",
        ram_required="24GB+",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-14B",
        display_name="Qwen 3 (14B Instruct)",
        size_gb=28.0,
        description="Larger Qwen 3 for serious fine-tunes",
        ram_required="32GB+",
        best_for="Storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=True,
    ),

    # ── Large (26B+) — frontier quality, hefty RAM bill ──
    LocalModelInfo(
        model_id="google/gemma-4-26b-a4b-it",
        display_name="Gemma 4 26B-A4B (MoE)",
        size_gb=26.0,
        description="Gemma 4 MoE — 4B active params, fast for its size",
        ram_required="32GB+",
        best_for="High-quality fine-tunes with MoE efficiency",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="google/gemma-3-27b-it",
        display_name="Gemma 3 (27B Instruct)",
        size_gb=54.0,
        description="Google's top-tier Gemma 3",
        ram_required="64GB+",
        best_for="Advanced creative writing, multilingual",
        requires_trust_remote_code=False,
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-30B-A3B",
        display_name="Qwen 3 (30B-A3B MoE)",
        size_gb=60.0,
        description="Qwen MoE with exceptional quality",
        ram_required="64GB+",
        best_for="Highest quality, professional writing",
        requires_trust_remote_code=True,
    ),
    LocalModelInfo(
        model_id="google/gemma-4-31b-it",
        display_name="Gemma 4 31B (Frontier)",
        size_gb=62.0,
        description="Gemma 4 31B — frontier quality, 256K context",
        ram_required="64GB+",
        best_for="Maximum quality fine-tunes (workstation only)",
        requires_trust_remote_code=False,
    ),
]


def get_training_base_models() -> List[LocalModelInfo]:
    """Full training-base catalog (no exclusion filter applied)."""
    return list(TRAINING_BASE_MODELS)


def get_included_training_base_models() -> List[LocalModelInfo]:
    """Training catalog filtered by the user's exclusion list.

    Used by the Training Studio's base-model picker and the Model
    Builder Agent. Falls back to the full catalog when the config
    layer is unreachable — better to show too much than to silently
    empty the picker.
    """
    try:
        from src.config.creativeos_config import get_creativeos_config
        excluded = set(get_creativeos_config().excluded_base_models())
    except Exception:
        excluded = set()
    return [m for m in TRAINING_BASE_MODELS if m.model_id not in excluded]


def included_training_base_model_ids() -> List[str]:
    """Just the HF ids — handy for agents and recipe validators."""
    return [m.model_id for m in get_included_training_base_models()]


# ── Downloader thread ────────────────────────────────────────

class ModelDownloadWorker(QThread):
    """Background worker that fetches a HuggingFace model snapshot.

    Signals:
        progress(str, int) — status line + percentage (-1 = indeterminate)
        finished(bool, str) — success flag + final message
    """

    progress = pyqtSignal(str, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, model_id: str,
                 trust_remote_code: bool = False,
                 hf_token: Optional[str] = None):
        super().__init__()
        self.model_id = model_id
        self.trust_remote_code = trust_remote_code
        self.hf_token = hf_token
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        try:
            self.progress.emit(
                f"Initializing download for {self.model_id}…", -1)

            try:
                from huggingface_hub import snapshot_download
            except ImportError as e:
                import sys
                self.finished.emit(
                    False,
                    f"huggingface_hub not installed in this Python env.\n"
                    f"Python: {sys.executable}\n"
                    f"Install with:\n"
                    f"  {sys.executable} -m pip install huggingface_hub\n\n"
                    f"Error: {e}")
                return

            if self._cancelled:
                self.finished.emit(False, "Download cancelled")
                return

            self.progress.emit("Downloading model files…", 25)

            cache_dir = snapshot_download(
                repo_id=self.model_id,
                allow_patterns=["*.json", "*.safetensors", "*.bin",
                                "*.model", "*.txt", "*.py"],
                ignore_patterns=["*.gguf", "*.ggml", "*.h5", "*.ot",
                                 "*.msgpack"],
                token=self.hf_token if self.hf_token else None,
            )

            if self._cancelled:
                self.finished.emit(False, "Download cancelled")
                return

            self.progress.emit("Verifying model files…", 75)

            cache_path = Path(cache_dir)
            if not cache_path.exists():
                self.finished.emit(
                    False, "Download failed - cache directory not found")
                return

            has_model = any(cache_path.glob("*.safetensors")) or \
                        any(cache_path.glob("*.bin"))
            if not has_model:
                self.finished.emit(
                    False,
                    "Download incomplete - model weights not found.\n"
                    "The model may require authentication or may not be "
                    "available.")
                return

            self.progress.emit("Download complete!", 100)
            self.finished.emit(
                True,
                f"Successfully downloaded {self.model_id}\n\n"
                f"Location: {cache_dir}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"Download failed: {e}")


# ── Reusable picker widget ────────────────────────────────────

class ModelPickerWidget(QGroupBox):
    """Drop-in QGroupBox: catalog list + details + download button.

    Emits ``model_selected(model_id: str)`` whenever a list row's
    radio-style selection changes — caller decides what to do (e.g.
    write the id into a settings field). Emits
    ``model_downloaded(model_id: str)`` after a successful download
    so callers can refresh other pickers (per-task model combos, etc.).

    The widget owns no settings — it only surfaces choices and runs
    downloads. Persistence is the parent's responsibility.
    """

    model_selected = pyqtSignal(str)
    model_downloaded = pyqtSignal(str)

    def __init__(self, title: str = "Download & Manage Local Models",
                 parent=None):
        super().__init__(title, parent)
        self._download_worker: Optional[ModelDownloadWorker] = None
        self._init_ui()
        self._populate_model_list()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Pick a model from the catalog. Models are downloaded into "
            "your HuggingFace cache; ✓ marks ones you already have. "
            "Selecting a row only previews — click <b>Download Selected "
            "Model</b> to fetch it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        layout.addWidget(hint)

        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(160)
        self.model_list.setMaximumHeight(220)
        self.model_list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.model_list)

        self.details_label = QLabel("Select a model to see details…")
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet(
            "background: #f9fafb; border: 1px solid #e5e7eb; "
            "border-radius: 4px; padding: 6px 8px; font-size: 11px;")
        layout.addWidget(self.details_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setVisible(False)
        self.status_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected Model")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download_selected)
        btns.addWidget(self.download_btn)
        self.refresh_btn = QPushButton("Check Downloaded Models")
        self.refresh_btn.clicked.connect(self._refresh_downloaded)
        btns.addWidget(self.refresh_btn)
        btns.addStretch()
        layout.addLayout(btns)

        self.downloaded_label = QLabel("")
        self.downloaded_label.setWordWrap(True)
        self.downloaded_label.setVisible(False)
        self.downloaded_label.setStyleSheet(
            "font-size: 11px; padding: 6px 8px; "
            "background: #ecfdf5; border-radius: 4px; color: #065f46;")
        layout.addWidget(self.downloaded_label)

    # ── catalog wiring ──

    def _downloaded_ids(self) -> set:
        """Best-effort scan of the HF cache for downloaded model ids."""
        try:
            from huggingface_hub import scan_cache_dir
            return {repo.repo_id for repo in scan_cache_dir().repos}
        except Exception:
            return set()

    def _populate_model_list(self) -> None:
        self.model_list.clear()
        downloaded = self._downloaded_ids()
        for model in get_available_models():
            is_downloaded = model.model_id in downloaded
            prefix = "✓ " if is_downloaded else ""
            item = QListWidgetItem(
                f"{prefix}{model.display_name} — {model.size_gb}GB")
            item.setData(Qt.ItemDataRole.UserRole, model)
            if is_downloaded:
                item.setForeground(QColor("#059669"))
                item.setToolTip(f"✓ Downloaded: {model.model_id}")
            else:
                item.setToolTip(f"Not downloaded: {model.model_id}")
            self.model_list.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            self.details_label.setText("Select a model to see details…")
            self.download_btn.setEnabled(False)
            return
        item = self.model_list.item(row)
        model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)
        details = (
            f"<b>{model.display_name}</b><br>"
            f"<b>Model ID:</b> <code>{model.model_id}</code><br>"
            f"<b>Size:</b> ~{model.size_gb}GB download<br>"
            f"<b>RAM Required:</b> {model.ram_required}<br>"
            f"<b>Best for:</b> {model.best_for}<br>"
            f"<b>Description:</b> {model.description}")
        if model.requires_trust_remote_code:
            details += "<br><i>(Requires 'trust remote code' enabled)</i>"
        self.details_label.setText(details)
        self.download_btn.setEnabled(True)
        self.model_selected.emit(model.model_id)

    # ── download flow ──

    def _hf_token(self) -> str:
        """Pull the HF token via the credential manager (gated models)."""
        try:
            from src.config.credential_manager import get_credential_manager
            return get_credential_manager().get_huggingface_token() or ""
        except Exception:
            return ""

    def _download_selected(self) -> None:
        row = self.model_list.currentRow()
        if row < 0:
            return
        item = self.model_list.item(row)
        model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)

        reply = QMessageBox.question(
            self, "Download Model",
            f"Download {model.display_name}?\n\n"
            f"This will download approximately {model.size_gb}GB of data. "
            f"The model will be cached in your HuggingFace cache directory.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText("Starting download…")
        self.download_btn.setEnabled(False)

        self._download_worker = ModelDownloadWorker(
            model.model_id,
            model.requires_trust_remote_code,
            self._hf_token() or None,
        )
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.finished.connect(
            lambda ok, msg, mid=model.model_id:
            self._on_finished(ok, msg, mid))
        self._download_worker.start()

    def _on_progress(self, status: str, pct: int) -> None:
        self.status_label.setText(status)
        if pct < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)

    def _on_finished(self, ok: bool, msg: str, model_id: str) -> None:
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        self.download_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Download Complete", msg)
            self._populate_model_list()
            self._refresh_downloaded()
            self.model_downloaded.emit(model_id)
        else:
            QMessageBox.warning(self, "Download Failed", msg)
        self._download_worker = None

    def _refresh_downloaded(self) -> None:
        """Show a summary of cached models from the HF cache."""
        try:
            from huggingface_hub import scan_cache_dir
        except ImportError:
            self.downloaded_label.setText(
                "Install <code>huggingface_hub</code> to scan the cache.")
            self.downloaded_label.setVisible(True)
            return

        try:
            cache_info = scan_cache_dir()
        except Exception as e:
            self.downloaded_label.setText(f"Error scanning cache: {e}")
            self.downloaded_label.setVisible(True)
            return

        catalog = {m.model_id: m for m in get_available_models()}
        rows = []
        for repo in cache_info.repos:
            size_gb = repo.size_on_disk / (1024 ** 3)
            if size_gb < 0.1:
                continue
            label = catalog[repo.repo_id].display_name \
                if repo.repo_id in catalog else repo.repo_id
            rows.append(f"{label} ({size_gb:.1f}GB)")

        if rows:
            self.downloaded_label.setText(
                "<b>Downloaded models:</b><br>" + "<br>".join(rows[:12]))
        else:
            self.downloaded_label.setText("No models downloaded yet.")
        self.downloaded_label.setVisible(True)
        # Refresh checkmarks too
        self._populate_model_list()

    # ── public helpers ──

    def selected_model_id(self) -> str:
        """Return the model id currently highlighted, or empty string."""
        row = self.model_list.currentRow()
        if row < 0:
            return ""
        item = self.model_list.item(row)
        model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)
        return model.model_id

    def select_model_by_id(self, model_id: str) -> bool:
        """Highlight the row whose model id matches. Returns True on hit."""
        if not model_id:
            return False
        for i in range(self.model_list.count()):
            item = self.model_list.item(i)
            m: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)
            if m.model_id == model_id:
                self.model_list.setCurrentRow(i)
                return True
        return False


# ── Manage built-in base models ────────────────────────────────

class BaseModelManagerDialog(QDialog):
    """Toggle which built-in *training* base models are available.

    Sources from ``TRAINING_BASE_MODELS`` (not the running catalog) —
    these are the small, fine-tunable bases the Training Studio offers.
    Persists via CreativeOS ``excluded_base_models``; the Model Builder
    Agent reads the same list, so anything hidden here won't be
    recommended either.

    Emits ``changed()`` when the user saves so callers can refresh
    dependent pickers.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Built-in Training Models")
        self.setMinimumSize(560, 520)

        try:
            from src.config.creativeos_config import get_creativeos_config
            self._cfg = get_creativeos_config()
            excluded = set(self._cfg.excluded_base_models())
        except Exception:
            self._cfg = None
            excluded = set()

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tick the built-in base models you want available in the "
            "Model Training Studio. Unchecked models disappear from the "
            "Step 2 picker and from the Model Builder Agent's "
            "recommendations. You can always type a custom HuggingFace "
            "id directly in Step 2 to use something that's not on this "
            "list.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        layout.addWidget(intro)

        # Scroll area so the full catalog fits on small screens.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(4)

        self._checkboxes: List[QCheckBox] = []
        for model in get_training_base_models():
            cb = QCheckBox(
                f"{model.display_name}  —  {model.size_gb}GB  "
                f"({model.ram_required})")
            cb.setChecked(model.model_id not in excluded)
            cb.setToolTip(
                f"{model.model_id}\n"
                f"Best for: {model.best_for}\n"
                f"{model.description}")
            cb.setProperty("model_id", model.model_id)
            self._checkboxes.append(cb)
            body_layout.addWidget(cb)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        # Quick-action buttons
        quick_row = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(self._select_all)
        quick_row.addWidget(all_btn)
        none_btn = QPushButton("Deselect all")
        none_btn.clicked.connect(self._select_none)
        quick_row.addWidget(none_btn)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept_and_save)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _select_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _select_none(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _accept_and_save(self) -> None:
        if not any(cb.isChecked() for cb in self._checkboxes):
            QMessageBox.warning(
                self, "Nothing selected",
                "Pick at least one built-in model — otherwise the "
                "Training Studio's picker would be empty.")
            return
        excluded = [cb.property("model_id")
                    for cb in self._checkboxes if not cb.isChecked()]
        if self._cfg is not None:
            self._cfg.set_excluded_base_models(excluded)
        self.changed.emit()
        self.accept()
