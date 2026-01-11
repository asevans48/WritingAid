"""Settings dialog for API keys and preferences."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QLabel,
    QCheckBox, QSlider, QSpinBox, QDoubleSpinBox, QTabWidget,
    QWidget, QScrollArea
)
from PyQt6.QtCore import Qt


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

        # Hugging Face API
        hf_api_group = QGroupBox("Hugging Face Inference API")
        hf_api_layout = QFormLayout()

        hf_key_container = QVBoxLayout()
        self.hf_api_key_edit = QLineEdit()
        self.hf_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
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

        self.hf_api_model_edit = QLineEdit()
        self.hf_api_model_edit.setText(self.settings.get("hf_api_model", "mistralai/Mistral-7B-Instruct-v0.2"))
        self.hf_api_model_edit.setPlaceholderText("e.g., mistralai/Mistral-7B-Instruct-v0.2")
        hf_api_layout.addRow("API Model ID:", self.hf_api_model_edit)

        hf_api_group.setLayout(hf_api_layout)
        layout.addWidget(hf_api_group)

        # Local Model Configuration
        local_group = QGroupBox("Local Model Configuration")
        local_layout = QFormLayout()

        self.local_model_edit = QLineEdit()
        self.local_model_edit.setText(self.settings.get("local_model_id", "microsoft/phi-2"))
        self.local_model_edit.setPlaceholderText("e.g., microsoft/phi-2, TinyLlama/TinyLlama-1.1B-Chat-v1.0")
        local_layout.addRow("Model ID:", self.local_model_edit)

        # Recommended models info
        models_info = QLabel(
            "Recommended small models for writing assistance:\n"
            "• microsoft/phi-2 (2.7B) - Good quality, low memory\n"
            "• TinyLlama/TinyLlama-1.1B-Chat-v1.0 - Very fast, 1.1B\n"
            "• mistralai/Mistral-7B-Instruct-v0.2 - High quality, needs 16GB+ VRAM\n"
            "• Qwen/Qwen2-1.5B-Instruct - Good balance\n"
            "• stabilityai/stablelm-2-zephyr-1_6b - Optimized for chat"
        )
        models_info.setWordWrap(True)
        models_info.setStyleSheet("color: #6b7280; font-size: 10px; padding: 8px; background-color: #f9fafb; border-radius: 4px;")
        local_layout.addRow("", models_info)

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
        local_layout.addRow("Quantization:", self.quantization_combo)

        # Device selection
        self.device_combo = QComboBox()
        self.device_combo.addItems(["Auto", "CUDA (GPU)", "CPU"])
        current_device = self.settings.get("local_model_device", "auto")
        device_map = {"auto": 0, "cuda": 1, "cpu": 2}
        self.device_combo.setCurrentIndex(device_map.get(current_device, 0))
        local_layout.addRow("Device:", self.device_combo)

        # Trust remote code
        self.trust_remote_code = QCheckBox("Trust remote code (required for some models like Phi, Qwen)")
        self.trust_remote_code.setChecked(self.settings.get("trust_remote_code", False))
        local_layout.addRow("", self.trust_remote_code)

        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

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

        layout.addStretch()
        scroll_area.setWidget(widget)
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
        pass

    def _on_collection_toggled(self, checked: bool):
        """Handle collection toggle."""
        # Could enable/disable related controls
        pass

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

        features_group.setLayout(features_layout)
        layout.addWidget(features_group)

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
        """Test AI API connection."""
        from PyQt6.QtWidgets import QMessageBox

        # TODO: Implement actual API testing
        QMessageBox.information(
            self,
            "Connection Test",
            "Connection testing will be implemented in the next update.\n\n"
            "For now, please verify your API keys are correct by checking:\n"
            "• Claude: https://console.anthropic.com/\n"
            "• OpenAI: https://platform.openai.com/api-keys\n"
            "• Gemini: https://makersuite.google.com/app/apikey"
        )

    def get_settings(self) -> dict:
        """Get updated settings."""
        # Map quantization combo to value
        quant_map = {0: "none", 1: "8bit", 2: "4bit"}
        device_map = {0: "auto", 1: "cuda", 2: "cpu"}
        min_rating_map = {0: "excellent", 1: "good", 2: "all"}

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
            "huggingface_api_key": self.hf_api_key_edit.text(),
            "hf_api_model": self.hf_api_model_edit.text(),
            "local_model_id": self.local_model_edit.text(),
            "local_model_quantization": quant_map.get(self.quantization_combo.currentIndex(), "8bit"),
            "local_model_device": device_map.get(self.device_combo.currentIndex(), "auto"),
            "trust_remote_code": self.trust_remote_code.isChecked(),
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

            # Context Settings
            "context_window": self.context_window_spin.value(),
            "enable_project_context": self.enable_project_context.isChecked(),

            # Advanced Options
            "enable_streaming": self.enable_streaming.isChecked(),
            "enable_fallback": self.enable_fallback.isChecked(),
            "enable_caching": self.enable_caching.isChecked()
        }
