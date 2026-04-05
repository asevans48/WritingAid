"""Settings dialog for API keys and preferences."""

from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QLabel,
    QCheckBox, QSlider, QSpinBox, QDoubleSpinBox, QTabWidget,
    QWidget, QScrollArea, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QFrame, QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from src.config.credential_manager import get_credential_manager
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
    # === Lightweight Models (4-8GB RAM) ===
    LocalModelInfo(
        model_id="mlx-community/Phi-3-mini-4k-instruct-4bit",
        display_name="Phi-3 Mini (3.8B) - MLX",
        size_gb=2.0,
        description="Microsoft's efficient model optimized for Apple Silicon",
        ram_required="8GB+",
        best_for="General writing, rephrasing, fast inference",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen2.5-3B-Instruct-4bit",
        display_name="Qwen 2.5 (3B) - MLX",
        size_gb=1.6,
        description="Alibaba's very fast 3B model",
        ram_required="6GB+",
        best_for="Quick rephrasing, instructions, very fast",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-4B-4bit",
        display_name="Qwen 3 (4B) - MLX [Latest]",
        size_gb=2.0,
        description="Latest Qwen model (January 2026)",
        ram_required="8GB+",
        best_for="General writing, latest features",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-4b-it-4bit",
        display_name="Gemma 3 (4B) - MLX",
        size_gb=2.0,
        description="Google's multimodal model, works great on MLX",
        ram_required="8GB+",
        best_for="Creative writing, dialogue",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="roneneldan/TinyStories-33M",
        display_name="📖 TinyStories (33M) - MLX [Ultra Fast]",
        size_gb=0.07,
        description="Tiny story-focused model, runs instantly on Apple Silicon",
        ram_required="1GB+",
        best_for="Quick story drafts, testing, ultra-fast generation",
        requires_trust_remote_code=False
    ),

    # === Reasoning Models for Planning & Critique ===
    LocalModelInfo(
        model_id="mlx-community/DeepSeek-R1-Distill-Qwen-7B-4bit",
        display_name="🧠 DeepSeek-R1 Qwen 7B - MLX [Reasoning]",
        size_gb=4.0,
        description="Chain-of-thought reasoning for plot analysis and planning",
        ram_required="12GB+",
        best_for="Chapter planning, outline critique, continuity checking",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Phi-4-reasoning-plus-4bit",
        display_name="🧠 Phi-4 Reasoning Plus - MLX [Recommended]",
        size_gb=7.0,
        description="Microsoft's 14B reasoning model for story analysis (128K context)",
        ram_required="16GB+",
        best_for="Story planning, plot analysis, character consistency, critique",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit",
        display_name="🧠 DeepSeek-R1 Qwen 14B - MLX [High Quality]",
        size_gb=7.0,
        description="Advanced reasoning for complex plot and multi-character tracking",
        ram_required="16GB+",
        best_for="Complex plot analysis, logic verification, full critique",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Ministral-3-3B-Reasoning-2512-bf16",
        display_name="🧠 Ministral 3 3B Reasoning - MLX [Lightweight]",
        size_gb=6.0,
        description="Mistral's compact reasoning model with 128K context",
        ram_required="8GB+",
        best_for="Quick plot checks, outline validation, fast iterations",
        requires_trust_remote_code=False
    ),

    # === Medium Models (16GB RAM) ===
    LocalModelInfo(
        model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
        display_name="Qwen 2.5 (7B) - MLX [Recommended]",
        size_gb=4.0,
        description="Excellent balance of speed and quality",
        ram_required="8GB+",
        best_for="All-around best choice for most tasks",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-8B-4bit",
        display_name="Qwen 3 (8B) - MLX [Latest]",
        size_gb=4.0,
        description="Latest Qwen 8B model (January 2026)",
        ram_required="8GB+",
        best_for="General writing, latest features",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Mistral-7B-Instruct-v0.3-4bit",
        display_name="Mistral 7B v0.3 - MLX",
        size_gb=4.0,
        description="Mistral AI's powerful 7B model",
        ram_required="8GB+",
        best_for="High-quality writing, reasoning",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-12b-it-4bit",
        display_name="Gemma 3 (12B) - MLX",
        size_gb=6.0,
        description="Google's high-quality 12B model",
        ram_required="16GB+",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False
    ),
    # === Storytelling-Specialized Models (Latest Mistral Models) ===
    # Note: Using verified mlx-community models optimized for Apple Silicon
    LocalModelInfo(
        model_id="mlx-community/Ministral-3-8B-Instruct-2512-4bit",
        display_name="⭐ Ministral 3 8B - MLX [Latest, Dec 2024]",
        size_gb=5.6,
        description="Latest Mistral model with 256K context, excellent for storytelling",
        ram_required="8GB+",
        best_for="Creative writing, storytelling, dialogue, long narratives",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Mistral-Nemo-Instruct-2407-4bit",
        display_name="⭐ Mistral Nemo 12B - MLX [High Quality]",
        size_gb=6.89,
        description="Mistral-NVIDIA collaboration, 128K context for long-form writing",
        ram_required="12GB+",
        best_for="High-quality creative writing, complex narratives",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        display_name="📝 Llama 3.1 8B - MLX (128K context)",
        size_gb=5.0,
        description="Meta's Llama 3.1 with 128K context window, excellent for long-form",
        ram_required="12GB+",
        best_for="Long chapters, extended narratives, worldbuilding documents",
        requires_trust_remote_code=False
    ),

    # === Gemma 4 Models ===
    LocalModelInfo(
        model_id="mlx-community/gemma-4-E2B-it-4bit",
        display_name="Gemma 4 E2B - MLX [Tiny, Fast]",
        size_gb=1.5,
        description="Google Gemma 4 ultra-efficient model for edge/mobile",
        ram_required="6GB+",
        best_for="Quick rephrasing, fast drafts, low memory",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-4-E4B-it-4bit",
        display_name="Gemma 4 E4B - MLX [Efficient]",
        size_gb=2.5,
        description="Google Gemma 4 efficient model, multimodal capable",
        ram_required="8GB+",
        best_for="General writing, creative tasks, fast inference",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-4-12b-it-4bit",
        display_name="Gemma 4 (12B) - MLX",
        size_gb=6.0,
        description="Google Gemma 4 12B model for high-quality writing",
        ram_required="16GB+",
        best_for="Creative writing, complex tasks, dialogue",
        requires_trust_remote_code=False
    ),

    # === High-Performance Models (32GB+ RAM) ===
    LocalModelInfo(
        model_id="mlx-community/Qwen2.5-14B-Instruct-4bit",
        display_name="Qwen 2.5 (14B) - MLX",
        size_gb=7.0,
        description="High-quality 14B model with excellent reasoning",
        ram_required="16GB+",
        best_for="Complex writing, long context (128K)",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-14B-4bit",
        display_name="📝 Qwen 3 (14B) - MLX [Latest, High Quality]",
        size_gb=7.0,
        description="Latest Qwen 3 with exceptional creative writing, 128K context",
        ram_required="16GB+",
        best_for="High-quality storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-2-27b-it-4bit",
        display_name="Gemma 2 (27B) - MLX [4-bit]",
        size_gb=14.0,
        description="Google's Gemma 2 27B quantized to 4-bit for Apple Silicon — replaces MPS loading",
        ram_required="36GB+",
        best_for="High-quality creative writing, long context",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-3-27b-it-4bit",
        display_name="Gemma 3 (27B) - MLX [4-bit]",
        size_gb=14.0,
        description="Google's top-tier Gemma 3 model for Apple Silicon",
        ram_required="36GB+",
        best_for="Maximum quality creative writing",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen3-30B-A3B-4bit",
        display_name="Qwen 3 (30B) - MLX [Latest]",
        size_gb=15.0,
        description="Latest Qwen model with exceptional quality",
        ram_required="32GB+",
        best_for="Highest quality, latest features",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Qwen2.5-32B-Instruct-4bit",
        display_name="Qwen 2.5 (32B) - MLX",
        size_gb=17.0,
        description="Top-tier model with exceptional capabilities",
        ram_required="32GB+",
        best_for="Maximum quality across all tasks",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/Mistral-Small-Instruct-2409-4bit",
        display_name="Mistral Small (22B) - MLX",
        size_gb=12.0,
        description="Mistral's high-quality 22B model",
        ram_required="32GB+",
        best_for="Professional writing, complex reasoning",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mlx-community/gemma-4-27b-it-4bit",
        display_name="Gemma 4 (27B) - MLX [4-bit]",
        size_gb=14.0,
        description="Google's Gemma 4 27B, frontier-quality creative writing",
        ram_required="32GB+",
        best_for="Maximum quality writing, nuanced dialogue, worldbuilding",
        requires_trust_remote_code=False
    ),
]

# PyTorch Models for Windows/Linux/Intel Macs
PYTORCH_MODELS: List[LocalModelInfo] = [
    # === Lightweight Models (4-6GB RAM) ===
    LocalModelInfo(
        model_id="microsoft/Phi-4-mini-instruct",
        display_name="Phi-4 Mini (3.8B)",
        size_gb=7.6,
        description="Microsoft's latest small model with excellent reasoning",
        ram_required="8GB+",
        best_for="General writing, rephrasing, creative tasks",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="microsoft/Phi-3.5-mini-instruct",
        display_name="Phi-3.5 Mini (3.8B)",
        size_gb=7.6,
        description="Improved Phi-3 with better multilingual support",
        ram_required="8GB+",
        best_for="Writing, translation, general tasks",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="google/gemma-3-4b-it",
        display_name="Gemma 3 (4B) ⚠️ Not Mac Compatible",
        size_gb=8.0,
        description="Google's latest efficient model - WARNING: Known to crash on macOS/Apple Silicon due to stack overflow. Use Qwen or Phi instead.",
        ram_required="8GB+",
        best_for="Creative writing, instructions, dialogue (Linux/Windows only)",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-3B-Instruct",
        display_name="Qwen 2.5 (3B)",
        size_gb=6.0,
        description="Alibaba's efficient instruction-following model",
        ram_required="6GB+",
        best_for="Instructions, rephrasing, multilingual",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        display_name="TinyLlama (1.1B)",
        size_gb=2.2,
        description="Very fast and lightweight chat model",
        ram_required="4GB+",
        best_for="Quick suggestions, low-resource systems",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="roneneldan/TinyStories-33M",
        display_name="📖 TinyStories (33M) [Ultra Fast]",
        size_gb=0.07,
        description="Tiny model trained specifically on story generation, runs instantly on CPU",
        ram_required="1GB+",
        best_for="Quick story drafts, testing, CPU-only systems",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="roneneldan/TinyStories-8M",
        display_name="📖 TinyStories (8M) [Fastest]",
        size_gb=0.02,
        description="Ultra-lightweight story model, instant generation on any device",
        ram_required="512MB+",
        best_for="Rapid prototyping, story outlines, minimal resources",
        requires_trust_remote_code=False
    ),

    # === Reasoning Models for Planning & Critique ===
    LocalModelInfo(
        model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        display_name="🧠 DeepSeek-R1 Qwen 7B [Reasoning, Fits 16GB]",
        size_gb=14.0,
        description="Chain-of-thought reasoning for plot analysis and planning",
        ram_required="16GB+",
        best_for="Chapter planning, outline critique, continuity checking",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Ministral-3-8B-Reasoning-2512",
        display_name="🧠 Ministral 3 8B Reasoning [Balanced]",
        size_gb=16.0,
        description="Mistral's reasoning model with 128K context, vision-capable",
        ram_required="16GB+",
        best_for="Plot structure, character arcs, scene analysis",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-4B-Thinking-2507",
        display_name="🧠 Qwen3 4B Thinking [Efficient, 262K context]",
        size_gb=8.0,
        description="Latest Qwen3 thinking model with massive 262K context",
        ram_required="12GB+",
        best_for="Long narrative analysis, multi-chapter tracking, continuity",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="microsoft/Phi-4-reasoning-plus",
        display_name="🧠 Phi-4 Reasoning Plus [Recommended]",
        size_gb=28.0,
        description="Microsoft's 14B reasoning model with 128K context, enhanced RL",
        ram_required="32GB+",
        best_for="Story planning, plot analysis, character consistency, critique",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        display_name="🧠 DeepSeek-R1 Qwen 14B [High Quality]",
        size_gb=28.0,
        description="Advanced reasoning for complex plot and multi-character tracking",
        ram_required="32GB+",
        best_for="Complex plot analysis, logic verification, full critique",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="Qwen/QwQ-32B",
        display_name="🧠 QwQ 32B [High Performance]",
        size_gb=64.0,
        description="Qwen's powerful 32B reasoning model with 131K context",
        ram_required="64GB+",
        best_for="Deep plot analysis, complex worldbuilding, full manuscript",
        requires_trust_remote_code=False
    ),

    # === Medium Models (8-16GB RAM) ===
    LocalModelInfo(
        model_id="meta-llama/Llama-3.2-3B-Instruct",
        display_name="Llama 3.2 (3B)",
        size_gb=6.0,
        description="Meta's latest small Llama with strong performance",
        ram_required="8GB+",
        best_for="General writing, chat, creative tasks",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="meta-llama/Llama-3.1-8B-Instruct",
        display_name="Llama 3.1 (8B)",
        size_gb=16.0,
        description="Meta's powerful 8B model with excellent quality",
        ram_required="16GB+",
        best_for="High-quality writing, complex tasks",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        display_name="Mistral 7B v0.3",
        size_gb=14.0,
        description="Latest Mistral 7B with improved capabilities",
        ram_required="16GB+",
        best_for="High-quality writing, complex reasoning",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Ministral-8B-Instruct-2410",
        display_name="Ministral 8B (Oct 2024)",
        size_gb=16.0,
        description="Mistral's efficient 8B model optimized for edge",
        ram_required="16GB+",
        best_for="Quality writing with reasonable resources",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="google/gemma-3-12b-it",
        display_name="Gemma 3 (12B) ⚠️ Not Mac Compatible",
        size_gb=24.0,
        description="Google's high-quality 12B model - WARNING: Known to crash on macOS/Apple Silicon due to stack overflow. Use Qwen 2.5-14B instead.",
        ram_required="24GB+",
        best_for="Best quality creative writing, complex tasks (Linux/Windows only)",
        requires_trust_remote_code=False
    ),

    # === Specialized/Community Models ===
    LocalModelInfo(
        model_id="ToastyPigeon/Gemma-3-Starshine-12B",
        display_name="Gemma 3 Starshine (12B) ⚠️ Not Mac Compatible",
        size_gb=24.0,
        description="Story-focused Gemma 3 merge - WARNING: Known to crash on macOS/Apple Silicon due to stack overflow. Use Qwen or Mistral Nemo instead.",
        ram_required="24GB+",
        best_for="Creative fiction, storytelling (Linux/Windows only)",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="ibm-research/Granite-3.2-3B-Instruct",
        display_name="Granite 3.2 (3B)",
        size_gb=6.0,
        description="IBM's efficient model optimized for enterprise tasks",
        ram_required="6GB+",
        best_for="Writing, summarization, structured output",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="01-ai/Yi-1.5-6B-Chat",
        display_name="Yi 1.5 (6B)",
        size_gb=12.0,
        description="Strong bilingual model (English/Chinese)",
        ram_required="12GB+",
        best_for="Multilingual writing, dialogue",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="arcee-ai/Arcee-Spark",
        display_name="Arcee Spark (7B)",
        size_gb=14.0,
        description="Optimized for creative and conversational tasks",
        ram_required="16GB+",
        best_for="Creative writing, storytelling",
        requires_trust_remote_code=False
    ),

    # === Storytelling-Specialized Models ===
    # Note: These are verified HuggingFace models optimized for creative writing
    LocalModelInfo(
        model_id="NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
        display_name="⭐ Nous Hermes 2 Mixtral (47B)",
        size_gb=90.0,
        description="Excellent creative writing model from Nous Research, DPO fine-tuned",
        ram_required="64GB+ (or use with CPU offloading)",
        best_for="Story writing, character dialogue, creative fiction",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Ministral-3-8B-Instruct-2512",
        display_name="⭐ Ministral 3 8B [Latest, Dec 2024]",
        size_gb=16.0,
        description="Latest Mistral model with 256K context, excellent for storytelling",
        ram_required="16GB+",
        best_for="Creative writing, storytelling, dialogue, long narratives",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-7B-Instruct",
        display_name="📝 Qwen 2.5 7B (128K context)",
        size_gb=14.0,
        description="Excellent for long-form writing with massive 128K context window",
        ram_required="16GB+",
        best_for="Long chapters, extended narratives, worldbuilding documents",
        requires_trust_remote_code=True
    ),

    # === High-Performance Models (32GB RAM, optimized for M5 Mac) ===
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-14B-Instruct",
        display_name="Qwen 2.5 (14B)",
        size_gb=28.0,
        description="Alibaba's powerful 14B model with excellent reasoning and coding",
        ram_required="32GB+",
        best_for="High-quality writing, complex reasoning, long context (128K)",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-14B-Instruct",
        display_name="📝 Qwen 3 (14B) [Latest, High Quality]",
        size_gb=28.0,
        description="Latest Qwen 3 with exceptional creative writing, 128K context",
        ram_required="32GB+",
        best_for="High-quality storytelling, long chapters, worldbuilding",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-32B-Instruct",
        display_name="Qwen 2.5 (32B)",
        size_gb=64.0,
        description="Top-tier Qwen model with exceptional capabilities across all tasks",
        ram_required="32GB+",
        best_for="Professional writing, complex analysis, multilingual (29 languages)",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen3-30B-A3B",
        display_name="Qwen 3 (30B-A3B) [Latest]",
        size_gb=60.0,
        description="Latest Qwen 3 model with exceptional reasoning and quality",
        ram_required="64GB+ (32GB with 4-bit quantization)",
        best_for="Highest quality critique, complex analysis, professional writing",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="mistralai/Mistral-Nemo-Instruct-2407",
        display_name="⭐ Mistral Nemo 12B [High Quality]",
        size_gb=24.0,
        description="Mistral-NVIDIA collaboration, 128K context for long-form writing",
        ram_required="24GB+",
        best_for="High-quality creative writing, complex narratives, long chapters",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="Qwen/Qwen2.5-Coder-14B-Instruct",
        display_name="Qwen 2.5 Coder (14B)",
        size_gb=28.0,
        description="Specialized coding variant with excellent technical writing",
        ram_required="32GB+",
        best_for="Technical documentation, code explanations, structured output",
        requires_trust_remote_code=True
    ),
    LocalModelInfo(
        model_id="google/gemma-2-27b-it",
        display_name="Gemma 2 (27B)",
        size_gb=54.0,
        description="Google's powerful 27B model trained on 13T tokens",
        ram_required="32GB+",
        best_for="High-quality creative writing, summarization, reasoning",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="google/gemma-3-27b-it",
        display_name="Gemma 3 (27B) ⚠️ Not Mac Compatible",
        size_gb=54.0,
        description="Latest Gemma with multimodal support - WARNING: Known to crash on macOS/Apple Silicon due to stack overflow. Use Qwen 2.5-32B or Mistral Small instead.",
        ram_required="32GB+",
        best_for="Advanced creative writing, multilingual (Linux/Windows only)",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Mistral-Small-Instruct-2409",
        display_name="Mistral Small (22B)",
        size_gb=44.0,
        description="Mistral's efficient 22B model with strong performance",
        ram_required="32GB+",
        best_for="Balanced writing tasks, efficient reasoning",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Codestral-22B-v0.1",
        display_name="Codestral (22B)",
        size_gb=44.0,
        description="Mistral's specialized code model with strong technical writing",
        ram_required="32GB+",
        best_for="Code generation, technical documentation, structured content",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        display_name="Mistral Small 3 (24B)",
        size_gb=48.0,
        description="Latest Mistral Small 3, rivals Llama 3.3 70B in performance",
        ram_required="32GB+",
        best_for="High-quality writing, reasoning, best performance for size",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="TheBloke/WizardLM-Uncensored-SuperCOT-StoryTelling-30B-GPTQ",
        display_name="WizardLM Storytelling (30B)",
        size_gb=20.0,
        description="GPTQ quantized model specialized for creative storytelling",
        ram_required="32GB+",
        best_for="Fiction writing, creative storytelling, narrative prose",
        requires_trust_remote_code=False
    ),
    # === Gemma 4 Models ===
    LocalModelInfo(
        model_id="google/gemma-4-E4B-it",
        display_name="Gemma 4 E4B",
        size_gb=8.0,
        description="Google Gemma 4 efficient model, multimodal capable",
        ram_required="8GB+",
        best_for="General writing, fast inference",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="google/gemma-4-12b-it",
        display_name="Gemma 4 (12B)",
        size_gb=24.0,
        description="Google Gemma 4 12B for high-quality writing",
        ram_required="16GB+",
        best_for="Creative writing, complex tasks",
        requires_trust_remote_code=False
    ),
    LocalModelInfo(
        model_id="google/gemma-4-27b-it",
        display_name="Gemma 4 (27B)",
        size_gb=54.0,
        description="Google's Gemma 4 27B, frontier-quality output",
        ram_required="32GB+",
        best_for="Maximum quality writing, nuanced dialogue",
        requires_trust_remote_code=False
    ),
]


def get_available_models() -> List[LocalModelInfo]:
    """Get the appropriate model list based on platform.

    Returns MLX models on Apple Silicon, PyTorch models elsewhere.
    """
    if can_use_mlx():
        return MLX_MODELS
    else:
        return PYTORCH_MODELS


# For backwards compatibility
AVAILABLE_MODELS = get_available_models()


class APITestWorker(QThread):
    """Background worker for testing API connections."""

    result = pyqtSignal(str, bool, str)  # provider, success, message
    finished = pyqtSignal()

    def __init__(self, providers: dict):
        """Initialize with providers to test.

        Args:
            providers: Dict of {provider_name: (api_key, model)}
        """
        super().__init__()
        self.providers = providers

    def run(self):
        """Test each provider's API connection."""
        for provider, (api_key, model) in self.providers.items():
            if not api_key:
                self.result.emit(provider, False, "No API key provided")
                continue

            try:
                if provider == "claude":
                    success, msg = self._test_claude(api_key, model)
                elif provider == "openai":
                    success, msg = self._test_openai(api_key, model)
                elif provider == "gemini":
                    success, msg = self._test_gemini(api_key, model)
                elif provider == "huggingface":
                    success, msg = self._test_huggingface(api_key)
                else:
                    success, msg = False, "Unknown provider"

                self.result.emit(provider, success, msg)
            except Exception as e:
                self.result.emit(provider, False, str(e))

        self.finished.emit()

    def _test_claude(self, api_key: str, model: str) -> tuple:
        """Test Claude/Anthropic API connection."""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)

            # Make a minimal API call
            response = client.messages.create(
                model=model or "claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )

            return True, f"Connected! Model: {model or 'claude-3-5-sonnet-20241022'}"

        except anthropic.AuthenticationError:
            return False, "Invalid API key"
        except anthropic.RateLimitError:
            return True, "Connected (rate limited, but key is valid)"
        except anthropic.APIError as e:
            return False, f"API error: {e}"
        except ImportError:
            return False, "anthropic package not installed"
        except Exception as e:
            return False, f"Error: {str(e)[:100]}"

    def _test_openai(self, api_key: str, model: str) -> tuple:
        """Test OpenAI API connection."""
        try:
            import openai

            client = openai.OpenAI(api_key=api_key)

            # Make a minimal API call
            response = client.chat.completions.create(
                model=model or "gpt-4-turbo-preview",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )

            return True, f"Connected! Model: {model or 'gpt-4-turbo-preview'}"

        except openai.AuthenticationError:
            return False, "Invalid API key"
        except openai.RateLimitError:
            return True, "Connected (rate limited, but key is valid)"
        except openai.APIError as e:
            return False, f"API error: {e}"
        except ImportError:
            return False, "openai package not installed"
        except Exception as e:
            return False, f"Error: {str(e)[:100]}"

    def _test_gemini(self, api_key: str, model: str) -> tuple:
        """Test Google Gemini API connection."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)

            # Make a minimal API call
            gen_model = genai.GenerativeModel(model or "gemini-pro")
            response = gen_model.generate_content(
                "Hi",
                generation_config={"max_output_tokens": 10}
            )

            return True, f"Connected! Model: {model or 'gemini-pro'}"

        except Exception as e:
            error_str = str(e).lower()
            if "api key" in error_str or "invalid" in error_str or "unauthorized" in error_str:
                return False, "Invalid API key"
            elif "quota" in error_str or "rate" in error_str:
                return True, "Connected (rate limited, but key is valid)"
            else:
                return False, f"Error: {str(e)[:100]}"

    def _test_huggingface(self, token: str) -> tuple:
        """Test Hugging Face token validity."""
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=token)
            # Try to get user info
            user_info = api.whoami()

            username = user_info.get("name", "Unknown")
            return True, f"Connected as: {username}"

        except Exception as e:
            error_str = str(e).lower()
            if "401" in error_str or "invalid" in error_str or "unauthorized" in error_str:
                return False, "Invalid token"
            else:
                return False, f"Error: {str(e)[:100]}"


class ModelDownloadWorker(QThread):
    """Background worker for downloading models from Hugging Face."""

    progress = pyqtSignal(str, int)  # status message, percentage (0-100, -1 for indeterminate)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, model_id: str, trust_remote_code: bool = False, hf_token: str = None):
        super().__init__()
        self.model_id = model_id
        self.trust_remote_code = trust_remote_code
        self.hf_token = hf_token
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the download."""
        self._cancelled = True

    def run(self):
        """Download the model."""
        try:
            self.progress.emit(f"Initializing download for {self.model_id}...", -1)

            # Import huggingface_hub
            try:
                from huggingface_hub import snapshot_download
            except ImportError as e:
                import sys
                import traceback

                # Log full error to console
                print("\n" + "="*70)
                print("ERROR: Failed to import huggingface_hub")
                print("="*70)
                print(f"Python executable: {sys.executable}")
                print(f"Python version: {sys.version}")
                print(f"sys.prefix: {sys.prefix}")
                print(f"sys.base_prefix: {sys.base_prefix}")
                print(f"In venv: {sys.prefix != sys.base_prefix}")
                print(f"\nImportError: {e}")
                print(f"\nFull traceback:")
                traceback.print_exc()
                print("="*70 + "\n")

                # User-friendly error message
                error_msg = (
                    f"huggingface_hub not installed in current Python environment.\n\n"
                    f"Python: {sys.executable}\n"
                    f"Version: {sys.version.split()[0]}\n"
                    f"In venv: {sys.prefix != sys.base_prefix}\n\n"
                    f"This usually means you're not running from the virtual environment.\n\n"
                    f"Solution:\n"
                    f"1. Close the app completely\n"
                    f"2. Run: ./run.sh\n\n"
                    f"OR install in current environment:\n"
                    f"{sys.executable} -m pip install huggingface_hub\n\n"
                    f"Error details: {e}"
                )
                self.finished.emit(False, error_msg)
                return

            if self._cancelled:
                self.finished.emit(False, "Download cancelled")
                return

            self.progress.emit(f"Downloading model files...", 25)

            # Download the model (this caches it locally)
            # Use token if available for gated models
            cache_dir = snapshot_download(
                repo_id=self.model_id,
                allow_patterns=["*.json", "*.safetensors", "*.bin", "*.model", "*.txt", "*.py"],
                ignore_patterns=["*.gguf", "*.ggml", "*.h5", "*.ot", "*.msgpack"],
                token=self.hf_token if self.hf_token else None,
            )

            if self._cancelled:
                self.finished.emit(False, "Download cancelled")
                return

            self.progress.emit("Verifying model files...", 75)

            # Verify the download by checking key files exist
            cache_path = Path(cache_dir)
            if not cache_path.exists():
                self.finished.emit(False, "Download failed - cache directory not found")
                return

            # Check for model files
            has_model = any(
                cache_path.glob("*.safetensors")
            ) or any(
                cache_path.glob("*.bin")
            )

            has_config = (cache_path / "config.json").exists()

            if not has_model:
                self.finished.emit(False,
                    "Download incomplete - model weights not found.\n"
                    "The model may require authentication or may not be available."
                )
                return

            self.progress.emit("Download complete!", 100)
            self.finished.emit(True, f"Successfully downloaded {self.model_id}\n\nLocation: {cache_dir}")

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg:
                error_msg = (
                    f"Access denied for {self.model_id}.\n\n"
                    "This model may require:\n"
                    "1. A Hugging Face account\n"
                    "2. Accepting the model's license\n"
                    "3. Setting HF_TOKEN environment variable\n\n"
                    f"Original error: {e}"
                )
            self.finished.emit(False, f"Download failed:\n\n{error_msg}")


class VibeVoiceInstallWorker(QThread):
    """Background worker for installing VibeVoice from GitHub."""

    progress = pyqtSignal(str, int)  # status message, percentage (0-100, -1 for indeterminate)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, install_path: str = None):
        super().__init__()
        self.install_path = install_path or str(Path.home() / "VibeVoice")
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the installation."""
        self._cancelled = True

    def run(self):
        """Clone and install VibeVoice."""
        import subprocess
        import sys

        try:
            install_dir = Path(self.install_path)

            # Check if already exists
            if install_dir.exists() and (install_dir / "vibevoice").exists():
                self.finished.emit(True, f"VibeVoice already installed at:\n{self.install_path}")
                return

            self.progress.emit("Cloning VibeVoice repository...", 10)

            if self._cancelled:
                self.finished.emit(False, "Installation cancelled")
                return

            # Clone the repository
            result = subprocess.run(
                ["git", "clone", "https://github.com/vibevoice-community/VibeVoice.git", str(install_dir)],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for clone
            )

            if result.returncode != 0:
                # Check if git is installed
                if "git" in result.stderr.lower() or "not found" in result.stderr.lower():
                    self.finished.emit(False,
                        "Git is not installed or not in PATH.\n\n"
                        "Please install Git from https://git-scm.com/ and try again."
                    )
                    return
                self.finished.emit(False, f"Failed to clone repository:\n{result.stderr}")
                return

            if self._cancelled:
                self.finished.emit(False, "Installation cancelled")
                return

            self.progress.emit("Installing VibeVoice dependencies...", 50)

            # Install with pip
            # Try uv first (as recommended in README), then fall back to pip
            try:
                result = subprocess.run(
                    ["uv", "pip", "install", "-e", str(install_dir)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=str(install_dir)
                )
                if result.returncode != 0:
                    raise Exception("uv not available")
            except Exception:
                # Fall back to regular pip
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", str(install_dir)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=str(install_dir)
                )

            if result.returncode != 0:
                self.finished.emit(False,
                    f"Failed to install dependencies:\n{result.stderr}\n\n"
                    f"You can try manually:\ncd {install_dir}\npip install -e ."
                )
                return

            if self._cancelled:
                self.finished.emit(False, "Installation cancelled")
                return

            self.progress.emit("Verifying installation...", 90)

            # Verify the installation - script is in demo/ folder
            if not (install_dir / "demo" / "inference_from_file.py").exists():
                self.finished.emit(False,
                    "Installation incomplete - required files not found.\n"
                    f"Expected: {install_dir / 'demo' / 'inference_from_file.py'}\n"
                    f"Please check the installation at: {install_dir}"
                )
                return

            self.progress.emit("Installation complete!", 100)
            self.finished.emit(True,
                f"VibeVoice successfully installed!\n\n"
                f"Location: {install_dir}\n\n"
                f"The first time you use VibeVoice, it will download the selected model."
            )

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Installation timed out.\nPlease check your internet connection and try again.")
        except Exception as e:
            self.finished.emit(False, f"Installation failed:\n{str(e)}")


@dataclass
class LanguageResourceInfo:
    """Information about a downloadable language resource."""
    resource_id: str
    display_name: str
    description: str
    platform: str  # 'nltk', 'spacy', etc.
    size_mb: float
    required_for: str


# Available language resources for download
LANGUAGE_RESOURCES: List[LanguageResourceInfo] = [
    # NLTK Resources
    LanguageResourceInfo(
        resource_id="wordnet",
        display_name="WordNet",
        description="Lexical database with synonyms, antonyms, definitions",
        platform="nltk",
        size_mb=30.0,
        required_for="Thesaurus, synonym lookup"
    ),
    LanguageResourceInfo(
        resource_id="averaged_perceptron_tagger",
        display_name="POS Tagger",
        description="Part-of-speech tagger for English text",
        platform="nltk",
        size_mb=2.0,
        required_for="Grammar analysis, word classification"
    ),
    LanguageResourceInfo(
        resource_id="punkt",
        display_name="Punkt Tokenizer",
        description="Sentence tokenization models",
        platform="nltk",
        size_mb=1.5,
        required_for="Sentence splitting, text processing"
    ),
    LanguageResourceInfo(
        resource_id="punkt_tab",
        display_name="Punkt Tab (Updated)",
        description="Updated Punkt tokenizer models",
        platform="nltk",
        size_mb=1.5,
        required_for="Sentence splitting (newer NLTK versions)"
    ),
    LanguageResourceInfo(
        resource_id="stopwords",
        display_name="Stopwords",
        description="Common words to filter (the, a, is, etc.)",
        platform="nltk",
        size_mb=0.1,
        required_for="Text analysis, keyword extraction"
    ),
    LanguageResourceInfo(
        resource_id="words",
        display_name="Word List",
        description="English word list for spell checking",
        platform="nltk",
        size_mb=0.7,
        required_for="Spell checking, word validation"
    ),
    LanguageResourceInfo(
        resource_id="omw-1.4",
        display_name="Open Multilingual WordNet",
        description="Extended WordNet with multilingual support",
        platform="nltk",
        size_mb=50.0,
        required_for="Extended synonyms, multilingual support"
    ),
]


class NLTKDownloadWorker(QThread):
    """Background worker for downloading NLTK data packages."""

    progress = pyqtSignal(str, int)  # status message, percentage (0-100, -1 for indeterminate)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, resource_ids: List[str]):
        super().__init__()
        self.resource_ids = resource_ids
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the download."""
        self._cancelled = True

    def run(self):
        """Download the NLTK resources."""
        try:
            self.progress.emit("Initializing NLTK...", -1)

            # Import NLTK
            try:
                import nltk
            except ImportError:
                self.finished.emit(False,
                    "NLTK not installed.\n\n"
                    "Install with: pip install nltk"
                )
                return

            if self._cancelled:
                self.finished.emit(False, "Download cancelled")
                return

            total = len(self.resource_ids)
            successful = []
            failed = []

            for i, resource_id in enumerate(self.resource_ids):
                if self._cancelled:
                    self.finished.emit(False, "Download cancelled")
                    return

                progress_pct = int((i / total) * 100)
                self.progress.emit(f"Downloading {resource_id}...", progress_pct)

                try:
                    # Download the resource
                    nltk.download(resource_id, quiet=True)
                    successful.append(resource_id)
                except Exception as e:
                    failed.append((resource_id, str(e)))

            self.progress.emit("Download complete!", 100)

            # Build result message
            msg_parts = []
            if successful:
                msg_parts.append(f"Successfully downloaded: {', '.join(successful)}")
            if failed:
                failed_msgs = [f"{r}: {e}" for r, e in failed]
                msg_parts.append(f"Failed to download:\n" + "\n".join(failed_msgs))

            success = len(failed) == 0
            self.finished.emit(success, "\n\n".join(msg_parts))

        except Exception as e:
            self.finished.emit(False, f"Download failed:\n\n{str(e)}")


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, current_settings: dict, parent=None):
        """Initialize settings dialog."""
        super().__init__(parent)
        self.settings = current_settings.copy()
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        self.setWindowTitle("AI Configuration & Settings")
        self.setMinimumSize(600, 500)  # Reduced for laptop compatibility

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("🤖 AI Configuration")
        header.setStyleSheet("font-size: 18px; font-weight: 600; color: #1a1a1a; padding: 10px;")
        layout.addWidget(header)

        # Tabs for different settings categories
        tabs = QTabWidget()

        # API Keys Tab
        api_tab = self._create_api_keys_tab()
        tabs.addTab(api_tab, "🔑 API Keys")

        # Model Configuration Tab
        model_tab = self._create_model_config_tab()
        tabs.addTab(model_tab, "⚙️ Model Settings")

        # Hugging Face / Local Models Tab
        hf_tab = self._create_huggingface_tab()
        tabs.addTab(hf_tab, "🤗 Local Models")

        # GenAI / Image Generation Tab
        genai_tab = self._create_genai_tab()
        tabs.addTab(genai_tab, "🎨 Image Generation")

        # Training Data Collection Tab
        training_tab = self._create_training_data_tab()
        tabs.addTab(training_tab, "📊 Training Data")

        # Text-to-Speech Tab
        tts_tab = self._create_tts_tab()
        tabs.addTab(tts_tab, "🔊 Text-to-Speech")

        # Features Tab
        features_tab = self._create_features_tab()
        tabs.addTab(features_tab, "✨ AI Features")

        # Language Resources Tab
        lang_tab = self._create_language_resources_tab()
        tabs.addTab(lang_tab, "📚 Language")

        # Knowledge Bases Tab
        from src.ui.knowledge_settings_widget import KnowledgeSettingsWidget
        self.knowledge_widget = KnowledgeSettingsWidget()
        self.knowledge_widget.set_britannica_key(self.settings.get("britannica_api_key", ""))
        self.knowledge_widget.set_knowledge_enabled(self.settings.get("enable_knowledge_base", True))
        tabs.addTab(self.knowledge_widget, "📖 Knowledge Bases")

        layout.addWidget(tabs)

        # Info
        info_label = QLabel(
            "💡 Tip: API keys are stored locally and encrypted. Your data never leaves your machine without explicit action."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #6b7280; font-size: 11px; padding: 10px; background-color: #f3f4f6; border-radius: 4px;")
        layout.addWidget(info_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        test_button = QPushButton("🧪 Test Connection")
        test_button.clicked.connect(self._test_connection)
        button_layout.addWidget(test_button)

        save_button = QPushButton("💾 Save")
        save_button.clicked.connect(self.accept)
        save_button.setDefault(True)
        button_layout.addWidget(save_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def _create_api_keys_tab(self) -> QWidget:
        """Create API keys configuration tab."""
        # Create scroll area wrapper
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # API Keys Group
        api_group = QGroupBox("API Keys")
        api_layout = QFormLayout()

        # Claude
        claude_container = QVBoxLayout()
        self.claude_key_edit = QLineEdit()
        self.claude_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.claude_key_edit.setText(self.settings.get("claude_api_key", ""))
        self.claude_key_edit.setPlaceholderText("sk-ant-api...")
        claude_container.addWidget(self.claude_key_edit)

        self.show_claude_key = QCheckBox("Show key")
        self.show_claude_key.toggled.connect(
            lambda checked: self.claude_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        claude_container.addWidget(self.show_claude_key)
        api_layout.addRow("Claude API Key:", claude_container)

        # ChatGPT/OpenAI
        chatgpt_container = QVBoxLayout()
        self.chatgpt_key_edit = QLineEdit()
        self.chatgpt_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.chatgpt_key_edit.setText(self.settings.get("chatgpt_api_key", ""))
        self.chatgpt_key_edit.setPlaceholderText("sk-proj-...")
        chatgpt_container.addWidget(self.chatgpt_key_edit)

        self.show_chatgpt_key = QCheckBox("Show key")
        self.show_chatgpt_key.toggled.connect(
            lambda checked: self.chatgpt_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        chatgpt_container.addWidget(self.show_chatgpt_key)
        api_layout.addRow("OpenAI API Key:", chatgpt_container)

        # Gemini
        gemini_container = QVBoxLayout()
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_edit.setText(self.settings.get("gemini_api_key", ""))
        self.gemini_key_edit.setPlaceholderText("AIza...")
        gemini_container.addWidget(self.gemini_key_edit)

        self.show_gemini_key = QCheckBox("Show key")
        self.show_gemini_key.toggled.connect(
            lambda checked: self.gemini_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        gemini_container.addWidget(self.show_gemini_key)
        api_layout.addRow("Gemini API Key:", gemini_container)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Help text
        help_text = QLabel(
            "Where to get API keys:\n"
            "• Claude: https://console.anthropic.com/\n"
            "• OpenAI: https://platform.openai.com/api-keys\n"
            "• Gemini: https://makersuite.google.com/app/apikey"
        )
        help_text.setStyleSheet("color: #6b7280; font-size: 11px; padding: 10px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()

        # Set widget to scroll area and return scroll area
        scroll_area.setWidget(widget)
        return scroll_area

    def _create_model_config_tab(self) -> QWidget:
        """Create model configuration tab."""
        # Create scroll area wrapper
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # Default AI Selection
        default_group = QGroupBox("Default AI Provider")
        default_layout = QFormLayout()

        self.default_llm_combo = QComboBox()
        self.default_llm_combo.addItems(["Claude", "ChatGPT", "Gemini"])
        current_llm = self.settings.get("default_llm", "claude")
        if current_llm:
            self.default_llm_combo.setCurrentText(current_llm.capitalize())
        default_layout.addRow("Primary AI:", self.default_llm_combo)

        default_group.setLayout(default_layout)
        layout.addWidget(default_group)

        # Model Selection
        model_group = QGroupBox("Model Selection")
        model_layout = QFormLayout()

        self.claude_model_combo = QComboBox()
        self.claude_model_combo.addItems([
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ])
        self.claude_model_combo.setCurrentText(
            self.settings.get("claude_model", "claude-3-5-sonnet-20241022")
        )
        model_layout.addRow("Claude Model:", self.claude_model_combo)

        self.openai_model_combo = QComboBox()
        self.openai_model_combo.addItems([
            "gpt-4-turbo-preview",
            "gpt-4",
            "gpt-3.5-turbo"
        ])
        self.openai_model_combo.setCurrentText(
            self.settings.get("openai_model", "gpt-4-turbo-preview")
        )
        model_layout.addRow("OpenAI Model:", self.openai_model_combo)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems([
            "gemini-pro",
            "gemini-pro-vision"
        ])
        self.gemini_model_combo.setCurrentText(
            self.settings.get("gemini_model", "gemini-pro")
        )
        model_layout.addRow("Gemini Model:", self.gemini_model_combo)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # Generation Parameters
        params_group = QGroupBox("Generation Parameters")
        params_layout = QFormLayout()

        # Temperature
        temp_container = QHBoxLayout()
        self.temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self.temperature_slider.setRange(0, 100)
        self.temperature_slider.setValue(int(self.settings.get("temperature", 0.7) * 100))
        temp_container.addWidget(self.temperature_slider)

        self.temperature_label = QLabel(f"{self.settings.get('temperature', 0.7):.2f}")
        self.temperature_slider.valueChanged.connect(
            lambda v: self.temperature_label.setText(f"{v/100:.2f}")
        )
        temp_container.addWidget(self.temperature_label)

        params_layout.addRow("Temperature (creativity):", temp_container)

        # Max tokens
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 8000)
        self.max_tokens_spin.setSingleStep(100)
        self.max_tokens_spin.setValue(self.settings.get("max_tokens", 2000))
        params_layout.addRow("Max Tokens:", self.max_tokens_spin)

        # Top P
        top_p_container = QHBoxLayout()
        self.top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.top_p_slider.setRange(0, 100)
        self.top_p_slider.setValue(int(self.settings.get("top_p", 0.95) * 100))
        top_p_container.addWidget(self.top_p_slider)

        self.top_p_label = QLabel(f"{self.settings.get('top_p', 0.95):.2f}")
        self.top_p_slider.valueChanged.connect(
            lambda v: self.top_p_label.setText(f"{v/100:.2f}")
        )
        top_p_container.addWidget(self.top_p_label)

        params_layout.addRow("Top P (nucleus sampling):", top_p_container)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # Parameter explanation
        explain_label = QLabel(
            "Temperature: Higher values (0.8-1.0) = more creative/random. Lower values (0.1-0.3) = more focused/deterministic.\n"
            "Max Tokens: Maximum length of AI response.\n"
            "Top P: Alternative to temperature for controlling randomness."
        )
        explain_label.setWordWrap(True)
        explain_label.setStyleSheet("color: #6b7280; font-size: 10px; padding: 10px;")
        layout.addWidget(explain_label)

        # Chapter Planning Configuration
        chapter_planning_group = QGroupBox("Chapter Planning & Storytelling")
        chapter_planning_layout = QVBoxLayout()

        planning_info = QLabel(
            "Configure which AI to use for chapter planning, event generation, and creative writing assistance."
        )
        planning_info.setWordWrap(True)
        planning_info.setStyleSheet("color: #374151; font-size: 11px; padding: 4px;")
        chapter_planning_layout.addWidget(planning_info)

        # Radio button group for chapter planning model choice
        self.chapter_planning_button_group = QButtonGroup()

        self.use_cloud_for_planning = QRadioButton("Use cloud AI (configured above)")
        self.use_cloud_for_planning.setToolTip("Uses your default cloud LLM (Claude, GPT-4, or Gemini)")
        self.chapter_planning_button_group.addButton(self.use_cloud_for_planning, 0)
        chapter_planning_layout.addWidget(self.use_cloud_for_planning)

        self.use_local_for_planning = QRadioButton("Use local storytelling model (configure in 'Local Models' tab)")
        self.use_local_for_planning.setToolTip("Uses a specialized storytelling model running on your device")
        self.chapter_planning_button_group.addButton(self.use_local_for_planning, 1)
        chapter_planning_layout.addWidget(self.use_local_for_planning)

        # Set current selection based on settings
        use_local = self.settings.get("use_local_for_chapter_planning", False)
        if use_local:
            self.use_local_for_planning.setChecked(True)
        else:
            self.use_cloud_for_planning.setChecked(True)

        # Info about local models
        local_models_info = QLabel(
            "📝 Storytelling models available for download:\n"
            "  ⭐ Hermes 2 Pro Mistral - Creative writing specialist (14GB)\n"
            "  📝 Qwen 2.5 7B - Long chapters with 128K context (14GB)\n"
            "  📖 TinyStories - Ultra-fast CPU story generation (70MB)\n"
            "  • Gemma, Phi - General purpose storytelling\n\n"
            "Go to the 'Local Models' tab to download and configure storytelling models."
        )
        local_models_info.setWordWrap(True)
        local_models_info.setStyleSheet(
            "color: #6b7280; font-size: 10px; padding: 8px; "
            "background-color: #f9fafb; border-radius: 4px; border-left: 3px solid #6366f1;"
        )
        chapter_planning_layout.addWidget(local_models_info)

        chapter_planning_group.setLayout(chapter_planning_layout)
        layout.addWidget(chapter_planning_group)

        layout.addStretch()

        # Set widget to scroll area and return scroll area
        scroll_area.setWidget(widget)
        return scroll_area

    def _create_huggingface_tab(self) -> QWidget:
        """Create Hugging Face / Local Models configuration tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # Enable Local Models
        enable_group = QGroupBox("Local Model Support")
        enable_layout = QVBoxLayout()

        self.enable_local_models = QCheckBox("Enable local/small language models (requires additional setup)")
        self.enable_local_models.setChecked(self.settings.get("enable_local_models", False))
        self.enable_local_models.toggled.connect(self._on_local_models_toggled)
        enable_layout.addWidget(self.enable_local_models)

        enable_note = QLabel(
            "Local models run on your machine and don't require API calls. "
            "They're faster and private, but may require significant GPU memory."
        )
        enable_note.setWordWrap(True)
        enable_note.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        enable_layout.addWidget(enable_note)

        enable_group.setLayout(enable_layout)
        layout.addWidget(enable_group)

        # Download Models Section
        download_group = QGroupBox("Download Models")
        download_layout = QVBoxLayout()

        download_info = QLabel(
            "Select a model to download. Models are cached locally and can be used offline."
        )
        download_info.setWordWrap(True)
        download_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        download_layout.addWidget(download_info)

        # Storytelling models highlight
        storytelling_highlight = QLabel(
            "📝 Storytelling models: ⭐ (creative writing), 📝 (long-form), 📖 (ultra-fast CPU). "
            "🧠 Reasoning models: For planning, plotting, and critique. "
            "Models optimized for specific tasks appear first in the list."
        )
        storytelling_highlight.setWordWrap(True)
        storytelling_highlight.setStyleSheet(
            "color: #059669; font-size: 10px; padding: 6px; "
            "background-color: #ecfdf5; border-radius: 4px; font-weight: 500;"
        )
        download_layout.addWidget(storytelling_highlight)

        # Model list
        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(150)
        self.model_list.setMaximumHeight(200)
        self.model_list.currentRowChanged.connect(self._on_model_selected)

        # Populate model list and check which ones are downloaded
        self._populate_model_list()

        download_layout.addWidget(self.model_list)

        # Model details
        self.model_details_label = QLabel("Select a model to see details...")
        self.model_details_label.setWordWrap(True)
        self.model_details_label.setStyleSheet(
            "color: #374151; font-size: 11px; padding: 8px; "
            "background-color: #f3f4f6; border-radius: 4px;"
        )
        download_layout.addWidget(self.model_details_label)

        # Download progress
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        download_layout.addWidget(self.download_progress)

        self.download_status_label = QLabel("")
        self.download_status_label.setWordWrap(True)
        self.download_status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.download_status_label.setVisible(False)
        download_layout.addWidget(self.download_status_label)

        # Download buttons
        download_buttons = QHBoxLayout()

        self.download_btn = QPushButton("Download Selected Model")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download_selected_model)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        download_buttons.addWidget(self.download_btn)

        self.check_downloaded_btn = QPushButton("Check Downloaded Models")
        self.check_downloaded_btn.clicked.connect(self._check_downloaded_models)
        download_buttons.addWidget(self.check_downloaded_btn)

        download_buttons.addStretch()
        download_layout.addLayout(download_buttons)

        # Downloaded models display
        self.downloaded_models_label = QLabel("")
        self.downloaded_models_label.setWordWrap(True)
        self.downloaded_models_label.setStyleSheet(
            "color: #059669; font-size: 11px; padding: 8px; "
            "background-color: #ecfdf5; border-radius: 4px;"
        )
        self.downloaded_models_label.setVisible(False)
        download_layout.addWidget(self.downloaded_models_label)

        download_group.setLayout(download_layout)
        layout.addWidget(download_group)

        # Hugging Face API
        hf_api_group = QGroupBox("Hugging Face Inference API (Optional)")
        hf_api_layout = QFormLayout()

        hf_key_container = QVBoxLayout()
        self.hf_api_key_edit = QLineEdit()
        self.hf_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # Load HF token from secure storage (Windows Credential Manager)
        cred_manager = get_credential_manager()
        hf_token = cred_manager.get_huggingface_token()
        if hf_token:
            self.hf_api_key_edit.setText(hf_token)
        else:
            # Fall back to settings if no secure credential found
            self.hf_api_key_edit.setText(self.settings.get("huggingface_api_key", ""))

        self.hf_api_key_edit.setPlaceholderText("hf_...")
        hf_key_container.addWidget(self.hf_api_key_edit)

        self.show_hf_key = QCheckBox("Show key")
        self.show_hf_key.toggled.connect(
            lambda checked: self.hf_api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        hf_key_container.addWidget(self.show_hf_key)
        hf_api_layout.addRow("HF API Token:", hf_key_container)

        hf_api_note = QLabel(
            "Token is stored securely in Windows Credential Manager.\n"
            "Get one at huggingface.co/settings/tokens (needed for gated models like Llama)"
        )
        hf_api_note.setWordWrap(True)
        hf_api_note.setStyleSheet("color: #6b7280; font-size: 10px;")
        hf_api_layout.addRow("", hf_api_note)

        hf_api_group.setLayout(hf_api_layout)
        layout.addWidget(hf_api_group)

        # Active Model Selection
        active_group = QGroupBox("Active Local Model")
        active_layout = QFormLayout()

        self.local_model_combo = QComboBox()
        self.local_model_combo.setEditable(True)
        self.local_model_combo.setPlaceholderText("Select or enter model ID...")

        # Add available models to combo with model_id as both display and data
        # Use get_available_models() to get platform-specific list (MLX on Apple Silicon, PyTorch elsewhere)
        available_models = get_available_models()
        for model in available_models:
            # Display format: "Display Name (model_id)"
            display_text = f"{model.display_name} ({model.model_id})"
            self.local_model_combo.addItem(display_text, model.model_id)

        # Set current value - find matching model_id
        # Use platform-specific default: MLX on Apple Silicon, PyTorch elsewhere
        default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit" if can_use_mlx() else "microsoft/Phi-3-mini-4k-instruct"
        current_model = self.settings.get("local_model_id", default_model)

        # Try to find and select the current model
        index = self.local_model_combo.findData(current_model)
        if index >= 0:
            self.local_model_combo.setCurrentIndex(index)
        else:
            # If not in list, add it as custom entry
            self.local_model_combo.setEditText(current_model)

        active_layout.addRow("Model:", self.local_model_combo)

        # Quantization with platform note
        quant_container = QVBoxLayout()

        self.quantization_combo = QComboBox()
        self.quantization_combo.addItems([
            "None (full precision)",
            "8-bit (CUDA only)",
            "4-bit (MLX on Mac / CUDA on Windows-Linux)",
        ])
        current_quant = self.settings.get("local_model_quantization", "none")
        if current_quant == "4bit":
            self.quantization_combo.setCurrentIndex(2)
        elif current_quant == "8bit":
            self.quantization_combo.setCurrentIndex(1)
        else:
            self.quantization_combo.setCurrentIndex(0)

        self.quantization_combo.setToolTip(
            "Quantization reduces model size and memory usage.\n"
            "4-bit: Supported natively by MLX on Apple Silicon AND by BitsAndBytes on CUDA.\n"
            "  - Mac: applies mlx.nn.quantize() (skipped for pre-quantized mlx-community models).\n"
            "  - Windows/Linux: requires NVIDIA GPU with BitsAndBytes.\n"
            "8-bit: CUDA only (BitsAndBytes). Not supported on Mac.\n"
            "Note: mlx-community models (e.g. *-4bit) are already quantized at download time;\n"
            "      selecting '4-bit' here is only needed for unquantized HuggingFace models."
        )
        quant_container.addWidget(self.quantization_combo)

        # Show platform-appropriate hint
        if can_use_mlx():
            quant_hint_text = (
                "Mac (MLX): 4-bit is supported. Pre-quantized mlx-community models "
                "are already quantized and ignore this setting."
            )
            quant_hint_style = "color: #22c55e; font-size: 10px;"
        else:
            quant_hint_text = "4-bit and 8-bit quantization require an NVIDIA GPU (CUDA)."
            quant_hint_style = "color: #f59e0b; font-size: 10px;"

        self.quantization_warning = QLabel(quant_hint_text)
        self.quantization_warning.setStyleSheet(quant_hint_style)
        self.quantization_warning.setWordWrap(True)
        quant_container.addWidget(self.quantization_warning)

        active_layout.addRow("Quantization:", quant_container)

        # Device selection with platform detection
        self.device_combo = QComboBox()
        self.device_combo.addItems(["Auto (Recommended)", "CUDA (NVIDIA GPU)", "MPS (Apple Silicon)", "CPU"])

        current_device = self.settings.get("local_model_device", "auto")
        device_map = {"auto": 0, "cuda": 1, "mps": 2, "cpu": 3}
        self.device_combo.setCurrentIndex(device_map.get(current_device, 0))

        # Add tooltip explaining device options
        self.device_combo.setToolTip(
            "Auto: Automatically select best device (CUDA > MPS > CPU)\n"
            "CUDA: Use NVIDIA GPU (supports quantization)\n"
            "MPS: Use Apple Silicon GPU (M1/M2/M3/M4/M5)\n"
            "CPU: Use CPU only (slowest, but works everywhere)"
        )
        active_layout.addRow("Device:", self.device_combo)

        # Trust remote code
        self.trust_remote_code = QCheckBox("Trust remote code (required for Phi, Qwen models)")
        self.trust_remote_code.setChecked(self.settings.get("trust_remote_code", True))
        active_layout.addRow("", self.trust_remote_code)

        active_group.setLayout(active_layout)
        layout.addWidget(active_group)

        # Storytelling / Chapter Planning Model
        storytelling_group = QGroupBox("Storytelling Model (Chapter Planning)")
        storytelling_layout = QFormLayout()

        storytelling_info = QLabel(
            "Choose a model optimized for creative writing, chapter planning, and story development. "
            "If not set, the active local model will be used."
        )
        storytelling_info.setWordWrap(True)
        storytelling_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        storytelling_layout.addRow("", storytelling_info)

        self.storytelling_model_combo = QComboBox()
        self.storytelling_model_combo.setEditable(True)
        self.storytelling_model_combo.setPlaceholderText("Use active model (default)")

        # Add "(Use active model)" as first option
        self.storytelling_model_combo.addItem("(Use active model)", "")

        # Add storytelling-optimized models from storytelling_config
        try:
            from src.config.storytelling_config import get_available_storytelling_models
            storytelling_models = get_available_storytelling_models()

            # Group models by category based on actual models in storytelling_config
            specialized = []  # Latest/recommended models
            longform = []  # Models with 128K+ context
            lightweight = []  # Ultra-fast/tiny models
            general = []  # Everything else

            for model in storytelling_models:
                display_text = f"{model.display_name} ({model.vram_gb}GB)"

                # Ultra lightweight models (TinyStories, TinyLlama)
                if "Tiny" in model.display_name:
                    lightweight.append((display_text, model.model_id))
                # Long-form models with 128K+ context
                elif model.context_length >= 128000:
                    longform.append((display_text, model.model_id))
                # Latest/recommended models (Qwen 3, Ministral 3, marked with [Latest] or [Recommended])
                elif "[Latest]" in model.display_name or "[Recommended]" in model.display_name or "Qwen 3" in model.display_name or "Ministral 3" in model.display_name:
                    specialized.append((display_text, model.model_id))
                else:
                    general.append((display_text, model.model_id))

            # Add specialized/latest models first
            if specialized:
                for display, model_id in specialized:
                    self.storytelling_model_combo.addItem(f"⭐ {display}", model_id)

            # Add long-form models
            if longform:
                for display, model_id in longform:
                    self.storytelling_model_combo.addItem(f"📝 {display}", model_id)

            # Add general models
            if general:
                for display, model_id in general:
                    self.storytelling_model_combo.addItem(display, model_id)

            # Add lightweight models last
            if lightweight:
                for display, model_id in lightweight:
                    self.storytelling_model_combo.addItem(f"⚡ {display}", model_id)

        except Exception as e:
            # Fallback to basic list if storytelling_config import fails
            print(f"Could not load storytelling models: {e}")
            basic_models = [
                ("Gemma 3 4B (8GB VRAM)", "google/gemma-3-4b-it"),
                ("Qwen 2.5 7B (14GB VRAM)", "Qwen/Qwen2.5-7B-Instruct"),
                ("Phi 3.5 Mini (6GB VRAM)", "microsoft/Phi-3.5-mini-instruct"),
            ]
            for display_name, model_id in basic_models:
                self.storytelling_model_combo.addItem(display_name, model_id)

        # Set current value
        current_storytelling = self.settings.get("storytelling_model_id", "")
        if current_storytelling:
            index = self.storytelling_model_combo.findData(current_storytelling)
            if index >= 0:
                self.storytelling_model_combo.setCurrentIndex(index)
            else:
                # Custom model - add it
                self.storytelling_model_combo.setEditText(current_storytelling)
        else:
            self.storytelling_model_combo.setCurrentIndex(0)  # Default to "(Use active model)"

        storytelling_layout.addRow("Model:", self.storytelling_model_combo)

        storytelling_note = QLabel(
            "⭐ = Latest/recommended models for creative writing\n"
            "📝 = Long-form writing with extended context (128K+ tokens)\n"
            "⚡ = Ultra-fast lightweight models for quick drafts\n"
            "These models are optimized for storytelling and narrative generation."
        )
        storytelling_note.setWordWrap(True)
        storytelling_note.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
        storytelling_layout.addRow("", storytelling_note)

        storytelling_group.setLayout(storytelling_layout)
        layout.addWidget(storytelling_group)

        # === Reasoning Models Configuration ===
        reasoning_group = QGroupBox("Reasoning Models for Planning & Critique")
        reasoning_layout = QFormLayout()

        reasoning_info = QLabel(
            "Reasoning models use chain-of-thought to analyze plot structure, check continuity, "
            "critique narratives, and help with story planning."
        )
        reasoning_info.setWordWrap(True)
        reasoning_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        reasoning_layout.addRow("", reasoning_info)

        self.reasoning_model_combo = QComboBox()
        self.reasoning_model_combo.setEditable(True)
        self.reasoning_model_combo.setPlaceholderText("Use storytelling model (default)")

        # Add "(Use storytelling model)" as first option
        self.reasoning_model_combo.addItem("(Use storytelling model)", "")

        # Add reasoning-optimized models from reasoning_config
        try:
            from src.config.reasoning_config import get_available_reasoning_models
            reasoning_models = get_available_reasoning_models()

            for model in reasoning_models:
                display_text = f"{model.display_name} ({model.vram_gb}GB)"
                self.reasoning_model_combo.addItem(f"🧠 {display_text}", model.model_id)

        except Exception as e:
            # Fallback to basic list if reasoning_config import fails
            print(f"Could not load reasoning models: {e}")
            basic_reasoning = [
                ("DeepSeek-R1 Qwen 7B (14GB)", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"),
                ("Phi-4 Reasoning Plus (28GB)", "microsoft/Phi-4-reasoning-plus"),
            ]
            for display_name, model_id in basic_reasoning:
                self.reasoning_model_combo.addItem(f"🧠 {display_name}", model_id)

        # Set current value
        current_reasoning = self.settings.get("reasoning_model_id", "")
        if current_reasoning:
            index = self.reasoning_model_combo.findData(current_reasoning)
            if index >= 0:
                self.reasoning_model_combo.setCurrentIndex(index)
            else:
                # Custom model - add it
                self.reasoning_model_combo.setEditText(current_reasoning)
        else:
            self.reasoning_model_combo.setCurrentIndex(0)  # Default to "(Use storytelling model)"

        reasoning_layout.addRow("Model:", self.reasoning_model_combo)

        reasoning_note = QLabel(
            "🧠 = Reasoning models with chain-of-thought\n"
            "These models show their reasoning process, ideal for:\n"
            "• Plot structure analysis and planning\n"
            "• Character consistency and continuity checking\n"
            "• Narrative critique and feedback"
        )
        reasoning_note.setWordWrap(True)
        reasoning_note.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
        reasoning_layout.addRow("", reasoning_note)

        reasoning_group.setLayout(reasoning_layout)
        layout.addWidget(reasoning_group)

        # Use local instead of API
        preference_group = QGroupBox("Model Preference")
        preference_layout = QVBoxLayout()

        self.prefer_local_model = QCheckBox("Use local model instead of API when available")
        self.prefer_local_model.setChecked(self.settings.get("prefer_local_model", False))
        preference_layout.addWidget(self.prefer_local_model)

        preference_note = QLabel(
            "When enabled, local models will be used for AI features instead of cloud APIs. "
            "This keeps your data private and works offline."
        )
        preference_note.setWordWrap(True)
        preference_note.setStyleSheet("color: #6b7280; font-size: 11px;")
        preference_layout.addWidget(preference_note)

        preference_group.setLayout(preference_layout)
        layout.addWidget(preference_group)

        # Critique Model Settings
        critique_group = QGroupBox("Critique Model Settings")
        critique_layout = QFormLayout()

        critique_info = QLabel(
            "Configure a specific model for writing critique and feedback. "
            "A dedicated model can provide more consistent and thorough analysis."
        )
        critique_info.setWordWrap(True)
        critique_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        critique_layout.addRow("", critique_info)

        # Critique model source
        self.critique_source_combo = QComboBox()
        self.critique_source_combo.addItems([
            "Use Default Model",
            "Use Specific Local Model",
            "Use Specific Cloud Provider"
        ])
        current_source = self.settings.get("critique_model_source", "default")
        source_map = {"default": 0, "local": 1, "cloud": 2}
        self.critique_source_combo.setCurrentIndex(source_map.get(current_source, 0))
        self.critique_source_combo.currentIndexChanged.connect(self._on_critique_source_changed)
        critique_layout.addRow("Critique Model:", self.critique_source_combo)

        # Local model selection for critique
        self.critique_local_combo = QComboBox()
        self.critique_local_combo.setEditable(True)
        self.critique_local_combo.setPlaceholderText("Select local model for critique...")
        for model in available_models:
            display_text = f"{model.display_name}"
            self.critique_local_combo.addItem(display_text, model.model_id)

        current_critique_model = self.settings.get("critique_local_model_id", "")
        if current_critique_model:
            index = self.critique_local_combo.findData(current_critique_model)
            if index >= 0:
                self.critique_local_combo.setCurrentIndex(index)
            else:
                self.critique_local_combo.setEditText(current_critique_model)
        critique_layout.addRow("Local Model:", self.critique_local_combo)

        # Cloud provider selection for critique
        self.critique_cloud_combo = QComboBox()
        self.critique_cloud_combo.addItems(["Claude", "ChatGPT", "Gemini"])
        current_provider = self.settings.get("critique_cloud_provider", "claude")
        provider_map = {"claude": 0, "chatgpt": 1, "gemini": 2}
        self.critique_cloud_combo.setCurrentIndex(provider_map.get(current_provider, 0))
        critique_layout.addRow("Cloud Provider:", self.critique_cloud_combo)

        # Critique temperature
        critique_temp_layout = QHBoxLayout()
        self.critique_temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.critique_temp_slider.setRange(0, 100)
        current_temp = int(self.settings.get("critique_temperature", 0.3) * 100)
        self.critique_temp_slider.setValue(current_temp)
        self.critique_temp_slider.valueChanged.connect(self._on_critique_temp_changed)
        critique_temp_layout.addWidget(self.critique_temp_slider)

        self.critique_temp_label = QLabel(f"{current_temp / 100:.2f}")
        self.critique_temp_label.setMinimumWidth(40)
        critique_temp_layout.addWidget(self.critique_temp_label)
        critique_layout.addRow("Temperature:", critique_temp_layout)

        critique_temp_note = QLabel("Lower values (0.2-0.4) give more consistent critique")
        critique_temp_note.setStyleSheet("color: #6b7280; font-size: 10px;")
        critique_layout.addRow("", critique_temp_note)

        critique_group.setLayout(critique_layout)
        layout.addWidget(critique_group)

        # Initialize critique visibility
        self._on_critique_source_changed(self.critique_source_combo.currentIndex())

        # Requirements note
        requirements = QLabel(
            "Requirements: pip install transformers torch huggingface_hub\n"
            "For quantization: pip install bitsandbytes accelerate"
        )
        requirements.setWordWrap(True)
        requirements.setStyleSheet("color: #f59e0b; font-size: 11px; padding: 10px; background-color: #fffbeb; border-radius: 4px;")
        layout.addWidget(requirements)

        # Initialize download worker reference
        self._download_worker: Optional[ModelDownloadWorker] = None

        layout.addStretch()
        scroll_area.setWidget(widget)
        return scroll_area

    def _on_model_selected(self, row: int):
        """Handle model selection in the list."""
        if row < 0:
            self.model_details_label.setText("Select a model to see details...")
            self.download_btn.setEnabled(False)
            return

        item = self.model_list.item(row)
        model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)

        details = (
            f"<b>{model.display_name}</b><br>"
            f"<b>Model ID:</b> {model.model_id}<br>"
            f"<b>Size:</b> ~{model.size_gb}GB download<br>"
            f"<b>RAM Required:</b> {model.ram_required}<br>"
            f"<b>Best for:</b> {model.best_for}<br>"
            f"<b>Description:</b> {model.description}"
        )
        if model.requires_trust_remote_code:
            details += "<br><i>(Requires 'trust remote code' enabled)</i>"

        self.model_details_label.setText(details)
        self.download_btn.setEnabled(True)

    def _download_selected_model(self):
        """Download the selected model."""
        row = self.model_list.currentRow()
        if row < 0:
            return

        item = self.model_list.item(row)
        model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)

        # Confirm download
        reply = QMessageBox.question(
            self,
            "Download Model",
            f"Download {model.display_name}?\n\n"
            f"This will download approximately {model.size_gb}GB of data.\n"
            f"The model will be cached in your Hugging Face cache directory.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Show progress
        self.download_progress.setVisible(True)
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_status_label.setVisible(True)
        self.download_status_label.setText("Starting download...")
        self.download_btn.setEnabled(False)

        # Get HF token from secure storage for gated models
        cred_manager = get_credential_manager()
        hf_token = cred_manager.get_huggingface_token()

        # Start download worker
        self._download_worker = ModelDownloadWorker(
            model.model_id,
            model.requires_trust_remote_code,
            hf_token
        )
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_progress(self, status: str, percentage: int):
        """Handle download progress updates."""
        self.download_status_label.setText(status)
        if percentage < 0:
            self.download_progress.setRange(0, 0)  # Indeterminate
        else:
            self.download_progress.setRange(0, 100)
            self.download_progress.setValue(percentage)

    def _on_download_finished(self, success: bool, message: str):
        """Handle download completion."""
        self.download_progress.setVisible(False)
        self.download_status_label.setVisible(False)
        self.download_btn.setEnabled(True)

        if success:
            QMessageBox.information(self, "Download Complete", message)
            # Update the active model combo to show this model
            row = self.model_list.currentRow()
            if row >= 0:
                item = self.model_list.item(row)
                model: LocalModelInfo = item.data(Qt.ItemDataRole.UserRole)
                # Find and select in combo, or add if custom
                index = self.local_model_combo.findData(model.model_id)
                if index >= 0:
                    self.local_model_combo.setCurrentIndex(index)
                else:
                    self.local_model_combo.setCurrentText(model.model_id)
                # Auto-enable trust remote code if needed
                if model.requires_trust_remote_code:
                    self.trust_remote_code.setChecked(True)
            self._check_downloaded_models()
        else:
            QMessageBox.warning(self, "Download Failed", message)

        self._download_worker = None

    def _populate_model_list(self):
        """Populate model list with download status indicators."""
        self.model_list.clear()

        # Get set of downloaded model IDs
        downloaded_ids = set()
        try:
            from huggingface_hub import scan_cache_dir
            cache_info = scan_cache_dir()
            for repo in cache_info.repos:
                downloaded_ids.add(repo.repo_id)
        except (ImportError, Exception):
            pass

        # Add models to list with download indicator
        # Use get_available_models() to get platform-specific list (MLX on Apple Silicon, PyTorch elsewhere)
        available_models = get_available_models()

        # Separate storytelling models to show them first
        storytelling_models = []
        other_models = []

        for model in available_models:
            if "⭐" in model.display_name or "📝" in model.display_name or "storytelling" in model.best_for.lower():
                storytelling_models.append(model)
            else:
                other_models.append(model)

        # Add storytelling models first, then others
        for model in storytelling_models + other_models:
            is_downloaded = model.model_id in downloaded_ids
            download_indicator = "✓ " if is_downloaded else ""
            item_text = f"{download_indicator}{model.display_name} - {model.size_gb}GB"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, model)

            # Color downloaded models green, storytelling models in bold
            if is_downloaded:
                item.setForeground(QColor("#059669"))
                item.setToolTip(f"✓ Downloaded: {model.model_id}")
            else:
                item.setToolTip(f"Not downloaded: {model.model_id}")

            self.model_list.addItem(item)

    def _check_downloaded_models(self):
        """Check which models are already downloaded."""
        try:
            from huggingface_hub import scan_cache_dir

            cache_info = scan_cache_dir()
            downloaded = []

            # Use get_available_models() to get platform-specific list
            available_models = get_available_models()

            for repo in cache_info.repos:
                # Check if it's one of our known models
                for model in available_models:
                    if model.model_id == repo.repo_id:
                        size_gb = repo.size_on_disk / (1024**3)
                        downloaded.append(f"{model.display_name} ({size_gb:.1f}GB)")
                        break
                else:
                    # Unknown model in cache
                    size_gb = repo.size_on_disk / (1024**3)
                    if size_gb > 0.1:  # Only show models > 100MB
                        downloaded.append(f"{repo.repo_id} ({size_gb:.1f}GB)")

            if downloaded:
                self.downloaded_models_label.setText(
                    "<b>Downloaded models:</b><br>" + "<br>".join(downloaded[:10])
                )
                self.downloaded_models_label.setVisible(True)
            else:
                self.downloaded_models_label.setText("No models downloaded yet.")
                self.downloaded_models_label.setVisible(True)

            # Refresh the model list to update download indicators
            self._populate_model_list()

        except ImportError:
            self.downloaded_models_label.setText(
                "Install huggingface_hub to check downloaded models:\n"
                "pip install huggingface_hub"
            )
            self.downloaded_models_label.setStyleSheet(
                "color: #f59e0b; font-size: 11px; padding: 8px; "
                "background-color: #fffbeb; border-radius: 4px;"
            )
            self.downloaded_models_label.setVisible(True)
        except Exception as e:
            self.downloaded_models_label.setText(f"Error checking cache: {e}")
            self.downloaded_models_label.setVisible(True)

    def _get_selected_model_id(self) -> str:
        """Get the model ID from the local model combo box."""
        # Check if user selected from dropdown (has data) or typed custom
        current_data = self.local_model_combo.currentData()
        if current_data:
            return current_data

        # User typed a custom entry
        text = self.local_model_combo.currentText()

        # If text contains parentheses (our display format), extract model_id
        if "(" in text and ")" in text:
            # Extract text between last ( and )
            start = text.rfind("(")
            end = text.rfind(")")
            if start < end:
                return text[start+1:end].strip()

        # Otherwise, treat entire text as model ID
        return text.strip()

    def _get_storytelling_model_id(self) -> str:
        """Get the storytelling model ID from the combo box.

        Returns empty string if "(Use active model)" is selected.
        """
        current_data = self.storytelling_model_combo.currentData()
        if current_data:
            return current_data  # Empty string for default, or model ID

        # User typed a custom entry
        text = self.storytelling_model_combo.currentText()

        # If it's the default placeholder, return empty
        if text == "(Use active model)" or not text.strip():
            return ""

        # If text contains parentheses (our display format), extract model_id
        if "(" in text and ")" in text:
            start = text.rfind("(")
            end = text.rfind(")")
            if start < end:
                return text[start+1:end].strip()

        # Otherwise, treat entire text as model ID
        return text.strip()

    def _get_reasoning_model_id(self) -> str:
        """Get the reasoning model ID from the combo box.

        Returns empty string if "(Use storytelling model)" is selected.
        """
        current_data = self.reasoning_model_combo.currentData()
        if current_data:
            return current_data  # Empty string for default, or model ID

        # User typed a custom entry
        text = self.reasoning_model_combo.currentText()

        # If it's the default placeholder, return empty
        if text == "(Use storytelling model)" or not text.strip():
            return ""

        # If text contains parentheses (our display format), extract model_id
        if "(" in text and ")" in text:
            start = text.rfind("(")
            end = text.rfind(")")
            if start < end:
                return text[start+1:end].strip()

        # Otherwise, treat entire text as model ID
        return text.strip()

    def _create_genai_tab(self) -> QWidget:
        """Create GenAI / Image Generation configuration tab."""
        from src.config.genai_config import get_genai_config, get_available_image_models

        genai_config = get_genai_config()
        settings = genai_config.get_settings()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Header
        header = QLabel("Configure image generation models and settings")
        header.setWordWrap(True)
        header.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(header)

        # Enable/Disable
        self.enable_image_gen = QCheckBox("Enable AI Image Generation")
        self.enable_image_gen.setChecked(settings.get("image_generation_enabled", True))
        layout.addWidget(self.enable_image_gen)

        # Image Model Selection
        model_group = QGroupBox("Image Generation Model")
        model_layout = QFormLayout()

        self.image_model_combo = QComboBox()
        available_models = get_available_image_models()
        for model in available_models:
            display = f"{model.display_name} ({model.vram_gb}GB VRAM)"
            self.image_model_combo.addItem(display, model.model_id)

        current_model = settings.get("image_model_id", "")
        index = self.image_model_combo.findData(current_model)
        if index >= 0:
            self.image_model_combo.setCurrentIndex(index)

        model_layout.addRow("Model:", self.image_model_combo)

        # Download Model Button
        download_layout = QHBoxLayout()
        self.download_model_btn = QPushButton("📥 Download/Verify Model")
        self.download_model_btn.setToolTip("Download the selected image generation model (first use)")
        self.download_model_btn.clicked.connect(self._download_image_model)
        download_layout.addWidget(self.download_model_btn)
        download_layout.addStretch()
        model_layout.addRow("", download_layout)

        # Model info label
        self.model_info_label = QLabel()
        self.model_info_label.setWordWrap(True)
        self.model_info_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        self._update_model_info()
        self.image_model_combo.currentIndexChanged.connect(self._update_model_info)
        model_layout.addRow("", self.model_info_label)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # Prompt Enhancement LLM
        prompt_group = QGroupBox("Prompt Enhancement (separate from main LLM)")
        prompt_layout = QFormLayout()

        self.use_prompt_enhancement = QCheckBox("Use LLM to enhance image prompts")
        self.use_prompt_enhancement.setChecked(settings.get("use_prompt_enhancement", True))
        prompt_layout.addRow("", self.use_prompt_enhancement)

        self.prompt_llm_provider = QComboBox()
        self.prompt_llm_provider.addItems(["Local SLM", "Claude", "ChatGPT", "Gemini"])
        provider_map = {"local": 0, "claude": 1, "chatgpt": 2, "gemini": 3}
        current_provider = settings.get("prompt_llm_provider", "local")
        self.prompt_llm_provider.setCurrentIndex(provider_map.get(current_provider, 0))
        prompt_layout.addRow("Provider:", self.prompt_llm_provider)

        self.prompt_llm_model = QComboBox()
        self.prompt_llm_model.setEditable(True)
        # Populate with text LLM models
        text_models = get_available_models()
        for model in text_models[:10]:  # Show first 10
            self.prompt_llm_model.addItem(model.display_name, model.model_id)

        current_prompt_model = settings.get("prompt_llm_model_id", "")
        idx = self.prompt_llm_model.findData(current_prompt_model)
        if idx >= 0:
            self.prompt_llm_model.setCurrentIndex(idx)
        else:
            self.prompt_llm_model.setCurrentText(current_prompt_model)

        prompt_layout.addRow("Local Model:", self.prompt_llm_model)

        prompt_group.setLayout(prompt_layout)
        layout.addWidget(prompt_group)

        # Image Settings
        settings_group = QGroupBox("Image Settings")
        settings_layout = QFormLayout()

        self.image_width = QSpinBox()
        self.image_width.setRange(256, 2048)
        self.image_width.setSingleStep(64)
        self.image_width.setValue(settings.get("image_width", 1024))
        settings_layout.addRow("Width:", self.image_width)

        self.image_height = QSpinBox()
        self.image_height.setRange(256, 2048)
        self.image_height.setSingleStep(64)
        self.image_height.setValue(settings.get("image_height", 1024))
        settings_layout.addRow("Height:", self.image_height)

        self.image_steps = QSpinBox()
        self.image_steps.setRange(10, 100)
        self.image_steps.setValue(settings.get("image_num_inference_steps", 20))
        settings_layout.addRow("Inference Steps:", self.image_steps)

        self.image_guidance = QDoubleSpinBox()
        self.image_guidance.setRange(1.0, 20.0)
        self.image_guidance.setSingleStep(0.5)
        self.image_guidance.setValue(settings.get("image_guidance_scale", 7.5))
        settings_layout.addRow("Guidance Scale:", self.image_guidance)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Character Context
        char_group = QGroupBox("Character Generation")
        char_layout = QFormLayout()

        self.include_char_context = QCheckBox("Include character backstory/personality in prompts")
        self.include_char_context.setChecked(settings.get("include_character_context", True))
        char_layout.addRow("", self.include_char_context)

        self.char_prompt_weight = QDoubleSpinBox()
        self.char_prompt_weight.setRange(0.0, 1.0)
        self.char_prompt_weight.setSingleStep(0.1)
        self.char_prompt_weight.setValue(settings.get("character_prompt_weight", 0.8))
        char_layout.addRow("Character Weight:", self.char_prompt_weight)

        char_group.setLayout(char_layout)
        layout.addWidget(char_group)

        layout.addStretch()
        scroll_area.setWidget(content)
        return scroll_area

    def _create_training_data_tab(self) -> QWidget:
        """Create training data collection configuration tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # Info header
        info_header = QLabel(
            "📊 Build Your Personal Training Dataset\n\n"
            "Collect high-quality AI conversations to fine-tune a small language model "
            "that matches your unique writing style and creative process."
        )
        info_header.setWordWrap(True)
        info_header.setStyleSheet("font-size: 12px; padding: 10px; background-color: #f0f9ff; border-radius: 6px; color: #0369a1;")
        layout.addWidget(info_header)

        # Enable collection
        enable_group = QGroupBox("Data Collection")
        enable_layout = QVBoxLayout()

        self.enable_conversation_collection = QCheckBox("Enable conversation collection for fine-tuning")
        self.enable_conversation_collection.setChecked(self.settings.get("enable_conversation_collection", False))
        self.enable_conversation_collection.toggled.connect(self._on_collection_toggled)
        enable_layout.addWidget(self.enable_conversation_collection)

        collection_note = QLabel(
            "When enabled, you can rate AI conversations as 'Excellent' to save them for training. "
            "Only conversations you explicitly rate are saved. All data stays on your machine."
        )
        collection_note.setWordWrap(True)
        collection_note.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        enable_layout.addWidget(collection_note)

        enable_group.setLayout(enable_layout)
        layout.addWidget(enable_group)

        # Collection settings
        collection_group = QGroupBox("Collection Settings")
        collection_layout = QFormLayout()

        # Auto-prompt for rating
        self.auto_prompt_rating = QCheckBox("Prompt to rate conversations after AI responses")
        self.auto_prompt_rating.setChecked(self.settings.get("auto_prompt_rating", True))
        collection_layout.addRow("", self.auto_prompt_rating)

        # Minimum rating to save
        self.min_rating_combo = QComboBox()
        self.min_rating_combo.addItems(["Excellent only", "Good and above", "All rated"])
        min_rating = self.settings.get("min_collection_rating", "good")
        rating_map = {"excellent": 0, "good": 1, "all": 2}
        self.min_rating_combo.setCurrentIndex(rating_map.get(min_rating, 1))
        collection_layout.addRow("Save conversations rated:", self.min_rating_combo)

        # Task types to collect
        task_types_label = QLabel("Collect data for:")
        collection_layout.addRow("", task_types_label)

        self.collect_character_dev = QCheckBox("Character development")
        self.collect_character_dev.setChecked(self.settings.get("collect_character_dev", True))
        collection_layout.addRow("", self.collect_character_dev)

        self.collect_worldbuilding = QCheckBox("Worldbuilding")
        self.collect_worldbuilding.setChecked(self.settings.get("collect_worldbuilding", True))
        collection_layout.addRow("", self.collect_worldbuilding)

        self.collect_plot = QCheckBox("Plot & story planning")
        self.collect_plot.setChecked(self.settings.get("collect_plot", True))
        collection_layout.addRow("", self.collect_plot)

        self.collect_writing = QCheckBox("Writing assistance & critique")
        self.collect_writing.setChecked(self.settings.get("collect_writing", True))
        collection_layout.addRow("", self.collect_writing)

        self.collect_general = QCheckBox("General chat")
        self.collect_general.setChecked(self.settings.get("collect_general", True))
        collection_layout.addRow("", self.collect_general)

        collection_group.setLayout(collection_layout)
        layout.addWidget(collection_group)

        # Export options
        export_group = QGroupBox("Export Training Data")
        export_layout = QVBoxLayout()

        export_note = QLabel(
            "Export your collected conversations in formats ready for fine-tuning:\n"
            "• OpenAI format (JSONL) - For OpenAI fine-tuning API\n"
            "• Alpaca format - For local fine-tuning with tools like LLaMA-Factory\n"
            "• ShareGPT format - Compatible with many training frameworks"
        )
        export_note.setWordWrap(True)
        export_note.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        export_layout.addWidget(export_note)

        export_buttons = QHBoxLayout()

        export_openai_btn = QPushButton("Export OpenAI Format")
        export_openai_btn.clicked.connect(lambda: self._export_training_data("openai"))
        export_buttons.addWidget(export_openai_btn)

        export_alpaca_btn = QPushButton("Export Alpaca Format")
        export_alpaca_btn.clicked.connect(lambda: self._export_training_data("alpaca"))
        export_buttons.addWidget(export_alpaca_btn)

        export_layout.addLayout(export_buttons)

        # Stats display
        self.training_stats_label = QLabel("No training data collected yet.")
        self.training_stats_label.setStyleSheet("color: #6b7280; font-size: 11px; padding: 8px; background-color: #f9fafb; border-radius: 4px;")
        export_layout.addWidget(self.training_stats_label)

        view_stats_btn = QPushButton("Refresh Statistics")
        view_stats_btn.clicked.connect(self._refresh_training_stats)
        view_stats_btn.setMaximumWidth(150)
        export_layout.addWidget(view_stats_btn)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        # Privacy notice
        privacy = QLabel(
            "🔒 Privacy: All collected data is stored locally on your machine in:\n"
            "~/.writer_platform/training_data/\n\n"
            "Your conversations are never uploaded anywhere unless you explicitly export and share them."
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: #059669; font-size: 11px; padding: 10px; background-color: #ecfdf5; border-radius: 4px;")
        layout.addWidget(privacy)

        layout.addStretch()
        scroll_area.setWidget(widget)
        return scroll_area

    def _on_local_models_toggled(self, checked: bool):
        """Handle local models toggle."""
        # Could enable/disable related controls

    def _on_critique_source_changed(self, index: int):
        """Handle critique model source change."""
        # 0 = Default, 1 = Local, 2 = Cloud
        self.critique_local_combo.setVisible(index == 1)
        self.critique_cloud_combo.setVisible(index == 2)

        # Update labels visibility
        # Find and update the label rows in the form layout
        try:
            # Just set enabled state instead of visibility for form rows
            self.critique_local_combo.setEnabled(index == 1)
            self.critique_cloud_combo.setEnabled(index == 2)
        except Exception:
            pass

    def _on_critique_temp_changed(self, value: int):
        """Handle critique temperature slider change."""
        temp = value / 100.0
        self.critique_temp_label.setText(f"{temp:.2f}")

    def _on_collection_toggled(self, checked: bool):
        """Handle collection toggle."""
        # Could enable/disable related controls

    def _on_disable_ai_toggled(self, checked: bool):
        """Handle disable all AI toggle."""
        # Disable/enable the AI features group when AI is disabled
        if hasattr(self, 'ai_features_group'):
            self.ai_features_group.setEnabled(not checked)

    def _create_tts_tab(self) -> QWidget:
        """Create Text-to-Speech configuration tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # TTS Engine Selection
        engine_group = QGroupBox("TTS Engine")
        engine_layout = QVBoxLayout()

        engine_info = QLabel(
            "Select your preferred text-to-speech engine. VibeVoice provides the highest quality "
            "neural voice synthesis but requires installation."
        )
        engine_info.setWordWrap(True)
        engine_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        engine_layout.addWidget(engine_info)

        self.tts_engine_combo = QComboBox()
        self.tts_engine_combo.addItem("System TTS (pyttsx3) - Offline", "system")
        self.tts_engine_combo.addItem("Edge TTS - Microsoft Neural Voices (Online)", "edge")
        self.tts_engine_combo.addItem("VibeVoice - High Quality Neural TTS (Local)", "vibevoice")

        current_engine = self.settings.get("tts_engine", "system")
        for i in range(self.tts_engine_combo.count()):
            if self.tts_engine_combo.itemData(i) == current_engine:
                self.tts_engine_combo.setCurrentIndex(i)
                break

        self.tts_engine_combo.currentIndexChanged.connect(self._on_tts_engine_changed)
        engine_layout.addWidget(self.tts_engine_combo)

        engine_group.setLayout(engine_layout)
        layout.addWidget(engine_group)

        # VibeVoice Installation
        vibevoice_group = QGroupBox("VibeVoice Community")
        vibevoice_layout = QVBoxLayout()

        # Status check
        self.vibevoice_status_label = QLabel("Checking VibeVoice status...")
        self.vibevoice_status_label.setWordWrap(True)
        self.vibevoice_status_label.setStyleSheet(
            "padding: 8px; background-color: #f3f4f6; border-radius: 4px;"
        )
        vibevoice_layout.addWidget(self.vibevoice_status_label)

        # Installation path
        path_container = QHBoxLayout()
        path_label = QLabel("Install location:")
        path_container.addWidget(path_label)

        self.vibevoice_path_edit = QLineEdit()
        self.vibevoice_path_edit.setText(self.settings.get("vibevoice_path", str(Path.home() / "VibeVoice")))
        self.vibevoice_path_edit.setPlaceholderText(str(Path.home() / "VibeVoice"))
        path_container.addWidget(self.vibevoice_path_edit, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_vibevoice_path)
        path_container.addWidget(browse_btn)

        vibevoice_layout.addLayout(path_container)

        # Installation progress
        self.vibevoice_progress = QProgressBar()
        self.vibevoice_progress.setVisible(False)
        vibevoice_layout.addWidget(self.vibevoice_progress)

        self.vibevoice_progress_label = QLabel("")
        self.vibevoice_progress_label.setWordWrap(True)
        self.vibevoice_progress_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.vibevoice_progress_label.setVisible(False)
        vibevoice_layout.addWidget(self.vibevoice_progress_label)

        # Install button
        install_buttons = QHBoxLayout()

        self.install_vibevoice_btn = QPushButton("Install VibeVoice from GitHub")
        self.install_vibevoice_btn.clicked.connect(self._install_vibevoice)
        self.install_vibevoice_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        install_buttons.addWidget(self.install_vibevoice_btn)

        self.check_vibevoice_btn = QPushButton("Check Status")
        self.check_vibevoice_btn.clicked.connect(self._check_vibevoice_status)
        install_buttons.addWidget(self.check_vibevoice_btn)

        install_buttons.addStretch()
        vibevoice_layout.addLayout(install_buttons)

        # VibeVoice info
        vibevoice_info = QLabel(
            "VibeVoice Community provides high-quality neural text-to-speech synthesis.\n\n"
            "Requirements:\n"
            "• Git (for installation)\n"
            "• Python 3.10+\n"
            "• ~16GB RAM for 1.5B model\n"
            "• GPU recommended for faster synthesis\n\n"
            "Models are downloaded on first use (~3-14GB depending on model size)."
        )
        vibevoice_info.setWordWrap(True)
        vibevoice_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 8px;")
        vibevoice_layout.addWidget(vibevoice_info)

        vibevoice_group.setLayout(vibevoice_layout)
        layout.addWidget(vibevoice_group)

        # VibeVoice Settings (only shown when VibeVoice is selected)
        self.vibevoice_settings_group = QGroupBox("VibeVoice Settings")
        vv_settings_layout = QFormLayout()

        # Model selection
        self.vibevoice_model_combo = QComboBox()
        self.vibevoice_model_combo.addItem("0.5B (Streaming) - Fastest, lowest quality", "0.5B")
        self.vibevoice_model_combo.addItem("1.5B - Balanced quality and speed", "1.5B")
        self.vibevoice_model_combo.addItem("7B - Highest quality, slower", "7B")

        current_model = self.settings.get("vibevoice_model", "1.5B")
        for i in range(self.vibevoice_model_combo.count()):
            if self.vibevoice_model_combo.itemData(i) == current_model:
                self.vibevoice_model_combo.setCurrentIndex(i)
                break

        vv_settings_layout.addRow("Model:", self.vibevoice_model_combo)

        # Voice selection
        self.vibevoice_voice_combo = QComboBox()
        voices = [
            ("carter", "Carter (Male)"),
            ("davis", "Davis (Male)"),
            ("emma", "Emma (Female)"),
            ("frank", "Frank (Male)"),
            ("grace", "Grace (Female)"),
            ("mike", "Mike (Male)"),
            ("samuel", "Samuel (Male)"),
        ]
        for voice_id, voice_name in voices:
            self.vibevoice_voice_combo.addItem(voice_name, voice_id)

        current_voice = self.settings.get("vibevoice_voice", "emma")
        for i in range(self.vibevoice_voice_combo.count()):
            if self.vibevoice_voice_combo.itemData(i) == current_voice:
                self.vibevoice_voice_combo.setCurrentIndex(i)
                break

        vv_settings_layout.addRow("Voice:", self.vibevoice_voice_combo)

        self.vibevoice_settings_group.setLayout(vv_settings_layout)
        layout.addWidget(self.vibevoice_settings_group)

        # General TTS Settings
        general_group = QGroupBox("General TTS Settings")
        general_layout = QFormLayout()

        # Speech rate
        rate_container = QHBoxLayout()
        self.tts_rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.tts_rate_slider.setRange(80, 250)  # Normal speech range
        self.tts_rate_slider.setValue(self.settings.get("tts_rate", 150))
        rate_container.addWidget(self.tts_rate_slider)

        self.tts_rate_label = QLabel(f"{self.settings.get('tts_rate', 150)} WPM")
        self.tts_rate_slider.valueChanged.connect(
            lambda v: self.tts_rate_label.setText(f"{v} WPM")
        )
        rate_container.addWidget(self.tts_rate_label)
        general_layout.addRow("Speech Rate:", rate_container)

        # Volume
        volume_container = QHBoxLayout()
        self.tts_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.tts_volume_slider.setRange(0, 100)
        self.tts_volume_slider.setValue(int(self.settings.get("tts_volume", 1.0) * 100))
        volume_container.addWidget(self.tts_volume_slider)

        self.tts_volume_label = QLabel(f"{int(self.settings.get('tts_volume', 1.0) * 100)}%")
        self.tts_volume_slider.valueChanged.connect(
            lambda v: self.tts_volume_label.setText(f"{v}%")
        )
        volume_container.addWidget(self.tts_volume_label)
        general_layout.addRow("Volume:", volume_container)

        general_group.setLayout(general_layout)
        layout.addWidget(general_group)

        # Initialize VibeVoice install worker reference
        self._vibevoice_worker: Optional[VibeVoiceInstallWorker] = None

        # Check initial status
        self._check_vibevoice_status()
        self._on_tts_engine_changed()

        layout.addStretch()
        scroll_area.setWidget(widget)
        return scroll_area

    def _on_tts_engine_changed(self):
        """Handle TTS engine selection change."""
        engine = self.tts_engine_combo.currentData()
        # Show/hide VibeVoice settings based on selection
        self.vibevoice_settings_group.setVisible(engine == "vibevoice")

    def _browse_vibevoice_path(self):
        """Browse for VibeVoice installation directory."""
        from PyQt6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(
            self,
            "Select VibeVoice Installation Directory",
            str(Path.home())
        )
        if path:
            self.vibevoice_path_edit.setText(path)

    def _check_vibevoice_status(self):
        """Check if VibeVoice is installed."""
        install_path = self.vibevoice_path_edit.text() or str(Path.home() / "VibeVoice")
        install_dir = Path(install_path)

        # Check for the inference script in demo/ folder
        if install_dir.exists() and (install_dir / "demo" / "inference_from_file.py").exists():
            self.vibevoice_status_label.setText(
                f"✓ VibeVoice is installed at:\n{install_path}"
            )
            self.vibevoice_status_label.setStyleSheet(
                "padding: 8px; background-color: #ecfdf5; border-radius: 4px; color: #059669;"
            )
            self.install_vibevoice_btn.setText("Reinstall VibeVoice")
        else:
            self.vibevoice_status_label.setText(
                "✗ VibeVoice is not installed.\n"
                "Click 'Install VibeVoice from GitHub' to download and set up."
            )
            self.vibevoice_status_label.setStyleSheet(
                "padding: 8px; background-color: #fef2f2; border-radius: 4px; color: #dc2626;"
            )
            self.install_vibevoice_btn.setText("Install VibeVoice from GitHub")

    def _install_vibevoice(self):
        """Start VibeVoice installation."""
        install_path = self.vibevoice_path_edit.text() or str(Path.home() / "VibeVoice")

        # Confirm installation
        reply = QMessageBox.question(
            self,
            "Install VibeVoice",
            f"This will clone VibeVoice from GitHub and install dependencies.\n\n"
            f"Installation path: {install_path}\n\n"
            f"Requirements:\n"
            f"• Git must be installed\n"
            f"• Internet connection required\n"
            f"• ~500MB download for code\n"
            f"• Additional model downloads on first use\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Show progress
        self.vibevoice_progress.setVisible(True)
        self.vibevoice_progress.setRange(0, 100)
        self.vibevoice_progress.setValue(0)
        self.vibevoice_progress_label.setVisible(True)
        self.vibevoice_progress_label.setText("Starting installation...")
        self.install_vibevoice_btn.setEnabled(False)

        # Start install worker
        self._vibevoice_worker = VibeVoiceInstallWorker(install_path)
        self._vibevoice_worker.progress.connect(self._on_vibevoice_progress)
        self._vibevoice_worker.finished.connect(self._on_vibevoice_finished)
        self._vibevoice_worker.start()

    def _on_vibevoice_progress(self, status: str, percentage: int):
        """Handle VibeVoice installation progress updates."""
        self.vibevoice_progress_label.setText(status)
        if percentage < 0:
            self.vibevoice_progress.setRange(0, 0)  # Indeterminate
        else:
            self.vibevoice_progress.setRange(0, 100)
            self.vibevoice_progress.setValue(percentage)

    def _on_vibevoice_finished(self, success: bool, message: str):
        """Handle VibeVoice installation completion."""
        self.vibevoice_progress.setVisible(False)
        self.vibevoice_progress_label.setVisible(False)
        self.install_vibevoice_btn.setEnabled(True)

        if success:
            QMessageBox.information(self, "Installation Complete", message)
            self._check_vibevoice_status()
        else:
            QMessageBox.warning(self, "Installation Failed", message)

        self._vibevoice_worker = None

    def _export_training_data(self, format_type: str):
        """Export training data in specified format."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from pathlib import Path

        try:
            from src.ai.conversation_store import ConversationStore, ConversationRating

            store = ConversationStore()
            stats = store.get_statistics()

            if stats["high_quality_count"] == 0:
                QMessageBox.warning(
                    self,
                    "No Data",
                    "No high-quality conversations have been collected yet.\n\n"
                    "Rate some AI conversations as 'Good' or 'Excellent' to build your dataset."
                )
                return

            # Get save path
            file_ext = ".jsonl" if format_type in ["openai", "alpaca"] else ".json"
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                f"Export {format_type.title()} Training Data",
                f"training_data_{format_type}{file_ext}",
                f"JSONL Files (*{file_ext});;All Files (*)"
            )

            if file_path:
                count = store.export_for_training(
                    Path(file_path),
                    format_type=format_type,
                    min_rating=ConversationRating.GOOD
                )
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Exported {count} conversations in {format_type} format.\n\n"
                    f"File saved to:\n{file_path}"
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export training data:\n{str(e)}"
            )

    def _refresh_training_stats(self):
        """Refresh training data statistics display."""
        try:
            from src.ai.conversation_store import ConversationStore

            store = ConversationStore()
            stats = store.get_statistics()

            text = (
                f"Total conversations: {stats['total_conversations']}\n"
                f"High quality (Good+): {stats['high_quality_count']}\n\n"
                f"By rating: {', '.join(f'{k}: {v}' for k, v in stats['rating_distribution'].items() if v > 0)}\n"
                f"By task: {', '.join(f'{k}: {v}' for k, v in stats['task_type_distribution'].items() if v > 0)}"
            )
            self.training_stats_label.setText(text)
        except Exception as e:
            self.training_stats_label.setText(f"Error loading stats: {e}")

    def _create_features_tab(self) -> QWidget:
        """Create AI features configuration tab."""
        # Create scroll area wrapper
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # Master AI Toggle
        master_group = QGroupBox("AI Mode")
        master_layout = QVBoxLayout()

        self.disable_all_ai = QCheckBox("Disable all AI/LLM features (use Python libraries only)")
        self.disable_all_ai.setChecked(self.settings.get("disable_all_ai", False))
        self.disable_all_ai.toggled.connect(self._on_disable_ai_toggled)
        master_layout.addWidget(self.disable_all_ai)

        ai_mode_note = QLabel(
            "When AI is disabled, features like rephrasing will use lightweight Python libraries\n"
            "(nlpaug, nltk) instead of LLMs. This works on any computer without API costs,\n"
            "but results may be less sophisticated."
        )
        ai_mode_note.setWordWrap(True)
        ai_mode_note.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        master_layout.addWidget(ai_mode_note)

        master_group.setLayout(master_layout)
        layout.addWidget(master_group)

        # Enable/Disable AI Features
        self.ai_features_group = QGroupBox("AI-Powered Features")
        features_layout = QVBoxLayout()

        self.enable_chat = QCheckBox("Enable AI Chat Assistant")
        self.enable_chat.setChecked(self.settings.get("enable_chat", True))
        features_layout.addWidget(self.enable_chat)

        self.enable_character_gen = QCheckBox("Enable AI Character Generation")
        self.enable_character_gen.setChecked(self.settings.get("enable_character_gen", True))
        features_layout.addWidget(self.enable_character_gen)

        self.enable_plot_suggestions = QCheckBox("Enable AI Plot Suggestions")
        self.enable_plot_suggestions.setChecked(self.settings.get("enable_plot_suggestions", True))
        features_layout.addWidget(self.enable_plot_suggestions)

        self.enable_worldbuilding_help = QCheckBox("Enable AI Worldbuilding Assistant")
        self.enable_worldbuilding_help.setChecked(self.settings.get("enable_worldbuilding_help", True))
        features_layout.addWidget(self.enable_worldbuilding_help)

        self.enable_writing_suggestions = QCheckBox("Enable AI Writing Suggestions")
        self.enable_writing_suggestions.setChecked(self.settings.get("enable_writing_suggestions", True))
        features_layout.addWidget(self.enable_writing_suggestions)

        self.enable_grammar_check = QCheckBox("Enable AI Grammar & Style Checking")
        self.enable_grammar_check.setChecked(self.settings.get("enable_grammar_check", True))
        features_layout.addWidget(self.enable_grammar_check)

        self.enable_image_generation = QCheckBox("Enable AI Image Generation")
        self.enable_image_generation.setChecked(self.settings.get("enable_image_generation", True))
        features_layout.addWidget(self.enable_image_generation)

        self.enable_auto_save = QCheckBox("Enable Auto-Save AI Responses")
        self.enable_auto_save.setChecked(self.settings.get("enable_auto_save", True))
        features_layout.addWidget(self.enable_auto_save)

        self.enable_rephrasing = QCheckBox("Enable AI Text Rephrasing")
        self.enable_rephrasing.setChecked(self.settings.get("enable_rephrasing", True))
        features_layout.addWidget(self.enable_rephrasing)

        self.show_craft_tips = QCheckBox("Show craft tips in critique results")
        self.show_craft_tips.setChecked(self.settings.get("show_craft_tips", True))
        self.show_craft_tips.setToolTip(
            "When enabled, critique suggestions include educational explanations "
            "of writing craft principles with before/after examples. "
            "Helpful for learning; turn off for a cleaner critique view."
        )
        features_layout.addWidget(self.show_craft_tips)

        self.ai_features_group.setLayout(features_layout)
        layout.addWidget(self.ai_features_group)

        # Set initial state based on disable_all_ai
        self._on_disable_ai_toggled(self.settings.get("disable_all_ai", False))

        # Writing Analysis Settings
        writing_group = QGroupBox("Writing Analysis")
        writing_layout = QVBoxLayout()

        self.enable_spell_check = QCheckBox("Enable Spell Checking (red underline)")
        self.enable_spell_check.setChecked(self.settings.get("enable_spell_check", True))
        writing_layout.addWidget(self.enable_spell_check)

        self.enable_grammar_check_editor = QCheckBox("Enable Grammar Checking (green underline)")
        self.enable_grammar_check_editor.setChecked(self.settings.get("enable_grammar_check_editor", True))
        writing_layout.addWidget(self.enable_grammar_check_editor)

        self.enable_overuse_check = QCheckBox("Enable Overused Word Detection (blue underline)")
        self.enable_overuse_check.setChecked(self.settings.get("enable_overuse_check", True))
        writing_layout.addWidget(self.enable_overuse_check)

        # Overuse threshold
        overuse_container = QHBoxLayout()
        overuse_label = QLabel("Overuse threshold:")
        overuse_container.addWidget(overuse_label)

        self.overuse_threshold_spin = QSpinBox()
        self.overuse_threshold_spin.setRange(2, 20)
        self.overuse_threshold_spin.setValue(self.settings.get("overuse_threshold", 3))
        self.overuse_threshold_spin.setSuffix(" occurrences")
        overuse_container.addWidget(self.overuse_threshold_spin)
        overuse_container.addStretch()
        writing_layout.addLayout(overuse_container)

        writing_note = QLabel(
            "Writing analysis highlights potential issues in your text:\n"
            "• Spelling errors (red) - Misspelled words with suggestions\n"
            "• Grammar errors (green) - Repeated words, a/an usage, etc.\n"
            "• Overused words (blue) - Words appearing too frequently with synonyms"
        )
        writing_note.setWordWrap(True)
        writing_note.setStyleSheet("color: #6b7280; font-size: 11px; padding: 8px; background-color: #f9fafb; border-radius: 4px;")
        writing_layout.addWidget(writing_note)

        writing_group.setLayout(writing_layout)
        layout.addWidget(writing_group)

        # Rephrasing Settings
        rephrase_group = QGroupBox("Rephrasing Settings")
        rephrase_layout = QFormLayout()

        self.rephrase_model_combo = QComboBox()
        self.rephrase_model_combo.addItems(["Cloud LLM (API)", "Local SLM (No API)"])
        current_rephrase = self.settings.get("rephrase_model", "cloud")
        self.rephrase_model_combo.setCurrentIndex(0 if current_rephrase == "cloud" else 1)
        rephrase_layout.addRow("Default Model:", self.rephrase_model_combo)

        rephrase_info = QLabel(
            "Cloud LLM uses your configured API for fast, high-quality rephrasing.\n"
            "Local SLM runs on your computer (requires ~4GB RAM, first run downloads model)."
        )
        rephrase_info.setWordWrap(True)
        rephrase_info.setStyleSheet("color: #6b7280; font-size: 11px;")
        rephrase_layout.addRow("", rephrase_info)

        rephrase_group.setLayout(rephrase_layout)
        layout.addWidget(rephrase_group)

        # Context Settings
        context_group = QGroupBox("Context & Memory")
        context_layout = QFormLayout()

        self.context_window_spin = QSpinBox()
        self.context_window_spin.setRange(1, 50)
        self.context_window_spin.setValue(self.settings.get("context_window", 10))
        self.context_window_spin.setSuffix(" messages")
        context_layout.addRow("Conversation History:", self.context_window_spin)

        self.enable_project_context = QCheckBox("Include project context in AI queries")
        self.enable_project_context.setChecked(self.settings.get("enable_project_context", True))
        context_layout.addRow("Project Awareness:", self.enable_project_context)

        context_group.setLayout(context_layout)
        layout.addWidget(context_group)

        # Advanced Options
        advanced_group = QGroupBox("Advanced Options")
        advanced_layout = QVBoxLayout()

        self.enable_streaming = QCheckBox("Enable streaming responses (real-time output)")
        self.enable_streaming.setChecked(self.settings.get("enable_streaming", False))
        advanced_layout.addWidget(self.enable_streaming)

        self.enable_fallback = QCheckBox("Auto-fallback to alternative AI if primary fails")
        self.enable_fallback.setChecked(self.settings.get("enable_fallback", True))
        advanced_layout.addWidget(self.enable_fallback)

        self.enable_caching = QCheckBox("Cache AI responses for faster retrieval")
        self.enable_caching.setChecked(self.settings.get("enable_caching", True))
        advanced_layout.addWidget(self.enable_caching)

        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)

        layout.addStretch()

        # Set widget to scroll area and return scroll area
        scroll_area.setWidget(widget)
        return scroll_area

    def _create_language_resources_tab(self) -> QWidget:
        """Create language resources download tab."""
        # Create scroll area wrapper
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # NLTK Resources Group
        nltk_group = QGroupBox("NLTK Language Resources")
        nltk_layout = QVBoxLayout()

        # Description
        nltk_desc = QLabel(
            "NLTK (Natural Language Toolkit) provides dictionaries and models for "
            "advanced text processing features like synonyms, grammar analysis, and more."
        )
        nltk_desc.setWordWrap(True)
        nltk_desc.setStyleSheet("color: #6b7280; font-size: 11px; padding-bottom: 8px;")
        nltk_layout.addWidget(nltk_desc)

        # Resource list with checkboxes
        self.nltk_resource_checkboxes = {}
        for resource in LANGUAGE_RESOURCES:
            if resource.platform == "nltk":
                # Create container for resource
                resource_frame = QFrame()
                resource_frame.setStyleSheet("""
                    QFrame {
                        background-color: #f9fafb;
                        border: 1px solid #e5e7eb;
                        border-radius: 6px;
                        padding: 8px;
                        margin: 2px 0;
                    }
                """)
                resource_layout = QVBoxLayout(resource_frame)
                resource_layout.setContentsMargins(8, 8, 8, 8)
                resource_layout.setSpacing(4)

                # Checkbox with name and size
                checkbox = QCheckBox(f"{resource.display_name} (~{resource.size_mb:.1f} MB)")
                checkbox.setStyleSheet("font-weight: 500;")
                self.nltk_resource_checkboxes[resource.resource_id] = checkbox
                resource_layout.addWidget(checkbox)

                # Description label
                desc_label = QLabel(resource.description)
                desc_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-left: 20px;")
                desc_label.setWordWrap(True)
                resource_layout.addWidget(desc_label)

                # Required for label
                req_label = QLabel(f"Used for: {resource.required_for}")
                req_label.setStyleSheet("color: #4f46e5; font-size: 10px; margin-left: 20px;")
                resource_layout.addWidget(req_label)

                nltk_layout.addWidget(resource_frame)

        # Download buttons row
        button_row = QHBoxLayout()

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all_nltk_resources)
        button_row.addWidget(select_all_btn)

        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self._select_no_nltk_resources)
        button_row.addWidget(select_none_btn)

        button_row.addStretch()

        self.nltk_download_btn = QPushButton("Download Selected")
        self.nltk_download_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        self.nltk_download_btn.clicked.connect(self._download_nltk_resources)
        button_row.addWidget(self.nltk_download_btn)

        nltk_layout.addLayout(button_row)

        # Progress bar (hidden initially)
        self.nltk_progress_bar = QProgressBar()
        self.nltk_progress_bar.setVisible(False)
        self.nltk_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #6366f1;
                border-radius: 3px;
            }
        """)
        nltk_layout.addWidget(self.nltk_progress_bar)

        # Status label
        self.nltk_status_label = QLabel("")
        self.nltk_status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.nltk_status_label.setWordWrap(True)
        nltk_layout.addWidget(self.nltk_status_label)

        nltk_group.setLayout(nltk_layout)
        layout.addWidget(nltk_group)

        # Status Group - Show installed resources
        status_group = QGroupBox("Installed Resources")
        status_layout = QVBoxLayout()

        self.installed_resources_label = QLabel("Checking installed resources...")
        self.installed_resources_label.setWordWrap(True)
        self.installed_resources_label.setStyleSheet("font-size: 11px; padding: 8px;")
        status_layout.addWidget(self.installed_resources_label)

        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self._refresh_installed_resources)
        status_layout.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignLeft)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Info note
        info_note = QLabel(
            "💡 Tip: WordNet is recommended for the thesaurus feature. "
            "Download it to enable synonym lookup when right-clicking on words."
        )
        info_note.setWordWrap(True)
        info_note.setStyleSheet(
            "color: #6b7280; font-size: 11px; padding: 10px; "
            "background-color: #f3f4f6; border-radius: 4px;"
        )
        layout.addWidget(info_note)

        layout.addStretch()

        # Set widget to scroll area and return scroll area
        scroll_area.setWidget(widget)

        # Initial check for installed resources
        self._refresh_installed_resources()

        return scroll_area

    def _select_all_nltk_resources(self):
        """Select all NLTK resource checkboxes."""
        for checkbox in self.nltk_resource_checkboxes.values():
            checkbox.setChecked(True)

    def _select_no_nltk_resources(self):
        """Deselect all NLTK resource checkboxes."""
        for checkbox in self.nltk_resource_checkboxes.values():
            checkbox.setChecked(False)

    def _download_nltk_resources(self):
        """Download selected NLTK resources."""
        # Get selected resources
        selected = [
            resource_id for resource_id, checkbox in self.nltk_resource_checkboxes.items()
            if checkbox.isChecked()
        ]

        if not selected:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select at least one resource to download."
            )
            return

        # Disable UI during download
        self.nltk_download_btn.setEnabled(False)
        self.nltk_progress_bar.setVisible(True)
        self.nltk_progress_bar.setValue(0)
        self.nltk_status_label.setText("Starting download...")

        # Start download worker
        self._nltk_worker = NLTKDownloadWorker(selected)
        self._nltk_worker.progress.connect(self._on_nltk_progress)
        self._nltk_worker.finished.connect(self._on_nltk_finished)
        self._nltk_worker.start()

    def _on_nltk_progress(self, message: str, percent: int):
        """Handle NLTK download progress update."""
        self.nltk_status_label.setText(message)
        if percent >= 0:
            self.nltk_progress_bar.setValue(percent)
        else:
            # Indeterminate progress
            self.nltk_progress_bar.setRange(0, 0)

    def _on_nltk_finished(self, success: bool, message: str):
        """Handle NLTK download completion."""
        self.nltk_download_btn.setEnabled(True)
        self.nltk_progress_bar.setVisible(False)
        self.nltk_progress_bar.setRange(0, 100)

        if success:
            self.nltk_status_label.setText("Download completed successfully!")
            self.nltk_status_label.setStyleSheet("color: #059669; font-size: 11px;")

            # Refresh WordNet availability so thesaurus can use it immediately
            try:
                from src.utils.thesaurus import refresh_wordnet_availability
                wordnet_enabled = refresh_wordnet_availability()
                if wordnet_enabled:
                    message += "\n\nWordNet is now active - synonyms will use enhanced lookup!"
            except Exception:
                pass  # Thesaurus refresh is optional

            QMessageBox.information(self, "Download Complete", message)
        else:
            self.nltk_status_label.setText(f"Download failed: {message[:50]}...")
            self.nltk_status_label.setStyleSheet("color: #dc2626; font-size: 11px;")
            QMessageBox.warning(self, "Download Failed", message)

        # Refresh installed resources display
        self._refresh_installed_resources()

    def _refresh_installed_resources(self):
        """Check and display installed NLTK resources."""
        try:
            import nltk
            installed = []
            not_installed = []

            for resource in LANGUAGE_RESOURCES:
                if resource.platform == "nltk":
                    try:
                        nltk.data.find(f"corpora/{resource.resource_id}")
                        installed.append(resource.display_name)
                    except LookupError:
                        try:
                            nltk.data.find(f"tokenizers/{resource.resource_id}")
                            installed.append(resource.display_name)
                        except LookupError:
                            try:
                                nltk.data.find(f"taggers/{resource.resource_id}")
                                installed.append(resource.display_name)
                            except LookupError:
                                not_installed.append(resource.display_name)

            # Check if thesaurus is using WordNet
            wordnet_status = ""
            try:
                from src.utils.thesaurus import is_wordnet_available
                if is_wordnet_available():
                    wordnet_status = "\n\n🔗 Thesaurus: Using WordNet for enhanced synonyms"
                elif "WordNet" in installed:
                    wordnet_status = "\n\n⚠️ Thesaurus: WordNet installed but not yet active (will activate on next lookup)"
            except Exception:
                pass

            if installed:
                installed_text = f"✓ Installed: {', '.join(installed)}"
            else:
                installed_text = "No NLTK resources installed."

            if not_installed:
                not_installed_text = f"\n✗ Not installed: {', '.join(not_installed)}"
            else:
                not_installed_text = ""

            self.installed_resources_label.setText(installed_text + not_installed_text + wordnet_status)
            self.installed_resources_label.setStyleSheet(
                "font-size: 11px; padding: 8px; background-color: #f9fafb; border-radius: 4px;"
            )

        except ImportError:
            self.installed_resources_label.setText(
                "NLTK is not installed. Install it with: pip install nltk"
            )
            self.installed_resources_label.setStyleSheet(
                "font-size: 11px; padding: 8px; background-color: #fef2f2; "
                "border-radius: 4px; color: #dc2626;"
            )

    def _test_connection(self):
        """Test AI API connections."""
        # Gather current API keys from the form
        providers = {}

        claude_key = self.claude_key_edit.text().strip()
        if claude_key:
            providers["claude"] = (claude_key, self.claude_model_combo.currentText())

        openai_key = self.chatgpt_key_edit.text().strip()
        if openai_key:
            providers["openai"] = (openai_key, self.openai_model_combo.currentText())

        gemini_key = self.gemini_key_edit.text().strip()
        if gemini_key:
            providers["gemini"] = (gemini_key, self.gemini_model_combo.currentText())

        hf_key = self.hf_api_key_edit.text().strip()
        if hf_key:
            providers["huggingface"] = (hf_key, None)

        if not providers:
            QMessageBox.warning(
                self,
                "No API Keys",
                "Please enter at least one API key to test."
            )
            return

        # Show test dialog
        dialog = ConnectionTestDialog(providers, self)
        dialog.exec()

    def accept(self):
        """Save settings and close dialog."""
        # Save GenAI settings separately
        self._save_genai_settings()
        # Call parent accept to close dialog
        super().accept()

    def _update_model_info(self):
        """Update model information display based on selected model."""
        from src.config.genai_config import get_available_image_models
        from src.ai.mlx_utils import can_use_mlx

        model_id = self.image_model_combo.currentData()
        if not model_id:
            return

        # Find model info
        available_models = get_available_image_models()
        model_info = next((m for m in available_models if m.model_id == model_id), None)

        if model_info:
            # Build info text
            info_parts = []
            info_parts.append(f"<b>{model_info.description}</b>")
            info_parts.append(f"Best for: {model_info.best_for}")
            info_parts.append(f"RAM required: {model_info.ram_gb}GB")

            # Platform check
            is_apple_silicon = can_use_mlx()
            if model_info.platform == "apple_silicon" and not is_apple_silicon:
                info_parts.append("⚠️ <span style='color: orange;'>This model requires Apple Silicon (M-series chip)</span>")
            elif model_info.platform == "nvidia" and is_apple_silicon:
                info_parts.append("⚠️ <span style='color: orange;'>This model is optimized for NVIDIA GPUs</span>")
            elif model_info.platform == "apple_silicon" and is_apple_silicon:
                info_parts.append("✅ <span style='color: green;'>Compatible with your Apple Silicon Mac</span>")
            elif model_info.platform == "nvidia":
                info_parts.append("ℹ️ Requires NVIDIA GPU with CUDA support")

            # Special notes for FLUX-2
            if "flux2" in model_id.lower():
                info_parts.append("<br>📝 <b>FLUX-2 requires:</b>")
                info_parts.append("  • HuggingFace account with accepted license")
                info_parts.append("  • HuggingFace token configured")
                info_parts.append(f"  • ~{int(model_info.ram_gb)}GB download on first use")

            self.model_info_label.setText("<br>".join(info_parts))
        else:
            self.model_info_label.setText("Select a model to see details")

    def _download_image_model(self):
        """Download or verify the selected image generation model."""
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog
        from src.config.genai_config import get_available_image_models
        from src.ai.mlx_utils import can_use_mlx

        model_id = self.image_model_combo.currentData()
        if not model_id:
            QMessageBox.warning(self, "No Model Selected", "Please select a model to download.")
            return

        # Find model info
        available_models = get_available_image_models()
        model_info = next((m for m in available_models if m.model_id == model_id), None)

        if not model_info:
            QMessageBox.warning(self, "Model Not Found", "Could not find information for the selected model.")
            return

        # Platform check
        is_apple_silicon = can_use_mlx()
        if model_info.platform == "apple_silicon" and not is_apple_silicon:
            QMessageBox.critical(
                self,
                "Incompatible Hardware",
                f"This model requires Apple Silicon (M-series chip).\n\n"
                f"Your system: {'Apple Silicon' if is_apple_silicon else 'Intel/AMD'}\n"
                f"Required: Apple Silicon"
            )
            return
        elif model_info.platform == "nvidia" and is_apple_silicon:
            result = QMessageBox.question(
                self,
                "Different Hardware",
                f"This model is optimized for NVIDIA GPUs, but you have Apple Silicon.\n\n"
                f"Do you want to continue anyway? (May not work or be slow)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        # Check for FLUX-2 gated model requirements
        if "flux2" in model_id.lower():
            # Check if HF token is configured
            from src.ai.image_generation_agent import ImageGenerationAgent
            agent = ImageGenerationAgent()
            hf_token = agent._get_huggingface_token()

            if not hf_token:
                result = QMessageBox.warning(
                    self,
                    "HuggingFace Token Required",
                    "FLUX-2 models require a HuggingFace token.\n\n"
                    "Steps:\n"
                    "1. Accept FLUX-2 license at:\n"
                    "   https://huggingface.co/black-forest-labs/FLUX.2-klein-9B\n\n"
                    "2. Get your token at:\n"
                    "   https://huggingface.co/settings/tokens\n\n"
                    "3. Enter token in Settings > API Keys tab\n\n"
                    "Continue without token? (Download will likely fail)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if result != QMessageBox.StandardButton.Yes:
                    return

        # Show confirmation
        result = QMessageBox.question(
            self,
            "Download Model",
            f"Download: {model_info.display_name}\n\n"
            f"Size: ~{int(model_info.ram_gb)}GB\n"
            f"Platform: {model_info.platform.replace('_', ' ').title()}\n\n"
            f"This will download the model to HuggingFace cache.\n"
            f"Location: ~/.cache/huggingface/\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        # Trigger download by running a test generation
        progress = QProgressDialog(
            f"Downloading {model_info.display_name}...\n\n"
            f"This may take 10-30 minutes depending on your internet speed.\n"
            f"Model will be cached for future use.\n\n"
            f"Check the console for progress.",
            "Cancel",
            0, 0,
            self
        )
        progress.setWindowTitle("Downloading Model")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            if model_info.platform == "apple_silicon" or (is_apple_silicon and "mflux" in model_id.lower()):
                # Use MFLUX to download
                self._download_mflux_model(model_id, model_info, progress)
            else:
                # Use diffusers/PyTorch to download
                self._download_torch_model(model_id, model_info, progress)

            progress.close()
            QMessageBox.information(
                self,
                "Download Complete",
                f"{model_info.display_name} is ready to use!\n\n"
                f"The model is cached and won't need to be downloaded again."
            )

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self,
                "Download Failed",
                f"Failed to download model:\n\n{str(e)}\n\n"
                f"Check the console for detailed error messages."
            )

    def _download_mflux_model(self, model_id: str, model_info, progress):
        """Download MFLUX model by running a test generation."""
        import subprocess
        import tempfile
        import os
        import sys
        from pathlib import Path

        print("\n" + "=" * 60)
        print(f"[Model Download] Starting download for: {model_id}")
        print("=" * 60)

        # Set HF token if available
        from src.ai.image_generation_agent import ImageGenerationAgent
        agent = ImageGenerationAgent()
        hf_token = agent._get_huggingface_token()
        if hf_token:
            os.environ['HF_TOKEN'] = hf_token
            print("[Model Download] HuggingFace token configured")
        else:
            print("[Model Download] WARNING: No HuggingFace token found (may be required for gated models)")

        # Determine command and model variant
        is_flux2 = "flux2" in model_id.lower()

        if is_flux2:
            cmd_name = "mflux-generate-flux2"
            if "klein-9b" in model_id.lower():
                model_variant = "flux2-klein-9b"
            elif "klein-4b" in model_id.lower():
                model_variant = "flux2-klein-4b"
            else:
                model_variant = "flux2-klein-4b"
        else:
            cmd_name = "mflux-generate"
            if "schnell" in model_id.lower():
                model_variant = "schnell"
            elif "dev" in model_id.lower():
                model_variant = "dev"
            else:
                model_variant = "dev"

        print(f"[Model Download] Model type: {'FLUX-2' if is_flux2 else 'FLUX-1'}")
        print(f"[Model Download] Model variant: {model_variant}")
        print(f"[Model Download] Command: {cmd_name}")

        # Create temp output file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            output_path = tmp.name

        try:
            # Run MFLUX with minimal settings to trigger download
            # Note: FLUX-2 requires minimum 2 steps to avoid division by zero
            min_steps = "2" if is_flux2 else "1"

            cmd = [
                cmd_name,
                "--model", model_variant,
                "--prompt", "test",
                "--steps", min_steps,
                "--seed", "42",
                "--height", "512",
                "--width", "512",
                "--output", output_path
            ]

            if is_flux2:
                cmd.extend(["--guidance", "1.0"])
            else:
                cmd.extend(["--quantize", "4" if "4bit" in model_id else "8"])

            print(f"[Model Download] Expected download size: ~{model_info.vram_gb:.1f} GB")
            print("[Model Download] This may take 10-30 minutes depending on your internet speed")
            print("[Model Download] MFLUX output will stream below:")
            print("-" * 60)

            result = subprocess.run(
                cmd,
                stdout=sys.stdout,  # Stream to console in real-time
                stderr=sys.stderr,  # Stream errors to console in real-time
                text=True,
                timeout=1800  # 30 minute timeout for download
            )

            print("-" * 60)
            if result.returncode != 0:
                print(f"[Model Download] FAILED with return code: {result.returncode}")
                raise Exception(f"MFLUX command failed with return code {result.returncode}")
            else:
                print("[Model Download] SUCCESS! Model downloaded and verified")
                print("=" * 60 + "\n")

        finally:
            # Clean up temp file
            try:
                Path(output_path).unlink(missing_ok=True)
            except:
                pass

    def _download_torch_model(self, model_id: str, model_info, progress):
        """Download PyTorch/Diffusers model."""
        from diffusers import DiffusionPipeline
        import torch

        print("\n" + "=" * 60)
        print(f"[Model Download] Starting download for: {model_id}")
        print("=" * 60)

        # Determine device
        if torch.cuda.is_available():
            device = "cuda"
            dtype = torch.float16
            print("[Model Download] Using CUDA GPU acceleration")
        else:
            device = "cpu"
            dtype = torch.float32
            print("[Model Download] Using CPU (GPU not available)")

        print(f"[Model Download] Expected download size: ~{model_info.vram_gb:.1f} GB")
        print("[Model Download] Downloading model files...")

        # Download model (this caches it)
        pipe = DiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            use_safetensors=True
        )

        print("[Model Download] Model downloaded, loading to device...")
        pipe = pipe.to(device)

        print("[Model Download] Running test generation to verify installation...")
        # Generate a test image to ensure everything works
        generator = torch.Generator(device=device).manual_seed(42)
        _ = pipe(
            prompt="test",
            num_inference_steps=1,
            generator=generator,
            height=512,
            width=512
        ).images[0]

        print("[Model Download] SUCCESS! Model downloaded and verified")
        print("=" * 60 + "\n")

    def _save_genai_settings(self):
        """Save GenAI / Image Generation settings."""
        from src.config.genai_config import get_genai_config

        genai_config = get_genai_config()

        # Map provider combo to value
        provider_map = {0: "local", 1: "claude", 2: "chatgpt", 3: "gemini"}

        genai_config.update_settings({
            "image_generation_enabled": self.enable_image_gen.isChecked(),
            "image_model_id": self.image_model_combo.currentData() or self.image_model_combo.currentText(),
            "use_prompt_enhancement": self.use_prompt_enhancement.isChecked(),
            "prompt_llm_provider": provider_map.get(self.prompt_llm_provider.currentIndex(), "local"),
            "prompt_llm_model_id": self.prompt_llm_model.currentData() or self.prompt_llm_model.currentText(),
            "image_width": self.image_width.value(),
            "image_height": self.image_height.value(),
            "image_num_inference_steps": self.image_steps.value(),
            "image_guidance_scale": self.image_guidance.value(),
            "include_character_context": self.include_char_context.isChecked(),
            "character_prompt_weight": self.char_prompt_weight.value(),
        })

    def get_settings(self) -> dict:
        """Get updated settings."""
        # Map quantization combo to value
        quant_map = {0: "none", 1: "8bit", 2: "4bit"}
        device_map = {0: "auto", 1: "cuda", 2: "mps", 3: "cpu"}
        min_rating_map = {0: "excellent", 1: "good", 2: "all"}

        # Store HF token securely in Windows Credential Manager
        hf_token = self.hf_api_key_edit.text()
        if hf_token:
            cred_manager = get_credential_manager()
            cred_manager.store_huggingface_token(hf_token)

        return {
            # API Keys
            "claude_api_key": self.claude_key_edit.text(),
            "chatgpt_api_key": self.chatgpt_key_edit.text(),
            "gemini_api_key": self.gemini_key_edit.text(),

            # Model Selection
            "default_llm": self.default_llm_combo.currentText().lower(),
            "claude_model": self.claude_model_combo.currentText(),
            "openai_model": self.openai_model_combo.currentText(),
            "gemini_model": self.gemini_model_combo.currentText(),

            # Generation Parameters
            "temperature": self.temperature_slider.value() / 100,
            "max_tokens": self.max_tokens_spin.value(),
            "top_p": self.top_p_slider.value() / 100,

            # Chapter Planning
            "use_local_for_chapter_planning": self.use_local_for_planning.isChecked(),

            # Hugging Face / Local Models
            "enable_local_models": self.enable_local_models.isChecked(),
            # Note: HF token is stored in Windows Credential Manager, not in config file
            "local_model_id": self._get_selected_model_id(),
            "storytelling_model_id": self._get_storytelling_model_id(),
            "reasoning_model_id": self._get_reasoning_model_id(),
            "local_model_quantization": quant_map.get(self.quantization_combo.currentIndex(), "8bit"),
            "local_model_device": device_map.get(self.device_combo.currentIndex(), "auto"),
            "local_model_trust_remote_code": self.trust_remote_code.isChecked(),
            "prefer_local_model": self.prefer_local_model.isChecked(),

            # Critique Model Settings
            "critique_model_source": ["default", "local", "cloud"][self.critique_source_combo.currentIndex()],
            "critique_local_model_id": self.critique_local_combo.currentData() or self.critique_local_combo.currentText(),
            "critique_cloud_provider": ["claude", "chatgpt", "gemini"][self.critique_cloud_combo.currentIndex()],
            "critique_temperature": self.critique_temp_slider.value() / 100,

            # Training Data Collection
            "enable_conversation_collection": self.enable_conversation_collection.isChecked(),
            "auto_prompt_rating": self.auto_prompt_rating.isChecked(),
            "min_collection_rating": min_rating_map.get(self.min_rating_combo.currentIndex(), "good"),
            "collect_character_dev": self.collect_character_dev.isChecked(),
            "collect_worldbuilding": self.collect_worldbuilding.isChecked(),
            "collect_plot": self.collect_plot.isChecked(),
            "collect_writing": self.collect_writing.isChecked(),
            "collect_general": self.collect_general.isChecked(),

            # Features
            "disable_all_ai": self.disable_all_ai.isChecked(),
            "enable_chat": self.enable_chat.isChecked(),
            "enable_character_gen": self.enable_character_gen.isChecked(),
            "enable_plot_suggestions": self.enable_plot_suggestions.isChecked(),
            "enable_worldbuilding_help": self.enable_worldbuilding_help.isChecked(),
            "enable_writing_suggestions": self.enable_writing_suggestions.isChecked(),
            "enable_grammar_check": self.enable_grammar_check.isChecked(),
            "enable_image_generation": self.enable_image_generation.isChecked(),
            "enable_auto_save": self.enable_auto_save.isChecked(),
            "enable_rephrasing": self.enable_rephrasing.isChecked(),
            "show_craft_tips": self.show_craft_tips.isChecked(),
            "enable_spell_check": self.enable_spell_check.isChecked(),
            "enable_grammar_check_editor": self.enable_grammar_check_editor.isChecked(),
            "enable_overuse_check": self.enable_overuse_check.isChecked(),
            "overuse_threshold": self.overuse_threshold_spin.value(),
            "rephrase_model": "cloud" if self.rephrase_model_combo.currentIndex() == 0 else "local",

            # Context Settings
            "context_window": self.context_window_spin.value(),
            "enable_project_context": self.enable_project_context.isChecked(),

            # Advanced Options
            "enable_streaming": self.enable_streaming.isChecked(),
            "enable_fallback": self.enable_fallback.isChecked(),
            "enable_caching": self.enable_caching.isChecked(),

            # Text-to-Speech Settings
            "tts_engine": self.tts_engine_combo.currentData(),
            "tts_rate": self.tts_rate_slider.value(),
            "tts_volume": self.tts_volume_slider.value() / 100,
            "vibevoice_path": self.vibevoice_path_edit.text(),
            "vibevoice_model": self.vibevoice_model_combo.currentData(),
            "vibevoice_voice": self.vibevoice_voice_combo.currentData(),

            # Knowledge Bases
            "britannica_api_key": self.knowledge_widget.get_britannica_key(),
            "enable_knowledge_base": self.knowledge_widget.is_knowledge_enabled(),
        }


class ConnectionTestDialog(QDialog):
    """Dialog for testing and displaying API connection results."""

    def __init__(self, providers: dict, parent=None):
        super().__init__(parent)
        self.providers = providers
        self.results = {}

        self.setWindowTitle("Testing API Connections")
        self.setMinimumSize(450, 300)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<b>Testing API Connections...</b>")
        header.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(header)

        # Results area
        self.results_layout = QVBoxLayout()

        # Create status widgets for each provider
        self.status_widgets = {}
        provider_names = {
            "claude": "Claude (Anthropic)",
            "openai": "OpenAI / ChatGPT",
            "gemini": "Google Gemini",
            "huggingface": "Hugging Face"
        }

        for provider in providers.keys():
            frame = QFrame()
            frame.setFrameStyle(QFrame.Shape.StyledPanel)
            frame.setStyleSheet("QFrame { background-color: #f9fafb; border-radius: 4px; padding: 8px; }")

            frame_layout = QHBoxLayout(frame)
            frame_layout.setContentsMargins(10, 8, 10, 8)

            # Provider name
            name_label = QLabel(provider_names.get(provider, provider.title()))
            name_label.setStyleSheet("font-weight: bold; min-width: 140px;")
            frame_layout.addWidget(name_label)

            # Status indicator
            status_label = QLabel("Testing...")
            status_label.setStyleSheet("color: #6b7280;")
            frame_layout.addWidget(status_label, 1)

            # Store reference
            self.status_widgets[provider] = status_label

            self.results_layout.addWidget(frame)

        layout.addLayout(self.results_layout)

        layout.addStretch()

        # Progress indicator
        self.progress_label = QLabel("Running tests...")
        self.progress_label.setStyleSheet("color: #6b7280; font-style: italic; padding: 10px;")
        layout.addWidget(self.progress_label)

        # Close button (initially disabled)
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

        # Start testing
        self._start_tests()

    def _start_tests(self):
        """Start the API tests in a background thread."""
        self.test_worker = APITestWorker(self.providers)
        self.test_worker.result.connect(self._on_test_result)
        self.test_worker.finished.connect(self._on_tests_complete)
        self.test_worker.start()

    def _on_test_result(self, provider: str, success: bool, message: str):
        """Handle a single test result."""
        self.results[provider] = (success, message)

        if provider in self.status_widgets:
            label = self.status_widgets[provider]
            if success:
                label.setText(f"✓ {message}")
                label.setStyleSheet("color: #059669; font-weight: bold;")
            else:
                label.setText(f"✗ {message}")
                label.setStyleSheet("color: #dc2626;")

    def _on_tests_complete(self):
        """Handle all tests completed."""
        # Count results
        success_count = sum(1 for s, _ in self.results.values() if s)
        total_count = len(self.results)

        if success_count == total_count:
            self.progress_label.setText(f"All {total_count} connections successful!")
            self.progress_label.setStyleSheet("color: #059669; font-weight: bold; padding: 10px;")
        elif success_count > 0:
            self.progress_label.setText(f"{success_count} of {total_count} connections successful")
            self.progress_label.setStyleSheet("color: #d97706; font-weight: bold; padding: 10px;")
        else:
            self.progress_label.setText("All connection tests failed")
            self.progress_label.setStyleSheet("color: #dc2626; font-weight: bold; padding: 10px;")

        self.close_btn.setEnabled(True)
        self.setWindowTitle("Connection Test Results")
