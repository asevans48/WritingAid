"""CreativeOS settings dialog — shared LLM config for all tools.

Tools may still keep their own settings dialogs for tool-specific
options (Writing Tool's spell-check, voice, etc.). This dialog only
exposes the OS-wide LLM defaults so users can configure once and have
every tool inherit by default.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QTabWidget, QWidget, QGroupBox,
    QDialogButtonBox,
)

from src.config.creativeos_config import (
    get_creativeos_config, TASK_MODEL_KEYS, TASK_MODEL_LABELS,
)
from src.ui.model_picker_widget import ModelPickerWidget


class CreativeOSSettingsDialog(QDialog):
    """Configure OS-level shared LLM access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CreativeOS Settings")
        self.setMinimumWidth(620)
        self.setMinimumHeight(640)
        self.config = get_creativeos_config()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "These settings apply across every CreativeOS tool. Each tool "
            "can still override them in its own settings if needed.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "color: #6b7280; padding: 8px 12px; "
            "background-color: #f3f4f6; border-radius: 6px;")
        layout.addWidget(intro)

        tabs = QTabWidget()

        # ── Cloud LLM tab ──
        cloud_tab = QWidget()
        cloud_form = QFormLayout(cloud_tab)

        self.disable_cb = QCheckBox(
            "Disable all AI features across CreativeOS")
        self.disable_cb.setChecked(self.config.get("disable_all_ai", False))
        cloud_form.addRow(self.disable_cb)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Claude (Anthropic)", "claude")
        self.provider_combo.addItem("ChatGPT (OpenAI)", "chatgpt")
        self.provider_combo.addItem("Gemini (Google)", "gemini")
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == self.config.get("default_llm", "claude"):
                self.provider_combo.setCurrentIndex(i)
                break
        cloud_form.addRow("Default provider:", self.provider_combo)

        self.claude_key = QLineEdit(self.config.get("claude_api_key", ""))
        self.claude_key.setEchoMode(QLineEdit.EchoMode.Password)
        cloud_form.addRow("Claude API key:", self.claude_key)

        self.openai_key = QLineEdit(self.config.get("chatgpt_api_key", ""))
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        cloud_form.addRow("OpenAI API key:", self.openai_key)

        self.gemini_key = QLineEdit(self.config.get("gemini_api_key", ""))
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        cloud_form.addRow("Gemini API key:", self.gemini_key)

        self.hf_token = QLineEdit(self.config.get("huggingface_token", ""))
        self.hf_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.hf_token.setToolTip(
            "HuggingFace token (for downloading gated models)")
        cloud_form.addRow("HuggingFace token:", self.hf_token)

        self.claude_model = QLineEdit(self.config.get(
            "claude_model", "claude-opus-4-7"))
        cloud_form.addRow("Claude model:", self.claude_model)
        self.openai_model = QLineEdit(self.config.get(
            "openai_model", "gpt-4-turbo-preview"))
        cloud_form.addRow("OpenAI model:", self.openai_model)
        self.gemini_model = QLineEdit(self.config.get(
            "gemini_model", "gemini-pro"))
        cloud_form.addRow("Gemini model:", self.gemini_model)

        tabs.addTab(cloud_tab, "Cloud Models")

        # ── Local model tab ──
        # Wraps a QFormLayout (toggles + model id field) and the shared
        # ModelPickerWidget (catalog + downloader). Selecting a model in
        # the picker writes its id into the Model ID field below, so the
        # one source of truth for "which local model" stays the field.
        local_tab = QWidget()
        local_outer = QVBoxLayout(local_tab)
        local_form_holder = QWidget()
        local_form = QFormLayout(local_form_holder)
        local_form.setContentsMargins(0, 0, 0, 0)

        self.enable_local_cb = QCheckBox("Enable local model support")
        self.enable_local_cb.setChecked(
            self.config.get("enable_local_models", False))
        local_form.addRow(self.enable_local_cb)

        self.prefer_local_cb = QCheckBox(
            "Prefer local model over cloud when both are available")
        self.prefer_local_cb.setChecked(
            self.config.get("prefer_local_model", False))
        local_form.addRow(self.prefer_local_cb)

        self.local_model_id = QLineEdit(self.config.get("local_model_id", ""))
        self.local_model_id.setPlaceholderText(
            "e.g. mlx-community/gemma-4-26b-a4b-it-4bit")
        local_form.addRow("Model ID:", self.local_model_id)

        self.local_device = QComboBox()
        self.local_device.addItems(["auto", "cpu", "cuda", "mps"])
        idx = self.local_device.findText(
            self.config.get("local_model_device", "auto"))
        if idx >= 0:
            self.local_device.setCurrentIndex(idx)
        local_form.addRow("Device:", self.local_device)

        self.local_quant = QComboBox()
        self.local_quant.addItems(["none", "4bit", "8bit"])
        idx = self.local_quant.findText(
            self.config.get("local_model_quantization", "none"))
        if idx >= 0:
            self.local_quant.setCurrentIndex(idx)
        local_form.addRow("Quantization:", self.local_quant)

        # Locally-trained models registered by the Training Studio
        try:
            from src.config.creativeos_config import load_trained_models
            trained = load_trained_models()
        except Exception:
            trained = []
        if trained:
            local_form.addRow(QLabel("<b>Trained models</b> (from Training Studio):"))
            self.trained_combo = QComboBox()
            self.trained_combo.addItem("(none — use Model ID above)", "")
            for m in trained:
                label = f"{m.get('name','?')} — base: {m.get('base_model','?')}"
                self.trained_combo.addItem(label, m.get("path", ""))
            self.trained_combo.setToolTip(
                "Pick a model trained locally via the Training Studio. "
                "Selecting one overrides Model ID at app launch.")
            self.trained_combo.currentIndexChanged.connect(
                self._on_trained_picked)
            local_form.addRow("Use trained model:", self.trained_combo)
        else:
            self.trained_combo = None

        local_outer.addWidget(local_form_holder)

        # Catalog + downloader (Qwen, Gemma, Phi, …). Same widget the
        # Writing Tool exposes — selecting a row fills the Model ID field
        # so the user can pick + save in one step.
        self.model_picker = ModelPickerWidget()
        self.model_picker.model_selected.connect(self.local_model_id.setText)
        # Pre-select whatever model_id is already in settings
        self.model_picker.select_model_by_id(self.local_model_id.text())
        local_outer.addWidget(self.model_picker, 1)

        tabs.addTab(local_tab, "Local Models")

        # ── Per-task model picker ──
        # Lets the user route specific writing-tool tasks (rephrasing,
        # plot, worldbuilding, character generation, general chat) to
        # different trained models. Empty = fall back to the global
        # Model ID / cloud default.
        task_tab = QWidget()
        task_form = QFormLayout(task_tab)

        task_intro = QLabel(
            "Pick a different trained model for each task. Leave a row on "
            "<b>(default)</b> to keep using the global Local Model ID or "
            "your cloud provider. Trained models come from the Model "
            "Training Studio.")
        task_intro.setWordWrap(True)
        task_intro.setStyleSheet("color: #6b7280; padding: 6px;")
        task_form.addRow(task_intro)

        try:
            from src.config.creativeos_config import load_trained_models
            trained_for_tasks = load_trained_models()
        except Exception:
            trained_for_tasks = []

        self.task_combos: dict = {}
        for key in TASK_MODEL_KEYS:
            combo = QComboBox()
            combo.addItem("(default — use global model)", "")
            current = self.config.get(key, "") or ""
            selected_idx = 0
            for i, m in enumerate(trained_for_tasks, start=1):
                name = m.get("name", "?")
                label = f"{name} — base: {m.get('base_model','?')}"
                combo.addItem(label, name)
                if name == current:
                    selected_idx = i
            combo.setCurrentIndex(selected_idx)
            if not trained_for_tasks:
                combo.setEnabled(False)
                combo.setToolTip(
                    "No trained models yet — use the Training Studio first.")
            task_form.addRow(TASK_MODEL_LABELS.get(key, key) + ":", combo)
            self.task_combos[key] = combo

        tabs.addTab(task_tab, "Per-Task Models")

        # ── Data Collection tab (transfer learning) ──
        data_tab = QWidget()
        data_form = QFormLayout(data_tab)

        intro = QLabel(
            "When enabled, accepted rephrase suggestions are stored locally "
            "in <code>~/.creativeos/rephrase_history.db</code>. The Model "
            "Training Studio uses this database to fine-tune a model on "
            "your writing voice. Nothing is sent off your machine.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6b7280; padding: 6px;")
        data_form.addRow(intro)

        self.collect_rephrases_cb = QCheckBox(
            "Collect rephrase queries and responses for transfer learning")
        self.collect_rephrases_cb.setChecked(self.config.get(
            "enable_rephrase_data_collection", False))
        data_form.addRow(self.collect_rephrases_cb)

        self.collect_chat_cb = QCheckBox(
            "Collect AI chat conversations for transfer learning")
        self.collect_chat_cb.setChecked(self.config.get(
            "enable_chat_data_collection", False))
        data_form.addRow(self.collect_chat_cb)

        self.collect_worldbuilding_cb = QCheckBox(
            "Collect worldbuilding generations for transfer learning")
        self.collect_worldbuilding_cb.setChecked(self.config.get(
            "enable_worldbuilding_data_collection", False))
        data_form.addRow(self.collect_worldbuilding_cb)

        self.collect_character_cb = QCheckBox(
            "Collect character generations for transfer learning")
        self.collect_character_cb.setChecked(self.config.get(
            "enable_character_data_collection", False))
        data_form.addRow(self.collect_character_cb)

        self.collect_plot_cb = QCheckBox(
            "Collect plot/outline generations for transfer learning")
        self.collect_plot_cb.setChecked(self.config.get(
            "enable_plot_data_collection", False))
        data_form.addRow(self.collect_plot_cb)

        # Show current count + a quick "Open Training Studio" link
        try:
            from src.data.rephrase_database import get_rephrase_database
            n = get_rephrase_database().count()
        except Exception:
            n = 0
        count_label = QLabel(
            f"Currently collected: <b>{n}</b> rephrase pairs.")
        count_label.setStyleSheet("padding: 4px;")
        data_form.addRow(count_label)

        tabs.addTab(data_tab, "Data Collection")

        layout.addWidget(tabs)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_trained_picked(self, index: int):
        """If the user selects a trained model, fill the Model ID field."""
        if not self.trained_combo:
            return
        path = self.trained_combo.itemData(index) or ""
        if path:
            self.local_model_id.setText(path)

    def _save_and_close(self):
        updates = dict(
            disable_all_ai=self.disable_cb.isChecked(),
            default_llm=self.provider_combo.currentData(),
            claude_api_key=self.claude_key.text().strip(),
            chatgpt_api_key=self.openai_key.text().strip(),
            gemini_api_key=self.gemini_key.text().strip(),
            huggingface_token=self.hf_token.text().strip(),
            claude_model=self.claude_model.text().strip() or "claude-opus-4-7",
            openai_model=self.openai_model.text().strip() or "gpt-4-turbo-preview",
            gemini_model=self.gemini_model.text().strip() or "gemini-pro",
            enable_local_models=self.enable_local_cb.isChecked(),
            prefer_local_model=self.prefer_local_cb.isChecked(),
            local_model_id=self.local_model_id.text().strip(),
            local_model_device=self.local_device.currentText(),
            local_model_quantization=self.local_quant.currentText(),
            enable_rephrase_data_collection=self.collect_rephrases_cb.isChecked(),
            enable_chat_data_collection=self.collect_chat_cb.isChecked(),
            enable_worldbuilding_data_collection=self.collect_worldbuilding_cb.isChecked(),
            enable_character_data_collection=self.collect_character_cb.isChecked(),
            enable_plot_data_collection=self.collect_plot_cb.isChecked(),
        )
        for key, combo in self.task_combos.items():
            updates[key] = combo.currentData() or ""
        self.config.update(**updates)
        self.accept()
