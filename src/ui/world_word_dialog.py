"""Dialog for AI-powered world-appropriate word suggestions.

Helps authors find words, terms, or phrases that fit their worldbuilding
context (e.g., a culture's vocabulary, a magic system's terminology,
era-appropriate language).
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QProgressBar, QMessageBox, QLineEdit, QFrame, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


class WorldWordWorker(QThread):
    """Background worker for world-appropriate word generation."""

    finished = pyqtSignal(list)  # List of (suggestion, explanation) tuples
    error = pyqtSignal(str)

    def __init__(self, llm_client, prompt: str, system_prompt: str):
        super().__init__()
        self.llm_client = llm_client
        self.prompt = prompt
        self.system_prompt = system_prompt

    def run(self):
        try:
            response = self.llm_client.generate_text(
                prompt=self.prompt,
                system_prompt=self.system_prompt,
                max_tokens=1500,
                temperature=0.8,
                task_type="world_word"
            )
            # Parse response into suggestions
            suggestions = self._parse_suggestions(response)
            self.finished.emit(suggestions)
        except Exception as e:
            self.error.emit(str(e))

    def _parse_suggestions(self, response: str) -> list:
        """Parse numbered suggestions from the LLM response."""
        suggestions = []
        current_word = None
        current_explanation = []

        for line in response.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            # Match lines like "1. word — explanation" or "1) word - explanation"
            import re
            match = re.match(
                r'^\d+[\.\)]\s*\*{0,2}(.+?)\*{0,2}\s*[-–—:]\s*(.+)$', line
            )
            if match:
                if current_word:
                    suggestions.append((current_word, ' '.join(current_explanation)))
                current_word = match.group(1).strip().strip('"\'`*')
                current_explanation = [match.group(2).strip()]
            elif current_word and line and not re.match(r'^\d+[\.\)]', line):
                current_explanation.append(line)

        if current_word:
            suggestions.append((current_word, ' '.join(current_explanation)))

        return suggestions


class WorldWordDialog(QDialog):
    """Dialog for finding world-appropriate word replacements."""

    def __init__(self, selected_text: str, project=None, parent=None,
                 surrounding_context: tuple = None):
        super().__init__(parent)
        self.selected_text = selected_text
        self.project = project
        self.surrounding_before = surrounding_context[0] if surrounding_context else ""
        self.surrounding_after = surrounding_context[1] if surrounding_context else ""
        self.chosen_replacement: Optional[str] = None
        self.worker: Optional[WorldWordWorker] = None
        self.suggestions: List[tuple] = []

        self._init_ui()
        self._init_llm()

    def _init_ui(self):
        self.setWindowTitle("World-Appropriate Word")
        self.setMinimumSize(500, 400)
        self.resize(600, 500)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # Header
        header = QLabel(f"<b style='font-size: 13pt;'>🌍 World-Appropriate Word</b>")
        main_layout.addWidget(header)

        desc = QLabel(
            "Find a word or phrase that fits your world's cultures, "
            "terminology, or setting."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; font-size: 11px;")
        main_layout.addWidget(desc)

        # Selected word display
        sel_group = QGroupBox("Selected Text")
        sel_layout = QVBoxLayout()
        self.selected_label = QLabel(f'"{selected_text}"')
        self.selected_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 4px;")
        self.selected_label.setWordWrap(True)
        sel_layout.addWidget(self.selected_label)
        sel_group.setLayout(sel_layout)
        main_layout.addWidget(sel_group)

        # Description input
        desc_group = QGroupBox("What are you looking for?")
        desc_layout = QVBoxLayout()
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Describe what you need, e.g.:\n"
            "• A word for 'magic' in this culture's language\n"
            "• A period-appropriate term for this technology\n"
            "• A name for this ritual that fits the faction's style\n"
            "• A more evocative synonym that fits the dark tone"
        )
        self.description_edit.setMaximumHeight(80)
        desc_layout.addWidget(self.description_edit)
        desc_group.setLayout(desc_layout)
        main_layout.addWidget(desc_group)

        # Generate button + progress
        gen_layout = QHBoxLayout()
        self.generate_btn = QPushButton("Generate Suggestions")
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.generate_btn.clicked.connect(self._generate)
        gen_layout.addWidget(self.generate_btn)
        gen_layout.addStretch()
        main_layout.addLayout(gen_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        main_layout.addWidget(self.progress_bar)

        # Suggestions list
        sug_group = QGroupBox("Suggestions")
        sug_layout = QVBoxLayout()

        self.suggestion_list = QListWidget()
        self.suggestion_list.currentRowChanged.connect(self._on_suggestion_selected)
        sug_layout.addWidget(self.suggestion_list)

        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setStyleSheet(
            "color: #4b5563; font-style: italic; padding: 4px; font-size: 11px;"
        )
        sug_layout.addWidget(self.explanation_label)

        sug_group.setLayout(sug_layout)
        main_layout.addWidget(sug_group, stretch=1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.use_btn = QPushButton("Use Selected")
        self.use_btn.setEnabled(False)
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self._use_selected)
        btn_layout.addWidget(self.use_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    def _init_llm(self):
        """Initialize the LLM client."""
        self.llm_client = None
        try:
            from src.config.ai_config import get_ai_config
            from src.ai.llm_client import LLMClient, LLMProvider
            from src.ai.mlx_utils import can_use_mlx

            config = get_ai_config()
            if config.is_ai_disabled():
                return

            settings = config.get_settings()
            provider = settings.get("default_llm", "claude")
            api_key = config.get_api_key(provider)

            if api_key:
                provider_enum = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.CHATGPT,
                    "openai": LLMProvider.CHATGPT,
                    "gemini": LLMProvider.GEMINI,
                }.get(provider, LLMProvider.CLAUDE)

                self.llm_client = LLMClient(
                    provider=provider_enum,
                    api_key=api_key,
                    model=settings.get(f"{provider}_model", None)
                )
            else:
                # Try local model
                if can_use_mlx():
                    default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
                else:
                    default_model = "microsoft/Phi-3-mini-4k-instruct"
                local_model_id = settings.get("local_model_id", default_model)

                if can_use_mlx():
                    self.llm_client = LLMClient(
                        provider=LLMProvider.MLX_LOCAL,
                        model=local_model_id
                    )
                else:
                    self.llm_client = LLMClient(
                        provider=LLMProvider.HUGGINGFACE_LOCAL,
                        model=local_model_id
                    )
        except Exception as e:
            print(f"World word dialog: LLM init failed: {e}")

    def _build_worldbuilding_context(self) -> str:
        """Gather worldbuilding context from the project."""
        if not self.project:
            return ""

        parts = []
        wb = getattr(self.project, 'worldbuilding', None)
        if not wb:
            return ""

        if wb.mythology:
            parts.append(f"MYTHOLOGY: {wb.mythology[:400]}")
        if wb.history:
            parts.append(f"HISTORY: {wb.history[:400]}")
        if wb.politics:
            parts.append(f"POLITICS: {wb.politics[:300]}")

        if wb.cultures:
            culture_parts = []
            for c in wb.cultures[:6]:
                info = f"- {c.name}"
                if hasattr(c, 'description') and c.description:
                    info += f": {c.description[:150]}"
                if hasattr(c, 'languages') and c.languages:
                    info += f" (Languages: {c.languages[:100]})"
                if hasattr(c, 'traditions') and c.traditions:
                    info += f" (Traditions: {c.traditions[:100]})"
                culture_parts.append(info)
            parts.append(f"CULTURES:\n" + "\n".join(culture_parts))

        if wb.magic_systems:
            magic_parts = []
            for m in wb.magic_systems[:4]:
                info = f"- {m.name}"
                if hasattr(m, 'description') and m.description:
                    info += f": {m.description[:150]}"
                if hasattr(m, 'source') and m.source:
                    info += f" (Source: {m.source[:80]})"
                magic_parts.append(info)
            parts.append(f"MAGIC SYSTEMS:\n" + "\n".join(magic_parts))

        if wb.factions:
            faction_parts = []
            for f in wb.factions[:6]:
                info = f"- {f.name}"
                if hasattr(f, 'description') and f.description:
                    info += f": {f.description[:120]}"
                faction_parts.append(info)
            parts.append(f"FACTIONS:\n" + "\n".join(faction_parts))

        if wb.places:
            place_parts = []
            for p in wb.places[:6]:
                info = f"- {p.name}"
                if hasattr(p, 'description') and p.description:
                    info += f": {p.description[:120]}"
                place_parts.append(info)
            parts.append(f"PLACES:\n" + "\n".join(place_parts))

        if wb.technologies:
            tech_parts = []
            for t in wb.technologies[:4]:
                info = f"- {t.name}"
                if hasattr(t, 'description') and t.description:
                    info += f": {t.description[:120]}"
                tech_parts.append(info)
            parts.append(f"TECHNOLOGIES:\n" + "\n".join(tech_parts))

        # Also include custom sections
        if wb.custom_sections:
            for key, val in list(wb.custom_sections.items())[:3]:
                if val:
                    parts.append(f"{key.upper()}: {val[:300]}")

        return "\n\n".join(parts)

    def _generate(self):
        """Generate world-appropriate word suggestions."""
        if not self.llm_client:
            QMessageBox.warning(
                self, "AI Not Available",
                "No AI provider is configured.\n\n"
                "Configure an LLM in Settings → AI Configuration."
            )
            return

        user_description = self.description_edit.toPlainText().strip()
        worldbuilding_ctx = self._build_worldbuilding_context()

        system_prompt = (
            "You are a creative writing assistant specializing in worldbuilding-aware "
            "word choice. The author has a fictional world with specific cultures, "
            "terminology, magic systems, and settings. Your job is to suggest "
            "replacement words or phrases that feel authentic to the world.\n\n"
            "Rules:\n"
            "- Suggest 5-8 options, numbered\n"
            "- Each suggestion should be a single word or short phrase (1-4 words)\n"
            "- Format: NUMBER. SUGGESTION — BRIEF EXPLANATION\n"
            "- Suggestions should range from subtle/grounded to creative/inventive\n"
            "- Consider the surrounding text for tone and flow\n"
            "- If the world has specific cultures or languages, draw from them\n"
            "- If no worldbuilding exists, suggest evocative genre-appropriate words"
        )

        if worldbuilding_ctx:
            system_prompt += f"\n\nWORLDBUILDING CONTEXT:\n{worldbuilding_ctx}"

        # Build the user prompt
        prompt_parts = [
            f'The author wants to replace: "{self.selected_text}"'
        ]
        if user_description:
            prompt_parts.append(f"Author's notes: {user_description}")
        if self.surrounding_before or self.surrounding_after:
            context_snippet = ""
            if self.surrounding_before:
                context_snippet += f"...{self.surrounding_before[-200:]}"
            context_snippet += f" [{self.selected_text}] "
            if self.surrounding_after:
                context_snippet += f"{self.surrounding_after[:200]}..."
            prompt_parts.append(f"Surrounding text: {context_snippet}")

        prompt_parts.append(
            "Suggest world-appropriate replacements. "
            "Include both grounded options and more inventive ones."
        )

        prompt = "\n\n".join(prompt_parts)

        # Start worker
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating...")
        self.progress_bar.setVisible(True)
        self.suggestion_list.clear()
        self.explanation_label.setText("")
        self.use_btn.setEnabled(False)

        self.worker = WorldWordWorker(self.llm_client, prompt, system_prompt)
        self.worker.finished.connect(self._on_suggestions_ready)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_suggestions_ready(self, suggestions: list):
        """Handle generated suggestions."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Suggestions")
        self.suggestions = suggestions

        if not suggestions:
            self.suggestion_list.addItem("(no suggestions generated — try again or add more detail)")
            return

        for word, explanation in suggestions:
            item = QListWidgetItem(word)
            item.setData(Qt.ItemDataRole.UserRole, explanation)
            self.suggestion_list.addItem(item)

        # Select first suggestion
        self.suggestion_list.setCurrentRow(0)

    def _on_error(self, error_msg: str):
        """Handle generation error."""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate Suggestions")
        QMessageBox.warning(self, "Error", f"Failed to generate suggestions:\n\n{error_msg}")

    def _on_suggestion_selected(self, row: int):
        """Handle suggestion selection."""
        if row < 0 or row >= len(self.suggestions):
            self.explanation_label.setText("")
            self.use_btn.setEnabled(False)
            return

        word, explanation = self.suggestions[row]
        self.explanation_label.setText(explanation)
        self.use_btn.setEnabled(True)

    def _use_selected(self):
        """Accept the selected suggestion."""
        row = self.suggestion_list.currentRow()
        if row >= 0 and row < len(self.suggestions):
            self.chosen_replacement = self.suggestions[row][0]
            self.accept()

    def get_replacement(self) -> Optional[str]:
        """Get the chosen replacement word."""
        return self.chosen_replacement
