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
    TASK_CLOUD_PROVIDERS, parse_task_model_spec, format_task_model_spec,
    load_trained_models,
)
from src.ui.model_picker_widget import ModelPickerWidget
from src.ui.per_task_model_picker import (
    populate_task_combo, read_task_combo_spec, attach_custom_handler,
)


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
        # ANY model — trained, local HuggingFace / MLX, OR cloud.
        # Each row is a two-combo cascade: a "Source" picker chooses
        # the kind (default / trained / hugging face / mlx / cloud /
        # custom-id) and a "Model" picker chooses within that kind.
        # The serialised form is the spec string parsed by
        # ``creativeos_config.parse_task_model_spec``.
        task_tab = QWidget()
        task_form = QFormLayout(task_tab)

        task_intro = QLabel(
            "Pick any model for each task — trained, local, or cloud. "
            "Leave a row on <b>(default)</b> to keep using the global "
            "Local Model ID or your cloud provider.")
        task_intro.setWordWrap(True)
        task_intro.setStyleSheet("color: #6b7280; padding: 6px;")
        task_form.addRow(task_intro)

        try:
            trained_for_tasks = load_trained_models()
        except Exception:
            trained_for_tasks = []

        # Source kinds shown in the kind combo.
        # (display label, kind_value)
        source_kinds = [
            ("(default — use global)", ""),
            ("Trained model (Training Studio)", "trained"),
            ("Local HuggingFace", "hf"),
            ("Local MLX (Apple Silicon)", "mlx"),
            ("Cloud provider", "cloud"),
            ("Custom (paste any model id)", "local"),
        ]

        # Cache rows so the save path can read them back. Each row
        # holds the kind combo + the value widget(s).
        self.task_rows: dict = {}
        for key in TASK_MODEL_KEYS:
            row_widget, row_state = self._build_task_row(
                key, trained_for_tasks, source_kinds)
            task_form.addRow(
                TASK_MODEL_LABELS.get(key, key) + ":", row_widget)
            self.task_rows[key] = row_state

        # Memory & multi-model controls — sit on the same tab as
        # the per-task pickers because the cap directly governs
        # how many of those task-specific models can be loaded at
        # once. Bumping the cap lets the user keep a rephrase
        # model AND a plot model in RAM simultaneously; lowering
        # it forces single-model-at-a-time operation.
        from PyQt6.QtWidgets import QSpinBox, QFrame
        mem_box = QGroupBox("Memory & multi-model")
        mem_form = QFormLayout(mem_box)

        # Available RAM display so the percentage makes sense.
        avail_gb = 0.0
        try:
            import psutil
            avail_gb = psutil.virtual_memory().available / (1024 ** 3)
        except Exception:
            pass
        mem_intro = QLabel(
            "Both the writing tool's per-task LLM cache AND the "
            "global model cache honour these limits. LRU eviction "
            "drops the least-recently-used model when either cap "
            "is hit.<br>"
            f"<span style='color:#6b7280;font-size:11px;'>"
            f"Detected available RAM at app start: "
            f"<b>{avail_gb:.1f} GB</b></span>")
        mem_intro.setWordWrap(True)
        mem_form.addRow(mem_intro)

        self.max_loaded_models_spin = QSpinBox()
        self.max_loaded_models_spin.setRange(1, 8)
        self.max_loaded_models_spin.setValue(int(
            self.config.get("max_loaded_models", 2) or 2))
        self.max_loaded_models_spin.setToolTip(
            "Hard cap on how many local models can be loaded into "
            "RAM at once. 1 = always one at a time (slow task "
            "switching, minimal RAM); higher = faster switching "
            "between rephrase / plot / character models at the "
            "cost of more memory.")
        mem_form.addRow(
            "Max loaded models:", self.max_loaded_models_spin)

        self.ram_pct_spin = QSpinBox()
        self.ram_pct_spin.setRange(10, 95)
        self.ram_pct_spin.setSuffix(" %")
        self.ram_pct_spin.setValue(int(
            self.config.get("model_cache_ram_pct", 60) or 60))
        self.ram_pct_spin.setToolTip(
            "Soft cap on aggregate model RAM as a percentage of "
            "the system's *available* RAM at app start. When "
            "estimated usage exceeds this the cache evicts even "
            "if max_loaded_models hasn't been hit. 60% leaves "
            "headroom for the OS and other apps.")
        mem_form.addRow("RAM cap (% of available):", self.ram_pct_spin)

        # Live preview of the resulting GB cap so the user sees
        # what the percentage actually means on this machine.
        self._ram_preview_label = QLabel("")
        self._ram_preview_label.setStyleSheet(
            "color:#6b7280;font-size:11px;padding:0 0 0 4px;")

        def _refresh_preview():
            if avail_gb <= 0:
                self._ram_preview_label.setText(
                    "(psutil unavailable — RAM cap will use 16 GB "
                    "fallback)")
                return
            cap_gb = avail_gb * (self.ram_pct_spin.value() / 100.0)
            self._ram_preview_label.setText(
                f"~{cap_gb:.1f} GB cap "
                f"(based on detected available RAM)")
        self.ram_pct_spin.valueChanged.connect(
            lambda _v: _refresh_preview())
        _refresh_preview()
        mem_form.addRow("", self._ram_preview_label)

        task_form.addRow(mem_box)

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
            "Collect plot generations for transfer learning")
        self.collect_plot_cb.setChecked(self.config.get(
            "enable_plot_data_collection", False))
        self.collect_plot_cb.setToolTip(
            "When ON: every plot suggestion you click "
            "‘+ Add to project’ on, and every plot-AI reply you "
            "rate Excellent or Good, is captured as a "
            "(question, answer) training pair in the rephrase "
            "database. The Model Training Studio picks them up "
            "next time you fine-tune. OFF = nothing is recorded.")
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

    def _build_task_row(self, key: str, trained_models: list,
                          source_kinds: list):
        """Build a per-task picker row — single combo over all options.

        Returns ``(QWidget, state_dict)``. The combo is populated from
        the unified ``per_task_model_picker`` helper, which enumerates
        every model the app actually has installed (trained + local
        pretrained + pinned) plus cloud providers, plus a "Custom…"
        escape hatch.

        ``trained_models`` and ``source_kinds`` are unused — kept in
        the signature so the call site doesn't have to change.
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        combo = QComboBox()
        h.addWidget(combo, stretch=1)
        state = populate_task_combo(combo, self.config.get(key, ""))
        combo.currentIndexChanged.connect(
            attach_custom_handler(state, self))
        return row, state

    def _read_task_row_spec(self, state: dict) -> str:
        return read_task_combo_spec(state)

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
        for key, row in self.task_rows.items():
            updates[key] = self._read_task_row_spec(row)
        # Memory & multi-model controls.
        old_max = int(self.config.get("max_loaded_models", 2) or 2)
        old_pct = int(self.config.get("model_cache_ram_pct", 60) or 60)
        new_max = int(self.max_loaded_models_spin.value())
        new_pct = int(self.ram_pct_spin.value())
        updates["max_loaded_models"] = new_max
        updates["model_cache_ram_pct"] = new_pct
        self.config.update(**updates)
        # If the memory caps changed, rebuild the global cache so the
        # new bounds take effect immediately. AgentSuite's task cache
        # re-reads its cap on the next task call so it doesn't need a
        # manual reset here.
        if new_max != old_max or new_pct != old_pct:
            try:
                from src.ai.model_cache import (
                    reload_default_cache_from_settings,
                )
                reload_default_cache_from_settings()
            except Exception:
                pass
        self.accept()
