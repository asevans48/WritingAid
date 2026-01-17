"""Settings dialog for API keys and preferences."""

from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QLabel,
    QCheckBox, QSlider, QSpinBox, QDoubleSpinBox, QTabWidget,
    QWidget, QScrollArea, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.config.credential_manager import get_credential_manager


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


# Curated list of verified small language models (updated 2025)
AVAILABLE_MODELS: List[LocalModelInfo] = [
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
        display_name="Gemma 3 (4B)",
        size_gb=8.0,
        description="Google's latest efficient model with strong capabilities",
        ram_required="8GB+",
        best_for="Creative writing, instructions, dialogue",
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
        display_name="Gemma 3 (12B)",
        size_gb=24.0,
        description="Google's high-quality 12B model",
        ram_required="24GB+",
        best_for="Best quality creative writing, complex tasks",
        requires_trust_remote_code=False
    ),

    # === Specialized/Community Models ===
    LocalModelInfo(
        model_id="ToastyPigeon/Gemma-3-Starshine-12B",
        display_name="Gemma 3 Starshine (12B)",
        size_gb=24.0,
        description="Story-focused Gemma 3 merge, excellent for creative writing",
        ram_required="24GB+",
        best_for="Creative fiction, storytelling, novel-like prose",
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
]


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
                from huggingface_hub import snapshot_download, HfFolder
            except ImportError:
                self.finished.emit(False,
                    "huggingface_hub not installed.\n\n"
                    "Install with: pip install huggingface_hub"
                )
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

        # Training Data Collection Tab
        training_tab = self._create_training_data_tab()
        tabs.addTab(training_tab, "📊 Training Data")

        # Text-to-Speech Tab
        tts_tab = self._create_tts_tab()
        tabs.addTab(tts_tab, "🔊 Text-to-Speech")

        # Features Tab
        features_tab = self._create_features_tab()
        tabs.addTab(features_tab, "✨ AI Features")

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

        # Model list
        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(150)
        self.model_list.setMaximumHeight(200)
        self.model_list.currentRowChanged.connect(self._on_model_selected)

        for model in AVAILABLE_MODELS:
            item = QListWidgetItem(f"{model.display_name} - {model.size_gb}GB")
            item.setData(Qt.ItemDataRole.UserRole, model)
            self.model_list.addItem(item)

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

        # Add available models to combo
        for model in AVAILABLE_MODELS:
            self.local_model_combo.addItem(model.display_name, model.model_id)

        # Set current value
        current_model = self.settings.get("local_model_id", "microsoft/Phi-3-mini-4k-instruct")
        self.local_model_combo.setCurrentText(current_model)

        active_layout.addRow("Model:", self.local_model_combo)

        # Quantization
        self.quantization_combo = QComboBox()
        self.quantization_combo.addItems(["None (full precision)", "8-bit (recommended)", "4-bit (low memory)"])
        current_quant = self.settings.get("local_model_quantization", "8bit")
        if current_quant == "4bit":
            self.quantization_combo.setCurrentIndex(2)
        elif current_quant == "8bit":
            self.quantization_combo.setCurrentIndex(1)
        else:
            self.quantization_combo.setCurrentIndex(0)
        active_layout.addRow("Quantization:", self.quantization_combo)

        # Device selection
        self.device_combo = QComboBox()
        self.device_combo.addItems(["Auto", "CUDA (GPU)", "CPU"])
        current_device = self.settings.get("local_model_device", "auto")
        device_map = {"auto": 0, "cuda": 1, "cpu": 2}
        self.device_combo.setCurrentIndex(device_map.get(current_device, 0))
        active_layout.addRow("Device:", self.device_combo)

        # Trust remote code
        self.trust_remote_code = QCheckBox("Trust remote code (required for Phi, Qwen models)")
        self.trust_remote_code.setChecked(self.settings.get("trust_remote_code", True))
        active_layout.addRow("", self.trust_remote_code)

        active_group.setLayout(active_layout)
        layout.addWidget(active_group)

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

    def _check_downloaded_models(self):
        """Check which models are already downloaded."""
        try:
            from huggingface_hub import scan_cache_dir

            cache_info = scan_cache_dir()
            downloaded = []

            for repo in cache_info.repos:
                # Check if it's one of our known models
                for model in AVAILABLE_MODELS:
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
        # User typed a custom model ID
        return self.local_model_combo.currentText()

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
        pass

    def _on_collection_toggled(self, checked: bool):
        """Handle collection toggle."""
        # Could enable/disable related controls
        pass

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

        # Enable/Disable AI Features
        features_group = QGroupBox("AI-Powered Features")
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

        features_group.setLayout(features_layout)
        layout.addWidget(features_group)

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

    def get_settings(self) -> dict:
        """Get updated settings."""
        # Map quantization combo to value
        quant_map = {0: "none", 1: "8bit", 2: "4bit"}
        device_map = {0: "auto", 1: "cuda", 2: "cpu"}
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

            # Hugging Face / Local Models
            "enable_local_models": self.enable_local_models.isChecked(),
            # Note: HF token is stored in Windows Credential Manager, not in config file
            "local_model_id": self._get_selected_model_id(),
            "local_model_quantization": quant_map.get(self.quantization_combo.currentIndex(), "8bit"),
            "local_model_device": device_map.get(self.device_combo.currentIndex(), "auto"),
            "local_model_trust_remote_code": self.trust_remote_code.isChecked(),
            "prefer_local_model": self.prefer_local_model.isChecked(),

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
            "enable_chat": self.enable_chat.isChecked(),
            "enable_character_gen": self.enable_character_gen.isChecked(),
            "enable_plot_suggestions": self.enable_plot_suggestions.isChecked(),
            "enable_worldbuilding_help": self.enable_worldbuilding_help.isChecked(),
            "enable_writing_suggestions": self.enable_writing_suggestions.isChecked(),
            "enable_grammar_check": self.enable_grammar_check.isChecked(),
            "enable_image_generation": self.enable_image_generation.isChecked(),
            "enable_auto_save": self.enable_auto_save.isChecked(),
            "enable_rephrasing": self.enable_rephrasing.isChecked(),
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
