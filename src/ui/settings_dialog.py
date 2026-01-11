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
