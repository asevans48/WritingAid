"""Model Hub — single OS-level window for managing loaded local models.

Three jobs:

  1. **Browse** every registered model: trained, built-in pretrained,
     pinned. Filter by kind/family. Same source of truth as the
     Training Studio and Writing Tool — wired through
     ``src.data.model_registry``.

  2. **Load / unload** models, with LRU eviction enforced by
     ``src.ai.model_cache``. The Hub is the only surface that
     directly drives the cache; the Training Studio test step and
     Writing Tool agent suite go through the same cache transparently.

  3. **Test** any loaded model with a small set of agent prompts
     (rephrase / continue / outline / character-from-brief / chat).
     Lets users sanity-check trained outputs side by side with their
     base model before committing them to per-task settings.

  4. **Delete** with full propagation: trained models go through
     ``creativeos_config.delete_trained_model`` (which already
     cascades to per-task settings + on-disk files); pinned ids drop
     from ``pinned_models.json``; built-in entries get added to the
     exclusion list.

The window is a separate top-level QMainWindow rather than a tab in
an existing tool because the user explicitly asked for an OS-level
feature. Future: register the window with the launcher's tool
registry so it has a permanent home in the dock.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QPlainTextEdit, QMessageBox, QSplitter,
    QGroupBox, QFormLayout, QProgressBar, QSizePolicy,
    QApplication,
)

from src.data.model_registry import (
    list_models, find_entry, register_pretrained_id, delete_model,
    KIND_TRAINED, KIND_PRETRAINED_BUILTIN, KIND_PRETRAINED_PINNED,
    ModelEntry,
)
from src.ai.model_cache import get_default_cache


# Agent-prompt presets — what users probe a model with on first load.
# Keep these short so testing isn't a 30-second wait per click; the
# hub renders the first response inline.
_AGENT_PROMPTS = [
    ("Rephrase", "rephrase",
     "Passage:\nShe walked into the room and looked around carefully."),
    ("Continue (voice)", "voice",
     "The cold came down hard that winter, harder than any of them"
     " had reckoned. Old Joel sat by the window watching"),
    ("Plot outline", "plot",
     "A young cartographer discovers their maps predict the future."),
    ("Character profile", "character",
     "An aging stage magician who lost his daughter to a rival's trick."),
    ("Chat", "chat",
     "Suggest three opening lines for a horror story set on a ship."),
]


class _ModelLoadWorker(QThread):
    """Background loader so the UI stays responsive while a model
    swaps in / out of RAM (loads can take 30-60 seconds for 7B+
    models on slower disks)."""
    loaded = pyqtSignal(object, object, str)  # tokenizer, model, entry_id
    failed = pyqtSignal(str, str)             # entry_id, error message
    log = pyqtSignal(str)

    def __init__(self, entry: ModelEntry, parent=None):
        super().__init__(parent)
        self._entry = entry

    def run(self):  # noqa: D401 — Qt slot
        try:
            cache = get_default_cache()
            tok, mdl = cache.get(self._entry)
            self.loaded.emit(tok, mdl, self._entry.id)
        except Exception as e:
            self.failed.emit(self._entry.id, str(e))


class _AgentTestWorker(QThread):
    """Run a single agent-prompt generation against a loaded model."""
    finished_text = pyqtSignal(str, str)   # entry_id, response
    failed = pyqtSignal(str, str)

    def __init__(self, entry: ModelEntry, prompt_text: str,
                 prompt_intent: str, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._prompt_text = prompt_text
        self._prompt_intent = prompt_intent

    def run(self):  # noqa: D401
        try:
            # Validate the entry hasn't been deleted out from under us
            # since the user clicked Run. This catches the race where
            # the Training Studio's manage dialog or another tool
            # removes the model AFTER its tree row was selected — the
            # user gets a clear "model no longer exists" message
            # instead of a confusing "no such file or directory" from
            # PEFT's loader 30 seconds later.
            if self._entry.kind == "trained":
                p = self._entry.path
                if p and not Path(p).exists():
                    self.failed.emit(
                        self._entry.id,
                        "Model directory no longer exists. It may "
                        "have been deleted via another tool. Refresh "
                        "the model list.")
                    return
            cache = get_default_cache()
            tok, mdl = cache.get(self._entry)
            # Match the Training Studio's per-intent instruction
            # mapping so a trained voice/rephrase/plot model sees a
            # familiar prompt shape. Uses chat templates when the
            # tokenizer has one (matches training-time behavior),
            # else Alpaca-with-Input fallback.
            instr, user_input, system = _instruction_for_intent(
                self._prompt_intent, self._prompt_text)
            if getattr(tok, "chat_template", None):
                user_msg = (f"{instr}\n\n{user_input}".strip()
                            if user_input else instr)
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": user_msg})
                prompt = tok.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True)
            else:
                if user_input:
                    prompt = (f"### Instruction:\n{instr}\n\n"
                              f"### Input:\n{user_input}\n\n"
                              f"### Response:\n")
                else:
                    prompt = (f"### Instruction:\n{instr}\n\n"
                              f"### Response:\n")
            # Dispatch on framework: MLX models can't go through
            # transformers' generate(); they need mlx_lm.generate.
            # is_mlx_model() inspects the loaded object's module path
            # so it works for both built-in MLX entries and pinned HF
            # ids that the registry's framework field doesn't know
            # about.
            from src.ai.model_cache import (
                generate_with_continuation,
                mlx_generate_with_continuation,
                is_mlx_model,
            )
            if is_mlx_model(mdl):
                text = mlx_generate_with_continuation(
                    tok, mdl, prompt,
                    max_new_tokens=200,
                    max_continuations=3,
                    max_total_new_tokens=1200,
                    temperature=0.7, top_p=0.9,
                )
            else:
                ids = tok(prompt, return_tensors="pt").to(mdl.device)
                text = generate_with_continuation(
                    tok, mdl, ids,
                    max_new_tokens=200,
                    max_continuations=3,
                    max_total_new_tokens=1200,
                    gen_kwargs=dict(
                        do_sample=True, temperature=0.7, top_p=0.9,
                        repetition_penalty=1.15, no_repeat_ngram_size=4,
                    ),
                )
            self.finished_text.emit(self._entry.id, text.strip())
        except Exception as e:
            self.failed.emit(self._entry.id, str(e))


def _instruction_for_intent(intent: str, passage: str):
    """Mirror the Training Studio's _run_test prompt shaping so a
    user can directly compare Hub output against Studio output.
    Returns (instruction, user_input, system_prompt)."""
    if intent == "voice":
        return ("Continue this passage in the same voice and style "
                "as the author.",
                passage,
                "You write in the voice of the user's chosen author corpus.")
    if intent == "plot":
        return ("Generate a story outline.",
                passage,
                "You are a plot-structure assistant.")
    if intent == "character":
        return ("Generate a complete character profile.",
                passage,
                "You are a character designer.")
    if intent == "chat":
        return (passage, "", "You are a helpful writing assistant.")
    # rephrase
    return ("Rephrase the following passage.",
            f"Passage:\n{passage}",
            "You are a creative writing assistant who rewrites prose "
            "while preserving voice.")


class ModelHubWindow(QMainWindow):
    """The Model Hub OS feature."""

    # Column indices for the registry tree.
    COL_NAME = 0
    COL_KIND = 1
    COL_FAMILY = 2
    COL_SIZE = 3
    COL_LOADED = 4
    COL_INTENT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Local Models Hub")
        self.resize(1100, 720)
        self._build_ui()
        self._refresh_registry()
        self._refresh_loaded_panel()
        # Periodically refresh the "loaded" column + RAM bar so
        # background loads/evictions from other tools surface here.
        self._tick = QTimer(self)
        self._tick.setInterval(2000)
        self._tick.timeout.connect(self._refresh_loaded_panel)
        self._tick.start()
        self._load_worker: Optional[_ModelLoadWorker] = None
        self._test_worker: Optional[_AgentTestWorker] = None

    # ── UI assembly ───────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top bar: filter + register-pin + refresh.
        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Filter:</b>"))
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("All kinds", "")
        self.kind_filter.addItem("✍️ Trained (yours)", KIND_TRAINED)
        self.kind_filter.addItem("📦 Built-in pretrained",
                                 KIND_PRETRAINED_BUILTIN)
        self.kind_filter.addItem("📌 Pinned HF ids",
                                 KIND_PRETRAINED_PINNED)
        self.kind_filter.currentIndexChanged.connect(
            self._refresh_registry)
        top.addWidget(self.kind_filter)

        self.family_filter = QComboBox()
        self.family_filter.setEditable(False)
        self._populate_family_filter()
        self.family_filter.currentIndexChanged.connect(
            self._refresh_registry)
        top.addWidget(self.family_filter)

        top.addStretch()
        self.pin_input = QLineEdit()
        self.pin_input.setPlaceholderText(
            "Pin HuggingFace id (e.g. mistralai/Mistral-7B-Instruct-v0.3)")
        self.pin_input.setMinimumWidth(360)
        top.addWidget(self.pin_input)
        self.pin_btn = QPushButton("📌 Pin")
        self.pin_btn.clicked.connect(self._on_pin_clicked)
        top.addWidget(self.pin_btn)

        self.refresh_btn = QPushButton("⟳ Refresh")
        self.refresh_btn.clicked.connect(self._refresh_registry)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        # Splitter: left = registry tree, right = test panel.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # ── Left: registry tree ─────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.registry_tree = QTreeWidget()
        self.registry_tree.setHeaderLabels(
            ["Model", "Kind", "Family", "Size", "Loaded", "Intent"])
        self.registry_tree.setRootIsDecorated(False)
        self.registry_tree.setAlternatingRowColors(True)
        self.registry_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self.registry_tree.itemSelectionChanged.connect(
            self._on_selection_changed)
        hdr = self.registry_tree.header()
        hdr.setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (self.COL_KIND, self.COL_FAMILY, self.COL_SIZE,
                    self.COL_LOADED, self.COL_INTENT):
            hdr.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.registry_tree, 1)

        # Action row under the tree.
        actions = QHBoxLayout()
        self.load_btn = QPushButton("▶ Load selected")
        self.load_btn.clicked.connect(self._on_load_clicked)
        actions.addWidget(self.load_btn)
        self.unload_btn = QPushButton("⏏ Unload selected")
        self.unload_btn.clicked.connect(self._on_unload_clicked)
        actions.addWidget(self.unload_btn)
        actions.addStretch()
        self.delete_btn = QPushButton("🗑 Delete…")
        self.delete_btn.setStyleSheet("color: #b91c1c;")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        actions.addWidget(self.delete_btn)
        left_layout.addLayout(actions)

        # Loaded summary + RAM bar.
        loaded_box = QGroupBox("Currently loaded")
        loaded_form = QFormLayout(loaded_box)
        self.loaded_label = QLabel("—")
        self.loaded_label.setWordWrap(True)
        loaded_form.addRow("Models:", self.loaded_label)
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setFormat("%v% of cache budget")
        loaded_form.addRow("RAM budget:", self.ram_bar)
        self.unload_all_btn = QPushButton("⏏ Unload all")
        self.unload_all_btn.clicked.connect(self._on_unload_all_clicked)
        loaded_form.addRow("", self.unload_all_btn)
        left_layout.addWidget(loaded_box)
        splitter.addWidget(left)

        # ── Right: test panel ───────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("<b>Test agent on selected model</b>"))

        test_form = QFormLayout()
        self.preset_combo = QComboBox()
        for label, intent, sample in _AGENT_PROMPTS:
            self.preset_combo.addItem(label, (intent, sample))
        self.preset_combo.currentIndexChanged.connect(
            self._on_preset_changed)
        test_form.addRow("Agent:", self.preset_combo)

        self.test_input = QPlainTextEdit()
        self.test_input.setMinimumHeight(120)
        test_form.addRow("Input:", self.test_input)

        right_layout.addLayout(test_form)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run on selected model")
        self.run_btn.setStyleSheet(
            "QPushButton { background-color: #6366f1; color: white; "
            "padding: 6px 14px; border-radius: 5px; font-weight: bold; }")
        self.run_btn.clicked.connect(self._on_run_test_clicked)
        run_row.addWidget(self.run_btn)
        run_row.addStretch()
        right_layout.addLayout(run_row)

        right_layout.addWidget(QLabel("<b>Output</b>"))
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        right_layout.addWidget(self.test_output, 1)

        # Status bar at the bottom of the right panel — the only
        # place loads/test runs report their progress.
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #6b7280; padding: 4px;")
        right_layout.addWidget(self.status_label)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Pre-populate the test input with the first preset.
        self._on_preset_changed(0)

    def _populate_family_filter(self) -> None:
        self.family_filter.clear()
        self.family_filter.addItem("All families", "")
        families = sorted({e.family for e in list_models() if e.family})
        for fam in families:
            self.family_filter.addItem(fam.title(), fam)

    # ── Registry tree ────────────────────────────────────

    def _refresh_registry(self) -> None:
        kind = self.kind_filter.currentData() or ""
        family = self.family_filter.currentData() or ""
        prev_selection = self._selected_entry()
        self.registry_tree.clear()
        kinds = [kind] if kind else None
        entries = list_models(kinds=kinds, family=family)
        loaded_ids = {x["id"] for x in get_default_cache().loaded_summary()}
        for e in entries:
            kind_label = {
                KIND_TRAINED: "✍️ trained",
                KIND_PRETRAINED_BUILTIN: "📦 built-in",
                KIND_PRETRAINED_PINNED: "📌 pinned",
            }.get(e.kind, e.kind)
            size_str = f"{e.size_b}B" if e.size_b else "—"
            loaded_str = "✓" if e.id in loaded_ids else ""
            intent_str = e.intent or ""
            item = QTreeWidgetItem([
                e.display_name, kind_label, e.family or "",
                size_str, loaded_str, intent_str])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.registry_tree.addTopLevelItem(item)
            # Restore previous selection if it survived the filter.
            if prev_selection and prev_selection.id == e.id:
                item.setSelected(True)

    def _selected_entry(self) -> Optional[ModelEntry]:
        items = self.registry_tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    # ── Loaded summary panel ─────────────────────────────

    def _refresh_loaded_panel(self) -> None:
        cache = get_default_cache()
        loaded = cache.loaded_summary()
        if not loaded:
            self.loaded_label.setText(
                "<i style='color:#9ca3af'>(none — load a model from the "
                "list)</i>")
        else:
            lines = []
            for e in loaded:
                ts = datetime.fromtimestamp(e["last_used"]).strftime("%H:%M:%S")
                lines.append(
                    f"<b>{e['id']}</b> &nbsp;"
                    f"<span style='color:#6b7280'>"
                    f"({e['ram_gb']}GB · used {ts})"
                    f"</span>")
            self.loaded_label.setText("<br>".join(lines))
        # RAM bar
        used = cache.current_ram_gb()
        budget = cache._max_ram_gb if hasattr(cache, "_max_ram_gb") else 1.0
        pct = int(min(100, used / max(1.0, budget) * 100))
        self.ram_bar.setValue(pct)
        self.ram_bar.setFormat(
            f"{used:.1f} / {budget:.1f} GB ({pct}%)")
        # Refresh the "loaded" column on the tree without rebuilding
        # the whole list.
        loaded_ids = {e["id"] for e in loaded}
        for i in range(self.registry_tree.topLevelItemCount()):
            item = self.registry_tree.topLevelItem(i)
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            item.setText(self.COL_LOADED,
                         "✓" if entry and entry.id in loaded_ids else "")

    # ── Action handlers ──────────────────────────────────

    def _on_pin_clicked(self) -> None:
        hf_id = self.pin_input.text().strip()
        if not hf_id:
            return
        try:
            register_pretrained_id(hf_id)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid id", str(e))
            return
        self.pin_input.clear()
        self._refresh_registry()
        self._populate_family_filter()
        self._set_status(f"Pinned {hf_id} — added to registry.")

    def _on_load_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(
                self, "Pick a model",
                "Select a row first.")
            return
        if self._load_worker is not None and self._load_worker.isRunning():
            self._set_status("(load already in progress…)")
            return
        self._set_status(
            f"Loading {entry.display_name} (this can take 10-60 seconds)…")
        self.run_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self._load_worker = _ModelLoadWorker(entry, self)
        self._load_worker.loaded.connect(self._on_load_done)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.start()

    def _on_load_done(self, _tok, _mdl, entry_id: str) -> None:
        self._set_status(f"✓ Loaded {entry_id}.")
        self.run_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self._refresh_loaded_panel()

    def _on_load_failed(self, entry_id: str, msg: str) -> None:
        self._set_status(f"⚠ Load failed for {entry_id}: {msg}")
        self.run_btn.setEnabled(True)
        self.load_btn.setEnabled(True)

    def _on_unload_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        cache = get_default_cache()
        if cache.evict(entry):
            self._set_status(f"⏏ Unloaded {entry.display_name}.")
        else:
            self._set_status(
                f"({entry.display_name} wasn't loaded — nothing to unload.)")
        self._refresh_loaded_panel()

    def _on_unload_all_clicked(self) -> None:
        cache = get_default_cache()
        cache.clear()
        self._set_status("⏏ Unloaded all models.")
        self._refresh_loaded_panel()

    def _on_delete_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        # Delete UX differs by kind — make sure the user understands.
        if entry.kind == KIND_TRAINED:
            warning = (
                f"Delete trained model <b>{entry.display_name}</b>?\n\n"
                f"This will:\n"
                f"  • Remove the registry entry\n"
                f"  • Delete the on-disk directory\n"
                f"  • Clear any per-task setting pointing at this model\n\n"
                f"This cannot be undone.")
        elif entry.kind == KIND_PRETRAINED_PINNED:
            warning = (
                f"Unpin <b>{entry.display_name}</b>?\n\n"
                f"This only removes the entry from your pinned list — "
                f"the HF cache (on-disk weights) stays where it is.")
        else:
            warning = (
                f"Hide built-in model <b>{entry.display_name}</b>?\n\n"
                f"This adds the model id to your exclusion list. "
                f"It will disappear from every Training Studio / "
                f"Writing Tool dropdown until you remove the "
                f"exclusion via the Manage Built-in Models dialog.")
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Warning)
        mb.setWindowTitle("Confirm")
        mb.setText(warning)
        mb.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Yes)
        mb.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if mb.exec() != QMessageBox.StandardButton.Yes:
            return

        # Evict from cache first so the on-disk delete doesn't race
        # against a still-loaded model. ``delete_model`` (specifically
        # the trained-model path through ``delete_trained_model``)
        # also evicts the cache as a safety net, so this double-call
        # is intentional belt-and-braces — Hub-driven deletions evict
        # immediately rather than waiting for the cascade.
        cache = get_default_cache()
        cache.evict(entry)
        ok = delete_model(entry.id, kind=entry.kind)
        if not ok:
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not remove {entry.display_name}.")
            return
        # Clear the test panel so the next test run can't accidentally
        # use a stale "Run" click on something that just went away.
        # The user has to re-select a model and re-click Run — same
        # safety contract as freshly opening the Hub.
        self.registry_tree.clearSelection()
        self.test_output.clear()
        self._set_status(f"✓ Removed {entry.display_name}.")
        self._refresh_registry()
        self._populate_family_filter()
        self._refresh_loaded_panel()

    # ── Test runner ──────────────────────────────────────

    def _on_preset_changed(self, idx: int) -> None:
        data = self.preset_combo.currentData()
        if not isinstance(data, tuple) or len(data) != 2:
            return
        _intent, sample = data
        self.test_input.setPlainText(sample)

    def _on_run_test_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(
                self, "Pick a model",
                "Select a model from the list first.")
            return
        if self._test_worker is not None and self._test_worker.isRunning():
            self._set_status("(test already running…)")
            return
        passage = self.test_input.toPlainText().strip()
        if not passage:
            self._set_status("(empty input — type a sample to test)")
            return
        data = self.preset_combo.currentData()
        intent = data[0] if isinstance(data, tuple) else "rephrase"
        self._set_status(
            f"Running {self.preset_combo.currentText()} on "
            f"{entry.display_name}…")
        self.run_btn.setEnabled(False)
        self.test_output.setPlainText("…")
        self._test_worker = _AgentTestWorker(
            entry, passage, intent, self)
        self._test_worker.finished_text.connect(self._on_test_done)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.start()

    def _on_test_done(self, _entry_id: str, response: str) -> None:
        self.test_output.setPlainText(response or "(empty response)")
        self._set_status("✓ Test complete.")
        self.run_btn.setEnabled(True)
        self._refresh_loaded_panel()

    def _on_test_failed(self, _entry_id: str, msg: str) -> None:
        self.test_output.setPlainText(f"Test failed: {msg}")
        self._set_status(f"⚠ {msg}")
        self.run_btn.setEnabled(True)

    def _on_selection_changed(self) -> None:
        # Swap the bottom action button states based on what's
        # selected — a kind-specific delete tooltip helps users
        # understand what each kind's "delete" actually does.
        entry = self._selected_entry()
        if entry is None:
            self.delete_btn.setToolTip("Pick a model first")
            return
        if entry.kind == KIND_TRAINED:
            self.delete_btn.setToolTip(
                "Delete this trained model — removes registry entry, "
                "on-disk dir, and any per-task setting pointing at it.")
        elif entry.kind == KIND_PRETRAINED_PINNED:
            self.delete_btn.setToolTip(
                "Unpin from registry. Local HF cache is not touched.")
        else:
            self.delete_btn.setToolTip(
                "Hide from dropdowns by adding to the exclusion list.")

    # ── Status bar ───────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    # ── Cleanup ──────────────────────────────────────────

    def closeEvent(self, event):
        if self._tick is not None:
            self._tick.stop()
        # Don't unload models on close — other tools (writing tool,
        # training studio) may still be using them. The cache is
        # process-wide; only the launcher's quit hook should clear it.
        super().closeEvent(event)
